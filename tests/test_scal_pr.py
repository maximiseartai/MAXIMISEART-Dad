"""``tools/scal_pr.py``: agent scala PR tylko przy zielonym CI na HEAD, werdykcie PASS dla HEAD, opisie z sekcjami wzoru
skilla ``pr`` i scaleniu z bieżącą bazą, które przechodzi ruff i mypy.

Testy biegną na prawdziwym Gicie z repozytorium bare jako ``origin`` (z ``refs/pull/N/head`` jak na GitHubie)
i na prawdziwym ``tools/ci_lokalnie.py --tylko ruff,mypy`` na małym kodzie. Atrapa ``gh`` podaje stan PR i zapisuje
wywołania ``gh pr merge`` zamiast scalać.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.fixtures import opisy_pr
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub, fake_cli
from tests.fixtures.git_repo import commit, git, with_imports

import czasy_ci
import naprawia

pytestmark = ONLY_FOUND_BY_NAME_ON_POSIX

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TEMPLATE = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "pr" / "SKILL.md"
BODY = opisy_pr.wzor("Cel.")
SUM = "def suma(a: int, b: int) -> int:\n    return a + b\n"
PYPROJECT = '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nstrict = true\nfiles = ["kod"]\n'
CLEANUP = 'import pathlib\n\npathlib.Path("posprzatane").write_text("tak")\nprint("SPRZĄTANIE OK | 0 usuniętych")\n'
FAKE_GH = """\
import json, os, pathlib, subprocess, sys, time

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
pulls = json.loads((here / "pulls.json").read_text())
issues = json.loads((here / "issues.json").read_text())
repo_view = (here / "repo_view").read_text()
markdown = json.loads((here / "markdown.json").read_text())


def git(*command):
    identity = {f"GIT_{role}_{key}": value for role in ("AUTHOR", "COMMITTER") for key, value in (("NAME", "gh"), ("EMAIL", "gh@example.com"))}
    done = subprocess.run(["git", "-c", "commit.gpgsign=false", *command], cwd=here.parent / "origin.git", env={**os.environ, **identity}, capture_output=True, text=True, check=True)
    return done.stdout.strip()


REPO = "maximiseartai/MAXIMISEART-Dad"


if arguments[:2] == ["pr", "view"]:
    pull = pulls[arguments[2]]
    if pull.get("poMergeu") == "błąd" and pull["state"] == "MERGED":
        sys.exit("gh: HTTP 502")
    print(json.dumps({field: pull[field] for field in arguments[arguments.index("--json") + 1].split(",")}))
elif arguments[:2] == ["pr", "merge"]:
    pull = pulls[arguments[2]]
    if arguments[arguments.index("--match-head-commit") + 1] != pull["headRefOid"]:
        sys.exit("HEAD PR zmienił się")
    base = git("rev-parse", "refs/heads/main")
    tree = git("merge-tree", "--write-tree", base, pull["headRefOid"])
    merge = git("commit-tree", tree, "-p", base, "-p", pull["headRefOid"], "-m", "Merge")
    git("update-ref", "refs/heads/main", merge)
    pull.update(state="MERGED", mergeCommit=None if pull.get("poMergeu") else {"oid": merge})
    (here / "pulls.json").write_text(json.dumps(pulls))
    with (here / "merges.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
elif arguments == ["api", "markdown", "--input", "-"]:
    request = json.loads(sys.stdin.read())
    with (here / "renders.jsonl").open("a") as log:
        log.write(json.dumps(request) + "\\n")
    if request.keys() != {"text", "mode", "context"} or request["mode"] != "gfm" or request["context"].casefold() != REPO.casefold():
        sys.exit(f"atrapa gh nie zna renderowania: {request}")
    html = markdown.get(request["text"], "gh: atrapa gh nie zna opisu")
    if html == "zawiesza":
        time.sleep(60)
    elif html.startswith("gh: "):
        sys.exit(html)
    print(html, end="")
elif arguments[0] == "api" and arguments[1].startswith(f"repos/{REPO}/issues/"):
    number = arguments[1].rpartition("/")[2]
    if issues.get(number) == "zawiesza":
        time.sleep(60)
    elif number in issues:
        print(issues[number])
    else:
        sys.exit("gh: Not Found (HTTP 404)")
elif arguments[:2] == ["repo", "view"]:
    with (here / "repo_views.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
    if repo_view.startswith("gh: "):
        sys.exit(repo_view)
    print(repo_view)
elif arguments[:2] == ["pr", "comment"]:
    pull = pulls[arguments[2]]
    body = pathlib.Path(arguments[arguments.index("--body-file") + 1]).read_text(encoding="utf-8")
    pull["comments"].append({"body": body, "authorAssociation": "OWNER", "createdAt": "2026-10-25T00:00:00Z", "author": {"login": "recenzent"}})
    (here / "pulls.json").write_text(json.dumps(pulls))
    with (here / "comments.jsonl").open("a") as log:
        log.write(json.dumps([arguments[2], body]) + "\\n")
    print(f"https://github.com/{REPO}/pull/{arguments[2]}#issuecomment-{len(pull['comments'])}")
elif arguments[:2] == ["run", "list"]:
    with (here / "run_lists.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
    runs = here / "runs.json"
    merged = arguments[arguments.index("--commit") + 1] == git("rev-parse", "refs/heads/main")
    print(runs.read_text() if merged and runs.exists() else "[]")
elif arguments[:2] == ["issue", "close"]:
    issues[arguments[2]] = json.dumps({"state": "closed"})
    (here / "issues.json").write_text(json.dumps(issues))
    with (here / "closed.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


URL = "https://github.com/o/r/actions/runs/4077/job/1"


def _check_run(
    status: str,
    conclusion: str | None,
    *,
    workflow: str = "CI",
    name: str = "Required CI status",
    url: str = URL,
    started: str | None = None,
) -> dict[str, str | None]:
    check = {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "workflowName": workflow, "detailsUrl": url}
    return check if started is None else {**check, "startedAt": started}


GREEN = [_check_run("COMPLETED", "SUCCESS", name="Ruff"), _check_run("COMPLETED", "SUCCESS")]
COMMIT_STATUS = {"__typename": "StatusContext", "context": "Required CI status", "state": "SUCCESS"}
NOT_ACTIONS = "CI: brak „Required CI status” z GitHub Actions na HEAD"
PASS = "WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)"
NO_PASS = "werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”; opublikuj werdykt przez tools/scal_pr.py 1 --werdykt PLIK"
OBJECTION = "werdykt: FAIL dla {short} bez nowszego „WERDYKT: PASS {head}”"


class MergeGitHub(FakeGitHub):
    def __init__(self, tmp_path: Path, files: dict[str, str]) -> None:
        super().__init__(
            tmp_path,
            {
                ".gitignore": ".mypy_cache/\n.ruff_cache/\n__pycache__/\nposprzatane\n",
                "pyproject.toml": PYPROJECT,
                ".agents/skills/pr/SKILL.md": TEMPLATE.read_text(encoding="utf-8"),
                "tools/sprzatanie.py": CLEANUP,
                **files,
            },
            tool="tools/scal_pr.py",
            gh=FAKE_GH,
        )
        _empty_state(self.bin)
        self.pulls: dict[str, dict[str, object]] = {}
        self.issues: dict[str, str] = {}
        self.repo_view = _repo_view("main")  # zaczęte od „gh: ” to błąd ``gh repo view``
        self.markdown = opisy_pr.rendered()  # HTML opisu, a jak w ``answer_issue`` błąd albo ``zawiesza``
        self.written = 0

    def open_pull(self, number: int, files: dict[str, str], *, parent: str = "") -> str:
        """HEAD nowego PR z zielonym CI i bez werdyktu: commit ``files`` na ``parent`` (domyślnie commit ``start``)."""

        head = self.commit_on(parent or self.start, files, f"PR {number}")
        self.push_head(number, head)
        self.pulls[str(number)] = {
            "number": number,
            "title": f"PR {number}",
            "body": BODY,
            "state": "OPEN",
            "isDraft": False,
            "isCrossRepository": False,
            "baseRefName": "main",
            "headRefOid": head,
            "statusCheckRollup": GREEN,
            "comments": [],
            "reviews": [],
            "mergeCommit": None,
            "url": f"https://github.com/{opisy_pr.REPO}/pull/{number}",
            "closingIssuesReferences": [],
        }
        self._save()
        return head

    def update(self, number: int, **fields: object) -> None:
        self.pulls[str(number)].update(fields)
        self._save()

    def comment(self, number: int, body: str, association: str = "OWNER") -> None:
        self._write(number, "comments", {"body": body, "authorAssociation": association, "createdAt": self._now()})

    def review(self, number: int, body: str, association: str = "OWNER", *, state: str = "COMMENTED") -> None:
        self._write(number, "reviews", {"body": body, "authorAssociation": association, "state": state, "submittedAt": self._now()})

    def _now(self) -> str:
        self.written += 1
        return f"2026-10-24T03:{self.written // 60:02d}:{self.written % 60:02d}Z"

    def _write(self, number: int, kind: str, verdict: dict[str, str]) -> None:
        verdicts = self.pulls[str(number)][kind]
        assert isinstance(verdicts, list)
        verdicts.append({**verdict, "author": {"login": "recenzent"}})
        self._save()

    def open_issues(self, *numbers: int, state: str = "open") -> None:
        self.answer_issue(*numbers, answer=json.dumps({"state": state}))

    def answer_issue(self, *numbers: int, answer: str) -> None:
        """``gh api`` issue ``numbers`` drukuje ``answer``, a ``zawiesza`` każe mu czekać minutę."""

        self.issues.update(dict.fromkeys(map(str, numbers), answer))
        self._save()

    def merges(self) -> list[list[str]]:
        return self._log("merges.jsonl")

    def closed(self) -> list[list[str]]:
        return self._log("closed.jsonl")

    def published(self) -> list[list[str]]:
        """Komentarze z ``gh pr comment``: numer PR i treść."""

        return self._log("comments.jsonl")

    def push_pull(self, number: int, files: dict[str, str]) -> str:
        """Nowy HEAD PR ``number``: commit ``files`` na jego obecnym HEAD."""

        head = self.commit_on(str(self.pulls[str(number)]["headRefOid"]), files, f"PR {number} dalej")
        self.push_head(number, head)
        self.update(number, headRefOid=head)
        return head

    def run_lists(self) -> list[list[str]]:
        return self._log("run_lists.jsonl")

    def repo_views(self) -> list[list[str]]:
        return self._log("repo_views.jsonl")

    def renders(self) -> list[list[str]]:
        return self._log("renders.jsonl")

    def _log(self, name: str) -> list[list[str]]:
        log = self.bin / name
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def _save(self) -> None:
        (self.bin / "pulls.json").write_text(json.dumps(self.pulls), encoding="utf-8")
        (self.bin / "issues.json").write_text(json.dumps(self.issues), encoding="utf-8")
        (self.bin / "repo_view").write_text(self.repo_view, encoding="utf-8")
        (self.bin / "markdown.json").write_text(json.dumps(self.markdown), encoding="utf-8")


def _fake_gh(tmp_path: Path) -> Path:
    """Katalog atrapy ``gh`` bez PR-ów i issues, która renderuje opisy z ``tests/fixtures/opisy_pr.json``."""

    directory = tmp_path / "bin"
    fake_cli(directory, "gh", FAKE_GH)
    _empty_state(directory)
    return directory


def _empty_state(directory: Path) -> None:
    for name, empty in (("pulls.json", "{}"), ("issues.json", "{}"), ("repo_view", ""), ("markdown.json", json.dumps(opisy_pr.rendered()))):
        (directory / name).write_text(empty, encoding="utf-8")


def _short_github_timeout(github: MergeGitHub) -> str:
    """Commit na ``main`` z ``github.LIMIT_S`` równym 3 s, żeby ``gh``, które zawiesza, kończyło się szybko."""

    klient = github.checkout / "tools" / "lib" / "github.py"
    klient.write_text(klient.read_text(encoding="utf-8").replace("LIMIT_S = 60", "LIMIT_S = 3"), encoding="utf-8")
    git(github.checkout, "commit", "--quiet", "--all", "--message", "gh po 3 s")
    git(github.checkout, "push", "--quiet", "origin", "main")
    return git(github.checkout, "rev-parse", "HEAD")


def _repo_view(default_branch: str) -> str:
    return json.dumps({"defaultBranchRef": {"name": default_branch}})


def _last_line(answered: subprocess.CompletedProcess[str]) -> str:
    return answered.stdout.rstrip().rpartition("\n")[2]


def test_gotowy_pr_jest_scalany_z_jego_head_a_po_merge_biegnie_sprzatanie(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    main = github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})
    github.comment(1, f"WERDYKT: FAIL {head}\n- krytyczne: brak testu")
    github.comment(1, f"Poprawione w {head[:7]}.")
    github.comment(1, f"WERDYKT: PASS {head}\nZnaleziska: 1 (Ważne 0, Drobne 1)\n- Drobne: nazwa")

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main {main[:7]}")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == (
        f"SCAL OK | #1 {head[:7]} | scalony do main jako {merge_commit[:7]} (baza {main[:7]}) | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    )
    assert git(github.origin, "rev-list", "--parents", "-n", "1", merge_commit).split()[1:] == [main, head]
    assert github.merges() == [["pr", "merge", "1", "--merge", "--match-head-commit", head]]
    assert (github.checkout / "posprzatane").exists()


@pytest.mark.parametrize(
    ("conclusion", "own"),
    [
        ("", "run commitu merge'a 4242 https://github.com/o/r/actions/runs/4242, o ile nowszy push nie anuluje go, zanim ruszy"),
        ("cancelled", "run commitu merge'a 4242 anulowany, więc rozstrzyga run późniejszego commitu z gh run list --workflow CI --event push --branch main"),
        (None, "runu commitu merge'a jeszcze nie ma, runy pokaże gh run list --workflow CI --event push --branch main"),
    ],
    ids=["run-czeka", "run-anulowany", "runu-jeszcze-nie-ma"],
)
def test_po_merge_do_main_linia_ci_main_mowi_ze_rozstrzyga_pierwszy_nieanulowany_run_z_merge_em(tmp_path: Path, conclusion: str | None, own: str) -> None:
    """Czerwony `main` po własnym merge'u nie wracał do wątku, który scalał (#911, #971), a run commitu merge'a anuluje
    nowszy push na `main`, gdy czeka za trwającym (#1449: runy merge'ów #1439, #1418, #1434 anulowane po 2 min, czerwień
    przyszła z runu merge'a #1437), więc linia nie każe czekać na wynik runu commitu merge'a."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))
    if conclusion is not None:
        run = {"databaseId": 4242, "url": "https://github.com/o/r/actions/runs/4242", "conclusion": conclusion}
        (github.bin / "runs.json").write_text(json.dumps([run]), encoding="utf-8")

    merged = github.run("1")

    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert merged.stdout.splitlines()[-2:] == [
        f"CI MAIN | {merge_commit[:7]} | o merge'u rozstrzyga pierwszy nieanulowany run CI pushu na main, którego commit zawiera merge: {own}"
        " | obserwuj PR do zielonego main z tym merge'em albo do komentarza czerwonego main w PR",
        _last_line(merged),
    ]
    assert github.run_lists() == [["run", "list", "--workflow", "CI", "--event", "push", "--branch", "main", "--commit", merge_commit, "--json", "databaseId,url,conclusion"]]


@pytest.mark.parametrize(
    ("ci", "comments", "reason"),
    [
        (
            [_check_run("COMPLETED", "FAILURE")],
            [(PASS, "OWNER")],
            "CI: „Required CI status” FAILURE",
        ),
        (
            [_check_run("IN_PROGRESS", None)],
            [(PASS, "OWNER")],
            "CI: „Required CI status” IN_PROGRESS",
        ),
        (GREEN[:1], [(PASS, "OWNER")], "CI: run CI 4077 jeszcze trwa"),
        ([COMMIT_STATUS], [(PASS, "OWNER")], NOT_ACTIONS),
        ([_check_run("COMPLETED", "SUCCESS", workflow="")], [(PASS, "OWNER")], NOT_ACTIONS),
        (GREEN, [], NO_PASS),
        (GREEN, [("WERDYKT: PASS {old}", "OWNER")], NO_PASS),
        (GREEN, [(PASS, "NONE")], NO_PASS),
        (GREEN, [(PASS, "CONTRIBUTOR")], NO_PASS),
        (GREEN, [(PASS, "CONTRIBUTOR", "COMMENTED")], NO_PASS),
        (GREEN, [(PASS, "OWNER", "PENDING")], NO_PASS),
        (GREEN, [("Recenzja: WERDYKT: PASS {head}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head} — bez uwag", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {head7}", "OWNER")], NO_PASS),
        (GREEN, [("WERDYKT: PASS {upper}", "OWNER")], NO_PASS),
        (GREEN, [("**WERDYKT: PASS {head}**", "OWNER")], NO_PASS),
        (GREEN, [("## Werdykt niezależny: PASS", "OWNER")], NO_PASS),
        (GREEN, [("Wygląda dobrze.", "OWNER", "APPROVED")], NO_PASS),
        (GREEN, [(PASS, "OWNER"), ("WERDYKT: FAIL {head}", "MEMBER")], OBJECTION),
        ([_check_run("COMPLETED", "FAILURE")], [], f"CI: „Required CI status” FAILURE; {NO_PASS}"),
    ],
    ids=[
        "ci-czerwone",
        "ci-trwa",
        "ci-run-bez-wymaganego-checku-jeszcze-trwa",
        "ci-tylko-status-commitu",
        "ci-check-spoza-github-actions",
        "bez-werdyktu",
        "pass-dla-starszego-commitu",
        "pass-konta-bez-prawa-zapisu",
        "pass-kontrybutora",
        "pass-w-recenzji-kontrybutora",
        "pass-w-nieopublikowanej-recenzji",
        "pass-nie-w-pierwszej-linii",
        "pass-z-dopiskiem-w-pierwszej-linii",
        "pass-z-7-znakami-sha",
        "pass-z-sha-wielkimi-literami",
        "pass-w-markdownie",
        "pass-w-naglowku",
        "zatwierdzona-recenzja-bez-linii-werdyktu",
        "fail-po-pass",
        "wszystkie-przyczyny-naraz",
    ],
)
def test_bez_zielonego_ci_albo_werdyktu_pass_dla_head_pr_nie_jest_scalany(
    tmp_path: Path, ci: list[dict[str, str | None]], comments: list[tuple[str, ...]], reason: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head, statusCheckRollup=ci)
    for body, association, *state in comments:
        text = body.format(head=head, old=old, head7=head[:7], upper=head.upper())
        github.review(1, text, association, state=state[0]) if state else github.comment(1, text, association)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(short=head[:7], head=head)}"
    assert github.merges() == []


SAME_START = "2026-11-09T22:01:27Z"
REQUIRED_DONE = ("Required CI status", "COMPLETED", "SUCCESS")
GREEN_RUN = (("Plan CI", "COMPLETED", "SUCCESS"), ("pytest (Python 3.11, 15/22)", "COMPLETED", "SUCCESS"), REQUIRED_DONE)
RED_RUN = (
    ("Plan CI", "COMPLETED", "SUCCESS"),
    ("pytest (Python 3.11, 15/22)", "COMPLETED", "FAILURE"),
    ("Required CI status", "COMPLETED", "FAILURE"),
)
# Prawdziwy kształt trwającego runu (run ``main`` 42709423144): część zadań skończona, część w toku, a check
# ``Required CI status`` jeszcze nie istnieje, bo GitHub tworzy go dopiero po zadaniach z jego ``needs:``.
RUNNING_RUN = (("Plan CI", "COMPLETED", "SUCCESS"), ("pytest (Python 3.11, 15/22)", "IN_PROGRESS", None), ("Frontend", "QUEUED", None))


def _run(run: int, *jobs: tuple[str, str, str | None], started: str = SAME_START) -> list[dict[str, str | None]]:
    """Checki jednego runu workflow ``CI`` w rollupie: ``detailsUrl`` każdego niesie identyfikator runu i zadania."""

    return [
        _check_run(status, conclusion, name=name, url=f"https://github.com/o/r/actions/runs/{run}/job/{run}{index}", started=started)
        for index, (name, status, conclusion) in enumerate(jobs)
    ]


@pytest.mark.parametrize(
    ("rollup", "outcome"),
    [
        ([*_run(42701212234, *RED_RUN), *_run(42706832032, *RED_RUN), *_run(42707489817, *GREEN_RUN)], None),
        ([*_run(42707489817, *GREEN_RUN), *_run(42706832032, *RED_RUN), *_run(42701212234, *RED_RUN)], None),
        ([*_run(42701212234, *GREEN_RUN), *_run(42706832032, *RED_RUN)], "„Required CI status” FAILURE"),
        ([*_run(42706832032, *RED_RUN), *_run(42701212234, *GREEN_RUN)], "„Required CI status” FAILURE"),
        ([*_run(9999, *RED_RUN), *_run(10000, *GREEN_RUN)], None),
        ([*_run(42707489817, *GREEN_RUN, started="2026-11-09T22:30:00Z"), *_run(42709423144, *RUNNING_RUN)], "run CI 42709423144 jeszcze trwa"),
        (
            [*_run(42701212234, *RED_RUN), *_run(42707489817, *GREEN_RUN), *_run(42709423144, *RUNNING_RUN, started="2026-11-09T21:00:00Z")],
            "run CI 42709423144 jeszcze trwa",
        ),
        ([*_run(42707489817, *GREEN_RUN), *_run(42709423144, ("Plan CI", "COMPLETED", "SUCCESS"), ("Required CI status", "IN_PROGRESS", None))], "„Required CI status” IN_PROGRESS"),
        ([*_run(42707489817, ("pytest (Python 3.11, 15/22)", "IN_PROGRESS", None), REQUIRED_DONE)], "run CI 42707489817 jeszcze trwa"),
        (
            [*_run(42707489817, *GREEN_RUN), _check_run("COMPLETED", "SUCCESS", name="Frontend", url="https://github.com/o/r/runs/129482655837")],
            "check „Frontend” workflow „CI” bez identyfikatora runu w detailsUrl https://github.com/o/r/runs/129482655837",
        ),
        (
            [*_run(42707489817, *GREEN_RUN), _check_run("COMPLETED", "FAILURE", name="Lint skilli", workflow="Skille", url="https://example.com/x")],
            None,
        ),
    ],
    ids=[
        "stare-czerwone-po-zamknieciu-i-otwarciu-nowe-zielone-jak-1238",
        "nowy-zielony-run-przed-starymi-czerwonymi-w-rollupie",
        "stary-zielony-run-nowy-czerwony",
        "nowy-czerwony-run-przed-starym-zielonym-w-rollupie",
        "identyfikator-runu-porownany-jako-liczba-nie-napis",
        "nowy-run-w-toku-bez-required-po-zielonym-o-tym-samym-starcie",
        "nowy-run-w-toku-bez-required-po-czerwonym-i-zielonym-jak-1238-po-ponownym-otwarciu",
        "nowy-run-z-required-w-toku-po-zielonym",
        "ponowione-zadanie-najnowszego-runu-w-toku-obok-jego-zielonego-required",
        "check-ci-bez-identyfikatora-runu",
        "inny-workflow-nie-jest-runem-ci",
    ],
)
def test_gotowosc_ci_liczy_tylko_najnowszy_run_ci_na_head(tmp_path: Path, rollup: list[dict[str, str | None]], outcome: str | None) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, statusCheckRollup=rollup)
    github.comment(1, PASS.format(head=head))

    answered = github.run("1", "--bez-merge")

    if outcome is None:
        assert answered.returncode == 0, answered.stdout + answered.stderr
        assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main")
    else:
        assert answered.returncode == 1, answered.stdout + answered.stderr
        assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | CI: {outcome}"
    assert github.merges() == []


@pytest.mark.parametrize(
    ("kind", "objection"),
    [
        ("comment", "WERDYKT: FAIL {head}"),
        ("comment", "WERDYKT: FAIL {head}\n- krytyczne: brak testu"),
        ("comment", "\n\n  WERDYKT: FAIL {head}  \r\n"),
        ("COMMENTED", "WERDYKT: FAIL {head}"),
        ("CHANGES_REQUESTED", "Popraw nazwę funkcji."),
        ("CHANGES_REQUESTED", ""),
        ("comment", "WERDYKT: FAIL {head}\nZnaleziska: dwa Ważne, brak testu"),
        ("comment", "WERDYKT: FAIL {head}\nZnaleziska: 1 (Ważne 0, Drobne 1)"),
    ],
    ids=[
        "komentarz",
        "komentarz-ze-znaleziskami",
        "puste-linie-i-odstepy",
        "recenzja",
        "prosba-o-zmiany",
        "prosba-o-zmiany-bez-tresci",
        "fail-z-proza-w-drugiej-linii-jak-532",
        "fail-bez-waznych-poza-regulami-werdyktu",
    ],
)
def test_sprzeciw_zaufanego_konta_dla_head_po_pass_blokuje_merge(tmp_path: Path, kind: str, objection: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    github.comment(1, PASS.format(head=head))
    body = objection.format(head=head)
    github.comment(1, body) if kind == "comment" else github.review(1, body, state=kind)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {OBJECTION.format(short=head[:7], head=head)}"
    assert github.merges() == []


@pytest.mark.parametrize(
    "verdicts",
    [
        [("comment", PASS), ("comment", "WERDYKT: FAIL {old}")],
        [("comment", "WERDYKT: FAIL {head}"), ("comment", PASS)],
        [("COMMENTED", "WERDYKT: FAIL {head}"), ("comment", PASS)],
        [("comment", "WERDYKT: FAIL {head}"), ("COMMENTED", PASS)],
        [("comment", PASS), ("comment", "WERDYKT: FAIL {head}", "CONTRIBUTOR")],
        [("comment", PASS), ("COMMENTED", "")],
        [("comment", "WERDYKT: PASS {head}\r\n\r\nZnaleziska: 1 (Ważne 0, Drobne 1)\r\n- drobne: nazwa")],
        [("comment", "  WERDYKT: PASS {head}  \n  Znaleziska: 0 (Ważne 0, Drobne 0)  ")],
        [("CHANGES_REQUESTED", "Popraw nazwę funkcji."), ("comment", PASS)],
        [("comment", PASS), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.", "CONTRIBUTOR")],
        [("comment", PASS), ("PENDING", "WERDYKT: FAIL {head}")],
        [("comment", PASS), ("comment", "WERDYKT: FAIL {head7}")],
        [("comment", PASS), ("comment", "WERDYKT: FAIL {head} — brak testu")],
        [("comment", PASS), ("comment", "Werdykt: FAIL {head}")],
        [("comment", PASS), ("comment", "## Przegląd\n\nWERDYKT: FAIL {head}")],
        [("comment", "WERDYKT: PASS {head}\nZnaleziska: 0"), ("comment", PASS)],
        [("comment", "WERDYKT: PASS {old}\nZnaleziska: 0"), ("comment", PASS)],
    ],
    ids=[
        "fail-dla-starszego-commitu",
        "pass-po-fail",
        "pass-po-starszej-recenzji-z-fail",
        "pass-w-recenzji-po-fail",
        "fail-kontrybutora",
        "recenzja-bez-tresci",
        "pass-z-crlf",
        "pass-z-odstepami",
        "pass-po-prosbie-o-zmiany",
        "prosba-o-zmiany-kontrybutora",
        "nieopublikowana-recenzja-z-fail",
        "fail-ze-skroconym-sha-to-nie-werdykt",
        "fail-z-dopiskiem-to-nie-werdykt",
        "fail-z-malymi-literami-to-nie-werdykt",
        "fail-nie-w-pierwszej-linii-to-nie-werdykt",
        "pass-po-pass-poza-regulami-werdyktu",
        "pass-poza-regulami-dla-starszego-commitu",
    ],
)
def test_sprzeciw_dla_innego_commitu_starszy_niz_pass_bez_prawa_zapisu_albo_poza_kontraktem_nie_blokuje(
    tmp_path: Path, verdicts: list[tuple[str, ...]]
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    old = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    head = github.commit_on(old, {"kod/inne.py": "INNE: int = 2\n"}, "PR 1 po poprawce")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{head}:refs/pull/1/head")
    github.update(1, headRefOid=head)
    for kind, body, *association in verdicts:
        text = body.format(head=head, head7=head[:7], old=old)
        github.comment(1, text, *association) if kind == "comment" else github.review(1, text, *association, state=kind)

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")


BROKEN_PASS = "werdykt: PASS dla {short} nie przechodzi reguł --werdykt ({problems}); popraw plik werdyktu i opublikuj go przez tools/scal_pr.py 1 --werdykt PLIK"
NO_FINDINGS = "druga linia „{line}” to nie „Znaleziska: N (Ważne a, Drobne b)”"


@pytest.mark.parametrize(
    ("verdicts", "problems"),
    [
        ([("comment", "WERDYKT: PASS {head}\nZnaleziska: 0")], NO_FINDINGS.format(line="Znaleziska: 0")),
        ([("comment", "WERDYKT: PASS {head}\nZnaleziska: 1 (Drobne 1)")], NO_FINDINGS.format(line="Znaleziska: 1 (Drobne 1)")),
        ([("comment", "WERDYKT: PASS {head}")], NO_FINDINGS.format(line="")),
        ([("comment", "WERDYKT: PASS {head}\nZnaleziska: 1 (Ważne 1, Drobne 0)")], "PASS z Ważne 1: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"),
        ([("comment", "WERDYKT: PASS {head}\nZnaleziska: 4 (Ważne 0, Drobne 4)")], "Drobne 4: podaj najwyżej 3, najważniejsze"),
        ([("COMMENTED", "WERDYKT: PASS {head}\nZnaleziska: 0")], NO_FINDINGS.format(line="Znaleziska: 0")),
        ([("comment", PASS), ("comment", "WERDYKT: PASS {head}\nZnaleziska: 0")], NO_FINDINGS.format(line="Znaleziska: 0")),
        (
            [("comment", "WERDYKT: PASS {head}\nZnaleziska: 2 (Ważne 1, Drobne 0)")],
            "Znaleziska: 2, a Ważne 1 i Drobne 0 dają 1; PASS z Ważne 1: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych",
        ),
    ],
    ids=[
        "znaleziska-0-jak-994",
        "drobne-bez-waznych-jak-1004",
        "bez-drugiej-linii",
        "pass-z-waznym",
        "za-duzo-drobnych",
        "w-recenzji",
        "po-pass-w-postaci-werdyktu",
        "kilka-przyczyn",
    ],
)
def test_pass_dla_head_opublikowany_z_pominieciem_regul_werdyktu_nie_scala_a_odmowa_wskazuje_werdykt(
    tmp_path: Path, verdicts: list[tuple[str, str]], problems: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    for kind, body in verdicts:
        github.comment(1, body.format(head=head)) if kind == "comment" else github.review(1, body.format(head=head), state=kind)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {BROKEN_PASS.format(short=head[:7], problems=problems)}"
    assert github.merges() == []


@pytest.mark.parametrize(
    ("state", "draft", "fork", "reason"),
    [
        ("MERGED", False, False, "PR nie jest otwarty: MERGED"),
        ("OPEN", True, False, "PR jest szkicem"),
        ("OPEN", False, True, "PR z forka"),
    ],
)
def test_pr_zamkniety_szkic_albo_z_forka_nie_jest_scalany(
    tmp_path: Path, state: str, draft: bool, fork: bool, reason: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, state=state, isDraft=draft, isCrossRepository=fork)
    github.comment(1, PASS.format(head=head))

    answered = github.run("1")

    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason}"
    assert github.merges() == []


ALL_SECTIONS = "„## Why”, „## Summary”, „## Evidence”, „## Merge Danger”"


@pytest.mark.parametrize(
    ("body", "missing"),
    [
        ("", ALL_SECTIONS),
        ("## Why\n\nCel.\n\n## Co\n\n- zmiana\n", "„## Summary”, „## Evidence”, „## Merge Danger”"),
        (
            "## Why\n\n## What changed\n\n## Scope\n\n## Tradeoffs\n\n## Blast Radius\n\n## Verification\n",
            "„## Summary”, „## Evidence”, „## Merge Danger”",
        ),
        (BODY.replace("## Why", "## Dlaczego"), "„## Why”"),
        ("## Summary\n\n" + BODY.replace("## Summary\n\n", ""), "„## Summary”"),
        (BODY.replace("## Evidence", "### Evidence"), "„## Evidence”"),
        (BODY.replace("## Evidence", "Dowody są w sekcji ## Evidence"), "„## Evidence”"),
        ("\r\n".join(f"  {line}  " for line in BODY.splitlines()), ""),
    ],
    ids=["pusty", "wlasne-sekcje", "sekcje-innego-wzoru", "przetlumaczony-naglowek", "zla-kolejnosc", "naglowek-3-stopnia", "naglowek-w-zdaniu", "odstepy-i-crlf"],
)
def test_pr_bez_naglowka_wzoru_skilla_pr_w_jego_kolejnosci_nie_jest_scalany(tmp_path: Path, body: str, missing: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=body)
    github.comment(1, PASS.format(head=head))

    answered = github.run("1", "--bez-merge")

    if missing:
        assert answered.returncode == 1, answered.stdout + answered.stderr
        assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | opis: brak {missing} w kolejności wzoru .agents/skills/pr/SKILL.md"
    else:
        assert answered.returncode == 0, answered.stdout + answered.stderr


def test_brak_naglowka_wzoru_jest_w_jednej_odmowie_z_czerwonym_ci_i_brakiem_werdyktu(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body="", statusCheckRollup=[_check_run("COMPLETED", "FAILURE")])

    answered = github.run("1", "--bez-merge")

    assert _last_line(answered) == (
        f"SCAL ODMOWA | #1 {head[:7]} | CI: „Required CI status” FAILURE; "
        f"opis: brak {ALL_SECTIONS} w kolejności wzoru .agents/skills/pr/SKILL.md; {NO_PASS.format(head=head)}"
    )


def test_naglowek_dopisany_do_wzoru_skilla_pr_od_razu_obowiazuje(tmp_path: Path) -> None:
    template = TEMPLATE.read_text(encoding="utf-8").replace("## Merge Danger\n", "## Merge Danger\n\n## Rollback\n", 1)
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, ".agents/skills/pr/SKILL.md": template})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))

    refused = github.run("1", "--bez-merge")
    github.update(1, body=f"{BODY}\n## Rollback\n\nRevert.\n")
    accepted = github.run("1", "--bez-merge")

    assert _last_line(refused) == f"SCAL ODMOWA | #1 {head[:7]} | opis: brak „## Rollback” w kolejności wzoru .agents/skills/pr/SKILL.md"
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


@pytest.mark.parametrize(
    ("main_files", "pull_files", "reason"),
    [
        ({"kod/nazwa.py": 'NAZWA = "z main"\n'}, {"kod/nazwa.py": 'NAZWA = "z PR"\n'}, "Konflikt z main {main}, zaktualizuj PR z bazy i rozwiąż: kod/nazwa.py"),
        (
            {"pyproject.toml": PYPROJECT.replace("[tool.mypy]", '[tool.ruff.lint]\nextend-select = ["B905"]\n\n[tool.mypy]')},
            {"kod/pary.py": "PARY = list(zip([1], [2]))\n"},
            "Na scaleniu z main {main} pada, zaktualizuj PR z bazy i popraw: ruff",
        ),
    ],
    ids=["konflikt", "regula-ruff-wlaczona-na-main-po-ci-pr"],
)
def test_pr_ktory_nie_scala_sie_czysto_z_biezacym_main_nie_jest_scalany(
    tmp_path: Path, main_files: dict[str, str], pull_files: dict[str, str], reason: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "kod/nazwa.py": 'NAZWA = "pierwsza"\n'})
    head = github.open_pull(1, pull_files)
    github.comment(1, PASS.format(head=head))
    main = github.push_main(main_files)

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {reason.format(main=main[:7])}"
    assert github.merges() == []


# Test scalenia: test sumy z PR i zmiana sumy na main są zielone osobno, a po scaleniu ``abs`` psuje sumę ujemnych.
WITH_PYTEST = PYPROJECT + '\n[tool.pytest.ini_options]\npythonpath = ["."]\n'
SUM_TEST = "from kod import suma\n\n\ndef test_suma_dodatnich() -> None:\n    assert suma(2, 2) == 4\n"
NEGATIVE_TEST = "\n\ndef test_suma_ujemnych() -> None:\n    assert suma(-1, -1) == -2\n"
# Id z parametrem ze spacją: wynik testu scalenia czyta junit, a nie linię ``FAILED`` wyjścia, którą spacja dzieli.
DESCRIBED_TEST = '\n\nimport pytest\n\n\n@pytest.mark.parametrize("opis", ["dwa i dwa"])\ndef test_suma_opisana(opis: str) -> None:\n    assert suma(-2, -2) == -4\n'
SLOW_TEST = "\n\ndef test_suma_ujemnych() -> None:\n    import time\n\n    time.sleep(60)\n"
ZERO_TEST = "\n\ndef test_zero() -> None:\n    from kod.pomoc import ZERO\n\n    assert ZERO == 0\n"
HELPER = "ZERO: int = 0\n"
HELPED_SUM = "from kod.pomoc import ZERO\n\n\ndef suma(a: int, b: int) -> int:\n    return a + b + ZERO\n"
ABS_SUM = "from kod.pomoc import ZERO\n\n\ndef suma(a: int, b: int) -> int:\n    return abs(a) + abs(b) + ZERO\n"
SAME_SUM = "from kod.pomoc import ZERO\n\n\ndef suma(a: int, b: int) -> int:\n    return ZERO + b + a\n"
BROKEN_SUM = "from kod.pomoc import ZERO\n\n\ndef suma(a: int, b: int) -> int:\n    return a + b + 1 + ZERO\n"
SUM_TEST_FILE = "tests/test_suma.py"
NEGATIVE_TEST_FILE = "tests/test_suma_ujemnych.py"


def _merge_test_github(
    tmp_path: Path, pull_files: dict[str, str], main_files: dict[str, str], ci_seconds: dict[str, float] | None
) -> tuple[MergeGitHub, str, str]:
    """PR 1 z PASS, który zapisuje ``pull_files`` obok testu sumy, ``main`` z ``main_files`` po jego merge-base i czasy CI
    plików testów, jakie ``tools/szybko.py`` pobrał dziś do ``.git/czasy-ci`` (``None``: bez czasów); HEAD PR i ``main``."""

    github = MergeGitHub(tmp_path, {"pyproject.toml": WITH_PYTEST, "kod/__init__.py": HELPED_SUM, "kod/pomoc.py": HELPER, SUM_TEST_FILE: SUM_TEST})
    head = github.open_pull(1, pull_files)
    github.comment(1, PASS.format(head=head))
    main = github.push_main(main_files)
    if ci_seconds is not None:
        observed = {"run": 7, "proba": 1, "zadanie": "pytest (Python 3.14, Linux, 1/2)", "status": "ok"}
        keys = {f"pytest:{test}": [{**observed, "s": s}] for test, s in ci_seconds.items()}
        times = {"wersja": 1, "runy": [{"run": 7, "proba": 1, "sha": "0" * 40, "zdarzenie": "push"}], "tory": {czasy_ci.TOR_LOKALNY: keys}}
        (github.checkout / ".git" / "czasy-ci").mkdir()
        (github.checkout / ".git" / "czasy-ci" / "7.json").write_text(json.dumps(times), encoding="utf-8")
        (github.checkout / ".git" / "czasy-ci" / "pobrane").write_text("", encoding="utf-8")
    return github, head, main


def test_test_dotkniety_zmiana_pr_i_zmiana_main_od_merge_base_biegnie_na_scaleniu_przed_merge(tmp_path: Path) -> None:
    github, head, main = _merge_test_github(tmp_path, {SUM_TEST_FILE: SUM_TEST + NEGATIVE_TEST}, {"kod/__init__.py": SAME_SUM}, {SUM_TEST_FILE: 1.0})

    merged = github.run("1")

    assert merged.returncode == 0, merged.stdout + merged.stderr
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert re.fullmatch(
        rf"SCAL OK \| #1 {head[:7]} \| scalony do main jako {merge_commit[:7]} \(baza {main[:7]}\)"
        rf" \| test scalenia: {SUM_TEST_FILE} przechodzą \(\d+ s\) \| sprzątanie: SPRZĄTANIE OK \| 0 usuniętych",
        _last_line(merged),
    )


def test_test_ktory_pada_juz_na_samym_main_nie_blokuje_merge_pr_i_stoi_w_linii_scal_ok(tmp_path: Path) -> None:
    github, head, main = _merge_test_github(tmp_path, {SUM_TEST_FILE: SUM_TEST + ZERO_TEST}, {"kod/__init__.py": BROKEN_SUM}, {SUM_TEST_FILE: 1.0})

    merged = github.run("1")

    assert merged.returncode == 0, merged.stdout + merged.stderr
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert re.fullmatch(
        rf"SCAL OK \| #1 {head[:7]} \| scalony do main jako {merge_commit[:7]} \(baza {main[:7]}\)"
        rf" \| test scalenia: {SUM_TEST_FILE} bez porażek przez PR, a na samym main {main[:7]} pada już:"
        rf" {SUM_TEST_FILE}::test_suma_dodatnich \(\d+ s\) \| sprzątanie: SPRZĄTANIE OK \| 0 usuniętych",
        _last_line(merged),
    )


@pytest.mark.parametrize(
    ("pull_files", "main_sum", "replaced", "reason"),
    [
        # Nowy plik testów PR: graf scalonego drzewa go zna, a checkout ``main``, z którego biegnie narzędzie, nie.
        ({NEGATIVE_TEST_FILE: SUM_TEST.replace("dodatnich", "zera") + NEGATIVE_TEST}, ABS_SUM, None, f"pada: {NEGATIVE_TEST_FILE}::test_suma_ujemnych"),
        # Na samym main pada test sumy, a na scaleniu jeszcze test PR: odmowa wymienia oba, a obwinia tylko test PR.
        (
            {SUM_TEST_FILE: SUM_TEST + NEGATIVE_TEST},
            ABS_SUM.replace("+ ZERO", "+ 1 + ZERO"),
            None,
            f"pada: {SUM_TEST_FILE}::test_suma_ujemnych (na samym main {{main}} pada też: {SUM_TEST_FILE}::test_suma_dodatnich)",
        ),
        ({SUM_TEST_FILE: SUM_TEST + DESCRIBED_TEST}, ABS_SUM, None, f"pada: {SUM_TEST_FILE}::test_suma_opisana[dwa i dwa]"),
        # Błąd kolekcji nowego pliku testów nie ma id testu, więc odmowa nazywa plik.
        ({NEGATIVE_TEST_FILE: "from kod import suma\n\nassert suma(-1, -1) == -2\n"}, ABS_SUM, None, f"pada: {NEGATIVE_TEST_FILE}"),
        ({SUM_TEST_FILE: SUM_TEST + SLOW_TEST}, ABS_SUM, ("MERGE_TEST_TIMEOUT_S = 300", "MERGE_TEST_TIMEOUT_S = 5"), f"bez wyniku po 5 s: {SUM_TEST_FILE}"),
        (
            {SUM_TEST_FILE: SUM_TEST + NEGATIVE_TEST},
            ABS_SUM,
            ('"-rfE"', '"--nieznana-opcja"'),
            # Nazwę programu w błędzie argparse daje wersja Pythona: ``__main__.py`` do 3.13, ``python -m pytest`` od 3.14.
            "pada: pytest kod 4: {prog}: error: unrecognized arguments: --nieznana-opcja",
        ),
    ],
    ids=["test-pada", "test-pada-a-inny-pada-juz-na-main", "test-z-parametrem-ze-spacja-pada", "blad-kolekcji", "test-ponad-limit-czasu", "pytest-nie-startuje"],
)
def test_pr_ktorego_test_pada_na_scaleniu_z_main_choc_oba_byly_zielone_nie_jest_scalany(
    tmp_path: Path, pull_files: dict[str, str], main_sum: str, replaced: tuple[str, str] | None, reason: str
) -> None:
    github, head, main = _merge_test_github(tmp_path, pull_files, {"kod/__init__.py": main_sum}, {SUM_TEST_FILE: 1.0})
    if replaced is not None:
        tool = github.checkout / "tools" / "lib" / "testy_scalenia.py"
        tool.write_text(tool.read_text(encoding="utf-8").replace(*replaced), encoding="utf-8")

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    expected = re.escape(f"SCAL ODMOWA | #1 {head[:7]} | test scalenia z main {main[:7]} {reason.format(main=main[:7], prog=chr(0))}")
    assert re.fullmatch(expected.replace(re.escape(chr(0)), ".+"), _last_line(answered)), _last_line(answered)
    assert github.merges() == []


@pytest.mark.parametrize(
    ("main_files", "ci_seconds", "note"),
    [
        ({"kod/inne.py": "INNE: int = 1\n"}, {SUM_TEST_FILE: 1.0}, ""),
        ({"kod/pomoc.py": "ZERO: int = 0  # suma importuje pomoc, a test sumę: test jest 2 kroki od zmiany main\n"}, {SUM_TEST_FILE: 1.0}, ""),
        ({"kod/__init__.py": ABS_SUM}, {SUM_TEST_FILE: 500.0}, " | test scalenia pominięty: ~500 s w CI ponad limit 180 s, plików testów: 1"),
        # Plik testów bez pomiaru waży medianę zmierzonych, tu 500 s.
        ({"kod/__init__.py": ABS_SUM}, {"tests/test_inny.py": 500.0}, " | test scalenia pominięty: ~500 s w CI ponad limit 180 s, plików testów: 1"),
        (
            {"kod/__init__.py": ABS_SUM, "pyproject.toml": WITH_PYTEST + "# reguła wyboru testów\n"},
            {SUM_TEST_FILE: 1.0},
            " | test scalenia pominięty: zmiana pyproject.toml dotyczy każdego testu",
        ),
        ({"kod/__init__.py": ABS_SUM}, None, " | test scalenia pominięty: brak czasów CI (pobranie czasy-ci z GitHuba: "),
    ],
    ids=[
        "main-nie-dotyka-testow-pr",
        "main-zmienia-plik-dalej-niz-krok-od-testu",
        "testy-ponad-limit-czasu-ci",
        "plik-bez-pomiaru-wazy-mediane",
        "zmiana-pliku-reguly-wyboru-testow",
        "bez-czasow-ci",
    ],
)
def test_test_scalenia_nie_biegnie_bez_wspolnego_testu_ponad_limit_czasu_ci_i_przy_zmianie_reguly_wyboru(
    tmp_path: Path, main_files: dict[str, str], ci_seconds: dict[str, float] | None, note: str
) -> None:
    github, head, main = _merge_test_github(tmp_path, {SUM_TEST_FILE: SUM_TEST + NEGATIVE_TEST}, main_files, ci_seconds)

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    line = f"SCAL OK | #1 {head[:7]} | gotowy do merge'a z main {main[:7]}, bez merge'a (--bez-merge){note}"
    # Bez czasów CI linia kończy się przyczyną z ``gh``, której treść należy do atrapy.
    shown = _last_line(answered) if ci_seconds is not None else _last_line(answered)[: len(line)]
    assert shown == line
    assert "== test scalenia" not in answered.stdout


def test_main_przesuniety_w_trakcie_sprawdzania_zatrzymuje_merge(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    moved = github.commit_on(github.start, {"kod/nowe.py": "NOWE: int = 1\n"}, "main w trakcie")
    pushes_main = (
        "import subprocess\n\n"
        f"subprocess.run(['git', '-C', {str(github.checkout)!r}, 'push', '--quiet', 'origin', '{moved}:refs/heads/main'], check=True)\n"
        "print('CI LOKALNIE OK')\n"
    )
    head = github.open_pull(1, {"tools/ci_lokalnie.py": pushes_main})
    github.comment(1, PASS.format(head=head))

    answered = github.run("1")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | main zmienił się w trakcie sprawdzania, uruchom ponownie"
    assert github.merges() == []


def test_baza_przesunieta_z_innego_klonu_przed_sprawdzeniem_jest_baza_scalenia(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))
    other = tmp_path / "inny-klon"
    git(tmp_path, "clone", "--quiet", str(tmp_path / "origin.git"), str(other))
    (other / "kod" / "nowe.py").write_text("NOWE: int = 1\n", encoding="utf-8")
    moved = commit(other, "main z innego klonu")
    git(other, "push", "--quiet", "origin", "HEAD:main")

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert f"| scalony do main jako {git(github.origin, 'rev-parse', 'refs/heads/main')[:7]} (baza {moved[:7]}) |" in _last_line(answered)
    assert len(github.merges()) == 1


def test_po_merge_zamyka_otwarte_issues_z_naprawia_z_komentarzem_a_bez_merge_tylko_je_podaje(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3, 4, 6, 7)
    github.open_issues(5, state="closed")
    seven = {"number": 7, "repository": {"name": "maximiseart-dad", "owner": {"login": "MAXIMISEARTAI"}}}
    four_elsewhere = {"number": 4, "repository": {"name": "repo", "owner": {"login": "inny"}}}
    github.update(1, body=opisy_pr.SCALENIE["zamyka"], closingIssuesReferences=[seven, four_elsewhere])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    closed_before_merge = github.closed()
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("bez merge'a (--bez-merge) | po merge'u zamknie: #3, #4")
    assert closed_before_merge == []
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged).endswith(f"jako {merge_commit[:7]} (baza {github.start[:7]}) | zamknięte: #3, #4 | sprzątanie: SPRZĄTANIE OK | 0 usuniętych")
    comment = f"Naprawione przez #1, scalone jako {merge_commit}."
    assert github.closed() == [["issue", "close", str(n), "--repo", opisy_pr.REPO, "--comment", comment] for n in (3, 4)]


def test_merge_do_galezi_innej_niz_domyslna_niczego_nie_zamyka_ani_nie_renderuje_opisu(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = _repo_view("trunk")
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3, 4)
    github.update(1, body=opisy_pr.SCALENIE["dwa"])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert _last_line(checked).endswith("bez merge'a (--bez-merge) | bez zamykania „Naprawia”: baza main to nie trunk")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert " | bez zamykania „Naprawia”: baza main to nie trunk | " in _last_line(merged)
    assert len(github.merges()) == 1
    assert github.closed() == []
    assert github.renders() == []


@pytest.mark.parametrize("body", [opisy_pr.wzor("Closes #3"), opisy_pr.wzor("Ten PR\nnaprawia #3")], ids=["closes", "naprawia-mala-litera"])
def test_pr_bez_slowa_naprawia_nie_pyta_o_domyslna_galaz_ani_nie_renderuje_opisu(tmp_path: Path, body: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = _repo_view("trunk")
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=body)
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert _last_line(checked).endswith("bez merge'a (--bez-merge)")
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert f"jako {merge_commit[:7]} (baza {github.start[:7]}) | sprzątanie: SPRZĄTANIE OK" in _last_line(merged)
    assert github.repo_views() == []
    assert github.renders() == []


@pytest.mark.parametrize("answer", ["gh: HTTP 502", "", "{}"], ids=["blad-http", "pusta-odpowiedz", "bez-defaultBranchRef"])
def test_bez_domyslnej_galezi_od_githuba_merge_sie_odbywa_a_issues_zostaja_otwarte_z_ostrzezeniem(
    tmp_path: Path, answer: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.repo_view = answer
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3)
    github.update(1, body=opisy_pr.SCALENIE["jedno"])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("(--bez-merge) | UWAGA: GitHub nie podał domyślnej gałęzi, nie sprawdzono „Naprawia”")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    warning = "UWAGA: GitHub nie podał domyślnej gałęzi, nie zamknięto issues z „Naprawia”, zamknij je ręcznie"
    assert f" | {warning} | " in _last_line(merged)
    assert "Traceback" not in merged.stderr
    assert len(github.merges()) == 1
    assert github.closed() == []


@pytest.mark.parametrize("answer", ["gh: HTTP 502", "\n", "zawiesza"], ids=["blad-http", "pusta-odpowiedz", "gh-po-czasie"])
def test_bez_html_opisu_od_githuba_merge_sie_odbywa_a_issues_zostaja_otwarte_z_ostrzezeniem(tmp_path: Path, answer: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
    github.open_issues(3)
    github.markdown[opisy_pr.SCALENIE["jedno"]] = answer
    github.update(1, body=opisy_pr.SCALENIE["jedno"])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    merged = github.run("1")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert _last_line(checked).endswith("(--bez-merge) | UWAGA: GitHub nie wyrenderował opisu PR, nie sprawdzono „Naprawia”")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    warning = "UWAGA: GitHub nie wyrenderował opisu PR, nie zamknięto issues z „Naprawia”, zamknij je ręcznie"
    assert f" | {warning} | " in _last_line(merged)
    assert "Traceback" not in merged.stderr
    assert len(github.merges()) == 1
    assert github.closed() == []


def test_porazka_zamykania_issue_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
    github.open_issues(3)
    github.answer_issue(10, answer="")
    github.answer_issue(11, answer="{}")
    github.answer_issue(12, answer="[]")
    github.answer_issue(13, answer="zawiesza")
    github.update(1, body=opisy_pr.SCALENIE["porazki"])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    answered = github.run("1")

    failed = "#14, #10, #11, #12, #13"
    assert _last_line(checked).endswith(f" | po merge'u zamknie: #3 | UWAGA: nie sprawdzono {failed}")
    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert f" | zamknięte: #3 | UWAGA: nie zamknięto {failed}, zamknij ręcznie | " in _last_line(answered)
    assert len(github.merges()) == 1


@pytest.mark.parametrize("after_merge", ["brak", "błąd"], ids=["github-bez-commitu-merge", "gh-pr-view-z-bledem"])
def test_bez_commitu_merge_od_githuba_issues_zostaja_otwarte_z_ostrzezeniem(tmp_path: Path, after_merge: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.open_issues(3)
    github.open_issues(5, state="closed")
    github.update(1, body=opisy_pr.SCALENIE["bez-commitu-merge"], poMergeu=after_merge)
    github.comment(1, PASS.format(head=head))

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    warning = "UWAGA: GitHub nie podał commitu merge'a, nie zamknięto #3, #15, zamknij ręcznie"
    assert f"| scalony do main jako ? (baza {github.start[:7]}) | {warning} | " in _last_line(answered)
    assert len(github.merges()) == 1
    assert github.closed() == []


@pytest.mark.parametrize(("body", "fixes"), [case[1:] for case in opisy_pr.PRZYPADKI], ids=[case[0] for case in opisy_pr.PRZYPADKI])
def test_naprawia_wskazuje_issues_tego_repo_tylko_na_poczatku_linii_tekstu_ktory_github_pokazuje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, fixes: tuple[int, ...]
) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert naprawia.fixed_issues(body, opisy_pr.REPO) == fixes


def test_naprawia_wskazuje_issues_tego_repo_bez_wzgledu_na_wielkosc_liter_jego_nazwy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert naprawia.fixed_issues(opisy_pr.SCALENIE["dwa"], opisy_pr.REPO.swapcase()) == (3, 4)


@pytest.mark.parametrize(("number", "fixes"), opisy_pr.PRAWDZIWE.items(), ids=[f"pr-{number}" for number in opisy_pr.PRAWDZIWE])
def test_opisy_scalonych_pr_wskazuja_issues_ktore_github_zostawil_otwarte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int, fixes: tuple[int, ...]
) -> None:
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path)}{os.pathsep}{os.environ['PATH']}")

    assert naprawia.fixed_issues(opisy_pr.real_body(number), opisy_pr.REPO) == fixes


def test_kazdy_opis_testow_ma_html_z_renderera_githuba() -> None:
    assert sorted(opisy_pr.rendered()) == sorted(set(opisy_pr.bodies())), "odśwież: .venv/bin/python tests/fixtures/opisy_pr.py"


def test_sprzatanie_po_czasie_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    hangs = "import time\n\ntime.sleep(600)\n"
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": hangs})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    tool = github.checkout / "tools" / "scal_pr.py"
    tool.write_text(tool.read_text(encoding="utf-8").replace("CLEANUP_TIMEOUT_S = 300", "CLEANUP_TIMEOUT_S = 1"), encoding="utf-8")
    github.comment(1, PASS.format(head=head))

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).endswith("| UWAGA: sprzątanie przerwane po 1 s, uruchom je ponownie")
    assert len(github.merges()) == 1



@pytest.mark.parametrize(
    "mutations",
    [
        [],
        [_check_run("IN_PROGRESS", None, name="Change mutations (1/3)", workflow="Mutacje nocne", url="https://github.com/o/r/actions/runs/4100/job/3")],
        [_check_run("COMPLETED", "FAILURE", name="Change mutations (1/3)")],
    ],
    ids=["bez-checku", "w-toku", "przezyte"],
)
def test_gotowy_pr_nie_czeka_na_mutacje_zmiany_ani_linie_mutacja_bo_mutacje_biegna_noca_na_main(
    tmp_path: Path, mutations: list[dict[str, str | None]]
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, statusCheckRollup=[*GREEN, *mutations])
    github.comment(1, PASS.format(head=head))

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")


# ``tools/skille_dla_zmiany.py`` atrapa: skill z pliku ``skille.txt`` drzewa, w którym leży skrypt (jak prawdziwe narzędzie,
# które szuka korzenia od ``__file__``, więc skrypt z checkoutu zamiast kopii HEAD PR czytałby ``skille.txt`` checkoutu), i pliki
# zmiany od bazy z argumentu.
SKILLS_FOR_CHANGE = """\
import pathlib, subprocess, sys

changed = subprocess.run(["git", "diff", "--name-only", sys.argv[1], "HEAD"], capture_output=True, text=True, check=True).stdout.split()
skill = (pathlib.Path(__file__).resolve().parents[1] / "skille.txt").read_text().strip()
print(f"{skill}: {', '.join(changed)}")
print(f"SKILLE VERIFY: {skill}")
"""


def _lines(answered: subprocess.CompletedProcess[str], prefix: str) -> list[str]:
    return [line for line in answered.stdout.splitlines() if line.startswith(prefix)]


def test_przeglad_podaje_merge_base_zmiane_skille_z_head_pr_i_poprzednie_werdykty_z_poleceniem_diffu_kolejnej_rundy(
    tmp_path: Path,
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "skille.txt": "verify-main\n", "tools/skille_dla_zmiany.py": SKILLS_FOR_CHANGE})
    reviewed = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n", "skille.txt": "verify-pr\n"})
    main = github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})
    github.comment(1, f"WERDYKT: FAIL {reviewed}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n- Ważne: brak testu")
    github.comment(1, f"Poprawione w {reviewed[:7]}.")
    github.comment(1, f"WERDYKT: PASS {reviewed}\nZnaleziska: 0 (Ważne 0, Drobne 0)", association="NONE")
    github.review(1, "Popraw.", state="CHANGES_REQUESTED")
    github.review(1, f"WERDYKT: PASS {reviewed}\nZnaleziska: 0 (Ważne 0, Drobne 0)", state="PENDING")
    head = github.push_pull(1, {"kod/inne.py": "INNE: int = 2\n"})
    comments, reviews = github.pulls["1"]["comments"], github.pulls["1"]["reviews"]
    assert isinstance(comments, list) and isinstance(reviews, list)
    fail, review = comments[0], reviews[0]

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert answered.stdout.splitlines()[0] == f"PRZEGLĄD | #1 PR 1 | HEAD {head} | baza main {main} | merge-base {github.start}"
    assert f"ZMIANA | git diff --stat {github.start} {head}\n" in answered.stdout
    assert " 2 files changed, 2 insertions(+), 1 deletion(-)\n" in answered.stdout
    assert "PLIKI | 2\nkod/inne.py\nskille.txt\n" in answered.stdout
    assert f"SKILLE | tools/skille_dla_zmiany.py {github.start} na HEAD PR\nverify-pr: kod/inne.py, skille.txt\nSKILLE VERIFY: verify-pr\n" in answered.stdout
    assert _lines(answered, "WERDYKT |") == [
        f"WERDYKT | {fail['createdAt']} recenzent | inny commit | WERDYKT: FAIL {reviewed} | Znaleziska: 1 (Ważne 1, Drobne 0)",
        f"WERDYKT | {review['submittedAt']} recenzent | recenzja CHANGES_REQUESTED | Popraw.",
    ]
    assert _lines(answered, "RUNDA |") == [f"RUNDA | rund z FAIL: 1, ostatni werdykt FAIL dla {reviewed[:7]}; zmiana od niego: git diff {reviewed} {head}"]
    assert _last_line(answered) == f"PRZEGLĄD OK | #1 {head[:7]}"
    assert github.published() == []
    assert github.merges() == []


def test_przeglad_po_pass_dla_head_mowi_ze_werdykt_dotyczy_tego_head_a_rundy_z_fail_licza_tylko_fail(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "skille.txt": "verify-a\n", "tools/skille_dla_zmiany.py": SKILLS_FOR_CHANGE})
    reviewed = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: FAIL {reviewed}\nZnaleziska: 1 (Ważne 1, Drobne 0)")
    head = github.push_pull(1, {"kod/inne.py": "INNE: int = 2\n"})
    github.comment(1, f"WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)")

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert [line.split(" | ", 2)[2] for line in _lines(answered, "WERDYKT |")] == [
        f"inny commit | WERDYKT: FAIL {reviewed} | Znaleziska: 1 (Ważne 1, Drobne 0)",
        f"HEAD | WERDYKT: PASS {head} | Znaleziska: 0 (Ważne 0, Drobne 0)",
    ]
    assert _lines(answered, "RUNDA |") == [f"RUNDA | rund z FAIL: 1, ostatni werdykt PASS dla {head[:7]}, czyli dla tego HEAD"]


OTHER_RUN = "https://github.com/o/r/actions/runs/4000/job/2"
PASSED = "polecenia z linii LICZY CI przeszły, ich logów nie przeszukuj"
UNPROVEN = "polecenia z linii LICZY CI nie są dowiedzione, czytaj tylko logi padłych zadań: gh run view 4077 --log-failed"


@pytest.mark.parametrize(
    ("ci", "line"),
    [
        (GREEN, f"success na HEAD {{head}} | {PASSED}"),
        (
            [
                *GREEN,
                _check_run("IN_PROGRESS", None, name="Verify Centrum na Windowsie", workflow="Verify", url=OTHER_RUN),
                _check_run("COMPLETED", "FAILURE", name="Lint skilli", workflow="Skille", url=OTHER_RUN),
                _check_run("COMPLETED", "SKIPPED", name="Notka", workflow="Skille", url=OTHER_RUN),
            ],
            f"success na HEAD {{head}} | {PASSED} | inne workflowy, na które czeka gotowość: w toku: Verify Centrum na Windowsie; padłe: Lint skilli",
        ),
        (
            [_check_run("COMPLETED", "SUCCESS", name="Ruff, mypy"), _check_run("IN_PROGRESS", None)],
            "pending na HEAD {head} (w toku: 1) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [_check_run("QUEUED", None, name="Plan CI"), _check_run("IN_PROGRESS", None, name="Frontend")],
            "pending na HEAD {head} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [_check_run("IN_PROGRESS", None, name="Frontend"), _check_run("COMPLETED", "FAILURE", name="pytest (Python 3.11, 1/2)")],
            "pending na HEAD {head} (w toku: 1; padłe zadania: pytest (Python 3.11, 1/2)) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [
                _check_run("COMPLETED", "FAILURE", name="pytest (Python 3.11, 1/2)"),
                _check_run("COMPLETED", "TIMED_OUT", name="Mutation checks 2"),
                _check_run("COMPLETED", "SUCCESS", name="Ruff, mypy"),
                _check_run("COMPLETED", "SKIPPED", name="Frontend"),
                _check_run("COMPLETED", "FAILURE", name="Verify Centrum na Windowsie", workflow="Verify", url=OTHER_RUN),
                _check_run("COMPLETED", "FAILURE"),
            ],
            f"failure na HEAD {{head}} | padłe zadania: Mutation checks 2, pytest (Python 3.11, 1/2) | {UNPROVEN}",
        ),
        (
            [_check_run("COMPLETED", "FAILURE", name="Plan CI", url=OTHER_RUN), _check_run("COMPLETED", "FAILURE")],
            f"failure na HEAD {{head}} | bez padłego zadania, przyczynę podaje log „Required CI status” | {UNPROVEN}",
        ),
        ([COMMIT_STATUS], "brak na HEAD {head} | CI nie biegło na tym HEAD: jeszcze nie wystartowało po pushu albo PR ma konflikt z bazą"),
        (
            [*_run(4000, ("pytest (Python 3.11, 1/2)", "COMPLETED", "FAILURE"), RED_RUN[-1]), *_run(4077, ("pytest (Python 3.11, 1/2)", "COMPLETED", "SUCCESS"), REQUIRED_DONE)],
            f"success na HEAD {{head}} | {PASSED}",
        ),
        (
            [*_run(4000, ("Ruff, mypy", "COMPLETED", "SUCCESS"), REQUIRED_DONE), *_run(4077, ("Ruff, mypy", "COMPLETED", "FAILURE"), RED_RUN[-1])],
            f"failure na HEAD {{head}} | padłe zadania: Ruff, mypy | {UNPROVEN}",
        ),
        (
            [*_run(4000, ("Plan CI", "COMPLETED", "FAILURE"), RED_RUN[-1]), *_run(4077, *RUNNING_RUN)],
            "pending na HEAD {head} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*_run(3000, *RED_RUN), *_run(4000, *GREEN_RUN), *_run(4077, *RUNNING_RUN)],
            "pending na HEAD {head} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            _run(4077, ("Plan CI", "COMPLETED", "SUCCESS"), ("Frontend", "COMPLETED", "SUCCESS")),
            "pending na HEAD {head} (w toku: 0) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*_run(4077, ("Frontend", "IN_PROGRESS", None), REQUIRED_DONE)],
            "pending na HEAD {head} (w toku: 1) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*GREEN, _check_run("COMPLETED", "SUCCESS", name="Frontend", url="https://github.com/o/r/runs/129482655837")],
            "nieznany na HEAD {head} | check „Frontend” workflow „CI” bez identyfikatora runu w detailsUrl "
            "https://github.com/o/r/runs/129482655837 | polecenia z linii LICZY CI nie są dowiedzione",
        ),
    ],
    ids=[
        "zielony",
        "zielony-a-inny-workflow-w-toku-albo-padl",
        "w-toku",
        "w-toku-przed-required",
        "w-toku-z-padlym-zadaniem",
        "czerwony-z-padlymi-zadaniami-jego-runu",
        "czerwony-bez-padlego-zadania",
        "tylko-status-commitu",
        "stary-run-czerwony-nowy-zielony",
        "stary-run-zielony-nowy-czerwony",
        "stary-run-czerwony-nowy-w-toku-bez-required",
        "stare-runy-czerwony-i-zielony-nowy-w-toku-bez-required-jak-1238-po-ponownym-otwarciu",
        "run-po-skonczonych-zadaniach-jeszcze-bez-required",
        "ponowione-zadanie-najnowszego-runu-w-toku-obok-jego-zielonego-required",
        "check-ci-bez-identyfikatora-runu",
    ],
)
def test_przeglad_podaje_stan_required_ci_status_na_head_i_padle_zadania_jego_runu(
    tmp_path: Path, ci: list[dict[str, str | None]], line: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, statusCheckRollup=ci)

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _lines(answered, "CI |") == [f"CI | Required CI status {line.format(head=head)}"]


def test_przeglad_oznacza_pass_dla_head_poza_regulami_werdyktu(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, f"WERDYKT: PASS {head}\nZnaleziska: 0")

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert [line.split(" | ", 2)[2] for line in _lines(answered, "WERDYKT |")] == [
        f"HEAD, PASS poza regułami --werdykt | WERDYKT: PASS {head} | Znaleziska: 0"
    ]


REAL_SKILLS_FOR_CHANGE = "tools/skille_dla_zmiany.py"


def test_przeglad_z_prawdziwym_skille_dla_zmiany_z_head_pr_podaje_skille_zmiany_od_merge_base(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, ".agents/skills/verify-kod/SKILL.md": "---\nname: verify-kod\ndescription: kod\npilnuje:\n  - kod/*\n---\n"})
    github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n", **{name: (TOOLS.parent / name).read_text(encoding="utf-8") for name in with_imports((REAL_SKILLS_FOR_CHANGE,))}})

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _lines(answered, "SKILLE VERIFY") == ["SKILLE VERIFY: verify-kod"]


def test_przeglad_nie_czeka_dluzej_niz_limit_na_skille_dla_zmiany(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/skille_dla_zmiany.py": "import time\n\ntime.sleep(60)\n"})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    tool = github.checkout / "tools" / "lib" / "kontekst_przegladu.py"
    tool.write_text(tool.read_text(encoding="utf-8").replace("SKILLS_TIMEOUT_S = 300", "SKILLS_TIMEOUT_S = 1"), encoding="utf-8")

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _lines(answered, "SKILLE VERIFY") == ["SKILLE VERIFY: nieznane (tools/skille_dla_zmiany.py przerwane po 1 s)"]
    assert _last_line(answered) == f"PRZEGLĄD OK | #1 {head[:7]}"


@pytest.mark.parametrize(
    ("files", "skills"),
    [
        ({}, "SKILLE VERIFY: nieznane (HEAD PR nie ma tools/skille_dla_zmiany.py)"),
        ({"tools/skille_dla_zmiany.py": 'print("verify-a: kod/inne.py")\nraise SystemExit("plan CI zepsuty")\n'}, "SKILLE VERIFY: nieznane (tools/skille_dla_zmiany.py: plan CI zepsuty)"),
        ({"tools/skille_dla_zmiany.py": "raise SystemExit(3)\n"}, "SKILLE VERIFY: nieznane (tools/skille_dla_zmiany.py: kod 3)"),
    ],
    ids=["bez-narzedzia", "narzedzie-pada", "narzedzie-pada-bez-slowa"],
)
def test_przeglad_bez_wyniku_skille_dla_zmiany_podaje_skille_nieznane_a_pr_bez_werdyktu_jako_pierwsza_runde(
    tmp_path: Path, files: dict[str, str], skills: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, **files})
    github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, "Wygląda dobrze, WERDYKT: PASS później.")

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _lines(answered, "SKILLE VERIFY") == [skills]
    assert _lines(answered, "WERDYKT |") == []
    assert _lines(answered, "RUNDA |") == ["RUNDA | 1: PR nie ma werdyktu"]


@pytest.mark.parametrize(
    ("verdict", "decision"),
    [
        ("\n  WERDYKT: PASS {head}  \n\nZnaleziska: 1 (Ważne 0, Drobne 1)\n- Drobne: nazwa\n", "PASS"),
        ("WERDYKT: FAIL {head}\nZnaleziska: 4 (Ważne 1, Drobne 3)\n- Ważne: brak testu\n", "FAIL"),
    ],
    ids=["pass", "fail"],
)
def test_werdykt_w_postaci_ze_skilla_dla_head_trafia_na_pr_jako_komentarz_ktory_rozstrzyga_scalenie(
    tmp_path: Path, verdict: str, decision: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(verdict.format(head=head), encoding="utf-8")

    answered = github.run("1", "--werdykt", str(path))
    checked = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered) == f"WERDYKT OK | #1 {head[:7]} | {decision} | https://github.com/{opisy_pr.REPO}/pull/1#issuecomment-1"
    assert github.published() == [["1", verdict.format(head=head)]]
    assert (checked.returncode == 0) == (decision == "PASS"), checked.stdout + checked.stderr


OLD = "0" * 40


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        ("", "pierwsza linia „” to nie „WERDYKT: PASS {head}” ani „WERDYKT: FAIL {head}”; druga linia „” to nie „Znaleziska: N (Ważne a, Drobne b)”"),
        ("WERDYKT: PASS {short}\nZnaleziska: 0 (Ważne 0, Drobne 0)", "pierwsza linia „WERDYKT: PASS {short}” to nie „WERDYKT: PASS {head}” ani „WERDYKT: FAIL {head}”"),
        ("Werdykt: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)", "pierwsza linia „Werdykt: PASS {head}” to nie „WERDYKT: PASS {head}” ani „WERDYKT: FAIL {head}”"),
        (f"WERDYKT: PASS {OLD}\nZnaleziska: 0 (Ważne 0, Drobne 0)", f"werdykt dla {OLD[:7]}, a HEAD PR to {{head}}: przejrzyj git diff {OLD} {{head}} i wpisz SHA HEAD"),
        ("WERDYKT: PASS {head}\n- Drobne: nazwa", "druga linia „- Drobne: nazwa” to nie „Znaleziska: N (Ważne a, Drobne b)”"),
        ("WERDYKT: FAIL {head}\nZnaleziska: 2 (Ważne 1, Drobne 0)", "Znaleziska: 2, a Ważne 1 i Drobne 0 dają 1"),
        ("WERDYKT: PASS {head}\nZnaleziska: 4 (Ważne 0, Drobne 4)", "Drobne 4: podaj najwyżej 3, najważniejsze"),
        ("WERDYKT: PASS {head}\nZnaleziska: 1 (Ważne 1, Drobne 0)", "PASS z Ważne 1: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"),
        ("WERDYKT: FAIL {head}\nZnaleziska: 1 (Ważne 0, Drobne 1)", "FAIL z Ważne 0: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"),
        (
            f"WERDYKT: FAIL {OLD}\nZnaleziska: 3 (Ważne 0, Drobne 4)",
            f"werdykt dla {OLD[:7]}, a HEAD PR to {{head}}: przejrzyj git diff {OLD} {{head}} i wpisz SHA HEAD; "
            "Znaleziska: 3, a Ważne 0 i Drobne 4 dają 4; Drobne 4: podaj najwyżej 3, najważniejsze; "
            "FAIL z Ważne 0: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych",
        ),
    ],
    ids=["pusty", "skrocony-sha", "male-litery", "inny-commit", "bez-linii-znalezisk", "zla-suma", "za-duzo-drobnych", "pass-z-waznym", "fail-bez-waznego", "kilka-naraz"],
)
def test_werdykt_niezgodny_z_postacia_ze_skilla_albo_z_head_nie_trafia_na_pr_a_odmowa_mowi_co_poprawic(
    tmp_path: Path, verdict: str, reason: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(verdict.format(head=head, short=head[:7]), encoding="utf-8")

    answered = github.run("1", "--werdykt", str(path))

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"WERDYKT ODMOWA | #1 | {reason.format(head=head, short=head[:7])}; popraw {path} i uruchom ponownie"
    assert github.published() == []


@pytest.mark.parametrize(
    "modes",
    [["--przeglad", "--bez-merge"], ["--werdykt", "PLIK", "--bez-merge"], ["--przeglad", "--werdykt", "PLIK"]],
    ids=["przeglad-i-bez-merge", "werdykt-i-bez-merge", "przeglad-i-werdykt"],
)
def test_tryby_przegladu_werdyktu_i_bez_merge_sie_wykluczaja_wiec_dwa_naraz_niczego_nie_publikuja_ani_nie_scalaja(
    tmp_path: Path, modes: list[str]
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(f"WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n", encoding="utf-8")

    answered = github.run("1", *(str(path) if mode == "PLIK" else mode for mode in modes))

    assert (answered.returncode, answered.stdout) == (2, ""), answered.stdout + answered.stderr
    assert "not allowed with argument" in answered.stderr, answered.stderr
    assert (github.published(), github.merges()) == ([], [])


@pytest.mark.parametrize(
    ("mode", "label"),
    [(["--przeglad"], "PRZEGLĄD"), (["--werdykt", "PLIK"], "WERDYKT"), (["--bez-merge"], "SCAL")],
    ids=["przeglad", "werdykt", "bez-merge"],
)
def test_blad_gh_konczy_sie_linia_fail_z_nazwa_trybu(tmp_path: Path, mode: list[str], label: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(f"WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n", encoding="utf-8")

    # Atrapa gh nie zna PR 2, więc ``gh pr view 2`` pada.
    answered = github.run("2", *(str(path) if part == "PLIK" else part for part in mode))

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert answered.stdout.startswith(f"{label} FAIL | gh pr view 2 "), answered.stdout
    assert (github.published(), github.merges()) == ([], [])


def _git_hanging_on(github: MergeGitHub, subcommand: str) -> None:
    """``git <subcommand>`` w narzędziu i atrapie ``gh`` czeka minutę i nic nie drukuje; reszta to prawdziwy Git.

    Podpolecenie stoi po opcjach ``-c <ustawienie>``, które dokłada ``tools/lib/repo.py``."""

    real = shutil.which("git")
    assert real is not None
    fake_cli(
        github.bin,
        "git",
        "import os, sys, time\n"
        "args = sys.argv[1:]\n"
        "while args[:1] == ['-c']:\n"
        "    args = args[2:]\n"
        f"if args[:1] == [{subcommand!r}]:\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        f"os.execv({real!r}, [{real!r}, *sys.argv[1:]])\n",
    )


@pytest.mark.parametrize(
    ("mode", "subcommand", "label"),
    [(["--przeglad"], "merge-base", "PRZEGLĄD"), ([], "ls-remote", "SCAL")],
    ids=["przeglad", "merge"],
)
def test_git_ktory_wisi_konczy_sie_linia_fail_po_limicie_githuba(tmp_path: Path, mode: list[str], subcommand: str, label: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    # Scalenie z bazą sprawdza tu atrapa ruff i mypy, bo sprawdzenie nie jest celem testu.
    head = github.open_pull(1, {"tools/ci_lokalnie.py": "print('CI LOKALNIE OK')\n"}, parent=_short_github_timeout(github))
    github.comment(1, PASS.format(head=head))
    _git_hanging_on(github, subcommand)

    answered = github.run("1", *mode)

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"{label} FAIL | Command '['git', '{subcommand}'"), answered.stdout
    assert _last_line(answered).endswith("timed out after 3 seconds"), answered.stdout
    assert github.merges() == []


def test_przeglad_pr_bez_wspolnej_historii_z_baza_konczy_sie_linia_fail_z_poleceniem_gita(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    git(github.checkout, "checkout", "--quiet", "--orphan", "obca-historia")
    orphan = commit(github.checkout, "obca historia")
    git(github.checkout, "push", "--quiet", "--force", "origin", f"{orphan}:refs/pull/1/head")
    git(github.checkout, "checkout", "--quiet", "--force", "main")
    github.update(1, headRefOid=orphan)
    base = git(github.origin, "rev-parse", "refs/heads/main")

    answered = github.run("1", "--przeglad")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"PRZEGLĄD FAIL | git merge-base {base} {orphan}:", answered.stdout


def test_werdykt_bez_pliku_konczy_sie_bledem_narzedzia_bez_komentarza(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})

    answered = github.run("1", "--werdykt", str(tmp_path / "brak.md"))

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered).startswith("WERDYKT FAIL | ")
    assert "brak.md" in _last_line(answered)
    assert github.published() == []
