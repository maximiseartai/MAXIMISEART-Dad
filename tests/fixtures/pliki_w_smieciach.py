"""Plik, który test zostawił otwarty w śmieciach (#1923).

Obiekt pliku trzymany tylko przez cykl referencji (skoroszyt openpyxl ``read_only=True`` bez ``close()``) zamyka dopiero
``gc``, czyli często w oknie innego testu na tym samym workerze, a ``ResourceWarning`` jego finalizera wywraca test, który
łapie własne ostrzeżenia: w #1923 test portu opiekuna dostał plik INTERMAX z ``tests/test_uporzadkowanie_intermax.py``,
gdy zmiana podziału plików postawiła oba pliki testów w jednym zadaniu CI.

``tests/conftest.py`` bierze zwykłe pliki procesu przed setupem testu (``open_files``) i po jego teardownie wywraca test,
którego plik zwolnił dopiero ``gc`` (``left_to_gc``). Lista deskryptorów kosztuje ułamek milisekundy, a przegląd
obiektów i ``gc.collect()`` biegną tylko wtedy, gdy po teście nowy plik jest jeszcze otwarty. Plik trzymany przez żywy
obiekt (fixture sesji, wątek kolejki Zgłoszeń, który kończy przejście już po teście) nie wywraca testu, także gdy wątek
zamyka go w trakcie ``gc.collect()``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import gc
import io
import os
from pathlib import Path
import stat
import sys
import threading
from typing import Final
import warnings
import weakref

_STANDARD_STREAMS: Final = frozenset({0, 1, 2})


def open_files() -> dict[int, str]:
    """Zwykłe pliki otwarte w procesie: deskryptor → ścieżka bez dowiązań; na Windows pusty, bo nie ma taniej listy
    deskryptorów procesu. Bez standardowych strumieni: przechwytywanie pytest podmienia je między setupem a teardownem,
    więc wyjście pytest przekierowane do pliku (``> log``) byłoby nowym plikiem po każdym teście."""

    if sys.platform == "win32":
        return {}
    directory = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    files: dict[int, str] = {}
    for entry in Path(directory).iterdir():
        descriptor = int(entry.name)
        if descriptor in _STANDARD_STREAMS:
            continue
        try:
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                files[descriptor] = os.path.realpath(_path(descriptor))
        except OSError:  # deskryptor samej listy katalogu jest już zamknięty
            continue
    return files


def _path(descriptor: int) -> str:
    if sys.platform == "darwin":
        import fcntl

        return fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
    return os.readlink(f"/proc/self/fd/{descriptor}")


def left_to_gc(before: Mapping[int, str]) -> list[str]:
    """Ścieżki plików otwartych od ``before``, których obiekt ``io.FileIO`` zwolnił dopiero ``gc.collect()``.

    Kryterium to zwolnienie obiektu pliku w trakcie ``gc.collect()`` i w wątku, który go woła: przez sam ``gc`` albo
    przez finalizer śmiecia (``zipfile.ZipFile.__del__`` zamyka swój plik bez ``ResourceWarning``). Zamknięty
    deskryptor nie jest kryterium, bo zamyka go też żywy wątek, który w trakcie ``gc.collect()`` kończy swój blok
    ``with``; jego obiekt pliku zwalnia ten drugi wątek. Zwolnienie przed ``gc.collect()`` też nie: lista
    ``gc.get_objects()`` trzyma każdy obiekt, więc plik, który inny wątek zamknął i puścił w trakcie przeglądu, zwalnia
    dopiero koniec tej listy w wątku straży. Samoczynny ``gc`` stoi na czas sprawdzenia, żeby śmieć nie zniknął przed
    ``gc.collect()``.
    """

    new = {descriptor: path for descriptor, path in open_files().items() if before.get(descriptor) != path}
    if not new:
        return []
    collecting: list[int] = []
    left: set[str] = set()

    def freed_by(path: str) -> Callable[[object], None]:
        def freed(_: object) -> None:
            if collecting == [threading.get_ident()]:
                left.add(path)

        return freed

    automatic = gc.isenabled()
    gc.disable()
    try:
        watched = [
            weakref.ref(candidate, freed_by(new[candidate.fileno()]))
            for candidate in gc.get_objects()
            if isinstance(candidate, io.FileIO) and not candidate.closed and candidate.fileno() in new
        ]
        if watched:
            collecting.append(threading.get_ident())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                gc.collect()
            collecting.clear()
    finally:
        if automatic:
            gc.enable()
    return sorted(left)
