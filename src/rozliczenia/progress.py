"""Projekcja postępu: Zdarzenia przebiegu zredukowane do bezpiecznego snapshotu dla Centrum rozliczeń (ADR 0002)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, TypeVar

from .domain import (
    PHASES,
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressPhase,
    StepReached,
    WorkerEnded,
    WorkerFailed,
    WorkerStarted,
    WorkerStatus,
)

KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


class PhaseState(StrEnum):
    """Presentation-neutral state of a settlement phase."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class TemplateProcessing:
    """Zakończone Przetworzenie Szablonu pracownika w tym Uruchomieniu, ze Zdarzeń przebiegu jego Wykonawcy.

    ``duration_ms``: od ``WorkerStarted`` do ``WorkerEnded`` albo ``WorkerFailed`` zegarem sekwencera etapów
    (różnica ``elapsed_ms``), tym samym co czasy etapów. ``failed``: Przetworzenie przerwane; ``rows`` jest wtedy 0.
    """

    worker_name: str
    outcome: WorkerStatus | Literal["failed"]
    rows: int
    duration_ms: int


@dataclass(frozen=True)
class SavingStep:
    """Ostatni krok Zapisywania procesu bez Szablonów pracownika (``StepReached``): etykieta, Wykonawca, ile z ilu."""

    label: str
    worker: str | None
    done: int
    total: int


@dataclass(frozen=True)
class ProgressSnapshot:
    """Niemutowalne fakty procesu, które podgląd postępu pokazuje bez interpretowania zdarzeń."""

    phase_states: Mapping[ProgressPhase, PhaseState]
    phase_durations_ms: Mapping[ProgressPhase, int]
    template_total: int
    templates_completed: int
    rows: int
    operation_counts: Mapping[str, int]
    current_worker: str | None
    total_elapsed_ms: int
    issue_count: int
    templates: tuple[TemplateProcessing, ...]
    """Zakończone Przetworzenia Szablonów pracownika po kolei; rozpoczęte bez końca (odłączony podgląd) ich nie mają."""
    step: SavingStep | None = None
    """Ostatni krok Zapisywania procesu bez Szablonów pracownika; ``None`` przed pierwszym i w innych procesach."""

    def metric_counters(self) -> dict[str, int]:
        return {
            "templates_total": self.template_total,
            "templates_completed": self.templates_completed,
            "rows": self.rows,
            "written": self.operation_counts.get("ZAPISANO", 0),
            "empty": self.operation_counts.get("PUSTY_SZABLON", 0),
            "planned": self.operation_counts.get("PLAN", 0),
        }


def _immutable_mapping(values: Mapping[KeyT, ValueT]) -> Mapping[KeyT, ValueT]:
    return MappingProxyType(dict(values))


class ProgressProjection:
    """Jedyny interpretator Zdarzeń przebiegu.

    Redukuje zdarzenia bez ponownego sprawdzania kolejności: ``PhaseRunner`` jest jedynym nadawcą i ją sprawdza (ADR 0002).
    """

    def __init__(self) -> None:
        self._phase_states = {ProgressPhase(phase): PhaseState.PENDING for phase in PHASES}
        self._phase_durations_ms = {ProgressPhase(phase): 0 for phase in PHASES}
        self._template_total = 0
        self._templates_completed = 0
        self._rows = 0
        self._operation_counts: dict[str, int] = {}
        self._current_worker: str | None = None
        self._total_elapsed_ms = 0
        self._issue_count = 0
        self._templates: list[TemplateProcessing] = []
        self._worker_started_ms = 0
        self._step: SavingStep | None = None
        self._snapshot = self._make_snapshot()

    @property
    def snapshot(self) -> ProgressSnapshot:
        return self._snapshot

    def update(self, event: ProgressEvent) -> ProgressSnapshot:
        self._total_elapsed_ms = event.elapsed_ms
        match event:
            case PhaseStarted(phase=phase):
                self._phase_states[phase] = PhaseState.RUNNING
            case PhaseEnded(phase=phase, phase_elapsed_ms=phase_elapsed_ms):
                self._phase_states[phase] = PhaseState.COMPLETED
                self._phase_durations_ms[phase] = phase_elapsed_ms
            case IssueCountReady(issue_count=issue_count):
                self._issue_count = issue_count
            case PlanReady(template_total=template_total, issue_count=issue_count):
                self._template_total = template_total
                self._issue_count = issue_count
            case WorkerStarted(worker_name=worker_name):
                self._current_worker = worker_name
                self._worker_started_ms = event.elapsed_ms
            case WorkerEnded():
                self._templates_completed = event.template_index
                self._rows += event.rows
                self._issue_count = event.issue_count
                self._operation_counts[event.status] = self._operation_counts.get(event.status, 0) + 1
                self._current_worker = None
                self._templates.append(
                    TemplateProcessing(
                        event.worker_name, event.status, event.rows, event.elapsed_ms - self._worker_started_ms
                    )
                )
            case PhaseFailed(phase=phase, phase_elapsed_ms=phase_elapsed_ms):
                self._phase_states[phase] = PhaseState.FAILED
                self._phase_durations_ms[phase] = phase_elapsed_ms
            case StepReached(label=label, worker=worker, done=done, total=total):
                self._step = SavingStep(label, worker, done, total)
            case WorkerFailed():
                self._phase_states[event.phase] = PhaseState.FAILED
                self._phase_durations_ms[event.phase] = event.phase_elapsed_ms
                self._current_worker = event.worker_name
                self._templates.append(
                    TemplateProcessing(event.worker_name, "failed", 0, event.elapsed_ms - self._worker_started_ms)
                )
        self._snapshot = self._make_snapshot()
        return self._snapshot

    def _make_snapshot(self) -> ProgressSnapshot:
        return ProgressSnapshot(
            phase_states=_immutable_mapping(self._phase_states),
            phase_durations_ms=_immutable_mapping(self._phase_durations_ms),
            template_total=self._template_total,
            templates_completed=self._templates_completed,
            rows=self._rows,
            operation_counts=_immutable_mapping(self._operation_counts),
            current_worker=self._current_worker,
            total_elapsed_ms=self._total_elapsed_ms,
            issue_count=self._issue_count,
            templates=tuple(self._templates),
            step=self._step,
        )
