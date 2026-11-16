"""Serwer HTTP atrap i testów (``tools/lib/atrapy/serwer_http.py``): po bloku nie żyje żaden jego wątek (#2012)."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import http.client
import threading
import time

from atrapy.serwer_http import serwer_http
from tests.fixtures.linie_watkow import new_line, threads_since


class _KeepAlive(BaseHTTPRequestHandler):
    """Odpowiada bez zamykania połączenia (HTTP/1.1), a koniec obsługi trwa chwilę, jak domknięcie odpowiedzi."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def finish(self) -> None:
        time.sleep(0.2)
        super().finish()

    def log_message(self, format: str, *args: object) -> None:
        return


def test_po_bloku_serwera_nie_zyje_watek_obslugi_polaczenia_ktore_klient_trzyma_otwarte() -> None:
    # Klient trzyma połączenie po odpowiedzi, jak przeglądarka i pula requests, więc wątek obsługi czeka na następne
    # żądanie; bez zamknięcia połączeń serwer czekałby na niego bez końca, a bez czekania wątek przeżyłby blok.
    since = new_line()
    connections: list[http.client.HTTPConnection] = []
    ended = threading.Event()

    def serve_one_request() -> None:
        with serwer_http(_KeepAlive, name="serwer-testu") as server:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
            connections.append(connection)
            connection.request("GET", "/")
            connection.getresponse().read()
        ended.set()

    client = threading.Thread(target=serve_one_request, name="klient-serwera-testu", daemon=True)
    client.start()
    finished = ended.wait(30)
    alive = [thread.name for thread in threads_since(since) if "process_request_thread" in thread.name]
    for connection in connections:
        connection.close()
    client.join(30)

    assert (finished, alive) == (True, [])
