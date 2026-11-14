"""Cykl Zgłoszenia na interfejsie jego uchwytu (``Reports.handle``): podgląd, pytanie skrzynki w tle, kolejka i stan.

Uchwytu używają Zatrzymanie (``stops``) i nieudana Aktualizacja narzędzia (``tool_updates``); tu źródłem jest
Aktualizacja, a okablowanie obu źródeł sprawdzają ich testy HTTP (``test_centrum_zgloszenie``,
``test_centrum_aktualizacja``). Wysyłka idzie przez prawdziwą kolejkę Skrzynki na fałszywej skrzynce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from rozliczenia import efenix_messages, preparation_messages
from rozliczenia.call_trace import CallCause, CallFrame, CallTrace
from rozliczenia.domain import RunMode
from rozliczenia.centrum import update_messages
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.keyed_box import KeyedBox, read_report_key
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, NOTE, REPORT, Case, DadCases
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY, case_outbox
from rozliczenia.centrum.outbox import PART_LIMIT, QUEUE_DIRECTORY, QUEUE_THREAD, RETRY_S, Outbox, Post
from rozliczenia.centrum.report_issue import fingerprint_line
from rozliczenia.centrum.report_box import IssuesOutcome, Label, Refused, Unreachable
from rozliczenia.centrum.reports import (
    SEARCH_DEADLINE_S,
    NoPreview,
    ProblemFingerprint,
    ReportHandle,
    Reports,
    StopReport,
    UpdateReport,
    report_target,
)
from rozliczenia.centrum.stops import Stops, plain
from rozliczenia.client_data import tool
from rozliczenia.centrum.tool_update import NO_CONNECTION, OTHER_BRANCH, UpdateResult
from rozliczenia.efenix_window import PagePart
from rozliczenia.process_run import Stop

from tests.fixtures.centrum import (
    QUEUED_FOR_INTERNET,
    QUEUED_FOR_KEY,
    REPORT_KEY,
    SENT,
    TOOL_COMMIT,
    FakeReportBox,
    ToolDirectory,
    dad_cases,
    join_threads_since,
    write_report_key,
)
from tests.fixtures.clock import ManualClock
from tests.fixtures.praca_centrum import centrum_work
from tests.fixtures.linie_watkow import new_line
from tests.fixtures.potomne import wait_for

READY = {"state": "ready"}
WAITING = {"state": "waiting"}


class Owner:
    """Właściciel Zgłoszenia: zapamiętuje każdy stan, który dostał od uchwytu."""

    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self._changed = threading.Condition()

    def __call__(self, state: BaseModel) -> None:
        with self._changed:
            self.states.append(dump(state))
            self._changed.notify_all()

    def wait_for(self, count: int, seconds: float = 10) -> list[dict[str, Any]]:
        with self._changed:
            assert self._changed.wait_for(lambda: len(self.states) >= count, seconds), self.states
            return list(self.states)


@dataclass
class Computer:
    """Katalog konfiguracji tego komputera, skrzynka Zgłoszeń, zegar i dziennik Centrum; ``reports()`` to start Centrum.

    ``outbox`` to kolejka Skrzynki ostatniego startu. Każdy kolejny start ma nowy zegar, jak nowy proces Centrum:
    budzik kolejki poprzedniego startu już nie dzwoni. Z tego samego powodu kolejny start czeka na koniec przejścia
    kolejki poprzedniego: kolejka, która zastałaby przejście poprzedniej na tym samym folderze, oddałaby jej swoje
    (``outbox._claimed``).
    """

    tmp_path: Path
    box: FakeReportBox = field(default_factory=FakeReportBox)
    search_deadline_s: float = SEARCH_DEADLINE_S
    clock: ManualClock = field(default_factory=ManualClock)
    outbox: Outbox | None = None
    keyed: KeyedBox | None = None
    stored: DadCases | None = None
    since: int | None = None

    @property
    def tool(self) -> ToolDirectory:
        return ToolDirectory(self.tmp_path)

    @property
    def config(self) -> Path:
        return self.tool.config

    @property
    def log(self) -> CentrumLog:
        return CentrumLog(self.tool.log_path)

    def with_key(self) -> None:
        write_report_key(self.tool)

    def reports(self) -> Reports:
        if self.since is not None:
            join_threads_since(self.since, named=QUEUE_THREAD)
            self.clock = ManualClock()
        self.since = new_line()
        work = centrum_work(self.config, self.log, self.clock)
        keyed = KeyedBox(self.box, lambda: read_report_key(self.config), clock=self.clock)
        stored = DadCases(work)
        outbox = case_outbox(work, keyed, stored)
        reports = Reports(
            work, keyed, outbox, lambda: TOOL_COMMIT, stored, search_deadline_s=self.search_deadline_s, settings_changes=tuple
        )
        self.outbox, self.keyed, self.stored = outbox, keyed, stored
        return reports

    def cases(self) -> list[dict[str, Any]]:
        return dad_cases(self.config, "zgloszenie")

    def numbers(self) -> list[int | None]:
        """Numery Zgłoszeń ostatniego startu: na nie czeka test, bo sprawy oddają je pod blokadą zapisu pliku stanu."""

        assert self.stored is not None
        return [case.number for case in self.stored.all() if case.kind == REPORT]

    def queued(self) -> list[Path]:
        return sorted((self.config / UNSENT_DIRECTORY / QUEUE_DIRECTORY).glob("*.json"))


@pytest.fixture
def computer(tmp_path: Path) -> Computer:
    (tmp_path / "config").mkdir()
    return Computer(tmp_path)


def dump(state: BaseModel) -> dict[str, Any]:
    return state.model_dump()


def source(computer: Computer, code: str = NO_CONNECTION) -> UpdateReport:
    message = update_messages.UpdateFailure.of(code).message
    return UpdateReport.of(UpdateResult(code, TOOL_COMMIT, None), message, computer.log)


def prepared(reports: Reports, computer: Computer, code: str = NO_CONNECTION) -> tuple[ReportHandle, Owner, str]:
    """Uchwyt z podglądem po odpowiedzi skrzynki (albo jej braku) na pytanie z podglądu: uchwyt, właściciel i treść."""

    owner = Owner()
    report = source(computer, code)
    handle = reports.handle(report.fingerprint, shown=owner)
    draft = handle.prepare(report)
    owner.wait_for(1)
    return handle, owner, draft.body


def test_wyslanie_przed_podgladem_nie_ma_czego_wyslac(computer: Computer) -> None:
    computer.with_key()
    handle = computer.reports().handle(source(computer).fingerprint)

    with pytest.raises(NoPreview):
        handle.send()

    assert (dump(handle.state), computer.box.keys) == (READY, [])


def test_wyslane_zgloszenie_to_dokladnie_podglad_a_sprawa_ma_numer_issue(computer: Computer) -> None:
    computer.with_key()
    handle, owner, body = prepared(computer.reports(), computer)

    assert dump(handle.send()) == SENT

    [issue] = computer.box.sent
    assert (issue.title.split(":")[0], issue.body, issue.comments) == (NO_CONNECTION, body, [])
    [case] = computer.cases()
    assert {name: case[name] for name in ("number", "commit", "closure")} == {
        "number": 1,
        "commit": TOOL_COMMIT,
        "closure": None,
    }
    assert (owner.states, computer.box.keys) == ([READY, SENT], [REPORT_KEY])
    assert wait_for(lambda: computer.queued() == [])


# Bardzo długi ślad wywołań i dziennik: każde z nich samo jest dłuższe niż jedna część wysyłki (#724).
LONG_FRAMES = tuple(CallFrame("src/rozliczenia/collective_preparation.py", line, f"krok_{line}") for line in range(3_000))
LONG_ENTRIES = tuple(f"2026-11-02T10:{minute:02d}:00+01:00 wpis-{minute:02d} {'x' * 5_000}" for minute in range(20))
SHORT_ENTRIES = tuple(f"2026-11-02T10:{minute:02d}:00+01:00 wpis-{minute:02d}" for minute in range(20))


def stop_report(entries: tuple[str, ...]) -> StopReport:
    """Zgłoszenie Zatrzymania po nieoczekiwanym wyjątku z bardzo długim śladem wywołań i dziennikiem ``entries``."""

    run = runs_contract.RunInfo(
        id="3f2a9c1b8e7d4f0a",
        process="preparation",
        title="Przygotowanie pliku zbiorczego",
        period="08_14_09_2026",
        mode=RunMode.DRY_RUN,
        pricing=None,
        confirms_readiness=False,
        register_name="Rejestr zleceń",
    )
    message = preparation_messages.unexpected_failure()
    stop = Stop("unexpected", message, trace=CallTrace("KeyError", LONG_FRAMES))
    return StopReport(run, stop, ProblemFingerprint.of("preparation", message), Diagnosis((), entries), logs=None)


def test_ten_sam_komunikat_zatrzymania_w_dwoch_procesach_to_dwa_problemy() -> None:
    """Kody Komunikatów są unikalne tylko w katalogu procesu, więc Zatrzymanie z tym samym Komunikatem w innym procesie
    ma inny odcisk problemu, czyli osobne Zgłoszenie (przegląd #1114 r1, Drobne 2)."""

    report = stop_report(SHORT_ENTRIES)
    other = report.run.model_copy(update={"process": "settlement", "title": "Przebieg rozliczeń"})

    fingerprints = {plain(run, report.stop).fingerprint.digest for run in (report.run, other)}

    assert len(fingerprints) == 2


LOGS_LINK = "https://github.com/tata/skrzynka/issues/7#issuecomment-1"


@dataclass
class _LogsCommentedWithDiagnosis:
    """Logi Uruchomienia, których komentarz kolejka zdążyła wysłać dopiero razem z Diagnozą: przed nią adresu nie ma."""

    runs: list[str] = field(default_factory=list)

    def link(self, run_id: str) -> str | None:
        return LOGS_LINK if run_id in self.runs else None

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None:
        self.runs.append(run_id)


def test_podglad_zgloszenia_po_diagnozie_ma_adres_logow_sprzed_komentarza_tej_diagnozy(computer: Computer) -> None:
    """Podgląd Zgłoszenia nie zależy od tego, czy kolejka zdążyła już wysłać komentarz Logów z tą Diagnozą: adres
    Logów jest ten sprzed jej komentarza, więc ta sama Diagnoza daje zawsze ten sam podgląd."""

    logs = _LogsCommentedWithDiagnosis()
    stops = Stops(computer.reports(), lambda process, period, settings: Diagnosis((), ()), computer.log, logs)
    report = stop_report(SHORT_ENTRIES)
    stopped = stops.ended(report.run, report.stop, shown=Owner(), settings=None)

    view = stops.diagnose(stopped)

    assert logs.runs == [report.run.id]
    assert f"- Logi: jeszcze niewysłane, Uruchomienie {report.run.id}" in view.report.body
    assert LOGS_LINK not in view.report.body


def sent_alone(computer: Computer, report: StopReport | UpdateReport) -> str:
    computer.with_key()
    handle = computer.reports().handle(report.fingerprint)
    body = handle.prepare(report).body

    assert dump(handle.send()) == SENT
    [issue] = computer.box.sent
    assert (issue.body, issue.comments) == (body, [])
    return body


def kept_newest(entries: tuple[str, ...], body: str) -> int:
    """Ile wpisów ``entries`` ma treść; to zawsze najnowsze, a dopisek mówi, ile najstarszych pominięto."""

    kept = sum(entry in body for entry in entries)
    assert all(entry in body for entry in entries[len(entries) - kept :])
    assert f"Pominięte najstarsze wpisy: {len(entries) - kept}, żeby Zgłoszenie zmieściło się w jednym issue." in body
    return kept


def test_zgloszenie_z_bardzo_dlugim_sladem_wywolan_traci_pierwsze_ramki_z_dopiskiem_o_logach(computer: Computer) -> None:
    body = sent_alone(computer, stop_report(SHORT_ENTRIES))

    frames = [f"{frame.file}:{frame.line} w {frame.function}" for frame in LONG_FRAMES]
    kept = sum(f"\n{frame}\n" in body for frame in frames)
    assert all(f"\n{frame}\n" in body for frame in frames[len(frames) - kept :])
    assert f"- Pominięte pierwsze ramki: {len(frames) - kept}, pełny ślad wywołań jest w Logach Uruchomienia" in body
    # Ślad traci tylko tyle ramek, ile trzeba, a dziennik zostaje cały.
    assert len(body) + len(frames[-kept - 1]) + 1 > PART_LIMIT
    assert all(entry in body for entry in SHORT_ENTRIES)
    assert "Pominięte najstarsze wpisy" not in body


def test_zgloszenie_zatrzymania_do_maksa_z_przyczyna_w_wyjatku_ma_typ_kazdej_przyczyny_w_sladzie_wywolan(
    computer: Computer,
) -> None:
    """Zatrzymanie okna efenix „do Maksa” ma ślad wywołań z łańcuchem przyczyn; Zgłoszenie podaje typ każdej przyczyny
    po kolei, bez treści wyjątków, a ich ramki zostawia Logom Uruchomienia."""

    run = runs_contract.RunInfo(
        id="5c1d7e2a9b0f4e36",
        process="efenix",
        title="Wycena w efenix",
        period="08_14_09_2026",
        mode=RunMode.RUN,
        pricing="bez Przekazania",
        confirms_readiness=False,
        register_name="Rejestr zleceń",
    )
    message = efenix_messages.window_stopped(PagePart.ORDER, kept=True)
    frames = (CallFrame("src/rozliczenia/efenix_pricing.py", 412, "_efenix_stops"),)
    causes = (
        CallCause("rozliczenia.efenix_window.UnexpectedPage", (CallFrame("src/rozliczenia/efenix_browser.py", 593, "_within"),)),
        CallCause("playwright._impl._errors.Error", ()),
    )
    stop = Stop("stop", message, trace=CallTrace("rozliczenia.message.StopError", frames, causes))
    body = sent_alone(computer, StopReport(run, stop, ProblemFingerprint.of("efenix", message), Diagnosis((), SHORT_ENTRIES), logs=None))

    lines = body.splitlines()
    section = lines[lines.index("## Ślad wywołań") + 1 :]
    assert section[: section.index("```text")] == [
        "",
        "- Wyjątek: rozliczenia.message.StopError",
        "- Przyczyna: rozliczenia.efenix_window.UnexpectedPage",
        "- Przyczyna: playwright._impl._errors.Error",
        "",
    ]
    assert ("src/rozliczenia/efenix_pricing.py:412 w _efenix_stops" in body, "_within" in body) == (True, False)


def test_zgloszenie_z_bardzo_dlugim_sladem_i_dziennikiem_to_jedna_czesc_bez_ramek_i_najstarszych_wpisow(
    computer: Computer,
) -> None:
    body = sent_alone(computer, stop_report(LONG_ENTRIES))

    assert f"- Pominięte pierwsze ramki: {len(LONG_FRAMES)}, pełny ślad wywołań jest w Logach Uruchomienia" in body
    kept = kept_newest(LONG_ENTRIES, body)
    assert 0 < kept < len(LONG_ENTRIES)
    assert len(body) + len(LONG_ENTRIES[-kept - 1]) + 1 > PART_LIMIT


def test_zgloszenie_nieudanej_aktualizacji_z_bardzo_dlugim_dziennikiem_to_jedna_czesc_bez_najstarszych_wpisow(
    computer: Computer,
) -> None:
    message = update_messages.UpdateFailure.of(NO_CONNECTION).message
    report = UpdateReport(UpdateResult(NO_CONNECTION, TOOL_COMMIT, None), message, LONG_ENTRIES, ProblemFingerprint.of_tool_update(message))

    body = sent_alone(computer, report)

    kept = kept_newest(LONG_ENTRIES, body)
    assert 0 < kept < len(LONG_ENTRIES)
    assert len(body) + len(LONG_ENTRIES[-kept - 1]) + 1 > PART_LIMIT


def update_report(result: UpdateResult, entries: tuple[str, ...]) -> UpdateReport:
    message = update_messages.UpdateFailure.of(result.code).message
    return UpdateReport(result, message, entries, ProblemFingerprint.of_tool_update(message))


def test_zgloszenie_nieudanej_aktualizacji_po_instalacji_bibliotek_bez_commitu_przed_mowi_to_wprost(
    computer: Computer,
) -> None:
    body = sent_alone(computer, update_report(UpdateResult(NO_CONNECTION, None, None, installed=True), SHORT_ENTRIES))

    lines = body.splitlines()
    start = lines.index("- Commit przed: nieznany")
    assert lines[start : start + 3] == ["- Commit przed: nieznany", "- Commit po: brak", "- Biblioteki instalowane: tak"]


def test_zgloszenie_dokladnie_na_granicy_jednej_czesci_wysylki_jest_cale(computer: Computer) -> None:
    result = UpdateResult(NO_CONNECTION, TOOL_COMMIT, None)
    frame = update_report(result, ("",)).report(commit=None, previous=None, settings=()).body
    entry = "x" * (PART_LIMIT - len(frame))

    body = sent_alone(computer, update_report(result, (entry,)))

    assert (len(body), f"\n{entry}\n" in body, "Pominięte najstarsze wpisy" in body) == (PART_LIMIT, True, False)


def test_bez_sieci_zgloszenie_czeka_w_kolejce_i_dostaje_numer_po_dostarczeniu(computer: Computer) -> None:
    computer.with_key()
    computer.box.search_failure = Unreachable()
    handle, owner, body = prepared(computer.reports(), computer)

    queued = dump(handle.send())
    [pending] = computer.cases()
    computer.box.search_failure = None
    computer.clock.advance(RETRY_S)

    assert (queued, pending["number"]) == (QUEUED_FOR_INTERNET, None)
    assert owner.wait_for(3) == [READY, QUEUED_FOR_INTERNET, SENT]
    assert [issue.body for issue in computer.box.sent] == [body]
    assert wait_for(lambda: computer.numbers() == [1])
    assert computer.cases() == [{**pending, "number": 1}]
    assert dump(handle.state) == SENT


@pytest.mark.parametrize("refused", [False, True], ids=["bez-klucza", "klucz-odrzucony"])
def test_bez_klucza_albo_z_odrzuconym_zgloszenie_czeka_na_klucz_i_wychodzi_samo_po_nowym_kluczu(
    computer: Computer, refused: bool
) -> None:
    if refused:
        computer.with_key()
        computer.box.search_failure = Refused()
    handle, owner, _ = prepared(computer.reports(), computer)

    queued = dump(handle.send())
    computer.box.search_failure = None
    write_report_key(computer.tool, REPORT_KEY + "_NOWY")
    computer.clock.advance(RETRY_S)

    assert queued == QUEUED_FOR_KEY
    assert owner.wait_for(3)[-1] == SENT
    assert len(computer.box.sent) == 1


def test_zgloszenie_ktorego_kolejka_nie_zapisala_daje_komunikat_i_nie_zostawia_sprawy(computer: Computer) -> None:
    computer.with_key()
    handle, _, _ = prepared(computer.reports(), computer)
    (computer.config / UNSENT_DIRECTORY).mkdir()
    blocker = computer.config / UNSENT_DIRECTORY / QUEUE_DIRECTORY
    blocker.write_text("plik zamiast folderu", encoding="utf-8")

    state = dump(handle.send())
    blocker.unlink()
    again = dump(handle.send())

    assert state == {
        "state": "not_queued",
        "message": {
            "what": "Nie udało się zapisać Zgłoszenia na tym komputerze, więc nie pójdzie do Maksa.",
            "where": "folder kolejka",
            "action": "Kliknij „Spróbuj ponownie”. Jeśli to nie pomoże, rozwiń „Co zostanie wysłane”, skopiuj treść i "
            "prześlij ją Maksowi mailem.",
        },
    }
    assert again == SENT
    assert [case["number"] for case in computer.cases()] == [1]


def test_drugi_uchwyt_tego_problemu_widzi_zgloszenie_w_kolejce_i_nie_wysyla_drugiego(computer: Computer) -> None:
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()

    second, owner, _ = prepared(reports, computer)

    assert (owner.states, dump(second.send())) == ([QUEUED_FOR_KEY], QUEUED_FOR_KEY)
    assert (len(computer.queued()), len(computer.cases())) == (1, 1)


def test_uchwyt_z_podgladem_sprzed_wysylki_tego_problemu_nie_wysyla_drugiego(computer: Computer) -> None:
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    second, _, _ = prepared(reports, computer)
    first.send()

    assert dump(second.send()) == QUEUED_FOR_KEY
    assert (len(computer.queued()), len(computer.cases())) == (1, 1)


def test_dwa_problemy_z_kolejki_dostaja_kazdy_numer_swojego_issue(computer: Computer) -> None:
    reports = computer.reports()
    for code in (NO_CONNECTION, OTHER_BRANCH):
        handle, _, _ = prepared(reports, computer, code)
        assert dump(handle.send()) == QUEUED_FOR_KEY

    computer.with_key()
    computer.clock.advance(RETRY_S)

    assert computer.box.wait_until(lambda box: len(box.sent) == 2)
    assert wait_for(lambda: None not in computer.numbers())
    bodies = {issue.number: issue.body.splitlines() for issue in computer.box.sent}
    assert [fingerprint_line(case["id"]) in bodies[case["number"]] for case in computer.cases()] == [True, True]


def test_dostarczenie_z_kolejki_zmienia_stan_kazdego_uchwytu_tego_problemu_na_wyslane(computer: Computer) -> None:
    reports = computer.reports()
    first, first_owner, _ = prepared(reports, computer)
    first.send()
    second, second_owner, _ = prepared(reports, computer)
    other, other_owner, _ = prepared(reports, computer, OTHER_BRANCH)

    computer.with_key()
    computer.clock.advance(RETRY_S)

    assert first_owner.wait_for(3) == [READY, QUEUED_FOR_KEY, SENT]
    assert second_owner.wait_for(2) == [QUEUED_FOR_KEY, SENT]
    assert (dump(other.state), other_owner.states) == (READY, [READY])


def test_ponowne_dostarczenie_tej_samej_sprawy_nie_zmienia_stanu_wyslanych(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    handle, _, body = prepared(reports, computer)
    handle.send()
    cases = computer.cases()
    [case] = cases
    report = source(computer)
    post = Post(
        report_target(report.fingerprint.digest, tool("tytuł")),
        period=None,
        run_id="ponowna-wysylka",
        header=None,
        parts=(tool(body),),
    )
    assert computer.outbox is not None

    computer.outbox.post(post)

    assert wait_for(lambda: computer.queued() == [])
    assert computer.box.sent[0].number == case["number"]
    assert len(computer.box.sent) == 1
    assert computer.cases() == cases


def test_przejete_zgloszenie_znane_z_tego_komputera_to_jedna_sprawa(computer: Computer) -> None:
    computer.with_key()
    first, _, _ = prepared(computer.reports(), computer)
    first.send()
    computer.box.search_failure = Unreachable()  # podgląd po restarcie nie wie, że Zgłoszenie jest otwarte
    restarted = computer.reports()
    again, owner, _ = prepared(restarted, computer)
    computer.box.search_failure = None

    assert owner.states == [WAITING]
    assert dump(again.send()) == SENT
    assert (len(computer.box.sent), [case["number"] for case in computer.cases()]) == (1, [1])


def test_poprzednie_zgloszenie_w_podgladzie_pomija_czekajace(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()
    computer.box.close(1)
    computer.box.search_failure = Unreachable()
    queued, _, _ = prepared(reports, computer)
    assert dump(queued.send()) == QUEUED_FOR_INTERNET

    _, _, body = prepared(reports, computer)

    assert "- Poprzednie Zgłoszenie: #1" in body.splitlines()


def test_wyslane_zgloszenie_nie_idzie_drugi_raz_takze_po_nowym_podgladzie(computer: Computer) -> None:
    computer.with_key()
    report = source(computer)
    handle, owner, _ = prepared(computer.reports(), computer)

    first, second = dump(handle.send()), dump(handle.send())
    handle.prepare(report)

    assert (first, second, owner.wait_for(3)) == (SENT, SENT, [READY, SENT, SENT])
    assert dump(handle.send()) == SENT
    assert (len(computer.box.keys), len(computer.box.sent)) == (1, 1)


def test_drugie_klikniecie_w_trakcie_wysylki_czeka_na_jej_wynik_i_nie_wysyla_drugi_raz(computer: Computer) -> None:
    computer.with_key()
    box = computer.box
    handle, _, _ = prepared(computer.reports(), computer)
    box.open_hold = threading.Event()
    answers: list[dict[str, Any]] = []
    clicks = [threading.Thread(target=lambda: answers.append(dump(handle.send())), daemon=True) for _ in range(2)]

    try:
        clicks[0].start()
        assert box.opening.wait(10)
        clicks[1].start()
        clicks[1].join(0.2)
        second_waits = clicks[1].is_alive()
    finally:
        box.open_hold.set()
    for click in clicks:
        click.join(10)

    assert second_waits
    assert answers == [SENT, SENT]
    assert len(box.sent) == 1


def test_wysylka_przerwana_wyjatkiem_nie_blokuje_nastepnej_ani_nie_zmienia_stanu(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.with_key()
    handle, owner, _ = prepared(computer.reports(), computer)
    outbox = computer.outbox
    assert outbox is not None
    post = outbox.post

    def broken(_post: Post) -> bool:
        raise RuntimeError("syntetyczna awaria kolejki")

    monkeypatch.setattr(outbox, "post", broken)
    with pytest.raises(RuntimeError, match="syntetyczna awaria kolejki"):
        handle.send()
    after_failure = dump(handle.state)
    monkeypatch.setattr(outbox, "post", post)

    answers: list[dict[str, Any]] = []
    again = threading.Thread(target=lambda: answers.append(dump(handle.send())), daemon=True)
    again.start()
    again.join(10)

    assert after_failure == READY
    assert answers == [SENT]
    assert owner.states == [READY, SENT]


def test_klikniecie_w_trakcie_powrotu_problemu_czeka_na_jego_koniec_i_nie_kladzie_zgloszenia_drugi_raz(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Problem z otwartym Zgłoszeniem wraca po Diagnozie, a uchwyt kładzie powrót w kolejce sam (bez sieci zostaje w
    niej); „Wyślij do Maksa” kliknięte w trakcie czeka na koniec powrotu i oddaje stan kolejki."""

    computer.with_key()
    reports = computer.reports()
    report = stop_report(SHORT_ENTRIES)
    first = reports.handle(report.fingerprint)
    first.prepare(report)
    first.wait_for_box()
    assert dump(first.send()) == SENT
    computer.box.search_failure = Unreachable()
    outbox = computer.outbox
    assert outbox is not None
    post, posting, release = outbox.post, threading.Event(), threading.Event()

    def held(queued: Post) -> bool:
        posting.set()
        release.wait(10)
        return post(queued)

    monkeypatch.setattr(outbox, "post", held)
    handle = reports.handle(report.fingerprint)
    answers: list[dict[str, Any]] = []
    click = threading.Thread(target=lambda: answers.append(dump(handle.send())), daemon=True)

    handle.prepare(report)
    try:
        assert posting.wait(10)
        click.start()
        click.join(0.2)
        click_waits = click.is_alive()
    finally:
        release.set()
    click.join(10)
    handle.wait_for_box()

    assert (click_waits, answers, dump(handle.state)) == (True, [QUEUED_FOR_INTERNET], QUEUED_FOR_INTERNET)
    assert len(computer.queued()) == 1


def test_otwarte_zgloszenie_wyslane_spoza_tego_komputera_czeka_na_naprawe_bez_drugiego_issue(computer: Computer) -> None:
    computer.with_key()
    first, _, _ = prepared(computer.reports(), computer)
    first.send()
    (computer.config / DAD_CASES_FILE).unlink()

    restarted = computer.reports()
    before = restarted.handle(source(computer).fingerprint)
    handle, owner, _ = prepared(restarted, computer)

    assert (dump(before.state), owner.states) == (READY, [WAITING])
    assert dump(handle.send()) == SENT
    assert (len(computer.box.sent), [case["number"] for case in computer.cases()]) == (1, [1])


def test_wyslane_zgloszenie_czeka_na_naprawe_po_restarcie_bez_pytania_skrzynki_a_inny_problem_nie(
    computer: Computer
) -> None:
    computer.with_key()
    handle, _, body = prepared(computer.reports(), computer)
    handle.send()
    asked = len(computer.box.listed)

    restarted = computer.reports()
    same = restarted.handle(source(computer).fingerprint)
    other = restarted.handle(source(computer, OTHER_BRANCH).fingerprint)

    assert (dump(same.state), dump(other.state), len(computer.box.listed)) == (WAITING, READY, asked)
    [fingerprint] = [line.removeprefix("- Odcisk problemu: ") for line in body.splitlines() if "Odcisk" in line]
    assert [{name: entry[name] for name in ("id", "number", "commit", "closure")} for entry in computer.cases()] == [
        {"id": fingerprint, "number": 1, "commit": TOOL_COMMIT, "closure": None}
    ]


def test_kolejny_start_zaczyna_sie_po_koncu_przejscia_kolejki_poprzedniego_jak_nowy_proces(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.with_key()
    hold = computer.box.open_hold = threading.Event()
    handle, _, _ = prepared(computer.reports(), computer)
    monkeypatch.setattr("rozliczenia.centrum.reports.DELIVERY_WAIT_S", 0.01)
    queued = dump(handle.send())
    release = threading.Timer(0.2, hold.set)
    release.start()

    computer.reports()

    assert (queued, len(computer.box.sent)) == (QUEUED_FOR_INTERNET, 1)


def test_inny_problem_wysyla_sie_osobno_obok_otwartego_zgloszenia(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()

    other, owner, body = prepared(reports, computer, OTHER_BRANCH)

    assert owner.states == [READY]
    assert "Poprzednie Zgłoszenie" not in body
    assert dump(other.send()) == SENT
    assert [report.title.split(":")[0] for report in computer.box.sent] == [NO_CONNECTION, OTHER_BRANCH]


def test_uwaga_taty_o_identyfikatorze_rownym_odciskowi_nie_jest_poprzednim_zgloszeniem(computer: Computer) -> None:
    computer.with_key()
    fingerprint = source(computer).fingerprint.digest
    note = Case(NOTE, fingerprint, "Uwaga o tym samym identyfikatorze", None, datetime.now(timezone.utc), 4)
    DadCases(centrum_work(computer.config, computer.log)).add(note)

    _, _, body = prepared(computer.reports(), computer)

    assert "Poprzednie Zgłoszenie" not in body


def test_po_zamknieciu_zgloszenia_powracajacy_problem_wysyla_nowe_z_odnosnikiem_do_poprzedniego(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, first_body = prepared(reports, computer)
    first.send()
    computer.box.close(1)

    before = reports.handle(source(computer).fingerprint)
    again, owner, body = prepared(reports, computer)

    assert (dump(before.state), owner.states) == (WAITING, [READY])
    assert "- Poprzednie Zgłoszenie: #1" in body.splitlines()
    assert "Poprzednie Zgłoszenie" not in first_body
    assert dump(again.send()) == SENT
    assert [case["number"] for case in computer.cases()] == [1, 2]


def test_bez_odpowiedzi_skrzynki_wyslany_problem_dalej_czeka_na_naprawe(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()
    computer.box.close(1)
    computer.box.search_failure = Unreachable()

    _, owner, _ = prepared(reports, computer)

    assert owner.states == [WAITING]
    assert len(computer.box.sent) == 1


def test_gdy_skrzynka_nie_odpowiada_zgloszenie_czeka_w_kolejce_bez_zakladania_issue(computer: Computer) -> None:
    computer.with_key()
    computer.box.search_failure = Unreachable()
    handle, _, _ = prepared(computer.reports(), computer)

    assert dump(handle.send()) == QUEUED_FOR_INTERNET
    assert (computer.box.keys, len(computer.queued())) == ([], 1)


def test_podglad_nie_czeka_na_skrzynke_a_spozniona_odpowiedz_to_brak_odpowiedzi(computer: Computer) -> None:
    computer.with_key()
    computer.search_deadline_s = 0.05
    box = computer.box
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()
    box.close(1)
    box.search_hold = threading.Event()
    release = threading.Timer(10, box.search_hold.set)  # bez limitu stan czekałby na skrzynkę
    release.start()

    try:
        _, owner, _ = prepared(reports, computer)
        box_answered_first = box.search_hold.is_set()
    finally:
        box.search_hold.set()
        release.cancel()

    assert not box_answered_first
    assert owner.states == [WAITING]


@dataclass
class FirstSearchHeld(FakeReportBox):
    """Skrzynka, w której tylko pierwsze pytanie o otwarte Zgłoszenia (``first_asked``) czeka, aż test je puści
    (``first_search``)."""

    first_asked: threading.Event = field(default_factory=threading.Event)
    first_search: threading.Event = field(default_factory=threading.Event)

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if not self.first_asked.is_set():
            self.first_asked.set()
            self.first_search.wait()
        return super().labelled_issues(label, include_closed=include_closed, key=key)


def test_odpowiedz_skrzynki_na_pytanie_sprzed_wysylki_nie_zmienia_wyniku_wysylki(tmp_path: Path) -> None:
    computer = Computer(tmp_path, FirstSearchHeld(outcomes=[Unreachable()]))
    computer.with_key()
    box = computer.box
    assert isinstance(box, FirstSearchHeld)
    report = source(computer)
    owner = Owner()
    handle = computer.reports().handle(report.fingerprint, shown=owner)

    try:
        handle.prepare(report)
        assert box.first_asked.wait(10)
        queued = dump(handle.send())
    finally:
        box.first_search.set()
    handle.wait_for_box()

    assert queued == QUEUED_FOR_INTERNET
    assert (owner.states, dump(handle.state)) == ([queued], queued)


def test_odpowiedz_skrzynki_sprzed_numeru_zgloszenia_nie_zaciera_go_gdy_dochodzi_po_nim(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.with_key()
    reports = computer.reports()
    keyed = computer.keyed
    assert keyed is not None
    find_issue = keyed.find_issue
    answered, arrives = threading.Event(), threading.Event()

    def late(label: Label, line: str, *, include_closed: bool) -> object:
        """Pierwsza odpowiedź „brak otwartego Zgłoszenia” policzona przed wysyłką dochodzi dopiero po niej."""

        answer = find_issue(label, line, include_closed=include_closed)
        if not answered.is_set():
            answered.set()
            arrives.wait()
        return answer

    monkeypatch.setattr(keyed, "find_issue", late)
    report = source(computer)
    first = reports.handle(report.fingerprint)

    try:
        first.prepare(report)
        assert answered.wait(10)
        assert dump(first.send()) == SENT
        assert wait_for(lambda: dump(reports.handle(report.fingerprint).state) == WAITING)
    finally:
        arrives.set()
    first.wait_for_box()

    assert dump(reports.handle(report.fingerprint).state) == WAITING


def test_dostarczenie_tuz_po_koncu_czekania_na_skrzynke_daje_stan_wyslane(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.with_key()
    computer.box.open_hold = threading.Event()
    handle, owner, _ = prepared(computer.reports(), computer)
    keyed = computer.keyed
    assert keyed is not None
    judge = keyed.judge

    def delivered_meanwhile(*, wait_s: float) -> str:
        assert computer.box.open_hold is not None
        computer.box.open_hold.set()
        assert wait_for(lambda: computer.numbers() == [1])
        return judge(wait_s=wait_s)

    monkeypatch.setattr("rozliczenia.centrum.reports.DELIVERY_WAIT_S", 0.01)
    monkeypatch.setattr(keyed, "judge", delivered_meanwhile)

    assert dump(handle.send()) == SENT
    assert (owner.states, dump(handle.state)) == ([READY, SENT], SENT)
