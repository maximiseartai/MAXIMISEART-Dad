"""Wiersze bez ilości dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń (#415, #421, ADR 0016), przez HTTP API.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, zmienia go jak tata w Excelu
(openpyxl) i pyta Centrum o wiersze bez ilości okresu, które okno potwierdzenia wymieni.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import workbook_files
from rozliczenia.centrum.filling import without_quantity_sentence
from tests.fixtures.centrum_processes import Surroundings, filling_centrum
from atrapy.preparation import PERIOD

URL = f"/api/periods/{PERIOD}/without-quantity"


def _write(path: Path, cells: dict[str, int | str | None], *, header: str | None = None) -> None:
    """Zmiana Pliku zbiorczego jak tata w Excelu; ``header`` to nagłówek wiersza 17, który tata usuwa."""

    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for cell, value in cells.items():
        sheet[cell] = value
    for found in sheet[17]:
        if header is not None and found.value == header:
            found.value = None
    workbook.save(path)


def test_okno_dostaje_wiersze_bez_ilosci_rosnaco_ze_zdaniem(tmp_path: Path) -> None:
    assert filling_centrum(tmp_path).view(URL) == {"state": "read", "sentence": "4 wiersze bez ilości: 19, 20, 21, 22"}


def test_po_uzupelnieniu_w_pliku_okno_przestaje_wymieniac_wiersze(tmp_path: Path) -> None:
    centrum = filling_centrum(tmp_path)
    path = centrum.fixture.collective_file_path

    _write(path, {"O19": 1, "AP21": 2})
    assert centrum.view(URL) == {"state": "read", "sentence": "2 wiersze bez ilości: 20, 22"}

    _write(path, {"N20": 45, "AE22": 3})
    assert centrum.view(URL) == {"state": "read", "sentence": None}


def test_nieczytelny_plik_zbiorczy_daje_unread_zamiast_bledu(tmp_path: Path) -> None:
    centrum = filling_centrum(tmp_path)
    centrum.fixture.collective_file_path.write_bytes(b"to nie jest skoroszyt")

    assert centrum.view(URL) == {"state": "unread"}


def test_plik_zbiorczy_bez_naglowka_urzadzen_daje_unread(tmp_path: Path) -> None:
    centrum = filling_centrum(tmp_path)
    _write(centrum.fixture.collective_file_path, {}, header="URZĄDZENIA")

    assert centrum.view(URL) == {"state": "unread"}


def test_ustawienie_przebiegu_nie_otwiera_zadnego_pliku_zbiorczego(tmp_path: Path) -> None:
    opened: list[Path] = []

    def spy(path: Path) -> bytes:
        opened.append(path)
        return workbook_files.file_bytes(path)

    centrum = filling_centrum(tmp_path, surroundings=Surroundings(source=spy))
    opened.clear()
    response = centrum.client.get("/api/runs/setup")
    assert response.status_code == 200, response.text
    settlement = next(setup for setup in response.json()["processes"] if setup["process"] == "settlement")
    assert PERIOD in [choice["token"] for choice in settlement["periods"]]
    assert opened == []

    centrum.view(URL)
    assert opened == [centrum.fixture.collective_file_path]


@pytest.mark.parametrize(
    ("count", "word"),
    [
        (1, "wiersz"),
        (2, "wiersze"),
        (4, "wiersze"),
        (5, "wierszy"),
        (12, "wierszy"),
        (13, "wierszy"),
        (14, "wierszy"),
        (21, "wierszy"),
        (22, "wiersze"),
        (112, "wierszy"),
        (124, "wiersze"),
    ],
)
def test_zdanie_okna_odmienia_wiersze(count: int, word: str) -> None:
    rows = list(range(18, 18 + count))

    assert without_quantity_sentence(rows) == f"{count} {word} bez ilości: {', '.join(map(str, rows))}"
