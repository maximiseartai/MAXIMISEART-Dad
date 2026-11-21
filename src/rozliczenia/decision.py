from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .message import Message, StopError

__all__ = ["Conversation", "Decision"]


@dataclass(frozen=True)
class Decision:
    message: Message
    counts_title: str
    counts: Sequence[tuple[str, int]]
    question: str


class Conversation(Protocol):
    @property
    def continue_hint(self) -> str: ...

    def confirm(self, decision: Decision) -> bool: ...


class Declined(StopError): ...
