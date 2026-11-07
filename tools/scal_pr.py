"""Jedyna droga merge'a PR przez agenta: sprawdza gotowość (CI, werdykt PASS, opis) tuż przed gh pr merge; użyj zamiast gołego merge'a.

Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy werdykt dla HEAD PR to ``PASS`` w postaci, którą publikuje ``--werdykt`` (niżej);
4. opis PR ma każdy nagłówek ``##`` wzoru z ``.agents/skills/pr/SKILL.md``, każdy jako osobną linię i w kolejności
   wzoru, więc każdy PR ma te same sekcje, a sekcja dopisana do wzoru od razu obowiązuje;
5. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``status_scalenia.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu);
6. na tym scalonym drzewie przechodzi test scalenia, gdy jest potrzebny i mieści się w limicie (niżej).

Test scalenia łapie PR, który z bieżącą bazą daje czerwony ``main``, choć sam był zielony, bo baza od merge-base PR
zmieniła coś, czego PR używa. Gdy baza od merge-base się nie zmieniła, nie liczy niczego. Inaczej bierze pliki testów
dotknięte i zmianą PR, i zmianą bazy od merge-base, w odległości najwyżej ``MERGE_TEST_DISTANCE`` od każdej z nich
w grafie ``tools/lib/wplyw_zmiany.py`` liczonym na scalonym drzewie: plik testów zmieniony albo zależny wprost od pliku
zmienionego po obu stronach. Gdy takich plików nie ma, nic nie biegnie (liczenie trwało ~1,5 s na merge'ach z 6.11.2026).
Gdy są, biegną pytestem w kopii scalonego drzewa, z jego ``tests/conftest.py``, więc test z kwarantanny
(``tests/fixtures/kwarantanna.py``) nie czerwieni wyniku, jak w CI. Gdy któryś test pada, te same pliki testów biegną
jeszcze raz na drzewie samej bazy, bo czerwony ``main`` nie blokuje merge'ów (ADR 0020): odmowa z nazwami testów
zachodzi tylko wtedy, gdy któryś test pada na scaleniu, a na samej bazie nie (albo nie ma go na bazie). Gdy każdy
padnięty test pada też na samej bazie, PR przechodzi, a linia ``SCAL OK`` wymienia te testy (``na samym main … pada
już: …``). Ten drugi bieg kosztuje tylko po porażce. Pytest, który pada bez nazwy testu, to odmowa z przyczyną ze stderr.
Test scalenia nie biegnie, a linia ``SCAL OK`` mówi dlaczego (``test scalenia pominięty: …``), gdy któraś strona
zmienia plik reguły wyboru testów (``Context.TESTS``: ``conftest.py`` każdego testu, konfiguracja), bo taki plik dotyczy
każdego testu, gdy suma czasów CI tych plików (tor ``czasy_ci.TOR_LOKALNY``, plik bez pomiaru waży medianę) przekracza
``MERGE_TEST_BUDGET_S`` albo gdy czasów CI nie ma. Na merge'ach z 6.11.2026 limit przepuścił pliki do 20 s w CI
(4–8 s na Macu agenta), a zatrzymał pliki od 437 s w CI (93 s na Macu i więcej). Test, który trwa dłużej niż
``MERGE_TEST_TIMEOUT_S``, to odmowa, bo nie dał wyniku.

Mutacje zmienionych linii nie biegną na PR i nie czeka na nie: biegną nocą na ``main`` (ADR 0021,
``tools/mutacje_nocne.py``).

Werdykty to komentarze i recenzje PR kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``), w kolejności
utworzenia; nieopublikowana recenzja (``PENDING``) się nie liczy. Werdykt to komentarz albo recenzja, której pierwsza
niepusta linia, bez odstępów na brzegach, to dokładnie ``WERDYKT: PASS <SHA>`` albo ``WERDYKT: FAIL <SHA>``, gdzie
``<SHA>`` to pełny SHA HEAD PR małymi literami. ``FAIL`` jest sprzeciwem bez względu na dalsze linie, tak jak
recenzja w stanie ``CHANGES_REQUESTED``. ``PASS`` jest zgodą tylko wtedy, gdy cała treść przechodzi reguły
``--werdykt`` (niżej), bez względu na to, jak go opublikowano; inaczej to odmowa ``werdykt: PASS dla <sha> nie
przechodzi reguł --werdykt (<przyczyny>)`` z poleceniem ``--werdykt``, bo ręczny komentarz omijał te reguły (#994,
#1001, #1004). Inny tekst, także ``FAIL`` w prozie albo werdykt ze skróconym SHA, nie jest werdyktem. Zgodę pisze
niezależny recenzent, nie autor zmiany: ``PASS`` mówi, że przegląd nie znalazł problemów, a skille ``verify-*``
z linii ``SKILLE VERIFY`` ``tools/skille_dla_zmiany.py`` przeszły na tym SHA (ich polecenia z linii ``LICZY CI``
w CI, reszta workflow u agenta). Rozstrzyga najnowszy werdykt dla HEAD:
sprzeciw po ``PASS`` odbiera zgodę, nowszy ``PASS`` ją przywraca, a werdykt starszego commitu nie przechodzi na nowy
push. Komentarz edytowany liczy się z treścią po edycji, ale w miejscu utworzenia, a ukryty komentarz nadal się liczy.

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–4 sprawdza razem i podaje wszystkie przyczyny; warunki 5 i 6 trwają dłużej, więc biegną dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia
``tools/sprzatanie.py``, jeśli istnieje, i podaje ostatnią linię jego raportu: bez ``--usun`` sprzątanie niczego nie
usuwa, tylko mówi, które lokalne gałęzie i worktree można usunąć. Sprzątanie, które przekroczy czas, kończy się
ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony.

Po merge'u do domyślnej gałęzi repozytorium, przed sprzątaniem, zamyka jego otwarte issues, które opis PR wskazuje
słowem „Naprawia”. GitHub tego słowa nie zna, więc bez narzędzia takie issues zostawały otwarte. Każde dostaje
komentarz z numerem PR i pełnym SHA commitu merge'a, a linia ``SCAL OK`` podaje ``zamknięte: #N``. Opis bez słowa
„Naprawia” pomija bez pytania GitHuba. Z nim pyta o domyślną gałąź (``gh repo view``), a przy merge'u do niej
renderuje opis rendererem GitHuba (``gh api markdown``, ``mode=gfm``, ``context`` to repozytorium PR), więc to GitHub
decyduje, co jest kodem, cytatem albo komentarzem HTML.

Issue się liczy, gdy GitHub zamienił jego odwołanie na link do issue tego repozytorium (bez względu na wielkość liter
właściciela i nazwy), a link stoi na liście numerów zaraz po słowie „Naprawia”, pisanym dokładnie tak, od wielkiej
litery, które zaczyna linię akapitu albo punktu listy. Linia liczy się tylko wtedy, gdy jej tekst zaczyna się
w akapicie albo punkcie listy, a wszystko, w czym ten blok stoi, to akapity, punkty i listy; w samym bloku tekst może
stać jeszcze w pogrubieniu albo kursywie. Każde inne miejsce niczego nie zamyka, także takie, którego tu nie wymieniono
i którego GitHub dopiero zacznie używać: nagłówek, tabela, ``<details>`` i ``<summary>``, cytat i alert GitHuba
(``> [!NOTE]``), blok HTML (``<div>``, ``<section>``, ``<dl>``), przypis i ``<pre>``, także gdy GitHub owinie tekst
w nich w akapit albo punkt listy. Linię kończy tylko ``<br>``, którym GitHub zastępuje koniec wiersza, oraz początek
i koniec bloku: akapitu, punktu listy, nagłówka, cytatu, tabeli, ``<pre>``, ``<div>``, ``<details>``, ``<summary>``
i ``<hr>``. Każdy inny znacznik (``<q>``, ``<kbd>``, emoji, wzór ``$…$`` i każdy, którego GitHub dopiero zacznie
używać) należy do linii, a jego tekst się liczy, poza kodem i przekreśleniem. Liczy się więc ``Naprawia #490``,
``Naprawia #490, #491 i #492 oraz #493``, kilka linii, także pogrubionych, i adres issue. Lista kończy się na
pierwszym tekście innym niż przecinek, „i”, „oraz” albo numer, którego GitHub nie zlinkował (nieistniejący): „Naprawia
#490. Nie naprawia #491” zamyka tylko #490. Kończy ją też odwołanie do innego repozytorium: w ``Naprawia
MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia#12, #13`` GitHub linkuje ``#13`` do tego repo, ale autor wylicza tam
Zgłoszenia. Zgłoszenie zostaje otwarte, bo zamknięte mówi Centrum taty, że poprawka czeka na aktualizację, a merge do
``main`` to jeszcze nie Wydanie. Nie zamyka: „Naprawia” w środku linii (także „Ten PR <q>nie</q> Naprawia #490”),
„naprawia” małą literą (także w zawiniętej linii „Ten PR nie do końca⏎naprawia #490”), linii, która zaczyna się od
kodu, przekreślenia (także takich, które zaczęły się przed końcem poprzedniego wiersza: ``~~Ten PR⏎nie~~ Naprawia
#490``), obrazka albo pola punktu listy zadań (``- [ ] Naprawia #490``), linii spoza akapitów i list (wyżej), kodu
(fragmentu, bloku i ``<pre>``), przekreślenia, PR-a, issue już zamkniętego ani issues, które GitHub zamyka sam
(``closingIssuesReferences``: ``Closes``, ``Fixes``, ``Resolves``).

Merge do innej gałęzi niż domyślna (stos PR-ów) niczego nie zamyka i nie renderuje opisu, jak GitHub przy ``Closes``,
a linia podaje ``bez zamykania „Naprawia”: baza <gałąź> to nie <domyślna>``. Gdy GitHub nie poda domyślnej gałęzi
albo nie wyrenderuje opisu (``gh`` z błędem albo po czasie, pusta odpowiedź), narzędzie niczego nie zamyka, tylko
ostrzega ``UWAGA: GitHub nie podał domyślnej gałęzi`` albo ``UWAGA: GitHub nie wyrenderował opisu PR`` z dopiskiem
``nie zamknięto issues z „Naprawia”, zamknij je ręcznie``. Gdy GitHub po merge'u nie poda commitu merge'a, narzędzie
nie zamyka, bo nie wie, czy PR wszedł do gałęzi (np. czeka w kolejce merge'a), tylko ostrzega ``UWAGA: GitHub nie
podał commitu merge'a, nie zamknięto #N, zamknij ręcznie``. Każdy błąd przy zamykaniu (``gh`` z błędem albo po
czasie, odpowiedź bez stanu issue) kończy się ostrzeżeniem ``UWAGA: nie zamknięto #N, zamknij ręcznie``. Każde z tych
ostrzeżeń stoi w linii ``SCAL OK`` z kodem 0, bo PR jest już scalony. Z ``--bez-merge`` tylko czyta, niczego nie
zamyka, a linia podaje ``po merge'u zamknie: #N`` (a zamiast „nie zamknięto …” ostrzeżenia ``nie sprawdzono …``).

Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony (albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA
commitu merge'a i bazy, z którą sprawdziła scalenie, a gdy test scalenia biegł albo został pominięty, także jego
wynik. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101).

Dwa tryby służą recenzentowi (skill ``przeglad``, tryb recenzenta) i niczego nie scalają. ``--przeglad`` drukuje
kontekst przeglądu: pełny SHA HEAD PR, bazę i merge-base z nią, ``git diff --stat`` i zmienione pliki od merge-base,
wynik ``tools/skille_dla_zmiany.py`` z HEAD PR liczony od merge-base (w kopii commitu HEAD, więc ``pilnuje:`` skilli
jest z PR) i poprzednie werdykty PR w kolejności utworzenia, każdy z datą, autorem, dwiema pierwszymi liniami i tym,
czy dotyczy HEAD (``PASS`` poza regułami ``--werdykt`` z dopiskiem). Gdy ostatni werdykt jest dla innego commitu,
linia ``RUNDA`` podaje polecenie diffu od niego do HEAD. Linia ``CI`` podaje stan ``Required CI status`` na HEAD
z rollupu checków: ``success`` znaczy, że polecenia z linii ``LICZY CI`` przeszły (``tools/plan_ci.py``), więc ich
logów nie trzeba czytać, a zadania innych workflowów, które jeszcze biegną albo padły, wymienia osobno, bo gotowość
czeka i na nie; ``pending``, gdy Required jeszcze się nie skończył, a któreś zadanie biegnie, także zanim Required się
zacznie; ``failure`` z padłymi zadaniami runu Required i poleceniem ``gh run view <run> --log-failed``; ``brak``, gdy
CI na HEAD nie biegło. Kończy się linią ``PRZEGLĄD OK | #N <sha>``.

``--werdykt <plik>`` publikuje plik jako komentarz PR (``gh pr comment --body-file``), gdy przechodzi te same reguły
co zgoda przy merge'u: pierwsza niepusta linia
to ``WERDYKT: PASS <SHA>`` albo ``WERDYKT: FAIL <SHA>`` z pełnym SHA bieżącego HEAD PR, druga to ``Znaleziska: N
(Ważne a, Drobne b)`` z ``N = a + b``, ``PASS`` ma zero Ważnych, ``FAIL`` co najmniej jedno, a Drobnych jest
najwyżej trzy. Inaczej niczego nie publikuje i kończy się linią ``WERDYKT ODMOWA | #N | <przyczyny>``, w której
każda przyczyna mówi, co poprawić w pliku. Opublikowany werdykt kończy się linią ``WERDYKT OK | #N <sha> | <PASS
albo FAIL> | <adres komentarza>``.

    .venv/bin/python tools/scal_pr.py 336               # sprawdza i scala
    .venv/bin/python tools/scal_pr.py 336 --bez-merge   # tylko sprawdza
    .venv/bin/python tools/scal_pr.py 336 --przeglad    # kontekst dla recenzenta
    .venv/bin/python tools/scal_pr.py 336 --werdykt ~/.t3/notes/bieg/recenzje/336/runda-1.md
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
import json
from pathlib import Path
import os
import re
import statistics
import subprocess
import sys
import time
from typing import Literal
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

import czasy_ci
import potomne
import status_scalenia
from wplyw_zmiany import Context, Repository, run_all

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECK = "Required CI status"
RUN_ID = re.compile(r"/actions/runs/(\d+)/")
JOB_NOT_FAILED = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{40})")
FINDINGS_LINE = re.compile(r"Znaleziska: (\d+) \(Ważne (\d+), Drobne (\d+)\)")
MAX_MINOR = 3
SKILLS_FOR_CHANGE = Path("tools") / "skille_dla_zmiany.py"
SKILLS_TIMEOUT_S = 300
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CLEANUP = ROOT / "tools" / "sprzatanie.py"
TEMPLATE = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
CLEANUP_TIMEOUT_S = 300
# Test scalenia: plik testów w tej odległości od zmiany PR i od zmiany bazy (0 to plik zmieniony, 1 zależny wprost).
MERGE_TEST_DISTANCE = 1
# Suma czasów CI plików testu scalenia; Mac agenta liczy je ~5 razy szybciej (6.11.2026: 507 s w CI, 94 s na Macu).
MERGE_TEST_BUDGET_S = 180.0
MERGE_TEST_TIMEOUT_S = 300
MERGE_TEST_WORKERS = "4"  # workery xdist, chyba że ustawiono PYTEST_XDIST_AUTO_NUM_WORKERS, jak tools/szybko.py
FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)
LINK = "\x01"
NOT_TEXT = "\x00"
_REFERENCE = rf"(?:{LINK}|(?:[\w.-]+/[\w.-]+)?#\d+)"
FIXES = re.compile(rf"\s*Naprawia\s+({_REFERENCE}(?:\s*(?:,|\bi\b|\boraz\b)\s*{_REFERENCE})*)")
REFERENCE = re.compile(_REFERENCE)
BLOCKS = frozenset({"blockquote", "details", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "p", "pre", "summary", "table"})
LIST_OR_PARAGRAPH = frozenset({"li", "ol", "p", "ul"})
EMPHASIS = frozenset({"em", "strong"})
HIDDEN = frozenset({"code", "del", "s", "strike"})
VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    head: str
    base: str
    problems: tuple[str, ...]
    verdicts: tuple[dict[str, object], ...]
    repository: str
    body: str
    closed_by_github: frozenset[int]
    checks: tuple[dict[str, str | None], ...]


class _Refused(Exception):
    pass


def _gh(*arguments: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["gh", *arguments],
        input=stdin,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=status_scalenia.GITHUB_TIMEOUT_S,
        check=True,
    )
    return done.stdout


def _required(rollup: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Checki ``Required CI status`` z GitHub Actions (CheckRun z workflow), nie status commitu, który ustawi każdy z prawem zapisu."""

    return [check for check in rollup if check.get("name") == REQUIRED_CHECK and check.get("workflowName")]


def _ci_problem(rollup: list[dict[str, str | None]]) -> str | None:
    results = [(check.get("conclusion") if check.get("status") == "COMPLETED" else check.get("status")) or "?" for check in _required(rollup)]
    if not results:
        return f"CI: brak „{REQUIRED_CHECK}” z GitHub Actions na HEAD"
    failed = [result for result in results if result != "SUCCESS"]
    return f"CI: „{REQUIRED_CHECK}” {', '.join(failed)}" if failed else None


def _run_id(check: dict[str, str | None]) -> str | None:
    found = RUN_ID.search(check.get("detailsUrl") or "")
    return found[1] if found else None


def _ci_line(rollup: list[dict[str, str | None]], head: str) -> str:
    where = f"CI | {REQUIRED_CHECK}"
    required = _required(rollup)
    actions = [check for check in rollup if check.get("workflowName") and check.get("name") != REQUIRED_CHECK]
    red = [check for check in required if check.get("status") == "COMPLETED" and check.get("conclusion") != "SUCCESS"]
    runs = {run for check in red if (run := _run_id(check))}
    failed = sorted(
        {
            str(check.get("name"))
            for check in actions
            if check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED and (not red or _run_id(check) in runs)
        }
    )
    jobs = f"padłe zadania: {', '.join(failed)}" if failed else ""
    logs = f"logi padłych zadań: gh run view {' '.join(sorted(runs))} --log-failed" if runs else "logi padłych zadań"
    if red:
        why = jobs or f"bez padłego zadania, przyczynę podaje log „{REQUIRED_CHECK}”"
        return f"{where} failure na HEAD {head} | {why} | polecenia z linii LICZY CI nie są dowiedzione, czytaj tylko {logs}"
    if required and all(check.get("status") == "COMPLETED" for check in required):
        running_others = sorted({str(check.get("name")) for check in actions if check.get("status") != "COMPLETED"})
        failed_others = sorted(
            {str(check.get("name")) for check in actions if check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED}
        )
        states = [f"{state}: {', '.join(names)}" for state, names in (("w toku", running_others), ("padłe", failed_others)) if names]
        rest = f" | inne workflowy, na które czeka gotowość: {'; '.join(states)}" if states else ""
        return f"{where} success na HEAD {head} | polecenia z linii LICZY CI przeszły, ich logów nie przeszukuj{rest}"
    running = [check for check in [*required, *actions] if check.get("status") != "COMPLETED"]
    if running:
        return f"{where} pending na HEAD {head} (w toku: {len(running)}{f'; {jobs}' if jobs else ''}) | polecenia z linii LICZY CI jeszcze bez wyniku"
    return f"{where} brak na HEAD {head} | CI nie biegło na tym HEAD: jeszcze nie wystartowało po pushu albo PR ma konflikt z bazą"


def _body_problem(body: str) -> str | None:
    """Przyczyna odmowy, gdy opisowi brakuje nagłówka wzoru albo ma go nie po poprzednim; wzór to blok ``markdown``."""

    template = TEMPLATE.read_text(encoding="utf-8").partition("```markdown\n")[2].partition("\n```")[0]
    lines = [line.strip() for line in body.splitlines()]
    missing, after = [], 0
    for heading in (line for line in template.splitlines() if line.startswith("## ")):
        if heading in lines[after:]:
            after = lines.index(heading, after) + 1
        else:
            missing.append(heading)
    if not missing:
        return None
    return f"opis: brak {', '.join(f'„{heading}”' for heading in missing)} w kolejności wzoru {TEMPLATE.relative_to(ROOT).as_posix()}"


class _Stance(Enum):
    CONSENT = "PASS"
    OBJECTION = "FAIL"
    BROKEN_CONSENT = "PASS poza regułami --werdykt"


@dataclass(frozen=True)
class _Verdict:
    when: str
    login: str
    first_lines: tuple[str, ...]
    decision: Literal["PASS", "FAIL"] | None
    commit: str | None
    stance: _Stance | None
    problems: tuple[str, ...]


def _read_verdict(verdict: dict[str, object], head: str) -> _Verdict | None:
    if verdict["authorAssociation"] not in TRUSTED or verdict.get("state") == "PENDING":
        return None
    lines = _text_lines(verdict["body"])
    found = VERDICT_LINE.fullmatch(lines[0]) if lines else None
    changes_requested = verdict.get("state") == "CHANGES_REQUESTED"
    if found is None and not changes_requested:
        return None
    decision: Literal["PASS", "FAIL"] | None = None if found is None else "PASS" if found[1] == "PASS" else "FAIL"
    commit = found[2] if found else None
    problems = tuple(_verdict_file_problems(str(verdict["body"]), head)) if decision == "PASS" and commit == head else ()
    if changes_requested or (decision == "FAIL" and commit == head):
        stance: _Stance | None = _Stance.OBJECTION
    else:
        stance = None if commit != head else _Stance.BROKEN_CONSENT if problems else _Stance.CONSENT
    author = verdict.get("author")
    login = str(author.get("login", "?")) if isinstance(author, dict) else "?"
    when = str(verdict.get("createdAt") or verdict.get("submittedAt") or "?")
    return _Verdict(when, login, tuple(lines[:2]), decision, commit, stance, problems)


def _text_lines(body: object) -> list[str]:
    """Niepuste linie tekstu bez odstępów na brzegach: pierwsza to linia werdyktu, druga linia znalezisk."""

    return [line.strip() for line in str(body).splitlines() if line.strip()]


def _verdict_problem(pull: Pull) -> str | None:
    head, publish = pull.head, f"tools/scal_pr.py {pull.number} --werdykt PLIK"
    latest = None
    for verdict in pull.verdicts:
        read = _read_verdict(verdict, head)
        latest = read if read is not None and read.stance is not None else latest
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”; opublikuj werdykt przez {publish}"
    if latest.stance is _Stance.BROKEN_CONSENT:
        return f"werdykt: PASS dla {head[:7]} nie przechodzi reguł --werdykt ({'; '.join(latest.problems)}); popraw plik werdyktu i opublikuj go przez {publish}"
    return None if latest.stance is _Stance.CONSENT else f"werdykt: FAIL dla {head[:7]} bez nowszego „WERDYKT: PASS {head}”"


@dataclass(frozen=True)
class _Link:
    repository: str
    number: int
    issue: bool


class _Lines(HTMLParser):
    """Linie akapitów i punktów list w HTML opisu PR: ``LINK`` w miejscu linku do issue albo PR, ``NOT_TEXT`` w miejscu kodu, przekreślenia, obrazka i pola wyboru.

    Linię kończy ``<br>`` i początek albo koniec bloku z ``BLOCKS``, a każdy inny znacznik należy do linii. Linia
    trafia do ``lines`` tylko wtedy, gdy jej tekst zaczyna się wewnątrz samych ``LIST_OR_PARAGRAPH`` i ``EMPHASIS``,
    a najgłębszy z tych bloków to akapit albo punkt listy.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[list[str | _Link]] = []
        self._line: list[str | _Link] = []
        self._start: tuple[str, ...] | None = None
        self._open: list[str] = []
        self._link: _Link | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in BLOCKS or tag == "br":
            self._end_line()
        if tag in {"img", "input"} or (tag in HIDDEN and not self._hidden()):
            self._append(NOT_TEXT)
        elif tag == "a" and not self._hidden() and "issue-link" in (attributes.get("class") or "").split():
            _, owner, name, _, number = urlsplit(attributes.get("data-url") or "").path.split("/")
            self._link = _Link(f"{owner}/{name}", int(number), attributes.get("data-hovercard-type") == "issue")
        if tag not in VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKS:
            self._end_line()
        if tag in self._open:
            del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]
        if tag == "a" and self._link is not None:
            self._line.append(self._link)
            self._link = None

    def handle_data(self, data: str) -> None:
        if not self._hidden() and self._link is None:
            self._append(data)

    def _hidden(self) -> bool:
        return not HIDDEN.isdisjoint(self._open)

    def _append(self, part: str) -> None:
        if self._start is None and part.strip():
            self._start = tuple(self._open)
        self._line.append(part)

    def _end_line(self) -> None:
        blocks = [tag for tag in self._start or () if tag not in EMPHASIS]
        if blocks and blocks[-1] in {"p", "li"} and LIST_OR_PARAGRAPH.issuperset(blocks):
            self.lines.append(self._line)
        self._line, self._start = [], None
        if self._hidden():
            self._append(NOT_TEXT)  # kod albo przekreślenie przechodzi przez ``<br>`` na początek następnej linii


def fixed_issues(body: str, repository: str) -> tuple[int, ...]:
    """Numery issues ``repository`` z linii „Naprawia” opisu PR ``body`` wyrenderowanego przez GitHuba.

    Rzuca wyjątek, gdy GitHub opisu nie wyrenderował.
    """

    rendered = _gh("api", "markdown", "--input", "-", stdin=json.dumps({"text": body, "mode": "gfm", "context": repository}))
    if not rendered.strip():
        raise ValueError("GitHub zwrócił pusty HTML")
    parser = _Lines()
    parser.feed(rendered)
    parser.close()
    numbers: list[int] = []
    for line in parser.lines:
        listed = FIXES.match("".join(LINK if isinstance(part, _Link) else part for part in line))
        links = iter(part for part in line if isinstance(part, _Link))
        for reference in REFERENCE.finditer(listed[1] if listed else ""):
            if reference[0] != LINK:
                if "/" in reference[0]:
                    break
                continue
            link = next(links)
            if link.repository.casefold() != repository.casefold():
                break
            if link.issue and link.number not in numbers:
                numbers.append(link.number)
    return tuple(numbers)


def _pull(number: int) -> Pull:
    fields = (
        "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments,reviews,"
        "url,body,closingIssuesReferences"
    )
    pull = json.loads(_gh("pr", "view", str(number), "--json", fields))
    problems = []
    if pull["state"] != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull['state']}")
    if pull["isDraft"]:
        problems.append("PR jest szkicem")
    if pull["isCrossRepository"]:
        problems.append("PR z forka")
    problems += filter(None, [_ci_problem(pull["statusCheckRollup"]), _body_problem(pull["body"])])
    verdicts = [*pull["comments"], *pull["reviews"]]
    verdicts.sort(key=lambda verdict: verdict.get("createdAt") or verdict.get("submittedAt") or "")
    repository = "/".join(pull["url"].split("/")[3:5])
    closed_by_github = frozenset(
        issue["number"]
        for issue in pull["closingIssuesReferences"]
        if f"{issue['repository']['owner']['login']}/{issue['repository']['name']}".casefold() == repository.casefold()
    )
    return Pull(
        number,
        pull["title"],
        pull["headRefOid"],
        pull["baseRefName"],
        tuple(problems),
        tuple(verdicts),
        repository,
        pull["body"],
        closed_by_github,
        tuple(pull["statusCheckRollup"]),
    )


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=status_scalenia.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> tuple[str, str]:
    """SHA bazy, z którą scalenie przeszło, i dopisek linii ``SCAL OK`` o teście scalenia."""

    checked = status_scalenia.PullRequest(pull.number, pull.title, pull.head)
    base = status_scalenia.fetch(pull.base, [checked])
    problems = [*pull.problems, *filter(None, [_verdict_problem(pull)])]
    if problems:
        raise _Refused("; ".join(problems))
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = status_scalenia.merge_verdict(copy, where, base, None, checked)
        if verdict.state != "success":
            raise _Refused(verdict.description)
        return base, _merge_test(copy, where, base, pull.head)


def _changed(fork: str, commit: str) -> frozenset[str]:
    return frozenset(filter(None, _git("diff", "-z", "--name-only", "--no-renames", fork, commit).split("\0")))


def _merge_test(copy: Path, where: str, base: str, head: str) -> str:
    """Dopisek linii ``SCAL OK`` o teście scalenia w ``copy`` ze scalonym drzewem ``base`` i ``head``; pusty, gdy test
    nie był potrzebny. Rzuca ``_Refused``, gdy test pada na scaleniu, a na samej bazie nie, albo nie daje wyniku w
    limicie czasu."""

    fork = _git("merge-base", base, head).strip()
    base_changed = _changed(fork, base)
    if not base_changed:
        return ""
    pull_changed = _changed(fork, head)
    if full := run_all(pull_changed | base_changed, Context.TESTS):
        return f" | test scalenia pominięty: zmiana {', '.join(full)} dotyczy każdego testu"
    repository = Repository.scan(copy)
    pull_impact, base_impact = repository.impact(pull_changed), repository.impact(base_changed)
    tests = sorted(
        test
        for test in set(pull_impact.tests) & set(base_impact.tests)
        if max(pull_impact.distances[test], base_impact.distances[test]) <= MERGE_TEST_DISTANCE
    )
    if not tests:
        return ""
    names = ", ".join(tests)
    times = czasy_ci.z_mainu(czasy_ci.katalog_checkoutu(ROOT), odswiez_po_s=czasy_ci.ODSWIEZ_S)
    measured = times.pliki(czasy_ci.TOR_LOKALNY)
    if not measured:
        why = times.blad or f"tor {czasy_ci.TOR_LOKALNY} bez plików testów"
        return f" | test scalenia pominięty: brak czasów CI ({why}), plików testów: {len(tests)}"
    cost = sum(measured.get(test, statistics.median(measured.values())) for test in tests)
    if cost > MERGE_TEST_BUDGET_S:
        return f" | test scalenia pominięty: ~{cost:.0f} s w CI ponad limit {MERGE_TEST_BUDGET_S:.0f} s, plików testów: {len(tests)}"
    print(f"== test scalenia z {where} (~{cost:.0f} s w CI): {names}", flush=True)
    started = time.monotonic()
    failed = _failed_tests(copy, tests, f"test scalenia z {where}")
    if not failed:
        return f" | test scalenia: {names} przechodzą ({time.monotonic() - started:.0f} s)"
    # Czerwony ``main`` nie blokuje merge'ów (ADR 0020): porażka, która jest już na samej bazie, nie jest winą PR.
    potomne.run(["git", "read-tree", "-u", "--reset", base], cwd=copy).check_returncode()
    on_base = [test for test in tests if (copy / test).is_file() and any(name.partition("::")[0] == test for name in failed)]
    print(f"== te same pliki na samym {where}: {', '.join(on_base) or 'brak'}", flush=True)
    failed_on_base = _failed_tests(copy, on_base, f"test scalenia na samym {where}") if on_base else []
    pull_failed = [name for name in failed if name not in failed_on_base]
    already = [name for name in failed if name in failed_on_base]
    if pull_failed:
        also = f" (na samym {where} pada też: {', '.join(already)})" if already else ""
        raise _Refused(f"test scalenia z {where} pada: {', '.join(pull_failed)}{also}")
    return f" | test scalenia: {names} bez porażek przez PR, a na samym {where} pada już: {', '.join(already)} ({time.monotonic() - started:.0f} s)"


def _failed_tests(copy: Path, tests: Sequence[str], what: str) -> list[str]:
    """Testy z ``tests``, które padły pytestem w ``copy``, po kolei z wyjścia. Rzuca ``_Refused``, gdy pytest nie daje
    wyniku w limicie czasu albo pada, nie nazywając testu (wtedy z przyczyną ze stderr, np. nieznana opcja)."""

    workers = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", MERGE_TEST_WORKERS)
    try:
        done = potomne.run(
            [sys.executable, "-m", "pytest", "-q", "-rfE", "-n", "auto", *tests],
            cwd=copy,
            env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": workers},
            timeout=MERGE_TEST_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise _Refused(f"{what} bez wyniku po {MERGE_TEST_TIMEOUT_S} s: {', '.join(tests)}") from None
    if not done.returncode:
        return []
    print(done.stdout.rstrip(), done.stderr.rstrip(), sep="\n", flush=True)
    if failed := list(dict.fromkeys(FAILED_TEST.findall(done.stdout))):
        return failed
    lines = (done.stderr.strip() or done.stdout.strip()).splitlines()
    reason = next((line.strip() for line in reversed(lines) if "error" in line.lower()), lines[-1].strip() if lines else "bez wyjścia")
    raise _Refused(f"{what} pada: pytest kod {done.returncode}: {reason}")


def _close_fixed(pull: Pull, *, merged: bool, merge_commit: str | None) -> str:
    """Zamyka otwarte issues z linii „Naprawia” z komentarzem o merge'u, a przed merge'em tylko je podaje."""

    if "Naprawia" not in pull.body:
        return ""
    unchecked = "nie zamknięto issues z „Naprawia”, zamknij je ręcznie" if merged else "nie sprawdzono „Naprawia”"
    try:
        default_branch = str(json.loads(_gh("repo", "view", pull.repository, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"])
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie podał domyślnej gałęzi, {unchecked}"
    if pull.base != default_branch:
        return f" | bez zamykania „Naprawia”: baza {pull.base} to nie {default_branch}"
    try:
        fixes = [number for number in fixed_issues(pull.body, pull.repository) if number not in pull.closed_by_github]
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie wyrenderował opisu PR, {unchecked}"
    closes = merged and merge_commit is not None
    open_issues, failed = [], []
    for number in fixes:
        try:
            if json.loads(_gh("api", f"repos/{pull.repository}/issues/{number}"))["state"] != "open":
                continue
            if closes:
                comment = f"Naprawione przez #{pull.number}, scalone jako {merge_commit}."
                _gh("issue", "close", str(number), "--repo", pull.repository, "--comment", comment)
            open_issues.append(f"#{number}")
        except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
            failed.append(f"#{number}")
    if merged and not closes:
        missed = [*open_issues, *failed]
        return f" | UWAGA: GitHub nie podał commitu merge'a, nie zamknięto {', '.join(missed)}, zamknij ręcznie" if missed else ""
    done, warning = ("zamknięte", "UWAGA: nie zamknięto {}, zamknij ręcznie") if merged else (
        "po merge'u zamknie", "UWAGA: nie sprawdzono {}"
    )
    parts = [f"{done}: {', '.join(open_issues)}"] if open_issues else []
    parts += [warning.format(", ".join(failed))] if failed else []
    return "".join(f" | {part}" for part in parts)


def _merge_commit(number: int) -> str | None:
    """SHA commitu merge'a scalonego PR albo ``None``, gdy GitHub go nie podał."""

    try:
        return str(json.loads(_gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]["oid"])
    except Exception:  # noqa: BLE001 - PR jest już scalony, a brak SHA podaje linia SCAL OK
        return None


def _clean_up() -> str:
    if not CLEANUP.exists():
        return f"sprzątanie pominięte: brak {CLEANUP.relative_to(ROOT).as_posix()}"
    try:
        done = potomne.run([sys.executable, str(CLEANUP)], cwd=ROOT, timeout=CLEANUP_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return f"UWAGA: sprzątanie przerwane po {CLEANUP_TIMEOUT_S} s, uruchom je ponownie"
    result = done.stdout.rstrip().rpartition("\n")[2]
    return f"sprzątanie: {result or f'kod {done.returncode}'}"


def _git(*arguments: str) -> str:
    done = potomne.run(["git", *arguments], cwd=ROOT, timeout=status_scalenia.GITHUB_TIMEOUT_S)
    done.check_returncode()
    return done.stdout


def _skills_for_change(head: str, fork: str) -> list[str]:
    """Wynik ``tools/skille_dla_zmiany.py`` z kopii commitu ``head`` od ``fork``; ostatnia linia to zawsze ``SKILLE VERIFY``."""

    unknown = "SKILLE VERIFY: nieznane ({})"
    with potomne.commit_copy(ROOT, head) as copy:
        if not (copy / SKILLS_FOR_CHANGE).is_file():
            return [unknown.format(f"HEAD PR nie ma {SKILLS_FOR_CHANGE.as_posix()}")]
        try:
            done = potomne.run([sys.executable, str(copy / SKILLS_FOR_CHANGE), fork], cwd=copy, timeout=SKILLS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return [unknown.format(f"{SKILLS_FOR_CHANGE.as_posix()} przerwane po {SKILLS_TIMEOUT_S} s")]
    lines = done.stdout.splitlines()
    if not lines or not lines[-1].startswith("SKILLE VERIFY: "):
        detail = (done.stderr.strip().splitlines() or [f"kod {done.returncode}"])[-1]
        lines.append(unknown.format(f"{SKILLS_FOR_CHANGE.as_posix()}: {detail}"))
    return lines


def _verdict_history(pull: Pull) -> list[str]:
    """Linie werdyktów PR w kolejności utworzenia i linia ``RUNDA`` o ostatnim z nich."""

    shown, last, failed = [], None, set()
    for verdict in filter(None, (_read_verdict(verdict, pull.head) for verdict in pull.verdicts)):
        if verdict.decision is None or verdict.commit is None:
            shown.append(f"WERDYKT | {verdict.when} {verdict.login} | recenzja CHANGES_REQUESTED | {' | '.join(verdict.first_lines)}")
            continue
        last = (verdict.decision, verdict.commit)
        if verdict.decision == "FAIL":
            failed.add(verdict.commit)
        which = "inny commit" if verdict.commit != pull.head else f"HEAD, {verdict.stance.value}" if verdict.stance is _Stance.BROKEN_CONSENT else "HEAD"
        shown.append(f"WERDYKT | {verdict.when} {verdict.login} | {which} | {' | '.join(verdict.first_lines)}")
    if last is None:
        return [*shown, "RUNDA | 1: PR nie ma werdyktu"]
    rounds = f"rund z FAIL: {len(failed)}, ostatni werdykt {last[0]} dla {last[1][:7]}"
    if last[1] == pull.head:
        return [*shown, f"RUNDA | {rounds}, czyli dla tego HEAD"]
    return [*shown, f"RUNDA | {rounds}; zmiana od niego: git diff {last[1]} {pull.head}"]


def _review_context(number: int) -> int:
    pull = _pull(number)
    base = status_scalenia.fetch(pull.base, [status_scalenia.PullRequest(pull.number, pull.title, pull.head)])
    fork = _git("merge-base", base, pull.head).strip()
    files = _git("diff", "--name-only", "--no-renames", fork, pull.head).splitlines()
    print(f"PRZEGLĄD | #{pull.number} {pull.title} | HEAD {pull.head} | baza {pull.base} {base} | merge-base {fork}")
    print(f"ZMIANA | git diff --stat {fork} {pull.head}")
    print(_git("diff", "--stat", fork, pull.head).rstrip())
    print(f"PLIKI | {len(files)}", *files, sep="\n")
    print(f"SKILLE | {SKILLS_FOR_CHANGE.as_posix()} {fork} na HEAD PR", *_skills_for_change(pull.head, fork), sep="\n")
    print(_ci_line(list(pull.checks), pull.head))
    print(*_verdict_history(pull), sep="\n")
    print(f"PRZEGLĄD OK | #{pull.number} {pull.head[:7]}")
    return 0


def _verdict_file_problems(text: str, head: str) -> list[str]:
    """Co poprawić w pliku werdyktu dla ``head``; pusta lista, gdy obie pierwsze linie są zgodne z ``--help``."""

    lines = _text_lines(text)
    first, second = [*lines, "", ""][:2]
    verdict = VERDICT_LINE.fullmatch(first)
    findings = FINDINGS_LINE.fullmatch(second)
    problems = []
    if verdict is None:
        problems.append(f"pierwsza linia „{first}” to nie „WERDYKT: PASS {head}” ani „WERDYKT: FAIL {head}”")
    elif verdict[2] != head:
        problems.append(f"werdykt dla {verdict[2][:7]}, a HEAD PR to {head}: przejrzyj git diff {verdict[2]} {head} i wpisz SHA HEAD")
    if findings is None:
        return [*problems, f"druga linia „{second}” to nie „Znaleziska: N (Ważne a, Drobne b)”"]
    total, major, minor = map(int, findings.groups())
    if total != major + minor:
        problems.append(f"Znaleziska: {total}, a Ważne {major} i Drobne {minor} dają {major + minor}")
    if minor > MAX_MINOR:
        problems.append(f"Drobne {minor}: podaj najwyżej {MAX_MINOR}, najważniejsze")
    if verdict is not None and (verdict[1] == "FAIL") != (major > 0):
        problems.append(f"{verdict[1]} z Ważne {major}: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych")
    return problems


def _publish_verdict(number: int, path: Path) -> int:
    pull = _pull(number)
    text = path.read_text(encoding="utf-8")
    if problems := _verdict_file_problems(text, pull.head):
        print(f"WERDYKT ODMOWA | #{pull.number} | {'; '.join(problems)}; popraw {path} i uruchom ponownie")
        return 1
    url = _gh("pr", "comment", str(number), "--body-file", str(path)).strip()
    print(f"WERDYKT OK | #{pull.number} {pull.head[:7]} | {_text_lines(text)[0].split()[1]} | {url}")
    return 0


def _merge(number: int, *, merge: bool) -> int:
    pull = _pull(number)
    where = f"#{pull.number} {pull.head[:7]}"
    try:
        base, merge_test = _check(pull)
        if merge and _remote_base(pull.base) != base:
            raise _Refused(f"{pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
    except _Refused as refusal:
        print(f"SCAL ODMOWA | {where} | {refusal}")
        return 1
    if not merge:
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge){merge_test}{_close_fixed(pull, merged=False, merge_commit=None)}")
        return 0
    _gh("pr", "merge", str(number), "--merge", "--match-head-commit", pull.head)
    merge_commit = _merge_commit(number)
    closed = _close_fixed(pull, merged=True, merge_commit=merge_commit)
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {(merge_commit or '?')[:7]} (baza {base[:7]}){merge_test}{closed} | {_clean_up()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("numer", type=int, help="Numer PR.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bez-merge", action="store_true", help="Sprawdź gotowość, ale nie scalaj.")
    mode.add_argument("--przeglad", action="store_true", help="Wydrukuj recenzentowi kontekst przeglądu PR.")
    mode.add_argument("--werdykt", type=Path, metavar="PLIK", help="Sprawdź plik werdyktu i opublikuj go jako komentarz PR.")
    args = parser.parse_args(argv)
    label = "PRZEGLĄD" if args.przeglad else "WERDYKT" if args.werdykt else "SCAL"
    try:
        if args.przeglad:
            return _review_context(args.numer)
        if args.werdykt:
            return _publish_verdict(args.numer, args.werdykt)
        return _merge(args.numer, merge=not args.bez_merge)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"{label} FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"{label} FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
