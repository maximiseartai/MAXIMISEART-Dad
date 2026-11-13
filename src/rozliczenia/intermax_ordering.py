"""Uporządkowanie INTERMAX: Surowe zlecenia dnia na dole Rejestru zleceń stają się uporządkowanym dniem.

Operacją procesu jest ``order_register()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty
rozpoznania, planu dnia i zapisu na Komunikaty: Sprawdzanie (INTERMAX jest i nie jest otwarty w Excelu), Odczyt
danych (``register_file.read`` i obszary wklejania z rozpoznania arkuszy zleceń, ``paste_areas``), Planowanie
(``raw_orders.recognize`` w każdym obszarze wklejania, odmowa dnia, który już jest Dniem uporządkowanym
(``_ordered_days``), i ``raw_orders.plan_day`` z widokiem na dzisiejszy dzień z ``now``) i Zapisywanie (bajty dnia z
``intermax_file.ordered`` przez podmianę INTERMAX ``intermax_replace`` z Kopią INTERMAX). Nie ma podglądu bez zapisu
ani Decyzji taty. Zatrzymania zgłasza jako ``StopError``, a wynik nie zawiera danych klientów.

Obok procesu, tylko do odczytu: ``register_problem`` dla Diagnozy i ``register_days`` (Dni uporządkowane) dla karty
Uporządkowania INTERMAX w Centrum rozliczeń. Dzień uporządkowany Planowanie i karta rozpoznają jedną regułą
(``_ordered_days``): w każdym obszarze wklejania, przeglądem z granicą 6 dni przed dzisiejszym dniem, a dla wklejonego
dnia sprzed niej w tym dniu. Rozpoznanie arkuszy zleceń proces, Diagnoza i karta tłumaczą na Komunikaty w jednym
miejscu (``paste_areas``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

from openpyxl.utils.cell import get_column_letter

from . import intermax_file, raw_orders, register_file, workbook_files
from . import intermax_messages as messages
from .dad_files import DadFiles
from .domain import ProgressPhase
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
from .register_file import DuplicatedHeaders, MissingHeaders, NoOrderSheet, OrderSheets, PasteArea, RegisterFile
from .workbook_files import WorkbookError
from .workbook_parts import UnsupportedShape
from .run_context import RunContext
from .settlement_period import period_of
from .wall_clock import local_now

__all__ = [
    "OrderingInputs",
    "OrderingSummary",
    "RegisterDay",
    "order_register",
    "paste_areas",
    "register_days",
]

# Karta Uporządkowania INTERMAX pokazuje dziś i 6 dni przed nim oraz późniejsze Dni uporządkowane; tyle dni wstecz
# sięga też przegląd Dni uporządkowanych, więc obejmuje cały okres rozliczeniowy dzisiejszego dnia (7 dni).
_SHOWN_DAYS = 7


@dataclass(frozen=True)
class OrderingInputs:
    """Wejście procesu Uporządkowania INTERMAX: INTERMAX z Ustawień Centrum, folder Kopii i zegar procesu.

    ``period`` to okres dzisiejszej daty z zegara procesu, ustalony przy tworzeniu wejścia, czyli przy starcie:
    Uruchomienie po północy z poniedziałku na wtorek dalej należy do okresu, w którym wystartowało (ADR 0019).
    ``waiting``: zegar w sekundach i przerwa krótkiej ponownej próby podmiany, której odmawia OneDrive, a ``disk``
    kroki podmiany INTERMAX na dysku.
    """

    register_path: Path
    copies_directory: Path
    now: Callable[[], datetime] = local_now
    waiting: Waiting = field(default_factory=Waiting)
    disk: Disk = LOCAL_DISK
    period: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", period_of(self.now().date()).token)


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


def order_register(inputs: OrderingInputs, context: RunContext) -> OrderingSummary:
    """Porządkuje Surowe zlecenia dnia w INTERMAX ``inputs.register_path``.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie; INTERMAX zostaje wtedy nietknięty. Zapisuje podmianą
    INTERMAX (``intermax_replace``) z Kopią INTERMAX w ``inputs.copies_directory`` z nazwą z ``inputs.now()`` i nazywa jej
    fakt Komunikatem Uporządkowania; nieudane usunięcie starszych Kopii to ostrzeżenie: INTERMAX jest już uporządkowany.
    INTERMAX czyta uchwyt plików taty ``context.files``: komórki zakazanych kolumn przeczytanych wierszy zna pamięć
    reguły danych (ADR 0025), a wklejone wiersze, które rozpoznaje Planowanie, i odcisk przeczytanego INTERMAX Kopia
    wejścia Uruchomienia (#842).
    """

    phases = PhaseRunner(context.observer, clock=context.clock.now)
    register_path = inputs.register_path.expanduser().resolve()
    copies_directory, now, waiting, disk = inputs.copies_directory, inputs.now, inputs.waiting, inputs.disk
    files = context.files

    def check() -> None:
        try:
            workbook_files.ensure_available(register_path)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error, messages.ORDERING)) from error

    phases.check(check)

    def read() -> tuple[RegisterFile, tuple[PasteArea, ...]]:
        try:
            register = register_file.read(register_path, files)
        except WorkbookError as error:
            raise StopError(messages.register_unusable(error, messages.ORDERING)) from error
        areas = paste_areas(register)
        if files.copy is not None:
            for area in areas:
                area.copy_paste()
        return register, areas

    register, areas = phases.read(read)

    def plan() -> tuple[PasteArea, RawBlock, DayPlan]:
        found: list[tuple[PasteArea, RawBlock | Obstacle]] = []
        for candidate in areas:
            with _stops(lambda: messages.unsupported_shape(register_path, candidate.sheet), UnsupportedShape):
                recognized = raw_orders.recognize(candidate.rows_from_bottom(), candidate.columns)
            if recognized is not None:
                found.append((candidate, recognized))
        if not found:
            raise StopError(messages.no_raw_orders(register_path, areas[0].sheet))
        if len(found) > 1:
            raise StopError(messages.raw_orders_in_several_sheets(register_path, [area.sheet for area, _ in found]))
        [(area, recognized)] = found
        if not isinstance(recognized, RawBlock):
            raise StopError(_obstacle(register_path, area.sheet, recognized))
        today = now().date()
        if recognized.day in _ordered_days(register_path, areas, min(recognized.day, _earliest_shown(today))):
            first, last = recognized.orders[0].row, recognized.orders[-1].row
            raise StopError(messages.day_already_ordered(register_path, area.sheet, recognized.day, first, last))
        return area, recognized, raw_orders.plan_day(recognized, area.rows_from_bottom(), area.columns, today)

    area, block, day = phases.plan(plan, issue_count=lambda _: 0)

    def save() -> Replaced:
        def written_as_planned(written: bytes) -> None:
            intermax_file.check(register, written, area, block, day)

        with (
            _stops(lambda: messages.unsupported_shape(register_path, area.sheet), UnsupportedShape),
            _stops_unusable(),
        ):
            outcome = replace_register(
                register_path,
                register.content,
                intermax_file.ordered(register, area, block, day),
                written_as_planned,
                before="ordering",
                copies=copies_directory,
                now=now,
                waiting=waiting,
                disk=disk,
            )
        if isinstance(outcome, Refusal):
            raise StopError(messages.refused(outcome, register_path, copies_directory, messages.ORDERING))
        return outcome

    replaced = phases.save(save)
    warnings = [messages.old_copies_kept(copies_directory, messages.ORDERING)] if replaced.old_copies_kept else []
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


@contextmanager
def _stops_unusable() -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(messages.register_unusable(error, messages.ORDERING)) from error


def paste_areas(register: RegisterFile) -> tuple[PasteArea, ...]:
    """Obszary wklejania arkuszy zleceń Rejestru albo ``StopError`` z Komunikatem, którym Odczyt danych mówi, że ich
    nie ma: jedno tłumaczenie rozpoznania dla procesu, Diagnozy i karty, a także dla Odczytu danych Wpisania raportów."""

    match register.order_sheets:
        case DuplicatedHeaders(sheet, labels):
            raise StopError(messages.register_with_duplicated_headers(register.path, sheet, labels))
        case NoOrderSheet() | MissingHeaders():
            raise StopError(messages.no_order_sheet(register.path))
        case OrderSheets() as sheets:
            areas = sheets.paste_areas()
            if not areas:
                raise StopError(messages.no_order_sheet(register.path))
            return areas


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


def register_problem(register_path: Path, files: DadFiles) -> Message | None:
    """Komunikat, którym Sprawdzanie albo Odczyt danych zatrzymałyby Uporządkowanie INTERMAX; ``None``, gdy przechodzą.

    Tylko czyta, uchwytem ``files``, więc Diagnoza sprawdza INTERMAX tą samą regułą co proces. ``register_file.read``
    sprawdza najpierw to samo co Sprawdzanie i daje ten sam Komunikat, więc wystarcza sam.
    """

    try:
        paste_areas(register_file.read(register_path, files))
    except WorkbookError as error:
        return messages.register_unusable(error, messages.ORDERING)
    except StopError as stop:
        return stop.message
    return None


@dataclass(frozen=True)
class RegisterDay:
    """Dzień INTERMAX na karcie Uporządkowania INTERMAX: data i to, czy jest Dniem uporządkowanym."""

    day: date
    ordered: bool


def register_days(register_path: Path, today: date, files: DadFiles) -> tuple[RegisterDay, ...] | Message:
    """Dzień ``today`` i 6 dni przed nim oraz późniejsze Dni uporządkowane, po kolei, każdy ze stanem.

    Tylko czyta, także INTERMAX otwarty w Excelu (jego ostatnią zapisaną wersję). Dzień uporządkowany rozpoznaje ta
    sama reguła co Planowanie przed drugim wklejeniem (``_ordered_days``). Komunikat, gdy INTERMAX nie da się
    odczytać, ten sam co w Odczycie danych i Planowaniu procesu. INTERMAX czyta uchwyt ``files``, którego pamięć reguły
    danych poznaje komórki zakazanych kolumn przeczytanych wierszy.
    """

    try:
        register = register_file.read(register_path, files, despite_excel_lock=True)
    except WorkbookError as error:
        return messages.register_unusable(error, messages.ORDERING)
    since = _earliest_shown(today)
    try:
        ordered = _ordered_days(register.path, paste_areas(register), since)
    except StopError as stop:
        return stop.message
    shown = ordered | {since + timedelta(days=offset) for offset in range(_SHOWN_DAYS)}
    return tuple(RegisterDay(day, day in ordered) for day in sorted(shown))


def _earliest_shown(today: date) -> date:
    return today - timedelta(days=_SHOWN_DAYS - 1)


def _ordered_days(register: Path, areas: tuple[PasteArea, ...], since: date) -> frozenset[date]:
    """Dni uporządkowane od ``since`` w którymkolwiek obszarze wklejania (``raw_orders.ordered_days``).

    Wszystkie arkusze, bo dzień uporządkowany w starszym arkuszu tata może wkleić do nowszego. ``StopError`` z
    Komunikatem Planowania, gdy wierszy arkusza nie da się rozdzielić.
    """

    ordered: set[date] = set()
    for area in areas:
        with _stops(lambda: messages.unsupported_shape(register, area.sheet), UnsupportedShape):
            ordered |= raw_orders.ordered_days(area.rows_from_bottom(), area.columns, since)
    return frozenset(ordered)
