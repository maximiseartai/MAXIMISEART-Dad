"""Ślad zlecenia Wyceny w efenix dla Logów Uruchomienia: każde działanie okna efenix z czasem i tym, co odpowiedział efenix.

Jedyną operacją jest ``traced()``: okno efenix (``efenix_pricing.Efenix``), które przekazuje każde działanie oknu pod
spodem i zapisuje je w ``OrderTrace``. Ślad nie ma numeru zlecenia, adresu, loginu realizatora ani treści stron efenix:
z szukania tylko liczbę trafień, ze strony zlecenia datę wykonania, kwotę i ilości po kodach pozycji, z pola „Ilość” kod
pozycji, wpisaną ilość i kwotę końcową, którą odesłał efenix. Działanie, które się nie udało (``LoggedOut``,
``UnexpectedPage``), nie trafia do śladu, bo przebieg kończy się wtedy Zatrzymaniem.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .efenix_checks import ListedOrder
    from .efenix_pricing import Efenix, OrderPricing

__all__ = ["Action", "OrderTrace", "TraceStep", "traced"]

Action = Literal["szukanie", "otwarcie zlecenia", "data wykonania", "Wycena Emmetta", "ilość"]


@dataclass(frozen=True)
class TraceStep:
    """Jedno działanie okna efenix: rodzaj, czas w milisekundach i to, co efenix odpowiedział, bez danych klientów.

    ``found``: trafienia szukania. ``execution_date``, ``amount`` i ``quantities``: strona zlecenia po otwarciu albo po
    Wycenie Emmetta, a ``amount`` także kwota końcowa po wpisaniu ilości. ``position`` i ``quantity``: pole „Ilość”, w które
    okno wpisało ilość. ``accepted``: kalendarz przyjął dzień daty wykonania.
    """

    action: Action
    duration_ms: int
    found: int | None = None
    execution_date: date | None = None
    amount: Decimal | None = None
    quantities: Mapping[str, int] | None = None
    position: str | None = None
    quantity: int | None = None
    accepted: bool | None = None


@dataclass
class OrderTrace:
    """Działania okna efenix przy jednym zleceniu, po kolei."""

    steps: list[TraceStep] = field(default_factory=list)


class _Traced:
    """Okno efenix, które zapisuje każde udane działanie okna ``efenix`` w ``trace`` z czasem z zegara ``clock``."""

    def __init__(self, efenix: Efenix, trace: OrderTrace, clock: Callable[[], float]) -> None:
        self._efenix = efenix
        self._trace = trace
        self._clock = clock

    @property
    def sent_change(self) -> bool:
        return self._efenix.sent_change

    def search(self, number: str) -> Sequence[ListedOrder]:
        started = self._clock()
        found = self._efenix.search(number)
        self._add(TraceStep("szukanie", self._since(started), found=len(found)))
        return found

    def open_order(self, order: ListedOrder) -> OrderPricing:
        started = self._clock()
        pricing = self._efenix.open_order(order)
        self._add(self._page("otwarcie zlecenia", started, pricing))
        return pricing

    def set_execution_date(self, day: date) -> bool:
        started = self._clock()
        accepted = self._efenix.set_execution_date(day)
        self._add(TraceStep("data wykonania", self._since(started), execution_date=day, accepted=accepted))
        return accepted

    def load_emmett(self) -> OrderPricing:
        started = self._clock()
        pricing = self._efenix.load_emmett()
        self._add(self._page("Wycena Emmetta", started, pricing))
        return pricing

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        started = self._clock()
        amount = self._efenix.enter_quantity(position, quantity)
        self._add(TraceStep("ilość", self._since(started), amount=amount, position=position, quantity=quantity))
        return amount

    def _page(self, action: Action, started: float, pricing: OrderPricing) -> TraceStep:
        return TraceStep(
            action,
            self._since(started),
            execution_date=pricing.execution_date,
            amount=pricing.amount,
            quantities=MappingProxyType(dict(pricing.quantities)),
        )

    def _since(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))

    def _add(self, step: TraceStep) -> None:
        self._trace.steps.append(step)


def traced(efenix: Efenix, trace: OrderTrace, clock: Callable[[], float]) -> Efenix:
    """Okno ``efenix``, które zapisuje w ``trace`` każde swoje udane działanie z czasem z ``clock`` (sekundy)."""

    return _Traced(efenix, trace, clock)
