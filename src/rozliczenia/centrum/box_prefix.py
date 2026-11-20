from __future__ import annotations

from rozliczenia.centrum.scope import BoxPrefix
from rozliczenia.client_data import Outgoing, tool


def titled(prefix: BoxPrefix | None, title: Outgoing) -> Outgoing:
    return title if prefix is None else tool(f"{prefix} ") + title


def tagged(prefix: BoxPrefix | None, tag: Outgoing) -> Outgoing:
    return tag if prefix is None else tool(f"{prefix.lower()}-") + tag


def prefix_of(title: str) -> BoxPrefix | None:
    return next((known for known in BoxPrefix if title.startswith(f"{known} ")), None)


def owns(prefix: BoxPrefix | None, title: str) -> bool:
    return prefix_of(title) is prefix
