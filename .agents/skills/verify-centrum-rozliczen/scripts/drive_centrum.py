"""Drive a running Centrum rozliczeń in Chromium the way Dad does and record the proof.

Each feature step pairs a user action with the resulting screen, the server's
answer, and the side effect on disk (settings file, picker dialogs, opened
paths). Screenshots and ARIA snapshots go to ``<evidence>/screenshots`` and
``<evidence>/aria``; API answers to ``<evidence>/api``; the run's state files
to ``<evidence>/state``.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from pathlib import Path
import shutil
import sys
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from drive import ALL, DEFAULT_REPEATS, FEATURES, feature
from drive.common import DriveFailure, Run, dad_context, page_requests
from drive.waiting import Budget, TimedOut
from skrypt_skilla import Parser
from harness import Log
from import_dynamiczny import modul
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.tool_files import config_dir

MODULES = {each.name: modul(each.module) for each in FEATURES}


def drive(run: Run, page: Page, name: str, driven: list[str], options: dict[str, Any]) -> None:
    for need in feature(name).needs:
        if need not in driven:
            print(f"  harness: {name} needs the state of {need}, which this drive has not driven, so it runs first", flush=True)
            drive(run, page, need, driven, options)
    MODULES[name].drive(run, page, **(options if feature(name).measurement else {}))
    driven.append(name)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_root("run root with fixture.json and a served Centrum")
    parser.add_argument("--url", required=True, help="Centrum URL from the record serve_centrum.py writes (harness.File.SERVER).")
    parser.add_argument("--evidence", required=True, help="Evidence directory that survives cleanup.")
    parser.add_argument(
        "--feature",
        nargs="+",
        choices=("all", *MODULES),
        default=["all"],
        help="all, or the features to drive in this order (a part of all in CI).",
    )
    parser.add_argument(
        "--baseline", type=Path, default=MODULES["wydajnosc"].BASELINE, help="wydajnosc: the baseline to compare with."
    )
    parser.add_argument(
        "--powtorzenia", type=int, default=DEFAULT_REPEATS, help="wydajnosc: repetitions per scenario and profile."
    )
    args = parser.parse_args(argv)
    run = Run(args.root, args.url, Path(args.evidence).resolve())
    options = {"baseline_path": args.baseline.resolve(), "repeats": args.powtorzenia}
    selected = ALL if args.feature == ["all"] else tuple(args.feature)
    driven: list[str] = []
    try:
        with sync_playwright() as playwright, page_requests.recording(run.evidence):
            browser = playwright.chromium.launch()
            try:
                page = dad_context(browser).new_page()
                page.set_default_timeout(Budget.SCREEN.ms)
                for name in selected:
                    drive(run, page, name, driven, options)
            except Exception as exc:
                if "page" in locals():
                    try:
                        page.screenshot(path=run.evidence / "screenshots" / "zz-failure.png", full_page=True)
                    except PlaywrightError as shot:
                        exc.add_note(f"zz-failure.png not taken: {shot.message}")
                page_requests.check(exc)
                raise
            finally:
                browser.close()
        page_requests.check()
    except (DriveFailure, TimedOut, AssertionError, PlaywrightError) as exc:
        print(f"DRIVE FAIL | {exc}" + "".join(f" | {note}" for note in getattr(exc, "__notes__", ())), file=sys.stderr)
        return 1
    finally:
        for source in (Log.OPENED.file(run.root), Log.DIALOGS.file(run.root), config_dir(run.root) / SETTINGS_FILE, run.log_path):
            if source.exists():
                shutil.copy2(source, run.evidence / "state" / source.name)
        logs = run.run_logs_dir
        if logs.is_dir():
            shutil.copytree(logs, run.evidence / "state" / logs.name, dirs_exist_ok=True)
    print(f"DRIVE OK | features={','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
