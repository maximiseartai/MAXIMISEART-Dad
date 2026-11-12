"""``tools/praca_w_toku.py`` pokazuje sesji pracę w toku z innych worktree tego samego repozytorium."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import TOOLS, built_once, commit, git, with_imports

from wplyw_zmiany import Repository

TOOL = Path(__file__).resolve().parents[1] / "tools" / "praca_w_toku.py"


def _git(cwd: Path, *args: str) -> None:
    try:
        subprocess.run(
            ["git", "-c", "user.name=Sesja", "-c", "user.email=sesja@example.invalid", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except subprocess.CalledProcessError as failed:
        failed.add_note(failed.stderr)
        raise


def _commit(cwd: Path, path: str, content: str, message: str) -> None:
    (cwd / path).write_text(content, encoding="utf-8")
    _git(cwd, "add", path)
    _git(cwd, "commit", "-m", message)


def _fake_gh(directory: Path, answer: str, code: int = 0) -> str:
    """``PATH`` z ``gh``, który na każde wywołanie wypisuje ``answer`` i kończy się kodem ``code``."""

    fake = directory / "gh-na-niby"
    fake.mkdir(exist_ok=True)
    (fake / "odpowiedz.json").write_text(answer, encoding="utf-8")
    fake_cli(fake, "gh", f"import pathlib, sys\nsys.stdout.buffer.write(pathlib.Path({str(fake / 'odpowiedz.json')!r}).read_bytes())\nsys.exit({code})\n")
    return f"{fake}{os.pathsep}{os.environ['PATH']}"


def _report(cwd: Path, *args: str, path: str | None = None) -> str:
    """Raport bez GitHuba albo z ``gh`` szukanym w ``path``."""

    completed = subprocess.run(
        [sys.executable, str(TOOL), *(["--lokalnie"] if path is None else []), *args],
        cwd=cwd,
        env=dict(os.environ) if path is None else {**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


@pytest.fixture
def checkouts(tmp_path: Path) -> dict[str, Path]:
    """Repo z originem i trzema worktree: inna sesja z pracą, sesja bez pracy i bieżący checkout."""

    built_once(tmp_path, _checkouts)
    return {"other": tmp_path / "inna-sesja", "current": tmp_path / "biezacy"}


def _checkouts(directory: Path) -> None:
    origin, main = directory / "origin.git", directory / "main"
    _git(directory, "init", "--bare", "-b", "main", str(origin))
    _git(directory, "clone", str(origin), str(main))
    _commit(main, "wspolny.py", "a = 1\n", "start")
    _commit(main, "inny.py", "b = 1\n", "drugi plik")
    _git(main, "push", "-u", "origin", "main")

    other, idle, current = directory / "inna-sesja", directory / "bez-pracy", directory / "biezacy"
    _git(main, "worktree", "add", "-b", "fix/opiekun", str(other))
    _commit(other, "wspolny.py", "a = 2\n", "fix(centrum): opiekun nie cofa bez startu (#7)")
    (other / "szkic.py").write_text("c = 1\n", encoding="utf-8")
    _git(main, "worktree", "add", "-b", "t3/bez-pracy", str(idle))
    _git(main, "worktree", "add", "-b", "feat/moje", str(current))
    _commit(current, "wspolny.py", "a = 3\n", "feat: moje")
    (current / "szkic.py").write_text("c = 2\n", encoding="utf-8")
    (current / "inny.py").write_text("b = 2\n", encoding="utf-8")


def test_issue_znajduje_galaz_ktorej_commit_odwoluje_sie_do_zgloszenia(checkouts: dict[str, Path]) -> None:
    assert "fix/opiekun" in _report(checkouts["current"], "--issue", "7")
    assert "fix/opiekun" not in _report(checkouts["current"], "--issue", "8")


def test_galaz_zbudowana_na_innej_naklada_sie_tylko_wlasnymi_commitami(checkouts: dict[str, Path]) -> None:
    stacked = checkouts["other"].parent / "na-opiekunie"
    _git(checkouts["other"], "worktree", "add", "-b", "fix/na-opiekunie", str(stacked), "fix/opiekun")
    _commit(stacked, "inny.py", "b = 3\n", "fix: na opiekunie")

    overlaps = _report(stacked, "--nakladania")

    lines = overlaps.splitlines()
    assert not [line for line in lines if line.startswith("- fix/opiekun")]
    assert "inny.py" in next(line for line in lines if line.startswith("- feat/moje"))


def test_przeniesienie_naklada_sie_stara_sciezka(checkouts: dict[str, Path]) -> None:
    moving = checkouts["other"].parent / "przenosze"
    _git(checkouts["other"], "worktree", "add", "-b", "feat/przenosze", str(moving), "main")
    _git(moving, "mv", "wspolny.py", "przeniesiony.py")
    _git(moving, "commit", "-m", "refactor: przenoszę wspolny.py")
    _git(moving, "mv", "inny.py", "inny2.py")

    github_only = '[{"number": 9, "headRefName": "fix/zdalna", "title": "", "body": "", "files": [{"path": "wspolny.py"}]}]'

    lines = _report(moving, "--nakladania", path=_fake_gh(moving.parent, github_only)).splitlines()

    assert "wspolny.py" in next(line for line in lines if line.startswith("- fix/opiekun"))
    assert "- fix/zdalna (PR #9): wspolny.py" in lines
    mine = next(line for line in lines if line.startswith("- feat/moje"))
    assert "wspolny.py" in mine  # przeniesiony w commicie tutaj, zmieniony w commicie tam
    assert "inny.py" in mine  # przeniesiony tutaj bez commita, zmieniony tam bez commita


def test_zly_ksztalt_odpowiedzi_gh_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[{}]"))

    assert "GITHUB POMINIĘTY" in report
    assert "fix/opiekun" in report  # praca lokalna nadal w raporcie


@pytest.mark.parametrize("gh", ["brak", "pada"])
def test_bez_odpowiedzi_gh_raport_jak_lokalnie(checkouts: dict[str, Path], gh: str) -> None:
    current = checkouts["current"]
    if gh == "brak":
        path = os.pathsep.join(
            folder
            for folder in os.environ["PATH"].split(os.pathsep)
            if not any((Path(folder) / name).exists() for name in ("gh", "gh.exe"))
        )
        if shutil.which("git", path=path) is None:
            pytest.skip("gh leży w tym samym folderze co git")
    else:
        path = _fake_gh(current.parent, "[]", code=4)

    skipped, *report = _report(current, path=path).splitlines()

    assert skipped == ("GITHUB POMINIĘTY | brak gh" if gh == "brak" else "GITHUB POMINIĘTY | gh: kod 4")
    assert report == _report(current).splitlines()[1:]


def test_zly_ksztalt_tresci_zgloszenia_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[]"))

    assert report.count("GITHUB POMINIĘTY") == 1
    assert "fix/opiekun" in report  # praca lokalna nadal w raporcie


WSPOLNY = "a = 1\nb = 1\nc = 1\nd = 1\ne = 1\n"
NIEPOTRZEBNA = "AKTUALIZACJA: niepotrzebna (bez konfliktu, bez wspólnych plików)"


def _branch_from_main(tmp_path: Path) -> tuple[Path, Path]:
    """Origin z ``main``, jego klon i worktree gałęzi ``feat/galaz`` z ``origin/main``; zwraca klon i worktree."""

    built_once(tmp_path, _build_branch_from_main)
    return tmp_path / "main", tmp_path / "galaz"


def _build_branch_from_main(directory: Path) -> None:
    origin, main, branch = directory / "origin.git", directory / "main", directory / "galaz"
    _git(directory, "init", "--bare", "-b", "main", str(origin))
    _git(directory, "clone", str(origin), str(main))
    _commit(main, "wspolny.py", WSPOLNY, "start")
    _commit(main, "inny.py", "x = 1\n", "drugi plik")
    _git(main, "push", "-u", "origin", "main")
    _git(main, "worktree", "add", "-b", "feat/galaz", str(branch), "origin/main")


def test_kazdy_test_ma_wlasne_repozytorium_z_worktree_choc_proces_buduje_je_raz(tmp_path: Path) -> None:
    changed_main, changed = _branch_from_main(tmp_path / "zmieniany")
    untouched = _branch_from_main(tmp_path / "nietkniety")
    _commit(changed, "inny.py", "x = 2\n", "tylko w zmienianym")
    _git(changed_main, "worktree", "add", "-b", "feat/tylko-tu", str(tmp_path / "zmieniany" / "nowy"))

    for main, branch in (untouched, _branch_from_main(tmp_path / "pozniejszy")):
        worktrees = git(main, "worktree", "list", "--porcelain").splitlines()
        assert [Path(line.removeprefix("worktree ")) for line in worktrees if line.startswith("worktree ")] == [
            main.resolve(),
            branch.resolve(),
        ]
        assert git(branch, "log", "-1", "--format=%s") == "drugi plik"
        assert (git(main, "diff-files", "--name-only"), git(branch, "diff-files", "--name-only")) == ("", "")


def test_kopia_narzedzia_ma_te_same_moduly_co_z_grafu_calego_repozytorium() -> None:
    """``with_imports`` liczy graf importów samych ``tools/``; plik ``tools/``, który dochodzi do innego pliku ``tools/``
    przez ``tests/``, ``src/`` albo skrypt skilla, dałby kopię narzędzia bez tego pliku, a test z tą kopią przeszedłby
    albo padł z powodu ImportError, nie tego, który sprawdza."""

    root = TOOL.parents[1]
    full = Repository.scan(root)
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    expected = {
        name: sorted({name, *(found for found in full.imported(name) if found.startswith("tools/"))})
        for name in listed
        if name.startswith("tools/")
    }

    assert {name: copied for name, wanted in expected.items() if (copied := with_imports([name])) != wanted} == {}
    assert all(len(expected[name]) > 1 for name in TOOLS)
    with pytest.raises(ValueError, match="tylko pliki tools/"):
        with_imports([".agents/skills/verify-a/scripts/a.py"])


def _compared(checkout: Path) -> str:
    """Koniec werdyktu, który nazywa ``origin/main``, z którym porównano gałąź."""

    return f" | origin/main {git(checkout, 'log', '-1', '--format=%h', 'origin/main')}"


def _merged_on_github(tmp_path: Path, files: dict[str, str]) -> None:
    """Commity na ``main`` z innego klonu, jak merge PR na GitHubie."""

    github = tmp_path / "github"
    _git(tmp_path, "clone", str(tmp_path / "origin.git"), str(github))
    for path, content in files.items():
        _commit(github, path, content, f"zmiana {path}")
    _git(github, "push", "origin", "main")


@pytest.mark.parametrize(
    ("in_branch", "on_main", "verdict"),
    [
        pytest.param({"inny.py": "x = 2\n"}, {"wspolny.py": WSPOLNY.replace("a = 1", "a = 3")}, NIEPOTRZEBNA, id="bez konfliktu"),
        pytest.param(
            {"wspolny.py": WSPOLNY.replace("a = 1", "a = 2")},
            {"wspolny.py": WSPOLNY.replace("a = 1", "a = 3")},
            "AKTUALIZACJA: potrzebna (konflikt w: wspolny.py)",
            id="konflikt",
        ),
        pytest.param(
            {"wspolny.py": WSPOLNY.replace("a = 1", "a = 2")},
            {"wspolny.py": WSPOLNY.replace("e = 1", "e = 3")},
            "AKTUALIZACJA: potrzebna (bez konfliktu, wspólne pliki: wspolny.py)",
            id="wspólny plik bez konfliktu",
        ),
        pytest.param({}, {}, NIEPOTRZEBNA, id="gałąź równa main"),
    ],
)
def test_aktualizacja_z_main_tylko_przy_konflikcie_albo_wspolnym_pliku(
    tmp_path: Path, in_branch: dict[str, str], on_main: dict[str, str], verdict: str
) -> None:
    main, branch = _branch_from_main(tmp_path)
    for path, content in in_branch.items():
        _commit(branch, path, content, f"moja zmiana {path}")
    if on_main:
        _merged_on_github(tmp_path, on_main)
    _git(main, "fetch")

    assert _report(branch).splitlines()[-1] == f"{verdict}{_compared(branch)}"
    assert _report(branch, "--aktualizacja") == f"{verdict}{_compared(branch)}\n"


@pytest.mark.parametrize(
    ("fetch", "note"),
    [
        pytest.param("w innym worktree", "", id="w innym worktree"),
        pytest.param("sprzed 3 h", " z fetch sprzed 3 h, odśwież: git fetch origin", id="sprzed 3 h"),
        pytest.param("brak", " bez śladu fetch, odśwież: git fetch origin", id="brak"),
        pytest.param("z adresu, bez origin/main", " bez śladu fetch, odśwież: git fetch origin", id="z adresu, bez origin/main"),
    ],
)
def test_werdykt_mowi_gdy_zaden_fetch_nie_potwierdzil_origin_main_w_ostatniej_godzinie(
    tmp_path: Path, fetch: str, note: str
) -> None:
    main, branch = _branch_from_main(tmp_path)
    coordinator = tmp_path / "koordynator"
    _git(main, "worktree", "add", "--detach", str(coordinator), "origin/main")
    if fetch == "w innym worktree":
        _git(coordinator, "fetch")
    elif fetch == "sprzed 3 h":
        _git(main, "fetch")
        hours_ago = time.time() - 3 * 3600 - 60
        os.utime(main / ".git" / "FETCH_HEAD", (hours_ago, hours_ago))
    elif fetch == "z adresu, bez origin/main":
        _merged_on_github(tmp_path, {"inny.py": "x = 2\n"})
        _git(coordinator, "fetch", str(tmp_path / "origin.git"), "main")

    assert _report(branch, "--aktualizacja") == f"{NIEPOTRZEBNA}{_compared(branch)}{note}\n"


@pytest.mark.parametrize("backend", ["--merge", "--apply"])
def test_rebase_odlaczonego_head_na_konflikcie_dotyczy_commitu_sprzed_rebase(tmp_path: Path, backend: str) -> None:
    main, branch = _branch_from_main(tmp_path)
    _git(branch, "switch", "--detach")
    _commit(branch, "inny.py", "x = 2\n", "przenosi się bez konfliktu")
    _commit(branch, "wspolny.py", WSPOLNY.replace("a = 1", "a = 2"), "konflikt z main")
    _merged_on_github(tmp_path, {"wspolny.py": WSPOLNY.replace("a = 1", "a = 3")})
    _git(main, "fetch")
    with pytest.raises(subprocess.CalledProcessError):
        _git(branch, "rebase", backend, "origin/main")

    assert _report(branch, "--aktualizacja") == f"AKTUALIZACJA: potrzebna (konflikt w: wspolny.py){_compared(branch)}\n"


@pytest.mark.parametrize(
    ("repository", "verdict"),
    [
        pytest.param("bez bazy scalenia", "AKTUALIZACJA: nieznana (git merge-tree: ", id="bez bazy scalenia"),
        pytest.param("bez origin/main", "AKTUALIZACJA: nieznana (brak origin/main)\n", id="bez origin/main"),
    ],
)
def test_gdy_git_nie_scali_galezi_z_main_werdykt_jest_nieznany(tmp_path: Path, repository: str, verdict: str) -> None:
    main, branch = _branch_from_main(tmp_path)
    if repository == "bez bazy scalenia":
        _git(branch, "switch", "--orphan", "feat/bez-historii")
        _commit(branch, "inny.py", "x = 9\n", "bez historii main")
        _git(main, "fetch")
    else:
        _git(main, "update-ref", "-d", "refs/remotes/origin/main")

    assert _report(branch, "--aktualizacja").startswith(verdict)


@dataclass(frozen=True)
class _Commit:
    name: str
    files: frozenset[str]
    merge: bool = False
    on_remote: bool = False


@dataclass(frozen=True)
class _Checkout:
    """Linia pracy w świecie testu: commity spoza ``main`` i niezacommitowane pliki, jak je zbudowano."""

    branch: str | None
    path: Path | None
    commits: frozenset[_Commit]
    dirty: frozenset[str] = frozenset()
    pr: int | None = None
    pr_files: frozenset[str] = frozenset()

    def changed(self, other: _Checkout) -> frozenset[str]:
        """Pliki zmieniane we własnych commitach (bez wspólnych z ``other``) albo niezacommitowane."""

        return frozenset().union(*(commit.files for commit in self.commits - other.commits)) | self.dirty


_REMOTE = _Commit("zdalna", frozenset({"zdalny.py"}), on_remote=True)
_MERGE = _Commit("merge", frozenset(), merge=True)
_REMOTE_LATER = _Commit("zdalna-dalej", frozenset({"szkic.py"}), on_remote=True)
_UNFETCHED = _Commit("niepobrana", frozenset({"pr-plik.py"}))
# Obie strony przepisują jedyną linię pliku, więc plik zmieniony tu i w nowym main to konflikt.
_MAIN_LATER = _Commit("nowy main", frozenset({"rebasowany.py"}))
_GITHUB_ONLY = (
    _Checkout("zdalna", None, frozenset({_REMOTE, _REMOTE_LATER}), pr=9, pr_files=_REMOTE.files | _REMOTE_LATER.files),
    _Checkout("niepobrana", None, frozenset({_UNFETCHED}), pr=10, pr_files=_UNFETCHED.files),
)
_PULL_REQUESTS = {
    "inny-g-wlasny-czysty": (8, {"wspolny.py", "tylko-w-pr.py"}),
    "ja": (7, {"wspolny.py"}),
    **{side.branch or "": (side.pr, side.pr_files) for side in _GITHUB_ONLY},
}


def _expected_report(me: _Checkout, world: list[_Checkout], github: bool, compared: str) -> list[str]:
    """Raport ze specyfikacji w docstringu narzędzia, wyliczony z modelu świata, nie z Gita."""

    on_branches = {commit for side in world if side.branch is not None for commit in side.commits}

    def in_progress(side: _Checkout) -> bool:
        if side.dirty or (side.branch is not None and side.commits):
            return True
        own = [c for c in side.commits if not (c.merge or c.on_remote or c in on_branches)]
        return side.branch is None and bool(own)

    others = [side for side in world if side is not me and in_progress(side)] + (list(_GITHUB_ONLY) if github else [])
    lines = ["GITHUB POMINIĘTY | --lokalnie"] if not github else []
    lines.append(f"PRACA W TOKU | inne: {len(others)} | odniesienie: {me.path} ({me.branch or 'odłączony HEAD'})")
    overlaps = []
    for side in others:
        parts = [side.branch or "odłączony HEAD"]
        parts += [f"PR #{side.pr}"] if github and side.pr is not None else []
        files = frozenset().union(*(commit.files for commit in side.commits)) | side.dirty
        if side in _GITHUB_ONLY:
            parts += ["tylko na GitHubie", f"niezacommitowane 0, pliki {len(side.pr_files)}"]
        else:
            ahead, unpushed = len(side.commits), len([c for c in side.commits if not c.on_remote])
            files |= side.pr_files if github else frozenset()
            parts += [str(side.path) if side.path else "bez worktree"]
            parts += [f"przed origin/main {ahead}, niewypchnięte {unpushed}, niezacommitowane {len(side.dirty)}, pliki {len(files)}"]
            parts += ["praca"] if any(not c.merge for c in side.commits) else []
        lines.append("- " + " | ".join(parts))
        shared = me.changed(side) & side.changed(me)
        if shared:
            name = side.branch or f"odłączony HEAD {side.path}"
            pr = f" (PR #{side.pr})" if github and side.pr is not None else ""
            overlaps.append(f"- {name}{pr}: {', '.join(sorted(shared))}")
    lines += ["NAKŁADANIA | pliki zmieniane tu i w innej pracy w toku", *overlaps] if overlaps else ["NAKŁADANIA | brak"]
    clash = sorted(frozenset().union(*(commit.files for commit in me.commits)) & _MAIN_LATER.files)
    verdict = f"potrzebna (konflikt w: {', '.join(clash)})" if clash else "niepotrzebna (bez konfliktu, bez wspólnych plików)"
    lines.append(f"AKTUALIZACJA: {verdict}{compared} bez śladu fetch, odśwież: git fetch origin")
    return sorted(lines)


def _world(tmp_path: Path) -> list[_Checkout]:
    """Worktree w każdej kombinacji: HEAD dołączony albo odłączony × commity × niezacommitowane pliki, plus rebase obu backendów i bisect."""

    origin, main = tmp_path / "origin.git", tmp_path / "main"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch", "main", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    for name in ("wspolny.py", "szkic.py", "przenoszony.py", "zdalny.py", "rebasowany.py"):
        (main / name).write_text("x = 0\n", encoding="utf-8")
    commit(main, "start")
    git(main, "push", "--quiet", "--set-upstream", "origin", "main")
    git(main, "switch", "--quiet", "--create", "zdalna")
    (main / "zdalny.py").write_text("x = 1\n", encoding="utf-8")
    commit(main, "praca")
    git(main, "push", "--quiet", "origin", "zdalna")
    git(main, "switch", "--quiet", "--create", "zdalna-druga", "main")
    (main / "zdalny.py").write_text("x = 2\n", encoding="utf-8")
    commit(main, "praca")
    git(main, "push", "--quiet", "origin", "zdalna-druga")
    git(main, "switch", "--quiet", "main")
    git(main, "branch", "--quiet", "--delete", "--force", "zdalna", "zdalna-druga")

    def worktree(name: str, attached: bool, start: str = "main") -> Path:
        path = tmp_path / name
        git(main, "worktree", "add", "--quiet", *(["-b", name] if attached else ["--detach"]), str(path), start)
        return path.resolve()

    def write(path: Path, files: frozenset[str]) -> None:
        for name in files:
            (path / name).write_text(f"x = '{path.name}'\n", encoding="utf-8")

    world = []
    for attached, commits, dirty in itertools.product(
        (True, False), ("brak", "wlasny", "przeniesienie", "merge", "na-remote"), ("czysty", "zmiana", "przeniesienie")
    ):
        name = f"inny-{'g' if attached else 'o'}-{commits}-{dirty}"
        path = worktree(name, attached, "origin/zdalna" if commits == "na-remote" else "main")
        made: frozenset[_Commit] = frozenset()
        moved = "przenoszony.py"
        if commits == "wlasny":
            own = _Commit(name, frozenset({"wspolny.py"}))
            write(path, own.files)
            commit(path, "praca")
            made = frozenset({own})
        elif commits == "przeniesienie":
            moved = f"{name}.py"
            git(path, "mv", "przenoszony.py", moved)
            commit(path, "praca")
            made = frozenset({_Commit(name, frozenset({"przenoszony.py", moved}))})
        elif commits == "merge":
            git(path, "merge", "--quiet", "--no-ff", "--no-edit", "origin/zdalna")
            made = frozenset({_REMOTE, _MERGE})
        elif commits == "na-remote":
            made = frozenset({_REMOTE})
        changed: frozenset[str] = frozenset()
        if dirty == "zmiana":
            changed = frozenset({"szkic.py"})
            write(path, changed)
        elif dirty == "przeniesienie":
            changed = frozenset({moved, f"{name}-brudny.py"})
            (path / moved).rename(path / f"{name}-brudny.py")
        pr, pr_files = _PULL_REQUESTS.get(name, (None, set()))
        world.append(_Checkout(name if attached else None, path, made, changed, pr, frozenset(pr_files)))

    pushed = worktree("tylko-na-remote", False, "origin/zdalna-druga")
    world.append(_Checkout(None, pushed, frozenset({_Commit("zdalna-druga", frozenset({"zdalny.py"}), on_remote=True)})))

    sandbox = worktree("piaskownica", False, "inny-g-wlasny-czysty")
    world.append(_Checkout(None, sandbox, next(side for side in world if side.branch == "inny-g-wlasny-czysty").commits))

    without = worktree("bez-worktree", True)
    write(without, frozenset({"wspolny.py"}))
    commit(without, "praca")
    git(main, "worktree", "remove", str(without))
    world.append(_Checkout("bez-worktree", None, frozenset({_Commit("bez-worktree", frozenset({"wspolny.py"}))})))

    deleted = worktree("usuniety", True)
    write(deleted, frozenset({"wspolny.py"}))
    commit(deleted, "praca")
    shutil.rmtree(deleted)
    world.append(_Checkout("usuniety", None, frozenset({_Commit("usuniety", frozenset({"wspolny.py"}))})))

    rebasing, rebasing_detached = worktree("rebasuje", True), worktree("rebasuje-odlaczony", False)
    rebasing_apply = worktree("rebasuje-apply", True)
    rebased = _Commit("rebasuje", frozenset({"wspolny.py", "rebasowany.py"}))
    for path in (rebasing, rebasing_detached, rebasing_apply):
        write(path, rebased.files)
        commit(path, "praca")
    world.append(_Checkout("rebasuje", rebasing, frozenset({rebased}), rebased.files))
    world.append(_Checkout("rebasuje-apply", rebasing_apply, frozenset({_Commit("rebasuje-apply", rebased.files)}), rebased.files))
    # Odłączony HEAD w trakcie rebase stoi na nowym main, a jego commit zna już tylko reflog.
    world.append(_Checkout(None, rebasing_detached, frozenset(), rebased.files))

    bisecting = worktree("szuka", True)
    searched = []
    for number in ("jeden", "dwa", "trzy"):
        write(bisecting, frozenset({f"szuka-{number}.py"}))
        commit(bisecting, "praca")
        searched.append(_Commit(f"szuka-{number}", frozenset({f"szuka-{number}.py"})))
    git(bisecting, "bisect", "start", "szuka", "origin/main")
    world.append(_Checkout("szuka", bisecting, frozenset(searched)))

    mine_dirty = frozenset({"szkic.py", "przenoszony.py", "nowy plik ł.py"})
    for name, attached in (("ja", True), ("ja-odlaczony", False)):
        path = worktree(name, attached)
        mine = _Commit(name, frozenset({"wspolny.py", "zdalny.py"}))
        write(path, mine.files)
        commit(path, "praca")
        write(path, mine_dirty)
        pr, pr_files = _PULL_REQUESTS.get(name, (None, set()))
        world.append(_Checkout(name if attached else None, path, frozenset({mine}), mine_dirty, pr, frozenset(pr_files)))

    stacked = worktree("ja-na-zdalnej", True, "origin/zdalna")
    write(stacked, frozenset({"wspolny.py"}))
    commit(stacked, "praca")
    write(stacked, frozenset({"szkic.py", "zdalny.py"}))
    stacked_commits = frozenset({_REMOTE, _Commit("ja-na-zdalnej", frozenset({"wspolny.py"}))})
    world.append(_Checkout("ja-na-zdalnej", stacked, stacked_commits, frozenset({"szkic.py", "zdalny.py"})))

    # PR #9 idzie dalej po zbudowaniu na nim ja-na-zdalnej: jego nowy commit zmienia szkic.py, tu niezacommitowany.
    git(main, "switch", "--quiet", "--create", "zdalna", "origin/zdalna")
    write(main, _REMOTE_LATER.files)
    commit(main, "praca")
    git(main, "push", "--quiet", "origin", "zdalna")
    git(main, "switch", "--quiet", "main")
    git(main, "branch", "--quiet", "--delete", "--force", "zdalna")

    write(main, _MAIN_LATER.files)
    commit(main, "nowy main")
    git(main, "push", "--quiet", "origin", "main")
    for path, backend in ((rebasing, "--merge"), (rebasing_detached, "--merge"), (rebasing_apply, "--apply")):
        with pytest.raises(subprocess.CalledProcessError):
            git(path, "rebase", backend, "origin/main")  # konflikt w rebasowany.py zatrzymuje rebase
    return world


# Każdy stan „ja” stoi w tym samym świecie jako osobny worktree, a dla pozostałych stanów jest zwykłą stroną modelu.
# Uruchomienia narzędzia biegną naraz: każde to ok. 400 gitów, głównie start procesu (25–37 ms na Windows), i pięć po kolei
# przekroczyło tam limit czasu testu (#1133). Jeden test buduje świat raz, a nie raz na worker xdist.
_STATES = (("ja", True), ("ja-odlaczony", False), ("ja-na-zdalnej", True), ("rebasuje", False), ("szuka", False))


@pytest.mark.dlugi
def test_raport_zgodny_ze_specyfikacja_w_kazdym_stanie_repozytorium(tmp_path: Path) -> None:
    world = _world(tmp_path)
    answer = json.dumps(
        [
            {"number": pr, "headRefName": branch, "title": "", "body": "", "files": [{"path": p} for p in sorted(files)]}
            for branch, (pr, files) in _PULL_REQUESTS.items()
        ]
    )
    with_github, compared = _fake_gh(tmp_path, answer), _compared(tmp_path / "main")

    def report(name: str, github: bool) -> list[str]:
        return sorted(_report(tmp_path / name, path=with_github if github else None).splitlines())

    with ThreadPoolExecutor(len(_STATES)) as pool:
        reports = [pool.submit(report, name, github) for name, github in _STATES]

    mismatches = []
    for (name, github), future in zip(_STATES, reports, strict=True):
        [me] = [side for side in world if side.path == (tmp_path / name).resolve()]
        expected, actual = _expected_report(me, world, github=github, compared=compared), future.result()
        mismatches += [f"{name}: brak {line}" for line in expected if line not in actual]
        mismatches += [f"{name}: nadmiar {line}" for line in actual if line not in expected]
    assert not mismatches, "\n".join(mismatches)
