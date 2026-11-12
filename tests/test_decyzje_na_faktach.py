"""Kod decyduje na faktach, nie na kodzie Komunikatu.

Plan procesu oddaje typowane fakty, a jedno miejsce na proces tłumaczy je na ostrzeżenia, Zatrzymania, wynik i
Decyzję taty; Centrum rozliczeń też bierze fakt (``diagnosis.CheckResult.fixed_by_update``) albo gotowy wynik
katalogu (``update_messages.UpdateFailure``). Decyzja to porównanie (``==``, ``in``…) albo ``match``; zapis kodu do
metryk albo tekstu wyjątku decyzją nie jest.

W silniku (``src/rozliczenia/*.py``) decyzją jest każde porównanie z ``.code`` w wyrażeniu. W całym ``src/``, także
w Centrum, gdzie wyniki Aktualizacji narzędzia też mają pole ``code``, a nie są Komunikatami, decyzją jest porównanie
albo ``case`` z kodem Komunikatu: literałem, stałą modułu (także zaimportowaną, ``moduł.STAŁA``) albo klasy
(``Klasa.STAŁA``, a w jej metodzie ``self.STAŁA`` i ``cls.STAŁA``) albo zbiorem, krotką, listą lub słownikiem, który
go zawiera, także w wyrażeniu (``frozenset({...})``, ``{KOD: …}``, ``{…} | {…}``, ``(…) + (…)``). Kody to kody
próbek katalogów z ``tests/fixtures/message_samples.py``.

Granica: kod tylko w zmiennej lokalnej, ``self.STAŁA`` klasy zagnieżdżonej albo zdefiniowanej w funkcji, stała
klasy bazowej spoza modułu przez ``self``, kod sklejony z części (``"BRAK_" + "POLACZENIA"``), wyszukanie w słowniku
po kodzie (``tabela[message.code]``) i ``getattr`` łapie tylko przegląd.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
import importlib
from pathlib import Path
from types import ModuleType
from typing import Final

from tests.fixtures import message_samples

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "rozliczenia"
_UNKNOWN: Final = object()


def _reads_code(node: ast.AST) -> bool:
    return any(isinstance(inner, ast.Attribute) and inner.attr == "code" for inner in ast.walk(node))


def _decisions_on_code(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    decisions = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Compare) and _reads_code(node))
        or (isinstance(node, ast.Match) and _reads_code(node.subject))
    ]
    return [f"src/rozliczenia/{path.name}:{node.lineno}: {ast.unparse(node).splitlines()[0]}" for node in decisions]


def test_silnik_nie_decyduje_na_kodzie_komunikatu() -> None:
    found = [decision for path in sorted(ENGINE.glob("*.py")) for decision in _decisions_on_code(path)]

    assert not found, "\n".join(
        [
            *found,
            "Silnik nie decyduje na kodzie Komunikatu: niech plan odda fakt (dataclass), a decyzja procesu weźmie ten "
            "fakt.",
        ]
    )


def _message_codes() -> frozenset[str]:
    return frozenset(
        sample().code
        for name, samples in vars(message_samples).items()
        if name.endswith("_SAMPLES")
        for factory_samples in samples.values()
        for sample in factory_samples
    )


def _value(node: ast.AST, names: Mapping[str, object]) -> object:
    """Wartość operandu ze stałych modułu i jego klas; ``_UNKNOWN`` dla tego, co znane jest dopiero w trakcie działania."""

    match node:
        case ast.Constant(value=value):
            return value
        case ast.Name(id=name):
            return names.get(name, _UNKNOWN)
        case ast.Attribute(value=owner, attr=attr):
            holder = _value(owner, names)
            return getattr(holder, attr, _UNKNOWN) if isinstance(holder, ModuleType | type) else _UNKNOWN
        case ast.Set(elts=elements) | ast.Tuple(elts=elements) | ast.List(elts=elements):
            return tuple(_value(element, names) for element in elements)
        case ast.Dict(keys=keys):
            return tuple(_UNKNOWN if key is None else _value(key, names) for key in keys)
        case ast.Call(func=ast.Name(id="frozenset" | "set" | "tuple" | "list" | "dict"), args=[collection], keywords=[]):
            return _value(collection, names)
        case ast.BinOp(left=left, op=ast.BitOr() | ast.Add(), right=right):
            return (_value(left, names), _value(right, names))
        case _:
            return _UNKNOWN


def _holds_code(value: object, codes: frozenset[str]) -> bool:
    if isinstance(value, str):
        return value in codes
    if isinstance(value, Mapping):
        return any(_holds_code(key, codes) for key in value)
    if isinstance(value, tuple | list | set | frozenset):
        return any(_holds_code(element, codes) for element in value)
    return False


def _module(path: Path) -> ModuleType:
    parts = path.relative_to(ENGINE).with_suffix("").parts
    return importlib.import_module(".".join(("rozliczenia", *(part for part in parts if part != "__init__"))))


def _scoped(node: ast.AST, names: Mapping[str, object]) -> Iterator[tuple[ast.AST, Mapping[str, object]]]:
    """Węzły drzewa z nazwami, które w nich widać: w ciele klasy modułu ``self`` i ``cls`` to ta klasa."""

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            owner = names.get(child.name, _UNKNOWN) if isinstance(node, ast.Module) else _UNKNOWN
            yield from _scoped(child, {**names, "self": owner, "cls": owner})
        else:
            yield child, names
            yield from _scoped(child, names)


def _decisions_on_message_code(path: Path, codes: frozenset[str]) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node, names in _scoped(tree, vars(_module(path))):
        match node:
            case ast.Compare(left=left, comparators=comparators):
                operands = [left, *comparators]
            case ast.MatchValue(value=value):
                operands = [value]
            case _:
                continue
        if any(_holds_code(_value(operand, names), codes) for operand in operands):
            yield f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: {ast.unparse(node).splitlines()[0]}"


def test_kod_nie_porownuje_kodu_komunikatu() -> None:
    codes = _message_codes()
    found = [decision for path in sorted(ENGINE.rglob("*.py")) for decision in _decisions_on_message_code(path, codes)]

    assert not found, "\n".join(
        [
            *found,
            "Tylko katalog decyduje o kodzie Komunikatu, a kod nie wnioskuje z niego faktu: niech sprawdzenie albo "
            "plan odda typowany fakt, a katalog razem z Komunikatem to, co z niego wynika (np. "
            "update_messages.UpdateFailure).",
        ]
    )
