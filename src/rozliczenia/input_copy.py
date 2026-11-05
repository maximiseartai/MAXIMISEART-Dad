"""Kopia wejścia (#841): Wiersze danych, które Uruchomienie procesu przeczytało z plików taty, i odcisk każdego pliku.

Uruchomienie z Centrum ma swoją Kopię wejścia (``InputCopy``), a czytnik Wierszy danych, który czyta dla niego plik
taty, oddaje jej bajty, z których czytał plik, zakazane kolumny każdego arkusza i każdy przeczytany wiersz: Rejestr
zleceń w Przygotowaniu pliku zbiorczego (``input_checks.read_register``), Plik zbiorczy w Przebiegu rozliczeń
(``workbook_files.read_data_rows``), w Wycenie w efenix (``workbook_files.read_computed_rows``) i INTERMAX w
Uporządkowaniu INTERMAX (``intermax_file.Register.read``, #842). Zakazane kolumny to te, których komórki ten sam czytnik
oddaje pamięci reguły danych (``client_data.ForbiddenValues``). Proces bez Centrum (Skrypt dla maszyn) Kopii nie ma, bo
nie ma Logów.

W trakcie odczytu Kopia trzyma tylko odwołania do bajtów i wartości, które czytnik i tak ma, i chwilę zmiany pliku,
którą czytnik bierze przed odczytem bajtów (``modified_at``). Plik po regule danych (``files``) powstaje po końcu
procesu, zanim karta pokaże wynik: odcisk (rozmiar, chwila zmiany i skrót SHA-256 przeczytanych bajtów) i arkusze z
kolumnami po nagłówku i wierszami po numerze, bez zakazanych kolumn i bez pustych komórek. Wolny tekst i wartości
zakazanych kolumn w innych komórkach, także liczby, maskuje strażnik Logów (``run_logs.guarded``), jak w każdym innym
polu Logów.

Kopia niesie wartości komórek, bo na nich proces podejmuje decyzje: wynik, Komunikaty i ślad. Wygląd komórek
(Wyróżnienia, format liczby, Hiperłącza) proces tylko przenosi do plików, które tworzy, więc go nie ma.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Literal

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from .raw_orders import OrderKind, ShiftTrace

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
    ``uncertain_rows``: wiersze z dwoma położeniami (wklejenie INTERMAX, ``raw_orders.Shifts.possible``), które mają
    w Kopii tylko komórki dozwolone przy każdym ich możliwym przesunięciu, więc brak komórki nie znaczy w nich pustej.
    ``last_ordered_row`` i ``yellow_row``: ostatni uporządkowany i żółty wiersz nad wklejeniem INTERMAX
    (``raw_orders.above_paste``), sam numer, bez treści; ``None``: bez takiego wiersza i arkusze innych plików.
    ``traced_rows``: wiersz ze śladem przesunięcia, który nie jest pierwszym wierszem bloku wklejenia, z rodzajami
    śladu (``raw_orders.ShiftTrace``): łamie fakt domeny, że przesunięty przychodzi tylko pierwszy wklejony wiersz.
    ``order_kinds``: rodzaj zlecenia (``raw_orders.OrderKind`` inny niż ``OTHER``) wiersza z dwoma położeniami, którego
    ``URZĄDZENIA`` Kopia nie niesie, bo w drugim położeniu ta komórka stoi pod ``ADRES``: z niego Planowanie bierze
    Kolor usterki i Wpis, więc odtworzenie Uruchomienia (#847) potrzebuje go bez komórki. To wartość z zamkniętej listy,
    a nie treść komórki.
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
    traced_rows: Mapping[int, tuple[ShiftTrace, ...]] = field(default_factory=dict)
    order_kinds: Mapping[int, OrderKind] = field(default_factory=dict)


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
    """Arkusz w trakcie odczytu: nagłówek (numer kolumny → nagłówek), zakazane kolumny (numery od 1), przesunięty
    wiersz, wiersze z dwoma położeniami, wiersze nad wklejeniem i wiersze ze śladem przesunięcia (``CopiedSheet``) i
    odwołania do przeczytanych wierszy."""

    name: str
    header_row: int
    header: Mapping[int, object]
    forbidden: frozenset[int]
    shifted_row: int | None = None
    uncertain_rows: tuple[int, ...] = ()
    last_ordered_row: int | None = None
    yellow_row: int | None = None
    traced_rows: Mapping[int, tuple[ShiftTrace, ...]] = field(default_factory=dict)
    order_kinds: Mapping[int, OrderKind] = field(default_factory=dict)
    _rows: list[tuple[int, Values]] = field(default_factory=list)
    _empty: list[int] = field(default_factory=list)

    def row(self, number: int, values: Values) -> None:
        """Wiersz ``number`` przeczytany z wartościami ``values``."""

        self._rows.append((number, values))

    def empty_rows(self, numbers: Sequence[int]) -> None:
        """Puste wiersze ``numbers`` z przeczytanego zakresu, które proces liczy (Rejestr zleceń)."""

        self._empty.extend(numbers)

    def copied(self) -> CopiedSheet:
        columns = {
            get_column_letter(column): str(name)
            for column, name in sorted(self.header.items())
            if column not in self.forbidden and name is not None and str(name).strip()
        }
        return CopiedSheet(
            self.name,
            self.header_row,
            columns,
            tuple(CopiedRow(number, _cells(values, self.forbidden)) for number, values in self._rows),
            tuple(self._empty),
            self.shifted_row,
            self.uncertain_rows,
            self.last_ordered_row,
            self.yellow_row,
            dict(self.traced_rows),
            dict(self.order_kinds),
        )


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
        shifted_row: int | None = None,
        uncertain_rows: Sequence[int] = (),
        *,
        last_ordered_row: int | None = None,
        yellow_row: int | None = None,
        traced_rows: Mapping[int, tuple[ShiftTrace, ...]] | None = None,
        order_kinds: Mapping[int, OrderKind] | None = None,
    ) -> SheetCopy:
        """Arkusz ``name`` z nagłówkiem w wierszu ``header_row``, bez kolumn ``forbidden`` (numery od 1), których komórki
        czytnik oddaje pamięci reguły danych; ``shifted_row``: przesunięty wiersz (``CopiedSheet.shifted_row``), którego
        wartości czytnik oddaje już pod ich nagłówkiem, a ``uncertain_rows`` wiersze z dwoma położeniami, którym
        czytnik oddaje tylko komórki dozwolone w każdym położeniu (``CopiedSheet.uncertain_rows``);
        ``last_ordered_row`` i ``yellow_row``: wiersze nad wklejeniem INTERMAX (``CopiedSheet.last_ordered_row``);
        ``traced_rows``: wiersze ze śladem przesunięcia poza pierwszym wierszem bloku (``CopiedSheet.traced_rows``), a
        ``order_kinds`` rodzaje zlecenia wierszy bez ``URZĄDZENIA`` w Kopii (``CopiedSheet.order_kinds``)."""

        sheet = SheetCopy(
            name,
            header_row,
            _numbered(header),
            frozenset(forbidden),
            shifted_row,
            tuple(uncertain_rows),
            last_ordered_row,
            yellow_row,
            dict(traced_rows or {}),
            dict(order_kinds or {}),
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
        (``modified_at``)."""

        folders = tuple(folder for folder in (path.parent.parent.name, path.parent.name) if folder)
        copy = WorkbookCopy(path.name, content, modified, folders=folders)
        self._files.append(copy)
        return copy

    def files(self) -> tuple[CopiedFile, ...]:
        """Przeczytane pliki po regule danych, z odciskiem; liczone po końcu procesu, w Logach Uruchomienia."""

        return tuple(copy.copied() for copy in self._files)


def modified_at(path: Path) -> datetime | None:
    """Chwila zmiany pliku ``path`` teraz (UTC); ``None``, gdy system jej nie oddał. Czytnik bierze ją przed odczytem
    bajtów, więc plik zapisany znowu w trakcie albo po odczycie (Autozapis Excela, OneDrive) nie zmienia jej w odcisku.
    Zapis między tą chwilą a początkiem odczytu daje w odcisku chwilę wcześniejszej wersji; o wersji rozstrzyga skrót."""

    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


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
