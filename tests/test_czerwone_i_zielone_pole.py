from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.colors import Color
from openpyxl.styles.proxy import StyleProxy
from openpyxl.utils import get_column_letter
import pytest

from rozliczenia.activity_legend import FillColour
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.run_context import RunContext

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_TEMPLATE, write_synthetic_templates
from atrapy.preparation import PERIOD, make_preparation_fixture, register_order
from tests.fixtures.operacje import run_preparation
from atrapy.settlement import worker_list
from atrapy.workbooks import active_worksheet, hyperlinks, marked_for_copy, refused_by_copy, written_by_copy

RED, GREEN = "FFFF0000", "FF92D050"
DARK_RED, OTHER_GREEN = "FFC00000", "FF99FF66"
LINK, GREEN_LINK = "https://przyklad.invalid/pole", "https://przyklad.invalid/zielone"
ORDERS = [("spawpg rt2", "dekoder"), ("inst20m", "gniazdo"), ("montaż", "technicolor"), ("montaż", "dekoder")]
BY_HAND: dict[str, tuple[str | int | None, PatternFill]] = {
    "Y19": (1, PatternFill("solid", fgColor=GREEN)),
    "AP19": (1, PatternFill("solid", fgColor=GREEN)),
    "AK20": (1, PatternFill("solid", fgColor=RED)),
    "P20": (2, PatternFill("solid", fgColor=RED)),
    "AO20": (None, PatternFill("solid", fgColor=GREEN)),
    "AN21": (1, PatternFill("solid", fgColor=Color(indexed=2))),
    "AL21": (1, PatternFill("solid", fgColor=DARK_RED)),
    "AJ21": (1, PatternFill("solid", fgColor=OTHER_GREEN)),
    "B21": ("syntetyczny adres SYN-004", PatternFill("solid", fgColor=RED)),
    "D21": ("dekoder", PatternFill("solid", fgColor=RED)),
    "AT21": ("uwaga taty", PatternFill("solid", fgColor=RED)),
    "AR21": (40, PatternFill("solid", fgColor=GREEN)),
    "AC21": (3, PatternFill("solid", fgColor=GREEN)),
}
FOR_WORKER = {
    "AS18": None,
    "AM18": None,
    "AF18": 1,
    "Y19": 1,
    "AP19": 1,
    "AK20": None,
    "P20": None,
    "AO20": 1,
    "AN21": None,
    "AC21": 1,
}
KEPT_FILLS = {"AL21": DARK_RED, "AJ21": OTHER_GREEN, "B21": RED, "D21": RED, "AT21": RED, "AR21": GREEN}


def _collective_file(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    start = datetime(2026, 9, 8, 8, 0)
    rows: list[dict[str, object] | None] = [
        register_order(number, start + timedelta(minutes=number)) | {"URZĄDZENIA": devices, "CZYNNOŚCI ZREALIZOWANE": completed}
        for number, (completed, devices) in enumerate(ORDERS, start=1)
    ]
    templates = write_synthetic_templates(tmp_path / "wzorce")
    (tmp_path / "okres").mkdir()
    fixture = replace(
        make_preparation_fixture(tmp_path / "okres", rows),
        internal_template_path=templates / INTERNAL_TEMPLATE,
        collective_template_path=templates / COLLECTIVE_TEMPLATE,
    )
    run_preparation(fixture)
    workbook = load_workbook(fixture.collective_file_path)
    try:
        sheet = active_worksheet(workbook)
        prepared = {reference: sheet[reference].value for reference in BY_HAND}
        for reference, (value, fill) in BY_HAND.items():
            sheet[reference] = value
            sheet[reference].fill = fill
        sheet["P20"].font = Font(bold=True)
        sheet["P20"].hyperlink = LINK
        sheet["AC21"].hyperlink = GREEN_LINK
        workbook.save(fixture.collective_file_path)
    finally:
        workbook.close()
    return fixture.collective_file_path, templates / WORKER_TEMPLATE, prepared


def _cells(path: Path) -> dict[str, tuple[object, str | None, str | None]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return {
            f"{get_column_letter(column)}{row}": (cell.value, cell.fill.patternType, _colour(cell.fill))
            for row in range(18, 22)
            for column in range(1, 47)
            for cell in (sheet.cell(row, column),)
        }
    finally:
        workbook.close()


def _colour(fill: StyleProxy) -> str | None:
    if fill.patternType is None:
        return None
    colour = fill.fgColor
    return {"rgb": colour.rgb, "indexed": f"indeks {colour.indexed}", "theme": "theme"}.get(colour.type)


@pytest.mark.parametrize("route", ["kopia", "openpyxl"])
def test_czerwone_pole_jest_puste_a_zielone_ma_1_i_oba_sa_biale_w_rozliczeniu_pracownika_a_plik_zbiorczy_bez_zmian(
    tmp_path: Path, route: str
) -> None:
    collective, worker_template, prepared = _collective_file(tmp_path)
    assert (prepared["AP19"], prepared["AK20"]) == (1, 1), "warunek: gniazdo i technicolor dają z Reguł ilości Ilość tylko dla INEA"
    if route == "kopia":
        marked_for_copy(worker_template)
    else:
        refused_by_copy(worker_template)
    before = collective.read_bytes()
    source = _cells(collective)
    assert {key: source[key][2] for key in FOR_WORKER} == {
        "AS18": RED, "AM18": RED, "AF18": GREEN, "Y19": GREEN, "AP19": GREEN, "AK20": RED, "P20": RED, "AO20": GREEN,
        "AN21": "indeks 2", "AC21": GREEN,
    }, "warunek: kolory legendy z Przygotowania i kolory taty"
    assert (source["AB18"][0], source["AS18"][0], source["AM18"][0], source["AP19"][0], source["AK20"][0]) == (1, 70, 1, 1, 1)
    assert source["AC21"][0] == 3
    assert source["N21"][2] == "theme", "warunek: tło Wzorca pliku zbiorczego taty w N"

    summary = run_settlements(SettlementInputs(collective, worker_list(), worker_template), RunContext())

    written = PeriodFolder.from_collective_file(collective).worker_settlements / f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx"
    assert written_by_copy(written) is (route == "kopia")
    settlement = _cells(written)
    assert {key: settlement[key][0] for key in FOR_WORKER} == FOR_WORKER
    assert {key: settlement[key][1] for key in FOR_WORKER} == dict.fromkeys(FOR_WORKER), "Czerwone i Zielone pole są białe"
    assert {key: value[0] for key, value in settlement.items() if key not in FOR_WORKER} == {
        key: value[0] for key, value in source.items() if key not in FOR_WORKER
    }
    assert {key: settlement[key][2] for key in (*KEPT_FILLS, "N21")} == {**KEPT_FILLS, "N21": "theme"}
    workbook = load_workbook(written)
    try:
        assert active_worksheet(workbook)["P20"].font.b, "pogrubienie taty zostaje"
    finally:
        workbook.close()
    links = hyperlinks(written)
    assert ("P20" in links, links.get("AC21")) == (False, GREEN_LINK), "Czerwone pole bez Hiperłącza, Zielone z nim"
    assert dict(summary.inea_only_cleared) == {"AK": 1, "AP": 0}, "zielone AP przy gniazdo ma 1, więc się nie liczy"
    assert collective.read_bytes() == before
    assert isinstance(summary.orders, tuple)
    first, *_ = summary.orders
    assert (dict(first.fills), first.amount, first.quantity("AM")) == (
        {"AF": FillColour.GREEN, "AM": FillColour.RED, "AS": FillColour.RED},
        70,
        1,
    ), "Kontrola ilości widzi Plik zbiorczy"
