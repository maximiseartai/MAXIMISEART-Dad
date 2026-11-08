"""Read-only check that this Mac's Excel and this run's fixture are worth driving.

    .venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel_doctor.py --root RUN_ROOT --desk DESK

Prints ``DOCTOR OK`` or one ``DOCTOR FAIL`` line per problem. It never starts Excel, opens a workbook,
or writes a file.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from pathlib import Path
import sys
import zipfile

import excel

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from skrypt_skilla import Parser

from tests.fixtures.preparation import COLLECTIVE_FILE_NAME, INTERNAL_SETTLEMENT_NAME
from tests.fixtures.scenariusz_rozliczen import (
    COLLECTIVE_TEMPLATE_NAME,
    PERIODS_DIRECTORY,
    REGISTER_NAME,
    TEMPLATES_DIRECTORY,
    WORKER_TEMPLATE_NAME,
    worker_settlement_name,
)
from tests.fixtures.settlement import PERIOD, WORKERS

LINKED_TEMPLATES = (COLLECTIVE_TEMPLATE_NAME, WORKER_TEMPLATE_NAME)
WORKBOOK_NAMES = (
    *LINKED_TEMPLATES,
    INTERNAL_SETTLEMENT_NAME,
    COLLECTIVE_FILE_NAME,
    *(worker_settlement_name(worker) for worker in WORKERS.values()),
)


def _used_link(template: Path) -> bool:
    """The Wzorzec has an ``xl/externalLinks`` part and a formula that uses it, like Dad's Słownik lookups.

    Excel drops a link no formula uses when it saves, so an unused link proves nothing about Dad's files.
    """

    with zipfile.ZipFile(template) as archive:
        names = archive.namelist()
        if not any(name.startswith("xl/externalLinks/externalLink") for name in names):
            return False
        return any(
            b"[1]" in archive.read(name)
            for name in names
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )


def check(root: Path, desk: Path) -> list[str]:
    problems: list[str] = []
    if sys.platform != "darwin":
        problems.append("this skill drives Excel for Mac; run it on macOS")
    if sys.version_info < (3, 11):
        problems.append("Python 3.11 or newer is required")
    version = excel.installed_version()
    if version is None:
        problems.append("Microsoft Excel is not installed in /Applications")
    if not desk.is_relative_to(excel.DESK.parent):
        problems.append(f"the desk must be inside Excel's container {excel.DESK.parent}")
    elif not excel.DESK.parent.is_dir():
        problems.append("Excel's container does not exist; start Excel once by hand")
    elif desk.exists() and any(desk.iterdir()):
        problems.append("the desk already holds files of another run")
    fixture = root / "okres"
    for name in LINKED_TEMPLATES:
        template = fixture / TEMPLATES_DIRECTORY / name
        if not template.is_file():
            problems.append(f"fixture lacks {TEMPLATES_DIRECTORY}/{name}")
        elif not _used_link(template):
            problems.append(f"{TEMPLATES_DIRECTORY}/{name} has no external link used by a formula")
    for relative in (REGISTER_NAME, f"{TEMPLATES_DIRECTORY}/worker_mapping.yaml", PERIODS_DIRECTORY):
        if not (fixture / relative).exists():
            problems.append(f"fixture lacks {relative}")
    if (fixture / PERIODS_DIRECTORY / PERIOD).exists():
        problems.append(f"Folder okresu {PERIOD} already exists before Przygotowanie")
    if excel.running():
        try:
            open_names = {Path(path).name for path in excel.open_paths()}
        except excel.ExcelDialog as exc:
            problems.append(f"Excel shows a dialog or does not answer: {exc}; dialogs: {excel.dialogs() or 'none on screen'}")
        except excel.ExcelError as exc:
            problems.append(f"Excel fails AppleScript: {exc}")
        else:
            clashes = sorted(open_names.intersection(WORKBOOK_NAMES))
            if clashes:
                problems.append(f"Excel already holds a workbook named like this run's: {', '.join(clashes)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_root("run root of this Excel run")
    parser.add_argument("--desk", required=True, type=Path, help="this run's directory inside Excel's container")
    args = parser.parse_args(argv)
    problems = check(args.root, args.desk.expanduser().resolve())
    for problem in problems:
        print(f"DOCTOR FAIL | {problem}")
    if problems:
        return 1
    state = "running" if excel.running() else "not running (the run starts it)"
    print(f"DOCTOR OK | excel={excel.installed_version()} {state} | links_used_by_formulas=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
