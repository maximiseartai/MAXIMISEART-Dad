"""Rozliczenie pracownika z Wiersza danych: to, co Wykonawca dostaje z Wiersza danych Pliku zbiorczego.

Jedna droga, ``for_worker``, robi z Wierszy danych z Wykonawcą to, co trafia do Rozliczenia pracownika, w tej
kolejności:

1. ``ADRES`` traci Znacznik efenix i Znacznik przekazania (``efenix_mark``), bo Znacznik nie jest Wyróżnieniem; inne
   Wyróżnienia tej komórki, inne wypełnienia ``ADRES`` i te same kolory w innej kolumnie zostają.
2. Ilości tylko dla INEA (ADR 0018) zostają puste: INEA płaci za nie tacie przy każdym takim zleceniu, ale Wykonawca tej
   pracy nie wykonuje. Które komórki, mówią reguły „zostaw pustą w Rozliczeniu pracownika” Reguł ilości (ADR 0033),
   liczone silnikiem na treści zlecenia każdego Wiersza danych, także bez daty w ``DATA``.
3. Czerwone pole i Zielone pole (ADR 0039), komórki Ilości usług i ``AS``: Czerwone pole to pozycja, za którą płaci INEA,
   a nie Wykonawca, więc jest puste; Zielone pole to pozycja, którą dostaje Wykonawca, więc ma 1. Oba tracą wypełnienie,
   więc są białe jak komórka Wzorca rozliczenia pracownika bez Wyróżnień. Kolor czyta jedyny odczyt koloru legendy
   (``order_facts.legend_colour``), więc liczy się pole z Kodu czynności i pole pokolorowane przez tatę ręcznie, a każde
   inne wypełnienie, np. tło Wzorca pliku zbiorczego w N:V, zostaje.

Kolejność 2 przed 3 to decyzja Maksa: Zielone pole nie jest Ilością tylko dla INEA, więc ma 1 także tam, gdzie
Reguła ilości zostawia komórkę pustą, i nie liczy się do wyczyszczonych. Plik zbiorczy i Kontrola ilości widzą Wiersze
danych bez zmian.

Trzy kroki leżą w jednym module, a nie Ilości tylko dla INEA w module Czerwonego i Zielonego pola: Ilości tylko dla INEA
nie są kolorem, a zdjęcie Znacznika efenix zostałoby wtedy w module Wyceny w efenix i wołający dalej składałby drogę do
Wykonawcy z dwóch kroków.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from openpyxl.utils import column_index_from_string

from .activity_legend import AMOUNT_COLUMN, FillColour
from .collective_layout import QUANTITY_LETTERS
from .efenix_mark import mark_of
from .order_facts import MissingHeaders, legend_colour, order_contents
from .quantity_engine import QuantityRules, evaluate
from .register_columns import ADDRESS, DEVICES
from .text import normalize_text
from .workbook_files import DataCell, DataRow, is_blank

Cleared = Mapping[str, int]
"""Kolumna reguły „zostaw pustą” → liczba wyczyszczonych komórek, które miały wartość (także 0), bez Zielonych pól; każda kolumna
``QuantityRules.leave_empty_columns`` w jej kolejności, także z liczbą 0."""

_COLUMNS: Final = tuple(column_index_from_string(column) - 1 for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN))
_FOR_WORKER: Final[Mapping[FillColour, int | None]] = {FillColour.RED: None, FillColour.GREEN: 1}


def for_worker(header: Mapping[str, int], rows: Sequence[DataRow], rules: QuantityRules) -> tuple[list[DataRow], Cleared]:
    """Wiersze danych dla Rozliczenia pracownika i liczba komórek wyczyszczonych jako Ilości tylko dla INEA w każdej kolumnie.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1. Bez nagłówka ``ADRES`` Znacznika nie ma gdzie zdjąć, bez
    nagłówka ``URZĄDZENIA`` nic nie jest czyszczone jako Ilość tylko dla INEA, a bez nagłówka ``UMOWA``, ``CZYNNOŚCI``
    albo ``DATA`` ta kolumna czyta się jak pusta komórka.

    Wyczyszczona Ilość tylko dla INEA zostaje z Wyróżnieniami i formatem liczby, jak po skasowaniu liczby w Excelu, i bez
    Hiperłącza, bo komórka ma je tylko przy wartości (``DataCell``). Czerwone pole i Zielone pole zmieniają się bez
    względu na to, co w nich stoi (liczba, 0, tekst, formuła); kolor czcionki, pogrubienie i kursywa zostają, a
    Hiperłącze zostaje przy wartości 1 Zielonego pola, jak przy każdej wartości (GLOSSARY „Hiperłącze”).
    """

    rows, cleared = _without_inea_only(header, _without_efenix_mark(header, rows), rules)
    return [_coloured(row) for row in rows], cleared


def _without_efenix_mark(header: Mapping[str, int], rows: Sequence[DataRow]) -> list[DataRow]:
    address = header.get(normalize_text(ADDRESS.target_header))
    if address is None:
        return list(rows)
    return [_unmarked(row, address - 1) for row in rows]


def _unmarked(row: DataRow, index: int) -> DataRow:
    cell = row.cells[index]
    if mark_of(cell.highlights.fill) is None:
        return row
    cells = list(row.cells)
    cells[index] = cell._replace(highlights=replace(cell.highlights, fill=None))
    return replace(row, cells=tuple(cells))


def _without_inea_only(
    header: Mapping[str, int], rows: Sequence[DataRow], rules: QuantityRules
) -> tuple[list[DataRow], Cleared]:
    cleared = dict.fromkeys(rules.leave_empty_columns, 0)
    contents = order_contents(header, rows, required=(DEVICES,))
    if isinstance(contents, MissingHeaders):
        return list(rows), cleared
    result: list[DataRow] = []
    for row, content in zip(rows, contents, strict=True):
        cells = list(row.cells)
        for column in evaluate(rules, content).leave_empty:
            index = column_index_from_string(column) - 1
            if _is_green(cells[index]):
                continue
            cleared[column] += not is_blank(cells[index].value)
            cells[index] = cells[index]._replace(value=None, hyperlink=None)
        result.append(replace(row, cells=tuple(cells)))
    return result, cleared


def _is_green(cell: DataCell) -> bool:
    return legend_colour(cell.highlights.fill) is FillColour.GREEN


def _coloured(row: DataRow) -> DataRow:
    cells = list(row.cells)
    for index in _COLUMNS:
        colour = legend_colour(cells[index].highlights.fill)
        if colour is not None:
            cells[index] = _settled(cells[index], _FOR_WORKER[colour])
    return replace(row, cells=tuple(cells))


def _settled(cell: DataCell, value: int | None) -> DataCell:
    return cell._replace(
        value=value,
        highlights=replace(cell.highlights, fill=None),
        hyperlink=None if value is None else cell.hyperlink,
    )
