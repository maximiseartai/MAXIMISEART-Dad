"""Stan PR z GitHuba dla ``tools/scal_pr.py`` z jednego ``gh pr view --json`` (jego ``--help`` mówi, co z niego bierze)."""

from __future__ import annotations

from dataclasses import dataclass
import json

import github


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


def required(checks: tuple[dict[str, str | None], ...] | list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Checki ``Required CI status`` z GitHub Actions (CheckRun z workflow), nie status commitu, który ustawi każdy z prawem zapisu."""

    return [check for check in checks if check.get("name") == github.REQUIRED and check.get("workflowName")]
