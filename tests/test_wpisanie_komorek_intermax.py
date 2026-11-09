"""Zapis komórek Wpisania raportów do INTERMAX bez Kopii (``intermax_cells.write_cells``, #1226, ADR 0028).

INTERMAX to syntetyczny Rejestr zleceń z atrap plików taty, czytany jak w procesie (``register_file.read``). Testy
patrzą na plik na dysku: części zip przed i po, wartości i wygląd komórek w openpyxl. Reguły samej podmiany (Excel,
OneDrive, nieudany zapis) wspólne z Uporządkowaniem INTERMAX sprawdza ``tests/test_podmiana_intermax.py``; tu po jednym
przypadku na każdy rodzaj odmowy, że Wpisanie raportów dostaje ten sam fakt.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell

from rozliczenia import register_file
from rozliczenia.dad_files import DadFiles
from rozliczenia.intermax_cells import CellProblem, CellsWritten, Rejected, write_cells
from rozliczenia.intermax_ordering import OrderingInputs, order_register
from rozliczenia.intermax_replace import Refusal, Waiting
from rozliczenia.report_cells import CellChange, OrderRow, ReportColumn
from rozliczenia.run_context import RunContext
from rozliczenia.workbook_parts import UnsupportedShape

from atrapy.intermax import FIRST, HEADERS, NUMBER, ORDER_SHEET, Intermax, Order, parts
from atrapy.workbooks import rewrite_parts
from tests.fixtures.clock import ManualClock
from tests.fixtures.intermax_disk import FaultyDisk, denied, failing_replace

NOW = datetime(2026, 10, 26, 20, 0, 0)
REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
SUCCESSFUL = FIRST + HEADERS.index("SKUTECZNE")
COMPLETED = FIRST + HEADERS.index("CZYNNOŚCI ZREALIZOWANE")
RETURN = FIRST + HEADERS.index("ZWROT")
SHEET_PART = "xl/worksheets/sheet2.xml"
STYLES_PART = "xl/styles.xml"
STYLE_LISTS = ("fonts", "fills", "borders", "cellXfs")
ACTIVITIES_TEXT = "wymiana gniazda, stb2 & <tv> — zółć"
"""Tekst z polskimi literami i znakami, które XML zapisuje encjami."""


def _register(tmp_path: Path, intermax: Intermax | None = None) -> Path:
    folder = tmp_path / "OneDrive"
    folder.mkdir()
    path = folder / REGISTER_NAME
    (intermax or Intermax()).write(path)
    return path


def _change(row: int, column: ReportColumn, value: str, sheet: str = ORDER_SHEET) -> CellChange:
    return CellChange(OrderRow(sheet, row), column, value)


def _write(
    path: Path, changes: Sequence[CellChange], *, disk: FaultyDisk | None = None, after_read: Callable[[], object] = lambda: None
) -> CellsWritten | Rejected | Refusal:
    """Wpisanie ``changes`` do INTERMAX przeczytanego jak w procesie; ``after_read`` dzieje się po odczycie."""

    register = register_file.read(path, DadFiles())
    after_read()
    clock = ManualClock()
    return write_cells(register, changes, waiting=Waiting(clock, clock.pause), disk=(disk or FaultyDisk()).disk())


@contextmanager
def _untouched(path: Path) -> Iterator[None]:
    """INTERMAX bajt w bajt i bez pliku tymczasowego obok po bloku."""

    before = path.read_bytes(), sorted(child.name for child in path.parent.iterdir())
    yield
    assert (path.read_bytes(), sorted(child.name for child in path.parent.iterdir())) == before


def _without_cells(sheet: bytes, references: Sequence[str]) -> bytes:
    for reference in references:
        sheet = re.sub(rb'<c r="' + reference.encode() + rb'"[^>]*?(?:/>|>.*?</c>)', b"", sheet, flags=re.S)
    return sheet


def _style_lists(styles: bytes) -> dict[str, list[bytes]]:
    root = ElementTree.fromstring(styles)
    return {child.tag.split("}")[1]: [ElementTree.tostring(entry) for entry in child] for child in root}


def _row_of(path: Path, number: str) -> int:
    sheet = load_workbook(path)[ORDER_SHEET]
    return next(row for row in range(2, sheet.max_row + 1) if sheet.cell(row, NUMBER).value == number)


def _look(cell: Cell | MergedCell) -> tuple[object, ...]:
    font, border = cell.font, cell.border
    sides = tuple(side.style for side in (border.left, border.right, border.top, border.bottom))
    color = font.color.rgb if font.color else None
    alignment = cell.alignment.horizontal, cell.alignment.vertical
    return font.name, font.sz, font.b, color, sides, cell.fill.fill_type, alignment


def test_wpisanie_dwoch_komorek_zostawia_reszte_intermax_bajt_w_bajt(tmp_path: Path) -> None:
    path = _register(tmp_path)
    before = parts(path)

    outcome = _write(
        path, [_change(2, ReportColumn.SUCCESSFUL, "tak"), _change(5, ReportColumn.COMPLETED, ACTIVITIES_TEXT)]
    )

    assert outcome == CellsWritten(2)
    after = parts(path)
    assert list(after) == list(before)
    assert {name for name in before if after[name] != before[name]} <= {SHEET_PART, STYLES_PART}
    references = ["L2", "M5"]
    assert _without_cells(after[SHEET_PART], references) == _without_cells(before[SHEET_PART], references)
    old, new = _style_lists(before[STYLES_PART]), _style_lists(after[STYLES_PART])
    assert new.keys() == old.keys()
    for tag, entries in old.items():
        assert new[tag][: len(entries)] == entries if tag in STYLE_LISTS else new[tag] == entries, tag
    sheet = load_workbook(path)[ORDER_SHEET]
    assert (sheet.cell(2, SUCCESSFUL).value, sheet.cell(5, COMPLETED).value) == ("tak", ACTIVITIES_TEXT)
    assert sheet.cell(2, COMPLETED).value is None and sheet.cell(5, SUCCESSFUL).value is None


def test_wpisane_komorki_maja_wyglad_uporzadkowanego_wiersza(tmp_path: Path) -> None:
    """Komórka dnia z Uporządkowania INTERMAX zachowuje swój styl, a brakująca komórka dnia uporządkowanego ręcznie
    dostaje ten sam wygląd, który Uporządkowanie daje pustej kolumnie zlecenia (``ZWROT``)."""

    path = _register(tmp_path)
    clock = ManualClock()
    order_register(
        OrderingInputs(path, tmp_path / "Kopie INTERMAX", now=lambda: NOW, waiting=Waiting(clock, clock.pause)),
        RunContext(),
    )
    ordered_by_tool = _row_of(path, "ZL-102")
    looks_before = load_workbook(path)[ORDER_SHEET]
    expected = _look(looks_before.cell(ordered_by_tool, RETURN))

    outcome = _write(
        path,
        [
            _change(ordered_by_tool, ReportColumn.SUCCESSFUL, "nie"),
            _change(ordered_by_tool, ReportColumn.COMPLETED, "brak klienta"),
            _change(2, ReportColumn.SUCCESSFUL, "tak"),
        ],
    )

    assert outcome == CellsWritten(3)
    sheet = load_workbook(path)[ORDER_SHEET]
    written = [sheet.cell(ordered_by_tool, SUCCESSFUL), sheet.cell(ordered_by_tool, COMPLETED), sheet.cell(2, SUCCESSFUL)]
    assert [cell.value for cell in written] == ["nie", "brak klienta", "tak"]
    assert [_look(cell) for cell in written] == [expected] * 3
    assert expected[:2] == ("Calibri", 8) and expected[4] == ("thin",) * 4


def test_komorka_za_ostatnia_komorka_wiersza_staje_na_jego_koncu(tmp_path: Path) -> None:
    """Wiersz uporządkowany ręcznie bywa bez komórek na prawo od ``NUMER UMOWY``; wpisana komórka zamyka go."""

    path = _register(tmp_path)
    beyond = re.compile(rb'<c r="(?:[L-Z]|A[A-K])5"[^>]*?(?:/>|>.*?</c>)', re.S)
    rewrite_parts(path, lambda name, data: beyond.sub(b"", data) if name == SHEET_PART else data)
    before = load_workbook(path)[ORDER_SHEET]
    kept = [before.cell(5, column).value for column in range(1, SUCCESSFUL)]

    assert _write(path, [_change(5, ReportColumn.COMPLETED, ACTIVITIES_TEXT)]) == CellsWritten(1)

    sheet = load_workbook(path)[ORDER_SHEET]
    assert [sheet.cell(5, column).value for column in range(1, COMPLETED + 2)] == [*kept, None, ACTIVITIES_TEXT, None]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (_change(11, ReportColumn.SUCCESSFUL, "tak"), CellProblem.NOT_ORDERED),
        (_change(4, ReportColumn.SUCCESSFUL, "tak"), CellProblem.NOT_ORDERED),
        (_change(1, ReportColumn.SUCCESSFUL, "tak"), CellProblem.NOT_ORDERED),
        (_change(1000, ReportColumn.SUCCESSFUL, "tak"), CellProblem.NOT_ORDERED),
        (_change(2, ReportColumn.SUCCESSFUL, "tak", sheet="komentarze"), CellProblem.NOT_ORDERED),
        (_change(2, cast(ReportColumn, "UWAGI"), "tak"), CellProblem.NOT_REPORT_COLUMN),
        (_change(5, ReportColumn.SUCCESSFUL, "nie"), CellProblem.REPEATED),
        (_change(3, ReportColumn.COMPLETED, "opis\x01"), CellProblem.UNWRITABLE_TEXT),
        (_change(3, ReportColumn.COMPLETED, "x" * 32768), CellProblem.UNWRITABLE_TEXT),
    ],
    ids=[
        "Surowe zlecenie",
        "pusty wiersz między Wykonawcami",
        "wiersz nagłówków",
        "wiersza nie ma",
        "arkusz bez zleceń",
        "kolumna UWAGI",
        "ta sama komórka drugi raz",
        "znak spoza XML",
        "tekst dłuższy niż komórka Excela",
    ],
)
def test_komorka_spoza_raportu_uporzadkowanego_wiersza_jest_odrzucona_przed_zapisem(
    tmp_path: Path, change: CellChange, problem: CellProblem
) -> None:
    path = _register(tmp_path)
    accepted = _change(5, ReportColumn.SUCCESSFUL, "tak")

    with _untouched(path):
        outcome = _write(path, [accepted, change])

    assert outcome == Rejected(((change, problem),))


def test_komorka_z_formula_to_ksztalt_nieobslugiwany_bez_zapisu(tmp_path: Path) -> None:
    intermax = Intermax()
    intermax.ordered = (Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1, cells=((SUCCESSFUL, "=1+1"),)),)
    path = _register(tmp_path, intermax)

    with _untouched(path), pytest.raises(UnsupportedShape, match="formuła"):
        _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")])


def test_bez_zmian_intermax_zostaje_nietkniety(tmp_path: Path) -> None:
    path = _register(tmp_path)

    with _untouched(path):
        assert _write(path, []) == CellsWritten(0)


def test_otwarty_intermax_i_odmowa_onedrive_daja_ten_sam_fakt_co_w_uporzadkowaniu(tmp_path: Path) -> None:
    path = _register(tmp_path)
    changes = [_change(2, ReportColumn.SUCCESSFUL, "tak")]
    lock = path.with_name(f"~${path.name}")
    replace, _ = failing_replace(denied)
    worker = b"INTERMAX z poprawka pracownika"
    replace_worker, _ = failing_replace(denied, before=lambda: path.write_bytes(worker))

    with _untouched(path):
        excel = _write(path, changes, after_read=lambda: lock.write_bytes(b"tata"))
        lock.unlink()
    with _untouched(path):
        onedrive = _write(path, changes, disk=FaultyDisk(replace=replace))
    changed = _write(path, changes, disk=FaultyDisk(replace=replace_worker))

    assert (excel, onedrive, changed) == (Refusal.EXCEL_HOLDS, Refusal.ONEDRIVE_HOLDS, Refusal.ONEDRIVE_HOLDS)
    assert path.read_bytes() == worker
    assert sorted(child.name for child in path.parent.iterdir()) == [path.name]
