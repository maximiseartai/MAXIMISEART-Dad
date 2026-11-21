from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Final

from .text import folded_name


class OrderKind(Enum):
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


def order_kind(devices: object) -> OrderKind:
    return _KINDS.get(folded_name(devices), OrderKind.OTHER)
