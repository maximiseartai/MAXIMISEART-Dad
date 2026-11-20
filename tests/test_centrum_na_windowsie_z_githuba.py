"""Werdykt ``run_on_github.py`` skilla ``verify-centrum-na-windowsie`` dotyczy lokalnego ``HEAD``, a nie dowolnego runu.

Każdy test buduje repozytorium z kopią skryptu i ``origin`` na dysku, a ``gh`` to atrapa, która odpowiada runami z
pliku i zapisuje swoje wywołania.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, fake_cli
from tests.fixtures.git_repo import commit, git

pytestmark = ONLY_FOUND_BY_NAME_ON_POSIX

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-centrum-na-windowsie" / "scripts" / "run_on_github.py"
OTHER = "f" * 40
FAKE_GH = """import json, sys
from pathlib import Path

state = Path(__file__).with_name("stan.json")
answers = json.loads(state.read_text(encoding="utf-8"))
with Path(__file__).with_name("wywolania.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
command = sys.argv[1:3]
if command == ["run", "list"]:
    print(json.dumps(answers["runs"]))
elif command == ["run", "view"]:
    print(json.dumps(answers["view"][sys.argv[3]]))
elif command == ["run", "download"]:
    drive = Path(sys.argv[sys.argv.index("--dir") + 1]) / "artefakt" / "drive.txt"
    drive.parent.mkdir(parents=True, exist_ok=True)
    drive.write_text("VERIFY OK | features=all\\n", encoding="utf-8")
"""


class Checkout:
    """Checkout na gałęzi ``praca`` wypchniętej do ``origin`` i atrapa ``gh`` na ``PATH``."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "checkout"
        scripts = self.root / ".agents" / "skills" / "verify-centrum-na-windowsie" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, scripts / SCRIPT.name)
        (self.root / "tools" / "lib").mkdir(parents=True)
        for module in ("skrypt_skilla.py", "jednostka.py"):
            shutil.copy(ROOT / "tools" / "lib" / module, self.root / "tools" / "lib" / module)
        (self.root / ".gitignore").write_text(".verification/\n__pycache__/\n", encoding="utf-8")
        origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--quiet", "--bare", str(origin))
        git(self.root, "init", "--quiet", "--initial-branch=praca")
        self.head = commit(self.root, "start")
        git(self.root, "remote", "add", "origin", str(origin))
        git(self.root, "push", "--quiet", "origin", "praca")
        self.bin = tmp_path / "bin"
        fake_cli(self.bin, "gh", FAKE_GH)
        self.answer(runs=[], view={})

    def answer(self, *, runs: list[dict[str, object]], view: dict[str, dict[str, str]]) -> None:
        (self.bin / "stan.json").write_text(json.dumps({"runs": runs, "view": view}), encoding="utf-8")

    def calls(self) -> list[str]:
        log = self.bin / "wywolania.txt"
        return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / ".agents" / "skills" / "verify-centrum-na-windowsie" / "scripts" / SCRIPT.name), *arguments],
            cwd=self.root,
            env={**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(("checked", "code", "verdict"), [("head", 0, "VERIFY OK | features=all"), ("other", 1, "VERIFY FAIL | the run checked")])
def test_werdykt_istniejacego_runu_dotyczy_tylko_runu_lokalnego_head(tmp_path: Path, checked: str, code: int, verdict: str) -> None:
    checkout = Checkout(tmp_path)
    sha = checkout.head if checked == "head" else OTHER
    checkout.answer(runs=[], view={"7": {"conclusion": "success", "headSha": sha}})

    done = checkout.run("--run", "7")

    assert done.returncode == code, done.stdout + done.stderr
    last = done.stdout.splitlines()[-1]
    assert last.startswith(verdict), last
    assert f"| run=7 | head={sha} |" in last


def test_dispatch_odmawia_startu_gdy_origin_nie_ma_lokalnego_head(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    (checkout.root / "zmiana.txt").write_text("zmiana\n", encoding="utf-8")
    head = commit(checkout.root, "niewypchnięta zmiana")

    done = checkout.run()

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stderr.strip().splitlines()[-1] == (
        f"VERIFY FAIL | origin/praca is {checkout.head}, not HEAD {head}: push HEAD to praca first | head={head}"
    )
    assert not any(call.startswith("workflow run") for call in checkout.calls())


def test_dispatch_przyjmuje_tylko_run_lokalnego_head(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    runs = [{"databaseId": 8, "createdAt": _now(), "headSha": OTHER}, {"databaseId": 9, "createdAt": _now(), "headSha": checkout.head}]
    checkout.answer(runs=runs, view={"8": {"conclusion": "success", "headSha": OTHER}, "9": {"conclusion": "success", "headSha": checkout.head}})

    done = checkout.run()

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[0].startswith("RUN 9 |")
    assert f"| run=9 | head={checkout.head} |" in done.stdout.splitlines()[-1]


def test_dispatch_widzi_cudzy_push_na_galezi_i_odmawia_startu(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    other = tmp_path / "inny-klon"
    git(tmp_path, "clone", "--quiet", "--branch", "praca", str(tmp_path / "origin.git"), str(other))
    (other / "cudza.txt").write_text("cudza zmiana\n", encoding="utf-8")
    pushed = commit(other, "cudza zmiana")
    git(other, "push", "--quiet", "origin", "praca")

    done = checkout.run()

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stderr.strip().splitlines()[-1].startswith(f"VERIFY FAIL | origin/praca is {pushed}, not HEAD {checkout.head}")
    assert not any(call.startswith("workflow run") for call in checkout.calls())


def test_dispatch_bez_dostepu_do_origin_konczy_sie_werdyktem(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    git(checkout.root, "remote", "set-url", "origin", str(tmp_path / "nie-ma.git"))

    done = checkout.run()

    assert done.returncode == 1, done.stdout + done.stderr
    verdict = done.stderr.strip().splitlines()[-1]
    assert verdict.startswith("VERIFY FAIL | git fetch --quiet origin praca:"), verdict
    assert "nie-ma.git" in verdict, "linia werdyktu ma przyczynę od gita"
    assert not any(call.startswith("workflow run") for call in checkout.calls())
