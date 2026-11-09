"""Sekwencer etapów: protokół etapów procesu, Zdarzenia przebiegu i pomiar czasów."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import TypeVar

from .domain import (
    IssueCountReady,
    PhaseEnded,
    PhaseFailed,
    PhaseStarted,
    PlanReady,
    ProgressEvent,
    ProgressObserver,
    ProgressPhase,
    ProgressProtocolError,
    StepReached,
    TemplateResult,
    WorkerEnded,
    WorkerFailed,
    WorkerStarted,
)

ResultT = TypeVar("ResultT")
TemplateResultT = TypeVar("TemplateResultT", bound=TemplateResult)
_PHASE_ORDER = tuple(ProgressPhase)


def _zero(result: object) -> int:
    return 0


def _no_templates(result: object) -> Sequence[str]:
    return ()


def _count(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProgressProtocolError(f"{label} musi być nieujemną liczbą całkowitą.")
    return value


class PhaseRunner:
    """Właściciel protokołu etapów jednego uruchomienia procesu.

    Proces wywołuje cztery etapy w stałej kolejności: ``check``, ``read``,
    ``plan`` i ``save``. Sekwencer wysyła ``PhaseStarted``, ``PhaseEnded`` albo
    jedno ``PhaseFailed`` każdego etapu oraz zdarzenia pośrednie:
    ``IssueCountReady`` po Odczycie danych i ``PlanReady`` po Planowaniu.
    W Zapisywaniu ``each_template`` prowadzi po kolei Szablony pracownika
    Wykonawców z planu i wysyła ich zdarzenia, a proces bez Szablonów (Wycena w
    efenix) zgłasza swoje kroki Zapisywania przez ``step``.

    Funkcje liczące są czystymi funkcjami wyniku etapu; sekwencer wywołuje je
    przed END. Liczba problemów jest łączna dla uruchomienia, a pominięta w
    Planowaniu oznacza wartość z Odczytu danych.

    Sekwencer jest jedynym nadawcą Zdarzeń przebiegu i jedynym miejscem, które
    sprawdza kolejność etapów. Pomyłka to ``ProgressProtocolError`` w miejscu
    wywołania, także bez obserwatora.

    Zegar uruchomienia startuje przy utworzeniu. Awaria obserwatora odłącza go
    do końca uruchomienia i nie zmienia wyniku etapów. Czas etapu jest
    zapisywany także po przerwaniu. ``clock`` to zegar w sekundach, z którego
    sekwencer liczy wszystkie czasy: w Uruchomieniu zegar Uruchomienia
    (``run_clock.RunClock.now``), który stoi w czasie czekania na tatę, więc
    ten czas nie wlicza się do czasów etapów ani do ``elapsed_ms`` zdarzeń.
    """

    def __init__(self, observer: ProgressObserver | None, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self._observer = observer
        self._clock = clock
        self._run_started = clock()
        self._phase_started = self._run_started
        self._next_phase = 0
        self._active_phase: ProgressPhase | None = None
        # Któryś etap tego uruchomienia został przerwany; kolejnego etapu już nie ma.
        self._run_interrupted = False
        # Bieżące Zapisywanie zgłosiło już FAILED zdarzeniem wykonawcy, więc
        # sekwencer nie wysyła drugiego FAILED etapu.
        self._worker_failure_reported = False
        self._issue_count = 0
        self._templates: Sequence[str] = ()
        self._templates_completed = 0
        self._durations_ms: dict[ProgressPhase, int] = {}

    def check(self, operation: Callable[[], ResultT]) -> ResultT:
        return self._run_phase(ProgressPhase.CHECKING, operation)

    def read(
        self,
        operation: Callable[[], ResultT],
        *,
        issue_count: Callable[[ResultT], int] = _zero,
    ) -> ResultT:
        def record_counts(result: ResultT) -> None:
            self._record_issue_count(issue_count(result))

        result = self._run_phase(ProgressPhase.READING, operation, record_counts)
        self._emit(IssueCountReady(elapsed_ms=self.elapsed_ms(), issue_count=self._issue_count))
        return result

    def plan(
        self,
        operation: Callable[[], ResultT],
        *,
        templates: Callable[[ResultT], Sequence[str]] = _no_templates,
        issue_count: Callable[[ResultT], int],
    ) -> ResultT:
        """``templates``: Wykonawcy Szablonów pracownika po kolei."""

        def record_counts(result: ResultT) -> None:
            self._record_issue_count(issue_count(result))
            self._templates = tuple(templates(result))

        result = self._run_phase(ProgressPhase.PLANNING, operation, record_counts)
        self._emit(PlanReady(elapsed_ms=self.elapsed_ms(), template_total=len(self._templates), issue_count=self._issue_count))
        return result

    def save(self, operation: Callable[[], ResultT]) -> ResultT:
        """Zapisywanie; kończy się dopiero po ``each_template`` przez wszystkie Szablony pracownika z planu."""

        def every_template_ended(_result: ResultT) -> None:
            if self._templates_completed != len(self._templates):
                raise ProgressProtocolError(
                    f"Zapisywanie kończy się po {self._templates_completed} z {len(self._templates)} Szablonów pracownika."
                )

        return self._run_phase(ProgressPhase.SAVING, operation, every_template_ended)

    def each_template(self, settle: Callable[[str], TemplateResultT]) -> list[TemplateResultT]:
        """W trwającym Zapisywaniu przetwarza po kolei Szablon pracownika każdego Wykonawcy z planu.

        Wysyła ``WorkerStarted``, wywołuje ``settle`` i wysyła ``WorkerEnded``.
        Wyjątek z ``settle`` to ``WorkerFailed`` zamiast ``PhaseFailed``
        Zapisywania; przechodzi dalej bez zmian.
        """

        if self._active_phase is not ProgressPhase.SAVING:
            raise ProgressProtocolError("Szablony pracownika przetwarza się tylko w trakcie Zapisywania.")
        results: list[TemplateResultT] = []
        for template_index, worker_name in enumerate(self._templates, start=1):
            self._emit(WorkerStarted(worker_name, template_index=template_index, elapsed_ms=self.elapsed_ms()))
            try:
                result = settle(worker_name)
            except Exception:
                self._worker_failure_reported = True
                self._emit(
                    WorkerFailed(
                        worker_name,
                        template_index=template_index,
                        elapsed_ms=self.elapsed_ms(),
                        phase_elapsed_ms=self.phase_elapsed_ms(),
                    )
                )
                raise
            results.append(result)
            self._templates_completed += 1
            self._emit(
                WorkerEnded(
                    worker_name,
                    template_index=template_index,
                    status=result.status,
                    rows=result.rows,
                    elapsed_ms=self.elapsed_ms(),
                    issue_count=self._issue_count,
                )
            )
        return results

    def step(self, label: str, *, worker: str | None = None, done: int = 0, total: int = 0) -> None:
        """W trwającym Zapisywaniu wysyła ``StepReached``: krok ``label``, Wykonawca i ``done`` z ``total`` zleceń."""

        if self._active_phase is not ProgressPhase.SAVING:
            raise ProgressProtocolError("Krok Zapisywania zgłasza się tylko w trakcie Zapisywania.")
        self._emit(
            StepReached(
                label,
                worker=worker,
                done=_count(done, "Liczba zleceń"),
                total=_count(total, "Liczba zleceń"),
                elapsed_ms=self.elapsed_ms(),
            )
        )

    def elapsed_ms(self) -> int:
        """Czas od rozpoczęcia uruchomienia, bez czasu wstrzymania."""

        return self._ms_since(self._run_started)

    def phase_elapsed_ms(self) -> int:
        """Czas od rozpoczęcia bieżącego (ostatniego) etapu."""

        return self._ms_since(self._phase_started)

    def durations_ms(self) -> Mapping[ProgressPhase, int]:
        """Nowa kopia tylko do odczytu czasów etapów zmierzonych do tej chwili."""

        return MappingProxyType(dict(self._durations_ms))

    def _ms_since(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))

    def _run_phase(
        self,
        phase: ProgressPhase,
        operation: Callable[[], ResultT],
        record_counts: Callable[[ResultT], None] | None = None,
    ) -> ResultT:
        self._enter(phase)
        self._phase_started = self._clock()
        self._worker_failure_reported = False
        self._emit(PhaseStarted(phase, elapsed_ms=self.elapsed_ms()))
        try:
            result = operation()
            if record_counts is not None:
                record_counts(result)
        except Exception:
            phase_elapsed_ms = self.phase_elapsed_ms()
            self._durations_ms[phase] = phase_elapsed_ms
            self._active_phase = None
            self._run_interrupted = True
            if not self._worker_failure_reported:
                self._emit(PhaseFailed(phase, elapsed_ms=self.elapsed_ms(), phase_elapsed_ms=phase_elapsed_ms))
            raise
        phase_elapsed_ms = self.phase_elapsed_ms()
        self._durations_ms[phase] = phase_elapsed_ms
        self._active_phase = None
        self._emit(PhaseEnded(phase, elapsed_ms=self.elapsed_ms(), phase_elapsed_ms=phase_elapsed_ms))
        return result

    def _record_issue_count(self, issue_count: int) -> None:
        issue_count = _count(issue_count, "Liczba problemów")
        if issue_count < self._issue_count:
            raise ProgressProtocolError("Liczba problemów uruchomienia nie może się zmniejszyć.")
        self._issue_count = issue_count

    def _enter(self, phase: ProgressPhase) -> None:
        if self._active_phase is not None:
            raise ProgressProtocolError(
                f"Nie można rozpocząć etapu {phase.value} w trakcie etapu {self._active_phase.value}."
            )
        if self._run_interrupted:
            raise ProgressProtocolError(f"Nie można rozpocząć etapu {phase.value} po przerwaniu uruchomienia.")
        expected = _PHASE_ORDER[self._next_phase] if self._next_phase < len(_PHASE_ORDER) else None
        if phase is not expected:
            expected_label = expected.value if expected is not None else "brak, uruchomienie jest zakończone"
            raise ProgressProtocolError(
                f"Etap {phase.value} uruchomiony poza kolejnością; oczekiwano: {expected_label}."
            )
        self._next_phase += 1
        self._active_phase = phase

    def _emit(self, event: ProgressEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception:  # noqa: BLE001 - ADR 0002: awaria obserwatora odłącza go, rdzeń zgłasza to neutralną linią
            self._observer = None
