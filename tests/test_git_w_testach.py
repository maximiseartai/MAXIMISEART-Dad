"""Git w testach ma jedną konfigurację: sesyjna fixture ``git_bez_konfiguracji_komputera`` z ``tests/conftest.py``.

Git uruchomiony z procesu testów ze środowiskiem bez konfiguracji testów wywraca test, gdy idzie przez ``subprocess``
(lista, krotka, pełna ścieżka, ``env``, ``env -i``, ``env -u``, ``sh -c`` i ``shell=True``, także z ``unset`` albo
przypisaniem przed gitem, ``executable=``), ``os.system``, ``os.posix_spawn`` albo ``os.posix_spawnp``, a ``git commit``
z ``src/`` pada z „Author identity unknown”. Ten moduł pada, gdy fixture albo któraś z tych dróg zniknie.

Granica: git w osobnym procesie (skrypt ``tools/``, ``python -c``) dziedziczy zmienne, ale straży tam nie ma; git po
``if``/``then``, w ``{ …; }``, po ``!``, ``time`` albo ``exec`` w powłoce oraz przez ``os.exec*`` i ``os.spawn*`` łapie
tylko przegląd.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from rozliczenia.centrum import tool_update

from tests.fixtures.tool_clone import git

MISSING_FIXTURE = (
    "git w teście czyta konfigurację komputera, więc wynik zależy od maszyny: tests/conftest.py musi mieć sesyjną "
    "fixture git_bez_konfiguracji_komputera z hermetic_git (tests/fixtures/git_config.py)"
)
FOREIGN_CONFIG = "GIT_CONFIG_GLOBAL='/dev/null' to nie konfiguracja testów"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Windows nie ma os.posix_spawn ani programu env")


def _maintenance_after_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *config: str) -> list[list[str]]:
    repo, trace = tmp_path / "repo", tmp_path / "trace2.json"
    repo.mkdir()
    git(repo, "init", "--quiet")
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    git(repo, *config, "commit", "--quiet", "--allow-empty", "--message", "x")
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    return [event["argv"] for event in events if event["event"] == "child_start" and "maintenance" in event["argv"]]


def test_commit_w_tescie_nie_uruchamia_konserwacji_repozytorium(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _maintenance_after_commit(tmp_path, monkeypatch) == []


def test_slad_gita_pokazuje_konserwacje_wlaczona_jawnie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started = _maintenance_after_commit(tmp_path, monkeypatch, "-c", "maintenance.auto=true", "-c", "maintenance.autoDetach=false")

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


def test_klon_pustego_origin_po_pushu_main_ma_pliki_na_kazdym_komputerze(tmp_path: Path) -> None:
    origin, work, other = tmp_path / "origin.git", tmp_path / "praca", tmp_path / "inny-klon"
    git(tmp_path, "init", "--quiet", "--bare", str(origin))
    git(tmp_path, "init", "--quiet", str(work))
    (work / "kod.py").write_text("WERSJA = 1\n", encoding="utf-8")
    git(work, "add", "kod.py")
    git(work, "commit", "--quiet", "--message", "pierwsza wersja")
    git(work, "push", "--quiet", str(origin), "HEAD:main")

    git(tmp_path, "clone", "--quiet", str(origin), str(other))

    assert (other / "kod.py").read_text(encoding="utf-8") == "WERSJA = 1\n", MISSING_FIXTURE


def test_git_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test() -> None:
    with pytest.raises(AssertionError, match="GIT_CONFIG_NOSYSTEM nie jest 1.*Napraw: zbuduj env z os.environ"):
        subprocess.run(["git", "--version"], env={"PATH": os.environ["PATH"]}, check=True)
    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        subprocess.run(["git", "--version"], env=os.environ | {"GIT_CONFIG_GLOBAL": "/dev/null"}, check=True)

    subprocess.run(["git", "--version"], env=os.environ | {"LC_ALL": "C"}, capture_output=True, check=True)


@pytest.mark.parametrize(
    ("home_files", "xdg", "refused"),
    [([], False, False), ([".gitconfig"], False, True), ([], True, True)],
    ids=["pusty HOME", "HOME z plikiem", "z XDG_CONFIG_HOME"],
)
def test_git_bez_zadnej_konfiguracji_przechodzi_tylko_z_pustym_home_bez_xdg_config_home(
    tmp_path: Path, home_files: list[str], xdg: bool, refused: bool
) -> None:
    """Git bez konfiguracji komputera, jak ``repo.git(isolated=True)``: ``GIT_CONFIG_GLOBAL`` to ``os.devnull``, a
    ``HOME`` pusty katalog; plik w ``HOME`` albo ``XDG_CONFIG_HOME`` to znów pliki gita komputera."""

    home = tmp_path / "home"
    home.mkdir()
    for name in home_files:
        (home / name).write_text("", encoding="utf-8")
    environment = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    if xdg:
        environment["XDG_CONFIG_HOME"] = str(tmp_path)
    if sys.platform == "win32":
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

    if refused:
        with pytest.raises(AssertionError, match="to nie konfiguracja testów"):
            subprocess.run(["git", "--version"], env=environment, capture_output=True, check=True)
    else:
        subprocess.run(["git", "--version"], env=environment, capture_output=True, check=True)


LAUNCHES: dict[str, Callable[[], object]] = {
    "lista bez env=": lambda: subprocess.run(["git", "--version"], check=True),
    "krotka": lambda: subprocess.run(("git", "--version"), check=True),
    "pełna ścieżka": lambda: subprocess.run([str(tool_update.find_git()), "--version"], check=True),
    "env": lambda: subprocess.run(["/usr/bin/env", "LC_ALL=C", "git", "--version"], check=True),
    "sh -c": lambda: subprocess.run(["sh", "-c", "cd . && git --version"], check=True),
    "shell=True": lambda: subprocess.run("cd . && git --version", shell=True, check=True),
    "executable=": lambda: subprocess.run(["wersja", "--version"], executable=tool_update.find_git(), check=True),
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
def test_git_z_posix_spawn_ze_srodowiskiem_bez_konfiguracji_testow_wywraca_test(spawn: str) -> None:
    git_program = str(tool_update.find_git())

    with pytest.raises(AssertionError, match=FOREIGN_CONFIG):
        getattr(os, spawn)(git_program, [git_program, "--version"], os.environ | {"GIT_CONFIG_GLOBAL": "/dev/null"})


@POSIX_ONLY
@pytest.mark.parametrize("spawn", ["posix_spawn", "posix_spawnp"])
@pytest.mark.parametrize("command", [["git", "--version"], ["sh", "-c", "cd . && git --version"]], ids=["git", "sh -c"])
def test_posix_spawn_bez_env_sprawdza_srodowisko_procesu(
    spawn: str, command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python 3.14 na Linuksie uruchamia tak ``subprocess.run([bash, "-c", …])``; brak env to środowisko procesu.
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
def test_polecenie_ktore_zdejmuje_konfiguracje_testow_przed_gitem_wywraca_test(command: list[str] | str, shell: bool) -> None:
    with pytest.raises(AssertionError, match="GIT_CONFIG_NOSYSTEM nie jest 1"):
        subprocess.run(command, shell=shell, check=True)


@POSIX_ONLY
def test_git_przez_env_i_powloke_z_konfiguracja_testow_dziala() -> None:
    for command in (["env", "LC_ALL=C", "git", "--version"], ["sh", "-c", "git --version"]):
        subprocess.run(command, capture_output=True, check=True)
    assert os.system("git --version >/dev/null") == 0


def test_git_z_kodu_narzedzia_nie_ma_tozsamosci_jak_u_taty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Maks")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "maks@example.invalid")
    git_program = tool_update.find_git()
    assert git_program is not None
    git(tmp_path, "init", "--quiet")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "--quiet", "--allow-empty", "--message", "test"], check=True)

    from_tool = tool_update._Git(git_program, tmp_path).run("commit", "--quiet", "--allow-empty", "--message", "narzędzie")

    identity = (
        "git z kodu narzędzia (src/) ma pustą tożsamość, jak u taty, więc jego git commit pada: nie przekazuj mu "
        "GIT_AUTHOR_*/GIT_COMMITTER_* ani user.name z konfiguracji testów"
    )
    assert from_tool.returncode != 0, identity
    assert "Author identity unknown" in from_tool.stderr, identity
