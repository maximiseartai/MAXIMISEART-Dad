"""Żywy proces bez okna czasu: ``hold_lock`` trzyma blokadę pliku do końca życia procesu, a ``held`` pyta, czy ktoś ją
trzyma. Blokadę zwalnia system, gdy proces ginie, także zabity, więc odpowiedź nie zależy od tego, czy proces dostał
ostatnio procesor. ``alive_code`` to kod procesu, który tak trzyma blokadę pliku obok ``path`` i potem tworzy ``path``,
a ``alive(path)`` pyta o tę blokadę; ``with_grandchild`` uruchamia takiego wnuka.

Na Windows ``os.kill(pid, 0)`` nie sprawdza procesu, tylko wysyła mu Ctrl+C (``CTRL_C_EVENT`` to 0).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
import time
from typing import IO, TypeVar

from tests.fixtures.git_repo import git
import potomne

__all__ = ["alive", "alive_code", "held", "hold_lock", "wait_for", "wait_for_value", "with_grandchild", "worktrees"]

T = TypeVar("T")

# Korzeń repozytorium i biblioteki narzędzi: proces z ``alive_code`` importuje stąd ``hold_lock``.
_PATHS = (str(Path(__file__).resolve().parents[2]), str(Path(potomne.__file__).resolve().parent))


def _lock_of(path: Path) -> Path:
    return path.with_name(path.name + ".blokada")


def alive_code(path: Path, seconds: float = 600) -> str:
    """Kod Pythona procesu, który bierze blokadę pliku obok ``path`` (``hold_lock``), potem tworzy ``path`` i żyje
    ``seconds`` s: ``path`` istnieje więc dopiero wtedy, gdy blokada jest wzięta, a ``alive(path)`` mówi, czy proces
    jeszcze żyje."""

    return (
        "import pathlib, sys, time\n"
        f"sys.path[:0] = {list(_PATHS)!r}\n"
        "from tests.fixtures.potomne import hold_lock\n"
        f"lock = hold_lock(pathlib.Path({str(_lock_of(path))!r}))\n"
        f"pathlib.Path({str(path)!r}).touch()\n"
        f"time.sleep({seconds!r})\n"
    )


def alive(path: Path) -> bool:
    """Czy proces z ``alive_code(path)`` jeszcze żyje (trzyma blokadę). Na Windows system zwalnia blokadę zabitego
    procesu z opóźnieniem, więc po zabiciu pytaj ``wait_for(lambda: not alive(path), s)``."""

    return held(_lock_of(path))


def with_grandchild(alive_file: Path, then: str) -> list[str]:
    """Polecenie, w którym ``then`` biegnie, gdy wnuk z ``alive_code(alive_file)`` już żyje (``alive_file`` istnieje);
    wnuk dziedziczy wyjście polecenia."""

    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {alive_code(alive_file)!r}])\n"
        f"while not pathlib.Path({str(alive_file)!r}).exists():\n"
        "    time.sleep(0.05)\n"
        f"{then}\n"
    )
    return [sys.executable, "-c", code]


def hold_lock(path: Path) -> IO[bytes]:
    """Blokada pliku ``path`` dla tego procesu do końca jego życia, tym samym mechanizmem co zamek ``potomne``
    (``fcntl.flock`` na POSIX, ``msvcrt.locking`` na Windows); wołający trzyma zwrócony plik otwarty."""

    lock = path.open("ab")
    if not potomne._locked(lock):
        raise RuntimeError(f"blokadę {path} trzyma już inny proces")
    return lock


def held(path: Path) -> bool:
    """Czy blokadę pliku ``path`` (``hold_lock``) trzyma żywy proces. Na Windows system zwalnia blokadę zabitego
    procesu z opóźnieniem zależnym od zasobów, więc po zabiciu pytaj ``wait_for(lambda: not held(path), s)``."""

    if not path.exists():
        return False
    with path.open("ab") as lock:
        if not potomne._locked(lock):
            return True
        potomne._unlock(lock)
    return False


def wait_for(condition: Callable[[], bool], seconds: float = 60, *, every: float = 0.05) -> bool:
    """``condition`` pytane co ``every`` s, aż da prawdę (``True``) albo minie ``seconds`` s (``False``); po terminie
    pada jeszcze jedno pytanie."""

    deadline = time.monotonic() + seconds
    while True:
        expired = time.monotonic() >= deadline
        if condition():
            return True
        if expired:
            return False
        time.sleep(every)


def wait_for_value(
    read: Callable[[], T], reached: Callable[[T], bool], seconds: float = 60, *, every: float = 0.05
) -> tuple[bool, T]:
    """``wait_for`` na wartość: czy ``read()`` doszło do ``reached`` i ostatnia odczytana wartość."""

    values: list[T] = []

    def now_reached() -> bool:
        values.append(read())
        return reached(values[-1])

    return wait_for(now_reached, seconds, every=every), values[-1]


def worktrees(repo: Path) -> list[Path]:
    listed = git(repo, "worktree", "list", "--porcelain").splitlines()
    return [Path(line.removeprefix("worktree ")) for line in listed if line.startswith("worktree ")]
