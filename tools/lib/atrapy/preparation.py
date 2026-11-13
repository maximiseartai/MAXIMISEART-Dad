"""Przygotowanie pliku zbiorczego: syntetyczne skoroszyty taty dla testów, narzędzi i skryptów skilli.

Rejestr zleceń, Wzorzec rozliczenia wewnętrznego i Wzorzec pliku zbiorczego są
budowane w katalogu tymczasowym. Nie zawierają prawdziwych danych klientów.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from atrapy import pliki_taty
from atrapy.pliki_taty import (
    AMOUNT_COLUMN,
    COLLECTIVE_HEADERS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    INTERNAL_HEADERS,
    PASTE_SHIFT,
    QUANTITY_COLUMNS,
    REGISTER_NAME,
)
from atrapy.settlement import write_worker_list
from atrapy.workbooks import TEMPLATE_VIEW, View, active_worksheet, add_external_link_fixture, set_view

PERIOD = "08_14_09_2026"
INTERNAL_SETTLEMENT_NAME = pliki_taty.internal_settlement_name(PERIOD)
COLLECTIVE_FILE_NAME = pliki_taty.collective_file_name(PERIOD)

# Nowy Rejestr taty od B (``pliki_taty.REGISTER_HEADERS``): kolumny są przesunięte względem wzorców.
REGISTER_HEADERS: tuple[str, ...] = ("", *pliki_taty.REGISTER_HEADERS)
# Starsza kopia Rejestru: inna kolejność, stare zapisy nagłówków, bez AKCJE, ZWROT i UWAGI,
# za to z kolumną "STATUS APLIKACJI", która nie jest przenoszona.
OLD_REGISTER_HEADERS: tuple[str, ...] = (
    "nr zlecenia",
    "DATA GODZ. POCZ.",
    "WYKONAWCA",
    "MIASTO",
    "adres",
    "STATUS APLIKACJI",
    "UMOWA",
    "URZĄDZENIA",
    "CZYNNOŚCI",
    "SKUTECZNE",
    "CZYNNOŚCI ZREALIZOWANE",
    "NUMER UMOWY/ZLECENIA ORANGE",
)
# Nagłówki nowego Rejestru zapisane w starszej kopii inaczej.
OLD_REGISTER_SPELLINGS = {"ADRES": "adres", "NUMER ZL.": "nr zlecenia", "NUMER UMOWY": "NUMER UMOWY/ZLECENIA ORANGE"}
# Wartości kolumn, które ma tylko starsza kopia Rejestru.
OLD_REGISTER_ONLY_VALUES: dict[str, object] = {"STATUS APLIKACJI": "zamknięte"}
# Początki wartości kolumn nowego Rejestru, które nie trafiają do plików okresu.
NOT_TRANSFERRED_PREFIXES: dict[str, str] = {"AKCJE": "akcja SYN-", "ZWROT": "zwrot SYN-", "UWAGI": "uwaga SYN-"}
# Wiersze Wzorca pliku zbiorczego przygotowane zerami w N:AP.
COLLECTIVE_TEMPLATE_ZERO_ROWS = 6
# Formatowanie przygotowanych wierszy Wzorca pliku zbiorczego: A:K i kolumny ilości.
COLLECTIVE_TEMPLATE_DATA_FILL = PatternFill(fill_type="solid", fgColor="FFDDDDDD")
COLLECTIVE_TEMPLATE_QUANTITY_FILL = PatternFill(fill_type="solid", fgColor="FFCCE5FF")

RegisterRow = dict[str, object] | None
"""Wiersz Rejestru: wartości po nagłówkach Rejestru albo ``None`` dla całkowicie pustego wiersza."""

# Wygląd Rejestru: uporządkowane zlecenia taty (Calibri 8, mniejsza czcionka niż we wzorcach) i własny format daty.
REGISTER_FONT_NAME = "Calibri"
REGISTER_FONT_SIZE = 8
REGISTER_DATE_FORMAT = "dd.mm.yyyy hh:mm"
# Wygląd wierszy danych z wzorców.
TEMPLATE_FONT_NAME = "Calibri"
TEMPLATE_FONT_SIZE = 10
# Wzorzec ze stylem wiersza: kolumny mają większą czcionkę niż wiersze danych,
# a komórki danych nie mają własnego stylu. Excel daje wpisanemu tekstowi styl wiersza.
TEMPLATE_COLUMN_FONT_SIZE = 11
TEMPLATE_ROW_STYLED_ROWS = 40
# Szerokości kolumn wzorców: różne, a C i E bardzo wąskie, jak kolumny, których tata nie musi oglądać.
TEMPLATE_NARROW_COLUMN_WIDTHS = {3: 2.29, 5: 3.0}


def template_column_width(column: int) -> float:
    """Szerokość kolumny ``column`` (od 1) w obu syntetycznych Wzorcach."""

    return TEMPLATE_NARROW_COLUMN_WIDTHS.get(column, 9 + column)


@dataclass(frozen=True)
class Highlight:
    """Wyróżnienie komórki Rejestru, które ma przejść do obu plików okresu."""

    fill: str | None = None
    color: str | None = None
    bold: bool = False
    italic: bool = False


# Wyróżnienia domyślnego Rejestru po (wiersz Excela, nagłówek Rejestru).
# Wiersz 4: zlecenie 2, wiersz 9: zlecenie 4 (oba skuteczne).
DEFAULT_REGISTER_HIGHLIGHTS: dict[tuple[int, str], Highlight] = {
    (4, "AKCJE"): Highlight(fill="FF00B050", bold=True),
    (4, "ADRES"): Highlight(fill="FFFFFF00", color="FFC00000", bold=True),
    (9, "ADRES"): Highlight(fill="FF00B0F0"),
    (9, "WYKONAWCA"): Highlight(italic=True),
}


def register_order(
    number: int,
    started: datetime,
    *,
    successful: str = "tak",
    worker: str = "adrian.testowy",
) -> dict[str, object]:
    """Syntetyczne zlecenie nowego Rejestru z unikalnymi znacznikami treści ``SYN-…``."""

    return {
        "AKCJE": f"{NOT_TRANSFERRED_PREFIXES['AKCJE']}{number:03d}",
        "DATA GODZ. POCZ.": started,
        "MIASTO": "POZNAŃ",
        "ADRES": f"syntetyczny adres SYN-{number:03d}",
        "UMOWA": f"UM-SYN-{number:03d}",
        "URZĄDZENIA": "dekoder",
        "CZYNNOŚCI": "instalacja",
        "NUMER ZL.": f"ZL-SYN-{number:03d}",
        "WYKONAWCA": worker,
        "NUMER UMOWY": f"OR-SYN-{number:03d}",
        "SKUTECZNE": successful,
        "CZYNNOŚCI ZREALIZOWANE": "montaż",
        "ZWROT": f"{NOT_TRANSFERRED_PREFIXES['ZWROT']}{number:03d}",
        "UWAGI": f"{NOT_TRANSFERRED_PREFIXES['UWAGI']}{number:03d}",
    }


def in_old_layout(rows: list[RegisterRow]) -> list[RegisterRow]:
    """Te same zlecenia w układzie starszej kopii Rejestru: każdy wiersz ma dokładnie ``OLD_REGISTER_HEADERS``."""

    def old_row(row: Mapping[str, object]) -> dict[str, object]:
        values = {OLD_REGISTER_SPELLINGS.get(header, header): value for header, value in row.items()}
        values |= OLD_REGISTER_ONLY_VALUES
        return {header: values[header] for header in OLD_REGISTER_HEADERS}

    return [None if row is None else old_row(row) for row in rows]


def default_register_rows() -> list[RegisterRow]:
    """Rejestr z okresem 08_14_09_2026 pośród innych okresów, pustymi wierszami i spóźnionym zleceniem."""

    return [
        register_order(1, datetime(2026, 9, 7, 15, 0)),  # poprzedni okres (poniedziałek)
        None,
        register_order(2, datetime(2026, 9, 8, 0, 0), worker="adrian.testowy"),
        None,
        register_order(3, datetime(2026, 9, 9, 10, 30), successful="NIE", worker="dariusz.fikcyjny2"),
        None,
        None,
        register_order(4, datetime(2026, 9, 12, 12, 0), successful=" Tak ", worker="kamil.syntetyczny"),
        None,
        register_order(5, datetime(2026, 9, 15, 0, 0)),  # następny okres (wtorek 00:00)
        None,
        register_order(6, datetime(2026, 9, 14, 18, 30), successful="TAK", worker="dariusz.fikcyjny2"),
    ]


def write_register(
    path: Path,
    rows: list[RegisterRow] | None = None,
    *,
    headers: tuple[str, ...] = REGISTER_HEADERS,
) -> Path:
    """Zapisuje Rejestr zleceń: arkusz-wabik ``lista`` i arkusz danych ``ZLECENIA``."""

    workbook = Workbook()
    decoy = active_worksheet(workbook)
    decoy.title = "lista"
    decoy["A1"] = "WYKONAWCY"
    decoy["A2"] = "adrian.testowy"
    write_register_sheet(
        workbook.create_sheet("ZLECENIA"),
        rows if rows is not None else default_register_rows(),
        headers=headers,
        highlights=DEFAULT_REGISTER_HIGHLIGHTS if rows is None else {},
    )
    workbook.save(path)
    return path


def write_register_sheet(
    sheet: Worksheet,
    rows: list[RegisterRow],
    *,
    headers: tuple[str, ...] = REGISTER_HEADERS,
    highlights: Mapping[tuple[int, str], Highlight] | None = None,
) -> None:
    """Zapisuje arkusz Rejestru: nagłówki w wierszu 1, zlecenia od wiersza 2 (``None`` to pusty wiersz).

    Pusty nagłówek oznacza całkowicie pustą kolumnę.
    """

    if highlights is None:
        highlights = {}
    columns = [(column, header) for column, header in enumerate(headers, start=1) if header]
    for column, header in columns:
        sheet.cell(1, column).value = header
    for row_number, row in enumerate(rows, start=2):
        if row is None:
            continue
        for column, header in columns:
            if header in row:
                cell = sheet.cell(row_number, column)
                cell.value = row[header]  # type: ignore[assignment]  # syntetyczne zlecenia mają tekst i daty
                highlight = highlights.get((row_number, header), Highlight())
                cell.font = Font(
                    name=REGISTER_FONT_NAME,
                    size=REGISTER_FONT_SIZE,
                    color=highlight.color,
                    bold=highlight.bold,
                    italic=highlight.italic,
                )
                if highlight.fill is not None:
                    cell.fill = PatternFill(fill_type="solid", fgColor=highlight.fill)
                if header == "DATA GODZ. POCZ.":
                    cell.number_format = REGISTER_DATE_FORMAT


RAW_ORDER_FONT = Font(name="Roboto", size=4, bold=True)
"""Wygląd zlecenia wklejonego z aplikacji firmowej (Surowego zlecenia)."""


def paste_raw_orders(
    path: Path,
    orders: Sequence[Mapping[str, object]],
    *,
    gap: int = 2,
    first: int | None = None,
    in_place_from: str | None = None,
) -> int:
    """Wkleja ``orders`` do arkusza ``ZLECENIA`` jak z aplikacji, Roboto 4: od wiersza ``first``, a bez niego na dół,
    ``gap`` pustych wierszy niżej.

    Pierwszy wiersz jest przesunięty o dwie kolumny w lewo, więc wklejenie nie ma wartości ``AKCJE``, także w wierszu,
    który miał ją przed wklejeniem; ``in_place_from``: tata postawił go z powrotem na miejsce od kolumny z tym
    nagłówkiem w prawo. Zwraca numer pierwszego wklejonego wiersza.
    """

    workbook = load_workbook(path)
    try:
        sheet = workbook["ZLECENIA"]
        columns = {cell.value: cell.column for cell in sheet[1] if cell.value}
        if first is None:
            first = sheet.max_row + gap + 1
        in_place = sheet.max_column + 1 if in_place_from is None else columns[in_place_from]
        for index, order in enumerate(orders):
            sheet.cell(first + index, columns["AKCJE"]).value = None
            for header, value in order.items():
                if header != "AKCJE":
                    shift = PASTE_SHIFT if index == 0 and columns[header] < in_place else 0
                    cell = sheet.cell(first + index, columns[header] - shift)
                    cell.value = value  # type: ignore[assignment]  # syntetyczne zlecenia mają tekst i daty
                    cell.font = RAW_ORDER_FONT
        workbook.save(path)
    finally:
        workbook.close()
    return first


def type_into_register(path: Path, row: int, header: str, value: object) -> None:
    """Tata wpisuje ``value`` w wiersz ``row`` arkusza ``ZLECENIA`` pod nagłówkiem ``header`` czcionką Rejestru."""

    workbook = load_workbook(path)
    try:
        sheet = workbook["ZLECENIA"]
        [column] = [cell.column for cell in sheet[1] if cell.value == header]
        cell = sheet.cell(row, column)
        cell.value = value  # type: ignore[assignment]  # syntetyczne zlecenia mają tekst
        cell.font = Font(name=REGISTER_FONT_NAME, size=REGISTER_FONT_SIZE)
        workbook.save(path)
    finally:
        workbook.close()


def link_register_order_numbers(path: Path, address: str) -> dict[int, str]:
    """Hiperłącze w ``NUMER ZL.`` każdego zlecenia arkusza ``ZLECENIA``, jak do zlecenia w aplikacji firmowej.

    Adres to ``address`` z numerem wiersza Rejestru na końcu; zwraca numer wiersza → adres.
    """

    workbook = load_workbook(path)
    try:
        sheet = workbook["ZLECENIA"]
        [column] = [cell.column for cell in sheet[1] if cell.value in ("NUMER ZL.", "nr zlecenia")]
        links = {
            row: f"{address}{row}" for row in range(2, sheet.max_row + 1) if sheet.cell(row, column).value is not None
        }
        for row, link in links.items():
            sheet.cell(row, column).hyperlink = link
        workbook.save(path)
    finally:
        workbook.close()
    return links


def _apply_template_layout(sheet: Worksheet, header_row: int, columns: int, *, row_style: bool, view: View) -> None:
    """Autofiltr wzorca celowo obejmuje zły zakres, który Przygotowanie ma zignorować."""

    column_font_size = TEMPLATE_COLUMN_FONT_SIZE if row_style else TEMPLATE_FONT_SIZE
    for column in range(1, columns + 1):
        dimension = sheet.column_dimensions[get_column_letter(column)]
        dimension.width = template_column_width(column)
        dimension.font = Font(name=TEMPLATE_FONT_NAME, size=column_font_size)
        sheet.cell(header_row, column).font = Font(name=TEMPLATE_FONT_NAME, size=TEMPLATE_FONT_SIZE, bold=True)
    sheet.row_dimensions[header_row].height = 30
    sheet.row_dimensions[header_row + 1].height = 14
    sheet.freeze_panes = f"A{header_row + 1}"
    set_view(sheet, view)
    sheet.auto_filter.ref = f"B{header_row}:C{header_row + 40}"
    if row_style:
        for row in range(header_row + 1, header_row + 1 + TEMPLATE_ROW_STYLED_ROWS):
            sheet.row_dimensions[row].font = Font(name=TEMPLATE_FONT_NAME, size=TEMPLATE_FONT_SIZE)


def write_internal_template(
    path: Path, *, row_style: bool = False, view: View = TEMPLATE_VIEW, headers: tuple[str, ...] = INTERNAL_HEADERS
) -> Path:
    """Wzorzec rozliczenia wewnętrznego: nagłówki w wierszu 1 (domyślnie w kolejności taty), bez zleceń."""

    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Arkusz1"
    for column, header in enumerate(headers, start=1):
        sheet.cell(1, column).value = header
    _apply_template_layout(sheet, 1, len(headers), row_style=row_style, view=view)
    workbook.save(path)
    return path


def write_collective_template(path: Path, *, row_style: bool = False, view: View = TEMPLATE_VIEW) -> Path:
    """Wzorzec pliku zbiorczego: stawki w wierszach 1–16, nagłówki w 17, zera i formuły, link zewnętrzny."""

    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet["A1"] = "STAWKI"
    sheet["N1"] = 17.5
    sheet["O1"] = 30
    sheet["N16"] = "=SUM(N18:N40)"
    sheet.cell(HEADER_ROW, 1).fill = PatternFill(fill_type="solid", fgColor="00AA55")
    for column, header in enumerate(COLLECTIVE_HEADERS, start=1):
        sheet.cell(HEADER_ROW, column).value = header
    sheet.cell(HEADER_ROW, QUANTITY_COLUMNS.start).value = "instalacja"
    sheet.cell(HEADER_ROW, QUANTITY_COLUMNS[-1]).value = "demontaż"
    _apply_template_layout(sheet, HEADER_ROW, len(COLLECTIVE_HEADERS), row_style=row_style, view=view)
    styled_data_columns = 0 if row_style else len(COLLECTIVE_HEADERS)
    for row in range(FIRST_DATA_ROW, FIRST_DATA_ROW + COLLECTIVE_TEMPLATE_ZERO_ROWS):
        for column in range(1, styled_data_columns + 1):  # A:K, przygotowane we wzorcu
            cell = sheet.cell(row, column)
            cell.font = Font(name=TEMPLATE_FONT_NAME, size=TEMPLATE_FONT_SIZE)
            cell.fill = COLLECTIVE_TEMPLATE_DATA_FILL
        for column in QUANTITY_COLUMNS:
            cell = sheet.cell(row, column)
            cell.value = 0
            cell.fill = COLLECTIVE_TEMPLATE_QUANTITY_FILL
            cell.number_format = "0"
        sheet.cell(row, AMOUNT_COLUMN).value = f"=N{row}*$N$1"
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = 17.5
    workbook.save(path)
    add_external_link_fixture(path)
    return path


@dataclass(frozen=True)
class PreparationFixture:
    """Ścieżki jednego syntetycznego uruchomienia Przygotowania pliku zbiorczego."""

    register_path: Path
    periods_directory: Path
    config_path: Path
    internal_template_path: Path
    collective_template_path: Path
    # Folder ``INEA`` miesiąca z Folderem okresu w układzie folderów taty; w płaskim sam folder okresów.
    month_periods_folder: Path | None = None

    @property
    def period_directory(self) -> Path:
        return (self.month_periods_folder or self.periods_directory) / PERIOD

    @property
    def internal_settlement_path(self) -> Path:
        return self.period_directory / INTERNAL_SETTLEMENT_NAME

    @property
    def collective_file_path(self) -> Path:
        return self.period_directory / COLLECTIVE_FILE_NAME


def make_preparation_fixture(tmp_path: Path, rows: list[RegisterRow] | None = None) -> PreparationFixture:
    """Rejestr, folder okresów ``INEA``, konfiguracja wykonawców i oba wzorce w ``tmp_path``."""

    config_directory = tmp_path / "config"
    config_directory.mkdir()
    periods_directory = tmp_path / "INEA"
    periods_directory.mkdir()
    return PreparationFixture(
        register_path=write_register(tmp_path / REGISTER_NAME, rows),
        periods_directory=periods_directory,
        config_path=write_worker_list(config_directory / pliki_taty.WORKER_LIST_NAME),
        internal_template_path=write_internal_template(
            config_directory / pliki_taty.INTERNAL_TEMPLATE_NAME
        ),
        collective_template_path=write_collective_template(
            config_directory / pliki_taty.COLLECTIVE_TEMPLATE_NAME
        ),
    )


def month_periods_folder(periods_directory: Path, month: str) -> Path:
    """Folder ``INEA`` miesiąca w układzie folderów taty, np. ``Rozliczenia 2026\\09_Wrzesień_2026\\INEA``."""

    folder = periods_directory / "Rozliczenia 2026" / month / "INEA"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def make_dad_layout_fixture(tmp_path: Path) -> PreparationFixture:
    """Jak ``make_preparation_fixture``, ale folder okresów ``Załączniki`` ma układ folderów taty.

    Folder okresu 08_14_09_2026 leży w ``Rozliczenia 2026\\09_Wrzesień_2026\\INEA``, obok
    folderu sierpnia i folderów, które nie są Folderami okresu.
    """

    fixture = make_preparation_fixture(tmp_path)
    periods_directory = tmp_path / "Załączniki"
    september = month_periods_folder(periods_directory, "09_Wrzesień_2026")
    (september / PERIOD).mkdir()
    (september / "Podpisane").mkdir()
    (month_periods_folder(periods_directory, "08_Sierpień_2026") / "25_31_08_2026").mkdir()
    (periods_directory / "Rozliczenia 2026" / "Nowe rozliczenia wzór od 01_2026").mkdir()
    return replace(fixture, periods_directory=periods_directory, month_periods_folder=september)


def collective_row(number: int, started: datetime, successful: str, worker: str) -> tuple[object, ...]:
    return (
        "POZNAŃ",
        f"syntetyczny adres SYN-{number:03d}",
        f"UM-SYN-{number:03d}",
        "dekoder",
        "instalacja",
        f"ZL-SYN-{number:03d}",
        started,
        worker,
        f"OR-SYN-{number:03d}",
        successful,
        "montaż",
    )


def cell_values(path: Path, *, min_row: int, max_row: int, min_col: int, max_col: int) -> list[tuple[object, ...]]:
    workbook = load_workbook(path)
    try:
        sheet = active_worksheet(workbook)
        return list(
            sheet.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True)
        )
    finally:
        workbook.close()


def incomplete_period_rows() -> list[RegisterRow]:
    """Okres 08_14_09_2026, w którym ostatnie zlecenie jest z soboty."""

    return [
        register_order(1, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(2, datetime(2026, 9, 9, 10, 0), successful="nie"),
        register_order(3, datetime(2026, 9, 12, 12, 0)),
    ]


def incomplete_period_fixture(tmp_path: Path) -> PreparationFixture:
    return make_preparation_fixture(tmp_path, incomplete_period_rows())

