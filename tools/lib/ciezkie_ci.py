"""Ciężkie zadania CI liczy GitHub, a lokalnie biegną tylko do odtworzenia ich konkretnej porażki.

Ciężkie zadania to ``change-mutations`` (``tools/mutacje_zmiany.py``) i ``mutations`` (``tools/ci/mutacje_skilli.py``
dla wszystkich skilli): trwają kilkanaście minut i dłużej, a CI liczy je w częściach, ``mutations`` po pushu, a
``change-mutations`` nocą na ``main`` (ADR 0021).
``tools/mutacje_zmiany.py`` i ``tools/ci_lokalnie.py`` z ``mutations`` (także pełne, bez ``--tylko``) pytają
``refusal`` przed startem, a ``tools/mutacje.py`` pyta ``mutations_refusal``, bo lista dłuższa niż ``TARGETED``
mutacji to ręczne ``change-mutations``. Poza CI odmawiają (kod 2 i linia ``CIĘŻKIE CI ODMOWA``), chyba że:

- biegną w CI (``GITHUB_ACTIONS=true``);
- ``--odtwarzam <id runu Actions albo URL>`` wskazuje run, w którym każde z tych zadań padło i który dotyczy bieżącej
  gałęzi (``headBranch`` to ona albo ``headSha`` jest przodkiem HEAD spoza ``origin/main``), a run ``NIGHTLY`` swojego
  commitu: jego ``headSha`` to HEAD (``git checkout --detach <headSha>``); ``gh run view`` to sprawdza;
- uruchamia je ``tools/na_scalonych_pr.py`` (``MAXIMISEART_NA_SCALONYCH_PR=1``): próba narzędzia na commicie scalenia
  cudzego PR-u, nie sprawdzenie przed pushem.

Skrypty ``check_*_mutations.py`` skilli ``verify-*`` wołają ``check_all`` wprost i nie mają limitu: ich lista leży
w repozytorium, więc przegląda ją PR.

Granica: tylko przegląd łapie ``GITHUB_ACTIONS`` albo ``MAXIMISEART_NA_SCALONYCH_PR``
podstawione ręcznie, ``tools/na_scalonych_pr.py --commit`` z commitem własnej gałęzi, ``tools/ci/mutacje_skilli.py``
uruchomione wprost, własny skrypt, który woła silnik (``check_all``, ``verdicts``) z długą listą, pytest z własną
pętlą mutacji, a także ręczne ``change-mutations`` w kilku uruchomieniach ``tools/mutacje.py`` po najwyżej ``TARGETED``
mutacji albo dla zmiany, która daje ich najwyżej tyle: strażnik liczy listę jednego uruchomienia, nie jej pochodzenie.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
import json
import os
from pathlib import Path
import re
import subprocess

import github
from repo import BASE
import repo

# Zadanie z ``tools/ci_lokalnie.py`` i początek nazwy jego zadań w ``ci.yml`` albo ``mutacje-nocne.yml``.
HEAVY = {"change-mutations": "Change mutations", "mutations": "Mutation checks"}
# Workflow ``mutacje-nocne.yml``: biegnie na ``main``, więc jego run nie dotyczy gałęzi, na której się go odtwarza.
NIGHTLY = "Mutacje nocne"
FROM_MERGED_PRS = "MAXIMISEART_NA_SCALONYCH_PR"
# Do 26.10 dowody nowych testów z 300 PR-ów miały najwyżej 32 mutacje (p99 21), ręczne listy przeglądów najwyżej 100,
# a lista z generatora Change mutations 335.
TARGETED = 100

Gh = Callable[[Sequence[str]], str]


def _gh(arguments: Sequence[str]) -> str:
    return github.gh(*arguments, limit_s=None)


def argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--odtwarzam",
        metavar="RUN",
        help="Id albo URL runu Actions tej gałęzi, w którym padło ciężkie zadanie: tylko wtedy biegnie ono poza CI.",
    )


def refusal(
    jobs: Iterable[str],
    reproduces: str | None,
    *,
    root: Path,
    env: Mapping[str, str] = os.environ,
    gh: Gh = _gh,
) -> str | None:
    """Powód odmowy startu ciężkich zadań z ``jobs`` albo ``None``, gdy mogą biec."""

    heavy = sorted(set(jobs) & HEAVY.keys())
    if not heavy or env.get("GITHUB_ACTIONS") == "true" or env.get(FROM_MERGED_PRS) == "1":
        return None
    named = ", ".join(heavy)
    if reproduces is None:
        where = (
            "Wypchnij gałąź: CI policzy je w częściach, a stan pokaże tools/praca_w_toku.py albo gh pr checks. "
            if "mutations" in heavy
            else "Liczy je noc na main (mutacje-nocne.yml, ADR 0021), a przeżyte mutacje trafiają do issue „Przeżyte mutacje z #N”. "
        )
        return (
            f"CIĘŻKIE CI ODMOWA | {named} liczy CI na GitHubie, nie ten komputer. {where}"
            "Lokalnie tylko odtworzenie porażki: dodaj --odtwarzam <id albo URL runu Actions tej gałęzi, w którym zadanie padło>."
        )
    try:
        why = _not_reproducing(heavy, reproduces, root, gh)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        why = f"nie odczytałem runu {reproduces} przez gh: {error}"
    return f"CIĘŻKIE CI ODMOWA | --odtwarzam {reproduces}: {why}" if why else None


def mutations_refusal(
    count: int,
    reproduces: str | None,
    *,
    root: Path,
    env: Mapping[str, str] = os.environ,
    gh: Gh = _gh,
) -> str | None:
    """Powód odmowy startu ``count`` mutacji ``tools/mutacje.py`` albo ``None``, gdy mogą biec."""

    if count <= TARGETED:
        return None
    refused = refusal({"change-mutations"}, reproduces, root=root, env=env, gh=gh)
    if refused is None:
        return None
    return f"{refused.rstrip('.')}. Celowany dowód nowego testu ma najwyżej {TARGETED} mutacji, a ta lista ma {count}."


def _not_reproducing(heavy: list[str], reproduces: str, root: Path, gh: Gh) -> str | None:
    found = re.fullmatch(r"(\d+)|https://github\.com/[^/]+/[^/]+/actions/runs/(\d+)(/.*)?", reproduces.strip())
    if not found:
        return "to nie jest id ani URL runu Actions"
    run_id = found.group(1) or found.group(2)
    run = json.loads(gh(["run", "view", run_id, "--json", "headBranch,headSha,jobs,workflowName"]))
    branch = repo.git(root, "branch", "--show-current").strip()
    if run["workflowName"] == NIGHTLY:
        if run["headSha"] != repo.git(root, "rev-parse", "HEAD").strip():
            return f"run nocny odtwarza się na jego commicie: git checkout --detach {run['headSha']}"
    elif run["headBranch"] != branch and not _own_commit(root, run["headSha"]):
        return f"run dotyczy gałęzi {run['headBranch']} ({run['headSha'][:8]}), a nie bieżącej {branch or 'HEAD'}"
    failed = {job["name"] for job in run["jobs"] if job["conclusion"] == "failure"}
    if missing := [job for job in heavy if not any(name.startswith(HEAVY[job]) for name in failed)]:
        return f"w runie {run_id} nie padło {', '.join(missing)}; odtwórz tylko zadanie, które padło"
    return None


def _own_commit(root: Path, commit: str) -> bool:
    """``commit`` jest przodkiem HEAD, ale nie ``origin/main``: czerwony run scalonego PR-u nie otwiera mutacji."""

    return repo.is_ancestor(root, commit, "HEAD") and not repo.is_ancestor(root, commit, BASE)
