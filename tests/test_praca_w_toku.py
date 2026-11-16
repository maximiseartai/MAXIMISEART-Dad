"""``tools/praca_w_toku.py`` odpowiada sesji, czy ktoś zajmuje jej zgłoszenie, czy aktywna praca zmienia jej pliki i czy aktualizować z main."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import TOOLS, built_once, commit, git, with_imports

import potomne
from wplyw_zmiany import Repository

TOOL = Path(__file__).resolve().parents[1] / "tools" / "praca_w_toku.py"
# Trzy doby temu: linia pracy bez znaku życia w ostatniej dobie (AKTYWNA_S w docstringu narzędzia).
STALE_S = 3 * 24 * 3600 + 60
LOCAL = " | bez GitHuba: --lokalnie"
ASK = "ZGŁOSZENIE | nie podano; przed startem zgłoszenia N: tools/praca_w_toku.py --issue N"


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


def _fake_gh(directory: Path, answer: str, code: int = 0, issue: str | None = None) -> str:
    """``PATH`` z ``gh``, który wypisuje ``answer`` (na ``gh issue`` ``issue``, gdy podane) i kończy się kodem ``code``."""

    fake = directory / "gh-na-niby"
    fake.mkdir(exist_ok=True)
    (fake / "odpowiedz.json").write_text(answer, encoding="utf-8")
    (fake / "zgloszenie.json").write_text(answer if issue is None else issue, encoding="utf-8")
    script = (
        "import pathlib, sys\n"
        "name = 'zgloszenie.json' if sys.argv[1:2] == ['issue'] else 'odpowiedz.json'\n"
        f"sys.stdout.buffer.write((pathlib.Path({str(fake)!r}) / name).read_bytes())\nsys.exit({code})\n"
    )
    fake_cli(fake, "gh", script)
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


def _age_tree(path: Path) -> None:
    """Pliki i katalogi worktree oraz indeks i HEAD jego katalogu gita bez zmiany od ``STALE_S``."""

    stale = time.time() - STALE_S
    git_dir = Path(git(path, "rev-parse", "--absolute-git-dir"))
    for place in [path, *path.rglob("*"), git_dir / "index", git_dir / "HEAD"]:
        os.utime(place, (stale, stale))


def _stale_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commity i wpisy reflogu z datą sprzed ``STALE_S``, jak w pracy porzuconej trzy doby temu."""

    monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{int(time.time() - STALE_S)} +0000")


def test_issue_znajduje_galaz_ktorej_commit_odwoluje_sie_do_zgloszenia(checkouts: dict[str, Path]) -> None:
    taken = _report(checkouts["current"], "--issue", "7").splitlines()
    free = _report(checkouts["current"], "--issue", "8").splitlines()

    assert taken[-3] == f"ZGŁOSZENIE #7 | zajęte: fix/opiekun; poprawka należy do właściciela tej gałęzi{LOCAL}"
    assert f"- fix/opiekun | {checkouts['other']} | ruch <1 h temu | commit odwołuje się do #7" in taken
    assert free[-3] == f"ZGŁOSZENIE #8 | wolne{LOCAL}"


def test_issue_nazywa_nieaktywna_prace_nad_zgloszeniem_z_jej_wiekiem(checkouts: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    forgotten = checkouts["other"].parent / "zapomniany"
    with monkeypatch.context() as stale:
        _stale_commits(stale)
        _git(checkouts["other"], "worktree", "add", "-b", "fix/zapomniany", str(forgotten), "main")
        _commit(forgotten, "inny.py", "b = 4\n", "fix: zapomniane (#8)")
    _age_tree(forgotten)

    lines = _report(checkouts["current"], "--issue", "8").splitlines()

    assert lines[-3] == f"ZGŁOSZENIE #8 | zajęte: fix/zapomniany (3 d, nieaktywna); poprawka należy do właściciela tej gałęzi{LOCAL}"
    assert f"- fix/zapomniany | {forgotten.resolve()} | ruch 3 d temu | commit odwołuje się do #8" in lines


def test_issue_znajduje_pr_ktory_odwoluje_sie_do_zgloszenia_i_pr_wskazany_w_tresci_zgloszenia(checkouts: dict[str, Path]) -> None:
    pulls = [
        {"number": 5, "headRefName": "fix/opiekun", "title": "fix: opiekun", "body": "Część #42", "files": []},
        {"number": 6, "headRefName": "fix/zdalna", "title": "", "body": "", "files": []},
        {"number": 11, "headRefName": "fix/obok", "title": "", "body": "Część #420", "files": []},
    ]
    path = _fake_gh(checkouts["current"].parent, json.dumps(pulls), issue=json.dumps({"body": "Robi to PR #6."}))

    lines = _report(checkouts["current"], "--issue", "42", path=path).splitlines()

    assert lines[-3] == "ZGŁOSZENIE #42 | zajęte: fix/opiekun (PR #5), fix/zdalna (PR #6); poprawka należy do właściciela tej gałęzi"
    assert f"- fix/opiekun (PR #5) | {checkouts['other']} | ruch <1 h temu | PR odwołuje się do #42" in lines
    assert "- fix/zdalna (PR #6) | tylko na GitHubie | ruch nieznany | #42 wskazuje PR #6" in lines


def test_issue_znajduje_galaz_z_numerem_zgloszenia_jako_osobnym_czlonem_nazwy(checkouts: dict[str, Path]) -> None:
    named = ["feat/legenda-1940-ostrzezenia", "feat/krok-ukryc-1940", "1940_poprawka", "fix/1940"]
    unnamed = ["feat/legenda-19401", "feat/x1940", "fix/1940a", "fix/v1940-2"]
    for branch in named + unnamed:
        _git(checkouts["other"], "branch", branch, "fix/opiekun")

    lines = _report(checkouts["current"], "--issue", "1940").splitlines()

    assert sorted(line.split(" | ")[0].removeprefix("- ") for line in lines if line.endswith("| nazwa gałęzi")) == sorted(named)


def test_worktree_w_trakcie_git_worktree_add_nie_zmienia_raportu(checkouts: dict[str, Path]) -> None:
    before = _report(checkouts["current"], "--issue", "7")
    creating = checkouts["other"].parent / "tworzony"
    _git(checkouts["other"], "worktree", "add", "--detach", str(creating), "main")
    # Tak zostawia HEAD git worktree add, zanim ustawi go na commit.
    (Path(git(creating, "rev-parse", "--absolute-git-dir")) / "HEAD").write_text("0" * 40 + "\n", encoding="utf-8")

    assert _report(checkouts["current"], "--issue", "7") == before


def test_checkout_bez_zmian_i_bez_zgloszenia_dostaje_trzy_odpowiedzi_bez_githuba(tmp_path: Path) -> None:
    _, branch = _branch_from_main(tmp_path)
    fake = tmp_path / "gh-wolany"
    fake_cli(fake, "gh", "import pathlib\nimport sys\npathlib.Path(__file__).with_name('wolany').touch()\nsys.exit(4)\n")

    report = _report(branch, path=f"{fake}{os.pathsep}{os.environ['PATH']}").splitlines()

    assert report == [ASK, "NAKŁADANIA | brak: ten checkout jeszcze niczego nie zmienia", f"{NIEPOTRZEBNA}{_compared(branch)} bez śladu fetch, odśwież: git fetch origin"]
    assert not (fake / "wolany").exists()


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
    assert "- fix/zdalna (PR #9) | tylko na GitHubie | ruch nieznany | wspolny.py" in lines
    mine = next(line for line in lines if line.startswith("- feat/moje"))
    assert "wspolny.py" in mine  # przeniesiony w commicie tutaj, zmieniony w commicie tam
    assert "inny.py" in mine  # przeniesiony tutaj bez commita, zmieniony tam bez commita


def test_zly_ksztalt_odpowiedzi_gh_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[{}]")).splitlines()

    skipped = " | bez GitHuba: gh pr list: nieoczekiwana odpowiedź (KeyError('number'))"
    assert report[-3] == f"ZGŁOSZENIE #7 | zajęte: fix/opiekun; poprawka należy do właściciela tej gałęzi{skipped}"
    assert report[-2].endswith(skipped)


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

    reason = "brak gh" if gh == "brak" else "gh: kod 4"

    assert _report(current, path=path) == _report(current).replace(LOCAL, f" | bez GitHuba: {reason}")
    assert f" | bez GitHuba: {reason}" in _report(current, path=path).splitlines()[-2]


def test_zly_ksztalt_tresci_zgloszenia_to_raport_bez_githuba(checkouts: dict[str, Path]) -> None:
    report = _report(checkouts["current"], "--issue", "7", path=_fake_gh(checkouts["current"].parent, "[]")).splitlines()

    skipped = " | bez GitHuba: gh issue view: nieoczekiwana odpowiedź (TypeError('list indices must be integers or slices, not str'))"
    assert report[-3] == f"ZGŁOSZENIE #7 | zajęte: fix/opiekun; poprawka należy do właściciela tej gałęzi{skipped}"
    assert "bez GitHuba" not in report[-2]  # nakładania pytają tylko o PR-y, a te GitHub dał


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
    issues: frozenset[int] = frozenset()


@dataclass(frozen=True)
class _Checkout:
    """Linia pracy w świecie testu: commity spoza ``main`` i niezacommitowane pliki, jak je zbudowano."""

    branch: str | None
    path: Path | None
    commits: frozenset[_Commit]
    dirty: frozenset[str] = frozenset()
    pr: int | None = None
    pr_files: frozenset[str] = frozenset()
    # Commity, reflog, worktree i jego niezacommitowane pliki bez zmiany od STALE_S, oprócz plików ``fresh``.
    stale: bool = False
    fresh: frozenset[str] = frozenset()

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
# Zgłoszenie, o które pyta każde uruchomienie w świecie testu: zajmują je commity, opis PR #8 i PR #10 z treści zgłoszenia.
_ISSUE = 77
_CLAIMED = frozenset({_ISSUE})
_PR_BODIES = {"inny-g-wlasny-czysty": f"Część #{_ISSUE}"}
_POINTED_PR = 10
_ISSUE_BODY = f"Zrobi to PR #{_POINTED_PR}."
_PULL_REQUESTS = {
    "inny-g-wlasny-czysty": (8, {"wspolny.py", "tylko-w-pr.py"}),
    "ja": (7, {"wspolny.py"}),
    "stary-g-pr": (11, {"wspolny.py"}),
    **{side.branch or "": (side.pr, side.pr_files) for side in _GITHUB_ONLY},
}


def _expected_report(me: _Checkout, world: list[_Checkout], github: bool, compared: str, everything: bool) -> tuple[list[str], list[str]]:
    """Szczegóły (posortowane) i trzy odpowiedzi ze specyfikacji w docstringu narzędzia, z modelu świata, nie z Gita."""

    on_branches = {commit for side in world if side.branch is not None for commit in side.commits}

    def in_progress(side: _Checkout, dirty: frozenset[str]) -> bool:
        if side in _GITHUB_ONLY or dirty or (side.branch is not None and side.commits):
            return True
        own = [c for c in side.commits if not (c.merge or c.on_remote or c in on_branches)]
        return side.branch is None and bool(own)

    mine = frozenset().union(*(commit.files for commit in me.commits)) | me.dirty
    details, claimants, active, inactive = [], [], 0, 0
    for side in [side for side in world if side is not me] + (list(_GITHUB_ONLY) if github else []):
        with_pr = github and side.pr is not None
        # Świeża zmiana pliku, którego checkout nie zmienia, nie jest znakiem życia dla żadnej odpowiedzi.
        stale = side.stale and not side.fresh & mine
        place = "tylko na GitHubie" if side in _GITHUB_ONLY else str(side.path) if side.path else "bez worktree"
        name = f"{side.branch or 'odłączony HEAD'}{f' (PR #{side.pr})' if with_pr else ''}"
        fetched = side not in _GITHUB_ONLY or all(commit.on_remote for commit in side.commits)
        moved = f"ruch {'3 d' if stale else '<1 h'} temu" if fetched else "ruch nieznany"
        alive = with_pr or not stale

        reasons = [f"commit odwołuje się do #{_ISSUE}"] if any(_ISSUE in commit.issues for commit in side.commits) else []
        if with_pr and side.branch in _PR_BODIES:
            reasons.append(f"PR odwołuje się do #{_ISSUE}")
        if with_pr and side.pr == _POINTED_PR:
            reasons.append(f"#{_ISSUE} wskazuje PR #{side.pr}")
        # Zgłoszenie zajmuje linia pracy aktywna czy nie, a jej niezacommitowane pliki narzędzie czyta wtedy zawsze.
        if reasons and in_progress(side, side.dirty):
            details.append(f"- {name} | {place} | {moved} | {', '.join(reasons)}")
            claimants.append(name if alive else f"{name} (3 d, nieaktywna)")

        # Niezacommitowanych plików nieaktywnego worktree narzędzie nie czyta bez --wszystkie.
        dirty = side.dirty if everything or not stale else frozenset()
        theirs = frozenset().union(*(commit.files for commit in side.commits - me.commits)) | dirty
        shared = me.changed(side) & theirs
        if not shared or not in_progress(side, dirty):
            continue
        line = f"- {name} | {place} | {moved} | {', '.join(sorted(shared))}"
        if alive:
            active += 1
            details.append(line)
        else:
            inactive += 1
            details += [line] if everything else []
    claim = f"zajęte: {', '.join(claimants)}; poprawka należy do właściciela tej gałęzi" if claimants else "wolne"
    overlaps = f"aktywne prace na twoich plikach: {active} (wyżej)" if active else "brak"
    if inactive:
        overlaps += f"; nieaktywne: {inactive} (wyżej)" if everything else f"; nieaktywne: {inactive}, pokaż: --wszystkie"
    clash = sorted(frozenset().union(*(commit.files for commit in me.commits)) & _MAIN_LATER.files)
    verdict = f"potrzebna (konflikt w: {', '.join(clash)})" if clash else "niepotrzebna (bez konfliktu, bez wspólnych plików)"
    answers = [
        f"ZGŁOSZENIE #{_ISSUE} | {claim}{'' if github else LOCAL}",
        f"NAKŁADANIA | {overlaps}{'' if github else LOCAL}",
        f"AKTUALIZACJA: {verdict}{compared} bez śladu fetch, odśwież: git fetch origin",
    ]
    return sorted(details), answers


def _in_any_order(answers: list[str]) -> list[object]:
    """Odpowiedzi z liniami pracy ``zajęte:`` jako zbiorem: narzędzie szereguje je po ruchu, którego model nie zna."""

    head, taken, rest = answers[0].partition("zajęte: ")
    names, _, tail = rest.partition("; poprawka")
    claimants = sorted(re.split(r", (?![^(]*\))", names)) if taken else []
    return [head, claimants, tail, *answers[1:]]


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
            own = _Commit(name, frozenset({"wspolny.py"}), issues=_CLAIMED if dirty == "zmiana" else frozenset())
            write(path, own.files)
            commit(path, f"praca (#{_ISSUE})" if own.issues else "praca")
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

    # Każdy rodzaj linii pracy bez znaku życia od trzech dób, z szkic.py niezacommitowanym od trzech dób („stary”)
    # albo zmienionym już po postarzeniu worktree („świeży”).
    aged, fresh_edits = [], []
    with pytest.MonkeyPatch.context() as stale:
        _stale_commits(stale)
        for name, attached, committed, dirty in (
            ("stary-g-wlasny", True, True, "czysty"),
            ("stary-g-zmiana", True, False, "stary"),
            ("stary-o-wlasny", False, True, "czysty"),
            ("stary-o-zmiana", False, False, "stary"),
            ("stary-g-pr", True, True, "czysty"),
            ("stary-swiezy-plik", True, True, "świeży"),
            ("stary-bez-worktree", True, True, "czysty"),
        ):
            path = worktree(name, attached)
            made = frozenset({_Commit(name, frozenset({"wspolny.py"}), issues=_CLAIMED)}) if committed else frozenset()
            if committed:
                write(path, frozenset({"wspolny.py"}))
                commit(path, f"praca (#{_ISSUE})")
            changed = frozenset({"szkic.py"}) if dirty != "czysty" else frozenset()
            if dirty == "stary":
                write(path, changed)
            elif dirty == "świeży":
                fresh_edits.append(path)
            pr, pr_files = _PULL_REQUESTS.get(name, (None, set()))
            kept = name != "stary-bez-worktree"
            fresh = changed if dirty == "świeży" else frozenset()
            world.append(_Checkout(name if attached else None, path if kept else None, made, changed, pr, frozenset(pr_files), True, fresh))
            if kept:
                aged.append(path)
            else:
                git(main, "worktree", "remove", str(path))

    # Gałąź założona teraz na commicie sprzed trzech dób: świeży wpis reflogu to znak życia.
    git(main, "branch", "swieza-na-starym", "stary-bez-worktree")
    world.append(_Checkout("swieza-na-starym", None, next(side.commits for side in world if side.branch == "stary-bez-worktree")))

    # Piaskownica na commicie gałęzi zdalnej z niezacommitowanym plikiem spoza plików checkoutu to praca.
    beside = worktree("obok", False, "origin/zdalna")
    write(beside, frozenset({"obok.py"}))
    world.append(_Checkout(None, beside, frozenset({_REMOTE}), frozenset({"obok.py"})))

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
    for path in aged:
        _age_tree(path)
    for path in fresh_edits:
        write(path, frozenset({"szkic.py"}))
    return world


# Każdy stan „ja” stoi w tym samym świecie jako osobny worktree, a dla pozostałych stanów jest zwykłą stroną modelu.
# Uruchomienia narzędzia biegną naraz, bo na Windows każdy git to 25–37 ms startu procesu, a jeden test buduje świat
# raz, a nie raz na worker xdist.
_STATES = (("ja", True), ("ja-odlaczony", False), ("ja-na-zdalnej", True), ("rebasuje", False), ("szuka", False))


@pytest.mark.dlugi
def test_raport_zgodny_ze_specyfikacja_w_kazdym_stanie_repozytorium(tmp_path: Path) -> None:
    started = time.monotonic()
    world = _world(tmp_path)
    built = time.monotonic()
    answer = json.dumps(
        [
            {"number": pr, "headRefName": branch, "title": "", "body": _PR_BODIES.get(branch, ""), "files": [{"path": p} for p in sorted(files)]}
            for branch, (pr, files) in _PULL_REQUESTS.items()
        ]
    )
    with_github = _fake_gh(tmp_path, answer, issue=json.dumps({"body": _ISSUE_BODY}))
    compared = _compared(tmp_path / "main")

    def report(name: str, github: bool, everything: bool) -> list[str]:
        asked = ["--issue", str(_ISSUE), *(["--wszystkie"] if everything else [])]
        return _report(tmp_path / name, *asked, path=with_github if github else None).splitlines()

    runs = [(name, github, everything) for name, github in _STATES for everything in (False, True)]
    # Kopia commitu narzędzia z własnym commitem i plikami checkoutu nie jest linią pracy, choć wygląda jak praca.
    with potomne.commit_copy(tmp_path / "main", "origin/main") as copy:
        (copy / "wspolny.py").write_text("x = 'kopia'\n", encoding="utf-8")
        commit(copy, "praca")
        (copy / "szkic.py").write_text("x = 'kopia'\n", encoding="utf-8")
        with ThreadPoolExecutor(len(runs)) as pool:
            reports = [pool.submit(report, *run) for run in runs]
            results = [future.result() for future in reports]
    ran = time.monotonic()

    mismatches = []
    for (name, github, everything), actual in zip(runs, results, strict=True):
        [me] = [side for side in world if side.path == (tmp_path / name).resolve()]
        details, answers = _expected_report(me, world, github=github, compared=compared, everything=everything)
        run = f"{name}{' --wszystkie' if everything else ''}"
        mismatches += [f"{run}: brak {line}" for line in details if line not in actual[:-3]]
        mismatches += [f"{run}: nadmiar {line}" for line in actual[:-3] if line not in details]
        mismatches += [f"{run}: odpowiedzi {actual[-3:]} zamiast {answers}"] if _in_any_order(actual[-3:]) != _in_any_order(answers) else []
    assert not mismatches, "\n".join(mismatches)
    pytest.fail(f"POMIAR 1685 | świat {built - started:.1f} s | uruchomienia {ran - built:.1f} s | razem {ran - started:.1f} s")
