"""Znacznik efenix: jasnofioletowe wypełnienie komórki ``ADRES``, którym Wycena w efenix oznacza gotowe zlecenie.

Kolor ma jednego właściciela, ``MARK_RGB``: Przebieg rozliczeń go rozpoznaje, a Wycena w efenix ma brać z niego
kolor zapisu, bez osobnej kopii. Znacznik nie jest Wyróżnieniem, więc Przebieg rozliczeń zdejmuje go z Wierszy danych w drodze do
Rozliczenia pracownika (``without_efenix_mark``), a Plik zbiorczy dalej go ma. Inne Wyróżnienia tej komórki, inne
wypełnienia ``ADRES`` i ten sam kolor w innej kolumnie zostają.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from openpyxl.styles.fills import Fill, PatternFill

from .preparation_register import ADDRESS
from .workbook_files import DataRow
from .worker_config import normalize_text

MARK_RGB: Final = "E0CCFF"
"""RGB Znacznika efenix: jednolite wypełnienie w tym kolorze, bez względu na kanał alfa, który Excel pomija."""


def without_efenix_mark(header: Mapping[str, int], rows: Sequence[DataRow]) -> list[DataRow]:
    """Wiersze danych, w których ``ADRES`` ze Znacznikiem efenix nie ma wypełnienia, a reszta Wyróżnień zostaje.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1. Bez nagłówka ``ADRES`` nie ma komórki, w której
    stoi Znacznik, więc nic się nie zmienia.
    """

    address = header.get(normalize_text(ADDRESS.target_header))
    if address is None:
        return list(rows)
    return [_unmarked(row, address - 1) for row in rows]


def _unmarked(row: DataRow, index: int) -> DataRow:
    cell = row.cells[index]
    if not _is_mark(cell.highlights.fill):
        return row
    cells = list(row.cells)
    cells[index] = cell._replace(highlights=replace(cell.highlights, fill=None))
    return replace(row, cells=tuple(cells))


def _is_mark(fill: Fill | None) -> bool:
    if not isinstance(fill, PatternFill) or fill.patternType != "solid" or fill.fgColor.type != "rgb":
        return False
    return str(fill.fgColor.rgb).upper().endswith(MARK_RGB)
