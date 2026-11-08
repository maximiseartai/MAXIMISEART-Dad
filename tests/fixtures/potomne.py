"""Wnuk polecenia co 0,1 s dopisuje znak do pliku; plik, który przestał rosnąć, znaczy, że wnuk nie żyje.

Na Windows ``os.kill(pid, 0)`` nie sprawdza procesu, tylko wysyła mu Ctrl+C (``CTRL_C_EVENT`` to 0).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
import time
from typing import TypeVar

from tests.fixtures.git_repo import git

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS / "lib"))

import potomne  # noqa: E402

__all__ = ["TOOLS", "beating", "potomne", "wait_for", "wait_for_value", "with_grandchild", "worktrees"]

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


def beating(beats: Path) -> bool:
    before = beats.stat().st_size
    return wait_for(lambda: beats.stat().st_size != before, 2)


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
