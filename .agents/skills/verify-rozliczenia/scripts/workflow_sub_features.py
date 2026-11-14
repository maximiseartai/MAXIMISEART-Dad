"""Prints the section ``## Sub-features`` of a feature file from the workflow of its process.

A feature is a process ``WorkflowProcess("<feature>", <workflow>, …)`` of ``run_verification.py``, and its variants are
the keys of ``WORKFLOW_VARIANTS`` whose ``WorkflowVariant(<process>)`` has no other argument. Each line is a step of the
workflow, in source order: a statement ``_run_step("<step>", [str(HELPER_DIRECTORY / "<script>"), …], …,
expected_exit=<n>)`` or ``_run_process_step("<step>", ["<command>", …], …, expected_exit=<n>)`` of the workflow
function's own body, which runs that helper script or ``tools/uruchom_proces.py <command>`` and expects that exit code.
Under a helper's step stand the ways the helper fails, in source order. The command reads ``main`` and every function
of the script or of ``wynik_uruchomienia.py`` it calls by name, at each call, and knows exactly these ways: a message
``errors.append(<message>)`` in the list ``main`` binds as ``errors = []`` and hands to a parameter ``errors``, which
``finish(errors, <line>)`` prints with exit 1 (and ``<line>`` when no message was appended); ``print(<message>)``
right before ``return <code>`` in ``main``; and ``assert <test>, <message>`` that no ``try`` catches. A message
prints by the rule of ``tools/lib/komunikat_mapy.py``. A ``raise`` is read only when a ``try`` around it, in the
function or around the call in a caller, catches it, by the hierarchy of the built-in exceptions; its handler then
says how the step fails. A condition whose names are all parameters bound to a literal, by a literal argument or by
the default the call leaves out, is decided: a branch or loop it rules out holds no check of this step.

The command reads only that form and fails, naming the file, the line and what to do, on anything else: a process
without a string literal name, or a workflow that is no function of the module; a variant with fields; a step that is
no statement of the workflow's own body (in an ``if``, a loop, a nested function, or kept as a value); a call in the
workflow of a function of the module that runs steps; a step without a string literal name, a list literal of
arguments starting with the script, or an ``expected_exit`` integer literal. In a helper it refuses: a module
statement other than imports, constants, functions, classes and ``if __name__ == "__main__": raise
SystemExit(main())``; a helper without ``main``; a ``return`` in ``main`` other than ``finish(errors, …)``, ``0``,
nothing, or a code right after ``print(<message>)``; ``sys.exit``, ``exit``, ``quit``, ``os._exit``, ``raise
SystemExit``, a bare ``raise`` and a ``raise`` no ``try`` catches; an ``assert`` without a message it can print; a
compound statement other than ``if``, ``for``, ``while``, ``with``, ``try``, ``def`` and ``class``; a condition on
literal parameters it cannot decide; ``errors`` changed other than by ``errors.append(<message>)``, standing anywhere
in the script outside the reading above (the module, the ``__main__`` block, a method, an attribute, a function
``main`` does not reach), or handed to a function it does not read or to a parameter not
named ``errors``. It does not see a check appended through another name bound to the list (``found = errors``), an
exception or exit from a function of another module or from code of the module outside functions, nor a step run
without ``_run_step`` or ``_run_process_step``. The steps ``cleanup`` and ``self-test`` that ``_verify`` runs after
every workflow are not part of the section.
"""

from __future__ import annotations

import argparse
import ast
import builtins
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
import operator
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


def _own(nodes: Sequence[ast.AST]) -> Iterator[ast.AST]:
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


EXITS = frozenset({"sys.exit", "exit", "quit", "os._exit"})
MAIN_BLOCK = "if __name__ == '__main__':\n    raise SystemExit(main())"
_NOT_LITERAL = object()


@dataclass(frozen=True)
class _Scope:
    """Where the reader stands: the module, whether ``errors`` is the list of checks here, the exceptions an enclosing
    ``try`` catches, the parameters bound to a literal value, and whether this is the body of ``main``."""

    module: str
    tree: ast.Module
    errors: bool
    caught: tuple[str, ...] = ()
    bound: dict[str, object] = field(default_factory=dict)
    main: bool = False


@dataclass
class _Helper:
    """Reads how one helper script fails; ``source`` gives the text of a script by its file name."""

    name: str
    source: Callable[[str], str]
    seen: set[int] = field(default_factory=set)
    printed: set[int] = field(default_factory=set)
    stack: list[tuple[str, str]] = field(default_factory=list)

    def checks(self, step: Step) -> None:
        tree = ast.parse(self.source(self.name))
        for statement in tree.body:
            if not _module_statement(statement):
                raise _refuse(self.name, statement, "the command reads no module statement but imports, constants, "
                              f"functions, classes and `{MAIN_BLOCK}`; move it into a function")
        main = _functions(tree).get("main")
        if main is None:
            raise _refuse(self.name, tree, "the helper has no def main(); its checks start there")
        self.seen |= {id(node) for statement in main.body if _binds_empty_errors(statement) for node in ast.walk(statement)}
        self._statements(main.body, _Scope(self.name, tree, errors=True, main=True), step)
        for node in ast.walk(tree):
            named = node.arg if isinstance(node, ast.arg) else getattr(node, "id", None) or getattr(node, "attr", None)
            if named == "errors" and id(node) not in self.seen:
                raise _refuse(self.name, node, "errors stands where the command does not read it as the list of checks; "
                              "bind it once in main as errors = [] and hand it only to functions of the script")

    def _statements(self, statements: list[ast.stmt], scope: _Scope, step: Step) -> None:
        for previous, statement in zip([None, *statements], statements, strict=False):
            self._statement(statement, previous, scope, step)

    def _statement(self, statement: ast.stmt, previous: ast.stmt | None, scope: _Scope, step: Step) -> None:
        inner = replace(scope, errors=False, main=False)
        if isinstance(statement, ast.Try):
            caught = tuple(name for handler in statement.handlers for name in _caught(handler))
            self._statements(statement.body, replace(scope, caught=(*scope.caught, *caught)), step)
            for handler in statement.handlers:
                self._statements(handler.body, scope, step)
            self._statements([*statement.orelse, *statement.finalbody], scope, step)
        elif isinstance(statement, (ast.If, ast.While)):
            self._expression(statement.test, scope, step)
            taken = _decide(statement.test, scope.bound, scope.module)
            self._branch(statement.body, taken is not False, scope, step)
            self._branch(statement.orelse, taken is not True, scope, step)
        elif isinstance(statement, (ast.For, ast.With)):
            parts = [statement.target, statement.iter] if isinstance(statement, ast.For) else statement.items
            for part in parts:
                self._expression(part, scope, step)
            empty = isinstance(statement, ast.For) and _decide(statement.iter, scope.bound, scope.module) is False
            self._branch(statement.body, not empty, scope, step)
            self._statements(getattr(statement, "orelse", []), scope, step)
        elif isinstance(statement, (ast.FunctionDef, ast.ClassDef)):
            self._statements(statement.body, inner, step)
        elif hasattr(statement, "body") or isinstance(statement, ast.Match):
            raise _refuse(scope.module, statement, "the command does not read this compound statement; use if, for, "
                          "while, with or try")
        elif isinstance(statement, ast.Return) and scope.main:
            self._exit(statement, previous, scope, step)
        elif isinstance(statement, ast.Raise):
            target = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc
            name = target.id if isinstance(target, ast.Name) else ""
            if name == "SystemExit" or not _catches(scope.caught, name):
                raise _refuse(scope.module, statement, "the raise is caught by no try around the call in main, so the "
                              "step fails without a message the map prints; catch it there or append the check")
            self._expression(statement, scope, step)
        elif isinstance(statement, ast.Assert):
            self._expression(statement, scope, step)
            if not _catches(scope.caught, "AssertionError"):
                printed = message(statement.msg, constants(scope.tree)) if statement.msg else None
                if printed is None:
                    raise _refuse(scope.module, statement, "the assert has no message the map can print; give it a "
                                  "string literal, a module constant or an f-string")
                self._check(statement, printed, step)
        else:
            self._expression(statement, scope, step)

    def _branch(self, statements: list[ast.stmt], taken: bool, scope: _Scope, step: Step) -> None:
        """Reads a branch the step can take; a branch a literal rules out holds no check of the step."""

        if taken:
            self._statements(statements, scope, step)
        elif scope.errors:
            self.seen |= {id(node) for statement in statements for node in ast.walk(statement) if _is_errors(node)}

    def _exit(self, statement: ast.Return, previous: ast.stmt | None, scope: _Scope, step: Step) -> None:
        value = statement.value
        said = previous.value if isinstance(previous, ast.Expr) else None
        if value is None or (isinstance(value, ast.Constant) and value.value == 0 and type(value.value) is int):
            return
        if isinstance(value, ast.Call) and ast.unparse(value.func) == "finish" and _origin(scope, "finish") == SHARED:
            self._expression(value, scope, step)
        elif (
            isinstance(value, ast.Constant)
            and type(value.value) is int
            and isinstance(said, ast.Call)
            and ast.unparse(said.func) == "print"
            and len(said.args) == 1
            and (printed := message(said.args[0], constants(scope.tree))) is not None
        ):
            self._check(said, printed, step)
        else:
            raise _refuse(scope.module, statement, f"main() returns `{ast.unparse(statement)}`; return finish(errors, "
                          "<message>), 0, or a code right after print(<message>)")

    def _expression(self, node: ast.AST, scope: _Scope, step: Step) -> None:
        appends = {id(each.func) for each in ast.walk(node) if isinstance(each, ast.Call) and _is_append(each)}
        for each in _own([node]):
            if isinstance(each, ast.Lambda):
                self._expression(each.body, replace(scope, errors=False, main=False), step)
            elif isinstance(each, ast.Name) and each.id == "errors" and scope.errors and isinstance(each.ctx, ast.Load):
                self.seen.add(id(each))
            elif isinstance(each, ast.Attribute) and _is_errors(each.value) and id(each) not in appends:
                raise _refuse(scope.module, each, f"`{ast.unparse(each)}` is no call errors.append(<message>); append "
                              "each check so")
            elif isinstance(each, ast.Subscript) and _is_errors(each.value) and not isinstance(each.ctx, ast.Load):
                raise _refuse(scope.module, each, f"`{ast.unparse(each)}` changes a check; append each check with "
                              "errors.append")
            elif isinstance(each, ast.Call) and _is_append(each):
                if len(each.args) != 1 or each.keywords or isinstance(each.args[0], ast.Starred):
                    raise _refuse(scope.module, each, "errors.append takes one message here; write errors.append(<message>)")
                printed = message(each.args[0], constants(scope.tree))
                if printed is None:
                    raise _refuse(scope.module, each, f"errors.append has the message `{ast.unparse(each.args[0])}`; give "
                                  "it as a string literal, a module constant or an f-string, so the map can print it")
                if scope.errors:
                    self._check(each, printed, step)
            elif isinstance(each, ast.Call) and ast.unparse(each.func) in EXITS:
                raise _refuse(scope.module, each, f"`{ast.unparse(each.func)}` ends the step without a message the map "
                              "prints; return from main instead")
            elif isinstance(each, ast.Call) and (_origin(scope, _called(each)) or _hands_errors(each)):
                self._call(each, scope, step)

    def _call(self, call: ast.Call, scope: _Scope, step: Step) -> None:
        name, origin = _called(call), _origin(scope, _called(call))
        if origin is None:
            raise _refuse(scope.module, call, f"`{ast.unparse(call.func)}` gets errors but the command does not read it; "
                          f"hand errors only to functions of this script or of {SHARED}")
        tree = scope.tree if origin == scope.module else ast.parse(self.source(origin))
        callee = _functions(tree).get(name)
        if callee is None or any(isinstance(arg, ast.Starred) for arg in call.args) or None in [k.arg for k in call.keywords]:
            raise _refuse(scope.module, call, f"{name}() is no function of {origin} called with plain arguments; call it so")
        positional = [argument.arg for argument in [*callee.args.posonlyargs, *callee.args.args]]
        handed = _handed(call, callee, positional)
        if handed is None:
            raise _refuse(scope.module, call, f"{name}() does not take errors as its parameter errors; hand it so")
        if handed:
            self.seen |= {id(argument) for argument in ast.walk(callee.args) if getattr(argument, "arg", None) == "errors"}
        if origin == SHARED and name == "finish":
            line = message(call.args[1], constants(scope.tree)) if len(call.args) == 2 else None
            if line is None:
                raise _refuse(scope.module, call, "finish takes errors and a message here; write finish(errors, <message>)")
            if line:
                step.prints.append(line)
        elif (origin, name) not in self.stack:
            self.stack.append((origin, name))
            bound = _bindings(call, callee, positional, scope.bound)
            self._statements(callee.body, _Scope(origin, tree, handed, scope.caught, bound), step)
            self.stack.pop()

    def _check(self, node: ast.AST, printed: str, step: Step) -> None:
        if id(node) not in self.printed:
            self.printed.add(id(node))
            step.checks.append(printed)


def _module_statement(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
        return True
    value = statement.value if isinstance(statement, ast.Expr) else None
    return (
        isinstance(value, ast.Constant)
        or (isinstance(value, ast.Call) and ast.unparse(value.func) == "sys.path.insert")
        or ast.unparse(statement) == MAIN_BLOCK
    )


def _binds_empty_errors(statement: ast.stmt) -> bool:
    targets = statement.targets if isinstance(statement, ast.Assign) else [getattr(statement, "target", None)]
    value = getattr(statement, "value", None)
    return [ast.unparse(target) for target in targets if target] == ["errors"] and isinstance(value, ast.List) and not value.elts


def _caught(handler: ast.ExceptHandler) -> list[str]:
    if handler.type is None:
        return ["BaseException"]
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return [ast.unparse(each) for each in types]


def _catches(caught: tuple[str, ...], name: str) -> bool:
    """Whether a handler of ``caught`` takes the exception ``name``, by the hierarchy of the built-in exceptions."""

    raised = getattr(builtins, name, None)
    return any(
        each == name
        or (isinstance(raised, type)
        and isinstance(handler := getattr(builtins, each, None), type)
        and issubclass(raised, handler))
        for each in caught
    )


def _called(call: ast.Call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _origin(scope: _Scope, name: str) -> str | None:
    """The script whose function ``name`` is: this module's, or ``wynik_uruchomienia.py`` for a name imported from it."""

    if name in _functions(scope.tree):
        return scope.module
    imported = {(alias.asname or alias.name): node.module for node in scope.tree.body if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    return SHARED if name and f"{imported.get(name)}.py" == SHARED else None


def _handed(call: ast.Call, callee: ast.FunctionDef, positional: list[str]) -> bool | None:
    """Whether ``call`` hands ``errors`` to the parameter ``errors`` of ``callee``; ``None`` when it hands it elsewhere."""

    passed = [index for index, argument in enumerate(call.args) if _is_errors(argument)]
    named = [keyword.arg for keyword in call.keywords if _is_errors(keyword.value)]
    names = positional + [argument.arg for argument in callee.args.kwonlyargs]
    if not passed and not named:
        return False
    by_position = "errors" in positional and passed == [positional.index("errors")] and not named
    return True if by_position or (named == ["errors"] and not passed and "errors" in names) else None


def _literal(node: ast.expr, bound: dict[str, object]) -> object:
    if isinstance(node, ast.Name):
        return bound.get(node.id, _NOT_LITERAL)
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return _NOT_LITERAL


def _bindings(call: ast.Call, callee: ast.FunctionDef, positional: list[str], bound: dict[str, object]) -> dict[str, object]:
    """Parameters of ``callee`` that ``call`` binds to a literal value: a literal argument, or the default it omits."""

    arguments = callee.args
    defaults = dict(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults, strict=True))
    defaults |= {each.arg: value for each, value in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True) if value}
    given = {**dict(zip(positional, call.args, strict=False)), **{k.arg: k.value for k in call.keywords if k.arg}}
    values = {name: _literal(node, bound) for name, node in {**defaults, **given}.items()}
    return {name: value for name, value in values.items() if value is not _NOT_LITERAL}


def _decide(test: ast.expr, bound: dict[str, object], module: str) -> bool | None:
    """The truth of ``test`` when every name in it is bound to a literal value; ``None`` when it depends on the run."""

    names = {each.id for each in ast.walk(test) if isinstance(each, ast.Name)}
    if not names or not names <= bound.keys():
        return None
    try:
        return bool(_evaluate(test, bound))
    except ValueError:
        raise _refuse(module, test, f"`{ast.unparse(test)}` depends only on literal arguments, but the command cannot "
                      "decide it; compare the parameter with ==, !=, in or is, or test it alone") from None


def _evaluate(node: ast.expr, bound: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return bound[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _evaluate(node.operand, bound)
    if isinstance(node, ast.BoolOp):
        values = [bool(_evaluate(value, bound)) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE:
        return COMPARE[type(node.ops[0])](_evaluate(node.left, bound), _evaluate(node.comparators[0], bound))
    raise ValueError(ast.unparse(node))


COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.In: lambda left, right: operator.contains(right, left),
    ast.NotIn: lambda left, right: not operator.contains(right, left),
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def _is_errors(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "errors"


def _is_append(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "append" and _is_errors(node.func.value)


def _hands_errors(node: ast.Call) -> bool:
    return any(_is_errors(argument) for argument in [*node.args, *(keyword.value for keyword in node.keywords)])


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
