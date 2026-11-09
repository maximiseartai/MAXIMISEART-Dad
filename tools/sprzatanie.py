"""Raportuje, a z --usun usuwa worktree i gałęzie, których praca jest już w origin/main; użyj po merge'u albo gdy worktree się mnożą.

Raportuje, a z ``--usun`` usuwa lokalne worktree i gałęzie, których praca jest już w ``origin/main``; resztę opisuje z powodem.

Bez ``--usun`` niczego nie usuwa. Z ``--usun`` usuwa worktree (``git worktree remove`` bez ``--force``, potem jego
gałąź), gdy naraz:

- HEAD jest w ``origin/main``: jest jego przodkiem albo scalenie go z ``origin/main`` niczego nie zmienia
  (gałąź scalona przez squash);
- w drzewie nie ma zmian ani niepustych plików nieśledzonych czy ignorowanych poza odtwarzalnymi (``.venv``,
  ``node_modules``, cache narzędzi), a git nie jest w trakcie rebase, merge'a, cherry-picka ani bisect;
- żaden proces nie ma w nim katalogu roboczego ani otwartego pliku (``lsof``) i nie jest to checkout, w którym
  narzędzie uruchomiono;
- nie należy do aktywnego wątku T3 (``running`` albo jeszcze nie zamknięty przez Maksa);
- nie jest świeżym worktree bez własnej pracy: HEAD stoi tam, gdzie go utworzono, a utworzono go w ostatniej dobie
  (sesja właśnie go założyła, a kopia commitu narzędzia jeszcze go używa);
- nie jest zablokowany (``git worktree lock``) ani pozbawiony katalogu.

Gałąź bez worktree usuwa przy tych samych warunkach HEAD, wątku T3 i świeżości. Główny checkout i gałąź ``main``
zostają zawsze. Gdy nie da się sprawdzić procesów (brak ``lsof``, jego pusta odpowiedź, Windows), zostaje każdy
worktree; gdy nie da się zapytać T3, zostają worktree w ``~/.t3/worktrees``.

Tuż przed usunięciem ocenia worktree jeszcze raz, ze świeżym ``lsof``. Gdy git odmówi usunięcia, worktree albo
gałąź zostaje z powodem ``git odmówił (...)``.

Przed oceną pobiera ``origin/main``; nieudany fetch tylko zmniejsza liczbę usuniętych.
Drukuje linię na każdy worktree i gałąź. Ostatnia linia to ``SPRZĄTANIE RAPORT | do usunięcia N | zostawione M
(powód liczba, ...) | uruchom z --usun``, a z ``--usun`` ``SPRZĄTANIE OK | usunięte N | zostawione M (...)``;
worktree z kilkoma powodami liczy się przy każdym. Kod 1 i ``SPRZĄTANIE FAIL`` znaczą, że nie da się odczytać
repozytorium.

    .venv/bin/python tools/sprzatanie.py           # co by usunęło i dlaczego reszta zostaje (woła je tools/scal_pr.py)
    .venv/bin/python tools/sprzatanie.py --usun    # usuwa
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import potomne
from repo import BASE, MAIN, REMOTE, Worktree
import repo

TIMEOUT_S = 30
FETCH_TIMEOUT_S = 120
REMOVE_TIMEOUT_S = 300
FRESH_S = 24 * 3600
REPRODUCIBLE = frozenset({".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"})
REPRODUCIBLE_SUFFIXES = (".pyc", ".egg-info")
IN_PROGRESS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
CLOSED_T3 = frozenset({"completed", "failed", "cancelled"})
FRESH = "nowe, bez własnych commitów"


@dataclass(frozen=True)
class _Verdict:
    worktree: Worktree | None
    branch: str | None
    head: str
    reasons: tuple[str, ...]

    def name(self) -> str:
        if self.worktree is None:
            return f"gałąź {self.branch}"
        return f"worktree {self.worktree.path} ({self.branch or 'odłączony HEAD'})"


@dataclass(frozen=True)
class _Threads:
    paths: frozenset[Path]
    branches: frozenset[str]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--usun", action="store_true", help="Usuwa; bez tej flagi narzędzie tylko raportuje.")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")
    here = Path.cwd().resolve()
    try:
        root = repo.toplevel(here)
    except (OSError, subprocess.CalledProcessError):
        print("SPRZĄTANIE FAIL | uruchom w checkoucie repozytorium git")
        return 1
    fetched = _fetch(root)
    if fetched:
        print(f"FETCH POMINIĘTY | {fetched}")
    if repo.commit(root, BASE) is None:
        print(f"SPRZĄTANIE FAIL | brak {BASE}, nie ma z czym porównać")
        return 1

    trees = repo.worktrees(root)
    threads = _t3_threads(root, next(tree.path for tree in trees if tree.main))
    busy = _busy()
    verdicts = [_judge_tree(root, tree, here, busy, threads) for tree in trees]
    checked_out = {tree.branch for tree in trees if tree.branch is not None}
    for ref in repo.git(root, "for-each-ref", "refs/heads", "--format=%(refname:short)%00%(objectname)").splitlines():
        branch, _, head = ref.partition("\0")
        if branch != MAIN and branch not in checked_out:
            verdicts.append(_Verdict(None, branch, head, _readable(_branch_reasons(root, branch, head, threads))))

    removed = 0
    for verdict in sorted(verdicts, key=lambda verdict: (bool(verdict.reasons), verdict.name())):
        if verdict.reasons:
            print(f"- zostaje | {verdict.name()} | {', '.join(verdict.reasons)}")
            continue
        if not args.usun:
            print(f"- do usunięcia | {verdict.name()}")
            removed += 1
            continue
        problem = _remove(root, verdict, here, threads)
        if problem is None:
            print(f"- usunięte | {verdict.name()}")
            removed += 1
        else:
            verdicts[verdicts.index(verdict)] = _Verdict(verdict.worktree, verdict.branch, verdict.head, (problem,))
            print(f"- zostaje | {verdict.name()} | {problem}")
    left = [verdict for verdict in verdicts if verdict.reasons]
    counts = Counter(reason.partition(" (")[0] for verdict in left for reason in verdict.reasons)
    why = ", ".join(f"{reason} {count}" for reason, count in counts.most_common())
    kept = f"zostawione {len(left)}{f' ({why})' if why else ''}"
    if args.usun:
        print(f"SPRZĄTANIE OK | usunięte {removed} | {kept}")
    else:
        print(f"SPRZĄTANIE RAPORT | do usunięcia {removed} | {kept} | uruchom z --usun")
    return 0


def _judge_tree(root: Path, tree: Worktree, here: Path, busy: frozenset[str] | None, threads: _Threads | None) -> _Verdict:
    return _Verdict(tree, tree.branch, tree.head, _readable(_tree_reasons(root, tree, here, busy, threads)))


def _readable(reasons: Iterable[str]) -> tuple[str, ...]:
    found: list[str] = []
    try:
        found.extend(reasons)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        found.append(f"nie da się odczytać ({type(error).__name__})")
    return tuple(found)


def _tree_reasons(root: Path, tree: Worktree, here: Path, busy: frozenset[str] | None, threads: _Threads | None) -> Iterable[str]:
    if tree.main:
        yield "główny checkout"
        return
    if tree.missing:
        yield "brak katalogu (git worktree prune)"
        return
    if tree.locked:
        yield "zablokowany"
    if here == tree.path or tree.path in here.parents:
        yield "bieżący checkout"
    if not _in_base(root, tree.head):
        yield f"commity spoza {BASE}"
    yield from _tree_state(tree.path)
    if busy is None:
        yield "procesy niesprawdzone (brak lsof albo pusta odpowiedź)"
    elif any(name == str(tree.path) or name.startswith(f"{tree.path}{os.sep}") for name in busy):
        yield "żywy proces"
    if threads is None:
        if (Path.home().resolve() / ".t3" / "worktrees") in tree.path.parents:
            yield "stan wątku T3 nieznany"
    elif tree.path in threads.paths or tree.branch in threads.branches:
        yield "aktywny wątek T3"
    if _fresh_without_own_work(tree.path, "HEAD", tree.head):
        yield FRESH


def _branch_reasons(root: Path, branch: str, head: str, threads: _Threads | None) -> Iterable[str]:
    if not _in_base(root, head):
        yield f"commity spoza {BASE}"
    if threads is not None and branch in threads.branches:
        yield "aktywny wątek T3"
    if _fresh_without_own_work(root, f"refs/heads/{branch}", head):
        yield FRESH


def _tree_state(path: Path) -> Iterable[str]:
    state = repo.git_dir(path)
    if any((state / name).exists() for name in IN_PROGRESS):
        yield "w trakcie rebase, merge'a albo bisect"
    status = repo.git(path, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=normal", "--ignored=traditional")
    changed: list[str] = []
    kept: list[str] = []
    for entry in filter(None, status.split("\0")):
        code, name = entry[:2], entry[3:]
        if code not in ("??", "!!"):
            changed.append(name)
        elif not _reproducible(name) and _holds_data(path / name):
            (changed if code == "??" else kept).append(name)
    if changed:
        yield f"zmiany w drzewie ({_few(changed)})"
    if kept:
        yield f"pliki ignorowane ({_few(kept)})"


def _reproducible(name: str) -> bool:
    parts = Path(name).parts
    return any(part in REPRODUCIBLE or part.endswith(REPRODUCIBLE_SUFFIXES) for part in parts) or parts[-1:] == (".DS_Store",)


def _holds_data(path: Path) -> bool:
    """Plik albo katalog z co najmniej jednym niepustym plikiem spoza odtwarzalnych (pusty plik blokady nic nie niesie)."""

    if not path.is_dir():
        return path.is_symlink() or path.stat().st_size > 0
    for folder, dirs, files in os.walk(path):
        dirs[:] = [name for name in dirs if not _reproducible(name)]
        if any(_holds_data(Path(folder) / name) for name in files if not _reproducible(name)):
            return True
    return False


def _few(names: list[str]) -> str:
    shown = ", ".join(sorted(names)[:3])
    return shown if len(names) <= 3 else f"{shown} i {len(names) - 3} innych"


def _in_base(root: Path, head: str) -> bool:
    """HEAD jest przodkiem ``origin/main`` albo jego scalenie z ``origin/main`` daje drzewo ``origin/main`` (squash)."""

    if repo.is_ancestor(root, head, BASE):
        return True
    try:
        merged = repo.merge_tree(root, BASE, head)
    except subprocess.CalledProcessError:
        return False  # historie bez wspólnej bazy
    return not merged.conflicts and merged.tree == repo.git(root, "rev-parse", f"{BASE}^{{tree}}").strip()


def _fresh_without_own_work(cwd: Path, ref: str, head: str) -> bool:
    """``ref`` stoi tam, gdzie go utworzono, a utworzono go w ostatniej dobie (reflog, najnowszy wpis pierwszy)."""

    entries = [line.split(" ", 1) for line in repo.git(cwd, "log", "-g", "--date=unix", "--format=%H %gd", ref).splitlines()]
    if not entries:
        return False
    created, when = entries[-1]
    return created == head and time.time() - int(when.rpartition("@{")[2].rstrip("}")) < FRESH_S


def _remove(root: Path, verdict: _Verdict, here: Path, threads: _Threads | None) -> str | None:
    """Usuwa po ponownej ocenie tuż przed usunięciem; zwraca powód, gdy coś zostaje."""

    tree = verdict.worktree
    if tree is not None:
        again = _judge_tree(root, replace(tree, head=_head(tree)), here, _busy(), threads)
        if again.reasons or again.head != tree.head:
            return ", ".join(again.reasons) or "HEAD zmienił się w trakcie"
        removed = repo.run_git(root, "worktree", "remove", str(tree.path), timeout=REMOVE_TIMEOUT_S)
        if removed.returncode:
            return f"git odmówił ({_first_line(removed)})"
    if verdict.branch is None:
        return None
    head = repo.commit(root, f"refs/heads/{verdict.branch}")
    if head is None:
        return None
    if head != verdict.head:
        return "gałąź przesunęła się w trakcie"
    try:
        repo.git(root, "branch", "--delete", "--force", verdict.branch)
    except subprocess.CalledProcessError as refused:
        return f"git odmówił ({_first_line(refused)})"
    return None


def _head(tree: Worktree) -> str:
    try:
        return repo.git(tree.path, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _busy() -> frozenset[str] | None:
    """Ścieżki katalogów roboczych i otwartych plików procesów użytkownika; ``None``, gdy nie da się ich sprawdzić."""

    lsof = shutil.which("lsof")
    if sys.platform == "win32" or lsof is None:
        return None
    try:
        listed = potomne.run([lsof, "-n", "-w", "-F", "n"], cwd=Path.home(), timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    names = frozenset(line[1:] for line in listed.stdout.splitlines() if line.startswith("n/"))
    # lsof kończy się kodem 1 także wtedy, gdy nie widzi niektórych plików; pusta lista znaczy, że nie zadziałał.
    return names or None


def _t3_threads(root: Path, project: Path) -> _Threads | None:
    """Worktree i gałęzie wątków T3, które biegną albo czekają na Maksa; ``None``, gdy T3 nie odpowiada."""

    installed = Path.home() / ".t3" / "bin" / "t3"
    t3 = str(installed) if installed.is_file() else shutil.which("t3")
    if t3 is None:
        return None
    paths, branches = set(), set()
    try:
        listed = json.loads(_t3(root, t3, "thread", "list", "--project", str(project), "--json"))
        for thread in listed:
            if thread["status"] in CLOSED_T3 and thread["settled"]:
                continue
            shown = json.loads(_t3(root, t3, "thread", "show", str(thread["threadId"]), "--messages", "0", "--json"))["thread"]
            if shown.get("worktreePath"):
                paths.add(Path(shown["worktreePath"]).resolve())
            if shown.get("branch"):
                branches.add(str(shown["branch"]))
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None
    return _Threads(frozenset(paths), frozenset(branches))


def _t3(root: Path, t3: str, *args: str) -> str:
    done = potomne.run([t3, *args], cwd=root, timeout=TIMEOUT_S)
    if done.returncode:
        raise OSError(_first_line(done))
    return done.stdout


def _fetch(root: Path) -> str | None:
    try:
        done = repo.run_git(root, "fetch", "--quiet", REMOTE, MAIN, timeout=FETCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"git fetch przekroczył {FETCH_TIMEOUT_S} s"
    return f"git fetch: {_first_line(done)}" if done.returncode else None


def _first_line(done: subprocess.CompletedProcess[str] | subprocess.CalledProcessError) -> str:
    return next(iter((done.stderr or done.stdout).strip().splitlines()), f"kod {done.returncode}")


if __name__ == "__main__":
    raise SystemExit(main())
