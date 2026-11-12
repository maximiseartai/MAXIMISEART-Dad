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

Hook dzieli dokładnie tylko podzbiór basha. Słowa to napisy bez cudzysłowu, w apostrofach i w cudzysłowie, ``\\``
z nową linią to dalszy ciąg polecenia, a polecenie proste kończy się na ``;``, ``&``, ``&&``, ``|``, ``||``, nowej
linii i nawiasie. Przekierowanie z celem i deskryptorem (``2>&1``) nie jest argumentem, ``#`` na początku słowa
zaczyna komentarz do końca linii, a ciało heredoku to dane (``_without_heredocs`` hooka ``czekanie.py``).
Podstawienie ``$(…)``, `` `…` ``, ``<(…)`` i ``>(…)``, także zagnieżdżone i w środku słowa
(``$(git rev-parse HEAD):refs/tags/v1``), a ``$(…)`` i `` `…` `` także w cudzysłowie, to w poleceniu słowo o nieznanej
wartości, a treść podstawienia hook ocenia jak osobne polecenie.

Polecenie spoza tego podzbioru, w którym stoi słowo Wydania, dostaje odmowę, a jej przyczyna każe zapisać je prościej
albo rozbić na kilka poleceń. Spoza podzbioru jest polecenie, którego hook nie umie podzielić (niezamknięty
cudzysłów, także po ``\\'`` w napisie ANSI-C ``$'…'``, niezamknięte podstawienie albo heredok, ``\\`` na końcu,
podstawienia głębiej niż ``MAX_DEPTH``), polecenie z konstrukcją ze stałej ``OUTSIDE_SUBSET`` (``$((`` w tekście;
powłoka, ``eval``, ``source``, ``.``, ``trap``, ``xargs``, ``case`` i ``function`` jako program) i polecenie, którego
program albo podpolecenie ``git`` lub ``gh`` pochodzi ze zmiennej albo podstawienia, a także ``gh api`` z zapisem na
adres ze zmiennej. Słowo Wydania
(``RELEASE_WORD``) to ``tag``, ``release`` albo wersja z kropką (``v1.2``, także ``tag_name=v1.2``) jako osobne słowo
(cudzysłów go nie kończy), a ``refs/tags``, ``git/refs``, ``/releases``, ``--tags``, ``--follow-tags`` i ``--mirror``
w dowolnym miejscu polecenia poza ciałem zamkniętego heredoku.

Przechodzi wszystko, gdy sesja Claude Code ma w środowisku ``MAXIMISEART_WYDANIE=1`` (nazwa: ``RELEASE_OVERRIDE``
w ``tools/lib/repo.py``), a zmienna wpisana w samo polecenie niczego nie zmienia. ``tools/wydanie.py`` zakłada tag
i Release z Pythona, więc hook go nie widzi i nie zatrzymuje.
Granica: tego, czego nie ma w tekście polecenia, hook nie widzi, więc stronę GitHuba, skrypt z pliku, skrypt
w Pythonie albo innym interpreterze, także podany heredokiem, alias, ``gh api graphql`` (``createRef``)
i ``push.followTags`` z konfiguracji gita łapie tylko przegląd. Tak samo program spoza ``PROGRAMS``, ``WRAPPERS``
i ``OUTSIDE_SUBSET``, który sam uruchamia polecenie ze swoich argumentów (``find -exec``, ``env -S``), linie po
``<<SŁOWO`` w napisie aż do linii ``SŁOWO`` (``_without_heredocs`` bierze je za heredok) i polecenie spoza podzbioru
bez słowa Wydania (``$G push origin v9``). Słowo Wydania w opisie zwykłej pracy daje fałszywą odmowę polecenia spoza
podzbioru: na 285 997 poleceniach Basha agentów z 30 dni (#1414 r4) 10 takich, każde z programem ze zmiennej
i opisem ze słowem ``tag`` albo ``release``. Hook nie zna repozytorium, w którym polecenie biegnie, więc odmowę
dostaje też tag ``v*`` w repozytorium próbnym (``git init`` w katalogu tymczasowym), Release innego repozytorium i push
gałęzi o nazwie od ``v`` z cyfrą (``v2-redesign``). Czas ``shlex`` rośnie z kwadratem długości najdłuższego słowa:
polecenie z napisem ponad ok. 1 MB przekracza ``timeout`` i przechodzi.

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
from typing import NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/hooks"))

from czekanie import _without_heredocs  # jedyny właściciel rozpoznania heredoków w hookach

REFUSAL = (
    "Odmowa: tag Wydania v* i GitHub Release tworzy tylko narzędzie Wydań, bo tag na main trafia do taty (ADR 0014). "
    "Wydanie robi skill wydanie (.agents/skills/wydanie/SKILL.md): .venv/bin/python tools/wydanie.py plan, "
    "a po zgodzie Maksa tools/wydanie.py wydaj. Nie zakładaj ani nie wypychaj tagu v* (git tag, git push, także "
    "z --no-verify), nie twórz ani nie zmieniaj Release i refów tagów (gh release, gh api) i nie rób tego stroną GitHuba."
)
OUTSIDE_REFUSAL = (
    f"{REFUSAL} Polecenie ma też konstrukcję, której hook nie dzieli (powłoka, eval, xargs, case, $((, program "
    "ze zmiennej albo podstawienia, niezamknięty napis), i słowo Wydania (tag, release, refs/tags, /releases): "
    "jeśli nie zakłada Wydania, zapisz je prościej albo rozbij na kilka poleceń."
)

OPERATORS = ";&|()<>\n`"
# ``\`` z nową linią poza parzystą liczbą ``\`` przed nim: bash usuwa je przed podziałem na słowa.
CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# Znaki, po których ``#`` zaczyna komentarz; ``#`` w środku słowa (``$#``, ``issues#1``, ``$(…)#``) go nie zaczyna.
WORD_BREAKS = " \t\r\n;&|()<>"
# Słowo w miejscu podstawienia ``$(…)``, `` `…` ``, ``<(…)`` albo ``>(…)``: jego wartości hook nie zna.
SUBSTITUTION_STANDIN = "$S"
SUBSTITUTIONS = ("$(", "<(", ">(")
# Linia za poleceniem: zostaje po ``_without_heredocs`` tylko wtedy, gdy każdy heredok się zamknął.
HEREDOC_END = "\n\0"
# Przekierowanie w słowie operatora (``2>&1`` daje ``>&``, ``&>``, ``<<<``).
REDIRECTION = re.compile(r"&>>?|[<>]&|>\||<<<|<<-?|<>|>>|[<>]")
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
# Podstawienie w podstawieniu: dalej niż na tej głębokości hook nie zagląda i polecenie jest spoza podzbioru.
MAX_DEPTH = 20


class Constructs(NamedTuple):
    text: re.Pattern[str]
    programs: frozenset[str]


# Konstrukcje spoza podzbioru, który hook dzieli: tekst w poleceniu (bez ciał heredoków) i program polecenia prostego.
# Spoza podzbioru jest też polecenie, którego hook nie umie podzielić, z niezamkniętym heredokiem, programem
# albo podpoleceniem ``git``/``gh`` ze zmiennej lub podstawienia i ``gh api`` z zapisem na adres ze zmiennej.
OUTSIDE_SUBSET = Constructs(
    text=re.compile(r"\$\(\("),
    programs=frozenset({"bash", "sh", "zsh", "dash", "ksh", "eval", "source", ".", "trap", "xargs", "case", "function"}),
)
# Słowo Wydania: ``tag``, ``release`` albo wersja ``v1.2`` jako osobne słowo (między odstępem, operatorem albo nawiasem;
# wersja także po ``:`` i ``+`` refspecu i po ``=``) albo adres i opcja Wydania w dowolnym miejscu.
EDGE = f"[{re.escape(WORD_BREAKS)}`]"
RELEASE_WORD = re.compile(
    rf"(?:^|(?<={EDGE}))(?:tag|release)(?={EDGE}|$)|(?:^|(?<={EDGE}|[:+=]))v\d+\.\d"
    r"|refs/tags|git/refs|/releases|--tags|--follow-tags|--mirror(?![\w-])"
)

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
    """Indeks za `` ` ``, który zamyka `` ` `` pod ``index`` (bez ``\\`` przed nim), albo -1."""

    index += 1
    while index < len(shell) and shell[index] != "`":
        index += 2 if shell[index] == "\\" else 1
    return index + 1 if index < len(shell) else -1


def _lifted(shell: str, index: int = 0, closer: str = "") -> tuple[str, list[str], int]:
    """Tekst od ``index`` do ``closer`` ze słowem ``$S`` w miejscu podstawień, treści podstawień i indeks za ``closer``.

    ``closer`` to ``)`` podstawienia, ``"`` napisu albo pusty, gdy tekst biegnie do końca polecenia. Komentarz
    wypada z tekstu, a napis w apostrofach zostaje bez zmian. Indeks -1 znaczy, że ``closer``, apostrof, cudzysłów
    albo podstawienie się nie zamyka.
    """

    outer: list[str] = []
    substitutions: list[str] = []
    depth, previous = 0, " "
    while index < len(shell):
        char = shell[index]
        if char == closer and (closer == '"' or depth == 0):
            return "".join(outer), substitutions, index + 1
        if char == "\\":
            piece, end = shell[index : index + 2], index + 2
        elif (shell.startswith(SUBSTITUTIONS, index) and (char == "$" or closer != '"')) or char == "`":
            end = _backtick_end(shell, index) if char == "`" else _lifted(shell, index + 2, ")")[2]
            if end < 0:
                return "".join(outer), substitutions, -1
            substitutions.append(shell[index + (1 if char == "`" else 2) : end - 1])
            piece = SUBSTITUTION_STANDIN
        elif closer == '"':
            piece, end = char, index + 1
        elif char == "'":
            end = shell.find("'", index + 1) + 1
            if end == 0:
                return "".join(outer), substitutions, -1
            piece = shell[index:end]
        elif char == '"':
            text, inner, end = _lifted(shell, index + 1, '"')
            if end < 0:
                return "".join(outer), substitutions, -1
            piece = f'"{text}"'
            substitutions.extend(inner)
        elif char == "#" and previous in WORD_BREAKS:
            end = shell.find("\n", index)
            piece, end = "", len(shell) if end < 0 else end
        else:
            depth += {"(": 1, ")": -1}.get(char, 0)
            piece, end = char, index + 1
        outer.append(piece)
        previous = piece[-1] if piece else previous
        index = end
    return "".join(outer), substitutions, -1 if closer else index


def _operator(token: str) -> bool:
    return token != "" and all(char in OPERATORS for char in token)


def _simple_commands(shell: str) -> Iterator[list[str]]:
    """Słowa każdego polecenia prostego, bez przekierowań i ich celów; ``ValueError``, gdy ``shlex`` go nie podzieli."""

    lexer = shlex.shlex(CONTINUATION.sub(r"\1", shell), posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    words: list[str] = []
    target = False
    for token in list(lexer):
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


def _api_write(arguments: list[str]) -> tuple[str, list[str], bool]:
    """Adres ``gh api`` z zapisem (pusty bez zapisu), jego pola i czy treść idzie z pliku."""

    options, positionals = _parsed(arguments, GH_API_VALUE_OPTIONS)
    methods = [value.upper() for name, value in options if name in ("-X", "--method")]
    fields = [value for name, value in options if name in GH_API_FIELDS]
    from_file = any(name == "--input" for name, _ in options) or any(
        value.partition("=")[2].startswith("@") for value in fields
    )
    writes = methods[-1] not in GH_API_READS if methods else bool(fields) or from_file
    return (positionals[0] if positionals and writes else ""), fields, from_file


def _writes_release_api(arguments: list[str]) -> bool:
    address, fields, from_file = _api_write(arguments)
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


def _outside_subset(program: str, arguments: list[str]) -> bool:
    """Czy polecenie proste jest spoza podzbioru: jego program albo podpolecenie ``git``/``gh`` hook zna tylko z nazwy."""

    if program in OUTSIDE_SUBSET.programs or "$" in program:
        return True
    if program not in PROGRAMS:
        return False
    command, rest = _subcommand(arguments, GIT_VALUE_OPTIONS if program == "git" else GH_VALUE_OPTIONS)
    if command is not None and "$" in command:
        return True
    return command == "api" and _api_write(rest)[0].startswith("$")


def _scanned(shell: str, depth: int) -> tuple[bool, bool]:
    """Czy polecenie albo jego podstawienie zakłada Wydanie i czy ma konstrukcję spoza podzbioru."""

    outer, substitutions, end = _lifted(shell)
    outside = end < 0 or OUTSIDE_SUBSET.text.search(shell) is not None
    try:
        commands = list(_simple_commands(outer))
    except ValueError:  # niezamknięty cudzysłów albo ``\`` na końcu
        commands, outside = [], True
    for words in commands:
        program, arguments = _program(words)
        if program in PROGRAMS and _releases(program, arguments):
            return True, outside
        outside = outside or _outside_subset(program, arguments)
    for script in substitutions:
        release, inner = _scanned(script, depth + 1) if depth < MAX_DEPTH else (False, True)
        if release:
            return True, outside
        outside = outside or inner
    return False, outside


def refusal(command: str) -> Optional[str]:
    """Przyczyna odmowy polecenia Basha (forma Wydania albo polecenie spoza podzbioru ze słowem Wydania) albo None."""

    shell = _without_heredocs(command + HEREDOC_END)
    if not shell.endswith(HEREDOC_END):  # heredok bez linii końca: jego ciało może być poleceniem
        release, outside, shell = False, True, command
    else:
        shell = shell.removesuffix(HEREDOC_END)
        try:
            release, outside = _scanned(shell, 0)
        except RecursionError:  # setki zagnieżdżonych podstawień albo napisów
            release, outside = False, True
    if release:
        return REFUSAL
    return OUTSIDE_REFUSAL if outside and RELEASE_WORD.search(shell) else None


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
    reason = refusal(command) if isinstance(command, str) else None
    if reason is None or _release_tool():
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
