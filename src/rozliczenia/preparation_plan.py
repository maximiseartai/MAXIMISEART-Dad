"""Wybór zleceń okresu, reguły zleceń i Reguły ilości w Przygotowaniu pliku zbiorczego (etap Planowanie).

Zakres okresu w Rejestrze to wiersze od pierwszego do ostatniego zlecenia
okresu w arkuszu ze zleceniami. W tym zakresie wiersz z danymi bez poprawnej
daty zatrzymuje proces, a całkowicie puste wiersze są liczone jako pominięte.
Moduł wewnętrzny Przygotowania pliku zbiorczego; operacją publiczną pozostaje
``collective_preparation.prepare_collective_file()``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import preparation_messages as messages
from .message import StopError
from .preparation_register import cell_value
from .register_file import RegisterSheet
from .register_columns import ACTIVITIES, CONTRACT, DATE, DEVICES, SUCCESSFUL, WORKER
from .quantity_rules import OrderContent, RuleResult, evaluate
from .settlement_period import SettlementPeriod
from .workbook_files import RegisterRow, cell_datetime, is_blank
from .text import normalize_text

_SUCCESSFUL_VALUE = "tak"
_UNSUCCESSFUL_VALUE = "nie"
_BLANK_WORKER_LABEL = "(pusty)"


@dataclass(frozen=True)
class PeriodOrder:
    """Zlecenie okresu: wiersz Rejestru i jego data z ``DATA GODZ. POCZ.``."""

    register_row: RegisterRow
    started: datetime

    @property
    def row_number(self) -> int:
        return self.register_row.number

    @property
    def is_successful(self) -> bool:
        return normalize_text(cell_value(self.register_row, SUCCESSFUL)) == _SUCCESSFUL_VALUE


@dataclass(frozen=True)
class CollectiveRow:
    """Wiersz danych Pliku zbiorczego: Zlecenie skuteczne i wynik Reguł ilości dla jego treści."""

    order: PeriodOrder
    rule_result: RuleResult

    @classmethod
    def of(cls, order: PeriodOrder) -> CollectiveRow:
        row = order.register_row
        content = OrderContent.of(
            cell_value(row, CONTRACT), cell_value(row, DEVICES), cell_value(row, ACTIVITIES), order.started
        )
        return cls(order, evaluate(content))


@dataclass(frozen=True)
class IncompletePeriod:
    """Fakt planu: ostatnie zlecenie okresu jest sprzed poniedziałku okresu, więc Rejestr może nie mieć wszystkich."""

    last_order_day: date
    monday: date


@dataclass(frozen=True)
class Plan:
    """Plan okresu; ``collective_rows`` to Zlecenia skuteczne w kolejności Rejestru, tak jak trafią do Pliku zbiorczego."""

    period: SettlementPeriod
    sheet: str
    orders: list[PeriodOrder]
    collective_rows: list[CollectiveRow]
    skipped_empty_rows: int

    @property
    def orders_per_day(self) -> dict[date, int]:
        first_day = self.period.start.date()
        counts = {first_day + timedelta(days=offset): 0 for offset in range(7)}
        for order in self.orders:
            counts[order.started.date()] += 1
        return counts

    @property
    def incomplete_period(self) -> IncompletePeriod | None:
        """Niepełny okres, gdy żadne zlecenie okresu nie jest z poniedziałku."""

        last_order_day = max(order.started.date() for order in self.orders)
        if last_order_day >= self.period.monday:
            return None
        return IncompletePeriod(last_order_day, self.period.monday)


def plan_period_orders(
    register_path: Path,
    sheets: Sequence[RegisterSheet],
    period: SettlementPeriod,
    config_path: Path,
    worker_mapping: Mapping[str, str],
) -> Plan:
    """Wybiera zlecenia okresu po dacie, w kolejności Rejestru, sprawdza reguły zleceń i stosuje Reguły ilości."""

    register = _period_sheet(register_path, sheets, period)
    orders: list[PeriodOrder] = []
    undated_rows: list[int] = []
    for row in register.register_rows:
        started = cell_datetime(cell_value(row, DATE))
        if started is None:
            undated_rows.append(row.number)
        elif period.contains(started):
            orders.append(PeriodOrder(row, started))
    if not orders:
        raise StopError(messages.no_period_orders(register_path, register.name, period.token))
    first_row, last_row = orders[0].row_number, orders[-1].row_number
    undated_between = [row for row in undated_rows if first_row < row < last_row]
    if undated_between:
        raise StopError(messages.rows_without_date(register_path, register.name, undated_between))
    _check_successful_values(register_path, register, orders)
    unknown_workers = _unknown_workers(orders, worker_mapping)
    if unknown_workers:
        raise StopError(messages.unknown_workers(register_path, register.name, config_path, unknown_workers))
    skipped_empty_rows = sum(1 for row in register.empty_rows if first_row < row < last_row)
    collective_rows = [CollectiveRow.of(order) for order in orders if order.is_successful]
    return Plan(period, register.name, orders, collective_rows, skipped_empty_rows)


def _in_period(row: RegisterRow, period: SettlementPeriod) -> bool:
    started = cell_datetime(cell_value(row, DATE))
    return started is not None and period.contains(started)


def _check_successful_values(register_path: Path, register: RegisterSheet, orders: Sequence[PeriodOrder]) -> None:
    """Zatrzymanie, gdy zlecenie okresu nie ma ``tak`` ani ``nie`` w ``SKUTECZNE``: puste komórki i inne wartości."""

    empty_rows: list[int] = []
    other_values: list[messages.CellContent] = []
    for order in orders:
        value = cell_value(order.register_row, SUCCESSFUL)
        if normalize_text(value) in (_SUCCESSFUL_VALUE, _UNSUCCESSFUL_VALUE):
            continue
        if is_blank(value):
            empty_rows.append(order.row_number)
        else:
            other_values.append(messages.CellContent(order.row_number, value))
    if empty_rows or other_values:
        raise StopError(
            messages.invalid_successful_values(
                register_path, register.name, register.column_letter(SUCCESSFUL), empty_rows, other_values
            )
        )


def _period_sheet(register_path: Path, sheets: Sequence[RegisterSheet], period: SettlementPeriod) -> RegisterSheet:
    """Jedyny arkusz Rejestru ze zleceniami okresu; bez takiego arkusza pierwszy arkusz ze zleceniami."""

    with_orders = [sheet for sheet in sheets if any(_in_period(row, period) for row in sheet.register_rows)]
    if len(with_orders) > 1:
        raise StopError(
            messages.period_orders_in_many_sheets(register_path, [sheet.name for sheet in with_orders], period.token)
        )
    return (with_orders or list(sheets))[0]


def _unknown_workers(
    orders: Sequence[PeriodOrder], worker_mapping: Mapping[str, str]
) -> list[tuple[str, list[int]]]:
    """Wykonawcy Zleceń skutecznych spoza konfiguracji wykonawców, z numerami wierszy Rejestru."""

    unknown: dict[str, tuple[str, list[int]]] = {}
    for order in orders:
        worker = cell_value(order.register_row, WORKER)
        key = normalize_text(worker)
        if not order.is_successful or key in worker_mapping:
            continue
        label = str(worker).strip() if key else _BLANK_WORKER_LABEL
        unknown.setdefault(key, (label, []))[1].append(order.row_number)
    return list(unknown.values())
