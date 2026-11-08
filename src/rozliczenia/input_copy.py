"""Kopia wejścia (#841): Wiersze danych, które Uruchomienie procesu przeczytało z plików taty, i odcisk każdego pliku.

Uruchomienie z Centrum ma swoją Kopię wejścia (``InputCopy``) w uchwycie plików taty (``dad_files.DadFiles``), a
czytnik, który czyta dla niego plik taty, oddaje jej przez ten uchwyt bajty, z których czytał plik, zakazane kolumny
każdego arkusza i każdy przeczytany wiersz z jego położeniami (``raw_orders.RowPositions``): Rejestr zleceń w
Przygotowaniu pliku zbiorczego (``register_file.OrderSheets.period_rows``), Plik zbiorczy w Przebiegu rozliczeń
(``workbook_files.read_data_rows``), w Wycenie w efenix (``workbook_files.read_computed_rows``) i INTERMAX w
Uporządkowaniu INTERMAX (``register_file.PasteArea.copy_paste``, #842). Zakazane kolumny to te, których komórki ten sam czytnik
oddaje pamięci reguły danych (``client_data.ForbiddenValues``). Proces bez Centrum (Skrypt dla maszyn) Kopii nie ma, bo
nie ma Logów.

W trakcie odczytu Kopia trzyma tylko odwołania do bajtów i wartości, które czytnik i tak ma, i chwilę zmiany pliku,
którą uchwyt bierze przed odczytem bajtów (``dad_files.DadFiles.read``). Plik po regule danych (``files``) powstaje po
końcu procesu, zanim karta pokaże wynik: odcisk (rozmiar, chwila zmiany i skrót SHA-256 przeczytanych bajtów) i arkusze
z kolumnami po nagłówku i wierszami po numerze, bez zakazanych kolumn i bez pustych komórek. Komórki wiersza liczy jedna
reguła (``SheetCopy.row``). Wolny tekst i wartości zakazanych kolumn w innych komórkach, także liczby, maskuje
strażnik Logów (``run_logs_guard.guard_logs``), jak w każdym innym polu Logów.

Kopia niesie wartości komórek, bo na nich proces podejmuje decyzje: wynik, Komunikaty i ślad. Wygląd komórek
(Wyróżnienia, format liczby, Hiperłącza) proces tylko przenosi do plików, które tworzy, więc go nie ma.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import hashlib
from pathlib import Path
from typing import Literal

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from .raw_orders import UNDER_HEADER, RowPositions

TypedKind = Literal["datetime", "time", "timedelta", "other"]


@dataclass(frozen=True)
class Typed:
    """Wartość komórki, której JSON nie odróżnia od tekstu: ``kind`` i jej zapis (ISO 8601 albo sekundy); ``other``:
    wartość, której Kopia nie zapisuje, z nazwą jej typu."""

    kind: TypedKind
    text: str


CellValue = bool | int | float | str | Typed
"""Wartość niepustej komórki w Kopii wejścia."""


@dataclass(frozen=True)
class Fingerprint:
    """Odcisk przeczytanego pliku: ``size`` i ``sha256`` z przeczytanych bajtów, ``modified_at`` z pliku tuż przed
    odczytem (UTC; ``None``, gdy system jej nie oddał)."""

    size: int
    modified_at: datetime | None
    sha256: str


@dataclass(frozen=True)
class CopiedRow:
    """Przeczytany wiersz: numer w arkuszu i niepuste komórki po literze kolumny."""

    number: int
    cells: Mapping[str, CellValue]


@dataclass(frozen=True)
class CopiedSheet:
    """Przeczytany arkusz: wiersz nagłówka, nagłówki po literze kolumny, wiersze i puste wiersze, które proces liczy.

    ``shifted_row``: wiersz, którego komórki czytnik czyta o ``raw_orders.SHIFT`` kolumn na lewo od swojego nagłówka
    (przesunięty pierwszy wiersz wklejenia INTERMAX), a w Kopii stoją pod nim; ``None``: bez takiego wiersza.
    ``uncertain_rows``: wiersze wklejenia INTERMAX w obu położeniach (``raw_orders.RowPositions.uncertain``), które mają
    w Kopii tylko komórki dozwolone przy każdym ich możliwym przesunięciu i datę z godziną spod ``DATA GODZ. POCZ.``, więc
    brak komórki nie znaczy w nich pustej. ``last_ordered_row`` i ``yellow_row``: ostatni uporządkowany i
    żółty wiersz nad wklejeniem INTERMAX (``raw_orders.above_paste``), sam numer, bez treści; ``None``: bez takiego
    wiersza i arkusze innych plików. ``traced_rows``: wiersze ze śladem przesunięcia, które nie są pierwszym wierszem
    bloku wklejenia: łamią fakt domeny, że przesunięty przychodzi tylko pierwszy wklejony wiersz (ADR 0025).
    """

    name: str
    header_row: int
    columns: Mapping[str, str]
    rows: tuple[CopiedRow, ...]
    empty_rows: tuple[int, ...]
    shifted_row: int | None = None
    uncertain_rows: tuple[int, ...] = ()
    last_ordered_row: int | None = None
    yellow_row: int | None = None
    traced_rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class CopiedFile:
    """Przeczytany plik taty: sama nazwa (nigdy pełna ścieżka), odcisk i przeczytane arkusze.

    ``folders``: nazwy folderu nad folderem pliku i folderu pliku, od góry, bez pełnej ścieżki, żeby Uruchomienie
    odtworzone z Kopii (#847) leżało w tych samych folderach i miało te same Komunikaty. Komunikaty Pliku zbiorczego
    pokazują oba (``message.folder_label``), a Komunikaty INTERMAX tylko folder pliku (``message.file_label``), więc
    folder nad nim jest w Kopii, a w Komunikatach go nie ma.
    """

    name: str
    fingerprint: Fingerprint
    sheets: tuple[CopiedSheet, ...]
    folders: tuple[str, ...] = ()


Values = Sequence[object] | Mapping[int, object]
"""Wartości wiersza: kolejne od kolumny A albo numer kolumny (od 1) → wartość."""


@dataclass
class SheetCopy:
    """Arkusz w trakcie odczytu: nagłówek (numer kolumny → nagłówek), zakazane kolumny (numery od 1), kolumny, które
    Kopia niesie (``None``: każda), kolumna daty z godziną, wiersze nad wklejeniem (``CopiedSheet``) i odwołania do
    przeczytanych wierszy z ich położeniami."""

    name: str
    header_row: int
    header: Mapping[int, object]
    forbidden: frozenset[int]
    copied_columns: frozenset[int] | None = None
    date_column: int | None = None
    last_ordered_row: int | None = None
    yellow_row: int | None = None
    _rows: list[tuple[int, Values, RowPositions]] = field(default_factory=list)
    _empty: list[int] = field(default_factory=list)

    def row(self, number: int, values: Values, positions: RowPositions = UNDER_HEADER) -> None:
        """Wiersz ``number`` przeczytany z wartościami ``values`` w położeniach ``positions``; komórki liczy ``copied``."""

        self._rows.append((number, values, positions))

    def empty_rows(self, numbers: Sequence[int]) -> None:
        """Puste wiersze ``numbers`` z przeczytanego zakresu, które proces liczy (Rejestr zleceń)."""

        self._empty.extend(numbers)

    def copied(self) -> CopiedSheet:
        columns = {
            get_column_letter(column): str(name)
            for column, name in sorted(self.header.items())
            if column not in self.forbidden and name is not None and str(name).strip()
        }
        shifted = [number for number, _, positions in self._rows if positions.read]
        if len(shifted) > 1:
            raise ValueError(f"Arkusz {self.name} ma więcej niż jeden przesunięty wiersz: {shifted}")
        return CopiedSheet(
            self.name,
            self.header_row,
            columns,
            tuple(CopiedRow(number, self._cells(values, positions)) for number, values, positions in self._rows),
            tuple(self._empty),
            shifted[0] if shifted else None,
            tuple(number for number, _, positions in self._rows if positions.uncertain),
            self.last_ordered_row,
            self.yellow_row,
            tuple(number for number, _, positions in self._rows if positions.traced),
        )

    def _cells(self, values: Values, positions: RowPositions) -> dict[str, CellValue]:
        """Jedyna reguła komórki Kopii (ADR 0025 „Kopia wejścia”): komórka z kolumny c stoi w Kopii pod c +
        ``positions.read``, gdy tam i w każdym położeniu z ``positions.known`` stoi w kolumnie, którą Kopia niesie, a nie
        pod zakazanym nagłówkiem. Data z godziną spod ``date_column`` (czytana z przesunięciem ``read``) zostaje, bo nie
        jest wartością zakazanej kolumny, a bez niej odtworzenie nie powtórzy Uruchomienia (#847)."""

        numbered = _numbered(values)
        read, known = positions.read, positions.known
        placed = {
            column + read: value
            for column, value in numbered.items()
            if all(self._allowed(column + offset) for offset in {read, *known})
        }
        if self.date_column is not None:
            when = numbered.get(self.date_column - read)
            if isinstance(when, datetime):
                placed[self.date_column] = when
        return _cells(placed, self.forbidden)

    def _allowed(self, column: int) -> bool:
        return column not in self.forbidden and (self.copied_columns is None or column in self.copied_columns)


@dataclass
class WorkbookCopy:
    """Plik w trakcie odczytu: nazwa, przeczytane bajty, chwila zmiany sprzed odczytu, arkusze i nazwy folderów nad
    plikiem (``CopiedFile.folders``)."""

    name: str
    content: bytes
    modified_at: datetime | None
    _sheets: list[SheetCopy] = field(default_factory=list)
    folders: tuple[str, ...] = ()

    def sheet(
        self,
        name: str,
        header_row: int,
        header: Values,
        forbidden: Collection[int],
        *,
        copied_columns: Collection[int] | None = None,
        date_column: int | None = None,
        last_ordered_row: int | None = None,
        yellow_row: int | None = None,
    ) -> SheetCopy:
        """Arkusz ``name`` z nagłówkiem w wierszu ``header_row``, bez kolumn ``forbidden`` (numery od 1), których komórki
        czytnik oddaje pamięci reguły danych; ``copied_columns``: kolumny, które Kopia niesie (``None``: każda),
        ``date_column``: kolumna daty z godziną, która zostaje w wierszu z siatki (``SheetCopy._cells``),
        ``last_ordered_row`` i ``yellow_row``: wiersze nad wklejeniem INTERMAX (``CopiedSheet.last_ordered_row``)."""

        sheet = SheetCopy(
            name,
            header_row,
            _numbered(header),
            frozenset(forbidden),
            None if copied_columns is None else frozenset(copied_columns),
            date_column,
            last_ordered_row,
            yellow_row,
        )
        self._sheets.append(sheet)
        return sheet

    def copied(self) -> CopiedFile:
        fingerprint = Fingerprint(len(self.content), self.modified_at, hashlib.sha256(self.content).hexdigest())
        return CopiedFile(self.name, fingerprint, tuple(sheet.copied() for sheet in self._sheets), self.folders)


class InputCopy:
    """Kopia wejścia jednego Uruchomienia procesu z Centrum; pliki w kolejności odczytu."""

    def __init__(self) -> None:
        self._files: list[WorkbookCopy] = []

    def workbook(self, path: Path, content: bytes, modified: datetime | None) -> WorkbookCopy:
        """Plik ``path`` przeczytany z bajtów ``content``; ``modified``: chwila zmiany pliku sprzed odczytu bajtów
        (``dad_files.DadFiles.read``)."""

        folders = tuple(folder for folder in (path.parent.parent.name, path.parent.name) if folder)
        copy = WorkbookCopy(path.name, content, modified, folders=folders)
        self._files.append(copy)
        return copy

    def files(self) -> tuple[CopiedFile, ...]:
        """Przeczytane pliki po regule danych, z odciskiem; liczone po końcu procesu, w Logach Uruchomienia."""

        return tuple(copy.copied() for copy in self._files)


def _numbered(values: Values) -> Mapping[int, object]:
    return values if isinstance(values, Mapping) else dict(enumerate(values, start=1))


def _cells(values: Values, forbidden: frozenset[int]) -> dict[str, CellValue]:
    numbered = _numbered(values)
    return {
        get_column_letter(column): _value(value)
        for column, value in numbered.items()
        if value is not None and column not in forbidden
    }


def _value(value: object) -> CellValue:
    """Wartość komórki z openpyxl do JSON: tekst (także formuła), liczba i prawda/fałsz jak są, a data z godziną (openpyxl
    czyta tak także samą datę), godzina i czas trwania z rodzajem. Formuła tablicowa to jej tekst, jak każda formuła."""

    match value:
        case bool() | int() | float() | str():
            return value
        case datetime():
            return Typed("datetime", value.isoformat())
        case time():
            return Typed("time", value.isoformat())
        case timedelta():
            return Typed("timedelta", repr(value.total_seconds()))
        case ArrayFormula():
            return str(value.text)
        case _:
            return Typed("other", type(value).__name__)
