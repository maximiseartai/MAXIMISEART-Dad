"""Check the verify-centrum-rozliczen skill package and the hygiene of one run's evidence.

Checks the frontmatter, the feature-map headings, that every helper named in
SKILL.md exists and answers ``--help``, the gate of ``wydajnosc`` on made-up
numbers (no browser), that the retrying helpers of ``drive/common.py`` outlast a
file the server holds open, retry nothing else and nothing longer, and take the key away only after a step wrote it,
that the result of a started Uruchomienie is never the one before it and the Centrum log is read as ``log.py`` writes it,
that a file the server puts in place is read once it is there and only a vanished queue file is left out,
that the drive reads files in no other way than through those readers (``_direct_reads``),
that the scripted skrzynka reads an issue file the drive is putting in place once it is there,
that the scripted boundaries of ``serve_centrum.py`` take their files from ``harness.py`` in the round trips of
``_check_served_side_reads_harness`` and no other script spells a name of ``harness.py`` (``_protocol_spelled``),
that Centrum's clock reads each move of the drive whole, also while the system refuses a read for a moment, stands still
without a move and fails on a refusal that outlasts its limit, that the drive fails on the clock's wake-up thread once it has died,
that the drive deletes, moves and replaces in none of the forms of ``_removals`` outside those helpers, that
evidence text is strict UTF-8 and screenshots are PNG files, and that no workbook content (the fixture's row marker) reached the
evidence.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from atrapy.scenariusz_centrum import ROW_MARKER
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.tool_files import config_dir

from harness import File, issue_file

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
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# How long a read of Centrum's clock may take in the self-test before it counts as one that never answers.
CLOCK_ANSWER_S = 5.0
# Deleting, moving or replacing a file or folder fails on Windows while another process holds it open (WinError 32,
# #921), so the drive does it only through the retrying helpers of ``drive/common.py`` (``DRIVE_HELPERS``). The forms
# the guard ``_removals`` catches and its boundary are the tables of its docstring and of features/README.md; ruff
# ``TID251`` (``drive/ruff.toml``) rejects the functions of ``os``, ``shutil`` and the pathlib classes it can resolve,
# each ban with a sample in ``tests/test_zakazy_ruff.py``.
# Only deletions and moves have attributes of these names (pathlib, ``os``, ``shutil``): form 1 takes them on anything.
ONLY_REMOVING = frozenset({"unlink", "rename", "rmdir", "rmtree", "removedirs", "renames", "move_into"})
# Path methods whose names other objects share (``str.replace``, ``page.mouse.move``): form 2.
PATH_SHARED = frozenset({"replace", "move"})
# Deletions and moves whose names other objects share (``list.remove``), which form 3 takes in ``getattr``.
SHARED_REMOVING = frozenset({"remove", *PATH_SHARED})
DRIVE_HELPERS = frozenset({"remove", "remove_tree", "remove_empty_folder", "move", "replace_file"})
# The readers of ``drive/common.py`` that wait while the server puts a file in place (#1087); ``read_json`` reads
# through ``read_text``.
DRIVE_READERS = frozenset({"read_text", "read_bytes"})
GUARD_HEADING = "### Guard of deletions in the drive"  # the section of features/README.md with the guard's tables
# Each sample of a deletion or move with the one finding the guard reports for it.
REMOVAL_SAMPLES = {
    "p.unlink()": ".unlink (form 1)",
    "p.unlink(missing_ok=True)": ".unlink (form 1)",
    "p.rename(q)": ".rename (form 1)",
    "p.rename(target=q)": ".rename (form 1)",
    "p.rmdir()": ".rmdir (form 1)",
    "p.move_into(folder)": ".move_into (form 1)",
    "import os\nos.unlink(p)": ".unlink (form 1)",
    "import os\nos.renames(p, q)": ".renames (form 1)",
    "import os\nos.removedirs(p)": ".removedirs (form 1)",
    "import shutil\nshutil.rmtree(p, ignore_errors=True)": ".rmtree (form 1)",
    "from pathlib import Path\ndrop = Path.unlink": ".unlink (form 1)",
    "type(p).unlink(p)": ".unlink (form 1)",
    "import os\nfs = os\nfs.unlink(p)": ".unlink (form 1)",
    "import os\nimport shutil\nfs = os\nfs = shutil\nfs.rmtree(p)": ".rmtree (form 1)",
    "p.replace(q)": ".replace(target) (form 2)",
    "p.replace(target=q)": ".replace(target) (form 2)",
    "p.move(q)": ".move(target) (form 2)",
    "p.move(target=q)": ".move(target) (form 2)",
    "from pathlib import Path\nPath(p).replace(q)": ".replace(target) (form 2)",
    "getattr(p, 'unlink')()": "getattr(…, 'unlink') (form 3)",
    "import os\ngetattr(os, 'remove')(p)": "getattr(…, 'remove') (form 3)",
    "getattr(p, 'replace')(q)": "getattr(…, 'replace') (form 3)",
    "import shutil\ngetattr(shutil, 'move', None)": "getattr(…, 'move') (form 3)",
}
LOOKALIKE_SAMPLES = (
    "text.replace('a', 'b')",
    "text.replace('a', 'b', count=1)",
    "text.replace(*pair)",
    "moment.replace(tzinfo=zone)",
    "import dataclasses\ndataclasses.replace(item)",
    "import dataclasses\ndataclasses.replace(item, name='x')",
    "from dataclasses import replace\nreplace(item)",
    "page.mouse.move(4, 4)",
    "items.remove(item)",
    "import os\nos.path.join(a, b)\nos.kill(pid, 9)",
    "import os.path as osp\nosp.join(a, b)",
    "import shutil\nshutil.copytree(a, b)\nshutil.copyfile(a, b)\nshutil.copy2(a, b)\nshutil.which('python')",
    "from pathlib import Path\nPath(a).write_bytes(b'')",
    "from drive.common import move, remove, remove_tree, replace_file\nremove(p)\nmove(p, q)\nremove_tree(p)\n"
    "replace_file(p, q)",
    "getattr(page, 'url')",
    "from .os import remove",
    # One name for two modules, which hung the guard of #925's third round: assignments bind no module here.
    "import os\nimport shutil\nfs = os\nfs.getcwd()\nfs = shutil\nfs.which('python')",
)

# A path part of a file of harness.py the product names too, so the guard ``_protocol_spelled`` takes it only as an
# operand of ``/``.
SHARED_PARTS = {
    "brak-sieci": "the przyczyna of a skrzynka-czeka line in the Centrum log (src), which the drive checks",
    "efenix": "the name of the process Wycena w efenix, its metrics and its Logi",
    "skrzynka-archiwum": "the event of the Logi (src) when a send already in the skrzynka reached the Archiwum okresu",
}
# A name of harness.py spelled in each of its forms, which the guard ``_protocol_spelled`` reports.
PROTOCOL_SAMPLES = (
    'run.lines("opened.jsonl")',
    'root / "skrzynka-zgloszen" / "odmawia-klucza"',
    'box / f"odrzuca-{label}"',
    'box / "brak-sieci"',
    'root / "efenix" / PERIOD',
    'root / "skrzynka-archiwum" / tag',
    'f"skrzynka-zgloszen/{number}.json#komentarz-{index}"',
    'Path(root, "github", "main-commit.txt")',
    'root / "pacing" / name',
    'root / "fixture.json"',
)
# Strings beside those names, which the guard leaves alone.
PROTOCOL_LOOKALIKES = (
    '"""``<root>/opened.jsonl`` in a docstring."""',
    'run.step(FEATURE, "aktualizacja-brak-sieci")',
    'facts.get("przyczyna") == "brak-sieci"',
    'process == "efenix"',
    'entry.event == "skrzynka-archiwum"',
    'run.capture(page, "77-aktualnosc-brak-sieci")',
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
    """Each deletion, move or replacement of a file or folder in ``source`` in a form of the first table, outside the
    top-level functions ``helpers``, as ``<line>: <what> (form <n>)``.

    Ruff ``TID251`` (``drive/ruff.toml``) already rejects each name it resolves through ``import [as x]``, ``from …
    import … [as x]`` or an attribute to ``os.remove``, ``os.unlink``, ``os.rmdir``, ``os.removedirs``, ``os.rename``,
    ``os.renames``, ``os.replace``, ``shutil.rmtree``, ``shutil.move``, or ``replace`` and ``move`` of ``pathlib.Path``,
    ``PosixPath`` and ``WindowsPath`` (``import os as system; system.replace(p, q)``, ``partial(os.remove, p)``,
    ``from shutil import rmtree``, ``P.move(p, q)``), and ruff ``F403`` rejects ``from os import *``. This guard catches
    only these forms, which ruff cannot resolve, mostly a method on an instance; it knows a module only by a name an
    ``import`` binds, never by an assignment, which form 2 skips:

    | Form | The guard catches | Example |
    |---|---|---|
    | 1 | an attribute `unlink`, `rename`, `rmdir`, `rmtree`, `removedirs`, `renames` or `move_into` on anything, called or not | `p.unlink(missing_ok=True)`, `p.rename(target=q)`, `os.renames(p, q)`, `shutil.rmtree(p)`, `drop = Path.unlink`, `fs = os; fs.unlink(p)` |
    | 2 | a call `x.replace(…)` or `x.move(…)` with one positional argument and no named one, or with only `target=`, where `x` is not a name that an `import` binds | `p.replace(q)`, `p.move(target=q)`, `Path(p).replace(q)` |
    | 3 | `getattr(x, "<name>", …)` with a constant name of form 1, `remove`, `replace` or `move` | `getattr(p, "unlink")()`, `getattr(os, "remove")(p)` |

    Its boundary, which review checks:

    | Boundary | Passes the guard |
    |---|---|
    | a module or pathlib class through a name that no import binds (forms 1 and 2 still catch on it) | `fs = os; fs.remove(p)`, `s: ModuleType = os; s.replace(p, q)`, `Q = Path; Q.replace(p, q)`, `self.files = shutil` |
    | `replace` or `move` of an object kept or passed instead of called (form 2 takes only a call) | `swap = p.replace; swap(q)`, `retry(p.move, q)` |
    | a call of form 2 with unpacked arguments | `p.replace(*args)`, `p.move(**named)` |
    | a call of form 2 on a name that an `import` in the file also binds | `import time` and elsewhere `time = p; time.replace(q)` |
    | a pathlib class from an expression | `type(p).replace(p, q)`, `p.__class__.move(p, q)` |
    | another module | `posix`, `nt`, `_winapi`, `ctypes` |
    | a name computed at run time, or a name in a string outside `getattr` | `getattr(p, name)`, `operator.methodcaller("unlink")`, `vars(os)["remove"]`, `sys.modules["os"]`, `importlib`, `__import__`, `eval` |
    | another process | `subprocess` with `rm`, `del`, `Remove-Item` or `move`, `os.system` |
    | no deletion or move | a copy onto a file the server reads (`shutil.copy2`, `copyfile`, `copytree(…, dirs_exist_ok=True)`), a write (`open(p, "w")`, `write_bytes`, `workbook.save`), `tempfile` cleanup |
    | code outside `drive/*.py` | `drive_centrum.py`, `create_centrum_fixture.py`, `serve_centrum.py` |

    A false alarm is loud and names the helpers: form 1 on an object that is no file (`frame.rename(columns=…)`), form 2
    on any object with a one-argument `replace` or `move` (`moment.replace(2026)`), form 3 on any object."""

    tree = ast.parse(source)
    skipped = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helpers
        for inner in ast.walk(node)
    }
    # Each name an ``import`` binds: ``import os.path`` binds ``os``, ``import os.path as p`` binds ``p``.
    modules = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    def path_signature(call: ast.Call) -> bool:
        one_positional = len(call.args) == 1 and not isinstance(call.args[0], ast.Starred) and not call.keywords
        return one_positional or (not call.args and [keyword.arg for keyword in call.keywords] == ["target"])

    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Attribute) and node.attr in ONLY_REMOVING:
            found.add((node.lineno, f".{node.attr} (form 1)"))
        elif isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr in PATH_SHARED
                and path_signature(node)
                and not (isinstance(function.value, ast.Name) and function.value.id in modules)
            ):
                found.add((node.lineno, f".{function.attr}(target) (form 2)"))
            elif (
                isinstance(function, ast.Name)
                and function.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in ONLY_REMOVING | SHARED_REMOVING
            ):
                found.add((node.lineno, f"getattr(…, {node.args[1].value!r}) (form 3)"))
    return [f"{line}: {form}" for line, form in sorted(found)]


def _helpers_of(name: str) -> frozenset[str]:
    return DRIVE_HELPERS if name == "common.py" else frozenset()


def _check_drive_removals(errors: list[str]) -> None:
    """The drive deletes, moves and replaces files and folders only through the helpers of ``drive/common.py``: the
    guard reports each sample of ``REMOVAL_SAMPLES`` as its one form and nothing in ``LOOKALIKE_SAMPLES``."""

    for sample, form in REMOVAL_SAMPLES.items():
        forms = [finding.split(": ", 1)[1] for finding in _removals(sample)]
        if forms != [form]:
            errors.append(f"the guard of #934 reports {forms} for {sample!r} instead of {form}")
    for sample in LOOKALIKE_SAMPLES:
        if found := _removals(sample):
            errors.append(f"the guard of #934 takes {sample!r} for a deletion or move: {found}")
    if not _removals("def remove(path):\n    path.unlink()\n", _helpers_of("kontrola_ilosci.py")):
        errors.append("the guard of #934 lets a feature hide a deletion in its own function named like a helper")
    for path in sorted((SCRIPTS_ROOT / "drive").glob("*.py")):
        for finding in _removals(path.read_text(encoding="utf-8"), _helpers_of(path.name)):
            errors.append(
                f"drive/{path.name}:{finding}; delete, move and replace through remove, remove_tree, "
                "remove_empty_folder, move or replace_file of drive/common.py, which retry while the server holds the "
                "file open on Windows (#921)"
            )


def _direct_reads(source: str, helpers: frozenset[str] = frozenset()) -> list[str]:
    """Each attribute ``read_text`` or ``read_bytes`` in ``source``, called or not, and each ``getattr`` with one of
    those names as a constant, outside the top-level functions ``helpers``, as ``<line>: .<name>``: the drive reads
    files only through ``read_text``, ``read_bytes`` and ``read_json`` of ``drive/common.py``, which wait while the
    server puts a file in place (#1087).

    It takes every file for one the server may put in place, so no list of the server's files can fall behind it. Its
    boundary, which review checks: a handle (``path.open()``, ``open(path)``, ``with … as handle: handle.read()``), a
    library that opens the path itself (``load_workbook``, ``gzip.open``, ``yaml.safe_load`` of a handle), a name
    computed at run time (``getattr(p, name)``, ``operator.methodcaller("read_text")``), another process, and code
    outside ``drive/*.py``."""

    tree = ast.parse(source)
    skipped = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helpers
        for inner in ast.walk(node)
    }
    found = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Attribute) and node.attr in DRIVE_READERS:
            found.append((node.lineno, node.attr))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in DRIVE_READERS
        ):
            found.append((node.lineno, str(node.args[1].value)))
    return [f"{line}: .{name}" for line, name in sorted(found)]


def _check_drive_reads(errors: list[str]) -> None:
    """The drive reads files only through the readers of ``drive/common.py``: the guard reports a read in any form of
    ``Path`` and leaves the readers themselves and a call of them alone."""

    for sample in (
        'p.read_text(encoding="utf-8")',
        "p.read_bytes()",
        "while_open(p.read_bytes)",
        "(a / b).read_text()",
        "map(Path.read_bytes, paths)",
        "getattr(p, 'read_text')()",
    ):
        if len(_direct_reads(sample)) != 1:
            errors.append(f"the guard of reads takes {sample!r} for no read of a file")
    for sample in ("read_text(p)", "read_bytes(a / b)", "read_json(p)['x']"):
        if found := _direct_reads(sample):
            errors.append(f"the guard of reads takes {sample!r} for a direct read: {found}")
    if not _direct_reads("def read_text(path):\n    return path.read_text()\n", frozenset()):
        errors.append("the guard of reads lets a feature hide a read in its own function named like a reader")
    beside = "def read_text(path):\n    return path.read_text()\n\n\ndef issue(path):\n    return path.read_text()\n"
    if _direct_reads(beside, DRIVE_READERS) != ["6: .read_text"]:
        errors.append("the guard of reads leaves alone more of common.py than its readers: a read beside them passes")
    for path in sorted((SCRIPTS_ROOT / "drive").glob("*.py")):
        helpers = DRIVE_READERS if path.name == "common.py" else frozenset()
        for finding in _direct_reads(path.read_text(encoding="utf-8"), helpers):
            errors.append(
                f"drive/{path.name}:{finding}; read through read_text, read_bytes or read_json of drive/common.py, which "
                "wait while the server puts the file in place on Windows (#1087)"
            )


def _check_guard_documented(errors: list[str]) -> None:
    """features/README.md shows the forms and the boundary of the guard as the table rows of ``_removals``, in order."""

    rows = [line.strip() for line in (_removals.__doc__ or "").splitlines() if line.strip().startswith("|")]
    readme = (FEATURES_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    section = readme[readme.index(GUARD_HEADING) + 1 :] if GUARD_HEADING in readme else []
    end = next((index for index, line in enumerate(section) if line.startswith("#")), len(section))
    shown = [line.strip() for line in section[:end] if line.strip().startswith("|")]
    if not rows or shown != rows:
        errors.append(
            f"features/README.md must show under {GUARD_HEADING!r} the table rows of the docstring of _removals in "
            f"centrum_self_test.py, in order: it misses {[row for row in rows if row not in shown]} and has "
            f"{[row for row in shown if row not in rows]} besides"
        )


def _check_retry_while_open(errors: list[str]) -> None:
    """The helpers outlast a file the server holds open for a moment (Windows refuses twice, then allows), and raise
    any other error at once and a refusal that outlasts its limit after it; ``remove_tree`` takes a missing
    folder for removed only with ``missing_ok``."""

    import tempfile

    from drive import common, waiting

    refusals = 2

    def held_for_a_moment() -> None:
        nonlocal refusals
        if refusals:
            refusals -= 1
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    try:
        waiting.while_open(held_for_a_moment)
    except PermissionError:
        errors.append("while_open of drive/waiting.py gives up on a file the server holds open for a moment (#921)")
    attempts = 0

    def missing_at_first() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FileNotFoundError(2, "No such file or directory")

    try:
        waiting.while_open(missing_at_first)
    except FileNotFoundError:
        pass
    else:
        errors.append("while_open of drive/waiting.py retries an error other than a file the server holds open, so it hides it")

    def held_for_good() -> None:
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    try:
        waiting.while_open(held_for_good, limit_s=0.2)  # a refusal for good, without waiting the whole limit
    except PermissionError:
        pass
    else:
        errors.append("drive/common.py swallows a refusal that outlasts its limit, so the drive goes on without it")
    with tempfile.TemporaryDirectory() as scratch:
        missing = Path(scratch) / "brak"
        try:
            common.remove_tree(missing)
        except FileNotFoundError:
            pass
        else:
            errors.append("remove_tree takes a missing folder for removed without missing_ok")
        try:
            common.remove_tree(missing, missing_ok=True)
        except FileNotFoundError:
            errors.append("remove_tree(missing_ok=True) refuses a missing folder")


def _check_result_of_start(errors: list[str]) -> None:
    """``result_of_start`` (and ``run_again``) returns the Uruchomienie Dad's click started, though the server may show
    the one before it as finished until the tab's request arrives (the flaky „the same stop again offers Diagnoza”),
    and also when it shows the new one at once, so the one before is read before the click."""

    import contextlib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import io
    import json
    import tempfile
    import threading

    from drive.common import DriveFailure, Run, result_of_start
    from drive.waiting import TimedOut

    for late in (2, 0):
        # Reads of the current Uruchomienie since Dad's click; the server shows the new one after `late` of them.
        since_click: list[int] = []

        class Scripted(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if since_click:
                    since_click[0] += 1
                new = bool(since_click) and since_click[0] > late
                shown = {"id": "nowe", "stop_kind": "repeated"} if new else {"id": "poprzednie", "stop_kind": "for_tata"}
                body = json.dumps(
                    {"state": "finished", "run": {"id": shown["id"]}, "result": {"stop_kind": shown["stop_kind"]}}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Scripted)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch) / "run"
                root.mkdir()
                File.FIXTURE.write(root, "{}")
                run = Run(root, f"http://127.0.0.1:{server.server_port}/", Path(scratch) / "evidence")
                with contextlib.redirect_stdout(io.StringIO()):
                    result: object = result_of_start(run, "powtorka", lambda: since_click.append(0))
        except (DriveFailure, TimedOut) as failure:
            result = failure
        finally:
            server.shutdown()
            server.server_close()
        if result != {"stop_kind": "repeated"}:
            errors.append(
                f"result_of_start with the new Uruchomienie shown after {late} reads took another one for it: {result}"
            )


def _read_while_put_in_place(path: Path, read: Callable[[], object]) -> object:
    """What ``read`` gives, or the refusal it raises, while another thread puts ``path`` in place: the system refuses
    to read it for 0.3 s (``unreadable``), as Windows does while a file is put in place (#1087)."""

    import contextlib
    import io
    import threading
    import time

    from drive.common import unreadable

    refusing = threading.Event()

    def put_in_place() -> None:
        with unreadable(path):
            refusing.set()
            time.sleep(0.3)

    with contextlib.redirect_stdout(io.StringIO()):
        server = threading.Thread(target=put_in_place)
        server.start()
        refusing.wait()
        try:
            return read()
        except PermissionError as failure:
            return failure
        finally:
            server.join()


def _check_read_while_put_in_place(errors: list[str]) -> None:
    """``read_text``, ``read_bytes``, ``run_logs`` (through ``read_json``) and ``Run.remembered`` wait while the server
    puts a file of Logi or the settings file in place, which refuses a read for a moment on Windows (#1087, the night of
    #1132), and ``queued_posts`` leaves out only a queue file that is gone, never one it cannot read."""

    import json
    import tempfile

    from drive.common import Run, queued_posts, read_bytes, read_text, run_logs

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "run"
        root.mkdir()
        settings = config_dir(root) / SETTINGS_FILE
        File.FIXTURE.write(root, json.dumps({"settings": str(settings)}))
        run = Run(root, "http://127.0.0.1:1/", Path(scratch) / "evidence")
        run.run_logs_dir.mkdir(parents=True)
        logs = run.run_logs_dir / "20261019T060000Z-preparation-aaaaaaaa.json"
        logs.write_text(json.dumps({"run_id": "aaaaaaaa"}), encoding="utf-8")
        settings.parent.mkdir()
        settings.write_text("rejestr_zlecen: INTERMAX.xlsx\n", encoding="utf-8")

        read = _read_while_put_in_place(logs, lambda: read_text(logs))
        if read != '{"run_id": "aaaaaaaa"}':
            errors.append(f"read_text gives up on a file the server is putting in place: {read!r}")
        read = _read_while_put_in_place(logs, lambda: read_bytes(logs))
        if read != b'{"run_id": "aaaaaaaa"}':
            errors.append(f"read_bytes gives up on a file the server is putting in place: {read!r}")
        read = _read_while_put_in_place(logs, lambda: run_logs(run))
        if read != {logs.name: {"run_id": "aaaaaaaa"}}:
            errors.append(f"run_logs gives up on a file of Logi the server is putting in place: {read!r}")
        read = _read_while_put_in_place(settings, lambda: run.remembered("rejestr_zlecen"))
        if read != "INTERMAX.xlsx":
            errors.append(f"Run.remembered gives up on the settings file the server is putting in place: {read!r}")

        # Windows creates no symbolic link without a privilege; the forms of a vanished and an unreadable file are
        # the same there, and a refusal is retried for RETRY_OPEN_S, so the queue is checked where links are free.
        if sys.platform == "win32":
            return
        run.queue.mkdir(parents=True)
        (run.queue / "1-zgloszenie-aaaaaaaa.json").write_text(json.dumps({"parts": ["czeka"]}), encoding="utf-8")
        (run.queue / "2-zgloszenie-bbbbbbbb.json").symlink_to(run.queue / "wyslany.json")
        if queued_posts(run, "zgloszenie") != [{"parts": ["czeka"]}]:
            errors.append("queued_posts does not leave out a queue file the queue delivered and removed meanwhile")
        loop = run.queue / "3-zgloszenie-cccccccc.json"
        loop.symlink_to(loop)
        try:
            queued_posts(run, "zgloszenie")
        except FileNotFoundError:
            errors.append("queued_posts takes a queue file it cannot read for one that is gone")
        except OSError:
            pass
        else:
            errors.append("queued_posts leaves out a queue file it cannot read, so a lost post passes")


def _check_clock_moved_whole(errors: list[str]) -> None:
    """Centrum's clock (``ScriptedClock``) reads each move of ``advance_clock`` whole while its wake-up thread asks it
    every 0.2 s: a read of a half-written file stopped that thread, so the queue never tried again (#1124). A read the
    system refuses while the file is put in place (#1087) waits for it."""

    import contextlib
    import io
    import json
    import tempfile
    import threading
    import time

    from drive.common import Run, advance_clock, unreadable
    from serve_centrum import ScriptedClock

    moves = 200
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "run"
        root.mkdir()
        File.FIXTURE.write(root, json.dumps({"settings": str(root / "config" / "s.yaml")}))
        run = Run(root, "http://127.0.0.1:1/", Path(scratch) / "evidence")
        clock = ScriptedClock(root)
        failures: list[BaseException] = []
        moved = threading.Event()

        def read_meanwhile() -> None:
            while not moved.is_set():
                try:
                    clock()
                except (ValueError, OSError) as failure:
                    failures.append(failure)
                    return

        reader = threading.Thread(target=read_meanwhile)
        reader.start()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for _ in range(moves):
                    advance_clock(run, 1, "the self-test reads it meanwhile")
        finally:
            moved.set()
            reader.join()
        if failures:
            errors.append(f"Centrum's clock fails on a move of advance_clock it reads meanwhile: {failures[0]!r}")
        if clock() - time.monotonic() < moves * 60 - 1:
            errors.append(f"Centrum's clock does not stand {moves} minutes on after {moves} moves of one minute")

        refusing = threading.Event()

        def put_in_place() -> None:
            with unreadable(File.CLOCK_MOVE.file(root)):
                refusing.set()
                time.sleep(0.3)

        with contextlib.redirect_stdout(io.StringIO()):
            server = threading.Thread(target=put_in_place)
            server.start()
            refusing.wait()
            try:
                waited: object = clock() - time.monotonic() >= moves * 60 - 1
            except PermissionError as failure:
                waited = failure
            server.join()
        if waited is not True:
            errors.append(f"Centrum's clock gives up on a move the drive is putting in place: {waited!r}")


def _check_clock_without_move(errors: list[str]) -> None:
    """Centrum's clock without a move of the drive stands still at once, as only a refusal is tried again
    (``_read_put_in_place``), and a refusal that outlasts the clock's limit fails the clock instead of moving it by 0.
    Each read gets ``CLOCK_ANSWER_S``, so a clock that tries again without end fails this check, not the whole
    self-test at the step's time limit (review of #1169)."""

    import contextlib
    import io
    import tempfile
    import threading
    import time

    from drive.common import unreadable
    from serve_centrum import ScriptedClock

    def read(clock: ScriptedClock) -> object:
        answer: list[object] = []

        def call() -> None:
            try:
                answer.append(clock() - time.monotonic())
            except OSError as failure:
                answer.append(failure)

        reader = threading.Thread(target=call, daemon=True)
        reader.start()
        reader.join(CLOCK_ANSWER_S)
        return answer[0] if answer else f"no answer within {CLOCK_ANSWER_S} s"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        root = Path(scratch) / "run"
        File.CLOCK_MOVE.file(root).parent.mkdir(parents=True)
        # A refusal for good, without waiting the whole limit; no wake-up thread, which would read the same move.
        clock = ScriptedClock(root, retry_s=0.2, alarm=False)
        started = time.monotonic()
        moved = read(clock)
        if not (isinstance(moved, float) and abs(moved) < 1 and time.monotonic() - started < 1):
            errors.append(f"Centrum's clock without a move of the drive does not stand still at once: {moved!r}")

        move = File.CLOCK_MOVE.write(root, "5")
        with contextlib.redirect_stdout(io.StringIO()), unreadable(move):
            refused = read(clock)
        if not isinstance(refused, PermissionError):
            errors.append(f"Centrum's clock goes on past a refused read of a move that outlasts its limit: {refused!r}")


def _check_box_reads_while_put_in_place(errors: list[str]) -> None:
    """The scripted skrzynka reads an issue file once the drive has put it in place (``edit_issue``): its comments,
    a new comment and the issues with a label each wait while the system refuses to read it (#1087)."""

    import json
    import tempfile

    from serve_centrum import FileReportBox

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        issue = issue_file(root, 1)
        issue.parent.mkdir()
        body = {"number": 1, "title": "t", "body": "b", "labels": ["zgloszenie"], "state": "open", "comments": ["c"]}
        issue.write_text(json.dumps(body), encoding="utf-8")
        box = FileReportBox(root)

        def comments() -> object:
            found = box.comments(1, key="k")
            return [comment.body for comment in found] if isinstance(found, tuple) else found

        def labelled() -> object:
            found = box.labelled_issues("zgloszenie", include_closed=False, key="k")
            return [issue.number for issue in found] if isinstance(found, tuple) else found

        reads: dict[str, Callable[[], object]] = {
            "its comments": comments,
            "a new comment": lambda: type(box.comment(1, "nowy", key="k")).__name__,
            "the issues with a label": labelled,
        }
        expected: dict[str, object] = {"its comments": ["c"], "a new comment": "Commented", "the issues with a label": [1]}
        for what, read in reads.items():
            got = _read_while_put_in_place(issue, read)
            if got != expected[what]:
                errors.append(f"the scripted skrzynka gives up on {what} while the drive puts the issue in place: {got!r}")


def _protocol_names() -> tuple[frozenset[str], str]:
    """The path parts of every file of ``harness.py`` (those also named in the product only beside ``SHARED_PARTS``)
    and the prefix of a label's rejection, each taken from the module's own answers."""

    import harness

    root = Path("R")
    paths = [
        *(each.file(root) for kind in (harness.Pace, harness.Switch, harness.Log, harness.File) for each in kind),
        harness.issue_file(root, 1),
        harness.archive_listing(root),
        harness.archive_file(root, "t", "n"),
        harness.last_file_id(root),
        harness.efenix_files(root),
    ]
    parts = {part for path in paths for part in path.relative_to(root).parts}
    parts.update(harness.comment_address(1, 1).split("/")[:-1])
    rejection = harness.rejects(root, "L")
    parts.add(rejection.parent.name)
    return frozenset(parts - {"1.json", "t", "n"}), rejection.name.removesuffix("L")


def _protocol_spelled(source: str) -> list[str]:
    """Each string of ``source`` (a docstring or other bare string aside) with a path part of a file of ``harness.py``
    or a label's rejection, as ``<line>: <string>``: both sides of the protocol take its names from ``harness.py``, so
    a name changed there cannot leave one side on the old name. A part the product names too (``SHARED_PARTS``) counts
    only as an operand of ``/``.

    Its boundary, which review checks: a name put together at run time (``"brak-" + "sieci"``), a part glued to another
    in one string (``f"{x}-zapytania.jsonl"``), and a shared part that is no operand of ``/``
    (``Path("efenix", PERIOD)``, ``root / f"efenix/{PERIOD}"``)."""

    names, rejecting = _protocol_names()
    tree = ast.parse(source)
    bare = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    joined = {
        id(operand)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        for operand in (node.left, node.right)
    }
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in bare:
            continue
        parts = set(node.value.replace("#", "/").split("/"))
        spelled = parts & (names if id(node) in joined else names - SHARED_PARTS.keys())
        if spelled or any(part.startswith(rejecting) for part in parts):
            found.append((node.lineno, node.value))
    return [f"{line}: {text!r}" for line, text in sorted(found)]


def _check_protocol_spelled_once(errors: list[str]) -> None:
    """No script but ``harness.py`` spells a name of its files: the guard reports each sample of ``PROTOCOL_SAMPLES`` and
    nothing of ``PROTOCOL_LOOKALIKES``, and every script of the skill passes it."""

    for sample in PROTOCOL_SAMPLES:
        if not _protocol_spelled(sample):
            errors.append(f"the guard of the harness's names lets {sample!r} through")
    for sample in PROTOCOL_LOOKALIKES:
        if found := _protocol_spelled(sample):
            errors.append(f"the guard of the harness's names takes {sample!r} for a name of harness.py: {found}")
    for path in sorted(SCRIPTS_ROOT.rglob("*.py")):
        if path.name == "harness.py":
            continue
        for finding in _protocol_spelled(path.read_text(encoding="utf-8")):
            errors.append(
                f"{path.relative_to(SCRIPTS_ROOT).as_posix()}:{finding}; take the name from harness.py, which both the "
                "drive and serve_centrum.py read it from"
            )


def _check_served_side_reads_harness(errors: list[str]) -> None:
    """The scripted boundaries of ``serve_centrum.py`` take their files from ``harness.py``: each round trip below runs
    a boundary on one member and fails here when the boundary reads or writes it under another name, instead of as a
    check of the drive that passes because nothing opened (``Log.OPENED``) or nothing was refused.

    The round trips: ``ScriptedPlatform`` opens a file (logged in ``Log.OPENED``) and answers a picker (logged in
    ``Log.DIALOGS``, answered from ``File.PICKER_ANSWER``); ``ScriptedAutostart`` writes and removes
    ``File.AUTOSTART_SHORTCUT`` and is ``unsupported`` while ``Switch.NO_AUTOSTART`` is on; ``FileReportBox`` gives its outcome for a new issue while
    ``Switch.BOX_OFFLINE``, ``Switch.KEY_REFUSED`` or ``rejects`` is on, opens issue 1 with comment 1 and reads the
    comment back from ``issue_file``, and logs a
    question for closed issues in ``Log.REPORT_QUESTIONS``; it gives its outcome for a new Archiwum while
    ``Switch.ARCHIVE_REFUSED``, ``Switch.BOX_OFFLINE`` or ``Switch.KEY_REFUSED`` is on, uploads a file (kept at
    ``archive_file``, ``archive_listing`` and ``last_file_id``), uploads a second one under the next file id and
    removes the first; ``_scripted_github`` answers from ``File.TOOL_COMMIT``, ``File.MAIN_COMMIT``,
    ``File.RELEASE_TAG`` and ``File.RELEASES``, gives no answer while ``Switch.GITHUB_OFFLINE`` is on and logs each
    question for the list in ``Log.RELEASE_QUESTIONS``; ``_scripted_onedrive`` reads ``File.CLOUD_ONLY``;
    ``_register_failing_on_hook`` fails while ``Switch.REGISTER_FAULT`` is on. ``ScriptedClock`` (``File.CLOCK_MOVE``,
    ``File.CLOCK_DIED``) runs in ``_check_clock_alarm_failure``. What these round trips do not run is held by review
    only; the files the served side writes as it starts, ``File.EFENIX_ADDRESS`` with ``efenix_files``
    (``_efenix_window``) and ``File.SERVER`` (``record_bound_server``), and the one it reads as it starts,
    ``File.FIXTURE`` (``_serve``), are held by the run itself, loudly: the drive fails on a missing address of the
    Atrapa efenix, the run waits for the server record until its limit, and the served side does not start without
    the fixture."""

    import json
    import tempfile

    from harness import File, Log, Switch, archive_file, archive_listing, comment_position, issue_file, last_file_id, rejects
    from rozliczenia.centrum.report_box import Archive, Asset, Commented, Refused, Rejected, Removed, Sent, Unreachable
    from rozliczenia.centrum.tool_freshness import GitHubReleases
    from serve_centrum import (
        FileReportBox,
        ScriptedAutostart,
        ScriptedPlatform,
        _register_failing_on_hook,
        _scripted_github,
        _scripted_onedrive,
    )

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)

        def records(log: Log) -> list[object]:
            path = log.file(root)
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

        platform = ScriptedPlatform(root)
        platform.open_path(root / "plik.xlsx")
        File.PICKER_ANSWER.write(root, str(root / "wybrany"))
        chosen = platform.choose_folder("Okno")
        if records(Log.OPENED) != [{"path": str(root / "plik.xlsx")}]:
            errors.append(f"opening a file is not logged in {Log.OPENED.value}: {records(Log.OPENED)}")
        if records(Log.DIALOGS) != [{"title": "Okno"}] or chosen != root / "wybrany":
            errors.append(f"a picker does not log in {Log.DIALOGS.value} or answer from {File.PICKER_ANSWER.value}")

        autostart = ScriptedAutostart(root)
        autostart.enable()
        enabled = (autostart.state(), File.AUTOSTART_SHORTCUT.file(root).exists())
        autostart.disable()
        disabled = (autostart.state(), File.AUTOSTART_SHORTCUT.file(root).exists())
        Switch.NO_AUTOSTART.on(root)
        unsupported = autostart.state()
        Switch.NO_AUTOSTART.file(root).unlink()
        if (enabled, disabled, unsupported) != (("on", True), ("off", False), "unsupported"):
            errors.append(
                f"the Autostart does not write {File.AUTOSTART_SHORTCUT.value} or does not read {Switch.NO_AUTOSTART.value}: "
                f"{enabled}, {disabled}, {unsupported}"
            )

        box = FileReportBox(root)
        scripted = [
            (Switch.BOX_OFFLINE.file(root), Unreachable()),
            (Switch.KEY_REFUSED.file(root), Refused()),
            (rejects(root, "zgloszenie"), Rejected()),
        ]
        for path, expected in scripted:
            path.parent.mkdir(exist_ok=True)
            path.touch()
            got = box.open_issue("zgloszenie", "t", "b", key="k")
            path.unlink()
            if got != expected:
                errors.append(f"the scripted skrzynka gives {got!r} instead of {expected!r} while {path.name} exists")
        sent = box.open_issue("zgloszenie", "t", "b", key="k")
        commented = box.comment(1, "c", key="k")
        if sent != Sent(1) or not (isinstance(commented, Commented) and comment_position(commented.url) == (1, 1)):
            errors.append(f"the scripted skrzynka does not open issue 1 with comment 1: {sent!r}, {commented!r}")
        # The answer to the comment comes before any write, so the comment is read back from ``issue_file``.
        kept = box.comments(1, key="k")
        if not isinstance(kept, tuple) or [(comment_position(each.url), each.body) for each in kept] != [((1, 1), "c")]:
            errors.append(f"the scripted skrzynka does not keep comment 1 in {issue_file(root, 1).name}: {kept!r}")
        box.labelled_issues("zgloszenie", include_closed=True, key="k")
        if records(Log.REPORT_QUESTIONS) != [{"label": "zgloszenie"}]:
            errors.append(f"a question for closed issues is not logged in {Log.REPORT_QUESTIONS.value}")
        refused = Switch.ARCHIVE_REFUSED.on(root)
        got_archive = box.open_archive("logi-x", "t", "d", key="k")
        refused.unlink()
        if got_archive != Refused():
            errors.append(f"the scripted Archiwa give {got_archive!r} while {Switch.ARCHIVE_REFUSED.value} exists")
        for switch, expected_archive in ((Switch.BOX_OFFLINE, Unreachable()), (Switch.KEY_REFUSED, Refused())):
            switched = switch.on(root)
            got_archive = box.open_archive("logi-x", "t", "d", key="k")
            switched.unlink()
            if got_archive != expected_archive:
                errors.append(
                    f"the scripted Archiwa give {got_archive!r} instead of {expected_archive!r} while {switch.value} exists"
                )
        opened = box.open_archive("logi-x", "t", "d", key="k")
        uploaded = box.upload(opened.id, "logi.gz", "l", b"x", key="k") if isinstance(opened, Archive) else opened
        if not (
            isinstance(uploaded, Asset)
            and archive_file(root, "logi-x", "logi.gz").read_bytes() == b"x"
            and archive_listing(root).exists()
            and last_file_id(root).read_text(encoding="utf-8") == str(uploaded.id)
        ):
            errors.append(f"the scripted Archiwa do not keep a file where harness.py puts it: {uploaded!r}")
        # The second upload reads back the Archiwa written by the first: the file's bytes and the last file id.
        second = box.upload(opened.id, "drugi.gz", "l", b"y", key="k") if isinstance(opened, Archive) else opened
        removed = box.remove(uploaded.id, key="k") if isinstance(uploaded, Asset) else uploaded
        if not (
            isinstance(uploaded, Asset)
            and isinstance(second, Asset)
            and second.id == uploaded.id + 1
            and isinstance(removed, Removed)
            and not archive_file(root, "logi-x", "logi.gz").exists()
            and archive_file(root, "logi-x", "drugi.gz").read_bytes() == b"y"
        ):
            errors.append(f"the scripted Archiwa do not read back what they kept: {second!r}, {removed!r}")

        github = _scripted_github(root, root / "klon")
        File.TOOL_COMMIT.write(root, "a" * 40)
        File.MAIN_COMMIT.write(root, "b" * 40)
        File.RELEASE_TAG.write(root, "v1.0.0")
        published = {
            "tag_name": "v1.0.0",
            "draft": False,
            "prerelease": False,
            "body": "n",
            "published_at": "2026-11-01T10:00:00+00:00",
        }
        File.RELEASES.write(root, json.dumps([published]))
        answers = (github.local(), github.release(), tuple(each.release.tag for each in github.published() or ()))
        offline_switch = Switch.GITHUB_OFFLINE.on(root)
        offline = (github.release(), github.published())
        offline_switch.unlink()
        if answers != ("a" * 40, GitHubReleases("b" * 40, "v1.0.0"), ("v1.0.0",)) or offline != (None, None):
            errors.append(f"the scripted GitHub does not answer from the files of harness.py: {answers}, {offline}")
        if len(records(Log.RELEASE_QUESTIONS)) != 2:
            errors.append(f"each question for the published Wydania is not logged in {Log.RELEASE_QUESTIONS.value}")

        register = root / "Rejestr.xlsx"
        register.write_bytes(b"r")
        File.CLOUD_ONLY.write(root, str(register) + "\n")
        onedrive = _scripted_onedrive(root).read_attributes
        if onedrive is None or onedrive(register) == onedrive(root / "inny.xlsx"):
            errors.append(f"the scripted OneDrive does not read {File.CLOUD_ONLY.value}")
        source = _register_failing_on_hook(root, register)
        Switch.REGISTER_FAULT.on(root)
        try:
            source(register)
        except RuntimeError:
            pass
        else:
            errors.append(f"reading the Rejestr zleceń does not fail while {Switch.REGISTER_FAULT.value} exists")


def _check_clock_alarm_failure(errors: list[str]) -> None:
    """Once the wake-up thread of Centrum's clock dies (here on a move it cannot read), the drive fails on it at the
    next ``advance_clock`` instead of waiting for a wake-up that never fires (#1124). A wait that times out names the
    dead clock in ``drive()`` of ``drive_centrum.py``, which ``tests/test_podstawa_w_czesciach.py`` checks."""

    import contextlib
    import io
    import json
    import tempfile
    import threading
    import time

    from drive.common import DriveFailure, Run, advance_clock
    from serve_centrum import ScriptedClock

    hook = threading.excepthook
    threading.excepthook = lambda failure: None  # the dying thread's traceback is the file below
    try:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "run"
            File.CLOCK_MOVE.file(root).parent.mkdir(parents=True)
            File.FIXTURE.write(root, json.dumps({}))
            File.CLOCK_MOVE.write(root, "jedna minuta")
            run = Run(root, "http://127.0.0.1:1/", Path(scratch) / "evidence")
            ScriptedClock(root)
            died = File.CLOCK_DIED.file(root)
            deadline = time.monotonic() + 5
            while not died.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if "could not convert" not in (died.read_text(encoding="utf-8") if died.exists() else ""):
                errors.append(f"the wake-up thread of Centrum's clock dies without leaving why in {File.CLOCK_DIED.value}")
                return
            steps: dict[str, Callable[[], None]] = {
                "advance_clock": lambda: advance_clock(run, 1, "the self-test moves a dead clock"),
            }
            failures: list[str] = []
            with contextlib.redirect_stdout(io.StringIO()):
                for name, step in steps.items():
                    try:
                        step()
                    except (DriveFailure, ValueError, OSError) as failure:  # a step that reads the dead clock fails otherwise
                        if not (isinstance(failure, DriveFailure) and "clock died" in str(failure)):
                            failures.append(f"{name}: {failure!r}")
                    else:
                        failures.append(f"{name} goes on")
            if failures:
                errors.append(f"the drive does not fail on the dead wake-up thread of Centrum's clock: {failures}")
    finally:
        threading.excepthook = hook


def _check_log_entries(errors: list[str]) -> None:
    """``log_entries`` reads a fact whose value has a space, which the Centrum log writes in quotes (``log.py``)."""

    import tempfile

    from drive.common import LogEntry, log_entries

    line = 'skrzynka-czeka etykieta=zgloszenie przyczyna="brak sieci" okres=06_12_10_2026'
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "centrum-rozliczen.log"
        path.write_text(f"2026-10-19T08:00:00+02:00 {line}\n", encoding="utf-8")
        entries = log_entries(path)
    facts = {"etykieta": "zgloszenie", "przyczyna": "brak sieci", "okres": "06_12_10_2026"}
    if entries != [LogEntry("skrzynka-czeka", facts, line)]:
        errors.append(f"log_entries splits an entry of the Centrum log other than log.py writes it: {entries}")


def _check_drop_report_key(errors: list[str]) -> None:
    """``drop_report_key`` empties a key the step wrote, and refuses one it never wrote unless ``missing_ok``: a file
    of blanks is no key to the server (``read_report_key``)."""

    import tempfile

    from drive.common import DriveFailure, drop_report_key

    with tempfile.TemporaryDirectory() as scratch:
        key_file = Path(scratch) / "zgloszenia-klucz.txt"
        key_file.write_text("  \n", encoding="utf-8")
        try:
            drop_report_key(key_file)
        except DriveFailure:
            pass
        else:
            errors.append("drop_report_key takes a file of blanks, which the server reads as no key, for a written key")
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
    _check_retry_while_open(errors)
    _check_drop_report_key(errors)
    _check_result_of_start(errors)
    _check_read_while_put_in_place(errors)
    _check_box_reads_while_put_in_place(errors)
    _check_served_side_reads_harness(errors)
    _check_protocol_spelled_once(errors)
    _check_clock_moved_whole(errors)
    _check_clock_without_move(errors)
    _check_clock_alarm_failure(errors)
    _check_log_entries(errors)
    _check_performance_gate(errors)
    _check_guard_documented(errors)
    _check_drive_removals(errors)
    _check_drive_reads(errors)
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
