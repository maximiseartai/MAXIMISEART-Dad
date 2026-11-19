"""Środowisko Required CI dowodu strażnika (``tools/lib/srodowisko_ci.py``, ADR 0042 „Środowisko dowodu”).

``mismatch`` na ``main`` jest puste, więc stałe ``srodowisko_ci`` opisują zadanie „Ruff, mypy” z ``ci.yml``, a każda
zmiana tego zadania, która zmienia środowisko ruff i mypy, daje różnicę, której dowód odmawia. Dowód strażnika
``mypy`` w środowisku z ``built`` liczy to, co Required CI PR: zależności i konfiguracja drzewa HEAD scalonego z bazą,
a nie wołającego (#2116 r4–r6).
"""

from __future__ import annotations

from collections.abc import Callable
import copy as copying
import json
import re
from pathlib import Path
import subprocess
import sys
from typing import Any
import unicodedata
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest
import yaml

import srodowisko_ci
import straznik
from tests.fixtures.git_config import computer_git_config
from tests.fixtures.git_repo import commit, git
from tests.fixtures.srodowisko import CI, PINS, project, wymaga_uv

ROOT = Path(__file__).resolve().parents[1]
MYPY = '[tool.mypy]\nfiles = ["kod"]\nstrict = true\n{}\n'


def test_srodowisko_dowodu_opisuje_zadanie_ruff_mypy_z_ci_main() -> None:
    """Stałe ``srodowisko_ci`` to Required CI ``main``: PR, który zmienia zadanie „Ruff, mypy” bez nich, tu pada."""

    assert srodowisko_ci.mismatch(ROOT) == []


Job = dict[str, Any]


def _steps(job: Job) -> list[Job]:
    steps: list[Job] = job["steps"]
    return steps


def _named(job: Job, fragment: str) -> Job:
    return next(step for step in _steps(job) if fragment in str(step.get("name", "")) or fragment in str(step.get("uses", "")))


def _set(path: str, value: object) -> Callable[[Job, Job], None]:
    def change(workflow: Job, job: Job) -> None:
        *head, last = path.split(".")
        target = workflow if head[:1] == ["workflow"] else job
        for key in head[1:] if head[:1] == ["workflow"] else head:
            target = target.setdefault(key, {})
        target[last] = value

    return change


def _step(fragment: str, values: Job) -> Callable[[Job, Job], None]:
    """Zmiana kroku: klucze ``values`` zastępują jego klucze, a ``with`` dokłada się do jego ``with``."""

    def change(_: Job, job: Job) -> None:
        step = _named(job, fragment)
        step.update({**values, **({"with": {**step.get("with", {}), **values["with"]}} if "with" in values else {})})

    return change


def _insert(before: str, step: Job) -> Callable[[Job, Job], None]:
    def change(_: Job, job: Job) -> None:
        steps = _steps(job)
        steps.insert(steps.index(_named(job, before)), step)

    return change


def _drop(fragment: str) -> Callable[[Job, Job], None]:
    def change(_: Job, job: Job) -> None:
        _steps(job).remove(_named(job, fragment))

    return change


def _swap(first: str, second: str) -> Callable[[Job, Job], None]:
    def change(_: Job, job: Job) -> None:
        steps = _steps(job)
        one, two = steps.index(_named(job, first)), steps.index(_named(job, second))
        steps[one], steps[two] = steps[two], steps[one]

    return change


def _ci(change: Callable[[Job, Job], None]) -> str:
    """``ci.yml`` repozytorium ze zmianą ``change`` zadania ``srodowisko_ci.JOB``."""

    workflow = copying.deepcopy(yaml.safe_load(CI))
    change(workflow, workflow["jobs"][srodowisko_ci.JOB])
    return yaml.safe_dump(workflow, allow_unicode=True)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (_step("setup-python", {"with": {"python-version": "3.15"}}), "krok 2 zadania to"),
        (_step("Install development dependencies", {"run": 'uv pip install --system --python "${{ steps.python.outputs.python-path }}" -e ".[dev]"'}), "krok 4 zadania to"),
        (_step("Install development dependencies", {"run": srodowisko_ci.CI_INSTALL + " types-requests"}), "krok 4 zadania to"),
        (_set("runs-on", "macos-latest"), "runs-on 'macos-latest' zamiast 'ubuntu-latest'"),
        (_set("container", "python:3.13"), "container w zadaniu"),
        (_set("env.MYPYPATH", "stuby"), "env w zadaniu"),
        (_set("workflow.env.MYPYPATH", "stuby"), "env w workflow"),
        (_set("defaults.run.working-directory", "src"), "defaults w zadaniu"),
        (_set("workflow.defaults.run.working-directory", "src"), "defaults w workflow"),
        (_step("Typecheck Python code (Linux)", {"env": {"MYPYPATH": "stuby"}}), "krok 6 zadania to"),
        (_step("Lint Python code", {"working-directory": "src"}), "krok 5 zadania to"),
        (_step("setup-python", {"env": {"PYTHONPATH": "src"}}), "krok 2 zadania to"),
        (_insert("Lint Python code", {"name": "Stuby", "run": 'echo "MYPYPATH=stuby" >> "$GITHUB_ENV"'}), "krok 5 zadania to"),
        (_insert("Lint Python code", {"name": "Generator", "run": "python tools/generuj.py"}), "krok 5 zadania to"),
        (_insert("Lint Python code", {"uses": "actions/cache@v4", "with": {"path": ".mypy_cache"}}), "krok 5 zadania to"),
        (_step("actions/checkout", {"with": {"ref": "main"}}), "krok 1 zadania to"),
        (_step("astral-sh/setup-uv", {"with": {"python-version": "3.13"}}), "krok 3 zadania to"),
        (_insert("Lint Python code", {"name": "Mypy macOS", "run": "python -m mypy --platform darwin"}), "krok 5 zadania to"),
        (_step("Typecheck Python code (Linux)", {"run": "python -m mypy --platform linux --strict"}), "krok 6 zadania to"),
        (_drop("Typecheck Python code (Linux)"), "krok 6 zadania to"),
        (_drop("Lint Python code"), "krok 5 zadania to"),
        (_drop("setup-python"), "krok 2 zadania to"),
        (_insert("Lint Python code", {"name": "Testy przed mypy", "run": "python -m pytest tests/test_zapadki.py"}), "krok 5 zadania to"),
        (_set("continue-on-error", True), "continue-on-error w zadaniu"),
        (_set("strategy.matrix.python", ["3.13"]), "strategy w zadaniu"),
        (_step("Typecheck Python code (Linux)", {"if": "false"}), "krok 6 zadania to"),
        (_drop("Install development dependencies"), "krok 4 zadania to"),
        (_step("Install development dependencies", {"id": "instalacja"}), "krok 4 zadania to"),
        (_swap("Typecheck Python code (Linux)", "Typecheck Python code (Windows)"), "krok 6 zadania to"),
        (_step("Typecheck Python code (Windows)", {"run": "python -m mypy"}), "krok 7 zadania to"),
        (_step("Typecheck Python code (Linux)", {"run": "python -m mypy"}), "krok 6 zadania to"),
    ],
    ids=[
        "python",
        "dodatki",
        "pakiet-obok-instalacji",
        "runner",
        "kontener",
        "env-zadania",
        "env-workflow",
        "katalog-zadania",
        "katalog-workflow",
        "env-kroku-mypy",
        "katalog-kroku-ruff",
        "env-akcji",
        "github-env",
        "plik-wygenerowany",
        "pamiec-akcji",
        "checkout-innego-drzewa",
        "python-z-setup-uv",
        "platforma-spoza-listy",
        "opcja-mypy",
        "bez-kroku-mypy",
        "bez-kroku-ruff",
        "bez-setup-python",
        "pytest-przed-mypy",
        "zadanie-bez-porazki",
        "macierz",
        "mypy-pominiety",
        "bez-instalacji",
        "instalacja-bez-id-warunku",
        "kolejnosc-mypy",
        "mypy-windows-bez-platformy",
        "mypy-linux-bez-platformy",
    ],
)
def test_zmiana_srodowiska_ruff_i_mypy_w_ci_to_roznica(tmp_path: Path, change: Callable[[Job, Job], None], fragment: str) -> None:
    _write(tmp_path, {srodowisko_ci.WORKFLOW: _ci(change)})

    found = srodowisko_ci.mismatch(tmp_path)

    assert any(fragment in problem for problem in found), found


@pytest.mark.parametrize(
    "change",
    [
        _step("Audit workflows (zizmor)", {"env": {"GH_TOKEN": "x"}}),
        _insert("Audit workflows (zizmor)", {"name": "Po mypy", "run": "python tools/cokolwiek.py"}),
        _set("timeout-minutes", 30),
        _step("Lint Python code", {"name": "Ruff"}),
        _step("astral-sh/setup-uv", {"uses": "astral-sh/setup-uv@0000000000000000000000000000000000000000"}),
    ],
    ids=["env-po-mypy", "krok-po-mypy", "limit-czasu", "nazwa-kroku", "wersja-akcji"],
)
def test_zmiana_zadania_ktora_srodowiska_ruff_i_mypy_nie_zmienia_nie_jest_roznica(tmp_path: Path, change: Callable[[Job, Job], None]) -> None:
    _write(tmp_path, {srodowisko_ci.WORKFLOW: _ci(change)})

    assert srodowisko_ci.mismatch(tmp_path) == []


@pytest.mark.parametrize(
    ("files", "fragment"),
    [
        ({"uv.toml": "prerelease = 'allow'\n"}, "uv.toml w drzewie"),
        ({"pyproject.toml": "[tool.uv]\nprerelease = 'allow'\n"}, "tabela tool.uv w pyproject.toml"),
        ({"pyproject.toml": "[ tool.uv ]\noverride-dependencies = ['mypy==1.18.2']\n"}, "tabela tool.uv w pyproject.toml"),
        ({"pyproject.toml": "[tool]\nuv.resolution = 'lowest'\n"}, "tabela tool.uv w pyproject.toml"),
        ({"pyproject.toml": "tool.uv.prerelease = 'allow'\n"}, "tabela tool.uv w pyproject.toml"),
        ({"pyproject.toml": "[tool.uv\n"}, "pyproject.toml bez odczytu TOML"),
    ],
    ids=["uv-toml", "tool-uv", "tool-uv-ze-spacjami", "uv-pod-tool", "klucz-kropkowy", "toml-z-bledem"],
)
def test_konfiguracja_uv_w_drzewie_to_roznica(tmp_path: Path, files: dict[str, str], fragment: str) -> None:
    _write(tmp_path, {srodowisko_ci.WORKFLOW: CI, **files})

    assert any(fragment in problem for problem in srodowisko_ci.mismatch(tmp_path))


def test_zmienne_ktore_steruja_pythonem_mypy_ruff_i_uv_nie_trafiaja_do_srodowiska(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = ("MYPYPATH", "PYTHONPATH", "RUFF_OUTPUT_FORMAT", "UV_INDEX_URL", "PIP_INDEX_URL", "VIRTUAL_ENV", "GH_TOKEN", "GITHUB_TOKEN")
    for name in (*hidden, "UV_CACHE_DIR", "HOME"):
        monkeypatch.setenv(name, "x")

    passed = srodowisko_ci.variables()

    assert [name for name in hidden if name in passed] == []
    assert passed["UV_CACHE_DIR"] == "x" and passed["HOME"] == "x"


TYPED = {
    "kod/__init__.py": "",
    "kod/odczyt.py": "def odczyt() -> str:\n    return 'tekst'\n",
    "kod/uzycie.py": "from kod.odczyt import odczyt\n\n\ndef glosno() -> str:\n    return odczyt().upper()\n",
}
TYPED_FIX = {
    "kod/odczyt.py": "def odczyt() -> str | None:\n    return None\n",
    "kod/uzycie.py": "from kod.odczyt import odczyt\n\n\ndef glosno() -> str:\n    tekst = odczyt()\n    return '' if tekst is None else tekst.upper()\n",
}
# Plik, który PR dodaje z zależnością PyYAML (sonda #2116 r6 W1): mypy strict wymaga jej stubów.
KONFIG = {"kod/konfig.py": "import yaml\n\n\ndef wczytaj(tekst: str) -> object:\n    return yaml.safe_load(tekst)\n"}
CASE = (("kod/uzycie.py", 5, 5),)
SCOPE = (("kod/uzycie.py", 4, 5),)


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def _repository(tmp_path: Path, base: dict[str, str], failed: dict[str, str], head: dict[str, str], moved: dict[str, str] | None = None) -> tuple[Path, str, str, str, str]:
    """``main`` z ``base``, gałąź PR z commitem FAIL (``failed``) i HEAD (``head``), a z ``moved`` ``main`` idzie dalej;
    zwraca repozytorium, rozwidlenie, FAIL, HEAD i bazę."""

    root = tmp_path / "repo"
    _write(root, base)
    git(root, "init", "--quiet", "--initial-branch", "main")
    fork = commit(root, "main")
    git(root, "checkout", "--quiet", "-b", "pr")
    _write(root, failed)
    failing = commit(root, "FAIL")
    _write(root, head)
    fixed = commit(root, "HEAD")
    target = fork
    if moved:
        git(root, "checkout", "--quiet", "main")
        _write(root, moved)
        target = commit(root, "main idzie dalej")
    return root, fork, failing, fixed, target


def _proved(root: Path, fork: str, failed: str, head: str, target: str) -> straznik.Outcome:
    case = straznik.Case("#5 W1 r1", failed, fork, CASE, SCOPE)
    with srodowisko_ci.built(root, head, target) as environment:
        [outcome] = straznik.prove(root, straznik.parse("mypy"), environment, [case])
    return outcome


LINUX = "; sys_platform == 'linux'"


@wymaga_uv
@pytest.mark.parametrize(
    ("marker", "stubs", "detected", "state"),
    [("", ("types-PyYAML==6.0.12.20260906",), True, "WYKRYTA"), ("", (), False, "PODSTAWA CZERWONA"), (LINUX, (f"types-PyYAML==6.0.12.20260906{LINUX}",), True, "WYKRYTA")],
    ids=["pr-dodaje-zaleznosc-ze-stubami", "pr-dodaje-zaleznosc-bez-stubow", "zaleznosc-tylko-systemu-runnera-ci"],
)
def test_dowod_mypy_bierze_zaleznosci_drzewa_pr_a_nie_wolajacego(tmp_path: Path, marker: str, stubs: tuple[str, ...], detected: bool, state: str) -> None:
    """Sonda #2116 r6 W1: PR dodaje ``import yaml`` z zależnością PyYAML w swoim ``pyproject.toml``. Dowód liczy mypy
    z zależnościami drzewa jak Required CI (``ci.yml:125``), więc stuby z dodatku dev PR dają ``WYKRYTA``, a ich brak
    ``PODSTAWA CZERWONA``, choć Python testów, który woła dowód, ma PyYAML i jego stuby. Zależność tylko dla Linuksa
    instaluje się jak na runnerze Required CI na każdej maszynie dowodu, także na Macu."""

    base = {**project(tools=MYPY.format("")), **TYPED}
    pr = project(f"PyYAML==6.0.3{marker}", dev=stubs, tools=MYPY.format(""))
    root, fork, failed, head, target = _repository(tmp_path, base, {**pr, **KONFIG, "kod/uzycie.py": TYPED["kod/uzycie.py"]}, TYPED_FIX)

    outcome = _proved(root, fork, failed, head, target)

    assert outcome.detected is detected and f"| {state} |" in outcome.line, outcome.line
    if not detected:
        assert 'kod/konfig.py:1 [import-untyped] Library stubs not installed for "yaml"' in outcome.line, outcome.line


@wymaga_uv
def test_dowod_liczy_drzewo_head_scalone_z_baza_jak_refs_pull_merge(tmp_path: Path) -> None:
    """Baza po rozwidleniu PR wyłącza błąd ``union-attr``, więc po merge'u mypy ``main`` błędu z ``Gdzie`` nie złapie:
    dowód na drzewie scalonym, które sprawdza Required CI PR, daje ``NIEWYKRYTA``, a nie ``WYKRYTA`` samego HEAD."""

    base = {**project(tools=MYPY.format("")), **TYPED}
    moved = project(tools=MYPY.format('disable_error_code = ["union-attr"]'))
    root, fork, failed, head, target = _repository(tmp_path, base, {"kod/uzycie.py": TYPED["kod/uzycie.py"] + "\n"}, TYPED_FIX, moved)

    outcome = _proved(root, fork, failed, head, target)

    assert not outcome.detected and "| NIEWYKRYTA | kod/uzycie.py: bez znaleziska (kod 0)" in outcome.line, outcome.line


@wymaga_uv
@pytest.mark.parametrize("fix", ["fix = true", "fix-only = true"])
def test_krok_ktory_przepisuje_pliki_przed_mypy_to_odmowa_a_nie_dowod(tmp_path: Path, fix: str) -> None:
    """Sonda #2161 r1 W2: Required CI uruchamia ``ruff check`` przed mypy w tym samym checkoucie, więc z ``fix``
    w konfiguracji ruff drzewa mypy liczy plik bez importu, który ruff usunął, i jest zielone. Dowód uruchamia kroki
    po kolei i odmawia, gdy krok zmienił pliki kopii, zamiast liczyć mypy na pliku, którego Required CI nie widzi."""

    ruff = f'[tool.ruff]\n{fix}\n\n[tool.ruff.lint]\nselect = ["F401"]\n'
    base = {**project(tools=MYPY.format("") + ruff), **TYPED}
    failed = {"kod/uzycie.py": "from kod.odczyt import odczyt, brak\n\n\ndef glosno() -> str:\n    return odczyt()\n"}
    root, fork, failing, head, target = _repository(tmp_path, base, failed, {"kod/uzycie.py": TYPED["kod/uzycie.py"]})
    case = straznik.Case("#5 W1 r1", failing, fork, (("kod/uzycie.py", 1, 1),), (("kod/uzycie.py", 1, 1),))

    with srodowisko_ci.built(root, head, target) as environment:
        [outcome] = straznik.prove(root, straznik.parse("mypy"), environment, [case])

    assert not outcome.detected and "| KROK PISZE PLIKI | po kroku ruff: kod/uzycie.py (" in outcome.line, outcome.line


@wymaga_uv
def test_kopia_nie_bierze_wykluczen_gita_repozytorium_wolajacego(tmp_path: Path) -> None:
    """Ruff pomija pliki z ``.git/info/exclude`` i globalnych wykluczeń gita, a checkout Required CI ich nie ma: plik PR
    w katalogu, który repozytorium wołającego wyklucza lokalnie, dowód ``ruff`` liczy jak Required CI."""

    ruff = '[tool.ruff.lint]\nselect = ["F401"]\n'
    base = {**project(tools=MYPY.format("") + ruff), **TYPED}
    root, fork, failing, head, target = _repository(tmp_path, base, {"wykluczone/modul.py": "import os\n"}, {"wykluczone/modul.py": "X = 1\n"})
    (root / ".git" / "info").mkdir(exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text("wykluczone/\n", encoding="utf-8")
    case = straznik.Case("#5 W1 r1", failing, fork, (("wykluczone/modul.py", 1, 1),), (("wykluczone/modul.py", 1, 1),))

    with srodowisko_ci.built(root, head, target) as environment:
        [outcome] = straznik.prove(root, straznik.parse("ruff"), environment, [case])

    assert outcome.detected and "| WYKRYTA | z FAIL: wykluczone/modul.py | wykluczone/modul.py:1 F401" in outcome.line, outcome.line


@wymaga_uv
def test_kopia_nie_bierze_konfiguracji_gita_komputera(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkout Required CI biegnie bez konfiguracji komputera, więc ``core.autocrlf`` wołającego nie zmienia końców linii
    plików, które czytają ruff i mypy dowodu."""

    root, _, _, head, target = _repository(tmp_path, {**project(tools=MYPY.format("")), **TYPED}, {"kod/uzycie.py": "X = 1\n"}, {"kod/nowy.py": "Y = 2\n"})
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(computer_git_config(tmp_path / "gitconfig", "[core]\n\tautocrlf = true\n")))

    with srodowisko_ci.built(root, head, target) as environment:
        text = (environment.copy / "kod" / "nowy.py").read_bytes()

    assert text == b"Y = 2\n"


@wymaga_uv
def test_srodowisko_ma_pythona_ci_i_projekt_z_kopii_drzewa(tmp_path: Path) -> None:
    """Python ``CI_PYTHON``, narzędzia z pinów drzewa, zależność ze znacznikiem wersji z poprawką (Required CI rozwiązuje
    ją dla Pythona z setup-python, a nie dla 3.14.0) i projekt edytowalnie z kopii HEAD scalonego z bazą."""

    marked = "six==1.17.0; python_full_version >= '3.14.1'"
    root, _, _, head, target = _repository(tmp_path, {**project(marked, tools=MYPY.format("")), **TYPED}, {"kod/uzycie.py": "X = 1\n"}, {"kod/nowy.py": "Y = 2\n"}, {"kod/z_bazy.py": "Z = 3\n"})

    with srodowisko_ci.built(root, head, target) as environment:
        done = subprocess.run(
            [
                str(environment.python),
                "-c",
                "import sys, importlib.metadata as m; print('.'.join(map(str, sys.version_info[:2]))); "
                "print(' '.join(f'{name}=={m.version(name)}' for name in ('mypy', 'ruff', 'ast-grep-cli', 'six'))); print(m.distribution('proba').read_text('direct_url.json'))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        files = sorted(path.name for path in (environment.copy / "kod").iterdir())
        copy = environment.copy.resolve()

    version, tools, origin = done.stdout.splitlines()
    installed = json.loads(origin)
    assert version == srodowisko_ci.CI_PYTHON
    assert sorted(tools.split()) == sorted((*PINS, "six==1.17.0"))
    assert installed["dir_info"] == {"editable": True} and Path(url2pathname(urlparse(installed["url"]).path)).resolve() == copy, origin
    assert files == ["__init__.py", "nowy.py", "odczyt.py", "uzycie.py", "z_bazy.py"]


@wymaga_uv
@pytest.mark.parametrize(
    ("moved", "fragment"),
    [
        ({srodowisko_ci.WORKFLOW: _ci(_step("setup-python", {"with": {"python-version": "3.15"}}))}, "zmień środowisko Required CI osobnym PR przed tym"),
        ({"kod/uzycie.py": "Z = 3\n"}, "z konfliktem (kod/uzycie.py): zaktualizuj PR z bazy"),
        (project("brak @ file:///nie/ma/takiego/pakietu"), "uv pip compile skończył się kodem 1 (error: Distribution not found at: file:///nie/ma/takiego/pakietu): popraw pyproject.toml"),
    ],
    ids=["baza-z-innym-pythonem-ci", "konflikt-z-baza", "budowa-pada"],
)
def test_dowod_odmawia_drzewa_ktorego_srodowiska_nie_zbuduje_jak_ci(tmp_path: Path, moved: dict[str, str], fragment: str) -> None:
    root, _, _, head, target = _repository(tmp_path, {**project(tools=MYPY.format("")), **TYPED}, {"kod/uzycie.py": "X = 1\n"}, {"kod/uzycie.py": "X = 2\n"}, moved)

    with pytest.raises(srodowisko_ci.Refused, match=re.escape(fragment)), srodowisko_ci.built(root, head, target):
        pass


@wymaga_uv
@pytest.mark.parametrize(
    "twins",
    [("Modul.py", "modul.py"), (unicodedata.normalize("NFC", "zó.py"), unicodedata.normalize("NFD", "zó.py"))],
    ids=["wielkosc-liter", "nfc-i-nfd"],
)
def test_na_macos_drzewo_ze_sciezkami_ktore_apfs_scala_to_odmowa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, twins: tuple[str, str]) -> None:
    """APFS macOS trzyma jedną z dwóch ścieżek różnych tylko wielkością liter albo normalizacją Unicode, a runner obie,
    więc dowód na macOS liczyłby inne drzewo; commit powstaje z drzewa gita, bo system plików testu może pary nie
    utrzymać."""

    root = tmp_path / "repo"
    git(tmp_path, "init", "--quiet", "--initial-branch", "main", str(root))
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=root, input="X = 1\n", capture_output=True, text=True, check=True).stdout.strip()

    def tree(*names: str) -> str:
        listing = "".join(f"100644 blob {blob}\t{name}\n" for name in names)
        return subprocess.run(["git", "mktree"], cwd=root, input=listing, capture_output=True, text=True, check=True).stdout.strip()

    target = git(root, "commit-tree", tree("inny.py"), "-m", "baza")
    head = git(root, "commit-tree", tree("inny.py", *twins), "-p", target, "-m", "PR")
    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(srodowisko_ci.Refused, match=re.escape(f"ścieżki różne tylko wielkością liter albo normalizacją Unicode ({', '.join(sorted(twins))})")), srodowisko_ci.built(root, head, target):
        pass


@wymaga_uv
def test_dowod_bez_uv_odmawia_z_tym_co_zrobic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(srodowisko_ci.Refused, match="brak uv na PATH, a Required CI instaluje zależności uv \\(setup-uv\\): zainstaluj uv"), srodowisko_ci.built(tmp_path, "HEAD", "HEAD"):
        pass
