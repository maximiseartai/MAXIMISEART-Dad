"""Pamięć Wpisania raportów z wartości dla testów rdzenia raportów: obie operacje odczytu okna przez jej interfejs.

``src/`` dostaje pamięć Wpisania tylko z ``ReportState`` pracy, a testy rdzenia składają ją z wartości (``Saved``, źródło
pamięci z gotowym ``SavedState``) razem z tym, co proces przeczytał (``Given``, pola jak wejście odczytu okna), i pytają
``EnteringMemory.enter`` albo ``EnteringMemory.reminders``. Dzień wdrożenia Wpisania pamięci to bez ``rollout``
pierwszy dzień okna, jak w procesie, który czyta okno od dnia wdrożenia z pamięci.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.worker_reports import (
    EnteringMemory,
    Kept,
    Login,
    OrderedDay,
    OwnEntries,
    ReadNumber,
    RegisterOrder,
    RegisterWindow,
    Reminder,
    ReminderSettings,
    ReportMail,
    ReportsOutcome,
    RequestedEntry,
    SavedState,
    SchedulesInEffect,
    SentReminder,
    Window,
    WorkerAddresses,
)


@dataclass(frozen=True)
class Saved:
    """Źródło pamięci Wpisania z gotowej pamięci ``saved``."""

    saved: SavedState

    def load(self) -> SavedState:
        return self.saved


@dataclass(frozen=True)
class Given:
    """Pamięć Wpisania i to, co proces przeczytał: maile, adresy Wykonawców, INTERMAX okna (zlecenia, numery wierszy
    ``present``, Dni uporządkowane), okno dni, Legenda czynności oraz własne wpisy, decyzje „Zostaw moją” i Wpisu na
    życzenie z pamięci, z dniem wdrożenia Wpisania ``rollout`` (``None``: ``window.rollout``)."""

    mails: Sequence[ReportMail]
    addresses: WorkerAddresses
    orders: Sequence[RegisterOrder]
    window: Window
    memory: OwnEntries
    kept: frozenset[Kept]
    present: Sequence[ReadNumber]
    legend: ActivityLegend
    ordered_days: frozenset[OrderedDay] = frozenset()
    requested: frozenset[RequestedEntry] = frozenset()
    rollout: date | None = None

    def entering_memory(self) -> EnteringMemory:
        rollout = self.window.rollout if self.rollout is None else self.rollout
        return EnteringMemory(Saved(SavedState(rollout, self.memory, self.kept, self.requested)))

    def intermax(self) -> RegisterWindow:
        return RegisterWindow(tuple(self.orders), self.ordered_days, tuple(("", number) for number in self.present))


def enter_reports(given: Given) -> ReportsOutcome:
    """Operacja Wpisania raportów na pamięci i odczycie ``given``."""

    return given.entering_memory().enter(given.window, given.intermax(), given.mails, given.addresses, given.legend)


def reminders_due(
    given: Given,
    now: datetime,
    *,
    sent: Sequence[SentReminder],
    reminded: frozenset[Login],
    settings: ReminderSettings,
    in_effect: SchedulesInEffect | None = None,
) -> tuple[Reminder, ...]:
    """Przypomnienia o raporcie, które w chwili ``now`` należą się z pamięci i odczytu ``given``; bez ``in_effect`` pory
    „Wysłanych” to pory z ADR 0030."""

    return given.entering_memory().reminders(
        now,
        given.window,
        given.intermax(),
        given.mails,
        given.addresses,
        given.legend,
        sent=sent,
        reminded=reminded,
        settings=settings,
        in_effect=SchedulesInEffect() if in_effect is None else in_effect,
    )
