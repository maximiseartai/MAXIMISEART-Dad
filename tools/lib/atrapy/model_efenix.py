"""Model efenix: zlecenia, sesja i decyzje serwera efenix, bez HTTP, stron i przeglądarki.

Model trzyma to, co w efenix trzyma serwer: zlecenia z wyceną, datą wykonania, statusem i propozycją Emmetta, jedną
sesję i decyzje serwera o każdym działaniu okna (``Action``): szukanie, strona zlecenia, zapis daty wykonania,
propozycja Emmetta, „Załaduj do zlecenia” z odmowami, zapis ilości i zmiana statusu. HTTP i strony gra nad nim
Atrapa efenix (``tools/lib/atrapy/atrapa_efenix.py``). Test widzi stan po przebiegu przez ``StanEfenix``.

Moduł importuje tylko bibliotekę standardową (``tests/test_granice_importow.py``), więc model, z którym test porównuje
Wycenę w efenix, nie bierze niczego z kodu pod testem (``src``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
import enum
import threading
from typing import Final, Generic, TypeVar

TODAY: Final = date(2026, 10, 12)
"""Dzień, który kalendarz efenix ma za dzisiejszy, gdy test nie poda innego: dni z ``DATA`` testów (wrzesień 2026) są
w zakresie, który przyjmuje efenix."""


def earliest_execution_date(today: date) -> date:
    """Pierwszy dzień poprzedniego miesiąca: najwcześniejsza data wykonania, którą przyjmuje kalendarz efenix."""

    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def calendar_day(today: date, day: date) -> date:
    """Dzień, który kalendarz efenix zostawia w polu po wyborze ``day``: ``day`` od ``earliest_execution_date`` do
    ``today`` włącznie, a każdy inny dzień kalendarz zamienia na ``today``. Skrypt strony Atrapy efenix dostaje te same
    granice (``earliest_execution_date`` i ``today``)."""

    return day if earliest_execution_date(today) <= day <= today else today


@dataclass(frozen=True)
class Position:
    """Pozycja wyceny: kod ``NNN``, wymyślona cena i rodzaj pola (``ILOSC`` albo ``CENA``)."""

    code: str
    price: Decimal
    kind: str = "ILOSC"


# Kody pozycji stron efenix (z przypisania kolumn Wyceny w efenix i bez niego); ceny są wymyślone, bo ceny efenix to
# ceny umowy taty z firmą.
CATALOG: Final = (
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
PRICES: Final = {position.code: position.price for position in CATALOG}


def amount_of(quantities: Mapping[str, int], prices: Mapping[str, Decimal] = PRICES) -> Decimal:
    """Kwota końcowa wyceny z ilościami ``quantities`` (kod → ilość) w cenach ``prices`` (domyślnie cenach Atrapy)."""

    return sum((prices[code] * quantity for code, quantity in quantities.items()), Decimal("0.00"))


class Action(enum.Enum):
    """Działanie serwera efenix, które okno wysyła za narzędzie; ``expire_after`` i ``StanEfenix.count`` je liczą."""

    SEARCH = "szukanie zleceń po numerze z pola Numer"
    OPEN = "strona zlecenia"
    DATE = "zapis daty wykonania"
    PROPOSAL = "propozycja Emmetta"
    EMMETT = "„Załaduj do zlecenia” Wyceny Emmetta"
    QUANTITY = "zapis ilości pozycji"
    STATUS = "zmiana statusu zlecenia"


class NoSession(enum.Enum):
    """Działanie bez sesji efenix: serwer go nie wykonał."""

    NO_SESSION = "brak sesji"


class NoOrder(enum.Enum):
    """Działanie na zleceniu, którego identyfikatora efenix nie zna: serwer go nie wykonał."""

    NO_ORDER = "brak zlecenia"


class ProposalFailure(enum.Enum):
    """Jak pada propozycja Emmetta zlecenia (``EfenixOrder.emmett_proposal_failure``); skrypt strony i tak pokazuje
    okno Emmetta, puste, jak skrypt efenix."""

    SERVER_ERROR = "HTTP 500 bez propozycji"
    TORN = "odpowiedź z propozycją zerwana w połowie treści"
    CUT = "połączenie zerwane bez odpowiedzi"


class EmmettRefusal(enum.Enum):
    """Jak efenix odmawia „Załaduj do zlecenia” zlecenia (``EfenixOrder.emmett_refusal``); skrypt strony i tak ją
    przeładowuje, bo czeka tylko na koniec odpowiedzi, a nie na jej status."""

    FORBIDDEN = "HTTP 403 bez załadowania Wyceny Emmetta"
    SERVER_ERROR = "HTTP 500 po załadowaniu Wyceny Emmetta"
    ELSEWHERE = "przekierowanie na listę zleceń bez załadowania Wyceny Emmetta"
    LOGGED_OUT = "sesja wygasa przy tym żądaniu: przekierowanie na stronę logowania bez załadowania Wyceny Emmetta"
    NOK = "200 z JSON result: nok bez załadowania Wyceny Emmetta"
    OTHER = "200 z inną treścią (strona HTML) bez załadowania Wyceny Emmetta"


@dataclass
class EfenixOrder:
    """Wymyślone zlecenie efenix w tym, co trzyma serwer i co pokazują lista i strona zlecenia.

    ``quantities``: ilości wyceny (kod → ilość różna od 0), ``emmett``: propozycja Emmetta w tym samym kształcie,
    ``emmett_loads``: ile razy załadowano do zlecenia Wycenę Emmetta, a ``emmett_over_pricing``: ile z tych razy
    zlecenie miało w chwili żądania wycenę inną niż ta Wycena Emmetta, którą „Załaduj do zlecenia” zastąpił (wycenę taty
    albo ilości wpisane przez proces). ``without``: kody pozycji, których karty strona tego zlecenia nie ma, jak strony
    efenix z częścią pozycji wyceny; z ``after_date`` strona jest zmieniona (``page_changed``) dopiero od zapisu daty
    wykonania, a z ``after_emmett`` od Wyceny Emmetta. ``emmett_refusal``: efenix odmawia „Załaduj do zlecenia” tego
    zlecenia (``EmmettRefusal``), aż test to zmieni. ``emmett_proposal_failure``: propozycja Emmetta tego zlecenia pada
    (``ProposalFailure``), więc okno Emmetta zostaje puste. ``keeps_status``: efenix odpowiada na zmianę statusu tego
    zlecenia jak zwykle, ale statusu nie zmienia. ``forward_refusal``: tekst, którym skrypt strony tego zlecenia po
    przycisku Przekazania do akceptacji odmawia go w oknie informacji, zamiast pokazać okno zmiany statusu (efenix
    sprawdza tak zdjęcia, długość przyłącza, wycenę i datę wykonania), więc zmiana statusu nie dochodzi do serwera.
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
    emmett_over_pricing: int = 0
    without: frozenset[str] = frozenset()
    after_date: bool = False
    after_emmett: bool = False
    emmett_refusal: EmmettRefusal | None = None
    emmett_proposal_failure: ProposalFailure | None = None
    keeps_status: bool = False
    forward_refusal: str | None = None

    @property
    def amount(self) -> Decimal:
        return amount_of(self.quantities)

    @property
    def page_changed(self) -> bool:
        if self.after_emmett:
            return self.emmett_loads > 0
        return not self.after_date or self.execution_date is not None

    @property
    def positions(self) -> tuple[Position, ...]:
        """Pozycje ``CATALOG``, których karty ma strona zlecenia."""

        return tuple(position for position in CATALOG if not (position.code in self.without and self.page_changed))


@dataclass(frozen=True)
class Saved:
    """Zapisana ilość: wartość pozycji i kwota końcowa zlecenia po zapisie, w cenach ``StanEfenix``."""

    price: Decimal
    amount: Decimal


OrderT = TypeVar("OrderT", bound=EfenixOrder)


@dataclass
class _State(Generic[OrderT]):
    """Stan efenix, który dzielą twarz testu (``StanEfenix``) i twarz okna (``SerwerEfenix``), pod jedną blokadą."""

    orders: list[OrderT]
    refuse_dates: bool
    prices: Mapping[str, Decimal]
    expire_after: tuple[Action, int] | None
    logged_in: bool = True
    expired: bool = False
    counts: Counter[Action] = field(default_factory=Counter)
    searched: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def session_after(self, action: Action | None) -> bool:
        """Liczy działanie ``action`` (``None``: działanie, którego ``expire_after`` nie liczy) i mówi, czy sesja trwa
        po nim; sesja wygasa raz, przy pierwszym działaniu ponad liczbę z ``expire_after``."""

        if action is None:
            return self.logged_in
        self.counts[action] += 1
        if self.expire_after is not None and not self.expired and self.counts[action] > self.expire_after[1] and action is self.expire_after[0]:
            self.logged_in = False
            self.expired = True
        return self.logged_in

    def order(self, order_id: str) -> OrderT | NoOrder:
        return next((order for order in self.orders if order.order_id == order_id), NoOrder.NO_ORDER)


class StanEfenix(Generic[OrderT]):
    """Twarz testu: stan efenix po przebiegu, zmiany taty, sesja i liczby działań okna; ``serwer`` to twarz okna.

    Model pracuje na kopii ``orders``, więc zlecenia testu zostają bez zmian także wtedy, gdy działanie zmieni ich stan
    w efenix. ``today``: dzisiejszy dzień kalendarza daty wykonania. ``refuse_dates``: serwer odpowiada na zapis daty
    wykonania bez zapisu. ``prices``: cena każdej pozycji ``CATALOG`` po kodzie, domyślnie ceny Atrapy (``PRICES``).
    ``expire_after``: działanie i liczba jego wykonań, po których sesja wygasa raz, jak przy wylogowaniu w trakcie
    przebiegu; po ponownym zalogowaniu już nie wygasa.
    """

    def __init__(
        self,
        orders: Sequence[OrderT],
        *,
        today: date = TODAY,
        refuse_dates: bool = False,
        prices: Mapping[str, Decimal] = PRICES,
        expire_after: tuple[Action, int] | None = None,
    ) -> None:
        self.today = today
        self.prices = prices
        self._state = _State(copy.deepcopy(list(orders)), refuse_dates, prices, expire_after)
        self.serwer: SerwerEfenix[OrderT] = SerwerEfenix(self._state)

    @property
    def logged_in(self) -> bool:
        with self._state.lock:
            return self._state.logged_in

    def expire_session(self) -> None:
        with self._state.lock:
            self._state.logged_in = False

    def log_in(self) -> None:
        """Tata zalogował się w efenix (w tej samej sesji, w której pracuje okno narzędzia)."""

        with self._state.lock:
            self._state.logged_in = True

    def edit(self, number: str, change: Callable[[OrderT], object]) -> None:
        """Tata sam zmienia w efenix zlecenie ``number``: ``change`` dostaje jego stan w efenix."""

        with self._state.lock:
            [order] = [order for order in self._state.orders if order.number == number]
            change(order)

    def state(self) -> tuple[list[OrderT], bool]:
        """Kopia zleceń i sesji do porównania stanu przed przebiegiem i po nim."""

        with self._state.lock:
            return copy.deepcopy(self._state.orders), self._state.logged_in

    def count(self, action: Action) -> int:
        """Ile razy okno wysłało działanie ``action``, także bez sesji (szukanie, które lista wysyła sama, się nie liczy)."""

        with self._state.lock:
            return self._state.counts[action]

    def searched(self) -> list[str]:
        """Numery z każdego szukania okna po kolei, także bez sesji, jak ``count(Action.SEARCH)``."""

        with self._state.lock:
            return list(self._state.searched)


class SerwerEfenix(Generic[OrderT]):
    """Twarz okna: decyzje serwera efenix. Każde działanie najpierw liczy się w ``expire_after``, potem sprawdza sesję,
    a bez niej nic nie zmienia; zlecenia oddaje jako kopie."""

    def __init__(self, state: _State[OrderT]) -> None:
        self._state = state

    def search(self, number: str, *, own: bool = True) -> tuple[OrderT, ...] | NoSession:
        """Zlecenia, których numer zawiera ``number``; ``own=False``: szukanie, które lista wysyła sama, bez liczenia."""

        with self._state.lock:
            if own:
                self._state.searched.append(number)
            if not self._state.session_after(Action.SEARCH if own else None):
                return NoSession.NO_SESSION
            return tuple(copy.deepcopy(order) for order in self._state.orders if number in order.number)

    def page(self, order_id: str) -> OrderT | NoOrder | NoSession:
        with self._state.lock:
            if not self._state.session_after(Action.OPEN):
                return NoSession.NO_SESSION
            return copy.deepcopy(self._state.order(order_id))

    def set_date(self, order_id: str, day: str) -> bool | NoOrder | NoSession:
        """Zapis daty wykonania ``day`` w zapisie RRRR-MM-DD, jak wysyła ją strona; ``False``: odpowiedź bez zapisu
        (``refuse_dates``). Dzień serwer czyta dopiero po sesji, zleceniu i ``refuse_dates``, więc na te trzy odpowiada
        także przy dniu, którego nie przeczyta (``ValueError``)."""

        with self._state.lock:
            if not self._state.session_after(Action.DATE):
                return NoSession.NO_SESSION
            order = self._state.order(order_id)
            if isinstance(order, NoOrder):
                return order
            if self._state.refuse_dates:
                return False
            order.execution_date = date.fromisoformat(day)
            return True

    def proposal(self, order_id: str) -> OrderT | NoOrder | NoSession:
        """Zlecenie, którego propozycję Emmetta (``emmett``) okno chce zobaczyć; czy pada, mówi ``emmett_proposal_failure``."""

        with self._state.lock:
            if not self._state.session_after(Action.PROPOSAL):
                return NoSession.NO_SESSION
            return copy.deepcopy(self._state.order(order_id))

    def load_emmett(self, order_id: str) -> EmmettRefusal | None | NoOrder | NoSession:
        """„Załaduj do zlecenia”: wycena zlecenia staje się propozycją Emmetta, a ``None`` mówi, że bez odmowy.

        Odmowa ``SERVER_ERROR`` przychodzi już po załadowaniu, ``LOGGED_OUT`` kończy sesję, a inna odmowa nic nie zmienia.
        Załadowanie na wycenę inną niż propozycja liczy ``emmett_over_pricing``.
        """

        with self._state.lock:
            if not self._state.session_after(Action.EMMETT):
                return NoSession.NO_SESSION
            order = self._state.order(order_id)
            if isinstance(order, NoOrder):
                return order
            refusal = order.emmett_refusal
            if refusal is EmmettRefusal.LOGGED_OUT:
                self._state.logged_in = False
            if refusal in (None, EmmettRefusal.SERVER_ERROR):
                if order.quantities and order.quantities != order.emmett:
                    order.emmett_over_pricing += 1
                order.quantities = dict(order.emmett)
                order.emmett_loads += 1
            return refusal

    def save_quantity(self, order_id: str, code: str, quantity: int | None) -> Saved | None | NoOrder | NoSession:
        """Zapis ilości ``quantity`` pozycji ``code`` (0 usuwa pozycję z wyceny); ``None``: odmowa, bo kod jest spoza
        ``CATALOG`` albo ilość nie jest liczbą całkowitą (``quantity=None``)."""

        with self._state.lock:
            if not self._state.session_after(Action.QUANTITY):
                return NoSession.NO_SESSION
            order = self._state.order(order_id)
            if isinstance(order, NoOrder):
                return order
            if code not in PRICES or quantity is None:
                return None
            if quantity:
                order.quantities[code] = quantity
            else:
                order.quantities.pop(code, None)
            return Saved(self._state.prices[code] * quantity, amount_of(order.quantities, self._state.prices))

    def date_of(self, order_id: str) -> date | None | NoOrder | NoSession:
        """Zapisana data wykonania zlecenia (``None``: bez daty); okno jej nie czyta, więc ``expire_after`` jej nie liczy."""

        with self._state.lock:
            if not self._state.session_after(None):
                return NoSession.NO_SESSION
            order = self._state.order(order_id)
            return order if isinstance(order, NoOrder) else order.execution_date

    def change_status(self, order_id: str, status: str) -> NoOrder | NoSession | None:
        """Zmiana statusu zlecenia na ``status`` (Przekazanie do akceptacji, anulowanie); zlecenie z ``keeps_status``
        zostaje przy swoim statusie."""

        with self._state.lock:
            if not self._state.session_after(Action.STATUS):
                return NoSession.NO_SESSION
            order = self._state.order(order_id)
            if isinstance(order, NoOrder):
                return order
            if not order.keeps_status:
                order.status = status
            return None
