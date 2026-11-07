"""Pojęcia i wyniki procesu rozliczeń."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Literal

from .inea_only_quantities import Cleared
from .message import Message
from .order_facts import CollectiveOrders
from .write_routes import Route, RouteCounts, TemplateKind


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
StopKind = Literal["for_tata", "for_maks"]
"""Rodzaj Zatrzymania: przyczynę usuwa tata według Komunikatu (``for_tata``) albo Maks (``for_maks``)."""


@dataclass(frozen=True)
class PlannedWorkerResult:
    """Bezpieczny wynik dla jednego szablonu w Podglądzie bez zapisu: nic nie powstało, więc bez drogi zapisu."""

    worker_name: str
    output_file: Path
    rows: int

    @property
    def status(self) -> Literal["PLAN", "PUSTY_SZABLON"]:
        return "PLAN" if self.rows else "PUSTY_SZABLON"


@dataclass(frozen=True)
class SavedWorkerResult:
    """Bezpieczny wynik dla jednego zapisanego szablonu; ``route`` to droga zapisu Rozliczenia pracownika."""

    worker_name: str
    output_file: Path
    rows: int
    route: Route

    @property
    def status(self) -> Literal["ZAPISANO", "PUSTY_SZABLON"]:
        return "ZAPISANO" if self.rows else "PUSTY_SZABLON"


WorkerResult = PlannedWorkerResult | SavedWorkerResult
"""Wynik Przetworzenia Szablonu pracownika; tylko zapisany ma drogę zapisu, a ``status`` wynika z liczby wierszy."""


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


@dataclass
class SettlementSummary:
    """Podsumowanie operacyjne; z treści Wierszy danych tylko kolumny dozwolone regułą prywatności (``order_facts``)."""

    period: str
    source_file: Path
    target_directory: Path
    orders: CollectiveOrders = ()
    """Dozwolona treść każdego Wiersza danych, który Przebieg wczytał: dla Kontroli ilości w Centrum."""
    inea_only_cleared: Cleared = field(default_factory=lambda: MappingProxyType({}))
    """Liczba wyczyszczonych komórek Ilości tylko dla INEA w każdej kolumnie: tylko dla Logów Uruchomienia."""
    results: list[WorkerResult] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    """Ostrzeżenia Podglądu bez zapisu z katalogu Przebiegu rozliczeń; Przebieg z zapisem zatrzymuje się na nich."""
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def written_count(self) -> int:
        return sum(result.status == "ZAPISANO" for result in self.results)

    @property
    def planned_count(self) -> int:
        return sum(result.status == "PLAN" for result in self.results)

    @property
    def empty_count(self) -> int:
        return sum(result.status == "PUSTY_SZABLON" for result in self.results)

    @property
    def total_rows(self) -> int:
        return sum(result.rows for result in self.results)

    @property
    def template_count(self) -> int:
        return len(self.results)

    @property
    def routes(self) -> RouteCounts:
        return Counter(
            (TemplateKind.WORKER_SETTLEMENT, result.route)
            for result in self.results
            if isinstance(result, SavedWorkerResult)
        )

    @property
    def ok(self) -> bool:
        return not self.warnings
