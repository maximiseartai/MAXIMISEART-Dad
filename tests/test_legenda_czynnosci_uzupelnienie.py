"""Ilości do uzupełnienia w Centrum rozliczeń z Legendą czynności z Wydania (ADR 0038, #1940), przez HTTP API.

Plik zbiorczy powstaje w Centrum z syntetycznego Rejestru zleceń, którego ``CZYNNOŚCI ZREALIZOWANE`` mają Kody
czynności z maila taty. Wiersz, którego opis to same kody, nie czeka na tatę, a wiersz z kodem obok zwykłego opisu
czeka, z wartościami legendy jako kolumnami narzędzia.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.fixtures.centrum_processes import PreparingCentrum, filling_centrum
from atrapy.preparation import PERIOD

URL = f"/api/periods/{PERIOD}/quantities-to-fill"
CELL_COLUMNS = (
    *("N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"),
    *("AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP"),
    "AS",
)
COMPLETED = {
    18: "spawpg",  # nokia zte: same kody
    19: "tak inst20m",  # przeniesienie (wiersz bez reguły): same kody
    20: "instmdik.",  # prewencja (wiersz z opisu): same kody
    21: "20 m patchcord dzielnik 1/2",  # puste URZĄDZENIA (wiersz z opisu): kod obok opisu
    22: "montaż",  # router x9 (wiersz bez reguły): bez kodu
}


def _prepared(tmp_path: Path) -> PreparingCentrum:
    return filling_centrum(tmp_path, columns=lambda _index, row: {"CZYNNOŚCI ZREALIZOWANE": COMPLETED[row]})


def _write(centrum: PreparingCentrum, cells: dict[str, int]) -> None:
    path = centrum.fixture.collective_file_path
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for cell, value in cells.items():
        sheet[cell] = value
    workbook.save(path)


def _rows(view: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    return {kind["kind"]: [(row["row"], row["state"]) for row in kind["rows"]] for kind in view["kinds"]}


def _shown(row: dict[str, Any]) -> dict[str, tuple[str, int | str]]:
    """Komórki wiersza, które coś pokazują: litera kolumny → (czyja wartość, wartość)."""

    return {
        column: (cell["source"], cell["value"])
        for column, cell in zip(CELL_COLUMNS, row["cells"], strict=True)
        if cell != {"source": "empty", "value": 0}
    }


def _table_rows(centrum: PreparingCentrum, kind: str) -> dict[int, dict[str, Any]]:
    table = centrum.view(f"{URL}/{kind}")
    assert [column["column"] for column in table["columns"]] == list(CELL_COLUMNS)
    return {row["row"]: row for row in table["rows"]}


def test_wiersz_z_opisu_z_samych_kodow_nie_czeka_na_tate_a_kod_obok_opisu_czeka(tmp_path: Path) -> None:
    view = _prepared(tmp_path).view(URL)

    assert _rows(view) == {"without_rule": [(19, "to_fill"), (22, "to_fill")], "from_description": [(21, "to_fill")]}
    assert view["description_rows"] == {"by_legend": 3, "for_tata": 2}


def test_kolumny_legendy_sa_kolumnami_narzedzia_takze_kwota_w_as(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    from_description = _table_rows(centrum, "from_description")
    without_rule = _table_rows(centrum, "without_rule")

    assert (from_description[21]["state"], _shown(from_description[21])) == ("to_fill", {"AS": ("tool", 50)})
    assert without_rule[19]["state"] == "to_fill"
    assert _shown(without_rule[19])["Y"] == ("tool", 1)
    assert "AS" not in _shown(without_rule[22])


def test_wpis_taty_poza_kolumnami_legendy_robi_wiersz_a_kwota_taty_w_as_nie(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum, {"Y21": 1, "AS22": 30, "Y19": 2})

    view = centrum.view(URL)
    from_description = _table_rows(centrum, "from_description")
    without_rule = _table_rows(centrum, "without_rule")

    assert _rows(view) == {"without_rule": [(19, "to_fill"), (22, "to_fill")], "from_description": [(21, "done")]}
    assert _shown(from_description[21]) == {"Y": ("tata", 1), "AS": ("tool", 50)}
    assert _shown(without_rule[19])["Y"] == ("tool", 2)
    assert _shown(without_rule[22])["AS"] == ("tata", 30)
    description = {column["column"]: column["rows"] for column in view["description_columns"]}
    assert (description["Y"], description["AB"]) == (1, 0), "Y19 i AB18 wpisała legenda, Y21 tata"
