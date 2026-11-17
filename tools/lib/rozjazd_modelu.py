"""Rozjazd modelu skilla z kodem: czy kod, który opisuje model skilla, zmienił się od chwili, gdy ktoś potwierdził model.

Jedyne miejsce tej decyzji. W CI pyta ``rozjazd`` wykonanie zadania (``tools/ci/wykonaj_zadanie.py``) przed każdym
krokiem skilla z modelem i przy rozjeździe kończy krok porażką ``ROZJAZD`` bez uruchamiania; ``tools/szybko.py`` pyta to
samo dla skilli, których podstawę ``ci:`` zmiana uruchomiłaby na pull request, a skrypt sprawdzenia skilla tylko ostrzega.

Skill z modelem kodu ma plik ``DEFINICJE`` (``model/definicje.json``): ścieżka pliku od korzenia → nazwa definicji →
jej skrót z chwili, gdy model ją opisywał. Nazwa ``CALY_PLIK`` to cały plik (jego tekst z ujednoliconymi końcami linii),
a inna nazwa to ścieżka od modułu po kropkach (``create_app.disk``, ``Klasa.metoda``): każdy człon to funkcja, klasa albo
przypisanie w zakresie poprzedniego członu, także w jego ``if``, ``with`` i ``try``, a nie w zagnieżdżonej funkcji. Skrót
definicji liczy się z każdego jej wiązania w tym zakresie, z docstringiem, a bez położenia, więc przesunięte linie i kod
obok rozjazdem nie są. Rozjazd to skrót inny niż w pliku ``DEFINICJE`` albo definicja, której nie ma; porównanie nie
pyta gita, więc rebase i squash go nie zmieniają.

Skróty przelicza ``przesun`` (``tools/przesun_model.py``), dopiero gdy model znów opisuje kod. Rozjazdem jest też plik
definicji w innej postaci, bo model nie jest wtedy porównany z kodem. Rozjazd widzi tylko definicje z kluczem w pliku
``DEFINICJE``, więc ``bez_klucza`` mówi, które funkcje z tabeli modelu w ``SKILL.md`` skilla klucza nie mają.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

__all__ = ["CALY_PLIK", "DEFINICJE", "KROKI", "ROZJAZD", "TABELA", "bez_klucza", "definicje", "przesun", "rozjazd", "skille", "skroty"]

DEFINICJE = "model/definicje.json"
CALY_PLIK = "cały plik"
# Początek nagłówka sekcji ``SKILL.md`` skilla z krokami, które doprowadzają model do kodu.
KROKI = "Bring the model in line"
ROZJAZD = "ROZJAZD MODELU Z KODEM"
# Nagłówek sekcji ``SKILL.md`` skilla z tabelą, która wiąże model z kodem.
TABELA = "## Does the change touch it?"
# Długość skrótu w znakach szesnastkowych SHA-256: dość, by przypadkiem nie trafić tego samego skrótu.
DLUGOSC = 16

Skroty = dict[str, dict[str, str]]


def skille(root: Path) -> list[Path]:
    return sorted(path.parents[1] for path in (root / ".agents" / "skills").glob(f"*/{DEFINICJE}"))


def rozjazd(skill: Path, root: Path) -> str | None:
    """Czym kod opisany modelem skilla ``skill`` różni się od skrótów z jego ``DEFINICJE``, z krokami naprawy; ``None``,
    gdy niczym."""

    found = _found(skill, root)
    if found is None:
        return None
    steps = (skill / "SKILL.md").relative_to(root).as_posix()
    return f"{found} Wykonaj kroki „{KROKI}” z {steps}, a skróty przelicz (tools/przesun_model.py {skill.name}) dopiero, gdy model opisuje kod."


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


def bez_klucza(skill: Path, root: Path) -> list[str]:
    """Funkcje i metody, które tabela sekcji ``TABELA`` w ``SKILL.md`` skilla nazywa w `` ` ``, stojące w pliku z
    ``DEFINICJE``, bez klucza tam: ``"ścieżka nazwa"`` w kolejności tabeli. Rozjazd zmiany takiej funkcji nie widzi, choć
    model ją opisuje. ``SKILL.md`` bez tej sekcji to ``ValueError``.

    | Nazwa w wierszu tabeli | Przykład | Wynik |
    | --- | --- | --- |
    | funkcja modułu z pliku definicji | `enter_reports` | bez klucza `enter_reports`: zgłoszona |
    | metoda klasy | `ReportEnteringEntry.on_request` | bez klucza tej metody i klasy: zgłoszona |
    | z modułem z przodu | `_cells.with_added` | jak `with_added` w `_cells.py` (`__init__.py`: nazwa pakietu) |
    | z wywołaniem | `write_cells(...)`, `kept()` | jak nazwa bez nawiasów |
    | metoda bez klasy | `prepare`, `efenix.search` | nazwa bez definicji od modułu: jak `Klasa.prepare` każdej klasy |
    | metoda klasy z kluczem | `StateFile.retry` przy kluczu `StateFile` | przechodzi: skrót klasy obejmuje metodę |
    | funkcja pliku z `CALY_PLIK` | | przechodzi |
    | nazwa w dwóch plikach definicji | `_case` z kluczem w jednym z nich | przechodzi |

    Granice, które przechodzą bez klucza: klasa, stała i przypisanie (`ClickResult`, `RETRY_S`), zaślepka bez ciała
    poza docstringiem i ``...`` (metoda ``Protocol``, `OrderJournal.ended`), także gdy inna klasa ma metodę o tej nazwie
    z ciałem, nazwa obiektu przed funkcją modułu (`pliki.zapisz()` to tylko metoda `zapisz`), definicja w pliku spoza
    ``DEFINICJE`` (`onedrive_conflicts.beside`), nazwa w prozie sekcji poza tabelą, nazwa w tabeli innej sekcji i każda
    nazwa skilla, którego sekcja nie ma tabeli, bo model wiąże z kodem proza albo komentarze modelu TLA+
    (`verify-urwane-uruchomienie`).
    """

    recorded = definicje(skill)
    trees = {path: _tree((root / path).read_text(encoding="utf-8")) for path, names in recorded.items() if CALY_PLIK not in names}
    missing: list[str] = []
    for span in _table_spans((skill / "SKILL.md").read_text(encoding="utf-8")):
        name = span.split("(", 1)[0] if span.endswith(")") else span
        if not all(part.isidentifier() for part in name.split(".")):
            continue
        bound = [(path, inner, nodes) for path, tree in trees.items() for inner in _in_module(path, name) if (nodes := _nodes(tree, inner))]
        if not bound:
            method = name.rsplit(".", 1)[-1]
            bound = [(path, f"{cls}.{method}", nodes) for path, tree in trees.items() for cls in _classes(tree) if (nodes := _nodes(tree, f"{cls}.{method}"))]
        found = [(path, inner) for path, inner, nodes in bound if _is_function(nodes)]
        if found and not any(_keyed(recorded[path], inner) for path, inner in found):
            missing += [f"{path} {inner}" for path, inner in found if f"{path} {inner}" not in missing]
    return missing


def _keyed(names: dict[str, str], name: str) -> bool:
    """Czy ``name`` albo zakres, w którym stoi (klasa metody), ma klucz w ``names``: skrót zakresu obejmuje ``name``."""

    parts = name.split(".")
    return any(".".join(parts[:end]) in names for end in range(1, len(parts) + 1))


def _classes(tree: ast.Module | None) -> list[str]:
    return [] if tree is None else list(dict.fromkeys(node.name for node in _statements(tree) if isinstance(node, ast.ClassDef)))


def _table_spans(text: str) -> list[str]:
    lines = text.splitlines()
    if TABELA not in lines:
        raise ValueError(f"SKILL.md nie ma sekcji „{TABELA}”")
    rows: list[str] = []
    for line in lines[lines.index(TABELA) + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append(line)
    return [span for row in rows for span in row.split("`")[1::2]]


def _in_module(path: str, name: str) -> list[str]:
    """Ścieżki od modułu, które ``name`` może znaczyć w pliku ``path``: sama nazwa i bez członu modułu z przodu."""

    file = Path(path)
    module = file.parent.name if file.name == "__init__.py" else file.stem
    head, _, rest = name.partition(".")
    return [name, rest] if head == module and rest else [name]


def _is_function(nodes: list[ast.stmt]) -> bool:
    """Czy wiązania ``nodes`` jednej nazwy to funkcja albo metoda z ciałem: każde to ``def``, a jedno ma coś poza
    docstringiem i ``...``."""

    functions = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return bool(nodes) and len(functions) == len(nodes) and any(not _stub(function) for function in functions)


def _stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and (node.value.value is ... or isinstance(node.value.value, str)) for node in function.body)


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

    nodes = _nodes(tree, name)
    return _digest("\n".join(_canonical(node) for node in nodes)) if nodes else None


def _nodes(tree: ast.Module | None, name: str) -> list[ast.stmt]:
    """Wiązania definicji ``name`` (ścieżka po kropkach od modułu) w ``tree``; pusta lista, gdy jej nie ma."""

    if tree is None:
        return []
    scopes: list[ast.AST] = [tree]
    nodes: list[ast.stmt] = []
    for part in name.split("."):
        nodes = [node for scope in scopes for node in _bindings(scope, part)]
        scopes = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return nodes


def _bindings(scope: ast.AST, name: str) -> list[ast.stmt]:
    """Funkcje, klasy i przypisania ``name`` w zakresie ``scope``, w kolejności kodu."""

    return [node for node in _statements(scope) if _binds(node, name)]


def _binds(node: ast.stmt, name: str) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == name
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return any(isinstance(target, ast.Name) and target.id == name for target in targets)


def _statements(scope: ast.AST) -> list[ast.stmt]:
    """Instrukcje zakresu ``scope`` w kolejności kodu, także w jego instrukcjach złożonych, bez wnętrza zagnieżdżonych
    funkcji i klas."""

    found: list[ast.stmt] = []
    pending = list(reversed(_body(scope)))
    while pending:
        node = pending.pop()
        found.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pending += reversed(_body(node))
    return found


def _body(node: ast.AST) -> list[ast.stmt]:
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
