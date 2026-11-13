"""Ścieżki, które moduł Pythona nazywa w swoim kodzie: napisy, ścieżki składane operatorem ``/`` (także od katalogu
``Path(__file__)``) i globy na katalogach.

Czyta je ``tools/lib/wplyw_zmiany.py``: od tych plików zależy test, choć ich nie importuje.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeGuard

PATH_TYPES = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
GLOBS = frozenset({"glob", "rglob", "iterdir", "walk"})


@dataclass(frozen=True)
class Glob:
    folder: str
    pattern: str
    recursive: bool


def references(nodes: Sequence[ast.AST], module: str) -> tuple[set[str], set[Glob]]:
    """Napisy modułu, ścieżki składane operatorem ``/`` (``ROOT / "docs" / "adr"`` daje ``docs/adr``, a
    ``Path(__file__).parent / "expected"`` w ``tests/test_a.py`` daje ``tests/expected``) i globy na katalogach; glob ze
    wzorcem, który nie jest napisem, się nie liczy. ``nodes`` to wszystkie węzły modułu ``module`` (ścieżka w
    repozytorium, ``ast.walk``), które ``tools/lib/wplyw_zmiany.py`` przegląda raz także dla importów."""

    def is_path(node: ast.AST) -> TypeGuard[ast.BinOp]:
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)

    names: dict[str, list[str | None]] = {}

    def pieces(node: ast.AST) -> list[str | None]:
        if is_path(node):
            return pieces(node.left) + pieces(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value.strip("/")]
        if isinstance(node, ast.Name) and node.id == "__file__":
            return [module]
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if _is_path_call(node):
            return [piece for argument in node.args for piece in pieces(argument)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"resolve", "absolute"}:
            return pieces(node.func.value)
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return up(pieces(node.value), 1)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, int) and not isinstance(index.value, bool):
                return up(pieces(node.value.value), index.value + 1)
        return [None]

    def up(path: list[str | None], levels: int) -> list[str | None]:
        """Katalog ``levels`` poziomów nad ścieżką znaną w całości; korzeń repozytorium to pusta lista."""

        if None in path:
            return [None]
        parts = [part for piece in path if piece for part in piece.split("/")]
        return [None] if levels > len(parts) else [*parts[: len(parts) - levels]]

    def runs(path: list[str | None]) -> list[str]:
        found, joined = [], []
        for piece in [*path, None]:
            if piece is not None:
                joined.append(piece)
                continue
            if joined:
                found.append("/".join(joined))
            joined = []
        return found

    assignments = [node for node in nodes if isinstance(node, ast.Assign) and len(node.targets) == 1]
    for assignment in sorted(assignments, key=lambda node: (node.lineno, node.col_offset)):
        target, value = assignment.targets[0], assignment.value
        if isinstance(target, ast.Name) and isinstance(value, (ast.BinOp, ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
            if (path := pieces(value)) != [None]:
                names[target.id] = path
    # Tylko cała ścieżka: początek ``ROOT / ".agents" / "skills"`` łańcucha ``... / "x"`` wskazałby wszystkie skille.
    beginnings = {id(node.left) for node in nodes if is_path(node)}
    texts = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    paths = [node for node in nodes if (is_path(node) or _is_path_call(node)) and id(node) not in beginnings]
    texts |= {run for node in paths for run in runs(pieces(node)) if "/" in run}
    globs: set[Glob] = set()
    for node in nodes:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in GLOBS):
            continue
        attribute, owner = node.func.attr, node.func.value
        # ``os.walk(katalog)`` przechodzi katalog z argumentu, a ``Path.walk()`` swój, jak ``iterdir()``.
        if attribute == "walk" and isinstance(owner, ast.Name) and owner.id == "os" and node.args:
            owner = node.args[0]
        folder = pieces(owner)
        if not folder or folder[-1] is None:
            continue
        if attribute in {"iterdir", "walk"}:
            globs.add(Glob(runs(folder)[-1], "*", recursive=attribute == "walk"))
        elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            globs.add(Glob(runs(folder)[-1], node.args[0].value, recursive=attribute == "rglob"))
    return texts, globs


def _is_path_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_TYPES and bool(node.args)
