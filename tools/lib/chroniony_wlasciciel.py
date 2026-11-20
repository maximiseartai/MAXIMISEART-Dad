from __future__ import annotations

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
| zakaz ``TID251`` | plik z ``TID251`` w ``[lint.per-file-ignores]`` ``ruff.toml`` korzenia; że ma wiersz ``OWNERS`` z nazwami, których jest właścicielem, pilnuje ``tests/test_zakazy_ruff.py`` w Required CI tego drzewa |
| nazwa w ``banned-api`` | moduł, który ją definiuje (``def``, ``class`` albo przypisanie na początku linii), jako ``<katalog importu>/<moduł>.py`` albo ``…/__init__.py`` z katalogów ``src`` i ``repo.IMPORT_ROOTS``: zakaz kieruje do niego resztę kodu |
| sama reguła | ``ruff.toml`` korzenia z ``banned-api`` i każdy plik reguły ast-grep z ``ruleDirs``, który ma ``id``: lukę we wzorcu albo zasięgu zamyka test jego próbek (``tests/test_zakazy_ruff.py``, ``tests/test_zapadki.py``), a słabszą regułę odrzuca warunek 6 ``tools/scal_pr.py`` |
| kontrakt importów | moduł z ``allowed_importers`` kontraktu ``.importlinter`` jako plik ``src/<moduł>.py`` albo ``src/<moduł>/__init__.py`` |
| reguła ast-grep | plik z ``ignores:`` reguły z katalogu ``ruleDirs`` ``sgconfig.yml`` |

Wpis z ``{a,b}`` daje każdą ścieżkę z nawiasu. Właścicielem jest tylko plik, którego ścieżkę wpis podaje wprost, więc
wpis ze wzorcem (``src/**``) albo katalog to zasięg reguły, nie właściciel, a konfiguracja, której narzędzie nie wczyta,
nie daje właściciela.
"""

RUFF = "ruff.toml"
BAN = "TID251"
IMPORT_CONTRACTS = ".importlinter"
CONTRACT = "importlinter:contract:"
ALLOWED = "allowed_importers"
PACKAGES = "src"
AST_GREP = "sgconfig.yml"
IMPORT_ROOTS = (PACKAGES, *repo.IMPORT_ROOTS)
SOURCES = (
    f"{BAN} w per-file-ignores {RUFF} z wierszem OWNERS w tests/test_zakazy_ruff.py, moduł nazwy z banned-api, {ALLOWED} kontraktu w {IMPORT_CONTRACTS}, "
    f"ignores: reguły ast-grep z ruleDirs {AST_GREP}, sam plik takiej reguły albo {RUFF} z banned-api"
)
_BRACES = re.compile(r"\{([^{}]*)\}")
_UNREADABLE = (tomllib.TOMLDecodeError, configparser.Error, yaml.YAMLError, UnicodeDecodeError)


@dataclass(frozen=True)
class _Tree:
    root: Path
    tree: str
    files: frozenset[str]

    def read(self, path: str) -> str | None:
        return repo.git(self.root, "cat-file", "blob", f"{self.tree}:{path}") if path in self.files else None


def owners(root: Path, tree: str) -> frozenset[str]:
    listed = _Tree(root, tree, frozenset(repo.git(root, "ls-tree", "-r", "-z", "--name-only", tree).split("\0")) - {""})
    return frozenset({*_banned(listed), *_importers(listed), *_ignored(listed)})


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
    if (config := tree.read(RUFF)) is None:
        return set()
    try:
        lint = tomllib.loads(config).get("lint", {})
    except _UNREADABLE:
        return set()
    ignores = lint.get("per-file-ignores", {})
    names = lint.get("flake8-tidy-imports", {}).get("banned-api", {})
    exempt = {path for pattern, codes in ignores.items() if isinstance(codes, list) and BAN in codes for path in _paths(pattern)}
    return exempt | {path for name in names for path in _defining(tree, name)} | ({RUFF} if names else set())


def _defining(tree: _Tree, banned: str) -> Iterator[str]:
    module, _, name = banned.rpartition(".")
    defined = re.compile(rf"^(?:(?:async +)?def +|class +)?{re.escape(name)}\b", re.MULTILINE)
    stem = module.replace(".", "/")
    candidates = (f"{root}/{stem}{suffix}".removeprefix("./") for root in IMPORT_ROOTS for suffix in (".py", "/__init__.py"))
    yield from (path for path in candidates if defined.search(tree.read(path) or ""))


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
    return {path for module in modules for path in (f"{PACKAGES}/{module.replace('.', '/')}.py", f"{PACKAGES}/{module.replace('.', '/')}/__init__.py")}


def _ignored(tree: _Tree) -> set[str]:
    if (text := tree.read(AST_GREP)) is None:
        return set()
    try:
        directories = [str(directory).rstrip("/") for directory in (yaml.safe_load(text) or {}).get("ruleDirs") or []]
    except (*_UNREADABLE, AttributeError):
        return set()
    rules = {path: _documents(tree.read(path) or "") for path in tree.files if path.endswith((".yml", ".yaml")) and any(path.startswith(f"{directory}/") for directory in directories)}
    ignored = {path for documents in rules.values() for document in documents for path in _rule_ignores(document)}
    return ignored | {rule for rule, documents in rules.items() if any(isinstance(document, dict) and "id" in document for document in documents)}


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
    else:
        yield pattern
