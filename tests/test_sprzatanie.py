"""``tools/sprzatanie.py`` raportuje, a z ``--usun`` usuwa lokalne worktree i gałęzie scalone do ``origin/main``; cudzą pracę zostawia."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import AUTHOR, commit, git

TOOL = Path(__file__).resolve().parents[1] / "tools" / "sprzatanie.py"
LONG_AGO = "2026-01-01T12:00:00+0000"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="na Windows narzędzie nie sprawdza procesów, więc niczego nie usuwa")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "dom"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GIT_COMMITTER_DATE", raising=False)
    return home


@pytest.fixture
def main(tmp_path: Path, home: Path) -> Path:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
    checkout = tmp_path / "glowny"
    git(tmp_path, "init", "--quiet", "--initial-branch=main", str(checkout))
    (checkout / ".gitignore").write_text(".venv/\nnode_modules/\n__pycache__/\n.benchmark/\n.noc/\n", encoding="utf-8")
    (checkout / "a.txt").write_text("a\n", encoding="utf-8")
    commit(checkout, "start")
    git(checkout, "remote", "add", "origin", str(origin))
    git(checkout, "push", "--quiet", "--set-upstream", "origin", "main")
    return checkout


def _cleanup(cwd: Path, *args: str) -> tuple[int, list[str]]:
    done = subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert not done.stderr
    return done.returncode, done.stdout.splitlines()


def _line(lines: list[str], what: str) -> str:
    [found] = [line for line in lines if f"{what} " in line or line.endswith(what)]
    return found


def _worktree(main: Path, name: str, *, long_ago: bool = True) -> Path:
    path = main.parent / name
    (_old_git if long_ago else git)(main, "worktree", "add", "--quiet", "-b", name, str(path), "origin/main")
    return path


def _old_git(repo: Path, *args: str) -> None:
    """Git z datą sprzed doby w reflogu: worktree albo gałąź bez własnych commitów, którą ktoś porzucił."""

    subprocess.run(["git", *args], cwd=repo, env={**os.environ, **AUTHOR, "GIT_COMMITTER_DATE": LONG_AGO}, capture_output=True, check=True)


def _branch_with_work(main: Path, name: str) -> Path:
    path = _worktree(main, name)
    (path / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    commit(path, f"feat: {name}")
    git(path, "push", "--quiet", "origin", name)
    return path


def _merge(main: Path, branch: str, *, squash: bool = False) -> None:
    if squash:
        git(main, "merge", "--quiet", "--squash", branch)
        commit(main, f"{branch} (squash)")
    else:
        git(main, "merge", "--quiet", "--no-ff", "--no-edit", branch)
    git(main, "push", "--quiet", "origin", "main")


def _branches(main: Path) -> set[str]:
    return set(git(main, "for-each-ref", "refs/heads", "--format=%(refname:short)").splitlines())


@pytest.mark.parametrize("squash", [False, True], ids=["merge", "squash"])
def test_scalony_worktree_znika_razem_z_galezia(main: Path, squash: bool) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione", squash=squash)

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert not path.exists()
    assert _branches(main) == {"main"}
    assert _line(lines, str(path)).startswith("- usunięte |")
    assert lines[-1] == "SPRZĄTANIE OK | usunięte 1 | zostawione 1 (główny checkout 1)"


def test_commity_spoza_origin_main_zostaja(main: Path) -> None:
    path = _branch_with_work(main, "w-toku")
    _merge(main, "w-toku")
    (path / "dalej.txt").write_text("niewypchnięte\n", encoding="utf-8")
    commit(path, "feat: niewypchnięte")

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert "w-toku" in _branches(main)
    assert _line(lines, str(path)).endswith("| commity spoza origin/main")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("a.txt", "zmiany w drzewie (a.txt)"),
        ("nowy.txt", "zmiany w drzewie (nowy.txt)"),
        (".noc/dziennik.tsv", "pliki ignorowane (.noc/)"),
    ],
    ids=["zmieniony", "nieśledzony", "ignorowany"],
)
def test_zmiany_w_drzewie_zostaja(main: Path, change: str, reason: str) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    (path / change).parent.mkdir(exist_ok=True)
    (path / change).write_text("praca, której nie ma w gicie\n", encoding="utf-8")

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert (path / change).is_file()
    assert _line(lines, str(path)).endswith(f"| {reason}")


def test_odtwarzalne_pliki_i_puste_blokady_nie_zatrzymuja(main: Path) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    for name in (".venv/bin/python", "node_modules/x/index.js", "__pycache__/a.pyc"):
        (path / name).parent.mkdir(parents=True)
        (path / name).write_text("odtwarzalne\n", encoding="utf-8")
    (path / ".benchmark").mkdir()
    (path / ".benchmark" / "reference.lock").touch()

    code, _ = _cleanup(main, "--usun")

    assert code == 0
    assert not path.exists()


@pytest.mark.parametrize("where", ["", "frontend"], ids=["korzen", "podkatalog"])
def test_worktree_z_zywym_procesem_zostaje(main: Path, where: str) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    (path / where).mkdir(exist_ok=True)
    with _process_in(path / where):
        code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert _line(lines, str(path)).endswith("| żywy proces")


@pytest.fixture
def fake_t3(home: Path) -> Path:
    return fake_cli(home / ".t3" / "bin", "t3", _FAKE_T3)


_FAKE_T3 = """import json, os, sys
threads = json.loads(os.environ["T3_WATKI"])
if sys.argv[2] == "list":
    print(json.dumps([{key: value for key, value in thread.items() if key != "worktreePath"} for thread in threads]))
else:
    [shown] = [thread for thread in threads if thread["threadId"] == sys.argv[3]]
    print(json.dumps({"thread": {"worktreePath": shown.get("worktreePath"), "branch": shown.get("branch")}}))
"""


@pytest.mark.parametrize(
    ("status", "settled", "kept"),
    [("running", True, True), ("completed", False, True), ("completed", True, False)],
    ids=["biegnie", "czeka-na-maksa", "zamkniety"],
)
def test_worktree_aktywnego_watku_t3_zostaje(
    main: Path, fake_t3: Path, monkeypatch: pytest.MonkeyPatch, status: str, settled: bool, kept: bool
) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    thread = {"threadId": "w1", "status": status, "settled": settled, "worktreePath": str(path)}
    monkeypatch.setenv("T3_WATKI", json.dumps([thread]))

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir() is kept
    assert _line(lines, str(path)).endswith("| aktywny wątek T3") is kept


def test_worktree_watku_t3_rozpoznany_po_galezi_zostaje(main: Path, fake_t3: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    thread = {"threadId": "w1", "status": "running", "settled": False, "branch": "zrobione"}
    monkeypatch.setenv("T3_WATKI", json.dumps([thread]))

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert _line(lines, str(path)).endswith("| aktywny wątek T3")


def test_worktree_t3_bez_odpowiedzi_t3_zostaje_tez_przez_dowiazanie_domu(main: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    linked = home.parent / "dom-dowiazanie"
    linked.symlink_to(home)
    monkeypatch.setenv("HOME", str(linked))
    t3_path = linked / ".t3" / "worktrees" / "MAXIMISEART-Dad" / "t3-zrobione"
    t3_path.parent.mkdir(parents=True)
    git(main, "worktree", "move", str(path), str(t3_path))

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert t3_path.is_dir()
    assert _line(lines, str(t3_path.resolve())).endswith("| stan wątku T3 nieznany")


def test_biezacy_checkout_zostaje(main: Path) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")

    code, lines = _cleanup(path, "--usun")

    assert code == 0
    assert path.is_dir()
    assert "| bieżący checkout" in _line(lines, str(path))


def test_nowy_worktree_bez_commitow_zostaje_a_porzucony_znika(main: Path) -> None:
    fresh = _worktree(main, "nowy", long_ago=False)
    abandoned = _worktree(main, "porzucony")

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert fresh.is_dir()
    assert _line(lines, str(fresh)).endswith("| nowe, bez własnych commitów")
    assert not abandoned.exists()


def test_galaz_bez_worktree_znika_tylko_scalona_i_porzucona(main: Path) -> None:
    _old_git(main, "branch", "scalona")
    git(main, "branch", "swieza")
    git(main, "worktree", "remove", str(_branch_with_work(main, "zrobiona")))
    _merge(main, "zrobiona", squash=True)
    unmerged = _branch_with_work(main, "obca")
    (unmerged / "obca.txt").write_text("zmieniona\n", encoding="utf-8")
    commit(unmerged, "feat: dalej")
    git(main, "worktree", "remove", str(unmerged))

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert _branches(main) == {"main", "obca", "swieza"}
    assert _line(lines, "gałąź obca").endswith("| commity spoza origin/main")
    assert _line(lines, "gałąź swieza").endswith("| nowe, bez własnych commitów")


def test_bez_usun_tylko_raportuje(main: Path) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")

    code, lines = _cleanup(main)

    assert code == 0
    assert path.is_dir()
    assert "zrobione" in _branches(main)
    assert _line(lines, str(path)).startswith("- do usunięcia |")
    assert lines[-1] == "SPRZĄTANIE RAPORT | do usunięcia 1 | zostawione 1 (główny checkout 1) | uruchom z --usun"


@pytest.mark.parametrize(
    ("command", "reason"),
    [(("worktree", "lock"), "zablokowany"), (("bisect", "start"), "w trakcie rebase, merge'a albo bisect")],
    ids=["zablokowany", "bisect"],
)
def test_worktree_zablokowany_albo_w_trakcie_bisect_zostaje(main: Path, command: tuple[str, ...], reason: str) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    git(path, *command, *([str(path)] if command[0] == "worktree" else []))

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert _line(lines, str(path)).endswith(f"| {reason}")


def test_odmowa_gita_zostawia_worktree_z_powodem(main: Path) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    (path / "pusty.txt").touch()

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert (path / "pusty.txt").is_file()
    assert "| git odmówił (" in _line(lines, str(path))
    assert lines[-1] == "SPRZĄTANIE OK | usunięte 0 | zostawione 2 (główny checkout 1, git odmówił 1)"


@pytest.fixture
def fake_lsof(home: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Podróbka ``lsof`` na ``PATH``: kolejne wywołania drukują kolejne odpowiedzi, ostatnia się powtarza."""

    lsof = fake_cli(home / "bin", "lsof", _FAKE_LSOF)
    monkeypatch.setenv("PATH", f"{lsof.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LSOF_LICZNIK", str(home / "lsof-wywolania"))

    def answers(*outputs: str) -> None:
        monkeypatch.setenv("LSOF_ODPOWIEDZI", json.dumps(outputs))

    return answers


_FAKE_LSOF = """import json, os, pathlib
calls = pathlib.Path(os.environ["LSOF_LICZNIK"])
answers = json.loads(os.environ["LSOF_ODPOWIEDZI"])
done = int(calls.read_text()) if calls.exists() else 0
calls.write_text(str(done + 1))
print(answers[min(done, len(answers) - 1)], end="")
"""


def test_proces_ktory_wszedl_po_ocenie_zatrzymuje_usuniecie(main: Path, fake_lsof: Callable[..., None]) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    fake_lsof("n/gdzie-indziej\n", f"n{path.resolve()}\n")

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert _line(lines, str(path)).endswith("| żywy proces")


def test_pusta_odpowiedz_lsof_zostawia_wszystko(main: Path, fake_lsof: Callable[..., None]) -> None:
    path = _branch_with_work(main, "zrobione")
    _merge(main, "zrobione")
    fake_lsof("")

    code, lines = _cleanup(main, "--usun")

    assert code == 0
    assert path.is_dir()
    assert "| procesy niesprawdzone" in _line(lines, str(path))


@contextmanager
def _process_in(path: Path) -> Iterator[None]:
    with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], cwd=path, stdin=subprocess.PIPE) as process:
        assert process.stdin is not None
        try:
            yield
        finally:
            process.stdin.close()


def test_galaz_main_zostaje_tez_bez_checkoutu(main: Path) -> None:
    (main / "b.txt").write_text("b\n", encoding="utf-8")
    commit(main, "feat: druga")
    git(main, "push", "--quiet", "origin", "main")
    git(main, "switch", "--quiet", "--detach")

    code, _ = _cleanup(main, "--usun")

    assert code == 0
    assert "main" in _branches(main)
