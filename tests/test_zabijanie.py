from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "zabijanie.py"
SETTINGS = ROOT / ".claude" / "settings.json"
WORKTREE = "/srv/worktrees/t3-moj"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("zabijanie", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load()

PUSTE_PODSTAWIENIE = 'pkill -f "pytest -n auto" -P $(pgrep -f "tee .*szybko1.log" | head -1)'
BEZ_SCIEZKI = 'pkill -f "tools/szybko.py"'

ODMOWY = [
    pytest.param(
        PUSTE_PODSTAWIENIE, "z podstawieniem $(…)", id="pusty-pgrep-w-pkill-z-incydentu"
    ),
    pytest.param(
        f'pkill -f "{WORKTREE}/.venv/bin/python" -P $(pgrep -f "{WORKTREE}/tee")',
        "z podstawieniem $(…)",
        id="pusty-pgrep-w-pkill-ze-sciezka",
    ),
    pytest.param(
        f'pkill -f "$(cat {WORKTREE}/wzorzec)"',
        "z podstawieniem $(…)",
        id="podstawienie-w-cudzyslowie",
    ),
    pytest.param(
        f"pkill -f `cat {WORKTREE}/wzorzec`",
        "z podstawieniem $(…)",
        id="podstawienie-backtick",
    ),
    pytest.param(
        BEZ_SCIEZKI,
        "bez absolutnej ścieżki tego worktree",
        id="wzorzec-bez-sciezki-z-incydentu",
    ),
    pytest.param(
        "killall python3", "wzorzec killall bez absolutnej ścieżki", id="killall"
    ),
    pytest.param(
        "killall -9 node",
        "wzorzec killall bez absolutnej ścieżki",
        id="killall-z-sygnalem",
    ),
    pytest.param(
        "killall -c python", "wzorzec killall bez absolutnej ścieżki", id="killall-c"
    ),
    pytest.param(
        "killall -u agent",
        "bez wzorca albo z więcej niż jednym",
        id="killall-bez-wzorca",
    ),
    pytest.param(
        f'pkill -f "{WORKTREE}-inny/x"',
        "bez absolutnej ścieżki",
        id="inny-worktree-z-tym-samym-poczatkiem",
    ),
    pytest.param(
        f'pkill -f "[{WORKTREE}]"',
        "bez absolutnej ścieżki",
        id="sciezka-w-klasie-znakow",
    ),
    pytest.param(
        f'pkill -f "{WORKTREE}/x" pytest',
        "z więcej niż jednym wzorcem",
        id="dwa-wzorce",
    ),
    pytest.param("pkill -u agent", "bez wzorca", id="bez-wzorca"),
    pytest.param("pkill -F plik.pid", "bez wzorca", id="plik-pid-bez-wzorca"),
    pytest.param(f'pkill -f "{WORKTREE}/x|pytest"', "z |, (, )", id="alternatywa"),
    pytest.param(f'pkill -f "({WORKTREE})?pytest"', "z |, (, )", id="grupa-opcjonalna"),
    pytest.param(
        f'W={WORKTREE}; pkill -f "$W/x"', "ze zmienną ($…)", id="zmienna-we-wzorcu"
    ),
    pytest.param(
        f"pkill --bez-takiej-opcji -f {WORKTREE}/x",
        "z opcją --bez-takiej-opcji",
        id="nieznana-opcja-dluga",
    ),
    pytest.param(f"pkill -k -f {WORKTREE}/x", "z opcją -k", id="nieznana-opcja-krotka"),
    pytest.param(
        "kill $(pgrep -f szybko.py)",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="kill-pgrep",
    ),
    pytest.param(
        "pgrep -f szybko.py | xargs kill",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="xargs-kill",
    ),
    pytest.param(
        "for p in $(pgrep -f szybko.py); do kill $p; done",
        "wzorzec pgrep",
        id="petla-for-kill",
    ),
    pytest.param(
        "pids=$(pgrep -f szybko.py); kill $pids", "wzorzec pgrep", id="pidy-w-zmiennej"
    ),
    pytest.param("sudo pkill -f x", "bez absolutnej ścieżki", id="sudo"),
    pytest.param("timeout 5 pkill -f x", "bez absolutnej ścieżki", id="timeout"),
    pytest.param(
        "echo x | xargs -n 1 pkill -f", "bez wzorca", id="xargs-pkill-wzorzec-z-wejscia"
    ),
    pytest.param(
        "/usr/bin/pkill -f x", "bez absolutnej ścieżki", id="pkill-sciezka-programu"
    ),
    pytest.param('"pkill" -f x', "bez absolutnej ścieżki", id="pkill-w-cudzyslowie"),
    pytest.param("bash -lc 'pkill -f x'", "bez absolutnej ścieżki", id="bash-c"),
    pytest.param("zsh -c 'sleep 1; pkill -f x'", "bez absolutnej ścieżki", id="zsh-c"),
    pytest.param('eval "pkill -f x"', "bez absolutnej ścieżki", id="eval"),
    pytest.param("trap 'pkill -f x' EXIT", "bez absolutnej ścieżki", id="trap"),
    pytest.param(
        f"pkill -v -f '{WORKTREE}/x'",
        "z -v zabija każdy proces, który do wzorca nie pasuje",
        id="pkill-odwrocony",
    ),
    pytest.param(
        f"pkill -fv '{WORKTREE}/x'",
        "z -v zabija każdy proces",
        id="pkill-odwrocony-w-grupie-flag",
    ),
    pytest.param(
        f"pkill --inverse -f '{WORKTREE}/x'",
        "z --inverse zabija każdy proces",
        id="pkill-odwrocony-dluga-opcja",
    ),
    pytest.param(
        f"pgrep -v -f '{WORKTREE}/x' | xargs kill",
        "z -v zabija każdy proces",
        id="pgrep-odwrocony-do-kill",
    ),
    pytest.param(
        'trap "kill $pids" EXIT; pgrep -x yes | wc -l',
        "wzorzec pgrep w jednym poleceniu z kill",
        id="trap-kill-zmiennej-obok-pgrep",
    ),
    pytest.param(
        "pgrep -f szybko.py | xargs -I{} kill {}",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="pgrep-do-xargs-I-kill",
    ),
    pytest.param(
        "kill 123; pgrep -fl run_centrum.py | grep t3-moj",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="kill-pidu-i-przeglad-pgrep",
    ),
    pytest.param(
        "kill %1; pgrep -fl szybko",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="kill-zadania-i-przeglad-pgrep",
    ),
    pytest.param(
        "pkill -f '/srv/worktrees/t3-moj/x'; pgrep -fl szybko",
        "wzorzec pgrep w jednym poleceniu z kill",
        id="pgrep-obok-wlasnego-pkill",
    ),
    pytest.param("kill -9 -1", "kill z ujemnym PID-em", id="kill-wszystkich"),
    pytest.param("kill -- -4321", "kill z ujemnym PID-em", id="kill-grupy"),
    pytest.param("kill -s TERM -1", "kill z ujemnym PID-em", id="kill-wszystkich-z-s"),
    pytest.param("echo $(pkill -f x)", "bez absolutnej ścieżki", id="w-podstawieniu"),
    pytest.param("true && pkill -f x || true", "bez absolutnej ścieżki", id="lista"),
    pytest.param("(pkill -f x)", "bez absolutnej ścieżki", id="podpowloka"),
    pytest.param("{ pkill -f x; }", "bez absolutnej ścieżki", id="grupa"),
    pytest.param(
        "if true; then pkill -f x; fi", "bez absolutnej ścieżki", id="po-then"
    ),
    pytest.param("X=1 pkill -f x", "bez absolutnej ścieżki", id="po-przypisaniu"),
    pytest.param(
        "pkill -f x 2>/dev/null; echo ok",
        "bez absolutnej ścieżki",
        id="z-przekierowaniem",
    ),
    pytest.param(
        "cat <<EOF\ntekst\nEOF\npkill -f x", "bez absolutnej ścieżki", id="po-heredocu"
    ),
    pytest.param('pkill -f "x', "nie da się odczytać", id="niezamkniety-cudzyslow"),
    pytest.param(
        "pkill -f $(pgrep x", "nie da się odczytać", id="niezamkniete-podstawienie"
    ),
]

PRZECHODZI = [
    pytest.param(f'pkill -f "{WORKTREE}/tools/szybko.py"', id="pkill-ze-sciezka"),
    pytest.param(f"pkill -f {WORKTREE}", id="pkill-z-sama-sciezka"),
    pytest.param(f"pkill -9 -f '{WORKTREE}/tools/szybko.py'", id="pkill-z-sygnalem"),
    pytest.param(
        f"pkill -TERM -f '{WORKTREE}/tools/szybko.py'", id="pkill-z-nazwa-sygnalu"
    ),
    pytest.param(f"pkill --signal KILL -f '{WORKTREE}/x'", id="pkill-z-dluga-opcja"),
    pytest.param(f"pkill -f '{WORKTREE}/x' -P 123", id="pkill-z-rodzicem"),
    pytest.param(f"pkill -f '{WORKTREE}/[t]ools/x'", id="pkill-z-klasa-znakow"),
    pytest.param(f"pkill -f '{WORKTREE}/x$'", id="pkill-z-kotwica"),
    pytest.param(
        f"pkill -f '{WORKTREE}/x' 2>/dev/null || true", id="pkill-z-przekierowaniem"
    ),
    pytest.param(f"killall '{WORKTREE}/bin/serwer'", id="killall-ze-sciezka"),
    pytest.param("kill $!", id="kill-pid-z-tla"),
    pytest.param("sleep 60 & echo $! > plik.pid", id="zapis-pid"),
    pytest.param('kill "$(cat plik.pid)"', id="kill-pid-z-pliku"),
    pytest.param("kill -TERM $PID", id="kill-pid-ze-zmiennej"),
    pytest.param(
        f'kill $(pgrep -f "{WORKTREE}/tools/szybko.py")', id="kill-pgrep-ze-sciezka"
    ),
    pytest.param("kill -0 $(pgrep -f szybko) && echo zyje", id="kill-0-sprawdza-pgrep"),
    pytest.param("pgrep -fl szybko", id="pgrep-bez-kill"),
    pytest.param("grep -rn pkill tools/hooks", id="grep-z-issue"),
    pytest.param("rg 'killall|pkill' docs", id="rg"),
    pytest.param('git commit -m "fix(hooki): pkill -f bez ścieżki"', id="opis-commitu"),
    pytest.param("echo 'pkill -f x'", id="echo"),
    pytest.param(
        "gh pr create --body \"$(cat <<'EOF'\npkill -f x i killall node\nEOF\n)\"",
        id="heredoc-opisu-pr",
    ),
    pytest.param("ls # potem: ; pkill -f x", id="komentarz"),
    pytest.param("kill -1 4321", id="kill-sygnalem-1"),
    pytest.param("ssh box 'pkill -f pytest'", id="ssh-na-innej-maszynie"),
]

ZNANE_LUKI = [
    pytest.param("bash <<'EOF'\npkill -f x\nEOF", id="heredoc-do-powloki"),
    pytest.param("bash <<< 'pkill -f x'", id="here-string-do-powloki"),
    pytest.param("env -S 'pkill -f x'", id="env-s"),
    pytest.param(
        "ps aux | grep szybko | awk '{print $2}' | xargs kill", id="pidy-z-ps"
    ),
    pytest.param("kill -9 $(lsof -ti :8000)", id="pidy-z-lsof"),
    pytest.param("python3 -c 'import os; os.system(\"pkill -f x\")'", id="inny-jezyk"),
    pytest.param("sh zabij.sh", id="skrypt-z-pliku"),
    pytest.param("K=pkill; $K -f x", id="program-ze-zmiennej"),
    pytest.param(
        "find . -name x -exec pkill -f x ';'", id="program-uruchamiajacy-spoza-listy"
    ),
]


def _hook(
    stdin: str, project: str | None = WORKTREE
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"
    }
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = project
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _bash(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


@pytest.mark.parametrize(("command", "said"), ODMOWY)
def test_zabijanie_spoza_wlasnego_worktree_dostaje_odmowe(
    command: str, said: str
) -> None:
    refusal = hook.judge(command, WORKTREE)

    assert refusal is not None
    assert said in refusal.reason


@pytest.mark.parametrize("command", PRZECHODZI)
def test_zabijanie_wlasnych_procesow_i_inne_polecenia_przechodza(command: str) -> None:
    assert hook.judge(command, WORKTREE) is None


@pytest.mark.parametrize("command", ZNANE_LUKI)
def test_znane_luki_hooka_zabijania_przechodza(command: str) -> None:
    assert hook.judge(command, WORKTREE) is None, (
        "hook łapie już tę postać: usuń ją ze ZNANE_LUKI i dopisz do ODMOWY"
    )


def test_hook_odmawia_kodem_2_i_podaje_dozwolona_droge() -> None:
    hooked = _hook(_bash(PUSTE_PODSTAWIENIE))

    assert (hooked.returncode, hooked.stdout) == (2, "")
    for allowed in (
        "TaskStop z ID zadania",
        "echo $! > plik.pid",
        'kill "$(cat plik.pid)"',
        f"pkill -f '{WORKTREE}/tools/szybko.py'",
    ):
        assert allowed in hooked.stderr


@pytest.mark.parametrize(
    ("project", "said"),
    [
        pytest.param(None, "($CLAUDE_PROJECT_DIR)", id="bez-zmiennej"),
        pytest.param("/", "($CLAUDE_PROJECT_DIR)", id="korzen-dysku"),
        pytest.param(
            "worktrees/t3-moj", "($CLAUDE_PROJECT_DIR)", id="sciezka-wzgledna"
        ),
    ],
)
def test_bez_absolutnej_sciezki_projektu_kazdy_pkill_dostaje_odmowe(
    project: str | None, said: str
) -> None:
    hooked = _hook(_bash(f"pkill -f '{WORKTREE}/tools/szybko.py'"), project)

    assert hooked.returncode == 2
    assert said in hooked.stderr


def test_sciezka_projektu_z_ukosnikiem_na_koncu_wpuszcza_wlasny_pkill() -> None:
    hooked = _hook(_bash(f"pkill -f '{WORKTREE}/tools/szybko.py'"), WORKTREE + "/")

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "[]",
        '{"tool_input": {"command": 5}}',
        '{"tool_name": "Bash"}',
    ],
    ids=["pusto", "lista", "liczba", "bez-polecenia"],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def _configured(project: Path, command: str) -> list[subprocess.CompletedProcess[str]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    hooks = [
        hook
        for entry in entries
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
        if "zabijanie.py" in hook["command"]
    ]
    assert [hook["timeout"] for hook in hooks] == [10]
    return [
        subprocess.run(
            hook["command"],
            shell=True,
            input=_bash(command),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
        )
        for hook in hooks
    ]


@pytest.mark.skipif(
    sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store"
)
def test_ustawienia_projektu_wpinaja_hook_zabijania_dla_basha() -> None:
    refused = _configured(ROOT, BEZ_SCIEZKI)
    own = _configured(ROOT, f"pkill -f '{ROOT.as_posix()}/tools/szybko.py'")

    assert [(run.returncode, "TaskStop" in run.stderr) for run in refused] == [
        (2, True)
    ]
    assert [(run.returncode, run.stderr) for run in own] == [(0, "")]


@pytest.mark.skipif(
    sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store"
)
def test_checkout_bez_skryptu_hooka_zabijania_nie_blokuje_basha(tmp_path: Path) -> None:
    hooked = _configured(tmp_path, BEZ_SCIEZKI)

    assert [(run.returncode, run.stderr) for run in hooked] == [(0, "")]
