"""Skrypty narzędzi i skilli startują osobnym procesem bez zainstalowanego pakietu ``rozliczenia``.

CI na Windows instaluje tylko ``requirements.txt``, więc skrypt widzi ``src`` tylko wtedy, gdy sam dopisze go do
``sys.path`` (jak ``tools/uruchom_proces.py``). Na Macu ``.venv`` ma instalację edytowalną, która to chowa, więc
test usuwa z ``sys.path`` każdy katalog z pakietem ``rozliczenia`` i uruchamia ``--help`` każdego skryptu z parserem
argumentów, tak jak ``python skrypt.py``. Skrypt z ``if __name__ == "__main__"`` bez parsera ładuje pod inną nazwą
niż ``__main__``, bo ``--help`` nie zatrzymałoby jego pracy, więc sprawdza tylko jego importy.

Czas zjada import bibliotek, więc jeden podproces wczytuje raz moduły bibliotek z ``requirements.txt``, które skrypty
importują, i każdy skrypt biegnie w swoim dziecku ``os.fork``: importy jednego skryptu nie dochodzą do następnego (115
skryptów na Macu 12.11.2026: 4,3 s, bez wstępnego importu 8,3 s). Granica: skrypt, który sięga po podmoduł biblioteki bez jego
importu (``openpyxl.styles`` po samym ``import openpyxl``), przejdzie, gdy ten podmoduł importuje inny skrypt.
``os.fork`` nie ma na Windows, ale tam test się nie uruchamia.

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
from importlib.metadata import packages_distributions
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*(ROOT / "tools").glob("**/*.py"), *(ROOT / ".agents" / "skills").glob("*/scripts/**/*.py")])
REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
ONE_PROCESS = """
import json, os, runpy, signal, sys, traceback
from importlib import import_module
from pathlib import Path

work = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
sys.path[:] = [entry for entry in sys.path if not (Path(entry or '.') / 'rozliczenia').is_dir()]
for module in work['libraries']:
    import_module(module)
loaded = sorted(name for name in sys.modules if name.split('.')[0] == 'rozliczenia')
failed = {}
for index, (script, run_name) in enumerate(work['scripts']):
    folder = Path(str(index))
    folder.mkdir()
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            os.chdir(folder)
            os.dup2(os.open('stderr.txt', os.O_WRONLY | os.O_CREAT), 2)
            os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
            signal.alarm(60)
            sys.path.insert(0, str(Path(script).parent))
            sys.argv = [script, '--help'] if run_name == '__main__' else ['-c', script]
            try:
                runpy.run_path(script, run_name=run_name)
                code = 0
            except SystemExit as stop:
                if stop.code is None or isinstance(stop.code, int):
                    code = stop.code or 0
                else:
                    print(stop.code, file=sys.stderr)
            sys.stdout.flush()
        except BaseException:
            code = 1
            traceback.print_exc()
        finally:
            sys.stderr.flush()
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    if code != 0:
        failed[script] = f'kod {code}\\n' + (folder / 'stderr.txt').read_text(encoding='utf-8', errors='replace')
print(json.dumps({'rozliczenia': loaded, 'failed': failed}))
"""
BOOTSTRAP = 'sys.path.insert(0, str(Path(__file__).resolve().parents[{parents}] / "{folder}"))'
BOOTSTRAP_SHAPE = re.compile(
    r"sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\](?: / '([^']+)')?\)\)"
)
READING = frozenset({"copy", "count", "index"})
FAKE_API = ROOT / "tools" / "lib" / "falszywe_api.py"
BASE_URL = "ANTHROPIC_BASE_URL"
BASE_URL_WORD = re.compile(rf"(?<![A-Za-z0-9_]){BASE_URL}(?![A-Za-z0-9_])")


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


def _libraries() -> list[str]:
    """Moduły bibliotek z ``requirements.txt``, które skrypty importują, do wczytania raz przed pierwszym skryptem."""

    def normal(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    required = {
        normal(found.group())
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (found := REQUIREMENT.match(line))
    }
    tops = {top for top, names in packages_distributions().items() if any(normal(name) in required for name in names)}
    imported: set[str] = set()
    for path in SCRIPTS:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module)
    return sorted(name for name in imported if name.split(".")[0] in tops)


@pytest.mark.skipif(sys.platform == "win32", reason="CI na Windows i tak uruchamia skrypty bez instalacji pakietu")
def test_skrypt_odpowiada_na_help_albo_laduje_sie_bez_zainstalowanego_pakietu(tmp_path: Path) -> None:
    scripts = [
        *([str(path), "__main__"] for path in SCRIPTS if _entry(path) == (True, True)),
        *([str(path), "bez_instalacji"] for path in SCRIPTS if _entry(path) == (True, False)),
    ]
    work = tmp_path / "praca.json"
    work.write_text(json.dumps({"libraries": _libraries(), "scripts": scripts}), encoding="utf-8")
    answered = subprocess.run(
        [sys.executable, "-c", ONE_PROCESS, str(work)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=True,
    )
    result = json.loads(answered.stdout)

    assert result["rozliczenia"] == [], "biblioteki z requirements.txt wczytały pakiet rozliczenia przed skryptami"
    assert result["failed"] == {}, "\n\n".join(
        f"{Path(script).relative_to(ROOT).as_posix()}: {error}" for script, error in result["failed"].items()
    )


def _text(node: ast.AST) -> str | None:
    """Tekst stałej ``str`` albo ``bytes`` (``os.environb``, ``env={b"…": …}``); inaczej ``None``."""

    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        return node.value if isinstance(node.value, str) else node.value.decode("latin-1")
    return None


def _claude_launches(tree: ast.AST) -> Iterator[tuple[int, str]]:
    bare = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    for node in ast.walk(tree):
        text = _text(node)
        if isinstance(node, ast.keyword) and node.arg == BASE_URL:
            yield node.lineno, f"nazywa {BASE_URL}"
        elif isinstance(node, ast.Constant) and text is not None and id(node) not in bare:
            if BASE_URL_WORD.search(text):
                yield node.lineno, f"nazywa {BASE_URL}"
        elif isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first, *rest = (_text(element) for element in node.elts)
            if first == "claude" and rest[:1] != ["--version"]:
                yield node.lineno, "uruchamia claude"


@pytest.mark.parametrize(
    "code",
    [
        'env = dict(os.environ, ANTHROPIC_BASE_URL="http://127.0.0.1:8317")',
        'os.environ.update(ANTHROPIC_BASE_URL=url)',
        'env = {**os.environ, "ANTHROPIC_BASE_URL": url}',
        'os.environ["ANTHROPIC_BASE_URL"] = url',
        'os.putenv("ANTHROPIC_BASE_URL", url)',
        'os.environ.setdefault("ANTHROPIC_BASE_URL", url)',
        'os.environ.update({"ANTHROPIC_BASE_URL": url})',
        'subprocess.run("ANTHROPIC_BASE_URL=http://127.0.0.1:8317 claude -p x", shell=True)',
        'settings = f\'{{"env": {{"ANTHROPIC_BASE_URL": "{url}"}}}}\'',
        'os.environb[b"ANTHROPIC_BASE_URL"] = b"http://127.0.0.1:8317"',
        'subprocess.run(command, env={b"ANTHROPIC_" b"BASE_URL": url})',
    ],
)
def test_adres_api_w_kodzie_skryptu_lapie_straznik(code: str) -> None:
    assert list(_claude_launches(ast.parse(code))) == [(1, f"nazywa {BASE_URL}")]


@pytest.mark.parametrize("code", ['subprocess.run(["claude", "-p", "x"])', 'subprocess.run((b"claude", b"-p", b"x"))'])
def test_claude_w_kodzie_skryptu_lapie_straznik(code: str) -> None:
    assert list(_claude_launches(ast.parse(code))) == [(1, "uruchamia claude")]


@pytest.mark.parametrize(
    "code",
    [
        'subprocess.run(["claude", "--version"])',
        '"""Docstring: ``env.ANTHROPIC_BASE_URL`` z ustawień użytkownika wygrywa ze środowiskiem."""',
        'env = {"ANTHROPIC_BASE_URL_ZAPAS": url, "MOJ_ANTHROPIC_BASE_URL": url}  # ANTHROPIC_BASE_URL w komentarzu',
    ],
)
def test_wersja_claude_opis_i_inna_zmienna_nie_budza_straznika(code: str) -> None:
    assert list(_claude_launches(ast.parse(code))) == []


def test_claude_ze_skryptu_biegnie_tylko_przez_falszywe_api() -> None:
    """Polecenie ``["claude", …]`` inne niż ``claude --version`` i nazwa ``ANTHROPIC_BASE_URL`` są tylko w ``FAKE_API``.

    5.11.2026 wyrocznia z adresem fałszywego API tylko w środowisku procesu zapytała prawdziwy model przez hub z
    ustawień użytkownika i uruchomiła ok. 100 sesji (#956). Test czyta kod tylko w dwóch miejscach: w stałych ``str``
    i ``bytes`` (sąsiednie literały ``"ANTHROPIC_" "BASE_URL"`` parser skleja w jedną stałą, części f-stringu też są
    stałymi), gdzie szuka nazwy jako osobnego słowa i stałej ``"claude"`` na początku listy albo krotki, oraz w
    nazwach argumentów słownych (``dict(os.environ, ANTHROPIC_BASE_URL=…)``).
    Granica: wszystko, co powstaje w czasie biegu (``"ANTHROPIC_" + "BASE_URL"``, odczyt z pliku,
    ``[shutil.which("claude"), …]``), docstring i goły napis, skrypty inne niż ``.py``. W czasie biegu chroni lista
    dozwolona środowiska ``falszywe_api.claude``: ``claude`` nie dostaje ze środowiska wyroczni nic spoza niej.
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
