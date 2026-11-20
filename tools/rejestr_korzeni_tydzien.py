from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from statistics import median
import subprocess
import sys
import sysconfig
import tomllib
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import bramka_straznika
import github
import limit_rund
import odpalenia_ast_grep
import ponow_ci
import potomne
import rejestr_korzeni
from rejestr_korzeni import GuardCase, Reviewed
from repo import MAIN, REMOTE, ROOT
import repo
import straznik
from straznik import Guard, Kind
import szablon_werdyktu
from tydzien_polski import WARSAW, last_full_week, midnight, week_of
import werdykt_pr

OPIS = """Pomiar ADR 0036, 0042 i 0046 w issue „Rejestr korzeni”: odpalenia strażników, poszerzenia reguł, czekanie, strażniki; w poniedziałek, ręcznie z --bez-zapisu.

Miary z [ADR 0036](../docs/adr/0036-chwast-to-regula.md) („Miara”, wiersz miary Q1 w „Wdrożenie”), strażniki
z [ADR 0042](../docs/adr/0042-straznik-przy-pierwszym-waznym.md) i pomiar bez pola ``Idiom:`` z
[ADR 0046](../docs/adr/0046-szczebel-straznika-wybiera-recenzent.md): workflow ``.github/workflows/rejestr-korzeni.yml``
uruchamia pomiar w poniedziałek o 6:17 czasu polskiego. Minuta 17, a nie pełna godzina, bo GitHub opóźnia, a przy dużym
obciążeniu porzuca biegi z cronu na początku godziny. Liczby bierze z jednego skanu rejestru korzeni
(``rejestr_korzeni.reviewed``) od wdrożenia szablonu werdyktu na ``origin/main``, a pola werdyktu czytają jego parsery
(``szablon_werdyktu`` przez ``rejestr_korzeni``), z runów Required CI tygodnia i z historii gita ``origin/main``:

- wystąpienie to wystąpienie kodu z rejestru: Ważne werdyktu ``FAIL`` albo blok czerwonego `main` scalonego PR,
  w chwili ``Occurrence.when``;
- odpalenie strażnika to porażka kroku strażnika w runie workflow ``CI`` PR-u (``CI_RUNS``: zdarzenie ``pull_request``,
  wynik ``failure``, ostatnia próba runu) założonym w tygodniu: krok ruff i każdy krok mypy zadania ``RUFF_MYPY``
  odpala ``ruff`` albo ``mypy``, a krok reguł chwastów (``STEP_GUARDS``) ``ast-grep <id>`` każdej reguły, której
  odpalenie ``RULE_IN_LOG`` stoi w logu kroku (``ponow_ci.log_kroku``), a bez takiej linii samo ``ast-grep``
  (porażka zakazu tłumienia); test odpala strażnik ``pytest <węzeł>`` Ważnego scalonego przed założeniem runu, gdy
  linia ``FAILED`` albo ``ERROR`` (``ponow_ci.TEST_LINE``) padniętego zadania to ten węzeł albo jego parametr. Run
  należy do najpóźniej założonego PR-u skanu z tą gałęzią sprzed runu, a bez takiego do gałęzi; „Odpalenia
  strażników” to każda para PR i strażnika tygodnia z Ważnymi, których selektor to ten strażnik (``-`` przy
  ``ruff``, ``mypy`` i samym ``ast-grep``: porażka kroku nie mówi, które Ważne wróciło). Licznik nie widzi prób
  złapanych lokalnie przed pushem (``tools/szybko.py``, brama pre-push) ani błędów bez strażnika (``GRANICE``), a logi
  runów GitHub trzyma przez czas retencji repozytorium, więc odpalenia są tylko dla tygodnia pomiaru, bez historii;
- poszerzenie reguły to zmiana zasięgu reguły, którą miała już baza merge'a PR-u na ``origin/main``
  (``widenings``): w pliku reguły ``RULES`` reguła z tym samym ``id`` przed i po merge'u z innym polem spoza
  ``META`` (``rule``, ``files``, ``ignores``, ``constraints``, ``utils``…), a w każdym ``ruff.toml`` grupa wpisów
  ``banned-api`` z tym samym ``msg`` przed merge'em z inną listą nazw po nim (``nazwy``) albo inne pliki właścicieli
  ``TID251`` w ``per-file-ignores``; sama zmiana komunikatu, metadanych, komentarza i nowa reguła nim nie jest,
  a narzędzie nie odróżnia poszerzenia od zawężenia wzorca, więc kolumna ``Pola`` mówi, co się zmieniło, w chwili
  merge'a;
- czekanie to czas od utworzenia ostatniego werdyktu ``PASS`` na HEAD PR do jego merge'a, dla PR-ów scalonych
  w okresie, a merge bez takiego werdyktu liczy się osobno (``Bez PASS na HEAD``); chwili zielonego CI skan nie
  czyta, więc czekanie na samo CI jest w tej liczbie;
- odpalenia reguł to odpalenia reguł ast-grep z ``sgconfig.yml`` checkoutu na liniach dodanych przez każdy z
  ``ALARM_PRS`` ostatnich merge'y PR-ów ``origin/main`` przed końcem tygodnia (``odpalenia_ast_grep.on_added_lines``,
  jak zapadka), czyli reguły dzisiejszego ``main`` na kodzie, który już przeszedł przegląd; próg ADR to 10% PR-ów;
  ten kod przeszedł też zapadkę Required CI, więc reguła starsza niż okno ma tu 0 z założenia, a liczba mówi
  o regule dodanej albo poszerzonej w oknie, jak dowód reguły przy przyjęciu, a nie o czerwonym CI działającej reguły;
- strażnik to selektor linii ``Strażnik:`` bloku Ważnego w sekcji ``## Korzeń`` PR scalonego w wątku, w którym
  obowiązuje warunek strażnika ADR 0042 (``rejestr_korzeni.GuardCase``: te same Ważne, blok i parser co
  ``bramka_straznika``), w chwili merge'a, od wdrożenia tego warunku (``werdykt_pr.deployment`` dla
  ``bramka_straznika.MARKER``); merge takiego PR wymaga ``DOWÓD OK`` jego strażników (warunek 5 ``tools/scal_pr.py``
  i status „Werdykt i bramka”, który ruleset wymaga na ``main``), więc pomiar dowodów nie powtarza, a Ważne bez
  selektora z listy liczy jako „Bez strażnika”; udział wyjątków to Ważne z wyjątkiem (``straznik.EXEMPT``, ``brak -
  …``) przez wszystkie Ważne, a „Wyjątki strażnika” to każde Ważne tygodnia z wyjątkiem albo bez strażnika, żeby
  recenzent tygodnia sprawdził, czy wyjątek był uczciwy;
- „Po limicie rund” to każdy PR założony w tygodniu na plikach PR-u zamkniętego bez merge'a, któremu limit rund
  odmawiał kolejnej rundy (``Reviewed.limited``), założony po ostatnim werdykcie ``FAIL`` tamtego PR, z liczbą
  wspólnych plików: limit kończy PR po szóstej rundzie z ``FAIL`` i zostawia tylko nowy PR od ``main``, którego nic
  nie blokuje, więc raport pokazuje, czy nowy PR powtarza zamknięte podejście.

Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego (``Europe/Warsaw``, także po
zmianie czasu), a wystąpienie, run, merge i poszerzenie należą do tygodnia swojej chwili. Bez ``--tydzien`` pomiar
bierze ostatni pełny tydzień przed uruchomieniem, a z ``--tydzien DATA`` tydzień z tym dniem; „od wdrożenia” liczy do
końca tego tygodnia, więc pomiar tygodnia daje te same liczby, kiedykolwiek go uruchomić, dopóki rejestr, reguły
i logi runów się nie zmienią.

Treść issue to szablon bez wolnej prozy (``body``): ``## Pomiar``, ``## Czekanie`` (tydzień i od wdrożenia),
``## Reguły``, ``## Odpalenia strażników`` (z linią ``GRANICE``), ``## Poszerzenia reguł``, ``## Strażniki``
(tydzień i od wdrożenia warunku strażnika), ``## Wyjątki strażnika``, ``## Po limicie rund``, ``## Kody`` (każdy kod
z wystąpieniem od wdrożenia, kod to kategoria ODC z ADR 0036), ``## Chwasty`` (otwarte issues „Chwast: R-KOD”)
i ``## Historia`` z wierszem na każdy z ostatnich ``HISTORY`` tygodni od tygodnia wdrożenia. Historię pomiar liczy od
nowa z rejestru i historii gita przy każdym uruchomieniu, a starej treści issue nie czyta: rozstrzygnięcie kodu (Q25)
poprawia też minione tygodnie, a issue nie staje się drugim rejestrem. Treść należy do narzędzia, więc uwagi idą
w komentarze.

Issue to otwarte issue z etykietą ``rejestr-korzeni`` (``rejestr_korzeni.REGISTRY``, osobna od ``chwast``, żeby
lista chwastów miała same chwasty) i tytułem ``TITLE``; gdy go nie ma, pomiar je zakłada (i brakującą etykietę),
a gdy jest kilka, zmienia najstarsze z ostrzeżeniem. Pomiar zmienia tylko treść i nigdy nie komentuje, bo konto ma
secondary rate limit.

Koszt przebiegu to skan rejestru (``rejestr_korzeni`` podaje budżet: strona GraphQL na każde 19 PR-ów od wdrożenia,
1 punkt z 1000 na godzinę ``GITHUB_TOKEN``, bez renderowania treści), stała liczba żądań (``gh repo view``, lista
issues ``chwast`` i ``rejestr-korzeni`` oraz zapis issue, z etykietą przy pierwszym), żądania REST odpaleń (strona
padniętych runów tygodnia na każde 100, lista zadań każdego i log każdego padniętego zadania poza ``Required CI
status``, z 1000 żądań na godzinę ``GITHUB_TOKEN``), ``ALARM_PRS`` kopii commitów z biegiem
ast-grep z dodatku dev, który workflow instaluje, i polecenia gita na merge'ach, które zmieniły pliki reguł.

Workflow ma dwa crony, bo cron GitHuba biegnie w UTC: ``--cron`` z cronem, który go uruchomił, przepuszcza tylko ten,
którego godzina jest dziś 6 w Warszawie (``on_time``), a drugi kończy się linią ``REJESTR KORZENI POMINIĘTY``.
Pusty ``--cron`` (``workflow_dispatch``) biegnie zawsze.

Linie wyniku: ``REJESTR KORZENI | …`` na każdą akcję albo ostrzeżenie, z ``--bez-zapisu`` po nich treść issue, a na
końcu ``REJESTR KORZENI OK | tydzień RRRR-MM-DD: …``. Błąd GitHuba, Gita, ast-grep, pliku reguły albo zły cron
kończy się linią ``REJESTR KORZENI FAIL`` i kodem 1.
"""

TITLE = "Rejestr korzeni"
PREFIX = "REJESTR KORZENI"
HOUR = 6
HISTORY = 26
ALARM_PRS = 20
CONFIG = "sgconfig.yml"
AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
CRON = re.compile(r"(\d{1,2}) (\d{1,2}) \* \* 1")
WEED_TITLE = re.compile(rf"{re.escape(rejestr_korzeni.TITLE.format(code=''))}({szablon_werdyktu.CODE.pattern})")
COLUMNS = ("Wystąpienia", "Poszerzenia reguł")
GUARD_COLUMNS = ("Ważne", *(kind.value for kind in Kind), "Bez strażnika", "Udział wyjątków")
WAIT_COLUMNS = ("Merge'e", "Bez PASS na HEAD", "Mediana PASS → merge", "Najdłużej", "Ponad 1 h")
HOUR_LONG = timedelta(hours=1)
GRANICE = "Licznik nie widzi prób złapanych lokalnie przed pushem ani błędów bez strażnika."
CI_RUNS = f"{github.REPO}/actions/workflows/ci.yml/runs?event=pull_request&status=failure"
RUFF_MYPY = "Ruff, mypy"
STEP_GUARDS = {
    "Lint Python code": Kind.RUFF,
    "Typecheck Python code (Linux)": Kind.MYPY,
    "Typecheck Python code (Windows)": Kind.MYPY,
    "Weed rules of the whole tree": Kind.AST_GREP,
    "ast-grep rules on the added lines of the repository": Kind.AST_GREP,
}
RULE_IN_LOG = re.compile(r"'[^'\s]+:\d+: ([\w.-]+): ")
RULES = "reguly-ast-grep"
RUFF_CONFIG = "ruff.toml"
META = frozenset({"id", "message", "note", "url", "metadata", "severity", "labels", "fix"})
BANNED_NAMES = "nazwy"
OWNERS = "per-file-ignores"
BANNED_CODE = "TID251"

EXAMPLES = """\
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu                       # drukuje treść za ostatni pełny tydzień
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu --tydzien 2026-11-16  # tydzień z tym dniem
    .venv/bin/python tools/rejestr_korzeni_tydzien.py                                    # zmienia albo zakłada issue
"""


@dataclass(frozen=True)
class Alarms:
    """Odpalenia reguł na ``prs`` ostatnich merge'ach: liczba PR-ów z odpaleniem każdej reguły, która odpaliła."""

    prs: int
    by_rule: dict[str, int]
    any_rule: int


@dataclass(frozen=True)
class Firing:
    owner: str
    guard: Guard
    majors: tuple[GuardCase, ...]

    def row(self) -> str:
        return f"| {self.owner} | {self.guard} | {', '.join(f'#{case.pull} {case.major}' for case in self.majors) or '-'} |"


@dataclass(frozen=True)
class Widening:
    pull: int
    when: datetime
    rule: str
    fields: tuple[str, ...]

    def row(self) -> str:
        return f"| #{self.pull} | {self.rule} | {', '.join(self.fields)} |"


def _share(part: int, whole: int) -> str:
    """Udział ``part`` w ``whole`` w procentach zaokrąglonych w górę od połowy, a ``-`` przy ``whole`` równym 0."""

    return f"{(200 * part + whole) // (2 * whole)}%" if whole else "-"


def on_time(cron: str, now: datetime) -> bool:
    """Czy cron ``M H * * 1`` (w UTC) wypada w dniu ``now`` (w UTC) w godzinie ``HOUR`` czasu polskiego, w dowolnej
    minucie; inna postać to ``ValueError``."""

    found = CRON.fullmatch(cron)
    if found is None:
        raise ValueError(f"cron „{cron}” to nie „M H * * 1”")
    planned = now.astimezone(UTC).replace(hour=int(found[2]), minute=int(found[1]), second=0, microsecond=0)
    return planned.astimezone(WARSAW).hour == HOUR


def _inside(when: datetime | None, start: datetime | None, end: datetime) -> bool:
    return when is not None and (start is None or when >= start) and when < end


def _cells(pulls: Sequence[Reviewed], widened: Sequence[Widening], start: datetime | None, end: datetime) -> str:
    occurrences = sum(_inside(occurrence.when, start, end) for pull in pulls for occurrence in pull.occurrences)
    return f"{occurrences} | {sum(_inside(widening.when, start, end) for widening in widened)}"


def _guards(pulls: Sequence[Reviewed], start: datetime | None, end: datetime) -> list[GuardCase]:
    return [case for pull in pulls for case in pull.guards if _inside(case.when, start, end)]


def _guard_cells(cases: Iterable[GuardCase]) -> str:
    """Ważne, liczba Ważnych z każdym rodzajem strażnika (``straznik.Kind``), bez strażnika i udział wyjątków."""

    kinds = Counter(case.guard.kind if case.guard is not None else None for case in cases)
    total = kinds.total()
    return " | ".join([str(total), *(str(kinds[kind]) for kind in Kind), str(kinds[None]), _share(sum(kinds[kind] for kind in straznik.EXEMPT), total)])


def _hours(span: timedelta) -> str:
    """Czas poniżej godziny w pełnych minutach, a dłuższy w godzinach z jednym miejscem po przecinku."""

    return f"{round(span / timedelta(minutes=1))} min" if span < HOUR_LONG else f"{span / HOUR_LONG:.1f} h".replace(".", ",")


def _wait(pulls: Sequence[Reviewed], start: datetime | None, end: datetime) -> str:
    merged = [pull for pull in pulls if _inside(pull.merged, start, end)]
    waits = [max(pull.merged - pull.passed, timedelta()) for pull in merged if pull.merged is not None and pull.passed is not None]
    spans = f"{_hours(timedelta(seconds=median(wait.total_seconds() for wait in waits)))} | {_hours(max(waits))}" if waits else "- | -"
    return f"{len(merged)} | {len(merged) - len(waits)} | {spans} | {sum(wait > HOUR_LONG for wait in waits)}"


def _after_limit(pulls: Sequence[Reviewed], start: datetime, end: datetime) -> list[str]:
    limited = [pull for pull in pulls if pull.limited is not None]
    return [
        f"| #{new.pull} | #{old.pull} | {len(common)} |"
        for new in pulls
        if _inside(new.created, start, end)
        for old in limited
        if old.limited is not None and new.created is not None and old.limited <= new.created and (common := new.files & old.files)
    ]


def _table(name: str, columns: Sequence[str], rows: Iterable[str], *lead: str) -> list[str]:
    return ["", f"## {name}", "", *lead, *([""] if lead else []), f"| {' | '.join(columns)} |", "| " + " | ".join(["---"] * len(columns)) + " |", *rows]


def body(
    pulls: Sequence[Reviewed],
    weeds: Sequence[tuple[int, str]],
    week: date,
    deployed: datetime,
    guarded: datetime,
    alarms: Alarms,
    fired: Sequence[Firing],
    widened: Sequence[Widening],
) -> str:
    """Treść issue ``TITLE`` dla tygodnia od poniedziałku ``week`` z PR-ów skanu rejestru ``pulls``, otwartych issues
    chwastów ``weeds`` (numer i kod), chwili wdrożenia ``deployed`` (szablon), ``guarded`` (warunek strażnika),
    odpaleń reguł ``alarms``, odpaleń strażników tygodnia ``fired`` i poszerzeń reguł od wdrożenia ``widened``."""

    start, end = midnight(week), midnight(week + timedelta(days=7))
    since = f"Od wdrożenia {deployed.astimezone(WARSAW).date().isoformat()}"
    lines = _table("Pomiar", ("Okres", *COLUMNS), [f"| Tydzień {week.isoformat()} | {_cells(pulls, widened, start, end)} |", f"| {since} | {_cells(pulls, widened, None, end)} |"])[1:]
    lines += _table("Czekanie", ("Okres", *WAIT_COLUMNS), [f"| Tydzień {week.isoformat()} | {_wait(pulls, start, end)} |", f"| {since} | {_wait(pulls, None, end)} |"])
    share = f" ({_share(alarms.any_rule, alarms.prs)})" if alarms.prs else ""
    rules = [f"| {name} | {count} |" for name, count in sorted(alarms.by_rule.items(), key=lambda item: (-item[1], item[0]))]
    lines += _table("Reguły", ("Reguła", f"PR-y z odpaleniem z {alarms.prs} ostatnich"), [*rules, f"| Każda reguła | {alarms.any_rule}{share} |"])
    lines += _table("Odpalenia strażników", ("PR", "Strażnik", "Ważne strażnika"), (firing.row() for firing in fired), GRANICE)
    lines += _table("Poszerzenia reguł", ("PR", "Reguła", "Pola"), (widening.row() for widening in widened if _inside(widening.when, start, end)))
    since_guard = f"Od wdrożenia {guarded.astimezone(WARSAW).date().isoformat()}"
    guards = [f"| Tydzień {week.isoformat()} | {_guard_cells(_guards(pulls, start, end))} |", f"| {since_guard} | {_guard_cells(_guards(pulls, None, end))} |"]
    lines += _table("Strażniki", ("Okres", *GUARD_COLUMNS), guards)
    exempt = (f"| #{case.pull} {case.major} | {case.guard or '-'} |" for case in _guards(pulls, start, end) if case.guard is None or case.guard.kind in straznik.EXEMPT)
    lines += _table("Wyjątki strażnika", ("Ważne", "Strażnik"), exempt)
    lines += _table("Po limicie rund", ("Nowy PR", "PR zamknięty po limicie", "Wspólne pliki"), _after_limit(pulls, start, end))
    found = [occurrence for pull in pulls for occurrence in pull.occurrences]
    total = Counter(occurrence.code for occurrence in found if occurrence.when < end)
    weekly = Counter(occurrence.code for occurrence in found if start <= occurrence.when < end)
    lines += _table("Kody", ("Kod", "Tydzień", "Od wdrożenia"), (f"| {code} | {weekly[code]} | {count} |" for code, count in sorted(total.items(), key=lambda item: (-item[1], item[0]))))
    lines += _table("Chwasty", ("Issue", "Kod"), (f"| #{number} | {code} |" for number, code in sorted(weeds)))
    first = week_of(deployed)
    weeks = [first + timedelta(days=7 * index) for index in range((week - first).days // 7 + 1)] if week >= first else []
    history = (f"| {monday.isoformat()} | {_cells(pulls, widened, midnight(monday), midnight(monday + timedelta(days=7)))} |" for monday in weeks[-HISTORY:])
    lines += _table("Historia", ("Tydzień", *COLUMNS), history)
    return "\n".join([*lines, ""])


def alarms(end: datetime) -> Alarms:
    """Odpalenia reguł ``CONFIG`` checkoutu na liniach dodanych przez ``ALARM_PRS`` ostatnich merge'y PR-ów
    ``origin/main`` przed chwilą ``end``; brak ast-grep przy dodanej linii albo jego porażka to ``ScanFailed``."""

    log = repo.git(ROOT, "log", "--first-parent", f"--before={end.isoformat()}", "--format=%H %s", f"{REMOTE}/{MAIN}")
    merges = [commit for commit, _, subject in (line.partition(" ") for line in log.splitlines()) if github.MERGE.fullmatch(subject)][:ALARM_PRS]
    by_rule: Counter[str] = Counter()
    any_rule = 0
    for commit in merges:
        with potomne.commit_copy(ROOT, commit) as copy:
            fired = {finding.rule for finding in odpalenia_ast_grep.on_added_lines(copy, f"{commit}^1", ("--config", str(ROOT / CONFIG)), AST_GREP)}
        by_rule.update(fired)
        any_rule += bool(fired)
    return Alarms(len(merges), dict(by_rule), any_rule)


def firings(api: github.GitHub, pulls: Sequence[Reviewed], start: datetime, end: datetime) -> list[Firing]:
    span = "..".join(moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") for moment in (start, end))
    guarded = [case for pull in pulls for case in pull.guards if case.guard is not None]
    found: dict[tuple[str, Guard], Firing] = {}
    for run in github.strony(api, f"{CI_RUNS}&created={span}", "workflow_runs"):
        created = datetime.fromisoformat(str(run["created_at"]))
        if not start <= created < end:
            continue
        owner = _owner(pulls, str(run["head_branch"]), created)
        earlier = [case for case in guarded if case.when < created]
        for job in github.strony(api, f"{github.REPO}/actions/runs/{run['id']}/jobs", "jobs"):
            if job["conclusion"] in ponow_ci.FAILED_JOB and job["name"] != github.REQUIRED:
                for guard in _fired(job, ponow_ci.log_zadania(api, job), earlier):
                    found[owner, guard] = Firing(owner, guard, tuple(case for case in earlier if guard.arguments and case.guard == guard))
    return sorted(found.values(), key=lambda firing: (_number(firing.owner), firing.owner, str(firing.guard)))


def _owner(pulls: Sequence[Reviewed], branch: str, created: datetime) -> str:
    candidates = [pull for pull in pulls if pull.branch == branch and pull.created is not None and pull.created <= created]
    latest = max(candidates, key=lambda pull: (pull.created, pull.pull), default=None)
    return f"#{latest.pull}" if latest is not None else f"gałąź {branch}"


def _number(owner: str) -> int:
    return int(owner[1:]) if owner.startswith("#") else sys.maxsize


def _fired(job: Mapping[str, Any], log: str, earlier: Sequence[GuardCase]) -> Iterator[Guard]:
    steps = job.get("steps") or ()
    if job["name"] == RUFF_MYPY:
        for step in steps:
            kind = STEP_GUARDS.get(str(step["name"])) if step["conclusion"] == "failure" else None
            if kind is Kind.AST_GREP:
                rules = dict.fromkeys(RULE_IN_LOG.findall(ponow_ci.log_kroku(log, steps, str(step["name"]))))
                yield from (Guard(kind, (rule,)) for rule in rules) if rules else (Guard(kind),)
            elif kind is not None:
                yield Guard(kind)
    failed = {found[1] for found in ponow_ci.TEST_LINE.finditer(log)}
    for case in earlier:
        if case.guard is not None and case.guard.kind is Kind.PYTEST and any(test == case.guard.arguments[0] or test.startswith(f"{case.guard.arguments[0]}[") for test in failed):
            yield case.guard


def widenings(end: datetime) -> list[Widening]:
    log = repo.git(ROOT, "log", "--first-parent", f"--before={end.isoformat()}", "--format=%H %cI %s", f"{REMOTE}/{MAIN}", "--", RULES, f"*{RUFF_CONFIG}")
    found = []
    for line in log.splitlines():
        commit, when, subject = line.split(" ", 2)
        merge = github.MERGE.fullmatch(subject)
        if merge is None:
            continue
        for path in repo.git(ROOT, "diff", "--name-only", f"{commit}^1", commit, "--", RULES, f"*{RUFF_CONFIG}").splitlines():
            before, after = repo.blob(ROOT, f"{commit}^1", path), repo.blob(ROOT, commit, path)
            if before is None or after is None:
                continue
            if path.startswith(f"{RULES}/"):
                changes = _rule_changes(before.decode("utf-8"), after.decode("utf-8"))
            elif PurePosixPath(path).name == RUFF_CONFIG:
                changes = _ban_changes(path, tomllib.loads(before.decode("utf-8")), tomllib.loads(after.decode("utf-8")))
            else:
                continue
            found += [Widening(int(merge["numer"]), datetime.fromisoformat(when), rule, fields) for rule, fields in changes]
    return sorted(found, key=lambda widening: (widening.when, widening.pull, widening.rule))


def _rule_changes(before: str, after: str) -> list[tuple[str, tuple[str, ...]]]:
    old, new = _rules(before), _rules(after)
    changes = [(rule, tuple(sorted(key for key in (old[rule].keys() | new[rule].keys()) - META if old[rule].get(key) != new[rule].get(key)))) for rule in sorted(old.keys() & new.keys())]
    return [(rule, fields) for rule, fields in changes if fields]


def _rules(text: str) -> dict[str, dict[str, Any]]:
    return {str(document["id"]): document for document in yaml.safe_load_all(text) if isinstance(document, dict) and "id" in document}


def _ban_changes(path: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    old, new = _bans(before), _bans(after)
    changes: list[tuple[str, tuple[str, ...]]] = []
    for message in dict.fromkeys(old.values()):
        names = {name for name, text in old.items() if text == message}
        moved = {new[name] for name in names if name in new}
        group = {name for name, text in new.items() if text in moved}
        if moved and (len(moved) > 1 or group != names):
            changes.append((f"banned-api {min(names)}", (BANNED_NAMES,)))
    if _owners(before) != _owners(after):
        changes.append((f"banned-api {path}", (OWNERS,)))
    return changes


def _bans(config: Mapping[str, Any]) -> dict[str, str]:
    banned = config.get("lint", {}).get("flake8-tidy-imports", {}).get("banned-api", {})
    return {str(name): str(entry.get("msg", "")) for name, entry in banned.items()}


def _owners(config: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(str(pattern) for pattern, codes in config.get("lint", {}).get(OWNERS, {}).items() if BANNED_CODE in codes)


def weeds(issues: Sequence[dict[str, object]]) -> list[tuple[int, str]]:
    """Numer i kod każdego issue z tytułem „Chwast: R-KOD”."""

    return [(int(str(issue["number"])), found[1]) for issue in issues if (found := WEED_TITLE.fullmatch(str(issue["title"])))]


def _action(issues: Sequence[dict[str, object]], text: str) -> tuple[github.Akcja | None, list[str]]:
    """Akcja na issue ``TITLE`` z nową treścią ``text`` (``None``: treść już taka jest) i ostrzeżenia; ``issues`` to
    otwarte issues z etykietą ``rejestr_korzeni.REGISTRY``."""

    own = sorted((issue for issue in issues if issue["title"] == TITLE), key=lambda issue: int(str(issue["number"])))
    if not own:
        return github.Zaloz(TITLE, text, (rejestr_korzeni.REGISTRY,)), []
    numbers = [f"#{issue['number']}" for issue in own]
    notes = [f"{PREFIX} | UWAGA: otwarte issues „{TITLE}” {', '.join(numbers)}, zmieniam najstarsze {numbers[0]}"] if len(own) > 1 else []
    if str(own[0].get("body") or "").replace("\r\n", "\n") == text:
        return None, [*notes, f"{PREFIX} | #{own[0]['number']} ma już tę treść"]
    return github.Edytuj(int(str(own[0]["number"])), text), notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bez-zapisu", action="store_true", help="Niczego nie zapisuj na GitHubie, tylko wydrukuj treść issue.")
    parser.add_argument("--tydzien", type=date.fromisoformat, help="Dzień tygodnia do pomiaru, RRRR-MM-DD (domyślnie ostatni pełny tydzień).")
    parser.add_argument("--cron", default="", help="Cron, który uruchomił workflow; pomiar biegnie, gdy jego godzina to dziś 6 czasu polskiego.")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.cron and not on_time(args.cron, now):
            print(f"{PREFIX} POMINIĘTY | cron „{args.cron}” nie wypada dziś w godzinie {HOUR} czasu polskiego")
            return 0
        week = last_full_week(now) if args.tydzien is None else week_of(midnight(args.tydzien))
        start, end = midnight(week), midnight(week + timedelta(days=7))
        repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{MAIN}:refs/remotes/{REMOTE}/{MAIN}", timeout=github.LIMIT_S).check_returncode()
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        deployed, guarded = (werdykt_pr.deployment(MAIN, marker) for marker in (szablon_werdyktu.ADR, bramka_straznika.MARKER))
        if deployed is None or guarded is None:
            raise ValueError(f"{szablon_werdyktu.ADR} albo {bramka_straznika.MARKER} nie wszedł jeszcze do {MAIN}, więc rejestru korzeni albo strażników nie ma")
        pulls = rejestr_korzeni.reviewed(repository, deployed, werdykt_pr.deployment(MAIN, limit_rund.MARKER), guarded)
        api = github.GhApi()
        fired = firings(api, pulls, start, end)
        widened = [widening for widening in widenings(end) if widening.when >= deployed]
        text = body(pulls, weeds(github.issues(api, rejestr_korzeni.WEED, "open")), week, deployed, guarded, alarms(end), fired, widened)
        action, lines = _action(github.issues(api, rejestr_korzeni.REGISTRY, "open"), text)
        if isinstance(action, github.Zaloz):
            lines += github.zaloz_etykiety(api, rejestr_korzeni.LABELS, PREFIX, zapis=not args.bez_zapisu)
        if action is not None:
            lines += [f"{PREFIX} | bez zapisu: {github.opis(action)}"] if args.bez_zapisu else github.wykonaj(api, [action], PREFIX)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, yaml.YAMLError, github.BladApi) as error:
        print(f"{PREFIX} FAIL | {error}")
        return 1
    for line in lines:
        print(line)
    if args.bez_zapisu:
        print(text)
    occurrences = sum(_inside(occurrence.when, start, end) for pull in pulls for occurrence in pull.occurrences)
    print(
        f"{PREFIX} OK | tydzień {week.isoformat()}: {occurrences} wystąpień, {len(fired)} odpaleń strażników,"
        f" {sum(_inside(widening.when, start, end) for widening in widened)} poszerzeń reguł, {len(_guards(pulls, start, end))} Ważnych w wątkach strażnika"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
