#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: ciężkie polecenie z tabeli skilla ``boat`` biegnie tylko przez ``boatbox``.

``boatbox auto`` i ``boatbox run --here`` dają ciężkiemu poleceniu slot Maca, a ``boatbox auto`` bez wolnego slotu od
razu box (skill ``boat``, sekcja „Budżet”). Polecenie uruchomione wprost omija sloty i biegnie na Macu obok wszystkich
wątków, więc hook go odmawia (kod 2, przyczyna na stderr trafia do agenta) i podaje gotowe polecenie ``boatbox``.
Działa tylko tam, gdzie ``boatbox`` jest w ``PATH`` (Mac Maksa), a na innej maszynie przepuszcza wszystko, bo skill
każe tam uruchamiać lokalnie.

Hook czyta polecenie słowami ``shlex`` bez ciał heredoców i dzieli je na polecenia proste na operatorach powłoki
(``;``, ``&``, ``|``, nawiasy, nowa linia); przekierowanie zabiera tylko swój cel. Python to słowo ``python``,
``python3`` albo ``python3.14`` ze ścieżką (``.venv/bin/python``) w dowolnym miejscu polecenia prostego, także za
``timeout 900`` czy ``nohup``, albo bez ścieżki na pozycji programu: pierwsze słowo za przypisaniami (``X=1``)
i słowami ``PREFIXES`` (``do``, ``then``, ``!``, ``{``…). Jego skrypt to pierwsze słowo za opcjami Pythona, a ``-m``
podaje moduł. Odmowę dostaje polecenie proste, które uruchamia (``SCRIPTS`` i ``PYTEST_RUN``):

| Ciężkie polecenie | Przykład | Gotowe polecenie w odmowie |
|---|---|---|
| ``szybko.py`` | ``.venv/bin/python tools/szybko.py --baza x 2>&1 \\| tail`` | ``boatbox auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8 '…'`` |
| ``mutacje.py`` z ``--plik`` | ``timeout 900 .venv/bin/python tools/mutacje.py --plik m.json`` | ``boatbox auto '…'`` |
| ``benchmark_przebiegu.py`` z ``measure`` albo ``freeze`` | ``.venv/bin/python tools/benchmark_przebiegu.py measure --scenario s`` | ``boatbox run --here '…'`` |
| pytest z workerami xdist bez pliku testów | ``.venv/bin/python -m pytest -n auto``, ``pytest -q -n 4 tests/``, ``.venv/bin/pytest -nauto -k x`` | ``boatbox job pytest '…'`` |
| każde z nich w skrypcie powłoki | ``bash -lc '.venv/bin/python tools/szybko.py'`` | jak wyżej, dla polecenia ze skryptu |

``pytest`` bez ścieżki liczy się tylko na pozycji programu, bo jako argument (``pip install pytest``,
``rg pytest``) niczego nie uruchamia. Skrypt powłoki to słowo za opcją z literą ``c`` (``-c``, ``-lc``) programu
``bash``, ``sh``, ``zsh``, ``dash`` albo ``ksh``. Gotowe polecenie ze zmienną (``--plik $G/m.json``) stoi w
cudzysłowie podwójnym, bo zmienną zna tylko powłoka agenta. Przechodzi bez słowa (kod 0):

| Polecenie | Przykład |
|---|---|
| ciężkie polecenie w ``boatbox`` | ``boatbox auto '.venv/bin/python tools/szybko.py'`` |
| pytest z plikiem testów albo z argumentem ze zmiennej lub pliku | ``.venv/bin/python -m pytest -n 4 tests/test_x.py -k y``, ``pytest -n 4 $T``, ``pytest -n 4 @testy.txt`` |
| pytest w jednym procesie (bez ``-n``, ``-n 0``, ``-p no:xdist``) | ``.venv/bin/python -m pytest -q tests/ -k y``, ``pytest --collect-only -q`` |
| ``mutacje.py`` bez ``--plik``, ``benchmark_przebiegu.py comment`` albo ``guard`` | ``.venv/bin/python tools/mutacje.py --zmiana a b c`` |
| pomoc narzędzia (``-h``, ``--help``) | ``.venv/bin/python tools/szybko.py --help``, ``pytest -n 4 -h`` |
| nazwa skryptu jako argument innego programu | ``sed -n 1,9p tools/szybko.py``, ``git add tools/szybko.py`` |
| Python ze skryptem z napisu albo stdin | ``.venv/bin/python - <<'EOF'``, ``.venv/bin/python -c '…'`` |
| lekkie polecenia skilla | ``.venv/bin/python -m ruff check .``, ``.venv/bin/python -m mypy``, ``git``, ``gh`` |
| wejście, którego hook nie odczyta | ``echo "niedomknięte`` |

Postacie, które hook przepuszcza, choć uruchamiają ciężkie polecenie (interpreter ze zmiennej, ``eval``, ``"$(…)"``…),
są próbkami ``ZNANE_LUKI`` w ``tests/test_ciezkie.py``; inny harness niż Claude Code hooka nie uruchamia.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``ruff.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json
import re
import shlex
import shutil
import sys
from typing import Optional

OPERATORS = "();<>|&\n"
REDIRECT = re.compile(r"[<>&]*[<>][<>&]*")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
PREFIXES = frozenset({"!", "{", "if", "then", "else", "elif", "do", "while", "until", "time", "exec", "command", "nohup"})
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?")
PYTHON_VALUE_OPTIONS = frozenset({"-W", "-X"})
PYTEST = frozenset({"pytest", "py.test"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
SCRIPT_OPTION = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
TEST_FILE = re.compile(r".+\.py(?:::.*)?|.*\$.*|@.+")
WORKERS = re.compile(r"(?:-n|--numprocesses=?)(.*)")
HELP = frozenset({"-h", "--help"})
BARE_WORD = re.compile(r"[\w@%+=:,./${}~-]+")
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")

AUTO = "boatbox auto bierze wolny slot Maca, bez wolnego slotu od razu box, a bez startu boxa czeka w kolejce na slot."


@dataclass(frozen=True)
class Heavy:
    name: str
    heavy: Callable[[list[str]], bool]
    route: str
    note: str


@dataclass(frozen=True)
class Refusal:
    reason: str


def _with(*words: str) -> Callable[[list[str]], bool]:
    return lambda arguments: any(argument.split("=", 1)[0] in words for argument in arguments)


def _suite_on_workers(arguments: list[str]) -> bool:
    workers = "0"
    for index, argument in enumerate(arguments):
        option = WORKERS.fullmatch(argument)
        if option:
            workers = option.group(1) or next(iter(arguments[index + 1 : index + 2]), "0")
        elif argument == "-pno:xdist" or arguments[index : index + 2] == ["-p", "no:xdist"]:
            return False
    files = any(TEST_FILE.fullmatch(argument) for argument in arguments if not argument.startswith("-"))
    return workers != "0" and not files


SCRIPTS = {
    "szybko.py": Heavy(
        "szybko.py",
        lambda arguments: True,
        "auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8",
        f"{AUTO} Box large ma 8 vCPU, więc --box-env daje mu 8 workerów pytest.",
    ),
    "mutacje.py": Heavy(
        "mutacje.py --plik",
        _with("--plik"),
        "auto",
        f"{AUTO} Mutacje o kilku różnych polecenie dziel przez boatbox fan (skill boat, „Fan mutacji”).",
    ),
    "benchmark_przebiegu.py": Heavy(
        "benchmark_przebiegu.py measure albo freeze",
        _with("measure", "freeze"),
        "run --here",
        "boatbox run --here zostawia pomiar na Macu w jego slocie, a przy zajętych slotach czeka w kolejce. "
        "Pomiar na boxie (A/B po kolei na tym samym boxie): boatbox run z jego własnym --machine.",
    ),
}
PYTEST_RUN = Heavy(
    "pytest z workerami xdist bez pliku testów",
    _suite_on_workers,
    "job pytest",
    "Pełny pytest biegnie na boxie, bo na Macu bierze wszystkie rdzenie; wynik daje boatbox wait pytest.",
)


def _without_heredocs(command: str) -> str:
    kept: list[str] = []
    delimiter: Optional[str] = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        opened = HEREDOC.search(line)
        if opened:
            delimiter = opened.group(2)
    return "\n".join(kept)


def _simple_commands(command: str) -> list[list[str]]:
    lexer = shlex.shlex(_without_heredocs(command).replace("\\\n", " "), posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[list[str]] = [[]]
    target = False
    for token in lexer:
        if token and all(char in OPERATORS for char in token):
            if REDIRECT.fullmatch(token):
                if commands[-1] and commands[-1][-1].isdigit():
                    commands[-1].pop()
                target = True
            else:
                commands.append([])
                target = False
        elif target:
            target = False
        else:
            commands[-1].append(token)
    return commands


def _python_run(arguments: list[str]) -> Optional[tuple[Heavy, list[str]]]:
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "-m":
            module = arguments[index + 1 : index + 2]
            return (PYTEST_RUN, arguments[index + 2 :]) if module == ["pytest"] else None
        if not word.startswith("-"):
            heavy = SCRIPTS.get(word.rsplit("/", 1)[-1])
            return None if heavy is None else (heavy, arguments[index + 1 :])
        index += 2 if word in PYTHON_VALUE_OPTIONS else 1
    return None


def _shell_script(arguments: list[str]) -> Optional[str]:
    for index, word in enumerate(arguments[:-1]):
        if SCRIPT_OPTION.fullmatch(word):
            return arguments[index + 1]
    return None


def _refusals(words: list[str]) -> Iterator[Refusal]:
    lead = 0
    while lead < len(words) and (ASSIGNMENT.match(words[lead]) or words[lead] in PREFIXES):
        lead += 1
    command = [word for word in words[:lead] if ASSIGNMENT.match(word)] + words[lead:]
    for index in range(lead, len(words)):
        word = words[index]
        name = word.rsplit("/", 1)[-1]
        program = index == lead or "/" in word
        run: Optional[tuple[Heavy, list[str]]] = None
        if PYTHON.fullmatch(name) and program:
            run = _python_run(words[index + 1 :])
        elif name in PYTEST and index == lead:
            run = (PYTEST_RUN, words[index + 1 :])
        elif name in SHELLS and program:
            script = _shell_script(words[index + 1 :])
            if script is not None:
                yield from _judged(script)
        if run is None:
            continue
        heavy, arguments = run
        if heavy.heavy(arguments) and not HELP.intersection(arguments):
            text = " ".join(part if BARE_WORD.fullmatch(part) else shlex.quote(part) for part in command)
            yield Refusal(
                f"Odmowa: {text} to ciężkie polecenie ({heavy.name}) z tabeli skilla boat, a uruchomione bez boatbox "
                f"biegnie na Macu poza jego slotami, które dzielą wszystkie wątki. Uruchom je tak: "
                f"boatbox {heavy.route} {_argument(text)}\n{heavy.note}"
            )


def _argument(text: str) -> str:
    if "$" not in text:
        return shlex.quote(text)
    return '"' + re.sub(r'(["\\`])', r"\\\1", text) + '"'


def _judged(command: str) -> Iterator[Refusal]:
    try:
        commands = _simple_commands(command)
    except ValueError:
        return
    for words in commands:
        yield from _refusals(words)


def judge(command: str) -> Optional[Refusal]:
    return next(_judged(command), None)


def main() -> int:
    if shutil.which("boatbox") is None:
        return 0
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0
    if not isinstance(command, str):
        return 0
    refusal = judge(command)
    if refusal is None:
        return 0
    print(refusal.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
