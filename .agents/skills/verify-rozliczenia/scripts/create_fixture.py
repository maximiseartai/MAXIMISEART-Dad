"""Create disposable synthetic workbooks for the rozliczenia verification skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from openpyxl import Workbook
from openpyxl.styles import PatternFill

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from skrypt_skilla import Parser, create_run_root

from tests.fixtures.scenariusz_rozliczen import (
    SETTLEMENT_CITY,
    SETTLEMENT_ORDER_LINK,
    SETTLEMENT_ROWS,
    UNMAPPED_ROW,
    WORKER_TEMPLATE_NAME,
)
from tests.fixtures.settlement import PERIOD, SOURCE_NAME, WORKERS, write_mapping
from tests.fixtures.workbooks import active_worksheet


def _write_template(path: Path) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    sheet["A17"].fill = PatternFill(fill_type="solid", fgColor="00AA55")
    sheet.cell(18, 47).value = "=N18"
    sheet.cell(19, 47).value = "=N19"
    sheet.cell(18, 14).value = 0
    sheet.cell(19, 14).value = 0
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = 17.5
    workbook.save(path)
    workbook.close()


def _write_source(path: Path, *, include_unmapped: bool) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet.cell(17, 8).value = "WYKONAWCA"
    rows = [*SETTLEMENT_ROWS, UNMAPPED_ROW] if include_unmapped else SETTLEMENT_ROWS
    for row_number, (worker, marker) in enumerate(rows, start=18):
        sheet.cell(row_number, 1).value = SETTLEMENT_CITY
        sheet.cell(row_number, 6).value = marker
        sheet.cell(row_number, 6).hyperlink = f"{SETTLEMENT_ORDER_LINK}{row_number}"
        sheet.cell(row_number, 8).value = worker
        sheet.cell(row_number, 14).value = row_number - 17
    workbook.save(path)
    workbook.close()


def _write_fixture(root: Path, *, include_unmapped: bool) -> None:
    period_directory = root / PERIOD
    period_directory.mkdir(parents=True, exist_ok=False)
    source = period_directory / SOURCE_NAME
    worker_template = root / WORKER_TEMPLATE_NAME
    _write_source(source, include_unmapped=include_unmapped)
    write_mapping(root / "worker_mapping.yaml")
    _write_template(worker_template)
    manifest = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "worker_template_sha256": hashlib.sha256(worker_template.read_bytes()).hexdigest(),
        "include_unmapped": include_unmapped,
    }
    (root / "fixture_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root to create; absent or empty")
    parser.add_argument("--include-unmapped", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = create_run_root(args.root)
        _write_fixture(root, include_unmapped=args.include_unmapped)
    except (OSError, ValueError) as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"FIXTURE_READY root={root} period={PERIOD} workers={len(WORKERS)} unmapped={args.include_unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
