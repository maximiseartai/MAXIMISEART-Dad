from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import DIAGNOSIS, DIAGNOZA, ORDER_REGISTER_ROUTER, SETTINGS_OWNER
from silnik_mutacji import Edit, Mutation, check_all

OPIS = """Show that the drive of verify-centrum-rozliczen fails on broken variants of its `diagnoza` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

MUTATIONS = (
    Mutation(
        "„Otwórz Rejestr zleceń” niczego nie otwiera",
        (Edit(ORDER_REGISTER_ROUTER, "        platform.open_path(register)\n", "        pass\n"),),
        DIAGNOZA,
        "tata klika „Otwórz Rejestr zleceń” przy Zatrzymaniu do poprawy, a Excel się nie otwiera",
    ),
    Mutation(
        "zła Lista Wykonawców przechodzi sprawdzenie Diagnozy",
        (Edit(DIAGNOSIS, "    problem = workers.problem()\n    if problem is None:\n", "    problem = workers.problem()\n    if True:\n"),),
        DIAGNOZA,
        "tata widzi w Diagnozie, że Lista Wykonawców jest dobra, choć nie da się jej użyć",
    ),
    Mutation(
        "Lista Wykonawców bez odczytu startuje proces na pustej liście",
        (
            Edit(
                SETTINGS_OWNER,
                "                raise refusal.workers_unusable(None)\n",
                "                return WorkerList(())\n",
            ),
        ),
        DIAGNOZA,
        "proces startuje bez Wykonawców i zatrzymuje się na każdym jako nieznanym zamiast odmowy ze zdaniem",
    ),

)


if __name__ == "__main__":
    argparse.ArgumentParser(description=OPIS).parse_args()
    raise SystemExit(check_all(MUTATIONS))
