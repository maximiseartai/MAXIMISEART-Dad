"""Ścieżki, które moduł Pythona nazywa w swoim kodzie: napisy, ścieżki składane operatorem ``/`` i globy na katalogach.

Czyta je ``tools/lib/wplyw_zmiany.py``: od tych plików zależy test, choć ich nie importuje.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeGuard

PATH_TYPES = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
GLOBS = frozenset({"glob", "rglob", "iterdir"})


@dataclass(frozen=True)
class Glob:
    folder: str
    pattern: str
    recursive: bool


def references(nodes: Sequence[ast.AST]) -> tuple[set[str], set[Glob]]:
    """Napisy modułu, ścieżki składane operatorem ``/`` (``ROOT / "docs" / "adr"`` daje ``docs/adr``) i globy na katalogach;
    ``nodes`` to wszystkie węzły modułu (``ast.walk``), które ``tools/lib/wplyw_zmiany.py`` przegląda raz także dla importów."""

    def is_path(node: ast.AST) -> TypeGuard[ast.BinOp]:
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)

    names: dict[str, list[str | None]] = {}

    def pieces(node: ast.AST) -> list[str | None]:
        if is_path(node):
            return pieces(node.left) + pieces(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value.strip("/")]
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if _is_path_call(node):
            return [piece for argument in node.args for piece in pieces(argument)]
        return [None]

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
        if isinstance(target, ast.Name) and (is_path(value) or (isinstance(value, ast.Name) and value.id in names)):
            names[target.id] = pieces(value)
    # Tylko cała ścieżka: początek ``ROOT / ".agents" / "skills"`` łańcucha ``... / "x"`` wskazałby wszystkie skille.
    beginnings = {id(node.left) for node in nodes if is_path(node)}
    texts = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    paths = [node for node in nodes if (is_path(node) or _is_path_call(node)) and id(node) not in beginnings]
    texts |= {run for node in paths for run in runs(pieces(node)) if "/" in run}
    globs: set[Glob] = set()
    for node in nodes:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in GLOBS):
            continue
        folder = pieces(node.func.value)
        if folder[-1] is None:
            continue
        if node.func.attr == "iterdir":
            globs.add(Glob(runs(folder)[-1], "*", recursive=False))
        elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            globs.add(Glob(runs(folder)[-1], node.args[0].value, recursive=node.func.attr == "rglob"))
    return texts, globs


def _is_path_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_TYPES and bool(node.args)
