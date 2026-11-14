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
Skrypt, który plik GitHub Actions tego repo uruchamia systemowym ``python3`` runnera (bez zależności projektu), razem
ze wszystkim, co importuje z ``tools/``, używa tylko biblioteki standardowej (które pliki strażnik czyta, mówi
``_system_python_scripts``).

Każdy wpis listy wyjątków dwóch szop (``tools/lib/szopa.toml``, ADR 0034), z której i z reguły katalogu licznik
w workflow rozmiaru PR liczy linie maszynerii procesu, obejmuje co najmniej jeden plik, a żaden plik nie ma dwóch
wpisów. Plik bez wpisu ma grupę z reguły katalogu, więc test nie wymaga wpisu dla nowego pliku.

Granica: test nie ocenia, czy zdanie mówi „kiedy” słowami sytuacji agenta (czerwone CI, przed merge'em); to łapie
tylko przegląd. Postacie, których nie łapią strażnicy kierunku zależności, kontraktu napisów i skryptów
systemowego ``python3``, są próbkami ``ZNANE_LUKI_*`` przy ich testach.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
import posixpath
import re
import sys
from typing import get_args

import pytest
import yaml

import rozmiar_pr
from szopa import LISTA
from rozliczenia.centrum.contract import common as common_contract

from tests.fixtures.expect import assert_expected
from tests.fixtures.git_repo import git
from tests.fixtures.skladnia import drzewo, pamiec_drzew, wezly
from tests.fixtures.znane_luki import assert_znane_luki, zapisz

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
# Skrypt uruchamiany systemowym python3 runnera, bez zależności projektu, w całym tekście pliku *.yml albo *.yaml pod
# .github albo pliku, do którego prowadzi lokalne uses (./…, .\…, $/…: action.yml/action.yaml, workflow wielokrotnego
# użytku); uses docker://… i REMOTE_ACTION są pomijane, a plik albo uses, którego strażnik nie umie przeczytać, wywraca
# test (granica w _system_python_scripts).
SYSTEM_PYTHON = re.compile(r"\bpython3\s+(tools/\S+\.py)\b")
# Akcja z innego repo w uses, którą strażnik pomija świadomie: właściciel/repo[/ścieżka]@ref, gdzie właściciel ma znaki
# nazwy konta GitHuba, repo znaki nazwy repo, każdy człon jest niepusty, bez spacji, „\”, „@” i nie jest „.” ani „..”,
# a ref jest niepusty i bez spacji.
REMOTE_ACTION = re.compile(r"[A-Za-z0-9-]+/(?!\.\.?[/@])[A-Za-z0-9_.-]+(?:/(?!\.\.?[/@])[^\s/\\@]+)*@[^\s@]+")
# Katalogi, z których skrypt z tools/ importuje moduły projektu (sys.path jego i testów).
MODULE_DIRS = (TOOLS / "lib", TOOLS, TOOLS / "ci")


@pytest.fixture(autouse=True, scope="module")
def drzewa_raz_na_modul() -> Iterator[None]:
    with pamiec_drzew():
        yield


def _tools() -> list[Path]:
    return sorted(TOOLS.glob("*.py"))


def _first_paragraph(path: Path) -> list[str]:
    docstring = ast.get_docstring(drzewo(path)) or ""
    return docstring.split("\n\n", 1)[0].splitlines()


def _required_subcommands(path: Path) -> list[str]:
    """Stałe nazwy ``add_parser`` narzędzia, które ma ``add_subparsers(required=True)``; pusta lista bez takiej grupy.

    Czyta każde ``add_parser("<nazwa>")`` ze stałą nazwą w pliku, bez rozróżniania grup, bo pierwsze zdanie ma wymienić
    którąkolwiek z nich, a podkomenda na każdy wpis katalogu procesów (``add_parser(kind.key)`` w ciele pętli
    ``for kind in CATALOG.kinds``, Skrypt dla maszyn) to każdy klucz procesu (``common_contract.ProcessKey``). Podkomendy dodane
    inaczej (ze zmiennej, w innej pętli, także po zmiennej o tej samej nazwie) obok tych nie są sprawdzane. Narzędzie z ``required=True``, z którego nie da się
    odczytać żadnej nazwy, to ``ValueError``, bo pusta lista przepuściłaby je bez sprawdzenia.
    """

    tree = drzewo(path)
    calls = [
        (node.func.attr, node)
        for node in wezly(tree)
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
        for loop in wezly(tree)
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
    documents |= {path: ast.get_docstring(drzewo(path)) or "" for path in _tools()}
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
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            names += [alias.name.partition(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and node.module != "__future__":
            names.append(node.module.partition(".")[0])
    return names


def _adds_to_sys_path(tree: ast.Module) -> list[str]:
    """Napisy w argumentach każdego ``sys.path.insert`` i ``sys.path.append`` pliku."""

    found = []
    for node in wezly(tree):
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
        tree = drzewo(path)
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
    ``tools/lib``, więc go nie liczy, a uruchomienie narzędzia jako procesu (``SCRIPT`` w ``tools/lib/benchmark``) nie
    jest importem i przechodzi. Postacie, których nie łapie, są próbkami w ``ZNANE_LUKI_NARZEDZI``."""

    tools = {path.stem for path in (root / "tools").glob("*.py")}
    found = []
    for path in sorted((root / "tools" / "lib").rglob("*.py")):
        tree = drzewo(path)
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


def _drzewo_tools(korzen: Path) -> None:
    """Drzewo ``tools/`` w ``korzen`` z narzędziem ``narzedzie``, skryptem CI ``skrypt`` i pustym hookiem ``pre-push``."""

    for katalog in ("lib", "ci", "hooks"):
        (korzen / "tools" / katalog).mkdir(parents=True)
    for plik in (korzen / "tools" / "narzedzie.py", korzen / "tools" / "ci" / "skrypt.py", korzen / "tools" / "hooks" / "pre-push"):
        plik.write_text("", encoding="utf-8")


def _zgloszenia_straznika(test: Callable[[], None], korzen: Path) -> list[str]:
    """Linie zgłoszenia testu strażnika całego repo uruchomionego na drzewie ``korzen`` zamiast repozytorium, bez wcięcia,
    które pytest dodaje liniom komunikatu po pierwszej."""

    kontrakty = tuple((wzor, korzen / wlasciciel.relative_to(ROOT)) for wzor, wlasciciel in CONTRACTS)
    with pytest.MonkeyPatch.context() as podmiana:
        for nazwa, wartosc in {"ROOT": korzen, "TOOLS": korzen / "tools", "SKILLS": korzen / ".agents" / "skills", "CONTRACTS": kontrakty}.items():
            podmiana.setattr(sys.modules[__name__], nazwa, wartosc)
        try:
            test()
        except AssertionError as blad:
            return [linia.strip() for linia in str(blad).splitlines()]
    return []


def _wedlug_probek(pliki: Mapping[str, Path], korzen: Path, linie: list[str]) -> dict[str, list[str]]:
    """Linie zgłoszenia strażnika na drzewie ``korzen`` przy próbce, której plik zaczyna linię."""

    opisy = {plik.relative_to(korzen).as_posix(): opis for opis, plik in pliki.items()}
    zgloszenia: dict[str, list[str]] = {opis: [] for opis in pliki}
    for linia in linie:
        if (opis := opisy.get(linia.partition(":")[0])) is not None:
            zgloszenia[opis].append(linia)
    return zgloszenia


def test_straznik_skryptow_ci_widzi_import_skryptu_i_sys_path_z_napisem_w_narzedziu_bibliotece_i_hooku(tmp_path: Path) -> None:
    _drzewo_tools(tmp_path)
    pliki = {
        "narzędzie": tmp_path / "tools" / "narzedzie.py",
        "biblioteka": tmp_path / "tools" / "lib" / "modul.py",
        "hook": tmp_path / "tools" / "hooks" / "hook.py",
    }
    pliki["narzędzie"].write_text('"""Narzędzie."""\nimport skrypt\n', encoding="utf-8")
    biblioteka = "import json\ndef f() -> None:\n    from skrypt import x\nimport sys\nsys.path.insert(0, 'repo/tools/ci/')\nsys.path.append('repo/tools')\n"
    pliki["biblioteka"].write_text(biblioteka, encoding="utf-8")
    pliki["hook"].write_text("#!/usr/bin/env python3\nimport skrypt.czesc\n", encoding="utf-8")

    assert _wedlug_probek(pliki, tmp_path, _zgloszenia_straznika(test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci, tmp_path)) == {
        "narzędzie": ["tools/narzedzie.py: import skrypt"],
        "biblioteka": ["tools/lib/modul.py: sys.path z 'repo/tools/ci/'", "tools/lib/modul.py: import skrypt"],
        "hook": ["tools/hooks/hook.py: import skrypt"],
    }


# Znane luki strażników kierunku zależności w tools/ (tests/fixtures/znane_luki.py): opis postaci → moduł, który sięga
# do skryptu CI ``skrypt`` (``ZNANE_LUKI_SKRYPTOW_CI`` w tools/lib, ``ZNANE_LUKI_HOOKOW`` w tools/hooks) albo do
# narzędzia ``narzedzie`` (``ZNANE_LUKI_NARZEDZI`` w tools/lib) drzewa ``_drzewo_tools``, a mimo to przechodzi przez
# strażnika.
ZNANE_LUKI_SKRYPTOW_CI = {
    "import przez pakiet tools": "import tools.ci.skrypt\n",
    "from tools.ci import": "from tools.ci import skrypt\n",
    "importlib.import_module": 'import importlib\n\nSKRYPT = importlib.import_module("skrypt")\n',
    "__import__": 'SKRYPT = __import__("skrypt")\n',
    "runpy.run_path": 'from pathlib import Path\nimport runpy\n\nSKRYPT = runpy.run_path(str(Path(__file__).parents[1] / "ci" / "skrypt.py"))\n',
    "spec_from_file_location": """\
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SPEC = spec_from_file_location("skrypt", Path(__file__).parents[1] / "ci" / "skrypt.py")
assert SPEC is not None
SKRYPT = module_from_spec(SPEC)
""",
    "ścieżka w zmiennej": 'from pathlib import Path\nimport sys\n\nCI = Path(__file__).parents[1] / "ci"\nsys.path.insert(0, str(CI))\n',
    "sys.path pod inną nazwą": 'from sys import path\n\npath.insert(0, "repo/tools/ci")\n',
    "sys pod aliasem": 'import sys as system\n\nsystem.path.insert(0, "repo/tools/ci")\n',
    "sys.path.extend": 'import sys\n\nsys.path.extend(["repo/tools/ci"])\n',
    "przypisanie do wycinka sys.path": 'import sys\n\nsys.path[:0] = ["repo/tools/ci"]\n',
}
ZNANE_LUKI_HOOKOW = {
    "hook bez shebangu i docstringu": "import sys\n\nimport skrypt\n",
}
ZNANE_LUKI_NARZEDZI = {
    "import przez pakiet tools": "import tools.narzedzie\n",
    "from tools import": "from tools import narzedzie\n",
    "from tools.narzedzie import": "from tools.narzedzie import main\n",
    "importlib.import_module": 'import importlib\n\nNARZEDZIE = importlib.import_module("narzedzie")\n',
    "__import__": 'NARZEDZIE = __import__("narzedzie")\n',
    "runpy.run_path": 'from pathlib import Path\nimport runpy\n\nNARZEDZIE = runpy.run_path(str(Path(__file__).parents[1] / "narzedzie.py"))\n',
    "spec_from_file_location": """\
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SPEC = spec_from_file_location("narzedzie", Path(__file__).parents[1] / "narzedzie.py")
assert SPEC is not None
NARZEDZIE = module_from_spec(SPEC)
""",
    "ścieżka bez napisu kończącego się na tools": "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).parents[1]))\n",
    "ścieżka w zmiennej": 'import sys\n\nTOOLS = "repo/tools"\nsys.path.insert(0, TOOLS)\n',
    "sys.path pod inną nazwą": 'from sys import path\n\npath.insert(0, "repo/tools")\n',
    "sys pod aliasem": 'import sys as system\n\nsystem.path.insert(0, "repo/tools")\n',
    "sys.path.extend": 'import sys\n\nsys.path.extend(["repo/tools"])\n',
    "przypisanie do wycinka sys.path": 'import sys\n\nsys.path[:0] = ["repo/tools"]\n',
}


@pytest.mark.parametrize(
    ("nazwa", "probki", "katalog", "straznik"),
    [
        ("ZNANE_LUKI_SKRYPTOW_CI", ZNANE_LUKI_SKRYPTOW_CI, "lib", lambda korzen: _zgloszenia_straznika(test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci, korzen)),
        ("ZNANE_LUKI_HOOKOW", ZNANE_LUKI_HOOKOW, "hooks", lambda korzen: _zgloszenia_straznika(test_narzedzie_biblioteka_ani_hook_nie_siega_do_skryptow_ci, korzen)),
        ("ZNANE_LUKI_NARZEDZI", ZNANE_LUKI_NARZEDZI, "lib", _library_reaches_tools),
    ],
    ids=["skrypty-ci-z-biblioteki", "skrypty-ci-z-hooka", "narzedzia-z-biblioteki"],
)
def test_znane_luki_kierunku_zaleznosci_tools_przechodza_przez_straznikow(
    tmp_path: Path, nazwa: str, probki: dict[str, str], katalog: str, straznik: Callable[[Path], list[str]]
) -> None:
    _drzewo_tools(tmp_path)
    pliki = zapisz(probki, tmp_path / "tools" / katalog)

    zgloszenia = _wedlug_probek(pliki, tmp_path, straznik(tmp_path))

    assert_znane_luki(zgloszenia, f"tests/test_spis_narzedzi.py ({nazwa})")


def _system_python_scripts(root: Path = ROOT) -> set[Path]:
    """Skrypty ``python3 tools/….py`` z całego tekstu plików GitHub Actions, które GitHub uruchamia z tego repo: każdego
    ``*.yml`` i ``*.yaml`` pod ``.github`` (workflowy i akcje złożone) oraz każdego pliku, do którego prowadzi lokalne
    ``uses`` z pliku już czytanego (``./…``, ``.\\…`` albo ``$/…``, jak w runnerze GitHuba; ``action.yml`` albo
    ``action.yaml`` katalogu akcji, plik workflowu wielokrotnego użytku), w dowolnym miejscu repo.

    Regex biegnie po całym tekście pliku, więc łapie polecenie w każdym polu (``run``, ``env``, ``matrix``, ``with``),
    a parser YAML służy tylko do znalezienia ``uses``. Świadomie pomija tylko dwie postacie ``uses``, które nie leżą
    w tym repo: ``docker://…`` i akcję z innego repo w postaci ``REMOTE_ACTION`` (``właściciel/repo[/ścieżka]@ref``).
    Czego nie umie przeczytać, nie pomija: plik, którego parser nie czyta, ``uses``, które nie jest stałym napisem,
    ``uses`` żadnej z pięciu postaci i lokalne ``uses``, którego celu nie ma w repo po rozwiązaniu ``..`` od korzenia
    repo (także akcja spod katalogu z ``actions/checkout`` z ``path:``), wywracają test z nazwą pliku. Granica:
    strażnik nie czyta plików, które uruchamia krok (skrypt powłoki albo plik ``main`` akcji JavaScript, które same
    wołają ``python3``), ani akcji tego repo wołanej jako ``właściciel/repo/…@ref``; próbki
    ``ZNANE_LUKI_SYSTEMOWEGO_PYTHONA`` to luki znane, nie pełna lista."""

    queue = sorted({*(root / ".github").rglob("*.yml"), *(root / ".github").rglob("*.yaml")})
    seen, scripts = set(), set()
    while queue:
        plik = queue.pop()
        if plik in seen:
            continue
        seen.add(plik)
        nazwa = plik.relative_to(root).as_posix()
        try:
            tekst = plik.read_text(encoding="utf-8")
            dane = yaml.safe_load(tekst)
        except (UnicodeDecodeError, yaml.YAMLError) as error:
            pytest.fail(f"{nazwa}: parser YAML nie czyta pliku, więc strażnik nie wie, za którym uses iść: {error}")
        scripts |= {root / script for script in SYSTEM_PYTHON.findall(tekst)}
        queue += [cel for uses in _uses(dane) for cel in _local_targets(nazwa, uses, root)]
    return scripts


def _uses(dane: object) -> Iterator[object]:
    """Każda wartość klucza ``uses`` w drzewie YAML, na dowolnej głębokości."""

    if isinstance(dane, dict):
        for klucz, wartosc in dane.items():
            if klucz == "uses":
                yield wartosc
            else:
                yield from _uses(wartosc)
    elif isinstance(dane, list):
        for element in dane:
            yield from _uses(element)


def _local_targets(nazwa: str, uses: object, root: Path) -> list[Path]:
    """Pliki repo, które GitHub czyta dla ``uses`` z pliku ``nazwa``: dla lokalnego ``uses`` (``./``, ``.\\``, ``$/``)
    ``action.yml`` albo ``action.yaml`` katalogu akcji albo plik workflowu wielokrotnego użytku, dla ``docker://…``
    i ``REMOTE_ACTION`` pusta lista; każda inna wartość wywraca test."""

    if not isinstance(uses, str) or "${{" in uses:
        pytest.fail(
            f"{nazwa}: uses: {uses!r} nie jest stałym napisem, więc strażnik nie wie, który plik GitHub uruchamia: "
            "wpisz uses jako ścieżkę ./… albo właściciel/repo@ref bez wyrażenia ${{ … }}."
        )
    if uses.startswith(("./", ".\\")):
        sciezka = uses.replace("\\", "/")
    elif uses.startswith("$/") and "@" not in uses:
        sciezka = uses.removeprefix("$/").lstrip("/").replace("\\", "/")
    elif uses.startswith("docker://") or REMOTE_ACTION.fullmatch(uses):
        return []
    else:
        pytest.fail(
            f"{nazwa}: uses: {uses} nie ma żadnej z postaci, które strażnik zna z runnera GitHuba (./…, .\\…, $/… bez @, "
            "docker://…, właściciel/repo[/ścieżka]@ref), więc nie wie, co ten krok uruchamia: zapisz uses w jednej z nich."
        )
    cel = posixpath.normpath(sciezka)
    kandydaci = [root / cel] if cel.endswith((".yml", ".yaml")) else [root / cel / "action.yml", root / cel / "action.yaml"]
    pliki = [plik for plik in kandydaci if cel != ".." and not cel.startswith("../") and plik.is_file()]
    if not pliki:
        pytest.fail(
            f"{nazwa}: uses: {uses} nie prowadzi do action.yml ani action.yaml (ani pliku workflowu) w repo, licząc od "
            "korzenia repo, więc strażnik nie widzi, co ten krok uruchamia: wskaż w uses katalog akcji od korzenia repo "
            "(bez katalogu z actions/checkout z path:) albo przenieś akcję do repo."
        )
    return pliki


def _outside_stdlib(scripts: set[Path], root: Path = ROOT) -> list[str]:
    """``plik: moduł`` dla każdego importu spoza biblioteki standardowej w domknięciu importów ``scripts`` w ``tools/``."""

    found, seen, queue = [], set(), sorted(scripts)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for module in _imports(drzewo(path)):
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
        "Skrypt, który plik *.yml albo *.yaml pod .github albo plik z lokalnego uses (./…, .\\…, $/…: "
        "action.yml/action.yaml, workflow wielokrotnego użytku) "
        "uruchamia systemowym python3 runnera, i wszystko, co importuje z tools/, biorą tylko z biblioteki standardowej, "
        "bo ten interpreter nie ma zależności projektu: zastąp import biblioteką standardową albo przenieś kod, który "
        "jej potrzebuje, do kroku uruchamianego z .venv."
    )



def _zapisz_drzewo(korzen: Path, pliki: Mapping[str, str | bytes]) -> None:
    for sciezka, tresc in pliki.items():
        (korzen / sciezka).parent.mkdir(parents=True, exist_ok=True)
        (korzen / sciezka).write_bytes(tresc if isinstance(tresc, bytes) else tresc.encode("utf-8"))


def _akcja(kroki: str) -> str:
    return f"runs:\n  using: composite\n  steps:\n{kroki}"


def test_skrypt_systemowego_python3_z_kazdego_pola_workflowu_i_akcji_ktora_github_uruchamia_wywraca_straznika(tmp_path: Path) -> None:
    """Strażnik czyta cały tekst workflowu (polecenie w ``env`` i ``matrix``, nie tylko w ``run``), każdy plik ``.yaml``
    pod ``.github``, akcję spoza ``.github`` pod ``uses`` z ``..``, ``$/``, ``.\\`` i pod ``uses`` z akcji oraz workflow
    wielokrotnego użytku, pomija ``docker://…`` i akcję z innego repo, kończy na cyklu akcji, a skryptu akcji, której nic
    nie woła spoza ``.github``, nie zgłasza (przegląd #1689: W3 r1, W2 r2, W1 r3; przegląd #1709: W1 r1, W1 r2)."""

    _zapisz_drzewo(
        tmp_path,
        {
            ".github/workflows/ci.yml": (
                "on: push\njobs:\n  a:\n    strategy:\n      matrix:\n        polecenie: [python3 tools/z_matrix.py]\n"
                "    steps:\n      - uses: actions/checkout@v4\n      - env:\n          POLECENIE: python3 tools/z_env.py\n"
                "        run: $POLECENIE\n      - run: ${{ matrix.polecenie }}\n      - uses: ./ci/x/../a\n"
                "      - uses: $/ci/d\n      - uses: .\\ci\\e\n      - uses: github/codeql-action/upload-sarif@v3\n"
                "      - uses: docker://alpine:3\n"
                "  r:\n    uses: ./.github/workflows/r.yml\n"
            ),
            ".github/workflows/r.yml": "on: workflow_call\njobs:\n  a:\n    steps:\n      - run: echo\n",
            ".github/actions/b/action.yaml": _akcja("    - run: python3 tools/z_github_yaml.py\n      shell: bash\n"),
            "ci/a/action.yml": _akcja("    - uses: ./ci/b/\n"),
            "ci/b/action.yaml": _akcja("    - run: |\n        echo start\n        python3 tools/z_akcji.py\n      shell: bash\n    - uses: ./ci/a\n"),
            "ci/c/action.yml": _akcja("    - run: python3 tools/nikt.py\n      shell: bash\n"),
            "ci/d/action.yml": _akcja("    - run: python3 tools/z_dolara.py\n      shell: bash\n"),
            "ci/e/action.yml": _akcja("    - run: python3 tools/z_ukosnika.py\n      shell: bash\n"),
            **{f"tools/{nazwa}.py": "import yaml\n" for nazwa in ("z_matrix", "z_env", "z_github_yaml", "z_akcji", "nikt", "z_dolara", "z_ukosnika")},
        },
    )

    assert _outside_stdlib(_system_python_scripts(tmp_path), tmp_path) == [
        "tools/z_akcji.py: yaml",
        "tools/z_dolara.py: yaml",
        "tools/z_env.py: yaml",
        "tools/z_github_yaml.py: yaml",
        "tools/z_matrix.py: yaml",
        "tools/z_ukosnika.py: yaml",
    ]


# Pliki, których strażnik nie umie przeczytać: opis → pliki drzewa (repo pod ``repo/``, obok niego ``poza/``) i początek
# odmowy, która nazywa plik.
NIECZYTELNE: dict[str, tuple[dict[str, str | bytes], str]] = {
    "parser YAML nie czyta pliku": ({"repo/.github/workflows/zly.yml": "jobs:\n  a:\n    steps:\n      - uses: ./ci/a\n     zły: [\n"}, ".github/workflows/zly.yml: parser YAML"),
    "plik nie jest w UTF-8": ({"repo/.github/workflows/zly.yml": "run: python3 tools/skrypt.py # \xff".encode("latin-1")}, ".github/workflows/zly.yml: parser YAML"),
    "uses po actions/checkout z path: liczone od katalogu roboczego runu": (
        {
            "repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          path: repo\n      - uses: ./repo/ci/a\n",
            "repo/ci/a/action.yml": _akcja("    - run: python3 tools/skrypt.py\n      shell: bash\n"),
        },
        ".github/workflows/ci.yml: uses: ./repo/ci/a nie prowadzi",
    ),
    "uses z .. poza repo": (
        {"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: ./../poza/a\n", "poza/a/action.yml": _akcja("    - run: python3 tools/skrypt.py\n      shell: bash\n")},
        ".github/workflows/ci.yml: uses: ./../poza/a nie prowadzi",
    ),
    "lokalna akcja bez action.yml w akcji": (
        {"repo/.github/actions/a/action.yml": _akcja("    - uses: ./ci/brak\n")},
        ".github/actions/a/action.yml: uses: ./ci/brak nie prowadzi",
    ),
    "uses nie jest napisem": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: [./ci/a]\n"}, ".github/workflows/ci.yml: uses: ['./ci/a'] nie jest stałym"),
    "akcja z innego repo bez @ref": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout\n"}, ".github/workflows/ci.yml: uses: actions/checkout nie ma żadnej"),
    "akcja z innego repo z pustym członem": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions//checkout@v4\n"}, ".github/workflows/ci.yml: uses: actions//checkout@v4 nie ma żadnej"),
    "akcja z innego repo ze spacją": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: 'actions/checkout/pod katalog@v4'\n"}, ".github/workflows/ci.yml: uses: actions/checkout/pod katalog@v4 nie ma żadnej"),
    "akcja z innego repo ze ścieżką z ..": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout/../x@v4\n"}, ".github/workflows/ci.yml: uses: actions/checkout/../x@v4 nie ma żadnej"),
    "akcja z innego repo z pustym ref": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@\n"}, ".github/workflows/ci.yml: uses: actions/checkout@ nie ma żadnej"),
    "$/ z @ref (runner też odmawia)": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: $/ci/a@main\n"}, ".github/workflows/ci.yml: uses: $/ci/a@main nie ma żadnej"),
    "ścieżka bez prefiksu lokalnego": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: ../ci/a\n"}, ".github/workflows/ci.yml: uses: ../ci/a nie ma żadnej"),
    "uses z wyrażeniem": ({"repo/.github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: ${{ matrix.akcja }}\n"}, ".github/workflows/ci.yml: uses: '${{ matrix.akcja }}' nie jest stałym"),
}


@pytest.mark.parametrize("opis", NIECZYTELNE)
def test_plik_ktorego_straznik_systemowego_python3_nie_umie_przeczytac_wywraca_go_z_nazwa_pliku(tmp_path: Path, opis: str) -> None:
    pliki, odmowa = NIECZYTELNE[opis]
    _zapisz_drzewo(tmp_path, pliki)

    with pytest.raises(pytest.fail.Exception, match=re.escape(odmowa)):
        _system_python_scripts(tmp_path / "repo")


# Znane luki strażnika skryptów systemowego python3 (tests/fixtures/znane_luki.py): „klasa: postać” → krok workflowu
# ``.github/workflows/ci.yml`` i pliki drzewa próbki, w którym ``tools/skrypt.py`` uruchomiony systemowym python3 bierze
# moduł spoza biblioteki standardowej, a mimo to drzewo przechodzi przez ``_system_python_scripts`` i ``_outside_stdlib``.
ZNANE_LUKI_SYSTEMOWEGO_PYTHONA = {
    "czyta tylko instrukcje importu: importlib.import_module": ("run: python3 tools/skrypt.py", {"tools/skrypt.py": 'import importlib\n\nYAML = importlib.import_module("yaml")\n'}),
    "zna tylko dosłowne python3 tools/….py w tekście: polecenie złożone w biegu": ('run: S=tools/skrypt.py; python3 "$S"', {"tools/skrypt.py": "import yaml\n"}),
    "zna tylko dosłowne python3 tools/….py w tekście: flaga interpretera przed skryptem": ("run: python3 -u tools/skrypt.py", {"tools/skrypt.py": "import yaml\n"}),
    "zna tylko dosłowne python3 tools/….py w tekście: kod Pythona kroku z shell: python3 {0}, który importuje z tools/": (
        "shell: python3 {0}\n        run: import sys; sys.path.insert(0, 'tools'); import skrypt",
        {"tools/skrypt.py": "import yaml\n"},
    ),
    # dbm.sqlite3 jest od Pythona 3.13, a python3 runnera ubuntu-latest (Ubuntu 24.04) to 3.12.
    "zna najwyższą nazwę modułu i bibliotekę standardową Pythona testu, nie python3 runnera: dbm.sqlite3": ("run: python3 tools/skrypt.py", {"tools/skrypt.py": "import dbm.sqlite3\n"}),
    "czyta tylko pliki GitHub Actions, nie pliki, które krok uruchamia: skrypt powłoki, który woła python3": (
        "run: bash tools/skrypt.sh",
        {"tools/skrypt.sh": "python3 tools/skrypt.py\n", "tools/skrypt.py": "import yaml\n"},
    ),
    "czyta tylko pliki GitHub Actions, nie pliki, które krok uruchamia: plik main lokalnej akcji JavaScript, który woła python3": (
        "uses: ./ci/js",
        {
            "ci/js/action.yml": "runs:\n  using: node20\n  main: index.js\n",
            "ci/js/index.js": 'require("child_process").execSync("python3 tools/skrypt.py");\n',
            "tools/skrypt.py": "import yaml\n",
        },
    ),
    "idzie tylko za lokalnym uses: ./…: akcja tego repo spoza .github spod uses: właściciel/repo/ścieżka@ref": (
        "uses: maximiseartai/MAXIMISEART-Dad/ci/a@main",
        {"ci/a/action.yml": _akcja("    - run: python3 tools/skrypt.py\n      shell: bash\n"), "tools/skrypt.py": "import yaml\n"},
    ),
}


def test_znane_luki_skryptow_systemowego_pythona_przechodza_przez_straznika(tmp_path: Path) -> None:
    zgloszenia = {}
    for numer, (opis, (krok, pliki)) in enumerate(ZNANE_LUKI_SYSTEMOWEGO_PYTHONA.items()):
        korzen = tmp_path / str(numer)
        _zapisz_drzewo(korzen, {".github/workflows/ci.yml": f"jobs:\n  a:\n    steps:\n      - {krok}\n", **pliki})
        zgloszenia[opis] = _outside_stdlib(_system_python_scripts(korzen), korzen)

    assert_znane_luki(zgloszenia, "tests/test_spis_narzedzi.py (ZNANE_LUKI_SYSTEMOWEGO_PYTHONA)")

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
        for node in wezly(drzewo(path))
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

    alone = {id(node.value) for node in wezly(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
    return [(node.lineno, node.value) for node in wezly(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in alone]


def test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela() -> None:
    """Klucz jednostki planu (``pytest:``, ``krok:``, ``skill:``, ``narzut:``), nazwę zmiennej części ``MUTACJE_CZESC``
    i początek ostatniej linii, którą czyta inne narzędzie, hook albo CI, pisze w ``tools/`` i skryptach skilli tylko
    ich właściciel: reszta składa je i rozbiera przez ``jednostka.Klucz``, ``jednostka.Czesc`` i stałe właściciela, więc
    zmiana napisu po jednej stronie nie zostawia drugiej z cichym „nieznane”. Każdy stały kawałek f-stringu liczy się od
    swojego początku, a nazwy zmiennej szuka w całym kawałku. Postacie, których nie łapie, są próbkami w
    ``ZNANE_LUKI_KONTRAKTU``."""

    paths = sorted({*TOOLS.rglob("*.py"), TOOLS / "hooks" / "pre-push", *SKILLS.glob("*/scripts/**/*.py")})
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {text[:60]!r} należy do {owner.relative_to(ROOT).as_posix()}"
        for path in paths
        for line, text in _texts(drzewo(path))
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


def test_straznik_kontraktu_napisow_widzi_napis_i_kawalek_fstringu_poza_wlascicielem(tmp_path: Path) -> None:
    _drzewo_tools(tmp_path)
    pliki = {
        "biblioteka": tmp_path / "tools" / "lib" / "modul.py",
        "hook pre-push": tmp_path / "tools" / "hooks" / "pre-push",
        "skrypt skilla": tmp_path / ".agents" / "skills" / "verify-x" / "scripts" / "skrypt.py",
        "właściciel": tmp_path / CONTRACTS[2][1].relative_to(ROOT),
    }
    pliki["biblioteka"].write_text(
        'def f(x: str) -> str:\n    """MUTACJE OK w docstringu."""\n    "MUTACJE OK samotnie"\n'
        '    print("MUTACJE OK")\n    print(f"{x}pytest:{x}")\n    return f"{x}=1 MUTACJE_CZESC {x}"\n',
        encoding="utf-8",
    )
    pliki["hook pre-push"].write_text('print("AKTUALIZACJA: niepotrzebna")\n', encoding="utf-8")
    pliki["skrypt skilla"].parent.mkdir(parents=True)
    pliki["skrypt skilla"].write_text('KONIEC = "SKILLE VERIFY: brak"\n', encoding="utf-8")
    pliki["właściciel"].write_text('KONIEC = "MUTACJE OK"\n', encoding="utf-8")

    zgloszenia = _wedlug_probek(pliki, tmp_path, _zgloszenia_straznika(test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela, tmp_path))

    assert {opis: sorted(linia.split(": ")[0].rpartition(":")[2] for linia in linie) for opis, linie in zgloszenia.items()} == {
        "biblioteka": ["4", "5", "6"],
        "hook pre-push": ["1"],
        "skrypt skilla": ["1"],
        "właściciel": [],
    }


# Znane luki strażnika kontraktu napisów (tests/fixtures/znane_luki.py): opis postaci → moduł w tools/lib drzewa
# ``_drzewo_tools``, który poza właścicielem pisze klucz jednostki planu, zmienną części albo początek ostatniej linii
# z ``CONTRACTS``, a mimo to przechodzi przez strażnika.
ZNANE_LUKI_KONTRAKTU = {
    "napis złożony w trakcie działania": 'KONIEC = "MUTACJE " + "OK"\n',
    "klucz z kawałków w f-stringu": "def klucz(plik: str) -> str:\n    return f\"{'pytest'}:{plik}\"\n",
    "część #k/n doklejona do klucza": 'def jednostka(klucz: str, k: int, n: int) -> str:\n    return f"{klucz}#{k}/{n}"\n',
    "klucz przez str.format": 'def klucz(plik: str) -> str:\n    return "{}:{}".format("pytest", plik)\n',
    "napis z join": 'KONIEC = " ".join(("MUTACJE", "OK"))\n',
    "napis od nowej linii": 'print("\\nMUTACJE OK")\n',
    "napis zmieniony metodą": 'KONIEC = "mutacje ok".upper()\n',
    "napis w bajtach": 'KONIEC = b"MUTACJE OK".decode()\n',
}


def test_znane_luki_kontraktu_napisow_przechodza_przez_straznika(tmp_path: Path) -> None:
    _drzewo_tools(tmp_path)
    pliki = zapisz(ZNANE_LUKI_KONTRAKTU, tmp_path / "tools" / "lib")

    zgloszenia = _wedlug_probek(pliki, tmp_path, _zgloszenia_straznika(test_kontrakt_napisow_miedzy_narzedziami_ci_ma_jednego_wlasciciela, tmp_path))

    assert_znane_luki(zgloszenia, "tests/test_spis_narzedzi.py (ZNANE_LUKI_KONTRAKTU)")


def test_kazdy_wpis_listy_dwoch_szop_obejmuje_plik_a_zaden_plik_nie_ma_dwoch_wpisow() -> None:
    wpisy = rozmiar_pr.wpisy((ROOT / "tools" / "lib" / "szopa.toml").read_text(encoding="utf-8"))
    pliki = sorted(
        nazwa
        for nazwa in set(filter(None, git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")))
        if (ROOT / nazwa).is_file()
    )
    obejmujace = {nazwa: rozmiar_pr.obejmujace(wpisy, nazwa) for nazwa in pliki}
    bledy = [f"{nazwa}: obejmuje go kilka wpisów ({', '.join(swoje)})" for nazwa, swoje in obejmujace.items() if len(swoje) > 1]
    bledy += [f"{wpis}: wpis nie obejmuje żadnego pliku" for wpis in wpisy if not any(wpis in swoje for swoje in obejmujace.values())]

    assert bledy == [], "\n".join(
        [
            *bledy,
            f"{LISTA} trzyma tylko wyjątki od reguły katalogu rozmiar_pr.REGULY (ADR 0034): wpis bez pliku "
            "usuń albo popraw jego ścieżkę, a plik z kilkoma wpisami zostaw w jednym.",
        ]
    )
