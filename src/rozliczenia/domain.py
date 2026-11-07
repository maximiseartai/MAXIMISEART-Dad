"""Pojęcia procesu rozliczeń: etapy, Zdarzenia przebiegu i Rodzaj Zatrzymania."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Literal, Protocol


class ProgressPhase(StrEnum):
    """Typed phase values while retaining the existing Polish strings."""

    CHECKING = "Sprawdzanie"
    READING = "Odczyt danych"
    PLANNING = "Planowanie"
    SAVING = "Zapisywanie"


class ProgressProtocolError(ValueError):
    """Błąd kodu: Zdarzenie przebiegu poza kolejnością etapów albo Szablonów pracownika."""


PHASES = tuple(phase.value for phase in ProgressPhase)
WorkerStatus = Literal["ZAPISANO", "PUSTY_SZABLON", "PLAN"]
"""Wynik Przetworzenia Szablonu pracownika; szablonu, którego nie da się bezpiecznie zapisać, nie ma w wynikach."""


class TemplateResult(Protocol):
    """Wynik Przetworzenia Szablonu pracownika w tym, co mówi o nim ``WorkerEnded``."""

    @property
    def status(self) -> WorkerStatus: ...

    @property
    def rows(self) -> int: ...


StopKind = Literal["for_tata", "for_maks"]
"""Rodzaj Zatrzymania: przyczynę usuwa tata według Komunikatu (``for_tata``) albo Maks (``for_maks``)."""


@dataclass(frozen=True)
class PhaseStarted:
    """Etap się rozpoczął."""

    phase: ProgressPhase
    elapsed_ms: int


@dataclass(frozen=True)
class PhaseEnded:
    """Etap się zakończył."""

    phase: ProgressPhase
    elapsed_ms: int
    phase_elapsed_ms: int


@dataclass(frozen=True)
class PhaseFailed:
    """Etap został przerwany; uruchomienie nie ma już kolejnych zdarzeń."""

    phase: ProgressPhase
    elapsed_ms: int
    phase_elapsed_ms: int


@dataclass(frozen=True)
class IssueCountReady:
    """Liczba problemów po Odczycie danych."""

    elapsed_ms: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.READING


@dataclass(frozen=True)
class PlanReady:
    """Plan gotowy: liczba Szablonów pracownika i łączna liczba problemów."""

    elapsed_ms: int
    template_total: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.PLANNING


@dataclass(frozen=True)
class WorkerStarted:
    """Przetworzenie Szablonu pracownika ``template_index`` (od 1, po kolei z planu) się rozpoczęło."""

    worker_name: str
    template_index: int
    elapsed_ms: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


@dataclass(frozen=True)
class WorkerEnded:
    """Przetworzenie Szablonu pracownika się zakończyło; ``issue_count`` jest łączna dla uruchomienia."""

    worker_name: str
    template_index: int
    status: WorkerStatus
    rows: int
    elapsed_ms: int
    issue_count: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


@dataclass(frozen=True)
class WorkerFailed:
    """Przetworzenie Szablonu pracownika zostało przerwane; przerywa też Zapisywanie."""

    worker_name: str
    template_index: int
    elapsed_ms: int
    phase_elapsed_ms: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


@dataclass(frozen=True)
class StepReached:
    """Krok Zapisywania procesu bez Szablonów pracownika (Wycena w efenix): co trwa, u którego Wykonawcy i ile z ilu.

    ``worker`` to Wykonawca bieżącego zlecenia (``None`` poza zleceniami), a ``done`` z ``total`` liczą zlecenia, które
    proces już sprawdził w efenix (``total`` 0: krok bez liczenia, np. czekanie na logowanie).
    """

    label: str
    worker: str | None
    done: int
    total: int
    elapsed_ms: int
    phase: ClassVar[ProgressPhase] = ProgressPhase.SAVING


ProgressEvent = (
    PhaseStarted
    | PhaseEnded
    | PhaseFailed
    | IssueCountReady
    | PlanReady
    | WorkerStarted
    | WorkerEnded
    | WorkerFailed
    | StepReached
)
"""Zdarzenie przebiegu (GLOSSARY); każdy rodzaj ma tylko swoje pola, a wysyła je tylko ``PhaseRunner``."""

ProgressObserver = Callable[[ProgressEvent], None]
