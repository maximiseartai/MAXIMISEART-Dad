"""Porównuje budowę stron efenix z Atrapą efenix samym odczytem; uruchom przed pierwszą Wyceną w efenix i po Zgłoszeniu z Zatrzymania okna efenix.

Narzędzie dla Maksa, poza CI (ADR 0024). Łączy się z Chrome, w którym Maks jest zalogowany do efenix kontem taty, i
sprawdza budowę, której używa Wycena w efenix i którą odtwarza Atrapa efenix (``tests/fixtures/atrapa_efenix.py``).
Żadna strona efenix nie działa przy tym w przeglądarce: każde żądanie do efenix narzędzie wysyła samo, z ciasteczkami
sesji domyślnego kontekstu Chrome (``contexts[0].request``, bez kart i bez skryptów), tylko z listy ``ALLOWED``
porównywanej po pełnej ścieżce i hoście ``--efenix-url``, i nigdy nie podąża za przekierowaniem: przekierowanie na
``page_login.php`` i odpowiedź szukania z ostrzeżeniem o wygasłej sesji (``efenix_browser.SearchWarning``) to brak
sesji, a inne przekierowanie to różnica. HTML z odpowiedzi składa parserem przeglądarki we własnej karcie
w osobnym kontekście bez ciasteczek, z wyłączonym JavaScriptem i service workerami, z której nie wychodzi żadne żądanie
(obraz, styl, ramka, przejście, prefetch; ``parser_page``). Kart taty nie dotyka. Sprawdza:

- lista zleceń: elementy ``efenix_browser.LIST_ELEMENTS`` (pole ``Numer``) i skrypt ``js/index.js``, który lista ładuje,
  z nazwami ``efenix_browser.LIST_SCRIPT_USES`` (Enter w polu ``Numer`` wysyła ``action_fill_orders.php`` z polem
  ``numer``);
- tabela wyników: szukanie ``--numer`` tak jak skrypt listy w domyślnym stanie listy (POST ``action_fill_orders.php``
  z każdym polem, które wysyła wtedy skrypt listy, bez ``xrodzaj``, z pustymi filtrami, pierwszym ``sortowanie`` i
  ``na_stronie`` jak w domyślnym ustawieniu listy), a odpowiedź czyta
  ``efenix_browser.read_results``, odczyt Wyceny w efenix, ze statusem, loginem realizatora i ``Dane adresowe`` w każdym
  wierszu, które reguła adresu (``efenix_address.readable``) rozbiera na ulicę, numer domu i lokal, bo z tych części
  Logi Uruchomienia mówią, czym różni się adres (przy błędzie odczytu nagłówki ``efenix_browser.HEADERS``, liczba komórek, link ``page_order_edit.php?id=`` i status
  w ``.badge``); ostrzeżenie „Nie znaleziono pasujących wyników”, którym efenix odpowiada na numer, którego nie zna,
  Wycena czyta jak tabelę bez wierszy, więc ``--numer`` takiego numeru sprawdza i tę odpowiedź;
- strona zlecenia (do ``ORDERS_TO_OPEN`` zleceń z tabeli, najpierw „Do wyceny”, aż znajdzie pustą datę wykonania):
  ``efenix_browser.read_order`` (data wykonania ``RRRR-MM-DD`` albo pusta, kwota końcowa, pola Ilość), a na pierwszym
  zleceniu elementy ``efenix_browser.ORDER_ELEMENTS`` (okno daty wykonania, przycisk i okno Emmetta; przycisk Emmetta
  widoczny w samym HTML, bez stylów efenix, a propozycja w oknie Emmetta ``#emmett-propozycja`` pusta, bez elementu i
  tekstu, jak w Atrapie, zanim skrypt strony włoży do niej propozycję), przyciski Przekazania do akceptacji i anulowania, które ma Atrapa, skrypt
  ``js/page_order_edit.js`` (pod adresem z listy ``ALLOWED``) z nazwami ``efenix_browser.ORDER_SCRIPT_USES``
  (pickadate z ``onSet``, „Potwierdź” daty, Emmett, zapis ilości z ``price_all``) i karty pozycji
  ``.card.rounded-lg.kolorek``: karta z polem Ilość ma cenę w tekście ``.col-sm-1.mt-2 > span.text-default > small``,
  a karta z ceną wpisywaną samo pole ``input.wycena-cena``; każdy kod ``INDEKS_NNN_NNN`` jest pozycją Atrapy
  (``atrapa_efenix.CATALOG``) z tym samym rodzajem karty, przy czym strona może mieć tylko część pozycji Atrapy, jak
  zlecenia efenix z mniejszą liczbą pozycji wyceny, a strona bez żadnej karty pozycji to część niesprawdzona; cena
  pozycji z przypisania kolumn (``efenix_positions.POSITION_OF_COLUMN``) jest równa kosztowi jej kolumny w wierszu 14 Wzorca pliku zbiorczego, bo z kosztów tego wiersza liczy się ``Kwota`` (AU),
  z którą Wycena w efenix porównuje kwotę końcową efenix;
- bez sesji (żądania bez ciasteczek, więc sesja taty trwa): lista przekierowuje na ``page_login.php``, szukanie
  odpowiada 2xx bez przekierowania samym ostrzeżeniem o wygasłej sesji, które rozpoznaje Wycena w efenix
  (``efenix_browser.SearchWarning``), a strona logowania ma formularz ``action_login.php`` z polami
  ``field_signum``, ``field_password`` i ``fingerprint``.

Skryptów stron narzędzie nie uruchamia, więc ich działania nie widzi: sprawdza tylko, że skrypt ma nazwy, na których
polega okno Wyceny w efenix. Przycisku kalendarza daty wykonania (``#button-calendar``) nie sprawdza: okno klika go tylko
przy pustej dacie wykonania, a efenix pokazuje go najpewniej tylko wtedy, więc wynik zawsze ma linię ``NIESPRAWDZONE``
z prośbą o sprawdzenie ręczne (``DATE_BUTTON_BY_HAND``).

Propozycji Emmetta narzędzie samo nie czyta: ``action_fill_emmett.php`` nie jest na liście ``ALLOWED``, bo nic nie
pokazuje, co robi z nim serwer efenix. Skrypt strony zlecenia efenix (rekonesans z 1.11.2026) wysyła w nim tylko
``order_id`` z przycisku Emmetta, odpowiedź 2xx wkłada do ``#emmett-propozycja`` i pokazuje okno Emmetta, a jego treść
mówi, że wycenę czyści dopiero „Załaduj do zlecenia”; czy serwer przy propozycji czegoś nie zapisuje, z tego nie wynika.
Bez pliku ``--propozycja`` wynik ma więc zawsze linię ``NIESPRAWDZONE`` o budowie propozycji (``PROPOSAL_BY_HAND``).
Plik zapisuje człowiek, jeśli Maks zdecyduje, że może kliknąć przycisk Emmetta na zleceniu taty (#953): kliknięcie
wysyła to samo żądanie, które okno Wyceny w efenix wysyła przed każdym „Załaduj do zlecenia”, okno Emmetta pokazuje
propozycję, a w DevTools Chrome (prawy klik na propozycji, „Zbadaj”) element ``<div id="emmett-propozycja">`` kopiuje
Copy → Copy outerHTML i zapisuje schowek do pliku poleceniem ``pbpaste > ~/.t3/notes/953/propozycja.html`` (nie przez
TextEdit, który zapisuje RTF); okno zamyka „Zamknij”, nigdy „Załaduj do zlecenia”. Narzędzie składa plik w swojej karcie
bez skryptów i sieci tak, jak skrypt strony efenix odpowiedź: jako treść elementu, więc ``<script>``, ``<style>`` czy
``<meta>`` z początku pliku zostają w propozycji. Czyta go od elementu ``#emmett-propozycja``, a plik bez niego, np. sama
odpowiedź z zakładki Network, w całości, więc obie postacie tej samej propozycji dają ten sam wynik. Budowę porównuje z propozycją Atrapy
(``atrapa_efenix.emmett_proposal``): każdy element (nazwy i klasy od propozycji), tekst i atrybut z maską (kod pozycji
to ``INDEKS_NNN_NNN``, ciąg cyfr 9, ciąg liter a), którego nie ma po drugiej stronie, to różnica, a liczba kodów pozycji
w propozycji stoi w nagłówku wyniku. Propozycja, która nic nie pokazuje (jak w oknie Emmetta, gdy Emmett nic nie
proponuje), to część niesprawdzona.

Uruchomienie: Chrome z osobnym profilem i zdalnym debugowaniem (macOS, Linux, Windows), w nim logowanie do efenix kontem
taty, potem narzędzie, z ``--propozycja`` tylko z plikiem propozycji:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.efenix-zgodnosc"
    google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.efenix-zgodnosc"
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\\.efenix-zgodnosc"
    .venv/bin/python tools/zgodnosc_efenix.py --efenix-url <adres listy zleceń, …/index.php> --cdp http://127.0.0.1:9222 [--numer <numer>] [--propozycja <plik>]

Pomiar z propozycją (#953), gdy plik jest już zapisany:

    .venv/bin/python tools/zgodnosc_efenix.py --efenix-url <adres listy zleceń, …/index.php> --propozycja ~/.t3/notes/953/propozycja.html

Czasu przebiegu w prawdziwym efenix nikt nie zmierzył: narzędzie wysyła po kolei najwyżej 17 odczytów (lista, jej
skrypt, szukanie, do ``ORDERS_TO_OPEN`` stron zleceń, skrypt strony zlecenia i trzy odczyty bez sesji), więc trwa mniej
więcej tyle, ile tyle odpowiedzi efenix (na Atrapie 0,98 s: ``pytest --durations`` testu zgodnej Atrapy 5.11.2026), a odpowiedź, która nie przyjdzie w ``--limit-ms``
(domyślnie 30 s), kończy je kodem 1.

Na czas sprawdzania w Chrome otwiera się okno narzędzia, w którym widać złożony HTML stron bez stylów i skryptów;
narzędzie zamyka je na końcu. Wzorzec pliku zbiorczego to domyślnie ten z konfiguracji narzędzia
(``config/Wzorzec pliku zbiorczego.xlsx``, jak w Centrum rozliczeń), a inny podaje ``--wzorzec``.

Wynik (na stdout): linie ``RÓŻNICA | <część> | <co>`` i ``NIESPRAWDZONE | <część> | <co>``, na końcu liczby jednych i
drugich. Kod 0: bez różnic, a niesprawdzone są tylko przycisk kalendarza i, bez ``--propozycja``, budowa propozycji
Emmetta; kod 2: różnice albo inne części niesprawdzone. Wynik nie zawiera numerów zleceń, adresów, loginów ani cen: tylko nazwy elementów, liczby, kody pozycji
z kolumnami, postać daty i kwoty (cyfry jako ``9``) i budowę propozycji Emmetta z maską. Kod 1: brak Chrome pod
``--cdp``, nieczytelny Wzorzec albo plik ``--propozycja``, efenix nie odpowiada albo Chrome nie jest zalogowany; opis na
stderr.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import enum
from pathlib import Path
import re
import socket
import sys
from typing import Final, TypedDict, cast
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import APIRequestContext, Browser, Page, ProxySettings, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Korzeń repozytorium dla Atrapy efenix (``tests.fixtures``), z której narzędzie bierze kody pozycji i pola szukania.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozliczenia import workbook_files
from rozliczenia.efenix_address import readable
from rozliczenia.collective_preparation import default_collective_template_path
from rozliczenia.efenix_browser import (
    AMOUNT,
    EXECUTION_DATE,
    HEADERS,
    LIST_ELEMENTS,
    LIST_SCRIPT_USES,
    LOGIN_PAGE,
    ORDER_ELEMENTS,
    ORDER_PAGE,
    ORDER_SCRIPT_USES,
    QUANTITY,
    SEARCH,
    TIMEOUT_MS,
    PageElement,
    ScriptUse,
    SearchWarning,
    read_order,
    read_results,
    search_warning,
)
from rozliczenia.efenix_checks import PRICING_STATUS
from rozliczenia.efenix_positions import POSITION_OF_COLUMN
from rozliczenia.efenix_pricing import UnexpectedPage
from rozliczenia.workbook_files import WorkbookError

from tests.fixtures.atrapa_efenix import CATALOG, LIST_ROWS_PER_PAGE, LIST_SEARCH_FIELDS, emmett_proposal

LIST_PAGE: Final = "index.php"
LIST_SCRIPT: Final = "js/index.js"
ORDER_SCRIPT: Final = "js/page_order_edit.js"
# Jedyne żądania do efenix, które narzędzie wysyła: (metoda, ścieżka względem katalogu ``--efenix-url``). Zapis ilości,
# Emmett, data wykonania, zmiana statusu, Przekazanie do akceptacji, anulowanie, logowanie i wylogowanie nie są na liście.
ALLOWED: Final = frozenset(
    {
        ("GET", LIST_PAGE),
        ("GET", LIST_SCRIPT),
        ("POST", SEARCH),
        ("GET", ORDER_PAGE),
        ("GET", ORDER_SCRIPT),
        ("GET", LOGIN_PAGE),
    }
)
# Szukanie z pola Numer tak, jak wysyła je skrypt listy efenix (``js/index.js``) w domyślnym stanie listy, który
# odtwarza Atrapa: każde jego pole w jego kolejności, bez ``xrodzaj``, którego skrypt wtedy nie wysyła, z pustymi
# filtrami, pierwszą opcją ``sortowanie`` i liczbą wierszy ``na_stronie`` z domyślnego ustawienia listy. Pusty
# ``xrodzaj`` daje w efenix zero wyników, a brak ``na_stronie`` stronę błędu bazy danych (#822). ``asp`` zostaje pusty
# zamiast nazwy ASP konta taty: w pomiarze z 4.11.2026 pusty nie zmienił wyniku.
SEARCH_FORM: Final = dict.fromkeys(LIST_SEARCH_FIELDS, "") | {
    "rodzaj": "szukanie",
    "strona": "1",
    "na_stronie": LIST_ROWS_PER_PAGE,
    "sortowanie": "1",
}
POSITION_CODE: Final = re.compile(r"INDEKS_\d{3}_\d{3}")
# Wiersz Wzorca pliku zbiorczego z kosztem jednej sztuki każdej pozycji Ilości usług (GLOSSARY: Ilości usług); silnik go
# nie czyta, więc ``workbook_files`` nie ma go w układzie arkusza.
COST_ROW: Final = 14
ORDERS_TO_OPEN: Final = 10
NOT_SIGNED_IN: Final = "Chrome nie jest zalogowany do efenix: zaloguj się kontem taty i uruchom narzędzie jeszcze raz"
LOGGED_OUT_MIDWAY: Final = "efenix wylogował w trakcie sprawdzania: zaloguj się i uruchom narzędzie jeszcze raz"


class Part(enum.Enum):
    """Część efenix, której dotyczy linia wyniku."""

    LIST = "lista zleceń"
    RESULTS = "tabela wyników"
    ORDER = "strona zlecenia"
    PRICING = "pozycje wyceny"
    LOGGED_OUT = "bez sesji"
    LOGIN = "strona logowania"
    PROPOSAL = "propozycja Emmetta"


# Elementy, których Wycena w efenix nie używa, a Atrapa ma: przyciski, których okno nie może kliknąć, i formularz
# logowania, w którym tata loguje się sam.
UNUSED_ORDER_ELEMENTS: Final = (
    PageElement("przycisk Przekazania do akceptacji", "#button_forward_to_accept"),
    PageElement("przycisk anulowania", "#button_forward_to_cancel"),
)
LOGIN_ELEMENTS: Final = (
    PageElement("formularz logowania", 'form[action$="action_login.php"]'),
    PageElement("pole loginu", "input#field_signum"),
    PageElement("pole hasła", "input#field_password"),
    PageElement("pole fingerprint", 'input[name="fingerprint"]'),
)
PRICING_CARD: Final = ".card.rounded-lg.kolorek"
# Propozycja w oknie Emmetta z ``ORDER_ELEMENTS``: element, do którego skrypt strony wkłada odpowiedź
# ``action_fill_emmett.php``; w pliku ``--propozycja`` sam element, bez okna Emmetta.
PROPOSAL: Final = next(element.selector for element in ORDER_ELEMENTS if element.name == "propozycja w oknie Emmetta")
PROPOSAL_ALONE: Final = PROPOSAL.split()[-1]
CODE_TOKEN: Final = "INDEKS_NNN_NNN"
# Część, której narzędzie nie sprawdza nigdy, a Maks sprawdza ręcznie; zawsze w wyniku jako ``NIESPRAWDZONE``.
DATE_BUTTON_BY_HAND: Final = (
    Part.ORDER,
    "przycisk kalendarza daty wykonania nie jest sprawdzany: sprawdź ręcznie w efenix na zleceniu "
    f"„{PRICING_STATUS}” bez daty wykonania, że jest przycisk otwierający okno wyboru daty",
)
# Budowa propozycji Emmetta bez pliku ``--propozycja``: narzędzie nie wysyła ``action_fill_emmett.php``.
PROPOSAL_BY_HAND: Final = (
    Part.PROPOSAL,
    "budowa propozycji Emmetta nie jest sprawdzana: narzędzie nie wysyła action_fill_emmett.php; zmierz ją plikiem"
    " --propozycja z propozycją zapisaną w Chrome (--help)",
)

# Tabela odpowiedzi szukania przeczytana w ``<template>``, w którym nic nie biegnie i nic się nie wczytuje. Linki
# (identyfikatory zleceń) zostają w pamięci narzędzia: służą do otwierania zleceń, nie trafiają do wyniku.
_READ_TABLE: Final = """([html, orderPage]) => {
    const template = document.createElement('template');
    template.innerHTML = html;
    const table = template.content.querySelector('table');
    if (!table) return null;
    const text = (element) => {
        const copy = element.cloneNode(true);
        copy.querySelectorAll('br').forEach((br) => br.replaceWith(' '));
        return copy.textContent.replace(/\\s+/g, ' ').trim();
    };
    return {
        headers: [...table.querySelectorAll('thead th')].map(text),
        rows: [...table.querySelectorAll('tbody tr')].map((row) => ({
            cells: row.querySelectorAll('td').length,
            links: [...row.querySelectorAll(`a[href*="${orderPage}?id="]`)].map((link) => link.getAttribute('href')),
            badges: [...row.querySelectorAll('td .badge')].map(text),
        })),
    };
}"""
# Budowa jedynego elementu ``selector`` (z ``within``: w elemencie o tym ``id``, a bez ``selector`` w nim cały ``within``)
# bez treści do maskowania: każdy element w nim (ścieżka nazw i klas od niego, ``null``, ``null``), każdy tekst inny niż
# białe znaki (ścieżka elementu, ``null``, tekst) i każdy atrybut poza ``class`` (ścieżka, nazwa, wartość); ``null``, gdy
# elementu nie ma dokładnie raz, a ``within`` nie ma. Pusta lista to element, który nic nie pokazuje: bez elementu i bez
# tekstu, jak w ``load_emmett``.
_READ_SKELETON: Final = """([selector, within]) => {
    const scope = within ? document.getElementById(within) : document;
    const matching = scope.querySelectorAll(selector);
    const root = matching.length === 1 ? matching[0] : within ? scope : null;
    if (!root) return null;
    const name = (element) => [element.localName, ...[...element.classList].sort()].join('.');
    const found = [];
    const walk = (node, path) => {
        for (const child of node.childNodes) {
            if (child.nodeType === Node.TEXT_NODE && child.textContent.trim() !== '') {
                found.push([path, null, child.textContent]);
            } else if (child.nodeType === Node.ELEMENT_NODE) {
                const inner = path ? `${path} > ${name(child)}` : name(child);
                found.push([inner, null, null]);
                for (const attribute of child.attributes) {
                    if (attribute.name !== 'class') found.push([inner, attribute.name, attribute.value]);
                }
                walk(child, inner);
            }
        }
    };
    walk(root, '');
    return found;
}"""
# Plik ``--propozycja`` i propozycja Atrapy złożone jak w efenix: skrypt strony zlecenia wkłada odpowiedź
# ``action_fill_emmett.php`` jako treść ``#emmett-propozycja`` (jQuery ``.html()``), więc ``<script>``, ``<style>``,
# ``<meta>``, ``<link>`` i ``<title>`` z jej początku zostają w propozycji, a nie trafiają do ``<head>``, jak przy
# składaniu całej strony. Pojemnik ma własne ``id``, żeby skopiowany element ``#emmett-propozycja`` był w nim raz.
_COMPOSE_PROPOSAL: Final = """([within, html]) => {
    const box = document.createElement('div');
    box.id = within;
    document.body.replaceChildren(box);
    box.innerHTML = html;
}"""
_PROPOSAL_BOX: Final = "zgodnosc-plik-propozycji"
# Karta pozycji: ``id`` pól Ilość, ``id`` pól ceny wpisywanej i ceny z tekstu karty.
_READ_CARDS: Final = """([card, quantity]) => [...document.querySelectorAll(card)].map((element) => ({
    quantity: [...element.querySelectorAll(quantity)].map((input) => input.id),
    price: [...element.querySelectorAll('input.wycena-cena')].map((input) => input.id),
    shown: [...element.querySelectorAll('.col-sm-1.mt-2 > span.text-default > small')].map((small) => small.textContent.trim()),
}))"""


class _Row(TypedDict):
    cells: int
    links: list[str]
    badges: list[str]


class _Table(TypedDict):
    headers: list[str]
    rows: list[_Row]


class _Card(TypedDict):
    quantity: list[str]
    price: list[str]
    shown: list[str]


class ToolError(Exception):
    """Narzędzie nie może sprawdzić efenix (brak Chrome, Wzorca, odpowiedzi efenix albo sesji); opis dla Maksa."""


@dataclass
class Report:
    """Różnice i części niesprawdzone; ``checked`` to liczby tego, co narzędzie obejrzało, a ``proposal_read``: czy
    narzędzie przeczytało propozycję Emmetta z pliku ``--propozycja``."""

    differences: list[tuple[Part, str]] = field(default_factory=list)
    unchecked: list[tuple[Part, str]] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)
    proposal_read: bool = False

    def differ(self, part: Part, what: str) -> None:
        self.differences.append((part, what))

    def lines(self) -> list[str]:
        """Wynik dla Maksa; po częściach niesprawdzonych stoi zawsze ``DATE_BUTTON_BY_HAND``, a bez pliku
        ``--propozycja`` także ``PROPOSAL_BY_HAND``."""

        head = " | ".join(f"{name}: {count}" for name, count in self.checked.items())
        unchecked = [*self.unchecked, DATE_BUTTON_BY_HAND, *([] if self.proposal_read else [PROPOSAL_BY_HAND])]
        lines = [f"ZGODNOŚĆ ATRAPY EFENIX Z EFENIX | {head}"]
        lines += [f"RÓŻNICA | {part.value} | {what}" for part, what in self.differences]
        lines += [f"NIESPRAWDZONE | {part.value} | {what}" for part, what in unchecked]
        lines.append(f"RÓŻNICE: {len(self.differences)} | NIESPRAWDZONE: {len(unchecked)}")
        return lines


def allowed(method: str, url: str, efenix_url: str) -> bool:
    """Czy narzędzie może wysłać to żądanie: ``ALLOWED`` po pełnej ścieżce w katalogu ``efenix_url``, na jego hoście."""

    address, efenix = urlparse(url), urlparse(efenix_url)
    folder = efenix.path.rpartition("/")[0] + "/"
    if (address.scheme, address.netloc) != (efenix.scheme, efenix.netloc) or address.params or address.fragment:
        return False
    return address.path.startswith(folder) and (method, address.path.removeprefix(folder)) in ALLOWED


@dataclass(frozen=True)
class _Answer:
    """Odpowiedź efenix: kod, adres przekierowania (``None``: bez przekierowania) i treść."""

    status: int
    location: str | None
    text: str


class _Efenix:
    """Odczyty efenix z ``ALLOWED`` wysyłane przez ``request`` bez podążania za przekierowaniem."""

    def __init__(self, request: APIRequestContext, url: str, *, timeout_ms: int) -> None:
        self._request = request
        self.url = url
        self._timeout_ms = timeout_ms

    def address(self, name: str, **query: str) -> str:
        return urljoin(self.url, name + (f"?{urlencode(query)}" if query else ""))

    def name(self, url: str) -> str:
        """Ścieżka adresu względem katalogu efenix (adres innego hosta: sam host), bez zapytania."""

        address, efenix = urlparse(url), urlparse(self.url)
        if address.netloc != efenix.netloc:
            return address.netloc
        return address.path.removeprefix(efenix.path.rpartition("/")[0] + "/")

    def get(self, url: str) -> _Answer:
        return self._send("GET", url, {})

    def post(self, url: str, form: Mapping[str, str]) -> _Answer:
        return self._send("POST", url, form)

    def to_login(self, answer: _Answer) -> bool:
        return answer.location is not None and urlparse(answer.location).path == urlparse(self.address(LOGIN_PAGE)).path

    def _send(self, method: str, url: str, form: Mapping[str, str]) -> _Answer:
        if not allowed(method, url, self.url):
            raise ValueError(f"{method} {self.name(url)} nie jest na liście dozwolonych żądań")
        try:
            response = self._request.fetch(
                url,
                method=method,
                form=dict(form) if method == "POST" else None,
                max_redirects=0,
                timeout=self._timeout_ms,
            )
        except PlaywrightError as error:
            raise ToolError("efenix nie odpowiada pod --efenix-url") from error
        try:
            location = urljoin(url, response.headers["location"]) if 300 <= response.status < 400 and "location" in response.headers else None
            return _Answer(response.status, location, "" if location is not None else response.text())
        finally:
            response.dispose()


def template_costs(path: Path) -> dict[str, Decimal | None]:
    """Koszt z wiersza 14 Wzorca pliku zbiorczego w każdej kolumnie przypisania kolumn; ``None``: komórka bez liczby."""

    try:
        content = workbook_files.template_content(path)
        with workbook_files.open_workbook(path, content, read_only=True) as workbook:
            sheet = cast(Worksheet, workbook.active)  # tylko do odczytu: ReadOnlyWorksheet
            row = next(sheet.iter_rows(min_row=COST_ROW, max_row=COST_ROW, values_only=True), ())
    except WorkbookError as error:
        raise ToolError(f"Wzorzec pliku zbiorczego {path}: {error.problem.value}") from error
    costs: dict[str, Decimal | None] = {}
    for column in POSITION_OF_COLUMN:
        index = column_index_from_string(column) - 1
        value = row[index] if index < len(row) else None
        costs[column] = Decimal(str(value)) if isinstance(value, int | float | Decimal) and not isinstance(value, bool) else None
    return costs


def check(
    signed_in: _Efenix,
    signed_out: _Efenix,
    page: Page,
    costs: Mapping[str, Decimal | None],
    *,
    number: str = "",
    proposal: str | None = None,
) -> Report:
    """Sprawdza efenix odczytami ``signed_in`` (sesja taty) i ``signed_out`` (bez ciasteczek); HTML składa w ``page``.

    ``proposal``: HTML propozycji Emmetta z pliku ``--propozycja``, który narzędzie porównuje z propozycją Atrapy.
    """

    report = Report()
    _check_signed_in(signed_in, page, costs, report, number=number)
    _check_signed_out(signed_out, page, report)
    if proposal is not None:
        _check_proposal(page, proposal, report)
    return report


@contextmanager
def parser_page(browser: Browser, *, timeout_ms: int) -> Iterator[Page]:
    """Karta w nowym kontekście bez ciasteczek, JavaScriptu i service workerów, z której nie wychodzi żadne żądanie.

    Przejście (``<meta http-equiv="refresh">``, ramka) dostaje od narzędzia odpowiedź 204, więc karta zostaje przy
    złożonym HTML, a każde inne żądanie (obraz, styl, skrypt) narzędzie przerywa. Żądania, których przechwytywanie
    Playwrighta nie widzi (``<link rel="prefetch">`` wysyła proces przeglądarki), idą przez proxy kontekstu na port, który
    narzędzie zajmuje bez nasłuchu, więc połączenie jest odrzucane (adresy lokalne Playwright też kieruje przez proxy).
    """

    with socket.socket() as dead:
        dead.bind(("127.0.0.1", 0))
        proxy: ProxySettings = {"server": f"http://127.0.0.1:{dead.getsockname()[1]}"}
        context = browser.new_context(java_script_enabled=False, service_workers="block", proxy=proxy)
        try:
            context.route("**/*", _stay)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            yield page
        finally:
            context.close()


def _stay(route: Route) -> None:
    if route.request.is_navigation_request():
        route.fulfill(status=204)
    else:
        route.abort()


def _show(page: Page, html: str) -> None:
    page.set_content(html, wait_until="domcontentloaded")


def _text(efenix: _Efenix, answer: _Answer, what: str, part: Part, report: Report) -> str | None:
    """Treść odpowiedzi 2xx; przekierowanie na stronę logowania kończy narzędzie, a inne i inny kod to różnica."""

    if efenix.to_login(answer):
        raise ToolError(LOGGED_OUT_MIDWAY)
    if answer.location is not None:
        report.differ(part, f"{what} przekierowuje na {efenix.name(answer.location)}")
    elif not 200 <= answer.status < 300:
        report.differ(part, f"{what}: odpowiedź {answer.status}")
    else:
        return answer.text
    return None


def _check_signed_in(efenix: _Efenix, page: Page, costs: Mapping[str, Decimal | None], report: Report, *, number: str) -> None:
    listing = efenix.get(efenix.url)
    if efenix.to_login(listing):
        raise ToolError(NOT_SIGNED_IN)
    html = _text(efenix, listing, f"GET {LIST_PAGE}", Part.LIST, report)
    if html is None:
        report.unchecked.append((Part.RESULTS, "bez listy zleceń"))
        return
    _show(page, html)
    _check_elements(page, Part.LIST, LIST_ELEMENTS, report)
    _check_script(efenix, page, efenix.url, Part.LIST, LIST_SCRIPT, LIST_SCRIPT_USES, report)
    answer = efenix.post(efenix.address(SEARCH), {**SEARCH_FORM, "numer": number})
    results = _text(efenix, answer, f"POST {SEARCH}", Part.RESULTS, report)
    table: _Table | None = None
    if results is not None:
        match search_warning(page, results):
            case SearchWarning.SESSION_EXPIRED:
                raise ToolError(LOGGED_OUT_MIDWAY)
            case SearchWarning.NOT_FOUND:
                # Wycena w efenix czyta tę odpowiedź jak tabelę bez wierszy (``read_results``).
                table = _Table(headers=[], rows=[])
            case None:
                table = page.evaluate(_READ_TABLE, [results, ORDER_PAGE])
    if results is not None and table is None:
        report.differ(Part.RESULTS, f"odpowiedź POST {SEARCH} bez tabeli")
    if results is None or table is None:
        report.unchecked += [(Part.ORDER, "bez tabeli wyników nie ma zleceń do otwarcia"), (Part.PRICING, "bez strony zlecenia")]
        return
    _check_results(page, results, table, report)
    rows = sorted((row for row in table["rows"] if len(row["links"]) == 1), key=lambda row: PRICING_STATUS not in row["badges"])
    if not table["rows"]:
        report.unchecked.append((Part.RESULTS, "tabela wyników bez wierszy: podaj --numer, który znajduje zlecenia"))
    if not rows:
        report.unchecked += [(Part.ORDER, "żaden wiersz nie prowadzi do strony zlecenia"), (Part.PRICING, "bez strony zlecenia")]
        return
    _check_orders(efenix, page, [_order_id(row) for row in rows], costs, report)


def _check_results(page: Page, html: str, table: _Table, report: Report) -> None:
    """Wycena w efenix czyta każdy wiersz ze statusem, loginem realizatora i adresem, który rozbiera reguła adresu; przy
    błędzie odczytu budowa tabeli."""

    rows = table["rows"]
    report.checked["wiersze wyników"] = len(rows)
    try:
        listed = read_results(page, html)
    except UnexpectedPage:
        report.differ(Part.RESULTS, "Wycena w efenix nie czyta tabeli wyników")
        _explain_table(table, report)
        return
    for what, missing in (
        ("statusu", sum(not order.status for order in listed)),
        ("loginu realizatora „(login)” z kolumny Wykonawca", sum(order.realizator is None for order in listed)),
        ("Dane adresowe", sum(not order.address for order in listed)),
        (
            "Dane adresowe jako ulicy, numeru domu i lokalu (reguła adresu ich nie rozbiera)",
            sum(bool(order.address) and not readable(order.address) for order in listed),
        ),
    ):
        if missing:
            report.differ(Part.RESULTS, f"Wycena w efenix nie czyta {what}: {missing} z {len(listed)} wierszy")


def _explain_table(table: _Table, report: Report) -> None:
    headers, rows = table["headers"], table["rows"]
    for header in HEADERS.values():
        found = sum(text.casefold().startswith(header) for text in headers)
        if found != 1:
            shown = " / ".join(text or "(pusty)" for text in headers)
            report.differ(Part.RESULTS, f"nagłówek zaczynający się od „{header}”: {found} zamiast 1 (nagłówki: {shown})")
    faults = {
        f"wiersze z inną liczbą komórek niż nagłówków ({len(headers)})": [row["cells"] != len(headers) for row in rows],
        f"wiersze bez jednego linku {ORDER_PAGE}?id=": [len(row["links"]) != 1 for row in rows],
        "wiersze bez statusu w .badge": [not row["badges"] for row in rows],
    }
    for what, bad in faults.items():
        if any(bad):
            report.differ(Part.RESULTS, f"{what}: {sum(bad)} z {len(rows)}")


def _order_id(row: _Row) -> str:
    return parse_qs(urlparse(row["links"][0]).query).get("id", [""])[0]


def _check_orders(efenix: _Efenix, page: Page, order_ids: Sequence[str], costs: Mapping[str, Decimal | None], report: Report) -> None:
    """Otwiera zlecenia z tabeli, aż sprawdzi budowę strony zlecenia i znajdzie pustą datę wykonania."""

    opened = report.checked["otwarte zlecenia"] = 0
    unread: Counter[str] = Counter()
    structure_checked = empty_found = False
    for order_id in order_ids[:ORDERS_TO_OPEN]:
        if structure_checked and empty_found:
            break
        address = efenix.address(ORDER_PAGE, id=order_id)
        html = _text(efenix, efenix.get(address), f"GET {ORDER_PAGE}", Part.ORDER, report)
        if html is None:
            break
        opened += 1
        _show(page, html)
        try:
            empty_found = empty_found or read_order(page).execution_date is None
        except UnexpectedPage:
            unread[_shape(page)] += 1
        if not structure_checked:
            _check_elements(page, Part.ORDER, (*ORDER_ELEMENTS, *UNUSED_ORDER_ELEMENTS), report)
            _check_proposal_before(page, report)
            _check_script(efenix, page, address, Part.ORDER, ORDER_SCRIPT, ORDER_SCRIPT_USES, report)
            _check_positions(page, costs, report)
            structure_checked = True
    report.checked["otwarte zlecenia"] = opened
    for shape, count in unread.items():
        report.differ(Part.ORDER, f"Wycena w efenix nie czyta strony zlecenia ({shape}): {count} z {opened}")
    if not structure_checked:
        report.unchecked.append((Part.PRICING, "bez strony zlecenia"))
    elif not empty_found:
        report.unchecked.append((Part.ORDER, f"postać pustej daty wykonania: żadne z {opened} otwartych zleceń nie ma pustej {EXECUTION_DATE}"))


def _shape(page: Page) -> str:
    """Postać daty wykonania i kwoty końcowej bez treści: cyfra to 9, a litera to a."""

    shapes = []
    for selector in (EXECUTION_DATE, AMOUNT):
        located = page.locator(selector)
        if located.count() != 1:
            shapes.append(f"{located.count()} × {selector}")
            continue
        text = re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "a", " ".join(located.inner_text().split())))
        shapes.append(f"{selector} „{text}”")
    return ", ".join(shapes)


def _check_elements(page: Page, part: Part, elements: Sequence[PageElement], report: Report) -> None:
    for element in elements:
        located = page.locator(element.selector)
        found = located.count()
        if found == 0 or (found > 1 and not element.many):
            report.differ(part, f"{element.name} ({element.selector}): {found} zamiast {'co najmniej 1' if element.many else '1'}")
        elif element.clicked and not located.first.is_visible():
            report.differ(part, f"{element.name} ({element.selector}) jest ukryty w HTML strony")


def _check_proposal_before(page: Page, report: Report) -> None:
    """Propozycja w oknie Emmetta na stronie zlecenia nic nie pokazuje, zanim skrypt strony włoży do niej odpowiedź
    ``action_fill_emmett.php``, jak w Atrapie; strona bez niej dokładnie raz to różnica z ``ORDER_ELEMENTS``."""

    if _skeleton(page, PROPOSAL):
        report.differ(Part.ORDER, f"propozycja w oknie Emmetta ({PROPOSAL}) coś pokazuje przed propozycją Emmetta, a w Atrapie jest pusta")


def _check_proposal(page: Page, html: str, report: Report) -> None:
    """Propozycja Emmetta z pliku ``--propozycja`` ma budowę propozycji Atrapy (``atrapa_efenix.emmett_proposal``).

    Budowa to elementy, teksty i atrybuty (``_READ_SKELETON``) z maską ``_masked``, a plik narzędzie składa jako treść
    elementu, jak skrypt strony efenix odpowiedź w ``#emmett-propozycja`` (``_COMPOSE_PROPOSAL``): plik z elementem
    ``#emmett-propozycja`` (skopiowany element) czyta od niego, a inny (sama odpowiedź) w całości, więc obie postacie
    tej samej propozycji mają tę samą budowę. Propozycja, która nic nie pokazuje, to część niesprawdzona: tak samo pusta
    jest propozycja Atrapy, gdy Emmett nic nie proponuje, ale budowy ilości z niej nie widać.
    """

    report.proposal_read = True
    found = _composed(page, html)
    report.checked["pozycje w propozycji Emmetta"] = len({code for _path, _attribute, value in found if value for code in POSITION_CODE.findall(value)})
    if not found:
        report.unchecked.append(
            (Part.PROPOSAL, "propozycja z pliku --propozycja nic nie pokazuje: zapisz propozycję zlecenia, któremu Emmett proponuje ilości")
        )
        return
    efenix = _shown(found)
    atrapa = _shown(_composed(page, emmett_proposal({position.code: 1 for position in CATALOG if position.kind == "ILOSC"})))
    for line in sorted(efenix - atrapa):
        report.differ(Part.PROPOSAL, f"w efenix, nie w Atrapie: {line}")
    for line in sorted(atrapa - efenix):
        report.differ(Part.PROPOSAL, f"w Atrapie, nie w efenix: {line}")


def _composed(page: Page, html: str) -> list[tuple[str, str | None, str | None]]:
    """Budowa propozycji ``html`` złożonej jak w efenix (``_COMPOSE_PROPOSAL``): od jedynego ``#emmett-propozycja`` w
    niej, a bez niego cała."""

    _show(page, "")
    page.evaluate(_COMPOSE_PROPOSAL, [_PROPOSAL_BOX, html])
    return _skeleton(page, PROPOSAL_ALONE, within=_PROPOSAL_BOX)


def _skeleton(page: Page, selector: str, *, within: str | None = None) -> list[tuple[str, str | None, str | None]]:
    """``_READ_SKELETON`` przez ``page.evaluate``, które, inaczej niż lokator, nie czeka na przejście strony (``<meta
    http-equiv="refresh">``), na które narzędzie odpowiada 204; element, którego nie ma dokładnie raz, bez ``within``:
    pusta lista."""

    found = page.evaluate(_READ_SKELETON, [selector, within])
    return [] if found is None else [(path, attribute, value) for path, attribute, value in found]


def _shown(skeleton: Sequence[tuple[str, str | None, str | None]]) -> set[str]:
    """Linie budowy bez treści: element, tekst w nim (``„…”``) albo atrybut (``[nazwa] „…”``) z maską ``_masked``."""

    lines = set()
    for path, attribute, value in skeleton:
        where = path or "(bez elementu)"
        lines.add(where if value is None else f"{where}{f'[{attribute}]' if attribute else ''} „{_masked(value)}”")
    return lines


def _masked(text: str) -> str:
    """Tekst bez treści: kod pozycji to ``INDEKS_NNN_NNN``, ciąg cyfr to 9, ciąg liter to a, białe znaki jedna spacja."""

    parts = POSITION_CODE.split(" ".join(text.split()))
    return CODE_TOKEN.join(re.sub(r"\d+", "9", re.sub(r"[^\W\d_]+", "a", part)) for part in parts)


def _check_script(efenix: _Efenix, page: Page, page_url: str, part: Part, script: str, uses: Sequence[ScriptUse], report: Report) -> None:
    """Skrypt ``script``, który strona ładuje, ma nazwy każdego działania ``uses``; skryptu narzędzie nie uruchamia."""

    sources: list[str] = page.locator("script[src]").evaluate_all("(scripts) => scripts.map((script) => script.getAttribute('src'))")
    loaded = [address for address in (urljoin(page_url, source) for source in sources) if efenix.name(address) == script]
    if not loaded:
        report.differ(part, f"strona nie ładuje skryptu {script}")
        return
    if not allowed("GET", loaded[0], efenix.url):
        report.unchecked.append(
            (part, f"skrypt {script}: strona ładuje go pod adresem spoza listy dozwolonych żądań (inny schemat, #fragment albo ;parametr)")
        )
        return
    text = _text(efenix, efenix.get(loaded[0]), f"GET {script}", part, report)
    if text is None:
        return
    for use in uses:
        missing = [name for name in use.names if name not in text]
        if missing:
            report.differ(part, f"skrypt {script} bez {', '.join(f'„{name}”' for name in missing)}: {use.what}")


def _check_positions(page: Page, costs: Mapping[str, Decimal | None], report: Report) -> None:
    """Karty pozycji to pozycje Atrapy (kod, rodzaj karty), a ceny pozycji z przypisania są równe kosztom Wzorca.

    Strona z częścią pozycji Atrapy jest zgodna: zlecenia efenix bywają bez części pozycji wyceny (#819, #822). Strona
    bez żadnej pozycji z przypisania kolumn nie pozwala porównać cen, więc to porównanie zostaje niesprawdzone.
    """

    cards: list[_Card] = page.evaluate(_READ_CARDS, [PRICING_CARD, QUANTITY])
    if not cards:
        report.unchecked.append((Part.PRICING, f"strona zlecenia bez kart pozycji {PRICING_CARD}"))
    found = dict(position for card in cards if (position := _position(card)) is not None)
    report.checked["pozycje wyceny"] = len(found)
    if broken := len(cards) - len(found):
        report.differ(
            Part.PRICING,
            f"karty bez jednego pola Ilość z ceną w tekście albo jednego pola ceny wpisywanej z kodem INDEKS_NNN_NNN: {broken} z {len(cards)}",
        )
    atrapa = {f"INDEKS_{item.code}_078": item.kind == "CENA" for item in CATALOG}
    for code in sorted(found.keys() - atrapa.keys()):
        report.differ(Part.PRICING, f"{code}: jest w efenix, nie ma go w Atrapie")
    for code in sorted(found.keys() & atrapa.keys()):
        if (found[code] is None) != atrapa[code]:
            kinds = ("pole ceny wpisywanej", "pole Ilość") if found[code] is None else ("pole Ilość", "pole ceny wpisywanej")
            report.differ(Part.PRICING, f"{code}: w efenix {kinds[0]}, w Atrapie {kinds[1]}")
    compared = mapped_shown = 0
    for column, mapped in POSITION_OF_COLUMN.items():
        for code, shown in sorted(found.items()):
            if code.split("_")[1] != mapped or shown is None:
                continue
            mapped_shown += 1
            cost = costs.get(column)
            if cost is None:
                report.unchecked.append((Part.PRICING, f"{code} (kolumna {column}): koszt w wierszu {COST_ROW} Wzorca pliku zbiorczego nie jest liczbą"))
                continue
            compared += 1
            if _amount(shown) != cost:
                report.differ(Part.PRICING, f"{code} (kolumna {column}): cena w efenix inna niż koszt w wierszu {COST_ROW} Wzorca pliku zbiorczego")
    if cards and not mapped_shown:
        report.unchecked.append((Part.PRICING, "strona zlecenia bez pozycji z przypisania kolumn: ceny nie porównane z Wzorcem pliku zbiorczego"))
    report.checked["ceny porównane z Wzorcem"] = compared


def _position(card: _Card) -> tuple[str, str | None] | None:
    """Kod i cena z tekstu karty; ``None`` jako cena to karta z ceną wpisywaną, a karta w innym kształcie to ``None``."""

    match card["quantity"], card["price"], card["shown"]:
        case [code], [], [shown]:
            position: tuple[str, str | None] = (code, shown)
        case [], [code], []:
            position = (code, None)
        case _:
            return None
    return position if POSITION_CODE.fullmatch(position[0]) else None


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def _check_signed_out(efenix: _Efenix, page: Page, report: Report) -> None:
    """Lista bez sesji przekierowuje na stronę logowania, szukanie odpowiada ostrzeżeniem o wygasłej sesji, które
    rozpoznaje Wycena w efenix, a strona logowania ma pola formularza logowania."""

    if not efenix.to_login(efenix.get(efenix.url)):
        report.differ(Part.LOGGED_OUT, f"GET {LIST_PAGE} bez sesji nie przekierowuje na {LOGIN_PAGE}")
    search = efenix.post(efenix.address(SEARCH), SEARCH_FORM)
    if search.location is not None:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji przekierowuje na {efenix.name(search.location)} zamiast ostrzeżenia o wygasłej sesji")
    elif not 200 <= search.status < 300:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji: odpowiedź {search.status}")
    elif search_warning(page, search.text) is not SearchWarning.SESSION_EXPIRED:
        report.differ(Part.LOGGED_OUT, f"POST {SEARCH} bez sesji nie odpowiada ostrzeżeniem o wygasłej sesji")
    login = efenix.get(efenix.address(LOGIN_PAGE))
    if login.location is not None or not 200 <= login.status < 300:
        report.differ(Part.LOGIN, f"GET {LOGIN_PAGE}: odpowiedź {login.status}")
        return
    _show(page, login.text)
    _check_elements(page, Part.LOGIN, LOGIN_ELEMENTS, report)


def _proposal_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ToolError(f"plik --propozycja {path}: nie da się go przeczytać jako tekstu UTF-8") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efenix-url", required=True, help=f"Adres listy zleceń efenix (…/{LIST_PAGE}).")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222", help="Adres zdalnego debugowania Chrome (domyślnie %(default)s).")
    parser.add_argument(
        "--numer",
        default="",
        help=(
            "Co wpisać w pole Numer, żeby lista pokazała zlecenia (domyślnie puste pole). Podaj numer zlecenia"
            f" „{PRICING_STATUS}” bez daty wykonania, gdy wynik mówi, że lista nie ma zleceń albo że żadne otwarte zlecenie nie ma pustej daty wykonania."
        ),
    )
    parser.add_argument(
        "--wzorzec",
        type=Path,
        default=None,
        help="Wzorzec pliku zbiorczego z kosztami pozycji w wierszu 14 (domyślnie Wzorzec z konfiguracji narzędzia, jak w Centrum).",
    )
    parser.add_argument(
        "--propozycja",
        type=Path,
        default=None,
        help=(
            "Plik HTML z propozycją Emmetta zapisaną w Chrome (element #emmett-propozycja albo odpowiedź"
            " action_fill_emmett.php), zapisany ze schowka poleceniem pbpaste > ~/.t3/notes/953/propozycja.html;"
            " narzędzie porównuje jej budowę z Atrapą, a samo action_fill_emmett.php nie wysyła."
        ),
    )
    parser.add_argument("--limit-ms", type=int, default=TIMEOUT_MS, help="Limit czekania na odpowiedź efenix (ms).")
    args = parser.parse_args(argv)
    try:
        address = urlparse(args.efenix_url)
        if address.scheme not in ("http", "https") or not address.path.endswith("/" + LIST_PAGE):
            raise ToolError(f"--efenix-url to adres listy zleceń efenix kończący się na /{LIST_PAGE}")
        costs = template_costs(args.wzorzec or default_collective_template_path())
        proposal = None if args.propozycja is None else _proposal_file(args.propozycja)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(args.cdp)
            except PlaywrightError as error:
                raise ToolError(f"nie ma Chrome ze zdalnym debugowaniem pod --cdp {args.cdp}") from error
            if not browser.contexts:
                raise ToolError("Chrome pod --cdp nie ma okna z sesją efenix")
            # Domyślny kontekst Chrome (sesja taty), wzięty przed kontekstem narzędzia, który też trafia do ``contexts``.
            session = browser.contexts[0].request
            signed_out = playwright.request.new_context()
            try:
                with parser_page(browser, timeout_ms=args.limit_ms) as page:
                    report = check(
                        _Efenix(session, args.efenix_url, timeout_ms=args.limit_ms),
                        _Efenix(signed_out, args.efenix_url, timeout_ms=args.limit_ms),
                        page,
                        costs,
                        number=args.numer,
                        proposal=proposal,
                    )
            finally:
                signed_out.dispose()
    except ToolError as error:
        print(f"BŁĄD | {error}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    return 2 if report.differences or report.unchecked else 0


if __name__ == "__main__":
    sys.exit(main())
