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
``LoggedOut``, adres, który nie odpowiada, to ``EfenixUnreachable``, a strona bez oczekiwanej budowy, element obecny,
ale niewidoczny, albo brak odpowiedzi w czasie ``timeout_ms`` to ``UnexpectedPage``. Przeglądarkę daje rozmówca: stronę (``window``) albo Chromium Playwrighta (``chromium``).

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
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import json
import re
from typing import Final, TypedDict
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .efenix_pricing import EfenixUnreachable, ListedOrder, LoggedOut, OrderPricing, PagePart, UnexpectedPage

__all__ = ["BrowserEfenix", "chromium", "window"]

_NUMBER_FIELD: Final = "#field_numer"
_LOGIN_PAGE: Final = "page_login.php"
_SEARCH: Final = "action_fill_orders.php"
_ORDER_PAGE: Final = "page_order_edit.php"
_EXECUTION_DATE: Final = "#data_install"
_AMOUNT: Final = "#cena_all2"
_QUANTITY: Final = "input.wycena-ilosc"
_DATE_BUTTON: Final = "#button-calendar"
_DATE_DIALOG: Final = "#dialog_select_date"
_DATE_FIELD: Final = "#field_data_instalacji"
_SET_DATE: Final = "action_set_date_of_instalation.php"
_EMMETT_BUTTON: Final = "#button_emmett"
_EMMETT_DIALOG: Final = "#dialog_emmett"
_LOAD_EMMETT: Final = "action_load_emmett.php"
_SAVE_QUANTITY: Final = "action_save_index.php"
_OK: Final = ".btn-ok"
_POSITION: Final = re.compile(r"INDEKS_(\d{3})_\d+")
_AMOUNT_TEXT: Final = re.compile(r"[0-9]+(\.[0-9]+)?")
_QUANTITY_TEXT: Final = re.compile(r"[0-9]*")
_HEADERS: Final = {"number": "numer dokumentu", "status": "status", "realizator": "wykonawca", "address": "dane adresowe"}
_LOGIN: Final = re.compile(r"\(([^()\s]+)\)")
_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
TIMEOUT_MS: Final = 30_000

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
_SHOWS: Final = "([selector, text]) => document.querySelector(selector)?.textContent.trim() === text"


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

    @property
    def sent_change(self) -> bool:
        """Okno kliknęło już „Potwierdź” daty, „Załaduj do zlecenia” albo Enter w polu „Ilość”."""

        return self._sent_change

    def open_list(self) -> None:
        """Otwiera listę zleceń; ``EfenixUnreachable``, gdy adres nie odpowiada."""

        try:
            self._page.goto(self._url, wait_until="load", timeout=self._timeout_ms)
        except PlaywrightError as error:
            raise EfenixUnreachable from error
        self._ensure_logged_in()
        if self._page.locator(_NUMBER_FIELD).count() != 1:
            raise UnexpectedPage(PagePart.LIST)

    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze tabeli wyników po szukaniu ``number`` w polu ``Numer`` listy zleceń."""

        if urlparse(self._page.url).path != urlparse(self._url).path:
            self.open_list()
        field = self._page.locator(_NUMBER_FIELD)
        with _within(PagePart.LIST):
            field.fill(number, timeout=self._timeout_ms)
        with _within(PagePart.RESULTS), self._page.expect_response(lambda response: _is_search(response, number), timeout=self._timeout_ms) as answer:
            field.press("Enter", timeout=self._timeout_ms)
        if _redirected_to_login(answer.value):
            raise LoggedOut
        try:
            html = answer.value.text()
        except PlaywrightError as error:
            raise UnexpectedPage(PagePart.RESULTS) from error
        results: _Results | None = self._page.evaluate(_READ_RESULTS, html)
        if results is None:
            raise UnexpectedPage(PagePart.RESULTS)
        return tuple(self._listed(results["headers"], row) for row in results["rows"])

    def open_order(self, order: ListedOrder) -> OrderPricing:
        """Otwiera stronę zlecenia ``order`` i czyta datę wykonania, kwotę końcową i ilości pozycji."""

        try:
            self._page.goto(urljoin(self._url, f"{_ORDER_PAGE}?id={order.order_id}"), wait_until="load", timeout=self._timeout_ms)
        except PlaywrightError as error:
            raise EfenixUnreachable from error
        return self._read_order()

    def set_execution_date(self, day: date) -> bool:
        """Wybiera ``day`` w kalendarzu okna „Wybierz datę wykonania” i potwierdza go, gdy kalendarz go przyjął.

        ``False``: kalendarz efenix zamienił dzień na inny, więc okno zamknęło kalendarz bez „Potwierdź”.
        """

        self._click(self._only(_DATE_BUTTON, PagePart.DATE), PagePart.DATE)
        self._shown(_DATE_DIALOG, PagePart.DATE)
        field = self._only(f"{_DATE_DIALOG} {_DATE_FIELD}", PagePart.DATE)
        with _within(PagePart.DATE):
            picked = field.evaluate(_PICK_DAY, [day.year, day.month, day.day], timeout=self._timeout_ms)
            shown = field.input_value(timeout=self._timeout_ms)
        if picked is not True:
            raise UnexpectedPage(PagePart.DATE)
        if shown != day.isoformat():
            self._close(_DATE_DIALOG, PagePart.DATE)
            return False
        confirm = self._only(f"{_DATE_DIALOG} {_OK}", PagePart.DATE)
        answer = self._answer(_SET_DATE, lambda _params: True, lambda: self._click(confirm, PagePart.DATE), PagePart.DATE)
        if _redirected_to_login(answer):
            raise LoggedOut
        return True

    def load_emmett(self) -> OrderPricing:
        """Ładuje Wycenę Emmetta do otwartego zlecenia i czyta stronę po przeładowaniu, które robi skrypt efenix."""

        self._click(self._only(_EMMETT_BUTTON, PagePart.EMMETT), PagePart.EMMETT)
        self._shown(_EMMETT_DIALOG, PagePart.EMMETT)
        load = self._only(f"{_EMMETT_DIALOG} {_OK}", PagePart.EMMETT)
        with _within(PagePart.EMMETT), self._page.expect_navigation(wait_until="load", timeout=self._timeout_ms):
            self._answer(_LOAD_EMMETT, lambda _params: True, lambda: self._click(load, PagePart.EMMETT), PagePart.EMMETT)
        return self._read_order()

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Wpisuje ``quantity`` w pole „Ilość” pozycji ``position`` i zwraca kwotę końcową z odpowiedzi efenix."""

        field_id = self._positions.get(position)
        if field_id is None:
            raise UnexpectedPage(PagePart.QUANTITY)
        field = self._only(f"{_QUANTITY}#{field_id}", PagePart.QUANTITY)
        self._click(field, PagePart.QUANTITY)
        with _within(PagePart.QUANTITY):
            field.fill(str(quantity), timeout=self._timeout_ms)
        answer = self._answer(
            _SAVE_QUANTITY,
            lambda params: params.get("index") == [field_id],
            lambda: field.press("Enter", timeout=self._timeout_ms),
            PagePart.QUANTITY,
        )
        if _redirected_to_login(answer):
            raise LoggedOut
        try:
            saved = json.loads(answer.text())
        except (PlaywrightError, ValueError) as error:
            raise UnexpectedPage(PagePart.QUANTITY) from error
        result = saved.get("result") if isinstance(saved, dict) else None
        if result == "nok":
            raise LoggedOut
        if result != "ok":
            raise UnexpectedPage(PagePart.QUANTITY)
        shown = str(saved.get("price_all", ""))
        amount = _amount(shown, PagePart.QUANTITY)
        self._wait_for_text(_AMOUNT, shown, PagePart.QUANTITY)
        return amount

    def _read_order(self) -> OrderPricing:
        self._ensure_logged_in()
        executed = self._only(_EXECUTION_DATE, PagePart.ORDER)
        total = self._only(_AMOUNT, PagePart.ORDER)
        fields: list[list[str]] = self._page.locator(_QUANTITY).evaluate_all("(fields) => fields.map((f) => [f.id, f.value])")
        positions: dict[str, str] = {}
        quantities: dict[str, int] = {}
        for field_id, value in fields:
            found = _POSITION.fullmatch(field_id)
            if found is None or found[1] in positions or not _QUANTITY_TEXT.fullmatch(value.strip()):
                raise UnexpectedPage(PagePart.ORDER)
            positions[found[1]] = field_id
            quantities[found[1]] = int(value.strip() or 0)
        self._positions = positions
        return OrderPricing(_execution_date(executed.inner_text()), _amount(total.inner_text(), PagePart.ORDER), quantities)

    def _only(self, selector: str, part: PagePart) -> Locator:
        located = self._page.locator(selector)
        if located.count() != 1:
            raise UnexpectedPage(part)
        return located

    def _shown(self, selector: str, part: PagePart) -> None:
        with _within(part):
            self._only(selector, part).wait_for(state="visible", timeout=self._timeout_ms)

    def _click(self, located: Locator, part: PagePart) -> None:
        """Klik elementu, który musi być widoczny i klikalny w czasie ``timeout_ms``; inaczej ``UnexpectedPage``."""

        with _within(part):
            located.click(timeout=self._timeout_ms)

    def _close(self, dialog: str, part: PagePart) -> None:
        """Zamyka okno dialogowe jego przyciskiem zamknięcia, bez „Potwierdź”, i czeka, aż zniknie."""

        dismiss = self._page.locator(f"{dialog} {_DISMISS}")
        if dismiss.count() == 0:
            raise UnexpectedPage(part)
        self._click(dismiss.first, part)
        with _within(part):
            self._only(dialog, part).wait_for(state="hidden", timeout=self._timeout_ms)

    def _answer(self, path: str, wanted: Callable[[dict[str, list[str]]], bool], act: Callable[[], None], part: PagePart) -> Response:
        """Odpowiedź efenix na zmianę zlecenia, którą wysyła ``act``."""

        self._sent_change = True
        with _within(part), self._page.expect_response(
            lambda response: _is_post(response, path) and wanted(_form(response)), timeout=self._timeout_ms
        ) as answer:
            act()
        return answer.value

    def _wait_for_text(self, selector: str, text: str, part: PagePart) -> None:
        with _within(part):
            self._page.wait_for_function(_SHOWS, arg=[selector, text], timeout=self._timeout_ms)

    def _ensure_logged_in(self) -> None:
        if urlparse(self._page.url).path.endswith("/" + _LOGIN_PAGE):
            raise LoggedOut

    @staticmethod
    def _listed(headers: Sequence[str], row: Sequence[_Cell]) -> ListedOrder:
        columns = {field: _column(headers, header) for field, header in _HEADERS.items()}
        links = [cell["link"] for cell in row if cell["link"]]
        if len(row) != len(headers) or len(links) != 1:
            raise UnexpectedPage(PagePart.RESULTS)
        order_id = parse_qs(urlparse(links[0]).query).get("id", [""])[0]
        number = row[columns["number"]]["plain"]
        status = row[columns["status"]]
        found = _LOGIN.findall(row[columns["realizator"]]["login"] or "")
        if not order_id or not number:
            raise UnexpectedPage(PagePart.RESULTS)
        return ListedOrder(
            number=number,
            status=status["badge"] if status["badge"] is not None else status["plain"],
            realizator=found[-1] if found else None,
            address=row[columns["address"]]["plain"],
            order_id=order_id,
        )


@contextmanager
def _within(part: PagePart) -> Iterator[None]:
    """Działanie na części ``part`` strony, które nie skończyło się w czasie okna, to efenix o innej budowie."""

    try:
        yield
    except PlaywrightTimeoutError as error:
        raise UnexpectedPage(part) from error


def _column(headers: Sequence[str], header: str) -> int:
    positions = [index for index, text in enumerate(headers) if text.casefold().startswith(header)]
    if len(positions) != 1:
        raise UnexpectedPage(PagePart.RESULTS)
    return positions[0]


def _is_search(response: Response, number: str) -> bool:
    return _is_post(response, _SEARCH) and _form(response).get("numer") == [number]


def _is_post(response: Response, path: str) -> bool:
    return response.request.method == "POST" and urlparse(response.url).path.endswith("/" + path)


def _form(response: Response) -> dict[str, list[str]]:
    return parse_qs(response.request.post_data or "")


def _execution_date(shown: str) -> date | None:
    text = " ".join(shown.split())
    if not text:
        return None
    if not _DAY.fullmatch(text):
        raise UnexpectedPage(PagePart.ORDER)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise UnexpectedPage(PagePart.ORDER) from error


def _amount(shown: str, part: PagePart) -> Decimal:
    text = "".join(shown.split())
    if not _AMOUNT_TEXT.fullmatch(text):
        raise UnexpectedPage(part)
    return Decimal(text)


def _redirected_to_login(response: Response) -> bool:
    return 300 <= response.status < 400 and urlparse(response.headers.get("location", "")).path.endswith(_LOGIN_PAGE)


@contextmanager
def window(page: Page, url: str, *, timeout_ms: int = TIMEOUT_MS) -> Iterator[BrowserEfenix]:
    """Okno efenix na stronie ``page``, którą daje rozmówca, z otwartą listą zleceń pod adresem ``url``."""

    efenix = BrowserEfenix(page, url, timeout_ms=timeout_ms)
    efenix.open_list()
    yield efenix


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
