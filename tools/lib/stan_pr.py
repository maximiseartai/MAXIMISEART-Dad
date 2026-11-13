"""Stan PR z GitHuba dla ``tools/scal_pr.py`` z jednego ``gh pr view --json`` (jego ``--help`` mówi, co z niego bierze).

Stan najnowszego runu CI na HEAD czytają dwa tryby narzędzia: merge jako przyczynę odmowy (``ci_problem``) i
``--przeglad`` jako linię ``CI`` (``ci_line``), oba z tego samego ``latest_ci_run``. Obie biorą cały ``Pull`` z
``pull``, a nie rollup, żeby wołający nie mógł regule niczego przyciąć ani przefiltrować.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import github

JOB_NOT_FAILED = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
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
    return from_view(json.loads(github.gh("pr", "view", str(number), "--json", fields)))


def from_view(found: dict[str, Any]) -> Pull:
    """``Pull`` z pól ``gh pr view --json`` (te same nazwy ma GraphQL GitHuba, z którego czyta ``rejestr_korzeni``);
    komentarze i recenzje w kolejności utworzenia."""

    verdicts = [*found["comments"], *found["reviews"]]
    verdicts.sort(key=lambda verdict: verdict.get("createdAt") or verdict.get("submittedAt") or "")
    repository = "/".join(found["url"].split("/")[3:5])
    closed_by_github = frozenset(
        issue["number"]
        for issue in found["closingIssuesReferences"]
        if f"{issue['repository']['owner']['login']}/{issue['repository']['name']}".casefold() == repository.casefold()
    )
    return Pull(
        found["number"],
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


def ci_problem(pull: Pull) -> str | None:
    """Przyczyna odmowy merge'a, gdy najnowszy run CI na HEAD nie skończył się zielonym ``Required CI status``."""

    try:
        run = latest_ci_run(pull.checks)
    except UnknownRun as unknown:
        return f"CI: check „{unknown.name}” workflow „{github.CI_WORKFLOW}” bez identyfikatora runu w detailsUrl {unknown.url}"
    if run is None:
        return f"CI: brak „{github.REQUIRED}” z GitHub Actions na HEAD"
    check = run.required
    if check is None:
        return f"CI: run {github.CI_WORKFLOW} {run.id} jeszcze trwa"
    result = (check.get("conclusion") if check.get("status") == "COMPLETED" else check.get("status")) or "?"
    if result != "SUCCESS":
        return f"CI: „{github.REQUIRED}” {result}"
    return f"CI: run {github.CI_WORKFLOW} {run.id} jeszcze trwa" if run.running else None


def ci_line(pull: Pull) -> str:
    """Linia ``CI`` przeglądu: stan najnowszego runu CI na HEAD i zadania innych workflowów, na które czeka gotowość."""

    where = f"CI | {github.REQUIRED}"
    head = pull.head
    others = [check for check in pull.checks if check.get("workflowName") and check.get("workflowName") != github.CI_WORKFLOW]
    try:
        run = latest_ci_run(pull.checks)
    except UnknownRun as unknown:
        return (
            f"{where} nieznany na HEAD {head} | check „{unknown.name}” workflow „{github.CI_WORKFLOW}” bez identyfikatora "
            f"runu w detailsUrl {unknown.url} | polecenia z linii LICZY CI nie są dowiedzione"
        )
    if run is None:
        return f"{where} brak na HEAD {head} | CI nie biegło na tym HEAD: jeszcze nie wystartowało po pushu albo PR ma konflikt z bazą"
    required = run.required
    failed = sorted(
        {
            str(check.get("name"))
            for check in run.checks
            if check.get("name") != github.REQUIRED and check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED
        }
    )
    jobs = f"padłe zadania: {', '.join(failed)}" if failed else ""
    if required is not None and required.get("status") == "COMPLETED" and required.get("conclusion") != "SUCCESS":
        why = jobs or f"bez padłego zadania, przyczynę podaje log „{github.REQUIRED}”"
        logs = f"logi padłych zadań: gh run view {run.id} --log-failed"
        return f"{where} failure na HEAD {head} | {why} | polecenia z linii LICZY CI nie są dowiedzione, czytaj tylko {logs}"
    if required is not None and not run.running:
        running_others = sorted({str(check.get("name")) for check in others if check.get("status") != "COMPLETED"})
        failed_others = sorted(
            {str(check.get("name")) for check in others if check.get("status") == "COMPLETED" and check.get("conclusion") not in JOB_NOT_FAILED}
        )
        states = [f"{state}: {', '.join(names)}" for state, names in (("w toku", running_others), ("padłe", failed_others)) if names]
        rest = f" | inne workflowy, na które czeka gotowość: {'; '.join(states)}" if states else ""
        return f"{where} success na HEAD {head} | polecenia z linii LICZY CI przeszły, ich logów nie przeszukuj{rest}"
    running = [*run.running, *(check for check in others if check.get("status") != "COMPLETED")]
    return f"{where} pending na HEAD {head} (w toku: {len(running)}{f'; {jobs}' if jobs else ''}) | polecenia z linii LICZY CI jeszcze bez wyniku"
