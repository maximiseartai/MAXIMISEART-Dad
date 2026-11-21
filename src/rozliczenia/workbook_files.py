from __future__ import annotations

import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import IO, TYPE_CHECKING, Final, NamedTuple, Never, TypeAlias, TypeVar, cast
from xml.etree.ElementTree import ParseError
from xml.parsers.expat import ExpatError

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText
from openpyxl.styles.fills import Fill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from . import client_data
from .collective_layout import (
    ADDRESS_COLUMN,
    AMOUNT_COLUMN,
    DATA_ROW_COLUMNS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    INPUT_COLUMNS,
    LOOK_COLUMNS,
    ORANGE_COLUMN,
    QUANTITY_COLUMNS,
    REMARKS_AMOUNT,
    WORKER_COLUMN,
)
from .file_state import file_state
from .highlights import Highlights, LookReader
from .hyperlinks import Hyperlink, read_sheet_hyperlinks
from .row_look import GENERAL
from .workbook_parts import (
    IrregularSheetData,
    SharedStrings,
    UnsupportedShape,
    active_sheet,
    column_texts,
    office_document,
    package_parts,
    relationships,
    rows_with_input,
)
from .text import normalize_text

if TYPE_CHECKING:
    from .dad_files import DadFiles, ReadFile, WitnessedSheet


_UNREADABLE_WORKBOOK_ERRORS = (
    OSError,
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    IndexError,
    ValueError,
    zlib.error,
    ParseError,
    ExpatError,
)

_WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xltx", ".xltm")

FORBIDDEN_POSITIONS: Final = (
    (client_data.ForbiddenColumn.ADDRESS, ADDRESS_COLUMN),
    (client_data.ForbiddenColumn.ORANGE, ORANGE_COLUMN),
)


_ExcelCellValue = (
    bool
    | int
    | float
    | Decimal
    | str
    | CellRichText
    | date
    | datetime
    | time
    | timedelta
    | DataTableFormula
    | ArrayFormula
    | bytes
    | None
)
ExcelRow = tuple[_ExcelCellValue, ...]


class Problem(Enum):
    MISSING = "brak pliku"
    OPEN_IN_EXCEL = "otwarty w Excelu"
    INACCESSIBLE = "niedostępny"
    UNREADABLE = "nieczytelny"
    LAYOUT = "zły układ"
    HAS_DATA = "zawiera dane"


@dataclass(frozen=True)
class MissingHeader:
    sheet: str
    row: int
    header: str
    found_in: str | None = None


@dataclass(frozen=True)
class MergedCells:
    sheet: str
    cells: str


LayoutFault = MissingHeader | MergedCells


class WorkbookError(Exception):
    def __init__(self, path: Path, problem: Problem, fault: LayoutFault | None = None) -> None:
        super().__init__(f"{problem.value}: {path.name}")
        self.path = path
        self.problem = problem
        self.fault = fault


@dataclass(frozen=True)
class HeaderCell:
    column: str
    row: int

    def __str__(self) -> str:
        return f"{self.column}{self.row}"


WORKER_HEADER = HeaderCell(get_column_letter(WORKER_COLUMN), HEADER_ROW)
_WORKER_LABEL = "WYKONAWCA"


_NO_QUANTITIES: MappingProxyType[str, Never] = MappingProxyType({})
_NO_FILLS: MappingProxyType[str, Never] = MappingProxyType({})


class DataCell(NamedTuple):
    value: _ExcelCellValue
    highlights: Highlights
    number_format: str
    hyperlink: Hyperlink | None


@dataclass(frozen=True)
class DataRow:
    number: int
    cells: tuple[DataCell, ...]

    def value(self, column: str) -> _ExcelCellValue:
        return self.cells[column_index_from_string(column) - 1].value

    @property
    def worker(self) -> _ExcelCellValue:
        return self.value(WORKER_HEADER.column)


@dataclass(frozen=True)
class RegisterRow:
    number: int
    cells: Mapping[str, DataCell]
    quantities: Mapping[str, int] = field(default_factory=lambda: _NO_QUANTITIES)
    amount: int = 0
    fills: Mapping[str, Fill] = field(default_factory=lambda: _NO_FILLS)


def excel_lock_file(path: Path) -> Path:
    return path.with_name(f"~${path.name}")


def is_open_in_excel(path: Path) -> bool:
    return file_state(excel_lock_file(path)) == "file"


def ensure_available(path: Path, *, despite_excel_lock: bool = False) -> None:
    match file_state(path):
        case "inaccessible":
            raise WorkbookError(path, Problem.INACCESSIBLE)
        case "missing":
            raise WorkbookError(path, Problem.MISSING)
        case "file":
            pass
    if is_open_in_excel(path) and not despite_excel_lock:
        raise WorkbookError(path, Problem.OPEN_IN_EXCEL)


_T = TypeVar("_T")


@contextmanager
def unreadable_as_error(path: Path) -> Iterator[None]:
    try:
        yield
    except _UNREADABLE_WORKBOOK_ERRORS as exc:
        raise WorkbookError(path, Problem.UNREADABLE) from exc


def file_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise WorkbookError(path, Problem.INACCESSIBLE) from exc


ByteSource: TypeAlias = Callable[[Path], bytes]


def classified(path: Path, items: Iterator[_T]) -> Iterator[_T]:
    while True:
        with unreadable_as_error(path):
            try:
                item = next(items)
            except StopIteration:
                return
        yield item


def _open(path: Path, source: IO[bytes], *, read_only: bool, computed: bool = False) -> Workbook:
    with unreadable_as_error(path):
        if read_only:
            workbook = load_workbook(source, read_only=True, data_only=computed)
        else:
            workbook = load_workbook(source, read_only=False, data_only=False, keep_links=True)
    if not isinstance(workbook.active, (Worksheet, ReadOnlyWorksheet)):
        workbook.close()
        raise WorkbookError(path, Problem.UNREADABLE)
    return workbook


def _is_worker_header(value: object) -> bool:
    return str(value or "").casefold().split() == ["wykonawca"]


def check_worker_header(path: Path, sheet: str, header: Sequence[object]) -> None:
    columns = [column for column, value in enumerate(header[: INPUT_COLUMNS[-1]], start=1) if _is_worker_header(value)]
    if WORKER_COLUMN not in columns:
        found_in = get_column_letter(columns[0]) if columns else None
        raise WorkbookError(path, Problem.LAYOUT, MissingHeader(sheet, HEADER_ROW, _WORKER_LABEL, found_in))


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def cell_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def header_columns(values: Sequence[object]) -> dict[str, int]:
    return {normalize_text(value): column for column, value in enumerate(values, start=1) if not is_blank(value)}


def _forbidden_columns(header: Sequence[object]) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
    by_header = client_data.forbidden_columns(header_columns(header[: INPUT_COLUMNS[-1]]))
    return tuple(dict.fromkeys((*FORBIDDEN_POSITIONS, *by_header)))


@dataclass(frozen=True)
class _Collective:
    file: ReadFile
    title: str
    header: ExcelRow
    content: bytes = field(repr=False)
    rows: Iterator[tuple[int, tuple[object, ...], ExcelRow]]


@contextmanager
def _collective_sheet(
    path: Path, files: DadFiles, *, last_column: int, computed: bool = False, despite_excel_lock: bool = False
) -> Iterator[_Collective]:
    file = files.read(path, despite_excel_lock=despite_excel_lock)
    with unreadable_as_error(path):
        content = rows_with_input(file.content, INPUT_COLUMNS[-1])
    workbook = _open(path, BytesIO(content), read_only=True, computed=computed)
    try:
        # ZEWNĘTRZNE: types-openpyxl opisuje ReadOnlyWorksheet.iter_rows jako Worksheet.iter_rows z self typu Worksheet, choć workbook.active skoroszytu otwartego tylko do odczytu to ReadOnlyWorksheet (types-openpyxl, openpyxl-stubs/worksheet/_read_only.pyi)
        sheet = cast(Worksheet, workbook.active)
        header = next(
            classified(
                path,
                sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=QUANTITY_COLUMNS[-1], values_only=True),
            ),
            (),
        )
        witness = file.sheet(sheet.title, HEADER_ROW, header, _forbidden_columns(header))
        check_worker_header(path, sheet.title, header)
        yield _Collective(file, sheet.title, header, content, _data_rows(path, sheet, witness, last_column))
    finally:
        workbook.close()


def _data_rows(
    path: Path, sheet: Worksheet, witness: WitnessedSheet, last_column: int
) -> Iterator[tuple[int, tuple[object, ...], ExcelRow]]:
    for number, cells in enumerate(
        classified(path, sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=last_column)), start=FIRST_DATA_ROW
    ):
        values = tuple(cell.value for cell in cells)
        if all(value is None for value in values[: INPUT_COLUMNS[-1]]):
            continue
        witness.row(number, values)
        yield number, cells, values


@dataclass(frozen=True)
class DataRows:
    header: Mapping[str, int]
    rows: list[DataRow]
    price_list: Mapping[str, str]


def read_data_rows(path: Path, files: DadFiles, *, despite_excel_lock: bool = False) -> DataRows:
    with _collective_sheet(path, files, last_column=DATA_ROW_COLUMNS[-1], despite_excel_lock=despite_excel_lock) as sheet:
        with unreadable_as_error(path):
            links = read_sheet_hyperlinks(sheet.content, sheet.title)
        rows: list[DataRow] = []
        highlights = LookReader()
        for number, cells, values in sheet.rows:
            row_links = links.row(number, values)
            with unreadable_as_error(path):
                rows.append(
                    DataRow(
                        number,
                        tuple(
                            DataCell(
                                values[column - 1],
                                highlights.of(cell),
                                (getattr(cell, "number_format", None) or GENERAL) if column in LOOK_COLUMNS else GENERAL,
                                row_links.get(column),
                            )
                            for column, cell in enumerate(cells, start=1)
                        ),
                    )
                )
    return DataRows(
        header_columns(sheet.header[: INPUT_COLUMNS[-1]]), rows, price_list(sheet.header, (*QUANTITY_COLUMNS, REMARKS_AMOUNT))
    )


def collective_workers(path: Path, files: DadFiles) -> frozenset[str]:
    file = files.read(path, despite_excel_lock=True)
    with unreadable_as_error(path), package_parts(file.content) as parts:
        workbook = office_document(parts)
        if workbook is None:
            raise KeyError("officeDocument")
        try:
            sheet = active_sheet(parts, workbook)
            if not sheet.worksheet:
                raise ValueError("aktywna karta to wykres")
            strings = next(
                (rel.target for rel in relationships(parts, workbook).values() if rel.kind.endswith("/sharedStrings")),
                None,
            )
            shared = SharedStrings(parts[strings] if strings else b"<sst/>")
            texts = dict(column_texts(parts[sheet.part], WORKER_COLUMN, HEADER_ROW, shared))
        except (UnsupportedShape, IrregularSheetData) as error:
            raise ValueError(str(error)) from error
    header: list[object] = [None] * INPUT_COLUMNS[-1]
    header[WORKER_COLUMN - 1] = texts.pop(HEADER_ROW, None)
    check_worker_header(path, sheet.title, header)
    found = {normalize_text(text) for row, text in texts.items() if row >= FIRST_DATA_ROW}
    found.discard("")
    return frozenset(found)


def price_list(header: Sequence[object], columns: Sequence[int] = QUANTITY_COLUMNS) -> dict[str, str]:
    return {
        get_column_letter(column): "" if column > len(header) or is_blank(header[column - 1]) else " ".join(str(header[column - 1]).split())
        for column in columns
    }


@dataclass(frozen=True)
class ComputedRow:
    number: int
    values: ExcelRow

    def value(self, column: str) -> _ExcelCellValue:
        index = column_index_from_string(column) - 1
        return self.values[index] if index < len(self.values) else None


@dataclass(frozen=True)
class ComputedRows:
    header: Mapping[str, int]
    rows: list[ComputedRow]
    content: bytes


def read_computed_rows(path: Path, files: DadFiles) -> ComputedRows:
    with _collective_sheet(path, files, last_column=AMOUNT_COLUMN, computed=True) as sheet:
        rows = [ComputedRow(number, values) for number, _, values in sheet.rows]
    return ComputedRows(header_columns(sheet.header[: INPUT_COLUMNS[-1]]), rows, sheet.file.content)


def workbook_content(path: Path) -> bytes:
    ensure_available(path)
    return file_bytes(path)


def template_content(path: Path) -> bytes:
    ensure_available(path)
    if path.suffix.lower() not in _WORKBOOK_SUFFIXES:
        raise WorkbookError(path, Problem.UNREADABLE)
    return file_bytes(path)


@contextmanager
def open_workbook(path: Path, content: bytes, *, read_only: bool) -> Iterator[Workbook]:
    workbook = _open(path, BytesIO(content), read_only=read_only)
    try:
        yield workbook
    finally:
        workbook.close()
