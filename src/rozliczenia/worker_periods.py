"""Wykonawca w okresach (ADR 0032): czy login z Listy Wykonawców występuje w którymś okresie i w których okresach leży
już Rozliczenie pracownika z daną nazwą.

Login występuje w okresie, gdy stoi w ``WYKONAWCA`` Rejestru zleceń albo Pliku zbiorczego któregoś Folderu okresu. Od
tego zależy, czy tata może usunąć Wykonawcę albo jego login: okres rozliczany ponownie zatrzymałby się na nieznanym
Wykonawcy. Najpierw Rejestr zleceń, potem Pliki zbiorcze od najnowszego okresu; pierwsze trafienie kończy szukanie, a
``NotInPeriods`` daje dopiero pełne przejście. Każdy plik, którego nie da się przeczytać, i nieustawiony albo
niedostępny Rejestr zleceń lub folder okresów to ``Unchecked``: „nie występuje” musi przejść przez każdy plik.

Pliki czyta uchwyt plików taty, tylko kolumnę ``WYKONAWCA`` z XML (``register_file.OrderSheets.workers``,
``workbook_files.collective_workers``), bez openpyxl. Ostrzeżenie o starej nazwie patrzy tylko na listy plików
Folderów rozliczeń pracowników, bez czytania skoroszytów: Rozliczenie pracownika leży tylko tam, gdzie Wykonawca miał
zlecenia.
"""

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
    """Login stoi w ``WYKONAWCA`` Rejestru zleceń."""


@dataclass(frozen=True)
class InPeriod:
    """Login stoi w ``WYKONAWCA`` Pliku zbiorczego okresu ``token``."""

    token: str


@dataclass(frozen=True)
class NotInPeriods:
    """Loginu nie ma w Rejestrze zleceń ani w żadnym Pliku zbiorczym: każdy plik został przeczytany."""


UncheckedPlace = Literal["not_set", "register", "periods_directory", "collective_file"]
"""Czego nie dało się sprawdzić: Rejestr zleceń albo folder okresów nie są ustawione (``not_set``), Rejestru zleceń nie
ma albo nie da się go przeczytać (``register``), tak samo folderu okresów (``periods_directory``) albo Pliku zbiorczego
okresu (``collective_file``)."""


@dataclass(frozen=True)
class Unchecked:
    """Nie wiadomo, czy login występuje w okresie; ``token``: okres Pliku zbiorczego przy ``collective_file``."""

    place: UncheckedPlace
    token: str | None = None


Presence = InRegister | InPeriod | NotInPeriods | Unchecked


class WorkerPeriods:
    """Szukanie loginów w okresach jednym uchwytem plików taty pracy Centrum.

    Pamięta Wykonawców każdego przeczytanego Pliku zbiorczego z jego rozmiarem i chwilą zmiany z listowania Folderu
    okresu, więc następne szukanie czyta tylko Pliki zbiorcze zmienione od tamtej pory: pełne przejście czyta Plik
    zbiorczy każdego okresu, a plik „tylko online” OneDrive pobiera się przy każdym odczycie. Rejestr zleceń czyta za
    każdym razem, bo zmienia się codziennie.
    Pamięć żyje tyle co praca Centrum.
    """

    def __init__(self, files: DadFiles) -> None:
        self._files = files
        self._lock = threading.Lock()
        self._known: dict[Path, tuple[_Stamp, frozenset[str]]] = {}

    def find(self, logins: Iterable[str], register: Path | None, periods_directory: Path | None) -> Presence:
        """Czy któryś z ``logins`` (porównanych po ``normalize_text``) występuje w okresie: Rejestr zleceń
        ``register``, potem Pliki zbiorcze Folderów okresu w folderze okresów ``periods_directory`` od najnowszego."""

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
        """Login z ``wanted`` w Pliku zbiorczym okresu ``folder``; ``None``: nie ma go tam albo okres nie ma Pliku
        zbiorczego."""

        token = folder.period.token
        path = folder.collective_file
        try:
            listed = {entry.name: entry for entry in folder_entries(folder.directory) or ()}
        except OSError:
            return Unchecked("collective_file", token)
        entry = listed.get(path.name)
        if entry is None:
            # Windows i macOS nie rozróżniają wielkości liter, więc plik może mieć w listowaniu inną nazwę.
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
"""Rozmiar i chwila zmiany (ns) pliku z listowania folderu."""


def _stamp(entry: os.DirEntry[str]) -> _Stamp | None:
    """Rozmiar i chwila zmiany wpisu; Windows podaje je z listowania, bez otwierania pliku. ``None``: system ich nie
    podał, więc plik czyta się od nowa."""

    try:
        status = entry.stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


def old_name_periods(old: str, new: str, periods_directory: Path | None) -> tuple[str, ...]:
    """Tokeny okresów (od najnowszego), w których Folderze rozliczeń pracowników leży Rozliczenie pracownika z nazwą
    ``old``, gdy ``new`` daje inny plik (``normalize_text``, jak ``WorkerList.of``).

    Ostrzeżenie, nie straż: folder okresów nieustawiony albo niedostępny i Folder okresu, którego nie da się
    wylistować, nie dają okresu.
    """

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
