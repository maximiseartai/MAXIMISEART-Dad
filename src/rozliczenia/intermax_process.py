"""Uporządkowanie INTERMAX dla Uruchomienia procesu: silnik i fakty zakończenia.

Proces nie należy do okresu; jego Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019).
"""

from __future__ import annotations


from . import intermax_ordering
from . import intermax_messages as messages
from .intermax_ordering import OrderingInputs, OrderingSummary
from .process_run import Counter, Process
from .run_context import RunContext

PROCESS: Process[OrderingInputs, OrderingSummary, RunContext] = Process(
    name="Uporządkowanie INTERMAX",
    counters=(
        Counter("orders", lambda summary: summary.order_count),
        Counter("workers", lambda summary: summary.worker_count),
    ),
    result=lambda _inputs, _summary: "OK",
    preview=None,
    metrics_failure_tail="Uporządkowanie INTERMAX zakończyło się niezależnie.",
    execute=intermax_ordering.order_register,
    unexpected_failure=messages.unexpected_failure(),
    summary_not_shown=messages.summary_not_shown(),
)
