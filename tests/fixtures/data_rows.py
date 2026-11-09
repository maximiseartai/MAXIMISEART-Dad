"""Wiersze danych Pliku zbiorczego i wiersze Rejestru zleceń zbudowane w teście, tak jak dają je czytniki."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from types import MappingProxyType

from rozliczenia.collective_layout import DATA_ROW_COLUMNS, FIRST_DATA_ROW, LOOK_COLUMNS
from rozliczenia.highlights import PLAIN, Highlights
from rozliczenia.hyperlinks import Hyperlink
from rozliczenia.register_columns import TARGET_HEADERS
from rozliczenia.workbook_files import DataCell, DataRow, ExcelRow, RegisterRow


def data_row(
    values: ExcelRow,
    highlights: Mapping[int, Highlights] | None = None,
    *,
    number: int = FIRST_DATA_ROW,
    links: Mapping[int, str] | None = None,
) -> DataRow:
    """Wiersz danych A:AT z ``values`` od A; ``highlights`` i ``links`` po kolumnie od 1, reszta komórek bez nich.

    Format liczby to format daty przy dacie w kolumnach wyglądu A:L, a poza tym ogólny.
    """

    padded = tuple(values) + (None,) * (len(DATA_ROW_COLUMNS) - len(values))
    return DataRow(
        number,
        tuple(
            DataCell(
                value,
                (highlights or {}).get(column, PLAIN),
                "m/d/yy h:mm" if column in LOOK_COLUMNS and isinstance(value, (date, time)) else "General",
                Hyperlink((links or {})[column]) if column in (links or {}) else None,
            )
            for column, value in enumerate(padded, start=1)
        ),
    )


def register_row(values: Mapping[str, str], *, number: int = 2) -> RegisterRow:
    """Wiersz Rejestru zleceń z ``values`` pod nagłówkami docelowymi, bez Wyróżnień; inne nagłówki mają pustą komórkę."""

    return RegisterRow(
        number,
        MappingProxyType({header: DataCell(values.get(header), PLAIN, "General", None) for header in TARGET_HEADERS}),
    )
