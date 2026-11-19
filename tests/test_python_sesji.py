"""Hook ``tools/hooks/python_sesji.py``: powłoka sesji Claude Code ma ``python3`` z ``requires-python`` zamiast starego z ``PATH``.

Claude Code wczytuje plik ``CLAUDE_ENV_FILE`` przed każdym poleceniem Bash, więc test uruchamia polecenie hooka
``SessionStart`` z ``.claude/settings.json`` i polecenie sesji, które ten plik wczytuje, z ``python3`` starszym niż
minimum na początku ``PATH``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.fake_cli import fake_cli

import setup_worktree

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "python_sesji.py"
SETTINGS = ROOT / ".claude" / "settings.json"
OLD_PYTHON = 'import sys\nprint("3.9")\n'

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="CLAUDE_ENV_FILE to skrypt sh, a hook biegnie z sh -c")


def _session_start_command() -> str:
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    command: str
    (command,) = [hook["command"] for entry in hooks for hook in entry["hooks"] if "python_sesji.py" in hook["command"]]
    return command


def _session_python(env_file: Path, path: str) -> str:
    """Wersja ``python3`` w poleceniu sesji, które najpierw wczytuje ``env_file``, jak Claude Code."""

    return subprocess.run(
        ["sh", "-c", '. "$1"; python3 -c "import sys; print(\'%d.%d\' % sys.version_info[:2])"', "sesja", str(env_file)],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_sesja_dostaje_python3_z_requires_python_zamiast_starego_z_path(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("brak uv na tym komputerze")
    old = fake_cli(tmp_path / "stary", "python3", OLD_PYTHON).parent
    env_file = tmp_path / "sesja.sh"
    env_file.touch()
    path = f"{old}{os.pathsep}{os.environ['PATH']}"

    subprocess.run(
        ["sh", "-c", _session_start_command()],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), "CLAUDE_ENV_FILE": str(env_file)},
        check=True,
    )

    major, minor = _session_python(env_file, path).split(".")
    assert (int(major), int(minor)) >= setup_worktree.MINIMUM_PYTHON


def test_bez_uv_sesja_zostaje_przy_python3_z_path(tmp_path: Path) -> None:
    old = fake_cli(tmp_path / "stary", "python3", OLD_PYTHON).parent
    env_file = tmp_path / "sesja.sh"
    env_file.touch()

    answered = subprocess.run(
        [sys.executable, str(HOOK)],
        env={**os.environ, "PATH": str(old), "CLAUDE_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (answered.returncode, env_file.read_text(encoding="utf-8")) == (0, "")
    assert _session_python(env_file, f"{old}{os.pathsep}{os.environ['PATH']}") == "3.9"


def test_katalog_ktorego_python3_to_inny_python_nie_trafia_na_poczatek_path(tmp_path: Path) -> None:
    """Jak ``/usr/bin/python3.13`` obok ``python3`` 3.12: katalog przesłoniłby inne programy, a ``python3`` by nie zmienił."""

    system = tmp_path / "usr" / "bin"
    fake_cli(system, "python3.13", "")
    fake_cli(system, "python3", "")
    uv = fake_cli(tmp_path / "uv", "uv", f"print({str(system / 'python3.13')!r})\n").parent
    env_file = tmp_path / "sesja.sh"
    env_file.touch()

    answered = subprocess.run(
        [sys.executable, str(HOOK)],
        env={**os.environ, "PATH": f"{uv}{os.pathsep}{os.environ['PATH']}", "CLAUDE_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (answered.returncode, env_file.read_text(encoding="utf-8")) == (0, "")
