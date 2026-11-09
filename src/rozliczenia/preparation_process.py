"""Przygotowanie pliku zbiorczego dla Uruchomienia procesu: silnik i fakty zakończenia."""

from __future__ import annotations


from . import collective_preparation
from . import preparation_messages as messages
from .collective_preparation import PreparationInputs, PreparationSummary
from .process_run import Counter, Preview, Process
from .run_context import RunContext
from .telemetry import CompletedResult


def _result(inputs: PreparationInputs, _summary: PreparationSummary) -> CompletedResult:
    """Zapisany Plik zbiorczy wymaga sprawdzenia: ilości z opisu technika zawsze zostają do uzupełnienia.

    Tata uzupełnia go przed Przebiegiem rozliczeń. Podgląd bez zapisu nic nie tworzy, więc z tymi samymi
    ostrzeżeniami kończy się wynikiem OK i prowadzi do zapisu. Fakty planu nie zmieniają wyniku.
    """

    return "OK" if inputs.dry_run else "WYMAGA_SPRAWDZENIA"


PROCESS: Process[PreparationInputs, PreparationSummary, RunContext] = Process(
    name="Przygotowanie pliku zbiorczego",
    counters=(
        Counter("period_orders", lambda summary: summary.period_order_count),
        Counter("successful_orders", lambda summary: summary.successful_order_count),
        Counter("skipped_empty_rows", lambda summary: summary.skipped_empty_rows),
        Counter("warnings", lambda summary: len(summary.warnings)),
    ),
    result=_result,
    routes=lambda summary: summary.routes,
    preview=Preview(messages.plan_not_shown(), dry_run=lambda inputs: inputs.dry_run),
    metrics_failure_tail="Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
    execute=collective_preparation.prepare_collective_file,
    unexpected_failure=messages.unexpected_failure(),
    summary_not_shown=messages.summary_not_shown(),
)
