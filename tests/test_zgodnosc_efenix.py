"""Narzędzie zgodności Atrapy efenix z efenix (``tools/zgodnosc_efenix.py``, #748) na Atrapie efenix.

Każdy test uruchamia narzędzie jak Maks: osobnym procesem, który łączy się przez zdalne debugowanie z Chromium (u Maksa
Chrome z sesją taty), a sprawdza to, co widać z zewnątrz: wynik (plik expect w ``tests/expected/zgodnosc_efenix/``),
kod wyjścia, żądania, które dostała Atrapa, i jej stan. Zgodna Atrapa daje wynik bez różnic, a Atrapa ze zmienioną
budową każdą różnicę; każdy wynik ma prośbę o ręczne sprawdzenie przycisku kalendarza daty wykonania. Każde żądanie, które dostaje Atrapa, jest z listy dozwolonych odczytów, także gdy skrypty i
elementy stron same wysyłają zapis albo wylogowanie, a nigdy propozycja Emmetta (``action_fill_emmett.php``): jej budowę
narzędzie czyta tylko z pliku ``--propozycja`` i porównuje z propozycją Atrapy. Wynik nie zawiera numerów zleceń, adresów, loginów ani
identyfikatorów, które Atrapa pokazuje, ani cen.

Budowę, której Atrapa nie umie zmienić sama (``Changed``, ``Unread``), zmienia serwer przed Atrapą (``_in_front``):
narzędzie łączy się z nim, a on przekazuje każde żądanie Atrapie i zmienia odpowiedź na wskazane strony (inny kod,
inna treść), jak efenix, którego autor zmienił jedną stronę.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
from urllib.parse import urlparse
from urllib.request import urlopen

from openpyxl import Workbook
from playwright.sync_api import sync_playwright
import pytest
import zgodnosc_efenix

from rozliczenia.efenix_browser import launch_options
from rozliczenia.efenix_positions import POSITION_OF_COLUMN

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
    emmett_proposal,
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
# Linia każdego wyniku bez pliku ``--propozycja`` (#953): narzędzie nie wysyła propozycji Emmetta.
PROPOSAL_BY_HAND = (
    "NIESPRAWDZONE | propozycja Emmetta | budowa propozycji Emmetta nie jest sprawdzana: narzędzie nie wysyła"
    " action_fill_emmett.php; zmierz ją plikiem --propozycja z propozycją zapisaną w Chrome (--help)"
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
    ``proposal``: treść pliku ``--propozycja`` z adresu listy zleceń, pod którym narzędzie widzi Atrapę (``None``: bez
    pliku).
    """

    expected: Path
    changed: Changed | Unread | None = None
    cookie_session: bool = True
    orders: tuple[AtrapaOrder, ...] = ORDERS
    costs: Mapping[str, CellValue] = field(default_factory=lambda: COSTS)
    number: str = ""
    rewrites: Mapping[str, Rewrite] = field(default_factory=dict)
    proposal: Callable[[str], str] | None = None


def _copied(html: str) -> Callable[[str], str]:
    """Plik propozycji, jak Maks kopiuje go w DevTools Chrome: element ``#emmett-propozycja`` z propozycją ``html``."""

    return lambda _url: f'<div id="emmett-propozycja">\n\t\t\t\t\t{html}\n\t\t\t\t</div>'


# Propozycja Emmetta Atrapy z pozycją z przypisania kolumn i spoza niego, w tym z ilością dwucyfrową.
EMMETT = {"012": 2, "005": 12}
# Propozycja Atrapy, przed którą odpowiedź ma elementy, które parser HTML z początku całej strony wkłada do ``<head>``.
HEAD_FIRST = '<meta charset="utf-8"><title>Emmett</title><style>.ilosc{}</style><script>pokaz()</script>' + emmett_proposal(EMMETT)


def _sending(url: str) -> str:
    """Propozycja Atrapy z elementami, które przeglądarka wysyła sama (obraz, ramka, styl, prefetch, przejście, skrypt),
    z adresami propozycji i Załadowania Emmetta, zmiany statusu i wylogowania pod adresem efenix ``url``."""

    folder = url.rpartition("/")[0]
    return (
        f'<div id="emmett-propozycja">{emmett_proposal(EMMETT)}'
        f'<img src="{folder}/{LOAD_EMMETT}?order_id=ID-TAJNE-72"><iframe src="{folder}/{FILL_EMMETT}"></iframe>'
        f'<link rel="stylesheet" href="{folder}/{SAVE_QUANTITY}"><link rel="prefetch" href="{folder}/{FILL_EMMETT}?order_id=ID-TAJNE-72">'
        f'<meta http-equiv="refresh" content="0;url={folder}/{CHANGE_STATUS}?order_id=ID-TAJNE-72&amp;xstatus=Anulowane">'
        f"<script>fetch('{folder}/{FILL_EMMETT}', {{method: 'POST', body: 'order_id=ID-TAJNE-72'}}); navigator.sendBeacon('{folder}/{LOGOUT}');</script>"
        "</div>"
    )


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
    # Szukanie bez sesji przekierowane na stronę logowania, jak Atrapa przed #828, zamiast ostrzeżenia efenix.
    "szukanie-bez-sesji-przekierowuje-na-logowanie": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "szukanie-bez-sesji-przekierowuje-na-logowanie.txt",
        rewrites={SEARCH: _to_login_if_warned},
    ),
    # Propozycja w oknie Emmetta ma tekst na stronie zlecenia, zanim skrypt włoży do niej propozycję.
    "propozycja-pokazuje-cos-przed-propozycja": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-pokazuje-cos-przed-propozycja.txt",
        rewrites={ORDER_PAGE: _replaced(('<div id="emmett-propozycja"></div>', '<div id="emmett-propozycja">Wczytywanie propozycji</div>'))},
    ),
    # Propozycja w polach z klasami bez tekstu (kod w ``name``, ilość w ``value``), a nie w tekście listy, jak w Atrapie.
    "propozycja-w-polach": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-w-polach.txt",
        proposal=_copied(emmett_proposal(EMMETT, in_fields=True).replace("<input ", '<input class="wycena-ilosc form-control" ')),
    ),
    "propozycja-pusta": Variant(ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-pusta.txt", proposal=_copied("")),
    # Sama odpowiedź (zakładka Network) z elementami, które parser całej strony przeniósłby do ``<head>``, a które w
    # ``#emmett-propozycja`` efenix zostają, i ten sam element skopiowany w DevTools: obie dają te same różnice.
    "propozycja-z-odpowiedzi-ze-skryptem-i-stylem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-ze-skryptem-i-stylem.txt", proposal=lambda _url: HEAD_FIRST
    ),
    "propozycja-skopiowana-ze-skryptem-i-stylem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-ze-skryptem-i-stylem.txt", proposal=_copied(HEAD_FIRST)
    ),
    # Odpowiedź z samym skryptem: Emmett nic nie proponuje, ale okno Emmetta w efenix ma dziecko, więc coś pokazało (#908).
    "propozycja-z-odpowiedzi-z-samym-skryptem": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-z-samym-skryptem.txt", proposal=lambda _url: "<script>pokaz()</script>"
    ),
    "propozycja-z-elementami-ktore-wysylaja": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-z-elementami-ktore-wysylaja.txt", proposal=_sending
    ),
    "logowanie-bez-formularza-i-pol": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "logowanie-bez-formularza-i-pol.txt",
        rewrites={
            LOGIN_PAGE: _replaced(('action="action_login.php"', 'action="zaloguj.php"'), ('id="field_signum"', 'id="login"'), ('id="field_password"', 'id="haslo"'))
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
    "propozycja-jak-w-atrapie": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-jak-w-atrapie.txt", proposal=_copied(emmett_proposal(EMMETT))
    ),
    # Sama odpowiedź ``action_fill_emmett.php`` (zakładka Network), bez elementu ``#emmett-propozycja``.
    "propozycja-z-odpowiedzi": Variant(
        ROOT / "tests" / "expected" / "zgodnosc_efenix" / "propozycja-jak-w-atrapie.txt", proposal=lambda _url: emmett_proposal(EMMETT)
    ),
}


@dataclass(frozen=True)
class Checked:
    code: int
    stdout: str
    stderr: str


@pytest.fixture(scope="module")
def chrome() -> Iterator[str]:
    """Chromium ze zdalnym debugowaniem (jak Chrome Maksa) i ciasteczkiem sesji Atrapy w domyślnym kontekście.

    Chromium i jego Playwright żyją w osobnym wątku, który przez cały czas obsługuje Playwrighta, jak osobny program
    Chrome u Maksa. Playwright, który uruchomił przeglądarkę, a którego nikt nie obsługuje, bo test czeka na proces
    narzędzia, na Windows wstrzymuje przeglądarkę: jego sterownik pisze do pełnej rury procesu testu i przestaje
    wznawiać nowe karty, więc karta, w której narzędzie składa HTML, nie wczytuje się (#755, CI na windows-2025).
    """

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    started: queue.Queue[BaseException | None] = queue.Queue()
    stop = threading.Event()

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
                        idle.wait_for_timeout(50)
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
        yield endpoint
    finally:
        stop.set()
        owner.join()


def _run(endpoint: str, url: str, template: Path, *extra: str, limit_ms: int = 10_000) -> Checked:
    done = subprocess.run(
        [sys.executable, str(TOOL), "--efenix-url", url, "--cdp", endpoint, "--limit-ms", str(limit_ms), "--wzorzec", str(template), *extra],
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
            extra = ["--numer", variant.number]
            if variant.proposal is not None:
                proposal = tmp_path / "propozycja.html"
                proposal.write_text(variant.proposal(url), encoding="utf-8")
                extra += ["--propozycja", str(proposal)]
            checked = _run(endpoint, url, template, *extra)
        assert (atrapa.state(), _pages(endpoint)) == (state, pages)
    assert not [text for text in PRIVATE if text in checked.stdout + checked.stderr]
    assert DATE_BUTTON_BY_HAND in checked.stdout.splitlines()
    assert (PROPOSAL_BY_HAND in checked.stdout.splitlines()) == (variant.proposal is None)
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


def test_nieczytelny_plik_propozycji_konczy_narzedzie_bledem_przed_efenix(chrome: str, tmp_path: Path) -> None:
    template = write_template_costs(tmp_path / "Wzorzec pliku zbiorczego.xlsx", COSTS)
    proposal = tmp_path / "propozycja.html"
    proposal.write_bytes(b"<ul><li>INDEKS_012_078: \xff</li></ul>")
    with atrapa_efenix(ORDERS, cookie_session=True) as atrapa:
        checked = _run(chrome, atrapa.url, template, "--propozycja", str(proposal))

    assert (checked.code, checked.stdout, checked.stderr) == (1, "", f"BŁĄD | plik --propozycja {proposal}: nie da się go przeczytać jako tekstu UTF-8\n")
    assert atrapa.requested() == []


def test_przejscie_w_karcie_skladania_zostawia_zlozony_html(chrome: str) -> None:
    # Przejście ramki kończy się przed zdarzeniem ``load``, na które czeka złożenie strony, więc po nim widać, czy ramka
    # przeszła na inną stronę (bez odpowiedzi 204 przeglądarka pokazałaby w niej stronę błędu połączenia).
    with atrapa_efenix(ORDERS) as atrapa, sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(chrome)
        with zgodnosc_efenix.parser_page(browser, timeout_ms=10_000) as page:
            page.set_content(f'<p>Złożony HTML</p><iframe src="{atrapa.url}"></iframe>')
            shown = (page.locator("p").inner_text(), [frame.content() for frame in page.main_frame.child_frames])

        assert shown == ("Złożony HTML", ["<html><head></head><body></body></html>"])
        assert atrapa.requested() == []


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
    monkeypatch.setattr(zgodnosc_efenix, "default_collective_template_path", lambda: configured)

    code = zgodnosc_efenix.main(["--efenix-url", "https://efenix.example/app/index.php", "--cdp", _dead_endpoint()])

    assert (code, capsys.readouterr().err) == (1, f"BŁĄD | Wzorzec pliku zbiorczego {configured}: brak pliku\n")
