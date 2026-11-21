from __future__ import annotations

from datetime import datetime, time

import pytest

from rozliczenia.cell_values import CellValues
from rozliczenia.workbook_parts import Relationship, sheet_cells

WORKBOOK = "xl/workbook.xml"
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STYLES = (
    f'<styleSheet xmlns="{_MAIN}"><numFmts count="2"><numFmt numFmtId="164" formatCode="dd.mm.yyyy hh:mm"/>'
    '<numFmt numFmtId="165" formatCode="0.00"/></numFmts><cellXfs count="5"><xf numFmtId="0"/><xf numFmtId="14"/>'
    '<xf numFmtId="164"/><xf numFmtId="165"/><xf numFmtId="20"/></cellXfs></styleSheet>'
).encode()
GENERAL, BUILT_IN_DATE, OWN_DATE, OWN_NUMBER, BUILT_IN_TIME = range(5)
SHARED = f'<sst xmlns="{_MAIN}"><si><t>Jan</t></si><si><t>   </t></si></sst>'.encode()
RELS = {
    "rId1": Relationship(f"{_REL}/styles", "xl/styles.xml", False),
    "rId2": Relationship(f"{_REL}/sharedStrings", "xl/sharedStrings.xml", False),
}
LAST_MOMENT = "2958465.9999999884"


def _values(*, date1904: bool = False, rels: dict[str, Relationship] = RELS) -> CellValues:
    properties = '<workbookPr date1904="1"/>' if date1904 else ""
    workbook = f'<workbook xmlns="{_MAIN}">{properties}<sheets/></workbook>'.encode()
    parts = {WORKBOOK: workbook, "xl/styles.xml": STYLES, "xl/sharedStrings.xml": SHARED}
    return CellValues.of(parts, WORKBOOK, rels)


def _cell(attributes: str, content: str | None) -> str:
    return f'<c r="A1"{attributes}/>' if content is None else f'<c r="A1"{attributes}>{content}</c>'


@pytest.mark.parametrize(
    ("cell", "date1904", "expected"),
    [
        pytest.param(_cell(' t="s"', "<v>0</v>"), False, "Jan", id="tekst-wspolny"),
        pytest.param(_cell(' t="inlineStr"', "<is><t>Kowalski &amp; syn</t></is>"), False, "Kowalski & syn", id="tekst-wbudowany"),
        pytest.param(_cell("", "<v>12.5</v>"), False, 12.5, id="liczba"),
        pytest.param(_cell(f' s="{OWN_NUMBER}"', "<v>46000</v>"), False, 46000.0, id="liczba-w-formacie-liczby"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>46000</v>"), False, datetime(2025, 12, 9), id="data-we-wbudowanym-formacie-daty"),
        pytest.param(_cell(f' s="{OWN_DATE}"', "<v>46000.5</v>"), False, datetime(2025, 12, 9, 12), id="data-we-wlasnym-formacie-daty"),
        pytest.param(_cell(f' s="{BUILT_IN_TIME}"', "<v>0.75</v>"), False, time(18), id="liczba-ponizej-1-to-godzina"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>0</v>"), False, time(0), id="zero-w-formacie-daty-to-polnoc"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>1</v>"), True, datetime(1904, 1, 2), id="data-w-systemie-dat-1904"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>1</v>"), False, datetime(1900, 1, 1), id="data-w-systemie-dat-1900"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>-1</v>"), False, -1.0, id="ujemna-w-formacie-daty-zostaje-liczba"),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>2958465</v>"), False, datetime(9999, 12, 31), id="ostatni-dzien-excela"),
        pytest.param(
            _cell(f' s="{BUILT_IN_DATE}"', f"<v>{LAST_MOMENT}</v>"),
            False,
            datetime(9999, 12, 31, 23, 59, 59, 999000),
            id="ostatnia-chwila-excela",
        ),
        pytest.param(_cell(f' s="{BUILT_IN_DATE}"', "<v>2958466</v>"), False, 2958466.0, id="za-ostatnia-chwila-zostaje-liczba"),
        pytest.param(_cell(' t="b"', "<v>1</v>"), False, "1", id="prawda-to-tekst-1"),
        pytest.param(_cell(' t="b"', "<v>0</v>"), False, "0", id="falsz-to-tekst-0"),
        pytest.param(_cell(' t="e"', "<v>#N/A</v>"), False, "#N/A", id="blad-to-tekst-zapisu"),
        pytest.param(_cell(' t="str"', "<f>A2&amp;A3</f><v>a&amp;b</v>"), False, "a&b", id="wynik-formuly-tekstem"),
        pytest.param(_cell("", None), False, None, id="pusta"),
        pytest.param(_cell(' t="s"', "<v>1</v>"), False, None, id="tekst-wspolny-z-samych-odstepow"),
        pytest.param(_cell(' t="inlineStr"', "<is><t> </t></is>"), False, None, id="tekst-wbudowany-z-samych-odstepow"),
    ],
)
def test_wartosc_komorki_ma_typ_wedlug_rodzaju_i_formatu_daty_w_systemie_dat_skoroszytu(
    cell: str, date1904: bool, expected: object
) -> None:
    (found,) = sheet_cells(cell.encode())

    value = _values(date1904=date1904).value(found)

    assert (type(value), value) == (type(expected), expected)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>3</v></c></row>', ["Jan", None, 3.0], id="od-kolumny-a"),
        pytest.param('<row r="1"/>', [], id="pusty-wiersz-1"),
        pytest.param('<row r="2"><c r="A2"><v>1</v></c></row>', [], id="bez-wiersza-1"),
    ],
)
def test_naglowek_to_wartosci_wiersza_1_od_kolumny_a(row: str, expected: list[object]) -> None:
    sheet = f'<worksheet xmlns="{_MAIN}"><sheetData>{row}</sheetData></worksheet>'.encode()

    assert _values().header(sheet) == expected


def test_skoroszyt_bez_czesci_stylow_jest_nieczytelny() -> None:
    with pytest.raises(KeyError):
        _values(rels={"rId2": RELS["rId2"]})
