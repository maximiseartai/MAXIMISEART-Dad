"""Uporządkowanie INTERMAX dla Uruchomienia procesu: silnik i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Proces nie należy do okresu; jego Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019).
"""

from __future__ import annotations


from . import intermax_ordering
from . import intermax_messages as messages
from .intermax_ordering import OrderingInputs, OrderingSummary
from .process_run import Finished, Process
from .run_context import RunContext
from .tool_files import INTERMAX_METRICS

_COUNTERS = frozenset({"orders", "workers"})


def _finished(_inputs: OrderingInputs, summary: OrderingSummary) -> Finished:
    return Finished(
        result="OK",
        counters={"orders": summary.order_count, "workers": summary.worker_count},
        phase_durations_ms=summary.phase_durations_ms,
    )


PROCESS: Process[OrderingInputs, OrderingSummary, RunContext] = Process(
    name="Uporządkowanie INTERMAX",
    counter_names=_COUNTERS,
    metrics_path=lambda: INTERMAX_METRICS,
    metrics_failure_tail="Uporządkowanie INTERMAX zakończyło się niezależnie.",
    execute=intermax_ordering.order_register,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)
