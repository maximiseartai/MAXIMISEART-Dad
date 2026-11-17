"""Wpis narzędzia: to, co narzędzie wyznacza w Wierszu danych Pliku zbiorczego z Reguł ilości i Legendy czynności.

Jedyna operacja ``tool_entry`` to czysta funkcja bez plików: z treści zlecenia, opisu technika (``CZYNNOŚCI
ZREALIZOWANE``), Reguł ilości i Legendy czynności daje Ilości usług w ``N:AP`` (reguły i legenda razem, legenda tylko w
wierszu z samych Kodów czynności), kwotę w ``AS``, Wyróżnienia legendy, kolumny narzędzia i rodzaj Ilości do
uzupełnienia. Liczą nią Przygotowanie pliku zbiorczego (zapis i ostrzeżenia), Kontrola ilości (oczekiwane wartości) i
Ilości do uzupełnienia, więc to, co Przygotowanie wpisuje, i to, czego oczekuje Kontrola, liczy jeden rachunek.

Wiersz, którego ``DATA`` nie jest datą, nie ma wyniku Reguł ilości (``rules`` ``None``): jego wpis to sama legenda, a
wiersz nie ma rodzaju. Treść bez pory (``OrderContent.started`` ``None``) liczy się tak samo jak brak treści, bo typ
``OrderContent`` ją dopuszcza, choć ``order_facts`` daje wtedy ``None``, a Przygotowanie zawsze ma datę. Kolumny
narzędzia to kolumny, które narzędzie w tym wierszu wpisało albo porównuje Regułami ilości: wpis taty obok nich robi
wiersz zrobionym. Kontrola ilości porównuje szerzej (każdą kolumnę legendy i ``AS`` w wierszu z samych kodów, ADR
0038); ten zakres należy do niej (``quantity_check.legend_row_check``).

Właścicielem nie jest ``quantity_check``, bo Przygotowanie (pisarz) zależałoby wtedy od Kontroli (sprawdzającego), a
rodzaj Ilości do uzupełnienia i odczyt reguł z legendą zostałyby w dwóch i trzech miejscach: suma w jednym miejscu nie
wystarcza, gdy wołający dalej składa wiersz z surowych wyników.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .activity_legend import AMOUNT_COLUMN, ActivityLegend, CodesOnly, DescriptionRead, FillColour
from .collective_layout import QUANTITY_LETTERS
from .quantity_engine import (
    DESCRIPTION_COLUMNS,
    FromDescription,
    OrderContent,
    Quantities,
    QuantityRules,
    RuleResult,
    WithoutRule,
    evaluate,
)


class FillKind(StrEnum):
    """Rodzaj Ilości do uzupełnienia, który ma listę wierszy."""

    WITHOUT_RULE = "without_rule"
    """Nieznane ``URZĄDZENIA``: Reguły ilości dały najwyżej ilości reguł dla składnika spoza listy (z Wydania V, T i N)."""
    FROM_DESCRIPTION = "from_description"
    """Prewencja, niedostępność usług albo puste ``URZĄDZENIA``: Reguły ilości nie dały nic."""


_KINDS: Final[Mapping[type[RuleResult], FillKind]] = {
    WithoutRule: FillKind.WITHOUT_RULE,
    FromDescription: FillKind.FROM_DESCRIPTION,
}


@dataclass(frozen=True)
class ToolEntry:
    """Wpis narzędzia w jednym Wierszu danych (zob. opis modułu)."""

    rules: RuleResult | None
    """Wynik Reguł ilości; ``None``: ``DATA`` nie jest datą."""
    read: DescriptionRead
    quantities: Quantities
    """Kolumna ``N:AP`` → Ilość usług reguł i legendy razem, w kolejności kolumn."""
    amount: int
    """Kwota w ``AS``; 0: bez kwoty."""
    fills: Mapping[str, FillColour]
    columns: frozenset[str]
    """Kolumny narzędzia (``N:AP`` i ``AS``): porównywane Regułami ilości, wpisane legendą, ``AS`` przy kwocie."""

    @property
    def closed(self) -> bool:
        """Opis to same Kody czynności, więc wiersz nie czeka na tatę w kolumnach z opisu technika (ADR 0038)."""

        return isinstance(self.read, CodesOnly)

    @property
    def kind(self) -> FillKind | None:
        """Rodzaj Ilości do uzupełnienia, gdy wiersz czeka na tatę; wiersz z opisu z samych kodów nie czeka."""

        kind = None if self.rules is None else _KINDS.get(type(self.rules))
        if kind is FillKind.FROM_DESCRIPTION and self.closed:
            return None
        return kind


_NONE: Final[Mapping[str, FillColour]] = MappingProxyType({})


def tool_entry(content: OrderContent | None, completed: str, rules: QuantityRules, legend: ActivityLegend) -> ToolEntry:
    """Wpis narzędzia dla treści ``content`` (``None`` albo bez pory: bez Reguł ilości) i opisu technika ``completed``."""

    result = None if content is None or content.started is None else evaluate(rules, content)
    read = legend.read(completed)
    by_rules: Quantities = {} if result is None else result.quantities
    compared = () if result is None else compared_columns(result, rules)
    by_legend: Quantities = {}
    colours = _NONE
    amount = 0
    columns = frozenset(compared)
    if isinstance(read, CodesOnly):
        by_legend, amount, colours = read.quantities, read.amount, read.fills
        columns = frozenset((*compared, *read.quantities, *((AMOUNT_COLUMN,) if read.amount else ())))
    quantities = {
        column: by_rules.get(column, 0) + by_legend.get(column, 0)
        for column in QUANTITY_LETTERS
        if column in by_rules or column in by_legend
    }
    return ToolEntry(result, read, MappingProxyType(quantities), amount, colours, columns)


def compared_columns(rule: RuleResult, rules: QuantityRules) -> tuple[str, ...]:
    """Kolumny Reguł ilości ``rules``, w których Kontrola porównuje wynik reguł z wpisami taty (decyzje 9 i 10)."""

    if isinstance(rule, FromDescription):
        return ()
    if isinstance(rule, WithoutRule):
        return rules.without_rule_columns
    return tuple(
        column for column in rules.rule_columns if column not in DESCRIPTION_COLUMNS or rule.quantities.get(column, 0)
    )
