"""Zapis komórek, Przeniesień zleceń i Zleceń dopisanych z raportu Wpisania raportów do INTERMAX bez Kopii
(``intermax_cells.write_cells``, #1226, #1347, #1354, ADR 0028, ADR 0029).

INTERMAX to syntetyczny Rejestr zleceń z atrap plików taty, czytany jak w procesie (``register_file.read``). Testy
patrzą na plik na dysku: części zip przed i po, wartości i wygląd komórek w openpyxl. Reguły samej podmiany (Excel,
OneDrive, nieudany zapis) wspólne z Uporządkowaniem INTERMAX sprawdza ``tests/test_podmiana_intermax.py``; tu po jednym
przypadku na każdy rodzaj odmowy, że Wpisanie raportów dostaje ten sam fakt.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import tempfile
from typing import cast
from xml.etree import ElementTree
import zipfile

from hypothesis import example, given, settings
from hypothesis import strategies as st
import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell

from rozliczenia import register_file
from rozliczenia.dad_files import DadFiles
from rozliczenia.intermax_cells import CellProblem, CellsWritten, Rejected, write_cells
from rozliczenia.intermax_ordering import OrderingInputs, order_register
from rozliczenia.intermax_replace import LOCAL_DISK, Refusal, Waiting
from rozliczenia.report_cells import CellChange, OrderAdded, OrderMove, OrderRow, ReportColumn
from rozliczenia.run_context import RunContext
from rozliczenia.workbook_parts import UnsupportedShape

from atrapy.intermax import DATE, FIRST, HEADERS, LAST, NUMBER, ORDER_SHEET, WORKER, Intermax, Order, parts
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
    path: Path,
    changes: Sequence[CellChange],
    *,
    disk: FaultyDisk | None = None,
    after_read: Callable[[], object] = lambda: None,
    moves: Sequence[OrderMove] = (),
    added: Sequence[OrderAdded] = (),
) -> CellsWritten | Rejected | Refusal:
    """Wpisanie ``changes``, Przeniesień ``moves`` i dopisań ``added`` do INTERMAX przeczytanego jak w procesie;
    ``after_read`` dzieje się po odczycie."""

    register = register_file.read(path, DadFiles())
    after_read()
    clock = ManualClock()
    return write_cells(
        register, changes, moves, added, waiting=Waiting(clock, clock.pause), disk=(disk or FaultyDisk()).disk()
    )


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


def test_komorka_wpisana_w_luke_wiersza_staje_miedzy_sasiadami_w_kolejnosci_kolumn(tmp_path: Path) -> None:
    """Wiersz 5 atrapy nie ma komórek ``L``–``O``, a ma komórki na prawo od nich: wpisana komórka staje przed pierwszą
    komórką na prawo od siebie, bo Excel otwiera wiersz z komórkami nie po kolei tylko z naprawą pliku."""

    path = _register(tmp_path)
    before = _cell_references(parts(path)[SHEET_PART], 5)
    assert "L5" not in before and "P5" in before

    outcome = _write(path, [_change(5, ReportColumn.SUCCESSFUL, "tak"), _change(5, ReportColumn.COMPLETED, "montaż")])

    assert outcome == CellsWritten(2)
    after = _cell_references(parts(path)[SHEET_PART], 5)
    assert after == sorted({*before, "L5", "M5"}, key=lambda reference: (len(reference), reference))


def _cell_references(sheet: bytes, row: int) -> list[str]:
    """Adresy komórek wiersza ``row`` w kolejności w XML arkusza."""

    [row_xml] = re.findall(rb'<row r="%d"[ >].*?</row>' % row, sheet, flags=re.S)
    return [reference.decode() for reference in re.findall(rb'<c r="([A-Z]+\d+)"', row_xml)]


def test_komorka_w_scaleniu_to_ksztalt_nieobslugiwany_bez_zapisu(tmp_path: Path) -> None:
    path = _register(tmp_path)
    merged = b'<mergeCells count="1"><mergeCell ref="L2:M2"/></mergeCells><hyperlinks>'
    rewrite_parts(path, lambda name, data: data.replace(b"<hyperlinks>", merged, 1) if name == SHEET_PART else data)

    with _untouched(path), pytest.raises(UnsupportedShape, match="scalenie"):
        _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")])


def _zip_changed(
    content: bytes, change: Callable[[str, bytes], bytes | None], added: dict[str, bytes] | None = None
) -> bytes:
    """Archiwum ``content`` z każdą częścią po ``change`` (``None`` usuwa część) i nowymi częściami ``added`` na
    końcu."""

    with zipfile.ZipFile(BytesIO(content)) as source:
        members = [(info, change(info.filename, source.read(info.filename))) for info in source.infolist()]
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in members:
            if data is not None:
                target.writestr(info, data)
        for name, data in (added or {}).items():
            target.writestr(name, data)
    return out.getvalue()


def _in_part(part: str, old: bytes, new: bytes) -> Callable[[bytes], bytes]:
    def change(content: bytes) -> bytes:
        def one(name: str, data: bytes) -> bytes:
            if name != part:
                return data
            assert old in data, (part, old)
            return data.replace(old, new, 1)

        return _zip_changed(content, one)

    return change


WRITTEN_DIFFERENTLY: dict[str, Callable[[bytes], bytes]] = {
    "nowa-czesc": lambda content: _zip_changed(content, lambda name, data: data, {"xl/extra.xml": b"<extra/>"}),
    "bez-czesci": lambda content: _zip_changed(content, lambda name, data: None if name == "docProps/app.xml" else data),
    "zmieniona-inna-czesc": _in_part("docProps/app.xml", b"</Properties>", b"<Company>x</Company></Properties>"),
    "styl-w-srodku-listy": _in_part(STYLES_PART, b"<fonts", b'<fonts><font><sz val="9"/></font></fonts><fonts'),
    "komorka-spoza-wpisanych": _in_part(SHEET_PART, b'<c r="D5" s="4" t="s"><v>17</v>', b'<c r="D5" s="4" t="s"><v>18</v>'),
    "tekst-wpisanej-komorki": _in_part(SHEET_PART, b"<is><t>tak</t></is>", b"<is><t>nie</t></is>"),
}


@pytest.mark.parametrize("spoil", WRITTEN_DIFFERENTLY.values(), ids=WRITTEN_DIFFERENTLY.keys())
def test_zapis_rozny_od_planu_w_odczycie_kontrolnym_nie_podmienia_intermax(
    tmp_path: Path, spoil: Callable[[bytes], bytes]
) -> None:
    """Odczyt kontrolny pliku tymczasowego porównuje go z INTERMAX: inna lista części (nowa albo brakująca), inna
    część poza arkuszem i stylami, styl wstawiony w środek listy, inna komórka arkusza albo inny tekst wpisanej komórki
    to zapis niezgodny, a INTERMAX zostaje nietknięty."""

    path = _register(tmp_path)
    disk = FaultyDisk(read=lambda temporary: spoil(LOCAL_DISK.read(temporary)))

    with _untouched(path):
        outcome = _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")], disk=disk)

    assert outcome == Refusal.WRITE_MISMATCH


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


DAY = date(2026, 11, 9)


def _on(hour: int, worker: str, number: int) -> Order:
    return Order(datetime(2026, 11, 9, hour), worker, number, cells=((NUMBER, number),))


def _move(row: int, worker: str, day: date = DAY) -> OrderMove:
    return OrderMove(OrderRow(ORDER_SHEET, row), day, worker)


def _sheet_rows(path: Path, last: int) -> list[object]:
    """Wiersze arkusza zleceń od 2 do ``last``: (``NUMER ZL.``, ``WYKONAWCA``, Hiperłącze ``NUMER ZL.``) wiersza z
    wartościami albo „żółty” i „pusty”."""

    sheet = load_workbook(path)[ORDER_SHEET]
    rows: list[object] = []
    for number in range(2, last + 1):
        values = [sheet.cell(number, column).value for column in range(1, sheet.max_column + 1)]
        if any(value is not None for value in values):
            link = sheet.cell(number, NUMBER).hyperlink
            rows.append((sheet.cell(number, NUMBER).value, sheet.cell(number, WORKER).value, link and link.target))
        else:
            rows.append("żółty" if sheet.row_dimensions[number].fill.fgColor.rgb == "FFFFFF00" else "pusty")
    return rows


def _link(number: int) -> str:
    return f"https://example.invalid/zlecenie/{number}"


def test_przeniesienie_jedynego_zlecenia_segmentu_zabiera_pusty_wiersz_a_wiersze_pod_dniem_ida_wyzej(tmp_path: Path) -> None:
    """ADR 0029: Jan miał jedno zlecenie dnia, więc jego segment znika razem z pustym wierszem pod nim, a zlecenie staje
    pod ostatnim zleceniem Anny. Pusty wiersz pod dniem, żółty wiersz i wklejenie na dole przesuwają się o wiersz w górę
    z Hiperłączami, więc Uporządkowanie INTERMAX stawia potem dzień tak, jak bez Przeniesienia."""

    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "anna.kowalska", 40000002), _on(11, "anna.kowalska", 40000003)))
    path = _register(tmp_path, intermax)
    pasted = _sheet_rows(path, 17)[9:]

    outcome = _write(path, [], moves=[_move(2, "anna.kowalska")])
    rows = _sheet_rows(path, 16)
    ordered = order_register(OrderingInputs(path, tmp_path / "Kopie", now=lambda: NOW), RunContext())

    assert outcome == CellsWritten(0, 1)
    assert rows[:6] == [
        (40000002, "anna.kowalska", _link(40000002)),
        (40000003, "anna.kowalska", _link(40000003)),
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        "żółty",
        "pusty",
    ]
    assert rows[8:] == pasted
    assert ordered.order_count == len(intermax.raw)


def test_przeniesione_zlecenie_staje_pod_ostatnim_zleceniem_segmentu_nadawcy_a_nie_na_koncu_dnia(tmp_path: Path) -> None:
    """Glosariusz „Przeniesienie zlecenia”: zlecenie Anny przejęte przez Jana staje pod ostatnim zleceniem Jana, przed
    pustym wierszem i segmentem Zofii, którzy są dalej w kolejności alfabetycznej."""

    intermax = Intermax(
        ordered=(
            _on(9, "anna.kowalska", 40000001),
            _on(10, "anna.kowalska", 40000002),
            _on(11, "jan.testowy", 40000003),
            _on(12, "zofia.nowa", 40000004),
        ),
        raw=(),
    )
    path = _register(tmp_path, intermax)

    _write(path, [], moves=[_move(2, "jan.testowy")])

    assert _sheet_rows(path, 8) == [
        (40000002, "anna.kowalska", _link(40000002)),
        "pusty",
        (40000003, "jan.testowy", _link(40000003)),
        (40000001, "jan.testowy", _link(40000001)),
        "pusty",
        (40000004, "zofia.nowa", _link(40000004)),
        "pusty",
    ]

def test_dwa_przeniesienia_jednego_klikniecia_tworza_segment_i_zabieraja_segment_ktory_zostal_pusty(tmp_path: Path) -> None:
    """Oba zlecenia Jana przechodzą do Anny, która nie ma segmentu: pierwsze zakłada jej segment przed segmentem Jana,
    drugie staje pod nim, a pusty segment Jana znika z pustym wierszem nad sobą."""

    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "jan.testowy", 40000005)), raw=())
    path = _register(tmp_path, intermax)

    outcome = _write(path, [], moves=[_move(3, "anna.kowalska"), _move(2, "anna.kowalska")])

    assert outcome == CellsWritten(0, 2)
    assert _sheet_rows(path, 5) == [
        (40000001, "anna.kowalska", _link(40000001)),
        (40000005, "anna.kowalska", _link(40000005)),
        "pusty",
        "żółty",
    ]


def test_przeniesienie_z_komorkami_wpisuje_je_przed_przesunieciem_wiersza(tmp_path: Path) -> None:
    """Komórki zmian mają wiersze INTERMAX sprzed zapisu, więc idą z przeniesionym wierszem, a wiersz, który przesunął
    się w górę, zostaje bez nich."""

    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "jan.testowy", 40000005), _on(11, "anna.kowalska", 40000002)), raw=())
    path = _register(tmp_path, intermax)

    _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")], moves=[_move(2, "anna.kowalska")])

    sheet = load_workbook(path)[ORDER_SHEET]
    assert [(sheet.cell(row, NUMBER).value, sheet.cell(row, SUCCESSFUL).value) for row in (2, 4, 5)] == [
        (40000005, None),
        (40000002, None),
        (40000001, "tak"),
    ]


@pytest.mark.parametrize(
    ("ordered", "moves", "expected"),
    [
        pytest.param(
            (("anna.kowalska", 40000001), ("jan.testowy", 40000002), ("jan.testowy", 40000003)),
            ((2, "jan.testowy"), (4, "zofia.nowa")),
            (("jan.testowy", (40000003, 40000001)), ("zofia.nowa", (40000002,))),
            id="drugie z pierwszego wiersza segmentu, do którego weszło pierwsze",
        ),
        pytest.param(
            (("anna.kowalska", 40000001), ("jan.testowy", 40000002), ("zofia.nowa", 40000003)),
            ((2, "jan.testowy"), (4, "zofia.nowa")),
            (("jan.testowy", (40000001,)), ("zofia.nowa", (40000003, 40000002))),
            id="łańcuch A do B i B do C",
        ),
        pytest.param(
            (("anna.kowalska", 40000001), ("anna.kowalska", 40000004), ("jan.testowy", 40000002)),
            ((2, "jan.testowy"), (5, "anna.kowalska")),
            (("anna.kowalska", (40000004, 40000002)), ("jan.testowy", (40000001,))),
            id="zamiana A i B",
        ),
        pytest.param(
            (("anna.kowalska", 40000001), ("jan.testowy", 40000002), ("jan.testowy", 40000005), ("zofia.nowa", 40000003)),
            ((2, "zofia.nowa"), (4, "anna.kowalska"), (7, "jan.testowy")),
            (("anna.kowalska", (40000002,)), ("jan.testowy", (40000005, 40000003)), ("zofia.nowa", (40000001,))),
            id="trzy naraz",
        ),
    ],
)
def test_kilka_przeniesien_w_dniu_zostawia_kazdy_segment_wykonawcy_w_jednym_kawalku(
    tmp_path: Path,
    ordered: tuple[tuple[str, int], ...],
    moves: tuple[tuple[int, str], ...],
    expected: tuple[tuple[str, tuple[int, ...]], ...],
) -> None:
    """US 10 i glosariusz „Przeniesienie zlecenia”: kilka Przeniesień jednego kliknięcia (dwa zwykłe maile o przejęciu)
    stawia każde zlecenie pod ostatnim zleceniem jego Wykonawcy, także gdy wcześniejsze Przeniesienie weszło do segmentu,
    z którego później odchodzi pierwsze zlecenie (przegląd #1358 r1)."""

    intermax = Intermax(ordered=tuple(_on(9 + index, worker, number) for index, (worker, number) in enumerate(ordered)), raw=())
    path = _register(tmp_path, intermax)

    _write(path, [], moves=[_move(row, worker) for row, worker in moves])

    rows: list[object] = []
    for worker, numbers in expected:
        rows += [(number, worker, _link(number)) for number in numbers] + ["pusty"]
    assert _sheet_rows(path, len(rows) + 2) == [*rows, "żółty"]


_WORKERS = ("anna.kowalska", "ewa.probna", "jan.testowy", "zofia.nowa")


@st.composite
def _day_with_moves(draw: st.DrawFn) -> tuple[tuple[tuple[str, int], ...], dict[int, str]]:
    """Uporządkowany dzień (segmenty Wykonawców po kolei, 1–3 zlecenia) i Przeniesienia części jego zleceń do innych
    Wykonawców: numer zlecenia → nowy Wykonawca."""

    workers = sorted(draw(st.sets(st.sampled_from(_WORKERS), min_size=1, max_size=3)))
    ordered = tuple(
        (worker, 40000000 + 10 * segment + index)
        for segment, worker in enumerate(workers)
        for index in range(draw(st.integers(1, 3)))
    )
    moved = draw(st.sets(st.sampled_from([number for _, number in ordered]), min_size=1, max_size=3))
    targets = {
        number: draw(st.sampled_from([worker for worker in _WORKERS if (worker, number) not in ordered]))
        for number in sorted(moved)
    }
    return ordered, targets


@settings(max_examples=40, deadline=None, derandomize=True, database=None)
@given(_day_with_moves())
def test_dowolne_przeniesienia_w_dniu_daja_uklad_uporzadkowania(day: tuple[tuple[tuple[str, int], ...], dict[int, str]]) -> None:
    """Własność US 10–11: po dowolnych Przeniesieniach w dniu każdy Wykonawca ma jeden segment, segmenty stoją w
    kolejności alfabetycznej jak po Uporządkowaniu INTERMAX, z jednym pustym wierszem między nimi i nad żółtym wierszem,
    zlecenia Wykonawcy, których nikt nie przeniósł, zostają w swojej kolejności, a każde przeniesione staje pod nimi,
    pod ostatnim zleceniem swojego Wykonawcy (Przeniesienia po wierszach od góry), z Hiperłączem."""

    ordered, targets = day
    with tempfile.TemporaryDirectory() as folder:
        path = _register(Path(folder), Intermax(ordered=tuple(_on(9, worker, number) for worker, number in ordered), raw=()))
        rows_of = {number: row for row, (_, number) in enumerate(_ordered_rows(ordered), start=2) if number}
        _write(path, [], moves=[_move(rows_of[number], worker) for number, worker in targets.items()])
        shown = _sheet_rows(path, len(ordered) + 2 * len(_WORKERS) + 2)

    expected: list[object] = []
    for worker in sorted({targets.get(number, owner) for owner, number in ordered}):
        expected += [(number, worker, _link(number)) for owner, number in ordered if owner == worker and number not in targets]
        expected += [(number, worker, _link(number)) for number, target in sorted(targets.items(), key=lambda item: rows_of[item[0]]) if target == worker]
        expected.append("pusty")
    assert shown[: len(expected) + 1] == [*expected, "żółty"]


def _ordered_rows(ordered: Sequence[tuple[str, int]]) -> list[tuple[str, int | None]]:
    """Wiersze uporządkowanego dnia atrapy od wiersza 2: zlecenia z pustym wierszem (numer ``None``) między Wykonawcami."""

    rows: list[tuple[str, int | None]] = []
    for index, (worker, number) in enumerate(ordered):
        if index and ordered[index - 1][0] != worker:
            rows.append(("", None))
        rows.append((worker, number))
    return rows

@pytest.mark.parametrize(
    ("move", "problem"),
    [
        pytest.param(_move(11, "anna.kowalska", date(2026, 10, 26)), CellProblem.MOVE_NOT_ORDERED, id="Surowe zlecenie"),
        pytest.param(_move(3, "anna.kowalska"), CellProblem.MOVE_NOT_ORDERED, id="pusty wiersz"),
        pytest.param(_move(2, "anna.kowalska", date(2026, 11, 10)), CellProblem.NO_DAY, id="dzień bez zleceń"),
    ],
)
def test_przeniesienie_spoza_uporzadkowanego_wiersza_albo_na_dzien_bez_zlecen_jest_odrzucone_przed_zapisem(
    tmp_path: Path, move: OrderMove, problem: CellProblem
) -> None:
    """Zapis przenosi tylko uporządkowane zlecenie i tylko pod uporządkowane zlecenia dnia docelowego w tym arkuszu
    (#1350): dzień bez nich zostawia INTERMAX nietknięty."""

    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "anna.kowalska", 40000002)))
    path = _register(tmp_path, intermax)

    with _untouched(path):
        outcome = _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")], moves=[move])

    assert outcome == Rejected(((move, problem),))


def test_formula_w_przesuwanym_wierszu_to_ksztalt_nieobslugiwany_bez_zapisu(tmp_path: Path) -> None:
    formula = Order(datetime(2026, 11, 9, 11), "anna.kowalska", 40000002, cells=((NUMBER, 40000002), (SUCCESSFUL, "=1+1")))
    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "jan.testowy", 40000005), formula), raw=())
    path = _register(tmp_path, intermax)

    with _untouched(path), pytest.raises(UnsupportedShape, match="formuła"):
        _write(path, [], moves=[_move(2, "anna.kowalska")])


def test_inny_wykonawca_w_odczycie_kontrolnym_przeniesienia_nie_podmienia_intermax(tmp_path: Path) -> None:
    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "anna.kowalska", 40000002)), raw=())
    path = _register(tmp_path, intermax)

    spoil = _in_part(SHEET_PART, b"<t>anna.kowalska</t>", b"<t>jan.testowy</t>")
    disk = FaultyDisk(read=lambda temporary: spoil(LOCAL_DISK.read(temporary)))

    with _untouched(path):
        outcome = _write(path, [], moves=[_move(2, "anna.kowalska")], disk=disk)

    assert outcome == Refusal.WRITE_MISMATCH


EIGHTH = date(2026, 11, 8)


def _at(day: date, hour: int, worker: str, number: int) -> Order:
    return Order(datetime(day.year, day.month, day.day, hour, 30), worker, number, cells=((NUMBER, number),))


def _dates(path: Path, last: int) -> dict[int, tuple[object, str]]:
    """``NUMER ZL.`` → (``DATA GODZ. POCZ.``, format liczby) w wierszach od 2 do ``last``."""

    sheet = load_workbook(path)[ORDER_SHEET]
    found: dict[int, tuple[object, str]] = {}
    for number in range(2, last + 1):
        order, cell = sheet.cell(number, NUMBER).value, sheet.cell(number, DATE)
        if isinstance(order, int):
            found[order] = (cell.value, cell.number_format)
    return found


TWO_DAYS = (
    _at(EIGHTH, 9, "anna.kowalska", 40000001),
    _at(EIGHTH, 10, "zofia.nowa", 40000005),
    _at(DAY, 9, "anna.kowalska", 40000003),
    _at(DAY, 11, "jan.testowy", 40000004),
)
"""8.11: Anna, Zofia; 9.11: Anna, Jan; każdy segment z pustym wierszem pod sobą, żółty wiersz pod ostatnim."""


def test_przeniesienie_na_inny_dzien_zmienia_dzien_z_ta_sama_godzina_i_staje_w_nowym_segmencie_dnia(tmp_path: Path) -> None:
    """ADR 0029, #1350: zlecenie Jana z 9.11 przeniesione na 8.11 dostaje w ``DATA GODZ. POCZ.`` 8.11 z tą samą godziną
    i formatem daty, a wiersz staje w nowym segmencie Jana na miejscu alfabetycznym między Anną a Zofią 8.11, z
    Hiperłączem. Segment Jana w 9.11 znika z pustym wierszem nad sobą, więc żółty wiersz i wklejenie zostają na swoich
    numerach, a Uporządkowanie INTERMAX stawia potem dzień tak jak bez Przeniesienia."""

    intermax = Intermax(ordered=TWO_DAYS)
    path = _register(tmp_path, intermax)
    before = _dates(path, 9)
    pasted = _sheet_rows(path, 20)[9:]

    outcome = _write(path, [_change(8, ReportColumn.SUCCESSFUL, "tak")], moves=[_move(8, "jan.testowy", EIGHTH)])
    still_pasted = _sheet_rows(path, 20)[9:]
    ordered = order_register(OrderingInputs(path, tmp_path / "Kopie", now=lambda: NOW), RunContext())

    assert outcome == CellsWritten(1, 1)
    assert _sheet_rows(path, 10) == [
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        (40000004, "jan.testowy", _link(40000004)),
        "pusty",
        (40000005, "zofia.nowa", _link(40000005)),
        "pusty",
        (40000003, "anna.kowalska", _link(40000003)),
        "pusty",
        "żółty",
    ]
    after = _dates(path, 10)
    assert after[40000004] == (datetime(2026, 11, 8, 11, 30), before[40000004][1])
    assert {number: value for number, value in after.items() if number != 40000004} == {
        number: value for number, value in before.items() if number != 40000004
    }
    sheet = load_workbook(path)[ORDER_SHEET]
    assert sheet.cell(4, SUCCESSFUL).value == "tak"
    assert sheet.cell(4, WORKER).font.b == sheet.cell(2, WORKER).font.b
    assert still_pasted == pasted
    assert ordered.order_count == len(intermax.raw)


def test_przeniesienie_na_pozniejszy_dzien_staje_pod_ostatnim_zleceniem_segmentu_nadawcy(tmp_path: Path) -> None:
    """Zlecenie Anny z 8.11 przeniesione na 9.11 staje pod jej zleceniem 9.11; segment Anny 8.11 znika z pustym
    wierszem pod sobą."""

    path = _register(tmp_path, Intermax(ordered=TWO_DAYS))

    _write(path, [], moves=[_move(2, "anna.kowalska", DAY)])

    assert _sheet_rows(path, 10) == [
        (40000005, "zofia.nowa", _link(40000005)),
        "pusty",
        (40000003, "anna.kowalska", _link(40000003)),
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        (40000004, "jan.testowy", _link(40000004)),
        "pusty",
        "żółty",
        "pusty",
    ]
    assert _dates(path, 10)[40000001][0] == datetime(2026, 11, 9, 9, 30)


def test_przeniesienia_na_inny_dzien_i_w_tym_samym_dniu_w_jednym_kliknieciu_tworza_jeden_ciagly_segment(
    tmp_path: Path,
) -> None:
    """Jan przejmuje zlecenie Anny z 8.11 i dostaje swoje zlecenie z 9.11 na 8.11 w tym samym kliknięciu: oba stoją w
    jednym segmencie Jana 8.11, bez pustego wiersza między nimi."""

    path = _register(tmp_path, Intermax(ordered=TWO_DAYS))

    outcome = _write(path, [], moves=[_move(2, "jan.testowy", EIGHTH), _move(8, "jan.testowy", EIGHTH)])

    assert outcome == CellsWritten(0, 2)
    assert _sheet_rows(path, 9) == [
        (40000001, "jan.testowy", _link(40000001)),
        (40000004, "jan.testowy", _link(40000004)),
        "pusty",
        (40000005, "zofia.nowa", _link(40000005)),
        "pusty",
        (40000003, "anna.kowalska", _link(40000003)),
        "pusty",
        "żółty",
    ]


def _next_day(data: bytes) -> bytes:
    return re.sub(rb'(<c r="C4"[^>]*><v>)(\d+)', lambda found: found.group(1) + b"%d" % (int(found.group(2)) + 1), data)


def _other_style(data: bytes) -> bytes:
    return re.sub(rb'<c r="C4" s="(\d+)"', lambda found: b'<c r="C4" s="%d"' % (int(found.group(1)) + 1), data)


def _text_kind(data: bytes) -> bytes:
    return re.sub(rb'<c r="C4"( s="\d+")?', lambda found: found.group(0) + b' t="str"', data)


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(_next_day, id="inny-dzien"),
        pytest.param(_other_style, id="inny-styl"),
        pytest.param(_text_kind, id="inny-rodzaj"),
    ],
)
def test_inna_data_w_odczycie_kontrolnym_przeniesienia_na_inny_dzien_nie_podmienia_intermax(
    tmp_path: Path, spoil: Callable[[bytes], bytes]
) -> None:
    """Kontrola zapisu sprawdza nową datę przeniesionego zlecenia: zapis z innym dniem niż w planie albo z datą w innym
    stylu (formacie) czy rodzaju komórki (tekst zamiast liczby) to odmowa."""

    path = _register(tmp_path, Intermax(ordered=TWO_DAYS, raw=()))

    def spoiled(content: bytes) -> bytes:
        return _zip_changed(content, lambda name, data: spoil(data) if name == SHEET_PART else data)

    disk = FaultyDisk(read=lambda temporary: spoiled(LOCAL_DISK.read(temporary)))

    with _untouched(path):
        outcome = _write(path, [], moves=[_move(8, "jan.testowy", EIGHTH)], disk=disk)

    assert outcome == Refusal.WRITE_MISMATCH


def test_przeniesienie_na_inny_dzien_z_pierwszego_wiersza_segmentu_do_ktorego_idzie_inne_przeniesienie_zostawia_segmenty_ciagle(
    tmp_path: Path,
) -> None:
    """Przegląd #1358 r1 dla dwóch dni: Jan przejmuje zlecenie Anny z 8.11, a pierwsze zlecenie segmentu Jana idzie do
    Anny na 9.11 w tym samym kliknięciu. Zlecenie Anny staje pod ostatnim zleceniem Jana 8.11, a zlecenie Jana pod
    zleceniem Anny 9.11: każdy Wykonawca ma w dniu jeden ciągły segment."""

    intermax = Intermax(
        ordered=(
            _at(EIGHTH, 9, "anna.kowalska", 40000001),
            _at(EIGHTH, 10, "jan.testowy", 40000002),
            _at(EIGHTH, 11, "jan.testowy", 40000003),
            _at(DAY, 9, "anna.kowalska", 40000004),
        ),
        raw=(),
    )
    path = _register(tmp_path, intermax)

    outcome = _write(path, [], moves=[_move(2, "jan.testowy", EIGHTH), _move(4, "anna.kowalska", DAY)])

    assert outcome == CellsWritten(0, 2)
    assert _sheet_rows(path, 8) == [
        (40000003, "jan.testowy", _link(40000003)),
        (40000001, "jan.testowy", _link(40000001)),
        "pusty",
        (40000004, "anna.kowalska", _link(40000004)),
        (40000002, "anna.kowalska", _link(40000002)),
        "pusty",
        "żółty",
    ]
    assert _dates(path, 8)[40000002][0] == datetime(2026, 11, 9, 10, 30)


def test_zamiana_jedynych_zlecen_dwoch_dni_w_jednym_kliknieciu_staje_na_miejscu_dnia(tmp_path: Path) -> None:
    """Przegląd #1367 r1 (Ważne 1): jedyne zlecenie 8.11 (Anna) idzie na 9.11, a zlecenie Jana z 9.11 na 8.11 w tym
    samym kliknięciu. Rdzeń widzi oba dni jako Dni uporządkowane sprzed kliknięcia, więc zapis też: zlecenie Jana staje
    tam, gdzie stał dzień 8.11, a zlecenie Anny w nowym segmencie Anny 9.11 przed Zofią. Zapis nie odrzuca kliknięcia."""

    intermax = Intermax(
        ordered=(
            _at(EIGHTH, 9, "anna.kowalska", 40000001),
            _at(DAY, 9, "jan.testowy", 40000004),
            _at(DAY, 10, "zofia.nowa", 40000005),
        ),
        raw=(),
    )
    path = _register(tmp_path, intermax)

    outcome = _write(path, [], moves=[_move(2, "anna.kowalska", DAY), _move(4, "jan.testowy", EIGHTH)])

    assert outcome == CellsWritten(0, 2)
    assert _sheet_rows(path, 8) == [
        (40000004, "jan.testowy", _link(40000004)),
        "pusty",
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        (40000005, "zofia.nowa", _link(40000005)),
        "pusty",
        "żółty",
    ]
    dates = _dates(path, 8)
    assert (dates[40000004][0], dates[40000001][0]) == (datetime(2026, 11, 8, 9, 30), datetime(2026, 11, 9, 9, 30))


SEVENTH = date(2026, 11, 7)
_THREE_DAYS = (SEVENTH, EIGHTH, DAY)

_Planned = tuple[tuple[tuple[date, str, int], ...], dict[int, tuple[str, date]], tuple[tuple[str, date], ...]]
"""Uporządkowane zlecenia (dzień, Wykonawca, numer) w kolejności arkusza, Przeniesienia: numer → (Wykonawca, dzień) i
Zlecenia dopisane z raportu (Wykonawca, dzień) po kolei."""


def _added_number(index: int) -> int:
    return 40000900 + index


@st.composite
def _days_with_moves(draw: st.DrawFn) -> _Planned:
    """Dwa albo trzy uporządkowane dni (w każdym segmenty Wykonawców po kolei, 1–2 zlecenia), Przeniesienia części
    zleceń na inny dzień albo do innego Wykonawcy i do dwóch Zleceń dopisanych z raportu w tym samym kliknięciu."""

    days = draw(st.sampled_from([_THREE_DAYS[:2], _THREE_DAYS[1:], _THREE_DAYS]))
    ordered: list[tuple[date, str, int]] = []
    for index, day in enumerate(days):
        workers = sorted(draw(st.sets(st.sampled_from(_WORKERS), min_size=1, max_size=2)))
        for segment, worker in enumerate(workers):
            ordered += [(day, worker, 40000000 + 100 * index + 10 * segment + order) for order in range(draw(st.integers(1, 2)))]
    moved = draw(st.sets(st.sampled_from([number for _, _, number in ordered]), min_size=1, max_size=4))
    targets: dict[int, tuple[str, date]] = {}
    for number in sorted(moved):
        day, worker = next((day, worker) for day, worker, found in ordered if found == number)
        places = [(other, when) for when in days for other in _WORKERS if (other, when) != (worker, day)]
        targets[number] = draw(st.sampled_from(places))
    added = tuple(draw(st.lists(st.tuples(st.sampled_from(_WORKERS), st.sampled_from(days)), max_size=2)))
    return tuple(ordered), targets, added


def _expected_rows(
    ordered: Sequence[tuple[date, str, int]],
    targets: dict[int, tuple[str, date]],
    rows_of: dict[int, int],
    added: Sequence[tuple[str, date]] = (),
) -> list[object]:
    """Wiersze arkusza po kliknięciu jak w ``_sheet_rows``: każdy dzień w swoim miejscu, w nim segmenty Wykonawców
    alfabetycznie z pustym wierszem między nimi, w segmencie najpierw zlecenia, które zostały, w kolejności arkusza, pod
    nimi przeniesione w kolejności wierszy sprzed zapisu, a pod nimi dopisane po kolei (bez Hiperłącza). Puste wiersze
    między dniami i nad żółtym wierszem zostają jak w atrapie (pusty wiersz, gdy ostatni Wykonawca dnia różni się od
    pierwszego następnego), a dzień bez zleceń zostawia tylko je."""

    days = sorted({day for day, _, _ in ordered})
    rows: list[object] = []
    for index, day in enumerate(days):
        stay = [(worker, number) for when, worker, number in ordered if when == day and number not in targets]
        come = sorted(((worker, number) for number, (worker, when) in targets.items() if when == day), key=lambda item: rows_of[item[1]])
        new = [(worker, _added_number(found)) for found, (worker, when) in enumerate(added) if when == day]
        previous: str | None = None
        for worker in sorted({worker for worker, _ in stay + come + new}):
            if previous is not None:
                rows.append("pusty")
            rows += [(number, worker, _link(number)) for found, number in stay + come if found == worker]
            rows += [(number, worker, None) for found, number in new if found == worker]
            previous = worker
        last = [worker for when, worker, _ in ordered if when == day][-1]
        following = [worker for when, worker, _ in ordered if index + 1 < len(days) and when == days[index + 1]]
        rows += ["pusty"] * (not following or following[0] != last)
    return [*rows, "żółty"]


@settings(max_examples=60, deadline=None, derandomize=True, database=None)
@given(_days_with_moves())
@example(
    (
        ((EIGHTH, "anna.kowalska", 40000001), (DAY, "jan.testowy", 40000101), (DAY, "zofia.nowa", 40000111)),
        {40000001: ("anna.kowalska", DAY), 40000101: ("jan.testowy", EIGHTH)},
        (),
    )
).via("przegląd #1367 r1: zamiana jedynych zleceń dwóch dni")
@example(
    (
        ((SEVENTH, "anna.kowalska", 40000001), (EIGHTH, "ewa.probna", 40000101), (DAY, "jan.testowy", 40000201)),
        {
            40000001: ("anna.kowalska", EIGHTH),
            40000101: ("ewa.probna", DAY),
            40000201: ("jan.testowy", SEVENTH),
        },
        (),
    )
).via("łańcuch przez trzy dni, każdy dzień opróżniony i zapełniony")
@example(
    (
        ((SEVENTH, "anna.kowalska", 40000001), (EIGHTH, "ewa.probna", 40000101)),
        {40000101: ("ewa.probna", SEVENTH)},
        (),
    )
).via("dzień opróżniony do zera zleceń")
@example(
    (
        ((SEVENTH, "anna.kowalska", 40000001), (EIGHTH, "ewa.probna", 40000101)),
        {40000101: ("ewa.probna", SEVENTH)},
        (("zofia.nowa", EIGHTH), ("anna.kowalska", EIGHTH)),
    )
).via("dopisania do dnia opróżnionego do zera zleceń")
def test_dowolne_przeniesienia_miedzy_dniami_jednego_klikniecia_zapis_przyjmuje_i_zostawia_uklad_uporzadkowania(
    planned: _Planned,
) -> None:
    """Własność #1350 (przegląd #1367 r1) i #1354: rdzeń przenosi i dopisuje tylko na Dzień uporządkowany arkusza sprzed
    kliknięcia, a każdy taki zbiór Przeniesień i dopisań (wyjścia i wejścia dnia, łańcuchy przez dni, dzień opróżniony do
    zera zleceń, dopisanie do dnia opróżnionego albo w nowym segmencie) zapis przyjmuje w całości, więc przyjmuje każdy
    plan rdzenia. Po zapisie arkusz ma dokładnie układ ``_expected_rows``: dni na swoich miejscach, w każdym dniu każdy
    Wykonawca ma jeden segment, segmenty idą alfabetycznie z jednym pustym wierszem między nimi, puste wiersze między
    dniami i żółty wiersz zostają, przeniesione zlecenie ma dzień docelowy z tą samą godziną i Hiperłącze, a dopisane
    sam dzień docelowy."""

    ordered, targets, added = planned
    rows_of = {number: row for row, (_, number) in enumerate(_ordered_rows([(worker, number) for _, worker, number in ordered]), start=2) if number}
    moves = [_move(rows_of[number], worker, day) for number, (worker, day) in targets.items()]
    new = [_add(worker, day, _added_number(index)) for index, (worker, day) in enumerate(added)]
    last = len(ordered) * 3 + len(added) * 2 + 8
    with tempfile.TemporaryDirectory() as folder:
        path = _register(Path(folder), Intermax(ordered=tuple(_at(day, 9 + number % 10, worker, number) for day, worker, number in ordered), raw=()))
        outcome = _write(path, [], moves=moves, added=new)
        shown = _sheet_rows(path, last)
        dates = _dates(path, last)

    assert outcome == CellsWritten(0, len(moves), len(new))
    expected = _expected_rows(ordered, targets, rows_of, added)
    assert shown[: len(expected)] == expected
    assert set(shown[len(expected) :]) <= {"pusty"}
    for day, _, number in ordered:
        moved = targets.get(number, (None, day))[1]
        assert dates[number][0] == datetime(moved.year, moved.month, moved.day, 9 + number % 10, 30)
    for index, (_, day) in enumerate(added):
        assert dates[_added_number(index)][0] == datetime(day.year, day.month, day.day)


def _add(worker: str, day: date = DAY, number: int = 40000077, completed: str | None = "montaż ONT") -> OrderAdded:
    return OrderAdded(ORDER_SHEET, day, worker, str(number), "tak", completed)


def _row_cells(path: Path, row: int) -> dict[int, object]:
    """Wartości komórek wiersza od A do ``UWAGI``, które nie są puste."""

    sheet = load_workbook(path)[ORDER_SHEET]
    return {column: value for column in range(1, LAST + 1) if (value := sheet.cell(row, column).value) is not None}


def test_dopisane_zlecenie_staje_pod_ostatnim_zleceniem_nadawcy_z_piecioma_wartosciami_i_wygladem_uporzadkowania(
    tmp_path: Path,
) -> None:
    """ADR 0029, US 17, 18, 23 (#1354): dopisane zlecenie Jana staje pod jego ostatnim zleceniem dnia, przed pustym
    wierszem i segmentem Zofii, z ``NUMER ZL.`` liczbą, dniem w ``DATA GODZ. POCZ.`` w formacie daty sąsiednich zleceń,
    ``WYKONAWCA``, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``; reszta wiersza jest pusta. Wygląda jak uporządkowane
    zlecenie (Calibri 8, cienka ramka, pogrubione ``WYKONAWCA`` Calibri 9) bez Koloru operatora, a data ma wygląd daty
    sąsiedniego zlecenia. Żółty wiersz i wklejenie
    przesuwają się o wiersz w dół, więc Uporządkowanie INTERMAX stawia potem dzień tak jak bez dopisania."""

    intermax = Intermax(
        ordered=(_on(9, "anna.kowalska", 40000001), _on(10, "jan.testowy", 40000002), _on(11, "zofia.nowa", 40000003))
    )
    path = _register(tmp_path, intermax)
    pasted = _sheet_rows(path, 20)[8:]
    neighbour = _dates(path, 9)[40000002][1]

    outcome = _write(path, [], added=[_add("jan.testowy")])
    rows = _sheet_rows(path, 21)
    ordered = order_register(OrderingInputs(path, tmp_path / "Kopie", now=lambda: NOW), RunContext())

    assert outcome == CellsWritten(0, 0, 1)
    assert rows[:8] == [
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        (40000002, "jan.testowy", _link(40000002)),
        (40000077, "jan.testowy", None),
        "pusty",
        (40000003, "zofia.nowa", _link(40000003)),
        "pusty",
        "żółty",
    ]
    assert _row_cells(path, 5) == {
        DATE: datetime(2026, 11, 9),
        NUMBER: 40000077,
        WORKER: "jan.testowy",
        SUCCESSFUL: "tak",
        COMPLETED: "montaż ONT",
    }
    assert _dates(path, 9)[40000077] == (datetime(2026, 11, 9), neighbour)
    sheet = load_workbook(path)[ORDER_SHEET]
    columns = [column for column in range(FIRST, LAST + 1) if column != DATE]
    plain = ("Calibri", 8, False, "FF000000", ("thin",) * 4, None, ("left", "center"))
    assert [_look(sheet.cell(5, column)) for column in columns] == [
        ("Calibri", 9, True, *plain[3:]) if column == WORKER else plain for column in columns
    ]
    assert _look(sheet.cell(5, DATE)) == _look(sheet.cell(4, DATE))
    assert rows[9:] == pasted
    assert ordered.order_count == len(intermax.raw)


def test_dopisane_zlecenie_wykonawcy_bez_segmentu_dostaje_nowy_segment_na_miejscu_alfabetycznym(tmp_path: Path) -> None:
    """Glosariusz „Zlecenie dopisane z raportu”: Ewa nie ma zleceń dnia, więc jej dopisane zlecenie staje w nowym
    segmencie między Anną a Janem, z pustym wierszem pod sobą, a dwa dopisania Ewy w jednym kliknięciu stoją razem."""

    intermax = Intermax(ordered=(_on(9, "anna.kowalska", 40000001), _on(10, "jan.testowy", 40000002)), raw=())
    path = _register(tmp_path, intermax)

    outcome = _write(path, [], added=[_add("ewa.probna", completed=None), _add("ewa.probna", number=40000078)])

    assert outcome == CellsWritten(0, 0, 2)
    assert _sheet_rows(path, 9) == [
        (40000001, "anna.kowalska", _link(40000001)),
        "pusty",
        (40000077, "ewa.probna", None),
        (40000078, "ewa.probna", None),
        "pusty",
        (40000002, "jan.testowy", _link(40000002)),
        "pusty",
        "żółty",
    ]
    assert COMPLETED not in _row_cells(path, 4)


def test_numer_dopisanego_zlecenia_z_zerem_na_poczatku_staje_tekstem(tmp_path: Path) -> None:
    """``NUMER ZL.`` dopisanego zlecenia jest liczbą jak numery z aplikacji firmowej, a numer z zerem na początku tekstem,
    bo liczba straciłaby zero i następne kliknięcie nie znalazłoby zlecenia z numerem z Wpisu."""

    path = _register(tmp_path, Intermax(ordered=(_on(9, "jan.testowy", 40000001),), raw=()))

    _write(path, [], added=[OrderAdded(ORDER_SHEET, DAY, "jan.testowy", "04000077", "nie", None)])

    assert _row_cells(path, 3)[NUMBER] == "04000077"


@pytest.mark.parametrize(
    ("added", "problem"),
    [
        pytest.param(_add("jan.testowy", date(2026, 11, 10)), CellProblem.NO_DAY, id="dzien-bez-zlecen"),
        pytest.param(replace(_add("jan.testowy"), sheet="Inny arkusz"), CellProblem.ADDED_OUTSIDE, id="arkusz-bez-obszaru"),
        pytest.param(_add("jan.testowy", completed="montaż\x01"), CellProblem.UNWRITABLE_TEXT, id="znak-spoza-xml"),
    ],
)
def test_dopisanie_na_dzien_bez_zlecen_albo_do_arkusza_bez_obszaru_wklejania_jest_odrzucone_przed_zapisem(
    tmp_path: Path, added: OrderAdded, problem: CellProblem
) -> None:
    """Zapis dopisuje tylko pod uporządkowane zlecenia dnia w arkuszu zleceń z obszarem wklejania i tylko tekst, który
    komórka przyjmie; inaczej INTERMAX zostaje nietknięty, także bez zmiany komórki z tego samego kliknięcia."""

    intermax = Intermax(ordered=(_on(9, "jan.testowy", 40000001), _on(10, "anna.kowalska", 40000002)))
    path = _register(tmp_path, intermax)

    with _untouched(path):
        outcome = _write(path, [_change(2, ReportColumn.SUCCESSFUL, "tak")], added=[added])

    assert outcome == Rejected(((added, problem),))


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda data: data.replace("<t>montaż ONT</t>".encode(), "<t>montaż</t>".encode()), id="inny-tekst"),
        pytest.param(lambda data: re.sub(rb'(<c r="C5"[^>]*><v>)(\d+)', rb"\g<1>1", data), id="inna-data"),
        pytest.param(lambda data: re.sub(rb'<c r="C5" s="(\d+)"', rb'<c r="C5" s="0"', data), id="inny-styl-daty"),
        pytest.param(lambda data: data.replace(b'<c r="E5"', b'<c r="E5" t="inlineStr"><is><t>x</t></is></c><c r="Z5"'), id="adres"),
    ],
)
def test_inny_wiersz_dopisanego_zlecenia_w_odczycie_kontrolnym_nie_podmienia_intermax(
    tmp_path: Path, spoil: Callable[[bytes], bytes]
) -> None:
    """Kontrola zapisu sprawdza dopisany wiersz: inny tekst, inny dzień, inny styl daty niż u sąsiedniego zlecenia albo
    dodatkowa wartość (np. w ``ADRES``) to odmowa."""

    intermax = Intermax(ordered=(_on(9, "anna.kowalska", 40000001), _on(10, "jan.testowy", 40000002)), raw=())
    path = _register(tmp_path, intermax)

    def spoiled(content: bytes) -> bytes:
        return _zip_changed(content, lambda name, data: spoil(data) if name == SHEET_PART else data)

    disk = FaultyDisk(read=lambda temporary: spoiled(LOCAL_DISK.read(temporary)))

    with _untouched(path):
        outcome = _write(path, [], added=[_add("jan.testowy")], disk=disk)

    assert outcome == Refusal.WRITE_MISMATCH
