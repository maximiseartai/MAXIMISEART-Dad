"""Wpisanie raportów z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka (#1227, #1232,
ADR 0028).

Karta „Wpisz raporty z maili” stoi poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, maile daje atrapa
Skrzynki raportów (``FakeInbox``), a hasło aplikacji sprawdza lokalny serwer IMAP (``AtrapaImap``) zamiast Gmaila.
Pierwsze kliknięcie ma okno dni od dziś (dzień wdrożenia), więc zlecenia z Wpisami są z dnia ``ENTERING_NOW``.
Przeszkody kliknięcia (#1232) mają zdania Komunikatów ze speca #1224 (US 44–51).
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

from rozliczenia.intermax_replace import LOCAL_DISK
from rozliczenia.tool_files import REPORT_ENTERING_STATE
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE, ImapInbox, InboxAccess, InboxUnreachable, PasswordRejected

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
    """Gmail odrzuca hasło aplikacji z pliku dostępu: Zatrzymanie do Maksa ze Zgłoszeniem, a samo hasło i adres skrzynki
    nie wychodzą z odczytu skrzynki: nie ma ich w odpowiedziach Centrum, strumieniu zdarzeń, Logach, Zgłoszeniu ani
    dzienniku (US 48)."""

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
    for word in (password, password.replace(" ", ""), "raporty@przyklad.invalid"):
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
    # Bez pliku adresów Wpisanie raportów odmawia startu, zanim zapyta o miejsce „jedno naraz”.
    centrum.tool.configuration.worker_addresses.touch()
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


def _stopped_view(centrum: EnteringCentrum) -> dict[str, Any]:
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "stop", view["result"]
    return view


def _stopped(centrum: EnteringCentrum) -> dict[str, Any]:
    return dict(_stopped_view(centrum)["result"])


def _state(centrum: EnteringCentrum) -> Path:
    return centrum.tool.config / REPORT_ENTERING_STATE


def test_intermax_otwarty_w_excelu_zatrzymuje_klikniecie_zanim_proces_przeczyta_skrzynke(tmp_path: Path) -> None:
    """ADR 0028, US 44: przy INTERMAX otwartym w Excelu tata dostaje Komunikat „Zamknij INTERMAX i kliknij jeszcze
    raz”, a skrzynka raportów nie jest czytana."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    open_in_excel(centrum.register)
    before = _cells(centrum.register)

    result = _stopped(centrum)

    assert result["stop_kind"] == "for_tata"
    [stop] = result["stops"]
    assert (stop["what"], stop["action"].split(". ")[0]) == (
        "INTERMAX jest otwarty w Excelu. INTERMAX nie został zmieniony.",
        "Zamknij INTERMAX i kliknij jeszcze raz",
    )
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


# --- Przeszkody kliknięcia (#1232) --------------------------------------------------------------------------------------


def _conflict_copy(centrum: EnteringCentrum, device: str = "LAPTOP-TATY") -> Path:
    """Kopia konfliktu OneDrive obok INTERMAX: INTERMAX z dopiskiem nazwy komputera, jak ją zostawia OneDrive."""

    copy = centrum.register.with_name(f"{centrum.register.stem}-{device}{centrum.register.suffix}")
    copy.write_bytes(centrum.register.read_bytes())
    return copy


CONFLICT_ACTION = (
    "Otwórz w Excelu INTERMAX i tę kopię, przepisz do INTERMAX zmiany, których w nim brakuje, zapisz go i usuń kopię."
)


def _conflict_note(copy: Path) -> str:
    return f"Obok INTERMAX leży kopia konfliktu OneDrive {copy.name}. {CONFLICT_ACTION} Potem odśwież kartę."


def test_kopia_konfliktu_onedrive_przed_kliknieciem_blokuje_karte_i_zatrzymuje_klikniecie_bez_odczytu_skrzynki(
    tmp_path: Path,
) -> None:
    """US 46: kopia konfliktu OneDrive obok INTERMAX blokuje kartę z instrukcją, a kliknięcie ze starej karty kończy się
    Zatrzymaniem „dla taty” z tą samą instrukcją, zanim proces przeczyta skrzynkę; po usunięciu kopii raport się wpisuje."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    copy = _conflict_copy(centrum)
    before = centrum.register.read_bytes()

    blocked = centrum.setup()
    result = _stopped(centrum)
    copy.unlink()
    unblocked = centrum.setup()
    _finished(centrum)

    assert blocked["blocker"] == _conflict_note(copy)
    assert result["stop_kind"] == "for_tata"
    assert result["stops"] == [
        {
            "what": "Obok INTERMAX leży kopia konfliktu OneDrive, więc maili nie przeczytano. INTERMAX nie został zmieniony.",
            "where": f"plik {copy.name}, folder OneDrive",
            "action": f"{CONFLICT_ACTION} Potem kliknij jeszcze raz.",
        }
    ]
    assert centrum.fake_inbox.days == [ENTERING_NOW.date()], "skrzynka czytana tylko przez kliknięcie bez kopii"
    assert unblocked["blocker"] is None
    assert before != centrum.register.read_bytes()
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana")


def test_kopia_konfliktu_onedrive_po_zapisie_zatrzymuje_dla_taty_z_wpisanymi_raportami_i_blokuje_nastepne_klikniecie(
    tmp_path: Path,
) -> None:
    """US 46: kopia konfliktu, którą OneDrive kładzie obok INTERMAX tuż po podmianie, daje Zatrzymanie „dla taty” z
    instrukcją; raporty i pamięć własnych wpisów są już zapisane (Logi mają liczbę wpisanych komórek), a dopóki kopia
    leży, karta jest zablokowana, a kliknięcie kończy się bez odczytu skrzynki."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    copies: list[Path] = []

    def replace_then_conflict(source: Path, target: Path) -> None:
        LOCAL_DISK.replace(source, target)
        copies.append(_conflict_copy(centrum))

    centrum.disk.replace = replace_then_conflict

    view = _stopped_view(centrum)
    centrum.disk.replace = None
    blocked = centrum.setup()
    again = _stopped(centrum)

    [copy] = copies
    result = view["result"]
    assert result["stop_kind"] == "for_tata"
    assert result["stops"] == [
        {
            "what": (
                "Raporty zostały wpisane, ale obok INTERMAX pojawiła się kopia konfliktu OneDrive: ktoś zmieniał INTERMAX "
                "w tym samym czasie."
            ),
            "where": f"plik {copy.name}, folder OneDrive",
            "action": f"{CONFLICT_ACTION} Dopiero wtedy kliknij jeszcze raz.",
        }
    ]
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana")
    [first] = [logs["report_entering"] for logs in centrum.run_logs() if logs["run_id"] == view["run"]["id"]]
    assert first["written"] == 2
    assert [own["number"] for own in json.loads(_state(centrum).read_text(encoding="utf-8"))["own"]] == ["40000001"] * 2
    assert blocked["blocker"] == _conflict_note(copy)
    assert again["stops"][0]["what"].startswith("Obok INTERMAX leży kopia konfliktu OneDrive")
    assert centrum.fake_inbox.days == [ENTERING_NOW.date()]


@pytest.mark.parametrize(
    ("name", "conflict"),
    [
        pytest.param("{stem}-LAPTOP-TATY{suffix}", True, id="nazwa-komputera-z-lacznikiem"),
        pytest.param("{stem}-DESKTOP-7QK2M1A.XLSX", True, id="rozszerzenie-wielkimi-literami"),
        pytest.param("{lower}-laptop{suffix}", True, id="nazwa-intermax-malymi-literami"),
        pytest.param("{stem}-MacBook Pro{suffix}", True, id="nazwa-komputera-ze-spacja"),
        pytest.param("{stem}-LAPTOP-TATY-2{suffix}", True, id="kolejna-kopia-z-numerem"),
        pytest.param("{stem}-Łódź_1{suffix}", True, id="polskie-litery-i-podkreslenie"),
        pytest.param("{stem} - Kopia{suffix}", False, id="kopia-z-eksploratora"),
        pytest.param("~${stem}{suffix}", False, id="plik-blokady-excela"),
        pytest.param(".{stem}.k2x9{suffix}", False, id="plik-tymczasowy-zapisu"),
        pytest.param("{stem}-{suffix}", False, id="pusty-dopisek"),
        pytest.param("{stem}-LAPTOP {suffix}", False, id="spacja-na-koncu-dopisku"),
        pytest.param("{stem}--LAPTOP{suffix}", False, id="lacznik-na-poczatku-dopisku"),
        pytest.param("{stem}-LAPTOP.TATY{suffix}", False, id="kropka-w-dopisku"),
        pytest.param("{stem}_LAPTOP{suffix}", False, id="podkreslenie-zamiast-lacznika"),
        pytest.param("{stem}-LAPTOP.xlsm", False, id="inne-rozszerzenie"),
        pytest.param("{stem}-LAPTOP{suffix}.tmp", False, id="rozszerzenie-po-rozszerzeniu"),
        pytest.param("ZLECENIA INTERMAX OD 08_11_2021-LAPTOP{suffix}", False, id="krotsza-nazwa-intermax"),
        pytest.param("INNY PLIK-LAPTOP{suffix}", False, id="inny-plik"),
    ],
)
def test_karta_rozpoznaje_kopie_konfliktu_onedrive_po_nazwie_intermax_z_dopiskiem_nazwy_komputera(
    tmp_path: Path, name: str, conflict: bool
) -> None:
    """Kopia konfliktu OneDrive to ``<nazwa INTERMAX>-<nazwa komputera><rozszerzenie>`` obok INTERMAX, bez względu na
    wielkość liter (Microsoft Learn: „Report-JOHNS-SURFACE.txt” dla „Report.txt”); kopia z Eksploratora, plik blokady
    Excela, plik tymczasowy zapisu i inny plik z łącznikiem kopią nie są."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    register = centrum.register
    beside = register.with_name(name.format(stem=register.stem, lower=register.stem.lower(), suffix=register.suffix))
    beside.write_bytes(b"syntetyczny")
    assert REGISTER_NAME == "ZLECENIA INTERMAX OD 08_11_2021-NOWA WERSJA.xlsx"

    blocker = centrum.setup()["blocker"]

    assert blocker == (_conflict_note(beside) if conflict else None)


def test_odmowa_onedrive_przy_zapisie_zostawia_intermax_i_pamiec_wpisow_bajt_w_bajt(tmp_path: Path) -> None:
    """US 45: gdy OneDrive trzyma INTERMAX przy podmianie, zapis odmawia tym samym zdaniem co w Uporządkowaniu, a INTERMAX
    i pamięć własnych wpisów z poprzedniego kliknięcia zostają takie, jak były."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)
    _next_morning(centrum)
    register, state = centrum.register.read_bytes(), _state(centrum).read_bytes()
    centrum.disk.replace, attempts = failing_replace(denied)

    result = _stopped(centrum)

    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_tata",
        "OneDrive jeszcze synchronizuje INTERMAX. INTERMAX nie został zmieniony.",
    )
    assert attempts, "zapis doszedł do podmiany"
    assert (centrum.register.read_bytes(), _state(centrum).read_bytes()) == (register, state)


def _diagnosed(centrum: EnteringCentrum, view: dict[str, Any]) -> None:
    response = centrum.client.post(f"/api/runs/{view['run']['id']}/diagnosis")
    assert response.status_code == 200, response.json()


def _reported(centrum: EnteringCentrum, view: dict[str, Any]) -> None:
    _diagnosed(centrum, view)
    response = centrum.client.post(f"/api/runs/{view['run']['id']}/report")
    assert response.status_code == 200, response.json()


def _issue_texts(surroundings: Surroundings) -> list[str]:
    return [part for issue in surroundings.report_box.sent for part in (issue.title, issue.body, *issue.comments)]


def test_odrzucone_haslo_to_komunikat_do_maksa_ze_zgloszeniem_a_powtorka_komentarzem_w_otwartym_zgloszeniu(
    tmp_path: Path,
) -> None:
    """US 47–48: odrzucone hasło aplikacji daje Komunikat „Skrzynka raportów odrzuciła hasło, Maks musi je odnowić” i
    Zatrzymanie „do Maksa” ze Zgłoszeniem w Skrzynce Zgłoszeń; to samo przy następnym kliknięciu ma ten sam odcisk
    problemu, więc trafia jako komentarz do otwartego Zgłoszenia, a INTERMAX zostaje nietknięty."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path, INTERMAX, PasswordRejected(), surroundings=surroundings)
    before = centrum.register.read_bytes()
    box = surroundings.report_box

    first = _stopped_view(centrum)
    _reported(centrum, first)
    assert box.wait_until(lambda fake: len(fake.sent) == 1)
    again = _stopped_view(centrum)
    _diagnosed(centrum, again)

    assert box.wait_until(lambda fake: bool(fake.sent[0].comments))
    result = first["result"]
    assert (result["stop_kind"], result["diagnosis"]) == ("for_maks", "on_request")
    assert result["stops"] == [
        {
            "what": (
                "Skrzynka raportów odrzuciła hasło, Maks musi je odnowić. Maili nie przeczytano. "
                "INTERMAX nie został zmieniony."
            ),
            "where": "skrzynka raportów w Gmailu",
            "action": "Przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    [issue] = box.sent
    assert "Skrzynka raportów odrzuciła hasło" in issue.body
    assert [comment.splitlines()[0] for comment in issue.comments] == ["## Zgłoszenie wróciło"]
    assert centrum.register.read_bytes() == before


@pytest.mark.parametrize("cause", ["OSError", "TimeoutError", "IMAP4.abort"])
def test_brak_sieci_albo_gmail_bez_odpowiedzi_to_tylko_komunikat_sprobuj_za_chwile_bez_zgloszenia(
    tmp_path: Path, cause: str
) -> None:
    """US 49: gdy Gmail nie odpowiada, tata dostaje Zatrzymanie „dla taty” z „Spróbuj za chwilę”, bez Diagnozy i
    Zgłoszenia, a INTERMAX i pamięć wpisów zostają nietknięte."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path, INTERMAX, InboxUnreachable(cause), surroundings=surroundings)
    before = centrum.register.read_bytes()

    result = _stopped(centrum)

    assert (result["stop_kind"], result["diagnosis"], result["report"]) == ("for_tata", None, None)
    assert result["stops"] == [
        {
            "what": "Nie udało się połączyć ze skrzynką raportów. INTERMAX nie został zmieniony.",
            "where": "skrzynka raportów w Gmailu",
            "action": (
                "Spróbuj za chwilę: sprawdź połączenie z internetem i kliknij jeszcze raz. Jeśli błąd wraca, przekaż ten "
                "komunikat osobie utrzymującej narzędzie."
            ),
        }
    ]
    assert surroundings.report_box.sent == []
    assert centrum.register.read_bytes() == before
    assert not _state(centrum).exists()


@pytest.mark.parametrize(
    ("spoil", "problem"),
    [
        pytest.param(
            lambda addresses: addresses.write_text("wykonawcy: [jan@przyklad.invalid\n", encoding="utf-8"),
            "plik nie jest poprawnym YAML-em",
            id="nieczytelny",
        ),
        pytest.param(
            lambda addresses: addresses.write_text(
                json.dumps({"schema_version": 1, "wykonawcy": {"obcy.login": [JAN]}}), encoding="utf-8"
            ),
            "któryś Wykonawca nie jest w konfiguracji wykonawców",
            id="login-spoza-konfiguracji",
        ),
    ],
)
def test_zly_plik_adresow_to_zatrzymanie_do_maksa_ze_zgloszeniem_bez_adresow_i_loginu(
    tmp_path: Path, spoil: Callable[[Path], object], problem: str
) -> None:
    """US 50: plik adresów, którego nie da się odczytać albo który ma login spoza Konfiguracji wykonawców, daje
    Zatrzymanie „do Maksa” ze Zgłoszeniem bez adresów i loginów z pliku, zanim proces przeczyta skrzynkę."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")], surroundings=surroundings)
    spoil(centrum.tool.configuration.worker_addresses)
    before = centrum.register.read_bytes()

    view = _stopped_view(centrum)
    _reported(centrum, view)

    assert surroundings.report_box.wait_until(lambda fake: len(fake.sent) == 1)
    result = view["result"]
    assert (result["stop_kind"], result["stops"][0]["what"], result["stops"][0]["where"]) == (
        "for_maks",
        f"Nie można użyć adresów Wykonawców: {problem}. INTERMAX nie został zmieniony.",
        "plik adresy-wykonawcow.yaml, folder config",
    )
    texts = _issue_texts(surroundings)
    for secret in (JAN, "jan.testowy", "obcy.login"):
        assert [text for text in texts if secret in text] == [], secret
    assert centrum.fake_inbox.days == []
    assert centrum.register.read_bytes() == before


ACCESS_MISSING = "hasła do skrzynki raportów (plik skrzynka-raportow.txt)"
ADDRESSES_MISSING = "adresów Wykonawców (plik adresy-wykonawcow.yaml)"


@pytest.mark.parametrize(
    ("access", "addresses", "missing"),
    [
        pytest.param("missing", True, ACCESS_MISSING, id="bez-hasla"),
        pytest.param("ready", False, ADDRESSES_MISSING, id="bez-adresow"),
        pytest.param("missing", False, f"{ACCESS_MISSING} i {ADDRESSES_MISSING}", id="bez-obu"),
    ],
)
def test_bez_pliku_hasla_albo_adresow_karta_mowi_czego_brakuje_a_start_jest_odrzucony(
    tmp_path: Path, access: InboxAccess, addresses: bool, missing: str
) -> None:
    """US 51: bez pliku dostępu do skrzynki raportów albo pliku adresów Wykonawców karta mówi, którego brakuje, a start
    jest odrzucony tym samym zdaniem, bez Uruchomienia i bez odczytu skrzynki."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")], access=access)
    if not addresses:
        centrum.tool.configuration.worker_addresses.unlink()
    sentence = f"Wpisanie raportów nie jest jeszcze ustawione: w folderze config brakuje {missing}. Dopisze je Maks."

    setup = centrum.setup()
    started = centrum.start()

    assert setup["blocker"] == sentence
    assert (started.status_code, started.json()) == (409, {"message": sentence})
    assert centrum.fake_inbox.days == []
    assert centrum.run_logs() == []
