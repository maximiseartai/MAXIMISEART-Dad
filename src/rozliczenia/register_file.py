from __future__ import annotations

import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import cached_property, lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NamedTuple, cast
from xml.etree import ElementTree

from openpyxl.styles.fonts import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from . import client_data, raw_orders, workbook_files
from .cell_values import CellValues
from .dad_files import DadFiles, ReadFile, SheetMemory
from .highlights import LookReader
from .hyperlinks import read_sheet_hyperlinks
from .raw_orders import SHIFT, CellFacts, OrderColumns, RowFacts, RowLook
from .register_columns import (
    ACTIVITIES,
    ADDRESS,
    CITY,
    COLUMNS,
    CONTRACT_NUMBER,
    DATE,
    DAY_FILL,
    DEVICES,
    ORDER_NUMBER,
    TARGET_HEADERS,
    WORKER,
    Column,
)
from .row_look import GENERAL
from .row_positions import RowPositions
from .settlement_period import SettlementPeriod
from .text import normalize_text
from .workbook_files import DataCell, RegisterRow, header_columns, is_blank
from .workbook_parts import (
    MAIN,
    OFFICE_REL,
    IrregularSheetData,
    RowsFromBottom,
    SharedStrings,
    SheetCell,
    UnsupportedShape,
    column_texts,
    office_document,
    relationships,
    row_attributes,
    row_tag,
    rows_dated_between,
    sheet_cells,
    unpacked,
)

__all__ = [
    "DuplicatedHeaders",
    "HeadersProblem",
    "MissingHeaders",
    "NoOrderSheet",
    "OrderSheet",
    "OrderSheets",
    "PasteArea",
    "RecognizedSheet",
    "RegisterFile",
    "RegisterPackage",
    "RegisterSheet",
    "read",
    "recognize",
]

_FIRST: Final = "AKCJE"
_LAST: Final = "UWAGI"


@dataclass(frozen=True)
class NoOrderSheet:
    ...


@dataclass(frozen=True)
class MissingHeaders:
    sheet: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class DuplicatedHeaders:
    sheet: str
    labels: tuple[str, ...]


HeadersProblem = NoOrderSheet | MissingHeaders | DuplicatedHeaders


@dataclass(frozen=True)
class RecognizedSheet:
    name: str
    positions: Mapping[Column, int]
    header: Mapping[str, int]


def recognize(sheets: Iterable[tuple[str, Sequence[object]]]) -> tuple[RecognizedSheet, ...] | HeadersProblem:
    found: list[RecognizedSheet] = []
    closest: MissingHeaders | None = None
    for name, values in sheets:
        header = header_columns(values)
        positions = {column: _position(column, header) for column in COLUMNS}
        missing = tuple(column.label for column, position in positions.items() if position is None)
        if missing:
            if len(missing) < len(COLUMNS) / 2 and (closest is None or len(missing) < len(closest.labels)):
                closest = MissingHeaders(name, missing)
            continue
        duplicated = _duplicated(values)
        if duplicated:
            return DuplicatedHeaders(name, duplicated)
        complete = {column: position for column, position in positions.items() if position is not None}
        found.append(RecognizedSheet(name, MappingProxyType(complete), MappingProxyType(header)))
    if found:
        return tuple(found)
    return closest if closest is not None else NoOrderSheet()


def _position(column: Column, header: Mapping[str, int]) -> int | None:
    return next((header[name] for name in map(normalize_text, column.register_headers) if name in header), None)


def _duplicated(values: Sequence[object]) -> tuple[str, ...]:
    normalized = [normalize_text(value) for value in values if not is_blank(value)]
    return tuple(
        column.label
        for column in COLUMNS
        if sum(normalized.count(name) for name in set(map(normalize_text, column.register_headers))) > 1
    )


@dataclass(frozen=True)
class RegisterPackage:
    infos: tuple[zipfile.ZipInfo, ...]
    parts: Mapping[str, bytes]
    workbook_part: str
    styles_part: str
    sheet_parts: tuple[str, ...]


@dataclass(frozen=True)
class OrderSheet:
    name: str
    positions: Mapping[Column, int]
    header: tuple[object, ...] = field(repr=False)
    paste: PasteArea | None
    part: str = field(repr=False)

    @property
    def look_columns(self) -> frozenset[int]:
        if self.paste is not None:
            return self.paste.columns.look_columns
        return frozenset(self.positions.values()) - {self.positions[WORKER]}


@dataclass(frozen=True, eq=False)
class OrderSheets:
    sheets: tuple[OrderSheet, ...]
    _file: ReadFile = field(repr=False)
    _epoch: datetime = field(repr=False)
    _parts: Mapping[str, bytes] = field(repr=False)
    _shared: SharedStrings = field(repr=False)

    def paste_areas(self) -> tuple[PasteArea, ...]:
        return tuple(sheet.paste for sheet in self.sheets if sheet.paste is not None)

    def workers(self) -> frozenset[str]:
        found: set[str] = set()
        for sheet in self.sheets:
            try:
                texts = column_texts(self._parts[sheet.part], sheet.positions[WORKER], 2, self._shared)
                found.update(normalize_text(text) for _, text in texts)
            except IrregularSheetData as error:
                raise UnsupportedShape(str(error)) from error
        found.discard("")
        return frozenset(found)

    def period_rows(self, period: SettlementPeriod | None) -> tuple[RegisterSheet, ...]:
        file = self._file
        sheets = tuple(
            (sheet.name, tuple(sheet.positions[column] for column in COLUMNS), tuple(sorted(sheet.look_columns)))
            for sheet in self.sheets
        )
        if period is None:
            windows = _windows(file.path, file.content, sheets, {})
        else:
            windows = _period_read(file.path, file.content, sheets, self._epoch, period)
        for sheet, window in zip(self.sheets, windows, strict=True):
            positions = sheet.positions
            header = sheet.header
            last = header_columns(header).get(normalize_text(_LAST), max(positions.values()))
            span = range(1, max(last, *positions.values()) + 1)
            witnessed = file.sheet(
                sheet.name,
                1,
                {column: header[column - 1] for column in span if column <= len(header)},
                _forbidden_positions(positions),
                copied_columns=positions.values(),
                date_column=positions[DATE],
                span=span,
            )
            for row in window.rows:
                witnessed.row(row.number, row.values, row.positions)
            witnessed.empty_rows(window.sheet.empty_rows)
        return tuple(window.sheet for window in windows)


@dataclass(frozen=True, eq=False)
class RegisterFile:
    path: Path
    content: bytes = field(repr=False)
    order_sheets: OrderSheets | HeadersProblem
    package: RegisterPackage = field(repr=False)


def read(path: Path, files: DadFiles, *, despite_excel_lock: bool = False) -> RegisterFile:
    file = files.read(path, despite_excel_lock=despite_excel_lock)
    with workbook_files.unreadable_as_error(file.path):
        infos, parts = unpacked(file.content)
        workbook = office_document(parts)
        if workbook is None:
            raise KeyError("officeDocument")
        rels = relationships(parts, workbook)
        root = ElementTree.fromstring(parts[workbook])
        cells = CellValues.of(parts, workbook, rels)
        styles = next(rel.target for rel in rels.values() if rel.kind.endswith("/styles"))
        values = _Values(_ReadStyles.of(parts[styles]), cells)
        sheets = [
            (sheet.get("name", ""), rels[sheet.get(f"{{{OFFICE_REL}}}id", "")].target)
            for sheet in root.iter(f"{MAIN}sheet")
        ]
        if not sheets:
            raise KeyError("sheet")
        headers = [cells.header(parts[part]) for _, part in sheets]
    package = RegisterPackage(infos, parts, workbook, styles, tuple(part for _, part in sheets))
    file.enter_copy()
    recognized = recognize((name, header) for (name, _), header in zip(sheets, headers, strict=True))
    if not isinstance(recognized, tuple):
        return RegisterFile(file.path, file.content, recognized, package)
    by_name = {name: (part, header) for (name, part), header in zip(sheets, headers, strict=True)}
    order_sheets = tuple(
        OrderSheet(
            sheet.name,
            sheet.positions,
            tuple(by_name[sheet.name][1]),
            _paste_area(sheet, *by_name[sheet.name], parts, values, file),
            by_name[sheet.name][0],
        )
        for sheet in recognized
    )
    return RegisterFile(
        file.path, file.content, OrderSheets(order_sheets, file, cells.epoch, parts, cells.shared), package
    )


def _paste_area(
    sheet: RecognizedSheet,
    part: str,
    header: Sequence[object],
    parts: Mapping[str, bytes],
    values: _Values,
    file: ReadFile,
) -> PasteArea | None:
    first, last = sheet.header.get(normalize_text(_FIRST)), sheet.header.get(normalize_text(_LAST))
    if first is None or last is None:
        return None
    positions = sheet.positions
    columns = OrderColumns(
        first,
        positions[DATE],
        positions[WORKER],
        last,
        devices=positions[DEVICES],
        activities=positions[ACTIVITIES],
        contract_number=positions[CONTRACT_NUMBER],
        address=positions[ADDRESS],
        city=positions[CITY],
        number=positions[ORDER_NUMBER],
    )
    return PasteArea(sheet.name, part, columns, header, parts[part], values, file)


def recent_workers(areas: Sequence[PasteArea], since: date) -> Counter[str]:
    found: Counter[str] = Counter()
    for area in areas:
        for row in raw_orders.ordered_rows(area.rows_from_bottom(), area.columns, since):
            found[normalize_text(row.value(area.columns.worker))] += 1
    del found[""]
    return found


class PasteArea:
    def __init__(
        self,
        sheet: str,
        part: str,
        columns: OrderColumns,
        header: Sequence[object],
        xml: bytes,
        values: _Values,
        file: ReadFile,
    ) -> None:
        self.sheet = sheet
        self.part = part
        self.columns = columns
        self._header = header
        self._xml = xml
        self._values = values
        self._file = file
        self._facts_read: dict[int, RowFacts] = {}
    @property
    def epoch(self) -> datetime:
        return self._values.cells.epoch

    @cached_property
    def sheet_xml(self) -> RowsFromBottom:
        try:
            return RowsFromBottom(self._xml)
        except IrregularSheetData as error:
            raise UnsupportedShape(str(error)) from error

    @cached_property
    def _forbidden_columns(self) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
        return client_data.forbidden_columns(header_columns(self._header))

    @cached_property
    def _memory(self) -> SheetMemory:
        return self._file.memory(self._forbidden_columns)

    @cached_property
    def _shifted_row(self) -> int | None:
        return raw_orders.shifted_row(self._facts_from_bottom(), self.columns)

    def rows_from_bottom(self) -> Iterator[RowFacts]:
        memory, columns, shifted = self._memory, self.columns, self._shifted_row
        for facts, first in raw_orders.first_in_block(self._facts_from_bottom(), lambda row: raw_orders.look(row, columns)):
            memory.remember(_values(facts), self._positions(facts, first, shifted))
            yield facts

    def copy_paste(self) -> None:
        columns = self.columns
        try:
            shifted = self._shifted_row
            pasted = raw_orders.pasted_rows(self.rows_from_bottom(), columns)
            above = raw_orders.above_paste(self._facts_from_bottom(), columns)
        except UnsupportedShape:
            return
        copied = range(1, columns.last + 1)
        header = self._header
        sheet = self._file.sheet(
            self.sheet,
            1,
            {column: header[column - 1] for column in copied if column <= len(header)},
            self._forbidden_columns,
            copied_columns=copied,
            date_column=columns.date,
            above=above,
        )
        for facts in pasted:
            sheet.row(facts.number, _values(facts), self._positions(facts, facts is pasted[0], shifted))

    def copy_rows(self, rows: Sequence[RowFacts]) -> None:
        columns = self.columns
        copied = range(1, columns.last + 1)
        header = self._header
        sheet = self._file.sheet(
            self.sheet,
            1,
            {column: header[column - 1] for column in copied if column <= len(header)},
            self._forbidden_columns,
            copied_columns=copied,
            date_column=columns.date,
        )
        for facts in rows:
            sheet.row(facts.number, _values(facts), self._positions(facts, False, None))

    def _positions(self, facts: RowFacts, first: bool, shifted: int | None) -> RowPositions:
        columns = self.columns
        return raw_orders.row_positions(
            first=first,
            left_of_date=facts.value(columns.date - SHIFT),
            date=facts.value(columns.date),
            read=SHIFT if facts.number == shifted else 0,
        )

    def _facts_from_bottom(self) -> Iterator[RowFacts]:
        sheet, read = self.sheet_xml, self._facts_read
        try:
            for row in sheet:
                if row.number < 2:
                    return
                facts = read.get(row.number)
                if facts is None:
                    facts = read[row.number] = self._values.facts(
                        row_tag(sheet.xml, row), row.number, sheet_cells(sheet.xml[row.start : row.end])
                    )
                yield facts
        except IrregularSheetData as error:
            raise UnsupportedShape(str(error)) from error


def _values(facts: RowFacts) -> dict[int, object]:
    return {column: cell.value for column, cell in facts.cells.items()}


@dataclass(frozen=True)
class RegisterSheet:
    name: str
    register_rows: tuple[RegisterRow, ...]
    empty_rows: tuple[int, ...]
    _positions: tuple[int, ...]

    def column_letter(self, column: Column) -> str:
        return get_column_letter(self._positions[COLUMNS.index(column)])

    @property
    def positions(self) -> dict[Column, int]:
        return dict(zip(COLUMNS, self._positions, strict=True))


_SheetsKey = tuple[tuple[str, tuple[int, ...], tuple[int, ...]], ...]


class _ReadRow(NamedTuple):
    values: tuple[object, ...]
    row: RegisterRow
    ordered: bool


@dataclass(frozen=True)
class _WindowRow:
    number: int
    values: tuple[object, ...]
    positions: RowPositions


@dataclass(frozen=True)
class _Window:
    sheet: RegisterSheet
    rows: tuple[_WindowRow, ...]


@lru_cache(maxsize=2)
def _period_read(
    path: Path, content: bytes, sheets: _SheetsKey, epoch: datetime, period: SettlementPeriod
) -> tuple[_Window, ...]:
    day = timedelta(days=1)
    low, high = ((moment - epoch) / day for moment in (period.start - day, period.end + day))
    dates = {name: columns[COLUMNS.index(DATE)] for name, columns, _ in sheets}
    with workbook_files.unreadable_as_error(path):
        narrowed, ranges = rows_dated_between(content, dates, low, high)
    return _windows(path, narrowed, sheets, ranges)


def _windows(path: Path, content: bytes, sheets: _SheetsKey, ranges: Mapping[str, range]) -> tuple[_Window, ...]:
    with workbook_files.open_workbook(path, content, read_only=True) as workbook:
        windows = []
        for name, columns, look_columns in sheets:
            with workbook_files.unreadable_as_error(path):
                sheet = cast(Worksheet, workbook[name])
            read = list(workbook_files.classified(path, _read_rows(content, sheet, columns, look_columns, ranges.get(name))))
            windows.append(_window(name, columns, read))
        return tuple(windows)


def _read_rows(
    content: bytes, sheet: Worksheet, columns: Sequence[int], look_columns: Sequence[int], rows: range | None
) -> Iterator[_ReadRow]:
    min_row, max_row = 2, None
    if rows is not None:
        min_row, max_row = max(min_row, rows.start), rows.stop - 1
        if min_row > max_row:
            return
    targets = {header: columns[index] for index, header in enumerate(TARGET_HEADERS)}
    links = read_sheet_hyperlinks(content, sheet.title)
    highlights = LookReader()
    for number, cells in enumerate(sheet.iter_rows(min_row=min_row, max_row=max_row), start=min_row):
        values = tuple(getattr(cell, "value", None) for cell in cells)
        row_links = links.row(number, values)
        picked = {header: cells[column - 1] if column <= len(cells) else None for header, column in targets.items()}
        looks = {header: highlights.of(cell) for header, cell in picked.items()}
        row = RegisterRow(
            number,
            MappingProxyType(
                {
                    header: DataCell(
                        getattr(cell, "value", None),
                        looks[header],
                        getattr(cell, "number_format", None) or GENERAL,
                        row_links.get(targets[header]),
                    )
                    for header, cell in picked.items()
                }
            ),
        )
        faces = (
            highlights.look(cells[column - 1])[1]
            for column in look_columns
            if column <= len(cells) and not is_blank(values[column - 1])
        )
        yield _ReadRow(values, row, raw_orders.ordered_look(faces))


def _window(name: str, columns: Sequence[int], read: Sequence[_ReadRow]) -> _Window:
    looks = {found.row.number: _look(found) for found in read}
    firsts = {
        found.row.number: first
        for found, first in raw_orders.first_in_block(reversed(read), lambda found: looks[found.row.number])
    }
    date = columns[COLUMNS.index(DATE)]
    rows = [found for found in read if looks[found.row.number] is not RowLook.BLANK]
    return _Window(
        RegisterSheet(
            name,
            tuple(found.row for found in rows),
            tuple(found.row.number for found in read if looks[found.row.number] is RowLook.BLANK),
            tuple(columns),
        ),
        tuple(
            _WindowRow(
                found.row.number,
                found.values,
                raw_orders.row_positions(
                    first=firsts[found.row.number],
                    left_of_date=_value_at(found.values, date - SHIFT),
                    date=_value_at(found.values, date),
                ),
            )
            for found in rows
        ),
    )


def _look(found: _ReadRow) -> RowLook:
    if all(is_blank(value) for value in found.values):
        return RowLook.BLANK
    return RowLook.ORDERED if found.ordered else RowLook.APP


def _forbidden_positions(positions: Mapping[Column, int]) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
    return client_data.forbidden_columns({normalize_text(column.target_header): positions[column] for column in COLUMNS})


def _value_at(values: Sequence[object], column: int) -> object:
    return values[column - 1] if 1 <= column <= len(values) else None


@dataclass(frozen=True)
class _ReadStyles:
    faces: tuple[tuple[str | None, float | None], ...]
    yellow: tuple[bool, ...]

    @classmethod
    def of(cls, xml: bytes) -> _ReadStyles:
        root = ElementTree.fromstring(xml)
        faces = [_face(Font.from_tree(cast(Any, font))) for font in root.iterfind(f"{MAIN}fonts/{MAIN}font")]
        fills = [_is_yellow(fill) for fill in root.iterfind(f"{MAIN}fills/{MAIN}fill")]
        xfs = list(root.iterfind(f"{MAIN}cellXfs/{MAIN}xf"))
        return cls(
            faces=tuple(faces[int(xf.get("fontId", "0"))] for xf in xfs),
            yellow=tuple(fills[int(xf.get("fillId", "0"))] for xf in xfs),
        )


def _face(font: Font) -> tuple[str | None, float | None]:
    return font.name, font.sz


def _is_yellow(fill: ElementTree.Element) -> bool:
    color = fill.find(f"{MAIN}patternFill[@patternType='solid']/{MAIN}fgColor")
    return color is not None and color.get("rgb", "").upper().endswith(DAY_FILL)


@dataclass(frozen=True)
class _Values:
    styles: _ReadStyles
    cells: CellValues

    def facts(self, tag: bytes, number: int, cells: Sequence[SheetCell]) -> RowFacts:
        styles = self.styles
        attributes = row_attributes(tag)
        row_style = attributes.get(b"s") if attributes.get(b"customFormat") == b"1" else None
        return RowFacts(
            number,
            {cell.column: CellFacts(self.cells.value(cell), styles.faces[cell.style], styles.yellow[cell.style]) for cell in cells},
            row_style is not None and styles.yellow[int(row_style)],
        )
