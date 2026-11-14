"""Serwer Centrum rozliczeń: uvicorn na ``127.0.0.1`` do zamknięcia z karty Centrum albo Ctrl+C."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import socket
import threading

import uvicorn
from fastapi import FastAPI
from uvicorn.config import LOGGING_CONFIG

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import has_console
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.version import tool_commit, version_label
from rozliczenia.tool_files import HOST

_GRACEFUL_SHUTDOWN_S = 5
"""Otwarte połączenia (np. strumień postępu) nie wstrzymują zamknięcia dłużej."""
AFTER_START = "po_starcie"
"""Klucz stanu ``lifespan`` aplikacji (ASGI ``state``): krok, który serwer robi zaraz po wpisie ``start``, przed pierwszym
zapytaniem, więc jego wpisy w dzienniku należą do tej pracy Centrum (``CentrumLog.recent`` liczy je od ``start``)."""


def serve(
    app: FastAPI,
    *,
    listener: socket.socket,
    on_ready: Callable[[str], None],
    shutdown: Shutdown,
    log: CentrumLog,
) -> int:
    """Obsługuje żądania do zamknięcia; ``on_ready`` dostaje adres, gdy serwer już odpowiada."""

    port = int(listener.getsockname()[1])
    url = f"http://{HOST}:{port}/"
    console = has_console()
    if not console:
        _silence_uvicorn()
    config = uvicorn.Config(
        app,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_S,
        log_config=LOGGING_CONFIG if console else None,
    )

    def started(state: Mapping[str, object]) -> None:
        log.started(port=port, version=version_label(tool_commit()), console=console)
        after_start(state)
        threading.Thread(target=on_ready, args=(url,), name="centrum-gotowosc", daemon=True).start()

    server = _Server(config, started=started, stopping=lambda: log.stopped(port=port))

    def stop_when_asked() -> None:
        shutdown.wait()
        server.should_exit = True

    threading.Thread(target=stop_when_asked, name="centrum-zamkniecie", daemon=True).start()
    log.hold_until_started()
    try:
        server.run(sockets=[listener])
    except Exception as failure:
        log.unexpected_failure(failure, where="serwer")
        return 1
    finally:
        log.release_held()
        listener.close()
    return 0 if server.started else 1


def after_start(state: Mapping[str, object]) -> None:
    step = state.get(AFTER_START)
    if callable(step):
        step()


class _Server(uvicorn.Server):
    """Uvicorn, który zgłasza start zaraz po zajęciu portu, a zamykanie, zanim go zwolni.

    ``shutdown`` uvicorn zamyka gniazdo, a po nim opiekun ponownego startu od razu startuje nowe Centrum,
    więc ``stop`` po ``shutdown`` trafiłby do dziennika po ``start`` nowego. Uvicorn woła ``shutdown``
    tylko po udanym starcie.
    """

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        started: Callable[[Mapping[str, object]], None],
        stopping: Callable[[], None],
    ) -> None:
        super().__init__(config)
        self._started = started
        self._stopping = stopping

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._started(self.lifespan.state)

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self._stopping()
        await super().shutdown(sockets=sockets)


def _silence_uvicorn() -> None:
    """Pod ``pythonw`` nie ma ``sys.stdout`` ani ``sys.stderr``: logi uvicorn nie mają dokąd trafić.

    Domyślna konfiguracja logów uvicorn pyta ``sys.stdout.isatty()`` i bez konsoli
    przerywa start. Bezpieczne fakty i tak trafiają do dziennika Centrum.
    """

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(logging.NullHandler())
    uvicorn_logger.propagate = False
