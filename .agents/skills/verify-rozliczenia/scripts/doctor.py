"""Read-only fixture check for the rozliczenia verification skill."""

from __future__ import annotations

from pathlib import Path
import sys

from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.worksheet import Worksheet

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.workers import WORKERS as WORKER_LIST_FILE, WORKERS_FILE
from skrypt_skilla import Parser
from rozliczenia.period_folder import PeriodFolder, PeriodFolderError
from rozliczenia.template_file import TemplateFile
from rozliczenia.workbook_files import WorkbookError
from atrapy.scenariusz_rozliczen import WORKER_TEMPLATE_NAME
from atrapy.settlement import PERIOD, SOURCE_NAME, WORKERS


def _check(root: Path) -> tuple[str, int]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"missing fixture root: {root}")
    if sys.version_info < (3, 13):
        raise ValueError("Python 3.13 or newer is required")

    source = root / PERIOD / SOURCE_NAME
    folder = PeriodFolder.from_collective_file(source)
    period = folder.period.token
    target_directory = folder.worker_settlements
    listed = WORKER_LIST_FILE.parse((root / WORKERS_FILE).read_bytes())
    if isinstance(listed, FieldProblem) or len(listed.workers) != len(WORKERS):
        raise ValueError(f"synthetic mapping must contain {len(WORKERS)} workers")
    if target_directory.exists():
        raise ValueError("target directory must not exist before dry-run")
    TemplateFile.worker_settlement(root / WORKER_TEMPLATE_NAME).check()

    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        sheet = workbook.active
        if not isinstance(sheet, (Worksheet, ReadOnlyWorksheet)):
            raise ValueError("source workbook has no active worksheet")
        if sheet["H17"].value != "WYKONAWCA":
            raise ValueError("source H17 is not WYKONAWCA")
    finally:
        workbook.close()

    return period, len(listed.workers)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_root("run root of a settlement fixture")
    args = parser.parse_args(argv)
    try:
        period, template_count = _check(args.root)
    except (OSError, ValueError, KeyError, TypeError, WorkbookError, PeriodFolderError) as exc:
        print(f"DOCTOR FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"DOCTOR OK | app=MAXIMISEART-Dad | "
        f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
        f"period={period} | workers={template_count} | worker_template=valid | target_absent=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
