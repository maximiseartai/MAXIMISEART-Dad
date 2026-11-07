"""Rozjazd modelu skilla z kodem: czy kod, który opisuje model skilla, zmienił się od chwili, gdy ktoś potwierdził model.

Jedyne miejsce tej decyzji. Skrypt sprawdzenia skilla pyta ``rozjazd`` przed sprawdzeniem (w CI rozjazd kończy go
porażką, ``porazka_w_ci``), a ``tools/szybko.py`` pyta to samo dla skilli, których podstawę ``ci:`` zmiana uruchomiłaby
na pull request.

Skill z modelem kodu ma plik ``DEFINICJE`` (``model/definicje.json``): ścieżka pliku od korzenia → nazwa definicji →
jej skrót z chwili, gdy model ją opisywał. Nazwa ``CALY_PLIK`` to cały plik (jego tekst z ujednoliconymi końcami linii),
a inna nazwa to ścieżka od modułu po kropkach (``create_app.disk``, ``Klasa.metoda``): każdy człon to funkcja, klasa albo
przypisanie w zakresie poprzedniego członu, także w jego ``if``, ``with`` i ``try``, a nie w zagnieżdżonej funkcji. Skrót
definicji liczy się z każdego jej wiązania w tym zakresie, z docstringiem, a bez położenia, więc przesunięte linie i kod
obok rozjazdem nie są. Rozjazd to skrót inny niż w pliku ``DEFINICJE`` albo definicja, której nie ma; porównanie nie
pyta gita, więc rebase i squash go nie zmieniają.

Skróty przelicza ``przesun`` (``tools/przesun_model.py``), dopiero gdy model znów opisuje kod. Rozjazdem jest też plik
definicji w innej postaci, bo model nie jest wtedy porównany z kodem.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

__all__ = ["CALY_PLIK", "DEFINICJE", "KROKI", "ROZJAZD", "definicje", "porazka_w_ci", "przesun", "rozjazd", "skille", "skroty"]

DEFINICJE = "model/definicje.json"
CALY_PLIK = "cały plik"
# Początek nagłówka sekcji ``SKILL.md`` skilla z krokami, które doprowadzają model do kodu.
KROKI = "Bring the model in line"
ROZJAZD = "ROZJAZD MODELU Z KODEM"
# Długość skrótu w znakach szesnastkowych SHA-256: dość, by przypadkiem nie trafić tego samego skrótu.
DLUGOSC = 16

Skroty = dict[str, dict[str, str]]


def skille(root: Path) -> list[Path]:
    """Foldery skilli z plikiem ``DEFINICJE``, posortowane."""

    return sorted(path.parents[1] for path in (root / ".agents" / "skills").glob(f"*/{DEFINICJE}"))


def rozjazd(skill: Path, root: Path) -> str | None:
    """Czym kod opisany modelem skilla ``skill`` różni się od skrótów z jego ``DEFINICJE``, z krokami naprawy; ``None``,
    gdy niczym."""

    found = _found(skill, root)
    if found is None:
        return None
    steps = (skill / "SKILL.md").relative_to(root).as_posix()
    return f"{found} Wykonaj kroki „{KROKI}” z {steps}, a skróty przelicz (tools/przesun_model.py {skill.name}) dopiero, gdy model opisuje kod."


def porazka_w_ci(drift: str | None, werdykt: str) -> str | None:
    """Tekst, którym skrypt skilla kończy się porażką w CI (``GITHUB_ACTIONS=true``) przy rozjeździe ``drift``; ``None``
    bez rozjazdu albo poza CI, gdzie skrypt sprawdza dalej i tylko ostrzega."""

    if drift is None or os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    return f"UWAGA: {drift}\n\n{werdykt}: {ROZJAZD}"


def _found(skill: Path, root: Path) -> str | None:
    try:
        recorded = definicje(skill)
    except ValueError as error:
        return f"{(skill / DEFINICJE).relative_to(root).as_posix()}: {error}."
    now = skroty(recorded, root)
    changed = [
        path if name == CALY_PLIK else f"{path} {name}"
        for path, names in recorded.items()
        for name, digest in names.items()
        if now[path][name] != digest
    ]
    if not changed:
        return None
    return f"kod opisany modelem zmienił się: {', '.join(changed)}."


def definicje(skill: Path) -> Skroty:
    """Plik ``DEFINICJE`` skilla: ścieżka → nazwa definicji → skrót; inna postać to ``ValueError``."""

    try:
        loaded = json.loads((skill / DEFINICJE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"nie da się odczytać ({error})") from error
    if not isinstance(loaded, dict) or not loaded:
        raise ValueError("to nie jest niepusty obiekt ścieżka → definicje")
    for path, names in loaded.items():
        if not isinstance(names, dict) or not names or not all(isinstance(name, str) and name and isinstance(digest, str) for name, digest in names.items()):
            raise ValueError(f"{path} ma {names!r}, a nie niepusty obiekt nazwa definicji → skrót")
        if CALY_PLIK in names and len(names) > 1:
            raise ValueError(f"{path} ma „{CALY_PLIK}” obok nazw definicji")
    return loaded


def skroty(recorded: Skroty, root: Path) -> dict[str, dict[str, str | None]]:
    """Skróty kodu w ``root`` dla ścieżek i nazw z ``recorded``; ``None``, gdy pliku albo definicji nie ma."""

    found: dict[str, dict[str, str | None]] = {}
    for path, names in recorded.items():
        file = root / path
        source = file.read_text(encoding="utf-8") if file.is_file() else None
        tree = _tree(source)
        found[path] = {name: _digest(source) if name == CALY_PLIK else _definition(tree, name) for name in names}
    return found


def przesun(skill: Path, root: Path) -> list[str]:
    """Zapisuje w ``DEFINICJE`` skilla skróty kodu z ``root`` i zwraca zmienione definicje; definicja, której nie ma, albo
    plik definicji w innej postaci to ``ValueError`` bez zapisu."""

    recorded = definicje(skill)
    now = skroty(recorded, root)
    missing = [f"{path} {name}" for path, names in now.items() for name, digest in names.items() if digest is None]
    if missing:
        raise ValueError(f"nie ma definicji: {', '.join(missing)}; popraw nazwy w {DEFINICJE}")
    moved = [f"{path} {name}" for path, names in recorded.items() for name, digest in names.items() if now[path][name] != digest]
    (skill / DEFINICJE).write_text(json.dumps(now, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    return moved


def _tree(source: str | None) -> ast.Module | None:
    """Drzewo składni ``source``; ``None``, gdy pliku nie ma albo się nie parsuje (każda jego definicja się zmieniła)."""

    if source is None:
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _definition(tree: ast.Module | None, name: str) -> str | None:
    """Skrót definicji ``name`` (ścieżka po kropkach od modułu) w ``tree``; ``None``, gdy jej nie ma."""

    if tree is None:
        return None
    scopes: list[ast.AST] = [tree]
    nodes: list[ast.stmt] = []
    for part in name.split("."):
        nodes = [node for scope in scopes for node in _bindings(scope, part)]
        scopes = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return _digest("\n".join(_canonical(node) for node in nodes)) if nodes else None


def _bindings(scope: ast.AST, name: str) -> list[ast.stmt]:
    """Funkcje, klasy i przypisania ``name`` w zakresie ``scope``, w kolejności kodu, także w jego instrukcjach złożonych,
    bez zagnieżdżonych funkcji i klas."""

    found: list[ast.stmt] = []
    pending = list(reversed(_body(scope)))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                found.append(node)
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            found.append(node)
        pending += reversed(_body(node))
    return found


def _body(node: ast.AST) -> list[ast.stmt]:
    """Instrukcje bezpośrednio w ``node``: jego ciało i gałęzie (``orelse``, ``finalbody``, ``except``, ``case``)."""

    children: list[ast.stmt] = []
    for field in ("body", "orelse", "finalbody", "handlers", "cases"):
        for child in getattr(node, field, None) or []:
            children += child.body if isinstance(child, (ast.ExceptHandler, ast.match_case)) else [child]
    return children


def _canonical(node: object) -> str:
    """Postać drzewa bez położenia i bez pól ``None`` albo pustych list, ta sama w każdej wersji Pythona, która to drzewo
    parsuje: ``ast.dump`` od Pythona 3.13 sam pomija takie pola, a nowe pola węzłów (``type_params`` z 3.12) są puste w
    kodzie, który ich nie używa."""

    if isinstance(node, ast.AST):
        fields = ", ".join(f"{field}={_canonical(value)}" for field, value in ast.iter_fields(node) if value is not None and value != [])
        return f"{type(node).__name__}({fields})"
    if isinstance(node, list):
        return f"[{', '.join(_canonical(each) for each in node)}]"
    return repr(node)


def _digest(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()[:DLUGOSC]
