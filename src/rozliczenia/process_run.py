from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic, Literal, Protocol, Self, TypeVar

from .call_trace import CallTrace
from .decision import Conversation, Decision, Declined
from .domain import ProgressEvent, ProgressObserver, ProgressPhase, RunMode, StopKind
from .message import Message, StopError
from .progress import PhaseState, ProgressProjection, ProgressSnapshot
from .telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from .write_routes import RouteCounts
from .run_clock import RunClock
from .wall_clock import utc_now

__all__ = [
    "Counter",
    "Finished",
    "Interlocutor",
    "Outcome",
    "Preview",
    "Process",
    "ProcessInputs",
    "ProcessSummary",
    "Stop",
    "run_process",
]

_DETACHED_OBSERVER_NOTE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."


class ProcessInputs(Protocol):
    @property
    def period(self) -> str: ...


class EngineContext(Protocol):
    @property
    def clock(self) -> RunClock: ...

    def engaged(self, observer: ProgressObserver, conversation: Conversation) -> Self: ...


class ProcessSummary(Protocol):
    @property
    def phase_durations_ms(self) -> Mapping[ProgressPhase, int]: ...


InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=ProcessSummary)
ViewT = TypeVar("ViewT")
ContextT = TypeVar("ContextT", bound=EngineContext)


class Interlocutor(Conversation, Protocol):
    def show_progress(self, snapshot: ProgressSnapshot) -> None: ...


StopEnding = Literal["stop", "declined", "unexpected", "after_engine"]


@dataclass(frozen=True)
class Stop:
    kind: StopEnding
    message: Message
    trace: CallTrace | None = field(default=None, compare=False, repr=False)
    facts: object = field(default=None, compare=False, repr=False)

    @property
    def stop_kind(self) -> StopKind:
        own = self.kind in ("stop", "declined")
        return "for_maks" if not own or self.message.reports_to_maintainer else "for_tata"


RunResult = Literal[CompletedResult, "BLAD_KRYTYCZNY"]


@dataclass(frozen=True)
class Finished:
    result: CompletedResult
    counters: Mapping[str, int]
    phase_durations_ms: Mapping[ProgressPhase, int]
    routes: RouteCounts = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Counter(Generic[SummaryT]):
    name: str
    count: Callable[[SummaryT], int]


@dataclass(frozen=True)
class Preview(Generic[InputsT]):
    plan_not_shown: Message
    dry_run: Callable[[InputsT], bool]


def _no_routes(_summary: object) -> RouteCounts:
    return MappingProxyType({})


@dataclass(frozen=True, kw_only=True)
class Process(Generic[InputsT, SummaryT, ContextT]):
    name: str
    counters: tuple[Counter[SummaryT], ...]
    result: Callable[[InputsT, SummaryT], CompletedResult]
    routes: Callable[[SummaryT], RouteCounts] = _no_routes
    preview: Preview[InputsT] | None
    metrics_failure_tail: str
    execute: Callable[[InputsT, ContextT], SummaryT]
    unexpected_failure: Message
    summary_not_shown: Message

    @property
    def counter_names(self) -> frozenset[str]:
        return frozenset(counter.name for counter in self.counters)

    def dry_run(self, inputs: InputsT) -> bool:
        return self.preview is not None and self.preview.dry_run(inputs)

    def finished(self, inputs: InputsT, summary: SummaryT) -> Finished:
        return Finished(
            result=self.result(inputs, summary),
            counters={counter.name: counter.count(summary) for counter in self.counters},
            phase_durations_ms=summary.phase_durations_ms,
            routes=self.routes(summary),
        )


@dataclass(frozen=True)
class Outcome(Generic[ViewT]):
    ending: Finished | Stop
    view: ViewT | None
    total_duration_ms: int
    technical_notes: tuple[str, ...]
    metrics_saved: bool
    progress: ProgressSnapshot
    files_unchanged: bool

    @property
    def result(self) -> RunResult:
        return self.ending.result if isinstance(self.ending, Finished) else "BLAD_KRYTYCZNY"


class _ClockedConversation:
    def __init__(self, interlocutor: Interlocutor, clock: RunClock) -> None:
        self._interlocutor = interlocutor
        self._clock = clock

    @property
    def continue_hint(self) -> str:
        return self._interlocutor.continue_hint

    def confirm(self, decision: Decision) -> bool:
        with self._clock.hold():
            return self._interlocutor.confirm(decision)


class _Observation:
    def __init__(self, interlocutor: Interlocutor) -> None:
        self._interlocutor = interlocutor
        self.projection = ProgressProjection()
        self.failed = False

    def start(self) -> None:
        try:
            self._interlocutor.show_progress(self.projection.snapshot)
        except Exception:  # noqa: BLE001 - ADR 0002: awaria podglądu odłącza go, rdzeń zgłasza to neutralną linią
            self.failed = True

    def __call__(self, event: ProgressEvent) -> None:
        try:
            snapshot = self.projection.update(event)
            if self.failed:
                raise RuntimeError("Progress view is detached.")
            self._interlocutor.show_progress(snapshot)
        except Exception:
            self.failed = True
            raise


def _stop_from(error: Exception, process: Process[Any, Any, Any]) -> Stop:
    if isinstance(error, Declined):
        return Stop("declined", error.message)
    if isinstance(error, StopError):
        stop = Stop("stop", error.message, facts=error.facts)
        if error.__cause__ is not None:
            return replace(stop, trace=CallTrace.of(error))
        return stop
    return Stop("unexpected", process.unexpected_failure, CallTrace.of(error))


_DeferredSummary = Callable[[], tuple[Finished, ViewT]]


def _run_engine(
    process: Process[InputsT, SummaryT, ContextT],
    inputs: InputsT,
    context: ContextT,
    view: Callable[[InputsT, SummaryT], ViewT],
) -> _DeferredSummary[ViewT] | Stop:
    try:
        summary = process.execute(inputs, context)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, process)
    return lambda: (process.finished(inputs, summary), view(inputs, summary))


def _build_summary(
    engine_outcome: _DeferredSummary[ViewT] | Stop, *, not_shown: Message
) -> tuple[Finished | Stop, ViewT | None]:
    if isinstance(engine_outcome, Stop):
        return engine_outcome, None
    try:
        return engine_outcome()
    except Exception as error:  # noqa: BLE001 - granica procesu: kończy jako zatrzymanie "after_engine" w wyniku i metrykach
        return Stop("after_engine", not_shown, CallTrace.of(error)), None


def run_process(
    process: Process[InputsT, SummaryT, ContextT],
    inputs: InputsT,
    interlocutor: Interlocutor,
    *,
    view: Callable[[InputsT, SummaryT], ViewT],
    metrics_path: Path,
    context: ContextT,
) -> Outcome[ViewT]:
    dry_run = process.dry_run(inputs)
    mode = RunMode.of(dry_run=dry_run)
    started_at = utc_now().isoformat()
    clock = context.clock
    started = clock.now()
    observation = _Observation(interlocutor)
    observation.start()

    engine_outcome = _run_engine(
        process, inputs, context.engaged(observation, _ClockedConversation(interlocutor, clock)), view
    )
    total_duration_ms = max(0, round((clock.now() - started) * 1000))
    ending, shown = _build_summary(
        engine_outcome,
        not_shown=process.preview.plan_not_shown if process.preview is not None and dry_run else process.summary_not_shown,
    )

    finished = ending if isinstance(ending, Finished) else None
    record = metric_record(
        mode=mode,
        period=inputs.period,
        started_at=started_at,
        total_duration_ms=total_duration_ms,
        phase_durations_ms=(
            finished.phase_durations_ms if finished else observation.projection.snapshot.phase_durations_ms
        ),
        ending=(
            ending.result
            if isinstance(ending, Finished)
            else RecordedStop(kind=ending.stop_kind, code=ending.message.code)
        ),
        counters=finished.counters if finished else {counter.name: 0 for counter in process.counters},
        routes=finished.routes if finished else {},
    )
    technical_notes: list[str] = []
    try:
        MetricsStore(metrics_path, process.counter_names).append(record)
        metrics_saved = True
    except (OSError, UnicodeError, ValueError):
        metrics_saved = False
        technical_notes.append(f"Ostrzeżenie: Nie zapisano metryk; {process.metrics_failure_tail}")
    if observation.failed:
        technical_notes.append(_DETACHED_OBSERVER_NOTE)
    progress = observation.projection.snapshot
    before_saving = not observation.failed and progress.phase_states[ProgressPhase.SAVING] is PhaseState.PENDING

    return Outcome(
        ending=ending,
        view=shown,
        total_duration_ms=total_duration_ms,
        technical_notes=tuple(technical_notes),
        metrics_saved=metrics_saved,
        progress=progress,
        files_unchanged=dry_run or before_saving,
    )
