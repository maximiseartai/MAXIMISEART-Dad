"""Prints the section ``## Sub-features`` of a feature file from the feature's drive module.

Each sub-feature is a ``run.step(feature, "<id>")`` of ``drive/<feature>.py``, in source order, and its line joins the
messages of the ``run.check`` calls after it, which the drive prints as ``ok:`` under ``STEP <feature> | <id>`` in
``drive.txt``. A name in a check's f-string that the module binds to a string at its top level is printed as that
string, any other placeholder as its source in braces. A step whose name is not a string literal fails, because the map
would then guess it.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys

from drive import FEATURES, feature

DRIVE = Path(__file__).resolve().parent / "drive"


def _constants(tree: ast.Module) -> dict[str, str]:
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _text(node: ast.expr, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(part, constants) for part in node.values)
    if isinstance(node, ast.FormattedValue) and isinstance(node.value, ast.Name) and node.value.id in constants:
        return constants[node.value.id]
    if isinstance(node, ast.FormattedValue):
        return "{" + ast.unparse(node.value) + "}"
    return "{" + ast.unparse(node) + "}"


def _run_calls(tree: ast.Module) -> list[ast.Call]:
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "run"
        and node.func.attr in {"step", "check"}
    ]
    return sorted(calls, key=lambda call: (call.lineno, call.col_offset))


def section(name: str) -> str:
    module = DRIVE / f"{feature(name).module.removeprefix('drive.')}.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    constants = _constants(tree)
    steps: list[tuple[str, list[str]]] = []
    for call in _run_calls(tree):
        assert isinstance(call.func, ast.Attribute)
        if call.func.attr == "step":
            step = call.args[1] if len(call.args) == 2 else None
            if not (isinstance(step, ast.Constant) and isinstance(step.value, str)):
                raise SystemExit(f"{module.name}:{call.lineno}: run.step names its sub-feature without a string literal")
            steps.append((step.value, []))
        elif steps and len(call.args) == 2:
            steps[-1][1].append(_text(call.args[1], constants))
    if not steps:
        raise SystemExit(f"{module.name} has no run.step")
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
    # Bytes, so the Windows console (cp1252) neither refuses Polish letters nor turns line ends into CRLF.
    sys.stdout.buffer.write(section(parser.parse_args().feature).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
