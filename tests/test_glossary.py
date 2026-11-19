"""GLOSSARY.md jako jedno źródło języka domeny: każde hasło ma jedną definicję.

Każdy agent wczytuje GLOSSARY.md przez ``AGENTS.md``, więc zdublowane hasło
(np. po merge'u) kosztuje kontekst i może rozjechać definicje jednego terminu.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "GLOSSARY.md"
CODE = (ROOT / "src", ROOT / "tools")
IDENTIFIER_HEADER = ("| pojęcie | identyfikator |", "|---|---|")
IDENTIFIER_ROW = re.compile(r"\| (?P<term>[^|`]+?) \| (?:`(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)`|–) \|")


@dataclass(frozen=True)
class Identifier:
    term: str
    name: str | None


def _terms(text: str) -> list[str]:
    return [line.removeprefix("## ").strip() for line in text.splitlines() if line.startswith("## ")]


def _identifier_lines(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(IDENTIFIER_HEADER[0])
    assert lines[start + 1] == IDENTIFIER_HEADER[1], f"po nagłówku tabeli identyfikatorów stoi {IDENTIFIER_HEADER[1]!r}"
    table = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        table.append(line)
    return table


def _identifiers(text: str) -> list[Identifier]:
    rows = [IDENTIFIER_ROW.fullmatch(line) for line in _identifier_lines(text)]
    return [Identifier(row["term"], row["name"]) for row in rows if row is not None]


def _assigned(target: ast.expr) -> Iterator[str]:
    match target:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            yield name
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            for element in elements:
                yield from _assigned(element)
        case ast.Starred(value=value):
            yield from _assigned(value)
        case _:
            return


def _defined_in(statement: ast.stmt) -> Iterator[str]:
    match statement:
        case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            yield name
        case ast.Assign(targets=targets):
            for target in targets:
                yield from _assigned(target)
        case ast.AnnAssign(target=target) | ast.AugAssign(target=target):
            yield from _assigned(target)
        case ast.TypeAlias(name=ast.Name(id=name)):
            yield name
        case _:
            return


def _definitions(modules: Mapping[PurePosixPath, str]) -> frozenset[str]:
    names: set[str] = set()
    for path, source in modules.items():
        names.add(path.parent.name if path.stem == "__init__" else path.stem)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.stmt):
                names.update(_defined_in(node))
            if isinstance(node, ast.arg):
                names.add(node.arg)
            if isinstance(node, ast.ClassDef):
                names.update(f"{node.name}.{member}" for statement in node.body for member in _defined_in(statement))
    return frozenset(names)


def _code() -> dict[PurePosixPath, str]:
    return {
        PurePosixPath(path.relative_to(ROOT).as_posix()): path.read_text(encoding="utf-8")
        for directory in CODE
        for path in sorted(directory.rglob("*.py"))
    }


def test_kazde_haslo_glossary_ma_jedna_definicje() -> None:
    terms = _terms(GLOSSARY.read_text(encoding="utf-8"))
    repeated = sorted(term for term, count in Counter(terms).items() if count > 1)

    assert terms
    assert repeated == []


def test_tabela_identyfikatorow_ma_kazde_haslo_glossary_raz_w_kolejnosci_hasel() -> None:
    text = GLOSSARY.read_text(encoding="utf-8")
    unknown_forms = [line for line in _identifier_lines(text) if IDENTIFIER_ROW.fullmatch(line) is None]

    assert unknown_forms == [], (
        "wiersz tabeli identyfikatorów GLOSSARY.md to „| hasło | `nazwa` |” albo „| hasło | – |” dla pojęcia bez nazwy w kodzie"
    )
    assert [identifier.term for identifier in _identifiers(text)] == _terms(text), (
        "tabela identyfikatorów na początku GLOSSARY.md ma jeden wiersz każdego hasła „## ” w kolejności haseł: "
        "dopisz albo popraw wiersz hasła"
    )


def test_kazdy_identyfikator_z_glossary_jest_nazwa_zdefiniowana_w_src_albo_tools() -> None:
    defined = _definitions(_code())
    missing = [
        f"{identifier.term} → {identifier.name}"
        for identifier in _identifiers(GLOSSARY.read_text(encoding="utf-8"))
        if identifier.name is not None and identifier.name not in defined
    ]

    assert missing == [], (
        "identyfikator pojęcia w GLOSSARY.md to nazwa zdefiniowana w Pythonie src/ albo tools/ (moduł, klasa, funkcja, "
        "parametr, przypisanie) albo „Klasa.składowa”: popraw nazwę w tabeli albo daj „–” pojęciu bez nazwy w kodzie"
    )


@pytest.mark.parametrize(
    ("path", "source", "name", "defined"),
    [
        pytest.param("src/a.py", "class Release:\n    pass\n", "Release", True, id="klasa"),
        pytest.param("src/a.py", "def run_settlements():\n    pass\n", "run_settlements", True, id="funkcja"),
        pytest.param("src/a.py", "async def deliver():\n    pass\n", "deliver", True, id="funkcja-async"),
        pytest.param("src/rozliczenia/collective_file.py", "", "collective_file", True, id="modul-z-nazwy-pliku"),
        pytest.param("src/rozliczenia/worker_reports/__init__.py", "", "worker_reports", True, id="pakiet-z-nazwy-katalogu"),
        pytest.param("src/a.py", "PeriodStatus = int\n", "PeriodStatus", True, id="alias-typu-przypisaniem"),
        pytest.param("src/a.py", "type Kind = int\n", "Kind", True, id="alias-typu-instrukcja-type"),
        pytest.param("src/a.py", "inea_only: int = 0\n", "inea_only", True, id="przypisanie-z-adnotacja"),
        pytest.param("src/a.py", "first, *rest = [1, 2]\n", "rest", True, id="przypisanie-rozpakowaniem"),
        pytest.param("src/a.py", "def f(periods_directory):\n    pass\n", "periods_directory", True, id="parametr"),
        pytest.param("src/a.py", "class A:\n    def f(self):\n        self.release = 1\n", "release", True, id="atrybut-obiektu"),
        pytest.param("src/a.py", "class Worker:\n    active: bool\n", "Worker.active", True, id="pole-klasy"),
        pytest.param("src/a.py", "class Mark:\n    READY = 'E0CCFF'\n", "Mark.READY", True, id="skladowa-enum"),
        pytest.param("src/a.py", "class T:\n    def worker_settlement(self):\n        pass\n", "T.worker_settlement", True, id="metoda"),
        pytest.param("src/pakiet/modul.py", "", "src", False, id="katalog-kodu-to-nie-modul"),
        pytest.param("tools/lib/modul.py", "", "lib", False, id="katalog-bez-init-to-nie-pakiet"),
        pytest.param("src/pakiet/podpakiet/modul.py", "", "pakiet", False, id="pakiet-nadrzedny-to-nie-ten-modul"),
        pytest.param("src/a.py", "print(release)\n", "release", False, id="nazwa-tylko-uzyta"),
        pytest.param("src/a.py", "from pathlib import Path\n", "Path", False, id="nazwa-tylko-z-importu"),
        pytest.param("src/a.py", "x = 'Release'\n", "Release", False, id="nazwa-tylko-w-napisie"),
        pytest.param("src/a.py", "class A:\n    X = 1\n\n\nclass B:\n    pass\n", "B.X", False, id="skladowa-innej-klasy"),
        pytest.param("src/a.py", "class A:\n    def f(self):\n        X = 1\n", "A.X", False, id="zmienna-metody-to-nie-skladowa"),
        pytest.param("src/a.py", "class A:\n    class B:\n        X = 1\n", "A.X", False, id="skladowa-klasy-zagniezdzonej"),
    ],
)
def test_nazwa_zdefiniowana_w_kodzie_to_definicja_a_nie_uzycie_import_ani_napis(
    path: str, source: str, name: str, defined: bool
) -> None:
    assert (name in _definitions({PurePosixPath(path): source})) is defined
