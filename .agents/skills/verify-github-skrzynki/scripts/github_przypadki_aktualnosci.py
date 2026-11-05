"""Przypadki Aktualności narzędzia: odczyt publicznego repozytorium narzędzia przez ``tool_freshness``.

Oczekiwany wynik daje wyrocznia z Gita, nie z API: ``git ls-remote`` (tagi i czubek `main` protokołem Gita) i
``git rev-list --first-parent`` na pobranym `main`, z reguły Wydania z ADR 0014 (tag ``vMAJOR.MINOR.PATCH`` na linii
pierwszych rodziców `main`, nowsze to wyższy numer). Przypadki pytają funkcje, z których Aktualność składa odpowiedź
(``_tag_commits``, ``_on_first_parent_line``, ``_compare``), i całe ``releases_from`` i ``published_from``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Final, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum import tool_freshness
from rozliczenia.centrum.tool_freshness import (
    GitHubReleases,
    PublishedRelease,
    published_from,
    releases_from,
)

from github_wymiana import TOOL_REPOSITORY, Case, Facts, GitHubProxy

ROOT = Path(__file__).resolve().parents[4]
TIMEOUT_S: Final = 60.0
REMOTE: Final = f"https://github.com/{TOOL_REPOSITORY}.git"
_RELEASE: Final = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Client:
    proxy: GitHubProxy

    @property
    def api(self) -> str:
        return self.proxy.api


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    subject: str


@dataclass(frozen=True)
class Oracle:
    """Repozytorium narzędzia według Gita: tagi (commit po zdjęciu tagu opisanego), czubek `main` i jego linia."""

    tags: dict[str, str]
    tip: str
    line: tuple[Commit, ...]

    @classmethod
    def read(cls) -> Oracle:
        listed = _git("ls-remote", REMOTE)
        refs: dict[str, str] = {}
        for row in listed.splitlines():
            sha, name = row.split("\t")
            refs[name] = sha
        tags = {
            name.removeprefix("refs/tags/").removesuffix("^{}"): sha
            for name, sha in sorted(refs.items(), key=lambda item: item[0].endswith("^{}"))
            if name.startswith("refs/tags/")
        }
        tip = refs["refs/heads/main"]
        _git("fetch", "--quiet", "--no-tags", REMOTE, "main")
        log = _git("log", "--first-parent", "--format=%H%x09%P%x09%s", tip)
        line = tuple(
            Commit(sha, tuple(parents.split()), subject)
            for sha, parents, subject in (row.split("\t", 2) for row in log.splitlines())
        )
        return cls(tags, tip, line)

    def releases(self) -> dict[str, str]:
        return {tag: sha for tag, sha in self.tags.items() if _RELEASE.fullmatch(tag)}

    def newest_on_line(self) -> tuple[str, str]:
        on_line = {commit.sha for commit in self.line}
        found = [(tag, sha) for tag, sha in self.releases().items() if sha in on_line]
        return max(found, key=lambda item: _number(item[0]))


def _number(tag: str) -> tuple[int, ...]:
    found = _RELEASE.fullmatch(tag)
    assert found is not None
    return tuple(int(part) for part in found.groups())


def _git(*arguments: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=True).stdout


@dataclass
class AktualnoscLive:
    oracle: Oracle


def _expect(outcome: object, expected: object) -> list[str]:
    return [] if outcome == expected else [f"wynik {outcome}, oczekiwane {expected}"]


def _asked(client: Client) -> int:
    return len(client.proxy.exchanges)


# --- przypadki ------------------------------------------------------------------------------------------------------


def _prepare_tag_pages(live: AktualnoscLive, earlier: Facts) -> Facts:
    tags = live.oracle.tags
    return {"na_stronie": max(1, -(-len(tags) // 3)), "tagi": tags}


def _tag_pages(client: Client, facts: Facts) -> object:
    found = tool_freshness._tag_commits(f"{client.api}/tags?per_page={facts['na_stronie']}", TIMEOUT_S)
    return (found, _asked(client))


def _judge_tag_pages(facts: Facts, outcome: object) -> list[str]:
    found, asked = cast(tuple[object, int], outcome)
    problems = _expect(found, facts["tagi"])
    return (
        problems
        if asked >= 2
        else [
            *problems,
            f"lista tagów przyszła w {asked} stronie, oczekiwane co najmniej 2",
        ]
    )


def _prepare_newest(live: AktualnoscLive, earlier: Facts) -> Facts:
    tag, sha = live.oracle.newest_on_line()
    return {"tag": tag, "commit": sha, "czubek": live.oracle.tip}


def _newest(client: Client, facts: Facts) -> object:
    return releases_from(client.api, timeout_s=TIMEOUT_S, known={})


def _prepare_published(live: AktualnoscLive, earlier: Facts) -> Facts:
    return {
        "wydania": sorted(live.oracle.releases()),
        "najnowsze": live.oracle.newest_on_line()[0],
    }


def _published(client: Client, facts: Facts) -> object:
    return published_from(client.api, timeout_s=TIMEOUT_S)


def _judge_published(facts: Facts, outcome: object) -> list[str]:
    if not isinstance(outcome, tuple) or not outcome:
        return [f"wynik {outcome}, oczekiwane niepusta lista opublikowanych Wydań"]
    published = cast(tuple[PublishedRelease, ...], outcome)
    tags = [item.release.tag for item in published]
    problems = [
        f"opublikowane {tag} nie jest tagiem Wydania repozytorium"
        for tag in tags
        if tag not in cast(list[str], facts["wydania"])
    ]
    if facts["najnowsze"] not in tags:
        problems.append(f"lista {tags} nie ma najnowszego Wydania {facts['najnowsze']}")
    moments = [item.at for item in published]
    if moments != sorted(moments, reverse=True):
        problems.append(f"lista {tags} nie jest od najnowszej publikacji")
    if len(published) > tool_freshness.PUBLISHED_PAGE:
        problems.append(f"{len(published)} Wydań, najwyżej {tool_freshness.PUBLISHED_PAGE}")
    return problems


def _pick(live: AktualnoscLive, condition: Callable[[Commit], bool], what: str) -> str:
    for commit in live.oracle.line[1:]:
        if condition(commit):
            return commit.sha
    raise RuntimeError(f"brak warunku: na linii pierwszych rodziców `main` nie ma commitu {what}")


def _prepare_merged(live: AktualnoscLive, earlier: Facts) -> Facts:
    commit = _pick(live, lambda c: c.subject.startswith("Merge pull request #"), "scalenia PR")
    return {"commit": commit, "czubek": live.oracle.tip}


def _prepare_direct(live: AktualnoscLive, earlier: Facts) -> Facts:
    commit = _pick(
        live,
        lambda c: not c.subject.startswith("Merge pull request #") and not re.search(r"\(#\d+\)", c.subject),
        "bez PR",
    )
    return {"commit": commit, "czubek": live.oracle.tip}


def _prepare_branch(live: AktualnoscLive, earlier: Facts) -> Facts:
    line = {commit.sha for commit in live.oracle.line}
    merge = next(commit for commit in live.oracle.line if len(commit.parents) == 2 and commit.parents[1] not in line)
    return {"commit": merge.parents[1], "czubek": live.oracle.tip}


def _on_line(client: Client, facts: Facts) -> object:
    return tool_freshness._on_first_parent_line(client.api, str(facts["commit"]), str(facts["czubek"]), TIMEOUT_S)


def _prepare_not_ancestor(live: AktualnoscLive, earlier: Facts) -> Facts:
    return {"commit": live.oracle.tip, "czubek": live.oracle.line[5].sha}


def _prepare_before_first(live: AktualnoscLive, earlier: Facts) -> Facts:
    return {
        "commit": live.oracle.line[-1].sha,
        "czubek": live.oracle.tip,
        "glebokosc": len(live.oracle.line),
    }


def _before_first(client: Client, facts: Facts) -> object:
    try:
        return tool_freshness._compare(
            client.api,
            str(facts["commit"]),
            f"{facts['czubek']}~{facts['glebokosc']}",
            TIMEOUT_S,
        )
    except tool_freshness._NotFound:
        return "404: GitHub nie zna takiego commitu (_NotFound)"
    except tool_freshness._NoAnswer:
        return "brak pełnej odpowiedzi (_NoAnswer)"


def _is(expected: object) -> Callable[[Facts, object], list[str]]:
    return lambda facts, outcome: _expect(outcome, expected)


LINE_SOURCE: Final = "tool_freshness._on_first_parent_line: Wydanie leży na linii pierwszych rodziców `main` (ADR 0014)"

CASES: Final[tuple[Case[AktualnoscLive, Client], ...]] = (
    Case(
        "tagi-strony",
        "tagi i ich commity jak w git ls-remote, zebrane z co najmniej 2 stron (nagłówek Link)",
        "tool_freshness._tag_commits: „Tagi i ich commity ze wszystkich stron listy tagów”",
        _prepare_tag_pages,
        _tag_pages,
        _judge_tag_pages,
    ),
    Case(
        "najnowsze-wydanie",
        "GitHubReleases z commitem i tagiem najwyższego Wydania na linii pierwszych rodziców `main` według Gita",
        "ADR 0014; tool_freshness.releases_from",
        _prepare_newest,
        _newest,
        lambda facts, outcome: _expect(outcome, GitHubReleases(str(facts["commit"]), str(facts["tag"]))),
    ),
    Case(
        "opublikowane",
        "niepusta lista tagów Wydań od najnowszej publikacji, z najnowszym Wydaniem, najwyżej PUBLISHED_PAGE",
        "tool_freshness.published_from, parse_published; ADR 0014 (Wydanie to tag i GitHub Release)",
        _prepare_published,
        _published,
        _judge_published,
    ),
    Case(
        "linia-scalenie-pr",
        "True: commit scalenia PR na linii",
        LINE_SOURCE,
        _prepare_merged,
        _on_line,
        _is(True),
    ),
    Case(
        "linia-bez-pr",
        "True: commit wypchnięty wprost na linii (wyszukiwanie binarne)",
        LINE_SOURCE,
        _prepare_direct,
        _on_line,
        _is(True),
    ),
    Case(
        "poza-linia",
        "False: commit gałęzi wciągniętej merge'em",
        LINE_SOURCE,
        _prepare_branch,
        _on_line,
        _is(False),
    ),
    Case(
        "nie-przodek",
        "None: commit nie jest przodkiem porównywanego czubka",
        "tool_freshness._on_first_parent_line: „None, gdy nie jest przodkiem tip”",
        _prepare_not_ancestor,
        _on_line,
        _is(None),
    ),
    Case(
        "przed-poczatkiem",
        "404: GitHub nie zna tip~k sprzed pierwszego commitu (_NotFound)",
        "tool_freshness._on_first_parent_line: „tip~k sprzed pierwszego commitu repozytorium (404) nie zawiera commit”",
        _prepare_before_first,
        _before_first,
        _is("404: GitHub nie zna takiego commitu (_NotFound)"),
    ),
)


def describe(outcome: object) -> str:
    if isinstance(outcome, tuple) and outcome and all(isinstance(item, PublishedRelease) for item in outcome):
        return "(" + ", ".join(cast(PublishedRelease, item).release.tag for item in outcome) + ")"
    if isinstance(outcome, tuple) and len(outcome) == 2 and isinstance(outcome[0], dict):
        return f"({len(outcome[0])} tagów, {outcome[1]} stron)"
    return repr(outcome)
