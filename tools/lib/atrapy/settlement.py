"""Przebieg rozliczeń: syntetyczne pliki taty dla testów, narzędzi i skryptów skilli.

Plik zbiorczy, Wzorzec rozliczenia pracownika i Lista Wykonawców są
budowane w katalogu tymczasowym. Nie zawierają prawdziwych danych klientów.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from atrapy import pliki_taty
from atrapy.pliki_taty import (
    ADDRESS_COLUMN,
    AMOUNT_COLUMN,
    CITY_COLUMN,
    FIRST_DATA_ROW,
    HEADER_ROW,
    ORDER_COLUMN,
    QUANTITY_COLUMNS,
    WORKER_COLUMN,
)
from atrapy.workbooks import TEMPLATE_VIEW, View, active_worksheet, set_view
from rozliczenia.centrum.settings.workers import WORKERS as WORKER_LIST_FILE
from rozliczenia.worker_list import WorkerEntry, WorkerList

PERIOD = "08_14_09_2026"


NOT_A_PERIOD = "09_15_09_2026"  # wygląda jak token okresu, ale 9 września 2026 to środa


SOURCE_NAME = pliki_taty.collective_file_name(PERIOD)


# Lista Wykonawców: login Wykonawcy z pliku -> nazwa w Rozliczeniu pracownika.
WORKERS: dict[str, str] = {
    "adrian.testowy": "Adrian Testowy",
    "dariusz.fikcyjny2": "Darek Fikcyjny",
    "kamil.syntetyczny": "Kamil Syntetyczny",
}


def worker_list(names: Mapping[str, str] = WORKERS, addresses: Mapping[str, Sequence[str]] | None = None) -> WorkerList:
    """Lista Wykonawców z loginów i nazw ``names`` (domyślnie ``WORKERS``), z adresami ``addresses`` po loginie."""

    found = WorkerList.of([WorkerEntry([login], name, (addresses or {}).get(login, ())) for login, name in names.items()])
    assert isinstance(found, WorkerList), found
    return found


def write_worker_list(path: Path, workers: WorkerList | None = None) -> Path:
    """Plik Listy Wykonawców ``wykonawcy.yaml`` w kształcie właściciela Ustawień Centrum (domyślnie ``worker_list()``)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WORKER_LIST_FILE.dump(worker_list() if workers is None else workers), encoding="utf-8")
    return path


# Szerokości kolumn Wzorca rozliczenia pracownika: różne, z bardzo wąskimi C, E, L i M.
WORKER_TEMPLATE_COLUMN_WIDTHS: dict[int, float] = {
    1: 12.0,
    2: 30.5,
    3: 2.29,
    4: 14.0,
    5: 3.0,
    6: 20.33,
    7: 16.66,
    8: 18.0,
    9: 23.33,
    10: 11.0,
    11: 15.5,
    12: 2.0,
    13: 2.0,
    14: 6.5,
}


def write_template(path: Path, *, view: View = TEMPLATE_VIEW) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    set_view(sheet, view)
    for number, width in WORKER_TEMPLATE_COLUMN_WIDTHS.items():
        sheet.column_dimensions[get_column_letter(number)].width = width
    sheet.cell(HEADER_ROW, WORKER_COLUMN).value = "WYKONAWCA"
    sheet.cell(HEADER_ROW, 1).fill = PatternFill(fill_type="solid", fgColor="00AA55")
    for row in (FIRST_DATA_ROW, FIRST_DATA_ROW + 1):
        sheet.cell(row, AMOUNT_COLUMN).value = f"=N{row}"
        sheet.cell(row, QUANTITY_COLUMNS.start).value = 0
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = 17.5
    workbook.save(path)


@dataclass(frozen=True)
class SourceRow:
    """Wiersz danych Pliku zbiorczego Przebiegu: MIASTO, ADRES, Wykonawca i NUMER ZL."""

    city: str
    address: str
    worker: str
    order_number: str


SOURCE_ROWS = (
    SourceRow("POZNAŃ", "syntetyczny adres 1", "adrian.testowy", "#1"),
    SourceRow("POZNAŃ", "syntetyczny adres 2", "dariusz.fikcyjny2", "#2"),
    SourceRow("POZNAŃ", "syntetyczny adres 3", "adrian.testowy", "#3"),
)
UNMAPPED_SOURCE_ROW = SourceRow("POZNAŃ", "syntetyczny adres 4", "andrzej.nieznany2", "#4")


def write_source(path: Path, *, include_unmapped: bool = True) -> None:
    write_source_rows(path, [*SOURCE_ROWS, UNMAPPED_SOURCE_ROW] if include_unmapped else SOURCE_ROWS)


def write_source_rows(path: Path, rows: Sequence[SourceRow]) -> None:
    """Plik zbiorczy z nagłówkiem WYKONAWCA i ``rows`` od pierwszego Wiersza danych; ilość w N to numer w kolejności."""

    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(HEADER_ROW, WORKER_COLUMN).value = "WYKONAWCA"
    for row_number, row in enumerate(rows, start=FIRST_DATA_ROW):
        sheet.cell(row_number, CITY_COLUMN).value = row.city
        sheet.cell(row_number, ADDRESS_COLUMN).value = row.address
        sheet.cell(row_number, ORDER_COLUMN).value = row.order_number
        sheet.cell(row_number, WORKER_COLUMN).value = row.worker
        sheet.cell(row_number, QUANTITY_COLUMNS.start).value = row_number - HEADER_ROW
    workbook.save(path)


CellValue = str | int | float | datetime | date | time | timedelta | ArrayFormula | None

# Wiersz danych ze znacznikiem w każdej kolumnie z treścią zlecenia (MIASTO, ADRES, UMOWA, URZĄDZENIA, CZYNNOŚCI,
# NUMER ZL., NUMER UMOWY, CZYNNOŚCI ZREALIZOWANE, AQ:AT i ilość w V), w środę 09.09.2026 o 13:45 i z Wykonawcą
# ``adrian.testowy``, który Konfiguracja wykonawców mapuje na „Adrian Testowy”.
MARKED: dict[str, CellValue] = {
    "A": "ZNACZNIK-MIASTO",
    "B": "ZNACZNIK-ADRES",
    "C": "u ZNACZNIK-UMOWA",
    "D": "nokia ZNACZNIK-URZADZENIA",
    "E": "ZNACZNIK-CZYNNOSCI",
    "F": "ZNACZNIK-NUMER-ZL",
    "G": datetime(2026, 9, 9, 13, 45),
    "I": "ZNACZNIK-NUMER-UMOWY",
    "J": "tak",
    "K": "ZNACZNIK-ZREALIZOWANE",
    "AQ": "ZNACZNIK-AQ",
    "AR": "ZNACZNIK-AR",
    "AS": "ZNACZNIK-AS",
    "AT": "ZNACZNIK-AT",
    "V": "ZNACZNIK-ILOSC",
}


def write_quantity_source(path: Path, rows: Sequence[Mapping[str, CellValue]]) -> None:
    """Plik zbiorczy z nagłówkami A17:K17 Wzorca i Wierszami danych od 18: litera kolumny → wartość.

    Bez podanej wartości wiersz ma syntetyczne MIASTO, ADRES, NUMER ZL. i SKUTECZNE oraz Wykonawcę
    ``adrian.testowy``, więc Przebieg z zapisem kończy się wynikiem.
    """

    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    for number, header in enumerate(pliki_taty.COLLECTIVE_HEADERS, start=1):
        sheet.cell(HEADER_ROW, number).value = header
    for number, cells in enumerate(rows, start=FIRST_DATA_ROW):
        defaults: dict[str, CellValue] = {"A": "POZNAŃ", "B": f"syntetyczny adres {number}", "F": f"#{number}", "H": "adrian.testowy", "J": "tak"}
        for letter, value in {**defaults, **cells}.items():
            sheet[f"{letter}{number}"] = value
    workbook.save(path)


def link_order_numbers(path: Path, address: str) -> dict[int, str]:
    """Hiperłącze w ``NUMER ZL.`` (F) każdego Wiersza danych Pliku zbiorczego, jak przy zleceniu z aplikacji firmowej.

    Adres to ``address`` z numerem wiersza na końcu; zwraca numer wiersza → adres.
    """

    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        links = {
            row: f"{address}{row}"
            for row in range(FIRST_DATA_ROW, sheet.max_row + 1)
            if sheet.cell(row, ORDER_COLUMN).value is not None
        }
        for row, link in links.items():
            sheet.cell(row, ORDER_COLUMN).hyperlink = link
        workbook.save(path)
    finally:
        workbook.close()
    return links


def make_fixture(tmp_path: Path, period: str = PERIOD) -> tuple[Path, Path, Path]:
    period_directory = tmp_path / period
    period_directory.mkdir(parents=True)
    target_directory = period_directory / pliki_taty.worker_settlements_name(period)
    source_path = period_directory / pliki_taty.collective_file_name(period)
    write_source(source_path, include_unmapped=False)
    config_path = write_worker_list(tmp_path / pliki_taty.WORKER_LIST_NAME)
    write_template(tmp_path / pliki_taty.WORKER_TEMPLATE_NAME)
    return source_path, target_directory, config_path


def make_preview_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    write_source(source_path, include_unmapped=True)
    return source_path, target_directory, config_path
