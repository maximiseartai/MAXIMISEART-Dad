from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import NoReturn

import pytest

from rozliczenia.decision import Declined
from rozliczenia.domain import PhaseEnded, PhaseStarted, ProgressEvent, ProgressPhase
from rozliczenia.message import Message, StopError
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.process_run import Counter, Finished, Outcome, Process, Stop, run_process
from rozliczenia.progress import PhaseState, ProgressProjection, ProgressSnapshot
from rozliczenia.run_clock import RunClock
from rozliczenia.run_context import RunContext
from rozliczenia.tool_files import TOOL_ROOT

from tests.fixtures.clock import ManualClock
from tests.fixtures.fake_process import (
    ENDINGS,
    METRICS_WARNING,
    PERIOD,
    QUESTION,
    SECRET,
    Durations,
    Inputs,
    Summary,
    asking_between_planning_and_saving,
    execute,
    fail,
    fake_process,
    records,
    stop_error,
)
from atrapy.interlocutor import Tata


def durations_view(_inputs: Inputs, summary: Summary) -> Durations:
    return summary.phase_durations_ms


def run_core(
    process: Process[Inputs, Summary, RunContext],
    metrics_path: Path,
    *,
    dry_run: bool = False,
    tata: Tata | None = None,
    view: Callable[[Inputs, Summary], Durations] = durations_view,
    clock: Callable[[], float] = time.perf_counter,
) -> Outcome[Durations]:
    return run_process(
        process,
        Inputs(dry_run=dry_run),
        tata or Tata(),
        view=view,
        metrics_path=metrics_path,
        context=RunContext(clock=RunClock(clock)),
    )


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
def test_core_closes_every_ending_with_a_message(tmp_path: Path, dry_run: bool) -> None:
    own = stop_error("Brak pliku.")

    def stop_in_engine(_inputs: Inputs, _context: RunContext) -> NoReturn:
        raise own

    endings: dict[str, tuple[Process[Inputs, Summary, RunContext], Callable[[Inputs, Summary], Durations]]] = {
        "stop": (fake_process(execute=stop_in_engine), durations_view),
        "unexpected": (fake_process(execute=fail), durations_view),
        "after_engine": (fake_process(result=fail), durations_view),
        "view": (fake_process(), fail),
    }

    seen = {
        name: run_core(process, tmp_path / "metrics.jsonl", dry_run=dry_run, view=view)
        for name, (process, view) in endings.items()
    }

    not_shown = ENDINGS["plan_not_shown" if dry_run else "summary_not_shown"]
    assert {
        name: (outcome.ending.kind, outcome.ending.message, outcome.view, outcome.ending.trace is not None)
        for name, outcome in seen.items()
        if isinstance(outcome.ending, Stop)
    } == {
        "stop": ("stop", own.message, None, False),
        "unexpected": ("unexpected", ENDINGS["unexpected_failure"], None, True),
        "after_engine": ("after_engine", not_shown, None, True),
        "view": ("after_engine", not_shown, None, True),
    }
    assert [
        (record["result"], record["completed"], record["counters"], record["stop"])
        for record in records(tmp_path / "metrics.jsonl")
    ] == [
        ("BLAD_KRYTYCZNY", False, {"items": 0}, {"kind": "for_tata", "code": own.message.code}),
        ("BLAD_KRYTYCZNY", False, {"items": 0}, {"kind": "for_maks", "code": ENDINGS["unexpected_failure"].code}),
        ("BLAD_KRYTYCZNY", False, {"items": 0}, {"kind": "for_maks", "code": not_shown.code}),
        ("BLAD_KRYTYCZNY", False, {"items": 0}, {"kind": "for_maks", "code": not_shown.code}),
    ]


def test_rekord_metryk_zatrzymania_do_maksa_ma_rodzaj_i_kod_bez_tresci_komunikatu(tmp_path: Path) -> None:
    to_maks = Message.to_maintainer("ZLA_KONFIGURACJA", SECRET, "Proces testowy")

    def stop_to_maks(_inputs: Inputs, _context: RunContext) -> NoReturn:
        raise StopError(to_maks)

    run_core(fake_process(execute=stop_to_maks), tmp_path / "metrics.jsonl")
    run_core(fake_process(), tmp_path / "metrics.jsonl")

    assert [record["stop"] for record in records(tmp_path / "metrics.jsonl")] == [
        {"kind": "for_maks", "code": "ZLA_KONFIGURACJA"},
        None,
    ]
    assert SECRET not in (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")


def test_rekord_metryk_ma_liczniki_w_kolejnosci_ich_definicji_w_procesie_takze_przy_zatrzymaniu(tmp_path: Path) -> None:
    names = ("zapisane", "akcje", "pominiete", "braki", "wiersze")

    def counted(value: int) -> Counter[Summary]:
        return Counter(names[value - 1], lambda _summary: value)

    counters = tuple(counted(value) for value in range(1, len(names) + 1))

    run_core(fake_process(counters=counters), tmp_path / "metrics.jsonl")
    run_core(fake_process(counters=counters, execute=fail), tmp_path / "metrics.jsonl")

    assert [list(record["counters"].items()) for record in records(tmp_path / "metrics.jsonl")] == [
        list(zip(names, range(1, len(names) + 1), strict=True)),
        [(name, 0) for name in names],
    ]


def test_zatrzymanie_zapisuje_rekord_z_okresem_zerowymi_licznikami_i_czasami_etapow_ktore_sie_wykonaly(
    tmp_path: Path,
) -> None:
    clock = ManualClock()

    def stop_in_reading(_inputs: Inputs, context: RunContext) -> NoReturn:
        phases = PhaseRunner(context.observer, clock=context.clock.now)
        phases.check(lambda: clock.advance(0.05))

        def read() -> NoReturn:
            clock.advance(0.025)
            raise stop_error("Brak pliku.")

        phases.read(read)
        raise AssertionError("Odczyt danych miał zatrzymać proces.")

    outcome = run_core(fake_process(execute=stop_in_reading), tmp_path / "metrics.jsonl", clock=clock)

    assert isinstance(outcome.ending, Stop)
    assert outcome.ending.kind == "stop"
    [record] = records(tmp_path / "metrics.jsonl")
    assert (record["period"], record["completed"], record["result"], record["counters"]) == (
        PERIOD,
        False,
        "BLAD_KRYTYCZNY",
        {"items": 0},
    )
    assert record["phase_durations_ms"] == {"Sprawdzanie": 50, "Odczyt danych": 25, "Planowanie": 0, "Zapisywanie": 0}


def test_nieudany_zapis_metryk_to_tylko_ostrzezenie_bez_zmiany_wyniku_procesu(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "nie-katalog"
    not_a_directory.write_text("nie katalog", encoding="utf-8")

    saved = run_core(fake_process(), tmp_path / "metrics.jsonl")
    unsaved = run_core(fake_process(), not_a_directory / "metrics.jsonl")

    assert (saved.metrics_saved, saved.technical_notes) == (True, ())
    assert (unsaved.metrics_saved, unsaved.technical_notes) == (False, (METRICS_WARNING,))
    assert isinstance(unsaved.ending, Finished)
    assert (unsaved.result, unsaved.ending.counters) == ("OK", {"items": 1})
    assert unsaved.view == unsaved.ending.phase_durations_ms


@pytest.mark.parametrize("interrupted_at", ["w-silniku", "przy-decyzji-taty"])
def test_przerwanie_przechodzi_przez_rdzen(tmp_path: Path, interrupted_at: str) -> None:
    def interrupt() -> NoReturn:
        raise KeyboardInterrupt

    def interrupted(_inputs: Inputs, _context: RunContext) -> NoReturn:
        interrupt()

    if interrupted_at == "w-silniku":
        process, tata = fake_process(execute=interrupted), Tata()
    else:
        process, tata = fake_process(execute=asking_between_planning_and_saving), Tata(before_answer=interrupt)

    with pytest.raises(KeyboardInterrupt):
        run_core(process, tmp_path / "metrics.jsonl", tata=tata)


def test_decyzja_taty_w_trakcie_etapu_nie_liczy_sie_do_czasu_etapu_ani_czasu_uruchomienia(tmp_path: Path) -> None:
    clock = ManualClock()
    tata = Tata(before_answer=lambda: clock.advance(600))

    def asking_while_reading(_inputs: Inputs, context: RunContext) -> Summary:
        phases = PhaseRunner(context.observer, clock=context.clock.now)
        phases.check(lambda: None)

        def read() -> None:
            clock.advance(0.25)
            context.conversation.confirm(QUESTION)
            clock.advance(0.5)

        phases.read(read)
        phases.plan(lambda: None, issue_count=lambda _planned: 0)
        phases.save(lambda: None)
        return Summary(phases.durations_ms())

    outcome = run_core(fake_process(execute=asking_while_reading), tmp_path / "metrics.jsonl", tata=tata, clock=clock)

    assert len(tata.decisions) == 1
    assert outcome.view is not None
    assert outcome.view[ProgressPhase.READING] == 750
    assert outcome.total_duration_ms == 750


def test_przerwany_etap_ma_czas_do_przerwania() -> None:
    clock = ManualClock()
    runner = PhaseRunner(None, clock=clock)
    runner.check(lambda: clock.advance(0.05))

    def read() -> None:
        clock.advance(0.025)
        raise RuntimeError("syntetyczny błąd")

    with pytest.raises(RuntimeError):
        runner.read(read)

    assert dict(runner.durations_ms()) == {ProgressPhase.CHECKING: 50, ProgressPhase.READING: 25}


def test_czas_uruchomienia_liczy_sie_od_utworzenia_sekwencera() -> None:
    clock = ManualClock()
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append, clock=clock)
    clock.advance(0.1)

    runner.check(lambda: clock.advance(0.05))

    assert [(type(event), event.elapsed_ms) for event in events][:2] == [(PhaseStarted, 100), (PhaseEnded, 150)]


@dataclass
class TataSeeingSteps(Tata):
    reached_ms: list[int] = field(default_factory=list)
    _last: object = None

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        if snapshot.step is not None and snapshot.step != self._last:
            self._last = snapshot.step
            self.reached_ms.append(snapshot.total_elapsed_ms)


def test_czekanie_silnika_na_tate_z_decyzja_w_srodku_zatrzymuje_zegar_raz_dla_krokow_etapu_i_uruchomienia(
    tmp_path: Path,
) -> None:
    clock = ManualClock()
    tata = TataSeeingSteps(before_answer=lambda: clock.advance(600))

    def waiting_for_tata_while_saving(_inputs: Inputs, context: RunContext) -> Summary:
        phases = PhaseRunner(context.observer, clock=context.clock.now)
        phases.check(lambda: None)
        phases.read(lambda: None)
        phases.plan(lambda: None, issue_count=lambda _planned: 0)

        def save() -> None:
            clock.advance(0.25)
            with context.clock.hold():
                clock.advance(300)
                phases.step("czekam na tatę")
                context.conversation.confirm(QUESTION)
                phases.step("tata odpowiedział")
            clock.advance(0.5)
            phases.step("dalej")

        phases.save(save)
        return Summary(phases.durations_ms())

    outcome = run_core(
        fake_process(execute=waiting_for_tata_while_saving), tmp_path / "metrics.jsonl", tata=tata, clock=clock
    )

    assert tata.reached_ms == [250, 250, 750]
    assert outcome.view is not None
    assert (outcome.view[ProgressPhase.SAVING], outcome.total_duration_ms) == (750, 750)


def test_odmowa_w_decyzji_taty_to_zatrzymanie_po_odmowie_a_w_metrykach_zatrzymanie_dla_taty(tmp_path: Path) -> None:
    refused = Message("ODMOWA", "Tata wybrał „Przerwij”.", "Proces testowy", "Uruchom ponownie.")

    def declining(_inputs: Inputs, _context: RunContext) -> NoReturn:
        raise Declined(refused)

    outcome = run_core(fake_process(execute=declining), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop)
    assert (outcome.ending.kind, outcome.ending.message, outcome.ending.stop_kind) == ("declined", refused, "for_tata")
    assert [record["stop"] for record in records(tmp_path / "metrics.jsonl")] == [{"kind": "for_tata", "code": "ODMOWA"}]


def stop_in_reading(_inputs: Inputs, context: RunContext) -> NoReturn:
    phases = PhaseRunner(context.observer, clock=context.clock.now)
    phases.check(lambda: None)

    def read() -> NoReturn:
        raise stop_error("Brak pliku.")

    phases.read(read)
    raise AssertionError("Odczyt danych miał zatrzymać proces.")


def stop_in_saving(_inputs: Inputs, context: RunContext) -> NoReturn:
    phases = PhaseRunner(context.observer, clock=context.clock.now)
    phases.check(lambda: None)
    phases.read(lambda: None)
    phases.plan(lambda: None, issue_count=lambda _planned: 0)

    def save() -> NoReturn:
        raise stop_error("Nie udało się zapisać.")

    phases.save(save)
    raise AssertionError("Zapisywanie miało zatrzymać proces.")


class BlindTata(Tata):
    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        raise RuntimeError("podgląd nie działa")


@dataclass
class TataWatching(Tata):
    snapshots: list[ProgressSnapshot] = field(default_factory=list)

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.snapshots.append(snapshot)


def test_podglad_postepu_dostaje_pusty_snapshot_na_starcie_i_po_jednym_po_kazdym_zdarzeniu_przebiegu(
    tmp_path: Path,
) -> None:
    tata = TataWatching()

    outcome = run_core(fake_process(), tmp_path / "metrics.jsonl", tata=tata)

    started_and_ended = 2 * len(ProgressPhase)
    issue_count_and_plan_ready = 2
    assert len(tata.snapshots) == 1 + started_and_ended + issue_count_and_plan_ready
    assert tata.snapshots[0] == ProgressProjection().snapshot
    assert tata.snapshots[-1] == outcome.progress


@dataclass
class TataBlindOnce(Tata):
    shown: int = 0

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.shown += 1
        if self.shown == 1:
            raise RuntimeError("podgląd nie działa")


def test_podglad_postepu_ktory_raz_padl_jest_odlaczony_do_konca_uruchomienia_bez_zmiany_wyniku(tmp_path: Path) -> None:
    tata = TataBlindOnce()

    outcome = run_core(fake_process(), tmp_path / "metrics.jsonl", tata=tata)

    assert tata.shown == 1
    assert (outcome.result, outcome.technical_notes) == (
        "OK",
        ("Podgląd postępu przestał się aktualizować; wynik nie zależy od tego.",),
    )
    assert outcome.progress.phase_states == {
        phase: PhaseState.RUNNING if phase is ProgressPhase.CHECKING else PhaseState.PENDING for phase in ProgressPhase
    }


@pytest.mark.parametrize(
    ("engine", "dry_run", "tata", "unchanged"),
    [
        (stop_in_reading, False, Tata(), True),
        (stop_in_saving, False, Tata(), False),
        (execute, False, Tata(), False),
        (execute, True, Tata(), True),
        (stop_in_reading, False, BlindTata(), False),
        (stop_in_reading, True, BlindTata(), True),
    ],
    ids=[
        "zatrzymanie-przed-zapisywaniem",
        "zatrzymanie-w-zapisywaniu",
        "zapis",
        "podglad",
        "odlaczony-podglad-postepu",
        "podglad-z-odlaczonym-podgladem-postepu",
    ],
)
def test_pliki_taty_sa_bez_zmian_tylko_w_podgladzie_albo_gdy_zapisywanie_sie_nie_zaczelo(
    tmp_path: Path,
    engine: Callable[[Inputs, RunContext], Summary],
    dry_run: bool,
    tata: Tata,
    unchanged: bool,
) -> None:
    outcome = run_core(fake_process(execute=engine), tmp_path / "metrics.jsonl", dry_run=dry_run, tata=tata)

    assert outcome.files_unchanged is unchanged


def test_slad_wywolan_zatrzymania_ucina_lancuch_przyczyn_na_dziesieciu_takze_lancuch_ktory_wraca_do_siebie(
    tmp_path: Path,
) -> None:
    looped = ValueError(SECRET)
    looped.__cause__ = looped

    def stop_from_loop(_inputs: Inputs, _context: RunContext) -> NoReturn:
        raise stop_error("Pętla przyczyn.") from looped

    outcome = run_core(fake_process(execute=stop_from_loop), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop) and outcome.ending.trace is not None, outcome.ending
    assert [cause.exception_type for cause in outcome.ending.trace.causes] == 10 * ["ValueError"]


def test_slad_wywolan_pomija_ramke_kodu_bez_pliku_takze_gdy_katalog_biezacy_to_katalog_narzedzia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def without_file() -> NoReturn:
        raise RuntimeError(SECRET)

    without_file.__code__ = without_file.__code__.replace(co_filename="<string>")

    def calling_code_without_file(_inputs: Inputs, _context: RunContext) -> NoReturn:
        without_file()

    monkeypatch.chdir(TOOL_ROOT)
    outcome = run_core(fake_process(execute=calling_code_without_file), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop) and outcome.ending.trace is not None, outcome.ending
    assert [frame.function for frame in outcome.ending.trace.frames][-1] == "calling_code_without_file"
    assert "<string>" not in {frame.file for frame in outcome.ending.trace.frames}


def test_podsumowanie_i_widok_rozmowcy_po_silniku_nie_licza_sie_do_czasu_uruchomienia(tmp_path: Path) -> None:
    clock = ManualClock()

    def working_250_ms(inputs: Inputs, context: RunContext) -> Summary:
        clock.advance(0.25)
        return execute(inputs, context)

    def view_taking_2_s(inputs: Inputs, summary: Summary) -> Durations:
        clock.advance(2)
        return durations_view(inputs, summary)

    outcome = run_core(fake_process(execute=working_250_ms), tmp_path / "metrics.jsonl", view=view_taking_2_s, clock=clock)

    assert (outcome.result, outcome.total_duration_ms) == ("OK", 250)
    [record] = records(tmp_path / "metrics.jsonl")
    assert record["total_duration_ms"] == 250


def test_tekst_bledu_zatrzymania_to_sam_kod_komunikatu_bez_jego_tresci() -> None:
    message = Message("KOD_PROBNY", "Co syntetyczne.", "plik a.xlsx, folder syntetyczny", "Zrób to syntetycznie.")

    error = StopError(message)

    assert (str(error), error.message) == ("KOD_PROBNY", message)
