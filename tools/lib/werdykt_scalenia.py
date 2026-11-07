"""Werdykt scalenia PR z bazą: bez konfliktu (``git merge-tree``) i z ruff i mypy obu systemów na scalonym drzewie.

Werdykt to ``success``, ``failure`` (konflikt albo kroki, które padły) albo ``error``: scalenie pada, ale sama baza
też pada (``base_problem``), albo sprawdzenie nie dało wyniku. Kroki to ``tools/ci_lokalnie.py --tylko ruff,mypy`` ze
scalonego drzewa w kopii bazy, którą ``git read-tree`` przestawia na kolejne drzewo, więc cache mypy zostaje ciepły.
Pytają o niego status ``scalenie z main`` (``tools/ci/status_scalenia.py``) i ``tools/scal_pr.py`` tuż przed merge'em.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Literal

import github
import potomne
from repo import REMOTE, ROOT
import repo

CHECKS = ("tools/ci_lokalnie.py", "--tylko", "ruff,mypy")
CHECK_TIMEOUT_S = 300


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    head: str


@dataclass(frozen=True)
class Verdict:
    state: Literal["success", "failure", "error"]
    description: str


class _NoCheckResult(Exception):
    pass


def fetch(base: str, pulls: list[PullRequest]) -> str:
    """SHA ``base`` w ``origin``; HEAD-y ``pulls`` trafiają do repozytorium przez ich ``refs/pull/N/head``."""

    tracking = f"refs/remotes/{REMOTE}/{base}"
    heads = [f"refs/pull/{pull.number}/head" for pull in pulls]
    repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{base}:{tracking}", *heads, timeout=github.LIMIT_S).check_returncode()
    return repo.git(ROOT, "rev-parse", "--verify", f"{tracking}^{{commit}}").strip()


def _failed_checks(copy: Path) -> list[str]:
    try:
        done = potomne.run([sys.executable, *CHECKS], cwd=copy, timeout=CHECK_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired as error:
        raise _NoCheckResult(f"ruff i mypy trwały ponad {CHECK_TIMEOUT_S} s") from error
    result = done.stdout.rstrip().rpartition("\n")[2]
    if result.startswith("CI LOKALNIE OK"):
        return []
    if result.startswith("CI LOKALNIE FAIL | "):
        return result.removeprefix("CI LOKALNIE FAIL | ").split(", ")
    raise _NoCheckResult(f"tools/ci_lokalnie.py skończyło się bez wyniku, kod {done.returncode}")


def base_problem(copy: Path, where: str) -> str | None:
    """Czemu sama baza w ``copy`` nie przechodzi kroków; ``None``, gdy przechodzi."""

    try:
        failed = _failed_checks(copy)
    except _NoCheckResult as error:
        return f"{where}: {error}"
    return f"{where} sam nie przechodzi: {', '.join(failed)}" if failed else None


def merge_verdict(copy: Path, where: str, base: str, base_problem: str | None, pull: PullRequest) -> Verdict:
    try:
        tree = repo.git(ROOT, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, pull.head).splitlines()[0]
    except subprocess.CalledProcessError as unmerged:
        if unmerged.returncode == 1:
            return Verdict("failure", f"Konflikt z {where}: {', '.join(unmerged.stdout.splitlines()[1:])}")
        return Verdict("error", f"git merge-tree z {where}: {unmerged.stderr.strip()}")
    repo.run_git(copy, "read-tree", "-u", "--reset", tree).check_returncode()
    try:
        failed = _failed_checks(copy)
    except _NoCheckResult as error:
        return Verdict("error", f"Scalenie z {where}: {error}")
    if failed and base_problem:
        return Verdict("error", base_problem)
    if failed:
        return Verdict("failure", f"Na scaleniu z {where} pada: {', '.join(failed)}")
    return Verdict("success", f"Scalenie z {where} bez konfliktu, ruff i mypy (oba systemy) przechodzą")
