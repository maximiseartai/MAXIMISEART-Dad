"""Czerwone pole i Zielone pole (ADR 0039): komórki Ilości usług i ``AS``, które Przebieg rozliczeń zmienia w drodze do
Rozliczenia pracownika.

Czerwone pole to pozycja, za którą płaci INEA, a nie Wykonawca, więc w Rozliczeniu pracownika jest puste; Zielone pole
to pozycja, którą dostaje Wykonawca, więc ma 1. Oba tracą wypełnienie, więc są białe jak komórka Wzorca rozliczenia
pracownika bez Wyróżnień. Kolor czyta jedyny odczyt koloru legendy (``order_facts.legend_colour``), więc liczy się
pole z Kodu czynności i pole pokolorowane przez tatę ręcznie, a każde inne wypełnienie, np. tło Wzorca pliku
zbiorczego w N:V, zostaje. Plik zbiorczy i Kontrola ilości widzą pola bez zmian.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from openpyxl.utils import column_index_from_string

from .activity_legend import AMOUNT_COLUMN, FillColour
from .collective_layout import QUANTITY_LETTERS
from .order_facts import legend_colour
from .workbook_files import DataCell, DataRow

_COLUMNS: Final = tuple(column_index_from_string(column) - 1 for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN))
_FOR_WORKER: Final[Mapping[FillColour, int | None]] = {FillColour.RED: None, FillColour.GREEN: 1}
"""Kolor pola → wartość pola w Rozliczeniu pracownika (``None``: puste)."""


def for_worker(rows: Sequence[DataRow]) -> list[DataRow]:
    """Wiersze danych, w których Czerwone pole jest puste i bez Hiperłącza, a Zielone pole ma 1, oba bez wypełnienia.

    Pole zmienia się bez względu na to, co w nim stoi (liczba, 0, tekst, formuła); kolor czcionki, pogrubienie i
    kursywa pola zostają, a Hiperłącze zostaje przy wartości 1 Zielonego pola, jak przy każdej wartości (GLOSSARY
    „Hiperłącze”).
    """

    return [_for_worker(row) for row in rows]


def is_green(cell: DataCell) -> bool:
    """Czy komórka Ilości usług albo ``AS`` Wiersza danych jest Zielonym polem (kolumnę zna wołający)."""

    return legend_colour(cell.highlights.fill) is FillColour.GREEN


def _for_worker(row: DataRow) -> DataRow:
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
