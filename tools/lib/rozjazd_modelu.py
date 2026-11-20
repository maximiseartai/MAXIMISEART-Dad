"""Rozjazd modelu skilla z kodem: czy kod, który opisuje model skilla, zmienił się od chwili, gdy ktoś potwierdził model.

Jedyne miejsce tej decyzji. W CI pyta ``rozjazd`` wykonanie zadania (``tools/ci/wykonaj_zadanie.py``) przed każdym
krokiem skilla z modelem i przy rozjeździe kończy krok porażką ``ROZJAZD`` bez uruchamiania; ``tools/szybko.py`` pyta to
samo dla skilli, których podstawę ``ci:`` zmiana uruchomiłaby na pull request, a skrypt sprawdzenia skilla tylko ostrzega.

Skill z modelem kodu ma plik ``DEFINICJE`` (``model/definicje.json``): ścieżka pliku od korzenia → nazwa definicji → jej
skrót z chwili, gdy model ją opisywał. Nazwa ``CALY_PLIK`` to cały plik: plik Pythona z drzewa składni, a inny jego
tekst z ujednoliconymi końcami linii. Inna nazwa to ścieżka od modułu po kropkach (``create_app.disk``,
``Klasa.metoda``): każdy człon to funkcja, klasa albo przypisanie w zakresie poprzedniego członu, także w jego ``if``,
``with`` i ``try``, a nie w zagnieżdżonej funkcji. Skrót definicji liczy się z każdego jej wiązania w tym zakresie.
Skrót z drzewa składni nie zna położenia, komentarzy ani docstringów, więc przesunięte linie, kod obok i proza rozjazdem
nie są. Rozjazd to skrót inny niż w pliku ``DEFINICJE`` albo definicja, której nie ma; porównanie nie pyta gita, więc
rebase i squash go nie zmieniają.

Skróty przelicza ``przesun`` (``tools/przesun_model.py``), dopiero gdy model znów opisuje kod. Rozjazdem jest też plik
definicji w innej postaci, bo model nie jest wtedy porównany z kodem. Rozjazd widzi tylko definicje z kluczem w pliku
``DEFINICJE``, więc ``bez_klucza`` mówi, które funkcje z tabeli modelu w ``SKILL.md`` skilla klucza nie mają.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re

__all__ = ["CALY_PLIK", "DEFINICJE", "KROKI", "ROZJAZD", "TABELA", "bez_klucza", "definicje", "przesun", "rozjazd", "scal", "skille", "skroty", "wiersze_tabeli"]

DEFINICJE = "model/definicje.json"
CALY_PLIK = "cały plik"
# Początek nagłówka sekcji ``SKILL.md`` skilla z krokami, które doprowadzają model do kodu.
KROKI = "Bring the model in line"
ROZJAZD = "ROZJAZD MODELU Z KODEM"
# Nagłówek sekcji ``SKILL.md`` skilla z tabelą, która wiąże model z kodem.
TABELA = "## Does the change touch it?"
KOD = ("src", "tools")
# Długość skrótu w znakach szesnastkowych SHA-256: dość, by przypadkiem nie trafić tego samego skrótu.
DLUGOSC = 16

Skroty = dict[str, dict[str, str]]


def skille(root: Path) -> list[Path]:
    return sorted(path.parents[1] for path in (root / ".agents" / "skills").glob(f"*/{DEFINICJE}"))


def rozjazd(skill: Path, root: Path) -> str | None:
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
        text = (skill / DEFINICJE).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"nie da się odczytać ({error})") from error
    return _parsed(text)


def _parsed(text: str) -> Skroty:
    try:
        loaded = json.loads(text)
    except ValueError as error:
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
        tree = _tree(source) if path.endswith(".py") else None
        found[path] = {name: _whole_file(source, tree) if name == CALY_PLIK else _definition(tree, name) for name in names}
    return found


def _whole_file(source: str | None, tree: ast.Module | None) -> str | None:
    return _digest(source) if tree is None else _digest(_canonical(tree))


def przesun(skill: Path, root: Path) -> list[str]:
    recorded = definicje(skill)
    now = skroty(recorded, root)
    missing = [f"{path} {name}" for path, names in now.items() for name, digest in names.items() if digest is None]
    if missing:
        raise ValueError(f"nie ma definicji: {', '.join(missing)}; popraw nazwy w {DEFINICJE}")
    moved = [f"{path} {name}" for path, names in recorded.items() for name, digest in names.items() if now[path][name] != digest]
    (skill / DEFINICJE).write_text(json.dumps(now, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    return moved


def scal(base: Path, ours: Path, theirs: Path, merge_tree: Callable[[list[str]], Path | None]) -> list[str]:
    old, mine, other = (_side(name, file) for name, file in (("bazy", base), ("nasza", ours), ("ich", theirs)))
    if _keys(other) in (_keys(mine), _keys(old)):
        kept = mine
    elif _keys(mine) == _keys(old):
        kept = other
    else:
        raise ValueError("obie strony zmieniły definicje modelu inaczej")
    merged = {path: {name: _one_side(mine, other, old, path, name) for name in names} for path, names in kept.items()}
    both = {path: dict.fromkeys(missing, "") for path, names in merged.items() if (missing := [name for name, digest in names.items() if digest is None])}
    if both:
        root = merge_tree(list(both))
        found = skroty(both, root) if root is not None else {}
        for path, names in both.items():
            for name in names:
                if (digest := found.get(path, {}).get(name)) is None:
                    raise ValueError(f"obie strony zmieniły skrót {path} {name}, a drzewo scalenia nie ma tej definicji bez konfliktu")
                merged[path][name] = digest
    ours.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    return [f"{path} {name}" for path, names in both.items() for name in names]


def _side(name: str, file: Path) -> Skroty:
    try:
        return _parsed(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"definicje {name}: {error}") from error


def _keys(recorded: Skroty) -> dict[str, set[str]]:
    return {path: set(names) for path, names in recorded.items()}


def _one_side(mine: Skroty, other: Skroty, old: Skroty, path: str, name: str) -> str | None:
    now, then, before = (side.get(path, {}).get(name) for side in (mine, other, old))
    if then in (now, before):
        return now
    return then if now == before else None


def bez_klucza(skill: Path, root: Path) -> list[str]:
    """Funkcje i metody, które tabela sekcji ``TABELA`` w ``SKILL.md`` skilla nazywa w `` ` ``, bez klucza w ``DEFINICJE``:
    ``"ścieżka nazwa"`` w kolejności tabeli. Rozjazd zmiany takiej funkcji nie widzi, choć model ją opisuje. Nazwę z
    klasą albo modułem z przodu sprawdzenie szuka w całym kodzie ``KOD``, więc zgubiony wpis całego pliku też jest
    zgłoszony, a gołą nazwę tylko w plikach z ``DEFINICJE``, bo ``save`` czy ``read`` jest w wielu plikach. ``SKILL.md``
    bez tej sekcji to ``ValueError``.

    | Nazwa w wierszu tabeli | Przykład | Wynik |
    | --- | --- | --- |
    | funkcja modułu z pliku definicji | `enter_reports` | bez klucza `enter_reports`: zgłoszona |
    | metoda klasy | `ReportEnteringEntry.on_request` | bez klucza tej metody i klasy: zgłoszona |
    | z modułem z przodu | `_cells.with_added` | jak `with_added` w `_cells.py` (`__init__.py`: nazwa pakietu) |
    | z klasą albo modułem z przodu z pliku spoza definicji | `efenix_page.emmett_window`, `RunHost.end` | zgłoszona |
    | z wywołaniem | `write_cells(...)`, `kept()` | jak nazwa bez nawiasów |
    | metoda bez klasy | `prepare`, `efenix.search` | nazwa bez definicji od modułu: jak `Klasa.prepare` każdej klasy z pliku definicji |
    | metoda klasy z kluczem | `StateFile.retry` przy kluczu `StateFile` | przechodzi: skrót klasy obejmuje metodę |
    | funkcja pliku z `CALY_PLIK` | | przechodzi |
    | nazwa w dwóch plikach | `_case` z kluczem w jednym z nich | przechodzi |

    Granice, które przechodzą bez klucza: klasa, stała i przypisanie (`ClickResult`, `RETRY_S`), zaślepka bez ciała
    poza docstringiem i ``...`` (metoda ``Protocol``, `OrderJournal.ended`), także gdy inna klasa ma metodę o tej nazwie
    z ciałem, nazwa obiektu przed funkcją modułu (`pliki.zapisz()` to tylko metoda `zapisz`), goła nazwa definicji w
    pliku spoza ``DEFINICJE`` (`beside`), nazwa w prozie sekcji poza tabelą, nazwa w tabeli innej sekcji i każda nazwa
    skilla, którego sekcja nie ma tabeli.
    """

    recorded = definicje(skill)
    whole = {path for path, names in recorded.items() if CALY_PLIK in names}
    listed = [path for path in recorded if path not in whole]
    code = sorted({file.relative_to(root).as_posix() for folder in KOD for file in (root / folder).rglob("*.py")} - whole - set(listed))
    sources = {path: (root / path).read_text(encoding="utf-8") for path in [*listed, *code]}
    # Plik kodu spoza definicji wchodzi w poszukiwania nazwy, gdy jest jej modułem albo ma klasę tej nazwy; drzewo
    # składni dopiero wtedy, bo przeglądanie drzew całego kodu przy każdej nazwie tabeli trwa sekundy.
    heads = {path: {_module(path), *re.findall(r"^[ \t]*class[ \t]+(\w+)", sources[path], re.MULTILINE)} for path in code}
    trees: dict[str, ast.Module | None] = {}

    def tree(path: str) -> ast.Module | None:
        if path not in trees:
            trees[path] = _tree(sources[path])
        return trees[path]

    missing: list[str] = []
    for span in _table_spans((skill / "SKILL.md").read_text(encoding="utf-8")):
        name = span.split("(", 1)[0] if span.endswith(")") else span
        if not all(part.isidentifier() for part in name.split(".")):
            continue
        head = name.split(".", 1)[0]
        scope = [*listed, *(path for path in code if "." in name and head in heads[path])]
        bound = [(path, inner, nodes) for path in scope for inner in _in_module(path, name) if (nodes := _nodes(tree(path), inner))]
        if not bound:
            method = name.rsplit(".", 1)[-1]
            bound = [(path, f"{cls}.{method}", nodes) for path in listed for cls in _classes(tree(path)) if (nodes := _nodes(tree(path), f"{cls}.{method}"))]
        found = [(path, inner) for path, inner, nodes in bound if _is_function(nodes)]
        if found and not any(_keyed(recorded.get(path, {}), inner) for path, inner in found):
            missing += [f"{path} {inner}" for path, inner in found if f"{path} {inner}" not in missing]
    return missing


def _keyed(names: dict[str, str], name: str) -> bool:
    parts = name.split(".")
    return any(".".join(parts[:end]) in names for end in range(1, len(parts) + 1))


def _classes(tree: ast.Module | None) -> list[str]:
    return [] if tree is None else list(dict.fromkeys(node.name for node in _statements(tree) if isinstance(node, ast.ClassDef)))


def wiersze_tabeli(text: str) -> list[str]:
    lines = text.splitlines()
    if TABELA not in lines:
        raise ValueError(f"SKILL.md nie ma sekcji „{TABELA}”")
    rows: list[str] = []
    for line in lines[lines.index(TABELA) + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append(line)
    return rows


def _table_spans(text: str) -> list[str]:
    return [span for row in wiersze_tabeli(text) for span in row.split("`")[1::2]]


def _in_module(path: str, name: str) -> list[str]:
    head, _, rest = name.partition(".")
    return [name, rest] if head == _module(path) and rest else [name]


def _module(path: str) -> str:
    file = Path(path)
    return file.parent.name if file.name == "__init__.py" else file.stem


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
    nodes = _nodes(tree, name)
    return _digest("\n".join(_canonical(node) for node in nodes)) if nodes else None


def _nodes(tree: ast.Module | None, name: str) -> list[ast.stmt]:
    if tree is None:
        return []
    scopes: list[ast.AST] = [tree]
    nodes: list[ast.stmt] = []
    for part in name.split("."):
        nodes = [node for scope in scopes for node in _bindings(scope, part)]
        scopes = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return nodes


def _bindings(scope: ast.AST, name: str) -> list[ast.stmt]:
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
    """Postać drzewa bez położenia, docstringów i pól ``None`` albo pustych list, ta sama w każdej wersji Pythona, która
    to drzewo parsuje: ``ast.dump`` od Pythona 3.13 sam pomija takie pola, a nowe pola węzłów (``type_params`` z 3.12) są
    puste w kodzie, który ich nie używa."""

    if isinstance(node, ast.AST):
        fields = ", ".join(f"{field}={_canonical(value)}" for field, value in _fields_without_docstring(node) if value is not None and value != [])
        return f"{type(node).__name__}({fields})"
    if isinstance(node, list):
        return f"[{', '.join(_canonical(each) for each in node)}]"
    return repr(node)


def _fields_without_docstring(node: ast.AST) -> list[tuple[str, object]]:
    documented = isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node, clean=False) is not None
    return [(field, value[1:] if documented and field == "body" else value) for field, value in ast.iter_fields(node)]


def _digest(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()[:DLUGOSC]
