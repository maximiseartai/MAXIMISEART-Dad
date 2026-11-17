"""Wnuk polecenia co 0,1 s dopisuje znak do pliku; plik, który przestał rosnąć, znaczy, że wnuk nie żyje.

Na Windows ``os.kill(pid, 0)`` nie sprawdza procesu, tylko wysyła mu Ctrl+C (``CTRL_C_EVENT`` to 0).

Żywy proces bez okna czasu: ``hold_lock`` trzyma blokadę pliku do końca życia procesu, a ``held`` pyta, czy ktoś ją
trzyma. Blokadę zwalnia system, gdy proces ginie, także zabity, więc odpowiedź nie zależy od tego, czy proces dostał
ostatnio procesor (bicie z ``beating`` zależy).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import signal
import sys
import time
from typing import IO, TypeVar

from tests.fixtures.git_repo import git
import potomne

__all__ = [
    "beating",
    "ctrl_c_reaches_children",
    "held",
    "hold_lock",
    "until_stopped",
    "wait_for",
    "wait_for_value",
    "with_grandchild",
    "worktrees",
]

T = TypeVar("T")

GRANDCHILD = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('.')\n    time.sleep(0.1)\n"


def with_grandchild(beats: Path, then: str) -> list[str]:
    """``then`` biegnie, gdy wnuk już dopisuje do ``beats``; wnuk dziedziczy wyjście polecenia."""

    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {GRANDCHILD!r}, {str(beats)!r}])\n"
        f"while not pathlib.Path({str(beats)!r}).exists():\n"
        "    time.sleep(0.05)\n"
        f"{then}\n"
    )
    return [sys.executable, "-c", code]


def until_stopped(stop: Path, *, each: str = "pass", seconds: int = 600) -> str:
    """Kod końca procesu potomnego testu: co 0,05 s wykonuje ``each``, aż test utworzy plik ``stop`` albo minie ``seconds``
    s. Test kończy swój proces tym plikiem, nie PID-em z pliku: proces, który już zginął, zwalnia PID dla obcego procesu
    (na Windows ``os.kill`` to ``TerminateProcess`` każdego procesu z tym PID-em, także workera xdist), a plik z PID-em
    istnieje, zanim ma treść, i zostaje pusty, gdy proces zginie w środku zapisu."""

    return (
        "import os as _os, time as _time\n"
        f"_koniec = _time.monotonic() + {seconds}\n"
        f"while not _os.path.exists({str(stop)!r}) and _time.monotonic() < _koniec:\n"
        f"    {each}\n"
        "    _time.sleep(0.05)\n"
    )


def beating(beats: Path) -> bool:
    before = beats.stat().st_size
    return wait_for(lambda: beats.stat().st_size != before, 2)


def ctrl_c_reaches_children() -> None:
    """Ctrl+C (SIGINT), który test wysyła procesowi potomnemu, dochodzi do niego także wtedy, gdy proces testów odziedziczył
    SIGINT ignorowany (``nohup`` i ``&`` z nieinteraktywnej powłoki): sygnał ignorowany przechodzi przez ``exec`` do potomka, a
    obsługiwany wraca w nim do domyślnego, więc proces testów, który go ignoruje, dostaje obsługę Pythona
    (``KeyboardInterrupt``). Obsługi, którą ustawił ktoś inny, nie zmienia; woła ją ``pytest_configure`` w
    ``tests/conftest.py`` w każdym procesie testów, przed startem workerów xdist."""

    if signal.getsignal(signal.SIGINT) is signal.SIG_IGN:
        signal.signal(signal.SIGINT, signal.default_int_handler)


def hold_lock(path: Path) -> IO[bytes]:
    """Blokada pliku ``path`` dla tego procesu do końca jego życia, tym samym mechanizmem co zamek ``potomne``
    (``fcntl.flock`` na POSIX, ``msvcrt.locking`` na Windows); wołający trzyma zwrócony plik otwarty."""

    lock = path.open("ab")
    if not potomne._locked(lock):
        raise RuntimeError(f"blokadę {path} trzyma już inny proces")
    return lock


def held(path: Path) -> bool:
    """Czy blokadę pliku ``path`` (``hold_lock``) trzyma żywy proces. Na Windows system zwalnia blokadę zabitego
    procesu z opóźnieniem zależnym od zasobów, więc po zabiciu pytaj ``wait_for(lambda: not held(path), s)``.

    Pytanie samo bierze wolną blokadę na chwilę, więc kod, który bierze ją w tej chwili bez czekania, dostaje odmowę, a
    odpowiedź nie mówi, kto ją trzyma; o blokadę, którą kod pod testem bierze bez czekania, nie pytaj nim (#2086)."""

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
