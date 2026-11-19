"""Pamięć Wpisania raportów (ADR 0028, ADR 0041): dzień wdrożenia, własne wpisy i decyzje taty z ostatniego udanego
zapisu (``SavedState``), z których Wpisanie raportów i Przypomnienia o raporcie liczą dzień raportu.

Pamięć daje tylko jej źródło (``MemorySource``), a jej wartość trzyma ``EnteringMemory``. INTERMAX okna
(``RegisterWindow``) czyta proces Wpisania raportów, bo plik i Excel zostają poza rdzeniem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol, final

from ..activity_legend import ActivityLegend
from ._model import (
    Kept,
    OlderOwnEntries,
    OrderedDay,
    OwnEntries,
    ReadNumber,
    RegisterOrder,
    ReportInputs,
    ReportMail,
    RequestedEntry,
    Window,
    WorkerAddresses,
)


@dataclass(frozen=True)
class SavedState:
    """Pamięć z ostatniego udanego zapisu: dzień wdrożenia (``None``: jeszcze żadnego udanego kliknięcia), własne
    wpisy (``OlderOwnEntries`` z pliku sprzed wersji 4) i decyzje taty Wpisu na życzenie (``requested``), a do tego
    decyzje taty „Zostaw moją” (``kept``)."""

    rollout: date | None
    memory: OwnEntries | OlderOwnEntries
    kept: frozenset[Kept] = frozenset()
    requested: frozenset[RequestedEntry] = frozenset()


class MemorySource(Protocol):
    def load(self) -> SavedState:
        """Pamięć z ostatniego udanego zapisu; błąd odczytu źródła przechodzi do tego, kto buduje ``EnteringMemory``."""
        ...


@dataclass(frozen=True)
class RegisterWindow:
    """INTERMAX okna dla rdzenia raportów: uporządkowane zlecenia i Dni uporządkowane od ``Window.start`` oraz numer
    każdego przeczytanego wiersza od ``Window.numbers_since`` z nazwą arkusza (``ReportInputs``)."""

    orders: tuple[RegisterOrder, ...]
    ordered_days: frozenset[OrderedDay]
    present: tuple[tuple[str, ReadNumber], ...]


@final
class EnteringMemory:
    """Pamięć Wpisania raportów, z której Wpisanie raportów i Przypomnienia o raporcie liczą dzień raportu. Powstaje
    tylko z ``MemorySource.load`` (w procesie ``ReportState.load``, ze ``StateUnreadable`` i ``DecisionsUnreadable``
    jak tam), a jej wartość wychodzi tylko jako wejście odczytu okna (``report_inputs``) i fakty do pokazania, więc obie
    operacje liczą dzień raportu z tej samej pamięci i żadna nie ma wartości, którą mogłaby zmienić; podklasa z własną
    pamięcią nie przechodzi mypy (``final``). ``requested``: decyzja taty z kliknięcia Wpisu na
    życzenie, którą rdzeń dostaje razem z decyzjami z pamięci."""

    __slots__ = ("_saved",)

    def __init__(self, source: MemorySource, requested: RequestedEntry | None = None) -> None:
        saved = source.load()
        self._saved = saved if requested is None else replace(saved, requested=saved.requested | {requested})

    @property
    def rollout(self) -> date | None:
        """Dzień wdrożenia Wpisania (``None``: jeszcze żadnego udanego kliknięcia)."""
        return self._saved.rollout

    @property
    def kept(self) -> frozenset[Kept]:
        """Decyzje taty „Zostaw moją” z chwili odczytu pamięci."""
        return self._saved.kept

    @property
    def requested(self) -> frozenset[RequestedEntry]:
        """Decyzje taty Wpisu na życzenie z pamięci, z decyzją kliknięcia."""
        return self._saved.requested

    def report_inputs(
        self, window: Window, intermax: RegisterWindow, mails: Sequence[ReportMail], addresses: WorkerAddresses, legend: ActivityLegend
    ) -> ReportInputs:
        """Jedyne wejście odczytu okna rdzenia raportów, to samo dla Wpisania raportów i Przypomnień o raporcie: INTERMAX
        okna z ``register_window`` i ta pamięć (pamięć z pliku sprzed wersji 4 zamieniona przy odczytanych zleceniach,
        ``OlderOwnEntries.upgraded``). Dzień raportu zależy od pamięci: numer dopisany przez Centrum nie robi z tematu
        pomylonego, a zlecenie po Przeniesieniu ma w rdzeniu dzień sprzed niego, więc obie operacje liczą ten sam dzień
        raportu tylko z tej samej pamięci; decyzje Wpisu na życzenie zmieniają tylko wpisany znak, nie dzień raportu.
        Dzień wdrożenia Wpisania z pamięci (przed pierwszym kliknięciem: dziś) ogranicza dzień wskazany raportu bez dnia
        w temacie także w oknie przypomnień, które zaczyna się wcześniej (``ReportInputs.entering_rollout``)."""

        saved = self._saved
        memory = saved.memory.upgraded(intermax.orders) if isinstance(saved.memory, OlderOwnEntries) else saved.memory
        return ReportInputs(
            mails=mails,
            addresses=addresses,
            orders=intermax.orders,
            window=window,
            memory=memory,
            kept=saved.kept,
            ordered_days=intermax.ordered_days,
            present=tuple(read for _, read in intermax.present),
            legend=legend,
            requested=saved.requested,
            entering_rollout=window.today if saved.rollout is None else saved.rollout,
        )
