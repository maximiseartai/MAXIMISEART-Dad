"""Wycena w efenix dla Uruchomienia procesu: silnik i fakty zakończenia.

Opis procesu (``PROCESS``) jest wspólny dla każdego rozmówcy, więc liczby, Komunikaty i rekord metryk są te same.
Wynik to OK, gdy żadne zlecenie nie zostało tacie (każde jest gotowe, Zleceniem rozliczonym albo Zleceniem
przekazanym). Zlecenia rozliczone i przekazane liczą się w rekordzie metryk tylko do ``orders``: zestaw liczników jest
stały, bo rekord z innym zestawem Historia odrzuca, a z niej Droga okresu liczy Wycenę w efenix.
Okno efenix daje rozmówca (``EfenixInputs.open_efenix``): Centrum rozliczeń otwiera widoczne okno Google Chrome w profilu
narzędzia i czeka w nim na logowanie taty (``efenix_browser.chrome``), Skrypt dla maszyn otwiera Chromium Playwrighta
(``efenix_browser.chromium``), a testy okno na Atrapie efenix. Czas czekania na logowanie wstrzymuje zegar
Uruchomienia, tak jak Decyzja taty. Tempo ludzkie okna (``efenix_pace``) wybiera każdy rozmówca:
Centrum taty bierze je z okna taty (``centrum.efenix_run.EfenixWindow.of_tata``), a testy, weryfikacja i Skrypt dla
maszyn na Atrapie efenix wyłączają je (``None``).
"""

from __future__ import annotations


from . import efenix_pricing
from . import efenix_messages as messages
from .efenix_pricing import EfenixInputs, OrderKind, PricingSummary
from .process_run import Finished, Process
from .run_context import RunContext
from .tool_files import EFENIX_METRICS

_COUNTERS = frozenset({"orders", "ready", "errors", "emmett_warnings", "with_photos", "defects"})


def _finished(_inputs: EfenixInputs, summary: PricingSummary) -> Finished:
    return Finished(
        result="OK" if not summary.warnings else "WYMAGA_SPRAWDZENIA",
        counters={
            "orders": len(summary.results),
            "ready": summary.count(OrderKind.READY),
            "errors": summary.count(OrderKind.ERROR),
            "emmett_warnings": summary.count(OrderKind.WARNING),
            "with_photos": summary.with_photos,
            "defects": summary.defects,
        },
        phase_durations_ms=summary.phase_durations_ms,
    )


PROCESS: Process[EfenixInputs, PricingSummary, RunContext] = Process(
    name="Wycena w efenix",
    counter_names=_COUNTERS,
    metrics_path=lambda: EFENIX_METRICS,
    metrics_failure_tail="Wycena w efenix zakończyła się niezależnie.",
    execute=efenix_pricing.price_orders,
    finished=_finished,
    unexpected_failure=messages.unexpected_failure(),
    plan_not_shown=messages.plan_not_shown(),
    summary_not_shown=messages.summary_not_shown(),
)
