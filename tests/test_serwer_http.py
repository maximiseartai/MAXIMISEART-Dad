"""Serwer HTTP atrap i testów (``tools/lib/atrapy/serwer_http.py``): po bloku nie żyje żaden jego wątek (#2012)."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import http.client
import select
import threading
import time

from atrapy.serwer_http import CZEKANIE_S, serwer_http
from tests.fixtures.linie_watkow import new_line, threads_since
from tests.fixtures.potomne import wait_for


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
    # żądanie. Serwer nie budzi tego odczytu przez system (shutdown ani close gniazda), tylko flagą końca, więc ten
    # test na każdym systemie sprawdza tę samą drogę, którą wątek obsługi kończy się na Windows.
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
    # Czekanie w krokach dotyczy tylko końca serwera: dopóki serwer działa, połączenie keep-alive nie zrywa się po kroku.
    with serwer_http(_KeepAlive, name="serwer-testu") as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        try:
            answers = []
            for _ in range(2):
                connection.request("GET", "/")
                response = connection.getresponse()
                response.read()
                sock = connection.sock
                answers.append((response.status, sock.getsockname() if sock else None))
                # Przez kilka kroków czekania serwer nie zamyka połączenia (koniec strumienia daje gniazdu dane).
                assert sock is not None and not wait_for(lambda: bool(select.select([sock], [], [], 0)[0]), 5 * CZEKANIE_S)
        finally:
            connection.close()

    # To samo gniazdo klienta (ten sam port lokalny) dostaje obie odpowiedzi.
    assert [status for status, _ in answers] == [200, 200] and answers[0][1] == answers[1][1] is not None, answers
