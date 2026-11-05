"""Rozjazd modelu skilla z kodem: czy kod, który opisuje model TLA+ skilla, zmienił się od Sync commit z jego ``SKILL.md``.

Jedyne miejsce tej decyzji. Skrypt sprawdzenia modelu skilla pyta ``rozjazd`` przed TLC (w CI rozjazd kończy go
porażką), a ``tools/szybko.py`` pyta to samo dla skilli, których podstawę ``ci:`` zmiana uruchomiłaby na pull request.

Skill z modelem kodu ma plik ``DEFINICJE`` (``model/definicje.json``): ścieżka pliku od korzenia → lista nazw definicji
albo napis ``CALY_PLIK``. Nazwa to pierwsza funkcja (także zagnieżdżona), klasa albo przypisanie o tej nazwie, a
``Klasa.metoda`` to metoda tej klasy. Definicja zmieniła się, gdy jej drzewo składni bez położenia (``ast.dump``, więc
z docstringiem, a bez numerów linii) różni się od tego w Sync commit albo gdy jej nie ma; cały plik zmienił się, gdy
``git diff`` z Sync commit go wymienia. Sync commit to pierwsza linia ``Sync commit: `<sha>``` w ``SKILL.md``.

Rozjazdem jest też ``SKILL.md`` bez Sync commit, Sync commit spoza historii i plik definicji w innej postaci, bo model
nie jest wtedy porównany z kodem. Płytki klon bez Sync commit (CI) dopobiera historię, gdy ``dopobierz``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess

__all__ = ["CALY_PLIK", "DEFINICJE", "KROKI", "SYNC", "definicje", "rozjazd", "skille"]

DEFINICJE = "model/definicje.json"
CALY_PLIK = "cały plik"
# Początek nagłówka sekcji ``SKILL.md`` skilla z krokami, które przesuwają Sync commit.
KROKI = "Bring the model in line"
SYNC = re.compile(r"Sync commit: `([0-9a-f]{7,40})`")
# Dopobranie historii płytkiego klonu CI (ok. 33 MiB) nie czeka do limitu czasu runnera.
FETCH_TIMEOUT_S = 300


def skille(root: Path) -> list[Path]:
    """Foldery skilli z plikiem ``DEFINICJE``, posortowane."""

    return sorted(path.parents[1] for path in (root / ".agents" / "skills").glob(f"*/{DEFINICJE}"))


def rozjazd(skill: Path, root: Path, *, dopobierz: bool = False) -> str | None:
    """Czym kod opisany modelem skilla ``skill`` różni się od Sync commit, z krokami naprawy; ``None``, gdy niczym."""

    found = _found(skill, root, dopobierz)
    if found is None:
        return None
    steps = (skill / "SKILL.md").relative_to(root).as_posix()
    return f"{found} Wykonaj kroki „{KROKI}” z {steps}, a Sync commit przesuń dopiero, gdy model opisuje kod."


def _found(skill: Path, root: Path, dopobierz: bool) -> str | None:
    sync = SYNC.search((skill / "SKILL.md").read_text(encoding="utf-8"))
    if sync is None:
        return "SKILL.md nie ma Sync commit."
    try:
        definitions = definicje(skill)
    except ValueError as error:
        return f"{(skill / DEFINICJE).relative_to(root).as_posix()}: {error}."
    commit = f"{sync[1]}^{{commit}}"
    if _git(root, "cat-file", "-e", commit) is None and dopobierz:
        # W pełnym klonie ``--unshallow`` pada i niczego nie zmienia.
        _git(root, "fetch", "--quiet", "--unshallow", "origin", timeout_s=FETCH_TIMEOUT_S)
    if _git(root, "cat-file", "-e", commit) is None:
        if _git(root, "rev-parse", "--is-shallow-repository") != "true":
            return f"Sync commit {sync[1]} nie ma w tej historii; pobierz go albo porównaj kod ręcznie."
        if dopobierz:
            return f"nie udało się dopobrać historii do Sync commit {sync[1]} (git fetch --unshallow); sprawdź sieć."
        return f"Sync commit {sync[1]} nie ma w płytkim klonie; dopobierz historię: git fetch --unshallow origin."
    whole = [path for path, names in definitions.items() if names is None]
    diff = _git(root, "diff", "--name-only", sync[1], "--", *whole) if whole else ""
    if diff is None:
        return f"git diff z Sync commit {sync[1]} się nie udał; porównaj kod ręcznie."
    changed = diff.split()
    for path, names in definitions.items():
        if names is not None:
            then, now = _tree(_git(root, "show", f"{sync[1]}:{path}")), _tree(_read(root / path))
            changed += [f"{path} {name}" for name in names if (found := _definition(now, name)) is None or found != _definition(then, name)]
    if not changed:
        return None
    return f"kod opisany modelem zmienił się od {sync[1]}: {', '.join(changed)}."


def definicje(skill: Path) -> dict[str, tuple[str, ...] | None]:
    """Plik ``DEFINICJE`` skilla: ścieżka → nazwy definicji albo ``None`` dla ``CALY_PLIK``; inna postać to ``ValueError``."""

    try:
        loaded = json.loads((skill / DEFINICJE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"nie da się odczytać ({error})") from error
    if not isinstance(loaded, dict) or not loaded:
        raise ValueError("to nie jest niepusty obiekt ścieżka → definicje")
    found: dict[str, tuple[str, ...] | None] = {}
    for name, names in loaded.items():
        if names == CALY_PLIK:
            found[name] = None
        elif isinstance(names, list) and names and all(isinstance(each, str) and each for each in names):
            found[name] = tuple(names)
        else:
            raise ValueError(f"{name} ma {names!r}, a nie listę nazw definicji albo „{CALY_PLIK}”")
    return found


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _tree(source: str | None) -> ast.Module | None:
    """Drzewo składni ``source``; ``None``, gdy pliku nie ma albo się nie parsuje (każda jego definicja się zmieniła)."""

    if source is None:
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _definition(tree: ast.Module | None, name: str) -> str | None:
    """Definicja ``name`` w ``tree`` bez położenia: ``Klasa.metoda`` to metoda klasy, a inna nazwa to pierwsza funkcja
    (także zagnieżdżona), klasa albo przypisanie o tej nazwie."""

    if tree is None:
        return None
    if "." in name:
        owner, member = name.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == owner and (found := _named(node.body, member)) is not None:
                return found
        return None
    return next((found for node in ast.walk(tree) if (found := _named([node], name)) is not None), None)


def _named(nodes: list[ast.stmt] | list[ast.AST], name: str) -> str | None:
    """Pierwsza z ``nodes``, która definiuje ``name`` (funkcja, klasa albo przypisanie), bez położenia."""

    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return ast.dump(node)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.dump(node)
    return None


def _git(root: Path, *arguments: str, timeout_s: float | None = None) -> str | None:
    """Wyjście polecenia ``git`` bez końcowych białych znaków; ``None``, gdy się nie udało albo minęło ``timeout_s``."""

    try:
        done = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None
    return done.stdout.strip() if done.returncode == 0 else None
