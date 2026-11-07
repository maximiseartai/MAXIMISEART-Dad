"""``tools/ci/status_scalenia.py``: każdy otwarty PR do bazy, poza PR z forka, dostaje status, czy jego scalenie z bieżącą
bazą przechodzi.

Testy biegną na prawdziwym Gicie z repozytorium bare jako ``origin`` (z ``refs/pull/N/head`` jak na GitHubie)
i na prawdziwym ``tools/ci_lokalnie.py --tylko ruff,mypy`` na małym kodzie. Atrapa ``gh`` podaje otwarte PR-y
i zapisuje statusy, które narzędzie wysyła do GitHuba.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub
from tests.fixtures.git_repo import git
from tests.fixtures.potomne import beating, wait_for, with_grandchild, worktrees

pytestmark = ONLY_FOUND_BY_NAME_ON_POSIX

SUM = "def suma(a: int, b: int) -> int:\n    return a + b\n"
SUM_OF_THREE = "def suma(a: int, b: int, c: int) -> int:\n    return a + b + c\n"
TYPE_ERROR = 'LICZBA: int = "tekst"\n'
LONG_NAMES = [f"dlugie/plik-o-bardzo-dlugiej-nazwie-numer-{number}.txt" for number in range(6)]
FAKE_GH = """\
import json, pathlib, sys

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
if arguments[:2] == ["pr", "list"] and "--state" in arguments and arguments[arguments.index("--state") + 1] == "open":
    fields = arguments[arguments.index("--json") + 1].split(",")
    pulls = json.loads((here / "pulls.json").read_text())
    print(json.dumps([{field: pull[field] for field in fields} for pull in pulls]))
elif arguments[:3] == ["api", "--method", "POST"]:
    path = next(argument for argument in arguments if argument.startswith("repos/"))
    if path.rpartition("/")[2] in (here / "odrzucane").read_text().split():
        sys.exit("HTTP 422: Validation Failed")
    fields = dict(value.split("=", 1) for flag, value in zip(arguments, arguments[1:]) if flag == "-f")
    with (here / "statuses.jsonl").open("a") as log:
        log.write(json.dumps({"path": path, **fields}) + "\\n")
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


class StatusGitHub(FakeGitHub):
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        super().__init__(
            tmp_path,
            {
                ".gitignore": ".mypy_cache/\n.ruff_cache/\n__pycache__/\n",
                "pyproject.toml": '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nstrict = true\nfiles = ["kod"]\n',
                **files,
            },
            tool="tools/ci/status_scalenia.py",
            copies=("tools/lib/werdykt_scalenia.py", "tools/lib/github.py"),
            gh=FAKE_GH,
        )
        (self.bin / "odrzucane").write_text("", encoding="utf-8")
        self.pulls: list[dict[str, object]] = []

    def open_pull(self, number: int, files: dict[str, str], *, base: str = "main", fork: bool = False, parent: str = "") -> str:
        """HEAD nowego PR: commit ``files`` na ``parent`` (domyślnie commit ``start``)."""

        head = self.commit_on(parent or self.start, files, f"PR {number}")
        self.push_head(number, head)
        self.pulls.append(
            {"number": number, "title": f"PR {number}", "headRefOid": head, "baseRefName": base, "isCrossRepository": fork}
        )
        (self.bin / "pulls.json").write_text(json.dumps(self.pulls), encoding="utf-8")
        return head

    def reject_statuses_for(self, head: str) -> None:
        (self.bin / "odrzucane").write_text(head, encoding="utf-8")

    def statuses_by_head(self) -> dict[str, list[dict[str, str]]]:
        log = self.bin / "statuses.jsonl"
        sent: dict[str, list[dict[str, str]]] = {}
        for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
            status = json.loads(line)
            sent.setdefault(status.pop("path").removeprefix("repos/{owner}/{repo}/statuses/"), []).append(status)
        return sent


def test_kazdy_pr_do_main_dostaje_werdykt_scalenia_z_nowym_main(tmp_path: Path) -> None:
    github = StatusGitHub(
        tmp_path, {"kod/__init__.py": SUM, "kod/nazwa.py": 'NAZWA = "pierwsza"\n', **dict.fromkeys(LONG_NAMES, "start\n")}
    )
    agrees = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    collides = github.open_pull(2, {"kod/uzycie.py": "from kod import suma\n\nWYNIK = suma(1, 2)\n"})
    collides_on_windows = github.open_pull(
        3, {"kod/okna.py": 'import sys\n\nfrom kod import suma\n\nif sys.platform == "win32":\n    WYNIK = suma(1, 2)\n'}
    )
    conflicts = github.open_pull(4, {"kod/nazwa.py": 'NAZWA = "z PR"\n'})
    conflicts_in_many_files = github.open_pull(5, dict.fromkeys(LONG_NAMES, "z PR\n"))
    from_fork = github.open_pull(6, {"kod/forka.py": "FORK: int = 1\n"}, fork=True)
    stacked = github.open_pull(7, {"kod/stos.py": "STOS: int = 1\n"}, base="inna")
    main = github.push_main(
        {"kod/__init__.py": SUM_OF_THREE, "kod/nazwa.py": 'NAZWA = "z main"\n', **dict.fromkeys(LONG_NAMES, "z main\n")}
    )
    head_before = git(github.checkout, "rev-parse", "HEAD")

    answered = github.run("--publikuj")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    sent = github.statuses_by_head()
    assert set(sent) == {agrees, collides, collides_on_windows, conflicts, conflicts_in_many_files}
    assert from_fork not in sent and stacked not in sent
    final = {}
    for head, statuses in sent.items():
        assert [status["context"] for status in statuses] == ["scalenie z main"]
        final[head] = statuses[0]
        assert f"main {main[:7]}" in final[head]["description"]
        assert len(final[head]["description"]) <= 140
    assert final[agrees]["state"] == "success"
    assert final[collides]["state"] == "failure"
    assert final[collides]["description"].endswith(": mypy, mypy (Windows)")
    assert final[collides_on_windows]["state"] == "failure"
    assert final[collides_on_windows]["description"].endswith(": mypy (Windows)")
    assert final[conflicts]["state"] == "failure"
    assert final[conflicts]["description"].endswith(": kod/nazwa.py")
    assert final[conflicts_in_many_files]["state"] == "failure"
    assert final[conflicts_in_many_files]["description"].endswith("…")
    assert git(github.checkout, "rev-parse", "HEAD") == head_before
    assert git(github.checkout, "status", "--porcelain") == ""
    assert len(worktrees(github.checkout)) == 1


def test_gdy_baza_sama_pada_pr_ktory_jej_nie_naprawia_dostaje_blad_a_bez_publikuj_nic_nie_trafia_na_github(
    tmp_path: Path,
) -> None:
    github = StatusGitHub(tmp_path, {"kod/__init__.py": SUM})
    main = github.push_main({"kod/__init__.py": SUM + TYPE_ERROR})
    github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_pull(2, {"kod/__init__.py": SUM}, parent=main)

    answered = github.run()

    assert answered.returncode == 0, answered.stdout + answered.stderr
    lines = answered.stdout.splitlines()
    assert f"#1 error | main {main[:7]} sam nie przechodzi: mypy, mypy (Windows)" in lines
    assert any(line.startswith("#2 success | ") for line in lines)
    assert github.statuses_by_head() == {}


def test_pr_do_innej_bazy_dostaje_jej_werdykt_a_odrzucony_status_nie_zatrzymuje_reszty(tmp_path: Path) -> None:
    github = StatusGitHub(tmp_path, {"kod/__init__.py": SUM})
    git(github.checkout, "push", "--quiet", "origin", f"{github.start}:refs/heads/inna")
    github.push_main({"kod/__init__.py": SUM_OF_THREE})
    rejected = github.open_pull(1, {"kod/pierwszy.py": "PIERWSZY: int = 1\n"}, base="inna")
    accepted = github.open_pull(2, {"kod/drugi.py": "DRUGI: int = 1\n"}, base="inna")
    to_main = github.open_pull(3, {"kod/trzeci.py": "TRZECI: int = 1\n"})
    github.reject_statuses_for(rejected)

    answered = github.run("--publikuj", "--baza", "inna")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert answered.stdout.splitlines()[-1].startswith("SCALENIA FAIL | ")
    assert answered.stdout.splitlines()[-1].endswith("statusy niewysłane: #1")
    sent = github.statuses_by_head()
    assert set(sent) == {accepted}
    assert to_main not in sent
    assert [(status["context"], status["state"]) for status in sent[accepted]] == [("scalenie z inna", "success")]
    assert f"inna {github.start[:7]}" in sent[accepted][0]["description"]


def test_zabite_narzedzie_nie_zostawia_sprawdzen_ani_kopii_bazy(tmp_path: Path) -> None:
    beats = tmp_path / "wnuk-zyje"
    hangs = with_grandchild(beats, "time.sleep(600)")
    github = StatusGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.open_pull(1, {"tools/ci_lokalnie.py": f"import subprocess\n\nsubprocess.run({hangs!r})\n"})
    started = subprocess.Popen(
        github.command(), cwd=github.checkout, env=github.environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        assert wait_for(beats.exists, 90), "ci_lokalnie ze scalenia nie uruchomiło wiszącego sprawdzenia"
        copies = worktrees(github.checkout)[1:]

        started.kill()
        started.wait(timeout=20)
        wait_for(lambda: not beating(beats) and not any(copy.exists() for copy in copies), 20)

        assert not beating(beats)
        assert (len(copies), [copy for copy in copies if copy.exists()], len(worktrees(github.checkout))) == (1, [], 1)
    finally:
        started.kill()
        started.wait()
