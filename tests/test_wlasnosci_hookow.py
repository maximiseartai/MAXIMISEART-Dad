"""Hooki Claude Code ``tools/hooks/czekanie.py`` i ``tools/hooks/zgoda.py`` jako własności Hypothesis.

Parsery poleceń w hookach padały w przeglądzie na wejściach, których autor nie przewidział: wzorzec ``rg`` ze słowem
pętli dostawał odmowę, ``&>`` było tłem, a wzorzec z zagnieżdżonym kwantyfikatorem liczył się w czasie wykładniczym
(#446); ``$(`` w apostrofach, ``sh -c '…'`` i zamiana cudzysłowów zmieniały werdykt (#496). Autor sprawdzał się na
przykładach z tym samym założeniem co kod, więc fałszywych odmów nie widział.

Tu oczekiwanie bierze się z docstringów hooków: czekanie na CI albo pętla na
``pgrep -f`` na pierwszym planie dostaje odmowę, a reszta przechodzi. To, czym napis jest dla powłoki, rozstrzyga
wyrocznia niezależna od hooka: ``shlex`` (tekst jest jednym argumentem, cudzysłów nie zmienia słów polecenia) i
``bash -n`` (wygenerowane polecenie jest poprawne składniowo). Przykłady są deterministyczne (``derandomize=True``,
bez bazy przykładów) tylko przy tych samych modułach w procesie: Hypothesis losuje też stałe z kodu repozytorium,
który proces już załadował, więc inny zestaw testów (noc mutacji zmian) dostaje inne przykłady. Czas mierzy stosunek
czasu werdyktu długiego polecenia do tylu werdyktów krótkiego, ile razy jest dłuższe, w rundach tuż po sobie, więc nie
zależy od szybkości runnera, a chwilowy tłok na nim trafia obie strony stosunku.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
import importlib.util
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import string
import subprocess
import sys
from types import ModuleType
from unittest import mock

import pytest
from hypothesis import Phase, example, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
CZEKANIE = ROOT / "tools" / "hooks" / "czekanie.py"
ZGODA = ROOT / "tools" / "hooks" / "zgoda.py"

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=150)


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"wlasnosci_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


czekanie = _load(CZEKANIE)
zgoda = _load(ZGODA)
REFUSALS = {"ci": czekanie.CI_LOOP, "pgrep": czekanie.PGREP_LOOP, "watch": czekanie.WATCHING}


@dataclass(frozen=True)
class Case:
    """Polecenie i odmowy, które według docstringu hooka może dostać (pusty zbiór: przechodzi)."""

    text: str
    refusals: frozenset[str]


@dataclass(frozen=True)
class Template:
    """Polecenie z argumentami, które można ująć w cudzysłowy, bo nie są słowem kluczowym ani nazwą polecenia."""

    form: str
    arguments: tuple[str, ...]
    refusals: frozenset[str]

    def text(self, quotes: Sequence[str] = ()) -> str:
        padded = (*quotes, *[""] * len(self.arguments))[: len(self.arguments)]
        return self.form.format(
            *(quote + argument + quote for quote, argument in zip(padded, self.arguments, strict=True))
        )


def _judged(text: str) -> frozenset[str]:
    refusal = czekanie.judge(text, in_background=False)
    return frozenset(name for name, known in REFUSALS.items() if refusal is known) if refusal else frozenset()


def _verdict_matches(case: Case) -> bool:
    judged = _judged(case.text)
    return judged <= case.refusals and bool(judged) == bool(case.refusals)


NUMBERS = st.integers(1, 99999).map(str)
SECONDS = st.integers(1, 120).map(str)
NAMES = st.sampled_from(("bench.py", "mutacje.json", "ci_lokalnie.py", "serve_centrum", "pytest"))
PENDING = st.sampled_from(("pending", "pass", "PENDING"))


@st.composite
def _ci_query(draw: st.DrawFn) -> tuple[str, tuple[str, ...]]:
    """Zapytanie o CI z docstringu: ``gh pr checks``/``view``, ``gh run view``/``list``, ``gh api`` o status commitu."""

    number = draw(NUMBERS)
    form, arguments = draw(
        st.sampled_from(
            (
                ("gh pr checks {}", (number,)),
                ("gh-axi pr checks {}", (number,)),
                ("gh pr view {} --json {}", (number, "state")),
                ("gh run view {} --json {}", (number, "status")),
                ("gh run list --branch {} --json {}", ("main", "status,conclusion")),
                ("gh api {}", (f"repos/o/r/commits/{number}abc/status",)),
                ("gh api {}", (f"repos/o/r/commits/{number}abc/check-runs",)),
                ("gh api {}", (f"repos/o/r/actions/runs/{number}",)),
            )
        )
    )
    return form, arguments


@st.composite
def _sleep(draw: st.DrawFn) -> tuple[str, tuple[str, ...]]:
    seconds = draw(SECONDS)
    return draw(st.sampled_from((("sleep {}", (seconds,)), (f"perl -e 'select(undef,undef,undef,{seconds})'", ()))))


@st.composite
def _waits(draw: st.DrawFn) -> Template:
    """Czekanie na pierwszym planie, które według docstringu dostaje odmowę."""

    sleep, sleep_arguments = draw(_sleep())
    kind = draw(st.sampled_from(("ci", "pgrep", "watch")))
    if kind == "watch":
        number = draw(NUMBERS)
        form, arguments = draw(
            st.sampled_from(
                (
                    ("gh pr checks {} --watch", (number,)),
                    ("timeout {} gh pr checks {} --watch --interval {}", ("600", number, "30")),
                    ("gh run watch {} --exit-status", (number,)),
                )
            )
        )
        return Template(form, arguments, frozenset({kind}))
    if kind == "pgrep":
        condition = draw(
            st.sampled_from(
                ("until ! pgrep -f {} >/dev/null", "while pgrep -f {} >/dev/null", "until ! pgrep -l -f {}")
            )
        )
        condition_arguments: tuple[str, ...] = (draw(NAMES),)
    else:
        query, query_arguments = draw(_ci_query())
        condition, condition_arguments = draw(
            st.sampled_from(
                (
                    (f"until {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                    (f"until ! {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                    (f"while {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                )
            )
        )
    loop = draw(
        st.sampled_from(
            (
                (f"{condition}; do {sleep}; done", (*condition_arguments, *sleep_arguments)),
                (f"{condition}\ndo\n  {sleep}\ndone", (*condition_arguments, *sleep_arguments)),
                # Wcięcie przed słowem pętli i przed ``done`` (pętla w skrypcie wklejonym z edytora).
                (f"cd .\n  {condition}\n  do\n    {sleep}\n  done", (*condition_arguments, *sleep_arguments)),
                # ``done`` jako argument za ``do`` nie kończy pętli (runda 3 #636).
                (
                    f"{condition}; do echo {draw(st.sampled_from(('do done', 'dodone', 'to do done')))}; {sleep}; done",
                    (*condition_arguments, *sleep_arguments),
                ),
            )
        )
    )
    if kind == "ci" and draw(st.booleans()):
        # Licznik prób od 1 z wyjściem z pętli: docstring liczy ``for`` jako czekanie tylko z nimi.
        query, query_arguments = draw(_ci_query())
        counter = draw(st.sampled_from(("$(seq 1 {})", "{{1..{}}}")))
        loop = (
            f"for i in {counter}; do {query} | grep -q {{}} || break; {sleep}; done",
            (draw(SECONDS), *query_arguments, draw(PENDING), *sleep_arguments),
        )
    return Template(loop[0], loop[1], frozenset({kind}))


@st.composite
def _quiet(draw: st.DrawFn) -> Template:
    """Polecenie, które według docstringu przechodzi: zapytanie bez pętli, partia zapytań, czekanie na plik."""

    query, query_arguments = draw(_ci_query())
    sleep, sleep_arguments = draw(_sleep())
    first, second = draw(NUMBERS), draw(NUMBERS)
    form, arguments = draw(
        st.sampled_from(
            (
                (query, query_arguments),
                (f"{query} | grep -c {{}}", (*query_arguments, draw(PENDING))),
                (f"{sleep}; {query}", (*sleep_arguments, *query_arguments)),
                (
                    f"for id in {{}} {{}}; do {sleep}; gh run view $id --json {{}}; done",
                    (first, second, *sleep_arguments, "jobs"),
                ),
                ("for n in {} {}; do gh pr view $n --json {}; done", (first, second, "title")),
                (
                    f"until grep -q {{}} {{}}; do {sleep}; done; tail -5 {{}}",
                    ("DONE", "ci.log", *sleep_arguments, "ci.log"),
                ),
                ("pgrep -fl {}", (draw(NAMES),)),
                ("git status --short", ()),
                # ``sleep``, ``exit``, adres CI i ``--watch`` stoją poza pętlą albo w innym poleceniu prostym.
                (f"until {query}; do gh auth refresh; done; {sleep}", (*query_arguments, *sleep_arguments)),
                (
                    f"for id in {{}} {{}}; do {sleep}; gh run view $id --json {{}}; done; {query} || exit 1",
                    (first, second, *sleep_arguments, "jobs", *query_arguments),
                ),
                (
                    f"until gh api {{}} --jq {{}} | grep -q {{}}; do {sleep}; tail -1 actions/runs.log; done",
                    (f"repos/o/r/pulls/{first}", ".mergeable", "true", *sleep_arguments),
                ),
                ("gh pr checks {}; npx vitest run --watch=false", (first,)),
            )
        )
    )
    return Template(form, arguments, frozenset())


def _templates() -> st.SearchStrategy[Template]:
    return st.one_of(_waits(), _quiet())


def _cases() -> st.SearchStrategy[Case]:
    return _templates().map(lambda template: Case(template.text(), template.refusals))


def _single_quoted(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _in_backticks(command: str) -> str:
    """``command`` do wstawienia w `` `…` ``: powłoka zamyka je pierwszym gołym `` ` ``, także w ``${…}`` (POSIX), więc
    zagnieżdżony `` ` `` dostaje ukośnik. Drugi dostaje też ukośnik przed `` ` ``, ``$`` i ``\\``, bo w `` `…` `` znika,
    i ten na końcu, bo zjadłby zamykający `` ` ``."""

    return re.sub(r"\\(?=[`$\\]|\Z)|`", lambda found: "\\" + found.group(), command)


def _negated(member: str) -> str:
    return f"! {member}"


WRAPPERS: tuple[Callable[[str], str], ...] = (
    lambda member: f"( {member} )",
    lambda member: f"{{ {member}; }}",
    lambda member: f"x=$( {member} )",
    lambda member: f'echo "$( {member} )"',
    lambda member: f"if true; then {member}; fi",
    _negated,
    lambda member: f"bash -c {_single_quoted(member)}",
    lambda member: f"timeout 600 sh -c {_single_quoted(member)}",
)
PIPE = " | "
CONNECTORS = ("; ", " && ", " || ", PIPE, "\n", "\n  ")
# Polecenia, które według docstringu hooka uruchamiają argument ``-c`` jako skrypt powłoki, także przez inne polecenie.
SCRIPT_RUNNERS = (
    "sh",
    "bash",
    "zsh",
    "dash",
    "ksh",
    "fish",
    "tcsh",
    "/bin/sh",
    "/opt/homebrew/bin/bash",
    "/usr/bin/env bash",
    "timeout 600 bash",
    "sudo -u x bash",
    "xargs -I{} sh",
    "su",
    "\\bash",
    "runuser",
    "flock /tmp/blokada",
    "script -q",
    '"$SHELL"',
    '"/bin/bash"',
)
# Słowa przed ``-c`` biorą się z ogólnej składni opcji i argumentów, a nie z listy, którą zna hook: w rundach 1 i 2
# #636 własność losowała opcje z listy wzorca hooka, więc nie mogła znaleźć ``bash -euo pipefail -c`` ani
# ``su -l -s /bin/sh root -c``.
LETTERS = st.text(alphabet=string.ascii_letters, min_size=1, max_size=4)
LONG_NAME = st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True)
VALUE = st.text(alphabet=string.ascii_letters + string.digits + "/._-~=:,@%+", min_size=1, max_size=12)
WORDS = st.one_of(
    LETTERS.map(lambda letters: f"-{letters}"),
    LETTERS.map(lambda letters: f"+{letters}"),
    LONG_NAME.map(lambda name: f"--{name}"),
    st.builds(lambda name, value: f"--{name}={value}", LONG_NAME, VALUE),
    st.builds(lambda letters, value: f"-{letters} {value}", LETTERS, VALUE),
    VALUE,
    st.sampled_from(
        ("-", "--", "root", "~/.bashrc", '"moje rc"', "'a b'", "$(mktemp)", "`mktemp`", "\\;", "x\\&y")
    ),
    # Separator w cudzysłowie to znak, a nie koniec polecenia.
    st.sampled_from(("'a;b'", '"x|y"', "'(c'")),
    # Przekierowanie między słowami nie kończy polecenia.
    st.sampled_from(("2>/dev/null", ">&2", "&>/dev/null", ">|plik", "<&0")),
    # Znaki w ``${…}`` nie kończą polecenia ani nie otwierają nowego, a ``}`` poza nim nie zamyka ``$(`` (runda 3 #636).
    st.sampled_from(("${x:-)}", "${x:-(}", "${x:-a;b}", "${x:-a|b}", "$(echo {a,b})")),
    # ``${…}`` w ``${…}`` i za ``$(…)`` albo `` `…` `` w nim, a ``}`` poza ``${…}`` niczego nie zamyka (runda 1 #648).
    st.sampled_from(("${x:-${y})}", "${x-${y:=a|b}}", "${x:-$(echo -l)|b}", "${x:+`echo -l`;b}", "{a,b}")),
)
SCRIPT_OPTIONS = st.builds(
    lambda before, after: f"-{before}c{after}",
    st.text(alphabet=string.ascii_letters, max_size=3),
    st.text(alphabet=string.ascii_letters, max_size=3),
)


@st.composite
def _script_prefix(draw: st.DrawFn) -> str:
    """Początek ``-c`` powłoki z dowolnymi słowami przed ``-c``, jak ``bash --rcfile x -euc``."""

    return " ".join([draw(st.sampled_from(SCRIPT_RUNNERS)), *draw(st.lists(WORDS, max_size=8)), draw(SCRIPT_OPTIONS)])


@st.composite
def _shell_script(draw: st.DrawFn) -> Callable[[str], str]:
    """Skrypt ``-c`` powłoki: ``main`` brał za skrypt argument każdego ``-c``, więc żadna z tych form nie przechodzi."""

    prefix = draw(_script_prefix())
    return lambda member: f"{prefix} {_single_quoted(member)}"


# Bash wykonuje ``$(…)`` i `` `…` `` w słowie ``${…}``, także zagnieżdżonego, więc skrypt ``-c`` w nim to polecenie
# (runda 1 #648: ``echo ${x:-$(bash -c '…')}`` przechodziło).
PARAMETER_OPERATORS = (":-", ":=", ":+", "-")
PARAMETER_WORDS: tuple[Callable[[str], str], ...] = (
    lambda script: f"$( {script} )",
    lambda script: f"`{_in_backticks(script)}`",
    lambda script: f"${{y:-$( {script} )}}",
    lambda script: f"${{y:+`{_in_backticks(script)}`}}",
    lambda script: f"a;b$( {script} )",
)


@st.composite
def _parameter_default(draw: st.DrawFn) -> Callable[[str], str]:
    """Skrypt ``-c`` powłoki w podstawieniu w wartości ``${…}``: ``echo ${x:-$(bash -c '…')}``, ``X=${x:=`…`}``."""

    script = draw(_shell_script())
    assignment = draw(st.sampled_from(("echo ", "X=")))
    operator = draw(st.sampled_from(PARAMETER_OPERATORS))
    word = draw(st.sampled_from(PARAMETER_WORDS))
    return lambda member: f"{assignment}${{x{operator}{word(script(member))}}}"


@st.composite
def _compound(draw: st.DrawFn) -> Case:
    """Polecenie złożone z członów (``;``, ``&&``, ``||``, ``|``, nowa linia, podpowłoka, ``$(…)``, ``-c`` powłoki)."""

    members = draw(st.lists(_cases(), min_size=1, max_size=4))
    text = ""
    for index, member in enumerate(members):
        connector = draw(st.sampled_from(CONNECTORS)) if index else ""
        # ``!`` stoi tylko na początku potoku: ``a | ! b`` to błąd składni w bashu i zsh (ziarno 7015 recenzji #687).
        own = WRAPPERS if connector != PIPE else tuple(wrapper for wrapper in WRAPPERS if wrapper is not _negated)
        wrappers = st.one_of(st.sampled_from(own), _shell_script(), _parameter_default())
        text += connector + (draw(wrappers)(member.text) if draw(st.booleans()) else member.text)
    return Case(text, frozenset().union(*(member.refusals for member in members)))


# Człony ziarna 7015 z recenzji #687 z ``!`` na początku potoku, gdzie ``_compound`` je teraz stawia.
PGREP_WAIT = "until ! pgrep -f bench.py >/dev/null; do sleep 1; done"
NEGATED_PIPELINE = Case(f"{PGREP_WAIT}; ! {PGREP_WAIT} | {PGREP_WAIT}", frozenset({"pgrep"}))
# Jedyna pętla stoi za ``!``: odmowa zależy tylko od tego, że hook widzi pętlę za ``!``.
LOOP_AFTER_NEGATION = Case(f"echo a; ! {PGREP_WAIT} | cat", frozenset({"pgrep"}))


PROGRAMS = (
    "echo",
    "printf '%s\\n'",
    "grep -c",
    "grep -nE",
    "rg -n",
    "rg -c",
    "git commit -q -m",
    "git log --grep",
    "jq -n --arg opis",
    "python3 -c",
    "perl -e",
    "jq -c",
    "tr -c",
)
LOOP_WORDS = ("until", "while", "for", "do", "done", "sleep", "gh", "pgrep")


@st.composite
def _pattern(draw: st.DrawFn) -> str:
    """Wzorzec wyszukiwania bez spacji ze słowami pętli (``while|until``, ``^(for|done)$``), jak w #446."""

    words = draw(st.lists(st.sampled_from(LOOP_WORDS), min_size=1, max_size=3))
    body = draw(st.sampled_from(("|", "\\|", ";", "&", "!"))).join(words)
    opening, closing = draw(
        st.sampled_from((("", ""), ("(", ")"), ("^(", ")$"), ("\\b", "\\b"), ("{", "}"), ("`", "`")))
    )
    return opening + body + closing


def _quoted_argument(text: str, quote: str) -> str:
    return _single_quoted(text) if quote == "'" else f'"{text}"'


@PROPERTY
@example(text="until ! gh pr checks 1 | grep -q pending; do sleep 30; done", program="grep -c", quote="'", after="")
@example(text="while|until", program="rg -n", quote="'", after="sleep 1; gh pr checks 446")
@example(text="(while)", program="rg -n", quote="'", after="sleep 1; gh pr checks 446")
@example(text="x=$(until ! gh pr checks 1; do sleep 30; done)", program="echo", quote="'", after="")
@given(
    text=st.one_of(_compound().map(lambda case: case.text), _pattern()),
    program=st.sampled_from(PROGRAMS),
    quote=st.sampled_from(("'", '"')),
    # Za argumentem często ``sleep`` i zapytanie o CI: z nimi tekst wzięty za pętlę dostaje odmowę (#446).
    after=st.one_of(st.just(""), st.just("sleep 1; gh pr checks 446"), _quiet().map(lambda template: template.text())),
)
def test_tekst_w_cudzyslowie_jako_argument_polecenia_nie_jest_poleceniem(
    text: str, program: str, quote: str, after: str
) -> None:
    if any(char in text for char in '"$`\\'):
        quote = "'"
    searched = f"{program} {_quoted_argument(text, quote)} wyniki.log"
    command = f"{searched}; {after}" if after else searched

    assert shlex.split(searched) == [*shlex.split(program), text, "wyniki.log"]
    assert czekanie.judge(command, in_background=False) is None


@PROPERTY
@given(template=_templates(), quotes=st.lists(st.sampled_from(("", "'", '"')), max_size=8))
def test_ujecie_argumentu_w_cudzyslow_nie_zmienia_werdyktu(template: Template, quotes: list[str]) -> None:
    bare, quoted = template.text(), template.text(quotes)

    assert shlex.split(quoted) == shlex.split(bare)
    assert _judged(quoted) == _judged(bare) == template.refusals


REDIRECTIONS = (
    "&>/dev/null",
    "&> ci.log",
    "&>>ci.log",
    ">&2",
    "2>&1",
    "> ci.log 2>&1",
    "1>&2",
    "<&0",
    "2>&-",
    ">| ci.log",
    "| tee ci.log",
    "2>&1 | tee -a ci.log",
    "|& tee ci.log",
    "|| echo przerwane",
)


GROUPS_AFTER = (" | (cat & wait)", " | { tee ci.log & wait; }", " | tee >(cat &)")


@st.composite
def _loops(draw: st.DrawFn) -> Template:
    return draw(_waits().filter(lambda template: "watch" not in template.refusals))


@st.composite
def _redirected(draw: st.DrawFn) -> tuple[Case, Case]:
    """Ta sama pętla czekania z przekierowaniami za ``done``: na pierwszym planie i puszczona ``&``."""

    loop = draw(_loops())
    redirections = " ".join(draw(st.lists(st.sampled_from(REDIRECTIONS), max_size=3)))
    looped = f"{loop.text()} {redirections}".rstrip()
    # ``&`` w grupie za potokiem puszcza w tło tylko tę grupę, a nie pętlę.
    # ``\&`` za potokiem to znak, a nie tło.
    after = draw(
        st.sampled_from(("", "; gh pr checks 1", " && echo koniec", "\necho koniec", " | sed s/a/\\&/", *GROUPS_AFTER))
    )
    in_background = draw(
        st.sampled_from(
            (
                f"{looped} &",
                f"{looped}&",
                f"{looped} & W=$!",
                f"{looped} &\necho w tle",
                f"{{ {looped}; echo koniec ${{n}}; }} &",
                f"( {looped}; echo koniec ) &",
                f"( {{ {looped}; }} & echo w tle )",
                f"{{ {looped}; echo koniec &}} &",
                f"{looped} | (cat; wait) &",
                f"{looped} | tee ci-${{n}}.log &",
            )
        )
    )
    return Case(looped + after, loop.refusals), Case(in_background, frozenset())


@PROPERTY
@example(
    cases=(
        Case("until ! gh pr checks 1; do sleep 30; done &>/dev/null", frozenset({"ci"})),
        Case("until ! gh pr checks 1; do sleep 30; done &>/dev/null &", frozenset()),
    )
)
@example(
    cases=(
        Case("until ! gh pr checks 1; do sleep 30; done | (cat & wait)", frozenset({"ci"})),
        Case("{ until ! gh pr checks 1; do sleep 30; done; } &", frozenset()),
    )
)
@example(
    cases=(
        Case("until ! gh pr checks 1; do sleep 30; done | tee >(cat &)", frozenset({"ci"})),
        Case("until ! gh pr checks 1\n  do sleep 30\n  done &", frozenset()),
    )
)
@given(cases=_redirected())
def test_przekierowanie_za_petla_to_nie_tlo_a_pętla_puszczona_ampersandem_przechodzi(cases: tuple[Case, Case]) -> None:
    foreground, background = cases

    assert _verdict_matches(foreground), foreground.text
    assert _verdict_matches(background), background.text


@PROPERTY
# Skrypt ``-c`` powłoki w apostrofach to polecenie, a nie literał (#496).
@example(case=Case("bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'", frozenset({"ci"})))
@example(case=Case("echo a; timeout 600 sh -c 'until ! pgrep -f bench.py; do sleep 5; done'", frozenset({"pgrep"})))
# Napis przyklejony do skryptu ``-c`` (``'\\''``) to dalszy ciąg skryptu: bez tego ``done`` ginęło w literale.
@example(
    case=Case(
        "bash -c 'until ! pgrep -f x; do perl -e '\\''select(undef,undef,undef,1)'\\''; done'; sleep 1; gh pr checks 1",
        frozenset({"pgrep"}),
    )
)
# ``$(…)`` w ``"…"`` to polecenie, a pętla bez ``sleep`` nie kończy oceny następnych.
@example(case=Case('echo "$( until ! gh pr checks 1; do sleep 30; done )"', frozenset({"ci"})))
@example(case=Case("until gh pr view 1; do gh auth refresh; done; until ! gh pr checks 1; do sleep 30; done", frozenset({"ci"})))
# Opcje powłoki przed ``-c`` (runda 2 #636): ``bash -l -c`` i ``su -c`` przechodziły.
@example(
    case=Case(
        "/bin/bash --noprofile --norc -o pipefail -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
        frozenset({"ci"}),
    )
)
@example(case=Case("runuser -l x -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'", frozenset({"ci"})))
@example(case=Case("bash -l -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'", frozenset({"ci"})))
@example(case=Case("su - x -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'", frozenset({"ci"})))
@example(case=Case("cd x\n  until ! gh pr checks 1 | grep -q pending; do sleep 30; done", frozenset({"ci"})))
# ``done`` jako argument za ``do`` nie kończy pętli, więc jej ``sleep`` zostaje w ciele (runda 3 #636).
@example(case=Case("while gh pr checks 1 | grep -q pending; do echo do done; sleep 30; done", frozenset({"ci"})))
# Skrypt ``-c`` w podstawieniu w ``${…}`` (runda 1 #648), a separator w tym podstawieniu kończy polecenie powłoki.
@example(case=Case("echo ${x:-$(bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done')}", frozenset({"ci"})))
@example(case=Case("X=${X:-$(bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done')}", frozenset({"ci"})))
@example(case=Case("echo ${x:-`bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'`}", frozenset({"ci"})))
# `` ` `` w `` `…` `` zagnieżdża dopiero ukośnik (noc 30.10), a skrypt ``-c`` za nim biegnie w bashu i zsh.
@example(case=Case("echo ${x:-`sh ${x:+\\`echo -l\\`;b} -c 'gh pr checks 1 --watch'`}", frozenset({"watch"})))
@example(
    case=Case(
        "for l in ${(@f)$(bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done')}; do echo $l; done",
        frozenset({"ci"}),
    )
)
@example(
    case=Case(
        "echo ${x:-$(bash x.sh; grep -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done' f)}", frozenset()
    )
)
@example(case=Case("until gh pr view 1; do gh auth refresh; done; sleep 1", frozenset()))
@example(case=Case("for id in 1 2; do sleep 1; gh run view $id; done; gh pr checks 1 || exit 1", frozenset()))
@example(case=Case("until gh api pulls/1 | grep -q true; do sleep 2; tail -1 actions/runs.log; done", frozenset()))
@example(case=Case("gh pr checks 1; npx vitest run --watch=false", frozenset()))
@example(case=NEGATED_PIPELINE)
@example(case=LOOP_AFTER_NEGATION)
@given(case=_compound())
def test_polecenie_zlozone_dostaje_werdykt_najgorszego_czlonu(case: Case) -> None:
    assert _verdict_matches(case), case.text
    assert czekanie.judge(case.text, in_background=True) is None


LOOP = Template("until ! gh pr checks {} | grep -q pending; do sleep 30; done", ("1",), frozenset({"ci"}))


@PROPERTY
# Runda 1 #636: opcja przed ``-c``.
@example(prefix="bash -l -c", wait=LOOP)
@example(prefix="bash -e -c", wait=LOOP)
@example(prefix="bash --login -c", wait=LOOP)
@example(prefix="zsh -i -c", wait=LOOP)
@example(prefix="sh -x -c", wait=LOOP)
@example(prefix="su -c", wait=LOOP)
# Runda 2 #636: opcja z wartością, dłuższe ``su`` i słowa dłuższe niż dawne okno 80 znaków.
@example(prefix="bash -euo pipefail -c", wait=LOOP)
@example(prefix="bash -eo pipefail -c", wait=LOOP)
@example(prefix="sh -eo pipefail -c", wait=LOOP)
@example(prefix="bash --rcfile x -c", wait=LOOP)
@example(prefix="bash --init-file x -c", wait=LOOP)
@example(prefix="bash --rcfile=x -c", wait=LOOP)
@example(prefix="bash -l --rcfile x -c", wait=LOOP)
@example(prefix="su -l -s /bin/sh root -c", wait=LOOP)
@example(prefix="su --login --shell /bin/zsh maks -c", wait=LOOP)
@example(prefix="su -m -p -l root -c", wait=LOOP)
@example(prefix="su -m -l root -c", wait=LOOP)
@example(prefix="su - root -m -c", wait=LOOP)
@example(prefix="bash -o pipefail -o errexit -o nounset -o noclobber -o xtrace -o verbose -o noglob -c", wait=LOOP)
# ``$(…)`` i `` `…` `` wśród słów to osobne polecenie, po którym słowa wracają do powłoki.
@example(prefix="bash $(echo -l) -c", wait=LOOP)
@example(prefix="bash `echo -l` --norc -c", wait=LOOP)
@example(prefix="bash 'a;b' --norc -c", wait=LOOP)
# Runda 3 #636: ukośnik przed nazwą powłoki i ``)`` w ``${…}``.
@example(prefix="\\bash -c", wait=LOOP)
@example(prefix="bash ${x:-)} -c", wait=LOOP)
# Runda 1 #648: ``)`` za zagnieżdżonym ``${…}``, ``|`` za ``$(…)`` w ``${…}`` i `` ` `` zamyka niedomknięte w nim ``${``.
@example(prefix="bash ${x:-${y})} -c", wait=LOOP)
@example(prefix="bash ${x:-$(echo -l)|b} -c", wait=LOOP)
@example(prefix="bash `echo ${x` -c", wait=LOOP)
@given(prefix=_script_prefix(), wait=_waits())
def test_skrypt_c_powloki_z_dowolnymi_slowami_przed_c_to_polecenie(prefix: str, wait: Template) -> None:
    command = f"{prefix} {_single_quoted(wait.text())}"

    assert _judged(command) == wait.refusals, command


# Separator, ``(``, ``$(`` i lewy `` ` `` bez odstępu przed słowem powłoki zaczynają jej polecenie (runda 3 #636).
GLUED = (
    ("(", ")"),
    ("x=$(", ")"),
    ("echo `", "`"),
    ("true|", ""),
    ("cd x&&", ""),
    ("false||", ""),
    ("cd x;", ""),
    ("sleep 1&", ""),
)


@PROPERTY
@example(glued=("x=$(", ")"), prefix="bash -c", wait=LOOP)
@example(glued=("echo `", "`"), prefix="bash -c", wait=LOOP)
@example(glued=("true|", ""), prefix="bash -c", wait=LOOP)
@example(glued=("cd x&&", ""), prefix="bash -c", wait=LOOP)
@example(glued=("sleep 1&", ""), prefix="bash -c", wait=LOOP)
# Noc 30.10: `` ` `` w słowie przed ``-c`` zagnieżdża się w `` `…` `` tylko z ukośnikiem. Bez niego zamyka podstawienie
# (`` `sh ${x:+` ``), więc ani bash, ani zsh nie uruchamia skryptu, a hook słusznie go przepuszczał.
@example(
    glued=("echo `", "`"),
    prefix="sh ${x:+`echo -l`;b} -c",
    wait=Template("gh pr checks {} --watch", ("1",), frozenset({"watch"})),
)
@given(glued=st.sampled_from(GLUED), prefix=_script_prefix(), wait=_waits())
def test_slowo_powloki_przyklejone_do_separatora_zaczyna_skrypt_c(
    glued: tuple[str, str], prefix: str, wait: Template
) -> None:
    opening, closing = glued
    script = f"{prefix} {_single_quoted(wait.text())}"
    command = f"{opening}{_in_backticks(script) if opening.endswith('`') else script}{closing}"

    assert _judged(command) == wait.refusals, command


# Bash nie czyta ``${`` w komentarzu, a hook zamyka niedomknięte ``${`` z końcem linii, więc nie przestaje widzieć
# następnych linii: ani skryptu ``-c`` w nich, ani ``)``, która za komentarzem zamyka ``$(`` (runda 1 #648).
COMMENTS = ("echo hi # ${", "# uwaga: ${PR", "# ${a ${b:-(", "cd x # ${y:-)")
IN_SUBSTITUTION = st.sampled_from((False, True))


@PROPERTY
@example(comment="echo hi # ${", prefix="bash -c", in_substitution=False, wait=LOOP)
@example(comment="# uwaga: ${PR", prefix="bash -c", in_substitution=False, wait=LOOP)
@example(comment="# ${", prefix="bash -l -c", in_substitution=True, wait=LOOP)
@given(comment=st.sampled_from(COMMENTS), prefix=_script_prefix(), in_substitution=IN_SUBSTITUTION, wait=_waits())
def test_dolar_klamra_w_komentarzu_nie_ukrywa_skryptu_c_w_nastepnej_linii(
    comment: str, prefix: str, in_substitution: bool, wait: Template
) -> None:
    if in_substitution:
        words, option = prefix.rsplit(" ", 1)
        command = f"{words} $(echo {comment}\n) {option} {_single_quoted(wait.text())}"
    else:
        command = f"{comment}\n{prefix} {_single_quoted(wait.text())}"

    assert _judged(command) == wait.refusals, command


# Separator kończy polecenie proste powłoki, a ``$(…)`` i `` `…` `` zaczynają w nim osobne.
SEPARATORS = (
    ("; ", ""),
    (" && ", ""),
    (" || ", ""),
    (" | ", ""),
    (" & ", ""),
    ("\n", ""),
    (" # ${x:-(\n", ""),
    (" $(", ")"),
    (" `", "`"),
)


@PROPERTY
@example(prefix="bash -l x.sh", separator=("; ", ""), program="grep -c", wait=LOOP)
@example(prefix="su - root", separator=(" | ", ""), program="python3 -c", wait=LOOP)
@example(prefix="sh", separator=(" $(", ")"), program="python3 -c", wait=LOOP)
# ``}`` poza ``${…}`` niczego nie otwiera, więc ``;`` za ``{a,b}`` kończy polecenie (runda 1 #648).
@example(prefix="bash {a,b}", separator=("; ", ""), program="grep -c", wait=LOOP)
# Komentarz z niedomkniętym ``${`` kończy się z linią, a z nim polecenie powłoki (runda 1 #648).
@example(prefix="bash x.sh", separator=(" # ${x:-(\n", ""), program="grep -c", wait=LOOP)
@given(
    prefix=st.builds(
        lambda runner, words: " ".join([runner, *words]), st.sampled_from(SCRIPT_RUNNERS), st.lists(WORDS, max_size=6)
    ),
    separator=st.sampled_from(SEPARATORS),
    program=st.sampled_from(("grep -c", "rg -c", "python3 -c", "jq -c", "tr -c", "shasum -c")),
    wait=_waits(),
)
def test_powloka_za_separatorem_nie_robi_skryptu_z_argumentu_c_innego_polecenia(
    prefix: str, separator: tuple[str, str], program: str, wait: Template
) -> None:
    opening, closing = separator
    command = f"{prefix}{opening}{program} {_single_quoted(wait.text())} wyniki.log{closing}"

    assert czekanie.judge(command, in_background=False) is None, command


def _bash_4() -> str | None:
    bash = shutil.which("bash")
    if bash is None or sys.platform == "win32":
        return None
    version = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=True)
    return bash if int(version.stdout) >= 4 else None


@pytest.mark.skipif(_bash_4() is None, reason="bez bash 4 (|& i &>>), np. /bin/bash 3.2 na Macu i Windows")
@settings(derandomize=True, database=None, deadline=None, max_examples=60)
@example(case=NEGATED_PIPELINE)
@given(
    case=st.one_of(_compound(), _redirected().map(lambda cases: cases[0]), _redirected().map(lambda cases: cases[1]))
)
def test_wygenerowane_polecenia_sa_poprawne_dla_basha(case: Case) -> None:
    bash = _bash_4()
    assert bash is not None

    checked = subprocess.run([bash, "-n", "-c", case.text], capture_output=True, text=True, check=False)

    assert checked.returncode == 0, (case.text, checked.stderr)


TIMER = """
import importlib.util, json, math, statistics, sys, time
spec = importlib.util.spec_from_file_location("czekanie", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hook
spec.loader.exec_module(hook)
growth, rounds, min_half_s = int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
short, long = json.load(sys.stdin)
once = []
for _ in range(2):
    start = time.perf_counter()
    hook.judge(long, False)
    once.append(time.perf_counter() - start)
repeat = max(1, math.ceil(min_half_s / min(once)))
ratios = []
for _ in range(rounds):
    start = time.perf_counter()
    for _ in range(growth * repeat):
        hook.judge(short, False)
    middle = time.perf_counter()
    for _ in range(repeat):
        hook.judge(long, False)
    ratios.append((time.perf_counter() - middle) / (middle - start))
print(statistics.median(ratios))
"""
# Długie polecenie to ``GROWTH`` krótkich: liniowy werdykt trwa tyle co ``GROWTH`` werdyktów krótkiego (stosunek ok. 1),
# a kwadratowy ``GROWTH`` razy dłużej. Obie połowy rundy trwają przy kodzie liniowym tyle samo i biegną tuż po sobie,
# więc wywłaszczenie przez sąsiada na tłocznym runnerze trafia każdą z nich tak samo często, a spowolnienie całego
# runnera skraca się w stosunku; mediana rund pomija rundy, w które trafiło. Dawniej długie i krótkie polecenie biegły
# osobno, a w runie 41975021886 werdykt długiego (47 ms) wyszedł 68,6 raza dłuższy od krótkiego (0,69 ms) przy limicie
# 64, choć na Macu ten przykład rośnie liniowo (#906).
# Połowa rundy trwa co najmniej ``MIN_HALF_S``: obie powtarzają swoje werdykty tyle samo razy. Przestój o długości
# przydziału procesora (kilka ms) zmienia wtedy stosunek o dziesiąte części, a nie kilka razy. Dawniej połowa z jednym
# werdyktem długiego trwała na Macu 0,4 ms, a w runie 42438089096 mediana pięciu rund wyszła 4,16 przy limicie 4
# (``echo '`` i ``{ ``, na Macu 0,8), więc przestój wydłużył tę połowę w co najmniej trzech rundach z pięciu (#1096).
GROWTH = 16
ROUNDS = 5
MIN_HALF_S = 0.01
LINEAR_LIMIT = 4
# Tylko na zawieszenie (wzorzec wykładniczy): werdykt daje stosunek czasów, a nie ten limit.
HANG_S = 30
FRAGMENTS = (
    "'",
    '"',
    "(",
    ")",
    "$(",
    '"$(',
    "`",
    "\\",
    "{",
    "}",
    "{ ",
    " }",
    "${",
    "${x:-$(",
    "# ${",
    " ",
    "\n",
    ";",
    "&",
    "|",
    "2>&1 ",
    "2>1 ",
    "&>",
    "until x; do ",
    "while x; do ",
    "for x in y; do ",
    "done; ",
    "done",
    "do ",
    "sleep 1; ",
    "gh pr checks 1 ",
    "gh api x ",
    "check-runs ",
    "--watch ",
    "pgrep -a ",
    "pgrep -f x ",
    "bash -c ",
    "bash -l -o x -c ",
    "su - x -c ",
    "-lc ",
    "-c ",
    "<<EOF\n",
    "EOF\n",
    "break ",
    "$(seq 1 ",
    "{1..",
    "x",
    "a b",
)
PREFIXES = ("", "until x; do sleep 1; ", "while :; do sleep 1; gh pr checks 1; done ", "echo '", 'echo "')


# Bez zmniejszania przykładu: na kodzie kwadratowym każda próba zmniejszenia czekałaby do ``HANG_S``.
@settings(derandomize=True, database=None, deadline=None, max_examples=10, phases=(Phase.explicit, Phase.generate))
# Dawne regresje: wzorzec wykładniczy po ``done`` (#446 runda 2), pętle bez końca, puste wiersze, ``gh pr checks``
# i ``gh api`` czytane do końca polecenia, ``"$(`` głębiej niż stos Pythona.
@example(prefix="while :; do sleep 1; gh pr checks 1; done ", unit="2>1 ")
@example(prefix="", unit="until x; do ")
@example(prefix="", unit="until a& do b& done& ")
@example(prefix="", unit="\n")
@example(prefix="", unit="gh pr checks 1 ")
@example(prefix="until x; do sleep 1; ", unit="gh api x ")
@example(prefix="", unit='"$(')
@given(prefix=st.sampled_from(PREFIXES), unit=st.lists(st.sampled_from(FRAGMENTS), min_size=1, max_size=3).map("".join))
def test_czas_werdyktu_rosnie_najwyzej_liniowo_z_dlugoscia_polecenia(prefix: str, unit: str) -> None:
    repeats = -(-4000 // len(unit))
    commands = [prefix + unit * repeats, prefix + unit * repeats * GROWTH]

    timed = subprocess.run(
        [sys.executable, "-c", TIMER, str(CZEKANIE), str(GROWTH), str(ROUNDS), str(MIN_HALF_S)],
        input=json.dumps(commands),
        capture_output=True,
        text=True,
        check=True,
        timeout=HANG_S,
    )
    ratio = float(timed.stdout)

    assert ratio <= LINEAR_LIMIT, (ratio, len(commands[1]))


MODES = st.one_of(
    st.none(),
    st.sampled_from(("default", "acceptEdits", "plan", "dontAsk", "auto", "bypassPermissions")),
    st.text(max_size=20),
)
SWAPPED_QUOTES = str.maketrans({"'": '"', '"': "'"})


@PROPERTY
@given(mode=MODES, command=st.one_of(_compound().map(lambda case: case.text), st.text()))
def test_zgoda_rozstrzyga_sam_tryb_a_nie_tekst_polecenia(mode: str | None, command: str) -> None:
    # Docstring zgoda.py: kiedy pytać, rozstrzyga kontrola Claude Code, a hook jej nie odtwarza (wariant A z #496).
    denied = {"behavior": "deny", "message": zgoda.MESSAGE}
    refusal = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": denied}}
    expected = refusal if mode == "bypassPermissions" else None

    for text in (command, command.translate(SWAPPED_QUOTES), f"sh -c {_single_quoted(command)}"):
        tool_input = {"command": text, "description": "x"}
        event = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": mode,
            "tool_name": "Bash",
            "tool_input": tool_input,
        }

        assert zgoda.decision(event) == expected


@PROPERTY
@example(stdin=b"[" * 100000)
@example(stdin=b'{"permission_mode": "bypassPermissions"')
@given(
    stdin=st.one_of(
        st.binary(),
        st.text().map(str.encode),
        st.builds(lambda depth, opening: opening * depth, st.integers(1, 200000), st.sampled_from((b"[", b'{"a":'))),
    )
)
def test_zgoda_na_nieczytelnym_wejsciu_konczy_sie_kodem_0_bez_odpowiedzi(stdin: bytes) -> None:
    printed = io.StringIO()
    with mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin))), redirect_stdout(printed):
        code = zgoda.main()

    assert (code, printed.getvalue()) == (0, "")
