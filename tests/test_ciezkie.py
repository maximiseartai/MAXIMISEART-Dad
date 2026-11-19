"""Hook ``tools/hooks/ciezkie.py``: ciężkie polecenie z tabeli skilla ``boat`` biegnie na Macu Maksa tylko przez ``boatbox``.

Polecenia pochodzą z poleceń Basha agentów z 16–19.11.2026, skrócone o ``cd`` do worktree i ścieżki notatek, a każdy
wiersz tabel z docstringu hooka ma tu swój przypadek. Protokół (JSON na stdin, odmowa kodem 2 z przyczyną na stderr)
i warunek ``boatbox`` w ``PATH`` sprawdzają testy, które uruchamiają hook tak jak Claude Code.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import ModuleType

import pytest

from tests.fixtures.znane_luki import assert_znane_luki

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "ciezkie.py"
SETTINGS = ROOT / ".claude" / "settings.json"

SZYBKO = "boatbox auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8 "


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ciezkie", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load()

REFUSED = [
    (".venv/bin/python tools/szybko.py 2>&1 | tail -15", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    (
        "cd wt && .venv/bin/python tools/szybko.py --baza feat/x > szybko.txt 2>&1; echo exit=$?",
        SZYBKO + "'.venv/bin/python tools/szybko.py --baza feat/x'",
    ),
    ("python3 tools/szybko.py", SZYBKO + "'python3 tools/szybko.py'"),
    (".venv/bin/python -X importtime tools/szybko.py", SZYBKO + "'.venv/bin/python -X importtime tools/szybko.py'"),
    ("cd wt # wejście do worktree\n.venv/bin/python tools/szybko.py", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    ("nohup .venv/bin/python tools/szybko.py &", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    ("git add -A\n.venv/bin/python tools/szybko.py", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    ('out=$(.venv/bin/python tools/szybko.py 2>&1); echo "$out" | tail', SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    ("bash -lc '.venv/bin/python tools/szybko.py'", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    ("bash -euo pipefail -c 'cd wt && .venv/bin/python tools/szybko.py'", SZYBKO + "'.venv/bin/python tools/szybko.py'"),
    (
        "timeout 900 .venv/bin/python tools/mutacje.py --plik mutacje-b2.json > mutacje.log 2>&1; echo exit=$?",
        "boatbox auto 'timeout 900 .venv/bin/python tools/mutacje.py --plik mutacje-b2.json'",
    ),
    (
        ".venv/bin/python tools/mutacje.py --rownolegle \\\n  --plik m.json",
        "boatbox auto '.venv/bin/python tools/mutacje.py --rownolegle --plik m.json'",
    ),
    (
        ".venv/bin/python tools/mutacje.py --rownolegle --plik ~/n/m.json -- -m pytest -q -n 0 tests/test_x.py",
        "boatbox auto '.venv/bin/python tools/mutacje.py --rownolegle --plik ~/n/m.json -- -m pytest -q -n 0 tests/test_x.py'",
    ),
    (
        ".venv/bin/python tools/mutacje.py --rownolegle --plik=m.json -- -m pytest -q -n 0 tests/test_x.py -k y",
        "boatbox auto '.venv/bin/python tools/mutacje.py --rownolegle --plik=m.json -- -m pytest -q -n 0 tests/test_x.py -k y'",
    ),
    (
        "G=~/n; .venv/bin/python tools/mutacje.py --plik $G/m.json -- -m pytest -q -n 0 tests/test_x.py -k \"a or b\"",
        "boatbox auto \".venv/bin/python tools/mutacje.py --plik $G/m.json -- -m pytest -q -n 0 tests/test_x.py -k 'a or b'\"",
    ),
    (
        "cat > opis.txt <<'EOF'\nto nie polecenie, it's opis\nEOF\n.venv/bin/python tools/mutacje.py --plik m.json",
        "boatbox auto '.venv/bin/python tools/mutacje.py --plik m.json'",
    ),
    (
        ".venv/bin/python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --machine mac-m4max",
        "boatbox run --here '.venv/bin/python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --machine mac-m4max'",
    ),
    (
        ".venv/bin/python tools/benchmark_przebiegu.py freeze --scenario typowy-tydzien --commit abc",
        "boatbox run --here '.venv/bin/python tools/benchmark_przebiegu.py freeze --scenario typowy-tydzien --commit abc'",
    ),
    (
        ".venv/bin/python -m pytest -n auto -q -p no:cacheprovider",
        "boatbox job pytest '.venv/bin/python -m pytest -n auto -q -p no:cacheprovider'",
    ),
    ("pytest -n auto", "boatbox job pytest 'pytest -n auto'"),
    (
        ".venv/bin/python -m pytest -q -n 8 > pytest.log 2>&1",
        "boatbox job pytest '.venv/bin/python -m pytest -q -n 8'",
    ),
    (
        ".venv/bin/python -m pytest -q --numprocesses 4 >> pytest.log",
        "boatbox job pytest '.venv/bin/python -m pytest -q --numprocesses 4'",
    ),
    (".venv/bin/pytest -q -n 4 tests/ -k szybko", "boatbox job pytest '.venv/bin/pytest -q -n 4 tests/ -k szybko'"),
    (".venv/bin/pytest -nauto -x", "boatbox job pytest '.venv/bin/pytest -nauto -x'"),
    (
        "PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python -m pytest --numprocesses=auto -x",
        "boatbox job pytest 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python -m pytest --numprocesses=auto -x'",
    ),
    (
        "for i in 1 2; do .venv/bin/python -m pytest -q --numprocesses 4; done",
        "boatbox job pytest '.venv/bin/python -m pytest -q --numprocesses 4'",
    ),
]

PASSING = [
    SZYBKO + "'.venv/bin/python tools/szybko.py' 2>&1 | tail -25",
    "boatbox auto '.venv/bin/python tools/mutacje.py --rownolegle --plik m.json -- -m pytest -q -n 0 tests/test_x.py'",
    "boatbox job pytest '.venv/bin/python -m pytest -n auto -q -p no:cacheprovider' 2>&1 | tail -5",
    "boatbox run --here '.venv/bin/python tools/benchmark_przebiegu.py measure --scenario s'",
    "awk '{print \".venv/bin/python tools/mutacje.py --rownolegle --plik \" $0}' czesci.txt | boatbox fan",
    "pytest tests/test_x.py",
    ".venv/bin/python -m pytest -q -p no:cacheprovider -n 8 tests/test_centrum_rozliczen.py -k 'bez_odczytu or znane_luki'",
    ".venv/bin/python -m pytest -q -n 4 tests/test_szybko.py tests/test_repo.py::test_x",
    'T="tests/test_a.py tests/test_b.py"; .venv/bin/python -m pytest -q -n 4 $T',
    ".venv/bin/python -m pytest -q -x -n 4 @testy-sprzed-zmiany.txt",
    ".venv/bin/python -m pytest -q -n0 -p no:cacheprovider tests -k test_x",
    ".venv/bin/python -m pytest -q tests/ -k skill",
    "PYTHONPATH=$R $R/.venv/bin/python -m pytest -p no:cacheprovider -p no:xdist -rA -q --basetemp=tmp",
    ".venv/bin/python -m pytest -n 4 -pno:xdist",
    ".venv/bin/python -m pytest --collect-only -q tests/",
    ".venv/bin/python -m pytest --version",
    ".venv/bin/python tools/mutacje.py --zmiana tools/x.py 'a' 'b' -- -m pytest -q -n 0 tests/test_x.py -k y",
    ".venv/bin/python tools/benchmark_przebiegu.py comment --before abc",
    ".venv/bin/python tools/benchmark_przebiegu.py guard --budget-ms 900",
    ".venv/bin/python tools/szybko.py --help | head -40",
    "pytest -n 4 -h",
    "sed -n 78,90p tools/szybko.py; git log --oneline -- tools/szybko.py",
    "git add tools/szybko.py tools/mutacje.py && git commit -qm 'szybko: --plik'",
    "rg -n pytest pyproject.toml; pip install pytest; grep pytest -n pyproject.toml",
    "grep -n python tools/szybko.py",
    ".venv/bin/python - <<'EOF'\nimport subprocess\nsubprocess.run(['.venv/bin/python', 'tools/szybko.py'])\nEOF",
    ".venv/bin/python -c 'import szybko'",
    ".venv/bin/python -m ruff check tools/szybko.py && .venv/bin/python -m mypy",
    "gh pr view 1 --json title",
    'echo "niedomknięte',
]


ZNANE_LUKI = {
    "interpreter ze zmiennej: $PY tools/szybko.py": "PY=.venv/bin/python; $PY tools/szybko.py",
    "opcje pytest ze zmiennej: pytest $ARGS": 'ARGS="-n auto"; .venv/bin/python -m pytest $ARGS',
    "pytest bez ścieżki za innym programem: timeout 900 pytest": "timeout 900 pytest -n auto",
    "Python bez ścieżki za innym programem: timeout 900 python3": "timeout 900 python3 tools/szybko.py",
    "podstawienie w cudzysłowie podwójnym: \"$(…)\"": 'echo "$(.venv/bin/python tools/szybko.py)"',
    "podstawienie w backtickach": "x=`.venv/bin/python tools/szybko.py`",
    "eval": "eval '.venv/bin/python tools/szybko.py'",
    "xargs: skrypt ze stdin": "echo tools/szybko.py | xargs .venv/bin/python",
    "skrypt powłoki z pliku": "bash sprawdz.sh",
    "plik testów tylko jako wartość opcji": ".venv/bin/python -m pytest -n auto --ignore tests/test_x.py",
    "połączone opcje Pythona: -um pytest": ".venv/bin/python -um pytest -n auto",
    "komentarz z niedomkniętym cudzysłowem przed poleceniem": "# don't\n.venv/bin/python tools/szybko.py",
}


def test_znane_luki_hooka_ciezkich_polecen_przechodza() -> None:
    zgloszenia: dict[str, list[str]] = {}
    for opis, command in ZNANE_LUKI.items():
        refusal = hook.judge(command)
        zgloszenia[opis] = [] if refusal is None else [refusal.reason]

    assert_znane_luki(zgloszenia, "tests/test_ciezkie.py (ZNANE_LUKI)")


@pytest.mark.parametrize(("command", "ready"), REFUSED, ids=[command for command, _ in REFUSED])
def test_ciezkie_polecenie_bez_boatbox_dostaje_odmowe_z_gotowym_poleceniem(command: str, ready: str) -> None:
    refusal = hook.judge(command)

    assert refusal is not None
    assert f"Uruchom je tak: {ready}\n" in refusal.reason


@pytest.mark.parametrize("ready", [ready for _, ready in REFUSED])
def test_gotowe_polecenie_z_odmowy_przechodzi(ready: str) -> None:
    assert hook.judge(ready) is None


@pytest.mark.parametrize("command", PASSING)
def test_polecenie_w_boatbox_i_lekkie_polecenie_przechodza(command: str) -> None:
    assert hook.judge(command) is None


HEAVY = [shlex.split(ready)[-1] for _, ready in REFUSED]
BOATBOX = ["boatbox auto", "boatbox run", "boatbox run --here", "boatbox job nazwa", "timeout 900 boatbox auto"]


@pytest.mark.parametrize("boatbox", BOATBOX)
@pytest.mark.parametrize("heavy", HEAVY)
def test_ciezkie_polecenie_za_boatbox_bez_cudzyslowu_przechodzi(boatbox: str, heavy: str) -> None:
    assert hook.judge(f"{boatbox} {heavy}") is None


@pytest.mark.parametrize("redirect", [" > f", " 2>&1", " &> f", " >> f 2>&1", " 2>blad.log", " </dev/null"])
@pytest.mark.parametrize(("heavy", "ready"), [(heavy, ready) for heavy, (_, ready) in zip(HEAVY, REFUSED, strict=True)])
def test_przekierowanie_za_ciezkim_poleceniem_nie_zmienia_odmowy(heavy: str, ready: str, redirect: str) -> None:
    refusal = hook.judge(heavy + redirect)

    assert refusal is not None
    assert f"Uruchom je tak: {ready}\n" in refusal.reason


def _fake_boatbox(folder: Path) -> Path:
    folder.mkdir()
    for name in ("boatbox", "boatbox.cmd"):
        program = folder / name
        program.write_text("exit 0\n", encoding="utf-8")
        program.chmod(0o755)
    return folder


def _hook(stdin: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env={**os.environ, "PATH": str(path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _bash(command: str) -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}})


def test_hook_z_boatbox_w_path_odmawia_kodem_2_z_poleceniem_na_stderr(tmp_path: Path) -> None:
    command, ready = REFUSED[0]

    hooked = _hook(_bash(command), _fake_boatbox(tmp_path / "bin"))

    assert (hooked.returncode, hooked.stdout) == (2, ""), hooked.stderr
    assert ready in hooked.stderr


@pytest.mark.parametrize(
    ("stdin", "with_boatbox"),
    [
        pytest.param(_bash(REFUSED[0][0]), False, id="bez-boatbox-w-path"),
        pytest.param(_bash(PASSING[0]), True, id="polecenie-w-boatbox"),
        pytest.param("nie json", True, id="wejscie-nieczytelne"),
        pytest.param(json.dumps({"tool_input": {"command": 7}}), True, id="polecenie-nie-tekst"),
    ],
)
def test_hook_przepuszcza_bez_slowa(stdin: str, with_boatbox: bool, tmp_path: Path) -> None:
    path = _fake_boatbox(tmp_path / "bin") if with_boatbox else tmp_path

    hooked = _hook(stdin, path)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def _configured() -> list[dict[str, object]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    return [
        hook
        for entry in entries
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
        if str(hook["command"]).endswith('/tools/hooks/ciezkie.py"')
    ]


def test_limit_hooka_w_ustawieniach_opoznia_polecenie_najwyzej_o_10_s() -> None:
    (configured,) = _configured()

    assert 0 < float(str(configured["timeout"])) <= 10


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
@pytest.mark.parametrize(("project", "code"), [pytest.param(ROOT, 2, id="checkout-z-hookiem"), pytest.param(None, 0, id="checkout-bez-skryptu")])
def test_ustawienia_projektu_wpinaja_hook_dla_basha(project: Path | None, code: int, tmp_path: Path) -> None:
    (configured,) = _configured()

    hooked = subprocess.run(
        str(configured["command"]),
        shell=True,
        input=_bash(REFUSED[0][0]),
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(project or tmp_path),
            "PATH": f"{_fake_boatbox(tmp_path / 'bin')}{os.pathsep}/usr/bin{os.pathsep}/bin",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert hooked.returncode == code, hooked.stderr
