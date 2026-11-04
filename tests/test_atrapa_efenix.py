"""Połączenia Atrapy efenix (``tests/fixtures/atrapa_efenix.py``): trwałe w bloku, zamknięte po nim.

Przy połączeniu na każde żądanie przeglądarki testów pod xdist na Windows wyczerpywały gniazda
(``net::ERR_NO_BUFFER_SPACE``, #778), więc Atrapa odpowiada na kolejne żądania tym samym połączeniem, a koniec bloku
zamyka połączenia, które zostały otwarte, żeby po nim nic pod jej adresem nie odpowiadało.
"""

from __future__ import annotations

from http.client import HTTPConnection
import socket
import threading
from urllib.parse import urlparse

import pytest

from tests.fixtures.atrapa_efenix import LIST_PAGE, LIST_SCRIPT, LOGIN_PAGE, LOGOUT, SEARCH, AtrapaOrder, atrapa_efenix
from tests.fixtures.potomne import wait_for

_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _connection(url: str) -> HTTPConnection:
    address = urlparse(url)
    assert address.hostname is not None
    assert address.port is not None
    return HTTPConnection(address.hostname, address.port, timeout=10)


def _answer(connection: HTTPConnection, method: str, path: str, body: str | None = None) -> tuple[int, socket.socket | None]:
    """Status odpowiedzi na żądanie i gniazdo połączenia, którym poszło."""

    connection.request(method, f"/{path}", body=body, headers=_FORM if body is not None else {})
    sent_by = connection.sock
    response = connection.getresponse()
    response.read()
    return response.status, sent_by


def test_atrapa_odpowiada_na_kolejne_zadania_tym_samym_polaczeniem_takze_przekierowaniem_i_bledem() -> None:
    with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")]) as atrapa:
        connection = _connection(atrapa.url)
        answers = [
            _answer(connection, "GET", LIST_PAGE),
            _answer(connection, "GET", LIST_SCRIPT),
            _answer(connection, "POST", SEARCH, "numer=9301&rodzaj=szukanie&strona=1&na_stronie=10"),
            _answer(connection, "GET", "nie_ma.php"),
            _answer(connection, "GET", LOGOUT),
            _answer(connection, "GET", LOGIN_PAGE),
        ]
        connection.close()

    sockets = [sent_by for _, sent_by in answers]
    assert ([status for status, _ in answers], all(sent_by is sockets[0] for sent_by in sockets)) == ([200, 200, 200, 404, 302, 200], True)


@pytest.mark.parametrize(
    ("fields", "answer"),
    [
        pytest.param("", "Błąd bazy danych", id="bez-liczby-wierszy"),
        pytest.param("&na_stronie=", "Błąd bazy danych", id="pusta-liczba-wierszy"),
        pytest.param("&na_stronie=10&xrodzaj=", "Nie znaleziono pasujących wyników", id="pusty-rodzaj-zlecenia"),
    ],
)
def test_szukanie_bez_liczby_wierszy_albo_z_pustym_rodzajem_zlecenia_dostaje_jak_w_efenix_strone_bez_tabeli_wynikow(
    fields: str, answer: str
) -> None:
    with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")]) as atrapa:
        connection = _connection(atrapa.url)
        connection.request("POST", f"/{SEARCH}", body=f"numer=9301&rodzaj=szukanie&strona=1{fields}", headers=_FORM)
        refused = connection.getresponse().read().decode("utf-8")
        connection.request("POST", f"/{SEARCH}", body="numer=9301&rodzaj=szukanie&strona=1&na_stronie=10", headers=_FORM)
        found = connection.getresponse().read().decode("utf-8")
        connection.close()

    assert (answer in refused, "<table" in refused, "9301" in refused, "<table" in found, "9301" in found) == (True, False, False, True, True)


def test_szukanie_bez_sesji_dostaje_jak_w_efenix_samo_ostrzezenie_o_wygaslej_sesji_bez_przekierowania() -> None:
    with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")]) as atrapa:
        atrapa.expire_session()
        connection = _connection(atrapa.url)
        connection.request("POST", f"/{SEARCH}", body="numer=9301&rodzaj=szukanie&strona=1&na_stronie=10", headers=_FORM)
        response = connection.getresponse()
        answer = (response.status, response.getheader("Location"), response.read().decode("utf-8"))
        connection.close()

    assert answer[:2] == (200, None)
    assert ("Twoja sesja wygasła - zaloguj się ponownie !" in answer[2], "<table" in answer[2], "9301" in answer[2]) == (True, False, False)


def test_po_bloku_atrapy_polaczenie_otwarte_w_bloku_nie_dostaje_odpowiedzi_a_po_jego_zamknieciu_nie_zostaje_jej_watek() -> None:
    before = set(threading.enumerate())
    with atrapa_efenix([]) as atrapa:
        connection = _connection(atrapa.url)
        assert _answer(connection, "GET", LIST_PAGE)[0] == 200

    with pytest.raises(ConnectionError):
        _answer(connection, "GET", LIST_PAGE)
    connection.close()
    assert wait_for(lambda: set(threading.enumerate()) <= before, seconds=10)
