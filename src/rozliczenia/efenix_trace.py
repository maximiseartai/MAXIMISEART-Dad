"""Ślad zlecenia Wyceny w efenix dla Logów Uruchomienia: każde działanie okna efenix z czasem i tym, co odpowiedział efenix.

Jedyną operacją jest ``traced()``: okno efenix (``efenix_pricing.Efenix``) przy jednym zleceniu Pliku zbiorczego, które
przekazuje każde działanie oknu pod spodem i zapisuje je w ``OrderTrace`` z chwilą rozpoczęcia (UTC), więc przerwy tempa
ludzkiego między działaniami widać bez symulacji. Każde działanie niesie odczyt strony efenix po nim (#843), bez numeru
zlecenia i bez danych adresowych (reguła danych, ADR 0025): z szukania liczbę trafień i każdy wiersz listy
(``efenix_checks.ListedRead``: czy ``Numer dokumentu`` to ``NUMER ZL.`` z pliku, status, login realizatora i nazwy
części adresu, którymi ``Dane adresowe`` różnią się od ``ADRES``), z otwarcia zlecenia status i login realizatora wiersza
listy, który okno otworzyło (okno nie czyta ich ze strony zlecenia), oraz ze strony zlecenia po otwarciu i po Wycenie
Emmetta datę wykonania, kwotę i ilości wszystkich pozycji po kodach, z daty wykonania wybrany dzień i to, czy kalendarz
go przyjął, a z pola „Ilość” kod pozycji, wpisaną ilość i kwotę końcową, którą odesłał efenix. Działanie, które się nie udało (wyjątek okna, np.
``UnexpectedPage``, także Zatrzymanie z werdyktu Wyceny o Wycenie Emmetta, który biegnie w działaniu okna), nie trafia do udanych działań śladu, tylko do ``OrderTrace.failed`` z rodzajem i czasem do
wyjątku, bo przebieg kończy się wtedy Zatrzymaniem, a Logi Uruchomienia mówią, przy którym działaniu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeVar

from .efenix_checks import ListedRead, read_listed

if TYPE_CHECKING:
    from .efenix_checks import ListedOrder
    from .efenix_orders import CollectiveOrder
    from .efenix_pricing import Efenix, EmmettLoad, OrderPricing

__all__ = ["Action", "OrderTrace", "TraceStep", "traced"]

Action = Literal["szukanie", "otwarcie zlecenia", "data wykonania", "Wycena Emmetta", "ilość"]


@dataclass(frozen=True)
class TraceStep:
    """Jedno działanie okna efenix: rodzaj, chwila rozpoczęcia (UTC), czas w milisekundach i to, co efenix odpowiedział,
    bez danych klientów.

    ``found``: trafienia szukania, a ``results``: odczyt każdego z nich po kolei. ``status`` i ``realizator``: wiersz
    listy, którego stronę zlecenia okno otworzyło. ``execution_date``, ``amount`` i ``quantities``: strona zlecenia po
    otwarciu albo po Wycenie Emmetta, a ``amount`` także kwota końcowa po wpisaniu ilości. ``position`` i ``quantity``:
    pole „Ilość”, w które okno wpisało ilość. ``accepted``: kalendarz przyjął dzień daty wykonania.
    """

    action: Action
    started_at: datetime
    duration_ms: int
    found: int | None = None
    execution_date: date | None = None
    amount: Decimal | None = None
    quantities: Mapping[str, int] | None = None
    position: str | None = None
    quantity: int | None = None
    accepted: bool | None = None
    results: tuple[ListedRead, ...] | None = None
    status: str | None = None
    realizator: str | None = None


@dataclass
class OrderTrace:
    """Udane działania okna efenix przy jednym zleceniu, po kolei, i działanie, które się nie udało (``None``: żadne)."""

    steps: list[TraceStep] = field(default_factory=list)
    failed: TraceStep | None = None


_T = TypeVar("_T")


class _Traced:
    """Okno efenix przy zleceniu ``order``, które zapisuje każde udane działanie okna ``efenix`` w ``trace`` z czasem z
    zegara ``clock`` i chwilą rozpoczęcia z zegara ściennego ``now``."""

    def __init__(
        self, efenix: Efenix, order: CollectiveOrder, trace: OrderTrace, clock: Callable[[], float], now: Callable[[], datetime]
    ) -> None:
        self._efenix = efenix
        self._order = order
        self._trace = trace
        self._clock = clock
        self._now = now

    def search(self, number: str) -> Sequence[ListedOrder]:
        found, at, duration_ms = self._done("szukanie", lambda: self._efenix.search(number))
        results = tuple(read_listed(self._order, listed) for listed in found)
        self._add(TraceStep("szukanie", at, duration_ms, found=len(found), results=results))
        return found

    def open_order(self, order: ListedOrder) -> OrderPricing:
        pricing, at, duration_ms = self._done("otwarcie zlecenia", lambda: self._efenix.open_order(order))
        self._add(replace(_page("otwarcie zlecenia", at, duration_ms, pricing), status=order.status, realizator=order.realizator))
        return pricing

    def set_execution_date(self, day: date) -> bool:
        accepted, at, duration_ms = self._done("data wykonania", lambda: self._efenix.set_execution_date(day))
        self._add(TraceStep("data wykonania", at, duration_ms, execution_date=day, accepted=accepted))
        return accepted

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        pricing, at, duration_ms = self._done("Wycena Emmetta", lambda: self._efenix.load_emmett(verdict))
        self._add(_page("Wycena Emmetta", at, duration_ms, pricing))
        return pricing

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        amount, at, duration_ms = self._done("ilość", lambda: self._efenix.enter_quantity(position, quantity))
        self._add(TraceStep("ilość", at, duration_ms, amount=amount, position=position, quantity=quantity))
        return amount

    def _done(self, action: Action, act: Callable[[], _T]) -> tuple[_T, datetime, int]:
        """Wynik działania ``act``, chwila jego rozpoczęcia i czas; działanie, które zgłosiło wyjątek, trafia do
        ``OrderTrace.failed``."""

        at = self._now()
        started = self._clock()
        try:
            value = act()
        except Exception:
            self._trace.failed = TraceStep(action, at, self._since(started))
            raise
        return value, at, self._since(started)

    def _since(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))

    def _add(self, step: TraceStep) -> None:
        self._trace.steps.append(step)


def _page(action: Action, started_at: datetime, duration_ms: int, pricing: OrderPricing) -> TraceStep:
    return TraceStep(
        action,
        started_at,
        duration_ms,
        execution_date=pricing.execution_date,
        amount=pricing.amount,
        quantities=MappingProxyType(dict(pricing.quantities)),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def traced(
    efenix: Efenix,
    order: CollectiveOrder,
    trace: OrderTrace,
    clock: Callable[[], float],
    now: Callable[[], datetime] = _utc_now,
) -> Efenix:
    """Okno ``efenix`` przy zleceniu ``order`` Pliku zbiorczego, które zapisuje w ``trace`` każde swoje udane działanie z
    odczytem strony, czasem z ``clock`` (sekundy) i chwilą rozpoczęcia z ``now`` (UTC)."""

    return _Traced(efenix, order, trace, clock, now)
