"""Wiersze bez ilości dla okna „Uruchomić z zapisem?” Przebiegu rozliczeń (#415, #421, ADR 0016), przez HTTP API.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, zmienia go jak tata w Excelu
(openpyxl) i pyta Centrum o wiersze bez ilości okresu, które okno potwierdzenia wymieni.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import workbook_files
from rozliczenia.centrum.filling import without_quantity_sentence
from rozliczenia.input_checks import FILE_READERS
from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum, run_to_end
from atrapy.preparation import PERIOD, register_order

TUE = datetime(2026, 9, 8, 10, 0)
MON = datetime(2026, 9, 14, 9, 0)
URL = f"/api/periods/{PERIOD}/without-quantity"

# Zlecenia skuteczne okresu po kolei, więc w Pliku zbiorczym od wiersza 18: wiersz → URZĄDZENIA.
DEVICES = {
    18: "nokia zte",  # Reguły ilości znają każdy składnik
    19: "przeniesienie",  # wiersz bez reguły
    20: "prewencja",  # wiersz z opisu
    21: "",  # wiersz z opisu
    22: "router x9",  # wiersz bez reguły
}


def _prepared(tmp_path: Path, *, surroundings: Surroundings | None = None) -> PreparingCentrum:
    # Ostatnie zlecenie w poniedziałek: okres jest pełny, więc Przygotowanie nie czeka na Decyzję taty.
    starts = [TUE.replace(hour=8 + index) for index in range(len(DEVICES) - 1)] + [MON]
    rows = [
        {**register_order(index, started), "URZĄDZENIA": text}
        for index, (text, started) in enumerate(zip(DEVICES.values(), starts, strict=True), start=1)
    ]
    centrum = preparing_centrum(tmp_path, list(rows), surroundings=surroundings)
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    return centrum


def _without_quantity(centrum: PreparingCentrum) -> dict[str, Any]:
    response = centrum.client.get(URL)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


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
    assert _without_quantity(_prepared(tmp_path)) == {"state": "read", "sentence": "4 wiersze bez ilości: 19, 20, 21, 22"}


def test_po_uzupelnieniu_w_pliku_okno_przestaje_wymieniac_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path

    _write(path, {"O19": 1, "AP21": 2})
    assert _without_quantity(centrum) == {"state": "read", "sentence": "2 wiersze bez ilości: 20, 22"}

    _write(path, {"N20": 45, "AE22": 3})
    assert _without_quantity(centrum) == {"state": "read", "sentence": None}


def test_v_t_i_n_nie_zdejmuja_wiersza_bez_reguly_a_zero_nie_jest_iloscia(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum.fixture.collective_file_path, {"V19": 1, "T19": 1, "N19": 45, "O22": 0, "Y20": "0"})

    assert _without_quantity(centrum)["sentence"] == "4 wiersze bez ilości: 19, 20, 21, 22"


def test_plik_otwarty_w_excelu_dalej_wymienia_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")

    assert _without_quantity(centrum)["sentence"] == "4 wiersze bez ilości: 19, 20, 21, 22"


def test_nieczytelny_plik_zbiorczy_daje_unread_zamiast_bledu(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.write_bytes(b"to nie jest skoroszyt")

    assert _without_quantity(centrum) == {"state": "unread"}


def test_plik_zbiorczy_bez_naglowka_urzadzen_daje_unread(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum.fixture.collective_file_path, {}, header="URZĄDZENIA")

    assert _without_quantity(centrum) == {"state": "unread"}


def test_przeniesiony_folder_okresow_to_odmowa(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.periods_directory.rename(tmp_path / "przeniesiony")

    response = centrum.client.get(URL)

    assert (response.status_code, response.json()["message"]) == (409, "Najpierw wskaż folder okresów.")


def test_ustawienie_przebiegu_nie_otwiera_zadnego_pliku_zbiorczego(tmp_path: Path) -> None:
    opened: list[Path] = []

    def spy(path: Path) -> bytes:
        opened.append(path)
        return workbook_files.file_bytes(path)

    centrum = _prepared(tmp_path, surroundings=Surroundings(readers=replace(FILE_READERS, source=spy)))
    opened.clear()
    response = centrum.client.get("/api/runs/setup")
    assert response.status_code == 200, response.text
    settlement = next(setup for setup in response.json()["processes"] if setup["process"] == "settlement")
    assert PERIOD in [choice["token"] for choice in settlement["periods"]]
    assert opened == []

    _without_quantity(centrum)
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
