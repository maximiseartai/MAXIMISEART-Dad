#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca ręczny tag Wydania i GitHub Release.

Tag Wydania ``v*`` i GitHub Release tworzy tylko narzędzie Wydań ``tools/wydanie.py`` ze skilla ``wydanie``, bo tag
na ``main`` trafia do taty (ADR 0014), a brama ``tools/hooks/pre-push`` widzi tylko ``git push`` z hookami. Hook
odrzuca więc (kod 2, przyczyna z drogą przez skill na stderr trafia do agenta), na pierwszym planie i w tle,
polecenie proste z podzbioru opisanego niżej, którego programem jest ``git``, ``gh`` albo ``gh-axi`` (także ze ścieżką
i za przypisaniem zmiennej), a w nim:

- ``gh release`` z innym podpoleceniem niż ``list``, ``ls``, ``view``, ``download``, ``verify`` i ``verify-asset``,
  chyba że ``--help`` stoi zaraz za podpoleceniem albo za słowem, które nie jest opcją czekającą na wartość
  (``--notes --help`` to treść ``--notes``);
- ``gh api`` z zapisem (``-X``/``--method`` innym niż ``GET`` i ``HEAD``, a bez metody z ``-f``, ``-F``,
  ``--field``, ``--raw-field`` albo ``--input``) na adres z segmentem ``releases`` albo na ``git/refs``, gdy adres
  albo pole wskazuje ``refs/tags/`` z nazwą od ``v`` albo nieznaną (``$``, ``*``) albo gdy treść idzie z pliku
  (``--input``, pole ``=@plik``);
- ``git push`` z ``--tags``, ``--follow-tags`` albo ``--mirror``, ze słowem spoza podzbioru albo ze wzorcem ścieżek
  albo z argumentem, którego
  strona refspecu (bez ``+``, po obu stronach ``:``) to ``v`` z cyfrą albo ``refs/tags/`` lub ``tags/`` z nazwą od
  ``v`` albo nieznaną, albo z nazwą od ``v`` albo nieznaną po słowie ``tag``;
- ``git tag`` bez trybu listy, usunięcia i weryfikacji (``-l``, ``-d``, ``-v``, ``-n``, ``--list``, ``--delete``,
  ``--verify``, ``--contains``, ``--no-contains``, ``--merged``, ``--no-merged``, ``--points-at``) z argumentem od
  ``v``, od ``refs/tags/v``, nieznanym albo spoza podzbioru;
- ``git update-ref`` bez ``-d`` z refem ``refs/tags/`` albo ``tags/`` z nazwą od ``v`` albo nieznaną.

Podzbiór to tylko to, co hook rozumie; reszta jest spoza niego:

- słowo to napisy bez cudzysłowu, w apostrofach i w cudzysłowie; bez cudzysłowu ma tylko litery, cyfry, znaki
  ``LITERAL``, znak po ``\\``, ``=`` poza początkiem słowa (zsh czyta ``=git`` jako ścieżkę programu), ``{`` jako całe
  słowo, ``{}`` i ``{nazwa}`` (``PLAIN_BRACES``), ``[`` i ``[[`` jako całe słowo oraz znaki wzorca ścieżek ``*``, ``?``
  i ``[``, z którymi słowo ma nieznaną wartość;
- ``$`` przed nazwą zmiennej, cyfrą, parametrem specjalnym albo ``{nazwa}`` (``PARAMETER``) i ``${nazwa`` z operatorem
  (``EXPANSION``), także w cudzysłowie, daje słowo o nieznanej wartości, a ``$`` przed odstępem, operatorem i końcem
  jest zwykłym znakiem; podstawienie ``$(…)``, `` `…` ``, ``<(…)`` i ``>(…)`` (także zagnieżdżone, w środku słowa,
  w ``${…}``, a ``$(…)`` i `` `…` `` także w cudzysłowie) to słowo o nieznanej wartości, a jego treść hook ocenia jak
  osobne polecenie;
- polecenie proste kończą ``;``, ``&``, ``&&``, ``|``, ``||``, ``|&`` i nowa linia, każdy za poleceniem, ``(`` zaczyna
  podpowłokę tylko na początku polecenia, a ``()`` za słowem definiuje funkcję; ``\\`` z nową linią to dalszy ciąg
  polecenia, przekierowanie z celem i deskryptorem (``2>&1``) nie jest argumentem, ``#`` na początku słowa zaczyna
  komentarz do końca linii, a ciało heredoku to dane (``_without_heredocs`` hooka ``czekanie.py``), gdy ``<<`` stoi
  poza napisem i komentarzem, a ogranicznik w cudzysłowie albo ciało bez podstawienia;
- program to pierwsze słowo za słowami ``RESERVED`` i przypisaniami, o znanej wartości; ``git``, ``gh`` i ``gh-axi``
  stoją w podzbiorze tylko w tym miejscu (nie w argumencie, wartości przypisania, ``${…}`` ani celu przekierowania),
  ``git`` z opcjami przed poleceniem z ``GIT_OPTIONS`` i poleceniem z ``GIT_COMMANDS`` (alias, także z ``-c alias.``,
  nie może zastąpić polecenia gita), a ``gh`` z ``GH_OPTIONS`` i ``GH_COMMANDS``; powłoka (``SHELLS``) nie stoi w podzbiorze w żadnym
  miejscu, a jej polecenia, które wykonują napis albo zmieniają czytanie dalszych poleceń (``SHELL_BUILTINS``), jako
  program.

Hook dzieli polecenie jak bash, a agent na Macu biegnie w zsh: tekst, który zsh z domyślnymi opcjami czyta inaczej
niż bash (``=git``, ``<1-9>``, ``(…)`` w środku polecenia, ``for x (…)``, ``${(f)x}``), jest spoza podzbioru,
a ``$x[1]`` ma nieznaną wartość. Spoza podzbioru jest więc też polecenie, w którym ``git`` albo ``gh`` stoi za innym
programem (``xargs git``, ``sudo gh``, ``coproc git``, ``X=git; env $X``), a ``gh api`` pisze na adres o nieznanej
wartości. Polecenie spoza podzbioru, w którym stoi słowo Wydania, dostaje odmowę, a jej przyczyna każe zapisać je
prościej albo rozbić na kilka poleceń. Słowo Wydania (``RELEASE_WORD``) to ``tag``, ``release`` albo wersja z kropką
(``v1.2``, także ``tag_name=v1.2``) jako osobne słowo (cudzysłów go nie kończy, a nawias klamrowy i przecinek tak),
a ``refs/tags``, ``git/refs``, ``/releases``, ``--tags``, ``--follow-tags`` i ``--mirror`` w dowolnym miejscu polecenia
poza ciałem heredoku, które jest danymi. Polecenie spoza podzbioru bez słowa Wydania przechodzi, także gdy słowo
Wydania składa się w nim z części (``sh -c 'git t"a"g v"9"'``), a ``git push`` nazwy o nieznanej wartości bez
``refs/tags/`` (``git push origin $V``) przechodzi w podzbiorze.

Przechodzi wszystko, gdy sesja Claude Code ma w środowisku ``MAXIMISEART_WYDANIE=1`` (nazwa: ``RELEASE_OVERRIDE``
w ``tools/lib/repo.py``), a zmienna wpisana w samo polecenie niczego nie zmienia. ``tools/wydanie.py`` zakłada tag
i Release z Pythona, więc hook go nie widzi i nie zatrzymuje.
Granica: hook widzi tylko tekst polecenia, więc stronę GitHuba, skrypt z pliku (``bash skrypt.sh``, ``source``, hook
gita), Pythona i inny program, który wykonuje napis jako polecenie (interpreter z ``-c`` albo heredokiem,
``git rebase -x``, ``ssh``, ``watch``), alias i funkcję z konfiguracji gita, ``gh`` i powłoki, opcje zsh
z konfiguracji, które zmieniają składnię (``extendedglob``, ``rcquotes``), wartość zmiennej z profilu i nazwy plików,
które wstawia wzorzec ścieżek, ``gh api graphql`` (``createRef``) oraz ``push.followTags`` i ``remote.*.push``
z konfiguracji gita łapie tylko przegląd.
Słowo Wydania w opisie zwykłej pracy daje fałszywą odmowę polecenia spoza podzbioru: na 285 997 poleceniach Basha
agentów z 30 dni (#1414 r5) 13 takich: 11 z programem ze zmiennej i opisem ze słowem ``tag``, ``release`` albo
wersją, jedno z nawiasami ``{a,b}`` i jedno z ``gh api`` piszącym na adres ze zmiennej. Hook nie zna repozytorium, w którym polecenie biegnie, więc odmowę
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

from czekanie import HEREDOC, _without_heredocs  # jedyny właściciel rozpoznania heredoków w hookach

REFUSAL = (
    "Odmowa: tag Wydania v* i GitHub Release tworzy tylko narzędzie Wydań, bo tag na main trafia do taty (ADR 0014). "
    "Wydanie robi skill wydanie (.agents/skills/wydanie/SKILL.md): .venv/bin/python tools/wydanie.py plan, "
    "a po zgodzie Maksa tools/wydanie.py wydaj. Nie zakładaj ani nie wypychaj tagu v* (git tag, git push, także "
    "z --no-verify), nie twórz ani nie zmieniaj Release i refów tagów (gh release, gh api) i nie rób tego stroną GitHuba."
)
OUTSIDE_REFUSAL = (
    f"{REFUSAL} Polecenie ma też tekst, którego hook nie czyta (nawiasy {{a,b}}, $'…', git lub gh za innym "
    "programem, powłoka, program ze zmiennej, niezamknięty napis), i słowo Wydania (tag, release, refs/tags, "
    "/releases): jeśli nie zakłada Wydania, zapisz je prościej albo rozbij na kilka poleceń."
)

OPERATORS = ";&|()<>\n`"
# ``\`` z nową linią poza parzystą liczbą ``\`` przed nim: bash usuwa je przed podziałem na słowa.
CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# Znaki, po których ``#`` zaczyna komentarz; ``#`` w środku słowa (``$#``, ``issues#1``, ``$(…)#``) go nie zaczyna.
WORD_BREAKS = " \t\r\n;&|()<>"
# Słowo w miejscu podstawienia ``$(…)``, `` `…` ``, ``<(…)`` albo ``>(…)``: jego wartości hook nie zna.
SUBSTITUTION_STANDIN = "$S"
SUBSTITUTIONS = ("$(", "<(", ">(")
# Znacznik przed znakiem, którego hook nie czyta: słowo z nim jest spoza podzbioru.
UNREAD = "\x1f"
# Znacznik przed znakiem wzorca ścieżek (``*``, ``?``, ``[…]``): słowo ma nieznaną wartość jak ``$X``.
PATTERN = "\x1e"
# Znaki słowa bez cudzysłowu, które bash i zsh z domyślnymi opcjami biorą dosłownie.
LITERAL = frozenset("_-./:=+@%,^~!]}#")
# ``{`` jako słowo, ``{}`` i ``{nazwa}`` bez ``,`` i ``..``: bash i zsh nie rozwijają ich w kilka słów.
PLAIN_BRACES = re.compile(r"\{(?=[\s;&|()<>]|$)|\{(?:[\w-]|\.(?!\.))*\}")
# ``[`` i ``[[`` jako słowo (polecenie ``test``); ``[`` w słowie to wzorzec ścieżek.
PLAIN_BRACKETS = re.compile(r"\[\[?(?=[\s;&|()<>]|$)")
PATTERN_CHARS = frozenset("*?[")
# Po ``$``: nazwa zmiennej, cyfra, parametr specjalny albo ``{nazwa}``; wartość jest nieznana, ale słowo czytelne.
PARAMETER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]|[@*#?$!-]|\{(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+)\}")
# ``${`` z nazwą i operatorem (``${x:-a}``, ``${r##*/}``, ``${#x}``): wartość nieznana, a tekst za nazwą hook czyta
# do ``}`` jak słowo; ``${(f)x}`` i ``${x@P}`` są spoza podzbioru.
EXPANSION = re.compile(r"\$\{[#!]?(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-])")
EXPANSION_PARTS = re.compile(r"[^\w./]+")
# Linia za poleceniem: zostaje po ``_without_heredocs`` tylko wtedy, gdy każdy heredok się zamknął.
HEREDOC_END = "\n\0"
# Przekierowanie w słowie operatora (``2>&1`` daje ``>&``, ``&>``, ``<<<``) i heredok wśród nich.
REDIRECTION = re.compile(r"&>>?|[<>]&|>\||<<<|<<-?|<>|>>|[<>]")
HEREDOC_OPERATORS = frozenset({"<<", "<<-"})
# Podstawienie w ciele heredoku z ogranicznikiem bez cudzysłowu: bash je wykonuje, chyba że stoi za ``\``.
BODY_SUBSTITUTION = re.compile(r"(?<!\\)(?:\\\\)*(?:\$\(|`)")
# Operator, który kończy polecenie proste; dwa takie bez polecenia między nimi (``;;`` w ``case``) są spoza podzbioru.
CONTROL = re.compile(r"&&|\|\||\|&|[;&|()\n]")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
RESERVED = frozenset({"!", "{", "}", "if", "then", "elif", "else", "while", "until", "do", "time"})
# Powłoka i jej polecenia wbudowane, które wykonują napis albo zmieniają, jak powłoka czyta dalsze polecenia.
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
SHELL_BUILTINS = frozenset({"eval", "trap", "source", ".", "alias"})
# Podstawienie zagnieżdżone głębiej, niż hook zagląda: polecenie jest spoza podzbioru.
MAX_DEPTH = 20
# Słowo Wydania: ``tag``, ``release`` albo wersja ``v1.2`` jako osobne słowo (między odstępem, operatorem, nawiasem
# klamrowym i przecinkiem; wersja także po ``:`` i ``+`` refspecu i po ``=``) albo adres i opcja Wydania.
EDGE = f"[{re.escape(WORD_BREAKS)}`{{}},]"
RELEASE_WORD = re.compile(
    rf"(?:^|(?<={EDGE}))(?:tag|release)(?={EDGE}|$)|(?:^|(?<={EDGE}|[:+=]))v\d+\.\d"
    r"|refs/tags|git/refs|/releases|--tags|--follow-tags|--mirror(?![\w-])"
)

PROGRAMS = frozenset({"git", "gh", "gh-axi"})


class Options(NamedTuple):
    """Opcje programu przed podpoleceniem, które hook zna: z wartością w osobnym słowie albo po ``=`` i flagi."""

    values: frozenset[str]
    flags: frozenset[str]


GIT_OPTIONS = Options(
    values=frozenset(
        {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source", "--list-cmds"}
    ),
    flags=frozenset(
        {"-v", "--version", "-h", "--help", "-p", "--paginate", "-P", "--no-pager", "--bare", "--exec-path"}
        | {"--html-path", "--man-path", "--info-path", "--no-replace-objects", "--no-lazy-fetch", "--no-advice"}
        | {"--no-optional-locks", "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}
    ),
)
GH_OPTIONS = Options(values=frozenset({"-R", "--repo"}), flags=frozenset({"-h", "--help", "--version"}))
# Polecenia gita 2.50 (``git --list-cmds=main,nohelpers``) i ``gh`` 2.101 (``gh help``); inne słowo to alias
# z konfiguracji albo rozszerzenie, których hook nie zna.
GIT_COMMANDS = frozenset(
    """
    add am annotate apply archive backfill bisect blame branch bugreport bundle cat-file check-attr check-ignore
    check-mailmap check-ref-format checkout checkout-index cherry cherry-pick clean clone column commit commit-graph
    commit-tree config count-objects credential credential-cache credential-osxkeychain credential-store daemon
    describe diagnose diff diff-files diff-index diff-pairs diff-tree difftool fast-export fast-import fetch
    fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo format-patch fsck fsck-objects gc
    get-tar-commit-id grep hash-object help hook http-backend http-fetch http-push imap-send index-pack init init-db
    interpret-trailers lfs log ls-files ls-remote ls-tree mailinfo mailsplit maintenance merge merge-base merge-file
    merge-index merge-octopus merge-one-file merge-ours merge-recursive merge-recursive-ours merge-recursive-theirs
    merge-resolve merge-subtree merge-tree mergetool mktag mktree multi-pack-index mv name-rev notes p4 pack-objects
    pack-redundant pack-refs patch-id pickaxe prune prune-packed pull push quiltimport range-diff read-tree rebase
    receive-pack reflog refs remote remote-ext remote-fd remote-ftp remote-ftps remote-http remote-https repack
    replace replay request-pull rerere reset restore rev-list rev-parse revert rm send-email send-pack shell
    shortlog show show-branch show-index show-ref sparse-checkout stage stash status stripspace submodule subtree
    switch symbolic-ref tag unpack-file unpack-objects update-index update-ref update-server-info upload-archive
    upload-pack var verify-commit verify-pack verify-tag version whatchanged worktree write-tree
    """.split()
)
GH_COMMANDS = frozenset(
    """
    agent-task alias api attestation auth browse cache co codespace completion config copilot discussion extension
    ext gist gpg-key help issue label licenses org pr preview project release repo ruleset run search secret skill
    ssh-key status variable version workflow
    """.split()
)
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
TAG_REF = re.compile(r"(?:refs/)?tags/(?:v|[^A-Za-z0-9_.-]|$)")
# ``refs/tags/`` i ``tags/``, które git rozwija do ``refs/tags/``.
TAG_PREFIX = re.compile(r"(?:refs/)?tags/")
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


class Scan(NamedTuple):
    release: bool
    outside: bool
    heredocs: int


def _backtick_end(shell: str, index: int) -> int:
    """Indeks za `` ` ``, który zamyka `` ` `` pod ``index`` (bez ``\\`` przed nim), albo -1."""

    index += 1
    while index < len(shell) and shell[index] != "`":
        index += 2 if shell[index] == "\\" else 1
    return index + 1 if index < len(shell) else -1


def _read(shell: str, index: int, previous: str) -> str:
    """Znak bez cudzysłowu pod ``index``, a przed nim ``UNREAD`` albo ``PATTERN``, gdy bash i zsh czytają go inaczej."""

    char = shell[index]
    if char in PATTERN_CHARS:
        return PATTERN + char
    if char == "{":
        plain = PLAIN_BRACES.match(shell, index) is not None
    elif char == "=" and previous in WORD_BREAKS:  # zsh: ``=git`` to ścieżka programu, ``=(…)`` plik z wyjściem
        plain = shell[index + 1 : index + 2] in ("", " ", "\t", "\r", "\n", ";", "&", "|", ")", "=")
    elif char == "<":  # zsh: ``<1-9>`` to wzorzec liczb
        plain = re.match(r"<\d*-\d*>", shell[index:]) is None
    else:
        plain = char.isalnum() or not char.isascii() or char in WORD_BREAKS or char in LITERAL
    return char if plain else UNREAD + char


def _dollar(shell: str, index: int, quoted: bool) -> tuple[str, int]:
    """``$`` pod ``index`` poza podstawieniem: parametr, zwykły znak albo znak, którego hook nie czyta."""

    parameter = PARAMETER.match(shell, index + 1)
    if parameter:
        return shell[index : parameter.end()], parameter.end()
    following = shell[index + 1 : index + 2]
    literal = following in ("", *WORD_BREAKS) or (quoted and following in "'\"")
    return ("$" if literal else UNREAD + "$"), index + 1


def _lifted(shell: str, index: int = 0, closer: str = "") -> tuple[str, list[str], int]:
    """Tekst od ``index`` do ``closer`` ze słowem ``$S`` w miejscu podstawień, treści podstawień i indeks za ``closer``.

    ``closer`` to ``)`` podstawienia, ``}`` rozwinięcia ``${…}``, ``"`` napisu albo pusty, gdy tekst biegnie do końca
    polecenia. ``${…}`` z operatorem też staje się słowem ``$S``. Komentarz wypada z tekstu, napis w apostrofach zostaje
    bez zmian, a przed znakiem, którego hook nie czyta, stoi ``UNREAD``, i ``PATTERN`` przed znakiem wzorca ścieżek.
    Indeks -1 znaczy, że ``closer``, apostrof, cudzysłów albo podstawienie się nie zamyka.
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
            # ``$((…))`` to arytmetyka, a nie podstawienie polecenia.
            piece = (UNREAD if shell.startswith("$((", index) else "") + SUBSTITUTION_STANDIN
        elif shell.startswith("${", index) and not PARAMETER.match(shell, index + 1):
            expansion = EXPANSION.match(shell, index)
            if expansion is None or shell.startswith("@", expansion.end()):  # ``${(f)x}``, ``${x@P}``
                piece, end = UNREAD + "$", index + 1
            else:
                text, inner, end = _lifted(shell, expansion.end(), "}")
                if end < 0:
                    return "".join(outer), substitutions, -1
                substitutions.extend(inner)
                named = any(_names_program(part, False) for part in EXPANSION_PARTS.split(text))
                piece = (UNREAD if named else "") + SUBSTITUTION_STANDIN
        elif char == "$":
            piece, end = _dollar(shell, index, closer == '"')
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
        elif char == "#" and previous in WORD_BREAKS and closer != "}":
            end = shell.find("\n", index)
            piece, end = "", len(shell) if end < 0 else end
        else:
            depth += {"(": 1, ")": -1}.get(char, 0)
            bracket = PLAIN_BRACKETS.match(shell, index) if previous in WORD_BREAKS else None
            piece, end = (bracket.group(), bracket.end()) if bracket else (_read(shell, index, previous), index + 1)
        outer.append(piece)
        previous = piece[-1] if piece else previous
        index = end
    return "".join(outer), substitutions, -1 if closer else index


def _operator(token: str) -> bool:
    return token != "" and all(char in OPERATORS for char in token)


def _simple_commands(shell: str, redirections: list[tuple[str, str]]) -> Iterator[list[str]]:
    """Słowa każdego polecenia prostego, bez przekierowań i ich celów; ``ValueError`` poza podzbiorem.

    ``redirections`` dostaje każde przekierowanie (operator i cel), które stoi poza napisem i komentarzem.
    """

    lexer = shlex.shlex(CONTINUATION.sub(r"\1", shell), posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    words: list[str] = []
    target, depth, after_control = "", 0, True
    for token in list(lexer):
        if not _operator(token):
            if target:
                redirections.append((target, token))
                target = ""
            else:
                words.append(token)
            after_control = False
            continue
        index = 0
        while index < len(token):
            redirection = REDIRECTION.match(token, index)
            if redirection:
                if index == 0 and words and words[-1].isdigit():
                    words.pop()  # deskryptor przekierowania: ``2>&1`` to dla ``shlex`` słowo ``2`` i operator ``>&``
                target, index = redirection.group(), redirection.end()
                continue
            control = CONTROL.match(token, index)
            if control is None:
                raise ValueError(token)
            piece, index = control.group(), control.end()
            if piece == "(" and token.startswith(")", index) and words:
                index += 1  # ``f()``: definicja funkcji
            elif piece == "(":
                if any(word not in RESERVED for word in words):
                    raise ValueError(token)  # nawias w środku polecenia: zsh czyta go jako wzorzec
                depth += 1
            elif piece == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError(token)  # wzorzec ``case``
            elif piece != "\n" and after_control:
                raise ValueError(token)
            after_control = piece != ")"
            if words:
                yield words
            words = []
    if words:
        yield words


def _names_program(word: str, position: bool) -> bool:
    """Czy słowo albo wartość za ``=`` to ``git``/``gh`` albo powłoka (bez ścieżki); polecenie wbudowane powłoki
    (``eval``, ``.``) tylko w miejscu programu, bo inny program go nie uruchomi."""

    names = {part.rsplit("/", 1)[-1] for part in (word, word.partition("=")[2])}
    return bool(names & PROGRAMS or names & SHELLS or (position and names & SHELL_BUILTINS))


def _subcommand(arguments: list[str], known: Options) -> tuple[Optional[str], list[str], bool]:
    """Podpolecenie, jego argumenty i czy każda opcja przed nim jest znana."""

    index = 0
    while index < len(arguments):
        word = arguments[index]
        name = word.partition("=")[0]
        if word in known.values:
            index += 2
        elif word in known.flags or (word != name and name.startswith("--") and name in known.values | known.flags):
            index += 1
        elif word.startswith("-"):
            return None, [], False
        else:
            return word, arguments[index + 1 :], True
    return None, [], True


def _unknown(word: Optional[str]) -> bool:
    """Czy wartość słowa jest nieznana (zmienna, podstawienie) albo słowo jest spoza podzbioru."""

    return word is not None and ("$" in word or UNREAD in word or PATTERN in word)


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
    prefix = TAG_PREFIX.match(name)
    return _unknown(name) or RELEASE_TAG.match(name[prefix.end() if prefix else 0 :]) is not None


def _pushes_release(arguments: list[str]) -> bool:
    if any(UNREAD in word or PATTERN in word for word in arguments):  # ``?9.9.9``, ``{v9.9.9,}``: nazwa nieznana
        return True
    options, positionals = _parsed(arguments, PUSH_VALUE_OPTIONS)
    if any(name in PUSH_ALL_TAGS for name, _ in options):
        return True
    after_tag = False
    for word in positionals:
        if after_tag and _release_tag(word):
            return True
        after_tag = word == "tag"
        for side in word.lstrip("+").split(":", 1):
            if _release_tag(side) if TAG_PREFIX.match(side) else PUSHED_RELEASE.match(side) is not None:
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


def _updates_tag(arguments: list[str]) -> bool:
    options, positionals = _parsed(arguments, frozenset({"-m"}))
    if any(name == "-d" for name, _ in options):
        return False
    return bool(positionals) and TAG_PREFIX.match(positionals[0]) is not None and _release_tag(positionals[0])


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


def _writes_release_api(address: str, fields: list[str], from_file: bool) -> bool:
    if RELEASES_ADDRESS.search(address):
        return True
    return REFS_ADDRESS.search(address) is not None and (
        from_file or any(TAG_REF.search(text) for text in (address, *fields))
    )


def _help(arguments: list[str]) -> bool:
    """Czy ``--help`` stoi zaraz za podpoleceniem albo za słowem, które nie jest opcją czekającą na wartość."""

    return any(
        word == "--help" and (index == 0 or not arguments[index - 1].startswith("-") or "=" in arguments[index - 1])
        for index, word in enumerate(arguments)
    )


GIT_RELEASES = {"push": _pushes_release, "tag": _tags_release, "update-ref": _updates_tag}


def _releases(program: str, arguments: list[str]) -> tuple[bool, bool]:
    """Czy polecenie ``git``/``gh`` zakłada Wydanie i czy jest spoza podzbioru."""

    if program == "git":
        command, rest, known = _subcommand(arguments, GIT_OPTIONS)
        if not known or (command is not None and command not in GIT_COMMANDS):
            return False, True
        return command in GIT_RELEASES and GIT_RELEASES[command](rest), False
    group, rest, known = _subcommand(arguments, GH_OPTIONS)
    if not known or (group is not None and group not in GH_COMMANDS):
        return False, True
    if group == "release":
        command, rest, known = _subcommand(rest, GH_OPTIONS)
        if not known or _unknown(command):
            return False, True
        return command is not None and command not in GH_RELEASE_READS and not _help(rest), False
    if group != "api":
        return False, False
    address, fields, from_file = _api_write(rest)
    return _writes_release_api(address, fields, from_file), _unknown(address)


def _command(words: list[str]) -> tuple[bool, bool]:
    """Czy polecenie proste zakłada Wydanie i czy jest spoza podzbioru."""

    index = 0
    while index < len(words) and (words[index] in RESERVED or ASSIGNMENT.match(words[index])):
        index += 1
    program = words[index] if index < len(words) else ""
    modelled = program.rsplit("/", 1)[-1] in PROGRAMS
    outside = _unknown(program) or any(
        UNREAD in word or (_names_program(word, position == index) and not (modelled and position == index))
        for position, word in enumerate(words)
    )
    if not modelled:
        return False, outside
    release, unread = _releases(program.rsplit("/", 1)[-1], words[index + 1 :])
    return release, outside or unread


def _scanned(shell: str, depth: int) -> Scan:
    """Czy polecenie albo jego podstawienie zakłada Wydanie, czy jest spoza podzbioru i ile ma heredoków."""

    outer, substitutions, end = _lifted(shell)
    redirections: list[tuple[str, str]] = []
    try:
        commands = list(_simple_commands(outer, redirections))
    except ValueError:  # niezamknięty cudzysłów, ``\`` na końcu albo operator spoza podzbioru
        commands, end = [], -1
    # Cel przekierowania to słowo jak argument: ``read X <<< git`` nazywa gita poza miejscem programu.
    outside = end < 0 or any(UNREAD in target or _names_program(target, False) for _, target in redirections)
    heredocs = sum(operator in HEREDOC_OPERATORS for operator, _ in redirections)
    for words in commands:
        release, unread = _command(words)
        if release:
            return Scan(True, outside, heredocs)
        outside = outside or unread
    for script in substitutions:
        inner = _scanned(script, depth + 1) if depth < MAX_DEPTH else Scan(False, True, 0)
        if inner.release:
            return Scan(True, outside, heredocs)
        outside = outside or inner.outside
        heredocs += inner.heredocs
    return Scan(False, outside, heredocs)


def refusal(command: str) -> Optional[str]:
    """Przyczyna odmowy polecenia Basha (forma Wydania albo polecenie spoza podzbioru ze słowem Wydania) albo None."""

    expanded: list[str] = []
    shell = _without_heredocs(command + HEREDOC_END, expanded)
    if not shell.endswith(HEREDOC_END):  # heredok bez linii końca: jego ciało może być poleceniem
        release, outside, shell = False, True, command
    else:
        shell = shell.removesuffix(HEREDOC_END)
        try:
            scan = _scanned(shell, 0)
        except RecursionError:  # setki zagnieżdżonych podstawień albo napisów
            scan = Scan(False, True, -1)
        release, outside = scan.release, scan.outside
        # ``<<`` w napisie albo komentarzu: ``_without_heredocs`` wziął za ciało heredoku linie, które są poleceniem.
        if scan.heredocs != len(HEREDOC.findall(shell)) or any(BODY_SUBSTITUTION.search(line) for line in expanded):
            outside, shell = True, command
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
