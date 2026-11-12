"""Blok ``## Narzędzia`` w ``AGENTS.md`` to spis narzędzi agenta: każde narzędzie z ``tools/`` z pierwszym zdaniem docstringu.

Spis jest w kontekście agenta od początku sesji, więc agent nie musi wiedzieć, że narzędzie istnieje, zanim go szuka.
W ``tools/`` leżą tylko narzędzia, które agent albo człowiek uruchamia; skrypty, które uruchamia workflow, leżą
w ``tools/ci/``, a moduły bez własnego wywołania w ``tools/lib/``, więc spis ich nie ma, a ``AGENTS.md`` i skille nie
wskazują ``tools/ci/``. Skrypt, który agent uruchamia sam według ``docs/agents/``, ``README.md`` albo docstringu
narzędzia (plan runu, odtworzenie części nocnych mutacji), leży w ``tools/``, bo inaczej spis go nie ma, a agent bierze
najbliższą pozycję spisu: polecenie ``python … tools/ci/…`` w tych dokumentach to błąd. Pierwsze zdanie docstringu (zarazem pierwsza linia ``--help``) mówi w jednej linii
``MIN_CHARS``–``MAX_CHARS`` znaków, co narzędzie robi i kiedy go użyć, a pierwsze ``SAME_WORDS`` słów odróżnia je od
każdego innego narzędzia. Narzędzie z obowiązkową podkomendą (``add_subparsers(required=True)``) wymienia w tym
zdaniu w nawiasie co najmniej jedną z nich, np. „(plan --baza origin/main)”, bo agent, który zna je tylko ze spisu,
inaczej woła narzędzie bez podkomendy; nawias odróżnia podkomendę od tego samego słowa w zdaniu („Drukuje plan runu”).
Blok między ``START`` i ``END`` zapisuje ten test z ``ZAPISZ_EXPECT=1``, jak plik expect.

Zależności idą w jedną stronę: narzędzia z ``tools/``, biblioteki z ``tools/lib/`` i hooki nie importują skryptów
z ``tools/ci/`` ani nie dodają tego katalogu do ``sys.path``, bo zmiana skryptu workflow nie może łamać narzędzi agenta.
Biblioteka z ``tools/lib/`` nie importuje też narzędzia z ``tools/``, bo narzędzie zmienia się razem ze swoim wywołaniem,
a z biblioteki biorą narzędzia, skille i testy (``_library_reaches_tools`` wylicza, co strażnik widzi).
Skrypt, który workflow uruchamia systemowym ``python3`` runnera (bez zależności projektu), razem ze wszystkim, co
importuje z ``tools/``, używa tylko biblioteki standardowej.

Granica: test nie ocenia, czy zdanie mówi „kiedy” słowami sytuacji agenta (czerwone CI, przed merge'em); to łapie
tylko przegląd. Importu przez ``importlib`` ani polecenia składanego w czasie biegu strażnik importów nie widzi.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
import re
import sys
from typing import get_args

import pytest

from rozliczenia.centrum.contract import common as common_contract

from tests.fixtures.expect import assert_expected

ROOT = Path(__file__).resolve().parents[1]
AGENTS_MD = ROOT / "AGENTS.md"
TOOLS = ROOT / "tools"
SKILLS = ROOT / ".agents" / "skills"
AGENT_DOCS = [ROOT / "README.md", *sorted((ROOT / "docs" / "agents").glob("*.md"))]
START = "<!-- spis narzędzi: generuje tests/test_spis_narzedzi.py z ZAPISZ_EXPECT=1, nie edytuj ręcznie -->"
END = "<!-- koniec spisu narzędzi -->"
MIN_CHARS = 80
MAX_CHARS = 160
SAME_WORDS = 3
CI_TOOLS = "tools/ci/"
# Polecenie, które uruchamia skrypt z tools/ci/: interpreter (python3, .venv/bin/python, py -3) albo `--` przed nim.
RUNS_CI_TOOL = re.compile(r"(?:python[\d.]*|py -3|--)\s+tools/ci/")
WORKFLOWS = ROOT / ".github" / "workflows"
# Skrypt w kroku workflow uruchamiany systemowym python3 runnera, bez zależności projektu.
SYSTEM_PYTHON = re.compile(r"\bpython3\s+(tools/\S+\.py)\b")
# Katalogi, z których skrypt z tools/ importuje moduły projektu (sys.path jego i testów).
MODULE_DIRS = (TOOLS / "lib", TOOLS, TOOLS / "ci")


def _tools() -> list[Path]:
    return sorted(TOOLS.glob("*.py"))


def _first_paragraph(path: Path) -> list[str]:
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return docstring.split("\n\n", 1)[0].splitlines()


def _required_subcommands(path: Path) -> list[str]:
    """Stałe nazwy ``add_parser`` narzędzia, które ma ``add_subparsers(required=True)``; pusta lista bez takiej grupy.

    Czyta każde ``add_parser("<nazwa>")`` ze stałą nazwą w pliku, bez rozróżniania grup, bo pierwsze zdanie ma wymienić
    którąkolwiek z nich, a podkomenda na każdy wpis katalogu procesów (``add_parser(kind.key)`` w ciele pętli
    ``for kind in CATALOG.kinds``, Skrypt dla maszyn) to każdy klucz procesu (``common_contract.ProcessKey``). Podkomendy dodane
    inaczej (ze zmiennej, w innej pętli, także po zmiennej o tej samej nazwie) obok tych nie są sprawdzane. Narzędzie z ``required=True``, z którego nie da się
    odczytać żadnej nazwy, to ``ValueError``, bo pusta lista przepuściłaby je bez sprawdzenia.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        (node.func.attr, node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    required = any(
        method == "add_subparsers"
        and any(keyword.arg == "required" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in call.keywords)
        for method, call in calls
    )
    if not required:
        return []
    per_kind = {
        id(call)
        for loop in ast.walk(tree)
        if isinstance(loop, ast.For) and isinstance(loop.target, ast.Name) and ast.unparse(loop.iter) == "CATALOG.kinds"
        for call in _calls_with_key_of(loop.target.id, loop.body)
    }
    names = []
    for method, call in calls:
        if method != "add_parser" or not call.args:
            continue
        name = call.args[0]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            names.append(name.value)
        elif id(call) in per_kind:
            names += get_args(common_contract.ProcessKey)
    if not names:
        raise ValueError(
            f"{path.name}: add_subparsers(required=True), a żadnej podkomendy nie da się odczytać ze stałej w "
            'add_parser("<nazwa>"); dodaj choć jedną podkomendę osobnym add_parser ze stałą nazwą'
        )
    return names


def _calls_with_key_of(kind: str, body: list[ast.stmt]) -> Iterator[ast.Call]:
    """Wywołania ``….add_parser(<kind>.key)`` w ``body`` pętli po ``kind``."""

    for node in (node for statement in body for node in ast.walk(statement)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_parser" and node.args:
            if ast.unparse(node.args[0]) == f"{kind}.key":
                yield node


def _names_subcommand_in_brackets(sentence: str, subcommands: list[str]) -> bool:
    brackets = " ".join(re.findall(r"\(([^)]*)\)", sentence))
    return any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", brackets) for name in subcommands)


def _index() -> str:
    return "".join(f"- `{path.relative_to(ROOT).as_posix()}`: {' '.join(_first_paragraph(path))}\n" for path in _tools())


def test_spis_narzedzi_w_agents_md_to_pierwsze_zdania_narzedzi_z_tools() -> None:
    text = AGENTS_MD.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1, f"AGENTS.md ma mieć raz linię {START!r} i raz {END!r}"
    before, rest = text.split(START + "\n")
    _, after = rest.split(END)

    assert_expected(f"{before}{START}\n{_index()}{END}{after}", AGENTS_MD)


def test_pierwsze_zdanie_narzedzia_to_jedna_linia_o_dlugosci_spisu() -> None:
    problems = []
    for path in _tools():
        paragraph = _first_paragraph(path)
        name = path.relative_to(ROOT).as_posix()
        if len(paragraph) != 1:
            problems.append(f"{name}: pierwszy akapit docstringu ma {len(paragraph)} linii, a ma mieć jedno zdanie w jednej")
        elif not MIN_CHARS <= len(paragraph[0]) <= MAX_CHARS or not paragraph[0].endswith("."):
            problems.append(f"{name}: pierwsze zdanie ma {len(paragraph[0])} znaków albo nie kończy się kropką")

    assert problems == [], "\n".join(
        [
            *problems,
            f"Zacznij docstring jednym zdaniem {MIN_CHARS}–{MAX_CHARS} znaków zakończonym kropką: co narzędzie robi i kiedy "
            "go użyć, słowami sytuacji agenta; szczegóły daj w następnych akapitach.",
        ]
    )


def test_pierwsze_slowa_odrozniaja_narzedzie_od_innych() -> None:
    by_start: dict[str, list[str]] = {}
    for path in _tools():
        words = " ".join(re.findall(r"\w+", " ".join(_first_paragraph(path)).lower())[:SAME_WORDS])
        by_start.setdefault(words, []).append(path.name)

    same = {start: names for start, names in by_start.items() if len(names) > 1}

    assert same == {}, f"te narzędzia zaczynają pierwsze zdanie tymi samymi {SAME_WORDS} słowami; powiedz od razu, czym się różnią: {same}"


def test_agents_md_ani_skill_nie_wskazuja_agentowi_skryptow_ci() -> None:
    documents = [AGENTS_MD, *sorted(SKILLS.glob("*/**/*.md"))]
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
        for path in documents
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CI_TOOLS in line
    ]

    assert found == [], "\n".join(
        [
            *found,
            f"Skrypty {CI_TOOLS} uruchamia workflow; agent odtwarza ich zadanie według docs/agents/pr-i-ci.md, więc AGENTS.md i "
            "skille wskazują narzędzie z tools/ albo nazywają zadanie CI.",
        ]
    )


def test_dokument_agenta_nie_kaze_mu_uruchamiac_skryptu_ci() -> None:
    documents = {path: path.read_text(encoding="utf-8") for path in AGENT_DOCS}
    documents |= {path: ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "" for path in _tools()}
    found = [
        f"{path.relative_to(ROOT).as_posix()}: {line.strip()}"
        for path, text in documents.items()
        for line in text.splitlines()
        if RUNS_CI_TOOL.search(line)
    ]

    assert found == [], "\n".join(
        [
            *found,
            f"Agent uruchamia ten skrypt sam, więc przenieś go z {CI_TOOLS} do tools/ (wtedy trafi do spisu) "
            "albo każ agentowi użyć narzędzia z tools/, które go uruchamia.",
        ]
    )


def _without_subcommand_in_first_sentence(paths: list[Path]) -> dict[Path, list[str]]:
    """Narzędzia z obowiązkową podkomendą, których pierwsze zdanie docstringu nie wymienia żadnej w nawiasie."""

    missing = {}
    for path in paths:
        subcommands = _required_subcommands(path)
        sentence = " ".join(_first_paragraph(path))
        if subcommands and not _names_subcommand_in_brackets(sentence, subcommands):
            missing[path] = subcommands
    return missing


def test_pierwsze_zdanie_narzedzia_z_obowiazkowa_podkomenda_ja_wymienia() -> None:
    missing = {path.relative_to(ROOT).as_posix(): subcommands for path, subcommands in _without_subcommand_in_first_sentence(_tools()).items()}

    assert missing == {}, (
        f"te narzędzia wymagają podkomendy, a pierwsze zdanie docstringu (pozycja spisu) żadnej nie wymienia w nawiasie: {missing}; "
        "napisz w nim w nawiasie podkomendę, której agent używa, np. „(plan --baza origin/main)”, bo agent, który zna "
        "narzędzie tylko ze spisu, uruchamiał je bez podkomendy (pomiar 30–31.10.2026), a gołe słowo nie odróżnia "
        "podkomendy od tego samego słowa w zdaniu (ADR 0022)."
    )


PARSER = "import argparse\ncommands = argparse.ArgumentParser().add_subparsers({})\ncommands.add_parser('plan')\ncommands.add_parser('wykonaj')\n"


def test_podkomenda_na_kazdy_wpis_katalogu_procesow_to_kazdy_klucz_procesu(tmp_path: Path) -> None:
    tool = tmp_path / "narzedzie.py"
    tool.write_text(
        "import argparse\nfrom rozliczenia.centrum.catalog import CATALOG\n"
        "commands = argparse.ArgumentParser().add_subparsers(required=True)\n"
        "for kind in CATALOG.kinds:\n    commands.add_parser(kind.key)\n"
        "for other in EXTRA:\n    commands.add_parser(other.key)\n",
        encoding="utf-8",
    )

    assert _required_subcommands(tool) == ["preparation", "settlement", "efenix", "intermax", "report_entering"]


def test_podkomendy_sa_obowiazkowe_tylko_z_required_true(tmp_path: Path) -> None:
    arguments = {"wymaga": "dest='polecenie', required=True", "bez_required": "dest='polecenie'", "required_false": "dest='polecenie', required=False"}
    for name, argument in arguments.items():
        (tmp_path / f"{name}.py").write_text(PARSER.format(argument), encoding="utf-8")

    assert [_required_subcommands(tmp_path / f"{name}.py") for name in arguments] == [["plan", "wykonaj"], [], []]


@pytest.mark.parametrize(
    ("docstring", "missing"),
    [
        ("Drukuje plan runu CI i wykonuje jego zadanie (plan --baza origin/main), gdy agent chce zobaczyć plan.", False),
        ("Drukuje plan runu CI i wykonuje jego zadanie, gdy agent chce zobaczyć plan.\n\nPodkomendy: (plan --baza origin/main) i (wykonaj).", True),
    ],
    ids=["podkomenda w pierwszym zdaniu", "podkomenda tylko w dalszym akapicie"],
)
def test_podkomenda_liczy_sie_tylko_w_pierwszym_zdaniu_docstringu(tmp_path: Path, docstring: str, missing: bool) -> None:
    tool = tmp_path / "narzedzie.py"
    tool.write_text(f'"""{docstring}\n"""\n\n' + PARSER.format("required=True"), encoding="utf-8")

    assert _without_subcommand_in_first_sentence([tool]) == ({tool: ["plan", "wykonaj"]} if missing else {})


@pytest.mark.parametrize(
    "parsers",
    [
        "for name in ('plan', 'wykonaj'):\n    commands.add_parser(name)\n",
        "commands.add_parser(NAME)\n",
        "",
        "for kind in CATALOG.kinds:\n    pass\nfor kind in OTHER:\n    commands.add_parser(kind.key)\n",
    ],
    ids=["w petli", "ze zmiennej", "bez podkomend", "ta sama nazwa w innej petli"],
)
def test_obowiazkowa_podkomenda_spoza_stalej_nie_przechodzi_po_cichu(tmp_path: Path, parsers: str) -> None:
    tool = tmp_path / "narzedzie.py"
    tool.write_text("import argparse\ncommands = argparse.ArgumentParser().add_subparsers(required=True)\n" + parsers, encoding="utf-8")

    with pytest.raises(ValueError, match=r"żadnej podkomendy nie da się odczytać ze stałej"):
        _required_subcommands(tool)


@pytest.mark.parametrize(
    "extra",
    [
        "inner = commands.add_parser('pokaz').add_subparsers(dest='co')\nfor name in ('a', 'b'):\n    inner.add_parser(name)\n",
        "sub = commands.add_parser('pokaz').add_subparsers(dest='co')\nfor name in ('a', 'b'):\n    sub.add_parser(name)\n",
        "alias = commands\nfor name in ('a', 'b'):\n    alias.add_parser(name)\n",
    ],
    ids=["zagniezdzona grupa w petli", "zagniezdzona pod ta sama nazwa", "alias grupy w petli"],
)
def test_podkomendy_spoza_stalej_obok_stalych_nie_wywracaja_testu(tmp_path: Path, extra: str) -> None:
    tool = tmp_path / "narzedzie.py"
    tool.write_text(PARSER.format("required=True") + extra, encoding="utf-8")

    assert set(_required_subcommands(tool)) >= {"plan", "wykonaj"}


@pytest.mark.parametrize(
    "group",
    ["commands: argparse._SubParsersAction = argparse.ArgumentParser().add_subparsers(required=True)\n", "if (commands := argparse.ArgumentParser().add_subparsers(required=True)):\n    pass\n"],
    ids=["adnotacja", "walrus"],
)
def test_grupa_przypisana_adnotacja_albo_walrusem_daje_swoje_podkomendy(tmp_path: Path, group: str) -> None:
    tool = tmp_path / "narzedzie.py"
    tool.write_text("import argparse\n" + group + "commands.add_parser('plan')\n", encoding="utf-8")

    assert _required_subcommands(tool) == ["plan"]


def test_podkomenda_liczy_sie_tylko_cala_w_nawiasie() -> None:
    sentences = ["Drukuje plan runu CI.", "Drukuje plan runu (planem).", "Drukuje plan runu (plan --baza origin/main)."]

    assert [_names_subcommand_in_brackets(sentence, ["plan", "wykonaj"]) for sentence in sentences] == [False, False, True]


def _imports(tree: ast.Module) -> list[str]:
    """Najwyższe nazwy modułów, które plik importuje, także w funkcjach, bez ``from __future__``."""

    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name.partition(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and node.module != "__future__":
            names.append(node.module.partition(".")[0])
    return names


def _adds_to_sys_path(tree: ast.Module) -> list[str]:
    """Napisy w argumentach każdego ``sys.path.insert`` i ``sys.path.append`` pliku."""

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and ast.unparse(node.func) in ("sys.path.insert", "sys.path.append"):
            found += [part.value for argument in node.args for part in ast.walk(argument) if isinstance(part, ast.Constant) and isinstance(part.value, str)]
    return found


def _agent_files() -> list[Path]:
    hooks = [path for path in sorted((TOOLS / "hooks").iterdir()) if path.is_file() and path.read_bytes().startswith((b"#!/usr/bin/env python3", b'"""'))]
    return [*_tools(), *sorted((TOOLS / "lib").rglob("*.py")), *hooks]


def test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci() -> None:
    ci_modules = {path.stem for path in (TOOLS / "ci").glob("*.py")}
    found = []
    for path in _agent_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        name = path.relative_to(ROOT).as_posix()
        found += [f"{name}: sys.path z {text!r}" for text in _adds_to_sys_path(tree) if text.rstrip("/").endswith("ci")]
        found += [f"{name}: import {module}" for module in _imports(tree) if module in ci_modules]

    assert found == [], "\n".join(
        [*found, f"{CI_TOOLS} to skrypty workflow (ADR 0022): wspólny kod przenieś do tools/lib/, a narzędzie importuje go stamtąd."]
    )


def _library_reaches_tools(root: Path = ROOT) -> list[str]:
    """``plik: …`` dla każdego modułu ``tools/lib/**/*.py`` w ``root``, który sięga do narzędzia z ``tools/*.py``.

    Łapie dokładnie te postacie: ``import X``, ``import X.y`` i ``from X import …`` (także w funkcji i pod ``if``), gdzie
    ``X`` to nazwa pliku ``tools/*.py`` bez ``.py``, oraz ``sys.path.insert`` i ``sys.path.append`` (pełną nazwą) ze
    stałym napisem w argumencie, który kończy się na ``tools``. Import względny (``from . import x``) zostaje w
    ``tools/lib``, więc go nie liczy. Nie widzi importu narzędzia przez pakiet ``tools`` (``import tools.X``,
    ``from tools import X``, ``from tools.X import …``), importu przez ``importlib``, ``__import__``, ``runpy`` i
    ``spec_from_file_location``, ścieżki składanej w czasie biegu bez takiego napisu ani ``sys.path`` pod inną nazwą;
    uruchomienie narzędzia jako procesu (``SCRIPT`` w ``tools/lib/benchmark``) nie jest importem i przechodzi."""

    tools = {path.stem for path in (root / "tools").glob("*.py")}
    found = []
    for path in sorted((root / "tools" / "lib").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        name = path.relative_to(root).as_posix()
        found += [f"{name}: sys.path z {text!r}" for text in _adds_to_sys_path(tree) if text.rstrip("/").endswith("tools")]
        found += [f"{name}: import {module}" for module in _imports(tree) if module in tools]
    return found


def test_biblioteka_narzedzi_nie_importuje_narzedzia_z_tools() -> None:
    found = _library_reaches_tools()

    assert found == [], "\n".join(
        [*found, "tools/lib/ to biblioteki narzędzi (ADR 0022): kod, którego potrzebuje biblioteka, przenieś z narzędzia do tools/lib/, a narzędzie zostaw cienkie."]
    )


def test_straznik_biblioteki_widzi_kazda_postac_importu_narzedzia_z_docstringu(tmp_path: Path) -> None:
    (tmp_path / "tools" / "lib" / "pakiet").mkdir(parents=True)
    (tmp_path / "tools" / "narzedzie.py").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "lib" / "obok.py").write_text("", encoding="utf-8")
    sasiedzi = "from . import obok\nimport obok\nimport json\n"
    siegniecia = (
        "import narzedzie\n"
        "import narzedzie.czesc\n"
        "def f() -> None:\n    from narzedzie import x\n"
        "import sys\nsys.path.insert(0, 'repo/tools')\nsys.path.append('repo/tools/')\nsys.path.insert(0, 'repo/tools/lib')\n"
    )
    (tmp_path / "tools" / "lib" / "pakiet" / "modul.py").write_text(sasiedzi + siegniecia, encoding="utf-8")

    assert _library_reaches_tools(tmp_path) == [
        "tools/lib/pakiet/modul.py: sys.path z 'repo/tools'",
        "tools/lib/pakiet/modul.py: sys.path z 'repo/tools/'",
        "tools/lib/pakiet/modul.py: import narzedzie",
        "tools/lib/pakiet/modul.py: import narzedzie",
        "tools/lib/pakiet/modul.py: import narzedzie",
    ]


def _system_python_scripts() -> set[Path]:
    return {ROOT / script for workflow in sorted(WORKFLOWS.glob("*.yml")) for script in SYSTEM_PYTHON.findall(workflow.read_text(encoding="utf-8"))}


def _outside_stdlib(scripts: set[Path], root: Path = ROOT) -> list[str]:
    """``plik: moduł`` dla każdego importu spoza biblioteki standardowej w domknięciu importów ``scripts`` w ``tools/``."""

    found, seen, queue = [], set(), sorted(scripts)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for module in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            local = next((folder / f"{module}.py" for folder in (path.parent, *MODULE_DIRS) if (folder / f"{module}.py").is_file()), None)
            if local is not None:
                queue.append(local)
            elif module not in sys.stdlib_module_names:
                found.append(f"{path.relative_to(root).as_posix()}: {module}")
    return sorted(found)


def test_skrypt_workflow_na_systemowym_python3_importuje_tylko_biblioteke_standardowa() -> None:
    scripts = _system_python_scripts()

    assert {path.relative_to(ROOT).as_posix() for path in scripts} >= {"tools/plan_ci.py", "tools/ci/werdykt_required.py", "tools/ci/zgloszenia_ci.py"}
    assert _outside_stdlib(scripts) == [], (
        "Skrypt, który workflow uruchamia systemowym python3 runnera, i wszystko, co importuje z tools/, biorą tylko z "
        "biblioteki standardowej, bo ten interpreter nie ma zależności projektu: zastąp import biblioteką standardową "
        "albo przenieś kod, który jej potrzebuje, do kroku uruchamianego z .venv."
    )


def test_domkniecie_importow_skryptu_widzi_import_spoza_biblioteki_w_module_ktory_importuje(tmp_path: Path) -> None:
    (tmp_path / "skrypt.py").write_text("import json\nimport modul\n", encoding="utf-8")
    (tmp_path / "modul.py").write_text("def f() -> None:\n    import yaml\n", encoding="utf-8")

    assert [line.rpartition(": ")[2] for line in _outside_stdlib({tmp_path / "skrypt.py"}, tmp_path)] == ["yaml"]


def test_narzedzie_uruchamia_gh_tylko_przez_github() -> None:
    """Lista albo krotka zaczynająca się od stałej ``"gh"`` stoi w ``tools/`` tylko w ``tools/lib/github.py``: narzędzie
    woła ``gh`` przez ten moduł, który znajduje program na ``PATH`` (także ``gh.cmd`` na Windows), uruchamia go w
    checkoucie z limitem czasu i bez wejścia wołającego. Nazwy programu zbudowanej w czasie biegu test nie widzi."""

    found = [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: {ast.unparse(node)[:80]}"
        for path in sorted({*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push"} - {TOOLS / "lib" / "github.py"})
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "gh"
    ]

    assert found == [], "\n".join([*found, "Uruchom gh przez github.gh albo github.gh_bajty z tools/lib/github.py."])


# Kontrakty napisów między narzędziami CI i ich jedyni właściciele: klucz jednostki planu i zmienna części
# (``tools/lib/jednostka.py``) oraz początki ostatnich linii, które czyta inne narzędzie.
CONTRACTS = (
    (re.compile(r"(?:pytest|krok|skill|narzut):"), TOOLS / "lib" / "jednostka.py"),
    (re.compile(r".*MUTACJE_CZESC", re.DOTALL), TOOLS / "lib" / "jednostka.py"),
    (re.compile(r"MUTACJE OK|SKILLE VERIFY|AKTUALIZACJA:|CI LOKALNIE (?:OK|FAIL)"), TOOLS / "lib" / "ostatnie_linie.py"),
    (re.compile(r"MUTACJE ZMIANY OK"), TOOLS / "mutacje_zmiany.py"),
)


def _texts(tree: ast.AST) -> list[tuple[int, str]]:
    """Napisy kodu, także każdy stały kawałek f-stringu, bez docstringów i innych napisów stojących samotnie jako instrukcja."""

    alone = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
    return [(node.lineno, node.value) for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in alone]


def test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela() -> None:
    """Klucz jednostki planu (``pytest:``, ``krok:``, ``skill:``, ``narzut:``), nazwę zmiennej części ``MUTACJE_CZESC``
    i początek ostatniej linii, którą czyta inne narzędzie, hook albo CI, pisze w ``tools/`` i skryptach skilli tylko
    ich właściciel: reszta składa je i rozbiera przez ``jednostka.Klucz``, ``jednostka.Czesc`` i stałe właściciela, więc
    zmiana napisu po jednej stronie nie zostawia drugiej z cichym „nieznane”. Każdy stały kawałek f-stringu liczy się od
    swojego początku, a nazwy zmiennej szuka w całym kawałku. Napisu złożonego w czasie biegu ani części ``#k/n``
    doklejonej do klucza poza właścicielem test nie widzi: separator ``#`` stoi też w napisach spoza kontraktu."""

    paths = sorted({*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push", *SKILLS.glob("*/scripts/**/*.py")})
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {text[:60]!r} należy do {owner.relative_to(ROOT).as_posix()}"
        for path in paths
        for line, text in _texts(ast.parse(path.read_text(encoding="utf-8")))
        for pattern, owner in CONTRACTS
        if path != owner and pattern.match(text)
    ]

    assert found == [], "\n".join(
        [
            *found,
            "Napis, który jedno narzędzie CI pisze, a inne czyta, pisze tylko jego właściciel: weź klucz, część albo "
            "prefiks od właściciela zamiast pisać napis, bo zmiana napisu po jednej stronie zostawiała drugą z cichym "
            "„nieznane”.",
        ]
    )
