"""Wpisanie raportów dla Uruchomienia procesu: silnik i fakty zakończenia.

Proces nie należy do okresu; jego Uruchomienie ma okres dzisiejszej daty z zegara procesu (ADR 0019, ADR 0028).
"""

from __future__ import annotations

from . import report_entering
from . import report_entering_messages as messages
from .process_run import Counter, Process
from .report_entering import EnteringInputs, EnteringSummary
from .run_context import RunContext

PROCESS: Process[EnteringInputs, EnteringSummary, RunContext] = Process(
    name="Wpisanie raportów",
    counters=(
        Counter("entered", lambda summary: summary.entered),
        Counter("problems", lambda summary: len(summary.facts.problems)),
        Counter("reports", lambda summary: summary.reports),
    ),
    result=lambda _inputs, _summary: "OK",
    preview=None,
    metrics_failure_tail="Wpisanie raportów zakończyło się niezależnie.",
    execute=report_entering.enter_from_mail,
    unexpected_failure=messages.unexpected_failure(),
    summary_not_shown=messages.summary_not_shown(),
)
