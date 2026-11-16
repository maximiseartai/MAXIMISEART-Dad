"""Lokalny serwer HTTP atrap i testów, którego wątki obsługi kończą się razem z nim.

``ThreadingHTTPServer`` obsługuje każde połączenie we własnym wątku, a ``shutdown`` kończy tylko pętlę przyjmowania:
wątek połączenia, które klient (przeglądarka, ``requests`` z pulą połączeń) trzyma otwarte, czyta dalej następne żądanie
po końcu serwera, więc żyje w oknie następnego testu, aż klient zamknie połączenie (#2012). ``serwer_http`` po
``shutdown`` kończy każde przyjęte połączenie, które jest jeszcze otwarte, tak, jak system budzi zablokowany odczyt:
na Linuksie i macOS budzi go ``shutdown(SHUT_RDWR)``, a na Windows tylko zamknięcie gniazda (``closesocket``), więc
tam serwer gniazdo też zamyka. Zamknięcia nie robi na Linuksie i macOS, bo numer deskryptora wraca tam do puli od razu,
a wątek obsługi, który jeszcze go trzyma, mógłby pisać do pliku, który dostał ten numer. Potem czeka na każdy wątek
obsługi najwyżej ``KONIEC_S``: wątek, który i tak żyje, zostaje dla straży stanu procesu (``tests/fixtures/stan_procesu.py``)
zamiast zatrzymać blok bez końca.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import sys
import threading
import time
from typing import Any

POLL_S = 0.05
"""Co tyle pętla serwera sprawdza ``shutdown``."""
KONIEC_S = 10.0
"""Najdłużej tyle po zamknięciu połączeń blok czeka na wątki obsługi."""


class SerwerHttp(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` na ``127.0.0.1`` z wolnym portem, który pamięta przyjęte połączenia i wątki obsługi, żeby
    na końcu zakończyć połączenia i poczekać na wątki."""

    daemon_threads = True
    # Kolejka ``listen`` dłuższa niż domyślne 5: Windows odrzuca połączenie ponad kolejkę, a macOS i Linux je trzymają.
    request_queue_size = 128

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self._connections: set[socket.socket] = set()
        self._handlers: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._closing = threading.Event()
        super().__init__(("127.0.0.1", 0), handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def get_request(self) -> tuple[socket.socket, Any]:
        # Pętla serwera przyjmuje połączenie przed końcem ``shutdown``, więc po nim zbiór ma każde przyjęte połączenie.
        connection, address = super().get_request()
        with self._lock:
            self._connections.add(connection)
        return connection, address

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        with self._lock:
            self._handlers.add(threading.current_thread())
        super().process_request_thread(request, client_address)

    def shutdown_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
        if isinstance(request, socket.socket):
            with self._lock:
                self._connections.discard(request)
        super().shutdown_request(request)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Połączenie zakończone przez ``close_connections`` nie jest błędem obsługi do wydruku na stderr testu.
        if not (self._closing.is_set() and isinstance(sys.exc_info()[1], OSError)):
            super().handle_error(request, client_address)

    def close_connections(self) -> None:
        """Po ``shutdown`` kończy połączenia, które są jeszcze otwarte, tak, żeby zablokowany odczyt wrócił na każdym
        systemie, i czeka na wątki obsługi najwyżej ``KONIEC_S``."""

        self._closing.set()
        with self._lock:
            connections = list(self._connections)
        for connection in connections:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            if sys.platform == "win32":
                connection.close()
        deadline = time.monotonic() + KONIEC_S
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            handler.join(max(deadline - time.monotonic(), 0))


@contextmanager
def serwer_http(handler: type[BaseHTTPRequestHandler], *, name: str, poll_s: float = POLL_S) -> Iterator[SerwerHttp]:
    """Serwer ``handler`` w wątku ``name`` na czas bloku; na końcu ``shutdown``, koniec przyjętych połączeń z czekaniem
    na wątki obsługi, zamknięcie gniazda nasłuchu i koniec wątku pętli, więc po bloku nie żyje żaden jego wątek.
    Obsługa, która czeka na zdarzenie testu, dostaje je przed końcem bloku."""

    server = SerwerHttp(handler)
    thread = threading.Thread(target=server.serve_forever, args=(poll_s,), name=name, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.close_connections()
        server.server_close()
        thread.join()
