"""Puszcza Legendę czynności (``--legenda``: plik ``legenda-czynnosci.yaml`` z Ustawień taty; bez niego legenda z
Wydania) na Plikach zbiorczych wypełnionych przez tatę: ``.xlsx`` z dysku (wartości, kwota w ``AS`` i kolory) albo
plik Logów Wyceny w efenix z dysku taty lub z Archiwum Logów okresu (``.json``, ``.json.gz``), z którego czyta tylko
Kopię wejścia Pliku zbiorczego: ``N:AP`` i ``CZYNNOŚCI ZREALIZOWANE``, bo kolorów Logi nie mają. Pliki są tylko czytane.

Wiersz czyta filtr prywatności wierszy (``order_facts.collective_orders``), a liczy go rachunek Kontroli ilości
(``quantity_check.legend_row_check``) z Regułami ilości z Wydania, więc brama i Kontrola mówią to samo o każdej komórce
tego samego pliku. Wiersz z kodem to wiersz z Kodami czynności bez Błędu opisu, także obok zwykłego opisu. W nim brama porównuje z tatą kolumny legendy
(wartość Reguł ilości i legendy razem z Wpisu narzędzia, ``tool_entry``, tego samego, który wpisuje Przygotowanie), a
z dysku także kwotę w ``AS`` i kolory kolumn, które legenda wypełnia (zielony, czerwony albo brak; inne wypełnienie, np. tło Wzorca, to brak). Wiersz z Błędem opisu
brama liczy osobno, według powodu, bo legenda nic w nim nie wpisuje. Wpis taty w wierszu bez kodów albo z Błędem opisu
to wartość taty w kolumnie z opisu technika, której nie porównują Reguły ilości, albo kwota w ``AS``. Wiersz, którego
``DATA`` nie jest datą, liczy się bez Reguł ilości, jak w Kontroli.

Na stdout trafiają same liczby, identyfikatory kodów legendy, liczby z kodów spoza przedziałów i litery kolumn: bez
opisów technika, adresów i numerów, więc wynik można wkleić do PR. ``--opisy PLIK`` zapisuje
lokalnie każdy wiersz z różnicą, z Błędem opisu i bez kodów z wpisem taty razem z numerem wiersza i treścią
``CZYNNOŚCI ZREALIZOWANE``; plik w repozytorium (publicznym) jest odrzucony.

    .venv/bin/python tools/brama_legendy.py "…/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" "…/…-efenix-….json.gz" \
        [--legenda config/legenda-czynnosci.yaml] [--opisy ~/.t3/notes/<run>/opisy.txt]
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import gzip
import json
from pathlib import Path
import sys
from typing import Final

from pydantic import TypeAdapter, ValidationError
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia.activity_legend import (
    AMOUNT_COLUMN,
    REASONS,
    ActivityLegend,
    DescriptionError,
    DescriptionProblem,
    FillColour,
    LegendProblem,
    WithCodes,
    problem_text,
)
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, parse_activity_legend
from rozliczenia.centrum.logged_input_copy import LoggedCell, LoggedInputFile, LoggedTyped
from rozliczenia.collective_layout import DATA_ROW_COLUMNS, INPUT_COLUMNS, QUANTITY_LETTERS, letter
from rozliczenia.dad_files import DadFiles
from rozliczenia.highlights import PLAIN
from rozliczenia.order_facts import MissingHeaders, OrderFacts, TataValue, collective_orders
from rozliczenia.quantity_check import (
    FillDifference,
    LegendDifference,
    LegendRowCheck,
    legend_columns,
    legend_fill_columns,
    legend_row_check,
)
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES
from rozliczenia.register_columns import COMPLETED
from rozliczenia.row_look import GENERAL
from rozliczenia.text import normalize_text
from rozliczenia.workbook_files import DataCell, DataRow, header_columns, read_data_rows

OPIS = "Brama Legendy czynności: liczy, w ilu wierszach z kodem legenda daje to, co wpisał tata; tylko na Macu Maksa, przed Wydaniem z legendą."

ROOT: Final = Path(__file__).resolve().parents[1]
NONE: Final = "brak"
Difference = tuple[str, str, str]
"""Kolumna (``kolor AF`` dla koloru), wartość legendy, wartość taty."""
_LOGS: Final = TypeAdapter(list[LoggedInputFile])
_EFENIX: Final = "efenix"


@dataclass(frozen=True)
class DadRow:
    """Wiersz danych Pliku zbiorczego taty po filtrze prywatności wierszy, z numerem wiersza arkusza."""

    number: int
    order: OrderFacts


@dataclass(frozen=True)
class Source:
    label: str
    rows: tuple[DadRow, ...]
    looked: bool


@dataclass(frozen=True)
class Checked:
    """Wiersz po rachunku Kontroli ilości: różnice legendy z tatą (wiersz z kodami bez Błędu opisu) i wpis taty (wiersz
    bez kodów albo z Błędem opisu), z Logów bez ``AS`` i kolorów."""

    row: DadRow
    check: LegendRowCheck
    differences: tuple[Difference, ...]
    entries: Mapping[str, TataValue]

    @property
    def coded(self) -> bool:
        return isinstance(self.check.read, WithCodes)

    @property
    def code_ids(self) -> tuple[str, ...]:
        read = self.check.read
        return tuple(dict.fromkeys(found.code for found in read.found)) if isinstance(read, WithCodes) else ()

    @property
    def problems(self) -> tuple[DescriptionProblem, ...]:
        read = self.check.read
        return read.problems if isinstance(read, DescriptionError) else ()


class Gate:
    def __init__(self, legend: ActivityLegend, rules: QuantityRules) -> None:
        self.legend = legend
        self.rules = rules
        self.columns = legend_columns(legend)
        self.fill_columns = legend_fill_columns(legend)

    def check(self, row: DadRow, *, looked: bool) -> Checked:
        checked = legend_row_check(row.order, self.legend, self.rules)
        differences = tuple(_shown(found) for found in checked.differences if looked or _in_logs(found))
        entries = {column: value for column, value in checked.entry if looked or column != AMOUNT_COLUMN}
        return Checked(row, checked, differences, entries)

    def compared(self, looked: bool) -> str:
        columns = " ".join(self.columns)
        if not looked:
            return f"{columns} (Logi: bez AS i kolorów)"
        return f"{columns}, {AMOUNT_COLUMN}, kolory {' '.join(self.fill_columns) or NONE}"


def _in_logs(difference: LegendDifference) -> bool:
    return not isinstance(difference, FillDifference) and difference.column != AMOUNT_COLUMN


def _shown(difference: LegendDifference) -> Difference:
    if isinstance(difference, FillDifference):
        return (f"kolor {difference.column}", _colour(difference.legend), _colour(difference.tata))
    return (difference.column, str(difference.legend), str(difference.tata))


def _colour(colour: FillColour | None) -> str:
    return NONE if colour is None else str(colour)


def disk_rows(path: Path) -> Source:
    read = read_data_rows(path, DadFiles(), despite_excel_lock=True)
    return Source(path.name, _rows(path.name, read.header, read.rows), looked=True)


def logs_rows(path: Path) -> Source:
    """Wiersze danych Pliku zbiorczego z Kopii wejścia pliku Logów Wyceny w efenix."""

    data = path.read_bytes()
    document = json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)
    if not isinstance(document, dict) or document.get("process") != _EFENIX:
        raise SystemExit(f"{path.name}: to nie są Logi Wyceny w efenix")
    try:
        files = _LOGS.validate_python(document.get("input_copy"))
    except ValidationError as error:
        raise SystemExit(f"{path.name}: Kopia wejścia nie ma postaci Logów ({error.error_count()} błędów)") from error
    if len(files) != 1 or len(files[0].sheets) != 1:
        raise SystemExit(f"{path.name}: Kopia wejścia powinna mieć jeden Plik zbiorczy z jednym arkuszem")
    [copied] = files
    [sheet] = copied.sheets
    header = header_columns([sheet.columns.get(letter(column)) for column in INPUT_COLUMNS])
    rows = [
        DataRow(row.row, tuple(DataCell(_value(row.cells.get(letter(column))), PLAIN, GENERAL, None) for column in DATA_ROW_COLUMNS))
        for row in sheet.rows
    ]
    label = f"{copied.name} (Logi {path.name})"
    return Source(label, _rows(label, header, rows), looked=False)


def _value(cell: LoggedCell | None) -> bool | int | float | str | datetime | time | timedelta | None:
    if not isinstance(cell, LoggedTyped):
        return cell
    match cell.type:
        case "datetime":
            return datetime.fromisoformat(cell.text)
        case "time":
            return time.fromisoformat(cell.text)
        case "timedelta":
            return timedelta(seconds=float(cell.text))
        case "other":
            return cell.text


def _rows(label: str, header: Mapping[str, int], rows: Sequence[DataRow]) -> tuple[DadRow, ...]:
    if normalize_text(COMPLETED.target_header) not in header:
        raise SystemExit(f"{label}: w wierszu nagłówka nie ma {COMPLETED.target_header}")
    orders = collective_orders(header, rows)
    if isinstance(orders, MissingHeaders):
        raise SystemExit(f"{label}: w wierszu nagłówka nie ma {', '.join(orders.headers)}")
    return tuple(DadRow(row.number, order) for row, order in zip(rows, orders, strict=True))


@dataclass(frozen=True)
class Tally:
    rows: int
    undated: int
    checked: tuple[Checked, ...]

    @classmethod
    def of(cls, gate: Gate, sources: Iterable[Source]) -> Tally:
        checked = tuple(gate.check(row, looked=source.looked) for source in sources for row in source.rows)
        return cls(len(checked), sum(row.row.order.content is None for row in checked), checked)

    def report(self) -> list[str]:
        coded = [row for row in self.checked if row.coded]
        faulty = [row for row in self.checked if row.problems]
        uncoded = [row for row in self.checked if not row.coded and not row.problems]
        lines = [
            f"wiersze danych: {self.rows} | z kodem: {len(coded)} | z Błędem opisu: {len(faulty)}"
            f" | bez kodów: {len(uncoded)} | DATA nie jest datą: {self.undated}",
            f"zgodne z tatą wiersze z kodem: {_share(coded)}",
        ]
        codes = Counter(code for row in coded for code in row.code_ids)
        lines.append(f"kody (wiersze): {' '.join(f'{code}={count}' for code, count in codes.most_common()) or NONE}")
        classes = Counter((row.code_ids, row.differences) for row in coded if row.differences)
        lines.append(f"-- różnice (wiersze | kody | kolumna: legenda, tata): {len(classes)} klas")
        for (code_ids, differences), count in sorted(classes.items(), key=lambda item: (-item[1], item[0])):
            shown = "; ".join(f"{column}: legenda {legend}, tata {tata}" for column, legend, tata in differences)
            lines.append(f"{count} | {', '.join(code_ids)} | {shown}")
        reasons = Counter(reason for row in faulty for reason in dict.fromkeys(problem.reason for problem in row.problems))
        lines.append(
            "-- Błędy opisu (powód → wiersze): "
            + (" | ".join(f"{reason}={reasons[reason]}" for reason in REASONS if reason in reasons) or NONE)
        )
        named = Counter(problem_text(problem) for row in faulty for problem in row.problems)
        lines.append("-- powody z kodami (powód → wiersze): " + (" | ".join(f"{reason}→{count}" for reason, count in sorted(named.items())) or NONE))
        lines.append(_entries("Błędy opisu z wpisem taty", [row for row in faulty if row.entries]))
        lines.append(_entries("wiersze bez kodów z wpisem taty", [row for row in uncoded if row.entries]))
        return lines


def _entries(label: str, rows: Sequence[Checked]) -> str:
    entries = Counter(column for row in rows for column in row.entries)
    ordered = [column for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN) if column in entries]
    return f"-- {label}: {len(rows)} | " + (" ".join(f"{column}={entries[column]}" for column in ordered) or NONE)


def _share(rows: Sequence[Checked]) -> str:
    part, whole = sum(not row.differences for row in rows), len(rows)
    return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else "0/0"


def descriptions(gate: Gate, sources: Sequence[Source]) -> list[str]:
    """Wiersze z różnicą, z Błędem opisu i bez kodów z wpisem taty z treścią ``CZYNNOŚCI ZREALIZOWANE``: tylko do pliku
    lokalnego."""

    lines: list[str] = []
    for source in sources:
        for row in (gate.check(dad_row, looked=source.looked) for dad_row in source.rows):
            text = " ".join(row.row.order.completed.split())
            where = f"{source.label} | wiersz {row.row.number}"
            entries = " ".join(f"{column}={value}" for column, value in row.entries.items()) or NONE
            if row.differences:
                shown = "; ".join(f"{column}: legenda {legend}, tata {tata}" for column, legend, tata in row.differences)
                lines.append(f"{where} | różnica | {', '.join(row.code_ids)} | {shown} | {text}")
            elif row.problems:
                shown = "; ".join(problem_text(problem) for problem in row.problems)
                lines.append(f"{where} | Błąd opisu | {shown} | wpis taty {entries} | {text}")
            elif row.entries:
                lines.append(f"{where} | bez kodów z wpisem taty | {entries} | {text}")
    return lines


def _legend(path: Path | None) -> ActivityLegend:
    if path is None:
        return DEFAULT_ACTIVITY_LEGEND
    legend = parse_activity_legend(yaml.safe_load(path.read_text(encoding="utf-8")))
    if isinstance(legend, LegendProblem):
        raise SystemExit(f"{path.name}: {legend.field}: {legend.message}")
    return legend


def _outside_repository(text: str) -> Path:
    path = Path(text).expanduser()
    if path.resolve().is_relative_to(ROOT):
        raise argparse.ArgumentTypeError(f"{path} leży w repozytorium, które jest publiczne; podaj plik poza nim (~/.t3/notes/<run>/)")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS)
    parser.add_argument("pliki", nargs="+", type=Path, help="Pliki zbiorcze taty (.xlsx) i pliki Logów Wyceny w efenix (.json, .json.gz)")
    parser.add_argument("--legenda", type=Path, help="legenda-czynnosci.yaml z Ustawień; bez niego legenda z Wydania")
    parser.add_argument("--opisy", type=_outside_repository, help="plik poza repozytorium na wiersze z treścią CZYNNOŚCI ZREALIZOWANE")
    args = parser.parse_args(argv)
    gate = Gate(_legend(args.legenda), DEFAULT_QUANTITY_RULES)
    sources = [disk_rows(path) if path.suffix == ".xlsx" else logs_rows(path) for path in args.pliki]
    print(f"Legenda czynności: {'z Wydania' if args.legenda is None else args.legenda.name} | Reguły ilości: z Wydania")
    for source in sources:
        print(f"== {source.label} | porównane: {gate.compared(source.looked)}")
        print("\n".join(Tally.of(gate, [source]).report()))
    if len(sources) > 1:
        print(f"== razem: {len(sources)} plików")
        print("\n".join(Tally.of(gate, sources).report()))
    if args.opisy is not None:
        args.opisy.parent.mkdir(parents=True, exist_ok=True)
        args.opisy.write_text("".join(f"{line}\n" for line in descriptions(gate, sources)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
