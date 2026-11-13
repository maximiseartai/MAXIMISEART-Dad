"""Start Centrum rozliczeń: skrót „Centrum rozliczeń” (``pythonw``, bez konsoli) albo ``run_centrum.py`` z konsolą.

Jedno Centrum na komputerze: gdy port jest zajęty, ``health`` rozstrzyga, czy
to własne Centrum z tego samego commitu narzędzia (wtedy tylko otwiera kartę),
Centrum innej wersji, czy inny program. Każdy błąd startu kończy się
komunikatem w trzech częściach: bez konsoli w natywnym okienku, z konsolą w
konsoli, a fakt trafia do dziennika Centrum. Ponowny start po Aktualizacji narzędzia (``--bez-okienek``)
nie pokazuje okienka, tylko zapisuje fakt w dzienniku: tata widzi wtedy jeden
Komunikat, w karcie. Takie Centrum przez 10 sekund ponawia zajęcie portu,
bo skrót kliknięty w trakcie ponownego startu trzyma go tylko do odczytu
dziennika: opiekun nie cofa przez to wersji, która działa. Przy imporcie moduł
używa tylko biblioteki standardowej, więc brak FastAPI albo uvicorn też staje
się takim komunikatem.

Skrót, który zajmie port i zastanie dziennik „Aktualizacja w toku”, kończy
Aktualizację narzędzia przerwaną wyłączeniem komputera: cofa klon do wersji
sprzed niej, zostawia dla karty wynik porażki nieoczekiwanej i startuje od
nowa w cofniętej wersji. Wtedy jeszcze nie wczytał niczego spoza biblioteki
standardowej, więc nowa wersja bez swoich bibliotek też da się cofnąć. Nie
cofa, dopóki opiekun ponownego startu może jeszcze kończyć aktualizację, ani
przy starcie nowej wersji przez samego opiekuna (``--bez-okienek``).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import functools
import socket
import subprocess
import sys
import time
import webbrowser

from rozliczenia.centrum import start_problems
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import has_console, show_start_problem
from rozliczenia.centrum.tool_update import (
    RESULT_FILE,
    UNEXPECTED,
    InterruptedUpdate,
    ToolClone,
    UpdateResult,
    write_result,
)
from rozliczenia.centrum.version import running_centrum, tool_commit, version_label
from rozliczenia.message import Message
from rozliczenia.tool_files import (
    CONFIG_DIR,
    DEFAULT_PORT,
    HOST,
    LOG_PATH,
    NO_BROWSER_FLAG,
    NO_DIALOGS_FLAG,
    PORT_FLAG,
    TOOL_ROOT,
    centrum_script,
    listen_locally,
)
from rozliczenia.wall_clock import epoch_s

_HEALTH_TIMEOUT_S = 5  # drugie kliknięcie skrótu może trafić na Centrum, które jeszcze startuje
_SHORTCUT_HOLDS_PORT_S = 10  # skrót kliknięty w trakcie ponownego startu oddaje port po odczycie dziennika (#246)
_POLL_S = 0.1


def parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Argumenty ``run_centrum.py``: z linii poleceń, ze skrótu albo z ``tool_files.start_command`` opiekuna."""

    parser = argparse.ArgumentParser(description="Uruchamia Centrum rozliczeń w przeglądarce.")
    parser.add_argument(PORT_FLAG, type=int, default=DEFAULT_PORT, help=f"Port na {HOST}.")
    parser.add_argument(NO_BROWSER_FLAG, action="store_true", help="Nie otwieraj karty w przeglądarce.")
    parser.add_argument(
        NO_DIALOGS_FLAG,
        action="store_true",
        help="Błąd startu tylko do dziennika Centrum, bez natywnego okienka (ponowny start po aktualizacji).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    log = CentrumLog(LOG_PATH)
    refuse = functools.partial(_refuse, port=args.port, log=log, dialog=not args.bez_okienek)
    restart_from_disk = [sys.executable, str(centrum_script(TOOL_ROOT)), *(sys.argv[1:] if argv is None else argv)]
    try:
        return _start(
            args.port,
            log,
            refuse,
            browser=not args.no_browser,
            started_by_guardian=args.bez_okienek,
            restart_from_disk=restart_from_disk,
        )
    except Exception as failure:
        log.unexpected_failure(failure, where="start")
        return refuse(start_problems.unexpected_start_failure())


def _start(
    port: int,
    log: CentrumLog,
    refuse: Callable[[Message], int],
    *,
    browser: bool,
    started_by_guardian: bool,
    restart_from_disk: list[str],
) -> int:
    def open_tab(url: str) -> None:
        if browser:
            webbrowser.open(url)

    url = f"http://{HOST}:{port}/"
    try:
        listener = _listen_when_released(port, wait_s=_SHORTCUT_HOLDS_PORT_S if started_by_guardian else 0)
    except OSError:
        running = running_centrum(port, timeout_s=_HEALTH_TIMEOUT_S)
        if running is None:
            return refuse(start_problems.port_taken(port))
        if running.runs(tool_commit()):
            log.already_running(port=port)
            _say(f"Centrum rozliczeń już działa: {url}")
            open_tab(url)
            return 0
        open_tab(url)  # tata widzi starą kartę z przyciskiem „Zamknij Centrum rozliczeń”
        return refuse(start_problems.other_version_running(port, version_label(running.commit)))

    try:
        interrupted = None if started_by_guardian else ToolClone(TOOL_ROOT).interrupted_update()
        guardian_may_run = interrupted is not None and interrupted.guardian_may_run(epoch_s())
        if interrupted is not None and not guardian_may_run:
            _roll_back(interrupted)
    except BaseException:
        listener.close()
        raise
    if interrupted is not None:
        listener.close()
        if guardian_may_run:
            return refuse(start_problems.update_finishing())
        # Ten proces ma w pamięci moduły wersji, którą właśnie cofnął: Centrum startuje od nowa z dysku.
        return subprocess.call(restart_from_disk)

    try:
        from rozliczenia.centrum.app import create_app
        from rozliczenia.centrum.platform import system_platform
        from rozliczenia.centrum.server import serve
        from rozliczenia.centrum.shortcut import system_autostart
        from rozliczenia.centrum.shutdown import Shutdown
    except ModuleNotFoundError as missing:
        listener.close()
        return refuse(start_problems.missing_library(missing.name or "?"))

    def announce(address: str) -> None:
        _say(f"Centrum rozliczeń działa: {address}")
        open_tab(address)

    shutdown = Shutdown(log)
    app = create_app(
        config=CONFIG_DIR, platform=system_platform(), autostart=system_autostart(), log=log, shutdown=shutdown
    )
    return serve(app, listener=listener, on_ready=announce, shutdown=shutdown, log=log)


def _listen_when_released(port: int, *, wait_s: float) -> socket.socket:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return listen_locally(port)
        except OSError:
            if time.monotonic() >= deadline:
                raise
        time.sleep(_POLL_S)


def _roll_back(interrupted: InterruptedUpdate) -> None:
    """Cofa przerwaną Aktualizację narzędzia; każda porażka to wyjątek, a dziennik zostaje na następny start.

    Plik wyniku od opiekuna mógł już mówić „ok”, a karta cofniętej wersji ma
    pokazać porażkę.
    """

    ToolClone(TOOL_ROOT).roll_back()
    write_result(CONFIG_DIR / RESULT_FILE, UpdateResult(UNEXPECTED, interrupted.before, interrupted.after))


def _refuse(problem: Message, *, port: int, log: CentrumLog, dialog: bool) -> int:
    log.start_failed(problem.code, port=port)
    if has_console():
        print(problem.text, flush=True)
    elif dialog:
        show_start_problem(start_problems.TITLE, problem.text)
    return 1


def _say(line: str) -> None:
    if has_console():
        print(line, flush=True)

