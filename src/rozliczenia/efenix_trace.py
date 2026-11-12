"""Ślad zlecenia Wyceny w efenix dla Logów Uruchomienia: każde działanie okna efenix z czasem i tym, co odpowiedział efenix.

Okno ``traced()`` przy jednym zleceniu Pliku zbiorczego przekazuje każde działanie oknu pod spodem i zapisuje je w
``OrderTrace`` z chwilą rozpoczęcia (UTC), więc przerwy tempa ludzkiego między działaniami widać bez symulacji. Każde
działanie niesie odczyt strony efenix po nim (#843, ``TraceStep``), bez numeru zlecenia i bez danych adresowych (reguła
danych, ADR 0025). Status i login realizatora przy otwarciu zlecenia pochodzą z wiersza listy, bo okno nie czyta ich ze
strony zlecenia, a Przekazanie do akceptacji niesie odmowę efenix z zamkniętej listy (``ForwardRefusal``, bez tekstu
okna informacji) albo sam rodzaj i czas (status po nim pokazuje następne szukanie). Działanie, które się nie udało
(wyjątek okna, np. ``UnexpectedPage``, także Zatrzymanie z werdyktu Wyceny o Wycenie Emmetta, który biegnie w działaniu
okna), nie trafia do udanych działań śladu, tylko do ``OrderTrace.failed`` z rodzajem i czasem do wyjątku, bo przebieg
kończy się wtedy Zatrzymaniem, a Logi Uruchomienia mówią, przy którym działaniu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TypeVar

from .efenix_checks import ListedRead, read_listed
from .efenix_orders import CollectiveOrder
from .efenix_window import Efenix, EmmettLoad, ForwardRefusal, ListedOrder, OrderPricing, WindowAction
from .wall_clock import utc_now

__all__ = ["OrderTrace", "TraceStep", "traced"]


@dataclass(frozen=True)
class TraceStep:
    """Jedno działanie okna efenix: rodzaj, chwila rozpoczęcia (UTC), czas w milisekundach i to, co efenix odpowiedział,
    bez danych klientów.

    ``found``: trafienia szukania, a ``results``: odczyt każdego z nich po kolei. ``status`` i ``realizator``: wiersz
    listy, którego stronę zlecenia okno otworzyło. ``execution_date``, ``amount`` i ``quantities``: strona zlecenia po
    otwarciu albo po Wycenie Emmetta, a ``amount`` także kwota końcowa po wpisaniu ilości. ``position`` i ``quantity``:
    pole „Ilość”, w które okno wpisało ilość. ``accepted``: kalendarz przyjął dzień daty wykonania. ``refusal``: efenix
    odmówił Przekazania do akceptacji, więc okno niczego nie wysłało.
    """

    action: WindowAction
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
    refusal: ForwardRefusal | None = None

    @property
    def sent(self) -> bool:
        """Działanie wysłało do efenix zmianę zlecenia (zob. ``WindowAction.writes``)."""

        return self.action.writes and self.accepted is not False and self.refusal is None


@dataclass
class OrderTrace:
    """Udane działania okna efenix przy jednym zleceniu, po kolei, i działanie, które się nie udało (``None``: żadne)."""

    steps: list[TraceStep] = field(default_factory=list)
    failed: TraceStep | None = None


_T = TypeVar("_T")


class _Traced:
    def __init__(
        self, efenix: Efenix, order: CollectiveOrder, trace: OrderTrace, clock: Callable[[], float], now: Callable[[], datetime]
    ) -> None:
        self._efenix = efenix
        self._order = order
        self._trace = trace
        self._clock = clock
        self._now = now

    def search(self, number: str) -> Sequence[ListedOrder]:
        found, at, duration_ms = self._done(WindowAction.SEARCH, lambda: self._efenix.search(number))
        results = tuple(read_listed(self._order, listed) for listed in found)
        self._add(TraceStep(WindowAction.SEARCH, at, duration_ms, found=len(found), results=results))
        return found

    def open_order(self, order: ListedOrder) -> OrderPricing:
        pricing, at, duration_ms = self._done(WindowAction.OPEN, lambda: self._efenix.open_order(order))
        self._add(replace(_page(WindowAction.OPEN, at, duration_ms, pricing), status=order.status, realizator=order.realizator))
        return pricing

    def set_execution_date(self, day: date) -> bool:
        accepted, at, duration_ms = self._done(WindowAction.DATE, lambda: self._efenix.set_execution_date(day))
        self._add(TraceStep(WindowAction.DATE, at, duration_ms, execution_date=day, accepted=accepted))
        return accepted

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        pricing, at, duration_ms = self._done(WindowAction.EMMETT, lambda: self._efenix.load_emmett(verdict))
        self._add(_page(WindowAction.EMMETT, at, duration_ms, pricing))
        return pricing

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        amount, at, duration_ms = self._done(WindowAction.QUANTITY, lambda: self._efenix.enter_quantity(position, quantity))
        self._add(TraceStep(WindowAction.QUANTITY, at, duration_ms, amount=amount, position=position, quantity=quantity))
        return amount

    def forward_to_accept(self) -> ForwardRefusal | None:
        refusal, at, duration_ms = self._done(WindowAction.FORWARD, self._efenix.forward_to_accept)
        self._add(TraceStep(WindowAction.FORWARD, at, duration_ms, refusal=refusal))
        return refusal

    def _done(self, action: WindowAction, act: Callable[[], _T]) -> tuple[_T, datetime, int]:
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


def _page(action: WindowAction, started_at: datetime, duration_ms: int, pricing: OrderPricing) -> TraceStep:
    return TraceStep(
        action,
        started_at,
        duration_ms,
        execution_date=pricing.execution_date,
        amount=pricing.amount,
        quantities=MappingProxyType(dict(pricing.quantities)),
    )


def traced(
    efenix: Efenix,
    order: CollectiveOrder,
    trace: OrderTrace,
    clock: Callable[[], float],
    now: Callable[[], datetime] = utc_now,
) -> Efenix:
    """Okno ``efenix`` przy zleceniu ``order`` Pliku zbiorczego, które zapisuje w ``trace`` każde swoje udane działanie z
    odczytem strony, czasem z ``clock`` (sekundy) i chwilą rozpoczęcia z ``now`` (UTC)."""

    return _Traced(efenix, order, trace, clock, now)
