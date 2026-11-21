from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import hashlib
from pathlib import Path
from typing import Literal

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from .row_positions import UNDER_HEADER, AbovePaste, RowPositions

TypedKind = Literal["datetime", "time", "timedelta", "other"]


@dataclass(frozen=True)
class Typed:
    kind: TypedKind
    text: str


CellValue = bool | int | float | str | Typed


@dataclass(frozen=True)
class Fingerprint:
    size: int
    modified_at: datetime | None
    sha256: str


@dataclass(frozen=True)
class CopiedRow:
    number: int
    cells: Mapping[str, CellValue]


@dataclass(frozen=True)
class PasteFacts:
    shifted_row: int | None = None
    uncertain_rows: tuple[int, ...] = ()
    last_ordered_row: int | None = None
    yellow_row: int | None = None
    traced_rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class CopiedSheet:
    name: str
    header_row: int
    columns: Mapping[str, str]
    rows: tuple[CopiedRow, ...]
    empty_rows: tuple[int, ...]
    paste: PasteFacts = PasteFacts()


@dataclass(frozen=True)
class CopiedFile:
    name: str
    fingerprint: Fingerprint
    sheets: tuple[CopiedSheet, ...]
    folders: tuple[str, ...] = ()


Values = Sequence[object] | Mapping[int, object]


@dataclass
class SheetCopy:
    name: str
    header_row: int
    header: Mapping[int, object]
    forbidden: frozenset[int]
    copied_columns: frozenset[int] | None = None
    date_column: int | None = None
    above: AbovePaste | None = None
    span: frozenset[int] | None = None
    _rows: list[tuple[int, Values, RowPositions]] = field(default_factory=list)
    _empty: list[int] = field(default_factory=list)

    def row(self, number: int, values: Values, positions: RowPositions = UNDER_HEADER) -> None:
        self._rows.append((number, values, positions))

    def empty_rows(self, numbers: Sequence[int]) -> None:
        self._empty.extend(numbers)

    def copied(self) -> CopiedSheet:
        columns = {
            get_column_letter(column): str(name)
            for column, name in sorted(self.header.items())
            if column not in self.forbidden and name is not None and str(name).strip()
        }
        shifted = [number for number, _, positions in self._rows if positions.read]
        if len(shifted) > 1:
            raise ValueError(f"Arkusz {self.name} ma więcej niż jeden przesunięty wiersz: {shifted}")
        above = self.above
        return CopiedSheet(
            self.name,
            self.header_row,
            columns,
            tuple(CopiedRow(number, self._cells(values, positions)) for number, values, positions in self._rows),
            tuple(self._empty),
            PasteFacts(
                shifted_row=shifted[0] if shifted else None,
                uncertain_rows=tuple(number for number, _, positions in self._rows if positions.uncertain),
                last_ordered_row=None if above is None else above.last_ordered,
                yellow_row=None if above is None else above.yellow,
                traced_rows=tuple(number for number, _, positions in self._rows if positions.traced),
            ),
        )

    def _cells(self, values: Values, positions: RowPositions) -> dict[str, CellValue]:
        numbered = _numbered(values)
        read, known = positions.read, positions.known
        span = self.copied_columns if self.span is None else self.span
        placed = {
            column + read: value
            for column, value in numbered.items()
            if _allowed(column + read, self.forbidden, self.copied_columns)
            and all(_allowed(column + offset, self.forbidden, span) for offset in known)
        }
        if self.date_column is not None:
            when = numbered.get(self.date_column - read)
            if isinstance(when, datetime):
                placed[self.date_column] = when
        return _cells(placed, self.forbidden)



@dataclass
class WorkbookCopy:
    name: str
    content: bytes
    modified_at: datetime | None
    _sheets: list[SheetCopy] = field(default_factory=list)
    folders: tuple[str, ...] = ()

    def sheet(
        self,
        name: str,
        header_row: int,
        header: Values,
        forbidden: Collection[int],
        *,
        copied_columns: Collection[int] | None = None,
        date_column: int | None = None,
        above: AbovePaste | None = None,
        span: Collection[int] | None = None,
    ) -> SheetCopy:
        sheet = SheetCopy(
            name,
            header_row,
            _numbered(header),
            frozenset(forbidden),
            None if copied_columns is None else frozenset(copied_columns),
            date_column,
            above,
            None if span is None else frozenset(span),
        )
        self._sheets.append(sheet)
        return sheet

    def copied(self) -> CopiedFile:
        fingerprint = Fingerprint(len(self.content), self.modified_at, hashlib.sha256(self.content).hexdigest())
        return CopiedFile(self.name, fingerprint, tuple(sheet.copied() for sheet in self._sheets), self.folders)


class InputCopy:
    def __init__(self) -> None:
        self._files: list[WorkbookCopy] = []

    def workbook(self, path: Path, content: bytes, modified: datetime | None) -> WorkbookCopy:
        folders = tuple(folder for folder in (path.parent.parent.name, path.parent.name) if folder)
        copy = WorkbookCopy(path.name, content, modified, folders=folders)
        self._files.append(copy)
        return copy

    def files(self) -> tuple[CopiedFile, ...]:
        return tuple(copy.copied() for copy in self._files)


def _allowed(column: int, forbidden: frozenset[int], columns: frozenset[int] | None) -> bool:
    return column not in forbidden and (columns is None or column in columns)


def _numbered(values: Values) -> Mapping[int, object]:
    return values if isinstance(values, Mapping) else dict(enumerate(values, start=1))


def _cells(values: Values, forbidden: frozenset[int]) -> dict[str, CellValue]:
    numbered = _numbered(values)
    return {
        get_column_letter(column): _value(value)
        for column, value in numbered.items()
        if value is not None and column not in forbidden
    }


def _value(value: object) -> CellValue:
    match value:
        case bool() | int() | float() | str():
            return value
        case datetime():
            return Typed("datetime", value.isoformat())
        case time():
            return Typed("time", value.isoformat())
        case timedelta():
            return Typed("timedelta", repr(value.total_seconds()))
        case ArrayFormula():
            return str(value.text)
        case _:
            return Typed("other", type(value).__name__)
