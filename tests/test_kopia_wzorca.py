"""Rozliczenie pracownika z kopii Wzorca (ADR 0008) jest takie, jak zapisane przez openpyxl, dla generowanych Wierszy danych.

Test właściciel zapisu w ``test_workbook_files.py`` sprawdza wybrane wartości i Wyróżnienia.
Granice kawałków kompresji, nietypowe teksty i liczby, generowane Wyróżnienia oraz kilka
Rozliczeń pracowników z jednego wczytanego Wzorca sprawdza skrypt skilla ``verify-kopia-wzorca``
na prawdziwym ``template_copy.py``. Reguły, zakres i postępowanie przy porażce opisuje
``.agents/skills/verify-kopia-wzorca/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
import warnings
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given, settings

CHECKER = (
    Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-kopia-wzorca" / "scripts" / "check_template_copy.py"
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_template_copy", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Części testu, które xdist rozkłada: każda porównuje co n-ty przykład swojego Wzorca, a pokrycie liczy ze wszystkich.
# Każdy Wzorzec ma osobny przebieg Hypothesis z tymi samymi przykładami w każdej części.
CZESCI = {"syntetyczny": 4, "maly": 1}


# 60 przykładów na Wzorzec: ~90 s wszystkich części razem, najdłuższa ~22 s, na Macu M4 Max; kilka razy dłużej na runnerze Windows.
@pytest.mark.dlugi
@pytest.mark.timeout(600)
@pytest.mark.parametrize(("wzorzec", "czesc"), [(wzorzec, czesc) for wzorzec, czesci in CZESCI.items() for czesc in range(czesci)])
def test_rozliczenie_pracownika_z_kopii_wzorca_jest_jak_zapisane_przez_openpyxl_dla_generowanych_wierszy_danych(
    wzorzec: str, czesc: int
) -> None:
    checker = _load_checker()
    assert sorted(CZESCI) == sorted(checker.SYNTHETIC_TEMPLATES), "każdy Wzorzec checkera ma swoje części testu"

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        # Hypothesis warns about the size of a shrunk counterexample's repr; the checker prints its own story.
        warnings.filterwarnings("ignore", message="Generating overly large repr")
        outcome = checker.run_check(template_names=(wzorzec,), part=(czesc, CZESCI[wzorzec]))

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_kopia_wzorca_sprawdza_te_same_przyklady_niezaleznie_od_modulow_i_testow_hypothesis_obok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker()
    checked: list[str] = []

    def record(run: object, case: object) -> None:
        checked.append(re.sub(r" object at 0x[0-9a-f]+", "", repr(case.workers)))  # type: ignore[attr-defined]

    def examples() -> list[str]:
        checked.clear()
        checker.run_check(shrink=False, template_names=("maly",))
        return list(checked)

    monkeypatch.setattr(checker.Run, "check", record)
    alone = examples()

    # Pełny pytest wczytuje moduły, których test uruchomiony sam nie wczytuje (#288).
    source = tmp_path / "modul_obok.py"
    source.write_text('LITERALY = ("kopia", "Wzorca", "#288", 4096, -7777, 12.5, b"bajty")\n', encoding="utf-8")
    spec = importlib.util.spec_from_file_location("modul_obok", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, spec.name, module)
    beside_module = examples()

    # Test z Hypothesis, który biegnie wcześniej w tym samym workerze, zostawia w pamięci Hypothesis stałe z modułów.
    @settings(max_examples=20, database=None, derandomize=True)
    @given(checker.data_rows())
    def other_test(row: object) -> None:
        pass

    other_test()
    after_other_test = examples()

    assert len(alone) > checker.DEFAULT_EXAMPLES
    assert beside_module == alone
    assert after_other_test == alone


def test_czesci_kopii_wzorca_porownuja_razem_kazde_rozliczenie_pracownika_raz_i_licza_pokrycie_ze_wszystkich(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_checker()
    compared: list[str] = []

    def reference(twin: Path, target: Path, rows: object, via_copy: bool) -> None:
        compared.append(re.sub(r" object at 0x[0-9a-f]+", "", repr(rows)))

    monkeypatch.setattr(checker, "_write_with_openpyxl", reference)
    monkeypatch.setattr(checker, "check_settlement", lambda *args: [])

    def run(part: tuple[int, int]) -> tuple[list[str], list[str]]:
        compared.clear()
        lines = checker.run_check(examples=10, shrink=False, template_names=("maly",), part=part).lines
        return sorted(compared), [line for line in lines if line.startswith("Wzorzec maly:")]

    whole, coverage = run((0, 1))
    parts = [run((part, 3)) for part in range(3)]

    assert len(whole) > 10
    assert sorted(rows for found, _ in parts for rows in found) == whole
    assert all(len(found) < len(whole) for found, _ in parts)
    assert [lines for _, lines in parts] == [coverage] * 3


def test_hypothesis_ma_te_sama_wersje_w_requirements_i_w_dodatku_dev() -> None:
    """Sprawdzenie sięga do ``hypothesis.internal`` (wyłącza losowanie z literałów modułów obok, #288), którego Hypothesis
    nie obiecuje między wersjami. Zadania CI z samym ``requirements.txt`` (pytest Windows, Mutation checks) i z dodatkiem
    ``dev`` mają więc dostać tę samą, dokładnie przypiętą wersję."""

    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    dev = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]["dev"]

    def pins(specifications: list[str]) -> list[str]:
        return [spec.replace(" ", "") for spec in specifications if re.match(r"hypothesis\b", spec)]

    assert pins(requirements) == pins(dev)
    assert len(pins(dev)) == 1 and "==" in pins(dev)[0]
