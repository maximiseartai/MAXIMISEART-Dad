"""Przebieg rozliczeń dla Uruchomienia procesu: silnik i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby,
Komunikaty i rekord metryk są te same.
"""

from __future__ import annotations


from . import engine, settlement_messages
from .engine import SettlementInputs, SettlementSummary
from .process_run import Finished, Process
from .run_context import RunContext
from .tool_files import SETTLEMENT_METRICS

_COUNTERS = frozenset(
    {"templates_total", "templates_completed", "rows", "written", "empty", "planned", "skipped", "issues"}
)


def _finished(_inputs: SettlementInputs, summary: SettlementSummary) -> Finished:
    return Finished(
        result="OK" if summary.ok else "WYMAGA_SPRAWDZENIA",
        counters={
            "templates_total": summary.template_count,
            "templates_completed": summary.template_count,
            "rows": summary.total_rows,
            "written": summary.written_count,
            "empty": summary.empty_count,
            "planned": summary.planned_count,
            # Licznik ze schematu metryk sprzed usunięcia pominiętych szablonów; zawsze 0,
            # żeby stare i nowe rekordy miały te same klucze.
            "skipped": 0,
            "issues": len(summary.warnings),
        },
        phase_durations_ms=summary.phase_durations_ms,
        routes=summary.routes,
    )


PROCESS: Process[SettlementInputs, SettlementSummary, RunContext] = Process(
    name="Przebieg rozliczeń",
    counter_names=_COUNTERS,
    metrics_path=lambda: SETTLEMENT_METRICS,
    metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
    execute=engine.run_settlements,
    finished=_finished,
    unexpected_failure=settlement_messages.unexpected_failure(),
    plan_not_shown=settlement_messages.plan_not_shown(),
    summary_not_shown=settlement_messages.summary_not_shown(),
)
