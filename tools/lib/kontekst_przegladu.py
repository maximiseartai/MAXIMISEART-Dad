"""Dwa tryby służą recenzentowi (skill ``przeglad``, tryb recenzenta) i niczego nie scalają. ``--przeglad`` drukuje
kontekst przeglądu: pełny SHA HEAD PR, bazę i merge-base z nią, ``git diff --stat`` i zmienione pliki od merge-base,
wynik ``tools/skille_dla_zmiany.py`` z HEAD PR liczony od merge-base (w kopii commitu HEAD, więc ``pilnuje:`` skilli
jest z PR) i poprzednie werdykty PR w kolejności utworzenia, każdy z datą, autorem, dwiema pierwszymi liniami i tym,
czy dotyczy HEAD (``PASS`` poza regułami ``--werdykt`` z dopiskiem). Gdy ostatni werdykt jest dla innego commitu,
linia ``RUNDA`` podaje polecenie diffu od niego do HEAD. Linia ``CI`` podaje stan najnowszego runu workflow ``CI``
na HEAD z rollupu checków, tego samego, który liczy ``scal_pr`` (``stan_pr.latest_ci_run``), a jego zadania i
``Required CI status`` bierze tylko z tego runu, więc zadania starszych runów, na przykład sprzed zamknięcia i otwarcia
PR, się nie liczą: ``success``, gdy run się skończył, a jego Required przeszedł, znaczy, że polecenia z linii
``LICZY CI`` przeszły (``tools/plan_ci.py``), więc ich logów nie trzeba czytać, a zadania innych workflowów, które
jeszcze biegną albo padły, wymienia osobno, bo gotowość czeka i na nie; ``pending``, gdy run trwa (nie ma jeszcze
checku Required, bo GitHub tworzy go po zadaniach z jego ``needs:``, albo któreś jego zadanie biegnie); ``failure``
z padłymi zadaniami runu i poleceniem ``gh run view <run> --log-failed``; ``nieznany``, gdy check workflow ``CI``
nie ma identyfikatora runu w ``detailsUrl``; ``brak``, gdy CI na HEAD nie biegło. Kończy się linią ``PRZEGLĄD OK | #N <sha>``.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import github
from ostatnie_linie import SKILLE_VERIFY
import potomne
from repo import ROOT
import repo
import stan_pr
import werdykt_pr
import werdykt_scalenia

JOB_NOT_FAILED = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
SKILLS_FOR_CHANGE = Path("tools") / "skille_dla_zmiany.py"
SKILLS_TIMEOUT_S = 300


def _ci_line(rollup: list[dict[str, str | None]], head: str) -> str:
    where = f"CI | {github.REQUIRED}"
    others = [check for check in rollup if check.get("workflowName") and check.get("workflowName") != github.CI_WORKFLOW]
    try:
        run = stan_pr.latest_ci_run(rollup)
    except stan_pr.UnknownRun as unknown:
        return (
            f"{where} nieznany na HEAD {head} | check „{unknown.name}” workflow „{github.CI_WORKFLOW}” bez identyfikatora "
            f"runu w detailsUrl {unknown.url} | polecenia z linii LICZY CI nie są dowiedzione"
        )
    if run is None:
        return f"{where} brak na HEAD {head} | CI nie biegło na tym HEAD: jeszcze nie wystartowało po pushu albo PR ma konflikt z bazą"
    required = run.required
    failed = sorted(
        {
            str(check.get("name"))
            for check in run.checks
            if check.get("name") != github.REQUIRED and check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED
        }
    )
    jobs = f"padłe zadania: {', '.join(failed)}" if failed else ""
    if required is not None and required.get("status") == "COMPLETED" and required.get("conclusion") != "SUCCESS":
        why = jobs or f"bez padłego zadania, przyczynę podaje log „{github.REQUIRED}”"
        logs = f"logi padłych zadań: gh run view {run.id} --log-failed"
        return f"{where} failure na HEAD {head} | {why} | polecenia z linii LICZY CI nie są dowiedzione, czytaj tylko {logs}"
    if required is not None and not run.running:
        running_others = sorted({str(check.get("name")) for check in others if check.get("status") != "COMPLETED"})
        failed_others = sorted(
            {str(check.get("name")) for check in others if check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED}
        )
        states = [f"{state}: {', '.join(names)}" for state, names in (("w toku", running_others), ("padłe", failed_others)) if names]
        rest = f" | inne workflowy, na które czeka gotowość: {'; '.join(states)}" if states else ""
        return f"{where} success na HEAD {head} | polecenia z linii LICZY CI przeszły, ich logów nie przeszukuj{rest}"
    running = [*run.running, *(check for check in others if check.get("status") != "COMPLETED")]
    return f"{where} pending na HEAD {head} (w toku: {len(running)}{f'; {jobs}' if jobs else ''}) | polecenia z linii LICZY CI jeszcze bez wyniku"


def _skills_for_change(head: str, fork: str) -> list[str]:
    """Wynik ``tools/skille_dla_zmiany.py`` z kopii commitu ``head`` od ``fork``; ostatnia linia to zawsze ``SKILLE VERIFY``."""

    unknown = SKILLE_VERIFY + "nieznane ({})"
    with potomne.commit_copy(ROOT, head) as copy:
        if not (copy / SKILLS_FOR_CHANGE).is_file():
            return [unknown.format(f"HEAD PR nie ma {SKILLS_FOR_CHANGE.as_posix()}")]
        try:
            done = potomne.run([sys.executable, str(copy / SKILLS_FOR_CHANGE), fork], cwd=copy, timeout=SKILLS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return [unknown.format(f"{SKILLS_FOR_CHANGE.as_posix()} przerwane po {SKILLS_TIMEOUT_S} s")]
    lines = done.stdout.splitlines()
    if not lines or not lines[-1].startswith(SKILLE_VERIFY):
        detail = (done.stderr.strip().splitlines() or [f"kod {done.returncode}"])[-1]
        lines.append(unknown.format(f"{SKILLS_FOR_CHANGE.as_posix()}: {detail}"))
    return lines


def print_context(number: int) -> int:
    pull = stan_pr.pull(number)
    base = werdykt_scalenia.fetch(pull.base, [werdykt_scalenia.PullRequest(pull.number, pull.title, pull.head)])
    limit = github.LIMIT_S
    fork = repo.merge_base(ROOT, base, pull.head, timeout=limit)
    files = sorted(repo.changed(ROOT, fork, pull.head, timeout=limit))
    print(f"PRZEGLĄD | #{pull.number} {pull.title} | HEAD {pull.head} | baza {pull.base} {base} | merge-base {fork}")
    print(f"ZMIANA | git diff --stat {fork} {pull.head}")
    print(repo.git(ROOT, "diff", "--stat", fork, pull.head, timeout=limit).rstrip())
    print(f"PLIKI | {len(files)}", *files, sep="\n")
    print(f"SKILLE | {SKILLS_FOR_CHANGE.as_posix()} {fork} na HEAD PR", *_skills_for_change(pull.head, fork), sep="\n")
    print(_ci_line(list(pull.checks), pull.head))
    print(*werdykt_pr.history(pull.verdicts, pull.head), sep="\n")
    print(f"PRZEGLĄD OK | #{pull.number} {pull.head[:7]}")
    return 0

