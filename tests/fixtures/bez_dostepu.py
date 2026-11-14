"""Folder bez dostępu (odebrane uprawnienia albo OneDrive, który nie działa) w testach silnika i Centrum rozliczeń.

Do Pythona 3.13 ``Path.exists``, ``is_file``, ``is_dir`` i ``is_symlink`` w folderze bez dostępu rzucają ``OSError``, a od
3.14 dają ``False``, więc każdy test folderu bez dostępu biegnie z ``Path`` obu wersji (``PATH_CHECKS``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import pytest


@contextmanager
def without_access(folder: Path) -> Iterator[None]:
    """Folder ``folder`` bez dostępu do końca bloku.

    ``chmod`` w Windows nie odbiera prawa odczytu, więc test z nim pomija Windows (``NO_ACCESS_ON_WINDOWS``).
    """

    folder.chmod(0)
    try:
        yield
    finally:
        folder.chmod(0o755)


def deny_reading(path: Path) -> None:
    """Plik albo folder ``path`` bez prawa odczytu na każdym systemie: ``chmod`` poza Windows, a w Windows odmowa odczytu
    danych (``icacls /deny :(RD)``), bo ``chmod`` zmienia tam tylko atrybut „tylko do odczytu”. Folder dalej widać w
    listowaniu folderu nad nim, a odczyt jego treści pada, co funkcja sprawdza."""

    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/deny", f"{os.environ['USERNAME']}:(RD)"], check=True, capture_output=True)
    else:
        path.chmod(0)
    with pytest.raises(PermissionError):
        list(path.iterdir()) if path.is_dir() else path.open("rb").close()


def allow_reading(path: Path) -> None:
    """Oddaje prawo odczytu, które odebrało ``deny_reading``."""

    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/remove:d", os.environ["USERNAME"]], check=True, capture_output=True)
    else:
        path.chmod(0o755)


@contextmanager
def without_reading(path: Path) -> Iterator[None]:
    """``path`` bez prawa odczytu (``deny_reading``) do końca bloku, na każdym systemie."""

    deny_reading(path)
    try:
        yield
    finally:
        allow_reading(path)


@contextmanager
def without_creating(folder: Path) -> Iterator[None]:
    """Folder ``folder``, w którym do końca bloku nie da się założyć pliku, a pliki, które już w nim są, dalej przyjmują
    dopisanie, na każdym systemie: ``chmod`` bez prawa zapisu poza Windows, a w Windows odmowa zakładania plików
    (``icacls /deny :(WD)``) na samym folderze, bez dziedziczenia na pliki w nim. Funkcja sprawdza, że założenie pliku
    pada."""

    if sys.platform == "win32":
        subprocess.run(["icacls", str(folder), "/deny", f"{os.environ['USERNAME']}:(WD)"], check=True, capture_output=True)
    else:
        folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            (folder / "proba-zalozenia.tmp").open("xb").close()
        yield
    finally:
        if sys.platform == "win32":
            subprocess.run(["icacls", str(folder), "/remove:d", os.environ["USERNAME"]], check=True, capture_output=True)
        else:
            folder.chmod(0o755)


def path_checks_up_to_python_313(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Path`` bez zmian: do Pythona 3.13 brak dostępu do folderu rzuca ``OSError``."""


def path_checks_from_python_314(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Path.exists``, ``is_file``, ``is_dir`` i ``is_symlink`` jak od Pythona 3.14: ``False`` przy każdym ``OSError``.

    Tak działają ``os.path.exists``, ``isfile``, ``isdir`` i ``islink`` na każdej wersji, więc test na starszym Pythonie
    widzi, czy kod pomyliłby folder bez dostępu z brakiem pliku.
    """

    monkeypatch.setattr(Path, "exists", lambda path, **_: os.path.exists(path))
    monkeypatch.setattr(Path, "is_file", lambda path, **_: os.path.isfile(path))
    monkeypatch.setattr(Path, "is_dir", lambda path, **_: os.path.isdir(path))
    monkeypatch.setattr(Path, "is_symlink", lambda path: os.path.islink(path))


PATH_CHECKS: Final = pytest.mark.parametrize(
    "path_checks",
    [path_checks_up_to_python_313, path_checks_from_python_314],
    ids=["path-do-3.13", "path-od-3.14"],
)
NO_ACCESS_ON_WINDOWS: Final = pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows nie odbiera prawa odczytu")
