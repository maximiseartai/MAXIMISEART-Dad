from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

from openpyxl.styles.colors import COLOR_INDEX, Color
from openpyxl.styles.fills import Fill, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter

from .activity_legend import AMOUNT_COLUMN, FILL_COLUMNS, FillColour
from .tool_entry import description
from .collective_layout import QUANTITY_LETTERS
from .register_columns import ACTIVITIES, COMPLETED, CONTRACT, DATE, DEVICES, Column
from .quantity_engine import OrderContent
from .workbook_files import DataRow, cell_datetime, is_blank
from .text import normalize_text

NON_NUMERIC: Final = "nieliczbowa"
TataValue = int | Literal["nieliczbowa"]

_INPUTS: Final[tuple[Column, ...]] = (CONTRACT, DEVICES, ACTIVITIES, DATE)
_NO_FILLS: Final[Mapping[str, FillColour]] = MappingProxyType({})


@dataclass(frozen=True)
class OrderFacts:
    content: OrderContent | None
    quantities: Mapping[str, TataValue]
    completed: str = ""
    amount: TataValue = 0
    fills: Mapping[str, FillColour] = field(default=_NO_FILLS)

    def quantity(self, column: str) -> TataValue:
        return self.quantities.get(column, 0)


@dataclass(frozen=True)
class MissingHeaders:
    headers: tuple[str, ...]


CollectiveOrders = tuple[OrderFacts, ...] | MissingHeaders


def collective_orders(header: Mapping[str, int], rows: Sequence[DataRow]) -> CollectiveOrders:
    contents = order_contents(header, rows)
    if isinstance(contents, MissingHeaders):
        return contents
    completed_index = header.get(normalize_text(COMPLETED.target_header))
    completed = None if completed_index is None else get_column_letter(completed_index)
    return tuple(
        OrderFacts(
            None if content.started is None else content,
            _quantities(row),
            description(_value(row, completed)),
            tata_value(row.value(AMOUNT_COLUMN)),
            _fills(row),
        )
        for content, row in zip(contents, rows, strict=True)
    )


def order_contents(
    header: Mapping[str, int], rows: Sequence[DataRow], required: tuple[Column, ...] = _INPUTS
) -> tuple[OrderContent, ...] | MissingHeaders:
    columns = {column: header.get(normalize_text(column.target_header)) for column in _INPUTS}
    missing = tuple(column.target_header for column in required if columns[column] is None)
    if missing:
        return MissingHeaders(missing)
    contract, devices, activities, started = (None if index is None else get_column_letter(index) for index in columns.values())
    return tuple(
        OrderContent.of(
            _value(row, contract), _value(row, devices), _value(row, activities), cell_datetime(_value(row, started))
        )
        for row in rows
    )


def _value(row: DataRow, letter: str | None) -> object:
    return None if letter is None else row.value(letter)


def tata_value(cell: object) -> TataValue:
    if is_blank(cell):
        return 0
    if isinstance(cell, bool):
        return NON_NUMERIC
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float):
        return int(cell) if cell.is_integer() else NON_NUMERIC
    if isinstance(cell, Decimal):
        return int(cell) if cell.is_finite() and cell == cell.to_integral_value() else NON_NUMERIC
    if isinstance(cell, str):
        return _number_text(cell.strip())
    return NON_NUMERIC


def _number_text(text: str) -> TataValue:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return NON_NUMERIC
    return int(number) if number.is_integer() else NON_NUMERIC


def _quantities(row: DataRow) -> dict[str, TataValue]:
    values = {letter: tata_value(row.value(letter)) for letter in QUANTITY_LETTERS}
    return {letter: value for letter, value in values.items() if value != 0}


def _fills(row: DataRow) -> Mapping[str, FillColour]:
    colours = {column: legend_colour(row.cells[column_index_from_string(column) - 1].highlights.fill) for column in FILL_COLUMNS}
    return MappingProxyType({column: colour for column, colour in colours.items() if colour is not None})


def legend_colour(fill: Fill | None) -> FillColour | None:
    if not isinstance(fill, PatternFill) or fill.patternType != "solid":
        return None
    rgb = _rgb(fill.fgColor)
    return next((colour for colour in FillColour if rgb is not None and rgb == colour.argb[-6:]), None)


def _rgb(color: Color | None) -> str | None:
    if color is None:
        return None
    if color.type == "rgb" and isinstance(color.rgb, str):
        return color.rgb[-6:].upper()
    if color.type == "indexed" and isinstance(color.indexed, int) and color.indexed < len(COLOR_INDEX):
        return COLOR_INDEX[color.indexed][-6:].upper()
    return None
