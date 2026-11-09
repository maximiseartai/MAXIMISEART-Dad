"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `diagnoza` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import DIAGNOZA, SETTINGS_ROUTER, WORKER_CONFIG
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "„Otwórz Rejestr zleceń” niczego nie otwiera",
        (Edit(SETTINGS_ROUTER, "        platform.open_path(register)\n", "        pass\n"),),
        DIAGNOZA,
        "tata klika „Otwórz Rejestr zleceń” przy Zatrzymaniu do poprawy, a Excel się nie otwiera",
    ),
    Mutation(
        "Konfiguracja wykonawców bez dostępu jest brakującym plikiem",
        (
            Edit(
                WORKER_CONFIG,
                '    return WorkerConfigError("missing" if file_state(config_path) == "missing" else "inaccessible")\n',
                '    return WorkerConfigError("missing")\n',
            ),
        ),
        DIAGNOZA,
        "tata widzi „Nie można odczytać konfiguracji wykonawców.” zamiast Komunikatu, że plik jest teraz niedostępny",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
