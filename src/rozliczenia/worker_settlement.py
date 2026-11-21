from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from openpyxl.utils import column_index_from_string

from .activity_legend import AMOUNT_COLUMN, FillColour
from .collective_layout import QUANTITY_LETTERS
from .efenix_mark import mark_of
from .order_facts import MissingHeaders, legend_colour, order_contents
from .quantity_engine import QuantityRules, evaluate
from .register_columns import ADDRESS, DEVICES
from .text import normalize_text
from .workbook_files import DataCell, DataRow, is_blank

Cleared = Mapping[str, int]

_COLUMNS: Final = tuple(column_index_from_string(column) - 1 for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN))
_FOR_WORKER: Final[Mapping[FillColour, int | None]] = {FillColour.RED: None, FillColour.GREEN: 1}


def for_worker(header: Mapping[str, int], rows: Sequence[DataRow], rules: QuantityRules) -> tuple[list[DataRow], Cleared]:
    rows, cleared = _without_inea_only(header, _without_efenix_mark(header, rows), rules)
    return [_coloured(row) for row in rows], cleared


def _without_efenix_mark(header: Mapping[str, int], rows: Sequence[DataRow]) -> list[DataRow]:
    address = header.get(normalize_text(ADDRESS.target_header))
    if address is None:
        return list(rows)
    return [_unmarked(row, address - 1) for row in rows]


def _unmarked(row: DataRow, index: int) -> DataRow:
    cell = row.cells[index]
    if mark_of(cell.highlights.fill) is None:
        return row
    cells = list(row.cells)
    cells[index] = cell._replace(highlights=replace(cell.highlights, fill=None))
    return replace(row, cells=tuple(cells))


def _without_inea_only(
    header: Mapping[str, int], rows: Sequence[DataRow], rules: QuantityRules
) -> tuple[list[DataRow], Cleared]:
    cleared = dict.fromkeys(rules.leave_empty_columns, 0)
    contents = order_contents(header, rows, required=(DEVICES,))
    if isinstance(contents, MissingHeaders):
        return list(rows), cleared
    result: list[DataRow] = []
    for row, content in zip(rows, contents, strict=True):
        cells = list(row.cells)
        for column in evaluate(rules, content).leave_empty:
            index = column_index_from_string(column) - 1
            if _is_green(cells[index]):
                continue
            cleared[column] += not is_blank(cells[index].value)
            cells[index] = cells[index]._replace(value=None, hyperlink=None)
        result.append(replace(row, cells=tuple(cells)))
    return result, cleared


def _is_green(cell: DataCell) -> bool:
    return legend_colour(cell.highlights.fill) is FillColour.GREEN


def _coloured(row: DataRow) -> DataRow:
    cells = list(row.cells)
    for index in _COLUMNS:
        colour = legend_colour(cells[index].highlights.fill)
        if colour is not None:
            cells[index] = _settled(cells[index], _FOR_WORKER[colour])
    return replace(row, cells=tuple(cells))


def _settled(cell: DataCell, value: int | None) -> DataCell:
    return cell._replace(
        value=value,
        highlights=replace(cell.highlights, fill=None),
        hyperlink=None if value is None else cell.hyperlink,
    )
