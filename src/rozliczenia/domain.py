"""Pojęcia procesu rozliczeń: tryb Uruchomienia, etapy, Zdarzenia przebiegu i Rodzaj Zatrzymania."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final, Literal, Protocol


class RunMode(StrEnum):
    """Tryb Uruchomienia procesu: zapis albo Podgląd bez zapisu. Jedyny słownik trybu: rekord metryk, dziennik
    Centrum, Zgłoszenie, kontrakt Centrum, Logi Uruchomienia i dziennik działań taty niosą jego wartość, a słowo
    (``word``) pokazują Uwaga taty i jej okno."""

    RUN = "RUN"
    DRY_RUN = "DRY-RUN"

    @classmethod
    def of(cls, *, dry_run: bool) -> RunMode:
        return cls.DRY_RUN if dry_run else cls.RUN

    @classmethod
    def stored(cls, value: object) -> object:
        """Tryb z pliku na dysku taty: plik sprzed schematu Logów 3 (Logi schematu 1–2, plik ostatniego startu
        schematu 1, dziennik Wyceny w efenix i dziennik działań taty sprzed niego) ma słowo trybu zamiast wartości;
        inną wartość zostawia walidacji."""

        return _BY_OLD_WORD.get(value, value) if isinstance(value, str) else value

    @property
    def dry_run(self) -> bool:
        return self is RunMode.DRY_RUN

    @property
    def word(self) -> str:
        return "podgląd" if self.dry_run else "zapis"


_BY_OLD_WORD: Final = {mode.word: mode for mode in RunMode}


class ProgressPhase(StrEnum):
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
    phase: ProgressPhase
    elapsed_ms: int


@dataclass(frozen=True)
class PhaseEnded:
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
