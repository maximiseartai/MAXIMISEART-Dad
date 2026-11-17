"""Baza zleceń taty czytana raz, tylko do odczytu: Historia adresu zlecenia z jej arkuszy.

Kształt danych. Baza to arkusze w kolejności skoroszytu (``_Sheet``), każdy z własnym układem kolumn: szerokość to
ostatnia kolumna wiersza 1 z nagłówkiem, kolumnę daty realizacji i numeru zlecenia daje nagłówek (``_DATE_HEADERS``,
``_NUMBER_HEADERS``, bez wielkości liter), a wiersze Bazy to wiersze od 2 z tekstem w kolumnie A (adres), każdy z
``MIASTO``, gdy arkusz ma kolumnę o tym nagłówku. Historia adresu zlecenia (``OrderBase.history``) to bloki
(``HistoryBlock``): wiersze z tym samym adresem (``same_address``), od najnowszej daty realizacji do najstarszej, a
wiersz bez daty z datą (data tekstem, liczba bez formatu daty, pusta) na końcu, w kolejności arkuszy i wierszy. Wiersz z tym samym numerem zlecenia co zlecenie (po samych cyfrach) nie wchodzi.
Blok ma wartości komórek od kolumny A do szerokości swojego arkusza, bez stylów i Hiperłączy.

Odczyt (``read``) idzie przez uchwyt plików taty bez Kopii wejścia: pamięć reguły danych poznaje adres z kolumny A
każdego wiersza Bazy, a Kopia wejścia Bazy nie dostaje. Bazę otwartą w Excelu czyta w jej ostatniej zapisanej wersji.
Arkusze czyta z XML bez openpyxl (``workbook_parts``, ``cell_values``): przy odczycie tylko kolumnę A, ``MIASTO`` i
granice wierszy, a wartości całego wiersza dopiero dla trafienia, bo Baza taty ma ~125 tys. wierszy w sześciu arkuszach.
Plik, którego nie ma, nie da się odczytać albo nie jest skoroszytem, to ``WorkbookError``, a arkusz, którego wierszy
nie da się rozdzielić albo który ma adresy w kolumnie A bez jej nagłówka, to wynik ``UnsupportedSheet``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

from . import workbook_files
from .cell_values import CellValues
from .client_data import ForbiddenColumn, shown
from .dad_files import DadFiles
from .same_address import AddressIndex
from .text import normalize_text
from .workbook_parts import (
    MAIN,
    OFFICE_REL,
    IrregularSheetData,
    Relationship,
    SheetData,
    SheetRow,
    column_texts,
    office_document,
    package_parts,
    relationships,
    sheet_cells,
)

__all__ = ["ORDER_BASE_NAME", "HistoryBlock", "OrderBase", "UnsupportedSheet", "read"]

ORDER_BASE_NAME: Final = "Baza zleceń do 17_11_2026.xlsx"
"""Nazwa Bazy zleceń w folderze INTERMAX; tata jej nie zmienia, tylko dopisuje arkusze."""

_DATE_HEADERS: Final = frozenset(map(normalize_text, ("data", "DATA GODZ. POCZ.")))
_NUMBER_HEADERS: Final = frozenset(map(normalize_text, ("nr zle", "NUMER ZL.")))
_CITY_HEADERS: Final = frozenset({normalize_text("MIASTO")})
_ADDRESS_COLUMN: Final = 1
_NOT_DIGIT: Final = re.compile(r"\D")


@dataclass(frozen=True)
class HistoryBlock:
    """Wiersz Bazy zleceń w Historii adresu zlecenia: wartości komórek od kolumny A do szerokości nagłówka jego arkusza
    (``cell_values``; ``None``: pusta komórka)."""

    values: tuple[object, ...]


@dataclass(frozen=True)
class UnsupportedSheet:
    """Arkusz Bazy, którego narzędzie nie czyta: wierszy nie da się rozdzielić albo kolumna A nie ma nagłówka."""

    sheet: str


@dataclass(frozen=True)
class _Sheet:
    """Arkusz Bazy: szerokość nagłówka, kolumny daty i numeru zlecenia (od 1, ``None``: bez nagłówka), XML i wiersze."""

    width: int
    date: int | None
    number: int | None
    xml: bytes
    rows: Mapping[int, SheetRow]


@dataclass(frozen=True)
class _Row:
    """Wiersz Bazy w indeksie adresów: arkusz (miejsce w ``OrderBase.sheets``) i numer wiersza."""

    sheet: int
    number: int


class OrderBase:
    """Baza zleceń przeczytana raz: jej arkusze i indeks adresów kolumny A."""

    def __init__(self, path: Path, sheets: Sequence[_Sheet], index: AddressIndex[_Row], values: CellValues) -> None:
        self._path = path
        self._sheets = tuple(sheets)
        self._index = index
        self._values = values

    @property
    def sheet_count(self) -> int:
        return len(self._sheets)

    def history(self, address: object, city: object, number: object) -> tuple[HistoryBlock, ...]:
        """Historia adresu zlecenia z ``ADRES`` ``address``, ``MIASTO`` ``city`` i ``NUMER ZL.`` ``number`` (zob.
        docstring modułu); ``WorkbookError``, gdy komórki wiersza z tym adresem nie da się odczytać."""

        own = _order_number(number)
        dated: list[tuple[datetime, HistoryBlock]] = []
        undated: list[HistoryBlock] = []
        for row in self._index.matching(address, city):
            sheet = self._sheets[row.sheet]
            values = self._row_values(sheet, row.number)
            if own is not None and sheet.number is not None and _order_number(values[sheet.number - 1]) == own:
                continue
            when = None if sheet.date is None else values[sheet.date - 1]
            if isinstance(when, datetime):
                dated.append((when, HistoryBlock(values)))
            else:
                undated.append(HistoryBlock(values))
        dated.sort(key=lambda found: found[0], reverse=True)
        return (*(block for _, block in dated), *undated)

    def _row_values(self, sheet: _Sheet, number: int) -> tuple[object, ...]:
        with workbook_files.unreadable_as_error(self._path):
            row = sheet.rows[number]
            cells = {cell.column: cell for cell in sheet_cells(sheet.xml[row.start : row.end])}
            return tuple(
                None if (cell := cells.get(column)) is None else self._values.value(cell) for column in range(1, sheet.width + 1)
            )


def read(path: Path, files: DadFiles) -> OrderBase | UnsupportedSheet:
    """Baza zleceń ``path`` uchwytem ``files``; ``WorkbookError``, gdy jej nie ma, jest niedostępna albo nieczytelna."""

    file = files.read(path, despite_excel_lock=True)
    memory = file.memory(((ForbiddenColumn.ADDRESS, _ADDRESS_COLUMN),))
    sheets: list[_Sheet] = []
    addresses: list[tuple[object, object, _Row]] = []
    with workbook_files.unreadable_as_error(path), package_parts(file.content) as parts:
        workbook = office_document(parts)
        if workbook is None:
            raise KeyError("officeDocument")
        rels = relationships(parts, workbook)
        values = CellValues.of(parts, workbook, rels)
        for name, part in _worksheets(parts[workbook], rels):
            xml = parts[part]
            try:
                texts = list(column_texts(xml, _ADDRESS_COLUMN, 2, values.shared))
                rows = {row.number: row for row in SheetData.of(xml).rows}
            except IrregularSheetData:
                return UnsupportedSheet(name)
            header = [normalize_text(value) for value in values.header(xml)]
            if texts and not (header[0] if header else ""):
                return UnsupportedSheet(name)
            city = _column(header, _CITY_HEADERS)
            cities = {} if city is None else dict(column_texts(xml, city, 2, values.shared))
            for number, text in texts:
                memory.remember({_ADDRESS_COLUMN: text})
                addresses.append((text, cities.get(number), _Row(len(sheets), number)))
            sheets.append(_Sheet(_width(header), _column(header, _DATE_HEADERS), _column(header, _NUMBER_HEADERS), xml, rows))
    return OrderBase(path, sheets, AddressIndex(addresses), values)


def _worksheets(workbook_xml: bytes, rels: Mapping[str, Relationship]) -> list[tuple[str, str]]:
    """Nazwa i część zip każdego arkusza z wierszami w kolejności skoroszytu; arkusz wykresu nie ma wierszy."""

    sheets = ElementTree.fromstring(workbook_xml).iter(f"{MAIN}sheet")
    found = ((sheet.get("name", ""), rels.get(sheet.get(f"{{{OFFICE_REL}}}id", ""))) for sheet in sheets)
    return [(name, rel.target) for name, rel in found if rel is not None and rel.kind.endswith("/worksheet")]


def _width(header: Sequence[str]) -> int:
    return max((column for column, value in enumerate(header, start=1) if value), default=0)


def _column(header: Sequence[str], names: frozenset[str]) -> int | None:
    return next((column for column, value in enumerate(header, start=1) if value in names), None)


def _order_number(value: object) -> str | None:
    """Numer zlecenia: same cyfry tego, co pokazuje Excel (``shown``), bez zer wiodących; ``None``: bez cyfry innej niż
    zero. Cyfry zostają tekstem, bo komórka Bazy ma ich dowolnie wiele."""

    return ("" if value is None else _NOT_DIGIT.sub("", shown(value)).lstrip("0")) or None
