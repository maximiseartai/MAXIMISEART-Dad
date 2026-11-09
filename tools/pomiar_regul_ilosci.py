"""Mierzy Reguły ilości na Plikach zbiorczych wypełnionych przez tatę (spec #268); tylko na Macu Maksa, przed zmianą Reguł ilości.

Dla każdego Pliku zbiorczego z argumentów liczy to, co Kontrola ilości, tymi samymi częściami: jeden odczyt
(``collective_file.read_data_rows``), treść po filtrze prywatności (``order_facts``) i kolumny porównania
(``quantity_check.compared_columns``). Własne są tylko zestawienia: zgodność całych wierszy i kolumn oraz klasy
rozbieżności. Wypisuje same liczby i teksty ``URZĄDZENIA``, bez adresów, numerów, umów i opisów technika, więc
wynik nie niesie danych klientów. Pliki są tylko czytane.

Klasa rozbieżności to zbiór różniących się kolumn (kolumna, reguła, tata) razem z tym, od czego zależy ich
wartość: dzień i godzina ``DATA`` dla N, liczba w ``CZYNNOŚCI`` dla V i AN, pierwsze słowo ``UMOWA`` dla T, a dla
AE, AP i AK wpis taty w Y (Last drop MDU z opisu technika).

    .venv/bin/python tools/pomiar_regul_ilosci.py "…/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" […]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia.collective_file import read_data_rows
from rozliczenia.dad_files import DadFiles
from rozliczenia.collective_layout import HEADER_ROW, QUANTITY_LETTERS
from rozliczenia.order_facts import MissingHeaders, OrderFacts, TataValue
from rozliczenia.quantity_check import compared_columns
from rozliczenia.quantity_rules import (
    FromDescription,
    OrderContent,
    QuantityColumn,
    RuleResult,
    ServiceQuantities,
    WithoutRule,
    evaluate,
)
from rozliczenia.text import WEEKDAY_LABELS

Difference = tuple[QuantityColumn, int, TataValue]
"""Kolumna, wartość z reguły, wartość taty."""

_Q = QuantityColumn
_LATE = time(17)
_DIGIT = re.compile(r"[0-9]")
_SHORT_WORD = re.compile(r"[a-ząćęłńóśźż]{1,4}")


@dataclass(frozen=True)
class Row:
    """Wiersz danych z datą: treść po filtrze prywatności, wynik reguł i kolumny, które Kontrola w nim porównuje."""

    order: OrderFacts
    content: OrderContent
    result: RuleResult
    compared: tuple[QuantityColumn, ...]

    def ruled(self, column: QuantityColumn) -> int:
        return self.result.quantities.get(column, 0)

    def differences(self) -> tuple[Difference, ...]:
        return tuple(
            (column, self.ruled(column), self.order.quantity(column))
            for column in self.compared
            if self.ruled(column) != self.order.quantity(column)
        )

    def beyond(self) -> dict[str, TataValue]:
        """Wpisy taty w ``N:AP`` poza kolumnami porównania."""

        return {letter: entry for letter, entry in self.order.quantities.items() if letter not in self.compared}

    def context(self) -> dict[QuantityColumn, str]:
        started = self.content.started
        day = WEEKDAY_LABELS[started.weekday]
        slot = day if started.weekday >= 5 else f"{day} {'od' if started.at >= _LATE else 'przed'} 17:00"
        activities = f"CZYNNOŚCI {'z liczbą' if _DIGIT.search(self.content.activities) else 'bez liczby'}"
        words = self.content.contract.casefold().split()
        contract = "puste" if not words else words[0] if _SHORT_WORD.fullmatch(words[0]) else "inne"
        last_drop = f"Y taty {'≠' if self.order.quantity('Y') != 0 else '='} 0"
        return {
            _Q.N: f"DATA {slot}",
            _Q.V: activities,
            _Q.AN: activities,
            _Q.T: f"UMOWA {contract}",
            _Q.AE: last_drop,
            _Q.AP: last_drop,
            _Q.AK: last_drop,
        }


def rows(path: Path) -> tuple[list[Row], int]:
    """Wiersze danych z wynikiem reguł i liczba wierszy, których ``DATA`` nie ma dnia i godziny."""

    orders = read_data_rows(path, DadFiles()).orders
    if isinstance(orders, MissingHeaders):
        raise SystemExit(f"{path.name}: w wierszu {HEADER_ROW} nie ma nagłówka {', '.join(orders.headers)}")
    measured: list[Row] = []
    undated = 0
    for order in orders:
        content = order.content
        if content is None:
            undated += 1
            continue
        result = evaluate(content)
        measured.append(Row(order, content, result, compared_columns(result)))
    return measured, undated


def report(name: str, measured: list[Row], undated: int) -> list[str]:
    service = [row for row in measured if isinstance(row.result, ServiceQuantities)]
    without_rule = [row for row in measured if isinstance(row.result, WithoutRule)]
    from_description = [row for row in measured if isinstance(row.result, FromDescription)]
    lines = [
        f"== {name}",
        f"wiersze danych: {len(measured) + undated} | z regułą: {len(service)} | bez reguły: {len(without_rule)}"
        f" | z opisu: {len(from_description)} | DATA nie jest datą: {undated}",
        f"zgodne całe wiersze z regułą (AK, AM tylko gdy reguła ≠ 0): {_share([not row.differences() for row in service])}",
        f"zgodne całe wiersze z regułą, ściśle we wszystkich {len(QuantityColumn)} kolumnach: {_share([all(row.ruled(column) == row.order.quantity(column) for column in QuantityColumn) for row in service])}",
        f"wiersze bez reguły zgodne w V, T, N: {_share([not row.differences() for row in without_rule])}",
        "-- kolumna: zgodne / porównane | reguła ≠ 0 | tata ≠ 0 (wiersze z regułą; V, T, N także bez reguły)",
    ]
    for column in QuantityColumn:
        compared = [row for row in measured if column in row.compared]
        lines.append(
            f"{column}: {_share([row.ruled(column) == row.order.quantity(column) for row in compared])}"
            f" | {sum(row.ruled(column) != 0 for row in compared)} | {sum(row.order.quantity(column) != 0 for row in compared)}"
        )
    classes: dict[tuple[str, tuple[Difference, ...], tuple[str, ...]], Counter[str]] = defaultdict(Counter)
    for row in service + without_rule:
        found = row.differences()
        if found:
            kind = "z regułą" if isinstance(row.result, ServiceQuantities) else "bez reguły"
            depends_on = row.context()
            context = tuple(sorted({depends_on[column] for column, _, _ in found if column in depends_on}))
            classes[(kind, found, context)][row.content.devices] += 1
    lines.append(f"-- klasy rozbieżności: {len(classes)}")
    for (kind, found, context), texts in sorted(classes.items(), key=lambda item: -item[1].total()):
        columns = "; ".join(f"{column}: reguła {ruled}, tata {tata}" for column, ruled, tata in found)
        lines.append(f"{texts.total()} wierszy {kind} | {columns}{''.join(f' | {part}' for part in context)} | {_texts(texts)}")
    lines.append("-- wiersze bez reguły według URZĄDZENIA: wiersze | wpisy taty poza V, T, N → wiersze")
    lines += _groups(without_rule)
    lines.append("-- wiersze z opisu według URZĄDZENIA: wiersze | wpisy taty w N:AP → wiersze")
    lines += _groups(from_description)
    beyond = Counter(letter for row in service for letter in row.beyond())
    lines.append(f"-- wiersze z regułą z wpisem taty w kolumnie spoza porównania: {_counts(beyond)}")
    return lines


def _share(matches: Sequence[bool]) -> str:
    part, whole = sum(matches), len(matches)
    return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else "0/0"


def _texts(texts: Counter[str], limit: int = 12) -> str:
    shown = ", ".join(f"{count}× {text!r}" for text, count in texts.most_common(limit))
    return shown + (f" i {len(texts) - limit} innych tekstów" if len(texts) > limit else "")


def _counts(values: Mapping[str, object]) -> str:
    return " ".join(f"{letter}={values[letter]}" for letter in QUANTITY_LETTERS if letter in values and values[letter] != 0) or "nic"


def _groups(group: list[Row]) -> list[str]:
    by_text: dict[str, Counter[str]] = defaultdict(Counter)
    for row in group:
        by_text[row.content.devices][_counts(row.beyond())] += 1
    return [
        f"{entries.total()}× {text!r} | " + ", ".join(f"{filled} → {count}" for filled, count in entries.most_common())
        for text, entries in sorted(by_text.items(), key=lambda item: -item[1].total())
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pomiar Reguł ilości na Plikach zbiorczych wypełnionych przez tatę.")
    parser.add_argument("pliki", nargs="+", type=Path, help="Pliki zbiorcze wypełnione przez tatę")
    for path in parser.parse_args(argv).pliki:
        measured, undated = rows(path)
        print("\n".join(report(path.name, measured, undated)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
