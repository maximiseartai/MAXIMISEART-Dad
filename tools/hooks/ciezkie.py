#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from slowa_powloki import QUOTED, unquoted

SEPARATORS = frozenset({"&&", "&"})
SEPARATOR_CHARACTERS = ";|()\n"
TOKEN = re.compile(
    rf"[ \t\r]+|#[^\n]*|(?P<separator>[{re.escape(SEPARATOR_CHARACTERS)}]+)"
    rf"|(?P<word>(?:[^ \t\r'\"\\{re.escape(SEPARATOR_CHARACTERS)}]|{QUOTED})+)"
)
KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{"})
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
PYTHON = re.compile(r"python(?:3(?:\.\d+)?)?")
REDIRECT = re.compile(r"((?:\d+|&)?(?:>>|>&|<&|&>|>\||<>|>|<))(.*)", re.DOTALL)
PYTHON_OPTIONS_WITH_VALUE = frozenset({"-X", "-W"})
HELP = frozenset({"-h", "--help"})
WORKERS = frozenset({"-n", "--numprocesses"})
BENCHMARK_MEASURING = frozenset({"measure", "freeze"})
VENV_PYTHON = ".venv/bin/python"
SZYBKO_WORKERS = "PYTEST_XDIST_AUTO_NUM_WORKERS"
SKILL_MUTATIONS = "check_*_mutations.py"
VARIABLES = "zmienne powłoki rozwija Mac, więc ich definicje wklej przed poleceniem"
UNCHECKED_PLIK = "plik --plik spoza worktree skopiuj najpierw do jego korzenia, bo box dostaje tylko pliki widziane przez git"


@dataclass(frozen=True)
class _Launcher:
    positional: int = 0
    with_value: frozenset[str] = frozenset()


LAUNCHERS = {
    "time": _Launcher(0, frozenset({"-o", "-f", "--output", "--format"})),
    "timeout": _Launcher(1, frozenset({"-s", "-k", "--signal", "--kill-after"})),
    "env": _Launcher(0, frozenset({"-u", "-C", "--unset", "--chdir"})),
    "nice": _Launcher(0, frozenset({"-n", "--adjustment"})),
    "nohup": _Launcher(),
    "caffeinate": _Launcher(0, frozenset({"-t", "-w"})),
    "command": _Launcher(),
    "exec": _Launcher(),
}


@dataclass(frozen=True)
class Refusal:
    reason: str


@dataclass(frozen=True)
class _Command:
    assignments: tuple[tuple[str, str], ...]
    words: tuple[str, ...]
    redirects: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Heavy:
    what: str
    script: Optional[str]
    arguments: tuple[str, ...]
    job: bool = False
    note: str = ""


def _words(command: str) -> Optional[list[str]]:
    text, words, index = command.replace("\\\n", ""), [], 0
    while index < len(text):
        token = TOKEN.match(text, index)
        if token is None:
            return None
        index = token.end()
        if token.lastgroup == "separator":
            words.append(token.group())
        elif token.lastgroup == "word":
            words.append(unquoted(token.group()))
    return words


def _is_separator(word: str) -> bool:
    return word in SEPARATORS or all(character in SEPARATOR_CHARACTERS for character in word)


def _simple_commands(words: list[str]) -> list[list[str]]:
    commands: list[list[str]] = [[]]
    for word in words:
        if _is_separator(word):
            commands.append([])
        else:
            commands[-1].append(word)
    return [command for command in commands if command]


def _command(words: list[str]) -> _Command:
    rest: list[str] = []
    redirects: list[tuple[str, str]] = []
    target = False
    for word in words:
        if target:
            redirects[-1] = (redirects[-1][0], word)
            target = False
            continue
        redirect = REDIRECT.fullmatch(word)
        if redirect:
            operator, glued = redirect.groups()
            redirects.append((operator, glued))
            target = not glued
        else:
            rest.append(word)
    assignments: list[tuple[str, str]] = []
    index = 0
    while index < len(rest):
        assignment = ASSIGNMENT.fullmatch(rest[index])
        if assignment:
            assignments.append((assignment.group(1), assignment.group(2)))
            index += 1
        elif rest[index] in KEYWORDS:
            index += 1
        elif posixpath.basename(rest[index]) in LAUNCHERS:
            index = _after_launcher(rest, index)
        else:
            break
    return _Command(tuple(assignments), tuple(rest[index:]), tuple(redirects))


def _after_launcher(words: list[str], index: int) -> int:
    launcher = LAUNCHERS[posixpath.basename(words[index])]
    positional = launcher.positional
    index += 1
    while index < len(words):
        word = words[index]
        if word in launcher.with_value:
            index += 2
        elif word.startswith("-"):
            index += 1
        elif positional:
            positional -= 1
            index += 1
        else:
            break
    return index


def _workers(arguments: tuple[str, ...]) -> Optional[str]:
    value: Optional[str] = None
    for index, argument in enumerate(arguments):
        if argument in WORKERS:
            value = arguments[index + 1] if index + 1 < len(arguments) else None
        elif argument.startswith("--numprocesses="):
            value = argument.partition("=")[2]
        elif argument.startswith("-n") and not argument.startswith("--"):
            value = argument[2:].lstrip("=")
    return value


def _many_workers(value: Optional[str]) -> bool:
    if value in ("auto", "logical"):
        return True
    return value is not None and value.isdigit() and int(value) >= 2


def _names_tests(arguments: tuple[str, ...]) -> bool:
    return any(".py" in argument or (argument.startswith("tests/") and argument.rstrip("/") != "tests") for argument in arguments)


def _pytest(arguments: tuple[str, ...]) -> Optional[_Heavy]:
    if HELP.intersection(arguments) or not _many_workers(_workers(arguments)):
        return None
    full = not _names_tests(arguments)
    note = "pełny pytest biegnie jako job, a boatbox wait z kodem 3 powtórz" if full else ""
    return _Heavy("pytest z kilkoma workerami", None, arguments, job=full, note=note)


def _plik(arguments: tuple[str, ...]) -> bool:
    return any(argument == "--plik" or argument.startswith("--plik=") for argument in arguments)


def _script(script: str, arguments: tuple[str, ...]) -> Optional[_Heavy]:
    if HELP.intersection(arguments):
        return None
    parent, name = posixpath.split(posixpath.normpath(script))
    tool = posixpath.basename(parent) == "tools"
    if tool and name == "szybko.py":
        return _Heavy("szybko.py", script, arguments)
    if tool and name == "mutacje.py" and _plik(arguments):
        return _Heavy("mutacje.py --plik", script, arguments, note="mutacje o kilku różnych `polecenie` dziel przez boatbox fan")
    if tool and name == "benchmark_przebiegu.py" and BENCHMARK_MEASURING.intersection(arguments[:1]):
        return _Heavy(
            "pomiar benchmark_przebiegu.py", script, arguments, note="pliki ignorowane przez git, np. .benchmark/, na box nie trafiają"
        )
    if fnmatch(name, SKILL_MUTATIONS):
        return _Heavy("mutacje skilla", script, arguments)
    return None


def _python(arguments: tuple[str, ...]) -> Optional[_Heavy]:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-m":
            module = arguments[index + 1 : index + 2]
            return _pytest(arguments[index + 2 :]) if module == ("pytest",) else None
        if argument.startswith("-m"):
            return _pytest(arguments[index + 1 :]) if argument[2:] == "pytest" else None
        if argument == "-" or argument.startswith("-c"):
            return None
        if argument in PYTHON_OPTIONS_WITH_VALUE:
            index += 2
        elif argument.startswith("-"):
            index += 1
        else:
            return _script(argument, arguments[index + 1 :])
    return None


def _heavy(command: _Command) -> Optional[_Heavy]:
    words = command.words
    if not words:
        return None
    program = posixpath.basename(words[0])
    if program == "pytest":
        return _pytest(words[1:])
    if PYTHON.fullmatch(program):
        return _python(words[1:])
    return None


def _git_root(path: str) -> Optional[str]:
    while True:
        if os.path.exists(posixpath.join(path, ".git")):
            return path
        parent = posixpath.dirname(path)
        if parent == path:
            return None
        path = parent


def _absolute(path: str, cwd: str) -> str:
    return posixpath.normpath(posixpath.join(cwd, posixpath.expanduser(path)))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _variable(word: str) -> bool:
    return "$" in word or "`" in word


def _double_quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _shell_word(word: str) -> str:
    if _variable(word):
        return _double_quoted(word)
    return shlex.quote(posixpath.expanduser(word))


def _from_repo_directory(script: str) -> str:
    parts = script.split("/")
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] == ".agents" or (parts[index] == "tools" and index == len(parts) - 2):
            return "/".join(parts[index:])
    return script


def _plik_index(arguments: list[str]) -> Optional[int]:
    for index, argument in enumerate(arguments):
        if argument.startswith("--plik="):
            return index
        if argument == "--plik" and index + 1 < len(arguments):
            return index + 1
    return None


def _box_command(heavy: _Heavy, command: _Command, cwd: str, hook_cwd: str) -> tuple[str, list[str]]:
    known = not _variable(cwd)
    script = _absolute(heavy.script, cwd) if known and heavy.script and not _variable(heavy.script) else None
    root = _git_root(posixpath.dirname(script) if script else cwd) if known else None
    directory = cwd if root is None or _git_root(cwd) == root else root
    before = [] if directory == hook_cwd else [f"cd {_shell_word(directory)}"]
    arguments = list(heavy.arguments)
    notes = [heavy.note] if heavy.note else []
    plik = _plik_index(arguments)
    if plik is not None:
        prefix = "--plik=" if arguments[plik].startswith("--plik=") else ""
        path = arguments[plik][len(prefix) :]
        if _variable(path) or root is None:
            notes.append(UNCHECKED_PLIK)
        else:
            absolute = _absolute(path, cwd)
            if not _inside(absolute, root):
                copy = posixpath.join(root, posixpath.basename(absolute))
                before.append(f"cp {shlex.quote(absolute)} {shlex.quote(posixpath.relpath(copy, directory))}")
                absolute = copy
            arguments[plik] = prefix + posixpath.relpath(absolute, root)
    outside = [(name, value) for name, value in command.assignments if name.startswith("BOATBOX_")]
    assignments = [(name, value) for name, value in command.assignments if not name.startswith("BOATBOX_")]
    if heavy.what == "szybko.py" and SZYBKO_WORKERS not in dict(assignments):
        assignments.insert(0, (SZYBKO_WORKERS, "8"))
    if script is not None and root is not None:
        program = [VENV_PYTHON, posixpath.relpath(script, root)]
    elif heavy.script is not None:
        program = [VENV_PYTHON, _from_repo_directory(heavy.script)]
    else:
        program = [VENV_PYTHON, "-m", "pytest"]
    inner = " ".join(
        [f"{name}={_shell_word(value)}" for name, value in assignments] + [_shell_word(word) for word in program + arguments]
    )
    if _variable(inner) or any(_variable(value) for _, value in outside + list(command.redirects)):
        notes.append(VARIABLES)
    quoted = _double_quoted(inner) if _variable(inner) else shlex.quote(inner)
    boatbox = " ".join([*(f"{name}={_shell_word(value)}" for name, value in outside), "boatbox"])
    if heavy.job:
        call = f"{boatbox} job pytest {quoted} && {boatbox} wait pytest"
    else:
        call = f"{boatbox} run {quoted}"
    redirects = [_redirect(operator, target, cwd, directory) for operator, target in command.redirects]
    return " && ".join([*before, " ".join([call, *redirects])]), notes


def _directory(target: str, cwd: str) -> str:
    if _variable(target):
        return target
    if _variable(cwd):
        return posixpath.join(cwd, posixpath.expanduser(target))
    return _absolute(target, cwd)


def _redirect(operator: str, target: str, cwd: str, directory: str) -> str:
    if operator.endswith("&"):
        return operator + target
    if not _variable(target) and not _variable(cwd) and directory != cwd:
        return operator + shlex.quote(_absolute(target, cwd))
    return operator + _shell_word(target)


def _reason(heavy: _Heavy, box_command: str, notes: list[str]) -> str:
    said = "".join(f" {note[0].upper()}{note[1:]}." for note in notes)
    return f"Ciężkie polecenie ({heavy.what}) biegnie na boxie boat, nie na Macu (skill boat).{said} Uruchom: {box_command}"


def judge(command: str, cwd: str) -> Optional[Refusal]:
    cwd = posixpath.normpath(cwd)
    hook_cwd = cwd
    words = _words(command)
    if words is None or any(word.startswith("<<") and not word.startswith("<<<") for word in words):
        return None
    for simple in _simple_commands(words):
        parsed = _command(simple)
        if parsed.words[:1] == ("cd",):
            targets = [word for word in parsed.words[1:] if word == "-" or not word.startswith("-")]
            if targets != ["-"]:
                cwd = _directory(targets[-1] if targets else "~", cwd)
            continue
        heavy = _heavy(parsed)
        if heavy is not None:
            return Refusal(_reason(heavy, *_box_command(heavy, parsed, cwd, hook_cwd)))
    return None


def main() -> int:
    if shutil.which("boatbox") is None or os.environ.get("BOATBOX_BOX") == "1":
        return 0
    try:
        hook_input = json.load(sys.stdin)
        command = hook_input["tool_input"]["command"]
        cwd = hook_input.get("cwd") or os.getcwd()
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0
    if not isinstance(command, str) or not isinstance(cwd, str):
        return 0
    refusal = judge(command, cwd)
    if refusal is None:
        return 0
    print(refusal.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
