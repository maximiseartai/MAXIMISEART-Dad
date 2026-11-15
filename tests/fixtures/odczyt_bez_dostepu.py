"""Plik, którego system nie daje teraz czytać, na każdym systemie i każdą drogą odczytu: hak audytu Pythona (PEP 578).

Każde otwarcie pliku w Pythonie (``open``, ``Path.read_bytes``, ``os.open``) zgłasza zdarzenie audytu ``open``, zanim
system otworzy plik, a wyjątek z haka przerywa otwarcie. Hak odmawia więc odczytu pliku z ``denied`` tak samo jak
antywirus albo OneDrive (``PermissionError``), a pliku nie zmienia: ``stat``, listowanie folderu i zapis działają.
Tak samo widzi otwarcia do odczytu w folderze ``watched``, więc test wie, które pliki czyta krok, bez listy w kodzie.

Haka nie da się zdjąć (PEP 578), więc instaluje się raz na proces i bez ``reading`` niczego nie robi.
Granicę haka pokazują próbki ``ZNANE_LUKI_ODCZYTU`` w ``tests/test_centrum_rozliczen.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
import os
from pathlib import Path
import sys
import threading

_LOCK = threading.Lock()


@dataclass
class _Reading:
    watched: Path
    denied: frozenset[Path]
    seen: set[Path] = field(default_factory=set)


_active: _Reading | None = None
_installed = False


def _opened_for_reading(mode: object, flags: object) -> bool:
    if isinstance(mode, str):
        return not any(letter in mode for letter in "wax+")
    return isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR) == 0


def _hook(event: str, arguments: tuple[object, ...]) -> None:
    if event != "open" or _active is None:
        return
    target, mode, flags = arguments
    if not isinstance(target, (str, bytes, os.PathLike)) or not _opened_for_reading(mode, flags):
        return
    path = Path(os.path.abspath(os.fsdecode(target)))
    reading = _active
    if not path.is_relative_to(reading.watched):
        return
    with _LOCK:
        reading.seen.add(path)
    if path in reading.denied:
        raise PermissionError(errno.EACCES, "plik trzymany przez system (test)", str(path))


@contextmanager
def reading(watched: Path, denied: frozenset[Path] = frozenset()) -> Iterator[set[Path]]:
    """Do końca bloku odczyt plików ``denied`` pada z ``PermissionError``; zwraca zbiór plików w ``watched``, które
    blok otwierał do odczytu (także te z ``denied``), pełny po wyjściu z bloku."""

    global _active, _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
    assert _active is None, "Jeden blok reading naraz."
    _active = _Reading(
        Path(os.path.abspath(watched)),
        frozenset(Path(os.path.abspath(path)) for path in denied),
    )
    try:
        yield _active.seen
    finally:
        _active = None
