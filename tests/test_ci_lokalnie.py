"""``tools/ci_lokalnie.py`` odtwarza lokalnie te same polecenia co CI, więc nie może się z nim rozjechać.

Każde polecenie z zadań CI, które narzędzie odtwarza, ma w nim swój krok, a każdy krok narzędzia ma
swoje polecenie w CI. Zadanie i polecenie CI, których narzędzie nie odtwarza, mają wskazane miejsce, które je zastępuje. ``--kazdy-commit``
wskazuje każdy commit gałęzi, na którym krok pada, także gdy HEAD przechodzi.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

from tests.fixtures.ci_workflow import action
from tests.fixtures.git_repo import commit, git, repository
from tests.fixtures.potomne import beating, wait_for, with_grandchild, worktrees

import ci_lokalnie
from kroki_lokalne import Step

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ci_lokalnie.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
# Linie `run:`, które przygotowują runner, a nie sprawdzają kodu.
RUNNER_SETUP = ("pip install", "playwright install", "py -3 -c", "Add-Content", "GITHUB_OUTPUT")


def _tool_steps() -> dict[str, object]:
    answered = subprocess.run(
        [sys.executable, str(TOOL), "--kroki-ci"], capture_output=True, text=True, encoding="utf-8", check=True
    )
    steps: dict[str, object] = json.loads(answered.stdout)
    return steps


def _steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kroki zadania z krokami akcji złożonych z repozytorium (``uses: ./…``) w miejscu kroku, który je woła."""

    return [inner for step in steps for inner in (_steps(action(step["uses"])["runs"]["steps"]) if step.get("uses", "").startswith("./") else [step])]


def _commands(job: dict[str, object]) -> list[str]:
    """Polecenia sprawdzające z kroków `run:` zadania i akcji złożonych, które woła, z `py -3` zapisanym jak `python`."""

    commands = []
    for step in _steps(job.get("steps", [])):  # type: ignore[arg-type]
        for line in str(step.get("run", "")).splitlines():
            command = line.strip().replace("py -3 ", "python ")
            if command.startswith(("python ", "npm ", 'stale="$(git')) and not any(
                setup in command for setup in RUNNER_SETUP
            ):
                commands.append(command)
    return commands


def test_kazde_zadanie_ci_jest_odtworzone_albo_ma_wskazane_zastepstwo() -> None:
    steps = _tool_steps()
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    assert set(jobs) == set(steps["lokalnie"]) | set(steps["gdzie_indziej"]["zadania"])  # type: ignore[call-overload, index]


def test_kazde_polecenie_odtwarzanych_zadan_ma_krok_i_odwrotnie() -> None:
    steps = _tool_steps()
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    fragments: list[str] = steps["fragmenty"]  # type: ignore[assignment]
    elsewhere: list[str] = list(steps["gdzie_indziej"]["polecenia"])  # type: ignore[index]
    commands = [command for job in steps["lokalnie"] for command in _commands(jobs[job])]  # type: ignore[attr-defined]

    without_step = [command for command in commands if not any(fragment in command for fragment in [*fragments, *elsewhere])]
    without_command = [fragment for fragment in [*fragments, *elsewhere] if not any(fragment in command for command in commands)]

    assert without_step == []
    assert without_command == []


@pytest.mark.parametrize("fail_fast", [False, True])
def test_do_pierwszego_bledu_pomija_kroki_po_pierwszym_nieudanym(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fail_fast: bool
) -> None:
    # Pełny przebieg kończy się nakładaniami z praca_w_toku.py; prawdziwe pytają GitHub i git o wszystkie worktree.
    (tmp_path / "tools").mkdir()
    stub = tmp_path / "tools" / "praca_w_toku.py"
    stub.write_text("from pathlib import Path\nPath(__file__).with_suffix('.uruchomiona').touch()\n", encoding="utf-8")
    second_ran = tmp_path / "drugi-krok"
    steps = [
        Step("pierwszy", "ruff", (sys.executable, "-c", "raise SystemExit(1)"), tmp_path),
        Step("drugi", "mypy", (sys.executable, "-c", f"open({str(second_ran)!r}, 'w')"), tmp_path),
    ]
    monkeypatch.setattr(ci_lokalnie, "_steps", lambda root: steps)

    returned = ci_lokalnie.main(["--do-pierwszego-bledu"] if fail_fast else [], root=tmp_path)

    assert returned == 1
    assert "CI LOKALNIE FAIL | pierwszy" in capsys.readouterr().out
    assert second_ran.exists() != fail_fast
    assert stub.with_suffix(".uruchomiona").exists()


def test_kazdy_commit_wskazuje_commit_ze_zlamanym_krokiem_choc_head_przechodzi(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    (repo / "tests" / "test_zepsuty.py").write_text("def test_zepsuty() -> None:\n    assert False\n", encoding="utf-8")
    broken = commit(repo, "zepsuty test")
    (repo / "tests" / "test_zepsuty.py").unlink()
    head = commit(repo, "bez zepsutego testu")
    tool = [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--tylko", "pytest"]

    every_commit = subprocess.run([*tool, "--kazdy-commit", base], capture_output=True, text=True, encoding="utf-8", check=False)
    only_head = subprocess.run(tool, capture_output=True, text=True, encoding="utf-8", check=False)

    assert (only_head.returncode, only_head.stdout.splitlines()[-1]) == (0, "CI LOKALNIE OK | tylko pytest")
    assert (every_commit.returncode, every_commit.stdout.splitlines()[-1]) == (1, f"COMMITY FAIL | {broken[:7]} (pytest)")
    assert "test_zepsuty.py::test_zepsuty" in every_commit.stdout
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "worktree", "list", "--porcelain").count("worktree ")) == (head, 1)


def test_kazdy_commit_przechodzi_gdy_kazdy_commit_przechodzi(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    for name in ("drugi", "trzeci"):
        (repo / "tests" / f"test_{name}.py").write_text(f"def test_{name}() -> None:\n    pass\n", encoding="utf-8")
        commit(repo, name)

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--tylko", "pytest", "--kazdy-commit", base],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "COMMITY OK (2)")


def test_kazdy_commit_od_nieistniejacej_bazy_nazywa_baze_bez_tracebacku(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    commit(repo, "baza")

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--kazdy-commit", "nie-ma-takiej-bazy"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert (answered.returncode, answered.stdout.splitlines()[-1:]) == (1, ["COMMITY FAIL | nieznana baza nie-ma-takiej-bazy"])
    assert "Traceback" not in answered.stderr


def _hanging_repository(path: Path, beats: Path) -> tuple[Path, str]:
    repo = repository(path, {".gitignore": "__pycache__/\n", "tests/test_dobry.py": "def test_dobry() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    hangs = with_grandchild(beats, "time.sleep(600)")
    (repo / "tests" / "test_wisi.py").write_text(
        f"import subprocess\n\n\ndef test_wisi() -> None:\n    subprocess.run({hangs!r})\n", encoding="utf-8"
    )
    commit(repo, "wiszący test")
    return repo, base


def test_przerwane_ci_lokalnie_nie_zostawia_krokow_ani_kopii_commitow(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"
    repo, base = _hanging_repository(tmp_path / "repo", beats)
    command = [sys.executable, str(repo / "tools" / "ci_lokalnie.py"), "--tylko", "pytest", "--kazdy-commit", base]
    started = subprocess.Popen(
        command,
        cwd=repo,
        env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for(beats.exists, 90), "krok pytest nie uruchomił wiszącego testu"
        copies = worktrees(repo)[1:]

        started.kill()
        started.wait(timeout=20)
        wait_for(lambda: not beating(beats) and not any(copy.exists() for copy in copies), 20)

        assert not beating(beats)
        assert (len(copies), [copy for copy in copies if copy.exists()], len(worktrees(repo))) == (1, [], 1)
    finally:
        started.kill()
        started.wait()
