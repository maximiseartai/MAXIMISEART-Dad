"""Tempo ludzkie Wyceny w efenix: przerwy przed zapisami w oknie efenix, ok. 20 s na zlecenie z zapisem (spec #741, ADR 0024).

Przerwy należą do zapisów w efenix, nie do odczytów (decyzja Maksa 4.11.2026, #834). Okno zlecenia z tempem
(``Pacing.window``) robi przerwę ``ACTION_PAUSE_S`` przed każdym zapisem (data wykonania, Wycena Emmetta, ilość), a przed
szukaniem następnego zlecenia tyle, ile zostało do ``ORDER_S`` od szukania zlecenia, w którym coś zapisało. Zlecenie z
zapisem trwa więc ok. ``ORDER_S``, jak u taty, a żadna przerwa nie jest dłuższa niż ``KEEPALIVE_S``, więc ruch w oknie co
kilkanaście sekund podtrzymuje sesję efenix. Samo sprawdzenie zlecenia bez zmiany w efenix (wycena już jest, Zlecenie
rozliczone, błąd zlecenia) to tylko szukanie i otwarcie, które idą bez przerwy, tak samo jak szukanie po takim zleceniu i
pierwsze szukanie przebiegu. Ponowne uruchomienie po Zatrzymaniu nie czeka więc na zleceniach, które już są gotowe.

Czas mierzy i odczekuje ``Pace`` (``clock`` i ``sleep``), więc test sprawdza przerwy na udawanym zegarze. Silnik owija
tempem okno zlecenia, które zapisuje ślad działań do Logów Uruchomienia (``efenix_trace``), więc czas działania w Logach
nie liczy przerwy przed nim. Chwilę szukania poprzedniego zlecenia z zapisem pamięta ``Pacing`` jednego przebiegu, a nie
okno, bo szukanie następnego zlecenia jest już w jego własnym oknie.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .efenix_checks import ListedOrder
    from .efenix_pricing import Efenix, EmmettLoad, OrderPricing

__all__ = ["ACTION_PAUSE_S", "KEEPALIVE_S", "ORDER_S", "Pace", "Pacing"]

ORDER_S: Final = 20.0
"""Czas jednego zlecenia, ile zajmuje ono tacie (spec #741: „ok. 20 s na zlecenie”)."""
ACTION_PAUSE_S: Final = 2.0
"""Przerwa przed każdym zapisem w efenix: zlecenie z datą wykonania, Wyceną Emmetta i dwiema ilościami ma cztery zapisy,
czyli 8 s przerw, a resztę do ``ORDER_S`` dopełnia przerwa przed szukaniem następnego zlecenia."""
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


class Pacing:
    """Tempo ludzkie ``pace`` jednego przebiegu: okno każdego zlecenia (``window``) robi przerwy przed zapisami, a przerwa
    przed szukaniem liczy się od szukania poprzedniego zlecenia, jeśli coś w nim zapisało."""

    def __init__(self, pace: Pace) -> None:
        self._pace = pace
        # Chwila szukania poprzedniego zlecenia, w którym okno coś zapisało; ``None``, gdy poprzednie zlecenie nic nie
        # zapisało albo przebieg dopiero ruszył, więc szukanie idzie bez przerwy.
        self._written_search: float | None = None

    def window(self, efenix: Efenix) -> Efenix:
        """Okno ``efenix`` z przerwami tempa przed zapisami i przed szukaniem po zleceniu z zapisem."""

        return _PacedEfenix(efenix, self)

    def before_search(self) -> float:
        """Przerwa przed szukaniem zlecenia; zwraca chwilę tego szukania."""

        if self._written_search is not None:
            left = ORDER_S - (self._pace.clock() - self._written_search)
            self._pace.sleep(min(max(left, ACTION_PAUSE_S), KEEPALIVE_S))
            self._written_search = None
        return self._pace.clock()

    def before_write(self, searched: float | None) -> None:
        """Przerwa przed zapisem w zleceniu, którego szukanie było w chwili ``searched`` (``None``: bez szukania)."""

        self._pace.sleep(ACTION_PAUSE_S)
        self._written_search = searched


class _PacedEfenix:
    """Okno efenix z przerwami ``pacing`` przed zapisami; implementuje ``efenix_pricing.Efenix``."""

    def __init__(self, efenix: Efenix, pacing: Pacing) -> None:
        self._efenix = efenix
        self._pacing = pacing
        self._searched: float | None = None

    def search(self, number: str) -> Sequence[ListedOrder]:
        self._searched = self._pacing.before_search()
        return self._efenix.search(number)

    def open_order(self, order: ListedOrder) -> OrderPricing:
        return self._efenix.open_order(order)

    def set_execution_date(self, day: date) -> bool:
        self._pacing.before_write(self._searched)
        return self._efenix.set_execution_date(day)

    def load_emmett(self, verdict: Callable[[EmmettLoad], OrderPricing]) -> OrderPricing:
        self._pacing.before_write(self._searched)
        return self._efenix.load_emmett(verdict)

    def enter_quantity(self, position: str, quantity: int) -> Decimal:
        self._pacing.before_write(self._searched)
        return self._efenix.enter_quantity(position, quantity)
