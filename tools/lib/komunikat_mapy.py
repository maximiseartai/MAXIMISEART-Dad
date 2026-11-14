"""Komunikat sprawdzenia z kodu skilla, jak drukuje go sekcja ``## Sub-features`` mapy funkcji (``features/``).

Jeden właściciel tej reguły dla poleceń ``scripts/sub_features.py`` skilli ``verify-*``. Komunikat to literał napisu,
stała modułu (nazwa, którą moduł wiąże tylko raz, na swoim najwyższym poziomie, z napisem) albo f-string. Pole
f-stringu, które jest taką stałą, bez konwersji i bez formatu, drukuje jej wartość; każde inne pole drukuje się jako
``…``, bez względu na wyrażenie, konwersję i format, bo wartość zna dopiero przebieg skilla. Tekst f-stringu drukuje
się, jak stoi, ``{{`` jako ``{``. Komunikat innej postaci nie ma wydruku (``None``), a polecenie odmawia go z plikiem i
linią.
"""

from __future__ import annotations

import ast
from collections import Counter


def constants(tree: ast.Module) -> dict[str, str]:
    """Nazwy, które moduł wiąże dokładnie raz, na swoim najwyższym poziomie, z literałem napisu."""

    top: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            top[target.id] = value.value
    bound = Counter(name for node in ast.walk(tree) for name in _binds(node))
    return {name: value for name, value in top.items() if bound[name] == 1}


def _binds(node: ast.AST) -> list[str]:
    """Nazwy, które ``node`` wiąże, według konstrukcji wiązania z dokumentacji języka Python („Naming and binding”):
    cele przypisania, ``for``, ``with``, ``:=`` i ``del``, parametry, importy, ``def`` i ``class``,
    ``except ... as``, wzorce przechwytujące i parametry typu. ``global`` i ``nonlocal`` tylko deklarują nazwę, którą
    wiąże potem jedna z tych konstrukcji."""

    if isinstance(node, ast.Name):
        return [node.id] if isinstance(node.ctx, (ast.Store, ast.Del)) else []
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.alias):
        return [(node.asname or node.name).split(".")[0]]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.MatchMapping):
        return [node.rest] if node.rest else []
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return [node.name] if node.name else []
    if isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)):
        return [node.name]
    return []


def message(node: ast.expr, known: dict[str, str]) -> str | None:
    """Wydruk komunikatu ``node`` ze stałymi modułu ``known`` (``constants``); ``None`` dla innej postaci."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    if not isinstance(node, ast.JoinedStr):
        return None
    parts = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue) and part.conversion == -1 and part.format_spec is None:
            value = part.value
            parts.append(known[value.id] if isinstance(value, ast.Name) and value.id in known else "…")
        else:
            parts.append("…")
    return "".join(parts)
