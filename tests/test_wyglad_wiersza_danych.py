from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import cast

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles import Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia.period_folder import PeriodFolder
from rozliczenia import tool_files
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.highlights import PLAIN, Highlights
from rozliczenia.row_look import GENERAL, RowLook
from rozliczenia.run_context import RunContext

from atrapy.preparation import (
    REGISTER_DATE_FORMAT,
    default_register_rows,
    make_preparation_fixture,
)
from tests.fixtures.operacje import run_preparation
from tests.fixtures.wyglad_komorek import wyglad, wyglady
from tests.fixtures.znane_luki import wymaga_ruff
from atrapy.pliki_taty import ADDRESS_COLUMN, COLLECTIVE_HEADERS
from atrapy.settlement import worker_list, write_template
from tests.fixtures.benchmark import WORKER_TEMPLATE, write_synthetic_templates
from atrapy.workbooks import LEFTOVER_DATE_FORMAT, LEFTOVER_ROW_HEIGHT, active_worksheet, leave_data_row_leftovers

RED = "FFFF0000"
_SPREADSHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DATE_COLUMN = COLLECTIVE_HEADERS.index("DATA") + 1
COMPLETED_ACTIVITIES = get_column_letter(COLLECTIVE_HEADERS.index("CZYNNOŚCI ZREALIZOWANE") + 1)
MULTILINE = "montaż\ndemontaż"
LEFTOVER_ROWS = 6


@dataclass(frozen=True)
class WrittenFile:
    path: Path
    template: Path
    header_row: int
    rows: range
    look_columns: int


@dataclass(frozen=True)
class Chain:
    internal: WrittenFile
    collective: WrittenFile
    worker: WrittenFile


def _chain(tmp_path: Path) -> Chain:
    rows = default_register_rows()
    order = rows[2]
    assert order is not None and order["ADRES"] == "syntetyczny adres SYN-002"
    order["CZYNNOŚCI ZREALIZOWANE"] = MULTILINE
    fixture = make_preparation_fixture(tmp_path, rows)
    _paint_register_address(fixture.register_path, row=4, color=RED)
    leave_data_row_leftovers(fixture.internal_template_path, first_row=2, rows=LEFTOVER_ROWS, columns=13)
    leave_data_row_leftovers(fixture.collective_template_path, first_row=18, rows=LEFTOVER_ROWS, columns=12)
    worker_template = tmp_path / tool_files.WORKER_TEMPLATE.name
    write_template(worker_template)
    leave_data_row_leftovers(worker_template, first_row=18, rows=LEFTOVER_ROWS, columns=12)

    run_preparation(fixture)
    run_settlements(SettlementInputs(fixture.collective_file_path, worker_list(), worker_template), RunContext())

    worker = PeriodFolder.from_collective_file(fixture.collective_file_path).worker_settlement("Adrian Testowy")
    return Chain(
        internal=WrittenFile(fixture.internal_settlement_path, fixture.internal_template_path, 1, range(2, 6), 13),
        collective=WrittenFile(fixture.collective_file_path, fixture.collective_template_path, 17, range(18, 21), 12),
        worker=WrittenFile(worker, worker_template, 17, range(18, 19), 12),
    )


def _paint_register_address(path: Path, *, row: int, color: str) -> None:
    workbook = load_workbook(path)
    try:
        sheet = workbook["ZLECENIA"]
        [column] = [cell.column for cell in sheet[1] if cell.value == "ADRES"]
        sheet.cell(row, column).fill = PatternFill(fill_type="solid", fgColor=color)
        workbook.save(path)
    finally:
        workbook.close()


def _cells(written: WrittenFile) -> list[Cell]:
    workbook = load_workbook(written.path)
    sheet = active_worksheet(workbook)
    return [
        cell
        for row in sheet.iter_rows(min_row=written.rows[0], max_row=written.rows[-1], max_col=written.look_columns)
        for cell in row
        if isinstance(cell, Cell)
    ]


def _header_faces(written: WrittenFile) -> dict[int, tuple[object, object]]:
    workbook = load_workbook(written.template)
    sheet = active_worksheet(workbook)
    return {
        column: (sheet.cell(written.header_row, column).font.name, sheet.cell(written.header_row, column).font.sz)
        for column in range(1, written.look_columns + 1)
    }


def _fill(cell: Cell) -> str | None:
    return cell.fill.fgColor.rgb if cell.fill.fill_type == "solid" else None


def test_kazda_komorka_kolumn_wygladu_ma_kroj_naglowka_obramowanie_i_wyrownanie_bez_resztek_wzorca(
    tmp_path: Path,
) -> None:
    chain = _chain(tmp_path)

    for written in (chain.internal, chain.collective, chain.worker):
        faces = _header_faces(written)
        cells = _cells(written)
        assert len(cells) == len(written.rows) * written.look_columns
        thin = [("thin", 64)] * 4
        assert [
            (
                cell.coordinate,
                (cell.font.name, cell.font.sz),
                (cell.alignment.horizontal, cell.alignment.vertical),
                [(side.style, side.color.indexed if side.color is not None else None)
                 for side in (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)],
            )
            for cell in cells
        ] == [(cell.coordinate, faces[cell.column], ("left", "center"), thin) for cell in cells], written.path.name
    condition = "warunek: krój nagłówka różni się między kolumnami Wzorca pliku zbiorczego i między Wzorcami"
    assert set(_header_faces(chain.collective).values()) == {("Calibri", 10), ("Calibri", 11)}, condition
    assert set(_header_faces(chain.worker).values()) == {("Calibri", 11)}, condition


def _borders(path: Path) -> list[bytes]:
    with zipfile.ZipFile(path) as archive:
        borders = ET.fromstring(archive.read("xl/styles.xml")).find(f"{{{_SPREADSHEET}}}borders")
    assert borders is not None
    return [ET.tostring(border) for border in borders]


def test_obramowanie_wiersza_danych_to_obramowanie_wzorca_z_pusta_przekatna_bez_nowego_obramowania(tmp_path: Path) -> None:
    templates = write_synthetic_templates(tmp_path / "wzorce")
    (tmp_path / "okres").mkdir()
    fixture = make_preparation_fixture(tmp_path / "okres")
    run_preparation(fixture)
    worker_template = templates / WORKER_TEMPLATE
    run_settlements(SettlementInputs(fixture.collective_file_path, worker_list(), worker_template), RunContext())
    worker = PeriodFolder.from_collective_file(fixture.collective_file_path).worker_settlement("Adrian Testowy")

    assert _borders(worker) == _borders(worker_template)


def test_zawijany_jest_tylko_tekst_z_koncem_linii(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    for written, wrapped in ((chain.internal, 2), (chain.collective, 18), (chain.worker, 18)):
        cells = _cells(written)
        assert {cell.coordinate for cell in cells if cell.alignment.wrap_text} == {f"{COMPLETED_ACTIVITIES}{wrapped}"}, written.path.name
        assert {cell.coordinate for cell in cells if isinstance(cell.value, str) and "\n" in cell.value} == {f"{COMPLETED_ACTIVITIES}{wrapped}"}


def test_zapisane_wiersze_danych_nie_maja_zapisanej_wysokosci_a_pozostale_wiersze_maja_wysokosc_wzorca(
    tmp_path: Path,
) -> None:
    chain = _chain(tmp_path)

    for written in (chain.internal, chain.collective, chain.worker):
        workbook = load_workbook(written.path)
        sheet = active_worksheet(workbook)
        first_leftover_row = written.header_row + 1
        heights = {row: sheet.row_dimensions[row].height for row in range(first_leftover_row, first_leftover_row + LEFTOVER_ROWS)}
        assert heights == {
            row: None if row in written.rows else LEFTOVER_ROW_HEIGHT for row in heights
        }, written.path.name


def test_adres_ma_wypelnienie_adresu_tego_zlecenia_w_rejestrze_we_wszystkich_trzech_plikach(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    internal = {cell.coordinate: _fill(cell) for cell in _cells(chain.internal) if cell.column == ADDRESS_COLUMN}
    collective = {cell.coordinate: _fill(cell) for cell in _cells(chain.collective) if cell.column == ADDRESS_COLUMN}
    worker = {cell.coordinate: _fill(cell) for cell in _cells(chain.worker) if cell.column == ADDRESS_COLUMN}

    assert internal == {"B2": RED, "B3": None, "B4": None, "B5": None}
    assert collective == {"B18": RED, "B19": None, "B20": None}
    assert worker == {"B18": RED}


def test_format_liczby_jest_z_komorki_zrodlowej_a_data_pracownika_ma_format_pliku_zbiorczego(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    for written in (chain.internal, chain.collective, chain.worker):
        cells = _cells(written)
        looks = wyglady(cells)
        formats = {(cell.column == DATE_COLUMN, looks[cell.coordinate].number_format) for cell in cells}
        assert formats == {(True, REGISTER_DATE_FORMAT), (False, "General")}, written.path.name
    assert REGISTER_DATE_FORMAT != LEFTOVER_DATE_FORMAT


def _cells_before_look(workbook: Workbook) -> list[Cell | MergedCell]:
    sheet = cast(Worksheet, workbook.active)
    sheet["A1"].value = "bez stylu"
    sheet["A2"].style = "Good"
    sheet["A2"].protection = Protection(locked=False)
    sheet["A3"].font = Font(name="Courier New", bold=True)
    sheet["A3"].number_format = "0%"
    sheet["A3"].quotePrefix = True
    return [sheet["A1"], sheet["A2"], sheet["A3"], MergedCell(sheet, row=4, column=1)]


def _resolved(cell: Cell | MergedCell) -> tuple[object, ...]:
    return (*wyglad(cell), cell.style, cell.quotePrefix)


@pytest.mark.parametrize("first", range(4))
def test_cell_look_daje_kazdej_komorce_kazdego_skoroszytu_styl_jak_przypisanie_przez_openpyxl(first: int) -> None:
    faces = RowLook([Font(name="Calibri", sz=10), Font(name="Arial", sz=11)])
    looks = [
        faces.cell(1, PLAIN, GENERAL, wrapped=False),
        faces.cell(2, Highlights.of(Font(color=RED, bold=True), PatternFill("solid", fgColor=RED)), "0.00", wrapped=True),
    ]
    actual: list[tuple[int, tuple[object, ...]]] = []
    expected: list[tuple[int, tuple[object, ...]]] = []
    for other_styles in (False, True):
        workbooks = Workbook(), Workbook()
        for workbook in workbooks:
            if other_styles:
                cast(Worksheet, workbook.active)["Z9"].font = Font(name="Comic Sans MS")
        cells, twins = (_cells_before_look(workbook) for workbook in workbooks)
        order = [*range(first, len(cells)), *range(first)]
        for look in looks:
            for index in order:
                look.apply(cells[index])
                twin = twins[index]
                twin.font, twin.fill, twin.border, twin.alignment = look.font, look.fill, look.border, look.alignment
                twin.number_format = look.number_format
                actual.append((index, _resolved(cells[index])))
                expected.append((index, _resolved(twin)))

    assert actual == expected
    assert {(resolved[5], resolved[6]) for index, resolved in actual if index == 1} == {(Protection(locked=False), "Good")}


def test_wyglad_komorek_jednego_skoroszytu_daje_kazdej_komorce_wyglad_jej_stylu() -> None:
    sheet = cast(Worksheet, Workbook().active)
    for coordinate, number_format in (("A1", "0.00"), ("B1", "0%"), ("C1", "0.00")):
        sheet[coordinate].number_format = number_format

    looks = wyglady([sheet["A1"], sheet["B1"], sheet["C1"], sheet["D1"]])

    assert {coordinate: look.number_format for coordinate, look in looks.items()} == {
        "A1": "0.00",
        "B1": "0%",
        "C1": "0.00",
        "D1": GENERAL,
    }


def test_wyglad_komorek_z_tym_samym_stylearray_w_dwoch_skoroszytach_bierze_tabele_wlasnego_skoroszytu() -> None:
    cells = []
    for name in ("Czcionka-A", "Czcionka-B"):
        cell = cast(Worksheet, Workbook().active)["A1"]
        cell.font = Font(name=name)
        cells.append(cell)

    looks = [cast(Font, wyglady([cell])["A1"].font).name for cell in cells]

    assert looks == ["Czcionka-A", "Czcionka-B"]


@wymaga_ruff
def test_prawo_wygladu_do_slf001_obejmuje_tylko_styl_komorki_openpyxl() -> None:
    module = Path(cast(str, inspect.getsourcefile(RowLook)))
    found = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", "--stdin-filename", str(module.with_name("sonda_wygladu.py")), "-"],
        input=module.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert {(finding["code"], finding["message"]) for finding in json.loads(found.stdout)} == {("SLF001", "Private member accessed: `_style`")}, (
        "prawo row_look.py do SLF001 obejmuje tylko _style openpyxl: inna prywatna składowa to droga obok jej właściciela"
    )
