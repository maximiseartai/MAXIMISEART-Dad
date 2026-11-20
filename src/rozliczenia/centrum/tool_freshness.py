from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
from http.client import HTTPException
import json
from pathlib import Path
import threading
from typing import Final, Literal
from urllib.parse import urlsplit

from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.github import (
    ANSWER_KEPT_S,
    MAX_PAGES,
    NO_ANSWER_KEPT_S,
    PAGE_SIZE,
    TOOL_API,
    HttpRequest,
    headers,
    next_page,
    rate_limit_reset,
    send,
)
from rozliczenia.centrum.tool_update import Release, contains_commit, find_git, newest_on_main, release_at
from rozliczenia.centrum.version import commit_since, is_commit, tool_commit
from rozliczenia.tool_files import TOOL_ROOT

CommitSource = Callable[[], str | None]


@dataclass(frozen=True)
class GitHubReleases:
    newest: str | None
    tag: str | None


@dataclass(frozen=True)
class RateLimited:
    reset: datetime


ReleaseSource = Callable[[], GitHubReleases | None]
ReleaseAnswer = GitHubReleases | RateLimited | None
AnswerSource = Callable[[], ReleaseAnswer]
KeySource = Callable[[], str | None]


@dataclass(frozen=True)
class PublishedRelease:
    release: Release
    notes: str
    at: datetime


PublishedSource = Callable[[], tuple[PublishedRelease, ...] | None]
Judgement = Literal["current", "newer", "no_release", "no_answer", "no_commit"]


def offers_update(judgement: Judgement) -> bool:
    return judgement == "newer"


_CANDIDATES: Final = 5
_PAGE_BYTES: Final = 1_000_000
RELEASES_TIMEOUT_S: Final = 3.0
RELEASES_THREAD: Final = "github-wydania"
RELEASE_NOTES_THREAD: Final = "github-notki-wydan"


@dataclass(frozen=True)
class ToolFreshness:
    local: CommitSource
    since: Callable[[], date | None]
    release: AnswerSource
    published: PublishedSource
    contains: Callable[[str, str], bool] = field(default=lambda release, local: release == local)
    wydanie: Callable[[str], Release | None] = field(default=lambda local: None)

    @classmethod
    def of_system(cls, key: KeySource) -> ToolFreshness:
        return cls.of_clone(TOOL_ROOT, github_releases(key, TOOL_API), lambda: github_published(key()))

    @classmethod
    def of_clone(
        cls,
        root: Path,
        release: AnswerSource,
        published: PublishedSource,
        *,
        find_git: Callable[[], Path | None] = find_git,
    ) -> ToolFreshness:
        running = tool_commit(root)
        since = None if running is None else commit_since(running, root)
        return cls(
            local=lambda: running,
            since=lambda: since,
            release=release,
            published=published,
            contains=partial(contains_commit, root),
            wydanie=partial(release_at, root, find_git=find_git),
        )

    def judge(self, release: AnswerSource | None = None) -> Judgement:
        return self.assess(release)[0]

    def assess(self, release: AnswerSource | None = None) -> tuple[Judgement, ReleaseAnswer]:
        local = self.local()
        if local is None:
            return "no_commit", None
        answer = (release or self.release)()
        if not isinstance(answer, GitHubReleases):
            return "no_answer", answer
        if answer.newest is None:
            return "no_release", answer
        return ("current" if self.contains(answer.newest, local) else "newer"), answer


class RememberedRelease:
    def __init__(self, release: AnswerSource, *, clock: Callable[[], float]) -> None:
        self._release = release
        self._clock = clock
        self._lock = threading.Lock()
        self._answer: GitHubReleases | None = None
        self._asked_at: float | None = None

    def __call__(self) -> GitHubReleases | None:
        with self._lock:
            if self._asked_at is not None:
                kept = ANSWER_KEPT_S if self._answer is not None else NO_ANSWER_KEPT_S
                if self._clock() - self._asked_at < kept:
                    return self._answer
        answer = self._release()
        known = answer if isinstance(answer, GitHubReleases) else None
        with self._lock:
            self._answer, self._asked_at = known, self._clock()
        return known

    def fresh(self) -> ReleaseAnswer:
        answer = self._release()
        if isinstance(answer, GitHubReleases):
            with self._lock:
                self._answer, self._asked_at = answer, self._clock()
        return answer


def github_releases(key: KeySource, api: str) -> AnswerSource:
    line: dict[str, bool] = {}
    return lambda: releases_from(api, timeout_s=RELEASES_TIMEOUT_S, known=line, token=key())


def releases_from(
    api: str, *, timeout_s: float, known: dict[str, bool] | None = None, token: str | None = None
) -> ReleaseAnswer:
    line = {} if known is None else known

    def fetch() -> ReleaseAnswer:
        asking = Asking(api, timeout_s, token)
        answer = newest(asking)
        return answer if answer is not None else asking.limited

    def newest(asking: Asking) -> GitHubReleases | None:
        commits = tag_commits(asking, f"{api}/tags?per_page={PAGE_SIZE}")
        if commits is None:
            return None
        asked = 0
        tips: list[str] = []

        def on_main(commit: str) -> bool:
            nonlocal asked
            asked += 1
            if asked > _CANDIDATES:
                raise NoAnswer
            if commit in line:
                return line[commit]
            if not tips:
                tips.append(_main_tip(asking))
            on_line = on_first_parent_line(asking, commit, tips[0])
            if on_line is not None:
                line[commit] = on_line
            return on_line is True

        try:
            found = newest_on_main(commits, on_main)
        except NoAnswer:
            return None
        return GitHubReleases(found.commit, None if found.release is None else found.release.tag)

    return within(timeout_s, fetch, name=RELEASES_THREAD)


def _main_tip(asking: Asking) -> str:
    ref = asking.json(f"{asking.api}/git/ref/heads/main")
    target = ref.get("object") if isinstance(ref, dict) else None
    sha = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(sha, str) or not is_commit(sha):
        raise NoAnswer
    return sha


def on_first_parent_line(asking: Asking, commit: str, tip: str) -> bool | None:
    status, ahead = compare(asking, commit, tip)
    if status == "identical":
        return True
    if status != "ahead":
        return None
    if _merged_into_main(asking, commit):
        return True
    # ZEWNĘTRZNE: REST API GitHuba nie podaje linii pierwszych rodziców, ale porównuje commit z `sha~k` (docs.github.com, List commits bez first-parent; porównanie z `sha~k`: ADR 0014)
    contains, beyond = 0, ahead + 1
    while beyond - contains > 1:
        middle = (contains + beyond) // 2
        try:
            status, _ = compare(asking, commit, f"{tip}~{middle}")
        except NotFound:
            status = "behind"
        if status == "identical":
            return True
        if status == "ahead":
            contains = middle
        else:
            beyond = middle
    return False


def _merged_into_main(asking: Asking, commit: str) -> bool:
    try:
        pulls = asking.json(f"{asking.api}/commits/{commit}/pulls")
    except NoAnswer:
        pulls = ()
    return any(
        isinstance(pull, dict)
        and pull.get("merge_commit_sha") == commit
        and isinstance(pull.get("merged_at"), str)
        and isinstance(base := pull.get("base"), dict)
        and base.get("ref") == "main"
        for pull in (pulls if isinstance(pulls, list) else ())
    )


def compare(asking: Asking, commit: str, head: str) -> tuple[str, int]:
    # ZEWNĘTRZNE: porównanie GitHuba podaje zmienione pliki tylko na pierwszej stronie, więc druga strona po jednym commicie ma najwyżej jeden commit i żadnego pliku (docs.github.com, Compare two commits)
    compared = asking.json(f"{asking.api}/compare/{commit}...{head}?per_page=1&page=2")
    status = compared.get("status") if isinstance(compared, dict) else None
    ahead = compared.get("ahead_by") if isinstance(compared, dict) else None
    if not isinstance(status, str) or type(ahead) is not int:
        raise NoAnswer
    return status, ahead


PUBLISHED_PAGE: Final = 30


def github_published(token: str | None = None) -> tuple[PublishedRelease, ...] | None:
    return published_from(TOOL_API, timeout_s=RELEASES_TIMEOUT_S, token=token)


def published_from(api: str, *, timeout_s: float, token: str | None = None) -> tuple[PublishedRelease, ...] | None:
    def fetch() -> tuple[PublishedRelease, ...] | None:
        try:
            return parse_published(Asking(api, timeout_s, token).json(f"{api}/releases?per_page={PUBLISHED_PAGE}"))
        except NoAnswer:
            return None

    return within(timeout_s, fetch, name=RELEASE_NOTES_THREAD)


def parse_published(document: object) -> tuple[PublishedRelease, ...] | None:
    if not isinstance(document, list):
        return None
    return tuple(published for entry in document if (published := _published(entry)) is not None)


def _published(entry: object) -> PublishedRelease | None:
    if not isinstance(entry, dict) or entry.get("draft") is not False or entry.get("prerelease") is not False:
        return None
    tag, notes, at = entry.get("tag_name"), entry.get("body"), entry.get("published_at")
    release = Release.of_tag(tag) if isinstance(tag, str) else None
    if release is None or not isinstance(notes, str | None) or not isinstance(at, str):
        return None
    try:
        published_at = datetime.fromisoformat(at)
    except ValueError:
        return None
    return PublishedRelease(release, notes or "", published_at) if published_at.tzinfo is not None else None


class NoAnswer(Exception):
    ...


class NotFound(NoAnswer):
    ...


def tag_commits(asking: Asking, url: str) -> dict[str, str] | None:
    commits: dict[str, str] = {}
    page = url
    for _ in range(MAX_PAGES):
        try:
            tags, following = asking.page(page)
        except NoAnswer:
            return None
        if not isinstance(tags, list):
            return None
        for tag in tags:
            named = _tag_commit(tag)
            if named is not None:
                commits[named[0]] = named[1]
        if following is None:
            return commits
        page = following
    return None


_TOKEN_REFUSALS: Final = frozenset({401, 403})


class Asking:
    def __init__(self, api: str, timeout_s: float, token: str | None) -> None:
        self.api = api
        self._timeout_s = timeout_s
        self._token = token
        self._host = urlsplit(api)[:2]
        self.limited: RateLimited | None = None

    def json(self, url: str) -> object:
        return self.page(url)[0]

    def page(self, url: str, *, with_token: bool = True) -> tuple[object, str | None]:
        token = self._token if with_token and urlsplit(url)[:2] == self._host else None
        request = HttpRequest("GET", url, headers(token), None)
        try:
            response = send(
                request, proxy="direct", key_after_redirect="nowhere", timeout_s=self._timeout_s, read_limit=_PAGE_BYTES
            )
            if 200 <= response.status < 300:
                return json.loads(response.body), next_page(response)
        except (OSError, HTTPException, ValueError) as failure:
            raise NoAnswer from failure
        reset = rate_limit_reset(response)
        if reset is not None and token is None:
            self.limited = RateLimited(reset)
            raise NoAnswer
        # ZEWNĘTRZNE: GitHub liczy limit pytań z tokenem na konto, wspólny dla wszystkich jego tokenów, a bez tokenu na adres IP, więc to dwie osobne pule (docs.github.com, Rate limits for the REST API)
        if token is not None and (reset is not None or response.status in _TOKEN_REFUSALS):
            self._token = None
            return self.page(url)
        if token is not None and response.status == 404:
            return self.page(url, with_token=False)
        raise NotFound if response.status == 404 else NoAnswer


def _tag_commit(tag: object) -> tuple[str, str] | None:
    if not isinstance(tag, dict):
        return None
    name, commit = tag.get("name"), tag.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return (name, sha) if isinstance(name, str) and isinstance(sha, str) and is_commit(sha) else None
