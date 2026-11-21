from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from statistics import median
import subprocess
import sys
import sysconfig
import time
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
from rejestr_korzeni import GuardCase, Occurrence, Reviewed
from repo import MAIN, REMOTE, ROOT
import repo
import srodowisko_ci
import straznik
from straznik import Guard, Kind
import strazniki_przeniesione
import szablon_werdyktu
from tydzien_polski import WARSAW, last_full_week, midnight, week_of
import werdykt_pr

OPIS = """Pomiar ADR 0036, 0042 i 0046 w issue „Rejestr korzeni”: odpalenia strażników, poszerzenia reguł, pary do audytu; w poniedziałek, ręcznie z --bez-zapisu.

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
  odpala ``ruff`` albo ``mypy``, a krok reguł chwastów (``STEP_GUARDS``) rodzaj strażnika każdego swojego testu z linii
  ``FAILED`` w logu kroku (``ponow_ci.log_kroku``, ``ponow_ci.TEST_LINE``) według ``WEED_TESTS`` (testy kroków reguł
  chwastów z ``srodowisko_ci``: zakaz ``noqa`` przy zakazanej nazwie i prawo właściciela to ``ruff``), a test
  ``ast-grep`` i krok bez linii ``FAILED`` odpalają ``ast-grep <id>`` każdej reguły z linii
  ``odpalenia_ast_grep.FIRED_LINE`` w logu kroku, którą zapadka drukuje na każde odpalenie
  (``odpalenia_ast_grep.refusal``), a bez takiej linii samo ``ast-grep``
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
  ``banned-api`` z tym samym ``msg`` przed merge'em, która po nim straciła nazwę albo zyskała nową nazwę z ``msg``
  którejś ze swoich nazw (``nazwy``; grupę wyznaczają nazwy, więc nowy ``msg`` jednej z nich zasięgu nie zmienia),
  albo inne pliki właścicieli ``TID251`` w ``per-file-ignores``; sama zmiana komunikatu, metadanych, komentarza i nowa reguła nim nie jest,
  a narzędzie nie odróżnia poszerzenia od zawężenia wzorca, więc kolumna ``Pola`` mówi, co się zmieniło, w chwili
  merge'a;
- para do audytu to Ważne tygodnia z polem ``Mechanizm:`` i wcześniejsze Ważne innego PR-u, scalonego przed chwilą
  Ważnego tygodnia, z tym samym szczeblem i co najmniej jednym wspólnym plikiem miejsc pola ``Gdzie:``
  (``Occurrence.files``; miejsca w tej samej funkcji leżą w tym samym pliku), z kolumną wspólnych plików; czy para to
  ten sam mechanizm błędu, rozstrzyga na ślepo audyt skilla ``polowanie``, a jego komentarz w issue z pierwszą linią
  ``AUDYT`` (``AUDIT_LINE``) od konta z ``werdykt_pr.TRUSTED`` daje liczbę ucieczek tygodnia w historii (ostatni taki
  komentarz tygodnia, ``-`` bez audytu);
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
  selektora z listy liczy jako „Bez strażnika”; odpalenia i ponowny dowód biorą w miejsce tego selektora strażnika
  wpisu Ważnego w ``strazniki_przeniesione.PLIK`` na ostatnim commicie ``origin/main`` przed końcem tygodnia
  (``moved_guards``, zasady niżej), a tabele „Strażniki” i „Wyjątki strażnika” selektor z opisu PR; udział wyjątków to Ważne z wyjątkiem (``straznik.EXEMPT``, ``brak -
  …``) przez wszystkie Ważne, a „Wyjątki strażnika” to każde Ważne tygodnia z wyjątkiem albo bez strażnika, żeby
  recenzent tygodnia sprawdził, czy wyjątek był uczciwy;
- ponowny dowód (``--ponowny-dowod``, ``reproofs``) to dowód każdego strażnika scalonego do końca tygodnia, poza
  wyjątkami ``brak - …`` (``straznik.EXEMPT``), na ostatnim commicie ``origin/main`` przed końcem tygodnia, tym samym
  poleceniem co warunek 5 ``tools/scal_pr.py`` (``bramka_straznika.PROOF``: ``--straznik <selektor> --z-commita <commit>
  --wazne <PR>/W<n>/r<k>``, jedno wywołanie na PR i selektor ze wszystkimi jego Ważnymi; bez flag warunków przyjęcia
  strażnika w wątku PR, ``--przed-dowodem-testu`` i ``--chroniony-wlasciciel``, bo pytanie to, czy strażnik dalej łapie
  swój błąd) z kopii tego commitu
  (``potomne.commit_copy``), więc kod dowodu i zadanie Required CI, które on odtwarza (``srodowisko_ci``), są z tego
  samego drzewa także po ich zmianie na ``main`` po końcu tygodnia, od najstarszego merge'a,
  w budżecie ``--budzet-dowodu`` (``REPROOF_BUDGET_S``); „Ponowny dowód strażników” pokazuje każdego strażnika bez
  ostatniej linii ``DOWÓD OK`` z liniami jego Ważnych i ostatnią linią dowodu (wynik inny niż ``WYKRYTA`` to strażnik,
  który na tym commicie przestał łapać swój błąd albo którego dowodu, np. mutacji recenzenta, nie da się już nanieść),
  a także każdego, którego dowód nie skończył się albo nie zaczął przed końcem budżetu, i każdy wpis
  ``strazniki_przeniesione.PLIK`` bez Ważnego PR scalonego do końca tygodnia w wątku strażnika (``REPROOF_STRAY``). Dowód wykonuje kod
  ``main`` (testy, backend budowy), więc w workflow biegnie w jobie bez prawa zapisu, który kończy treść issue w pliku
  (``--tresc-do``), a zapisuje ją job z ``issues: write`` bez pomiaru (``--tresc-z``); pomiar bez
  ``--ponowny-dowod`` ma w sekcji tylko linię ``REPROOF_SKIPPED``;
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
``## Reguły``, ``## Odpalenia strażników`` (z linią ``GRANICE``), ``## Poszerzenia reguł``, ``## Pary do audytu``,
``## Ponowny dowód strażników`` (z linią commitu, budżetu i liczb), ``## Strażniki``
(tydzień i od wdrożenia warunku strażnika), ``## Wyjątki strażnika``, ``## Po limicie rund``, ``## Kody`` (każdy kod
z wystąpieniem od wdrożenia, kod to kategoria ODC z ADR 0036), ``## Chwasty`` (otwarte issues „Chwast: R-KOD”)
i ``## Historia`` z wierszem na każdy z ostatnich ``HISTORY`` tygodni od tygodnia wdrożenia. Historię pomiar liczy od
nowa z rejestru, historii gita i komentarzy audytu przy każdym uruchomieniu, a starej treści issue nie czyta: rozstrzygnięcie kodu (Q25)
poprawia też minione tygodnie, a issue nie staje się drugim rejestrem. Treść należy do narzędzia, więc uwagi idą
w komentarze.

Issue to otwarte issue z etykietą ``rejestr-korzeni`` (``rejestr_korzeni.REGISTRY``, osobna od ``chwast``, żeby
lista chwastów miała same chwasty) i tytułem ``TITLE``; gdy go nie ma, pomiar je zakłada (i brakującą etykietę),
a gdy jest kilka, zmienia najstarsze z ostrzeżeniem. Pomiar zmienia tylko treść i nigdy nie komentuje, bo konto ma
secondary rate limit.

Koszt przebiegu to skan rejestru (``rejestr_korzeni`` podaje budżet: strona GraphQL na każde 19 PR-ów od wdrożenia,
1 punkt z 1000 na godzinę ``GITHUB_TOKEN``, bez renderowania treści), stała liczba żądań (``gh repo view``, lista
issues ``chwast`` i ``rejestr-korzeni``, strona komentarzy issue na każde 100 oraz zapis issue, z etykietą przy pierwszym), żądania REST odpaleń (strona
padniętych runów tygodnia na każde 100, lista zadań każdego i log każdego padniętego zadania poza ``Required CI
status``, z 1000 żądań na godzinę ``GITHUB_TOKEN``), ``ALARM_PRS`` kopii commitów z biegiem
ast-grep z dodatku dev, który workflow instaluje, polecenia gita na merge'ach, które zmieniły pliki reguł, a z
``--ponowny-dowod`` dowód każdego strażnika (środowisko Required CI z uv i jego biegi, ``srodowisko_ci``) i jego
żądania werdyktów PR.

Workflow ma dwa crony, bo cron GitHuba biegnie w UTC: ``--cron`` z cronem, który go uruchomił, przepuszcza tylko ten,
którego godzina jest dziś 6 w Warszawie (``on_time``), a drugi kończy się linią ``REJESTR KORZENI POMINIĘTY``.
Pusty ``--cron`` (``workflow_dispatch``) biegnie zawsze.

Linie wyniku: ``REJESTR KORZENI | …`` na każdą akcję albo ostrzeżenie, z ``--bez-zapisu`` po nich treść issue, a na
końcu ``REJESTR KORZENI OK | tydzień RRRR-MM-DD: …`` (z ``--tresc-z`` ``REJESTR KORZENI OK | treść z PLIK``). Błąd GitHuba, Gita, ast-grep, pliku reguły albo zły cron
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
HISTORY_COLUMNS = (*COLUMNS, "Pary do audytu", "Ucieczki z audytu")
PAIR_COLUMNS = ("Ważne tygodnia", "Wcześniejsze Ważne", "Mechanizm", "Wspólne pliki")
AUDIT = "AUDYT POWROTÓW {week} | pary {pairs} | ucieczki {escapes}"
AUDIT_LINE = re.compile(r"AUDYT POWROTÓW (\d{4}-\d{2}-\d{2}) \| pary \d+ \| ucieczki (\d+)")
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
RULES = "reguly-ast-grep"
RUFF_CONFIG = "ruff.toml"
META = frozenset({"id", "message", "note", "url", "metadata", "severity", "labels", "fix"})
BANNED_NAMES = "nazwy"
OWNERS = "per-file-ignores"
BANNED_CODE = "TID251"
WEED_TESTS = {**srodowisko_ci.WEED_TESTS, **srodowisko_ci.ADDED_LINES_TESTS}
REPROOF_BUDGET_S = 150 * 60
REPROOF_CELL = 300
REPROOF_LATE = "dowód nie skończył się przed końcem budżetu ponownego dowodu"
REPROOF_UNSTARTED = "dowód nie zaczął się przed końcem budżetu ponownego dowodu"
REPROOF_SKIPPED = "Ponowny dowód nie biegł w tym pomiarze (bez --ponowny-dowod)."
REPROOF_STRAY = f"wpis w {strazniki_przeniesione.PLIK} bez Ważnego PR scalonego do końca tygodnia w wątku strażnika: popraw klucz PR/W<n>/r<k> albo usuń wpis"

EXAMPLES = """\
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu                       # drukuje treść za ostatni pełny tydzień
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --bez-zapisu --tydzien 2026-11-16  # tydzień z tym dniem
    .venv/bin/python tools/rejestr_korzeni_tydzien.py                                    # zmienia albo zakłada issue
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --ponowny-dowod --tresc-do tresc.md  # pomiar z ponownym dowodem do pliku
    .venv/bin/python tools/rejestr_korzeni_tydzien.py --tresc-z tresc.md                 # zapis tej treści w issue
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
class Reproof:
    pull: int
    guard: Guard
    majors: tuple[str, ...]
    failure: str | None
    late: bool = False

    def row(self) -> str:
        shown = " ".join(str(self.failure).split()).replace("|", "\\|")
        cell = shown if len(shown) <= REPROOF_CELL else f"{shown[: REPROOF_CELL - 1]}…"
        return f"| #{self.pull} | {self.guard} | {', '.join(self.majors)} | {cell} |"


@dataclass(frozen=True)
class Reproofs:
    commit: str
    budget: int
    proved: tuple[Reproof, ...]

    def lead(self) -> str:
        failed = sum(reproof.failure is not None for reproof in self.proved)
        late = sum(reproof.late for reproof in self.proved)
        return (
            f"Dowód każdego strażnika scalonego do końca tygodnia na {MAIN} z {self.commit[:8]} (tools/na_scalonych_pr.py --straznik) w budżecie"
            f" {self.budget // 60} min: {len(self.proved)} strażników, {failed} bez DOWÓD OK, w tym {late} poza budżetem."
            f" Ważne, którego strażnik przestał łapać błąd, dostaje nowego wpisem w {strazniki_przeniesione.PLIK}."
        )


@dataclass(frozen=True)
class Widening:
    pull: int
    when: datetime
    rule: str
    fields: tuple[str, ...]

    def row(self) -> str:
        return f"| #{self.pull} | {self.rule} | {', '.join(self.fields)} |"


@dataclass(frozen=True)
class Pair:
    new: Occurrence
    old: Occurrence

    def row(self) -> str:
        common = ", ".join(sorted(self.new.files & self.old.files))
        return f"| #{self.new.pull} {self.new.major} | #{self.old.pull} {self.old.major} | {self.new.mechanism} | {common} |"


def pairs(pulls: Sequence[Reviewed], start: datetime, end: datetime) -> list[Pair]:
    """Pary do audytu tygodnia od ``start`` do ``end``: Ważne tygodnia i wcześniejsze Ważne innego PR-u scalonego przed
    nim, z tym samym szczeblem ``Mechanizm:`` i wspólnym plikiem miejsc ``Gdzie:``."""

    merged = {pull.pull: pull.merged for pull in pulls if pull.merged is not None}
    placed = [occurrence for pull in pulls for occurrence in pull.occurrences if occurrence.mechanism is not None and occurrence.files]
    return [
        Pair(new, old)
        for new in placed
        if start <= new.when < end
        for old in placed
        if old.pull != new.pull and old.pull in merged and merged[old.pull] <= new.when and old.mechanism == new.mechanism and old.files & new.files
    ]


def audits(comments: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Ucieczki z audytu po poniedziałku tygodnia (``RRRR-MM-DD``): z ostatniego komentarza tygodnia od konta
    z ``werdykt_pr.TRUSTED``, którego pierwsza linia to ``AUDIT_LINE``."""

    found: dict[str, int] = {}
    for comment in sorted(comments, key=lambda comment: str(comment["created_at"])):
        first = str(comment.get("body") or "").strip().splitlines()[:1]
        audit = AUDIT_LINE.fullmatch(first[0].strip()) if first and comment.get("author_association") in werdykt_pr.TRUSTED else None
        if audit is not None:
            found[audit[1]] = int(audit[2])
    return found


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
    audited: Mapping[str, int],
    reproved: Reproofs | None = None,
) -> str:
    """Treść issue ``TITLE`` dla tygodnia od poniedziałku ``week`` z PR-ów skanu rejestru ``pulls``, otwartych issues
    chwastów ``weeds`` (numer i kod), chwili wdrożenia ``deployed`` (szablon), ``guarded`` (warunek strażnika),
    odpaleń reguł ``alarms``, odpaleń strażników tygodnia ``fired``, poszerzeń reguł od wdrożenia ``widened``
    i ucieczek z audytu po poniedziałku tygodnia ``audited`` (``audits``)."""

    start, end = midnight(week), midnight(week + timedelta(days=7))
    since = f"Od wdrożenia {deployed.astimezone(WARSAW).date().isoformat()}"
    lines = _table("Pomiar", ("Okres", *COLUMNS), [f"| Tydzień {week.isoformat()} | {_cells(pulls, widened, start, end)} |", f"| {since} | {_cells(pulls, widened, None, end)} |"])[1:]
    lines += _table("Czekanie", ("Okres", *WAIT_COLUMNS), [f"| Tydzień {week.isoformat()} | {_wait(pulls, start, end)} |", f"| {since} | {_wait(pulls, None, end)} |"])
    share = f" ({_share(alarms.any_rule, alarms.prs)})" if alarms.prs else ""
    rules = [f"| {name} | {count} |" for name, count in sorted(alarms.by_rule.items(), key=lambda item: (-item[1], item[0]))]
    lines += _table("Reguły", ("Reguła", f"PR-y z odpaleniem z {alarms.prs} ostatnich"), [*rules, f"| Każda reguła | {alarms.any_rule}{share} |"])
    lines += _table("Odpalenia strażników", ("PR", "Strażnik", "Ważne strażnika"), (firing.row() for firing in fired), GRANICE)
    lines += _table("Poszerzenia reguł", ("PR", "Reguła", "Pola"), (widening.row() for widening in widened if _inside(widening.when, start, end)))
    lines += _table("Pary do audytu", PAIR_COLUMNS, (pair.row() for pair in pairs(pulls, start, end)))
    rows = (reproof.row() for reproof in reproved.proved if reproof.failure is not None) if reproved is not None else ()
    lines += _table("Ponowny dowód strażników", ("PR", "Strażnik", "Ważne", "Wynik"), rows, reproved.lead() if reproved is not None else REPROOF_SKIPPED)
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
    history = (_history(pulls, widened, audited, monday) for monday in weeks[-HISTORY:])
    lines += _table("Historia", ("Tydzień", *HISTORY_COLUMNS), history)
    return "\n".join([*lines, ""])


def _history(pulls: Sequence[Reviewed], widened: Sequence[Widening], audited: Mapping[str, int], monday: date) -> str:
    start, end = midnight(monday), midnight(monday + timedelta(days=7))
    escapes = audited.get(monday.isoformat())
    return f"| {monday.isoformat()} | {_cells(pulls, widened, start, end)} | {len(pairs(pulls, start, end))} | {'-' if escapes is None else escapes} |"


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
                kinds = {WEED_TESTS.get(found[1], kind) for found in ponow_ci.TEST_LINE.finditer(ponow_ci.log_kroku(log, steps, str(step["name"])))} or {kind}
                yield from (Guard(other) for other in sorted(kinds - {kind}, key=str))
                rules = dict.fromkeys(odpalenia_ast_grep.FIRED_LINE.findall(ponow_ci.log_kroku(log, steps, str(step["name"]))))
                if kind in kinds:
                    yield from (Guard(kind, (rule,)) for rule in rules) if rules else (Guard(kind),)
            elif kind is not None:
                yield Guard(kind)
    failed = {found[1] for found in ponow_ci.TEST_LINE.finditer(log)}
    for case in earlier:
        if case.guard is not None and case.guard.kind is Kind.PYTEST and any(test == case.guard.arguments[0] or test.startswith(f"{case.guard.arguments[0]}[") for test in failed):
            yield case.guard


def week_commit(end: datetime) -> str:
    return repo.git(ROOT, "log", "--first-parent", "-1", f"--before={end.isoformat()}", "--format=%H", f"{REMOTE}/{MAIN}").strip()


def moved_guards(pulls: Sequence[Reviewed], moved: Mapping[tuple[int, str], strazniki_przeniesione.Moved]) -> list[Reviewed]:
    return [replace(pull, guards=tuple(replace(case, guard=moved[case.pull, case.major].guard) if (case.pull, case.major) in moved else case for case in pull.guards)) for pull in pulls]


def reproofs(pulls: Sequence[Reviewed], moved: Mapping[tuple[int, str], strazniki_przeniesione.Moved], commit: str, end: datetime, budget: int) -> Reproofs:
    merged = [case for pull in pulls for case in pull.guards if case.when < end]
    cases = sorted((case for case in merged if case.guard is not None and case.guard.kind not in straznik.EXEMPT), key=lambda case: (case.when, case.pull))
    wanted: dict[tuple[int, Guard], list[str]] = {}
    for case in cases:
        if case.guard is not None:
            wanted.setdefault((case.pull, case.guard), []).append(case.major)
    with potomne.commit_copy(ROOT, commit) as copy:
        deadline = time.monotonic() + budget
        proved = tuple(_reproof(copy, commit, pull, guard, tuple(majors), deadline - time.monotonic()) for (pull, guard), majors in wanted.items())
    known = {(case.pull, case.major) for case in merged}
    strays = tuple(Reproof(entry.pull, entry.guard, (entry.major,), REPROOF_STRAY) for key, entry in moved.items() if key not in known)
    return Reproofs(commit, budget, proved + strays)


def _reproof(copy: Path, commit: str, pull: int, guard: Guard, majors: tuple[str, ...], left: float) -> Reproof:
    if left <= 0:
        return Reproof(pull, guard, majors, REPROOF_UNSTARTED, late=True)
    arguments = ["--straznik", str(guard), "--z-commita", commit, *(part for major in majors for part in ("--wazne", f"{pull}/{major.replace(' ', '/')}"))]
    try:
        done = potomne.run([sys.executable, str(copy / bramka_straznika.PROOF.relative_to(ROOT)), *arguments], cwd=copy, timeout=left)
    except subprocess.TimeoutExpired:
        return Reproof(pull, guard, majors, REPROOF_LATE, late=True)
    lines = (done.stdout + done.stderr).strip().splitlines()
    if done.returncode == 0 and lines and lines[-1].startswith(bramka_straznika.PROOF_OK):
        return Reproof(pull, guard, majors, None)
    shown = [line for line in done.stdout.splitlines() if line.startswith(f"#{pull} ")] + lines[-1:]
    return Reproof(pull, guard, majors, "; ".join(dict.fromkeys(shown)) or f"kod {done.returncode} bez wyniku")


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
        kept = names & new.keys()
        added = {name for name in new.keys() - old.keys() if new[name] in {new[member] for member in kept}}
        if kept and (added or kept != names):
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

    own = _own(issues)
    if not own:
        return github.Zaloz(TITLE, text, (rejestr_korzeni.REGISTRY,)), []
    numbers = [f"#{issue['number']}" for issue in own]
    notes = [f"{PREFIX} | UWAGA: otwarte issues „{TITLE}” {', '.join(numbers)}, zmieniam najstarsze {numbers[0]}"] if len(own) > 1 else []
    if str(own[0].get("body") or "").replace("\r\n", "\n") == text:
        return None, [*notes, f"{PREFIX} | #{own[0]['number']} ma już tę treść"]
    return github.Edytuj(int(str(own[0]["number"])), text), notes


def _own(issues: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    return sorted((issue for issue in issues if issue["title"] == TITLE), key=lambda issue: int(str(issue["number"])))


def _publish(api: github.GhApi, registry: Sequence[dict[str, object]], text: str, dry: bool) -> list[str]:
    action, lines = _action(registry, text)
    if isinstance(action, github.Zaloz):
        lines += github.zaloz_etykiety(api, rejestr_korzeni.LABELS, PREFIX, zapis=not dry)
    if action is not None:
        lines += [f"{PREFIX} | bez zapisu: {github.opis(action)}"] if dry else github.wykonaj(api, [action], PREFIX)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{OPIS}\n{strazniki_przeniesione.ZASADY}", epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bez-zapisu", action="store_true", help="Niczego nie zapisuj na GitHubie, tylko wydrukuj treść issue.")
    parser.add_argument("--tydzien", type=date.fromisoformat, help="Dzień tygodnia do pomiaru, RRRR-MM-DD (domyślnie ostatni pełny tydzień).")
    parser.add_argument("--cron", default="", help="Cron, który uruchomił workflow; pomiar biegnie, gdy jego godzina to dziś 6 czasu polskiego.")
    parser.add_argument("--ponowny-dowod", action="store_true", help="Uruchom ponowny dowód scalonych strażników na main z końca tygodnia.")
    parser.add_argument("--budzet-dowodu", type=int, default=REPROOF_BUDGET_S, metavar="S", help=f"Budżet ponownego dowodu w sekundach (domyślnie {REPROOF_BUDGET_S}).")
    parser.add_argument("--tresc-do", type=Path, metavar="PLIK", help="Zapisz treść issue do pliku zamiast w issue na GitHubie.")
    parser.add_argument("--tresc-z", type=Path, metavar="PLIK", help="Zapisz w issue treść z pliku --tresc-do, bez pomiaru.")
    args = parser.parse_args(argv)
    if args.tresc_z is not None and (args.tydzien is not None or args.cron or args.ponowny_dowod or args.tresc_do is not None):
        parser.error("--tresc-z zapisuje treść gotowego pomiaru, więc bez --tydzien, --cron, --ponowny-dowod i --tresc-do")
    now = datetime.now(UTC)
    try:
        if args.tresc_z is not None:
            text = args.tresc_z.read_bytes().decode("utf-8")
            lines = _publish(github.GhApi(), github.issues(github.GhApi(), rejestr_korzeni.REGISTRY, "open"), text, args.bez_zapisu)
            summary = f"{PREFIX} OK | treść z {args.tresc_z}"
        else:
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
            commit = week_commit(end)
            moved = strazniki_przeniesione.at(ROOT, commit)
            proving = moved_guards(pulls, moved)
            api = github.GhApi()
            fired = firings(api, proving, start, end)
            widened = [widening for widening in widenings(end) if widening.when >= deployed]
            weeded = weeds(github.issues(api, rejestr_korzeni.WEED, "open"))
            registry = github.issues(api, rejestr_korzeni.REGISTRY, "open")
            own = _own(registry)
            audited = audits(github.strony(api, f"{github.REPO}/issues/{own[0]['number']}/comments")) if own else {}
            reproved = reproofs(proving, moved, commit, end, args.budzet_dowodu) if args.ponowny_dowod else None
            text = body(pulls, weeded, week, deployed, guarded, alarms(end), fired, widened, audited, reproved)
            if args.tresc_do is not None:
                args.tresc_do.parent.mkdir(parents=True, exist_ok=True)
                args.tresc_do.write_bytes(text.encode("utf-8"))
                lines = [f"{PREFIX} | treść w {args.tresc_do}"]
            else:
                lines = _publish(api, registry, text, args.bez_zapisu)
            occurrences = sum(_inside(occurrence.when, start, end) for pull in pulls for occurrence in pull.occurrences)
            failed = f", {sum(reproof.failure is not None for reproof in reproved.proved)} strażników bez DOWÓD OK" if reproved is not None else ""
            summary = (
                f"{PREFIX} OK | tydzień {week.isoformat()}: {occurrences} wystąpień, {len(fired)} odpaleń strażników,"
                f" {sum(_inside(widening.when, start, end) for widening in widened)} poszerzeń reguł, {len(_guards(pulls, start, end))} Ważnych w wątkach strażnika{failed}"
            )
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, yaml.YAMLError, github.BladApi) as error:
        print(f"{PREFIX} FAIL | {error}")
        return 1
    for line in lines:
        print(line)
    if args.bez_zapisu:
        print(text)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
