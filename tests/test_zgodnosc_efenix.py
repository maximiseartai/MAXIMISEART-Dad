"""Narzędzie zgodności Atrapy efenix z efenix (``tools/zgodnosc_efenix.py``, #748) na Atrapie efenix.

Każdy test uruchamia narzędzie jak Maks: osobnym procesem, który łączy się przez zdalne debugowanie z Chromium (u Maksa
Chrome z sesją taty), a sprawdza to, co widać z zewnątrz: wynik (plik expect w ``tests/expected/zgodnosc_efenix/``),
kod wyjścia, żądania, które dostała Atrapa, i jej stan. Zgodna Atrapa daje wynik bez różnic, a Atrapa ze zmienioną
budową każdą różnicę; każdy wynik ma prośbę o ręczne sprawdzenie przycisku kalendarza daty wykonania. Każde żądanie, które dostaje Atrapa, jest z listy dozwolonych odczytów, także gdy skrypty i
elementy stron same wysyłają zapis albo wylogowanie, a nigdy propozycja Emmetta (``action_fill_emmett.php``), więc
każdy wynik bez ``--emmett`` ma też linię o niesprawdzonej budowie propozycji. Wynik nie zawiera numerów zleceń,
adresów, loginów ani identyfikatorów, które Atrapa pokazuje, ani cen.

Budowę, której Atrapa nie umie zmienić sama (``Changed``, ``Unread``), zmienia serwer przed Atrapą (``_in_front``):
narzędzie łączy się z nim, a on przekazuje każde żądanie Atrapie i zmienia odpowiedź na wskazane strony (inny kod,
inna treść), jak efenix, którego autor zmienił jedną stronę.

Pomiar propozycji Emmetta (``--emmett``) test uruchamia tak, jak robi to Maks: zanim narzędzie wystartuje, „Maks” w karcie
domyślnego kontekstu Chromium otwiera zlecenie przez serwer przed Atrapą i klika przycisk Emmetta (jedyne
``action_fill_emmett.php`` przebiegu), a Enter przychodzi na stdin narzędzia. Żądania, które Atrapa dostaje od startu
narzędzia, są tylko z listy odczytów, a karty Maksa i ich okna Emmetta zostają takie, jakie były.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
import http.client
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
from typing import TypeVar, cast
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from openpyxl import Workbook
from playwright.sync_api import Browser, Page, sync_playwright
import pytest
import zgodnosc_efenix

from rozliczenia.efenix_browser import launch_options
from rozliczenia.efenix_page import EmmettWindow, emmett_window, read_results
from rozliczenia.efenix_positions import POSITION_OF_COLUMN
from rozliczenia.efenix_window import ListedOrder

from tests.fixtures.atrapa_efenix import (
    CHANGE_STATUS,
    FILL_EMMETT,
    LIST_PAGE,
    LIST_SCRIPT,
    LIST_SEARCH_FIELDS,
    LOAD_EMMETT,
    LOGIN_PAGE,
    LOGOUT,
    ORDER_PAGE,
    ORDER_SCRIPT,
    PRICES,
    SAVE_QUANTITY,
    SEARCH,
    SESSION_COOKIE,
    SET_DATE,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    Unread,
    atrapa_efenix,
)
from tests.fixtures.efenix import write_template_costs
from tests.fixtures.expect import assert_expected
from tests.fixtures.settlement import CellValue
from tests.fixtures.workbooks import active_worksheet

ROOT = Path(__file__).resolve().parents[1]
# Linia, którą ma każdy wynik narzędzia (#748): przycisku kalendarza narzędzie nie sprawdza, sprawdza go Maks.
DATE_BUTTON_BY_HAND = (
    "NIESPRAWDZONE | strona zlecenia | przycisk kalendarza daty wykonania nie jest sprawdzany: sprawdź ręcznie w efenix"
    " na zleceniu „Do wyceny” bez daty wykonania, że jest przycisk otwierający okno wyboru daty"
)
# Linia każdego wyniku (#953): narzędzie nie wysyła propozycji Emmetta.
PROPOSAL_BY_HAND = (
    "NIESPRAWDZONE | propozycja Emmetta | budowa propozycji Emmetta nie jest sprawdzana: uruchom narzędzie z --emmett"
    " i kliknij w Chrome przycisk Emmetta, gdy narzędzie o to poprosi"
)
TOOL = ROOT / "tools" / "zgodnosc_efenix.py"
# Żądania, które niczego w efenix nie zmieniają: lista, szukanie, strona zlecenia, skrypty obu stron i strona logowania.
READING = {("GET", LIST_PAGE), ("GET", LIST_SCRIPT), ("POST", SEARCH), ("GET", ORDER_PAGE), ("GET", ORDER_SCRIPT), ("GET", LOGIN_PAGE)}
# Żądania, które zmieniają zlecenie w efenix: zapis ilości, załadowanie Emmetta, ustawienie daty i statusu (#741),
# i logowanie oraz wylogowanie, które zmieniają sesję taty.
WRITES = (SAVE_QUANTITY, LOAD_EMMETT, SET_DATE, CHANGE_STATUS, "action_login.php", LOGOUT)
FORWARDING = ("forward", "accept", "cancel")
ORDERS = (
    AtrapaOrder("ID-TAJNE-71", "ZL/TAJNE/0001", "tajny-login", "ul.Tajemnicza 7 Lokal 3", execution_date=date(2026, 9, 2), executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-72", "ZL/TAJNE/0002", "tajny-login", "ul.Ukryta 9", executor="Firma Sekretna"),
    AtrapaOrder("ID-TAJNE-73", "ZL/TAJNE/0003", "inny-tajny", "os.Zakryte 4", status="Do akceptacji", execution_date=date(2026, 9, 3)),
)
PRIVATE = [text for order in ORDERS for text in (order.order_id, order.number, order.realizator, order.address, order.executor)]
# Koszty pozycji w wierszu 14 Wzorca pliku zbiorczego równe cenom Atrapy: kolumna → koszt pozycji z przypisania kolumn.
COSTS: dict[str, CellValue] = {column: float(PRICES[position]) for column, position in POSITION_OF_COLUMN.items()}


@dataclass(frozen=True)
class Answer:
    """Odpowiedź Atrapy, którą serwer przed nią może zmienić: kod, nagłówki ``Location`` i ``Set-Cookie`` i treść."""

    status: int
    headers: Mapping[str, str]
    body: str


Rewrite = Callable[[Answer], Answer]


def _replaced(*changes: tuple[str, str]) -> Rewrite:
    """Odpowiedź z każdym tekstem ``old`` w treści zamienionym na ``new`` (``changes``: pary ``old``, ``new``)."""

    def rewrite(answer: Answer) -> Answer:
        body = answer.body
        for old, new in changes:
            body = body.replace(old, new)
        return replace(answer, body=body)

    return rewrite


def _answered(status: int) -> Rewrite:
    """Odpowiedź z kodem ``status`` bez nagłówka ``Location`` i bez treści strony efenix."""

    return lambda _answer: Answer(status, {}, "<p>Błąd serwera.</p>")


def _to_login_if_warned(answer: Answer) -> Answer:
    """Odpowiedź z ostrzeżeniem o wygasłej sesji zamieniona na przekierowanie na stronę logowania, a inna bez zmian."""

    if "Twoja sesja wygasła" in answer.body:
        return Answer(302, {"Location": LOGIN_PAGE}, "")
    return answer


@dataclass(frozen=True)
class Variant:
    """Atrapa efenix pod narzędziem, koszty we Wzorcu i plik expect wyniku.

    ``rewrites``: strona Atrapy (ścieżka jak ``ORDER_PAGE``) → zmiana jej odpowiedzi, którą robi serwer przed Atrapą.
    """

    expected: Path
    changed: Changed | Unread | None = None
    cookie_session: bool = True
    orders: tuple[AtrapaOrder, ...] = ORDERS
    costs: Mapping[str, CellValue] = field(default_factory=lambda: COSTS)
    number: str = ""
    rewrites: Mapping[str, Rewrite] = field(default_factory=dict)


# Strona zlecenia z częścią pozycji Atrapy, jak zlecenia efenix z mniejszą liczbą pozycji wyceny (#822): bez dwóch
# pozycji z przypisania kolumn, jednej spoza niego i jednej z ceną wpisywaną.
SUBSET = tuple(replace(order, without=frozenset({"012", "021", "005", "045"})) for order in ORDERS)
NO_MAPPED = tuple(replace(order, without=frozenset(POSITION_OF_COLUMN.values())) for order in ORDERS)
NO_CARDS = tuple(replace(order, without=frozenset(PRICES)) for order in ORDERS)
DATED = tuple(AtrapaOrder(order.order_id, order.number, order.realizator, order.address, execution_date=date(2026, 9, 1)) for order in ORDERS)
CHANGED = {
    "inny-naglowek-status": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-naglowek-status.txt", Changed.STATUS_HEADER),
    "wiersz-bez-linku": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-bez-linku.txt", Changed.ORDER_LINK),
    "inny-zapis-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inny-zapis-daty.txt", Changed.DATE_FORMAT),
    "bez-emmetta-i-pola-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-emmetta-i-pola-daty.txt", Unread.ORDER_PARTS),
    "ukryty-przycisk-emmetta": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "ukryty-przycisk-emmetta.txt", Changed.HIDDEN_EMMETT),
    "inne-pozycje-wyceny": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inne-pozycje-wyceny.txt", Unread.PRICE_LIST),
    "inne-koszty-we-wzorcu": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "inne-koszty-we-wzorcu.txt",
        costs={**COSTS, "O": 99.5, "P": "=O14", "Q": True, "AP": None},
    ),
    "skrypty-stron-inne": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypty-stron-inne.txt", Unread.SCRIPTS),
    "skrypty-stron-pod-adresem-z-fragmentem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypty-stron-pod-adresem-z-fragmentem.txt", Unread.SCRIPT_ADDRESSES
    ),
    "przekierowanie-strony-zlecenia": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "przekierowanie-strony-zlecenia.txt", Unread.ORDER_REDIRECT
    ),
    "logowanie-bez-fingerprint": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "logowanie-bez-fingerprint.txt", Unread.LOGIN_FORM),
    "sesja-bez-ciasteczka": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "sesja-bez-ciasteczka.txt", cookie_session=False),
    "bez-pustej-daty": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "bez-pustej-daty.txt", orders=DATED),
    "strona-zlecenia-bez-kart-pozycji": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "strona-zlecenia-bez-kart-pozycji.txt", orders=NO_CARDS
    ),
    "strona-zlecenia-bez-pozycji-z-przypisania": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "strona-zlecenia-bez-pozycji-z-przypisania.txt", orders=NO_MAPPED
    ),
    "szukanie-bez-wynikow": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "szukanie-bez-wynikow.txt", number="ZL/NIEZNANY"),
    "wiersz-bez-loginu-i-adresu": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-bez-loginu-i-adresu.txt",
        orders=(replace(ORDERS[0], realizator="", address=""), *ORDERS[1:]),
    ),
    "wiersz-bez-statusu-i-adres-bez-rodzaju-ulicy": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-bez-statusu-i-adres-bez-rodzaju-ulicy.txt",
        orders=(replace(ORDERS[0], status=""), replace(ORDERS[1], address="Miastowo Zawilcowa 12 Lokal 3"), *ORDERS[2:]),
    ),
    "lista-bez-pola-numer-i-jej-skrypt-z-bledem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "lista-bez-pola-numer-i-jej-skrypt-z-bledem.txt",
        rewrites={LIST_PAGE: _replaced(('id="field_numer"', 'id="field_nr"')), LIST_SCRIPT: _answered(500)},
    ),
    "lista-ze-skryptem-innego-hosta-szukanie-bez-tabeli-logowanie-z-bledem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "lista-ze-skryptem-innego-hosta-szukanie-bez-tabeli-logowanie-z-bledem.txt",
        rewrites={
            LIST_PAGE: _replaced((f'src="{LIST_SCRIPT}?v=1"', f'src="http://inny.example/{LIST_SCRIPT}"')),
            SEARCH: _replaced(('<table class="table table-sm">', "<div>"), ("</table>", "</div>")),
            LOGIN_PAGE: _answered(500),
        },
    ),
    "strona-zlecenia-w-innej-budowie": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "strona-zlecenia-w-innej-budowie.txt",
        rewrites={
            ORDER_PAGE: _replaced(
                ('id="button_forward_to_accept"', 'id="button_accept"'),
                ('id="button_forward_to_cancel"', 'id="button_cancel"'),
                # Okno daty wykonania bez przycisku zamknięcia: jedyne okno z polem ``readonly``.
                ('readonly></div><button type="button" class="btn btn-secondary" data-dismiss="modal">', 'readonly></div><button type="button" class="btn btn-secondary">'),
                # Karta pozycji 005 z polem Ilość bez ceny w tekście karty.
                (f'<div class="col-sm-1 mt-2"><span class="text-default"><small>{PRICES["005"]:.2f}</small></span></div>', ""),
                ('id="cena_all2"', 'id="cena_razem"'),
                # Okno Emmetta bez elementu, do którego skrypt wkłada propozycję.
                ('id="emmett-propozycja"', 'id="emmett-wynik"'),
            ),
            ORDER_SCRIPT: _answered(302),
        },
    ),
    # Skrypt strony zlecenia bez jednej nazwy każdego działania, na którym polega okno: kalendarz bez ``onSet``, „Potwierdź”
    # daty wysyła inny adres, „Załaduj do zlecenia” Emmetta też, a kwotę końcową skrypt wpisuje do innego elementu.
    "skrypt-strony-zlecenia-bez-nazw-dzialan-okna": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "skrypt-strony-zlecenia-bez-nazw-dzialan-okna.txt",
        rewrites={
            ORDER_SCRIPT: _replaced(
                ("onSet", "poWyborze"),
                (SET_DATE, "action_save_date.php"),
                (LOAD_EMMETT, "action_emmett_load.php"),
                ("cena_all2", "cena_razem"),
            )
        },
    ),
    # Szukanie bez sesji przekierowane na stronę logowania, jak Atrapa przed #828, zamiast ostrzeżenia efenix.
    "szukanie-bez-sesji-przekierowuje-na-logowanie": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "szukanie-bez-sesji-przekierowuje-na-logowanie.txt",
        rewrites={SEARCH: _to_login_if_warned},
    ),
    # Propozycja w oknie Emmetta ma tekst albo element bez tekstu na stronie zlecenia, zanim skrypt włoży do niej
    # propozycję.
    "propozycja-pokazuje-cos-przed-propozycja": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-pokazuje-cos-przed-propozycja.txt",
        rewrites={ORDER_PAGE: _replaced(('<div id="emmett-propozycja"></div>', '<div id="emmett-propozycja">Wczytywanie propozycji</div>'))},
    ),
    "propozycja-pokazuje-element-przed-propozycja": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-pokazuje-cos-przed-propozycja.txt",
        rewrites={ORDER_PAGE: _replaced(('<div id="emmett-propozycja"></div>', '<div id="emmett-propozycja"><span class="spinner-border"></span></div>'))},
    ),
    "logowanie-bez-formularza-i-pol": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "logowanie-bez-formularza-i-pol.txt",
        rewrites={
            LOGIN_PAGE: _replaced(('action="action_login.php"', 'action="zaloguj.php"'), ('id="field_signum"', 'id="login"'), ('id="field_password"', 'id="haslo"'))
        },
    ),
    # Numer dokumentu pierwszego wiersza jest linkiem do jego strony zlecenia, więc wiersz ma dwa linki, a Wycena w
    # efenix czyta tylko wiersz z jednym.
    "wiersz-z-dwoma-linkami": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-z-dwoma-linkami.txt",
        rewrites={
            SEARCH: _replaced(
                (f"<td>{ORDERS[0].number}<br>", f'<td><a href="{ORDER_PAGE}?id={ORDERS[0].order_id}">{ORDERS[0].number}</a><br>')
            )
        },
    ),
    # Drugi wiersz bez numeru dokumentu, a status i data w komórce Wykonawca bez ``.badge``, w którym pokazuje je Atrapa:
    # Wycena czyta status z tekstu komórki, a pierwsze otwarte zlecenie to pierwszy wiersz.
    "wiersz-z-pustym-numerem-i-bez-badge": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-z-pustym-numerem-i-bez-badge.txt",
        rewrites={SEARCH: _replaced((f"<td>{ORDERS[1].number}<br>", "<td><br>"), ('class="badge ', 'class="etykieta '))},
    ),
    # Pole Ilość pozycji 020 ma id z kodem 005, więc kod 005 stoi w dwóch polach Ilość strony zlecenia.
    "kod-pozycji-w-dwoch-polach-ilosc": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "kod-pozycji-w-dwoch-polach-ilosc.txt",
        rewrites={ORDER_PAGE: _replaced(('id="INDEKS_020_078"', 'id="INDEKS_005_079"'))},
    ),
    # Nagłówek „Dane adresowe” to „Adres”, a drugi wiersz nie ma numeru dokumentu: Wycena w efenix nie czyta tabeli już
    # przez kolumnę, której nie ma dokładnie raz, więc pustego numeru nie sprawdza i wynik nie ma o nim linii.
    "kolumna-nie-raz-i-wiersz-z-pustym-numerem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "kolumna-nie-raz-i-wiersz-z-pustym-numerem.txt",
        rewrites={SEARCH: _replaced(("<th>Dane adresowe</th>", "<th>Adres</th>"), (f"<td>{ORDERS[1].number}<br>", "<td><br>"))},
    ),
    # Pierwszy wiersz ma dwa linki, a trzeci o jedną komórkę więcej niż nagłówków: linie różnic wierszy stoją w kolejności,
    # w której Wycena je sprawdza (najpierw liczba komórek, potem link), nie w kolejności wierszy.
    "wiersz-z-dwoma-linkami-i-wiersz-z-dodatkowa-komorka": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "wiersz-z-dwoma-linkami-i-wiersz-z-dodatkowa-komorka.txt",
        rewrites={
            SEARCH: _replaced(
                (f"<td>{ORDERS[0].number}<br>", f'<td><a href="{ORDER_PAGE}?id={ORDERS[0].order_id}">{ORDERS[0].number}</a><br>'),
                (f"<td>{ORDERS[2].number}<br>", f"<td></td><td>{ORDERS[2].number}<br>"),
            )
        },
    ),
}
# Atrapa w innej postaci niż zgodna, a jednak zgodna z tym, czego używa Wycena w efenix: wynik bez różnic.
SAME = {
    "ceny-z-przecinkiem": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", Unread.PRICE_TEXT),
    "najpierw-zlecenie-do-akceptacji": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", orders=(ORDERS[2], ORDERS[0], ORDERS[1])),
    "skrypty-stron-zapisuja-i-wylogowuja": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt", Unread.HOSTILE),
    "strona-zlecenia-z-czescia-pozycji": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "strona-zlecenia-z-czescia-pozycji.txt", orders=SUBSET
    ),
    "szukanie-numeru": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "szukanie-numeru.txt", number=ORDERS[1].number),
    # Propozycja w oknie Emmetta z samymi białymi znakami przed propozycją: według reguły okna Wyceny pusta (#908).
    "propozycja-z-bialymi-znakami-przed-propozycja": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt",
        rewrites={ORDER_PAGE: _replaced(('<div id="emmett-propozycja"></div>', '<div id="emmett-propozycja">\n \t\u00a0\n</div>'))},
    ),
}
# Zlecenia pomiaru propozycji Emmetta: Maks klika Emmetta na drugim, któremu Emmett proponuje jedną pozycję (zlecenie
# Atrapy narzędzia ma dwie, a liczba pozycji propozycji zależy od zlecenia, nie od budowy).
EMMETT_ORDERS = (ORDERS[0], replace(ORDERS[1], emmett={"012": 3}), ORDERS[2])
DIALOG = "#dialog_emmett"
# Skrypt strony zlecenia, który wkłada propozycję jak ``.html()`` jQuery: skrypty w odpowiedzi biegną.
RUNS_ANSWER_SCRIPTS = _replaced(
    (
        "document.getElementById('emmett-propozycja').innerHTML = html;",
        "document.getElementById('emmett-propozycja').replaceChildren(document.createRange().createContextualFragment(html));",
    )
)


def _proposal(body: str) -> Rewrite:
    """Odpowiedź ``action_fill_emmett.php`` z treścią ``body`` i kodem Atrapy."""

    return lambda answer: replace(answer, body=body)


def _clicked(browser: Browser, address: str) -> Page:
    """Maks otwiera zlecenie pod ``address`` w nowej karcie, klika przycisk Emmetta i czeka, aż zobaczy okno Emmetta
    (gdy strona ma ich kilka, pierwsze widoczne)."""

    tab = browser.contexts[0].new_page()
    tab.goto(address)
    tab.click("#button_emmett")
    tab.locator(DIALOG).filter(visible=True).first.wait_for(state="visible")
    return tab


def _click(browser: Browser, address: str, _elsewhere: str) -> None:
    _clicked(browser, address)


def _click_and_close(browser: Browser, address: str, _elsewhere: str) -> None:
    tab = _clicked(browser, address)
    tab.click(f'{DIALOG} [data-dismiss="modal"]')
    tab.locator(DIALOG).wait_for(state="hidden")


def _click_and_reload(browser: Browser, address: str, _elsewhere: str) -> None:
    _clicked(browser, address).reload()


def _click_in_two_tabs(browser: Browser, address: str, _elsewhere: str) -> None:
    _clicked(browser, address)
    _clicked(browser, address)


def _click_and_open_second(browser: Browser, address: str, _elsewhere: str) -> None:
    _clicked(browser, address)
    browser.contexts[0].new_page().goto(address)


def _open(browser: Browser, address: str, _elsewhere: str) -> None:
    browser.contexts[0].new_page().goto(address)


def _open_list(browser: Browser, address: str, _elsewhere: str) -> None:
    browser.contexts[0].new_page().goto(urljoin(address, LIST_PAGE))


def _click_elsewhere(browser: Browser, _address: str, elsewhere: str) -> None:
    _clicked(browser, elsewhere)


def _click_in_frame(browser: Browser, address: str, _elsewhere: str) -> None:
    """Maks klika Emmetta na stronie zlecenia w ramce strony listy zleceń."""

    tab = browser.contexts[0].new_page()
    tab.goto(urljoin(address, LIST_PAGE))
    tab.set_content(f'<iframe src="{address}" width="900" height="700"></iframe>')
    frame = tab.frame_locator("iframe")
    frame.locator("#button_emmett").click()
    frame.locator(DIALOG).wait_for(state="visible")


@dataclass(frozen=True)
class Emmett:
    """Pomiar propozycji Emmetta: co Maks robi w Chrome (``maks``: przeglądarka, adres zlecenia pod ``--efenix-url`` i
    adres tego zlecenia na innym hoście), co wpisuje na stdin, Atrapa efenix pod narzędziem, kod wyjścia i plik expect.
    ``read``: narzędzie przeczytało otwarte okno Emmetta, więc prosi o jego zamknięcie."""

    expected: Path
    maks: Callable[[Browser, str, str], None] = _click
    code: int = 2
    read: bool = True
    orders: tuple[AtrapaOrder, ...] = EMMETT_ORDERS
    rewrites: Mapping[str, Rewrite] = field(default_factory=dict)
    enter: str = "\n"


EMMETT = {
    "zgodna": Emmett(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-zgodna.txt", code=0),
    # Propozycja z białymi znakami i komentarzem między elementami, jak HTML pisany z wcięciami.
    "propozycja-z-wcieciami-i-komentarzem": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-zgodna.txt",
        code=0,
        rewrites={FILL_EMMETT: _proposal("\n<!-- Emmett -->\n<ul>\n  <li>INDEKS_012_078: 3</li>\n  <!-- koniec -->\n</ul>\n")},
    ),
    "druga-karta-bez-okna": Emmett(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-zgodna.txt", _click_and_open_second, code=0),
    "bez-enter": Emmett(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-bez-enter.txt", read=False, enter=""),
    "bez-karty-zlecenia": Emmett(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-bez-karty-zlecenia.txt", _open_list, read=False),
    "karta-zlecenia-innego-hosta": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-bez-karty-zlecenia.txt", _click_elsewhere, read=False
    ),
    "zlecenie-w-ramce": Emmett(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-bez-karty-zlecenia.txt", _click_in_frame, read=False),
    "okno-zamkniete-przed-odczytem": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-okno-zamkniete.txt", _click_and_close, read=False
    ),
    "okno-ukryte-przez-visibility": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-okno-zamkniete.txt",
        _click_and_close,
        read=False,
        rewrites={ORDER_SCRIPT: _replaced(("document.getElementById(id).style.display = 'none';", "document.getElementById(id).style.visibility = 'hidden';"))},
    ),
    "strona-przeladowana-po-kliknieciu": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-okno-zamkniete.txt", _click_and_reload, read=False
    ),
    "strona-bez-okna-emmetta": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-strona-bez-okna-emmetta.txt",
        _open,
        read=False,
        rewrites={ORDER_PAGE: _replaced(('id="dialog_emmett"', 'id="dialog_inny"'))},
    ),
    # Strona zlecenia ma ``#emmett-propozycja`` poza oknem Emmetta, więc okno, które Maks widzi, nie ma propozycji.
    "propozycja-poza-oknem": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-poza-oknem.txt",
        rewrites={ORDER_PAGE: _replaced(('<div id="emmett-propozycja"></div>', ""), ("</body>", '<div id="emmett-propozycja"></div></body>'))},
    ),
    # Za widocznym oknem Emmetta strona ma drugie, ukryte, z propozycją: okno Wyceny liczy okna na całej stronie, także
    # ukryte.
    "druga-propozycja-w-ukrytym-drugim-oknie": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-druga-propozycja-w-ukrytym-drugim-oknie.txt",
        rewrites={
            ORDER_PAGE: _replaced(("</body>", '<div id="dialog_emmett" style="display: none"><div id="emmett-propozycja"></div></div></body>'))
        },
    ),
    # Skrypt strony przenosi jedyną propozycję do dopisanego, ukrytego drugiego okna: HTML strony ma jedno okno z
    # propozycją, a widoczne okno po skryptach nie ma żadnej.
    "propozycja-przeniesiona-do-ukrytego-drugiego-okna": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-dwa-okna-po-skrypcie.txt",
        rewrites={
            ORDER_PAGE: _replaced(
                (
                    "</body>",
                    "<script>const second = document.createElement('div'); second.id = 'dialog_emmett';"
                    " second.style.display = 'none'; second.append(document.getElementById('emmett-propozycja'));"
                    " document.body.append(second);</script></body>",
                )
            )
        },
    ),
    # Skrypt strony po kliknięciu Emmetta dopisuje przed widocznym oknem drugie, ukryte: widać drugie okno strony.
    "ukryte-okno-przed-widocznym": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-dwa-okna-po-skrypcie.txt",
        rewrites={
            ORDER_SCRIPT: _replaced(
                (
                    "show('dialog_emmett');",
                    "show('dialog_emmett');"
                    " document.body.prepend(Object.assign(document.createElement('div'), {id: 'dialog_emmett', hidden: true}));",
                )
            )
        },
    ),
    "okno-otwarte-w-dwoch-kartach": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-okno-w-dwoch-kartach.txt", _click_in_two_tabs, read=False
    ),
    # Skrypt strony psuje odczyt pudełka okna, więc odczyt karty pada, jak przy przejściu karty w trakcie odczytu.
    "odczyt-karty-pada": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-odczyt-karty-pada.txt",
        read=False,
        rewrites={
            ORDER_PAGE: _replaced(
                ('<div id="toast"></div>', "<div id=\"toast\"></div><script>Element.prototype.getClientRects = () => { throw new Error('zepsute'); };</script>")
            )
        },
    ),
    # Emmett nic nie proponuje: Atrapa odpowiada pustą treścią.
    "propozycja-pusta": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-nic-nie-pokazuje.txt",
        orders=(ORDERS[0], replace(ORDERS[1], emmett={}), ORDERS[2]),
    ),
    "propozycja-z-bialymi-znakami": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-nic-nie-pokazuje.txt",
        rewrites={FILL_EMMETT: _proposal("\n \t\u00a0\n")},
    ),
    "propozycja-sam-tekst": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-sam-tekst.txt",
        rewrites={FILL_EMMETT: _proposal(f"Emmett proponuje dla {ORDERS[1].address} 3 pozycje")},
    ),
    "propozycja-w-polach-bez-tekstu": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-w-polach-bez-tekstu.txt",
        orders=(ORDERS[0], replace(ORDERS[1], emmett={"012": 3}, emmett_in_fields=True), ORDERS[2]),
    ),
    # Klasy i atrybuty nie po kolei: budowa ma je w porządku alfabetycznym, więc te same w innej kolejności to ta sama
    # budowa, nie różnica.
    "propozycja-z-innymi-klasami": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-z-innymi-klasami.txt",
        rewrites={FILL_EMMETT: _proposal('<ul class="list-group"><li class="pozycja-12 list-group-item">INDEKS_012_078: 3</li></ul>')},
    ),
    "propozycja-z-innymi-atrybutami": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-propozycja-z-innymi-atrybutami.txt",
        rewrites={FILL_EMMETT: _proposal('<ul><li title="ul.Ukryta 9" data-indeks="012">INDEKS_012_078: 3</li></ul>')},
    ),
    "skrypt-w-odpowiedzi-rysuje-liste": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-skrypt-w-odpowiedzi-rysuje-liste.txt",
        rewrites={
            ORDER_SCRIPT: RUNS_ANSWER_SCRIPTS,
            FILL_EMMETT: _proposal(
                "<script>document.getElementById('emmett-propozycja')"
                ".insertAdjacentHTML('beforeend', '<ul><li>INDEKS_012_078: 3</li></ul>');</script>"
            ),
        },
    ),
    "ramka-w-propozycji": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-ramka-w-propozycji.txt",
        rewrites={FILL_EMMETT: _proposal('<iframe src="about:blank">ul.Ukryta 9</iframe>')},
    ),
    "druga-propozycja-w-propozycji": Emmett(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "emmett-druga-propozycja-w-propozycji.txt",
        rewrites={FILL_EMMETT: _proposal('<div id="emmett-propozycja"><ul><li>INDEKS_012_078: 3</li></ul></div>')},
    ),
}


@dataclass(frozen=True)
class Checked:
    code: int
    stdout: str
    stderr: str


_T = TypeVar("_T")


@dataclass(frozen=True)
class Chromium:
    """Chromium ze zdalnym debugowaniem pod ``endpoint``; ``do`` wykonuje działanie Maksa w jego przeglądarce."""

    endpoint: str
    _jobs: queue.Queue[tuple[Callable[[Browser], object], queue.Queue[tuple[object, BaseException | None]]]]

    def do(self, job: Callable[[Browser], _T]) -> _T:
        """``job`` na przeglądarce połączonej przez zdalne debugowanie, w wątku, który obsługuje Playwrighta Chromium."""

        answer: queue.Queue[tuple[object, BaseException | None]] = queue.Queue()
        self._jobs.put((job, answer))
        result, error = answer.get(timeout=120)
        if error is not None:
            raise error
        return cast(_T, result)


@pytest.fixture(scope="module")
def chromium() -> Iterator[Chromium]:
    """Chromium ze zdalnym debugowaniem (jak Chrome Maksa) i ciasteczkiem sesji Atrapy w domyślnym kontekście.

    Chromium i jego Playwright żyją w osobnym wątku, który przez cały czas obsługuje Playwrighta, jak osobny program
    Chrome u Maksa. Playwright, który uruchomił przeglądarkę, a którego nikt nie obsługuje, bo test czeka na proces
    narzędzia, na Windows wstrzymuje przeglądarkę: jego sterownik pisze do pełnej rury procesu testu i przestaje
    wznawiać nowe karty, więc karta, w której narzędzie składa HTML, nie wczytuje się (#755, CI na windows-2025).
    Dlatego i działania Maksa w kartach (``Chromium.do``) wykonuje ten sam wątek.
    """

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    started: queue.Queue[BaseException | None] = queue.Queue()
    stop = threading.Event()
    jobs: queue.Queue[tuple[Callable[[Browser], object], queue.Queue[tuple[object, BaseException | None]]]] = queue.Queue()

    def own() -> None:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**launch_options(playwright, arguments=[f"--remote-debugging-port={port}"]))
                try:
                    remote = playwright.chromium.connect_over_cdp(endpoint)
                    name, value = SESSION_COOKIE
                    remote.contexts[0].add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
                    idle = browser.new_page()
                    started.put(None)
                    while not stop.is_set():
                        try:
                            job, answer = jobs.get_nowait()
                        except queue.Empty:
                            idle.wait_for_timeout(50)
                            continue
                        try:
                            answer.put((job(remote), None))
                        except Exception as error:  # noqa: BLE001 - błąd działania Maksa wraca do testu w jego wątku
                            answer.put((None, error))
                finally:
                    browser.close()
        except BaseException as error:  # noqa: BLE001 - błąd startu przeglądarki wraca do fixture'a w wątku testu
            started.put(error)

    owner = threading.Thread(target=own, name="chromium-zgodnosc")
    owner.start()
    try:
        failure = started.get(timeout=120)
        if failure is not None:
            raise failure
        yield Chromium(endpoint, jobs)
    finally:
        stop.set()
        owner.join()


@pytest.fixture
def chrome(chromium: Chromium) -> str:
    """Adres zdalnego debugowania Chromium, pod który narzędzie się łączy."""

    return chromium.endpoint


def _run(endpoint: str, url: str, template: Path, *extra: str, limit_ms: int = 10_000, enter: str | None = None) -> Checked:
    done = subprocess.run(
        [sys.executable, str(TOOL), "--efenix-url", url, "--cdp", endpoint, "--limit-ms", str(limit_ms), "--wzorzec", str(template), *extra],
        input=enter,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    return Checked(done.returncode, done.stdout, done.stderr)


def _checked(
    endpoint: str, tmp_path: Path, variant: Variant, before: Callable[[AtrapaEfenix], None] = lambda _atrapa: None
) -> tuple[Checked, AtrapaEfenix]:
    """Wynik narzędzia na Atrapie ``variant``; Atrapa ma po nim ten sam stan i sesję, a Chrome te same karty."""

    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", variant.costs)
    with atrapa_efenix(variant.orders, changed=variant.changed, cookie_session=variant.cookie_session) as atrapa:
        before(atrapa)
        state, pages = atrapa.state(), _pages(endpoint)
        with _in_front(atrapa, variant.rewrites) if variant.rewrites else nullcontext(atrapa.url) as url:
            checked = _run(endpoint, url, template, "--numer", variant.number)
        assert (atrapa.state(), _pages(endpoint)) == (state, pages)
    assert not [text for text in PRIVATE if text in checked.stdout + checked.stderr]
    assert DATE_BUTTON_BY_HAND in checked.stdout.splitlines()
    assert PROPOSAL_BY_HAND in checked.stdout.splitlines()
    assert FILL_EMMETT not in {path for _method, path in atrapa.requested()}
    return checked, atrapa


@contextmanager
def _in_front(atrapa: AtrapaEfenix, rewrites: Mapping[str, Rewrite]) -> Iterator[str]:
    """Serwer przed Atrapą na czas bloku: każde żądanie (metoda, adres, treść, ciasteczko) przekazuje Atrapie, a jej
    odpowiedź na stronę z ``rewrites`` zmienia zmianą tej strony; daje adres listy zleceń przez ten serwer."""

    target = urlparse(atrapa.url)

    class Handler(BaseHTTPRequestHandler):
        def handle(self) -> None:
            # Narzędzie zrywa połączenie, na którego odpowiedź już nie czeka.
            with suppress(ConnectionError):
                super().handle()

        def do_GET(self) -> None:
            self._forward(None)

        def do_POST(self) -> None:
            self._forward(self.rfile.read(int(self.headers.get("Content-Length") or 0)))

        def log_message(self, format: str, *args: object) -> None:
            return

        def _forward(self, body: bytes | None) -> None:
            headers = {name: value for name, value in self.headers.items() if name.casefold() in ("cookie", "content-type")}
            connection = http.client.HTTPConnection(target.hostname or "", target.port, timeout=30)
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                passed = {name: value for name, value in response.getheaders() if name.casefold() in ("location", "set-cookie")}
                answer = Answer(response.status, passed, response.read().decode("utf-8"))
            finally:
                connection.close()
            rewrite = rewrites.get(urlparse(self.path).path.lstrip("/"))
            if rewrite is not None:
                answer = rewrite(answer)
            content = answer.body.encode("utf-8")
            self.send_response(answer.status)
            for name, value in answer.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="przed-atrapa-efenix")
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/{LIST_PAGE}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _dead_endpoint() -> str:
    """Adres zdalnego debugowania, pod którym nie ma Chrome (wolny port bez nasłuchu)."""

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{free.getsockname()[1]}"


def _pages(endpoint: str) -> int:
    """Liczba kart Chrome (lista celów zdalnego debugowania)."""

    with urlopen(f"{endpoint}/json/list", timeout=10) as answer:
        return sum(target["type"] == "page" for target in json.load(answer))


def test_atrapa_efenix_jest_zgodna_z_budowa_ktorej_uzywa_wycena_w_efenix(chrome: str, tmp_path: Path) -> None:
    checked, atrapa = _checked(chrome, tmp_path, Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt"))

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert_expected(checked.stdout, ROOT / "tests" / "expected" / "zgodnosc_efenix" / "zgodna.txt")
    assert set(atrapa.requested()) == READING
    # Szukanie z sesją i bez niej z każdym polem, które wysyła skrypt listy efenix po Enter w polu Numer w domyślnym
    # stanie listy: bez ``xrodzaj``, z pustymi filtrami, pierwszym sortowaniem i liczbą wierszy z domyślnego ustawienia
    # listy. Atrapa, jak efenix, bez liczby wierszy albo z pustym ``xrodzaj`` nie daje tabeli wyników (#822).
    searched = dict.fromkeys(LIST_SEARCH_FIELDS, "") | {"rodzaj": "szukanie", "strona": "1", "na_stronie": "10", "sortowanie": "1"}
    assert [request.params for request in atrapa.requests if request.path == SEARCH] == 2 * [searched]


@pytest.mark.parametrize("variant", SAME.values(), ids=SAME.keys())
def test_atrapa_w_innej_postaci_tej_samej_budowy_jest_zgodna(chrome: str, tmp_path: Path, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, tmp_path, variant)

    assert (checked.code, checked.stderr) == (0, ""), checked
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) == READING


@pytest.mark.parametrize("variant", CHANGED.values(), ids=CHANGED.keys())
def test_atrapa_ze_zmieniona_budowa_daje_kazda_roznice(chrome: str, tmp_path: Path, variant: Variant) -> None:
    checked, atrapa = _checked(chrome, tmp_path, variant)

    assert (checked.code, checked.stderr) == (2, ""), checked
    assert_expected(checked.stdout, variant.expected)
    assert set(atrapa.requested()) <= READING


# Wyjątek bez terminu, zgoda Maksa 6.11.2026 (#979): `zgodnosc_efenix.py --emmett` uruchamia tylko Maks na swoim Macu,
# więc ten test biegnie tylko na Macu i Linuksie. Na Windows CI wątek Playwrighta z fixture `chromium` ginie w trakcie
# kliknięcia Maksa, a worker xdist pada („node down: Not properly terminated”, #975); kwarantanna (xfail) tego nie łapie.
@pytest.mark.skipif(sys.platform == "win32", reason="#979: narzędzie Maksa tylko na Macu; worker xdist pada na Windows")
@pytest.mark.parametrize("variant", EMMETT.values(), ids=EMMETT.keys())
def test_okno_emmetta_po_kliknieciu_maksa_narzedzie_porownuje_z_atrapa_samym_odczytem(
    chromium: Chromium, tmp_path: Path, variant: Emmett
) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    with atrapa_efenix(variant.orders, cookie_session=True) as atrapa, _in_front(atrapa, variant.rewrites) as url:
        before: list[Page] = chromium.do(lambda browser: list(browser.contexts[0].pages))
        try:
            chromium.do(lambda browser: variant.maks(browser, _order(url), _order(atrapa.url)))
            clicked = len(atrapa.requests)
            shown, state, pages = chromium.do(lambda browser: _tabs(browser, before)), atrapa.state(), _pages(chromium.endpoint)
            checked = _run(chromium.endpoint, url, template, "--emmett", enter=variant.enter)
            assert (chromium.do(lambda browser: _tabs(browser, before)), atrapa.state(), _pages(chromium.endpoint)) == (shown, state, pages)
        finally:
            chromium.do(lambda browser: _close_new(browser, before))

    asked = [zgodnosc_efenix.ASK_EMMETT, *([zgodnosc_efenix.CLOSE_EMMETT] if variant.read else [])]
    assert (checked.code, checked.stderr.splitlines()) == (variant.code, asked), checked
    assert_expected(checked.stdout, variant.expected)
    assert not [text for text in PRIVATE if text in checked.stdout + checked.stderr]
    assert DATE_BUTTON_BY_HAND in checked.stdout.splitlines()
    assert PROPOSAL_BY_HAND not in checked.stdout.splitlines()
    # Przycisk Emmetta klika tylko Maks, przed startem narzędzia; narzędzie wysyła same odczyty.
    assert set(atrapa.requested()[clicked:]) <= READING
    assert set(atrapa.requested()) <= READING | {("POST", FILL_EMMETT)}


def _order(url: str) -> str:
    """Adres strony zlecenia, na którym Maks klika Emmetta, w katalogu listy zleceń ``url``."""

    return urljoin(url, f"{ORDER_PAGE}?id={EMMETT_ORDERS[1].order_id}")


def _close_new(browser: Browser, before: Sequence[Page]) -> None:
    for tab in browser.contexts[0].pages:
        if tab not in before:
            tab.close()


def _tabs(browser: Browser, before: Sequence[Page]) -> list[tuple[str, list[bool]]]:
    """Adres każdej karty Maksa (poza ``before``) i czy jest w niej widoczne każde okno Emmetta na stronie."""

    return [(tab.url, [dialog.is_visible() for dialog in tab.locator(DIALOG).all()]) for tab in browser.contexts[0].pages if tab not in before]


@pytest.mark.parametrize(
    ("before", "expire_after", "error"),
    [
        pytest.param(AtrapaEfenix.expire_session, None, zgodnosc_efenix.NOT_SIGNED_IN, id="przed-sprawdzaniem"),
        pytest.param(lambda _atrapa: None, (ORDER_PAGE, 0), zgodnosc_efenix.LOGGED_OUT_MIDWAY, id="w-trakcie-sprawdzania"),
        pytest.param(lambda _atrapa: None, (SEARCH, 0), zgodnosc_efenix.LOGGED_OUT_MIDWAY, id="przy-szukaniu-ostrzezenie"),
    ],
)
def test_bez_sesji_taty_narzedzie_konczy_sie_bledem_bez_wyniku(
    chrome: str, tmp_path: Path, before: Callable[[AtrapaEfenix], None], expire_after: tuple[str, int] | None, error: str
) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    with atrapa_efenix(ORDERS, cookie_session=True, expire_after=expire_after) as atrapa:
        before(atrapa)
        checked = _run(chrome, atrapa.url, template)

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", f"BŁĄD | {error}\n")
    assert set(atrapa.requested()) <= READING


def test_bez_chrome_pod_adresem_zdalnego_debugowania_narzedzie_konczy_sie_bledem(tmp_path: Path) -> None:
    endpoint = _dead_endpoint()
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    with atrapa_efenix(ORDERS) as atrapa:
        checked = _run(endpoint, atrapa.url, template)

    assert (checked.code, checked.stdout) == (1, "")
    assert checked.stderr == f"BŁĄD | nie ma Chrome ze zdalnym debugowaniem pod --cdp {endpoint}\n"
    assert atrapa.requested() == []


def test_bez_wzorca_pliku_zbiorczego_narzedzie_konczy_sie_bledem_przed_efenix(chrome: str, tmp_path: Path) -> None:
    missing = tmp_path / "Wzorzec pliku zbiorczego.xlsx"
    with atrapa_efenix(ORDERS, cookie_session=True) as atrapa:
        checked = _run(chrome, atrapa.url, missing)

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", f"BŁĄD | Wzorzec pliku zbiorczego {missing}: brak pliku\n")
    assert atrapa.requested() == []


def test_przejscie_w_karcie_skladania_zostawia_zlozony_html(chrome: str) -> None:
    # Przejście ramki kończy się przed zdarzeniem ``load``, na które czeka złożenie strony, więc po nim widać, czy ramka
    # przeszła na inną stronę (bez odpowiedzi 204 przeglądarka pokazałaby w niej pustą stronę błędu połączenia, adres
    # ``chrome-error://``), czy została przy swoim pierwszym, pustym dokumencie.
    with atrapa_efenix(ORDERS) as atrapa, sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(chrome)
        with zgodnosc_efenix.parser_page(browser, timeout_ms=10_000) as page:
            page.set_content(f'<p>Złożony HTML</p><iframe src="{atrapa.url}"></iframe>')
            frames = page.main_frame.child_frames
            shown = (page.locator("p").inner_text(), [frame.content() for frame in frames], [frame.url in {"", "about:blank"} for frame in frames])

        assert shown == ("Złożony HTML", ["<html><head></head><body></body></html>"], [True])
        assert atrapa.requested() == []


def test_tabela_wynikow_w_karcie_skladania_daje_status_z_badge_i_ostatni_login_realizatora(chrome: str) -> None:
    # Odczyt tabeli wyników, który narzędzie dzieli z Wyceną w efenix: status to tekst ``.badge``, choć komórka Status
    # ma obok niego inny tekst, a login realizatora to ostatni „(login)” w ``small.text-default`` komórki Wykonawca.
    html = (
        '<table class="table table-sm"><thead><tr><th>Numer dokumentu</th><th>Status</th><th>Wykonawca (login)</th>'
        "<th>Dane adresowe</th><th></th></tr></thead><tbody><tr><td>ZL/1</td>"
        '<td><span class="badge badge-default">Do wyceny</span> od 2 dni</td>'
        '<td>Firma <small><small class="text-default">(zastepca) (realizator)</small></small></td>'
        f'<td>ul.Prosta 1</td><td><a href="{ORDER_PAGE}?id=7" class="btn btn-sm">Otwórz</a></td></tr></tbody></table>'
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(chrome)
        with zgodnosc_efenix.parser_page(browser, timeout_ms=10_000) as page:
            orders = read_results(page, html)

    assert orders == (ListedOrder(number="ZL/1", status="Do wyceny", realizator="realizator", address="ul.Prosta 1", order_id="7"),)


def test_karta_zlecenia_zmieniona_miedzy_odczytami_okna_emmetta_daje_niesprawdzona_propozycje(
    chrome: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Okno Emmetta narzędzie czyta kilkoma odczytami karty. Karta Maksa, która po pierwszym (okno jest widoczne) przejdzie
    # na listę zleceń, ma nie dać różnicy budowy z odczytów dwóch stron, tylko niesprawdzoną propozycję z prośbą o
    # ponowne kliknięcie Emmetta, jak odczyt, który padł w trakcie przejścia (#1039).
    efenix_url = f"http://efenix.test/{LIST_PAGE}"
    pages = {
        ORDER_PAGE: '<!doctype html><body><div id="dialog_emmett"><div id="emmett-propozycja"><ul><li>INDEKS_012_078: 3</li></ul></div></div></body>',
        LIST_PAGE: "<!doctype html><body><table></table></body>",
    }
    read = emmett_window

    def read_after_leaving(tab: Page) -> EmmettWindow:
        tab.goto(urljoin(efenix_url, LIST_PAGE))
        return read(tab)

    report = zgodnosc_efenix.Report()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(chrome)
        tab = browser.contexts[0].new_page()
        try:
            tab.route("http://efenix.test/**", lambda route: route.fulfill(content_type="text/html", body=pages[urlparse(route.request.url).path.lstrip("/")]))
            tab.goto(urljoin(efenix_url, f"{ORDER_PAGE}?id=7"))
            monkeypatch.setattr(zgodnosc_efenix, "emmett_window", read_after_leaving)
            monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
            zgodnosc_efenix.measure_proposal(browser, efenix_url, report, timeout_ms=10_000)
        finally:
            tab.close()

    assert (report.differences, report.unchecked) == ([], [(zgodnosc_efenix.Part.PROPOSAL, zgodnosc_efenix.READ_FAILED)])
    assert capsys.readouterr().err.splitlines() == [zgodnosc_efenix.ASK_EMMETT]


def test_lista_dozwolonych_zadan_ma_tylko_odczyty() -> None:
    names = {name for _method, name in zgodnosc_efenix.ALLOWED}

    assert not names & set(WRITES)
    assert not [name for name in names if any(word in name.casefold() for word in FORWARDING)]
    efenix = "https://efenix.example/app/index.php"
    for name in (*WRITES, "action_forward_to_accept.php", "action_forward_to_cancel.php", "action_fill_emmett.php"):
        for method in ("GET", "POST"):
            assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{name}?id=1", efenix), (method, name)
    for method, name in zgodnosc_efenix.ALLOWED:
        assert zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{name}?v=1", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"https://inny.example/app/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"http://efenix.example/app/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/{name}", efenix), (method, name)
        assert not zgodnosc_efenix.allowed("DELETE", f"https://efenix.example/app/{name}", efenix), name
    # Skrypt zapisu z dopisaną ścieżką (PATH_INFO serwera PHP) i ścieżka z ``..`` to inne strony niż dozwolone.
    for path in (f"{LOGOUT}/{LIST_PAGE}", f"{SAVE_QUANTITY}/{SEARCH}", f"js/../{LOGOUT}", f"{LIST_PAGE}/x.png"):
        for method in ("GET", "POST"):
            assert not zgodnosc_efenix.allowed(method, f"https://efenix.example/app/{path}", efenix), (method, path)


def test_karta_strony_zlecenia_to_strona_zlecenia_w_katalogu_i_na_hoscie_adresu_efenix() -> None:
    efenix = "https://efenix.example/app/index.php"

    assert zgodnosc_efenix.order_tab(f"https://efenix.example/app/{ORDER_PAGE}?id=1#dol", efenix)
    for url in (
        f"http://efenix.example/app/{ORDER_PAGE}?id=1",
        f"https://inny.example/app/{ORDER_PAGE}?id=1",
        f"https://efenix.example/{ORDER_PAGE}?id=1",
        f"https://efenix.example/app/{LIST_PAGE}",
        f"https://efenix.example/app/{ORDER_PAGE}/{LIST_PAGE}",
    ):
        assert not zgodnosc_efenix.order_tab(url, efenix), url


def test_efenix_bez_odpowiedzi_w_limicie_konczy_narzedzie_bledem(chrome: str, tmp_path: Path) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    # Szukanie odpowiada po 5 s, a limit czekania to 1 s; domyślny limit Playwrighta (30 s) doczekałby się odpowiedzi.
    with atrapa_efenix(ORDERS, cookie_session=True, answer_delay_s=5) as atrapa:
        checked = _run(chrome, atrapa.url, template, limit_ms=1000)

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", "BŁĄD | efenix nie odpowiada pod --efenix-url\n")


def test_zadanie_spoza_listy_dozwolonych_nie_wychodzi_do_efenix() -> None:
    with atrapa_efenix(ORDERS) as atrapa, sync_playwright() as playwright:
        request = playwright.request.new_context()
        try:
            efenix = zgodnosc_efenix._Efenix(request, atrapa.url, timeout_ms=10_000)
            with pytest.raises(ValueError, match=f"^GET {LOGOUT} nie jest na liście dozwolonych żądań$"):
                efenix.get(efenix.address(LOGOUT))
            with pytest.raises(ValueError, match=f"^POST {SAVE_QUANTITY} nie jest na liście dozwolonych żądań$"):
                efenix.post(efenix.address(SAVE_QUANTITY), {"order_id": ORDERS[0].order_id, "parametr": "1"})
        finally:
            request.dispose()

        assert atrapa.requested() == []


def test_wzorzec_bez_kolumn_kosztow_daje_koszty_bez_liczby(tmp_path: Path) -> None:
    path = tmp_path / "Wzorzec pliku zbiorczego.xlsx"
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    # Arkusz kończy się na kolumnie N, tuż przed O, pierwszą kolumną przypisania kolumn.
    sheet["M14"], sheet["N14"] = "Koszt", 7.0
    workbook.save(path)

    assert zgodnosc_efenix.template_costs(path) == dict.fromkeys(POSITION_OF_COLUMN, None)


def test_wzorzec_z_logiczna_wartoscia_kosztu_daje_koszt_bez_liczby(tmp_path: Path) -> None:
    path = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", {**COSTS, "O": True, "P": 12.5})

    costs = zgodnosc_efenix.template_costs(path)

    assert (costs["O"], costs["P"]) == (None, Decimal("12.5"))


@pytest.mark.parametrize("url", ["https://efenix.example/app/", "https://efenix.example/app/page_login.php", "ftp://efenix.example/app/index.php"])
def test_adres_efenix_inny_niz_lista_zlecen_konczy_narzedzie_bledem_przed_efenix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], url: str
) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)

    code = zgodnosc_efenix.main(["--efenix-url", url, "--wzorzec", str(template), "--cdp", _dead_endpoint()])

    assert (code, capsys.readouterr().err) == (1, f"BŁĄD | --efenix-url to adres listy zleceń efenix kończący się na /{LIST_PAGE}\n")


def test_narzedzie_bez_adresu_efenix_konczy_sie_bledem_polecenia(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        zgodnosc_efenix.main(["--cdp", _dead_endpoint()])

    assert exited.value.code == 2
    assert "--efenix-url" in capsys.readouterr().err


def test_bez_wzorca_w_poleceniu_narzedzie_czyta_wzorzec_z_konfiguracji(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Wzorzec z konfiguracji to plik ``config/`` checkoutu, u Maksa prawdziwy plik taty, więc test wskazuje inny.
    configured = tmp_path / "config" / "Wzorzec pliku zbiorczego.xlsx"
    monkeypatch.setattr(zgodnosc_efenix, "COLLECTIVE_TEMPLATE", configured)

    code = zgodnosc_efenix.main(["--efenix-url", "https://efenix.example/app/index.php", "--cdp", _dead_endpoint()])

    assert (code, capsys.readouterr().err) == (1, f"BŁĄD | Wzorzec pliku zbiorczego {configured}: brak pliku\n")
