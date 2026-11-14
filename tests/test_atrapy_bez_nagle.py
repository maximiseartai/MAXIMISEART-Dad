"""Serwery atrap z kilkoma zapisami na odpowiedź mają ``TCP_NODELAY`` na każdym przyjętym połączeniu (#1856, #1860).

Bez niego drugi mały zapis odpowiedzi czeka na ACK klienta, który Linux opóźnia o ~40 ms, więc każda odpowiedź
atrapy IMAP, SMTP, Atrapy efenix i proxy skilla ``verify-wycena-efenix`` kosztowała tyle. Test czyta opcję z gniazda
przyjętego przez serwer, a nie czas, więc pada na każdym systemie, także tam, gdzie ACK nie jest opóźniany.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
import importlib.util
from pathlib import Path
import socket
import socketserver
import sys
from types import ModuleType
from urllib.parse import urlparse

import pytest

from atrapy.atrapa_efenix import atrapa_efenix
from atrapy.skrzynka_raportow import AtrapaImap, AtrapaSmtp
from tests.fixtures.potomne import wait_for

ROOT = Path(__file__).resolve().parents[1]
WYCENA_SCRIPTS = ROOT / ".agents" / "skills" / "verify-wycena-efenix" / "scripts"


def _imap() -> AbstractContextManager[AtrapaImap]:
    return AtrapaImap(address="skrzynka@przyklad.invalid", password="haslo")


@contextmanager
def _imap_port() -> Iterator[int]:
    with _imap() as imap:
        yield imap.port


@contextmanager
def _smtp_port() -> Iterator[int]:
    with _imap() as imap, AtrapaSmtp(imap) as smtp:
        yield smtp.port


@contextmanager
def _efenix_port() -> Iterator[int]:
    with atrapa_efenix([]) as atrapa:
        port = urlparse(atrapa.url).port
        assert port is not None
        yield port


def _wycena_proxy(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(WYCENA_SCRIPTS))
    spec = importlib.util.spec_from_file_location("awarie_efenix", WYCENA_SCRIPTS / "awarie_efenix.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass modułu szuka go w ``sys.modules`` już w trakcie wykonania.
    monkeypatch.setitem(sys.modules, "awarie_efenix", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def nodelay(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """``TCP_NODELAY`` każdego połączenia przyjętego od teraz przez serwer ``socketserver``, odczytany z gniazda serwera
    zaraz po ``StreamRequestHandler.setup``, który ustawia go według ``disable_nagle_algorithm``."""

    seen: list[bool] = []
    setup = socketserver.StreamRequestHandler.setup

    def recorded(self: socketserver.StreamRequestHandler) -> None:
        setup(self)
        seen.append(bool(self.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)))

    monkeypatch.setattr(socketserver.StreamRequestHandler, "setup", recorded)
    return seen


def _accepted(port: int, seen: list[bool]) -> list[bool]:
    with socket.create_connection(("127.0.0.1", port), timeout=10):
        assert wait_for(lambda: bool(seen), 10), "serwer nie przyjął połączenia"
    return seen


@pytest.mark.parametrize("server", [_imap_port, _smtp_port, _efenix_port], ids=["atrapa-imap", "atrapa-smtp", "atrapa-efenix"])
def test_atrapa_wylacza_algorytm_nagle_na_przyjetym_polaczeniu(nodelay: list[bool], server: Callable[[], AbstractContextManager[int]]) -> None:
    with server() as port:
        assert _accepted(port, nodelay) == [True]


def test_proxy_skilla_wyceny_wylacza_algorytm_nagle_na_przyjetym_polaczeniu(nodelay: list[bool], monkeypatch: pytest.MonkeyPatch) -> None:
    awarie = _wycena_proxy(monkeypatch)

    with atrapa_efenix([]) as atrapa, awarie.Proxy(atrapa.url, awarie.Plan(), atrapa.expire_session) as proxy:
        port = urlparse(proxy.url).port
        assert port is not None
        assert _accepted(port, nodelay) == [True]
