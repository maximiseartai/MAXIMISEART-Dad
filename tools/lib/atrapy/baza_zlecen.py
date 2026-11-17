"""Syntetyczna Baza zleceń w kształcie skoroszytu taty dla testów Historii adresu w Uporządkowaniu INTERMAX.

Arkusze mają układy kolumn Bazy taty: 5 kolumn najstarszego arkusza (``FIVE``: ``adres``, ``sprzęt``, ``nr zle``,
``data``, ``kto``, adres z miastem przed przecinkiem), 11 kolumn (``ELEVEN``, data w ``DATA``) i 12 kolumn (``TWELVE``,
``DATA GODZ. POCZ.`` i ``MIASTO``, pusta, gdy wiersz nie ma miasta). Zapis jak u taty: nagłówki pogrubione, wartości w innej czcionce niż INTERMAX, co
drugi wiersz na żółtym tle, numer zlecenia z Hiperłączem, data w formacie daty, ``UMOWA`` pusta w środku wiersza, a
teksty wspólne jak w Excelu (``intermax.like_excel``). Adresy i wartości są zmyślone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from atrapy.intermax import like_excel


@dataclass(frozen=True)
class Layout:
    """Układ kolumn arkusza Bazy: nagłówki od kolumny A i kolumny (od 1) daty realizacji, numeru zlecenia i ``MIASTO``
    (``None``: arkusz bez niej)."""

    headers: tuple[str, ...]
    date: int
    number: int
    city: int | None = None


FIVE = Layout(("adres", "sprzęt", "nr zle", "data", "kto"), date=4, number=3)
ELEVEN = Layout(
    (
        "ADRES",
        "UMOWA",
        "URZĄDZENIA",
        "CZYNNOŚCI",
        "NUMER ZL.",
        "DATA",
        "WYKONAWCA",
        "SKUTECZNE",
        "CZYNNOŚCI ZREALIZOWANE",
        "zwrot",
        "UWAGI",
    ),
    date=6,
    number=5,
)
TWELVE = Layout(
    (
        "ADRES",
        "DATA GODZ. POCZ.",
        "MIASTO",
        "UMOWA",
        "URZĄDZENIA",
        "CZYNNOŚCI",
        "NUMER ZL.",
        "WYKONAWCA",
        "SKUTECZNE",
        "CZYNNOŚCI ZREALIZOWANE",
        "ZWROT",
        "UWAGI",
    ),
    date=2,
    number=7,
    city=3,
)
_EMPTY = "UMOWA"
"""Nagłówek kolumny, która w wierszach Bazy taty jest zwykle pusta: pusta komórka w środku bloku."""
_FONT = Font(name="Arial", sz=10, b=True, color="FF0000FF")
_YELLOW = PatternFill("solid", fgColor="FFFFFF00")


@dataclass(frozen=True)
class Visit:
    """Wiersz Bazy: adres w kolumnie A, data realizacji (data, tekst albo pusta), numer zlecenia, znak wiersza, z którego
    powstają wartości pozostałych kolumn, i ``MIASTO`` w układzie z tą kolumną (``None``: pusta)."""

    address: str
    when: datetime | str | None
    number: int | str | None
    mark: str
    city: str | None = None

    def values(self, layout: Layout) -> tuple[object, ...]:
        """Wartości od kolumny A do szerokości ``layout``, jak w wierszu Bazy (``None``: pusta komórka)."""

        values: list[object] = [None if header == _EMPTY else f"{self.mark} {header}" for header in layout.headers]
        values[0] = self.address
        values[layout.date - 1] = self.when
        values[layout.number - 1] = self.number
        if layout.city is not None:
            values[layout.city - 1] = self.city
        return tuple(values)


@dataclass(frozen=True)
class BaseSheet:
    """Arkusz Bazy: nazwa, układ kolumn i wiersze od 2, po kolei."""

    name: str
    layout: Layout
    visits: Sequence[Visit]


WITHOUT_HITS: tuple[BaseSheet, ...] = (
    BaseSheet("10_12_2018-01_08_2020", FIVE, [Visit("Miastko,Daleka 001/", datetime(2019, 3, 4, 9), 11, "stara")]),
    BaseSheet("01_08_2020-01_06_2021", ELEVEN, [Visit("UL. DALEKA 2/5", datetime(2021, 2, 3, 10), 22, "środkowa")]),
    BaseSheet("19_12_2025-17_11_2026", TWELVE, [Visit("DALEKA 3", datetime(2026, 1, 2, 11), 33, "nowa")]),
)
"""Baza w trzech układach taty bez adresów zleceń atrap INTERMAX (``Ulica N``): Uporządkowanie czyta ją bez trafień."""


def write_order_base(path: Path, sheets: Sequence[BaseSheet]) -> None:
    """Baza zleceń z arkuszami ``sheets`` w tej kolejności, zapisana jak w Excelu."""

    workbook = Workbook()
    first = workbook.active
    assert isinstance(first, Worksheet)
    workbook.remove(first)
    for found in sheets:
        sheet = workbook.create_sheet(found.name)
        for column, header in enumerate(found.layout.headers, start=1):
            sheet.cell(1, column, header).font = Font(name="Calibri", sz=11, b=True)
        for row, visit in enumerate(found.visits, start=2):
            for column, value in enumerate(visit.values(found.layout), start=1):
                cell = sheet.cell(row, column, value)
                cell.font = _FONT
                if row % 2:
                    cell.fill = _YELLOW
                if column == found.layout.date and isinstance(value, datetime):
                    cell.number_format = "dd.mm.yyyy hh:mm"
                if column == found.layout.number and value is not None:
                    cell.hyperlink = f"https://example.invalid/baza/{value}"
    workbook.save(path)
    like_excel(path)
