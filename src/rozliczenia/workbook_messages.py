"""Komunikat o skoroszycie, którego nie da się użyć (``WorkbookError``): jeden wybór po ``Problem`` dla każdego katalogu.

Katalog procesu albo strony Centrum opisuje każdy swój skoroszyt jako ``WorkbookMessages``: swój Komunikat na każdy
``Problem``. ``unusable`` wybiera z niego Komunikat błędu, więc nowy ``Problem`` to nowe pole, które mypy każe dać w
każdym katalogu. Kody i zdania, których nikt inny nie mówi (brak pliku, plik nieczytelny, zły układ), zostają w katalogu.

Zdania wspólne Komunikatów o pliku taty składa tylko ten moduł, z pliku, ogona „Co się stało” (co zostało bez zmian) i
zwrotu ponowienia (``DadWorkbook``): plik otwarty w Excelu (``open_in_excel``), plik, którego OneDrive jeszcze nie oddał
(``not_synced``), i pozostawiony plik blokady Excela (``lock_hint``), który po awarii Excela trzyma skoroszyt „otwarty”.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .message import IF_ERROR_RETURNS, DadFile, Message, file_label
from .workbook_files import LayoutFault, Problem, WorkbookError, excel_lock_file


@dataclass(frozen=True)
class WorkbookMessages:
    """Komunikaty jednego skoroszytu w jednym katalogu, po jednym na ``Problem``.

    ``layout`` dostaje też miejsce złego układu (``WorkbookError.fault``); ``layout`` i ``has_data`` ``None``: jak
    ``unreadable``.
    """

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
    """Plik taty w zdaniach wspólnych: nazwa w mianowniku i dopełniaczu, ogon „Co się stało” i zwrot ponowienia.

    Np. ``DadWorkbook("Rejestr zleceń", "Rejestru zleceń", "order_register", "Nie utworzono żadnego pliku.",
    "uruchom ponownie")``.
    """

    name: str
    genitive: str
    dad_file: DadFile
    unchanged: str
    again: str


def lock_hint(path: Path, again: str) -> str:
    """Zdanie „Co zrobić” o pliku blokady skoroszytu ``path``, który zostaje po awarii Excela; narzędzie go nie usuwa."""

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
        action=f"Zapisz i zamknij {workbook.name} w Excelu, potem {workbook.again}. {lock_hint(path, workbook.again)}",
    )


def not_synced(code: str, path: Path, workbook: DadWorkbook) -> Message:
    """System nie oddał bajtów pliku taty ``path`` (np. zajęty przez inny program albo OneDrive bez sieci)."""

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
