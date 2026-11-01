"""Porównuje budowę stron efenix z Atrapą efenix samym odczytem; uruchom przed pierwszą Wyceną w efenix i po Zgłoszeniu „efenix się zmienił”.

Narzędzie dla Maksa, poza CI (ADR 0024). Łączy się z Chrome, w którym Maks jest zalogowany do efenix kontem taty, otwiera
w nim własną kartę i sprawdza budowę, której używa Wycena w efenix i którą odtwarza Atrapa efenix
(``tests/fixtures/atrapa_efenix.py``):

- lista zleceń: pole ``Numer`` (``efenix_browser.NUMBER_FIELD``) i ``#wyniki``, a otwiera ją ``BrowserEfenix.open_list``;
- szukanie: Enter w polu ``Numer`` wysyła ``POST action_fill_orders.php`` z polem ``numer``, a tabela odpowiedzi ma
  nagłówki ``efenix_browser.HEADERS`` i w każdym wierszu link ``page_order_edit.php?id=`` i status w ``.badge``;
  ``BrowserEfenix.search`` czyta jeden jej wiersz, z loginem realizatora i ``Dane adresowe``;
- strona zlecenia: ``BrowserEfenix.execution_date`` czyta ``#data_install`` (``RRRR-MM-DD`` albo pusty tekst; pustej
  daty narzędzie szuka wśród otwieranych zleceń, najpierw „Do wyceny”), elementy z ``ELEMENTS`` (przycisk i okno
  Emmetta, okno daty, kwota końcowa, pola Ilość i ceny wpisywanej w kartach pozycji, przyciski Przekazania do akceptacji
  i anulowania, których nie dotyka) oraz karty pozycji ``.card.rounded-lg.kolorek`` równe ``atrapa_efenix.POSITIONS``:
  kod ``INDEKS_NNN_NNN`` to ``id`` jedynego pola karty, karta z polem Ilość (``input.wycena-ilosc``) ma cenę jednostkową
  w tekście ``.col-sm-1.mt-2 > span.text-default > small`` (porównaną jako liczba), a karta z ceną wpisywaną ma samo pole
  ``input.wycena-cena`` bez ceny w tekście;
- bez sesji (nowy kontekst przeglądarki bez ciasteczek, więc sesja taty trwa): lista i szukanie przekierowują na
  ``page_login.php``, a strona logowania ma formularz ``action_login.php`` z polami ``field_signum``,
  ``field_password`` i ``fingerprint``.

Na czas sprawdzania każde żądanie kontekstu przeglądarki z sesją (każdej jego karty i okna, także otwartego skryptem
strony, ramki i workera) przechodzi przez ``ALLOWED`` (``context.route``): GET listy, strony zlecenia i strony logowania,
POST szukania, odczyt daty ``action_get_date_of_instalation.php``, odczyty, które strony efenix wysyłają same, i GET
plików strony (style, skrypty, obrazy, czcionki) bez ``.php``. Dozwolone żądanie narzędzie wysyła samo, bez podążania
za przekierowaniem, i oddaje przeglądarce odpowiedź, więc każdy krok przekierowania wraca na listę jako nowe żądanie,
zanim wyjdzie. Inne żądanie i każdy WebSocket narzędzie przerywa przed wysłaniem i wypisuje jako ``ZABLOKOWANE``, a okna
otwarte przez swoją kartę zamyka. Niczego nie klika poza Enter w polu ``Numer``. ``action_fill_emmett.php`` (propozycja
Emmetta) nie jest na liście, bo bez kodu serwera nie wiadomo, czy niczego nie zapisuje. Chrome z osobnym profilem (niżej)
nie ma innych kart, więc blokada kontekstu nie zatrzymuje cudzej pracy.

Uruchomienie: Chrome z osobnym profilem i zdalnym debugowaniem, w nim logowanie do efenix kontem taty, potem narzędzie:

    google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.efenix-zgodnosc"
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\\.efenix-zgodnosc"
    .venv/bin/python tools/zgodnosc_efenix.py --efenix-url <adres listy zleceń, …/index.php>

Wynik: linie ``RÓŻNICA | <część> | <co>``, ``NIESPRAWDZONE | <część> | <co>`` i ``ZABLOKOWANE | <metoda> <strona>``,
na końcu ``ZGODNOŚĆ OK`` (kod 0) albo liczby (kod 2). Wynik nie zawiera numerów zleceń, adresów ani loginów: tylko
nazwy elementów, liczby, kody pozycji z cenami i postać daty (cyfry jako ``9``). Kod 1: brak Chrome pod ``--cdp``,
efenix nie odpowiada albo karta nie jest zalogowana; opis na stderr.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import enum
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Final, TypedDict
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import APIResponse, Browser, BrowserContext, Page, Route, WebSocketRoute, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Korzeń repozytorium dla Atrapy efenix (``tests.fixtures``), z której narzędzie bierze kody pozycji i ceny.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozliczenia.efenix_browser import (
    EXECUTION_DATE,
    HEADERS,
    LOGIN_PAGE,
    NUMBER_FIELD,
    ORDER_PAGE,
    SEARCH,
    TIMEOUT_MS,
    BrowserEfenix,
)
from rozliczenia.efenix_checks import PRICING_STATUS
from rozliczenia.efenix_pricing import EfenixUnreachable, ListedOrder, LoggedOut, UnexpectedPage

from tests.fixtures.atrapa_efenix import POSITIONS

LIST_PAGE: Final = "index.php"
LOGIN_ACTION: Final = "action_login.php"
DATE_READ: Final = "action_get_date_of_instalation.php"
# Odczyty, które strony efenix wysyłają same, a z kodu strony z rekonesansu (#741) tylko wkładają odpowiedź na stronę.
# Bez nich na zgodnym efenix wynik zawsze miałby ZABLOKOWANE. Atrapa efenix je odtwarza (``atrapa_efenix.PAGE_READS``).
PAGE_READS: Final = frozenset(
    {
        # Lista po wczytaniu: licznik zalogowanych (też co 2 minuty) i opcje list wyboru województwa, powiatu, gminy,
        # miasta oraz liczba ulic; po każdej tabeli wyników skrypt stronicowania pobierany przez XHR, nie jako <script>.
        ("POST", "action_users_online.php"),
        ("POST", "action_fill_country_order.php"),
        ("POST", "action_fill_community_order.php"),
        ("POST", "action_fill_city_order.php"),
        ("POST", "action_streets_count_order.php"),
        ("POST", "action_fill_streets_order.php"),
        ("GET", "pagination.js"),
        # Strona zlecenia po wczytaniu: notatki zlecenia do ``#notatki`` (pole ``button_note_delete`` mówi tylko, czy
        # pokazać przyciski kasowania; kasuje ``action_note_delete.php``, którego nie ma na liście).
        ("POST", "action_fill_notes.php"),
    }
)
# Jedyne żądania do efenix, które narzędzie przepuszcza: odczyty stron i szukanie. Zapis ilości, Emmett, ustawienie
# daty, zmiana statusu, Przekazanie do akceptacji, anulowanie i wylogowanie nie są na liście, więc ich żądanie nie wychodzi.
ALLOWED: Final = frozenset(
    {
        ("GET", LIST_PAGE),
        ("POST", SEARCH),
        ("GET", ORDER_PAGE),
        ("GET", LOGIN_PAGE),
        ("GET", DATE_READ),
        ("POST", DATE_READ),
        *PAGE_READS,
    }
)
# Pliki, z których przeglądarka składa stronę: GET bez ``.php``, z dowolnego adresu.
PAGE_FILES: Final = frozenset({"stylesheet", "script", "image", "font", "media"})
POSITION_CODE: Final = re.compile(r"INDEKS_\d{3}_\d{3}")
ORDERS_TO_OPEN: Final = 10
# Odpowiedzi, za których ``Location`` przeglądarka podąża sama, i najdłuższy łańcuch przekierowań, który narzędzie przepuszcza.
FOLLOWED: Final = frozenset({301, 302, 303, 307, 308})
REDIRECT_HOPS: Final = 5
OK: Final = "ZGODNOŚĆ OK"
LOGGED_OUT_MIDWAY: Final = "efenix wylogował kartę narzędzia w trakcie sprawdzania: zaloguj się i uruchom narzędzie jeszcze raz"


class Part(enum.Enum):
    """Część efenix, której dotyczy linia wyniku."""

    LIST = "lista zleceń"
    RESULTS = "tabela wyników"
    ORDER = "strona zlecenia"
    PRICING = "pozycje wyceny"
    LOGGED_OUT = "bez sesji"
    LOGIN = "strona logowania"


@dataclass(frozen=True)
class Element:
    """Element strony, który musi być na niej dokładnie raz (``many``: co najmniej raz)."""

    part: Part
    selector: str
    name: str
    many: bool = False


PRICING_CARD: Final = ".card.rounded-lg.kolorek"
ELEMENTS: Final = (
    Element(Part.LIST, f"input{NUMBER_FIELD}", "pole Numer"),
    Element(Part.LIST, "#wyniki", "miejsce tabeli wyników"),
    Element(Part.ORDER, EXECUTION_DATE, "data wykonania"),
    Element(Part.ORDER, "#button_emmett", "przycisk Emmetta"),
    Element(Part.ORDER, "#dialog_emmett #emmett-propozycja", "propozycja w oknie Emmetta"),
    Element(Part.ORDER, "#dialog_emmett .btn-ok", "„Załaduj do zlecenia” w oknie Emmetta"),
    Element(Part.ORDER, "input#field_data_instalacji", "pole w oknie daty wykonania"),
    Element(Part.ORDER, "#cena_all2", "kwota końcowa"),
    Element(Part.ORDER, f"{PRICING_CARD} input.wycena-ilosc", "pola Ilość pozycji wyceny", many=True),
    Element(Part.ORDER, f"{PRICING_CARD} input.wycena-cena", "pola ceny wpisywanej pozycji wyceny", many=True),
    Element(Part.ORDER, "#button_forward_to_accept", "przycisk Przekazania do akceptacji"),
    Element(Part.ORDER, "#button_forward_to_cancel", "przycisk anulowania"),
    Element(Part.LOGIN, f'form[action$="{LOGIN_ACTION}"]', "formularz logowania"),
    Element(Part.LOGIN, "input#field_signum", "pole loginu"),
    Element(Part.LOGIN, "input#field_password", "pole hasła"),
    Element(Part.LOGIN, 'input[name="fingerprint"]', "pole fingerprint"),
)

# Tabela odpowiedzi szukania przeczytana w ``<template>``, w którym jej skrypty nie biegną. Numery i identyfikatory
# zostają w pamięci narzędzia: służą do szukania i otwierania zleceń, nie trafiają do wyniku.
_READ_RESULTS: Final = """([html, orderPage]) => {
    const template = document.createElement('template');
    template.innerHTML = html;
    const table = template.content.querySelector('table');
    if (!table) return null;
    const text = (element) => {
        const copy = element.cloneNode(true);
        copy.querySelectorAll('br').forEach((br) => br.replaceWith(' '));
        return copy.textContent.replace(/\\s+/g, ' ').trim();
    };
    const plain = (element) => {
        const copy = element.cloneNode(true);
        copy.querySelectorAll('small').forEach((small) => small.remove());
        return text(copy);
    };
    return {
        headers: [...table.querySelectorAll('thead th')].map(text),
        rows: [...table.querySelectorAll('tbody tr')].map((row) => ({
            cells: [...row.querySelectorAll('td')].map(plain),
            links: [...row.querySelectorAll(`a[href*="${orderPage}?id="]`)].map((link) => link.getAttribute('href')),
            badges: [...row.querySelectorAll('td .badge')].map(text),
        })),
    };
}"""
# Karta pozycji: ``id`` pól Ilość, ``id`` pól ceny wpisywanej i ceny jednostkowe z tekstu karty.
_READ_POSITIONS: Final = """(card) => [...document.querySelectorAll(card)].map((element) => ({
    quantity: [...element.querySelectorAll('input.wycena-ilosc')].map((input) => input.id),
    price: [...element.querySelectorAll('input.wycena-cena')].map((input) => input.id),
    shown: [...element.querySelectorAll('.col-sm-1.mt-2 > span.text-default > small')].map((small) => small.textContent.trim()),
}))"""


class _Row(TypedDict):
    cells: list[str]
    links: list[str]
    badges: list[str]


class _Results(TypedDict):
    headers: list[str]
    rows: list[_Row]


class _Card(TypedDict):
    quantity: list[str]
    price: list[str]
    shown: list[str]


class ToolError(Exception):
    """Narzędzie nie może sprawdzić efenix (brak Chrome, efenix nie odpowiada, karta niezalogowana); opis dla Maksa."""


@dataclass
class Report:
    """Różnice, części niesprawdzone i przerwane żądania; ``checked`` to liczby tego, co narzędzie obejrzało."""

    differences: list[tuple[Part, str]] = field(default_factory=list)
    unchecked: list[tuple[Part, str]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def differ(self, part: Part, what: str) -> None:
        self.differences.append((part, what))

    def lines(self) -> list[str]:
        head = " | ".join(f"{name}: {count}" for name, count in self.checked.items())
        lines = [f"ZGODNOŚĆ ATRAPY EFENIX Z EFENIX | {head}"]
        lines += [f"RÓŻNICA | {part.value} | {what}" for part, what in self.differences]
        lines += [f"NIESPRAWDZONE | {part.value} | {what}" for part, what in self.unchecked]
        lines += [f"ZABLOKOWANE | {request} | żądanie spoza listy dozwolonych, przerwane przed wysłaniem" for request in self.blocked]
        if self.differences or self.unchecked or self.blocked:
            lines.append(f"RÓŻNICE: {len(self.differences)} | NIESPRAWDZONE: {len(self.unchecked)} | ZABLOKOWANE: {len(self.blocked)}")
        else:
            lines.append(OK)
        return lines


def allowed(method: str, url: str, resource_type: str, efenix_host: str) -> bool:
    """Czy narzędzie może wysłać to żądanie: odczyt z ``ALLOWED`` do efenix albo GET pliku strony bez ``.php``."""

    address = urlparse(url)
    if address.netloc == efenix_host and (method, PurePosixPath(address.path).name) in ALLOWED:
        return True
    return method == "GET" and resource_type in PAGE_FILES and not address.path.endswith(".php")


def check(browser: Browser, session: BrowserContext, url: str, *, number: str = "", timeout_ms: int = TIMEOUT_MS) -> Report:
    """Sprawdza efenix pod ``url`` w zalogowanym kontekście ``session``; bez sesji w nowym kontekście ``browser``."""

    if urlparse(url).scheme not in ("http", "https") or PurePosixPath(urlparse(url).path).name != LIST_PAGE:
        raise ToolError(f"--efenix-url to adres listy zleceń efenix kończący się na /{LIST_PAGE}")
    report = Report()
    with _guarded_page(session, url, report, timeout_ms=timeout_ms) as page:
        _check_signed_in(page, url, report, number=number, timeout_ms=timeout_ms)
    context = browser.new_context()
    try:
        _check_logged_out(context, url, report, timeout_ms=timeout_ms)
    finally:
        context.close()
    return report


@contextmanager
def _guarded_page(context: BrowserContext, url: str, report: Report, *, timeout_ms: int) -> Iterator[Page]:
    """Nowa karta w ``context``; na czas bloku każde żądanie całego ``context`` przechodzi przez ``allowed``.

    Blokada jest na kontekście, nie na karcie, bo ``page.route`` nie widzi okien otwartych skryptem strony. Za
    przekierowaniem z odpowiedzi, którą dostaje przeglądarka, przeglądarka podąża bez ``guard`` (Playwright go dla kroków
    przekierowania nie woła), więc dozwolone żądanie narzędzie wysyła samo z ``max_redirects=0`` i odpowiedź
    z przekierowaniem oddaje przeglądarce dopiero wtedy, gdy każdy krok łańcucha jest na liście (``_forbidden_hop``);
    inaczej przerywa żądanie. WebSocket nie łączy się z serwerem (obsługa bez ``connect_to_server``). Na końcu zamyka
    swoją kartę i okna, które otworzyła, a potem zdejmuje blokadę.
    """

    host = urlparse(url).netloc

    def block(method: str, address: str) -> None:
        parsed = urlparse(address)
        name = PurePosixPath(parsed.path).name if parsed.netloc == host else parsed.netloc
        if f"{method} {name}" not in report.blocked:
            report.blocked.append(f"{method} {name}")

    def guard(route: Route) -> None:
        request = route.request
        if not allowed(request.method, request.url, request.resource_type, host):
            block(request.method, request.url)
            route.abort()
            return
        try:
            response = route.fetch(max_redirects=0, timeout=timeout_ms)
            forbidden = _forbidden_hop(route, response, host, timeout_ms=timeout_ms)
        except PlaywrightError:
            route.abort("failed")
            return
        if forbidden is not None:
            block(*forbidden)
            route.abort()
            return
        route.fulfill(response=response)

    def no_socket(socket: WebSocketRoute) -> None:
        block("WebSocket", socket.url)

    ours: list[Page] = []

    def opened(page: Page) -> None:
        if page.opener() in ours:
            ours.append(page)

    context.route("**/*", guard)
    context.route_web_socket("**/*", no_socket)
    context.on("page", opened)
    try:
        ours.append(context.new_page())
        yield ours[0]
    finally:
        for page in reversed(ours):
            page.close()
        context.remove_listener("page", opened)
        context.unroute_all(behavior="ignoreErrors")


def _forbidden_hop(route: Route, response: APIResponse, host: str, *, timeout_ms: int) -> tuple[str, str] | None:
    """Pierwszy krok przekierowania spoza listy (metoda, adres) w łańcuchu od ``response``; ``None``: cały na liście.

    Kroki na liście to odczyty, więc narzędzie wysyła je samo, żeby zobaczyć następny krok; przeglądarka wyśle je drugi
    raz, gdy dostanie przekierowanie. Łańcuch dłuższy niż ``REDIRECT_HOPS`` kroków jest spoza listy.
    """

    request = route.request
    method, address = request.method, request.url
    for _ in range(REDIRECT_HOPS):
        if response.status not in FOLLOWED:
            return None
        address = urljoin(address, response.headers.get("location", ""))
        method = method if response.status in (307, 308) else "GET"
        if not allowed(method, address, request.resource_type, host):
            return method, address
        response = route.fetch(url=address, method=method, max_redirects=0, timeout=timeout_ms)
    return method, address


def _check_signed_in(page: Page, url: str, report: Report, *, number: str, timeout_ms: int) -> None:
    efenix = BrowserEfenix(page, url, timeout_ms=timeout_ms)
    try:
        efenix.open_list()
    except EfenixUnreachable as error:
        raise ToolError("efenix nie odpowiada pod --efenix-url") from error
    except LoggedOut as error:
        raise ToolError("karta Chrome nie jest zalogowana do efenix: zaloguj się kontem taty i uruchom narzędzie jeszcze raz") from error
    except UnexpectedPage as error:
        report.differ(Part.LIST, f"Wycena w efenix nie otwiera listy ({error.part.value})")
    _check_elements(page, Part.LIST, report)
    results = _search(page, number, report, timeout_ms=timeout_ms)
    if results is None:
        report.unchecked += [(Part.ORDER, "bez tabeli wyników nie ma zleceń do otwarcia"), (Part.PRICING, "bez strony zlecenia")]
        return
    rows = _check_results(results, report)
    if not results["rows"]:
        report.unchecked.append((Part.RESULTS, "tabela wyników bez wierszy: podaj --numer, który znajduje zlecenia"))
    if not rows:
        report.unchecked += [(Part.ORDER, "żaden wiersz nie prowadzi do strony zlecenia"), (Part.PRICING, "bez strony zlecenia")]
        return
    _check_listed(efenix, results["headers"], rows[0], report)
    _check_orders(efenix, page, rows, report)


def _search(page: Page, number: str, report: Report, *, timeout_ms: int) -> _Results | None:
    """Szuka ``number`` jak tata (Enter w polu Numer) i czyta tabelę z odpowiedzi ``action_fill_orders.php``."""

    field = page.locator(NUMBER_FIELD)
    if field.count() != 1:
        return None
    field.fill(number)

    def answered(response_url: str, method: str, body: str | None) -> bool:
        searched = parse_qs(body or "", keep_blank_values=True).get("numer")
        return method == "POST" and urlparse(response_url).path.endswith("/" + SEARCH) and searched == [number]

    try:
        with page.expect_response(lambda response: answered(response.url, response.request.method, response.request.post_data), timeout=timeout_ms) as answer:
            field.press("Enter")
    except PlaywrightTimeoutError:
        report.differ(Part.RESULTS, f"Enter w polu Numer nie dał odpowiedzi POST {SEARCH} z polem numer")
        return None
    if 300 <= answer.value.status < 400:
        raise ToolError(LOGGED_OUT_MIDWAY)
    try:
        html = answer.value.text()
    except PlaywrightError:
        report.differ(Part.RESULTS, f"odpowiedź POST {SEARCH} bez treści")
        return None
    results: _Results | None = page.evaluate(_READ_RESULTS, [html, ORDER_PAGE])
    if results is None:
        report.differ(Part.RESULTS, f"odpowiedź {SEARCH} bez tabeli")
    return results


def _check_results(results: _Results, report: Report) -> list[_Row]:
    """Nagłówki i budowa wierszy; wynik to wiersze z jednym linkiem do strony zlecenia, najpierw „Do wyceny”."""

    headers = results["headers"]
    for header in HEADERS.values():
        found = sum(text.casefold().startswith(header) for text in headers)
        if found != 1:
            shown = " / ".join(text or "(pusty)" for text in headers)
            report.differ(Part.RESULTS, f"nagłówek zaczynający się od „{header}”: {found} zamiast 1 (nagłówki: {shown})")
    rows = results["rows"]
    report.checked["wiersze wyników"] = len(rows)
    faults = {
        f"wiersze z inną liczbą komórek niż nagłówków ({len(headers)})": [len(row["cells"]) != len(headers) for row in rows],
        f"wiersze bez jednego linku {ORDER_PAGE}?id=": [len(row["links"]) != 1 for row in rows],
        "wiersze bez statusu w .badge": [not row["badges"] for row in rows],
    }
    for what, bad in faults.items():
        if any(bad):
            report.differ(Part.RESULTS, f"{what}: {sum(bad)} z {len(rows)}")
    linked = [row for row in rows if len(row["links"]) == 1]
    return sorted(linked, key=lambda row: PRICING_STATUS not in row["badges"])


def _order_id(row: _Row) -> str:
    return parse_qs(urlparse(row["links"][0]).query).get("id", [""])[0]


def _check_listed(efenix: BrowserEfenix, headers: Sequence[str], row: _Row, report: Report) -> None:
    """Wycena w efenix szuka numeru wiersza i czyta go tak jak przy zleceniu taty."""

    # Wiersz z inną liczbą komórek niż nagłówków zgłasza już ``_check_results``.
    numbers = [cell for text, cell in zip(headers, row["cells"], strict=False) if text.casefold().startswith(HEADERS["number"])]
    if not numbers or not numbers[0]:
        report.unchecked.append((Part.RESULTS, "odczyt wiersza przez Wycenę w efenix: wiersz bez Numer dokumentu"))
        return
    try:
        listed = [order for order in efenix.search(numbers[0]) if order.order_id == _order_id(row)]
    except UnexpectedPage as error:
        report.differ(Part.RESULTS, f"Wycena w efenix nie czyta wiersza ({error.part.value})")
        return
    except LoggedOut as error:
        raise ToolError(LOGGED_OUT_MIDWAY) from error
    if len(listed) != 1:
        report.differ(Part.RESULTS, f"szukanie numeru wiersza daje {len(listed)} wierszy tego zlecenia zamiast 1")
        return
    order = listed[0]
    for missing, what in ((order.realizator is None, "loginu realizatora „(login)” w kolumnie Wykonawca"), (not order.address, "Dane adresowe")):
        if missing:
            report.differ(Part.RESULTS, f"Wycena w efenix nie czyta z wiersza {what}")


def _check_orders(efenix: BrowserEfenix, page: Page, rows: Sequence[_Row], report: Report) -> None:
    """Otwiera zlecenia z listy, aż sprawdzi budowę strony zlecenia i znajdzie pustą datę wykonania."""

    opened = report.checked["otwarte zlecenia"] = 0
    unread: Counter[str] = Counter()
    pricing_checked = empty_found = False
    for row in rows[:ORDERS_TO_OPEN]:
        if pricing_checked and empty_found:
            break
        order = ListedOrder(number="", status="", realizator=None, address="", order_id=_order_id(row))
        opened += 1
        try:
            day = efenix.execution_date(order)
        except LoggedOut as error:
            raise ToolError(LOGGED_OUT_MIDWAY) from error
        except UnexpectedPage:
            unread[_day_shape(page)] += 1
        else:
            empty_found = empty_found or day is None
        if not pricing_checked:
            _check_elements(page, Part.ORDER, report)
            _check_positions(page, report)
            pricing_checked = True
    report.checked["otwarte zlecenia"] = opened
    for shape, count in unread.items():
        report.differ(Part.ORDER, f"Wycena w efenix nie czyta daty wykonania {EXECUTION_DATE} w postaci {shape}: {count} z {opened}")
    if not empty_found:
        report.unchecked.append((Part.ORDER, f"postać pustej daty wykonania: żadne z {opened} otwartych zleceń nie ma pustej {EXECUTION_DATE}"))


def _day_shape(page: Page) -> str:
    executed = page.locator(EXECUTION_DATE)
    if executed.count() != 1:
        return f"bez jednego {EXECUTION_DATE}"
    text = " ".join(executed.inner_text().split())
    if not text:
        return "pusta"
    # Postać bez treści: cyfra to 9, a litera to a.
    return "„" + re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "a", text)) + "”"


def _check_elements(page: Page, part: Part, report: Report) -> None:
    for element in (element for element in ELEMENTS if element.part is part):
        found = page.locator(element.selector).count()
        if found == 0 or (found > 1 and not element.many):
            report.differ(part, f"{element.name} ({element.selector}): {found} zamiast {'co najmniej 1' if element.many else '1'}")


def _check_positions(page: Page, report: Report) -> None:
    """Karty pozycji równe pozycjom Atrapy efenix: te same kody, rodzaj karty i ceny jednostkowe jako liczby."""

    cards: list[_Card] = page.evaluate(_READ_POSITIONS, PRICING_CARD)
    found = dict(position for card in cards if (position := _position(card)) is not None)
    report.checked["pozycje wyceny"] = len(found)
    if broken := len(cards) - len(found):
        report.differ(
            Part.PRICING,
            f"karty bez jednego pola Ilość z ceną w tekście albo jednego pola ceny wpisywanej z kodem INDEKS_NNN_NNN: {broken} z {len(cards)}",
        )
    for code in sorted(POSITIONS.keys() - found.keys()):
        report.differ(Part.PRICING, f"{code}: jest w Atrapie ({_price(POSITIONS[code])}), nie ma go w efenix")
    for code in sorted(found.keys() - POSITIONS.keys()):
        report.differ(Part.PRICING, f"{code}: jest w efenix ({_price(found[code])}), nie ma go w Atrapie")
    for code in sorted(found.keys() & POSITIONS.keys()):
        if not _same_price(found[code], POSITIONS[code]):
            report.differ(Part.PRICING, f"{code}: w efenix {_price(found[code])}, w Atrapie {_price(POSITIONS[code])}")


def _position(card: _Card) -> tuple[str, str | None] | None:
    """Kod i cena karty; ``None`` jako cena to karta z ceną wpisywaną, a karta w innym kształcie to ``None``."""

    match card["quantity"], card["price"], card["shown"]:
        case [code], [], [shown]:
            position: tuple[str, str | None] = (code, shown)
        case [], [code], []:
            position = (code, None)
        case _:
            return None
    return position if POSITION_CODE.fullmatch(position[0]) else None


def _price(price: str | None) -> str:
    return "cena wpisywana" if price is None else f"cena {price}"


def _same_price(shown: str | None, expected: str | None) -> bool:
    if shown is None or expected is None:
        return shown is expected
    return _amount(shown) == _amount(expected)


def _amount(text: str) -> Decimal | str:
    try:
        return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return text


def _check_logged_out(context: BrowserContext, url: str, report: Report, *, timeout_ms: int) -> None:
    """Lista i szukanie bez sesji przekierowują na stronę logowania, a ta ma pola formularza logowania."""

    host = urlparse(url).netloc
    probes: tuple[tuple[str, str, Callable[[], int | str]], ...] = (
        ("GET", url, lambda: _redirect(context.request.get(url, max_redirects=0, timeout=timeout_ms).headers)),
        (
            "POST",
            urljoin(url, SEARCH),
            lambda: _redirect(context.request.post(urljoin(url, SEARCH), form={"numer": ""}, max_redirects=0, timeout=timeout_ms).headers),
        ),
    )
    for method, address, probe in probes:
        if not allowed(method, address, "fetch", host):
            raise ValueError(f"{method} {PurePosixPath(urlparse(address).path).name} nie jest na liście dozwolonych")
        if probe() != LOGIN_PAGE:
            report.differ(Part.LOGGED_OUT, f"{method} {PurePosixPath(urlparse(address).path).name} bez sesji nie przekierowuje na {LOGIN_PAGE}")
    with _guarded_page(context, url, report, timeout_ms=timeout_ms) as page:
        page.goto(urljoin(url, LOGIN_PAGE), wait_until="load", timeout=timeout_ms)
        _check_elements(page, Part.LOGIN, report)


def _redirect(headers: dict[str, str]) -> str:
    return PurePosixPath(urlparse(headers.get("location", "")).path).name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efenix-url", required=True, help=f"Adres listy zleceń efenix (…/{LIST_PAGE}).")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222", help="Adres zdalnego debugowania Chrome (domyślnie %(default)s).")
    parser.add_argument("--numer", default="", help="Co wpisać w pole Numer, żeby lista pokazała zlecenia (domyślnie puste pole).")
    parser.add_argument("--limit-ms", type=int, default=TIMEOUT_MS, help="Limit czekania na stronę i odpowiedź (ms).")
    args = parser.parse_args(argv)
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(args.cdp)
            except PlaywrightError as error:
                raise ToolError(f"nie ma Chrome ze zdalnym debugowaniem pod --cdp {args.cdp}") from error
            if not browser.contexts:
                raise ToolError("Chrome pod --cdp nie ma okna z sesją efenix")
            report = check(browser, browser.contexts[0], args.efenix_url, number=args.numer, timeout_ms=args.limit_ms)
    except ToolError as error:
        print(f"BŁĄD | {error}", file=sys.stderr)
        return 1
    lines = report.lines()
    print("\n".join(lines))
    return 0 if lines[-1] == OK else 2


if __name__ == "__main__":
    sys.exit(main())
