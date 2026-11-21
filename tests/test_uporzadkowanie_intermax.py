from __future__ import annotations

import errno
import re
import struct
import zipfile
import zlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Color, Font, PatternFill
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter
from openpyxl.utils.datetime import CALENDAR_MAC_1904
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia.client_data import MIN_VALUE, empty_memory, guarded
from rozliczenia.dad_files import DadFiles
from rozliczenia.domain import ProgressPhase
from rozliczenia.efenix_mark import Mark
from rozliczenia.intermax_ordering import HistoryCounts, OrderingInputs, OrderingSummary, RegisterDay, register_days
from rozliczenia.intermax_replace import Waiting
from rozliczenia.intermax_process import PROCESS
from rozliczenia.message import Message
from rozliczenia.order_base import ORDER_BASE_NAME
from rozliczenia.run_clock import RunClock
from rozliczenia.run_context import RunContext
from rozliczenia.process_run import Finished, Outcome, Stop, run_process
from rozliczenia.progress import PhaseState
from rozliczenia.workbook_files import Problem, WorkbookError

from tests.fixtures.clock import ManualClock
from atrapy.intermax import (
    ACTIVITIES,
    ADDRESS,
    CITY,
    APP_LAST,
    BLANK_HEIGHT,
    CONTRACT_NUMBER,
    DATE,
    DEVICES,
    DATE_FORMAT,
    FIRST,
    HEADERS,
    LAST,
    NUMBER,
    ORDER_HEIGHT,
    ORDER_SHEET,
    WORKER,
    YELLOW,
    Intermax,
    Layout,
    Order,
    like_excel,
    order_rows,
    parts,
)
from atrapy.baza_zlecen import ELEVEN, FIVE, TWELVE, BaseSheet, Visit, write_order_base
from atrapy.baza_zlecen import Layout as BaseLayout
from atrapy.interlocutor import Tata
from atrapy.preparation import make_preparation_fixture, paste_raw_orders, register_order
from atrapy.pliki_taty import PASTE_SHIFT
from tests.fixtures.intermax_disk import FaultyDisk, denied, failing_replace, no_space, writing
from tests.fixtures.operacje import run_preparation
from atrapy.workbooks import rewrite_parts, without_sheet

NOW = datetime(2026, 10, 25, 21, 5, 7)
COPY_NAME = "INTERMAX przed uporządkowaniem 2026-10-25 21-05-07.xlsx"
REGISTER_NAME = "ZLECENIA INTERMAX OD 08_11_2021.xlsx"


def _run(
    tmp_path: Path,
    *,
    now: datetime = NOW,
    clock: ManualClock | None = None,
    disk: FaultyDisk | None = None,
    base: bool = False,
    files: DadFiles | None = None,
) -> Outcome[OrderingSummary]:
    """Uruchomienie Uporządkowania; ``clock`` to zegar procesu krótkiej ponownej próby podmiany, ``disk`` usterki
    kroków podmiany INTERMAX, ``base``: wejście ma Bazę zleceń obok INTERMAX, ``files``: uchwyt plików taty."""

    waiting = clock or ManualClock()
    inputs = OrderingInputs(
        tmp_path / "OneDrive" / REGISTER_NAME,
        tmp_path / "Kopie INTERMAX",
        lambda: now,
        Waiting(waiting, waiting.pause),
        (disk or FaultyDisk()).disk(),
        order_base=tmp_path / "OneDrive" / ORDER_BASE_NAME if base else None,
    )
    return run_process(
        PROCESS,
        inputs,
        Tata(),
        view=lambda _inputs, summary: summary,
        metrics_path=tmp_path / "m.jsonl",
        context=RunContext(files=files or DadFiles(), clock=RunClock(ManualClock())),
    )


def _register(tmp_path: Path, intermax: Intermax | None = None) -> tuple[Path, Layout]:
    folder = tmp_path / "OneDrive"
    folder.mkdir(exist_ok=True)
    path = folder / REGISTER_NAME
    return path, (intermax or Intermax()).write(path)


def _expected(order: Order, entry: tuple[str, str] | None = None) -> tuple[object, ...]:
    values: dict[int, object] = {column: value for column, value in order.values().items() if column <= LAST}
    if entry is not None:
        values[DEVICES], values[ACTIVITIES] = entry
    return tuple(values.get(column) for column in range(1, APP_LAST + 1))


def _stop(outcome: Outcome[OrderingSummary]) -> Stop:
    assert isinstance(outcome.ending, Stop), outcome.ending
    return outcome.ending


def _without_order_data(message: Message, orders: Sequence[Order]) -> None:
    """Komunikat bez adresów, numerów zleceń, numerów umów, loginów Wykonawców i innych wartości zleceń."""

    for order in orders:
        for value in order.values().values():
            if isinstance(value, str) and value not in ("Miastko", "Umowa", "Instalacja", "INEA"):
                assert value not in message.text, value


def _raw_row(order: Order) -> Callable[[Worksheet, int], None]:
    """Wiersz ``order`` z wyglądem z aplikacji (Roboto 4) wpisany w wiersz arkusza."""

    def write(sheet: Worksheet, number: int) -> None:
        for column, value in order.values().items():
            sheet.cell(number, column, value).font = Font(name="Roboto", sz=4)

    return write


def _in_other_font(number: int) -> Callable[[Worksheet], None]:
    """Uporządkowany wiersz ``number`` przepisany czcionką inną niż Calibri 8, jak wiersz z wyglądem z aplikacji."""

    def edit(sheet: Worksheet) -> None:
        for column in range(FIRST, LAST + 1):
            sheet.cell(number, column).font = Font(name="Arial", sz=10)

    return edit


def _ordered_row(order: Order) -> Callable[[Worksheet, int], None]:
    """Wiersz ``order`` z wyglądem uporządkowanego zlecenia (Calibri 8) wpisany w wiersz arkusza."""

    def write(sheet: Worksheet, number: int) -> None:
        for column, value in order.values().items():
            cell = sheet.cell(number, column, value)
            cell.font = Font(name="Calibri", sz=8)
            if column == DATE:
                cell.number_format = DATE_FORMAT

    return write


def _ordered(outcome: Outcome[OrderingSummary]) -> OrderingSummary:
    assert isinstance(outcome.ending, Finished) and outcome.ending.result == "OK", outcome.ending
    assert outcome.view is not None
    return outcome.view


def _copies(tmp_path: Path) -> set[str]:
    folder = tmp_path / "Kopie INTERMAX"
    return {entry.name for entry in folder.iterdir()} if folder.is_dir() else set()


@contextmanager
def _nothing_written(tmp_path: Path, path: Path) -> Iterator[None]:
    """INTERMAX bajt w bajt, bez pliku tymczasowego obok i bez nowej Kopii INTERMAX po bloku."""

    original, neighbours, copies = path.read_bytes(), set(path.parent.iterdir()), _copies(tmp_path)
    yield
    assert path.read_bytes() == original
    assert set(path.parent.iterdir()) <= neighbours | {path.with_name(f"~${REGISTER_NAME}")}, "plik tymczasowy nie zostaje"
    assert _copies(tmp_path) == copies


def _edited(path: Path, edit: Callable[[Worksheet], None]) -> None:
    """INTERMAX zmieniony w openpyxl tak, jak tata zmienia go w Excelu: ``edit(arkusz zleceń)``."""

    workbook = load_workbook(path)
    edit(workbook[ORDER_SHEET])
    workbook.save(path)


def _row_xml(path: Path, number: int) -> bytes:
    found = re.search(rb'<row r="%d"[^>]*?(?:/>|>.*?</row>)' % number, parts(path)["xl/worksheets/sheet2.xml"], re.S)
    assert found is not None, number
    return found.group(0)


def test_rekord_metryk_uporzadkowania_liczy_zlecenia_i_wykonawcow_dnia(tmp_path: Path) -> None:
    _register(tmp_path)

    outcome = _run(tmp_path)

    assert isinstance(outcome.ending, Finished), outcome.ending
    assert outcome.ending.counters == {"orders": 6, "workers": 3}


def test_dzien_staje_pod_zoltym_wierszem_w_segmentach_wykonawcow_alfabetycznie_i_po_godzinie(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    anna_10, anna_10_later, anna_16 = layout.raw[1], layout.raw[4], layout.raw[2]
    bartek, jan_8, jan_14_shifted = layout.raw[5], layout.raw[3], layout.raw[0]

    outcome = _run(tmp_path)

    assert isinstance(outcome.ending, Finished) and outcome.ending.result == "OK"
    assert outcome.view is not None
    assert (outcome.view.day.isoformat(), outcome.view.order_count, outcome.view.worker_count) == ("2026-10-26", 6, 3)
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 1, layout.yellow + 12) == [
        None,
        _expected(anna_10),
        _expected(anna_10_later),
        _expected(anna_16),
        None,
        _expected(bartek),
        None,
        _expected(jan_8),
        _expected(jan_14_shifted),
        None,
        None,
        None,
    ]


_OLDER_DAYS = tuple(
    Order(datetime(2026, 10, 1 + day, 8) + timedelta(minutes=5 * index), f"wykonawca.{index // 8:02d}", 100 * day + index)
    for day in range(6)
    for index in range(40)
)
_WEEK = tuple(
    Order(datetime(2026, 10, 19 + day, 8) + timedelta(minutes=5 * index), f"wykonawca.{index // 8:02d}", 1000 + 100 * day + index)
    for day in range(7)
    for index in range(40)
)
"""Uporządkowane dni jak u taty, kilkadziesiąt zleceń dziennie: starsze dni i tydzień przed dzisiejszym dniem (``NOW``)."""
_LONG_PASTE = tuple(
    Order(datetime(2026, 10, 26, 8) + timedelta(minutes=(7 * index) % 600), f"wykonawca.{index % 9:02d}", 5000 + index)
    for index in range(160)
)


def _long_register(tmp_path: Path, raw: Sequence[Order] = Intermax().raw) -> tuple[Path, Layout]:
    """INTERMAX, którego arkusz zleceń ma ponad pół MB XML: Uporządkowanie czyta tylko jego dół."""

    path, layout = _register(tmp_path, Intermax(ordered=_OLDER_DAYS + _WEEK, raw=raw))
    assert len(parts(path)[_SHEET]) > 600_000
    return path, layout


def test_dzien_pod_dlugim_arkuszem_staje_w_segmentach_a_wiersze_nad_nim_zostaja_bajt_w_bajt(tmp_path: Path) -> None:
    path, layout = _long_register(tmp_path, _LONG_PASTE)
    before = parts(path)[_SHEET]

    summary = _ordered(_run(tmp_path))

    assert (summary.order_count, summary.worker_count) == (len(_LONG_PASTE), 9)
    expected: list[tuple[object, ...] | None] = []
    for worker in sorted({order.worker for order in _LONG_PASTE}):
        expected += [_expected(order) for order in sorted(_LONG_PASTE, key=lambda order: order.when) if order.worker == worker]
        expected.append(None)
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 1 + len(expected)) == expected
    region = next(row for row in re.finditer(rb'<row r="(\d+)"', before) if int(row.group(1)) > layout.yellow)
    without_dimension_and_view = re.compile(rb"<dimension [^>]*>|<sheetViews>.*?</sheetViews>")
    above = without_dimension_and_view.sub(b"", before[: region.start()])
    assert without_dimension_and_view.sub(b"", parts(path)[_SHEET]).startswith(above)


@pytest.mark.parametrize(
    ("opening", "closing"), [(b"<!-- ", b" -->"), (b"<![CDATA[", b"]]>"), (b"", b"</sheetData><sheetData>")]
)
def test_komentarz_konczacy_sie_w_czytanym_dole_arkusza_to_zatrzymanie_do_maksa_bez_zapisu(
    tmp_path: Path, opening: bytes, closing: bytes
) -> None:
    """Komentarz albo CDATA zaczyna się w starszych dniach, których Uporządkowanie nie czyta, a kończy w tygodniu,
    który czyta: wiersze w nim nie są wierszami arkusza. Tak samo granica drugiego ``<sheetData>`` w tygodniu."""

    path, layout = _long_register(tmp_path)

    def commented(name: str, data: bytes) -> bytes:
        if name != _SHEET:
            return data
        data = data.replace(b'<row r="3"', opening + b'<row r="3"', 1)
        return data.replace(b'<row r="%d"' % layout.last_ordered, closing + b'<row r="%d"' % layout.last_ordered, 1)

    rewrite_parts(path, commented)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


@pytest.mark.parametrize("comment", [b'<!-- <row r="999"> -->', b'<![CDATA[<row r="999">]]>'])
def test_komentarz_z_niedomknietym_wierszem_pod_ostatnim_wierszem_to_zatrzymanie_do_maksa_bez_zapisu(
    tmp_path: Path, comment: bytes
) -> None:
    """Pierwszy wiersz, który Uporządkowanie czyta od dołu, zaczyna się w komentarzu albo CDATA i nie ma ``</row>``."""

    path, _ = _register(tmp_path)
    rewrite_parts(path, lambda name, data: data.replace(b"</sheetData>", comment + b"</sheetData>", 1) if name == _SHEET else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_komentarz_w_starszych_dniach_nad_czytanym_dolem_arkusza_zostaje_bajt_w_bajt(tmp_path: Path) -> None:
    """Uporządkowanie czyta arkusz od dołu do tygodnia przed dzisiejszym dniem, a starszych wierszy nie zmienia."""

    path, layout = _long_register(tmp_path)
    comment = b"<!-- uwaga -->"
    rewrite_parts(path, lambda name, data: data.replace(b'<row r="3"', comment + b'<row r="3"', 1) if name == _SHEET else data)

    summary = _ordered(_run(tmp_path))

    assert summary.order_count == len(layout.raw)
    assert parts(path)[_SHEET].count(comment + b'<row r="3"') == 1


def test_wiersz_nie_po_kolei_w_czytanym_dole_arkusza_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _long_register(tmp_path)
    moved = b'<row r="%d"' % (layout.last_ordered - 3)
    rewrite_parts(path, lambda name, data: data.replace(moved, b'<row r="%d"' % (layout.last_ordered + 500), 1) if name == _SHEET else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_bez_zoltego_wiersza_dzien_staje_10_pustych_wierszy_pod_ostatnim_uporzadkowanym_zleceniem(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(yellow=None, gap=1))

    _run(tmp_path)

    rows = order_rows(path, layout.last_ordered + 1, layout.last_ordered + 11)
    assert rows[:10] == [None] * 10
    assert rows[10] == _expected(layout.raw[1])
    with closing(load_workbook(path, read_only=True)) as workbook:
        max_row = workbook.worksheets[1].max_row
    assert max_row == layout.last_ordered + 10 + 6 + 2, "<dimension> obejmuje dłuższy dzień"


def test_zlecenia_maja_wyglad_reszty_intermax_od_kolumny_a_z_pogrubionym_wykonawca_i_nic_za_uwagi(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)

    _run(tmp_path)

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    for row in (layout.yellow + 2, layout.yellow + 5, layout.yellow + 9):
        for column in range(1, LAST + 1):
            cell = sheet.cell(row, column)
            font = cell.font
            assert (font.name, font.sz, font.b, font.i, font.color.rgb) == (
                "Calibri",
                9 if column == WORKER else 8,
                column == WORKER,
                False,
                "FF000000",
            ), cell.coordinate
            assert cell.fill.fill_type is None, cell.coordinate
            assert {side.style for side in (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)} == {
                "thin"
            }
            assert (cell.alignment.horizontal, cell.alignment.vertical) == ("left", "center")
        assert sheet.cell(row, DATE + 1).number_format == "General"
    for row in (layout.yellow + 2, layout.yellow + 9):
        assert sheet.cell(row, DATE).number_format == "m/d/yy h:mm"
        written = {letters.decode("ascii") for letters in re.findall(rb'<c r="([A-Z]+)\d', _row_xml(path, row))}
        assert written == {get_column_letter(column) for column in range(1, LAST + 1)}, row


_GREEN, _ORANGE, _DARK_BLUE, _LIGHT_BLUE, _PINK = "FF99FF66", "FFFFC000", "FF69D8FF", "FF00FFFF", "FFE89CA7"


def _fills(sheet: Worksheet, row: int) -> dict[int, str | None]:
    return {
        column: cell.fill.fgColor.rgb if (cell := sheet.cell(row, column)).fill.fill_type == "solid" else None
        for column in range(FIRST, LAST + 1)
    }


def _colored(activities: str | None, contract_number: str | None, devices: str | None) -> dict[int, str | None]:
    return {column: None for column in range(FIRST, LAST + 1)} | {
        ACTIVITIES: activities,
        CONTRACT_NUMBER: contract_number,
        DEVICES: devices,
    }


def test_znaczniki_wyceny_w_efenix_nie_sa_zadnym_kolorem_operatora_ani_zoltym_oddzieleniem_dni() -> None:
    # Kolory, które Uporządkowanie INTERMAX nadaje według testów niżej, i żółty wiersz, którym tata oddziela dni.
    taken = {_GREEN, _ORANGE, _DARK_BLUE, _LIGHT_BLUE, _PINK, YELLOW.fgColor.rgb}

    assert {mark.value for mark in Mark}.isdisjoint({rgb[-6:].upper() for rgb in taken})


@pytest.mark.parametrize(
    ("operator", "kind", "expected"),
    [
        ("TMOBILE", "Instalacja Hurt", _colored(_GREEN, _GREEN, None)),
        ("T-Mobile", "Instalacja", _colored(_GREEN, _GREEN, None)),
        ("ORANGE", "Instalacja Hurt", _colored(_ORANGE, _ORANGE, None)),
        ("Netia", "Instalacja Hurt", _colored(_DARK_BLUE, _LIGHT_BLUE, None)),
        ("P4", "Instalacja Hurt", _colored(_LIGHT_BLUE, _LIGHT_BLUE, None)),
        ("VECTRA", "Instalacja Hurt", _colored(_LIGHT_BLUE, _LIGHT_BLUE, None)),
        ("INEA", "Instalacja Hurt", _colored(None, None, None)),
        ("OXYLION", "Instalacja", _colored(_LIGHT_BLUE, _LIGHT_BLUE, None)),
        (None, "Instalacja", _colored(None, None, None)),
        ("TMOBILE", "Usterka", _colored(None, None, _PINK)),
        ("TMOBILE", "Usterka Hurt", _colored(None, None, _PINK)),
        (None, "Usterka", _colored(None, None, _PINK)),
    ],
    ids=[
        "tmobile",
        "t-mobile",
        "orange",
        "netia",
        "p4",
        "vectra",
        "inea",
        "inny operator",
        "puste czynnosci",
        "usterka przy tmobile",
        "usterka hurt przy tmobile",
        "usterka bez operatora",
    ],
)
def test_kolor_operatora_w_czynnosciach_numerze_umowy_i_urzadzeniach_a_inne_komorki_bez_wypelnienia(
    tmp_path: Path, operator: str | None, kind: str, expected: dict[int, str | None]
) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, operator, kind),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 102, operator, kind),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    assert [sheet.cell(row, NUMBER).value for row in (layout.yellow + 2, layout.yellow + 3)] == ["ZL-102", "ZL-101"]
    assert _fills(sheet, layout.yellow + 2) == expected, "zlecenie na miejscu"
    assert _fills(sheet, layout.yellow + 3) == expected, "przesunięty pierwszy wiersz"


@pytest.mark.parametrize(
    ("operator", "kind", "entry"),
    [
        ("Netia", "Instalacja Hurt", ("nokia", "Netia - akt pętli")),
        ("P4", "Instalacja Hurt", ("nokia", "P4 - akt pętli")),
        ("Plus", "Instalacja Hurt", ("nokia", "Plus - akt pętli")),
        ("VECTRA", "Instalacja Hurt", ("nokia", "VECTRA - akt pętli")),
        ("SYSTEMIA", "Instalacja Hurt", ("nokia", "SYSTEMIA - akt pętli")),
        ("ORANGE", "Instalacja Hurt", ("gniazdo", "ORANGE - akt pętli LLU")),
        ("TMOBILE", "Instalacja Hurt", ("nokia getewayHomeBox", "TMOBILE - akt int")),
        ("P4 <&>", "Instalacja Hurt", ("nokia", "P4 <&> - akt pętli")),
        ("T-Mobile", "Instalacja Hurt", ("nokia getewayHomeBox", "T-Mobile - akt int")),
    ],
    ids=[
        "netia",
        "p4",
        "plus",
        "vectra",
        "systemia",
        "orange",
        "tmobile",
        "znaki xml w nazwie operatora",
        "t-mobile",
    ],
)
def test_instalacja_hurt_operatora_z_reguly_taty_dostaje_wpis_urzadzenia_i_czynnosci_intermax(
    tmp_path: Path, operator: str, kind: str, entry: tuple[str, str]
) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, operator, kind),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 102, operator, kind),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 3) == [_expected(raw[1], entry), _expected(raw[0], entry)]


@pytest.mark.parametrize(
    ("operator", "kind"),
    [
        ("P4", "Usterka"),
        ("TMOBILE", "Usterka Hurt"),
        ("ORANGE", "Usterka pomontażowa"),
        ("P4", "Instalacja"),
        ("OXYLION", "Instalacja Hurt"),
        (None, "Instalacja Hurt"),
    ],
    ids=[
        "usterka",
        "usterka hurt",
        "usterka pomontazowa",
        "instalacja reczna",
        "oxylion",
        "puste czynnosci",
    ],
)
def test_zlecenie_poza_regula_taty_zostaje_bez_wpisu_z_wartosciami_z_aplikacji(
    tmp_path: Path, operator: str | None, kind: str
) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, operator, kind),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 102, operator, kind),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 3) == [_expected(raw[1]), _expected(raw[0])]


def test_komorki_wpisu_maja_wyglad_reszty_dnia_i_kolor_operatora(tmp_path: Path) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, "ORANGE", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 102, "ORANGE", "Instalacja Hurt"),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    for row in (layout.yellow + 2, layout.yellow + 3):
        for column, fill in ((DEVICES, None), (ACTIVITIES, _ORANGE)):
            cell = sheet.cell(row, column)
            assert (cell.data_type, cell.number_format) == ("s", "General"), cell.coordinate
            assert (cell.font.name, cell.font.sz, cell.font.b, cell.font.color.rgb) == ("Calibri", 8, False, "FF000000")
            assert _fills(sheet, row)[column] == fill, cell.coordinate
            assert {side.style for side in (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)} == {
                "thin"
            }
            assert (cell.alignment.horizontal, cell.alignment.vertical) == ("left", "center")


def test_pusta_komorka_numeru_umowy_dostaje_kolor_operatora(tmp_path: Path) -> None:
    raw = (Order(datetime(2026, 10, 26, 8), "jan.nowak", 101, "TMOBILE"),)
    path, layout = _register(tmp_path, Intermax(raw=raw, shifted=False))
    contract = rb'<c r="%s%d"[^>]*?(?:/>|>.*?</c>)' % (get_column_letter(CONTRACT_NUMBER).encode(), layout.first_raw)
    rewrite_parts(path, lambda name, data: re.sub(contract, b"", data, flags=re.S) if name == _SHEET else data)

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    assert sheet.cell(layout.yellow + 2, CONTRACT_NUMBER).value is None
    assert _fills(sheet, layout.yellow + 2) == _colored(_GREEN, _GREEN, None)


def _links(path: Path, first: int, last: int) -> dict[str, str | None]:
    sheet = load_workbook(path)[ORDER_SHEET]
    return {
        cell.coordinate: link.target
        for row in range(first, last + 1)
        if (link := (cell := sheet.cell(row, NUMBER)).hyperlink) is not None
    }


def test_inne_czesci_pliku_i_wiersze_nad_dniem_zostaja_bajt_w_bajt_a_hiperlacza_ida_ze_zleceniem(tmp_path: Path) -> None:
    """Arkusz zleceń był aktywny, więc poza nim i stylami nic się nie zmienia; nad dniem zmienia się tylko widok."""

    path, layout = _register(tmp_path)
    before = parts(path)
    ordered_links = _links(path, 2, layout.last_ordered)
    assert len(ordered_links) == 3

    _run(tmp_path)

    assert _links(path, 2, layout.last_ordered) == ordered_links

    after = parts(path)
    sheet_part, styles_part = "xl/worksheets/sheet2.xml", "xl/styles.xml"
    assert list(after) == list(before)
    assert {name for name in before if before[name] != after[name]} <= {sheet_part, styles_part}
    assert layout.yellow is not None
    region = next(row for row in re.finditer(rb'<row r="(\d+)"', before[sheet_part]) if int(row.group(1)) > layout.yellow)
    without_dimension_and_view = re.compile(rb"<dimension [^>]*>|<sheetViews>.*?</sheetViews>")
    above = without_dimension_and_view.sub(b"", before[sheet_part][: region.start()])
    assert b"<sheetData>" in above and without_dimension_and_view.sub(b"", after[sheet_part]).startswith(above)
    sheet = load_workbook(path).worksheets[1]
    links = {
        cell.value: link.target
        for row in range(layout.yellow + 2, layout.yellow + 10)
        if (link := (cell := sheet.cell(row, NUMBER)).hyperlink) is not None
    }
    assert links == {f"ZL-{order.number}": order.link for order in layout.raw}


def test_kazda_czesc_intermax_po_uporzadkowaniu_to_pelny_strumien_deflate_z_data_oryginalu(tmp_path: Path) -> None:
    """Excel czyta część skoroszytu jako strumień deflate z blokiem końcowym. Duża część (kilka MB, jak arkusz zleceń
    taty) wraca z tą samą treścią i datą."""

    path, _ = _register(tmp_path)
    big = b"".join(b'<row r="%d"><c r="A%d"><v>%d</v></c></row>' % (number, number, number * 7919) for number in range(150_000))
    rewrite_parts(path, lambda _name, data: data, {"customXml/duza.xml": big})
    before = {info.filename: info.date_time for info in zipfile.ZipFile(path).infolist()}

    _ordered(_run(tmp_path))

    content = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        assert {info.filename: info.date_time for info in archive.infolist()} == before
        assert archive.read("customXml/duza.xml") == big
        for info in archive.infolist():
            name_length, extra_length = struct.unpack("<HH", content[info.header_offset + 26 : info.header_offset + 30])
            start = info.header_offset + 30 + name_length + extra_length
            stream = zlib.decompressobj(-zlib.MAX_WBITS)
            stream.decompress(content[start : start + info.compress_size])
            assert (info.compress_type, stream.eof) == (zipfile.ZIP_DEFLATED, True), info.filename


@dataclass(frozen=True)
class _View:
    """Jak INTERMAX otwiera się w Excelu: aktywny arkusz, zaznaczone karty, górny wiersz widoku i zaznaczenie."""

    active: str
    selected: tuple[str, ...]
    top_row: int
    selection: str
    frozen_header: bool


def _view(path: Path) -> _View:
    workbook = load_workbook(path)
    sheet = workbook[ORDER_SHEET]
    view = sheet.sheet_view
    pane = view.pane
    top = pane.topLeftCell if pane is not None else view.topLeftCell
    [selection] = view.selection
    assert top is not None and selection.activeCell == selection.sqref
    assert selection.pane == (pane.activePane if pane is not None else None)
    assert workbook.active is not None
    return _View(
        workbook.active.title,
        tuple(sheet.title for sheet in workbook.worksheets if sheet.sheet_view.tabSelected),
        coordinate_from_string(top)[1],
        selection.activeCell,
        pane is not None and (pane.ySplit, pane.state, pane.activePane) == (1, "frozen", "bottomLeft"),
    )


# Uporządkowane dni fixture'u ``_VIEW_DAYS``: 19.10 w wierszu 2, 20.10 od wiersza 3 (dwóch Wykonawców, pusty wiersz 5).
_VIEW_DAYS = (
    Order(datetime(2026, 10, 19, 9), "anna.kowalska", 1),
    Order(datetime(2026, 10, 20, 9), "anna.kowalska", 2),
    Order(datetime(2026, 10, 20, 12), "anna.kowalska", 3),
    Order(datetime(2026, 10, 20, 8), "jan.nowak", 4),
)


@pytest.mark.parametrize(
    ("today", "top_row"),
    [(datetime(2026, 10, 20, 7), 3), (datetime(2026, 10, 19, 7), 2), (datetime(2026, 10, 23, 7), 3)],
    ids=["dzis-ze-zleceniami", "dzis-wczesniejszy-dzien", "dzis-bez-zlecen-ostatni-wczesniejszy-dzien"],
)
def test_intermax_otwiera_sie_na_pierwszym_zleceniu_dzisiejszego_dnia_choc_uporzadkowany_dzien_jest_inny(
    tmp_path: Path, today: datetime, top_row: int
) -> None:
    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS))

    _ordered(_run(tmp_path, now=today))

    assert _view(path) == _View(ORDER_SHEET, (ORDER_SHEET,), top_row, f"B{top_row}", frozen_header=True)


@pytest.mark.parametrize(
    "today", [datetime(2026, 10, 26, 7), datetime(2026, 10, 28, 7), datetime(2026, 10, 1, 7)], ids=["dzis", "pozniej", "przed"]
)
def test_intermax_otwiera_sie_na_uporzadkowanym_dniu_gdy_to_dzis_ostatni_dzien_przed_dzis_albo_nie_ma_wczesniejszych(
    tmp_path: Path, today: datetime
) -> None:
    path, layout = _register(tmp_path, Intermax(ordered=_VIEW_DAYS))

    _ordered(_run(tmp_path, now=today))

    assert layout.yellow is not None
    assert _view(path).top_row == layout.yellow + 2


def test_usterka_poprzedniego_dnia_dopisana_pod_dzisiejszym_dniem_nie_przesuwa_widoku(tmp_path: Path) -> None:
    ordered = (*_VIEW_DAYS[1:3], Order(datetime(2026, 10, 19, 15), "anna.kowalska", 5))
    path, _ = _register(tmp_path, Intermax(ordered=ordered))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).top_row == 2


# Zlecenie na dziś w wierszu 2, pod nim ``below`` zleceń z 19.10, pusty wiersz i dzisiejszy dzień Wykonawcy jan.nowak.
@pytest.mark.parametrize(("below", "top_row"), [(9, 2), (10, 14)])
def test_zlecenie_na_dzis_wpisane_we_wczesniejszym_dniu_jest_poczatkiem_widoku_tylko_tuz_nad_dzisiejszym_dniem(
    tmp_path: Path, below: int, top_row: int
) -> None:
    earlier = (Order(datetime(2026, 10, 19, 8 + hour % 10), "anna.kowalska", 10 + hour) for hour in range(below))
    ordered = (Order(datetime(2026, 10, 20, 7), "anna.kowalska", 1), *earlier, Order(datetime(2026, 10, 20, 9), "jan.nowak", 2))
    path, _ = _register(tmp_path, Intermax(ordered=ordered))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).top_row == top_row


def test_zlecenie_na_dzis_wsrod_wczesniejszych_zaczyna_widok_gdy_10_wczesniejszych_nie_stoi_pod_rzad(tmp_path: Path) -> None:
    """Granica 10 wierszy liczy wcześniejsze dni pod rząd, jak przegląd nad wklejeniem: zlecenie na dziś ją zeruje."""

    earlier = tuple(Order(datetime(2026, 10, 19, 8 + hour), "anna.kowalska", 10 + hour) for hour in range(10))
    ordered = (
        Order(datetime(2026, 10, 20, 7), "anna.kowalska", 1),
        *earlier[:9],
        Order(datetime(2026, 10, 20, 8), "anna.kowalska", 2),
        earlier[9],
        Order(datetime(2026, 10, 20, 9), "jan.nowak", 3),
    )
    path, _ = _register(tmp_path, Intermax(ordered=ordered))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).top_row == 2


def test_dzien_bez_zoltego_wiersza_z_jedynym_zleceniem_dzisiaj_w_ostatnim_uporzadkowanym_wierszu_jest_widokiem(
    tmp_path: Path,
) -> None:
    ordered = (_VIEW_DAYS[0], _VIEW_DAYS[3])
    path, layout = _register(tmp_path, Intermax(ordered=ordered, yellow=None))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).top_row == layout.last_ordered == 4


def test_intermax_zapisany_z_innym_aktywnym_arkuszem_otwiera_sie_na_arkuszu_zlecen(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS, active_sheet="LISTA OD 08.11.2021."))
    before = parts(path)

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path) == _View(ORDER_SHEET, (ORDER_SHEET,), 3, "B3", frozen_header=True)
    after = parts(path)
    assert {name for name in before if before[name] != after[name]} == {
        _SHEET,
        _STYLES,
        "xl/workbook.xml",
        "xl/worksheets/sheet3.xml",
    }


def test_intermax_zapisany_na_ostatnim_arkuszu_otwiera_sie_na_samym_arkuszu_zlecen(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS, active_sheet="komentarze"))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).selected == (ORDER_SHEET,)


def test_karta_zaznaczona_jako_true_w_innym_arkuszu_przestaje_byc_zaznaczona(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS, active_sheet="LISTA OD 08.11.2021."))
    rewrite_parts(
        path, lambda name, data: data.replace(b'tabSelected="1"', b'tabSelected="true"') if name == _LIST_SHEET else data
    )

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).selected == (ORDER_SHEET,)
    assert b"tabSelected" not in parts(path)[_LIST_SHEET]


def test_w_drugim_oknie_excela_intermax_tez_otwiera_sie_na_arkuszu_zlecen_i_dzisiejszym_dniu(tmp_path: Path) -> None:
    """Każde okno skoroszytu ma własny ``<workbookView>`` i własny ``<sheetView>`` w każdym arkuszu."""

    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS, active_sheet="LISTA OD 08.11.2021."))

    def second_window(name: str, data: bytes) -> bytes:
        if name == "xl/workbook.xml":
            return re.sub(rb"(<workbookView\b[^>]*/>)", rb"\1\1", data)
        if name == _SHEET:
            view = re.search(rb"<sheetView\b.*?</sheetView>", data, re.S)
            assert view is not None
            second = view.group(0).replace(b'workbookViewId="0"', b'workbookViewId="1"')
            return data.replace(view.group(0), view.group(0) + second)
        return data

    rewrite_parts(path, second_window)

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    after = parts(path)
    assert re.findall(rb'<workbookView\b[^>]*\sactiveTab="(\d+)"', after["xl/workbook.xml"]) == [b"1", b"1"]
    views = re.findall(rb"<sheetView\b.*?</sheetView>", after[_SHEET], re.S)
    assert len(views) == 2
    for view in views:
        assert b'tabSelected="1"' in view and b'topLeftCell="A3"' in view and b'activeCell="B3"' in view


def test_intermax_zapisany_na_pierwszym_arkuszu_bez_activetab_otwiera_sie_na_arkuszu_zlecen(tmp_path: Path) -> None:
    """Excel nie zapisuje ``activeTab``, gdy aktywny jest pierwszy arkusz."""

    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS))
    rewrite_parts(path, lambda name, data: data.replace(b' activeTab="1"', b"") if name == "xl/workbook.xml" else data)
    assert load_workbook(path).active.title == "Arkusz1"  # type: ignore[union-attr]

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path).active == ORDER_SHEET


def test_zamrozony_naglowek_bez_activepane_ma_zaznaczenie_w_gornym_panelu(tmp_path: Path) -> None:
    """Bez ``activePane`` aktywny jest górny lewy panel, więc zaznaczenie staje w nim."""

    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS))
    rewrite_parts(path, lambda name, data: data.replace(b' activePane="bottomLeft"', b"") if name == _SHEET else data)

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    view = load_workbook(path)[ORDER_SHEET].sheet_view
    assert view.pane is not None and (view.pane.ySplit, view.pane.state, view.pane.topLeftCell) == (1, "frozen", "A3")
    assert [(selection.pane, selection.activeCell) for selection in view.selection] == [("topLeft", "B3")]


def test_bez_zamrozonego_naglowka_widok_bez_panelu_otwiera_sie_na_dzisiejszym_dniu(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(ordered=_VIEW_DAYS, frozen=False))

    _ordered(_run(tmp_path, now=datetime(2026, 10, 20, 7)))

    assert _view(path) == _View(ORDER_SHEET, (ORDER_SHEET,), 3, "B3", frozen_header=False)
    assert load_workbook(path)[ORDER_SHEET].sheet_view.pane is None


def test_po_jedenastej_kopii_zostaje_10_najnowszych_a_inne_pliki_folderu_zostaja(tmp_path: Path) -> None:
    _register(tmp_path)
    copies = tmp_path / "Kopie INTERMAX"
    copies.mkdir()
    older = [copies / f"INTERMAX przed uporządkowaniem 2026-10-{day:02d} 07-00-00.xlsx" for day in range(10, 20)]
    for copy in older:
        copy.write_bytes(b"kopia")
    (copies / "notatka.txt").write_text("tata", encoding="utf-8")

    _run(tmp_path)

    assert sorted(path.name for path in copies.iterdir()) == sorted(
        [*(copy.name for copy in older[1:]), COPY_NAME, "notatka.txt"]
    )


def _part_changed(content: bytes, name: str, change: Callable[[bytes], bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            target.writestr(info, change(data) if info.filename == name else data)
    return out.getvalue()


def _parts_reordered(content: bytes) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
        infos = source.infolist()
        for info in [infos[1], infos[0], *infos[2:]]:
            target.writestr(info, source.read(info))
    return out.getvalue()


_SHEET, _STYLES = "xl/worksheets/sheet2.xml", "xl/styles.xml"
_LIST_SHEET = "xl/worksheets/sheet3.xml"
"""Arkusz ``LISTA OD 08.11.2021.`` fixture'u, za arkuszem zleceń."""


def _in_sheet(change: Callable[[bytes], bytes]) -> Callable[[bytes, Layout], bytes]:
    return lambda content, _layout: _part_changed(content, _SHEET, change)


def _cell_value_changed(content: bytes, layout: Layout) -> bytes:
    assert layout.yellow is not None
    row = rb'(<c r="D%d"[^>]*><v>)\d+' % (layout.yellow + 2)
    return _part_changed(content, _SHEET, lambda xml: re.sub(row, rb"\g<1>0", xml, count=1))


def _cell_kind_changed(content: bytes, layout: Layout) -> bytes:
    assert layout.yellow is not None
    row = rb'(<c r="D%d"[^>]*?) t="s"' % (layout.yellow + 2)
    return _part_changed(content, _SHEET, lambda xml: re.sub(row, rb'\g<1> t="str"', xml, count=1))


def _blank_row_valued(cell: bytes) -> Callable[[bytes, Layout], bytes]:
    def change(content: bytes, layout: Layout) -> bytes:
        assert layout.yellow is not None
        number = layout.yellow + 5
        separator = rb'(<row r="%d"[^>]*>)' % number
        return _part_changed(content, _SHEET, lambda xml: re.sub(separator, rb"\g<1>" + cell % number, xml))

    return change


def _in_first_order(change: Callable[[bytes, int], bytes]) -> Callable[[bytes, Layout], bytes]:
    def changed(content: bytes, layout: Layout) -> bytes:
        assert layout.yellow is not None
        return _part_changed(content, _SHEET, lambda xml: change(xml, layout.yellow + 2))  # type: ignore[operator]

    return changed


def _order_row_removed(content: bytes, layout: Layout) -> bytes:
    assert layout.yellow is not None
    row = rb'<row r="%d"[^>]*>.*?</row>' % (layout.yellow + 9)
    return _part_changed(content, _SHEET, lambda xml: re.sub(row, b"", xml, count=1, flags=re.S))


# Każde zepsucie zmienia w pliku tymczasowym jedną rzecz, której pilnuje jedno sprawdzenie zapisu.
CORRUPTIONS: dict[str, Callable[[bytes, Layout], bytes]] = {
    "nie zip": lambda _content, _layout: b"to nie jest skoroszyt",
    "kolejność części": lambda content, _layout: _parts_reordered(content),
    "inna część": lambda content, _layout: _part_changed(content, "docProps/app.xml", lambda xml: xml + b" "),
    "skoroszyt poza aktywną kartą": lambda content, _layout: _part_changed(
        content, "xl/workbook.xml", lambda xml: xml.replace(b'tabRatio="600"', b'tabRatio="601"', 1)
    ),
    "inny arkusz poza zaznaczeniem karty": lambda content, _layout: _part_changed(
        content, _LIST_SHEET, lambda xml: xml.replace(b'activeCell="A1" sqref="A1"', b'activeCell="A2" sqref="A2"', 1)
    ),
    "inna aktywna karta": lambda content, _layout: _part_changed(
        content, "xl/workbook.xml", lambda xml: xml.replace(b'activeTab="1"', b'activeTab="2"', 1)
    ),
    "inny arkusz zaznaczony": lambda content, _layout: _part_changed(
        content, _LIST_SHEET, lambda xml: xml.replace(b"<sheetView ", b'<sheetView tabSelected="true" ', 1)
    ),
    "istniejący styl": lambda content, _layout: _part_changed(
        content, _STYLES, lambda xml: xml.replace(b'<sz val="11"', b'<sz val="12"', 1)
    ),
    "istniejące wypełnienie": lambda content, _layout: _part_changed(
        content, _STYLES, lambda xml: xml.replace(b'patternType="gray125"', b'patternType="gray0625"', 1)
    ),
    "lista stylów": lambda content, _layout: _part_changed(
        content, _STYLES, lambda xml: re.sub(rb"<borders\b.*?</borders>", b"", xml, flags=re.S)
    ),
    "nagłówek arkusza": _in_sheet(lambda xml: xml.replace(b"<sheetData>", b'<sheetFormatPr defaultRowHeight="20"/><sheetData>', 1)),
    "wiersze nad dniem": _in_sheet(lambda xml: xml.replace(b'<row r="2" ', b'<row r="2" hidden="1" ', 1)),
    "ogon arkusza": _in_sheet(lambda xml: xml.replace(b'<pageMargins left="0.75"', b'<pageMargins left="0.5"', 1)),
    "wartość zlecenia": _cell_value_changed,
    "rodzaj wartości zlecenia": _cell_kind_changed,
    "liczba w pustym wierszu": _blank_row_valued(b'<c r="B%d"><v>1</v></c>'),
    "tekst w pustym wierszu": _blank_row_valued(b'<c r="B%d" t="inlineStr"><is><t>x</t></is></c>'),
    "brak zlecenia": _order_row_removed,
    "dodatkowa wartość w zleceniu": _in_first_order(
        lambda xml, row: re.sub(rb'(<row r="%d"[^>]*>.*?)</row>' % row, rb'\g<1><c r="AZ%d"><v>1</v></c></row>' % row, xml, count=1, flags=re.S)
    ),
    "brak pustej komórki zlecenia": _in_first_order(lambda xml, row: re.sub(rb'<c r="B%d"[^>]*/>' % row, b"", xml, count=1)),
    "pusta komórka za UWAGI": _in_first_order(
        lambda xml, row: re.sub(rb'(<row r="%d"[^>]*>.*?)</row>' % row, rb'\g<1><c r="P%d" s="0"/></row>' % row, xml, count=1, flags=re.S)
    ),
}


@pytest.mark.parametrize("corruption", CORRUPTIONS)
def test_niezgodnosc_w_sprawdzeniu_zapisu_to_zatrzymanie_do_maksa_bez_zmiany_intermax_i_kopii(
    tmp_path: Path, corruption: str
) -> None:
    path, layout = _register(tmp_path)
    disk = FaultyDisk(write=writing(lambda data: CORRUPTIONS[corruption](data, layout)))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, disk=disk))

    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEZGODNY", "for_maks")


@pytest.mark.parametrize(
    ("column", "app_value"), [(DEVICES, "Instalacja Hurt"), (ACTIVITIES, "TMOBILE")], ids=["urzadzenia", "czynnosci"]
)
def test_wartosc_z_aplikacji_zamiast_wpisu_w_sprawdzeniu_zapisu_to_zatrzymanie_do_maksa_bez_zmiany_intermax(
    tmp_path: Path, column: int, app_value: str
) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, "TMOBILE", "Instalacja Hurt"),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 102, "TMOBILE", "Instalacja Hurt"),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))
    assert layout.yellow is not None
    reference = b"%s%d" % (get_column_letter(column).encode("ascii"), layout.yellow + 2)
    app_cell = b'<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (reference, app_value.encode("utf-8"))
    cell = re.compile(rb'<c r="%s"[^>]*?(?:/>|>.*?</c>)' % reference, re.S)
    disk = FaultyDisk(write=writing(lambda data: _part_changed(data, _SHEET, lambda xml: cell.sub(app_cell, xml, count=1))))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, disk=disk))

    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEZGODNY", "for_maks")

def test_bez_surowych_zlecen_zatrzymanie_dla_taty_i_nic_nie_zapisano(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, Intermax(raw=()))
    original = path.read_bytes()

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("BRAK_SUROWYCH_ZLECEN", "for_tata")
    assert ORDER_SHEET in stop.message.where
    assert path.read_bytes() == original
    assert not (tmp_path / "Kopie INTERMAX").exists()


def test_scalone_komorki_w_surowych_zleceniach_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    workbook = load_workbook(path)
    workbook.worksheets[1].merge_cells(start_row=layout.first_raw + 1, start_column=4, end_row=layout.first_raw + 2, end_column=4)
    workbook.save(path)
    original = path.read_bytes()

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")
    assert path.read_bytes() == original


def _first_day_row(path: Path, layout: Layout, order: Order) -> int:
    """Wiersz arkusza zleceń, w którym stoi zlecenie ``order`` (po ``NUMER ZL.``)."""

    with closing(load_workbook(path, read_only=True)) as workbook:
        numbers = [row[NUMBER - 1].value for row in workbook[ORDER_SHEET].iter_rows(min_row=1, max_col=NUMBER)]
    return numbers.index(f"ZL-{order.number}") + 1


@pytest.mark.parametrize("yellow", ["row", "cells"])
@pytest.mark.parametrize("above_yellow", [1, 3])
def test_dzien_staje_jeden_pusty_wiersz_pod_zoltym_wierszem_taty(
    tmp_path: Path, yellow: Literal["row", "cells"], above_yellow: int
) -> None:
    path, layout = _register(tmp_path, Intermax(yellow=yellow, above_yellow=above_yellow))

    _ordered(_run(tmp_path))

    assert layout.yellow == layout.last_ordered + above_yellow + 1
    assert _first_day_row(path, layout, layout.raw[1]) == layout.yellow + 2
    assert order_rows(path, layout.last_ordered + 1, layout.yellow + 1) == [None] * (above_yellow + 2)


@pytest.mark.parametrize(("cells", "under_yellow"), [(7, True), (6, False)])
def test_zolty_wiersz_to_co_najmniej_polowa_kolumn_zlecenia_w_zoltym(tmp_path: Path, cells: int, under_yellow: bool) -> None:
    path, layout = _register(tmp_path, Intermax(yellow="cells", yellow_cells=cells))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    expected = layout.yellow + 2 if under_yellow else layout.last_ordered + 11
    assert _first_day_row(path, layout, layout.raw[1]) == expected


def test_z_dwoch_zoltych_wierszy_dzien_staje_pod_nizszym(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(above_yellow=3))
    _edited(path, lambda sheet: setattr(sheet.row_dimensions[layout.last_ordered + 1], "fill", YELLOW))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert _first_day_row(path, layout, layout.raw[1]) == layout.yellow + 2


def test_zolty_wiersz_wewnatrz_wklejenia_nie_wyznacza_miejsca_dnia(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(yellow=None, gap=12))
    inside = layout.first_raw + 2

    def emptied(sheet: Worksheet) -> None:
        for column in range(1, APP_LAST + 1):
            cell = sheet.cell(inside, column)
            cell.value, cell.fill, cell.hyperlink = None, YELLOW, None

    _edited(path, emptied)

    summary = _ordered(_run(tmp_path))

    assert summary.order_count == len(layout.raw) - 1
    assert _first_day_row(path, layout, layout.raw[1]) == layout.last_ordered + 11


def test_wiersz_wklejenia_z_wykonawca_w_calibri_8_dalej_jest_surowym_zleceniem(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    last_raw = layout.first_raw + len(layout.raw) - 1
    _edited(path, lambda sheet: setattr(sheet.cell(last_raw, WORKER), "font", Font(name="Calibri", sz=8)))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_komorka_w_calibri_8_za_uwagi_nie_czyni_wiersza_wklejenia_uporzadkowanym(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    last_raw = layout.first_raw + len(layout.raw) - 1
    _edited(path, lambda sheet: setattr(sheet.cell(last_raw, APP_LAST), "font", Font(name="Calibri", sz=8)))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_uporzadkowany_wiersz_z_jedna_komorka_w_innej_czcionce_dalej_jest_uporzadkowany(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.last_ordered, 4), "font", Font(name="Arial", sz=10)))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)
    assert layout.yellow is not None
    assert _first_day_row(path, layout, layout.raw[1]) == layout.yellow + 2


def test_pierwszy_wiersz_z_data_na_miejscu_nie_jest_przesuwany_nawet_z_data_w_kolumnie_a(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(shifted=False))
    stray = datetime(2026, 10, 26, 7)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.first_raw, DATE - 2), "value", stray))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 9, layout.yellow + 9) == [(stray, *_expected(layout.raw[0])[1:])]


def test_segmenty_wykonawcow_ida_alfabetycznie_bez_wzgledu_na_wielkosc_liter(tmp_path: Path) -> None:
    raw = (
        Order(datetime(2026, 10, 26, 9), "Cezary", 201),
        Order(datetime(2026, 10, 26, 9), "anna", 202),
        Order(datetime(2026, 10, 26, 9), "Bartek", 203),
        Order(datetime(2026, 10, 26, 10), "ANNA", 204),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    summary = _ordered(_run(tmp_path))

    assert layout.yellow is not None
    rows = order_rows(path, layout.yellow + 2, layout.yellow + 8)
    assert [None if row is None else row[NUMBER - 1] for row in rows] == [
        "ZL-202",
        "ZL-204",
        None,
        "ZL-203",
        None,
        "ZL-201",
        None,
    ]
    assert summary.worker_count == 3


def test_bez_uporzadkowanych_dni_dzien_staje_10_pustych_wierszy_pod_naglowkiem_bez_wygladu_naglowka(
    tmp_path: Path,
) -> None:
    path, layout = _register(tmp_path, Intermax(ordered=(), yellow=None, grid=False, excel=False, gap=0))
    _edited(path, lambda sheet: setattr(sheet.row_dimensions[1], "height", 20))
    assert layout.first_raw == 2

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)

    assert _first_day_row(path, layout, layout.raw[1]) == 12
    assert _row_look(path, 12) == {}


def test_porzadkowany_jest_arkusz_zlecen_z_wklejeniem_a_starszy_zostaje(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(older_sheet=True))
    older = load_workbook(path)["ZLECENIA OD 08_11_2021"]
    before = [[cell.value for cell in row] for row in older.iter_rows()]

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)

    assert [[cell.value for cell in row] for row in load_workbook(path)["ZLECENIA OD 08_11_2021"].iter_rows()] == before
    assert layout.yellow is not None
    assert _first_day_row(path, layout, layout.raw[1]) == layout.yellow + 2


def _without_workbook_properties(path: Path) -> None:
    rewrite_parts(path, lambda name, data: re.sub(rb"<workbookPr\b[^>]*/>", b"", data) if name == "xl/workbook.xml" else data)


def test_data_wklejenia_we_wbudowanym_formacie_daty_excela_jest_data(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(raw_date_format=DATE_FORMAT))
    sheet = load_workbook(path)[ORDER_SHEET]
    first, *other = layout.raw_rows  # pierwszy wiersz wklejenia przychodzi przesunięty
    shown = {sheet.cell(first, DATE - PASTE_SHIFT).number_format, *(sheet.cell(row, DATE).number_format for row in other)}
    assert shown == {DATE_FORMAT}, "wklejenie ma daty we wbudowanym formacie, który test sprawdza"

    summary = _ordered(_run(tmp_path))

    assert (summary.day.isoformat(), summary.order_count) == ("2026-10-26", len(layout.raw))


@pytest.mark.parametrize("dates", ["1904", "bez workbookPr"])
def test_dzien_ma_date_z_systemu_dat_intermax(tmp_path: Path, dates: str) -> None:
    path, layout = _register(tmp_path, Intermax(epoch_1904=dates == "1904"))
    if dates != "1904":
        _without_workbook_properties(path)

    summary = _ordered(_run(tmp_path))

    assert summary.day.isoformat() == "2026-10-26"
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 2) == [_expected(layout.raw[1])]


@pytest.mark.parametrize("value", [True, 7])
def test_wiersz_z_sama_wartoscia_pod_wklejeniem_to_zlecenie_bez_daty_z_wierszem_i_kolumna(
    tmp_path: Path, value: object
) -> None:
    path, layout = _register(tmp_path)
    stray = layout.first_raw + len(layout.raw) + 1
    _edited(path, lambda sheet: setattr(sheet.cell(stray, 12), "value", value))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("SUROWE_ZLECENIE_BEZ_DATY", "for_tata")
    assert stop.message.where.endswith(f"komórka C{stray}")


def test_atrapa_stawia_pusty_wiersz_taty_nad_wskazanym_zleceniem_wklejenia_i_ramke_piec_wierszy_pod_wklejeniem(
    tmp_path: Path,
) -> None:
    path, layout = _register(tmp_path, Intermax(blank_in_paste=frozenset({2})))
    first, last = layout.first_raw, layout.first_raw + len(layout.raw)
    sheet = load_workbook(path)[ORDER_SHEET]

    assert layout.raw_rows == (first, first + 1, *range(first + 3, last + 1))
    assert order_rows(path, first + 2, first + 2) == [None]
    assert [_thin_row(sheet, number) for number in (last + 5, last + 6)] == [(BLANK_HEIGHT, "thin"), (None, None)]


def test_wiersz_z_samymi_spacjami_pod_wklejeniem_jest_pusty(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.first_raw + len(layout.raw) + 1, 12), "value", "   "))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_pusta_komorka_w_calibri_8_nie_czyni_wiersza_wklejenia_uporzadkowanym(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    last_raw = layout.first_raw + len(layout.raw) - 1
    _edited(path, lambda sheet: setattr(sheet.cell(last_raw, FIRST), "font", Font(name="Calibri", sz=8)))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_blad_i_prawda_w_komorkach_wklejenia_przechodza_do_dnia_bez_zmian(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)

    def marked(sheet: Worksheet) -> None:
        sheet.cell(layout.first_raw + 1, 12).value = True
        sheet.cell(layout.first_raw + 1, 13).value = "#N/A"

    _edited(path, marked)

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    sheet = load_workbook(path)[ORDER_SHEET]
    assert (sheet.cell(layout.yellow + 2, 12).value, sheet.cell(layout.yellow + 2, 13).value) == (True, "#N/A")


@pytest.mark.parametrize("value", ["jutro", 46321.5, None], ids=["tekst", "liczba bez formatu daty", "pusta"])
def test_surowe_zlecenie_bez_daty_to_zatrzymanie_dla_taty_z_wierszem_i_kolumna(
    tmp_path: Path, value: str | float | None
) -> None:
    path, layout = _register(tmp_path)
    row = layout.first_raw + 1

    def undated(sheet: Worksheet) -> None:
        cell = sheet.cell(row, DATE)
        cell.value, cell.number_format = value, "General"

    _edited(path, undated)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("SUROWE_ZLECENIE_BEZ_DATY", "for_tata")
    assert f"w wierszu {row} nie ma daty z godziną w kolumnie C." in stop.message.what
    assert stop.message.where == f"plik {REGISTER_NAME}, folder OneDrive, arkusz {ORDER_SHEET}, komórka C{row}"
    assert stop.message.action == f"Wpisz datę z godziną w komórce C{row}, zapisz i zamknij INTERMAX i uruchom ponownie."
    _without_order_data(stop.message, layout.raw)


@pytest.mark.parametrize(("shifted", "column"), [(True, "H"), (False, "J")])
def test_surowe_zlecenie_bez_wykonawcy_to_zatrzymanie_dla_taty_z_wierszem_i_kolumna(
    tmp_path: Path, shifted: bool, column: str
) -> None:
    path, layout = _register(tmp_path, Intermax(shifted=shifted))
    _edited(path, lambda sheet: setattr(sheet[f"{column}{layout.first_raw}"], "value", None))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("SUROWE_ZLECENIE_BEZ_WYKONAWCY", "for_tata")
    assert f"w wierszu {layout.first_raw} nie ma Wykonawcy w kolumnie {column}." in stop.message.what
    assert stop.message.where.endswith(f"komórka {column}{layout.first_raw}")
    assert stop.message.action.startswith(f"Wpisz Wykonawcę w komórce {column}{layout.first_raw}")
    _without_order_data(stop.message, layout.raw)


def test_zlecenie_bez_daty_we_wklejeniu_z_kilku_dni_to_najpierw_brak_daty(tmp_path: Path) -> None:
    """Bez daty nie wiadomo, z którego dnia jest zlecenie, więc tata najpierw wpisuje datę."""

    raw = (
        Order(datetime(2026, 10, 27, 9), "jan.nowak", 101),
        Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
        Order(datetime(2026, 10, 26, 11), "jan.nowak", 103),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))
    _edited(path, lambda sheet: setattr(sheet.cell(layout.first_raw + 2, DATE), "value", "jutro"))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert stop.message.code == "SUROWE_ZLECENIE_BEZ_DATY"
    assert stop.message.where.endswith(f"komórka C{layout.first_raw + 2}")


def test_przesuniety_pierwszy_wiersz_bez_daty_wskazuje_kolumne_a(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.first_raw, DATE - 2), "value", "jutro"))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert stop.message.code == "SUROWE_ZLECENIE_BEZ_DATY"
    assert stop.message.where.endswith(f"komórka A{layout.first_raw}")


def test_wklejenie_z_kilku_dni_to_zatrzymanie_dla_taty_z_dniami(tmp_path: Path) -> None:
    raw = (
        Order(datetime(2026, 10, 27, 9), "jan.nowak", 101),
        Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102),
        Order(datetime(2026, 10, 26, 11), "jan.nowak", 103),
    )
    path, layout = _register(tmp_path, Intermax(raw=raw))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("WKLEJENIE_Z_KILKU_DNI", "for_tata")
    assert "26.10.2026, 27.10.2026" in stop.message.what
    assert stop.message.where.endswith(f"wiersze {layout.first_raw}–{layout.first_raw + 2}")
    assert stop.message.action == (
        "Zostaw na dole arkusza zleceń zlecenia jednego dnia, a pozostałe usuń. Zapisz i zamknij INTERMAX i uruchom "
        "ponownie, a następny dzień wklej i uporządkuj osobno."
    )
    _without_order_data(stop.message, layout.raw)


def test_surowe_zlecenia_w_dwoch_arkuszach_to_zatrzymanie_dla_taty_z_nazwami_arkuszy(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(older_sheet=True))
    workbook = load_workbook(path)
    older = workbook["ZLECENIA OD 08_11_2021"]
    _raw_row(layout.raw[1])(older, older.max_row + 3)
    workbook.save(path)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("SUROWE_ZLECENIA_W_KILKU_ARKUSZACH", "for_tata")
    assert stop.message.where.endswith(f"arkusze ZLECENIA OD 08_11_2021, {ORDER_SHEET}")
    _without_order_data(stop.message, layout.raw)


@pytest.mark.parametrize("raw_below", [True, False])
def test_surowe_zlecenia_nad_uporzadkowanym_wierszem_to_zatrzymanie_dla_taty(tmp_path: Path, raw_below: bool) -> None:
    path, layout = _register(tmp_path)
    last_raw = layout.first_raw + len(layout.raw) - 1
    typed = Order(datetime(2026, 10, 25, 12), "jan.nowak", 301)

    def typed_below(sheet: Worksheet) -> None:
        _ordered_row(typed)(sheet, last_raw + 2)
        _ordered_row(replace(typed, number=303))(sheet, last_raw + 3)
        if raw_below:
            _raw_row(Order(datetime(2026, 10, 26, 7), "jan.nowak", 302))(sheet, last_raw + 5)

    _edited(path, typed_below)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI", "for_tata")
    assert f"Wiersz {last_raw} wygląda jak wklejone zlecenie, ale stoi nad uporządkowanym wierszem {last_raw + 2}." in (
        stop.message.what
    )
    assert stop.message.where.endswith(f"arkusz {ORDER_SHEET}, wiersz {last_raw}")
    assert stop.message.action == (
        "Przenieś wklejone zlecenia na dół arkusza zleceń, pod ostatni uporządkowany wiersz. Jeśli wiersz "
        f"{last_raw} jest już uporządkowany, nadaj mu czcionkę Calibri 8. Zapisz i zamknij INTERMAX i uruchom ponownie."
    )
    _without_order_data(stop.message, [*layout.raw, typed, replace(typed, number=303)])


def test_bez_wklejenia_wiersz_z_wygladem_z_aplikacji_w_starszym_dniu_nie_zatrzymuje(tmp_path: Path) -> None:
    ordered = tuple(
        Order(datetime(2026, 10, 19 if index < 12 else 20, 7 + index % 12), "anna.kowalska", index + 1) for index in range(14)
    )
    path, _ = _register(tmp_path, Intermax(ordered=ordered, raw=()))
    _edited(path, _in_other_font(2))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert stop.message.code == "BRAK_SUROWYCH_ZLECEN"


def test_bez_wklejenia_wiersz_z_wygladem_z_aplikacji_wysoko_w_ostatnim_dniu_zatrzymuje(tmp_path: Path) -> None:
    """Wiersze ostatniego dnia nie są wcześniejszym dniem, więc nie kończą przeglądu."""

    ordered = tuple(Order(datetime(2026, 10, 19, 7 + index % 12), "anna.kowalska", index + 1) for index in range(14))
    path, _ = _register(tmp_path, Intermax(ordered=ordered, raw=()))
    _edited(path, _in_other_font(2))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert stop.message.code == "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI"
    assert stop.message.where.endswith("wiersz 2")


def test_pojedyncze_wiersze_wczesniejszych_dni_miedzy_dniami_nie_koncza_przegladu(tmp_path: Path) -> None:
    def day(number: int, count: int, first: int) -> tuple[Order, ...]:
        return tuple(Order(datetime(2026, 10, number, 7 + index), "anna.kowalska", first + index) for index in range(count))

    path, _ = _register(tmp_path, Intermax(ordered=(*day(26, 2, 1), *day(25, 6, 3), *day(27, 1, 9), *day(25, 6, 10))))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert stop.message.code == "DZIEN_JUZ_UPORZADKOWANY"


@pytest.mark.parametrize(("above", "stops"), [(9, True), (10, False)])
def test_wiersz_z_wygladem_z_aplikacji_w_poprzednim_dniu_zatrzymuje_tylko_tuz_nad_wklejeniem(
    tmp_path: Path, above: int, stops: bool
) -> None:
    ordered = tuple(Order(datetime(2026, 10, 19, 7 + index), "anna.kowalska", index + 1) for index in range(12))
    path, layout = _register(tmp_path, Intermax(ordered=ordered))
    strange = layout.last_ordered - above
    _edited(path, _in_other_font(strange))

    outcome = _run(tmp_path)

    if stops:
        assert _stop(outcome).message.code == "SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI"
        assert _stop(outcome).message.where.endswith(f"wiersz {strange}")
    else:
        assert _ordered(outcome).order_count == len(layout.raw)


def test_drugie_wklejenie_tego_samego_dnia_mowi_ze_dzien_jest_uporzadkowany_i_nic_nie_zmienia(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    original = path.read_bytes()
    _ordered(_run(tmp_path))
    first_raw = _pasted_again(path, original, layout)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, now=NOW + timedelta(minutes=5)))

    assert (stop.message.code, stop.stop_kind) == ("DZIEN_JUZ_UPORZADKOWANY", "for_tata")
    assert stop.message.what == "Dzień 26.10.2026 jest już uporządkowany. INTERMAX nie został zmieniony."
    assert stop.message.action == "Nowe zlecenia na ten dzień dopisz ręcznie, a wklejone usuń."
    assert stop.message.where.endswith(f"wklejone wiersze {first_raw}–{first_raw + len(layout.raw) - 1}")
    _without_order_data(stop.message, layout.raw)


def test_wklejony_dzien_uporzadkowany_nad_nowszymi_dniami_jest_juz_uporzadkowany(tmp_path: Path) -> None:
    ordered = (
        Order(datetime(2026, 10, 26, 8), "anna.kowalska", 1),
        *(Order(datetime(2026, 10, 27, 7 + index), "jan.nowak", index + 2) for index in range(12)),
    )
    path, _ = _register(tmp_path, Intermax(ordered=ordered))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.message.what) == (
        "DZIEN_JUZ_UPORZADKOWANY",
        "Dzień 26.10.2026 jest już uporządkowany. INTERMAX nie został zmieniony.",
    )


def test_drugie_wklejenie_dnia_sprzed_tygodnia_mowi_ze_dzien_jest_uporzadkowany(tmp_path: Path) -> None:
    """Dzień sprzed 6 dni przed dzisiejszym przegląd szuka aż do niego samego (dziś 25.10, wklejony 14.10)."""

    def day(number: int, count: int, first: int) -> tuple[Order, ...]:
        return tuple(Order(datetime(2026, 10, number, 7 + index), "anna.kowalska", first + index) for index in range(count))

    path, _ = _register(tmp_path, Intermax(ordered=(*day(14, 2, 1), *day(15, 12, 3)), raw=day(14, 2, 101)))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.message.what) == (
        "DZIEN_JUZ_UPORZADKOWANY",
        "Dzień 14.10.2026 jest już uporządkowany. INTERMAX nie został zmieniony.",
    )


def test_zlecenie_na_jutro_w_srodku_dzisiejszego_dnia_z_jego_wierszami_pod_nim_nie_czyni_jutra_uporzadkowanym(tmp_path: Path) -> None:
    def day(number: int, count: int, first: int) -> tuple[Order, ...]:
        return tuple(Order(datetime(2026, 10, number, 7 + index), "anna.kowalska", first + index) for index in range(count))

    path, layout = _register(tmp_path, Intermax(ordered=(*day(25, 6, 1), *day(26, 1, 7), *day(25, 4, 8))))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_uporzadkowany_wiersz_bez_daty_nad_wklejeniem_nie_zatrzymuje(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.last_ordered, DATE), "value", None))

    assert _ordered(_run(tmp_path)).order_count == len(layout.raw)


def test_dzien_jest_uporzadkowany_takze_z_usterka_poprzedniego_dnia_dopisana_pod_nim(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(grid=False))
    original = path.read_bytes()
    _ordered(_run(tmp_path))
    first_raw = _pasted_again(path, original, layout)
    _edited(path, lambda sheet: _ordered_row(Order(datetime(2026, 10, 25, 15), "jan.nowak", 401))(sheet, first_raw - 2))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, now=NOW + timedelta(minutes=5)))

    assert stop.message.code == "DZIEN_JUZ_UPORZADKOWANY"


_TODAY = date(2026, 10, 29)
_SHEET_DAYS = st.lists(st.tuples(st.integers(-12, 4), st.integers(1, 12)), max_size=6)
"""Uporządkowane dni arkusza od góry: dzień względem ``_TODAY`` i liczba jego wierszy; dzień może iść do przodu,
wstecz albo być jedną usterką dopisaną pod innym dniem."""


def _days(days: Sequence[tuple[int, int]], first: int) -> tuple[Order, ...]:
    whens = [datetime.combine(_TODAY + timedelta(days=day), time(8 + hour)) for day, count in days for hour in range(count)]
    return tuple(Order(when, "anna.kowalska", first + index) for index, when in enumerate(whens))


@settings(derandomize=True, database=None, deadline=None, max_examples=30)
@given(newer=_SHEET_DAYS, older=st.none() | _SHEET_DAYS, pasted=st.integers(-6, 4))
def test_karta_przed_wklejeniem_pokazuje_dzien_jako_uporzadkowany_wtedy_gdy_uporzadkowanie_odmawia_jego_wklejenia(
    newer: list[tuple[int, int]], older: list[tuple[int, int]] | None, pasted: int
) -> None:
    """Losowe arkusze zleceń: dni do przodu i wstecz, usterki pod dniem, dzień w starszym arkuszu (#775).

    Tata patrzy na kartę, zanim wklei dzień, więc karta czyta INTERMAX bez wklejenia, a Uporządkowanie ten sam
    INTERMAX z wklejonym dniem, który karta pokazuje (dziś i 6 dni przed nim albo później).
    """

    day = _TODAY + timedelta(days=pasted)
    raw = (Order(datetime.combine(day, time(9)), "jan.nowak", 500), Order(datetime.combine(day, time(11)), "jan.nowak", 501))
    intermax = Intermax(
        ordered=_days(newer, 1),
        older_sheet=older is not None,
        older_ordered=None if older is None else _days(older, 100),
    )
    with TemporaryDirectory() as folder:
        tmp_path = Path(folder)
        path, _ = _register(tmp_path, replace(intermax, raw=()))
        days = register_days(path, _TODAY, DadFiles())
        _register(tmp_path, replace(intermax, raw=raw))
        outcome = _run(tmp_path, now=datetime.combine(_TODAY, time(12)))

    assert not isinstance(days, Message), days
    refused = isinstance(outcome.ending, Stop) and outcome.ending.message.code == "DZIEN_JUZ_UPORZADKOWANY"
    assert refused or isinstance(outcome.ending, Finished), outcome.ending
    assert (RegisterDay(day, True) in days) == refused


def test_recznie_przesuniety_pierwszy_wiersz_jest_surowym_zleceniem_i_nie_przesuwa_sie_drugi_raz(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: sheet.move_range(f"A{layout.first_raw}:{get_column_letter(APP_LAST - 2)}{layout.first_raw}", cols=2))

    summary = _ordered(_run(tmp_path))

    assert summary.order_count == len(layout.raw)
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 9, layout.yellow + 9) == [_expected(layout.raw[0])]


def test_formula_we_wklejeniu_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(layout.first_raw + 1, 4), "value", "=1+1"))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_hiperlacze_w_pustym_wierszu_pod_dniem_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    assert layout.yellow is not None
    first_link = rb'(<hyperlink [^>]*?ref=")I2("[^>]*>)'
    blank_link = rb"\g<0>\g<1>I%d\g<2>" % (layout.yellow + 1)
    rewrite_parts(path, lambda name, data: re.sub(first_link, blank_link, data, count=1) if name == _SHEET else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_hiperlacze_za_uwagi_w_surowym_zleceniu_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    raw_link = rb'(<hyperlink [^>]*?ref=")I%d(")' % (layout.first_raw + 1)
    beyond = rb"\g<1>%s%d\g<2>" % (get_column_letter(LAST + 1).encode("ascii"), layout.first_raw + 1)
    rewrite_parts(path, lambda name, data: re.sub(raw_link, beyond, data, count=1) if name == _SHEET else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_hiperlacze_w_uwagach_surowego_zlecenia_idzie_ze_zleceniem(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    raw_link = rb'(<hyperlink [^>]*?ref=")I%d(")' % (layout.first_raw + 1)
    in_notes = rb"\g<1>%s%d\g<2>" % (get_column_letter(LAST).encode("ascii"), layout.first_raw + 1)
    rewrite_parts(path, lambda name, data: re.sub(raw_link, in_notes, data, count=1) if name == _SHEET else data)

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    sheet = load_workbook(path).worksheets[1]
    notes = [row for row in range(layout.yellow, sheet.max_row + 1) if sheet.cell(row, LAST).hyperlink is not None]
    assert len(notes) == 1


def test_arkusz_bez_dimension_dostaje_dzien_bez_dimension(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    rewrite_parts(path, lambda name, data: re.sub(rb"<dimension [^>]*>", b"", data) if name == _SHEET else data)

    _ordered(_run(tmp_path))

    assert b"<dimension" not in parts(path)[_SHEET]
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 2) == [_expected(layout.raw[1])]


def _style_entries(xml: bytes, tag: bytes, item: bytes) -> tuple[int, list[bytes]]:
    found = re.search(rb"<" + tag + rb'\b[^>]*?count="(\d+)"[^>]*>(.*?)</' + tag + rb">", xml, re.S)
    assert found is not None, tag
    entries = re.findall(rb"<" + item + rb"\b(?:[^>]*/>|[^>]*>.*?</" + item + rb">)", found.group(2), re.S)
    return int(found.group(1)), entries


_LISTS = ((b"fonts", b"font"), (b"fills", b"fill"), (b"borders", b"border"), (b"cellXfs", b"xf"))
_COLORED = Intermax(
    raw=(
        Order(datetime(2026, 10, 26, 14), "jan.nowak", 101, "TMOBILE"),
        Order(datetime(2026, 10, 26, 10), "anna.kowalska", 102, "NETIA"),
        Order(datetime(2026, 10, 26, 16), "anna.kowalska", 103, "T-Mobile"),
        Order(datetime(2026, 10, 26, 8), "jan.nowak", 104, None, "Usterka"),
        Order(datetime(2026, 10, 26, 9), "bartek.zielinski", 105, "P4"),
    )
)
"""Surowe zlecenia z Kolorami operatora, które powtarzają wypełnienia."""


def test_dopisane_style_sa_raz_kazdy_a_licznik_count_zgadza_sie_z_lista(tmp_path: Path) -> None:
    path, _ = _register(tmp_path, _COLORED)
    before = parts(path)[_STYLES]

    _ordered(_run(tmp_path))

    after = parts(path)[_STYLES]
    for tag, item in _LISTS:
        count, entries = _style_entries(after, tag, item)
        added = entries[len(_style_entries(before, tag, item)[1]) :]
        assert count == len(entries), tag
        assert len(set(added)) == len(added), tag
    assert len(_style_entries(after, b"cellXfs", b"xf")[1]) > len(_style_entries(before, b"cellXfs", b"xf")[1])
    # Zielony, ciemniejszy i jasny niebieski oraz różowy, każdy raz.
    assert len(_style_entries(after, b"fills", b"fill")[1]) == len(_style_entries(before, b"fills", b"fill")[1]) + 4


def _pasted_again(path: Path, original: bytes, layout: Layout, *, days: int = 0) -> int:
    """Te same wiersze wklejenia co w ``original`` doklejone w XML pod ostatni wiersz ``path``, jak drugie wklejenie.

    Daty zleceń są ``days`` dni później. Zwraca pierwszy wiersz nowego wklejenia.
    """

    numbers = range(layout.first_raw, layout.first_raw + len(layout.raw))
    source = zipfile.ZipFile(BytesIO(original)).read(_SHEET)
    rows = [re.search(rb'<row r="%d"[^>]*>.*?</row>' % number, source, re.S) for number in numbers]
    last = max(int(number) for number in re.findall(rb'<row r="(\d+)"', parts(path)[_SHEET]))

    def renumbered(index: int, row: re.Match[bytes] | None) -> bytes:
        assert row is not None
        number = b"%d" % (last + 3 + index)
        cells = re.sub(rb'(<c r="[A-Z]+)\d+"', rb'\g<1>' + number + b'"', row.group(0))
        cells = re.sub(
            rb'(<c r="[AC]\d+"(?:(?! t=")[^>])*><v>)([\d.]+)(</v>)',
            lambda date: date.group(1) + b"%r" % (float(date.group(2)) + days) + date.group(3),
            cells,
        )
        return re.sub(rb'<row r="\d+"', b'<row r="' + number + b'"', cells, count=1)

    pasted = b"".join(renumbered(index, row) for index, row in enumerate(rows))
    rewrite_parts(path, lambda name, data: data.replace(b"</sheetData>", pasted + b"</sheetData>") if name == _SHEET else data)
    return last + 3


def test_kolor_operatora_bierze_wypelnienie_ktore_tata_juz_ma_w_intermax(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(raw=(Order(datetime(2026, 10, 26, 8), "jan.nowak", 101, "TMOBILE"),)))
    green = PatternFill(patternType="solid", fgColor=Color(rgb=_GREEN), bgColor=Color(indexed=64))
    _edited(path, lambda sheet: setattr(sheet.cell(2, ACTIVITIES), "fill", green))
    before = _style_entries(parts(path)[_STYLES], b"fills", b"fill")

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert _fills(load_workbook(path).worksheets[1], layout.yellow + 2)[ACTIVITIES] == _GREEN
    assert _style_entries(parts(path)[_STYLES], b"fills", b"fill") == before


def test_kolejne_uporzadkowanie_nie_dopisuje_stylow_ktore_juz_sa(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, replace(_COLORED, grid=False))
    original = path.read_bytes()
    _ordered(_run(tmp_path))
    first = parts(path)[_STYLES]
    _pasted_again(path, original, layout, days=1)

    assert _ordered(_run(tmp_path, now=NOW + timedelta(days=1))).order_count == len(layout.raw)

    second = parts(path)[_STYLES]
    for tag, item in _LISTS:
        assert _style_entries(second, tag, item) == _style_entries(first, tag, item), tag


def _thin_row(sheet: Worksheet, number: int) -> tuple[float | None, str | None]:
    look = sheet.row_dimensions[number]
    return look.height, look.border.left.style


def _row_look(path: Path, number: int) -> dict[bytes, bytes]:
    """Atrybuty ``<row>`` wiersza ``number`` arkusza zleceń bez numeru i ``spans``."""

    tag = re.match(rb"<row\b[^>]*", _row_xml(path, number))
    assert tag is not None
    attributes = dict(re.findall(rb'\s([\w:]+)="([^"]*)"', tag.group(0)))
    return {name: value for name, value in attributes.items() if name not in (b"r", b"spans")}


@pytest.mark.parametrize("grid", [True, False])
def test_wiersze_nowego_dnia_maja_wysokosc_i_styl_wierszy_poprzednich_dni(tmp_path: Path, grid: bool) -> None:
    path, layout = _register(tmp_path, Intermax(gap=10, grid=grid))
    assert layout.yellow is not None
    yellow = layout.yellow
    order_look = _row_look(path, layout.last_ordered)
    blank_look = _row_look(path, layout.last_ordered + 1) if grid else order_look
    kept = {number: _row_xml(path, number) for number in (yellow + 1, yellow + 10)} if grid else {}

    _ordered(_run(tmp_path))

    sheet = load_workbook(path)[ORDER_SHEET]
    for number in (yellow + 2, yellow + 3, yellow + 4, yellow + 6, yellow + 8, yellow + 9):
        assert _thin_row(sheet, number) == (ORDER_HEIGHT, "thin"), number
        assert _row_look(path, number) == order_look, number
    for number in (yellow + 5, yellow + 7):
        assert _thin_row(sheet, number) == (ORDER_HEIGHT, "thin"), number
        assert _row_look(path, number) == order_look, number
        assert {sheet.cell(number, column).border.left.style for column in range(FIRST, LAST + 1)} == {"thin"}, number
    blank_height = BLANK_HEIGHT if grid else ORDER_HEIGHT
    vacated = range(layout.first_raw, layout.first_raw + len(layout.raw))
    for number in (yellow + 1, yellow + 10, *vacated):
        assert _thin_row(sheet, number) == (blank_height, "thin"), number
        assert _row_look(path, number) == blank_look, number
    assert order_rows(path, yellow + 10, vacated[-1]) == [None] * (vacated[-1] - yellow - 9)
    assert {number: _row_xml(path, number) for number in kept} == kept, "pusty wiersz taty zostaje bajt w bajt"


def test_pusty_wiersz_pod_dniem_ma_wyglad_pustego_wiersza_taty_a_nie_zoltego(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(above_yellow=0, gap=10))
    blank_look = _row_look(path, layout.first_raw - 1)

    _ordered(_run(tmp_path))

    for number in range(layout.first_raw, layout.first_raw + len(layout.raw)):
        assert _row_look(path, number) == blank_look, number


def test_zolty_wiersz_pod_wklejeniem_nie_wyznacza_miejsca_dnia(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    below = layout.first_raw + len(layout.raw) + 1
    _edited(path, lambda sheet: setattr(sheet.row_dimensions[below], "fill", YELLOW))

    _ordered(_run(tmp_path))

    assert layout.yellow is not None
    assert _first_day_row(path, layout, layout.raw[1]) == layout.yellow + 2


def test_styl_wiersza_bez_customformat_nie_czyni_wiersza_zoltym(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    assert layout.yellow is not None
    yellow_row = rb'(<row r="%d"[^>]*?) customFormat="1"' % layout.yellow
    rewrite_parts(path, lambda name, data: re.sub(yellow_row, rb"\g<1>", data) if name == _SHEET else data)

    _ordered(_run(tmp_path))

    assert _first_day_row(path, layout, layout.raw[1]) == layout.last_ordered + 11


def test_kopia_o_tej_samej_nazwie_zostaje_a_intermax_nie_jest_zmieniony(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    copies = tmp_path / "Kopie INTERMAX"
    copies.mkdir()
    (copies / COPY_NAME).write_bytes(b"kopia sprzed minuty")

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("KOPIA_INTERMAX_NIEUDANA", "for_tata")
    assert (copies / COPY_NAME).read_bytes() == b"kopia sprzed minuty"


def test_folder_kopii_ktorego_nie_da_sie_utworzyc_to_zatrzymanie_dla_taty_bez_zapisu(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    (tmp_path / "Kopie INTERMAX").write_bytes(b"plik zamiast folderu")
    original = path.read_bytes()

    stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("KOPIA_INTERMAX_NIEUDANA", "for_tata")
    assert path.read_bytes() == original
    assert [entry.name for entry in path.parent.iterdir()] == [REGISTER_NAME]


def _lock(tmp_path: Path) -> Callable[[], object]:
    """Tata otwiera INTERMAX w Excelu: plik blokady obok INTERMAX."""

    return lambda: (tmp_path / "OneDrive" / f"~${REGISTER_NAME}").write_bytes(b"")


CONFLICT_ACTION: Final = (
    "Otwórz w Excelu INTERMAX i tę kopię, przepisz do INTERMAX zmiany, których w nim brakuje, zapisz go i usuń kopię."
)


@pytest.mark.parametrize("excel", [False, True], ids=["intermax-zamkniety", "intermax-otwarty-w-excelu"])
def test_kopia_konfliktu_onedrive_obok_intermax_to_zatrzymanie_dla_taty_z_jej_nazwa_bez_kopii_intermax_i_zapisu(
    tmp_path: Path, excel: bool
) -> None:
    path, layout = _register(tmp_path)
    conflict = path.with_name(f"{path.stem}-LAPTOP-ANDRZEJA{path.suffix}")
    conflict.write_bytes(path.read_bytes())
    older = tmp_path / "Kopie INTERMAX" / "INTERMAX przed uporządkowaniem 2026-10-24 20-00-00.xlsx"
    older.parent.mkdir()
    older.write_bytes(b"starsza kopia")
    if excel:
        _lock(tmp_path)()

    with _nothing_written(tmp_path, path):
        outcome = _run(tmp_path)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == ("KOPIA_KONFLIKTU_INTERMAX", "for_tata")
    assert stop.message.what == (
        "Obok INTERMAX leży kopia konfliktu OneDrive: OneDrive ma dwie wersje INTERMAX. INTERMAX nie został zmieniony."
    )
    assert stop.message.where == f"plik {conflict.name}, folder OneDrive"
    assert stop.message.action == f"{CONFLICT_ACTION} Potem uruchom ponownie."
    assert conflict.read_bytes() == path.read_bytes()
    assert (_copies(tmp_path), older.read_bytes()) == ({older.name}, b"starsza kopia")
    _without_order_data(stop.message, layout.raw)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        pytest.param("{stem} - Kopia{suffix}", None, id="kopia-z-eksploratora"),
        pytest.param(".{stem}.k2x9{suffix}", None, id="plik-tymczasowy-zapisu"),
        pytest.param("~${stem}{suffix}", "INTERMAX_OTWARTY", id="plik-blokady-excela"),
    ],
)
def test_kopia_z_eksploratora_plik_tymczasowy_i_plik_blokady_obok_intermax_nie_sa_kopia_konfliktu(
    tmp_path: Path, name: str, code: str | None
) -> None:
    path, _ = _register(tmp_path)
    path.with_name(name.format(stem=path.stem, suffix=path.suffix)).write_bytes(b"syntetyczny")

    outcome = _run(tmp_path)

    if code is None:
        assert _ordered(outcome).copy_name == COPY_NAME
    else:
        assert _stop(outcome).message.code == code


def test_odmowa_podmiany_bez_excela_po_krotkiej_ponownej_probie_to_onedrive_dla_taty(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    replace, attempts = failing_replace(denied)
    clock = ManualClock(seconds=4000.0)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, clock=clock, disk=FaultyDisk(replace=replace)))

    assert (stop.message.code, stop.stop_kind) == ("INTERMAX_SYNCHRONIZOWANY", "for_tata")
    assert stop.message.what == "OneDrive jeszcze synchronizuje INTERMAX. INTERMAX nie został zmieniony."
    assert stop.message.action == "Poczekaj, aż OneDrive skończy synchronizację, potem uruchom ponownie."
    assert (clock.seconds, len(attempts)) == (4005.0, 11)
    _without_order_data(stop.message, layout.raw)


def test_odmowa_podmiany_przy_otwartym_excelu_to_zatrzymanie_dla_taty_bez_czekania(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    replace, attempts = failing_replace(denied, before=_lock(tmp_path))
    clock = ManualClock()

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, clock=clock, disk=FaultyDisk(replace=replace)))

    assert (stop.message.code, stop.stop_kind) == ("INTERMAX_OTWARTY", "for_tata")
    assert (clock.seconds, len(attempts)) == (0.0, 1)


def test_inny_blad_podmiany_niz_odmowa_to_zatrzymanie_dla_taty_bez_czekania(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    replace, attempts = failing_replace(no_space)
    clock = ManualClock()

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, clock=clock, disk=FaultyDisk(replace=replace)))

    # Pełny dysk to nie Excel: tata słyszy o wolnym miejscu, nie „INTERMAX otwarty” (#716).
    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEUDANY", "for_tata")
    assert stop.message.what == "Nie udało się zapisać INTERMAX. INTERMAX nie został zmieniony."
    assert stop.message.action.startswith("Sprawdź, czy na dysku jest wolne miejsce")
    assert stop.message.dad_file is None
    assert (clock.seconds, len(attempts)) == (0.0, 1)
    _without_order_data(stop.message, layout.raw)


@pytest.mark.parametrize(("content", "code"), [(None, "BRAK_INTERMAX"), (b"to nie jest skoroszyt", "NIECZYTELNY_INTERMAX")])
def test_brak_albo_nieczytelny_intermax_to_zatrzymanie_dla_taty(tmp_path: Path, content: bytes | None, code: str) -> None:
    folder = tmp_path / "OneDrive"
    folder.mkdir()
    if content is not None:
        (folder / REGISTER_NAME).write_bytes(content)

    outcome = _run(tmp_path)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == (code, "for_tata")
    stopped = ProgressPhase.CHECKING if content is None else ProgressPhase.READING
    assert outcome.progress.phase_states[stopped] == PhaseState.FAILED
    assert sorted(entry.name for entry in folder.iterdir()) == ([] if content is None else [REGISTER_NAME])
    assert not _copies(tmp_path)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"</sst>", b""),
        (b"</sst>", b"</sst"),
        (b"</t></si>", b"&zepsuta;</t></si>"),
        (b"<t>", b'<t p:a="1">'),
        (b"</si><si>", b"</si><!-- komentarz --><si>"),
        (b"</si></sst>", b"<!-- komentarz --></si></sst>"),
        (b"spreadsheetml/2006/main", b"spreadsheetml/2006/inna"),
    ],
    ids=[
        "bez-konca-korzenia",
        "urwany-koniec-korzenia",
        "nieznana-encja",
        "prefiks-bez-przestrzeni-nazw",
        "komentarz-miedzy-tekstami",
        "komentarz-w-ostatnim-tekscie",
        "inna-przestrzen-nazw",
    ],
)
def test_teksty_wspolne_zepsute_albo_w_ksztalcie_spoza_listy_to_nieczytelny_intermax_bez_zapisu(
    tmp_path: Path, old: bytes, new: bytes
) -> None:
    """Teksty wspólne, których parser XML nie przeczyta (także z nieznaną encją albo prefiksem bez przestrzeni nazw),
    albo w kształcie, którego granic tekstów Uporządkowanie nie zna (komentarz między tekstami albo w ostatnim, inna
    przestrzeń nazw): INTERMAX jest nieczytelny, także gdy wiersze z dołu arkusza sięgają tylko po teksty przed
    usterką."""

    path, _ = _register(tmp_path)
    rewrite_parts(path, lambda name, data: data.replace(old, new, 1) if name == "xl/sharedStrings.xml" else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIECZYTELNY_INTERMAX", "for_tata")


@pytest.mark.parametrize(
    ("part", "relationship"),
    [("xl/_rels/workbook.xml.rels", "/styles"), ("_rels/.rels", "/officeDocument")],
    ids=["bez-stylow", "bez-dokumentu-skoroszytu"],
)
def test_skoroszyt_bez_czesci_stylow_albo_dokumentu_to_nieczytelny_intermax_bez_zapisu(
    tmp_path: Path, part: str, relationship: str
) -> None:
    """Paczka, której relacje nie wskazują stylów albo dokumentu skoroszytu: Excel takiej nie zapisuje, a tata słyszy o
    nieczytelnym INTERMAX, nie o błędzie narzędzia."""

    path, _ = _register(tmp_path)
    dropped = re.compile(rb'<Relationship [^>]*Type="[^"]*%s"[^>]*/>' % re.escape(relationship.encode()))
    rewrite_parts(path, lambda name, data: dropped.sub(b"", data) if name == part else data)

    with _nothing_written(tmp_path, path):
        outcome = _run(tmp_path)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == ("NIECZYTELNY_INTERMAX", "for_tata")
    assert outcome.progress.phase_states[ProgressPhase.READING] == PhaseState.FAILED


def test_skoroszyt_bez_arkusza_to_nieczytelny_intermax_bez_zapisu(tmp_path: Path) -> None:
    """Skoroszyt, którego dokument nie wymienia żadnego arkusza: Excel takiego nie zapisuje, a openpyxl go nie otwiera,
    więc tata słyszy o nieczytelnym INTERMAX, tak jak w Przygotowaniu pliku zbiorczego, a nie o braku arkusza zleceń."""

    path, _ = _register(tmp_path)
    without_sheet(path)

    with _nothing_written(tmp_path, path):
        outcome = _run(tmp_path)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == ("NIECZYTELNY_INTERMAX", "for_tata")
    assert outcome.progress.phase_states[ProgressPhase.READING] == PhaseState.FAILED


def test_obramowanie_w_stylach_ktorego_nie_da_sie_odczytac_to_nieczytelny_intermax_bez_zapisu(tmp_path: Path) -> None:
    """Obramowanie ze stylem linii spoza listy Excela: Odczyt danych go nie potrzebuje, a zapis dnia rozszerza style
    o obramowania, więc tata słyszy o nieczytelnym INTERMAX, zanim cokolwiek się zapisze."""

    path, _ = _register(tmp_path)
    rewrite_parts(path, lambda name, data: data.replace(b"<border><left />", b'<border><left style="zly" />', 1) if name == _STYLES else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIECZYTELNY_INTERMAX", "for_tata")


def test_pusty_tekst_wspolny_i_biale_znaki_przy_si_nie_przesuwaja_tekstow_zlecen(tmp_path: Path) -> None:
    """``<si/>`` na początku listy tekstów wspólnych i ``<si >`` w nowej linii przy każdym innym: poprawny XML, którego
    Excel nie zapisuje, a który Uporządkowanie czyta tak samo jak zwykły."""

    path, layout = _register(tmp_path)
    shifted = re.compile(rb'(<c [^>]*?t="s"[^>]*><v>)(\d+)')

    def with_empty_first(name: str, data: bytes) -> bytes:
        if name == "xl/sharedStrings.xml":
            return re.sub(rb"(<sst\b[^>]*>)", rb"\g<1>\n<si/>", data.replace(b"<si>", b"\n<si >"), count=1)
        if name.startswith("xl/worksheets/sheet"):
            return shifted.sub(lambda found: found.group(1) + b"%d" % (int(found.group(2)) + 1), data)
        return data

    rewrite_parts(path, with_empty_first)

    summary = _ordered(_run(tmp_path))

    assert summary.order_count == len(layout.raw)
    assert layout.yellow is not None
    assert order_rows(path, layout.yellow + 2, layout.yellow + 2) == [_expected(layout.raw[1])]


@pytest.mark.parametrize("header", ["AKCJE", "UWAGI", "WYKONAWCA"])
def test_bez_naglowka_zlecen_w_wierszu_1_zatrzymanie_dla_taty_bez_zapisu(tmp_path: Path, header: str) -> None:
    path, _ = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(1, FIRST + HEADERS.index(header)), "value", f"{header} X"))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("BRAK_ARKUSZA_ZLECEN", "for_tata")


def test_powtorzony_naglowek_adres_zatrzymuje_uporzadkowanie_dla_taty_bez_zapisu(tmp_path: Path) -> None:
    """Druga kolumna ``ADRES`` w wierszu 1 (tu za ``UWAGI``): nie wiadomo, z której kolumny brać dane, a pamięć reguły
    danych znałaby tylko jedną z nich, więc Uporządkowanie zatrzymuje się jak Przygotowanie na tym samym pliku."""

    path, _ = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(1, LAST + 1), "value", "ADRES"))

    with _nothing_written(tmp_path, path):
        outcome = _run(tmp_path)

    stop = _stop(outcome)
    assert (stop.message.code, stop.stop_kind) == ("POWTORZONY_NAGLOWEK_INTERMAX", "for_tata")
    assert stop.message.where == f"plik {REGISTER_NAME}, folder OneDrive, arkusz {ORDER_SHEET}, wiersz 1"
    assert outcome.progress.phase_states[ProgressPhase.READING] == PhaseState.FAILED


def test_karta_przed_wklejeniem_bez_arkusza_zlecen_mowi_to_samo_co_uporzadkowanie(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    _edited(path, lambda sheet: setattr(sheet.cell(1, FIRST + HEADERS.index("AKCJE")), "value", "AKCJE X"))

    days = register_days(path, _TODAY, DadFiles())

    assert isinstance(days, Message) and days.code == "BRAK_ARKUSZA_ZLECEN", days


def test_nieudane_usuniecie_starszej_kopii_to_ostrzezenie_przy_uporzadkowanym_intermax(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)
    original = path.read_bytes()
    copies = tmp_path / "Kopie INTERMAX"
    copies.mkdir()
    for day in range(10, 20):
        (copies / f"INTERMAX przed uporządkowaniem 2026-10-{day:02d} 07-00-00.xlsx").write_bytes(b"kopia")
    oldest = copies / "INTERMAX przed uporządkowaniem 2026-10-09 07-00-00.xlsx"
    oldest.mkdir()  # usunięcie dostaje błąd systemu plików, jak Kopia otwarta w Excelu na Windows

    summary = _ordered(_run(tmp_path))

    assert [warning.code for warning in summary.warnings] == ["STARE_KOPIE_INTERMAX"]
    assert "uporządkowany" in summary.warnings[0].what
    assert path.read_bytes() != original
    assert (copies / COPY_NAME).read_bytes() == original


def test_podsumowanie_ktorego_nie_da_sie_pokazac_mowi_ze_intermax_jest_uporzadkowany(tmp_path: Path) -> None:
    _register(tmp_path)
    inputs = OrderingInputs(tmp_path / "OneDrive" / REGISTER_NAME, tmp_path / "Kopie INTERMAX", lambda: NOW)

    def broken(_inputs: OrderingInputs, _summary: OrderingSummary) -> OrderingSummary:
        raise RuntimeError("widok")

    outcome = run_process(
        PROCESS,
        inputs,
        Tata(),
        view=broken,
        metrics_path=tmp_path / "m.jsonl",
        context=RunContext(clock=RunClock(ManualClock())),
    )

    stop = _stop(outcome)
    assert (stop.kind, stop.message.code, stop.stop_kind) == ("after_engine", "BLAD_PODSUMOWANIA", "for_maks")


def test_niedostepny_intermax_to_zatrzymanie_dla_taty_bez_zapisu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, _ = _register(tmp_path)
    read_bytes = Path.read_bytes

    def blocked(target: Path) -> bytes:
        if target.name == REGISTER_NAME:
            raise PermissionError(errno.EACCES, "Permission denied")
        return read_bytes(target)

    with _nothing_written(tmp_path, path):
        monkeypatch.setattr(Path, "read_bytes", blocked)
        stop = _stop(_run(tmp_path))
        monkeypatch.undo()

    assert (stop.message.code, stop.stop_kind) == ("NIEDOSTEPNY_INTERMAX", "for_tata")


def test_nieoczekiwany_blad_przed_podmiana_mowi_ze_intermax_nie_zostal_zmieniony(tmp_path: Path) -> None:
    path, _ = _register(tmp_path)

    def broken(_temporary: Path, _content: bytes) -> None:
        raise RuntimeError("zapis")

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, disk=FaultyDisk(write=broken)))

    assert (stop.kind, stop.message.code, stop.stop_kind) == ("unexpected", "BLAD_NIEOCZEKIWANY", "for_maks")
    assert "INTERMAX nie został zmieniony." in stop.message.what


@pytest.mark.parametrize(("rows", "stops"), [("yellow", False), ("above", False), ("whole column", True)])
def test_zakres_za_danymi_arkusza_zatrzymuje_tylko_gdy_siega_pod_zolty_wiersz(
    tmp_path: Path, rows: str, stops: bool
) -> None:
    path, layout = _register(tmp_path)
    assert layout.yellow is not None
    yellow = layout.yellow

    def ranged(sheet: Worksheet) -> None:
        if rows == "yellow":
            sheet.merge_cells(start_row=yellow - 1, start_column=FIRST, end_row=yellow, end_column=FIRST)
        elif rows == "above":
            sheet.merge_cells(start_row=2, start_column=LAST, end_row=3, end_column=LAST)

    if rows == "whole column":
        rule = b'<conditionalFormatting sqref="L:L"><cfRule type="expression" priority="1"><formula>1</formula></cfRule></conditionalFormatting>'
        rewrite_parts(path, lambda name, data: data.replace(b"<hyperlinks>", rule + b"<hyperlinks>") if name == _SHEET else data)
    else:
        _edited(path, ranged)

    outcome = _run(tmp_path)

    if stops:
        assert (_stop(outcome).message.code, _stop(outcome).stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")
    else:
        assert _ordered(outcome).order_count == len(layout.raw)


def test_hiperlacze_na_kilka_komorek_we_wklejeniu_to_zatrzymanie_do_maksa_bez_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path)
    first = rb'(<hyperlink [^>]*?ref=")I%d(")' % (layout.first_raw + 1)
    wide = rb"\g<1>I%d:I%d\g<2>" % (layout.first_raw + 1, layout.first_raw + 2)
    rewrite_parts(path, lambda name, data: re.sub(first, wide, data, count=1) if name == _SHEET else data)

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path))

    assert (stop.message.code, stop.stop_kind) == ("NIEOBSLUGIWANY_UKLAD_INTERMAX", "for_maks")


def test_wiersz_wklejenia_pozostawiony_na_miejscu_to_niezgodnosc_zapisu(tmp_path: Path) -> None:
    path, layout = _register(tmp_path, Intermax(gap=10))
    raw_row = _row_xml(path, layout.first_raw + 1)
    row = rb'<row r="%d"[^>]*?(?:/>|>.*?</row>)' % (layout.first_raw + 1)

    def left_in_place(data: bytes) -> bytes:
        return _part_changed(data, _SHEET, lambda xml: re.sub(row, lambda _found: raw_row, xml, count=1, flags=re.S))

    with _nothing_written(tmp_path, path):
        stop = _stop(_run(tmp_path, disk=FaultyDisk(write=writing(left_in_place))))

    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEZGODNY", "for_maks")


# Historia adresu (spec #2079, #2080). Wartości oczekiwane biorą się z hasła Historia adresu w GLOSSARY.md i specu:
# wiersze Bazy zleceń z tym samym adresem od kolumny P, od najnowszej daty realizacji, każdy w szerokości swojego
# arkusza, co drugi od pierwszego na tle D9D9D9, a kolumna A zlecenia z Historią adresu FF0000.

_LOGIN = "jan.nowak"
P = LAST + 1
GRAY, RED = "FFD9D9D9", "FFFF0000"


def _order(index: int, address: str, number: int | None = None, *, without_city: bool = False) -> Order:
    """Surowe zlecenie Wykonawcy ``_LOGIN`` o godzinie 7 + ``index``, więc w dniu stoi na miejscu ``index``, z
    ``MIASTO`` atrapy (``Miastko``) albo, ``without_city``, z pustym."""

    number = 300 + index if number is None else number
    city = ((CITY, None),) if without_city else ()
    return Order(datetime(2026, 10, 26, 7 + index), _LOGIN, number, cells=((ADDRESS, address), *city))


def _visit(
    address: str,
    mark: str,
    when: datetime | str | None = datetime(2024, 1, 1),
    number: int | str | None = 9000,
    city: str | None = None,
) -> Visit:
    return Visit(address, when, number, mark, city)


@dataclass(frozen=True)
class Day:
    """Dzień do uporządkowania: INTERMAX na dysku, wiersz pierwszego zlecenia po Uporządkowaniu i zlecenia po kolei."""

    path: Path
    first: int
    orders: tuple[Order, ...]

    def sheet(self) -> Worksheet:
        return load_workbook(self.path).worksheets[1]

    def row(self, order: Order) -> int:
        return self.first + self.orders.index(order)

    def after_uwagi(self, sheet: Worksheet, order: Order) -> tuple[object, ...]:
        """Wartości każdej komórki, którą wiersz zlecenia ma w pliku od kolumny P, po kolei."""

        return tuple(sheet.cell(self.row(order), column).value for column in self.written(order) if column >= P)

    def written(self, order: Order) -> list[int]:
        """Kolumny komórek, które wiersz zlecenia ma w XML arkusza zleceń, także pustych."""

        row = self.row(order)
        found = re.search(rb'<row r="%d"[^>]*?(?:/>|>.*?</row>)' % row, parts(self.path)[_SHEET], re.S)
        assert found is not None, row
        return [column_index_from_string(letters.decode("ascii")) for letters in re.findall(rb'<c r="([A-Z]+)\d+"', found.group(0))]


def _base_path(tmp_path: Path) -> Path:
    return tmp_path / "OneDrive" / ORDER_BASE_NAME


def _day(tmp_path: Path, orders: Sequence[Order], sheets: Sequence[BaseSheet] | None) -> Day:
    """INTERMAX z wklejeniem ``orders`` i, gdy ``sheets`` nie jest ``None``, Baza zleceń z tymi arkuszami obok niego."""

    folder = tmp_path / "OneDrive"
    folder.mkdir(exist_ok=True)
    layout = Intermax(raw=tuple(orders)).write(folder / REGISTER_NAME)
    if sheets is not None:
        write_order_base(_base_path(tmp_path), sheets)
    assert layout.yellow is not None
    return Day(folder / REGISTER_NAME, layout.yellow + 2, tuple(orders))


def _blocks(*found: tuple[BaseLayout, Visit]) -> tuple[object, ...]:
    """Oczekiwane wartości od kolumny P: bloki wierszy Bazy po kolei, każdy w szerokości swojego układu."""

    return tuple(value for layout, visit in found for value in visit.values(layout))


def _fill(sheet: Worksheet, row: int, column: int) -> str | None:
    cell = sheet.cell(row, column)
    return cell.fill.fgColor.rgb if cell.fill.fill_type == "solid" else None


# Reguła tego samego adresu (historyjki 10–17 specu #2079): adres zlecenia i wiersze Bazy z tym adresem zapisanym
# inaczej, z krótszą albo dłuższą nazwą ulicy i z miastem albo bez niego, które trafiają, obok wierszy, które nie
# trafiają, bo różnią się mieszkaniem, budynkiem, nazwą ulicy poza jej końcem od granicy słowa, miastem przy miastach w
# obu wierszach albo nie mają numeru. Miasto zlecenia to ``Miastko`` z atrapy INTERMAX, chyba że jest puste; miasto
# z dzielnicą po myślniku to to samo miasto (decyzja Maksa z 18.11.2026), a miasto z tym samym początkiem nazwy albo
# kodem pocztowym nie.
_LIPOWA_18_3 = _order(0, "UL. LIPOWA 18/3")
_LIPOWA_34_2 = _order(1, "UL. LIPOWA 34/2")
_LIPOWA_34 = _order(2, "UL. LIPOWA 34")
_KASZTANOWA = _order(3, "UL. KASZTANOWA 26A/15B")
_ZIELONE = _order(4, "OS. ZIELONE 3")
_MOSTOWA = _order(5, "AL. GEN. MOSTOWA 5")
_RYNKOWY = _order(6, "PL. RYNKOWY 9/1")
_NIEZNANA = _order(7, "UL. NIEZNANA 1")
_BEZ_NUMERU = _order(8, "UL. LIPOWA")
_BEZ_ULICY = _order(9, "UL. 18/3")
_JANA_KOWALSKIEGO = _order(10, "UL. JANA KOWALSKIEGO 4/15")
_KOWALSKIEGO = _order(11, "KOWALSKIEGO 6/2")
_BRZOZOWA = _order(12, "UL. BRZOZOWA 5")
_BRZOZOWA_BEZ_MIASTA = _order(13, "UL. BRZOZOWA 5", without_city=True)
RULE_ORDERS: Final = (
    _LIPOWA_18_3, _LIPOWA_34_2, _LIPOWA_34, _KASZTANOWA, _ZIELONE, _MOSTOWA, _RYNKOWY, _NIEZNANA, _BEZ_NUMERU, _BEZ_ULICY,
    _JANA_KOWALSKIEGO, _KOWALSKIEGO, _BRZOZOWA, _BRZOZOWA_BEZ_MIASTA,
)
_V: Final = {
    "miasto przed przecinkiem i zero wiodące": (FIVE, _visit("Miastko,Lipowa 018/3", "a", datetime(2025, 5, 1))),
    "inne mieszkanie": (ELEVEN, _visit("UL. LIPOWA 18/7", "b")),
    "inna ulica": (ELEVEN, _visit("UL. GRUSZKOWA 18/3", "r")),
    "bez mieszkania obok mieszkania": (TWELVE, _visit("LIPOWA 18", "c")),
    "bez UL.": (TWELVE, _visit("LIPOWA 18/3", "d", datetime(2024, 5, 1))),
    "dom": (TWELVE, _visit("LIPOWA 34", "e", datetime(2023, 5, 1))),
    "mieszkanie małymi literami": (ELEVEN, _visit("lipowa 34/2", "f", datetime(2022, 5, 1))),
    "inne mieszkanie domu": (TWELVE, _visit("LIPOWA 34/7", "g")),
    "ukośnik bez mieszkania": (FIVE, _visit("Miastko,Lipowa 034/", "h", datetime(2019, 5, 1))),
    "litery małe": (ELEVEN, _visit("kasztanowa 26a/15b", "i", datetime(2021, 5, 1))),
    "bez litery mieszkania": (TWELVE, _visit("KASZTANOWA 26A/15", "j")),
    "bez litery budynku": (TWELVE, _visit("KASZTANOWA 26/15B", "k")),
    "kropka bez spacji i zero": (TWELVE, _visit("os.zielone 03", "l", datetime(2024, 6, 1))),
    "wielokrotne spacje": (ELEVEN, _visit("OS.  ZIELONE   3", "m", datetime(2021, 6, 1))),
    "kropki w nazwie": (ELEVEN, _visit("AL GEN MOSTOWA 5", "n", datetime(2021, 7, 1))),
    "przedrostek sklejony z miastem": (FIVE, _visit("Miastko,PL.RYNKOWY 9/1", "o", datetime(2019, 7, 1))),
    "sama ulica": (TWELVE, _visit("LIPOWA", "p")),
    "sam numer": (TWELVE, _visit("18/3", "q")),
    "krótsza nazwa ulicy": (ELEVEN, _visit("KOWALSKIEGO 4/15", "s", datetime(2021, 8, 1))),
    "dłuższa nazwa ulicy": (TWELVE, _visit("UL. JANA KOWALSKIEGO 6/2", "t", datetime(2025, 8, 1))),
    "koniec słowa": (TWELVE, _visit("SKIEGO 4/15", "u")),
    "koniec nazwy od środka słowa": (TWELVE, _visit("ANA KOWALSKIEGO 4/15", "v")),
    "inny patron ulicy": (TWELVE, _visit("ADAMA KOWALSKIEGO 4/15", "w")),
    "MIASTO innej wielkości liter": (TWELVE, _visit("BRZOZOWA 5", "x", datetime(2026, 3, 1), city="MIASTKO")),
    "inne MIASTO": (TWELVE, _visit("BRZOZOWA 5", "y", datetime(2025, 3, 1), city="Inne Miasto")),
    "MIASTO przed miastem przed przecinkiem": (
        TWELVE, _visit("Inne Miasto,BRZOZOWA 5", "z", datetime(2024, 3, 1), city="Miastko")
    ),
    "bez miasta": (ELEVEN, _visit("UL. BRZOZOWA 5", "aa", datetime(2021, 3, 1))),
    "inne miasto przed przecinkiem": (FIVE, _visit("Inne Miasto,Brzozowa 5", "ab", datetime(2019, 4, 1))),
    "miasto przed przecinkiem innej wielkości liter": (FIVE, _visit("miastko,Brzozowa 5", "ac", datetime(2019, 3, 1))),
    "MIASTO z dzielnicą": (TWELVE, _visit("BRZOZOWA 5", "ad", datetime(2026, 2, 1), city="Miastko-Dzielnica")),
    "miasto z dzielnicą przed przecinkiem": (FIVE, _visit("Miastko - Dzielnica,Brzozowa 5", "ae", datetime(2019, 2, 1))),
    "inne miasto z tym samym początkiem": (TWELVE, _visit("BRZOZOWA 5", "af", datetime(2025, 2, 1), city="Miastkowo")),
    "kod pocztowy w MIASTO": (TWELVE, _visit("BRZOZOWA 5", "ag", datetime(2023, 3, 1), city="11-111 Miastko")),
    "kod pocztowy innego miasta": (TWELVE, _visit("BRZOZOWA 5", "ah", datetime(2022, 3, 1), city="11-111Inne Miasto")),
    "miasto od myślnika": (TWELVE, _visit("BRZOZOWA 5", "ai", datetime(2020, 3, 1), city="-Dzielnica")),
    "MIASTO z samym kodem": (TWELVE, _visit("Inne Miasto,BRZOZOWA 5", "aj", datetime(2019, 1, 1), city="11-111")),
}
RULE_BASE: Final = tuple(
    BaseSheet(name, layout, [visit for found, visit in _V.values() if found is layout])
    for name, layout in (("10_12_2018-01_08_2020", FIVE), ("01_08_2020-01_06_2021", ELEVEN), ("08_11_2021-23_03_2024", TWELVE))
)
RULE: Final[dict[Order, tuple[str, ...]]] = {
    _LIPOWA_18_3: ("miasto przed przecinkiem i zero wiodące", "bez UL."),
    _LIPOWA_34_2: ("mieszkanie małymi literami",),
    _LIPOWA_34: ("dom", "ukośnik bez mieszkania"),
    _KASZTANOWA: ("litery małe",),
    _ZIELONE: ("kropka bez spacji i zero", "wielokrotne spacje"),
    _MOSTOWA: ("kropki w nazwie",),
    _RYNKOWY: ("przedrostek sklejony z miastem",),
    _NIEZNANA: (),
    _BEZ_NUMERU: (),
    _BEZ_ULICY: (),
    _JANA_KOWALSKIEGO: ("krótsza nazwa ulicy",),
    _KOWALSKIEGO: ("dłuższa nazwa ulicy",),
    _BRZOZOWA: (
        "MIASTO innej wielkości liter",
        "MIASTO z dzielnicą",
        "MIASTO przed miastem przed przecinkiem",
        "kod pocztowy w MIASTO",
        "bez miasta",
        "miasto przed przecinkiem innej wielkości liter",
        "miasto z dzielnicą przed przecinkiem",
    ),
    _BRZOZOWA_BEZ_MIASTA: (
        "MIASTO innej wielkości liter",
        "MIASTO z dzielnicą",
        "inne MIASTO",
        "inne miasto z tym samym początkiem",
        "MIASTO przed miastem przed przecinkiem",
        "kod pocztowy w MIASTO",
        "kod pocztowy innego miasta",
        "bez miasta",
        "miasto od myślnika",
        "inne miasto przed przecinkiem",
        "miasto przed przecinkiem innej wielkości liter",
        "miasto z dzielnicą przed przecinkiem",
        "MIASTO z samym kodem",
    ),
}
"""Zlecenie → wiersze Bazy z ``_V``, które trafiają, od najnowszej daty; zlecenie ``_LIPOWA_18_3`` stoi pierwsze w
wklejeniu, więc przychodzi przesunięte dwie kolumny w lewo."""


@pytest.fixture(scope="module")
def rule_day(tmp_path_factory: pytest.TempPathFactory) -> tuple[Day, Worksheet]:
    """Dzień tabeli reguły uporządkowany raz z Bazą ``RULE_BASE``."""

    tmp_path = tmp_path_factory.mktemp("regula")
    day = _day(tmp_path, RULE_ORDERS, RULE_BASE)
    _ordered(_run(tmp_path, base=True))
    return day, day.sheet()


@pytest.mark.parametrize("order", RULE, ids=[f"{order.values()[ADDRESS]}, {order.values()[CITY] or 'bez MIASTO'}" for order in RULE])
def test_zlecenie_dostaje_od_kolumny_p_tylko_wiersze_bazy_z_tym_samym_adresem(rule_day: tuple[Day, Worksheet], order: Order) -> None:
    day, sheet = rule_day

    assert day.after_uwagi(sheet, order) == _blocks(*(_V[name] for name in RULE[order]))
    row = day.row(order)
    assert sheet.cell(row, NUMBER).value == f"ZL-{order.number}"
    assert (sheet.cell(row, LAST - 1).value, sheet.cell(row, LAST).value) == (None, None), "ZWROT i UWAGI zostają puste"


def test_wynik_ma_liczbe_zlecen_z_historia_adresu_skopiowanych_wierszy_i_arkuszy_bazy(tmp_path: Path) -> None:
    _day(tmp_path, RULE_ORDERS, RULE_BASE)

    summary = _ordered(_run(tmp_path, base=True))

    hits = RULE.values()
    assert summary.history == HistoryCounts(orders=sum(1 for found in hits if found), rows=sum(map(len, hits)), sheets=3)
    assert summary.warnings == []


_TOPOLOWA = _order(0, "UL. TOPOLOWA 7")
_INNE = _order(1, "UL. TOPOLOWA 8")
_ORDER_VISITS: Final = {
    "2019": (FIVE, _visit("Topolowa 7", "2019", datetime(2019, 5, 1, 10))),
    "bez daty w najstarszym": (FIVE, _visit("Topolowa 7", "bez daty", None)),
    "2021": (ELEVEN, _visit("TOPOLOWA 7", "2021", datetime(2021, 1, 1, 9))),
    "2025": (ELEVEN, _visit("TOPOLOWA 7", "2025", datetime(2025, 6, 1, 12))),
    "data tekstem": (TWELVE, _visit("TOPOLOWA 7", "tekst", "10.12.2018")),
    "2024": (TWELVE, _visit("TOPOLOWA 7", "2024", datetime(2024, 3, 1, 8))),
}
ORDER_BASE: Final = (
    BaseSheet("10_12_2018-01_08_2020", FIVE, [_ORDER_VISITS["2019"][1], _ORDER_VISITS["bez daty w najstarszym"][1]]),
    BaseSheet("01_08_2020-01_06_2021", ELEVEN, [_ORDER_VISITS["2021"][1], _ORDER_VISITS["2025"][1]]),
    BaseSheet("25_03_2024-18_12_2025", TWELVE, [_ORDER_VISITS["data tekstem"][1], _ORDER_VISITS["2024"][1]]),
)
ORDERED_HISTORY: Final = tuple(
    _ORDER_VISITS[name] for name in ("2025", "2024", "2021", "2019", "bez daty w najstarszym", "data tekstem")
)


@pytest.fixture(scope="module")
def topolowa(tmp_path_factory: pytest.TempPathFactory) -> tuple[Day, Worksheet]:
    """Dzień ``_TOPOLOWA`` (sześć trafień w trzech układach) i ``_INNE`` (bez trafienia) uporządkowany raz."""

    tmp_path = tmp_path_factory.mktemp("topolowa")
    day = _day(tmp_path, (_TOPOLOWA, _INNE), ORDER_BASE)
    _ordered(_run(tmp_path, base=True))
    return day, day.sheet()


def test_trafienia_stoja_od_najnowszej_daty_realizacji_a_wiersze_bez_daty_na_koncu_w_kolejnosci_arkuszy(
    topolowa: tuple[Day, Worksheet],
) -> None:
    day, sheet = topolowa

    assert day.after_uwagi(sheet, _TOPOLOWA) == _blocks(*ORDERED_HISTORY)


def test_kazdy_blok_ma_szerokosc_naglowka_swojego_arkusza_z_pustymi_komorkami_w_srodku(topolowa: tuple[Day, Worksheet]) -> None:
    day, sheet = topolowa

    widths = [len(layout.headers) for layout, _ in ORDERED_HISTORY]
    assert widths == [11, 12, 11, 5, 5, 12]
    assert [column for column in day.written(_TOPOLOWA) if column >= P] == list(range(P, P + sum(widths))), (
        "każda komórka bloku jest w pliku, także pusta"
    )
    row = day.row(_TOPOLOWA)
    with closing(load_workbook(day.path, read_only=True)) as workbook:
        assert workbook.worksheets[1].max_column == P + sum(widths) - 1, "<dimension> sięga ostatniej kolumny Historii adresu"
    assert sheet.cell(row, P + 1).value is None, "UMOWA pierwszego bloku jest pusta"
    second = (sheet.cell(row, P + 11).value, sheet.cell(row, P + 12).value)
    assert second == ("TOPOLOWA 7", datetime(2024, 3, 1, 8)), "drugi blok zaczyna się zaraz za pierwszym"


def test_bloki_maja_same_wartosci_z_data_jako_data_bez_stylow_i_hiperlaczy_bazy(topolowa: tuple[Day, Worksheet]) -> None:
    day, sheet = topolowa

    row = day.row(_TOPOLOWA)
    when = sheet.cell(row, P + 5)
    assert isinstance(when, Cell) and (when.value, when.is_date) == (datetime(2025, 6, 1, 12), True)
    for column in range(P, P + 56):
        cell = sheet.cell(row, column)
        assert (cell.font.name, cell.font.sz, bool(cell.font.b), cell.font.color.rgb) == ("Calibri", 8, False, "FF000000"), cell.coordinate
        assert cell.hyperlink is None, cell.coordinate


def test_blok_pierwszy_trzeci_i_piaty_ma_jasnoszare_tlo_na_calej_szerokosci_a_drugi_czwarty_i_szosty_bez_tla(
    topolowa: tuple[Day, Worksheet],
) -> None:
    day, sheet = topolowa

    fills: list[str | None] = []
    for index, (layout, _) in enumerate(ORDERED_HISTORY):
        fills += [GRAY if index % 2 == 0 else None] * len(layout.headers)
    row = day.row(_TOPOLOWA)
    assert [_fill(sheet, row, column) for column in range(P, P + len(fills))] == fills


def test_kolumna_a_zlecenia_z_historia_adresu_jest_czerwona_a_zlecenie_bez_trafienia_nie_ma_nic_za_uwagi(
    topolowa: tuple[Day, Worksheet],
) -> None:
    day, sheet = topolowa

    assert _fill(sheet, day.row(_TOPOLOWA), 1) == RED
    assert _fill(sheet, day.row(_INNE), 1) is None
    assert day.after_uwagi(sheet, _INNE) == ()


def test_wiersz_bazy_z_numerem_porzadkowanego_zlecenia_nie_jest_kopiowany_a_dwa_z_innym_wspolnym_numerem_sa(
    tmp_path: Path,
) -> None:
    """Zlecenie ``ZL-501``: wiersz Bazy z numerem 501 (liczbą albo tekstem z innymi znakami i zerem wiodącym) to ono
    samo po przywróceniu Kopii INTERMAX, a dwa wiersze z numerem 777 to dwie wizyty innego zlecenia."""

    order = _order(0, "UL. GRABOWA 2", number=501)
    own_number = _visit("GRABOWA 2", "własny liczbą", datetime(2026, 10, 1), 501)
    own_text = _visit("GRABOWA 2", "własny tekstem", datetime(2026, 9, 1), "nr 0501")
    first = (TWELVE, _visit("GRABOWA 2", "pierwsza wizyta", datetime(2025, 1, 1), 777))
    second = (TWELVE, _visit("GRABOWA 2", "druga wizyta", datetime(2024, 1, 1), 777))
    sheets = (
        BaseSheet("01_08_2020-01_06_2021", ELEVEN, [own_number]),
        BaseSheet("08_11_2021-23_03_2024", TWELVE, [own_text, first[1], second[1]]),
    )
    day = _day(tmp_path, (order,), sheets)

    _ordered(_run(tmp_path, base=True))

    assert day.after_uwagi(day.sheet(), order) == _blocks(first, second)


def test_bez_bazy_w_wejsciu_dzien_jest_uporzadkowany_bez_historii_adresu_i_bez_ostrzezenia(tmp_path: Path) -> None:
    day = _day(tmp_path, RULE_ORDERS, RULE_BASE)

    summary = _ordered(_run(tmp_path))

    assert (summary.history, summary.warnings) == (None, [])
    sheet = day.sheet()
    assert [day.after_uwagi(sheet, order) for order in RULE_ORDERS] == [()] * len(RULE_ORDERS)
    assert {_fill(sheet, day.row(order), 1) for order in RULE_ORDERS} == {None}


def _no_base(tmp_path: Path) -> DadFiles:
    return DadFiles()


def _garbage(tmp_path: Path) -> DadFiles:
    _base_path(tmp_path).write_bytes(b"to nie jest skoroszyt")
    return DadFiles()


def _inaccessible(tmp_path: Path) -> DadFiles:
    write_order_base(_base_path(tmp_path), RULE_BASE)

    def source(path: Path) -> bytes:
        if path.name == ORDER_BASE_NAME:
            raise WorkbookError(path, Problem.INACCESSIBLE)
        return path.read_bytes()

    return DadFiles(source=source)


def _without_header(tmp_path: Path) -> DadFiles:
    headless = replace(TWELVE, headers=("", *TWELVE.headers[1:]))
    write_order_base(_base_path(tmp_path), (*RULE_BASE[:2], BaseSheet("bez nagłówka", headless, [_visit("LIPOWA 18/3", "x")])))
    return DadFiles()


def _comment(tmp_path: Path) -> DadFiles:
    write_order_base(_base_path(tmp_path), RULE_BASE)
    commented = "xl/worksheets/sheet3.xml"
    rewrite_parts(_base_path(tmp_path), lambda name, data: data.replace(b"<sheetData>", b"<sheetData><!-- x -->", 1) if name == commented else data)
    return DadFiles()


def _broken_date(tmp_path: Path) -> DadFiles:
    """Data realizacji w arkuszu 12 kolumn (pod nagłówkiem) to liczba, której nie da się odczytać: odczyt Bazy
    przechodzi, a komórki trafienia nie da się odczytać dopiero w Planowaniu."""

    write_order_base(_base_path(tmp_path), RULE_BASE)
    broken = "xl/worksheets/sheet3.xml"
    rewrite_parts(
        _base_path(tmp_path),
        lambda name, data: re.sub(rb'(<c r="B(?!1")\d+"[^>]*><v>)[^<]*', rb"\g<1>nie liczba", data) if name == broken else data,
    )
    return DadFiles()


BASE_PROBLEMS: Final[dict[str, tuple[Callable[[Path], DadFiles], str, str]]] = {
    "brak pliku": (_no_base, "bo w folderze INTERMAX nie ma Bazy zleceń", ""),
    "nie skoroszyt": (_garbage, "bo Bazy zleceń nie można odczytać jako skoroszytu Excela", ""),
    "niedostępna": (_inaccessible, "bo nie można teraz odczytać Bazy zleceń", ""),
    "arkusz bez nagłówka kolumny A": (_without_header, "bo arkusz Bazy zleceń ma układ", ", arkusz bez nagłówka"),
    "komentarz w arkuszu": (_comment, "bo arkusz Bazy zleceń ma układ", ", arkusz 08_11_2021-23_03_2024"),
    "zepsuta komórka trafienia": (_broken_date, "bo Bazy zleceń nie można odczytać jako skoroszytu Excela", ""),
}


@pytest.mark.parametrize("problem", BASE_PROBLEMS)
def test_baza_ktorej_nie_da_sie_przeczytac_to_ostrzezenie_z_nazwa_pliku_a_dzien_jest_uporzadkowany_bez_historii(
    tmp_path: Path, problem: str
) -> None:
    prepare, reason, sheet_name = BASE_PROBLEMS[problem]
    day = _day(tmp_path, RULE_ORDERS, None)
    files = prepare(tmp_path)

    summary = _ordered(_run(tmp_path, base=True, files=files))

    [warning] = summary.warnings
    assert warning.code == "BAZA_ZLECEN_POMINIETA"
    assert warning.what.startswith("INTERMAX został uporządkowany bez Historii adresu, ") and reason in warning.what
    assert warning.where == f"plik {ORDER_BASE_NAME}, folder OneDrive{sheet_name}"
    for value in ("LIPOWA", "Lipowa", "Miastko"):
        assert value not in warning.text, value
    assert (summary.history, summary.order_count) == (None, len(RULE_ORDERS))
    sheet = day.sheet()
    assert [day.after_uwagi(sheet, order) for order in RULE_ORDERS] == [()] * len(RULE_ORDERS)


def _with_cell(
    path: Path, row: int, column: int, value: bool | float | str | None, number_format: str, *, date1904: bool = False
) -> None:
    """Baza ``path`` z komórką w wierszu ``row`` i kolumnie ``column`` pierwszego arkusza zmienioną na ``value`` w
    formacie liczby ``number_format``, zapisana jak w Excelu; ``date1904``: w systemie dat od 1904 r."""

    workbook = load_workbook(path)
    if date1904:
        workbook.epoch = CALENDAR_MAC_1904
    cell = workbook.worksheets[0].cell(row, column)
    cell.value = value
    cell.number_format = number_format
    workbook.save(path)
    like_excel(path)


_LIPOWA_BASE: Final = (BaseSheet("19_12_2025-17_11_2026", TWELVE, [_visit("LIPOWA 18/3", "a")]),)
_UMOWA: Final = TWELVE.headers.index("UMOWA") + 1


@pytest.mark.parametrize(
    ("value", "number_format", "expected"),
    [(0.5, "hh:mm", time(12)), (40000011, "dd.mm.yyyy", 40000011), (-1.5, "dd.mm.yyyy", -1.5)],
    ids=["godzina", "liczba za 31.12.9999", "liczba ujemna"],
)
def test_godzina_z_bazy_jest_w_historii_adresu_godzina_a_liczba_spoza_dat_excela_liczba(
    tmp_path: Path, value: float, number_format: str, expected: object
) -> None:
    """Liczba w formacie daty, której Excel nie pokazuje jako daty (ujemna albo za 31.12.9999, np. 8-cyfrowy numer), ma
    w Bazie ``#######``, a jej wartością zostaje liczba; godzina jest wartością czasu, nie tekstem."""

    order = _order(0, "UL. LIPOWA 18/3")
    day = _day(tmp_path, (order,), _LIPOWA_BASE)
    _with_cell(_base_path(tmp_path), 2, _UMOWA, value, number_format)

    _ordered(_run(tmp_path, base=True))

    cell = day.sheet().cell(day.row(order), P + _UMOWA - 1)
    assert isinstance(cell, Cell) and (cell.value, cell.is_date) == (expected, isinstance(expected, time))


_OWN_NUMBER: Final = 987654321
"""Numer porządkowanego zlecenia, którego żadna wartość z ``_CELL_VALUES`` nie powtarza w praktyce."""
_CELL_VALUES: Final = (
    st.none()
    | st.booleans()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.integers(-(10**300), 10**300)
    | st.text(st.characters(exclude_categories=("Cc", "Cs", "Cn")))
    | st.text("0123456789", min_size=4301, max_size=4310)
)
"""Wartość, którą Excel zapisuje w komórce: pusta, prawda albo fałsz, liczba dowolnej wielkości i znaku, tekst, także
tekst samych cyfr dłuższy niż 4300 cyfr (granica zamiany tekstu na liczbę całkowitą w Pythonie)."""
_NUMBER_FORMATS: Final = st.sampled_from(
    ("General", "0.00", "@", "dd.mm.yyyy", "dd.mm.yyyy hh:mm", "yyyy-mm-dd", "hh:mm", "mm:ss", "[h]:mm")
)
_BASE_PLACES: Final = st.tuples(st.just(1), st.integers(1, 20)) | st.tuples(st.just(2), st.integers(2, 20))
"""Wiersz i kolumna komórki: wiersz 1 arkusza (nagłówek i za nim) albo wiersz trafienia poza adresem w kolumnie A."""


@settings(derandomize=True, database=None, deadline=None, max_examples=60)
@given(
    layout=st.sampled_from((FIVE, ELEVEN, TWELVE)),
    place=_BASE_PLACES,
    value=_CELL_VALUES,
    number_format=_NUMBER_FORMATS,
    date1904=st.booleans(),
)
@example(layout=TWELVE, place=(2, _UMOWA), value=40000011, number_format="dd.mm.yyyy", date1904=False)
@example(layout=TWELVE, place=(2, TWELVE.number), value="1" * 4301, number_format="General", date1904=False)
@example(layout=TWELVE, place=(2, _UMOWA), value=2958000, number_format="dd.mm.yyyy", date1904=True)
def test_dowolna_komorka_bazy_daje_historie_adresu_albo_ostrzezenie_a_dzien_jest_uporzadkowany(
    layout: BaseLayout, place: tuple[int, int], value: bool | float | str | None, number_format: str, date1904: bool
) -> None:
    """Jedna komórka Bazy z dowolną wartością w dowolnym formacie liczby, w wierszu 1 arkusza albo w wierszu trafienia,
    w systemie dat od 1900 albo 1904 r.: Uporządkowanie kończy się dniem uporządkowanym z Historią adresu albo z
    ostrzeżeniem ``BAZA_ZLECEN_POMINIETA``, nigdy Zatrzymaniem z nieoczekiwanym błędem. Wartość w ``MIASTO`` trafienia
    jest jego miastem, więc może dać też dzień bez trafienia.

    Przykłady stałe: 8-cyfrowy numer w formacie daty w ``UMOWA``, 4301 cyfr w ``NUMER ZL.`` i liczba w formacie daty
    za 31.12.9999 tylko w systemie dat od 1904 r."""

    row, column = place
    order = _order(0, "UL. LIPOWA 18/3", number=_OWN_NUMBER)
    with TemporaryDirectory() as folder:
        tmp_path = Path(folder)
        _day(tmp_path, (order,), (BaseSheet("19_12_2025-17_11_2026", layout, [_visit("LIPOWA 18/3", "a")]),))
        _with_cell(_base_path(tmp_path), row, column, value, number_format, date1904=date1904)
        summary = _ordered(_run(tmp_path, base=True))

    codes = [warning.code for warning in summary.warnings]
    endings = [([], HistoryCounts(1, 1, 1)), (["BAZA_ZLECEN_POMINIETA"], None)]
    if place == (2, layout.city):
        endings.append(([], HistoryCounts(0, 0, 1)))
    assert (codes, summary.history) in endings, (codes, summary.history)


def test_baza_otwarta_w_excelu_daje_historie_adresu_z_ostatniego_zapisu(tmp_path: Path) -> None:
    day = _day(tmp_path, RULE_ORDERS, RULE_BASE)
    _base_path(tmp_path).with_name(f"~${ORDER_BASE_NAME}").write_bytes(b"blokada Excela")

    summary = _ordered(_run(tmp_path, base=True))

    assert summary.warnings == []
    assert day.after_uwagi(day.sheet(), _MOSTOWA) == _blocks(_V["kropki w nazwie"])


def test_pamiec_reguly_danych_zna_adresy_bazy_a_kopia_wejscia_nie_ma_bazy(tmp_path: Path) -> None:
    _day(tmp_path, RULE_ORDERS, RULE_BASE)
    memory = empty_memory()
    files = DadFiles(forbidden=memory).for_run()

    _ordered(_run(tmp_path, base=True, files=files))

    assert files.copy is not None
    assert [copied.name for copied in files.copy.files()] == [REGISTER_NAME]
    searched = [visit.address for _, visit in _V.values() if len(visit.address) >= MIN_VALUE]
    assert len(searched) == len(_V) - 1, "strażnik nie szuka wartości krótszej niż MIN_VALUE (18/3)"
    assert [address for address in searched if not guarded(memory, f"adres {address}", "Uwaga taty").notes] == []


def _changed(row_change: Callable[[bytes, int], bytes], row: int) -> Callable[[bytes], bytes]:
    """Bajty INTERMAX z arkuszem zleceń zmienionym przez ``row_change`` w wierszu ``row``, jak zepsuty zapis."""

    def changed(content: bytes) -> bytes:
        out = BytesIO()
        with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(out, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                target.writestr(info, row_change(data, row) if info.filename == _SHEET else data)
        return out.getvalue()

    return changed


def _cell(column: str, row: int) -> re.Pattern[bytes]:
    return re.compile(rb'<c r="%s%d"[^>]*?(?:/>|>.*?</c>)' % (column.encode("ascii"), row), re.S)


def _style_of(column: str, other: str) -> Callable[[bytes, int], bytes]:
    """Komórka ``column`` wiersza dostaje styl komórki ``other`` tego wiersza."""

    def change(xml: bytes, row: int) -> bytes:
        found = _cell(other, row).search(xml)
        assert found is not None
        style = re.search(rb'\ss="\d+"', found.group(0))
        assert style is not None
        return _cell(column, row).sub(lambda cell: re.sub(rb'\ss="\d+"', style.group(0), cell.group(0), count=1), xml, count=1)

    return change


def _removed(column: str) -> Callable[[bytes, int], bytes]:
    return lambda xml, row: _cell(column, row).sub(b"", xml, count=1)


HISTORY_CORRUPTIONS: Final[dict[str, Callable[[bytes, int], bytes]]] = {
    "wartość w bloku": lambda xml, row: re.sub(rb'(<c r="P%d"[^>]*><is><t>)[^<]*' % row, rb"\g<1>inny", xml, count=1),
    "brak pustej komórki bloku": _removed("Q"),
    "brak ostatniej komórki ostatniego bloku": _removed("BS"),
    "blok bez szarego tła": _style_of("Q", "AA"),
    "szare tło w drugim bloku": _style_of("AA", "Q"),
    "kolumna A bez czerwieni": _style_of("A", "B"),
}
"""Zepsucie zapisu w wierszu ``_TOPOLOWA``: wartość, szerokość bloku, tło bloku i kolumna A. Kolumna Q to pusta
``UMOWA`` pierwszego bloku (szarego), AA pierwsza kolumna drugiego (bez tła), a BS ostatnia kolumna szóstego."""


@pytest.mark.parametrize("corruption", HISTORY_CORRUPTIONS)
def test_niezgodna_historia_adresu_w_sprawdzeniu_zapisu_to_zatrzymanie_do_maksa_bez_zmiany_intermax(
    tmp_path: Path, corruption: str
) -> None:
    day = _day(tmp_path, (_TOPOLOWA, _INNE), ORDER_BASE)
    original = day.path.read_bytes()
    disk = FaultyDisk(write=writing(_changed(HISTORY_CORRUPTIONS[corruption], day.row(_TOPOLOWA))))

    stop = _stop(_run(tmp_path, base=True, disk=disk))

    assert (stop.message.code, stop.stop_kind) == ("ZAPIS_INTERMAX_NIEZGODNY", "for_maks")
    assert day.path.read_bytes() == original


def _pasted(path: Path, order: Order, when: datetime) -> None:
    """Surowe zlecenie ``order`` z chwilą ``when`` wklejone z wyglądem z aplikacji trzy wiersze pod ostatnim, zapisane
    jak w Excelu taty."""

    workbook = load_workbook(path)
    sheet = workbook.worksheets[1]
    number = sheet.max_row + 3
    for column, value in replace(order, when=when).values().items():
        sheet.cell(number, column, value).font = Font(name="Roboto", sz=4)
    workbook.save(path)


def test_dzien_z_historia_adresu_jest_dniem_uporzadkowanym_a_nastepny_dzien_porzadkuje_sie_pod_nim(tmp_path: Path) -> None:
    day = _day(tmp_path, (_TOPOLOWA, _INNE), ORDER_BASE)
    _ordered(_run(tmp_path, base=True))
    ordered = day.path.read_bytes()
    _pasted(day.path, _INNE, datetime(2026, 10, 26, 15))

    stop = _stop(_run(tmp_path, base=True, now=NOW + timedelta(minutes=5)))

    assert stop.message.code == "DZIEN_JUZ_UPORZADKOWANY"
    days = register_days(day.path, date(2026, 10, 26), DadFiles())
    assert isinstance(days, tuple) and [found.ordered for found in days if found.day == date(2026, 10, 26)] == [True]
    day.path.write_bytes(ordered)
    _pasted(day.path, _TOPOLOWA, datetime(2026, 10, 27, 15))

    summary = _ordered(_run(tmp_path, base=True, now=NOW + timedelta(days=1)))

    assert (summary.day, summary.order_count, summary.history) == (date(2026, 10, 27), 1, HistoryCounts(1, 6, 3))
    sheet = day.sheet()
    assert day.after_uwagi(sheet, _TOPOLOWA) == _blocks(*ORDERED_HISTORY), "dzień z Historią adresu zostaje"


def test_przygotowanie_okresu_z_dniem_z_historia_adresu_nie_przenosi_blokow_ani_czerwonej_kolumny_a(tmp_path: Path) -> None:
    """Spec #2079, historyjka 27: Przygotowanie pliku zbiorczego bierze z Rejestru zleceń tylko kolumny zlecenia, więc
    Historia adresu i czerwona kolumna A dnia uporządkowanego z Bazą zleceń nie trafiają do Pliku zbiorczego."""

    fixture = make_preparation_fixture(tmp_path)
    pasted = [{**register_order(number, datetime(2026, 9, 13, 8 + number)), "ADRES": f"UL. JASNA {number}"} for number in (7, 8)]
    paste_raw_orders(fixture.register_path, pasted)
    base = fixture.register_path.with_name(ORDER_BASE_NAME)
    write_order_base(base, (BaseSheet("19_12_2025-17_11_2026", TWELVE, [_visit("JASNA 7", "WIZYTA-HISTORII")]),))
    ordering = OrderingInputs(fixture.register_path, tmp_path / "Kopie", now=lambda: datetime(2026, 9, 14, 20), order_base=base)
    ordered = run_process(
        PROCESS, ordering, Tata(), view=lambda _inputs, summary: summary, metrics_path=tmp_path / "m.jsonl", context=RunContext()
    )
    assert _ordered(ordered).history == HistoryCounts(1, 1, 1)

    preparation = run_preparation(fixture)

    sheet = load_workbook(preparation.collective_file).worksheets[0]
    cells = [cell for row in sheet.iter_rows() for cell in row]
    assert [cell.coordinate for cell in cells if isinstance(cell.value, str) and "WIZYTA-HISTORII" in cell.value] == []
    assert [cell.coordinate for cell in cells if cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb == RED] == []
    assert sum(1 for cell in cells if cell.value == "UL. JASNA 7") == 1, "zlecenie z Historią adresu jest w Pliku zbiorczym"
