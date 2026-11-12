#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca ręczny tag Wydania i GitHub Release.

Tag Wydania ``v*`` i GitHub Release tworzy tylko narzędzie Wydań ``tools/wydanie.py`` ze skilla ``wydanie``, bo tag
na ``main`` trafia do taty (ADR 0014), a brama ``tools/hooks/pre-push`` widzi tylko ``git push`` z hookami. Hook
odrzuca więc (kod 2, przyczyna z drogą przez skill na stderr trafia do agenta), na pierwszym planie i w tle,
polecenie proste, którego programem jest ``git``, ``gh`` albo ``gh-axi`` (także ze ścieżką, za przypisaniem zmiennej
albo za ``env``, ``timeout``, ``nice``, ``nohup``, ``command``, ``exec``, ``sudo`` czy ``time``), a w nim:

- ``gh release`` z innym podpoleceniem niż ``list``, ``ls``, ``view``, ``download``, ``verify`` i ``verify-asset``,
  bez ``--help``;
- ``gh api`` z zapisem (``-X``/``--method`` innym niż ``GET`` i ``HEAD``, a bez metody z ``-f``, ``-F``,
  ``--field``, ``--raw-field`` albo ``--input``) na adres z segmentem ``releases`` albo na ``git/refs``, gdy adres
  albo pole wskazuje ``refs/tags/`` z nazwą od ``v`` albo nieznaną (``$``, ``*``) albo gdy treść idzie z pliku
  (``--input``, pole ``=@plik``);
- ``git push`` (z dowolnymi opcjami ``git`` przed nim, także ``--no-verify``) z ``--tags``, ``--follow-tags`` albo
  ``--mirror`` albo z argumentem, którego strona refspecu (bez ``+``, po obu stronach ``:``) to ``v`` z cyfrą,
  ``refs/tags/`` z nazwą od ``v`` albo nieznaną, albo nazwa od ``v`` albo nieznana po słowie ``tag``;
- ``git tag`` bez trybu listy, usunięcia i weryfikacji (``-l``, ``-d``, ``-v``, ``-n``, ``--list``, ``--delete``,
  ``--verify``, ``--contains``, ``--no-contains``, ``--merged``, ``--no-merged``, ``--points-at``) z argumentem od
  ``v``, od ``refs/tags/v`` albo nieznanym.

Polecenie dzieli na słowa jak bash ``shlex`` w trybie POSIX: napis w cudzysłowie to jedno słowo bez cudzysłowów,
``\\`` z nową linią to dalszy ciąg polecenia, a polecenie proste kończy się na ``;``, ``&``, ``&&``, ``|``, ``||``,
nowej linii i nawiasie. Podstawienie ``$(…)`` (także zagnieżdżone) i `` `…` `` bez cudzysłowu to w poleceniu jedno
słowo o nieznanej treści, także w środku słowa (``$(git rev-parse HEAD):refs/tags/v1``), a jego treść hook ocenia
jak osobne polecenie. Ciała heredoców pomija (``_without_heredocs`` hooka ``czekanie.py``), przekierowania z ich
celem i deskryptorem (``2>&1``) nie są argumentami, ``#`` na początku słowa zaczyna komentarz do końca linii, a skrypt
``-c`` powłoki (``bash``, ``sh``, ``zsh``, ``dash``, ``ksh``) i argumenty ``eval`` ocenia jak polecenie. Gdy
``shlex`` nie umie podzielić polecenia (niezamknięty cudzysłów, ``\\`` na końcu), hook dzieli je tak samo, ale
cudzysłowy i ``\\`` traktuje jak zwykłe znaki i usuwa je ze słów, więc odmawia tylko wtedy, gdy forma Wydania stoi
w poleceniu wprost.

Przechodzi wszystko, gdy sesja Claude Code ma w środowisku ``MAXIMISEART_WYDANIE=1`` (nazwa: ``RELEASE_OVERRIDE``
w ``tools/lib/repo.py``), a zmienna wpisana w samo polecenie niczego nie zmienia. ``tools/wydanie.py`` zakłada tag
i Release z Pythona, więc hook go nie widzi i nie zatrzymuje.
Granica: stronę GitHuba, skrypt z pliku albo w Pythonie, który sam woła ``git`` lub ``gh``, skrypt podany powłoce
heredokiem, ``$(…)`` i `` `…` `` w cudzysłowie podwójnym, nazwę programu ze zmiennej albo aliasu, ``gh api graphql``
(``createRef``), ``gh api`` z adresem ze zmiennej, ``push.followTags`` z konfiguracji gita i polecenie za ``#``
w środku słowa w tej samej linii (``echo $#; git tag v1``) łapie tylko przegląd. Tak samo trzy rzadkie formy:
polecenie w linii za komentarzem zakończonym ``\\`` (hook bierze ją za dalszy ciąg komentarza, a bash ją wykonuje),
polecenie w liniach za ``<<`` w napisie albo w ``$((…))`` (``_without_heredocs`` bierze je za początek heredoku
i pomija dalsze linie) i ciało funkcji ``function f { …; }``. Hook nie zna repozytorium, w którym polecenie biegnie,
więc odmowę dostaje też tag ``v*`` w repozytorium próbnym (``git init`` w katalogu tymczasowym), Release innego
repozytorium i push gałęzi o nazwie od ``v`` z cyfrą (``v2-redesign``). Czas ``shlex`` rośnie z kwadratem długości
najdłuższego słowa: polecenie z napisem ponad ok. 1 MB przekracza ``timeout`` i przechodzi.

Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9 (``per-file-target-version``
w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową, ``czekanie.py`` obok i ``tools/lib/repo.py``
dopiero przy odmowie. Wejście, którego nie da się odczytać, przechodzi, a hook, który się wywróci albo przekroczy
``timeout``, nie zatrzymuje polecenia.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/hooks"))

from czekanie import _without_heredocs  # jedyny właściciel rozpoznania heredoków w hookach

REFUSAL = (
    "Odmowa: tag Wydania v* i GitHub Release tworzy tylko narzędzie Wydań, bo tag na main trafia do taty (ADR 0014). "
    "Wydanie robi skill wydanie (.agents/skills/wydanie/SKILL.md): .venv/bin/python tools/wydanie.py plan, "
    "a po zgodzie Maksa tools/wydanie.py wydaj. Nie zakładaj ani nie wypychaj tagu v* (git tag, git push, także "
    "z --no-verify), nie twórz ani nie zmieniaj Release i refów tagów (gh release, gh api) i nie rób tego stroną GitHuba."
)

OPERATORS = ";&|()<>\n`"
# ``\`` z nową linią poza parzystą liczbą ``\`` przed nim: bash usuwa je przed podziałem na słowa.
CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# Znaki, po których ``#`` zaczyna komentarz; ``#`` w środku słowa (``$#``, ``issues#1``) go nie zaczyna, a ``shlex``
# zaczyna go tam także.
WORD_BREAKS = " \t\r\n;&|()<>`"
INNER_HASH = re.compile(f"(?<=[^{re.escape(WORD_BREAKS)}])#")
# Słowo w miejscu podstawienia ``$(…)`` albo `` `…` ``: jego wartości hook nie zna.
SUBSTITUTION_STANDIN = "$S"
HASH_STANDIN = "\0"
# Przekierowanie w słowie operatora (``2>&1`` daje ``>&``, ``&>``, ``<<<``); ``<(`` to podstawienie procesu.
REDIRECTION = re.compile(r"&>>?|[<>]&|>\||<<<|<<-?|<>|>>|[<>](?!\()")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
RESERVED = frozenset({"!", "{", "}", "if", "then", "elif", "else", "while", "until", "do"})
# Program przed poleceniem: opcje, które biorą wartość, i liczba słów bez ``-`` przed poleceniem.
WRAPPERS = {
    "env": (frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}), 0),
    "timeout": (frozenset({"-s", "--signal", "-k", "--kill-after"}), 1),
    "nice": (frozenset({"-n", "--adjustment"}), 0),
    "nohup": (frozenset(), 0),
    "command": (frozenset(), 0),
    "exec": (frozenset({"-a"}), 0),
    "sudo": (frozenset({"-u", "--user", "-g", "--group", "-C", "-D", "-h", "-p", "-R", "-r", "-t", "-U"}), 0),
    "time": (frozenset(), 0),
}
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
SHELL_SCRIPT_OPTION = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
# Skrypt w skrypcie: dalej niż na tej głębokości hook nie zagląda.
MAX_DEPTH = 20

PROGRAMS = frozenset({"git", "gh", "gh-axi"})
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"})
GH_VALUE_OPTIONS = frozenset({"-R", "--repo"})
GH_RELEASE_READS = frozenset({"list", "ls", "view", "download", "verify", "verify-asset"})
GH_API_VALUE_OPTIONS = frozenset(
    {"-X", "--method", "-f", "--raw-field", "-F", "--field", "--input", "-H", "--header", "-q", "--jq", "-t"}
    | {"--template", "--cache", "--hostname", "-p", "--preview"}
)
GH_API_FIELDS = frozenset({"-f", "--raw-field", "-F", "--field"})
GH_API_READS = frozenset({"GET", "HEAD"})
RELEASES_ADDRESS = re.compile(r"(?:^|/)releases(?:[/?]|$)")
REFS_ADDRESS = re.compile(r"(?:^|/)git/refs(?:[/?]|$)")
# Nazwa tagu od ``v`` albo nieznana: ze zmiennej, podstawienia albo wzorca (``$T``, `` `…` ``, ``*``), także pusta.
RELEASE_TAG = re.compile(r"v|[^A-Za-z0-9_.-]|$")
TAG_REF = re.compile(r"refs/tags/(?:v|[^A-Za-z0-9_.-]|$)")
PUSHED_RELEASE = re.compile(r"v\d")
PUSH_ALL_TAGS = frozenset({"--tags", "--follow-tags", "--mirror"})
PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--receive-pack", "--exec", "--repo"})
TAG_VALUE_OPTIONS = frozenset(
    {"-m", "--message", "-F", "--file", "-u", "--local-user", "--cleanup", "--trailer", "--sort", "--format"}
)
TAG_SHORT_VALUES = frozenset("mFu")
TAG_NOT_CREATING = frozenset("ldvn")
TAG_NOT_CREATING_LONG = frozenset(
    {"--list", "--delete", "--verify", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}
)


def _backtick_end(shell: str, index: int) -> int:
    """Indeks `` ` ``, który zamyka `` ` `` pod ``index``, albo długość polecenia."""

    index += 1
    while index < len(shell) and shell[index] != "`":
        index += 2 if shell[index] == "\\" else 1
    return min(index, len(shell))


def _closing(shell: str, index: int) -> int:
    """Indeks ``)``, który zamyka ``(`` otwarty przed ``index`` (z zagnieżdżeniem i cudzysłowami), albo -1."""

    depth = 1
    while index < len(shell):
        char = shell[index]
        if char in "\\'\"":
            index = _quoted_end(shell, index)
            continue
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0:
            return index
        index += 1
    return -1


def _quoted_end(shell: str, index: int) -> int:
    """Indeks za napisem w cudzysłowie albo znakiem po ``\\`` pod ``index``; ``"…"`` mija ``$(…)`` i `` `…` `` w nim."""

    if shell[index] == "\\":
        return index + 2
    if shell[index] == "'":
        end = shell.find("'", index + 1)
        return len(shell) if end < 0 else end + 1
    index += 1
    while index < len(shell) and shell[index] != '"':
        if shell[index] == "\\":
            index += 2
        elif shell.startswith("$(", index):
            end = _closing(shell, index + 2)
            index = len(shell) if end < 0 else end + 1
        elif shell[index] == "`":
            index = _backtick_end(shell, index) + 1
        else:
            index += 1
    return min(index + 1, len(shell))


def _lifted(shell: str) -> tuple[str, list[str]]:
    """Polecenie ze słowem ``$S`` w miejscu podstawień bez cudzysłowu i treść tych podstawień.

    Napis w cudzysłowie i komentarz zostają w poleceniu bez zmian, tak jak podstawienie w nich.
    """

    outer: list[str] = []
    substitutions: list[str] = []
    index = 0
    while index < len(shell):
        char = shell[index]
        if char in "\\'\"":
            end = _quoted_end(shell, index)
        elif char == "#" and (index == 0 or shell[index - 1] in WORD_BREAKS):
            end = shell.find("\n", index)
            end = len(shell) if end < 0 else end
        elif shell.startswith("$(", index) or char == "`":
            close = _closing(shell, index + 2) if char == "$" else _backtick_end(shell, index)
            if close < 0:  # niezamknięte ``$(``: reszta zostaje, a nawias kończy polecenie
                outer.append(shell[index:])
                break
            substitutions.append(shell[index + (2 if char == "$" else 1) : close])
            outer.append(SUBSTITUTION_STANDIN)
            index = close + 1
            continue
        else:
            end = index + 1
        outer.append(shell[index:end])
        index = end
    return "".join(outer), substitutions


def _tokens(shell: str, quoting: bool) -> list[str]:
    """Słowa i operatory jak u basha; bez ``quoting`` cudzysłów i ``\\`` to zwykłe znaki, usunięte ze słów."""

    # Komentarz ``shlex`` zjada linię razem z jej końcem, więc nowa linia idzie podwójnie: druga kończy polecenie.
    lexer = shlex.shlex(shell.replace("\n", "\n\n"), posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    if not quoting:
        lexer.quotes = lexer.escape = ""
    tokens = []
    for token in lexer:
        word = token if quoting or _operator(token) else token.replace("'", "").replace('"', "").replace("\\", "")
        tokens.append(word.replace(HASH_STANDIN, "#"))
    return tokens


def _operator(token: str) -> bool:
    return token != "" and all(char in OPERATORS for char in token)


def _simple_commands(shell: str) -> Iterator[list[str]]:
    """Słowa każdego polecenia prostego, bez przekierowań i ich celów."""

    shell = INNER_HASH.sub(HASH_STANDIN, CONTINUATION.sub(r"\1", shell))
    try:
        tokens = _tokens(shell, quoting=True)
    except ValueError:  # niezamknięty cudzysłów albo ``\`` na końcu
        tokens = _tokens(shell, quoting=False)
    words: list[str] = []
    target = False
    for token in tokens:
        if not _operator(token):
            if target:
                target = False
            else:
                words.append(token)
            continue
        target = REDIRECTION.search(token) is not None
        if REDIRECTION.match(token) and words and words[-1].isdigit():
            words.pop()  # deskryptor przekierowania: ``2>&1`` to dla ``shlex`` słowo ``2`` i operator ``>&``
        if REDIRECTION.sub("", token):
            if words:
                yield words
            words = []
    if words:
        yield words


def _program(words: list[str]) -> tuple[str, list[str]]:
    """Nazwa programu polecenia prostego (bez ścieżki) i jego argumenty, za przypisaniami i programami przed nim."""

    index = 0
    while index < len(words):
        word = words[index]
        name = word.rsplit("/", 1)[-1]
        if word in RESERVED or ASSIGNMENT.match(word):
            index += 1
        elif name in WRAPPERS:
            takes_value, operands = WRAPPERS[name]
            index += 1
            while index < len(words) and (words[index].startswith("-") or ASSIGNMENT.match(words[index])):
                index += 2 if words[index] in takes_value else 1
            index += operands
        else:
            return name, words[index + 1 :]
    return "", []


def _shell_script(arguments: list[str]) -> Optional[str]:
    """Skrypt ``-c`` powłoki: pierwsze słowo bez ``-`` za opcją z ``c`` (``-c``, ``-lc``, ``-euo pipefail -c``)."""

    script_follows = False
    for word in arguments:
        if word.startswith("-"):
            script_follows = script_follows or SHELL_SCRIPT_OPTION.fullmatch(word) is not None
        elif script_follows:
            return word
    return None


def _subcommand(arguments: list[str], takes_value: frozenset[str]) -> tuple[Optional[str], list[str]]:
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word in takes_value:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return word, arguments[index + 1 :]
    return None, []


def _parsed(arguments: list[str], takes_value: frozenset[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Opcje (nazwa, wartość; flaga z pustą) i argumenty; wartość także sklejona: ``--method=POST``, ``-XPOST``."""

    options: list[tuple[str, str]] = []
    positionals: list[str] = []
    words = iter(arguments)
    for word in words:
        if word == "--":
            positionals.extend(words)
        elif word.startswith("--") and "=" in word:
            name, value = word.split("=", 1)
            options.append((name, value))
        elif word in takes_value:
            options.append((word, next(words, "")))
        elif not word.startswith("--") and word[:2] in takes_value:
            options.append((word[:2], word[2:]))
        elif word.startswith("-") and word != "-":
            options.append((word, ""))
        else:
            positionals.append(word)
    return options, positionals


def _release_tag(name: str) -> bool:
    return RELEASE_TAG.match(name.removeprefix("refs/tags/")) is not None


def _pushes_release(arguments: list[str]) -> bool:
    options, positionals = _parsed(arguments, PUSH_VALUE_OPTIONS)
    if any(name in PUSH_ALL_TAGS for name, _ in options):
        return True
    after_tag = False
    for word in positionals:
        if after_tag and _release_tag(word):
            return True
        after_tag = word == "tag"
        for side in word.lstrip("+").split(":", 1):
            full = side.startswith("refs/tags/")
            if _release_tag(side) if full else PUSHED_RELEASE.match(side) is not None:
                return True
    return False


def _short_flags(name: str) -> set[str]:
    """Litery skupionych flag krótkich (``-fa``) do pierwszej, która bierze wartość (``-mdone`` to wiadomość)."""

    letters: set[str] = set()
    if name.startswith("-") and not name.startswith("--"):
        for letter in name[1:]:
            if letter in TAG_SHORT_VALUES:
                break
            letters.add(letter)
    return letters


def _tags_release(arguments: list[str]) -> bool:
    options, positionals = _parsed(arguments, TAG_VALUE_OPTIONS)
    if any(name in TAG_NOT_CREATING_LONG or _short_flags(name) & TAG_NOT_CREATING for name, _ in options):
        return False
    return any(_release_tag(word) for word in positionals)


def _writes_release_api(arguments: list[str]) -> bool:
    options, positionals = _parsed(arguments, GH_API_VALUE_OPTIONS)
    if not positionals:
        return False
    address = positionals[0]
    methods = [value.upper() for name, value in options if name in ("-X", "--method")]
    fields = [value for name, value in options if name in GH_API_FIELDS]
    from_file = any(name == "--input" for name, _ in options) or any(
        value.partition("=")[2].startswith("@") for value in fields
    )
    writes = methods[-1] not in GH_API_READS if methods else bool(fields) or from_file
    if not writes:
        return False
    if RELEASES_ADDRESS.search(address):
        return True
    return REFS_ADDRESS.search(address) is not None and (
        from_file or any(TAG_REF.search(text) for text in (address, *fields))
    )


GIT_RELEASES = {"push": _pushes_release, "tag": _tags_release}


def _releases(program: str, arguments: list[str]) -> bool:
    if program == "git":
        command, rest = _subcommand(arguments, GIT_VALUE_OPTIONS)
        return command in GIT_RELEASES and GIT_RELEASES[command](rest)
    group, rest = _subcommand(arguments, GH_VALUE_OPTIONS)
    if group == "release":
        command, _ = _subcommand(rest, GH_VALUE_OPTIONS)
        return command is not None and command not in GH_RELEASE_READS and "--help" not in rest
    return group == "api" and _writes_release_api(rest)


def releases(command: str, depth: int = 0) -> bool:
    """Czy polecenie Basha zakłada tag Wydania albo GitHub Release poza narzędziem Wydań (formy z docstringu)."""

    shell, substitutions = _lifted(_without_heredocs(command))
    for words in _simple_commands(shell):
        program, arguments = _program(words)
        script = _shell_script(arguments) if program in SHELLS else " ".join(arguments) if program == "eval" else None
        if program in PROGRAMS and _releases(program, arguments):
            return True
        if script is not None and depth < MAX_DEPTH and releases(script, depth + 1):
            return True
    return depth < MAX_DEPTH and any(releases(script, depth + 1) for script in substitutions)


def _release_tool() -> bool:
    """Czy sesja ma zmienną narzędzia Wydań; czyta jej nazwę z ``tools/lib/repo.py`` dopiero przy odmowie."""

    try:
        import repo
    except ImportError:  # checkout bez repo.py: bez nazwy zmiennej odmowa zostaje
        return False
    return os.environ.get(repo.RELEASE_OVERRIDE) == "1"


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0
    if not isinstance(command, str) or not releases(command) or _release_tool():
        return 0
    print(REFUSAL, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
