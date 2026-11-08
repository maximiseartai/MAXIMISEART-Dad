"""Check the Uporządkowanie INTERMAX of the ``intermax`` variant: its JSON result, the Kopia INTERMAX, INTERMAX, metrics.

The result is read as the contract model ``ProcessResult`` (``wynik_uruchomienia.py``). The expected values come
from the synthetic pasted day in ``create_intermax_fixture.py`` and from GLOSSARY.md (Uporządkowanie INTERMAX, Kopia
INTERMAX, Okres rozliczeniowy), never from a run of the process. Messages name fields and checks, never a row value.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from create_intermax_fixture import COPIES_DIRECTORY, MANIFEST_NAME, ROW_MARKERS
from skrypt_skilla import Parser
from wynik_uruchomienia import check_metrics, contract, finish, load_result

from atrapy.intermax import FIRST, LAST, NUMBER, ORDER_SHEET
from atrapy.scenariusz_rozliczen import REGISTER_NAME

# Uporządkowanie INTERMAX: Wykonawcy alphabetically (anna, bartek, jan), each from the earliest hour to the latest.
EXPECTED_ORDER_NUMBERS = ("ZL-78202", "ZL-78205", "ZL-78203", "ZL-78206", "ZL-78204", "ZL-78201")
EXPECTED_ORDERS = 6
EXPECTED_WORKERS = 3
EXPECTED_DAY = "pon 26.10.2026"
EXPECTED_PHASES = ["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]
# Kopia INTERMAX: named after the moment it comes from, in the computer's clock. A deliberate copy of the name in
# ``intermax_copies`` (docs/agents/skille.md, „Co wyrocznia bierze z src”): tata finds the Kopia by this name.
COPY_NAME = re.compile(r"INTERMAX przed uporządkowaniem (\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})\.xlsx")
COPY_MOMENT = "%Y-%m-%d %H-%M-%S"


def _period_token(day: date) -> str:
    """Okres rozliczeniowy of ``day``: Tuesday to Monday, the month and year of the Monday."""

    monday = day + timedelta(days=(7 - day.weekday()) % 7)
    tuesday = monday - timedelta(days=6)
    return f"{tuesday:%d}_{monday:%d}_{monday:%m}_{monday:%Y}"


def _expected_summary(copy_name: str | None) -> contract.RunSummary:
    return contract.RunSummary(
        figures=[
            contract.Figure(label="Zlecenia", value=EXPECTED_ORDERS, unit="count"),
            contract.Figure(label="Wykonawcy", value=EXPECTED_WORKERS, unit="count"),
        ],
        counts=contract.CountGroup(
            title="Uporządkowany dzień", counts=[contract.Count(label=EXPECTED_DAY, count=EXPECTED_ORDERS)]
        ),
        files=[],
        worker_settlements=None,
        intermax_copy=copy_name,
    )


def _check_result(result_path: Path, errors: list[str]) -> str | None:
    """The result's checks; returns the Kopia INTERMAX name the summary reports."""

    result = load_result(result_path, ROW_MARKERS, errors)
    if result is None:
        return None
    if result.result != "OK" or result.stop is not None or result.warnings:
        errors.append("result is not OK without a stop and warnings")
    summary = result.summary
    if summary is None:
        errors.append("result has no summary")
        return None
    figures = [(figure.label, figure.value, figure.unit) for figure in summary.figures]
    if figures != [("Zlecenia", EXPECTED_ORDERS, "count"), ("Wykonawcy", EXPECTED_WORKERS, "count")]:
        errors.append(f"summary figures are not Zlecenia {EXPECTED_ORDERS} and Wykonawcy {EXPECTED_WORKERS}")
    if summary.intermax_copy is None or COPY_NAME.fullmatch(summary.intermax_copy) is None:
        errors.append("summary.intermax_copy is not the name of a Kopia INTERMAX before ordering")
    elif summary != _expected_summary(summary.intermax_copy):
        errors.append(f"summary does not match the ordered day {EXPECTED_DAY} of the synthetic INTERMAX")
    progress = result.progress
    if [(phase.phase, phase.state) for phase in progress.phases] != [(phase, "completed") for phase in EXPECTED_PHASES]:
        errors.append("progress does not report the four stages completed in order")
    if (progress.template_total, progress.templates_completed) != (0, 0):
        errors.append("progress reports Szablony pracowników")
    return summary.intermax_copy


def _check_copy(root: Path, copy_name: str | None, manifest: dict[str, Any], errors: list[str]) -> date | None:
    """The one Kopia INTERMAX holds INTERMAX's bytes from before the run; returns the day of its moment."""

    copies = sorted(path.name for path in (root / COPIES_DIRECTORY).iterdir())
    if copy_name is None or copies != [copy_name]:
        errors.append(f"{COPIES_DIRECTORY} does not hold exactly the Kopia INTERMAX the summary names")
        return None
    copy = root / COPIES_DIRECTORY / copy_name
    if hashlib.sha256(copy.read_bytes()).hexdigest() != manifest["register_sha256"]:
        errors.append("Kopia INTERMAX is not INTERMAX as it was before the run")
    found = COPY_NAME.fullmatch(copy_name)
    assert found is not None, "_check_result accepted only a matching name"
    # The name holds the local moment without a zone; astimezone() reads it in the computer's zone.
    moment = datetime.strptime(found.group(1), COPY_MOMENT).astimezone()
    if not datetime.fromisoformat(manifest["created_at"]) <= moment <= datetime.now().astimezone():
        errors.append("Kopia INTERMAX is not named after a moment of this run in the computer's clock")
    return moment.date()


def _order_sheet(path: Path) -> Worksheet:
    sheet = load_workbook(path)[ORDER_SHEET]
    if not isinstance(sheet, Worksheet):
        raise ValueError(f"{ORDER_SHEET} is not a worksheet")
    return sheet


def _check_register(root: Path, copy_name: str | None, manifest: dict[str, Any], errors: list[str]) -> None:
    """INTERMAX was replaced; earlier days are as in the Kopia and the pasted day is ordered below them."""

    register = root / REGISTER_NAME
    if hashlib.sha256(register.read_bytes()).hexdigest() == manifest["register_sha256"]:
        errors.append("INTERMAX was not written")
        return
    sheet = _order_sheet(register)
    last_ordered: int = manifest["last_ordered_row"]
    numbers = [
        sheet.cell(row, NUMBER).value
        for row in range(last_ordered + 1, sheet.max_row + 1)
        if sheet.cell(row, NUMBER).value is not None
    ]
    if tuple(numbers) != EXPECTED_ORDER_NUMBERS:
        errors.append("the pasted day is not ordered by Wykonawca alphabetically and by hour")
    if copy_name is None or not (root / COPIES_DIRECTORY / copy_name).is_file():
        return
    before = _order_sheet(root / COPIES_DIRECTORY / copy_name)

    def earlier_days(found: Worksheet) -> list[tuple[object, ...]]:
        return [
            tuple(row)
            for row in found.iter_rows(min_row=1, max_row=last_ordered, min_col=FIRST, max_col=LAST, values_only=True)
        ]

    if earlier_days(sheet) != earlier_days(before):
        errors.append("rows of the ordered days above the pasted day changed")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root created by create_intermax_fixture.py")
    parser.add_argument("--result", required=True, type=Path, help="evidence JSON of the intermax step")
    args = parser.parse_args(argv)
    root = args.root
    errors: list[str] = []
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        copy_name = _check_result(args.result.expanduser().resolve(), errors)
        copy_day = _check_copy(root, copy_name, manifest, errors)
        _check_register(root, copy_name, manifest, errors)
        period = _period_token(copy_day or datetime.now().astimezone().date())
        records = check_metrics(
            root / "metrics.jsonl", root, period=period, expected=[("RUN", "OK")], row_content=ROW_MARKERS, errors=errors
        )
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"evidence cannot be read: {exc.__class__.__name__}")
        return finish(errors, "")
    if any(record.get("counters") != {"orders": EXPECTED_ORDERS, "workers": EXPECTED_WORKERS} for record in records):
        errors.append("metrics counters are not the orders and Wykonawcy of the pasted day")
    return finish(
        errors,
        f"ASSERT OK | intermax=true | orders={EXPECTED_ORDERS} | workers={EXPECTED_WORKERS} | "
        "intermax_copy=before_run | ordered_by_worker_and_hour=true | earlier_days_unchanged=true | metrics_safe=true",
    )


if __name__ == "__main__":
    raise SystemExit(main())
