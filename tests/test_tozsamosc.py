"""Hook ``tools/hooks/tozsamosc.py``: agent nie zapisuje tożsamości autora gita do configu wspólnego dla worktree.

13.11.2026 recenzent PR #1646 ustawił w swoim worktree ``git config user.email r@x && git config user.name r``, żeby
zrobić próbny commit, a ``git config`` bez ``--file`` pisze do ``.git/config`` głównego checkoutu, który dzielą
wszystkie worktree: przez trzy dni każdy agent na Macu Maksa podpisywał nim commity. Korpus ocenia ``writes_identity``
hooka wczytanego raz; protokół (JSON na stdin, odmowa to kod 2 z przyczyną na stderr), znane luki i wpis w ustawieniach
sprawdzają testy, które uruchamiają hook tak jak Claude Code.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.znane_luki import assert_znane_luki

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "tozsamosc.py"
SETTINGS = ROOT / ".claude" / "settings.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tozsamosc", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load()

REFUSED = (
    "git config user.email r@x && git config user.name r",
    "git -C /srv/rev-1646 config user.name r",
    "cd /srv/rev-1646\ngit config user.name r",
    "git config --local user.email r@x",
    "git config --global user.name 'Recenzent R'",
    "git config --system user.email r@x",
    "git config --worktree user.name r",
    "git config user.name r 2>/dev/null",
    "git config set user.email r@x",
    "git config set --global user.name r",
    "git config --add user.name r",
    "git config --replace-all user.email r@x",
    "git config --unset user.name",
    "git config unset --global user.email",
    "git config --remove-section user",
    "git config rename-section author stary",
    "git config author.name r",
    "git config committer.email r@x",
    "git config User.Name r",
    "git config --file .git/config user.name r",
    "git config -f ~/.gitconfig user.email r@x",
    "git config --file=/repo/.git/worktrees/w/config.worktree user.name r",
    "git --git-dir=/repo/.git config user.name r",
    "git -c core.pager=cat config user.name r",
    "env GIT_TRACE=1 git config user.name r",
    "/usr/bin/git config user.name r",
    # Repo próbne nie jest wyjątkiem: ścieżka tymczasowa może być worktree wspólnego repo.
    "cd /tmp/proba && git init -q && git config user.name r",
    'git -C "$tmp" config user.email r@x',
    "bash -c 'git config user.name r'",
    'sh -lc "git config --global user.email r@x"',
    'eval "git config user.name r"',
    "x=$(git config user.name r)",
    'echo "$(git config user.email r@x)"',
    "echo `git config user.name r`",
)

PASSING = (
    "git config user.name",
    "git config user.name 2>/dev/null",
    "git config --get user.email",
    "git config --get user.name r",
    "git config get user.name",
    "git config --global --get user.email",
    "git config --get-regexp '^user\\.'",
    "git config --list | grep user",
    "git config list --show-origin",
    "git config core.hooksPath tools/hooks",
    "git config --file /tmp/proba.ini user.name r",
    "git -c user.name=r -c user.email=r@x commit -q -m próba",
    "GIT_AUTHOR_NAME=r GIT_AUTHOR_EMAIL=r@x GIT_COMMITTER_NAME=r GIT_COMMITTER_EMAIL=r@x git commit -q -m próba",
    "git commit --author='r <r@x>' -m próba",
    "git commit -m 'fix: hook odrzuca git config user.name r'",
    "git commit -q -F - <<'EOF'\nfix: hook odrzuca\ngit config user.name r\nEOF\ngit log -1",
    "rg -n 'git config user\\.' tools tests",
    "git log --format='%an <%ae>' -5",
)

# Postacie zapisu tożsamości, które hook przepuszcza, nazwane klasą mechanizmu, który je przepuszcza.
ZNANE_LUKI = {
    "pomija ciała heredoców: skrypt powłoki z heredoca": "bash <<'EOF'\ngit config user.name r\nEOF",
    "nie czyta plików: skrypt powłoki z pliku": "sh ./ustaw_tozsamosc.sh",
    "zna tylko polecenia powłoki: Python z subprocess": (
        "python3 -c \"import subprocess; subprocess.run(['git', 'config', 'user.name', 'r'])\""
    ),
    "zna tylko klucz dosłowny: klucz ze zmiennej": 'k=user.name; git config "$k" r',
    "zna tylko słowo git: program ze zmiennej": "g=git; $g config user.name r",
    "zna tylko podpolecenie config: alias gita": "git -c alias.ustaw=config ustaw user.name r",
    "zna tylko klucze tożsamości: include.path do pliku z tożsamością": "git config include.path ~/tozsamosc.inc",
}


def _bash(command: str) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x"}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}))


def _hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, encoding="utf-8", check=False
    )


@pytest.mark.parametrize("command", REFUSED)
def test_zapis_tozsamosci_do_configu_dostaje_odmowe(command: str) -> None:
    assert hook.writes_identity(command)


@pytest.mark.parametrize("command", PASSING)
def test_odczyt_jednorazowy_podpis_i_inne_polecenie_przechodza(command: str) -> None:
    assert not hook.writes_identity(command)


def test_hook_odmawia_kodem_2_z_droga_jednorazowego_podpisu_na_stderr() -> None:
    hooked = _bash(REFUSED[0])

    assert (hooked.returncode, hooked.stdout) == (2, ""), hooked.stderr
    said = ("git -c user.name=… -c user.email=… commit", "GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL", "katalogu tymczasowym")
    assert [text for text in said if text not in hooked.stderr] == [], hooked.stderr


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param(json.dumps({"tool_input": {"command": PASSING[0]}}), id="odczyt"),
        pytest.param("nie json", id="nie-json"),
        pytest.param(json.dumps({"tool_input": {"command": ["git", "config", "user.name", "r"]}}), id="polecenie-nie-napis"),
        pytest.param(json.dumps({"tool_input": None}), id="bez-polecenia"),
    ],
)
def test_hook_przepuszcza_bez_slowa(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def test_znane_luki_hooka_tozsamosci_przechodza_przez_hook() -> None:
    zgloszenia = {opis: [line for line in [_bash(command).stderr.strip()] if line] for opis, command in ZNANE_LUKI.items()}

    assert_znane_luki(zgloszenia, "tests/test_tozsamosc.py")


def _registered() -> list[dict[str, object]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    return [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"] if "tozsamosc.py" in hook["command"]]


def test_claude_code_uruchamia_hook_przed_kazdym_bashem_z_limitem_najwyzej_10_s() -> None:
    (registered,) = _registered()
    timeout = registered["timeout"]

    assert isinstance(timeout, (int, float)) and 0 < timeout <= 10


def _configured(project: Path) -> subprocess.CompletedProcess[str]:
    (registered,) = _registered()
    command = registered["command"]
    assert isinstance(command, str)
    return subprocess.run(
        command,
        shell=True,
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": REFUSED[0]}}),
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_polecenie_z_ustawien_projektu_odmawia_zapisu_tozsamosci() -> None:
    hooked = _configured(ROOT)

    assert (hooked.returncode, "git -c user.name=" in hooked.stderr) == (2, True), hooked.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_checkout_bez_skryptu_hooka_tozsamosci_nie_blokuje_basha(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path)

    assert (hooked.returncode, hooked.stderr) == (0, "")


@pytest.mark.parametrize(
    "command",
    [
        # Odczyt na końcu, bo odmowa kończy ocenę przy pierwszym zapisie, a hook czyta do końca tylko polecenie,
        # które przechodzi.
        "eval " * 10000 + "git config user.name",
        "bash -c " * 40000 + "'git config user.name'",
        'echo "$(' * 40000 + "git config user.name",
        "git config core.x y; " * 40000 + "git config user.name",
    ],
    ids=["eval-w-eval", "bash-c-w-bash-c", "podstawienia", "wiele-wywolan"],
)
def test_hook_ocenia_dlugie_polecenie_przed_limitem_z_ustawien(command: str) -> None:
    (registered,) = _registered()
    timeout = registered["timeout"]
    assert isinstance(timeout, (int, float))

    hooked = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )

    assert (hooked.returncode, hooked.stderr) == (0, "")
