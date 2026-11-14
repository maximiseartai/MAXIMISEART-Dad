"""Kontrakt Tablicy okresów: okresy, ich Droga i następny krok, otwarcie plików okresu."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model, PeriodProcessKey
from rozliczenia.period_folder import PeriodPlace, PeriodStatus


StepAction = Literal["prepare_collective_file", "price_in_efenix", "create_worker_settlements"]
"""Krok okresu, który robi proces."""


class ProcessStep(Model):
    """Krok okresu, który robi proces ``process``; ``preview_hint`` to podpowiedź „Podgląd bez zapisu” tego procesu, a
    ``None`` ma proces bez podglądu (Wycena w efenix)."""

    action: StepAction
    process: PeriodProcessKey
    label: str
    hint: str
    preview_hint: str | None


class FillStep(Model):
    """Uzupełnienie w Excelu: tata robi je w Excelu, Centrum prowadzi na podsumowanie Uzupełnienia pliku zbiorczego;
    ``then`` to krok po nim, Wycena w efenix."""

    action: Literal["fill_collective_file"]
    label: str
    hint: str
    then: ProcessStep


class ClosedStep(Model):
    """Okres jest zamknięty: następnego kroku nie robi żaden proces."""

    action: Literal["none"]
    label: str
    hint: str


NextStep = Annotated[ProcessStep | FillStep | ClosedStep, Field(discriminator="action")]


PathStage = Literal["done", "now", "later", "not_done"]


class PathStep(Model):
    """Krok Drogi okresu: ``now`` to pierwszy niezrobiony krok okresu otwartego, ``not_done`` krok, którego okres
    zamknięty nie zrobił (Wycena w efenix bez wyniku OK)."""

    label: str
    stage: PathStage


class BoardFile(Model):
    """Plik albo folder okresu, który Tablica okresów otwiera: ``label`` to jego nazwa z GLOSSARY, a ``count`` liczba
    Rozliczeń pracownika w istniejącym Folderze rozliczeń pracowników (``None`` przy innym miejscu i bez folderu)."""

    target: PeriodPlace
    label: str
    exists: bool
    count: int | None


BoardPlace = Literal["recent", "older", "not_started"]
"""Miejsce okresu na Tablicy okresów: ``recent`` widać od razu (bieżący okres i 4 poprzednie wiersze), ``older`` po
„Pokaż wszystkie”, ``not_started`` (wtorek po dzisiejszym dniu taty) nigdy."""


class PeriodRow(Model):
    """Jeden okres Tablicy okresów, wyliczony przy każdym odczycie z plików i z Historii Wyceny w efenix.

    ``files``: każde miejsce okresu (``PeriodPlace``) po kolei.
    """

    token: str
    tuesday: date
    monday: date
    status: PeriodStatus
    status_label: str
    files: list[BoardFile]
    last_complete: bool
    board_place: BoardPlace
    fillable: bool
    """Plik zbiorczy jest przygotowany, więc „Uzupełnij” prowadzi na podsumowanie jego Uzupełnienia."""
    path: list[PathStep]
    next_step: NextStep
    secondary_step: ProcessStep | None
    """Krok osiągalny obok następnego: Przebieg rozliczeń przed zaliczoną Wyceną w efenix; ``None``: żadnego."""


class BoardNotSet(Model):
    state: Literal["not_set"]


class BoardMissing(Model):
    state: Literal["missing"]
    name: str


class BoardReady(Model):
    """Okresy od najnowszego; ``last_prepared_period`` to najnowszy okres z Plikiem zbiorczym."""

    state: Literal["ready"]
    periods: list[PeriodRow]
    last_prepared_period: str | None


PeriodBoard = Annotated[BoardNotSet | BoardMissing | BoardReady, Field(discriminator="state")]


class OpenRequest(Model):
    """Co otworzyć w okresie; ścieżkę wylicza serwer z folderu okresów, nigdy z żądania."""

    target: PeriodPlace


class WorkerSettlementRequest(Model):
    """Którego Wykonawcy Rozliczenie pracownika otworzyć; ścieżkę wylicza serwer z Folderu okresu."""

    worker: str
