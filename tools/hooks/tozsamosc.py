#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca zapis tożsamości autora gita do configu.

``git config user.email r@x`` bez ``--file`` pisze do ``.git/config`` głównego checkoutu, który dzielą wszystkie
jego worktree, więc od tej chwili każdy agent na tym komputerze podpisuje nim commity (13.11.2026 recenzent PR #1646
ustawił tak próbną tożsamość i podpisała ona setki commitów na ``main``). ``--worktree`` bez
``extensions.worktreeConfig`` też pisze tam, a ``--global`` i ``--system`` sięgają wszystkich repozytoriów. Repo
próbne w katalogu tymczasowym nie jest wyjątkiem, bo worktree pod ``/tmp`` to wciąż wspólny config; jednorazowy podpis
(``git -c user.name=… commit``, zmienne ``GIT_AUTHOR_*``/``GIT_COMMITTER_*``) działa wszędzie.

Odrzuca (kod 2, przyczyna na stderr trafia do agenta) wywołanie ``git … config``, które zapisuje albo usuwa klucz
``user``, ``author`` albo ``committer`` z ``name`` lub ``email`` (wielkość liter bez znaczenia): ustawienie (dwa
słowa pozycyjne), ``set``, ``unset``, ``--add``, ``--replace-all``, ``--unset``, ``--unset-all`` oraz
``rename-section`` i ``remove-section`` tych sekcji, z dowolnym zakresem i dowolnymi opcjami globalnymi ``git``
(``-C ścieżka``, ``--git-dir``). Przechodzi odczyt (jedno słowo pozycyjne, ``get``, ``--get*``, ``--list``), zapis
innych kluczy i zapis do pliku ``--file``, którego nazwa nie jest nazwą configu gita (``config``,
``config.worktree``, ``.gitconfig``). Hook czyta polecenie słowami ``shlex``: słowo ``git`` w dowolnym miejscu (za
``env``, ``xargs``, ``sudo``, ale też w ``echo git config user.name x``) zaczyna wywołanie, które biegnie do
następnego ``git``, ``;``, ``&``, ``|`` albo nawiasu. Czyta też skrypt ``-c`` powłoki, argumenty ``eval``
i ``$(…)`` w napisie; ciała heredoców pomija, bo to zwykle treść commitu.
Wszystko inne przechodzi bez słowa (kod 0), także wejście, którego nie da się odczytać, bo hook nie może zatrzymać
pracy.

Granica: inne harnessy niż Claude Code (Codex, opencode), skrypt z pliku albo z heredoca, Python (``subprocess``),
klucz albo polecenie ze zmiennej i alias gita łapie tylko przegląd; postacie z próbkami są w ``ZNANE_LUKI``
w ``tests/test_tozsamosc.py``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import re
import shlex
import sys
from typing import Optional

IDENTITY_SECTIONS = frozenset({"user", "author", "committer"})
IDENTITY_KEYS = frozenset(f"{section}.{name}" for section in IDENTITY_SECTIONS for name in ("name", "email"))
CONFIG_FILES = frozenset({"config", "config.worktree", ".gitconfig"})
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"})
CONFIG_VALUE_OPTIONS = frozenset({"-f", "--file", "--blob", "--type", "--default", "--comment", "--value", "--url"})
WRITE_SUBCOMMANDS = frozenset({"set", "unset", "rename-section", "remove-section", "edit"})
READ_SUBCOMMANDS = frozenset({"get", "list"})
WRITE_OPTIONS = frozenset({"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section", "-e", "--edit"})
READ_OPTIONS = frozenset({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "-l", "--list"})
SECTION_OPERATIONS = frozenset({"rename-section", "remove-section", "--rename-section", "--remove-section"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "su", "runuser"})
SCRIPT_OPTION = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")
SEPARATORS = frozenset("();|&")

REFUSAL = (
    "Odmowa: git config zapisuje tożsamość autora (user.name/user.email, także author.* i committer.*) do configu, "
    "który dzielą checkout główny i wszystkie jego worktree (albo --global/--system: cały komputer), więc od tej chwili "
    "podpisywałby nią commity każdy agent. Podpisz jedno polecenie: git -c user.name=… -c user.email=… commit …, "
    "albo zmiennymi GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME i GIT_COMMITTER_EMAIL przed tym jednym "
    "poleceniem. Tak samo w repo próbnym w katalogu tymczasowym, bo worktree pod /tmp też pisze do wspólnego configu. "
    "Tożsamość we wspólnym configu zmienia tylko Maks we własnym terminalu."
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


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command.replace("`", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # niedomknięty cudzysłów: słowa bez cudzysłowów
        return command.split()


def _is_separator(token: str) -> bool:
    return bool(token) and set(token) <= SEPARATORS


def _is_redirection(token: str) -> bool:
    return bool(token) and set(token) <= SEPARATORS | {"<", ">"} and ("<" in token or ">" in token)


def _simple_commands(tokens: list[str]) -> Iterator[list[str]]:
    """Słowa każdego polecenia prostego bez przekierowań (``2>/dev/null`` ani jego cel nie są słowem polecenia)."""

    words: list[str] = []
    skip_target = False
    for token in tokens:
        if skip_target:
            skip_target = False
        elif _is_redirection(token):
            if words and words[-1].isdigit():
                words.pop()
            skip_target = True
        elif _is_separator(token):
            yield words
            words = []
        else:
            words.append(token)
    yield words


def _nested(words: list[str]) -> Iterator[str]:
    """Skrypty, które polecenie proste wykonuje: ciało ``-c`` powłoki, argumenty ``eval`` i ``$(…)`` w słowie."""

    shell = False
    for index, word in enumerate(words):
        if "$(" in word:
            yield word[word.index("$(") + 2 :]
        name = word.rsplit("/", 1)[-1]
        if name == "eval":
            # Słowa za ``eval`` to jeden skrypt, a dalsze ``eval`` stoją w nim.
            yield " ".join(words[index + 1 :])
            return
        if name in SHELLS:
            shell = True
        elif shell and SCRIPT_OPTION.fullmatch(word) and index + 1 < len(words):
            yield words[index + 1]


def _git_calls(words: list[str]) -> Iterator[list[str]]:
    """Słowa za każdym ``git`` polecenia prostego, do następnego ``git``."""

    call: Optional[list[str]] = None
    for word in words:
        if word.rsplit("/", 1)[-1] == "git":
            if call is not None:
                yield call
            call = []
        elif call is not None:
            call.append(word)
    if call is not None:
        yield call


def _config_arguments(call: list[str]) -> Optional[list[str]]:
    """Argumenty za ``config``, gdy podpolecenie ``git`` to ``config``; opcje globalne ``git`` pomija."""

    index = 0
    while index < len(call):
        word = call[index]
        if word in GIT_VALUE_OPTIONS:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return call[index + 1 :] if word == "config" else None
    return None


def _writes_identity(arguments: list[str]) -> bool:
    options: set[str] = set()
    positional: list[str] = []
    config_file: Optional[str] = None
    index = 0
    while index < len(arguments):
        word = arguments[index]
        option, equals, value = word.partition("=")
        if word.startswith("-") and option in CONFIG_VALUE_OPTIONS:
            if not equals:
                index += 1
                value = arguments[index] if index < len(arguments) else ""
            if option in ("-f", "--file"):
                config_file = value
        elif word.startswith("-"):
            options.add(option)
        else:
            positional.append(word)
        index += 1
    if config_file is not None and config_file.replace("\\", "/").rsplit("/", 1)[-1] not in CONFIG_FILES:
        return False
    subcommand = positional[0] if positional and positional[0] in WRITE_SUBCOMMANDS | READ_SUBCOMMANDS else None
    names = positional[1:] if subcommand else positional
    if subcommand in READ_SUBCOMMANDS or options & READ_OPTIONS:
        return False
    if not (subcommand in WRITE_SUBCOMMANDS or options & WRITE_OPTIONS or len(names) >= 2):
        return False
    if subcommand in SECTION_OPERATIONS or options & SECTION_OPERATIONS:
        return any(name.casefold() in IDENTITY_SECTIONS for name in names[:2])
    return bool(names) and names[0].casefold() in IDENTITY_KEYS


def writes_identity(command: str, depth: int = 0) -> bool:
    """Czy polecenie zapisuje albo usuwa tożsamość autora w configu gita (szczegóły w docstringu modułu)."""

    if depth > 20:  # setki zagnieżdżonych ``bash -c``: polecenia nie da się odczytać, więc przechodzi
        return False
    for words in _simple_commands(_tokens(_without_heredocs(command))):
        for call in _git_calls(words):
            arguments = _config_arguments(call)
            if arguments is not None and _writes_identity(arguments):
                return True
        if any(writes_identity(script, depth + 1) for script in _nested(words)):
            return True
    return False


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError, RecursionError):
        return 0
    if not isinstance(command, str) or not writes_identity(command):
        return 0
    print(REFUSAL, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
