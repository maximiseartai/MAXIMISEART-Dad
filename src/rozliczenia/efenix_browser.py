"""Okno efenix w przeglądarce: jedyny moduł, który zna Playwright i budowę stron efenix.

Na zewnątrz daje tylko typy domeny (``efenix_pricing.Efenix``, ``ListedOrder``) i zna tylko dwa działania, które niczego
w efenix nie zmieniają: szukanie po ``Numer`` na liście zleceń i odczyt daty wykonania ze strony zlecenia. Szuka tak jak
tata: wpisuje numer w pole ``#field_numer`` i naciska Enter, a skrypt strony wysyła ``action_fill_orders.php`` i wkłada
odpowiedź do ``#wyniki``. Tabelę wyników okno czyta z odpowiedzi na swoje szukanie (tej z jego numerem w polu ``numer``),
tę samą, którą skrypt wkłada do ``#wyniki``, bo lista po wczytaniu sama szuka ostatniego numeru z poprzedniej wizyty, a
jej odpowiedź trafia do ``#wyniki`` w dowolnej chwili. Kolumny tabeli rozpoznaje po nagłówkach (``Numer dokumentu``,
``Status``, ``Wykonawca``, ``Dane adresowe``), a stronę zlecenia otwiera linkiem ``page_order_edit.php?id=`` z wiersza. Przekierowanie strony
albo szukania na ``page_login.php`` to ``LoggedOut``, a strona bez oczekiwanej budowy albo bez odpowiedzi w czasie
``timeout_ms`` to ``UnexpectedPage``. Przeglądarkę daje rozmówca: stronę (``window``) albo Chromium Playwrighta (``chromium``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
import re
from typing import Final, TypedDict
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .efenix_pricing import EfenixUnreachable, ListedOrder, LoggedOut, PagePart, UnexpectedPage

__all__ = ["BrowserEfenix", "chromium", "window"]

_NUMBER_FIELD: Final = "#field_numer"
_LOGIN_PAGE: Final = "page_login.php"
_SEARCH: Final = "action_fill_orders.php"
_ORDER_PAGE: Final = "page_order_edit.php"
_EXECUTION_DATE: Final = "#data_install"
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
            const link = cell.querySelector('a[href*="page_order_edit.php?id="]');
            return {
                plain: text(plain),
                badge: badge ? text(badge) : null,
                link: link ? link.getAttribute('href') : null,
            };
        })),
    };
}"""


class _Cell(TypedDict):
    plain: str
    badge: str | None
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
        field.fill(number)
        try:
            with self._page.expect_response(lambda response: _is_search(response, number), timeout=self._timeout_ms) as answer:
                field.press("Enter")
        except PlaywrightTimeoutError as error:
            raise UnexpectedPage(PagePart.RESULTS) from error
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

    def execution_date(self, order: ListedOrder) -> date | None:
        """Data wykonania ze strony zlecenia ``order`` (``#data_install``); pusta to ``None``."""

        self._page.goto(urljoin(self._url, f"{_ORDER_PAGE}?id={order.order_id}"), wait_until="load", timeout=self._timeout_ms)
        self._ensure_logged_in()
        executed = self._page.locator(_EXECUTION_DATE)
        if executed.count() != 1:
            raise UnexpectedPage(PagePart.ORDER)
        text = " ".join(executed.inner_text().split())
        if not text:
            return None
        if not _DAY.fullmatch(text):
            raise UnexpectedPage(PagePart.ORDER)
        try:
            return date.fromisoformat(text)
        except ValueError as error:
            raise UnexpectedPage(PagePart.ORDER) from error

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
        found = _LOGIN.findall(row[columns["realizator"]]["plain"])
        if not order_id or not number:
            raise UnexpectedPage(PagePart.RESULTS)
        return ListedOrder(
            number=number,
            status=status["badge"] if status["badge"] is not None else status["plain"],
            realizator=found[-1] if found else None,
            address=row[columns["address"]]["plain"],
            order_id=order_id,
        )


def _column(headers: Sequence[str], header: str) -> int:
    positions = [index for index, text in enumerate(headers) if text.casefold().startswith(header)]
    if len(positions) != 1:
        raise UnexpectedPage(PagePart.RESULTS)
    return positions[0]


def _is_search(response: Response, number: str) -> bool:
    request = response.request
    searched = parse_qs(request.post_data or "").get("numer")
    return request.method == "POST" and urlparse(response.url).path.endswith("/" + _SEARCH) and searched == [number]


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
