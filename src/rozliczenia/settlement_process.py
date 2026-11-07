"""Przebieg rozliczeń dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby,
Komunikaty i rekord metryk są te same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import engine, settlement_messages
from .client_data import ForbiddenValues
from .input_copy import InputCopy
from .decision import Conversation
from .domain import ProgressObserver
from .engine import SettlementSummary
from .input_checks import FILE_READERS, Readers
from .period_folder import PeriodFolder, PeriodFolderError
from .process_run import Finished, Process
from .telemetry import UNKNOWN_PERIOD
from .tool_files import SETTLEMENT_METRICS

_COUNTERS = frozenset(
    {"templates_total", "templates_completed", "rows", "written", "empty", "planned", "skipped", "issues"}
)

def _period_label(source: Path) -> str:
    try:
        return PeriodFolder.from_collective_file(source.expanduser().resolve()).period.token
    except PeriodFolderError:
        return UNKNOWN_PERIOD


@dataclass(frozen=True)
class SettlementInputs:
    """Wejście procesu Przebiegu rozliczeń, gotowe przed startem silnika.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da). ``readers`` czytają Wzorzec, a
    ``forbidden`` to pamięć reguły danych pracy Centrum (``None``: bez wysyłki, bez pamięci), a ``copy`` Kopia wejścia
    Uruchomienia z Centrum (``None``: bez Logów, bez Kopii).
    """

    source: Path
    config_path: Path
    worker_template_path: Path
    dry_run: bool = False
    readers: Readers = FILE_READERS
    forbidden: ForbiddenValues | None = None
    copy: InputCopy | None = field(default=None, compare=False)

    @property
    def period(self) -> str:
        return _period_label(self.source)


def _execute(
    inputs: SettlementInputs, observer: ProgressObserver, _conversation: Conversation
) -> SettlementSummary:
    return engine.run_settlements(
        inputs.source,
        inputs.config_path,
        dry_run=inputs.dry_run,
        worker_template_path=inputs.worker_template_path,
        observer=observer,
        readers=inputs.readers,
        forbidden=inputs.forbidden,
        copy=inputs.copy,
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


PROCESS: Process[SettlementInputs, SettlementSummary] = Process(
    name="Przebieg rozliczeń",
    counter_names=_COUNTERS,
    metrics_path=lambda: SETTLEMENT_METRICS,
    metrics_failure_tail="proces rozliczeń zakończył się niezależnie.",
    execute=_execute,
    finished=_finished,
    unexpected_failure=settlement_messages.unexpected_failure(),
    plan_not_shown=settlement_messages.plan_not_shown(),
    summary_not_shown=settlement_messages.summary_not_shown(),
)
