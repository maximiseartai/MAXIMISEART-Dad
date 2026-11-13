"""One Windows run's world: Dad's synthetic files, the tool's versions on a local "origin", and the boundaries.

``prepare`` writes, under the run root:

- ``dane/``: the synthetic folder okresów ``INEA``, Rejestr zleceń and Dad's ``config/`` (Lista Wykonawców and the
  three Wzorce) from ``verify-centrum-rozliczen``'s fixture (``create_centrum_fixture.dad_files``);
- ``wydawca/`` and ``origin.git``: three versions of the tool. ``first`` is this checkout as it is now (tracked and
  untracked files, ignored ones left out), so a run proves the working tree, not the last commit. ``newest`` changes
  ``requirements.txt`` (a comment only, so pip installs nothing new), which makes the update install libraries.
  ``not_starting``, one version after ``newest``, has a ``run_centrum.py`` that fails at once. The only Wydanie
  ``v0.1.0`` starts on ``first`` and the origin's ``main`` one version past it on ``newest``, so only README's choice
  of the newest Wydanie installs ``first``; ``release`` moves the Wydanie and puts ``main`` on ``not_starting``;
- ``przegladarka.cmd``: Dad's browser, which only records the address Centrum opens in ``otwarte-adresy.txt``;
- ``windows.json``: these facts for the drive, doctor and cleanup.

The tool itself (the clone in a folder with spaces and Polish letters) is made by ``instalacja``, as Maks installs it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

import create_centrum_fixture
from rozliczenia.tool_files import DEFAULT_PORT, HOST, REPOSITORY_URL
from skrypt_skilla import create_run_root

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]

PORT = DEFAULT_PORT
URL = f"http://{HOST}:{PORT}/"
FACTS = "windows.json"
# The tool lives on Dad's C: in his user folder, whose name has a space and a Polish letter. ``ó`` is in both Dad's
# code page (1250) and the English runner's (1252), so the stand-in can write it where Windows uses the code page.
TOOL_FOLDER = Path("Users") / "Józef Kowalski" / "MAXIMISEART-Dad"
# A deliberate copy (docs/agents/skille.md, „Co wyrocznia bierze z src”): Dad finds Centrum by this name on his
# desktop, so a change of shortcut.SHORTCUT_NAME must break the drive, not follow it.
SHORTCUT = "Centrum rozliczeń.lnk"
_NEW_REQUIREMENT_LINE = "# verify-centrum-na-windowsie: nowa wersja zmienia wymagania\n"
_NOT_STARTING = 'raise ImportError("verify-centrum-na-windowsie: ta wersja Centrum nie startuje")\n'


def git(directory: Path, *args: str, machine: bool = False) -> str:
    """``machine`` is Git as Maks and Centrum run it on this computer, with its own configuration."""

    environment = os.environ if machine else os.environ | {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_AUTHOR_NAME": "Maks Syntetyczny",
        "GIT_AUTHOR_EMAIL": "maks@example.invalid",
        "GIT_COMMITTER_NAME": "Maks Syntetyczny",
        "GIT_COMMITTER_EMAIL": "maks@example.invalid",
    }
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _checkout_files() -> list[str]:
    listed = git(REPO_ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({name for name in listed.split("\0") if name and (REPO_ROOT / name).is_file()})


def _publish_versions(publisher: Path, origin: Path) -> dict[str, str]:
    for name in _checkout_files():
        target = publisher / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, target)
    git(publisher, "init", "--quiet", "--initial-branch", "main")
    git(publisher, "config", "core.autocrlf", "false")
    git(publisher, "add", "--all")
    git(publisher, "commit", "--quiet", "-m", "Wersja z checkoutu")
    first = git(publisher, "rev-parse", "HEAD")
    with (publisher / "requirements.txt").open("a", encoding="utf-8", newline="\n") as requirements:
        requirements.write(_NEW_REQUIREMENT_LINE)
    git(publisher, "commit", "--quiet", "--all", "-m", "Nowa wersja: zmienione wymagania")
    newest = git(publisher, "rev-parse", "HEAD")
    (publisher / "run_centrum.py").write_text(_NOT_STARTING, encoding="utf-8")
    git(publisher, "commit", "--quiet", "--all", "-m", "Wersja, której Centrum nie startuje")
    not_starting = git(publisher, "rev-parse", "HEAD")
    git(origin.parent, "init", "--quiet", "--bare", "--initial-branch", "main", origin.name)
    git(publisher, "push", "--quiet", str(origin), f"{newest}:refs/heads/main", f"{first}:refs/tags/v0.1.0", f"{not_starting}:refs/heads/nie-startuje")
    return {"first": first, "newest": newest, "not_starting": not_starting}


def prepare(root: Path) -> dict[str, Any]:
    """Writes the run's world under ``root`` (which must not exist) and returns its facts."""

    create_run_root(root)
    (root / "dane").mkdir()
    data = create_centrum_fixture.dad_files(root / "dane")
    origin = root / "origin.git"
    versions = _publish_versions(root / "wydawca", origin)
    recorder, opened = root / "przegladarka.cmd", root / "otwarte-adresy.txt"
    recorder.write_text(f'@echo %~1>>"{opened}"\r\n', encoding="utf-8")
    configuration, board = data["configuration"], data["board"]
    assert isinstance(configuration, dict) and isinstance(board, list)
    facts: dict[str, Any] = {
        "root": str(root),
        "tool": str(root / TOOL_FOLDER),
        "desktop": str(root / "Pulpit"),
        "shortcut": str(root / "Pulpit" / SHORTCUT),
        "startup": str(root / "Autostart"),
        "origin": str(origin),
        "versions": versions,
        "browser": str(recorder),
        "opened": str(opened),
        "periods_directory": data["periods_directory"],
        "order_register": data["order_register"],
        "dad_config": [str(Path(path)) for path in configuration.values()],
        "board": [row[0] for row in board],
        "url": URL,
        "port": PORT,
    }
    (root / FACTS).write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    return facts


def load(root: Path) -> dict[str, Any]:
    facts = json.loads((root / FACTS).read_text(encoding="utf-8"))
    assert isinstance(facts, dict)
    return facts


def boundaries(facts: dict[str, Any]) -> dict[str, str]:
    """Environment that Centrum, started from the shortcut, inherits: Dad's browser and GitHub, both local.

    Git rewrites the tool's fixed GitHub address to the run's origin (``url.<origin>.insteadOf``), so Aktualizacja
    narzędzia runs its production code and only the network endpoint is local.
    """

    return {
        "BROWSER": facts["browser"],
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{Path(facts['origin']).as_posix()}.insteadOf",
        "GIT_CONFIG_VALUE_0": REPOSITORY_URL,
    }


def release(facts: dict[str, Any], version: str) -> None:
    """The origin's only Wydanie (Centrum updates to the newest one) is ``version``, a key of ``versions``.

    A real Wydanie never moves; the harness withdraws every tag and tags ``v0.1.0`` again. ``main`` moves to
    ``not_starting``, ahead of every version and in no Wydanie: a Centrum that took ``main`` would fail the run.
    """

    origin = Path(facts["origin"])
    tags = git(origin, "tag", "--list", "v*").split()
    if tags:
        git(origin, "tag", "--delete", *tags)
    git(origin, "tag", "v0.1.0", facts["versions"][version])
    git(origin, "update-ref", "refs/heads/main", facts["versions"]["not_starting"])
