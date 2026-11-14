"""Wygląd Wiersza danych: zapisane Wiersze danych wyglądają jak w plikach taty, bez resztek formatowania Wzorców.

Przygotowanie pliku zbiorczego zapisuje Rozliczenie wewnętrzne (kolumny wyglądu A:M) i Plik zbiorczy (A:L), a Przebieg
rozliczeń z tego Pliku zbiorczego Rozliczenie pracownika (A:L). Wszystkie trzy Wzorce mają w Wierszach danych resztki
formatowania jak u taty: inny krój, zawijanie, wyrównanie do góry, brak obramowania, format daty i własną wysokość.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles import Font, PatternFill, Protection
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
from atrapy.settlement import worker_list, write_template
from atrapy.workbooks import LEFTOVER_DATE_FORMAT, LEFTOVER_ROW_HEIGHT, active_worksheet, leave_data_row_leftovers

RED = "FFFF0000"
# Zlecenie 2 (wiersz 4 Rejestru) jest skuteczne, ma czerwony ADRES i koniec linii w CZYNNOŚCI ZREALIZOWANE; trafia do
# wiersza 2 Rozliczenia wewnętrznego, 18 Pliku zbiorczego i 18 Rozliczenia pracownika Adriana.
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
    """Krój i rozmiar czcionki nagłówka każdej kolumny wyglądu we Wzorcu."""

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
    # Nagłówki Wzorców: Rozliczenia wewnętrznego i pliku zbiorczego Calibri 10, rozliczenia pracownika Calibri 11.
    assert set(_header_faces(chain.collective).values()) == {("Calibri", 10), ("Calibri", 11)}
    assert set(_header_faces(chain.worker).values()) == {("Calibri", 11)}


def test_zawijany_jest_tylko_tekst_z_koncem_linii(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    # CZYNNOŚCI ZREALIZOWANE to K we wszystkich trzech plikach.
    for written, wrapped in ((chain.internal, "K2"), (chain.collective, "K18"), (chain.worker, "K18")):
        cells = _cells(written)
        assert {cell.coordinate for cell in cells if cell.alignment.wrap_text} == {wrapped}, written.path.name
        assert {cell.coordinate for cell in cells if isinstance(cell.value, str) and "\n" in cell.value} == {wrapped}


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

    # ADRES: kolumna B we wszystkich trzech plikach. W Rejestrze czerwony jest tylko ADRES zlecenia 2; skuteczne
    # zlecenia 4 i 6 trafiają do wierszy 19 i 20 Pliku zbiorczego.
    internal = {cell.coordinate: _fill(cell) for cell in _cells(chain.internal) if cell.column == 2}
    collective = {cell.coordinate: _fill(cell) for cell in _cells(chain.collective) if cell.column == 2}
    worker = {cell.coordinate: _fill(cell) for cell in _cells(chain.worker) if cell.column == 2}

    assert internal == {"B2": RED, "B3": None, "B4": None, "B5": None}
    assert collective == {"B18": RED, "B19": None, "B20": None}
    assert worker == {"B18": RED}


def test_format_liczby_jest_z_komorki_zrodlowej_a_data_pracownika_ma_format_pliku_zbiorczego(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    # DATA: kolumna G we wszystkich trzech plikach; Wzorce mają tam LEFTOVER_DATE_FORMAT, a pozostałe komórki Rejestru
    # format ogólny.
    for written in (chain.internal, chain.collective, chain.worker):
        cells = _cells(written)
        # Przez wyglady: jedyna asercja bezwzględna na pamięci stylów pomocnika (w wierszu G ma inny styl niż reszta).
        looks = wyglady(cells)
        formats = {(cell.column == 7, looks[cell.coordinate].number_format) for cell in cells}
        assert formats == {(True, REGISTER_DATE_FORMAT), (False, "General")}, written.path.name
    assert REGISTER_DATE_FORMAT != LEFTOVER_DATE_FORMAT


def _cells_before_look(workbook: Workbook) -> list[Cell | MergedCell]:
    """Komórki Wzorca w różnym stanie: bez stylu, ze stylem nazwanym i ochroną, z resztkami formatowania, scalona."""

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


def test_wyglad_komorek_z_tym_samym_stylearray_w_dwoch_skoroszytach_bierze_tabele_wlasnego_skoroszytu() -> None:
    # Numery w StyleArray znaczą co innego w innym skoroszycie, więc pamięć wspólna dla skoroszytów porównywałaby kopię
    # samą ze sobą (#1455 r1).
    cells = []
    for name in ("Czcionka-A", "Czcionka-B"):
        cell = cast(Worksheet, Workbook().active)["A1"]
        cell.font = Font(name=name)
        cells.append(cell)

    looks = [cast(Font, wyglady([cell])["A1"].font).name for cell in cells]

    assert looks == ["Czcionka-A", "Czcionka-B"]


@wymaga_ruff
def test_prawo_wygladu_do_slf001_obejmuje_tylko_styl_komorki_openpyxl() -> None:
    """``row_look.py`` ustawia indeksy stylu komórki wprost w prywatnym ``StyleArray`` openpyxl (``_style``), bo openpyxl
    nie ma do niego publicznego API, więc ``pyproject.toml`` daje mu prawo właściciela do ``SLF001``. Kod modułu jako
    sonda obok niego, poza tym prawem, zgłasza w ruff tylko ``_style``: inna prywatna składowa to droga obok jej
    właściciela."""

    module = Path(cast(str, inspect.getsourcefile(RowLook)))
    found = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", "--stdin-filename", str(module.with_name("sonda_wygladu.py")), "-"],
        input=module.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert {(finding["code"], finding["message"]) for finding in json.loads(found.stdout)} == {("SLF001", "Private member accessed: `_style`")}
