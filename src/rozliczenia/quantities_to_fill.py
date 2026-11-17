"""Ilości do uzupełnienia: wiersze Pliku zbiorczego, w których Ilości usług wpisuje tata, i czy już coś wpisał.

Czysta funkcja ``quantities_to_fill`` na Wierszach danych zapisanego Pliku zbiorczego, przeliczana przy każdym
odczycie; nic nie jest przechowywane. Rodzaj wiersza i kolumny narzędzia daje Wpis narzędzia (``tool_entry``) na
regułach podanych przy odczycie: rodzaj wynika tylko z typu wyniku Reguł ilości, a kolumny narzędzia to kolumny
porównywane przez Kontrolę ilości (``compared_columns``) i kolumny, w które Legenda czynności wpisuje z ``CZYNNOŚCI
ZREALIZOWANE`` wiersza (ADR 0038). Puste i 0 to to samo, jak w Kontroli ilości.

Wiersz z opisu, którego ``CZYNNOŚCI ZREALIZOWANE`` mają Kody czynności bez Błędu opisu, także obok zwykłego opisu, nie
czeka na tatę: ilości z opisu technika wpisała legenda. Wiersz bez żadnego kodu i wiersz z Błędem opisu czekają na
tatę, bo legenda nic w nich nie wpisała. Wiersz
bez reguły czeka mimo to, bo legenda nie wpisuje ilości z ``URZĄDZENIA``.
Wiersz bez reguły jest zrobiony, gdy ma ilość różną od 0 poza kolumnami narzędzia (z Wydania V, T i N oraz kolumny
legendy), a wiersz z opisu, gdy ma ją gdziekolwiek w N:AP poza kolumnami legendy. Każda komórka N:AP i ``AS`` wiersza
pokazuje wartość z pliku: w kolumnie narzędzia jako kolumnę narzędzia, która nie robi wiersza zrobionym, a w
pozostałych jako wpis taty; kwota taty w ``AS`` się pokazuje, ale wiersza nie robi, bo nie jest Ilością usług. Wyniku
Reguł ilości i legendy obok wartości z pliku nie ma, bo porównanie ich to Kontrola ilości, która zostaje dla Maksa.
Wiersz z ``DATA``, która nie jest datą, nie ma wyniku reguł, więc nie trafia do żadnego rodzaju. Kolumny z opisu
technika mają liczbę wierszy, które zamknęła legenda, liczbę pozostałych i w każdej kolumnie liczbę wierszy, w których
tata coś wpisał poza kolumnami narzędzia.
Po Przebiegu rozliczeń okresu wiersz z listą bez wpisu taty nie czeka już na tatę: jest „bez ilości”.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .activity_legend import AMOUNT_COLUMN, ActivityLegend
from .collective_layout import QUANTITY_LETTERS
from .order_facts import OrderFacts, TataValue
from .quantity_engine import DESCRIPTION_COLUMNS, QuantityRules
from .register_columns import ACTIVITIES, COMPLETED, DEVICES, WORKER, Column
from .tool_entry import FillKind, tool_entry


def fill_hint(kind: FillKind, rules: QuantityRules) -> str:
    """Podpowiedź dla taty, co wpisuje w wierszach rodzaju ``kind``: te same kolumny, które robią wiersz zrobionym."""

    match kind:
        case FillKind.WITHOUT_RULE:
            columns = rules.without_rule_columns
            if not columns:
                return "Dopisz ilości."
            listed = columns[0] if len(columns) == 1 else f"{', '.join(columns[:-1])} i {columns[-1]}"
            return f"Dopisz ilości poza {listed}."
        case FillKind.FROM_DESCRIPTION:
            return "Wpisz ilości według opisu technika."


TEXT_COLUMNS: Final[tuple[Column, ...]] = (WORKER, DEVICES, ACTIVITIES, COMPLETED)
"""Kolumny Pliku zbiorczego, po których tata rozpoznaje zlecenie na stronie rodzaju (ADR 0016), w kolejności strony;
``CZYNNOŚCI ZREALIZOWANE`` to opis technika, który Legenda czynności czyta z ``OrderFacts.completed``."""
CELL_COLUMNS: Final = (*QUANTITY_LETTERS, AMOUNT_COLUMN)
"""Kolumny komórek wiersza do uzupełnienia: Ilości usług N:AP i ``AS`` (Uwagi - kwota), w którą wpisuje Legenda czynności."""

RowTexts = tuple[str, ...]
"""Teksty Wiersza danych w kolumnach ``TEXT_COLUMNS`` po kolei; pusta komórka to ``""``.

Trafiają tylko do przeglądarki taty, nie przez ``OrderFacts``; opis technika ma tam osobne pole, które Kontrola ilości
wysyła tylko w wierszach wskazanych przez ``quantity_check.legend_row_check``."""


@dataclass(frozen=True)
class NumberedOrder:
    """Wiersz danych Pliku zbiorczego: numer wiersza w pliku, jego treść po filtrze prywatności, teksty strony rodzaju i
    kwota w ``AS``, która jak teksty trafia tylko do przeglądarki taty."""

    number: int
    order: OrderFacts
    texts: RowTexts
    amount: TataValue


class CellSource(StrEnum):
    """Czyją wartość pokazuje komórka N:AP wiersza do uzupełnienia."""

    TOOL = "tool"
    """Kolumna, którą wyznaczają Reguły ilości albo Legenda czynności: wartość z pliku, także 0, nie robi wiersza
    zrobionym."""
    TATA = "tata"
    """Wartość taty różna od 0 w kolumnie, której narzędzie nie wyznacza: w N:AP robi wiersz zrobionym, w ``AS`` nie."""
    EMPTY = "empty"
    """Kolumna, której narzędzie nie wyznacza, pusta albo z 0."""


@dataclass(frozen=True)
class QuantityCell:
    source: CellSource
    value: TataValue
    """Wartość komórki w pliku; w ``EMPTY`` zawsze 0."""


class RowState(StrEnum):
    TO_FILL = "to_fill"
    """Bez komórki ``TATA`` w N:AP, a Przebiegu rozliczeń okresu jeszcze nie było."""
    DONE = "done"
    """Choć jedna komórka ``TATA`` w N:AP."""
    WITHOUT_QUANTITY = "without_quantity"
    """Bez komórki ``TATA`` w N:AP po Przebiegu rozliczeń okresu: wiersz został na zerach („bez ilości”)."""


@dataclass(frozen=True)
class RowToFill:
    number: int
    """Numer wiersza w Pliku zbiorczym z tego odczytu, więc usunięcie wiersza w Excelu przenumerowuje listę."""
    texts: RowTexts
    cells: tuple[QuantityCell, ...]
    """Każda kolumna ``CELL_COLUMNS`` po kolei."""
    state: RowState

    @property
    def done(self) -> bool:
        return self.state is RowState.DONE


@dataclass(frozen=True)
class KindToFill:
    kind: FillKind
    rows: tuple[RowToFill, ...]
    """W kolejności z pliku, czyli rosnąco po numerze wiersza."""

    @property
    def done(self) -> bool:
        """Każdy wiersz zrobiony; rodzaj bez wierszy jest zrobiony."""

        return all(row.done for row in self.rows)


@dataclass(frozen=True)
class DescriptionRows:
    """Wiersze Pliku zbiorczego w kolumnach z opisu technika: ``by_legend`` z Kodami czynności bez Błędu opisu, więc nie
    czekają na tatę, a ``for_tata`` pozostałe (bez żadnego kodu albo z Błędem opisu)."""

    by_legend: int
    for_tata: int


@dataclass(frozen=True)
class QuantitiesToFill:
    kinds: tuple[KindToFill, ...]
    """Każdy ``FillKind`` w kolejności z ``FillKind``, także bez wierszy."""
    description_rows: DescriptionRows
    description_filled: Mapping[str, int]
    """Każda kolumna z opisu technika (``DESCRIPTION_COLUMNS``) → liczba wierszy, w których tata coś w niej wpisał, poza
    wierszami, w których tę kolumnę wyznacza narzędzie."""

    @property
    def without_quantity(self) -> tuple[int, ...]:
        """Numery wierszy z listą, w których tata nic jeszcze nie wpisał, rosnąco: wiersze „bez ilości” Gotowości."""

        return tuple(sorted(row.number for kind in self.kinds for row in kind.rows if not row.done))


def quantities_to_fill(
    rows: Sequence[NumberedOrder], rules: QuantityRules, legend: ActivityLegend, *, settled: bool
) -> QuantitiesToFill:
    """``rules`` i ``legend``: Reguły ilości i Legenda czynności, którymi liczyć; ``settled``: Przebieg rozliczeń okresu
    się odbył, więc wiersz bez wpisu taty jest „bez ilości”."""

    listed: dict[FillKind, list[RowToFill]] = {kind: [] for kind in FillKind}
    filled: Counter[str] = Counter()
    by_legend = 0
    for row in rows:
        entry = tool_entry(row.order.content, row.order.completed, rules, legend)
        by_legend += entry.closed
        filled.update(column for column in DESCRIPTION_COLUMNS if row.order.quantity(column) != 0 and column not in entry.columns)
        if entry.kind is None:
            continue
        listed[entry.kind].append(_row(row, entry.columns, settled=settled))
    return QuantitiesToFill(
        tuple(KindToFill(kind, tuple(found)) for kind, found in listed.items()),
        DescriptionRows(by_legend, len(rows) - by_legend),
        {column: filled[column] for column in DESCRIPTION_COLUMNS},
    )


def _row(row: NumberedOrder, tool: frozenset[str], *, settled: bool) -> RowToFill:
    quantities = tuple(_cell(row.order.quantity(column), column in tool) for column in QUANTITY_LETTERS)
    if any(cell.source is CellSource.TATA for cell in quantities):
        state = RowState.DONE
    else:
        state = RowState.WITHOUT_QUANTITY if settled else RowState.TO_FILL
    return RowToFill(row.number, row.texts, (*quantities, _cell(row.amount, AMOUNT_COLUMN in tool)), state)


def _cell(value: TataValue, by_tool: bool) -> QuantityCell:
    if by_tool:
        return QuantityCell(CellSource.TOOL, value)
    return QuantityCell(CellSource.EMPTY if value == 0 else CellSource.TATA, value)
