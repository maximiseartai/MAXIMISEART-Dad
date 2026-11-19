"""Plik, którego system nie daje teraz czytać, na każdym systemie i każdą drogą odczytu: hak audytu Pythona (PEP 578).

Każde otwarcie pliku w Pythonie (``open``, ``Path.read_bytes``, ``os.open``) zgłasza zdarzenie audytu ``open``, zanim
system otworzy plik, a wyjątek z haka przerywa otwarcie. Hak odmawia więc odczytu pliku z ``denied`` tak samo jak
antywirus albo OneDrive (``PermissionError``), a pliku nie zmienia: ``stat``, listowanie folderu i zapis działają.
Tak samo widzi otwarcia do odczytu w folderze ``watched``, więc test wie, które pliki czyta krok, bez listy w kodzie,
i zapisy w nim (otwarcie do zapisu, zamiana i usunięcie pliku), więc wie też, które pliki krok czytał przed zapisem.

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
from typing import Final

_LOCK = threading.Lock()
_WRITES = {"os.rename": 1, "os.remove": 0}
"""Zdarzenia audytu zapisu pliku poza ``open`` i miejsce ścieżki zapisanej w ich argumentach: ``os.rename`` (także
``os.replace`` i ``Path.replace``) zapisuje cel, ``os.remove`` (także ``os.unlink``) usuwa plik."""


@dataclass
class Reads:
    """Pliki w ``watched``, które blok ``reading`` otwierał do odczytu (``seen``, także odebrane i brakujące), i kolejność
    jego odczytów i zapisów w ``watched``."""

    watched: Path
    denied: frozenset[Path]
    seen: set[Path] = field(default_factory=set)
    order: list[tuple[bool, Path]] = field(default_factory=list)
    """Odczyt (``False``) albo zapis (``True``) i plik, w kolejności zdarzeń."""
    listed: set[Path] = field(default_factory=set)

    def before_last_write(self, outside: Path) -> set[Path]:
        """Pliki czytane przed ostatnim zapisem bloku poza folderem ``outside`` (np. Logi): odczyt po nim nie zmienia
        niczego, co blok zapisał."""

        writes = [index for index, (write, path) in enumerate(self.order) if write and not path.is_relative_to(outside)]
        last = writes[-1] if writes else 0
        return {path for write, path in self.order[:last] if not write}


_LISTINGS: Final = frozenset({"os.listdir", "os.scandir"})
_active: Reads | None = None
_installed = False


def _opened_for_reading(mode: object, flags: object) -> bool:
    if isinstance(mode, str):
        return not any(letter in mode for letter in "wax+")
    return isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR) == 0


def _target(event: str, arguments: tuple[object, ...]) -> tuple[bool, Path] | None:
    """Zapis (``True``) albo odczyt i plik zdarzenia audytu; ``None``: zdarzenie nie otwiera, nie zamienia i nie usuwa
    pliku o ścieżce."""

    if event == "open":
        target, mode, flags = arguments
        write = not _opened_for_reading(mode, flags)
    elif event in _WRITES:
        target, write = arguments[_WRITES[event]], True
    else:
        return None
    if not isinstance(target, (str, bytes, os.PathLike)):
        return None
    return write, Path(os.path.abspath(os.fsdecode(target)))


def _hook(event: str, arguments: tuple[object, ...]) -> None:
    reads = _active
    if reads is None:
        return
    if event in _LISTINGS:
        _list(reads, arguments[0])
        return
    opened = _target(event, arguments)
    if opened is None or not opened[1].is_relative_to(reads.watched):
        return
    write, path = opened
    with _LOCK:
        reads.order.append(opened)
        if not write:
            reads.seen.add(path)
    if not write and path in reads.denied:
        raise PermissionError(errno.EACCES, "plik trzymany przez system (test)", str(path))


def _list(reads: Reads, folder: object) -> None:
    if folder is None:
        folder = "."
    if not isinstance(folder, (str, bytes, os.PathLike)):
        return
    path = Path(os.path.abspath(os.fsdecode(folder)))
    if path.is_relative_to(reads.watched):
        with _LOCK:
            reads.listed.add(path)


@contextmanager
def reading(watched: Path, denied: frozenset[Path] = frozenset()) -> Iterator[Reads]:
    """Do końca bloku odczyt plików ``denied`` pada z ``PermissionError``; zwraca odczyty i zapisy bloku w ``watched``,
    pełne po wyjściu z bloku."""

    global _active, _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
    assert _active is None, "Jeden blok reading naraz."
    _active = Reads(Path(os.path.abspath(watched)), frozenset(Path(os.path.abspath(path)) for path in denied))
    try:
        yield _active
    finally:
        _active = None
