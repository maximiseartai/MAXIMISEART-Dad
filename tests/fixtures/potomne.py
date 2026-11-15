"""Żywy proces bez okna czasu: ``hold_lock`` trzyma blokadę pliku do końca życia procesu, a ``held`` pyta, czy ktoś ją
trzyma. Blokadę zwalnia system, gdy proces ginie, także zabity, więc odpowiedź nie zależy od tego, czy proces dostał
ostatnio procesor. ``alive_code`` to kod procesu, który tak trzyma blokadę pliku obok ``path`` i potem tworzy ``path``,
``alive(path)`` pyta o tę blokadę, a ``dead(path)`` odpowiada, czy proces zginął razem ze swoim drzewem;
``with_grandchild`` uruchamia takiego wnuka.

Na Windows ``os.kill(pid, 0)`` nie sprawdza procesu, tylko wysyła mu Ctrl+C (``CTRL_C_EVENT`` to 0).
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

__all__ = ["alive", "alive_code", "ctrl_c_reaches_children", "dead", "held", "hold_lock", "wait_for", "wait_for_value", "with_grandchild", "worktrees"]

T = TypeVar("T")

# Korzeń repozytorium i biblioteki narzędzi: proces z ``alive_code`` importuje stąd ``hold_lock``.
_PATHS = (str(Path(__file__).resolve().parents[2]), str(Path(potomne.__file__).resolve().parent))
# Na POSIX tyle ``dead(..., after_guard=True)`` czeka na strażnika narzędzia zabitego SIGKILL, a na macOS też ``dead``.
_GUARD_S = 5.0
# Na Linuksie tyle ``dead`` czeka, aż proces, który już dostał SIGKILL, zamknie pliki.
_EXIT_S = 10.0


def _lock_of(path: Path) -> Path:
    return path.with_name(path.name + ".blokada")


def alive_code(path: Path, seconds: float = 600) -> str:
    """Kod Pythona procesu, który bierze blokadę pliku obok ``path`` (``hold_lock``), potem zapisuje w ``path`` swój PID
    i żyje ``seconds`` s: ``path`` istnieje więc dopiero wtedy, gdy blokada jest wzięta, a ``alive(path)`` mówi, czy
    proces jeszcze żyje."""

    return (
        "import os, pathlib, sys, time\n"
        f"sys.path[:0] = {list(_PATHS)!r}\n"
        "from tests.fixtures.potomne import hold_lock\n"
        f"lock = hold_lock(pathlib.Path({str(_lock_of(path))!r}))\n"
        f"pathlib.Path({str(path)!r}).write_text(str(os.getpid()))\n"
        f"time.sleep({seconds!r})\n"
    )


def alive(path: Path) -> bool:
    """Czy proces z ``alive_code(path)`` jeszcze żyje (trzyma blokadę). Po zabiciu jego drzewa pytaj ``dead(path)``."""

    return held(_lock_of(path))


def dead(path: Path, *, after_guard: bool = False) -> bool:
    """Czy proces z ``alive_code(path)`` już nie żyje, pytane zaraz po końcu, który zabija jego drzewo: powrocie
    ``potomne.run`` (albo innego zabijania, które czeka na koniec polecenia) albo sprzątaniu strażnika, które widać po
    zniknięciu jego kopii (strażnik zabija drzewa przed usuwaniem kopii).

    Zabijanie na POSIX wysyła SIGKILL całej grupie, ale czeka tylko na jej lidera, więc proces może jeszcze trzymać
    blokadę: pod obciążeniem jądro kończy go dopiero po powrocie ``run``. Na Linuksie ``dead`` pyta więc jądro, czy
    proces już dostał SIGKILL (``_killed``): jeśli nie, odpowiada od razu ``False``, a drzewo zabite po powrocie
    ``run`` pada niezależnie od tego, jak długo po nim ginie; jeśli tak, czeka najwyżej ``_EXIT_S``, aż proces zamknie
    pliki, a z nimi blokadę ``flock``. Tylko ``after_guard`` czeka najwyżej ``_GUARD_S`` na strażnika narzędzia
    zabitego SIGKILL, gdy test nie widzi końca jego sprzątania (narzędzie bez kopii). Znane luki: strażnik spóźniony
    mniej niż ``_GUARD_S``, a na macOS, bez ``/proc``, każde drzewo zabite przed tym terminem.

    Na Windows czeka najwyżej ``potomne._RELEASE_S`` na zwolnienie blokady przez system. ``TerminateJobObject`` i
    zabicie przy zamknięciu uchwytu zadania (KILL_ON_JOB_CLOSE, gdy ginie narzędzie) tylko zaczynają kończenie
    procesów, a dokumentacja ``LockFileEx`` mówi, że blokady zakończonego procesu system zwalnia w czasie zależnym od
    dostępnych zasobów, i nie wiąże tego z sygnałem końca procesu, na który czeka ``_Tree.kill``. Windows nie pokazuje
    zabicia, które już zaczęło się w jądrze, a koniec procesu po jego uchwycie też wymaga terminu, bo spóźnione
    zabicie opóźnia ten sam koniec. Znana luka: drzewo zabite na Windows później, ale przed terminem, przechodzi;
    spóźnienie w kodzie wspólnym obu systemów łapie strona POSIX.
    """

    if not alive(path):
        return True
    if sys.platform == "win32":
        return wait_for(lambda: not alive(path), potomne._RELEASE_S)
    if after_guard or sys.platform != "linux":
        return wait_for(lambda: not alive(path), _GUARD_S)
    return _killed(int(path.read_text(encoding="utf-8"))) and wait_for(lambda: not alive(path), _EXIT_S)


def _killed(pid: int) -> bool:
    """Czy proces ``pid`` dostał już SIGKILL albo go nie ma. SIGKILL wysłany procesowi albo jego grupie zostaje w zbiorze
    sygnałów czekających całego procesu (``ShdPnd``) do jego pogrzebania, a jądro dokłada go też wątkom (``SigPnd``);
    zombie (``Z``, ``X``) pliki już zamknął."""

    if sys.platform == "win32":
        raise AssertionError("/proc i SIGKILL są tylko na POSIX")
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    fields = dict(line.split(":\t", 1) for line in status.splitlines() if ":\t" in line)
    pending = int(fields["SigPnd"], 16) | int(fields["ShdPnd"], 16)
    return bool(pending & 1 << (signal.SIGKILL - 1)) or fields["State"][:1] in ("Z", "X")


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


def ctrl_c_reaches_children() -> None:
    """Ctrl+C (SIGINT), który test wysyła procesowi potomnemu, dochodzi do niego także wtedy, gdy proces testów odziedziczył
    SIGINT ignorowany (``nohup`` i ``&`` w ``boatbox job``): sygnał ignorowany przechodzi przez ``exec`` do potomka, a
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
    """Czy blokadę pliku ``path`` (``hold_lock``) trzyma żywy proces; po zabiciu procesu z ``alive_code`` pytaj
    ``dead``, które zna opóźnienie zwolnienia blokady na Windows."""

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
