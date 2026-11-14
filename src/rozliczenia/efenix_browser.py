"""Okno efenix w przeglądarce: jedyny moduł, który zna czekanie, klik i sieć efenix (stronę czyta przez Playwright także ``efenix_page``).

Budowę stron efenix (adresy działań, elementy ``Element``, nazwy w skryptach stron) i jej odczyty (tabela wyników,
strona zlecenia, okno Emmetta) daje ``efenix_page``, z którego okno bierze każdy selektor. Na zewnątrz okno daje tylko
typy domeny (``efenix_window.Efenix``, ``ListedOrder``, ``OrderPricing``) i zna tylko działania
z listy dozwolonych: szukanie po ``Numer`` na liście zleceń, otwarcie strony zlecenia, ustawienie daty wykonania,
przycisk Emmetta z „Załaduj do zlecenia”, pola „Ilość” i Przekazanie do akceptacji. Przycisku anulowania nie zna. Każdy
przycisk okna dialogowego klika w jego oknie (``#dialog_… .btn-ok``), bo strona zlecenia ma ``.btn-ok`` w każdym oknie,
także w oknie zmiany statusu. Szuka tak jak tata: wpisuje numer w pole ``#field_numer`` i naciska Enter, a skrypt strony wysyła ``action_fill_orders.php`` i wkłada
odpowiedź do ``#wyniki``. Tabelę wyników okno czyta z odpowiedzi na swoje szukanie (tej z jego numerem w polu ``numer``),
tę samą, którą skrypt wkłada do ``#wyniki``, bo lista po wczytaniu sama szuka ostatniego numeru z poprzedniej wizyty, a
jej odpowiedź trafia do ``#wyniki`` w dowolnej chwili; czyta ją ``efenix_page.read_results``, a stronę zlecenia otwiera
linkiem z wiersza. Przekierowanie strony albo odpowiedzi daty, Wyceny Emmetta i ilości na
``page_login.php`` to ``LoggedOut``, tak samo ostrzeżenie o wygasłej sesji w odpowiedzi szukania (``efenix_page.SearchWarning``),
bo na szukanie bez sesji efenix nie przekierowuje. Lista zleceń, której okno nie otworzyło przy starcie albo w czasie
czekania na logowanie (adres nie odpowiada), to ``EfenixUnreachable``.
Który wyjątek okna daje awaria, rozstrzyga tylko tabela decyzji ``efenix_window.WindowStop.of`` z dowodu, który okno
zbiera w miejscu awarii.
Każde inne działanie, którego okno nie dokończyło, to ``UnexpectedPage`` z częścią strony: strona bez oczekiwanej
budowy, odpowiedź efenix ze statusem błędu, element obecny, ale niewidoczny, i każdy błąd Playwrighta w działaniu (czas czekania na stronę, odpowiedź albo
element, który minął, otwarcie strony, które się nie udało, treść odpowiedzi, której nie da się przeczytać). Każdy z
tych wyjątków niesie przyczynę techniczną z zamkniętej listy (``efenix_window.WindowCause``): element, który nie
występuje dokładnie raz, z jego selektorem i liczbą, budowę strony, której okno nie zna (``Shape``), status HTTP
(``HttpStatus``), a przy błędzie Playwrighta typ jego wyjątku i działanie okna, w którym wystąpił (``Operation``), bez
treści wyjątku i strony. Wpisanie numeru i Enter w polu ``Numer``, które się nie udały, bo pola nie ma już na stronie
dokładnie raz, to element z jego liczbą, a nie błąd Playwrighta: odpowiedź szukania listy mogła w tym czasie włożyć do
``#wyniki`` stronę listy (#971). Status HTTP daje każda odpowiedź efenix ze statusem błędu (4xx, 5xx), na którą okno czeka
(szukanie, zapis daty, „Załaduj do zlecenia”, zapis ilości), zanim okno ją przeczyta, i strona, którą okno otwiera
(lista zleceń, także przy starcie, i strona zlecenia), gdy przyszła ze statusem błędu, a okno jej nie przeczytało
(nawigacja nie zgłasza błędu przy 4xx i 5xx). Czy to
zerwane połączenie, wolny czy zmieniony efenix, okno nie zgaduje: Maks ustala to z przyczyny w Logach. Na odpowiedź efenix
okno czeka do jej końca, z całą treścią, a nie tylko do nagłówków, bo na treść, którą sieć wstrzymała w połowie,
czekałoby bez końca. Działanie w zamkniętej karcie albo oknie, także zamkniętym w trakcie działania, to
``WindowClosed``, cokolwiek zgłosił wtedy Playwright, także gdy błąd nawigacji przerwanej zamknięciem karty przyszedł,
zanim Playwright powiedział o zamknięciu (``BrowserEfenix.closed``). Przeglądarkę daje rozmówca: stronę (``window``), Chromium
Playwrighta (``chromium``) albo widoczne okno zainstalowanego Google Chrome w trwałym profilu narzędzia (``chrome``),
które nie startuje (``BrowserNotStarted``), gdy Chrome nie ma albo jego profil trzyma inne okno; Chromium Playwrighta nie
startuje tak samo, gdy go nie ma, a każde okno także wtedy, gdy nie wystartował sterownik Playwrighta
(``Operation.DRIVER``). Każda przeglądarka
okna, także Chromium testów, startuje z argumentami ``launch_options``: bez losowania portu lokalnego każdego połączenia
(``TcpPortRandomizationWin``), przy którym Windows odmawia czasem połączenia, choć porty są wolne.

Okno z ``Login`` od silnika (``chrome`` zawsze, ``window`` na życzenie) na stronie logowania czeka, aż tata się zaloguje:
pyta efenix o listę zleceń w tej samej sesji przeglądarki bez przekierowań, nie ruszając strony z formularzem, w którym
tata pisze, najwyżej co ``LOGIN_POLL_MS``; gdy strona przejdzie ze strony logowania na inną, pyta od razu, jeśli od
poprzedniego pytania minął ten odstęp, a inaczej po nim. Gdy lista odpowiada, otwiera ją i proces rusza; lista ze
statusem błędu (4xx, 5xx) to ``UnexpectedPage`` z ``HttpStatus`` jak przy starcie, brak logowania przez
``LOGIN_TIMEOUT_MS`` to ``LoggedOut``, a gdy efenix nie odpowiedział na ostatnie pytanie przed końcem tego czasu ani
na żadne przez dwa czasy okna przed nim, ``EfenixUnreachable`` z błędem przeglądarki jak przy starcie; pytanie bez
odpowiedzi czekania nie kończy. Karta, okno albo przeglądarka zamknięte w tym czasie to ``WindowClosed`` najpóźniej
po ``LOGIN_POLL_MS``.

Stronę zlecenia czyta ``efenix_page.read_order`` tak, jak widzi ją tata: data wykonania, kwota końcowa i ilość każdej
pozycji. Datę ustawia przyciskiem kalendarza ``#button-calendar`` i kalendarzem pickadate pola ``#field_data_instalacji`` okna
``#dialog_select_date``: wybiera dzień przez ``picker.set('select', …)`` kalendarza strony, więc biegnie sprawdzenie
zakresu efenix, które dzień spoza zakresu zamienia na dzisiejszy. Gdy w polu nie ma potem dokładnie wybranego dnia, okno
zamyka kalendarz bez „Potwierdź”; inaczej klika „Potwierdź” i czeka na odpowiedź ``action_set_date_of_instalation.php``.
Tekstowi ``#data_install`` po niej nie wierzy, bo skrypt efenix wpisuje go przy każdej odpowiedzi. Wycenę Emmetta ładuje przyciskiem
``#button_emmett`` i „Załaduj do zlecenia” w ``#dialog_emmett``: czeka na odpowiedź ``action_load_emmett.php`` i na
przeładowanie strony, które robi skrypt efenix, i czyta stronę od nowa. Odpowiedź z przekierowaniem na ``page_login.php``
to ``LoggedOut``, ze statusem błędu (4xx, 5xx) ``UnexpectedPage`` ze statusem (``HttpStatus``), a z przekierowaniem gdzie
indziej ``UnexpectedPage`` z odpowiedzią w budowie, której okno nie zna; po każdej z nich okno strony nie czyta. Po
odpowiedzi 2xx skrypt przeładowuje stronę także wtedy, gdy efenix odmówił, a strona bez Wyceny Emmetta wygląda jak pusta
Wycena Emmetta (#877, #889). Czy efenix załadował Wycenę Emmetta, okno nie rozstrzyga: oddaje werdyktowi Wyceny
(``efenix_pricing``) obserwacje (``EmmettLoad``), czyli stronę po przeładowaniu i to, co okno Emmetta pokazało przed
kliknięciem „Załaduj do zlecenia” (``Proposal``), w tym samym działaniu okna. Treści odpowiedzi „Załaduj do zlecenia”
okno nie czyta, bo Chromium porzuca ją, gdy przeładowanie wyprzedzi odczyt (#895), a jej postaci nikt nie zmierzył.
Okno Emmetta liczy dwa razy: zaraz po kliknięciu przycisku Emmetta (dokładnie jedno ``#dialog_emmett``), a gdy któreś
okno Emmetta jest już widoczne, regułą ``efenix_page.emmett_window_fault`` (dokładnie jedno okno, potem dokładnie jedna
propozycja w nim), tą samą, którą narzędzie zgodności mierzy efenix. Na pokazanie czeka więc na dowolne okno Emmetta, a
nie na jedyne, bo drugie okno dopisane przed pokazaniem ma być tą różnicą budowy, a nie błędem Playwrighta.
Propozycja w oknie Emmetta (``#emmett-propozycja``) nic nie pokazała, gdy nie ma w niej elementu ani tekstu, a przyszła cała,
gdy odpowiedź ``action_fill_emmett.php`` przyszła cała ze statusem 2xx: okno Emmetta jest puste także po statusie błędu,
przekierowaniu i zerwanym połączeniu, bo skrypt efenix wkłada propozycję tylko z odpowiedzi 2xx, a okno pokazuje i tak
(#908). Tę odpowiedź okno czyta po pokazaniu okna Emmetta, które skrypt efenix pokazuje dopiero po jej końcu albo
zerwaniu (synchroniczne ``$.ajax``), a przed kliknięciem, po którym strona się przeładuje, więc odczyt na nic nie czeka i
nie ściga się z przeładowaniem. Postaci propozycji okno nie czyta, bo tej też nikt nie zmierzył; po padniętej propozycji
„Załaduj do zlecenia” i tak ładuje Wycenę Emmetta, bo efenix bierze ją u siebie, a nie z okna. Ilość wpisuje w polu i naciska Enter, a skrypt strony zapisuje ją przez ``action_save_index.php``:
kwotą końcową jest ``price_all`` z tej odpowiedzi, a ``#cena_all2``, które się do niej nie odświeży, to
``UnexpectedPage``. Odpowiedź ``result: nok`` to wygasła sesja (``LoggedOut``).

Przekazanie do akceptacji okno robi przyciskiem ``#button_forward_to_accept`` i „Tak” w ``#dialog_forward_yes_no``: czeka
na koniec żądania ``action_change_status.php`` i na przeładowanie strony, które robi skrypt efenix po odpowiedzi, jak po
„Załaduj do zlecenia”. Gdy skrypt efenix po przycisku Przekazania pokaże zamiast okna zmiany statusu okno informacji
``#dialog_info``, efenix odmówił Przekazania: okno czyta tekst ``#dialog_info_field_info`` jako ``ForwardRefusal``,
zamyka okno informacji i oddaje odmowę, a „Tak” nie klika. Każde okno dialogowe okno zamyka dopiero po końcu jego animacji
pokazania, bo bootstrap efenix (``.modal.fade``) nie zamyka okna w jej trakcie (#1084).
Strażnik zmiany statusu (``window``) stoi na całym kontekście przeglądarki okna, więc widzi także
żądania ramek i kart, które otworzy strona: każde żądanie, w którego ścieżce jest ``action_change_status``, przepuszcza
tylko wtedy, gdy okno jest w Przekazaniu do akceptacji, to jego pierwsze takie żądanie, a jest to POST z polem ``xstatus``
dokładnie raz, równym dokładnie „Do akceptacji”, i z polem ``order_id`` dokładnie raz, równym identyfikatorowi
zlecenia, które okno otworzyło, bo Przekazanie innego zlecenia też jest nieodwracalne. Każde inne przerywa przed wysłaniem, a działanie okna, w którym albo
przed którym to się stało, kończy się ``UnexpectedPage`` z ``StatusChangeBlocked`` (żądanie po ostatnim działaniu: przy
zamknięciu okna). Okno w trybie bez Przekazania nie wchodzi w Przekazanie, więc przerywa każde takie żądanie. Okno
anulowania dzieli z Przekazaniem to samo okno dialogowe, a strona, która po pomyłce wyśle w nim „Anulowane”, nie
dochodzi do efenix. Strażnik nie widzi żądań, których przeglądarka nie daje do przechwycenia: kolejnego kroku
przekierowania i service workera, którego okno taty i Skryptu dla maszyn nie pozwalają zarejestrować.
"""

from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Concatenate, Final, ParamSpec, TypedDict, TypeVar
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, Playwright, Request, Response, Route, sync_playwright

from .tool_files import TOOL_ROOT
from .call_trace import exception_type
from .efenix_window import (
    ACCEPTANCE_STATUS,
    BrowserFailure,
    Closed,
    EfenixUnreachable,
    ElementCount,
    EmmettLoad,
    ForwardRefusal,
    HttpStatus,
    ListOpenFailed,
    ListedOrder,
    LoggedOut,
    Login,
    LoginExpired,
    LoginSign,
    Operation,
    OrderPricing,
    OtherShape,
    PagePart,
    Proposal,
    SentChanges,
    Shape,
    StatusChangeBlocked,
    UnexpectedPage,
    WindowClosed,
    WindowStop,
)
from .efenix_page import (
    AMOUNT,
    CHANGE_STATUS,
    FILL_EMMETT,
    LOAD_EMMETT,
    LOGIN_PAGE,
    NUMBER_PARAM,
    ORDER_PAGE,
    PRICE_ALL,
    QUANTITY,
    SAVE_QUANTITY,
    SEARCH,
    ORDER_PARAM,
    SET_DATE,
    STATUS_PARAM,
    Element,
    amount,
    emmett_window,
    emmett_window_fault,
    login_form,
    read_order,
    read_results,
    single,
)

__all__ = [
    "LOGIN_TIMEOUT_MS",
    "PROFILE_DIRECTORY",
    "TIMEOUT_MS",
    "BrowserEfenix",
    "LaunchOptions",
    "chrome",
    "chromium",
    "default_profile",
    "launch_options",
    "window",
]

PROFILE_DIRECTORY: Final = "przegladarka-efenix"
"""Folder profilu przeglądarki narzędzia w katalogu narzędzia: na dysku lokalnym taty, poza OneDrive, w ``.gitignore``."""

TIMEOUT_MS: Final = 30_000
"""Tyle okno czeka na stronę, odpowiedź albo element efenix; narzędzie zgodności czeka tyle samo."""
LOGIN_TIMEOUT_MS: Final = 15 * 60_000
"""Tyle okno czeka na logowanie taty, zanim proces zatrzyma się jak po wylogowaniu."""
LOGIN_POLL_MS: Final = 2_000
_STATUS_POLL_MS: Final = 50
"""Co tyle okno sprawdza, czy żądanie Przekazania do akceptacji skończyło się albo strażnik je przerwał."""

# Dzień wybrany kalendarzem pickadate pola, tak jak klik dnia: biegnie ``onSet`` strony, które sprawdza zakres dat.
# Miesiąc pickadate liczy od 0. ``false``, gdy pole nie ma kalendarza.
_PICK_DAY: Final = """(field, [year, month, day]) => {
    const jquery = window.jQuery;
    const picker = typeof jquery === 'function' && typeof jquery(field).pickadate === 'function' ? jquery(field).pickadate('picker') : null;
    if (!picker || typeof picker.set !== 'function') return false;
    picker.set('select', [year, month - 1, day]);
    return true;
}"""
_SHOWS: Final = "([selector, text]) => document.querySelector(selector)?.textContent.trim() === text"
_COUNT: Final = "(selector) => ({count: document.querySelectorAll(selector).length})"
_SETTLED: Final = """(selector) => {
    const dialog = document.querySelector(selector);
    return dialog !== null && dialog.getAnimations({subtree: true}).every(
        (animation) => animation.playState !== 'running' || !Number.isFinite(animation.effect?.getComputedTiming().endTime));
}"""
"""Okno dialogowe i jego poddrzewo nie mają już biegnącej animacji z końcem: bootstrap 4 kończy pokazanie okna na
przejściu dziecka ``.modal-dialog``. Okno nie czeka na animację bez końca (spinner) ani wstrzymaną, bo czekałoby do końca
czasu okna, a skończona animacja z ``fill: forwards`` zostaje w ``getAnimations`` jako ``finished``."""
_P = ParamSpec("_P")
_R = TypeVar("_R")


class BrowserEfenix:
    """Okno efenix na stronie ``page`` z listą zleceń pod adresem ``url``; implementuje ``efenix_window.Efenix``."""

    def __init__(self, page: Page, url: str, *, timeout_ms: int = TIMEOUT_MS) -> None:
        self._page = page
        self._url = url
        self._timeout_ms = timeout_ms
        self._positions: dict[str, str] = {}
        # Przyciski zmiany zlecenia, które okno kliknęło (``_answer``), a przy Przekazaniu do akceptacji żądania, które
        # przepuścił strażnik (``guard``).
        self._sent = SentChanges()
        self._opened = False
        # Strażnik zmiany statusu (``guard``): czy okno czeka na swoje żądanie Przekazania do akceptacji, pierwsze żądanie,
        # które przerwał, i część strony ostatniego działania okna.
        self._forwarding = False
        self._blocked: StatusChangeBlocked | None = None
        self._part = PagePart.LIST
        self._order_id: str | None = None

    @property
    def closed(self) -> bool:
        """Karta okna jest zamknięta: tata zamknął ją albo całe okno przeglądarki.

        Najpierw pyta kartę o jej dokument (``:root``), bo karta zamknięta w trakcie nawigacji przerywa ją błędem, który
        Playwright podaje, zanim powie o zamknięciu karty (``Page.is_closed`` jest jeszcze fałszem, pomiar #878: 89 na 100
        zamknięć karty, gdy okno czeka na stronę). Odpowiedź przychodzi po wiadomości o zamknięciu karty, które przerwało
        nawigację, więc po niej ``Page.is_closed`` już je zna (pomiar #886: 247 z 247 zamknięć karty w trakcie
        nawigacji). Pytanie w zamkniętej karcie albo przeglądarce kończy się błędem, a o zamknięciu mówi wtedy też
        ``Page.is_closed``. Pytanie ma czas okna, bo przeglądarka albo strona, która nie odpowiada, inaczej zatrzymałaby
        okno tu bez końca (#886).
        """

        with suppress(PlaywrightError):
            self._page.locator(":root").wait_for(state="attached", timeout=self._timeout_ms)
        return self._page.is_closed()

    def guard(self, route: Route) -> None:
        """Strażnik zmiany statusu na kontekście przeglądarki okna: przepuszcza tylko pierwsze żądanie Przekazania do
        akceptacji w czasie, gdy okno na nie czeka: POST z ``xstatus`` dokładnie „Do akceptacji” i ``order_id`` dokładnie
        zlecenia otwartego w oknie; każde inne przerywa i zapamiętuje przyczynę pierwszego przerwanego."""

        try:
            blocked = self._blocked_cause(route.request)
        except (PlaywrightError, ValueError):  # treść żądania, której nie da się przeczytać, nie jest Przekazaniem
            blocked = StatusChangeBlocked.OTHER_STATUS if self._forwarding else StatusChangeBlocked.OUTSIDE_FORWARD
        with suppress(PlaywrightError):
            if blocked is None:
                self._forwarding = False
                self._sent.send()
                route.continue_()
                return
            if self._blocked is None:
                self._blocked = blocked
            route.abort()

    def _blocked_cause(self, request: Request) -> StatusChangeBlocked | None:
        if not self._forwarding:
            return StatusChangeBlocked.OUTSIDE_FORWARD
        if request.method != "POST" or _field(request, STATUS_PARAM) != [ACCEPTANCE_STATUS]:
            return StatusChangeBlocked.OTHER_STATUS
        if self._order_id is None or _field(request, ORDER_PARAM) != [self._order_id]:
            return StatusChangeBlocked.OTHER_ORDER
        return None

    def raise_blocked(self, error: BaseException | None = None) -> None:
        """``UnexpectedPage`` z częścią strony ostatniego działania i ``StatusChangeBlocked``, gdy strażnik przerwał już
        żądanie zmiany statusu; ``error``: wyjątek działania, który to Zatrzymanie zastępuje."""

        if self._blocked is not None:
            raise WindowStop.of(self._part, self._blocked) from error

    @staticmethod
    def _action(
        part: PagePart,
    ) -> Callable[[Callable[Concatenate[BrowserEfenix, _P], _R]], Callable[Concatenate[BrowserEfenix, _P], _R]]:
        """Działanie okna na części ``part`` strony efenix: każdy błąd Playwrighta w działaniu to ``UnexpectedPage(part)``
        z typem błędu i działaniem przeglądarki, które nazwał ``_doing`` (granica ``_within``), więc żadne czekanie na sieć
        ani czytanie odpowiedzi jej nie omija.

        Każdy wyjątek działania w karcie zamkniętej przed nim albo w jego trakcie to zamknięte okno (``WindowClosed``), a nie
        lista typów: Playwright zgłasza wtedy błąd, a granica mogła go już zamienić na ``UnexpectedPage`` albo
        ``open_list`` na ``EfenixUnreachable``. O zamknięciu mówi ``BrowserEfenix.closed``, które po jednym pytaniu
        przeglądarki zna zamknięcie karty także wtedy, gdy błąd nawigacji wyprzedził wiadomość Playwrighta o nim.

        Wyjątek okna (``WindowStop``) z działania ma ``sent``, gdy działanie przed nim kliknęło przycisk zmiany zlecenia
        (``BrowserEfenix._answer``, ``SentChanges``).

        Żądanie zmiany statusu, które strażnik przerwał przed działaniem albo w jego trakcie, kończy działanie
        ``UnexpectedPage`` z ``StatusChangeBlocked`` zamiast jego wyniku albo wyjątku (``BrowserEfenix.raise_blocked``).
        """

        def decorate(action: Callable[Concatenate[BrowserEfenix, _P], _R]) -> Callable[Concatenate[BrowserEfenix, _P], _R]:
            @functools.wraps(action)
            def guarded(efenix: BrowserEfenix, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
                with efenix._sent.action():
                    efenix._part = part
                    efenix.raise_blocked()
                    try:
                        with _within(part):
                            done = action(efenix, *args, **kwargs)
                    except Exception as error:
                        efenix.raise_blocked(error)
                        if efenix.closed and not isinstance(error, WindowClosed):
                            raise WindowStop.of(part, Closed.DURING_ACTION) from error
                        raise
                    efenix.raise_blocked()
                    return done

            return guarded

        return decorate

    @_action(PagePart.LIST)
    def open_list(self) -> None:
        """Otwiera listę zleceń; ``EfenixUnreachable``, gdy okno nie otworzyło jeszcze efenix, a adres nie odpowiada."""

        try:
            response = self._go(self._url)
        except _Failed as failed:
            raise WindowStop.of(PagePart.LIST, ListOpenFailed(failed.failure, self._opened)) from failed.__cause__
        self._opened = True
        self._ensure_logged_in(PagePart.LIST)
        try:
            self._element(Element.NUMBER, PagePart.LIST)
        except UnexpectedPage as unread:
            # Strona błędu serwera efenix: adres odpowiada, więc to nie ``EfenixUnreachable``, także przy starcie.
            if (error_page := _error_page(response)) is not None:
                raise WindowStop.of(PagePart.LIST, error_page) from unread
            raise

    def wait_for_login(
        self, login: Login, *, timeout_ms: int = LOGIN_TIMEOUT_MS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Otwiera listę zleceń, a na stronie logowania czeka w ``login``, aż tata się zaloguje; ``LoggedOut`` po
        ``timeout_ms`` bez logowania (najwyżej ``LOGIN_POLL_MS`` później), ``EfenixUnreachable`` po nim, gdy efenix nie
        odpowiedział na ostatnie pytanie o sesję ani na żadne przez dwa czasy okna przed nim, ``UnexpectedPage`` listy ze
        statusem HTTP, gdy lista odpowiada stroną błędu serwera, a ``WindowClosed`` najpóźniej ``LOGIN_POLL_MS`` po
        zamknięciu karty, okna albo całej przeglądarki. ``clock`` (sekundy) mierzy czas czekania.

        Pytanie bez odpowiedzi nie kończy czekania: gdy sieć wróci, tata może się jeszcze zalogować. Dwa czasy okna to
        co najmniej dwa pełne pytania bez odpowiedzi także przy efenix, który wisi, więc jedno zerwane połączenie tuż
        przed limitem po 15 minutach odpowiedzi zostaje brakiem logowania. Pytanie, które padło, bo tata zamknął kartę
        albo przeglądarkę, to ``WindowClosed``, a nie efenix bez odpowiedzi, także na granicy limitu.

        Zamkniętą kartę rozpoznaje po ``Page.is_closed`` przed każdym sprawdzeniem, bo czekanie Playwrighta na adres karty
        zamkniętej przed nim nie zgłasza jej zamknięcia, tylko kończy się po swoim limicie. Efenix pyta najwyżej co
        ``LOGIN_POLL_MS``, także gdy karta nie stoi na stronie logowania i czekanie na zmianę jej adresu wraca od razu
        (#891).
        """

        try:
            self.open_list()
            return
        except LoggedOut:
            pass
        with login():
            answered = clock()
            deadline = answered + timeout_ms / 1000
            while True:
                if self._page.is_closed():
                    raise WindowStop.of(PagePart.LIST, Closed.DURING_LOGIN)
                unanswered: _Failed | None = None
                try:
                    session_open = self._session_open()
                except _Failed as failed:
                    if self.closed:
                        continue
                    session_open, unanswered = False, failed
                if session_open:
                    try:
                        self.open_list()
                        return
                    except LoggedOut:
                        pass
                asked = clock()
                if unanswered is None:
                    answered = asked
                remaining_ms = round((deadline - asked) * 1000)
                if remaining_ms <= 0:
                    failure = None if unanswered is None else unanswered.failure
                    stop = WindowStop.of(PagePart.LIST, LoginExpired(failure, asked - answered, self._timeout_ms))
                    # Niedostępny efenix ma za przyczynę błąd pytania bez odpowiedzi, a brak logowania nie ma przyczyny.
                    if unanswered is not None and isinstance(stop, EfenixUnreachable):
                        raise stop from unanswered.__cause__
                    raise stop
                # Czekanie kończy się po limicie, a w karcie zamkniętej w jego trakcie błędem; o zamknięciu mówi ``is_closed``.
                with suppress(PlaywrightError):
                    self._page.wait_for_url(lambda url: not _on_login_page(url), timeout=min(LOGIN_POLL_MS, remaining_ms))
                    # Karta zeszła ze strony logowania albo na niej nie stoi: do następnego pytania mija i tak ``LOGIN_POLL_MS``.
                    rest_ms = LOGIN_POLL_MS - round((clock() - asked) * 1000)
                    if rest_ms > 0:
                        self._page.wait_for_timeout(rest_ms)

    def _session_open(self) -> bool:
        """Lista zleceń odpowiada w sesji okna bez przekierowania na logowanie; pytanie nie zmienia strony okna.

        Odpowiedź ze statusem błędu (4xx, 5xx) to ``UnexpectedPage`` listy z tym statusem, jak lista przy starcie: adres
        odpowiada, a tata mógł się już zalogować, więc czekanie dalej nic nie da (#891). Pytanie bez odpowiedzi (błąd
        Playwrighta) to ``_Failed`` otwarcia listy, jak przy starcie.
        """

        with _doing(Operation.OPEN):
            response = self._page.context.request.get(self._url, max_redirects=0, timeout=self._timeout_ms)
        if response.status >= 400:
            raise WindowStop.of(PagePart.LIST, HttpStatus(response.status))
        location = urlparse(response.headers.get("location", "")).path
        return response.ok and not location.endswith(LOGIN_PAGE)

    @_action(PagePart.RESULTS)
    def search(self, number: str) -> Sequence[ListedOrder]:
        if urlparse(self._page.url).path != urlparse(self._url).path:
            self.open_list()
        field = self._page.locator(Element.NUMBER.selector)
        with _within(PagePart.LIST), self._still_single(Element.NUMBER.selector, PagePart.LIST), _doing(Operation.FILL):
            field.fill(number, timeout=self._timeout_ms)

        def enter() -> None:
            with self._still_single(Element.NUMBER.selector, PagePart.LIST):
                self._enter(field)

        answer = self._finished(lambda request: _is_search(request, number), enter)
        html = self._text(answer)
        with _doing(Operation.READ):
            return read_results(self._page, html)

    @_action(PagePart.ORDER)
    def open_order(self, order: ListedOrder) -> OrderPricing:
        self._order_id = order.order_id
        return self._read_order(self._go(urljoin(self._url, f"{ORDER_PAGE}?id={order.order_id}")))

    @_action(PagePart.DATE)
    def set_execution_date(self, day: date) -> bool:
        self._click(self._element(Element.DATE_BUTTON, PagePart.DATE))
        self._shown(Element.DATE_DIALOG, PagePart.DATE)
        field = self._element(Element.DATE_FIELD, PagePart.DATE)
        with _doing(Operation.PICK):
            picked = field.evaluate(_PICK_DAY, [day.year, day.month, day.day], timeout=self._timeout_ms)
        with _doing(Operation.READ):
            shown = field.input_value(timeout=self._timeout_ms)
        if picked is not True:
            raise WindowStop.of(PagePart.DATE, OtherShape(Shape.NO_CALENDAR))
        if shown != day.isoformat():
            self._close(Element.DATE_DIALOG, Element.DATE_DISMISS, PagePart.DATE)
            return False
        confirm = self._element(Element.DATE_OK, PagePart.DATE)
        answer = self._answer(SET_DATE, lambda _params: True, lambda: self._click(confirm))
        if _redirected_to_login(answer):
            raise WindowStop.of(PagePart.DATE, LoginSign.REDIRECT)
        return True

    @_action(PagePart.EMMETT)
    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        """Ładuje Wycenę Emmetta do otwartego zlecenia, czyta stronę po przeładowaniu, które robi skrypt efenix, i oddaje ją
        z tym, co pokazało okno Emmetta (``EmmettLoad``), werdyktowi Wyceny ``verdict`` w tym samym działaniu okna.

        Po odmowie „Załaduj do zlecenia” odpowiedzią z przekierowaniem albo statusem błędu okno nie czeka na przeładowanie
        i strony nie czyta. Przed kliknięciem okno czyta, czy okno Emmetta coś pokazało, a gdy nic, czy propozycja
        przyszła cała ze statusem 2xx (#908). Treści odpowiedzi „Załaduj do zlecenia” okno nie czyta, więc
        przeładowanie, które ją porzuca, nic nie zmienia (#895).
        """

        button = self._element(Element.EMMETT_BUTTON, PagePart.EMMETT)
        with _doing(Operation.ANSWER), self._page.expect_request(
            lambda request: _is_post(request, FILL_EMMETT), timeout=self._timeout_ms
        ) as asked:
            self._click(button)
        dialogs = self._element(Element.EMMETT_DIALOG, PagePart.EMMETT)
        with _doing(Operation.ELEMENT):
            dialogs.locator("visible=true").first.wait_for(state="visible", timeout=self._timeout_ms)
        with _doing(Operation.READ):
            window = emmett_window(self._page)
        if (fault := emmett_window_fault(window)) is not None:
            raise WindowStop.of(PagePart.EMMETT, fault)
        seen = Proposal.SHOWN if window.shows else Proposal.NOTHING if _came_whole(asked.value) else Proposal.LOST
        load = self._element(Element.EMMETT_LOAD, PagePart.EMMETT)

        def load_to_order() -> None:
            answer = self._answer(LOAD_EMMETT, lambda _params: True, lambda: self._click(load))
            if _redirected_to_login(answer):
                raise WindowStop.of(PagePart.EMMETT, LoginSign.REDIRECT)
            if 300 <= answer.status < 400:
                raise WindowStop.of(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))

        reloaded = self._reloaded(load_to_order)
        loaded = self._read_order(reloaded)
        return verdict(EmmettLoad(seen, loaded))

    @_action(PagePart.QUANTITY)
    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        field_id = self._positions.get(position)
        if field_id is None:
            raise WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.UNKNOWN_POSITION, position))
        with _doing(Operation.READ):
            field = single(self._page, f"{QUANTITY}#{field_id}", PagePart.QUANTITY)
        self._click(field)
        with _doing(Operation.FILL):
            field.fill(str(quantity), timeout=self._timeout_ms)
        answer = self._answer(SAVE_QUANTITY, lambda params: params.get("index") == [field_id], lambda: self._enter(field))
        if _redirected_to_login(answer):
            raise WindowStop.of(PagePart.QUANTITY, LoginSign.REDIRECT)
        try:
            saved = json.loads(self._text(answer))
        except ValueError as error:
            raise WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.ANSWER_NOT_JSON, position)) from error
        result = saved.get("result") if isinstance(saved, dict) else None
        if result == "nok":
            raise WindowStop.of(PagePart.QUANTITY, LoginSign.REFUSED)
        if result != "ok":
            raise WindowStop.of(PagePart.QUANTITY, OtherShape(Shape.ANSWER_RESULT, position))
        shown = str(saved.get(PRICE_ALL, ""))
        total = amount(shown, PagePart.QUANTITY)
        with _doing(Operation.AMOUNT):
            self._page.wait_for_function(_SHOWS, arg=[AMOUNT, shown], timeout=self._timeout_ms)
        return total

    @_action(PagePart.FORWARD)
    def forward_to_accept(self) -> ForwardRefusal | None:
        """Przekazuje otwarte zlecenie do akceptacji: przycisk Przekazania, „Tak” w oknie zmiany statusu, koniec żądania
        ``action_change_status.php`` i przeładowanie strony, które robi skrypt efenix po odpowiedzi. Odmowę efenix w
        oknie informacji oddaje bez „Tak” (``_refusal``)."""

        self._click(self._element(Element.FORWARD_BUTTON, PagePart.FORWARD))
        if (refusal := self._refusal()) is not None:
            return refusal
        confirm = self._element(Element.FORWARD_OK, PagePart.FORWARD)

        def accept() -> None:
            answer = self._status_answer(lambda: self._click(confirm))
            if _redirected_to_login(answer):
                raise WindowStop.of(PagePart.FORWARD, LoginSign.REDIRECT)

        # Status zmieniło już żądanie Przekazania (``_status_answer``), więc strony po przeładowaniu okno nie czyta,
        # a tylko sprawdza jej adres.
        self._reloaded(accept)
        self._ensure_logged_in(PagePart.FORWARD)
        return None

    def _refusal(self) -> ForwardRefusal | None:
        """Odmowa Przekazania, gdy po przycisku Przekazania skrypt efenix pokazał okno informacji, a nie okno zmiany
        statusu: okno czeka na pokazanie jednego z nich, a z okna informacji czyta tekst i zamyka je. Tekst skrypt efenix
        wpisuje, zanim pokaże okno."""

        dialog = self._element(Element.FORWARD_DIALOG, PagePart.FORWARD)
        info = self._element(Element.INFO_DIALOG, PagePart.FORWARD)
        with _doing(Operation.ELEMENT):
            dialog.or_(info).filter(visible=True).first.wait_for(state="visible", timeout=self._timeout_ms)
            refused = info.is_visible()
        if not refused:
            return None
        text = self._element(Element.INFO_TEXT, PagePart.FORWARD)
        with _doing(Operation.READ):
            shown = text.text_content(timeout=self._timeout_ms) or ""
        self._close(Element.INFO_DIALOG, Element.INFO_DISMISS, PagePart.FORWARD)
        return ForwardRefusal.of(shown)

    def _status_answer(self, act: Callable[[], None]) -> Response:
        """Odpowiedź efenix na żądanie Przekazania do akceptacji, które wysyła ``act``.

        Strażnik przepuszcza je tylko w tym czasie. Okno czeka na koniec albo porażkę żądania zmiany statusu, a nie na
        samo żądanie, bo żądanie przerwane przez strażnika nie kończy się odpowiedzią: wtedy to ``StatusChangeBlocked``.
        Treści odpowiedzi okno nie czyta, a porażka po nagłówkach to odpowiedź, bo przeładowanie strony, które skrypt
        robi zaraz po nagłówkach, porzuca treść (jak po „Załaduj do zlecenia”, #895). Żądanie bez nagłówków odpowiedzi w
        czasie okna albo z zerwanym połączeniem to ``Shape.STATUS_NOT_ANSWERED``, a odpowiedź ze statusem błędu
        ``HttpStatus`` (``_ErrorAnswer``).
        """

        ended: list[Request] = []
        context = self._page.context

        def on_ended(request: Request) -> None:
            if _changes_status(request.url):
                ended.append(request)

        context.on("requestfinished", on_ended)
        context.on("requestfailed", on_ended)
        self._forwarding = True
        try:
            act()
            deadline = time.monotonic() + self._timeout_ms / 1000
            while not (ended or self._blocked) and time.monotonic() < deadline:
                with _doing(Operation.ANSWER):
                    self._page.wait_for_timeout(_STATUS_POLL_MS)
        finally:
            self._forwarding = False
            context.remove_listener("requestfinished", on_ended)
            context.remove_listener("requestfailed", on_ended)
        self.raise_blocked()
        response = None
        if ended:
            with _doing(Operation.ANSWER):
                response = ended[0].response()
        if response is None:
            raise WindowStop.of(PagePart.FORWARD, OtherShape(Shape.STATUS_NOT_ANSWERED))
        if response.status >= 400:
            raise _ErrorAnswer(HttpStatus(response.status))
        return response

    def _read_order(self, response: Response | None) -> OrderPricing:
        """Strona zlecenia, na którą przeglądarka przeszła odpowiedzią ``response`` (otwarcie albo przeładowanie).

        Stronę, której nie przeczytało, okno nazywa w przyczynie stroną błędu HTTP (nawigacja nie zgłasza błędu przy
        statusie 4xx i 5xx) albo formularzem logowania pod adresem zlecenia, zanim uzna ją za stronę w innej budowie.
        Sprawdza to tylko po nieudanym odczycie, więc strony, którą czyta, nie odrzuca.
        """

        self._ensure_logged_in(PagePart.ORDER)
        try:
            with _doing(Operation.READ):
                pricing, positions = read_order(self._page, timeout_ms=self._timeout_ms)
        except UnexpectedPage as unread:
            if (error_page := _error_page(response)) is not None:
                raise WindowStop.of(PagePart.ORDER, error_page) from unread
            if login_form(self._page):
                raise WindowStop.of(PagePart.ORDER, OtherShape(Shape.LOGIN_FORM)) from unread
            raise
        self._positions = dict(positions)
        return pricing

    def _element(self, element: Element, part: PagePart) -> Locator:
        """Element strony tyle razy, ile deklaruje jego ``PageElement`` (``fits``: dokładnie raz albo, z ``many``, co
        najmniej raz); inna liczba to ``ElementCount``. Narzędzie zgodności mierzy efenix tą samą regułą."""

        located = self._page.locator(element.selector)
        with _doing(Operation.READ):
            count = located.count()
        if not element.element.fits(count):
            raise WindowStop.of(part, ElementCount(element.selector, count))
        return located

    @contextmanager
    def _still_single(self, selector: str, part: PagePart) -> Iterator[None]:
        """Działanie przeglądarki na elemencie ``selector``, który był na stronie dokładnie raz: gdy się nie udało, a
        elementu nie ma już dokładnie raz, strona zmieniła budowę między sprawdzeniem a działaniem, więc to
        ``ElementCount`` jak w ``single``, a nie błąd przeglądarki. Tak jest z polem ``Numer``, gdy odpowiedź szukania,
        które lista wysyła sama, wkłada do ``#wyniki`` stronę listy, na którą przekierował ją efenix (#971). Liczenie ma
        czas okna, bo strona, która nie odpowiada, zatrzymałaby okno tu bez końca (#886)."""

        try:
            yield
        except _Failed as failed:
            try:
                counted = self._page.wait_for_function(_COUNT, arg=selector, timeout=self._timeout_ms)
                count = int(counted.json_value()["count"])
            except PlaywrightError:
                raise failed from failed.__cause__
            if count != 1:
                raise WindowStop.of(part, ElementCount(selector, count)) from failed.__cause__
            raise

    def _shown(self, element: Element, part: PagePart) -> None:
        located = self._element(element, part)
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

    def _close(self, dialog: Element, dismiss: Element, part: PagePart) -> None:
        located = self._element(dialog, part)
        with _doing(Operation.ELEMENT):
            self._page.wait_for_function(_SETTLED, arg=dialog.selector, timeout=self._timeout_ms)
        self._click(self._element(dismiss, part).first)
        with _doing(Operation.ELEMENT):
            located.wait_for(state="hidden", timeout=self._timeout_ms)

    def _answer(self, path: str, wanted: Callable[[dict[str, list[str]]], bool], act: Callable[[], None]) -> Response:
        """Odpowiedź efenix na zmianę zlecenia, którą wysyła ``act``."""

        self._sent.send()
        return self._finished(lambda request: _is_post(request, path) and wanted(_form(request)), act)

    def _finished(self, wanted: Callable[[Request], bool], act: Callable[[], None]) -> Response:
        """Odpowiedź efenix z całą treścią na żądanie ``wanted``, które wysyła ``act``: okno czeka w czasie ``timeout_ms``
        na koniec żądania, a nie na nagłówki odpowiedzi, po których treść może się urwać albo stanąć.

        Odpowiedź ze statusem błędu (4xx, 5xx) to ``_ErrorAnswer``, zanim okno ją przeczyta: skrypt strony efenix jej nie
        użyje, a jej treść to strona błędu serwera, nie odpowiedź w innej budowie. Przekierowanie (3xx) okno czyta dalej.
        """

        with _doing(Operation.ANSWER):
            with self._page.expect_request_finished(wanted, timeout=self._timeout_ms) as finished:
                act()
            response = finished.value.response()
        assert response is not None, "zakończone żądanie ma odpowiedź"
        if response.status >= 400:
            raise _ErrorAnswer(HttpStatus(response.status))
        return response

    def _ensure_logged_in(self, part: PagePart) -> None:
        if _on_login_page(self._page.url):
            raise WindowStop.of(part, LoginSign.PAGE)

    def _go(self, url: str) -> Response | None:
        """Jedyne przejście karty pod adres ``url`` (``Operation.OPEN``). Odpowiedź oddaje temu, kto czyta stronę, bo
        nawigacja nie zgłasza błędu przy statusie 4xx i 5xx: o stronę, której nie przeczytał, pyta ``_error_page``."""

        with _doing(Operation.OPEN):
            return self._page.goto(url, wait_until="load", timeout=self._timeout_ms)

    def _reloaded(self, act: Callable[[], None]) -> Response | None:
        """Jedyne czekanie na przeładowanie strony, które skrypt efenix robi po działaniu ``act`` (``Operation.RELOAD``),
        z odpowiedzią przeładowania jak ``_go``. Wyjątek ``act`` kończy czekanie bez przeładowania."""

        with _doing(Operation.RELOAD), self._page.expect_navigation(wait_until="load", timeout=self._timeout_ms) as reload:
            act()
        return reload.value


class _Failed(Exception):
    """Błąd Playwrighta w działaniu przeglądarki, które nazwał ``_doing``; ``__cause__`` to ten błąd."""

    def __init__(self, failure: BrowserFailure) -> None:
        super().__init__(failure.error_type)
        self.failure = failure


class _ErrorAnswer(Exception):
    """Odpowiedź efenix ze statusem błędu na żądanie, na które okno czeka (``_finished``); część strony daje ``_within``."""

    def __init__(self, status: HttpStatus) -> None:
        super().__init__(status.status)
        self.status = status


@contextmanager
def _doing(operation: Operation) -> Iterator[None]:
    """Działanie przeglądarki ``operation`` w działaniu okna: błąd Playwrighta w nim to ``_Failed`` z typem błędu."""

    try:
        yield
    except PlaywrightError as error:
        raise _Failed(BrowserFailure(exception_type(error), operation)) from error


def _error_page(response: Response | None) -> HttpStatus | None:
    """Jedyne sprawdzenie odpowiedzi nawigacji (``BrowserEfenix._go``, ``_reloaded``): dowód ``HttpStatus`` dla
    ``WindowStop.of``, gdy odpowiedź ma status błędu HTTP, bo to strona błędu serwera efenix, a nie strona w innej
    budowie; inaczej ``None``. Pyta się je dopiero po nieudanym odczycie strony, bo strony, którą okno przeczytało, żaden
    status nie odrzuca."""

    return None if response is None or response.ok else HttpStatus(response.status)


@contextmanager
def _within(part: PagePart) -> Iterator[None]:
    """Działanie na części ``part`` strony, które skończyło się błędem Playwrighta, to ``UnexpectedPage(part)`` z typem
    błędu i działaniem przeglądarki (``None``, gdy ``_doing`` go nie nazwał), a odpowiedzią efenix ze statusem błędu
    (``_ErrorAnswer``) to ``UnexpectedPage(part)`` z tym statusem."""

    try:
        yield
    except _ErrorAnswer as answer:
        raise WindowStop.of(part, answer.status) from answer
    except _Failed as failed:
        raise WindowStop.of(part, failed.failure) from failed.__cause__
    except PlaywrightError as error:
        raise WindowStop.of(part, BrowserFailure(exception_type(error), None)) from error


def _is_search(request: Request, number: str) -> bool:
    return _is_post(request, SEARCH) and _form(request).get(NUMBER_PARAM) == [number]


def _is_post(request: Request, path: str) -> bool:
    return request.method == "POST" and urlparse(request.url).path.endswith("/" + path)


def _came_whole(request: Request) -> bool:
    """Czy efenix odpowiedział na skończone żądanie ``request`` całą odpowiedzią ze statusem 2xx: bez statusu błędu,
    przekierowania i zerwania połączenia przed nagłówkami albo w trakcie treści.

    Na koniec żądania, które już się skończyło, Playwright nie czeka: odpowiedź bez nagłówków to ``None``, a treść
    zerwana w połowie to błąd odczytu treści (pomiar 5.11.2026 w Chromium Playwrighta, synchroniczne XHR jak efenix i
    ``fetch`` jak Atrapa, #908). Każdy inny błąd odczytu, np. zamknięta karta, też znaczy, że okno odpowiedzi nie zna.
    """

    with _doing(Operation.ANSWER):
        response = request.response()
    if response is None or not response.ok:
        return False
    try:
        response.body()
    except PlaywrightError:
        return False
    return True


def _form(request: Request) -> dict[str, list[str]]:
    return parse_qs(request.post_data or "")


def _changes_status(url: str) -> bool:
    """Żądanie zmiany statusu zlecenia: ``action_change_status`` w ścieżce bez wielkości liter i po zdekodowaniu, więc
    także pod inną pisownią tego samego skryptu PHP i z dalszą częścią ścieżki."""

    return CHANGE_STATUS.removesuffix(".php") in unquote(urlparse(url).path).casefold()


def _field(request: Request, name: str) -> list[str]:
    """Każda wartość pola ``name`` żądania, z adresu i z treści formularza, po kolei."""

    query = parse_qs(urlparse(request.url).query, keep_blank_values=True).get(name, [])
    return query + parse_qs(request.post_data or "", keep_blank_values=True).get(name, [])


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
    ``clock``), bez niego to ``LoggedOut``. Od początku bloku kontekst przeglądarki strony ma strażnika zmiany statusu
    (``BrowserEfenix.guard``) do swojego zamknięcia, a żądanie, które strażnik przerwał po ostatnim działaniu okna, to
    ``UnexpectedPage`` na końcu bloku.
    """

    efenix = BrowserEfenix(page, url, timeout_ms=timeout_ms)
    # Strażnika okno nie zdejmuje: ``unroute`` na stronie, której skrypt nie odpowiada, czeka na nią, a kontekst z
    # przeglądarką okna i tak zamyka się po bloku (``chrome``, ``chromium``).
    page.context.route(_changes_status, efenix.guard)
    if login is None:
        efenix.open_list()
    else:
        efenix.wait_for_login(login, timeout_ms=login_timeout_ms, clock=clock)
    yield efenix
    efenix.raise_blocked()


def default_profile() -> Path:
    """Profil przeglądarki okna efenix taty: osobny od jego profilu z kartami, trwały między uruchomieniami."""

    return TOOL_ROOT / PROFILE_DIRECTORY


# Funkcje Chromium, które każda przeglądarka okna wyłącza ponad listę Playwrighta. ``TcpPortRandomizationWin``: Chromium
# 156 na Windows 11 22H2 i nowszym (także Windows Server 2025 runnerów CI) losuje port lokalny każdego połączenia, a
# Windows odmawia wtedy czasem połączenia z WSAENOBUFS (``net::ERR_NO_BUFFER_SPACE``), choć porty są wolne
# (crbug.com/572515601, microsoft/playwright#43545). Playwright wyłącza ją sam od microsoft/playwright#43605, scalonego
# po wydaniu 1.64.1.
_DISABLED_FEATURES: Final = ("TcpPortRandomizationWin",)
_DISABLE_FEATURES: Final = "--disable-features="
# Przełączniki ``--disable-features``, które Playwright daje przeglądarce danego kanału, raz na proces.
_PLAYWRIGHT_DISABLING: dict[str | None, tuple[str, ...]] = {}


class LaunchOptions(TypedDict):
    ignore_default_args: list[str]
    args: list[str]


def launch_options(playwright: Playwright, *, channel: str | None = None, arguments: Sequence[str] = ()) -> LaunchOptions:
    """Argumenty uruchomienia przeglądarki ``channel`` okna efenix (``None`` to Chromium Playwrighta) z ``arguments``.

    Jeden ``--disable-features`` z listą Playwrighta i ``_DISABLED_FEATURES`` zamiast przełącznika Playwrighta, bo
    Chromium bierze tylko ostatni ``--disable-features``, a własny obok zgubiłby listę Playwrighta. Tej listy Playwright
    nie podaje w API, więc daje ją linia poleceń przeglądarki tego kanału uruchomionej raz na proces bez okna i zaraz
    zamkniętej; ``PlaywrightError``, gdy ta przeglądarka nie wystartowała.
    """

    theirs = _playwright_disabling(playwright, channel)
    features = [feature for switch in theirs for feature in switch.removeprefix(_DISABLE_FEATURES).split(",")]
    disabled = ",".join(dict.fromkeys([*features, *_DISABLED_FEATURES]))
    return {"ignore_default_args": list(theirs), "args": [_DISABLE_FEATURES + disabled, *arguments]}


def _playwright_disabling(playwright: Playwright, channel: str | None) -> tuple[str, ...]:
    if channel not in _PLAYWRIGHT_DISABLING:
        # ``--enable-automation`` odblokowuje ``Browser.getBrowserCommandLine``.
        probe = playwright.chromium.launch(channel=channel, headless=True, args=["--enable-automation"])
        try:
            line = probe.new_browser_cdp_session().send("Browser.getBrowserCommandLine")["arguments"]
        finally:
            probe.close()
        _PLAYWRIGHT_DISABLING[channel] = tuple(str(argument) for argument in line if str(argument).startswith(_DISABLE_FEATURES))
    return _PLAYWRIGHT_DISABLING[channel]


@contextmanager
def _playwright() -> Iterator[Playwright]:
    """Playwright okna na czas bloku; ``BrowserNotStarted`` z ``Operation.DRIVER``, gdy jego sterownik nie wystartował.

    Sterownik to osobny proces z własną pętlą zdarzeń, której start zgłasza ``OSError`` (np. ``socketpair`` pętli na
    Windows bez wolnych gniazd, #975, albo brak programu sterownika) albo błąd Playwrighta. To droga startu okna, a nie
    nieoczekiwany wyjątek: Logi Uruchomienia nazywają ją i niosą typ wyjątku z ramkami (#976).
    """

    try:
        playwright = sync_playwright().start()
    except (PlaywrightError, OSError) as error:
        raise WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.DRIVER)) from error
    try:
        yield playwright
    finally:
        playwright.stop()


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

    with _playwright() as playwright:
        try:
            options = launch_options(playwright, channel=channel, arguments=arguments)
            context = playwright.chromium.launch_persistent_context(
                profile, channel=channel, headless=headless, no_viewport=True, service_workers="block", **options
            )
        except PlaywrightError as error:
            raise WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.START)) from error
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
    """Okno efenix w nowym Chromium Playwrighta (Skrypt dla maszyn); przeglądarka zamyka się z oknem.
    ``BrowserNotStarted``, gdy Chromium nie wystartował, jak w ``chrome``."""

    with _playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless, **launch_options(playwright))
        except PlaywrightError as error:
            raise WindowStop.of(PagePart.LIST, BrowserFailure(exception_type(error), Operation.START)) from error
        try:
            with window(browser.new_page(service_workers="block"), url) as efenix:
                yield efenix
        finally:
            browser.close()
