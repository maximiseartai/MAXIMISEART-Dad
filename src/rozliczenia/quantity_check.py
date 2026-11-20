from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from .activity_legend import (
    AMOUNT_COLUMN,
    ActivityLegend,
    ColumnByNumber,
    DescriptionError,
    DescriptionRead,
    FillColour,
    FixedColumn,
    WithCodes,
    problem_text,
)
from .text import WEEKDAY_LABELS, plural
from .collective_layout import HEADER_ROW, QUANTITY_LETTERS
from .order_facts import CollectiveOrders, MissingHeaders, OrderFacts, TataValue
from .quantity_engine import (
    DESCRIPTION_COLUMNS,
    FromDescription,
    OrderContent,
    QuantityRules,
    RuleResult,
    ServiceQuantities,
    WeekTime,
    WithoutRule,
    evaluate,
)
from .tool_entry import compared_columns, tool_entry


@dataclass(frozen=True)
class Difference:
    devices: str
    activities: str
    contract: str
    weekday: int
    hour: int
    column: str
    rule: int
    tata: TataValue


@dataclass
class Unruled:
    rows: int = 0
    differences: Counter[Difference] = field(default_factory=Counter)
    values: Counter[tuple[str, TataValue]] = field(default_factory=Counter)


@dataclass
class QuantityCheck:
    other_columns: tuple[str, ...]
    rows: int = 0
    compared: int = 0
    from_description: int = 0
    undated: int = 0
    differences: Counter[Difference] = field(default_factory=Counter)
    unruled: dict[str, Unruled] = field(default_factory=lambda: defaultdict(Unruled))
    description_filled: Counter[str] = field(default_factory=Counter)
    other_filled: Counter[str] = field(default_factory=Counter)
    coded: int = 0
    coded_matching: int = 0
    legend_differences: dict[tuple[str, ...], LegendGroup] = field(default_factory=lambda: defaultdict(LegendGroup))
    uncoded_entries: Counter[tuple[str, Entry]] = field(default_factory=Counter)
    description_error_rows: int = 0
    description_errors: Counter[str] = field(default_factory=Counter)
    faulty_entries: Counter[tuple[tuple[str, ...], str, Entry]] = field(default_factory=Counter)

    @property
    def legend_difference_count(self) -> int:
        return sum(sum(group.rows.values()) for group in self.legend_differences.values())

    @property
    def unruled_rows(self) -> int:
        return sum(group.rows for group in self.unruled.values())

    @property
    def difference_count(self) -> int:
        return sum(self.differences.values()) + sum(sum(group.differences.values()) for group in self.unruled.values())


@dataclass
class LegendGroup:
    rows: Counter[LegendDifference] = field(default_factory=Counter)
    descriptions: dict[LegendDifference, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))


@dataclass(frozen=True)
class NotCompared:
    missing_headers: tuple[str, ...]


CheckResult = QuantityCheck | NotCompared


@dataclass(frozen=True)
class RowCheck:
    result: RuleResult | None
    compared: tuple[str, ...]
    differences: tuple[str, ...]


def row_check(row: OrderFacts, rules: QuantityRules) -> RowCheck:
    content = row.content
    return _rule_check(row, None if content is None or content.started is None else evaluate(rules, content), rules)


def _rule_check(row: OrderFacts, result: RuleResult | None, rules: QuantityRules) -> RowCheck:
    if result is None:
        return RowCheck(None, (), ())
    compared = compared_columns(result, rules)
    return RowCheck(
        result, compared, tuple(column for column in compared if result.quantities.get(column, 0) != row.quantity(column))
    )


@dataclass(frozen=True)
class ValueDifference:
    column: str
    legend: int
    tata: TataValue


@dataclass(frozen=True)
class FillDifference:
    column: str
    legend: FillColour | None
    tata: FillColour | None


LegendDifference = ValueDifference | FillDifference
Entry = tuple[tuple[str, TataValue], ...]


@dataclass(frozen=True)
class LegendRowCheck:
    read: DescriptionRead
    rules: RowCheck
    differences: tuple[LegendDifference, ...]
    entry: Entry
    description: str | None
    columns: frozenset[str]

    @property
    def rule_differences(self) -> tuple[str, ...]:
        written = self.read.quantities if isinstance(self.read, WithCodes) else {}
        return tuple(column for column in self.rules.differences if column not in written)


def legend_row_check(row: OrderFacts, legend: ActivityLegend, rules: QuantityRules) -> LegendRowCheck:
    tool = tool_entry(row.content, row.completed, rules, legend)
    ruled = _rule_check(row, tool.rules, rules)
    codes = tool.read
    if not isinstance(codes, WithCodes):
        entry = tuple(
            (column, row.quantity(column))
            for column in DESCRIPTION_COLUMNS
            if column not in ruled.compared and row.quantity(column) != 0
        ) + (((AMOUNT_COLUMN, row.amount),) if row.amount != 0 else ())
        return LegendRowCheck(codes, ruled, (), entry, row.completed if entry else None, tool.columns)
    compared: list[LegendDifference] = [
        ValueDifference(column, tool.quantities.get(column, 0), row.quantity(column))
        for column in legend_columns(legend)
        if column in codes.quantities or column not in ruled.compared
    ]
    compared.append(ValueDifference(AMOUNT_COLUMN, tool.amount, row.amount))
    compared.extend(FillDifference(column, tool.fills.get(column), row.fills.get(column)) for column in legend_fill_columns(legend))
    differences = tuple(difference for difference in compared if difference.legend != difference.tata)
    return LegendRowCheck(codes, ruled, differences, (), row.completed if differences else None, tool.columns)


def legend_columns(legend: ActivityLegend) -> tuple[str, ...]:
    columns: set[str] = set()
    for code in legend.codes:
        match code.column:
            case FixedColumn(column=column):
                columns.add(column)
            case ColumnByNumber(ranges=ranges):
                columns.update(found.column for found in ranges)
            case None:
                pass
    return tuple(column for column in QUANTITY_LETTERS if column in columns)


def legend_fill_columns(legend: ActivityLegend) -> tuple[str, ...]:
    columns = {fill.column for code in legend.codes for fill in code.fills}
    return tuple(column for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN) if column in columns)


def check(orders: CollectiveOrders, rules: QuantityRules, legend: ActivityLegend) -> CheckResult:
    if isinstance(orders, MissingHeaders):
        return NotCompared(orders.headers)
    rule_columns = rules.rule_columns
    other_columns = tuple(
        column for column in QUANTITY_LETTERS if column not in rule_columns and column not in DESCRIPTION_COLUMNS
    )
    result = QuantityCheck(other_columns)
    for row in orders:
        result.rows += 1
        coded = legend_row_check(row, legend, rules)
        checked = coded.rules
        content, rule = row.content, checked.result
        if content is None or content.started is None or rule is None:
            result.undated += 1
        elif isinstance(rule, FromDescription):
            result.from_description += 1
        elif isinstance(rule, ServiceQuantities):
            result.compared += 1
            result.differences.update(_differences(content, content.started, row, rule.quantities, coded.rule_differences))
        else:
            _add_unruled(result.unruled[content.devices], content, content.started, row, rule, coded)
        result.description_filled.update(
            column for column in DESCRIPTION_COLUMNS if row.quantity(column) != 0 and column not in coded.columns
        )
        result.other_filled.update(column for column in other_columns if row.quantity(column) != 0)
        _add_legend(result, coded)
    return result


def _add_legend(result: QuantityCheck, coded: LegendRowCheck) -> None:
    match coded.read:
        case DescriptionError(problems=problems):
            reasons = tuple(dict.fromkeys(problem_text(problem) for problem in problems))
            result.description_error_rows += 1
            result.description_errors.update(reasons)
            if coded.description is not None:
                result.faulty_entries[reasons, coded.description, coded.entry] += 1
            return
        case WithCodes(found=found):
            ids = tuple(dict.fromkeys(code.code for code in found))
        case _:
            if coded.description is not None:
                result.uncoded_entries[coded.description, coded.entry] += 1
            return
    result.coded += 1
    if not coded.differences:
        result.coded_matching += 1
        return
    group = result.legend_differences[ids]
    group.rows.update(coded.differences)
    for difference in coded.differences:
        group.descriptions[difference][coded.description or ""] += 1


def week_hour(weekday: int, hour: int) -> str:
    return f"{WEEKDAY_LABELS[weekday]} {hour}"


def _add_unruled(
    group: Unruled,
    content: OrderContent,
    started: WeekTime,
    row: OrderFacts,
    rule: WithoutRule,
    coded: LegendRowCheck,
) -> None:
    group.rows += 1
    group.differences.update(_differences(content, started, row, rule.quantities, coded.rule_differences))
    group.values.update(
        (column, row.quantity(column))
        for column in QUANTITY_LETTERS
        if column not in coded.columns and row.quantity(column) != 0
    )


def _differences(
    content: OrderContent, started: WeekTime, row: OrderFacts, quantities: Mapping[str, int], columns: Iterable[str]
) -> Iterable[Difference]:
    for column in columns:
        yield Difference(
            content.devices,
            content.activities,
            content.contract,
            started.weekday,
            started.at.hour,
            column,
            quantities.get(column, 0),
            row.quantity(column),
        )


def title(period: str, result: CheckResult) -> str:
    if isinstance(result, NotCompared):
        return f"Kontrola ilości {period}: bez porównania"
    count = result.difference_count + result.legend_difference_count
    differences = f"{count} {plural(count, 'różnica', 'różnice', 'różnic')}" if count else "bez różnic"
    return f"Kontrola ilości {period}: {differences}"


_INTRO: Final = (
    "Kontrola ilości z Centrum rozliczeń: Reguły ilości przeliczone na Pliku zbiorczym, "
    "z którego tata uruchomił Przebieg rozliczeń.\n\n"
)
_DIFFERENCE_HEADER: Final = (
    "| Kolumna | Reguła | Tata | CZYNNOŚCI | UMOWA | Dzień, godzina | Wiersze |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)
_COLUMN_ORDER: Final = {column: position for position, column in enumerate(QUANTITY_LETTERS)}


def blocks(result: CheckResult, *, commit: str | None, run_id: str) -> tuple[str, ...]:
    tool = (
        "\n## Narzędzie\n\n"
        f"- Wersja narzędzia (commit): {commit or 'nieznana'}\n"
        f"- Uruchomienie: {run_id}\n"
    )
    if isinstance(result, NotCompared):
        missing = ", ".join(result.missing_headers)
        return (
            _INTRO,
            f"Bez porównania: w wierszu {HEADER_ROW} Pliku zbiorczego nie ma nagłówka {missing}, "
            "więc Kontrola nie wie, gdzie czytać treść zlecenia.\n",
            tool,
        )
    return (
        _INTRO,
        f"- Wiersze danych: {result.rows} (porównane {result.compared}, rozliczane z opisu "
        f"{result.from_description}, bez reguły {result.unruled_rows}, bez daty i godziny w DATA {result.undated})\n"
        f"- Różnice w kolumnach Reguł ilości: {result.difference_count}\n"
        f"- Wiersze z Kodami czynności: {result.coded} (zgodne z legendą {result.coded_matching}), "
        f"różnice legendy: {result.legend_difference_count}, wiersze z Błędem opisu: {result.description_error_rows}\n",
        *_difference_blocks(result.differences),
        *_unruled_blocks(result.unruled),
        *_legend_blocks(result.legend_differences),
        *_description_error_blocks(result.description_errors, result.faulty_entries),
        *_uncoded_blocks(result.uncoded_entries),
        "\n## Kolumny z opisu technika: wiersze wypełnione przez tatę\n\n",
        _count_table(DESCRIPTION_COLUMNS, result.description_filled),
        "\n## Pozostałe kolumny N:AP: wiersze wypełnione przez tatę\n\n",
        _count_table(result.other_columns, result.other_filled),
        tool,
    )


def _difference_blocks(differences: Counter[Difference]) -> list[str]:
    if not differences:
        return []
    found: list[str] = ["\n## Różnice\n"]
    for devices in sorted({difference.devices for difference in differences}, key=_text_order):
        found.append(f"\n### URZĄDZENIA {_code(devices)}\n\n{_DIFFERENCE_HEADER}")
        found.extend(_difference_rows(differences, devices))
    return found


def _unruled_blocks(unruled: Mapping[str, Unruled]) -> list[str]:
    if not unruled:
        return []
    found: list[str] = ["\n## Wiersze bez reguły\n"]
    for devices in sorted(unruled, key=_text_order):
        group = unruled[devices]
        found.append(f"\n### URZĄDZENIA {_code(devices)} (wiersze: {group.rows})\n")
        if group.differences:
            found.append(f"\n{_DIFFERENCE_HEADER}")
            found.extend(_difference_rows(group.differences, devices))
        if group.values:
            found.append("\n| Kolumna | Wartość taty | Wiersze |\n| --- | --- | --- |\n")
            found.extend(
                f"| {column} | {value} | {count} |\n"
                for (column, value), count in sorted(
                    group.values.items(), key=lambda item: (_COLUMN_ORDER[item[0][0]], _value_order(item[0][1]))
                )
            )
    return found


_LEGEND_HEADER: Final = "| Kolumna | Legenda | Tata | Wiersze | Opisy |\n| --- | --- | --- | --- | --- |\n"
_NO_FILL: Final = "brak"


def _legend_blocks(groups: Mapping[tuple[str, ...], LegendGroup]) -> list[str]:
    if not groups:
        return []
    found: list[str] = ["\n## Różnice legendy\n"]
    for ids in sorted(groups, key=lambda ids: [_text_order(code) for code in ids]):
        group = groups[ids]
        found.append(f"\n### Kody {', '.join(_code(code) for code in ids)}\n\n{_LEGEND_HEADER}")
        found.extend(
            f"| {_legend_column(difference)} | {_legend_value(difference.legend)} | {_legend_value(difference.tata)} | "
            f"{group.rows[difference]} | {_descriptions(group.descriptions[difference])} |\n"
            for difference in sorted(group.rows, key=_legend_order)
        )
    return found


def _uncoded_blocks(entries: Counter[tuple[str, Entry]]) -> list[str]:
    if not entries:
        return []
    return [
        "\n## Wiersze bez kodu z wpisem taty\n\n| Opis | Wpis taty | Wiersze |\n| --- | --- | --- |\n",
        *(
            f"| {_code(description)} | {_entry(entry)} | {count} |\n"
            for (description, entry), count in sorted(entries.items(), key=lambda item: (_text_order(item[0][0]), str(item[0][1])))
        ),
    ]


def _description_error_blocks(reasons: Counter[str], entries: Counter[tuple[tuple[str, ...], str, Entry]]) -> list[str]:
    if not reasons:
        return []
    found = [
        "\n## Błędy opisu\n\n| Powód | Wiersze |\n| --- | --- |\n",
        *(f"| {reason} | {reasons[reason]} |\n" for reason in sorted(reasons, key=_text_order)),
    ]
    if entries:
        found.append("\n### Błędy opisu z wpisem taty\n\n| Opis | Powód | Wpis taty | Wiersze |\n| --- | --- | --- | --- |\n")
        found.extend(
            f"| {_code(description)} | {'; '.join(shown)} | {_entry(entry)} | {count} |\n"
            for (shown, description, entry), count in sorted(entries.items(), key=lambda item: (_text_order(item[0][1]), str(item[0][2])))
        )
    return found


def _entry(entry: Entry) -> str:
    return ", ".join(f"{column} {value}" for column, value in entry)


def _legend_column(difference: LegendDifference) -> str:
    return f"{difference.column} kolor" if isinstance(difference, FillDifference) else difference.column


def _legend_value(value: int | str | None) -> str:
    return _NO_FILL if value is None else str(value)


def _legend_order(difference: LegendDifference) -> tuple[int, int, str, str]:
    position = _COLUMN_ORDER.get(difference.column, len(_COLUMN_ORDER))
    return (isinstance(difference, FillDifference), position, str(difference.legend), str(difference.tata))


def _descriptions(descriptions: Counter[str]) -> str:
    return "<br>".join(
        _code(description) + (f" ({count})" if count > 1 else "")
        for description, count in sorted(descriptions.items(), key=lambda item: _text_order(item[0]))
    )


def _difference_rows(differences: Counter[Difference], devices: str) -> list[str]:
    rows = sorted(
        (difference for difference in differences if difference.devices == devices),
        key=lambda difference: (
            _COLUMN_ORDER[difference.column],
            _text_order(difference.activities),
            _text_order(difference.contract),
            difference.weekday,
            difference.hour,
            difference.rule,
            _value_order(difference.tata),
        ),
    )
    return [
        f"| {difference.column} | {difference.rule} | {difference.tata} | {_code(difference.activities)} | "
        f"{_code(difference.contract)} | {week_hour(difference.weekday, difference.hour)} | "
        f"{differences[difference]} |\n"
        for difference in rows
    ]


def _count_table(columns: Iterable[str], counts: Counter[str]) -> str:
    names = list(columns)
    return (
        "| " + " | ".join(names) + " |\n"
        "| " + " | ".join("---" for _ in names) + " |\n"
        "| " + " | ".join(str(counts[name]) for name in names) + " |\n"
    )


def _code(text: str) -> str:
    if not text:
        return "(puste)"
    shown = text.replace("\r\n", "\n").replace("\n", "⏎").replace("|", "\\|")
    return f"`` {shown} ``" if "`" in shown else f"`{shown}`"


def _value_order(value: TataValue) -> tuple[int, int]:
    return (0, value) if isinstance(value, int) else (1, 0)


def _text_order(text: str) -> tuple[str, str]:
    return (text.casefold(), text)
