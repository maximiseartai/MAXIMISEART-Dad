from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import itertools

import pytest

from rozliczenia.domain import (
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressPhase,
    WorkerEnded,
    WorkerFailed,
    WorkerStarted,
    WorkerStatus,
)
from rozliczenia.progress import (
    PhaseState,
    ProgressProjection,
    TemplateProcessing,
)


def until_saving(template_total: int, *, issue_count: int = 0) -> list[ProgressEvent]:
    """Zdarzenia przebiegu od Sprawdzania do rozpoczęcia Zapisywania, z czasem rosnącym o 1 ms."""

    events: list[ProgressEvent] = []
    for phase in (ProgressPhase.CHECKING, ProgressPhase.READING, ProgressPhase.PLANNING):
        events.append(PhaseStarted(phase, elapsed_ms=len(events)))
        events.append(PhaseEnded(phase, elapsed_ms=len(events), phase_elapsed_ms=1))
        if phase is ProgressPhase.READING:
            events.append(IssueCountReady(elapsed_ms=len(events), issue_count=issue_count))
    events.append(PlanReady(elapsed_ms=len(events), template_total=template_total, issue_count=issue_count))
    events.append(PhaseStarted(ProgressPhase.SAVING, elapsed_ms=len(events)))
    return events


START = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


def moment(index: int) -> datetime:
    """Chwila zdarzenia numer ``index`` (od 0) projekcji z zegarem ``ticking``."""

    return START + timedelta(seconds=index)


def ticking() -> Callable[[], datetime]:
    """Zegar ścienny, który przy każdym odczycie idzie o sekundę od ``START``."""

    seconds = itertools.count()
    return lambda: moment(next(seconds))


def project(events: list[ProgressEvent], now: Callable[[], datetime] | None = None) -> ProgressProjection:
    projection = ProgressProjection() if now is None else ProgressProjection(now)
    for event in events:
        projection.update(event)
    return projection


def ended(worker_name: str, index: int, status: WorkerStatus = "ZAPISANO", rows: int = 1) -> WorkerEnded:
    return WorkerEnded(
        worker_name,
        template_index=index,
        status=status,
        rows=rows,
        elapsed_ms=20 + index,
        issue_count=0,
    )


def test_projection_reduces_failed_przetworzenie_szablonu_pracownika_without_counting_it_as_completed() -> None:
    projection = project(
        [
            *until_saving(2),
            WorkerStarted("Adrian Testowy", template_index=1, elapsed_ms=10),
            ended("Adrian Testowy", 1, rows=2),
            WorkerStarted("Darek Fikcyjny", template_index=2, elapsed_ms=12),
        ]
    )

    failed = WorkerFailed("Darek Fikcyjny", template_index=2, elapsed_ms=25, phase_elapsed_ms=5)
    snapshot = projection.update(failed)

    assert snapshot.phase_states[ProgressPhase.SAVING] is PhaseState.FAILED
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 5
    assert snapshot.current_worker == "Darek Fikcyjny"
    assert snapshot.templates_completed == 1
    assert snapshot.rows == 2
    assert snapshot.operation_counts["ZAPISANO"] == 1
    with pytest.raises(TypeError):
        snapshot.phase_states[ProgressPhase.SAVING] = PhaseState.COMPLETED  # type: ignore[index]


def test_projection_reduces_complete_przebieg_rozliczen_to_one_snapshot() -> None:
    projection = project(
        [
            *until_saving(2, issue_count=1),
            WorkerStarted("Adrian Testowy", template_index=1, elapsed_ms=9),
            WorkerEnded(
                "Adrian Testowy",
                template_index=1,
                status="ZAPISANO",
                rows=2,
                elapsed_ms=12,
                issue_count=1,
            ),
            WorkerStarted("Darek Fikcyjny", template_index=2, elapsed_ms=13),
            WorkerEnded(
                "Darek Fikcyjny",
                template_index=2,
                status="PUSTY_SZABLON",
                rows=0,
                elapsed_ms=14,
                issue_count=1,
            ),
        ]
    )

    snapshot = projection.update(PhaseEnded(ProgressPhase.SAVING, elapsed_ms=16, phase_elapsed_ms=7))

    assert all(state is PhaseState.COMPLETED for state in snapshot.phase_states.values())
    assert snapshot.template_total == 2
    assert snapshot.templates_completed == 2
    assert snapshot.rows == 2
    assert snapshot.operation_counts == {"ZAPISANO": 1, "PUSTY_SZABLON": 1}
    assert snapshot.current_worker is None
    assert snapshot.phase_durations_ms[ProgressPhase.SAVING] == 7
    assert snapshot.total_elapsed_ms == 16
    assert snapshot.issue_count == 1


def test_projection_marks_failed_faza_przebiegu() -> None:
    projection = project([PhaseStarted(ProgressPhase.CHECKING, elapsed_ms=1)])

    snapshot = projection.update(PhaseFailed(ProgressPhase.CHECKING, elapsed_ms=3, phase_elapsed_ms=2))

    assert snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.FAILED
    assert snapshot.phase_durations_ms[ProgressPhase.CHECKING] == 2


def test_projekcja_mierzy_kazde_przetworzenie_szablonu_pracownika_od_jego_rozpoczecia_do_konca() -> None:
    before = until_saving(3)
    projection = project(
        [
            *before,
            WorkerStarted("Adrian Testowy", template_index=1, elapsed_ms=10),
            WorkerEnded("Adrian Testowy", template_index=1, status="ZAPISANO", rows=2, elapsed_ms=13, issue_count=0),
            WorkerStarted("Darek Fikcyjny", template_index=2, elapsed_ms=14),
            WorkerEnded("Darek Fikcyjny", template_index=2, status="PUSTY_SZABLON", rows=0, elapsed_ms=15, issue_count=0),
            WorkerStarted("Kamil Syntetyczny", template_index=3, elapsed_ms=21),
        ],
        ticking(),
    )
    adrian = len(before)

    running = projection.snapshot
    failed = projection.update(WorkerFailed("Kamil Syntetyczny", template_index=3, elapsed_ms=27, phase_elapsed_ms=9))

    written = TemplateProcessing("Adrian Testowy", "ZAPISANO", 2, 3, moment(adrian), moment(adrian + 1))
    empty = TemplateProcessing("Darek Fikcyjny", "PUSTY_SZABLON", 0, 1, moment(adrian + 2), moment(adrian + 3))
    assert running.templates == (written, empty)
    stopped = TemplateProcessing("Kamil Syntetyczny", "failed", 0, 6, moment(adrian + 4), moment(adrian + 5))
    assert failed.templates == (written, empty, stopped)
    assert (failed.phase_started_at[ProgressPhase.SAVING], failed.phase_ended_at[ProgressPhase.SAVING]) == (
        moment(adrian - 1),
        moment(adrian + 5),
    )
