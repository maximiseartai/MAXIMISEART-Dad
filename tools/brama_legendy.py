"""Brama Legendy czynności: liczy, w ilu wierszach z kodem legenda daje to, co wpisał tata; tylko na Macu Maksa, przed Wydaniem z legendą.

Puszcza Legendę czynności (``--legenda``: plik ``legenda-czynnosci.yaml`` z Ustawień taty; bez niego legenda z
Wydania) na Plikach zbiorczych wypełnionych przez tatę: ``.xlsx`` z dysku (wartości, kwota w ``AS`` i kolory) albo
plik Logów Wyceny w efenix z dysku taty lub z Archiwum Logów okresu (``.json``, ``.json.gz``), z którego czyta tylko
Kopię wejścia Pliku zbiorczego: ``N:AP`` i ``CZYNNOŚCI ZREALIZOWANE``, bo kolorów Logi nie mają. Pliki są tylko czytane.

Rachunek wiersza jest rachunkiem Przygotowania pliku zbiorczego: ``read_codes`` z ``CZYNNOŚCI ZREALIZOWANE``, a w
kolumnie Ilości usług wartość legendy dodana do wartości Reguł ilości z Wydania (``quantity_engine.evaluate``), jak w
``preparation_files``. Wiersz z kodem to wiersz, w którym legenda znalazła kod, który coś wyznacza. W nim brama
porównuje z tatą kolumny legendy (każda kolumna Ilości usług jej kodów), a z dysku także kwotę w ``AS`` i kolory
kolumn, które legenda wypełnia (jest albo nie ma, zielony, czerwony albo inny kolor taty). Wiersz bez kodu z wpisem
taty to wiersz, w którym tata wpisał w kolumnie legendy albo z opisu technika (``DESCRIPTION_COLUMNS``) coś innego niż
Reguły ilości, albo kwotę w ``AS``. Wiersz, którego ``DATA`` nie jest datą, ma tylko liczbę, bo bez pory nie ma wyniku
Reguł ilości.

Na stdout trafiają same liczby, identyfikatory kodów legendy, liczby z kodów spoza przedziałów i litery kolumn: bez
opisów technika, adresów i numerów, więc wynik można wkleić do PR. ``--opisy PLIK`` zapisuje lokalnie każdy wiersz z
różnicą, bez kodu z wpisem taty i z kodem spoza przedziałów razem z numerem wiersza i treścią ``CZYNNOŚCI
ZREALIZOWANE``; plik w repozytorium (publicznym) jest odrzucony.

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
from typing import Final, Literal

from pydantic import TypeAdapter, ValidationError
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia.activity_legend import (
    AMOUNT_COLUMN,
    FILL_COLUMNS,
    ActivityLegend,
    CodesRead,
    ColumnByNumber,
    FillColour,
    FixedColumn,
    LegendProblem,
    read_codes,
)
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, parse_activity_legend
from rozliczenia.centrum.run_logs import LoggedCell, LoggedInputFile, LoggedTyped
from rozliczenia.collective_layout import DATA_ROW_COLUMNS, INPUT_COLUMNS, QUANTITY_LETTERS, letter
from rozliczenia.dad_files import DadFiles
from rozliczenia.highlights import PLAIN, Highlights
from rozliczenia.order_facts import MissingHeaders, OrderFacts, TataValue, collective_orders, tata_value
from rozliczenia.quantity_engine import DESCRIPTION_COLUMNS, Quantities, QuantityRules, evaluate
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES
from rozliczenia.register_columns import COMPLETED
from rozliczenia.row_look import GENERAL
from rozliczenia.text import normalize_text
from rozliczenia.workbook_files import DataCell, DataRow, header_columns, read_data_rows

ROOT: Final = Path(__file__).resolve().parents[1]
OTHER: Final = "inny"
NONE: Final = "brak"
Colour = FillColour | Literal["inny"]
"""Kolor wypełnienia komórki taty: zielony i czerwony legendy albo inny."""
Difference = tuple[str, str, str]
"""Kolumna (``kolor AF`` dla koloru), wartość legendy, wartość taty."""
_LOGS: Final = TypeAdapter(list[LoggedInputFile])
_EFENIX: Final = "efenix"


@dataclass(frozen=True)
class Look:
    """Kwota w ``AS`` i kolory wypełnienia komórek taty: tylko z Pliku zbiorczego na dysku."""

    amount: TataValue
    fills: Mapping[str, Colour]


@dataclass(frozen=True)
class DadRow:
    """Wiersz danych Pliku zbiorczego taty, jak go czyta brama."""

    number: int
    order: OrderFacts
    completed: str
    look: Look | None
    """``None``: Logi, które nie niosą kolorów."""


@dataclass(frozen=True)
class Source:
    label: str
    rows: tuple[DadRow, ...]
    looked: bool
    """Porównanie obejmuje ``AS`` i kolory (plik z dysku)."""


@dataclass(frozen=True)
class Checked:
    """Wiersz po rachunku bramy: wynik legendy, różnice z tatą (wiersz z kodem) i wpisy taty (wiersz bez kodu)."""

    row: DadRow
    codes: CodesRead
    differences: tuple[Difference, ...]
    entries: Mapping[str, TataValue]

    @property
    def coded(self) -> bool:
        return bool(self.codes.found)

    @property
    def code_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(found.code for found in self.codes.found))

    @property
    def kind(self) -> str:
        return "z samych kodów" if self.codes.only_codes else "kod obok opisu"


class Gate:
    """Rachunek wiersza bramy dla jednej Legendy czynności i Reguł ilości."""

    def __init__(self, legend: ActivityLegend, rules: QuantityRules) -> None:
        self.legend = legend
        self.rules = rules
        used = {column for code in legend.codes for column in _columns(code.column)}
        filled = {fill.column for code in legend.codes for fill in code.fills}
        self.columns = tuple(column for column in QUANTITY_LETTERS if column in used)
        self.fill_columns = tuple(column for column in FILL_COLUMNS if column in filled)
        self.entry_columns = tuple(column for column in QUANTITY_LETTERS if column in used or column in DESCRIPTION_COLUMNS)

    def check(self, row: DadRow) -> Checked | None:
        """Wiersz po rachunku; ``None``: ``DATA`` nie jest datą."""

        content = row.order.content
        if content is None:
            return None
        ruled = evaluate(self.rules, content).quantities
        codes = read_codes(self.legend, row.completed)
        if codes.found:
            return Checked(row, codes, self._differences(row, ruled, codes), {})
        return Checked(row, codes, (), self._entries(row, ruled))

    def _differences(self, row: DadRow, ruled: Quantities, codes: CodesRead) -> tuple[Difference, ...]:
        found: list[Difference] = []
        for column in self.columns:
            expected, tata = ruled.get(column, 0) + codes.quantities.get(column, 0), row.order.quantity(column)
            if expected != tata:
                found.append((column, str(expected), str(tata)))
        if row.look is not None:
            if codes.amount != row.look.amount:
                found.append((AMOUNT_COLUMN, str(codes.amount), str(row.look.amount)))
            for column in self.fill_columns:
                expected_colour, tata_colour = codes.fills.get(column), row.look.fills.get(column)
                if expected_colour != tata_colour:
                    found.append((f"kolor {column}", _colour(expected_colour), _colour(tata_colour)))
        return tuple(found)

    def _entries(self, row: DadRow, ruled: Quantities) -> dict[str, TataValue]:
        entries = {
            column: row.order.quantity(column)
            for column in self.entry_columns
            if row.order.quantity(column) != ruled.get(column, 0)
        }
        if row.look is not None and row.look.amount != 0:
            entries[AMOUNT_COLUMN] = row.look.amount
        return entries

    def compared(self, looked: bool) -> str:
        columns = " ".join(self.columns)
        if not looked:
            return f"{columns} (Logi: bez AS i kolorów)"
        return f"{columns}, {AMOUNT_COLUMN}, kolory {' '.join(self.fill_columns) or NONE}"


def _columns(choice: FixedColumn | ColumnByNumber | None) -> tuple[str, ...]:
    match choice:
        case None:
            return ()
        case FixedColumn(column=column):
            return (column,)
        case ColumnByNumber(ranges=ranges):
            return tuple(found.column for found in ranges)


def _colour(colour: Colour | None) -> str:
    return NONE if colour is None else str(colour)


def disk_rows(path: Path) -> Source:
    """Wiersze danych Pliku zbiorczego z dysku z kwotą w ``AS`` i kolorami."""

    read = read_data_rows(path, DadFiles(), despite_excel_lock=True)
    return Source(path.name, _rows(path.name, read.header, read.rows, looked=True), looked=True)


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
    return Source(label, _rows(label, header, rows, looked=False), looked=False)


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


def _rows(label: str, header: Mapping[str, int], rows: Sequence[DataRow], *, looked: bool) -> tuple[DadRow, ...]:
    orders = collective_orders(header, rows)
    if isinstance(orders, MissingHeaders):
        raise SystemExit(f"{label}: w wierszu nagłówka nie ma {', '.join(orders.headers)}")
    completed_column = header.get(normalize_text(COMPLETED.target_header))
    if completed_column is None:
        raise SystemExit(f"{label}: w wierszu nagłówka nie ma {COMPLETED.target_header}")
    completed = letter(completed_column)
    return tuple(
        DadRow(row.number, order, _text(row.value(completed)), _look(row) if looked else None)
        for row, order in zip(rows, orders, strict=True)
    )


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _look(row: DataRow) -> Look:
    cells = {letter(number): cell for number, cell in enumerate(row.cells, start=1)}
    fills = {column: colour for column in FILL_COLUMNS if (colour := _fill(cells[column].highlights)) is not None}
    return Look(tata_value(cells[AMOUNT_COLUMN].value), fills)


def _fill(highlights: Highlights) -> Colour | None:
    fill = highlights.fill
    if fill is None:
        return None
    rgb = getattr(getattr(fill, "fgColor", None), "rgb", None)
    if getattr(fill, "patternType", None) == "solid":
        return next((colour for colour in FillColour if colour.argb == rgb), OTHER)
    return OTHER


@dataclass(frozen=True)
class Tally:
    """Wiersze jednego albo wielu źródeł po rachunku bramy."""

    rows: int
    undated: int
    checked: tuple[Checked, ...]

    @classmethod
    def of(cls, gate: Gate, sources: Iterable[Source]) -> Tally:
        rows = [row for source in sources for row in source.rows]
        results = [gate.check(row) for row in rows]
        return cls(len(rows), sum(result is None for result in results), tuple(result for result in results if result is not None))

    def report(self) -> list[str]:
        coded = [row for row in self.checked if row.coded]
        only = [row for row in coded if row.codes.only_codes]
        beside = [row for row in coded if not row.codes.only_codes]
        lines = [
            f"wiersze danych: {self.rows} | z kodem: {len(coded)} | z samych kodów: {len(only)}"
            f" | kod obok opisu: {len(beside)} | DATA nie jest datą: {self.undated}",
            f"zgodne z tatą wiersze z kodem: {_share(coded)} | z samych kodów: {_share(only)} | kod obok opisu: {_share(beside)}",
        ]
        codes = Counter(code for row in coded for code in row.code_ids)
        lines.append(f"kody (wiersze): {' '.join(f'{code}={count}' for code, count in codes.most_common()) or NONE}")
        classes = Counter((row.kind, row.code_ids, row.differences) for row in coded if row.differences)
        lines.append(f"-- różnice (wiersze | wiersz | kody | kolumna: legenda, tata): {len(classes)} klas")
        for (kind, code_ids, differences), count in sorted(classes.items(), key=lambda item: (-item[1], item[0])):
            shown = "; ".join(f"{column}: legenda {legend}, tata {tata}" for column, legend, tata in differences)
            lines.append(f"{count} | {kind} | {', '.join(code_ids)} | {shown}")
        outside = Counter((found.code, found.number) for row in self.checked for found in row.codes.out_of_range)
        lines.append(
            "-- kody spoza przedziałów (kod liczba → wiersze): "
            + (" ".join(f"{code} {number}→{count}" for (code, number), count in sorted(outside.items(), key=str)) or NONE)
        )
        uncoded = [row for row in self.checked if not row.coded and row.entries]
        entries = Counter(column for row in uncoded for column in row.entries)
        ordered = [column for column in (*QUANTITY_LETTERS, AMOUNT_COLUMN) if column in entries]
        lines.append(
            f"-- wiersze bez kodu z wpisem taty: {len(uncoded)} | " + (" ".join(f"{column}={entries[column]}" for column in ordered) or NONE)
        )
        return lines


def _share(rows: Sequence[Checked]) -> str:
    part, whole = sum(not row.differences for row in rows), len(rows)
    return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else "0/0"


def descriptions(gate: Gate, sources: Sequence[Source]) -> list[str]:
    """Wiersze z różnicą, bez kodu z wpisem taty i z kodem spoza przedziałów z treścią ``CZYNNOŚCI ZREALIZOWANE``:
    tylko do pliku lokalnego."""

    lines: list[str] = []
    for source in sources:
        for row in filter(None, map(gate.check, source.rows)):
            text = " ".join(row.row.completed.split())
            where = f"{source.label} | wiersz {row.row.number}"
            if row.differences:
                shown = "; ".join(f"{column}: legenda {legend}, tata {tata}" for column, legend, tata in row.differences)
                lines.append(f"{where} | różnica | {row.kind} | {', '.join(row.code_ids)} | {shown} | {text}")
            if row.entries:
                shown = " ".join(f"{column}={value}" for column, value in row.entries.items())
                lines.append(f"{where} | bez kodu z wpisem taty | {shown} | {text}")
            if row.codes.out_of_range:
                shown = ", ".join(f"{found.code} {found.number}" for found in row.codes.out_of_range)
                lines.append(f"{where} | spoza przedziałów | {shown} | {text}")
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
