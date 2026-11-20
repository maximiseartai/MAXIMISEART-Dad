"""Ciężkie wejście repo uruchomione na Macu nie rusza, tylko odmawia z gotowym poleceniem ``boatbox``
(``tools/lib/na_boxie.py``), a test scalenia puszcza na box swój pytest.

Testy uruchamiają prawdziwe narzędzia jako procesy z atrapą ``boatbox`` w ``PATH``, która zapisuje swoje argumenty
i katalog i kończy się kodem ``ATRAPA_KOD``, więc żaden box nie startuje. Narzędzie, które nie odmawia, ma argumenty,
przy których kończy się samo zaraz za decyzją, więc test nie uruchamia jego pełnej pracy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import na_boxie
import potomne
import testy_scalenia

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="boatbox biegnie tylko na Macu")

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
ATRAPA_KOD = 7
CI = {"GITHUB_ACTIONS": "true"}
"""Bez tego ``mutacje_zmiany.py`` i ``ci_lokalnie.py`` odmawiają ciężkich zadań CI, zanim dojdą do decyzji o Macu."""
PYTEST = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only", "tests/test_adr.py"]
SZYBKO = [PYTHON, "tools/szybko.py", "--baza", "nie/ma/takiej"]
PLAN = '[{"nazwa": "x", "zmiany": [["README.md", "nie ma takiej kotwicy", "y"]], "polecenie": ["-c", ""]}]'
"""Plan jednej mutacji, której kotwicy nie ma: przechodzi sprawdzenia ``mutacje.py`` przed decyzją, a bez odmowy kończy
się zaraz linią ``NIEAKTUALNA``."""
HEAVY = [
    pytest.param(lambda tmp: SZYBKO, {}, id="szybko"),
    pytest.param(lambda tmp: [PYTHON, "tools/mutacje.py", "--plik", str(tmp / "plan.json")], {}, id="mutacje-plik"),
    pytest.param(lambda tmp: [PYTHON, "tools/mutacje_zmiany.py"], CI, id="mutacje-zmiany"),
    pytest.param(lambda tmp: [PYTHON, "tools/benchmark_przebiegu.py", "freeze", "--commit", "0"], {}, id="benchmark-freeze"),
    pytest.param(lambda tmp: [PYTHON, "tools/ci_lokalnie.py", "--tylko", "pytest", "--kazdy-commit", "nie/ma/takiej"], CI, id="ci-lokalnie-pytest"),
    pytest.param(lambda tmp: [PYTHON, "tools/na_scalonych_pr.py", "--commit", "HEAD", "--", "tools/mutacje_zmiany.py", "--baza", "HEAD"], {}, id="na-scalonych-pr"),
    pytest.param(lambda tmp: [*PYTEST, "-n", "2"], {}, id="pytest-z-workerami"),
    pytest.param(lambda tmp: [PYTHON, ".agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py"], {}, id="skrypt-mutacji-skilla"),
    pytest.param(lambda tmp: [PYTHON, ".agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py"], {}, id="model-tlc-skilla"),
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
    (tmp_path / "plan.json").write_text(PLAN, encoding="utf-8")
    return folder


def _env(tmp_path: Path, *, boatbox: bool = True, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Środowisko agenta w powłoce Maca: bez zmiennych boxa, ``run --here`` i znacznika narzędzia repo (tu: sesji pytest
    testu), z atrapą ``boatbox``."""

    hidden = (na_boxie.BOX, na_boxie.TUTAJ, potomne.NARZEDZIE, "PYTEST_VERSION", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "GITHUB_ACTIONS")
    env = {name: value for name, value in os.environ.items() if name not in hidden}
    path = [*[str(_fake(tmp_path))] * boatbox, "/usr/bin", "/bin"]
    return env | {"PATH": os.pathsep.join(path), "ATRAPA_ZAPIS": str(tmp_path / "zapis"), "QUIET_MACHINE_SCRATCH": str(tmp_path / "maszyna"), **(extra or {})}


def _run(
    command: list[str], tmp_path: Path, *, cwd: Path = ROOT, boatbox: bool = True, extra: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _env(tmp_path, boatbox=boatbox, extra=extra)
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def _called(tmp_path: Path) -> list[str]:
    """Polecenia ``boatbox``, które atrapa dostała."""

    return sorted(path.name for path in (tmp_path / "zapis").iterdir())


def _refusal(command: str) -> str:
    return f"CIĘŻKIE NA MACU ODMOWA | uruchom: boatbox run {shlex.quote(command)}"


@pytest.mark.parametrize(("build", "extra"), HEAVY)
def test_ciezkie_wejscie_na_macu_nie_rusza_tylko_odmawia_z_tym_samym_poleceniem_dla_boatbox(
    build: Callable[[Path], list[str]], extra: dict[str, str], tmp_path: Path
) -> None:
    command = build(tmp_path)

    done = _run(command, tmp_path, extra=extra)

    assert (done.returncode, _called(tmp_path), done.stdout) == (na_boxie.ODMOWA, [], ""), done.stderr
    assert done.stderr.splitlines()[-1].startswith(_refusal(shlex.join([".venv/bin/python", *command[1:]]))), done.stderr


def test_pelny_pytest_z_workerami_dostaje_tez_polecenie_w_tle(tmp_path: Path) -> None:
    done = _run([*PYTEST, "-n", "2"], tmp_path)

    command = shlex.quote(shlex.join([".venv/bin/python", *PYTEST[1:], "-n", "2"]))
    assert done.stderr.rstrip().endswith(f" (pełny pytest w tle: boatbox job pytest {command}, potem boatbox wait pytest)"), done.stderr


@pytest.mark.parametrize(
    ("boatbox", "extra"),
    [
        pytest.param(True, {na_boxie.BOX: "1"}, id="na-boxie"),
        pytest.param(True, {na_boxie.TUTAJ: "1"}, id="boatbox-run-here"),
        pytest.param(True, {potomne.NARZEDZIE: "1"}, id="potomek-narzedzia-repo"),
        pytest.param(False, {}, id="bez-boatbox-w-path"),
    ],
)
@pytest.mark.parametrize(("command", "own"), [pytest.param(SZYBKO, 1, id="szybko"), pytest.param([*PYTEST, "-n", "2"], 0, id="pytest-z-workerami")])
def test_na_boxie_przy_run_here_u_potomka_narzedzia_repo_i_bez_boatbox_ciezkie_wejscie_biegnie(
    command: list[str], own: int, boatbox: bool, extra: dict[str, str], tmp_path: Path
) -> None:
    done = _run(command, tmp_path, boatbox=boatbox, extra=extra)

    assert (done.returncode, "ODMOWA" in done.stderr) == (own, False), done.stdout + done.stderr


@pytest.mark.parametrize("workers", [pytest.param([], id="bez-workerow"), pytest.param(["-n", "0"], id="n-0"), pytest.param(["-n", "1"], id="n-1")])
def test_pytest_bez_workerow_albo_z_jednym_biegnie_na_macu(workers: list[str], tmp_path: Path) -> None:
    done = _run([*PYTEST, *workers], tmp_path)

    assert (done.returncode, "ODMOWA" in done.stderr) == (0, False), done.stdout + done.stderr


@pytest.mark.parametrize(
    "command",
    [
        pytest.param([PYTHON, "tools/ci_lokalnie.py", "--tylko", "ruff", "--kazdy-commit", "nie/ma/takiej"], id="ci-lokalnie-bez-pytest"),
        pytest.param([PYTHON, "tools/ci_lokalnie.py", "--tylko", "mutations"], id="ci-lokalnie-odmowa-ciezkiego-ci"),
        pytest.param([PYTHON, "tools/mutacje.py", "--zasady"], id="mutacje-zasady"),
        pytest.param([PYTHON, "tools/mutacje.py", "--plik", "brak.json"], id="mutacje-bez-planu"),
        pytest.param([PYTHON, "tools/mutacje_zmiany.py"], id="mutacje-zmiany-odmowa-ciezkiego-ci"),
        pytest.param([PYTHON, "tools/benchmark_przebiegu.py", "comment", "--journal", "brak.jsonl"], id="benchmark-comment"),
        pytest.param([PYTHON, "tools/benchmark_przebiegu.py", "guard", "--journal", "brak.jsonl", "--budget-ms", "1"], id="benchmark-guard"),
    ],
)
def test_lekki_tryb_albo_szybka_odmowa_ciezkiego_narzedzia_biegnie_na_macu(command: list[str], tmp_path: Path) -> None:
    done = _run(command, tmp_path)

    assert (done.returncode != na_boxie.ODMOWA, "CIĘŻKIE NA MACU ODMOWA" in done.stderr) == (True, False), done.stdout + done.stderr


def test_polecenie_z_podkatalogu_wchodzi_do_niego_na_boxie(tmp_path: Path) -> None:
    done = _run([PYTHON, "szybko.py", "--baza", "nie/ma"], tmp_path, cwd=ROOT / "tools")

    assert _refusal("cd tools && ../.venv/bin/python szybko.py --baza nie/ma") in done.stderr, done.stderr


def test_narzedzie_spoza_katalogu_repo_dostaje_polecenie_z_korzenia_repo(tmp_path: Path) -> None:
    done = _run([PYTHON, str(ROOT / "tools" / "szybko.py"), "--baza", "nie/ma"], tmp_path, cwd=tmp_path)

    assert _refusal(".venv/bin/python tools/szybko.py --baza nie/ma") in done.stderr, done.stderr


WOLAJACY = """import os
from pathlib import Path
import sys

sys.path.insert(0, "tools/lib")
import potomne

done = potomne.run([sys.executable, "tools/mutacje_zmiany.py", "--baza", "HEAD"], cwd=Path.cwd(), env={**os.environ, "MAXIMISEART_NA_SCALONYCH_PR": "1"})
print(done.stdout, done.stderr)
sys.exit(done.returncode)
"""
"""Narzędzie repo jak ``tools/na_scalonych_pr.py``: uruchamia ciężkie narzędzie z własną zmienną, z której ono czyta decyzję."""


def test_ciezkie_narzedzie_uruchomione_przez_narzedzie_repo_biegnie_przy_nim_z_jego_srodowiskiem(tmp_path: Path) -> None:
    done = _run([PYTHON, "-c", WOLAJACY], tmp_path)

    assert (done.returncode, "MUTACJE ZMIANY OK" in done.stdout, "ODMOWA" in done.stdout) == (0, True, False), done.stdout + done.stderr


def test_ciezkie_wejscie_wolane_w_procesie_sesji_pytest_nie_odmawia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(potomne, "POTOMEK_NARZEDZIA", False)
    for name in (na_boxie.BOX, na_boxie.TUTAJ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", f"{_fake(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert (os.environ.get("PYTEST_VERSION") is not None, na_boxie.na_macu()) == (True, False)


IMPORT_ENV = dict(os.environ)
"""Środowisko z chwili importu modułu testów, jak ``WITHOUT_XDIST_WORKERS`` w ``tests/test_mutacje.py``."""


@pytest.mark.skipif("NA_BOXIE_PROBKA" not in os.environ, reason="próbka testu w sesji pytest, którą uruchamia test niżej")
def test_probka_test_uruchamia_narzedzie_ze_srodowiskiem_z_importu() -> None:
    done = subprocess.run(SZYBKO, cwd=ROOT, env=IMPORT_ENV, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

    assert "ODMOWA" not in done.stderr, done.stderr


def test_narzedzie_uruchomione_przez_test_w_sesji_pytest_biegnie_przy_sesji(tmp_path: Path) -> None:
    probe = [*PYTEST[:-2], "-n", "0", "tests/test_na_boxie.py", "-k", "probka"]

    done = _run(probe, tmp_path, extra={"NA_BOXIE_PROBKA": "1"})

    assert (done.returncode, "1 passed" in done.stdout) == (0, True), done.stdout + done.stderr


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="test_a" file="tests/test_x.py"><failure message="padł"/>
</testcase></testsuite></testsuites>
"""


@pytest.fixture
def mac(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Proces testu jak narzędzie na Macu: atrapa ``boatbox`` w ``PATH``, poza boxem i nie jako potomek narzędzia."""

    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    for name, value in (_env(tmp_path) | {"ATRAPA_JUNIT": str(junit)}).items():
        monkeypatch.setenv(name, value)
    for name in (na_boxie.BOX, na_boxie.TUTAJ, "PYTEST_VERSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(potomne, "POTOMEK_NARZEDZIA", False)
    return tmp_path


def test_test_scalenia_na_macu_biegnie_na_boxie_kopii_a_junit_wraca_z_boxa(mac: Path) -> None:
    copy = mac / "kopia"
    copy.mkdir()

    failed = testy_scalenia.failed_tests(copy, ["tests/test_x.py"], "test scalenia z main")

    run = (mac / "zapis" / "run").read_text(encoding="utf-8").splitlines()
    assert failed == ["tests/test_x.py::test_a"]
    assert run[:2] == [str(copy), "run"] and f"--junitxml={testy_scalenia.JUNIT}" in run[2] and run[2].endswith(" tests/test_x.py"), run
    assert run[2].startswith(f"{na_boxie.WORKERY_BOXA} && .venv/bin/python -m pytest "), run
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
