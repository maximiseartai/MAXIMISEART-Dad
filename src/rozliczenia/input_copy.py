"""Kopia wejścia (#841): Wiersze danych, które Uruchomienie procesu przeczytało z plików taty, i odcisk każdego pliku.

Uruchomienie z Centrum ma swoją Kopię wejścia (``InputCopy``), a czytnik Wierszy danych, który czyta dla niego plik
taty, oddaje jej bajty pliku i każdy przeczytany wiersz: Rejestr zleceń w Przygotowaniu pliku zbiorczego
(``input_checks.read_register``), Plik zbiorczy w Przebiegu rozliczeń (``workbook_files.read_data_rows``) i w Wycenie
w efenix (``workbook_files.read_computed_rows``). Proces bez Centrum (Skrypt dla maszyn) Kopii nie ma, bo nie ma Logów.

W trakcie odczytu Kopia trzyma tylko odwołania do bajtów i wartości, które czytnik i tak ma, i chwilę zmiany pliku.
Plik po regule danych (``files``) powstaje po wyniku Uruchomienia: odcisk (rozmiar, chwila zmiany i skrót SHA-256
przeczytanych bajtów) i arkusze z kolumnami po nagłówku i wierszami po numerze, bez kolumn zakazanych przez regułę
danych (``client_data.forbidden_column``) i bez pustych komórek. Wolny tekst i wartości zakazanych kolumn w innych
komórkach maskuje strażnik Logów (``run_logs.guarded``), jak w każdym innym polu Logów.

Kopia niesie wartości komórek, bo na nich proces podejmuje decyzje: wynik, Komunikaty i ślad. Wygląd komórek
(Wyróżnienia, format liczby, Hiperłącza) proces tylko przenosi do plików, które tworzy, więc go nie ma.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import math
from pathlib import Path
from typing import Literal

from openpyxl.utils import get_column_letter

from . import client_data

TypedKind = Literal["datetime", "date", "time", "timedelta", "number", "other"]


@dataclass(frozen=True)
class Typed:
    """Wartość komórki, której JSON nie odróżnia od tekstu: ``kind`` i jej zapis (ISO 8601, sekundy albo tekst)."""

    kind: TypedKind
    text: str


CellValue = bool | int | float | str | Typed
"""Wartość niepustej komórki w Kopii wejścia."""


@dataclass(frozen=True)
class Fingerprint:
    """Odcisk przeczytanego pliku: ``size`` i ``sha256`` z przeczytanych bajtów, ``modified_at`` z pliku w chwili
    odczytu (UTC; ``None``, gdy system jej nie oddał)."""

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
    """Przeczytany arkusz: wiersz nagłówka, nagłówki po literze kolumny, wiersze i puste wiersze, które proces liczy."""

    name: str
    header_row: int
    columns: Mapping[str, str]
    rows: tuple[CopiedRow, ...]
    empty_rows: tuple[int, ...]


@dataclass(frozen=True)
class CopiedFile:
    """Przeczytany plik taty: sama nazwa (nigdy pełna ścieżka), odcisk i przeczytane arkusze."""

    name: str
    fingerprint: Fingerprint
    sheets: tuple[CopiedSheet, ...]


Values = Sequence[object] | Mapping[int, object]
"""Wartości wiersza: kolejne od kolumny A albo numer kolumny (od 1) → wartość."""


@dataclass
class SheetCopy:
    """Arkusz w trakcie odczytu: nagłówek (numer kolumny → nagłówek) i odwołania do przeczytanych wierszy."""

    name: str
    header_row: int
    header: Mapping[int, object]
    _rows: list[tuple[int, Values]] = field(default_factory=list)
    _empty: list[int] = field(default_factory=list)

    def row(self, number: int, values: Values) -> None:
        """Wiersz ``number`` przeczytany z wartościami ``values``."""

        self._rows.append((number, values))

    def empty_rows(self, numbers: Sequence[int]) -> None:
        """Puste wiersze ``numbers`` z przeczytanego zakresu, które proces liczy (Rejestr zleceń)."""

        self._empty.extend(numbers)

    def copied(self) -> CopiedSheet:
        forbidden = {column for column, name in self.header.items() if client_data.forbidden_column(name) is not None}
        columns = {
            get_column_letter(column): str(name)
            for column, name in sorted(self.header.items())
            if column not in forbidden and name is not None and str(name).strip()
        }
        return CopiedSheet(
            self.name,
            self.header_row,
            columns,
            tuple(CopiedRow(number, _cells(values, forbidden)) for number, values in self._rows),
            tuple(self._empty),
        )


@dataclass
class WorkbookCopy:
    """Plik w trakcie odczytu: nazwa, przeczytane bajty, chwila zmiany z chwili odczytu i arkusze."""

    name: str
    content: bytes
    modified_at: datetime | None
    _sheets: list[SheetCopy] = field(default_factory=list)

    def sheet(self, name: str, header_row: int, header: Values) -> SheetCopy:
        """Arkusz ``name`` z nagłówkiem w wierszu ``header_row``."""

        sheet = SheetCopy(name, header_row, _numbered(header))
        self._sheets.append(sheet)
        return sheet

    def copied(self) -> CopiedFile:
        fingerprint = Fingerprint(len(self.content), self.modified_at, hashlib.sha256(self.content).hexdigest())
        return CopiedFile(self.name, fingerprint, tuple(sheet.copied() for sheet in self._sheets))


class InputCopy:
    """Kopia wejścia jednego Uruchomienia procesu z Centrum; pliki w kolejności odczytu."""

    def __init__(self) -> None:
        self._files: list[WorkbookCopy] = []

    def workbook(self, path: Path, content: bytes) -> WorkbookCopy:
        """Plik ``path`` przeczytany z bajtów ``content``; chwila zmiany pliku jest z tej chwili."""

        try:
            modified_at: datetime | None = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            modified_at = None
        copy = WorkbookCopy(path.name, content, modified_at)
        self._files.append(copy)
        return copy

    def files(self) -> tuple[CopiedFile, ...]:
        """Przeczytane pliki po regule danych, z odciskiem; liczone po wyniku Uruchomienia."""

        return tuple(copy.copied() for copy in self._files)


def _numbered(values: Values) -> Mapping[int, object]:
    return values if isinstance(values, Mapping) else dict(enumerate(values, start=1))


def _cells(values: Values, forbidden: set[int]) -> dict[str, CellValue]:
    numbered = _numbered(values)
    return {
        get_column_letter(column): _value(value)
        for column, value in numbered.items()
        if value is not None and column not in forbidden
    }


def _value(value: object) -> CellValue:
    """Wartość komórki do JSON: tekst, liczba i prawda/fałsz jak są, a data, godzina i czas trwania z rodzajem."""

    match value:
        case bool() | int() | str():
            return value
        case float() if math.isfinite(value):
            return value
        case float():
            return Typed("number", repr(value))
        case Decimal():
            return Typed("number", str(value))
        case datetime():
            return Typed("datetime", value.isoformat())
        case date():
            return Typed("date", value.isoformat())
        case time():
            return Typed("time", value.isoformat())
        case timedelta():
            return Typed("timedelta", repr(value.total_seconds()))
        case _:
            return Typed("other", str(value))
