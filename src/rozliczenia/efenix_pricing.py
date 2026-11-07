"""Wycena w efenix: wycena każdego zlecenia z zakresu Pliku zbiorczego uzupełniona w efenix, w sesji, którą otworzył tata.

Jedyną operacją publiczną jest ``price_orders()``. Silnik sekwencjonuje cztery etapy i jako jedyny tłumaczy fakty na
Komunikaty: Sprawdzanie (Plik zbiorczy jest, nie trzyma go Excel i daje się otworzyć okno efenix z listą zleceń), Odczyt
danych (zakres z ``efenix_orders``), Planowanie (Zatrzymanie, gdy Plik zbiorczy nie ma kwot AU policzonych przez Excel) i
Zapisywanie, w którym idzie przez zlecenia z zakresu po kolei, a na końcu raz oznacza gotowe Znacznikiem efenix. Najpierw to, co widać bez efenix: numer, data i ilości, które da się
przepisać (``efenix_positions``). Potem zlecenie znajduje po ``Numer dokumentu`` równym ``NUMER ZL.`` i sprawdza:
dokładnie jedno trafienie, status „Do wyceny”, realizator równy ``WYKONAWCA``, ``Dane adresowe`` równe ``ADRES``
(``efenix_address``) i datę wykonania (``date_problem``). Pierwsza niezgodność to błąd zlecenia, w efenix
nic się nie zmienia i proces idzie dalej. Zlecenie o statusie „Rozliczone” z realizatorem i adresem z pliku to Zlecenie
rozliczone (``Settled``): proces go nie otwiera, nie oznacza i nie zostawia tacie jako błędu. Każdy odczyt strony zlecenia (otwarcie, ponowne otwarcie po dacie wykonania i
strona po Wycenie Emmetta) musi mieć pozycje, w których plik ma ilość: strona bez którejś z nich to błąd zlecenia z
kodami pozycji i ich kolumnami (``missing_positions``), a strona bez pozycji z 0 w pliku to zwykła strona efenix.

Wycenę zlecenia proces dokańcza do Pliku zbiorczego tylko w górę (ADR 0026, ``completion``). Najpierw, z ilościami na
stronie albo bez, ustawia datę wykonania z ``DATA``, gdy jest pusta, i sprawdza ją na ponownie otwartej stronie (dzień,
którego kalendarz efenix nie przyjął albo którego efenix nie zapisał, to błąd zlecenia ``DateRefused`` bez Emmetta i bez
zmian ilości), żeby gotowe zlecenie nie zostało bez daty wykonania. Strona bez żadnej ilości nie ma wyceny: proces ładuje
do niej Wycenę Emmetta, a czy efenix ją załadował, rozstrzyga z obserwacji okna (``EmmettLoad``): strona po
przeładowaniu bez żadnej ilości to odmowa „Załaduj do zlecenia” i Zatrzymanie, chyba że Emmett nic nie zaproponował
(``_emmett``). Strona z ilościami ma już wycenę, zaczętą przez proces, przez tatę albo samą
Wycenę Emmetta: proces nie ładuje do niej Wyceny Emmetta, bo „Załaduj do zlecenia” czyści wycenę. Potem w obu
przypadkach proces wpisuje ilość z pliku w każdej pozycji, w której strona ma mniej niż plik,
także w miejsce ilości Emmetta. Pozycji, w której strona ma więcej niż plik, nie
obniża i nie czyści: zlecenie z taką pozycją to Ostrzeżenie Emmetta z pozycją i obiema ilościami, choć resztę ilości
proces i tak wpisał. Zlecenie bez takiej pozycji jest gotowe, gdy kwota końcowa, którą odesłał efenix, jest równa
``Kwota`` (AU), a w przeciwnym razie to błąd z obiema kwotami. Ponowne uruchomienie dokańcza więc każde zlecenie, które
przerwało Zatrzymanie albo zgaśnięcie Centrum, tak samo jak zlecenie zaczęte przez tatę. Okno efenix (``Efenix``) nie ma działania, które przekazuje zlecenie do
akceptacji, anuluje je albo zmienia jego status. Strona logowania, efenix, którego okno nie otworzyło, zamknięte okno
efenix i działanie okna, którego okno nie dokończyło, to Zatrzymanie (``LoggedOut``, ``EfenixUnreachable``,
``WindowClosed``, ``UnexpectedPage``), a Komunikat Zatrzymania mówi, czy przed nim proces zmienił już coś w efenix:
rozstrzyga to Wycena ze śladu zleceń i z działania, przy którym okno stanęło (``_kept``), a nie okno.
Niedokończone działanie okna to Zatrzymanie „do Maksa” z częścią strony, bez treści strony i bez zgadywania przyczyny
(zerwane połączenie, wolny albo zmieniony efenix): tata uruchamia ponownie, a Maks ustala przyczynę z Logów Uruchomienia. Każdy wyjątek okna niesie przyczynę techniczną z zamkniętej listy
(``WindowCause``), a Zatrzymanie z okna niesie w ``StopError.facts`` (``PricingStopped``) tę przyczynę, wynik każdego
zlecenia sprzed niego i zlecenie, przy którym okno stanęło (``StoppedOrder``: wiersz, miejsce w przebiegu, udane
działania okna i to, które się nie udało). Komunikat taty przyczyny nie pokazuje.
Okno, które czeka, aż tata się zaloguje, robi to w ``Login`` od silnika: ten czas nie wlicza się do czasów etapów ani,
przez ``waiting`` rozmowy rdzenia, do ``Czas uruchomienia``. Postęp Zapisywania to kroki (``PhaseRunner.step``):
logowanie, zlecenia z Wykonawcą i liczbą sprawdzonych z wszystkich, na końcu Znaczniki efenix; ślad działań okna przy
każdym zleceniu (``efenix_trace``) trafia do jego wyniku, a stamtąd do Logów Uruchomienia. Dziennik Wyceny w efenix
(``OrderJournal``, w Centrum ``centrum.pricing_journal``) dostaje wpis o każdym zleceniu przed pierwszym działaniem okna przy
nim, więc przed każdym zapisem w efenix, i wpis z wynikiem zaraz po nim, zanim proces przejdzie do następnego zlecenia.

Po ostatnim zleceniu, a także przy Zatrzymaniu w trakcie, ``efenix_marking`` raz zapisuje Plik zbiorczy: komórka ``ADRES``
każdego gotowego zlecenia dostaje Znacznik efenix, a reszta pliku zostaje bajt w bajt. Gdy zapis się nie udaje (Excel trzyma
plik, plik zmienił się od odczytu, zapis nieudany), przebieg kończy się Zatrzymaniem z prośbą o ponowne uruchomienie, a
wycena w efenix zostaje; przy Zatrzymaniu z efenix zostaje jego Komunikat, bo ponowne uruchomienie i tak jest potrzebne.
Ponowne uruchomienie dokańcza oznaczanie: gotowe zlecenia mają już wycenę zgodną z plikiem, więc proces je tylko czyta. Wynik nie zawiera
numerów zleceń, adresów ani loginów, tylko numery wierszy Pliku zbiorczego.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date
import enum
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from . import efenix_messages as messages
from . import efenix_trace, workbook_files
from .client_data import ForbiddenColumn, ForbiddenValues
from .input_copy import InputCopy
from .domain import ProgressObserver, ProgressPhase
from .efenix_checks import (
    DateRefused,
    ListedOrder,
    OrderProblem,
    PagePart,
    Settled,
    date_problem,
    listing,
    searched_number,
)
from .efenix_marking import Refusal, mark_ready
from .efenix_orders import (
    AmountsNotComputed,
    CollectiveOrder,
    MissingColumns,
    PricingScope,
    read_scope,
)
from .efenix_pace import Pace, Pacing
from .efenix_positions import (
    Excess,
    NotWholeQuantities,
    OrderFault,
    OtherAmount,
    PageRead,
    UnpairedColumns,
    completion,
    file_quantities,
    missing_positions,
    same_amount,
)
from .efenix_trace import OrderTrace, TraceStep
from .message import Message, StopError
from .phase_runner import PhaseRunner
from .workbook_files import WorkbookError

__all__ = [
    "BrowserFailure",
    "BrowserNotStarted",
    "Closed",
    "Efenix",
    "EfenixUnreachable",
    "ElementCount",
    "EmmettLoad",
    "HttpStatus",
    "EmmettWarning",
    "ListedOrder",
    "LoggedOut",
    "Login",
    "LoginSign",
    "NO_JOURNAL",
    "OpenEfenix",
    "Operation",
    "OrderError",
    "OrderJournal",
    "OrderPricing",
    "OrderProblem",
    "OrderResult",
    "OtherShape",
    "PageCause",
    "PagePart",
    "PricingStopped",
    "PricingSummary",
    "Proposal",
    "Ready",
    "Settled",
    "Shape",
    "StoppedOrder",
    "UnexpectedPage",
    "WindowCause",
    "WindowClosed",
    "WindowStop",
    "price_orders",
]


class Operation(enum.Enum):
    """Działanie przeglądarki w oknie efenix, które skończyło się błędem Playwrighta."""

    DRIVER = "start sterownika Playwrighta"
    START = "start przeglądarki"
    OPEN = "otwarcie strony"
    RELOAD = "czekanie na przeładowanie strony przez skrypt efenix"
    ANSWER = "czekanie na całą odpowiedź efenix"
    ELEMENT = "czekanie na pokazanie albo schowanie elementu"
    AMOUNT = "czekanie na kwotę końcową z odpowiedzi na stronie"
    CLICK = "kliknięcie"
    FILL = "wpisanie w pole"
    ENTER = "Enter w polu"
    PICK = "wybór dnia w kalendarzu pickadate"
    READ = "odczyt strony"


class Shape(enum.Enum):
    """Strona albo odpowiedź efenix w budowie, której okno nie zna."""

    QUANTITY_ID = "pole Ilość o id spoza INDEKS_NNN_…"
    POSITION_TWICE = "kod pozycji w dwóch polach Ilość"
    QUANTITY_VALUE = "wartość pola Ilość, która nie jest liczbą całkowitą"
    DATE_TEXT = "data wykonania w innej postaci niż RRRR-MM-DD"
    AMOUNT_TEXT = "kwota w innej postaci niż liczba z kropką"
    NO_TABLE = "odpowiedź szukania bez tabeli i bez ostrzeżenia efenix, które zna okno"
    COLUMNS = "nagłówek kolumny tabeli wyników nie występuje dokładnie raz"
    ROW_CELLS = "wiersz tabeli wyników z inną liczbą komórek niż nagłówków albo bez jednego linku do strony zlecenia"
    ROW_EMPTY = "wiersz tabeli wyników bez identyfikatora zlecenia albo bez numeru"
    NO_CALENDAR = "pole daty wykonania bez kalendarza pickadate"
    UNKNOWN_POSITION = "pozycja bez pola Ilość na ostatnio odczytanej stronie zlecenia"
    ANSWER_NOT_JSON = "odpowiedź zapisu ilości, która nie jest JSON"
    ANSWER_RESULT = "odpowiedź zapisu ilości z wynikiem innym niż ok i nok"
    LOGIN_FORM = "formularz logowania efenix pod adresem strony zlecenia, bez przekierowania"
    ANSWER_REDIRECT = "odpowiedź na „Załaduj do zlecenia” przekierowana poza stronę logowania"
    EMMETT_NOT_LOADED = (
        "strona przeładowana po „Załaduj do zlecenia” bez wyceny, choć okno Emmetta pokazało propozycję albo propozycja"
        " nie przyszła cała ze statusem 2xx"
    )


class LoginSign(enum.Enum):
    """Po czym okno poznało, że efenix wylogował."""

    PAGE = "strona logowania zamiast strony, o którą prosiło okno"
    REDIRECT = "odpowiedź efenix przekierowana na stronę logowania"
    SESSION_WARNING = "odpowiedź szukania z samym ostrzeżeniem efenix o wygasłej sesji"
    REFUSED = "odpowiedź zapisu ilości z wynikiem nok"
    NO_LOGIN = "tata nie zalogował się w czasie, w którym okno czeka na logowanie"


class Closed(enum.Enum):
    """Kiedy okno zastało zamkniętą kartę albo okno przeglądarki."""

    DURING_ACTION = "karta albo okno zamknięte przed działaniem okna albo w jego trakcie"
    DURING_LOGIN = "karta albo okno zamknięte w czasie czekania na logowanie taty"


@dataclass(frozen=True)
class ElementCount:
    """Element strony (selektor z kodu okna, nie treść strony) jest na niej ``count`` razy zamiast dokładnie raz."""

    selector: str
    count: int


@dataclass(frozen=True)
class HttpStatus:
    """Odpowiedź efenix, na którą okno czekało, albo strona, której okno nie przeczytało, przyszła ze statusem błędu
    HTTP ``status`` (4xx, 5xx): to strona błędu serwera efenix, a nie strona albo odpowiedź w innej budowie."""

    status: int


@dataclass(frozen=True)
class OtherShape:
    """Budowa strony albo odpowiedzi, której okno nie zna; ``position``: kod pozycji, gdy dotyczy jednej pozycji."""

    shape: Shape
    position: str | None = None


@dataclass(frozen=True)
class BrowserFailure:
    """Błąd Playwrighta: typ wyjątku (bez jego treści, w której bywa adres i selektor) i działanie, w którym wystąpił
    (``None``: działanie okna bez nazwy)."""

    error_type: str
    operation: Operation | None


PageCause = ElementCount | HttpStatus | OtherShape | BrowserFailure
"""Przyczyna niedokończonego działania okna (``UnexpectedPage``)."""
WindowCause = PageCause | LoginSign | Closed
"""Przyczyna techniczna Zatrzymania okna efenix z zamkniętej listy, dla Logów Uruchomienia, bez treści strony i danych
zleceń; Komunikat taty jej nie pokazuje."""


class WindowStop(Exception):
    """Okno efenix nie może działać dalej: część strony (``None`` poza stronami efenix) i przyczyna techniczna.

    ``sent``: działanie okna, które zgłosiło wyjątek, kliknęło już przycisk, który wysyła do efenix zmianę zlecenia (data
    wykonania, „Załaduj do zlecenia”, Enter w polu „Ilość”), więc efenix mógł ją zapisać. Ustawia je okno.
    """

    sent: bool = False

    def __init__(self, part: PagePart | None, cause: WindowCause) -> None:
        super().__init__(None if part is None else part.name)
        self.part = part
        self.cause = cause


class LoggedOut(WindowStop):
    """efenix wylogował okno: pokazał stronę logowania albo ostrzeżenie o wygasłej sesji zamiast strony albo odpowiedzi,
    o którą prosiło okno (``sign`` mówi, po czym okno to poznało)."""

    def __init__(self, part: PagePart, sign: LoginSign) -> None:
        super().__init__(part, sign)


class UnexpectedPage(WindowStop):
    """Okno nie dokończyło działania w części ``part`` strony efenix (bez treści strony): strona nie ma budowy, którą
    zna okno, albo przeglądarka zgłosiła błąd (także czas okna, który minął); ``cause`` mówi, które z nich."""

    def __init__(self, part: PagePart, cause: PageCause) -> None:
        super().__init__(part, cause)
        self.part: PagePart = part


class EfenixUnreachable(WindowStop):
    """Okno nie otworzyło efenix przy starcie: adres nie odpowiada albo nie ma połączenia."""

    def __init__(self, failure: BrowserFailure) -> None:
        super().__init__(PagePart.LIST, failure)


class WindowClosed(WindowStop):
    """Okno albo karta efenix zamknęły się w trakcie przebiegu (tata je zamknął)."""

    def __init__(self, part: PagePart, closed: Closed) -> None:
        super().__init__(part, closed)


class BrowserNotStarted(WindowStop):
    """Przeglądarka okna efenix nie wystartowała: nie ma jej na komputerze, jej profil trzyma inne okno albo nie
    wystartował sterownik Playwrighta (``Operation.DRIVER``)."""

    def __init__(self, failure: BrowserFailure) -> None:
        super().__init__(None, failure)


@dataclass(frozen=True)
class OrderPricing:
    """Strona zlecenia efenix w tym, co porównuje proces: data wykonania (``None``, gdy pusta), kwota końcowa i ilość
    każdej pozycji wyceny (kod ``NNN`` → ilość, pole puste to 0)."""

    execution_date: date | None
    amount: Decimal
    quantities: Mapping[str, int]


class Proposal(enum.Enum):
    """Co okno Emmetta pokazało przed „Załaduj do zlecenia” (#908)."""

    SHOWN = "okno Emmetta coś pokazało"
    NOTHING = "okno Emmetta nic nie pokazało, a propozycja przyszła cała ze statusem 2xx"
    LOST = "okno Emmetta nic nie pokazało, a propozycja nie przyszła cała ze statusem 2xx"


@dataclass(frozen=True)
class EmmettLoad:
    """Obserwacje okna po odpowiedzi 2xx na „Załaduj do zlecenia”: co pokazało okno Emmetta przed kliknięciem
    (``proposal``) i strona zlecenia po przeładowaniu, które robi skrypt efenix (``page``). Czy efenix załadował Wycenę
    Emmetta, rozstrzyga z nich Wycena (``_emmett``), a nie okno."""

    proposal: Proposal
    page: OrderPricing


class Efenix(Protocol):
    """Okno efenix w sesji taty z listą dozwolonych działań: szukanie, otwarcie zlecenia, data wykonania, Wycena Emmetta i
    pola „Ilość”. Przekazania do akceptacji, anulowania ani zmiany statusu zlecenia w nim nie ma.

    Działania po ``open_order`` dotyczą otwartego zlecenia. Każde działanie zgłasza ``LoggedOut`` na stronie logowania,
    ``UnexpectedPage``, gdy go nie dokończyło, i ``WindowClosed`` w zamkniętym oknie, z ``WindowStop.sent``, gdy przed
    wyjątkiem kliknęło już przycisk zmiany zlecenia.
    """

    def search(self, number: str) -> Sequence[ListedOrder]:
        """Wiersze listy zleceń po szukaniu po ``Numer``."""
        ...

    def open_order(self, order: ListedOrder) -> OrderPricing:
        """Otwiera stronę zlecenia i czyta jego datę wykonania i wycenę."""
        ...

    def set_execution_date(self, day: date) -> bool:
        """Wybiera ``day`` w kalendarzu daty wykonania otwartego zlecenia i potwierdza go.

        ``False``, gdy kalendarz efenix zamienił dzień na inny: wtedy okno zamyka kalendarz bez „Potwierdź” i niczego nie
        wysyła. ``True`` znaczy tylko, że efenix odpowiedział na „Potwierdź”; czy zapisał dzień, pokazuje ``open_order``.
        """
        ...

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        """Ładuje do otwartego zlecenia Wycenę Emmetta (efenix czyści wtedy dotychczasową wycenę), czyta stronę od nowa i
        zwraca stronę, którą przyjął werdykt Wyceny ``verdict`` z obserwacji okna (``EmmettLoad``).

        Werdykt biegnie w działaniu okna, więc jego Zatrzymanie jest, jak każdy wyjątek okna, nieudaną Wyceną Emmetta w
        śladzie zlecenia (``efenix_trace``).
        """
        ...

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        """Wpisuje ``quantity`` w pole „Ilość” pozycji ``position`` otwartego zlecenia; kwota końcowa, którą odesłał efenix.

        ``LoggedOut`` znaczy, że efenix tej ilości nie zapisał; po każdym innym wyjątku mógł ją zapisać albo nie.
        """
        ...


Login = Callable[[], AbstractContextManager[None]]
"""Czas, w którym okno czeka, aż tata zaloguje się w efenix; silnik nie liczy go do czasów Uruchomienia."""

OpenEfenix = Callable[[Login], AbstractContextManager[Efenix]]
"""Otwiera okno efenix z listą zleceń na czas Zapisywania, a czekanie na logowanie taty robi w ``Login``;
``BrowserNotStarted``, ``EfenixUnreachable``, ``LoggedOut``, ``UnexpectedPage`` albo ``WindowClosed``."""


@dataclass(frozen=True)
class Ready:
    """Wycena zlecenia w efenix zgadza się z Plikiem zbiorczym, a kwota końcowa jest równa ``Kwota`` (AU)."""

    listed: ListedOrder


@dataclass(frozen=True)
class OrderError:
    """Zlecenie, które proces zostawia tacie: pierwsza niezgodność z efenix albo kwota inna niż AU."""

    problem: OrderFault


@dataclass(frozen=True)
class EmmettWarning:
    """Ostrzeżenie Emmetta: efenix ma w pozycjach ``excess`` więcej niż Plik zbiorczy, więc proces ich nie zmienił, a
    pozostałe ilości pliku wpisał."""

    excess: tuple[Excess, ...]


@dataclass(frozen=True)
class OrderResult:
    """Wynik zlecenia; ``steps``: ślad działań okna efenix przy nim, po kolei (``efenix_trace``)."""

    order: CollectiveOrder
    outcome: Ready | Settled | OrderError | EmmettWarning
    steps: tuple[TraceStep, ...] = ()


@dataclass
class PricingSummary:
    """Podsumowanie Wyceny w efenix: wynik każdego zlecenia z zakresu po kolei i liczby pominiętych Wierszy danych.

    ``warnings``: Komunikat każdego błędu zlecenia i każdego ostrzeżenia Emmetta, z numerem wiersza Pliku zbiorczego.
    """

    results: tuple[OrderResult, ...]
    with_photos: int
    defects: int
    warnings: list[Message] = field(default_factory=list)
    phase_durations_ms: Mapping[ProgressPhase, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def ready_count(self) -> int:
        return sum(isinstance(result.outcome, Ready) for result in self.results)

    @property
    def settled_count(self) -> int:
        return sum(isinstance(result.outcome, Settled) for result in self.results)

    @property
    def error_count(self) -> int:
        return sum(isinstance(result.outcome, OrderError) for result in self.results)

    @property
    def warning_count(self) -> int:
        return sum(isinstance(result.outcome, EmmettWarning) for result in self.results)

    @property
    def not_found(self) -> int:
        """Błędy zleceń, których efenix nie zna po numerze z ``NUMER ZL.``."""

        return sum(
            isinstance(result.outcome, OrderError) and result.outcome.problem is OrderProblem.UNKNOWN_NUMBER
            for result in self.results
        )

    @property
    def left_for_tata(self) -> tuple[tuple[OrderResult, Message], ...]:
        """Każde zlecenie z błędem albo ostrzeżeniem Emmetta po kolei z Komunikatem z ``warnings``."""

        left = [result for result in self.results if isinstance(result.outcome, (OrderError, EmmettWarning))]
        return tuple(zip(left, self.warnings, strict=True))


@dataclass(frozen=True)
class StoppedOrder:
    """Zlecenie, przy którym okno efenix stanęło: wiersz Pliku zbiorczego, miejsce w przebiegu (``place`` z ``total``, od
    1), udane działania okna przy nim po kolei i działanie, które się nie udało (``failed``, z samym rodzajem i czasem;
    ``None``, gdy ślad zlecenia nie ma nieudanego działania).
    """

    row: int
    place: int
    total: int
    steps: tuple[TraceStep, ...]
    failed: TraceStep | None


@dataclass(frozen=True)
class PricingStopped:
    """Fakty Zatrzymania okna efenix dla Logów Uruchomienia (``StopError.facts``): część strony (``None`` poza stronami efenix), przyczyna techniczna, wynik każdego zlecenia sprzed
    Zatrzymania (``summary``, z Komunikatami jak po przebiegu) i zlecenie, przy którym Wycena stanęła (``None``: przed
    pierwszym zleceniem, przy otwieraniu okna albo logowaniu)."""

    part: PagePart | None
    cause: WindowCause
    summary: PricingSummary
    stopped_at: StoppedOrder | None


class OrderJournal(Protocol):
    """Dziennik Wyceny w efenix w trakcie przebiegu: proces woła go na wątku przebiegu, zlecenie po zleceniu.

    Wpis nie może zatrzymać przebiegu: dziennik, który nie zapisał wpisu, sam to zgłasza i wraca.
    """

    def begun(self, row: int, place: int, total: int) -> None:
        """Zaczynam zlecenie z wiersza ``row`` Pliku zbiorczego, ``place`` z ``total`` w przebiegu (od 1), przed pierwszym
        działaniem okna efenix przy nim."""
        ...

    def ended(self, result: OrderResult, message: Message | None) -> None:
        """Zlecenie skończone z wynikiem ``result`` i jego Komunikatem (``None`` przy gotowym i rozliczonym)."""
        ...


class _NoJournal:
    """Przebieg bez dziennika (Skrypt dla maszyn, testy silnika)."""

    def begun(self, row: int, place: int, total: int) -> None:
        return None

    def ended(self, result: OrderResult, message: Message | None) -> None:
        return None


NO_JOURNAL: Final[OrderJournal] = _NoJournal()


# Kroki Zapisywania na karcie Uruchomienia.
_LOGIN: Final = "Zaloguj się w oknie efenix"
_ORDERS: Final = "Zlecenia"
_MARKING: Final = "Znaczniki efenix w Pliku zbiorczym"


def price_orders(
    source: Path,
    open_efenix: OpenEfenix,
    *,
    observer: ProgressObserver | None = None,
    clock: Callable[[], float] = time.perf_counter,
    waiting: Login = nullcontext,
    pace: Pace | None = None,
    forbidden: ForbiddenValues | None = None,
    journal: OrderJournal = NO_JOURNAL,
    copy: InputCopy | None = None,
) -> PricingSummary:
    """Uzupełnia w efenix wycenę każdego zlecenia z zakresu Pliku zbiorczego ``source`` i oznacza w nim gotowe zlecenia.

    Zgłasza ``StopError``, gdy nie można działać bezpiecznie. ``clock`` to zegar w sekundach, z którego liczone są czasy etapów i śladu zleceń, a
    ``waiting`` wstrzymuje zegar rozmówcy na czas czekania na logowanie taty. ``pace``: tempo ludzkie okna
    (``efenix_pace``), ``None`` bez przerw. ``journal``: dziennik Wyceny w efenix (``OrderJournal``). Komórki zakazanych
    kolumn Pliku zbiorczego i dane adresowe z listy wyników efenix poznaje ``forbidden`` (reguła danych, ADR 0025), a
    odczyt Pliku zbiorczego Kopia wejścia Uruchomienia ``copy`` (#841).
    """

    phases = PhaseRunner(observer, clock=clock)
    source = source.expanduser().resolve()

    def check() -> None:
        try:
            workbook_files.ensure_available(source)
        except WorkbookError as error:
            raise StopError(messages.source_unusable(error)) from error

    phases.check(check)

    def read() -> PricingScope | AmountsNotComputed | MissingColumns:
        try:
            return read_scope(source, forbidden, copy)
        except WorkbookError as error:
            raise StopError(messages.source_unusable(error)) from error

    read_outcome = phases.read(read)

    def plan() -> PricingScope:
        match read_outcome:
            case MissingColumns(headers):
                raise StopError(messages.missing_columns(source, headers))
            case AmountsNotComputed(row):
                raise StopError(messages.amounts_not_computed(source, row))
            case PricingScope():
                return read_outcome

    scope = phases.plan(plan, issue_count=lambda _: 0)

    @contextmanager
    def login() -> Iterator[None]:
        with phases.waiting(), waiting():
            phases.step(_LOGIN)
            yield

    def save() -> tuple[OrderResult, ...]:
        results: list[OrderResult] = []
        pacing = None if pace is None else Pacing(pace)
        total = len(scope.orders)
        current: tuple[int, CollectiveOrder, OrderTrace] | None = None

        def stopped(part: PagePart | None, cause: WindowCause) -> PricingStopped:
            before = tuple(results)
            summary = PricingSummary(before, scope.with_photos, scope.defects, _warnings(source, before))
            at = (
                None
                if current is None
                else StoppedOrder(current[1].row, current[0] + 1, total, tuple(current[2].steps), current[2].failed)
            )
            return PricingStopped(part, cause, summary, at)

        try:
            with _efenix_stops(lambda _error: False, stopped), open_efenix(login) as efenix:
                with _efenix_stops(lambda error: _kept(results, None if current is None else current[2], error), stopped):
                    for done, order in enumerate(scope.orders):
                        phases.step(_ORDERS, worker=order.worker, done=done, total=total)
                        trace = OrderTrace()
                        current = (done, order, trace)
                        journal.begun(order.row, done + 1, total)
                        window = efenix_trace.traced(efenix, order, trace, clock)
                        outcome = _outcome(order, window if pacing is None else pacing.window(window), forbidden)
                        result = OrderResult(order, outcome, tuple(trace.steps))
                        results.append(result)
                        journal.ended(result, _warning(source, result))
                        current = None
        except StopError:
            phases.step(_MARKING)
            _mark(source, scope, results)
            raise
        phases.step(_MARKING)
        if (refusal := _mark(source, scope, results)) is not None:
            raise StopError(messages.marks_not_saved(source, refusal))
        return tuple(results)

    results = phases.save(save)
    return PricingSummary(
        results,
        scope.with_photos,
        scope.defects,
        _warnings(source, results),
        phases.durations_ms(),
    )


def _mark(source: Path, scope: PricingScope, results: Sequence[OrderResult]) -> Refusal | None:
    """Znacznik efenix w ``ADRES`` każdego gotowego zlecenia z ``results``."""

    ready = [result.order.row for result in results if isinstance(result.outcome, Ready)]
    return mark_ready(source, scope.content, scope.address_column, ready)


def _warnings(source: Path, results: Sequence[OrderResult]) -> list[Message]:
    """Komunikat każdego zlecenia z błędem albo ostrzeżeniem Emmetta, po kolei."""

    return [warning for result in results if (warning := _warning(source, result)) is not None]


def _warning(source: Path, result: OrderResult) -> Message | None:
    match result.outcome:
        case Ready() | Settled():
            return None
        case OrderError(problem):
            return messages.order_error(source, result.order.row, problem)
        case EmmettWarning(excess):
            return messages.emmett_warning(source, result.order.row, excess)


@contextmanager
def _efenix_stops(
    changed: Callable[[WindowStop], bool], stopped: Callable[[PagePart | None, WindowCause], PricingStopped]
) -> Iterator[None]:
    """Strona logowania, niedokończone działanie okna, zamknięte okno i efenix, którego okno nie otworzyło, to Zatrzymanie
    z Komunikatem procesu, a fakty Zatrzymania dla Logów Uruchomienia daje ``stopped`` z częścią strony i przyczyną.

    ``changed``: czy przed Zatrzymaniem z wyjątku okna proces zmienił już coś w efenix.
    """

    try:
        yield
    except LoggedOut as error:
        raise StopError(messages.logged_out(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except UnexpectedPage as error:
        raise StopError(messages.window_stopped(error.part, kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except WindowClosed as error:
        raise StopError(messages.window_closed(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except EfenixUnreachable as error:
        raise StopError(messages.efenix_unreachable(kept=changed(error)), facts=stopped(error.part, error.cause)) from error
    except BrowserNotStarted as error:
        raise StopError(messages.browser_not_started(), facts=stopped(error.part, error.cause)) from error


def _kept(results: Sequence[OrderResult], current: OrderTrace | None, error: WindowStop) -> bool:
    """Czy przed Zatrzymaniem z wyjątku okna ``error`` proces mógł coś zmienić w efenix: udany zapis w śladzie zleceń
    ``results`` albo zlecenia ``current``, przy którym okno stanęło, albo działanie, które przed wyjątkiem kliknęło już
    przycisk zmiany zlecenia (``WindowStop.sent``)."""

    done = [step for result in results for step in result.steps]
    if current is not None:
        done.extend(current.steps)
    return error.sent or any(_wrote(step) for step in done)


def _wrote(step: TraceStep) -> bool:
    """Udane działanie okna ``step`` wysłało do efenix zmianę zlecenia: data wykonania, którą przyjął kalendarz (okno
    kliknęło „Potwierdź”), Wycena Emmetta i ilość."""

    match step.action:
        case "szukanie" | "otwarcie zlecenia":
            return False
        case "data wykonania":
            return step.accepted is True
        case "Wycena Emmetta" | "ilość":
            return True


def _outcome(order: CollectiveOrder, efenix: Efenix, forbidden: ForbiddenValues | None) -> Ready | Settled | OrderError | EmmettWarning:
    """Wynik zlecenia ``order`` w oknie ``efenix``: sprawdzenia, data wykonania z ``DATA``, gdy jest pusta, Wycena
    Emmetta przy stronie bez ilości i dokończenie do Pliku zbiorczego tylko w górę."""

    searched = searched_number(order)
    if isinstance(searched, OrderProblem):
        return OrderError(searched)
    number, day = searched
    file = file_quantities(order)
    if isinstance(file, (UnpairedColumns, NotWholeQuantities)):
        return OrderError(file)
    found = efenix.search(number)
    if forbidden is not None:
        for listed in found:
            forbidden.remember_value(ForbiddenColumn.ADDRESS, listed.address)
    hit = listing(order, found)
    if isinstance(hit, OrderProblem):
        return OrderError(hit)
    if isinstance(hit, Settled):
        return hit
    opened = efenix.open_order(hit)
    if (missing := missing_positions(file, opened.quantities, PageRead.OPENED)) is not None:
        return OrderError(missing)
    if (problem := date_problem(order, opened.execution_date)) is not None:
        return OrderError(problem)
    if opened.execution_date is None:
        dated = _dated(hit, efenix, file, day)
        if isinstance(dated, OrderError):
            return dated
        opened = dated
    if not _priced(opened):
        opened = efenix.load_emmett(_emmett)
        if (missing := missing_positions(file, opened.quantities, PageRead.AFTER_EMMETT)) is not None:
            return OrderError(missing)
    return _completed(order, hit, efenix, file, opened)


def _priced(page: OrderPricing) -> bool:
    """Strona zlecenia ma wycenę: co najmniej jedną ilość (ADR 0026). Proces ładuje Wycenę Emmetta tylko do strony bez
    wyceny, a strona po niej ma wycenę, gdy efenix ją załadował. Kwocie końcowej proces tu nie wierzy, bo karta ceny
    wpisywanej (pole ``.wycena-cena`` bez pola Ilość) daje kwotę różną od 0 także stronie bez ilości, a pozycja w cenie 0
    daje kwotę 0 stronie z ilością."""

    return any(page.quantities.values())


def _emmett(load: EmmettLoad) -> OrderPricing:
    """Strona zlecenia z Wyceną Emmetta, którą efenix załadował: strona po przeładowaniu ma wycenę (``_priced``) albo
    Emmett nic nie zaproponował (``Proposal.NOTHING``), bo proces ładuje Wycenę Emmetta tylko do strony bez wyceny.

    Strona bez ilości po każdej innej propozycji, także po pustym oknie Emmetta po padniętej propozycji, to
    ``UnexpectedPage`` z ``Shape.EMMETT_NOT_LOADED``: efenix odmówił „Załaduj do zlecenia” odpowiedzią 2xx (#877, #889), a
    skrypt efenix i tak przeładował stronę. Postaci propozycji ani treści tej odpowiedzi nikt nie zmierzył, więc werdykt ich
    nie czyta. Prawdziwy efenix dał stronę z ilością i kwotą różną od 0 po każdym ze 108 załadowań przebiegu z 4.11.2026
    (Logi Uruchomienia Wydania 0.4.2), więc Zatrzymanie przy pustej propozycji, którą efenix pokazałby czymś, zdarza się
    najwyżej rzadko.

    Emmett, który zaproponowałby same pozycje bez pola Ilość (karta ceny wpisywanej), dałby stronę bez ilości i
    Zatrzymanie, choć efenix go załadował. Takiej propozycji nikt nie zmierzył, a Zatrzymanie jest tu stroną bezpieczną, bo
    po nim proces nie wpisuje ilości z pliku. Każde następne Uruchomienie znowu otworzy jednak tę samą stronę bez ilości,
    znowu załaduje Emmetta i znowu zatrzyma się na tym zleceniu, dopóki tata sam nie wpisze ilości.
    """

    if load.proposal is not Proposal.NOTHING and not _priced(load.page):
        raise UnexpectedPage(PagePart.EMMETT, OtherShape(Shape.EMMETT_NOT_LOADED))
    return load.page


def _dated(hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], day: date) -> OrderPricing | OrderError:
    """Strona zlecenia ``hit`` z pustą datą wykonania po ustawieniu ``day``, otwarta ponownie, z ilościami albo bez.

    Dzień, którego kalendarz efenix nie przyjął albo którego efenix nie zapisał, to błąd ``DateRefused``, a ponownie
    otwarta strona bez pozycji z ilością w pliku to błąd ``missing_positions``; ilości proces wtedy nie zmienia."""

    if not efenix.set_execution_date(day):
        return OrderError(DateRefused.OUT_OF_RANGE)
    reopened = efenix.open_order(hit)
    if (missing := missing_positions(file, reopened.quantities, PageRead.AFTER_DATE)) is not None:
        return OrderError(missing)
    if reopened.execution_date != day:
        return OrderError(DateRefused.NOT_SAVED)
    return reopened


def _completed(
    order: CollectiveOrder, hit: ListedOrder, efenix: Efenix, file: Mapping[str, int], on_page: OrderPricing
) -> Ready | OrderError | EmmettWarning:
    """Ilości pliku wpisane w pozycjach, w których strona ``on_page`` ma mniej niż plik (``completion``); pozycja, w której
    ma więcej, to Ostrzeżenie Emmetta, a bez niej kwota końcowa porównana z ``Kwota`` (AU)."""

    plan = completion(file, on_page.quantities)
    amount = on_page.amount
    for position, quantity in plan.to_enter.items():
        amount = efenix.enter_quantity(position, quantity)
    if plan.excess:
        return EmmettWarning(plan.excess)
    return Ready(hit) if same_amount(amount, order.amount) else OrderError(OtherAmount(amount, order.amount))
