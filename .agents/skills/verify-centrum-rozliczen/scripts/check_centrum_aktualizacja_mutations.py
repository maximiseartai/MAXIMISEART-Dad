"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `aktualizacja` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import AKTUALIZACJA, BUILD, TOOL_UPDATES
from silnik_mutacji import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "wynik AKTUALNA zostaje, gdy najnowsze Wydanie to commit narzędzia",
        (
            Edit(
                TOOL_UPDATES,
                "            if newest is not None and newest != judged and self._view is view:\n",
                "            if newest is not None and newest != judged and newest.newest != self._commit() and self._view is view:\n",
            ),
        ),
        AKTUALIZACJA,
        "karta mówi „Masz najnowszą wersję.” o Wydaniu, którego Centrum już nie zna",
    ),
    Mutation(
        "„ok” od opiekuna bez porównania z działającym commitem",
        (
            Edit(
                TOOL_UPDATES,
                "        if result.code == UPDATED and running is not None and running != result.after:\n",
                "        if False:\n",
            ),
        ),
        AKTUALIZACJA,
        "stara wersja po cofnięciu nie pokazuje porażki, gdy w pliku wyniku zostało „ok”",
    ),
    Mutation(
        "stan aktualizacji czyta tylko karta przeładowana po ponownym starcie",
        (Edit(BUILD, "Promise.all([Jg(),e?qg():null])", "e&&Promise.all([Jg(),e?qg():null])"),),
        AKTUALIZACJA,
        "po starcie ze skrótu Okresy nie mówią, że nowa wersja nie wystartowała",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
