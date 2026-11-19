"""Składnia plików dla testów struktury: drzewo pliku i jego węzły raz na moduł strażników oraz pełna nazwa wołanej
funkcji po importach modułu (``sp.run`` to ``subprocess.run``)."""

from __future__ import annotations

import ast
from collections.abc import Callable, Hashable, Iterator, Mapping
import contextlib
from pathlib import Path
from typing import TypeVar, cast

__all__ = ["dotted", "drzewo", "imports", "pamiec_drzew", "raz_na_drzewo", "wezly"]

_Drzewo = TypeVar("_Drzewo", bound=ast.AST)
_Wynik = TypeVar("_Wynik")
# Otwarte bloki ``pamiec_drzew``, ostatni na końcu.
_PAMIEC: list[dict[Hashable, object]] = []


@contextlib.contextmanager
def pamiec_drzew() -> Iterator[None]:
    """Blok, w którym ``drzewo``, ``wezly`` i funkcje z ``raz_na_drzewo`` liczą każdy wynik raz; moduł strażników
    całego repo otacza nim swoje testy fixture'em na moduł, bo jego testy czytają te same ~600 plików.

    Poza blokiem każde wywołanie liczy od nowa. Pamięć nie żyje dłużej niż moduł, bo ~1,4 mln węzłów całego repo, które
    zostałyby w workerze, spowalnia GC każdego następnego testu (praca z alokacjami 1,3 → 2,9 s na Pythonie 3.12)."""

    _PAMIEC.append({})
    try:
        yield
    finally:
        _PAMIEC.pop()


def _raz(key: Hashable, compute: Callable[[], _Wynik]) -> _Wynik:
    if not _PAMIEC:
        return compute()
    memo = _PAMIEC[-1]
    if key not in memo:
        memo[key] = compute()
    return cast(_Wynik, memo[key])


def drzewo(path: Path) -> ast.Module:
    """Drzewo składni pliku ``path``, w bloku ``pamiec_drzew`` jedno na jego treść.

    Klucz to treść, nie ścieżka ani czas zmiany: plik zapisany w trakcie (próbka w ``tmp_path``) dostaje nowe drzewo
    także w tej samej sekundzie. Drzewo dzielą wszyscy, którzy czytają ten plik w bloku, więc nie zmieniaj jego
    węzłów."""

    source = path.read_text(encoding="utf-8")
    return _raz(("drzewo", source), lambda: ast.parse(source))


def wezly(tree: ast.AST) -> tuple[ast.AST, ...]:
    """Węzły ``tree`` w kolejności ``ast.walk``, w bloku ``pamiec_drzew`` raz na drzewo: przejście ``ast.walk`` po
    całym repo kosztuje ok. 0,4 s, a strażnicy robią ich kilkanaście po tych samych drzewach."""

    return _raz(("wezly", tree), lambda: tuple(ast.walk(tree)))


def raz_na_drzewo(function: Callable[[_Drzewo], _Wynik]) -> Callable[[_Drzewo], _Wynik]:
    """``function`` od drzewa, w bloku ``pamiec_drzew`` liczona raz na drzewo."""

    def once(tree: _Drzewo) -> _Wynik:
        return _raz((function, tree), lambda: function(tree))

    return once


def imports(tree: ast.Module) -> dict[str, str]:
    """Nazwa, którą import wiąże w module, i pełna nazwa tego, co wskazuje."""

    names: dict[str, str] = {}
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                names[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names |= {alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names}
    return names


def dotted(expression: ast.expr, names: Mapping[str, str], module: str) -> str | None:
    """``a.b.c`` z ``a`` rozwiniętym przez import; nazwa spoza importów należy do ``module``."""

    if isinstance(expression, ast.Name):
        return names.get(expression.id, f"{module}.{expression.id}")
    if isinstance(expression, ast.Attribute):
        owner = dotted(expression.value, names, module)
        return None if owner is None else f"{owner}.{expression.attr}"
    return None
