#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca blokujące czekanie na CI i zadanie w tle, pętle ``pgrep -f`` i gołe ponowienie runu.

Agent na pierwszym planie, który pętli ``until/while/for … sleep`` na ``gh pr checks``, stoi do limitu 600 s
Basha, choć CI i tak powiadamia: wątek główny przez ``watch_pull_request`` T3, a zadanie w tle przez powiadomienie,
które budzi sesję po jego końcu (``tools/hooks/praca_w_tle.py``). Przez czas pętli wątek nie reaguje też na
powiadomienia dzieci. Pętla ``until ! pgrep -f X`` nigdy się nie kończy, bo ``pgrep -f`` znajduje powłokę, której
linia polecenia zawiera tę samą pętlę, a więc i ``X`` (z tego samego powodu ``until pgrep -f X`` kończy się od razu).

Odrzuca (kod 2, przyczyna na stderr trafia do agenta) tylko polecenie na pierwszym planie, a odmowa podaje jedyną
drogę dla przypadku: PR (``INSTEAD``: wątek główny ``watch_pull_request`` i koniec tury, dziecko kończy na URL PR i
pełnym SHA), ``main`` po merge'u (``INSTEAD``: nie czekać) i zadanie w tle (``WAIT_FOR_TASK``: ``t3_background_wait``
i koniec tury; ``tools/hooks/praca_w_tle.py`` podaje ten sam tekst, a test pilnuje jego równości). Odrzuca:

- pętlę z ``sleep``, której ciało pyta o CI (``gh pr checks``, ``gh pr view``, ``gh run view``/``list``, ``gh api``
  o check-runs, actions/runs, stan zadania ``actions/jobs/<id>`` albo status commitu) albo woła ``pgrep -f``, oraz
  ``gh pr checks --watch`` i ``gh run watch``;
- pętlę z ``sleep``, w której stoi plik wyjścia zadania w tle (``tasks/<id>.output``) wprost albo przez zmienną, której
  polecenie go przypisuje (``F=…/tasks/b1.output; until grep -q KONIEC $F; do sleep 15; done``);
- pętlę skryptu Pythona (``python3 -c '…'`` i heredoc, który Python czyta ze stdin), w której ``sleep`` stoi w jej
  ciele (także w pętli wewnętrznej), a w obrocie stoi wywołanie z tymi samymi argumentami w każdym obrocie: proces z
  ``gh`` o CI albo z ``pgrep -f`` (``subprocess``, ``os.system``, ``os.popen`` albo funkcja skryptu, która je woła) albo
  odczyt pliku wyjścia zadania (ścieżka w skrypcie, w zmiennej powłoki albo w ``sys.argv[N]``, gdy N-ty argument
  skryptu to ten plik). Argument zmienia się między obrotami, gdy pętla zmienia nazwę, od której zależy: wiąże ją
  (cel ``for``, ``+=``, wynik wywołania) albo zmienia jej wartość w miejscu (zapis albo ``del`` elementu lub
  atrybutu, ``pop``, wywołanie dla skutku z nią jako odbiorcą albo argumentem, poza procesem, snem i ``print``), więc
  partia zapytań po liście, stronach albo kolejce, także z ``break`` przy limicie API, przechodzi. Skrypt czyta
  ``ast``, od najkrótszego, a ocena wszystkich skryptów polecenia ma jeden limit długości i jeden budżet węzłów.

Pętla ``for`` i ``while read`` czeka tylko z ``break``, ``exit``, ``return`` albo licznikiem prób od 0 albo 1
(``$(seq N)``, ``$(seq 1 N)``, ``{1..N}``, ``for ((``), bo bez nich to partia zapytań z ``sleep`` jako limitem API, a pętla puszczona ``&`` nie czeka: sama, w liście z ``|``,
``&&`` albo ``||``, w grupie ``( … )`` albo ``{ …; }``.
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
hook pomija jako polecenia powłoki; zostawia z nich ``$(…)`` i ciało ``-c`` powłoki, ``su``, ``runuser``,
``flock`` albo ``script`` z dowolnymi słowami przed ``-c`` (``bash -euo pipefail -c '…'``, ``bash -lc``,
``su -l -s /bin/sh root -c``). Program Pythona to słowo polecenia prostego, którego nazwa za ostatnim ``/`` to
``python``, ``python3``, ``python3.12`` albo ``py``, a jego skrypt to napis za ``-c`` (także ``-uc``) po samych opcjach
interpretera albo heredoc, gdy przed ``<<`` stoją same opcje albo ``-``. Cudzysłów w komentarzu (``#`` na początku
słowa) nie otwiera napisu, a tekst komentarza zostaje w poleceniu. Postacie, które przechodzą, i znane luki stoją
jako przypadki ``PASSING``, ``PYTHON_PASSING`` i ``ZNANE_LUKI`` w ``tests/test_czekanie.py``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``ruff.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

import ast
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import json
import re
import shlex
import sys
from typing import Optional
import warnings

_GH = r"\bgh(?:-axi)?\s+"
ASKS_CI = re.compile(_GH + r"(?:pr\s+(?:checks|view)|run\s+(?:view|list|watch))")
# `gh api` pyta o CI, gdy w tym samym poleceniu prostym (do `;`, `&`, `|` albo nowej linii) stoi adres CI. Pary szuka
# `_in_one_command`, a nie wzorzec `api\b[^;&|\n]*adres`, bo ten od każdego `gh api` czyta do końca polecenia.
GH_API = re.compile(_GH + r"api\b")
CI_ADDRESS = re.compile(r"check-runs|actions/runs|actions/jobs/[^/\s'\"]+(?![^\s'\"])|/status\b")
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
TASK_OUTPUT = re.compile(r"\btasks/[^/\s]*\.output\b")
ASSIGNMENT = re.compile(r"(?<![\w$])([A-Za-z_]\w*)=(\S*)")
REFERENCE = re.compile(r"\$[{_]?([A-Za-z_]\w*)")

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
HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)(\w+)\2")
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
_PYTHON = r"python[\d.]*|py"
PYTHON_NAME = re.compile(_PYTHON)
COMMAND_PART = re.compile(
    rf"(?P<shell>(?<![^\s/;&|(`])(?:\\(?=[a-z]))?(?:{_SHELLS})(?![^\s;&|()`]))"
    rf"|(?P<python>(?<![^\s/;&|(`])(?:\\(?=[a-z]))?(?:{_PYTHON})(?![^\s;&|()`]))"
    r"|\\[\s\S]|(?P<parameter>\$\{)|(?P<brace>\})|(?P<substitution>\$\()"
    r"|(?P<end>[;\n]|(?<![<>])&(?!>)|(?<!>)\|)|(?P<open>\()|(?P<close>\))|(?P<tick>`)"
)
SCRIPT_OPTION = re.compile(r"-[a-zA-Z]+")
PYTHON_SCRIPT_OPTION = re.compile(r"-[a-zA-Z]*c")
PYTHON_CODE_OPTION = re.compile(r"-[a-zA-Z]*[cm]")
PYTHON_VALUE_OPTIONS = frozenset({"-X", "-W"})
REDIRECTION = re.compile(r"\d*[<>&]")
REDIRECTION_ALONE = re.compile(r"\d*(?:<<?|>>?|&>>?|>&|<&)-?")
PYTHON_COMMAND_END = re.compile(r"[;\n(){}`]|\|\|?|&&|(?<![<>])&(?!>)")
COMMENT_AFTER = frozenset(" \t\n;&|(")
PYTHON_SCRIPT = re.compile("\x00(\\d+)\x00")
DOUBLE_QUOTED_ESCAPE = re.compile(r'\\([$`"\\])')
RUNS_PROCESS = frozenset(
    {
        "run",
        "call",
        "check_call",
        "check_output",
        "Popen",
        "getoutput",
        "getstatusoutput",
        "system",
        "popen",
        "create_subprocess_exec",
        "create_subprocess_shell",
    }
)
KEEPS_VALUE = frozenset(
    {"str", "int", "float", "repr", "bool", "format", "tuple", "list", "split", "join", "strip", "replace", "lower", "upper"}
)
TAKES_FROM = frozenset({"pop", "popleft", "popitem"})
LEAVES_VALUES = RUNS_PROCESS | {"sleep", "print"}
PYTHON_SOURCE_LIMIT = 200_000
PYTHON_NODES_LIMIT = 1_000_000

INSTEAD = (
    "Na CI nie czekaj w Bashu. PR: wątek główny wywołuje watch_pull_request z URL PR i kończy turę, a T3 budzi go po "
    "końcu CI; dziecko delegate_task kończy zadanie na URL PR i pełnym SHA HEAD, a CI sprawdza i PR scala rodzic "
    "(tools/scal_pr.py). main po merge'u: nie czekaj wcale, bo czerwony main zakłada issue czerwony-main sam "
    "(tools/ci/zgloszenia_ci.py)."
)
WAIT_FOR_TASK = (
    "Na swoje zadanie w tle czekaj tylko tak: wywołaj t3_background_wait z taskIds (lista ID, nie taskId) i zakończ "
    "turę bez sleep i bez pętli; T3 trzyma wątek w pracy, a Claude Code budzi go powiadomieniem po końcu zadania. "
    "Zadanie, na które nie czekasz, zatrzymaj TaskStop z jego ID."
)


@dataclass(frozen=True)
class Refusal:
    reason: str


CI_LOOP = Refusal(f"Odmowa: pętla z sleep na pierwszym planie czeka na CI. {INSTEAD}")
WATCHING = Refusal(f"Odmowa: gh pr checks --watch i gh run watch blokują na pierwszym planie. {INSTEAD}")
TASK_OUTPUT_LOOP = Refusal(
    "Odmowa: pętla z sleep na pliku wyjścia zadania w tle (tasks/*.output) czeka na pierwszym planie na koniec zadania. "
    f"{WAIT_FOR_TASK} Plik wyjścia przeczytaj po wybudzeniu. Na gotowość serwera, który ma biec dalej, czekaj pętlą "
    "na jego porcie (curl) bez pliku wyjścia w pętli, a plik przeczytaj po niej."
)
RERUN = Refusal(
    "Odmowa: o ponowieniu runu CI decyduje tools/ponow_ci.py: .venv/bin/python tools/ponow_ci.py N (najnowszy run CI "
    "na HEAD PR N) albo --run ID (Windows: py -3 tools/ponow_ci.py). Czeka na koniec runu, odróżnia awarię runnera od "
    "defektu po logach padniętych zadań, przy wspólnej awarii ponawia tylko kanarka, a przy defekcie podaje polecenie "
    "tools/ci_lokalnie.py --tylko <zadanie>."
)
PGREP_LOOP = Refusal(
    "Odmowa: pętla z sleep na pgrep -f nie widzi procesu, bo pgrep -f znajduje własną powłokę tej pętli: "
    "until ! pgrep -f X i while pgrep -f X nie kończą się nigdy, a until pgrep -f X kończy się od razu. "
    f"Własny proces uruchom Bashem z run_in_background: true. {WAIT_FOR_TASK} "
    "Na proces ze znanym PID sprawdzaj kill -0 $PID, nie pgrep."
)


def _without_heredocs(command: str) -> tuple[str, list[str]]:
    kept: list[str] = []
    python: list[list[str]] = []
    delimiter: Optional[str] = None
    body: Optional[list[str]] = None
    without_tabs = False
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            elif body is not None:
                body.append(line.lstrip("\t") if without_tabs else line)
            continue
        opened = HEREDOC.search(line)
        if opened is None:
            kept.append(line)
            continue
        delimiter, body, without_tabs = opened.group(3), None, opened.group(1) == "-"
        if _python_reads_heredoc(line[: opened.start()]):
            body = []
            python.append(body)
            kept.append(f"{line[: opened.end()]}\x00{len(python) - 1}\x00{line[opened.end() :]}")
        else:
            kept.append(line)
    return "\n".join(kept), ["\n".join(lines) for lines in python]


def _python_reads_heredoc(before: str) -> bool:
    words = _without_redirections(PYTHON_COMMAND_END.split(before)[-1].split())
    programs = [index for index, word in enumerate(words) if _is_python(word)]
    if not programs:
        return False
    arguments = words[programs[-1] + 1 :]
    end = _python_options_end(arguments)
    return end == len(arguments) or arguments[end] == "-"


def _is_python(word: str) -> bool:
    return PYTHON_NAME.fullmatch(word.strip("'\"").rsplit("/", 1)[-1]) is not None


def _without_redirections(words: list[str]) -> list[str]:
    kept: list[str] = []
    target = False
    for word in words:
        if target:
            target = False
        elif REDIRECTION_ALONE.fullmatch(word):
            target = True
        elif not REDIRECTION.match(word):
            kept.append(word)
    return kept


def _script_arguments(command: str, script: str, heredoc: bool) -> list[str]:
    words = command.split()
    at = next(index for index, word in enumerate(words) if script in word)
    if not heredoc:
        return _without_redirections(words[at + 1 :])
    before = _without_redirections(words[:at])
    programs = [index for index, word in enumerate(before) if _is_python(word)]
    options = before[programs[-1] + 1 :] if programs else []
    end = _python_options_end(options)
    return options[end + 1 :] + _without_redirections(words[at + 1 :]) if end < len(options) else []


def _python_options_end(words: list[str]) -> int:
    value = False
    for index, word in enumerate(words):
        if value:
            value = False
        elif word == "-" or not word.startswith("-") or PYTHON_CODE_OPTION.fullmatch(word):
            return index
        else:
            value = word in PYTHON_VALUE_OPTIONS
    return len(words)


def _python_script_option(words: list[str]) -> bool:
    return len(words) > 0 and _python_options_end(words) == len(words) - 1 and bool(PYTHON_SCRIPT_OPTION.fullmatch(words[-1]))


def _script_text(command: str, quote: int, end: int) -> str:
    closed = quote < end - 1 < len(command) and command[end - 1] == command[quote]
    text = command[quote + 1 : end - 1 if closed else len(command)]
    if command[quote] == "'":
        return text
    return DOUBLE_QUOTED_ESCAPE.sub(r"\1", text)


def _comment_starts(command: str, index: int, start: int) -> bool:
    return command[index] == "#" and (index == start or command[index - 1] in COMMENT_AFTER)


def _code(
    command: str, python: list[str], start: int = 0, inside_substitution: bool = False
) -> tuple[str, int]:
    """Polecenie bez tekstu w cudzysłowach, ale z ``$(…)`` w nich i z ciałem ``bash -c '…'``.

    Proza w argumentach (opis commitu, wiersz logu, wzorzec ``sed``) nie jest poleceniem, nawet gdy cytuje pętlę.
    Skrypt ``-c`` Pythona dopisuje do ``python``, a w poleceniu zostawia w jego miejscu znacznik ``\\x00<numer>\\x00``.
    Zwraca też indeks za ``)``, która zamyka ``$(`` przy ``inside_substitution``.
    """

    kept: list[str] = []
    scripts = _ShellScripts(command, start)
    # Napis przyklejony do skryptu ``-c`` to jego dalszy ciąg: w ``bash -c '… perl -e '\''select(…)'\''; done'``
    # ``done`` stoi w trzecim napisie.
    depth, index, script_end, in_python = 0, start, -1, False
    while index < len(command):
        char = command[index]
        if char == "\\":
            if index == script_end and in_python:
                python[-1] += command[index + 1 : index + 2]
            else:
                kept.append(command[index : index + 2])
            if index == script_end:
                script_end += 2
            index += 2
            continue
        if _comment_starts(command, index, start):
            line_end = command.find("\n", index)
            line_end = len(command) if line_end < 0 else line_end
            kept.append(command[index:line_end])
            index = line_end
            continue
        if char in "'\"":
            literal, end = _quoted(command, index, python)
            script = scripts.script(index, end)
            if index == script_end and in_python:
                python[-1] += _script_text(command, index, end)
                script_end = end
            elif index == script_end:
                kept.append(command[index + 1 : end])
                script_end = end
            elif script == "python":
                kept.append(f"\x00{len(python)}\x00")
                python.append(_script_text(command, index, end))
                script_end, in_python = end, True
            elif script == "shell":
                kept.append(";" + command[index + 1 : end])
                script_end, in_python = end, False
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


def _quoted(command: str, start: int, python: list[str]) -> tuple[str, int]:
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
                substitution, index = _code(command, python, index + 2, inside_substitution=True)
                parts.append(f" $({substitution}) ")
            else:
                index += 1
        end, kept = index + 1, "".join(parts) + '"'
    literal = command[start:end]
    return (kept if WHITESPACE.search(literal) else QUOTED_SEPARATOR.sub("_", literal)), end


class _ShellScripts:
    """Napisy w cudzysłowach jednego polecenia po kolei: który z nich to skrypt ``-c`` powłoki albo Pythona.

    Każdy znak poza cudzysłowami czyta raz, więc czas zostaje liniowy przy dowolnie wielu słowach przed ``-c``.
    """

    def __init__(self, command: str, start: int) -> None:
        self.command, self.read_to = command, start
        self.program: Optional[str] = None
        self.python_from = -1
        # Otwarte ``${`` polecenia, w którym stoi skaner; ``$(``, ``(`` i lewy `` ` `` odkładają je razem ze słowem
        # powłoki do ``outer``, a ich zamknięcie je przywraca.
        self.parameters = 0
        self.outer: list[tuple[str, Optional[str], int, int]] = []

    def script(self, quote: int, end: int) -> Optional[str]:
        for part in COMMAND_PART.finditer(self.command, self.read_to, quote):
            kind = part.lastgroup
            if part.group() == "\n":
                self.parameters = 0
            if kind == "shell":
                self.program = "shell"
            elif kind == "python":
                self.program, self.python_from = "python", part.end()
            elif kind == "parameter":
                self.parameters += 1
            elif kind == "brace":
                self.parameters = max(self.parameters - 1, 0)
            elif self.parameters and kind in ("end", "open", "close"):
                continue
            elif kind == "end":
                self.program = None
            elif kind in ("open", "substitution") or (
                kind == "tick" and not (self.outer and self.outer[-1][0] == "`")
            ):
                self.outer.append((part.group(), self.program, self.python_from, self.parameters))
                self.program, self.parameters = None, 0
            elif kind in ("close", "tick"):
                _, self.program, self.python_from, self.parameters = self.outer.pop() if self.outer else ("", None, -1, 0)
        words = self.command[self.read_to : quote].split()
        option = words[-1] if words else ""
        found: Optional[str] = None
        if self.program == "shell" and "c" in option and SCRIPT_OPTION.fullmatch(option) is not None:
            found = "shell"
        elif self.program == "python" and self.python_from >= self.read_to:
            found = "python" if _python_script_option(self.command[self.python_from : quote].split()) else None
        self.read_to = end
        name = self.command[quote + 1 : end - 1].rsplit("/", 1)[-1]
        # Nazwa powłoki w cudzysłowie (``"$SHELL" -c``) też jest słowem powłoki.
        if SHELL_NAME.fullmatch(name):
            self.program = "shell"
        elif PYTHON_NAME.fullmatch(name):
            self.program, self.python_from = "python", end
        return found


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


def _loop_bodies(command: str, parts: tuple[list[int], list[bool]]) -> Iterator[tuple[int, int]]:
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
    positions, in_background = parts
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


def _task_files(text: str, variables: frozenset[str]) -> list[int]:
    """Początki plików wyjścia zadania w ``text``: wprost i przez odwołanie do zmiennej z ``variables``.

    Zmienne to te, którym polecenie przypisuje plik (``F=…/tasks/b1.output``, ``ASSIGNMENT``). Odwołanie ``"${F}"``
    jest w kodzie po ``_code`` napisem ``"$_F_"``, bo napis bez spacji ma nawiasy zamienione na podkreślenia, stąd
    ``rstrip("_")``.
    """

    named = [found.start() for found in TASK_OUTPUT.finditer(text)]
    referred = [found.start() for found in REFERENCE.finditer(text) if found.group(1).rstrip("_") in variables]
    return sorted(named + referred)


class _ScriptTooLong(Exception):
    pass


@dataclass
class _Visits:
    left: int = PYTHON_NODES_LIMIT

    def step(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise _ScriptTooLong


@dataclass(frozen=True)
class _Enclosing:
    loop: ast.AST
    outer: Optional[_Enclosing]


def _called(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _changes_value(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _called(node) not in KEEPS_VALUE


def _names(target: ast.AST) -> list[ast.Name]:
    return [node for node in ast.walk(target) if isinstance(node, ast.Name)]


def _root(node: ast.AST) -> Optional[str]:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _reads_argument(node: ast.AST, arguments: frozenset[int]) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "argv"
        and _root(node.value) == "sys"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in arguments
    )


class _PythonScript:
    def __init__(self, tree: ast.Module, task_arguments: frozenset[int], variables: frozenset[str], visits: _Visits) -> None:
        self.task_arguments, self.variables, self.visits = task_arguments, variables, visits
        self.functions: dict[str, ast.FunctionDef] = {}
        self.values: dict[str, list[ast.expr]] = defaultdict(list)
        self.modules: set[str] = set()
        self.command_texts: dict[str, str] = {}
        self.function_texts: dict[str, str] = {}
        self.function_sleeps: dict[str, bool] = {}
        self.task_names: dict[str, bool] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.functions[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.values[target.id].append(node.value)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.modules.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def nodes(self, *roots: ast.AST) -> Iterator[ast.AST]:
        stack = list(reversed(roots))
        while stack:
            node = stack.pop()
            self.visits.step()
            yield node
            stack.extend(reversed(list(ast.iter_child_nodes(node))))

    def sleeping_loops(self, tree: ast.Module) -> list[ast.AST]:
        loops: dict[int, ast.AST] = {}
        stack: list[tuple[ast.AST, Optional[_Enclosing]]] = [(tree, None)]
        while stack:
            node, enclosing = stack.pop()
            self.visits.step()
            if enclosing is not None and isinstance(node, ast.Call) and self.sleeps(node):
                marked: Optional[_Enclosing] = enclosing
                while marked is not None and id(marked.loop) not in loops:
                    loops[id(marked.loop)] = marked.loop
                    marked = marked.outer
            for field, value in ast.iter_fields(node):
                inner = enclosing
                if (isinstance(node, ast.While) and field in ("test", "body")) or (isinstance(node, ast.For) and field == "body"):
                    inner = _Enclosing(node, enclosing)
                children = value if isinstance(value, list) else [value]
                stack.extend((child, inner) for child in children if isinstance(child, ast.AST))
        return list(loops.values())

    def sleeps(self, call: ast.Call) -> bool:
        if _called(call) == "sleep":
            return True
        if isinstance(call.func, ast.Name) and call.func.id in self.functions:
            return self.function_sleep(call.func.id)
        return _called(call) in RUNS_PROCESS and SLEEP.search(self.command_text(call)) is not None

    def function_sleep(self, name: str) -> bool:
        if name not in self.function_sleeps:
            self.function_sleeps[name] = False
            calls = [node for node in self.nodes(self.functions[name]) if isinstance(node, ast.Call)]
            self.function_sleeps[name] = any(self.sleeps(call) for call in calls)
        return self.function_sleeps[name]

    def command_text(self, node: ast.AST) -> str:
        words: list[str] = []
        for child in self.nodes(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                words.append(child.value)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                words.append(self.name_text(child.id))
        return " ".join(word for word in words if word)

    def name_text(self, name: str) -> str:
        if name not in self.command_texts:
            self.command_texts[name] = ""
            data = [value for value in self.values.get(name, ()) if not any(map(_changes_value, ast.walk(value)))]
            self.command_texts[name] = " ".join(self.command_text(value) for value in data)
        return self.command_texts[name]

    def query_text(self, call: ast.Call) -> str:
        if isinstance(call.func, ast.Name) and call.func.id in self.functions:
            return f"{self.function_text(call.func.id)} {self.command_text(call)}"
        return self.command_text(call) if _called(call) in RUNS_PROCESS else ""

    def function_text(self, name: str) -> str:
        if name not in self.function_texts:
            self.function_texts[name] = ""
            calls = [node for node in self.nodes(self.functions[name]) if isinstance(node, ast.Call)]
            self.function_texts[name] = " ".join(self.query_text(call) for call in calls)
        return self.function_texts[name]

    def reads_task_file(self, node: ast.AST) -> bool:
        for child in self.nodes(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if TASK_OUTPUT.search(child.value) or any(
                    found.group(1) in self.variables for found in REFERENCE.finditer(child.value)
                ):
                    return True
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and self.task_name(child.id):
                return True
            elif _reads_argument(child, self.task_arguments):
                return True
        return False

    def task_name(self, name: str) -> bool:
        if name not in self.task_names:
            self.task_names[name] = False
            self.task_names[name] = any(self.reads_task_file(value) for value in self.values.get(name, ()))
        return self.task_names[name]

    def changed_in_place(self, region: list[ast.AST]) -> set[str]:
        changed: set[Optional[str]] = set()
        for node in region:
            if isinstance(node, (ast.Subscript, ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Del):
                changed.add(_root(node))
            elif isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, ast.Store):
                changed.add(_root(node))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in TAKES_FROM:
                changed.add(_root(node.func.value))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _called(node.value) not in LEAVES_VALUES:
                call = node.value
                receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
                changed.update(_root(part) for part in [receiver, *call.args] if part is not None)
        return {name for name in changed if name is not None and name not in self.modules}

    def varying(self, loop: ast.AST, region: list[ast.AST]) -> set[str]:
        varying = {name.id for name in _names(loop.target)} if isinstance(loop, ast.For) else set()
        varying |= self.changed_in_place(region)
        bindings: list[tuple[set[str], ast.AST]] = []
        valued: set[int] = set()
        for node in region:
            if isinstance(node, ast.Assign):
                targets = [name for target in node.targets for name in _names(target)]
                bindings.append(({name.id for name in targets}, node.value))
            elif isinstance(node, (ast.For, ast.comprehension)):
                targets = _names(node.target)
                bindings.append(({name.id for name in targets}, node.iter))
            else:
                continue
            valued.update(id(name) for name in targets)
        stores = (node for node in region if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
        varying |= {node.id for node in stores if id(node) not in valued}
        dependents: dict[str, list[int]] = defaultdict(list)
        for index, (names, value) in enumerate(bindings):
            reads = set()
            for node in self.nodes(value):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    reads.add(node.id)
                elif _changes_value(node):
                    varying |= names
            if reads & names:
                varying |= names
            for name in reads:
                dependents[name].append(index)
        queue = list(varying)
        while queue:
            for index in dependents.get(queue.pop(), ()):
                new = bindings[index][0] - varying
                varying |= new
                queue.extend(new)
        return varying

    def waits(self, loop: ast.AST) -> set[Refusal]:
        roots = [loop.test, *loop.body] if isinstance(loop, ast.While) else list(getattr(loop, "body", []))
        region = list(self.nodes(*roots))
        varying = self.varying(loop, region)
        found: set[Refusal] = set()
        for call in region:
            if not isinstance(call, ast.Call):
                continue
            if any(isinstance(node, ast.Name) and node.id in varying for node in self.nodes(call)):
                continue
            if self.reads_task_file(call):
                found.add(TASK_OUTPUT_LOOP)
            query = self.query_text(call)
            if ASKS_CI.search(query) or _in_one_command(query, GH_API, CI_ADDRESS).starts:
                found.add(CI_LOOP)
            if PGREP.search(query):
                found.add(PGREP_LOOP)
        return found


def _python_waits(source: str, task_arguments: frozenset[int], variables: frozenset[str], visits: _Visits) -> set[Refusal]:
    found: set[Refusal] = set()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
        script = _PythonScript(tree, task_arguments, variables, visits)
        for loop in script.sleeping_loops(tree):
            found |= script.waits(loop)
    except (SyntaxError, RecursionError, _ScriptTooLong):
        pass
    return found


def _python_refusal(
    shell: str, python: list[str], heredocs: int, parts: tuple[list[int], list[bool]], variables: frozenset[str]
) -> Optional[Refusal]:
    positions, in_background = parts
    separators = list(PYTHON_COMMAND_END.finditer(shell))
    command_ends = [found.start() for found in separators]
    scripts: list[tuple[int, int, str, int]] = []
    for marker in PYTHON_SCRIPT.finditer(shell):
        number = int(marker.group(1))
        if not in_background[bisect_left(positions, marker.start())] and "sleep" in python[number]:
            scripts.append((len(python[number]), marker.start(), marker.group(), number))
    found: set[Refusal] = set()
    unread, visits = PYTHON_SOURCE_LIMIT, _Visits()
    for length, at, marker_text, number in sorted(scripts):
        if length > unread:
            break
        unread -= length
        index = bisect_left(command_ends, at)
        start = separators[index - 1].end() if index else 0
        end = command_ends[index] if index < len(command_ends) else len(shell)
        arguments = _script_arguments(shell[start:end], marker_text, number < heredocs)
        tasks = frozenset(place + 1 for place, word in enumerate(arguments) if _task_files(word, variables))
        found |= _python_waits(python[number], tasks, variables, visits)
    return next((refusal for refusal in (CI_LOOP, PGREP_LOOP, TASK_OUTPUT_LOOP) if refusal in found), None)


def judge(command: str, in_background: bool) -> Optional[Refusal]:
    command = command.replace("\x00", "")
    try:
        kept, python = _without_heredocs(command)
        heredocs = len(python)
        shell, _ = _code(kept, python)
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
    variables = frozenset(found.group(1) for found in ASSIGNMENT.finditer(kept) if TASK_OUTPUT.search(found.group(2)))
    task_files = _Matches(_task_files(shell, variables))
    parts = _list_parts(shell)
    for start, end in _loop_bodies(shell, parts):
        if not sleeps.inside(start, end):
            continue
        over_list = OVER_LIST.match(shell, start, end)
        if over_list and not (FOR_ARITHMETIC.match(shell, start, end) or stops.inside(start, end)):
            continue
        if queries.inside(start, end) or api_queries.inside(start, end):
            return CI_LOOP
        if pgreps.inside(start, end):
            return PGREP_LOOP
        if task_files.inside(start, end):
            return TASK_OUTPUT_LOOP
    return _python_refusal(shell, python, heredocs, parts, variables)


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
