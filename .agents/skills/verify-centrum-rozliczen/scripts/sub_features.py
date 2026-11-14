"""Prints the section ``## Sub-features`` of a feature file from the feature's drive module.

Each sub-feature is a ``run.step(feature, "<id>")`` in ``drive(run, page)`` of ``drive/<feature>.py``, in source
order, and its line joins the messages of the ``run.check`` calls after it, which the drive prints as ``ok:`` under
``STEP <feature> | <id>`` in ``drive.txt``. A message is a string literal, a module constant (a name the module binds
only once, at its top level, to a string) or an f-string. A placeholder of the f-string that is such a constant, with
no conversion and no format spec, prints its value; every other placeholder prints as ``…``, whatever its expression,
conversion or format spec, because the value is known only when the drive runs. The literal text prints as it is,
``{{`` as ``{``. The rule has one owner, ``tools/lib/komunikat_mapy.py``, for the map commands of every skill. A
helper (a plain top-level function the module binds once, whose first parameter is ``run`` and whose body calls
``run.step`` or ``run.check``) prints its steps and checks at each call of ``drive``, in the order of the statements:
each whole statement of ``drive``'s body runs once when ``drive`` runs to its end, and so does each statement of the
body of a ``try`` that stands so in ``drive`` with only a ``finally`` that does not return, as an exception in that
body leaves ``drive`` after the ``finally``. A step or a check in a loop prints once per loop over a fixed list: a
``for`` over a non-empty tuple or list literal, written in its header or bound to a name the module binds only once,
earlier in the same block, without ``break``, ``continue`` or ``else``, runs its body at least once and as many times
as the code says.

The command reads only that form and fails, naming the file, the line and what to do, on anything else: a ``drive``
whose first parameter is not ``run``, a step or a check without exactly two positional arguments or with a starred
one, a step name that is no string literal, a message of another kind,
a check before the first step, and any attribute ``.step`` or ``.check`` in the module, on whatever object, that
is not the called function of such a call on ``run`` in the body of ``drive`` or of a helper (outside any function,
lambda or class in it), any use of a helper's name but a call ``helper(run, …)`` that is a whole statement, or the
whole value of an assignment to names, of such a body, before any ``return`` of ``drive`` and without a step or a
check in its arguments, a helper that is decorated or yields, and a step or a check of ``drive`` or a helper in any
other loop, in a condition (a branch, an operand after the first of ``and``/``or``, ``except``, the ``else`` or the
body with ``except`` of ``try``) or after a ``return`` of its function: elsewhere it cannot tell whether, how many times or
in which order the helper runs. It does not see a check reached without such an attribute, as
``getattr(run, "check")``, a function of another drive module, or a helper reached without its name, as
``globals()["helper"]``. Checks in the
shared helpers of ``drive/common.py`` print under the step that calls them and are not part of the section: the
section maps this module's own steps and checks.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from komunikat_mapy import binds, constants, message

from drive import FEATURES, feature

DRIVE = Path(__file__).resolve().parent / "drive"
CALLS = frozenset({"step", "check"})
NOT_FIXED_LOOP = "in a loop that is not a `for` over a fixed list (a non-empty tuple or list literal, without break, continue or else)"


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

    calls = [node for node in _own_nodes(function) if isinstance(node, ast.Call) and _is_run_call(node.func)]
    return sorted(calls, key=lambda call: (call.lineno, call.col_offset))


def _own_nodes(function: ast.FunctionDef) -> list[ast.AST]:
    """The nodes of ``function``'s body, not those of a function, lambda or class inside it."""

    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            nodes.append(node)
            stack.extend(ast.iter_child_nodes(node))
    return nodes


def _is_run_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in CALLS
        and isinstance(node.value, ast.Name)
        and node.value.id == "run"
    )


def _refuse_other_forms(tree: ast.Module, own: list[ast.Call], module: str) -> None:
    """Fails on every attribute ``.step``/``.check`` in the module, on whatever object, but the called function of
    ``own``: the command does not tell which object is a ``Run``, so it reads none but ``run`` in ``drive`` and helpers."""

    read = {id(call.func) for call in own}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in CALLS and id(node) not in read:
            raise _refuse(
                module,
                node,
                f"`{ast.unparse(node)}` is not run.{node.attr} called in the body of drive() or of a helper drive() calls "
                f"as a whole statement `helper(run, …)`; call run.{node.attr}(…) there, so the map sees what the drive prints",
            )


def _refuse_flow(tree: ast.Module, function: ast.FunctionDef, module: str) -> None:
    """Fails on a step or a check of ``function`` that may run another number of times than the section says."""

    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    bound = Counter(name for node in ast.walk(tree) for name in binds(node))
    returns = [node.lineno for node in _own_nodes(function) if isinstance(node, ast.Return)]
    for call in _own_calls(function):
        where = "after a `return`" if any(line < call.lineno for line in returns) else None
        child: ast.AST = call
        while where is None and (parent := parents[id(child)]) is not function:
            if isinstance(parent, ast.For) and child is not parent.iter and not _fixed_loop(parent, parents, bound):
                where = NOT_FIXED_LOOP
            elif isinstance(parent, ast.AsyncFor | ast.While | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
                where = NOT_FIXED_LOOP
            elif _branch(parent, child):
                where = "in a condition"
            child = parent
        if where is not None:
            raise _refuse(module, call, f"run.{call.func.attr} of {function.name}() stands {where}, and the section prints "
                          "each step and check once: the command reads one only where it runs once, or once per loop over "
                          "a fixed list; move it out, or loop over a non-empty tuple or list literal")


def _branch(parent: ast.AST, child: ast.AST) -> bool:
    """Whether ``child`` runs only on some runs of ``parent``."""

    if isinstance(parent, ast.If | ast.IfExp):
        return child is not parent.test
    if isinstance(parent, ast.BoolOp):
        return child is not parent.values[0]
    if isinstance(parent, ast.Match):
        return child is not parent.subject
    if isinstance(parent, ast.Try | ast.TryStar):
        return child in parent.orelse or (child in parent.body and bool(parent.handlers))
    if isinstance(parent, ast.Assert):
        return child is parent.msg
    return isinstance(parent, ast.ExceptHandler)


def _fixed_loop(loop: ast.For, parents: dict[int, ast.AST], bound: Counter[str]) -> bool:
    """Whether ``loop`` runs its body at least once and as many times as the code says (see the module docstring)."""

    def fixed(node: ast.expr) -> bool:
        return isinstance(node, ast.Tuple | ast.List) and bool(node.elts) and not any(isinstance(e, ast.Starred) for e in node.elts)

    block = next(body for _, body in ast.iter_fields(parents[id(loop)]) if isinstance(body, list) and loop in body)
    earlier = block[: block.index(loop)]
    named = isinstance(loop.iter, ast.Name) and bound[loop.iter.id] == 1 and any(
        isinstance(node, ast.Assign | ast.AnnAssign)
        and [ast.unparse(target) for target in getattr(node, "targets", [getattr(node, "target", None)])] == [loop.iter.id]
        and node.value is not None
        and fixed(node.value)
        for node in earlier
    )
    jumps = any(isinstance(node, ast.Break | ast.Continue) for part in loop.body for node in ast.walk(part))
    return (fixed(loop.iter) or named) and not jumps and not loop.orelse


def _helpers(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    bound = Counter(name for node in ast.walk(tree) for name in binds(node))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name != "drive"
            and bound[node.name] == 1 and [a.arg for a in [*node.args.posonlyargs, *node.args.args][:1]] == ["run"]
            and _own_calls(node)}


def _helper_calls(tree: ast.Module, drive: ast.FunctionDef, helpers: dict[str, ast.FunctionDef], module: str) -> list[ast.Call]:
    """Each call of each helper, a statement of ``drive``'s body or of a plain ``try``/``finally`` in it; fails on any
    other use of its name."""

    def cannot_tell(node: ast.AST, what: str) -> Unreadable:
        return _refuse(module, node, f"`{name}` {what}, but it calls run.step or run.check: the command prints a helper's "
                       "steps and checks only at a whole statement `helper(run, …)` or `name = helper(run, …)` in the body of "
                       "drive() or of a try in it with only a finally, as elsewhere it cannot tell whether, how many times or in which order they run; "
                       "call the plain helper so, or move its run.step and run.check into drive()")

    def owner(node: ast.AST) -> ast.AST:
        while not isinstance(node := parents[id(node)], ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            pass
        return node

    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = []
    for name, helper in helpers.items():
        named = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == name), key=lambda n: (n.lineno, n.col_offset))
        if helper.decorator_list or any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(helper)):
            raise cannot_tell(helper, "is decorated or yields")
        for one in named:
            call = parents[id(one)]
            if not (isinstance(call, ast.Call) and call.func is one and call.args[:1]
                    and isinstance(call.args[0], ast.Name) and call.args[0].id == "run"):
                raise cannot_tell(one, "is named here without the call `helper(run, …)`")
            statement, block = parents[id(call)], parents[id(parents[id(call)])]
            plain_try = (isinstance(block, ast.Try) and not block.handlers and statement in block.body
                         and parents[id(block)] is drive
                         and not any(isinstance(node, ast.Return) for part in block.finalbody for node in ast.walk(part)))
            if not (isinstance(statement, ast.Expr | ast.Assign) and (block is drive or plain_try)
                    and all(isinstance(target, ast.Name) for target in getattr(statement, "targets", []))):
                raise cannot_tell(call, "is called elsewhere than as a whole statement `helper(run, …)` or "
                                  "`name = helper(run, …)` in the body of drive() or of a try in it with only a finally")
            if any(isinstance(node, ast.Call) and _is_run_call(node.func) for node in ast.walk(call)):
                raise cannot_tell(call, "has run.step or run.check in its arguments")
            if any(isinstance(node, ast.Return) and node.lineno < call.lineno and owner(node) is drive for node in ast.walk(drive)):
                raise cannot_tell(call, "is called after a `return` of drive()")
            calls.append(call)
    return calls


def sub_features(source: str, module: str) -> list[tuple[str, list[str]]]:
    """Each sub-feature of a drive module's ``source`` with the messages of its checks; ``module`` names it in a
    refusal (``Unreadable``)."""

    tree = ast.parse(source)
    known = constants(tree)
    drive = _drive(tree, module)
    helpers = _helpers(tree)
    for function in [drive, *helpers.values()]:
        _refuse_flow(tree, function, module)
    own: list[ast.Call] = []
    for call in sorted([*_own_calls(drive), *_helper_calls(tree, drive, helpers, module)], key=lambda call: (call.lineno, call.col_offset)):
        own += _own_calls(helpers[call.func.id]) if isinstance(call.func, ast.Name) else [call]
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
