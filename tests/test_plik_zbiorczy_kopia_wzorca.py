"""Plik zbiorczy i Rozliczenie wewnętrzne z kopii Wzorca (ADR 0008) są takie same jak zapisane przez openpyxl.

Test właściciel drogi kopii w Przygotowaniu pliku zbiorczego: obie drogi zapisu dają te same wartości, Wygląd
Wiersza danych, Hiperłącza, wymiary wierszy i kolumn, blokadę wierszy, scalenia, autofiltr, flagi przeliczania i
odwołania zewnętrzne.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import re
import zipfile

from openpyxl import load_workbook
import pytest

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, write_synthetic_templates
from datetime import datetime

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import absolute_coordinate

from atrapy.pliki_taty import INTERNAL_HEADERS
from atrapy.preparation import (
    COLLECTIVE_TEMPLATE_ZERO_ROWS,
    PreparationFixture,
    link_register_order_numbers,
    make_dad_layout_fixture,
    make_preparation_fixture,
    register_order,
    write_collective_template,
    write_internal_template,
)
from tests.fixtures.operacje import other_warnings, run_preparation
from tests.fixtures.wyglad_komorek import wyglady
from atrapy.workbooks import (
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


def _linked_without_rels_type(tmp_path: Path) -> PreparationFixture:
    fixture = _linked(tmp_path)
    for path in (fixture.collective_template_path, fixture.internal_template_path):
        with zipfile.ZipFile(path) as source:
            assert not any(name.startswith("xl/worksheets/_rels/") for name in source.namelist())
        rewrite_parts(
            path,
            lambda name, data: (
                re.sub(rb'<(?:\w+:)?Default Extension="rels"[^>]*/>', b"", data) if name == "[Content_Types].xml" else data
            ),
        )
        with zipfile.ZipFile(path) as source:
            assert b'Extension="rels"' not in source.read("[Content_Types].xml")
    return fixture


def _row_style(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    write_collective_template(fixture.collective_template_path, row_style=True)
    return fixture


def _leftovers(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    leave_data_row_leftovers(fixture.collective_template_path, first_row=18, rows=6, columns=12)
    return fixture


def _internal_header_after_k(tmp_path: Path) -> PreparationFixture:
    """Wzorzec rozliczenia wewnętrznego z kolumną przed nagłówkami: nagłówek docelowy w L, poza nagłówkiem kopii."""

    fixture = make_preparation_fixture(tmp_path)
    workbook = load_workbook(write_internal_template(fixture.internal_template_path))
    active_worksheet(workbook).insert_cols(1)
    active_worksheet(workbook)["A1"] = "LP"
    workbook.save(fixture.internal_template_path)
    assert active_worksheet(load_workbook(fixture.internal_template_path))["L1"].value == INTERNAL_HEADERS[10]
    return fixture


def _internal_header_repeated_after_k(tmp_path: Path) -> PreparationFixture:
    """Wzorzec rozliczenia wewnętrznego z nagłówkiem docelowym w B1 i drugi raz w N1: openpyxl wpisuje pod ostatnim."""

    fixture = make_preparation_fixture(tmp_path)
    workbook = load_workbook(write_internal_template(fixture.internal_template_path))
    active_worksheet(workbook)["N1"] = INTERNAL_HEADERS[1]
    workbook.save(fixture.internal_template_path)
    return fixture


def _content_in_look_columns(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    for path, cells in (
        (fixture.collective_template_path, {"L18": "uwaga Wzorca"}),
        (fixture.internal_template_path, {"L2": "zwrot Wzorca", "M2": "uwagi Wzorca"}),
    ):
        workbook = load_workbook(path, keep_links=True)
        for reference, value in cells.items():
            active_worksheet(workbook)[reference] = value
        workbook.save(path)
    return fixture


def _filter_with_condition(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    for path in (fixture.collective_template_path, fixture.internal_template_path):
        rewrite_parts(
            path,
            lambda name, data: (
                re.sub(
                    rb'<autoFilter ref="([A-Z0-9:]+)" />',
                    rb'<autoFilter ref="\1"><filterColumn colId="0"><filters><filter val="x"/></filters></filterColumn></autoFilter>',
                    data,
                )
                if name == "xl/worksheets/sheet1.xml"
                else data
            ),
        )
        with zipfile.ZipFile(path) as source:
            assert b"<filterColumn" in source.read("xl/worksheets/sheet1.xml")
    return fixture


def _without_autofilter(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    for path in (fixture.collective_template_path, fixture.internal_template_path):
        rewrite_parts(path, lambda name, data: re.sub(rb"<autoFilter [^>]*/>", b"", data) if name == "xl/worksheets/sheet1.xml" else data)
        with zipfile.ZipFile(path) as source:
            assert b"autoFilter" not in source.read("xl/worksheets/sheet1.xml")
    return fixture


def _blank_header_cells(tmp_path: Path) -> PreparationFixture:
    fixture = make_preparation_fixture(tmp_path)
    for path, reference in ((fixture.collective_template_path, "AZ17"), (fixture.internal_template_path, "Z1")):
        workbook = load_workbook(path, keep_links=True)
        active_worksheet(workbook)[reference] = "   "
        workbook.save(path)
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


def _without_cell_styles(tmp_path: Path, *, zeros: bool = True) -> PreparationFixture:
    """Wzorzec pliku zbiorczego bez żadnego stylu komórki: puste ``cellXfs`` i arkusz bez atrybutów stylu."""

    fixture = make_preparation_fixture(tmp_path)
    path = fixture.collective_template_path
    with zipfile.ZipFile(path) as source:
        parts = {info.filename: source.read(info) for info in source.infolist()}
    parts["xl/styles.xml"] = re.sub(rb"<cellXfs\b.*?</cellXfs>", b'<cellXfs count="0"></cellXfs>', parts["xl/styles.xml"], flags=re.S)
    for name in [name for name in parts if name.startswith("xl/worksheets/")]:
        parts[name] = re.sub(rb'\s(?:s|style)="\d+"', b"", parts[name])
        if not zeros:
            parts[name] = re.sub(rb'(<c r="(?:[N-Z]|A[A-P])\d+"[^>]*?)><v>0</v></c>', rb"\1/>", parts[name])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in parts.items():
            target.writestr(name, data)
    return fixture


def _without_cell_styles_or_zeros(tmp_path: Path) -> PreparationFixture:
    fixture = _without_cell_styles(tmp_path, zeros=False)
    with zipfile.ZipFile(fixture.collective_template_path) as source:
        assert b"<v>0</v>" not in source.read("xl/worksheets/sheet1.xml")
    return fixture


def _cells(path: Path) -> dict[str, object]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        all_cells = [cell for row in sheet.iter_rows() for cell in row]
        looks = wyglady(all_cells)
        cells = {
            cell.coordinate: (
                cell.value,
                looks[cell.coordinate],
                cell.hyperlink.target if cell.hyperlink is not None else None,
            )
            for cell in all_cells
        }
        names = {name: str(value.attr_text) for name, value in sheet.defined_names.items()}
        heights = {row: dimension.ht for row, dimension in sheet.row_dimensions.items()}
        calculation = workbook.calculation
        return {
            **cells,
            "wysokosci": heights,
            "szerokosci": {letter: dimension.width for letter, dimension in sheet.column_dimensions.items()},
            "blokada": sheet.freeze_panes,
            "autofiltr": (sheet.auto_filter.ref, len(sheet.auto_filter.filterColumn)),
            "scalenia": sorted(str(merged) for merged in sheet.merged_cells.ranges),
            "nazwy arkusza": names,
            "_FilterDatabase": _filter_database(path),
            "przeliczenie": (calculation.calcMode, calculation.fullCalcOnLoad, calculation.forceFullCalc),
        }
    finally:
        workbook.close()


@pytest.mark.parametrize(
    ("make_fixture", "collective_copied", "internal_copied"),
    [
        pytest.param(make_preparation_fixture, True, True, id="syntetyczny"),
        pytest.param(_linked, True, True, id="hiperlacza"),
        pytest.param(_linked_without_rels_type, False, False, id="hiperlacza-bez-typu-rels-przez-openpyxl"),
        pytest.param(make_dad_layout_fixture, True, True, id="uklad-taty"),
        pytest.param(_synthetic, True, True, id="wzorce-ksztaltu-taty"),
        pytest.param(_row_style, True, True, id="styl-wiersza"),
        pytest.param(_leftovers, True, True, id="resztki-formatowania-wzorca"),
        pytest.param(_filter_with_condition, True, True, id="warunek-filtra-wzorca"),
        pytest.param(_without_autofilter, False, False, id="bez-autofiltra-przez-openpyxl"),
        pytest.param(_blank_header_cells, True, True, id="naglowek-ze-spacji-za-ostatnim"),
        pytest.param(_content_in_look_columns, True, True, id="tresc-wzorca-w-kolumnach-samego-wygladu"),
        pytest.param(_filter_name_ref_error, False, True, id="nazwa-filtra-ref-przez-openpyxl"),
        pytest.param(
            _without_cell_styles,
            False,
            True,
            id="bez-stylow-komorek-przez-openpyxl",
            marks=pytest.mark.filterwarnings("ignore:Workbook contains no stylesheet:UserWarning"),
        ),
        pytest.param(
            _without_cell_styles_or_zeros,
            False,
            True,
            id="bez-stylow-komorek-i-zer-przez-openpyxl",
            marks=pytest.mark.filterwarnings("ignore:Workbook contains no stylesheet:UserWarning"),
        ),
        pytest.param(_formula_in("K18"), False, True, id="formula-w-ostatniej-kolumnie-danych-przez-openpyxl"),
        pytest.param(_formula_in("AP18"), False, True, id="formula-w-ostatniej-kolumnie-ilosci-przez-openpyxl"),
        pytest.param(_internal_header_after_k, True, False, id="naglowek-wewnetrznego-za-K-przez-openpyxl"),
        pytest.param(
            _internal_header_repeated_after_k, True, False, id="naglowek-wewnetrznego-powtorzony-za-K-przez-openpyxl"
        ),
    ],
)
def test_pliki_okresu_z_kopii_wzorca_sa_takie_jak_z_openpyxl(
    tmp_path: Path,
    make_fixture: Callable[[Path], PreparationFixture],
    collective_copied: bool,
    internal_copied: bool,
) -> None:
    (tmp_path / "kopia").mkdir()
    (tmp_path / "openpyxl").mkdir()
    by_copy = make_fixture(tmp_path / "kopia")
    by_openpyxl = make_fixture(tmp_path / "openpyxl")
    for template in (by_copy.collective_template_path, by_copy.internal_template_path):
        marked_for_copy(template)
    for template in (by_openpyxl.collective_template_path, by_openpyxl.internal_template_path):
        refused_by_copy(marked_for_copy(template))
    run_preparation(by_copy)
    run_preparation(by_openpyxl)

    for created, reference, template, copied in (
        (by_copy.collective_file_path, by_openpyxl.collective_file_path, by_copy.collective_template_path, collective_copied),
        (by_copy.internal_settlement_path, by_openpyxl.internal_settlement_path, by_copy.internal_template_path, internal_copied),
    ):
        with zipfile.ZipFile(created) as archive:
            keeps_template_calc_chain = "xl/calcChain.xml" in archive.namelist()
        with zipfile.ZipFile(template) as archive:
            template_has_calc_chain = "xl/calcChain.xml" in archive.namelist()

        assert written_by_copy(created) == copied
        assert not has_xml_comment(reference)
        assert _cells(created) == _cells(reference)
        assert external_link_parts(created) == external_link_parts(reference)
        assert keeps_template_calc_chain == (copied and template_has_calc_chain)



def test_kopia_pliku_zbiorczego_zmienia_nazwe_filtra_tylko_aktywnego_arkusza(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    other = b'<ns0:definedName name="_xlnm._FilterDatabase" localSheetId="1" hidden="1">\'Rates\'!$A$1:$B$2</ns0:definedName>'
    rewrite_parts(
        marked_for_copy(fixture.collective_template_path),
        lambda name, data: data.replace(b"<ns0:definedNames>", b"<ns0:definedNames>" + other, 1) if name == "xl/workbook.xml" else data,
    )
    assert _filter_database(fixture.collective_template_path) == ["Rates!$A$1:$B$2", "Sheet1!$B$17:$C$57"]

    run_preparation(fixture)

    created = fixture.collective_file_path
    workbook = load_workbook(created)
    try:
        ref = active_worksheet(workbook).auto_filter.ref
    finally:
        workbook.close()
    assert written_by_copy(created)
    assert _filter_database(created) == ["Rates!$A$1:$B$2", f"Sheet1!{absolute_coordinate(ref)}"]


def _looks(path: Path, references: tuple[str, ...]) -> dict[str, tuple[object, ...]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return {
            reference: (
                *(side.style for side in (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)),
                cell.alignment.horizontal,
                cell.alignment.vertical,
            )
            for reference in references
            for cell in (sheet[reference],)
        }
    finally:
        workbook.close()


ROW_LOOK = ("thin", "thin", "thin", "thin", "left", "center")


def test_kolumna_rozliczenia_wewnetrznego_za_kolumnami_wygladu_dostaje_wyglad_wiersza_danych(tmp_path: Path) -> None:
    fixture = _internal_header_repeated_after_k(tmp_path)
    run_preparation(fixture)

    workbook = load_workbook(fixture.internal_settlement_path)
    try:
        sheet = active_worksheet(workbook)
        assert sheet["N1"].value == INTERNAL_HEADERS[1] and sheet["N2"].value is not None
    finally:
        workbook.close()
    assert _looks(fixture.internal_settlement_path, ("C2", "N2")) == dict.fromkeys(("C2", "N2"), ROW_LOOK)


def test_rozliczenie_wewnetrzne_z_kopii_ma_wyglad_wiersza_danych_w_a_m_z_kolumnami_zwrot_i_uwagi(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    marked_for_copy(fixture.internal_template_path)
    run_preparation(fixture)

    workbook = load_workbook(fixture.internal_settlement_path)
    try:
        assert [cell.value for cell in active_worksheet(workbook)[1][11:13]] == ["zwrot", "UWAGI"]
    finally:
        workbook.close()
    assert written_by_copy(fixture.internal_settlement_path)
    assert _looks(fixture.internal_settlement_path, ("A2", "L2", "M2")) == dict.fromkeys(("A2", "L2", "M2"), ROW_LOOK)


_QUANTITY_LETTERS = [get_column_letter(column) for column in range(14, 43)]


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


def _zeros_beside_quantities(path: Path) -> None:
    """Wiersz 20 bez liczb w N:AP, a z liczbą 0 w kolumnach tuż obok nich, M i AQ: to nie wiersz przygotowany zerami."""

    replace_cells(
        path,
        {f"{letter}20": f'<c r="{letter}20"/>' for letter in _QUANTITY_LETTERS[1:-1]}
        | {"N20": '<c r="M20"><v>0</v></c><c r="N20"/>', "AP20": '<c r="AP20"/><c r="AQ20"><v>0</v></c>'},
    )


def _zero_only_in_ap(path: Path) -> None:
    _third_zero_row(path, lambda reference: f'<c r="{reference}"/>' if reference != "AP20" else '<c r="AP20"><v>0.0</v></c>')


@pytest.mark.parametrize("copied", [True, False], ids=["kopia", "openpyxl"])
@pytest.mark.parametrize(
    ("change", "zero_rows"),
    [
        pytest.param(lambda path: None, COLLECTIVE_TEMPLATE_ZERO_ROWS, id="wzorzec"),
        pytest.param(_zero_only_in_ap, COLLECTIVE_TEMPLATE_ZERO_ROWS, id="zero-tylko-w-AP"),
        pytest.param(_zeros_beside_quantities, 2, id="zera-obok-N-AP"),
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
