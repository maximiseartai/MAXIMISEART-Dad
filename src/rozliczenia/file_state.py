"""Stan pliku albo folderu na dysku: jest, nie ma go albo jest niedostępny.

Jedyne miejsce reguły, który błąd systemu plików znaczy brak, a który niedostępność. Brak to ``FileNotFoundError`` i
``NotADirectoryError`` (plik w miejscu folderu nad ścieżką); każdy inny ``OSError`` (np. brak dostępu do folderu, plik
trzymany przez OneDrive) to niedostępność, o której tata dostaje inny Komunikat niż o braku pliku. ``Path.exists`` i
``Path.is_file`` od Pythona 3.14 dają w folderze bez dostępu ``False``, więc plik niedostępny byłby z nimi brakiem.
"""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Literal

__all__ = ["FileState", "PathState", "file_state", "folder_entries", "path_state", "remove_file"]

PathState = Literal["file", "folder", "missing", "inaccessible"]
FileState = Literal["file", "missing", "inaccessible"]

_ABSENT = (FileNotFoundError, NotADirectoryError)


def path_state(path: Path) -> PathState:
    """Czy ``path`` jest plikiem, folderem, nie ma go (także gdy jest czymś innym) albo jest niedostępny."""

    try:
        status = path.stat()
    except _ABSENT:
        return "missing"
    except OSError:
        return "inaccessible"
    if stat.S_ISREG(status.st_mode):
        return "file"
    return "folder" if stat.S_ISDIR(status.st_mode) else "missing"


def file_state(path: Path) -> FileState:
    """Czy ``path`` jest plikiem, nie ma go (także gdy na jego miejscu jest folder) albo jest niedostępny."""

    state = path_state(path)
    return "missing" if state == "folder" else state


def folder_entries(directory: Path) -> list[os.DirEntry[str]] | None:
    """Wpisy folderu z jednego listowania; ``None``, gdy folderu nie ma, a ``OSError``, gdy jest niedostępny."""

    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except _ABSENT:
        return None


def remove_file(path: Path) -> None:
    """Usuwa plik ``path``; pliku, którego nie ma, nie zgłasza, a ``OSError`` znaczy, że jest, ale go nie usunięto."""

    with suppress(*_ABSENT):
        path.unlink()
