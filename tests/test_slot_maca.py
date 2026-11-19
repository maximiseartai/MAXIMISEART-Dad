"""Slot Maca ciężkiego procesu (``tools/lib/slot_maca.py``): na Macu z ``boatbox`` w ``PATH`` ciężki proces bierze slot
``boatbox`` przy starcie, a bez wolnego slotu kończy się kodem 75 z gotowym poleceniem ``boatbox``.

Testy uruchamiają prawdziwe narzędzia jako procesy z atrapą ``boatbox`` w ``PATH`` i z katalogiem slotów testu, którego
sloty test zajmuje tym samym ``flock`` co ``boatbox``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="sloty Maca to flock, a boatbox biegnie tylko na Macu")

ROOT = Path(__file__).resolve().parents[1]
MUTACJE = [sys.executable, str(ROOT / "tools" / "mutacje.py"), "--plik", "brak.json"]
HEAVY = [
    pytest.param([sys.executable, str(ROOT / "tools" / "szybko.py")], "szybko.py", "auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8", id="szybko"),
    pytest.param(MUTACJE, "mutacje.py --plik", "auto", id="mutacje-plik"),
    pytest.param(
        [sys.executable, str(ROOT / "tools" / "benchmark_przebiegu.py"), "measure", "--scenario", "typowy-tydzien"],
        "benchmark_przebiegu.py measure",
        "run --here",
        id="benchmark-measure",
    ),
    pytest.param(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "no:cacheprovider", str(ROOT / "tests" / "test_slot_maca.py")],
        "pytest",
        "auto",
        id="pytest-z-workerami",
    ),
]


@contextmanager
def _busy(folder: Path, numbers: range) -> Iterator[None]:
    import fcntl

    folder.mkdir(exist_ok=True)
    held = []
    try:
        for number in numbers:
            slot = (folder / str(number)).open("a", encoding="utf-8")
            held.append(slot)
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for slot in held:
            slot.close()


def _run(command: list[str], tmp_path: Path, *, boatbox: bool = True, **extra: str) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "boatbox").write_text("exit 0\n", encoding="utf-8")
    (fake / "boatbox").chmod(0o755)
    hidden = ("PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "BOATBOX_MAC_SLOT", "BOATBOX_MAC_SLOTS", "BOATBOX_SLOT_DIR")
    env = {name: value for name, value in os.environ.items() if name not in hidden}
    env |= {"PATH": os.pathsep.join([*[str(fake)] * boatbox, "/usr/bin", "/bin"]), "BOATBOX_SLOT_DIR": str(tmp_path / "sloty")}
    env |= {"BOATBOX_MAC_SLOTS": "2", **extra}
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)


@pytest.mark.parametrize(("command", "name", "route"), HEAVY)
def test_ciezki_proces_bez_wolnego_slotu_maca_konczy_sie_kodem_75_z_poleceniem_boatbox(
    command: list[str], name: str, route: str, tmp_path: Path
) -> None:
    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(command, tmp_path)

    assert done.returncode == 75, done.stderr
    assert f"CIĘŻKIE {name} | Mac zajęty (2/2 sloty): uruchom przez boatbox {route} '" in done.stderr
    assert " ".join(command[1:]) in done.stderr


@pytest.mark.parametrize(
    ("boatbox", "extra"),
    [
        pytest.param(True, {"BOATBOX_MAC_SLOT": "1"}, id="w-slocie-boatbox"),
        pytest.param(True, {"PYTEST_CURRENT_TEST": "tests/test_x.py::test_x (call)"}, id="w-tescie-pytest"),
        pytest.param(False, {}, id="bez-boatbox-w-path"),
    ],
)
def test_proces_w_slocie_w_tescie_albo_bez_boatbox_nie_czeka_na_slot(boatbox: bool, extra: dict[str, str], tmp_path: Path) -> None:
    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(MUTACJE, tmp_path, boatbox=boatbox, **extra)

    assert (done.returncode, "Mac zajęty" in done.stderr) != (75, True), done.stderr


def test_wolny_slot_bierze_proces_do_konca_a_jadro_zwalnia_go_po_nim(tmp_path: Path) -> None:
    import fcntl

    with _busy(tmp_path / "sloty", range(1, 2)):
        done = _run(MUTACJE, tmp_path)

    who = (tmp_path / "sloty" / "2.who").read_text(encoding="utf-8")
    with (tmp_path / "sloty" / "2").open("a", encoding="utf-8") as slot:
        fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert done.returncode != 75, done.stderr
    assert who.startswith("pid=") and f"\ndir={ROOT}\ncmd=" in who


def test_pytest_bez_workerow_z_plikiem_testow_nie_bierze_slotu(tmp_path: Path) -> None:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only", str(ROOT / "tests" / "test_slot_maca.py")]

    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(command, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif("SLOT_MACA_PROBKA" not in os.environ, reason="próbka sesji pytest w slocie, którą uruchamia test niżej")
def test_probka_worker_widzi_slot_rodzica_zajety() -> None:
    import fcntl

    with (Path(os.environ["BOATBOX_SLOT_DIR"]) / os.environ["BOATBOX_MAC_SLOT"]).open("a", encoding="utf-8") as slot:
        with pytest.raises(BlockingIOError):
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_proces_trzyma_slot_przez_caly_bieg_a_potomkowie_dostaja_jego_numer(tmp_path: Path) -> None:
    command = [sys.executable, "-m", "pytest", "-q", "-n", "1", "-p", "no:cacheprovider", str(ROOT / "tests" / "test_slot_maca.py"), "-k", "probka"]

    done = _run(command, tmp_path, SLOT_MACA_PROBKA="1")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 passed" in done.stdout, done.stdout
