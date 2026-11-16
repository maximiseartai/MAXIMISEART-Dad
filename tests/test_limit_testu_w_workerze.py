"""Test po limicie pytest-timeout w workerze xdist zostawia w logu limit, swoje id i stosy wątków (``tests/fixtures/limit_testu_w_workerze.py``)."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tests.fixtures import limit_testu_w_workerze

ROOT = Path(__file__).resolve().parents[1]
WISI = "import time\n\n\ndef test_wisi() -> None:\n    time.sleep(60)\n\n\ndef test_obok() -> None:\n    pass\n"
# Linie wątków sprawdzane na końcu modułu, w teardownie ostatniego testu, gdy żyje jeszcze jego timer limitu (#1080).
LINIA_MODULU = (
    "import pytest\n\nfrom tests.fixtures.linie_watkow import new_line, threads_since\n\n\n"
    "@pytest.fixture(scope='module')\ndef linia():\n    since = new_line()\n    yield\n"
    "    assert [thread.name for thread in threads_since(since)] == []\n\n\n"
    "def test_pierwszy(linia) -> None:\n    pass\n\n\ndef test_ostatni(linia) -> None:\n    pass\n"
)


def _pytest(directory: Path, tests: str, limit_s: int, *args: str) -> tuple[int, str]:
    """Przebieg pytest ``tests`` w ``directory`` z limitem metody ``thread`` (jedynej na Windows), bez conftest repozytorium."""

    (directory / "pytest.ini").write_text(f"[pytest]\ntimeout = {limit_s}\ntimeout_method = thread\n", encoding="utf-8")
    (directory / "test_probka.py").write_text(tests, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", limit_testu_w_workerze.__name__, *args, "test_probka.py"],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def test_test_po_limicie_w_workerze_xdist_zostawia_w_logu_limit_swoje_id_i_stosy_watkow(tmp_path: Path) -> None:
    code, out = _pytest(tmp_path, WISI, 1, "-n", "1")

    assert code == pytest.ExitCode.TESTS_FAILED, out
    assert "worker 'gw0' crashed while running 'test_probka.py::test_wisi'" in out, out
    assert re.search(r"^LIMIT TESTU \| 1 s pytest-timeout: test_probka\.py::test_wisi; ", out, re.MULTILINE), out
    assert re.search(r'File ".*test_probka\.py", line 5 in test_wisi', out), out
    # Linia pytest-timeout, którą silnik mutacji czyta jako ZAWIESZENIE, nie powstaje w workerze xdist.
    assert not re.search(r"^\++ Timeout \++$", out, re.MULTILINE), out


def test_test_po_limicie_bez_xdist_konczy_pytest_timeout_ze_swoim_zrzutem(tmp_path: Path) -> None:
    code, out = _pytest(tmp_path, WISI, 1, "-n", "0")

    assert code != pytest.ExitCode.OK, out
    assert re.search(r"^\++ Timeout \++$", out, re.MULTILINE), out
    assert "LIMIT TESTU" not in out, out


def test_timer_limitu_w_workerze_xdist_nie_nalezy_do_linii_watkow_testu(tmp_path: Path) -> None:
    code, out = _pytest(tmp_path, LINIA_MODULU, 30, "-n", "1")

    assert code == pytest.ExitCode.OK, out
