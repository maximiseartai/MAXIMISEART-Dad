from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from rozliczenia.client_data import READ_VALUES
from rozliczenia.input_copy import CellValue, CopiedFile, CopiedSheet, Typed, TypedKind


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LoggedTyped(_Record):
    type: TypedKind
    text: str


LoggedCell = bool | int | float | str | LoggedTyped


def _cell(value: CellValue) -> LoggedCell:
    return LoggedTyped(type=value.kind, text=value.text) if isinstance(value, Typed) else value


class LoggedRow(_Record):
    row: int
    cells: Annotated[dict[str, LoggedCell], READ_VALUES]


class LoggedSheet(_Record):
    sheet: str
    header_row: int
    columns: dict[str, str]
    rows: list[LoggedRow]
    empty_rows: list[int]
    shifted_row: int | None = None
    uncertain_rows: list[int] = []
    last_ordered_row: int | None = None
    yellow_row: int | None = None

    @classmethod
    def of(cls, sheet: CopiedSheet) -> LoggedSheet:
        paste = sheet.paste
        return cls(
            sheet=sheet.name,
            header_row=sheet.header_row,
            columns=dict(sheet.columns),
            rows=[
                LoggedRow(row=row.number, cells={letter: _cell(value) for letter, value in row.cells.items()})
                for row in sheet.rows
            ],
            empty_rows=list(sheet.empty_rows),
            shifted_row=paste.shifted_row,
            uncertain_rows=list(paste.uncertain_rows),
            last_ordered_row=paste.last_ordered_row,
            yellow_row=paste.yellow_row,
        )


class LoggedFingerprint(_Record):
    size: int
    modified_at: datetime | None
    sha256: str


class LoggedInputFile(_Record):
    name: str
    fingerprint: LoggedFingerprint
    sheets: list[LoggedSheet]
    folders: list[str] = []

    @classmethod
    def of(cls, copied: CopiedFile) -> LoggedInputFile:
        fingerprint = copied.fingerprint
        return cls(
            name=copied.name,
            fingerprint=LoggedFingerprint(
                size=fingerprint.size, modified_at=fingerprint.modified_at, sha256=fingerprint.sha256
            ),
            sheets=[LoggedSheet.of(sheet) for sheet in copied.sheets],
            folders=list(copied.folders),
        )
