"""Stan PR z GitHuba dla ``tools/scal_pr.py`` z jednego ``gh pr view --json`` (jego ``--help`` mówi, co z niego bierze)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

import github

_JOB_URL = re.compile(r"https://github\.com/[^/]+/[^/]+/actions/runs/(?P<run>[0-9]+)/job/[0-9]+")


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    head: str
    base: str
    state: str
    draft: bool
    from_fork: bool
    verdicts: tuple[dict[str, object], ...]  # komentarze i recenzje w kolejności utworzenia
    repository: str  # właściciel/nazwa
    body: str
    closed_by_github: frozenset[int]  # issues tego repozytorium z ``closingIssuesReferences``
    checks: tuple[dict[str, str | None], ...]


def pull(number: int) -> Pull:
    fields = (
        "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments,reviews,"
        "url,body,closingIssuesReferences"
    )
    found = json.loads(github.gh("pr", "view", str(number), "--json", fields))
    verdicts = [*found["comments"], *found["reviews"]]
    verdicts.sort(key=lambda verdict: verdict.get("createdAt") or verdict.get("submittedAt") or "")
    repository = "/".join(found["url"].split("/")[3:5])
    closed_by_github = frozenset(
        issue["number"]
        for issue in found["closingIssuesReferences"]
        if f"{issue['repository']['owner']['login']}/{issue['repository']['name']}".casefold() == repository.casefold()
    )
    return Pull(
        number,
        found["title"],
        found["headRefOid"],
        found["baseRefName"],
        found["state"],
        found["isDraft"],
        found["isCrossRepository"],
        tuple(verdicts),
        repository,
        found["body"],
        closed_by_github,
        tuple(found["statusCheckRollup"]),
    )


@dataclass(frozen=True)
class CiRun:
    """Run workflow ``CI`` na HEAD: identyfikator runu i jego checki z rollupu."""

    id: int
    checks: tuple[dict[str, str | None], ...]

    @property
    def required(self) -> dict[str, str | None] | None:
        """Check ``Required CI status`` tego runu; ``None``, gdy run jeszcze trwa, bo GitHub tworzy ten check dopiero
        po zadaniach z jego ``needs:`` (``.github/workflows/ci.yml``)."""

        return next((check for check in self.checks if check.get("name") == github.REQUIRED), None)

    @property
    def running(self) -> list[dict[str, str | None]]:
        """Checki runu, które się jeszcze nie skończyły, na przykład zadania ponowione w tym samym runie."""

        return [check for check in self.checks if check.get("status") != "COMPLETED"]


class UnknownRun(Exception):
    """Check workflow ``CI``, którego ``detailsUrl`` nie ma postaci ``…/actions/runs/<run>/job/<zadanie>``."""

    def __init__(self, name: str, url: str) -> None:
        super().__init__(name, url)
        self.name = name
        self.url = url


def latest_ci_run(checks: tuple[dict[str, str | None], ...] | list[dict[str, str | None]]) -> CiRun | None:
    """Najnowszy run workflow ``CI`` na HEAD albo ``None``, gdy rollup nie ma żadnego checku tego workflow.

    Po zamknięciu i otwarciu PR rollup ma obok siebie checki kilku runów CI na tym samym HEAD, a liczy się tylko
    najnowszy: ten o największym identyfikatorze runu z ``detailsUrl`` checku, bo GitHub nadaje identyfikatory rosnąco
    (porównanie liczb, nie napisów i nie ``startedAt``). Checki starszych runów nic nie znaczą. Check workflow ``CI``
    z ``detailsUrl`` innej postaci daje ``UnknownRun``, zamiast zgadywać jego run. Checki innych workflowów i statusy
    commitu (bez ``workflowName``, ustawi je każdy z prawem zapisu) do żadnego runu CI nie należą.
    """

    runs: dict[int, list[dict[str, str | None]]] = {}
    for check in checks:
        if check.get("workflowName") != github.CI_WORKFLOW:
            continue
        url = check.get("detailsUrl") or ""
        found = _JOB_URL.fullmatch(url)
        if found is None:
            raise UnknownRun(str(check.get("name")), url)
        runs.setdefault(int(found["run"]), []).append(check)
    if not runs:
        return None
    latest = max(runs)
    return CiRun(latest, tuple(runs[latest]))
