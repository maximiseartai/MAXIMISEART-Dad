from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import repo

from rozliczenia.centrum import tool_update

from tests.fixtures.git_config import hermetic_git
from tests.fixtures.tool_clone import git

MISSING_FIXTURE = (
    "git w teście czyta konfigurację komputera, więc wynik zależy od maszyny: tests/conftest.py musi mieć sesyjną "
    "fixture git_bez_konfiguracji_komputera z hermetic_git (tests/fixtures/git_config.py)"
)
FOREIGN_CONFIG = "GIT_CONFIG_GLOBAL='/dev/null' to nie konfiguracja testów"
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows nie ma os.posix_spawn ani programu env"
)


def _maintenance_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *config: str
) -> list[list[str]]:
    repo, trace = tmp_path / "repo", tmp_path / "trace2.json"
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet")
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    git(repo, *config, "commit", "--quiet", "--allow-empty", "--message", "x")
    events = [
        json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()
    ]
    return [
        event["argv"]
        for event in events
        if event["event"] == "child_start" and "maintenance" in event["argv"]
    ]


def test_commit_w_tescie_nie_uruchamia_konserwacji_repozytorium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _maintenance_after_commit(tmp_path, monkeypatch) == []
    started = _maintenance_after_commit(
        tmp_path / "jawnie",
        monkeypatch,
        "-c",
        "maintenance.auto=true",
        "-c",
        "maintenance.autoDetach=false",
    )
    assert [argv[1:3] for argv in started] == [["maintenance", "run"]]


def test_git_w_tescie_czyta_tylko_konfiguracje_testow(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet")
    listed = git(tmp_path, "config", "--list", "--show-scope").splitlines()

    outside_repository = [line for line in listed if not line.startswith("local\t")]

    assert outside_repository == [
        "global\tinit.defaultbranch=main",
        "global\tuser.name=test",
        "global\tuser.email=test@example.com",
        "global\tcore.autocrlf=false",
        "global\tcommit.gpgsign=false",
        "global\ttag.gpgsign=false",
        "global\tmaintenance.auto=false",
        "global\tgc.auto=0",
    ], MISSING_FIXTURE


def test_git_w_tescie_nie_bierze_tozsamosci_ze_srodowiska_wolajacego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "agent")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "agent@example.invalid")
    (tmp_path / "sesja").mkdir()
    with hermetic_git(tmp_path / "sesja"):
        subprocess.run(["git", "init", "--quiet", str(tmp_path / "repo")], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path / "repo"),
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "x",
            ],
            check=True,
        )
        identity = git(tmp_path / "repo", "log", "-1", "--format=%an <%ae> | %cn <%ce>")

    assert identity == "test <test@example.com> | test <test@example.com>", (
        "git testów bierze tożsamość ze środowiska wołającego (GIT_AUTHOR_*/GIT_COMMITTER_*, które Claude Code daje "
        "agentom z .claude/settings.json), więc wynik testu zależy od tego, kto go uruchomił: hermetic_git ma je zdjąć"
    )


def test_git_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test() -> None:
    with pytest.raises(
        AssertionError,
        match="GIT_CONFIG_NOSYSTEM nie jest 1.*Napraw: zbuduj env z os.environ",
    ):
        subprocess.run(
            ["git", "--version"], env={"PATH": os.environ["PATH"]}, check=True
        )
    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        subprocess.run(
            ["git", "--version"],
            env=os.environ | {"GIT_CONFIG_GLOBAL": "/dev/null"},
            check=True,
        )

    subprocess.run(
        ["git", "--version"],
        env=os.environ | {"LC_ALL": "C"},
        capture_output=True,
        check=True,
    )


@pytest.mark.parametrize(
    ("home_files", "xdg", "refused"),
    [([], False, False), ([".gitconfig"], False, True), ([], True, True)],
    ids=["pusty HOME", "HOME z plikiem", "z XDG_CONFIG_HOME"],
)
def test_git_bez_zadnej_konfiguracji_przechodzi_tylko_z_pustym_home_bez_xdg_config_home(
    tmp_path: Path, home_files: list[str], xdg: bool, refused: bool
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    for name in home_files:
        (home / name).write_text("", encoding="utf-8")
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if xdg:
        environment["XDG_CONFIG_HOME"] = str(tmp_path)
    if sys.platform == "win32":
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

    if refused:
        with pytest.raises(AssertionError, match="to nie konfiguracja testów"):
            subprocess.run(
                ["git", "--version"], env=environment, capture_output=True, check=True
            )
    else:
        subprocess.run(
            ["git", "--version"], env=environment, capture_output=True, check=True
        )


def test_git_bez_konfiguracji_komputera_z_narzedzi_maksa_przechodzi_przez_straz(tmp_path: Path) -> None:
    assert repo.git(tmp_path, "--version", isolated=True).startswith("git version")


LAUNCHES: dict[str, Callable[[], object]] = {
    "lista bez env=": lambda: subprocess.run(["git", "--version"], check=True),
    "krotka": lambda: subprocess.run(("git", "--version"), check=True),
    "pełna ścieżka": lambda: subprocess.run(
        [str(tool_update.find_git()), "--version"], check=True
    ),
    "env": lambda: subprocess.run(
        ["/usr/bin/env", "LC_ALL=C", "git", "--version"], check=True
    ),
    "sh -c": lambda: subprocess.run(["sh", "-c", "cd . && git --version"], check=True),
    "shell=True": lambda: subprocess.run(
        "cd . && git --version", shell=True, check=True
    ),
    "executable=": lambda: subprocess.run(
        ["wersja", "--version"], executable=tool_update.find_git(), check=True
    ),
    "os.system": lambda: os.system("git --version"),
}


@pytest.mark.parametrize("launch", LAUNCHES.values(), ids=LAUNCHES.keys())
def test_git_kazda_droga_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test(
    launch: Callable[[], object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")

    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        launch()


@POSIX_ONLY
@pytest.mark.parametrize("spawn", ["posix_spawn", "posix_spawnp"])
def test_git_z_posix_spawn_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test(
    spawn: str,
) -> None:
    git_program = str(tool_update.find_git())

    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        getattr(os, spawn)(
            git_program,
            [git_program, "--version"],
            os.environ | {"GIT_CONFIG_GLOBAL": "/dev/null"},
        )


@POSIX_ONLY
@pytest.mark.parametrize("spawn", ["posix_spawn", "posix_spawnp"])
@pytest.mark.parametrize(
    "command",
    [["git", "--version"], ["sh", "-c", "cd . && git --version"]],
    ids=["git", "sh -c"],
)
def test_posix_spawn_bez_env_sprawdza_srodowisko_procesu(
    spawn: str, command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # ZEWNĘTRZNE: subprocess na Linuksie uruchamia program podany ścieżką przez os.posix_spawn z env z Popen, także None, gdy Python ma os.POSIX_SPAWN_CLOSEFROM albo Popen dostał close_fds=False (Lib/subprocess.py: Popen._execute_child)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    program = shutil.which(command[0])
    assert program is not None

    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        getattr(os, spawn)(program, command, None)


@pytest.mark.parametrize(
    ("command", "shell"),
    [
        (["env", "-i", "git", "--version"], False),
        (["env", "-u", "GIT_CONFIG_NOSYSTEM", "git", "--version"], False),
        (["sh", "-c", "unset GIT_CONFIG_NOSYSTEM; git --version"], False),
        ("GIT_CONFIG_NOSYSTEM=0 git --version", True),
    ],
    ids=["env -i", "env -u", "unset w powłoce", "przypisanie w powłoce"],
)
def test_polecenie_ktore_zdejmuje_konfiguracje_testow_przed_gitem_wywraca_test(
    command: list[str] | str, shell: bool
) -> None:
    with pytest.raises(AssertionError, match="GIT_CONFIG_NOSYSTEM nie jest 1"):
        subprocess.run(command, shell=shell, check=True)


ZNANE_LUKI: dict[str, Callable[[Path], object]] = {
    "powłoka: straż czyta tylko proste polecenia, git po then": lambda _: subprocess.run(
        ["bash", "-c", "if true; then git --version; fi"], capture_output=True, check=True
    ),
    "powłoka: straż czyta tylko proste polecenia, git w klamrach": lambda _: subprocess.run(
        ["bash", "-c", "{ git --version; }"], capture_output=True, check=True
    ),
    "powłoka: straż czyta tylko proste polecenia, git po wykrzykniku": lambda _: subprocess.run(
        ["bash", "-c", "! git --version || true"], capture_output=True, check=True
    ),
    "powłoka: straż czyta tylko proste polecenia, git po time": lambda _: subprocess.run(
        ["bash", "-c", "time git --version"], capture_output=True, check=True
    ),
    "powłoka: straż czyta tylko proste polecenia, git po exec": lambda _: subprocess.run(
        ["bash", "-c", "exec git --version"], capture_output=True, check=True
    ),
    "straż żyje tylko w procesie testów: git w osobnym procesie Pythona": lambda _: subprocess.run(
        [sys.executable, "-c", "import subprocess; subprocess.run(['git', '--version'], capture_output=True, check=True)"],
        check=True,
    ),
    "straż nie patrzy na os.exec*": lambda directory: _exec_missing(directory / "brak" / "git"),
    "straż nie patrzy na os.spawn*: os.spawnv dochodzi do fork": lambda directory: _spawn_until_fork(directory / "git"),
}


def _exec_missing(program: Path) -> None:
    with pytest.raises(FileNotFoundError):
        os.execv(program, [str(program), "--version"])


def _spawn_until_fork(program: Path) -> None:
    def fork() -> int:
        raise ChildProcessError("próbka nie rozwidla procesu testów")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "fork", fork)
        with pytest.raises(ChildProcessError):
            os.spawnv(os.P_WAIT, program, [str(program), "--version"])


@POSIX_ONLY
@pytest.mark.parametrize("launch", ZNANE_LUKI.values(), ids=ZNANE_LUKI.keys())
def test_znane_luki_strazy_gita_przepuszczaja_git_ze_srodowiskiem_bez_konfiguracji_testow(
    launch: Callable[[Path], object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")

    try:
        launch(tmp_path)
    except AssertionError as refused:
        pytest.fail(f"straż łapie już tę drogę, więc nie jest luką: usuń ją ze ZNANE_LUKI i dopisz do LAUNCHES ({refused})")


@POSIX_ONLY
def test_git_przez_env_i_powloke_z_konfiguracja_testow_dziala() -> None:
    for command in (
        ["env", "LC_ALL=C", "git", "--version"],
        ["sh", "-c", "git --version"],
    ):
        subprocess.run(command, capture_output=True, check=True)
    assert os.system("git --version >/dev/null") == 0


def test_git_z_kodu_narzedzia_nie_ma_tozsamosci_jak_u_taty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Maks")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "maks@example.invalid")
    git_program = tool_update.find_git()
    assert git_program is not None
    git(tmp_path, "init", "--quiet")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "commit",
            "--quiet",
            "--allow-empty",
            "--message",
            "test",
        ],
        check=True,
    )

    from_tool = tool_update._Git(git_program, tmp_path).run(
        "commit", "--quiet", "--allow-empty", "--message", "narzędzie"
    )

    identity = (
        "git z kodu narzędzia (src/) ma pustą tożsamość, jak u taty, więc jego git commit pada: nie przekazuj mu "
        "GIT_AUTHOR_*/GIT_COMMITTER_* ani user.name z konfiguracji testów"
    )
    assert from_tool.returncode != 0, identity
    assert "Author identity unknown" in from_tool.stderr, identity
