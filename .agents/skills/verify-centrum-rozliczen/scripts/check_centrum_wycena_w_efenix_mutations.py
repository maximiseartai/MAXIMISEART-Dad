"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `wycena-w-efenix` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import (
    BUILD,
    EFENIX_BROWSER,
    EFENIX_CHECKS,
    EFENIX_KIND,
    LOGS_OF_RUN,
    NOTIFICATIONS,
    RUN_LOGS,
    WYCENA,
)
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "bez przycisku dla okresu z Plikiem zbiorczym przygotowanym",
        (Edit(EFENIX_KIND, 'frozenset({"collective_file_prepared", "worker_settlements_ready"})', 'frozenset({"worker_settlements_ready"})'),),
        WYCENA,
        "tata nie może wycenić okresu zaraz po Uzupełnieniu pliku zbiorczego",
    ),
    Mutation(
        "okno nie mówi, że czeka na logowanie",
        (Edit(EFENIX_BROWSER, "        with login():\n            answered", "        if True:\n            answered"),),
        WYCENA,
        "tata nie wie, że proces czeka, aż zaloguje się w oknie efenix",
    ),
    Mutation(
        "karta bez numerów zleceń i Wykonawców",
        (Edit(EFENIX_KIND, "        _notes=_notes,\n", ""),),
        WYCENA,
        "tata widzi tylko wiersze pliku, bez numeru zlecenia i Wykonawcy, którego ma szukać w efenix",
    ),
    Mutation(
        "Logi bez śladu zleceń",
        (Edit(LOGS_OF_RUN, "efenix_orders=None if priced is None else LoggedOrder.all_of(priced)", "efenix_orders=None"),),
        WYCENA,
        "Maks nie odtworzy problemu zlecenia z Logów Uruchomienia",
    ),
    Mutation(
        "Logi bez odczytu stron efenix",
        (Edit(RUN_LOGS, "results=None if step.results is None else [LoggedResult.of(read) for read in step.results],", "results=None,"),),
        WYCENA,
        "Maks nie wie, co zwróciło szukanie zlecenia, którego efenix „nie zna” (#843)",
    ),
    Mutation(
        "zlecenie Rozliczone to znowu błąd",
        (Edit(EFENIX_CHECKS, "    settled = _is_status(hit, SETTLED_STATUS)\n", "    settled = False\n"),),
        WYCENA,
        "tata dostaje fałszywy błąd za zlecenie, które firma już rozliczyła (#821)",
    ),
    Mutation(
        "przycisk „Uzupełnij i zapisz” uzupełnia bez Przekazania",
        (Edit(EFENIX_KIND, "mode=PricingMode(start.pricing)", "mode=PricingMode.FILL"),),
        WYCENA,
        "tata wybrał zapis, a gotowe zlecenia czekają w efenix na zielony „Zapisz”, o którym myśli, że Centrum go kliknęło",
    ),
    Mutation(
        "karta bez listy zleceń przekazanych",
        (
            Edit(
                EFENIX_KIND,
                "_NOTED: Final = (OrderKind.ERROR, OrderKind.WARNING, OrderKind.FORWARDED, OrderKind.SETTLED)",
                "_NOTED: Final = (OrderKind.ERROR, OrderKind.WARNING, OrderKind.SETTLED)",
            ),
        ),
        WYCENA,
        "tata nie widzi, które zlecenia Centrum przekazało do akceptacji",
    ),
    Mutation(
        "plakietka Wyceny bez zapisu mówi „Z zapisem”",
        (Edit(BUILD, "badge:`Bez zapisu`", "badge:`Z zapisem`"),),
        WYCENA,
        "na karcie Wyceny „zapis” znaczy dwie rzeczy i tata myśli, że zlecenia są przekazane",
    ),
    Mutation(
        "etykieta „Przekazane do akceptacji” łamie się na dwie linie",
        (Edit(BUILD, "-mt-px -ml-px flex min-w-fit flex-1", "-mt-px -ml-px flex flex-1"),),
        WYCENA,
        "pasek liczb karty ma jedną etykietę w dwóch liniach, jak w #1067",
    ),
    Mutation(
        "Powiadomienie bez trybu Wyceny",
        (Edit(NOTIFICATIONS, "            pricing=card.run.pricing,\n", "            pricing=None,\n"),),
        WYCENA,
        "tata, który wraca do komputera, nie wie z Powiadomienia, czy zlecenia są już przekazane",
    ),
    Mutation(
        "„Uruchom ponownie” Wyceny startuje ją od razu",
        (Edit(BUILD, "rerun:e=>{e.pricing!==null&&e.process!==`intermax`?", "rerun:e=>{false?"),),
        WYCENA,
        "Centrum powtarza Wycenę po Zatrzymaniu, choć tata wybiera tryb przy każdym starcie (ADR 0027)",
    ),
    Mutation(
        "bez Powiadomienia o zakończonej Wycenie",
        (Edit(NOTIFICATIONS, "            *map(self._pricing, self._pricings()),\n", ""),),
        WYCENA,
        "tata, który odszedł od komputera na półtorej godziny, nie dowie się pod dzwonkiem, że Wycena się skończyła",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
