"""Wycena w efenix dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Okno efenix daje rozmówca (``EfenixInputs.open_efenix``): Skrypt dla maszyn otwiera Chromium Playwrighta
(``efenix_browser.chromium``), a testy okno na Atrapie efenix. Proces pracuje w oknie w tempie ludzkim (``efenix_pace``),
chyba że rozmówca je wyłączy (``EfenixInputs.pace`` równe ``None``), jak testy i Skrypt dla maszyn na Atrapie efenix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import TOOL_ROOT, efenix_pricing
from .efenix_pace import Pace, paced
from . import efenix_messages as messages
from .decision import Conversation
from .domain import ProgressObserver
from .efenix_pricing import OpenEfenix, PricingSummary
from .period_folder import PeriodFolder, PeriodFolderError
from .process_run import Finished, Process
from .telemetry import UNKNOWN_PERIOD

_COUNTERS = frozenset({"orders", "ready", "errors", "emmett_warnings", "with_photos", "defects"})


def default_metrics_path() -> Path:
    """Osobna lokalna historia metryk, obok historii pozostałych procesów."""

    return TOOL_ROOT / ".wycena-efenix-metrics.jsonl"


@dataclass(frozen=True)
class EfenixInputs:
    """Wejście procesu Wyceny w efenix: Plik zbiorczy okresu i okno efenix w sesji taty.

    Okres wynika z nazwy Pliku zbiorczego (``nieznany``, gdy się nie da). Wycena w efenix nie ma podglądu bez zapisu.
    ``pace``: tempo ludzkie okna, domyślnie z prawdziwym zegarem; ``None`` wyłącza przerwy.
    """

    source: Path
    open_efenix: OpenEfenix
    pace: Pace | None = Pace()

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
    open_efenix = inputs.open_efenix if inputs.pace is None else paced(inputs.open_efenix, inputs.pace)
    return efenix_pricing.price_orders(inputs.source, open_efenix, observer=observer)


def _finished(_inputs: EfenixInputs, summary: PricingSummary) -> Finished:
    return Finished(
        result="OK" if summary.ready_count == len(summary.results) else "WYMAGA_SPRAWDZENIA",
        counters={
            "orders": len(summary.results),
            "ready": summary.ready_count,
            "errors": summary.error_count,
            "emmett_warnings": summary.warning_count,
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
