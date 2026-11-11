"""Rdzeń Uruchomienia procesu (``run_process``) na sztucznym procesie w pamięci, z rozmówcą testowym.

Sztuczny proces jest trzecim adapterem seamu ``Process``, obok Przebiegu
rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import NoReturn

import pytest

from rozliczenia.decision import Declined
from rozliczenia.domain import ProgressPhase
from rozliczenia.message import Message, StopError
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.process_run import Counter, Finished, Outcome, Process, Stop, run_process
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.run_clock import RunClock
from rozliczenia.run_context import RunContext

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
        name: (outcome.ending.kind, outcome.ending.message, outcome.view)
        for name, outcome in seen.items()
        if isinstance(outcome.ending, Stop)
    } == {
        "stop": ("stop", own.message, None),
        "unexpected": ("unexpected", ENDINGS["unexpected_failure"], None),
        "after_engine": ("after_engine", not_shown, None),
        "view": ("after_engine", not_shown, None),
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
    checking_ms = 50

    def stop_in_reading(_inputs: Inputs, context: RunContext) -> NoReturn:
        phases = PhaseRunner(context.observer, clock=context.clock.now)
        phases.check(lambda: time.sleep(checking_ms / 1000))

        def read() -> NoReturn:
            raise stop_error("Brak pliku.")

        phases.read(read)
        raise AssertionError("Odczyt danych miał zatrzymać proces.")

    outcome = run_core(fake_process(execute=stop_in_reading), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop)
    assert outcome.ending.kind == "stop"
    [record] = records(tmp_path / "metrics.jsonl")
    assert (record["period"], record["completed"], record["result"], record["counters"]) == (
        PERIOD,
        False,
        "BLAD_KRYTYCZNY",
        {"items": 0},
    )
    durations = record["phase_durations_ms"]
    assert durations["Sprawdzanie"] >= checking_ms
    assert (durations["Planowanie"], durations["Zapisywanie"]) == (0, 0)


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


def test_czas_decyzji_taty_nie_liczy_sie_do_czasu_uruchomienia(tmp_path: Path) -> None:
    clock = ManualClock()
    tata = Tata(before_answer=lambda: clock.advance(600))

    def working_250_ms_before_and_500_ms_after_decision(inputs: Inputs, context: RunContext) -> Summary:
        clock.advance(0.25)
        durations = asking_between_planning_and_saving(inputs, context)
        clock.advance(0.5)
        return durations

    outcome = run_core(
        fake_process(execute=working_250_ms_before_and_500_ms_after_decision),
        tmp_path / "metrics.jsonl",
        tata=tata,
        clock=clock,
    )

    assert outcome.result == "OK"
    assert len(tata.decisions) == 1
    assert outcome.total_duration_ms == 750
    [record] = records(tmp_path / "metrics.jsonl")
    assert record["total_duration_ms"] == 750


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


@dataclass
class TataSeeingSteps(Tata):
    """Tata, który zapisuje ``Czas uruchomienia`` z postępu przy każdym nowym kroku Zapisywania."""

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
    """Rozmówca, którego podgląd postępu pada od startu, więc rdzeń go odłącza."""

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        raise RuntimeError("podgląd nie działa")


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
    """Ślad wywołań własnego zatrzymania z przyczyną w wyjątku niesie łańcuch ``__cause__`` (#976), najwyżej 10
    przyczyn, więc przyczyna, której przyczyną jest ona sama, nie zatrzymuje Uruchomienia w nieskończonej pętli."""

    looped = ValueError(SECRET)
    looped.__cause__ = looped

    def stop_from_loop(_inputs: Inputs, _context: RunContext) -> NoReturn:
        raise stop_error("Pętla przyczyn.") from looped

    outcome = run_core(fake_process(execute=stop_from_loop), tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop) and outcome.ending.trace is not None, outcome.ending
    assert [cause.exception_type for cause in outcome.ending.trace.causes] == 10 * ["ValueError"]
