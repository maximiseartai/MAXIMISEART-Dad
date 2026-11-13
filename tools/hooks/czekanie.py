#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca blokujące czekanie na CI, pętle ``pgrep -f`` i gołe ponowienie runu.

Agent na pierwszym planie, który pętli ``until/while/for … sleep`` na ``gh pr checks``, stoi do limitu 600 s
Basha, choć CI i tak powiadamia: wątek główny przez ``watch_pull_request`` T3, a polecenie w tle przez
powiadomienie ``run_in_background``. Pętla ``until ! pgrep -f X`` nigdy się nie kończy, bo ``pgrep -f``
znajduje powłokę, której linia polecenia zawiera tę samą pętlę, a więc i ``X`` (z tego samego powodu
``until pgrep -f X`` kończy się od razu).

Odrzuca (kod 2, przyczyna na stderr trafia do agenta) tylko polecenie na pierwszym planie:
pętlę z ``sleep``, której ciało pyta o CI (``gh pr checks``, ``gh pr view``, ``gh run view``/``list``, ``gh api``
o check-runs, actions/runs albo status commitu) albo woła ``pgrep -f``, oraz ``gh pr checks --watch`` i ``gh run watch``.
Pętla ``for`` i ``while read`` czeka tylko z ``break``, ``exit``, ``return`` albo licznikiem prób od 0 albo 1
(``$(seq N)``, ``$(seq 1 N)``, ``{1..N}``, ``for ((``), bo bez nich to partia zapytań z ``sleep`` jako limitem API,
a pętla puszczona ``&`` nie czeka: sama, w liście z ``|``, ``&&`` albo ``||``, w grupie ``( … )`` albo ``{ …; }``.
``&`` w grupie za pętlą (``done | (cat & wait)``) puszcza w tło tylko tę grupę.
Ponowienie runu GitHub Actions odrzuca zawsze, także w tle, bo o ponowieniu decyduje ``tools/ponow_ci.py``: czeka
na koniec runu, odróżnia awarię runnera od defektu i przy wspólnej awarii ponawia tylko kanarka. Hook czyta każde
polecenie proste słowami ``shlex``: za słowem ``gh`` albo ``gh-axi`` w dowolnym miejscu (za ``env``, ``xargs``,
``command``, ale też w ``echo gh run rerun``, bo hook nie wylicza programów, które uruchamiają ``gh``)
słowa pozycyjne ``run rerun`` z dowolnymi opcjami przed i między nimi (``-R``/``--repo`` z wartością w osobnym słowie)
albo ``api`` z adresem ponowienia Actions (``ADRES_PONOWIENIA``).
Wszystko inne, także czekanie z ``run_in_background``, przechodzi bez słowa (kod 0).
Wejście, którego nie da się odczytać, też przechodzi, bo hook nie może zatrzymać pracy.

Ciała heredoców (skrypt Pythona, treść commitu) i napisy ze spacją w cudzysłowach (opis commitu, wiersz logu)
hook pomija, bo to nie są polecenia powłoki; zostawia z nich ``$(…)`` i ciało ``-c`` powłoki, ``su``, ``runuser``,
``flock`` albo ``script`` z dowolnymi słowami przed ``-c`` (``bash -euo pipefail -c '…'``, ``bash -lc``,
``su -l -s /bin/sh root -c``).

Granica: inne harnessy niż Claude Code (Codex, opencode), pętlę w skrypcie uruchomionym z pliku, w Pythonie
(``time.sleep``) albo z adresem ``gh api`` w cudzysłowie, czekanie na plik wyjścia zadania w tle i pętle, których
wzorca hook nie zna, łapie tylko przegląd. Tak samo ponowienie z ``eval "…"``, z polecenia złożonego ze zmiennych
(``$GH run rerun``), z opcją ``gh`` innej niż ``-R`` z wartością w osobnym słowie między ``run`` a ``rerun`` i przez
skrypt albo program inny niż ``gh``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import json
import re
import shlex
import sys
from typing import Optional

_GH = r"\bgh(?:-axi)?\s+"
ASKS_CI = re.compile(_GH + r"(?:pr\s+(?:checks|view)|run\s+(?:view|list|watch))")
# `gh api` pyta o CI, gdy w tym samym poleceniu prostym (do `;`, `&`, `|` albo nowej linii) stoi adres CI. Pary szuka
# `_in_one_command`, a nie wzorzec `api\b[^;&|\n]*adres`, bo ten od każdego `gh api` czyta do końca polecenia.
GH_API = re.compile(_GH + r"api\b")
CI_ADDRESS = re.compile(r"check-runs|actions/runs|/status\b")
CHECKS = re.compile(_GH + r"pr\s+checks\b")
WATCH_OPTION = re.compile(r"--watch\b")
RUN_WATCH = re.compile(_GH + r"run\s+watch\b")
GH_NAMES = frozenset({"gh", "gh-axi"})
GH_VALUE_OPTIONS = frozenset({"-R", "--repo"})
# Ponowienie runu, jego próby albo zadania w REST API Actions, z zapytaniem albo bez.
ADRES_PONOWIENIA = re.compile(r"actions/(?:runs/[^/\s]+(?:/attempts/[^/\s]+)?/rerun(?:-failed-jobs)?|jobs/[^/\s]+/rerun)(?:\?\S*)?")
# Polecenia proste po ``_code``: między nimi stoją ``;``, ``&``, ``|``, nowa linia, nawiasy, ``$(`` i backtick.
SIMPLE_COMMANDS = re.compile(r"[;&|\n()`]|\$\(")
SIMPLE_COMMAND_END = re.compile(r"[;&|\n]")
PGREP = re.compile(r"\bpgrep\s+(?:-\w+\s+)*-\w*f")
# Agenci śpią też przez `perl -e 'select(undef,undef,undef,N)'`, gdy harness blokuje sam `sleep`; w napisie bez
# spacji nawias jest już podkreśleniem (`QUOTED_SEPARATOR`).
SLEEP = re.compile(r"(?<![\w.$-])sleep\s+\S|\bselect[(_]undef\b")
WHITESPACE = re.compile(r"\s")
# W napisie bez spacji (`perl -e 'select(undef,…)'`, wzorzec `rg '(while|until)'`) słowo pętli nie stoi na pozycji
# polecenia, a nawias nie otwiera ani nie zamyka grupy.
QUOTED_SEPARATOR = re.compile(r"[;&|(){}!`]")
# Słowo pętli liczy się na pozycji polecenia, więc „done” w `grep -q done` nie zamyka pętli, a za `do` też nie, bo
# `do done` z pustym ciałem to błąd składni, a w `do echo do done` „done” jest argumentem. Za początkiem wiersza
# odstęp bez nowej linii: inaczej od każdego z tysięcy pustych wierszy wzorzec czytałby wszystkie następne.
_STARTS = r"(?:^[^\S\n]*|(?:(?<=[;&|({!`])|(?<=\bdo)|(?<=\bthen)|(?<=\belse))\s*)"
_ENDS = r"(?:(?<=\n)[^\S\n]*|(?<=[;&])\s*)"
LOOP_WORD = re.compile(rf"{_STARTS}(until|while|for)\b|{_ENDS}(done)\b", re.MULTILINE)
# `for` i `while read` z `sleep` to zwykle partia zapytań z limitem API (`for id in …; do sleep 2; gh run view $id`),
# a czekaniem są dopiero z wyjściem z pętli albo licznikiem prób od 0 albo 1 (`$(seq 247 264)` to numery PR).
OVER_LIST = re.compile(r"(?:for|while\s+(?:IFS=\S*\s+)?read)\b")
FOR_ARITHMETIC = re.compile(r"for\s*\(\(")
STOPS = re.compile(r"\b(?:break|exit|return)\b(?!=)|\$\(seq\s+(?:[01]\s+)?\d+\s*\)|\{[01]\.\.\d+\}")
# Pętla puszczona `&` (próbnik obok pomiaru, ubijany potem `kill`) nie blokuje polecenia, a `&>`, `>&2`, `2>&1`
# i `|&` to przekierowania, a `\&` to znak. `&` puszcza w tło całą listę do `;` albo nowej linii, także z `|` i `||`
# (`done | tee log &`), a `&` za grupą `( … )` albo `{ …; }` także pętle w niej. Grupa za pętlą (`done | (cat & wait)`,
# `>(cat &)`) to jedno polecenie listy, więc `&` w środku nie dotyczy pętli. `{` grupy ma za sobą odstęp, a `}` przed
# sobą, w odróżnieniu od `${x}` i `{1..3}`. Bez zagnieżdżonych kwantyfikatorów, bo cofanie po `2>1 2>1 …` nie miałoby
# końca.
LIST_PART = re.compile(
    r"(?P<open>\(|\{(?=\s))|(?P<close>\)|(?<=[\s;&])\})"
    r"|(?P<end>[;\n])|(?P<background>(?<![<>&|\\])&(?![&>]))"
)
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")
# Skrypt powłoki to tylko argument `-c` (także złączonego: `-lc`, `-euc`) w poleceniu prostym, w którym stoi słowo
# powłoki, `su`, `runuser`, `flock` albo `script`: `grep -c '…'` liczy wiersze, a `python3 -c '…'` to Python. Słowa
# między nimi mogą być dowolne (`-euo pipefail`, `--rcfile x`, `-s /bin/sh root`), więc `bash skrypt.sh -c '…'` też
# dostaje odmowę. Polecenie proste kończą `;`, `&`, `|` i nowa linia, a `(` i lewy `` ` `` zaczynają polecenie, po
# którym `)` i prawy `` ` `` wracają do zewnętrznego (`bash $(echo -l) -c`). `${…}` to część słowa, więc `;`, `&`,
# `|`, `(` i `)` w nim niczego nie kończą ani nie otwierają (`bash ${x:-)} -c`), ale `$(` i `` ` `` w nim zaczynają
# polecenie, bo bash wykonuje podstawienie w wartości domyślnej (`${x:-$(bash -c '…')}`). Nowa linia zamyka
# niedomknięte `${`, więc `${` w komentarzu nie sięga dalej niż jego linia. Ukośnik przed literą nic nie zmienia
# (`\bash`).
# `fish` i `csh` mają inną składnię pętli, ale pętla bez `done` sięga do końca polecenia.
_SHELLS = r"(?:ba|da|k|z|mk|a|fi|c|tc)?sh|su|runuser|flock|script|\$\{?(?:SHELL|BASH)\}?"
SHELL_NAME = re.compile(rf"(?:{_SHELLS})")
COMMAND_PART = re.compile(
    rf"(?P<shell>(?<![^\s/;&|(`])(?:\\(?=[a-z]))?(?:{_SHELLS})(?![^\s;&|()`]))"
    r"|\\[\s\S]|(?P<parameter>\$\{)|(?P<brace>\})|(?P<substitution>\$\()"
    r"|(?P<end>[;\n]|(?<![<>])&(?!>)|(?<!>)\|)|(?P<open>\()|(?P<close>\))|(?P<tick>`)"
)
SCRIPT_OPTION = re.compile(r"-[a-zA-Z]+")

INSTEAD = (
    "Zamiast czekać: dziecko delegate_task kończy zadanie i zwraca URL PR i pełny SHA HEAD (rodzic ma "
    "watch_pull_request i scal_pr.py, który sam sprawdza CI na HEAD). Wątek główny wywołuje watch_pull_request "
    "i kończy turę, a T3 budzi go po końcu CI, albo uruchamia to samo polecenie z run_in_background: true "
    "i przed końcem tury czeka na jego koniec (w T3 t3_background_wait z jego ID; hook Stop praca_w_tle.py nie "
    "kończy tury z pracą w tle)."
)


@dataclass(frozen=True)
class Refusal:
    reason: str


CI_LOOP = Refusal(f"Odmowa: pętla z sleep na pierwszym planie czeka na CI. {INSTEAD}")
WATCHING = Refusal(f"Odmowa: gh pr checks --watch i gh run watch blokują na pierwszym planie. {INSTEAD}")
RERUN = Refusal(
    "Odmowa: o ponowieniu runu CI decyduje tools/ponow_ci.py: .venv/bin/python tools/ponow_ci.py N (najnowszy run CI "
    "na HEAD PR N) albo --run ID (Windows: py -3 tools/ponow_ci.py). Czeka na koniec runu, odróżnia awarię runnera od "
    "defektu po logach padniętych zadań, przy wspólnej awarii ponawia tylko kanarka, a przy defekcie podaje polecenie "
    "tools/ci_lokalnie.py --tylko <zadanie>."
)
PGREP_LOOP = Refusal(
    "Odmowa: pętla z sleep na pgrep -f nie widzi procesu, bo pgrep -f znajduje własną powłokę tej pętli: "
    "until ! pgrep -f X i while pgrep -f X nie kończą się nigdy, a until pgrep -f X kończy się od razu. "
    "Na własny proces uruchom go Bashem z run_in_background: true i przed końcem tury czekaj na jego koniec "
    "(w T3 t3_background_wait z jego ID), "
    "a na proces ze znanym PID sprawdzaj kill -0 $PID, nie pgrep."
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


def _code(command: str, start: int = 0, inside_substitution: bool = False) -> tuple[str, int]:
    """Polecenie bez tekstu w cudzysłowach, ale z ``$(…)`` w nich i z ciałem ``bash -c '…'``.

    Proza w argumentach (opis commitu, wiersz logu, wzorzec ``sed``) nie jest poleceniem, nawet gdy cytuje pętlę.
    Zwraca też indeks za ``)``, która zamyka ``$(`` przy ``inside_substitution``.
    """

    kept: list[str] = []
    scripts = _ShellScripts(command, start)
    # Napis przyklejony do skryptu ``-c`` to jego dalszy ciąg: w ``bash -c '… perl -e '\''select(…)'\''; done'``
    # ``done`` stoi w trzecim napisie.
    depth, index, script_end = 0, start, -1
    while index < len(command):
        char = command[index]
        if char == "\\":
            kept.append(command[index : index + 2])
            if index == script_end:
                script_end += 2
            index += 2
            continue
        if char in "'\"":
            literal, end = _quoted(command, index)
            script = scripts.is_script(index, end)
            if index == script_end:
                kept.append(command[index + 1 : end])
                script_end = end
            elif script:
                kept.append(";" + command[index + 1 : end])
                script_end = end
            else:
                kept.append(literal)
            index = end
            continue
        if inside_substitution and char == ")":
            if depth == 0:
                return "".join(kept), index + 1
            depth -= 1
        elif char == "(":
            depth += 1
        kept.append(char)
        index += 1
    return "".join(kept), index


def _quoted(command: str, start: int) -> tuple[str, int]:
    """Napis w cudzysłowie od ``start`` i indeks za nim; z napisu ze spacją (proza) zostają tylko ``$(…)`` w ``"…"``."""

    if command[start] == "'":
        close = command.find("'", start + 1)
        end, kept = (len(command) if close < 0 else close + 1), "''"
    else:
        parts, index = ['"'], start + 1
        while index < len(command):
            char = command[index]
            if char == "\\":
                index += 2
            elif char == '"':
                break
            elif command.startswith("$(", index):
                substitution, index = _code(command, index + 2, inside_substitution=True)
                parts.append(f" $({substitution}) ")
            else:
                index += 1
        end, kept = index + 1, "".join(parts) + '"'
    literal = command[start:end]
    return (kept if WHITESPACE.search(literal) else QUOTED_SEPARATOR.sub("_", literal)), end


class _ShellScripts:
    """Napisy w cudzysłowach jednego polecenia po kolei: który z nich to skrypt ``-c`` powłoki.

    Każdy znak poza cudzysłowami czyta raz, więc czas zostaje liniowy przy dowolnie wielu słowach przed ``-c``.
    """

    def __init__(self, command: str, start: int) -> None:
        self.command, self.read_to = command, start
        self.shell = False
        # Otwarte ``${`` polecenia, w którym stoi skaner; ``$(``, ``(`` i lewy `` ` `` odkładają je razem ze słowem
        # powłoki do ``outer``, a ich zamknięcie je przywraca.
        self.parameters = 0
        self.outer: list[tuple[str, bool, int]] = []

    def is_script(self, quote: int, end: int) -> bool:
        """Czy napis od ``quote`` do ``end`` stoi za ``-c`` w poleceniu prostym ze słowem powłoki."""

        for part in COMMAND_PART.finditer(self.command, self.read_to, quote):
            kind = part.lastgroup
            if part.group() == "\n":
                self.parameters = 0
            if kind == "shell":
                self.shell = True
            elif kind == "parameter":
                self.parameters += 1
            elif kind == "brace":
                self.parameters = max(self.parameters - 1, 0)
            elif self.parameters and kind in ("end", "open", "close"):
                continue
            elif kind == "end":
                self.shell = False
            elif kind in ("open", "substitution") or (
                kind == "tick" and not (self.outer and self.outer[-1][0] == "`")
            ):
                self.outer.append((part.group(), self.shell, self.parameters))
                self.shell, self.parameters = False, 0
            elif kind in ("close", "tick"):
                self.shell, self.parameters = self.outer.pop()[1:] if self.outer else (False, 0)
        words = self.command[self.read_to : quote].split()
        option = words[-1] if words else ""
        script = self.shell and "c" in option and SCRIPT_OPTION.fullmatch(option) is not None
        self.read_to = end
        # Nazwa powłoki w cudzysłowie (``"$SHELL" -c``) też jest słowem powłoki.
        if SHELL_NAME.fullmatch(self.command[quote + 1 : end - 1].rsplit("/", 1)[-1]):
            self.shell = True
        return script


class _Matches:
    """Początki dopasowań wzorca w poleceniu, rosnąco.

    Pytanie, czy jedno z nich zaczyna się w pętli, kosztuje bisekcję, a nie przeszukanie ciała pętli: ciała pętli
    zagnieżdżonych albo niezamkniętych razem rosną z kwadratem długości polecenia. Koniec dopasowania się nie liczy,
    bo ``done`` stoi za ``;``, ``&``, nową linią albo ``do``, a przez nie przechodzi tylko ``gh api … do done adres``.
    """

    def __init__(self, starts: Iterable[int]) -> None:
        self.starts = list(starts)

    def inside(self, start: int, end: int) -> bool:
        index = bisect_left(self.starts, start)
        return index < len(self.starts) and self.starts[index] < end


def _found(pattern: re.Pattern[str], command: str) -> _Matches:
    return _Matches(match.start() for match in pattern.finditer(command))


def _in_one_command(command: str, head: re.Pattern[str], tail: re.Pattern[str]) -> _Matches:
    """Każde ``head``, za którym w tym samym poleceniu prostym stoi ``tail``."""

    tail_starts = [match.start() for match in tail.finditer(command)]
    command_ends = [match.start() for match in SIMPLE_COMMAND_END.finditer(command)]
    return _Matches(
        match.start()
        for match in head.finditer(command)
        if _first_from(tail_starts, match.end(), len(command)) < _first_from(command_ends, match.end(), len(command))
    )


def _loop_bodies(command: str) -> Iterator[tuple[int, int]]:
    """Początek i koniec każdej pętli na pierwszym planie od słowa ``until``/``while``/``for`` do jej ``done``
    (albo do końca polecenia)."""

    loops: list[list[int]] = []
    unclosed: list[int] = []
    for word in LOOP_WORD.finditer(command):
        if not word.group(2):
            unclosed.append(len(loops))
            loops.append([word.start(1), len(command)])
        elif unclosed:
            loops[unclosed.pop()][1] = word.end()
    positions, in_background = _list_parts(command)
    for start, end in loops:
        if not in_background[bisect_left(positions, end)]:
            yield start, end


def _list_parts(command: str) -> tuple[list[int], list[bool]]:
    """Pozycje nawiasów grup, ``;``, nowych linii i ``&`` tła, a dla każdej: czy lista, która biegnie od niej
    dalej na jej poziomie, idzie w tło; na końcu polecenia ``False``.

    Liczone raz od końca: szukanie od każdej pętli osobno kosztuje O(pętle × długość polecenia).
    """

    parts = list(LIST_PART.finditer(command))
    closing = [len(parts)] * len(parts)
    enclosing: list[Optional[int]] = [None] * len(parts)
    opened: list[int] = []
    for index, part in enumerate(parts):
        if part.lastgroup == "open":
            opened.append(index)
        elif part.lastgroup == "close" and opened:
            closing[opened.pop()] = index
        elif part.lastgroup == "end" and opened:
            enclosing[index] = opened[-1]
    in_background = [False] * (len(parts) + 1)
    for index in reversed(range(len(parts))):
        kind = parts[index].lastgroup
        if kind == "background":
            in_background[index] = True
        elif kind == "open":
            in_background[index] = in_background[closing[index]]
        elif kind == "close":
            in_background[index] = in_background[index + 1]
        else:
            # Lista kończy się na `;`, ale grupa, w której stoi, biegnie dalej: `{ pętla; } &` idzie w tło cała.
            group = enclosing[index]
            in_background[index] = group is not None and in_background[closing[group]]
    return [part.start() for part in parts], in_background


def _first_from(positions: list[int], start: int, default: int) -> int:
    index = bisect_left(positions, start)
    return positions[index] if index < len(positions) else default


def _words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:  # cudzysłów przecięty granicą polecenia prostego (``"$r $(gh …)"``)
        return command.split()


def _reruns(shell: str) -> bool:
    """Czy któreś polecenie proste ponawia run GitHub Actions przez ``gh`` (``gh run rerun`` albo ``gh api`` z adresem
    ponowienia); słowa za każdym ``gh`` czyta do następnego ``gh``, więc czas zostaje liniowy."""

    for command in SIMPLE_COMMANDS.split(shell.replace("\\\n", " ")):
        calls: list[list[str]] = []
        value = False
        for word in _words(command):
            if word.rsplit("/", 1)[-1] in GH_NAMES:
                calls.append([])
            elif value:
                value = False
            elif word in GH_VALUE_OPTIONS:
                value = True
            elif calls and not word.startswith("-"):
                calls[-1].append(word)
        for positional in calls:
            if positional[:1] == ["api"] and any(ADRES_PONOWIENIA.search(argument) for argument in positional[1:]):
                return True
            if any(positional[index : index + 2] == ["run", "rerun"] for index in range(len(positional))):
                return True
    return False


def judge(command: str, in_background: bool) -> Optional[Refusal]:
    try:
        shell, _ = _code(_without_heredocs(command))
    except RecursionError:  # setki zagnieżdżonych "$(…)": polecenia nie da się odczytać, więc przechodzi
        return None
    if _reruns(shell):
        return RERUN
    if in_background:
        return None
    if RUN_WATCH.search(shell) or _in_one_command(shell, CHECKS, WATCH_OPTION).starts:
        return WATCHING
    sleeps, stops, pgreps = _found(SLEEP, shell), _found(STOPS, shell), _found(PGREP, shell)
    queries, api_queries = _found(ASKS_CI, shell), _in_one_command(shell, GH_API, CI_ADDRESS)
    for start, end in _loop_bodies(shell):
        if not sleeps.inside(start, end):
            continue
        over_list = OVER_LIST.match(shell, start, end)
        if over_list and not (FOR_ARITHMETIC.match(shell, start, end) or stops.inside(start, end)):
            continue
        if queries.inside(start, end) or api_queries.inside(start, end):
            return CI_LOOP
        if pgreps.inside(start, end):
            return PGREP_LOOP
    return None


def main() -> int:
    try:
        tool_input = json.load(sys.stdin)["tool_input"]
        command = tool_input["command"]
        in_background = tool_input.get("run_in_background") is True
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0
    if not isinstance(command, str):
        return 0
    refusal = judge(command, in_background)
    if refusal is None:
        return 0
    print(refusal.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
