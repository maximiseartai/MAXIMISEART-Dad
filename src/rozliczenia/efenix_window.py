"""Okno efenix jako seam Wyceny w efenix: protokół okna (``Efenix``), to, co okno czyta ze stron efenix, i jego
Zatrzymania z przyczyną techniczną z zamkniętej listy.

Jedyna zmiana statusu zlecenia, którą zna okno, to Przekazanie do akceptacji (``Efenix.forward_to_accept``): status
``ACCEPTANCE_STATUS``. Żądanie zmiany statusu, którego okno nie wysłało w tym działaniu, albo na inny status okno
przerywa, zanim dojdzie do efenix (``StatusChangeBlocked``).

Moduł to sam słownik okna, bez decyzji Wyceny i bez przeglądarki: tylko biblioteka standardowa. Implementują go okno w
przeglądarce (``efenix_browser`` z odczytami ``efenix_page``), okno z tempem ludzkim (``efenix_pace``), okno ze śladem
dla Logów Uruchomienia (``efenix_trace``) i okno w procesie testów (``tests/fixtures/okno_w_procesie.py``). Silnik
(``efenix_pricing``) woła okno przez ``Efenix`` i tłumaczy jego wyjątki na Zatrzymania z Komunikatem, a przyczynę
(``WindowCause``) niesie do Logów Uruchomienia (``centrum.run_logs``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import enum
from typing import Final, Protocol

ACCEPTANCE_STATUS: Final = "Do akceptacji"
"""Status zlecenia efenix po Przekazaniu do akceptacji: jedyny, na który okno może zmienić status zlecenia."""

__all__ = [
    "ACCEPTANCE_STATUS",
    "BrowserFailure",
    "BrowserNotStarted",
    "Closed",
    "Efenix",
    "EfenixUnreachable",
    "ElementCount",
    "EmmettLoad",
    "HttpStatus",
    "ListedOrder",
    "LoggedOut",
    "Login",
    "LoginSign",
    "OpenEfenix",
    "Operation",
    "OrderPricing",
    "OtherShape",
    "PageCause",
    "PagePart",
    "Proposal",
    "SentChanges",
    "Shape",
    "StatusChangeBlocked",
    "UnexpectedPage",
    "WindowAction",
    "WindowCause",
    "WindowClosed",
    "WindowStop",
]


class PagePart(enum.Enum):
    """Część strony efenix, którą czyta okno; jej nazwa trafia do Komunikatu zmienionej strony efenix."""

    LIST = "lista zleceń z polem Numer"
    RESULTS = "tabela wyników szukania"
    ORDER = "strona zlecenia z datą wykonania i wyceną"
    DATE = "okno daty wykonania"
    EMMETT = "Wycena Emmetta"
    QUANTITY = "pole Ilość i kwota końcowa"
    FORWARD = "okno Przekazania do akceptacji"


@dataclass(frozen=True)
class ListedOrder:
    """Wiersz listy zleceń efenix po szukaniu: ``Numer dokumentu``, status, realizator (login, ``None`` bez niego),
    ``Dane adresowe`` bez linii województwa i identyfikator, którym otwiera się stronę zlecenia."""

    number: str
    status: str
    realizator: str | None
    address: str
    order_id: str


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
    STATUS_NOT_ANSWERED = "żądanie Przekazania do akceptacji bez odpowiedzi efenix (zerwane połączenie)"
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


class StatusChangeBlocked(enum.Enum):
    """Żądanie zmiany statusu zlecenia (``action_change_status.php``), które okno przerwało, zanim doszło do efenix: pomyłka
    anulowałaby zlecenie, czego nie da się cofnąć, więc to Zatrzymanie do Maksa, a nie błąd zlecenia."""

    OTHER_STATUS = "żądanie zmiany statusu na inny niż „Do akceptacji” w Przekazaniu do akceptacji"
    OUTSIDE_FORWARD = "żądanie zmiany statusu poza Przekazaniem do akceptacji (także w trybie bez Przekazania)"
    OTHER_ORDER = "żądanie Przekazania do akceptacji innego zlecenia niż otwarte w oknie"


PageCause = ElementCount | HttpStatus | OtherShape | BrowserFailure | StatusChangeBlocked
"""Przyczyna niedokończonego działania okna (``UnexpectedPage``)."""
WindowCause = PageCause | LoginSign | Closed
"""Przyczyna techniczna Zatrzymania okna efenix z zamkniętej listy, dla Logów Uruchomienia, bez treści strony i danych
zleceń; Komunikat taty jej nie pokazuje."""


class WindowStop(Exception):
    """Okno efenix nie może działać dalej: część strony (``None`` poza stronami efenix) i przyczyna techniczna.

    ``sent``: działanie okna, które zgłosiło wyjątek, kliknęło już przycisk, który wysyła do efenix zmianę zlecenia (data
    wykonania, „Załaduj do zlecenia”, Enter w polu „Ilość”, „Tak” Przekazania do akceptacji), więc efenix mógł ją
    zapisać. Ustawia je ``SentChanges.action`` okna.
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


class SentChanges:
    """Przyciski zmiany zlecenia, które okno kliknęło: każde okno woła ``send`` przy takim kliknięciu, a swoje działania
    obejmuje ``action``, więc wyjątek okna z działania niesie ``WindowStop.sent``."""

    def __init__(self) -> None:
        self._sent = 0

    def send(self) -> None:
        """Okno klika przycisk, który wysyła do efenix zmianę zlecenia."""

        self._sent += 1

    @contextmanager
    def action(self) -> Iterator[None]:
        """Działanie okna: wyjątek okna z niego ma ``sent``, gdy w nim okno kliknęło przycisk zmiany zlecenia, także w
        działaniu, które woła inne działanie okna."""

        before = self._sent
        try:
            yield
        except WindowStop as stop:
            stop.sent = self._sent > before
            raise


class WindowAction(enum.Enum):
    """Działanie okna efenix (metoda ``Efenix``). Wartość to klucz działania w śladzie zlecenia w Logach Uruchomienia na
    dysku taty: czytają go stare Logi i narzędzia odtwarzania, więc się nie zmienia."""

    SEARCH = "szukanie"
    OPEN = "otwarcie zlecenia"
    DATE = "data wykonania"
    EMMETT = "Wycena Emmetta"
    QUANTITY = "ilość"
    FORWARD = "przekazanie do akceptacji"

    @property
    def writes(self) -> bool:
        """Działanie wysyła do efenix zmianę zlecenia (data wykonania tylko wtedy, gdy kalendarz przyjął dzień): przed
        nim tempo ludzkie robi przerwę (ADR 0024), a po nim Komunikat nie mówi, że w efenix nic się nie zmieniło."""

        match self:
            case WindowAction.SEARCH | WindowAction.OPEN:
                return False
            case WindowAction.DATE | WindowAction.EMMETT | WindowAction.QUANTITY | WindowAction.FORWARD:
                return True


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
    Emmetta, rozstrzyga z nich Wycena (``efenix_pricing._emmett``), a nie okno."""

    proposal: Proposal
    page: OrderPricing


class Efenix(Protocol):
    """Okno efenix w sesji taty z listą dozwolonych działań: szukanie, otwarcie zlecenia, data wykonania, Wycena Emmetta,
    pola „Ilość” i Przekazanie do akceptacji. Anulowania ani innej zmiany statusu zlecenia w nim nie ma.

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

    def forward_to_accept(self) -> None:
        """Przekazuje otwarte zlecenie do akceptacji (zielony „Zapisz” i „Tak” w jego oknie) i czeka na odpowiedź efenix.

        Czy efenix zmienił status, okno nie rozstrzyga: pokazuje to dopiero lista zleceń po ponownym szukaniu. Żądanie
        zmiany statusu na inny status albo poza tym działaniem okno przerywa przed wysłaniem (``UnexpectedPage`` z
        ``StatusChangeBlocked``).
        """
        ...


Login = Callable[[], AbstractContextManager[None]]
"""Czas, w którym okno czeka, aż tata zaloguje się w efenix; silnik nie liczy go do czasów Uruchomienia."""

OpenEfenix = Callable[[Login], AbstractContextManager[Efenix]]
"""Otwiera okno efenix z listą zleceń na czas Zapisywania, a czekanie na logowanie taty robi w ``Login``;
``BrowserNotStarted``, ``EfenixUnreachable``, ``LoggedOut``, ``UnexpectedPage`` albo ``WindowClosed``."""

