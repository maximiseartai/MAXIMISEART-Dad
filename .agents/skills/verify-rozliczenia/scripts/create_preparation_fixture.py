"""Create a disposable synthetic Rejestr zleceń and both Wzorce for Przygotowanie pliku zbiorczego.

``--with-worker-template`` also creates the Wzorzec rozliczenia pracownika for the Przebieg rozliczeń
that follows. With ``--templates-from`` every Wzorce is a byte copy of the real one instead of a
synthetic workbook.

The synthetic Wzorce are the shared ``atrapy`` Wzorce of the tests, so the skill checks the shape the tests check.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from skrypt_skilla import Parser, create_run_root

from atrapy.pliki_taty import WORKER_LIST_NAME
from atrapy.preparation import REGISTER_HEADERS, write_collective_template, write_internal_template
from atrapy.scenariusz_rozliczen import (
    ARCHIVED_NUMBER,
    ARCHIVED_ORDER,
    COLLECTIVE_TEMPLATE_NAME,
    INTERNAL_TEMPLATE_NAME,
    ORDER_LINK,
    ORDERS,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    TEMPLATE_ZERO_ROWS,
    TEMPLATES_DIRECTORY,
    WORKER_TEMPLATE_NAME,
    WORKER_TEMPLATE_RATE,
    register_values,
)
from atrapy.settlement import PERIOD, WORKERS, write_worker_list
from atrapy.workbooks import active_worksheet

REGISTER_DATE_FORMAT = "dd.mm.yyyy hh:mm"
HIGHLIGHT_FILL = "FFFFFF00"
HIGHLIGHT_COLOR = "FFC00000"
# ADRES of order 4: neither yellow nor plain, so the Plik zbiorczy shows it only when it copies the Rejestr.
ADDRESS_FILL = "FF00B0F0"


# Excel row -> order; rows without an entry are fully empty export rows.
REGISTER_ROWS: dict[int, dict[str, object]] = {
    order.row: register_values(number, order) for number, order in ORDERS.items()
}


def _write_register(path: Path) -> None:
    workbook = Workbook()
    decoy = active_worksheet(workbook)
    decoy.title = "lista"
    decoy["A1"] = "WYKONAWCY"
    archive = workbook.create_sheet("ARCHIWUM")
    archive.sheet_state = "hidden"
    sheet = workbook.create_sheet("ZLECENIA")
    # Column A has no header and stays completely empty.
    columns = [(column, header) for column, header in enumerate(REGISTER_HEADERS, start=1) if header]
    for target, rows in ((archive, {ARCHIVED_ORDER.row: register_values(ARCHIVED_NUMBER, ARCHIVED_ORDER)}), (sheet, REGISTER_ROWS)):
        for column, header in columns:
            target.cell(1, column).value = header
        for row_number, order in rows.items():
            for column, header in columns:
                cell = target.cell(row_number, column)
                cell.value = order[header]
                cell.font = Font(name="Calibri", size=8)  # uporządkowane zlecenia taty, nie Surowe zlecenia
                if header == "DATA GODZ. POCZ.":
                    cell.number_format = REGISTER_DATE_FORMAT
    adres_column = REGISTER_HEADERS.index("ADRES") + 1
    highlighted = sheet.cell(4, adres_column)
    highlighted.font = Font(name="Calibri", size=8, color=HIGHLIGHT_COLOR, bold=True)
    highlighted.fill = PatternFill(fill_type="solid", fgColor=HIGHLIGHT_FILL)
    sheet.cell(9, adres_column).fill = PatternFill(fill_type="solid", fgColor=ADDRESS_FILL)
    worker_column = REGISTER_HEADERS.index("WYKONAWCA") + 1
    sheet.cell(9, worker_column).font = Font(name="Calibri", size=8, italic=True)
    order_column = REGISTER_HEADERS.index("NUMER ZL.") + 1
    for row_number in REGISTER_ROWS:
        sheet.cell(row_number, order_column).hyperlink = f"{ORDER_LINK}{row_number}"
    workbook.active = workbook.sheetnames.index("ZLECENIA")
    workbook.save(path)
    workbook.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fixture(root: Path, templates_from: Path | None, *, with_worker_template: bool) -> None:
    config_directory = root / TEMPLATES_DIRECTORY
    config_directory.mkdir(parents=True)
    (root / PERIODS_DIRECTORY).mkdir()
    register = root / REGISTER_NAME
    internal_template = config_directory / INTERNAL_TEMPLATE_NAME
    collective_template = config_directory / COLLECTIVE_TEMPLATE_NAME
    _write_register(register)
    if templates_from is None:
        write_internal_template(internal_template)
        write_collective_template(collective_template, zero_rows=TEMPLATE_ZERO_ROWS)
    else:
        shutil.copyfile(templates_from / INTERNAL_TEMPLATE_NAME, internal_template)
        shutil.copyfile(templates_from / COLLECTIVE_TEMPLATE_NAME, collective_template)
    worker_template = config_directory / WORKER_TEMPLATE_NAME
    if with_worker_template:
        if templates_from is None:
            write_collective_template(worker_template, rate=WORKER_TEMPLATE_RATE, zero_rows=TEMPLATE_ZERO_ROWS)
        else:
            shutil.copyfile(templates_from / WORKER_TEMPLATE_NAME, worker_template)
    write_worker_list(config_directory / WORKER_LIST_NAME)
    manifest = {
        "register_sha256": _sha256(register),
        "internal_template_sha256": _sha256(internal_template),
        "collective_template_sha256": _sha256(collective_template),
    }
    if with_worker_template:
        manifest["worker_template_sha256"] = _sha256(worker_template)
    (root / "fixture_manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root to create; absent or empty")
    parser.add_argument("--templates-from", type=Path, help="copy the real Wzorce from this directory")
    parser.add_argument(
        "--with-worker-template",
        action="store_true",
        help="also create the Wzorzec rozliczenia pracownika for the Przebieg rozliczeń",
    )
    args = parser.parse_args(argv)
    templates_from = args.templates_from.expanduser().resolve() if args.templates_from else None
    try:
        root = create_run_root(args.root)
        _write_fixture(root, templates_from, with_worker_template=args.with_worker_template)
    except (OSError, ValueError) as exc:
        print(f"FIXTURE FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"FIXTURE_READY process=przygotowanie root={root} period={PERIOD} "
        f"register_rows={len(REGISTER_ROWS)} workers={len(WORKERS)} "
        f"worker_template={str(args.with_worker_template).lower()} "
        f"templates={'synthetic' if templates_from is None else 'copied'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
