"""Plik zbiorczy z Przygotowania pliku zbiorczego jest wejściem Przebiegu rozliczeń bez ręcznych zmian."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rozliczenia.period_folder import PeriodFolder
from rozliczenia import tool_files
from rozliczenia import quantity_check
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.run_context import RunContext

from atrapy.preparation import PERIOD, make_preparation_fixture
from atrapy.preparation import cell_values, collective_row, register_order
from tests.fixtures.operacje import run_preparation
from atrapy.settlement import write_template


def test_plik_zbiorczy_z_przygotowania_daje_rozliczenia_pracownikow_z_ich_zleceniami_skutecznymi(
    tmp_path: Path,
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)

    preparation = run_preparation(fixture)
    settlement = run_settlements(
        SettlementInputs(preparation.collective_file, fixture.config_path, worker_template),
        RunContext(),
    )

    assert settlement.warnings == []
    assert [(result.worker_name, result.status, result.rows) for result in settlement.results] == [
        ("Adrian Testowy", "ZAPISANO", 1),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "ZAPISANO", 1),
    ]
    target_directory = PeriodFolder.from_collective_file(fixture.collective_file_path).worker_settlements
    expected_rows = {
        "Adrian Testowy": collective_row(2, datetime(2026, 9, 8, 0, 0), "tak", "adrian.testowy"),
        "Darek Fikcyjny": collective_row(6, datetime(2026, 9, 14, 18, 30), "TAK", "dariusz.fikcyjny2"),
        "Kamil Syntetyczny": collective_row(4, datetime(2026, 9, 12, 12, 0), " Tak ", "kamil.syntetyczny"),
    }
    assert sorted(path.name for path in target_directory.iterdir()) == sorted(
        f"Rozliczenie {PERIOD} - {name}.xlsx" for name in expected_rows
    )
    collective_file_rows = cell_values(preparation.collective_file, min_row=18, max_row=20, min_col=1, max_col=46)
    collective_file_row_of = {  # Wiersze danych A:AT Pliku zbiorczego, w kolejności Rejestru zleceń
        "Adrian Testowy": collective_file_rows[0],
        "Kamil Syntetyczny": collective_file_rows[1],
        "Darek Fikcyjny": collective_file_rows[2],
    }
    for name, expected_row in expected_rows.items():
        settlement_file = target_directory / f"Rozliczenie {PERIOD} - {name}.xlsx"
        assert cell_values(settlement_file, min_row=18, max_row=19, min_col=1, max_col=11) == [
            expected_row,
            (None,) * 11,
        ]
        # Przebieg rozliczeń kopiuje cały Wiersz danych A:AT po pozycji kolumn.
        assert cell_values(settlement_file, min_row=18, max_row=18, min_col=1, max_col=46) == [
            collective_file_row_of[name]
        ]


TUE, FRI, SAT = datetime(2026, 9, 8), datetime(2026, 9, 11), datetime(2026, 9, 12)

# Treść zlecenia w Rejestrze w typach komórek, które zostawia tata: liczby, daty, puste komórki, spacje, wielkie litery.
ORDER_CONTENTS: list[dict[str, object]] = [
    {"UMOWA": 12345, "URZĄDZENIA": "nokia zte", "CZYNNOŚCI": "instalacja", "DATA GODZ. POCZ.": TUE.replace(hour=9)},
    {"UMOWA": " U 77 ", "URZĄDZENIA": "  Nokia ZTEXG,  2* FUT ", "CZYNNOŚCI": None},
    {"UMOWA": None, "URZĄDZENIA": "usterka", "DATA GODZ. POCZ.": FRI.replace(hour=17, minute=0, second=59)},
    {"UMOWA": 2.5, "URZĄDZENIA": "usterka hurt", "DATA GODZ. POCZ.": FRI.replace(hour=16, minute=59, second=59)},
    {"UMOWA": SAT, "URZĄDZENIA": "usterka wew", "DATA GODZ. POCZ.": SAT.date()},
    {"URZĄDZENIA": "instalacja ręczna", "CZYNNOŚCI": 7},
    {"URZĄDZENIA": "wizja", "CZYNNOŚCI": "  6szt "},
    {"URZĄDZENIA": "instalacja ręczna", "CZYNNOŚCI": TUE},
    {"URZĄDZENIA": 42, "CZYNNOŚCI": 3.0},
    {"URZĄDZENIA": 0.1 + 0.2},
    {"URZĄDZENIA": None},
    {"URZĄDZENIA": "   "},
    {"URZĄDZENIA": "Prewencja"},
    {"URZĄDZENIA": True, "UMOWA": False},
    {"URZĄDZENIA": "gateway\nwifi6extra", "UMOWA": "u\tdruk"},
    {"URZĄDZENIA": "nokia zte przeniesienie", "UMOWA": "=1+1"},
]


def test_swiezo_przygotowany_plik_zbiorczy_daje_kontrole_ilosci_bez_roznic(tmp_path: Path) -> None:
    rows: list[dict[str, object] | None] = [
        register_order(number, TUE.replace(hour=10, minute=number)) | content
        for number, content in enumerate(ORDER_CONTENTS, start=1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)

    preparation = run_preparation(fixture)
    settlement = run_settlements(
        SettlementInputs(preparation.collective_file, fixture.config_path, worker_template),
        RunContext(),
    )
    result = quantity_check.check(settlement.orders)

    assert isinstance(result, quantity_check.QuantityCheck)
    assert (result.rows, result.compared, result.from_description, result.unruled_rows, result.undated) == (
        16,
        9,
        3,
        4,
        0,
    )
    assert result.difference_count == 0
