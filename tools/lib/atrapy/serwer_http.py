"""Lokalny serwer HTTP atrap i testów, którego wątki obsługi kończą się razem z nim.

``ThreadingHTTPServer`` obsługuje każde połączenie we własnym wątku, a ``shutdown`` kończy tylko pętlę przyjmowania:
wątek połączenia, które klient (przeglądarka, ``requests`` z pulą połączeń) trzyma otwarte, czyta dalej następne żądanie
po końcu serwera, więc żyje w oknie następnego testu, aż klient zamknie połączenie (#2012). Budzenie zablokowanego
odczytu z zewnątrz zależy od systemu (``shutdown`` budzi go na Linuksie i macOS, a na Windows nie, i ``close()`` nie
zamyka gniazda, dopóki ``rfile`` i ``wfile`` handlera trzymają do niego referencję), więc wątek obsługi kończy się sam:
przyjęte połączenie (``Polaczenie``) czeka na dane w krokach po ``CZEKANIE_S`` i po fladze końca serwera zwraca koniec
strumienia, a ``BaseHTTPRequestHandler`` kończy wtedy połączenie jak po rozłączeniu klienta.

Granica z natury tego mechanizmu: na każdym systemie kończy się najpóźniej jeden krok po fladze wątek, który czeka na
żądanie albo na jego treść. Zapis zostaje blokujący, a dopóki serwer działa, odczyt czeka bez limitu, więc połączenie
trzymane przez klienta i wolna odpowiedź się nie zrywają. Wątku, który stoi gdzie indziej (w kodzie handlera na
zdarzeniu testu, w zapisie do klienta, który nie czyta), mechanizm nie kończy: blok czeka na niego najwyżej
``KONIEC_S``, a wątek, który przeżyje, zgłasza straż stanu procesu (``tests/fixtures/stan_procesu.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socket
import sys
import threading
import time
from typing import Any

POLL_S = 0.05
"""Co tyle pętla serwera sprawdza ``shutdown``."""
CZEKANIE_S = 0.05
"""Krok, w którym odczyt przyjętego połączenia czeka na dane, zanim sprawdzi flagę końca serwera."""
KONIEC_S = 10.0
"""Najdłużej tyle po fladze końca blok czeka na wątki obsługi."""


class Polaczenie(socket.socket):
    """Przyjęte połączenie, którego odczyt czeka na dane w krokach po ``CZEKANIE_S``, a po fladze ``koniec`` zwraca
    koniec strumienia (0 bajtów); zapis i reszta gniazda działają jak zwykle."""

    koniec: threading.Event

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        if not self._czeka_na_dane():
            return 0
        return super().recv_into(buffer, nbytes, flags)

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        if not self._czeka_na_dane():
            return b""
        return super().recv(bufsize, flags)

    def _czeka_na_dane(self) -> bool:
        """Czy są dane albo koniec od klienta (prawda), czy przyszła flaga końca serwera (fałsz)."""

        while not self.koniec.is_set():
            if select.select([self], [], [], CZEKANIE_S)[0]:
                return True
        return False


class SerwerHttp(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` na ``127.0.0.1`` z wolnym portem, którego połączenia kończą się po fladze końca, a który
    pamięta wątki obsługi, żeby na nie poczekać."""

    daemon_threads = True
    # Kolejka ``listen`` dłuższa niż domyślne 5: Windows odrzuca połączenie ponad kolejkę, a macOS i Linux je trzymają.
    request_queue_size = 128

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self._handlers: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._koniec = threading.Event()
        super().__init__(("127.0.0.1", 0), handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        polaczenie = Polaczenie(connection.family, connection.type, connection.proto, fileno=connection.detach())
        polaczenie.koniec = self._koniec
        return polaczenie, address

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        with self._lock:
            self._handlers.add(threading.current_thread())
        super().process_request_thread(request, client_address)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Połączenie, które serwer skończył flagą końca, nie jest błędem obsługi do wydruku na stderr testu.
        if not (self._koniec.is_set() and isinstance(sys.exc_info()[1], OSError)):
            super().handle_error(request, client_address)

    def close_connections(self) -> None:
        """Po ``shutdown`` stawia flagę końca, więc każdy wątek obsługi, który czeka na dane, kończy się w ciągu kroku
        ``CZEKANIE_S``, i czeka na wątki obsługi najwyżej ``KONIEC_S``."""

        self._koniec.set()
        deadline = time.monotonic() + KONIEC_S
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            handler.join(max(deadline - time.monotonic(), 0))


@contextmanager
def serwer_http(handler: type[BaseHTTPRequestHandler], *, name: str, poll_s: float = POLL_S) -> Iterator[SerwerHttp]:
    """Serwer ``handler`` w wątku ``name`` na czas bloku; na końcu ``shutdown``, koniec połączeń z czekaniem na wątki
    obsługi, zamknięcie gniazda nasłuchu i koniec wątku pętli, więc po bloku nie żyje żaden jego wątek. Obsługa, która
    czeka na zdarzenie testu, dostaje je przed końcem bloku."""

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
