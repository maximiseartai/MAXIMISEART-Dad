"""Slot Maca ciężkiego procesu (``tools/lib/slot_maca.py``): na Macu z ``boatbox`` w ``PATH`` ciężki proces bierze slot
``boatbox`` przy starcie, a bez wolnego czeka w kolejce z linią ``CIĘŻKIE`` i rusza po zwolnieniu slotu z własnym kodem
wyjścia.

Testy uruchamiają prawdziwe narzędzia jako procesy z atrapą ``boatbox`` w ``PATH`` i z katalogiem slotów testu, którego
sloty test zajmuje tym samym ``flock`` co ``boatbox``. Każde ciężkie polecenie ma argumenty, przy których zaraz za
bramką kończy się samo, więc test nie uruchamia pełnej pracy narzędzia.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import IO

import pytest

from tests.fixtures.potomne import wait_for

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="sloty Maca to flock, a boatbox biegnie tylko na Macu")

ROOT = Path(__file__).resolve().parents[1]
MUTACJE = [sys.executable, str(ROOT / "tools" / "mutacje.py"), "--plik", "brak.json"]
HEAVY = [
    pytest.param(
        lambda tmp: [sys.executable, str(ROOT / "tools" / "szybko.py"), "--baza", "nie/ma/takiej"],
        "szybko.py",
        "auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8",
        1,
        id="szybko",
    ),
    pytest.param(lambda tmp: MUTACJE, "mutacje.py --plik", "auto", 1, id="mutacje-plik"),
    pytest.param(
        lambda tmp: [
            *[sys.executable, str(ROOT / "tools" / "benchmark_przebiegu.py"), "freeze", "--commit", "0000000"],
            *["--reference-dir", str(tmp / "ref"), "--mirror-dir", str(tmp / "lustro")],
        ],
        "benchmark_przebiegu.py freeze",
        "run --here",
        1,
        id="benchmark-freeze",
    ),
    pytest.param(
        lambda tmp: [sys.executable, str(ROOT / "tools" / "ci_lokalnie.py"), "--tylko", "pytest", "--kazdy-commit", "nie/ma/takiej"],
        "ci_lokalnie.py pytest",
        "auto",
        1,
        id="ci-lokalnie-pytest",
    ),
]


def _lock(slot: IO[str]) -> None:
    if sys.platform != "win32":
        import fcntl

        fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    raise OSError("sloty Maca to flock, którego Windows nie ma")


@contextmanager
def _busy(folder: Path, numbers: range) -> Iterator[None]:
    folder.mkdir(exist_ok=True)
    held = []
    try:
        for number in numbers:
            slot = (folder / str(number)).open("a", encoding="utf-8")
            held.append(slot)
            _lock(slot)
        yield
    finally:
        for slot in held:
            slot.close()


def _env(tmp_path: Path, *, boatbox: bool = True, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "boatbox").write_text("exit 0\n", encoding="utf-8")
    (fake / "boatbox").chmod(0o755)
    hidden = ("PYTEST_VERSION", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "BOATBOX_MAC_SLOT", "BOATBOX_MAC_SLOTS", "BOATBOX_SLOT_DIR")
    env = {name: value for name, value in os.environ.items() if name not in hidden}
    env |= {"PATH": os.pathsep.join([*[str(fake)] * boatbox, "/usr/bin", "/bin"]), "BOATBOX_SLOT_DIR": str(tmp_path / "sloty")}
    return env | {"BOATBOX_MAC_SLOTS": "2", "QUIET_MACHINE_SCRATCH": str(tmp_path / "maszyna"), **(extra or {})}


def _waiting(command: list[str], tmp_path: Path, busy: range, extra: Mapping[str, str] | None = None) -> str:
    errors = tmp_path / "stderr"
    with errors.open("w", encoding="utf-8") as stderr, _busy(tmp_path / "sloty", busy):
        process = subprocess.Popen(command, cwd=ROOT, env=_env(tmp_path, extra=extra), stdout=subprocess.DEVNULL, stderr=stderr)
        try:
            waiting = wait_for(lambda: "CIĘŻKIE" in errors.read_text(encoding="utf-8"), 60)
        finally:
            process.kill()
            process.wait()
    assert waiting, errors.read_text(encoding="utf-8")
    return errors.read_text(encoding="utf-8")


def _run(command: list[str], tmp_path: Path, *, boatbox: bool = True, extra: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = _env(tmp_path, boatbox=boatbox, extra=extra)
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


@pytest.mark.parametrize(("build", "name", "route", "own"), HEAVY)
def test_ciezki_proces_bez_wolnego_slotu_czeka_w_kolejce_i_rusza_po_zwolnieniu_z_wlasnym_kodem(
    build: Callable[[Path], list[str]], name: str, route: str, own: int, tmp_path: Path
) -> None:
    command, errors = build(tmp_path), tmp_path / "stderr"
    with errors.open("w", encoding="utf-8") as stderr:
        with _busy(tmp_path / "sloty", range(1, 3)):
            process = subprocess.Popen(command, cwd=ROOT, env=_env(tmp_path), stdout=subprocess.DEVNULL, stderr=stderr)
            try:
                waiting = wait_for(lambda: "CIĘŻKIE" in errors.read_text(encoding="utf-8"), 60)
                alive = process.poll() is None
            except BaseException:
                process.kill()
                process.wait()
                raise
        code = process.wait(timeout=120)

    said = errors.read_text(encoding="utf-8")
    assert (waiting, alive) == (True, True), said
    assert f"CIĘŻKIE {name} | Mac zajęty (2/2 sloty), czekam 0 s na slot; bez czekania: boatbox {route} '" in said
    assert " ".join(command[1:]) in said
    assert f"pid={process.pid}\n" in (tmp_path / "sloty" / "1.who").read_text(encoding="utf-8")
    assert code == own, said


@pytest.mark.parametrize(
    ("boatbox", "extra"),
    [
        pytest.param(True, {"BOATBOX_MAC_SLOT": "1"}, id="w-slocie-boatbox"),
        pytest.param(False, {}, id="bez-boatbox-w-path"),
    ],
)
def test_proces_w_slocie_albo_bez_boatbox_nie_czeka_na_slot(boatbox: bool, extra: dict[str, str], tmp_path: Path) -> None:
    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(MUTACJE, tmp_path, boatbox=boatbox, extra=extra)

    assert "CIĘŻKIE" not in done.stderr, done.stderr


def test_wolny_slot_bierze_proces_do_konca_a_jadro_zwalnia_go_po_nim(tmp_path: Path) -> None:
    with _busy(tmp_path / "sloty", range(1, 2)):
        done = _run(MUTACJE, tmp_path)

    who = (tmp_path / "sloty" / "2.who").read_text(encoding="utf-8")
    with (tmp_path / "sloty" / "2").open("a", encoding="utf-8") as slot:
        _lock(slot)
    assert "CIĘŻKIE" not in done.stderr, done.stderr
    assert who.startswith("pid=") and f"\ndir={ROOT}\ncmd=" in who


@pytest.mark.parametrize("workers", [pytest.param(["-n", "1"], id="z-workerami"), pytest.param([], id="w-jednym-procesie")])
def test_pytest_nie_czeka_na_slot_bo_limit_czasu_potomka_liczy_narzedzie(workers: list[str], tmp_path: Path) -> None:
    command = [sys.executable, "-m", "pytest", "-q", *workers, "-p", "no:cacheprovider", "--collect-only", str(ROOT / "tests" / "test_slot_maca.py")]

    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(command, tmp_path)

    assert (done.returncode, "CIĘŻKIE" in done.stderr) == (0, False), done.stdout + done.stderr


@pytest.mark.skipif("SLOT_MACA_PROBKA" not in os.environ, reason="próbka polecenia w slocie, którą uruchamia test niżej")
def test_probka_potomek_widzi_slot_rodzica_zajety() -> None:
    with (Path(os.environ["BOATBOX_SLOT_DIR"]) / os.environ["BOATBOX_MAC_SLOT"]).open("a", encoding="utf-8") as slot:
        with pytest.raises(BlockingIOError):
            _lock(slot)


def test_narzedzie_trzyma_slot_przez_caly_bieg_a_potomkowie_dostaja_jego_numer(tmp_path: Path) -> None:
    probe = ["-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_slot_maca.py", "-k", "probka_potomek"]
    mutations = tmp_path / "mutacje.json"
    change = [["tools/lib/slot_maca.py", "LINE_S = 30", "LINE_S = 31"]]
    mutations.write_text(json.dumps([{"nazwa": "bez zmiany zachowania", "zmiany": change, "polecenie": probe}]), encoding="utf-8")

    done = _run([sys.executable, str(ROOT / "tools" / "mutacje.py"), "--plik", str(mutations)], tmp_path, extra={"SLOT_MACA_PROBKA": "1"})

    assert done.returncode == 1, done.stdout + done.stderr
    assert "NIEWYKRYTA: bez zmiany zachowania" in done.stdout + done.stderr


IMPORT_ENV = dict(os.environ)
"""Środowisko z chwili importu modułu, takie jak ``WITHOUT_XDIST_WORKERS`` w ``tests/test_mutacje.py``: bez
``PYTEST_CURRENT_TEST``, które pytest ustawia dopiero w fazie testu."""


@pytest.mark.skipif("SLOT_MACA_PROBKA_TESTU" not in os.environ, reason="próbka testu w sesji pytest, którą uruchamia test niżej")
def test_probka_test_uruchamia_narzedzie_ze_srodowiskiem_z_importu() -> None:
    done = subprocess.run(MUTACJE, cwd=ROOT, env=IMPORT_ENV, capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)

    assert (done.returncode, "CIĘŻKIE" in done.stderr) == (1, False), done.stderr


def test_narzedzie_uruchomione_przez_test_ze_srodowiskiem_z_importu_nie_czeka_na_slot(tmp_path: Path) -> None:
    probe = [sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_slot_maca.py", "-k", "probka_test"]

    with _busy(tmp_path / "sloty", range(1, 3)):
        done = _run(probe, tmp_path, extra={"SLOT_MACA_PROBKA_TESTU": "1"})

    assert (done.returncode, "1 passed" in done.stdout) == (0, True), done.stdout + done.stderr


def test_bez_wlasnej_liczby_slotow_jest_ich_tyle_co_w_boatbox_takze_przy_zerze(tmp_path: Path) -> None:
    said = _waiting(MUTACJE, tmp_path, range(1, 2), extra={"BOATBOX_MAC_SLOTS": "0"})

    assert "Mac zajęty (1/1 sloty)" in said


@pytest.mark.parametrize(
    ("place", "route"),
    [
        pytest.param(lambda tmp: str(tmp / "mutacje.json"), "run --here", id="spoza-worktree"),
        pytest.param(lambda tmp: str(ROOT / ".venv" / "mutacje.json"), "run --here", id="ignorowany-w-worktree"),
        pytest.param(lambda tmp: "brak.json", "auto", id="widziany-przez-gita"),
    ],
)
def test_plik_mutacji_ktorego_box_nie_dostanie_daje_droge_run_here(place: Callable[[Path], str], route: str, tmp_path: Path) -> None:
    said = _waiting([sys.executable, str(ROOT / "tools" / "mutacje.py"), "--plik", place(tmp_path)], tmp_path, range(1, 3))

    assert f"bez czekania: boatbox {route} '" in said
