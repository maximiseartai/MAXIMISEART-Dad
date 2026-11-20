from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from rozliczenia.centrum.run_logs import LoggedOrder, StartFacts
from rozliczenia.efenix_pricing import OrderKind


@dataclass(frozen=True)
class OrderDone:
    row: int
    outcome: OrderKind
    code: str | None

    @classmethod
    def of(cls, order: LoggedOrder) -> OrderDone:
        return cls(order.row, order.outcome, order.code)


@dataclass(frozen=True)
class PricingProgress:
    started: StartFacts
    done: tuple[OrderDone, ...]
    total: int | None
    current: int | None

    def outcomes(self) -> tuple[tuple[OrderKind, int], ...]:
        counted = Counter(order.outcome for order in self.done)
        return tuple((kind, counted[kind]) for kind in OrderKind if counted[kind])
