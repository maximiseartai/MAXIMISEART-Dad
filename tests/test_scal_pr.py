"""``tools/scal_pr.py``: agent scala PR tylko przy zielonym CI na HEAD, werdykcie PASS dla HEAD, opisie z sekcjami wzoru
skilla ``pr`` i scaleniu z bieżącą bazą, które przechodzi ruff i mypy.

Testy biegną na prawdziwym Gicie z repozytorium bare jako ``origin`` (z ``refs/pull/N/head`` jak na GitHubie).
Prawdziwe ``tools/ci_lokalnie.py --tylko ruff,mypy`` na małym kodzie sprawdza scalenie tylko w testach z
``real_checks``; reszta ma w commicie ``start`` atrapę, która drukuje ``CI LOKALNIE OK``. Atrapa ``gh`` podaje stan PR
i zapisuje wywołania ``gh pr merge`` zamiast scalać.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import cast

import pytest

from tests.fixtures import chwasty, korzenie_pr, opisy_pr, werdykty_szablonu
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub, fake_cli
from tests.fixtures.git_repo import commit, git, with_imports

import czasy_ci
import github as klient_github
import naprawia
import rejestr_korzeni
import stan_pr
import szablon_werdyktu
import werdykt_pr

pytestmark = ONLY_FOUND_BY_NAME_ON_POSIX

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TEMPLATE = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "pr" / "SKILL.md"
REVIEW = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "przeglad"
BODY = opisy_pr.wzor("Cel.")
SUM = "def suma(a: int, b: int) -> int:\n    return a + b\n"
PYPROJECT = '[tool.ruff]\ninclude = ["kod/**/*.py"]\n\n[tool.mypy]\nstrict = true\nfiles = ["kod"]\n'
CHECKS_PASS = "print('CI LOKALNIE OK')\n"
CLEANUP = 'import pathlib\n\npathlib.Path("posprzatane").write_text("tak")\nprint("SPRZĄTANIE OK | 0 usuniętych")\n'
# Atrapa ``gh`` składa ``bodyHTML`` treści w odpowiedziach GraphQL z HTML renderera (``tests/fixtures/body_html.py``).
FAKE_GH = f"import sys\nsys.path.insert(0, {str(TOOLS.parent)!r})\nfrom tests.fixtures.body_html import body_html\n" + """\
import json, os, pathlib, re, subprocess, sys, time

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


def html_node(node, starts):
    # Węzeł PR GraphQL z bodyHTML każdej treści; komentarze i recenzje (listy) po 100 od indeksu starts[kind].
    found = {**node, "bodyHTML": body_html(node["body"], markdown)}
    for kind, start in starts.items():
        page = [{**verdict, "bodyHTML": body_html(verdict["body"], markdown)} for verdict in node[kind][start : start + 100]]
        found[kind] = {"pageInfo": {"hasNextPage": start + 100 < len(node[kind]), "endCursor": str(start + 100)}, "nodes": page}
    return found


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
        print(json.dumps({"state": "open"}))
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
elif arguments[:2] == ["api", "graphql"] and any(argument.startswith("number=") for argument in arguments):
    # jeden PR z pulls.json (pola gh pr view) albo z graphql.json, komentarze i recenzje po 100 od kursora
    variables = dict(arguments[index + 1].split("=", 1) for index, value in enumerate(arguments) if value in {"-f", "-F"})
    with (here / "pull_queries.jsonl").open("a") as out:
        out.write(json.dumps({key: value for key, value in variables.items() if key != "query"}) + "\\n")
    if variables["number"] in pulls:
        node = {**pulls[variables["number"]], "mergedAt": None}
    else:
        node = next(node for node in json.loads((here / "graphql.json").read_text()) if str(node["number"]) == variables["number"])
        node.update({kind: node[kind]["nodes"] for kind in ("comments", "reviews")})
    print(json.dumps({"data": {"repository": {"pullRequest": html_node(node, {kind: 0 if variables[kind] == "null" else int(variables[kind]) for kind in ("comments", "reviews")})}}}))
elif arguments[:2] == ["api", "graphql"]:
    # GraphQL search PR-ów jak GitHub: kwalifikatory updated/created z >= i <=, sort:<pole>-<kierunek> i first; zmiana
    # z graphql_changes.json ("po": tyle wcześniejszych zapytań) zmienia PR między stronami.
    variables = dict(arguments[index + 1].split("=", 1) for index, value in enumerate(arguments) if value in {"-f", "-F"})
    log = here / "graphql.jsonl"
    calls = len(log.read_text().splitlines()) if log.exists() else 0
    with log.open("a") as out:
        out.write(json.dumps({key: value for key, value in variables.items() if key != "query"}) + "\\n")
    nodes = json.loads((here / "graphql.json").read_text())
    for change in json.loads((here / "graphql_changes.json").read_text()):
        if calls >= change["po"]:
            next(node for node in nodes if node["number"] == change["number"]).update(change["pola"])
    terms = variables["q"].split()
    if f"repo:{REPO}" not in terms or "is:pr" not in terms:
        sys.exit(f"atrapa gh nie zna wyszukiwania: {terms}")
    for field, sign, value in (re.fullmatch(r"(updated|created):([<>]=)(.+)", term).groups() for term in terms if re.fullmatch(r"(updated|created):[<>]=.+", term)):
        nodes = [node for node in nodes if (node[field + "At"] >= value if sign == ">=" else node[field + "At"] <= value)]
    field, direction = next(term for term in terms if term.startswith("sort:")).removeprefix("sort:").split("-")
    nodes.sort(key=lambda node: (node[field + "At"], node["number"]), reverse=direction == "desc")
    found = [html_node({**node, **{kind: node[kind]["nodes"] for kind in ("comments", "reviews")}}, {"comments": 0, "reviews": 0}) for node in nodes[: int(variables["first"])]]
    print(json.dumps({"data": {"search": {"nodes": found}}}))
elif arguments[0] == "api" and any(argument.startswith("repos/{owner}/{repo}/") for argument in arguments):
    # zapis statusu commita: pola z -f
    method = arguments[arguments.index("--method") + 1] if "--method" in arguments else "GET"
    path = next(argument for argument in arguments if argument.startswith("repos/{owner}/{repo}/"))
    if method == "GET":
        sys.exit(f"atrapa gh nie zna: {arguments}")
    fields = dict(value.split("=", 1) for flag, value in zip(arguments, arguments[1:]) if flag == "-f")
    with (here / "writes.jsonl").open("a") as log:
        log.write(json.dumps([method, path, fields]) + "\\n")
    if path.startswith("repos/{owner}/{repo}/statuses/") and (here / "statusy_odrzucane").exists():
        sys.exit("gh: Validation Failed (HTTP 422)")
    print("{}")
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


def _verdict(kind: str, body: str, association: str = "OWNER", *, when: str) -> dict[str, object]:
    """Komentarz (``kind`` to ``comment``) albo recenzja w stanie ``kind`` w polach ``gh pr view --json``."""

    if kind == "comment":
        return {"body": body, "authorAssociation": association, "createdAt": when, "author": {"login": "recenzent"}}
    return {"body": body, "authorAssociation": association, "state": kind, "submittedAt": when, "author": {"login": "recenzent"}}


def _pr_view(number: int, head: str, **fields: object) -> dict[str, object]:
    """Odpowiedź ``gh pr view --json`` otwartego PR ``number`` z HEAD ``head``, zielonym CI i bez werdyktu, z ``fields``."""

    return {
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
        **fields,
    }


class MergeGitHub(FakeGitHub):
    def __init__(self, tmp_path: Path, files: dict[str, str], *, started: str = "2026-11-01T00:00:00Z", real_checks: bool = False) -> None:
        """Commit ``start`` ma datę ``started``, a z kopią narzędzia dodaje moduł bramki korzenia, więc to chwila jej
        wdrożenia na ``main`` (``bramka_korzenia.MARKER``); domyślnie po werdyktach atrapy (24.10.2026), więc ich wątki
        kończą bez bramki, a ``GATE_BEFORE_VERDICTS`` ją w nich włącza.

        Bez ``real_checks`` ``tools/ci_lokalnie.py`` w ``start`` to atrapa ``CHECKS_PASS``: stoi po obu stronach
        scalenia, więc nie zmienia plików zmiany PR ani ``main`` i wyboru testu scalenia."""

        super().__init__(
            tmp_path,
            {
                ".gitignore": ".mypy_cache/\n.ruff_cache/\n__pycache__/\nposprzatane\n",
                "pyproject.toml": PYPROJECT,
                ".agents/skills/pr/SKILL.md": TEMPLATE.read_text(encoding="utf-8"),
                ".agents/skills/przeglad/SKILL.md": (REVIEW / "SKILL.md").read_text(encoding="utf-8"),
                ".agents/skills/przeglad/korzenie.toml": (REVIEW / "korzenie.toml").read_text(encoding="utf-8"),
                "tools/sprzatanie.py": CLEANUP,
                **({} if real_checks else {"tools/ci_lokalnie.py": CHECKS_PASS}),
                **files,
            },
            tool="tools/scal_pr.py",
            gh=FAKE_GH,
            started=started,
        )
        _empty_state(self.bin)
        self.pulls: dict[str, dict[str, object]] = {}
        self.issues: dict[str, str] = {}
        self.repo_view = _repo_view("main")  # zaczęte od „gh: ” to błąd ``gh repo view``
        self.markdown = {**opisy_pr.rendered(), **werdykty_szablonu.rendered(), **korzenie_pr.rendered(), **chwasty.rendered()}  # HTML opisu i treści werdyktu, a jak w ``answer_issue`` błąd albo ``zawiesza``
        self.graphql: list[dict[str, object]] = []  # PR-y repozytorium dla wyszukiwania rejestru korzeni
        self.graphql_changes: list[dict[str, object]] = []  # zmiany PR-ów po danej liczbie zapytań GraphQL
        self.written = 0

    def environment(self) -> dict[str, str]:
        # Test scalenia biegnie na jednym-dwóch plikach testów, a liczbę workerów brałby z pytesta, który go uruchomił.
        return {**super().environment(), "PYTEST_XDIST_AUTO_NUM_WORKERS": "1"}

    def open_pull(self, number: int, files: dict[str, str], *, parent: str = "") -> str:
        """HEAD nowego PR z zielonym CI i bez werdyktu: commit ``files`` na ``parent`` (domyślnie commit ``start``)."""

        head = self.commit_on(parent or self.start, files, f"PR {number}")
        self.push_head(number, head)
        self.pulls[str(number)] = _pr_view(number, head)
        self._save()
        return head

    def update(self, number: int, **fields: object) -> None:
        self.pulls[str(number)].update(fields)
        self._save()

    def comment(self, number: int, body: str, association: str = "OWNER") -> None:
        self._write(number, "comments", _verdict("comment", body, association, when=self._now()))

    def edited_comment(self, number: int, body: str) -> None:
        """Komentarz konta z prawem zapisu, którego treść zmieniono po utworzeniu (``includesCreatedEdit``)."""

        self._write(number, "comments", {**_verdict("comment", body, when=self._now()), "includesCreatedEdit": True})

    def review(self, number: int, body: str, association: str = "OWNER", *, state: str = "COMMENTED") -> None:
        self._write(number, "reviews", _verdict(state, body, association, when=self._now()))

    def _now(self) -> str:
        self.written += 1
        return f"2026-10-24T03:{self.written // 60:02d}:{self.written % 60:02d}Z"

    def _write(self, number: int, kind: str, verdict: dict[str, object]) -> None:
        verdicts = self.pulls[str(number)][kind]
        assert isinstance(verdicts, list)
        verdicts.append(verdict)
        self._save()

    def open_issues(self, *numbers: int, state: str = "open") -> None:
        self.answer_issue(*numbers, answer=json.dumps({"state": state}))

    def answer_issue(self, *numbers: int, answer: str) -> None:
        """``gh api`` issue ``numbers`` drukuje ``answer``, a ``zawiesza`` każe mu czekać minutę i podać issue otwarte,
        więc narzędzie bez limitu ``gh`` by je zamknęło."""

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

    def writes(self) -> list[list[str]]:
        """Zapisy ``gh api --method`` w repozytorium checkoutu: metoda, ścieżka i pola."""

        return self._log("writes.jsonl")

    def _log(self, name: str) -> list[list[str]]:
        log = self.bin / name
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def _save(self) -> None:
        (self.bin / "pulls.json").write_text(json.dumps(self.pulls), encoding="utf-8")
        (self.bin / "issues.json").write_text(json.dumps(self.issues), encoding="utf-8")
        (self.bin / "repo_view").write_text(self.repo_view, encoding="utf-8")
        (self.bin / "markdown.json").write_text(json.dumps(self.markdown), encoding="utf-8")
        for name, value in (
            ("graphql.json", self.graphql),
            ("graphql_changes.json", self.graphql_changes),
        ):
            (self.bin / name).write_text(json.dumps(value), encoding="utf-8")


def _empty_state(directory: Path) -> None:
    rendered = {**opisy_pr.rendered(), **werdykty_szablonu.rendered(), **korzenie_pr.rendered(), **chwasty.rendered()}
    for name, empty in (
        ("pulls.json", "{}"),
        ("issues.json", "{}"),
        ("repo_view", ""),
        ("markdown.json", json.dumps(rendered)),
        ("graphql.json", "[]"),
        ("graphql_changes.json", "[]"),
    ):
        (directory / name).write_text(empty, encoding="utf-8")


def _tool_on_main(github: MergeGitHub, name: str, replaced: tuple[str, str]) -> str:
    """Commit na ``main`` w ``origin``, który w pliku narzędzia ``name`` zamienia ``replaced``; scalenie i werdykt sądzi
    kod ``origin/main``, więc zmiana narzędzia tylko w checkoucie by nie zadziałała."""

    tool = github.checkout / name
    tool.write_text(tool.read_text(encoding="utf-8").replace(*replaced), encoding="utf-8")
    git(github.checkout, "commit", "--quiet", "--all", "--message", f"{name} po zmianie")
    git(github.checkout, "push", "--quiet", "origin", "main")
    return git(github.checkout, "rev-parse", "HEAD")


def _short_github_timeout(github: MergeGitHub) -> str:
    """Commit na ``main`` z ``github.LIMIT_S`` równym 3 s, żeby ``gh``, które zawiesza, kończyło się szybko."""

    return _tool_on_main(github, "tools/lib/github.py", ("LIMIT_S = 60", "LIMIT_S = 3"))


def _repo_view(default_branch: str) -> str:
    return json.dumps({"defaultBranchRef": {"name": default_branch}, "nameWithOwner": opisy_pr.REPO})


def _last_line(answered: subprocess.CompletedProcess[str]) -> str:
    return answered.stdout.rstrip().rpartition("\n")[2]


def _deploy_template(github: MergeGitHub, *, authored: str = "2026-10-01T00:00:00Z", merged: str = "2026-10-01T00:00:00Z") -> None:
    """Wdrożenie szablonu werdyktu na ``main`` w ``origin``: commit autora z ADR 0031 z datą ``authored`` scalony do
    ``main`` commitem merge'a z datą ``merged``; werdykty atrapy powstają 24 i 25.10.2026."""

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GIT_COMMITTER_DATE", authored)
        added = github.commit_on("main", {szablon_werdyktu.ADR: "# ADR 0031: Korzeń po FAIL i chwasty\n"}, "ADR 0031")
        patch.setenv("GIT_COMMITTER_DATE", merged)
        git(github.checkout, "merge", "--quiet", "--no-ff", "--message", "Merge wdrożenia szablonu", added)
    git(github.checkout, "push", "--quiet", "origin", "main")


def test_gotowy_pr_jest_scalany_z_jego_head_a_po_merge_biegnie_sprzatanie(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM}, real_checks=True)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    main = github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})
    github.comment(1, f"WERDYKT: FAIL {head}\n- krytyczne: brak testu")
    github.comment(1, f"Poprawione w {head[:7]}.")
    github.comment(1, f"WERDYKT: PASS {head}\nZnaleziska: 1 (Ważne 0, Drobne 1)\n- Drobne: nazwa")

    merged = github.run("1")

    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert _last_line(merged) == (
        f"SCAL OK | #1 {head[:7]} | scalony do main jako {merge_commit[:7]} (baza {main[:7]}) | sprzątanie: SPRZĄTANIE OK | 0 usuniętych"
    )
    assert git(github.origin, "rev-list", "--parents", "-n", "1", merge_commit).split()[1:] == [main, head]
    assert github.merges() == [["pr", "merge", "1", "--merge", "--match-head-commit", head]]
    assert (github.checkout / "posprzatane").exists()


# Pełne SHA w tabelach na interfejsach: HEAD PR i starszy commit (litery, żeby ``HEAD.upper()`` był inny niż HEAD).
HEAD = "abcdef0123456789abcdef0123456789abcdef01"
OLD = "0" * 40
PASS_HEAD = PASS.format(head=HEAD)
FAIL_HEAD = f"WERDYKT: FAIL {HEAD}"
NO_PASS_HEAD = NO_PASS.format(head=HEAD)
OBJECTION_HEAD = OBJECTION.format(short=HEAD[:7], head=HEAD)
BROKEN_PASS = "werdykt: PASS dla {short} nie przechodzi reguł --werdykt ({problems}); popraw plik werdyktu i opublikuj go przez tools/scal_pr.py 1 --werdykt PLIK"
NO_FINDINGS = "druga linia „{line}” to nie „Znaleziska: N (Ważne a, Drobne b)”"


def _broken(problems: str) -> str:
    return BROKEN_PASS.format(short=HEAD[:7], problems=problems)


def _pull(**fields: object) -> stan_pr.Pull:
    """``stan_pr.pull`` PR 1 z HEAD ``HEAD`` na odpowiedzi ``gh pr view`` z ``fields``, z atrapą ``gh`` w procesie."""

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(klient_github, "gh", lambda *arguments: json.dumps(_pr_view(1, HEAD, **fields)))
        return stan_pr.pull(1)


def _written(*verdicts: tuple[str, ...]) -> stan_pr.Pull:
    """PR z komentarzami (``comment``) i recenzjami (stan recenzji) z kontem (domyślnie ``OWNER``) utworzonymi po kolei."""

    written = [_verdict(kind, body, *association, when=f"2026-10-24T03:00:{index:02d}Z") for index, (kind, body, *association) in enumerate(verdicts)]
    return _pull(comments=[verdict for verdict in written if "createdAt" in verdict], reviews=[verdict for verdict in written if "submittedAt" in verdict])


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
    ("verdicts", "reason"),
    [
        ([], NO_PASS_HEAD),
        ([("comment", f"WERDYKT: PASS {OLD}")], NO_PASS_HEAD),
        ([("comment", PASS_HEAD, "NONE")], NO_PASS_HEAD),
        ([("comment", PASS_HEAD, "CONTRIBUTOR")], NO_PASS_HEAD),
        ([("COMMENTED", PASS_HEAD, "CONTRIBUTOR")], NO_PASS_HEAD),
        ([("PENDING", PASS_HEAD)], NO_PASS_HEAD),
        ([("comment", f"Recenzja: WERDYKT: PASS {HEAD}")], NO_PASS_HEAD),
        ([("comment", f"WERDYKT: PASS {HEAD} — bez uwag")], NO_PASS_HEAD),
        ([("comment", f"WERDYKT: PASS {HEAD[:7]}")], NO_PASS_HEAD),
        ([("comment", f"WERDYKT: PASS {HEAD.upper()}")], NO_PASS_HEAD),
        ([("comment", f"**WERDYKT: PASS {HEAD}**")], NO_PASS_HEAD),
        ([("comment", "## Werdykt niezależny: PASS")], NO_PASS_HEAD),
        ([("APPROVED", "Wygląda dobrze.")], NO_PASS_HEAD),
        ([("comment", PASS_HEAD), ("comment", FAIL_HEAD, "MEMBER")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", FAIL_HEAD)], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", f"{FAIL_HEAD}\n- krytyczne: brak testu")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", f"\n\n  {FAIL_HEAD}  \r\n")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("COMMENTED", FAIL_HEAD)], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("CHANGES_REQUESTED", "")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", f"{FAIL_HEAD}\nZnaleziska: dwa Ważne, brak testu")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", f"{FAIL_HEAD}\nZnaleziska: 1 (Ważne 0, Drobne 1)")], OBJECTION_HEAD),
        ([("comment", PASS_HEAD), ("comment", f"WERDYKT: FAIL {OLD}")], None),
        ([("comment", FAIL_HEAD), ("comment", PASS_HEAD)], None),
        ([("COMMENTED", FAIL_HEAD), ("comment", PASS_HEAD)], None),
        ([("comment", FAIL_HEAD), ("COMMENTED", PASS_HEAD)], None),
        ([("comment", PASS_HEAD), ("comment", FAIL_HEAD, "CONTRIBUTOR")], None),
        ([("comment", PASS_HEAD), ("COMMENTED", "")], None),
        ([("comment", f"WERDYKT: PASS {HEAD}\r\n\r\nZnaleziska: 1 (Ważne 0, Drobne 1)\r\n- drobne: nazwa")], None),
        ([("comment", f"  WERDYKT: PASS {HEAD}  \n  Znaleziska: 0 (Ważne 0, Drobne 0)  ")], None),
        ([("CHANGES_REQUESTED", "Popraw nazwę funkcji."), ("comment", PASS_HEAD)], None),
        ([("comment", PASS_HEAD), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.", "CONTRIBUTOR")], None),
        ([("comment", PASS_HEAD), ("PENDING", FAIL_HEAD)], None),
        ([("comment", PASS_HEAD), ("comment", f"WERDYKT: FAIL {HEAD[:7]}")], None),
        ([("comment", PASS_HEAD), ("comment", f"{FAIL_HEAD} — brak testu")], None),
        ([("comment", PASS_HEAD), ("comment", f"Werdykt: FAIL {HEAD}")], None),
        ([("comment", PASS_HEAD), ("comment", f"## Przegląd\n\n{FAIL_HEAD}")], None),
        ([("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 0"), ("comment", PASS_HEAD)], None),
        ([("comment", f"WERDYKT: PASS {OLD}\nZnaleziska: 0"), ("comment", PASS_HEAD)], None),
        ([("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 0")], _broken(NO_FINDINGS.format(line="Znaleziska: 0"))),
        ([("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 1 (Drobne 1)")], _broken(NO_FINDINGS.format(line="Znaleziska: 1 (Drobne 1)"))),
        ([("comment", f"WERDYKT: PASS {HEAD}")], _broken(NO_FINDINGS.format(line=""))),
        (
            [("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 1 (Ważne 1, Drobne 0)")],
            _broken("PASS z Ważne 1: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"),
        ),
        ([("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 4 (Ważne 0, Drobne 4)")], _broken("Drobne 4: podaj najwyżej 3, najważniejsze")),
        ([("COMMENTED", f"WERDYKT: PASS {HEAD}\nZnaleziska: 0")], _broken(NO_FINDINGS.format(line="Znaleziska: 0"))),
        ([("comment", PASS_HEAD), ("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 0")], _broken(NO_FINDINGS.format(line="Znaleziska: 0"))),
        (
            [("comment", f"WERDYKT: PASS {HEAD}\nZnaleziska: 2 (Ważne 1, Drobne 0)")],
            _broken("Znaleziska: 2, a Ważne 1 i Drobne 0 dają 1; PASS z Ważne 1: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"),
        ),
    ],
    ids=[
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
        "sprzeciw-komentarz",
        "sprzeciw-komentarz-ze-znaleziskami",
        "sprzeciw-puste-linie-i-odstepy",
        "sprzeciw-recenzja",
        "sprzeciw-prosba-o-zmiany",
        "sprzeciw-prosba-o-zmiany-bez-tresci",
        "sprzeciw-fail-z-proza-w-drugiej-linii-jak-532",
        "sprzeciw-fail-bez-waznych-poza-regulami-werdyktu",
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
        "pass-poza-regulami-znaleziska-0-jak-994",
        "pass-poza-regulami-drobne-bez-waznych-jak-1004",
        "pass-poza-regulami-bez-drugiej-linii",
        "pass-poza-regulami-z-waznym",
        "pass-poza-regulami-za-duzo-drobnych",
        "pass-poza-regulami-w-recenzji",
        "pass-poza-regulami-po-pass-w-postaci-werdyktu",
        "pass-poza-regulami-kilka-przyczyn",
    ],
)
def test_najnowszy_werdykt_dla_head_rozstrzyga_zgode_na_merge(verdicts: list[tuple[str, ...]], reason: str | None) -> None:
    assert werdykt_pr.consent_problem(_written(*verdicts), None) == reason


@pytest.mark.parametrize(
    ("verdicts", "refused"),
    [
        ([("comment", PASS), ("COMMENTED", "WERDYKT: FAIL {head}")], True),
        ([("COMMENTED", "WERDYKT: FAIL {head}"), ("comment", PASS)], False),
        ([("comment", PASS), ("CHANGES_REQUESTED", "Popraw nazwę funkcji.")], True),
        ([("comment", PASS), ("comment", "WERDYKT: FAIL {head}", "CONTRIBUTOR")], False),
    ],
    ids=["recenzja-z-fail-po-komentarzu-pass", "komentarz-pass-po-recenzji-z-fail", "prosba-o-zmiany-po-pass", "fail-kontrybutora-po-pass"],
)
def test_komentarze_i_recenzje_z_gh_licza_sie_w_kolejnosci_utworzenia(tmp_path: Path, verdicts: list[tuple[str, ...]], refused: bool) -> None:
    """Rozstrzyga też element inny niż ostatni, więc ``scal_pr`` musi oddać regule wszystkie komentarze i recenzje."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    for kind, body, *association in verdicts:
        if kind == "comment":
            github.comment(1, body.format(head=head), *association)
        else:
            github.review(1, body.format(head=head), *association, state=kind)

    answered = github.run("1", "--bez-merge")

    assert answered.returncode == int(refused), answered.stdout + answered.stderr
    if refused:
        assert _last_line(answered) == f"SCAL ODMOWA | #1 {head[:7]} | {OBJECTION.format(short=head[:7], head=head)}"
    else:
        assert _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} | gotowy do merge'a")


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


RED_RUN_BEFORE_OLDER_GREEN = [*_run(42706832032, *RED_RUN), *_run(42701212234, *GREEN_RUN)]


@pytest.mark.parametrize(
    ("rollup", "reason"),
    [
        ([_check_run("COMPLETED", "FAILURE")], "„Required CI status” FAILURE"),
        ([_check_run("IN_PROGRESS", None)], "„Required CI status” IN_PROGRESS"),
        (GREEN[:1], "run CI 4077 jeszcze trwa"),
        ([COMMIT_STATUS], "brak „Required CI status” z GitHub Actions na HEAD"),
        ([_check_run("COMPLETED", "SUCCESS", workflow="")], "brak „Required CI status” z GitHub Actions na HEAD"),
        ([*_run(42701212234, *RED_RUN), *_run(42706832032, *RED_RUN), *_run(42707489817, *GREEN_RUN)], None),
        ([*_run(42707489817, *GREEN_RUN), *_run(42706832032, *RED_RUN), *_run(42701212234, *RED_RUN)], None),
        ([*_run(42701212234, *GREEN_RUN), *_run(42706832032, *RED_RUN)], "„Required CI status” FAILURE"),
        (RED_RUN_BEFORE_OLDER_GREEN, "„Required CI status” FAILURE"),
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
        (GREEN, None),
        ([*GREEN, _check_run("IN_PROGRESS", None, name="Change mutations (1/3)", workflow="Mutacje nocne", url="https://github.com/o/r/actions/runs/4100/job/3")], None),
        ([*GREEN, _check_run("COMPLETED", "FAILURE", name="Change mutations (1/3)")], None),
    ],
    ids=[
        "ci-czerwone",
        "ci-trwa",
        "ci-run-bez-wymaganego-checku-jeszcze-trwa",
        "ci-tylko-status-commitu",
        "ci-check-spoza-github-actions",
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
        "mutacje-zmiany-bez-checku",
        "mutacje-zmiany-w-toku-w-nocnym-workflow",
        "mutacje-zmiany-przezyte-w-runie-ci",
    ],
)
def test_gotowosc_ci_liczy_tylko_najnowszy_run_ci_na_head_a_nie_czeka_na_mutacje_zmiany(rollup: list[dict[str, str | None]], reason: str | None) -> None:
    """Mutacje zmienionych linii biegną nocą na ``main`` (ADR 0021), więc ich check nie blokuje gotowości."""

    assert stan_pr.ci_problem(_pull(statusCheckRollup=rollup)) == (None if reason is None else f"CI: {reason}")


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


@pytest.mark.parametrize(
    "rollup", [[_check_run("COMPLETED", "FAILURE")], RED_RUN_BEFORE_OLDER_GREEN], ids=["ci-czerwone", "nowy-czerwony-run-przed-starym-zielonym-w-rollupie"]
)
def test_brak_naglowka_wzoru_jest_w_jednej_odmowie_z_czerwonym_ci_i_brakiem_werdyktu(tmp_path: Path, rollup: list[dict[str, str | None]]) -> None:
    """W drugim rollupie rozstrzyga run sprzed ostatniego checku, więc ``scal_pr`` musi oddać regule cały rollup."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body="", statusCheckRollup=rollup)

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
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "kod/nazwa.py": 'NAZWA = "pierwsza"\n'}, real_checks=True)
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
        ({SUM_TEST_FILE: SUM_TEST + SLOW_TEST}, ABS_SUM, ("MERGE_TEST_TIMEOUT_S = 300", "MERGE_TEST_TIMEOUT_S = 1"), f"bez wyniku po 1 s: {SUM_TEST_FILE}"),
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
        main = _tool_on_main(github, "tools/lib/testy_scalenia.py", replaced)

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


# ``gh`` po czasie czeka limit w każdym przebiegu, a „nie sprawdzono” z ``--bez-merge`` to ten sam ``except`` co błąd HTTP.
@pytest.mark.parametrize(
    ("answer", "dry_run"), [("gh: HTTP 502", True), ("\n", True), ("zawiesza", False)], ids=["blad-http", "pusta-odpowiedz", "gh-po-czasie"]
)
def test_bez_html_opisu_od_githuba_merge_sie_odbywa_a_issues_zostaja_otwarte_z_ostrzezeniem(tmp_path: Path, answer: str, dry_run: bool) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
    github.open_issues(3)
    github.markdown[opisy_pr.SCALENIE["jedno"]] = answer
    github.update(1, body=opisy_pr.SCALENIE["jedno"])
    github.comment(1, PASS.format(head=head))

    if dry_run:
        checked = github.run("1", "--bez-merge")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert _last_line(checked).endswith("(--bez-merge) | UWAGA: GitHub nie wyrenderował opisu PR, nie sprawdzono „Naprawia”")
    merged = github.run("1")

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
    github.answer_issue(13, answer="")
    github.update(1, body=opisy_pr.SCALENIE["porazki"])
    github.comment(1, PASS.format(head=head))

    checked = github.run("1", "--bez-merge")
    # Tylko w przebiegu z merge'em: ``gh`` po czasie czeka limit, a w ``--bez-merge`` daje ten sam ``except`` co #10.
    github.answer_issue(13, answer="zawiesza")
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


def _render_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """``gh`` klienta GitHuba renderuje w procesie testu jak ``gh api markdown`` atrapy ``FAKE_GH``: HTML opisu
    z ``opisy_pr.json`` tylko dla prośby z ``mode=gfm`` i ``context`` tego repozytorium bez względu na litery.
    Drogę przez program ``gh`` sprawdzają testy przebiegu narzędzia (``test_po_merge_zamyka…``)."""

    rendered = opisy_pr.rendered()

    def gh(*arguments: str, wejscie: str | None = None, limit_s: float | None = None, cwd: Path | None = None) -> str:
        assert arguments == ("api", "markdown", "--input", "-") and wejscie is not None, arguments
        request = json.loads(wejscie)
        assert request.keys() == {"text", "mode", "context"} and request["mode"] == "gfm", request
        assert request["context"].casefold() == opisy_pr.REPO.casefold(), request
        return rendered[request["text"]]

    monkeypatch.setattr(klient_github, "gh", gh)


def _fixed_issues(body: str, repository: str) -> tuple[int, ...]:
    return naprawia.listed_issues(klient_github.html_markdownu(body, repository), repository, (naprawia.FIXES,))


@pytest.mark.parametrize(("body", "fixes"), [case[1:] for case in opisy_pr.PRZYPADKI], ids=[case[0] for case in opisy_pr.PRZYPADKI])
def test_naprawia_wskazuje_issues_tego_repo_tylko_na_poczatku_linii_tekstu_ktory_github_pokazuje(
    monkeypatch: pytest.MonkeyPatch, body: str, fixes: tuple[int, ...]
) -> None:
    _render_in_process(monkeypatch)

    assert _fixed_issues(body, opisy_pr.REPO) == fixes


def test_naprawia_wskazuje_issues_tego_repo_bez_wzgledu_na_wielkosc_liter_jego_nazwy(monkeypatch: pytest.MonkeyPatch) -> None:
    _render_in_process(monkeypatch)

    assert _fixed_issues(opisy_pr.SCALENIE["dwa"], opisy_pr.REPO.swapcase()) == (3, 4)


@pytest.mark.parametrize(("number", "fixes"), opisy_pr.PRAWDZIWE.items(), ids=[f"pr-{number}" for number in opisy_pr.PRAWDZIWE])
def test_opisy_scalonych_pr_wskazuja_issues_ktore_github_zostawil_otwarte(monkeypatch: pytest.MonkeyPatch, number: int, fixes: tuple[int, ...]) -> None:
    _render_in_process(monkeypatch)

    assert _fixed_issues(opisy_pr.real_body(number), opisy_pr.REPO) == fixes


def test_kazdy_opis_testow_ma_html_z_renderera_githuba() -> None:
    assert sorted(opisy_pr.rendered()) == sorted(set(opisy_pr.bodies())), "odśwież: .venv/bin/python tests/fixtures/opisy_pr.py"


def test_sprzatanie_po_czasie_nie_odwoluje_scalenia(tmp_path: Path) -> None:
    hangs = "import time\n\ntime.sleep(600)\n"
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/sprzatanie.py": hangs})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    _tool_on_main(github, "tools/scal_pr.py", ("CLEANUP_TIMEOUT_S = 300", "CLEANUP_TIMEOUT_S = 1"))
    github.comment(1, PASS.format(head=head))

    answered = github.run("1")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered).endswith("| UWAGA: sprzątanie przerwane po 1 s, uruchom je ponownie")
    assert len(github.merges()) == 1



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
RED_WITH_FAILED_JOBS = [
    _check_run("COMPLETED", "FAILURE", name="pytest (Python 3.11, 1/2)"),
    _check_run("COMPLETED", "TIMED_OUT", name="Mutation checks 2"),
    _check_run("COMPLETED", "SUCCESS", name="Ruff, mypy"),
    _check_run("COMPLETED", "SKIPPED", name="Frontend"),
    _check_run("COMPLETED", "FAILURE", name="Verify Centrum na Windowsie", workflow="Verify", url=OTHER_RUN),
    _check_run("COMPLETED", "FAILURE"),
]
FAILED_JOBS = "padłe zadania: Mutation checks 2, pytest (Python 3.11, 1/2)"
WAITING_VERIFY = _check_run("IN_PROGRESS", None, name="Verify Centrum na Windowsie", workflow="Verify", url=OTHER_RUN)


@pytest.mark.parametrize(
    ("ci", "line"),
    [
        (GREEN, f"success na HEAD {HEAD} | {PASSED}"),
        (
            [
                *GREEN,
                WAITING_VERIFY,
                _check_run("COMPLETED", "FAILURE", name="Lint skilli", workflow="Skille", url=OTHER_RUN),
                _check_run("COMPLETED", "SKIPPED", name="Notka", workflow="Skille", url=OTHER_RUN),
            ],
            f"success na HEAD {HEAD} | {PASSED} | inne workflowy, na które czeka gotowość: w toku: Verify Centrum na Windowsie; padłe: Lint skilli",
        ),
        (
            [_check_run("COMPLETED", "SUCCESS", name="Ruff, mypy"), _check_run("IN_PROGRESS", None)],
            f"pending na HEAD {HEAD} (w toku: 1) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [_check_run("QUEUED", None, name="Plan CI"), _check_run("IN_PROGRESS", None, name="Frontend")],
            f"pending na HEAD {HEAD} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [_check_run("IN_PROGRESS", None, name="Frontend"), _check_run("COMPLETED", "FAILURE", name="pytest (Python 3.11, 1/2)")],
            f"pending na HEAD {HEAD} (w toku: 1; padłe zadania: pytest (Python 3.11, 1/2)) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (RED_WITH_FAILED_JOBS, f"failure na HEAD {HEAD} | {FAILED_JOBS} | {UNPROVEN}"),
        (
            [_check_run("COMPLETED", "FAILURE", name="Plan CI", url=OTHER_RUN), _check_run("COMPLETED", "FAILURE")],
            f"failure na HEAD {HEAD} | bez padłego zadania, przyczynę podaje log „Required CI status” | {UNPROVEN}",
        ),
        ([COMMIT_STATUS], f"brak na HEAD {HEAD} | CI nie biegło na tym HEAD: jeszcze nie wystartowało po pushu albo PR ma konflikt z bazą"),
        (
            [*_run(4000, ("pytest (Python 3.11, 1/2)", "COMPLETED", "FAILURE"), RED_RUN[-1]), *_run(4077, ("pytest (Python 3.11, 1/2)", "COMPLETED", "SUCCESS"), REQUIRED_DONE)],
            f"success na HEAD {HEAD} | {PASSED}",
        ),
        (
            [*_run(4000, ("Ruff, mypy", "COMPLETED", "SUCCESS"), REQUIRED_DONE), *_run(4077, ("Ruff, mypy", "COMPLETED", "FAILURE"), RED_RUN[-1])],
            f"failure na HEAD {HEAD} | padłe zadania: Ruff, mypy | {UNPROVEN}",
        ),
        (
            [*_run(4000, ("Plan CI", "COMPLETED", "FAILURE"), RED_RUN[-1]), *_run(4077, *RUNNING_RUN)],
            f"pending na HEAD {HEAD} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*_run(3000, *RED_RUN), *_run(4000, *GREEN_RUN), *_run(4077, *RUNNING_RUN)],
            f"pending na HEAD {HEAD} (w toku: 2) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            _run(4077, ("Plan CI", "COMPLETED", "SUCCESS"), ("Frontend", "COMPLETED", "SUCCESS")),
            f"pending na HEAD {HEAD} (w toku: 0) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*_run(4077, ("Frontend", "IN_PROGRESS", None), REQUIRED_DONE)],
            f"pending na HEAD {HEAD} (w toku: 1) | polecenia z linii LICZY CI jeszcze bez wyniku",
        ),
        (
            [*GREEN, _check_run("COMPLETED", "SUCCESS", name="Frontend", url="https://github.com/o/r/runs/129482655837")],
            f"nieznany na HEAD {HEAD} | check „Frontend” workflow „CI” bez identyfikatora runu w detailsUrl "
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
def test_linia_ci_przegladu_podaje_stan_required_ci_status_i_padle_zadania_najnowszego_runu(ci: list[dict[str, str | None]], line: str) -> None:
    assert stan_pr.ci_line(_pull(statusCheckRollup=ci)) == f"CI | Required CI status {line}"


@pytest.mark.parametrize(
    ("rollup", "line"),
    [
        ([*GREEN, WAITING_VERIFY], f"success na HEAD {{head}} | {PASSED} | inne workflowy, na które czeka gotowość: w toku: Verify Centrum na Windowsie"),
        (RED_WITH_FAILED_JOBS, f"failure na HEAD {{head}} | {FAILED_JOBS} | {UNPROVEN}"),
    ],
    ids=["zielony-a-inny-workflow-w-toku", "czerwony-z-padlymi-zadaniami-jego-runu"],
)
def test_przeglad_podaje_linie_ci_z_rollupu_checkow_gh(tmp_path: Path, rollup: list[dict[str, str | None]], line: str) -> None:
    """W czerwonym rollupie linię zmienia też pierwszy check, więc ``--przeglad`` musi oddać regule cały rollup."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, statusCheckRollup=rollup)

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
        ("\n  WERDYKT: PASS {head}  \n\nZnaleziska: 1 (Ważne 0, Drobne 1)\n" + werdykty_szablonu.WERDYKTY["drobne"] + "\n", "PASS"),
        ("WERDYKT: FAIL {head}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne"] + "\n", "FAIL"),
    ],
    ids=["pass", "fail"],
)
def test_werdykt_w_postaci_ze_skilla_dla_head_trafia_na_pr_jako_komentarz_ktory_rozstrzyga_scalenie(
    tmp_path: Path, verdict: str, decision: str
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    _deploy_template(github)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(verdict.format(head=head), encoding="utf-8")

    answered = github.run("1", "--werdykt", str(path))
    checked = github.run("1", "--bez-merge")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered) == f"WERDYKT OK | #1 {head[:7]} | {decision} | https://github.com/{opisy_pr.REPO}/pull/1#issuecomment-1"
    assert github.published() == [["1", verdict.format(head=head)]]
    assert (checked.returncode == 0) == (decision == "PASS"), checked.stdout + checked.stderr


MANY_PROBLEMS = f"WERDYKT: FAIL {OLD}\nZnaleziska: 3 (Ważne 0, Drobne 4)"
MANY_REASONS = (
    f"werdykt dla {OLD[:7]}, a HEAD PR to {{head}}: przejrzyj git diff {OLD} {{head}} i wpisz SHA HEAD; "
    "Znaleziska: 3, a Ważne 0 i Drobne 4 dają 4; Drobne 4: podaj najwyżej 3, najważniejsze; "
    "FAIL z Ważne 0: FAIL daje tylko Ważne znalezisko, a PASS jest bez Ważnych"
)


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
        (MANY_PROBLEMS, MANY_REASONS),
    ],
    ids=["pusty", "skrocony-sha", "male-litery", "inny-commit", "bez-linii-znalezisk", "zla-suma", "za-duzo-drobnych", "pass-z-waznym", "fail-bez-waznego", "kilka-naraz"],
)
def test_plik_werdyktu_niezgodny_z_postacia_ze_skilla_albo_z_head_daje_przyczyny_co_poprawic(verdict: str, reason: str) -> None:
    problems = werdykt_pr.file_problems(verdict.format(head=HEAD, short=HEAD[:7]), HEAD)

    assert "; ".join(problems) == reason.format(head=HEAD, short=HEAD[:7])


def test_werdykt_niezgodny_z_regulami_nie_trafia_na_pr_a_odmowa_podaje_wszystkie_przyczyny_i_plik(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    _deploy_template(github)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(MANY_PROBLEMS, encoding="utf-8")

    answered = github.run("1", "--werdykt", str(path))

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered).startswith(f"WERDYKT ODMOWA | #1 | {MANY_REASONS.format(head=head)}; ")
    assert "brak „## Sprawdzone”" in _last_line(answered)
    assert _last_line(answered).endswith(f"; popraw {path} i uruchom ponownie")
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
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"}, parent=_short_github_timeout(github))
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


# Szablon werdyktu (ADR 0031, decyzja Q9): treść pod dwiema pierwszymi liniami czyta renderer GitHuba, a w testach
# zastępuje go HTML z ``tests/fixtures/werdykty_szablonu.json``.
ROOTS = frozenset({"R-BEZ-TESTU", "R-DRUGA-DROGA"})


def _template_problems(text: str, declared: tuple[int, int] = (1, 1)) -> list[str]:
    return szablon_werdyktu.problems(werdykty_szablonu.html(text), declared, lambda: ROOTS)


@pytest.mark.parametrize("text", werdykty_szablonu.PRZECHODZA.values(), ids=werdykty_szablonu.PRZECHODZA)
def test_tresc_werdyktu_w_szablonie_przechodzi_takze_z_cytatem_pola_w_bloku_kodu(text: str) -> None:
    assert _template_problems(text) == []


@pytest.mark.parametrize(("text", "declared", "fragment"), werdykty_szablonu.ODMOWY.values(), ids=werdykty_szablonu.ODMOWY)
def test_tresc_werdyktu_poza_szablonem_daje_przyczyne_i_wzor(text: str, declared: tuple[int, int], fragment: str) -> None:
    problems = _template_problems(text, declared)

    assert any(fragment in problem for problem in problems[:-1]), problems
    assert problems[-1].startswith("wzór (.agents/skills/przeglad/SKILL.md): WERDYKT: FAIL <pełny SHA HEAD> / Znaleziska: "), problems[-1]
    assert "### W1." in problems[-1] and "## Sprawdzone" in problems[-1], problems[-1]


@pytest.mark.parametrize(("name", "expected"), [(name, idiom) for name, (_, idiom) in werdykty_szablonu.IDIOMY.items()], ids=werdykty_szablonu.IDIOMY)
def test_pole_idiom_wazne_daje_regule_klase_i_wczesniejsze_wazne_z_jednej_z_trzech_postaci(
    name: str, expected: tuple[str | None, str | None, tuple[int, str, int] | None]
) -> None:
    """Pole ``Idiom:`` (ADR 0036, „Pole werdyktu”) pisze recenzent po Szczeblu, a warunek merge'a bierze z niego id
    reguły i wcześniejsze Ważne, którego przypadek jej dowód ma złapać."""

    found = szablon_werdyktu.findings(szablon_werdyktu.items(werdykty_szablonu.html(werdykty_szablonu.PRZECHODZA[f"idiom-{name}"])))

    assert found.idioms == (szablon_werdyktu.Idiom("W1", *expected),)


def test_kazda_tresc_werdyktu_testow_ma_html_z_renderera_githuba() -> None:
    assert sorted(werdykty_szablonu.rendered()) == sorted(set(werdykty_szablonu.bodies())), "odśwież: .venv/bin/python tests/fixtures/werdykty_szablonu.py"


def test_werdykt_bez_pola_korzen_nie_czyta_listy_kodow() -> None:
    def unread() -> frozenset[str]:
        raise AssertionError("lista kodów czytana bez pola Korzeń")

    assert szablon_werdyktu.problems(werdykty_szablonu.html(werdykty_szablonu.WERDYKTY["sprawdzone"]), (0, 0), unread) == []


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ('[R-DOBRY]\nopis = "Zdanie."\nprzyklad = 1\n[r-male]\nopis = "Zdanie."\nprzyklad = 2\n', "r-male"),
        ('[R-BEZ-OPISU]\nprzyklad = 1\n', "R-BEZ-OPISU"),
        ('[R-PUSTY]\nopis = " "\nprzyklad = 1\n', "R-PUSTY"),
        ('[R-BEZ-PR]\nopis = "Zdanie."\nprzyklad = "#1"\n', "R-BEZ-PR"),
        ('[R-PR-ZERO]\nopis = "Zdanie."\nprzyklad = 0\n', "R-PR-ZERO"),
        ('[R-NADMIAR]\nopis = "Zdanie."\nprzyklad = 1\nszczebel = "c"\n', "R-NADMIAR"),
        ('R-PLASKI = "Zdanie."\n', "R-PLASKI"),
    ],
    ids=["kod-malymi-literami", "bez-opisu", "pusty-opis", "przyklad-tekstem", "przyklad-zero", "dodatkowe-pole", "wpis-bez-tabeli"],
)
def test_lista_korzeni_z_wpisem_poza_postacia_sie_nie_wczytuje(entry: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        szablon_werdyktu.listed_codes(entry)


def test_lista_korzeni_w_repo_ma_kody_z_opisem_i_przykladem_pr() -> None:
    assert "R-BEZ-TESTU" in szablon_werdyktu.listed_codes((REVIEW / "korzenie.toml").read_text(encoding="utf-8"))


NEW_CODE = '\n[R-NOWY-KOD]\nopis = "Kod dodany w tym PR."\nprzyklad = 1\n'


@pytest.mark.parametrize(
    ("listed", "root", "published", "reason"),
    [
        ("", 0, True, None),
        (NEW_CODE, 1, True, None),
        (NEW_CODE, 2, False, "W1: NOWY R-NOWY-KOD: ten kod jest już na liście .agents/skills/przeglad/korzenie.toml, napisz go bez NOWY"),
        ("", 3, False, "W1: kod R-NOWY-KOD spoza listy"),
        ("", 4, True, None),
        ("", 5, False, "W1: NOWY R-BEZ-TESTU: ten kod jest już na liście .agents/skills/przeglad/korzenie.toml, napisz go bez NOWY"),
        ('\n[r-male]\nopis = "Zdanie."\nprzyklad = 1\n', 4, False, "się nie wczytuje: „r-male” to nie kod"),
    ],
    ids=["nowy-spoza-listy", "kod-dodany-przez-head", "nowy-dodany-przez-head", "kod-spoza-listy", "kod-z-listy", "nowy-z-listy", "nieczytelna-lista"],
)
def test_werdykt_z_korzeniem_trafia_na_pr_tylko_z_kodem_listy_head_a_nowy_tylko_spoza_niej(
    tmp_path: Path, listed: str, root: int, published: bool, reason: str | None
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    _deploy_template(github)
    codes = (REVIEW / "korzenie.toml").read_text(encoding="utf-8") + listed
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n", ".agents/skills/przeglad/korzenie.toml": codes})
    path = tmp_path / "runda-1.md"
    path.write_text(f"WERDYKT: FAIL {head}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n{werdykty_szablonu.WERDYKTY[f'korzen-{root}']}\n", encoding="utf-8")

    answered = github.run("1", "--werdykt", str(path))

    assert (answered.returncode == 0) == published, answered.stdout + answered.stderr
    assert len(github.published()) == published
    if reason is not None:
        assert _last_line(answered).startswith("WERDYKT ODMOWA | #1 | "), answered.stdout
        assert reason in _last_line(answered), answered.stdout


# Decyzja Q20: szablon obowiązuje od pierwszego werdyktu po wdrożeniu, a wątek, którego najstarszy werdykt jest
# starszy od wdrożenia, kończy po staremu. Werdykty ``_written`` powstają 24.10.2026 o 3:00:00, 3:00:01 i dalej.
BEFORE_FIRST = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
AFTER_FIRST = datetime(2026, 10, 24, 3, 0, 1, tzinfo=UTC)
FAIL_OLD = f"WERDYKT: FAIL {OLD}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n- Ważne: brak testu"


@pytest.mark.parametrize(
    ("verdicts", "deployed", "applies"),
    [
        ([], None, False),
        ([("comment", FAIL_OLD), ("comment", PASS_HEAD)], None, False),
        ([], AFTER_FIRST, True),
        ([("comment", FAIL_OLD), ("comment", PASS_HEAD)], BEFORE_FIRST, True),
        ([("comment", FAIL_OLD), ("comment", PASS_HEAD)], AFTER_FIRST, False),
        ([("COMMENTED", FAIL_OLD), ("comment", PASS_HEAD)], AFTER_FIRST, False),
        ([("comment", FAIL_OLD, "CONTRIBUTOR"), ("comment", PASS_HEAD)], AFTER_FIRST, True),
        ([("comment", FAIL_OLD, "NONE"), ("comment", PASS_HEAD)], AFTER_FIRST, True),
        ([("PENDING", FAIL_OLD), ("comment", PASS_HEAD)], AFTER_FIRST, True),
        ([("comment", "Komentarz bez werdyktu."), ("comment", PASS_HEAD)], AFTER_FIRST, True),
        ([("CHANGES_REQUESTED", "Popraw nazwę."), ("comment", PASS_HEAD)], AFTER_FIRST, True),
        ([("comment", f"WERDYKT: FAIL {OLD[:7]}"), ("comment", PASS_HEAD)], AFTER_FIRST, True),
    ],
    ids=[
        "niewdrozony-bez-werdyktu",
        "niewdrozony-z-werdyktami",
        "pr-bez-werdyktu-po-wdrozeniu",
        "pierwszy-werdykt-po-wdrozeniu",
        "pierwszy-werdykt-przed-wdrozeniem",
        "pierwszy-werdykt-w-recenzji-przed-wdrozeniem",
        "stary-werdykt-kontrybutora-nie-postarza",
        "stary-werdykt-konta-bez-zwiazku-nie-postarza",
        "stara-nieopublikowana-recenzja-nie-postarza",
        "stary-komentarz-bez-werdyktu-nie-postarza",
        "stara-prosba-o-zmiany-bez-linii-werdyktu-nie-postarza",
        "stary-werdykt-ze-skroconym-sha-nie-postarza",
    ],
)
def test_szablon_obowiazuje_od_wdrozenia_a_watek_z_werdyktem_sprzed_niego_konczy_po_staremu(
    verdicts: list[tuple[str, ...]], deployed: datetime | None, applies: bool
) -> None:
    assert werdykt_pr.rule_applies(_written(*verdicts), deployed) is applies


@pytest.mark.parametrize(
    "verdicts",
    [
        [(PASS_HEAD, True)],
        [(FAIL_OLD, True), (PASS_HEAD, False)],
    ],
    ids=["komentarz-zmieniony-na-pass", "komentarz-zmieniony-na-fail-potem-reczny-pass"],
)
def test_komentarz_sprzed_wdrozenia_zmieniony_na_werdykt_nie_postarza_watku_a_reczny_pass_bez_szablonu_to_odmowa(
    verdicts: list[tuple[str, bool]],
) -> None:
    comments = [
        {**_verdict("comment", body, when=f"2026-10-24T03:00:{index:02d}Z"), "includesCreatedEdit": edited}
        for index, (body, edited) in enumerate(verdicts)
    ]
    pull = _pull(comments=comments)

    assert werdykt_pr.rule_applies(pull, AFTER_FIRST) is True
    assert (werdykt_pr.consent_problem(pull, AFTER_FIRST) or "").startswith(f"werdykt: PASS dla {HEAD[:7]} nie przechodzi reguł --werdykt (")


SPRAWDZONE_PASS = "WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["sprawdzone"] + "\n"
PROSE_PASS = "WERDYKT: PASS {head}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["proza"] + "\n"


@pytest.mark.parametrize(
    ("merged", "earlier", "verdict", "template"),
    [
        (None, None, PASS, False),
        ("2026-10-24T12:00:00Z", FAIL_OLD, PASS, False),
        ("2026-10-01T00:00:00Z", None, PASS, True),
        ("2026-10-01T00:00:00Z", FAIL_OLD, PASS, True),
        ("2026-10-01T00:00:00Z", FAIL_OLD, PROSE_PASS, True),
        ("2026-10-24T03:00:01Z", "Komentarz bez werdyktu.", PASS, True),
        ("2026-10-01T00:00:00Z", None, SPRAWDZONE_PASS, True),
    ],
    ids=[
        "niewdrozony",
        "watek-sprzed-wdrozenia",
        "pr-bez-werdyktu-po-wdrozeniu",
        "pierwszy-reczny-werdykt-bez-szablonu-po-wdrozeniu",
        "pass-z-proza-po-wdrozeniu",
        "komentarz-bez-werdyktu-nie-postarza",
        "pass-w-szablonie-po-wdrozeniu",
    ],
)
def test_ta_sama_regula_szablonu_rozstrzyga_publikacje_i_zgode_na_merge_takze_dla_pass_opublikowanego_recznie(
    tmp_path: Path, merged: str | None, earlier: str | None, verdict: str, template: bool
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    if merged is not None:
        _deploy_template(github, authored="2026-10-01T00:00:00Z", merged=merged)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    if earlier is not None:
        github.comment(1, earlier)
    path = tmp_path / "runda-2.md"
    path.write_text(verdict.format(head=head), encoding="utf-8")
    passes = not template or verdict == SPRAWDZONE_PASS

    answered = github.run("1", "--werdykt", str(path))
    if not passes:
        github.comment(1, verdict.format(head=head))
    checked = github.run("1", "--bez-merge")

    assert (answered.returncode == 0) == passes, answered.stdout + answered.stderr
    assert len(github.published()) == passes
    assert (checked.returncode == 0) == passes, checked.stdout + checked.stderr
    if not passes:
        assert f"werdykt: PASS dla {head[:7]} nie przechodzi reguł --werdykt (" in _last_line(checked), checked.stdout
        assert "wzór (.agents/skills/przeglad/SKILL.md): WERDYKT: FAIL <pełny SHA HEAD>" in _last_line(checked), checked.stdout
        assert _last_line(answered).startswith("WERDYKT ODMOWA | #1 | "), answered.stdout


# Reguły werdyktu w checkoucie, który nie jest ``origin/main``: gałąź sprzed wdrożenia szablonu (#1489) go nie zna,
# a gałąź, która zaostrza regułę, odrzuca każdy werdykt.
WITHOUT_TEMPLATE = ("tools/lib/szablon_werdyktu.py", (f'ADR = "{szablon_werdyktu.ADR}"', 'ADR = "docs/adr/brak.md"'))
STRICTER = ("tools/lib/werdykt_pr.py", ("MAX_MINOR = 3", "MAX_MINOR = -1"))
# Atrapa ruff i mypy scalenia, która pada bez wyniku, gdy dostała znacznik kopii bazy: procesy potomne kopii go nie
# dziedziczą, bo inaczej test scalenia z testami tego narzędzia odmawiałby w każdym checkoucie poza bazą.
CHECKS_WITHOUT_COPY_MARKER = "import os\n\nassert 'SCAL_PR_Z_KOPII_BAZY' not in os.environ\nprint('CI LOKALNIE OK')\n"


def _checkout_of(github: MergeGitHub, commit: str, tmp_path: Path) -> Path:
    """Odłączony checkout ``commit`` obok checkoutu ``main``, jak checkout recenzenta na HEAD PR."""

    checkout = tmp_path / "recenzent"
    git(github.checkout, "worktree", "add", "--quiet", "--detach", str(checkout), commit)
    return checkout


def _run_from(github: MergeGitHub, checkout: Path, *arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(checkout / "tools" / "scal_pr.py"), *arguments],
        cwd=checkout,
        env={**github.environment(), **(environment or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize(
    ("where", "rules", "verdict", "passes"),
    [
        ("head-pr", WITHOUT_TEMPLATE, PROSE_PASS, False),
        ("main-ze-zmiana", WITHOUT_TEMPLATE, PROSE_PASS, False),
        ("head-pr", STRICTER, SPRAWDZONE_PASS, True),
    ],
    ids=["galaz-sprzed-szablonu-jak-1489", "checkout-main-ze-zmiana-regul", "pr-zaostrza-regule"],
)
def test_werdykt_i_merge_z_checkoutu_innego_niz_baza_sadzi_kod_bazy_z_origin(
    tmp_path: Path, where: str, rules: tuple[str, tuple[str, str]], verdict: str, passes: bool
) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, "tools/ci_lokalnie.py": CHECKS_WITHOUT_COPY_MARKER})
    _deploy_template(github)
    main = git(github.origin, "rev-parse", "refs/heads/main")
    name, replaced = rules
    tool = github.checkout / name
    if where == "head-pr":
        old = tool.read_text(encoding="utf-8")
        head = github.open_pull(1, {name: old.replace(*replaced), "kod/inne.py": "INNE: int = 1\n"})
        checkout = _checkout_of(github, head, tmp_path)
    else:
        head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
        tool.write_text(tool.read_text(encoding="utf-8").replace(*replaced), encoding="utf-8")
        checkout = github.checkout
    path = tmp_path / "runda-1.md"
    path.write_text(verdict.format(head=head), encoding="utf-8")

    answered = _run_from(github, checkout, "1", "--werdykt", str(path))
    if not passes:
        github.comment(1, verdict.format(head=head))
    checked = _run_from(github, checkout, "1", "--bez-merge")

    here = f"{head[:7]}" if where == "head-pr" else f"{main[:7]} ze zmianami"
    judge = f"SĘDZIA | #1 | reguły z origin/main {main[:7]}, nie z checkoutu {here}: biegnę z kopii tego commitu"
    for run in (answered, checked):
        assert run.stdout.splitlines()[0] == judge, run.stdout + run.stderr
    assert (answered.returncode == 0) == passes, answered.stdout + answered.stderr
    assert len(github.published()) == passes
    assert (checked.returncode == 0) == passes, checked.stdout + checked.stderr
    if not passes:
        assert _last_line(answered).startswith("WERDYKT ODMOWA | #1 | "), answered.stdout
        assert f"werdykt: PASS dla {head[:7]} nie przechodzi reguł --werdykt (" in _last_line(checked), checked.stdout


def test_kopia_bazy_nie_uruchamia_nastepnej_kopii_gdy_baza_przesunela_sie_przed_jej_sprawdzeniem(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    path = tmp_path / "runda-1.md"
    path.write_text(PASS.format(head=head), encoding="utf-8")
    checkout = _checkout_of(github, github.start, tmp_path)
    github.push_main({"kod/nazwa.py": 'NAZWA = "z main"\n'})

    answered = _run_from(github, checkout, "1", "--werdykt", str(path), environment={"SCAL_PR_Z_KOPII_BAZY": "1"})

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert answered.stdout.splitlines() == ["WERDYKT ODMOWA | #1 | main zmienił się w trakcie sprawdzania, uruchom ponownie"]
    assert github.published() == []


@pytest.mark.parametrize("answer", ["gh: HTTP 502", "\n"], ids=["blad-http", "pusta-odpowiedz"])
def test_pass_w_watku_z_szablonem_bez_html_tresci_od_githuba_nie_jest_zgoda_a_odmowa_podaje_przyczyne(tmp_path: Path, answer: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    _deploy_template(github)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.markdown[werdykty_szablonu.WERDYKTY["sprawdzone"]] = answer
    github.comment(1, SPRAWDZONE_PASS.format(head=head))

    checked = github.run("1", "--bez-merge")

    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert f"werdykt: PASS dla {head[:7]} nie przechodzi reguł --werdykt (GitHub nie wyrenderował treści werdyktu (" in _last_line(checked), checked.stdout


# Bramka korzenia (ADR 0031, decyzje Q8, Q10, Q14, Q17, Q18, Q20, Q25, Q26): po FAIL z Ważnym albo przy naprawie
# czerwonego main opis PR ma sekcję „## Korzeń” z blokiem na każde Ważne według wzoru „Root section” skilla pr.
FAIL_W1 = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne"]
FAIL_NEW_CODE = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["korzen-0"]
PASS_RESOLVES = "WERDYKT: PASS {commit}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n" + korzenie_pr.WERDYKTY["rozstrzyga-w1-r1"]
FAIL_WITHOUT_ROOT = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + korzenie_pr.WERDYKTY["wazne-bez-korzenia"]
PASS_RESOLVES_NEW = "WERDYKT: PASS {commit}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n" + korzenie_pr.WERDYKTY["rozstrzyga-nowym-kodem"]
# FAIL opublikowany poza --werdykt: kod spoza listy bez NOWY, bez linii Znaleziska, z Ważne 0 i z dwoma Ważnymi prozą.
FAIL_UNLISTED = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["korzen-3"]
FAIL_PROSE = "WERDYKT: FAIL {commit}\nTest nie łapie regresji w kod/inne.py:1.\n"
FAIL_MAJORS_0 = "WERDYKT: FAIL {commit}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n"
FAIL_TWO_MAJORS = "WERDYKT: FAIL {commit}\nZnaleziska: 2 (Ważne 2, Drobne 0)\n" + korzenie_pr.WERDYKTY["wazne-bez-korzenia"]
SECTION_FOR_FAIL = "korzeń: brak sekcji „## Korzeń”, a PR ma werdykt FAIL z Ważnym; brak bloku „### W1 r1: R-KOD”"
UNLISTED = "nie stoi na liście .agents/skills/przeglad/korzenie.toml na HEAD: użyj kodu z listy albo dopisz go z opisem i przykładem PR"
NEW_POINT = "korzeń: W1 r1: Szczebel (e) wymaga nowego punktu z linkiem do tego PR (#1) dopisanego w tym PR do sekcji „Co jest porażką”"
RED = {korzenie_pr.RED_MAIN: "czerwony-main"}
FLAKY = {korzenie_pr.FLAKY: "flaky-test"}
UPROOTED_IN = f"korzeń: W1 r1: Wyrwany w #{korzenie_pr.ROOT_PR}"
GATE_BEFORE_VERDICTS = "2026-09-01T00:00:00Z"


def _root_gate(
    tmp_path: Path, verdicts: list[str], body: str, setup: dict[str, object], *, gate: str = GATE_BEFORE_VERDICTS, edited: bool = False
) -> subprocess.CompletedProcess[str]:
    """``--bez-merge`` PR 1 z werdyktami ``verdicts`` (na starszym commicie, więc PR nie ma zgody, a pierwszy powstaje
    24.10.2026 o 3:00:01, w komentarzu edytowanym, gdy ``edited``) i opisem ``body`` z ``korzenie_pr.OPISY``, z bramką
    korzenia wdrożoną na ``main`` w chwili ``gate``, a szablonem 1.10.2026; ``setup`` podaje stan i opis PR korzenia
    (``root``: stan, opis i opcjonalnie gałąź, do której go scalono, domyślnie ``main``), domyślną gałąź repozytorium
    albo błąd ``gh repo view`` (``repo_view``), etykiety issues (``labels``), skill ``przeglad`` na bazie (``skill_base``,
    domyślnie ``baza``) i na HEAD (``skill``) i kod dopisany do listy korzeni na HEAD (``listed``)."""

    skill = korzenie_pr.SKILL[str(setup.get("skill_base", "baza"))]
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM, szablon_werdyktu.SKILL.relative_to(TOOLS.parent).as_posix(): skill}, started=gate)
    _deploy_template(github)
    files = {"kod/inne.py": "INNE: int = 1\n"}
    if "skill" in setup:
        files[szablon_werdyktu.SKILL.relative_to(TOOLS.parent).as_posix()] = korzenie_pr.SKILL[str(setup["skill"])]
    if "listed" in setup:
        files[szablon_werdyktu.LIST] = (REVIEW / "korzenie.toml").read_text(encoding="utf-8") + str(setup["listed"])
    github.open_pull(1, files)
    github.update(1, body=korzenie_pr.OPISY[body])
    if "root" in setup:
        state, root_body, *merged_into = cast(tuple[str, ...], setup["root"])
        root = _pr_view(korzenie_pr.ROOT_PR, OLD, state=state, body=korzenie_pr.PR_KORZENIA[root_body], baseRefName=next(iter(merged_into), "main"))
        github.pulls[str(korzenie_pr.ROOT_PR)] = root
    if "repo_view" in setup:
        github.repo_view = str(setup["repo_view"])
    for number, label in cast(dict[int, str], setup.get("labels", {})).items():
        github.answer_issue(number, answer=json.dumps({"state": "closed", "labels": [{"name": label}]}))
    for index, verdict in enumerate(verdicts):
        if edited and index == 0:
            github.edited_comment(1, verdict.format(commit=OLD))
        else:
            github.comment(1, verdict.format(commit=OLD))
    return github.run("1", "--bez-merge")


@pytest.mark.parametrize(
    ("verdicts", "body", "setup", "fragments"),
    [
        ([FAIL_W1], "bez-sekcji", {}, ["korzeń: brak sekcji „## Korzeń”, a PR ma werdykt FAIL z Ważnym; brak bloku „### W1 r1: R-BEZ-TESTU”"]),
        ([FAIL_W1], "szczebel-c", {}, []),
        ([FAIL_W1], "szczebel-a", {}, []),
        ([FAIL_W1], "szczebel-b-wyzej-w-linii-pola", {}, []),
        (
            [FAIL_W1],
            "blok-innego-waznego",
            {},
            ["korzeń: brak bloku „### W1 r1: R-BEZ-TESTU”", "korzeń: blok „### W2 r1: R-BEZ-TESTU”, a PR nie ma takiego Ważnego ani czerwonego main"],
        ),
        ([FAIL_W1], "blok-dwa-razy", {}, ["korzeń: blok „### W1 r1: R-BEZ-TESTU” powtórzony"]),
        ([FAIL_W1], "inny-kod", {}, ["korzeń: W1 r1: kod R-DRUGA-DROGA, a ostatni werdykt, który go dotyczy, podaje R-BEZ-TESTU"]),
        ([FAIL_W1, PASS_RESOLVES], "kod-rozstrzygniety", {}, []),
        ([FAIL_W1, PASS_RESOLVES], "szczebel-c", {}, ["korzeń: W1 r1: kod R-BEZ-TESTU, a ostatni werdykt, który go dotyczy, podaje R-DRUGA-DROGA"]),
        ([FAIL_W1], "szczebel-c-bez-wyzej-nie", {}, ["korzeń: W1 r1: po Szczeblu (c) linia „Wyżej nie, bo: (a) - zdanie” z jedną linią na każdy wyższy szczebel (a), (b)"]),
        ([FAIL_W1], "szczebel-c-bez-zdania-dla-b", {}, ["korzeń: W1 r1: „Wyżej nie, bo:” ma jedną linię „(x) - zdanie” na każdy wyższy szczebel (a), (b) po kolei"]),
        ([FAIL_W1], "szczebel-a-z-wyzej-nie", {}, ["korzeń: W1 r1: przy (a) nie ma wyższego szczebla"]),
        ([FAIL_W1], "bez-dowodu", {}, ["korzeń: W1 r1: brak pola „Dowód: <polecenie i wynik>” na końcu bloku"]),
        ([FAIL_W1], "bez-szczebla", {}, ["korzeń: W1 r1: pierwsza linia bloku to „Szczebel: (a) - mechanizm” ze szczeblem od (a) do (e) albo „Wyrwany w #M”"]),
        ([FAIL_W1], "szczebel-e", {}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill": "punkt-z-linkiem-do-pr"}, []),
        ([FAIL_W1], "szczebel-e", {"skill": "punkt-z-przykladem"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill": "punkt-bez-przykladu"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill": "punkt-z-przykladem-poza-sekcja"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill_base": "punkt-z-przykladem"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill_base": "punkt-z-przykladem", "skill": "punkt-z-przykladem-zmieniony-z-linkiem-do-pr"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill": "punkt-z-linkiem-do-pr-i-zmieniony-punkt-bazy"}, [NEW_POINT]),
        ([FAIL_W1], "szczebel-e", {"skill_base": "punkt-z-przykladem", "skill": "punkty-bazy-zamienione-z-linkiem-do-pr"}, [NEW_POINT]),
        ([FAIL_W1], "cytat-pola-w-bloku-kodu", {}, []),
        ([FAIL_W1], "cytat-pola-bez-bloku-kodu", {}, ["korzeń: blok „### W1 r1: R-DRUGA-DROGA” powtórzony"]),
        ([FAIL_W1], "wyrwany", {"root": ("OPEN", "ten-kod")}, [f"{UPROOTED_IN}: PR korzenia jest otwarty, a scala się go do domyślnej gałęzi przed tym PR"]),
        ([FAIL_W1], "wyrwany", {"root": ("CLOSED", "ten-kod")}, [f"{UPROOTED_IN}: PR korzenia jest zamknięty bez merge'a"]),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "inny-kod")}, [f"{UPROOTED_IN}: opis PR korzenia nie ma linii „Korzeń z #1: R-BEZ-TESTU” z linkiem do tego PR"]),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "inny-pr")}, [f"{UPROOTED_IN}: opis PR korzenia nie ma linii „Korzeń z #1: R-BEZ-TESTU”"]),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "ten-kod")}, []),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "ten-kod", "feat/stos")}, [f"{UPROOTED_IN}: PR korzenia scalony do feat/stos, a nie do domyślnej gałęzi main"]),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "ten-kod"), "repo_view": _repo_view("trunk")}, [f"{UPROOTED_IN}: PR korzenia scalony do main, a nie do domyślnej gałęzi trunk"]),
        ([FAIL_W1], "wyrwany", {"root": ("MERGED", "ten-kod"), "repo_view": "gh: HTTP 502"}, [f"{UPROOTED_IN}: GitHub nie podał domyślnej gałęzi repozytorium"]),
        ([FAIL_W1], "wyrwany", {}, [f"{UPROOTED_IN}: GitHub nie podał stanu PR"]),
        ([FAIL_W1], "wyrwany-z-dowodem", {"root": ("MERGED", "ten-kod")}, [f"korzeń: W1 r1: po „Wyrwany w #{korzenie_pr.ROOT_PR}” nic więcej, a jest linia „{korzenie_pr.EVIDENCE}”"]),
        ([FAIL_W1], "wyrwany-bez-linku", {}, ["korzeń: W1 r1: Wyrwany w #9999999 bez linku GitHuba do PR tego repo"]),
        ([FAIL_W1], "wyrwany-w-issue", {}, [f"korzeń: W1 r1: Wyrwany w #{korzenie_pr.RED_MAIN} bez linku GitHuba do PR tego repo"]),
        ([FAIL_NEW_CODE], "nowy-kod", {}, [f"korzeń: kod R-NOWY-KOD (NOWY z werdyktu, blok „### W1 r1”) {UNLISTED}"]),
        ([FAIL_NEW_CODE], "nowy-kod", {"listed": NEW_CODE}, []),
        ([FAIL_W1, PASS_RESOLVES_NEW], "nowy-kod", {}, [f"korzeń: kod R-NOWY-KOD (NOWY z werdyktu, blok „### W1 r1”) {UNLISTED}"]),
        ([FAIL_UNLISTED], "nowy-kod", {}, [f"korzeń: kod R-NOWY-KOD (blok „### W1 r1”) {UNLISTED}"]),
        ([FAIL_UNLISTED], "nowy-kod", {"listed": NEW_CODE}, []),
        ([], "czerwony-main-bez-sekcji", {"labels": RED}, [f"korzeń: brak sekcji „## Korzeń”, a PR ma naprawę czerwonego main; brak bloku „### Czerwony main #{korzenie_pr.RED_MAIN}: R-KOD”"]),
        ([], "czerwony-main", {"labels": RED}, []),
        ([], "czerwony-main-kod-spoza-listy", {"labels": RED}, [f"korzeń: kod R-WYMYSLONY-KOD (blok „### Czerwony main #{korzenie_pr.RED_MAIN}”) {UNLISTED}"]),
        ([], "czerwony-main-bez-sekcji", {}, [f"korzeń: GitHub nie podał etykiet #{korzenie_pr.RED_MAIN}, więc nie wiadomo, czy to czerwony main"]),
        ([PASS_RESOLVES], "bez-sekcji", {}, ["korzeń: punkt „Korzeń W1 r1: R-DRUGA-DROGA” werdyktu r1 nie wskazuje Ważnego werdyktu FAIL tej albo wcześniejszej rundy"]),
        ([FAIL_WITHOUT_ROOT], "szczebel-c", {}, ["korzeń: W1 r1: werdykt nie podaje kodu korzenia w szablonie, więc kod podaje recenzent następnej rundy punktem „Korzeń W1 r1: R-KOD - zdanie”"]),
        ([FAIL_WITHOUT_ROOT, PASS_RESOLVES], "kod-rozstrzygniety", {}, []),
        ([FAIL_PROSE], "bez-sekcji", {}, [SECTION_FOR_FAIL]),
        ([FAIL_MAJORS_0], "bez-sekcji", {}, [SECTION_FOR_FAIL]),
        ([FAIL_PROSE], "szczebel-c", {}, ["korzeń: W1 r1: werdykt nie podaje kodu korzenia w szablonie"]),
        ([FAIL_PROSE, PASS_RESOLVES], "kod-rozstrzygniety", {}, []),
        ([FAIL_TWO_MAJORS, PASS_RESOLVES], "kod-rozstrzygniety", {}, ["korzeń: brak bloku „### W2 r1: R-KOD”"]),
        ([FAIL_W1], "proza-w-sekcji", {}, ["korzeń: w sekcji „## Korzeń” przed blokiem jest linia „Korzeń wyrwany w tym PR.”"]),
        ([FAIL_W1], "naglowek-poza-wzorem", {}, ["korzeń: nagłówek „### W1: R-BEZ-TESTU” to nie „### W<n> r<runda>: R-KOD”", "korzeń: brak bloku „### W1 r1: R-BEZ-TESTU”"]),
        ([FAIL_W1], "dowod-6-linii", {}, ["korzeń: W1 r1: Dowód ma 6 linii, najwyżej 5"]),
        ([], "flaky-test", {"labels": FLAKY}, []),
    ],
    ids=[
        "brak-sekcji",
        "szczebel-c-z-wyzej-nie-i-dowodem",
        "szczebel-a-bez-wyzej-nie",
        "szczebel-b-ze-zdaniem-w-linii-pola",
        "brak-bloku-dla-waznego",
        "blok-powtorzony",
        "kod-inny-niz-w-werdykcie",
        "kod-rozstrzygniety-pozniejszym-werdyktem",
        "kod-sprzed-rozstrzygniecia",
        "szczebel-c-bez-wyzej-nie",
        "szczebel-c-bez-zdania-dla-b",
        "szczebel-a-z-wyzej-nie",
        "bez-dowodu",
        "bez-szczebla",
        "szczebel-e-bez-punktu-w-skillu",
        "szczebel-e-z-nowym-punktem-z-linkiem-do-pr",
        "szczebel-e-z-punktem-z-przykladem-innego-pr",
        "szczebel-e-z-punktem-bez-przykladu",
        "szczebel-e-z-punktem-poza-sekcja",
        "szczebel-e-z-punktem-ktory-byl-na-bazie",
        "szczebel-e-z-punktem-bazy-zmienionym-o-link-do-pr",
        "szczebel-e-z-nowym-punktem-i-zmienionym-punktem-bazy",
        "szczebel-e-z-nowym-punktem-i-punktami-bazy-w-innej-kolejnosci",
        "cytat-pola-w-bloku-kodu",
        "cytat-pola-bez-bloku-kodu",
        "wyrwany-w-otwartym-pr",
        "wyrwany-w-zamknietym-bez-merge",
        "wyrwany-w-pr-z-innym-kodem",
        "wyrwany-w-pr-z-linia-innego-pr",
        "wyrwany-w-scalonym-pr-z-tym-kodem",
        "wyrwany-w-pr-scalonym-do-galezi-stosu",
        "wyrwany-w-pr-scalonym-poza-domyslna-galaz",
        "wyrwany-bez-domyslnej-galezi-z-githuba",
        "wyrwany-bez-stanu-pr-korzenia-z-githuba",
        "wyrwany-z-czymkolwiek-dalej",
        "wyrwany-bez-linku",
        "wyrwany-w-issue",
        "nowy-kod-spoza-listy-head",
        "nowy-kod-na-liscie-head",
        "nowy-kod-z-rozstrzygniecia-spoza-listy",
        "kod-bloku-waznego-spoza-listy-head",
        "kod-bloku-waznego-na-liscie-head",
        "czerwony-main-bez-sekcji",
        "czerwony-main-z-blokiem",
        "czerwony-main-z-kodem-spoza-listy",
        "bez-etykiet-issue-z-githuba",
        "rozstrzygniecie-bez-waznego",
        "wazne-bez-kodu-w-szablonie",
        "wazne-bez-kodu-rozstrzygniete",
        "fail-bez-linii-znaleziska-bez-sekcji",
        "fail-z-wazne-0-bez-sekcji",
        "fail-bez-linii-znaleziska-z-blokiem-w1-bez-kodu",
        "fail-bez-linii-znaleziska-z-kodem-rozstrzygnietym",
        "blok-na-kazde-wazne-z-linii-znaleziska",
        "proza-w-sekcji-przed-blokiem",
        "naglowek-poza-wzorem",
        "dowod-6-linii",
        "flaky-test-bez-sekcji",
    ],
)
def test_bramka_korzenia_odmawia_merge_dopoki_sekcja_korzen_nie_ma_bloku_na_kazde_wazne_i_czerwony_main(
    tmp_path: Path, verdicts: list[str], body: str, setup: dict[str, object], fragments: list[str]
) -> None:
    answered = _root_gate(tmp_path, verdicts, body, setup)

    last = _last_line(answered)
    assert answered.returncode == 1 and last.startswith("SCAL ODMOWA | #1 "), answered.stdout + answered.stderr
    missing = [fragment for fragment in fragments if fragment not in last]
    assert missing == [], last
    assert ("korzeń:" in last) == bool(fragments), last
    assert ("wzór sekcji (.agents/skills/pr/SKILL.md): ## Korzeń / ### W1 r2: R-BEZ-TESTU / Szczebel: (c)" in last) == bool(fragments), last


# Decyzja Q20 dla bramki korzenia: wątki, które już pracują, kończą po swojemu, więc bramka liczy wątek od chwili
# własnego wdrożenia (merge, który dodał jej moduł), nie od wdrożenia szablonu 1.10.2026; pierwszy werdykt powstaje
# 24.10.2026 o 3:00:01, a werdykt w komentarzu edytowanym wątku nie postarza.
@pytest.mark.parametrize(
    ("gate", "edited", "required"),
    [
        ("2026-10-24T03:00:02Z", False, False),
        ("2026-10-24T03:00:01Z", False, True),
        ("2026-10-24T12:00:00Z", True, True),
    ],
    ids=["pierwszy-werdykt-przed-wdrozeniem-bramki", "pierwszy-werdykt-w-chwili-wdrozenia-bramki", "edytowany-werdykt-nie-postarza-watku"],
)
def test_bramka_korzenia_obowiazuje_w_watku_od_wlasnego_wdrozenia_a_nie_od_wdrozenia_szablonu(
    tmp_path: Path, gate: str, edited: bool, required: bool
) -> None:
    answered = _root_gate(tmp_path, [FAIL_W1], "bez-sekcji", {}, gate=gate, edited=edited)

    last = _last_line(answered)
    assert last.startswith("SCAL ODMOWA | #1 "), answered.stdout + answered.stderr
    assert ("korzeń: brak sekcji „## Korzeń”, a PR ma werdykt FAIL z Ważnym" in last) == required, last


def test_odmowa_bramki_korzenia_podaje_wzor_a_opis_poprawiony_bez_nowego_commita_i_werdyktu_daje_merge(tmp_path: Path) -> None:
    files = {"kod/__init__.py": SUM, szablon_werdyktu.SKILL.relative_to(TOOLS.parent).as_posix(): korzenie_pr.SKILL["baza"]}
    github = MergeGitHub(tmp_path, files, started=GATE_BEFORE_VERDICTS)
    _deploy_template(github)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=korzenie_pr.OPISY["bez-sekcji"])
    github.comment(1, FAIL_W1.format(commit=OLD))
    github.comment(1, SPRAWDZONE_PASS.format(head=head))

    refused = github.run("1", "--bez-merge")
    github.update(1, body=korzenie_pr.OPISY["szczebel-c"])
    merged = github.run("1")

    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert _last_line(refused).startswith(f"SCAL ODMOWA | #1 {head[:7]} | korzeń: brak sekcji „## Korzeń”"), refused.stdout
    assert _last_line(refused).endswith("; opis popraw przez gh pr edit 1 --body-file PLIK, bez nowego commita i bez nowego werdyktu"), refused.stdout
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert github.merges() == [["pr", "merge", "1", "--merge", "--match-head-commit", head]]


@pytest.mark.parametrize(
    ("verdict", "fragment"),
    [
        ("rozstrzyga-w1-r1", None),
        ("rozstrzyga-nowym-kodem", None),
        ("rozstrzyga-kodem-spoza-listy", "punkt „Korzeń W1 r1”: kod R-NIE-MA spoza listy"),
        ("rozstrzygniecie-bez-rundy", "punkt „Korzeń W1: R-DRUGA-DROGA - bez rundy.” to nie rozstrzygnięcie „Korzeń W<n> r<runda>: R-KOD - zdanie”"),
    ],
    ids=["kod-z-listy", "nowy-kod-spoza-listy", "kod-spoza-listy", "bez-rundy"],
)
def test_punkt_rozstrzygniecia_kodu_w_sprawdzone_przechodzi_tylko_z_runda_i_kodem_jak_pole_korzen(verdict: str, fragment: str | None) -> None:
    problems = szablon_werdyktu.problems(korzenie_pr.html(korzenie_pr.WERDYKTY[verdict]), (0, 0), lambda: ROOTS)

    assert (problems == []) == (fragment is None), problems
    assert fragment is None or any(fragment in problem for problem in problems), problems


def test_kazda_tresc_bramki_korzenia_ma_html_z_renderera_githuba() -> None:
    assert sorted(korzenie_pr.rendered()) == sorted(set(korzenie_pr.bodies())), "odśwież: .venv/bin/python -m tests.fixtures.korzenie_pr"


# Rejestr korzeni (ADR 0031, decyzje Q13, Q22, Q25): wystąpienie kodu to Ważne z kodem w werdykcie FAIL po wdrożeniu
# szablonu (1.10.2026 w ``_deploy_template``) albo blok czerwonego main w opisie PR scalonego po wdrożeniu.
AFTER_DEPLOYMENT = "2026-10-20T00:00:00Z"
BEFORE_DEPLOYMENT = "2026-09-20T00:00:00Z"
UPDATED = "2026-10-24T05:00:00Z"
DEPLOYED = datetime(2026, 10, 1, tzinfo=UTC)
FAIL_TWO_SAME = "WERDYKT: FAIL {commit}\nZnaleziska: 2 (Ważne 2, Drobne 0)\n" + chwasty.WERDYKTY["dwa-wazne-z-tym-samym-kodem"]
FAIL_OTHER_CODE = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + chwasty.WERDYKTY["inny-kod"]
RED_MAIN_BLOCK = f"Czerwony main #{korzenie_pr.RED_MAIN}"


def _node(
    verdicts: list[tuple[str, str]],
    *,
    body: str = "",
    merged: str | None = None,
    edited: bool = False,
    number: int = chwasty.OTHER,
    created: str = BEFORE_DEPLOYMENT,
    updated: str = UPDATED,
) -> dict[str, object]:
    """PR ``number`` z zapytania GraphQL rejestru korzeni: komentarze ``verdicts`` (treść i chwila utworzenia, w komentarzu
    edytowanym, gdy ``edited``), opis ``body``, chwila merge'a ``merged``, założenia ``created`` i ostatniej zmiany
    ``updated``."""

    comments = [{**_verdict("comment", text.format(commit=OLD), when=when), "includesCreatedEdit": edited} for text, when in verdicts]
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "MERGED" if merged else "OPEN",
        "isDraft": False,
        "isCrossRepository": False,
        "baseRefName": "main",
        "headRefOid": OLD,
        "url": f"https://github.com/{opisy_pr.REPO}/pull/{number}",
        "body": body,
        "createdAt": created,
        "updatedAt": updated,
        "mergedAt": merged,
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": comments},
        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    }


MERGED_B = _node([(FAIL_W1, AFTER_DEPLOYMENT)], body=korzenie_pr.OPISY["szczebel-b-wyzej-w-linii-pola"], merged=AFTER_DEPLOYMENT)


def _registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pulls: list[dict[str, object]], changes: list[dict[str, object]] | None = None) -> tuple[MergeGitHub, list[tuple[int, str, str]]]:
    """Wystąpienia z rejestru korzeni od wdrożenia szablonu ``DEPLOYED`` (PR, Ważne albo blok, kod), gdy zapytanie
    GraphQL podaje PR-y ``pulls``, a ``changes`` zmienia je między stronami."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    github.graphql = pulls
    github.graphql_changes = changes or []
    github._save()
    monkeypatch.setenv("PATH", github.environment()["PATH"])
    return github, [(found.pull, found.major, found.code) for found in rejestr_korzeni.read(opisy_pr.REPO, DEPLOYED)]


@pytest.mark.parametrize(
    ("pulls", "occurrences"),
    [
        ([MERGED_B], [(chwasty.OTHER, "W1 r1", chwasty.CODE)]),
        ([_node([(FAIL_W1, AFTER_DEPLOYMENT)])], [(chwasty.OTHER, "W1 r1", chwasty.CODE)]),
        ([_node([], body=korzenie_pr.OPISY["czerwony-main"], merged=AFTER_DEPLOYMENT)], [(chwasty.OTHER, RED_MAIN_BLOCK, chwasty.CODE)]),
        ([_node([(FAIL_W1, AFTER_DEPLOYMENT)], edited=True)], [(chwasty.OTHER, "W1 r1", chwasty.CODE)]),
        ([_node([(FAIL_W1, AFTER_DEPLOYMENT), (PASS_RESOLVES, AFTER_DEPLOYMENT)])], [(chwasty.OTHER, "W1 r1", "R-DRUGA-DROGA")]),
        ([_node([(FAIL_TWO_SAME, AFTER_DEPLOYMENT)])], [(chwasty.OTHER, "W1 r1", chwasty.CODE), (chwasty.OTHER, "W2 r1", chwasty.CODE)]),
        ([_node([(FAIL_W1, BEFORE_DEPLOYMENT)])], []),
        ([_node([(FAIL_W1, BEFORE_DEPLOYMENT)], edited=True)], []),
        ([_node([(PASS_RESOLVES, BEFORE_DEPLOYMENT), (FAIL_W1, AFTER_DEPLOYMENT)])], []),
        ([_node([], body=korzenie_pr.OPISY["czerwony-main"], merged=BEFORE_DEPLOYMENT)], []),
        ([_node([(FAIL_OTHER_CODE, AFTER_DEPLOYMENT)])], [(chwasty.OTHER, "W1 r1", "R-DRUGA-DROGA")]),
    ],
    ids=[
        "wazne-w-scalonym-pr",
        "wazne-w-otwartym-pr",
        "czerwony-main-scalonego-pr",
        "wazne-w-edytowanym-werdykcie-po-wdrozeniu",
        "kod-rozstrzygniety-na-inny",
        "dwa-wazne-z-tym-samym-kodem-w-jednym-werdykcie",
        "wazne-sprzed-wdrozenia",
        "edytowany-werdykt-sprzed-wdrozenia",
        "watek-z-pierwszym-werdyktem-sprzed-wdrozenia",
        "czerwony-main-scalony-przed-wdrozeniem",
        "inny-kod",
    ],
)
def test_rejestr_liczy_wazne_i_czerwony_main_po_wdrozeniu_szablonu_z_kodem_ostatniego_werdyktu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pulls: list[dict[str, object]], occurrences: list[tuple[int, str, str]]
) -> None:
    _, found = _registry(tmp_path, monkeypatch, pulls)

    assert found == occurrences


def test_rejestr_czyta_kazdy_pr_zmieniony_od_wdrozenia_takze_gdy_pr_zmienia_sie_miedzy_stronami(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """30 PR-ów to dwie strony, a #125 z drugiej strony (w kolejności założenia i w kolejności ostatniej zmiany)
    dostaje werdykt po pobraniu pierwszej, jak przy publikacji w trakcie skanu."""

    pulls = [_node([(FAIL_W1, AFTER_DEPLOYMENT)], number=number, created=f"2026-10-02T00:{number - 100:02d}:00Z", updated=f"2026-10-24T05:{130 - number:02d}:00Z") for number in range(100, 130)]

    _, found = _registry(tmp_path, monkeypatch, pulls, [{"po": 1, "number": 125, "pola": {"updatedAt": "2026-10-24T23:00:00Z"}}])

    assert [pull for pull, _, _ in found] == list(range(100, 130))


def test_rejestr_doczytuje_komentarze_pr_ponad_pierwsza_setke_zapytaniem_o_ten_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR #1 ma 150 komentarzy, a werdykt ``FAIL`` z kodem to 101. z nich, więc strona wyszukiwania go nie podaje:
    rejestr doczytuje komentarze tego PR z GraphQL po 100 od kursora, z HTML treści, bez renderowania."""

    comments = [*[("", AFTER_DEPLOYMENT)] * 100, (FAIL_W1, AFTER_DEPLOYMENT), *[("", AFTER_DEPLOYMENT)] * 49]

    github, found = _registry(tmp_path, monkeypatch, [MERGED_B, _node(comments, number=1)])

    assert found == [(1, "W1 r1", chwasty.CODE), (chwasty.OTHER, "W1 r1", chwasty.CODE)]
    assert [(query["number"], query["comments"]) for query in cast(list[dict[str, str]], github._log("pull_queries.jsonl"))] == [("1", "null"), ("1", "100")]
    assert github.renders() == []


def test_skan_rejestru_czyta_tylko_pr_zmienione_od_wdrozenia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """45 PR-ów zmienionych przed wdrożeniem szablonu (1.10.2026) skan pomija bez czytania: jedna strona z PR-em
    zmienionym po wdrożeniu."""

    before = [_node([], number=number, created=f"2026-09-02T00:{number - 100:02d}:00Z", updated=f"2026-09-30T23:{number - 100:02d}:00Z") for number in range(100, 145)]

    github, found = _registry(tmp_path, monkeypatch, [*before, _node([(FAIL_W1, AFTER_DEPLOYMENT)], number=1)])

    assert found == [(1, "W1 r1", chwasty.CODE)]
    assert len(github._log("graphql.jsonl")) == 1, github._log("graphql.jsonl")


# Warunek merge'a z polem Idiom: (ADR 0036, „Warunek merge'a”): dowód tools/na_scalonych_pr.py --regula-id z regułą
# z HEAD PR na każdym przypadku tego id z historii pól Idiom:. Dowód zastępuje atrapa ``FAKE_PROOF``: zapisuje swoje
# argumenty do ``dowody.jsonl`` w katalogu atrapy gh i kończy się kodem i linią z ``dowod.json``; prawdziwy dowód,
# także odmowę bez reguły na HEAD, sprawdza tests/test_na_scalonych_pr.py.
FAKE_PROOF = """\
import json, pathlib, sys

state = pathlib.Path(sys.argv[0]).resolve().parents[2] / "bin"
with (state / "dowody.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
answer = json.loads((state / "dowod.json").read_text(encoding="utf-8"))
print(answer["linia"])
sys.exit(answer["kod"])
"""
PROOF_OK = (0, "DOWÓD OK | zakazane-wywolanie | złapane 2/2 | FP 0 w 0 z 20 PR (0%) | main 0")
PROOF_REFUSED = (1, "DOWÓD ODMOWA | zakazane-wywolanie | złapane 1/2 | FP 0 w 0 z 20 PR (0%) | main 0")
PROOF_WITHOUT_RULE = (1, "DOWÓD ODMOWA | zakazane-wywolanie | na 12345678 nie ma reguły ast-grep o id zakazane-wywolanie w katalogach ruleDirs sgconfig.yml")


def _idiom_verdict(name: str) -> str:
    return "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY[f"wazne-idiom-{name}"]


def _idiom_gate(
    tmp_path: Path, verdict: str, *, registry: list[dict[str, object]] | None = None, proof: tuple[int, str] = PROOF_OK
) -> tuple[MergeGitHub, str, subprocess.CompletedProcess[str]]:
    """``--bez-merge`` PR 1 z werdyktem ``FAIL`` z polem Idiom (``_idiom_verdict``) na starszym commicie, sekcją
    ``## Korzeń`` i ``PASS`` na HEAD; rejestr podaje PR-y ``registry``, a dowód kończy się ``proof``."""

    files = {"kod/__init__.py": SUM, "tools/na_scalonych_pr.py": FAKE_PROOF}
    github = MergeGitHub(tmp_path, {**files, szablon_werdyktu.SKILL.relative_to(TOOLS.parent).as_posix(): korzenie_pr.SKILL["baza"]}, started=GATE_BEFORE_VERDICTS)
    _deploy_template(github)
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=korzenie_pr.OPISY["szczebel-c"])
    github.graphql = registry or []
    github._save()
    (github.bin / "dowod.json").write_text(json.dumps({"kod": proof[0], "linia": proof[1]}), encoding="utf-8")
    github.comment(1, verdict.format(commit=OLD))
    github.comment(1, SPRAWDZONE_PASS.format(head=head))
    return github, head, github.run("1", "--bez-merge")


def _proofs(github: MergeGitHub) -> list[list[str]]:
    return github._log("dowody.jsonl")


def _proof_arguments(head: str, *cases: str) -> list[str]:
    return ["--regula-id", "zakazane-wywolanie", "--z-commita", head, *(part for case in cases for part in ("--wazne", case))]


@pytest.mark.parametrize(
    "proof",
    [PROOF_WITHOUT_RULE, PROOF_REFUSED, (0, "DOWÓD ZAWIESZONY"), (1, PROOF_OK[1])],
    ids=["bez-reguly-na-head", "dowod-odmawia", "dowod-bez-linii-dowod-ok", "dowod-ok-z-kodem-bledu"],
)
def test_wazne_z_polem_idiom_nie_scala_sie_bez_dowodu_ok_reguly_z_head(tmp_path: Path, proof: tuple[int, str]) -> None:
    """Próbka ``ZNANE_LUKI`` nigdy nie zastępuje reguły (ADR 0036), a dowód przechodzi tylko kodem 0 i linią ``DOWÓD OK``."""

    github, head, answered = _idiom_gate(tmp_path, _idiom_verdict("drugie-wystapienie"), proof=proof)

    last = _last_line(answered)
    assert answered.returncode == 1 and last.startswith(f"SCAL ODMOWA | #1 {head[:7]} | idiom: zakazane-wywolanie: Ważne 1/W1/r1, 1553/W1/r2 ma pole Idiom: zakazane-wywolanie"), answered.stdout
    assert f"dowód reguły nie przeszedł (kod {proof[0]}): {proof[1]}; dodaj albo popraw regułę ast-grep o id zakazane-wywolanie" in last, last
    assert _proofs(github) == [_proof_arguments(head, "1/W1/r1", "1553/W1/r2")]


def test_wazne_z_polem_idiom_scala_sie_po_dowodzie_na_kazdym_przypadku_z_historii_pol_idiom(tmp_path: Path) -> None:
    """Przypadki dowodu to Ważne tego PR z polem, Ważne z jego ``jak`` i każde Ważne z polem tego id w innym PR rejestru
    razem z jego ``jak``; Ważne z polem innej reguły do dowodu nie należy."""

    registry = [
        _node([(_idiom_verdict("drugie-wystapienie"), AFTER_DEPLOYMENT)], number=chwasty.OTHER),
        _node([(_idiom_verdict("innej-reguly"), AFTER_DEPLOYMENT)], number=1437),
    ]

    github, head, answered = _idiom_gate(tmp_path, _idiom_verdict("ucieczka"), registry=registry)

    assert answered.returncode == 0 and _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} "), answered.stdout + answered.stderr
    assert _proofs(github) == [_proof_arguments(head, "1/W1/r1", f"{chwasty.OTHER}/W1/r1", "1553/W1/r2")]


@pytest.mark.parametrize(("verdict", "cases"), [("drugie-wystapienie", [("1/W1/r1", "1553/W1/r2")]), ("bez-reguly", [])], ids=["drugie-wystapienie", "bez-reguly"])
def test_pole_idiom_bez_reguly_niczego_nie_wymaga_a_drugie_wystapienie_dowodzi_ze_wczesniejszym_waznym(tmp_path: Path, verdict: str, cases: list[tuple[str, ...]]) -> None:
    github, head, answered = _idiom_gate(tmp_path, _idiom_verdict(verdict))

    assert answered.returncode == 0 and _last_line(answered).startswith(f"SCAL OK | #1 {head[:7]} "), answered.stdout + answered.stderr
    assert _proofs(github) == [_proof_arguments(head, *found) for found in cases]


@pytest.mark.parametrize(
    ("title", "closed", "suffix"),
    [
        (f"Chwast: {chwasty.CODE}", True, f" | zamknięte: #{chwasty.WEED_ISSUE} |"),
        ("Chwast: R-DRUGA-DROGA", False, f" | UWAGA: #{chwasty.WEED_ISSUE} z „Korzeń z” to nie otwarte issue „Chwast: R-KOD” z tym kodem, nie zamknięte |"),
    ],
    ids=["issue-chwastu-z-tym-kodem", "issue-chwastu-innego-kodu"],
)
def test_merge_pr_z_linia_korzen_z_issue_zamyka_issue_chwastu_z_komentarzem_o_pr_i_commicie_merge(tmp_path: Path, title: str, closed: bool, suffix: str) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.answer_issue(chwasty.WEED_ISSUE, answer=json.dumps({"state": "open", "title": title}))
    github.update(1, body=chwasty.OPISY["wyrywa-chwast"])
    github.comment(1, PASS.format(head=head))

    merged = github.run("1")

    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert suffix in _last_line(merged), merged.stdout
    merge_commit = git(github.origin, "rev-parse", "refs/heads/main")
    comment = f"Naprawione przez #1, scalone jako {merge_commit}."
    assert github.closed() == ([["issue", "close", str(chwasty.WEED_ISSUE), "--repo", opisy_pr.REPO, "--comment", comment]] if closed else [])


def test_kazda_tresc_rejestru_korzeni_ma_html_z_renderera_githuba() -> None:
    assert sorted(chwasty.rendered()) == sorted(set(chwasty.bodies())), "odśwież: .venv/bin/python -m tests.fixtures.chwasty"


# Status „Werdykt i bramka” (``--status``, ADR 0036 „Status w Actions”): warunki 1–4 tools/scal_pr.py jako status commita
# na HEAD PR, bez merge'a; w runie Actions z linkiem do runu, w którym linia STATUS podaje przyczyny w całości.
RUN = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": opisy_pr.REPO, "GITHUB_RUN_ID": "77"}
RUN_URL = f"https://github.com/{opisy_pr.REPO}/actions/runs/77"


def _status(github: MergeGitHub, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _run_from(github, github.checkout, *arguments, environment=RUN)


def _statuses(github: MergeGitHub) -> list[list[str]]:
    return [write for write in github.writes() if str(write[1]).startswith("repos/{owner}/{repo}/statuses/")]


def test_status_gotowego_pr_jest_zielony_na_jego_head_a_pr_nie_jest_scalany(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))

    answered = _status(github, "1", "--status")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered) == f"STATUS success | #1 {head[:7]} | warunki 1–4 tools/scal_pr.py spełnione"
    assert _statuses(github) == [
        [
            "POST",
            f"repos/{{owner}}/{{repo}}/statuses/{head}",
            {"state": "success", "context": "Werdykt i bramka", "description": "warunki 1–4 tools/scal_pr.py spełnione", "target_url": RUN_URL},
        ]
    ]
    assert github.merges() == []


@pytest.mark.parametrize(
    "fields",
    [
        {"isDraft": True},
        {"statusCheckRollup": [_check_run("COMPLETED", "FAILURE")]},
        {"body": BODY.replace("## Merge Danger", "## Ryzyko")},
        {"comments": []},
    ],
    ids=["szkic", "ci-czerwone", "opis-bez-naglowka-wzoru", "bez-werdyktu"],
)
def test_status_pr_niegotowego_jest_czerwony_z_ta_sama_przyczyna_co_odmowa_bez_merge(tmp_path: Path, fields: dict[str, object]) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))
    github.update(1, **fields)

    refused = github.run("1", "--bez-merge")
    answered = _status(github, "1", "--status")

    reasons = _last_line(refused).removeprefix(f"SCAL ODMOWA | #1 {head[:7]} | ")
    assert reasons != _last_line(refused), refused.stdout + refused.stderr
    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert _last_line(answered) == f"STATUS failure | #1 {head[:7]} | {reasons}"
    # GitHub przyjmuje opis statusu do 140 znaków, a pełne przyczyny podaje linia STATUS w runie z target_url.
    limit = klient_github.OPIS_STATUSU_LIMIT
    described = reasons if len(reasons) <= limit else reasons[: limit - 1] + "…"
    assert _statuses(github) == [
        ["POST", f"repos/{{owner}}/{{repo}}/statuses/{head}", {"state": "failure", "context": "Werdykt i bramka", "description": described, "target_url": RUN_URL}]
    ]


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"state": "MERGED"}, "PR MERGED, więc status HEAD zostaje z chwili zamknięcia"),
        ({"state": "CLOSED"}, "PR CLOSED, więc status HEAD zostaje z chwili zamknięcia"),
        ({"baseRefName": "wydanie"}, "PR do wydanie, a status dostają PR-y do main"),
    ],
    ids=["scalony", "zamkniety", "do-innej-galezi"],
)
def test_pr_zamkniety_albo_do_innej_galezi_niz_main_nie_dostaje_statusu(tmp_path: Path, fields: dict[str, object], reason: str) -> None:
    """Status scalonego HEAD zostaje taki, jak w chwili merge'a, więc raport po fakcie widzi merge bez zielonego statusu."""

    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))
    github.update(1, **fields)

    answered = _status(github, "1", "--status")

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert answered.stdout.splitlines() == [f"STATUS POMINIĘTY | #1 {head[:7]} | {reason}"]
    assert _statuses(github) == []


def test_status_pr_ktory_zmienia_wzor_opisu_sadzi_wzor_z_bazy_takze_z_checkoutu_head_pr(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    main = git(github.origin, "rev-parse", "refs/heads/main")
    template = TEMPLATE.read_text(encoding="utf-8").replace("## Merge Danger\n", "", 1)
    head = github.open_pull(1, {".agents/skills/pr/SKILL.md": template, "kod/inne.py": "INNE: int = 1\n"})
    github.update(1, body=BODY.replace("## Merge Danger", "## Ryzyko"))
    github.comment(1, PASS.format(head=head))
    checkout = _checkout_of(github, head, tmp_path)

    answered = _run_from(github, checkout, "1", "--status", environment=RUN)

    assert answered.stdout.splitlines()[0] == f"SĘDZIA | #1 | reguły z origin/main {main[:7]}, nie z checkoutu {head[:7]}: biegnę z kopii tego commitu"
    assert _last_line(answered) == f"STATUS failure | #1 {head[:7]} | opis: brak „## Merge Danger” w kolejności wzoru .agents/skills/pr/SKILL.md"
    assert [cast(dict[str, str], write[2])["state"] for write in _statuses(github)] == ["failure"]


def test_status_odrzucony_przez_github_konczy_sie_bledem_z_odpowiedzia_githuba(tmp_path: Path) -> None:
    github = MergeGitHub(tmp_path, {"kod/__init__.py": SUM})
    head = github.open_pull(1, {"kod/inne.py": "INNE: int = 1\n"})
    github.comment(1, PASS.format(head=head))
    (github.bin / "statusy_odrzucane").write_text("", encoding="utf-8")

    answered = _status(github, "1", "--status")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert _last_line(answered) == f"STATUS FAIL | #1 {head[:7]} | success niewysłany: gh: Validation Failed (HTTP 422)"
