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
from .process_run import Counter, Process
from .run_context import RunContext
from .tool_files import EFENIX_METRICS

PROCESS: Process[EfenixInputs, PricingSummary, RunContext] = Process(
    name="Wycena w efenix",
    counters=(
        Counter("orders", lambda summary: len(summary.results)),
        Counter("ready", lambda summary: summary.count(OrderKind.READY)),
        Counter("errors", lambda summary: summary.count(OrderKind.ERROR)),
        Counter("emmett_warnings", lambda summary: summary.count(OrderKind.WARNING)),
        Counter("with_photos", lambda summary: summary.with_photos),
        Counter("defects", lambda summary: summary.defects),
    ),
    result=lambda _inputs, summary: "OK" if not summary.warnings else "WYMAGA_SPRAWDZENIA",
    preview=None,
    metrics_path=lambda: EFENIX_METRICS,
    metrics_failure_tail="Wycena w efenix zakończyła się niezależnie.",
    execute=efenix_pricing.price_orders,
    unexpected_failure=messages.unexpected_failure(),
    summary_not_shown=messages.summary_not_shown(),
)
