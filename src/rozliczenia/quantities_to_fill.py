"""Ilości do uzupełnienia: wiersze Pliku zbiorczego, w których Ilości usług wpisuje tata, i czy już coś wpisał.

Czysta funkcja ``quantities_to_fill`` na Wierszach danych zapisanego Pliku zbiorczego, przeliczana przy każdym
odczycie; nic nie jest przechowywane. Rodzaj wiersza wynika tylko z typu wyniku Reguł ilości (``evaluate``), a
kolumny, w których wpis taty się liczy, to kolumny poza porównywanymi przez Kontrolę ilości (``compared_columns``),
więc ta lista i Kontrola ilości się nie rozjadą. Puste i 0 to to samo, jak w Kontroli ilości.

Wiersz bez reguły jest zrobiony, gdy ma ilość różną od 0 poza V, T i N, a wiersz z opisu, gdy ma ją gdziekolwiek
w N:AP. Każda komórka N:AP wiersza pokazuje wartość z pliku: w kolumnie, którą wyznaczają Reguły ilości, jako
kolumnę narzędzia, która nie robi wiersza zrobionym, a w pozostałych jako wpis taty. Wyniku Reguł ilości obok
wartości z pliku nie ma, bo porównanie ich to Kontrola ilości, która zostaje dla Maksa.
Wiersz z ``DATA``, która nie jest datą, nie ma wyniku reguł, więc nie trafia do żadnego rodzaju. Kolumny z opisu
technika mają tylko liczbę wierszy, w których tata coś wpisał, wziętą z Kontroli ilości tych samych wierszy.
Po Przebiegu rozliczeń okresu wiersz z listą bez wpisu taty nie czeka już na tatę: jest „bez ilości”.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .collective_layout import QUANTITY_LETTERS
from .order_facts import OrderFacts, TataValue
from .quantity_check import QuantityCheck, check, compared_columns
from .quantity_rules import DESCRIPTION_COLUMNS, FromDescription, RuleResult, WithoutRule, evaluate


class FillKind(StrEnum):
    """Rodzaj Ilości do uzupełnienia, który ma listę wierszy."""

    WITHOUT_RULE = "without_rule"
    """Nieznane ``URZĄDZENIA``: Reguły ilości dały najwyżej V, T i N."""
    FROM_DESCRIPTION = "from_description"
    """Prewencja, niedostępność usług albo puste ``URZĄDZENIA``: Reguły ilości nie dały nic."""


_KINDS: Final[Mapping[type[RuleResult], FillKind]] = {
    WithoutRule: FillKind.WITHOUT_RULE,
    FromDescription: FillKind.FROM_DESCRIPTION,
}


@dataclass(frozen=True)
class RowTexts:
    """Teksty Wiersza danych, po których tata rozpoznaje zlecenie na stronie rodzaju (ADR 0016).

    Trafiają tylko do przeglądarki taty, nigdy do ``OrderFacts``, więc nie wychodzą z komputera: ani w Kontroli
    ilości, ani w Logach Uruchomienia. Pusta komórka to ``""``.
    """

    worker: str
    devices: str
    activities: str
    completed: str
    """``CZYNNOŚCI ZREALIZOWANE``: opis technika."""


@dataclass(frozen=True)
class NumberedOrder:
    """Wiersz danych Pliku zbiorczego: numer wiersza w pliku, jego treść po filtrze prywatności i teksty strony rodzaju."""

    number: int
    order: OrderFacts
    texts: RowTexts


class CellSource(StrEnum):
    """Czyją wartość pokazuje komórka N:AP wiersza do uzupełnienia."""

    TOOL = "tool"
    """Kolumna, którą wyznaczają Reguły ilości: wartość z pliku, także 0, nie robi wiersza zrobionym."""
    TATA = "tata"
    """Ilość taty różna od 0 w kolumnie, której Reguły ilości nie wyznaczają: robi wiersz zrobionym."""
    EMPTY = "empty"
    """Kolumna, której Reguły ilości nie wyznaczają, pusta albo z 0."""


@dataclass(frozen=True)
class QuantityCell:
    source: CellSource
    value: TataValue
    """Wartość komórki w pliku; w ``EMPTY`` zawsze 0."""


class RowState(StrEnum):
    TO_FILL = "to_fill"
    """Bez komórki ``TATA``, a Przebiegu rozliczeń okresu jeszcze nie było."""
    DONE = "done"
    """Choć jedna komórka ``TATA``."""
    WITHOUT_QUANTITY = "without_quantity"
    """Bez komórki ``TATA`` po Przebiegu rozliczeń okresu: wiersz został na zerach („bez ilości”)."""


@dataclass(frozen=True)
class RowToFill:
    number: int
    """Numer wiersza w Pliku zbiorczym z tego odczytu, więc usunięcie wiersza w Excelu przenumerowuje listę."""
    texts: RowTexts
    cells: tuple[QuantityCell, ...]
    """Każda kolumna N:AP po kolei."""
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
class QuantitiesToFill:
    kinds: tuple[KindToFill, ...]
    """Każdy ``FillKind`` w kolejności z ``FillKind``, także bez wierszy."""
    description_filled: Mapping[str, int]
    """Każda kolumna z opisu technika (``DESCRIPTION_COLUMNS``) → liczba wierszy, w których tata coś wpisał."""

    @property
    def without_quantity(self) -> tuple[int, ...]:
        """Numery wierszy z listą, w których tata nic jeszcze nie wpisał, rosnąco: wiersze „bez ilości” Gotowości."""

        return tuple(sorted(row.number for kind in self.kinds for row in kind.rows if not row.done))


def quantities_to_fill(rows: Sequence[NumberedOrder], *, settled: bool) -> QuantitiesToFill:
    """``settled``: Przebieg rozliczeń okresu się odbył, więc wiersz bez wpisu taty jest „bez ilości”."""

    listed: dict[FillKind, list[RowToFill]] = {kind: [] for kind in FillKind}
    for row in rows:
        content = row.order.content
        if content is None:
            continue
        rule = evaluate(content)
        kind = _KINDS.get(type(rule))
        if kind is not None:
            listed[kind].append(_row(row, rule, settled=settled))
    control = check(tuple(row.order for row in rows))
    assert isinstance(control, QuantityCheck)  # ``check`` nie porównuje tylko przy brakujących nagłówkach
    return QuantitiesToFill(
        tuple(KindToFill(kind, tuple(found)) for kind, found in listed.items()),
        {column: control.description_filled[column] for column in DESCRIPTION_COLUMNS},
    )


def _row(row: NumberedOrder, rule: RuleResult, *, settled: bool) -> RowToFill:
    cells = _cells(row.order, rule)
    if any(cell.source is CellSource.TATA for cell in cells):
        state = RowState.DONE
    else:
        state = RowState.WITHOUT_QUANTITY if settled else RowState.TO_FILL
    return RowToFill(row.number, row.texts, cells, state)


def _cells(order: OrderFacts, rule: RuleResult) -> tuple[QuantityCell, ...]:
    compared = compared_columns(rule)
    return tuple(_cell(order.quantity(column), column in compared) for column in QUANTITY_LETTERS)


def _cell(value: TataValue, by_rules: bool) -> QuantityCell:
    if by_rules:
        return QuantityCell(CellSource.TOOL, value)
    return QuantityCell(CellSource.EMPTY if value == 0 else CellSource.TATA, value)
