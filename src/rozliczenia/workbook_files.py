"""Skoroszyty na dysku: otwarcie z jedną klasyfikacją uszkodzeń, sprawdzenie układu arkusza i odczyt Wierszy danych.

Każde otwarcie skoroszytu w obu procesach przechodzi przez ten moduł: Plik zbiorczy (``read_data_rows``) daje Wiersze
danych z komórkami po kolumnie (``DataRow``), a Rejestr zleceń (``register_file``) wiersze z komórkami pod nagłówkiem
docelowym (``RegisterRow``). Wzorce czyta przez ``open_workbook`` plik z Wzorca (``template_file``). Otwarcie
sprawdza dostępność i klasyfikuje każde uszkodzenie, a problem zgłasza jako ``WorkbookError`` z powodem, przy złym
układzie z jego miejscem. Moduł nie zna Komunikatów: proces tłumaczy powód na Komunikat ze swojego katalogu.

Układ arkusza Pliku zbiorczego bierze z ``collective_layout``. Wycena w efenix czyta ``Kwota`` w AU tak, jak policzył ją
Excel (``read_computed_rows``).
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import IO, TYPE_CHECKING, Final, NamedTuple, Never, TypeAlias, TypeVar, cast
from xml.etree.ElementTree import ParseError
from xml.parsers.expat import ExpatError

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from . import client_data
from .collective_layout import (
    ADDRESS_COLUMN,
    AMOUNT_COLUMN,
    DATA_ROW_COLUMNS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    INPUT_COLUMNS,
    LOOK_COLUMNS,
    ORANGE_COLUMN,
    QUANTITY_COLUMNS,
    WORKER_COLUMN,
)
from .file_state import file_state
from .highlights import Highlights, LookReader
from .hyperlinks import Hyperlink, read_sheet_hyperlinks
from .row_look import GENERAL
from .workbook_parts import rows_with_input
from .text import normalize_text

if TYPE_CHECKING:
    from .dad_files import DadFiles, ReadFile, WitnessedSheet


# Błędy openpyxl przy pliku, który nie jest poprawnym skoroszytem .xlsx: przy otwieraniu, a w trybie
# tylko do odczytu także przy czytaniu wierszy, bo arkusz jest wtedy parsowany leniwie. ``IndexError``:
# komórka ze stylem w skoroszycie bez ``xl/styles.xml``. ``ExpatError``: zepsuty XML arkusza przy odczycie
# Wierszy danych (``workbook_parts.rows_with_input``).
_UNREADABLE_WORKBOOK_ERRORS = (
    OSError,
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    IndexError,
    ValueError,
    zlib.error,
    ParseError,
    ExpatError,
)

_WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xltx", ".xltm")

FORBIDDEN_POSITIONS: Final = (
    (client_data.ForbiddenColumn.ADDRESS, ADDRESS_COLUMN),
    (client_data.ForbiddenColumn.ORANGE, ORANGE_COLUMN),
)
"""Kolumny reguły danych, które układ Wzorca stawia na stałym miejscu, bez względu na nagłówek."""


_ExcelCellValue = (
    bool
    | int
    | float
    | Decimal
    | str
    | CellRichText
    | date
    | datetime
    | time
    | timedelta
    | DataTableFormula
    | ArrayFormula
    | bytes
    | None
)
ExcelRow = tuple[_ExcelCellValue, ...]


class Problem(Enum):
    """Powód, dla którego skoroszytu nie da się użyć."""

    MISSING = "brak pliku"
    OPEN_IN_EXCEL = "otwarty w Excelu"
    INACCESSIBLE = "niedostępny"
    """Plik jest cały, ale system nie oddał jego bajtów, np. zajęty przez inny program albo OneDrive bez sieci."""
    UNREADABLE = "nieczytelny"
    LAYOUT = "zły układ"
    HAS_DATA = "zawiera dane"
    """Wzorzec rozliczenia pracownika ma już wartości w Wierszach danych."""


@dataclass(frozen=True)
class MissingHeader:
    """Nagłówek ``header`` nie stoi na swoim miejscu w wierszu ``row`` arkusza ``sheet``.

    ``found_in``: litera kolumny A:K, w której stoi WYKONAWCA zamiast w H; ``None``: nagłówka w wierszu nie ma.
    """

    sheet: str
    row: int
    header: str
    found_in: str | None = None


@dataclass(frozen=True)
class MergedCells:
    """Komórki ``cells`` arkusza ``sheet``, do których trafiłyby Wiersze danych, są scalone."""

    sheet: str
    cells: str


LayoutFault = MissingHeader | MergedCells


class WorkbookError(Exception):
    """Skoroszytu nie da się użyć; ``problem`` mówi dlaczego, a przy złym układzie (i tylko wtedy) ``fault`` mówi gdzie."""

    def __init__(self, path: Path, problem: Problem, fault: LayoutFault | None = None) -> None:
        super().__init__(f"{problem.value}: {path.name}")
        self.path = path
        self.problem = problem
        self.fault = fault


@dataclass(frozen=True)
class HeaderCell:
    """Etykieta komórki nagłówka do treści Komunikatów: ``str()`` daje np. ``H17``."""

    column: str
    row: int

    def __str__(self) -> str:
        return f"{self.column}{self.row}"


WORKER_HEADER = HeaderCell(get_column_letter(WORKER_COLUMN), HEADER_ROW)
_WORKER_LABEL = "WYKONAWCA"


_NO_QUANTITIES: MappingProxyType[str, Never] = MappingProxyType({})


class DataCell(NamedTuple):
    """Komórka Wiersza danych: wartość, jej Wyróżnienia, format liczby i Hiperłącze (tylko przy wartości)."""

    value: _ExcelCellValue
    highlights: Highlights
    number_format: str
    hyperlink: Hyperlink | None


@dataclass(frozen=True)
class DataRow:
    """Wiersz danych Pliku zbiorczego: komórki kolumn A:AT po kolei od A.

    ``number`` to numer wiersza w Pliku zbiorczym. Przebieg rozliczeń wpisuje każdą komórkę do tej samej kolumny
    Rozliczenia pracownika, a Ilości tylko dla INEA jako puste (``inea_only_quantities``). Format liczby z pliku mają
    tylko kolumny wyglądu A:L, a dalsze komórki ogólny: odczyt formatu, którego plik nie użyje, mógłby zatrzymać
    rozliczenie na komórce ze stylem bez definicji formatu.
    """

    number: int
    cells: tuple[DataCell, ...]

    def value(self, column: str) -> _ExcelCellValue:
        """Wartość komórki w kolumnie ``column`` (litera, np. ``N``)."""

        return self.cells[column_index_from_string(column) - 1].value

    @property
    def worker(self) -> _ExcelCellValue:
        """Surowa wartość WYKONAWCA z kolumny H Pliku zbiorczego."""

        return self.value(WORKER_HEADER.column)


@dataclass(frozen=True)
class RegisterRow:
    """Wiersz Rejestru zleceń, który staje się Wierszem danych obu plików okresu: komórki pod nagłówkiem docelowym.

    ``number`` to numer wiersza w Rejestrze zleceń; plik z Wzorca wpisuje komórkę do kolumny pod jej nagłówkiem.
    """

    number: int
    cells: Mapping[str, DataCell]
    quantities: Mapping[str, int] = field(default_factory=lambda: _NO_QUANTITIES)
    """Ilości usług Wiersza danych Pliku zbiorczego z Przygotowania: litera kolumny N:AP → liczba różna od zera.

    Trafiają do komórki Wzorca z jej wyglądem, bez Wyróżnień; reszta kolumn ilości zostaje jak we Wzorcu.
    """


def excel_lock_file(path: Path) -> Path:
    """Plik blokady ``~$…``, który desktopowy Excel kładzie obok otwartego skoroszytu ``path``."""

    return path.with_name(f"~${path.name}")


def is_open_in_excel(path: Path) -> bool:
    """Rozpoznaje skoroszyt otwarty w desktopowym Excelu po pliku blokady ``~$…``.

    W folderze bez dostępu blokady nie widać; niedostępny skoroszyt zgłasza jego odczyt (``ensure_available``).
    """

    return file_state(excel_lock_file(path)) == "file"


def ensure_available(path: Path, *, despite_excel_lock: bool = False) -> None:
    """Skoroszyt jest na dysku i nie jest otwarty w Excelu; inaczej ``WorkbookError``.

    Folder, którego nie da się odczytać (np. brak dostępu), czyni skoroszyt niedostępnym, a nie uszkodzonym.
    ``despite_excel_lock`` pozwala czytać skoroszyt, który trzyma Excel: jego ostatnią zapisaną wersję (ADR 0016).
    """

    match file_state(path):
        case "inaccessible":
            raise WorkbookError(path, Problem.INACCESSIBLE)
        case "missing":
            raise WorkbookError(path, Problem.MISSING)
        case "file":
            pass
    if is_open_in_excel(path) and not despite_excel_lock:
        raise WorkbookError(path, Problem.OPEN_IN_EXCEL)


_T = TypeVar("_T")


@contextmanager
def unreadable_as_error(path: Path) -> Iterator[None]:
    """Uszkodzenie skoroszytu zgłoszone przez openpyxl staje się ``WorkbookError``; inne błędy przechodzą."""

    try:
        yield
    except _UNREADABLE_WORKBOOK_ERRORS as exc:
        raise WorkbookError(path, Problem.UNREADABLE) from exc


def file_bytes(path: Path) -> bytes:
    """Bajty skoroszytu z dysku; błąd systemu plików to ``Problem.INACCESSIBLE``, nie uszkodzenie. Jedyny odczyt bajtów
    skoroszytu z dysku w ``src`` (``tests/test_jeden_odczyt_skoroszytu.py``)."""

    try:
        return path.read_bytes()
    except OSError as exc:
        raise WorkbookError(path, Problem.INACCESSIBLE) from exc


ByteSource: TypeAlias = Callable[[Path], bytes]
"""Źródło bajtów skoroszytu (``dad_files.DadFiles.source``): produkcyjne to ``file_bytes``, a test podstawia źródło,
które się psuje, liczy odczyty albo zapisuje plik zaraz po odczycie."""


def classified(path: Path, items: Iterator[_T]) -> Iterator[_T]:
    """Elementy leniwego odczytu openpyxl; klasyfikowane jest tylko pobranie elementu."""

    while True:
        with unreadable_as_error(path):
            try:
                item = next(items)
            except StopIteration:
                return
        yield item


def _open(path: Path, source: IO[bytes], *, read_only: bool, computed: bool = False) -> Workbook:
    """Skoroszyt ``path`` otwarty przez openpyxl z jego bajtów (``file_bytes``) z klasyfikacją uszkodzeń.

    ``computed`` (tylko do odczytu): komórka z formułą ma wartość, którą Excel policzył przy ostatnim zapisie, a bez niej
    ``None``.
    """

    with unreadable_as_error(path):
        if read_only:
            workbook = load_workbook(source, read_only=True, data_only=computed)
        else:
            workbook = load_workbook(source, read_only=False, data_only=False, keep_links=True)
    if not isinstance(workbook.active, (Worksheet, ReadOnlyWorksheet)):
        workbook.close()
        raise WorkbookError(path, Problem.UNREADABLE)
    return workbook


def _is_worker_header(value: object) -> bool:
    return str(value or "").casefold().split() == ["wykonawca"]


def check_worker_header(path: Path, sheet: str, header: Sequence[object]) -> None:
    """Jedno sprawdzenie nagłówka WYKONAWCA w H17 (bez względu na wielkość liter i spacje) dla wartości A17:K17."""

    columns = [column for column, value in enumerate(header[: INPUT_COLUMNS[-1]], start=1) if _is_worker_header(value)]
    if WORKER_COLUMN not in columns:
        found_in = get_column_letter(columns[0]) if columns else None
        raise WorkbookError(path, Problem.LAYOUT, MissingHeader(sheet, HEADER_ROW, _WORKER_LABEL, found_in))


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def cell_datetime(value: object) -> datetime | None:
    """Data i godzina z komórki ``DATA``; data bez godziny to północ, inna treść to ``None``."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def header_columns(values: Sequence[object]) -> dict[str, int]:
    return {normalize_text(value): column for column, value in enumerate(values, start=1) if not is_blank(value)}


def _forbidden_columns(header: Sequence[object]) -> tuple[tuple[client_data.ForbiddenColumn, int], ...]:
    """Zakazane kolumny Wiersza danych Pliku zbiorczego (reguła danych, ADR 0025) z ich numerem od 1, z nagłówków
    A17:K17 ``header``: ``ADRES`` (B) i ``NUMER UMOWY/ZLECENIA ORANGE`` (I) z układu Wzorca bez względu na nagłówek, więc
    adres pod innym nagłówkiem też nie wychodzi, i każda kolumna A:K z nagłówkiem zakazanej kolumny."""

    by_header = client_data.forbidden_columns(header_columns(header[: INPUT_COLUMNS[-1]]))
    return tuple(dict.fromkeys((*FORBIDDEN_POSITIONS, *by_header)))


@dataclass(frozen=True)
class _Collective:
    """Arkusz Pliku zbiorczego z jednego odczytu po sprawdzeniu układu (``_collective_sheet``)."""

    file: ReadFile
    title: str
    header: ExcelRow
    """Wartości A17:AP17: nagłówki A:K i nazwy pozycji cennika N:AP."""
    content: bytes = field(repr=False)
    """Bajty, które czyta openpyxl: plik bez wierszy, które nie mogą mieć wartości w A:K (``rows_with_input``)."""
    rows: Iterator[tuple[int, tuple[object, ...], ExcelRow]]
    """Wiersze danych od 18 w kolejności z pliku: numer, komórki i wartości do ``last_column``; każdy już u świadka."""


@contextmanager
def _collective_sheet(
    path: Path, files: DadFiles, *, last_column: int, computed: bool = False, despite_excel_lock: bool = False
) -> Iterator[_Collective]:
    """Jedyny ciąg kroków odczytu Pliku zbiorczego, wspólny dla obu obiektywów (wyglądu i wartości policzonych).

    ``computed``: wartości policzone przez Excel. Arkusz wchodzi do Kopii wejścia przed sprawdzeniem nagłówka, więc Logi
    Uruchomienia zatrzymanego na złym układzie mają odcisk pliku i jego nagłówek. Każdy Wiersz danych przechodzi przez
    świadka (pamięć reguły danych i Kopia), zanim dostanie go obiektyw.

    openpyxl czyta tylko wiersze, które mogą mieć wartości w A:K (``workbook_parts.rows_with_input``), a nie każdy z
    ~10 tys. sformatowanych wierszy Pliku zbiorczego; wartości i klasyfikacja uszkodzeń są takie jak przy odczycie
    całego arkusza.
    """

    file = files.read(path, despite_excel_lock=despite_excel_lock)
    with unreadable_as_error(path):
        content = rows_with_input(file.content, INPUT_COLUMNS[-1])
    workbook = _open(path, BytesIO(content), read_only=True, computed=computed)
    try:
        sheet = cast(Worksheet, workbook.active)  # tylko do odczytu: ReadOnlyWorksheet
        header = next(
            classified(
                path,
                sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, max_col=QUANTITY_COLUMNS[-1], values_only=True),
            ),
            (),
        )
        witness = file.sheet(sheet.title, HEADER_ROW, header, _forbidden_columns(header))
        check_worker_header(path, sheet.title, header)
        yield _Collective(file, sheet.title, header, content, _data_rows(path, sheet, witness, last_column))
    finally:
        workbook.close()


def _data_rows(
    path: Path, sheet: Worksheet, witness: WitnessedSheet, last_column: int
) -> Iterator[tuple[int, tuple[object, ...], ExcelRow]]:
    for number, cells in enumerate(
        classified(path, sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=last_column)), start=FIRST_DATA_ROW
    ):
        values = tuple(cell.value for cell in cells)
        if all(value is None for value in values[: INPUT_COLUMNS[-1]]):
            continue
        witness.row(number, values)
        yield number, cells, values


@dataclass(frozen=True)
class DataRows:
    """Wiersze danych Pliku zbiorczego i nagłówki A17:K17 z tego samego odczytu.

    ``header``: znormalizowany nagłówek (``header_columns``) → kolumna od 1. Przygotowanie zapisuje kolumny A:K pod
    nagłówkami Wzorca, więc odczyt po nagłówku jest lustrem zapisu.
    """

    header: Mapping[str, int]
    rows: list[DataRow]
    price_list: Mapping[str, str]
    """Litera kolumny N:AP → tekst jej komórki w wierszu 17: nazwa pozycji cennika, którą Przygotowanie kopiuje z Wzorca;
    pusta komórka to ``""``."""


def read_data_rows(path: Path, files: DadFiles, *, despite_excel_lock: bool = False) -> DataRows:
    """Wiersze danych Pliku zbiorczego z Wyróżnieniami i Hiperłączami komórek A:AT w kolejności z pliku; plik jest tylko
    czytany.

    Obiektyw wyglądu na potoku ``_collective_sheet``: wiersz bez wartości w A:K nie jest Wierszem danych i jest
    pomijany, a brak nagłówka WYKONAWCA w H17 to ``WorkbookError`` ze złym układem. Plik otwarty w Excelu to
    ``WorkbookError``, chyba że wywołujący jawnie pozwala go czytać (``despite_excel_lock``, ADR 0016). Komórki
    zakazanych kolumn (``_forbidden_columns``) zna pamięć reguły danych (ADR 0025), a bajty pliku, nagłówki A17:AP17 i
    wartości A:AT bez tych kolumn Kopia wejścia Uruchomienia.
    """

    with _collective_sheet(path, files, last_column=DATA_ROW_COLUMNS[-1], despite_excel_lock=despite_excel_lock) as sheet:
        with unreadable_as_error(path):
            links = read_sheet_hyperlinks(sheet.content, sheet.title)
        rows: list[DataRow] = []
        highlights = LookReader()
        for number, cells, values in sheet.rows:
            row_links = links.row(number, values)
            with unreadable_as_error(path):
                rows.append(
                    DataRow(
                        number,
                        tuple(
                            DataCell(
                                values[column - 1],
                                highlights.of(cell),
                                (getattr(cell, "number_format", None) or GENERAL) if column in LOOK_COLUMNS else GENERAL,
                                row_links.get(column),
                            )
                            for column, cell in enumerate(cells, start=1)
                        ),
                    )
                )
    names = {
        get_column_letter(column): "" if is_blank(name) else " ".join(str(name).split())
        for column, name in enumerate(sheet.header[QUANTITY_COLUMNS[0] - 1 :], start=QUANTITY_COLUMNS[0])
    }
    return DataRows(header_columns(sheet.header[: INPUT_COLUMNS[-1]]), rows, names)


@dataclass(frozen=True)
class ComputedRow:
    """Wiersz danych Pliku zbiorczego z wartościami komórek A:AU tak, jak Excel je policzył przy ostatnim zapisie.

    ``number`` to numer wiersza w Pliku zbiorczym; komórka z formułą, której Excel nie policzył, ma ``None``.
    """

    number: int
    values: ExcelRow

    def value(self, column: str) -> _ExcelCellValue:
        """Wartość komórki w kolumnie ``column`` (litera, np. ``AU``)."""

        index = column_index_from_string(column) - 1
        return self.values[index] if index < len(self.values) else None


@dataclass(frozen=True)
class ComputedRows:
    """Wiersze danych Pliku zbiorczego z wartościami policzonymi przez Excel i nagłówki A17:K17 z tego samego odczytu.

    ``header``: znormalizowany nagłówek (``header_columns``) → kolumna od 1. ``content``: bajty pliku, z których pochodzą
    wiersze.
    """

    header: Mapping[str, int]
    rows: list[ComputedRow]
    content: bytes


def read_computed_rows(path: Path, files: DadFiles) -> ComputedRows:
    """Wiersze danych Pliku zbiorczego (A:AU) z wartościami, które policzył Excel, w kolejności z pliku; plik jest tylko
    czytany.

    Obiektyw wartości na tym samym potoku co ``read_data_rows`` (``_collective_sheet``): te same Wiersze danych, to samo
    Zatrzymanie na złym układzie i ta sama Kopia wejścia, tylko z wartościami A:AU. Plik otwarty w Excelu to
    ``WorkbookError``.
    """

    with _collective_sheet(path, files, last_column=AMOUNT_COLUMN, computed=True) as sheet:
        rows = [ComputedRow(number, values) for number, _, values in sheet.rows]
    return ComputedRows(header_columns(sheet.header[: INPUT_COLUMNS[-1]]), rows, sheet.file.content)


def workbook_content(path: Path) -> bytes:
    """Bajty skoroszytu, który jest na dysku i nie jest otwarty w Excelu; inaczej ``WorkbookError``."""

    ensure_available(path)
    return file_bytes(path)


def template_content(path: Path) -> bytes:
    """Bajty Wzorca jak ``workbook_content``, a plik bez rozszerzenia skoroszytu, który otwiera openpyxl, jest nieczytelny."""

    ensure_available(path)
    if path.suffix.lower() not in _WORKBOOK_SUFFIXES:
        raise WorkbookError(path, Problem.UNREADABLE)
    return file_bytes(path)


@contextmanager
def open_workbook(path: Path, content: bytes, *, read_only: bool) -> Iterator[Workbook]:
    """Skoroszyt ``path`` z jego bajtów (``workbook_content``) otwarty przez openpyxl z klasyfikacją uszkodzeń.

    Bez ``read_only`` z odwołaniami zewnętrznymi, do zapisu. Zamykany przy wyjściu z bloku.
    """

    workbook = _open(path, BytesIO(content), read_only=read_only)
    try:
        yield workbook
    finally:
        workbook.close()
