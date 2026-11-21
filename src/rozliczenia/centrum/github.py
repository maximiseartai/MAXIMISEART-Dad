from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from http.client import HTTPMessage
from typing import IO, Final, Literal
import urllib.error
import urllib.parse
import urllib.request

from rozliczenia.centrum.opener import opener
from rozliczenia.tool_files import REPOSITORY

API: Final = "https://api.github.com"
UPLOADS: Final = "https://uploads.github.com"
WEB: Final = "https://github.com"
TOOL_API: Final = f"{API}/repos/{REPOSITORY}"

PAGE_SIZE: Final = 100
MAX_PAGES: Final = 10

ANSWER_KEPT_S: Final = 10 * 60
NO_ANSWER_KEPT_S: Final = 60

Proxy = Literal["system", "direct"]
KeyAfterRedirect = Literal["same-origin", "nowhere"]


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]


def headers(key: str | None = None) -> dict[str, str]:
    sent = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
    }
    return sent if key is None else {**sent, "Authorization": f"Bearer {key}"}


def sendable(key: str) -> bool:
    return key.isascii() and key.isprintable() and " " not in key


def send(
    request: HttpRequest,
    *,
    proxy: Proxy,
    key_after_redirect: KeyAfterRedirect,
    timeout_s: float,
    read_limit: int | None = None,
) -> HttpResponse:
    plain = {name: value for name, value in request.headers.items() if name != "Authorization"}
    sent = urllib.request.Request(request.url, data=request.body, headers=plain, method=request.method)
    if "Authorization" in request.headers:
        sent.add_unredirected_header("Authorization", request.headers["Authorization"])
    handlers: list[urllib.request.BaseHandler] = [] if proxy == "system" else [urllib.request.ProxyHandler({})]
    if key_after_redirect == "same-origin":
        handlers.append(_KeyToSameOrigin())
    try:
        with opener(*handlers).open(sent, timeout=timeout_s) as response:
            body = response.read() if read_limit is None else response.read(read_limit)
            return HttpResponse(response.status, body, _lowered(response.headers.items()))
    except urllib.error.HTTPError as error:
        with error:
            body = error.read() if read_limit is None else error.read(read_limit)
            return HttpResponse(error.code, body, _lowered(error.headers.items()))


class _KeyToSameOrigin(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        key = req.unredirected_hdrs.get("Authorization")
        if redirected is not None and key is not None and _origin(redirected.full_url) == _origin(req.full_url):
            redirected.add_unredirected_header("Authorization", key)
        return redirected


def _origin(url: str) -> tuple[str, str | None, int | None] | None:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        return None
    return scheme, parts.hostname, port or _DEFAULT_PORTS.get(scheme)


_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


def _lowered(received: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {name.lower(): value for name, value in received}


def next_page(response: HttpResponse) -> str | None:
    link = response.headers.get("link")
    found = None if link is None else _NEXT_PAGE.search(link)
    return None if found is None else found[1]


def rate_limit_reset(response: HttpResponse) -> datetime | None:
    if response.status not in (403, 429) or response.headers.get("x-ratelimit-remaining") != "0":
        return None
    reset = response.headers.get("x-ratelimit-reset", "")
    if re.fullmatch(r"[0-9]{1,10}", reset) is None:
        return None
    return datetime.fromtimestamp(int(reset), timezone.utc)


_NEXT_PAGE: Final = re.compile(r'<([^>]+)>;\s*rel="next"')
