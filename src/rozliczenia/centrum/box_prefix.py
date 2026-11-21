from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from rozliczenia.centrum.scope import BoxPrefix
from rozliczenia.client_data import Outgoing, tool

WORKSTATIONS: Final[Mapping[BoxPrefix, str]] = MappingProxyType({BoxPrefix.ANDRZEJ: "Stanowisko Andrzeja"})


def titled(prefix: BoxPrefix | None, title: Outgoing) -> Outgoing:
    return title if prefix is None else tool(f"{prefix} ") + title


def tagged(prefix: BoxPrefix | None, tag: Outgoing) -> Outgoing:
    return tag if prefix is None else tool(f"{prefix.lower()}-") + tag


def stamped(prefix: BoxPrefix | None, body: str) -> str:
    return body if prefix is None else f"{body}\n{_stamp(prefix)}"


def _stamp(prefix: BoxPrefix) -> Outgoing:
    return tool(f"<!-- {WORKSTATIONS[prefix]} -->")


def prefix_of(title: str) -> BoxPrefix | None:
    return next((known for known in BoxPrefix if title.startswith(f"{known} ")), None)


def owns(prefix: BoxPrefix | None, title: str) -> bool:
    return prefix_of(title) is prefix
