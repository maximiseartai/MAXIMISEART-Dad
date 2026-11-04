"""Przygotowanie pliku zbiorczego dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby,
ostrzeżenia, Komunikaty i rekord metryk są te same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import TOOL_ROOT, collective_preparation
from . import preparation_messages as messages
from .collective_preparation import (
    PreparationSummary,
    default_collective_template_path,
    default_internal_template_path,
)
from .client_data import ForbiddenValues
from .decision import Conversation
from .domain import ProgressObserver
from .input_checks import FILE_READERS, Readers
from .process_run import Finished, Process
from .worker_config import default_config_path


# Liczniki historii metryk Przygotowania pliku zbiorczego (inne niż Przebiegu rozliczeń).
_COUNTERS = frozenset({"period_orders", "successful_orders", "skipped_empty_rows", "warnings"})


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii Przebiegu rozliczeń."""

    return TOOL_ROOT / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"


@dataclass(frozen=True)
class PreparationInputs:
    """Wejście procesu Przygotowania pliku zbiorczego, gotowe przed startem silnika, z czytnikami plików taty.

    ``forbidden`` to pamięć reguły danych pracy Centrum (``None``: bez wysyłki, bez pamięci).
    """

    register_path: Path
    periods_directory: Path
    period: str
    dry_run: bool = False
    config_path: Path = field(default_factory=default_config_path)
    internal_template_path: Path = field(default_factory=default_internal_template_path)
    collective_template_path: Path = field(default_factory=default_collective_template_path)
    readers: Readers = FILE_READERS
    forbidden: ForbiddenValues | None = None


def _execute(inputs: PreparationInputs, observer: ProgressObserver, conversation: Conversation) -> PreparationSummary:
    return collective_preparation.prepare_collective_file(
        inputs.register_path,
        inputs.periods_directory,
        inputs.period,
        inputs.config_path,
        internal_template_path=inputs.internal_template_path,
        collective_template_path=inputs.collective_template_path,
        dry_run=inputs.dry_run,
        observer=observer,
        conversation=conversation,
        readers=inputs.readers,
        forbidden=inputs.forbidden,
    )


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


PROCESS: Process[PreparationInputs, PreparationSummary] = Process(
    name="Przygotowanie pliku zbiorczego",
    counter_names=_COUNTERS,
    metrics_path=default_metrics_path,
    metrics_failure_tail="Przygotowanie pliku zbiorczego zakończyło się niezależnie.",
    execute=_execute,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)
