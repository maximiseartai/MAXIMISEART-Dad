"""Opiekun ponownego startu: po udanej Aktualizacji narzędzia uruchamia Centrum rozliczeń w nowej wersji (ADR 0009).

Centrum kopiuje ten moduł razem z ``tool_update`` do swojego katalogu
tymczasowego, zanim zmieni klon (``prepare``). Po sukcesie uruchamia opiekuna
odłączonym procesem bez konsoli (``launch``) i samo się zamyka. Opiekun działa
z kopii sprzed aktualizacji i używa tylko biblioteki standardowej (``main``):
zapisuje wynik aktualizacji obok Ustawień Centrum, czeka na zwolnienie portu,
startuje nową wersję jak skrót, tylko bez karty i bez okienek, i czeka, aż
odpowie w nowym commicie. Wtedy aktualizacja jest skończona, a jej dziennik
„Aktualizacja w toku” znika (``ToolClone.confirm_update``). Gdy nie odpowie
(albo stare Centrum nie zwolni portu), opiekun ją zatrzymuje, cofa klon z
dziennika do commitu sprzed aktualizacji razem z plikami taty
(``ToolClone.roll_back``), zapisuje wynik „Nowa wersja nie wystartowała” i tak
samo startuje starą wersję, która pokaże go w karcie. Gdy cofnięcie się nie
uda, wynik mówi to wprost, a dziennik czeka na następny start skrótu. Gdy nie
wystartuje żadna wersja, opiekun pokazuje jedno natywne okienko z Komunikatem
startu, chyba że port trzyma już stara wersja, którą tata uruchomił skrótem,
także po cofnięciu bez zwolnionego portu.
Na końcu usuwa katalog tymczasowy aktualizacji.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Final

from rozliczenia.centrum import start_problems
from rozliczenia.centrum.platform import show_start_problem
from rozliczenia.centrum.version import running_centrum
from rozliczenia.centrum.tool_update import (
    NEW_VERSION_FAILED,
    ROLLBACK_FAILED,
    UPDATED,
    ToolClone,
    UpdateResult,
    write_result,
)
from rozliczenia.file_state import file_state
from rozliczenia.tool_files import TOOL_ROOT, port_free, start_command

# Tyle czekają: stare Centrum na zamknięcie (otwarte połączenia karty do 5 s) i nowa wersja na pierwszą odpowiedź.
PORT_TIMEOUT_S: Final = 60.0
START_TIMEOUT_S: Final = 60.0
_POLL_S: Final = 0.2
_STOP_TIMEOUT_S: Final = 10.0
_SOURCE: Final = TOOL_ROOT / "src"
# Pakiet-szkielet kopii: tylko moduły bez bibliotek narzędzia, które opiekun importuje.
_COPIED: Final = (
    "rozliczenia/__init__.py",
    "rozliczenia/file_state.py",
    "rozliczenia/message.py",
    "rozliczenia/tool_files.py",
    "rozliczenia/wall_clock.py",
    "rozliczenia/centrum/__init__.py",
    "rozliczenia/centrum/opener.py",
    "rozliczenia/centrum/platform.py",
    "rozliczenia/centrum/start_problems.py",
    "rozliczenia/centrum/tool_update.py",
    "rozliczenia/centrum/version.py",
    "rozliczenia/centrum/restart_guardian.py",
)
_BOOT: Final = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from rozliczenia.centrum.restart_guardian import main; raise SystemExit(main(sys.argv[2:]))"
)
# Windows: proces bez konsoli, który przeżyje zamknięcie Centrum; gdzie indziej robi to osobna sesja.
_DETACHED: Final = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


@dataclass(frozen=True)
class Restart:
    """Ponowny start po udanej aktualizacji.

    ``root`` to katalog narzędzia, ``result`` plik wyniku obok Ustawień Centrum,
    ``work`` katalog tymczasowy aktualizacji z kopią opiekuna.
    """

    port: int
    before: str | None
    after: str
    root: Path
    result: Path
    installed: bool
    work: Path

    def arguments(self) -> list[str]:
        return [
            "--port",
            str(self.port),
            "--before",
            self.before or "",
            "--after",
            self.after,
            "--root",
            str(self.root),
            "--result",
            str(self.result),
            "--work",
            str(self.work),
            *(["--installed"] if self.installed else []),
        ]

    @classmethod
    def of_arguments(cls, argv: Sequence[str]) -> Restart:
        parser = argparse.ArgumentParser(description="Opiekun ponownego startu Centrum rozliczeń.")
        parser.add_argument("--port", type=int, required=True)
        parser.add_argument("--before", required=True)
        parser.add_argument("--after", required=True)
        parser.add_argument("--root", type=Path, required=True)
        parser.add_argument("--result", type=Path, required=True)
        parser.add_argument("--work", type=Path, required=True)
        parser.add_argument("--installed", action="store_true")
        args = parser.parse_args(argv)
        return cls(args.port, args.before or None, args.after, args.root, args.result, args.installed, args.work)


def prepare(work: Path) -> Path:
    """Kopiuje opiekuna z tej wersji narzędzia do ``work``, zanim aktualizacja zmieni klon; zwraca katalog kopii."""

    copy = work / "opiekun"
    for name in _COPIED:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SOURCE / name, copy / name)
    return copy


def launch(copy: Path, restart: Restart) -> subprocess.Popen[bytes]:
    """Uruchamia opiekuna z kopii ``copy`` odłączonym procesem bez konsoli, który przeżyje zamknięcie Centrum."""

    # -I: ani katalog roboczy, ani PYTHONPATH nie podsuną modułów spoza kopii; -B: kopia bez __pycache__.
    return _detached([_windowless_python(), "-I", "-B", "-c", _BOOT, str(copy), *restart.arguments()], restart.root)


def main(argv: Sequence[str], *, show_problem: Callable[[str, str], None] = show_start_problem) -> int:
    """Ponowny start po aktualizacji: 0, gdy Centrum odpowiada (nowe albo cofnięte stare), inaczej 1.

    Wszystko albo nic: gdy nowa wersja nie odpowie (albo stare Centrum nie
    zwolni portu), klon wraca do commitu sprzed aktualizacji, a plik wyniku
    mówi, co się stało naprawdę, albo go nie ma, gdy dysk go nie przyjmie.
    ``show_problem`` pokazuje natywne okienko (tytuł, treść).
    """

    restart = Restart.of_arguments(argv)
    released = _port_released(restart.port)
    if released:
        # Nowe Centrum czyta wynik raz przy starcie, więc plik musi być gotowy, zanim ono wystartuje.
        _record(restart, UPDATED)
        new = _start_centrum(restart)
        if _answers(new, restart.port, restart.after):
            ToolClone(restart.root).confirm_update()
            shutil.rmtree(restart.work, ignore_errors=True)
            return 0
        _stop(new)
        # „ok” przestało być prawdą: Centrum ze skrótu w trakcie cofania nie może go przeczytać.
        with suppress(OSError):
            restart.result.unlink(missing_ok=True)
    before = restart.before
    rolled_back = _rolled_back(restart)
    _record(restart, NEW_VERSION_FAILED if rolled_back else ROLLBACK_FAILED)
    # Po nieudanym cofnięciu nie ma starej wersji. Bez zwolnionego portu tak samo jak po nim: stare Centrum mogło
    # oddać port w trakcie cofania (#726).
    if rolled_back and before is not None:
        if _port_released(restart.port) and _answers(_start_centrum(restart), restart.port, before):
            return 0
        # Tata mógł po cofnięciu uruchomić starą wersję skrótem: zajęła port przed opiekunem i działa.
        if _runs(restart.port, before):
            return 0
    # Karta nie ma już z kim rozmawiać: jedno okienko zamiast ciszy.
    problem = start_problems.not_started_after_update()
    show_problem(start_problems.TITLE, problem.text)
    return 1


def _record(restart: Restart, code: str) -> None:
    """Wynik dla karty; gdy dysk go nie przyjmie, karta nic nie powie, a opiekun i tak startuje Centrum albo okienko."""

    with suppress(OSError):
        write_result(restart.result, UpdateResult(code, restart.before, restart.after, restart.installed))


def _start_centrum(restart: Restart) -> subprocess.Popen[bytes]:
    """Centrum z klonu jak skrót, tylko bez karty i bez okienek: tata ma widzieć jeden Komunikat."""

    return _detached(start_command(restart.root, restart.port), restart.root)


def _stop(centrum: subprocess.Popen[bytes]) -> None:
    """Zatrzymuje wersję, która nie odpowiedziała, żeby zwolniła port i pliki klonu."""

    if centrum.poll() is not None:
        return
    centrum.terminate()
    try:
        centrum.wait(timeout=_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        centrum.kill()
        centrum.wait()


def _rolled_back(restart: Restart) -> bool:
    """Cofa klon z dziennika „Aktualizacja w toku”; po porażce dziennik z kopią plików taty czeka na następny start skrótu."""

    try:
        ToolClone(restart.root).roll_back()
    except Exception:
        return False
    finally:
        shutil.rmtree(restart.work, ignore_errors=True)
    return True


def _windowless_python() -> str:
    """``pythonw.exe`` obok tego Pythona w Windows (bez okna konsoli, jak skrót); gdzie indziej ten sam Python."""

    windowless = Path(sys.executable).with_name("pythonw.exe")
    return str(windowless) if sys.platform == "win32" and file_state(windowless) == "file" else sys.executable


def _detached(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_DETACHED,
        start_new_session=sys.platform != "win32",
    )


def _port_released(port: int) -> bool:
    deadline = time.monotonic() + PORT_TIMEOUT_S
    while True:
        if port_free(port):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(_POLL_S)


def _answers(centrum: subprocess.Popen[bytes], port: int, commit: str) -> bool:
    deadline = time.monotonic() + START_TIMEOUT_S
    while centrum.poll() is None and time.monotonic() < deadline:
        if _runs(port, commit):
            return True
        time.sleep(_POLL_S)
    return False


def _runs(port: int, commit: str) -> bool:
    running = running_centrum(port, timeout_s=2)
    return running is not None and running.runs(commit)
