"""Atrapa efenix: lokalny serwer HTTP z wymyślonymi zleceniami w budowie stron efenix (ADR 0024).

Odtwarza tylko to, czego używa okno efenix narzędzia: identyfikatory pól (``#field_numer``, ``#wyniki``, ``#data_install``,
``#field_signum``, ``#field_password``), adresy odpowiedzi (``action_fill_orders.php``, ``page_order_edit.php?id=``,
``page_login.php``) i kształt komórek tabeli wyników (``Numer dokumentu<br><small>Identyfikator Fenix</small>``, status
w ``.badge``, ``Wykonawca <small><small class="text-default">(login)</small></small><br><small>`` z datą w ``.badge``,
``<small>województwo</small><br>Dane adresowe``). Skrypty stron leżą jak w efenix w plikach, które strony ładują
(``LIST_SCRIPT``, ``ORDER_SCRIPT``). Skrypt listy to własny,
krótki kod Atrapy: Enter w polu ``Numer`` wysyła do ``action_fill_orders.php`` pola skryptu listy efenix
(``LIST_SEARCH_FIELDS``) z liczbą wierszy z pola ``#field_na_stronie`` (domyślnie ``10``) i wkłada odpowiedź do
``#wyniki``, a po wczytaniu, gdy karta pamięta numer z poprzedniego szukania (``sessionStorage``), sama szuka go
jeszcze raz, jak efenix po powrocie ze strony zlecenia na listę. Szukanie bez liczby wierszy (``na_stronie``) dostaje,
jak w efenix, stronę błędu bazy danych bez tabeli wyników, a szukanie, które nie znajduje żadnego zlecenia (numer, którego
Atrapa nie ma, albo pusty ``xrodzaj``), jak w efenix (pomiar 4.11.2026, #828) samo ostrzeżenie „Nie znaleziono pasujących
wyników” bez tabeli. Nie ma w niej żadnego kodu, stylu ani danych z efenix poza tekstem ostrzeżeń, który rozpoznaje okno.

Strona zlecenia ma wycenę ze stanem: pozycje z wymyślonymi cenami (``CATALOG``: kody ``INDEKS_NNN_078`` stron efenix,
z przypisania kolumn i bez niego) w kartach ``.card.rounded-lg.kolorek`` jak w efenix: karta z polem
``input.wycena-ilosc`` ma cenę w tekście ``.col-sm-1.mt-2 > span.text-default > small``, a dwie karty z ceną wpisywaną
mają samo pole ``.wycena-cena``. Zlecenie z ``AtrapaOrder.without`` ma stronę bez kart części pozycji, jak zlecenia
efenix, których strona ma mniej pozycji wyceny. Strona ma kwotę końcową ``#cena_all2``, datę
wykonania z oknem ``#dialog_select_date`` (przycisk ``#button-calendar``, pole ``#field_data_instalacji`` z własnym
kalendarzem Atrapy w API pickadate: ``jQuery(pole).pickadate('picker').set('select', …)``). Jak w efenix pole nie
przyjmuje pisania, a kalendarz po otwarciu okna pokazuje dzisiejszy dzień, dzień po dziś albo przed pierwszym dniem
poprzedniego miesiąca zamienia na dzisiejszy z komunikatem w ``#toast``, „Potwierdź” wysyła wartość pola, a po
odpowiedzi 2xx wpisuje ją do ``#data_install`` bez czytania treści odpowiedzi. „Dziś” daje test (``today``), a
``refuse_dates`` każe serwerowi odpowiadać na zapis daty bez zapisu. Wycenę Emmetta (``#button_emmett``,
okno ``#dialog_emmett`` z propozycją z ``action_fill_emmett.php``, „Załaduj do zlecenia” wysyła ``action_load_emmett.php``,
który czyści wycenę i wpisuje propozycję, a skrypt przeładowuje stronę po każdej odpowiedzi, także po odmowie
``AtrapaOrder.emmett_refusal``) i przyciski, których narzędzie nie może użyć:
Przekazanie do akceptacji (``#button_forward_to_accept``) i anulowanie (``#button_forward_to_cancel``) z oknem
``#dialog_forward_yes_no``, którego ``.btn-ok`` wysyła ``action_change_status.php`` (``order_id``, ``xstatus``,
``comment``, jak efenix) i stoi na stronie przed oknem Emmetta. Okna zamyka przycisk ``[data-dismiss="modal"]``.
Ilość zapisuje skrypt strony po wyjściu z pola (Enter też z niego wychodzi) przez ``action_save_index.php``, a odpowiedź
JSON (``result``, ``price_index``, ``price_all``) odświeża ``#cena-…`` i ``#cena_all2``; bez sesji ta odpowiedź to
``result: nok``, jak w efenix.

Atrapa ma jedną sesję, jak okno taty z zapamiętanym logowaniem: po starcie jest zalogowana, ``expire_session`` i
``action_logout.php`` ją kończą, a wtedy każda strona i odpowiedź przekierowuje na ``page_login.php``, poza zapisem
ilości (``result: nok``) i szukaniem, na które Atrapa, jak efenix (pomiar 4.11.2026, #828), odpowiada 200 z samym
ostrzeżeniem o wygasłej sesji (tekst efenix, który rozpoznaje okno, w znacznikach Atrapy); formularz
logowania (``action_login.php`` z polem ``fingerprint``, jak w efenix) albo ``log_in`` (tata loguje się w swoim oknie)
loguje z powrotem. ``cookie_session`` wiąże sesję z ciasteczkiem ``SESSION_COOKIE``, więc żądanie bez niego widzi stronę
logowania, a sesja z ciasteczkiem trwa. Pliki skryptów Atrapa daje także bez sesji, jak serwer plików. ``requests`` to
każde żądanie po kolei (metoda, ścieżka, parametry i chwila z zegara ``clock``), więc test widzi, czego narzędzie użyło
i kiedy.
``answer_delay_s`` opóźnia każdą odpowiedź na szukanie, więc szukanie, które lista wysyła sama, trwa jeszcze, gdy
narzędzie szuka swojego numeru. ``changed`` psuje budowę jednej części strony tak, jak mógłby ją zmienić autor efenix
(``Changed``, a w części, której Wycena w efenix w testach nie używa, a sprawdza narzędzie zgodności, ``Unread``).
``outage_from`` w trakcie przebiegu odcina efenix od żądania o danym numerze (``Outage``: zerwane połączenie, także w połowie
odpowiedzi, odpowiedź, która staje w połowie, albo efenix wolniejszy niż okno), aż test przywróci połączenie
(``reconnect``), jak sieć taty, która na chwilę znika.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
import enum
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import struct
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

LIST_PAGE = "index.php"
SEARCH = "action_fill_orders.php"
ORDER_PAGE = "page_order_edit.php"
LOGIN_PAGE = "page_login.php"
SAVE_QUANTITY = "action_save_index.php"
FILL_EMMETT = "action_fill_emmett.php"
LOAD_EMMETT = "action_load_emmett.php"
SET_DATE = "action_set_date_of_instalation.php"
GET_DATE = "action_get_date_of_instalation.php"
CHANGE_STATUS = "action_change_status.php"
LOGIN_ACTION = "action_login.php"
LOGOUT = "action_logout.php"
LIST_SCRIPT = "js/index.js"
ORDER_SCRIPT = "js/page_order_edit.js"
SESSION_COOKIE = ("PHPSESSID", "atrapa-efenix")
# Pole ``rodzaj`` szukania, które skrypt listy wysyła sam po wczytaniu strony.
BY_LIST = "powrot"
# Pola szukania, które skrypt listy efenix wysyła do ``SEARCH`` w domyślnym stanie listy, w jego kolejności (odczyt
# efenix z 4.11.2026, #822). ``xrodzaj`` skrypt bierze z ``<select multiple>``, którego jedyna zaznaczona opcja jest
# wyłączona, więc wartość to pusta tablica, a jQuery ``$.ajax`` klucza z pustą tablicą nie wysyła.
LIST_SEARCH_FIELDS = (
    "id", "numer", "xstatus", "asp", "rodzaj", "strona", "na_stronie", "wojewodztwo", "powiat", "gmina", "miasto",
    "ulica", "realizator", "owner", "operator", "data_od", "data_do", "data_do_akceptacji", "ulica_numer", "adres_id", "sortowanie",
)
# Liczba wierszy tabeli wyników w domyślnym ustawieniu listy (pole ``#field_na_stronie``), jak w efenix.
LIST_ROWS_PER_PAGE = "10"
# Odpowiedź efenix na szukanie bez liczby wierszy: strona błędu zapytania z pustym limitem wierszy (tekst wymyślony).
_NO_ROW_LIMIT = "<p>Błąd bazy danych: zapytanie bez liczby wierszy.</p>"
# Odpowiedzi efenix na szukanie bez tabeli wyników, samym ostrzeżeniem (pomiar 4.11.2026, #828): szukanie, które nie
# znajduje żadnego zlecenia, i szukanie bez sesji. Zdanie i puste linie przed nim są jak w efenix, a znaczniki są Atrapy.
_NOT_FOUND = '\r\n\n\r\n\r\n<p class="alert alert-danger"><strong>Ostrzeżenie: </strong>Nie znaleziono pasujących wyników !</p>'
_SESSION_EXPIRED = '\r\n\n\r\n\r\n<p class="alert alert-danger"><strong>Ostrzeżenie: </strong>Twoja sesja wygasła - zaloguj się ponownie !</p>'
# Ostrzeżenie, którego okno nie zna, bez tabeli wyników (``Changed.RESULTS_WARNING``, tekst wymyślony).
_OTHER_WARNING = '<p class="alert alert-danger"><strong>Ostrzeżenie: </strong>Lista zleceń jest chwilowo niedostępna !</p>'
TODAY = date(2026, 10, 12)
"""Dzień, który kalendarz Atrapy ma za dzisiejszy, gdy test nie poda innego: dni z ``DATA`` testów (wrzesień 2026) są
w zakresie, który przyjmuje efenix."""


def earliest_execution_date(today: date) -> date:
    """Pierwszy dzień poprzedniego miesiąca: najwcześniejsza data wykonania, którą przyjmuje kalendarz efenix."""

    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


class Changed(enum.Enum):
    """Część strony Atrapy w innej budowie niż w efenix, który zna narzędzie."""

    STATUS_HEADER = "nagłówek Status tabeli wyników ma inną nazwę"
    ORDER_LINK = "wiersz wyników nie ma linku do strony zlecenia"
    RESULTS_WARNING = "szukanie odpowiada ostrzeżeniem, którego okno nie zna, bez tabeli wyników"
    DATE_FORMAT = "data wykonania w innym zapisie niż RRRR-MM-DD"
    DATE_DIALOG = "przycisk kalendarza nie otwiera okna daty wykonania"
    EMMETT_BUTTON = "strona zlecenia nie ma przycisku Emmetta"
    HIDDEN_EMMETT = "przycisk Emmetta jest na stronie, ale niewidoczny"
    STALE_AMOUNT = "kwota końcowa nie odświeża się po zapisie ilości"
    QUANTITY_ANSWER = "zapis ilości odpowiada stroną HTML, a nie JSON z kwotą końcową"
    QUANTITY_VALUE = "pole Ilość pozycji 012 ma wartość, która nie jest liczbą całkowitą (1.5)"


class Unread(enum.Enum):
    """Część strony Atrapy w innej budowie, której testy Wyceny w efenix nie używają, a sprawdza narzędzie zgodności."""

    ORDER_PARTS = (
        "strona zlecenia bez przycisku Emmetta i pola kalendarza w oknie daty wykonania, a przycisk kalendarza ma tylko przy"
        " pustej dacie wykonania, jak efenix w rekonesansie"
    )
    PRICE_LIST = "jedna pozycja wyceny ma inny kod, a druga cenę wpisywaną zamiast pola Ilość"
    PRICE_TEXT = "ceny pozycji w tekście karty z przecinkiem (21,00), a nie z kropką"
    LOGIN_FORM = "formularz logowania bez pola fingerprint"
    SCRIPTS = "skrypt listy szuka bez pola numer, a strona zlecenia ma skrypt w stronie, a nie w js/page_order_edit.js"
    SCRIPT_ADDRESSES = "lista ładuje skrypt z #fragmentem w adresie, a strona zlecenia z ;parametrem"
    ORDER_REDIRECT = "strona zlecenia przekierowuje na wylogowanie (action_logout.php)"
    HOSTILE = "skrypty i elementy stron po wczytaniu i przy opuszczeniu zapisują, zmieniają status i wylogowują"


class Outage(enum.Enum):
    """Jak Atrapa nie odpowiada na żądania, gdy efenix jest odcięty (``outage_after``)."""

    CUT = "zrywa połączenie każdego żądania bez odpowiedzi i bez wykonania żądania, jak sieć, która zniknęła"
    SLOW = "wykonuje każde żądanie, a odpowiedź wysyła dopiero na końcu bloku, jak efenix wolniejszy niż czas okna"
    TORN = "wykonuje każde żądanie i zaczyna odpowiedź, ale zrywa połączenie w połowie jej treści, jak sieć, która zniknęła w trakcie pliku"
    STALLED = (
        "wykonuje każde żądanie i zaczyna odpowiedź, a po połowie jej treści milknie do końca bloku, jak sieć, która stanęła w"
        " trakcie pliku bez zerwania połączenia"
    )


class EmmettRefusal(enum.Enum):
    """Jak efenix odmawia „Załaduj do zlecenia” zlecenia (``AtrapaOrder.emmett_refusal``); skrypt strony i tak ją
    przeładowuje, bo czeka tylko na koniec odpowiedzi, a nie na jej status."""

    FORBIDDEN = "HTTP 403 bez załadowania Wyceny Emmetta"
    SERVER_ERROR = "HTTP 500 po załadowaniu Wyceny Emmetta"
    ELSEWHERE = "przekierowanie na listę zleceń bez załadowania Wyceny Emmetta"
    LOGGED_OUT = "sesja wygasa przy tym żądaniu: przekierowanie na stronę logowania bez załadowania Wyceny Emmetta"
    NOK = "200 z JSON result: nok bez załadowania Wyceny Emmetta"


@dataclass(frozen=True)
class Position:
    """Pozycja wyceny Atrapy: kod ``NNN``, wymyślona cena i rodzaj pola (``ILOSC`` albo ``CENA``)."""

    code: str
    price: Decimal
    kind: str = "ILOSC"


# Kody pozycji stron efenix (z przypisania kolumn Wyceny w efenix i bez niego); ceny są wymyślone, bo ceny efenix to
# ceny umowy taty z firmą.
CATALOG = (
    *(
        Position(code, Decimal(price))
        for code, price in [
            ("005", "11.00"), ("007", "12.00"), ("008", "13.00"), ("009", "14.00"), ("010", "15.00"), ("012", "21.00"),
            ("013", "22.00"), ("014", "23.00"), ("015", "24.00"), ("016", "3.00"), ("017", "25.00"), ("018", "26.00"),
            ("019", "4.00"), ("020", "27.00"), ("021", "28.00"), ("023", "61.00"), ("024", "62.00"), ("025", "63.00"),
            ("026", "64.00"), ("027", "41.00"), ("028", "42.00"), ("029", "31.00"), ("022", "29.00"), ("033", "32.00"),
            ("034", "33.00"), ("035", "34.00"), ("036", "35.00"), ("037", "36.00"), ("038", "37.00"), ("039", "38.00"),
            ("040", "39.00"), ("041", "43.00"), ("042", "44.00"), ("044", "45.00"), ("046", "46.00"), ("047", "47.00"),
            ("050", "51.00"), ("051", "52.00"), ("052", "53.00"), ("053", "54.00"), ("054", "55.00"),
        ]
    ),
    Position("045", Decimal("1.00"), "CENA"),
    Position("032", Decimal("1.00"), "CENA"),
)
PRICES = {position.code: position.price for position in CATALOG}
EFENIX_EMMETT_RELOAD_MS = 1000
"""Przeładowanie strony, które skrypt efenix robi po odpowiedzi „Załaduj do zlecenia”: w efenix po 1 s."""
# W Atrapie domyślnie krócej, żeby testy szły szybko.
_EMMETT_RELOAD_MS = 200


def amount_of(quantities: Mapping[str, int]) -> Decimal:
    """Kwota końcowa wyceny z ilościami ``quantities`` (kod → ilość) w cenach Atrapy."""

    return sum((PRICES[code] * quantity for code, quantity in quantities.items()), Decimal("0.00"))


@dataclass
class AtrapaOrder:
    """Wymyślone zlecenie Atrapy w tym, co pokazują lista i strona zlecenia efenix.

    ``quantities``: ilości wyceny (kod → ilość różna od 0), ``emmett``: propozycja Emmetta w tym samym kształcie,
    ``emmett_loads``: ile razy załadowano do zlecenia Wycenę Emmetta. ``changed``: strona tylko tego zlecenia w innej
    budowie (``Changed``), a ``cut``: strona tego zlecenia zrywa połączenie bez odpowiedzi, jak sieć, która zniknęła, więc
    zlecenia przed nim przechodzą jak w efenix. ``error_status``: strona tego zlecenia to strona błędu serwera z tym
    statusem HTTP, a ``login_form``: formularz logowania pod adresem strony zlecenia, bez przekierowania. ``hung``: strona
    tego zlecenia nie odpowiada do końca bloku, jak efenix, który stanął, więc test może zgasić Centrum w trakcie
    zlecenia. ``without``: kody pozycji, których karty strona tego zlecenia nie ma, jak strony efenix z częścią pozycji
    wyceny. Z ``after_date`` każda z tych czterech zmian strony jest dopiero od zapisu daty wykonania, a z ``after_emmett``
    od przeładowania po załadowaniu Wyceny Emmetta. ``emmett_refusal``: efenix odmawia „Załaduj do zlecenia” tego
    zlecenia (``EmmettRefusal``), aż test to zmieni.
    """

    order_id: str
    number: str
    realizator: str
    address: str
    status: str = "Do wyceny"
    execution_date: date | None = None
    executor: str = "Firma Testowa Jan Fikcyjny"
    region: str = "WOJEWODZTWO-Miasto-Gmina-Dzielnica"
    operator: str = "OPERATOR"
    quantities: dict[str, int] = field(default_factory=dict)
    emmett: dict[str, int] = field(default_factory=dict)
    emmett_loads: int = 0
    changed: Changed | None = None
    cut: bool = False
    error_status: HTTPStatus | None = None
    login_form: bool = False
    hung: bool = False
    without: frozenset[str] = frozenset()
    after_date: bool = False
    after_emmett: bool = False
    emmett_refusal: EmmettRefusal | None = None

    @property
    def amount(self) -> Decimal:
        return amount_of(self.quantities)


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: Mapping[str, str]
    at: float = 0.0

    @property
    def by_list(self) -> bool:
        """Szukanie, które skrypt listy wysłał sam po wczytaniu strony, a nie po Enter w polu ``Numer``."""

        return self.path == SEARCH and self.params.get("rodzaj") == BY_LIST


@dataclass
class AtrapaEfenix:
    """Stan Atrapy: zlecenia, sesja i dziennik żądań; ``url`` to adres listy zleceń."""

    orders: list[AtrapaOrder]
    url: str = ""
    logged_in: bool = True
    outage: Outage | None = None
    requests: list[Request] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def expire_session(self) -> None:
        with self._lock:
            self.logged_in = False

    def log_in(self) -> None:
        """Tata zalogował się w efenix (w tej samej sesji, w której pracuje okno narzędzia)."""

        with self._lock:
            self.logged_in = True

    def reconnect(self) -> None:
        """Połączenie z efenix wróciło: Atrapa znów odpowiada na każde żądanie (odpowiedzi wstrzymane przez ``SLOW`` i
        ``STALLED`` dalej czekają na koniec bloku)."""

        with self._lock:
            self.outage = None

    def edit(self, number: str, change: Callable[[AtrapaOrder], object]) -> None:
        """Tata sam zmienia w efenix zlecenie ``number``: ``change`` dostaje jego stan w Atrapie."""

        with self._lock:
            [order] = [order for order in self.orders if order.number == number]
            change(order)

    def state(self) -> tuple[list[AtrapaOrder], bool]:
        """Kopia zleceń i sesji do porównania stanu przed przebiegiem i po nim."""

        with self._lock:
            return copy.deepcopy(self.orders), self.logged_in

    def requested(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(request.method, request.path) for request in self.requests]

    def searched(self) -> list[str]:
        """Numery z każdego szukania z pola ``Numer`` po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.path == SEARCH and not request.by_list]

    def moments(self) -> list[tuple[float, str]]:
        """Chwila z zegara Atrapy i ścieżka każdego żądania po kolei."""

        with self._lock:
            return [(request.at, request.path) for request in self.requests]

    def status_changes(self) -> int:
        """Ile żądań zmiany statusu (Przekazanie do akceptacji, anulowanie) dostała Atrapa."""

        with self._lock:
            return sum(request.path == CHANGE_STATUS for request in self.requests)

    def searched_by_list(self) -> list[str]:
        """Numery z każdego szukania, które lista wysłała sama po wczytaniu, po kolei."""

        with self._lock:
            return [request.params.get("numer", "") for request in self.requests if request.by_list]


@contextmanager
def atrapa_efenix(
    orders: Sequence[AtrapaOrder],
    *,
    expire_after: tuple[str, int] | None = None,
    changed: Changed | Unread | None = None,
    answer_delay_s: float = 0.0,
    today: date = TODAY,
    refuse_dates: bool = False,
    clock: Callable[[], float] = time.monotonic,
    cookie_session: bool = False,
    outage_from: tuple[Outage, int] | None = None,
    error_answer: tuple[str, int, HTTPStatus] | None = None,
    emmett_reload_ms: int = _EMMETT_RELOAD_MS,
) -> Iterator[AtrapaEfenix]:
    """Uruchamia Atrapę na wolnym porcie ``127.0.0.1`` na czas bloku i zamyka ją razem z jej wątkiem.

    ``expire_after``: ścieżka i liczba jej żądań narzędzia (bez szukania, które lista wysyła sama), po których sesja
    wygasa raz, jak przy wylogowaniu w trakcie przebiegu; po ponownym zalogowaniu już nie wygasa. ``today``: dzisiejszy
    dzień kalendarza daty wykonania. ``refuse_dates``: serwer odpowiada na zapis daty wykonania bez zapisu. ``clock``:
    zegar w sekundach, którego chwilę dostaje każde żądanie. ``outage_from``: rodzaj odcięcia i numer żądania (od 0, każde
    żądanie po kolei, jak w ``requests``), od którego efenix jest odcięty raz, do ``reconnect``. ``emmett_reload_ms``: po
    ilu milisekundach od odpowiedzi „Załaduj do zlecenia” skrypt strony ją przeładowuje (w efenix
    ``EFENIX_EMMETT_RELOAD_MS``, domyślnie krócej). Atrapa pracuje na kopii
    ``orders``, więc zlecenia testu zostają bez zmian także wtedy, gdy żądanie zmieni ich stan w Atrapie.
    ``error_answer``: ścieżka, numer jej żądania narzędzia (od 1, bez szukania, które lista wysyła sama) i status błędu
    HTTP: na to jedno żądanie Atrapa odpowiada stroną błędu serwera z tym statusem, bez wykonania żądania.
    """

    atrapa = AtrapaEfenix(copy.deepcopy(list(orders)))
    expired = threading.Event()
    cut_off = threading.Event()
    # Koniec bloku przerywa opóźnione odpowiedzi i zamyka otwarte połączenia, więc żaden wątek obsługi nie czeka dłużej
    # niż Atrapa, a po bloku nic już pod jej adresem nie odpowiada.
    closing = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        # Połączenia trwałe: przeglądarka wysyła kolejne żądania kilkoma połączeniami, a nie nowym na każde żądanie, jak
        # przy HTTP/1.0, co pod xdist na Windows wyczerpywało gniazda (``net::ERR_NO_BUFFER_SPACE``, #778). Każda
        # odpowiedź ma ``Content-Length``.
        protocol_version = "HTTP/1.1"
        # Odpowiedź żądania, które Atrapa wykonała, gdy efenix był wolny (``Outage.SLOW``), czeka na koniec bloku, a gdy
        # sieć zrywała odpowiedzi (``Outage.TORN``) albo stawała (``Outage.STALLED``), urywa się albo staje w połowie treści
        # (przekierowanie bez treści przychodzi całe).
        _late = False
        _torn = False
        _stalled = False

        def handle(self) -> None:
            try:
                super().handle()
            except OSError as error:
                # Przeglądarka zrywa połączenie, na które już nie czeka (karta przeszła na inną stronę albo zamknięta),
                # a koniec bloku zamyka połączenia, na których przeglądarka czeka na odpowiedź albo wysyła następne żądanie.
                if not (isinstance(error, ConnectionError) or closing.is_set()):
                    raise

        def do_GET(self) -> None:
            self._answer("GET", {})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8")
            self._answer("POST", {name: values[0] for name, values in parse_qs(body, keep_blank_values=True).items()})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _answer(self, method: str, form: dict[str, str]) -> None:
            url = urlparse(self.path)
            path = url.path.lstrip("/") or LIST_PAGE
            params = {name: values[0] for name, values in parse_qs(url.query).items()} | form
            with atrapa._lock:
                atrapa.requests.append(Request(method, path, params, clock()))
                if expire_after is not None and path == expire_after[0] and not expired.is_set():
                    if sum(request.path == path and not request.by_list for request in atrapa.requests) > expire_after[1]:
                        atrapa.logged_in = False
                        expired.set()
                if outage_from is not None and len(atrapa.requests) > outage_from[1] and not cut_off.is_set():
                    atrapa.outage = outage_from[0]
                    cut_off.set()
                outage = atrapa.outage
                failing = (
                    error_answer is not None
                    and path == error_answer[0]
                    and not atrapa.requests[-1].by_list
                    and sum(request.path == path and not request.by_list for request in atrapa.requests) == error_answer[1]
                )
                logged_in = atrapa.logged_in and (not cookie_session or _has_session_cookie(self.headers.get("Cookie", "")))
                orders = copy.deepcopy(atrapa.orders)
            if outage is Outage.CUT:
                self._cut()
                return
            self._late = outage is Outage.SLOW
            self._torn = outage is Outage.TORN
            self._stalled = outage is Outage.STALLED
            if failing and error_answer is not None:
                self._html("<p>Wystąpił błąd serwera.</p>", error_answer[2])
            elif path == LOGIN_ACTION and method == "POST":
                with atrapa._lock:
                    atrapa.logged_in = True
                self._redirect(LIST_PAGE, cookie=cookie_session)
            elif path == LOGIN_PAGE:
                self._html(_login_page(changed))
            elif path == LIST_SCRIPT and method == "GET":
                self._html(_list_script(changed), content_type="text/javascript")
            elif path == ORDER_SCRIPT and method == "GET":
                self._html(_order_script(changed, today, emmett_reload_ms), content_type="text/javascript")
            elif not logged_in and path == SAVE_QUANTITY:
                self._json({"result": "nok", "error": "Brak sesji."})
            elif not logged_in and path == SEARCH and method == "POST":
                self._html(_SESSION_EXPIRED)
            elif not logged_in:
                self._redirect(LOGIN_PAGE)
            elif path == LOGOUT:
                with atrapa._lock:
                    atrapa.logged_in = False
                self._redirect(LOGIN_PAGE)
            elif method == "POST" and path == LOAD_EMMETT and (refusal := _emmett_refusal(orders, params)) is not None:
                match refusal:
                    case EmmettRefusal.FORBIDDEN:
                        self._html("<p>Brak dostępu.</p>", HTTPStatus.FORBIDDEN)
                    case EmmettRefusal.SERVER_ERROR:
                        with atrapa._lock:
                            [order] = [order for order in atrapa.orders if order.order_id == params.get("order_id")]
                            _change(path, order, params, refuse_dates=refuse_dates)
                        self._html("<p>Wystąpił błąd serwera.</p>", HTTPStatus.INTERNAL_SERVER_ERROR)
                    case EmmettRefusal.ELSEWHERE:
                        self._redirect(LIST_PAGE)
                    case EmmettRefusal.LOGGED_OUT:
                        with atrapa._lock:
                            atrapa.logged_in = False
                        self._redirect(LOGIN_PAGE)
                    case EmmettRefusal.NOK:
                        self._json({"result": "nok", "error": "Nie załadowano."})
            elif method == "POST" and path in _CHANGES:
                with atrapa._lock:
                    found = [order for order in atrapa.orders if order.order_id == params.get(_CHANGES[path])]
                    answer = _change(path, found[0], params, refuse_dates=refuse_dates) if found else None
                if answer is None:
                    self._html("<p>Nie ma takiego zlecenia.</p>", HTTPStatus.NOT_FOUND)
                elif isinstance(answer, dict) and changed is Changed.QUANTITY_ANSWER:
                    self._html("<p>Zapisano.</p>")
                elif isinstance(answer, dict):
                    self._json(answer)
                else:
                    self._html(answer)
            elif path == LIST_PAGE and method == "GET":
                self._html(_list_page(changed, self.headers.get("Host", "")))
            elif path == SEARCH and method == "POST":
                closing.wait(answer_delay_s)
                number = params.get("numer", "").strip()
                if not params.get("na_stronie"):
                    self._html(_NO_ROW_LIMIT)
                elif changed is Changed.RESULTS_WARNING:
                    self._html(_OTHER_WARNING)
                else:
                    found = [] if params.get("xrodzaj") == "" else [order for order in orders if number in order.number]
                    self._html(_results(found, changed) if found else _NOT_FOUND)
            elif path == ORDER_PAGE and method == "GET" and changed is Unread.ORDER_REDIRECT:
                self._redirect(LOGOUT)
            elif path == ORDER_PAGE and method == "GET":
                found = [order for order in orders if order.order_id == params.get("id")]
                if found and found[0].cut:
                    self._cut()
                elif found and found[0].error_status is not None and _broken(found[0]):
                    self._html("<p>Wystąpił błąd serwera.</p>", found[0].error_status)
                elif found and found[0].login_form and _broken(found[0]):
                    self._html(_login_page(None))
                elif found and found[0].hung and _broken(found[0]):
                    closing.wait()
                    self.close_connection = True
                elif found:
                    self._html(_order_page(found[0], found[0].changed or changed, today, self.headers.get("Host", ""), emmett_reload_ms))
                else:
                    self._html("<p>Nie ma takiego zlecenia.</p>", HTTPStatus.NOT_FOUND)
            else:
                self._html("<p>Nie ma takiej strony.</p>", HTTPStatus.NOT_FOUND)

        def _cut(self) -> None:
            """Zrywa połączenie bez odpowiedzi: zamknięcie z ``SO_LINGER`` 0 wysyła RST (``net::ERR_CONNECTION_RESET``)."""

            self.close_connection = True
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.connection.close()

        def _wait_if_late(self) -> None:
            if self._late:
                closing.wait()

        def _html(self, text: str, status: HTTPStatus = HTTPStatus.OK, *, content_type: str = "text/html") -> None:
            self._wait_if_late()
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self._torn or self._stalled:
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                if self._stalled:
                    closing.wait()
                    self.close_connection = True
                else:
                    self._cut()
                return
            self.wfile.write(body)

        def _json(self, answer: Mapping[str, str]) -> None:
            self._html(json.dumps(answer))

        def _redirect(self, target: str, *, cookie: bool = False) -> None:
            self._wait_if_late()
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", target)
            if cookie:
                self.send_header("Set-Cookie", "=".join(SESSION_COOKIE))
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = _Server(Handler)
    thread = threading.Thread(target=server.serve_forever, name="atrapa-efenix")
    thread.start()
    atrapa.url = f"http://127.0.0.1:{server.server_address[1]}/{LIST_PAGE}"
    try:
        yield atrapa
    finally:
        closing.set()
        server.shutdown()
        server.close_connections()
        server.server_close()
        thread.join()


class _Server(ThreadingHTTPServer):
    """Serwer Atrapy na wolnym porcie ``127.0.0.1``, który pamięta otwarte połączenia, żeby je zamknąć na końcu bloku."""

    daemon_threads = True
    # Kolejka ``listen`` dłuższa niż domyślne 5: Windows odrzuca połączenie ponad kolejkę, a macOS i Linux je trzymają.
    request_queue_size = 128

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        # Pętla serwera przyjmuje połączenie przed końcem ``shutdown``, więc po nim zbiór ma każde przyjęte połączenie.
        connection, address = super().get_request()
        with self._connections_lock:
            self._connections.add(connection)
        return connection, address

    def shutdown_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
        if isinstance(request, socket.socket):
            with self._connections_lock:
                self._connections.discard(request)
        super().shutdown_request(request)

    def close_connections(self) -> None:
        """Po ``shutdown`` zamyka w obie strony połączenia, które są jeszcze otwarte, więc wątek, który na nim czyta
        następne żądanie albo pisze odpowiedź, kończy obsługę, a przeglądarka nie dostaje już odpowiedzi."""

        with self._connections_lock:
            for connection in self._connections:
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)


# Działania na zleceniu i pole, w którym przychodzi jego identyfikator.
_CHANGES = {SAVE_QUANTITY: "order_id", FILL_EMMETT: "order_id", LOAD_EMMETT: "order_id", SET_DATE: "id", GET_DATE: "id", CHANGE_STATUS: "order_id"}


def _emmett_refusal(orders: Sequence[AtrapaOrder], params: Mapping[str, str]) -> EmmettRefusal | None:
    """Odmowa „Załaduj do zlecenia” zlecenia, którego ``order_id`` przyszło w ``params``."""

    return next((order.emmett_refusal for order in orders if order.order_id == params.get("order_id")), None)


def _change(path: str, order: AtrapaOrder, params: Mapping[str, str], *, refuse_dates: bool) -> str | dict[str, str]:
    """Odpowiedź Atrapy na działanie ``path`` na zleceniu ``order`` i zmiana jego stanu (pod blokadą Atrapy)."""

    if path == SAVE_QUANTITY:
        code = params.get("index", "").removeprefix("INDEKS_").partition("_")[0]
        if code not in PRICES or not params.get("parametr", "").isdigit():
            return {"result": "nok", "error": "Zły indeks."}
        quantity = int(params["parametr"])
        if quantity:
            order.quantities[code] = quantity
        else:
            order.quantities.pop(code, None)
        return {"result": "ok", "price_index": f"{PRICES[code] * quantity:.2f}", "price_all": f"{order.amount:.2f}"}
    if path == FILL_EMMETT:
        rows = "".join(f"<li>INDEKS_{escape(code)}_078: {quantity}</li>" for code, quantity in sorted(order.emmett.items()))
        return f"<ul>{rows}</ul>"
    if path == LOAD_EMMETT:
        order.quantities = dict(order.emmett)
        order.emmett_loads += 1
        return "ok"
    if path == SET_DATE:
        if refuse_dates:
            return "Nie zapisano daty."
        order.execution_date = date.fromisoformat(params["date"])
        return "ok"
    if path == GET_DATE:
        return "0" if order.execution_date is None else order.execution_date.isoformat()
    order.status = params.get("xstatus", "")
    return "ok"


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title></head><body>{body}</body></html>"
    )


_LIST_SCRIPT = """
(function () {
  const numer = document.getElementById('field_numer');
  function szukaj(rodzaj) {
    sessionStorage.setItem('atrapa_numer', numer.value);
    const pola = Object.fromEntries('__FIELDS__'.split(' ').map((nazwa) => [nazwa, '']));
    const wartosci = {numer: numer.value, rodzaj: rodzaj, strona: '1', na_stronie: document.getElementById('field_na_stronie').value};
    const body = new URLSearchParams({...pola, ...wartosci});
    fetch('action_fill_orders.php', {method: 'POST', body: body})
      .then((answer) => answer.text())
      .then((html) => { document.getElementById('wyniki').innerHTML = html; });
  }
  numer.addEventListener('keypress', (event) => { if (event.key === 'Enter') szukaj('szukanie'); });
  document.getElementById('button_order_search').addEventListener('click', () => szukaj('szukanie'));
  const zapamietany = sessionStorage.getItem('atrapa_numer');
  if (zapamietany !== null) {
    numer.value = zapamietany;
    szukaj('__BY_LIST__');
  }
})();
"""


# Skrypt i elementy strony, które przy wczytaniu i przy opuszczeniu strony wysyłają zapis, zmianę statusu i wylogowanie
# każdą drogą przeglądarki: okno, beacon, ``fetch`` z ``keepalive``, WebSocket, worker, service worker, przejście. Na
# początku skrypt czyści stronę, więc strona, na której w ogóle biegnie, nie ma już budowy efenix.
_HOSTILE_SCRIPT = """
document.body.replaceChildren();
window.open('action_change_status.php?order_id=1&xstatus=Anulowane');
navigator.sendBeacon('action_logout.php');
fetch('action_save_index.php', {method: 'POST', keepalive: true, body: 'ilosc=1'});
addEventListener('pagehide', () => navigator.sendBeacon('action_logout.php'));
addEventListener('unload', () => fetch('action_save_index.php', {method: 'POST', keepalive: true, body: 'ilosc=1'}));
new WebSocket('ws://' + location.host + '/gniazdo');
new Worker(URL.createObjectURL(new Blob(["fetch('/action_save_index.php', {method: 'POST', body: 'ilosc=1'})"])));
if (navigator.serviceWorker) navigator.serviceWorker.register('sw.js');
location.href = 'action_logout.php';
"""


def _hostile(host: str) -> str:
    """Elementy strony z adresami Atrapy, które przeglądarka wysyła sama: przejście, obraz, ramka, styl, skrypt."""

    origin = f"http://{escape(host)}"
    return (
        f'<meta http-equiv="refresh" content="0; url={origin}/{LOGOUT}"><img src="{origin}/{LOGOUT}">'
        f'<iframe src="{origin}/{CHANGE_STATUS}?order_id=1&amp;xstatus=Anulowane"></iframe>'
        f'<link rel="stylesheet" href="{origin}/{SAVE_QUANTITY}"><link rel="prefetch" href="{origin}/{LOGOUT}">'
        f'<script src="{origin}/{LOGOUT}"></script><script>{_HOSTILE_SCRIPT}</script>'
    )


def _list_page(changed: Changed | Unread | None, host: str) -> str:
    return _page(
        "Atrapa efenix",
        '<div class="container-fluid"><input type="text" id="field_numer" class="form-control">'
        '<button type="button" id="button_order_search" class="btn">Szukaj</button>'
        f'<select id="field_na_stronie" class="form-control"><option value="{LIST_ROWS_PER_PAGE}" selected>{LIST_ROWS_PER_PAGE}</option>'
        '<option value="25">25</option><option value="50">50</option></select>'
        f'<div id="wyniki"></div></div>{_hostile(host) if changed is Unread.HOSTILE else ""}'
        f'<script src="{LIST_SCRIPT}{"#v1" if changed is Unread.SCRIPT_ADDRESSES else "?v=1"}"></script>',
    )


def _list_script(changed: Changed | Unread | None) -> str:
    script = _LIST_SCRIPT.replace("__BY_LIST__", BY_LIST).replace("__FIELDS__", " ".join(LIST_SEARCH_FIELDS))
    if changed is Unread.SCRIPTS:
        return script.replace("{numer: numer.value", "{nr: numer.value")
    return _HOSTILE_SCRIPT + script if changed is Unread.HOSTILE else script


def _results(orders: Sequence[AtrapaOrder], changed: Changed | Unread | None) -> str:
    status = "Stan" if changed is Changed.STATUS_HEADER else "Status"
    head = (
        "<thead><tr><th>Numer dokumentu<br><small>Identyfikator Fenix</small></th><th>Operator/Rodzaj</th>"
        f"<th>{status}</th><th>Wykonawca (login)</th><th>Dane adresowe</th><th></th></tr></thead>"
    )
    link = "" if changed is Changed.ORDER_LINK else ORDER_PAGE
    rows = "".join(
        f'<tr><td>{escape(order.number)}<br><small>{escape(order.order_id)}</small></td>'
        f"<td>{escape(order.operator)}<br><small>FSM</small></td>"
        f'<td><span class="badge badge-default">{escape(order.status)}</span></td>'
        f'<td>{escape(order.executor)} <small><small class="text-default">({escape(order.realizator)})</small></small>'
        '<br><small><span class="badge badge-light"><i class="fas fa-tools"></i>2026-09-01</span></small></td>'
        f"<td><small>{escape(order.region)}</small><br>{escape(order.address)}</td>"
        f'<td><a href="{link}?id={escape(order.order_id)}" class="btn btn-sm">Otwórz</a></td></tr>'
        for order in orders
    )
    return f'<table class="table table-sm">{head}<tbody>{rows}</tbody></table>'


_ORDER_SCRIPT = """
(function () {
  const show = (id) => { document.getElementById(id).style.display = 'block'; };
  const hide = (id) => { document.getElementById(id).style.display = 'none'; };
  const post = (url, data) => fetch(url, {method: 'POST', body: new URLSearchParams(data)});
  const mainId = document.getElementById('main_id').value;
  let status = '';
  document.getElementById('button_forward_to_accept').addEventListener('click', () => { status = 'Do akceptacji'; show('dialog_forward_yes_no'); });
  document.getElementById('button_forward_to_cancel').addEventListener('click', () => { status = 'Anulowane'; show('dialog_forward_yes_no'); });
  document.querySelector('#dialog_forward_yes_no .btn-ok').addEventListener('click', () => {
    post('action_change_status.php', {order_id: mainId, xstatus: status, comment: ''}).then(() => location.reload());
  });
  document.querySelectorAll('[data-dismiss="modal"]').forEach((button) => {
    button.addEventListener('click', () => hide(button.closest('.modal').id));
  });
  const today = '__TODAY__';
  const earliest = '__EARLIEST__';
  const pad = (number) => String(number).padStart(2, '0');
  const calendar = document.getElementById('button-calendar');
  const dayField = document.getElementById('field_data_instalacji');
  // Kalendarz pola w API pickadate: set('select', [rok, miesiąc od 0, dzień] albo 'RRRR-MM-DD'), potem onSet.
  const onSet = () => {
    const toast = document.getElementById('toast');
    if (dayField.value > today) {
      toast.textContent = 'Data nie może być większa niż dzisiejsza !';
      dayField.value = today;
    } else if (dayField.value < earliest) {
      toast.textContent = 'Nie możesz rozliczyć zlecenia sprzed daty: ' + earliest;
      dayField.value = today;
    }
  };
  const picker = {
    set: (what, value) => {
      if (what === 'select') {
        dayField.value = Array.isArray(value) ? value[0] + '-' + pad(value[1] + 1) + '-' + pad(value[2]) : String(value);
        onSet();
      }
      return picker;
    },
  };
  window.jQuery = (target) => ({ pickadate: (action) => (action === 'picker' && target === dayField ? picker : undefined) });
  let recordId = '';
  calendar.addEventListener('click', () => {
    recordId = calendar.dataset.recordId;
    picker.set('select', today);
    if (__DATE_DIALOG__) show('dialog_select_date');
  });
  document.querySelector('#dialog_select_date .btn-ok').addEventListener('click', () => {
    const day = dayField.value;
    post('action_set_date_of_instalation.php', {id: recordId, date: day}).then((answer) => {
      if (!answer.ok) return;
      hide('dialog_select_date');
      document.getElementById('data_install').textContent = day;
    });
  });
  const emmett = document.getElementById('button_emmett');
  if (emmett) {
    emmett.addEventListener('click', () => {
      post('action_fill_emmett.php', {order_id: emmett.getAttribute('order_id')}).then((answer) => answer.text()).then((html) => {
        document.getElementById('emmett-propozycja').innerHTML = html;
        show('dialog_emmett');
      });
    });
  }
  document.querySelector('#dialog_emmett .btn-ok').addEventListener('click', () => {
    hide('dialog_emmett');
    post('action_load_emmett.php', {order_id: mainId}).then(() => setTimeout(() => location.reload(), __RELOAD__));
  });
  document.querySelectorAll('.wycena-ilosc, .wycena-cena').forEach((field) => {
    field.addEventListener('keypress', (event) => {
      if (event.key === 'Enter') field.blur();
      else if (!/^[0-9]$/.test(event.key)) event.preventDefault();
    });
    field.addEventListener('blur', () => {
      const kind = field.classList.contains('wycena-ilosc') ? 'ILOSC' : 'CENA';
      post('action_save_index.php', {order_id: field.getAttribute('order_id'), index: field.id, rodzaj: kind, parametr: field.value || '0'})
        .then((answer) => answer.json())
        .then((saved) => {
          if (saved.result !== 'ok') return;
          document.getElementById('cena-' + field.id).textContent = saved.price_index;
          if (__REFRESH__) document.getElementById('cena_all2').textContent = saved.price_all;
        });
    });
  });
})();
"""


def _order_page(order: AtrapaOrder, changed: Changed | Unread | None, today: date, host: str, reload_ms: int) -> str:
    day = "" if order.execution_date is None else order.execution_date.isoformat()
    if changed is Changed.DATE_FORMAT and order.execution_date is not None:
        day = f"{order.execution_date:%d.%m.%Y}"
    order_id = escape(order.order_id)
    hidden = ' style="display: none"' if changed is Changed.HIDDEN_EMMETT else ""
    emmett = (
        ""
        if changed in (Changed.EMMETT_BUTTON, Unread.ORDER_PARTS)
        else f'<button type="button" id="button_emmett" order_id="{order_id}"{hidden} title="Załaduj wycenę przygotowaną przez Emmetta.">Emmett</button>'
    )
    day_field = "" if changed is Unread.ORDER_PARTS else '<input type="text" id="field_data_instalacji" readonly>'
    calendar = (
        ""
        if changed is Unread.ORDER_PARTS and order.execution_date is not None
        else f'<button type="button" id="button-calendar" data-record-id="{order_id}">Kalendarz</button>'
    )
    return _page(
        "Atrapa efenix - zlecenie",
        f'<input type="hidden" name="main_id" id="main_id" value="{order_id}"><div id="toast"></div>'
        f"<div><small>Status</small> {escape(order.status)}</div>"
        f"<div><small>Realizator</small> {escape(order.realizator)}</div>"
        f'<div><small>Data wykonania</small><span id="data_install">{day}</span>'
        f"{calendar}</div>"
        f"<div><small>Ulica - numer</small> {escape(order.address)}</div>"
        '<div class="card"><button type="button" id="button_forward_to_accept">Przekaż do akceptacji.</button>'
        '<button type="button" id="button_forward_to_cancel">Anuluj to zlecenie.</button></div>'
        f'<div class="card"><span>Wycena</span>{emmett}{"".join(_position(order, position, changed) for position in CATALOG if not (position.code in order.without and _broken(order)))}'
        f'<h1><span id="cena_all2">{order.amount:.2f}</span></h1></div>'
        + _dialog("dialog_forward_yes_no", "Zmiana statusu", "", "Tak")
        + _dialog("dialog_select_date", "Wybierz datę wykonania", day_field, "Potwierdź")
        + _dialog("dialog_emmett", "Emmett", '<div id="emmett-propozycja"></div>', "Załaduj do zlecenia")
        + (_hostile(host) if changed is Unread.HOSTILE else "")
        + (
            f"<script>{_order_script(changed, today, reload_ms)}</script>"
            if changed is Unread.SCRIPTS
            else f'<script src="{ORDER_SCRIPT}{";v=1" if changed is Unread.SCRIPT_ADDRESSES else "?v=1"}"></script>'
        ),
    )


def _order_script(changed: Changed | Unread | None, today: date, reload_ms: int) -> str:
    script = (
        _ORDER_SCRIPT.replace("__RELOAD__", str(reload_ms))
        .replace("__REFRESH__", "false" if changed is Changed.STALE_AMOUNT else "true")
        .replace("__DATE_DIALOG__", "false" if changed is Changed.DATE_DIALOG else "true")
        .replace("__TODAY__", today.isoformat())
        .replace("__EARLIEST__", earliest_execution_date(today).isoformat())
    )
    return _HOSTILE_SCRIPT + script if changed is Unread.HOSTILE else script


def _position(order: AtrapaOrder, position: Position, changed: Changed | Unread | None) -> str:
    """Karta pozycji jak w efenix: pole Ilość z ceną w tekście karty albo samo pole ceny wpisywanej, bez ceny w tekście."""

    suffix = "079" if changed is Unread.PRICE_LIST and position.code == "005" else "078"
    field_id = f"INDEKS_{position.code}_{suffix}"
    shown = f'<div class="col-sm-1 mt-2"><span class="text-default"><small>{_price_text(position.price, changed)}</small></span></div>'
    if position.kind == "CENA" or (changed is Unread.PRICE_LIST and position.code == "007"):
        field = f'<input type="text" id="{field_id}" order_id="{escape(order.order_id)}" class="form-control form-control-sm wycena-cena" value="0.00">'
        value = Decimal("0.00")
        shown = ""
    else:
        quantity = order.quantities.get(position.code, 0)
        field = (
            f'<input step="1" type="number" id="{field_id}" order_id="{escape(order.order_id)}" '
            f'class="form-control form-control-sm wycena-ilosc" min="0" max="999999" value="{quantity}">'
        )
        value = position.price * quantity
        if changed is Changed.QUANTITY_VALUE and position.code == "012":
            field = field.replace(f'value="{quantity}"', 'value="1.5"')
    return (
        '<div class="card rounded-lg kolorek"><div class="row">'
        f'<div class="col-sm-3 mt-2"><span class="text-default">Usługa testowa {position.code}</span></div>'
        f'<div class="col-sm-2 mt-2"><span class="text-secondary"><small>{field_id}</small></span></div>{shown}'
        f'<div class="col-sm-2 mt-2">{field}</div>'
        f'<div class="col-sm-2 mt-2"><small><span id="cena-{field_id}"> {value:.2f}</span></small></div></div></div>'
    )


def _dialog(dialog_id: str, title: str, body: str, ok: str) -> str:
    return (
        f'<div class="modal" id="{dialog_id}" style="display: none"><h5>{escape(title)}</h5><div class="modal-body">{body}</div>'
        f'<button type="button" class="btn btn-secondary" data-dismiss="modal">Zamknij</button><button type="button" class="btn btn-ok">{escape(ok)}</button></div>'
    )


def _price_text(price: Decimal, changed: Changed | Unread | None) -> str:
    shown = f"{price:.2f}"
    return shown.replace(".", ",") if changed is Unread.PRICE_TEXT else shown


def _has_session_cookie(header: str) -> bool:
    return "=".join(SESSION_COOKIE) in (part.strip() for part in header.split(";"))


def _broken(order: AtrapaOrder) -> bool:
    """Strona zlecenia ``order`` jest już zmieniona: strona błędu, formularz logowania, strona bez odpowiedzi albo bez
    pozycji ``without`` (``after_date``: od zapisu daty wykonania, ``after_emmett``: po Wycenie Emmetta)."""

    if order.after_emmett:
        return order.emmett_loads > 0
    return not order.after_date or order.execution_date is not None


def _login_page(changed: Changed | Unread | None) -> str:
    fingerprint = "" if changed is Unread.LOGIN_FORM else '<input type="hidden" id="fingerprint" name="fingerprint" value="">'
    return _page(
        "Atrapa efenix - logowanie",
        f'<form method="post" action="{LOGIN_ACTION}"><input type="text" id="field_signum" name="field_signum">'
        f'<input type="password" id="field_password" name="field_password">{fingerprint}'
        '<button type="submit" id="button_login">Zaloguj</button></form>',
    )
