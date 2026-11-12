"""Zapis komórek i Przeniesień zleceń Wpisania raportów do INTERMAX bez Kopii (``intermax_cells.write_cells``, #1226,
#1347, ADR 0028, ADR 0029).

INTERMAX to syntetyczny Rejestr zleceń z atrap plików taty, czytany jak w procesie (``register_file.read``). Testy
patrzą na plik na dysku: części zip przed i po, wartości i wygląd komórek w openpyxl. Reguły samej podmiany (Excel,
OneDrive, nieudany zapis) wspólne z Uporządkowaniem INTERMAX sprawdza ``tests/test_podmiana_intermax.py``; tu po jednym
przypadku na każdy rodzaj odmowy, że Wpisanie raportów dostaje ten sam fakt.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import cast
from xml.etree import ElementTree
import zipfile

import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell

from rozliczenia import register_file
from rozliczenia.dad_files import DadFiles
from rozliczenia.intermax_cells import CellProblem, CellsWritten, Rejected, write_cells
from rozliczenia.intermax_ordering import OrderingInputs, order_register
from rozliczenia.intermax_replace import LOCAL_DISK, Refusal, Waiting
from rozliczenia.report_cells import CellChange, OrderMove, OrderRow, ReportColumn
from rozliczenia.run_context import RunContext
from rozliczenia.workbook_parts import UnsupportedShape

from atrapy.intermax import FIRST, HEADERS, NUMBER, ORDER_SHEET, WORKER, Intermax, Order, parts
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
) -> CellsWritten | Rejected | Refusal:
    """Wpisanie ``changes`` i Przeniesień ``moves`` do INTERMAX przeczytanego jak w procesie; ``after_read`` dzieje się po
    odczycie."""

    register = register_file.read(path, DadFiles())
    after_read()
    clock = ManualClock()
    return write_cells(
        register, changes, moves, waiting=Waiting(clock, clock.pause), disk=(disk or FaultyDisk()).disk()
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
    ("move", "problem"),
    [
        pytest.param(_move(11, "anna.kowalska", date(2026, 10, 26)), CellProblem.MOVE_NOT_ORDERED, id="Surowe zlecenie"),
        pytest.param(_move(3, "anna.kowalska"), CellProblem.MOVE_NOT_ORDERED, id="pusty wiersz"),
        pytest.param(_move(2, "anna.kowalska", date(2026, 11, 10)), CellProblem.OTHER_DAY, id="inny dzień"),
    ],
)
def test_przeniesienie_spoza_uporzadkowanego_wiersza_albo_na_inny_dzien_jest_odrzucone_przed_zapisem(
    tmp_path: Path, move: OrderMove, problem: CellProblem
) -> None:
    """Zapis przenosi tylko uporządkowane zlecenie w obrębie jego dnia; Przeniesienie na inny dzień zostaje dla #1350."""

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
