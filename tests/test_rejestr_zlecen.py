from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904

from rozliczenia import register_file
from rozliczenia.dad_files import DadFiles
from rozliczenia.register_file import OrderSheets
from rozliczenia.settlement_period import period_of
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.workbook_parts import UnsupportedShape, rows_dated_between

from atrapy.intermax import WORKER, Intermax, Order, like_excel
from atrapy.workbooks import rewrite_parts


def _order_sheets(path: Path) -> OrderSheets:
    sheets = register_file.read(path, DadFiles()).order_sheets
    assert isinstance(sheets, OrderSheets), sheets
    return sheets


def _workers(tmp_path: Path, intermax: Intermax) -> frozenset[str]:
    path = tmp_path / "INTERMAX.xlsx"
    intermax.write(path)
    return _order_sheets(path).workers()


def test_wykonawcy_rejestru_sa_po_normalize_text_bez_pustych_a_przesuniety_pierwszy_wiersz_wklejenia_nie_daje_swojego(
    tmp_path: Path,
) -> None:
    intermax = Intermax(
        ordered=(
            Order(datetime(2026, 10, 19, 9), "  Anna.KOWALSKA ", 1),
            Order(datetime(2026, 10, 19, 10), "anna.kowalska", 2, cells=((WORKER, "   "),)),
        ),
        raw=(Order(datetime(2026, 10, 26, 8), "piotr.przesuniety", 101), Order(datetime(2026, 10, 26, 9), "Ola Druga", 102)),
    )

    workers = _workers(tmp_path, intermax)

    assert {"anna.kowalska", "ola druga"} <= workers
    assert {"", "  Anna.KOWALSKA ", "Ola Druga", "piotr.przesuniety"}.isdisjoint(workers)


def test_wykonawcy_arkusza_zlecen_z_wierszami_ktorych_nie_da_sie_rozdzielic_to_unsupported_shape(tmp_path: Path) -> None:
    path = tmp_path / "INTERMAX.xlsx"
    Intermax().write(path)
    sheets = _order_sheets(path)
    [part] = {sheet.part for sheet in sheets.sheets}
    rewrite_parts(path, lambda name, data: data.replace(b"<sheetData>", b"<sheetData><!-- x -->", 1) if name == part else data)

    with pytest.raises(UnsupportedShape):
        _order_sheets(path).workers()


def test_drugi_odczyt_wierszy_okresu_z_tych_samych_bajtow_rejestru_nie_zaweza_skoroszytu_drugi_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "INTERMAX.xlsx"
    Intermax(ordered=(Order(datetime(2026, 10, 20, 8), "drugi.odczyt", 7),)).write(path)
    period = period_of(date(2026, 10, 20))
    calls: list[object] = []

    def counted(*args: Any) -> Any:
        calls.append(args)
        return rows_dated_between(*args)

    monkeypatch.setattr(register_file, "rows_dated_between", counted)
    first = _order_sheets(path).period_rows(period)
    before = len(calls)

    second = _order_sheets(path).period_rows(period)

    assert (len(calls), second) == (before, first)


def test_rejestr_bez_czesci_stylow_jest_nieczytelny(tmp_path: Path) -> None:
    path = tmp_path / "INTERMAX.xlsx"
    Intermax().write(path)
    rewrite_parts(
        path, lambda name, data: re.sub(rb'<Relationship [^>]*styles"[^>]*/>', b"", data) if name == "xl/_rels/workbook.xml.rels" else data
    )

    with pytest.raises(WorkbookError):
        register_file.read(path, DadFiles())


def test_obszar_wklejania_rejestru_w_systemie_dat_od_1904_ma_jego_poczatek(tmp_path: Path) -> None:
    path = tmp_path / "INTERMAX.xlsx"
    Intermax().write(path)
    workbook = load_workbook(path)
    workbook.epoch = CALENDAR_MAC_1904
    workbook.save(path)
    like_excel(path)

    assert [area.epoch for area in _order_sheets(path).paste_areas()] == [datetime(1904, 1, 1)]
