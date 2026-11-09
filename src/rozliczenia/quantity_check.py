"""Kontrola ilości: Reguły ilości przeliczone na Wierszach danych z Przebiegu i porównane z Ilościami usług taty.

Czysta funkcja (``check``) i jej tekst Markdown (``title``, ``blocks``). Nie zna Centrum, Skrzynki Zgłoszeń ani
skoroszytów: dostaje tylko treść dozwoloną filtrem prywatności (``order_facts``). Kolumny (decyzja 9):

- kolumny Reguł ilości (``QuantityColumn``) są porównywane; AK i AM tylko w wierszu, w którym reguła daje w nich
  wartość różną od zera, a w pozostałych liczą się jak kolumny z opisu technika;
- kolumny z opisu technika (``DESCRIPTION_COLUMNS``): liczba wierszy wypełnionych przez tatę;
- pozostałe kolumny N:AP, wyliczone jako reszta: liczba wypełnionych wierszy, osobno.

Wiersze rozliczane z opisu nie dają różnic, a wiersze bez reguły tworzą grupę na dokładny tekst URZĄDZENIA:
różnice tylko w V, T i N oraz wartości taty w pozostałych kolumnach N:AP (decyzja 10). Puste i 0 to to samo
(decyzja 11). Grupy różnic pokazują dzień tygodnia i pełną godzinę, bo od godziny zależy dodatek za usterkę.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from .text import WEEKDAY_LABELS, plural
from .collective_layout import HEADER_ROW, QUANTITY_LETTERS
from .order_facts import CollectiveOrders, MissingHeaders, OrderFacts, TataValue
from .quantity_rules import (
    DESCRIPTION_COLUMNS,
    FromDescription,
    OrderContent,
    QuantityColumn,
    RuleResult,
    ServiceQuantities,
    WithoutRule,
    evaluate,
)

_RULE_COLUMNS: Final = frozenset(QuantityColumn)
_SHARED: Final = frozenset({QuantityColumn.AK, QuantityColumn.AM})
WITHOUT_RULE_COLUMNS: Final = (QuantityColumn.V, QuantityColumn.T, QuantityColumn.N)
"""Kolumny, w których Kontrola porównuje wiersz bez reguły (decyzja 10), w kolejności podpowiedzi dla taty."""
_OTHER_COLUMNS: Final = tuple(column for column in QUANTITY_LETTERS if column not in _RULE_COLUMNS and column not in DESCRIPTION_COLUMNS)


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
    rows: int = 0
    compared: int = 0
    from_description: int = 0
    undated: int = 0
    differences: Counter[Difference] = field(default_factory=Counter)
    unruled: dict[str, Unruled] = field(default_factory=lambda: defaultdict(Unruled))
    description_filled: Counter[str] = field(default_factory=Counter)
    other_filled: Counter[str] = field(default_factory=Counter)

    @property
    def unruled_rows(self) -> int:
        return sum(group.rows for group in self.unruled.values())

    @property
    def difference_count(self) -> int:
        """Komórki różne od reguły w kolumnach Reguł ilości, także V, T i N wierszy bez reguły."""

        return sum(self.differences.values()) + sum(sum(group.differences.values()) for group in self.unruled.values())


@dataclass(frozen=True)
class NotCompared:
    """W wierszu 17 Pliku zbiorczego brakuje nagłówka kolumny wejścia, więc Kontrola nie porównuje."""

    missing_headers: tuple[str, ...]


CheckResult = QuantityCheck | NotCompared


def check(orders: CollectiveOrders) -> CheckResult:
    if isinstance(orders, MissingHeaders):
        return NotCompared(orders.headers)
    result = QuantityCheck()
    for row in orders:
        result.rows += 1
        content = row.content
        if content is None:
            result.undated += 1
            compared: tuple[QuantityColumn, ...] = ()
        else:
            rule = evaluate(content)
            compared = compared_columns(rule)
            if isinstance(rule, FromDescription):
                result.from_description += 1
            elif isinstance(rule, ServiceQuantities):
                result.compared += 1
                result.differences.update(_differences(content, row, rule.quantities, compared))
            else:
                _add_unruled(result.unruled[content.devices], content, row, rule, compared)
        result.description_filled.update(
            column for column in DESCRIPTION_COLUMNS if row.quantity(column) != 0 and column not in compared
        )
        result.other_filled.update(column for column in _OTHER_COLUMNS if row.quantity(column) != 0)
    return result


def compared_columns(rule: RuleResult) -> tuple[QuantityColumn, ...]:
    """Kolumny Reguł ilości, w których Kontrola porównuje wynik reguł z wpisami taty (decyzje 9 i 10)."""

    if isinstance(rule, FromDescription):
        return ()
    if isinstance(rule, WithoutRule):
        return WITHOUT_RULE_COLUMNS
    return tuple(column for column in QuantityColumn if column not in _SHARED or rule.quantities.get(column, 0))


def _add_unruled(
    group: Unruled, content: OrderContent, row: OrderFacts, rule: WithoutRule, compared: tuple[QuantityColumn, ...]
) -> None:
    group.rows += 1
    group.differences.update(_differences(content, row, rule.quantities, compared))
    group.values.update(
        (column, row.quantity(column)) for column in QUANTITY_LETTERS if column not in compared and row.quantity(column) != 0
    )


def _differences(
    content: OrderContent, row: OrderFacts, quantities: Mapping[QuantityColumn, int], columns: Iterable[QuantityColumn]
) -> Iterable[Difference]:
    started = content.started
    for column in columns:
        rule, tata = quantities.get(column, 0), row.quantity(column)
        if rule != tata:
            yield Difference(
                content.devices,
                content.activities,
                content.contract,
                started.weekday,
                started.at.hour,
                column,
                rule,
                tata,
            )


def title(period: str, result: CheckResult) -> str:
    if isinstance(result, NotCompared):
        return f"Kontrola ilości {period}: bez porównania"
    count = result.difference_count
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
        f"- Różnice w kolumnach Reguł ilości: {result.difference_count}\n",
        *_difference_blocks(result.differences),
        *_unruled_blocks(result.unruled),
        "\n## Kolumny z opisu technika: wiersze wypełnione przez tatę\n\n",
        _count_table(DESCRIPTION_COLUMNS, result.description_filled),
        "\n## Pozostałe kolumny N:AP: wiersze wypełnione przez tatę\n\n",
        _count_table(_OTHER_COLUMNS, result.other_filled),
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
        f"{_code(difference.contract)} | {WEEKDAY_LABELS[difference.weekday]} {difference.hour} | "
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
