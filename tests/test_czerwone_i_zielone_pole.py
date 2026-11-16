"""Czerwone pole i Zielone pole w Rozliczeniu pracownika (ADR 0039, GLOSSARY): czerwone puste, zielone z 1, oba białe.

Plik zbiorczy powstaje z Przygotowania pliku zbiorczego z legendą z Wydania na syntetycznym Rejestrze i Wzorcach w
kształcie Wzorców taty, a potem „tata” koloruje w nim pola ręcznie. Oczekiwane wartości pochodzą z odpowiedzi taty z
16.11.2026 (ADR 0039): pole z czerwonym wypełnieniem traci liczbę, w pole z zielonym idzie 1, a oba są białe; kolory
spoza legendy i pola spoza Ilości usług i ``AS`` przechodzą jak każde Wyróżnienie.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.colors import Color
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
"""Kolory Czerwonego pola i Zielonego pola z GLOSSARY: czerwony i jasnozielony ze standardowych kolorów Excela."""
DARK_RED, OTHER_GREEN = "FFC00000", "FF99FF66"
LINK = "https://przyklad.invalid/pole"
ORDERS = [("spawpg rt2", "dekoder"), ("inst20m", "gniazdo"), ("montaż", "technicolor"), ("montaż", "dekoder")]
"""``CZYNNOŚCI ZREALIZOWANE`` i ``URZĄDZENIA`` zleceń w wierszach 18–21: ``spawpg rt2`` daje z legendy 1 w AB, 70 w
czerwonym AS, 1 w czerwonym AM i zielone AF; ``gniazdo`` daje z Reguł ilości 1 w AP, a ``technicolor`` 1 w AK, oba
Ilości tylko dla INEA."""
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
}
"""Pola pokolorowane przez tatę: komórka → (wartość, wypełnienie). Indeks 2 palety Excela to ten sam czerwony."""
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
}
"""Czerwone pole i Zielone pole → wartość w Rozliczeniu pracownika: Zielone pole AP przy ``gniazdo`` ma 1, choć Reguła
ilości zostawia tę komórkę pustą, bo zielony kolor taty mówi, że Wykonawca dostaje tę pozycję w tym zleceniu."""
KEPT_FILLS = {"AL21": DARK_RED, "AJ21": OTHER_GREEN, "B21": RED, "D21": RED, "AT21": RED, "AR21": GREEN}


def _collective_file(tmp_path: Path) -> tuple[Path, Path]:
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
        for reference, (value, fill) in BY_HAND.items():
            sheet[reference] = value
            sheet[reference].fill = fill
        sheet["P20"].font = Font(bold=True)
        sheet["P20"].hyperlink = LINK
        workbook.save(fixture.collective_file_path)
    finally:
        workbook.close()
    return fixture.collective_file_path, templates / WORKER_TEMPLATE


def _cells(path: Path) -> dict[str, tuple[object, str | None, str | None]]:
    """Komórki A:AT wierszy 18–21: wartość, rodzaj wypełnienia i kolor wypełnienia (RGB albo ``theme``)."""

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


def _colour(fill: PatternFill) -> str | None:
    if fill.patternType is None:
        return None
    colour = fill.fgColor
    return {"rgb": colour.rgb, "indexed": f"indeks {colour.indexed}", "theme": "theme"}.get(colour.type)


@pytest.mark.parametrize("route", ["kopia", "openpyxl"])
def test_czerwone_pole_jest_puste_a_zielone_ma_1_i_oba_sa_biale_w_rozliczeniu_pracownika_a_plik_zbiorczy_bez_zmian(
    tmp_path: Path, route: str
) -> None:
    collective, worker_template = _collective_file(tmp_path)
    if route == "kopia":
        marked_for_copy(worker_template)
    else:
        refused_by_copy(worker_template)
    before = collective.read_bytes()
    source = _cells(collective)
    assert {key: source[key][2] for key in FOR_WORKER} == {
        "AS18": RED, "AM18": RED, "AF18": GREEN, "Y19": GREEN, "AP19": GREEN, "AK20": RED, "P20": RED, "AO20": GREEN,
        "AN21": "indeks 2",
    }, "warunek: kolory legendy z Przygotowania i kolory taty"
    assert (source["AB18"][0], source["AS18"][0], source["AM18"][0], source["AP19"][0], source["AK20"][0]) == (1, 70, 1, 1, 1)
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
    assert "P20" not in hyperlinks(written)
    assert collective.read_bytes() == before
    assert isinstance(summary.orders, tuple)
    first, *_ = summary.orders
    assert (dict(first.fills), first.amount, first.quantity("AM")) == (
        {"AF": FillColour.GREEN, "AM": FillColour.RED, "AS": FillColour.RED},
        70,
        1,
    ), "Kontrola ilości widzi Plik zbiorczy"
