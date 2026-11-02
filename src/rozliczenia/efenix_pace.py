"""Tempo ludzkie Wyceny w efenix: przerwy między działaniami okna efenix, ok. 20 s na zlecenie (spec #741, ADR 0024).

Okno efenix z tempem (``paced``) robi przerwę przed każdym działaniem z listy dozwolonych: ``ACTION_PAUSE_S`` przed każdym
działaniem w zleceniu, a przed szukaniem następnego zlecenia tyle, ile zostało do ``ORDER_S`` od szukania poprzedniego.
Przerwy są więc rozłożone między działaniami, a zlecenie trwa ok. ``ORDER_S``, jak u taty. Żadna przerwa nie jest dłuższa
niż ``KEEPALIVE_S``, więc ruch w oknie co kilkanaście sekund podtrzymuje sesję efenix. Zlecenie z kilkoma działaniami (wycena
już jest: szukanie i otwarcie) trwa przez to krócej niż ``ORDER_S``. Zlecenie, które kończy się błędem przed szukaniem,
nie ma żadnego działania ani przerwy.

Czas mierzy i odczekuje ``Pace`` (``clock`` i ``sleep``), więc test sprawdza przerwy na udawanym zegarze.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import time
from typing import Final

from .efenix_pricing import Efenix, ListedOrder, OpenEfenix, OrderPricing

__all__ = ["ACTION_PAUSE_S", "KEEPALIVE_S", "ORDER_S", "Pace", "paced"]

ORDER_S: Final = 20.0
"""Czas jednego zlecenia, ile zajmuje ono tacie (spec #741: „ok. 20 s na zlecenie”)."""
ACTION_PAUSE_S: Final = 2.0
"""Przerwa przed każdym działaniem w zleceniu po szukaniu: zlecenie z datą wykonania, Wyceną Emmetta i dwiema ilościami
ma po szukaniu sześć działań, czyli 12 s przerw, a resztę do ``ORDER_S`` dopełnia przerwa przed szukaniem następnego."""
KEEPALIVE_S: Final = 15.0
"""Próg podtrzymania sesji: najdłuższa przerwa między działaniami w efenix.

Po ilu minutach bezczynności efenix wylogowuje, nie wiadomo. Zakładamy ostrożnie, że już po 3 minutach (zwykła sesja PHP
wygasa po 24). 15 s to „ruch co kilkanaście sekund” ze specyfikacji #741 i dwunastokrotny zapas do tych 3 minut.
"""


@dataclass(frozen=True)
class Pace:
    """Tempo ludzkie: zegar w sekundach, z którego liczone są przerwy, i odczekanie przerwy."""

    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


def paced(open_efenix: OpenEfenix, pace: Pace) -> OpenEfenix:
    """``open_efenix``, którego okno robi przerwy tempa ludzkiego ``pace`` przed każdym działaniem."""

    @contextmanager
    def open_paced() -> Iterator[Efenix]:
        with open_efenix() as efenix:
            yield _PacedEfenix(efenix, pace)

    return open_paced


class _PacedEfenix:
    """Okno efenix z przerwami przed działaniami; implementuje ``efenix_pricing.Efenix``."""

    def __init__(self, efenix: Efenix, pace: Pace) -> None:
        self._efenix = efenix
        self._pace = pace
        self._order_started: float | None = None

    @property
    def sent_change(self) -> bool:
        return self._efenix.sent_change

    def search(self, number: str) -> Sequence[ListedOrder]:
        self._pace.sleep(self._before_next_order())
        self._order_started = self._pace.clock()
        return self._efenix.search(number)

    def open_order(self, order: ListedOrder) -> OrderPricing:
        self._pace.sleep(ACTION_PAUSE_S)
        return self._efenix.open_order(order)

    def set_execution_date(self, day: date) -> bool:
        self._pace.sleep(ACTION_PAUSE_S)
        return self._efenix.set_execution_date(day)

    def load_emmett(self) -> OrderPricing:
        self._pace.sleep(ACTION_PAUSE_S)
        return self._efenix.load_emmett()

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        self._pace.sleep(ACTION_PAUSE_S)
        return self._efenix.enter_quantity(position, quantity)

    def _before_next_order(self) -> float:
        """Reszta ``ORDER_S`` od szukania poprzedniego zlecenia, co najmniej ``ACTION_PAUSE_S`` i najwyżej ``KEEPALIVE_S``."""

        if self._order_started is None:
            return ACTION_PAUSE_S
        left = ORDER_S - (self._pace.clock() - self._order_started)
        return min(max(left, ACTION_PAUSE_S), KEEPALIVE_S)
