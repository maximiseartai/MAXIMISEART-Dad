"""Proxy z ustawień systemu w teście, bez wyjścia do sieci: lokalny serwer, który zapisuje każde żądanie i odmawia
(``system_proxy``), albo serwer testu w tej roli (``proxy_of_system``)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler

import pytest

from atrapy.serwer_http import serwer_http


@contextmanager
def system_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Proxy HTTP i HTTPS ze zmiennych środowiska (stąd czyta je urllib na każdym systemie); daje metodę i cel każdego
    żądania, które do niego doszło (bez wersji HTTP: urllib Pythona 3.11 łączy CONNECT w HTTP/1.0, nowszy w 1.1),
    a każde odrzuca kodem 502."""

    requests: list[str] = []

    class _Proxy(BaseHTTPRequestHandler):
        def _refuse(self) -> None:
            requests.append(f"{self.command} {self.path}")
            self.send_response(502)
            self.end_headers()

        do_CONNECT = do_GET = do_POST = do_PATCH = do_DELETE = _refuse

        def log_message(self, format: str, *args: object) -> None:
            pass

    with serwer_http(_Proxy, name="proxy-systemu") as server:
        proxy_of_system(monkeypatch, server.url)
        yield requests


def proxy_of_system(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    """Serwer pod ``address`` jest proxy HTTP i HTTPS z ustawień systemu dla każdego adresu."""

    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.setenv(name, address)
    for name in ("no_proxy", "NO_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
