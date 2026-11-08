"""Run the Reguły ilości conformance test: every line of Dad's instruction through Przygotowanie pliku zbiorczego.

``check_quantity_rules_mutations.py`` breaks one rule at a time and expects this check to fail. The test runs by its
path in a pytest of this process, as a skill script does not import a module of ``tests/``
(``tests/test_granice_importow.py::test_kod_spoza_testow_nie_importuje_testow``); a renamed or missing test is a
pytest failure, not a pass. Ends with ``ILOŚCI USŁUG OK`` or ``ILOŚCI USŁUG FAIL``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFORMANCE = REPO_ROOT / "tests" / "test_ilosci_uslug.py"
TEST = "test_plik_zbiorczy_ma_ilosci_uslug_z_kazdej_linii_instrukcji_taty"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    code = pytest.main(["-q", "-p", "no:cacheprovider", "--rootdir", str(REPO_ROOT), f"{CONFORMANCE}::{TEST}"])
    print("ILOŚCI USŁUG OK" if code == pytest.ExitCode.OK else f"ILOŚCI USŁUG FAIL | pytest {int(code)}")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
