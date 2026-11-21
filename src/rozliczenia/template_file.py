from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager, suppress
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Never, cast

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles.fills import Fill
from openpyxl.styles.fonts import Font
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.exceptions import IllegalCharacterError
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.worksheet import Worksheet

from .highlights import PLAIN
from .register_columns import TARGET_HEADERS
from .row_look import GENERAL, RowLook, wraps
from .template_copy import InvalidValue, Package, Recalculation, Row, SheetLayout, TemplateCopy
from .collective_layout import (
    DATA_ROW_COLUMNS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    INPUT_COLUMNS,
    LOOK_COLUMNS,
    QUANTITY_COLUMNS,
    REMARKS_AMOUNT,
    letter,
)
from .workbook_files import (
    DataRow,
    MergedCells,
    MissingHeader,
    Problem,
    RegisterRow,
    WorkbookError,
    check_worker_header,
    header_columns,
    is_blank,
    open_workbook,
    price_list,
    template_content,
)
from .workbook_parts import UnsupportedShape
from .workbook_save import SaveProblem, WorkbookSaveError, save_from_template, write_atomically
from .text import normalize_text
from .write_routes import Route, TemplateKind


_INTERNAL_LOOK_COLUMNS = range(1, 14)


@dataclass(frozen=True)
class _Rules:
    sheet: SheetLayout
    kind: TemplateKind
    worker_header: bool
    headers: tuple[str, ...] = ()
    @property
    def last_header_column(self) -> int | None:
        return self.sheet.input_columns if self.worker_header else None


_WORKER_SETTLEMENT = _Rules(
    SheetLayout(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=DATA_ROW_COLUMNS[-1],
        look_columns=LOOK_COLUMNS[-1],
        period_file=False,
        recalculation=Recalculation.FORCED,
    ),
    kind=TemplateKind.WORKER_SETTLEMENT,
    worker_header=True,
)
_COLLECTIVE_FILE = _Rules(
    SheetLayout(
        header_row=HEADER_ROW,
        first_data_row=FIRST_DATA_ROW,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=INPUT_COLUMNS[-1],
        look_columns=LOOK_COLUMNS[-1],
        period_file=True,
        recalculation=Recalculation.FORCED,
        quantity_columns=QUANTITY_COLUMNS,
        written_columns=range(QUANTITY_COLUMNS.start, REMARKS_AMOUNT + 1),
    ),
    kind=TemplateKind.COLLECTIVE_FILE,
    worker_header=True,
    headers=TARGET_HEADERS,
)
_INTERNAL_SETTLEMENT = _Rules(
    SheetLayout(
        header_row=1,
        first_data_row=2,
        input_columns=INPUT_COLUMNS[-1],
        data_columns=INPUT_COLUMNS[-1],
        look_columns=_INTERNAL_LOOK_COLUMNS[-1],
        period_file=True,
        recalculation=Recalculation.ON_LOAD,
    ),
    kind=TemplateKind.INTERNAL_SETTLEMENT,
    worker_header=False,
    headers=TARGET_HEADERS,
)


def _is_value(cell: Cell | MergedCell) -> bool:
    return cell.value is not None and cell.data_type != "f"


def _is_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


@dataclass(frozen=True)
class _Outline:
    title: str
    header: Sequence[object]
    whole_header: Sequence[object]
    merged_ranges: tuple[CellRange, ...]
    zero_row_count: int


def _zero_row_count(sheet: Worksheet, layout: SheetLayout) -> int:
    if not layout.quantity_columns:
        return 0
    zero_row_count = 0
    for values in sheet.iter_rows(
        min_row=layout.first_data_row,
        min_col=layout.quantity_columns[0],
        max_col=layout.quantity_columns[-1],
        values_only=True,
    ):
        if not any(_is_zero(value) for value in values):
            break
        zero_row_count += 1
    return zero_row_count


@dataclass(frozen=True)
class TemplatePlan:
    data_rows: range
    zero_row_count: int
    first_row_without_zeros: int


class TemplateFile:
    def __init__(self, path: Path, rules: _Rules) -> None:
        self.path = path
        self._rules = rules
        self._content: bytes | None = None
        self._copy: TemplateCopy | None = None
        self._copy_read = False
        self._outline: _Outline | None = None
        self._read_for_files = False

    @classmethod
    def worker_settlement(cls, path: Path) -> TemplateFile:
        return cls(path, _WORKER_SETTLEMENT)

    @classmethod
    def collective_file(cls, path: Path) -> TemplateFile:
        return cls(path, _COLLECTIVE_FILE)

    @classmethod
    def internal_settlement(cls, path: Path) -> TemplateFile:
        return cls(path, _INTERNAL_SETTLEMENT)

    @property
    def kind(self) -> TemplateKind:
        return self._rules.kind

    def check(self) -> None:
        if self._rules.sheet.period_file:
            outline = self._read_outline()
            self._target_columns(outline.title, outline.header)
            if self._rules.worker_header:
                check_worker_header(self.path, outline.title, outline.header)
            return
        self._read()
        copy = self._template_copy()
        if copy is not None:
            self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            return
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            self._check_settlement_template(sheet.title, self._header(sheet), self._has_input_data(sheet))

    def price_list(self) -> Mapping[str, str]:
        return price_list(self._read_outline().whole_header)

    def plan(self, row_count: int) -> TemplatePlan:
        outline = self._read_outline()
        columns = self._written_columns(self._target_columns(outline.title, outline.header))
        _ensure_unmerged(self.path, outline.title, outline.merged_ranges, self._rules.sheet, columns, row_count)
        first_row = self._rules.sheet.first_data_row
        return TemplatePlan(
            range(first_row, first_row + row_count), outline.zero_row_count, first_row + outline.zero_row_count
        )

    def create(self, target: Path, rows: Sequence[DataRow] | Sequence[RegisterRow]) -> Route:
        if not self._read_for_files:
            self._read()
            self._read_for_files = True
        copy = self._template_copy()
        if copy is not None:
            target_columns = self._target_columns(copy.title, copy.header)
            if not self._rules.sheet.period_file:
                self._check_settlement_template(copy.title, copy.header, copy.has_input_data)
            try:
                package = copy.with_rows(_in_columns(rows, target_columns))
            except InvalidValue as exc:
                raise WorkbookSaveError(target, SaveProblem.INVALID_VALUE) from exc
            except UnsupportedShape:
                pass
            else:
                write_atomically(target, _package_writer(package, target))
                return Route.COPY
        self._create_with_openpyxl(target, rows)
        return Route.OPENPYXL

    def _read(self) -> None:
        content = template_content(self.path)
        if content != self._content:
            self._content = content
            self._copy = None
            self._copy_read = False
            self._outline = None

    def _read_outline(self) -> _Outline:
        self._read()
        if self._outline is None:
            copy = self._template_copy()
            if copy is not None:
                merged_ranges = tuple(MultiCellRange([CellRange(reference) for reference in copy.merged_cells]).ranges)
                self._outline = _Outline(copy.title, copy.header, copy.whole_header, merged_ranges, copy.zero_row_count)
            else:
                with self._openpyxl_workbook() as workbook:
                    sheet = _active_worksheet(self.path, workbook)
                    self._outline = _Outline(
                        sheet.title,
                        self._header(sheet),
                        [cell.value for cell in sheet[self._rules.sheet.header_row]],
                        tuple(sheet.merged_cells.ranges),
                        _zero_row_count(sheet, self._rules.sheet),
                    )
        return self._outline

    def _template_copy(self) -> TemplateCopy | None:
        if not self._copy_read:
            self._copy_read = True
            self._copy = None
            with suppress(UnsupportedShape):
                copy = TemplateCopy.of(self._loaded(), self._rules.sheet)
                found, whole = header_columns(copy.header), header_columns(copy.whole_header)
                if all(found.get(normalize_text(target)) == whole.get(normalize_text(target)) for target in self._rules.headers):
                    self._copy = copy
        return self._copy

    def _openpyxl_workbook(self) -> AbstractContextManager[Workbook]:
        return open_workbook(self.path, self._loaded(), read_only=False)

    def _create_with_openpyxl(self, target: Path, rows: Sequence[DataRow] | Sequence[RegisterRow]) -> None:
        with self._openpyxl_workbook() as workbook:
            sheet = _active_worksheet(self.path, workbook)
            header = self._header(sheet)
            target_columns = self._target_columns(sheet.title, header)
            columns = self._written_columns(target_columns)
            if self._rules.sheet.period_file:
                _ensure_unmerged(
                    self.path, sheet.title, tuple(sheet.merged_cells.ranges), self._rules.sheet, columns, len(rows)
                )
            else:
                self._check_settlement_template(sheet.title, header, self._has_input_data(sheet))
                _ensure_unmerged(
                    self.path, sheet.title, tuple(sheet.merged_cells.ranges), self._rules.sheet, columns, len(rows)
                )
            try:
                _write_rows(sheet, self._rules.sheet, _in_columns(rows, target_columns), columns)
            except IllegalCharacterError as exc:
                raise WorkbookSaveError(target, SaveProblem.INVALID_VALUE) from exc
            _request_recalculation(workbook, self._rules.sheet.recalculation)
            save_from_template(workbook, target, self._loaded())

    def _header(self, sheet: Worksheet) -> list[object]:
        last_column = self._rules.last_header_column or sheet.max_column
        return [sheet.cell(self._rules.sheet.header_row, column).value for column in range(1, last_column + 1)]

    def _has_input_data(self, sheet: Worksheet) -> bool:
        for row in range(self._rules.sheet.first_data_row, sheet.max_row + 1):
            if any(_is_value(sheet.cell(row, column)) for column in INPUT_COLUMNS):
                return True
        return False

    def _check_settlement_template(self, sheet: str, header: Sequence[object], has_input_data: bool) -> None:
        check_worker_header(self.path, sheet, header)
        if has_input_data:
            raise WorkbookError(self.path, Problem.HAS_DATA)

    def _target_columns(self, sheet: str, header: Sequence[object]) -> Mapping[str, int]:
        found = header_columns(header)
        columns: dict[str, int] = {}
        for target in self._rules.headers:
            column = found.get(normalize_text(target))
            if column is None:
                raise WorkbookError(self.path, Problem.LAYOUT, MissingHeader(sheet, self._rules.sheet.header_row, target))
            columns[target] = column
        return columns

    def _written_columns(self, target_columns: Mapping[str, int]) -> Collection[int]:
        return target_columns.values() if self._rules.headers else DATA_ROW_COLUMNS

    def _loaded(self) -> bytes:
        assert self._content is not None, "Wzorzec jest czytany przed użyciem"
        return self._content


def _ensure_unmerged(
    path: Path, sheet: str, merged_ranges: Sequence[CellRange], layout: SheetLayout, columns: Collection[int], row_count: int
) -> None:
    if row_count == 0:
        return
    first_row, last_row = layout.first_data_row, layout.first_data_row + row_count - 1
    last_column = max(_last_written_column(layout, columns), layout.written_columns.stop - 1)
    for merged in merged_ranges:
        if merged.min_row <= last_row and merged.max_row >= first_row and merged.min_col <= last_column:
            raise WorkbookError(path, Problem.LAYOUT, MergedCells(sheet, merged.coord))


def _last_written_column(layout: SheetLayout, columns: Collection[int]) -> int:
    return max(layout.look_columns, *columns)


_NO_NUMBERS: MappingProxyType[str, Never] = MappingProxyType({})
_NO_FILLS: MappingProxyType[str, Never] = MappingProxyType({})


def _in_columns(rows: Sequence[DataRow] | Sequence[RegisterRow], target_columns: Mapping[str, int]) -> list[Row]:
    return [
        Row(dict(enumerate(row.cells, start=1)), _NO_NUMBERS, _NO_FILLS)
        if isinstance(row, DataRow)
        else Row({target_columns[header]: cell for header, cell in row.cells.items()}, _numbers(row), row.fills)
        for row in rows
    ]


def _numbers(row: RegisterRow) -> Mapping[str, int]:
    return {**row.quantities, letter(REMARKS_AMOUNT): row.amount} if row.amount else row.quantities


def _write_rows(sheet: Worksheet, layout: SheetLayout, rows: Sequence[Row], columns: Collection[int]) -> None:
    last_column = _last_written_column(layout, columns)
    look_columns = last_column if layout.period_file else layout.look_columns
    look = RowLook([cast(Font, sheet.cell(layout.header_row, column).font) for column in range(1, look_columns + 1)])
    for index, row in enumerate(rows):
        number = layout.first_data_row + index
        dimension = sheet.row_dimensions.get(number)
        if dimension is not None:
            dimension.ht = None
        for column in range(1, last_column + 1):
            cell = sheet.cell(number, column)
            data = row.cells.get(column)
            if data is None:
                look.cell(column, PLAIN, GENERAL, wrapped=False).apply(cell)
                continue
            value, highlights, number_format, link = data
            cell.hyperlink = None if link is None else link.address
            cell.value = value
            if column <= look.columns:
                look.cell(column, highlights, number_format, wrapped=wraps(value)).apply(cell)
            else:
                cell.font = highlights.font_over(cast(Font, cell.font))
                cell.fill = highlights.fill_over(cast(Fill, copy(cell.fill)))
        for written, value in row.numbers.items():
            sheet.cell(number, column_index_from_string(written)).value = value
        for written, fill in row.fills.items():
            sheet.cell(number, column_index_from_string(written)).fill = copy(fill)
    if layout.period_file:
        _set_autofilter(sheet, layout.header_row, len(rows))


def _set_autofilter(sheet: Worksheet, header_row: int, row_count: int) -> None:
    columns = [column for column, cell in enumerate(sheet[header_row], start=1) if not is_blank(cell.value)]
    first_column, last_column = get_column_letter(min(columns)), get_column_letter(max(columns))
    sheet.auto_filter = AutoFilter(ref=f"{first_column}{header_row}:{last_column}{header_row + row_count}")


def _package_writer(package: Package, target: Path) -> Callable[[Path], None]:
    def write(path: Path) -> None:
        try:
            with path.open("wb") as out:
                package.write(out)
        except OSError as exc:
            raise WorkbookSaveError(target, SaveProblem.CONTENT) from exc

    return write


def _active_worksheet(path: Path, workbook: Workbook) -> Worksheet:
    worksheet = workbook.active
    if not isinstance(worksheet, Worksheet):
        raise WorkbookError(path, Problem.UNREADABLE)
    return worksheet


def _request_recalculation(workbook: Workbook, recalculation: Recalculation) -> None:
    calculation = getattr(workbook, "calculation", None)
    if calculation is not None:
        for flag, value in recalculation.value:
            setattr(calculation, flag, value)
