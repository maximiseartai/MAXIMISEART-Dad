"""Okno w procesie: okno efenix Wyceny (``efenix_window.Efenix``) wprost na modelu efenix, bez HTTP i przeglądarki.

``okno(stan, login)`` daje okno na stanie ``StanEfenix`` z ``tools/lib/atrapy/model_efenix.py``, tym samym, który pod Atrapą
efenix trzyma zlecenia i sesję (decyzja Maksa 6.11.2026: to test na Atrapie, ADR 0024). Okno woła działania
``SerwerEfenix`` i tłumaczy ich wynik na to, co z odpowiedzi Atrapy efenix robi okno przeglądarki
(``efenix_browser.BrowserEfenix``): wiersze listy (``_listed``), stronę zlecenia, wyjątki okna z częścią strony i przyczyną oraz
``WindowStop.sent``, gdy działanie przed wyjątkiem kliknęło już przycisk zmiany zlecenia. Nie udaje sieci,
przeglądarki, budowy strony ani czasu, więc zlecenie z pokrętłem strony Atrapy (pole ``AtrapaOrder`` spoza
``EfenixOrder`` z wartością inną niż domyślna) odrzuca ``AssertionError`` (fail closed).

Że oba okna dają na tym samym stanie te same obserwacje, ten sam stan i te same liczby działań, sprawdza kontrakt w
``tests/test_atrapa_efenix.py`` (plik expect okna w procesie i ten sam przebieg okna przeglądarki na Atrapie).
Z ``rozliczenia`` okno bierze tylko typy seamu (``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import dataclasses
from datetime import date
from decimal import Decimal
import functools
import re
from typing import Concatenate, Generic, ParamSpec, TypeVar

from atrapy.model_efenix import (
    EfenixOrder,
    EmmettRefusal,
    NoOrder,
    NoSession,
    Saved,
    StanEfenix,
    amount_of,
    calendar_day,
)

from rozliczenia.efenix_window import (
    Efenix,
    EmmettLoad,
    ForwardRefusal,
    HttpStatus,
    ListedOrder,
    Login,
    LoginSign,
    OrderPricing,
    OtherShape,
    PagePart,
    Proposal,
    SentChanges,
    Shape,
    WindowStop,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")
_O = TypeVar("_O", bound=EfenixOrder)
# Pola zlecenia, które zna model; każde inne pole zlecenia to pokrętło strony Atrapy efenix.
_MODEL_FIELDS = frozenset(field.name for field in dataclasses.fields(EfenixOrder))
# Status, którym Atrapa efenix odpowiada na działanie przy zleceniu, którego efenix nie zna.
_NO_ORDER = HttpStatus(404)
# Status, który „Tak” po przycisku Przekazania do akceptacji wysyła na stronie zlecenia Atrapy efenix.
_FORWARDED = "Do akceptacji"
# Login realizatora, który okno przeglądarki czyta z ``(login)`` w komórce Wykonawca: bez odstępów i nawiasów.
_LOGIN = re.compile(r"[^()\s]+")


def _action(action: Callable[Concatenate[OknoWProcesie[_O], _P], _R]) -> Callable[Concatenate[OknoWProcesie[_O], _P], _R]:
    """Działanie okna: wyjątek okna z niego ma ``WindowStop.sent`` (``SentChanges``), jak ``efenix_browser._action``."""

    @functools.wraps(action)
    def guarded(okno: OknoWProcesie[_O], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with okno._sent.action():
            return action(okno, *args, **kwargs)

    return guarded


class OknoWProcesie(Generic[_O]):
    """Okno efenix na stanie ``stan``; implementuje ``efenix_window.Efenix``."""

    def __init__(self, stan: StanEfenix[_O]) -> None:
        self._stan = stan
        self._sent = SentChanges()
        # Otwarte zlecenie i kody pozycji z polem Ilość na jego ostatnio przeczytanej stronie; ``None``: okno stoi na
        # liście zleceń.
        self._opened: str | None = None
        self._positions: frozenset[str] = frozenset()
        # Tekst odmowy Przekazania do akceptacji na ostatnio przeczytanej stronie, którą skrypt strony pokaże po przycisku
        # Przekazania, bez działania serwera.
        self._refusal: str | None = None

    def open_list(self) -> None:
        """Lista zleceń: bez sesji efenix przekierowuje ją na stronę logowania."""

        if not self._stan.logged_in:
            raise WindowStop.of(PagePart.LIST, LoginSign.PAGE)
        self._opened = None

    @_action
    def search(self, number: str) -> Sequence[ListedOrder]:
        if self._opened is not None:
            self.open_list()
        found = self._stan.serwer.search(number)
        if isinstance(found, NoSession):
            raise WindowStop.of(PagePart.RESULTS, LoginSign.SESSION_WARNING)
        return tuple(_listed(order) for order in found)

    @_action
    def open_order(self, order: ListedOrder) -> OrderPricing:
        self._opened = order.order_id
        return self._page()

    @_action
    def set_execution_date(self, day: date) -> bool:
        """``False`` bez działania, gdy kalendarz efenix zamienia ``day`` na inny dzień (``calendar_day``)."""

        if calendar_day(self._stan.today, day) != day:
            return False
        self._sent.send()
        saved = self._stan.serwer.set_date(self._order_id(), day.isoformat())
        if isinstance(saved, NoSession):
            raise WindowStop.of(PagePart.DATE, LoginSign.REDIRECT)
        if isinstance(saved, NoOrder):
            raise WindowStop.of(PagePart.DATE, _NO_ORDER)
        return True

    @_action
    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        """Propozycja Emmetta, „Załaduj do zlecenia” i strona od nowa, oddane werdyktowi ``verdict``.

        Okno Emmetta jest puste (``LOST``) po propozycji, która padła albo trafiła na nieznane zlecenie (404), a bez sesji
        pokazuje stronę logowania, na którą efenix przekierował propozycję (``SHOWN``). Odmowa przekierowaniem albo
        statusem błędu kończy działanie bez czytania strony; odmowa ``NOK`` i ``OTHER`` przychodzi ze statusem 2xx, więc
        okno czyta stronę po przeładowaniu jak po załadowaniu.
        """

        order_id = self._order_id()
        proposed = self._stan.serwer.proposal(order_id)
        if isinstance(proposed, NoSession):
            shown = Proposal.SHOWN
        elif isinstance(proposed, NoOrder) or proposed.emmett_proposal_failure is not None:
            shown = Proposal.LOST
        else:
            shown = Proposal.SHOWN if proposed.emmett else Proposal.NOTHING
        self._sent.send()
        refusal = self._stan.serwer.load_emmett(order_id)
        match refusal:
            case NoSession() | EmmettRefusal.LOGGED_OUT:
                raise WindowStop.of(PagePart.EMMETT, LoginSign.REDIRECT)
            case NoOrder():
                raise WindowStop.of(PagePart.EMMETT, _NO_ORDER)
            case EmmettRefusal.FORBIDDEN:
                raise WindowStop.of(PagePart.EMMETT, HttpStatus(403))
            case EmmettRefusal.SERVER_ERROR:
                raise WindowStop.of(PagePart.EMMETT, HttpStatus(500))
            case EmmettRefusal.ELSEWHERE:
                raise WindowStop.of(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))
            case None | EmmettRefusal.NOK | EmmettRefusal.OTHER:
                return verdict(EmmettLoad(shown, self._page()))

    @_action
    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Kwota końcowa po zapisie; ilość, której efenix nie przyjął (kod spoza katalogu), to odpowiedź ``nok``, którą
        okno czyta jak wygasłą sesję."""

        if position not in self._positions:
            raise WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.UNKNOWN_POSITION, position))
        self._sent.send()
        saved = self._stan.serwer.save_quantity(self._order_id(), position, quantity)
        if isinstance(saved, NoOrder):
            raise WindowStop.of(PagePart.QUANTITY, _NO_ORDER)
        if not isinstance(saved, Saved):
            raise WindowStop.of(PagePart.QUANTITY, LoginSign.REFUSED)
        return saved.amount

    @_action
    def forward_to_accept(self) -> ForwardRefusal | None:
        """Przekazanie do akceptacji otwartego zlecenia: zmiana statusu na „Do akceptacji” i strona zlecenia od nowa, jak
        przeładowanie, na które czeka okno przeglądarki; bez sesji przekierowanie na stronę logowania. Strona z odmową
        Przekazania (``forward_refusal``) daje ją bez działania serwera, jak okno informacji skryptu strony."""

        if self._refusal is not None:
            return ForwardRefusal.of(self._refusal)
        self._sent.send()
        order_id = self._order_id()
        changed = self._stan.serwer.change_status(order_id, _FORWARDED)
        if isinstance(changed, NoSession):
            raise WindowStop.of(PagePart.FORWARD, LoginSign.REDIRECT)
        if isinstance(changed, NoOrder):
            raise WindowStop.of(PagePart.FORWARD, _NO_ORDER)
        if isinstance(self._stan.serwer.page(order_id), NoSession):
            raise WindowStop.of(PagePart.FORWARD, LoginSign.PAGE)
        return None

    def _order_id(self) -> str:
        assert self._opened is not None, "działanie przy zleceniu po open_order"
        return self._opened

    def _page(self) -> OrderPricing:
        """Strona otwartego zlecenia: data wykonania, kwota końcowa i ilość w każdym polu Ilość, które ma strona."""

        order = self._stan.serwer.page(self._order_id())
        if isinstance(order, NoSession):
            raise WindowStop.of(PagePart.ORDER, LoginSign.PAGE)
        if isinstance(order, NoOrder):
            raise WindowStop.of(PagePart.ORDER, _NO_ORDER)
        knobs = {
            field.name
            for field in dataclasses.fields(order)
            if field.name not in _MODEL_FIELDS and getattr(order, field.name) != field.default
        }
        assert not knobs, f"okno w procesie nie udaje budowy strony Atrapy efenix ({', '.join(sorted(knobs))}): test w przeglądarce"
        quantities = {position.code: order.quantities.get(position.code, 0) for position in order.positions if position.kind == "ILOSC"}
        self._positions = frozenset(quantities)
        self._refusal = order.forward_refusal
        return OrderPricing(order.execution_date, amount_of(order.quantities, self._stan.prices), quantities)


def _listed(order: EfenixOrder) -> ListedOrder:
    """Wiersz listy tak, jak okno przeglądarki czyta go z tabeli wyników (``efenix_page.listed``): tekst komórki bez
    odstępów na brzegach i z jednym odstępem w miejscu każdego ciągu odstępów, a realizator bez loginu (pusty, z odstępem
    albo nawiasem) to ``None``."""

    return ListedOrder(
        _text(order.number),
        _text(order.status),
        order.realizator if _LOGIN.fullmatch(order.realizator) else None,
        _text(order.address),
        order.order_id,
    )


def _text(cell: str) -> str:
    return " ".join(cell.split())


@contextmanager
def okno(stan: StanEfenix[_O], _login: Login) -> Iterator[Efenix]:
    """Okno efenix z otwartą listą zleceń na stanie ``stan`` (``efenix_window.OpenEfenix`` przez
    ``functools.partial(okno, stan)``); bez sesji ``LoggedOut`` listy, bo okno, jak ``efenix_browser.chromium``, na
    logowanie taty nie czeka."""

    window = OknoWProcesie(stan)
    window.open_list()
    yield window
