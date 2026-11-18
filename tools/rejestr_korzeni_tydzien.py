"""Tygodniowy pomiar w issue „Rejestr korzeni”: powroty i ucieczki idiomu, czekanie na merge, odpalenia reguł, Ważne bez reguły, kody; biegnie w poniedziałek, ręcznie z --bez-zapisu.

Miary z [ADR 0036](../docs/adr/0036-chwast-to-regula.md) („Miara”, wiersz miary Q1 w „Wdrożenie”): workflow
``.github/workflows/rejestr-korzeni.yml`` uruchamia pomiar w poniedziałek o 6:17 czasu polskiego. Minuta 17, a nie
pełna godzina, bo GitHub opóźnia, a przy dużym obciążeniu porzuca biegi z cronu na początku godziny. Liczby bierze
z jednego skanu rejestru korzeni (``rejestr_korzeni.reviewed``) od wdrożenia szablonu werdyktu na ``origin/main``,
a pola werdyktu czytają jego parsery (``szablon_werdyktu`` przez ``rejestr_korzeni``):

- wystąpienie to wystąpienie kodu z rejestru: Ważne werdyktu ``FAIL`` albo blok czerwonego `main` scalonego PR,
  w chwili ``Occurrence.when``;
- powrót idiomu to Ważne z polem ``Idiom:`` w każdej z trzech postaci, bo recenzent pisze je tylko przy drugim
  wystąpieniu albo ucieczce, w chwili jego werdyktu; udział powrotów to powroty przez wystąpienia, w procentach
  zaokrąglonych w górę od połowy, a ``-`` bez wystąpień;
- ucieczka to pole ``Idiom: <id>`` bez ``jak``, czyli wystąpienie idiomu po merge'u jego reguły;
- połączenie między PR-ami to pole z ``jak #N``, gdzie ``N`` to inny PR niż PR pola;
- czekanie to czas od utworzenia ostatniego werdyktu ``PASS`` na HEAD PR do jego merge'a, dla PR-ów scalonych
  w okresie, a merge bez takiego werdyktu liczy się osobno (``Bez PASS na HEAD``); chwili zielonego CI skan nie
  czyta, więc czekanie na samo CI jest w tej liczbie;
- odpalenia reguł to odpalenia reguł ast-grep z ``sgconfig.yml`` checkoutu na liniach dodanych przez każdy z
  ``ALARM_PRS`` ostatnich merge'y PR-ów ``origin/main`` przed końcem tygodnia (``odpalenia_ast_grep.on_added_lines``,
  jak zapadka), czyli reguły dzisiejszego ``main`` na kodzie, który już przeszedł przegląd; próg ADR to 10% PR-ów;
- „Bez reguły” to każde Ważne tygodnia z polem ``Idiom: bez reguły <klasa>``, z odsyłaczem do PR.

Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego (``Europe/Warsaw``, także po
zmianie czasu), a wystąpienie, pole i merge należą do tygodnia swojej chwili. Bez ``--tydzien`` pomiar bierze ostatni
pełny tydzień przed uruchomieniem, a z ``--tydzien DATA`` tydzień z tym dniem; „od wdrożenia” liczy do końca tego
tygodnia, więc pomiar tygodnia daje te same liczby, kiedykolwiek go uruchomić, dopóki rejestr i reguły się nie zmienią.

Treść issue to szablon bez wolnej prozy (``body``): ``## Pomiar``, ``## Czekanie`` (tydzień i od wdrożenia),
``## Reguły``, ``## Bez reguły``, ``## Kody`` (każdy kod z wystąpieniem od wdrożenia, kod to kategoria ODC z ADR
0036), ``## Chwasty`` (otwarte issues „Chwast: R-KOD”) i ``## Historia`` z wierszem na każdy z ostatnich ``HISTORY``
tygodni od tygodnia wdrożenia. Historię pomiar liczy od nowa z rejestru przy każdym uruchomieniu, a starej treści
issue nie czyta: rozstrzygnięcie kodu (Q25) poprawia też minione tygodnie, a issue nie staje się drugim rejestrem.
Treść należy do narzędzia, więc uwagi idą w komentarze.

Issue to otwarte issue z etykietą ``rejestr-korzeni`` (``rejestr_korzeni.REGISTRY``, osobna od ``chwast``, żeby
lista chwastów miała same chwasty) i tytułem ``TITLE``; gdy go nie ma, pomiar je zakłada (i brakującą etykietę),
a gdy jest kilka, zmienia najstarsze z ostrzeżeniem. Pomiar zmienia tylko treść i nigdy nie komentuje, bo konto ma
secondary rate limit.

Koszt przebiegu to skan rejestru (``rejestr_korzeni`` podaje budżet: strona GraphQL na każde 19 PR-ów od wdrożenia,
1 punkt z 1000 na godzinę ``GITHUB_TOKEN``, bez renderowania treści), stała liczba żądań (``gh repo view``, lista
issues ``chwast`` i ``rejestr-korzeni`` oraz zapis issue, z etykietą przy pierwszym) i ``ALARM_PRS`` kopii commitów
z biegiem ast-grep z dodatku dev, który workflow instaluje.

Workflow ma dwa crony, bo cron GitHuba biegnie w UTC: ``--cron`` z cronem, który go uruchomił, przepuszcza tylko ten,
którego godzina jest dziś 6 w Warszawie (``on_time``), a drugi kończy się linią ``REJESTR KORZENI POMINIĘTY``.
Pusty ``--cron`` (``workflow_dispatch``) biegnie zawsze.

Linie wyniku: ``REJESTR KORZENI | …`` na każdą akcję albo ostrzeżenie, z ``--bez-zapisu`` po nich treść issue, a na
końcu ``REJESTR KORZENI OK | tydzień RRRR-MM-DD: …``. Błąd GitHuba, Gita, ast-grep albo zły cron kończy się linią
``REJESTR KORZENI FAIL`` i kodem 1.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
import shutil
from statistics import median
import subprocess
import sys
import sysconfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
import odpalenia_ast_grep
import potomne
import rejestr_korzeni
from rejestr_korzeni import IdiomCase, Reviewed
from repo import MAIN, REMOTE, ROOT
import repo
import szablon_werdyktu
from tydzien_polski import WARSAW, last_full_week, midnight, week_of
import werdykt_pr

TITLE = "Rejestr korzeni"
PREFIX = "REJESTR KORZENI"
HOUR = 6
HISTORY = 26
ALARM_PRS = 20
CONFIG = "sgconfig.yml"
AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))
CRON = re.compile(r"(\d{1,2}) (\d{1,2}) \* \* 1")
WEED_TITLE = re.compile(rf"{re.escape(rejestr_korzeni.TITLE.format(code=''))}({szablon_werdyktu.CODE.pattern})")
COLUMNS = ("Wystąpienia", "Powroty idiomu", "Udział powrotów", "Ucieczki", "Połączenia między PR-ami")
WAIT_COLUMNS = ("Merge'e", "Bez PASS na HEAD", "Mediana PASS → merge", "Najdłużej", "Ponad 1 h")
HOUR_LONG = timedelta(hours=1)

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
class Count:
    """Miary idiomu w okresie."""

    occurrences: int
    returns: int
    escapes: int
    links: int

    def share(self) -> str:
        return f"{(200 * self.returns + self.occurrences) // (2 * self.occurrences)}%" if self.occurrences else "-"

    def cells(self) -> str:
        return f"{self.occurrences} | {self.returns} | {self.share()} | {self.escapes} | {self.links}"


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


def _count(pulls: Sequence[Reviewed], start: datetime | None, end: datetime) -> Count:
    cases = [case for pull in pulls for case in pull.idioms if _inside(case.when, start, end)]
    return Count(
        sum(_inside(occurrence.when, start, end) for pull in pulls for occurrence in pull.occurrences),
        len(cases),
        sum(case.idiom.rule is not None and case.idiom.like is None for case in cases),
        sum(case.idiom.like is not None and case.idiom.like[0] != case.pull for case in cases),
    )


def _hours(span: timedelta) -> str:
    """Czas poniżej godziny w pełnych minutach, a dłuższy w godzinach z jednym miejscem po przecinku."""

    return f"{round(span / timedelta(minutes=1))} min" if span < HOUR_LONG else f"{span / HOUR_LONG:.1f} h".replace(".", ",")


def _wait(pulls: Sequence[Reviewed], start: datetime | None, end: datetime) -> str:
    merged = [pull for pull in pulls if _inside(pull.merged, start, end)]
    waits = [max(pull.merged - pull.passed, timedelta()) for pull in merged if pull.merged is not None and pull.passed is not None]
    spans = f"{_hours(median(waits))} | {_hours(max(waits))}" if waits else "- | -"
    return f"{len(merged)} | {len(merged) - len(waits)} | {spans} | {sum(wait > HOUR_LONG for wait in waits)}"


def _link(case: IdiomCase) -> str:
    like = case.idiom.like
    return f"| #{case.pull} {case.idiom.label} r{case.round} | {case.idiom.klass} | {f'#{like[0]} {like[1]} r{like[2]}' if like else '-'} |"


def body(pulls: Sequence[Reviewed], weeds: Sequence[tuple[int, str]], week: date, deployed: datetime, alarms: Alarms) -> str:
    """Treść issue ``TITLE`` dla tygodnia od poniedziałku ``week`` z PR-ów skanu rejestru ``pulls``, otwartych issues
    chwastów ``weeds`` (numer i kod), chwili wdrożenia ``deployed`` i odpaleń reguł ``alarms``."""

    start, end = midnight(week), midnight(week + timedelta(days=7))
    since = f"Od wdrożenia {deployed.astimezone(WARSAW).date().isoformat()}"
    rule = "| " + " | ".join(["---"] * (len(COLUMNS) + 1)) + " |"
    lines = ["## Pomiar", "", f"| Okres | {' | '.join(COLUMNS)} |", rule]
    lines += [f"| Tydzień {week.isoformat()} | {_count(pulls, start, end).cells()} |", f"| {since} | {_count(pulls, None, end).cells()} |"]
    lines += ["", "## Czekanie", "", f"| Okres | {' | '.join(WAIT_COLUMNS)} |", "| " + " | ".join(["---"] * (len(WAIT_COLUMNS) + 1)) + " |"]
    lines += [f"| Tydzień {week.isoformat()} | {_wait(pulls, start, end)} |", f"| {since} | {_wait(pulls, None, end)} |"]
    lines += ["", "## Reguły", "", f"| Reguła | PR-y z odpaleniem z {alarms.prs} ostatnich |", "| --- | --- |"]
    lines += [f"| {name} | {count} |" for name, count in sorted(alarms.by_rule.items(), key=lambda item: (-item[1], item[0]))]
    share = f" ({(200 * alarms.any_rule + alarms.prs) // (2 * alarms.prs)}%)" if alarms.prs else ""
    lines.append(f"| Każda reguła | {alarms.any_rule}{share} |")
    lines += ["", "## Bez reguły", "", "| Ważne | Klasa | Jak |", "| --- | --- | --- |"]
    lines += [_link(case) for pull in pulls for case in pull.idioms if case.idiom.klass is not None and _inside(case.when, start, end)]
    found = [occurrence for pull in pulls for occurrence in pull.occurrences]
    total = Counter(occurrence.code for occurrence in found if occurrence.when < end)
    weekly = Counter(occurrence.code for occurrence in found if start <= occurrence.when < end)
    lines += ["", "## Kody", "", "| Kod | Tydzień | Od wdrożenia |", "| --- | --- | --- |"]
    lines += [f"| {code} | {weekly[code]} | {count} |" for code, count in sorted(total.items(), key=lambda item: (-item[1], item[0]))]
    lines += ["", "## Chwasty", "", "| Issue | Kod |", "| --- | --- |"]
    lines += [f"| #{number} | {code} |" for number, code in sorted(weeds)]
    lines += ["", "## Historia", "", f"| Tydzień | {' | '.join(COLUMNS)} |", rule]
    first = week_of(deployed)
    weeks = [first + timedelta(days=7 * index) for index in range((week - first).days // 7 + 1)] if week >= first else []
    lines += [f"| {monday.isoformat()} | {_count(pulls, midnight(monday), midnight(monday + timedelta(days=7))).cells()} |" for monday in weeks[-HISTORY:]]
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
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
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
        repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{MAIN}:refs/remotes/{REMOTE}/{MAIN}", timeout=github.LIMIT_S).check_returncode()
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        deployed = werdykt_pr.deployment(MAIN, szablon_werdyktu.ADR)
        if deployed is None:
            raise ValueError(f"{szablon_werdyktu.ADR} nie wszedł jeszcze do {MAIN}, więc rejestru korzeni nie ma")
        pulls = rejestr_korzeni.reviewed(repository, deployed)
        api = github.GhApi()
        text = body(pulls, weeds(github.issues(api, rejestr_korzeni.WEED, "open")), week, deployed, alarms(midnight(week + timedelta(days=7))))
        action, lines = _action(github.issues(api, rejestr_korzeni.REGISTRY, "open"), text)
        if isinstance(action, github.Zaloz):
            lines += rejestr_korzeni.create_labels(api, (rejestr_korzeni.REGISTRY,), PREFIX, write=not args.bez_zapisu)
        if action is not None:
            lines += [f"{PREFIX} | bez zapisu: {github.opis(action)}"] if args.bez_zapisu else github.wykonaj(api, [action], PREFIX)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, github.BladApi) as error:
        print(f"{PREFIX} FAIL | {error}")
        return 1
    for line in lines:
        print(line)
    if args.bez_zapisu:
        print(text)
    count = _count(pulls, midnight(week), midnight(week + timedelta(days=7)))
    print(
        f"{PREFIX} OK | tydzień {week.isoformat()}: {count.occurrences} wystąpień, {count.returns} powrotów idiomu (udział {count.share()}),"
        f" {count.escapes} ucieczek, {count.links} połączeń między PR-ami"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
