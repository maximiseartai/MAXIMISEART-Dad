from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import register_file, workbook_files
from .dad_files import DadFiles
from .file_state import file_state, folder_entries
from .period_folder import PeriodFolder, PeriodFolderInaccessible, scan_period_folders
from .register_file import OrderSheets
from .text import normalize_text
from .workbook_files import WorkbookError
from .workbook_parts import UnsupportedShape

__all__ = [
    "InPeriod",
    "InRegister",
    "NotInPeriods",
    "Presence",
    "Unchecked",
    "WorkerPeriods",
    "old_name_periods",
]


@dataclass(frozen=True)
class InRegister:
    ...


@dataclass(frozen=True)
class InPeriod:
    token: str


@dataclass(frozen=True)
class NotInPeriods:
    ...


UncheckedPlace = Literal["not_set", "register", "periods_directory", "collective_file"]


@dataclass(frozen=True)
class Unchecked:
    place: UncheckedPlace
    token: str | None = None


Presence = InRegister | InPeriod | NotInPeriods | Unchecked


class WorkerPeriods:
    def __init__(self, files: DadFiles) -> None:
        self._files = files
        self._lock = threading.Lock()
        self._known: dict[Path, tuple[_Stamp, frozenset[str]]] = {}

    def find(self, logins: Iterable[str], register: Path | None, periods_directory: Path | None) -> Presence:
        wanted = frozenset(normalize_text(login) for login in logins)
        if register is None or periods_directory is None:
            return Unchecked("not_set")
        try:
            sheets = register_file.read(register, self._files, despite_excel_lock=True).order_sheets
            if not isinstance(sheets, OrderSheets):
                return Unchecked("register")
            if wanted & sheets.workers():
                return InRegister()
        except (WorkbookError, UnsupportedShape):
            return Unchecked("register")
        try:
            found = scan_period_folders(periods_directory)
        except PeriodFolderInaccessible:
            return Unchecked("periods_directory")
        if found.periods_directory_missing:
            return Unchecked("periods_directory")
        for folder in sorted(found.found(), key=lambda folder: folder.period.tuesday, reverse=True):
            presence = self._in_collective_file(folder, wanted)
            if presence is not None:
                return presence
        return NotInPeriods()

    def _in_collective_file(self, folder: PeriodFolder, wanted: frozenset[str]) -> InPeriod | Unchecked | None:
        token = folder.period.token
        path = folder.collective_file
        try:
            listed = {entry.name: entry for entry in folder_entries(folder.directory) or ()}
        except OSError:
            return Unchecked("collective_file", token)
        entry = listed.get(path.name)
        if entry is None:
            match file_state(path):
                case "missing":
                    return None
                case "inaccessible":
                    return Unchecked("collective_file", token)
                case "file":
                    pass
        stamp = None if entry is None else _stamp(entry)
        with self._lock:
            known = self._known.get(path)
        if stamp is not None and known is not None and known[0] == stamp:
            workers = known[1]
        else:
            try:
                workers = workbook_files.collective_workers(path, self._files)
            except WorkbookError:
                return Unchecked("collective_file", token)
            if stamp is not None:
                with self._lock:
                    self._known[path] = (stamp, workers)
        return InPeriod(token) if wanted & workers else None


_Stamp = tuple[int, int]


def _stamp(entry: os.DirEntry[str]) -> _Stamp | None:
    # ZEWNĘTRZNE: os.DirEntry.stat w Windows daje rozmiar i chwilę zmiany z listowania folderu, bez wywołania systemowego na samym pliku, chyba że follow_symlinks=True, a wpis to reparse point, np. dowiązanie symboliczne albo złącze katalogu (dokumentacja Pythona, os.DirEntry.stat)
    try:
        status = entry.stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


def old_name_periods(old: str, new: str, periods_directory: Path | None) -> tuple[str, ...]:
    if periods_directory is None or normalize_text(old) == normalize_text(new):
        return ()
    try:
        folders = scan_period_folders(periods_directory).found()
    except PeriodFolderInaccessible:
        return ()
    found: list[str] = []
    for folder in sorted(folders, key=lambda folder: folder.period.tuesday, reverse=True):
        wanted = normalize_text(folder.worker_settlement(old).name)
        try:
            files = folder.worker_settlement_files()
        except PeriodFolderInaccessible:
            continue
        if any(normalize_text(path.name) == wanted for path in files):
            found.append(folder.period.token)
    return tuple(found)
