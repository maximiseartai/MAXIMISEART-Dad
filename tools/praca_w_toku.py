"""Pokazuje pracę innych checkoutów i otwartych PR-ów oraz pliki wspólne z bieżącym; użyj przed startem issue i przed aktualizacją z main.

Wiele sesji pracuje naraz, każda w swoim git worktree, i nie widzą się nawzajem. Skrypt tylko
czyta: worktree (``git worktree list``), lokalne gałęzie z commitami spoza ``origin/main``,
niezacommitowane pliki każdego worktree i otwarte PR-y z GitHuba (``gh``). Odłączony HEAD liczy się
z niezacommitowanymi plikami albo z commitem innym niż merge, którego nie ma żadna gałąź ani remote
(inaczej to piaskownica albo przegląd). Worktree w trakcie rebase albo bisect gałęzi pracuje na tej gałęzi,
tak jak uznaje git. Przeniesienie pliku liczy się jako zmiana starej i nowej ścieżki.

Drukuje jedną linię na każdą inną pracę w toku, potem nakładania: pliki, które bieżący checkout i
inna praca zmieniają każdy we własnych commitach albo niezacommitowanych. Commity wspólne obu stron
(gałąź zbudowana na innej) się nie liczą. Bieżący checkout to ten, w którym skrypt uruchomiono.
Raport informuje i nie blokuje: kod wyjścia 0, inny tylko przy błędnym użyciu.

Ostatnia linia mówi, czy gałąź bieżącego checkoutu aktualizować z ``origin/main`` (rebase albo merge):
``AKTUALIZACJA: potrzebna``, gdy ``git merge-tree`` widzi konflikt albo gałąź i ``origin/main`` zmieniają
od bazy scalenia ten sam plik, inaczej ``AKTUALIZACJA: niepotrzebna``. Liczą się commity, nie
niezacommitowane pliki. W trakcie rebase odłączonego HEAD werdykt dotyczy commitu sprzed rebase.
Werdykt nie pobiera ``origin/main``: podaje commit ``origin/main``, z którym porównał, a gdy żaden fetch
w tym repozytorium nie potwierdził go w ostatniej godzinie, dopisuje to. ``git merge-tree`` dodaje do bazy
obiektów tylko nieosiągalne obiekty scalenia, które usuwa ``git gc``.

    py -3 tools/praca_w_toku.py                  # Windows
    python3 tools/praca_w_toku.py                # macOS i Linux
    python3 tools/praca_w_toku.py --issue 212    # przed startem zgłoszenia #212
    python3 tools/praca_w_toku.py --lokalnie     # bez GitHuba
    python3 tools/praca_w_toku.py --nakladania   # tylko nakładania (drukuje je tools/ci_lokalnie.py)
    python3 tools/praca_w_toku.py --aktualizacja # tylko werdykt aktualizacji, w ułamku sekundy
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
from ostatnie_linie import AKTUALIZACJA
from repo import BASE
import repo


SUBJECTS = 3
TIMEOUT_S = 30
FRESH_FETCH_S = 3600
ISSUE_REFERENCE = re.compile(r"#(\d+)\b")
PR_REFERENCE = re.compile(r"(?:#|/pull/)(\d+)\b")
BRANCH_NUMBER = re.compile(r"(?:^|/)(\d{1,5})(?=$|[/_-])")


@dataclass(frozen=True)
class WorkInProgress:
    """Jedna niescalona linia pracy: gałąź, odłączony HEAD worktree albo PR bez lokalnej gałęzi."""

    branch: str | None
    worktree: Path | None
    # None: gałąź PR istnieje tylko na GitHubie.
    head: str | None
    ahead: int
    unpushed: int
    dirty: frozenset[str]
    files: frozenset[str]
    pr: int | None
    issues: frozenset[int]
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class _PullRequest:
    number: int
    branch: str
    issues: frozenset[int]
    files: frozenset[str]


class _GitHubSkipped(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", type=int, metavar="N", help="Tylko praca nad zgłoszeniem #N albo PR, którego dotyczy.")
    parser.add_argument("--lokalnie", action="store_true", help="Bez wywołań gh.")
    parser.add_argument("--nakladania", action="store_true", help="Tylko sekcja nakładań.")
    parser.add_argument("--aktualizacja", action="store_true", help="Tylko werdykt, czy aktualizować z origin/main.")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        # Tematy commitów mogą mieć znaki spoza strony kodowej konsoli Windows.
        sys.stdout.reconfigure(errors="replace")
    try:
        root = repo.toplevel(Path.cwd())
    except (OSError, subprocess.CalledProcessError):
        print("BŁĄD: uruchom w checkoucie repozytorium git.", file=sys.stderr)
        return 2
    if repo.commit(root, BASE) is None:
        print(f"{AKTUALIZACJA}nieznana (brak {BASE})" if args.aktualizacja else f"PRACA W TOKU POMINIĘTA | brak {BASE}, nie ma z czym porównać")
        return 0

    branch = repo.git(root, "branch", "--show-current").strip() or _busy_branch(root)
    if args.aktualizacja:
        print(_update_verdict(root, branch))
        return 0
    mine_dirty = _dirty(root)
    others = [item for item in _local_work(root) if item.worktree != root and (branch is None or item.branch != branch)]
    issue_body = ""
    if args.lokalnie:
        print("GITHUB POMINIĘTY | --lokalnie")
    else:
        try:
            others = _with_pull_requests(others, _pull_requests(root), branch)
            if args.issue is not None:
                issue_body = _issue_body(root, args.issue)
        except _GitHubSkipped as skipped:
            print(f"GITHUB POMINIĘTY | {skipped}")
    others.sort(key=lambda item: (item.worktree is None, item.branch is None, item.branch or "", str(item.worktree)))

    if args.issue is not None:
        reasons = _issue_reasons(others, args.issue, issue_body)
        others = [item for item in others if item in reasons]
        if not args.nakladania:
            print(f"PRACA W TOKU NAD #{args.issue} | {len(others) or 'nikt'}")
            for item in others:
                print(f"{_line(item)} | {reasons[item]}")
    elif not args.nakladania:
        print(f"PRACA W TOKU | inne: {len(others)} | odniesienie: {root} ({branch or 'odłączony HEAD'})")
        for item in others:
            print(_line(item))
    mine = _files(root, "HEAD") | mine_dirty
    for line in _overlaps([(item, _shared(root, mine, mine_dirty, item)) for item in others]):
        print(line)
    if not args.nakladania:
        print(_update_verdict(root, branch))
    return 0


def _local_work(root: Path) -> list[WorkInProgress]:
    worktrees = _worktrees(root)
    checked_out = {tree.branch: tree.path for tree in worktrees if tree.branch is not None}
    branches = repo.git(root, "for-each-ref", "refs/heads", "--format=%(refname)").split()
    lines: list[tuple[str | None, Path | None, str]] = [
        (ref.removeprefix("refs/heads/"), checked_out.get(ref.removeprefix("refs/heads/")), ref) for ref in branches
    ]
    lines += [(None, tree.path, tree.head) for tree in worktrees if tree.branch is None]
    work = []
    for branch, worktree, ref in lines:
        try:
            item = _work(root, branch, worktree, ref)
        except (OSError, subprocess.CalledProcessError):
            continue  # inna sesja właśnie usunęła ten worktree albo gałąź
        if item is not None:
            work.append(item)
    return work


def _work(root: Path, branch: str | None, worktree: Path | None, ref: str) -> WorkInProgress | None:
    dirty = _dirty(worktree) if worktree is not None else frozenset()
    own = ("rev-list", "--count", "--no-merges", ref, "--not", "--branches", "--remotes")
    if branch is None and not dirty and not int(repo.git(root, *own)):
        return None  # czysta odłączona kopia commitów, które pokazuje już gałąź, albo ich merge: piaskownica albo przegląd
    ahead = int(repo.git(root, "rev-list", "--count", f"{BASE}..{ref}"))
    if not ahead and not dirty:
        return None
    return WorkInProgress(
        branch=branch,
        worktree=worktree,
        head=repo.git(root, "rev-parse", ref).strip(),
        ahead=ahead,
        unpushed=int(repo.git(root, "rev-list", "--count", ref, "--not", "--remotes")),
        dirty=dirty,
        files=_files(root, ref) | dirty,
        pr=None,
        issues=_issues(repo.git(root, "log", "--format=%B", f"{BASE}..{ref}")) | _branch_issues(branch),
        subjects=tuple(repo.git(root, "log", "--no-merges", f"-n{SUBJECTS}", "--format=%s", f"{BASE}..{ref}").splitlines()),
    )


def _worktrees(root: Path) -> list[repo.Worktree]:
    trees = [tree for tree in repo.worktrees(root) if tree.path.is_dir()]
    return [tree if tree.branch is not None else replace(tree, branch=_busy_branch(tree.path)) for tree in trees]


def _busy_branch(worktree: Path) -> str | None:
    """Gałąź, którą odłączony HEAD worktree przebudowuje (rebase) albo przeszukuje (bisect)."""

    try:
        state = repo.git_dir(worktree)
    except (OSError, subprocess.CalledProcessError):
        return None  # inna sesja właśnie usunęła ten worktree
    for name in ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"):
        try:
            branch = (state / name).read_text(encoding="utf-8").strip().removeprefix("refs/heads/")
        except OSError:
            continue
        # Rebase odłączonego HEAD zapisuje "detached HEAD", a bisect z odłączonego HEAD hash commita.
        if repo.succeeds(worktree, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"):
            return branch
    return None


def _with_pull_requests(
    work: list[WorkInProgress], pull_requests: list[_PullRequest], current_branch: str | None
) -> list[WorkInProgress]:
    by_branch = {pr.branch: pr for pr in pull_requests}
    attached = [
        replace(item, pr=pr.number, issues=item.issues | pr.issues, files=item.files | pr.files)
        if item.branch is not None and (pr := by_branch.get(item.branch)) is not None
        else item
        for item in work
    ]
    local = {item.branch for item in work}
    remote = [
        WorkInProgress(
            branch=pr.branch,
            worktree=None,
            head=None,
            ahead=0,
            unpushed=0,
            dirty=frozenset(),
            files=pr.files,
            pr=pr.number,
            issues=pr.issues | _branch_issues(pr.branch),
            subjects=(),
        )
        for pr in pull_requests
        if pr.branch not in local and pr.branch != current_branch
    ]
    return attached + remote


def _pull_requests(root: Path) -> list[_PullRequest]:
    fields = "number,headRefName,title,body,files"
    answer = _gh(root, "pr", "list", "--state", "open", "--limit", "200", "--json", fields)
    try:
        return [
            _PullRequest(
                number=int(pr["number"]),
                branch=str(pr["headRefName"]),
                issues=_issues(f"{pr['title']}\n{pr['body'] or ''}"),
                files=frozenset(str(file["path"]) for file in pr["files"] or ()),
            )
            for pr in answer
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise _GitHubSkipped(f"gh pr list: nieoczekiwana odpowiedź ({error!r})") from error


def _issue_body(root: Path, issue: int) -> str:
    answer = _gh(root, "issue", "view", str(issue), "--json", "body")
    try:
        return str(answer["body"] or "")
    except (KeyError, TypeError) as error:
        raise _GitHubSkipped(f"gh issue view: nieoczekiwana odpowiedź ({error!r})") from error


def _issue_reasons(work: list[WorkInProgress], issue: int, body: str) -> dict[WorkInProgress, str]:
    referenced_prs = {int(number) for number in PR_REFERENCE.findall(body)} - {issue}
    reasons = {}
    for item in work:
        found = []
        if issue in item.issues:
            found.append(f"odwołuje się do #{issue}")
        if item.pr in referenced_prs:
            found.append(f"#{issue} dotyczy PR #{item.pr}")
        if found:
            reasons[item] = ", ".join(found)
    return reasons


def _line(item: WorkInProgress) -> str:
    parts = [item.branch or "odłączony HEAD"]
    if item.pr is not None:
        parts.append(f"PR #{item.pr}")
    if item.worktree is not None:
        parts.append(str(item.worktree))
    else:
        parts.append("tylko na GitHubie" if item.head is None else "bez worktree")
    counts = [] if item.head is None else [f"przed {BASE} {item.ahead}", f"niewypchnięte {item.unpushed}"]
    counts += [f"niezacommitowane {len(item.dirty)}", f"pliki {len(item.files)}"]
    parts.append(", ".join(counts))
    if item.issues:
        parts.append(" ".join(f"#{number}" for number in sorted(item.issues)))
    if item.subjects:
        parts.append(item.subjects[0])
    return "- " + " | ".join(parts)


def _shared(root: Path, mine: frozenset[str], mine_dirty: frozenset[str], item: WorkInProgress) -> frozenset[str]:
    """Pliki, które zmienia ten checkout i ``item``, każdy we własnych commitach albo niezacommitowanych.

    Gałąź zbudowana na innej niesie jej commity; liczą się tylko commity, których druga strona nie ma.
    Gałąź PR tylko na GitHubie ma swoje commity lokalnie w gałęzi zdalnej ``origin``, jeśli ją pobrano.
    """

    if item.head is None:
        pushed = f"refs/remotes/origin/{item.branch}"
        if repo.commit(root, pushed) is None:
            return mine & item.files
        return (_own_files(root, "HEAD", pushed) | mine_dirty) & _own_files(root, pushed, "HEAD")
    return (_own_files(root, "HEAD", item.head) | mine_dirty) & (_own_files(root, item.head, "HEAD") | item.dirty)


def _overlaps(shared: list[tuple[WorkInProgress, frozenset[str]]]) -> list[str]:
    shared = [(item, files) for item, files in shared if files]
    if not shared:
        return ["NAKŁADANIA | brak"]
    lines = ["NAKŁADANIA | pliki zmieniane tu i w innej pracy w toku"]
    for item, files in shared:
        name = item.branch or f"odłączony HEAD {item.worktree}"
        pr = f" (PR #{item.pr})" if item.pr is not None else ""
        lines.append(f"- {name}{pr}: {', '.join(sorted(files))}")
    return lines


def _update_verdict(root: Path, branch: str | None) -> str:
    """Q9: gałąź aktualizuje się z ``origin/main`` tylko przy konflikcie albo pliku zmienionym po obu stronach."""

    ref = f"refs/heads/{branch}" if branch is not None else _before_rebase(root) or "HEAD"
    try:
        merged = repo.git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", ref, BASE)
    except subprocess.CalledProcessError as conflict:
        if conflict.returncode != 1:
            reason = (conflict.stderr.strip().splitlines() or [f"kod {conflict.returncode}"])[0]
            return f"{AKTUALIZACJA}nieznana (git merge-tree: {reason}){_base_note(root)}"
        merged = conflict.stdout
    if conflicts := sorted(set(merged.split("\0")[1:]) - {""}):
        verdict = f"potrzebna (konflikt w: {', '.join(conflicts)})"
    elif shared := sorted(_files(root, ref) & _files(root, BASE, since=ref)):
        verdict = f"potrzebna (bez konfliktu, wspólne pliki: {', '.join(shared)})"
    else:
        verdict = "niepotrzebna (bez konfliktu, bez wspólnych plików)"
    return f"{AKTUALIZACJA}{verdict}{_base_note(root)}"


def _before_rebase(root: Path) -> str | None:
    """Commit sprzed rebase odłączonego HEAD: w trakcie HEAD stoi na nowym ``origin/main``."""

    state = repo.git_dir(root)
    for name in ("rebase-merge/orig-head", "rebase-apply/orig-head"):
        try:
            return (state / name).read_text(encoding="utf-8").strip() or None
        except OSError:
            continue
    return None


def _base_note(root: Path) -> str:
    """Commit ``origin/main``, z którym werdykt porównał, i wiek fetch, gdy żaden nie potwierdził go w ostatniej godzinie."""

    seen, short = repo.git(root, "log", "-1", "--format=%H%n%h", BASE).split()
    main_branch = f"\tbranch '{BASE.partition('/')[2]}' of "
    common = repo.common_dir(root)
    # FETCH_HEAD ma każdy worktree osobno, a origin/main jest wspólny dla wszystkich.
    confirmed = []
    for fetch_head in [common / "FETCH_HEAD", *common.glob("worktrees/*/FETCH_HEAD")]:
        try:
            lines = fetch_head.read_text(encoding="utf-8", errors="replace").splitlines()
            fetched = fetch_head.stat().st_mtime
        except OSError:
            continue
        if any(line.startswith(f"{seen}\t") and main_branch in line for line in lines):
            confirmed.append(fetched)
    compared = f" | {BASE} {short}"
    if not confirmed:
        return f"{compared} bez śladu fetch, odśwież: git fetch origin"
    age = time.time() - max(confirmed)
    if age < FRESH_FETCH_S:
        return compared
    return f"{compared} z fetch sprzed {int(age // 3600)} h, odśwież: git fetch origin"


def _files(root: Path, ref: str, since: str = BASE) -> frozenset[str]:
    return repo.changed(root, repo.merge_base(root, since, ref), ref)


def _own_files(root: Path, ref: str, other: str) -> frozenset[str]:
    log = repo.git(root, "log", "--no-renames", "--name-only", "--format=", "-z", ref, f"^{BASE}", f"^{other}")
    return frozenset(log.split("\0")) - {""}


def _dirty(worktree: Path) -> frozenset[str]:
    status = repo.git(worktree, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    return frozenset(entry[3:] for entry in status.split("\0") if entry)


def _issues(text: str) -> frozenset[int]:
    return frozenset(int(number) for number in ISSUE_REFERENCE.findall(text))


def _branch_issues(branch: str | None) -> frozenset[int]:
    return frozenset(int(number) for number in BRANCH_NUMBER.findall(branch or ""))


def _gh(root: Path, *args: str) -> Any:
    """Odpowiedź JSON ``gh``; każda porażka to ``_GitHubSkipped``, bo raport bez GitHuba jest jak lokalnie."""

    try:
        answered = github.gh(*args, limit_s=TIMEOUT_S, cwd=root)
    except FileNotFoundError as error:
        raise _GitHubSkipped("brak gh") from error
    except subprocess.CalledProcessError as error:
        reason = (error.stderr.strip().splitlines() or [f"kod {error.returncode}"])[0]
        raise _GitHubSkipped(f"gh: {reason}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _GitHubSkipped(f"gh: {error}") from error
    try:
        return json.loads(answered)
    except json.JSONDecodeError as error:
        raise _GitHubSkipped(f"gh: {error}") from error

if __name__ == "__main__":
    raise SystemExit(main())
