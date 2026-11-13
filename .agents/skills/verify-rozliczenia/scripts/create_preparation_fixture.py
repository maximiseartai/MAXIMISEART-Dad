"""Create a disposable synthetic Rejestr zleceń and both Wzorce for Przygotowanie pliku zbiorczego.

``--with-worker-template`` also creates the Wzorzec rozliczenia pracownika for the Przebieg rozliczeń
that follows. With ``--templates-from`` every Wzorce is a byte copy of the real one instead of a
synthetic workbook.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from skrypt_skilla import Parser, create_run_root

from atrapy.pliki_taty import WORKER_LIST_NAME
from atrapy.preparation import (
    REGISTER_HEADERS,
    Highlight,
    RegisterRow,
    write_collective_template,
    write_internal_template,
    write_register_sheet,
)
from atrapy.scenariusz_rozliczen import (
    ARCHIVED_NUMBER,
    ARCHIVED_ORDER,
    COLLECTIVE_TEMPLATE_NAME,
    INTERNAL_TEMPLATE_NAME,
    ORDER_LINK,
    ORDERS,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    TEMPLATES_DIRECTORY,
    WORKER_TEMPLATE_NAME,
    register_values,
)
from atrapy.settlement import PERIOD, WORKERS, write_worker_list
from atrapy.workbooks import active_worksheet
from atrapy.wzorce import write_settlement_template

# Two rows of zeros below the 6 Zlecenia skuteczne prove that Przygotowanie keeps the Wzorzec below its written rows.
COLLECTIVE_ZERO_ROWS = 8
# Wzorzec rozliczenia pracownika shaped like Dad's: GODZINA in A17, its own rate and rows 1–16 unlike the Plik zbiorczy.
WORKER_TEMPLATE_ROWS = 40
# ADRES of order 4 (row 9): neither yellow nor plain, so the Plik zbiorczy shows it only when it copies the Rejestr.
REGISTER_HIGHLIGHTS = {
    (4, "ADRES"): Highlight(fill="FFFFFF00", color="FFC00000", bold=True),
    (9, "ADRES"): Highlight(fill="FF00B0F0"),
    (9, "WYKONAWCA"): Highlight(italic=True),
}


# Excel row -> order; rows without an entry are fully empty export rows.
REGISTER_ROWS: dict[int, dict[str, object]] = {
    order.row: register_values(number, order) for number, order in ORDERS.items()
}


def _sheet_rows(orders: dict[int, dict[str, object]]) -> list[RegisterRow]:
    return [orders.get(row) for row in range(2, max(orders) + 1)]


def _write_register(path: Path) -> None:
    """Decoy ``lista``, hidden ``ARCHIWUM`` with an order of another period and active ``ZLECENIA`` with hyperlinks."""

    workbook = Workbook()
    decoy = active_worksheet(workbook)
    decoy.title = "lista"
    decoy["A1"] = "WYKONAWCY"
    archive = workbook.create_sheet("ARCHIWUM")
    archive.sheet_state = "hidden"
    write_register_sheet(archive, _sheet_rows({ARCHIVED_ORDER.row: register_values(ARCHIVED_NUMBER, ARCHIVED_ORDER)}))
    sheet = workbook.create_sheet("ZLECENIA")
    write_register_sheet(sheet, _sheet_rows(REGISTER_ROWS), highlights=REGISTER_HIGHLIGHTS)
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
        write_collective_template(collective_template, zero_rows=COLLECTIVE_ZERO_ROWS)
    else:
        shutil.copyfile(templates_from / INTERNAL_TEMPLATE_NAME, internal_template)
        shutil.copyfile(templates_from / COLLECTIVE_TEMPLATE_NAME, collective_template)
    worker_template = config_directory / WORKER_TEMPLATE_NAME
    if with_worker_template:
        if templates_from is None:
            write_settlement_template(worker_template, "GODZINA", WORKER_TEMPLATE_ROWS, comments=True)
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
