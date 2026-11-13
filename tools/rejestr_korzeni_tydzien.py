"""Tygodniowy pomiar korzeni w issue „Rejestr korzeni”: wystąpienia, powtórzenia, kody i chwasty; biegnie w poniedziałek, ręcznie z --bez-zapisu.

Pomiar z ADR 0031 (decyzje Q1, Q19, Q23): workflow ``.github/workflows/rejestr-korzeni.yml`` uruchamia go
w poniedziałek o 6:00 czasu polskiego, zanim zadanie T3 o 8:00 dołoży kartę i osąd o kodach. Liczby bierze tylko
z rejestru korzeni (``rejestr_korzeni.read``) od wdrożenia szablonu werdyktu na ``origin/main``:

- wystąpienie to wystąpienie kodu z rejestru: Ważne werdyktu ``FAIL`` albo blok czerwonego `main` scalonego PR,
  w chwili ``Occurrence.when``;
- powtórzenie to wystąpienie, którego kod ma wcześniejsze wystąpienie (``when`` ściśle mniejsze) w innym PR (Q1),
  więc drugie Ważne z tym kodem w tym samym PR powtórzeniem nie jest;
- udział powtórzeń to powtórzenia przez wystąpienia, w procentach zaokrąglonych w górę od połowy, a ``-`` bez
  wystąpień.

Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego (``Europe/Warsaw``, także po
zmianie czasu), a wystąpienie należy do tygodnia swojej chwili. Bez ``--tydzien`` pomiar bierze ostatni pełny tydzień
przed uruchomieniem, a z ``--tydzien DATA`` tydzień z tym dniem; „od wdrożenia” liczy do końca tego tygodnia, więc
pomiar tygodnia daje te same liczby, kiedykolwiek go uruchomić, dopóki rejestr się nie zmieni.

Treść issue to szablon bez wolnej prozy (``body``): ``## Pomiar`` (tydzień i od wdrożenia), ``## Kody`` (każdy kod
z wystąpieniem od wdrożenia), ``## Chwasty`` (otwarte issues „Chwast: R-KOD”) i ``## Historia`` z wierszem na każdy
z ostatnich ``HISTORY`` tygodni od tygodnia wdrożenia, z którego zadanie T3 rysuje kartę XmR. Historię pomiar liczy
od nowa z rejestru przy każdym uruchomieniu, a starej treści issue nie czyta: rozstrzygnięcie kodu (Q25) poprawia też
minione tygodnie, a issue nie staje się drugim rejestrem. Treść należy do narzędzia, więc uwagi idą w komentarze.

Issue to otwarte issue z etykietą ``chwast`` i tytułem ``TITLE``; gdy go nie ma, pomiar je zakłada, a gdy jest kilka,
zmienia najstarsze z ostrzeżeniem. Pomiar zmienia tylko treść i nigdy nie komentuje, bo konto ma secondary rate limit.

Workflow ma dwa crony, bo cron GitHuba biegnie w UTC: ``--cron`` z cronem, który go uruchomił, przepuszcza tylko ten,
którego godzina jest dziś 6:00 w Warszawie (``on_time``), a drugi kończy się linią ``REJESTR KORZENI POMINIĘTY``.
Pusty ``--cron`` (``workflow_dispatch``) biegnie zawsze.

Linie wyniku: ``REJESTR KORZENI | …`` na każdą akcję albo ostrzeżenie, z ``--bez-zapisu`` po nich treść issue, a na
końcu ``REJESTR KORZENI OK | tydzień RRRR-MM-DD: …``. Błąd GitHuba, Gita albo zły cron kończy się linią
``REJESTR KORZENI FAIL`` i kodem 1.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
import rejestr_korzeni
from rejestr_korzeni import Occurrence
from repo import MAIN, REMOTE, ROOT
import repo
import szablon_werdyktu
import werdykt_pr

TITLE = "Rejestr korzeni"
PREFIX = "REJESTR KORZENI"
WARSAW = ZoneInfo("Europe/Warsaw")
HOUR = time(6, 0)
HISTORY = 26
CRON = re.compile(r"(\d{1,2}) (\d{1,2}) \* \* 1")
WEED_TITLE = re.compile(rf"{re.escape(rejestr_korzeni.TITLE.format(code=''))}({szablon_werdyktu.CODE.pattern})")
COLUMNS = ("Wystąpienia", "Powtórzenia", "Udział powtórzeń")

EXAMPLES = """\
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu                       # drukuje treść za ostatni pełny tydzień
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu --tydzien 2026-11-16  # tydzień z tym dniem
    .venv/bin/python tools/rejestr_korzeni_tydzien.py                                    # zmienia albo zakłada issue
"""


@dataclass(frozen=True)
class Count:
    """Wystąpienia i powtórzenia w okresie."""

    occurrences: int
    repeats: int

    def share(self) -> str:
        return f"{(200 * self.repeats + self.occurrences) // (2 * self.occurrences)}%" if self.occurrences else "-"

    def cells(self) -> str:
        return f"{self.occurrences} | {self.repeats} | {self.share()}"


def week_of(moment: datetime) -> date:
    """Poniedziałek tygodnia czasu polskiego, do którego należy chwila ``moment``."""

    day = moment.astimezone(WARSAW).date()
    return day - timedelta(days=day.weekday())


def last_full_week(now: datetime) -> date:
    """Poniedziałek ostatniego pełnego tygodnia czasu polskiego przed chwilą ``now``."""

    return week_of(now) - timedelta(days=7)


def on_time(cron: str, now: datetime) -> bool:
    """Czy cron ``M H * * 1`` (w UTC) wypada w dniu ``now`` (w UTC) o ``HOUR`` czasu polskiego; inna postać to
    ``ValueError``."""

    found = CRON.fullmatch(cron)
    if found is None:
        raise ValueError(f"cron „{cron}” to nie „M H * * 1”")
    planned = now.astimezone(UTC).replace(hour=int(found[2]), minute=int(found[1]), second=0, microsecond=0)
    return planned.astimezone(WARSAW).time() == HOUR


def _start(week: date) -> datetime:
    return datetime.combine(week, time(), WARSAW)


def _repeats(found: Sequence[Occurrence]) -> list[bool]:
    """Dla każdego wystąpienia: czy jego kod ma wcześniejsze wystąpienie w innym PR."""

    return [any(other.code == occurrence.code and other.pull != occurrence.pull and other.when < occurrence.when for other in found) for occurrence in found]


def _count(found: Sequence[Occurrence], repeats: Sequence[bool], start: datetime | None, end: datetime) -> Count:
    inside = [repeat for occurrence, repeat in zip(found, repeats, strict=True) if (start is None or occurrence.when >= start) and occurrence.when < end]
    return Count(len(inside), sum(inside))


def body(found: Sequence[Occurrence], weeds: Sequence[tuple[int, str]], week: date, deployed: datetime) -> str:
    """Treść issue ``TITLE`` dla tygodnia od poniedziałku ``week`` z wystąpień rejestru ``found``, otwartych issues
    chwastów ``weeds`` (numer i kod) i chwili wdrożenia ``deployed``."""

    start, end = _start(week), _start(week + timedelta(days=7))
    repeats = _repeats(found)
    lines = ["## Pomiar", "", f"| Okres | {' | '.join(COLUMNS)} |", "| --- | --- | --- | --- |"]
    lines.append(f"| Tydzień {week.isoformat()} | {_count(found, repeats, start, end).cells()} |")
    lines.append(f"| Od wdrożenia {deployed.astimezone(WARSAW).date().isoformat()} | {_count(found, repeats, None, end).cells()} |")
    total = Counter(occurrence.code for occurrence in found if occurrence.when < end)
    weekly = Counter(occurrence.code for occurrence in found if start <= occurrence.when < end)
    lines += ["", "## Kody", "", "| Kod | Tydzień | Od wdrożenia |", "| --- | --- | --- |"]
    lines += [f"| {code} | {weekly[code]} | {count} |" for code, count in sorted(total.items(), key=lambda item: (-item[1], item[0]))]
    lines += ["", "## Chwasty", "", "| Issue | Kod |", "| --- | --- |"]
    lines += [f"| #{number} | {code} |" for number, code in sorted(weeds)]
    lines += ["", "## Historia", "", f"| Tydzień | {' | '.join(COLUMNS)} |", "| --- | --- | --- | --- |"]
    first = week_of(deployed)
    weeks = [first + timedelta(days=7 * index) for index in range((week - first).days // 7 + 1)] if week >= first else []
    lines += [f"| {monday.isoformat()} | {_count(found, repeats, _start(monday), _start(monday + timedelta(days=7))).cells()} |" for monday in weeks[-HISTORY:]]
    return "\n".join([*lines, ""])


def weeds(issues: Sequence[dict[str, object]]) -> list[tuple[int, str]]:
    """Numer i kod każdego issue z tytułem „Chwast: R-KOD”."""

    return [(int(str(issue["number"])), found[1]) for issue in issues if (found := WEED_TITLE.fullmatch(str(issue["title"])))]


def _action(issues: Sequence[dict[str, object]], text: str) -> tuple[github.Akcja | None, list[str]]:
    """Akcja na issue ``TITLE`` z nową treścią ``text`` (``None``: treść już taka jest) i ostrzeżenia."""

    own = sorted((issue for issue in issues if issue["title"] == TITLE), key=lambda issue: int(str(issue["number"])))
    if not own:
        return github.Zaloz(TITLE, text, (rejestr_korzeni.WEED,)), []
    numbers = [f"#{issue['number']}" for issue in own]
    notes = [f"{PREFIX} | UWAGA: otwarte issues „{TITLE}” {', '.join(numbers)}, zmieniam najstarsze {numbers[0]}"] if len(own) > 1 else []
    if str(own[0].get("body") or "").replace("\r\n", "\n") == text:
        return None, [*notes, f"{PREFIX} | #{own[0]['number']} ma już tę treść"]
    return github.Edytuj(int(str(own[0]["number"])), text), notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bez-zapisu", action="store_true", help="Niczego nie zapisuj na GitHubie, tylko wydrukuj treść issue.")
    parser.add_argument("--tydzien", type=date.fromisoformat, help="Dzień tygodnia do pomiaru, RRRR-MM-DD (domyślnie ostatni pełny tydzień).")
    parser.add_argument("--cron", default="", help="Cron, który uruchomił workflow; pomiar biegnie, gdy jego godzina to dziś 6:00 czasu polskiego.")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.cron and not on_time(args.cron, now):
            print(f"{PREFIX} POMINIĘTY | cron „{args.cron}” nie wypada dziś o {HOUR:%H:%M} czasu polskiego")
            return 0
        week = last_full_week(now) if args.tydzien is None else week_of(_start(args.tydzien))
        repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{MAIN}:refs/remotes/{REMOTE}/{MAIN}", timeout=github.LIMIT_S).check_returncode()
        repository = str(json.loads(github.gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"])
        deployed = werdykt_pr.deployment(MAIN, szablon_werdyktu.ADR)
        if deployed is None:
            raise ValueError(f"{szablon_werdyktu.ADR} nie wszedł jeszcze do {MAIN}, więc rejestru korzeni nie ma")
        found = rejestr_korzeni.read(repository, deployed)
        api = github.GhApi()
        issues = github.issues(api, rejestr_korzeni.WEED, "open")
        text = body(found, weeds(issues), week, deployed)
        action, lines = _action(issues, text)
        if action is not None:
            lines += [f"{PREFIX} | bez zapisu: {github.opis(action)}"] if args.bez_zapisu else github.wykonaj(api, [action], PREFIX)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, github.BladApi) as error:
        print(f"{PREFIX} FAIL | {error}")
        return 1
    for line in lines:
        print(line)
    if args.bez_zapisu:
        print(text)
    repeats = _repeats(found)
    count = _count(found, repeats, _start(week), _start(week + timedelta(days=7)))
    print(f"{PREFIX} OK | tydzień {week.isoformat()}: {count.occurrences} wystąpień, {count.repeats} powtórzeń, udział {count.share()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
