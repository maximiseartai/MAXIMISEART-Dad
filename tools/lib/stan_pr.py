"""Stan PR z GitHuba dla ``tools/scal_pr.py`` z jednego ``gh pr view --json`` (jego ``--help`` mówi, co z niego bierze)."""

from __future__ import annotations

from dataclasses import dataclass
import json

import github

_NOT_STARTED = "0001-01-01"  # ``gh`` zapisuje brak ``startedAt`` jako zerową datę Go


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


def latest_required(checks: tuple[dict[str, str | None], ...] | list[dict[str, str | None]]) -> dict[str, str | None] | None:
    """Najnowszy check ``Required CI status`` z GitHub Actions (CheckRun z workflow, nie status commitu, który ustawi
    każdy z prawem zapisu) albo ``None``, gdy go nie ma.

    Rollup ma jeden taki check na każdy przebieg workflow na HEAD (ponowione zadanie zastępuje swój check w przebiegu),
    więc po zamknięciu i otwarciu PR stoją w nim checki starych przebiegów obok nowego, a liczy się tylko najnowszy.
    Najnowszy to ten z najpóźniejszym ``startedAt``; check, który jeszcze nie wystartował (``startedAt`` puste albo
    zerowa data, którą ``gh`` podaje za brak), jest nowszy od każdego, który wystartował.
    """

    found = [check for check in checks if check.get("name") == github.REQUIRED and check.get("workflowName")]
    return max(found, key=_start, default=None)


def _start(check: dict[str, str | None]) -> tuple[bool, str]:
    started = check.get("startedAt") or ""
    return started == "" or started.startswith(_NOT_STARTED), started
