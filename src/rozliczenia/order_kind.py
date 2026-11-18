"""Rodzaj Surowego zlecenia z ``URZĄDZENIA``: zamknięty słownik rodzajów z aplikacji firmowej.

Słownik ma jednego właściciela, bo czytają go dwie reguły: Planowanie Uporządkowania INTERMAX (``raw_orders``) daje
zleceniu rodzaj, od którego zależą Kolor operatora i Wpis urządzenia i czynności INTERMAX, a pamięć reguły danych
(``client_data``) nie zapamiętuje wartości z rodzajem jako zakazanej, bo słowo rodzaju nie wskazuje klienta.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Final

from .text import folded_name


class OrderKind(Enum):
    """Rodzaj Surowego zlecenia z ``URZĄDZENIA``: usterka (także hurt), instalacja hurt albo inny."""

    FAULT = "usterka"
    WHOLESALE_INSTALLATION = "instalacja hurt"
    OTHER = "inny"


_KINDS: Final[Mapping[str, OrderKind]] = MappingProxyType(
    {
        "usterka": OrderKind.FAULT,
        "usterkahurt": OrderKind.FAULT,
        "instalacjahurt": OrderKind.WHOLESALE_INSTALLATION,
    }
)
"""``URZĄDZENIA`` po ``folded_name`` → rodzaj zlecenia."""


def order_kind(devices: object) -> OrderKind:
    """Rodzaj zlecenia z wartości ``URZĄDZENIA`` bez wielkości liter, spacji i myślników (``folded_name``): „Instalacja
    Hurt” i ``instalacja-hurt`` to instalacja hurt, a każda wartość spoza słownika to ``OrderKind.OTHER``."""

    return _KINDS.get(folded_name(devices), OrderKind.OTHER)
