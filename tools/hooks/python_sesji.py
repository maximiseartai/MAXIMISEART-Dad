"""Hook ``SessionStart`` Claude Code: ``python3`` w powłoce sesji to Python z ``requires-python`` przez uv, nie systemowy.

Claude Code bierze ``PATH`` powłoki narzędzia Bash z procesu, który go uruchomił, a nie z ``~/.zshrc`` (snapshot powłoki
przenosi z niego opcje i funkcje, ale nie ``PATH``), więc na Macu ``python3`` sesji to systemowy 3.9 i skrypty repo padają
na składni nowszego Pythona. Hook pyta ``uv python find --system`` o Pythona ``setup_worktree.MINIMUM`` albo nowszego
(``--system`` pomija ``.venv`` checkoutu, którego nowy worktree jeszcze nie ma) i dopisuje jego katalog na początek
``PATH`` w pliku ``CLAUDE_ENV_FILE``, który Claude Code wczytuje przed każdym poleceniem Bash. Katalog trafia na początek
tylko wtedy, gdy jego ``python3`` to ten sam plik co znaleziony Python, bo katalog systemowy (``/usr/bin/python3.13`` obok
``python3`` 3.12) przesłoniłby inne programy, a ``python3`` by nie zmienił. Hooki dalej biegną z ``PATH`` procesu, czyli
systemowym Pythonem, więc ten plik działa pod 3.9 (``per-file-target-version`` w ``ruff.toml``).

Bez ``CLAUDE_ENV_FILE`` (inny gospodarz niż Claude Code) hook nic nie robi. Bez ``uv``, bez takiego Pythona albo z
katalogiem, którego ``python3`` to inny Python, nic nie dopisuje i pisze powód jedną linią na stderr; kod wyjścia jest
zawsze 0, bo sesja bez niego działa jak przedtem.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from setup_worktree import MINIMUM

FIND_TIMEOUT_S = 5


class _Skipped(Exception):
    """Powód, dla którego ``python3`` sesji zostaje bez zmiany."""


def main() -> int:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return 0
    try:
        folder = _python_folder()
    except _Skipped as skipped:
        print(f"python3 sesji bez zmiany: {skipped}", file=sys.stderr)
        return 0
    with open(env_file, "a", encoding="utf-8") as env:
        env.write(f'export PATH={shlex.quote(str(folder))}:"$PATH"\n')
    return 0


def _python_folder() -> Path:
    """Katalog, którego ``python3`` to Python ``MINIMUM`` albo nowszy z uv."""

    uv = shutil.which("uv")
    if uv is None:
        raise _Skipped("uv nie ma w PATH")
    try:
        found = subprocess.run(
            [uv, "python", "find", "--system", f">={MINIMUM}"],
            capture_output=True,
            text=True,
            timeout=FIND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _Skipped(f"uv python find: {error}") from error
    if found.returncode != 0:
        raise _Skipped(f"uv nie znalazł Pythona {MINIMUM} albo nowszego: {found.stderr.strip()}")
    python = Path(found.stdout.strip())
    python3 = python.parent / "python3"
    if not python3.exists() or not os.path.samefile(python3, python):
        raise _Skipped(f"{python3} to nie {python}")
    return python.parent


if __name__ == "__main__":
    raise SystemExit(main())
