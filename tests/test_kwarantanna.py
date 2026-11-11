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
import os
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


def test_porazka_testu_z_kwarantanny_drukuje_w_logu_koniec_powodu_a_przejscie_nic(tmp_path: Path) -> None:
    """Pod xdist, jak zadanie pytest w CI: porażka testu z kwarantanny jest xfail, więc bez podsumowania z
    ``tests/conftest.py`` log miałby tylko liczbę ``xfailed`` i diagnostyka z komunikatu by przepadła (#1008)."""

    # Jak tests/conftest.py: test z kwarantanny jest xfail(strict=False) i ma własność kwarantanny; zwykły xfail jej nie ma.
    (tmp_path / "conftest.py").write_text(
        "import pytest\n\nfrom tests.conftest import pytest_terminal_summary\n\n\n"
        "def pytest_itemcollected(item):\n"
        "    item.add_marker(pytest.mark.xfail(strict=False))\n"
        "    if item.name != 'test_zwykly_xfail':\n"
        f"        item.user_properties.append(({niestabilne_testy.WLASNOSC!r}, 'kwarantanna #1 do 2026-11-01'))\n",
        encoding="utf-8",
    )
    (tmp_path / "test_x.py").write_text(
        "def test_pada():\n"
        "    raise AssertionError('POCZATEK_KOMUNIKATU ' + 'x' * 20_000 + '\\nZatrzymanie EFENIX_X, ostatnie żądanie POST /a')\n\n\n"
        "def test_przechodzi():\n    pass\n\n\n"
        "def test_zwykly_xfail():\n    raise AssertionError('ZWYKLY_XFAIL')\n",
        encoding="utf-8",
    )

    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-n", "2", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), "test_x.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert [line for line in run.stdout.splitlines() if line.startswith("KWARANTANNA |")] == [
        "KWARANTANNA | test_x.py::test_pada padł (call), kwarantanna #1 do 2026-11-01:"
    ], run.stdout
    assert "Zatrzymanie EFENIX_X, ostatnie żądanie POST /a" in run.stdout
    assert "(początek ucięty, " in run.stdout
    assert "POCZATEK_KOMUNIKATU" not in run.stdout
    assert "ZWYKLY_XFAIL" not in run.stdout
