"""Pomiar Reguł ilości na Pliku zbiorczym wypełnionym przez tatę: liczby i teksty ``URZĄDZENIA``, bez danych zleceń."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook

from atrapy.preparation import make_preparation_fixture, register_order
from tests.fixtures.operacje import run_preparation
from atrapy.workbooks import active_worksheet

ROOT = Path(__file__).resolve().parents[1]
TUESDAY = datetime(2026, 9, 8, 9, 0)


def test_pomiar_podaje_zgodnosc_i_klasy_rozbieznosci_bez_danych_zlecen(tmp_path: Path) -> None:
    orders = [
        ("nokia zte fut", "u", "instalacja", TUESDAY),
        ("usterka", "pr", "instalacja", TUESDAY.replace(hour=17)),
        ("gniazdo", "pr", "instalacja", TUESDAY),
        ("przeniesienie", "pr", "instalacja", TUESDAY),
        ("prewencja", "u", "instalacja", TUESDAY),
        ("instalacja ręczna", "pr", "6 szt", TUESDAY),
    ]
    rows: list[dict[str, object] | None] = [
        register_order(number, started) | {"URZĄDZENIA": devices, "UMOWA": contract, "CZYNNOŚCI": activities}
        for number, (devices, contract, activities, started) in enumerate(orders, start=1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    run_preparation(fixture)
    workbook = load_workbook(fixture.collective_file_path)
    sheet = active_worksheet(workbook)
    entries: dict[str, str | float | None] = {
        "V18": " 1 ", "AM18": 1, "N19": None, "AE20": 0, "AP20": None, "Y20": 1, "O21": 1.0, "V23": 1, "AN23": None,
    }
    for cell, entry in entries.items():
        sheet[cell] = entry
    workbook.save(fixture.collective_file_path)

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "pomiar_regul_ilosci.py"), str(fixture.collective_file_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    lines = result.stdout.splitlines()
    assert lines[1:5] == [
        "wiersze danych: 6 | z regułą: 4 | bez reguły: 1 | z opisu: 1 | DATA nie jest datą: 0",
        "zgodne całe wiersze z regułą (AK, AM tylko gdy reguła ≠ 0): 1/4 (25.0%)",
        "zgodne całe wiersze z regułą, ściśle we wszystkich 16 kolumnach: 0/4 (0.0%)",
        "wiersze bez reguły zgodne w V, T, N: 1/1 (100.0%)",
    ]
    assert "N: 4/5 (80.0%) | 1 | 0" in lines
    assert lines[lines.index("-- klasy rozbieżności: 3") + 1 :][:3] == [
        "1 wierszy z regułą | N: reguła 45, tata 0 | DATA wt od 17:00 | 1× 'usterka'",
        "1 wierszy z regułą | AE: reguła 1, tata 0; AP: reguła 1, tata 0 | Y taty ≠ 0 | 1× 'gniazdo'",
        "1 wierszy z regułą | V: reguła 6, tata 1; AN: reguła 6, tata 0 | CZYNNOŚCI z liczbą | 1× 'instalacja ręczna'",
    ]
    assert "1× 'przeniesienie' | O=1 → 1" in lines
    assert "1× 'prewencja' | nic → 1" in lines
    assert lines[-1] == "-- wiersze z regułą z wpisem taty w kolumnie spoza porównania: Y=1 AM=1"
    assert "SYN" not in result.stdout
