"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `przygotowanie-pliku-zbiorczego` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import PRZYGOTOWANIE, STOPS
from silnik_mutacji import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "odmowa w Decyzji taty jak Zatrzymanie dla taty",
        (Edit(STOPS, '        if stop.kind == "declined":\n', "        if False:\n"),),
        PRZYGOTOWANIE,
        "karta pokazuje odmowę taty jako Zatrzymanie do poprawy zamiast spokojnego „Przerwano”",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
