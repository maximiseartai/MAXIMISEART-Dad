"""Wejścia na podsumowanie Uzupełnienia pliku zbiorczego (#420): czy „Otwórz Plik zbiorczy” ma co otworzyć.

Podsumowanie pokazuje przycisk tylko wtedy, gdy Plik zbiorczy jest w Folderze okresu, także gdy Centrum nie umie go
odczytać: uszkodzony albo bez nagłówka tata naprawia właśnie w Excelu.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end
from atrapy.preparation import PERIOD

URL = f"/api/periods/{PERIOD}/quantities-to-fill"


def _prepared(tmp_path: Path) -> PreparingCentrum:
    centrum = preparing_centrum(tmp_path)
    assert run_to_end(centrum, dry_run=False)["result"]["ending"] == "finished"
    assert centrum.fixture.collective_file_path.is_file()
    return centrum


def _problem(centrum: PreparingCentrum, url: str = URL) -> dict[str, Any]:
    response = centrum.client.get(url)
    assert response.status_code == 200, response.text
    view: dict[str, Any] = response.json()
    assert view["state"] == "problem"
    return view


def test_bez_pliku_zbiorczego_nie_ma_czego_otworzyc(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.unlink()

    view = _problem(centrum)

    assert view["message"]["what"] == "Nie ma Pliku zbiorczego tego okresu."
    assert view["collective_file_exists"] is False


def test_okres_bez_folderu_okresu_nie_ma_czego_otworzyc(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)

    view = _problem(centrum, "/api/periods/15_21_09_2026/quantities-to-fill")

    assert view["collective_file_exists"] is False


def test_plik_zbiorczy_bez_naglowka_da_sie_otworzyc_do_poprawki(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet["H17"] = None
    workbook.save(path)

    view = _problem(centrum)

    assert view["message"]["what"] == "Brakuje nagłówka w Pliku zbiorczym: WYKONAWCA w komórce H17."
    assert view["collective_file_exists"] is True


def test_uszkodzony_plik_zbiorczy_da_sie_otworzyc(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.write_bytes(b"to nie jest skoroszyt")

    view = _problem(centrum)

    assert view["message"]["what"] == "Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela."
    assert view["collective_file_exists"] is True
