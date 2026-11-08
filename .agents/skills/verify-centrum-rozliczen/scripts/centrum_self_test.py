"""Check the verify-centrum-rozliczen skill package and the hygiene of one run's evidence.

Checks the frontmatter, the feature-map headings, that every helper named in
SKILL.md exists and answers ``--help``, the gate of ``wydajnosc`` on made-up
numbers (no browser), that the retrying helpers of ``drive/common.py`` outlast a
file the server holds open, retry nothing else and nothing longer, and take the key away only after a step wrote it,
that the result of a started Uruchomienie is never the one before it and the Centrum log is read as ``log.py`` writes it,
that a file the server puts in place is read once it is there and only a vanished queue file is left out,
that Centrum's clock reads each move of the drive whole, also while the system refuses a read for a moment,
that the drive deletes, moves and replaces in none of the forms of ``_removals`` outside those helpers, that
evidence text is strict UTF-8 and screenshots are PNG files, and that no workbook content (the fixture's row marker) reached the
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
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.fixtures.scenariusz_centrum import ROW_MARKER

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
# Deleting, moving or replacing a file or folder fails on Windows while another process holds it open (WinError 32,
# #921), so the drive does it only through the retrying helpers of ``drive/common.py`` (``DRIVE_HELPERS``). The forms
# the guard ``_removals`` catches and its boundary are the tables of its docstring and of features/README.md.
# Only deletions and moves have attributes of these names (pathlib, ``os``, ``shutil``): form 1 takes them on anything.
ONLY_REMOVING = frozenset({"unlink", "rename", "rmdir", "rmtree", "removedirs", "renames", "move_into"})
# Deletions and moves of a module whose names other objects share (``list.remove``): form 2, only on the module.
SHARED_REMOVING = {"os": frozenset({"remove", "replace"}), "shutil": frozenset({"move"})}
# Path methods whose names other objects share (``str.replace``, ``page.mouse.move``): forms 4 and 5.
PATH_SHARED = frozenset({"replace", "move"})
PATHLIB_CLASSES = frozenset({"Path", "PosixPath", "WindowsPath"})
DRIVE_HELPERS = frozenset({"remove", "remove_tree", "remove_empty_folder", "move", "replace_file"})
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
    "import os\nos.remove(p)": "os.remove (form 2)",
    "import os\nos.replace(p, q)": "os.replace (form 2)",
    "import shutil\nshutil.move(p, q)": "shutil.move (form 2)",
    "import os as system\nsystem.remove(p)": "system.remove (form 2)",
    "import shutil as files\nfiles.move(p, q)": "files.move (form 2)",
    "import os.path\nos.remove(p)": "os.remove (form 2)",
    "import functools\nimport os\nfunctools.partial(os.replace, p, q)": "os.replace (form 2)",
    "import os as fs\nimport shutil as fs\nfs.move(p, q)": "fs.move (form 2)",
    "from os import remove": "from os import remove (form 3)",
    "from os import replace as swap": "from os import replace (form 3)",
    "from os import getcwd, unlink": "from os import unlink (form 3)",
    "from shutil import move as shift": "from shutil import move (form 3)",
    "from shutil import rmtree": "from shutil import rmtree (form 3)",
    "from os import *": "from os import * (form 3)",
    "from shutil import *": "from shutil import * (form 3)",
    "from pathlib import *": "from pathlib import * (form 3)",
    "from pathlib import Path\nPath.replace(p, q)": "Path.replace (form 4)",
    "from pathlib import Path\nPath.move(p, q)": "Path.move (form 4)",
    "from pathlib import Path as P\nP.replace(p, q)": "P.replace (form 4)",
    "import pathlib\npathlib.Path.move(p, q)": "pathlib.Path.move (form 4)",
    "import pathlib as pl\npl.WindowsPath.replace(p, q)": "pl.WindowsPath.replace (form 4)",
    "from pathlib import Path\nswap = Path.replace": "Path.replace (form 4)",
    "p.replace(q)": ".replace(target) (form 5)",
    "p.replace(target=q)": ".replace(target) (form 5)",
    "p.move(q)": ".move(target) (form 5)",
    "p.move(target=q)": ".move(target) (form 5)",
    "from pathlib import Path\nPath(p).replace(q)": ".replace(target) (form 5)",
    "getattr(p, 'unlink')()": "getattr(…, 'unlink') (form 6)",
    "import os\ngetattr(os, 'remove')(p)": "getattr(…, 'remove') (form 6)",
    "getattr(p, 'replace')(q)": "getattr(…, 'replace') (form 6)",
    "import shutil\ngetattr(shutil, 'move', None)": "getattr(…, 'move') (form 6)",
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

    It knows a module or a pathlib class only by a name an ``import`` or ``from … import`` binds, never by an
    assignment, so it walks the tree twice with no fixed point to reach; a name two imports bind to two modules keeps
    both. The guard catches exactly these forms:

    | Form | The guard catches | Example |
    |---|---|---|
    | 1 | an attribute `unlink`, `rename`, `rmdir`, `rmtree`, `removedirs`, `renames` or `move_into` on anything, called or not | `p.unlink(missing_ok=True)`, `p.rename(target=q)`, `os.renames(p, q)`, `shutil.rmtree(p)`, `drop = Path.unlink`, `fs = os; fs.unlink(p)` |
    | 2 | `remove` or `replace` on a name that `import os [as x]` binds, `move` on a name that `import shutil [as x]` binds, called or not | `os.remove(p)`, `import os as system; system.replace(p, q)`, `shutil.move(p, q)`, `partial(os.remove, p)` |
    | 3 | `from os import <name of form 1 or 2> [as x]`, the same from `shutil`, and `from os import *`, `from shutil import *`, `from pathlib import *` | `from os import replace as swap`, `from shutil import rmtree` |
    | 4 | `replace` or `move` on `Path`, `PosixPath` or `WindowsPath` that `from pathlib import <class> [as x]` binds or that is reached through a name that `import pathlib [as x]` binds, called or not | `Path.replace(p, q)`, `P.move(p, q)`, `pathlib.WindowsPath.replace(p, q)`, `swap = Path.replace` |
    | 5 | a call `x.replace(…)` or `x.move(…)` with one positional argument and no named one, or with only `target=`, where `x` is neither a name that an `import` binds nor a class of form 4 | `p.replace(q)`, `p.move(target=q)`, `Path(p).replace(q)` |
    | 6 | `getattr(x, "<name>", …)` with a constant name of form 1, 2 or 4 | `getattr(p, "unlink")()`, `getattr(os, "remove")(p)` |

    Its boundary, which review checks:

    | Boundary | Passes the guard |
    |---|---|
    | a module or pathlib class through a name that no import binds (forms 1 and 5 still catch on it) | `fs = os; fs.remove(p)`, `s: ModuleType = os; s.replace(p, q)`, `Q = Path; Q.replace(p, q)`, `self.files = shutil` |
    | `replace` or `move` of an object kept or passed instead of called (form 5 takes only a call) | `swap = p.replace; swap(q)`, `retry(p.move, q)` |
    | a call of form 5 with unpacked arguments | `p.replace(*args)`, `p.move(**named)` |
    | a call of form 5 on a name that an `import` in the file also binds | `import time` and elsewhere `time = p; time.replace(q)` |
    | a pathlib class from an expression | `type(p).replace(p, q)`, `p.__class__.move(p, q)` |
    | another module | `posix`, `nt`, `_winapi`, `ctypes` |
    | a name computed at run time, or a name in a string outside `getattr` | `getattr(p, name)`, `operator.methodcaller("unlink")`, `vars(os)["remove"]`, `sys.modules["os"]`, `importlib`, `__import__`, `eval` |
    | another process | `subprocess` with `rm`, `del`, `Remove-Item` or `move`, `os.system` |
    | no deletion or move | a copy onto a file the server reads (`shutil.copy2`, `copyfile`, `copytree(…, dirs_exist_ok=True)`), a write (`open(p, "w")`, `write_bytes`, `workbook.save`), `tempfile` cleanup |
    | code outside `drive/*.py` | `drive_centrum.py`, `create_centrum_fixture.py`, `serve_centrum.py` |

    A false alarm is loud and names the helpers: form 1 on an object that is no file (`frame.rename(columns=…)`), form 5
    on any object with a one-argument `replace` or `move` (`moment.replace(2026)`), form 6 on any object."""

    tree = ast.parse(source)
    skipped = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helpers
        for inner in ast.walk(node)
    }
    modules: dict[str, set[str]] = {}  # each name an ``import`` binds, with every module it binds it to
    pathlib_classes: set[str] = set()  # each name ``from pathlib import <class> [as x]`` binds
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]  # ``import os.path`` binds ``os``; ``import os.path as p`` binds os.path
                modules.setdefault(alias.asname or root, set()).add(alias.name if alias.asname else root)
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib" and not node.level:
            pathlib_classes.update(alias.asname or alias.name for alias in node.names if alias.name in PATHLIB_CLASSES)

    def pathlib_class(owner: ast.expr) -> bool:
        if isinstance(owner, ast.Name):
            return owner.id in pathlib_classes
        return (
            isinstance(owner, ast.Attribute)
            and owner.attr in PATHLIB_CLASSES
            and isinstance(owner.value, ast.Name)
            and "pathlib" in modules.get(owner.value.id, set())
        )

    def path_signature(call: ast.Call) -> bool:
        one_positional = len(call.args) == 1 and not isinstance(call.args[0], ast.Starred) and not call.keywords
        return one_positional or (not call.args and [keyword.arg for keyword in call.keywords] == ["target"])

    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.ImportFrom) and not node.level and node.module in ("os", "shutil", "pathlib"):
            imported = ONLY_REMOVING | SHARED_REMOVING[node.module] if node.module != "pathlib" else frozenset()
            for alias in node.names:
                if alias.name == "*" or alias.name in imported:
                    found.add((node.lineno, f"from {node.module} import {alias.name} (form 3)"))
        elif isinstance(node, ast.Attribute):
            owner = node.value
            bound = modules.get(owner.id, set()) if isinstance(owner, ast.Name) else set()
            if any(node.attr in SHARED_REMOVING.get(module, ()) for module in bound):
                found.add((node.lineno, f"{ast.unparse(owner)}.{node.attr} (form 2)"))
            elif node.attr in PATH_SHARED and pathlib_class(owner):
                found.add((node.lineno, f"{ast.unparse(owner)}.{node.attr} (form 4)"))
            elif node.attr in ONLY_REMOVING:
                found.add((node.lineno, f".{node.attr} (form 1)"))
        elif isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr in PATH_SHARED
                and path_signature(node)
                and not (isinstance(function.value, ast.Name) and function.value.id in modules)
                and not pathlib_class(function.value)
            ):
                found.add((node.lineno, f".{function.attr}(target) (form 5)"))
            elif (
                isinstance(function, ast.Name)
                and function.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in ONLY_REMOVING | PATH_SHARED | SHARED_REMOVING["os"] | SHARED_REMOVING["shutil"]
            ):
                found.add((node.lineno, f"getattr(…, {node.args[1].value!r}) (form 6)"))
    return [f"{line}: {form}" for line, form in sorted(found)]


def _helpers_of(name: str) -> frozenset[str]:
    """The functions of ``drive/<name>`` that may delete and move: only the retrying helpers of ``common.py``."""

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

    from drive import common

    refusals = 2

    def held_for_a_moment() -> None:
        nonlocal refusals
        if refusals:
            refusals -= 1
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    try:
        common.while_open(held_for_a_moment)
    except PermissionError:
        errors.append("drive/common.py gives up on a file the server holds open for a moment (#921)")
    attempts = 0

    def missing_at_first() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FileNotFoundError(2, "No such file or directory")

    try:
        common.while_open(missing_at_first)
    except FileNotFoundError:
        pass
    else:
        errors.append("drive/common.py retries an error other than a file the server holds open, so it hides it")

    def held_for_good() -> None:
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    try:
        common.while_open(held_for_good, limit_s=0.2)  # a refusal for good, without waiting the whole limit
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
                (root / "fixture.json").write_text("{}", encoding="utf-8")
                run = Run(root, f"http://127.0.0.1:{server.server_port}/", Path(scratch) / "evidence")
                with contextlib.redirect_stdout(io.StringIO()):
                    result: object = result_of_start(run, "powtorka", lambda: since_click.append(0))
        except DriveFailure as failure:
            result = failure
        finally:
            server.shutdown()
            server.server_close()
        if result != {"stop_kind": "repeated"}:
            errors.append(
                f"result_of_start with the new Uruchomienie shown after {late} reads took another one for it: {result}"
            )


def _check_read_while_put_in_place(errors: list[str]) -> None:
    """``run_logs`` (through ``read_json``) waits while the server puts a file of Logi in place, which refuses a read
    for a moment on Windows (#1087), and ``queued_posts`` leaves out only a queue file that is gone, never one it
    cannot read."""

    import contextlib
    import io
    import json
    import tempfile
    import threading
    import time

    from drive.common import Run, queued_posts, run_logs, unreadable

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "run"
        root.mkdir()
        settings = root / "config" / "centrum-ustawienia.yaml"
        (root / "fixture.json").write_text(json.dumps({"settings": str(settings)}), encoding="utf-8")
        run = Run(root, "http://127.0.0.1:1/", Path(scratch) / "evidence")
        run.run_logs_dir.mkdir(parents=True)
        logs = run.run_logs_dir / "20261019T060000Z-preparation-aaaaaaaa.json"
        logs.write_text(json.dumps({"run_id": "aaaaaaaa"}), encoding="utf-8")
        refusing = threading.Event()

        def put_in_place() -> None:
            with unreadable(logs):
                refusing.set()
                time.sleep(0.3)

        with contextlib.redirect_stdout(io.StringIO()):
            server = threading.Thread(target=put_in_place)
            server.start()
            refusing.wait()
            try:
                read: object = run_logs(run)
            except PermissionError as failure:
                read = failure
            server.join()
        if read != {logs.name: {"run_id": "aaaaaaaa"}}:
            errors.append(f"run_logs gives up on a file of Logi the server is putting in place: {read!r}")

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
        (root / "fixture.json").write_text(json.dumps({"settings": str(root / "config" / "s.yaml")}), encoding="utf-8")
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
            with unreadable(root / "zegar" / "przesuniecie-min.txt"):
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
    _check_retry_while_open(errors)
    _check_drop_report_key(errors)
    _check_result_of_start(errors)
    _check_read_while_put_in_place(errors)
    _check_clock_moved_whole(errors)
    _check_log_entries(errors)
    _check_performance_gate(errors)
    _check_machine_lock(errors)
    _check_guard_documented(errors)
    _check_drive_removals(errors)
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
