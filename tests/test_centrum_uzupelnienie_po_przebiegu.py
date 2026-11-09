"""Uzupełnienie pliku zbiorczego po Przebiegu rozliczeń (#415, #422, ADR 0016), przez HTTP API jak przeglądarka.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, tata wpisuje w nim jedną ilość
(openpyxl, jak w Excelu), a Centrum uruchamia na nim prawdziwy Przebieg rozliczeń. Potem strony okresu są
podglądem: wiersz, w którym tata nic nie wpisał, jest „bez ilości”.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import tool_files
from tests.fixtures.centrum import finished_view
from tests.fixtures.centrum_processes import WORKER_SETTLEMENTS, PreparingCentrum, filling_centrum
from atrapy.preparation import PERIOD
from atrapy.settlement import write_template

URL = f"/api/periods/{PERIOD}/quantities-to-fill"


def _prepared(tmp_path: Path) -> PreparingCentrum:
    centrum = filling_centrum(tmp_path)
    write_template(tool_files.config_dir(tmp_path) / tool_files.WORKER_TEMPLATE.name)
    # Tata uzupełnia tylko wiersz 19 i zapisuje Plik zbiorczy.
    path = centrum.fixture.collective_file_path
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet["O19"] = 1
    workbook.save(path)
    return centrum


def _settle(centrum: PreparingCentrum) -> None:
    started = centrum.client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "RUN"})
    assert started.status_code == 200, started.text
    assert finished_view(centrum.client)["result"]["result"] == "OK"
    assert (centrum.fixture.collective_file_path.parent / WORKER_SETTLEMENTS).is_dir()


def _states(view: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    return {kind["kind"]: [(row["row"], row["state"]) for row in kind["rows"]] for kind in view["kinds"]}


def test_przed_przebiegiem_wiersze_bez_wpisu_czekaja_na_tate(tmp_path: Path) -> None:
    view = _prepared(tmp_path).view(URL)

    assert view["settled"] is False
    assert _states(view) == {
        "without_rule": [(19, "done"), (22, "to_fill")],
        "from_description": [(20, "to_fill"), (21, "to_fill")],
    }


def test_po_przebiegu_podsumowanie_mowi_ze_sie_odbyl_a_niezrobione_sa_bez_ilosci(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    view = centrum.view(URL)

    assert view["settled"] is True
    assert _states(view) == {
        "without_rule": [(19, "done"), (22, "without_quantity")],
        "from_description": [(20, "without_quantity"), (21, "without_quantity")],
    }
    assert {kind["kind"]: kind["done"] for kind in view["kinds"]} == {"without_rule": False, "from_description": False}


def test_po_przebiegu_strona_rodzaju_pokazuje_wiersze_bez_ilosci(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    table = centrum.view(f"{URL}/without_rule")

    assert table["settled"] is True
    assert [(row["row"], row["state"]) for row in table["rows"]] == [(19, "done"), (22, "without_quantity")]


def test_po_przebiegu_okno_gotowosci_dalej_wymienia_te_same_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    assert centrum.view(f"/api/periods/{PERIOD}/without-quantity")["sentence"] == "3 wiersze bez ilości: 20, 21, 22"
