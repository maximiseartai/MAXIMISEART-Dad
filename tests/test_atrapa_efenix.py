"""Połączenia Atrapy efenix (``tests/fixtures/atrapa_efenix.py``), decyzje serwera efenix w jej modelu i kontrakt okna w
procesie z oknem przeglądarki.

Przy połączeniu na każde żądanie przeglądarki testów pod xdist na Windows wyczerpywały gniazda
(``net::ERR_NO_BUFFER_SPACE``, #778), więc Atrapa odpowiada na kolejne żądania tym samym połączeniem, a koniec bloku
zamyka połączenia, które zostały otwarte, żeby po nim nic pod jej adresem nie odpowiadało.

Decyzje serwera (sesja i jej wygaśnięcie, odmowy „Załaduj do zlecenia”, nadpisanie wyceny Wyceną Emmetta, zapis daty
wykonania i ilości) model ``tools/lib/model_efenix.py`` podejmuje dla każdego okna, więc ich macierz biegnie na jego
interfejsie ``SerwerEfenix``, bez HTTP i przeglądarki.

Kontrakt okien: każdy wiersz ``_ROWS`` to stan efenix i działania okna Wyceny (``efenix_pricing.Efenix``). Okno w procesie
(``tests/fixtures/okno_w_procesie.py``) daje na nich przebiegi z pliku ``tests/expected/kontrakt_okna_efenix.txt``
(obserwacje okna, Zatrzymanie z częścią strony, przyczyną i ``sent``, stan efenix i liczby działań), a okno przeglądarki
na Atrapie efenix w Chromium daje na każdym wierszu ten sam przebieg. Wiersze powstają z ``Action`` (wylogowanie przed
działaniem), ``EmmettRefusal``, ``ProposalFailure``, granic kalendarza i reguł strony (``refuse_dates``, ilość 0, pozycja
bez pola Ilość, ``without`` po dacie i po Wycenie Emmetta).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
import enum
from functools import partial
from http.client import HTTPConnection
from pathlib import Path
import socket
import threading
from typing import Any
from urllib.parse import urlparse

from model_efenix import (
    CATALOG,
    PRICES,
    TODAY,
    Action,
    EfenixOrder,
    EmmettRefusal,
    NoSession,
    ProposalFailure,
    Saved,
    SerwerEfenix,
    StanEfenix,
    earliest_execution_date,
)
from playwright.sync_api import Browser
import pytest

from rozliczenia import efenix_browser
from rozliczenia.efenix_checks import ListedOrder
from rozliczenia.efenix_pricing import Efenix, EmmettLoad, OrderPricing, WindowStop
from tests.fixtures.atrapa_efenix import (
    FILL_EMMETT,
    LIST_PAGE,
    LIST_SCRIPT,
    LOAD_EMMETT,
    LOGIN_PAGE,
    LOGOUT,
    ORDER_PAGE,
    SAVE_QUANTITY,
    SEARCH,
    SET_DATE,
    AtrapaOrder,
    atrapa_efenix,
)
from tests.fixtures.expect import assert_expected
from tests.fixtures.okno_w_procesie import okno
from tests.fixtures.potomne import wait_for
from tests.fixtures.przegladarka import chromium, page_of

ROOT = Path(__file__).resolve().parents[1]
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
    Action.DATE: lambda serwer: serwer.set_date("901", "2026-09-09"),
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
    """Każde inne działanie przed nim przechodzi, także ponad tę liczbę, a po ponownym zalogowaniu sesja już nie wygasa."""

    stan = StanEfenix([_order()], expire_after=(action, 1))

    before = [isinstance(_ACTS[each](stan.serwer), NoSession) for each in Action for _ in range(1 if each is action else 2)]
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

    assert (stan.serwer.set_date("901", "2026-09-09"), stan.serwer.date_of("901")) == (answer, saved)


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


@pytest.mark.parametrize(
    ("logged_in", "refuse_dates", "order_id", "answer"),
    [
        pytest.param(False, False, "901", (302, ""), id="bez-sesji"),
        pytest.param(True, True, "901", (200, "Nie zapisano daty."), id="serwer-odmawia-dat"),
        pytest.param(True, False, "999", (404, "<p>Nie ma takiego zlecenia.</p>"), id="nieznane-zlecenie"),
    ],
)
def test_zapis_daty_bez_sesji_przy_odmowie_dat_albo_nieznanego_zlecenia_dostaje_odpowiedz_bez_czytania_dnia(
    logged_in: bool, refuse_dates: bool, order_id: str, answer: tuple[int, str]
) -> None:
    """Pusty dzień: serwer odpowiada na sesję, zlecenie i ``refuse_dates``, zanim przeczyta dzień."""

    with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")], refuse_dates=refuse_dates) as atrapa:
        if not logged_in:
            atrapa.expire_session()
        connection = _connection(atrapa.url)
        connection.request("POST", f"/{SET_DATE}", body=f"id={order_id}&date=", headers=_FORM)
        response = connection.getresponse()
        got = (response.status, response.read().decode("utf-8"))
        connection.close()

    assert got == answer


def test_dzialania_ktorych_wygasniecie_sesji_nie_liczy_bez_sesji_dostaja_brak_sesji_i_sie_nie_licza() -> None:
    """Szukanie, które lista wysyła sama, i odczyt daty wykonania."""

    stan = StanEfenix([_order()])
    stan.expire_session()

    answers = (stan.serwer.search("9301", own=False), stan.serwer.date_of("901"))

    assert (answers, stan.count(Action.SEARCH)) == ((NoSession.NO_SESSION, NoSession.NO_SESSION), 0)


def test_szukanie_znajduje_kazde_zlecenie_ktorego_numer_zawiera_szukany_numer() -> None:
    stan = StanEfenix([_order(), replace(_order(), order_id="902", number="19301"), replace(_order(), order_id="903", number="9302")])

    found = stan.serwer.search("9301")

    assert (found if isinstance(found, NoSession) else [order.order_id for order in found]) == ["901", "902"]


def test_model_zmienia_kopie_zlecen_testu_i_oddaje_kopie_stanu() -> None:
    """Zlecenia testu zostają bez zmian po działaniu okna, a zmiana zlecenia ze ``state`` nie zmienia stanu efenix."""

    order = _order()
    stan = StanEfenix([order])

    stan.serwer.load_emmett("901")
    [copied], _ = stan.state()
    copied.quantities["005"] = 7

    assert (order, stan.state()[0][0].quantities) == (_order(), {"012": 1})


def test_zmiana_statusu_zmienia_status_zlecenia_w_efenix() -> None:
    stan = StanEfenix([_order()])

    answer = stan.serwer.change_status("901", "Do akceptacji")

    [order], _ = stan.state()
    assert (answer, order.status) == (None, "Do akceptacji")


# Kontrakt okien: okno w procesie i okno przeglądarki na Atrapie efenix na tym samym stanie efenix.

_DAY = date(2026, 9, 9)
_EARLIEST = earliest_execution_date(TODAY)
# Kody pozycji z polem Ilość na pełnej stronie zlecenia.
_QUANTITY_CODES = tuple(position.code for position in CATALOG if position.kind == "ILOSC")
# Ścieżka żądania Atrapy efenix, które jest działaniem serwera (``expire_after`` Atrapy bierze ścieżkę).
_PATHS = {
    Action.SEARCH: SEARCH,
    Action.OPEN: ORDER_PAGE,
    Action.DATE: SET_DATE,
    Action.PROPOSAL: FILL_EMMETT,
    Action.EMMETT: LOAD_EMMETT,
    Action.QUANTITY: SAVE_QUANTITY,
}
# Odmowy „Załaduj do zlecenia” przekierowaniem albo statusem błędu: okno nie czeka po nich na przeładowanie strony.
_NOT_RELOADED = frozenset({EmmettRefusal.FORBIDDEN, EmmettRefusal.SERVER_ERROR, EmmettRefusal.ELSEWHERE, EmmettRefusal.LOGGED_OUT})


@dataclass(frozen=True)
class _Search:
    number: str = "9301"


@dataclass(frozen=True)
class _Open:
    """Otwarcie pierwszego wiersza ostatniego szukania."""


@dataclass(frozen=True)
class _SetDate:
    day: date = _DAY


@dataclass(frozen=True)
class _Emmett:
    pass


@dataclass(frozen=True)
class _Quantity:
    code: str
    quantity: int


_Step = _Search | _Open | _SetDate | _Emmett | _Quantity


@dataclass(frozen=True)
class _Row:
    """Wiersz kontraktu: zlecenia efenix, działania okna po kolei i stan efenix (``expire_after``, ``refuse_dates``)."""

    name: str
    orders: tuple[AtrapaOrder, ...]
    steps: tuple[_Step, ...]
    expire_after: tuple[Action, int] | None = None
    refuse_dates: bool = False

    @property
    def reload_awaited(self) -> bool:
        """Okno czeka na przeładowanie strony po „Załaduj do zlecenia”, a nie kończy działania przed nim (odmowa
        przekierowaniem albo statusem błędu, bez sesji przy propozycji albo „Załaduj”)."""

        expired = self.expire_after is not None and self.expire_after[0] in (Action.PROPOSAL, Action.EMMETT)
        return not (expired or any(order.emmett_refusal in _NOT_RELOADED for order in self.orders))

    @property
    def resent(self) -> frozenset[Action]:
        """Działania, których żądanie Atrapa zrywa bez odpowiedzi (``ProposalFailure.CUT``): Chromium wysyła je drugi raz,
        gdy zerwane połączenie było już wcześniej użyte (na Macu 8 z 8 przebiegów, 7.11.2026), a nowym połączeniem nie,
        więc serwer wykonuje je raz albo dwa razy."""

        return frozenset({Action.PROPOSAL}) if any(order.emmett_proposal_failure is ProposalFailure.CUT for order in self.orders) else frozenset()


def _new(**changes: Any) -> AtrapaOrder:
    """Zlecenie bez wyceny z propozycją Emmetta 012: 1 i 019: 2."""

    return replace(AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1", emmett={"012": 1, "019": 2}), **changes)


_FULL = (_Search(), _Open(), _SetDate(), _Open(), _Emmett(), _Quantity("012", 3))
_DATED_EMMETT = (_Search(), _Open(), _Emmett(), _Quantity("012", 3))
_DATING = (_Search(), _Open(), _SetDate(), _Open())
_ROWS = (
    *(
        _Row(f"wylogowanie-{action.name.lower()}-{after}", (_new(),), _FULL, expire_after=(action, after))
        for action, after in [
            (Action.SEARCH, 0),
            (Action.OPEN, 0),
            (Action.DATE, 0),
            (Action.OPEN, 1),
            (Action.PROPOSAL, 0),
            (Action.EMMETT, 0),
            (Action.OPEN, 2),
            (Action.QUANTITY, 0),
        ]
    ),
    _Row("zaladuj-bez-odmowy", (_new(execution_date=_DAY),), _DATED_EMMETT),
    *(
        _Row(f"zaladuj-odmowa-{refusal.name.lower()}", (_new(execution_date=_DAY, emmett_refusal=refusal),), _DATED_EMMETT)
        for refusal in EmmettRefusal
    ),
    *(
        _Row(f"propozycja-{failure.name.lower()}", (_new(execution_date=_DAY, emmett_proposal_failure=failure),), _DATED_EMMETT)
        for failure in ProposalFailure
    ),
    _Row("propozycja-pusta", (_new(execution_date=_DAY, emmett={}),), _DATED_EMMETT[:3]),
    _Row("zaladuj-na-wycene", (_new(execution_date=_DAY, quantities={"019": 2}),), _DATED_EMMETT[:3]),
    *(
        _Row(f"kalendarz-{name}", (_new(),), (_Search(), _Open(), _SetDate(day), _Open()))
        for name, day in [
            ("przed-najwczesniejszym", _EARLIEST - timedelta(days=1)),
            ("najwczesniejszy", _EARLIEST),
            ("dzis", TODAY),
            ("jutro", TODAY + timedelta(days=1)),
        ]
    ),
    _Row("serwer-odmawia-dat", (_new(),), _DATING, refuse_dates=True),
    _Row("bez-pozycji-po-dacie", (_new(without=frozenset({"012"}), after_date=True),), _DATING),
    _Row("bez-pozycji-po-emmecie", (_new(execution_date=_DAY, without=frozenset({"012"}), after_emmett=True),), _DATED_EMMETT),
    _Row("ilosc-poza-strona", (_new(execution_date=_DAY, without=frozenset({"012"})),), (_Search(), _Open(), _Quantity("012", 1))),
    _Row("ilosc-ceny-wpisywanej", (_new(execution_date=_DAY),), (_Search(), _Open(), _Quantity("045", 5))),
    _Row("ilosc-zero", (_new(execution_date=_DAY, quantities={"019": 2}),), (_Search(), _Open(), _Quantity("019", 0))),
    _Row("szukanie-bez-wynikow", (_new(),), (_Search("9399"),)),
    _Row("szukanie-zawiera", (_new(), _new(order_id="902", number="19301", realizator="beata.testowa")), (_Search(), _Open())),
)


def _text(value: object) -> str:
    """Wartość obserwacji bez treści strony: element wyliczenia z nazwą typu, dataklasa z polami."""

    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if is_dataclass(value) and not isinstance(value, type):
        return f"{type(value).__name__}({', '.join(_text(getattr(value, field.name)) for field in fields(value))})"
    return str(value)


def _quantities(quantities: dict[str, int] | object) -> str:
    assert isinstance(quantities, dict)
    return " ".join(f"{code}={quantity}" for code, quantity in sorted(quantities.items()) if quantity) or "-"


def _page(page: OrderPricing) -> str:
    absent = [code for code in _QUANTITY_CODES if code not in page.quantities]
    return (
        f"data {page.execution_date or '-'}, kwota {page.amount}, ilości {_quantities(dict(page.quantities))}"
        f", bez pola Ilość {' '.join(absent) or '-'}"
    )


def _listed(order: ListedOrder) -> str:
    return f"{order.order_id} {order.number} {order.status} {order.realizator} {order.address}"


def _observed(open_window: Callable[[], AbstractContextManager[Efenix]], steps: Sequence[_Step]) -> list[str]:
    """Obserwacja każdego działania okna po kolei; Zatrzymanie z wyjątku okna kończy przebieg."""

    lines: list[str] = []
    found: Sequence[ListedOrder] = ()
    try:
        with open_window() as efenix:
            for step in steps:
                match step:
                    case _Search(number):
                        found = efenix.search(number)
                        lines.append(f"szukanie {number}: {'; '.join(_listed(order) for order in found) or 'brak wyników'}")
                    case _Open():
                        lines.append(f"otwarcie {found[0].order_id}: {_page(efenix.open_order(found[0]))}")
                    case _SetDate(day):
                        accepted = efenix.set_execution_date(day)
                        lines.append(f"data {day}: {'potwierdzona' if accepted else 'kalendarz zamienił dzień'}")
                    case _Emmett():
                        loads: list[EmmettLoad] = []

                        def recorded(load: EmmettLoad) -> OrderPricing:
                            loads.append(load)
                            return load.page

                        efenix.load_emmett(recorded)
                        [load] = loads
                        lines.append(f"Emmett: okno {_text(load.proposal)}, strona {_page(load.page)}")
                    case _Quantity(code, quantity):
                        lines.append(f"ilość {code}={quantity}: kwota {efenix.enter_quantity(code, quantity)}")
    except WindowStop as stop:
        lines.append(f"Zatrzymanie: {type(stop).__name__} {_text(stop.part)} {_text(stop.cause)}, wysłane {stop.sent}")
    return lines


def _ended(stan: StanEfenix[AtrapaOrder], resent: frozenset[Action]) -> list[str]:
    """Stan efenix po przebiegu i liczba każdego działania okna; działanie z ``resent`` co najmniej raz."""

    orders, logged_in = stan.state()
    return [
        *(
            f"stan {order.order_id}: data {order.execution_date or '-'}, ilości {_quantities(order.quantities)}, status"
            f" {order.status}, Wycena Emmetta {order.emmett_loads} (na wycenę {order.emmett_over_pricing})"
            for order in orders
        ),
        f"sesja {'trwa' if logged_in else 'wygasła'}",
        "działania "
        + " ".join(f"{action.name}≥1" if action in resent and stan.count(action) >= 1 else f"{action.name}={stan.count(action)}" for action in Action),
    ]


def _in_process(row: _Row) -> list[str]:
    stan = StanEfenix(row.orders, refuse_dates=row.refuse_dates, expire_after=row.expire_after)
    return _observed(partial(okno, stan, nullcontext), row.steps) + _ended(stan, row.resent)


def test_okno_w_procesie_daje_przebiegi_z_pliku_kontraktu() -> None:
    contract = "".join(f"wiersz {row.name}\n" + "".join(f"  {line}\n" for line in _in_process(row)) for row in _ROWS)

    assert_expected(contract, ROOT / "tests" / "expected" / "kontrakt_okna_efenix.txt")


def test_kontrakt_okien_ma_wiersz_dla_kazdego_dzialania_odmowy_zaladuj_i_padniecia_propozycji() -> None:
    """Każde działanie okna (bez zmiany statusu, której okno nie ma) z wylogowaniem przed nim, każda odmowa „Załaduj do
    zlecenia” i każde padnięcie propozycji Emmetta."""

    expired = {row.expire_after[0] for row in _ROWS if row.expire_after is not None}
    refusals = {order.emmett_refusal for row in _ROWS for order in row.orders}
    failures = {order.emmett_proposal_failure for row in _ROWS for order in row.orders}

    assert (expired, refusals >= set(EmmettRefusal), failures >= set(ProposalFailure)) == (set(Action) - {Action.STATUS}, True, True)


def test_okno_w_procesie_odrzuca_zlecenie_z_pokretlem_strony_atrapy() -> None:
    stan = StanEfenix([_new(changed=None, cut=True)])

    with okno(stan, nullcontext) as efenix, pytest.raises(AssertionError, match="cut"):
        efenix.open_order(ListedOrder("9301", "Do wyceny", "adrian.testowy", "Miasto ul.Testowa 1", "901"))


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with chromium() as launched:
        yield launched


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row.name)
def test_okno_przegladarki_na_atrapie_daje_ten_sam_przebieg_co_okno_w_procesie(row: _Row, browser: Browser) -> None:
    """Przy odmowie, po której okno nie czeka na przeładowanie strony, skrypt strony przeładowuje ją dopiero po bloku
    (``emmett_reload_ms``), więc liczby działań kończą się na ostatniej odpowiedzi, na którą czekało okno."""

    expire_after = None if row.expire_after is None else (_PATHS[row.expire_after[0]], row.expire_after[1])
    atrapa_of_row = partial(atrapa_efenix, row.orders, expire_after=expire_after, refuse_dates=row.refuse_dates)
    with atrapa_of_row() if row.reload_awaited else atrapa_of_row(emmett_reload_ms=600_000) as atrapa, page_of(browser) as page:
        observed = _observed(partial(efenix_browser.window, page, atrapa.url, timeout_ms=10_000), row.steps) + _ended(atrapa.stan, row.resent)

    assert observed == _in_process(row)
