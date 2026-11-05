"""Uporządkowanie INTERMAX: Surowe zlecenia dnia na dole Rejestru zleceń stają się uporządkowanym dniem.

Operacją procesu jest ``order_register()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty
rozpoznania, planu dnia i zapisu na Komunikaty: Sprawdzanie (INTERMAX jest i nie jest otwarty w Excelu), Odczyt
danych (``intermax_file.Register``), Planowanie (``raw_orders.recognize`` w każdym arkuszu zleceń, odmowa dnia,
który już jest Dniem uporządkowanym (``_ordered_days``), i ``raw_orders.plan_day`` z widokiem na dzisiejszy dzień z
``now``) i Zapisywanie (bajty dnia z
``intermax_file.Register.ordered`` przez podmianę INTERMAX ``intermax_replace`` z Kopią INTERMAX). Nie ma podglądu
bez zapisu ani Decyzji taty. Zatrzymania zgłasza jako ``StopError``, a wynik nie zawiera danych klientów.

Obok procesu, tylko do odczytu: ``register_problem`` dla Diagnozy i ``register_days`` (Dni uporządkowane) dla karty
Uporządkowania INTERMAX w Centrum rozliczeń. Dzień uporządkowany Planowanie i karta rozpoznają jedną regułą
(``_ordered_days``): w każdym arkuszu zleceń, przeglądem z granicą 6 dni przed dzisiejszym dniem, a dla wklejonego
dnia sprzed niej w tym dniu.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

from openpyxl.utils.cell import get_column_letter

from . import raw_orders, workbook_files
from . import intermax_messages as messages
from .client_data import ForbiddenValues
from .domain import ProgressObserver, ProgressPhase
from .input_copy import InputCopy
from .intermax_file import OrderSheet, Register, UnsupportedShape
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Replaced, Waiting, replace_register
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .raw_orders import (
    AboveOrdered,
    DayPlan,
    Obstacle,
    OrderKind,
    RawBlock,
    SeveralDays,
    Undated,
    WithoutWorker,
)
from .workbook_files import WorkbookError

__all__ = ["OrderingSummary", "RegisterDay", "order_register", "register_days"]

# Karta Uporządkowania INTERMAX pokazuje dziś i 6 dni przed nim oraz późniejsze Dni uporządkowane; tyle dni wstecz
# sięga też przegląd Dni uporządkowanych, więc obejmuje cały okres rozliczeniowy dzisiejszego dnia (7 dni).
_SHOWN_DAYS = 7


@dataclass
class OrderingSummary:
    """Podsumowanie Uporządkowania INTERMAX bez danych klientów: dzień, liczby zleceń i Wykonawców, Kopia i Wpisy.

    ``entries``: operator z reguły taty → wiersze INTERMAX zleceń z Wpisem urządzenia i czynności INTERMAX.
    ``without_entry``: wiersz INTERMAX i nazwa operatora z aplikacji (``None``: puste ``CZYNNOŚCI``) każdej
    instalacji hurt bez Wpisu.
    """

    day: date
    order_count: int
    worker_count: int
    copy_name: str
    entries: Mapping[str, tuple[int, ...]]
    without_entry: tuple[tuple[int, str | None], ...]
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))


@contextmanager
def _stops(explain: Callable[[], Message], *errors: type[Exception]) -> Iterator[None]:
    try:
        yield
    except errors as error:
        raise StopError(explain()) from error


def order_register(
    register_path: Path,
    copies_directory: Path,
    *,
    now: Callable[[], datetime],
    waiting: Waiting,
    disk: Disk = LOCAL_DISK,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
    forbidden: ForbiddenValues | None = None,
    copy: InputCopy | None = None,
) -> OrderingSummary:
    """Porządkuje Surowe zlecenia dnia w INTERMAX ``register_path``.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; INTERMAX zostaje wtedy nietknięty. Zapisuje podmianą
    INTERMAX (``intermax_replace``) z Kopią INTERMAX w ``copies_directory`` z nazwą z ``now()`` i nazywa jej fakt
    Komunikatem Uporządkowania; nieudane usunięcie starszych Kopii to ostrzeżenie: INTERMAX jest już uporządkowany.
    ``clock`` to zegar w sekundach, z którego liczone są czasy etapów, ``waiting`` zegar i przerwa krótkiej ponownej
    próby podmiany, której odmawia OneDrive, a ``disk`` kroki podmiany na dysku. Komórki zakazanych kolumn
    przeczytanych wierszy poznaje ``forbidden`` (reguła danych, ADR 0025), a wklejone wiersze, które rozpoznaje
    Planowanie, i odcisk przeczytanego INTERMAX Kopia wejścia Uruchomienia ``copy`` (#842).
    """

    phases = PhaseRunner(observer, clock=clock)
    register_path = register_path.expanduser().resolve()

    def check() -> None:
        try:
            workbook_files.ensure_available(register_path)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error)) from error

    phases.check(check)

    def read() -> Register:
        try:
            register = Register.read(register_path, forbidden=forbidden, copy=copy)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error)) from error
        if not register.order_sheets:
            raise StopError(messages.no_order_sheet(register_path))
        return register

    register = phases.read(read)

    def plan() -> tuple[OrderSheet, RawBlock, DayPlan]:
        found: list[tuple[OrderSheet, RawBlock | Obstacle]] = []
        for candidate in register.order_sheets:
            with _stops(lambda: messages.unsupported_shape(register_path, candidate.name), UnsupportedShape):
                recognized = raw_orders.recognize(candidate.rows_from_bottom(), candidate.columns)
            if recognized is not None:
                found.append((candidate, recognized))
        if not found:
            raise StopError(messages.no_raw_orders(register_path, register.order_sheets[0].name))
        if len(found) > 1:
            raise StopError(messages.raw_orders_in_several_sheets(register_path, [sheet.name for sheet, _ in found]))
        [(sheet, recognized)] = found
        if not isinstance(recognized, RawBlock):
            raise StopError(_obstacle(register_path, sheet.name, recognized))
        today = now().date()
        if recognized.day in _ordered_days(register, min(recognized.day, _earliest_shown(today))):
            first, last = recognized.orders[0].row, recognized.orders[-1].row
            raise StopError(messages.day_already_ordered(register_path, sheet.name, recognized.day, first, last))
        return sheet, recognized, raw_orders.plan_day(recognized, sheet.rows_from_bottom(), sheet.columns, today)

    sheet, block, day = phases.plan(plan, issue_count=lambda _: 0)

    def save() -> Replaced:
        def written_as_planned(written: bytes) -> None:
            register.check(written, sheet, block, day)

        with _stops(lambda: messages.unsupported_shape(register_path, sheet.name), UnsupportedShape):
            outcome = replace_register(
                register_path,
                register.content,
                register.ordered(sheet, block, day),
                written_as_planned,
                before="ordering",
                copies=copies_directory,
                now=now,
                waiting=waiting,
                disk=disk,
            )
        if isinstance(outcome, Refusal):
            raise StopError(_refused(outcome, register_path, copies_directory))
        return outcome

    replaced = phases.save(save)
    warnings = [messages.old_copies_kept(copies_directory)] if replaced.old_copies_kept else []
    entries: dict[str, list[int]] = {}
    for placement in day.placements:
        if placement.entry is not None:
            entries.setdefault(placement.entry.operator, []).append(placement.row)
    without_entry = tuple(
        (placement.row, placement.order.operator)
        for placement in day.placements
        if placement.entry is None and placement.order.kind is OrderKind.WHOLESALE_INSTALLATION
    )
    frozen = MappingProxyType({operator: tuple(rows) for operator, rows in entries.items()})
    summary = OrderingSummary(
        day.day, len(day.placements), day.worker_count, replaced.copy.path.name, frozen, without_entry, warnings
    )
    return replace(summary, phase_durations_ms=phases.durations_ms())


def _refused(refusal: Refusal, register: Path, copies: Path) -> Message:
    match refusal:
        case Refusal.EXCEL_HOLDS:
            return messages.register_open(register)
        case Refusal.ONEDRIVE_HOLDS:
            return messages.register_syncing(register)
        case Refusal.WRITE_FAILED:
            return messages.register_write_failed(register)
        case Refusal.WRITE_MISMATCH:
            return messages.write_check_failed(register)
        case Refusal.COPY_FAILED | Refusal.COPY_EXISTS:
            return messages.copy_failed(copies)


def _obstacle(register: Path, sheet: str, obstacle: Obstacle) -> Message:
    match obstacle:
        case AboveOrdered(row, ordered_row):
            return messages.raw_order_above_ordered(register, sheet, row, ordered_row)
        case Undated(row, column):
            return messages.raw_order_without_value(register, sheet, row, get_column_letter(column), worker=False)
        case WithoutWorker(row, column):
            return messages.raw_order_without_value(register, sheet, row, get_column_letter(column), worker=True)
        case SeveralDays(days, first_row, last_row):
            return messages.several_days(register, sheet, days, first_row, last_row)


def register_problem(register_path: Path) -> Message | None:
    """Komunikat, którym Sprawdzanie albo Odczyt danych zatrzymałyby Uporządkowanie INTERMAX; ``None``, gdy przechodzą.

    Tylko czyta, więc Diagnoza sprawdza INTERMAX tą samą regułą co proces. ``Register.read`` sprawdza najpierw to
    samo co Sprawdzanie i daje ten sam Komunikat, więc wystarcza sam.
    """

    try:
        register = Register.read(register_path)
    except WorkbookError as error:
        return messages.register_unusable(error)
    return None if register.order_sheets else messages.no_order_sheet(register_path)


@dataclass(frozen=True)
class RegisterDay:
    """Dzień INTERMAX na karcie Uporządkowania INTERMAX: data i to, czy jest Dniem uporządkowanym."""

    day: date
    ordered: bool


def register_days(
    register_path: Path, today: date, forbidden: ForbiddenValues | None = None
) -> tuple[RegisterDay, ...] | Message:
    """Dzień ``today`` i 6 dni przed nim oraz późniejsze Dni uporządkowane, po kolei, każdy ze stanem.

    Tylko czyta, także INTERMAX otwarty w Excelu (jego ostatnią zapisaną wersję). Dzień uporządkowany rozpoznaje ta
    sama reguła co Planowanie przed drugim wklejeniem (``_ordered_days``). Komunikat, gdy INTERMAX nie da się
    odczytać, ten sam co w Odczycie danych i Planowaniu procesu. Komórki zakazanych kolumn przeczytanych wierszy
    poznaje ``forbidden``.
    """

    try:
        register = Register.read(register_path, despite_excel_lock=True, forbidden=forbidden)
    except WorkbookError as error:
        return messages.register_unusable(error)
    if not register.order_sheets:
        return messages.no_order_sheet(register_path)
    since = _earliest_shown(today)
    try:
        ordered = _ordered_days(register, since)
    except StopError as stop:
        return stop.message
    shown = ordered | {since + timedelta(days=offset) for offset in range(_SHOWN_DAYS)}
    return tuple(RegisterDay(day, day in ordered) for day in sorted(shown))


def _earliest_shown(today: date) -> date:
    return today - timedelta(days=_SHOWN_DAYS - 1)


def _ordered_days(register: Register, since: date) -> frozenset[date]:
    """Dni uporządkowane od ``since`` w którymkolwiek arkuszu zleceń (``raw_orders.ordered_days``).

    Wszystkie arkusze, bo dzień uporządkowany w starszym arkuszu tata może wkleić do nowszego. ``StopError`` z
    Komunikatem Planowania, gdy wierszy arkusza nie da się rozdzielić.
    """

    ordered: set[date] = set()
    for sheet in register.order_sheets:
        with _stops(lambda: messages.unsupported_shape(register.path, sheet.name), UnsupportedShape):
            ordered |= raw_orders.ordered_days(sheet.rows_from_bottom(), sheet.columns, since)
    return frozenset(ordered)
