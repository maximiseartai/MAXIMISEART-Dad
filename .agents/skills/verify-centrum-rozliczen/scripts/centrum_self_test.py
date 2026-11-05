"""Check the verify-centrum-rozliczen skill package and the hygiene of one run's evidence.

Checks the frontmatter, the feature-map headings, that every helper named in
SKILL.md exists and answers ``--help``, the gate of ``wydajnosc`` on made-up
numbers (no browser), that the drive deletes, moves and replaces files and folders
only through the retrying helpers of ``drive/common.py``, that evidence text is strict UTF-8 and screenshots are PNG
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
# Deleting, moving or replacing a file or folder fails on Windows while another process holds it open (WinError 32,
# #921), so the drive does it only through the retrying helpers of ``drive/common.py`` (``DRIVE_HELPERS``). The
# forms the guard catches and its boundary are the table in ``_removals``; ``REMOVAL_SAMPLES`` holds samples of each.
OS_REMOVALS = frozenset({"remove", "unlink", "rename", "replace", "renames", "rmdir", "removedirs"})
SHUTIL_REMOVALS = frozenset({"move", "rmtree"})
REMOVING_MODULES = {"os": OS_REMOVALS, "shutil": SHUTIL_REMOVALS, "pathlib": frozenset()}
# Attributes no other object of the drive has: any access counts, also an alias such as ``Path.unlink``.
REMOVING_ATTRIBUTES = frozenset({"unlink", "rename", "rmdir", "rmtree", "removedirs", "renames", "move_into"})
# Path methods whose names other objects share (``str.replace``, ``page.mouse.move``): a call with the Path signature
# (one positional argument, or only ``target=``), or any access on a pathlib class.
ONE_TARGET_METHODS = frozenset({"replace", "move"})
PATHLIB_CLASSES = frozenset({"Path", "PurePath", "PosixPath", "WindowsPath", "PurePosixPath", "PureWindowsPath"})
DRIVE_HELPERS = frozenset({"_while_open", "remove", "remove_tree", "remove_empty_folder", "move", "replace_file"})
REMOVAL_SAMPLES = (
    "p.unlink()",
    "p.unlink(missing_ok=True)",
    "p.rename(q)",
    "p.rmdir()",
    "p.replace(q)",
    "p.replace(target=q)",
    "p.move(target=q)",
    "p.rename(target=q)",
    "p.move(q)",
    "p.move_into(folder)",
    "drop = Path.unlink",
    "from pathlib import Path\nswap = Path.replace",
    "from pathlib import Path as P\nswap = P.replace",
    "import pathlib\nswap = pathlib.Path.move",
    "import os\nos.remove(p)",
    "import os\nos.unlink(p)",
    "import os\nos.rename(p, q)",
    "import os\nos.replace(p, q)",
    "import os\nos.renames(p, q)",
    "import os\nos.rmdir(p)",
    "import os\nos.removedirs(p)",
    "import os as system\nsystem.remove(p)",
    "import os\nsystem = os\nsystem.remove(p)",
    "import os\nsystem = os\nplatform = system\nplatform.replace(p, q)",
    "import shutil\nfiles = shutil\nfiles.rmtree(p)",
    "import os.path\nos.remove(p)",
    "import shutil\nshutil.move(p, q)",
    "import shutil\nshutil.rmtree(p)",
    "import shutil\nshutil.rmtree(p, ignore_errors=True)",
    "import shutil as sh\nsh.move(p, q)",
    "from os import remove",
    "from os import replace as swap",
    "from shutil import rmtree",
    "from shutil import move as shift",
    "from os import *",
    "from shutil import *",
    "from pathlib import *",
    "getattr(p, 'unlink')()",
    "import os\ngetattr(os, 'remove')(p)",
)
LOOKALIKE_SAMPLES = (
    "text.replace('a', 'b')",
    "text.replace(*pair)",
    "text.replace('a', 'b', count=1)",
    "import dataclasses\nchange = dataclasses\nchange.replace(item)",
    "moment.replace(tzinfo=zone)",
    "import dataclasses\ndataclasses.replace(item)",
    "import dataclasses\ndataclasses.replace(item, name='x')",
    "page.mouse.move(4, 4)",
    "items.remove(item)",
    "import os\nos.path.join(a, b)",
    "import os\nos.kill(pid, 9)",
    "import shutil\nshutil.copytree(a, b)\nshutil.copyfile(a, b)\nshutil.copy2(a, b)",
    "from pathlib import Path\nPath(a).write_bytes(b'')",
    "from drive.common import move, remove\nremove(p)\nmove(p, q)",
    "getattr(page, 'url')",
)


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


def _removals(source: str, helpers: frozenset[str] = frozenset()) -> list[str]:
    """Each deletion, move or replacement of a file or folder in ``source`` in one of the forms below, outside the
    top-level functions ``helpers``, as ``<line>: <form>``.

    The guard catches exactly these forms (a sample of each is in ``REMOVAL_SAMPLES``):

    1. any access to an attribute of ``REMOVING_ATTRIBUTES`` (``p.unlink()``, ``p.rename(target=q)``, ``p.rmdir()``,
       ``os.unlink``, ``Path.unlink`` as a value, ``p.move_into(d)``);
    2. an attribute of ``OS_REMOVALS`` or ``SHUTIL_REMOVALS`` on a name bound to ``os`` or ``shutil`` by
       ``import os|shutil [as x]`` or by an assignment ``x = os`` (also chained, ``y = x``);
    3. ``from os|shutil import <name of those sets>``, and ``from os|shutil|pathlib import *``;
    4. ``replace`` or ``move`` on a pathlib class (``Path.replace``, ``pathlib.Path.move``, ``P.replace`` after
       ``from pathlib import Path as P``);
    5. a call ``x.replace(...)`` or ``x.move(...)`` with the Path signature, one positional argument or only
       ``target=``, unless ``x`` is an imported module (``dataclasses.replace(item)``);
    6. ``getattr(x, "<name>")`` with a constant name of those sets.

    Its boundary, which review still checks: a bound method assigned to a name (``swap = p.replace; swap(q)``), the
    modules ``posix`` and ``nt``, a copy onto a file the server reads (``shutil.copy2``, ``shutil.copyfile``,
    ``shutil.copytree(..., dirs_exist_ok=True)``; today no copy in ``drive/`` targets one), a shell command (``rm``,
    ``del``, ``Remove-Item``), ``importlib`` or ``__import__``, a name computed at run time (``getattr`` with a
    variable, ``vars(os)[...]``, ``operator.methodcaller``), and ``tempfile`` cleanup."""

    tree = ast.parse(source)
    skipped = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helpers
        for inner in ast.walk(node)
    }
    modules: dict[str, str] = {}
    imported: set[str] = set()
    pathlib_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                bound = alias.asname or root
                imported.add(bound)
                if root in REMOVING_MODULES:
                    modules[bound] = root
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            pathlib_classes.update(alias.asname or alias.name for alias in node.names if alias.name in PATHLIB_CLASSES)
    assignments = [
        (target.id, node.value.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    aliased = True
    while aliased:  # ``system = os``, also chained: until no assignment binds a new name to an imported module
        aliased = False
        for bound, source in assignments:
            if source in imported and bound not in imported:
                imported.add(bound)
                aliased = True
            if source in modules and modules.get(bound) != modules[source]:
                modules[bound] = modules[source]
                aliased = True

    def pathlib_class(value: ast.expr) -> bool:
        if isinstance(value, ast.Name):
            return value.id in pathlib_classes
        return (
            isinstance(value, ast.Attribute)
            and value.attr in PATHLIB_CLASSES
            and isinstance(value.value, ast.Name)
            and modules.get(value.value.id) == "pathlib"
        )

    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.ImportFrom) and node.module in REMOVING_MODULES:
            for alias in node.names:
                if alias.name == "*" or alias.name in REMOVING_MODULES[node.module]:
                    found.add((node.lineno, f"from {node.module} import {alias.name}"))
        elif isinstance(node, ast.Attribute):
            owner = node.value.id if isinstance(node.value, ast.Name) else None
            if node.attr in REMOVING_ATTRIBUTES:
                found.add((node.lineno, f".{node.attr}"))
            elif owner in modules and node.attr in REMOVING_MODULES[modules[owner]]:
                found.add((node.lineno, f"{modules[owner]}.{node.attr}"))
            elif node.attr in ONE_TARGET_METHODS and pathlib_class(node.value):
                found.add((node.lineno, f"Path.{node.attr}"))
        elif isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr in ONE_TARGET_METHODS
                and (
                    (
                        len(node.args) == 1
                        and not any(isinstance(argument, ast.Starred) for argument in node.args)
                        and not node.keywords
                    )
                    or (not node.args and [keyword.arg for keyword in node.keywords] == ["target"])
                )
                and not (isinstance(function.value, ast.Name) and function.value.id in imported)
            ):
                found.add((node.lineno, f".{function.attr}(target)"))
            elif (
                isinstance(function, ast.Name)
                and function.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in REMOVING_ATTRIBUTES | OS_REMOVALS | SHUTIL_REMOVALS | ONE_TARGET_METHODS
            ):
                found.add((node.lineno, f"getattr(…, {node.args[1].value!r})"))
    return [f"{line}: {form}" for line, form in sorted(found)]


def _helpers_of(name: str) -> frozenset[str]:
    """The functions of ``drive/<name>`` that may delete and move: only the retrying helpers of ``common.py``."""

    return DRIVE_HELPERS if name == "common.py" else frozenset()


def _check_drive_removals(errors: list[str]) -> None:
    """The drive deletes, moves and replaces files and folders only through the helpers of ``drive/common.py``, and
    the guard catches every form of ``REMOVAL_SAMPLES`` and none of ``LOOKALIKE_SAMPLES``."""

    for sample in REMOVAL_SAMPLES:
        if not _removals(sample):
            errors.append(f"the guard of #921 misses a deletion or move: {sample!r}")
    for sample in LOOKALIKE_SAMPLES:
        if _removals(sample):
            errors.append(f"the guard of #921 takes {sample!r} for a deletion or move: {_removals(sample)}")
    if not _removals("def remove(path):\n    path.unlink()\n", _helpers_of("kontrola_ilosci.py")):
        errors.append("the guard of #921 lets a feature hide a deletion in its own function named like a helper")
    for path in sorted((SCRIPTS_ROOT / "drive").glob("*.py")):
        for finding in _removals(path.read_text(encoding="utf-8"), _helpers_of(path.name)):
            errors.append(
                f"drive/{path.name}:{finding}; delete, move and replace through remove, remove_tree, "
                "remove_empty_folder, move or replace_file of drive/common.py, which retry while the server holds the "
                "file open on Windows (#921)"
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


def _check_drop_report_key(errors: list[str]) -> None:
    """``drop_report_key`` empties a key the step wrote, and refuses one it never wrote unless ``missing_ok``."""

    import tempfile

    from drive.common import DriveFailure, drop_report_key

    with tempfile.TemporaryDirectory() as scratch:
        key_file = Path(scratch) / "zgloszenia-klucz.txt"
        key_file.write_text("KLUCZ\n", encoding="utf-8")
        drop_report_key(key_file)
        if key_file.read_bytes() != b"":
            errors.append("drop_report_key leaves the key in its file")
        for missing_ok in (False, True):
            try:
                drop_report_key(key_file, missing_ok=missing_ok)
            except DriveFailure:
                if missing_ok:
                    errors.append("drop_report_key(missing_ok=True) refuses a file without a key")
            else:
                if not missing_ok:
                    errors.append("drop_report_key takes away a key the step never wrote, which the removal refused")


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
    _check_drop_report_key(errors)
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
