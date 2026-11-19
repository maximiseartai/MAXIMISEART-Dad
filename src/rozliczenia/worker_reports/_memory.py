"""Pamięć Wpisania raportów (ADR 0028, ADR 0041): dzień wdrożenia, własne wpisy i decyzje taty z ostatniego udanego
zapisu (``SavedState``), z których Wpisanie raportów i Przypomnienia o raporcie liczą dzień raportu.

Pamięć daje tylko jej źródło (``MemorySource``), a jej wartość trzyma ``EnteringMemory``, która ma okno dni i obie
operacje odczytu okna: Wpisanie raportów (``EnteringMemory.enter``) i Przypomnienia o raporcie
(``EnteringMemory.reminders``). INTERMAX okna (``RegisterWindow``) i tokeny okresów z Plikiem zbiorczym czyta proces,
bo plik, folder okresów i Excel zostają poza rdzeniem.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol, TypeAlias, final

from ..activity_legend import ActivityLegend
from ..settlement_period import SettlementPeriod
from . import _operation
from ._model import (
    Kept,
    Login,
    OlderOwnEntries,
    OrderedDay,
    OwnEntries,
    ReadNumber,
    RegisterOrder,
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    RequestedEntry,
    Window,
    WorkerAddresses,
)
from ._reminders import Reminder, ReminderInputs, ReminderSettings, SchedulesInEffect, SentReminder, reminders_due

ClosedPeriods: TypeAlias = Callable[[tuple[SettlementPeriod, ...]], Iterable[str]]
"""Tokeny okresów z Plikiem zbiorczym spośród okresów okna (w procesie ``report_entering.closed_periods``)."""


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
    jak tam), a jej wartość wychodzi tylko jako wynik operacji odczytu okna (``enter``, ``reminders``) i fakty do
    pokazania, więc obie operacje liczą dzień raportu z tej samej pamięci i żadna nie ma wartości, którą mogłaby
    zmienić; podklasa z własną pamięcią nie przechodzi mypy (``final``). ``requested``: decyzja taty z kliknięcia Wpisu
    na życzenie, którą rdzeń dostaje razem z decyzjami z pamięci."""

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

    def window(self, today: date, closed: ClosedPeriods, *, reminders_since: date | None = None) -> Window:
        """Okno dni dnia taty ``today``: od dnia wdrożenia Wpisania z pamięci (przed pierwszym udanym kliknięciem:
        dziś), a z dniem wdrożenia Przypomnień o raporcie (``reminders_since``) od wcześniejszego z tych dni, bo
        Przeniesienie Centrum na dzień sprzed wdrożenia przypomnień dalej zmienia dzień raportu. Dni okresów, których
        tokeny ``closed`` daje spośród okresów okna (``Window.periods``), są zamknięte; błąd ``closed`` przechodzi do
        wołającego."""

        entering = today if self._saved.rollout is None else self._saved.rollout
        since = entering if reminders_since is None else min(reminders_since, entering)
        return Window.of(today, since, closed(Window.periods(today, since)))

    def remembered(self, intermax: RegisterWindow) -> OwnEntries:
        """Pamięć własnych wpisów, którą dostaje rdzeń przy INTERMAX okna ``intermax``: pamięć z pliku sprzed wersji 4
        zamieniona przy odczytanych zleceniach (``OlderOwnEntries.upgraded``), bo rdzeń przyjmuje tylko ``OwnEntries``."""

        memory = self._saved.memory
        return memory.upgraded(intermax.orders) if isinstance(memory, OlderOwnEntries) else memory

    def enter(
        self, window: Window, intermax: RegisterWindow, mails: Sequence[ReportMail], addresses: WorkerAddresses, legend: ActivityLegend
    ) -> ReportsOutcome:
        """Operacja Wpisania raportów (``_operation.enter_reports``) na wejściu odczytu okna z tej pamięci
        (``report_inputs``)."""

        return _operation.enter_reports(self.report_inputs(window, intermax, mails, addresses, legend))

    def reminders(
        self,
        now: datetime,
        window: Window,
        intermax: RegisterWindow,
        mails: Sequence[ReportMail],
        addresses: WorkerAddresses,
        legend: ActivityLegend,
        *,
        sent: Sequence[SentReminder],
        reminded: frozenset[Login],
        settings: ReminderSettings,
        in_effect: SchedulesInEffect,
    ) -> tuple[Reminder, ...]:
        """Przypomnienia o raporcie, które należą się w chwili ``now`` (``_reminders.reminders_due``), z wejścia odczytu
        okna z tej pamięci (``report_inputs``), więc przypomnienie nie idzie za żaden dzień, za który kafelek Wpisania
        liczy raport: przypomnienia z „Wysłanych” ``sent``, loginy Wykonawców, którym przypomnienia idą
        (``reminded``), Ustawienia przypomnień ``settings`` i pory, przy których praca przypomnień sprawdzała
        (``in_effect``)."""

        reports = self.report_inputs(window, intermax, mails, addresses, legend)
        return reminders_due(ReminderInputs(now, reports, sent, reminded, settings, in_effect))

    def report_inputs(
        self, window: Window, intermax: RegisterWindow, mails: Sequence[ReportMail], addresses: WorkerAddresses, legend: ActivityLegend
    ) -> ReportInputs:
        """Jedyne wejście odczytu okna rdzenia raportów, to samo dla Wpisania raportów i Przypomnień o raporcie: INTERMAX
        okna z ``register_window`` i ta pamięć (``remembered``). Dzień raportu zależy od pamięci: numer dopisany przez
        Centrum nie robi z tematu pomylonego, a zlecenie po Przeniesieniu ma w rdzeniu dzień sprzed niego, więc obie
        operacje liczą ten sam dzień raportu tylko z tej samej pamięci; decyzje Wpisu na życzenie zmieniają tylko wpisany
        znak, nie dzień raportu. Dzień wdrożenia Wpisania z pamięci (przed pierwszym kliknięciem: dziś) ogranicza dzień
        wskazany raportu bez dnia w temacie także w oknie przypomnień, które zaczyna się wcześniej
        (``ReportInputs.entering_rollout``)."""

        saved = self._saved
        return ReportInputs(
            mails=mails,
            addresses=addresses,
            orders=intermax.orders,
            window=window,
            memory=self.remembered(intermax),
            kept=saved.kept,
            ordered_days=intermax.ordered_days,
            present=tuple(read for _, read in intermax.present),
            legend=legend,
            requested=saved.requested,
            entering_rollout=window.today if saved.rollout is None else saved.rollout,
        )
