from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import github
import limit_rund
from ostatnie_linie import SKILLE_VERIFY
import potomne
from repo import ROOT
import repo
import stan_pr
import stawka_przegladu
import werdykt_pr

ZASADY = """Dwa tryby służą recenzentowi (skill ``przeglad``, ``recenzent.md``) i niczego nie scalają. ``--przeglad`` drukuje
kontekst przeglądu: pełny SHA HEAD PR, bazę i merge-base z nią, ``git diff --stat`` i zmienione pliki od merge-base,
stawkę przeglądu (linia ``STAWKA``: ``lekka`` z ``stawka_przegladu.light`` albo ``pełna``),
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
nie ma identyfikatora runu w ``detailsUrl``; ``brak``, gdy CI na HEAD nie biegło. Kończy się linią ``PRZEGLĄD OK | #N <sha>``,
a PR, któremu limit rund (``limit_rund``) nie daje kolejnej rundy, tylko linią ``PRZEGLĄD ODMOWA | #N <sha> | <przyczyna>``.
"""

SKILLS_FOR_CHANGE = Path("tools") / "skille_dla_zmiany.py"
SKILLS_TIMEOUT_S = 300
STAKE_LIGHT = (
    "STAWKA | lekka: PR zmienia tylko tools/ bez tools/wydanie.py, .github/ i testy narzędzi, więc Ważne jest tylko zepsucie main, "
    "Wydania albo danych taty, a scal_pr wymaga do niego bloku ## Korzeń i strażnika tylko przy Mechanizm: lint, jak w pełnej "
    "stawce (aneks ADR 0042, ADR 0046)"
)
STAKE_FULL = "STAWKA | pełna"


def _skills_for_change(head: str, fork: str) -> list[str]:
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


def print_context(pull: stan_pr.Pull, base: str) -> int:
    """Kontekst przeglądu ``pull`` z bazą ``base`` (SHA ``origin/<baza PR>`` tuż po pobraniu)."""

    if refused := limit_rund.deployed_problem(pull):
        print(f"PRZEGLĄD ODMOWA | #{pull.number} {pull.head[:7]} | {refused}")
        return 1
    limit = github.LIMIT_S
    fork = repo.merge_base(ROOT, base, pull.head, timeout=limit)
    files = sorted(repo.changed(ROOT, fork, pull.head, timeout=limit))
    print(f"PRZEGLĄD | #{pull.number} {pull.title} | HEAD {pull.head} | baza {pull.base} {base} | merge-base {fork}")
    print(f"ZMIANA | git diff --stat {fork} {pull.head}")
    print(repo.git(ROOT, "diff", "--stat", fork, pull.head, timeout=limit).rstrip())
    print(f"PLIKI | {len(files)}", *files, sep="\n")
    print(STAKE_LIGHT if stawka_przegladu.light(pull) else STAKE_FULL)
    print(f"SKILLE | {SKILLS_FOR_CHANGE.as_posix()} {fork} na HEAD PR", *_skills_for_change(pull.head, fork), sep="\n")
    print(stan_pr.ci_line(pull))
    print(*werdykt_pr.history(pull.verdicts, pull.head), sep="\n")
    print(f"PRZEGLĄD OK | #{pull.number} {pull.head[:7]}")
    return 0

