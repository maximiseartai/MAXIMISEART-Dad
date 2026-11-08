"""Szeroki ``except`` w Centrum rozliczeń przekazuje złapany wyjątek do dziennika Centrum albo rzuca go dalej.

Ruff BLE001 uznaje za wpis do dziennika tylko ``logging``, a Centrum ma własny dziennik, więc ``pyproject.toml``
wyłącza BLE001 dla ``src/rozliczenia/centrum``, a tę samą regułę z dziennikiem Centrum sprawdza ten test.
``except Exception``, ``except BaseException`` i gołe ``except`` przechodzą, gdy blok woła ``unexpected_failure``
ze złapanym wyjątkiem albo go rzuca. Gołe ``raise`` w zagnieżdżonym ``except`` rzuca wyjątek wewnętrzny, więc się nie
liczy. Blok, który kończy się czym innym, ma wpis w ``OTHER_ENDINGS`` z powodem.
``contextlib.suppress(Exception)`` i typ wyjątku pod inną nazwą są poza testem, tak jak były poza BLE001.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENTRUM = ROOT / "src" / "rozliczenia" / "centrum"
BROAD = frozenset({"Exception", "BaseException"})
NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
OTHER_ENDINGS = {
    "restart_guardian.py::_rolled_back": "każda porażka cofnięcia kończy się okienkiem dla taty",
    "runs.py::Run.work": "RunHost.failed zapisuje typ wyjątku przez unexpected_failure dziennika Centrum",
}


def _broad(handler: ast.ExceptHandler) -> bool:
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(name is None or ast.unparse(name).removeprefix("builtins.") in BROAD for name in caught)


def _own_nodes(handler: ast.ExceptHandler) -> Iterator[tuple[ast.AST, bool]]:
    """Węzły bloku ``except`` bez ciał funkcji i klas, z tym, czy stoją w zagnieżdżonym ``except``."""

    pending: list[tuple[ast.AST, bool]] = [(node, False) for node in handler.body]
    while pending:
        node, inner = pending.pop()
        yield node, inner
        pending.extend(
            (child, inner or isinstance(child, ast.ExceptHandler))
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, NESTED)
        )


def _is_caught(node: ast.expr | None, handler: ast.ExceptHandler) -> bool:
    return isinstance(node, ast.Name) and node.id == handler.name


def _ends_at_log_or_raise(handler: ast.ExceptHandler) -> bool:
    for node, inner in _own_nodes(handler):
        if isinstance(node, ast.Raise) and (
            (node.exc is None and not inner) or _is_caught(node.exc, handler) or _is_caught(node.cause, handler)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "unexpected_failure"
            and node.args
            and _is_caught(node.args[0], handler)
        ):
            return True
    return False


def _broad_handlers(tree: ast.Module) -> Iterator[tuple[str, ast.ExceptHandler]]:
    """Szerokie bloki ``except`` modułu z nazwą funkcji, w której stoją (``Klasa.metoda``)."""

    def visit(node: ast.AST, scope: tuple[str, ...]) -> Iterator[tuple[str, ast.ExceptHandler]]:
        for child in ast.iter_child_nodes(node):
            inner = (*scope, child.name) if isinstance(child, NESTED) and not isinstance(child, ast.Lambda) else scope
            if isinstance(child, ast.ExceptHandler) and _broad(child):
                yield ".".join(scope) or "<moduł>", child
            yield from visit(child, inner)

    return visit(tree, ())


def test_szeroki_except_w_centrum_konczy_sie_dziennikiem_centrum_albo_ponownym_rzuceniem() -> None:
    problems = []
    unused = dict(OTHER_ENDINGS)
    for path in sorted(CENTRUM.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for where, handler in _broad_handlers(tree):
            key = f"{path.relative_to(CENTRUM).as_posix()}::{where}"
            if _ends_at_log_or_raise(handler):
                continue
            if unused.pop(key, None) is None:
                problems.append(
                    f"{path.relative_to(ROOT).as_posix()}:{handler.lineno} ({where}): szeroki except bez "
                    "unexpected_failure(<złapany wyjątek>, where=...) dziennika Centrum i bez raise; dopisz jedno "
                    f"z nich albo wpis {key!r} z powodem do OTHER_ENDINGS"
                )

    problems.extend(f"OTHER_ENDINGS: {key} nie ma już szerokiego except bez dziennika, usuń wpis" for key in unused)
    assert problems == [], "\n".join(problems)
