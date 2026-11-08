"""Wymiany HTTP z GitHubem: nagrywanie na żywo, odtwarzanie z nagrań i granice, poza które przebieg nie wychodzi.

Skrzynka Zgłoszeń (``GitHubReportBox``) dostaje transport: na żywo ``LiveTransport`` przenosi jej żądania z adresu
Skrzynki (``report_box.REPOSITORY``) na jedno z repozytoriów próbnych ``TRIALS`` (puste ``TRIAL`` albo ``TRIAL_ARCHIVE``
z commitem, w którym da się założyć Archiwum okresu) i nigdzie indziej, przez ``urllib_transport`` klienta, a w
odtwarzaniu ``ReplayTransport`` odpowiada nagranymi odpowiedziami w nagranej kolejności. Aktualność
narzędzia (``tool_freshness``) nie ma transportu, tylko adres API, więc pyta lokalnego ``GitHubProxy``: na żywo
przekazuje on każde GET do ``api.github.com`` (tylko repozytorium narzędzia, bez klucza jak u taty bez pliku klucza
albo z kluczem ``gh``), a w odtwarzaniu odpowiada z nagrania.

Nagranie wymiany ma metodę, ścieżkę z zapytaniem (bez hosta, adres Skrzynki tak, jak wysłał go klient), skrót SHA-256
i długość treści żądania (bez nagłówków, więc bez klucza), status, nagłówek ``Link`` i ciało odpowiedzi przycięte przez
``trim`` do pól, które czyta klient, i komunikatów błędu. Długi tekst (ponad ``LONG_TEXT`` znaków) zostaje skrótem.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import IO, Final, Generic, TypeVar
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum.github import API, UPLOADS, WEB, HttpRequest, HttpResponse
from rozliczenia.centrum.report_box import REPOSITORY, urllib_transport
from rozliczenia.tool_files import REPOSITORY as TOOL_REPOSITORY

TRIAL: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba"
# Repozytorium próbne z jednym commitem (README na ``main``): Release, a więc Archiwum okresu, wymaga commitu.
TRIAL_ARCHIVE: Final = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba-archiwum"
TRIALS: Final = (TRIAL, TRIAL_ARCHIVE)
# Plik Release pobrany przez API przekierowuje na podpisany adres pod tą domeną.
DOWNLOAD_HOST: Final = ".githubusercontent.com"
RUN_MARKER: Final = "verify-github-skrzynki run="
LONG_TEXT: Final = 2000
# Pola odpowiedzi, które czytają ``report_box`` i ``tool_freshness``, i pola komunikatów błędu GitHuba.
KEPT: Final = frozenset(
    {
        "number", "body", "state", "state_reason", "closed_at", "id", "html_url",
        "name", "commit", "sha", "object", "status", "ahead_by",
        "merge_commit_sha", "merged_at", "base", "ref",
        "tag_name", "published_at", "draft", "prerelease", "label",
        "message", "errors", "resource", "code", "field",
    }
)  # fmt: skip
# Odstęp między żądaniami, które coś zmieniają: GitHub zaleca sekundę, inaczej daje limit „secondary”.
WRITE_GAP_S: Final = 1.0


Facts = dict[str, object]
Live = TypeVar("Live")
Client = TypeVar("Client")


@dataclass(frozen=True)
class Case(Generic[Live, Client]):
    """Przypadek przebiegu: przygotowanie na żywo, wywołanie klienta i oczekiwanie z domeny.

    ``prepare`` (tylko na żywo) zakłada w repozytorium próbnym to, czego przypadek potrzebuje, i zwraca fakty, które
    trafiają do nagrania (dostaje też fakty wcześniejszych przypadków); ``check`` woła klienta (na żywo i w odtwarzaniu tak samo) i zwraca jego wynik; ``judge``
    porównuje wynik z oczekiwaniem ``expected`` ze źródła ``source`` i zwraca rozjazdy (pusta lista: zgodnie).
    """

    id: str
    expected: str
    source: str
    prepare: Callable[[Live, Facts], Facts]
    check: Callable[[Client, Facts], object]
    judge: Callable[[Facts, object], list[str]]


class OutsideTrial(RuntimeError):
    """Żądanie poza dozwolone repozytorium: przebieg się przerywa, zamiast pisać gdziekolwiek indziej."""


def token_kind(token: str) -> str:
    """Rodzaj tokenu GitHuba z jego przedrostka; klucz taty to ``fine-grained``."""

    for prefix, kind in (
        ("github_pat_", "fine-grained"),
        ("gho_", "OAuth gh"),
        ("ghp_", "classic"),
        ("ghu_", "aplikacja (użytkownik)"),
        ("ghs_", "aplikacja (serwer)"),
    ):
        if token.startswith(prefix):
            return kind
    return "nieznany"


def token_slug(token: str) -> str:
    """Rodzaj tokenu w nazwie pliku nagrania (``skrzynka-<rodzaj>.json``)."""

    return token_kind(token).lower().replace(" ", "-").replace("(", "").replace(")", "")


def gh_token() -> str:
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def trim(value: object) -> object:
    """Ciało odpowiedzi do nagrania: tylko pola ``KEPT``, długi tekst jako jego długość i skrót."""

    if isinstance(value, dict):
        return {key: trim(item) for key, item in value.items() if key in KEPT}
    if isinstance(value, list):
        return [trim(item) for item in value]
    if isinstance(value, str) and len(value) > LONG_TEXT:
        return f"<{len(value)} znaków, sha256 {hashlib.sha256(value.encode()).hexdigest()[:16]}>"
    return value


def _recorded_body(body: bytes) -> object:
    try:
        return trim(json.loads(body))
    except ValueError:
        return {"$tekst": body[:200].decode("utf-8", "replace")}


def _served_body(body: object) -> bytes:
    if isinstance(body, dict) and set(body) == {"$tekst"}:
        return str(body["$tekst"]).encode()
    return json.dumps(body, ensure_ascii=False).encode()


@dataclass(frozen=True)
class Exchange:
    """Jedno żądanie klienta i odpowiedź GitHuba; ``status`` ``None``: brak odpowiedzi (wyjątek sieci)."""

    method: str
    path: str
    request_sha256: str | None
    request_length: int | None
    status: int | None
    link: str | None
    body: object

    def to_json(self) -> dict[str, object]:
        return {
            "metoda": self.method,
            "sciezka": self.path,
            "zadanie_sha256": self.request_sha256,
            "zadanie_dlugosc": self.request_length,
            "status": self.status,
            "link": self.link,
            "cialo": self.body,
        }

    @classmethod
    def of_json(cls, document: Mapping[str, object]) -> Exchange:
        status, link, digest, length = (
            document[name] for name in ("status", "link", "zadanie_sha256", "zadanie_dlugosc")
        )
        assert status is None or isinstance(status, int)
        assert link is None or isinstance(link, str)
        assert digest is None or isinstance(digest, str)
        assert length is None or isinstance(length, int)
        return cls(
            str(document["metoda"]),
            str(document["sciezka"]),
            digest,
            length,
            status,
            link,
            document["cialo"],
        )

    def describe(self) -> str:
        return (
            f"{self.method} {self.path.split('?')[0]} → {self.status if self.status is not None else 'brak odpowiedzi'}"
        )


def _digest(body: bytes | None) -> tuple[str | None, int | None]:
    return (None, None) if body is None else (hashlib.sha256(body).hexdigest(), len(body))


def _path(url: str) -> str:
    """Ścieżka nagrania: adres API bez hosta, adres wysyłki plików (``uploads.github.com``) z hostem."""

    if url.startswith(API + "/"):
        return url.removeprefix(API)
    if url.startswith(UPLOADS + "/"):
        return url
    raise OutsideTrial(f"adres spoza API GitHuba: {url}")


class Pace:
    """Najwyżej jedno żądanie zmieniające na ``WRITE_GAP_S``, wspólne dla klienta i harnessu runu."""

    def __init__(self) -> None:
        self._last = 0.0
        self._lock = threading.Lock()

    def write(self) -> None:
        with self._lock:
            wait = self._last + WRITE_GAP_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


@dataclass
class Recorder:
    """Wymiany bieżącego przypadku; ``None``: wymiany przygotowania, których się nie nagrywa."""

    current: list[Exchange] | None = None

    def add(self, exchange: Exchange) -> None:
        if self.current is not None:
            self.current.append(exchange)

    @contextmanager
    def case(self) -> Iterator[list[Exchange]]:
        exchanges: list[Exchange] = []
        self.current = exchanges
        try:
            yield exchanges
        finally:
            self.current = None


def to_trial(url: str, trial: str = TRIAL) -> str:
    """Adres Skrzynki (API albo wysyłka plików Archiwum) przeniesiony na repozytorium próbne ``trial``; każdy inny adres
    to ``OutsideTrial``."""

    if trial not in TRIALS:
        raise OutsideTrial(f"repozytorium {trial} nie jest repozytorium próbnym")
    for host in (API, UPLOADS):
        if url.startswith(f"{host}/repos/{REPOSITORY}/"):
            return f"{host}/repos/{trial}/" + url.removeprefix(f"{host}/repos/{REPOSITORY}/")
    raise OutsideTrial(f"klient Skrzynki pyta poza adres Skrzynki: {url}")


def from_trial_web(url: str) -> str:
    """Adres strony repozytorium próbnego Archiwum (np. ``browser_download_url`` pliku) jako adres w Skrzynce; adres
    spoza ``TRIAL_ARCHIVE`` to ``OutsideTrial``."""

    if not url.startswith(f"{WEB}/{TRIAL_ARCHIVE}/"):
        raise OutsideTrial(f"adres spoza repozytorium próbnego Archiwum: {url}")
    return f"{WEB}/{REPOSITORY}/" + url.removeprefix(f"{WEB}/{TRIAL_ARCHIVE}/")


@dataclass
class LiveTransport:
    """Transport klienta Skrzynki na żywo: każde żądanie do repozytorium próbnego ``trial`` przez ``urllib_transport``."""

    recorder: Recorder
    pace: Pace
    sent: list[str] = field(default_factory=list)
    last: str = "-"
    trial: str = TRIAL

    def __call__(self, request: HttpRequest) -> HttpResponse:
        url = to_trial(request.url, self.trial)
        if request.method != "GET":
            self.pace.write()
        digest, length = _digest(request.body)
        path = _path(request.url)
        self.sent.append(f"{request.method} {_path(url)}")
        try:
            response = urllib_transport(HttpRequest(request.method, url, request.headers, request.body))
        except OSError as error:
            self.last = f"{request.method} {_path(url).split('?')[0]} → {error}"
            self.recorder.add(Exchange(request.method, path, digest, length, None, None, None))
            raise
        self.last = f"{request.method} {_path(url).split('?')[0]} → {response.status} {response.body[:160].decode('utf-8', 'replace')}"
        self.recorder.add(
            Exchange(
                request.method,
                path,
                digest,
                length,
                response.status,
                None,
                _recorded_body(response.body),
            )
        )
        return response


@dataclass
class ReplayTransport:
    """Transport klienta Skrzynki w odtwarzaniu: nagrane odpowiedzi tylko na nagrane żądania, w nagranej kolejności."""

    exchanges: Sequence[Exchange]
    problems: list[str] = field(default_factory=list)
    _next: int = 0

    def __call__(self, request: HttpRequest) -> HttpResponse:
        digest, _ = _digest(request.body)
        asked = f"{request.method} {_path(request.url)}"
        if self._next >= len(self.exchanges):
            self.problems.append(f"żądanie spoza nagrania: {asked}")
            raise OSError("brak nagrania")
        expected = self.exchanges[self._next]
        self._next += 1
        if (request.method, _path(request.url), digest) != (
            expected.method,
            expected.path,
            expected.request_sha256,
        ):
            self.problems.append(f"żądanie {asked} zamiast nagranego {expected.method} {expected.path}")
            raise OSError("inne żądanie niż w nagraniu")
        if expected.status is None:
            raise OSError("nagrany brak odpowiedzi")
        return HttpResponse(expected.status, _served_body(expected.body))

    def finish(self) -> list[str]:
        left = [exchange.describe() for exchange in self.exchanges[self._next :]]
        return self.problems + [f"klient nie wysłał nagranego żądania: {item}" for item in left]


_TOOL_PATH: Final = re.compile(rf"/repos/{re.escape(TOOL_REPOSITORY)}/|/repositories/\d+/")


class GitHubProxy:
    """Lokalny serwer, przez który ``tool_freshness`` pyta API GitHuba: na żywo przekazuje, w odtwarzaniu odpowiada.

    Przekazuje tylko GET pod repozytorium narzędzia (także ``/repositories/<id>/``, które GitHub podaje w ``Link``), a
    adresy ``Link`` w odpowiedzi kieruje z powrotem na siebie, żeby następna strona też przeszła przez nagranie.
    """

    def __init__(self, *, replay: Sequence[Exchange] | None = None, token: str | None = None) -> None:
        self._replay = list(replay) if replay is not None else None
        self._token = token
        self.exchanges: list[Exchange] = []
        self.problems: list[str] = []
        self._lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, link, body = proxy._answer(self.path, dict(self.headers))
                self.send_response(status)
                if link is not None:
                    self.send_header("Link", link.replace(API, proxy.base))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    @property
    def api(self) -> str:
        return f"{self.base}/repos/{TOOL_REPOSITORY}"

    def __enter__(self) -> GitHubProxy:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _answer(self, path: str, headers: Mapping[str, str]) -> tuple[int, str | None, bytes]:
        with self._lock:
            if not _TOOL_PATH.match(path):
                self.problems.append(f"pytanie poza repozytorium narzędzia: GET {path}")
                return 599, None, b"{}"
            if self._replay is None:
                return self._forward(path, headers)
            index = len(self.exchanges)
            if index >= len(self._replay) or self._replay[index].path != path:
                recorded = self._replay[index].path if index < len(self._replay) else "nic"
                self.problems.append(f"pytanie GET {path} zamiast nagranego {recorded}")
                return 599, None, b"{}"
            exchange = self._replay[index]
            self.exchanges.append(exchange)
            return exchange.status or 599, exchange.link, _served_body(exchange.body)

    def _forward(self, path: str, headers: Mapping[str, str]) -> tuple[int, str | None, bytes]:
        sent = {name: value for name, value in headers.items() if name.lower() in {"accept", "user-agent", "x-github-api-version"}}
        if self._token is not None:
            sent["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(API + path, headers=sent)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status, link, body = (
                    response.status,
                    response.headers.get("Link"),
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            with error:
                status, link, body = error.code, error.headers.get("Link"), error.read()
        except OSError:
            self.exchanges.append(Exchange("GET", path, None, None, None, None, None))
            return 599, None, b""
        self.exchanges.append(Exchange("GET", path, None, None, status, link, _recorded_body(body)))
        return status, link, body

    def take(self) -> list[Exchange]:
        """Wymiany od poprzedniego ``take`` (jednego przypadku)."""

        with self._lock:
            taken, self.exchanges = self.exchanges, []
            if self._replay is not None:
                self._replay = self._replay[len(taken) :]
            return taken

    def unused(self) -> list[str]:
        """Nagrane wymiany, o które klient jeszcze nie zapytał (w odtwarzaniu)."""

        with self._lock:
            left = (self._replay or [])[len(self.exchanges) :]
        return [exchange.describe() for exchange in left]


@dataclass
class Admin:
    """Harness runu: REST i GraphQL GitHuba kluczem ``gh`` Maksa, tylko w repozytoriach próbnych i tylko do odczytu poza
    nimi.

    Robi to, co w Skrzynce robi Maks ręcznie (etykiety, zamknięcie, usunięcie issue, pobranie pliku z Archiwum), i
    sprzątanie. Każde żądanie trafia do ``log``.
    """

    token: str
    pace: Pace
    log: list[str] = field(default_factory=list)

    def request(self, method: str, path: str, payload: object = None) -> tuple[int, object]:
        allowed = any(path.startswith(f"/repos/{trial}/") or path == f"/repos/{trial}" for trial in TRIALS)
        if method != "GET" and not allowed:
            raise OutsideTrial(f"harness zmienia poza repozytorium próbnym: {method} {path}")
        if method == "GET" and not (allowed or path in {"/rate_limit", "/user"}):
            raise OutsideTrial(f"harness czyta poza repozytorium próbnym: {path}")
        return self._send(method, path, payload)

    def delete_issue(self, node_id: str) -> tuple[int, object]:
        """Usuwa issue repozytorium próbnego o ``node_id`` (GraphQL ``deleteIssue``); sprawdza je wcześniej wywołujący."""

        query = "mutation($id: ID!) { deleteIssue(input: {issueId: $id}) { repository { nameWithOwner } } }"
        status, document = self._send("POST", "/graphql", {"query": query, "variables": {"id": node_id}})
        data = document.get("data") if isinstance(document, dict) else None
        deleted = data.get("deleteIssue") if isinstance(data, dict) else None
        repository = deleted.get("repository") if isinstance(deleted, dict) else None
        if isinstance(repository, dict) and repository.get("nameWithOwner") != TRIAL:
            raise OutsideTrial(f"GraphQL usunął issue spoza repozytorium próbnego: {repository}")
        return status, document

    def _send(self, method: str, path: str, payload: object) -> tuple[int, object]:
        if method != "GET":
            self.pace.write()
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            API + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "verify-github-skrzynki",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                status, raw = error.code, error.read()
        self.log.append(f"harness: {method} {path.split('?')[0]} → {status}")
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw[:200].decode("utf-8", "replace")

    def download(self, asset_id: int) -> bytes:
        """Treść pliku ``asset_id`` z Archiwum repozytorium próbnego ``TRIAL_ARCHIVE``, tak jak dostałby ją Maks.

        API odpowiada przekierowaniem na podpisany adres pod ``DOWNLOAD_HOST``; ten adres harness pobiera bez klucza,
        a każdy inny adres przekierowania to ``OutsideTrial``.
        """

        path = f"/repos/{TRIAL_ARCHIVE}/releases/assets/{asset_id}"
        status, location = self._head(API + path, {"Accept": "application/octet-stream"})
        self.log.append(f"harness: GET {path} (plik) → {status}")
        target = urllib.parse.urlsplit(location or "")
        if status != 302 or target.scheme != "https" or not (target.hostname or "").endswith(DOWNLOAD_HOST):
            raise OutsideTrial(f"pobranie pliku {asset_id}: {status} na {target.scheme}://{target.hostname}")
        with urllib.request.urlopen(urllib.request.Request(str(location)), timeout=30) as response:
            data: bytes = response.read()
        self.log.append(f"harness: GET {target.hostname} (podpisany adres pliku) → {response.status}")
        return data

    def web_status(self, url: str) -> int:
        """Status odpowiedzi strony GitHuba ``url`` z repozytorium próbnego Archiwum (bez śledzenia przekierowania) na
        prośbę z kluczem ``gh``: czy adres pobrania pliku prywatnego repozytorium działa bez sesji przeglądarki."""

        if not url.startswith(f"{WEB}/{TRIAL_ARCHIVE}/releases/download/"):
            raise OutsideTrial(f"harness pyta o stronę spoza Archiwum repozytorium próbnego: {url}")
        status, _ = self._head(url, {})
        self.log.append(f"harness: GET {url.removeprefix(WEB)} (strona) → {status}")
        return status

    def _head(self, url: str, headers: Mapping[str, str]) -> tuple[int, str | None]:
        """Status i ``Location`` odpowiedzi na GET ``url`` kluczem ``gh``, bez śledzenia przekierowania i bez treści."""

        request = urllib.request.Request(
            url,
            headers={**headers, "Authorization": f"Bearer {self.token}", "User-Agent": "verify-github-skrzynki"},
        )
        try:
            with urllib.request.build_opener(_Unredirected()).open(request, timeout=30) as response:
                return response.status, response.headers.get("Location")
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers.get("Location")

    def pages(self, path: str) -> list[object]:
        """Wszystkie strony listy ``path`` (z ``?`` w adresie) po 100."""

        found: list[object] = []
        for page in range(1, 50):
            status, entries = self.request("GET", f"{path}&per_page=100&page={page}")
            if status != 200 or not isinstance(entries, list):
                raise RuntimeError(f"harness: lista {path} → {status}")
            found += entries
            if len(entries) < 100:
                return found
        raise RuntimeError(f"harness: lista {path} ma ponad 49 stron")


class _Unredirected(urllib.request.HTTPRedirectHandler):
    """Przekierowanie zostaje odpowiedzią: klucz nie idzie na adres przekierowania."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


def write_recording(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read_recording(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document
