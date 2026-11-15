"""Drive a running Centrum rozliczeń in Chromium the way Dad does and record the proof.

Each feature step pairs a user action with the resulting screen, the server's
answer, and the side effect on disk (settings file, picker dialogs, opened
paths). Screenshots and ARIA snapshots go to ``<evidence>/screenshots`` and
``<evidence>/aria``; API answers to ``<evidence>/api``; the run's state files
to ``<evidence>/state``. The section Sub-features of each driven feature, from the run's steps and checks (``sections``),
goes to ``<evidence>/sekcje-z-biegu/<feature>.md``, and the drive fails, printing the difference, when it differs from
the feature's file in ``features/`` (``compare``).
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from difflib import unified_diff
from functools import cache
import inspect
from pathlib import Path
import shutil
import sys
from typing import Any, NamedTuple

from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, StorageState
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from drive import ALL, DEFAULT_REPEATS, FEATURES, feature
from drive.common import Call, DriveFailure, Run, check_clock_alarm, dad_context, page_requests
from drive.waiting import Budget, TimedOut
from skrypt_skilla import Parser
from harness import Log
from import_dynamiczny import modul
from komunikat_mapy import call_messages
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.efenix_browser import launch_options
from rozliczenia.tool_files import config_dir

MODULES = {each.name: modul(each.module) for each in FEATURES}
FEATURE_FILES = Path(__file__).resolve().parents[1] / "features"
SECTIONS = "sekcje-z-biegu"
# Beside the sections: each run.check outside a section, as `<feature> | <reason> | <count>`.
OUTSIDE = "poza-sekcja.txt"
SECTION_START, SECTION_END = "\n## Sub-features\n", "\n## How to get to it (user POV)\n"


def drive(run: Run, windows: FeatureWindows, name: str, driven: list[str], options: dict[str, Any], owners: list[str]) -> None:
    """Drives ``name`` in a window of its own (``FeatureWindows``) after its needs this run has not driven; ``owners``
    gets ``name`` for each of its drive's calls."""

    for need in feature(name).needs:
        if need not in driven:
            print(f"  harness: {name} needs the state of {need}, which this drive has not driven, so it runs first", flush=True)
            drive(run, windows, need, driven, options, owners)
    # A check before the drive's first step names no feature, not the feature driven before.
    run.feature = ""
    with windows.open(run) as page:
        try:
            MODULES[name].drive(run, page, **(options if feature(name).measurement else {}))
        except TimedOut:
            # A wait that outlasted its budget after the wake-up thread of Centrum's clock died waited for a wake-up
            # that never fires: the failure names the dead clock.
            check_clock_alarm(run)
            raise
    owners += [name] * (len(run.calls) - len(owners))
    driven.append(name)


class FeatureWindows:
    """The windows of the drive's browser, one per feature: the only place the drive opens the page a feature drives.

    Whatever a feature leaves in the browser (an open or closing window or dialog, a route or listener of its tab or of
    its window, the window's clock, a narrow size, another tab or window it opened) ends with the feature, so every
    feature finds the window the fixture gives, whichever feature ran before it (#1589). Only what Dad's browser keeps
    between visits, the window's cookies and ``localStorage``, carries to the next window. A failure leaves
    ``zz-failure.png`` of the feature's page and ends the drive, which closes the browser.
    """

    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        self.kept: StorageState | None = None

    @contextmanager
    def open(self, run: Run) -> Iterator[Page]:
        window = dad_context(self.browser, storage_state=self.kept)
        page = window.new_page()
        page.set_default_timeout(Budget.SCREEN.ms)
        try:
            yield page
        except Exception as exc:
            try:
                page.screenshot(path=run.evidence / "screenshots" / "zz-failure.png", full_page=True)
            except PlaywrightError as shot:
                exc.add_note(f"zz-failure.png not taken: {shot.message}")
            raise
        self.kept = window.storage_state()
        for each in self.browser.contexts:
            each.close()


def _needed(name: str) -> set[str]:
    return {each for need in feature(name).needs for each in (need, *_needed(need))}


class Section(NamedTuple):
    """A feature's section Sub-features from the run, and its checks outside the section counted by reason."""

    text: str
    outside: dict[str, int]


def sections(calls: Sequence[Call], owners: Sequence[str], driven: Iterable[str]) -> dict[str, Section]:
    """The section Sub-features of each ``driven`` feature from the run's ``calls``; ``owners`` names the feature whose
    drive made each call.

    Every ``run.step`` that named the feature is a step of its section, from whichever module: each once per place and
    name it ran with, in the order of its first call, so the section's IDs are the feature's ``STEP`` lines. Every
    ``run.check`` after it is a row under that step (each place once, with the message of its call as written in the
    module, ``tools/lib/komunikat_mapy.py``, the same at every call) or, from a helper the drive modules share
    (``drive/common.py``), outside the section, counted with that reason. A message that rule cannot print fails the
    run, and so do, so that the section does not depend on the features a CI part drives before the feature, a check
    before the first step of a drive and a step of a feature called from the drive of one it does not need.
    """

    modules = {each.module for each in FEATURES}
    found: dict[str, dict[tuple[str, str, int, int], dict[tuple[str, int, int], str]]] = {}
    current: dict[str, tuple[str, str, int, int]] = {}
    outside: dict[str, Counter[str]] = {}
    for call, owner in zip(calls, owners, strict=True):
        where = f"{call.module}:{call.line}"
        if not call.feature:
            raise DriveFailure(f"{where}: run.check before the first run.step of the drive of {owner}; move it after the step")
        if call.feature != owner and owner not in _needed(call.feature):
            raise DriveFailure(
                f"{where}: the drive of {owner} runs a step of {call.feature}, which does not need {owner}, so the section "
                f"of {call.feature} would depend on the features of the CI part; add {owner} to its needs"
            )
        place, steps = (call.module, call.line, call.column), found.setdefault(call.feature, {})
        if call.step is not None:
            current[call.feature] = (call.step, *place)
            steps.setdefault(current[call.feature], {})
            continue
        if call.module not in modules:
            outside.setdefault(call.feature, Counter())[f"a helper the drives share ({call.module})"] += 1
        elif (printed := _messages(call.module)[call.line, call.column]) is None:
            raise DriveFailure(f"{where}: the message of this run.check cannot be printed in the map; give it as a string "
                               "literal, a module constant or an f-string")
        else:
            steps[current[call.feature]].setdefault(place, printed)
    return {
        name: Section(_section(name, found.get(name, {}).items()), dict(outside.get(name, Counter()))) for name in driven
    }


def _section(name: str, steps: Iterable[tuple[tuple[str, str, int, int], dict[tuple[str, int, int], str]]]) -> str:
    return "\n".join([
        "## Sub-features",
        "",
        f"Printed by `scripts/sub_features.py --feature {name}` from the drive's steps and checks; refresh the section with it.",
        "",
        *(f"- `{step}`: {'; '.join(checks.values())}." if checks else f"- `{step}`." for (step, *_), checks in steps),
    ]) + "\n"


@cache
def _messages(module: str) -> dict[tuple[int, int], str | None]:
    # The source of the imported module, not of a path the frame names, so the section is the same on every system.
    return call_messages(inspect.getsource(sys.modules[module]))


def compare(evidence: Path, printed: dict[str, Section]) -> None:
    """Writes each section and its checks outside it (``OUTSIDE``) to ``evidence`` and fails, printing the difference,
    where a feature has another section in its file in ``features/``."""

    folder = evidence / SECTIONS
    folder.mkdir(exist_ok=True)
    outside = [f"{name} | {reason} | {count}" for name, (_, reasons) in printed.items() for reason, count in reasons.items()]
    (folder / OUTSIDE).write_text("".join(f"{line}\n" for line in outside), encoding="utf-8", newline="\n")
    differ = []
    for name, (section, _) in printed.items():
        (folder / f"{name}.md").write_text(section, encoding="utf-8", newline="\n")
        mapped = (FEATURE_FILES / f"{name}.md").read_text(encoding="utf-8")
        start = mapped.find(SECTION_START) + 1
        end = mapped.find(SECTION_END, start)
        in_file = mapped[start:end] if 0 < start < end else ""
        if in_file != section:
            lines = unified_diff(in_file.splitlines(keepends=True), section.splitlines(keepends=True), f"features/{name}.md", f"{SECTIONS}/{name}.md")
            sys.stderr.writelines(lines)
            differ.append(name)
    if differ:
        raise DriveFailure(
            f"the section Sub-features of {', '.join(differ)} from this run differs from its file in features/ (difference "
            f"above); put {SECTIONS}/<feature>.md of the evidence into the file"
        )


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
    owners: list[str] = []
    try:
        with sync_playwright() as playwright, page_requests.recording(run.evidence):
            browser = playwright.chromium.launch(**launch_options(playwright))
            try:
                windows = FeatureWindows(browser)
                for name in selected:
                    drive(run, windows, name, driven, options, owners)
            except Exception as exc:
                page_requests.check(exc)
                raise
            finally:
                browser.close()
        page_requests.check()
        compare(run.evidence, sections(run.calls, owners, driven))
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
