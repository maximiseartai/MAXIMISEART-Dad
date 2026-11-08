"""Plik zbiorczy z kopii Wzorca (ADR 0008) jest taki sam jak zapisany przez openpyxl.

Test właściciel drogi kopii w Przygotowaniu pliku zbiorczego: obie drogi zapisu dają te same
wartości, Wygląd Wiersza danych, Hiperłącza, wysokości wierszy, scalenia, autofiltr i odwołania zewnętrzne.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import copy
from dataclasses import replace
from pathlib import Path
import re
import zipfile

from openpyxl import load_workbook
import pytest

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, write_synthetic_templates
from datetime import datetime

from openpyxl.utils import get_column_letter

from tests.fixtures.preparation import (
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    PreparationFixture,
    link_register_order_numbers,
    make_dad_layout_fixture,
    make_preparation_fixture,
    other_warnings,
    register_order,
    run_preparation,
    write_collective_template,
)
from tests.fixtures.workbooks import (
    active_worksheet,
    external_link_parts,
    has_xml_comment,
    leave_data_row_leftovers,
    marked_for_copy,
    refused_by_copy,
    replace_cells,
    rewrite_parts,
    written_by_copy,
)


def _synthetic(tmp_path: Path) -> PreparationFixture:
    templates = write_synthetic_templates(tmp_path / "wzorce")
    (tmp_path / "syntetyczne").mkdir()
    return replace(
        make_preparation_fixture(tmp_path / "syntetyczne"),
        internal_template_path=templates / INTERNAL_TEMPLATE,
        collective_template_path=templates / COLLECTIVE_TEMPLATE,
    )


def _linked(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    link_register_order_numbers(fixture.register_path, "https://przyklad.invalid/zlecenie?caseId=SYN-1&tw=1")
    return fixture


def _row_style(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    write_collective_template(fixture.collective_template_path, row_style=True)
    return fixture


def _leftovers(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    leave_data_row_leftovers(fixture.collective_template_path, first_row=18, rows=6, columns=12)
    return fixture


def _formula_in(reference: str) -> Callable[[Path], PreparationFixture]:
    """Wzorzec z formułą w Wierszu danych: kopia go nie przyjmuje, bo wpisanie wartości zmienia ``calcChain``."""

    def make(tmp_path: Path) -> PreparationFixture:
        fixture = make_preparation_fixture(tmp_path)
        replace_cells(fixture.collective_template_path, {reference: f'<c r="{reference}"><f>1+1</f><v>2</v></c>'})
        return fixture

    return make


def _filter_database(path: Path) -> list[str]:
    """Zakres nazwy ``_xlnm._FilterDatabase``: openpyxl jej nie wczytuje, Excel filtruje według niej."""

    with zipfile.ZipFile(path) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
    found = re.findall(r'<(?:\w+:)?definedName\b[^>]*name="_xlnm\._FilterDatabase"[^>]*>([^<]*)<', workbook_xml)
    return [name.replace("'", "") for name in found]


def _filter_name_ref_error(tmp_path: Path) -> PreparationFixture:
    """Wzorzec, w którym nazwa ``_xlnm._FilterDatabase`` wskazuje ``#REF!``, jak po usunięciu zakresu w Excelu."""

    fixture = make_preparation_fixture(tmp_path)
    path = fixture.collective_template_path
    with zipfile.ZipFile(path) as source:
        parts = {info.filename: source.read(info) for info in source.infolist()}
    parts["xl/workbook.xml"] = re.sub(
        rb"('Sheet1'!)\$B\$17:\$C\$57", rb"\1#REF!", parts["xl/workbook.xml"]
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in parts.items():
            target.writestr(name, data)
    return fixture


def _cells(path: Path) -> dict[str, object]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        cells = {
            cell.coordinate: (
                cell.value,
                cell.number_format,
                (cell.font.name, cell.font.sz, bool(cell.font.b), bool(cell.font.i), copy(cell.font.color)),
                copy(cell.fill),
                copy(cell.border),
                copy(cell.alignment),
                copy(cell.protection),
                cell.hyperlink.target if cell.hyperlink is not None else None,
            )
            for row in sheet.iter_rows()
            for cell in row
        }
        names = {name: str(value.attr_text) for name, value in sheet.defined_names.items()}
        heights = {row: dimension.ht for row, dimension in sheet.row_dimensions.items()}
        return {
            **cells,
            "wysokosci": heights,
            "autofiltr": sheet.auto_filter.ref,
            "scalenia": sorted(str(merged) for merged in sheet.merged_cells.ranges),
            "nazwy arkusza": names,
            "_FilterDatabase": _filter_database(path),
            "przeliczenie": workbook.calculation.fullCalcOnLoad,
        }
    finally:
        workbook.close()


@pytest.mark.parametrize(
    ("make_fixture", "copied"),
    [
        pytest.param(make_preparation_fixture, True, id="syntetyczny"),
        pytest.param(_linked, True, id="hiperlacza"),
        pytest.param(make_dad_layout_fixture, True, id="uklad-taty"),
        pytest.param(_synthetic, True, id="wzorce-ksztaltu-taty"),
        pytest.param(_row_style, True, id="styl-wiersza"),
        pytest.param(_leftovers, True, id="resztki-formatowania-wzorca"),
        pytest.param(_filter_name_ref_error, False, id="nazwa-filtra-ref-przez-openpyxl"),
        pytest.param(_formula_in("K18"), False, id="formula-w-ostatniej-kolumnie-danych-przez-openpyxl"),
        pytest.param(_formula_in("AP18"), False, id="formula-w-ostatniej-kolumnie-ilosci-przez-openpyxl"),
    ],
)
def test_plik_zbiorczy_z_kopii_wzorca_jest_taki_jak_z_openpyxl(
    tmp_path: Path, make_fixture: Callable[[Path], PreparationFixture], copied: bool
) -> None:
    (tmp_path / "kopia").mkdir()
    (tmp_path / "openpyxl").mkdir()
    by_copy = make_fixture(tmp_path / "kopia")
    by_openpyxl = make_fixture(tmp_path / "openpyxl")
    marked_for_copy(by_copy.collective_template_path)
    refused_by_copy(marked_for_copy(by_openpyxl.collective_template_path))
    run_preparation(by_copy)
    run_preparation(by_openpyxl)

    created, reference = by_copy.collective_file_path, by_openpyxl.collective_file_path
    with zipfile.ZipFile(created) as archive:
        keeps_template_calc_chain = "xl/calcChain.xml" in archive.namelist()
    with zipfile.ZipFile(by_copy.collective_template_path) as archive:
        template_has_calc_chain = "xl/calcChain.xml" in archive.namelist()

    assert written_by_copy(created) == copied
    assert not has_xml_comment(reference)
    assert _cells(created) == _cells(reference)
    assert external_link_parts(created) == external_link_parts(reference)
    assert keeps_template_calc_chain == (copied and template_has_calc_chain)



_QUANTITY_LETTERS = [get_column_letter(column) for column in range(14, 43)]  # N:AP


def _date_style(path: Path) -> int:
    """Dopisuje do stylów Wzorca styl komórki z formatem daty (wbudowany ``numFmtId`` 14) i podaje jego numer."""

    found: list[int] = []

    def change(name: str, data: bytes) -> bytes:
        if name != "xl/styles.xml":
            return data
        count = re.search(rb'<cellXfs count="(\d+)"', data)
        assert count is not None
        found.append(int(count.group(1)))
        data = data.replace(count.group(0), b'<cellXfs count="%d"' % (found[0] + 1), 1)
        return data.replace(b"</cellXfs>", b'<xf numFmtId="14" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/></cellXfs>', 1)

    rewrite_parts(path, change)
    return found[0]


def _third_zero_row(path: Path, cell: Callable[[str], str]) -> None:
    replace_cells(path, {f"{letter}20": cell(f"{letter}20") for letter in _QUANTITY_LETTERS})


def _without_row_20(path: Path) -> None:
    rewrite_parts(
        path,
        lambda name, data: re.sub(rb'<row r="20".*?</row>', b"", data, count=1, flags=re.S)
        if name == "xl/worksheets/sheet1.xml"
        else data,
    )


def _date_zeros(path: Path) -> None:
    style = _date_style(path)
    _third_zero_row(path, lambda reference: f'<c r="{reference}" s="{style}"><v>0</v></c>')


def _zero_only_in_ap(path: Path) -> None:
    _third_zero_row(path, lambda reference: f'<c r="{reference}"/>' if reference != "AP20" else '<c r="AP20"><v>0.0</v></c>')


@pytest.mark.parametrize("copied", [True, False], ids=["kopia", "openpyxl"])
@pytest.mark.parametrize(
    ("change", "zero_rows"),
    [
        pytest.param(lambda path: None, COLLECTIVE_TEMPLATE_ZERO_ROWS, id="wzorzec"),
        pytest.param(_zero_only_in_ap, COLLECTIVE_TEMPLATE_ZERO_ROWS, id="zero-tylko-w-AP"),
        pytest.param(
            lambda path: _third_zero_row(path, lambda reference: f'<c r="{reference}" t="inlineStr"><is><t>0</t></is></c>'),
            2,
            id="tekst-0",
        ),
        pytest.param(
            lambda path: _third_zero_row(path, lambda reference: f'<c r="{reference}" t="b"><v>0</v></c>'),
            2,
            id="falsz",
        ),
        pytest.param(_date_zeros, 2, id="0-w-formacie-daty"),
        pytest.param(_without_row_20, 2, id="brak-wiersza"),
    ],
)
def test_wiersze_przygotowane_zerami_to_liczba_0_w_kolumnach_ilosci_na_obu_drogach_zapisu(
    tmp_path: Path, copied: bool, change: Callable[[Path], None], zero_rows: int
) -> None:
    successful_count = COLLECTIVE_TEMPLATE_ZERO_ROWS + 1
    fixture = make_preparation_fixture(
        tmp_path, [register_order(number, datetime(2026, 9, 14, 8, number)) for number in range(1, successful_count + 1)]
    )
    change(marked_for_copy(fixture.collective_template_path))
    if not copied:
        refused_by_copy(fixture.collective_template_path)

    summary = run_preparation(fixture)

    assert written_by_copy(fixture.collective_file_path) == copied
    assert [warning.text.splitlines()[0] for warning in other_warnings(summary.warnings)] == [
        f"Co się stało: Zleceń skutecznych: {successful_count}, wierszy przygotowanych zerami we Wzorcu pliku zbiorczego: "
        f"{zero_rows}. Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości."
    ]
