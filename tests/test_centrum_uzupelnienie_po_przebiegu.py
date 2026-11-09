"""Uzupełnienie pliku zbiorczego po Przebiegu rozliczeń (#415, #422, ADR 0016), przez HTTP API jak przeglądarka.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, tata wpisuje w nim jedną ilość
(openpyxl, jak w Excelu), a Centrum uruchamia na nim prawdziwy Przebieg rozliczeń. Potem strony okresu są
podglądem: wiersz, w którym tata nic nie wpisał, jest „bez ilości”.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.fixtures.centrum import finished_view
from tests.fixtures.centrum_processes import WORKER_SETTLEMENTS, PreparingCentrum, preparing_centrum, run_to_end
from atrapy.preparation import PERIOD, register_order
from atrapy.settlement import write_template

TUE = datetime(2026, 9, 8, 10, 0)
MON = datetime(2026, 9, 14, 9, 0)
URL = f"/api/periods/{PERIOD}/quantities-to-fill"

# Zlecenia skuteczne okresu po kolei, więc w Pliku zbiorczym od wiersza 18: wiersz → URZĄDZENIA.
DEVICES = {
    18: "nokia zte",  # Reguły ilości znają każdy składnik
    19: "przeniesienie",  # nieznane URZĄDZENIA: wiersz bez reguły
    20: "prewencja",  # wiersz z opisu
    21: "",  # puste URZĄDZENIA: wiersz z opisu
    22: "router x9",  # nieznane URZĄDZENIA: wiersz bez reguły
}


def _prepared(tmp_path: Path) -> PreparingCentrum:
    # Ostatnie zlecenie w poniedziałek: okres jest pełny, więc Przygotowanie nie czeka na Decyzję taty.
    starts = [TUE.replace(hour=8 + index) for index in range(len(DEVICES) - 1)] + [MON]
    rows = [
        {**register_order(index, started), "URZĄDZENIA": text}
        for index, (text, started) in enumerate(zip(DEVICES.values(), starts, strict=True), start=1)
    ]
    centrum = preparing_centrum(tmp_path, list(rows))
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    write_template(tmp_path / "config" / "Wzorzec rozliczenia pracownika.xlsx")
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


def _get(centrum: PreparingCentrum, url: str) -> dict[str, Any]:
    response = centrum.client.get(url)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def _states(view: dict[str, Any]) -> dict[str, list[tuple[int, str]]]:
    return {kind["kind"]: [(row["row"], row["state"]) for row in kind["rows"]] for kind in view["kinds"]}


def test_przed_przebiegiem_wiersze_bez_wpisu_czekaja_na_tate(tmp_path: Path) -> None:
    view = _get(_prepared(tmp_path), URL)

    assert view["settled"] is False
    assert _states(view) == {
        "without_rule": [(19, "done"), (22, "to_fill")],
        "from_description": [(20, "to_fill"), (21, "to_fill")],
    }


def test_po_przebiegu_podsumowanie_mowi_ze_sie_odbyl_a_niezrobione_sa_bez_ilosci(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    view = _get(centrum, URL)

    assert view["settled"] is True
    assert _states(view) == {
        "without_rule": [(19, "done"), (22, "without_quantity")],
        "from_description": [(20, "without_quantity"), (21, "without_quantity")],
    }
    assert {kind["kind"]: kind["done"] for kind in view["kinds"]} == {"without_rule": False, "from_description": False}


def test_po_przebiegu_strona_rodzaju_pokazuje_wiersze_bez_ilosci(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    table = _get(centrum, f"{URL}/without_rule")

    assert table["settled"] is True
    assert [(row["row"], row["state"]) for row in table["rows"]] == [(19, "done"), (22, "without_quantity")]


def test_po_przebiegu_okno_gotowosci_dalej_wymienia_te_same_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _settle(centrum)

    assert _get(centrum, f"/api/periods/{PERIOD}/without-quantity")["sentence"] == "3 wiersze bez ilości: 20, 21, 22"
