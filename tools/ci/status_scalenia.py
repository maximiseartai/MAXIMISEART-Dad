"""Werdykt scalenia każdego otwartego PR z jego bazą jako status commita na HEAD PR.

CI na PR sprawdza scalenie z bazą tylko w chwili pushu. Gdy potem do bazy wejdzie inny PR, otwarty PR może
się z nim kłócić bez konfliktu tekstowego. Narzędzie bierze każdy otwarty PR do bazy (domyślnie ``main``)
i sprawdza, czy jego HEAD scala się z bieżącą bazą bez konfliktu (``git merge-tree``) i czy scalenie
przechodzi ``tools/ci_lokalnie.py --tylko ruff,mypy`` ze scalonego drzewa: ruff, mypy dla systemu, na którym
biegnie (w workflow ``scalenia.yml`` Linux), i mypy dla Windows. Werdykt to status ``scalenie z <baza>`` na
HEAD PR: ``success``, ``failure`` (konflikt albo kroki, które padły) albo ``error``. ``error`` znaczy, że
scalenie pada, ale sama baza też pada, albo że sprawdzenie nie dało wyniku. Opis statusu podaje SHA bazy.

Scalenia biegną po kolei w jednej kopii bazy (``potomne.commit_copy``), którą ``git read-tree`` przestawia
na kolejne drzewo, więc cache mypy zostaje ciepły. PR z forka jest pomijany: jego kod (``ci_lokalnie``
i konfiguracja mypy ze scalonego drzewa) biegłby z tokenem, który może ustawić każdy status commita, także
wymagany przez ruleset. PR, który zmienia zależności, jest sprawdzany z zależnościami zainstalowanymi dla
narzędzia, nie ze swoimi. GitHub przyjmuje najwyżej 1000 statusów na commit i kontekst, więc PR bez pushu
przez 1000 przebiegów przestaje dostawać werdykt.

Kończy się kodem 0, gdy każdy PR dostał werdykt, także czerwony, bo czerwony job na commicie ``main``
wyglądałby jak czerwony ``main``. Kod 1 znaczy, że narzędzie nie wysłało któregoś werdyktu.

    .venv/bin/python tools/ci/status_scalenia.py                # werdykty bez statusów
    python tools/ci/status_scalenia.py --publikuj --baza main   # workflow scalenia.yml
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import potomne
from repo import REMOTE, ROOT
import repo

CHECKS = ("tools/ci_lokalnie.py", "--tylko", "ruff,mypy")
CHECK_TIMEOUT_S = 300
GITHUB_TIMEOUT_S = 60
DESCRIPTION_LIMIT = 140  # GitHub odrzuca dłuższy opis statusu


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


def _gh(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=GITHUB_TIMEOUT_S, check=False
    )


def _open_pull_requests(base: str) -> list[PullRequest]:
    listed = _gh("pr", "list", "--state", "open", "--limit", "500", "--json", "number,title,headRefOid,baseRefName,isCrossRepository")
    listed.check_returncode()
    pulls = []
    for pull in json.loads(listed.stdout):
        if pull["baseRefName"] != base:
            continue
        if pull["isCrossRepository"]:
            print(f"#{pull['number']} pominięty: PR z forka", flush=True)
            continue
        pulls.append(PullRequest(pull["number"], pull["title"], pull["headRefOid"]))
    return pulls


def fetch(base: str, pulls: list[PullRequest]) -> str:
    """SHA ``base`` w ``origin``; HEAD-y ``pulls`` trafiają do repozytorium przez ich ``refs/pull/N/head``."""

    tracking = f"refs/remotes/{REMOTE}/{base}"
    heads = [f"refs/pull/{pull.number}/head" for pull in pulls]
    repo.run_git(ROOT, "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{base}:{tracking}", *heads, timeout=GITHUB_TIMEOUT_S).check_returncode()
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


def _base_problem(copy: Path, where: str) -> str | None:
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


def _run_link() -> str | None:
    names = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    if not all(os.environ.get(name) for name in names):
        return None
    return "{}/{}/actions/runs/{}".format(*(os.environ[name] for name in names))


def _publish(context: str, pull: PullRequest, verdict: Verdict) -> str | None:
    """Błąd GitHuba, gdy status nie przeszedł."""

    description = verdict.description
    if len(description) > DESCRIPTION_LIMIT:
        description = description[: DESCRIPTION_LIMIT - 1] + "…"
    fields = {"state": verdict.state, "context": context, "description": description}
    if link := _run_link():
        fields["target_url"] = link
    flags = [part for name, value in fields.items() for part in ("-f", f"{name}={value}")]
    try:
        sent = _gh("api", "--method", "POST", "--silent", f"repos/{{owner}}/{{repo}}/statuses/{pull.head}", *flags)
    except subprocess.TimeoutExpired:
        return f"gh api bez odpowiedzi przez {GITHUB_TIMEOUT_S} s"
    return (sent.stderr.strip() or f"gh api: kod {sent.returncode}") if sent.returncode else None


def _check_all(base_name: str, publish: bool) -> int:
    started = time.monotonic()
    context = f"scalenie z {base_name}"
    pulls = _open_pull_requests(base_name)
    base = fetch(base_name, pulls)
    where = f"{base_name} {base[:7]}"
    states: Counter[str] = Counter()
    unsent = []
    if pulls:
        with potomne.commit_copy(ROOT, base) as copy:
            print(f"== {where}", flush=True)
            problem = _base_problem(copy, where)
            for pull in pulls:
                print(f"== #{pull.number} {pull.head[:7]} {pull.title}", flush=True)
                verdict = merge_verdict(copy, where, base, problem, pull)
                print(f"#{pull.number} {verdict.state} | {verdict.description}", flush=True)
                states[verdict.state] += 1
                if publish and (error := _publish(context, pull, verdict)):
                    print(f"#{pull.number} status niewysłany | {error}", flush=True)
                    unsent.append(f"#{pull.number}")
    counts = ", ".join(f"{state} {count}" for state, count in sorted(states.items()))
    summary = f"{where} | {len(pulls)} PR ({counts or 'brak'}) | {time.monotonic() - started:.0f} s"
    if unsent:
        print(f"SCALENIA FAIL | {summary} | statusy niewysłane: {', '.join(unsent)}")
        return 1
    print(f"SCALENIA OK | {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default="main", help="Gałąź, do której celują sprawdzane PR (domyślnie main).")
    parser.add_argument("--publikuj", action="store_true", help="Ustaw werdykty jako statusy commitów na GitHubie.")
    args = parser.parse_args(argv)
    try:
        return _check_all(args.baza, args.publikuj)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"SCALENIA FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"SCALENIA FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
