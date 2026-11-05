"""Check the verify-centrum-rozliczen skill package and the hygiene of one run's evidence.

Checks the frontmatter, the feature-map headings, that every helper named in
SKILL.md exists and answers ``--help``, the gate of ``wydajnosc`` on made-up
numbers (no browser), that the drive removes and renames files only through
``drive/common.py`` (``remove``, ``move``), that evidence text is strict UTF-8 and screenshots are PNG
files, and that no workbook content (the fixture's row marker) reached the
evidence.
"""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

SCRIPT = Path(__file__).resolve()
SKILL_ROOT = SCRIPT.parents[1]
FEATURES_ROOT = SKILL_ROOT / "features"
SCRIPTS_ROOT = SKILL_ROOT / "scripts"
HELPER_REFERENCE = re.compile(r"scripts[\\/]([A-Za-z0-9_.-]+\.py)")
REQUIRED_MAP_HEADINGS = (
    "# Centrum rozliczeń verification map",
    "## Baseline preconditions",
    "## Driving conventions",
    "## Proof and skip reporting",
    "## Feature entry contract",
)
REQUIRED_FEATURE_HEADINGS = (
    "## Sub-features",
    "## How to get to it (user POV)",
    "## Driving it with Playwright for Python",
    "## Gotchas",
)
ROW_MARKER = "CENTRUM-SYN-ROW"  # create_centrum_fixture.py puts it in every synthetic workbook
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Path methods that fail on Windows while another process holds the file open (WinError 32, #921): the drive calls
# them only inside ``drive/common.py``, whose ``remove`` and ``move`` retry while the server reads the file.
RETRIED_ON_WINDOWS = ("unlink", "rename")


def _check_skill(errors: list[str]) -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---")[1] if skill.startswith("---") else ""
    if "name: verify-centrum-rozliczen" not in frontmatter or "description:" not in frontmatter:
        errors.append("SKILL.md frontmatter needs name: verify-centrum-rozliczen and a description")
    for helper in sorted(set(HELPER_REFERENCE.findall(skill))):
        path = SCRIPTS_ROOT / helper
        if not path.exists():
            errors.append(f"SKILL.md names a missing helper: {helper}")
            continue
        answered = subprocess.run([sys.executable, str(path), "--help"], capture_output=True, check=False)
        if answered.returncode != 0:
            errors.append(f"{helper} --help failed")


def _check_feature_map(errors: list[str]) -> None:
    index = (FEATURES_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in REQUIRED_MAP_HEADINGS:
        if heading not in index.splitlines():
            errors.append(f"features/README.md is missing {heading}")
    files = sorted(path for path in FEATURES_ROOT.glob("*.md") if path.name != "README.md")
    if not files:
        errors.append("features/ holds no feature file")
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        headings = [line for line in lines if line.startswith("## ")]
        if headings != list(REQUIRED_FEATURE_HEADINGS):
            errors.append(f"{path.name} must have exactly the H2s {REQUIRED_FEATURE_HEADINGS}, in order")


def _check_drive_removals(errors: list[str]) -> None:
    """The drive deletes and renames the run's files only through ``remove`` and ``move`` of ``drive/common.py``."""

    for path in sorted((SCRIPTS_ROOT / "drive").glob("*.py")):
        if path.name == "common.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in RETRIED_ON_WINDOWS
            ):
                errors.append(
                    f"drive/{path.name}:{node.lineno} calls .{node.func.attr}(); use remove or move from drive/common.py, "
                    "which retry while the server holds the file open on Windows (#921)"
                )


def _check_retry_while_open(errors: list[str]) -> None:
    """``remove`` and ``move`` outlast a file the server holds open for a moment: Windows refuses twice, then allows."""

    from drive.common import _while_open

    refusals = 2

    def held_for_a_moment() -> None:
        nonlocal refusals
        if refusals:
            refusals -= 1
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    try:
        _while_open(held_for_a_moment)
    except PermissionError:
        errors.append("drive/common.py gives up on a file the server holds open for a moment (#921)")


def _check_performance_gate(errors: list[str]) -> None:
    """The ``wydajnosc`` gate decides on made-up medians and API requests the way features/wydajnosc.md says."""

    from drive.wydajnosc import Measured, compare, over_budget

    scenario, requests = "okresy/zimny-start", ["GET /api/settings", "GET /api/periods"]
    # Budget: max(200 ms × 1.15, 200 ms + 20 ms) = 230 ms.
    baseline: dict[str, Any] = {
        "margines": {"wzgledny": 0.15, "minimalny_ms": 20, "bundle_wzgledny": 0.02},
        "bundle_bajty": {"js": 1000},
        "scenariusze": {scenario: {"mediana_ms": {"4x": 200}, "zapytania_api": {request: 1 for request in requests}}},
    }

    def measured(median_ms: float, sent: list[str] = requests) -> Measured:
        result = Measured(bundle={"js": 1000})
        for offset in (-5, 0, 5):
            result.add(scenario, 4, median_ms + offset, sent)
        return result

    def failures(first: Measured, again: Measured | None = None) -> list[str]:
        report = compare(first, baseline, again)
        return [str(failure) for failure in report["porazki"]]

    slow = measured(260)
    cases = {
        "a median within its budget passes": failures(measured(225)) == [],
        "a median over budget is measured again": over_budget(slow, baseline) == [(scenario, 4)],
        "a median over budget that is within it when measured again passes": failures(slow, measured(225)) == [],
        "a median over budget also when measured again fails": [
            failure for failure in failures(slow, measured(250)) if "ponad budżet" in failure
        ] != [],
        "another number of API requests fails": [
            failure for failure in failures(measured(225, [*requests, requests[0]])) if "inna liczba" in failure
        ] != [],
    }
    for case, held in cases.items():
        if not held:
            errors.append(f"wydajnosc gate: {case} does not hold")


def _check_machine_lock(errors: list[str]) -> None:
    """One measurement at a time on the machine, as SKILL.md says: checked in a scratch lock directory."""

    import tempfile
    import threading

    from quiet_machine import MachineBusy, QuietMachine

    def held(attempt: Any) -> bool:
        try:
            with attempt:
                return True
        except MachineBusy:
            return False

    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)

        def machine(busy: list[str] | None = None) -> QuietMachine:
            return QuietMachine(
                directory,
                quiet_timeout_s=0.3,
                measurement_timeout_s=0.3,
                poll_s=0.05,
                busy_processes=lambda: busy or [],
                report_every_s=None,
            )

        dead_pid = 2**22 + 12345  # far above any live pid on the test machine
        cases: dict[str, bool] = {}
        cases["a measurement on a quiet machine starts"] = held(machine().measurement())
        cases["a run on a quiet machine starts"] = held(machine().run())
        with machine().run():
            cases["a measurement waits for a run in progress"] = not held(machine().measurement())
        with machine().measurement():
            cases["a run waits for a measurement in progress"] = not held(machine().run())
            cases["a second measurement waits for the first"] = not held(machine().measurement())
        cases["a measurement waits for pytest"] = not held(machine(["pytest"]).measurement())
        cases["a run does not wait for pytest"] = held(machine(["pytest"]).run())
        polled = threading.Event()

        def pytest_running() -> list[str]:
            polled.set()
            return ["pytest"]

        waiting = QuietMachine(
            directory, quiet_timeout_s=1, poll_s=0.05, busy_processes=pytest_running, report_every_s=None
        )
        measuring = threading.Thread(target=held, args=(waiting.measurement(),))
        measuring.start()
        polled.wait(timeout=1)
        cases["a run does not wait for a measurement that waits for a quiet CPU"] = held(machine().run())
        measuring.join()
        late_run = directory / "run-late.pid"

        def run_registers_after_first_look() -> list[str]:
            late_run.write_text(str(os.getpid()), encoding="utf-8")
            return []

        racing = QuietMachine(
            directory, quiet_timeout_s=0.3, poll_s=0.05, busy_processes=run_registers_after_first_look, report_every_s=None
        )
        cases["a measurement backs off when a run registers as it takes the lock"] = not held(racing.measurement())
        late_run.unlink()
        (directory / "pomiar.lock").write_text(str(dead_pid), encoding="utf-8")
        (directory / f"run-{dead_pid}.pid").write_text(str(dead_pid), encoding="utf-8")
        cases["locks of a process that died are taken over"] = held(machine().measurement())
        cases["the lock directory is empty after every attempt"] = list(directory.iterdir()) == []
    for case, holds in cases.items():
        if not holds:
            errors.append(f"quiet_machine: {case} does not hold")


def _check_evidence(root: Path, errors: list[str]) -> None:
    if not root.is_dir():
        errors.append(f"evidence directory is missing: {root}")
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".png":
            if not data.startswith(PNG_SIGNATURE):
                errors.append(f"{path.relative_to(root)} is not a PNG")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{path.relative_to(root)} is not UTF-8")
            continue
        if ROW_MARKER in text:
            errors.append(f"{path.relative_to(root)} contains workbook row content")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence-root", help="Evidence of one run; omit to check only the skill package.")
    args = parser.parse_args(argv)
    errors: list[str] = []
    _check_skill(errors)
    _check_feature_map(errors)
    _check_drive_removals(errors)
    _check_retry_while_open(errors)
    _check_performance_gate(errors)
    _check_machine_lock(errors)
    if args.evidence_root:
        _check_evidence(Path(args.evidence_root), errors)
    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL | {error}", file=sys.stderr)
        return 1
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
