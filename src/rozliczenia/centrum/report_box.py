from __future__ import annotations

import http.client
import json
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol, get_args

from rozliczenia.centrum.github import (
    API,
    MAX_PAGES,
    PAGE_SIZE,
    UPLOADS,
    WEB,
    HttpRequest,
    HttpResponse,
    Transport,
    headers,
    send,
    sendable,
)


Label = Literal["zgloszenie", "kontrola-ilosci", "logi-uruchomienia", "uwaga-taty"]
COMMENT_LIMIT: Final = 65_536


@dataclass(frozen=True)
class Sent:
    number: int


@dataclass(frozen=True)
class Commented:
    id: int
    url: str


@dataclass(frozen=True)
class Comment:
    id: int
    url: str
    body: str


CloseReason = Literal["completed", "not_planned", "duplicate"]


@dataclass(frozen=True)
class Closure:
    reason: CloseReason | None
    at: datetime | None


@dataclass(frozen=True)
class Issue:
    number: int
    body: str
    closure: Closure | None = None


@dataclass(frozen=True)
class ListedIssue:
    issue: Issue
    title: str


@dataclass(frozen=True)
class Refused:
    ...


@dataclass(frozen=True)
class Rejected:
    ...


@dataclass(frozen=True)
class Unreachable:
    ...


@dataclass(frozen=True)
class Asset:
    id: int
    name: str
    label: str
    uploaded: bool


@dataclass(frozen=True)
class Archive:
    id: int
    assets: tuple[Asset, ...]


@dataclass(frozen=True)
class Removed:
    ...


SendOutcome = Sent | Refused | Rejected | Unreachable
CommentOutcome = Commented | Refused | Rejected | Unreachable
IssuesOutcome = tuple[Issue, ...] | Refused | Unreachable
ListOutcome = tuple[ListedIssue, ...] | Refused | Unreachable
CommentsOutcome = tuple[Comment, ...] | Refused | Unreachable
FindOutcome = Issue | None | Refused | Unreachable
ArchiveOutcome = Archive | None | Refused | Unreachable
OpenArchiveOutcome = Archive | Refused | Rejected | Unreachable
UploadOutcome = Asset | Refused | Rejected | Unreachable
RemoveOutcome = Removed | Refused | Unreachable


class ReportBox(Protocol):
    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        ...

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        ...

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> ListOutcome:
        ...

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        ...

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        ...

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        ...

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        ...

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        ...

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        ...


REPOSITORY: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia"
_TIMEOUT_S: Final = 15.0
_REFUSALS: Final = frozenset({401, 403, 404})
_RATE_LIMIT: Final = b"rate limit"
_REJECTIONS: Final = frozenset({400, 413, 422})
_EMPTY_REPOSITORY: Final = 409
_CLOSE_REASONS: Final[Mapping[str, CloseReason]] = {reason: reason for reason in get_args(CloseReason)}


def newest_with_line(issues: tuple[Issue, ...], line: str) -> Issue | None:
    return max((issue for issue in issues if line in issue.body.splitlines()), key=lambda issue: issue.number, default=None)


def archive_url(tag: str, name: str) -> str:
    return f"{WEB}/{REPOSITORY}/releases/download/{urllib.parse.quote(tag)}/{urllib.parse.quote(name)}"


def urllib_transport(request: HttpRequest) -> HttpResponse:
    return send(request, proxy="system", key_after_redirect="same-origin", timeout_s=_TIMEOUT_S)


class GitHubReportBox:
    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if not sendable(key):
            return Refused()
        payload = {"title": title, "body": body, "labels": [label]}
        answer = self._send("POST", f"{API}/repos/{REPOSITORY}/issues", payload, key)
        if not isinstance(answer, HttpResponse):
            return answer
        number = _json_field(answer.body, "number") if answer.status == 201 else None
        return Sent(number) if isinstance(number, int) else Unreachable()

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        if not sendable(key):
            return Refused()
        answer = self._send("POST", f"{API}/repos/{REPOSITORY}/issues/{number}/comments", {"body": body}, key)
        return _commented(answer, 201)

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        if not sendable(key):
            return Refused()
        answer = self._send("PATCH", f"{API}/repos/{REPOSITORY}/issues/comments/{comment_id}", {"body": body}, key)
        return _commented(answer, 200)

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> ListOutcome:
        state = "all" if include_closed else "open"
        entries = self._pages(f"{API}/repos/{REPOSITORY}/issues?state={state}&labels={label}&", key)
        return entries if not isinstance(entries, list) else tuple(i for i in map(_issue, entries) if i is not None)

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        entries = self._pages(f"{API}/repos/{REPOSITORY}/issues/{number}/comments?", key)
        return entries if not isinstance(entries, list) else tuple(c for c in map(_comment, entries) if c is not None)

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        releases = self._pages(f"{API}/repos/{REPOSITORY}/releases?", key)
        if not isinstance(releases, list):
            return releases
        found = next((_release_id(entry) for entry in releases if _tag(entry) == tag), None)
        if found is None:
            return None
        assets = self._pages(f"{API}/repos/{REPOSITORY}/releases/{found}/assets?", key)
        if not isinstance(assets, list):
            return assets
        return Archive(found, tuple(asset for asset in map(_asset, assets) if asset is not None))

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        if not sendable(key):
            return Refused()
        payload = {"tag_name": tag, "name": title, "body": description, "make_latest": "false"}
        answer = self._send("POST", f"{API}/repos/{REPOSITORY}/releases", payload, key)
        if not isinstance(answer, HttpResponse):
            return answer
        if answer.status == _EMPTY_REPOSITORY:
            return Rejected()
        found = _release_id(_json(answer.body)) if answer.status == 201 else None
        return Archive(found, ()) if found is not None else Unreachable()

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        if not sendable(key):
            return Refused()
        query = urllib.parse.urlencode({"name": name, "label": label})
        url = f"{UPLOADS}/repos/{REPOSITORY}/releases/{archive_id}/assets?{query}"
        answer = self._submit("POST", url, data, "application/octet-stream", key)
        if not isinstance(answer, HttpResponse):
            return answer
        asset = _asset(_json(answer.body)) if answer.status == 201 else None
        return asset if asset is not None else Unreachable()

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        if not sendable(key):
            return Refused()
        answer = self._exchange(
            HttpRequest(
                method="DELETE",
                url=f"{API}/repos/{REPOSITORY}/releases/assets/{asset_id}",
                headers=headers(key),
                body=None,
            )
        )
        if not isinstance(answer, HttpResponse):
            return answer
        return Removed() if answer.status == 204 else Unreachable()

    def _pages(self, query: str, key: str) -> list[object] | Refused | Unreachable:
        if not sendable(key):
            return Refused()
        found: list[object] = []
        for page in range(1, MAX_PAGES + 1):
            paged = f"{query}per_page={PAGE_SIZE}&page={page}"
            answer = self._exchange(HttpRequest(method="GET", url=paged, headers=headers(key), body=None))
            if not isinstance(answer, HttpResponse):
                return answer
            entries = _json(answer.body) if answer.status == 200 else None
            if not isinstance(entries, list):
                return Unreachable()
            found.extend(entries)
            if len(entries) < PAGE_SIZE:
                break
        return found

    def _send(
        self, method: str, url: str, payload: Mapping[str, object], key: str
    ) -> HttpResponse | Refused | Rejected | Unreachable:
        return self._submit(method, url, json.dumps(payload).encode("utf-8"), "application/json", key)

    def _submit(
        self, method: str, url: str, body: bytes, content_type: str, key: str
    ) -> HttpResponse | Refused | Rejected | Unreachable:
        answer = self._exchange(
            HttpRequest(method=method, url=url, headers={**headers(key), "Content-Type": content_type}, body=body)
        )
        return Rejected() if isinstance(answer, HttpResponse) and answer.status in _REJECTIONS else answer

    def _exchange(self, request: HttpRequest) -> HttpResponse | Refused | Unreachable:
        transport = self._transport or urllib_transport
        try:
            response = transport(request)
        except (OSError, http.client.HTTPException):
            return Unreachable()
        if response.status in _REFUSALS and _RATE_LIMIT not in response.body:
            return Refused()
        return response


def _commented(answer: HttpResponse | Refused | Rejected | Unreachable, status: int) -> CommentOutcome:
    if not isinstance(answer, HttpResponse):
        return answer
    document = _json(answer.body) if answer.status == status else None
    if not isinstance(document, dict):
        return Unreachable()
    comment_id, url = document.get("id"), document.get("html_url")
    return Commented(comment_id, url) if isinstance(comment_id, int) and isinstance(url, str) else Unreachable()


def _comment(entry: object) -> Comment | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), int) or not isinstance(entry.get("html_url"), str):
        return None
    body = entry.get("body")
    return Comment(entry["id"], entry["html_url"], body if isinstance(body, str) else "")


def _release_id(entry: object) -> int | None:
    found = entry.get("id") if isinstance(entry, dict) else None
    return found if isinstance(found, int) else None


def _tag(entry: object) -> object:
    return entry.get("tag_name") if isinstance(entry, dict) else None


def _asset(entry: object) -> Asset | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), int) or not isinstance(entry.get("name"), str):
        return None
    label = entry.get("label")
    return Asset(entry["id"], entry["name"], label if isinstance(label, str) else "", entry.get("state") == "uploaded")


def _issue(entry: object) -> ListedIssue | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("number"), int):
        return None
    body, title = entry.get("body"), entry.get("title")
    closure = _closure(entry) if entry.get("state") == "closed" else None
    issue = Issue(entry["number"], body if isinstance(body, str) else "", closure)
    return ListedIssue(issue, title if isinstance(title, str) else "")


def _closure(entry: dict[str, object]) -> Closure:
    return Closure(close_reason(entry.get("state_reason")), read_moment(entry.get("closed_at")))


def close_reason(value: object) -> CloseReason | None:
    return _CLOSE_REASONS.get(value) if isinstance(value, str) else None


def _json_field(body: bytes, name: str) -> object:
    document = _json(body)
    return document.get(name) if isinstance(document, dict) else None


def _json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None


def read_moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None
