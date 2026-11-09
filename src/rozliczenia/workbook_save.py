"""Atomowy zapis skoroszytu: plik docelowy zmienia się dopiero po udanym zapisie całości.

Każdy zapis skoroszytu idzie do pliku tymczasowego obok celu i dopiero potem podmienia cel (``os.replace``);
nieudany zapis to ``WorkbookSaveError``, cel pozostaje bez zmian, a plik tymczasowy nie zostaje. openpyxl nie
zapisuje wiernie części ``xl/externalLinks/*``, więc skoroszyt zapisany przez openpyxl dostaje je bajtowo z pliku,
z którego go wczytano; błąd przygotowania albo przywrócenia tych części to ``ExternalLinksError``.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from collections.abc import Callable
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import IO

from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook

_EXTERNAL_LINKS_PREFIX = "xl/externalLinks/"
_ExternalLinkParts = dict[str, tuple[zipfile.ZipInfo, bytes]]
_WORKBOOK_FILE_ERRORS = (OSError, InvalidFileException, ValueError, zipfile.BadZipFile)


class SaveProblem(Enum):
    """Krok zapisu skoroszytu, który się nie udał."""

    TEMPORARY_FILE = "plik tymczasowy"
    """Obok celu nie da się utworzyć pliku tymczasowego, np. folder celu nie istnieje."""
    INVALID_VALUE = "wartość niedozwolona w XML"
    """Wpisywana wartość ma znak, którego skoroszyt nie przyjmuje."""
    CONTENT = "zapis treści"
    """Treści skoroszytu nie da się zapisać do pliku tymczasowego."""
    REPLACE = "podmiana"
    """System odmówił podmiany celu plikiem tymczasowym."""
    EXTERNAL_LINKS_UNREADABLE = "nieczytelne odwołania zewnętrzne"
    """Nie da się odczytać ``xl/externalLinks/*`` skoroszytu, z którego są kopiowane (celu albo Wzorca)."""
    EXTERNAL_LINKS_NOT_RESTORED = "nieprzywrócone odwołania zewnętrzne"
    """Nie da się przywrócić ``xl/externalLinks/*`` w pliku tymczasowym."""


class WorkbookSaveError(Exception):
    """Skoroszyt ``target`` nie został zapisany i pozostał bez zmian; ``problem`` mówi dlaczego, bez zdania dla taty.

    ``str(error)`` to krok i nazwa pliku bez folderu, np. ``podmiana: Plik.xlsx``, więc zapis wyjątku do logu nie
    przenosi pełnej ścieżki z nazwą konta.
    """

    def __init__(self, target: Path, problem: SaveProblem) -> None:
        super().__init__(f"{problem.value}: {target.name}")
        self.target = target
        self.problem = problem


class ExternalLinksError(WorkbookSaveError):
    """Nie można przygotować ani przywrócić części ``xl/externalLinks/*``."""


def write_atomically(
    target: Path, write: Callable[[Path], None], *, replace: Callable[[Path, Path], None] | None = None
) -> None:
    """``write`` zapisuje skoroszyt do pliku tymczasowego obok ``target``; dopiero potem ``target`` jest podmieniany.

    Nieudany zapis to ``WorkbookSaveError`` (albo błąd zapisu zgłoszony przez ``write`` albo inny niż ``OSError``
    błąd ``replace``); plik tymczasowy nigdy nie zostaje, a ``target`` zmienia się tylko po udanym zapisie całości.
    """

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.stem}.", suffix=".xlsx", dir=target.parent
        )
        os.close(file_descriptor)
    except OSError as exc:
        raise WorkbookSaveError(target, SaveProblem.TEMPORARY_FILE) from exc
    temporary_path = Path(temporary_name)
    try:
        write(temporary_path)
        try:
            (os.replace if replace is None else replace)(temporary_path, target)
        except OSError as exc:
            raise WorkbookSaveError(target, SaveProblem.REPLACE) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def save_workbook(workbook: Workbook, target: Path) -> None:
    """Atomowo zapisuje skoroszyt pod istniejący ``target``, zachowując 1:1 jego odwołania zewnętrzne."""

    _save_atomically(workbook, target, _read_external_link_parts(target, target))


def save_from_template(workbook: Workbook, target: Path, template: bytes) -> None:
    """Atomowo zapisuje pod ``target`` skoroszyt wczytany z bajtów Wzorca ``template`` z jego ``xl/externalLinks/*``."""

    _save_atomically(workbook, target, _read_external_link_parts(BytesIO(template), target))


def _read_external_link_parts(source: Path | IO[bytes], target: Path) -> _ExternalLinkParts:
    try:
        return _external_link_parts(source)
    except _WORKBOOK_FILE_ERRORS as exc:
        raise ExternalLinksError(target, SaveProblem.EXTERNAL_LINKS_UNREADABLE) from exc


def _save_atomically(workbook: Workbook, target: Path, parts: _ExternalLinkParts) -> None:
    def write(path: Path) -> None:
        try:
            workbook.save(path)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise WorkbookSaveError(target, SaveProblem.CONTENT) from exc
        try:
            _restore_external_link_parts(path, parts)
        except _WORKBOOK_FILE_ERRORS as exc:
            raise ExternalLinksError(target, SaveProblem.EXTERNAL_LINKS_NOT_RESTORED) from exc

    write_atomically(target, write)


def _external_link_parts(source: Path | IO[bytes]) -> _ExternalLinkParts:
    with zipfile.ZipFile(source, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith(_EXTERNAL_LINKS_PREFIX)
        }


def _restore_external_link_parts(path: Path, parts: _ExternalLinkParts) -> None:
    if not parts:
        return
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.links.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                if info.filename.startswith(_EXTERNAL_LINKS_PREFIX):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
