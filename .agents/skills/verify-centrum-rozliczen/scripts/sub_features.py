"""Prints the section ``## Sub-features`` of a feature file from the feature's drive module.

Each sub-feature is a ``run.step(feature, "<id>")`` in ``drive(run, page)`` of ``drive/<feature>.py``, in source
order, and its line joins the messages of the ``run.check`` calls after it, which the drive prints as ``ok:`` under
``STEP <feature> | <id>`` in ``drive.txt``. A message is a string literal, a module constant (a name the module binds
only once, at its top level, to a string) or an f-string. A placeholder of the f-string that is such a constant, with
no conversion and no format spec, prints its value; every other placeholder prints as ``…``, whatever its expression,
conversion or format spec, because the value is known only when the drive runs. The literal text prints as it is,
``{{`` as ``{``. The rule has one owner, ``tools/lib/komunikat_mapy.py``, shared with the map of ``verify-rozliczenia``.

The command reads only that form and fails, naming the file, the line and what to do, on anything else: a ``drive``
whose first parameter is not ``run``, a step or a check without exactly two positional arguments or with a starred
one, a step name that is no string literal, a message of another kind,
a check before the first step, and any attribute ``.step`` or ``.check`` in the module, on whatever object, that
is not the called function of such a call on ``run`` in the body of ``drive`` itself (outside any function, lambda or
class in it). It does not see a check reached without such an attribute, as ``getattr(run, "check")``. Checks in the
shared helpers of ``drive/common.py`` print under the step that calls them and are not part of the section: the
section maps this module's own steps and checks.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from komunikat_mapy import constants, message

from drive import FEATURES, feature

DRIVE = Path(__file__).resolve().parent / "drive"
CALLS = frozenset({"step", "check"})


class Unreadable(Exception):
    """A form of the drive module the command does not read; ``str`` is the file, the line and what to do."""


def _refuse(module: str, node: ast.AST, what: str) -> Unreadable:
    return Unreadable(f"{module}:{getattr(node, 'lineno', 1)}: {what}")


def _message(node: ast.expr, known: dict[str, str], module: str) -> str:
    printed = message(node, known)
    if printed is None:
        raise _refuse(
            module,
            node,
            f"run.check has the message `{ast.unparse(node)}`; give it as a string literal, a module constant or an "
            "f-string, so the map can print it",
        )
    return printed


def _two_positional(call: ast.Call, module: str) -> tuple[ast.expr, ast.expr]:
    assert isinstance(call.func, ast.Attribute)
    if call.keywords or len(call.args) != 2 or any(isinstance(arg, ast.Starred) for arg in call.args):
        raise _refuse(
            module,
            call,
            f"run.{call.func.attr} takes exactly two positional arguments here, `{ast.unparse(call)}` does not; "
            f"write it as run.{call.func.attr}(<{'feature' if call.func.attr == 'step' else 'condition'}>, "
            f"<{'name' if call.func.attr == 'step' else 'message'}>)",
        )
    return call.args[0], call.args[1]


def _drive(tree: ast.Module, module: str) -> ast.FunctionDef:
    drives = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "drive"]
    if len(drives) != 1:
        raise _refuse(module, tree, "the module has no single top-level `def drive(run, page)`; write one")
    if [arg.arg for arg in drives[0].args.args[:1]] != ["run"]:
        raise _refuse(module, drives[0], "drive() does not take `run` as its first parameter; name it run")
    return drives[0]


def _own_calls(function: ast.FunctionDef) -> list[ast.Call]:
    """Calls ``run.step``/``run.check`` in ``function`` itself, not in a function, lambda or class inside it."""

    calls: list[ast.Call] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call) and _is_run_call(node.func):
            calls.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(calls, key=lambda call: (call.lineno, call.col_offset))


def _is_run_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in CALLS
        and isinstance(node.value, ast.Name)
        and node.value.id == "run"
    )


def _refuse_other_forms(tree: ast.Module, own: list[ast.Call], module: str) -> None:
    """Fails on every attribute ``.step``/``.check`` in the module, on whatever object, but the called function of
    ``own``: the command does not tell which object is a ``Run``, so it reads none but ``run`` in ``drive``."""

    read = {id(call.func) for call in own}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in CALLS and id(node) not in read:
            raise _refuse(
                module,
                node,
                f"`{ast.unparse(node)}` is not run.{node.attr} called in the body of drive() itself; call "
                f"run.{node.attr}(…) there, so the map sees what the drive prints",
            )


def sub_features(source: str, module: str) -> list[tuple[str, list[str]]]:
    """Each sub-feature of a drive module's ``source`` with the messages of its checks; ``module`` names it in a
    refusal (``Unreadable``)."""

    tree = ast.parse(source)
    known = constants(tree)
    drive = _drive(tree, module)
    own = _own_calls(drive)
    _refuse_other_forms(tree, own, module)
    steps: list[tuple[str, list[str]]] = []
    for call in own:
        assert isinstance(call.func, ast.Attribute)
        _, second = _two_positional(call, module)
        if call.func.attr == "step":
            if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
                raise _refuse(module, call, "run.step names its sub-feature without a string literal; write the name as one")
            steps.append((second.value, []))
        elif not steps:
            raise _refuse(module, call, "run.check comes before the first run.step; move it after the step it checks")
        else:
            steps[-1][1].append(_message(second, known, module))
    if not steps:
        raise _refuse(module, drive, "drive() has no run.step; name each sub-feature with one")
    return steps


def section(name: str) -> str:
    module = DRIVE / f"{feature(name).module.removeprefix('drive.')}.py"
    steps = sub_features(module.read_text(encoding="utf-8"), module.name)
    command = f"`scripts/sub_features.py --feature {name}`"
    lines = [
        "## Sub-features",
        "",
        f"Printed by {command} from the drive's steps and checks; refresh the section with it.",
        "",
        *(f"- `{step}`: {'; '.join(checks)}." if checks else f"- `{step}`." for step, checks in steps),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature", required=True, choices=[each.name for each in FEATURES])
    try:
        printed = section(parser.parse_args().feature)
    except Unreadable as refusal:
        raise SystemExit(str(refusal)) from None
    # Bytes, so the Windows console (cp1252) neither refuses Polish letters nor turns line ends into CRLF.
    sys.stdout.buffer.write(printed.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
