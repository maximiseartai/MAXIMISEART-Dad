"""Treść Wiersza danych, która może opuścić komputer taty: reguła prywatności Kontroli ilości (ADR 0013, ADR 0015,
ADR 0038).

To jedyny typ z treścią komórek Pliku zbiorczego, który przeżywa silnik Przebiegu rozliczeń, i jedyne miejsce,
które wylicza dozwolone kolumny: UMOWA, URZĄDZENIA, CZYNNOŚCI i CZYNNOŚCI ZREALIZOWANE (po nagłówku z wiersza 17, pod
którym zapisuje je Przygotowanie), dzień tygodnia i godzina z DATA, N:AP i ``AS`` (po literze kolumny) oraz kolor
legendy w wypełnieniu kolumn, które może wypełnić Legenda czynności. Treść zlecenia
robią z komórek Reguły ilości (``OrderContent.of``), tak samo jak z Rejestru zleceń w Przygotowaniu; tę samą treść,
także bez daty w DATA, czytają Ilości tylko dla INEA Przebiegu (``order_contents``). Adres, numery
zlecenia i umowy, Wykonawca, data dzienna i reszta A:AT nie mają pola, więc nie da się ich wysłać przez ten typ. Tekst
wpisany przez tatę w komórce ilości i w ``AS`` też nie przechodzi: zostaje z niego „nieliczbowa”. Opis technika
(``completed``) wychodzi w Kontroli ilości tylko w wierszach, które wskazuje ``quantity_check.legend_row_check``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

from openpyxl.styles.colors import COLOR_INDEX, Color
from openpyxl.styles.fills import Fill, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter

from .activity_legend import AMOUNT_COLUMN, FILL_COLUMNS, FillColour
from .client_data import shown
from .collective_layout import QUANTITY_LETTERS
from .register_columns import ACTIVITIES, COMPLETED, CONTRACT, DATE, DEVICES, Column
from .quantity_engine import OrderContent
from .workbook_files import DataRow, cell_datetime, is_blank
from .text import normalize_text

NON_NUMERIC: Final = "nieliczbowa"
TataValue = int | Literal["nieliczbowa"]
"""Ilość taty: liczba (pusta komórka, 0 i ``"0"`` to 0; ``"2"`` i ``2.0`` to 2) albo „nieliczbowa” (formuła, słowo, 1.5)."""

_INPUTS: Final[tuple[Column, ...]] = (CONTRACT, DEVICES, ACTIVITIES, DATE)
_NO_FILLS: Final[Mapping[str, FillColour]] = MappingProxyType({})


@dataclass(frozen=True)
class OrderFacts:
    """Wiersz danych po filtrze prywatności."""

    content: OrderContent | None
    """Treść zlecenia dla Reguł ilości, zawsze z datą; ``None``, gdy ``DATA`` nie jest datą."""
    quantities: Mapping[str, TataValue]
    """Litera kolumny N:AP → ilość taty, tylko różna od 0."""
    completed: str = ""
    """Opis technika: tekst ``CZYNNOŚCI ZREALIZOWANE`` tak, jak go pokazuje Excel; pusta komórka albo brak nagłówka to
    ``""``."""
    amount: TataValue = 0
    """Kwota taty w ``AS`` (Uwagi - kwota), czytana jak ilość taty."""
    fills: Mapping[str, FillColour] = field(default=_NO_FILLS)
    """Kolumna, którą może wypełnić Legenda czynności (``FILL_COLUMNS``) → kolor legendy jej wypełnienia, tylko z
    wypełnieniem w kolorze legendy (``legend_colour``)."""

    def quantity(self, column: str) -> TataValue:
        return self.quantities.get(column, 0)


@dataclass(frozen=True)
class MissingHeaders:
    """W wierszu 17 Pliku zbiorczego nie ma nagłówka kolumny wejścia, więc nie wiadomo, gdzie ją czytać."""

    headers: tuple[str, ...]


CollectiveOrders = tuple[OrderFacts, ...] | MissingHeaders


def collective_orders(header: Mapping[str, int], rows: Sequence[DataRow]) -> CollectiveOrders:
    """Dozwolona treść każdego Wiersza danych.

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1.
    """

    contents = order_contents(header, rows)
    if isinstance(contents, MissingHeaders):
        return contents
    completed_index = header.get(normalize_text(COMPLETED.target_header))
    completed = None if completed_index is None else get_column_letter(completed_index)
    return tuple(
        OrderFacts(
            None if content.started is None else content,
            _quantities(row),
            _completed(_value(row, completed)),
            tata_value(row.value(AMOUNT_COLUMN)),
            _fills(row),
        )
        for content, row in zip(contents, rows, strict=True)
    )


def order_contents(
    header: Mapping[str, int], rows: Sequence[DataRow], required: tuple[Column, ...] = _INPUTS
) -> tuple[OrderContent, ...] | MissingHeaders:
    """Treść zlecenia każdego Wiersza danych, a przy ``DATA``, która nie jest datą, bez pory (``started`` ``None``).

    ``header``: znormalizowany nagłówek wiersza 17 → kolumna od 1. Bez nagłówka kolumny z ``required`` treści nie ma;
    kolumna treści spoza ``required`` bez nagłówka czyta się jak pusta komórka.
    """

    columns = {column: header.get(normalize_text(column.target_header)) for column in _INPUTS}
    missing = tuple(column.target_header for column in required if columns[column] is None)
    if missing:
        return MissingHeaders(missing)
    contract, devices, activities, started = (None if index is None else get_column_letter(index) for index in columns.values())
    return tuple(
        OrderContent.of(
            _value(row, contract), _value(row, devices), _value(row, activities), cell_datetime(_value(row, started))
        )
        for row in rows
    )


def _value(row: DataRow, letter: str | None) -> object:
    return None if letter is None else row.value(letter)


def tata_value(cell: object) -> TataValue:
    """Decyzja 11: puste i 0 to 0, liczba całkowita (także tekstem albo jako float) to ta liczba, reszta „nieliczbowa”."""

    if is_blank(cell):
        return 0
    if isinstance(cell, bool):
        return NON_NUMERIC
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float):
        return int(cell) if cell.is_integer() else NON_NUMERIC
    if isinstance(cell, Decimal):
        return int(cell) if cell.is_finite() and cell == cell.to_integral_value() else NON_NUMERIC
    if isinstance(cell, str):
        return _number_text(cell.strip())
    return NON_NUMERIC


def _number_text(text: str) -> TataValue:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return NON_NUMERIC
    return int(number) if number.is_integer() else NON_NUMERIC


def _quantities(row: DataRow) -> dict[str, TataValue]:
    values = {letter: tata_value(row.value(letter)) for letter in QUANTITY_LETTERS}
    return {letter: value for letter, value in values.items() if value != 0}


def _completed(cell: object) -> str:
    return "" if is_blank(cell) else shown(cell)


def _fills(row: DataRow) -> Mapping[str, FillColour]:
    colours = {column: legend_colour(row.cells[column_index_from_string(column) - 1].highlights.fill) for column in FILL_COLUMNS}
    return MappingProxyType({column: colour for column, colour in colours.items() if colour is not None})


def legend_colour(fill: Fill | None) -> FillColour | None:
    """Kolor legendy wypełnienia komórki: jednolite wypełnienie koloru Legendy czynności (po RGB albo indeksie palety);
    każde inne wypełnienie i brak wypełnienia to ``None``. To jedyny odczyt koloru komórki taty pod kątem legendy:
    Kontrola ilości i brama Legendy czynności biorą go z ``OrderFacts.fills``, a Przebieg rozliczeń z niego rozpoznaje
    Czerwone i zielone pole (``coloured_fields``).

    To lustro zapisu: w kolumnach za danymi wejściowymi Przygotowanie zostawia wygląd komórki Wzorca i kładzie na nim
    tylko wypełnienie legendy (``highlights.solid_fill``). Wypełnienie spoza palety legendy, np. białe tło motywu, które
    Wzorzec pliku zbiorczego taty ma w N–V i X każdego Wiersza danych, albo ręczne zaznaczenie, nie jest kolorem, który
    legenda mogłaby wpisać, więc Kontrola czyta je jak brak koloru."""

    if not isinstance(fill, PatternFill) or fill.patternType != "solid":
        return None
    rgb = _rgb(fill.fgColor)
    return next((colour for colour in FillColour if rgb is not None and rgb == colour.argb[-6:]), None)


def _rgb(color: Color | None) -> str | None:
    if color is None:
        return None
    if color.type == "rgb" and isinstance(color.rgb, str):
        return color.rgb[-6:].upper()
    if color.type == "indexed" and isinstance(color.indexed, int) and color.indexed < len(COLOR_INDEX):
        return COLOR_INDEX[color.indexed][-6:].upper()
    return None
