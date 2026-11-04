"""Wycena w efenix dla Uruchomienia procesu: wejście procesu, wywołanie silnika i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Wynik to OK, gdy żadne zlecenie nie zostało tacie (każde jest gotowe albo jest Zleceniem rozliczonym). Zlecenia
rozliczone liczą się w rekordzie metryk tylko do ``orders``: zestaw liczników jest stały, bo rekord z innym zestawem
Historia odrzuca, a z niej Droga okresu liczy Wycenę w efenix.
Okno efenix daje rozmówca (``EfenixInputs.open_efenix``): Centrum rozliczeń otwiera widoczne okno Google Chrome w profilu
narzędzia i czeka w nim na logowanie taty (``efenix_browser.chrome``), Skrypt dla maszyn otwiera Chromium Playwrighta
(``efenix_browser.chromium``), a testy okno na Atrapie efenix. Czas czekania na logowanie wstrzymuje zegar rdzenia
(``EngineConversation.waiting``), tak jak Decyzja taty. Tempo ludzkie okna (``efenix_pace``) i folder Śladu Wyceny
Emmetta (``efenix_emmett_trace``) wybiera każdy rozmówca: Centrum taty bierze je z okna taty
(``centrum.efenix_run.EfenixWindow.of_tata``), a testy, weryfikacja i Skrypt dla maszyn na Atrapie efenix wyłączają tempo
(``None``) i podają własny folder. Ślad okresu leży w pliku ``<okres>.json`` tego folderu, obok klucza, pod którym są w
nim zlecenia.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import TOOL_ROOT, efenix_pricing
from . import efenix_messages as messages
from .decision import EngineConversation
from .domain import ProgressObserver
from .efenix_pace import Pace
from .efenix_pricing import NO_JOURNAL, OpenEfenix, OrderJournal, PricingSummary
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
    ``clock`` to zegar w sekundach czasów etapów i śladu zleceń (ten sam, którym rdzeń liczy ``Czas uruchomienia``).
    ``pace``: tempo ludzkie okna; ``None`` wyłącza przerwy. ``trace_directory``: folder Śladów Wyceny Emmetta.
    ``journal``: dziennik Wyceny w efenix w trakcie przebiegu; Centrum podaje swój (``centrum.pricing_journal``), a Skrypt
    dla maszyn przebiega bez niego.
    """

    source: Path
    open_efenix: OpenEfenix
    pace: Pace | None
    trace_directory: Path
    clock: Callable[[], float] = field(default=time.perf_counter, compare=False)
    journal: OrderJournal = field(default=NO_JOURNAL, compare=False)

    @property
    def period(self) -> str:
        try:
            return PeriodFolder.from_collective_file(self.source.expanduser().resolve()).period.token
        except PeriodFolderError:
            return UNKNOWN_PERIOD

    @property
    def dry_run(self) -> bool:
        return False


def _execute(inputs: EfenixInputs, observer: ProgressObserver, conversation: EngineConversation) -> PricingSummary:
    return efenix_pricing.price_orders(
        inputs.source,
        inputs.open_efenix,
        inputs.trace_directory / f"{inputs.period}.json",
        observer=observer,
        clock=inputs.clock,
        waiting=conversation.waiting,
        pace=inputs.pace,
        journal=inputs.journal,
    )


def _finished(_inputs: EfenixInputs, summary: PricingSummary) -> Finished:
    return Finished(
        result="OK" if not summary.left_for_tata else "WYMAGA_SPRAWDZENIA",
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
