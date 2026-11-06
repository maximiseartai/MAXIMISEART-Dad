"""Połączenia Atrapy efenix (``tests/fixtures/atrapa_efenix.py``) i decyzje serwera efenix w jej modelu.

Przy połączeniu na każde żądanie przeglądarki testów pod xdist na Windows wyczerpywały gniazda
(``net::ERR_NO_BUFFER_SPACE``, #778), więc Atrapa odpowiada na kolejne żądania tym samym połączeniem, a koniec bloku
zamyka połączenia, które zostały otwarte, żeby po nim nic pod jej adresem nie odpowiadało.

Decyzje serwera (sesja i jej wygaśnięcie, odmowy „Załaduj do zlecenia”, nadpisanie wyceny Wyceną Emmetta, zapis daty
wykonania i ilości) model ``tools/lib/model_efenix.py`` podejmuje dla każdego okna, więc ich macierz biegnie na jego
interfejsie ``SerwerEfenix``, bez HTTP i przeglądarki.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from http.client import HTTPConnection
import socket
import threading
from urllib.parse import urlparse

from model_efenix import PRICES, Action, EfenixOrder, EmmettRefusal, NoSession, Saved, SerwerEfenix, StanEfenix
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
        pytest.param("numer=9301", "Błąd bazy danych", id="bez-liczby-wierszy"),
        pytest.param("numer=9301&na_stronie=", "Błąd bazy danych", id="pusta-liczba-wierszy"),
        pytest.param("numer=9301&na_stronie=10&xrodzaj=", "Nie znaleziono pasujących wyników !", id="pusty-rodzaj-zlecenia"),
        pytest.param("numer=9399&na_stronie=10", "Nie znaleziono pasujących wyników !", id="numer-ktorego-nie-ma"),
    ],
)
def test_szukanie_bez_liczby_wierszy_z_pustym_rodzajem_zlecenia_albo_bez_wynikow_dostaje_jak_w_efenix_odpowiedz_bez_tabeli(
    fields: str, answer: str
) -> None:
    with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")]) as atrapa:
        connection = _connection(atrapa.url)
        connection.request("POST", f"/{SEARCH}", body=f"rodzaj=szukanie&strona=1&{fields}", headers=_FORM)
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


def _order() -> EfenixOrder:
    """Zlecenie z wyceną taty (T, 019: 2) i inną propozycją Emmetta (O, 012: 1)."""

    return EfenixOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1", quantities={"019": 2}, emmett={"012": 1})


# Jedno działanie okna każdego rodzaju na zleceniu ``_order``.
_ACTS: dict[Action, Callable[[SerwerEfenix[EfenixOrder]], object]] = {
    Action.SEARCH: lambda serwer: serwer.search("9301"),
    Action.OPEN: lambda serwer: serwer.page("901"),
    Action.DATE: lambda serwer: serwer.set_date("901", date(2026, 9, 9)),
    Action.PROPOSAL: lambda serwer: serwer.proposal("901"),
    Action.EMMETT: lambda serwer: serwer.load_emmett("901"),
    Action.QUANTITY: lambda serwer: serwer.save_quantity("901", "012", 1),
    Action.STATUS: lambda serwer: serwer.change_status("901", "Do akceptacji"),
}


@pytest.mark.parametrize("action", list(Action), ids=lambda action: action.name.lower())
def test_bez_sesji_serwer_efenix_nie_wykonuje_dzialania_okna_i_nie_zmienia_zlecenia(action: Action) -> None:
    stan = StanEfenix([_order()])
    stan.expire_session()

    answer = _ACTS[action](stan.serwer)

    assert (answer, stan.state(), stan.count(action)) == (NoSession.NO_SESSION, ([_order()], False), 1)


@pytest.mark.parametrize("action", list(Action), ids=lambda action: action.name.lower())
def test_sesja_wygasa_raz_przy_pierwszym_dzialaniu_ponad_zadana_liczbe_takich_dzialan(action: Action) -> None:
    """Każde inne działanie przed nim przechodzi, a po ponownym zalogowaniu sesja już nie wygasa."""

    stan = StanEfenix([_order()], expire_after=(action, 1))

    before = [isinstance(_ACTS[each](stan.serwer), NoSession) for each in Action]
    expired = _ACTS[action](stan.serwer)
    stan.log_in()
    again = _ACTS[action](stan.serwer)

    assert (any(before), expired, isinstance(again, NoSession), stan.count(action)) == (False, NoSession.NO_SESSION, False, 3)


def test_szukanie_ktore_lista_wysyla_sama_nie_liczy_sie_do_wygasniecia_sesji() -> None:
    stan = StanEfenix([_order()], expire_after=(Action.SEARCH, 1))

    answers = [stan.serwer.search("9301", own=own) for own in (True, False, False, True)]

    assert ([isinstance(answer, NoSession) for answer in answers], stan.count(Action.SEARCH)) == ([False, False, False, True], 2)


@pytest.mark.parametrize(
    ("refusal", "loaded", "logged_in"),
    [
        pytest.param(None, True, True, id="bez-odmowy"),
        pytest.param(EmmettRefusal.FORBIDDEN, False, True, id="403"),
        pytest.param(EmmettRefusal.SERVER_ERROR, True, True, id="500-po-zaladowaniu"),
        pytest.param(EmmettRefusal.ELSEWHERE, False, True, id="przekierowanie-na-liste"),
        pytest.param(EmmettRefusal.LOGGED_OUT, False, False, id="wylogowanie"),
        pytest.param(EmmettRefusal.NOK, False, True, id="nok"),
        pytest.param(EmmettRefusal.OTHER, False, True, id="inna-tresc"),
    ],
)
def test_zaladuj_do_zlecenia_laduje_wycene_emmetta_bez_odmowy_i_przed_bledem_serwera_a_wylogowanie_konczy_sesje(
    refusal: EmmettRefusal | None, loaded: bool, logged_in: bool
) -> None:
    stan = StanEfenix([replace(_order(), emmett_refusal=refusal)])

    answer = stan.serwer.load_emmett("901")

    [order], session = stan.state()
    assert (answer, order.quantities, order.emmett_loads, session) == (refusal, {"012": 1} if loaded else {"019": 2}, int(loaded), logged_in)


@pytest.mark.parametrize(
    ("quantities", "over_pricing"),
    [
        pytest.param({}, 0, id="zlecenie-bez-ilosci"),
        pytest.param({"012": 1}, 0, id="wycena-rowna-propozycji"),
        pytest.param({"019": 2}, 1, id="wycena-taty"),
    ],
)
def test_wycena_emmetta_zaladowana_na_inna_wycene_liczy_sie_jako_nadpisanie_wyceny(quantities: dict[str, int], over_pricing: int) -> None:
    stan = StanEfenix([replace(_order(), quantities=quantities)])

    stan.serwer.load_emmett("901")

    [order], _ = stan.state()
    assert (order.quantities, order.emmett_over_pricing) == ({"012": 1}, over_pricing)


@pytest.mark.parametrize(
    ("refuse_dates", "answer", "saved"),
    [pytest.param(False, True, date(2026, 9, 9), id="zapis"), pytest.param(True, False, None, id="odpowiedz-bez-zapisu")],
)
def test_serwer_ktory_odmawia_dat_odpowiada_na_zapis_daty_wykonania_bez_zapisu(refuse_dates: bool, answer: bool, saved: date | None) -> None:
    stan = StanEfenix([_order()], refuse_dates=refuse_dates)

    assert (stan.serwer.set_date("901", date(2026, 9, 9)), stan.serwer.date_of("901")) == (answer, saved)


@pytest.mark.parametrize(
    ("code", "quantity", "answer", "quantities"),
    [
        pytest.param("012", 3, Saved(Decimal("6.00"), Decimal("14.00")), {"019": 2, "012": 3}, id="nowa-pozycja"),
        pytest.param("019", 0, Saved(Decimal("0.00"), Decimal("0.00")), {}, id="zero-usuwa-pozycje"),
        pytest.param("999", 1, None, {"019": 2}, id="kod-spoza-katalogu"),
        pytest.param("012", None, None, {"019": 2}, id="ilosc-niecalkowita"),
    ],
)
def test_zapis_ilosci_liczy_w_cenach_stanu_zero_usuwa_pozycje_a_kod_spoza_katalogu_i_ilosc_niecalkowita_dostaja_odmowe(
    code: str, quantity: int | None, answer: Saved | None, quantities: dict[str, int]
) -> None:
    stan = StanEfenix([_order()], prices={**PRICES, "012": Decimal("2.00"), "019": Decimal("4.00")})

    saved = stan.serwer.save_quantity("901", code, quantity)

    [order], _ = stan.state()
    assert (saved, order.quantities) == (answer, quantities)
