"""Przebieg rozliczeń dla Uruchomienia procesu: silnik i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby,
Komunikaty i rekord metryk są te same.
"""

from __future__ import annotations


from . import engine, settlement_messages
from .engine import SettlementInputs, SettlementSummary
from .process_run import Counter, Preview, Process
from .run_context import RunContext

PROCESS: Process[SettlementInputs, SettlementSummary, RunContext] = Process(
    name="Przebieg rozliczeń",
    counters=(
        Counter("templates_total", lambda summary: summary.template_count),
        Counter("templates_completed", lambda summary: summary.template_count),
        Counter("rows", lambda summary: summary.total_rows),
        Counter("written", lambda summary: summary.written_count),
        Counter("empty", lambda summary: summary.empty_count),
        Counter("planned", lambda summary: summary.planned_count),
        # Licznik ze schematu metryk sprzed usunięcia pominiętych szablonów; zawsze 0,
        # żeby stare i nowe rekordy miały te same klucze.
        Counter("skipped", lambda _summary: 0),
        Counter("issues", lambda summary: len(summary.warnings)),
    ),
    result=lambda _inputs, summary: "OK" if summary.ok else "WYMAGA_SPRAWDZENIA",
    routes=lambda summary: summary.routes,
    preview=Preview(settlement_messages.plan_not_shown(), dry_run=lambda inputs: inputs.dry_run),
    metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
    execute=engine.run_settlements,
    unexpected_failure=settlement_messages.unexpected_failure(),
    summary_not_shown=settlement_messages.summary_not_shown(),
)
