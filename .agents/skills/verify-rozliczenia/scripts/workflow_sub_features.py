"""Prints the section ``## Sub-features`` of a feature file from the workflow of its process.

A feature is a process ``WorkflowProcess("<feature>", <workflow>, …)`` of ``run_verification.py``, and its variants are
the keys of ``WORKFLOW_VARIANTS`` whose ``WorkflowVariant(<process>)`` has no other argument. Each line is a step of the
workflow, in source order: a statement ``_run_step("<step>", [str(HELPER_DIRECTORY / "<script>"), …], …,
expected_exit=<n>)`` or ``_run_process_step("<step>", ["<command>", …], …, expected_exit=<n>)`` of the workflow
function's own body, which runs that helper script or ``tools/uruchom_proces.py <command>`` and expects that exit code.
Under a helper's step stand the messages of the ``errors.append(<message>)`` calls its ``main`` reaches, in source
order, through the functions of the script and of ``wynik_uruchomienia.py`` it hands ``errors`` to, and the line each
``finish(errors, <line>)`` prints when none was appended. A message prints by the rule of
``tools/lib/komunikat_mapy.py``.

The command reads only that form and fails, naming the file, the line and what to do, on anything else: a process
without a string literal name, or a workflow that is no function of the module; a variant with fields; a step that is
no statement of the workflow's own body (in an ``if``, a loop, a nested function, or kept as a value); a call in the
workflow of a function of the module that runs steps; a step without a string literal name, a list literal of
arguments starting with the script, or an ``expected_exit`` integer literal; and in a helper, ``errors`` changed other
than by ``errors.append(<message>)`` with one argument (an item set or deleted included), bound other than
``errors = []`` at the top level of ``main``, handed to a function it does not read (a function of another module
under a name of ``wynik_uruchomienia.py`` included) or to a parameter not named ``errors``, used in a nested function
or lambda, a message of another kind, and a function using ``errors`` that ``main`` does not reach. It does not see a check appended through another
name bound to the list (``found = errors``) nor a step run without ``_run_step`` or ``_run_process_step``. The steps
``cleanup`` and ``self-test`` that ``_verify`` runs after every workflow, and a ``raise`` in a helper, are not part of
the section.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from komunikat_mapy import constants, message

SCRIPTS = Path(__file__).resolve().parent
WORKFLOWS = "run_verification.py"
SHARED = "wynik_uruchomienia.py"
STEPS = {"_run_step": "helper", "_run_process_step": "process"}
NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class Unreadable(Exception):
    """A form the command does not read; ``str`` is the file, the line and what to do."""


def _refuse(module: str, node: ast.AST, what: str) -> Unreadable:
    return Unreadable(f"{module}:{getattr(node, 'lineno', 1)}: {what}")


@dataclass
class Step:
    name: str
    runs: str
    exit_code: int
    checks: list[str] = field(default_factory=list)
    prints: list[str] = field(default_factory=list)


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _own(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
    """Nodes of ``nodes`` in source order, outside any function, lambda or class inside them."""

    found: list[ast.AST] = []
    stack: list[ast.AST] = list(nodes)
    while stack:
        node = stack.pop()
        found.append(node)
        if not isinstance(node, NESTED):
            stack.extend(ast.iter_child_nodes(node))
    yield from sorted(found, key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))


def _names(node: ast.AST) -> set[str]:
    return {each.id for each in ast.walk(node) if isinstance(each, ast.Name)}


def _process(tree: ast.Module, feature: str) -> tuple[str, ast.FunctionDef, list[str]]:
    processes: dict[str, tuple[str, ast.expr]] = {}
    variants: list[tuple[str, ast.expr, ast.Call]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "WorkflowProcess":
            first = value.args[0] if value.args else value
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                raise _refuse(WORKFLOWS, value, "WorkflowProcess has no string literal feature as its first argument; write one")
            processes[first.value] = (node.targets[0].id, value.args[1] if len(value.args) > 1 else value)
        if node.targets[0].id == "WORKFLOW_VARIANTS" and isinstance(value, ast.Dict):
            for key, variant in zip(value.keys, value.values, strict=True):
                if not (isinstance(key, ast.Constant) and isinstance(variant, ast.Call) and variant.args):
                    raise _refuse(WORKFLOWS, variant, "the command reads only a variant `\"<name>\": WorkflowVariant(<process>)`")
                variants.append((str(key.value), variant.args[0], variant))
    if feature not in processes:
        raise _refuse(WORKFLOWS, tree, f"no WorkflowProcess(\"{feature}\", …); name the process of the feature so")
    constant, workflow = processes[feature]
    function = _functions(tree).get(workflow.id) if isinstance(workflow, ast.Name) else None
    if function is None:
        raise _refuse(WORKFLOWS, workflow, "the workflow of WorkflowProcess is no function of the module; define it there")
    own = [(name, variant) for name, process, variant in variants if ast.unparse(process) == constant]
    for _, variant in own:
        if len(variant.args) != 1 or variant.keywords:
            raise _refuse(WORKFLOWS, variant, "the command does not print the fields of a variant; give its process none")
    return constant, function, [name for name, _ in own]


def _running(tree: ast.Module) -> set[str]:
    """Functions of the module that run steps, through any chain of calls of functions of the module."""

    functions = _functions(tree)
    running = set(STEPS)
    while grown := {name for name, function in functions.items() if name not in running and _names(function) & running}:
        running |= grown
    return running - set(STEPS)


def _script(arguments: ast.expr, kind: str) -> str | None:
    first = arguments.elts[0] if isinstance(arguments, ast.List) and arguments.elts else None
    if kind == "process":
        return f"tools/uruchom_proces.py {first.value}" if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
    if (
        isinstance(first, ast.Call)
        and ast.unparse(first.func) == "str"
        and len(first.args) == 1
        and isinstance(path := first.args[0], ast.BinOp)
        and isinstance(path.op, ast.Div)
        and ast.unparse(path.left) == "HELPER_DIRECTORY"
        and isinstance(path.right, ast.Constant)
        and isinstance(path.right.value, str)
    ):
        return path.right.value
    return None


def _step(call: ast.Call) -> Step:
    assert isinstance(call.func, ast.Name)
    kind = STEPS[call.func.id]
    name = call.args[0] if call.args else call
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        raise _refuse(WORKFLOWS, call, f"{call.func.id} names its step without a string literal; write the name as one")
    runs = _script(call.args[1], kind) if len(call.args) > 1 else None
    if runs is None:
        start = 'str(HELPER_DIRECTORY / "<script>.py")' if kind == "helper" else '"<command>"'
        raise _refuse(WORKFLOWS, call, f"{call.func.id} takes no list literal of arguments starting with {start}; write it so")
    exits = [keyword.value for keyword in call.keywords if keyword.arg == "expected_exit"]
    if len(exits) != 1 or not (isinstance(exits[0], ast.Constant) and type(exits[0].value) is int):
        raise _refuse(WORKFLOWS, call, f"{call.func.id} has no expected_exit integer literal; write expected_exit=<n>")
    return Step(name.value, runs, exits[0].value)


def _steps(tree: ast.Module, workflow: ast.FunctionDef) -> list[Step]:
    running = _running(tree)
    steps: list[Step] = []
    for statement in workflow.body:
        value = statement.value if isinstance(statement, ast.Expr) else None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in STEPS:
            steps.append(_step(value))
            reached = [node for node in ast.walk(value) if node is not value.func]
        else:
            reached = list(ast.walk(statement))
        for node in reached:
            if isinstance(node, ast.Name) and node.id in STEPS:
                raise _refuse(
                    WORKFLOWS, node, f"`{node.id}` is not called as a statement of {workflow.name}() itself; call it there"
                )
            if isinstance(node, ast.Name) and node.id in running:
                raise _refuse(
                    WORKFLOWS, node, f"{workflow.name}() runs steps in `{node.id}`; run them in {workflow.name}() itself"
                )
    if not steps:
        raise _refuse(WORKFLOWS, workflow, f"{workflow.name}() runs no step; run each with _run_step or _run_process_step")
    return steps


@dataclass
class _Helper:
    """Reads the checks of one helper script; ``source`` gives the text of a script by its file name."""

    name: str
    source: Callable[[str], str]
    read: set[tuple[str, str]] = field(default_factory=set)

    def checks(self, step: Step) -> None:
        tree = ast.parse(self.source(self.name))
        main = _functions(tree).get("main")
        if main is not None:
            self._function(self.name, tree, main, step)
        for name, function in _functions(tree).items():
            if (self.name, name) not in self.read and "errors" in _names(function):
                raise _refuse(
                    self.name, function, f"main() does not hand errors to {name}(), so the map cannot see its checks; "
                    "hand it errors from main or a function main hands it"
                )

    def _function(self, module: str, tree: ast.Module, function: ast.FunctionDef, step: Step) -> None:
        self.read.add((module, function.name))
        known = constants(tree)
        imported = {
            alias.asname or alias.name: node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        appends = {id(node.func) for node in ast.walk(function) if isinstance(node, ast.Call) and _is_append(node)}
        for node in _own(function.body):
            if isinstance(node, NESTED) and "errors" in _names(node):
                raise _refuse(module, node, "errors is used in a nested function or lambda; append in a function of the module")
            if isinstance(node, ast.Attribute) and _is_errors(node.value) and id(node) not in appends:
                raise _refuse(module, node, f"`{ast.unparse(node)}` is no call errors.append(<message>); append each check so")
            if isinstance(node, ast.Subscript) and _is_errors(node.value) and not isinstance(node.ctx, ast.Load):
                raise _refuse(module, node, f"`{ast.unparse(node)}` changes a check; append each check with errors.append")
            if isinstance(node, ast.Name) and node.id == "errors" and not isinstance(node.ctx, ast.Load):
                if not (function.name == "main" and module == self.name and _empty_list(function, node)):
                    raise _refuse(module, node, "errors is bound here; bind it once in main as errors = []")
            if not isinstance(node, ast.Call):
                continue
            if _is_append(node):
                if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
                    raise _refuse(module, node, "errors.append takes one message here; write errors.append(<message>)")
                printed = message(node.args[0], known)
                if printed is None:
                    raise _refuse(
                        module, node, f"errors.append has the message `{ast.unparse(node.args[0])}`; give it as a string "
                        "literal, a module constant or an f-string, so the map can print it"
                    )
                step.checks.append(printed)
            elif _hands_errors(node):
                self._call(module, tree, node, imported, known, step)

    def _call(
        self, module: str, tree: ast.Module, call: ast.Call, imported: dict[str, str | None], known: dict[str, str], step: Step
    ) -> None:
        name = call.func.id if isinstance(call.func, ast.Name) else None
        origin = module if name in _functions(tree) else f"{imported.get(name or '')}.py"
        if name is None or origin not in (module, SHARED):
            raise _refuse(module, call, f"`{ast.unparse(call.func)}` gets errors but the command does not read it; "
                          f"hand errors only to functions of this script or of {SHARED}")
        callee_tree = tree if origin == module else ast.parse(self.source(SHARED))
        callee = _functions(callee_tree).get(name)
        positional = [argument.arg for argument in [*callee.args.posonlyargs, *callee.args.args]] if callee else []
        named_ok = callee is not None and "errors" in [argument.arg for argument in [*callee.args.args, *callee.args.kwonlyargs]]
        passed = [index for index, argument in enumerate(call.args) if _is_errors(argument)]
        named = [keyword.arg for keyword in call.keywords if _is_errors(keyword.value)]
        by_position = passed == [positional.index("errors")] if "errors" in positional else False
        if callee is None or not ((by_position and not named) or (named_ok and named == ["errors"] and not passed)):
            raise _refuse(module, call, f"{name}() does not take errors as its parameter errors; hand it so")
        if origin == SHARED and name == "finish":
            line = message(call.args[1], known) if len(call.args) == 2 else None
            if line is None:
                raise _refuse(module, call, "finish takes errors and a message here; write finish(errors, <message>)")
            if line:
                step.prints.append(line)
        elif (origin, name) not in self.read:
            self._function(origin, callee_tree, callee, step)


def _is_errors(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "errors"


def _is_append(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "append" and _is_errors(node.func.value)


def _hands_errors(node: ast.Call) -> bool:
    return any(_is_errors(argument) for argument in [*node.args, *(keyword.value for keyword in node.keywords)])


def _empty_list(function: ast.FunctionDef, name: ast.Name) -> bool:
    return any(
        isinstance(statement, (ast.Assign, ast.AnnAssign))
        and name in (statement.targets if isinstance(statement, ast.Assign) else [statement.target])
        and isinstance(statement.value, ast.List)
        and not statement.value.elts
        for statement in function.body
    )


def sub_features(feature: str, source: Callable[[str], str]) -> tuple[list[str], list[Step]]:
    """The variants and the steps of ``feature``; ``source`` gives the text of a script of the skill by its file name."""

    tree = ast.parse(source(WORKFLOWS))
    _, workflow, variants = _process(tree, feature)
    steps = _steps(tree, workflow)
    for step in steps:
        if not step.runs.startswith("tools/"):
            _Helper(step.runs, source).checks(step)
    return variants, steps


def section(feature: str) -> str:
    variants, steps = sub_features(feature, lambda name: (SCRIPTS / name).read_text(encoding="utf-8"))
    lines = [
        "## Sub-features",
        "",
        f"Printed by `scripts/workflow_sub_features.py --feature {feature}` from the steps of the workflow and the checks of its "
        "helpers; refresh the section with it.",
        "",
        f"Variants: {', '.join(f'`{variant}`' for variant in variants)}.",
        "",
    ]
    for step in steps:
        fails = " It fails when:" if step.checks else ""
        lines.append(f"- `{step.name}` runs `{step.runs}` and expects exit {step.exit_code}.{fails}")
        lines += [f"  - {check}" for check in step.checks]
        for line in step.prints:
            lines += ["", f"  It prints `{line}` when no check fails."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature", required=True, help="feature of the map, the first argument of its WorkflowProcess")
    try:
        printed = section(parser.parse_args().feature)
    except Unreadable as refusal:
        raise SystemExit(str(refusal)) from None
    # Bytes, so the Windows console (cp1252) neither refuses Polish letters nor turns line ends into CRLF.
    sys.stdout.buffer.write(printed.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
