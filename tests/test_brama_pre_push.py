"""Brama ``tools/hooks/pre-push``: push agenta, który wysyła HEAD, przechodzi tylko po ruff i mypy dla obu systemów.

Każdy test robi prawdziwy ``git push`` do tymczasowego repozytorium bare. Test kroków bramy uruchamia prawdziwe
``tools/ci_lokalnie.py`` na małym kodzie, a pozostałe atrapę ``.venv/bin/python``. W CI moduł biegnie w jednym
z zadań ``pytest (Python 3.14, Linux, K/N)`` z planu runu (``tools/plan_ci.py``).
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, copy_files, repository
from tests.fixtures.potomne import wait_for

HOOK = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "pre-push"
WORK_IN_PROGRESS = HOOK.parents[1] / "praca_w_toku.py"
SKILLS_FOR_CHANGE = (
    "tools/skille_dla_zmiany.py", "tools/lib/kroki_skilli.py", "tools/lib/zakres_runu.py", "tools/ci/mutacje_skilli.py", "tools/plan_ci.py", "tools/lib/niestabilne_testy.py", "tools/mutacje_zmiany.py",
    "tools/ci/pokrycie_procesu.py", "tools/lib/wplyw_zmiany.py", "tools/ci_lokalnie.py", "tools/mutacje.py", "tools/lib/sciezki_w_kodzie.py",
)
SKILL = "---\nname: verify-kod\ndescription: kod\npilnuje:\n  - kod/*\n---\n"
BRANCH = "refs/heads/zmiana"
AGENT_MARKERS = ("AI_AGENT", "CLAUDECODE")
# Zmienne, którymi conftest (``git_bez_konfiguracji_komputera``) daje gitowi konfigurację testów.
CONFTEST_GIT_CONFIG = ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL")
TYPE_ERROR_ONLY_IF = 'import sys\n\nif {}:\n    LICZBA: int = "tekst"\n'

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Atrapa .venv/bin/python to skrypt sh, a tools/setup_worktree.py nie włącza bramy na Windows.",
)


def _environment(agent: str | None) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if (not name.startswith("GIT_") or name in CONFTEST_GIT_CONFIG) and name not in AGENT_MARKERS
    }
    if agent is not None:
        environment["AI_AGENT"] = agent
    return environment


def _git(cwd: Path, *args: str, agent: str | None = "claude-code") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        env=_environment(agent),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    remote = tmp_path / "zdalne.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    checkout = repository(
        tmp_path / "checkout",
        {
            ".gitignore": ".venv/\n__pycache__/\n",
            "pyproject.toml": '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nfiles = ["kod"]\n',
            "kod/__init__.py": "",
            "tools/praca_w_toku.py": 'print("NAKŁADANIA | atrapa")\n',
        },
    )
    (checkout / "tools" / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, checkout / "tools" / "hooks" / "pre-push")
    commit(checkout, "start")
    _git(checkout, "config", "core.hooksPath", "tools/hooks")
    _git(checkout, "remote", "add", "origin", str(remote))
    return checkout


def _venv_python(checkout: Path, body: str) -> None:
    """Atrapa ``.venv/bin/python``: ``body`` zamiast ``ci_lokalnie``, a narzędzia linii przed krokami prawdziwym Pythonem."""

    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    real = f'case "$1" in tools/praca_w_toku.py|tools/skille_dla_zmiany.py) exec "{sys.executable}" "$@";; esac'
    python.write_text(f"#!/bin/sh\n{real}\n{body}\n", encoding="utf-8")
    python.chmod(0o755)


def _stub_ci_lokalnie(checkout: Path, *, passes: bool) -> None:
    verdict = "CI LOKALNIE OK" if passes else "CI LOKALNIE FAIL | ruff"
    _venv_python(checkout, f"echo '{verdict}'\nexit {0 if passes else 1}")


def _hanging_ci_lokalnie(checkout: Path) -> list[Path]:
    """Atrapa, która wisi z procesem potomnym jak pytest pod ci_lokalnie; zwraca pliki z PID-ami obu."""

    _venv_python(checkout, "sleep 120 &\necho $! > potomek.pid\necho $$ > ci.pid\nwait")
    return [checkout / "ci.pid", checkout / "potomek.pid"]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_push(checkout: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["git", "push", "origin", f"HEAD:{BRANCH}"],
        cwd=checkout,
        env=_environment("claude-code"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _started_ci(pid_files: list[Path]) -> list[int]:
    assert wait_for(lambda: all(path.exists() and path.read_text().strip() for path in pid_files), 15)
    return [int(path.read_text()) for path in pid_files]


def _remote_branch(checkout: Path) -> str:
    return _git(checkout, "ls-remote", "origin", BRANCH).stdout.split("\t")[0]


@pytest.mark.parametrize(
    ("change", "passes"),
    [
        pytest.param({"kod/test_pada.py": "def test_pada() -> None:\n    assert False\n"}, True, id="pytest pada"),
        pytest.param({"kod/nieuzywany.py": "import os\n"}, False, id="błąd ruff"),
        pytest.param({"kod/tylko_windows.py": TYPE_ERROR_ONLY_IF.format('sys.platform == "win32"')}, False, id="błąd mypy tylko na Windows"),
        pytest.param({"kod/poza_windows.py": TYPE_ERROR_ONLY_IF.format('sys.platform != "win32"')}, False, id="błąd mypy poza Windows"),
    ],
)
def test_push_head_rozstrzygaja_ruff_i_mypy_dla_obu_systemow(checkout: Path, change: dict[str, str], passes: bool) -> None:
    _venv_python(checkout, f'exec "{sys.executable}" "$@"')
    for name, text in change.items():
        (checkout / name).write_text(text, encoding="utf-8")
    head = commit(checkout, "zmiana")

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert (pushed.returncode == 0) == passes, pushed.stdout + pushed.stderr
    assert _remote_branch(checkout) == (head if passes else "")
    assert "NAKŁADANIA" not in pushed.stdout + pushed.stderr


def test_usuniecie_galezi_przechodzi_bez_sprawdzania(checkout: Path) -> None:
    _stub_ci_lokalnie(checkout, passes=True)
    assert _git(checkout, "push", "origin", f"HEAD:{BRANCH}").returncode == 0
    _stub_ci_lokalnie(checkout, passes=False)

    deleted = _git(checkout, "push", "origin", "--delete", BRANCH)

    assert deleted.returncode == 0, deleted.stderr
    assert _remote_branch(checkout) == ""


def test_push_bez_venv_jest_odrzucony_ze_wskazaniem_setup_worktree(checkout: Path) -> None:
    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode != 0
    assert "tools/setup_worktree.py" in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == ""


@pytest.mark.parametrize("potomne_py", ["działa", "z błędem składni"])
def test_push_czlowieka_przechodzi_bez_sprawdzania_i_bez_komunikatu(checkout: Path, potomne_py: str) -> None:
    if potomne_py == "z błędem składni":
        (checkout / "tools" / "lib" / "potomne.py").write_text("def (\n", encoding="utf-8")
    _stub_ci_lokalnie(checkout, passes=False)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}", agent=None)

    assert pushed.returncode == 0, pushed.stderr
    assert "pre-push" not in pushed.stderr + pushed.stdout
    assert "AKTUALIZACJA" not in pushed.stderr + pushed.stdout
    assert "SKILLE VERIFY" not in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == _git(checkout, "rev-parse", "HEAD").stdout.strip()


def test_push_agenta_drukuje_werdykt_aktualizacji_z_main(checkout: Path) -> None:
    shutil.copy2(WORK_IN_PROGRESS, checkout / "tools" / "praca_w_toku.py")
    commit(checkout, "narzędzie")
    assert _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/main", agent=None).returncode == 0
    (checkout / "kod" / "nowy.py").write_text("x = 1\n", encoding="utf-8")
    commit(checkout, "zmiana")
    _stub_ci_lokalnie(checkout, passes=True)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    lines = (pushed.stdout + pushed.stderr).splitlines()
    assert next(line for line in lines if line.startswith("AKTUALIZACJA: ")).startswith("AKTUALIZACJA: niepotrzebna"), lines


BROKEN_VERDICTS = {
    "werdykt pada": ("tools/praca_w_toku.py", 'raise SystemExit("git: zepsuty")\n', "(tools/praca_w_toku.py: git: zepsuty)"),
    "potomne.py z błędem składni": ("tools/lib/potomne.py", "def (\n", "(SyntaxError: "),
    "werdykt wisi": ("tools/praca_w_toku.py", "import time\ntime.sleep(60)\n", "(TimeoutExpired: "),
}


@pytest.mark.parametrize(
    ("broken", "passes"),
    [("werdykt pada", True), ("werdykt pada", False), ("potomne.py z błędem składni", True), ("werdykt wisi", True)],
)
def test_nieudany_werdykt_aktualizacji_nie_zmienia_wyniku_pushu(checkout: Path, broken: str, passes: bool) -> None:
    path, text, reason = BROKEN_VERDICTS[broken]
    (checkout / path).write_text(text, encoding="utf-8")
    head = commit(checkout, "zepsuty werdykt")
    _stub_ci_lokalnie(checkout, passes=passes)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert (pushed.returncode == 0) == passes, pushed.stdout + pushed.stderr
    assert _remote_branch(checkout) == (head if passes else "")
    lines = (pushed.stdout + pushed.stderr).splitlines()
    assert [line for line in lines if line.startswith("AKTUALIZACJA: ")] == [
        next(line for line in lines if line.startswith(f"AKTUALIZACJA: nieznana {reason}"))
    ], lines


def _with_skills_for_change(checkout: Path, *, main: bool) -> None:
    """Narzędzie skilli i skill ``verify-kod`` pilnujący ``kod/*`` w checkoucie, z ``main``: ``origin/main`` na tym commicie."""

    copy_files(checkout, SKILLS_FOR_CHANGE)
    (checkout / ".agents" / "skills" / "verify-kod").mkdir(parents=True)
    (checkout / ".agents" / "skills" / "verify-kod" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    commit(checkout, "skill")
    if main:
        assert _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/main", agent=None).returncode == 0


def _skills_lines(checkout: Path, changed: str) -> list[str]:
    (checkout / changed).write_text("x = 1\n", encoding="utf-8")
    commit(checkout, "zmiana")
    _stub_ci_lokalnie(checkout, passes=True)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    return [line for line in (pushed.stdout + pushed.stderr).splitlines() if line.startswith("SKILLE VERIFY: ")]


@pytest.mark.parametrize(("changed", "line"), [("kod/nowy.py", "SKILLE VERIFY: verify-kod"), ("inny.txt", "SKILLE VERIFY: brak")])
def test_push_agenta_drukuje_skille_dla_zmiany(checkout: Path, changed: str, line: str) -> None:
    _with_skills_for_change(checkout, main=True)

    assert _skills_lines(checkout, changed) == [line]


def test_push_agenta_bez_origin_main_drukuje_powod_nieznanych_skilli(checkout: Path) -> None:
    _with_skills_for_change(checkout, main=False)

    [line] = _skills_lines(checkout, "kod/nowy.py")

    assert line.startswith("SKILLE VERIFY: nieznane (git merge-base: fatal: "), line


BROKEN_SKILLS = {
    "narzędzie pada": ('raise SystemExit("skille: zepsute")\n', "SKILLE VERIFY: nieznane (tools/skille_dla_zmiany.py: skille: zepsute)"),
    "narzędzie wisi": ("import time\ntime.sleep(60)\n", "SKILLE VERIFY: nieznane (TimeoutExpired: "),
}


@pytest.mark.parametrize(
    ("broken", "passes"), [("narzędzie pada", True), ("narzędzie pada", False), ("narzędzie wisi", True)]
)
def test_nieudane_skille_dla_zmiany_nie_zmieniaja_wyniku_pushu(checkout: Path, broken: str, passes: bool) -> None:
    text, line = BROKEN_SKILLS[broken]
    (checkout / "tools" / "skille_dla_zmiany.py").write_text(text, encoding="utf-8")
    head = commit(checkout, "zepsute skille")
    _stub_ci_lokalnie(checkout, passes=passes)

    pushed = _git(checkout, "push", "origin", f"HEAD:{BRANCH}")

    assert (pushed.returncode == 0) == passes, pushed.stdout + pushed.stderr
    assert _remote_branch(checkout) == (head if passes else "")
    lines = (pushed.stdout + pushed.stderr).splitlines()
    assert [found for found in lines if found.startswith("SKILLE VERIFY: ")] == [
        next(found for found in lines if found.startswith(line))
    ], lines


def test_push_z_samym_claudecode_rozstrzyga_brama(checkout: Path) -> None:
    _stub_ci_lokalnie(checkout, passes=False)

    pushed = subprocess.run(
        ["git", "push", "origin", f"HEAD:{BRANCH}"],
        cwd=checkout,
        env=_environment(None) | {"CLAUDECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert pushed.returncode != 0
    assert "CI LOKALNIE FAIL" in pushed.stdout + pushed.stderr
    assert _remote_branch(checkout) == ""


@pytest.mark.parametrize("detached", [False, True])
def test_push_head_odlaczonego_albo_galezi_rozstrzyga_brama(checkout: Path, detached: bool) -> None:
    _git(checkout, "checkout", "-q", "-b", "zmiana")
    _git(checkout, "push", "-q", "origin", "zmiana", agent=None)
    published = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "nowy commit")
    if detached:
        _git(checkout, "checkout", "-q", "--detach")
    _stub_ci_lokalnie(checkout, passes=False)

    pushed = _git(checkout, "push", "origin", "HEAD:zmiana" if detached else "zmiana")

    assert pushed.returncode != 0
    assert "CI LOKALNIE FAIL" in pushed.stderr + pushed.stdout
    assert _remote_branch(checkout) == published


GROUP_SIGNALS = {"SIGTERM": signal.SIGTERM}
if sys.platform != "win32":
    GROUP_SIGNALS["SIGKILL"] = signal.SIGKILL


@pytest.mark.parametrize("stop", sorted(GROUP_SIGNALS))
def test_sprawdzenie_nie_przezywa_sygnalu_dla_grupy_pushu(checkout: Path, stop: str) -> None:
    pid_files = _hanging_ci_lokalnie(checkout)
    push = _start_push(checkout)
    started = _started_ci(pid_files)

    os.kill(-push.pid, GROUP_SIGNALS[stop])
    push.wait(timeout=10)

    assert wait_for(lambda: not any(_alive(pid) for pid in started), 15)


@pytest.mark.parametrize("pushed", ["v0.2.0", "HEAD:refs/heads/zmiana v0.2.0"], ids=["sam-tag", "z-galezia"])
def test_push_tagu_wydania_przez_agenta_jest_odrzucony(checkout: Path, pushed: str) -> None:
    _stub_ci_lokalnie(checkout, passes=True)
    _git(checkout, "tag", "v0.2.0")

    rejected = _git(checkout, "push", "origin", *pushed.split())

    assert rejected.returncode != 0
    assert "tagów Wydania" in rejected.stdout + rejected.stderr
    assert _git(checkout, "ls-remote", "origin", "refs/tags/v0.2.0").stdout == ""


def test_tag_wydania_wypycha_narzedzie_wydan_i_czlowiek_a_inny_tag_agent(checkout: Path) -> None:
    _stub_ci_lokalnie(checkout, passes=True)
    for tag in ("v0.2.0", "v0.3.0", "proba"):
        _git(checkout, "tag", tag)
    release_tool = _environment("claude-code") | {"MAXIMISEART_WYDANIE": "1"}

    by_tool = subprocess.run(["git", "push", "origin", "v0.2.0"], cwd=checkout, env=release_tool, capture_output=True, text=True, check=False)
    by_human = _git(checkout, "push", "origin", "v0.3.0", agent=None)
    other = _git(checkout, "push", "origin", "proba")

    assert [by_tool.returncode, by_human.returncode, other.returncode] == [0, 0, 0], by_tool.stderr + other.stderr
    assert len(_git(checkout, "ls-remote", "--tags", "origin").stdout.splitlines()) == 3


@pytest.mark.parametrize("value", ["0", "", "tak"], ids=["zero", "pusta", "inna"])
def test_furtka_narzedzia_wydan_otwiera_sie_tylko_na_jedynke(checkout: Path, value: str) -> None:
    _stub_ci_lokalnie(checkout, passes=True)
    _git(checkout, "tag", "v0.2.0")

    rejected = subprocess.run(
        ["git", "push", "origin", "v0.2.0"],
        cwd=checkout,
        env=_environment("claude-code") | {"MAXIMISEART_WYDANIE": value},
        capture_output=True,
        text=True,
        check=False,
    )

    assert rejected.returncode != 0
    assert _git(checkout, "ls-remote", "origin", "refs/tags/v0.2.0").stdout == ""
