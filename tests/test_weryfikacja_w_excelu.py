"""Narzędzia skilla ``verify-skoroszyty-w-excelu`` nazywają przyczynę, gdy Excel nie odpowiada, i dzielą jednego Excela na Maca.

Prawdziwy Excel sprawdza sam skill (``.agents/skills/verify-skoroszyty-w-excelu/SKILL.md``).
Tu ``osascript``, ``open`` i ``pgrep`` są podstawione na ``PATH``, a ``HOME`` wskazuje katalog testu,
więc żaden test nie dotyka Excela ani jego kontenera.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import ModuleType

import pytest

from tests.fixtures.fake_cli import fake_cli

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="skill steruje Excelem dla Maca")

SKILL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-skoroszyty-w-excelu" / "scripts"

FAKE_OSASCRIPT = """import os, sys
if "-l" in sys.argv:
    print(os.environ.get("FAKE_EXCEL_WINDOWS", ""))
elif "-e" in sys.argv:
    print(os.environ.get("FAKE_EXCEL_RUNNING", "true"))
else:
    sys.stdin.read()
    if "FAKE_APPLESCRIPT_ANSWER" in os.environ:
        print(os.environ["FAKE_APPLESCRIPT_ANSWER"])
        sys.exit(0)
    code = os.environ["FAKE_APPLESCRIPT_ERROR"]
    print(f"271:290: execution error: Microsoft Excel got an error: fake ({code})", file=sys.stderr)
    sys.exit(1)
"""

# Jak ``pgrep -x``: jeden numer procesu w linii, kod 1, gdy żaden proces się nie nazywa tak.
FAKE_PGREP = """import os, sys
ids = os.environ.get("FAKE_EXCEL_PIDS", "").split()
print("\\n".join(ids))
sys.exit(0 if ids else 1)
"""

APPLESCRIPT_DENIED = "-1743"
APPLESCRIPT_REFUSED_DURING_DIALOG = "-1708"
APPLESCRIPT_TIMEOUT = "-1712"
DIALOG_WINDOW = "8 |  | 420x180"


def _fake_commands(tmp_path: Path) -> str:
    """``PATH`` whose ``osascript``, ``open`` and ``pgrep`` are fakes, so no test reaches the real Excel."""

    bin_dir = tmp_path / "bin"
    for name, body in (("osascript", FAKE_OSASCRIPT), ("open", ""), ("pgrep", FAKE_PGREP)):
        fake_cli(bin_dir, name, body)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


@pytest.fixture
def excel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """``excel.py`` with a fake ``osascript`` and ``open``; the test sets ``FAKE_APPLESCRIPT_ERROR``."""

    monkeypatch.setenv("PATH", _fake_commands(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(SKILL_SCRIPTS))
    for name in ("excel", "excel_doctor"):
        sys.modules.pop(name, None)
    yield importlib.import_module("excel")
    for name in ("excel", "excel_doctor"):
        sys.modules.pop(name, None)


@pytest.mark.parametrize("code", [APPLESCRIPT_REFUSED_DURING_DIALOG, APPLESCRIPT_TIMEOUT])
def test_excel_z_oknem_dialogowym_jest_nazwany_oknem_a_nie_brakiem_zgody(
    excel: ModuleType, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    monkeypatch.setenv("FAKE_APPLESCRIPT_ERROR", code)
    monkeypatch.setenv("FAKE_EXCEL_WINDOWS", DIALOG_WINDOW)

    with pytest.raises(excel.ExcelDialog):
        excel.open_paths()
    problems = _doctor_excel_problems()

    assert len(problems) == 1 and "dialog" in problems[0] and "Automatyzacja" not in problems[0], problems


def test_brak_zgody_na_automatyzacje_excela_jest_nazwany(excel: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_APPLESCRIPT_ERROR", APPLESCRIPT_DENIED)

    with pytest.raises(excel.ExcelNotPermitted):
        excel.open_paths()
    problems = _doctor_excel_problems()

    assert len(problems) == 1 and "Automatyzacja" in problems[0] and "dialog" not in problems[0], problems


def test_start_excela_bez_zgody_na_automatyzacje_konczy_sie_od_razu_nazwana_przyczyna(
    excel: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_APPLESCRIPT_ERROR", APPLESCRIPT_DENIED)
    started = time.monotonic()

    with pytest.raises(excel.ExcelNotPermitted):
        excel.launch(timeout=20)

    assert time.monotonic() - started < 10


def test_zimny_start_excela_konczy_sie_numerem_procesu_gdy_excel_odpowiada(
    excel: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_APPLESCRIPT_ANSWER", "Zeszyt1")
    monkeypatch.setenv("FAKE_EXCEL_PIDS", "733")

    assert excel.launch(timeout=20) == 733


def test_bez_dzialajacego_excela_nie_ma_numeru_procesu(excel: ModuleType) -> None:
    assert excel.pid() is None


def test_dwa_procesy_excela_start_konczy_sie_nazwana_przyczyna_a_pamiec_jest_pusta(
    excel: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_APPLESCRIPT_ANSWER", "Zeszyt1")
    monkeypatch.setenv("FAKE_EXCEL_PIDS", "733 734")

    with pytest.raises(excel.ExcelError, match="not one process id"):
        excel.launch(timeout=20)
    assert excel.rss_mb() is None


def _doctor_excel_problems() -> list[str]:
    """The doctor's lines about the running Excel: those it adds over the same check with Excel not running."""

    doctor = importlib.import_module("excel_doctor")
    root, desk = Path("/nonexistent-root"), Path("/nonexistent-desk")
    with_excel: list[str] = doctor.check(root, desk)
    os.environ["FAKE_EXCEL_RUNNING"] = "false"
    try:
        without_excel: list[str] = doctor.check(root, desk)
    finally:
        del os.environ["FAKE_EXCEL_RUNNING"]
    return [problem for problem in with_excel if problem not in without_excel]


# ---- one Excel per Mac ---------------------------------------------------------------------------------

HOLDER = """
import sys
sys.path.insert(0, sys.argv[1])
import excel
try:
    lock = excel.claim(owner=sys.argv[2])
except excel.ExcelBusy as exc:
    print(f"BUSY {exc}", flush=True)
    raise SystemExit(3)
print("HELD", flush=True)
sys.stdin.read()
"""


def _worktree(tmp_path: Path, name: str) -> Path:
    """A copy of the skill's scripts in its own worktree root, as ``git worktree add`` would make it."""

    root = tmp_path / name
    shutil.copytree(SKILL_SCRIPTS, root / ".agents" / "skills" / "verify-skoroszyty-w-excelu" / "scripts")
    (root / "tools" / "lib").mkdir(parents=True)
    for module in ("skrypt_skilla.py", "jednostka.py"):
        shutil.copy(SKILL_SCRIPTS.parents[3] / "tools" / "lib" / module, root / "tools" / "lib")
    shutil.copytree(SKILL_SCRIPTS.parents[3] / "tests" / "fixtures", root / "tests" / "fixtures")
    shutil.copy(SKILL_SCRIPTS.parents[3] / "tests" / "__init__.py", root / "tests")
    return root


def _scripts(root: Path) -> Path:
    return root / ".agents" / "skills" / "verify-skoroszyty-w-excelu" / "scripts"


def _environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    (home / "Library" / "Containers" / "com.microsoft.Excel" / "Data").mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "PATH": _fake_commands(tmp_path),
        "FAKE_APPLESCRIPT_ERROR": "-1712",
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _hold(root: Path, environment: dict[str, str]) -> subprocess.Popen[str]:
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(_scripts(root)), str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "HELD"
    return holder


def test_przebieg_z_drugiego_worktree_nie_startuje_gdy_pierwszy_steruje_excelem(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first, second = _worktree(tmp_path, "worktree-a"), _worktree(tmp_path, "worktree-b")
    holder = _hold(first, environment)
    try:
        refused = subprocess.run(
            [sys.executable, str(_scripts(second) / "run_excel_verification.py"), "--wzorce", "syntetyczne"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=False,
        )
    finally:
        holder.communicate("")

    output = refused.stdout + refused.stderr
    assert refused.returncode == 1, output
    assert "VERIFY FAIL | ExcelBusy" in output and f"pid {holder.pid}" in output and "worktree-a" in output, output
    assert not (second / ".verification" / "runs").exists(), "the refused run built a fixture"


def test_przebieg_bez_prawdziwych_wzorcow_jest_pominieciem_z_wlasnym_kodem_wyjscia(tmp_path: Path) -> None:
    root = _worktree(tmp_path, "worktree")
    (tmp_path / "bez-wzorcow").mkdir()

    skipped = subprocess.run(
        [
            sys.executable,
            str(_scripts(root) / "run_excel_verification.py"),
            *("--templates-dir", str(tmp_path / "bez-wzorcow"), "--run-dir", str(tmp_path / "przebieg")),
        ],
        capture_output=True,
        text=True,
        env=_environment(tmp_path),
        timeout=60,
        check=False,
    )

    output = skipped.stdout + skipped.stderr
    assert skipped.returncode == 3, output
    assert skipped.stdout.splitlines()[-1].startswith("VERIFY SKIP | wzorce=prawdziwe"), output


def test_przebieg_zabity_w_trakcie_nie_blokuje_excela_nastepnemu(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first, second = _worktree(tmp_path, "worktree-a"), _worktree(tmp_path, "worktree-b")
    killed = _hold(first, environment)
    killed.kill()
    killed.wait(timeout=10)

    successor = _hold(second, environment)
    successor.communicate("")

    assert successor.returncode == 0
