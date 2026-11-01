"""Wycena w efenix dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Okno efenix daje rozmówca (``EfenixInputs.open_efenix``): Skrypt dla maszyn otwiera Chromium Playwrighta
(``efenix_browser.chromium``), a testy okno na Atrapie efenix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import TOOL_ROOT, efenix_pricing
from . import efenix_messages as messages
from .decision import Conversation
from .domain import ProgressObserver
from .efenix_pricing import OpenEfenix, PricingSummary
from .period_folder import PeriodFolder, PeriodFolderError
from .process_run import Finished, Process
from .telemetry import UNKNOWN_PERIOD

_COUNTERS = frozenset({"orders", "found", "errors", "with_photos", "defects"})


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii pozostałych procesów."""

    return TOOL_ROOT / ".wycena-efenix-metrics.jsonl"


@dataclass(frozen=True)
class EfenixInputs:
    """Wejście procesu Wyceny w efenix: Plik zbiorczy okresu i okno efenix w sesji taty.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da). Wycena w efenix nie ma podglądu bez zapisu.
    """

    source: Path
    open_efenix: OpenEfenix

    @property
    def period(self) -> str:
        try:
            return PeriodFolder.from_collective_file(self.source.expanduser().resolve()).period.token
        except PeriodFolderError:
            return UNKNOWN_PERIOD

    @property
    def dry_run(self) -> bool:
        return False


def _execute(inputs: EfenixInputs, observer: ProgressObserver, _conversation: Conversation) -> PricingSummary:
    return efenix_pricing.price_orders(inputs.source, inputs.open_efenix, observer=observer)


def _finished(_inputs: EfenixInputs, summary: PricingSummary) -> Finished:
    return Finished(
        result="OK" if summary.error_count == 0 else "WYMAGA_SPRAWDZENIA",
        counters={
            "orders": len(summary.results),
            "found": summary.found_count,
            "errors": summary.error_count,
            "with_photos": summary.with_photos,
            "defects": summary.defects,
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


PROCESS: Process[EfenixInputs, PricingSummary] = Process(
    name="Wycena w efenix",
    counter_names=_COUNTERS,
    metrics_path=default_metrics_path,
    metrics_failure_tail="Wycena w efenix zakończyła się niezależnie.",
    execute=_execute,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)
