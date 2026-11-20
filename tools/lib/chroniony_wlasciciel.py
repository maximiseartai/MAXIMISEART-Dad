from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
import configparser
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Any

import yaml

import repo

ZASADY = """Chroniony właściciel (ADR 0046, „Właściciel”): plik, który konfiguracja reguł w drzewie (HEAD PR scalony z bazą)
wskazuje jako właściciela, więc jego jedyność pilnuje zakaz albo reguła, a szczebel ``test`` zamyka test na nim:

| Źródło | Właściciel |
|---|---|
| zakaz ``TID251`` | plik z ``TID251`` w ``[lint.per-file-ignores]`` ``ruff.toml`` korzenia i z wierszem ``OWNERS`` w ``tests/test_zakazy_ruff.py`` naraz |
| kontrakt importów | moduł z ``allowed_importers`` kontraktu ``.importlinter`` jako plik ``src/<moduł>.py`` albo ``src/<moduł>/__init__.py`` |
| reguła ast-grep | plik z ``ignores:`` reguły z katalogu ``ruleDirs`` ``sgconfig.yml`` |

Wpis z ``{a,b}`` daje każdą ścieżkę z nawiasu, a wpis z ``*``, ``?``, ``[`` albo ``!`` to zasięg reguły, nie właściciel,
tak jak katalog. Ścieżka, której w drzewie nie ma, i konfiguracja, której narzędzie nie wczyta, nie dają właściciela.
"""

RUFF = "ruff.toml"
OWNERS_TEST = "tests/test_zakazy_ruff.py"
OWNERS = "OWNERS"
BAN = "TID251"
IMPORT_CONTRACTS = ".importlinter"
CONTRACT = "importlinter:contract:"
ALLOWED = "allowed_importers"
PACKAGES = "src"
AST_GREP = "sgconfig.yml"
SOURCES = (
    f"{BAN} w per-file-ignores {RUFF} razem z wierszem {OWNERS} w {OWNERS_TEST}, {ALLOWED} kontraktu w {IMPORT_CONTRACTS} "
    f"albo ignores: reguły ast-grep z ruleDirs {AST_GREP}"
)
_BRACES = re.compile(r"\{([^{}]*)\}")
_WILDCARD = re.compile(r"[*?\[!]")
_UNREADABLE = (tomllib.TOMLDecodeError, SyntaxError, configparser.Error, yaml.YAMLError, UnicodeDecodeError)


@dataclass(frozen=True)
class _Tree:
    root: Path
    tree: str
    files: frozenset[str]

    def read(self, path: str) -> str | None:
        return repo.git(self.root, "cat-file", "blob", f"{self.tree}:{path}") if path in self.files else None


def owners(root: Path, tree: str) -> frozenset[str]:
    listed = _Tree(root, tree, frozenset(repo.git(root, "ls-tree", "-r", "-z", "--name-only", tree).split("\0")) - {""})
    found = {*_banned(listed), *_importers(listed), *_ignored(listed)}
    return frozenset(found & listed.files)


def refusal(files: Sequence[str], protected: frozenset[str]) -> str | None:
    outside = [path for path in dict.fromkeys(files) if path not in protected]
    if files and not outside:
        return None
    named = ", ".join(outside) if outside else "Gdzie bez miejsca plik:linia w repo"
    return (
        f"Mechanizm: test przyjmuje Strażnik: pytest tylko na chronionym właścicielu, a {named} nim nie jest w konfiguracji reguł HEAD "
        f"scalonego z bazą ({SOURCES}); właściciel bez tej ochrony to szczebel architektura: dopisz w tym PR zakaz TID251 albo regułę "
        "ast-grep, która kieruje resztę kodu do właściciela, z jego prawem właściciela w tej konfiguracji, albo daj strażnika mypy, "
        "ruff lub ast-grep <id>"
    )


def _banned(tree: _Tree) -> set[str]:
    config, test = tree.read(RUFF), tree.read(OWNERS_TEST)
    if config is None or test is None:
        return set()
    try:
        ignores = tomllib.loads(config).get("lint", {}).get("per-file-ignores", {})
        rows = _owner_rows(ast.parse(test))
    except _UNREADABLE:
        return set()
    exempt = {path for pattern, codes in ignores.items() if isinstance(codes, list) and BAN in codes for path in _paths(pattern)}
    return exempt & rows


def _owner_rows(module: ast.Module) -> set[str]:
    for node in module.body:
        targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if any(isinstance(target, ast.Name) and target.id == OWNERS for target in targets) and isinstance(value, ast.Dict):
            return {key.value for key in value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


def _importers(tree: _Tree) -> set[str]:
    if (text := tree.read(IMPORT_CONTRACTS)) is None:
        return set()
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except _UNREADABLE:
        return set()
    modules = {
        line.strip() for section in parser.sections() if section.startswith(CONTRACT) for line in parser.get(section, ALLOWED, fallback="").splitlines() if line.strip()
    }
    return {
        path
        for module in modules
        if not _WILDCARD.search(module)
        for path in (f"{PACKAGES}/{module.replace('.', '/')}.py", f"{PACKAGES}/{module.replace('.', '/')}/__init__.py")
    }


def _ignored(tree: _Tree) -> set[str]:
    if (text := tree.read(AST_GREP)) is None:
        return set()
    try:
        directories = [str(directory).rstrip("/") for directory in (yaml.safe_load(text) or {}).get("ruleDirs") or []]
    except (*_UNREADABLE, AttributeError):
        return set()
    rules = sorted(path for path in tree.files if path.endswith((".yml", ".yaml")) and any(path.startswith(f"{directory}/") for directory in directories))
    return {path for rule in rules for document in _documents(tree.read(rule) or "") for path in _rule_ignores(document)}


def _documents(text: str) -> list[Any]:
    try:
        return list(yaml.safe_load_all(text))
    except _UNREADABLE:
        return []


def _rule_ignores(document: Any) -> Iterator[str]:
    patterns = document.get("ignores") if isinstance(document, dict) else None
    for pattern in patterns if isinstance(patterns, list) else []:
        if isinstance(pattern, str):
            yield from _paths(pattern)


def _paths(pattern: str) -> Iterator[str]:
    if found := _BRACES.search(pattern):
        for choice in found[1].split(","):
            yield from _paths(pattern[: found.start()] + choice + pattern[found.end() :])
    elif not _WILDCARD.search(pattern):
        yield pattern
