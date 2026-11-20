from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import http.client
import select
import socket
import threading
import time

from atrapy.serwer_http import CZEKANIE_S, serwer_http
from tests.fixtures.linie_watkow import new_line, threads_since
from tests.fixtures.potomne import wait_for


class _KeepAlive(BaseHTTPRequestHandler):
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


def _server_closed_connection(sock: socket.socket) -> bool:
    # ZEWNĘTRZNE: gniazdo, które druga strona zamknęła, jest gotowe do odczytu, bo odczyt da koniec strumienia (man 2 select)
    return bool(select.select([sock], [], [], 0)[0])


def test_po_bloku_serwera_nie_zyje_watek_obslugi_polaczenia_ktore_klient_trzyma_otwarte() -> None:
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


def test_polaczenie_trzymane_przez_klienta_dluzej_niz_krok_czekania_dalej_obsluguje_zadania() -> None:
    with serwer_http(_KeepAlive, name="serwer-testu") as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        try:
            statuses: list[int] = []
            local_addresses: list[object] = []
            for _ in range(2):
                connection.request("GET", "/")
                response = connection.getresponse()
                response.read()
                sock = connection.sock
                statuses.append(response.status)
                local_addresses.append(sock.getsockname() if sock else None)
                assert sock is not None and not wait_for(lambda: _server_closed_connection(sock), 5 * CZEKANIE_S)
        finally:
            connection.close()

    assert (statuses, len(set(local_addresses)), None in local_addresses) == ([200, 200], 1, False), local_addresses
