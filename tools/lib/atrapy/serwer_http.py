"""Lokalny serwer HTTP atrap i testów, którego wątki obsługi kończą się razem z nim.

``ThreadingHTTPServer`` obsługuje każde połączenie we własnym wątku, a ``shutdown`` kończy tylko pętlę przyjmowania:
wątek połączenia, które klient (przeglądarka, ``requests`` z pulą połączeń) trzyma otwarte, czyta dalej następne żądanie
po końcu serwera, więc żyje w oknie następnego testu, aż klient zamknie połączenie (#2012). ``serwer_http`` po
``shutdown`` zamyka w obie strony każde przyjęte połączenie, które jest jeszcze otwarte, więc wątek, który na nim czyta
albo pisze, kończy obsługę, a ``server_close`` czeka na jego koniec.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
from typing import Any

POLL_S = 0.05
"""Co tyle pętla serwera sprawdza ``shutdown``."""


class SerwerHttp(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` na ``127.0.0.1`` z wolnym portem, który pamięta przyjęte połączenia, żeby je zamknąć, a
    ``server_close`` czeka na koniec każdego wątku obsługi (``block_on_close``)."""

    daemon_threads = False
    block_on_close = True
    # Kolejka ``listen`` dłuższa niż domyślne 5: Windows odrzuca połączenie ponad kolejkę, a macOS i Linux je trzymają.
    request_queue_size = 128

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def get_request(self) -> tuple[socket.socket, Any]:
        # Pętla serwera przyjmuje połączenie przed końcem ``shutdown``, więc po nim zbiór ma każde przyjęte połączenie.
        connection, address = super().get_request()
        with self._connections_lock:
            self._connections.add(connection)
        return connection, address

    def shutdown_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
        if isinstance(request, socket.socket):
            with self._connections_lock:
                self._connections.discard(request)
        super().shutdown_request(request)

    def close_connections(self) -> None:
        """Po ``shutdown`` zamyka w obie strony połączenia, które są jeszcze otwarte."""

        with self._connections_lock:
            for connection in self._connections:
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)


@contextmanager
def serwer_http(handler: type[BaseHTTPRequestHandler], *, name: str, poll_s: float = POLL_S) -> Iterator[SerwerHttp]:
    """Serwer ``handler`` w wątku ``name`` na czas bloku; na końcu ``shutdown``, zamknięcie przyjętych połączeń,
    zamknięcie gniazda nasłuchu z czekaniem na wątki obsługi i koniec wątku pętli, więc po bloku nie żyje żaden jego
    wątek. Obsługa, która czeka na zdarzenie testu, dostaje je przed końcem bloku."""

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
