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

SKILLS_FOR_CHANGE = Path("tools") / "skille_dla_zmiany.py"
SKILLS_TIMEOUT_S = 300


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
    print(stan_pr.ci_line(pull))
    print(*werdykt_pr.history(pull.verdicts, pull.head), sep="\n")
    print(f"PRZEGLĄD OK | #{pull.number} {pull.head[:7]}")
    return 0

