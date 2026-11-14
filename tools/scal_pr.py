"""Jedyna droga merge'a PR przez agenta: sprawdza gotowość (CI, werdykt PASS, opis) tuż przed gh pr merge; użyj zamiast gołego merge'a.

Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. najnowszy run workflow ``CI`` na HEAD PR (największy identyfikator runu z ``detailsUrl`` jego checków) skończył
   się, a jego check ``Required CI status`` sukcesem (jak w rulesecie ``main``: CheckRun z workflow, nie status
   commitu, który może ustawić każdy z prawem zapisu); run bez tego checku jeszcze trwa, bo GitHub tworzy go po
   zadaniach z jego ``needs:``, run z zadaniem w toku też (ponowienie), a checki starszych runów na tym HEAD, na
   przykład sprzed zamknięcia i otwarcia PR, się nie liczą, ani czerwone, ani zielone (``stan_pr.latest_ci_run``);
   check workflow ``CI`` bez identyfikatora runu w ``detailsUrl`` to odmowa;
3. najnowszy werdykt dla HEAD PR to ``PASS`` w postaci, którą publikuje ``--werdykt`` (niżej);
4. opis PR ma każdy nagłówek ``##`` wzoru z ``.agents/skills/pr/SKILL.md``, każdy jako osobną linię i w kolejności
   wzoru, więc każdy PR ma te same sekcje, a sekcja dopisana do wzoru od razu obowiązuje; w wątku z szablonem
   werdyktu opis po ``FAIL`` z Ważnym i przy naprawie czerwonego `main` ma też sekcję ``## Korzeń``, a każdy kod
   ``NOWY`` z werdyktów stoi na liście korzeni na HEAD (bramka korzenia, ``bramka_korzenia``, niżej);
5. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``werdykt_scalenia.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu);
6. na tym scalonym drzewie przechodzi test scalenia, gdy jest potrzebny i mieści się w limicie (niżej).

Mutacje zmienionych linii nie biegną na PR i nie czeka na nie: biegną nocą na ``main`` (ADR 0021,
``tools/mutacje_nocne.py``).

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–4 sprawdza razem i podaje wszystkie przyczyny; warunki 5 i 6 trwają dłużej, więc biegną dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia
``tools/sprzatanie.py`` i podaje ostatnią linię jego raportu: bez ``--usun`` sprzątanie niczego nie
usuwa, tylko mówi, które lokalne gałęzie i worktree można usunąć. Sprzątanie, które przekroczy czas, kończy się
ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony.

Po merge'u do ``main`` linia ``CI MAIN`` przed ``SCAL OK`` mówi, który run CI rozstrzyga o merge'u (``github.ROZSTRZYGA``):
nowszy push na `main` anuluje run commitu merge'a, gdy ten czeka za trwającym, i wtedy rozstrzyga run późniejszego
commitu. Linia podaje run commitu merge'a i to, czy już go anulowano, a bez niego polecenie ``gh run list``, które
pokaże runy pushu na `main`. Obserwację PR zostaw do zielonego `main` z tym merge'em albo do komentarza czerwonego
`main` w PR, który ``tools/ci/zgloszenia_ci.py`` pisze w każdym PR, o którego merge'u rozstrzyga czerwony run.

Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony (albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA
commitu merge'a i bazy, z którą sprawdziła scalenie, a gdy test scalenia biegł albo został pominięty, także jego
wynik. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Werdykt (``--werdykt``) i merge (także ``--bez-merge``) sądzi kod ``origin/<baza PR>`` tuż po pobraniu bazy, nie kod
checkoutu, z którego je uruchomiono: reguły werdyktu, bramki korzenia i wzoru opisu żyją w ``tools/`` i w plikach
skilli, a checkout gałęzi PR albo stary checkout `main` może mieć ich starszą albo zmienioną wersję (#1573). Checkout,
którego HEAD to ten commit bazy, bez zmian w plikach śledzonych przez Gita, sądzi sam. Każdy inny uruchamia to samo
polecenie z odłączonej kopii tego commitu (``potomne.commit_copy``) tym samym Pythonem, z tym samym katalogiem
roboczym, i kończy się jej kodem, a linia ``SĘDZIA`` przed jej wyjściem mówi, z którego commitu są reguły. PR, który
sam zmienia te reguły, sądzi więc wersja z bazy, a jego zmiana obowiązuje od jego merge'a. Kopia, której baza
w ``origin`` przesunęła się, zanim pobrała ją ponownie, nie uruchamia następnej kopii, tylko odmawia z poleceniem, by
uruchomić ponownie. ``--przeglad`` biegnie w checkoucie, z którego go uruchomiono.

Z ``--status`` narzędzie niczego nie scala, tylko ustawia warunki 1–4 jako status commita ``Werdykt i bramka``
(``github.WERDYKT_I_BRAMKA``) na HEAD PR do `main`: ``success`` albo ``failure`` z przyczynami odmowy w opisie, a linia
``STATUS`` podaje go w całości; sądzi go kod bazy, jak werdykt i merge. Warunków 5 i 6 nie liczy, bo uruchamiają kod PR
(ruff, mypy i pytest na scalonym drzewie), a status ustawia workflow ``.github/workflows/werdykt-i-bramka.yml`` tokenem
z prawem zapisu statusów; scalenie z ruff i mypy pokazuje status ``scalenie z main``. PR zamknięty albo do innej gałęzi
niż `main` statusu nie dostaje (linia ``STATUS POMINIĘTY``), więc status scalonego HEAD zostaje taki, jak w chwili
merge'a, i po fakcie pokazuje merge bez zielonego statusu. Status tylko raportuje, bo żaden ruleset go nie wymaga
(ADR 0036, „Status w Actions”). Kod 0 znaczy, że status jest ustawiony albo pominięty, a 1, że go nie ustawiono.

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import bramka_korzenia
import github
import kontekst_przegladu
import naprawia
import potomne
import rejestr_korzeni
from repo import MAIN, REMOTE, ROOT
import repo
import stan_pr
from stan_pr import Pull
import szablon_werdyktu
import testy_scalenia
import werdykt_pr
import werdykt_scalenia

CLEANUP = ROOT / "tools" / "sprzatanie.py"
TEMPLATE = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
CLEANUP_TIMEOUT_S = 300
# Zmienna środowiska kopii bazy, którą uruchamia ``_judged_from_base``; kopia zdejmuje ją od razu, więc jej procesy
# potomne (test scalenia z testami tego narzędzia) jej nie dziedziczą, a ``scal_pr.py`` bazy, który jej nie zna, ją pomija.
FROM_BASE_COPY = "SCAL_PR_Z_KOPII_BAZY"
EXAMPLES = """\
    .venv/bin/python tools/scal_pr.py 336               # sprawdza i scala
    .venv/bin/python tools/scal_pr.py 336 --bez-merge   # tylko sprawdza
    .venv/bin/python tools/scal_pr.py 336 --przeglad    # kontekst dla recenzenta
    python3 tools/scal_pr.py 336 --status               # workflow werdykt-i-bramka.yml: status bez merge'a
    .venv/bin/python tools/scal_pr.py 336 --werdykt ~/.t3/notes/bieg/recenzje/336/runda-1.md
"""


class _Refused(Exception):
    pass


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


def _problems(pull: Pull) -> list[str]:
    """Przyczyny odmowy z warunków 1–4; baza i HEAD PR są już pobrane z ``origin``."""

    problems = []
    if pull.state != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull.state}")
    if pull.draft:
        problems.append("PR jest szkicem")
    if pull.from_fork:
        problems.append("PR z forka")
    template = werdykt_pr.deployment(pull.base, szablon_werdyktu.ADR)
    consent = [stan_pr.ci_problem(pull), _body_problem(pull.body), werdykt_pr.consent_problem(pull, template)]
    return [*problems, *filter(None, consent), *bramka_korzenia.problems(pull, werdykt_pr.deployment(pull.base, bramka_korzenia.MARKER))]


def _remote_base(base: str) -> str:
    listed = repo.run_git(ROOT, "ls-remote", REMOTE, f"refs/heads/{base}", timeout=github.LIMIT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _judged_from_base(pull: Pull, base: str, label: str, argv: list[str], *, from_copy: bool) -> int | None:
    """``None``, gdy ten checkout to czysty checkout ``base`` (SHA ``origin/<baza PR>`` tuż po pobraniu) i sądzi sam;
    inaczej kod wyjścia polecenia ``argv`` uruchomionego z kopii ``base``, a w kopii (``from_copy``) odmowa."""

    head = repo.git(ROOT, "rev-parse", "HEAD").strip()
    changed = repo.run_git(ROOT, "diff", "--quiet", "HEAD").returncode != 0
    if head == base and not changed:
        return None
    if from_copy:
        print(f"{label} ODMOWA | #{pull.number} | {pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
        return 1
    here = f"{head[:7]}{' ze zmianami' if changed else ''}"
    print(f"SĘDZIA | #{pull.number} | reguły z {REMOTE}/{pull.base} {base[:7]}, nie z checkoutu {here}: biegnę z kopii tego commitu", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        command = [sys.executable, str(copy / "tools" / "scal_pr.py"), *argv]
        environment = {**os.environ, FROM_BASE_COPY: "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        return potomne.run(command, cwd=Path.cwd(), env=environment, echo=True).returncode


def _check(pull: Pull, base: str) -> str:
    """Dopisek linii ``SCAL OK`` o teście scalenia z bazą ``base`` (SHA ``origin/<baza PR>``)."""

    checked = werdykt_scalenia.PullRequest(pull.number, pull.title, pull.head)
    if problems := _problems(pull):
        raise _Refused("; ".join(problems))
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = werdykt_scalenia.merge_verdict(copy, where, base, None, checked)
        if verdict.state != "success":
            raise _Refused(verdict.description)
        return testy_scalenia.merge_test(copy, where, base, pull.head)


def _merge_commit(number: int) -> str | None:
    """SHA commitu merge'a scalonego PR albo ``None``, gdy GitHub go nie podał."""

    try:
        return str(json.loads(github.gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]["oid"])
    except Exception:  # noqa: BLE001 - PR jest już scalony, a brak SHA podaje linia SCAL OK
        return None


def _main_ci(merge_commit: str | None) -> str:
    """Linia ``CI MAIN``: który run CI rozstrzyga o merge'u do `main` i co wiadomo o runie commitu merge'a."""

    listing = f"gh run list --workflow {github.CI_WORKFLOW} --event push --branch {MAIN}"
    try:
        runs = json.loads(github.gh(*listing.split()[1:], "--commit", merge_commit, "--json", "databaseId,url,conclusion")) if merge_commit else []
    except (subprocess.SubprocessError, OSError, ValueError):
        runs = []
    if not runs:
        own = f"runu commitu merge'a jeszcze nie ma, runy pokaże {listing}"
    elif runs[0]["conclusion"] == "cancelled":
        own = f"run commitu merge'a {runs[0]['databaseId']} anulowany, więc rozstrzyga run późniejszego commitu z {listing}"
    else:
        own = f"run commitu merge'a {runs[0]['databaseId']} {runs[0]['url']}, o ile nowszy push nie anuluje go, zanim ruszy"
    return f"CI MAIN | {(merge_commit or '?')[:7]} | {github.ROZSTRZYGA}: {own} | obserwuj PR do zielonego main z tym merge'em albo do komentarza czerwonego main w PR"


def _clean_up() -> str:
    try:
        done = potomne.run([sys.executable, str(CLEANUP)], cwd=ROOT, timeout=CLEANUP_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return f"UWAGA: sprzątanie przerwane po {CLEANUP_TIMEOUT_S} s, uruchom je ponownie"
    result = done.stdout.rstrip().rpartition("\n")[2]
    return f"sprzątanie: {result or f'kod {done.returncode}'}"


def _publish_verdict(pull: Pull, path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    deployed = werdykt_pr.deployment(pull.base, szablon_werdyktu.ADR)
    if problems := werdykt_pr.publish_problems(text, pull, deployed):
        print(f"WERDYKT ODMOWA | #{pull.number} | {'; '.join(problems)}; popraw {path} i uruchom ponownie")
        return 1
    url = github.gh("pr", "comment", str(pull.number), "--body-file", str(path)).strip()
    weeds = rejestr_korzeni.after_verdict(pull.number, text, pull.base, deployed, pull.repository)
    print(f"WERDYKT OK | #{pull.number} {pull.head[:7]} | {werdykt_pr.text_lines(text)[0].split()[1]} | {url}{weeds}")
    return 0


def _skipped_status(pull: Pull) -> str | None:
    """Przyczyna, dla której ``--status`` nie ustawia statusu PR ``pull``: zamknięty albo do innej gałęzi niż `main`."""

    if pull.state != "OPEN":
        return f"PR {pull.state}, więc status HEAD zostaje z chwili zamknięcia"
    if pull.base != MAIN:
        return f"PR do {pull.base}, a status dostają PR-y do {MAIN}"
    return None


def _publish_status(pull: Pull) -> int:
    """Warunki 1–4 jako status commita ``github.WERDYKT_I_BRAMKA`` na HEAD otwartego PR do `main`."""

    where = f"#{pull.number} {pull.head[:7]}"
    problems = _problems(pull)
    state, description = ("failure", "; ".join(problems)) if problems else ("success", "warunki 1–4 tools/scal_pr.py spełnione")
    if error := github.ustaw_status(pull.head, github.WERDYKT_I_BRAMKA, state, description):
        print(f"STATUS FAIL | {where} | {state} niewysłany: {error}")
        return 1
    print(f"STATUS {state} | {where} | {description}")
    return 0


def _merge(pull: Pull, base: str, *, merge: bool) -> int:
    where = f"#{pull.number} {pull.head[:7]}"
    try:
        merge_test = _check(pull, base)
        if merge and _remote_base(pull.base) != base:
            raise _Refused(f"{pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
    except (_Refused, testy_scalenia.Refused) as refusal:
        print(f"SCAL ODMOWA | {where} | {refusal}")
        return 1
    if not merge:
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge){merge_test}{naprawia.close_fixed(pull, merged=False, merge_commit=None)}")
        return 0
    github.gh("pr", "merge", str(pull.number), "--merge", "--match-head-commit", pull.head)
    merge_commit = _merge_commit(pull.number)
    closed = naprawia.close_fixed(pull, merged=True, merge_commit=merge_commit)
    cleaned = _clean_up()
    if pull.base == MAIN:
        print(_main_ci(merge_commit))
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {(merge_commit or '?')[:7]} (baza {base[:7]}){merge_test}{closed} | {cleaned}")
    return 0


def main(argv: list[str] | None = None) -> int:
    rules = (__doc__, testy_scalenia.__doc__, werdykt_pr.__doc__, bramka_korzenia.__doc__, rejestr_korzeni.__doc__, naprawia.__doc__, kontekst_przegladu.__doc__)
    parser = argparse.ArgumentParser(
        description="\n".join(str(part).strip("\n") + "\n" for part in rules), epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("numer", type=int, help="Numer PR.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bez-merge", action="store_true", help="Sprawdź gotowość, ale nie scalaj.")
    mode.add_argument("--przeglad", action="store_true", help="Wydrukuj recenzentowi kontekst przeglądu PR.")
    mode.add_argument("--werdykt", type=Path, metavar="PLIK", help="Sprawdź plik werdyktu i opublikuj go jako komentarz PR.")
    mode.add_argument("--status", action="store_true", help=f"Ustaw warunki 1–4 jako status „{github.WERDYKT_I_BRAMKA}” na HEAD PR, bez merge'a.")
    from_copy = os.environ.pop(FROM_BASE_COPY, None) is not None
    given = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(given)
    label = "PRZEGLĄD" if args.przeglad else "WERDYKT" if args.werdykt else "STATUS" if args.status else "SCAL"
    try:
        if args.przeglad:
            return kontekst_przegladu.print_context(args.numer)
        pull = stan_pr.pull(args.numer)
        if args.status and (skipped := _skipped_status(pull)):
            print(f"STATUS POMINIĘTY | #{pull.number} {pull.head[:7]} | {skipped}")
            return 0
        base = werdykt_scalenia.fetch(pull.base, [werdykt_scalenia.PullRequest(pull.number, pull.title, pull.head)])
        if (judged := _judged_from_base(pull, base, label, given, from_copy=from_copy)) is not None:
            return judged
        if args.werdykt:
            return _publish_verdict(pull, args.werdykt)
        if args.status:
            return _publish_status(pull)
        return _merge(pull, base, merge=not args.bez_merge)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"{label} FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"{label} FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
