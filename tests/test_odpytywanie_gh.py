from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.fixtures.fake_cli import fake_cli

import github
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

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="nakładka to skrypt sh w PATH sesji Claude Code na Macu")


def _real_gh(tmp_path: Path) -> Path:
    return fake_cli(tmp_path / "bin", "gh", REAL_GH).parent


def _environment(tmp_path: Path, session: str = "sesja-1") -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in (nakladka.POMIJA, "GH_REPO")}
    path = os.pathsep.join([str(nakladka.NAKLADKI), str(_real_gh(tmp_path)), os.environ["PATH"]])
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


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({nakladka.POMIJA: "1"}, id="narzedzie-repo"),
        pytest.param({nakladka.ZMIENNA_SESJI: ""}, id="bez-sesji"),
    ],
)
def test_narzedzie_repo_i_polecenie_spoza_sesji_przechodza(tmp_path: Path, change: dict[str, str]) -> None:
    environment = {**_environment(tmp_path), **change}

    codes = [_gh(environment, "pr", "checks", "2178", cwd=tmp_path).returncode for _ in range(LIMIT + 2)]

    assert codes == [0] * (LIMIT + 2)


def test_kod_wyjscia_prawdziwego_gh_wraca_przez_nakladke(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    (tmp_path / "bin" / "kod").write_text("4")

    assert _gh(environment, "pr", "checks", "2178", cwd=tmp_path).returncode == 4


def test_narzedzia_repo_wolaja_gh_ze_znacznikiem_pominiecia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cli(tmp_path / "bin", "gh", f"import os\nprint(os.environ.get({nakladka.POMIJA!r}, 'brak'))\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    assert github.gh("pr", "checks", "1", cwd=tmp_path).strip() == "1"


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
