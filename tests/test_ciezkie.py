from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "ciezkie.py"
SETTINGS = ROOT / ".claude" / "settings.json"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="hook działa tylko tam, gdzie jest boatbox, a boatbox jest tylko na Macu Maksa"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ciezkie", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load()

SZYBKO = ".venv/bin/python tools/szybko.py"
NA_BOXIE_SZYBKO = "boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python tools/szybko.py'"

ODMOWY = [
    pytest.param(SZYBKO, NA_BOXIE_SZYBKO, id="szybko"),
    pytest.param("python3 tools/szybko.py", NA_BOXIE_SZYBKO, id="szybko-systemowym-pythonem"),
    pytest.param("python tools/szybko.py", NA_BOXIE_SZYBKO, id="szybko-pythonem-z-path"),
    pytest.param(".venv/bin/python -u tools/szybko.py", NA_BOXIE_SZYBKO, id="szybko-z-opcja-pythona"),
    pytest.param(
        f"{ROOT}/.venv/bin/python {ROOT}/tools/szybko.py", NA_BOXIE_SZYBKO, id="szybko-sciezka-bezwzgledna"
    ),
    pytest.param(
        f"{SZYBKO} --baza origin/feat/x 2>&1 | tail -20",
        "boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python tools/szybko.py --baza origin/feat/x' 2>&1",
        id="szybko-z-baza-w-potoku",
    ),
    pytest.param(
        f"PYTEST_XDIST_AUTO_NUM_WORKERS=4 {SZYBKO}",
        "boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=4 .venv/bin/python tools/szybko.py'",
        id="szybko-z-wlasna-liczba-workerow",
    ),
    pytest.param(f"cd {ROOT} && {SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-po-cd-do-tego-worktree"),
    pytest.param(f"git status; {SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-po-sredniku"),
    pytest.param(f"git status\n{SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-w-drugiej-linii"),
    pytest.param(f"ls  # nie ma tu cudzysłowu: don't\n{SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-po-linii-z-komentarzem"),
    pytest.param(f"echo \"don't\" # '\n{SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-po-komentarzu-z-niedomknietym-cudzyslowem"),
    pytest.param(f"if {SZYBKO}; then echo ok; fi", NA_BOXIE_SZYBKO, id="szybko-w-if"),
    pytest.param(f"(git status && {SZYBKO})", NA_BOXIE_SZYBKO, id="szybko-w-podpowloce"),
    pytest.param(f"timeout 900 {SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-za-timeout"),
    pytest.param(f"nice -n 5 {SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-za-nice"),
    pytest.param(f"time {SZYBKO}", NA_BOXIE_SZYBKO, id="szybko-za-time"),
    pytest.param(
        f"BOATBOX_SLOT=b2 {SZYBKO}",
        "BOATBOX_SLOT=b2 boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python tools/szybko.py'",
        id="szybko-ze-slotem-boatbox",
    ),
    pytest.param(
        f"{SZYBKO} > szybko.log 2>&1",
        "boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python tools/szybko.py' >szybko.log 2>&1",
        id="szybko-z-wyjsciem-do-pliku",
    ),
    pytest.param(
        ".venv/bin/python -m pytest -n auto",
        "boatbox job pytest '.venv/bin/python -m pytest -n auto' && boatbox wait pytest",
        id="pelny-pytest-n-auto",
    ),
    pytest.param(
        ".venv/bin/python -m pytest -q -n 8 > pytest.log 2>&1",
        "boatbox job pytest '.venv/bin/python -m pytest -q -n 8' && boatbox wait pytest >pytest.log 2>&1",
        id="pelny-pytest-n-8-z-wyjsciem-do-pliku",
    ),
    pytest.param(
        ".venv/bin/python -m pytest -q -n 4 tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest -q -n 4 tests/test_x.py'",
        id="pytest-n-4-na-pliku",
    ),
    pytest.param(
        "python3 -m pytest -n2 tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest -n2 tests/test_x.py'",
        id="pytest-n-przyklejone",
    ),
    pytest.param(
        "python -m pytest -n=2 tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest -n=2 tests/test_x.py'",
        id="pytest-n-ze-znakiem-rownosci",
    ),
    pytest.param(
        ".venv/bin/python -m pytest --numprocesses 3 tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest --numprocesses 3 tests/test_x.py'",
        id="pytest-numprocesses",
    ),
    pytest.param(
        ".venv/bin/python -m pytest --numprocesses=logical tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest --numprocesses=logical tests/test_x.py'",
        id="pytest-numprocesses-logical",
    ),
    pytest.param(
        ".venv/bin/python -m pytest -n 0 -n 4 tests/test_x.py",
        "boatbox run '.venv/bin/python -m pytest -n 0 -n 4 tests/test_x.py'",
        id="pytest-ostatnie-n-wygrywa",
    ),
    pytest.param(
        ".venv/bin/pytest -n 4 tests/test_x.py -k 'a and not b'",
        "boatbox run '.venv/bin/python -m pytest -n 4 tests/test_x.py -k '\"'\"'a and not b'\"'\"''",
        id="program-pytest-z-wyrazeniem-k",
    ),
    pytest.param(
        "env FOO=1 python3 -m pytest -n 2 tests/test_x.py",
        "boatbox run 'FOO=1 .venv/bin/python -m pytest -n 2 tests/test_x.py'",
        id="pytest-za-env-ze-zmienna",
    ),
    pytest.param(
        ".venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q -n 0 tests/test_x.py",
        "boatbox run '.venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q -n 0 tests/test_x.py'",
        id="mutacje-plik",
    ),
    pytest.param(
        ".venv/bin/python tools/mutacje.py --rownolegle --plik=mutacje.json",
        "boatbox run '.venv/bin/python tools/mutacje.py --rownolegle --plik=mutacje.json'",
        id="mutacje-plik-ze-znakiem-rownosci",
    ),
    pytest.param(
        "D=/srv/n; .venv/bin/python tools/mutacje.py --plik $D/m.json",
        'boatbox run ".venv/bin/python tools/mutacje.py --plik \\"$D/m.json\\""',
        id="mutacje-plik-ze-zmiennej",
    ),
    pytest.param(
        ".venv/bin/python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien",
        "boatbox run '.venv/bin/python tools/benchmark_przebiegu.py measure --scenario typowy-tydzien'",
        id="pomiar-benchmark",
    ),
    pytest.param(
        ".venv/bin/python tools/benchmark_przebiegu.py freeze --scenario s --commit abc",
        "boatbox run '.venv/bin/python tools/benchmark_przebiegu.py freeze --scenario s --commit abc'",
        id="zamrozenie-benchmark",
    ),
    pytest.param(
        ".venv/bin/python .agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py",
        "boatbox run '.venv/bin/python .agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py'",
        id="mutacje-skilla",
    ),
    pytest.param("$R/.venv/bin/python $R/tools/szybko.py", NA_BOXIE_SZYBKO, id="szybko-ze-sciezka-ze-zmiennej"),
]

PRZECHODZI = [
    pytest.param(NA_BOXIE_SZYBKO, id="boatbox-run"),
    pytest.param(f"boatbox run {SZYBKO}", id="boatbox-run-bez-cudzyslowu"),
    pytest.param(f"boatbox run --here '{SZYBKO}'", id="boatbox-run-here"),
    pytest.param(f"boatbox run --here {SZYBKO}", id="boatbox-run-here-bez-cudzyslowu"),
    pytest.param(f"boatbox auto '{SZYBKO}'", id="boatbox-auto"),
    pytest.param(f"BOATBOX_SLOT=b2 boatbox run '{SZYBKO}'", id="boatbox-ze-slotem"),
    pytest.param(f"~/.local/bin/boatbox run {SZYBKO}", id="boatbox-sciezka"),
    pytest.param(
        "boatbox job pytest '.venv/bin/python -m pytest -n auto' && boatbox wait pytest", id="boatbox-job-i-wait"
    ),
    pytest.param(
        "ls m-*.json | awk '{print \".venv/bin/python tools/mutacje.py --plik \" $1}' | boatbox fan", id="boatbox-fan"
    ),
    pytest.param(f"{SZYBKO} --help", id="szybko-help"),
    pytest.param(f"{SZYBKO} -h", id="szybko-h"),
    pytest.param(".venv/bin/python tools/mutacje.py --help", id="mutacje-help"),
    pytest.param(".venv/bin/python tools/mutacje.py --plik m.json --help", id="mutacje-plik-help"),
    pytest.param(".venv/bin/python tools/benchmark_przebiegu.py --help", id="benchmark-help"),
    pytest.param(
        ".venv/bin/python .agents/skills/verify-kopia-wzorca/scripts/check_copy_mutations.py --help",
        id="mutacje-skilla-help",
    ),
    pytest.param(".venv/bin/python -m pytest -n 4 --help", id="pytest-help"),
    pytest.param(".venv/bin/python -m pytest -q tests/test_x.py", id="pytest-pliku-bez-n"),
    pytest.param(".venv/bin/python -m pytest -q -n 0 tests/test_x.py", id="pytest-n-0"),
    pytest.param(".venv/bin/python -m pytest -q -n 1 tests/test_x.py", id="pytest-n-1"),
    pytest.param(".venv/bin/python -m pytest -q -n1 tests/test_x.py", id="pytest-n-1-przyklejone"),
    pytest.param(".venv/bin/python -m pytest -q -n 4 -n 0 tests/test_x.py", id="pytest-ostatnie-n-0-wygrywa"),
    pytest.param(".venv/bin/pytest -q tests/test_x.py", id="program-pytest-bez-n"),
    pytest.param(
        ".venv/bin/python tools/mutacje.py --zmiana src/x.py 'a' 'b' -- -m pytest -q -n 0 tests/test_x.py",
        id="mutacje-zmiana",
    ),
    pytest.param(".venv/bin/python tools/mutacje.py --zasady", id="mutacje-zasady"),
    pytest.param(".venv/bin/python tools/benchmark_przebiegu.py comment --before a --after b", id="benchmark-comment"),
    pytest.param(".venv/bin/python tools/benchmark_przebiegu.py guard --budget-ms 10", id="benchmark-guard"),
    pytest.param(".venv/bin/python tools/plan_ci.py plan --baza origin/main", id="inne-narzedzie"),
    pytest.param(".venv/bin/python tests/szybko.py", id="szybko-spoza-tools"),
    pytest.param("grep -n python tools/szybko.py", id="grep-po-nazwie"),
    pytest.param("echo python tools/szybko.py", id="echo-po-nazwie"),
    pytest.param("cat tools/szybko.py tools/mutacje.py", id="cat-narzedzia"),
    pytest.param(f'git commit -m "uruchom {SZYBKO} przed pushem"', id="tekst-commitu"),
    pytest.param(f"# {SZYBKO}", id="komentarz"),
    pytest.param(f"git status  # potem {SZYBKO}", id="komentarz-na-koncu-linii"),
    pytest.param(".venv/bin/ruff check tools/szybko.py && .venv/bin/mypy tools/szybko.py", id="ruff-i-mypy"),
    pytest.param("python3 -c 'import sys; print(sys.version)'", id="python-c"),
    pytest.param("echo 'niedomkniety", id="niedomkniety-cudzyslow"),
    pytest.param("", id="puste"),
]

ZNANE_LUKI = [
    pytest.param(f"cat <<'EOF' > m.json\n[]\nEOF\n{SZYBKO}", id="heredoc-w-poleceniu"),
    pytest.param(f".venv/bin/python - <<'EOF'\nimport os; os.system('{SZYBKO}')\nEOF", id="heredoc-do-pythona"),
    pytest.param(f"eval '{SZYBKO}'", id="eval"),
    pytest.param(f"bash -c '{SZYBKO}'", id="bash-c"),
    pytest.param(f'zsh -lc "{SZYBKO}"', id="zsh-c"),
    pytest.param("PY=.venv/bin/python; $PY tools/szybko.py", id="program-ze-zmiennej"),
    pytest.param("sh szybko.sh", id="skrypt-z-pliku"),
    pytest.param("uv run python tools/szybko.py", id="uv-run"),
    pytest.param(f"echo x | xargs {SZYBKO}", id="xargs"),
    pytest.param(f'echo "$({SZYBKO})"', id="podstawienie-w-cudzyslowie"),
    pytest.param(f"echo `{SZYBKO}`", id="backtick"),
    pytest.param('.venv/bin/python -m pytest -q -n "8">pytest.log', id="przekierowanie-przyklejone-do-liczby"),
    pytest.param(f"git status&&{SZYBKO}", id="operator-bez-spacji"),
    pytest.param("PYTEST_ADDOPTS='-n 8' .venv/bin/python -m pytest", id="workery-z-pytest-addopts"),
    pytest.param(".venv/bin/python -m pytest", id="pelny-pytest-bez-n-na-jednym-rdzeniu"),
]


@pytest.mark.parametrize(("command", "box"), ODMOWY)
def test_ciezkie_polecenie_bez_boatbox_dostaje_odmowe_z_gotowym_poleceniem_boxa(command: str, box: str) -> None:
    refusal = hook.judge(command, str(ROOT))

    assert refusal is not None
    assert refusal.reason.endswith(f" Uruchom: {box}")
    assert "\n" not in refusal.reason


@pytest.mark.parametrize("command", PRZECHODZI)
def test_polecenie_lekkie_albo_z_boatbox_przechodzi(command: str) -> None:
    assert hook.judge(command, str(ROOT)) is None


@pytest.mark.parametrize("command", ZNANE_LUKI)
def test_znane_luki_hooka_ciezkich_polecen_przechodza(command: str) -> None:
    assert hook.judge(command, str(ROOT)) is None, "hook łapie już tę postać: usuń ją ze ZNANE_LUKI i dopisz do ODMOWY"


def _repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


def test_plik_mutacji_spoza_worktree_odmowa_kopiuje_do_jego_korzenia(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "wt")
    notes = tmp_path / "notatki"

    refusal = hook.judge(f".venv/bin/python tools/mutacje.py --plik {notes}/m.json -- -m pytest -q", str(repo))

    assert refusal is not None
    assert refusal.reason.endswith(
        f" Uruchom: cp {notes}/m.json m.json && boatbox run '.venv/bin/python tools/mutacje.py --plik m.json -- -m pytest -q'"
    )


def test_plik_mutacji_w_podkatalogu_worktree_odmowa_podaje_sciezke_od_korzenia(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "wt")

    refusal = hook.judge(".venv/bin/python ../tools/mutacje.py --plik m.json", str(repo / "tests"))

    assert refusal is not None
    assert refusal.reason.endswith(" Uruchom: boatbox run '.venv/bin/python tools/mutacje.py --plik tests/m.json'")


def test_cd_do_innego_worktree_przechodzi_do_odmowy(tmp_path: Path) -> None:
    session = _repo(tmp_path / "sesja")
    other = _repo(tmp_path / "recenzja")

    refusal = hook.judge(f"cd {other} && {SZYBKO} > ../szybko.log", str(session))

    assert refusal is not None
    assert refusal.reason.endswith(f" Uruchom: cd {other} && {NA_BOXIE_SZYBKO} >../szybko.log")


def test_narzedzie_innego_worktree_sciezka_bezwzgledna_dostaje_cd_do_niego(tmp_path: Path) -> None:
    session = _repo(tmp_path / "sesja")
    other = _repo(tmp_path / "recenzja")

    refusal = hook.judge(f"{other}/.venv/bin/python {other}/tools/szybko.py > szybko.log", str(session))

    assert refusal is not None
    assert refusal.reason.endswith(f" Uruchom: cd {other} && {NA_BOXIE_SZYBKO} >{session}/szybko.log")


@pytest.mark.parametrize(
    ("command", "said"),
    [
        pytest.param(".venv/bin/python -m pytest -n auto", "boatbox wait z kodem 3", id="pelny-pytest"),
        pytest.param(".venv/bin/python tools/mutacje.py --plik m.json", "boatbox fan", id="mutacje"),
        pytest.param(".venv/bin/python tools/benchmark_przebiegu.py measure", ".benchmark/", id="pomiar"),
        pytest.param("D=x; .venv/bin/python tools/mutacje.py --plik $D/m.json", "skopiuj najpierw", id="plik-ze-zmiennej"),
        pytest.param("D=x; .venv/bin/python tools/mutacje.py --plik $D/m.json", "definicje wklej", id="zmienne"),
    ],
)
def test_odmowa_mowi_czego_gotowe_polecenie_nie_zrobi_samo(command: str, said: str) -> None:
    refusal = hook.judge(command, str(ROOT))

    assert refusal is not None
    assert said in refusal.reason.split(" Uruchom: ")[0]


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


ARGV = '#!/bin/sh\nfor a in "$@"; do printf "<%s>" "$a"; done >> "$ARGV_LOG"; echo >> "$ARGV_LOG"\n'
BOATBOX = (
    "#!/bin/bash\n"
    'd=$PWD; while [ ! -e "$d/.git" ]; do d=$(dirname "$d"); done; cd "$d"\n'
    "case $1 in run) shift ;; job) shift 2 ;; wait) exit 0 ;; esac\n"
    'exec bash -c "$*"\n'
)


@pytest.mark.parametrize(
    ("before", "command"),
    [
        pytest.param("", f"{SZYBKO} --baza 'origin/a b'", id="argument-ze-spacja"),
        pytest.param("", '.venv/bin/python -m pytest -n 4 tests/test_x.py -k "it\'s"', id="argument-z-apostrofem"),
        pytest.param("", "python3 -m pytest -n 4 tests/test_x.py -k 'a\"b'", id="cudzyslow-w-apostrofach"),
        pytest.param(
            "D=sub; T=tests/test_x.py; ",
            '.venv/bin/python tools/mutacje.py --plik $D/m.json -- -m pytest "$T"',
            id="zmienne",
        ),
        pytest.param("", ".venv/bin/python -m pytest -n auto -k 'a\\b'", id="ukosnik"),
    ],
)
def test_gotowe_polecenie_daje_na_boxie_te_same_argumenty_co_polecenie_na_macu(
    tmp_path: Path, before: str, command: str
) -> None:
    repo = _repo(tmp_path / "wt")
    bin_dir = tmp_path / "bin"
    for program in (repo / ".venv" / "bin" / "python", bin_dir / "python3", bin_dir / "python"):
        _executable(program, ARGV)
    _executable(bin_dir / "boatbox", BOATBOX)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "ARGV_LOG": str(tmp_path / "argv")}
    refusal = hook.judge(before + command, str(repo))
    assert refusal is not None
    box = refusal.reason.split(" Uruchom: ", 1)[1]

    for line in (before + command, before + box):
        subprocess.run(["bash", "-c", line], cwd=repo, env=env, check=True)

    on_mac, on_box = (tmp_path / "argv").read_text(encoding="utf-8").splitlines()
    assert on_box == on_mac


def test_dolar_w_apostrofach_gotowe_polecenie_oddaje_do_rozwiniecia_na_macu() -> None:
    refusal = hook.judge(".venv/bin/python -m pytest -n 4 tests/test_x.py -k '$x'", str(ROOT))

    assert refusal is not None
    assert refusal.reason.endswith(' Uruchom: boatbox run ".venv/bin/python -m pytest -n 4 tests/test_x.py -k \\"$x\\""')


def _on_mac() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "BOATBOX_BOX"}


def _boatbox_in_path(tmp_path: Path) -> dict[str, str]:
    _executable(tmp_path / "bin" / "boatbox", "#!/bin/sh\n")
    return {**_on_mac(), "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"}


def _hook(stdin: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, env=env, capture_output=True, text=True, check=False)


def _bash(command: str, cwd: Path = ROOT) -> str:
    return json.dumps({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}})


def test_hook_odmawia_kodem_2_jedna_linia_na_stderr(tmp_path: Path) -> None:
    hooked = _hook(_bash(SZYBKO), _boatbox_in_path(tmp_path))

    assert (hooked.returncode, hooked.stdout) == (2, "")
    assert hooked.stderr.endswith(f" Uruchom: {NA_BOXIE_SZYBKO}\n")
    assert hooked.stderr.count("\n") == 1


def test_hook_bez_boatbox_w_path_przepuszcza(tmp_path: Path) -> None:
    hooked = _hook(_bash(SZYBKO), {**_on_mac(), "PATH": str(tmp_path)})

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def test_hook_na_boxie_przepuszcza(tmp_path: Path) -> None:
    hooked = _hook(_bash(SZYBKO), {**_boatbox_in_path(tmp_path), "BOATBOX_BOX": "1"})

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "stdin",
    ["", "[]", '{"tool_input": {"command": 5}}', '{"tool_name": "Bash"}', '{"cwd": 5, "tool_input": {"command": "ls"}}'],
    ids=["pusto", "lista", "liczba", "bez-polecenia", "katalog-nie-napisem"],
)
def test_nieczytelne_wejscie_hooka_przechodzi(tmp_path: Path, stdin: str) -> None:
    hooked = _hook(stdin, _boatbox_in_path(tmp_path))

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def _configured(project: Path, env: dict[str, str]) -> list[subprocess.CompletedProcess[str]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    hooks = [
        hook
        for entry in entries
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
        if "ciezkie.py" in hook["command"]
    ]
    assert [hook["timeout"] for hook in hooks] == [10]
    return [
        subprocess.run(
            hook["command"],
            shell=True,
            input=_bash(SZYBKO),
            env={**env, "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
        )
        for hook in hooks
    ]


def test_ustawienia_projektu_wpinaja_hook_ciezkich_polecen_dla_basha(tmp_path: Path) -> None:
    hooked = _configured(ROOT, _boatbox_in_path(tmp_path))

    assert [(run.returncode, NA_BOXIE_SZYBKO in run.stderr) for run in hooked] == [(2, True)]


def test_checkout_bez_skryptu_hooka_ciezkich_polecen_nie_blokuje_basha(tmp_path: Path) -> None:
    hooked = _configured(tmp_path, _boatbox_in_path(tmp_path))

    assert [(run.returncode, run.stderr) for run in hooked] == [(0, "")]
