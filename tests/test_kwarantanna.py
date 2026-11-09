"""Strażnik kwarantanny niestabilnych testów (``tests/fixtures/kwarantanna.py``, ADR 0020).

Wpis kwarantanny ma numer issue ``Flaky test: <test>`` i ostatni dzień kwarantanny, najwyżej 7 dni od dziś, i nie wygasł,
a jego test istnieje. Maks zgodził się 26.10 z góry na każdy taki wpis (ADR 0020, decyzja Q15), więc wpis nie
potrzebuje osobnej zgody z ``AGENTS.md``, jakiej wymaga wyjątek z terminem. Wpis bez issue, z dłuższym terminem,
wygasły albo bez testu czerwieni ten test, a z nim ``Required CI status`` każdego PR, bo test biegnie przy każdym
``tools/szybko.py`` i w każdej bramce PR.

Granica: czy issue istnieje i dotyczy tego testu, sprawdza tylko przegląd, bo testy nie pytają GitHuba.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import importlib
from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

from tests import conftest
from tests.fixtures.kwarantanna import KWARANTANNA, Kwarantanna

import niestabilne_testy

ROOT = Path(__file__).resolve().parents[1]

NAJDLUZEJ = timedelta(days=7)


def problemy(wpisy: Mapping[str, Kwarantanna], dzis: date) -> list[str]:
    found = [f"{test}: bez numeru issue" for test, wpis in wpisy.items() if wpis.issue < 1]
    found += [f"{test}: termin {wpis.do} dalej niż {NAJDLUZEJ.days} dni od {dzis}" for test, wpis in wpisy.items() if wpis.do - dzis > NAJDLUZEJ]
    found += [f"{test}: kwarantanna wygasła {wpis.do}" for test, wpis in wpisy.items() if wpis.do < dzis]
    pliki = sorted({test.partition("::")[0] for test in wpisy if (ROOT / test.partition("::")[0]).is_file()})
    istnieja: set[str] = set()
    if pliki:
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-n", "0", *pliki],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        istnieja = set(collected.stdout.splitlines())
    return found + [f"{test}: nie ma takiego testu" for test in wpisy if test not in istnieja]


def test_wpisy_kwarantanny_maja_issue_termin_najwyzej_7_dni_i_istniejacy_test() -> None:
    assert problemy(KWARANTANNA, datetime.now().astimezone().date()) == []


@pytest.mark.parametrize(
    ("wpis", "problem"),
    [
        (Kwarantanna(0, date(2026, 10, 30)), "bez numeru issue"),
        (Kwarantanna(12, date(2026, 11, 3)), "termin 2026-11-03 dalej niż 7 dni od 2026-10-26"),
        (Kwarantanna(12, date(2026, 10, 25)), "kwarantanna wygasła 2026-10-25"),
    ],
)
def test_wpis_bez_issue_za_dlugi_albo_wygasly_czerwieni_straznika(wpis: Kwarantanna, problem: str) -> None:
    test = "tests/test_kwarantanna.py::test_wpisy_kwarantanny_maja_issue_termin_najwyzej_7_dni_i_istniejacy_test"

    assert problemy({test: wpis}, date(2026, 10, 26)) == [f"{test}: {problem}"]


def test_wpis_testu_ktorego_nie_ma_czerwieni_straznika_a_wazny_wpis_nie() -> None:
    istnieje = "tests/test_kwarantanna.py::test_wpis_bez_issue_za_dlugi_albo_wygasly_czerwieni_straznika[wpis0-bez numeru issue]"
    brak = "tests/test_kwarantanna.py::test_ktorego_nie_ma"
    bez_pliku = "tests/test_nie_ma_pliku.py::test_x"
    wpisy = {istnieje: Kwarantanna(12, date(2026, 11, 2)), brak: Kwarantanna(13, date(2026, 10, 26)), bez_pliku: Kwarantanna(14, date(2026, 10, 27))}

    assert problemy(wpisy, date(2026, 10, 26)) == [f"{brak}: nie ma takiego testu", f"{bez_pliku}: nie ma takiego testu"]


def test_wydanie_czyta_kwarantanne_z_pliku_ktory_importuje_conftest() -> None:
    """``tools/wydanie.py`` czyta ``KWARANTANNA`` z Gita spod ``PLIK_KWARANTANNY``; inny plik dałby każdemu commitowi
    stan sprzed kwarantanny i Wydanie bez jej zapisu."""

    plik = niestabilne_testy.PLIK_KWARANTANNY
    modul = importlib.import_module(".".join(PurePosixPath(plik).with_suffix("").parts))
    uzywana = vars(conftest)["KWARANTANNA"]

    assert modul.KWARANTANNA is uzywana
    assert niestabilne_testy.ma_wpisy((ROOT / plik).read_text(encoding="utf-8")) == bool(uzywana)
