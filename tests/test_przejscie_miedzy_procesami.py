"""Plik zbiorczy z Przygotowania pliku zbiorczego jest wejściem Przebiegu rozliczeń bez ręcznych zmian."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from rozliczenia.activity_legend import FILL_COLUMNS, ActivityCode, ActivityLegend, CellFill, FillColour
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.period_folder import PeriodFolder
from rozliczenia import tool_files
from rozliczenia import quantity_check
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.run_context import RunContext

from atrapy.preparation import PERIOD, make_preparation_fixture
from atrapy.preparation import cell_values, collective_row, register_order
from tests.fixtures.operacje import run_preparation
from atrapy.settlement import worker_list, write_template
from atrapy.workbooks import active_worksheet


def test_plik_zbiorczy_z_przygotowania_daje_rozliczenia_pracownikow_z_ich_zleceniami_skutecznymi(
    tmp_path: Path,
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)

    preparation = run_preparation(fixture)
    settlement = run_settlements(
        SettlementInputs(preparation.collective_file, worker_list(), worker_template),
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
    collective_file_row_of = {
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
        SettlementInputs(preparation.collective_file, worker_list(), worker_template),
        RunContext(),
    )
    result = quantity_check.check(settlement.orders, settlement.quantity_rules, settlement.activity_legend)

    assert isinstance(result, quantity_check.QuantityCheck)
    assert (result.rows, result.compared, result.from_description, result.unruled_rows, result.undated) == (
        16,
        9,
        3,
        4,
        0,
    )
    assert result.difference_count == 0


def test_legenda_kolorujaca_kazda_kolumne_nie_daje_roznic_koloru_na_tle_wzorca_taty(tmp_path: Path) -> None:
    # Wzorzec pliku zbiorczego ma tło Wzorca taty w N:V, X i AI przygotowanych wierszy; ``każdykolor`` koloruje każdą
    # kolumnę, którą może wypełnić legenda, więc w wierszach z innym kodem i bez kodu Kontrola widzi tam tło Wzorca.
    every = ActivityCode("każdykolor", ("każdykolor",), fills=tuple(CellFill(column, FillColour.GREEN) for column in FILL_COLUMNS))
    legend = ActivityLegend((*DEFAULT_ACTIVITY_LEGEND.codes, every))
    completed = ("każdykolor", "inst20m", "spawpg", "montaż")
    rows: list[dict[str, object] | None] = [
        register_order(number, TUE.replace(hour=10, minute=number)) | {"CZYNNOŚCI ZREALIZOWANE": text}
        for number, text in enumerate(completed, start=1)
    ]
    fixture = make_preparation_fixture(tmp_path, rows)
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)

    preparation = run_preparation(fixture, legend=legend)
    settlement = run_settlements(
        SettlementInputs(preparation.collective_file, worker_list(), worker_template, activity_legend=legend),
        RunContext(),
    )
    result = quantity_check.check(settlement.orders, settlement.quantity_rules, settlement.activity_legend)

    workbook = load_workbook(preparation.collective_file)
    try:
        sheet = active_worksheet(workbook)
        backgrounds = {
            str(sheet.cell(row, 11).value): {get_column_letter(column) for column in range(14, 47) if sheet.cell(row, column).fill.patternType}
            for row in range(18, 22)
        }
    finally:
        workbook.close()
    assert backgrounds["inst20m"] >= {"N", "V", "X", "AI"}, "warunek: wiersz bez koloru legendy ma tło Wzorca taty"
    assert isinstance(result, quantity_check.QuantityCheck)
    assert (result.coded, result.coded_matching, result.legend_difference_count) == (3, 3, 0)
