"""Ciężkie narzędzie repo na Macu przenosi się przy starcie na box boat (``tools/lib/na_boxie.py``), a test scalenia
puszcza na box swój pytest.

Testy uruchamiają prawdziwe narzędzia jako procesy z atrapą ``boatbox`` w ``PATH``, która zapisuje swoje argumenty
i katalog i kończy się kodem ``ATRAPA_KOD``, więc żaden box nie startuje. Narzędzie, które zostaje, ma argumenty, przy
których kończy się samo zaraz za decyzją, więc test nie uruchamia jego pełnej pracy.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
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
ARGUMENT_LINUKSA = 131_072
"""Najdłuższy jeden argument polecenia na Linuksie boxa (``MAX_ARG_STRLEN``)."""
CI = {"GITHUB_ACTIONS": "true"}
"""Bez tego ``mutacje_zmiany.py`` i ``ci_lokalnie.py`` odmawiają ciężkich zadań CI, zanim dojdą do przeniesienia."""
PYTEST = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only", "tests/test_adr.py"]
SZYBKO = [PYTHON, "tools/szybko.py", "--baza", "nie/ma/takiej"]
HEAVY = [
    pytest.param(lambda tmp: SZYBKO, {}, id="szybko"),
    pytest.param(lambda tmp: [PYTHON, "tools/mutacje_zmiany.py"], CI, id="mutacje-zmiany"),
    pytest.param(
        lambda tmp: [PYTHON, "tools/benchmark_przebiegu.py", "freeze", "--commit", "0", "--reference-dir", str(tmp / "r"), "--mirror-dir", str(tmp / "l")],
        {},
        id="benchmark-freeze",
    ),
    pytest.param(lambda tmp: [PYTHON, "tools/ci_lokalnie.py", "--tylko", "pytest", "--kazdy-commit", "nie/ma/takiej"], CI, id="ci-lokalnie-pytest"),
    pytest.param(lambda tmp: [*PYTEST, "-n", "2"], {}, id="pytest-z-workerami"),
]
FAKE = """#!/bin/bash
printf '%s\\n' "$PWD" "$@" > "$ATRAPA_ZAPIS/$1"
if [ "$1" = get ]; then mkdir -p "$3" && cp "$ATRAPA_JUNIT" "$3/$2"; fi
if [ "$1" = run ]; then exit "${ATRAPA_KOD:-7}"; fi
"""


def _plan(path: Path, name: str = "ą") -> Path:
    """Plan jednej mutacji, której kotwicy nie ma: przechodzi sprawdzenia ``mutacje.py`` przed przeniesieniem, a na
    miejscu kończy się zaraz linią ``NIEAKTUALNA`` i kodem 1."""

    path.write_text(json.dumps([{"nazwa": name, "zmiany": [["README.md", "nie ma takiej kotwicy", "y"]], "polecenie": ["-c", ""]}]), encoding="utf-8")
    return path


def _fake(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    (folder / "boatbox").write_text(FAKE, encoding="utf-8")
    (folder / "boatbox").chmod(0o755)
    (tmp_path / "zapis").mkdir(exist_ok=True)
    return folder


def _env(tmp_path: Path, *, boatbox: bool = True, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Środowisko agenta w powłoce Maca: bez zmiennych boxa, ``run --here`` i sesji pytest testu, z atrapą ``boatbox``."""

    hidden = (na_boxie.BOX, na_boxie.TUTAJ, na_boxie.SESJA, "PYTEST_VERSION", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "GITHUB_ACTIONS")
    env = {name: value for name, value in os.environ.items() if name not in hidden}
    path = [*[str(_fake(tmp_path))] * boatbox, "/usr/bin", "/bin"]
    return env | {"PATH": os.pathsep.join(path), "ATRAPA_ZAPIS": str(tmp_path / "zapis"), "QUIET_MACHINE_SCRATCH": str(tmp_path / "maszyna"), **(extra or {})}


def _run(
    command: list[str], tmp_path: Path, *, cwd: Path = ROOT, boatbox: bool = True, extra: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _env(tmp_path, boatbox=boatbox, extra=extra)
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def _moved(tmp_path: Path) -> tuple[str, list[str], str] | None:
    """Katalog i argumenty ``boatbox run`` z atrapy oraz treść skryptu, który dostał; ``None``, gdy narzędzie nie wołało
    ``boatbox run``."""

    record = tmp_path / "zapis" / "run"
    if not record.exists():
        return None
    folder, *arguments = record.read_text(encoding="utf-8").splitlines()
    assert arguments[:2] == ["run", "--file"], arguments
    return folder, arguments, Path(arguments[2]).read_text(encoding="utf-8")


def _script(*lines: str) -> str:
    return "\n".join(["set -e", 'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)"', *lines]) + "\n"


def _carried(script: str) -> bytes:
    lines = script.splitlines()
    start = next(number for number, line in enumerate(lines) if line.endswith("<<'NIESIONE'"))
    return base64.b64decode("".join(lines[start + 1 : lines.index("NIESIONE", start)]))


@pytest.mark.parametrize(("build", "extra"), HEAVY)
def test_ciezkie_narzedzie_na_macu_przenosi_sie_na_box_z_tym_samym_poleceniem_i_jego_kodem(
    build: Callable[[Path], list[str]], extra: dict[str, str], tmp_path: Path
) -> None:
    command = build(tmp_path)

    done = _run(command, tmp_path, extra=extra)

    moved = _moved(tmp_path)
    assert (done.returncode, moved and moved[::2]) == (ATRAPA_KOD, (str(ROOT), _script(f"exec .venv/bin/python {shlex.join(command[1:])}"))), done.stderr
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
@pytest.mark.parametrize(("command", "own"), [pytest.param(SZYBKO, 1, id="szybko"), pytest.param([*PYTEST, "-n", "2"], 0, id="pytest-z-workerami")])
def test_na_boxie_przy_run_here_w_sesji_pytest_i_bez_boatbox_narzedzie_zostaje(
    command: list[str], own: int, boatbox: bool, extra: dict[str, str], tmp_path: Path
) -> None:
    done = _run(command, tmp_path, boatbox=boatbox, extra=extra)

    assert (done.returncode, _moved(tmp_path)) == (own, None), done.stdout + done.stderr


@pytest.mark.parametrize("workers", [pytest.param([], id="bez-workerow"), pytest.param(["-n", "0"], id="n-0"), pytest.param(["-n", "1"], id="n-1")])
def test_pytest_bez_workerow_albo_z_jednym_zostaje_na_macu(workers: list[str], tmp_path: Path) -> None:
    done = _run([*PYTEST, *workers], tmp_path)

    assert (done.returncode, _moved(tmp_path)) == (0, None), done.stdout + done.stderr


@pytest.mark.parametrize(
    ("command", "extra"),
    [
        pytest.param([PYTHON, "tools/ci_lokalnie.py", "--tylko", "ruff", "--kazdy-commit", "nie/ma/takiej"], {}, id="ci-lokalnie-bez-pytest"),
        pytest.param([PYTHON, "tools/ci_lokalnie.py", "--tylko", "mutations"], {}, id="ci-lokalnie-odmowa-ciezkiego-ci"),
        pytest.param([PYTHON, "tools/mutacje.py", "--zasady"], {}, id="mutacje-zasady"),
        pytest.param([PYTHON, "tools/mutacje.py", "--plik", "brak.json"], {}, id="mutacje-bez-planu"),
        pytest.param([PYTHON, "tools/mutacje_zmiany.py"], {}, id="mutacje-zmiany-odmowa-ciezkiego-ci"),
        pytest.param([PYTHON, "tools/benchmark_przebiegu.py", "comment", "--journal", "brak.jsonl"], {}, id="benchmark-comment"),
        pytest.param([PYTHON, "tools/benchmark_przebiegu.py", "guard", "--journal", "brak.jsonl", "--budget-ms", "1"], {}, id="benchmark-guard"),
    ],
)
def test_lekki_tryb_albo_szybka_odmowa_ciezkiego_narzedzia_zostaje_na_macu(command: list[str], extra: dict[str, str], tmp_path: Path) -> None:
    done = _run(command, tmp_path, extra=extra)

    assert (done.returncode != ATRAPA_KOD, _moved(tmp_path)) == (True, None), done.stdout + done.stderr


def test_polecenie_z_podkatalogu_wchodzi_do_niego_a_sciezka_pod_repo_jest_wzgledna(tmp_path: Path) -> None:
    done = _run([PYTHON, "szybko.py", "--baza", str(ROOT / "tools" / "nie" / "ma")], tmp_path, cwd=ROOT / "tools")

    moved = _moved(tmp_path)
    assert moved and moved[::2] == (str(ROOT / "tools"), _script("cd tools", "exec ../.venv/bin/python szybko.py --baza nie/ma")), done.stderr


def test_narzedzie_spoza_katalogu_repo_przenosi_sie_z_korzenia_repo(tmp_path: Path) -> None:
    _run([PYTHON, str(ROOT / "tools" / "szybko.py"), "--baza", "nie/ma/takiej"], tmp_path, cwd=tmp_path)

    moved = _moved(tmp_path)
    assert moved and moved[::2] == (str(ROOT), _script("exec .venv/bin/python tools/szybko.py --baza nie/ma/takiej"))


@pytest.mark.parametrize("given", [pytest.param(["--plik", "{plik}"], id="osobno"), pytest.param(["--plik={plik}"], id="po-rownasie")])
def test_plik_mutacji_jedzie_na_box_w_skrypcie(given: list[str], tmp_path: Path) -> None:
    plan = _plan(tmp_path / "plan mutacji.json")

    _run([PYTHON, "tools/mutacje.py", *[word.format(plik=plan) for word in given]], tmp_path)

    moved = _moved(tmp_path)
    assert moved is not None and _carried(moved[2]) == plan.read_bytes(), moved
    assert moved[2].endswith('"$HOME/.boatbox-niesione/plan_mutacji.json"\n'), moved[2]


def test_plik_mutacji_ponad_limit_argumentu_linuksa_jedzie_na_box_w_pliku_skryptu_a_nie_w_argumencie(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "duzy.json", name="m" * 2 * ARGUMENT_LINUKSA)

    _run([PYTHON, "tools/mutacje.py", "--plik", str(plan)], tmp_path)

    moved = _moved(tmp_path)
    assert moved is not None and _carried(moved[2]) == plan.read_bytes()
    assert max(len(argument.encode()) for argument in moved[1]) < ARGUMENT_LINUKSA


IMPORT_ENV = dict(os.environ)
"""Środowisko z chwili importu modułu testów, jak ``WITHOUT_XDIST_WORKERS`` w ``tests/test_mutacje.py``."""


@pytest.mark.skipif("NA_BOXIE_PROBKA" not in os.environ, reason="próbka testu w sesji pytest, którą uruchamia test niżej")
def test_probka_test_uruchamia_narzedzie_ze_srodowiskiem_z_importu() -> None:
    done = subprocess.run(SZYBKO, cwd=ROOT, env=IMPORT_ENV, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

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

    moved = _moved(mac)
    assert failed == ["tests/test_x.py::test_a"]
    assert moved is not None and moved[0] == str(copy), moved
    assert f"--junitxml={testy_scalenia.JUNIT}" in moved[2] and moved[2].endswith(" tests/test_x.py\n"), moved[2]
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
