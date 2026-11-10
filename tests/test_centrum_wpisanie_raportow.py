"""Wpisanie raportów z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka (#1227, ADR 0028).

Karta „Wpisz raporty z maili” stoi poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, maile daje atrapa
Skrzynki raportów (``FakeInbox``), a hasło aplikacji sprawdza lokalny serwer IMAP (``AtrapaImap``) zamiast Gmaila.
Pierwsze kliknięcie ma okno dni od dziś (dzień wdrożenia), więc zlecenia z Wpisami są z dnia ``ENTERING_NOW``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
import imaplib
import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
import pytest

from rozliczenia.tool_files import REPORT_ENTERING_STATE
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE, ImapInbox

from atrapy.intermax import ADDRESS, CONTRACT_NUMBER, FIRST, HEADERS, LAST, NUMBER, ORDER_SHEET, Intermax, Order
from atrapy.preparation import PERIOD, incomplete_period_rows
from atrapy.skrzynka_raportow import AtrapaImap, FakeInbox
from tests.fixtures.centrum import ToolDirectory, run_events, views_until, write_report_key
from tests.fixtures.centrum_intermax import (
    ENTERING_NOW,
    ENTERING_PERIOD,
    REGISTER_NAME,
    SENDERS,
    EnteringCentrum,
    entering_centrum,
    open_in_excel,
    report,
)
from tests.fixtures.centrum_processes import Surroundings, preparing_centrum
from tests.fixtures.intermax_disk import denied, failing_replace

SUCCESSFUL = FIRST + HEADERS.index("SKUTECZNE")
COMPLETED = FIRST + HEADERS.index("CZYNNOŚCI ZREALIZOWANE")
SUBJECT = "Raport 09.11.2026"
JAN = SENDERS["jan.testowy"]


def _order(day: int, hour: int, worker: str, number: int) -> Order:
    return Order(datetime(2026, 11, day, hour), worker, number, cells=((NUMBER, number),))


# Uporządkowane zlecenia: Jana z 8.11 (sprzed okna) i z 9.11 oraz Anny z 9.11; na dole dwa Surowe zlecenia Jana z 9.11,
# z których drugie stoi pod nagłówkami (pierwszy wiersz wklejenia jest przesunięty, jak z aplikacji).
INTERMAX = Intermax(
    ordered=(
        _order(8, 9, "jan.testowy", 40000010),
        _order(9, 9, "jan.testowy", 40000001),
        _order(9, 11, "anna.kowalska", 40000002),
    ),
    raw=(_order(9, 14, "jan.testowy", 40000003), _order(9, 15, "jan.testowy", 40000004)),
)


def _cells(register: Path) -> dict[int, tuple[object, object]]:
    """``NUMER ZL.`` → ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` każdego wiersza arkusza zleceń z numerem."""

    sheet = load_workbook(register)[ORDER_SHEET]
    found: dict[int, tuple[object, object]] = {}
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, int) and cell.value >= 40000000:
                found[cell.value] = (sheet.cell(cell.row, SUCCESSFUL).value, sheet.cell(cell.row, COMPLETED).value)
    return found


def _finished(centrum: EnteringCentrum) -> dict[str, Any]:
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "finished", view["result"]
    return view


def test_klikniecie_wpisuje_tak_i_czynnosci_raportu_do_pustych_komorek_zlecenia_bez_kopii_intermax(tmp_path: Path) -> None:
    """Kryterium #1227: Wpis z Raportu wykonawcy od adresu z listy trafia do obu komórek jego zlecenia z dnia z tematu,
    zapisem bez Kopii INTERMAX; karta pokazuje liczbę wpisanych, a Historia ma Uruchomienie."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana routera")])
    before = _cells(centrum.register)

    setup = centrum.setup()
    view = _finished(centrum)
    history = centrum.client.get("/api/metrics").json()

    assert setup == {
        "title": "Wpisanie raportów",
        "reminder": "Zapisz i zamknij INTERMAX w Excelu",
        "blocker": None,
        "open_in_excel": [],
        "last": None,
    }
    assert view["result"]["result"] == "OK"
    assert view["run"]["period"] == ENTERING_PERIOD
    assert view["result"]["summary"]["figures"] == [
        {"label": "Wpisane", "value": 1, "unit": "count"},
        {"label": "Problemy", "value": 0, "unit": "count"},
        {"label": "Raporty", "value": 1, "unit": "count"},
    ]
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "wymiana routera")}
    assert not centrum.tool.intermax_copies.exists(), "Wpisanie raportów nie robi Kopii INTERMAX"
    assert sorted(path.name for path in centrum.register.parent.iterdir()) == [REGISTER_NAME]
    assert [row["process_label"] for row in history["runs"] if row["run_id"] == view["run"]["id"]] == ["Wpisanie raportów"]
    assert centrum.setup()["last"]["run"]["id"] == view["run"]["id"]


def test_mail_spoza_listy_adresow_surowe_zlecenie_dnia_i_zlecenie_sprzed_okna_nie_dostaja_niczego(tmp_path: Path) -> None:
    """Wpisanie raportów pisze tylko do uporządkowanych zleceń z dni od dnia wdrożenia: Surowe zlecenie dnia na dole
    INTERMAX i zlecenie sprzed okna zostają puste, tak jak zlecenie z Wpisem od adresu spoza listy adresów."""

    centrum = entering_centrum(
        tmp_path,
        INTERMAX,
        [
            report("obcy@przyklad.invalid", SUBJECT, "40000002 tak wymiana"),
            report(JAN, SUBJECT, "40000004 tak montaż"),
            report(JAN, "Raport 08.11.2026", "40000010 tak montaż"),
        ],
    )
    before = _cells(centrum.register)

    view = _finished(centrum)

    assert _cells(centrum.register) == before
    assert view["result"]["summary"]["figures"][0] == {"label": "Wpisane", "value": 0, "unit": "count"}
    [logs] = centrum.run_logs()
    assert [problem["kind"] for problem in logs["report_entering"]["problems"]] == ["unknown_sender", "unknown_number"]
    assert isinstance(centrum.inbox, FakeInbox)
    assert centrum.inbox.days == [ENTERING_NOW.date()], "skrzynka czytana od dnia wdrożenia, czyli dziś"


def test_logi_maja_wpisy_i_zmiany_bez_adresow_tematow_i_tresci_maili_a_telefon_w_czynnosciach_zamaskowany(
    tmp_path: Path,
) -> None:
    """Logi Wpisania raportów przechodzą przez strażnika Reguły danych: adres nadawcy, temat i treść maila spoza
    Wpisów nie mają w nich żadnego pola (Raport spoza listy adresów nie zostawia w nich swojej treści), a telefon w
    czynnościach jest zamaskowany (ADR 0025, ADR 0028)."""

    activities = "wymiana routera, klient tel. 600 100 200"
    stranger = "obcy@przyklad.invalid"
    later = datetime(2026, 11, 9, 18, 40)
    centrum = entering_centrum(
        tmp_path,
        INTERMAX,
        [report(JAN, SUBJECT, f"40000001 tak {activities}"), report(stranger, SUBJECT, "40000002 nie brak", at=later)],
    )

    _finished(centrum)

    [logs] = centrum.run_logs()
    written = json.dumps(logs, ensure_ascii=False)
    for secret in (JAN, stranger, SUBJECT, "brak", "600 100 200"):
        assert secret not in written, secret
    entering = logs["report_entering"]
    assert [mail["kind"] for mail in entering["mails"]] == ["report", "stranger"]
    assert entering["mails"][0]["entries"][0]["activities"] == "wymiana routera, klient tel. [telefon]"
    assert [change["value"] for change in entering["changes"]] == ["tak", "wymiana routera, klient tel. [telefon]"]
    assert entering["problems"] == [{"kind": "unknown_sender", "mail": entering["mails"][1]["mail"], "day": "2026-11-09"}]
    assert (entering["rollout_before"], entering["rollout"], entering["written"]) == (None, "2026-11-09", 2)
    assert _cells(centrum.register)[40000001] == ("tak", activities), "do INTERMAX trafia pełny Wpis"


@pytest.mark.parametrize(
    ("subject", "fault"),
    [
        pytest.param("Raport bez daty", "no_date", id="bez-daty"),
        pytest.param("Raport z 09.11.2026", "other_text", id="inny-tekst"),
        pytest.param("Raport 09.11", "no_year", id="bez-roku"),
        pytest.param("Raport 09112026", "date_form", id="postac-daty"),
        pytest.param("Raport 09-11-2026", "separator", id="separator"),
        pytest.param("Raport 09.11.226", "year_digits", id="cyfry-roku"),
        pytest.param("Raport 31.11.2026", "not_a_day", id="nie-dzien"),
    ],
)
def test_logi_maja_powod_kazdego_nieczytelnego_tematu_bez_tematu(tmp_path: Path, subject: str, fault: str) -> None:
    """Każdy powód nieczytelnego tematu z rdzenia ma swoje słowo w Logach (mail i problem), a sam temat do Logów nie
    trafia (ADR 0028)."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, subject, "40000001 tak wymiana")])

    _finished(centrum)

    [logs] = centrum.run_logs()
    entering = logs["report_entering"]
    assert [(mail["kind"], mail["fault"]) for mail in entering["mails"]] == [("unreadable", fault)]
    assert [(problem["kind"], problem["fault"]) for problem in entering["problems"]] == [("unreadable_subject", fault)]
    assert subject not in json.dumps(logs, ensure_ascii=False)


def test_logi_maja_kopie_wejscia_z_przeczytanymi_wierszami_bez_adresu_i_numeru_umowy(tmp_path: Path) -> None:
    """Kopia wejścia Wpisania raportów to uporządkowane wiersze z dni okna, które proces przeczytał, z komórkami od A do
    ``UWAGI`` bez ``ADRES`` i ``NUMER UMOWY``; Surowego zlecenia i wiersza sprzed okna w niej nie ma."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])

    _finished(centrum)

    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    [sheet] = copied["sheets"]
    numbers = [row["cells"].get("I") for row in sheet["rows"]]
    columns = {letter for row in sheet["rows"] for letter in row["cells"]}
    assert (copied["name"], sheet["sheet"]) == (REGISTER_NAME, ORDER_SHEET)
    assert numbers == [40000002, 40000001]
    assert columns <= {chr(ord("A") + column - 1) for column in range(1, LAST + 1)} - {"E", "K"}
    assert (ADDRESS, CONTRACT_NUMBER) == (5, 11), "ADRES w E, NUMER UMOWY w K"
    assert "Ulica 40000001" not in json.dumps(logs, ensure_ascii=False)


def test_dziewieciocyfrowy_numer_zlecenia_z_intermax_wychodzi_do_logow_a_numer_z_tresci_maila_jest_pod_straznikiem(
    tmp_path: Path,
) -> None:
    """``NUMER ZL.`` z wiersza INTERMAX może wyjść do Logów (ADR 0025) także z 9 cyframi, które strażnik maskuje jako
    telefon w tekście: pamięć własnych wpisów w Logach drugiego kliknięcia ma go jako liczbę. Numer z treści maila
    zostaje tekstem pod strażnikiem, więc 9 cyfr jest w nim zamaskowane; odtworzenie dostanie to jako granicę (#1233)."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 412345678),), raw=())
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "412345678 tak montaż")])

    first = _finished(centrum)
    second = _finished(centrum)

    logs = {entry["run_id"]: entry["report_entering"] for entry in centrum.run_logs()}
    assert logs[first["run"]["id"]]["written"] == 2
    again = logs[second["run"]["id"]]
    assert [(entry["number"], entry["column"], entry["value"]) for entry in again["memory_before"]] == [
        (412345678, "CZYNNOŚCI ZREALIZOWANE", "montaż"),
        (412345678, "SKUTECZNE", "tak"),
    ]
    assert (again["rollout_before"], again["written"], again["changes"]) == ("2026-11-09", 0, [])
    assert again["mails"][0]["entries"][0]["number"] == "[telefon]"


def test_odrzucone_haslo_skrzynki_raportow_nie_trafia_do_api_strumienia_logow_zgloszenia_ani_dziennika(
    tmp_path: Path,
) -> None:
    """Gmail odrzuca hasło aplikacji z pliku dostępu: Zatrzymanie do Maksa ze Zgłoszeniem, a samo hasło nie wychodzi z
    odczytu skrzynki: nie ma go w odpowiedziach Centrum, strumieniu zdarzeń, Logach, Zgłoszeniu ani dzienniku."""

    password = "qwer tyui opas dfgh"
    tool = ToolDirectory(tmp_path)
    write_report_key(tool, "github_pat_SYNTETYCZNY123")
    (tool.config / INBOX_ACCESS_FILE).write_text(f"raporty@przyklad.invalid\n{password}\n", encoding="utf-8")
    surroundings = Surroundings()
    with AtrapaImap(address="raporty@przyklad.invalid", password="inne haslo aplikacji") as imap:
        centrum = entering_centrum(
            tmp_path,
            INTERMAX,
            surroundings=surroundings,
            inbox=ImapInbox(tool.config, connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port)),
        )
        started = centrum.start()
        events = _events_until_finished(centrum)
    view = events[-1]["view"]
    diagnosis = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis")
    sent = centrum.client.post(f"/api/runs/{view['run']['id']}/report")
    card = centrum.client.get(f"/api/runs/{view['run']['id']}/card")
    box = surroundings.report_box
    assert box.wait_until(lambda fake: bool(fake.issues) and any(issue.comments for issue in fake.background_issues))

    result = view["result"]
    assert (result["stop_kind"], result["stops"][0]["where"]) == ("for_maks", "skrzynka raportów w Gmailu")
    assert sent.json()["state"] in ("sent", "queued")
    seen = [
        started.text,
        json.dumps(events),
        diagnosis.text,
        sent.text,
        card.text,
        json.dumps(centrum.setup()),
        *(json.dumps(logs) for logs in centrum.run_logs()),
        *(part for issue in [*box.issues, *box.background_issues] for part in (issue.title, issue.body, *issue.comments)),
        *(asset.text for archive in box.archives for asset in archive.assets),
        tool.log_path.read_text(encoding="utf-8") if tool.log_path.exists() else "",
    ]
    for word in (password, password.replace(" ", "")):
        assert [text for text in seen if word in text] == [], word


def _events_until_finished(centrum: EnteringCentrum) -> list[dict[str, Any]]:
    events = []
    for event in run_events(centrum.client):
        events.append(event)
        if event["view"]["state"] == "finished":
            return events
    raise AssertionError("Strumień skończył się przed końcem Uruchomienia.")


def test_wpisanie_raportow_nie_startuje_w_trakcie_innego_uruchomienia(tmp_path: Path) -> None:
    """Slot „jedno naraz”: w czasie Uruchomienia, które czeka na Decyzję taty, kliknięcie odmawia i niczego nie czyta."""

    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]

    refused = centrum.client.post("/api/report-entering/run")
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": "abort"})

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa już Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach."
            )
        },
    )


def _stopped(centrum: EnteringCentrum) -> dict[str, Any]:
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "stop", view["result"]
    return dict(view["result"])


def _state(centrum: EnteringCentrum) -> Path:
    return centrum.tool.config / REPORT_ENTERING_STATE


def test_intermax_otwarty_w_excelu_zatrzymuje_klikniecie_zanim_proces_przeczyta_skrzynke(tmp_path: Path) -> None:
    """ADR 0028: przy INTERMAX otwartym w Excelu tata dostaje Komunikat, a skrzynka raportów nie jest czytana."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    open_in_excel(centrum.register)
    before = _cells(centrum.register)

    result = _stopped(centrum)

    assert result["stop_kind"] == "for_tata"
    assert centrum.fake_inbox.days == [], "skrzynka nieczytana"
    assert _cells(centrum.register) == before
    assert not _state(centrum).exists()


def test_odmowa_podmiany_intermax_nie_zapisuje_pamieci_wpisow_ani_dnia_wdrozenia(tmp_path: Path) -> None:
    """Pamięć własnych wpisów i dzień wdrożenia zapisują się tylko po zapisie komórek: po odmowie podmiany (OneDrive
    trzyma INTERMAX) pliku stanu nie ma, więc następne kliknięcie, dzień później, ma okno od swojego dnia."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = _cells(centrum.register)
    centrum.disk.replace, _ = failing_replace(denied)

    result = _stopped(centrum)
    centrum.disk.replace = None
    centrum.moment.append(datetime(2026, 11, 10, 8))
    _finished(centrum)

    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_tata",
        "OneDrive jeszcze synchronizuje INTERMAX. INTERMAX nie został zmieniony.",
    )
    assert centrum.fake_inbox.days == [date(2026, 11, 9), date(2026, 11, 10)]
    assert _cells(centrum.register) == before, "Raport z 9.11 jest sprzed okna drugiego kliknięcia"


def _tata_writes(register: Path, number: int, value: str) -> None:
    """Tata wpisuje ``value`` w ``SKUTECZNE`` zlecenia ``number`` i zapisuje INTERMAX (bez Excela na dysku)."""

    book = load_workbook(register)
    sheet = book[ORDER_SHEET]
    [row] = [cell.row for line in sheet.iter_rows(min_row=2) for cell in line if cell.value == number]
    sheet.cell(row, SUCCESSFUL).value = value
    book.save(register)


def test_zapis_intermax_przez_tate_w_trakcie_odczytu_skrzynki_zostaje_w_intermax(tmp_path: Path) -> None:
    """Proces czyta INTERMAX dopiero po skrzynce raportów, tuż przed zapisem: zapis taty w czasie odczytu Gmaila nie
    przepada przy podmianie INTERMAX."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    centrum.fake_inbox.during = lambda: _tata_writes(centrum.register, 40000002, "nie")

    _finished(centrum)

    cells = _cells(centrum.register)
    assert (cells[40000001], cells[40000002]) == (("tak", "wymiana"), ("nie", None))


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda state: state.write_text("{", encoding="utf-8"), id="zly-json"),
        pytest.param(lambda state: state.mkdir(), id="niedostepny"),
    ],
)
def test_nieczytelna_pamiec_wpisow_to_zatrzymanie_do_maksa_bez_odczytu_skrzynki(
    tmp_path: Path, spoil: Callable[[Path], object]
) -> None:
    """DESIGN §2.3: bez pamięci własnych wpisów narzędzie nie odróżni swojego wpisu od ręcznego, więc plik stanu, którego
    nie da się odczytać, zatrzymuje kliknięcie do Maksa, zamiast liczyć się jak pusta pamięć."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = _cells(centrum.register)
    spoil(_state(centrum))

    result = _stopped(centrum)

    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_maks",
        "Nie można odczytać pamięci wpisanych raportów. INTERMAX nie został zmieniony.",
    )
    assert centrum.fake_inbox.days == []
    assert _cells(centrum.register) == before


def _next_morning(centrum: EnteringCentrum) -> None:
    """Następnego ranka Anna przysyła Raport za 9.11, a Raport Jana z 9.11 dalej jest w skrzynce."""

    centrum.moment.append(datetime(2026, 11, 10, 8))
    centrum.fake_inbox.outcome = [
        report(JAN, SUBJECT, "40000001 tak wymiana"),
        report(SENDERS["anna.kowalska"], SUBJECT, "40000002 tak montaż", at=datetime(2026, 11, 10, 7, 50)),
    ]


def _memory_before(centrum: EnteringCentrum, view: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Pamięć własnych wpisów, z którą zaczęło Uruchomienie ``view``, z jego Logów."""

    [logs] = [entry for entry in centrum.run_logs() if entry["run_id"] == view["run"]["id"]]
    return [(entry["number"], entry["column"], entry["value"]) for entry in logs["report_entering"]["memory_before"]]


JAN_OWN = [(40000001, "CZYNNOŚCI ZREALIZOWANE", "wymiana"), (40000001, "SKUTECZNE", "tak")]
ANNA_OWN = [(40000002, "CZYNNOŚCI ZREALIZOWANE", "montaż"), (40000002, "SKUTECZNE", "tak")]


def test_klikniecie_nastepnego_dnia_czyta_od_dnia_wdrozenia_a_pamiec_wpisow_przechodzi_przez_rdzen(tmp_path: Path) -> None:
    """Okno dni kliknięcia następnego dnia zaczyna się od zapisanego dnia wdrożenia, więc Raport za wczoraj trafia do
    pustych komórek; rdzeń dostaje zapamiętane własne wpisy, więc pamięć po tym kliknięciu dalej ma wpisy z pierwszego."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)
    _next_morning(centrum)

    _finished(centrum)
    third = _finished(centrum)

    assert centrum.fake_inbox.days == [date(2026, 11, 9)] * 3
    assert _cells(centrum.register)[40000002] == ("tak", "montaż")
    assert _memory_before(centrum, third) == JAN_OWN + ANNA_OWN


def test_pamiec_wpisow_niezapisana_czeka_w_centrum_na_nastepne_klikniecie(tmp_path: Path) -> None:
    """Gdy pliku stanu nie da się zapisać, raporty są wpisane z ostrzeżeniem, a pamięć czeka w tej pracy Centrum: drugie
    kliknięcie bierze ją, choć plik dalej jest niedostępny."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    centrum.fake_inbox.during = lambda: _state(centrum).mkdir(exist_ok=True)

    first = _finished(centrum)
    _next_morning(centrum)
    second = _finished(centrum)

    assert [warning["what"] for warning in first["result"]["warnings"]] == [
        "Raporty zostały wpisane, ale nie udało się zapisać pamięci wpisanych raportów."
    ]
    assert _memory_before(centrum, second) == JAN_OWN
    assert centrum.fake_inbox.days == [date(2026, 11, 9)] * 2
