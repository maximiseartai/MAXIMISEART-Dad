"""Create a disposable synthetic Rejestr zleceń and both Wzorce for Przygotowanie pliku zbiorczego.

``--with-worker-template`` also creates the Wzorzec rozliczenia pracownika for the Przebieg rozliczeń
that follows. With ``--templates-from`` every Wzorce is a byte copy of the real one instead of a
synthetic workbook.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from skrypt_skilla import Parser, create_run_root

from atrapy.pliki_taty import (
    AMOUNT_COLUMN,
    COLLECTIVE_HEADERS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    INTERNAL_HEADERS,
    QUANTITY_COLUMNS,
    WORKER_LIST_NAME,
)
from atrapy.preparation import REGISTER_HEADERS
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

COLLECTIVE_ZERO_ROWS = 8
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


def _apply_template_layout(sheet: Worksheet, header_row: int, columns: int) -> None:
    """Look of a Wzorzec, with a stale autofilter."""

    for column in range(1, columns + 1):
        dimension = sheet.column_dimensions[get_column_letter(column)]
        dimension.width = 9 + column
        dimension.font = Font(name="Calibri", size=10)
        sheet.cell(header_row, column).font = Font(name="Calibri", size=10, bold=True)
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"B{header_row}:C{header_row + 40}"


def _write_internal_template(path: Path) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Arkusz1"
    for column, header in enumerate(INTERNAL_HEADERS, start=1):
        sheet.cell(1, column).value = header
    _apply_template_layout(sheet, 1, len(INTERNAL_HEADERS))
    workbook.save(path)
    workbook.close()


def _write_collective_template(path: Path) -> None:
    _write_collective_layout(path, rate=17.5)


def _write_worker_template(path: Path) -> None:
    """Same layout as the Wzorzec pliku zbiorczego, with the worker's own rate and no WYKONAWCA name."""

    _write_collective_layout(path, rate=12.0)


def _write_collective_layout(path: Path, *, rate: float) -> None:
    workbook = Workbook()
    sheet = active_worksheet(workbook)
    sheet.title = "Sheet1"
    sheet["A1"] = "STAWKI"
    sheet["N1"] = rate
    sheet["N16"] = f"=SUM(N{FIRST_DATA_ROW}:N40)"
    sheet.cell(HEADER_ROW, 1).fill = PatternFill(fill_type="solid", fgColor="00AA55")
    for column, header in enumerate(COLLECTIVE_HEADERS, start=1):
        sheet.cell(HEADER_ROW, column).value = header
    sheet.cell(HEADER_ROW, QUANTITY_COLUMNS.start).value = "instalacja"
    sheet.cell(HEADER_ROW, QUANTITY_COLUMNS[-1]).value = "demontaż"
    _apply_template_layout(sheet, HEADER_ROW, len(COLLECTIVE_HEADERS))
    for row in range(FIRST_DATA_ROW, FIRST_DATA_ROW + COLLECTIVE_ZERO_ROWS):
        for column in QUANTITY_COLUMNS:
            sheet.cell(row, column).value = 0
        sheet.cell(row, AMOUNT_COLUMN).value = f"=N{row}*$N$1"
    rates = workbook.create_sheet("Rates")
    rates["A1"] = "synthetic rate"
    rates["B1"] = rate
    workbook.save(path)
    workbook.close()
    _add_external_link(path)


def _add_external_link(path: Path) -> None:
    """Inject one valid ``xl/externalLinks/*`` part, like the link to the Słownik."""

    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns_content = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("r", ns_rel)
    parts = {
        "xl/externalLinks/externalLink1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<externalLink xmlns="{ns_main}" xmlns:r="{ns_rel}">'
            '<externalBook r:id="rId1"><sheetNames><sheetName val="Słownik"/></sheetNames>'
            '<definedNames/><sheetDataSet><sheetData sheetId="0"/></sheetDataSet>'
            "</externalBook></externalLink>"
        ).encode("utf-8"),
        "xl/externalLinks/_rels/externalLink1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns_pkg_rel}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" '
            'Target="https://example.invalid/Slownik.xlsm" TargetMode="External"/>'
            "</Relationships>"
        ).encode("utf-8"),
    }
    descriptor, temporary_name = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "xl/workbook.xml":
                    # One default namespace per document: register it just before serialising.
                    ET.register_namespace("", ns_main)
                    root = ET.fromstring(data)
                    references = ET.SubElement(root, f"{{{ns_main}}}externalReferences")
                    ET.SubElement(references, f"{{{ns_main}}}externalReference", {f"{{{ns_rel}}}id": "rIdSynExternal1"})
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename == "xl/_rels/workbook.xml.rels":
                    ET.register_namespace("", ns_pkg_rel)
                    root = ET.fromstring(data)
                    ET.SubElement(
                        root,
                        f"{{{ns_pkg_rel}}}Relationship",
                        {
                            "Id": "rIdSynExternal1",
                            "Type": f"{ns_rel}/externalLink",
                            "Target": "externalLinks/externalLink1.xml",
                        },
                    )
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename == "[Content_Types].xml":
                    ET.register_namespace("", ns_content)
                    root = ET.fromstring(data)
                    ET.SubElement(
                        root,
                        f"{{{ns_content}}}Override",
                        {
                            "PartName": "/xl/externalLinks/externalLink1.xml",
                            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml",
                        },
                    )
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, data)
            for name, data in parts.items():
                target.writestr(name, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        _write_internal_template(internal_template)
        _write_collective_template(collective_template)
    else:
        shutil.copyfile(templates_from / INTERNAL_TEMPLATE_NAME, internal_template)
        shutil.copyfile(templates_from / COLLECTIVE_TEMPLATE_NAME, collective_template)
    worker_template = config_directory / WORKER_TEMPLATE_NAME
    if with_worker_template:
        if templates_from is None:
            _write_worker_template(worker_template)
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
