"""Wpisanie raportów z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka (#1227, #1232,
ADR 0028).

Przycisk „Wpisz raporty z maili” na ekranie Raporty stoi poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty,
maile daje atrapa Skrzynki raportów (``FakeInbox``), a hasło aplikacji sprawdza lokalny serwer IMAP (``AtrapaImap``)
zamiast Gmaila.
Pierwsze kliknięcie ma okno dni od dziś (dzień wdrożenia), więc zlecenia z Wpisami są z dnia ``ENTERING_NOW``.
Przeszkody kliknięcia (#1232) mają zdania Komunikatów ze speca #1224 (US 44–51).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import email
from email.message import EmailMessage
import email.policy
import imaplib
import json
from pathlib import Path
import shutil
import smtplib
import threading
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
import pytest

from rozliczenia.intermax_replace import LOCAL_DISK
from rozliczenia.public_holidays import public_holidays
from rozliczenia.tool_files import (
    REMINDERS_FOOTER,
    REMINDERS_RESULT,
    REMINDERS_ROLLOUT,
    REPORT_ENTERING_DECISIONS,
    REPORT_ENTERING_RESULT,
    REPORT_ENTERING_STATE,
)
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxAccess,
    InboxUnreachable,
    MailRefused,
    MailSent,
    PasswordRejected,
)
from rozliczenia.worker_reports import (
    ConflictingVerdicts,
    Login,
    MailId,
    OrderNumber,
    Reminder,
    ReportEntry,
    SenderAddress,
    SentReminder,
    SubjectFault,
    UnknownNumber,
    UnreadableSubject,
    Verdict,
)
from rozliczenia.worker_reports.reasons import reason

from atrapy.intermax import ADDRESS, CONTRACT_NUMBER, FIRST, HEADERS, LAST, NUMBER, ORDER_SHEET, WORKER, Intermax, Order
from atrapy.preparation import PERIOD, incomplete_period_rows
from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, AtrapaSmtp, FakeInbox, FakeMailbox
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access
from tests.fixtures.centrum import ROOT, ToolDirectory, run_events, views_until, write_report_key
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


def _tata_writes(register: Path, number: int, value: str, *, column: int = SUCCESSFUL) -> None:
    """Tata wpisuje ``value`` w kolumnie ``column`` (``SKUTECZNE``) zlecenia ``number`` i zapisuje INTERMAX (bez Excela
    na dysku)."""

    book = load_workbook(register)
    sheet = book[ORDER_SHEET]
    [row] = [cell.row for line in sheet.iter_rows(min_row=2) for cell in line if cell.value == number]
    sheet.cell(row, column).value = value
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
        pytest.param(
            lambda state: [path.write_text("{", encoding="utf-8") for path in (state, state.with_name(REPORT_ENTERING_DECISIONS))],
            id="zly-json-pamieci-i-decyzji",
        ),
    ],
)
def test_nieczytelna_pamiec_wpisow_to_zatrzymanie_do_maksa_bez_odczytu_skrzynki(
    tmp_path: Path, spoil: Callable[[Path], object]
) -> None:
    """DESIGN §2.3: bez pamięci własnych wpisów narzędzie nie odróżni swojego wpisu od ręcznego, więc plik stanu, którego
    nie da się odczytać, zatrzymuje kliknięcie do Maksa, zamiast liczyć się jak pusta pamięć. Przy zepsutych pamięci i
    decyzjach „Zostaw moją” Komunikat nazywa pamięć, bo proces czyta ją pierwszą."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = _cells(centrum.register)
    spoil(_state(centrum))

    result = _stopped(centrum)

    [stop] = result["stops"]
    assert (result["stop_kind"], stop["what"], stop["where"]) == (
        "for_maks",
        "Nie można odczytać pamięci wpisanych raportów. INTERMAX nie został zmieniony.",
        "plik wpisanie-raportow-stan.json, folder config",
    )
    assert centrum.fake_inbox.days == []
    assert _cells(centrum.register) == before


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda decisions: decisions.write_text("{", encoding="utf-8"), id="zly-json"),
        pytest.param(
            lambda decisions: decisions.write_text('{"schema_version": 2, "kept": []}', encoding="utf-8"),
            id="nowsza-wersja",
        ),
        pytest.param(lambda decisions: decisions.mkdir(), id="niedostepny"),
    ],
)
def test_nieczytelny_plik_decyzji_zostaw_moja_zatrzymuje_klikniecie_do_maksa_komunikatem_o_nim_a_nie_o_pamieci(
    tmp_path: Path, spoil: Callable[[Path], object]
) -> None:
    """Bez decyzji „Zostaw moją” różnice, które tata zostawił, wróciłyby, więc plik decyzji, którego nie da się
    odczytać, zatrzymuje kliknięcie do Maksa. Komunikat nazywa plik decyzji i mówi, żeby go nie usuwać, a nie wskazuje
    poprawnej pamięci własnych wpisów: jej „naprawa” skasowałaby własne wpisy i dzień wdrożenia (werdykt #1253)."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)
    memory = _state(centrum).read_bytes()
    before = _cells(centrum.register)
    read = list(centrum.fake_inbox.days)
    spoil(centrum.tool.config / REPORT_ENTERING_DECISIONS)

    result = _stopped(centrum)

    [stop] = result["stops"]
    assert (result["stop_kind"], stop["what"], stop["where"], stop["action"]) == (
        "for_maks",
        "Nie można odczytać decyzji „Zostaw moją”, więc maili nie przeczytano. INTERMAX nie został zmieniony.",
        "plik wpisanie-raportow-decyzje.json, folder config",
        "Nie usuwaj tego pliku: bez niego wrócą różnice, przy których kliknięto „Zostaw moją”. Przekaż ten komunikat "
        "osobie utrzymującej narzędzie.",
    )
    assert (_state(centrum).read_bytes(), centrum.fake_inbox.days, _cells(centrum.register)) == (memory, read, before)


def test_nieczytelny_plik_decyzji_przed_zapisana_pamiecia_wpisow_tez_zatrzymuje_klikniecie_do_maksa(tmp_path: Path) -> None:
    """Decyzja „Zostaw moją” bywa zapisana, zanim pamięć własnych wpisów zapisała się choć raz (pamięć niezapisana po
    kliknięciu), więc plik decyzji czyta się także bez pliku pamięci i zepsuty zatrzymuje kliknięcie do Maksa."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = _cells(centrum.register)
    (centrum.tool.config / REPORT_ENTERING_DECISIONS).write_text("{", encoding="utf-8")

    result = _stopped(centrum)

    [stop] = result["stops"]
    assert (result["stop_kind"], stop["where"]) == ("for_maks", "plik wpisanie-raportow-decyzje.json, folder config")
    assert (_state(centrum).exists(), centrum.fake_inbox.days, _cells(centrum.register)) == (False, [], before)


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


def test_reczna_zmiana_komorki_miedzy_kliknieciami_wygrywa_z_poprawka_a_nietkniety_wlasny_wpis_ja_dostaje(
    tmp_path: Path,
) -> None:
    """Kryterium #1230: po pierwszym kliknięciu tata zmienia w INTERMAX ``SKUTECZNE`` Jana, a rano Jan i Anna przysyłają
    poprawki. Ręczne ``nie`` taty zostaje z różnicą w Logach i w liczbie problemów, a własne wpisy, których nikt nie
    zmienił (opis Jana, oba Anny), dostają poprawkę; pamięć ma po kliknięciu wartości z poprawek bez ręcznej."""

    anna = SENDERS["anna.kowalska"]
    reports = [report(JAN, SUBJECT, "40000001 tak wymiana"), report(anna, SUBJECT, "40000002 tak montaż")]
    centrum = entering_centrum(tmp_path, INTERMAX, reports)
    _finished(centrum)
    _tata_writes(centrum.register, 40000001, "nie")
    centrum.moment.append(datetime(2026, 11, 10, 8))
    centrum.fake_inbox.outcome = [
        *reports,
        report(JAN, SUBJECT, "40000001 tak wymiana gniazda", at=datetime(2026, 11, 10, 7, 40)),
        report(anna, SUBJECT, "40000002 nie klient nieobecny", at=datetime(2026, 11, 10, 7, 45)),
    ]

    second = _finished(centrum)

    cells = _cells(centrum.register)
    assert (cells[40000001], cells[40000002]) == (("nie", "wymiana gniazda"), ("nie", "klient nieobecny"))
    assert second["result"]["summary"]["figures"][:2] == [
        {"label": "Wpisane", "value": 2, "unit": "count"},
        {"label": "Problemy", "value": 1, "unit": "count"},
    ]
    [logs] = [entry for entry in centrum.run_logs() if entry["run_id"] == second["run"]["id"]]
    assert logs["report_entering"]["problems"] == [
        {
            "kind": "manual_difference",
            "cell": {"number": 40000001, "day": "2026-11-09", "worker": "jan.testowy", "column": "SKUTECZNE", "value": "tak"},
            "manual": "nie",
        }
    ]
    own = json.loads(_state(centrum).read_text(encoding="utf-8"))["own"]
    assert sorted((entry["number"], entry["column"], entry["value"]) for entry in own) == [
        ("40000001", "CZYNNOŚCI ZREALIZOWANE", "wymiana gniazda"),
        ("40000002", "CZYNNOŚCI ZREALIZOWANE", "klient nieobecny"),
        ("40000002", "SKUTECZNE", "nie"),
    ]


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


def test_kopia_konfliktu_obok_intermax_otwartego_w_excelu_daje_komunikat_o_kopii(tmp_path: Path) -> None:
    """Spec #1224, kolejność kroków kliknięcia: kopia konfliktu (krok 2) przed blokadą Excela (krok 3), bo po zamknięciu
    INTERMAX kopia dalej by zatrzymała kliknięcie; tata najpierw przepisuje zmiany z kopii w Excelu."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    copy = _conflict_copy(centrum)
    open_in_excel(centrum.register)

    result = _stopped(centrum)

    assert (result["stop_kind"], result["stops"][0]["where"]) == ("for_tata", f"plik {copy.name}, folder OneDrive")
    assert centrum.fake_inbox.days == []


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
        pytest.param("{stem}-Jan’s MacBook Air{suffix}", True, id="nazwa-maca-z-apostrofem-typograficznym"),
        pytest.param("{stem}-Jan's MacBook Air{suffix}", True, id="nazwa-maca-z-apostrofem-prostym"),
        pytest.param("{stem}-’LAPTOP{suffix}", False, id="apostrof-na-poczatku-dopisku"),
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
    wielkość liter (Microsoft Learn: „Report-JOHNS-SURFACE.txt” dla „Report.txt”), także z domyślną nazwą Maca z
    apostrofem („Jan’s MacBook Air”); kopia z Eksploratora, plik blokady Excela, plik tymczasowy zapisu i inny plik z
    łącznikiem kopią nie są."""

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


def test_nieczytelny_plik_hasla_to_nie_brak_pliku_karta_bez_blokady_a_klikniecie_zatrzymuje_do_maksa_bez_odczytu_skrzynki(
    tmp_path: Path,
) -> None:
    """Plik dostępu do skrzynki raportów, który jest, ale nie da się go odczytać, to nie brak pliku (US 51): karta nie
    jest zablokowana zdaniem o brakującym haśle, a kliknięcie kończy się Zatrzymaniem „do Maksa” w Sprawdzaniu, zanim
    proces przeczyta skrzynkę."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")], access="unreadable")
    before = _cells(centrum.register)

    setup = centrum.setup()
    result = _stopped(centrum)

    assert setup["blocker"] is None
    [stop] = result["stops"]
    assert (result["stop_kind"], stop["what"]) == (
        "for_maks",
        "Nie można odczytać ustawień skrzynki raportów, więc maili nie przeczytano. INTERMAX nie został zmieniony.",
    )
    assert centrum.fake_inbox.days == []
    assert _cells(centrum.register) == before


def test_intermax_w_folderze_ktorego_juz_nie_ma_zatrzymuje_klikniecie_dla_taty_bez_odczytu_skrzynki(tmp_path: Path) -> None:
    """INTERMAX z Ustawień taty w folderze, którego już nie ma (OneDrive przeniósł albo tata usunął folder): karta
    działa bez blokady kopii konfliktu, a kliknięcie kończy się Zatrzymaniem „dla taty” o brakującym INTERMAX."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    shutil.rmtree(centrum.register.parent)

    setup = centrum.setup()
    result = _stopped(centrum)

    assert setup["blocker"] is None
    assert (result["stop_kind"], result["stops"][0]["what"]) == ("for_tata", "Nie znaleziono INTERMAX. INTERMAX nie został zmieniony.")
    assert centrum.fake_inbox.days == []


# --- Dopasowanie Wpisów do zleceń i zakres maili kliknięcia (#1229) ---------------------------------------------------

ANNA = SENDERS["anna.kowalska"]
MONDAY_PERIOD = "03_09_11_2026"


def _entering(centrum: EnteringCentrum, view: dict[str, Any]) -> dict[str, Any]:
    """Wpisanie raportów w Logach Uruchomienia ``view``."""

    [logs] = [entry for entry in centrum.run_logs() if entry["run_id"] == view["run"]["id"]]
    return dict(logs["report_entering"])


def _copied_numbers(centrum: EnteringCentrum, view: dict[str, Any]) -> list[object]:
    """``NUMER ZL.`` wierszy INTERMAX w Kopii wejścia Uruchomienia ``view``, po kolei."""

    [logs] = [entry for entry in centrum.run_logs() if entry["run_id"] == view["run"]["id"]]
    return [row["cells"].get("I") for copied in logs["input_copy"] for sheet in copied["sheets"] for row in sheet["rows"]]


def _click_at(centrum: EnteringCentrum, moment: datetime, mails: list[Any]) -> dict[str, Any]:
    centrum.moment.append(moment)
    centrum.fake_inbox.outcome = mails
    return _finished(centrum)


def test_pomylka_wykonawcy_w_numerze_albo_dniu_daje_problem_z_powodem_a_wpis_trafia_tylko_do_zlecenia_nadawcy_z_dnia(
    tmp_path: Path,
) -> None:
    """US 27–30: numer zlecenia Jana z 8.11 w Raporcie z 9.11 i numer spoza zleceń dają problemy z obiema datami i
    numerem, a Wpis Anny do zlecenia Jana przegrywa ze świeższym mailem Jana (ADR 0029); wpisuje się tylko Wpis Jana do
    jego zlecenia z 9.11."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = _cells(centrum.register)

    view = _click_at(
        centrum,
        ENTERING_NOW,
        [
            report(ANNA, SUBJECT, "40000001 tak montaż", at=datetime(2026, 11, 9, 17)),
            report(JAN, SUBJECT, "40000010 tak wymiana gniazda"),
            report(JAN, SUBJECT, "30000077 tak wymiana modemu"),
            report(JAN, SUBJECT, "40000001 tak wymiana routera"),
        ],
    )

    assert _cells(centrum.register) == {**before, 40000001: ("tak", "wymiana routera")}
    problems = _entering(centrum, view)["problems"]
    assert [
        (problem["kind"], problem["worker"], problem["number"], problem["owner"], problem["order_days"])
        for problem in problems
    ] == [
        ("unknown_number", "jan.testowy", "30000077", None, []),
        ("other_day", "jan.testowy", "40000010", None, ["2026-11-08"]),
    ]
    assert {problem["day"] for problem in problems} == {"2026-11-09"}
    assert view["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 2, "unit": "count"}


def test_ten_sam_numer_dwa_razy_u_wykonawcy_w_jednym_dniu_niczego_nie_wpisuje(tmp_path: Path) -> None:
    """US 31: dwa uporządkowane wiersze Jana z numerem 40000001 i dniem 9.11 zostają puste, a problem mówi o numerze."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 13, "jan.testowy", 40000001)), raw=())
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    sheet = load_workbook(centrum.register)[ORDER_SHEET]
    rows = [cell.row for line in sheet.iter_rows(min_row=2) for cell in line if cell.value == 40000001]

    view = _finished(centrum)

    after = load_workbook(centrum.register)[ORDER_SHEET]
    assert len(rows) == 2
    assert [(after.cell(row, SUCCESSFUL).value, after.cell(row, COMPLETED).value) for row in rows] == [(None, None)] * 2
    entering = _entering(centrum, view)
    assert [(problem["kind"], problem["number"]) for problem in entering["problems"]] == [("repeated_order", "40000001")]
    assert (entering["changes"], entering["written"]) == ([], 0)


def test_raport_z_adresu_spoza_listy_wpisuje_sie_przy_nastepnym_kliknieciu_po_dopisaniu_adresu(tmp_path: Path) -> None:
    """US 15–16: Raport z poprawnym tematem z nowego adresu Jana daje problem nieznanego nadawcy; Maks dopisuje adres do
    pliku adresów i następne kliknięcie wpisuje ten sam mail bez innej pracy."""

    new_address = "jan.nowy@przyklad.invalid"
    centrum = entering_centrum(tmp_path, INTERMAX, [report(new_address, SUBJECT, "40000001 tak wymiana routera")])
    before = _cells(centrum.register)

    first = _finished(centrum)
    listed = {"jan.testowy": [JAN, new_address], "anna.kowalska": [ANNA]}
    centrum.tool.configuration.worker_addresses.write_text(
        json.dumps({"schema_version": 1, "wykonawcy": listed}, ensure_ascii=False), encoding="utf-8"
    )
    second = _finished(centrum)

    assert [problem["kind"] for problem in _entering(centrum, first)["problems"]] == ["unknown_sender"]
    assert _entering(centrum, second)["problems"] == []
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "wymiana routera")}
    assert new_address not in json.dumps(centrum.run_logs(), ensure_ascii=False)


@pytest.mark.parametrize(
    "month",
    [
        pytest.param(Path(), id="folder-okresow-plaski"),
        pytest.param(Path("Rozliczenia 2026") / "11_Listopad_2026" / "INEA", id="uklad-folderow-taty"),
    ],
)
def test_raport_z_ostatniego_dnia_okresu_wpisuje_sie_w_nowym_okresie_dopoki_okres_nie_ma_pliku_zbiorczego(
    tmp_path: Path, month: Path
) -> None:
    """US 11–12 i 42: we wtorek 10.11 kliknięcie wpisuje Raport Jana z poniedziałku 9.11, bo okres 03_09_11_2026 nie ma
    Pliku zbiorczego. Gdy tata go przygotuje, kliknięcie nie czyta już dni tego okresu: Raport Anny z 9.11 się nie
    wpisuje, skrzynka jest czytana od dziś, a Kopia wejścia ma wiersze INTERMAX od pierwszego dnia otwartego, więc bez
    zleceń z 9.11."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    folder = centrum.periods_directory / month / MONDAY_PERIOD
    folder.mkdir(parents=True)
    _click_at(centrum, ENTERING_NOW, [])
    before = _cells(centrum.register)

    still_open = _click_at(
        centrum,
        datetime(2026, 11, 10, 8),
        [report(JAN, SUBJECT, "40000001 tak wymiana", at=datetime(2026, 11, 10, 7, 40))],
    )
    (folder / f"Rozliczenie {MONDAY_PERIOD} - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    closed = _click_at(
        centrum,
        datetime(2026, 11, 10, 9),
        [report(ANNA, SUBJECT, "40000002 tak montaż", at=datetime(2026, 11, 10, 8, 50))],
    )

    assert _cells(centrum.register) == {**before, 40000001: ("tak", "wymiana")}
    assert centrum.fake_inbox.days == [date(2026, 11, 9), date(2026, 11, 9), date(2026, 11, 10)]
    assert [_entering(centrum, view)["closed"] for view in (still_open, closed)] == [[], [MONDAY_PERIOD]]
    assert _entering(centrum, closed)["mails"] == [], "Raport z dnia okresu z Plikiem zbiorczym rdzeń pomija po cichu"
    assert [_copied_numbers(centrum, view) for view in (still_open, closed)] == [[40000002, 40000001], []]


def test_te_same_maile_w_innej_kolejnosci_i_drugie_klikniecie_daja_ten_sam_wynik(tmp_path: Path) -> None:
    """Kryterium #1229: kolejność, w jakiej skrzynka oddaje maile, nie zmienia wpisanych komórek ani problemów, a drugie
    kliknięcie z tymi samymi mailami niczego nie zmienia i ma te same problemy. Wpis Anny do zlecenia Jana przegrywa ze
    świeższym mailem Jana, więc zlecenie zostaje u Jana bez problemu (ADR 0029)."""

    mails = [
        report(JAN, SUBJECT, "40000001 tak wymiana", at=datetime(2026, 11, 9, 17)),
        report(JAN, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 17, 30)),
        report(ANNA, SUBJECT, "40000002 tak montaż", at=datetime(2026, 11, 9, 17, 10)),
        report(ANNA, SUBJECT, "40000001 tak montaż", at=datetime(2026, 11, 9, 17, 20)),
        report("obcy@przyklad.invalid", SUBJECT, "40000002 nie brak", at=datetime(2026, 11, 9, 17, 5)),
    ]
    forward = entering_centrum(tmp_path / "w-kolejnosci", INTERMAX, mails)
    backward = entering_centrum(tmp_path / "od-konca", INTERMAX, mails[::-1])

    first, reversed_first = _finished(forward), _finished(backward)
    again = _finished(forward)

    results = [_entering(forward, first), _entering(backward, reversed_first)]
    assert _cells(forward.register) == _cells(backward.register)
    assert _cells(forward.register)[40000001] == ("nie", "klient nieobecny"), "wygrywa późniejszy mail"
    assert [(result["changes"], result["problems"]) for result in results] == [
        (results[0]["changes"], results[0]["problems"])
    ] * 2
    assert [problem["kind"] for problem in results[0]["problems"]] == ["unknown_sender"]
    assert results[0]["moves"] == []
    repeated = _entering(forward, again)
    assert (repeated["changes"], repeated["problems"]) == ([], results[0]["problems"])


def _day_rows(register: Path, last: int) -> list[object]:
    """Wiersze arkusza zleceń od 2 do ``last``: (``NUMER ZL.``, ``WYKONAWCA``) zlecenia, „żółty” wiersz taty albo
    „pusty”."""

    sheet = load_workbook(register)[ORDER_SHEET]
    rows: list[object] = []
    for number in range(2, last + 1):
        if any(sheet.cell(number, column).value is not None for column in range(1, LAST + 1)):
            rows.append((sheet.cell(number, NUMBER).value, sheet.cell(number, WORKER).value))
        else:
            rows.append("żółty" if sheet.row_dimensions[number].fill.fgColor.rgb == "FFFFFF00" else "pusty")
    return rows


def _order_look(register: Path, number: int) -> list[tuple[object, ...]]:
    """Wygląd komórek od B do ``UWAGI`` wiersza zlecenia ``number`` poza ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``, które
    dostają Wpis: krój, rozmiar, pogrubienie i ramka, z Hiperłączem ``NUMER ZL.``."""

    sheet = load_workbook(register)[ORDER_SHEET]
    [row] = [cell.row for cell in sheet[get_column_letter(NUMBER)] if cell.value == number]
    cells = [sheet.cell(row, column) for column in range(FIRST, LAST + 1) if column not in (SUCCESSFUL, COMPLETED)]
    link = sheet.cell(row, NUMBER).hyperlink
    return [
        *((cell.font.name, cell.font.sz, cell.font.b, cell.border.left.style, cell.border.bottom.style) for cell in cells),
        (None if link is None else link.target,),
    ]


def test_klikniecie_przenosi_przejete_zlecenie_pod_zlecenia_nadawcy_z_informacja_w_okienku_dnia_po_obu_stronach(
    tmp_path: Path,
) -> None:
    """Kryterium #1347 (ADR 0029): Anna przysłała Wpis zlecenia 40000001, które INTERMAX ma u Jana w tym samym dniu.
    Kliknięcie zmienia ``WYKONAWCA`` na Annę i stawia wiersz pod jej ostatnim zleceniem, z wyglądem i Hiperłączem
    uporządkowanego zlecenia i z jej Wpisem, zapisem bez Kopii INTERMAX; pusty wiersz między segmentami i żółty wiersz
    dnia zostają na miejscach. Okienko dnia pokazuje „przejęte od jan.testowy” u Anny i „przekazane anna.kowalska” u
    Jana, bez problemu i bez ``ADRES``, ``NUMER UMOWY`` i treści maila; drugie kliknięcie niczego nie zmienia."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.testowy", 40000005),
            _order(9, 11, "anna.kowalska", 40000002),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax, [report(ANNA, SUBJECT, "40000001 tak montaż gniazda")])
    look = _order_look(centrum.register, 40000001)
    assert _day_rows(centrum.register, 7) == [
        (40000001, "jan.testowy"),
        (40000005, "jan.testowy"),
        "pusty",
        (40000002, "anna.kowalska"),
        "pusty",
        "żółty",
    ]

    view = _finished(centrum)
    shown = _view(centrum)
    after = centrum.register.read_bytes()
    again = _finished(centrum)

    assert _day_rows(centrum.register, 7) == [
        (40000005, "jan.testowy"),
        "pusty",
        (40000002, "anna.kowalska"),
        (40000001, "anna.kowalska"),
        "pusty",
        "żółty",
    ]
    assert _order_look(centrum.register, 40000001) == look
    assert _cells(centrum.register)[40000001] == ("tak", "montaż gniazda")
    assert not centrum.tool.intermax_copies.exists(), "Wpisanie raportów nie robi Kopii INTERMAX"
    assert _entering(centrum, view)["moves"] == [{"sheet": ORDER_SHEET, "row": 2, "day": "2026-11-09", "worker": "anna.kowalska"}]
    assert _entering(centrum, view)["problems"] == []
    anna, jan = _worker(shown, "anna.kowalska"), _worker(shown, "jan.testowy")
    assert anna["notes"] == [{"number": "40000001", "text": "przejęte od jan.testowy"}]
    assert jan["notes"] == [{"number": "40000001", "text": "przekazane anna.kowalska"}]
    assert [order["number"] for order in anna["orders_detail"]] == ["40000002", "40000001"]
    assert [order["number"] for order in jan["orders_detail"]] == ["40000005"]
    assert (anna["problems"], jan["problems"]) == ([], [])
    text = json.dumps(shown, ensure_ascii=False)
    assert "Ulica" not in text and "UM-" not in text and "montaż gniazda" not in text.replace('"activities": "montaż gniazda"', "")
    assert (_entering(centrum, again)["changes"], _entering(centrum, again)["moves"]) == ([], [])
    assert centrum.register.read_bytes() == after
    assert _worker(_view(centrum), "anna.kowalska")["notes"] == anna["notes"]


def test_reczna_zmiana_wykonawcy_po_wpisie_zostaje_przy_starym_mailu_a_swiezszy_mail_przenosi(tmp_path: Path) -> None:
    """ADR 0029 „Ręczna zmiana dalej wygrywa”, przegląd #1358 r1: kliknięcie wpisało Wpis Jana do jego zlecenia, a tata
    dał potem zlecenie Annie w Excelu. Następne kliknięcie z tym samym mailem zostawia zlecenie u Anny bez zapisu
    INTERMAX; świeższy mail Jana (US 3) przenosi je z powrotem pod jego zlecenia, z informacją w okienku dnia."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "anna.kowalska", 40000002),
            _order(9, 10, "jan.testowy", 40000001),
            _order(9, 11, "jan.testowy", 40000005),
        ),
        raw=(),
    )
    first = report(JAN, SUBJECT, "40000001 tak wymiana", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path, intermax, [first])
    _finished(centrum)
    sheet = load_workbook(centrum.register)
    [row] = [cell.row for cell in sheet[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == 40000001]
    sheet[ORDER_SHEET].cell(row, WORKER).value = "anna.kowalska"
    sheet.save(centrum.register)
    by_tata = centrum.register.read_bytes()

    same = _finished(centrum)
    kept = centrum.register.read_bytes()
    centrum.fake_inbox.outcome = [first, report(JAN, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 18))]
    newer = _finished(centrum)

    assert (_entering(centrum, same)["changes"], _entering(centrum, same)["moves"]) == ([], [])
    assert kept == by_tata
    assert _entering(centrum, newer)["moves"] == [{"sheet": ORDER_SHEET, "row": row, "day": "2026-11-09", "worker": "jan.testowy"}]
    assert _day_rows(centrum.register, 7) == [
        (40000002, "anna.kowalska"),
        "pusty",
        (40000005, "jan.testowy"),
        (40000001, "jan.testowy"),
        "pusty",
        "żółty",
    ]
    assert _cells(centrum.register)[40000001] == ("nie", "klient nieobecny")
    assert _worker(_view(centrum), "jan.testowy")["notes"] == [{"number": "40000001", "text": "przejęte od anna.kowalska"}]


def _given_to(register: Path, number: int, worker: str) -> None:
    """Tata zmienia w Excelu ``WYKONAWCA`` zlecenia ``number`` na ``worker``."""

    book = load_workbook(register)
    [row] = [cell.row for cell in book[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == number]
    book[ORDER_SHEET].cell(row, WORKER).value = worker
    book.save(register)


def test_druga_reczna_zmiana_wykonawcy_nie_wraca_mailem_ktory_centrum_juz_przyjelo(tmp_path: Path) -> None:
    """Przegląd #1358 r2 (C), ADR 0029 „Ręczna zmiana dalej wygrywa”: kliknięcie wpisało Wpis Jana, tata dał zlecenie
    Annie, kliknięcie wpisało u niej jej Wpis, a tata oddał zlecenie Janowi. Następne kliknięcie z tymi samymi mailami
    zostawia zlecenie u Jana: mail Anny Centrum już przyjęło. Wpis Jana wraca do komórek, które Centrum samo wpisało, bez
    różnicy z ręczną wartością i bez informacji o Przeniesieniu."""

    intermax = Intermax(
        ordered=(_order(9, 9, "anna.kowalska", 40000002), _order(9, 10, "jan.testowy", 40000001)),
        raw=(),
    )
    jan = report(JAN, SUBJECT, "40000001 tak wymiana", at=datetime(2026, 11, 9, 17))
    anna = report(ANNA, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 17, 30))
    centrum = entering_centrum(tmp_path, intermax, [jan])
    _finished(centrum)
    _given_to(centrum.register, 40000001, "anna.kowalska")
    centrum.fake_inbox.outcome = [jan, anna]
    at_anna = _finished(centrum)
    _given_to(centrum.register, 40000001, "jan.testowy")

    back = _finished(centrum)
    shown = _view(centrum)

    assert _entering(centrum, at_anna)["moves"] == []
    assert _entering(centrum, back)["moves"] == []
    assert _entering(centrum, back)["problems"] == []
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana")
    assert _day_rows(centrum.register, 6) == [(40000002, "anna.kowalska"), "pusty", (40000001, "jan.testowy"), "pusty", "żółty"]
    assert (_worker(shown, "jan.testowy")["notes"], _worker(shown, "jan.testowy")["problems"]) == ([], [])


def test_nadawca_bez_segmentu_w_dniu_dostaje_nowy_segment_na_miejscu_alfabetycznym(tmp_path: Path) -> None:
    """Kryterium #1347: Anna nie ma zleceń 9.11, a przejmuje jedno z dwóch zleceń Jana. Jej nowy segment staje przed
    segmentem Jana (alfabetycznie), z jednym pustym wierszem między segmentami z wyglądem pustego wiersza Uporządkowania
    (Calibri 8 z cienką ramką, ``WYKONAWCA`` Calibri 9); żółty wiersz dnia zostaje jeden pusty wiersz pod dniem, który
    urósł o wiersz."""

    intermax = Intermax(
        ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000005)),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax, [report(ANNA, SUBJECT, "40000005 nie klient nieobecny")])

    _finished(centrum)

    assert _day_rows(centrum.register, 7) == [
        (40000005, "anna.kowalska"),
        "pusty",
        (40000001, "jan.testowy"),
        "pusty",
        "żółty",
        "pusty",
    ]
    sheet = load_workbook(centrum.register)[ORDER_SHEET]
    separator = [sheet.cell(3, column) for column in range(FIRST, LAST + 1)]
    assert [(cell.font.name, cell.font.sz, cell.border.left.style) for cell in separator] == [
        ("Calibri", 9 if cell.column == WORKER else 8, "thin") for cell in separator
    ]
    assert not any(cell.value for cell in separator)


def test_plik_pamieci_sprzed_przeniesien_czyta_sie_a_nastepny_zapis_ma_przeniesienia_ktore_zatrzymuja_reczna_zmiane(
    tmp_path: Path,
) -> None:
    """Kryterium #1347: plik pamięci w wersji 1 (bez Przeniesień) czyta się bez błędu, z dniem wdrożenia i własnym
    wpisem, który poprawka Jana dalej nadpisuje. Kliknięcie z Przeniesieniem zlecenia Jana do Anny zapisuje wersję 3 z
    tym Przeniesieniem i z miejscem zlecenia Jana, którego Wpis przyjęło u Jana, z pisownią ``WYKONAWCA`` i chwilą
    maila, więc gdy tata odda potem zlecenie Janowi w Excelu, następne kliknięcie go nie przenosi."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.testowy", 40000005),
            _order(9, 11, "anna.kowalska", 40000002),
        ),
        raw=(),
    )
    mails = [
        report(JAN, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 17)),
        report(ANNA, SUBJECT, "40000005 tak montaż", at=datetime(2026, 11, 9, 17, 30)),
    ]
    centrum = entering_centrum(tmp_path, intermax, mails)
    _tata_writes(centrum.register, 40000001, "tak")
    own = {"number": "40000001", "day": "2026-11-09", "worker": "jan.testowy", "column": "SKUTECZNE", "value": "tak"}
    _state(centrum).write_text(
        json.dumps({"schema_version": 1, "rollout": "2026-11-09", "own": [own]}, ensure_ascii=False), encoding="utf-8"
    )

    view = _finished(centrum)
    saved = json.loads(_state(centrum).read_text(encoding="utf-8"))
    sheet = load_workbook(centrum.register)
    [row] = [cell.row for cell in sheet[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == 40000005]
    sheet[ORDER_SHEET].cell(row, WORKER).value = "jan.testowy"
    sheet.save(centrum.register)
    again = _finished(centrum)

    assert _entering(centrum, view)["rollout_before"] == "2026-11-09"
    assert _cells(centrum.register)[40000001] == ("nie", "klient nieobecny"), "własny wpis z pamięci w wersji 1"
    assert saved["schema_version"] == 3
    # Chwila maila ze strefą komputera (``report`` daje ``astimezone()``): na Macu „+01:00”, na Linuksie CI „Z”.
    jan_since, anna_since = datetime(2026, 11, 9, 17).astimezone(), datetime(2026, 11, 9, 17, 30).astimezone()
    assert [{**move, "since": datetime.fromisoformat(move["since"])} for move in saved["moves"]] == [
        {
            "number": "40000001",
            "day": "2026-11-09",
            "worker": "jan.testowy",
            "origin_day": "2026-11-09",
            "origin_worker": "jan.testowy",
            "origin_name": "jan.testowy",
            "since": jan_since,
            "overridden": False,
        },
        {
            "number": "40000005",
            "day": "2026-11-09",
            "worker": "anna.kowalska",
            "origin_day": "2026-11-09",
            "origin_worker": "jan.testowy",
            "origin_name": "jan.testowy",
            "since": anna_since,
            "overridden": False,
        },
    ]
    assert _entering(centrum, again)["moves"] == []
    assert _entering(centrum, again)["moves_before"] == [
        {**move, "number": int(move["number"])} for move in saved["moves"]
    ]


_BRANCH_MOVE = {"number": "40000001", "day": "2026-11-09", "worker": "jan.testowy", "origin_day": "2026-11-09"}


@pytest.mark.parametrize(
    "move",
    [
        pytest.param({**_BRANCH_MOVE, "origin_worker": "anna.kowalska"}, id="runda-1"),
        pytest.param(
            {**_BRANCH_MOVE, "origin_worker": "anna.kowalska", "origin_name": "Anna", "since": "2026-11-09T17:00:00+01:00"},
            id="runda-2",
        ),
    ],
)
def test_plik_pamieci_w_wersji_2_z_galezi_czyta_sie_bez_pamieci_zlecen_zamiast_zatrzymania(
    tmp_path: Path, move: dict[str, str]
) -> None:
    """Plik pamięci w wersji 2 powstał tylko na gałęzi #1358 przed jej trzecią rundą, w dwóch postaciach ``moves``.
    Kliknięcie go czyta jak wersję 1: dzień wdrożenia i własny wpis, który poprawka Jana dalej nadpisuje, ale bez
    pamięci zleceń (Logi: ``moves_before`` puste), a zapisuje wersję 3."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "anna.kowalska", 40000005)), raw=())
    centrum = entering_centrum(
        tmp_path, intermax, [report(JAN, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 17))]
    )
    _tata_writes(centrum.register, 40000001, "tak")
    own = {"number": "40000001", "day": "2026-11-09", "worker": "jan.testowy", "column": "SKUTECZNE", "value": "tak"}
    _state(centrum).write_text(
        json.dumps({"schema_version": 2, "rollout": "2026-11-09", "own": [own], "moves": [move]}), encoding="utf-8"
    )

    view = _finished(centrum)

    assert _entering(centrum, view)["rollout_before"] == "2026-11-09"
    assert _entering(centrum, view)["moves_before"] == []
    assert _cells(centrum.register)[40000001] == ("nie", "klient nieobecny"), "własny wpis z pamięci w wersji 2"
    assert json.loads(_state(centrum).read_text(encoding="utf-8"))["schema_version"] == 3

def test_bez_folderu_okresow_w_ustawieniach_karta_mowi_co_wskazac_a_start_jest_odrzucony(tmp_path: Path) -> None:
    """Bez folderu okresów kliknięcie nie wie, które okresy mają Plik zbiorczy, więc nie startuje i nie czyta skrzynki."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")], periods=False)

    setup = centrum.setup()
    started = centrum.start()

    assert setup["blocker"] == "Najpierw wskaż folder okresów."
    assert (started.status_code, started.json()) == (409, {"message": "Najpierw wskaż folder okresów."})
    assert centrum.fake_inbox.days == []
    assert centrum.run_logs() == []


def test_folder_okresow_ktorego_juz_nie_ma_zatrzymuje_klikniecie_dla_taty_bez_odczytu_skrzynki(tmp_path: Path) -> None:
    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = centrum.register.read_bytes()
    centrum.periods_directory.rmdir()

    result = _stopped(centrum)

    [stop] = result["stops"]
    assert (result["stop_kind"], stop["what"], stop["where"]) == (
        "for_tata",
        "Nie znaleziono folderu okresów, więc maili nie przeczytano. INTERMAX nie został zmieniony.",
        f"folder {tmp_path.name}\\Okresy",
    )
    assert centrum.fake_inbox.days == []
    assert centrum.register.read_bytes() == before


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_folder_okresu_bez_dostepu_zatrzymuje_klikniecie_dla_taty_bez_odczytu_skrzynki(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    """Bez dostępu do Folderu okresu (OneDrive nie działa) narzędzie nie wie, czy okres ma Plik zbiorczy: Zatrzymanie,
    zanim proces przeczyta skrzynkę, zamiast wpisu do okresu, który może być zamknięty."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    folder = centrum.periods_directory / MONDAY_PERIOD
    folder.mkdir()
    before = centrum.register.read_bytes()
    path_checks(monkeypatch)

    with without_access(folder):
        result = _stopped(centrum)

    [stop] = result["stops"]
    assert (result["stop_kind"], stop["what"], stop["where"]) == (
        "for_tata",
        "Nie można teraz odczytać folderu okresów, więc maili nie przeczytano. INTERMAX nie został zmieniony.",
        f"folder Okresy\\{MONDAY_PERIOD}",
    )
    assert centrum.fake_inbox.days == []
    assert centrum.register.read_bytes() == before


# --- Widok Raporty i „Zostaw moją” (#1231) ------------------------------------------------------------------------------

STRANGER = "obcy@przyklad.invalid"


def _view(centrum: EnteringCentrum) -> dict[str, Any]:
    response = centrum.client.get("/api/report-entering/view")
    assert response.status_code == 200, response.json()
    return dict(response.json())


def _worker(view: dict[str, Any], login: str, day: str = "2026-11-09") -> dict[str, Any]:
    """Dzień ``day`` Wykonawcy ``login`` z widoku Raporty."""

    [found] = [shown for worker in view["workers"] if worker["worker"] == login for shown in worker["days"] if shown["day"] == day]
    return dict(found)


def _days(view: dict[str, Any]) -> list[str]:
    return [shown["day"] for shown in view["days"]]


def _workers_of(view: dict[str, Any], day: str) -> list[str]:
    """Wykonawcy, którzy mają w widoku Raporty dzień ``day``."""

    return [worker["worker"] for worker in view["workers"] if day in {shown["day"] for shown in worker["days"]}]


def test_widok_raporty_pokazuje_przy_wykonawcy_liczby_problemy_z_powodem_i_zlecenia_bez_raportu_bez_odczytu_skrzynki(
    tmp_path: Path,
) -> None:
    """US 52–56: po kliknięciu widok Raporty ma przy każdym Wykonawcy dnia jego zlecenia, wpisane, Raporty wykonawcy i
    problemy z powodem i numerem zlecenia, oraz zlecenia bez żadnego Wpisu; Raport z adresu spoza listy stoi osobno z
    adresem, którego Logi nie mają. Widok czyta wynik z pliku, a nie skrzynkę."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.testowy", 40000005),
            _order(9, 11, "anna.kowalska", 40000002),
        ),
        raw=(),
    )
    centrum = entering_centrum(
        tmp_path,
        intermax,
        [
            report(JAN, SUBJECT, "40000001 tak wymiana routera"),
            report(ANNA, SUBJECT, "40000009 tak montaż"),
            report(STRANGER, SUBJECT, "40000002 nie brak"),
        ],
    )
    before = _view(centrum)
    _finished(centrum)
    read = list(centrum.fake_inbox.days)

    view = _view(centrum)

    assert before == {
        "clicked_at": None,
        "today": "2026-11-09",
        "days": [{"day": "2026-11-09", "holiday": None}],
        "workers": [],
        "unknown_senders": [],
        "reminders_without_footer": False,
    }
    assert centrum.fake_inbox.days == read, "widok Raporty nie czyta skrzynki"
    assert datetime.fromisoformat(view["clicked_at"]) == ENTERING_NOW.astimezone()
    assert view["days"] == [{"day": "2026-11-09", "holiday": None}]
    unknown = UnknownNumber(Login("anna.kowalska"), date(2026, 11, 9), OrderNumber("40000009"))
    assert view["workers"] == [
        {
            "worker": "anna.kowalska",
            "days": [
                {
                    "day": "2026-11-09",
                    "orders": 1,
                    "entered": 0,
                    "mails": 1,
                    "without_report": ["40000002"],
                    "problems": [{"reason": reason(unknown), "number": "40000009", "keep": None}],
                    "notes": [],
                    "orders_detail": [
                        {"number": "40000002", "successful": None, "activities": None, "state": "without_report"}
                    ],
                    "reminders": [],
                }
            ],
        },
        {
            "worker": "jan.testowy",
            "days": [
                {
                    "day": "2026-11-09",
                    "orders": 2,
                    "entered": 1,
                    "mails": 1,
                    "without_report": ["40000005"],
                    "problems": [],
                    "notes": [],
                    "orders_detail": [
                        {"number": "40000001", "successful": "tak", "activities": "wymiana routera", "state": "entered"},
                        {"number": "40000005", "successful": None, "activities": None, "state": "without_report"},
                    ],
                    "reminders": [],
                }
            ],
        },
    ]
    [stranger] = view["unknown_senders"]
    assert (stranger["day"], stranger["sender"]) == ("2026-11-09", STRANGER)
    assert STRANGER not in json.dumps(centrum.run_logs(), ensure_ascii=False)


def test_zlecenia_dnia_w_widoku_raporty_zgadzaja_sie_z_intermax_po_kliknieciu_takze_przy_zostaw_moja(tmp_path: Path) -> None:
    """#1322: przy każdym dniu Wykonawcy widok Raporty ma jego zlecenia w kolejności wierszy INTERMAX, z ``SKUTECZNE`` i
    ``CZYNNOŚCI ZREALIZOWANE`` takimi, jakie INTERMAX ma po kliknięciu, także z ręczną wartością taty, i stan: wpisane z
    Wpisu, bez raportu albo problem. Po „Zostaw moją” zlecenie z ręczną wartością jest wpisane, a INTERMAX bez zmian.
    Ręczny opis taty przy zleceniu bez raportu widok też pokazuje."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000006),
            _order(9, 10, "jan.testowy", 40000001),
            _order(9, 11, "jan.testowy", 40000005),
            _order(9, 12, "anna.kowalska", 40000002),
        ),
        raw=(),
    )
    centrum = entering_centrum(
        tmp_path,
        intermax,
        [report(JAN, SUBJECT, "40000006 tak montaż 40000001 tak wymiana"), report(ANNA, SUBJECT, "40000002 brak klienta")],
    )
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    _tata_writes(centrum.register, 40000005, "klient przełożył", column=COMPLETED)
    _finished(centrum)
    cells = _cells(centrum.register)

    view = _view(centrum)
    [difference] = _worker(view, "jan.testowy")["problems"]
    kept = centrum.client.post("/api/report-entering/keep", json=difference["keep"]).json()

    def shown(found: dict[str, Any], login: str) -> list[tuple[int, object, object, str]]:
        return [
            (int(order["number"]), order["successful"], order["activities"], order["state"])
            for order in _worker(found, login)["orders_detail"]
        ]

    jan = [number for number in cells if number in {40000006, 40000001, 40000005}]
    states = {40000006: "entered", 40000001: "problem", 40000005: "without_report"}
    assert jan == [40000006, 40000001, 40000005], "zlecenia Jana stoją w INTERMAX w tej kolejności"
    assert shown(view, "jan.testowy") == [(number, *cells[number], states[number]) for number in jan]
    assert (cells[40000001], cells[40000005]) == (("tak", "wymiana ręczna"), (None, "klient przełożył"))
    assert shown(view, "anna.kowalska") == [(40000002, *cells[40000002], "problem")]
    assert shown(kept, "jan.testowy") == [(number, *cells[number], {**states, 40000001: "entered"}[number]) for number in jan]
    assert _cells(centrum.register) == cells, "„Zostaw moją” nie zmienia INTERMAX"


def test_plik_wyniku_sprzed_zlecen_dnia_czyta_sie_z_liczbami_bez_zlecen_az_do_nastepnego_klikniecia(tmp_path: Path) -> None:
    """#1322: plik wyniku w wersji 1, zapisany przez Centrum sprzed listy zleceń, leży u taty w ``config``. Widok Raporty
    czyta go bez błędu: liczby, problemy i nieznany nadawca jak w pliku, a ``orders_detail`` jest ``null`` przy każdym
    dniu; „Zostaw moją” przy jego różnicy działa. Następne kliknięcie zapisuje wynik ze zleceniami dnia."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    old = ROOT / "tests" / "fixtures" / "wpisanie-raportow-wynik-v1.json"
    shutil.copyfile(old, centrum.tool.config / REPORT_ENTERING_RESULT)

    view = _view(centrum)
    [difference] = _worker(view, "jan.testowy")["problems"]
    kept = centrum.client.post("/api/report-entering/keep", json=difference["keep"])

    assert datetime.fromisoformat(view["clicked_at"]) == datetime.fromisoformat("2026-11-09T18:30:00+01:00")
    assert [
        (worker["worker"], [(day["day"], day["orders"], day["entered"], day["mails"], day["without_report"]) for day in worker["days"]])
        for worker in view["workers"]
    ] == [
        ("anna.kowalska", [("2026-11-09", 1, 0, 1, ["40000002"])]),
        ("jan.testowy", [("2026-11-09", 2, 1, 1, ["40000005"])]),
    ]
    assert [day["orders_detail"] for worker in view["workers"] for day in worker["days"]] == [None, None]
    assert [problem["number"] for problem in _worker(view, "anna.kowalska")["problems"]] == ["40000001"]
    assert [(sender["day"], sender["sender"]) for sender in view["unknown_senders"]] == [("2026-11-09", STRANGER)]
    assert kept.status_code == 200, kept.json()
    assert (_worker(kept.json(), "jan.testowy")["problems"], _worker(kept.json(), "jan.testowy")["orders_detail"]) == ([], None)

    _finished(centrum)

    assert [order["number"] for order in _worker(_view(centrum), "jan.testowy")["orders_detail"]] == ["40000001"]


def test_plik_wyniku_sprzed_zlecen_dnia_daje_null_takze_przy_dniu_z_samym_problemem(tmp_path: Path) -> None:
    """#1322: w pliku wyniku w wersji 1 Wykonawca może mieć dzień z samym problemem, bez liczb. Widok Raporty daje przy
    nim zera i ``orders_detail`` ``null`` jak przy innych dniach tego pliku, bo wersja 1 nie zapisywała zleceń dnia."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    old = json.loads((ROOT / "tests" / "fixtures" / "wpisanie-raportow-wynik-v1.json").read_text(encoding="utf-8"))
    old["problems"].append(
        {
            "day": "2026-11-09",
            "worker": "ola.testowa",
            "number": "40000009",
            "reason": "Numer 40000009 nie jest zleceniem ola.testowa z 09.11.2026.",
            "sender": None,
            "difference": None,
        }
    )
    (centrum.tool.config / REPORT_ENTERING_RESULT).write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

    only_problem = _worker(_view(centrum), "ola.testowa")

    assert (only_problem["orders"], only_problem["entered"], only_problem["mails"], only_problem["orders_detail"]) == (
        0,
        0,
        0,
        None,
    )
    assert [problem["number"] for problem in only_problem["problems"]] == ["40000009"]


def test_widok_raporty_na_przelomie_roku_daje_swieta_z_obu_lat(tmp_path: Path) -> None:
    """#1322: okno od Wigilii 2026, dnia wdrożenia, do soboty 2.01.2027 ma przy każdym dniu święto z jego własnego
    roku, więc 24–26.12.2026 i 1.01.2027 mają nazwy, choć okno kończy się w innym roku niż zaczyna."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _click_at(centrum, datetime(2026, 12, 24, 18), [])
    _click_at(centrum, datetime(2027, 1, 2, 8), [])

    days = _view(centrum)["days"]
    named = [shown["day"] for shown in days if shown["holiday"] is not None]

    assert [shown["holiday"] for shown in days] == [
        public_holidays(date.fromisoformat(shown["day"]).year).get(date.fromisoformat(shown["day"])) for shown in days
    ]
    assert named == ["2026-12-24", "2026-12-25", "2026-12-26", "2027-01-01"]


def test_widok_raporty_pokazuje_wykonawce_z_samym_problemem_w_dniu_bez_jego_zlecen_i_raportow(tmp_path: Path) -> None:
    """US 55: Anna nie ma zleceń 9.11, a jej mail z tego dnia ma temat bez daty, więc nie jest Raportem wykonawcy.
    Widok Raporty pokazuje ją przy tym dniu z zerami i tym problemem, zamiast zgubić problem razem z nią."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001),), raw=())
    mail = report(ANNA, "Raport bez daty", "40000002 tak montaż")
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000001 tak wymiana"), mail])
    _finished(centrum)

    view = _view(centrum)

    unreadable = UnreadableSubject(
        MailId.of("<syntetyczny@przyklad.invalid>"), Login("anna.kowalska"), mail.arrived, SubjectFault.NO_DATE
    )
    assert _worker(view, "anna.kowalska") == {
        "day": "2026-11-09",
        "orders": 0,
        "entered": 0,
        "mails": 0,
        "without_report": [],
        "problems": [{"reason": reason(unreadable), "number": None, "keep": None}],
        "notes": [],
        "orders_detail": [],
        "reminders": [],
    }


def test_tak_i_nie_jednego_zlecenia_w_mailu_nic_do_niego_nie_wpisuja_a_widok_raporty_pokazuje_ostrzezenie_z_oboma_wpisami(
    tmp_path: Path,
) -> None:
    """Decyzja Maksa 11.11: Raport Jana z aplikacji pocztowej w jednej linii ma dla 40000001 Wpis z ``tak`` i Wpis z
    ``nie``, a na końcu stopkę. Zlecenie 40000001 zostaje puste, 40000005 dostaje ``tak`` bez stopki w opisie, a widok
    Raporty pokazuje przy Janie ostrzeżenie z mailem, numerem i oboma Wpisami."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000005)), raw=())
    text = "40000001 tak inst25m  40000001 nie brak klienta od umowy  40000005 tak   Wysłano z aplikacji mobilnej Poczty o2"
    mail = report(JAN, SUBJECT, text)
    centrum = entering_centrum(tmp_path, intermax, [mail])
    before = _cells(centrum.register)

    view = _finished(centrum)

    number = OrderNumber("40000001")
    warning = ConflictingVerdicts(
        Login("jan.testowy"),
        date(2026, 11, 9),
        number,
        mail.id,
        mail.arrived,
        (ReportEntry(number, Verdict.YES, None, "inst25m"), ReportEntry(number, Verdict.NO, None, "brak klienta od umowy")),
    )
    assert _cells(centrum.register) == {**before, 40000005: ("tak", None)}
    assert view["result"]["summary"]["figures"][:2] == [
        {"label": "Wpisane", "value": 1, "unit": "count"},
        {"label": "Problemy", "value": 1, "unit": "count"},
    ]
    assert _worker(_view(centrum), "jan.testowy")["problems"] == [
        {"reason": reason(warning), "number": "40000001", "keep": None}
    ]
    assert f"{mail.arrived:%d.%m.%Y o %H:%M}" in reason(warning)


def test_widok_raporty_ma_cale_okno_od_dnia_wdrozenia_do_dzis_tylko_z_otwartych_okresow(tmp_path: Path) -> None:
    """US 53, #1322: we wtorek widok Raporty ma dni od poniedziałku, dnia wdrożenia, do dziś, także przed pierwszym
    kliknięciem tego dnia, a przy poniedziałku Wykonawców z Raportami z ostatniego kliknięcia. Gdy okres poniedziałku
    dostanie Plik zbiorczy, następne kliknięcie nie daje już jego dni."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)
    _next_morning(centrum)
    morning = _view(centrum)
    _finished(centrum)

    today = _view(centrum)
    folder = centrum.periods_directory / MONDAY_PERIOD
    folder.mkdir()
    (folder / f"Rozliczenie {MONDAY_PERIOD} - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    _finished(centrum)

    assert (morning["today"], _days(morning), _workers_of(morning, "2026-11-10")) == (
        "2026-11-10",
        ["2026-11-09", "2026-11-10"],
        [],
    )
    assert (today["today"], _days(today), _workers_of(today, "2026-11-10")) == (
        "2026-11-10",
        ["2026-11-09", "2026-11-10"],
        [],
    )
    assert [
        (login, _worker(today, login)["entered"], _worker(today, login)["mails"]) for login in _workers_of(today, "2026-11-09")
    ] == [("anna.kowalska", 1, 1), ("jan.testowy", 1, 1)]
    assert _days(_view(centrum)) == ["2026-11-10"]


def test_widok_raporty_daje_kazdy_dzien_okna_z_nazwa_swieta(tmp_path: Path) -> None:
    """#1322: kliknięcie w czwartek 12.11 po wdrożeniu w poniedziałek 9.11 daje widok z każdym dniem od 9.11 do 12.11,
    a 11.11 ma nazwę dnia ustawowo wolnego od pracy z ``public_holidays``; pozostałe dni są bez święta."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)

    _click_at(centrum, datetime(2026, 11, 12, 8), [report(JAN, SUBJECT, "40000001 tak wymiana")])

    assert _view(centrum)["days"] == [
        {"day": "2026-11-09", "holiday": None},
        {"day": "2026-11-10", "holiday": None},
        {"day": "2026-11-11", "holiday": public_holidays(2026)[date(2026, 11, 11)]},
        {"day": "2026-11-12", "holiday": None},
    ]


def test_widok_raporty_nie_daje_dni_okresu_z_plikiem_zbiorczym_miedzy_otwartymi_okresami(tmp_path: Path) -> None:
    """ADR 0028: okno dni od dnia wdrożenia 9.11 do środy 18.11 nie ma dni okresu 10_16_11_2026, gdy ten ma Plik
    zbiorczy, choć okres dnia wdrożenia dalej jest otwarty: widok Raporty daje poniedziałek 9.11, wtorek 17.11 i
    dziś."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _finished(centrum)
    folder = centrum.periods_directory / "10_16_11_2026"
    folder.mkdir()
    (folder / "Rozliczenie 10_16_11_2026 - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")

    _click_at(centrum, datetime(2026, 11, 18, 8), [report(JAN, SUBJECT, "40000001 tak wymiana")])

    assert _days(_view(centrum)) == ["2026-11-09", "2026-11-17", "2026-11-18"]


def test_udane_klikniecie_bez_problemow_nie_daje_powiadomienia(tmp_path: Path) -> None:
    """US 57: kliknięcie, które wpisało Raport bez problemów, zmienia tylko stan na ekranie: wynik proponuje „Otwórz
    Raporty”, a pod dzwonkiem nie ma nic nowego."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    before = centrum.client.get("/api/notifications").json()

    view = _finished(centrum)

    after = centrum.client.get("/api/notifications").json()
    assert view["result"]["next_action"] == "open_reports_view"
    assert view["result"]["summary"]["figures"][:2] == [
        {"label": "Wpisane", "value": 1, "unit": "count"},
        {"label": "Problemy", "value": 0, "unit": "count"},
    ]
    assert (after["unread"], after["items"]) == (before["unread"], before["items"])


def test_zostaw_moja_zapisuje_decyzje_poza_intermax_a_roznica_nie_wraca_dopoki_wykonawca_nie_przysle_innej_tresci(
    tmp_path: Path,
) -> None:
    """US 38–39 i 58: przy różnicy Wpisu z ręcznymi czynnościami taty „Zostaw moją” zapisuje decyzję w pliku decyzji,
    INTERMAX zostaje bajt w bajt, a różnica znika z widoku od razu i nie wraca przy następnym kliknięciu, które ma
    decyzję w Logach. Poprawka Wykonawcy z inną treścią pokazuje różnicę znowu, a ręczna wartość dalej zostaje."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    first = _finished(centrum)
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    register = centrum.register.read_bytes()

    kept = centrum.client.post("/api/report-entering/keep", json=difference["keep"])

    assert first["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 1, "unit": "count"}
    cell = {
        "number": "40000001",
        "day": "2026-11-09",
        "worker": "jan.testowy",
        "column": "CZYNNOŚCI ZREALIZOWANE",
        "reported": "wymiana",
    }
    assert (difference["number"], difference["keep"]) == ("40000001", cell)
    assert kept.status_code == 200, kept.json()
    assert _worker(kept.json(), "jan.testowy")["problems"] == []
    assert centrum.register.read_bytes() == register, "„Zostaw moją” nie zmienia INTERMAX"
    decisions = json.loads((centrum.tool.config / REPORT_ENTERING_DECISIONS).read_text(encoding="utf-8"))
    assert decisions == {"schema_version": 1, "kept": [cell]}

    again = _finished(centrum)

    assert (_entering(centrum, again)["problems"], _worker(_view(centrum), "jan.testowy")["problems"]) == ([], [])
    assert _entering(centrum, again)["kept"] == [
        {"number": 40000001, "day": "2026-11-09", "worker": "jan.testowy", "column": "CZYNNOŚCI ZREALIZOWANE", "value": "wymiana"}
    ]
    corrected = _click_at(
        centrum,
        datetime(2026, 11, 9, 19, 30),
        [
            report(JAN, SUBJECT, "40000001 tak wymiana"),
            report(JAN, SUBJECT, "40000001 tak wymiana gniazda", at=datetime(2026, 11, 9, 19)),
        ],
    )
    [shown] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert shown["keep"] == {**cell, "reported": "wymiana gniazda"}
    assert corrected["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 1, "unit": "count"}
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana ręczna")


def test_logi_klikniecia_maja_decyzje_zostaw_moja_tylko_przy_zleceniach_z_wpisem_w_tym_kliknieciu(tmp_path: Path) -> None:
    """Logi niosą decyzje „Zostaw moją” tak jak pamięć własnych wpisów: tylko zleceń z Wpisem w tym kliknięciu. Gdy
    Raportu Jana nie ma już w skrzynce, Logi kliknięcia z samym Raportem Anny nie mają decyzji przy zleceniu Jana, bo
    odtworzenie Logów z decyzją bez Wpisu kończy się granicą."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert centrum.client.post("/api/report-entering/keep", json=difference["keep"]).status_code == 200

    later = _click_at(centrum, datetime(2026, 11, 9, 19, 30), [report(ANNA, SUBJECT, "40000002 tak montaż")])

    assert _entering(centrum, later)["kept"] == []
    assert _cells(centrum.register)[40000002] == ("tak", "montaż")


def test_zostaw_moja_przy_roznicy_spoza_ostatniego_klikniecia_jest_odrzucone_bez_zapisu_decyzji(tmp_path: Path) -> None:
    """„Zostaw moją” tylko przy różnicy z wyniku ostatniego kliknięcia: inna treść Wpisu (widok sprzed nowszego
    kliknięcia) dostaje odmowę, a plik decyzji nie powstaje."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]

    refused = centrum.client.post("/api/report-entering/keep", json={**difference["keep"], "reported": "inna treść"})

    assert (refused.status_code, refused.json()["message"]) == (
        404,
        "Tej różnicy nie ma w ostatnim Wpisaniu raportów. Odśwież widok Raporty.",
    )
    assert not (centrum.tool.config / REPORT_ENTERING_DECISIONS).exists()
    assert _worker(_view(centrum), "jan.testowy")["problems"] == [difference]


@pytest.mark.parametrize("broken", [REPORT_ENTERING_RESULT, REPORT_ENTERING_DECISIONS])
def test_nieczytelny_plik_wyniku_albo_decyzji_daje_odmowe_widoku_i_zostaw_moja_bez_zapisu(tmp_path: Path, broken: str) -> None:
    """Pliku wyniku albo decyzji, którego nie da się odczytać, widok Raporty nie udaje pustym: odczyt i „Zostaw moją”
    dostają odmowę z tym samym zdaniem, a plik decyzji zostaje bajt w bajt, bo zapis bez dawnych decyzji przywróciłby
    ich różnice."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    decisions = centrum.tool.config / REPORT_ENTERING_DECISIONS
    if broken == REPORT_ENTERING_DECISIONS:
        decisions.write_text('{"schema_version": 2, "kept": []}', encoding="utf-8")
    else:
        (centrum.tool.config / REPORT_ENTERING_RESULT).write_text("{nie json", encoding="utf-8")
    before = decisions.read_bytes() if decisions.exists() else None

    shown = centrum.client.get("/api/report-entering/view")
    kept = centrum.client.post("/api/report-entering/keep", json=difference["keep"])

    message = (
        "Nie udało się odczytać wyniku Wpisania raportów ani decyzji „Zostaw moją”. Odśwież kartę, a gdy to się "
        "powtarza, wyślij Uwagę ogólną."
    )
    assert [(answer.status_code, answer.json()["message"]) for answer in (shown, kept)] == [(500, message)] * 2
    assert (decisions.read_bytes() if decisions.exists() else None) == before


# --- Przypomnienia o raporcie: praca Centrum co minutę (ADR 0030, #1349) -----------------------------------------------

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
ANNA = SENDERS["anna.kowalska"]
# Wtorek rano po dniu zleceń 9.11.2026: pora poranna, pierwsze przypomnienie za 9.11 (US 32).
REMINDER_MORNING = datetime(2026, 11, 10, 8, 30)


def _report_in_inbox(uid: int, sender: str, subject: str, at: datetime) -> AtrapaMail:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = SKRZYNKA
    message["Subject"] = subject
    message["Message-ID"] = f"<{uid}@przyklad.invalid>"
    message.set_content("40000002 tak montaż")
    return AtrapaMail(uid, at.astimezone(), bytes(message))


def _reminders_set_up(tool: ToolDirectory, *, footer: str | None = "Pozdrawiam\nTata\n") -> None:
    """Pliki Maksa w ``config``: dostęp do skrzynki raportów, dzień wdrożenia przypomnień 9.11.2026 i stopka taty."""

    (tool.config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\n{HASLO}\n", encoding="utf-8")
    (tool.config / REMINDERS_ROLLOUT).write_text("2026-11-09\n", encoding="utf-8")
    if footer is not None:
        (tool.config / REMINDERS_FOOTER).write_text(footer, encoding="utf-8")


def _reminder_result(centrum: EnteringCentrum) -> dict[str, Any]:
    return dict(json.loads((centrum.tool.config / REMINDERS_RESULT).read_text(encoding="utf-8")))


def test_praca_przypomnien_wysyla_przypomnienie_do_atrapy_smtp_raz_w_porze_takze_po_restarcie_centrum(
    tmp_path: Path,
) -> None:
    """Kryterium #1349: o 8:30 dnia po dniu zleceń Centrum wysyła przez SMTP przypomnienie Wykonawcy z listy, który ma
    zlecenia 9.11 i nie przysłał raportu, ze stopką taty, czytając INTERMAX otwarty w Excelu tylko do odczytu; druga
    minuta tej samej pory i Centrum po restarcie w tej porze nie wysyłają drugiego, bo pamięcią są „Wysłane”, a
    INTERMAX i skrzynka zostają bez zmian (US 31–36, 42–43, 46)."""

    anna_report = _report_in_inbox(1, ANNA, "Raport 09.11.2026", datetime(2026, 11, 9, 19, 0))
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[anna_report]) as imap, AtrapaSmtp(imap) as smtp:
        mailbox = ImapInbox(
            ToolDirectory(tmp_path).config,
            connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
            smtp=lambda: smtplib.SMTP("127.0.0.1", smtp.port, timeout=10),
        )
        centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
        _reminders_set_up(centrum.tool)
        lock = open_in_excel(centrum.register)
        before = centrum.register.read_bytes()
        centrum.moment.append(REMINDER_MORNING)
        centrum.client.start()

        centrum.rhythm.tick()
        centrum.moment.append(datetime(2026, 11, 10, 8, 31))
        centrum.rhythm.tick()
        centrum.restart()
        centrum.client.start()
        centrum.moment.append(datetime(2026, 11, 10, 9, 15))
        centrum.rhythm.tick()
        centrum.client.stop()

    [(raw, recipients)] = smtp.received
    message = email.message_from_bytes(raw, policy=email.policy.default)
    body = message.get_body()
    assert recipients == (JAN,)
    assert message["Subject"] == "Przypomnienie: raport za dzień 09.11.2026"
    assert body is not None and body.get_content().replace("\r\n", "\n").endswith("12345679 nie brak klienta\n\nPozdrawiam\nTata\n")
    assert centrum.register.read_bytes() == before and lock.exists()
    assert not {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"} & {command.split(" ")[0] for command in imap.commands}
    assert imap.flags[1] == set(), "przypomnienia nie oznaczają maili w skrzynce"
    log = centrum.tool.log_path.read_text(encoding="utf-8")
    assert log.count("przypomnienie-wyslane dzien=2026-11-09 pora=poranna") == 1
    for secret in (JAN, ANNA, SKRZYNKA, HASLO, "jan.testowy", "Raport 09.11.2026"):
        assert secret not in log, secret
    result = _reminder_result(centrum)
    assert {key: result[key] for key in ("schema_version", "pora", "failure", "footer")} == {
        "schema_version": 1,
        "pora": "poranna",
        "failure": None,
        "footer": "present",
    }
    assert [(sent["worker"], sent["day"]) for sent in result["sent"]] == [("jan.testowy", "2026-11-09")]
    assert not centrum.tool.run_logs.exists() or not list(centrum.tool.run_logs.glob("*.json")), "to nie Uruchomienie"


def test_praca_przypomnien_bez_stopki_wysyla_bez_niej_a_wynik_mowi_o_braku_stopki(tmp_path: Path) -> None:
    """Bez pliku stopki przypomnienie idzie bez niej, a wynik ostatniego sprawdzenia dla widoku Raporty mówi o tym (US 44)."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool, footer=None)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, reminder.text.endswith("12345679 nie brak klienta\n")) for reminder, _ in mailbox.sends] == [
        ("anna.kowalska", True),
        ("jan.testowy", True),
    ]
    assert _reminder_result(centrum)["footer"] == "missing"


def test_praca_przypomnien_bez_dnia_wdrozenia_w_nocy_i_przed_8_dnia_nastepnego_nic_nie_wysyla(tmp_path: Path) -> None:
    """Bez pliku dnia wdrożenia przypomnień Centrum nie czyta skrzynki i nic nie wysyła; z nim w dniu zleceń czyta
    skrzynkę raz w porze, ale za ten dzień nic nie wysyła, a w nocy i przed 8:00 dnia następnego nawet nie czyta (US
    32–33, 41)."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    (centrum.tool.config / REMINDERS_ROLLOUT).unlink()
    centrum.moment.append(datetime(2026, 11, 9, 21, 0))
    centrum.client.start()

    centrum.rhythm.tick()
    assert mailbox.days == [], "bez dnia wdrożenia skrzynka nie jest czytana"
    assert not (centrum.tool.config / REMINDERS_RESULT).exists(), "bez dnia wdrożenia praca nie pisze do config"
    (centrum.tool.config / REMINDERS_ROLLOUT).write_text("2026-11-09\n", encoding="utf-8")
    for moment in (datetime(2026, 11, 9, 21, 1), datetime(2026, 11, 9, 21, 2), datetime(2026, 11, 9, 23, 0), datetime(2026, 11, 10, 7, 59)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    centrum.client.stop()

    assert (mailbox.days, mailbox.sends) == ([date(2026, 11, 9)], [])
    log = centrum.tool.log_path.read_text(encoding="utf-8") if centrum.tool.log_path.exists() else ""
    assert "przypomnienia-porazka" not in log, "przypomnienia bez dnia wdrożenia są wyłączone, nie zepsute"


def test_brak_sieci_przy_przypomnieniach_ponawia_w_nastepnej_minucie_tej_samej_pory_bez_zgloszenia(tmp_path: Path) -> None:
    """Brak sieci przy przypomnieniach to tylko ponowienie w następnej minucie tej samej pory: bez Zgłoszenia, a
    porażka raz w Logach Centrum (US 47)."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    mailbox = FakeMailbox(sent=InboxUnreachable("TimeoutError"))
    centrum = entering_centrum(tmp_path, INTERMAX, surroundings=surroundings, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 8, 31))
    centrum.rhythm.tick()
    mailbox.sent = ()
    centrum.moment.append(datetime(2026, 11, 10, 8, 32))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]
    log = centrum.tool.log_path.read_text(encoding="utf-8")
    assert log.count("przypomnienia-porazka przyczyna=brak-sieci typ=TimeoutError") == 1
    assert surroundings.report_box.sent == []


def test_brak_sieci_przy_odczycie_maili_skrzynki_nie_wysyla_przypomnien_choc_wyslane_sa_czytelne(tmp_path: Path) -> None:
    """Gdy odczyt maili ze Skrzynki raportów się nie uda, a „Wysłane” są czytelne, nic nie wychodzi, bo bez maili
    przypomnienie poszłoby też do Wykonawcy, który raport przysłał; pora zostaje otwarta i następna minuta wysyła
    tylko temu, kto raportu nie przysłał (ADR 0030 „Kto i do kiedy”, US 47)."""

    anna_report = report(ANNA, "Raport 09.11.2026", "40000002 tak montaż")
    mailbox = FakeMailbox(outcome=InboxUnreachable("TimeoutError"))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    assert (mailbox.sends, _reminder_result(centrum)["failure"]) == ([], "brak-sieci")
    mailbox.outcome = (anna_report,)
    centrum.moment.append(datetime(2026, 11, 10, 8, 31))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [reminder.worker for reminder, _ in mailbox.sends] == ["jan.testowy"]


def test_odmowa_wysylki_przez_gmail_nie_ponawia_wysylki_do_konca_pory(tmp_path: Path) -> None:
    """Odmowa wysyłki przez Gmaila inna niż odrzucone hasło (np. dzienny limit) zamyka porę: następne minuty tej samej
    pory nie próbują znowu, a wynik dla widoku Raporty mówi o odmowie (US 47)."""

    mailbox = FakeMailbox(send_outcome=MailRefused("SMTPDataError"))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 8, 31))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]
    assert _reminder_result(centrum)["failure"] == "odmowa-wysylki"
    log = centrum.tool.log_path.read_text(encoding="utf-8")
    assert log.count("przypomnienia-porazka przyczyna=odmowa-wysylki typ=SMTPDataError") == 1


@pytest.mark.parametrize(
    ("started", "later"),
    [
        (datetime(2026, 11, 10, 21, 59), datetime(2026, 11, 10, 22, 0)),
        (datetime(2026, 11, 10, 17, 59), datetime(2026, 11, 10, 18, 0)),
        (datetime(2026, 11, 10, 21, 59), datetime(2026, 11, 11, 7, 0)),
        (datetime(2026, 11, 10, 21, 59), datetime(2026, 11, 11, 21, 0)),
    ],
    ids=["22-00", "poranna-do-wieczornej", "uspiony-do-rana", "uspiony-do-wieczora-innego-dnia"],
)
def test_seria_przypomnien_ktora_wyszla_poza_pore_czeka_z_reszta_na_nastepna_pore(
    tmp_path: Path, started: datetime, later: datetime
) -> None:
    """Gdy zegar w trakcie serii przypomnień wyjdzie poza porę, w której seria ruszyła (minęła 22:00 albo 18:00, laptop
    zasnął i obudził się rano albo wieczorem innego dnia), reszta serii nie idzie, a wysłane przypomnienie ma chwilę
    swojej wysyłki, nie początku sprawdzenia (ADR 0030 „nigdy w nocy”)."""

    class TickingMailbox(FakeMailbox):
        def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
            outcome = super().send(reminder, at)
            centrum.moment.append(later)
            return outcome

    first_send = started + timedelta(seconds=30)
    mailbox = TickingMailbox(during=lambda: centrum.moment.append(first_send))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    centrum.moment.append(started)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at) for reminder, at in mailbox.sends] == [("anna.kowalska", first_send.astimezone())]
    assert [(sent["worker"], sent["day"]) for sent in _reminder_result(centrum)["sent"]] == [("anna.kowalska", "2026-11-09")]


def test_odrzucone_haslo_przy_przypomnieniach_daje_zgloszenie_do_maksa_raz_w_porze(tmp_path: Path) -> None:
    """Odrzucone hasło aplikacji przy wysyłce przypomnienia Centrum zgłasza Maksowi samo, bez taty, i do końca pory
    nie pyta Gmaila znowu (US 47)."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    mailbox = FakeMailbox(send_outcome=PasswordRejected())
    centrum = entering_centrum(tmp_path, INTERMAX, surroundings=surroundings, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 9, 0))
    centrum.rhythm.tick()
    box = surroundings.report_box
    assert box.wait_until(lambda fake: len(fake.sent) == 1)
    centrum.client.stop()

    [issue] = box.sent
    assert issue.title.startswith("PRZYPOMNIENIA_HASLO_ODRZUCONE: Skrzynka raportów odrzuciła hasło")
    for secret in (JAN, ANNA, SKRZYNKA, HASLO):
        assert secret not in issue.body, secret
    assert len(mailbox.sends) == 1, "po odrzuconym haśle praca nie próbuje dalej w tej porze"
    assert _reminder_result(centrum)["failure"] == "haslo-odrzucone"


def test_praca_przypomnien_nie_blokuje_wpisania_raportow_ktore_biegnie_w_trakcie_wysylki(tmp_path: Path) -> None:
    """Praca przypomnień nie jest Uruchomieniem procesu: gdy czeka na Gmaila w trakcie wysyłki, tata klika „Wpisz
    raporty z maili”, a Wpisanie raportów startuje i kończy się, zanim wysyłka się skończy (US 46, ADR 0030)."""

    sending, release = threading.Event(), threading.Event()

    class HeldMailbox(FakeMailbox):
        def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
            sending.set()
            assert release.wait(30)
            return super().send(reminder, at)

    mailbox = HeldMailbox()
    centrum = entering_centrum(
        tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana routera")], reminder_mailbox=mailbox
    )
    _reminders_set_up(centrum.tool)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()
    check = threading.Thread(target=centrum.rhythm.tick, name="test-przypomnienia")
    check.start()
    try:
        assert sending.wait(30)
        view = _finished(centrum)
    finally:
        release.set()
        check.join(30)
    centrum.client.stop()

    assert view["result"]["result"] == "OK"
    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]


def _reminders_of(view: dict[str, Any], login: str) -> list[datetime]:
    """Chwile Przypomnień o raporcie za 9.11 przy dniu Wykonawcy ``login`` w widoku Raporty."""

    return [datetime.fromisoformat(moment) for moment in _worker(view, login)["reminders"]]


def test_widok_raporty_pokazuje_pory_przypomnien_przy_dniu_wykonawcy_a_brak_stopki_do_sprawdzenia_po_dodaniu_pliku(
    tmp_path: Path,
) -> None:
    """Kryterium #1351: po pracy przypomnień widok Raporty ma przy dniu 9.11 każdego Wykonawcy chwile wysłanych za ten
    dzień przypomnień, z „Wysłanych” i z tego sprawdzenia, bez przypomnienia za inny dzień; brak pliku stopki widok mówi
    do następnego sprawdzenia po dodaniu pliku, a odpowiedź nie ma adresów, tematu ani stopki (US 44–45, ADR 0030)."""

    for_other_day = SentReminder(frozenset({SenderAddress(JAN)}), date(2026, 11, 8), datetime(2026, 11, 9, 8, 0).astimezone())
    mailbox = FakeMailbox(sent=(for_other_day,))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum.tool, footer=None)
    centrum.client.start()
    _finished(centrum)
    before = _view(centrum)
    morning, evening = REMINDER_MORNING.astimezone(), datetime(2026, 11, 10, 18, 5).astimezone()

    centrum.moment.append(REMINDER_MORNING)
    centrum.rhythm.tick()
    after_morning = centrum.client.get("/api/report-entering/view")
    (centrum.tool.config / REMINDERS_FOOTER).write_text("Pozdrawiam\nTata\n", encoding="utf-8")
    mailbox.sent = (
        for_other_day,
        *(SentReminder(frozenset(reminder.recipients), reminder.day, at) for reminder, at in mailbox.sends),
    )
    centrum.moment.append(datetime(2026, 11, 10, 18, 5))
    centrum.rhythm.tick()
    after_evening = _view(centrum)
    centrum.client.stop()

    assert (_reminders_of(before, "jan.testowy"), before["reminders_without_footer"]) == ([], False)
    shown = after_morning.json()
    assert (_reminders_of(shown, "jan.testowy"), _reminders_of(shown, "anna.kowalska")) == ([morning], [morning])
    assert shown["reminders_without_footer"] is True
    assert _reminders_of(after_evening, "jan.testowy") == [morning, evening]
    assert after_evening["reminders_without_footer"] is False
    for secret in (JAN, ANNA, SKRZYNKA, "Przypomnienie: raport", "Pozdrawiam"):
        assert secret not in after_morning.text, secret


@pytest.mark.parametrize("content", [b"{\"schema_version\": 1, \"sent\": [", b"\xff\xfe nie JSON", b'{"schema_version": 2, "footer": "missing", "sent": []}'])
def test_nieczytelny_wynik_przypomnien_nie_psuje_widoku_raporty(tmp_path: Path, content: bytes) -> None:
    """Wynik pracy przypomnień, którego nie da się przeczytać (urwany, nie UTF-8, innej wersji), widok Raporty pomija:
    pokazuje wynik kliknięcia bez pór przypomnień i bez informacji o stopce, a nie odmowę (#1351)."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _finished(centrum)
    (centrum.tool.config / REMINDERS_RESULT).write_bytes(content)

    view = _view(centrum)

    assert (_reminders_of(view, "jan.testowy"), view["reminders_without_footer"]) == ([], False)
