"""Kontrola ilości: Reguły ilości przeliczone na Wierszach danych z Przebiegu i porównane z Ilościami usług taty.

Czysta funkcja (``check``) i jej tekst Markdown (``title``, ``blocks``). Nie zna Centrum, Skrzynki Zgłoszeń ani
skoroszytów: dostaje tylko treść dozwoloną filtrem prywatności (``order_facts``) i Reguły ilości, z których liczył
Przebieg. Kolumny (decyzja 9):

- kolumny Reguł ilości (``QuantityRules.rule_columns``) są porównywane; te z nich, które są też kolumnami z opisu
  technika (AK i AM), tylko w wierszu, w którym reguła daje w nich wartość różną od zera, a w pozostałych liczą się
  jak kolumny z opisu technika;
- kolumny z opisu technika (``DESCRIPTION_COLUMNS``): liczba wierszy wypełnionych przez tatę;
- pozostałe kolumny N:AP, wyliczone jako reszta: liczba wypełnionych wierszy, osobno.

Wiersze rozliczane z opisu nie dają różnic, a wiersze bez reguły tworzą grupę na dokładny tekst URZĄDZENIA:
różnice tylko w kolumnach reguł dla składnika spoza listy (``QuantityRules.without_rule_columns``, z Wydania V, T i N)
oraz wartości taty w pozostałych kolumnach N:AP (decyzja 10). Puste i 0 to to samo
(decyzja 11). Grupy różnic pokazują dzień tygodnia i pełną godzinę, bo od godziny zależy dodatek za usterkę.

Legenda czynności (ADR 0038) liczy się rachunkiem jednego wiersza ``legend_row_check``, tym samym w Kontroli, w
podglądzie zmiany legendy i w bramie Legendy czynności (``tools/brama_legendy.py``). W wierszu z Kodem czynności (także
tylko spoza przedziałów) porównuje z tatą:

- kolumny, w które może wpisać którykolwiek kod legendy, z wartością Reguł ilości i legendy razem, tak jak wpisuje
  je Przygotowanie; kolumnę, którą porównują Reguły ilości, tylko gdy legenda wpisała w nią coś w tym wierszu, i wtedy
  ta kolumna nie jest różnicą Reguł ilości;
- kwotę w ``AS``;
- kolory kolumn, które może wypełnić którykolwiek kod legendy (zielony, czerwony albo brak; wypełnienie spoza palety
  legendy, np. tło z Wzorca, to brak, zob. ``order_facts._colour``).

W wierszu bez kodu liczy wpis taty: kolumny z opisu technika poza porównywanymi przez Reguły ilości i ``AS``. Opis
technika (``CZYNNOŚCI ZREALIZOWANE``) wiersz oddaje (``LegendRowCheck.description``) tylko przy różnicy legendy albo,
bez kodu, przy wpisie taty, więc tylko taki opis trafia do treści Kontroli, a w niej przez strażnika reguły danych.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from .activity_legend import AMOUNT_COLUMN, ActivityLegend, CodesRead, ColumnByNumber, FillColour, FixedColumn
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


@dataclass(frozen=True)
class Difference:
    """Grupa różnic: kontekst, od którego zależą reguły, kolumna, wartość reguły i wartość taty."""

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
    """Wiersze bez reguły o jednym dokładnym tekście URZĄDZENIA (decyzja 10)."""

    rows: int = 0
    differences: Counter[Difference] = field(default_factory=Counter)
    """Tylko V, T i N."""
    values: Counter[tuple[str, TataValue]] = field(default_factory=Counter)
    """(kolumna, wartość taty) → wiersze, w pozostałych kolumnach N:AP."""


@dataclass
class QuantityCheck:
    other_columns: tuple[str, ...]
    """Kolumny N:AP poza kolumnami Reguł ilości i kolumnami z opisu technika, w kolejności N:AP."""
    rows: int = 0
    compared: int = 0
    from_description: int = 0
    undated: int = 0
    differences: Counter[Difference] = field(default_factory=Counter)
    unruled: dict[str, Unruled] = field(default_factory=lambda: defaultdict(Unruled))
    description_filled: Counter[str] = field(default_factory=Counter)
    other_filled: Counter[str] = field(default_factory=Counter)
    coded: int = 0
    """Wiersze danych z Kodem czynności."""
    coded_matching: int = 0
    """Wiersze z Kodem czynności bez różnicy legendy."""
    legend_differences: dict[tuple[str, ...], LegendGroup] = field(default_factory=lambda: defaultdict(LegendGroup))
    """Identyfikatory kodów wiersza → różnice legendy wierszy z tymi kodami."""
    uncoded_entries: Counter[tuple[str, tuple[tuple[str, TataValue], ...]]] = field(default_factory=Counter)
    """(opis technika, wpis taty) → wiersze bez kodu z tym wpisem."""
    out_of_range: Counter[tuple[str, int]] = field(default_factory=Counter)
    """(kod, liczba z zapisu spoza przedziałów) → wiersze."""

    @property
    def legend_difference_count(self) -> int:
        """Komórki różne od legendy (wartość albo kolor) w wierszach z Kodem czynności."""

        return sum(sum(group.rows.values()) for group in self.legend_differences.values())

    @property
    def unruled_rows(self) -> int:
        return sum(group.rows for group in self.unruled.values())

    @property
    def difference_count(self) -> int:
        """Komórki różne od reguły w kolumnach Reguł ilości, także V, T i N wierszy bez reguły."""

        return sum(self.differences.values()) + sum(sum(group.differences.values()) for group in self.unruled.values())


@dataclass
class LegendGroup:
    """Różnice legendy wierszy o jednym zestawie Kodów czynności: różnica → wiersze i opisy technika tych wierszy."""

    rows: Counter[LegendDifference] = field(default_factory=Counter)
    descriptions: dict[LegendDifference, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))


@dataclass(frozen=True)
class NotCompared:
    """W wierszu 17 Pliku zbiorczego brakuje nagłówka kolumny wejścia, więc Kontrola nie porównuje."""

    missing_headers: tuple[str, ...]


CheckResult = QuantityCheck | NotCompared


@dataclass(frozen=True)
class RowCheck:
    """Kontrola ilości jednego Wiersza danych: wynik reguł, kolumny porównania i te z nich, w których tata wpisał inaczej
    niż reguła. Wiersz bez daty i godziny w ``DATA`` nie ma wyniku reguł ani kolumn porównania."""

    result: RuleResult | None
    compared: tuple[str, ...]
    differences: tuple[str, ...]


def row_check(row: OrderFacts, rules: QuantityRules) -> RowCheck:
    """Rachunek Kontroli ilości na jednym Wierszu danych według ``rules``; ten sam liczy ``check`` i podgląd zmiany
    Reguł ilości w Ustawieniach (ADR 0033)."""

    content = row.content
    if content is None or content.started is None:
        return RowCheck(None, (), ())
    result = evaluate(rules, content)
    compared = compared_columns(result, rules)
    return RowCheck(
        result, compared, tuple(column for column in compared if result.quantities.get(column, 0) != row.quantity(column))
    )


@dataclass(frozen=True)
class ValueDifference:
    """Wartość komórki (Ilość usług w kolumnie albo kwota w ``AS``) inna u taty niż według Reguł ilości i legendy."""

    column: str
    legend: int
    tata: TataValue


@dataclass(frozen=True)
class FillDifference:
    """Kolor wypełnienia kolumny inny u taty niż według legendy; ``None``: bez koloru legendy."""

    column: str
    legend: FillColour | None
    tata: FillColour | None


LegendDifference = ValueDifference | FillDifference


@dataclass(frozen=True)
class LegendRowCheck:
    """Legenda czynności w Kontroli ilości jednego Wiersza danych.

    ``codes``: wynik legendy dla opisu technika. ``rules``: rachunek Reguł ilości (``row_check``). ``differences``: różnice
    legendy w wierszu z kodem, w kolejności N:AP, ``AS``, potem kolory. ``entry``: wpis taty w wierszu bez kodu (kolumna
    → wartość). ``description``: opis technika, tylko w wierszu z różnicą legendy albo bez kodu z wpisem taty.
    """

    codes: CodesRead
    rules: RowCheck
    differences: tuple[LegendDifference, ...]
    entry: tuple[tuple[str, TataValue], ...]
    description: str | None

    @property
    def coded(self) -> bool:
        return bool(self.codes.found or self.codes.out_of_range)

    @property
    def rule_differences(self) -> tuple[str, ...]:
        """Różnice Reguł ilości bez kolumn, które w tym wierszu wpisała też legenda: te porównuje legenda, z sumą."""

        return tuple(column for column in self.rules.differences if column not in self.codes.quantities)


def legend_row_check(row: OrderFacts, legend: ActivityLegend, rules: QuantityRules) -> LegendRowCheck:
    """Rachunek Legendy czynności ``legend`` w Kontroli ilości na jednym Wierszu danych, z Regułami ilości ``rules``; ten
    sam liczy ``check``, podgląd zmiany legendy w Ustawieniach i brama Legendy czynności (zob. opis modułu)."""

    ruled = row_check(row, rules)
    codes = legend.read(row.completed)
    if not (codes.found or codes.out_of_range):
        entry = tuple(
            (column, row.quantity(column))
            for column in DESCRIPTION_COLUMNS
            if column not in ruled.compared and row.quantity(column) != 0
        ) + (((AMOUNT_COLUMN, row.amount),) if row.amount != 0 else ())
        return LegendRowCheck(codes, ruled, (), entry, row.completed if entry else None)
    ruled_quantities = {} if ruled.result is None else ruled.result.quantities
    compared: list[LegendDifference] = [
        ValueDifference(column, ruled_quantities.get(column, 0) + codes.quantities.get(column, 0), row.quantity(column))
        for column in legend_columns(legend)
        if column in codes.quantities or column not in ruled.compared
    ]
    compared.append(ValueDifference(AMOUNT_COLUMN, codes.amount, row.amount))
    compared.extend(FillDifference(column, codes.fills.get(column), row.fills.get(column)) for column in legend_fill_columns(legend))
    differences = tuple(difference for difference in compared if difference.legend != difference.tata)
    return LegendRowCheck(codes, ruled, differences, (), row.completed if differences else None)


def legend_columns(legend: ActivityLegend) -> tuple[str, ...]:
    """Kolumny N:AP, w które może wpisać którykolwiek kod legendy, w kolejności N:AP."""

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
    """Kolumny, które może wypełnić którykolwiek kod legendy, w kolejności arkusza."""

    columns = {fill.column for code in legend.codes for fill in code.fills}
    return tuple(column for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN) if column in columns)


def check(orders: CollectiveOrders, rules: QuantityRules, legend: ActivityLegend) -> CheckResult:
    """Kontrola ilości Zleceń Przebiegu według ``rules`` i ``legend``, Reguł ilości i Legendy czynności tego Przebiegu."""

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
        content, rule, compared = row.content, checked.result, checked.compared
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
            column for column in DESCRIPTION_COLUMNS if row.quantity(column) != 0 and column not in compared
        )
        result.other_filled.update(column for column in other_columns if row.quantity(column) != 0)
        _add_legend(result, coded)
    return result


def _add_legend(result: QuantityCheck, coded: LegendRowCheck) -> None:
    result.out_of_range.update({(found.code, found.number) for found in coded.codes.out_of_range if found.number is not None})
    if not coded.coded:
        if coded.description is not None:
            result.uncoded_entries[coded.description, coded.entry] += 1
        return
    result.coded += 1
    if not coded.differences:
        result.coded_matching += 1
        return
    ids = tuple(dict.fromkeys(found.code for found in (*coded.codes.found, *coded.codes.out_of_range)))
    group = result.legend_differences[ids]
    group.rows.update(coded.differences)
    for difference in coded.differences:
        group.descriptions[difference][coded.description or ""] += 1


def week_hour(weekday: int, hour: int) -> str:
    """Dzień tygodnia z pełną godziną, jak grupy różnic Kontroli ilości („pt 16”): od godziny zależy dodatek za usterkę."""

    return f"{WEEKDAY_LABELS[weekday]} {hour}"


def compared_columns(rule: RuleResult, rules: QuantityRules) -> tuple[str, ...]:
    """Kolumny Reguł ilości ``rules``, w których Kontrola porównuje wynik reguł z wpisami taty (decyzje 9 i 10)."""

    if isinstance(rule, FromDescription):
        return ()
    if isinstance(rule, WithoutRule):
        return rules.without_rule_columns
    return tuple(
        column for column in rules.rule_columns if column not in DESCRIPTION_COLUMNS or rule.quantities.get(column, 0)
    )


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
        if column not in coded.rules.compared and row.quantity(column) != 0
    )


def _differences(
    content: OrderContent, started: WeekTime, row: OrderFacts, quantities: Mapping[str, int], columns: Iterable[str]
) -> Iterable[Difference]:
    """Grupy różnic w kolumnach ``columns``, w których tata wpisał inaczej niż reguła (``RowCheck.differences``)."""

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
    """Treść Markdown jako bloki (sekcje i wiersze tabel), które kolejka może rozdzielić na części."""

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
        f"- Wiersze z Kodem czynności: {result.coded} (zgodne z legendą {result.coded_matching}), "
        f"różnice legendy: {result.legend_difference_count}\n",
        *_difference_blocks(result.differences),
        *_unruled_blocks(result.unruled),
        *_legend_blocks(result.legend_differences),
        *_uncoded_blocks(result.uncoded_entries),
        *_out_of_range_blocks(result.out_of_range),
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


def _uncoded_blocks(entries: Counter[tuple[str, tuple[tuple[str, TataValue], ...]]]) -> list[str]:
    if not entries:
        return []
    return [
        "\n## Wiersze bez kodu z wpisem taty\n\n| Opis | Wpis taty | Wiersze |\n| --- | --- | --- |\n",
        *(
            f"| {_code(description)} | {', '.join(f'{column} {value}' for column, value in entry)} | {count} |\n"
            for (description, entry), count in sorted(entries.items(), key=lambda item: (_text_order(item[0][0]), str(item[0][1])))
        ),
    ]


def _out_of_range_blocks(codes: Counter[tuple[str, int]]) -> list[str]:
    if not codes:
        return []
    return [
        "\n## Kody spoza przedziałów\n\n| Kod | Liczba | Wiersze |\n| --- | --- | --- |\n",
        *(
            f"| {_code(code)} | {number} | {count} |\n"
            for (code, number), count in sorted(codes.items(), key=lambda item: (_text_order(item[0][0]), item[0][1]))
        ),
    ]


def _legend_column(difference: LegendDifference) -> str:
    return f"{difference.column} kolor" if isinstance(difference, FillDifference) else difference.column


def _legend_value(value: int | str | None) -> str:
    return _NO_FILL if value is None else str(value)


def _legend_order(difference: LegendDifference) -> tuple[int, int, str, str]:
    position = _COLUMN_ORDER.get(difference.column, len(_COLUMN_ORDER))
    return (isinstance(difference, FillDifference), position, str(difference.legend), str(difference.tata))


def _descriptions(descriptions: Counter[str]) -> str:
    """Opisy technika wierszy różnicy, każdy raz, z liczbą wierszy, gdy jest ich więcej niż jeden."""

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
    """Dokładny tekst komórki jako kod w komórce tabeli Markdown; pusty to „(puste)”, nowy wiersz to „⏎”."""

    if not text:
        return "(puste)"
    shown = text.replace("\r\n", "\n").replace("\n", "⏎").replace("|", "\\|")
    return f"`` {shown} ``" if "`" in shown else f"`{shown}`"


def _value_order(value: TataValue) -> tuple[int, int]:
    return (0, value) if isinstance(value, int) else (1, 0)


def _text_order(text: str) -> tuple[str, str]:
    return (text.casefold(), text)
