"""Ciężkie narzędzie repo na Macu przenosi się przy starcie na box boat (``tools/lib/na_boxie.py``), a test scalenia
puszcza na box swój pytest.

Testy uruchamiają prawdziwe narzędzia jako procesy z atrapą ``boatbox`` w ``PATH``, która zapisuje swoje argumenty
i katalog i kończy się kodem ``ATRAPA_KOD``, więc żaden box nie startuje. Narzędzie, które zostaje, ma argumenty, przy
których kończy się samo zaraz za decyzją, więc test nie uruchamia jego pełnej pracy.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

import na_boxie
import testy_scalenia

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="boatbox biegnie tylko na Macu, a przeniesienie to exec")

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
ATRAPA_KOD = 7
MUTACJE = [PYTHON, "tools/mutacje.py", "--plik", "brak.json"]
PYTEST = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only", "tests/test_adr.py"]
HEAVY = [
    pytest.param(lambda tmp: [PYTHON, "tools/szybko.py", "--baza", "nie/ma/takiej"], 1, id="szybko"),
    pytest.param(lambda tmp: MUTACJE, 1, id="mutacje"),
    pytest.param(lambda tmp: [PYTHON, "tools/mutacje_zmiany.py", "--pokrycie-czesc", "1/2"], 2, id="mutacje-zmiany"),
    pytest.param(lambda tmp: [PYTHON, "tools/benchmark_przebiegu.py", "comment", "--journal", str(tmp / "brak.jsonl")], 1, id="benchmark"),
    pytest.param(lambda tmp: [PYTHON, "tools/ci_lokalnie.py", "--tylko", "pytest", "--kazdy-commit", "nie/ma/takiej"], 1, id="ci-lokalnie-pytest"),
    pytest.param(lambda tmp: [*PYTEST, "-n", "2"], 0, id="pytest-z-workerami"),
]
FAKE = """#!/bin/bash
printf '%s\\n' "$PWD" "$@" > "$ATRAPA_ZAPIS/$1"
if [ "$1" = get ]; then mkdir -p "$3" && cp "$ATRAPA_JUNIT" "$3/$2"; fi
if [ "$1" = run ]; then exit "${ATRAPA_KOD:-7}"; fi
"""


def _fake(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    (folder / "boatbox").write_text(FAKE, encoding="utf-8")
    (folder / "boatbox").chmod(0o755)
    (tmp_path / "zapis").mkdir(exist_ok=True)
    return folder


def _env(tmp_path: Path, *, boatbox: bool = True, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Środowisko agenta w powłoce Maca: bez zmiennych boxa, ``run --here`` i sesji pytest testu, z atrapą ``boatbox``."""

    hidden = (na_boxie.BOX, na_boxie.TUTAJ, na_boxie.SESJA, "PYTEST_VERSION", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER")
    env = {name: value for name, value in os.environ.items() if name not in hidden}
    path = [*[str(_fake(tmp_path))] * boatbox, "/usr/bin", "/bin"]
    return env | {"PATH": os.pathsep.join(path), "ATRAPA_ZAPIS": str(tmp_path / "zapis"), "QUIET_MACHINE_SCRATCH": str(tmp_path / "maszyna"), **(extra or {})}


def _run(
    command: list[str], tmp_path: Path, *, cwd: Path = ROOT, boatbox: bool = True, extra: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _env(tmp_path, boatbox=boatbox, extra=extra)
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def _moved(tmp_path: Path) -> list[str] | None:
    """Katalog i argumenty ``boatbox run`` z atrapy; ``None``, gdy narzędzie nie wołało ``boatbox run``."""

    record = tmp_path / "zapis" / "run"
    return record.read_text(encoding="utf-8").splitlines() if record.exists() else None


@pytest.mark.parametrize(("build", "own"), HEAVY)
def test_ciezkie_narzedzie_na_macu_przenosi_sie_na_box_z_tym_samym_poleceniem_i_jego_kodem(build: Callable[[Path], list[str]], own: int, tmp_path: Path) -> None:
    command = build(tmp_path)

    done = _run(command, tmp_path)

    expected = f'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)" && .venv/bin/python {shlex.join(command[1:])}'
    assert (done.returncode, _moved(tmp_path)) == (ATRAPA_KOD, [str(ROOT), "run", expected]), done.stderr
    assert "NA BOXIE | ciężkie narzędzie repo nie biegnie na Macu" in done.stderr


@pytest.mark.parametrize(
    ("boatbox", "extra"),
    [
        pytest.param(True, {na_boxie.BOX: "1"}, id="na-boxie"),
        pytest.param(True, {na_boxie.TUTAJ: "1"}, id="boatbox-run-here"),
        pytest.param(True, {na_boxie.SESJA: "1"}, id="w-sesji-pytest"),
        pytest.param(False, {}, id="bez-boatbox-w-path"),
    ],
)
@pytest.mark.parametrize(("build", "own"), [HEAVY[1], HEAVY[-1]])
def test_na_boxie_przy_run_here_w_sesji_pytest_i_bez_boatbox_narzedzie_zostaje(
    build: Callable[[Path], list[str]], own: int, boatbox: bool, extra: dict[str, str], tmp_path: Path
) -> None:
    done = _run(build(tmp_path), tmp_path, boatbox=boatbox, extra=extra)

    assert (done.returncode, _moved(tmp_path)) == (own, None), done.stdout + done.stderr


@pytest.mark.parametrize("workers", [pytest.param([], id="bez-workerow"), pytest.param(["-n", "0"], id="n-0"), pytest.param(["-n", "1"], id="n-1")])
def test_pytest_bez_workerow_albo_z_jednym_zostaje_na_macu(workers: list[str], tmp_path: Path) -> None:
    done = _run([*PYTEST, *workers], tmp_path)

    assert (done.returncode, _moved(tmp_path)) == (0, None), done.stdout + done.stderr


def test_polecenie_z_podkatalogu_wchodzi_do_niego_a_sciezka_pod_repo_jest_wzgledna(tmp_path: Path) -> None:
    done = _run([PYTHON, "szybko.py", "--baza", str(ROOT / "tools" / "nie" / "ma")], tmp_path, cwd=ROOT / "tools")

    command = 'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)" && cd tools && ../.venv/bin/python szybko.py --baza nie/ma'
    assert _moved(tmp_path) == [str(ROOT / "tools"), "run", command], done.stderr


def test_narzedzie_spoza_katalogu_repo_przenosi_sie_z_korzenia_repo(tmp_path: Path) -> None:
    _run([PYTHON, str(ROOT / "tools" / "szybko.py"), "--baza", "nie/ma/takiej"], tmp_path, cwd=tmp_path)

    command = 'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)" && .venv/bin/python tools/szybko.py --baza nie/ma/takiej'
    assert _moved(tmp_path) == [str(ROOT), "run", command]


@pytest.mark.parametrize(
    "command",
    [
        pytest.param([PYTHON, "tools/ci_lokalnie.py", "--tylko", "ruff", "--kazdy-commit", "nie/ma/takiej"], id="ci-lokalnie-bez-pytest"),
        pytest.param([PYTHON, "tools/mutacje.py", "--zasady"], id="mutacje-zasady"),
    ],
)
def test_lekki_tryb_ciezkiego_narzedzia_zostaje_na_macu(command: list[str], tmp_path: Path) -> None:
    done = _run(command, tmp_path)

    assert (done.returncode != ATRAPA_KOD, _moved(tmp_path)) == (True, None), done.stdout + done.stderr


@pytest.mark.parametrize("given", [pytest.param(["--plik", "{plik}"], id="osobno"), pytest.param(["--plik={plik}"], id="po-rownasie")])
def test_plik_mutacji_jedzie_na_box_w_poleceniu(given: list[str], tmp_path: Path) -> None:
    plan = tmp_path / "plan mutacji.json"
    plan.write_text('[{"nazwa": "ą"}]', encoding="utf-8")

    _run([PYTHON, "tools/mutacje.py", *[word.format(plik=plan) for word in given]], tmp_path)

    moved = _moved(tmp_path)
    assert moved is not None
    carried = re.search(r"printf %s (\S+) \| base64 -d > \"\$HOME/\.boatbox-niesione/plan_mutacji\.json\"", moved[2])
    assert carried is not None and base64.b64decode(carried[1]) == plan.read_bytes(), moved[2]
    assert moved[2].endswith('"$HOME/.boatbox-niesione/plan_mutacji.json"'), moved[2]


IMPORT_ENV = dict(os.environ)
"""Środowisko z chwili importu modułu testów, jak ``WITHOUT_XDIST_WORKERS`` w ``tests/test_mutacje.py``."""


@pytest.mark.skipif("NA_BOXIE_PROBKA" not in os.environ, reason="próbka testu w sesji pytest, którą uruchamia test niżej")
def test_probka_test_uruchamia_narzedzie_ze_srodowiskiem_z_importu() -> None:
    done = subprocess.run(MUTACJE, cwd=ROOT, env=IMPORT_ENV, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

    assert "NA BOXIE" not in done.stderr, done.stderr


def test_narzedzie_uruchomione_przez_test_w_sesji_pytest_zostaje_przy_sesji(tmp_path: Path) -> None:
    probe = [*PYTEST[:-2], "-n", "0", "tests/test_na_boxie.py", "-k", "probka"]

    done = _run(probe, tmp_path, extra={"NA_BOXIE_PROBKA": "1"})

    assert (done.returncode, "1 passed" in done.stdout, _moved(tmp_path)) == (0, True, None), done.stdout + done.stderr


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="test_a" file="tests/test_x.py"><failure message="padł"/>
</testcase></testsuite></testsuites>
"""


@pytest.fixture
def mac(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Proces testu jak narzędzie na Macu: atrapa ``boatbox`` w ``PATH``, poza sesją pytest i poza boxem."""

    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    for name, value in (_env(tmp_path) | {"ATRAPA_JUNIT": str(junit)}).items():
        monkeypatch.setenv(name, value)
    for name in (na_boxie.SESJA, na_boxie.BOX, na_boxie.TUTAJ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_test_scalenia_na_macu_biegnie_na_boxie_kopii_a_junit_wraca_z_boxa(mac: Path) -> None:
    copy = mac / "kopia"
    copy.mkdir()

    failed = testy_scalenia.failed_tests(copy, ["tests/test_x.py"], "test scalenia z main")

    run = (mac / "zapis" / "run").read_text(encoding="utf-8").splitlines()
    assert failed == ["tests/test_x.py::test_a"]
    assert run[:2] == [str(copy), "run"] and f"--junitxml={testy_scalenia.JUNIT}" in run[2] and run[2].endswith(" tests/test_x.py"), run
    assert (mac / "zapis" / "get").read_text(encoding="utf-8").splitlines()[:3] == [str(copy), "get", testy_scalenia.JUNIT]
    assert (mac / "zapis" / "rm").exists()


def test_test_scalenia_gdy_box_nie_wstal_to_odmowa_bez_biegu_na_macu(mac: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATRAPA_KOD", str(na_boxie.NIE_WSTAL))
    copy = mac / "kopia"
    copy.mkdir()

    with pytest.raises(testy_scalenia.Refused, match="box boat nie wstał"):
        testy_scalenia.failed_tests(copy, ["tests/test_x.py"], "test scalenia z main")

    assert (not (mac / "zapis" / "get").exists(), (mac / "zapis" / "rm").exists()) == (True, True)


def test_junit_testu_scalenia_na_boxie_jest_ignorowany_przez_gita_bo_inaczej_sesja_pada_na_drzewie_repo() -> None:
    assert testy_scalenia.JUNIT in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
