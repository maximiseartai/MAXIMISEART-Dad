"""Okno efenix w przeglądarce: jedyny moduł, który zna Playwright i budowę stron efenix.

Na zewnątrz daje tylko typy domeny (``efenix_pricing.Efenix``, ``ListedOrder``, ``OrderPricing``) i zna tylko działania
z listy dozwolonych: szukanie po ``Numer`` na liście zleceń, otwarcie strony zlecenia, ustawienie daty wykonania,
przycisk Emmetta z „Załaduj do zlecenia” i pola „Ilość”. Przycisków Przekazania do akceptacji, anulowania i zmiany
statusu nie zna. Każdy przycisk okna dialogowego klika w jego oknie (``#dialog_… .btn-ok``), bo strona zlecenia ma
``.btn-ok`` w każdym oknie, także w oknie zmiany statusu. Szuka tak jak tata: wpisuje numer w pole ``#field_numer`` i naciska Enter, a skrypt strony wysyła ``action_fill_orders.php`` i wkłada
odpowiedź do ``#wyniki``. Tabelę wyników okno czyta z odpowiedzi na swoje szukanie (tej z jego numerem w polu ``numer``),
tę samą, którą skrypt wkłada do ``#wyniki``, bo lista po wczytaniu sama szuka ostatniego numeru z poprzedniej wizyty, a
jej odpowiedź trafia do ``#wyniki`` w dowolnej chwili. Kolumny tabeli rozpoznaje po nagłówkach (``Numer dokumentu``,
``Status``, ``Wykonawca``, ``Dane adresowe``), tekst komórki bez jej ``<small>`` (identyfikator Fenix, województwo),
login realizatora z ``small.text-default`` komórki Wykonawca (obok niego w ``<small>`` stoi data), a stronę zlecenia
otwiera linkiem ``page_order_edit.php?id=`` z wiersza. Przekierowanie strony albo szukania na ``page_login.php`` to
``LoggedOut``. Lista zleceń, której okno nie otworzyło przy starcie (adres nie odpowiada), to ``EfenixUnreachable``.
Każde inne działanie, którego okno nie dokończyło, to ``UnexpectedPage`` z częścią strony: strona bez oczekiwanej
budowy, element obecny, ale niewidoczny, i każdy błąd Playwrighta w działaniu (czas czekania na stronę, odpowiedź albo
element, który minął, otwarcie strony, które się nie udało, treść odpowiedzi, której nie da się przeczytać). Każdy z
tych wyjątków niesie przyczynę techniczną z zamkniętej listy (``efenix_pricing.WindowCause``): element, który nie
występuje dokładnie raz, z jego selektorem i liczbą, budowę strony, której okno nie zna (``Shape``), a przy błędzie
Playwrighta typ jego wyjątku i działanie okna, w którym wystąpił (``Operation``), bez treści wyjątku i strony. Czy to
zerwane połączenie, wolny czy zmieniony efenix, okno nie zgaduje: Maks ustala to z przyczyny w Logach. Na odpowiedź efenix
okno czeka do jej końca, z całą treścią, a nie tylko do nagłówków, bo na treść, którą sieć wstrzymała w połowie,
czekałoby bez końca. Działanie w zamkniętej karcie albo oknie, także zamkniętym w trakcie działania, to
``WindowClosed``, cokolwiek zgłosił wtedy Playwright. Przeglądarkę daje rozmówca: stronę (``window``), Chromium
Playwrighta (``chromium``) albo widoczne okno zainstalowanego Google Chrome w trwałym profilu narzędzia (``chrome``),
które nie startuje (``BrowserNotStarted``), gdy Chrome nie ma albo jego profil trzyma inne okno.

Okno z ``Login`` od silnika (``chrome`` zawsze, ``window`` na życzenie) na stronie logowania czeka, aż tata się zaloguje:
co ``LOGIN_POLL_MS`` sprawdza, czy strona przeszła na inną niż logowanie, albo pyta efenix o listę zleceń w tej samej
sesji przeglądarki bez przekierowań, nie ruszając strony z formularzem, w którym tata pisze. Gdy lista odpowiada, otwiera ją
i proces rusza; brak logowania przez ``LOGIN_TIMEOUT_MS`` to ``LoggedOut``, a karta, okno albo przeglądarka zamknięte
w tym czasie to ``WindowClosed`` najpóźniej po ``LOGIN_POLL_MS``.

Stronę zlecenia czyta tak, jak widzi ją tata: datę wykonania z ``#data_install`` (RRRR-MM-DD albo pusta), kwotę końcową z
``#cena_all2`` i ilość każdej pozycji z pola ``input.wycena-ilosc`` o id ``INDEKS_NNN_…`` (kod pozycji to ``NNN``).
Datę ustawia przyciskiem kalendarza ``#button-calendar`` i kalendarzem pickadate pola ``#field_data_instalacji`` okna
``#dialog_select_date``: wybiera dzień przez ``picker.set('select', …)`` kalendarza strony, więc biegnie sprawdzenie
zakresu efenix, które dzień spoza zakresu zamienia na dzisiejszy. Gdy w polu nie ma potem dokładnie wybranego dnia, okno
zamyka kalendarz bez „Potwierdź”; inaczej klika „Potwierdź” i czeka na odpowiedź ``action_set_date_of_instalation.php``.
Tekstowi ``#data_install`` po niej nie wierzy, bo skrypt efenix wpisuje go przy każdej odpowiedzi. Wycenę Emmetta ładuje przyciskiem
``#button_emmett`` i „Załaduj do zlecenia” w ``#dialog_emmett``: czeka na odpowiedź ``action_load_emmett.php`` i na
przeładowanie strony, które robi skrypt efenix, i czyta stronę od nowa. Ilość wpisuje w polu i naciska Enter, a skrypt
strony zapisuje ją przez ``action_save_index.php``: kwotą końcową jest ``price_all`` z tej odpowiedzi, a ``#cena_all2``,
które się do niej nie odświeży, to ``UnexpectedPage``. Odpowiedź ``result: nok`` to wygasła sesja (``LoggedOut``).

Tabelę wyników i stronę zlecenia czytają ``read_results`` i ``read_order``, których używa też narzędzie zgodności
Atrapy efenix (``tools/zgodnosc_efenix.py``) na HTML z serwera efenix. Resztę budowy, której okno używa, moduł podaje
jako dane dla tego narzędzia: elementy listy i strony zlecenia (``LIST_ELEMENTS``, ``ORDER_ELEMENTS``) i nazwy, które
muszą być w skryptach tych stron, bo okno polega na ich działaniu (``LIST_SCRIPT_USES``, ``ORDER_SCRIPT_USES``).
"""

from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Concatenate, Final, ParamSpec, TypedDict, TypeVar
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, Request, Response, sync_playwright

from . import TOOL_ROOT
from .call_trace import exception_type
from .efenix_pricing import (
    BrowserFailure,
    BrowserNotStarted,
    Closed,
    EfenixUnreachable,
    ElementCount,
    HttpStatus,
    ListedOrder,
    LoggedOut,
    Login,
    LoginSign,
    Operation,
    OrderPricing,
    OtherShape,
    PagePart,
    Shape,
    UnexpectedPage,
    WindowClosed,
)

__all__ = [
    "AMOUNT",
    "EXECUTION_DATE",
    "HEADERS",
    "LIST_ELEMENTS",
    "LIST_SCRIPT_USES",
    "LOGIN_PAGE",
    "LOGIN_TIMEOUT_MS",
    "ORDER_ELEMENTS",
    "ORDER_PAGE",
    "ORDER_SCRIPT_USES",
    "PROFILE_DIRECTORY",
    "QUANTITY",
    "SEARCH",
    "BrowserEfenix",
    "PageElement",
    "ScriptUse",
    "chrome",
    "chromium",
    "default_profile",
    "read_order",
    "read_results",
    "window",
]

PROFILE_DIRECTORY: Final = "przegladarka-efenix"
"""Folder profilu przeglądarki narzędzia w katalogu narzędzia: na dysku lokalnym taty, poza OneDrive, w ``.gitignore``."""

_NUMBER_FIELD: Final = "#field_numer"
_NUMBER_PARAM: Final = "numer"
LOGIN_PAGE: Final = "page_login.php"
SEARCH: Final = "action_fill_orders.php"
ORDER_PAGE: Final = "page_order_edit.php"
EXECUTION_DATE: Final = "#data_install"
AMOUNT: Final = "#cena_all2"
QUANTITY: Final = "input.wycena-ilosc"
_DATE_BUTTON: Final = "#button-calendar"
_DATE_DIALOG: Final = "#dialog_select_date"
_DATE_FIELD: Final = "#field_data_instalacji"
_SET_DATE: Final = "action_set_date_of_instalation.php"
_EMMETT_BUTTON: Final = "#button_emmett"
_EMMETT_DIALOG: Final = "#dialog_emmett"
_FILL_EMMETT: Final = "action_fill_emmett.php"
_LOAD_EMMETT: Final = "action_load_emmett.php"
_SAVE_QUANTITY: Final = "action_save_index.php"
_PRICE_ALL: Final = "price_all"
_OK: Final = ".btn-ok"
_POSITION: Final = re.compile(r"INDEKS_(\d{3})_\d+")
_AMOUNT_TEXT: Final = re.compile(r"[0-9]+(\.[0-9]+)?")
_QUANTITY_TEXT: Final = re.compile(r"[0-9]*")
HEADERS: Final = {"number": "numer dokumentu", "status": "status", "realizator": "wykonawca", "address": "dane adresowe"}
_LOGIN: Final = re.compile(r"\(([^()\s]+)\)")
_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
TIMEOUT_MS: Final = 30_000
LOGIN_TIMEOUT_MS: Final = 15 * 60_000
"""Tyle okno czeka na logowanie taty, zanim proces zatrzyma się jak po wylogowaniu."""
LOGIN_POLL_MS: Final = 2_000

# Tabela z odpowiedzi szukania przeczytana parserem HTML przeglądarki w ``<template>``, w którym jej skrypty nie biegną.
_READ_RESULTS: Final = """(html) => {
    const template = document.createElement('template');
    template.innerHTML = html;
    const table = template.content.querySelector('table');
    if (!table) return null;
    const text = (element) => element.textContent.replace(/\\s+/g, ' ').trim();
    return {
        headers: [...table.querySelectorAll('thead th')].map(text),
        rows: [...table.querySelectorAll('tbody tr')].map((row) => [...row.querySelectorAll('td')].map((cell) => {
            const plain = cell.cloneNode(true);
            plain.querySelectorAll('small').forEach((small) => small.remove());
            const badge = cell.querySelector('.badge');
            const login = cell.querySelector('small.text-default');
            const link = cell.querySelector('a[href*="page_order_edit.php?id="]');
            return {
                plain: text(plain),
                badge: badge ? text(badge) : null,
                login: login ? text(login) : null,
                link: link ? link.getAttribute('href') : null,
            };
        })),
    };
}"""


# Dzień wybrany kalendarzem pickadate pola, tak jak klik dnia: biegnie ``onSet`` strony, które sprawdza zakres dat.
# Miesiąc pickadate liczy od 0. ``false``, gdy pole nie ma kalendarza.
_PICK_DAY: Final = """(field, [year, month, day]) => {
    const jquery = window.jQuery;
    const picker = typeof jquery === 'function' && typeof jquery(field).pickadate === 'function' ? jquery(field).pickadate('picker') : null;
    if (!picker || typeof picker.set !== 'function') return false;
    picker.set('select', [year, month - 1, day]);
    return true;
}"""
_DISMISS: Final = '[data-dismiss="modal"]'
_LOGIN_FORM: Final = 'form[action*="action_login.php"]'
_SHOWS: Final = "([selector, text]) => document.querySelector(selector)?.textContent.trim() === text"


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _action(
    part: PagePart,
) -> Callable[[Callable[Concatenate[BrowserEfenix, _P], _R]], Callable[Concatenate[BrowserEfenix, _P], _R]]:
    """Działanie okna na części ``part`` strony efenix: każdy błąd Playwrighta w działaniu to ``UnexpectedPage(part)``
    z typem błędu i działaniem przeglądarki, które nazwał ``_doing`` (granica ``_within``), więc żadne czekanie na sieć
    ani czytanie odpowiedzi jej nie omija.

    Każdy wyjątek działania w karcie zamkniętej przed nim albo w jego trakcie to zamknięte okno (``WindowClosed``), a nie
    lista typów: Playwright zgłasza wtedy błąd, a granica mogła go już zamienić na ``UnexpectedPage``.
    """

    def decorate(action: Callable[Concatenate[BrowserEfenix, _P], _R]) -> Callable[Concatenate[BrowserEfenix, _P], _R]:
        @functools.wraps(action)
        def guarded(efenix: BrowserEfenix, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                with _within(part):
                    return action(efenix, *args, **kwargs)
            except Exception as error:
                if efenix.closed and not isinstance(error, WindowClosed):
                    raise WindowClosed(part, Closed.DURING_ACTION) from error
                raise

        return guarded

    return decorate


@dataclass(frozen=True)
class PageElement:
    """Element strony efenix, którego używa okno: jest na stronie dokładnie raz (``many``: co najmniej raz), a ten, który
    okno klika pierwszy (``clicked``), jest widoczny."""

    name: str
    selector: str
    many: bool = False
    clicked: bool = False


@dataclass(frozen=True)
class ScriptUse:
    """Działanie skryptu strony efenix, na którym polega okno, i nazwy (pól, klas, odpowiedzi), które skrypt zawiera."""

    what: str
    names: tuple[str, ...]


# Budowa stron efenix, której okno używa poza odczytem tabeli wyników i strony zlecenia (``read_results``,
# ``read_order``); narzędzie zgodności Atrapy efenix (``tools/zgodnosc_efenix.py``) sprawdza ją na efenix. Przycisku
# kalendarza (``_DATE_BUTTON``) nie ma w ``ORDER_ELEMENTS``: okno klika go tylko przy pustej dacie wykonania, a efenix
# pokazuje go najpewniej tylko wtedy, więc narzędzie nie sprawdza go na pierwszym otwartym zleceniu.
LIST_ELEMENTS: Final = (PageElement("pole Numer", _NUMBER_FIELD),)
ORDER_ELEMENTS: Final = (
    PageElement("okno daty wykonania", _DATE_DIALOG),
    PageElement("pole kalendarza w oknie daty wykonania", f"{_DATE_DIALOG} {_DATE_FIELD}"),
    PageElement("„Potwierdź” w oknie daty wykonania", f"{_DATE_DIALOG} {_OK}"),
    PageElement("zamknięcie okna daty wykonania", f"{_DATE_DIALOG} {_DISMISS}", many=True),
    PageElement("przycisk Emmetta", _EMMETT_BUTTON, clicked=True),
    PageElement("okno Emmetta", _EMMETT_DIALOG),
    PageElement("„Załaduj do zlecenia” w oknie Emmetta", f"{_EMMETT_DIALOG} {_OK}"),
)
LIST_SCRIPT_USES: Final = (
    ScriptUse("Enter w polu Numer wysyła szukanie z polem numer", (_NUMBER_FIELD[1:], SEARCH, f"{_NUMBER_PARAM}:")),
)
ORDER_SCRIPT_USES: Final = (
    ScriptUse("kalendarz pickadate pola daty wykonania sprawdza dzień w onSet", (_DATE_FIELD[1:], "pickadate", "onSet")),
    ScriptUse("„Potwierdź” okna daty wykonania zapisuje datę", (_DATE_DIALOG[1:], _OK[1:], _SET_DATE)),
    ScriptUse(
        "przycisk Emmetta pokazuje propozycję, a „Załaduj do zlecenia” ją ładuje",
        (_EMMETT_BUTTON[1:], _FILL_EMMETT, _EMMETT_DIALOG[1:], _LOAD_EMMETT),
    ),
    ScriptUse(
        "wyjście z pola Ilość zapisuje ilość, a kwotę końcową z odpowiedzi pokazuje na stronie",
        (QUANTITY.partition(".")[2], "blur", _SAVE_QUANTITY, _PRICE_ALL, AMOUNT[1:]),
    ),
)


class _Cell(TypedDict):
    plain: str
    badge: str | None
    login: str | None
    link: str | None


class _Results(TypedDict):
    headers: list[str]
    rows: list[list[_Cell]]


class BrowserEfenix:
    """Okno efenix na stronie ``page`` z listą zleceń pod adresem ``url``; implementuje ``efenix_pricing.Efenix``."""

    def __init__(self, page: Page, url: str, *, timeout_ms: int = TIMEOUT_MS) -> None:
        self._page = page
        self._url = url
        self._timeout_ms = timeout_ms
        self._positions: dict[str, str] = {}
        self._sent_change = False
        self._opened = False

    @property
    def sent_change(self) -> bool:
        """Okno kliknęło już „Potwierdź” daty, „Załaduj do zlecenia” albo Enter w polu „Ilość”."""

        return self._sent_change

    @property
    def closed(self) -> bool:
        """Karta okna jest zamknięta: tata zamknął ją albo całe okno przeglądarki."""

        return self._page.is_closed()

    @_action(PagePart.LIST)
    def open_list(self) -> None:
        """Otwiera listę zleceń; ``EfenixUnreachable``, gdy okno nie otworzyło jeszcze efenix, a adres nie odpowiada."""

        try:
            with _doing(Operation.OPEN):
                self._page.goto(self._url, wait_until="load", timeout=self._timeout_ms)
        except _Failed as failed:
            if not self._opened:
                raise EfenixUnreachable(failed.failure) from failed.__cause__
            raise
        self._opened = True
        self._ensure_logged_in(PagePart.LIST)
        self._only(_NUMBER_FIELD, PagePart.LIST)

    def wait_for_login(
        self, login: Login, *, timeout_ms: int = LOGIN_TIMEOUT_MS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Otwiera listę zleceń, a na stronie logowania czeka w ``login``, aż tata się zaloguje; ``LoggedOut`` po
        ``timeout_ms`` bez logowania, a ``WindowClosed`` najpóźniej ``LOGIN_POLL_MS`` po zamknięciu karty, okna albo
        całej przeglądarki. ``clock`` (sekundy) mierzy czas czekania.

        Zamkniętą kartę rozpoznaje po ``Page.is_closed`` przed każdym sprawdzeniem, bo czekanie Playwrighta na adres karty
        zamkniętej przed nim nie zgłasza jej zamknięcia, tylko kończy się po swoim limicie.
        """

        try:
            self.open_list()
            return
        except LoggedOut:
            pass
        with login():
            deadline = clock() + timeout_ms / 1000
            while True:
                if self._page.is_closed():
                    raise WindowClosed(PagePart.LIST, Closed.DURING_LOGIN)
                if self._session_open():
                    try:
                        self.open_list()
                        return
                    except LoggedOut:
                        pass
                remaining_ms = round((deadline - clock()) * 1000)
                if remaining_ms <= 0:
                    raise LoggedOut(PagePart.LIST, LoginSign.NO_LOGIN)
                # Czekanie kończy się po limicie, a w karcie zamkniętej w jego trakcie błędem; o zamknięciu mówi ``is_closed``.
                with suppress(PlaywrightError):
                    self._page.wait_for_url(lambda url: not _on_login_page(url), timeout=min(LOGIN_POLL_MS, remaining_ms))

    def _session_open(self) -> bool:
        """Lista zleceń odpowiada w sesji okna bez przekierowania na logowanie; pytanie nie zmienia strony okna."""

        try:
            response = self._page.context.request.get(self._url, max_redirects=0, timeout=self._timeout_ms)
        except PlaywrightError:
            return False
        location = urlparse(response.headers.get("location", "")).path
        return response.ok and not location.endswith(LOGIN_PAGE)

    @_action(PagePart.RESULTS)
    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze tabeli wyników po szukaniu ``number`` w polu ``Numer`` listy zleceń."""

        if urlparse(self._page.url).path != urlparse(self._url).path:
            self.open_list()
        field = self._page.locator(_NUMBER_FIELD)
        with _within(PagePart.LIST), _doing(Operation.FILL):
            field.fill(number, timeout=self._timeout_ms)
        answer = self._finished(lambda request: _is_search(request, number), lambda: self._enter(field))
        if _redirected_to_login(answer):
            raise LoggedOut(PagePart.RESULTS, LoginSign.REDIRECT)
        html = self._text(answer)
        with _doing(Operation.READ):
            return read_results(self._page, html)

    @_action(PagePart.ORDER)
    def open_order(self, order: ListedOrder) -> OrderPricing:
        """Otwiera stronę zlecenia ``order`` i czyta datę wykonania, kwotę końcową i ilości pozycji."""

        with _doing(Operation.OPEN):
            response = self._page.goto(
                urljoin(self._url, f"{ORDER_PAGE}?id={order.order_id}"), wait_until="load", timeout=self._timeout_ms
            )
        return self._read_order(response)

    @_action(PagePart.DATE)
    def set_execution_date(self, day: date) -> bool:
        """Wybiera ``day`` w kalendarzu okna „Wybierz datę wykonania” i potwierdza go, gdy kalendarz go przyjął.

        ``False``: kalendarz efenix zamienił dzień na inny, więc okno zamknęło kalendarz bez „Potwierdź”.
        """

        self._click(self._only(_DATE_BUTTON, PagePart.DATE))
        self._shown(_DATE_DIALOG, PagePart.DATE)
        field = self._only(f"{_DATE_DIALOG} {_DATE_FIELD}", PagePart.DATE)
        with _doing(Operation.PICK):
            picked = field.evaluate(_PICK_DAY, [day.year, day.month, day.day], timeout=self._timeout_ms)
        with _doing(Operation.READ):
            shown = field.input_value(timeout=self._timeout_ms)
        if picked is not True:
            raise UnexpectedPage(PagePart.DATE, OtherShape(Shape.NO_CALENDAR))
        if shown != day.isoformat():
            self._close(_DATE_DIALOG, PagePart.DATE)
            return False
        confirm = self._only(f"{_DATE_DIALOG} {_OK}", PagePart.DATE)
        answer = self._answer(_SET_DATE, lambda _params: True, lambda: self._click(confirm))
        if _redirected_to_login(answer):
            raise LoggedOut(PagePart.DATE, LoginSign.REDIRECT)
        return True

    @_action(PagePart.EMMETT)
    def load_emmett(self) -> OrderPricing:
        """Ładuje Wycenę Emmetta do otwartego zlecenia i czyta stronę po przeładowaniu, które robi skrypt efenix."""

        self._click(self._only(_EMMETT_BUTTON, PagePart.EMMETT))
        self._shown(_EMMETT_DIALOG, PagePart.EMMETT)
        load = self._only(f"{_EMMETT_DIALOG} {_OK}", PagePart.EMMETT)
        with _doing(Operation.RELOAD), self._page.expect_navigation(wait_until="load", timeout=self._timeout_ms) as reload:
            self._answer(_LOAD_EMMETT, lambda _params: True, lambda: self._click(load))
        return self._read_order(reload.value)

    @_action(PagePart.QUANTITY)
    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Wpisuje ``quantity`` w pole „Ilość” pozycji ``position`` i zwraca kwotę końcową z odpowiedzi efenix."""

        field_id = self._positions.get(position)
        if field_id is None:
            raise UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.UNKNOWN_POSITION, position))
        field = self._only(f"{QUANTITY}#{field_id}", PagePart.QUANTITY)
        self._click(field)
        with _doing(Operation.FILL):
            field.fill(str(quantity), timeout=self._timeout_ms)
        answer = self._answer(_SAVE_QUANTITY, lambda params: params.get("index") == [field_id], lambda: self._enter(field))
        if _redirected_to_login(answer):
            raise LoggedOut(PagePart.QUANTITY, LoginSign.REDIRECT)
        try:
            saved = json.loads(self._text(answer))
        except ValueError as error:
            raise UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, position)) from error
        result = saved.get("result") if isinstance(saved, dict) else None
        if result == "nok":
            raise LoggedOut(PagePart.QUANTITY, LoginSign.REFUSED)
        if result != "ok":
            raise UnexpectedPage(PagePart.QUANTITY, OtherShape(Shape.ANSWER_RESULT, position))
        shown = str(saved.get(_PRICE_ALL, ""))
        amount = _amount(shown, PagePart.QUANTITY)
        with _doing(Operation.AMOUNT):
            self._page.wait_for_function(_SHOWS, arg=[AMOUNT, shown], timeout=self._timeout_ms)
        return amount

    def _read_order(self, response: Response | None) -> OrderPricing:
        """Strona zlecenia, na którą przeglądarka przeszła odpowiedzią ``response`` (otwarcie albo przeładowanie).

        Stronę, której nie przeczytało, okno nazywa w przyczynie stroną błędu HTTP (nawigacja nie zgłasza błędu przy
        statusie 4xx i 5xx) albo formularzem logowania pod adresem zlecenia, zanim uzna ją za stronę w innej budowie.
        Sprawdza to tylko po nieudanym odczycie, więc strony, którą czyta, nie odrzuca.
        """

        self._ensure_logged_in(PagePart.ORDER)
        try:
            with _doing(Operation.READ):
                pricing, self._positions = _order_on(self._page)
        except UnexpectedPage as unread:
            if response is not None and not response.ok:
                raise UnexpectedPage(PagePart.ORDER, HttpStatus(response.status)) from unread
            if self._page.locator(_LOGIN_FORM).count() > 0:
                raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.LOGIN_FORM)) from unread
            raise
        return pricing

    def _only(self, selector: str, part: PagePart) -> Locator:
        with _doing(Operation.READ):
            return _single(self._page, selector, part)

    def _shown(self, selector: str, part: PagePart) -> None:
        located = self._only(selector, part)
        with _doing(Operation.ELEMENT):
            located.wait_for(state="visible", timeout=self._timeout_ms)

    def _click(self, located: Locator) -> None:
        with _doing(Operation.CLICK):
            located.click(timeout=self._timeout_ms)

    def _enter(self, field: Locator) -> None:
        with _doing(Operation.ENTER):
            field.press("Enter", timeout=self._timeout_ms)

    def _text(self, answer: Response) -> str:
        with _doing(Operation.ANSWER):
            return answer.text()

    def _close(self, dialog: str, part: PagePart) -> None:
        """Zamyka okno dialogowe jego przyciskiem zamknięcia, bez „Potwierdź”, i czeka, aż zniknie."""

        selector = f"{dialog} {_DISMISS}"
        dismiss = self._page.locator(selector)
        with _doing(Operation.READ):
            count = dismiss.count()
        if count == 0:
            raise UnexpectedPage(part, ElementCount(selector, count))
        self._click(dismiss.first)
        located = self._only(dialog, part)
        with _doing(Operation.ELEMENT):
            located.wait_for(state="hidden", timeout=self._timeout_ms)

    def _answer(self, path: str, wanted: Callable[[dict[str, list[str]]], bool], act: Callable[[], None]) -> Response:
        """Odpowiedź efenix na zmianę zlecenia, którą wysyła ``act``."""

        self._sent_change = True
        return self._finished(lambda request: _is_post(request, path) and wanted(_form(request)), act)

    def _finished(self, wanted: Callable[[Request], bool], act: Callable[[], None]) -> Response:
        """Odpowiedź efenix z całą treścią na żądanie ``wanted``, które wysyła ``act``: okno czeka w czasie ``timeout_ms``
        na koniec żądania, a nie na nagłówki odpowiedzi, po których treść może się urwać albo stanąć."""

        with _doing(Operation.ANSWER):
            with self._page.expect_request_finished(wanted, timeout=self._timeout_ms) as finished:
                act()
            response = finished.value.response()
        assert response is not None, "zakończone żądanie ma odpowiedź"
        return response

    def _ensure_logged_in(self, part: PagePart) -> None:
        if _on_login_page(self._page.url):
            raise LoggedOut(part, LoginSign.PAGE)


def read_results(page: Page, html: str) -> tuple[ListedOrder, ...]:
    """Wiersze tabeli wyników z odpowiedzi szukania ``html``, przeczytane parserem HTML przeglądarki strony ``page``."""

    results: _Results | None = page.evaluate(_READ_RESULTS, html)
    if results is None:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.NO_TABLE))
    return tuple(_listed(results["headers"], row) for row in results["rows"])


def read_order(page: Page) -> OrderPricing:
    """Data wykonania, kwota końcowa i ilości pozycji ze strony zlecenia, którą pokazuje ``page``."""

    return _order_on(page)[0]


def _listed(headers: Sequence[str], row: Sequence[_Cell]) -> ListedOrder:
    columns = {field: _column(headers, header) for field, header in HEADERS.items()}
    links = [cell["link"] for cell in row if cell["link"]]
    if len(row) != len(headers) or len(links) != 1:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_CELLS))
    order_id = parse_qs(urlparse(links[0]).query).get("id", [""])[0]
    number = row[columns["number"]]["plain"]
    status = row[columns["status"]]
    found = _LOGIN.findall(row[columns["realizator"]]["login"] or "")
    if not order_id or not number:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.ROW_EMPTY))
    return ListedOrder(
        number=number,
        status=status["badge"] if status["badge"] is not None else status["plain"],
        realizator=found[-1] if found else None,
        address=row[columns["address"]]["plain"],
        order_id=order_id,
    )


def _order_on(page: Page) -> tuple[OrderPricing, dict[str, str]]:
    """Strona zlecenia w ``page`` i ``id`` pola Ilość każdej pozycji (kod ``NNN`` → ``id``)."""

    executed = _single(page, EXECUTION_DATE, PagePart.ORDER)
    total = _single(page, AMOUNT, PagePart.ORDER)
    fields: list[list[str]] = page.locator(QUANTITY).evaluate_all("(fields) => fields.map((f) => [f.id, f.value])")
    positions: dict[str, str] = {}
    quantities: dict[str, int] = {}
    for field_id, value in fields:
        found = _POSITION.fullmatch(field_id)
        if found is None:
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_ID))
        if found[1] in positions:
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.POSITION_TWICE, found[1]))
        if not _QUANTITY_TEXT.fullmatch(value.strip()):
            raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.QUANTITY_VALUE, found[1]))
        positions[found[1]] = field_id
        quantities[found[1]] = int(value.strip() or 0)
    return OrderPricing(_execution_date(executed.inner_text()), _amount(total.inner_text(), PagePart.ORDER), quantities), positions


def _single(page: Page, selector: str, part: PagePart) -> Locator:
    """Element strony, który jest na niej dokładnie raz; inaczej efenix ma inną budowę."""

    located = page.locator(selector)
    if (count := located.count()) != 1:
        raise UnexpectedPage(part, ElementCount(selector, count))
    return located


class _Failed(Exception):
    """Błąd Playwrighta w działaniu przeglądarki, które nazwał ``_doing``; ``__cause__`` to ten błąd."""

    def __init__(self, failure: BrowserFailure) -> None:
        super().__init__(failure.error_type)
        self.failure = failure


@contextmanager
def _doing(operation: Operation) -> Iterator[None]:
    """Działanie przeglądarki ``operation`` w działaniu okna: błąd Playwrighta w nim to ``_Failed`` z typem błędu."""

    try:
        yield
    except PlaywrightError as error:
        raise _Failed(BrowserFailure(exception_type(error), operation)) from error


@contextmanager
def _within(part: PagePart) -> Iterator[None]:
    """Działanie na części ``part`` strony, które skończyło się błędem Playwrighta, to ``UnexpectedPage(part)`` z typem
    błędu i działaniem przeglądarki (``None``, gdy ``_doing`` go nie nazwał)."""

    try:
        yield
    except _Failed as failed:
        raise UnexpectedPage(part, failed.failure) from failed.__cause__
    except PlaywrightError as error:
        raise UnexpectedPage(part, BrowserFailure(exception_type(error), None)) from error


def _column(headers: Sequence[str], header: str) -> int:
    positions = [index for index, text in enumerate(headers) if text.casefold().startswith(header)]
    if len(positions) != 1:
        raise UnexpectedPage(PagePart.RESULTS, OtherShape(Shape.COLUMNS))
    return positions[0]


def _is_search(request: Request, number: str) -> bool:
    return _is_post(request, SEARCH) and _form(request).get(_NUMBER_PARAM) == [number]


def _is_post(request: Request, path: str) -> bool:
    return request.method == "POST" and urlparse(request.url).path.endswith("/" + path)


def _form(request: Request) -> dict[str, list[str]]:
    return parse_qs(request.post_data or "")


def _execution_date(shown: str) -> date | None:
    text = " ".join(shown.split())
    if not text:
        return None
    if not _DAY.fullmatch(text):
        raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT))
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise UnexpectedPage(PagePart.ORDER, OtherShape(Shape.DATE_TEXT)) from error


def _amount(shown: str, part: PagePart) -> Decimal:
    text = "".join(shown.split())
    if not _AMOUNT_TEXT.fullmatch(text):
        raise UnexpectedPage(part, OtherShape(Shape.AMOUNT_TEXT))
    return Decimal(text)


def _on_login_page(url: str) -> bool:
    return urlparse(url).path.endswith("/" + LOGIN_PAGE)


def _redirected_to_login(response: Response) -> bool:
    return 300 <= response.status < 400 and urlparse(response.headers.get("location", "")).path.endswith(LOGIN_PAGE)


@contextmanager
def window(
    page: Page,
    url: str,
    *,
    timeout_ms: int = TIMEOUT_MS,
    login: Login | None = None,
    login_timeout_ms: int = LOGIN_TIMEOUT_MS,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[BrowserEfenix]:
    """Okno efenix na stronie ``page``, którą daje rozmówca, z otwartą listą zleceń pod adresem ``url``.

    Z ``login`` na stronie logowania czeka na logowanie taty (``BrowserEfenix.wait_for_login``, czas czekania mierzy
    ``clock``), bez niego to ``LoggedOut``.
    """

    efenix = BrowserEfenix(page, url, timeout_ms=timeout_ms)
    if login is None:
        efenix.open_list()
    else:
        efenix.wait_for_login(login, timeout_ms=login_timeout_ms, clock=clock)
    yield efenix


def default_profile() -> Path:
    """Profil przeglądarki okna efenix taty: osobny od jego profilu z kartami, trwały między uruchomieniami."""

    return TOOL_ROOT / PROFILE_DIRECTORY


@contextmanager
def chrome(
    url: str,
    profile: Path,
    login: Login,
    *,
    channel: str | None = "chrome",
    headless: bool = False,
    login_timeout_ms: int = LOGIN_TIMEOUT_MS,
    arguments: Sequence[str] = (),
) -> Iterator[BrowserEfenix]:
    """Okno efenix taty: przeglądarka ``channel`` (zainstalowany Google Chrome) w trwałym profilu ``profile``.

    Profil pamięta logowanie między uruchomieniami i nie jest profilem taty z jego kartami. Okno czeka na logowanie taty
    w ``login`` i zamyka się z przeglądarką na końcu bloku. ``channel`` ``None`` to Chromium Playwrighta, a ``headless``
    i ``arguments`` (np. port debugowania) są dla testów i weryfikacji; ``BrowserNotStarted``, gdy przeglądarka nie
    wystartowała.
    """

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                profile, channel=channel, headless=headless, no_viewport=True, args=list(arguments)
            )
        except PlaywrightError as error:
            raise BrowserNotStarted(BrowserFailure(exception_type(error), Operation.START)) from error
        try:
            page = context.pages[0] if context.pages else context.new_page()
            with window(page, url, login=login, login_timeout_ms=login_timeout_ms) as efenix:
                yield efenix
        finally:
            # Przeglądarka, którą tata zamknął już sam, nie zmienia wyniku.
            with suppress(PlaywrightError):
                context.close()


@contextmanager
def chromium(url: str, *, headless: bool = True) -> Iterator[BrowserEfenix]:
    """Okno efenix w nowym Chromium Playwrighta (Skrypt dla maszyn); przeglądarka zamyka się z oknem."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            with window(browser.new_page(), url) as efenix:
                yield efenix
        finally:
            browser.close()
