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
   wzoru, więc każdy PR ma te same sekcje, a sekcja dopisana do wzoru od razu obowiązuje;
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

Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony (albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA
commitu merge'a i bazy, z którą sprawdziła scalenie, a gdy test scalenia biegł albo został pominięty, także jego
wynik. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
import kontekst_przegladu
import naprawia
import potomne
from repo import REMOTE, ROOT
import repo
import stan_pr
from stan_pr import Pull
import testy_scalenia
import werdykt_pr
import werdykt_scalenia

CLEANUP = ROOT / "tools" / "sprzatanie.py"
TEMPLATE = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
CLEANUP_TIMEOUT_S = 300
EXAMPLES = """\
    .venv/bin/python tools/scal_pr.py 336               # sprawdza i scala
    .venv/bin/python tools/scal_pr.py 336 --bez-merge   # tylko sprawdza
    .venv/bin/python tools/scal_pr.py 336 --przeglad    # kontekst dla recenzenta
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
    """Przyczyny odmowy z warunków 1–4."""

    problems = []
    if pull.state != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull.state}")
    if pull.draft:
        problems.append("PR jest szkicem")
    if pull.from_fork:
        problems.append("PR z forka")
    return [*problems, *filter(None, [stan_pr.ci_problem(pull.checks), _body_problem(pull.body), werdykt_pr.consent_problem(pull.verdicts, pull.head, pull.number)])]


def _remote_base(base: str) -> str:
    listed = repo.run_git(ROOT, "ls-remote", REMOTE, f"refs/heads/{base}", timeout=github.LIMIT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> tuple[str, str]:
    """SHA bazy, z którą scalenie przeszło, i dopisek linii ``SCAL OK`` o teście scalenia."""

    checked = werdykt_scalenia.PullRequest(pull.number, pull.title, pull.head)
    base = werdykt_scalenia.fetch(pull.base, [checked])
    if problems := _problems(pull):
        raise _Refused("; ".join(problems))
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = werdykt_scalenia.merge_verdict(copy, where, base, None, checked)
        if verdict.state != "success":
            raise _Refused(verdict.description)
        return base, testy_scalenia.merge_test(copy, where, base, pull.head)


def _merge_commit(number: int) -> str | None:
    """SHA commitu merge'a scalonego PR albo ``None``, gdy GitHub go nie podał."""

    try:
        return str(json.loads(github.gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]["oid"])
    except Exception:  # noqa: BLE001 - PR jest już scalony, a brak SHA podaje linia SCAL OK
        return None


def _clean_up() -> str:
    try:
        done = potomne.run([sys.executable, str(CLEANUP)], cwd=ROOT, timeout=CLEANUP_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return f"UWAGA: sprzątanie przerwane po {CLEANUP_TIMEOUT_S} s, uruchom je ponownie"
    result = done.stdout.rstrip().rpartition("\n")[2]
    return f"sprzątanie: {result or f'kod {done.returncode}'}"


def _publish_verdict(number: int, path: Path) -> int:
    pull = stan_pr.pull(number)
    text = path.read_text(encoding="utf-8")
    if problems := werdykt_pr.file_problems(text, pull.head):
        print(f"WERDYKT ODMOWA | #{pull.number} | {'; '.join(problems)}; popraw {path} i uruchom ponownie")
        return 1
    url = github.gh("pr", "comment", str(number), "--body-file", str(path)).strip()
    print(f"WERDYKT OK | #{pull.number} {pull.head[:7]} | {werdykt_pr.text_lines(text)[0].split()[1]} | {url}")
    return 0


def _merge(number: int, *, merge: bool) -> int:
    pull = stan_pr.pull(number)
    where = f"#{pull.number} {pull.head[:7]}"
    try:
        base, merge_test = _check(pull)
        if merge and _remote_base(pull.base) != base:
            raise _Refused(f"{pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
    except (_Refused, testy_scalenia.Refused) as refusal:
        print(f"SCAL ODMOWA | {where} | {refusal}")
        return 1
    if not merge:
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge){merge_test}{naprawia.close_fixed(pull, merged=False, merge_commit=None)}")
        return 0
    github.gh("pr", "merge", str(number), "--merge", "--match-head-commit", pull.head)
    merge_commit = _merge_commit(number)
    closed = naprawia.close_fixed(pull, merged=True, merge_commit=merge_commit)
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {(merge_commit or '?')[:7]} (baza {base[:7]}){merge_test}{closed} | {_clean_up()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    rules = (__doc__, testy_scalenia.__doc__, werdykt_pr.__doc__, naprawia.__doc__, kontekst_przegladu.__doc__)
    parser = argparse.ArgumentParser(
        description="\n".join(str(part).strip("\n") + "\n" for part in rules), epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("numer", type=int, help="Numer PR.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bez-merge", action="store_true", help="Sprawdź gotowość, ale nie scalaj.")
    mode.add_argument("--przeglad", action="store_true", help="Wydrukuj recenzentowi kontekst przeglądu PR.")
    mode.add_argument("--werdykt", type=Path, metavar="PLIK", help="Sprawdź plik werdyktu i opublikuj go jako komentarz PR.")
    args = parser.parse_args(argv)
    label = "PRZEGLĄD" if args.przeglad else "WERDYKT" if args.werdykt else "SCAL"
    try:
        if args.przeglad:
            return kontekst_przegladu.print_context(args.numer)
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
