from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import commit, copy_files, git, with_imports

import nakladka

ROOT = Path(__file__).resolve().parents[1]
SESSION_HOOK = ROOT / "tools" / "hooks" / "nakladka_gh.py"
SETTINGS = ROOT / ".claude" / "settings.json"
REAL_GH = (
    "import json, pathlib, sys\n"
    "here = pathlib.Path(__file__)\n"
    "with here.with_name('wywolania.jsonl').open('a') as stored:\n"
    "    stored.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    "code = here.with_name('kod')\n"
    "sys.exit(int(code.read_text()) if code.exists() else 0)\n"
)
LIMIT = 6
POLL = (
    "import subprocess, sys\n"
    "route = sys.argv[1] if len(sys.argv) > 1 else 'lista'\n"
    "command = {'lista': ['gh', 'pr', 'checks', '1'], 'powloka': 'gh pr checks 1', 'xargs': ['xargs', 'gh', 'pr', 'checks']}[route]\n"
    "codes = [subprocess.run(command, shell=route == 'powloka', input='1', text=True, cwd='/', capture_output=True).returncode for _ in range(8)]\n"
    "print(*codes)\n"
)
SHELL_POLL = "for i in 1 2 3 4 5 6 7 8; do gh pr checks 1 >/dev/null 2>&1; printf '%s ' $?; done"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="nakładka to skrypt sh w PATH sesji Claude Code na Macu")


def _real_gh(tmp_path: Path) -> Path:
    return fake_cli(tmp_path / "bin", "gh", REAL_GH).parent


def _environment(tmp_path: Path, session: str = "sesja-1", wrapper: Path = nakladka.NAKLADKI) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key != "GH_REPO"}
    path = os.pathsep.join([str(wrapper), str(_real_gh(tmp_path)), os.environ["PATH"]])
    return {**environment, "HOME": str(tmp_path / "dom"), "PATH": path, nakladka.ZMIENNA_SESJI: session}


def _gh(environment: dict[str, str], *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *arguments], env=environment, cwd=cwd, capture_output=True, text=True, check=False)


def _calls(tmp_path: Path) -> list[list[str]]:
    stored = tmp_path / "bin" / "wywolania.jsonl"
    return [json.loads(line) for line in stored.read_text().splitlines()] if stored.exists() else []


STATUS_QUERIES = [
    pytest.param(["pr", "checks", "2178"], id="gh-pr-checks"),
    pytest.param(["run", "view", "44439947891", "--json", "status"], id="gh-run-view"),
    pytest.param(["run", "list", "--branch", "main", "-L", "1"], id="gh-run-list-main"),
    pytest.param(["pr", "view", "2178", "--json", "statusCheckRollup"], id="gh-pr-view-status"),
    pytest.param(["api", "repos/o/r/actions/jobs/132626412782"], id="gh-api-stan-zadania"),
    pytest.param(["-R", "o/r", "pr", "checks", "1"], id="opcja-repo-przed-poleceniem"),
]


@pytest.mark.parametrize("arguments", STATUS_QUERIES)
def test_siodme_takie_samo_zapytanie_o_stan_ci_w_oknie_dostaje_odmowe_bez_gh(tmp_path: Path, arguments: list[str]) -> None:
    environment = _environment(tmp_path)

    allowed = [_gh(environment, *arguments, cwd=tmp_path).returncode for _ in range(LIMIT)]
    refused = _gh(environment, *arguments, cwd=tmp_path)

    assert allowed == [0] * LIMIT
    assert (refused.returncode, len(_calls(tmp_path))) == (2, LIMIT)
    assert "watch_pull_request" in refused.stderr and "nie czekaj" in refused.stderr, refused.stderr


DIFFERENT = [
    pytest.param([["pr", "checks", str(number)] for number in range(LIMIT + 2)], id="rozne-pr"),
    pytest.param([["pr", "view", "1", "--json", "title"]] * (LIMIT + 2), id="pr-view-bez-stanu-ci"),
    pytest.param([["run", "view", "1", "--log-failed"]] * (LIMIT + 2), id="logi-runu"),
    pytest.param([["run", "view", "1", "--log"]] * (LIMIT + 2), id="caly-log-runu"),
    pytest.param([["run", "view", "1", "--web"]] * (LIMIT + 2), id="run-w-przegladarce"),
    pytest.param([["run", "view", "1", "-w"]] * (LIMIT + 2), id="run-w-przegladarce-krotko"),
    pytest.param([["api", "repos/o/r/actions/jobs/1/logs"]] * (LIMIT + 2), id="logi-zadania"),
    pytest.param([["issue", "list"]] * (LIMIT + 2), id="inne-polecenie"),
]


@pytest.mark.parametrize("calls", DIFFERENT)
def test_rozne_zapytania_i_polecenia_bez_stanu_ci_przechodza(tmp_path: Path, calls: list[list[str]]) -> None:
    environment = _environment(tmp_path)

    codes = [_gh(environment, *arguments, cwd=tmp_path).returncode for arguments in calls]

    assert codes == [0] * len(calls)


def test_to_samo_zapytanie_w_innym_katalogu_albo_repozytorium_to_inne_zapytanie(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    folders = [tmp_path / f"wt{number}" for number in range(LIMIT + 2)]
    for folder in folders:
        folder.mkdir()

    in_folders = [_gh(environment, "pr", "checks", cwd=folder).returncode for folder in folders]
    in_repositories = [
        _gh({**environment, "GH_REPO": f"o/r{number}"}, "run", "list", "-L", "5", cwd=tmp_path).returncode
        for number in range(LIMIT + 2)
    ]

    assert in_folders + in_repositories == [0] * 2 * (LIMIT + 2)


def test_zapytanie_sprzed_okna_sie_nie_liczy(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    arguments = ["pr", "checks", "2178"]
    stored = tmp_path / "dom" / ".cache" / "maximiseart" / "odpytywanie_gh" / "sesja-1.jsonl"
    stored.parent.mkdir(parents=True)
    key = json.dumps([str(tmp_path.resolve()), "", arguments])
    old = time.time() - 601
    stored.write_text("".join(json.dumps({"t": old, "k": key}) + "\n" for _ in range(LIMIT)), encoding="utf-8")

    assert _gh(environment, *arguments, cwd=tmp_path).returncode == 0


def test_polecenie_spoza_sesji_przechodzi(tmp_path: Path) -> None:
    environment = {**_environment(tmp_path), nakladka.ZMIENNA_SESJI: ""}

    codes = [_gh(environment, "pr", "checks", "2178", cwd=tmp_path).returncode for _ in range(LIMIT + 2)]

    assert codes == [0] * (LIMIT + 2)


def test_kod_wyjscia_prawdziwego_gh_wraca_przez_nakladke(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    (tmp_path / "bin" / "kod").write_text("4")

    assert _gh(environment, "pr", "checks", "2178", cwd=tmp_path).returncode == 4


def _repo_copy(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    copy_files(repo, [*with_imports(["tools/hooks/odpytywanie_gh.py"]), "tools/nakladki/gh"])
    (repo / "tools" / "czeka.py").write_text(POLL, encoding="utf-8")
    (repo / "tools" / "czeka.sh").write_text(SHELL_POLL, encoding="utf-8")
    git(repo, "init", "--quiet")
    commit(repo, "nakładka")
    (repo / "nowy.py").write_text(POLL, encoding="utf-8")
    (tmp_path / "poza").mkdir()
    (tmp_path / "poza" / "czeka.py").write_text(POLL, encoding="utf-8")
    (tmp_path / "poza" / "czeka.sh").write_text(SHELL_POLL, encoding="utf-8")
    return repo


CALLERS = [
    pytest.param(["{python}", "tools/czeka.py"], "repo", [0] * 8, id="skrypt-repo-sciezka-wzgledna"),
    pytest.param(["{python}", "{repo}/tools/czeka.py"], "tmp", [0] * 8, id="skrypt-repo-sciezka-bezwzgledna"),
    pytest.param(["{python}", "tools/czeka.py", "powloka"], "repo", [0] * 8, id="skrypt-repo-przez-powloke"),
    pytest.param(["{python}", "tools/czeka.py", "xargs"], "repo", [0] * 8, id="skrypt-repo-przez-xargs"),
    pytest.param(["sh", "tools/czeka.sh"], "repo", [0] * 8, id="skrypt-powloki-w-repo"),
    pytest.param(["{python}", "-c", POLL], "repo", [0] * LIMIT + [2, 2], id="python-c"),
    pytest.param(["{python}", "-"], "repo", [0] * LIMIT + [2, 2], id="python-heredoc"),
    pytest.param(["{python}", "nowy.py"], "repo", [0] * LIMIT + [2, 2], id="nieśledzony-skrypt-w-repo"),
    pytest.param(["{python}", "{tmp}/poza/czeka.py"], "tmp", [0] * LIMIT + [2, 2], id="skrypt-spoza-repo"),
    pytest.param(["sh", "{tmp}/poza/czeka.sh"], "tmp", [0] * LIMIT + [2, 2], id="skrypt-powloki-spoza-repo"),
    pytest.param(["sh", "-c", SHELL_POLL], "repo", [0] * LIMIT + [2, 2], id="petla-powloki"),
]


@pytest.mark.parametrize(("command", "folder", "codes"), CALLERS)
def test_skrypt_sledzony_w_repo_czeka_bez_odmowy_ktoredykolwiek_wola_gh_a_petla_agenta_dostaje_odmowe(
    tmp_path: Path, command: list[str], folder: str, codes: list[int]
) -> None:
    repo = _repo_copy(tmp_path)
    environment = _environment(tmp_path, wrapper=repo / "tools" / "nakladki")

    done = subprocess.run(
        [word.replace("{python}", sys.executable).replace("{repo}", str(repo)).replace("{tmp}", str(tmp_path)) for word in command],
        input=POLL,
        cwd=repo if folder == "repo" else tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert [int(code) for code in done.stdout.split()] == codes, done.stderr


def test_nakladka_przepuszcza_gh_z_ostrzezeniem_gdy_hook_czekania_sie_nie_importuje(tmp_path: Path) -> None:
    repo = _repo_copy(tmp_path)
    (repo / "tools" / "hooks" / "czekanie.py").write_text("<<<<<<< HEAD\n", encoding="utf-8")
    environment = _environment(tmp_path, wrapper=repo / "tools" / "nakladki")

    calls = [_gh(environment, "pr", "checks", "2178", cwd=tmp_path) for _ in range(LIMIT + 2)]

    assert [call.returncode for call in calls] == [0] * (LIMIT + 2)
    assert "czekanie.py się nie importuje (SyntaxError" in calls[-1].stderr, calls[-1].stderr


def _session_start_command() -> str:
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    command: str
    (command,) = [hook["command"] for entry in hooks for hook in entry["hooks"] if "nakladka_gh.py" in hook["command"]]
    return command


def test_sesja_dostaje_nakladke_gh_na_poczatku_path_i_swoj_identyfikator(tmp_path: Path) -> None:
    env_file = tmp_path / "sesja.sh"
    env_file.touch()

    subprocess.run(
        ["sh", "-c", _session_start_command()],
        input=json.dumps({"session_id": "abc-123"}),
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), "CLAUDE_ENV_FILE": str(env_file)},
        text=True,
        check=True,
    )
    seen = subprocess.run(
        ["sh", "-c", f'. "$1"; command -v gh; echo "${nakladka.ZMIENNA_SESJI}"', "sesja", str(env_file)],
        env={**os.environ, "PATH": f"{_real_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert seen == [str(nakladka.NAKLADKI / "gh"), "abc-123"]


@pytest.mark.parametrize("session", ["../poza", "", 5], ids=["sciezka", "pusty", "liczba"])
def test_identyfikator_sesji_spoza_wzorca_nie_trafia_do_srodowiska(tmp_path: Path, session: object) -> None:
    env_file = tmp_path / "sesja.sh"
    env_file.touch()

    subprocess.run(
        [sys.executable, str(SESSION_HOOK)],
        input=json.dumps({"session_id": session}),
        env={**os.environ, "CLAUDE_ENV_FILE": str(env_file)},
        text=True,
        check=True,
    )

    assert env_file.read_text(encoding="utf-8") == ""
