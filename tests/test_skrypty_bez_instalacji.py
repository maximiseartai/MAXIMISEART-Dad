"""Skrypty narzędzi i skilli startują osobnym procesem bez zainstalowanego pakietu ``rozliczenia``.

CI na Windows instaluje tylko ``requirements.txt``, więc skrypt widzi ``src`` tylko wtedy, gdy sam dopisze go do
``sys.path`` (jak ``tools/uruchom_proces.py``). Na Macu ``.venv`` ma instalację edytowalną, która to chowa, więc
test usuwa z ``sys.path`` każdy katalog z pakietem ``rozliczenia`` i uruchamia ``--help`` każdego skryptu z parserem
argumentów, tak jak ``python skrypt.py``. Skrypt z ``if __name__ == "__main__"`` bez parsera ładuje pod inną nazwą
niż ``__main__``, bo ``--help`` nie zatrzymałoby jego pracy, więc sprawdza tylko jego importy.

Skrypt dopisuje każdy katalog jedną linią w jednej postaci (``BOOTSTRAP``) zaraz pod importami biblioteki. Ruff
zwalnia z E402 importy pod wywołaniem ``sys.path.insert``, ale nie pod przypisaniem ani stałą, więc ta postać nie
potrzebuje ani ``noqa``, ani ``per-file-ignores``, a E402 dalej łapie import pod innym kodem. Dlatego linia liczy
``Path(__file__).resolve().parents[N]`` sama, a stała z korzeniem repozytorium stoi dopiero pod importami.
Kopia w innej postaci albo z liczbą ``parents``, która nie trafia w korzeń repozytorium, czerwieni
``test_skrypt_dopisuje_katalogi_do_sys_path_jedna_linia``.

Skrypt, który uruchamia Claude Code, robi to tylko przez ``tools/lib/falszywe_api.py``
(``test_claude_ze_skryptu_biegnie_tylko_przez_falszywe_api``).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*(ROOT / "tools").glob("**/*.py"), *(ROOT / ".agents" / "skills").glob("*/scripts/**/*.py")])
STRIPPED = (
    "import runpy, sys\n"
    "from pathlib import Path\n"
    "script = sys.argv[1]\n"
    "sys.path[:] = [entry for entry in sys.path if not (Path(entry or '.') / 'rozliczenia').is_dir()]\n"
    "sys.path.insert(0, str(Path(script).parent))\n"
)
WITHOUT_INSTALL = STRIPPED + "sys.argv = [script, '--help']\nrunpy.run_path(script, run_name='__main__')\n"
LOADED_WITHOUT_INSTALL = STRIPPED + "runpy.run_path(script, run_name='bez_instalacji')\n"
BOOTSTRAP = 'sys.path.insert(0, str(Path(__file__).resolve().parents[{parents}] / "{folder}"))'
BOOTSTRAP_SHAPE = re.compile(
    r"sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\](?: / '([^']+)')?\)\)"
)
READING = frozenset({"copy", "count", "index"})
FAKE_API = ROOT / "tools" / "lib" / "falszywe_api.py"


def _entry(path: Path) -> tuple[bool, bool]:
    """Czy skrypt ma ``if __name__ == "__main__"`` i czy buduje parser argumentów."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    entry = any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in tree.body)
    parser = any(
        isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in ("ArgumentParser", "Parser")
        for node in ast.walk(tree)
    )
    return entry, parser


def _path_changes(tree: ast.Module) -> Iterator[ast.expr | ast.stmt]:
    """Każda zmiana ``sys.path``: wywołanie metody, przypisanie, ``del``, ``sys`` albo ``sys.path`` pod inną nazwą."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func.value) == "sys.path" and node.func.attr not in READING:
                yield node
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            value = getattr(node, "value", None)
            if any(ast.unparse(target).startswith("sys.path") for target in targets) or (
                value is not None and ast.unparse(value) in ("sys", "sys.path")
            ):
                yield node
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            if any(alias.name in ("path", "*") for alias in node.names):
                yield node
        elif isinstance(node, ast.Import) and any(alias.name == "sys" and alias.asname for alias in node.names):
            yield node


def _bootstrap_problem(path: Path, tree: ast.Module, change: ast.expr | ast.stmt, seen: set[str]) -> str | None:
    """Co w zmianie ``sys.path`` nie zgadza się z ``BOOTSTRAP`` i jak to naprawić; ``None``, gdy się zgadza."""

    parents = len(path.relative_to(ROOT).parts) - 1
    line = ast.unparse(change)
    shape = BOOTSTRAP_SHAPE.fullmatch(line)
    if shape is None or not any(isinstance(node, ast.Expr) and node.value is change for node in tree.body):
        return (
            f"zamiast {line!r} dopisz każdy katalog osobną linią na poziomie modułu, zaraz pod importami biblioteki, "
            f"np. {BOOTSTRAP.format(parents=parents, folder='src')}"
        )
    folder = shape.group(2) or "."
    if int(shape.group(1)) != parents:
        return (
            f"parents[{shape.group(1)}] nie trafia w korzeń repozytorium, z tego pliku to parents[{parents}]: "
            f"{BOOTSTRAP.format(parents=parents, folder=folder)}"
        )
    if folder in seen:
        return f"katalog {folder} jest już dopisany wyżej, usuń tę linię"
    seen.add(folder)
    inside = (ROOT / folder).resolve()
    if not inside.is_dir() or not inside.is_relative_to(ROOT):
        return f"katalogu {folder} nie ma w repozytorium, wpisz ścieżkę katalogu względem korzenia repozytorium"
    return None


def test_skrypt_dopisuje_katalogi_do_sys_path_jedna_linia() -> None:
    problems = []
    for path in SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: set[str] = set()
        for change in _path_changes(tree):
            problem = _bootstrap_problem(path, tree, change, seen)
            if problem is not None:
                problems.append(f"{path.relative_to(ROOT).as_posix()}:{change.lineno}: {problem}")

    assert problems == [], "\n".join(problems)


def _assert_runs(tmp_path: Path, program: str, script: Path) -> None:
    answered = subprocess.run(
        [sys.executable, "-c", program, str(script)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert answered.returncode == 0, answered.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="CI na Windows i tak uruchamia skrypty bez instalacji pakietu")
@pytest.mark.parametrize(
    "script", [path for path in SCRIPTS if _entry(path) == (True, True)], ids=lambda path: path.relative_to(ROOT).as_posix()
)
def test_skrypt_odpowiada_na_help_bez_zainstalowanego_pakietu(tmp_path: Path, script: Path) -> None:
    _assert_runs(tmp_path, WITHOUT_INSTALL, script)


@pytest.mark.skipif(sys.platform == "win32", reason="CI na Windows i tak uruchamia skrypty bez instalacji pakietu")
@pytest.mark.parametrize(
    "script", [path for path in SCRIPTS if _entry(path) == (True, False)], ids=lambda path: path.relative_to(ROOT).as_posix()
)
def test_skrypt_bez_parsera_laduje_sie_bez_zainstalowanego_pakietu(tmp_path: Path, script: Path) -> None:
    _assert_runs(tmp_path, LOADED_WITHOUT_INSTALL, script)


def _claude_launches(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "ANTHROPIC_BASE_URL":
            yield node.lineno, "ustawia adres API"
        elif isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first, *rest = node.elts
            second = rest[0].value if rest and isinstance(rest[0], ast.Constant) else None
            if isinstance(first, ast.Constant) and first.value == "claude" and second != "--version":
                yield node.lineno, "uruchamia claude"


def test_claude_ze_skryptu_biegnie_tylko_przez_falszywe_api() -> None:
    """Polecenie ``["claude", …]`` inne niż ``claude --version`` i stała ``ANTHROPIC_BASE_URL`` są tylko w ``FAKE_API``.

    5.11.2026 wyrocznia z adresem fałszywego API tylko w środowisku procesu zapytała prawdziwy model przez hub z
    ustawień użytkownika i uruchomiła ok. 100 sesji (#956). Granica: polecenie złożone w czasie biegu (tekst powłoki,
    lista budowana z części) test widzi tylko po stałej ``"claude"`` na początku listy albo krotki.
    """

    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {what} poza tools/lib/falszywe_api.py"
        for path in SCRIPTS
        if path != FAKE_API
        for line, what in _claude_launches(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert not found, "\n".join(
        [
            *found,
            "Claude Code uruchom przez falszywe_api.claude z tools/lib/falszywe_api.py: tylko tam ustawienia "
            "użytkownika nie dochodzą do claude, adres fałszywego API idzie w --settings, a claude bez kontaktu ginie.",
        ]
    )
