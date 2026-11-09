"""Publikacja przez folder tymczasowy: pliki procesu trafiają do taty wszystkie albo żaden.

Proces zapisuje pliki w nowym folderze tymczasowym obok miejsca publikacji i stamtąd je publikuje: Przebieg rozliczeń
Folder rozliczeń pracowników jedną zmianą nazwy, a Przygotowanie pliku zbiorczego oba pliki okresu
(``preparation_files``). Po publikacji i po zatrzymaniu folder tymczasowy jest usuwany. Folder, którego nie da się
usunąć (np. trzyma jego pliki OneDrive), zostaje, a Komunikat zatrzymania podaje początek jego nazwy.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from .file_state import path_state
from .message import Message, StopError

ResultT = TypeVar("ResultT")

__all__ = ["LOCAL_DISK", "Disk", "publish_staged", "staging_prefix"]


def staging_prefix(name: str) -> str:
    """Początek nazwy folderu tymczasowego publikacji ``name``."""

    return f".{name}.staging-"


def _make_staging(prefix: str, directory: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=directory))


def _remove_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


@dataclass(frozen=True)
class Disk:
    """Kroki folderu tymczasowego; ``LOCAL_DISK`` to prawdziwe, a sprawdzenie ``verify-publikacja-plikow-okresu``
    podaje własne, żeby prowadzić je na dysku w pamięci bez łatania modułu.

    ``make_staging``: nowy folder tymczasowy o początku nazwy ``prefix`` w folderze ``directory`` (``OSError``).
    ``remove_staging``: usunięcie folderu tymczasowego, którego może się nie dać usunąć; nigdy nie zgłasza błędu.
    """

    make_staging: Callable[[str, Path], Path] = _make_staging
    remove_staging: Callable[[Path], None] = _remove_staging


LOCAL_DISK: Final = Disk()


def publish_staged(
    directory: Path,
    name: str,
    publish: Callable[[Path], ResultT],
    *,
    failed: Message,
    left: Callable[[Message, str], Message],
    disk: Disk = LOCAL_DISK,
) -> ResultT:
    """Wynik ``publish``, które zapisuje i publikuje pliki z nowego folderu tymczasowego w folderze ``directory``.

    ``OSError`` przy zakładaniu folderu tymczasowego albo w ``publish`` zatrzymuje Uruchomienie Komunikatem ``failed``.
    Zatrzymanie, po którym folder tymczasowy został albo nie da się sprawdzić, czy został, dostaje zamiast swojego
    Komunikatu ``left`` z jego Komunikatem i początkiem nazwy folderu tymczasowego.
    """

    prefix = staging_prefix(name)
    try:
        staging = disk.make_staging(prefix, directory)
    except OSError as exc:
        raise StopError(failed) from exc
    try:
        try:
            result = publish(staging)
        except OSError as exc:
            raise StopError(failed) from exc
    except BaseException as error:
        disk.remove_staging(staging)
        if isinstance(error, StopError) and path_state(staging) != "missing":
            raise StopError(left(error.message, prefix)) from error
        raise
    disk.remove_staging(staging)
    return result
