"""Położenie wiersza arkusza zleceń (ADR 0025 „Położenie wiersza”) i wiersze nad wklejeniem: typy bez reguł.

Uchwyt plików taty i Kopia wejścia niosą położenia wiersza i wiersze nad wklejeniem, a buduje je rozpoznanie Surowych
zleceń INTERMAX (``raw_orders.row_positions``, ``raw_orders.above_paste``), więc typy leżą osobno od jego reguł.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class AbovePaste:
    """Wiersze nad wklejeniem, od których ``raw_orders.recognize`` liczy wiersz dnia (``raw_orders.RawBlock.anchor``):
    ostatni uporządkowany wiersz (``None``: bez niego dzień staje pod nagłówkiem) i żółty wiersz między nim a wklejeniem
    (``None``: bez żółtego wiersza)."""

    last_ordered: int | None
    yellow: int | None


@dataclass(frozen=True)
class RowPositions:
    """Położenia wiersza arkusza zleceń (ADR 0025 „Położenie wiersza”) z jednej reguły (``raw_orders.row_positions``).

    ``read``: o tyle kolumn na lewo od swojego nagłówka proces czyta komórki wiersza (``raw_orders.SHIFT`` w
    przesuniętym pierwszym wierszu bloku Surowych zleceń, inaczej 0). ``known``: przesunięcia, przy których pamięć reguły
    danych zna jego zakazane komórki, a Kopia wejścia ma tylko komórki dozwolone przy każdym z nich. ``traced``: wiersz,
    który nie jest pierwszym wierszem bloku wklejenia, ma ślad przesunięcia, więc Logi mówią, że fakt domeny jest
    złamany.
    """

    read: int = 0
    known: tuple[int, ...] = (0,)
    traced: bool = False

    @property
    def uncertain(self) -> bool:
        """Wiersz z siatki: pamięć zna go w obu położeniach (``raw_orders.both_positions``)."""

        return len(self.known) > 1


UNDER_HEADER: Final = RowPositions()
"""Wiersz pod swoimi nagłówkami: każdy wiersz Pliku zbiorczego i Rejestru w Przygotowaniu."""
