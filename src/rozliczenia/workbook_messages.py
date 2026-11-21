from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .message import IF_ERROR_RETURNS, DadFile, Message, file_label
from .workbook_files import LayoutFault, Problem, WorkbookError, excel_lock_file


@dataclass(frozen=True)
class WorkbookMessages:
    missing: Callable[[Path], Message]
    open_in_excel: Callable[[Path], Message]
    inaccessible: Callable[[Path], Message]
    unreadable: Callable[[Path], Message]
    layout: Callable[[Path, LayoutFault | None], Message] | None = None
    has_data: Callable[[Path], Message] | None = None


def unusable(error: WorkbookError, messages: WorkbookMessages) -> Message:
    path = error.path
    match error.problem:
        case Problem.MISSING:
            return messages.missing(path)
        case Problem.OPEN_IN_EXCEL:
            return messages.open_in_excel(path)
        case Problem.INACCESSIBLE:
            return messages.inaccessible(path)
        case Problem.UNREADABLE:
            return messages.unreadable(path)
        case Problem.LAYOUT:
            return messages.unreadable(path) if messages.layout is None else messages.layout(path, error.fault)
        case Problem.HAS_DATA:
            return messages.unreadable(path) if messages.has_data is None else messages.has_data(path)
        case _:
            assert_never(error.problem)


@dataclass(frozen=True)
class DadWorkbook:
    name: str
    genitive: str
    dad_file: DadFile
    unchanged: str
    again: str
    closing: str = ""


# ZEWNĘTRZNE: Excel zamknięty awaryjnie zostawia obok skoroszytu plik właściciela ~$<nazwa>, a ten wygląda dalej na skoroszyt otwarty w Excelu (Microsoft Support, „The document is locked for editing by another user”)
def lock_hint(path: Path, again: str) -> str:
    return (
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu pozostawiony plik "
        f"{excel_lock_file(path).name} i {again}."
    )


def open_in_excel(code: str, path: Path, workbook: DadWorkbook) -> Message:
    return Message(
        code=code,
        dad_file=workbook.dad_file,
        what=f"{workbook.name} jest otwarty w Excelu. {workbook.unchanged}",
        where=file_label(path),
        action=f"{workbook.closing or f'Zapisz i zamknij {workbook.name} w Excelu, potem {workbook.again}.'} "
        f"{lock_hint(path, workbook.again)}",
    )


def not_synced(code: str, path: Path, workbook: DadWorkbook) -> Message:
    return Message(
        code=code,
        dad_file=workbook.dad_file,
        what=(
            f"Nie można teraz odczytać {workbook.genitive}. Plik może być zajęty przez inny program albo czekać na "
            f"pobranie z OneDrive. {workbook.unchanged}"
        ),
        where=file_label(path),
        action=(
            f"Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy {workbook.name} otwiera się w Excelu. "
            f"Zamknij go i {workbook.again}. {IF_ERROR_RETURNS}"
        ),
    )
