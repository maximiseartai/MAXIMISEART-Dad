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

from cele_mutacji_centrum import EFENIX_BROWSER, EFENIX_RUN, RUN_LOGS, RUN_VIEW, WYCENA
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "bez przycisku dla okresu z Plikiem zbiorczym przygotowanym",
        (Edit(EFENIX_RUN, 'frozenset({"collective_file_prepared", "worker_settlements_ready"})', 'frozenset({"worker_settlements_ready"})'),),
        WYCENA,
        "tata nie może wycenić okresu zaraz po Uzupełnieniu pliku zbiorczego",
    ),
    Mutation(
        "okno nie mówi, że czeka na logowanie",
        (Edit(EFENIX_BROWSER, "        with login():\n            deadline", "        if True:\n            deadline"),),
        WYCENA,
        "tata nie wie, że proces czeka, aż zaloguje się w oknie efenix",
    ),
    Mutation(
        "karta bez numerów zleceń i Wykonawców",
        (Edit(RUN_VIEW, "    _notes=_pricing_notes,\n", ""),),
        WYCENA,
        "tata widzi tylko wiersze pliku, bez numeru zlecenia i Wykonawcy, którego ma szukać w efenix",
    ),
    Mutation(
        "Logi bez śladu zleceń",
        (Edit(RUN_LOGS, "efenix_orders=LoggedOrder.all_of(engine_summary) if", "efenix_orders=None if"),),
        WYCENA,
        "Maks nie odtworzy problemu zlecenia z Logów Uruchomienia",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
