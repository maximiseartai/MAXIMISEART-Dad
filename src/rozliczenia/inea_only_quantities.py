"""Ilości tylko dla INEA (ADR 0018): komórki Ilości usług, które Przebieg rozliczeń zostawia puste w Rozliczeniu pracownika.

INEA płaci za nie tacie przy każdym takim zleceniu, ale Wykonawca tej pracy nie wykonuje. Czyszczone są tylko
Wiersze danych w drodze do Rozliczenia pracownika: Plik zbiorczy i Kontrola ilości dalej widzą te ilości.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Final

from openpyxl.utils import column_index_from_string

from .register_columns import DEVICES
from .quantity_rules import QuantityColumn
from .workbook_files import DataRow, is_blank
from .text import normalize_text

_INEA_ONLY: Final[Mapping[QuantityColumn, str]] = MappingProxyType(
    {QuantityColumn.AP: "gniazdo", QuantityColumn.AK: "technicolor"}
)
"""Kolumna → słowo w URZĄDZENIA (bez względu na wielkość liter i resztę tekstu), przy którym komórka zostaje pusta."""

Cleared = Mapping[QuantityColumn, int]
"""Kolumna Ilości tylko dla INEA → liczba wyczyszczonych komórek, które miały wartość (także 0); każda kolumna, także
z liczbą 0."""


def without_inea_only(header: Mapping[str, int], rows: Sequence[DataRow]) -> tuple[list[DataRow], Cleared]:
    """Wiersze danych bez Ilości tylko dla INEA i liczba wyczyszczonych komórek w każdej kolumnie.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1. Wyczyszczona komórka zostaje z Wyróżnieniami i
    formatem liczby, jak po skasowaniu liczby w Excelu. Bez nagłówka URZĄDZENIA nie wiadomo, gdzie czytać zlecenie,
    więc nic nie jest czyszczone.
    """

    cleared = dict.fromkeys(_INEA_ONLY, 0)
    devices = header.get(normalize_text(DEVICES.target_header))
    if devices is None:
        return list(rows), cleared
    result: list[DataRow] = []
    for row in rows:
        text = normalize_text(row.cells[devices - 1].value)
        cells = list(row.cells)
        for column, word in _INEA_ONLY.items():
            if word in text:
                index = column_index_from_string(column) - 1
                cleared[column] += not is_blank(cells[index].value)
                # Hiperłącze komórka ma tylko przy wartości (``DataCell``).
                cells[index] = cells[index]._replace(value=None, hyperlink=None)
        result.append(replace(row, cells=tuple(cells)))
    return result, cleared
