"""Przygotowanie pliku zbiorczego dla Uruchomienia procesu: silnik i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby,
ostrzeżenia, Komunikaty i rekord metryk są te same.
"""

from __future__ import annotations


from . import collective_preparation
from . import preparation_messages as messages
from .collective_preparation import PreparationInputs, PreparationSummary
from .process_run import Finished, Process
from .run_context import RunContext
from .tool_files import PREPARATION_METRICS

# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = frozenset({"period_orders", "successful_orders", "skipped_empty_rows", "warnings"})


def _finished(inputs: PreparationInputs, summary: PreparationSummary) -> Finished:
    """Zapisany Plik zbiorczy wymaga sprawdzenia: ilości z opisu technika zawsze zostają do uzupełnienia.

    Tata uzupełnia go przed Przebiegiem rozliczeń. Podgląd bez zapisu nic nie tworzy, więc z tymi samymi
    ostrzeżeniami kończy się wynikiem OK i prowadzi do zapisu. Fakty planu nie zmieniają wyniku.
    """

    return Finished(
        result="OK" if inputs.dry_run else "WYMAGA_SPRAWDZENIA",
        counters={
            "period_orders": summary.period_order_count,
            "successful_orders": summary.successful_order_count,
            "skipped_empty_rows": summary.skipped_empty_rows,
            "warnings": len(summary.warnings),
        },
        phase_durations_ms=summary.phase_durations_ms,
        routes=summary.routes,
    )


PROCESS: Process[PreparationInputs, PreparationSummary, RunContext] = Process(
    name="Przygotowanie pliku zbiorczego",
    counter_names=_COUNTERS,
    metrics_path=lambda: PREPARATION_METRICS,
    metrics_failure_tail="Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
    execute=collective_preparation.prepare_collective_file,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)
