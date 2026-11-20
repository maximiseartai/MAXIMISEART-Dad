"""Odpowiada sesji na trzy pytania: czy ktoś zajmuje jej zgłoszenie, czy aktywna praca zmienia jej pliki, czy aktualizować z main; użyj przed startem issue.

Narzędzie nie wylicza pracy w repozytorium. Zaczyna od bieżącego checkoutu (tego, w którym je uruchomiono), jego
plików i numeru zgłoszenia, i szuka tylko innej pracy, która się z nimi przecina. Bez ``--issue`` i bez plików
checkoutu nie ma o co pytać, więc nie czyta innych worktree ani GitHuba. Skrypt tylko czyta.

Pliki checkoutu to pliki jego własnych commitów spoza ``origin/main`` (bez merge) i jego niezacommitowane pliki.
Linia pracy to inna lokalna gałąź z własnymi commitami spoza ``origin/main`` albo niezacommitowanymi plikami, odłączony
HEAD innego worktree albo otwarty PR (z lokalną gałęzią albo bez niej). Odłączony HEAD liczy się z niezacommitowanymi
plikami albo z commitem innym niż merge, którego nie ma żadna gałąź ani remote (inaczej to piaskownica albo przegląd).
Worktree w trakcie rebase albo bisect gałęzi pracuje na tej gałęzi, tak jak uznaje git. Kopia commitu narzędzia
(``potomne.commit_copy``) ani worktree w trakcie ``git worktree add`` (HEAD bez commitu) nie jest linią pracy, a
bieżący checkout i jego gałąź nie są inną pracą.

Linia pracy jest aktywna, gdy ma otwarty PR albo dała znak życia w ostatnich ``AKTYWNA_S`` sekundach (doba): commit
na jej czubku (data commitera), wpis reflogu jej gałęzi, zapis indeksu albo HEAD jej worktree, zmiana jej
niezacommitowanego pliku, który nakłada się z checkoutem. Niezacommitowane pliki innego worktree narzędzie czyta
(``git status``) tylko wtedy, gdy ten worktree w ostatniej dobie zapisał indeks albo HEAD albo zmienił plik checkoutu
(usunięcie pliku zmienia jego katalog), a z ``--wszystkie`` w każdym worktree.

Nakładanie to plik, który checkout i inna linia pracy zmieniają, każdy we własnych commitach albo niezacommitowanych.
Commity wspólne obu stron (gałąź zbudowana na innej) się nie liczą. Przeniesienie pliku liczy się jako zmiana starej
i nowej ścieżki. PR bez lokalnej gałęzi ma swoje commity w ``origin/<gałąź>``, jeśli ją pobrano, a inaczej jego pliki
z GitHuba przecinają się z plikami checkoutu.

Zgłoszenie #N zajmuje linia pracy, aktywna czy nie, której nazwa gałęzi ma N jako osobny człon (cyfry, najwyżej pięć,
odcięte od reszty nazwy przez ``/``, ``-``, ``_`` albo jej brzeg, jak w ``feat/legenda-1940-ostrzezenia``), której commit
spoza ``origin/main`` albo tytuł lub opis PR odwołuje się do #N, albo której PR wskazuje treść zgłoszenia #N. Aktywność
nie zmienia tej odpowiedzi: nieaktywną linię pracy odpowiedź nazywa z wiekiem jej ruchu, liczonym jak w nakładaniach.

PR samego procesu to otwarty PR autora, który nie jest botem, ze zmienionymi plikami wyłącznie z ``PROCESS_DIRS`` albo
``PROCESS_FILES`` (narzędzia, skille, CI, hooki, dokumenty agentów, ADR-y, reguły i testy). Koordynator ma naraz
najwyżej ``PROCESS_LIMIT`` takich PR-ów (#2348, decyzja agenta), więc przy pełnym limicie nowa jednostka samego procesu
czeka, aż któryś się scali albo zamknie; pracy produktu limit nie dotyczy.

Raport kończy się liniami odpowiedzi w tej kolejności, więc ``tail -3`` (z ``--issue`` ``tail -4``) daje same
odpowiedzi. Nad nimi stoją szczegóły, jedna linia na linię pracy, od najświeższego ruchu: najpierw każda linia, która
zajmuje zgłoszenie (z jego powodem), potem aktywne linie, które nakładają się z checkoutem (z plikami, najwyżej
``SHOWN_FILES``), z ``--wszystkie`` także nieaktywne:

    - <gałąź albo odłączony HEAD>[ (PR #M)] | <worktree> | bez worktree | tylko na GitHubie | ruch <wiek> temu | <powód albo pliki>
    PROCES W TOKU | <n> z <limit>[ (PR #A, #B)]; nowa jednostka samego procesu może ruszyć | czeka, aż któryś się scali albo zamknie
    ZGŁOSZENIE #N | zajęte: <linia pracy>[ (<wiek>, nieaktywna)], …; poprawka należy do właściciela tej gałęzi
    ZGŁOSZENIE #N | wolne
    NAKŁADANIA | brak | aktywne prace na twoich plikach: <k> (wyżej)[; nieaktywne: <m>, pokaż: --wszystkie]
    AKTUALIZACJA: potrzebna (…) | niepotrzebna (…) | nieznana (…) | origin/main <sha>[ uwaga o fetch]

Linię ``PROCES W TOKU`` raport ma tylko z ``--issue`` (bez GitHuba: ``nieznane``). Bez ``--issue`` linia
``ZGŁOSZENIE`` mówi, jak zapytać, a bez plików checkoutu ``NAKŁADANIA`` mówi, że checkout nic nie zmienia. Liczba
nieaktywnych nakładań liczy tylko commity, bo niezacommitowanych plików nieaktywnych worktree narzędzie nie czyta. Gdy
GitHub nie odpowiedział, linia odpowiedzi, która go potrzebowała, kończy się ``| bez GitHuba: <powód>``.
Raport informuje i nie blokuje: kod wyjścia 0, inny tylko przy błędnym użyciu.

``AKTUALIZACJA``: gałąź bieżącego checkoutu aktualizuje się z ``origin/main`` (rebase albo merge), gdy
``git merge-tree`` widzi konflikt albo gałąź i ``origin/main`` zmieniają od bazy scalenia ten sam plik. Liczą się
commity, nie niezacommitowane pliki. W trakcie rebase odłączonego HEAD werdykt dotyczy commitu sprzed rebase.
Werdykt nie pobiera ``origin/main``: podaje commit ``origin/main``, z którym porównał, a gdy żaden fetch
w tym repozytorium nie potwierdził go w ostatniej godzinie, dopisuje to. ``git merge-tree`` dodaje do bazy
obiektów tylko nieosiągalne obiekty scalenia, które usuwa ``git gc``.

    py -3 tools/praca_w_toku.py                  # Windows
    python3 tools/praca_w_toku.py                # macOS i Linux
    python3 tools/praca_w_toku.py --issue 212    # przed startem zgłoszenia #212
    python3 tools/praca_w_toku.py --nakladania   # tylko nakładania (drukuje je tools/ci_lokalnie.py)
    python3 tools/praca_w_toku.py --aktualizacja # tylko werdykt aktualizacji (brama pre-push)
    python3 tools/praca_w_toku.py --lokalnie     # bez GitHuba
    python3 tools/praca_w_toku.py --wszystkie    # także nieaktywne nakładania (czyta każdy worktree)
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
import potomne
from repo import BASE
import repo


AKTYWNA_S = 24 * 3600
# Na Macu Maksa git status ze ścieżkami checkoutu w 120 worktree trwa przy 4 wątkach ok. 0,4 s.
STATUS_THREADS = 4
# Linia polecenia Windows ma najwyżej 32 767 znaków; dłuższa lista plików checkoutu idzie do git status bez ścieżek.
PATHSPEC_CHARS = 16_000
SHOWN_FILES = 5
TIMEOUT_S = 30
FRESH_FETCH_S = 3600
ISSUE_REFERENCE = re.compile(r"#(\d+)\b")
PR_REFERENCE = re.compile(r"(?:#|/pull/)(\d+)\b")
BRANCH_NUMBER = re.compile(r"(?:^|[/_-])(\d{1,5})(?=$|[/_-])")
ASK_ISSUE = "nie podano; przed startem zgłoszenia N: tools/praca_w_toku.py --issue N"
PROCESS_LIMIT = 2
PROCESS_DIRS = ("tools/", ".agents/", ".github/", ".claude/", "docs/agents/", "docs/adr/", "reguly-ast-grep/", "tests/")
PROCESS_FILES = frozenset({"AGENTS.md", "CODING_STANDARDS.md", "ruff.toml", "sgconfig.yml", ".importlinter"})


@dataclass(frozen=True)
class Commits:
    """Commity spoza ``origin/main`` osiągalne z podanych czubków, z jednego ``git log``.

    ``own(tip)`` to dokładnie ``origin/main..tip``, a pliki ``own(a) - own(b)`` to dokładnie
    ``git log a ^origin/main ^b --name-only`` (merge bez plików, jak w ``git log``), więc pytania o parę linii pracy
    to działania na zbiorach SHA zamiast gita na każdą gałąź.
    """

    parents: Mapping[str, tuple[str, ...]]
    files: Mapping[str, frozenset[str]]
    time: Mapping[str, int]
    issues: Mapping[str, frozenset[int]]

    @classmethod
    def read(cls, root: Path, tips: Iterable[str]) -> Commits:
        log = repo.git(root, "log", "--no-renames", "--name-only", "-z", "--format=%x01%H %P%x02%ct%x02%B%x02", *tips, f"^{BASE}")
        parents: dict[str, tuple[str, ...]] = {}
        files: dict[str, frozenset[str]] = {}
        times: dict[str, int] = {}
        issues: dict[str, frozenset[int]] = {}
        for record in log.split("\x01")[1:]:
            header, committed, rest = record.split("\x02", 2)
            body, _, names = rest.rpartition("\x02")
            sha, *above = header.split()
            parents[sha] = tuple(above)
            files[sha] = frozenset(name.lstrip("\n") for name in names.split("\0")) - {""}
            times[sha] = int(committed)
            issues[sha] = _issues(body)
        return cls(parents, files, times, issues)

    def own(self, *tips: str | None) -> frozenset[str]:
        """Commity osiągalne z któregoś z ``tips`` spoza ``origin/main``."""

        seen: set[str] = set()
        stack = [tip for tip in tips if tip is not None and tip in self.parents]
        while stack:
            sha = stack.pop()
            if sha not in seen:
                seen.add(sha)
                stack += [parent for parent in self.parents[sha] if parent in self.parents]
        return frozenset(seen)

    def touched(self, commits: Iterable[str]) -> frozenset[str]:
        return frozenset[str]().union(*(self.files[sha] for sha in commits))

    def merge(self, sha: str) -> bool:
        return len(self.parents[sha]) > 1


@dataclass(frozen=True)
class Me:
    """Bieżący checkout: jego gałąź (także rebasowana albo bisectowana), własne commity i pliki."""

    root: Path
    branch: str | None
    own: frozenset[str]
    dirty: frozenset[str]
    files: frozenset[str]

    @classmethod
    def read(cls, root: Path, branch: str | None) -> Me:
        commits = Commits.read(root, ["HEAD"])
        own = frozenset(commits.parents)
        dirty = _status(root)
        return cls(root, branch, own, dirty, commits.touched(own) | dirty)


@dataclass(frozen=True)
class Tree:
    """Inny worktree z ``git worktree list`` i plików jego katalogu gita, bez procesów."""

    path: Path
    branch: str | None
    head: str
    seen: float

    @classmethod
    def read(cls, found: repo.Worktree, root: Path, branches: Mapping[str, str]) -> Tree | None:
        if found.missing or found.head is None or found.path == root or potomne.is_commit_copy(found.path):
            return None
        git_dir = _git_dir(found.path)
        if git_dir is None:
            return None  # inna sesja właśnie usunęła ten worktree
        branch = found.branch or _busy_branch(git_dir, branches.__contains__)
        # logs/HEAD nie jest znakiem życia: git gc przepisuje reflogi wszystkich worktree naraz.
        return cls(found.path, branch, found.head, max(_mtime(git_dir / "index"), _mtime(git_dir / "HEAD")))


@dataclass(frozen=True)
class World:
    """Inna praca w jednej chwili: worktree, gałęzie, gałęzie zdalne i graf ich commitów spoza ``origin/main``."""

    trees: tuple[Tree, ...]
    branches: Mapping[str, str]
    remotes: Mapping[str, str]
    commits: Commits
    on_refs: frozenset[str]
    common: Path
    now: float

    @classmethod
    def read(cls, me: Me) -> World:
        listed = repo.git(me.root, "for-each-ref", "refs/heads", "refs/remotes", "--format=%(refname) %(objectname)")
        refs = dict(line.rsplit(" ", 1) for line in listed.splitlines() if line)
        branches = {ref.removeprefix("refs/heads/"): sha for ref, sha in refs.items() if ref.startswith("refs/heads/")}
        remotes = {ref: sha for ref, sha in refs.items() if ref.startswith("refs/remotes/")}
        trees = tuple(tree for found in repo.worktrees(me.root) if (tree := Tree.read(found, me.root, branches)) is not None)
        detached = dict.fromkeys(tree.head for tree in trees if tree.branch is None)
        commits = Commits.read(me.root, ["--branches", "--remotes", "HEAD", *detached])
        on_refs = commits.own(*branches.values(), *remotes.values())
        return cls(trees, branches, remotes, commits, on_refs, repo.common_dir(me.root), time.time())


@dataclass(frozen=True)
class PullRequest:
    number: int
    branch: str
    issues: frozenset[int]
    files: frozenset[str]
    bot: bool

    def process_only(self) -> bool:
        return not self.bot and bool(self.files) and all(name in PROCESS_FILES or name.startswith(PROCESS_DIRS) for name in self.files)


@dataclass(frozen=True)
class GitHub:
    """Otwarte PR-y i treść zgłoszenia albo powód, dla którego ich nie ma (``--lokalnie``, brak gh, błąd, kształt).

    ``issue_skipped`` mówi, czemu odpowiedź o zgłoszeniu jest bez GitHuba: brak PR-ów albo treści zgłoszenia.
    """

    pulls: tuple[PullRequest, ...]
    issue_body: str
    pulls_skipped: str | None
    issue_skipped: str | None


@dataclass(frozen=True)
class Work:
    """Kandydat na linię pracy: gałąź, odłączony HEAD worktree albo PR bez lokalnej gałęzi (``local`` fałszywe)."""

    branch: str | None
    tree: Tree | None
    tip: str | None
    pr: PullRequest | None
    local: bool


@dataclass(frozen=True)
class Line:
    """Kandydat z plikami wspólnymi z checkoutem i ostatnim ruchem, liczony raz dla obu odpowiedzi."""

    work: Work
    files: frozenset[str]
    seen: float

    def active(self, now: float) -> bool:
        return self.work.pr is not None or now - self.seen < AKTYWNA_S

    def name(self) -> str:
        pr = f" (PR #{self.work.pr.number})" if self.work.pr is not None else ""
        return f"{self.work.branch or 'odłączony HEAD'}{pr}"

    def claimant(self, now: float) -> str:
        return self.name() if self.active(now) else f"{self.name()} ({_age(now - self.seen)}, nieaktywna)"

    def detail(self, now: float, what: str) -> str:
        if self.work.tree is not None:
            place = str(self.work.tree.path)
        else:
            place = "bez worktree" if self.work.local else "tylko na GitHubie"
        moved = f"ruch {_age(now - self.seen)} temu" if self.seen else "ruch nieznany"
        return f"- {self.name()} | {place} | {moved} | {what}"


@dataclass(frozen=True)
class Claim:
    line: Line
    reasons: tuple[str, ...]


class _GitHubSkipped(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", type=int, metavar="N", help="Także: kto zajmuje zgłoszenie #N.")
    parser.add_argument("--lokalnie", action="store_true", help="Bez wywołań gh.")
    parser.add_argument("--nakladania", action="store_true", help="Tylko nakładania.")
    parser.add_argument("--aktualizacja", action="store_true", help="Tylko werdykt, czy aktualizować z origin/main.")
    parser.add_argument("--wszystkie", action="store_true", help="Także nieaktywne nakładania; czyta każdy worktree.")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        # Ścieżki i nazwy gałęzi mogą mieć znaki spoza strony kodowej konsoli Windows.
        sys.stdout.reconfigure(errors="replace")
    try:
        root = repo.toplevel(Path.cwd())
    except (OSError, subprocess.CalledProcessError):
        print("BŁĄD: uruchom w checkoucie repozytorium git.", file=sys.stderr)
        return 2
    issue = None if args.nakladania else args.issue
    if repo.commit(root, BASE) is None:
        unknown = f"nieznane (brak {BASE})"
        answers = [f"NAKŁADANIA | {unknown}"]
        if not args.nakladania:
            answers = [f"{_issue_title(issue)} | {unknown}", *answers, f"{AKTUALIZACJA}nieznana (brak {BASE})"]
        print("\n".join(answers[-1:] if args.aktualizacja else answers))
        return 0

    branch = repo.git(root, "branch", "--show-current").strip() or _busy_branch(
        repo.git_dir(root), lambda name: repo.succeeds(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}")
    )
    if args.aktualizacja:
        print(_update_verdict(root, branch))
        return 0
    me = Me.read(root, branch)
    claimed: list[Claim] | None = None
    overlapping: list[Line] | None = None
    gh = GitHub((), "", "--lokalnie", "--lokalnie")
    if issue is not None or me.files:
        with ThreadPoolExecutor(1) as pool:
            asked = None if args.lokalnie else pool.submit(_github, root, issue)
            world = World.read(me)
            statused = _candidate_trees(world, me.files, args.wszystkie) if me.files else []
            dirty = _dirty_hits(statused, me.files)
            gh = gh if asked is None else asked.result()
        lines = _lines(me, world, _works(me, world, gh), dirty)
        if issue is not None:
            claimed = claims(issue, world, gh, lines)
        if me.files:
            overlapping = overlaps(world, lines, dirty, frozenset(tree.path for tree in statused))
        now = world.now
    else:
        now = time.time()
    for line in render(issue, claimed, overlapping, gh, now, everything=args.wszystkie, nakladania=args.nakladania):
        print(line)
    if not args.nakladania:
        print(_update_verdict(root, branch))
    return 0


def _works(me: Me, world: World, gh: GitHub) -> list[Work]:
    pulls = {pr.branch: pr for pr in gh.pulls}
    checked_out = {tree.branch: tree for tree in world.trees if tree.branch is not None}
    works = [Work(name, checked_out.get(name), tip, pulls.get(name), True) for name, tip in world.branches.items() if name != me.branch]
    works += [Work(None, tree, tree.head, None, True) for tree in world.trees if tree.branch is None]
    works += [
        Work(pr.branch, None, world.remotes.get(f"refs/remotes/origin/{pr.branch}"), pr, False)
        for pr in gh.pulls
        if pr.branch not in world.branches and pr.branch != me.branch
    ]
    return works


def _candidate_trees(world: World, files: frozenset[str], everything: bool) -> list[Tree]:
    """Worktree, których niezacommitowane pliki mogą być aktywnym nakładaniem: samym ``os.stat``, bez procesów."""

    if everything:
        return list(world.trees)
    since = world.now - AKTYWNA_S
    return [tree for tree in world.trees if tree.seen > since or any(_touched_at(tree.path, name) > since for name in files)]


def _dirty_hits(trees: list[Tree], files: frozenset[str]) -> dict[Path, frozenset[str]]:
    paths = [f":(literal){name}" for name in sorted(files)]
    limit = ("--", *paths) if sum(map(len, paths)) < PATHSPEC_CHARS else ()

    def hit(tree: Tree) -> frozenset[str]:
        try:
            return _status(tree.path, *limit) & files
        except (OSError, subprocess.SubprocessError):
            return frozenset()  # inna sesja właśnie usunęła ten worktree

    with ThreadPoolExecutor(STATUS_THREADS) as pool:
        return {tree.path: found for tree, found in zip(trees, pool.map(hit, trees), strict=True) if found}


def _lines(me: Me, world: World, works: list[Work], dirty: Mapping[Path, frozenset[str]]) -> list[Line]:
    """Każdy kandydat raz, z plikami, które nakładają się z checkoutem, i z ruchem, który liczy ich zmiany."""

    commits = world.commits
    found = []
    for work in works:
        theirs_dirty = dirty.get(work.tree.path, frozenset()) if work.tree is not None else frozenset()
        if work.pr is not None and work.tip is None:
            files = me.files & work.pr.files
        else:
            theirs = commits.own(work.tip)
            files = (commits.touched(me.own - theirs) | me.dirty) & (commits.touched(theirs - me.own) | theirs_dirty)
        found.append(_line(work, world, files, theirs_dirty & files))
    return found


def overlaps(world: World, lines: list[Line], dirty: Mapping[Path, frozenset[str]], statused: frozenset[Path]) -> list[Line]:
    """Linie pracy, aktywne i nie, które nakładają się z checkoutem; niezacommitowane pliki znane tylko w ``statused``."""

    def working(line: Line) -> bool:
        tree = line.work.tree
        if tree is not None and tree.path in dirty:
            return True  # niezacommitowany plik checkoutu w tym worktree to już praca, bez drugiego git status
        return _is_work(line.work, world, read_tree=tree is not None and tree.path in statused)

    return [line for line in lines if line.files and working(line)]


def claims(issue: int, world: World, gh: GitHub, lines: list[Line]) -> list[Claim]:
    """Linie pracy, aktywne i nie, które zajmują zgłoszenie ``issue``."""

    referenced = {int(number) for number in PR_REFERENCE.findall(gh.issue_body)} - {issue}
    found = []
    for line in lines:
        work = line.work
        reasons = []
        if issue in _branch_issues(work.branch):
            reasons.append("nazwa gałęzi")
        if any(issue in world.commits.issues[sha] for sha in world.commits.own(work.tip)):
            reasons.append(f"commit odwołuje się do #{issue}")
        if work.pr is not None and issue in work.pr.issues:
            reasons.append(f"PR odwołuje się do #{issue}")
        if work.pr is not None and work.pr.number in referenced:
            reasons.append(f"#{issue} wskazuje PR #{work.pr.number}")
        if reasons and _is_work(work, world, read_tree=True):
            found.append(Claim(line, tuple(reasons)))
    return found


def _is_work(work: Work, world: World, read_tree: bool) -> bool:
    """Czy kandydat to linia pracy (docstring modułu); niezacommitowane pliki czyta tylko z ``read_tree``."""

    theirs = world.commits.own(work.tip)
    if work.pr is not None or (work.branch is not None and theirs):
        return True
    if work.branch is None and any(not world.commits.merge(sha) for sha in theirs - world.on_refs):
        return True
    if not read_tree or work.tree is None:
        return False
    try:
        return bool(_status(work.tree.path))
    except (OSError, subprocess.SubprocessError):
        return False  # inna sesja właśnie usunęła ten worktree


def _line(work: Work, world: World, files: frozenset[str], dirty: Iterable[str]) -> Line:
    signs = [float(world.commits.time.get(work.tip or "", 0))]
    if work.tree is not None:
        signs += [work.tree.seen, *(_touched_at(work.tree.path, name) for name in dirty)]
    if work.local and work.branch is not None:
        signs.append(_reflog_time(world.common, work.branch))
    return Line(work, files, max(signs))


def render(
    issue: int | None,
    claimed: list[Claim] | None,
    overlapping: list[Line] | None,
    gh: GitHub,
    now: float,
    *,
    everything: bool,
    nakladania: bool,
) -> list[str]:
    """Szczegóły, potem odpowiedzi ``PROCES W TOKU`` (z ``issue``), ``ZGŁOSZENIE`` i ``NAKŁADANIA`` (bez ``AKTUALIZACJA``, którą drukuje ``main``)."""

    details: list[str] = []
    answers: list[str] = []
    if not nakladania:
        if claimed is None:
            answers.append(f"{_issue_title(issue)} | {ASK_ISSUE}")
        else:
            answers.append(_process_in_progress(gh))
            ordered = sorted(claimed, key=lambda claim: -claim.line.seen)
            details += [claim.line.detail(now, ", ".join(claim.reasons)) for claim in ordered]
            claimants = ", ".join(claim.line.claimant(now) for claim in ordered)
            answer = f"zajęte: {claimants}; poprawka należy do właściciela tej gałęzi" if claimants else "wolne"
            answers.append(f"{_issue_title(issue)} | {answer}{_without(gh.issue_skipped)}")
    if overlapping is None:
        answers.append("NAKŁADANIA | brak: ten checkout jeszcze niczego nie zmienia")
    else:
        ordered_overlaps = sorted(overlapping, key=lambda line: -line.seen)
        active_overlaps = [line for line in ordered_overlaps if line.active(now)]
        shown = ordered_overlaps if everything else active_overlaps
        details += [line.detail(now, _named(line.files)) for line in shown]
        answer = f"aktywne prace na twoich plikach: {len(active_overlaps)} (wyżej)" if active_overlaps else "brak"
        if inactive := len(ordered_overlaps) - len(active_overlaps):
            answer += f"; nieaktywne: {inactive} (wyżej)" if everything else f"; nieaktywne: {inactive}, pokaż: --wszystkie"
        answers.append(f"NAKŁADANIA | {answer}{_without(gh.pulls_skipped)}")
    return details + answers


def _process_in_progress(gh: GitHub) -> str:
    if gh.pulls_skipped is not None:
        return f"PROCES W TOKU | nieznane{_without(gh.pulls_skipped)}"
    numbers = sorted(pr.number for pr in gh.pulls if pr.process_only())
    listed = f" (PR {', '.join(f'#{number}' for number in numbers)})" if numbers else ""
    verdict = "czeka, aż któryś się scali albo zamknie" if len(numbers) >= PROCESS_LIMIT else "może ruszyć"
    return f"PROCES W TOKU | {len(numbers)} z {PROCESS_LIMIT}{listed}; nowa jednostka samego procesu {verdict}"


def _issue_title(issue: int | None) -> str:
    return "ZGŁOSZENIE" if issue is None else f"ZGŁOSZENIE #{issue}"


def _without(skipped: str | None) -> str:
    return "" if skipped is None else f" | bez GitHuba: {skipped}"


def _named(files: frozenset[str]) -> str:
    names = sorted(files)
    shown = ", ".join(names[:SHOWN_FILES])
    return shown if len(names) <= SHOWN_FILES else f"{shown} i {len(names) - SHOWN_FILES} innych"


def _age(seconds: float) -> str:
    if seconds < 3600:
        return "<1 h"
    if seconds < 2 * 24 * 3600:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // (24 * 3600))} d"


def _git_dir(worktree: Path) -> Path | None:
    """Katalog gita worktree z jego ``.git`` (katalog głównego checkoutu albo plik ``gitdir:`` dołączonego)."""

    dot_git = worktree / ".git"
    if dot_git.is_dir():
        return dot_git
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return (worktree / text.removeprefix("gitdir:").strip()).resolve() if text.startswith("gitdir:") else None


def _busy_branch(git_dir: Path, exists: Callable[[str], bool]) -> str | None:
    """Gałąź, którą odłączony HEAD worktree przebudowuje (rebase) albo przeszukuje (bisect)."""

    for name in ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"):
        try:
            branch = (git_dir / name).read_text(encoding="utf-8").strip().removeprefix("refs/heads/")
        except OSError:
            continue
        # Rebase odłączonego HEAD zapisuje "detached HEAD", a bisect z odłączonego HEAD hash commita.
        if exists(branch):
            return branch
    return None


def _reflog_time(common: Path, branch: str) -> float:
    """Czas ostatniego wpisu reflogu gałęzi z jego treści: mtime plików reflogu przepisuje ``git gc``."""

    try:
        entries = (common / "logs" / "refs" / "heads" / branch).read_bytes().splitlines()
    except OSError:
        return 0.0
    for entry in reversed(entries):
        identity = entry.split(b"\t", 1)[0].rsplit(b" ", 2)
        if len(identity) == 3 and identity[1].isdigit():
            return float(identity[1])
    return 0.0


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _touched_at(tree: Path, name: str) -> float:
    """mtime pliku ``name`` w ``tree``, a pliku, którego nie ma, najbliższego istniejącego katalogu nad nim."""

    path = tree / name
    for place in (path, *path.parents):
        try:
            return place.stat().st_mtime
        except OSError:
            if place == tree:
                break
    return 0.0


def _github(root: Path, issue: int | None) -> GitHub:
    try:
        pulls = _pull_requests(root)
    except _GitHubSkipped as skipped:
        return GitHub((), "", str(skipped), str(skipped))
    if issue is None:
        return GitHub(pulls, "", None, None)
    try:
        return GitHub(pulls, _issue_body(root, issue), None, None)
    except _GitHubSkipped as skipped:
        return GitHub(pulls, "", None, str(skipped))


def _pull_requests(root: Path) -> tuple[PullRequest, ...]:
    fields = "number,headRefName,title,body,files,author"
    answer = _gh(root, "pr", "list", "--state", "open", "--limit", "200", "--json", fields)
    try:
        return tuple(
            PullRequest(
                number=int(pr["number"]),
                branch=str(pr["headRefName"]),
                issues=_issues(f"{pr['title']}\n{pr['body'] or ''}"),
                files=frozenset(str(file["path"]) for file in pr["files"] or ()),
                bot=bool(pr["author"]["is_bot"]),
            )
            for pr in answer
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _GitHubSkipped(f"gh pr list: nieoczekiwana odpowiedź ({error!r})") from error


def _issue_body(root: Path, issue: int) -> str:
    answer = _gh(root, "issue", "view", str(issue), "--json", "body")
    try:
        return str(answer["body"] or "")
    except (KeyError, TypeError) as error:
        raise _GitHubSkipped(f"gh issue view: nieoczekiwana odpowiedź ({error!r})") from error


def _update_verdict(root: Path, branch: str | None) -> str:
    """Q9: gałąź aktualizuje się z ``origin/main`` tylko przy konflikcie albo pliku zmienionym po obu stronach."""

    ref = f"refs/heads/{branch}" if branch is not None else _before_rebase(root) or "HEAD"
    try:
        merged = repo.merge_tree(root, ref, BASE)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr.strip().splitlines() or [f"kod {error.returncode}"])[0]
        return f"{AKTUALIZACJA}nieznana (git merge-tree: {reason}){_base_note(root)}"
    if merged.conflicts:
        verdict = f"potrzebna (konflikt w: {', '.join(sorted(merged.conflicts))})"
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


def _status(worktree: Path, *limit: str) -> frozenset[str]:
    status = repo.git(worktree, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all", *limit)
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
