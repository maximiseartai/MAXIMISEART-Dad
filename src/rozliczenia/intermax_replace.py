"""Podmiana INTERMAX: jedyna droga, którą Uporządkowanie INTERMAX i przywrócenie Kopii INTERMAX zastępują Rejestr zleceń.

``replace_register`` dostaje to, czym oba procesy się różnią: nowe bajty INTERMAX, sprawdzenie zapisanego pliku i
rodzaj Kopii INTERMAX (``Before``). Ukrywa resztę (ADR 0019):

1. nowe bajty trafiają do pliku tymczasowego obok INTERMAX (``workbook_save.write_atomically``), który zostaje
   odczytany jeszcze raz i sprawdzony;
2. dopiero po zgodnym sprawdzeniu: INTERMAX otwarty w Excelu (plik blokady) zatrzymuje podmianę, a inaczej powstaje
   Kopia INTERMAX z bajtami sprzed podmiany, z nazwą z chwili ``now()``;
3. atomowa podmiana; odmowę bez pliku blokady Excela (OneDrive synchronizuje INTERMAX) ponawia przez ``_RETRY_S``
   sekund zegara ``Waiting``, a przed każdą ponowną próbą czyta INTERMAX jeszcze raz i podmienia tylko INTERMAX o
   bajtach sprzed podmiany;
4. po udanej podmianie zostaje ``intermax_copies.KEPT`` najnowszych Kopii obu nazw.

Zwraca fakt, nie Komunikat: ``Replaced`` albo jedną ``Refusal``. Katalog każdego procesu tylko ją nazywa. Po każdej
``Refusal`` i po każdym innym wyjątku INTERMAX, folder obok niego i folder Kopii są takie, jak były: Kopia, która
już powstała, znika (jedna polityka dla obu procesów), a plik tymczasowy nie zostaje. Nieudane usunięcie starszych
Kopii to ``Replaced.old_copies_kept``, bo INTERMAX jest już podmieniony.

Kroki, którymi podmiana zmienia dysk, czyta INTERMAX w trakcie albo sprawdza, czy nazwa Kopii jest zajęta, idą przez
``Disk``; testy i sprawdzenie ``verify-zapis-intermax`` podają własne, żeby zepsuć jeden krok bez łatania ``os`` i
``Path``.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final

from . import intermax_copies, workbook_files
from .intermax_copies import Before, Copy
from .workbook_files import Problem, WorkbookError
from .workbook_save import WorkbookSaveError, write_atomically

__all__ = ["LOCAL_DISK", "Disk", "Refusal", "Replaced", "Waiting", "WriteMismatch", "replace_register"]

_RETRY_S: Final = 5.0
"""Tyle sekund podmiana ponawia zastąpienie INTERMAX, którego system odmawia, choć Excel go nie trzyma."""
_PAUSE_S: Final = 0.5


class WriteMismatch(Exception):
    """Plik tymczasowy zapisany przed podmianą różni się od tego, co miał zawierać; zgłasza go ``check``."""


class Refusal(Enum):
    """Fakt, przez który INTERMAX nie został podmieniony; INTERMAX i Kopie INTERMAX są takie, jak były."""

    EXCEL_HOLDS = "Excel trzyma INTERMAX"
    """Plik blokady Excela przed Kopią, przy odmowie podmiany albo przy odczycie przed ponowną próbą."""
    ONEDRIVE_HOLDS = "OneDrive trzyma INTERMAX"
    """System odmawia podmiany bez pliku blokady dłużej niż ``_RETRY_S`` sekund albo OneDrive wgrał w przerwie między
    próbami inną wersję INTERMAX, albo jej nie da się odczytać."""
    WRITE_FAILED = "zapis nieudany"
    """Pliku tymczasowego nie da się utworzyć ani zapisać albo podmiana kończy się błędem innym niż odmowa dostępu,
    np. brak miejsca na dysku; bez ponownej próby."""
    WRITE_MISMATCH = "zapis niezgodny"
    """Odczytany plik tymczasowy jest nieczytelny albo sprawdzenie zapisu znalazło różnicę; Kopia jeszcze nie powstała."""
    COPY_FAILED = "Kopia nieudana"
    """Kopia INTERMAX nie powstała w całości (folder, dysk); jej część nie zostaje."""
    COPY_EXISTS = "Kopia o tej nazwie już jest"
    """Kopia INTERMAX z tą samą chwilą w nazwie już jest; zostaje nietknięta."""


@dataclass(frozen=True)
class Replaced:
    """INTERMAX podmieniony; ``copy`` to Kopia INTERMAX bajtów sprzed podmiany, ``old_copies_kept``: starszych Kopii
    ponad ``intermax_copies.KEPT`` nie udało się usunąć."""

    copy: Copy
    old_copies_kept: bool


@dataclass(frozen=True)
class Waiting:
    """Zegar procesu w sekundach i przerwa między próbami podmiany INTERMAX."""

    clock: Callable[[], float] = time.monotonic
    pause: Callable[[float], None] = time.sleep


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _read(path: Path) -> bytes:
    return workbook_files.workbook_content(path)


def _exists(path: Path) -> bool:
    return path.exists()


def _create(path: Path, content: bytes) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
    except FileExistsError as error:  # plik w miejscu folderu Kopii, nie Kopia o tej nazwie
        raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(path.parent)) from error
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)


def _replace(source: Path, target: Path) -> None:
    os.replace(source, target)


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


@dataclass(frozen=True)
class Disk:
    """Kroki podmiany na dysku: zmiany, odczyt skoroszytu w trakcie i zajętość nazwy Kopii; ``LOCAL_DISK`` to prawdziwe.

    ``write``: bajty pliku tymczasowego. ``read``: bajty skoroszytu jak ``workbook_files.workbook_content``
    (``WorkbookError``), dla odczytanego pliku tymczasowego i INTERMAX przed ponowną próbą. ``exists``: czy nazwa Kopii
    jest zajęta (``OSError``, gdy folderu Kopii nie da się przeszukać). ``create``: nowy plik Kopii z jej folderem,
    ``FileExistsError``, gdy plik o tej nazwie już jest. ``replace``: atomowa podmiana celu.
    ``remove``: usunięcie pliku, którego może już nie być.
    """

    write: Callable[[Path, bytes], None] = _write
    read: Callable[[Path], bytes] = _read
    exists: Callable[[Path], bool] = _exists
    create: Callable[[Path, bytes], None] = _create
    replace: Callable[[Path, Path], None] = _replace
    remove: Callable[[Path], None] = _remove


LOCAL_DISK: Final = Disk()


class _Refused(Exception):
    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


def replace_register(
    register: Path,
    current: bytes,
    content: bytes,
    check: Callable[[bytes], None],
    *,
    before: Before,
    copies: Path,
    now: Callable[[], datetime],
    waiting: Waiting,
    disk: Disk = LOCAL_DISK,
) -> Replaced | Refusal:
    """Zastępuje INTERMAX ``register`` o bajtach ``current`` bajtami ``content`` z Kopią INTERMAX ``before`` w
    ``copies``.

    ``check`` dostaje bajty odczytanego pliku tymczasowego i zgłasza ``WriteMismatch``, gdy zapis się nie zgadza.
    Wyjątek inny niż ``Refusal`` (błąd w kodzie) wychodzi dalej, a INTERMAX i Kopie są wtedy takie, jak były.
    """

    made: list[Copy] = []
    replaced = False

    def write(temporary: Path) -> None:
        try:
            disk.write(temporary, content)
        except OSError as error:
            raise _Refused(Refusal.WRITE_FAILED) from error
        try:
            written = disk.read(temporary)
            with workbook_files.unreadable_as_error(temporary):
                check(written)
        except (WorkbookError, WriteMismatch) as error:
            raise _Refused(Refusal.WRITE_MISMATCH) from error
        moment = now()
        if workbook_files.is_open_in_excel(register):
            raise _Refused(Refusal.EXCEL_HOLDS)
        copy = intermax_copies.named(copies, before, moment)
        try:
            taken = disk.exists(copy.path)  # Kopia o tej nazwie, która już jest, zostaje nietknięta
        except OSError as error:  # folderu Kopii nie da się przeszukać
            raise _Refused(Refusal.COPY_FAILED) from error
        try:
            disk.create(copy.path, current)
        except FileExistsError as error:  # także Kopia, którą ktoś zapisał po sprawdzeniu nazwy
            taken = True
            raise _Refused(Refusal.COPY_EXISTS) from error
        except OSError as error:
            raise _Refused(Refusal.COPY_EXISTS if taken else Refusal.COPY_FAILED) from error
        finally:
            if not taken:
                made.append(copy)  # cała albo jej część, której zapis się nie udał

    def replace(temporary: Path, target: Path) -> None:
        nonlocal replaced
        deadline = waiting.clock() + _RETRY_S
        while True:
            try:
                disk.replace(temporary, target)
            except PermissionError as error:
                if workbook_files.is_open_in_excel(target):
                    raise _Refused(Refusal.EXCEL_HOLDS) from error
                if waiting.clock() >= deadline:
                    raise _Refused(Refusal.ONEDRIVE_HOLDS) from error
            except OSError as error:
                raise _Refused(Refusal.WRITE_FAILED) from error
            else:
                replaced = True
                return
            waiting.pause(_PAUSE_S)
            try:
                unchanged = disk.read(target) == current
            except WorkbookError as error:
                excel = error.problem is Problem.OPEN_IN_EXCEL
                raise _Refused(Refusal.EXCEL_HOLDS if excel else Refusal.ONEDRIVE_HOLDS) from error
            if not unchanged:
                raise _Refused(Refusal.ONEDRIVE_HOLDS)

    try:
        write_atomically(register, write, replace=replace)
    except _Refused as refused:
        return refused.refusal
    except WorkbookSaveError:  # pliku tymczasowego nie da się utworzyć; podmiana nie przepuszcza ``OSError``
        return Refusal.WRITE_FAILED
    finally:
        if not replaced:
            for copy in made:
                _forget(copy.path, disk)
    return Replaced(made[0], not _pruned(copies, disk))


def _forget(path: Path, disk: Disk) -> None:
    """Usuwa Kopię podmiany, która się nie udała, bez zgłaszania błędu.

    Nieudane usunięcie nie zasłania faktu, przez który podmiana się nie udała: Kopia, która zostaje, ma bajty
    INTERMAX, który się nie zmienił, a usuwa ją limit ``intermax_copies.KEPT`` po następnej udanej podmianie.
    """

    with suppress(OSError):
        disk.remove(path)


def _pruned(copies: Path, disk: Disk) -> bool:
    """Usuwa Kopie starsze niż ``intermax_copies.KEPT`` najnowszych; ``False``, gdy któraś zostaje."""

    try:
        for copy in intermax_copies.outdated(copies):
            disk.remove(copy.path)
    except OSError:
        return False
    return True
