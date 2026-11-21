from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .activity_legend import AMOUNT_COLUMN, ActivityLegend, DescriptionRead, FillColour, WithCodes
from .client_data import shown
from .collective_layout import QUANTITY_LETTERS
from .quantity_engine import (
    DESCRIPTION_COLUMNS,
    FromDescription,
    OrderContent,
    Quantities,
    QuantityRules,
    RuleResult,
    WithoutRule,
    evaluated,
    is_fault,
)
from .workbook_files import is_blank


class FillKind(StrEnum):
    """Rodzaj Ilości do uzupełnienia, który ma listę wierszy."""

    WITHOUT_RULE = "without_rule"
    FROM_DESCRIPTION = "from_description"


_KINDS: Final[Mapping[type[RuleResult], FillKind]] = {
    WithoutRule: FillKind.WITHOUT_RULE,
    FromDescription: FillKind.FROM_DESCRIPTION,
}


@dataclass(frozen=True)
class ToolEntry:
    rules: RuleResult | None
    read: DescriptionRead
    quantities: Quantities
    amount: int
    fills: Mapping[str, FillColour]
    columns: frozenset[str]

    @property
    def closed(self) -> bool:
        return isinstance(self.read, WithCodes)

    @property
    def kind(self) -> FillKind | None:
        kind = None if self.rules is None else _KINDS.get(type(self.rules))
        if kind is FillKind.FROM_DESCRIPTION and self.closed:
            return None
        return kind


_NONE: Final[Mapping[str, FillColour]] = MappingProxyType({})


def description(cell: object) -> str:
    return "" if is_blank(cell) else shown(cell)


def tool_entry(content: OrderContent | None, completed: str, rules: QuantityRules, legend: ActivityLegend) -> ToolEntry:
    result = evaluated(rules, content)
    read = legend.read(completed, fault=is_fault(result))
    by_rules: Quantities = {} if result is None else result.quantities
    compared = () if result is None else compared_columns(result, rules)
    by_legend: Quantities = {}
    colours = _NONE
    amount = 0
    columns = frozenset(compared)
    if isinstance(read, WithCodes):
        by_legend, amount, colours = read.quantities, read.amount, read.fills
        columns = frozenset((*compared, *read.quantities, *((AMOUNT_COLUMN,) if read.amount else ())))
    quantities = {
        column: by_rules.get(column, 0) + by_legend.get(column, 0)
        for column in QUANTITY_LETTERS
        if column in by_rules or column in by_legend
    }
    return ToolEntry(result, read, MappingProxyType(quantities), amount, colours, columns)


def compared_columns(rule: RuleResult, rules: QuantityRules) -> tuple[str, ...]:
    if isinstance(rule, FromDescription):
        return ()
    if isinstance(rule, WithoutRule):
        return rules.without_rule_columns
    return tuple(
        column for column in rules.rule_columns if column not in DESCRIPTION_COLUMNS or rule.quantities.get(column, 0)
    )
