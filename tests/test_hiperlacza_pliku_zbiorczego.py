"""Hiperłącza Wierszy danych Pliku zbiorczego: które komórki je niosą i jaki mają adres (``read_data_rows``)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from rozliczenia.dad_files import DadFiles
from rozliczenia.workbook_files import read_data_rows
from atrapy.settlement import write_source

SHEET = "xl/worksheets/sheet1.xml"
SHEET_RELS = "xl/worksheets/_rels/sheet1.xml.rels"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_HYPERLINK = f"{_REL}/hyperlink"
ORDER = "https://przyklad.invalid/zlecenie?caseId=SYN-1&amp;tw=1"
OTHER = "https://przyklad.invalid/zlecenie?caseId=SYN-2"


def _relationship(rid: str, target: str, *, kind: str = _HYPERLINK, external: bool = True) -> str:
    mode = ' TargetMode="External"' if external else ""
    return f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"{mode}/>'


def with_hyperlinks(path: Path, links: str | None, relationships: str | None, *, root: str = "") -> None:
    """Arkusz Pliku zbiorczego z blokiem ``<hyperlinks>`` przed ``pageMargins`` i relacjami arkusza.

    ``links`` to elementy ``<hyperlink>`` (``None``: bez bloku), ``relationships`` to wpisy części relacji
    arkusza (``None``: bez tej części), ``root`` to deklaracje przestrzeni nazw dopisane do ``<worksheet>``;
    bez niej przedrostek ``r`` jest deklarowany na bloku, jak zapisuje openpyxl.
    """

    with zipfile.ZipFile(path) as source:
        parts = {info.filename: source.read(info) for info in source.infolist()}
    sheet = parts[SHEET]
    if root:
        sheet = sheet.replace(b"<worksheet ", b"<worksheet " + root.encode() + b" ", 1)
    if links is not None:
        declaration = "" if root else f' xmlns:r="{_REL}"'
        block = f"<hyperlinks{declaration}>{links}</hyperlinks>".encode()
        sheet = sheet.replace(b"<pageMargins", block + b"<pageMargins", 1)
    parts[SHEET] = sheet
    parts.pop(SHEET_RELS, None)
    if relationships is not None:
        parts[SHEET_RELS] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}'
            "</Relationships>"
        ).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in parts.items():
            target.writestr(name, data)


def _collective_file(tmp_path: Path) -> Path:
    """Plik zbiorczy z Wierszami danych 18–20, numerami zleceń w F i pustym C."""

    path = tmp_path / "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
    write_source(path, include_unmapped=False)
    return path


def _links_by_row(path: Path) -> dict[int, dict[str, str]]:
    letters = {1: "A", 2: "B", 3: "C", 6: "F", 8: "H"}
    return {
        row.number: links
        for row in read_data_rows(path, DadFiles()).rows
        if (
            links := {
                letters.get(column, str(column)): cell.hyperlink.address
                for column, cell in enumerate(row.cells, start=1)
                if cell.hyperlink is not None
            }
        )
    }


ORDER_ADDRESS = "https://przyklad.invalid/zlecenie?caseId=SYN-1&tw=1"


@pytest.mark.parametrize(
    ("links", "relationships", "root", "expected"),
    [
        pytest.param(None, None, "", {}, id="bez-hiperlaczy"),
        pytest.param(
            '<hyperlink ref="F18" r:id="rId1"/>', _relationship("rId1", ORDER), "", {18: {"F": ORDER_ADDRESS}}, id="komorka"
        ),
        pytest.param(
            '<hyperlink ref="F18" r:id="rId3" display="adres" xr:uid="{00000000-0000-0000-0000-000000000001}"/>',
            _relationship("rId3", ORDER),
            f'xmlns:r="{_REL}" xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision"',
            {18: {"F": ORDER_ADDRESS}},
            id="jak-z-excela",
        ),
        pytest.param(
            '<hyperlink ref="F18" r:id="rId1" location="sekcja-2"/>',
            _relationship("rId1", ORDER),
            "",
            {18: {"F": f"{ORDER_ADDRESS}#sekcja-2"}},
            id="adres-z-miejscem",
        ),
        pytest.param(
            '<hyperlink ref="F18:F20" r:id="rId1"/>',
            _relationship("rId1", ORDER),
            "",
            {row: {"F": ORDER_ADDRESS} for row in (18, 19, 20)},
            id="zakres",
        ),
        pytest.param(
            '<hyperlink ref="F18" r:id="rId1"/><hyperlink ref="F18" r:id="rId2"/>',
            _relationship("rId1", ORDER) + _relationship("rId2", OTHER),
            "",
            {18: {"F": OTHER}},
            id="powtorzona-komorka-ostatnie-wygrywa",
        ),
        pytest.param(
            '<hyperlink ref="F19" r:id="rId2"/><hyperlink ref="F18:F20" r:id="rId1"/>',
            _relationship("rId1", ORDER) + _relationship("rId2", OTHER),
            "",
            {row: {"F": ORDER_ADDRESS} for row in (18, 19, 20)},
            id="zakres-po-komorce-wygrywa",
        ),
        pytest.param(
            '<hyperlink ref="F18:F20" r:id="rId1"/><hyperlink ref="F19" r:id="rId2"/>',
            _relationship("rId1", ORDER) + _relationship("rId2", OTHER),
            "",
            {18: {"F": ORDER_ADDRESS}, 19: {"F": OTHER}, 20: {"F": ORDER_ADDRESS}},
            id="komorka-po-zakresie-wygrywa",
        ),
        pytest.param(
            '<hyperlink ref="F18" location="\'Arkusz2\'!A1"/>', None, "", {}, id="miejsce-w-skoroszycie-nie-przechodzi"
        ),
        pytest.param('<hyperlink ref="F18" r:id="rId9"/>', _relationship("rId1", ORDER), "", {}, id="brak-relacji"),
        pytest.param('<hyperlink ref="F18" r:id="rId1"/>', None, "", {}, id="brak-czesci-relacji"),
        pytest.param(
            '<hyperlink ref="F18" r:id="rId1"/>',
            _relationship("rId1", "../comments1.xml", kind=f"{_REL}/comments", external=False),
            "",
            {},
            id="relacja-do-czesci-skoroszytu",
        ),
        pytest.param(
            '<hyperlink ref="C18" r:id="rId1"/><hyperlink ref="B19" r:id="rId1"/>',
            _relationship("rId1", ORDER),
            "",
            {19: {"B": ORDER_ADDRESS}},
            id="komorka-bez-wartosci-nie-niesie-hiperlacza",
        ),
    ],
)
def test_wiersze_danych_maja_hiperlacza_z_adresem_poza_skoroszytem(
    tmp_path: Path, links: str | None, relationships: str | None, root: str, expected: dict[int, dict[str, str]]
) -> None:
    path = _collective_file(tmp_path)
    with_hyperlinks(path, links, relationships, root=root)
    before = path.read_bytes()

    assert _links_by_row(path) == expected
    assert path.read_bytes() == before

