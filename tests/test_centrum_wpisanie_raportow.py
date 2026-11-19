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
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import email
from email.message import EmailMessage
import email.policy
import imaplib
import json
from pathlib import Path
import shutil
import smtplib
import threading
from typing import Any, Final

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
import pytest

from rozliczenia.activity_legend import ActivityCode, ActivityLegend, FixedColumn, NumberOutOfRange
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.intermax_replace import LOCAL_DISK
from rozliczenia.public_holidays import public_holidays
from rozliczenia.tool_files import (
    REMINDERS_RESULT,
    REMINDERS_SCHEDULES,
    REPORT_ENTERING_DECISIONS,
    REPORT_ENTERING_RESULT,
    REPORT_ENTERING_STATE,
)
from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.contract.common import Message
from rozliczenia.centrum.run_logs import LoggedActivityLegend
from rozliczenia.centrum.settings.activity_legend import LEGEND, LEGEND_FILE
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.migrations.reminders import OLD_FOOTER_FILE, OLD_ROLLOUT_FILE
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.worker_list import WorkerEntry, WorkerList
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxAccess,
    InboxUnreachable,
    MailRefused,
    MailSent,
    PasswordRejected,
    SentReminders,
)
from rozliczenia.worker_reports import (
    AddBar,
    ConflictingVerdicts,
    FaultyDescription,
    Login,
    MailId,
    OrderNumber,
    Reminder,
    ReportEntry,
    ReportMail,
    ReportSubject,
    SenderAddress,
    SentReminder,
    SubjectFault,
    UnknownNumber,
    UnreadableSubject,
    Verdict,
)
from rozliczenia.worker_reports.reasons import reason

from atrapy.intermax import ADDRESS, CONTRACT_NUMBER, DATE, FIRST, HEADERS, LAST, NUMBER, ORDER_SHEET, WORKER, Intermax, Order
from atrapy.preparation import COMPLETED_WITHOUT_CODES, PERIOD, incomplete_period_rows
from atrapy.settlement import worker_list, write_worker_list
from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, AtrapaSmtp, FakeInbox, FakeMailbox
from atrapy.workbooks import rewrite_parts
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access, without_reading
from tests.fixtures.centrum import (
    ROOT,
    CentrumClient,
    FakeGitHub,
    ToolDirectory,
    finished_view,
    run_events,
    views_until,
    write_report_key,
)
from tests.fixtures.centrum_intermax import (
    ENTERING_NOW,
    ENTERING_PERIOD,
    REGISTER_NAME,
    SENDERS,
    WORKERS,
    EnteringCentrum,
    entering_centrum,
    open_in_excel,
    report,
)
from tests.fixtures.centrum_processes import Surroundings, preparing_centrum
from tests.fixtures.intermax_disk import denied, failing_replace
from tests.fixtures.znane_luki import assert_znane_luki, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

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
    zapisem bez Kopii INTERMAX; karta pokazuje liczbę wpisanych, a Historia ma Uruchomienie. Uruchomienie nie potwierdza
    Gotowości, bo ta dotyczy Pliku zbiorczego przed Rozliczeniami pracowników."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m rt2")])
    before = _cells(centrum.register)

    setup = centrum.setup()
    view = _finished(centrum)
    history = centrum.client.get("/api/metrics").json()

    assert setup == {
        "reminder": "Zapisz i zamknij INTERMAX w Excelu",
        "blocker": None,
        "open_in_excel": [],
        "last": None,
    }
    assert view["result"]["result"] == "OK"
    assert (view["run"]["period"], view["run"]["confirms_readiness"]) == (ENTERING_PERIOD, False)
    assert view["result"]["summary"]["figures"] == [
        {"label": "Wpisane", "value": 1, "unit": "count"},
        {"label": "Problemy", "value": 0, "unit": "count"},
        {"label": "Raporty", "value": 1, "unit": "count"},
    ]
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "inst20m rt2")}
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


def _workers(register: Path) -> dict[int, object]:
    """``NUMER ZL.`` → ``WYKONAWCA`` każdego wiersza arkusza zleceń z numerem."""

    sheet = load_workbook(register)[ORDER_SHEET]
    column = FIRST + HEADERS.index("WYKONAWCA")
    return {
        cell.value: sheet.cell(cell.row, column).value
        for row in sheet.iter_rows(min_row=2)
        for cell in row
        if isinstance(cell.value, int) and cell.value >= 40000000
    }


def test_raport_wykonawcy_trafia_do_zlecenia_spod_drugiego_loginu_dopisanego_w_ustawieniach(tmp_path: Path) -> None:
    """US 29 (#1474): tata dopisuje Wykonawcy w Ustawieniach drugi login z INTERMAX. Raport wykonawcy z jego adresu
    wpisuje się też w zlecenie spod drugiego loginu, które zostaje w miejscu, bez Przeniesienia zlecenia pod pierwszy."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.nowy", 40000005),
            _order(9, 11, "anna.kowalska", 40000002),
        ),
    )
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000001 tak montaż\n40000005 tak wymiana routera")])
    before, workers_before = _cells(centrum.register), _workers(centrum.register)
    second = centrum.client.put(
        "/api/settings/workers/jan.testowy",
        json={"logins": ["jan.testowy", "jan.nowy"], "name": "Jan Testowy", "addresses": [JAN]},
    )

    view = _finished(centrum)

    assert second.status_code == 200, second.json()
    assert view["result"]["summary"]["figures"][0] == {"label": "Wpisane", "value": 2, "unit": "count"}
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "montaż"), 40000005: ("tak", "wymiana routera")}
    assert _workers(centrum.register) == workers_before


def test_logi_maja_wpisy_i_zmiany_bez_adresow_tematow_i_tresci_maili_a_telefon_w_czynnosciach_zamaskowany(
    tmp_path: Path,
) -> None:
    """Logi Wpisania raportów przechodzą przez strażnika Reguły danych: adres nadawcy, temat i treść maila spoza
    Wpisów nie mają w nich żadnego pola (Raport spoza listy adresów nie zostawia w nich swojej treści), a telefon w
    czynnościach jest zamaskowany (ADR 0025, ADR 0028); Błąd opisu tego Wpisu ma w Logach sam powód z kodem, bez słów
    zwykłego opisu (ADR 0039, ADR 0041)."""

    activities = "instutp40m wymiana routera, klient tel. 600 100 200"
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
    assert entering["mails"][0]["entries"][0]["activities"] == "instutp40m wymiana routera, klient tel. [telefon]"
    assert [change["value"] for change in entering["changes"]] == ["tak", "instutp40m wymiana routera, klient tel. [telefon]"]
    assert entering["problems"] == [
        {"kind": "unknown_sender", "mail": entering["mails"][1]["mail"], "day": "2026-11-09"},
        {
            "kind": "faulty_description",
            "worker": "jan.testowy",
            "day": "2026-11-09",
            "number": "40000001",
            "reasons": ["kod z liczbą spoza przedziałów (instutp40m)"],
        },
    ]
    assert (entering["rollout_before"], entering["rollout"], entering["written"]) == (None, "2026-11-09", 2)
    assert _cells(centrum.register)[40000001] == ("tak", activities), "do INTERMAX trafia pełny Wpis"


@pytest.mark.parametrize(
    ("subject", "fault", "day"),
    [
        pytest.param("Raport bez daty", "no_date", None, id="bez-daty"),
        pytest.param("Raport 09.11.2026 Kowalski", "other_words", "2026-11-09", id="inne-slowa"),
        pytest.param("Raport: 09.11.2026", "other_text", "2026-11-09", id="inny-tekst"),
        pytest.param("Raport 09.11", "no_year", "2026-11-09", id="bez-roku"),
        pytest.param("Raport 09112026", "date_form", None, id="postac-daty"),
        pytest.param("Raport 09.11.226", "year_digits", None, id="cyfry-roku"),
        pytest.param("Raport 31.11.2026", "not_a_day", None, id="nie-dzien"),
    ],
)
def test_logi_maja_powod_kazdego_bledu_tematu_i_dzien_bez_tematu(tmp_path: Path, subject: str, fault: str, day: str | None) -> None:
    """Każdy powód błędu tematu, który daje dziś rdzeń, ma swoje słowo w Logach (mail i problem), mail ma dzień z
    tematu, gdy da się go przeczytać, a problem dzień, za który Centrum liczy raport (ADR 0041: Jan ma zlecenie tylko
    9.11), a sam temat do Logów nie trafia (ADR 0028)."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, subject, "40000001 tak wymiana")])

    _finished(centrum)

    [logs] = centrum.run_logs()
    entering = logs["report_entering"]
    assert [(mail["kind"], mail["fault"], mail["day"]) for mail in entering["mails"]] == [("unreadable", fault, day)]
    assert [(problem["kind"], problem["fault"], problem["day"]) for problem in entering["problems"]] == [
        ("unreadable_subject", fault, "2026-11-09")
    ]
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


def test_kopia_wejscia_ma_date_zlecenia_ze_sladem_przesuniecia_choc_w_drugim_polozeniu_stoi_pod_adresem(tmp_path: Path) -> None:
    """Uporządkowany wiersz z datą z godziną w kolumnie A (ślad przesunięcia) pamięć zna w obu położeniach, więc Kopia
    nie ma komórek, które w przesunięciu stoją pod ``ADRES`` i ``NUMER UMOWY``; ``DATA GODZ. POCZ.`` zostaje, bo bez
    niej odtworzenie nie powtórzy Uruchomienia (ADR 0025)."""

    traced = Order(datetime(2026, 11, 9, 9), "jan.testowy", 40000001, cells=((NUMBER, 40000001), (1, datetime(2026, 11, 9, 9))))
    centrum = entering_centrum(tmp_path, Intermax(ordered=(traced,), raw=()), [report(JAN, SUBJECT, "40000001 tak wymiana")])

    _finished(centrum)

    [logs] = centrum.run_logs()
    [copied] = logs["input_copy"]
    [row] = copied["sheets"][0]["rows"]
    assert row["cells"]["C"] == {"type": "datetime", "text": "2026-11-09T09:00:00"}
    assert "I" not in row["cells"], "NUMER ZL. w przesunięciu stoi pod NUMER UMOWY"


def test_dziewieciocyfrowy_numer_zlecenia_z_intermax_wychodzi_do_logow_a_numer_z_tresci_maila_jest_pod_straznikiem(
    tmp_path: Path,
) -> None:
    """``NUMER ZL.`` z wiersza INTERMAX może wyjść do Logów (ADR 0025) także z 9 cyframi, które strażnik maskuje jako
    telefon w tekście: pamięć własnych wpisów w Logach drugiego kliknięcia ma go jako liczbę. Numer z treści maila
    zostaje tekstem pod strażnikiem, więc 9 cyfr bez zera z przodu jest w nim zamaskowane, bo ten sam kształt ma
    telefon klienta na początku linii raportu; odtworzenie dostanie to jako granicę (#1233)."""

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


def test_numer_z_zerem_z_przodu_z_tresci_maila_jest_w_logach_a_telefon_na_poczatku_linii_raportu_nie(
    tmp_path: Path,
) -> None:
    """Wykonawca pisze w raporcie ``NUMER ZL.`` z zerem z przodu, czyli 9 cyfr, a żaden polski telefon nie zaczyna się od
    0: Logi mają ten numer we Wpisie i w problemie nieznanego numeru w postaci z maila, więc odtworzenie powtarza
    kliknięcie. Telefon klienta na początku linii raportu rdzeń też czyta jako Wpis, a w Logach jest on ``[telefon]``."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 14043137),), raw=())
    body = "014043137 tak montaż, klient prosi o kontakt\n600123456 po 17"
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, body)])

    run = _finished(centrum)

    [entering] = [entry["report_entering"] for entry in centrum.run_logs() if entry["run_id"] == run["run"]["id"]]
    assert [entry["number"] for entry in entering["mails"][0]["entries"]] == ["014043137", "[telefon]"]
    assert sorted(problem["number"] for problem in entering["problems"]) == ["014043137", "[telefon]"]
    assert "600123456" not in json.dumps(entering, ensure_ascii=False)


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
            inbox=ImapInbox(lambda: read_snapshot(tool.config).inbox, connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port)),
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
    # Bez adresu na Liście Wykonawców Wpisanie raportów odmawia startu, zanim zapyta o miejsce „jedno naraz”.
    write_worker_list(centrum.tool.worker_list, worker_list(addresses={"adrian.testowy": [JAN]}))
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


def test_logi_zatrzymania_przy_zapisie_maja_wpisy_i_komorki_do_wpisania_bez_liczby_wpisanych(tmp_path: Path) -> None:
    """Zatrzymanie przy zapisie przychodzi po rdzeniu raportów, więc Logi mają Wpisy i komórki, które kliknięcie miało
    wpisać, a liczby wpisanych komórek nie mają, bo INTERMAX nie został zmieniony: po niej odtworzenie poznaje, że
    Zatrzymanie taty zależało od jego dysku."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    centrum.disk.replace, _ = failing_replace(denied)

    view = _stopped_view(centrum)

    [entering] = [logs["report_entering"] for logs in centrum.run_logs() if logs["run_id"] == view["run"]["id"]]
    assert [entry["number"] for mail in entering["mails"] for entry in mail["entries"]] == ["40000001"]
    assert [change["value"] for change in entering["changes"]] == ["tak", "wymiana"]
    assert entering["written"] is None


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
        pytest.param(lambda state: state.write_bytes(b'{"schema_version": 1, "own": ["\xff"]}'), id="poza-utf8"),
        pytest.param(
            lambda state: state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "rollout": "2026-11-09",
                        "own": [
                            {"number": "40000001", "day": "2026-11-09", "worker": "jan.testowy", "column": "SKUTECZNE", "value": value}
                            for value in ("tak", "nie")
                        ],
                    }
                ),
                encoding="utf-8",
            ),
            id="dwa-wpisy-jednej-komorki",
        ),
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
    nie da się odczytać (zły JSON, bajty spoza UTF-8, dwie różne wartości jednej komórki zlecenia), zatrzymuje kliknięcie
    do Maksa, zamiast liczyć się jak pusta pamięć. Przy zepsutych pamięci i decyzjach „Zostaw moją” Komunikat nazywa
    pamięć, bo proces czyta ją pierwszą."""

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


def test_wynik_niezapisany_trafia_do_pliku_przy_widoku_raporty_po_odzyskaniu_dostepu_i_zostaje_po_ponownym_otwarciu_centrum(
    tmp_path: Path,
) -> None:
    """Gdy pliku wyniku Wpisania raportów nie da się zapisać, widok Raporty pokazuje wynik z tej pracy Centrum, a
    pierwszy widok po odzyskaniu dostępu zapisuje go do pliku: po zamknięciu i ponownym otwarciu Centrum widok jest ten
    sam."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    result = centrum.tool.config / REPORT_ENTERING_RESULT
    centrum.fake_inbox.during = result.mkdir

    _finished(centrum)
    held = _view(centrum)
    result.rmdir()
    shown = _view(centrum)
    centrum.restart()

    assert _view(centrum) == shown == held
    assert _worker(held, "jan.testowy")["entered"] == 1


def test_reczna_zmiana_komorki_miedzy_kliknieciami_wygrywa_z_poprawka_a_nietkniety_wlasny_wpis_ja_dostaje(
    tmp_path: Path,
) -> None:
    """Kryterium #1230: po pierwszym kliknięciu tata zmienia w INTERMAX ``SKUTECZNE`` Jana, a rano Jan i Anna przysyłają
    poprawki. Ręczne ``nie`` taty zostaje z różnicą w Logach i w liczbie problemów, a własne wpisy, których nikt nie
    zmienił (opis Jana, oba Anny), dostają poprawkę; pamięć ma po kliknięciu wartości z poprawek bez ręcznej."""

    anna = SENDERS["anna.kowalska"]
    reports = [report(JAN, SUBJECT, "40000001 tak inst20m"), report(anna, SUBJECT, "40000002 tak spawpg")]
    centrum = entering_centrum(tmp_path, INTERMAX, reports)
    _finished(centrum)
    _tata_writes(centrum.register, 40000001, "nie")
    centrum.moment.append(datetime(2026, 11, 10, 8))
    centrum.fake_inbox.outcome = [
        *reports,
        report(JAN, SUBJECT, "40000001 tak inst25m", at=datetime(2026, 11, 10, 7, 40)),
        report(anna, SUBJECT, "40000002 nie klient nieobecny", at=datetime(2026, 11, 10, 7, 45)),
    ]

    second = _finished(centrum)

    cells = _cells(centrum.register)
    assert (cells[40000001], cells[40000002]) == (("nie", "inst25m"), ("nie", "klient nieobecny"))
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
        ("40000001", "CZYNNOŚCI ZREALIZOWANE", "inst25m"),
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


def test_zapis_na_scalone_komorki_zlecenia_zatrzymuje_do_maksa_a_logi_maja_zaplanowane_wpisy(tmp_path: Path) -> None:
    """Gdy zapis trafia na układ, do którego narzędzie nie wpisuje (``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` zlecenia
    Jana scalone w jedną komórkę), kliknięcie zatrzymuje się do Maksa z INTERMAX bajt w bajt, a Logi Uruchomienia
    mają wpisy zaplanowane z Raportu, z których Maks odtworzy Uruchomienie."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")])
    merged = f'<mergeCells count="1"><mergeCell ref="{get_column_letter(SUCCESSFUL)}3:{get_column_letter(COMPLETED)}3"/>'
    rewrite_parts(
        centrum.register,
        lambda name, data: data.replace(b"<hyperlinks>", f"{merged}</mergeCells><hyperlinks>".encode(), 1)
        if name == "xl/worksheets/sheet2.xml"
        else data,
    )
    before = centrum.register.read_bytes()

    result = _stopped(centrum)

    assert (result["stop_kind"], result["stops"][0]["what"]) == (
        "for_maks",
        "Zlecenia mają układ, do którego narzędzie nie wpisuje raportów. INTERMAX nie został zmieniony.",
    )
    assert centrum.register.read_bytes() == before
    [logs] = centrum.run_logs()
    assert [(change["row"], change["column"], change["value"]) for change in logs["report_entering"]["changes"]] == [
        (3, "SKUTECZNE", "tak"),
        (3, "CZYNNOŚCI ZREALIZOWANE", "wymiana"),
    ]


def _unreadable_border(register: Path) -> None:
    rewrite_parts(
        register,
        lambda name, data: data.replace(b'<left style="thin" />', b'<left style="nieznany" />', 1) if name == "xl/styles.xml" else data,
    )


@pytest.mark.parametrize(
    ("text", "spoil", "stop"),
    [
        pytest.param(
            "40000001 tak wymiana\x01routera",
            lambda register: None,
            ("for_maks", "Zapis odrzucił komórki, które narzędzie chciało wpisać. INTERMAX nie został zmieniony."),
            id="opis-ze-znakiem-spoza-xml",
        ),
        pytest.param(
            "40000001 tak wymiana",
            _unreadable_border,
            ("for_tata", "Nie można odczytać INTERMAX jako skoroszytu Excela. INTERMAX nie został zmieniony."),
            id="styl-ramki-ktorego-zapis-nie-czyta",
        ),
    ],
)
def test_zapis_odrzucony_albo_nieczytelny_przy_zapisie_zatrzymuje_a_logi_maja_zaplanowane_wpisy(
    tmp_path: Path, text: str, spoil: Callable[[Path], object], stop: tuple[str, str]
) -> None:
    """Zapis odrzuca komórkę z tekstem, którego komórka nie przyjmie (znak spoza XML z treści maila), albo nie czyta
    stylów INTERMAX, które odczyt pominął: kliknięcie zatrzymuje się z INTERMAX bajt w bajt, a Logi Uruchomienia mają
    wpisy zaplanowane z Raportu, z których Maks odtworzy Uruchomienie."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, text)])
    spoil(centrum.register)
    before = centrum.register.read_bytes()

    result = _stopped(centrum)

    assert (result["stop_kind"], result["stops"][0]["what"]) == stop
    assert centrum.register.read_bytes() == before
    [logs] = centrum.run_logs()
    assert [(change["row"], change["column"]) for change in logs["report_entering"]["changes"]] == [
        (3, "SKUTECZNE"),
        (3, "CZYNNOŚCI ZREALIZOWANE"),
    ]


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


ACCESS_MISSING = (
    "Wpisanie raportów nie jest jeszcze ustawione: w folderze config brakuje hasła do skrzynki raportów (plik "
    "skrzynka-raportow.txt). Dopisze je Maks."
)
ADDRESSES_MISSING = "Na Liście Wykonawców nikt nie ma jeszcze adresu. Dopisz adresy Wykonawców w Ustawieniach."


@pytest.mark.parametrize(
    ("access", "addresses", "sentence"),
    [
        pytest.param("missing", True, ACCESS_MISSING, id="bez-hasla"),
        pytest.param("ready", False, ADDRESSES_MISSING, id="bez-adresow"),
        pytest.param("missing", False, ACCESS_MISSING, id="bez-obu"),
    ],
)
def test_bez_pliku_hasla_albo_adresow_wykonawcow_karta_mowi_czego_brakuje_a_start_jest_odrzucony(
    tmp_path: Path, access: InboxAccess, addresses: bool, sentence: str
) -> None:
    """US 51: bez pliku dostępu do skrzynki raportów albo bez adresu żadnego Wykonawcy na Liście Wykonawców karta mówi,
    czego brakuje, a start jest odrzucony tym samym zdaniem, bez Uruchomienia i bez odczytu skrzynki; brak hasła mówi
    pierwszy, bo dopisuje je Maks."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana")], access=access)
    if not addresses:
        write_worker_list(centrum.tool.worker_list, worker_list(WORKERS))

    setup = centrum.setup()
    started = centrum.start()

    assert setup["blocker"] == sentence
    assert (started.status_code, started.json()) == (409, {"message": sentence})
    assert centrum.fake_inbox.days == []
    assert centrum.run_logs() == []


def test_klikniecie_przy_zlej_liscie_wykonawcow_biegnie_na_ostatniej_dobrej_z_ostrzezeniem_na_karcie(tmp_path: Path) -> None:
    """DESIGN §4.3 dla Wpisania raportów (przegląd #1569 r2, D1): plik Listy Wykonawców dostaje złą treść po odczycie
    Ustawień, więc kliknięcie wpisuje raporty adresów z ostatniej dobrej listy, a karta mówi o tym ostrzeżeniem startu."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak wymiana routera")])
    assert centrum.client.get("/api/settings").json()["workers"]["state"] == "good"
    centrum.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")

    view = _finished(centrum)

    warning = Message.of(
        diagnosis_messages.worker_list_last_good(settings_messages.damaged(WORKERS_FILE, settings_messages.MAKS_FIXES))
    ).model_dump()
    assert (view["result"]["warnings"][:1], warning["setting"]) == ([warning], "wykonawcy")
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana routera")


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


def test_nowy_numer_jest_dopisany_a_jedyne_zlecenie_z_innego_dnia_przechodzi_na_dzien_z_tematu(
    tmp_path: Path,
) -> None:
    """ADR 0029: numer z 8 cyframi spoza zleceń (wcześniej problem, US 27–30 speca #1224) to Zlecenie dopisane z raportu
    (#1354), a Wpis Anny do zlecenia Jana przegrywa ze świeższym mailem Jana. Numer zlecenia Jana z 8.11 w Raporcie z
    9.11 to jedyny niezgodny Wpis tego raportu, więc zlecenie przechodzi na 9.11 z Wpisem (#1350), bez problemu."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = _cells(centrum.register)

    view = _click_at(
        centrum,
        ENTERING_NOW,
        [
            report(ANNA, SUBJECT, "40000001 tak spawpg", at=datetime(2026, 11, 9, 17)),
            report(JAN, SUBJECT, "40000010 tak inst25m"),
            report(JAN, SUBJECT, "30000077 tak spawez"),
            report(JAN, SUBJECT, "40000001 tak inst20m rt2"),
        ],
    )

    assert _cells(centrum.register) == {
        **before,
        40000001: ("tak", "inst20m rt2"),
        40000010: ("tak", "inst25m"),
    }
    assert _entering(centrum, view)["problems"] == []
    assert [(added["number"], added["worker"]) for added in _entering(centrum, view)["added"]] == [(30000077, "jan.testowy")]
    assert _entering(centrum, view)["moves"] == [{"sheet": ORDER_SHEET, "row": 2, "day": "2026-11-09", "worker": "jan.testowy"}]
    assert view["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 0, "unit": "count"}


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
    """US 15–16: Raport z poprawnym tematem z nowego adresu Jana daje problem nieznanego nadawcy; tata dopisuje adres na
    Liście Wykonawców i następne kliknięcie wpisuje ten sam mail bez innej pracy."""

    new_address = "jan.nowy@przyklad.invalid"
    centrum = entering_centrum(tmp_path, INTERMAX, [report(new_address, SUBJECT, "40000001 tak inst20m rt2")])
    before = _cells(centrum.register)

    first = _finished(centrum)
    listed = {"jan.testowy": [JAN, new_address], "anna.kowalska": [ANNA]}
    write_worker_list(centrum.tool.worker_list, worker_list(WORKERS, listed))
    second = _finished(centrum)

    assert [problem["kind"] for problem in _entering(centrum, first)["problems"]] == ["unknown_sender"]
    assert _entering(centrum, second)["problems"] == []
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "inst20m rt2")}
    assert new_address not in json.dumps(centrum.run_logs(), ensure_ascii=False)


NEW_ADDRESS = "jan.nowy@przyklad.invalid"


def _assign(centrum: EnteringCentrum, login: str, address: str) -> Any:
    """„Przypisz do Wykonawcy…” z widoku Raporty: adres nieznanego nadawcy u Wykonawcy z loginem ``login``."""

    return centrum.client.post(f"/api/settings/workers/{login}/addresses", json={"address": address})


def _addresses(centrum: EnteringCentrum) -> dict[str, list[str]]:
    """Adresy Wykonawców z sekcji Wykonawcy po pierwszym loginie."""

    workers = centrum.client.get("/api/settings").json()["workers"]["workers"]
    return {worker["logins"][0]: worker["addresses"] for worker in workers}


def _worker_rows(centrum: EnteringCentrum) -> list[dict[str, Any]]:
    """Wiersze Historii Ustawień o Liście Wykonawców, od najnowszego."""

    return [row for row in centrum.client.get("/api/settings/history").json()["rows"] if row["file"] == WORKERS_FILE]


def test_tata_przypisuje_nieznanego_nadawce_do_wykonawcy_a_nastepne_wpisanie_raportow_rozpoznaje_jego_raport(
    tmp_path: Path,
) -> None:
    """US 25, ADR 0028: Raport z nowego adresu Jana stoi w widoku Raporty jako nieznany nadawca z samym dniem, adresem i
    powodem, bez tematu i treści maila. Tata przypisuje adres Janowi: adres dopisuje się na Liście Wykonawców, nadawca w
    widoku Raporty jest przypisany do Jana jeszcze przed następnym kliknięciem, a następne kliknięcie wpisuje ten sam mail
    bez innej pracy."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(NEW_ADDRESS, SUBJECT, "40000001 tak inst20m rt2")])
    before = _cells(centrum.register)
    _finished(centrum)
    first = _view(centrum)

    assigned = _assign(centrum, "jan.testowy", NEW_ADDRESS)
    shown = _view(centrum)
    second = _finished(centrum)

    assert first["unknown_senders"] == [
        {
            "day": "2026-11-09",
            "sender": NEW_ADDRESS,
            "reason": "Raport wykonawcy z 09.11.2026 przyszedł z adresu, którego nie ma na Liście Wykonawców, więc Centrum "
            "go nie wpisało. Przypisz ten adres Wykonawcy, a następne kliknięcie go wpisze.",
            "worker": None,
        }
    ]
    shown_first = json.dumps(first, ensure_ascii=False)
    assert SUBJECT not in shown_first and "inst20m rt2" not in shown_first, "widok Raporty bez tematu i treści maila"
    assert assigned.status_code == 200, assigned.json()
    assert _addresses(centrum)["jan.testowy"] == [JAN, NEW_ADDRESS]
    assert [found["worker"] for found in shown["unknown_senders"]] == ["jan.testowy"]
    assert _entering(centrum, second)["problems"] == []
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "inst20m rt2")}


def test_adres_innego_wykonawcy_nie_przypisuje_sie_a_cofniecie_przypisania_przywraca_nieznanego_nadawce(
    tmp_path: Path,
) -> None:
    """US 25, 28: adresu, który ma już inny Wykonawca, nie da się przypisać: odmowa przy polu adresu, a Lista Wykonawców i
    Historia zostają bez zmian, tak samo przy Wykonawcy, którego już nie ma; adres, który Wykonawca już ma, niczego nie
    zmienia. Przypisanie ma wiersz Historii z „Cofnij”, które zdejmuje adres, więc nadawca w widoku Raporty znowu jest
    nieznany."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(NEW_ADDRESS, SUBJECT, "40000001 tak wymiana routera")])
    _finished(centrum)
    listed_before = centrum.tool.worker_list.read_bytes()

    refused = _assign(centrum, "anna.kowalska", JAN.upper())
    gone = _assign(centrum, "nikt.taki", NEW_ADDRESS)
    own = _assign(centrum, "jan.testowy", JAN.upper())
    listed_after_refusal = centrum.tool.worker_list.read_bytes()
    rows_after_refusal = _worker_rows(centrum)
    assigned = _assign(centrum, "anna.kowalska", NEW_ADDRESS)
    [row] = _worker_rows(centrum)
    undone = centrum.client.post(f"/api/settings/history/{row['id']}/undo")

    assert (refused.status_code, refused.json()) == (
        422,
        {"message": settings_messages.worker_address_repeated(), "field": "adresy[1]"},
    )
    assert (gone.status_code, gone.json()["message"]) == (422, settings_messages.worker_unknown())
    assert (own.status_code, own.json()["change"]) == (200, None)
    assert listed_after_refusal == listed_before
    assert rows_after_refusal == []
    assert assigned.status_code == 200, assigned.json()
    assert (row["id"], row["section"], row["undoable"]) == (assigned.json()["change"], "wykonawcy", True)
    assert undone.status_code == 200, undone.json()
    assert _addresses(centrum)["anna.kowalska"] == [ANNA]
    assert [found["worker"] for found in _view(centrum)["unknown_senders"]] == [None]


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
    Pliku zbiorczego. Gdy tata go przygotuje, Raport Anny z 9.11 się nie wpisuje, choć rdzeń go czyta (jego niezgodne
    Wpisy mówiłyby o dniach otwartych, #1350), skrzynka jest czytana od dziś, a Kopia wejścia ma wiersze INTERMAX od
    ``Window.start``, więc dalej zlecenia z 9.11: po nich rdzeń poznaje zlecenie z okresu z Plikiem zbiorczym, którego nie
    przenosi."""

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
    assert [mail["day"] for mail in _entering(centrum, closed)["mails"]] == ["2026-11-09"]
    assert (_entering(centrum, closed)["changes"], _entering(centrum, closed)["problems"]) == ([], [])
    assert [_copied_numbers(centrum, view) for view in (still_open, closed)] == [[40000002, 40000001]] * 2


def test_te_same_maile_w_innej_kolejnosci_i_drugie_klikniecie_daja_ten_sam_wynik(tmp_path: Path) -> None:
    """Kryterium #1229: kolejność, w jakiej skrzynka oddaje maile, nie zmienia wpisanych komórek ani problemów, a drugie
    kliknięcie z tymi samymi mailami niczego nie zmienia i ma te same problemy. Wpis Anny do zlecenia Jana przegrywa ze
    świeższym mailem Jana, więc zlecenie zostaje u Jana bez problemu (ADR 0029)."""

    mails = [
        report(JAN, SUBJECT, "40000001 tak inst20m", at=datetime(2026, 11, 9, 17)),
        report(JAN, SUBJECT, "40000001 nie klient nieobecny", at=datetime(2026, 11, 9, 17, 30)),
        report(ANNA, SUBJECT, "40000002 tak spawpg", at=datetime(2026, 11, 9, 17, 10)),
        report(ANNA, SUBJECT, "40000001 tak spawpg", at=datetime(2026, 11, 9, 17, 20)),
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
    centrum = entering_centrum(tmp_path, intermax, [report(ANNA, SUBJECT, "40000001 tak spawgnd")])
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
    assert _cells(centrum.register)[40000001] == ("tak", "spawgnd")
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
    shown_codes = text.replace('"activities": "spawgnd"', "").replace('"codes": ["spawgnd"]', "")
    assert "Ulica" not in text and "UM-" not in text and "spawgnd" not in shown_codes
    assert (_entering(centrum, again)["changes"], _entering(centrum, again)["moves"]) == ([], [])
    assert centrum.register.read_bytes() == after
    assert _worker(_view(centrum), "anna.kowalska")["notes"] == anna["notes"]


def _started(register: Path, number: int) -> tuple[object, str]:
    """``DATA GODZ. POCZ.`` wiersza zlecenia ``number`` i jej format liczby."""

    sheet = load_workbook(register)[ORDER_SHEET]
    [row] = [cell.row for cell in sheet[get_column_letter(NUMBER)] if cell.value == number]
    return sheet.cell(row, DATE).value, sheet.cell(row, DATE).number_format


TWO_DAYS = Intermax(
    ordered=(
        _order(8, 9, "anna.kowalska", 40000001),
        _order(8, 10, "jan.testowy", 40000002),
        _order(8, 12, "jan.testowy", 40000004),
        _order(9, 9, "anna.kowalska", 40000003),
    ),
    raw=(),
)
"""8.11: segment Anny i segment Jana z dwoma zleceniami; 9.11: segment Anny; pusty wiersz pod każdym segmentem, żółty
wiersz pod dniem 9.11."""


def test_klikniecie_przenosi_zlecenie_na_dzien_z_tematu_z_ta_sama_godzina_i_informacja_w_okienku_po_obu_stronach(
    tmp_path: Path,
) -> None:
    """Kryteria #1350 (ADR 0029): Raport Jana za 9.11 z jednym zleceniem z 8.11. Kliknięcie zmienia w INTERMAX dzień w
    ``DATA GODZ. POCZ.`` na 9.11 z tą samą godziną i formatem daty i stawia wiersz w nowym segmencie Jana 9.11 (za
    Anną, alfabetycznie), z wyglądem, Hiperłączem i Wpisem; segment Jana 8.11 zostaje z drugim zleceniem, a pusty
    wiersz między dniami i żółty wiersz zostają. Okienko dnia pokazuje „przeniesione z 8.11” u Jana 9.11 pod zleceniem
    i „przeniesione na 9.11” u Jana 8.11 osobnym wierszem; drugie kliknięcie niczego nie zmienia."""

    centrum = entering_centrum(tmp_path, TWO_DAYS)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    look, (_, date_format) = _order_look(centrum.register, 40000002), _started(centrum.register, 40000002)
    assert _day_rows(centrum.register, 9) == [
        (40000001, "anna.kowalska"),
        "pusty",
        (40000002, "jan.testowy"),
        (40000004, "jan.testowy"),
        "pusty",
        (40000003, "anna.kowalska"),
        "pusty",
        "żółty",
    ]

    view = _click_at(centrum, ENTERING_NOW, [report(JAN, SUBJECT, "40000002 tak spawgnd")])
    shown = _view(centrum)
    after = centrum.register.read_bytes()
    again = _finished(centrum)

    assert _day_rows(centrum.register, 10) == [
        (40000001, "anna.kowalska"),
        "pusty",
        (40000004, "jan.testowy"),
        "pusty",
        (40000003, "anna.kowalska"),
        "pusty",
        (40000002, "jan.testowy"),
        "pusty",
        "żółty",
    ]
    assert _started(centrum.register, 40000002) == (datetime(2026, 11, 9, 10), date_format)
    assert _started(centrum.register, 40000004) == (datetime(2026, 11, 8, 12), date_format)
    assert _order_look(centrum.register, 40000002) == look
    assert _cells(centrum.register)[40000002] == ("tak", "spawgnd")
    entering = _entering(centrum, view)
    assert entering["moves"] == [{"sheet": ORDER_SHEET, "row": 4, "day": "2026-11-09", "worker": "jan.testowy"}]
    assert entering["problems"] == []
    target, source = _worker(shown, "jan.testowy"), _worker(shown, "jan.testowy", "2026-11-08")
    assert target["notes"] == [{"number": "40000002", "text": "przeniesione z 8.11"}]
    assert [order["number"] for order in target["orders_detail"]] == ["40000002"]
    assert source["notes"] == [{"number": "40000002", "text": "przeniesione na 9.11"}]
    assert [order["number"] for order in source["orders_detail"]] == ["40000004"]
    assert (target["problems"], source["problems"]) == ([], [])
    assert (_entering(centrum, again)["changes"], _entering(centrum, again)["moves"]) == ([], [])
    assert centrum.register.read_bytes() == after


def test_zamiana_jedynych_zlecen_dwoch_dni_w_jednym_kliknieciu_przenosi_oba_a_drugie_klikniecie_niczego_nie_zmienia(
    tmp_path: Path,
) -> None:
    """Przegląd #1367 r1 (Ważne 1): 8.11 ma jedno zlecenie (Anny). W jednym kliknięciu Anna przysyła Raport za 9.11 z
    nim, a Jan Raport za 8.11 ze swoim zleceniem z 9.11. Oba dni są Dniami uporządkowanymi przed kliknięciem, więc
    kliknięcie przenosi oba zlecenia (zlecenie Jana staje na miejscu dnia 8.11) i wpisuje do nich Wpisy, zamiast
    zatrzymać całe Wpisanie raportów odrzuceniem zapisu, a drugie kliknięcie z tymi samymi mailami niczego nie zmienia."""

    intermax = Intermax(
        ordered=(
            _order(8, 9, "anna.kowalska", 40000001),
            _order(9, 10, "jan.testowy", 40000002),
            _order(9, 11, "anna.kowalska", 40000003),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    mails = [
        report(ANNA, "Raport 09.11.2026", "40000001 tak montaż"),
        report(JAN, "Raport 08.11.2026", "40000002 tak wymiana"),
    ]

    view = _click_at(centrum, ENTERING_NOW, mails)
    after = centrum.register.read_bytes()
    again = _click_at(centrum, ENTERING_NOW, mails)

    assert view["result"]["result"] == "OK"
    assert _day_rows(centrum.register, 8) == [
        (40000002, "jan.testowy"),
        "pusty",
        (40000003, "anna.kowalska"),
        (40000001, "anna.kowalska"),
        "pusty",
        "żółty",
        "pusty",
    ]
    assert (_started(centrum.register, 40000002)[0], _started(centrum.register, 40000001)[0]) == (
        datetime(2026, 11, 8, 10),
        datetime(2026, 11, 9, 9),
    )
    assert _cells(centrum.register)[40000001] == ("tak", "montaż")
    assert _cells(centrum.register)[40000002] == ("tak", "wymiana")
    assert len(_entering(centrum, view)["moves"]) == 2
    assert (again["result"]["result"], _entering(centrum, again)["changes"], _entering(centrum, again)["moves"]) == (
        "OK",
        [],
        [],
    )
    assert centrum.register.read_bytes() == after


def test_pomylony_temat_wpisuje_do_zlecen_z_ich_dnia_bez_przeniesienia_z_informacja_w_dniu_z_tematu(tmp_path: Path) -> None:
    """Kryterium #1350: Raport Jana za 9.11 z dwoma zleceniami z 8.11 to pomylony temat: Wpisy trafiają do zleceń 8.11,
    INTERMAX nie przenosi żadnego wiersza, a okienko Jana 9.11 mówi o każdym przegranym temacie."""

    centrum = entering_centrum(tmp_path, TWO_DAYS)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = _cells(centrum.register)

    view = _click_at(centrum, ENTERING_NOW, [report(JAN, SUBJECT, "40000002 tak a\n40000004 nie b")])

    assert _cells(centrum.register) == {**before, 40000002: ("tak", "a"), 40000004: ("nie", "b")}
    assert _entering(centrum, view)["moves"] == []
    assert _worker(_view(centrum), "jan.testowy")["notes"] == [
        {"number": "40000002", "text": "pomylony temat: wpisane do zlecenia z 8.11"},
        {"number": "40000004", "text": "pomylony temat: wpisane do zlecenia z 8.11"},
    ]


def test_raport_za_dzien_okresu_z_plikiem_zbiorczym_nie_przenosi_zlecenia_a_problem_stoi_w_dniu_zlecenia(
    tmp_path: Path,
) -> None:
    """Kryterium #1350 (US 14): okres 03_09_11_2026 dostał Plik zbiorczy, a Jan przysyła Raport za 9.11 ze zleceniem,
    które INTERMAX ma 10.11. Centrum go nie przenosi do zamkniętego okresu, a problem z powodem stoi w okienku Jana
    10.11, bo dnia 9.11 widok Raporty już nie pokazuje."""

    intermax = Intermax(ordered=(_order(9, 9, "anna.kowalska", 40000003), _order(10, 9, "jan.testowy", 40000002)), raw=())
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, ENTERING_NOW, [])
    folder = centrum.periods_directory / MONDAY_PERIOD
    folder.mkdir(parents=True)
    (folder / f"Rozliczenie {MONDAY_PERIOD} - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    before = centrum.register.read_bytes()

    view = _click_at(
        centrum, datetime(2026, 11, 10, 18), [report(JAN, SUBJECT, "40000002 tak montaż", at=datetime(2026, 11, 10, 17))]
    )

    assert centrum.register.read_bytes() == before
    assert [(problem["kind"], problem["bar"]) for problem in _entering(centrum, view)["problems"]] == [
        ("refused_move", "closed_target")
    ]
    [problem] = _worker(_view(centrum), "jan.testowy", "2026-11-10")["problems"]
    assert problem["number"] == "40000002"
    assert "okres z dniem 09.11.2026 ma już Plik zbiorczy" in problem["reason"]
def _tata_dates(register: Path, number: int, worker: str, when: datetime) -> None:
    """Tata zmienia w Excelu ``DATA GODZ. POCZ.`` zlecenia ``number`` Wykonawcy ``worker`` na ``when`` i zapisuje
    INTERMAX (bez Excela na dysku); wiersz zostaje na swoim miejscu."""

    book = load_workbook(register)
    sheet = book[ORDER_SHEET]
    [row] = [
        cell.row for cell in sheet[get_column_letter(NUMBER)] if cell.value == number and sheet.cell(cell.row, WORKER).value == worker
    ]
    sheet.cell(row, DATE).value = when
    book.save(register)


def _places(register: Path, number: int) -> list[tuple[object, ...]]:
    """``DATA GODZ. POCZ.``, ``WYKONAWCA``, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` każdego wiersza zlecenia
    ``number``, po kolei."""

    sheet = load_workbook(register)[ORDER_SHEET]
    return [
        tuple(sheet.cell(cell.row, column).value for column in (DATE, WORKER, SUCCESSFUL, COMPLETED))
        for cell in sheet[get_column_letter(NUMBER)]
        if cell.value == number
    ]


def test_numer_w_dwoch_miejscach_nie_przenosi_sie_a_stary_mail_nie_cofa_recznej_zmiany_dnia(tmp_path: Path) -> None:
    """Przegląd #1367 r2 Ważne 1 przez HTTP API: INTERMAX ma 40000001 u Anny 7.11 i u Jana 8.11. Kliknięcie wpisuje Raport
    Jana za 8.11 do jego zlecenia, a tata zmienia jego dzień na 9.11 10:00. Potem Anna przysyła świeższy Raport za 8.11 z
    tym numerem. Numer w dwóch miejscach nie przenosi żadnego zlecenia w żadnym kliknięciu, więc stary mail Jana nie
    cofa zmiany taty, a tata widzi w okienku dnia z tematu każdego niewpisanego maila oba miejsca numeru."""

    intermax = Intermax(
        ordered=(
            _order(7, 9, "anna.kowalska", 40000001),
            _order(7, 10, "jan.testowy", 40000009),
            _order(8, 9, "anna.kowalska", 40000003),
            _order(8, 10, "jan.testowy", 40000001),
            _order(9, 9, "anna.kowalska", 40000004),
            _order(9, 10, "jan.testowy", 40000005),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 7, 18), [])
    jan_mail = report(JAN, "Raport 08.11.2026", "40000001 tak wymiana", at=datetime(2026, 11, 9, 17))
    anna_mail = report(ANNA, "Raport 08.11.2026", "40000001 tak montaż", at=datetime(2026, 11, 9, 18))

    first = _click_at(centrum, ENTERING_NOW, [jan_mail])
    _tata_dates(centrum.register, 40000001, "jan.testowy", datetime(2026, 11, 9, 10))
    second = _click_at(centrum, ENTERING_NOW, [jan_mail])
    third = _click_at(centrum, ENTERING_NOW, [jan_mail, anna_mail])
    fourth = _click_at(centrum, ENTERING_NOW, [jan_mail, anna_mail])

    assert _entering(centrum, first)["changes"] != []
    assert [_entering(centrum, view)["moves"] for view in (first, second, third, fourth)] == [[], [], [], []]
    assert _places(centrum.register, 40000001) == [
        (datetime(2026, 11, 7, 9), "anna.kowalska", None, None),
        (datetime(2026, 11, 9, 10), "jan.testowy", "tak", "wymiana"),
    ]
    places = [{"day": "2026-11-07", "worker": "anna.kowalska"}, {"day": "2026-11-09", "worker": "jan.testowy"}]
    assert [
        (problem["kind"], problem["worker"], problem["day"], problem["places"]) for problem in _entering(centrum, fourth)["problems"]
    ] == [
        ("repeated_number", "anna.kowalska", "2026-11-08", places),
        ("repeated_number", "jan.testowy", "2026-11-08", places),
    ]
    [problem] = _worker(_view(centrum), "anna.kowalska", "2026-11-08")["problems"]
    assert problem["reason"] == (
        "Zlecenie 40000001 jest w INTERMAX więcej niż raz: u anna.kowalska z 07.11.2026, u jan.testowy z 09.11.2026. "
        "Centrum nie wie, którego z nich dotyczy Wpis od anna.kowalska z 08.11.2026, więc nie zmieniło żadnego z nich "
        "przy tym kliknięciu."
    )


def test_wpis_centrum_w_zleceniu_przelozonym_na_jutro_nie_przechodzi_na_reczna_wartosc_drugiego_zlecenia_numeru(
    tmp_path: Path,
) -> None:
    """Przegląd #1367 r3 Ważne 1 przez HTTP API: INTERMAX ma 40000001 u Jana 9.11 (pusty) i u Anny 8.11 z ręcznym „tak”
    i opisem taty. Kliknięcie wpisuje Raport Jana do jego zlecenia, a stary Raport Anny daje różnice, które tata zostawia
    („Zostaw moją”). Tata przekłada zlecenie Jana na jutro. Następne kliknięcie z tymi samymi mailami nie zmienia
    INTERMAX: wpisy Centrum ze zlecenia Jana nie przechodzą na zlecenie Anny, więc jej „tak” zostaje."""

    intermax = Intermax(
        ordered=(
            Order(datetime(2026, 11, 8, 9), "anna.kowalska", 40000001, cells=((NUMBER, 40000001), (SUCCESSFUL, "tak"), (COMPLETED, "montaż taty"))),
            _order(8, 10, "jan.testowy", 40000009),
            _order(9, 9, "anna.kowalska", 40000003),
            _order(9, 10, "jan.testowy", 40000001),
            _order(10, 9, "anna.kowalska", 40000004),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    mails = [
        report(ANNA, "Raport 08.11.2026", "40000001 nie brak klienta", at=datetime(2026, 11, 9, 17)),
        report(JAN, SUBJECT, "40000001 tak wymiana", at=datetime(2026, 11, 9, 17, 5)),
    ]

    first = _click_at(centrum, ENTERING_NOW, mails)
    differences = _worker(_view(centrum), "anna.kowalska", "2026-11-08")["problems"]
    for difference in differences:
        assert centrum.client.post("/api/report-entering/keep", json=difference["keep"]).status_code == 200
    _tata_dates(centrum.register, 40000001, "jan.testowy", datetime(2026, 11, 10, 10))
    by_tata = centrum.register.read_bytes()
    second = _click_at(centrum, ENTERING_NOW, mails)

    assert len(differences) == 2
    assert [change["value"] for change in _entering(centrum, first)["changes"]] == ["tak", "wymiana"]
    assert (_entering(centrum, second)["changes"], _entering(centrum, second)["moves"]) == ([], [])
    assert centrum.register.read_bytes() == by_tata
    assert _places(centrum.register, 40000001) == [
        (datetime(2026, 11, 8, 9), "anna.kowalska", "tak", "montaż taty"),
        (datetime(2026, 11, 10, 10), "jan.testowy", "tak", "wymiana"),
    ]


def test_numer_z_jutra_nie_jest_nieznany_ani_przenoszony_a_tata_widzi_jego_dzien(tmp_path: Path) -> None:
    """Przegląd #1367 r3 Ważne 2 przez HTTP API: dziś 9.11, a tata wkleił już zlecenia na 10.11 (ADR 0019). Raport Jana
    za 9.11 z numerem, który INTERMAX ma u Jana 8.11 i 10.11, nie przenosi zlecenia z 8.11, a Raport Anny za 9.11 z
    numerem, który INTERMAX ma tylko 10.11, nie jest nieznanym numerem i nie zmienia zlecenia z jutra. INTERMAX zostaje
    bajt w bajt, a tata widzi w okienku dnia z tematu oba dni numeru i dzień zlecenia z jutra."""

    intermax = Intermax(
        ordered=(
            _order(8, 9, "jan.testowy", 40000001),
            _order(9, 9, "anna.kowalska", 40000003),
            _order(9, 10, "jan.testowy", 40000009),
            _order(10, 9, "anna.kowalska", 40000005),
            _order(10, 10, "jan.testowy", 40000001),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = centrum.register.read_bytes()

    view = _click_at(
        centrum,
        ENTERING_NOW,
        [report(JAN, SUBJECT, "40000001 tak montaż"), report(ANNA, SUBJECT, "40000005 tak wymiana", at=datetime(2026, 11, 9, 17))],
    )

    assert centrum.register.read_bytes() == before
    entering = _entering(centrum, view)
    assert (entering["changes"], entering["moves"]) == ([], [])
    assert [(problem["kind"], problem["worker"], problem["places"], problem["bar"]) for problem in entering["problems"]] == [
        ("refused_move", "anna.kowalska", [], "after_today"),
        ("repeated_number", "jan.testowy", [{"day": "2026-11-08", "worker": "jan.testowy"}, {"day": "2026-11-10", "worker": "jan.testowy"}], None),
    ]
    [refused] = _worker(_view(centrum), "anna.kowalska")["problems"]
    assert refused["reason"] == (
        "Wpis zlecenia 40000005 od anna.kowalska ma w temacie 09.11.2026, a INTERMAX ma to zlecenie w 10.11.2026. Centrum "
        "go nie przeniosło i nie wpisało, bo dzień 10.11.2026 jeszcze nie nadszedł."
    )


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
    jan = report(JAN, SUBJECT, "40000001 tak inst20m", at=datetime(2026, 11, 9, 17))
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
    assert _cells(centrum.register)[40000001] == ("tak", "inst20m")
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


def _address_written(register: Path, number: int) -> None:
    """Tata wpisuje w Excelu ``ADRES`` dopisanego zlecenia ``number``."""

    book = load_workbook(register)
    [row] = [cell.row for cell in book[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == number]
    book[ORDER_SHEET].cell(row, ADDRESS).value = "Ulica Testowa 7"
    book.save(register)


def test_klikniecie_dopisuje_zlecenie_z_raportu_pod_zlecenia_nadawcy_a_okienko_przypomina_o_adresie_do_jego_wpisania(
    tmp_path: Path,
) -> None:
    """Kryteria #1354 (ADR 0029, US 17–24): Jan przysłał Wpis numeru z 8 cyframi, którego INTERMAX nie ma w żadnym dniu.
    Kliknięcie dopisuje wiersz pod ostatnim zleceniem Jana 9.11, przed pustym wierszem i żółtym wierszem dnia, z
    ``NUMER ZL.``, dniem w ``DATA GODZ. POCZ.`` w formacie dat dnia, ``WYKONAWCA``, ``SKUTECZNE`` i ``CZYNNOŚCI
    ZREALIZOWANE``, w wyglądzie uporządkowanego zlecenia bez Koloru operatora, zapisem bez Kopii INTERMAX; Logi mają
    dopisanie. Okienko dnia Jana mówi „dopisane z raportu, uzupełnij resztę” bez treści ``ADRES``, a drugie kliknięcie
    niczego nie dubluje. Gdy tata wpisze ``ADRES``, informacja znika."""

    intermax = Intermax(
        ordered=(_order(9, 9, "anna.kowalska", 40000002), _order(9, 10, "jan.testowy", 40000001)),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000077 tak instmdik")])
    date_format = _started(centrum.register, 40000001)[1]

    view = _finished(centrum)
    shown = _view(centrum)
    after = centrum.register.read_bytes()
    again = _finished(centrum)
    unchanged = centrum.register.read_bytes() == after
    still = _view(centrum)
    _address_written(centrum.register, 40000077)
    addressed = _finished(centrum)

    assert _day_rows(centrum.register, 7) == [
        (40000002, "anna.kowalska"),
        "pusty",
        (40000001, "jan.testowy"),
        (40000077, "jan.testowy"),
        "pusty",
        "żółty",
    ]
    sheet = load_workbook(centrum.register)[ORDER_SHEET]
    filled = {column: sheet.cell(5, column).value for column in range(1, LAST + 1) if column != ADDRESS}
    assert {column: value for column, value in filled.items() if value is not None} == {
        DATE: datetime(2026, 11, 9),
        NUMBER: 40000077,
        WORKER: "jan.testowy",
        SUCCESSFUL: "tak",
        COMPLETED: "instmdik",
    }
    assert sheet.cell(5, DATE).number_format == date_format
    looks = [(cell.font.name, cell.font.sz, bool(cell.font.b), cell.border.left.style, cell.fill.fill_type) for cell in sheet[5][FIRST - 1 : LAST]]
    assert looks == [("Calibri", 9 if column == WORKER else 8, column == WORKER, "thin", None) for column in range(FIRST, LAST + 1)]
    assert not centrum.tool.intermax_copies.exists(), "Wpisanie raportów nie robi Kopii INTERMAX"
    entering = _entering(centrum, view)
    assert entering["added"] == [
        {
            "sheet": ORDER_SHEET,
            "day": "2026-11-09",
            "worker": "jan.testowy",
            "number": 40000077,
            "successful": "tak",
            "completed": "instmdik",
        }
    ]
    assert (entering["problems"], entering["moves"]) == ([], [])
    assert view["result"]["summary"]["figures"][0] == {"label": "Wpisane", "value": 1, "unit": "count"}
    jan = _worker(shown, "jan.testowy")
    assert jan["notes"] == [{"number": "40000077", "text": "dopisane z raportu, uzupełnij resztę"}]
    assert [order["number"] for order in jan["orders_detail"]] == ["40000001", "40000077"]
    assert jan["problems"] == []
    assert "Ulica" not in json.dumps(shown, ensure_ascii=False)
    assert (_entering(centrum, again)["added"], _entering(centrum, again)["changes"]) == ([], [])
    assert unchanged, "drugie kliknięcie nie zmienia INTERMAX"
    assert _worker(still, "jan.testowy")["notes"] == jan["notes"]
    assert (_entering(centrum, addressed)["added"], _entering(centrum, addressed)["changes"]) == ([], [])
    assert _worker(_view(centrum), "jan.testowy")["notes"] == []


def test_dopisanie_zapisuje_sie_w_pamieci_w_wersji_4_a_plik_wersji_3_z_dopisaniem_czyta_sie_bez_zatrzymania(
    tmp_path: Path,
) -> None:
    """#1354 r4 po #1367 r5: kliknięcie, które dopisuje 40000077, zapisuje pamięć w wersji 4 z jego zleceniem jako
    dopisanym (``moves[].added``) i jego komórkami jako własnymi wpisami. Plik w wersji 3 z ``added`` zapisała tylko ta
    gałąź przed scaleniem #1367, nigdy Wydanie: kliknięcie czyta go bez Zatrzymania, nie dopisuje numeru drugi raz,
    okienko dalej przypomina o adresie, a pamięć wraca do wersji 4 z tym samym dopisaniem."""

    intermax = Intermax(ordered=(_order(9, 9, "anna.kowalska", 40000002), _order(9, 10, "jan.testowy", 40000001)), raw=())
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000077 tak instmdik")])
    _finished(centrum)
    saved = json.loads(_state(centrum).read_text(encoding="utf-8"))
    older = {key: value for key, value in saved.items() if key != "requested"}
    _state(centrum).write_text(json.dumps({**older, "schema_version": 3}, ensure_ascii=False), encoding="utf-8")
    after = centrum.register.read_bytes()

    entering = _entering(centrum, _finished(centrum))

    assert saved["schema_version"] == 4
    assert [(move["number"], move["added"]) for move in saved["moves"]] == [("40000077", True)]
    assert {(own["number"], own["column"], own["value"]) for own in saved["own"]} == {
        ("40000077", "SKUTECZNE", "tak"),
        ("40000077", "CZYNNOŚCI ZREALIZOWANE", "instmdik"),
    }
    assert centrum.register.read_bytes() == after, "plik wersji 3 z dopisaniem nie dopisuje numeru drugi raz"
    assert (entering["added"], entering["problems"]) == ([], [])
    assert [move["added"] for move in entering["moves_before"]] == [True]
    assert _worker(_view(centrum), "jan.testowy")["notes"] == [{"number": "40000077", "text": "dopisane z raportu, uzupełnij resztę"}]
    assert json.loads(_state(centrum).read_text(encoding="utf-8")) == saved


def _day_with(row: Order) -> Intermax:
    """Uporządkowany 9.11: zlecenie Jana, wiersz ``row`` i zlecenie Anny, bez Surowych zleceń."""

    return Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), row, _order(9, 11, "anna.kowalska", 40000002)), raw=())


_NINTH_AT_TEN = datetime(2026, 11, 9, 10)
_ORDERLESS_ROWS = {
    "surowe-zlecenia-na-dole": (INTERMAX, (40000003, 40000004)),
    "bez-wykonawcy": (_day_with(Order(_NINTH_AT_TEN, "", 40000066, cells=((NUMBER, 40000066),))), (40000066,)),
    "bez-wykonawcy-sprzed-dnia-wdrozenia": (
        Intermax(
            ordered=(
                Order(datetime(2026, 11, 8, 10), "", 40000065, cells=((NUMBER, 40000065),)),
                _order(9, 9, "jan.testowy", 40000001),
                _order(9, 11, "anna.kowalska", 40000002),
            ),
            raw=(),
        ),
        (40000065,),
    ),
    "data-tekstem": (
        _day_with(Order(_NINTH_AT_TEN, "jan.testowy", 40000067, cells=((NUMBER, 40000067), (DATE, "09.11.2026 10:00")))),
        (40000067,),
    ),
    "wyglad-z-aplikacji": (
        _day_with(Order(_NINTH_AT_TEN, "jan.testowy", 40000068, cells=((NUMBER, 40000068),), app_look=True)),
        (40000068,),
    ),
    "przesuniety-wiersz-z-aplikacji": (
        _day_with(Order(_NINTH_AT_TEN, "jan.testowy", 40000069, cells=((NUMBER, 40000069),), shifted=True, app_look=True)),
        (40000069,),
    ),
    "dwa-wklejenia-dolny-przesuniety": (
        Intermax(
            ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)),
            raw=(
                _order(10, 9, "jan.testowy", 40000080),
                _order(10, 10, "jan.testowy", 40000081),
                Order(datetime(2026, 11, 10, 11), "jan.testowy", 40000078, cells=((NUMBER, 40000078),), shifted=True),
                _order(10, 12, "jan.testowy", 40000079),
            ),
            blank_in_paste=frozenset({2}),
        ),
        (40000078,),
    ),
}


@pytest.mark.parametrize(("intermax", "numbers"), list(_ORDERLESS_ROWS.values()), ids=list(_ORDERLESS_ROWS))
def test_klikniecie_nie_dopisuje_numeru_ktory_intermax_ma_w_przeczytanym_wierszu_bez_zlecenia(
    tmp_path: Path, intermax: Intermax, numbers: tuple[int, ...]
) -> None:
    """Przegląd #1374 r2 Ważne 1 (ADR 0029: Centrum nigdy nie dubluje zlecenia, które INTERMAX już ma): dziś 9.11, a
    Jan przysłał Raport za 9.11 z numerami, które INTERMAX ma w wierszu, z którego proces nie robi zlecenia. Kształty z
    kopii INTERMAX taty i z Uporządkowania: Surowe zlecenia na dole arkusza (pierwsze przesunięte o dwie kolumny w lewo,
    jak z aplikacji), uporządkowany wiersz bez ``WYKONAWCA`` (także z 8.11 sprzed dnia wdrożenia: to wiersz bez zlecenia,
    a nie zlecenie sprzed okna), wiersz z ``DATA GODZ. POCZ.`` tekstem, wiersz z wyglądem z
    aplikacji między uporządkowanymi, taki wiersz przesunięty jak pierwszy wiersz wklejenia i przesunięty pierwszy wiersz dolnego z dwóch wklejeń bez
    Uporządkowania między nimi, który reguła danych zna w obu położeniach (przegląd #1374 r3 Drobne 1: numer tylko z
    pierwszego położenia dawał dubel). Kliknięcie nie zmienia INTERMAX, więc żaden numer nie stoi w
    nim dwa razy, a okienko Jana z 9.11 ma problem z każdym numerem, który mówi, że zlecenie już jest. Logi mają te
    numery, żeby odtworzenie postawiło je w INTERMAX."""

    text = "\n".join(f"{number} tak montaż" for number in numbers)
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, text)])
    before = centrum.register.read_bytes()

    view = _finished(centrum)

    assert centrum.register.read_bytes() == before, "kliknięcie nie dopisuje numeru, który INTERMAX już ma"
    entering = _entering(centrum, view)
    assert (entering["added"], [(problem["kind"], problem["bar"]) for problem in entering["problems"]]) == (
        [],
        [("unknown_number", "in_intermax")] * len(numbers),
    )
    assert entering["orderless"] == [{"sheet": ORDER_SHEET, "number": number, "day": None} for number in numbers]
    problems = _worker(_view(centrum), "jan.testowy")["problems"]
    assert [problem["number"] for problem in problems] == [str(number) for number in numbers]
    assert all(f"Zlecenie {problem['number']} z Wpisu od jan.testowy z 09.11.2026 jest już w INTERMAX" in problem["reason"] for problem in problems)


def test_wiersz_dopisany_recznie_pod_dniem_bez_calibri_8_nie_ukrywa_zlecen_nad_nim(tmp_path: Path) -> None:
    """Logi taty z 16.11 i 18.11.2026: po Uporządkowaniu dnia na pojutrze tata dopisał ręcznie zlecenie na jutro w
    pustym wierszu pod jutrzejszym dniem, jeszcze bez Calibri 8. Wpisanie raportów kończyło na nim przegląd od dołu,
    więc czytało tylko dni pod nim, nie wpisało nic, a każdy numer z wcześniejszych dni miało za problem; tata widział
    0/0 i klikał drugi raz, aż sformatował wiersz. Tu INTERMAX ma uporządkowane 8.11 ze zleceniem Jana, pod nim
    dopisany ręcznie wiersz Jana z 8.11 z wyglądem z aplikacji i uporządkowane 9.11. Raport Jana za 8.11 wpisuje się do
    jego zlecenia nad tym wierszem przy pierwszym kliknięciu."""

    intermax = Intermax(
        ordered=(
            _order(8, 9, "jan.testowy", 40000010),
            Order(datetime(2026, 11, 8, 10), "jan.testowy", 40000068, cells=((NUMBER, 40000068),), app_look=True),
            _order(9, 9, "anna.kowalska", 40000002),
            _order(9, 11, "jan.testowy", 40000001),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])

    entering = _entering(centrum, _click_at(centrum, ENTERING_NOW, [report(JAN, "Raport 08.11.2026", "40000010 tak montaż")]))

    assert _cells(centrum.register)[40000010] == ("tak", "montaż")
    assert (entering["written"], entering["problems"]) == (2, [])


def test_wiersz_bez_wykonawcy_nad_dziesiatkami_zlecen_dnia_nie_jest_dopisany_drugi_raz(tmp_path: Path) -> None:
    """Przegląd #1374 r3 Drobne 2: dzień taty ma dziesiątki zleceń. Tata kliknął pierwszy raz 8.11, a INTERMAX ma wiersz
    8.11 bez ``WYKONAWCA`` z 40000095 nad dwunastoma zleceniami Anny z 8.11, pod nimi dzień 9.11. Raport Jana za 9.11 z
    tym numerem: przegląd numerów sięga przez cały dzień 8.11 (granica dni okna, nie dzień najniższego wiersza), więc
    kliknięcie 9.11 nie dopisuje 40000095 drugi raz, a Jan ma problem, że zlecenie już jest."""

    intermax = Intermax(
        ordered=(
            Order(datetime(2026, 11, 8, 7), "", 40000095, cells=((NUMBER, 40000095),)),
            *(_order(8, 8, "anna.kowalska", 40000100 + index) for index in range(12)),
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 11, "anna.kowalska", 40000002),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = centrum.register.read_bytes()

    entering = _entering(centrum, _click_at(centrum, ENTERING_NOW, [report(JAN, SUBJECT, "40000095 tak montaż")]))

    assert centrum.register.read_bytes() == before, "kliknięcie nie dopisuje numeru, który INTERMAX już ma"
    assert entering["added"] == []
    assert [(problem["kind"], problem["bar"]) for problem in entering["problems"]] == [("unknown_number", "in_intermax")]


_REPASTED_NEXT_TO_ORDER = {
    "surowe-zlecenie-na-dole": Intermax(
        ordered=(
            _order(8, 9, "anna.kowalska", 40000001),
            _order(8, 10, "jan.testowy", 40000002),
            _order(8, 12, "jan.testowy", 40000004),
            _order(9, 9, "anna.kowalska", 40000003),
        ),
        raw=(_order(9, 14, "jan.testowy", 40000002), _order(9, 15, "anna.kowalska", 40000005)),
    ),
    "wiersz-bez-wykonawcy-w-dniu-z-tematu": Intermax(
        ordered=(
            _order(8, 9, "anna.kowalska", 40000001),
            _order(8, 10, "jan.testowy", 40000002),
            _order(8, 12, "jan.testowy", 40000004),
            _order(9, 9, "anna.kowalska", 40000003),
            Order(datetime(2026, 11, 9, 10), "", 40000002, cells=((NUMBER, 40000002),)),
        ),
        raw=(),
    ),
}


@pytest.mark.parametrize("intermax", list(_REPASTED_NEXT_TO_ORDER.values()), ids=list(_REPASTED_NEXT_TO_ORDER))
def test_zlecenie_numeru_z_drugim_wierszem_bez_zlecenia_nie_przechodzi_na_dzien_z_tematu(
    tmp_path: Path, intermax: Intermax
) -> None:
    """Reguła #1367 „numer w kilku miejscach się nie przenosi” liczy też przeczytany wiersz bez zlecenia (przegląd #1374
    r3): INTERMAX ma 40000002 jako zlecenie Jana z 8.11 (dzień otwarty od pierwszego kliknięcia 8.11) i drugi raz w 9.11
    jako Surowe zlecenie na dole albo wiersz bez ``WYKONAWCA``. Raport Jana za 9.11 z tym numerem nie przenosi zlecenia z
    8.11, bo 9.11 miałby wtedy ten numer dwa razy: INTERMAX zostaje bez zmian, a Jan ma problem z miejscem zlecenia i
    zdaniem o wierszu bez zlecenia."""

    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = centrum.register.read_bytes()

    entering = _entering(centrum, _click_at(centrum, ENTERING_NOW, [report(JAN, SUBJECT, "40000002 tak montaż")]))

    assert centrum.register.read_bytes() == before, "kliknięcie nie przenosi zlecenia obok wiersza z tym samym numerem"
    assert (entering["moves"], entering["added"]) == ([], [])
    assert [(problem["kind"], problem["number"]) for problem in entering["problems"]] == [("repeated_number", "40000002")]
    [problem] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert "u jan.testowy z 08.11.2026 i w wierszu, z którego Centrum nie robi zlecenia" in problem["reason"]


_EIGHTH_BEFORE_ROLLOUT = {
    "zlecenie-pod-dniem": (INTERMAX, 40000010),
    "zlecenie-nad-dziesiatkami-zlecen-dnia": (
        Intermax(
            ordered=(
                _order(8, 7, "jan.testowy", 40000095),
                *(_order(8, 8, "anna.kowalska", 40000100 + index) for index in range(12)),
                _order(9, 9, "jan.testowy", 40000001),
                _order(9, 11, "anna.kowalska", 40000002),
            ),
            raw=(),
        ),
        40000095,
    ),
}


@pytest.mark.parametrize(("intermax", "number"), list(_EIGHTH_BEFORE_ROLLOUT.values()), ids=list(_EIGHTH_BEFORE_ROLLOUT))
def test_zlecenie_sprzed_dnia_wdrozenia_nie_jest_dopisane_a_powod_mowi_o_dniu_sprzed_okna(
    tmp_path: Path, intermax: Intermax, number: int
) -> None:
    """Przegląd #1374 r3 (Drobne 3 i granica dnia wdrożenia): tata klika pierwszy raz 9.11, więc zlecenia czyta od 9.11,
    a INTERMAX ma pełne zlecenie Jana z 8.11 (z ``WYKONAWCA`` i datą z godziną), także nad dwunastoma zleceniami Anny z
    8.11. Raport Jana za 9.11 z tym numerem nie dopisuje go drugi raz, bo numery proces czyta też z tygodnia przed
    pierwszym dniem otwartym, sprzed dnia wdrożenia. Powód mówi, że zlecenie jest w dniu sprzed dni, które Centrum
    czyta, a nie że wierszowi brakuje ``WYKONAWCA`` albo daty, i nie radzi kliknąć jeszcze raz, bo to nic nie zmieni.
    Logi mają dzień zlecenia, żeby odtworzenie dało ten sam powód."""

    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, f"{number} tak montaż")])
    before = centrum.register.read_bytes()

    entering = _entering(centrum, _finished(centrum))

    assert centrum.register.read_bytes() == before, "kliknięcie nie dopisuje zlecenia, które INTERMAX ma przed dniem wdrożenia"
    assert entering["added"] == []
    assert [(problem["kind"], problem["bar"]) for problem in entering["problems"]] == [("unknown_number", "before_window")]
    assert entering["orderless"] == [{"sheet": ORDER_SHEET, "number": number, "day": "2026-11-08"}]
    [problem] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert f"Zlecenie {number} z Wpisu od jan.testowy z 09.11.2026 jest już w INTERMAX, ale z dniem sprzed dni" in problem["reason"]
    assert "WYKONAWCA" not in problem["reason"]
    assert "kliknij jeszcze raz" not in problem["reason"]


def test_zlecenie_z_dnia_po_dzis_nie_jest_dopisane_drugi_raz_a_nastepnego_dnia_przechodzi_na_dzien_z_tematu(
    tmp_path: Path,
) -> None:
    """Przegląd #1374 r1 przez HTTP API: dziś 9.11, a INTERMAX ma już uporządkowany 10.11 (tata wkleja i porządkuje
    zlecenia jutra dzień wcześniej, ADR 0019). Jan zrobił zlecenie 40000055 z 10.11 już dziś i wpisał je do Raportu za
    9.11. Kliknięcie nie zmienia INTERMAX, więc numer nie stoi w nim dwa razy, a okienko Jana z 9.11 ma problem z tym
    numerem: dzień zlecenia jeszcze nie nadszedł (#1367 r4). Kliknięcie 10.11 przenosi zlecenie na 9.11 z Wpisem
    (#1350)."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "anna.kowalska", 40000002),
            _order(9, 10, "jan.testowy", 40000001),
            _order(10, 9, "jan.testowy", 40000055),
        ),
        raw=(),
    )
    mail = report(JAN, SUBJECT, "40000055 tak montaż ONT")
    centrum = entering_centrum(tmp_path, intermax, [mail])
    before = centrum.register.read_bytes()

    view = _finished(centrum)
    unchanged = centrum.register.read_bytes() == before
    problems = _worker(_view(centrum), "jan.testowy")["problems"]
    tomorrow = _click_at(centrum, datetime(2026, 11, 10, 18, 30), [mail])

    assert unchanged, "kliknięcie nie dopisuje zlecenia, które INTERMAX ma w dniu po dziś"
    assert _entering(centrum, view)["added"] == []
    assert [problem["number"] for problem in problems] == ["40000055"]
    assert "10.11.2026 jeszcze nie nadszedł" in problems[0]["reason"]
    assert _places(centrum.register, 40000055) == [(datetime(2026, 11, 9, 9), "jan.testowy", "tak", "montaż ONT")]
    assert [move["day"] for move in _entering(centrum, tomorrow)["moves"]] == ["2026-11-09"]


def test_dopisane_zlecenie_przelozone_przez_tate_na_jutro_zostaje_na_jutro_przy_poprawionym_raporcie(tmp_path: Path) -> None:
    """Przegląd #1374 r4 Ważne 1 przez HTTP API: dziś 9.11. Raport Jana za 9.11 dopisuje 40000077, a tata przekłada
    dopisany wiersz na 10.11 10:00. Wieczorem Jan przysyła poprawiony Raport za 9.11 z tym numerem. Zlecenia z dnia po
    dziś Wpis nie zmienia (ADR 0029), także dopisanego, więc kliknięcie nie zmienia INTERMAX, a tata widzi w okienku
    Jana odmowę z dniem 10.11."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    added = report(JAN, SUBJECT, "40000077 tak montaż ONT", at=datetime(2026, 11, 9, 17))
    first = _click_at(centrum, ENTERING_NOW, [added])
    _tata_dates(centrum.register, 40000077, "jan.testowy", datetime(2026, 11, 10, 10))
    before = centrum.register.read_bytes()
    correction = report(JAN, SUBJECT, "40000077 nie brak klienta", at=datetime(2026, 11, 9, 19))

    view = _click_at(centrum, datetime(2026, 11, 9, 19, 30), [added, correction])

    assert [found["number"] for found in _entering(centrum, first)["added"]] == [40000077]
    assert centrum.register.read_bytes() == before, "kliknięcie nie przenosi dopisanego zlecenia z jutra"
    entering = _entering(centrum, view)
    assert (entering["moves"], entering["changes"], entering["added"]) == ([], [], [])
    assert [(problem["kind"], problem["number"], problem["bar"]) for problem in entering["problems"]] == [
        ("refused_move", "40000077", "after_today")
    ]
    assert _places(centrum.register, 40000077) == [(datetime(2026, 11, 10, 10), "jan.testowy", "tak", "montaż ONT")]
    [refused] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert "dzień 10.11.2026 jeszcze nie nadszedł" in refused["reason"]


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
    assert saved["schema_version"] == 4
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
            "added": False,
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
            "added": False,
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
    assert json.loads(_state(centrum).read_text(encoding="utf-8"))["schema_version"] == 4


@pytest.mark.parametrize(
    "saved",
    [
        pytest.param(ROOT / "tests" / "fixtures" / "wpisanie-raportow-stan-v1.json", id="wydanie-v0.8.0"),
        pytest.param(ROOT / "tests" / "fixtures" / "wpisanie-raportow-stan-v3.json", id="main-przed-1367"),
    ],
)
@pytest.mark.parametrize(
    ("day", "worker"),
    [
        pytest.param(8, "anna.kowalska", id="inny-dzien-i-wykonawca"),
        pytest.param(9, "anna.kowalska", id="ten-sam-dzien-inny-wykonawca"),
        pytest.param(8, "jan.testowy", id="ten-sam-wykonawca-inny-dzien"),
    ],
)
def test_plik_pamieci_ze_starszej_wersji_nie_niesie_wpisow_na_inne_zlecenie_numeru_z_reczna_wartoscia_taty(
    tmp_path: Path, saved: Path, day: int, worker: str
) -> None:
    """Przegląd #1367 r4 Ważne 1 i r5 Drobne 1, cel Maksa: Centrum nigdy nie nadpisuje ręcznej wartości taty, także po
    aktualizacji.

    Plik pamięci zapisało Centrum z Wydania v0.8.0 (wersja 1) albo z ``main`` przed #1367 (wersja 3), każde swoim kodem
    przy tym samym kliknięciu: 40000001 stał z ręcznym „tak” i opisem taty w drugim zleceniu i u Jana w 9.11, a Raport
    Jana za 9.11 wpisał się do jego zlecenia, więc plik ma wpisy Jana przy numerze w dwóch zleceniach. Drugie zlecenie
    różni się od Jana 9.11 dniem i Wykonawcą (Anna 8.11), samym Wykonawcą (Anna 9.11) albo samym dniem (Jan 8.11), a
    kod v0.8.0 zapisuje dla każdego z nich ten sam plik (przegląd #1367 r5 porównał oba nowe miejsca z fixture'em).
    Po aktualizacji, przed pierwszym kliknięciem, tata usuwa wiersz Jana 9.11 (duplikat). Raport właściciela drugiego zlecenia za jego dzień
    „nie” nie zmienia jego komórek: wpis ze starszego pliku należy do miejsca z chwili zapisu (numer, dzień i Wykonawca
    naraz) i nie przechodzi na wiersz, który zgadza się z nim tylko dniem albo tylko Wykonawcą, więc obie komórki są
    ręczne i zostają z różnicą. Logi mają pamięć, z którą liczyło kliknięcie, a plik pamięci ma potem wersję 4 bez tych
    wpisów."""

    intermax = Intermax(
        ordered=(
            Order(
                datetime(2026, 11, day, 8),
                worker,
                40000001,
                cells=((NUMBER, 40000001), (SUCCESSFUL, "tak"), (COMPLETED, "montaż taty")),
            ),
            _order(8, 10, "jan.testowy", 40000009),
            _order(9, 9, "anna.kowalska", 40000003),
        ),
        raw=(),
    )
    centrum = entering_centrum(tmp_path, intermax)
    shutil.copyfile(saved, _state(centrum))
    mail = report(SENDERS[worker], f"Raport {day:02d}.11.2026", "40000001 nie brak klienta", at=datetime(2026, 11, 9, 17, 30))

    view = _click_at(centrum, datetime(2026, 11, 9, 18, 30), [mail])

    entering = _entering(centrum, view)
    cell = {"number": 40000001, "day": f"2026-11-{day:02d}", "worker": worker}
    assert _cells(centrum.register)[40000001] == ("tak", "montaż taty"), "Centrum nadpisało ręczną wartość taty"
    assert entering["changes"] == []
    assert entering["problems"] == [
        {
            "kind": "manual_difference",
            "cell": {**cell, "column": "CZYNNOŚCI ZREALIZOWANE", "value": "brak klienta"},
            "manual": "montaż taty",
        },
        {"kind": "manual_difference", "cell": {**cell, "column": "SKUTECZNE", "value": "nie"}, "manual": "tak"},
    ]
    assert (entering["rollout_before"], entering["memory_before"]) == ("2026-11-08", [])
    assert [problem["number"] for problem in _worker(_view(centrum), worker, f"2026-11-{day:02d}")["problems"]] == [
        "40000001"
    ] * 2
    after = json.loads(_state(centrum).read_text(encoding="utf-8"))
    assert (after["schema_version"], after["own"]) == (4, [])

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


def _faulty_subject(problem: dict[str, Any]) -> tuple[str, str, str | None, datetime]:
    """Temat, rodzaj błędu, dzień, za który Centrum liczy raport, i chwila przyjścia raportu z błędem tematu z problemu
    widoku."""

    found = problem["faulty_subject"]
    return found["subject"], found["fault"], found["day"], datetime.fromisoformat(found["arrived"])


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
            report(JAN, SUBJECT, "40000001 tak inst20m rt2"),
            report(ANNA, SUBJECT, "400000099 tak spawpg"),
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
    unknown = UnknownNumber(Login("anna.kowalska"), date(2026, 11, 9), OrderNumber("400000099"), AddBar.FORM)
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
                    "problems": [
                        {
                            "reason": reason(unknown),
                            "number": "400000099",
                            "keep": None,
                            "request": None,
                            "faulty_subject": None,
                        }
                    ],
                    "notes": [],
                    "orders_detail": [
                        {
                            "number": "40000002",
                            "successful": None,
                            "activities": None,
                            "state": "without_report",
                            "codes": [],
                            "no_code": False,
                            "request": None,
                        }
                    ],
                    "mistaken_subjects": [],
                    "overtaken_subjects": [],
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
                        {
                            "number": "40000001",
                            "successful": "tak",
                            "activities": "inst20m rt2",
                            "state": "entered",
                            "codes": ["inst20m", "rt2"],
                            "no_code": False,
                            "request": None,
                        },
                        {
                            "number": "40000005",
                            "successful": None,
                            "activities": None,
                            "state": "without_report",
                            "codes": [],
                            "no_code": False,
                            "request": None,
                        },
                    ],
                    "mistaken_subjects": [],
                    "overtaken_subjects": [],
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
        [report(JAN, SUBJECT, "40000006 tak spawpg 40000001 tak inst20m"), report(ANNA, SUBJECT, "40000002 brak klienta")],
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
    """US 55 i ADR 0041 (historia 20): Anna nie ma zleceń, a jej mail z 9.11 ma temat bez daty, więc Centrum nie liczy
    go za żaden dzień i jest problemem bez dnia. Widok Raporty pokazuje ją przy dniu przyjścia maila z zerami i tym
    problemem z tematem bez dnia, zamiast zgubić problem razem z nią."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001),), raw=())
    mail = report(ANNA, "Raport bez daty", "40000002 tak montaż")
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, "40000001 tak wymiana"), mail])
    _finished(centrum)

    view = _view(centrum)

    unreadable = UnreadableSubject(
        MailId.of("<syntetyczny@przyklad.invalid>"),
        Login("anna.kowalska"),
        mail.arrived,
        SubjectFault.NO_DATE,
        ReportSubject("Raport bez daty"),
        None,
    )
    anna = _worker(view, "anna.kowalska")
    assert [_faulty_subject(problem) for problem in anna["problems"]] == [("Raport bez daty", "bez daty", None, mail.arrived)]
    assert anna == {
        "day": "2026-11-09",
        "orders": 0,
        "entered": 0,
        "mails": 0,
        "without_report": [],
        "problems": [
            {
                "reason": reason(unreadable),
                "number": None,
                "keep": None,
                "request": None,
                "faulty_subject": anna["problems"][0]["faulty_subject"],
            }
        ],
        "notes": [],
        "orders_detail": [],
        "mistaken_subjects": [],
        "overtaken_subjects": [],
        "reminders": [],
    }


def test_raport_z_bledem_tematu_stoi_przy_wskazanym_dniu_z_tematem_po_straznika_rodzajem_bledu_i_tym_dniem(tmp_path: Path) -> None:
    """ADR 0041 (historie 3, 5, 19–20, 40, 42; zmienia zdanie ADR 0028 o przeglądarce): raport z błędem tematu jest
    przysłany. Jan pisze w temacie nazwisko, adres klienta i telefon, Anna sam ``Raport``. Odpowiedź HTTP widoku Raporty
    ma przy dniu każdego z nich Raport wykonawcy i problem z tematem po strażniku reguły danych (wartość ``ADRES`` i
    telefon zamaskowane, nazwisko zostaje, bo tata widzi, co pracownik napisał), rodzajem błędu, dniem, za który Centrum
    go liczy (dla Jana dzień z tematu, dla Anny jej ostatni dzień ze zleceniami, 8.11, choć mail przyszedł 9.11), i
    chwilą przyjścia maila. Zlecenia z Wpisami takiego raportu nie są bez raportu: mają stan ``faulty_subject``, a linia
    Wykonawcy nie liczy ich do bez raportu, tylko drugie zlecenie Jana, którego raport nie ma. Wpisów takiego raportu
    Centrum nie wpisuje, a temat nie trafia do Logów."""

    client = "Testowa 12 m. 3 Wrocław"
    jan_order = Order(datetime(2026, 11, 9, 9), "jan.testowy", 40000001, cells=((NUMBER, 40000001), (ADDRESS, client)))
    ordered = (jan_order, _order(9, 12, "jan.testowy", 40000003), _order(8, 11, "anna.kowalska", 40000002))
    intermax = Intermax(ordered=ordered, raw=())
    mails = [
        report(JAN, f"Raport 09.11.2026 Kowalski {client} tel. 600 123 456", "40000001 tak inst20m"),
        report(ANNA, "Raport", "40000002 tak spawpg"),
    ]
    centrum = entering_centrum(tmp_path, intermax)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    before = _cells(centrum.register)
    _click_at(centrum, ENTERING_NOW, mails)

    view = _view(centrum)

    jan, anna = _worker(view, "jan.testowy"), _worker(view, "anna.kowalska", "2026-11-08")
    assert [(day["mails"], [_faulty_subject(problem) for problem in day["problems"]]) for day in (jan, anna)] == [
        (1, [("Raport 09.11.2026 Kowalski [adres] tel. [telefon]", "inne słowa", "2026-11-09", mails[0].arrived)]),
        (1, [("Raport", "bez daty", "2026-11-08", mails[1].arrived)]),
    ]
    shown = json.dumps(view, ensure_ascii=False)
    assert "Testowa" not in shown and "600 123" not in shown
    assert [([(order["number"], order["state"]) for order in day["orders_detail"]], day["without_report"]) for day in (jan, anna)] == [
        ([("40000001", "faulty_subject"), ("40000003", "without_report")], ["40000003"]),
        ([("40000002", "faulty_subject")], []),
    ]
    assert _cells(centrum.register) == before
    logs = json.dumps(centrum.run_logs(), ensure_ascii=False)
    assert "Kowalski" not in logs and "Testowa" not in logs


def test_raport_z_pomylonym_tematem_stoi_przy_dniu_swoich_zlecen_jako_informacja_z_dniem_z_tematu(tmp_path: Path) -> None:
    """ADR 0041 (historia 41) i ADR 0029: ``Raport 10.11.2026`` z dwoma numerami zleceń Jana z 9.11 to pomylony temat.
    Wpisy idą do zleceń z 9.11, a przy tym dniu widok Raporty ma informację z dniem z tematu, bez problemu."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000005)), raw=())
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, "Raport 10.11.2026", "40000001 tak inst20m\n40000005 tak spawpg")])
    _finished(centrum)

    jan = _worker(_view(centrum), "jan.testowy")

    assert (jan["mails"], jan["entered"], jan["problems"], jan["mistaken_subjects"]) == (1, 2, [], ["2026-11-10"])


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
        {"reason": reason(warning), "number": "40000001", "keep": None, "request": None, "faulty_subject": None}
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

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m")])
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

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m")])
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
        "reported": "inst20m",
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
        {"number": 40000001, "day": "2026-11-09", "worker": "jan.testowy", "column": "CZYNNOŚCI ZREALIZOWANE", "value": "inst20m"}
    ]
    corrected = _click_at(
        centrum,
        datetime(2026, 11, 9, 19, 30),
        [
            report(JAN, SUBJECT, "40000001 tak inst20m"),
            report(JAN, SUBJECT, "40000001 tak inst25m", at=datetime(2026, 11, 9, 19)),
        ],
    )
    [shown] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert shown["keep"] == {**cell, "reported": "inst25m"}
    assert corrected["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 1, "unit": "count"}
    assert _cells(centrum.register)[40000001] == ("tak", "wymiana ręczna")


def test_logi_klikniecia_maja_decyzje_zostaw_moja_tylko_przy_zleceniach_z_wpisem_w_tym_kliknieciu(tmp_path: Path) -> None:
    """Logi niosą decyzje „Zostaw moją” tak jak pamięć własnych wpisów: tylko zleceń z Wpisem w tym kliknięciu. Gdy
    Raportu Jana nie ma już w skrzynce, Logi kliknięcia z samym Raportem Anny nie mają decyzji przy zleceniu Jana, bo
    odtworzenie Logów z decyzją bez Wpisu kończy się granicą."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m")])
    _tata_writes(centrum.register, 40000001, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    assert centrum.client.post("/api/report-entering/keep", json=difference["keep"]).status_code == 200

    later = _click_at(centrum, datetime(2026, 11, 9, 19, 30), [report(ANNA, SUBJECT, "40000002 tak spawpg")])

    assert _entering(centrum, later)["kept"] == []
    assert _cells(centrum.register)[40000002] == ("tak", "spawpg")


def test_zostaw_moja_przy_roznicy_spoza_ostatniego_klikniecia_jest_odrzucone_bez_zapisu_decyzji(tmp_path: Path) -> None:
    """„Zostaw moją” tylko przy różnicy z wyniku ostatniego kliknięcia: inna treść Wpisu (widok sprzed nowszego
    kliknięcia) dostaje odmowę, a plik decyzji nie powstaje."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m")])
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

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak inst20m")])
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


# --- Wpis na życzenie (ADR 0041, spec #2032 US 45–53) ----------------------------------------------------------------


def _requests(centrum: EnteringCentrum, login: str, day: str = "2026-11-09") -> dict[str, Any]:
    """Wpis na życzenie przy każdym problemie dnia ``day`` Wykonawcy ``login`` w widoku Raporty, po numerze."""

    return {problem["number"]: problem["request"] for problem in _worker(_view(centrum), login, day)["problems"]}


def _enter_on_request(centrum: EnteringCentrum, offer: dict[str, Any], at: datetime) -> dict[str, Any]:
    """Tata klika Wpis na życzenie ``offer`` w chwili ``at``; widok Uruchomienia, które to kliknięcie startuje."""

    centrum.moment.append(at)
    started = centrum.client.post("/api/report-entering/request", json=offer)
    assert started.status_code == 200, started.json()
    view = finished_view(centrum.client)
    assert view["result"]["ending"] == "finished", view["result"]
    return view


def _without_moment(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in decision.items() if key != "at"} for decision in decisions]


def test_wpis_na_zyczenie_przy_t_wpisuje_tak_z_czynnosciami_a_blad_nie_wraca_przy_nastepnym_kliknieciu(
    tmp_path: Path,
) -> None:
    """US 45–48 i 52: przy Wpisie z ``t`` i z ``nieskuteczne`` zamiast ``tak``/``nie`` widok Raporty ma Wpis na życzenie
    z tym, co się wpisze (dzień, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``). Kliknięcie przy Wpisie Jana wpisuje jednym
    Uruchomieniem ``tak`` i czynności jak każdy Wpis, a Wpis Anny zostaje problemem. Logi mają decyzję taty, a
    następne kliknięcie „Wpisz raporty z maili” nie przywraca błędu Jana."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)), raw=())
    mails = [
        report(JAN, SUBJECT, "40000001 t inst20m rt2", at=datetime(2026, 11, 9, 17)),
        report(ANNA, SUBJECT, "40000002 nieskuteczne brak klienta", at=datetime(2026, 11, 9, 17)),
    ]
    centrum = entering_centrum(tmp_path, intermax, mails)
    _finished(centrum)
    before = _cells(centrum.register)
    [anna] = _worker(_view(centrum), "anna.kowalska")["problems"]

    jan = _requests(centrum, "jan.testowy")["40000001"]
    done = _enter_on_request(centrum, jan, datetime(2026, 11, 9, 19))

    offer = {"number": "40000001", "day": "2026-11-09", "worker": "jan.testowy", "activities": "inst20m rt2"}
    assert jan == {**offer, "mail": mails[0].id.digest, "successful": "tak", "order_day": "2026-11-09"}
    assert anna["request"] == {
        "mail": mails[1].id.digest,
        "number": "40000002",
        "day": "2026-11-09",
        "worker": "anna.kowalska",
        "activities": "brak klienta",
        "successful": "nie",
        "order_day": "2026-11-09",
    }
    assert before[40000001] == (None, None)
    assert _cells(centrum.register) == {**before, 40000001: ("tak", "inst20m rt2")}
    shown = _worker(_view(centrum), "jan.testowy")
    assert (shown["problems"], shown["orders_detail"][0]["state"]) == ([], "entered")
    assert _worker(_view(centrum), "anna.kowalska")["problems"] == [anna]
    decision = {
        "mail": mails[0].id.digest,
        "worker": "jan.testowy",
        "day": "2026-11-09",
        "number": "40000001",
        "verdict": "tak",
        "activities": "inst20m rt2",
    }
    [logged] = _entering(centrum, done)["requested"]
    assert _without_moment([logged]) == [decision]
    assert datetime.fromisoformat(logged["at"]) == datetime(2026, 11, 9, 19).astimezone()

    again = _click_at(centrum, datetime(2026, 11, 9, 20), mails)

    assert _worker(_view(centrum), "jan.testowy")["problems"] == []
    assert _entering(centrum, again)["requested"] == [logged]
    assert _cells(centrum.register)[40000001] == ("tak", "inst20m rt2")


def test_pozniejszy_raport_wygrywa_z_wpisem_na_zyczenie_a_reczna_wartosc_taty_zostaje(tmp_path: Path) -> None:
    """US 49–50: późniejszy Raport Jana wygrywa z Wpisem na życzenie także wtedy, gdy znowu ma ``t``: błąd wraca z
    przyciskiem, a drugie kliknięcie znowu go wpisuje. Poprawny Raport z 20:00 wygrywa z oboma. Przy zleceniu z ręcznymi czynnościami taty Wpis na życzenie wpisuje ``nie`` do pustego
    ``SKUTECZNE``, a czynności taty zostają z różnicą „Zostaw moją”."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000005)), raw=())
    first = report(JAN, SUBJECT, "40000001 t inst20m\n40000005 n brak dostępu", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path, intermax, [first])
    _tata_writes(centrum.register, 40000005, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    offers = _requests(centrum, "jan.testowy")

    _enter_on_request(centrum, offers["40000001"], datetime(2026, 11, 9, 19))
    manual = _enter_on_request(centrum, offers["40000005"], datetime(2026, 11, 9, 19, 5))
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    repeated = report(JAN, SUBJECT, "40000001 t inst20m", at=datetime(2026, 11, 9, 19, 30), message_id="<drugi@przyklad.invalid>")
    _click_at(centrum, datetime(2026, 11, 9, 19, 45), [first, repeated])
    back = _requests(centrum, "jan.testowy")
    _enter_on_request(centrum, back["40000001"], datetime(2026, 11, 9, 19, 50))
    again = _requests(centrum, "jan.testowy")
    corrected = report(JAN, SUBJECT, "40000001 nie brak klienta", at=datetime(2026, 11, 9, 20))
    _click_at(centrum, datetime(2026, 11, 9, 20, 30), [first, repeated, corrected])

    assert _cells(centrum.register) == {40000001: ("nie", "brak klienta"), 40000005: ("nie", "wymiana ręczna")}
    assert manual["result"]["summary"]["figures"][1] == {"label": "Problemy", "value": 1, "unit": "count"}
    assert (difference["number"], difference["keep"]["reported"], difference["request"]) == ("40000005", "brak dostępu", None)
    assert back["40000001"] == {**offers["40000001"], "mail": repeated.id.digest}
    assert set(again) == set(_requests(centrum, "jan.testowy")) == {"40000005"}


def test_wpis_na_zyczenie_wpisuje_sie_takze_gdy_zegar_komputera_taty_jest_wczesniej_niz_chwila_maila(
    tmp_path: Path,
) -> None:
    """Decyzja taty należy do maila, przy którym kliknął, a nie do chwili: zegar komputera taty, który stoi przed
    chwilą przyjścia maila, nie zostawia błędu w kafelku."""

    mail = report(JAN, SUBJECT, "40000001 t inst20m", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path, INTERMAX, [mail])
    _click_at(centrum, datetime(2026, 11, 9, 18), [mail])

    _enter_on_request(centrum, _requests(centrum, "jan.testowy")["40000001"], datetime(2026, 11, 9, 16))

    assert (_cells(centrum.register)[40000001], _requests(centrum, "jan.testowy")) == (("tak", "inst20m"), {})


def _offered_problems(centrum: EnteringCentrum) -> list[tuple[str | None, bool]]:
    """Numer i przycisk Wpisu na życzenie każdego problemu Jana z 9.11 w widoku Raporty."""

    return [(problem["number"], problem["request"] is not None) for problem in _worker(_view(centrum), "jan.testowy")["problems"]]


def test_wpisu_na_zyczenie_nie_ma_przy_przeciwnych_wpisach_numerze_bez_zlecenia_i_numerze_w_kilku_miejscach(
    tmp_path: Path,
) -> None:
    """US 51: przycisku nie ma, gdy Centrum nie wie, co wpisać: przy ``t`` i ``nie`` jednego zlecenia, przy ``t`` z
    numerem, którego INTERMAX nie ma, przy numerze w kilku zleceniach INTERMAX bez zlecenia Jana i przy Wpisie bez
    żadnego znaku; jest tylko przy ``skuteczne``."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.testowy", 40000005),
            _order(9, 11, "jan.testowy", 40000006),
            _order(9, 12, "anna.kowalska", 40000007),
            _order(9, 13, "anna.kowalska", 40000007),
        ),
        raw=(),
    )
    text = "\n".join(
        (
            "40000001 t inst20m",
            "40000001 nie brak klienta",
            "40000099 t inst20m",
            "40000007 t inst20m",
            "40000005 inst20m",
            "40000006 skuteczne inst20m",
        )
    )
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, text)])

    _finished(centrum)

    assert sorted(_offered_problems(centrum)) == [
        ("40000001", False),
        ("40000005", False),
        ("40000006", True),
        ("40000007", False),
        ("40000099", False),
    ]


def test_wpis_na_zyczenie_odmawia_jednym_zdaniem_przy_intermax_w_excelu_w_trakcie_innego_uruchomienia_i_po_zmianie_wpisu(
    tmp_path: Path,
) -> None:
    """US 53: przy INTERMAX otwartym w Excelu, w trakcie innego Uruchomienia i przy Wpisie, którego nie ma w ostatnim
    kliknięciu (także przed pierwszym kliknięciem), Wpis na życzenie odmawia jednym zdaniem, nie startuje Uruchomienia
    i niczego nie zapisuje."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 t inst20m")])
    _finished(centrum)
    offer = _requests(centrum, "jan.testowy")["40000001"]
    register, state, logs = centrum.register.read_bytes(), _state(centrum).read_bytes(), len(centrum.run_logs())
    lock = open_in_excel(centrum.register)

    before_any = entering_centrum(tmp_path / "pierwsze", INTERMAX).client.post("/api/report-entering/request", json=offer)
    in_excel = centrum.client.post("/api/report-entering/request", json=offer)
    lock.unlink()
    stale = centrum.client.post("/api/report-entering/request", json={**offer, "activities": "inst25m"})
    during: list[Any] = []
    centrum.fake_inbox.during = lambda: during.append(centrum.client.post("/api/report-entering/request", json=offer))
    _finished(centrum)

    assert (in_excel.status_code, in_excel.json()["message"]) == (
        409,
        "INTERMAX jest otwarty w Excelu, więc nic się nie wpisało: zapisz i zamknij INTERMAX, potem kliknij jeszcze raz.",
    )
    gone = "Tego Wpisu nie ma w ostatnim Wpisaniu raportów. Odśwież widok Raporty."
    assert [(answer.status_code, answer.json()["message"]) for answer in (stale, before_any)] == [(404, gone)] * 2
    [running] = during
    assert (running.status_code, running.json()["message"]) == (
        409,
        f"Trwa już Uruchomienie procesu: Wpisanie raportów, okres {ENTERING_PERIOD}. Poczekaj na jego wynik w Uruchomieniach.",
    )
    assert (centrum.register.read_bytes(), len(centrum.run_logs())) == (register, logs + 1)
    assert json.loads(_state(centrum).read_bytes())["requested"] == json.loads(state)["requested"] == []


def test_wpis_na_zyczenie_z_widoku_sprzed_nowszego_klikniecia_odmawia_a_przycisk_nowszego_wpisuje_wpis_pozniejszego_maila(
    tmp_path: Path,
) -> None:
    """US 49 i 53: późniejszy mail Jana z tym samym ``t`` przy tym samym zleceniu wygrywa, więc nowsze kliknięcie daje
    nowy przycisk, który różni się od dawnego tylko mailem. Przycisk z widoku sprzed nowszego kliknięcia jest
    nieaktualny: odmawia jednym zdaniem, nie startuje Uruchomienia i niczego nie zapisuje, a przycisk nowszego kliknięcia
    wpisuje Wpis późniejszego maila z decyzją przy tym mailu. Tak samo odmawia przycisk nowszego kliknięcia z innym
    dniem zlecenia po Wpisie, niż ma ten przycisk w wyniku, bo tata kliknąłby co innego, niż widział."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001),), raw=())
    first = report(JAN, SUBJECT, "40000001 t inst20m", at=datetime(2026, 11, 9, 17))
    later = report(JAN, SUBJECT, "40000001 t inst20m", at=datetime(2026, 11, 9, 18), message_id="<drugi@przyklad.invalid>")
    centrum = entering_centrum(tmp_path, intermax, [first])
    _finished(centrum)
    old = _requests(centrum, "jan.testowy")["40000001"]
    _click_at(centrum, datetime(2026, 11, 9, 19), [first, later])
    new = _requests(centrum, "jan.testowy")["40000001"]
    register, state, logs = centrum.register.read_bytes(), _state(centrum).read_bytes(), len(centrum.run_logs())

    stale = centrum.client.post("/api/report-entering/request", json=old)
    other_day = centrum.client.post("/api/report-entering/request", json={**new, "order_day": "2026-11-10"})

    assert old == {**new, "mail": first.id.digest} != new
    gone = "Tego Wpisu nie ma w ostatnim Wpisaniu raportów. Odśwież widok Raporty."
    assert [(answer.status_code, answer.json()["message"]) for answer in (stale, other_day)] == [(404, gone)] * 2
    assert (centrum.register.read_bytes(), _state(centrum).read_bytes(), len(centrum.run_logs())) == (register, state, logs)
    done = _enter_on_request(centrum, new, datetime(2026, 11, 9, 19, 30))
    assert [decision["mail"] for decision in _entering(centrum, done)["requested"]] == [later.id.digest]
    assert _cells(centrum.register)[40000001] == ("tak", "inst20m")


def test_wpis_na_zyczenie_przy_nieczytelnym_pliku_wyniku_odmawia_bez_uruchomienia(tmp_path: Path) -> None:
    """Pliku wyniku, którego nie da się odczytać, Wpis na życzenie nie bierze za wynik bez tego Wpisu: odmawia tym samym
    zdaniem co widok Raporty i nie startuje Uruchomienia."""

    centrum = entering_centrum(tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 t inst20m")])
    _finished(centrum)
    offer = _requests(centrum, "jan.testowy")["40000001"]
    (centrum.tool.config / REPORT_ENTERING_RESULT).write_text("{nie json", encoding="utf-8")
    logs = len(centrum.run_logs())

    refused = centrum.client.post("/api/report-entering/request", json=offer)

    assert (refused.status_code, refused.json()["message"]) == (
        500,
        "Nie udało się odczytać wyniku Wpisania raportów ani decyzji „Zostaw moją”. Odśwież kartę, a gdy to się "
        "powtarza, wyślij Uwagę ogólną.",
    )
    assert (len(centrum.run_logs()), centrum.client.get("/api/runs/current").json()["state"]) == (logs, "finished")


def _order_requests(centrum: EnteringCentrum, login: str, day: str = "2026-11-09") -> dict[str, Any]:
    """Stan i Wpis na życzenie każdego zlecenia dnia ``day`` Wykonawcy ``login`` w widoku Raporty, po numerze."""

    return {
        order["number"]: (order["state"], order["request"])
        for order in _worker(_view(centrum), login, day)["orders_detail"]
    }


def test_wpis_na_zyczenie_przy_raporcie_z_bledem_tematu_wpisuje_wpis_do_dnia_z_tematu_i_do_wskazanego_dnia(
    tmp_path: Path,
) -> None:
    """US 44, 46, 48 i 52: przy każdym zleceniu raportu ``Raport 09.11.2026 Kowalski`` (stan „Błąd tematu”) widok
    Raporty ma Wpis na życzenie z dniem z tematu, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``, także przy Wpisie z ``t``
    (wpisze ``tak``), a przy raporcie Anny ``Raport`` bez dnia z dniem, który Centrum wskazuje (8.11). Kliknięcie
    wpisuje jednym Uruchomieniem tylko ten Wpis; błąd tematu Jana stoi, dopóki tata nie wpisze obu jego Wpisów, a
    potem znika i nie wraca przy następnym kliknięciu „Wpisz raporty z maili”. Logi mają każdą decyzję taty. Chwila
    przyjścia raportu z błędem tematu idzie w UTC (``Z``), jak każda chwila kontraktu, bo stronę Raporty odrzuca inną."""

    ordered = (
        _order(9, 9, "jan.testowy", 40000001),
        _order(9, 10, "jan.testowy", 40000003),
        _order(8, 11, "anna.kowalska", 40000002),
    )
    mails = [
        report(JAN, "Raport 09.11.2026 Kowalski", "40000001 tak inst20m\n40000003 t spawpg"),
        report(ANNA, "Raport", "40000002 nie brak klienta"),
    ]
    centrum = entering_centrum(tmp_path, Intermax(ordered=ordered, raw=()))
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    _click_at(centrum, ENTERING_NOW, mails)
    jan, anna = _order_requests(centrum, "jan.testowy"), _order_requests(centrum, "anna.kowalska", "2026-11-08")
    [faulty_arrived] = [problem["faulty_subject"]["arrived"] for problem in _worker(_view(centrum), "jan.testowy")["problems"]]

    first = _enter_on_request(centrum, jan["40000001"][1], datetime(2026, 11, 9, 19))
    between = (_cells(centrum.register), _order_requests(centrum, "jan.testowy"), len(_worker(_view(centrum), "jan.testowy")["problems"]))
    second = _enter_on_request(centrum, jan["40000003"][1], datetime(2026, 11, 9, 19, 5))
    _enter_on_request(centrum, anna["40000002"][1], datetime(2026, 11, 9, 19, 10))
    again = _click_at(centrum, datetime(2026, 11, 9, 20), mails)

    on_jan = {"day": "2026-11-09", "worker": "jan.testowy", "mail": mails[0].id.digest, "order_day": "2026-11-09"}
    assert jan == {
        "40000001": ("faulty_subject", {**on_jan, "number": "40000001", "activities": "inst20m", "successful": "tak"}),
        "40000003": ("faulty_subject", {**on_jan, "number": "40000003", "activities": "spawpg", "successful": "tak"}),
    }
    on_anna = {"day": "2026-11-08", "worker": "anna.kowalska", "mail": mails[1].id.digest, "order_day": "2026-11-08"}
    assert anna == {"40000002": ("faulty_subject", {**on_anna, "number": "40000002", "activities": "brak klienta", "successful": "nie"})}
    assert between == (
        {40000001: ("tak", "inst20m"), 40000003: (None, None), 40000002: (None, None)},
        {"40000001": ("entered", None), "40000003": jan["40000003"]},
        1,
    )
    assert _cells(centrum.register) == {40000001: ("tak", "inst20m"), 40000003: ("tak", "spawpg"), 40000002: ("nie", "brak klienta")}
    for login, day in (("jan.testowy", "2026-11-09"), ("anna.kowalska", "2026-11-08")):
        shown = _worker(_view(centrum), login, day)
        assert (shown["problems"], {order["state"] for order in shown["orders_detail"]}) == ([], {"entered"}), shown
    assert [decision["number"] for decision in _entering(centrum, first)["requested"]] == ["40000001"]
    assert faulty_arrived.endswith("Z"), faulty_arrived
    assert _without_moment(_entering(centrum, second)["requested"]) == [
        {"mail": mails[0].id.digest, "worker": "jan.testowy", "day": "2026-11-09", "number": number, "verdict": "tak", "activities": activities}
        for number, activities in (("40000001", "inst20m"), ("40000003", "spawpg"))
    ]
    assert len(_entering(centrum, again)["requested"]) == 3


def test_pozniejszy_raport_wygrywa_z_wpisem_na_zyczenie_z_raportu_z_bledem_tematu_a_reczna_wartosc_zostaje(
    tmp_path: Path,
) -> None:
    """US 49–50: Wpis na życzenie z raportu z błędem tematu wpisuje się jak Wpis z chwilą przyjścia tego maila, więc
    późniejszy poprawny Raport Jana za 9.11 wygrywa z nim, a przy zleceniu z ręcznymi czynnościami taty Wpis na życzenie
    wpisuje tylko pusty ``SKUTECZNE``, a czynności taty zostają z różnicą „Zostaw moją”."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000005)), raw=())
    faulty = report(JAN, "Raport 09.11.2026 Kowalski", "40000001 tak inst20m\n40000005 nie brak dostępu", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path, intermax, [faulty])
    _tata_writes(centrum.register, 40000005, "wymiana ręczna", column=COMPLETED)
    _finished(centrum)
    offers = _order_requests(centrum, "jan.testowy")

    _enter_on_request(centrum, offers["40000001"][1], datetime(2026, 11, 9, 19))
    _enter_on_request(centrum, offers["40000005"][1], datetime(2026, 11, 9, 19, 5))
    [difference] = _worker(_view(centrum), "jan.testowy")["problems"]
    corrected = report(JAN, SUBJECT, "40000001 nie brak klienta", at=datetime(2026, 11, 9, 20))
    _click_at(centrum, datetime(2026, 11, 9, 20, 30), [faulty, corrected])

    assert _cells(centrum.register) == {40000001: ("nie", "brak klienta"), 40000005: ("nie", "wymiana ręczna")}
    assert (difference["number"], difference["keep"]["reported"]) == ("40000005", "brak dostępu")
    assert [problem["number"] for problem in _worker(_view(centrum), "jan.testowy")["problems"]] == ["40000005"]


def _rows(register: Path) -> list[tuple[object, ...]]:
    """Wartości każdego wiersza arkusza zleceń od góry."""

    return [tuple(cell.value for cell in row) for row in load_workbook(register)[ORDER_SHEET].iter_rows()]


def test_wpis_na_zyczenie_przy_raporcie_z_bledem_tematu_z_przeniesieniem_przenosi_zlecenie_jak_poprawny_raport(
    tmp_path: Path,
) -> None:
    """ADR 0041 i 0029 (US 44): Anna przysyła ``Raport 09.11.2026 Nowak`` z jedynym zleceniem Jana z 9.11. Przy tym
    zleceniu u Jana stoi Wpis na życzenie z Anną i 9.11 (stan „Błąd tematu”, nie „Bez raportu”), a kliknięcie daje w
    INTERMAX to samo Przeniesienie i Wpis co poprawny raport Anny za 9.11; błąd tematu znika, a zlecenie stoi u Anny."""

    def intermax() -> Intermax:
        return Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)), raw=())

    faulty = report(ANNA, "Raport 09.11.2026 Nowak", "40000001 tak inst20m")
    centrum = entering_centrum(tmp_path / "blad", intermax(), [faulty])
    right = entering_centrum(tmp_path / "poprawny", intermax(), [report(ANNA, SUBJECT, "40000001 tak inst20m")])
    _finished(centrum)
    _finished(right)
    offers = _order_requests(centrum, "jan.testowy")

    _enter_on_request(centrum, offers["40000001"][1], datetime(2026, 11, 9, 19))

    assert offers == {
        "40000001": (
            "faulty_subject",
            {
                "mail": faulty.id.digest,
                "worker": "anna.kowalska",
                "day": "2026-11-09",
                "number": "40000001",
                "activities": "inst20m",
                "successful": "tak",
                "order_day": "2026-11-09",
            },
        )
    }
    assert _workers(centrum.register)[40000001] == "anna.kowalska"
    assert _rows(centrum.register) == _rows(right.register)
    anna = _worker(_view(centrum), "anna.kowalska")
    assert (anna["problems"], [order["number"] for order in anna["orders_detail"]]) == ([], ["40000002", "40000001"])


@pytest.mark.parametrize(
    ("sender", "subject", "numbers", "place"),
    [
        pytest.param(JAN, "Raport 09.11.2026 Kowalski", ["40000001"], ("jan.testowy", "2026-11-09"), id="wlasne-zlecenie"),
        pytest.param(ANNA, "Raport 09.11.2026 Nowak", ["40000001", "40000002"], ("anna.kowalska", "2026-11-09"), id="do-nadawcy"),
        pytest.param(JAN, "Raport 10.11.2026 Kowalski", ["40000001"], ("jan.testowy", "2026-11-10"), id="na-dzien-z-tematu"),
    ],
)
def test_dzien_ze_zleceniem_z_wpisem_na_zyczenie_nie_jest_komplet_a_blad_tematu_nadawcy_ma_jego_przycisk(
    tmp_path: Path, sender: str, subject: str, numbers: list[str], place: tuple[str, str]
) -> None:
    """Historie 42 i 44 speca #2032 przy każdym rodzaju Wpisu na życzenie raportu z błędem tematu: własne zlecenie
    nadawcy, Przeniesienie do nadawcy (Anna raportuje zlecenie Jana obok swojego) i Przeniesienie na dzień z tematu (Jan
    raportuje 10.11 zlecenie z 9.11). Problem raportu z błędem tematu w dniu, za który Centrum go liczy, ma przy numerze
    każdego zlecenia raportu ten sam Wpis na życzenie co to zlecenie, więc tata klika tam, gdzie widzi błąd. Dzień
    Wykonawcy, w którym takie zlecenie stoi, ma ten problem z Wpisami swoich zleceń, więc strona nie pokaże go jako
    Komplet ani nie schowa filtrem „Problem”."""

    ordered = (_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002), _order(10, 9, "jan.testowy", 40000003))
    faulty = report(sender, subject, "\n".join(f"{number} tak inst20m" for number in numbers))
    centrum = entering_centrum(tmp_path, Intermax(ordered=ordered, raw=()))
    _click_at(centrum, datetime(2026, 11, 9, 12), [])
    _click_at(centrum, datetime(2026, 11, 10, 18), [faulty])
    view = _view(centrum)
    offers = {
        order["number"]: {"worker": worker["worker"], "day": day["day"], "request": order["request"]}
        for worker in view["workers"]
        for day in worker["days"]
        for order in day["orders_detail"]
        if order["request"] is not None
    }
    holders = {(offer["worker"], offer["day"]) for offer in offers.values()}

    def faults(where: tuple[str, str]) -> list[list[dict[str, Any]]]:
        """Wpisy na życzenie każdego problemu raportu z błędem tematu dnia ``where``, po numerze zlecenia."""

        return [
            sorted(problem["faulty_subject"]["offers"], key=lambda offer: str(offer["request"]["number"]))
            for problem in _worker(view, *where)["problems"]
            if problem["faulty_subject"]
        ]

    assert sorted(offers) == numbers
    assert {where: bool(day["problems"] or day["without_report"]) for where in holders for day in [_worker(view, *where)]} == (
        dict.fromkeys(holders, True)
    )
    assert faults(place) == [[offers[number] for number in numbers]]
    assert {where: faults(where) for where in holders - {place}} == {
        where: [[offer for offer in offers.values() if (offer["worker"], offer["day"]) == where]] for where in holders - {place}
    }


def test_wpisu_na_zyczenie_przy_raporcie_z_bledem_tematu_nie_ma_przy_przeciwnych_wpisach_wpisie_bez_znaku_i_numerze_dwa_razy(
    tmp_path: Path,
) -> None:
    """US 51: przy zleceniach raportu z błędem tematu przycisk jest tylko tam, gdzie Centrum wie, co wpisać: nie ma go
    przy ``t`` i ``nie`` jednego zlecenia, przy Wpisie bez żadnego znaku i przy numerze, który Jan ma dwa razy w dniu;
    jest przy ``tak``. Raport z błędem tematu bez wskazanego dnia (Anna bez zleceń) nie ma zleceń, więc i przycisku."""

    intermax = Intermax(
        ordered=(
            _order(9, 9, "jan.testowy", 40000001),
            _order(9, 10, "jan.testowy", 40000005),
            _order(9, 11, "jan.testowy", 40000006),
            _order(9, 12, "jan.testowy", 40000008),
            _order(9, 13, "jan.testowy", 40000008),
        ),
        raw=(),
    )
    text = "\n".join(("40000001 t inst20m", "40000001 nie brak klienta", "40000005 inst20m", "40000006 tak inst20m", "40000008 tak spawpg"))
    mails = [report(JAN, "Raport 09.11.2026 Kowalski", text), report(ANNA, "Raport", "40000002 tak montaż")]
    centrum = entering_centrum(tmp_path, intermax, mails)

    _finished(centrum)

    shown = _order_requests(centrum, "jan.testowy")
    assert {number: request is not None for number, (_, request) in shown.items()} == {
        "40000001": False,
        "40000005": False,
        "40000006": True,
        "40000008": False,
    }
    assert [problem["request"] for problem in _worker(_view(centrum), "anna.kowalska")["problems"]] == [None]


TAKEN_OVER = (
    "Raport wykonawcy od jan.testowy z 09.11.2026, 17:00 z tematem „Raport 09.11.2026 Kowalski tel. [telefon]” ma błąd "
    "w temacie (inne słowa), ale każde jego zlecenie wziął późniejszy raport od anna.kowalska, więc nie ma w nim nic do "
    "wpisania."
)


@pytest.mark.parametrize(
    ("subject", "text", "anna_problems"),
    [
        pytest.param(SUBJECT, "40000002 tak montaż", [], id="poprawny-raport-anny"),
        pytest.param("Raport 09.11.2026 Nowak", "40000002 tak montaż", [None], id="raport-anny-z-bledem-tematu"),
        pytest.param(SUBJECT, "40000002 t montaż", ["40000002"], id="raport-anny-z-litera-t"),
    ],
)
def test_blad_tematu_ktorego_kazde_zlecenie_wzial_pozniejszy_raport_innego_wykonawcy_jest_informacja_a_nie_problemem(
    tmp_path: Path, subject: str, text: str, anna_problems: list[str | None]
) -> None:
    """ADR 0041: Jan przysyła ``Raport 09.11.2026 Kowalski`` z telefonem i z jedynym zleceniem Anny z 9.11, a później
    Anna przysyła swój raport z tym zleceniem, więc o zleceniu decyduje jej Wpis. Błąd tematu Jana nie ma już czego
    wpisać: dzień Jana nie ma problemu, tylko jedno zdanie informacji z tematem po strażniku reguły danych, a raport dalej liczy się za 9.11, także przy następnym kliknięciu,
    gdy pamięć wpisów po Wpisie Anny nie pozwala już starszemu mailowi Jana ruszyć zlecenia. Dzień Anny jest jak dziś:
    po poprawnym raporcie zlecenie wpisane, po raporcie z błędem tematu i po Wpisie z ``t``, którego Centrum nie wpisało,
    jej problem z Wpisem na życzenie."""

    intermax = Intermax(ordered=(_order(9, 11, "anna.kowalska", 40000002),), raw=())
    mails = [
        report(JAN, "Raport 09.11.2026 Kowalski tel. 600 123 456", "40000002 tak inst20m", at=datetime(2026, 11, 9, 17)),
        report(ANNA, subject, text, at=datetime(2026, 11, 9, 18)),
    ]
    centrum = entering_centrum(tmp_path, intermax, mails)

    for moment in (datetime(2026, 11, 9, 19), datetime(2026, 11, 9, 20)):
        _click_at(centrum, moment, mails)

        view = _view(centrum)
        jan, anna = _worker(view, "jan.testowy"), _worker(view, "anna.kowalska")
        assert (jan["problems"], jan["overtaken_subjects"], jan["mails"], jan["orders"]) == ([], [TAKEN_OVER], 1, 0)
        assert ([problem["number"] for problem in anna["problems"]], anna["overtaken_subjects"]) == (anna_problems, [])
        assert all(problem["request"] or problem["faulty_subject"]["offers"] for problem in anna["problems"])
        assert [order["number"] for order in anna["orders_detail"]] == ["40000002"]
        assert _workers(centrum.register)[40000002] == "anna.kowalska"


def test_blad_tematu_z_jednym_zleceniem_wzietym_przez_pozniejszy_raport_zostaje_problemem_z_przyciskiem_drugiego(
    tmp_path: Path,
) -> None:
    """ADR 0041: raport Jana z błędem tematu ma swoje zlecenie i zlecenie Anny, które później bierze raport Anny. Jego
    własne zlecenie dalej czeka na decyzję taty, więc błąd tematu zostaje problemem dnia Jana z jednym Wpisem na życzenie
    (przy jego zleceniu), bez informacji; dzień Anny nie ma problemu. Po kliknięciu tego Wpisu raport nie ma już czego
    wpisać, więc błąd tematu znika, a informacji też nie ma, bo jedno jego zlecenie wpisał tata."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)), raw=())
    mails = [
        report(JAN, "Raport 09.11.2026 Kowalski", "40000001 tak inst20m\n40000002 tak inst20m", at=datetime(2026, 11, 9, 17)),
        report(ANNA, SUBJECT, "40000002 tak montaż", at=datetime(2026, 11, 9, 18)),
    ]
    centrum = entering_centrum(tmp_path, intermax, mails)

    _finished(centrum)

    view = _view(centrum)
    jan, anna = _worker(view, "jan.testowy"), _worker(view, "anna.kowalska")
    [problem] = jan["problems"]
    assert [offer["request"]["number"] for offer in problem["faulty_subject"]["offers"]] == ["40000001"]
    assert [(order["number"], order["request"] is not None) for order in jan["orders_detail"]] == [("40000001", True)]
    assert (jan["overtaken_subjects"], anna["problems"], anna["overtaken_subjects"]) == ([], [], [])

    _enter_on_request(centrum, jan["orders_detail"][0]["request"], datetime(2026, 11, 9, 19))

    after = _worker(_view(centrum), "jan.testowy")
    assert (after["problems"], after["overtaken_subjects"]) == ([], [])
    assert _cells(centrum.register) == {40000001: ("tak", "inst20m"), 40000002: ("tak", "montaż")}


def test_wpisy_na_zyczenie_dwoch_wykonawcow_z_tym_samym_message_id_wpisuja_kazdy_swoj_wpis(tmp_path: Path) -> None:
    """Message-ID ustawia nadawca, więc mail Jana i mail Anny mogą mieć ten sam skrót. Jan przysyła Wpis z ``t`` do
    swojego zlecenia, a później Anna raport z błędem tematu z tym samym Message-ID i Wpisem ``tak`` z tymi samymi
    czynnościami do tego zlecenia: przy problemie Jana stoi jego Wpis na życzenie, a przy zleceniu Wpis Anny, który
    przeniesie je do niej. Przyciski różnią się tylko Wykonawcą, a kliknięcie każdego wpisuje jego Wpis: Jana w
    zleceniu u Jana, Anny z Przeniesieniem zlecenia do Anny."""

    def intermax() -> Intermax:
        return Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)), raw=())

    shared = "<wspolny@przyklad.invalid>"
    mails = [
        report(JAN, SUBJECT, "40000001 t inst20m", at=datetime(2026, 11, 9, 17), message_id=shared),
        report(ANNA, "Raport 09.11.2026 Nowak", "40000001 tak inst20m", at=datetime(2026, 11, 9, 18), message_id=shared),
    ]
    clicked: dict[str, tuple[dict[str, Any], tuple[object, object], object]] = {}
    for login in ("jan.testowy", "anna.kowalska"):
        centrum = entering_centrum(tmp_path / login, intermax(), mails)
        _finished(centrum)
        at_order = _order_requests(centrum, "jan.testowy")["40000001"][1]
        offers = {"jan.testowy": _requests(centrum, "jan.testowy")["40000001"], "anna.kowalska": at_order}

        _enter_on_request(centrum, offers[login], datetime(2026, 11, 9, 19))

        clicked[login] = (offers, _cells(centrum.register)[40000001], _workers(centrum.register)[40000001])

    offers = clicked["jan.testowy"][0]
    assert mails[0].id == mails[1].id
    assert offers == clicked["anna.kowalska"][0]
    assert offers["jan.testowy"] == {**offers["anna.kowalska"], "worker": "jan.testowy"} != offers["anna.kowalska"]
    assert {login: found[1:] for login, found in clicked.items()} == {
        "jan.testowy": (("tak", "inst20m"), "jan.testowy"),
        "anna.kowalska": (("tak", "inst20m"), "anna.kowalska"),
    }


def test_widok_raporty_stawia_blad_tematu_przy_jego_nadawcy_z_jego_wpisami_na_zyczenie_takze_przy_wspolnym_message_id(
    tmp_path: Path,
) -> None:
    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 11, "anna.kowalska", 40000002)), raw=())
    shared = "<wspolny@przyklad.invalid>"
    mails = [
        report(JAN, "Raport 09.11.2026 Kowalski", "40000001 tak inst20m", at=datetime(2026, 11, 9, 17), message_id=shared),
        report(ANNA, "Raport 09.11.2026 Nowak", "40000002 tak montaż", at=datetime(2026, 11, 9, 18), message_id=shared),
    ]
    centrum = entering_centrum(tmp_path, intermax, mails)
    _finished(centrum)

    view = _view(centrum)

    assert mails[0].id == mails[1].id
    assert {
        login: [[offer["request"]["number"] for offer in problem["faulty_subject"]["offers"]] for problem in _worker(view, login)["problems"]]
        for login in ("jan.testowy", "anna.kowalska")
    } == {"jan.testowy": [["40000001"]], "anna.kowalska": [["40000002"]]}


def _v0_14_0_click() -> tuple[Intermax, list[ReportMail]]:
    """INTERMAX i maile kliknięcia, po którym Centrum z Wydania v0.14.0 zapisało pliki
    ``tests/fixtures/wpisanie-raportow-wynik-v3-oferty.json`` i ``tests/fixtures/wpisanie-raportow-stan-v4-requested.json``
    (swoim kodem, w worktree na tagu ``v0.14.0``): Anna przysyła ``Raport 09.11.2026 Nowak`` (błąd tematu) ze zleceniem
    Jana (Przeniesienie do Anny) i swoim, a Jan Wpis z ``t``. Plik wyniku zapisało pierwsze kliknięcie, a plik pamięci
    Wpisy na życzenie Jana przy problemie i Anny przy jej zleceniu, każdy swoim Uruchomieniem."""

    intermax = Intermax(
        ordered=(_order(9, 9, "jan.testowy", 40000001), _order(9, 10, "jan.testowy", 40000003), _order(9, 11, "anna.kowalska", 40000002)),
        raw=(),
    )
    mails = [
        report(ANNA, "Raport 09.11.2026 Nowak", "40000001 tak inst20m\n40000002 tak montaż"),
        report(JAN, SUBJECT, "40000003 t spawpg"),
    ]
    return intermax, mails


def _buttons(view: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Każdy przycisk Wpisu na życzenie widoku Raporty: Wykonawca i dzień kafelka, miejsce (zlecenie, problem albo raport
    z błędem tematu z kafelkiem zlecenia) i cała komórka ``request``, po kolei widoku."""

    found: list[tuple[str, str, str, dict[str, Any]]] = []
    for worker in view["workers"]:
        for day in worker["days"]:
            place = (worker["worker"], day["day"])
            found += [(*place, f"zlecenie {order['number']}", order["request"]) for order in day["orders_detail"] if order["request"]]
            for problem in day["problems"]:
                if problem["request"]:
                    found.append((*place, f"problem {problem['number']}", problem["request"]))
                for offer in (problem["faulty_subject"] or {}).get("offers", ()):
                    found.append((*place, f"błąd tematu przy {offer['worker']} {offer['day']}", offer["request"]))
    return found


@pytest.mark.parametrize(
    ("button", "written", "worker"),
    [
        pytest.param(("jan.testowy", "problem 40000003"), {40000003: ("tak", "spawpg")}, "jan.testowy", id="przy-problemie-z-t"),
        pytest.param(
            ("jan.testowy", "zlecenie 40000001"), {40000001: ("tak", "inst20m")}, "anna.kowalska", id="przy-zleceniu-z-przeniesieniem"
        ),
        pytest.param(("anna.kowalska", "zlecenie 40000002"), {40000002: ("tak", "montaż")}, "anna.kowalska", id="przy-zleceniu-nadawcy"),
    ],
)
def test_plik_wyniku_z_wpisami_na_zyczenie_z_wydania_v0_14_0_daje_te_same_przyciski_a_klikniecie_wpisuje_wpis(
    tmp_path: Path, button: tuple[str, str], written: dict[int, tuple[str, str]], worker: str
) -> None:
    """ADR 0041: plik wyniku z Wpisami na życzenie, który zapisało Centrum z Wydania v0.14.0 (wersja 3: przy zleceniu
    Wpis bez dnia i numeru, przy problemie cały), leży u taty w ``config`` po aktualizacji. Widok Raporty daje z niego
    te same przyciski co v0.14.0, z całą komórką ``request`` przy zleceniach, przy problemie i przy raporcie z błędem
    tematu, a kliknięcie przycisku z tego pliku startuje Wpisanie raportów, które wpisuje ten Wpis, przy zleceniu Jana
    z Przeniesieniem do Anny."""

    intermax, mails = _v0_14_0_click()
    centrum = entering_centrum(tmp_path, intermax, mails)
    shutil.copyfile(ROOT / "tests" / "fixtures" / "wpisanie-raportow-wynik-v3-oferty.json", centrum.tool.config / REPORT_ENTERING_RESULT)
    before = _cells(centrum.register)

    shown = _buttons(_view(centrum))
    [cell] = [found[3] for found in shown if (found[0], found[2]) == button]
    _enter_on_request(centrum, cell, datetime(2026, 11, 9, 19))

    anna = {"mail": mails[0].id.digest, "worker": "anna.kowalska", "day": "2026-11-09", "successful": "tak", "order_day": "2026-11-09"}
    moved, own = {**anna, "number": "40000001", "activities": "inst20m"}, {**anna, "number": "40000002", "activities": "montaż"}
    jan = {"mail": mails[1].id.digest, "worker": "jan.testowy", "day": "2026-11-09", "successful": "tak", "order_day": "2026-11-09"}
    assert shown == [
        ("anna.kowalska", "2026-11-09", "zlecenie 40000002", own),
        ("anna.kowalska", "2026-11-09", "błąd tematu przy anna.kowalska 2026-11-09", own),
        ("anna.kowalska", "2026-11-09", "błąd tematu przy jan.testowy 2026-11-09", moved),
        ("jan.testowy", "2026-11-09", "zlecenie 40000001", moved),
        ("jan.testowy", "2026-11-09", "błąd tematu przy jan.testowy 2026-11-09", moved),
        ("jan.testowy", "2026-11-09", "problem 40000003", {**jan, "number": "40000003", "activities": "spawpg"}),
    ]
    assert _cells(centrum.register) == {**before, **written}
    assert {number: _workers(centrum.register)[number] for number in written} == dict.fromkeys(written, worker)


def test_plik_pamieci_z_decyzjami_wpisu_na_zyczenie_z_wydania_v0_14_0_wpisuje_je_przy_nastepnym_kliknieciu(tmp_path: Path) -> None:
    """ADR 0041: plik pamięci w wersji 4 z decyzjami taty Wpisu na życzenie (``requested``), który zapisało Centrum z
    Wydania v0.14.0 po Wpisie Jana z ``t`` przy problemie i Wpisie Anny z raportu z błędem tematu przy jej zleceniu,
    leży u taty w ``config`` po aktualizacji, a INTERMAX nie ma tych Wpisów. Następne „Wpisz raporty z maili” wpisuje
    oba z decyzji z pliku, jak Wpisy z ``tak``: problem Jana i przycisk przy zleceniu Anny nie wracają, Logi mają obie
    decyzje, a plik pamięci zachowuje je bez zmian. Wpis Anny do zlecenia Jana, przy którym tata nie kliknął, zostaje
    z przyciskiem."""

    intermax, mails = _v0_14_0_click()
    centrum = entering_centrum(tmp_path, intermax, mails)
    saved = ROOT / "tests" / "fixtures" / "wpisanie-raportow-stan-v4-requested.json"
    shutil.copyfile(saved, _state(centrum))

    view = _finished(centrum)

    decisions = json.loads(saved.read_text(encoding="utf-8"))["requested"]
    assert _cells(centrum.register) == {40000001: (None, None), 40000003: ("tak", "spawpg"), 40000002: ("tak", "montaż")}
    assert [problem["number"] for problem in _worker(_view(centrum), "jan.testowy")["problems"]] == [None]
    assert [(button[0], button[2]) for button in _buttons(_view(centrum))] == [
        ("anna.kowalska", "błąd tematu przy jan.testowy 2026-11-09"),
        ("jan.testowy", "zlecenie 40000001"),
        ("jan.testowy", "błąd tematu przy jan.testowy 2026-11-09"),
    ]
    assert sorted(_without_moment(_entering(centrum, view)["requested"]), key=str) == sorted(_without_moment(decisions), key=str)
    assert json.loads(_state(centrum).read_text(encoding="utf-8"))["requested"] == decisions


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
    message.set_content(f"40000002 tak {COMPLETED_WITHOUT_CODES}")
    return AtrapaMail(uid, at.astimezone(), bytes(message))


def _reminders_form(**changes: object) -> dict[str, object]:
    """Formularz sekcji Przypomnienia z wartościami domyślnymi z ADR 0030 i zmianami ``changes``."""

    form: dict[str, object] = {
        "morning": {"start": "08:00", "end": "17:00"},
        "evening": {"start": "18:00", "end": "22:00"},
        "first": "08:00",
        "text": "Poproszę o wysłanie raportu za dzień {dzień}.",
        "footer": "",
    }
    return {**form, **changes}


def _reminders_set_up(centrum: EnteringCentrum, *, footer: str = "Pozdrawiam\nTata\n") -> None:
    """Plik Maksa z dostępem do skrzynki raportów w ``config``, a w Ustawieniach tata włącza przypomnienia w dniu
    zleceń 9.11.2026 (dzień wdrożenia) i wpisuje stopkę (``""``: bez stopki)."""

    (centrum.tool.config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\n{HASLO}\n", encoding="utf-8")
    assert centrum.client.put("/api/settings/reminders/enabled", json={"enabled": True}).status_code == 200
    assert centrum.client.put("/api/settings/reminders", json=_reminders_form(footer=footer)).status_code == 200


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
            lambda: read_snapshot(ToolDirectory(tmp_path).config).inbox,
            connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
            smtp=lambda: smtplib.SMTP("127.0.0.1", smtp.port, timeout=10),
        )
        centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
        _reminders_set_up(centrum)
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


@pytest.mark.parametrize("footer", ["", "   \n"], ids=["pusta", "same-spacje"])
def test_praca_przypomnien_bez_stopki_wysyla_bez_niej_a_wynik_mowi_o_braku_stopki(tmp_path: Path, footer: str) -> None:
    """Bez stopki w Ustawieniach (także ze stopką z samych spacji) przypomnienie idzie bez niej, a wynik ostatniego
    sprawdzenia dla widoku Raporty mówi o tym (US 44)."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum, footer=footer)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, reminder.text.endswith("12345679 nie brak klienta\n")) for reminder, _ in mailbox.sends] == [
        ("anna.kowalska", True),
        ("jan.testowy", True),
    ]
    assert _reminder_result(centrum)["footer"] == "missing"


@dataclass
class _MailboxBrokenOnce(FakeMailbox):
    """Skrzynka Przypomnień, której pierwsze pytanie o „Wysłane” kończy się wyjątkiem spoza portu skrzynki."""

    broke: bool = False

    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        if not self.broke:
            self.broke = True
            raise RuntimeError("syntetyczna awaria")
        return super().sent_reminders(day)


def test_nieoczekiwany_wyjatek_sprawdzenia_przypomnien_trafia_do_dziennika_a_nastepne_sprawdzenie_wysyla(
    tmp_path: Path,
) -> None:
    """Praca w tle nie może zgasić rytmu Przypomnień o raporcie: wyjątek jednego sprawdzenia ma dziennik Centrum, a
    następne tyknięcie rytmu sprawdza i wysyła jak zwykle."""

    mailbox = _MailboxBrokenOnce()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    after_failure = list(mailbox.sends)
    centrum.rhythm.tick()
    centrum.client.stop()

    assert after_failure == []
    assert 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="Przypomnienia o raporcie"' in centrum.tool.log_path.read_text(encoding="utf-8")
    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]


@pytest.mark.parametrize(
    ("login", "switches", "reminded"),
    [
        pytest.param("anna.kowalska", {"active": False}, ["jan.testowy"], id="nieaktywny"),
        pytest.param("jan.testowy", {"reminders": False}, ["anna.kowalska"], id="bez-przypomnien"),
    ],
)
def test_nieaktywny_i_bez_przypomnien_z_ustawien_nie_dostaja_przypomnienia_od_nastepnego_sprawdzenia(
    tmp_path: Path, login: str, switches: dict[str, bool], reminded: list[str]
) -> None:
    """ADR 0032, US 34, 37 (#1474): przełącznik na karcie Wykonawcy w Ustawieniach działa od następnego sprawdzenia
    przypomnień: Nieaktywny Wykonawca i Wykonawca z wyłączonymi Przypomnieniami o raporcie ich nie dostają, inni tak."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    switched = centrum.client.put(f"/api/settings/workers/{login}/switches", json=switches)
    centrum.rhythm.tick()
    centrum.client.stop()

    assert switched.status_code == 200, switched.json()
    assert [reminder.worker for reminder, _ in mailbox.sends] == reminded


def _assigned(client: CentrumClient, worker: dict[str, Any]) -> Any:
    """„Przypisz do Wykonawcy…” z widoku Raporty: adres ``NEW_ADDRESS`` u Wykonawcy ``worker``."""

    return client.post(f"/api/settings/workers/{worker['logins'][0]}/addresses", json={"address": NEW_ADDRESS})


def _edited(client: CentrumClient, worker: dict[str, Any]) -> Any:
    """Formularz Wykonawcy ``worker`` z jego loginami, nazwą i adresami, do których tata dopisał ``NEW_ADDRESS``."""

    form = {"logins": worker["logins"], "name": worker["name"], "addresses": [*worker["addresses"], NEW_ADDRESS]}
    return client.put(f"/api/settings/workers/{worker['logins'][0]}", json=form)


@pytest.mark.parametrize("change", [_assigned, _edited], ids=["przypisanie-adresu", "formularz"])
@pytest.mark.parametrize(
    ("active", "reminders"),
    [(False, True), (True, False), (False, False)],
    ids=["nieaktywny", "bez-przypomnien", "nieaktywny-bez-przypomnien"],
)
def test_dopisanie_adresu_przypisaniem_albo_formularzem_zostawia_reszte_wykonawcy_a_przypomnienia_go_omijaja(
    tmp_path: Path, change: Callable[[CentrumClient, dict[str, Any]], Any], active: bool, reminders: bool
) -> None:
    """ADR 0032 (D13), W1 #1650 r1: tata dopisuje Annie adres przyciskiem „Przypisz do Wykonawcy…” albo formularzem.
    Zmienia się tylko lista adresów: loginy (także drugi), nazwa, pierwsze adresy, Nieaktywny i Przypomnienia o raporcie
    zostają, więc następne sprawdzenie przypomnień dalej omija Annę, a Jan je dostaje."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    anna = WorkerEntry(["anna.kowalska", "anna.k2"], "Anna Kowalska", [ANNA, "anna.k2@przyklad.invalid"], active, reminders)
    listed = WorkerList.of([WorkerEntry(["jan.testowy"], "Jan Testowy", [JAN]), anna])
    assert isinstance(listed, WorkerList), listed
    write_worker_list(centrum.tool.worker_list, listed)
    before = _listed_worker(centrum.client, "anna.kowalska")
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    changed = change(centrum.client, before)
    after = _listed_worker(centrum.client, "anna.kowalska")
    centrum.rhythm.tick()
    centrum.client.stop()

    assert changed.status_code == 200, changed.json()
    assert after == {**before, "addresses": [*before["addresses"], NEW_ADDRESS]}
    assert (before["active"], before["reminders"]) == (active, reminders)
    assert [reminder.worker for reminder, _ in mailbox.sends] == ["jan.testowy"]


def _listed_worker(client: CentrumClient, login: str) -> dict[str, Any]:
    """Wykonawca z pierwszym loginem ``login`` z sekcji Wykonawcy w Ustawieniach."""

    [worker] = [worker for worker in client.get("/api/settings").json()["workers"]["workers"] if worker["logins"][0] == login]
    return dict(worker)


# Treść przypomnienia za 9.11 z pierwszym zdaniem i stopką „Pozdrawiam / Tata”, jakie Centrum wysyłało przed Ustawieniami
# (spec #1344), i ze wzorem Raportu wykonawcy z kodami czynności (ADR 0039).
TEXT_BEFORE_SETTINGS = """Poproszę o wysłanie raportu za dzień 09.11.2026.

Raport proszę wysłać według tego wzoru:
Temat maila: Raport 09.11.2026
Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód
PRZYKŁAD:
12345678 tak inst20m spawpg
12345679 nie brak klienta

Pozdrawiam
Tata
"""


@pytest.mark.parametrize(
    ("rollout", "footer", "text"),
    [
        (b"2026-11-09\n", b"Pozdrawiam\nTata\n", TEXT_BEFORE_SETTINGS),
        (
            b"\xef\xbb\xbf2026-11-09\r\n",
            b"\xef\xbb\xbfPozdrawiam\r\nTata\r\n",
            TEXT_BEFORE_SETTINGS.replace("Pozdrawiam\nTata", "Pozdrawiam\r\nTata"),
        ),
    ],
    ids=["lf", "crlf-z-notatnika"],
)
def test_po_aktualizacji_bez_zmian_przypomnienia_z_plikow_maksa_ida_te_same_co_przed_ustawieniami(
    tmp_path: Path, rollout: bytes, footer: bytes, text: str
) -> None:
    """Kryterium #1476: po Aktualizacji tata nic nie zmienia, a pierwszy start przenosi dzień wdrożenia i stopkę z plików
    Maksa do Ustawień, więc o 8:30 dnia po dniu zleceń idą te same przypomnienia co przed Wydaniem, z tym samym tematem,
    pierwszym zdaniem i stopką bajt w bajt (wzór Raportu wykonawcy ma kody czynności, ADR 0039), a druga minuta pory nie
    wysyła drugiego (ADR 0030, DESIGN §3). Stopka z Notatnika (BOM i CRLF) szła przed Wydaniem z CRLF między liniami i
    tak samo idzie po nim."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox, release_changes=RELEASE_CHANGES)
    (centrum.tool.config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\n{HASLO}\n", encoding="utf-8")
    (centrum.tool.config / OLD_ROLLOUT_FILE).write_bytes(rollout)
    (centrum.tool.config / OLD_FOOTER_FILE).write_bytes(footer)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    mailbox.sent = tuple(SentReminder(frozenset(reminder.recipients), reminder.day, at) for reminder, at in mailbox.sends)
    centrum.moment.append(datetime(2026, 11, 10, 8, 31))
    centrum.restart()
    centrum.client.start()
    centrum.rhythm.tick()
    centrum.client.stop()

    sent = [(reminder.worker, reminder.recipients, reminder.subject, reminder.text) for reminder, _ in mailbox.sends]
    assert sent == [
        (login, (SenderAddress(SENDERS[login]),), "Przypomnienie: raport za dzień 09.11.2026", text)
        for login in ("anna.kowalska", "jan.testowy")
    ]


def test_zmiana_pory_i_godziny_pierwszego_przypomnienia_dziala_od_nastepnego_sprawdzenia_bez_ponownego_startu(
    tmp_path: Path,
) -> None:
    """Kryterium #1476 (US 49): o 7:30 przypomnienia przy porach z ADR 0030 śpią; tata przesuwa poranną porę na 7:00 i
    następne sprawdzenie czyta skrzynkę, ale nic nie wysyła, bo pierwsze przypomnienie idzie od 8:00; tata przesuwa je na
    7:00 i następne sprawdzenie w tej samej porze wysyła przypomnienia, bez ponownego startu Centrum."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(datetime(2026, 11, 10, 7, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    asleep = list(mailbox.days)
    earlier = _reminders_form(morning={"start": "07:00", "end": "17:00"}, footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=earlier).status_code == 200
    for minute in (31, 32):
        centrum.moment.append(datetime(2026, 11, 10, 7, minute))
        centrum.rhythm.tick()
    read_before_first = (list(mailbox.days), list(mailbox.sends))
    assert centrum.client.put("/api/settings/reminders", json={**earlier, "first": "07:00"}).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 7, 33))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert asleep == []
    assert read_before_first == ([date(2026, 11, 9)], []), "pora otwarta raz, a 7:32 nie czyta drugi raz"
    assert [(reminder.worker, reminder.day, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", date(2026, 11, 9), time(7, 33)),
        ("jan.testowy", date(2026, 11, 9), time(7, 33)),
    ]


@dataclass
class SentFolderMailbox(FakeMailbox):
    """Skrzynka przypomnień, której „Wysłane” mają każde przypomnienie wysłane przez nią, z chwilą wysyłki według zegara
    Gmaila, który odchodzi od zegara laptopa taty o ``gmail_clock``."""

    gmail_clock: timedelta = timedelta()

    def sent_reminders(self, day: date) -> SentReminders | PasswordRejected | InboxUnreachable:
        return SentReminders(
            tuple(SentReminder(frozenset(reminder.recipients), reminder.day, at + self.gmail_clock) for reminder, at in self.sends)
        )


@pytest.mark.parametrize(
    ("sent_at", "later", "checked_at"),
    [
        (time(8, 5), {"morning": {"start": "09:00", "end": "17:00"}}, time(9, 1)),
        (time(18, 5), {"evening": {"start": "19:00", "end": "22:00"}}, time(19, 1)),
    ],
    ids=["poranna", "wieczorna"],
)
def test_przesuniecie_poczatku_pory_po_wysylce_nie_daje_drugiego_maila_tej_samej_pory(
    tmp_path: Path, sent_at: time, later: dict[str, object], checked_at: time
) -> None:
    """Decyzja W1 (#1568): przypomnienie wysłane w porze zamyka tę nazwaną porę na cały dzień, także gdy tata potem
    przesunie jej początek za chwilę wysyłki, więc następne sprawdzenie w nowej porze nie wysyła Wykonawcom drugiego."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(datetime.combine(date(2026, 11, 10), sent_at))
    centrum.client.start()
    centrum.rhythm.tick()
    first = [(reminder.worker, at.time()) for reminder, at in mailbox.sends]

    changed = centrum.client.put("/api/settings/reminders", json=_reminders_form(**later, footer="Pozdrawiam\nTata\n"))
    centrum.moment.append(datetime.combine(date(2026, 11, 10), checked_at))
    centrum.rhythm.tick()
    centrum.restart()
    centrum.client.start()
    centrum.moment.append(datetime.combine(date(2026, 11, 10), checked_at.replace(minute=30)))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert changed.status_code == 200
    assert first == [("anna.kowalska", sent_at), ("jan.testowy", sent_at)]
    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == first, "drugi mail tej samej pory"


def test_pory_bez_zmian_od_kilku_dni_dalej_chronia_poranna_wyslana_przed_ich_przesunieciem(tmp_path: Path) -> None:
    """Decyzja W1 (#1568): pory z ADR 0030 obowiązują od sprawdzenia 8.11; 10.11 o 8:05 idzie poranne przypomnienie, a
    tata przesuwa poranną na 9:00–17:00. Pory sprzed doby dalej mówią, że 8:05 była w porannej, więc o 9:01 drugiego
    porannego nie ma."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.client.start()
    for moment in (datetime(2026, 11, 8, 10, 0), datetime(2026, 11, 10, 8, 5)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    later = _reminders_form(morning={"start": "09:00", "end": "17:00"}, footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=later).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 9, 1))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", datetime(2026, 11, 10, 8, 5).astimezone()),
        ("jan.testowy", datetime(2026, 11, 10, 8, 5).astimezone()),
    ]


def test_pora_ktora_dzis_jeszcze_nie_poszla_po_zmianie_por_wysyla_przypomnienie_od_nastepnego_sprawdzenia(
    tmp_path: Path,
) -> None:
    """Decyzja W1 (#1568): o 13:00 przy porach z ADR 0030 idzie poranne przypomnienie; tata skraca poranną do 12:00 i
    zaczyna wieczorną o 12:30, więc 13:00 leży teraz w wieczornej, ale mail poszedł w porannej. Wieczorna dziś jeszcze
    nie poszła, więc następne sprawdzenie ją wysyła, a jeszcze następne nie wysyła drugiej."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(datetime(2026, 11, 10, 13, 0))
    centrum.client.start()
    centrum.rhythm.tick()
    later = _reminders_form(
        morning={"start": "08:00", "end": "12:00"}, evening={"start": "12:30", "end": "22:00"}, footer="Pozdrawiam\nTata\n"
    )
    assert centrum.client.put("/api/settings/reminders", json=later).status_code == 200
    for moment in (datetime(2026, 11, 10, 13, 30), datetime(2026, 11, 10, 13, 31), datetime(2026, 11, 10, 20, 0)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", time(13, 0)),
        ("jan.testowy", time(13, 0)),
        ("anna.kowalska", time(13, 30)),
        ("jan.testowy", time(13, 30)),
    ]


@pytest.mark.parametrize(("active", "reminders"), [(False, True), (True, False)], ids=["nieaktywny", "bez-przypomnien"])
def test_przypomnienia_ida_tylko_do_aktywnych_wykonawcow_z_wlaczonymi_przypomnieniami(
    tmp_path: Path, active: bool, reminders: bool
) -> None:
    """ADR 0032: Nieaktywny Wykonawca i Wykonawca z wyłączonymi przypomnieniami zostają na Liście Wykonawców z adresem,
    ale Przypomnienia o raporcie dostaje tylko aktywny z włączonymi (przegląd #1568 r4); Jan ma zlecenia dnia tak samo
    jak Anna."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    listed = WorkerList.of(
        [
            WorkerEntry(["jan.testowy"], WORKERS["jan.testowy"], [JAN], active=active, reminders=reminders),
            WorkerEntry(["anna.kowalska"], WORKERS["anna.kowalska"], [ANNA]),
        ]
    )
    assert isinstance(listed, WorkerList), listed
    write_worker_list(centrum.tool.worker_list, listed)
    centrum.moment.append(datetime(2026, 11, 10, 8, 30))
    centrum.client.start()
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska"]


def _old_version_sends(tmp_path: Path, at: datetime) -> list[tuple[Reminder, datetime]]:
    """Przypomnienia, które stara wersja (stałe pory z ADR 0030) wysłała o ``at`` do Anny i Jana, jak w jej „Wysłanych”."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(at)
    centrum.client.start()
    centrum.rhythm.tick()
    centrum.client.stop()
    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]
    return list(mailbox.sends)


@pytest.mark.parametrize(
    ("sent_at", "updated_at", "later", "checked_at"),
    [
        (time(8, 5), time(17, 20), {"morning": {"start": "09:00", "end": "17:45"}}, time(17, 21)),
        (time(18, 5), time(22, 10), {"evening": {"start": "19:00", "end": "23:00"}}, time(22, 11)),
    ],
    ids=["poranna", "wieczorna"],
)
def test_w_dniu_aktualizacji_zmiana_por_po_wysylce_starej_wersji_nie_daje_drugiego_maila_tej_samej_pory(
    tmp_path: Path, sent_at: time, updated_at: time, later: dict[str, object], checked_at: time
) -> None:
    """Sonda W1 r2 (#1568): stara wersja wysłała przypomnienia przy stałych porach z ADR 0030, a pór z chwili wysyłki nie
    zapisała. Centrum po Aktualizacji startuje poza porą, tata zmienia w Ustawieniach porę tak, że chwila wysyłki leży
    już poza nią, a następne sprawdzenie w nowej porze nie wysyła drugiego, bo stara wersja znała tylko pory z ADR 0030."""

    day = date(2026, 11, 10)
    mailbox = SentFolderMailbox(sends=_old_version_sends(tmp_path / "stara", datetime.combine(day, sent_at)))
    centrum = entering_centrum(tmp_path / "nowa", INTERMAX, reminder_mailbox=mailbox, release_changes=RELEASE_CHANGES)
    (centrum.tool.config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\n{HASLO}\n", encoding="utf-8")
    (centrum.tool.config / OLD_ROLLOUT_FILE).write_bytes(b"2026-11-09\n")
    (centrum.tool.config / OLD_FOOTER_FILE).write_bytes(b"Pozdrawiam\nTata\n")
    centrum.moment.append(datetime.combine(day, updated_at))
    centrum.client.start()
    centrum.rhythm.tick()
    changed = centrum.client.put("/api/settings/reminders", json=_reminders_form(**later, footer="Pozdrawiam\nTata\n"))
    centrum.moment.append(datetime.combine(day, checked_at))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert changed.status_code == 200
    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", sent_at),
        ("jan.testowy", sent_at),
    ], "drugi mail tej samej pory w dniu Aktualizacji"


def test_zegar_gmaila_spozniony_o_poltorej_minuty_nie_przenosi_wysylki_na_pory_sprzed_zmiany(tmp_path: Path) -> None:
    """Zapas zegara (``CLOCK_MARGIN``): o 7:30 praca sprawdza przy porannej 7:00–9:00, tata wydłuża ją do 17:00, a
    sprawdzenie o 9:30 wysyła przypomnienia. Zegar Gmaila spóźnia się o półtorej minuty, więc „Wysłane” mają 9:28:30,
    jeszcze przed zapisem nowych pór. Po ponownym starcie o 9:35 te maile dalej zamykają poranną, choć przy porach sprzed
    zmiany 9:28:30 leży poza porą."""

    mailbox = SentFolderMailbox(gmail_clock=-timedelta(seconds=90))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    short = _reminders_form(morning={"start": "07:00", "end": "09:00"}, footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=short).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 7, 30))
    centrum.client.start()
    centrum.rhythm.tick()
    longer = _reminders_form(morning={"start": "07:00", "end": "17:00"}, footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=longer).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 9, 30))
    centrum.rhythm.tick()
    centrum.restart()
    centrum.client.start()
    centrum.moment.append(datetime(2026, 11, 10, 9, 35))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", time(9, 30)),
        ("jan.testowy", time(9, 30)),
    ]


def test_zegar_gmaila_spieszacy_sie_o_poltorej_minuty_nie_gubi_por_sprzed_zmiany(tmp_path: Path) -> None:
    """Zapas zegara (``CLOCK_MARGIN``) w drugą stronę (przegląd #1568 r3, D1): przy porannej 8:00–9:00 i wieczornej
    9:00–22:00 przypomnienia idą o 8:30 i o 9:29 (wieczorna). Tata przesuwa granicę pór na 9:40, sprawdzenie o 9:30
    zapisuje nowe pory, a zegar Gmaila spieszy się o półtorej minuty, więc „Wysłane” mają 9:30:30, już po zapisie
    nowych pór, w których to poranna. Te maile dalej zamykają wieczorną przy porach sprzed zmiany, więc sprawdzenie
    o 9:45 w nowej wieczornej nie wysyła drugiego."""

    mailbox = SentFolderMailbox(gmail_clock=timedelta(seconds=90))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    early = _reminders_form(
        morning={"start": "08:00", "end": "09:00"}, evening={"start": "09:00", "end": "22:00"}, footer="Pozdrawiam\nTata\n"
    )
    assert centrum.client.put("/api/settings/reminders", json=early).status_code == 200
    centrum.client.start()
    for moment in (datetime(2026, 11, 10, 8, 30), datetime(2026, 11, 10, 9, 29)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    later = _reminders_form(
        morning={"start": "08:00", "end": "09:40"}, evening={"start": "09:40", "end": "22:00"}, footer="Pozdrawiam\nTata\n"
    )
    assert centrum.client.put("/api/settings/reminders", json=later).status_code == 200
    for moment in (datetime(2026, 11, 10, 9, 30), datetime(2026, 11, 10, 9, 45)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", time(8, 30)),
        ("jan.testowy", time(8, 30)),
        ("anna.kowalska", time(9, 29)),
        ("jan.testowy", time(9, 29)),
    ], "drugi mail wieczornej"


_NAIVE_SCHEDULES = b"""{"schema_version": 1,
 "przed": [{"poranna": {"od": "08:00", "do": "17:00"}, "wieczorna": {"od": "18:00", "do": "22:00"}, "pierwsze": "08:00"}],
 "pory": [{"od": "2026-11-10T07:00:00", "poranna": {"od": "08:00", "do": "17:00"},
  "wieczorna": {"od": "18:00", "do": "22:00"}, "pierwsze": "08:00"}]}
"""


@pytest.mark.parametrize(
    "broken",
    [b"{", b'{"schema_version": 1, "przed": [], "pory": []}\n', _NAIVE_SCHEDULES],
    ids=["urwany", "bez-por-przed", "chwila-bez-strefy"],
)
def test_nieczytelny_plik_por_liczy_wyslane_takze_przy_biezacych_porach_az_po_nastepny_start(
    tmp_path: Path, broken: bytes
) -> None:
    """Przy porannej 6:00–17:00 przypomnienia idą o 7:00, poza porami z ADR 0030. Plik pór psuje się, a Centrum
    startuje znowu o 7:30 i o 7:45: nie wiadomo, przy jakich porach ta wersja wysyłała, więc maile z 7:00 zamykają
    poranną przy porach z ADR 0030 i przy bieżących, także po starcie, przed którym praca zapisała plik od nowa."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    early = _reminders_form(morning={"start": "06:00", "end": "17:00"}, first="06:00", footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=early).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 7, 0))
    centrum.client.start()
    centrum.rhythm.tick()
    centrum.client.stop()
    (centrum.tool.config / REMINDERS_SCHEDULES).write_bytes(broken)
    for minute in (30, 45):
        centrum.restart()
        centrum.client.start()
        centrum.moment.append(datetime(2026, 11, 10, 7, minute))
        centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", time(7, 0)),
        ("jan.testowy", time(7, 0)),
    ]


_HALF_HOURS = st.lists(st.integers(6 * 2, 23 * 2 + 1), min_size=4, max_size=4, unique=True).map(sorted)
"""Cztery różne pełne albo połówkowe godziny od 6:00 do 23:30, rosnąco: początek i koniec porannej i wieczornej."""


@st.composite
def _pory(draw: st.DrawFn) -> tuple[tuple[time, time], tuple[time, time]]:
    """Dobre pory z formularza: poranna przed wieczorną, czasem stykające się (koniec porannej = początek wieczornej)."""

    found = [time(half // 2, 30 * (half % 2)) for half in draw(_HALF_HOURS)]
    if draw(st.booleans()):
        found[2] = found[1]
    return (found[0], found[1]), (found[2], found[3])


def test_nieudany_zapis_por_wstrzymuje_wysylke_az_do_zapisu_wiec_ponowny_start_nie_daje_drugiego_maila(
    tmp_path: Path,
) -> None:
    """Przy porannej 6:00–17:00 sprawdzenie o 7:00 nie zapisuje pór (plik tymczasowy zajęty), więc nie wysyła: po
    ponownym starcie bez pliku pór mail z 7:00 liczyłby się przy porach z ADR 0030, poza porą. Po zwolnieniu pliku
    następna minuta zapisuje pory i wysyła, a Centrum po ponownym starcie nie wysyła drugiego."""

    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    early = _reminders_form(morning={"start": "06:00", "end": "17:00"}, first="06:00", footer="Pozdrawiam\nTata\n")
    assert centrum.client.put("/api/settings/reminders", json=early).status_code == 200
    busy = centrum.tool.config / f"{REMINDERS_SCHEDULES}.tmp"
    busy.mkdir()
    centrum.client.start()
    centrum.moment.append(datetime(2026, 11, 10, 7, 0))
    centrum.rhythm.tick()
    blocked = (list(mailbox.sends), _reminder_result(centrum)["failure"])
    busy.rmdir()
    for minute in (1, 30):
        centrum.moment.append(datetime(2026, 11, 10, 7, minute))
        centrum.rhythm.tick()
        centrum.restart()
        centrum.client.start()
    centrum.client.stop()

    assert blocked == ([], "zapis-por")
    assert [(reminder.worker, at.time()) for reminder, at in mailbox.sends] == [
        ("anna.kowalska", time(7, 1)),
        ("jan.testowy", time(7, 1)),
    ]
    assert centrum.tool.log_path.read_text(encoding="utf-8").count("przypomnienia-porazka przyczyna=zapis-por") == 1


_FIRST_MINUTE, _LAST_MINUTE = 7 * 60, 23 * 60 + 58
_DAY_MINUTES = st.integers(_FIRST_MINUTE, _LAST_MINUTE)
_EVENTS = st.lists(
    st.tuples(_DAY_MINUTES, st.one_of(_pory(), st.just("sprawdzenie"), st.just("restart"))), min_size=1, max_size=12
)
"""Zdarzenia dnia 10.11.2026 po minutach: tata zapisuje pory, rytm sprawdza przypomnienia albo Centrum startuje znowu.
Po każdej zmianie pór i każdym starcie rytm sprawdza w następnej minucie, jak u taty. W dniu Aktualizacji test
ściska minuty zdarzeń za chwilę wysyłki starej wersji."""
_ADR_0030_PORY_MINUTE = st.one_of(st.integers(8 * 60, 17 * 60 - 1), st.integers(18 * 60, 22 * 60 - 1))
_OLD_VERSION_SENDING_MINUTE_BY_DAY = {"bez-aktualizacji": st.none(), "dzien-aktualizacji": _ADR_0030_PORY_MINUTE}


# Bez zmniejszania przykładu: każdy próbowany przykład to nowe Centrum, więc zmniejszanie złego przykładu trwa dłużej
# niż limit testu, a przykład z najwyżej 12 zdarzeniami czyta się i bez niego.
@pytest.mark.parametrize(
    "old_version_sending_minutes",
    list(_OLD_VERSION_SENDING_MINUTE_BY_DAY.values()),
    ids=list(_OLD_VERSION_SENDING_MINUTE_BY_DAY),
)
@settings(
    derandomize=True,
    database=None,
    deadline=None,
    max_examples=30,
    phases=[Phase.explicit, Phase.generate],
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data(), events=_EVENTS)
def test_wlasnosc_zadna_zmiana_por_w_ciagu_dnia_nie_daje_wykonawcy_dwoch_maili_tej_samej_pory(
    tmp_path_factory: pytest.TempPathFactory,
    old_version_sending_minutes: st.SearchStrategy[int | None],
    data: st.DataObject,
    events: list[tuple[int, object]],
) -> None:
    """Decyzja W1 (#1568): przy dowolnych zmianach pór w ciągu dnia, sprawdzeniach i ponownych startach Centrum każde
    przypomnienie idzie w porze obowiązującej w chwili jego sprawdzenia, a Wykonawca dostaje za dzień raportu najwyżej
    jedno przypomnienie w każdej nazwanej porze (porannej, wieczornej) tego dnia, także w dniu Aktualizacji, gdy
    „Wysłane” mają już przypomnienia starej wersji, a pliku pór jeszcze nie ma (W1 r2)."""

    old_version = data.draw(old_version_sending_minutes)
    mailbox = SentFolderMailbox()
    centrum = entering_centrum(tmp_path_factory.mktemp("pory"), INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    day = date(2026, 11, 10)
    in_effect: tuple[tuple[time, time], tuple[time, time]] = ((time(8), time(17)), (time(18), time(22)))
    named: list[tuple[str, str]] = []
    if old_version is not None:
        old_moment = time(old_version // 60, old_version % 60)
        centrum.moment.append(datetime.combine(day, old_moment))
        centrum.client.start()
        centrum.rhythm.tick()
        centrum.client.stop()
        (centrum.tool.config / REMINDERS_SCHEDULES).unlink()
        named += [(reminder.worker, _named_pora(old_moment, in_effect)) for reminder, _ in mailbox.sends]
        centrum.restart()
    first = _FIRST_MINUTE if old_version is None else old_version + 1
    moments: list[tuple[int, object]] = []
    for minute, event in sorted(events, key=lambda found: found[0]):
        at = first + (minute - _FIRST_MINUTE) * (_LAST_MINUTE - first) // (_LAST_MINUTE - _FIRST_MINUTE)
        moments += [(at, event)] if event == "sprawdzenie" else [(at, event), (at + 1, "sprawdzenie")]
    moments.sort(key=lambda found: found[0])
    centrum.client.start()
    try:
        for minute, event in moments:
            moment = datetime.combine(day, time(minute // 60, minute % 60))
            if event == "restart":
                centrum.restart()
                centrum.client.start()
            elif event == "sprawdzenie":
                centrum.moment.append(moment)
                before = len(mailbox.sends)
                centrum.rhythm.tick()
                pora = _named_pora(moment.time(), in_effect)
                named += [(reminder.worker, pora) for reminder, _ in mailbox.sends[before:]]
            else:
                assert isinstance(event, tuple)
                (morning_start, morning_end), (evening_start, evening_end) = in_effect = event
                form = _reminders_form(
                    morning={"start": f"{morning_start:%H:%M}", "end": f"{morning_end:%H:%M}"},
                    evening={"start": f"{evening_start:%H:%M}", "end": f"{evening_end:%H:%M}"},
                    footer="Pozdrawiam\nTata\n",
                )
                assert centrum.client.put("/api/settings/reminders", json=form).status_code == 200
    finally:
        centrum.client.stop()

    assert "poza porą" not in {pora for _, pora in named}, named
    assert len(named) == len(set(named)), f"dwa maile tej samej pory: {named}"


def _named_pora(moment: time, pory: tuple[tuple[time, time], tuple[time, time]]) -> str:
    """Nazwana pora chwili przy porach ``pory`` (od początku do końca, bez końca), wprost z ADR 0030."""

    (morning_start, morning_end), (evening_start, evening_end) = pory
    if morning_start <= moment < morning_end:
        return "poranna"
    return "wieczorna" if evening_start <= moment < evening_end else "poza porą"


def test_podglad_przypomnienia_pokazuje_temat_tresc_i_stopke_z_formularza_bez_zapisu_i_bez_wysylki(tmp_path: Path) -> None:
    """Kryterium #1476 (US 47–48): podgląd na przykładowy dzień (wczoraj taty) pokazuje stały temat, pierwsze zdanie
    taty z dniem, stały wzór Raportu wykonawcy i stopkę z formularza, a niczego nie zapisuje i nie wysyła."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    before = config_files(centrum.tool.config)
    form = _reminders_form(text="Dzień dobry, czekam na raport za {dzień}.", footer="Pozdrawiam\nTata Testowy\n")

    preview = centrum.client.post("/api/settings/reminders/preview", json=form)

    assert preview.status_code == 200
    assert preview.json() == {
        "subject": "Przypomnienie: raport za dzień 08.11.2026",
        "text": (
            "Dzień dobry, czekam na raport za 08.11.2026.\n\nRaport proszę wysłać według tego wzoru:\n"
            "Temat maila: Raport 08.11.2026\n"
            "Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód\nPRZYKŁAD:\n"
            "12345678 tak inst20m spawpg\n12345679 nie brak klienta\n\nPozdrawiam\nTata Testowy\n"
        ),
    }
    assert (config_files(centrum.tool.config), mailbox.sends) == (before, [])


def config_files(config: Path) -> dict[str, bytes]:
    return {path.relative_to(config).as_posix(): path.read_bytes() for path in sorted(config.rglob("*")) if path.is_file()}


def test_wylaczone_przypomnienia_nic_nie_wysylaja_a_wlaczone_w_nocy_i_przed_8_dnia_nastepnego_tez_nie(tmp_path: Path) -> None:
    """Wyłączone w Ustawieniach przypomnienia nie czytają skrzynki, nic nie wysyłają i nie zostawiają śladu; po włączeniu
    przełącznikiem w dniu zleceń Centrum czyta skrzynkę raz w porze, ale za ten dzień nic nie wysyła, a w nocy i przed
    8:00 dnia następnego nawet nie czyta (US 32–33, 40–41)."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    assert centrum.client.put("/api/settings/reminders/enabled", json={"enabled": False}).status_code == 200
    centrum.moment.append(datetime(2026, 11, 9, 21, 0))
    centrum.client.start()

    centrum.rhythm.tick()
    assert mailbox.days == [], "wyłączone przypomnienia nie czytają skrzynki"
    assert not (centrum.tool.config / REMINDERS_RESULT).exists(), "wyłączone przypomnienia nie piszą do config"
    switched = centrum.client.put("/api/settings/reminders/enabled", json={"enabled": True})
    for moment in (datetime(2026, 11, 9, 21, 1), datetime(2026, 11, 9, 21, 2), datetime(2026, 11, 9, 23, 0), datetime(2026, 11, 10, 7, 59)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    centrum.client.stop()

    assert (switched.status_code, switched.json()["settings"]["reminders"]["since"]) == (200, "2026-11-09")
    assert (mailbox.days, mailbox.sends) == ([date(2026, 11, 9)], [])
    log = centrum.tool.log_path.read_text(encoding="utf-8") if centrum.tool.log_path.exists() else ""
    assert "przypomnienia-porazka" not in log, "wyłączone przypomnienia są wyłączone, nie zepsute"


def test_brak_sieci_przy_przypomnieniach_ponawia_w_nastepnej_minucie_tej_samej_pory_bez_zgloszenia(tmp_path: Path) -> None:
    """Brak sieci przy przypomnieniach to tylko ponowienie w następnej minucie tej samej pory: bez Zgłoszenia, a
    porażka raz w Logach Centrum (US 47)."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    mailbox = FakeMailbox(sent=InboxUnreachable("TimeoutError"))
    centrum = entering_centrum(tmp_path, INTERMAX, surroundings=surroundings, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
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

    anna_report = report(ANNA, "Raport 09.11.2026", "40000002 tak spawpg")
    mailbox = FakeMailbox(outcome=InboxUnreachable("TimeoutError"))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
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
    _reminders_set_up(centrum)
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
        (datetime(2026, 11, 10, 16, 59), datetime(2026, 11, 10, 17, 0)),
        (datetime(2026, 11, 10, 21, 59), datetime(2026, 11, 11, 7, 0)),
        (datetime(2026, 11, 10, 21, 59), datetime(2026, 11, 11, 21, 0)),
    ],
    ids=["22-00", "poranna-do-17", "uspiony-do-rana", "uspiony-do-wieczora-innego-dnia"],
)
def test_seria_przypomnien_ktora_wyszla_poza_pore_czeka_z_reszta_na_nastepna_pore(
    tmp_path: Path, started: datetime, later: datetime
) -> None:
    """Gdy zegar w trakcie serii przypomnień wyjdzie poza porę, w której seria ruszyła (minęła 22:00 albo 17:00, laptop
    zasnął i obudził się rano albo wieczorem innego dnia), reszta serii nie idzie, a wysłane przypomnienie ma chwilę
    swojej wysyłki, nie początku sprawdzenia, w mailu i w wyniku dla widoku Raporty (ADR 0030 „nigdy w nocy”)."""

    class TickingMailbox(FakeMailbox):
        def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
            outcome = super().send(reminder, at)
            centrum.moment.append(later)
            return outcome

    first_send = started + timedelta(seconds=30)
    mailbox = TickingMailbox(during=lambda: centrum.moment.append(first_send))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(started)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at) for reminder, at in mailbox.sends] == [("anna.kowalska", first_send.astimezone())]
    assert [
        (sent["worker"], sent["day"], datetime.fromisoformat(sent["sent_at"])) for sent in _reminder_result(centrum)["sent"]
    ] == [("anna.kowalska", "2026-11-09", first_send.astimezone())]



def test_seria_porannych_przypomnien_przerwana_o_17_reszta_idzie_dopiero_o_18_bez_duplikatu(tmp_path: Path) -> None:
    """Seria porannych przypomnień zaczęta o 16:59 staje o 17:00: reszta nie idzie ani wtedy, ani w sprawdzeniu o 17:30,
    tylko o 18:00 jako wieczorne, po jednym do każdego Wykonawcy, a minuta później żadne (decyzja Maksa 12.11, ADR
    0030: poranne przypomnienie nie nadrabia się od 17:00)."""

    started, first_send = datetime(2026, 11, 10, 16, 59), datetime(2026, 11, 10, 16, 59, 30)
    evening = datetime(2026, 11, 10, 18, 0)

    class FirstSendPastFive(FakeMailbox):
        def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
            outcome = super().send(reminder, at)
            if len(self.sends) == 1:
                centrum.moment.append(datetime(2026, 11, 10, 17, 0))
            return outcome

    mailbox = FirstSendPastFive(during=lambda: centrum.moment.append(first_send) if not mailbox.sends else None)
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(started)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 17, 30))
    centrum.rhythm.tick()
    after_five = list(mailbox.sends)
    centrum.moment.append(evening)
    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 18, 1))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, at) for reminder, at in after_five] == [("anna.kowalska", first_send.astimezone())]
    assert [(reminder.worker, at) for reminder, at in mailbox.sends[1:]] == [
        ("anna.kowalska", evening.astimezone()),
        ("jan.testowy", evening.astimezone()),
    ]


def _shown_sent(centrum: EnteringCentrum) -> list[tuple[str, str, datetime]]:
    """Wysłane przypomnienia z pliku wyniku, który czyta widok Raporty: Wykonawca, dzień i chwila wysłania."""

    return [
        (sent["worker"], sent["day"], datetime.fromisoformat(sent["sent_at"])) for sent in _reminder_result(centrum)["sent"]
    ]


def _filed_at(mailbox: FakeMailbox) -> list[datetime]:
    """Chwile przypomnień, które Gmail atrapy położył już w „Wysłanych”."""

    assert isinstance(mailbox.sent, tuple), mailbox.sent
    return [found.sent_at for found in mailbox.sent]


def test_przypomnienie_wyslane_przed_brakiem_sieci_nie_idzie_drugi_raz_zanim_gmail_polozy_je_w_wyslanych(
    tmp_path: Path,
) -> None:
    """Sprawdzenie wysyła przypomnienie Annie, a przy Janie sieć znika, więc pora zostaje otwarta. Następna minuta tej
    samej pory wysyła tylko Janowi, choć Gmail jeszcze nie położył przypomnienia Anny w „Wysłanych”: maile wysłane w
    tej pracy Centrum praca pamięta sama (ADR 0030 „Najwyżej jedno w każdej porze”), a widok Raporty pokazuje oba
    przypomnienia do końca pory. O 18:00 Gmail położył już tylko przypomnienie Anny, a widok pokazuje każde poranne
    raz: przypomnienia Jana z 8:31 nie zakrywa przypomnienie Anny z „Wysłanych” wysłane minutę wcześniej."""

    class NetworkGoneAtJan(FakeMailbox):
        def send(self, reminder: Reminder, at: datetime) -> MailSent | PasswordRejected | InboxUnreachable | MailRefused:
            self.send_outcome = InboxUnreachable("TimeoutError") if len(self.sends) == 1 else MailSent()
            return super().send(reminder, at)

    mailbox = NetworkGoneAtJan(filed_after=1)
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()
    anna, jan = REMINDER_MORNING.astimezone(), (REMINDER_MORNING + timedelta(minutes=1)).astimezone()
    evening = datetime(2026, 11, 10, 18, 0)

    centrum.rhythm.tick()
    centrum.moment.append(REMINDER_MORNING + timedelta(minutes=1))
    centrum.rhythm.tick()
    centrum.moment.append(REMINDER_MORNING + timedelta(minutes=29))
    centrum.rhythm.tick()
    morning_view = _shown_sent(centrum)
    morning_sends = [reminder.worker for reminder, _ in mailbox.sends]
    centrum.moment.append(evening)
    centrum.rhythm.tick()
    centrum.client.stop()

    assert morning_sends == ["anna.kowalska", "jan.testowy", "jan.testowy"]
    assert morning_view == [("anna.kowalska", "2026-11-09", anna), ("jan.testowy", "2026-11-09", jan)]
    assert _filed_at(mailbox) == [anna]
    assert _shown_sent(centrum) == [
        ("anna.kowalska", "2026-11-09", anna),
        ("anna.kowalska", "2026-11-09", evening.astimezone()),
        ("jan.testowy", "2026-11-09", jan),
        ("jan.testowy", "2026-11-09", evening.astimezone()),
    ]


def _pora_changed_twice(centrum: EnteringCentrum) -> list[tuple[str, str, datetime]]:
    """Sprawdzenie o 8:30 wysyła poranne przypomnienia, a tata dwa razy zmienia poranną porę, każda zmiana minutę
    później (#1568). Wynik: widok Raporty po pierwszej zmianie; ten po drugiej zostaje w pliku wyniku."""

    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()
    centrum.rhythm.tick()

    def change(minute: int, end: str) -> None:
        form = _reminders_form(morning={"start": "08:00", "end": end}, footer="Pozdrawiam\nTata\n")
        assert centrum.client.put("/api/settings/reminders", json=form).status_code == 200
        centrum.moment.append(REMINDER_MORNING + timedelta(minutes=minute))
        centrum.rhythm.tick()

    change(1, "12:00")
    shown = _shown_sent(centrum)
    change(2, "13:00")
    centrum.client.stop()
    return shown


def test_zmiana_por_tuz_po_wysylce_widok_raporty_pokazuje_przypomnienia_zanim_gmail_je_polozy_i_po_tym_kazde_raz(
    tmp_path: Path,
) -> None:
    """Tata zmienia poranną porę minutę po wysyłce, zanim Gmail położy przypomnienia w „Wysłanych”: nowe sprawdzenie
    nie wysyła ich drugi raz, a widok Raporty dalej je pokazuje. Po drugiej zmianie Gmail już je położył, a widok
    pokazuje każde raz, bo mail z „Wysłanych” i z pamięci tej pracy to ten sam mail."""

    mailbox = FakeMailbox(filed_after=1)
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)

    before_filed = _pora_changed_twice(centrum)

    morning = REMINDER_MORNING.astimezone()
    assert [reminder.worker for reminder, _ in mailbox.sends] == ["anna.kowalska", "jan.testowy"]
    assert before_filed == [("anna.kowalska", "2026-11-09", morning), ("jan.testowy", "2026-11-09", morning)]
    assert _filed_at(mailbox) == [morning, morning]
    assert _shown_sent(centrum) == before_filed


def test_wieczorem_po_polozeniu_przez_gmaila_widok_pokazuje_raz_poranne_wykonawcy_z_dwoma_adresami_z_wolnej_serii(
    tmp_path: Path,
) -> None:
    """Anna ma dwa adresy, a odczyt skrzynki w sprawdzeniu z 8:30 trwa do 8:34, więc poranne przypomnienia idą o 8:34,
    dalej niż ``CLOCK_MARGIN`` od początku sprawdzenia. Wieczorem Gmail położył je już w „Wysłanych”, a widok Raporty
    pokazuje każde poranne raz: mail z pamięci tej pracy ma tych samych adresatów i chwilę wysyłki co mail z
    „Wysłanych”, więc to ten sam mail."""

    sent_at = datetime(2026, 11, 10, 8, 34)
    mailbox = FakeMailbox(filed_after=0, during=lambda: centrum.moment.append(sent_at) if not mailbox.sends else None)
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    assert _assign(centrum, "anna.kowalska", "anna.druga@przyklad.invalid").status_code == 200
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()
    evening = datetime(2026, 11, 10, 18, 0)

    centrum.rhythm.tick()
    centrum.moment.append(evening)
    centrum.rhythm.tick()
    centrum.client.stop()

    morning = sent_at.astimezone()
    assert [(reminder.worker, len(reminder.recipients), at) for reminder, at in mailbox.sends[:2]] == [
        ("anna.kowalska", 2, morning),
        ("jan.testowy", 1, morning),
    ]
    assert _filed_at(mailbox) == [morning, morning]
    assert _shown_sent(centrum) == [
        ("anna.kowalska", "2026-11-09", morning),
        ("anna.kowalska", "2026-11-09", evening.astimezone()),
        ("jan.testowy", "2026-11-09", morning),
        ("jan.testowy", "2026-11-09", evening.astimezone()),
    ]


def test_odrzucone_haslo_przy_przypomnieniach_daje_zgloszenie_do_maksa_raz_w_porze(tmp_path: Path) -> None:
    """Odrzucone hasło aplikacji przy wysyłce przypomnienia Centrum zgłasza Maksowi samo, bez taty, i do końca pory
    nie pyta Gmaila znowu (US 47)."""

    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings()
    mailbox = FakeMailbox(send_outcome=PasswordRejected())
    centrum = entering_centrum(tmp_path, INTERMAX, surroundings=surroundings, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
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
    assert _failures_in_log(centrum) == ["przyczyna=haslo-odrzucone"]


def test_zgloszenie_przypomnien_z_narzedzia_bez_commitu_gita_ma_commit_nieznany(tmp_path: Path) -> None:
    write_report_key(ToolDirectory(tmp_path))
    surroundings = Surroundings(github=FakeGitHub(tool_commit=None))
    mailbox = FakeMailbox(send_outcome=PasswordRejected())
    centrum = entering_centrum(tmp_path, INTERMAX, surroundings=surroundings, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    box = surroundings.report_box
    assert box.wait_until(lambda fake: len(fake.sent) == 1)
    centrum.client.stop()

    [issue] = box.sent
    body = issue.body.splitlines()
    assert body[body.index("## Narzędzie") + 2] == "- Commit: nieznany"


def _failures_in_log(centrum: EnteringCentrum) -> list[str]:
    """Pola każdej linii ``przypomnienia-porazka`` dziennika Centrum po nazwie zdarzenia, po kolei."""

    log = centrum.tool.log_path.read_text(encoding="utf-8") if centrum.tool.log_path.exists() else ""
    return [line.split(" przypomnienia-porazka ", 1)[1] for line in log.splitlines() if " przypomnienia-porazka " in line]


@pytest.mark.parametrize(
    ("cause", "broken"),
    [
        pytest.param("bez-ustawien", "ustawienia", id="bez-ustawien"),
        pytest.param("bez-dostepu", "dostep", id="bez-dostepu"),
        pytest.param("pamiec-wpisania", "pamiec", id="pamiec-wpisania"),
        pytest.param("pamiec-wpisania", "decyzje", id="decyzje-zostaw-moja"),
        pytest.param("okresy", "okresy", id="okresy"),
        pytest.param("intermax", "intermax", id="intermax"),
        pytest.param("intermax", "arkusz-zlecen", id="intermax-bez-arkusza-zlecen"),
    ],
)
def test_porazka_odczytu_przypomnien_trafia_raz_do_dziennika_centrum_i_do_wyniku(
    tmp_path: Path, cause: str, broken: str
) -> None:
    """Każda porażka sprawdzenia z dniem wdrożenia, które nie doszło do skrzynki (bez INTERMAX w Ustawieniach taty, bez
    pliku dostępu, nieczytelna pamięć Wpisania raportów albo decyzje „Zostaw moją”, bo pusta pamięć zmieniłaby dzień
    raportu, bez folderu okresów, nieczytelny INTERMAX albo INTERMAX bez arkusza zleceń), trafia do dziennika Centrum raz, bez
    adresów, a wynik dla widoku Raporty ją nazywa; wyjątkiem jest tylko brak dnia wdrożenia, przy którym przypomnienia
    są wyłączone (ADR 0030, przegląd #1372 r1 Drobne 1)."""

    mailbox = FakeMailbox(state="missing" if broken == "dostep" else "ready")
    centrum = entering_centrum(tmp_path, INTERMAX, chosen=broken != "ustawienia", reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    if broken == "okresy":
        shutil.rmtree(centrum.periods_directory)
    if broken == "intermax":
        centrum.register.write_bytes(b"to nie jest skoroszyt")
    if broken == "arkusz-zlecen":
        book = load_workbook(centrum.register)
        for header in book[ORDER_SHEET][1]:
            header.value = None
        book.save(centrum.register)
    if broken == "pamiec":
        _state(centrum).write_text("{", encoding="utf-8")
    if broken == "decyzje":
        (centrum.tool.config / REPORT_ENTERING_DECISIONS).write_text("{", encoding="utf-8")
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 8, 31))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert mailbox.sends == []
    assert [failure.split(" typ=")[0] for failure in _failures_in_log(centrum)] == [f"przyczyna={cause}"]
    assert _reminder_result(centrum)["failure"] == cause
    log = centrum.tool.log_path.read_text(encoding="utf-8")
    for secret in (JAN, ANNA, SKRZYNKA, HASLO):
        assert secret not in log, secret


@pytest.mark.parametrize("file", [SETTINGS_FILE, REMINDERS_FILE, WORKERS_FILE])
@pytest.mark.parametrize("back", [True, False], ids=["wraca-w-porze", "nie-wraca-do-konca-pory"])
def test_plik_ustawien_bez_odczytu_ponawia_w_tej_samej_porze_a_po_porze_zostawia_wpis_z_nazwa_pliku(
    tmp_path: Path, file: str, back: bool
) -> None:
    """Decyzja 4A Maksa: plik Przypomnień, Folderów albo Listy Wykonawców, którego system nie daje teraz czytać (np.
    trzyma go OneDrive), to nie wyłączone przypomnienia, niewskazany INTERMAX ani Wykonawcy bez adresów. Następna minuta tej samej pory próbuje znowu, więc plik,
    który wraca w porze, daje przypomnienia bez wpisu w dzienniku Centrum; plik, który nie wraca do końca pory, nie daje
    żadnego maila, a pierwsze sprawdzenie po porze zostawia w dzienniku Centrum jeden wpis z nazwą tego pliku."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.client.start()

    with without_reading(centrum.tool.config / file):
        for moment in (REMINDER_MORNING, datetime(2026, 11, 10, 8, 31)):
            centrum.moment.append(moment)
            centrum.rhythm.tick()
        unread = (list(mailbox.sends), _failures_in_log(centrum))
        if not back:
            centrum.moment.append(datetime(2026, 11, 10, 16, 59))
            centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 8, 32) if back else datetime(2026, 11, 10, 17, 1))
    centrum.rhythm.tick()
    centrum.client.stop()

    assert unread == ([], []), "w porze plik bez odczytu tylko czeka na następną minutę"
    reminded = sorted(reminder.worker for reminder, _ in mailbox.sends)
    if back:
        assert (reminded, _failures_in_log(centrum)) == (["anna.kowalska", "jan.testowy"], [])
    else:
        assert (reminded, _failures_in_log(centrum)) == ([], [f"przyczyna=plik-bez-odczytu plik={file}"])


def test_plik_przypomnien_bez_odczytu_od_startu_centrum_liczy_pore_taty_z_ostatniego_sprawdzenia_pracy(tmp_path: Path) -> None:
    """Decyzja 4A Maksa przy porze taty spoza pór ADR 0030: wczoraj praca sprawdzała w porannej porze taty 6:00–7:30,
    a dziś OneDrive trzyma plik Przypomnień od startu Centrum do końca tej pory. Porę zna plik pór pracy z wczoraj, więc
    pierwsze sprawdzenie po 7:30 zostawia w dzienniku Centrum wpis z nazwą pliku, a nie czeka na porę z ADR 0030."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    form = _reminders_form(footer="Pozdrawiam\nTata\n", morning={"start": "06:00", "end": "07:30"}, first="06:00")
    assert centrum.client.put("/api/settings/reminders", json=form).status_code == 200
    centrum.client.start()
    centrum.moment.append(datetime(2026, 11, 10, 6, 30))
    centrum.rhythm.tick()
    yesterday = len(mailbox.sends)
    centrum.restart()
    centrum.client.start()

    with without_reading(centrum.tool.config / REMINDERS_FILE):
        for moment in (datetime(2026, 11, 11, 6, 30), datetime(2026, 11, 11, 7, 30, 1)):
            centrum.moment.append(moment)
            centrum.rhythm.tick()
    centrum.client.stop()

    assert yesterday > 0, "wczoraj praca sprawdzała w porze taty"
    assert (len(mailbox.sends), _failures_in_log(centrum)) == (yesterday, [f"przyczyna=plik-bez-odczytu plik={REMINDERS_FILE}"])


def test_plik_przypomnien_bez_odczytu_od_startu_centrum_liczy_pore_taty_zmieniona_poza_pora(tmp_path: Path) -> None:
    """Decyzja 4A Maksa po zmianie pór poza porą: wczoraj praca sprawdzała w wieczornej porze z ADR 0030, o 22:30 tata
    przesunął poranną porę na 6:00–7:30 i zamknął Centrum przed nią, a dziś OneDrive trzyma plik Przypomnień od startu
    Centrum do końca tej pory. Pory z odczytu poza porą zna plik pór pracy, więc pierwsze sprawdzenie po 7:30 zostawia
    w dzienniku Centrum wpis z nazwą pliku, a nie czeka na porę z ADR 0030."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.client.start()
    centrum.moment.append(datetime(2026, 11, 10, 18, 30))
    centrum.rhythm.tick()
    centrum.moment.append(datetime(2026, 11, 10, 22, 30))
    form = _reminders_form(footer="Pozdrawiam\nTata\n", morning={"start": "06:00", "end": "07:30"}, first="06:00")
    assert centrum.client.put("/api/settings/reminders", json=form).status_code == 200
    centrum.moment.append(datetime(2026, 11, 10, 22, 31))
    centrum.rhythm.tick()
    yesterday = len(mailbox.sends)
    centrum.restart()
    centrum.client.start()

    with without_reading(centrum.tool.config / REMINDERS_FILE):
        for moment in (datetime(2026, 11, 11, 6, 30), datetime(2026, 11, 11, 7, 30, 1)):
            centrum.moment.append(moment)
            centrum.rhythm.tick()
    centrum.client.stop()

    assert (len(mailbox.sends), _failures_in_log(centrum)) == (yesterday, [f"przyczyna=plik-bez-odczytu plik={REMINDERS_FILE}"])


def test_przypomnienia_wylaczone_w_tej_samej_porze_po_pliku_bez_odczytu_nie_zostawiaja_wpisu(tmp_path: Path) -> None:
    """Plik Przypomnień bez odczytu w porze, a potem w tej samej porze tata wyłącza przypomnienia: wyłączone są
    wyłączone, a nie zepsute, więc po końcu pory dziennik Centrum nie dostaje wpisu o pliku bez odczytu."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.client.start()

    with without_reading(centrum.tool.config / REMINDERS_FILE):
        centrum.moment.append(REMINDER_MORNING)
        centrum.rhythm.tick()
    assert centrum.client.put("/api/settings/reminders/enabled", json={"enabled": False}).status_code == 200
    for moment in (datetime(2026, 11, 10, 8, 31), datetime(2026, 11, 10, 17, 1)):
        centrum.moment.append(moment)
        centrum.rhythm.tick()
    centrum.client.stop()

    assert (mailbox.sends, _failures_in_log(centrum)) == ([], [])


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
    _reminders_set_up(centrum)
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


def test_widok_raporty_pokazuje_pory_przypomnien_przy_dniu_wykonawcy_a_brak_stopki_do_sprawdzenia_po_jej_wpisaniu(
    tmp_path: Path,
) -> None:
    """Kryterium #1351: po pracy przypomnień widok Raporty ma przy dniu 9.11 każdego Wykonawcy chwile wysłanych za ten
    dzień przypomnień do niego, z „Wysłanych” i z tego sprawdzenia, bez przypomnienia za inny dzień i bez przypomnień
    innego Wykonawcy (Anna przysyła raport po porannym, więc wieczorne idzie tylko do Jana); brak stopki widok mówi
    do następnego sprawdzenia po wpisaniu stopki w Ustawieniach, a odpowiedź nie ma adresów, tematu ani stopki (US 44–45, ADR 0030)."""

    for_other_day = SentReminder(frozenset({SenderAddress(JAN)}), date(2026, 11, 8), datetime(2026, 11, 9, 8, 0).astimezone())
    mailbox = FakeMailbox(sent=(for_other_day,))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum, footer="")
    centrum.client.start()
    _finished(centrum)
    before = _view(centrum)
    morning, evening = REMINDER_MORNING.astimezone(), datetime(2026, 11, 10, 18, 5).astimezone()

    centrum.moment.append(REMINDER_MORNING)
    centrum.rhythm.tick()
    after_morning = centrum.client.get("/api/report-entering/view")
    assert centrum.client.put("/api/settings/reminders", json=_reminders_form(footer="Pozdrawiam\nTata\n")).status_code == 200
    mailbox.sent = (
        for_other_day,
        *(SentReminder(frozenset(reminder.recipients), reminder.day, at) for reminder, at in mailbox.sends),
    )
    mailbox.outcome = (report(ANNA, "Raport 09.11.2026", "40000002 tak spawpg"),)
    centrum.moment.append(datetime(2026, 11, 10, 18, 5))
    centrum.rhythm.tick()
    after_evening = _view(centrum)
    centrum.client.stop()

    assert (_reminders_of(before, "jan.testowy"), before["reminders_without_footer"]) == ([], False)
    shown = after_morning.json()
    assert (_reminders_of(shown, "jan.testowy"), _reminders_of(shown, "anna.kowalska")) == ([morning], [morning])
    assert shown["reminders_without_footer"] is True
    assert _reminders_of(after_evening, "jan.testowy") == [morning, evening]
    assert _reminders_of(after_evening, "anna.kowalska") == [morning]
    assert after_evening["reminders_without_footer"] is False
    for secret in (JAN, ANNA, SKRZYNKA, "Przypomnienie: raport", "Pozdrawiam"):
        assert secret not in after_morning.text, secret


def test_widok_raporty_mowi_o_braku_stopki_przed_pierwszym_kliknieciem_a_po_nieudanym_sprawdzeniu_milczy(
    tmp_path: Path,
) -> None:
    """Informacja o brakującej stopce stoi w widoku Raporty także przed pierwszym kliknięciem „Wpisz raporty z maili”,
    bo przypomnienia idą bez niego; sprawdzenie, które nie doszło do stopki (brak sieci przy odczycie skrzynki), niczego
    o stopce nie twierdzi, choć stopki dalej nie ma (#1351, przegląd #1364 r1 Drobne 2)."""

    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum, footer="")
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    before_click = _view(centrum)
    mailbox.outcome = InboxUnreachable("TimeoutError")
    centrum.moment.append(datetime(2026, 11, 10, 18, 5))
    centrum.rhythm.tick()
    after_failure = _view(centrum)
    centrum.client.stop()

    assert (before_click["clicked_at"], before_click["reminders_without_footer"]) == (None, True)
    assert (_reminder_result(centrum)["failure"], after_failure["reminders_without_footer"]) == ("brak-sieci", False)


@pytest.mark.parametrize("content", [b"{\"schema_version\": 1, \"sent\": [", b"\xff\xfe nie JSON", b'{"schema_version": 2, "footer": "missing", "sent": []}'])
def test_nieczytelny_wynik_przypomnien_nie_psuje_widoku_raporty(tmp_path: Path, content: bytes) -> None:
    """Wynik pracy przypomnień, którego nie da się przeczytać (urwany, nie UTF-8, innej wersji), widok Raporty pomija:
    pokazuje wynik kliknięcia bez pór przypomnień i bez informacji o stopce, a nie odmowę (#1351)."""

    centrum = entering_centrum(tmp_path, INTERMAX)
    _finished(centrum)
    (centrum.tool.config / REMINDERS_RESULT).write_bytes(content)

    view = _view(centrum)

    assert (_reminders_of(view, "jan.testowy"), view["reminders_without_footer"]) == ([], False)


# --- Błąd opisu we Wpisie ``tak`` z Legendą czynności Ustawień Centrum (ADR 0039) ---

MONTAZ = ActivityCode("montaz", ("montaż",), FixedColumn("Y"))
"""Kod taty spoza legendy z Wydania: z nim ``montaż`` jest Kodem czynności, a bez niego zwykłym opisem."""


def _with_dads_legend(centrum: EnteringCentrum) -> tuple[ActivityCode, ...]:
    """Legenda czynności taty w ``config``: legenda z Wydania z kodem ``MONTAZ``."""

    codes = (*DEFAULT_ACTIVITY_LEGEND.codes, MONTAZ)
    (centrum.tool.config / LEGEND_FILE).write_bytes(LEGEND.dump(codes))
    return codes


@pytest.mark.parametrize("dads_legend", [False, True], ids=["legenda-z-wydania", "legenda-taty"])
def test_wpisanie_raportow_czyta_opis_legenda_czynnosci_z_ustawien_i_ma_ja_w_logach(tmp_path: Path, dads_legend: bool) -> None:
    """ADR 0039, ADR 0041: Wpisanie raportów czyta opis Wpisu ``tak`` Legendą czynności z Ustawień Centrum, tą samą co
    Przygotowanie pliku zbiorczego, a Logi Uruchomienia mają ją dla odtworzenia. Przy legendzie z Wydania ``montaż`` to
    zwykły opis: Wpis się wpisuje, a widok Raporty pokazuje przy zleceniu „BRAK KODU”, nie problem; z ``montaż`` jako
    kodem w legendzie taty zlecenie ma ten kod. Przy kodzie z liczbą spoza przedziałów widok ma problem z powodem."""

    centrum = entering_centrum(
        tmp_path, INTERMAX, [report(JAN, SUBJECT, "40000001 tak montaż"), report(ANNA, SUBJECT, "40000002 tak montaż instutp40m")]
    )
    codes = _with_dads_legend(centrum) if dads_legend else DEFAULT_ACTIVITY_LEGEND.codes

    _finished(centrum)

    view = _view(centrum)
    faulty = FaultyDescription(
        Login("anna.kowalska"), date(2026, 11, 9), OrderNumber("40000002"), (NumberOutOfRange("instutp", "instutp{n}m", 40),)
    )
    assert _cells(centrum.register)[40000001] == ("tak", "montaż")
    assert _worker(view, "jan.testowy")["problems"] == []
    assert [(order["codes"], order["no_code"]) for order in _worker(view, "jan.testowy")["orders_detail"]] == [
        (["montaż"], False) if dads_legend else ([], True)
    ]
    assert _worker(view, "anna.kowalska")["problems"] == [
        {"reason": reason(faulty), "number": "40000002", "keep": None, "request": None, "faulty_subject": None}
    ]
    assert [(order["codes"], order["no_code"]) for order in _worker(view, "anna.kowalska")["orders_detail"]] == [
        (["montaż", "instutp40m"] if dads_legend else ["instutp40m"], False)
    ]
    [logs] = centrum.run_logs()
    assert LoggedActivityLegend.model_validate(logs["activity_legend"]).value() == ActivityLegend(codes)


def test_szczegoly_dnia_maja_przy_zleceniu_tak_kody_z_opisu_albo_brak_kodu_a_przy_bledzie_opisu_jego_powod(
    tmp_path: Path,
) -> None:
    """ADR 0041, US 32–39: Wpisanie raportów wpisuje do ``CZYNNOŚCI ZREALIZOWANE`` cały opis po ``tak``/``nie``, a
    szczegóły dnia w widoku Raporty mają przy każdym zleceniu ``tak`` słowa, które legenda wzięła za Kody czynności (przy
    ``inst30m instmdic`` tylko ``inst30m``, bez dopasowania po podobieństwie), przy zleceniu ``tak`` bez kodu „BRAK KODU”
    jako informację, nie problem, a przy Błędzie opisu jego powód. Zlecenie ``nie`` nie ma ani kodów, ani „BRAK KODU”."""

    numbers = (40000001, 40000005, 40000006, 40000007)
    intermax = Intermax(ordered=tuple(_order(9, 9 + index, "jan.testowy", number) for index, number in enumerate(numbers)), raw=())
    text = (
        "40000001 tak inst30m instmdic Podłączyłem lokal, klient zadowolony\n"
        "40000005 tak Podłączyłem lokal, dzielnik 1/2\n"
        "40000006 tak instutp40m wymiana gniazda\n"
        "40000007 nie brak klienta\n"
    )
    centrum = entering_centrum(tmp_path, intermax, [report(JAN, SUBJECT, text)])

    _finished(centrum)

    jan = _worker(_view(centrum), "jan.testowy")
    faulty = FaultyDescription(
        Login("jan.testowy"), date(2026, 11, 9), OrderNumber("40000006"), (NumberOutOfRange("instutp", "instutp{n}m", 40),)
    )
    assert [(order["number"], order["state"], order["codes"], order["no_code"]) for order in jan["orders_detail"]] == [
        ("40000001", "entered", ["inst30m"], False),
        ("40000005", "entered", [], True),
        ("40000006", "problem", ["instutp40m"], False),
        ("40000007", "entered", [], False),
    ]
    assert jan["problems"] == [
        {"reason": reason(faulty), "number": "40000006", "keep": None, "request": None, "faulty_subject": None}
    ]
    assert {number: _cells(centrum.register)[number] for number in numbers} == {
        40000001: ("tak", "inst30m instmdic Podłączyłem lokal, klient zadowolony"),
        40000005: ("tak", "Podłączyłem lokal, dzielnik 1/2"),
        40000006: ("tak", "instutp40m wymiana gniazda"),
        40000007: ("nie", "brak klienta"),
    }


def test_praca_przypomnien_nie_wysyla_przypomnienia_po_raporcie_z_bledem_opisu(tmp_path: Path) -> None:
    """ADR 0041: Raport Anny za 9.11 ma Wpis ``tak`` z kodem z liczbą spoza przedziałów, czyli Błąd opisu, ale jest
    przysłany, więc o 8:30 Anna nie dostaje Przypomnienia o raporcie; Jan bez raportu dostaje je z samym wzorem, bez
    bloku o zleceniach."""

    mailbox = FakeMailbox(outcome=(report(ANNA, "Raport 09.11.2026", "40000002 tak montaż instutp40m"),))
    centrum = entering_centrum(tmp_path, INTERMAX, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    [(reminder, _)] = mailbox.sends
    assert reminder.worker == "jan.testowy"
    assert reminder.text.splitlines() == [
        "Poproszę o wysłanie raportu za dzień 09.11.2026.",
        "",
        "Raport proszę wysłać według tego wzoru:",
        "Temat maila: Raport 09.11.2026",
        "Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód",
        "PRZYKŁAD:",
        "12345678 tak inst20m spawpg",
        "12345679 nie brak klienta",
        "",
        "Pozdrawiam",
        "Tata",
    ]


def test_praca_przypomnien_czyta_wpisy_od_cyfr_zlecen_z_tego_samego_odczytu_intermax_co_wpisanie_raportow(
    tmp_path: Path,
) -> None:
    """ADR 0041 (historia 14): okres 03_09_11_2026 ma Plik zbiorczy, a Jan przysyła 10.11 wieczorem Raport z pomylonym
    tematem 11.11 z dwoma numerami swoich zleceń: z 10.11 i siedmiocyfrowym z 9.11. Przypomnienia czytają INTERMAX od
    ``Window.start``, jak Wpisanie raportów, więc krótszy numer z dnia zamkniętego jest Wpisem, a nie słowem opisu, dwa
    niezgodne Wpisy to pomylony temat i raport liczy się za 10.11: o 8:30 11.11 przypomnienie dostaje tylko Anna."""

    intermax = Intermax(
        ordered=(_order(9, 9, "jan.testowy", 4000007), _order(10, 9, "jan.testowy", 40000005), _order(10, 11, "anna.kowalska", 40000006)),
        raw=(),
    )
    mail = report(JAN, "Raport 11.11.2026", "40000005 tak inst20m\n4000007 tak spawpg", at=datetime(2026, 11, 10, 21))
    mailbox = FakeMailbox(outcome=(mail,))
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    folder = centrum.periods_directory / MONDAY_PERIOD
    folder.mkdir(parents=True)
    (folder / f"Rozliczenie {MONDAY_PERIOD} - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, reminder.day) for reminder, _ in mailbox.sends] == [("anna.kowalska", date(2026, 11, 10))]



def test_praca_przypomnien_liczy_dzien_raportu_z_pamiecia_wpisania_po_zleceniach_dopisanych_z_raportu(tmp_path: Path) -> None:
    """ADR 0041 (historia 14), W1 r1 #2059: Jan przysyła 10.11 rano raport za 10.11 z datą 9.11 i dwoma numerami,
    których INTERMAX jeszcze nie ma, a kliknięcie o 7:00 dopisuje oba Janowi na 9.11. Wieczorem przychodzi ten sam
    raport z dobrą datą. Kafelek Wpisania z pamięcią tego kliknięcia liczy raport za 9.11 i za 10.11, bo numery dopisane
    przez Centrum nie robią z tematu pomylonego, więc praca przypomnień, która czyta tę samą pamięć, o 8:30 11.11 nie
    przypomina Janowi o 10.11; przypomnienie dostaje tylko Anna bez raportu."""

    intermax = Intermax(
        ordered=(_order(9, 9, "jan.testowy", 40000001), _order(10, 9, "jan.testowy", 40000005), _order(10, 11, "anna.kowalska", 40000006)),
        raw=(),
    )
    body = "40000007 tak inst20m\n40000008 tak spawpg"
    misdated = report(JAN, "Raport 09.11.2026", body, at=datetime(2026, 11, 10, 6))
    mailbox = FakeMailbox(outcome=(misdated, report(JAN, "Raport 10.11.2026", body, at=datetime(2026, 11, 10, 20))))
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    clicked = _click_at(centrum, datetime(2026, 11, 10, 7), [misdated])
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(added["number"], added["day"]) for added in _entering(centrum, clicked)["added"]] == [
        (40000007, "2026-11-09"),
        (40000008, "2026-11-09"),
    ]
    assert [(reminder.worker, reminder.day) for reminder, _ in mailbox.sends] == [("anna.kowalska", date(2026, 11, 10))]


def test_raport_bez_dnia_w_temacie_nie_konczy_przypomnien_za_dzien_sprzed_wdrozenia_wpisania_raportow(tmp_path: Path) -> None:
    """ADR 0041 (historia 20), D1 r1 #2068: przypomnienia działają od 9.11, a Wpisanie raportów od pierwszego kliknięcia
    10.11. Jan ma zlecenia 9.11 i 10.11, a 10.11 przysyła ``Raport 10.11.2026`` i sam ``Raport``. Dzień wskazany raportu
    bez dnia w temacie leży w dniach otwartych Wpisania, więc ten raport w obu operacjach nie liczy się za żaden dzień:
    widok Raporty ma problem bez dnia, a 11.11 rano idzie Janowi przypomnienie za 9.11."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(10, 9, "jan.testowy", 40000004)), raw=())
    mails = (
        report(JAN, "Raport 10.11.2026", "40000004 tak inst20m", at=datetime(2026, 11, 10, 19)),
        report(JAN, "Raport", "40000001 tak spawpg", at=datetime(2026, 11, 10, 20)),
    )
    mailbox = FakeMailbox(outcome=mails)
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    _click_at(centrum, datetime(2026, 11, 10, 21), list(mails))
    jan = _worker(_view(centrum), "jan.testowy", "2026-11-10")
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [_faulty_subject(problem) for problem in jan["problems"]] == [("Raport", "bez daty", None, mails[1].arrived)]
    assert [(reminder.worker, reminder.day) for reminder, _ in mailbox.sends] == [("jan.testowy", date(2026, 11, 9))]


def test_raport_bez_dnia_w_temacie_z_dnia_wdrozenia_wpisania_konczy_przypomnienie_za_ten_dzien(tmp_path: Path) -> None:
    """ADR 0041 (historia 20): przypomnienia działają od 9.11, a Wpisanie raportów od pierwszego kliknięcia 10.11. Jan
    przysyła 10.11 wieczorem sam ``Raport`` z numerem swojego zlecenia z 10.11, więc kafelek Wpisania liczy go za 10.11
    (dzień wskazany od dnia wdrożenia Wpisania). Praca przypomnień 11.11 o 8:30 czyta ten sam dzień wdrożenia z pamięci
    Wpisania, więc przypomina tylko Annie; z pamięcią bez dnia wdrożenia dzień wskazany zaczynałby się od dziś i Jan
    dostałby przypomnienie za 10.11."""

    intermax = Intermax(ordered=(_order(10, 9, "jan.testowy", 40000004), _order(10, 11, "anna.kowalska", 40000006)), raw=())
    mailbox = FakeMailbox(outcome=(report(JAN, "Raport", "40000004 tak inst20m", at=datetime(2026, 11, 10, 20)),))
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    _click_at(centrum, datetime(2026, 11, 10, 7), [])
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, reminder.day) for reminder, _ in mailbox.sends] == [("anna.kowalska", date(2026, 11, 10))]


def test_okres_z_plikiem_zbiorczym_sprzed_wdrozenia_wpisania_nie_dostaje_przypomnien_od_wdrozenia_przypomnien(
    tmp_path: Path,
) -> None:
    """ADR 0030: przypomnienia działają od poniedziałku 9.11, a Wpisanie raportów od pierwszego kliknięcia we wtorek
    10.11, więc okno przypomnień zaczyna się dzień wcześniej, w okresie 03_09_11_2026. Ten okres dostaje Plik zbiorczy:
    11.11 rano Jan bez raportów dostaje przypomnienie tylko za 10.11, a za 9.11 nie, choć ten dzień leży przed dniem
    wdrożenia Wpisania."""

    intermax = Intermax(ordered=(_order(9, 9, "jan.testowy", 40000001), _order(10, 9, "jan.testowy", 40000004)), raw=())
    mailbox = FakeMailbox()
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    _click_at(centrum, datetime(2026, 11, 10, 21), [])
    folder = centrum.periods_directory / MONDAY_PERIOD
    folder.mkdir(parents=True)
    (folder / f"Rozliczenie {MONDAY_PERIOD} - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert [(reminder.worker, reminder.day) for reminder, _ in mailbox.sends] == [("jan.testowy", date(2026, 11, 10))]


_SONDA_PAMIECI_WPISANIA = ROOT / "src" / "rozliczenia" / "centrum" / "sonda_pamieci_wpisania.py"


def _pamiec_wpisania(importy: str, cialo: str) -> str:
    """Moduł Centrum, który z ``ReportState`` pracy pyta pamięć Wpisania o odczyt okna jak Wpisanie raportów."""

    return (
        "from collections.abc import Sequence\nfrom datetime import date\n\n"
        f"{importy}\n"
        "from rozliczenia.activity_legend import ActivityLegend\n"
        "from rozliczenia.report_entering import ReportState\n"
        "from rozliczenia.worker_reports import EnteringMemory, RegisterWindow, ReportMail, Window, WorkerAddresses\n\n\n"
        "def wejscie(\n"
        "    state: ReportState, today: date, window: Window, intermax: RegisterWindow, mails: Sequence[ReportMail],\n"
        "    addresses: WorkerAddresses, legend: ActivityLegend,\n"
        ") -> object:\n"
        f"{cialo}"
        "    return memory.enter(window, intermax, mails, addresses, legend)\n"
    )


_PUSTA_PAMIEC = "from rozliczenia.worker_reports import OwnEntries, SavedState\n"
_ARGUMENT_PAMIECI = 'Argument 1 to "EnteringMemory" has incompatible type "SavedState"; expected "MemorySource"'
DROGI_PAMIECI_WPISANIA: Final = {
    "report_inputs z pamięcią zbudowaną obok (#2125 r1 W1)": (
        _pamiec_wpisania(
            "from rozliczenia.report_entering import report_inputs\nfrom rozliczenia.worker_reports import OwnEntries, SavedState\n",
            "    memory = EnteringMemory(state)\n"
            "    return report_inputs(window, intermax, mails, addresses, SavedState(None, OwnEntries.EMPTY), legend)\n",
        ),
        'Module "rozliczenia.report_entering" has no attribute "report_inputs"',
    ),
    "pamięć zbudowana obok: EnteringMemory(SavedState(None, OwnEntries.EMPTY)) (#2125 r1 W1)": (
        _pamiec_wpisania(_PUSTA_PAMIEC, "    memory = EnteringMemory(SavedState(None, OwnEntries.EMPTY))\n"),
        _ARGUMENT_PAMIECI,
    ),
    "gotowa pusta pamięć odtworzenia bez Logów: EnteringReplay.without_logs(dzień).saved (#2125 r2 W1)": (
        _pamiec_wpisania(
            "from rozliczenia.centrum.report_entering_logs import EnteringReplay\n",
            "    memory = EnteringMemory(EnteringReplay.without_logs(today).saved)\n",
        ),
        _ARGUMENT_PAMIECI,
    ),
    "pamięć z typu pamięci z pliku: type(state.load())(None, OwnEntries.EMPTY) (#2125 r2 W1)": (
        _pamiec_wpisania(
            "from rozliczenia.worker_reports import OwnEntries\n",
            "    memory = EnteringMemory(type(state.load())(None, OwnEntries.EMPTY))\n",
        ),
        _ARGUMENT_PAMIECI,
    ),
    "pamięć z pliku bez dnia wdrożenia Wpisania: replace(pamięć, …) (#2125 r3 W1)": (
        _pamiec_wpisania(
            "from dataclasses import replace\n",
            "    memory = replace(EnteringMemory(state), _saved=replace(state.load(), rollout=None))\n",
        ),
        'of "replace" cannot be "EnteringMemory"',
    ),
    "zmieniona prywatna wartość pamięci: pamięć._saved = …": (
        _pamiec_wpisania(
            "from dataclasses import replace\n",
            "    memory = EnteringMemory(state)\n    memory._saved = replace(state.load(), rollout=None)\n",
        ),
        "ruff SLF001",
    ),
    "podklasa z własną pamięcią: class Pusta(EnteringMemory) z __init__ bez ReportState (#2133 r1 W1)": (
        _pamiec_wpisania(
            _PUSTA_PAMIEC + "from rozliczenia.worker_reports import EnteringMemory\n\n\n"
            "class Pusta(EnteringMemory):\n"
            "    def __init__(self) -> None:\n"
            "        self._saved = SavedState(None, OwnEntries.EMPTY)\n\n",
            "    memory = Pusta()\n",
        ),
        'Cannot inherit from final class "EnteringMemory"',
    ),
    "podklasa, która zmienia pamięć z ReportState: super().__init__(state), potem rollout=None (#2133 r1 W1)": (
        _pamiec_wpisania(
            "from dataclasses import replace\n\nfrom rozliczenia.report_entering import ReportState\nfrom rozliczenia.worker_reports import EnteringMemory\n\n\n"
            "class BezWdrozenia(EnteringMemory):\n"
            "    def __init__(self, state: ReportState) -> None:\n"
            "        super().__init__(state)\n"
            "        self._saved = replace(state.load(), rollout=None)\n\n",
            "    memory = BezWdrozenia(state)\n",
        ),
        'Cannot inherit from final class "EnteringMemory"',
    ),
}
ZNANE_LUKI_PAMIECI_WPISANIA: Final = {
    "typ zna źródło pamięci, nie jego plik: ReportState zbudowany obok pamięci pracy Centrum": _pamiec_wpisania(
        _PUSTA_PAMIEC + "from rozliczenia.report_entering import ReportStateInMemory\n",
        "    memory = EnteringMemory(ReportStateInMemory(SavedState(None, OwnEntries.EMPTY)))\n",
    ),
    "refleksja po nazwie: object.__setattr__(pamięć, nazwa, …)": _pamiec_wpisania(
        "from dataclasses import replace\n",
        "    memory = EnteringMemory(state)\n"
        '    object.__setattr__(memory, "_saved", replace(state.load(), rollout=None))\n',
    ),
    "typ zna tylko klasy z kodu, nie klasy z biegu: podklasa z type(nazwa, (EnteringMemory,), …)": _pamiec_wpisania(
        _PUSTA_PAMIEC,
        '    pusta = type("Pusta", (EnteringMemory,), {"__init__": lambda self, state: None, "_saved": SavedState(None, OwnEntries.EMPTY)})\n'
        "    memory = pusta(state)\n",
    ),
}


@wymaga_ruff_i_mypy
def test_pamiec_wpisania_spoza_report_state_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    """Przypomnienia o raporcie i Wpisanie raportów liczą dzień raportu z tej samej pamięci Wpisania, bo wejście odczytu
    okna buduje tylko ``EnteringMemory`` za swoimi operacjami, a ``EnteringMemory`` powstaje tylko z ``ReportState`` pracy
    (``ReportState.load``): wołający nie ma wartości pamięci, którą mógłby zbudować, skopiować albo zmienić obok.

    | Postać | mypy, ruff | Próbka |
    |---|---|---|
    | ``report_inputs(…, SavedState(None, OwnEntries.EMPTY), …)`` (#2125 r1 W1) | łapie (mypy ``attr-defined``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``EnteringMemory(SavedState(None, OwnEntries.EMPTY))`` | łapie (mypy ``arg-type``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``EnteringMemory(EnteringReplay.without_logs(dzień).saved)`` (#2125 r2 W1) | łapie (mypy ``arg-type``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``EnteringMemory(type(state.load())(None, OwnEntries.EMPTY))`` (#2125 r2 W1) | łapie (mypy ``arg-type``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``replace(pamięć, _saved=replace(state.load(), rollout=None))`` (#2125 r3 W1) | łapie (mypy ``type-var``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``pamięć._saved = …`` | łapie (ruff ``SLF001``) | ``DROGI_PAMIECI_WPISANIA`` |
    | podklasa z własnym ``__init__``: ``class Pusta(EnteringMemory)`` (#2133 r1 W1) | łapie (mypy ``final``) | ``DROGI_PAMIECI_WPISANIA`` |
    | podklasa, która zmienia pamięć po ``super().__init__(state)`` (#2133 r1 W1) | łapie (mypy ``final``) | ``DROGI_PAMIECI_WPISANIA`` |
    | ``EnteringMemory(ReportStateInMemory(SavedState(None, OwnEntries.EMPTY)))`` | przepuszcza; w Przypomnieniach testy zachowania | ``ZNANE_LUKI_PAMIECI_WPISANIA`` |
    | ``object.__setattr__(pamięć, "_saved", …)`` | przepuszcza | ``ZNANE_LUKI_PAMIECI_WPISANIA`` |
    | podklasa z biegu: ``type("Pusta", (EnteringMemory,), {…})`` | przepuszcza | ``ZNANE_LUKI_PAMIECI_WPISANIA`` |

    ``ReportState`` zbudowany obok w Przypomnieniach o raporcie łapią testy zachowania pracy przypomnień:
    ``test_praca_przypomnien_liczy_dzien_raportu_z_pamiecia_wpisania_po_zleceniach_dopisanych_z_raportu`` (pamięć bez
    Zleceń dopisanych z raportu) i ``test_raport_bez_dnia_w_temacie_z_dnia_wdrozenia_wpisania_konczy_przypomnienie_za_ten_dzien``
    (pamięć bez dnia wdrożenia Wpisania)."""

    probki = {opis: kod for opis, (kod, _) in DROGI_PAMIECI_WPISANIA.items()} | ZNANE_LUKI_PAMIECI_WPISANIA
    zgloszenia = ruff_i_mypy(zapisz(probki, tmp_path), sonda=_SONDA_PAMIECI_WPISANIA)

    przepuszczone = {opis: zgloszenia[opis] for opis, (_, odmowa) in DROGI_PAMIECI_WPISANIA.items() if not any(odmowa in z for z in zgloszenia[opis])}
    assert przepuszczone == {}
    assert_znane_luki(
        {opis: zgloszenia[opis] for opis in ZNANE_LUKI_PAMIECI_WPISANIA}, "tests/test_centrum_wpisanie_raportow.py (ZNANE_LUKI_PAMIECI_WPISANIA)"
    )


def test_praca_przypomnien_czyta_okno_od_wdrozenia_wpisania_raportow_gdy_jest_wczesniejsze_niz_wdrozenie_przypomnien(
    tmp_path: Path,
) -> None:
    """ADR 0041 (historia 14), forma siostrzana W1 r1 #2059: Wpisanie raportów działa od 8.11, przypomnienia od 9.11.
    Jan przysyła Raport z tematem 9.11 z dwoma numerami swoich zleceń z 8.11, czyli pomylony temat, który kafelek
    Wpisania liczy za 8.11. Praca przypomnień czyta okno od 8.11 jak Wpisanie, więc zna te zlecenia i o 8:30 10.11
    przypomina Janowi o 9.11, za który raportu nie ma; za 8.11, dzień sprzed wdrożenia przypomnień, nie przypomina
    nikomu, także Annie bez raportu."""

    intermax = Intermax(
        ordered=(
            _order(8, 9, "jan.testowy", 40000001),
            _order(8, 10, "jan.testowy", 40000002),
            _order(8, 11, "anna.kowalska", 40000004),
            _order(9, 9, "jan.testowy", 40000003),
            _order(9, 11, "anna.kowalska", 40000005),
        ),
        raw=(),
    )
    mistaken = report(JAN, SUBJECT, "40000001 tak inst20m\n40000002 tak spawpg", at=datetime(2026, 11, 9, 19))
    mailbox = FakeMailbox(outcome=(mistaken,))
    centrum = entering_centrum(tmp_path, intermax, reminder_mailbox=mailbox)
    _reminders_set_up(centrum)
    _click_at(centrum, datetime(2026, 11, 8, 18), [])
    _click_at(centrum, datetime(2026, 11, 10, 8), [mistaken])
    shown = _view(centrum)
    tiles = [_worker(shown, "jan.testowy", day)["mails"] for day in ("2026-11-08", "2026-11-09")]
    centrum.moment.append(REMINDER_MORNING)
    centrum.client.start()

    centrum.rhythm.tick()
    centrum.client.stop()

    assert tiles == [1, 0]
    assert sorted((reminder.worker, reminder.day) for reminder, _ in mailbox.sends) == [
        ("anna.kowalska", date(2026, 11, 9)),
        ("jan.testowy", date(2026, 11, 9)),
    ]
