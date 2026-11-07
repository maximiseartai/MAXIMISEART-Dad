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

Granica: test nie ocenia, czy zdanie mówi „kiedy” słowami sytuacji agenta (czerwone CI, przed merge'em); to łapie
tylko przegląd.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

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


def _tools() -> list[Path]:
    return sorted(TOOLS.glob("*.py"))


def _first_paragraph(path: Path) -> list[str]:
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return docstring.split("\n\n", 1)[0].splitlines()


def _required_subcommands(path: Path) -> list[str]:
    """Stałe nazwy ``add_parser`` narzędzia, które ma ``add_subparsers(required=True)``; pusta lista bez takiej grupy.

    Czyta każde ``add_parser("<nazwa>")`` ze stałą nazwą w pliku, bez rozróżniania grup, bo pierwsze zdanie ma wymienić
    którąkolwiek z nich. Podkomendy dodane inaczej (w pętli, ze zmiennej) obok stałych nie są sprawdzane. Narzędzie z
    ``required=True``, z którego nie da się odczytać żadnej stałej nazwy, to ``ValueError``, bo pusta lista
    przepuściłaby je bez sprawdzenia.
    """

    calls = [
        (node.func.attr, node)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    required = any(
        method == "add_subparsers"
        and any(keyword.arg == "required" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in call.keywords)
        for method, call in calls
    )
    if not required:
        return []
    names = [
        call.args[0].value
        for method, call in calls
        if method == "add_parser" and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
    ]
    if not names:
        raise ValueError(
            f"{path.name}: add_subparsers(required=True), a żadnej podkomendy nie da się odczytać ze stałej w "
            'add_parser("<nazwa>"); dodaj choć jedną podkomendę osobnym add_parser ze stałą nazwą'
        )
    return names


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
        "napisz w nim w nawiasie podkomendę, której agent używa, np. „(plan --baza origin/main)”."
    )


PARSER = "import argparse\ncommands = argparse.ArgumentParser().add_subparsers({})\ncommands.add_parser('plan')\ncommands.add_parser('wykonaj')\n"


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
    ["for name in ('plan', 'wykonaj'):\n    commands.add_parser(name)\n", "commands.add_parser(NAME)\n", ""],
    ids=["w petli", "ze zmiennej", "bez podkomend"],
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
