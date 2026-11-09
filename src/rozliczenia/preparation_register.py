"""Rejestr zleceń w Przygotowaniu pliku zbiorczego: jeden odczyt na Uruchomienie i Komunikaty Przygotowania o nim.

Rejestr czyta raz ``register_file.read`` uchwytem plików taty (``dad_files.DadFiles``) w Sprawdzaniu, a strażnik Surowych
zleceń (``raw_orders_in_period``) i Odczyt danych (``period_sheets``) decydują na tych samych bajtach. Moduł tłumaczy
błąd odczytu (``WorkbookError``) i problem nagłówków (``register_file.HeadersProblem``) na Komunikaty Przygotowania;
Diagnoza pyta o ten sam Komunikat (``register_problem``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import preparation_messages as messages
from . import raw_orders, register_file, workbook_files
from .message import Message, StopError
from .register_columns import COLUMNS, Column
from .register_file import DuplicatedHeaders, MissingHeaders, NoOrderSheet, OrderSheets, RegisterFile, RegisterSheet
from .settlement_period import SettlementPeriod
from .workbook_files import Problem, RegisterRow, WorkbookError
from .workbook_parts import UnsupportedShape

if TYPE_CHECKING:
    from .dad_files import DadFiles


def cell_value(row: RegisterRow, column: Column) -> object:
    return row.cells[column.target_header].value


def read(path: Path, files: DadFiles) -> RegisterFile:
    """Rejestr ``path`` przeczytany uchwytem ``files``; zatrzymanie, gdy go nie ma, jest otwarty w Excelu, niedostępny
    albo nieczytelny."""

    with _stops():
        return register_file.read(path, files)


@dataclass(frozen=True)
class RawOrders:
    """Surowe zlecenia, które mogą należeć do okresu: arkusz zleceń i jego wiersze od ``first_row`` do ``last_row``."""

    sheet: str
    first_row: int
    last_row: int


def raw_orders_in_period(register: RegisterFile, period: SettlementPeriod) -> RawOrders | None:
    """Surowe zlecenia na dole arkusza zleceń z dniem w ``period`` albo z dniem, którego nie da się ustalić.

    Szuka ich tym samym rozpoznaniem bloku i odczytem arkusza co Uporządkowanie INTERMAX (``raw_orders.pasted`` na
    obszarach wklejania). Dzień nie daje się ustalić, gdy Surowe zlecenie nie ma daty albo Wykonawcy: wtedy to
    Uporządkowanie INTERMAX mówi, co poprawić. Wiersz z wyglądem z aplikacji nad uporządkowanymi bez bloku na dole nie
    jest Surowym zleceniem i Przygotowania nie zatrzymuje. Zatrzymanie przy nieczytelnym Rejestrze.

    Surowych zleceń szuka tylko w obszarach wklejania (zob. ``register_file.OrderSheet.paste``). Rejestr bez arkusza
    zleceń to ``None``: Zatrzymanie o jego nagłówkach daje Odczyt danych.
    """

    if not isinstance(register.order_sheets, OrderSheets):
        return None
    with _stops(), workbook_files.unreadable_as_error(register.path):
        for area in register.order_sheets.paste_areas():
            try:
                pasted = raw_orders.pasted(area.rows_from_bottom(), area.columns)
            except UnsupportedShape as error:
                raise WorkbookError(register.path, Problem.UNREADABLE) from error
            found = _raw_rows_in_period(pasted, period)
            if found is not None:
                return RawOrders(area.sheet, *found)
    return None


def _raw_rows_in_period(
    pasted: Sequence[raw_orders.RawOrder | raw_orders.Undated | raw_orders.WithoutWorker], period: SettlementPeriod
) -> tuple[int, int] | None:
    undetermined = next((order for order in pasted if not isinstance(order, raw_orders.RawOrder)), None)
    if undetermined is not None:
        return undetermined.row, undetermined.row
    in_period = any(period.contains(order.when) for order in pasted if isinstance(order, raw_orders.RawOrder))
    return (pasted[0].row, pasted[-1].row) if in_period else None


def period_sheets(register: RegisterFile, period: SettlementPeriod | None) -> tuple[RegisterSheet, ...]:
    """Arkusze ze zleceniami Rejestru (``register_file.OrderSheets.period_rows``): z ``period`` tylko wiersze od
    pierwszego do ostatniego, którego data może leżeć w okresie, bo Planowanie szuka zleceń okresu i wierszy bez daty
    tylko między nimi; bez ``period`` wszystkie wiersze. Zatrzymanie, gdy Rejestr nie ma arkusza zleceń, wymagany
    nagłówek stoi więcej niż raz albo openpyxl nie przeczyta skoroszytu."""

    path = register.path
    match register.order_sheets:
        case DuplicatedHeaders(sheet, labels):
            raise StopError(messages.register_with_duplicated_headers(path, sheet, labels))
        case MissingHeaders(sheet, labels):
            raise StopError(messages.register_without_headers(path, sheet, labels))
        case NoOrderSheet():
            raise StopError(messages.register_without_data_sheet(path, [column.label for column in COLUMNS]))
        case OrderSheets() as sheets:
            with _stops():
                return sheets.period_rows(period)


def register_problem(path: Path, files: DadFiles) -> Message | None:
    """Komunikat, którym Przygotowanie zatrzymałoby się na Rejestrze zleceń: otwarty w Excelu, nieczytelny (także w
    wierszu, którego okres nie czyta), bez nagłówków."""

    try:
        period_sheets(read(path, files), None)
    except StopError as stop:
        return stop.message
    return None


@contextmanager
def _stops() -> Iterator[None]:
    try:
        yield
    except WorkbookError as error:
        raise StopError(messages.register_unusable(error)) from error
