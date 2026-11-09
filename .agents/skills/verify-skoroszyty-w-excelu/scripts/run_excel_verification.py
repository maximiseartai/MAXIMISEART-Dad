"""Dad's week through real Microsoft Excel: period files open, Gotowość typed and saved in Excel, then Rozliczenia pracowników.

    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py
    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py --wzorce syntetyczne
    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py --kontrola-naprawy

Prints ``STEP <feature> | <id> | OK`` per checked behaviour, then ``VERIFY OK`` (or ``VERIFY FAIL``,
``VERIFY SKIP``) with the evidence directory. Evidence holds names, counts, addresses, and timings,
never a cell value. No step waits for a human, except the opt-in ``--kontrola-naprawy``.
"""

from __future__ import annotations

from argparse import Namespace, RawDescriptionHelpFormatter
from contextlib import suppress
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

import openpyxl

import excel

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.collective_layout import FIRST_DATA_ROW as FIRST_ROW, HEADER_ROW, QUANTITY_COLUMNS, REMARKS
from skrypt_skilla import SKIPPED, Parser, create_run_root, new_run
from atrapy.preparation import COLLECTIVE_FILE_NAME, INTERNAL_SETTLEMENT_NAME
from atrapy.scenariusz_rozliczen import (
    COLLECTIVE_TEMPLATE_NAME,
    FILLED_ORDERS,
    INTERNAL_TEMPLATE_NAME,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    ROW_MARKER,
    TEMPLATES_DIRECTORY,
    WORKER_ORDERS,
    WORKER_SETTLEMENTS_DIRECTORY,
    WORKER_TEMPLATE_NAME,
    order_number,
    worker_settlement_name,
)
from atrapy.scenariusz_rozliczen import QUANTITIES as ORDER_QUANTITIES
from atrapy.settlement import PERIOD, WORKERS

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
OTHER_SKILL = REPO_ROOT / ".agents" / "skills" / "verify-rozliczenia" / "scripts"
PROCESS_SCRIPT = REPO_ROOT / "tools" / "uruchom_proces.py"

# Exit code of the machine script for Wymaga sprawdzenia.
NEEDS_REVIEW_EXIT = 2
TEMPLATE_NAMES = (INTERNAL_TEMPLATE_NAME, COLLECTIVE_TEMPLATE_NAME, WORKER_TEMPLATE_NAME)
LAST_SCANNED_ROW = 60
INPUT_COLUMNS = range(QUANTITY_COLUMNS.start, REMARKS + 1)  # N:AT, what Dad types
CALCULATED = "AU{row}:AX{row}"  # amounts; AY looks up the Słownik, which is #N/D without the Słownik itself
FORMULAS = "AU{row}:AY{row}"
FILLED = tuple(order_number(number) for number in FILLED_ORDERS)
WORKER_FILES = {
    WORKERS[worker]: tuple(order_number(number) for number in numbers) for worker, numbers in WORKER_ORDERS.items()
}
# Wyróżnienia of the synthetic Rejestr: ADRES of order 2 yellow with bold dark red, ADRES of order 4 blue, WYKONAWCA
# of order 4 italic, ADRES of orders 7 and 6 none. Excel shows no fill as white and the automatic colour as black.
HIGHLIGHTS = {
    (order_number(2), "adres"): (0xFFFF00, 0xC00000, True, False),
    (order_number(4), "adres"): (0x00B0F0, 0x000000, False, False),
    (order_number(4), "wykonawca"): (0xFFFFFF, 0x000000, False, True),
    (order_number(7), "adres"): (0xFFFFFF, 0x000000, False, False),
    (order_number(6), "adres"): (0xFFFFFF, 0x000000, False, False),
}
# Ilości usług Przygotowanie writes from the Reguły ilości for the fixture's URZĄDZENIA and UMOWA.
QUANTITIES = {order_number(number): quantities for number, quantities in ORDER_QUANTITIES.items()}
# Ilości tylko dla INEA (ADR 0018): AP of the gniazdo order and AK of the technicolor one stay empty in the
# Rozliczenie pracownika, while the Plik zbiorczy keeps them.
INEA_ONLY = {order_number(8): "AP", order_number(9): "AK"}
QUANTITY_SUMS_ROW = 15
# CZYNNOŚCI ZREALIZOWANE of order 2 has two lines (scenariusz_rozliczen.completed_activities); every other
# Wiersz danych has one.
TWO_LINE_ORDER = order_number(2)


class VerificationFailure(RuntimeError):
    """A step did not end in the state Dad would see."""


def column_letter(number: int) -> str:
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


@dataclass
class Run:
    root: Path
    desk: Path
    evidence: Path
    # Process id of the Excel this run started, which the cleanup may stop when a dialog keeps it from quitting.
    started_excel: int | None = None
    steps: list[str] = field(default_factory=list)
    observations: dict[str, object] = field(default_factory=dict)

    @property
    def fixture(self) -> Path:
        return self.root / "okres"

    @property
    def config(self) -> Path:
        return self.fixture / TEMPLATES_DIRECTORY

    @property
    def period_folder(self) -> Path:
        return self.fixture / PERIODS_DIRECTORY / PERIOD

    @property
    def collective_file(self) -> Path:
        return self.period_folder / COLLECTIVE_FILE_NAME

    @property
    def internal_file(self) -> Path:
        return self.period_folder / INTERNAL_SETTLEMENT_NAME

    def worker_file(self, worker: str) -> Path:
        return self.period_folder / WORKER_SETTLEMENTS_DIRECTORY / worker_settlement_name(worker)

    def on_desk(self, path: Path) -> Path:
        """Byte copy of ``path`` on Excel's desk, where Excel opens it without a dialog."""

        copy = self.desk / path.name
        shutil.copyfile(path, copy)
        return copy

    def step(self, feature: str, identifier: str, detail: str = "") -> None:
        line = f"STEP {feature} | {identifier} | OK" + (f" | {detail}" if detail else "")
        self.steps.append(line)
        print(line, flush=True)

    def observe(self, key: str, value: object) -> None:
        self.observations[key] = value

    def write_evidence(self) -> None:
        (self.evidence / "drive.txt").write_text("\n".join(self.steps) + "\n", encoding="utf-8")
        (self.evidence / "excel.json").write_text(
            json.dumps(self.observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    return environment


def _python(
    run: Run, name: str, arguments: list[str], *, json_output: bool = False, accepted_exits: tuple[int, ...] = (0,)
) -> object:
    """Run a helper or the process script with this Python; record its output and exit code as evidence."""

    completed = subprocess.run(
        [sys.executable, *arguments], cwd=REPO_ROOT, env=_environment(), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
    )
    record: dict[str, object] = {"script": Path(arguments[0]).name, "exit_code": completed.returncode}
    if json_output:
        try:
            record["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            record["stdout"] = completed.stdout
        record["stderr"] = completed.stderr
        (run.evidence / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        text = f"exit_code={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        (run.evidence / f"{name}.txt").write_text(text, encoding="utf-8")
    if completed.returncode not in accepted_exits:
        print(completed.stdout + completed.stderr, file=sys.stderr)
        raise VerificationFailure(f"{name} exited {completed.returncode}")
    return record.get("result")


def _main_checkout_config() -> Path | None:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return (REPO_ROOT / common).resolve().parent / "config"


def _real_templates(explicit: Path | None) -> Path | None:
    """``--templates-dir``, else this checkout's ``config/``, else the main checkout's (worktrees lack the Wzorce)."""

    candidates = [explicit] if explicit else [REPO_ROOT / "config", _main_checkout_config()]
    for directory in candidates:
        if directory is not None and all((directory / name).is_file() for name in TEMPLATE_NAMES):
            return directory
    return None


# ---- steps -------------------------------------------------------------------------------------------


def create_fixture(run: Run, real_templates: Path | None) -> None:
    if real_templates is None:
        templates = run.root / "wzorce"
        _python(run, "wzorce", [str(REPO_ROOT / "tools" / "syntetyczne_wzorce.py"), str(templates)])
    else:
        templates = real_templates
    _python(
        run,
        "fixture",
        [
            str(OTHER_SKILL / "create_preparation_fixture.py"),
            "--root", str(run.fixture),
            "--with-worker-template",
            "--templates-from", str(templates),
        ],
    )


def doctor(run: Run) -> None:
    _python(run, "doctor", [str(SCRIPT.parent / "excel_doctor.py"), "--root", str(run.root), "--desk", str(run.desk)])


def preparation(run: Run) -> None:
    result = _python(
        run,
        "przygotowanie",
        [
            str(PROCESS_SCRIPT), "preparation",
            "--register", str(run.fixture / REGISTER_NAME),
            "--periods-directory", str(run.fixture / PERIODS_DIRECTORY),
            "--period", PERIOD,
            "--config", str(run.config / "worker_mapping.yaml"),
            "--internal-template", str(run.config / TEMPLATE_NAMES[0]),
            "--collective-template", str(run.config / TEMPLATE_NAMES[1]),
            "--metrics", str(run.root / "przygotowanie-metrics.jsonl"),
        ],
        json_output=True,
        accepted_exits=(0, NEEDS_REVIEW_EXIT),
    )
    expect(isinstance(result, dict), "Przygotowanie printed no result")
    assert isinstance(result, dict)
    # Przygotowanie ends a write Wymaga sprawdzenia only for the Ilości usług warnings (preparation_process._finished).
    expect(
        result["result"] == "WYMAGA_SPRAWDZENIA", "Przygotowanie did not end Wymaga sprawdzenia for the Ilości usług warnings"
    )
    expect(run.collective_file.is_file() and run.internal_file.is_file(), "Przygotowanie left no period files")


def settlement(run: Run) -> None:
    result = _python(
        run,
        "przebieg",
        [
            str(PROCESS_SCRIPT), "settlement",
            "--source", str(run.collective_file),
            "--config", str(run.config / "worker_mapping.yaml"),
            "--worker-template", str(run.config / TEMPLATE_NAMES[2]),
            "--metrics", str(run.root / "przebieg-metrics.jsonl"),
        ],
        json_output=True,
    )
    if not isinstance(result, dict) or result.get("result") != "OK":
        raise VerificationFailure("Przebieg rozliczeń did not end OK")
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    expect(figures.get("Zapisane szablony") == len(WORKER_FILES), "Przebieg did not write three Szablony pracowników")


@dataclass(frozen=True)
class Layout:
    """Columns found by header in row 17, as the processes find them."""

    columns: dict[str, int]

    @property
    def order(self) -> int:
        return self.columns["numer zl."]


def _layout(path: Path) -> Layout:
    headers = [cell.text.strip().casefold() for cell in excel.read(path, f"A{HEADER_ROW}:AT{HEADER_ROW}")[0]]
    columns: dict[str, int] = {}
    for name in ("numer zl.", "adres", "wykonawca", "data"):
        expect(headers.count(name) == 1, f"{path.name}: header {name.upper()} not found once in row {HEADER_ROW}")
        columns[name] = headers.index(name) + 1
    return Layout(columns)


def _order_rows(path: Path, layout: Layout) -> dict[str, int]:
    letter = column_letter(layout.order)
    cells = excel.read(path, f"{letter}{FIRST_ROW}:{letter}{LAST_SCANNED_ROW}")
    return {row[0].text: FIRST_ROW + index for index, row in enumerate(cells) if not row[0].empty}


def _reference(run: Run, name: str) -> tuple[list[str], list[str]]:
    """Link names and row-18 formulas of a Wzorzec as Excel reads them; the Wzorzec is closed again."""

    template = run.on_desk(run.config / name)
    seconds = excel.open_file(template)
    try:
        links = excel.link_names(template)
        formulas = excel.formulas_r1c1(template, FORMULAS.format(row=FIRST_ROW))
    finally:
        excel.close(template)
    run.observe(f"wzorzec:{name}", {"open_seconds": seconds, "links": len(links), "formula_cells": len(formulas)})
    expect(bool(links), f"Excel sees no external link in {name}")
    return links, formulas


def _check_formulas(path: Path, rows: dict[str, int], reference: list[str], *, label: str) -> None:
    """Every Wiersz danych keeps the Wzorzec's formulas, and Excel shows no error in its amounts."""

    for row in rows.values():
        expect(excel.formulas_r1c1(path, FORMULAS.format(row=row)) == reference, f"{label}: row {row} formulas differ from the Wzorzec")
        errors = excel.error_cells(path, CALCULATED.format(row=row))
        expect(errors is None, f"{label}: Excel shows errors in {errors}")


# (address, location) of one cell Hiperłącze, keyed by column letter within A:AT.
RowLinks = dict[str, tuple[str | None, str | None]]


def _hyperlinks(path: Path, rows: dict[str, int]) -> dict[str, RowLinks]:
    """Hiperłącza in A:AT of each order's row, as the file's bytes hold them (openpyxl, not Excel, not the tool's reader)."""

    workbook = openpyxl.load_workbook(path)
    try:
        sheet = workbook.worksheets[0]
        return {
            order: {
                cell.column_letter: (cell.hyperlink.target, cell.hyperlink.location)
                for cell in sheet[f"A{row}:AT{row}"][0]
                if cell.hyperlink is not None
            }
            for order, row in rows.items()
        }
    finally:
        workbook.close()


def _check_highlights(path: Path, rows: dict[str, int], layout: Layout, *, label: str) -> int:
    checked = 0
    for (order, header), expected in HIGHLIGHTS.items():
        if order not in rows:
            continue
        address = f"{column_letter(layout.columns[header])}{rows[order]}"
        expect(excel.fill(path, address) == expected, f"{label}: Wyróżnienie in {address} is not what the Rejestr has")
        checked += 1
    return checked


def _check_row_look(path: Path, rows: dict[str, int], layout: Layout, *, label: str) -> tuple[float, dict[str, str]]:
    """Excel auto-fits the Wiersze danych: one line at the sheet's standard height, the two-line row taller.

    Returns the standard height and the DATA of every order as Excel shows it in its number format.
    """

    standard = excel.standard_height(path)
    heights = {order: excel.row_heights(path, row, row)[0] for order, row in rows.items()}
    tall = [str(rows[order]) for order, height in heights.items() if order != TWO_LINE_ORDER and height != standard]
    expect(not tall, f"{label}: rows {', '.join(tall)} with one line are not {standard} pt high")
    if TWO_LINE_ORDER in rows:
        expect(heights[TWO_LINE_ORDER] > standard, f"{label}: row {rows[TWO_LINE_ORDER]} with two lines is not taller")
    date = column_letter(layout.columns["data"])
    return standard, {order: excel.shown_text(path, f"{date}{row}") for order, row in rows.items()}


def _check_quantities(path: Path, rows: dict[str, int], *, label: str) -> int:
    """Excel holds the Ilości usług in N:AP of every order and row 15 sums them; returns the non-zero cells."""

    letters = [column_letter(column) for column in QUANTITY_COLUMNS]
    span = f"{letters[0]}{{row}}:{letters[-1]}{{row}}"
    for order, quantities in QUANTITIES.items():
        cells = excel.read(path, span.format(row=rows[order]))[0]
        held = {letter: cell.number for letter, cell in zip(letters, cells, strict=True) if not cell.empty and cell.number}
        expect(held == quantities, f"{label}: row {rows[order]} holds other Ilości usług in {', '.join(sorted(held.keys() ^ quantities.keys())) or 'N:AP'}")
    sums = excel.read(path, span.format(row=QUANTITY_SUMS_ROW))[0]
    expected = {letter: sum(quantities.get(letter, 0) for quantities in QUANTITIES.values()) for letter in letters}
    wrong = [letter for letter, cell in zip(letters, sums, strict=True) if cell.kind != "n" or cell.number != expected[letter]]
    expect(not wrong, f"{label}: row {QUANTITY_SUMS_ROW} does not sum the Ilości usług in {', '.join(wrong)}")
    return sum(len(quantities) for quantities in QUANTITIES.values())


def period_files_open(
    run: Run, collective_reference: tuple[list[str], list[str]]
) -> tuple[Path, Layout, dict[str, str]]:
    """Feature otwarcie-plikow-okresu: both period files open in Excel without a dialog; the Plik zbiorczy stays open."""

    feature = "otwarcie-plikow-okresu"
    internal = run.on_desk(run.internal_file)
    seconds = excel.open_file(internal)
    excel.close(internal)
    run.observe("otwarcie:rozliczenie-wewnetrzne", {"open_seconds": seconds})
    run.step(feature, "rozliczenie-wewnetrzne-bez-okna", f"open_seconds={seconds}")

    collective = run.on_desk(run.collective_file)
    seconds = excel.open_file(collective)
    run.step(feature, "plik-zbiorczy-bez-okna", f"open_seconds={seconds}")
    links = excel.link_names(collective)
    expect(links == collective_reference[0], "Plik zbiorczy links to other workbooks than its Wzorzec")
    run.step(feature, "plik-zbiorczy-lacze", f"links={len(links)}")
    layout = _layout(collective)
    rows = _order_rows(collective, layout)
    expected_orders = {order for orders in WORKER_FILES.values() for order in orders}
    expect(expected_orders <= set(rows), "Plik zbiorczy lacks Zlecenia skuteczne of the Rejestr")
    _check_formulas(collective, rows, collective_reference[1], label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-formuly", f"rows={len(rows)}")
    quantities = _check_quantities(collective, rows, label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-ilosci", f"cells={quantities} | sums_row={QUANTITY_SUMS_ROW}")
    highlights = _check_highlights(collective, rows, layout, label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-wyroznienia", f"cells={highlights}")
    standard, dates = _check_row_look(collective, rows, layout, label="Plik zbiorczy")
    run.step(feature, "plik-zbiorczy-wyglad-wiersza", f"rows={len(rows)} | one_line_pt={standard}")
    run.observe("otwarcie:plik-zbiorczy", {"open_seconds": seconds, "links": len(links), "rows": len(rows)})
    return collective, layout, dates


def _entries(index: int, order: str) -> dict[int, str]:
    """What Dad types into one Wiersz danych: distinct quantities, a charge, remarks; numbers as Excel input."""

    suffix = order.removeprefix("PREP-SYN-ZL-")
    values = {column: str(10 * (index + 1) + column - 13) for column in QUANTITY_COLUMNS}
    values[43] = f"PREP-SYN-OBC-{suffix}"
    values[44] = f"{25.5 + index}"
    values[45] = str(10 + index)
    values[46] = f"PREP-SYN-UWAGI-{suffix}"
    return values


def _matches(cell: excel.Cell, typed: str) -> bool:
    try:
        number = float(typed)
    except ValueError:
        return cell.kind == "s" and cell.text == typed
    return cell.kind == "n" and cell.number == number


def readiness(run: Run, collective: Path, layout: Layout) -> tuple[dict[str, list[excel.Cell]], dict[str, RowLinks]]:
    """Feature gotowosc-w-excelu: type N:AT like Dad, save and close in Excel; returns A:AT and Hiperłącza of every order."""

    feature = "gotowosc-w-excelu"
    rows = _order_rows(collective, layout)
    links_before = _hyperlinks(run.collective_file, rows)
    order_letter = column_letter(layout.order)
    unlinked = [str(rows[order]) for order, links in links_before.items() if order_letter not in links]
    expect(not unlinked, f"Przygotowanie left NUMER ZL. without its Rejestr Hiperłącze in rows {', '.join(unlinked)}")
    for index, order in enumerate(FILLED):
        entries = _entries(index, order)
        excel.type_row(collective, f"N{rows[order]}:AT{rows[order]}", [entries[column] for column in INPUT_COLUMNS])
        typed = excel.read(collective, f"N{rows[order]}:AT{rows[order]}")[0]
        differing = [
            f"{column_letter(column)}({cell.kind})"
            for column, cell in zip(INPUT_COLUMNS, typed, strict=True)
            if not _matches(cell, entries[column])
        ]
        expect(not differing, f"Excel holds other values than typed in row {rows[order]}: {', '.join(differing)}")
        amount = excel.read(collective, CALCULATED.format(row=rows[order]))[0][0]
        expect(amount.kind == "n" and amount.number > 0, f"Excel calculated no amount in AU{rows[order]}")
    run.step(feature, "wpisy", f"rows={len(FILLED)} | columns=N:AT | amounts_calculated=true")
    expected = {order: excel.read(collective, f"A{row}:AT{row}")[0] for order, row in rows.items()}
    excel.save(collective)
    excel.close(collective)
    run.step(feature, "zapis-i-zamkniecie", "lock_removed=true")
    expect(collective.read_bytes() != run.collective_file.read_bytes(), "Excel did not write the Plik zbiorczy")
    with zipfile.ZipFile(collective) as archive:
        application = archive.read("docProps/app.xml").decode("utf-8")
        link_parts = [name for name in archive.namelist() if name.startswith("xl/externalLinks/externalLink")]
    expect("Microsoft Macintosh Excel" in application, "the Plik zbiorczy was not last saved by Excel")
    expect(bool(link_parts), "Excel's save dropped the external link of the Plik zbiorczy")
    run.step(feature, "lacze-po-zapisie", f"external_link_parts={len(link_parts)}")
    links_after = _hyperlinks(collective, rows)
    changed = [str(rows[order]) for order in rows if links_after[order] != links_before[order]]
    expect(not changed, f"Excel's save changed the Hiperłącza of the Plik zbiorczy in rows {', '.join(changed)}")
    run.step(feature, "hiperlacza-po-zapisie", f"rows={len(rows)} | column={order_letter}")
    # Dad saves in his Folder okresu; the desk copy goes back byte for byte.
    shutil.copyfile(collective, run.collective_file)
    digest = hashlib.sha256(run.collective_file.read_bytes()).hexdigest()
    run.observe("gotowosc", {"rows_typed": len(FILLED), "saved_by": "Microsoft Macintosh Excel", "external_link_parts": len(link_parts), "sha256": digest})
    return expected, links_after


def worker_files(
    run: Run,
    expected: dict[str, list[excel.Cell]],
    expected_links: dict[str, RowLinks],
    worker_reference: tuple[list[str], list[str]],
    collective_dates: dict[str, str],
) -> None:
    """Feature rozliczenia-pracownikow-w-excelu: every Rozliczenie pracownika opens and shows the Gotowość."""

    feature = "rozliczenia-pracownikow-w-excelu"
    for worker, orders in WORKER_FILES.items():
        path = run.on_desk(run.worker_file(worker))
        label = f"Rozliczenie {worker}"
        seconds = excel.open_file(path)
        try:
            run.step(feature, "bez-okna", f"{worker} | open_seconds={seconds}")
            sources = excel.link_names(path)
            expect(sources == worker_reference[0], f"{label} links to other workbooks than its Wzorzec")
            run.step(feature, "lacze", f"{worker} | links={len(sources)}")
            layout = _layout(path)
            rows = _order_rows(path, layout)
            expect(tuple(rows) == orders, f"{label} holds other Zlecenia or another order than the Plik zbiorczy")
            inea_only = 0
            for order, row in rows.items():
                shown = excel.read(path, f"A{row}:AT{row}")[0]
                differing = []
                for column, (left, right) in enumerate(zip(shown, expected[order], strict=True), start=1):
                    letter = column_letter(column)
                    if INEA_ONLY.get(order) == letter:
                        expect(not right.empty, f"Plik zbiorczy row of {order} has no Ilość tylko dla INEA in {letter}")
                        if not left.empty:
                            differing.append(letter)
                        inea_only += 1
                    elif left != right:
                        differing.append(letter)
                expect(not differing, f"{label} row {row} differs from the Plik zbiorczy in {','.join(differing)}")
            run.step(feature, "wiersze-a-at", f"{worker} | rows={len(rows)} | inea_only_empty={inea_only}")
            links = _hyperlinks(run.worker_file(worker), rows)
            unequal = [str(row) for order, row in rows.items() if links[order] != expected_links[order]]
            expect(not unequal, f"{label} rows {', '.join(unequal)} lack the Hiperłącza of the Plik zbiorczy Excel saved")
            run.step(feature, "hiperlacza", f"{worker} | rows={len(rows)}")
            _check_formulas(path, rows, worker_reference[1], label=label)
            for order in set(rows).intersection(FILLED):
                amount = excel.read(path, CALCULATED.format(row=rows[order]))[0][0]
                expect(amount.kind == "n" and amount.number > 0, f"{label}: Excel shows no amount for the Gotowość")
            run.step(feature, "formuly", worker)
            highlights = _check_highlights(path, rows, layout, label=label)
            run.step(feature, "wyroznienia", f"{worker} | cells={highlights}")
            standard, dates = _check_row_look(path, rows, layout, label=label)
            differing_dates = [str(rows[order]) for order in rows if dates[order] != collective_dates[order]]
            expect(not differing_dates, f"{label}: DATA in rows {', '.join(differing_dates)} shows otherwise than in the Plik zbiorczy")
            run.step(feature, "wyglad-wiersza", f"{worker} | one_line_pt={standard} | data_as_plik_zbiorczy=true")
            run.observe(f"rozliczenie:{worker}", {"open_seconds": seconds, "rows": len(rows), "highlights": highlights})
        finally:
            excel.close(path)


def repair_control(run: Run) -> None:
    """Feature okno-naprawy: a copy with a broken external link must stop the run as a dialog, not open."""

    feature = "okno-naprawy"
    broken = run.desk / "Zepsute łącze.xlsx"
    with zipfile.ZipFile(run.worker_file("Darek Fikcyjny")) as original, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as copy:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "xl/externalLinks/externalLink1.xml":
                data = data.replace(b"<sheetDataSet>", b"<sheetDataSet><zepsute>", 1)
            copy.writestr(info, data)
    try:
        excel.open_file(broken, timeout=30)
    except excel.ExcelDialog:
        found = excel.dialogs()
        expect(bool(found), "Excel missed the deadline but shows no dialog")
        run.step(feature, "wykryte", f"dialogs={len(found)} | {found[0].split(' | ')[-1]}")
    else:
        excel.close(broken)
        raise VerificationFailure("Excel opened a workbook with a broken external link without a dialog")
    print("ACTION | W Excelu kliknij „Nie” w oknie o zawartości, która powoduje problem.", flush=True)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        time.sleep(2)
        if not excel.dialogs():
            run.step(feature, "okno-zamkniete")
            return
    raise VerificationFailure("the repair dialog was not answered within 10 minutes")


# ---- orchestration -----------------------------------------------------------------------------------


def _sweep(run: Run) -> None:
    """Close, without saving, what runs killed before their cleanup left in Excel, and remove their desks.

    Under the lock no other run drives Excel, so every workbook and desk below ``excel.DESK`` is stranded.
    It runs before the doctor, which refuses an Excel holding a workbook named like this run's. A dialog raises
    ``ExcelDialog`` here, before the run opens anything into it.
    """

    run.observe("excel_workbooks_before", len(excel.open_paths()) if excel.running() else 0)
    stale = excel.close_under(excel.DESK)
    desks = [path for path in excel.DESK.iterdir() if path.is_dir() and path != run.desk]
    for desk in desks:
        shutil.rmtree(desk)
    run.observe("stale_workbooks_closed", len(stale))
    run.observe("stale_desks_removed", len(desks))


def _drive(run: Run, args: Namespace, real_templates: Path | None) -> None:
    """The steps of Drive (SKILL.md), from the fixture to the last workbook checked."""

    create_fixture(run, real_templates)
    run.desk.mkdir(parents=True)
    doctor(run)
    preparation(run)
    if not excel.running():
        run.started_excel = excel.launch()
    collective_reference = _reference(run, TEMPLATE_NAMES[1])
    worker_reference = _reference(run, TEMPLATE_NAMES[2])
    collective, layout, collective_dates = period_files_open(run, collective_reference)
    expected, expected_links = readiness(run, collective, layout)
    settlement(run)
    worker_files(run, expected, expected_links, worker_reference, collective_dates)
    if args.kontrola_naprawy:
        repair_control(run)


def _holds_others(desk: Path) -> bool:
    """Whether Excel names a workbook outside ``desk``, such as one the user opened in the Excel this run started.

    While a modal dialog is up Excel names none (``ExcelDialog``), so then no workbook is known to be the user's.
    """

    try:
        return any(not Path(path).is_relative_to(desk) for path in excel.open_paths())
    except excel.ExcelError:
        return False


def _cleanup(run: Run) -> tuple[list[str], bool]:
    """Close this run's workbooks, quit an Excel that holds no workbook, remove scratch; evidence stays.

    Returns the notes and whether this run's workbooks may still be open. Then the desk stays, because Excel
    still holds its files, and the next run's sweep closes them once the dialog is answered.
    """

    notes: list[str] = []
    try:
        notes.append(f"closed_workbooks={len(excel.close_under(run.desk))}")
        closed = True
    except excel.ExcelError as exc:
        closed = False
        notes.append(f"close_failed={type(exc).__name__}")
    try:
        if run.started_excel is not None and excel.dialogs() and excel.pid() == run.started_excel and not _holds_others(run.desk):
            notes.append(f"excel_stopped={str(excel.terminate(run.started_excel)).lower()}")
        elif excel.dialogs():
            notes.append("excel_dialog_left=true (answer the dialog in Excel by hand)")
        else:
            # Also an Excel that ran before the run: one process grows with every run until it hangs.
            run.observe("excel_rss_mb_end", excel.rss_mb())
            notes.append(f"excel_quit={str(excel.quit_if_idle()).lower()}")
    except (excel.ExcelError, subprocess.SubprocessError, OSError) as exc:
        notes.append(f"excel_quit_failed={type(exc).__name__}")
    run.observe("excel_rss_mb_after", excel.rss_mb())
    try:
        run.observe("excel_workbooks_after", len(excel.open_paths()) if excel.running() else 0)
    except excel.ExcelError as exc:
        run.observe("excel_workbooks_after", type(exc).__name__)
    left_open = not closed and excel.running() and run.desk.exists()
    if left_open:
        notes.append(f"desk_kept={run.desk}")
    else:
        shutil.rmtree(run.desk, ignore_errors=True)
    completed = subprocess.run(
        [sys.executable, str(OTHER_SKILL / "cleanup.py"), "--root", str(run.root)],
        capture_output=True, text=True, check=False,
    )
    removed = completed.returncode == 0 and not run.root.exists() and not run.desk.exists()
    notes.append(f"scratch_removed={str(removed).lower()}")
    (run.evidence / "cleanup.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    return notes, left_open


def _hygiene(run: Run) -> None:
    """Evidence names files and counts; it never carries a cell value of the synthetic Rejestr."""

    for path in run.evidence.iterdir():
        expect(ROW_MARKER not in path.read_text(encoding="utf-8"), f"{path.name} carries row content")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_run_dir()
    parser.add_argument("--wzorce", choices=("prawdziwe", "syntetyczne"), default="prawdziwe")
    parser.add_argument("--templates-dir", type=Path, help="directory with the three real Wzorce (default: config/)")
    parser.add_argument("--kontrola-naprawy", action="store_true", help="also prove the dialog detector; needs one click")
    args = parser.parse_args(argv)

    # Taken before Excel is looked at, because a second run would close or type into the first run's workbooks.
    try:
        lock = excel.claim(owner=str(REPO_ROOT))
    except excel.ExcelError as exc:
        print(f"VERIFY FAIL | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    run_id = f"excel-{uuid.uuid4().hex[:12]}"
    paths = new_run(args.run_dir, run_id)
    evidence = paths.evidence
    run = Run(paths.root, excel.DESK / run_id, evidence)
    real_templates = None
    if args.wzorce == "prawdziwe":
        real_templates = _real_templates(args.templates_dir)
        if real_templates is None:
            print(f"VERIFY SKIP | wzorce=prawdziwe | no config/ holds all three Wzorce; use --wzorce syntetyczne | evidence={evidence}")
            return SKIPPED
    run.observe("excel_version", excel.installed_version())
    run.observe("wzorce", args.wzorce)
    excel_was_running = excel.running()
    run.observe("excel_was_running", excel_was_running)
    run.observe("excel_rss_mb_before", excel.rss_mb())
    outcome = "OK"
    try:
        create_run_root(run.root)
        _sweep(run)
        _drive(run, args, real_templates)
    except (VerificationFailure, excel.ExcelError, subprocess.SubprocessError, OSError) as exc:
        outcome = "FAIL"
        if not excel_was_running and run.started_excel is None and excel.running():
            # Without a known process id the cleanup never stops this Excel, which leaves it to its owner.
            with suppress(excel.ExcelError):
                run.started_excel = excel.pid()
        run.observe("failure", f"{type(exc).__name__}: {exc}")
        print(f"VERIFY FAIL | {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        run.write_evidence()
        notes, left_open = _cleanup(run)
        run.write_evidence()
        lock.close()
    if left_open:
        outcome = "FAIL"
        print(f"VERIFY FAIL | Excel may still hold this run's workbooks; their desk stays at {run.desk}", file=sys.stderr)
    try:
        _hygiene(run)
    except VerificationFailure as exc:
        outcome = "FAIL"
        print(f"VERIFY FAIL | {exc}", file=sys.stderr)
    evidence_kept = (evidence / "drive.txt").is_file()
    print(
        f"VERIFY {outcome} | wzorce={args.wzorce} | steps={len(run.steps)} | {' | '.join(notes)} "
        f"| evidence_kept={str(evidence_kept).lower()} | evidence={evidence}"
    )
    return 0 if outcome == "OK" and evidence_kept else 1


if __name__ == "__main__":
    raise SystemExit(main())
