from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rozliczenia.input_copy import InputCopy, Typed
from rozliczenia.row_positions import RowPositions

PERIOD_FOLDER = Path("Załączniki") / "Rozliczenia 2026" / "09_Wrzesień_2026" / "INEA" / "08_14_09_2026"
REGISTER = Path("Załączniki") / "INTERMAX" / "INTERMAX.xlsx"
WHEN = datetime(2026, 9, 8, 7, 30)


def test_kopia_ma_pliki_w_kolejnosci_odczytu_z_sama_nazwa_i_dwoma_folderami_nad_plikiem() -> None:
    copy = InputCopy()
    copy.workbook(PERIOD_FOLDER / "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx", b"syntetyczny plik zbiorczy", None)
    copy.workbook(REGISTER, b"syntetyczny INTERMAX", None)

    assert [(file.name, file.folders) for file in copy.files()] == [
        ("Rozliczenie 08_14_09_2026 - zbiorcze.xlsx", ("INEA", "08_14_09_2026")),
        ("INTERMAX.xlsx", ("Załączniki", "INTERMAX")),
    ]


def test_komorka_przesunietego_wiersza_stoi_w_kopii_pod_swoim_naglowkiem_z_data_z_godziny_spoza_kolumn_kopii() -> None:
    sheet = InputCopy().workbook(REGISTER, b"syntetyczny INTERMAX", None).sheet(
        "Zlecenia",
        1,
        ["", "", "DATA GODZ. POCZ.", "NUMER ZL.", "UWAGI"],
        [],
        copied_columns=[4, 5],
        date_column=3,
    )
    sheet.row(2, {1: WHEN, 2: "ZL-001", 3: "syntetyczna uwaga"}, RowPositions(read=2, known=(2,)))

    [row] = sheet.copied().rows

    assert row.cells == {"C": Typed("datetime", WHEN.isoformat()), "D": "ZL-001", "E": "syntetyczna uwaga"}


def test_wiersz_z_siatki_ma_w_kopii_tylko_komorki_z_kolumn_kopii_w_kazdym_polozeniu() -> None:
    sheet = InputCopy().workbook(REGISTER, b"syntetyczny INTERMAX", None).sheet(
        "Zlecenia", 1, ["NUMER ZL.", "URZĄDZENIA", "UWAGI", "", ""], [], copied_columns=[1, 2, 3]
    )
    sheet.row(2, ["ZL-001", "syntetyczne urządzenie", "syntetyczna uwaga"], RowPositions(known=(0, 2)))

    [row] = sheet.copied().rows

    assert row.cells == {"A": "ZL-001"}


def test_wartosc_spoza_typow_kopii_to_nazwa_jej_typu() -> None:
    sheet = InputCopy().workbook(REGISTER, b"syntetyczny INTERMAX", None).sheet("Zlecenia", 1, ["ILOŚĆ"], [])
    sheet.row(2, [Decimal("1.5")])

    [row] = sheet.copied().rows

    assert row.cells == {"A": Typed("other", "Decimal")}


def test_drugi_przesuniety_wiersz_arkusza_to_blad_w_kodzie() -> None:
    sheet = InputCopy().workbook(REGISTER, b"syntetyczny INTERMAX", None).sheet("Zlecenia", 1, ["NUMER ZL."], [])
    for number in (2, 3):
        sheet.row(number, ["ZL-001"], RowPositions(read=2, known=(2,)))

    with pytest.raises(ValueError, match=r"\[2, 3\]"):
        sheet.copied()
