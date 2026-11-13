"""Ilości tylko dla INEA (ADR 0018): komórki Ilości usług, które Przebieg rozliczeń zostawia puste w Rozliczeniu pracownika.

INEA płaci za nie tacie przy każdym takim zleceniu, ale Wykonawca tej pracy nie wykonuje. Które komórki zostają puste,
mówią reguły „zostaw pustą w Rozliczeniu pracownika” Reguł ilości (ADR 0033), liczone silnikiem na treści zlecenia
każdego Wiersza danych, także bez daty w ``DATA``. Czyszczone są tylko Wiersze danych w drodze do Rozliczenia
pracownika: Plik zbiorczy i Kontrola ilości dalej widzą te ilości.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Final

from openpyxl.utils import column_index_from_string

from .order_facts import MissingHeaders, order_contents
from .quantity_engine import QuantityRules, evaluate
from .quantity_rules import QuantityColumn
from .register_columns import DEVICES
from .workbook_files import DataRow, is_blank
from .text import normalize_text

Cleared = Mapping[str, int]
"""Kolumna reguły „zostaw pustą” → liczba wyczyszczonych komórek, które miały wartość (także 0); każda kolumna
``QuantityRules.leave_empty_columns`` w jej kolejności, także z liczbą 0."""


def without_inea_only(
    header: Mapping[str, int], rows: Sequence[DataRow], rules: QuantityRules
) -> tuple[list[DataRow], Cleared]:
    """Wiersze danych bez Ilości tylko dla INEA według ``rules`` i liczba wyczyszczonych komórek w każdej kolumnie.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1. Wyczyszczona komórka zostaje z Wyróżnieniami i
    formatem liczby, jak po skasowaniu liczby w Excelu. Bez nagłówka kolumny treści zlecenia (``UMOWA``,
    ``URZĄDZENIA``, ``CZYNNOŚCI``, ``DATA``) nie wiadomo, gdzie czytać zlecenie, więc nic nie jest czyszczone.
    """

    cleared = dict.fromkeys(rules.leave_empty_columns, 0)
    contents = order_contents(header, rows)
    if isinstance(contents, MissingHeaders):
        return list(rows), cleared
    result: list[DataRow] = []
    for row, content in zip(rows, contents, strict=True):
        cells = list(row.cells)
        for column in evaluate(rules, content).leave_empty:
            index = column_index_from_string(column) - 1
            cleared[column] += not is_blank(cells[index].value)
            # Hiperłącze komórka ma tylko przy wartości (``DataCell``).
            cells[index] = cells[index]._replace(value=None, hyperlink=None)
        result.append(replace(row, cells=tuple(cells)))
    return result, cleared


_INEA_ONLY: Final[Mapping[QuantityColumn, str]] = MappingProxyType(
    {QuantityColumn.AP: "gniazdo", QuantityColumn.AK: "technicolor"}
)
"""Kolumna → słowo w URZĄDZENIA (bez względu na wielkość liter i resztę tekstu), przy którym komórka zostaje pusta."""


def legacy_without_inea_only(header: Mapping[str, int], rows: Sequence[DataRow]) -> tuple[list[DataRow], Cleared]:
    """Ilości tylko dla INEA sprzed silnika Reguł ilości: tylko wyrocznia testu własności stare = nowe (#1471 PR 3 ją usuwa).

    Bez nagłówka URZĄDZENIA nic nie jest czyszczone.
    """

    cleared: dict[str, int] = dict.fromkeys(_INEA_ONLY, 0)
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
                cells[index] = cells[index]._replace(value=None, hyperlink=None)
        result.append(replace(row, cells=tuple(cells)))
    return result, cleared
