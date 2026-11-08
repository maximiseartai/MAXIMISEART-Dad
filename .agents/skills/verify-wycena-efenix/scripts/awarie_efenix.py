"""Faults between the efenix window and the Atrapa efenix: a local proxy that breaks one request of a Wycena w efenix.

The window talks to ``Proxy.url``; the proxy forwards every request to the Atrapa efenix (``tools/lib/atrapy/atrapa_efenix.py``)
without following redirects and answers the browser itself, so it can break any request, the redirects and page files
included, which ``page.route`` of Playwright misses. It changes the Atrapa only where a fault says so (``LOGGED_OUT``
ends its session), and it adds to every page it passes on two things the Atrapa lacks and efenix has or the check needs:

- a stylesheet ``css/efenix.css`` that the proxy serves itself, as efenix pages load fontawesome, so a page file the
  ``load`` event waits for can hang, break or be missing (#802);
- a click watcher that reports a click on a button the window must never use (Przekazanie do akceptacji, anulowanie and
  the „Tak” of their dialog) as a request to ``__przycisk-spoza-listy``, which the proxy counts and never forwards.

A request is a ``Call``: method, path without the query, the kind of search (the window's own or the one the list sends
by itself after loading) and its occurrence among calls of the same kind, so a fault hits the same request in every run
whatever the order of requests that the browser sends side by side. ``Fault`` lists what can go wrong with it: the
network (``CUT``, ``TORN``, ``STALLED``, ``SLOW`` from that request on until ``reconnect``), one answer (HTTP 4xx without
running the request, HTTP 5xx after running it, a redirect elsewhere, 200 with ``result: nok`` without running it, an
answer that never comes, an answer just before or just after the window's time limit), efenix logging the window out at
that request, and two that the browser side and
the explorer handle: the tab closed when the browser sends the request (``TAB_CLOSED``) and the tool's process killed
right before or right after efenix ran it (``KILLED``, snapshots taken by ``before_executed`` and ``after_executed``).
Three more belong to one kind of request: the login page under the address of an order page (``LOGIN_PAGE``, #808), and
the session ended when the list opens, after which Dad logs in or closes the tab while the window waits for him
(``LOGIN_LATER``, ``LOGIN_CLOSED``, #758), or Dad logs in and the list the window asks for next is an error page of
the server (``LOGIN_ERROR``, #891).
"""

from __future__ import annotations

import enum
import http.client
import socket
import struct
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

# Adresy stron i przyciski efenix z Atrapy, celowej kopii efenix (docs/agents/skille.md, „Co wyrocznia bierze z src”):
# pośrednik stoi przed Atrapą, więc rozpoznaje żądania i kliknięcia po jej adresach i przyciskach, a nie po tych z kodu,
# który sprawdza.
from atrapy.atrapa_efenix import (
    BY_LIST,
    CANCEL_BUTTON,
    FILL_EMMETT,
    FORWARD_BUTTON,
    LIST_PAGE,
    LOGIN_PAGE,
    ORDER_PAGE,
    SEARCH,
    STATUS_DIALOG,
)

STYLESHEET: Final = "css/efenix.css"
FORBIDDEN_CLICK: Final = "__przycisk-spoza-listy"
_FORBIDDEN_BUTTONS: Final = f"#{FORWARD_BUTTON}, #{CANCEL_BUTTON}, #{STATUS_DIALOG} .btn-ok"
_WATCHER: Final = (
    "<script>document.addEventListener('click', (event) => {"
    f" const button = event.target.closest && event.target.closest('{_FORBIDDEN_BUTTONS}');"
    f" if (button) navigator.sendBeacon('{FORBIDDEN_CLICK}', button.id || 'tak');"
    " }, true);</script>"
)
_PAGES: Final = (LIST_PAGE, ORDER_PAGE, LOGIN_PAGE)
_ELSEWHERE: Final = f"/{LIST_PAGE}?przekierowanie=1"


class Fault(enum.Enum):
    """What goes wrong with one request of the window; the value is the name in reports and ``--variant`` axes."""

    CUT = "zerwane połączenie"
    TORN = "odpowiedź zerwana w połowie"
    STALLED = "odpowiedź stanęła w połowie"
    SLOW = "efenix wolniejszy niż okno"
    HTTP_4XX = "HTTP 4xx bez wykonania (404 pliku strony, 403 innego żądania)"
    HTTP_5XX = "HTTP 500 po wykonaniu"
    LOGGED_OUT = "efenix wylogował przy tym żądaniu"
    REDIRECT = "przekierowanie na listę zleceń bez wykonania"
    REFUSED = "200 z result: nok bez wykonania, w ważnej sesji"
    REFUSED_NO_PROPOSAL = "propozycja Emmetta tego zlecenia to HTTP 500, a „Załaduj do zlecenia” 200 z result: nok bez wykonania"
    HUNG = "odpowiedź po wykonaniu nigdy nie przychodzi"
    LATE_BEFORE = "odpowiedź tuż przed granicą czasu okna"
    LATE_AFTER = "odpowiedź tuż po granicy czasu okna"
    LOGIN_PAGE = "strona logowania pod adresem strony, bez przekierowania i bez wykonania"
    TAB_CLOSED = "karta zamknięta przy wysłaniu żądania"
    KILLED = "proces narzędzia zabity tuż przed albo zaraz po wykonaniu żądania"
    LOGIN_LATER = "efenix wylogował przed otwarciem listy, a tata zalogował się w oknie"
    LOGIN_CLOSED = "efenix wylogował przed otwarciem listy, a tata zamknął kartę zamiast się zalogować"
    LOGIN_ERROR = "efenix wylogował przed otwarciem listy, tata zalogował się w oknie, a lista po nim to błąd serwera"


OUTAGES: Final = frozenset({Fault.CUT, Fault.TORN, Fault.STALLED, Fault.SLOW})
"""Faults of the network: from the faulted request on, until ``Proxy.reconnect``."""
DAD_LOGINS: Final = frozenset({Fault.LOGIN_LATER, Fault.LOGIN_CLOSED, Fault.LOGIN_ERROR})
"""Faults where Dad acts on the login page the window waits at: he logs in or closes the tab."""
LOGOUTS: Final = frozenset({Fault.LOGGED_OUT, *DAD_LOGINS})
"""Faults that end the Atrapa session at the faulted request, until Dad logs in."""
DAD: Final = "__tata"
"""Request that the login page sends 0.3 s after it shows, when Dad acts in it (``DAD_LOGINS``): the browser side logs
him in or closes the tab when it sees it, and after it, at ``LOGIN_ERROR``, the proxy answers the next list with HTTP 500."""


@dataclass(frozen=True, order=True)
class Call:
    """One request of the window: method, path without query, ``search`` (``okno``: the window's own search, ``lista``:
    the one the list sends by itself after loading, ``""``: not a search) and its occurrence (from 1) among equal calls."""

    method: str
    path: str
    search: str
    occurrence: int

    @property
    def kind(self) -> tuple[str, str, str]:
        return self.method, self.path, self.search

    @property
    def is_file(self) -> bool:
        return self.path.endswith((".js", ".css"))

    def __str__(self) -> str:
        search = f" ({self.search})" if self.search else ""
        return f"{self.method} {self.path}{search} #{self.occurrence}"


def call_kind(method: str, url: str, body: str) -> tuple[str, str, str]:
    """Kind of a request as the proxy and the browser side both see it."""

    path = urlparse(url).path.lstrip("/") or LIST_PAGE
    search = ""
    if path == SEARCH and method == "POST":
        search = "lista" if parse_qs(body).get("rodzaj") == [BY_LIST] else "okno"
    return method, path, search


class Counter:
    """Occurrences of each kind of call, in the order the requests come."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str, str], int] = {}
        self._lock = threading.Lock()

    def next(self, kind: tuple[str, str, str]) -> Call:
        with self._lock:
            count = self._seen[kind] = self._seen.get(kind, 0) + 1
        return Call(*kind, count)


@dataclass(frozen=True)
class Seen:
    """A call the proxy got, at ``at`` seconds from its start, and what it did with it."""

    call: Call
    at: float
    action: str


@dataclass
class Plan:
    """The fault ``fault`` at call ``target`` (``None``: no fault) and the window's time limit, which places the two
    late answers: ``early_s`` before it and ``late_s`` after it."""

    fault: Fault | None = None
    target: Call | None = None
    limit_s: float = 3.0
    early_s: float = 0.6
    late_s: float = 0.6


@dataclass
class Proxy:
    """The proxy in front of the Atrapa at ``upstream`` (``http://127.0.0.1:port/index.php``) with ``plan``.

    ``before_executed`` gets each call the proxy passes on right before the Atrapa gets it, and ``after_executed`` right
    after the Atrapa answered it and before the browser gets the answer.
    ``expire_session`` ends the Atrapa session (``AtrapaEfenix.expire_session``) for ``Fault.LOGGED_OUT``.
    """

    upstream: str
    plan: Plan
    expire_session: Callable[[], None]
    after_executed: Callable[[Call], None] = lambda _call: None
    before_executed: Callable[[Call], None] = lambda _call: None
    seen: list[Seen] = field(default_factory=list)
    forbidden_clicks: int = 0
    url: str = ""
    _outage: Fault | None = None
    _error_list: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _released: threading.Event = field(default_factory=threading.Event)
    _started: float = field(default_factory=time.monotonic)
    _counter: Counter = field(default_factory=Counter)
    _server: _Server | None = None
    _thread: threading.Thread | None = None

    def __enter__(self) -> Proxy:
        server = self._server = _Server(_handler(self))
        self._thread = threading.Thread(target=server.serve_forever, name="awarie-efenix", daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{server.server_address[1]}/{LIST_PAGE}"
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
        if self._server is not None:
            self._server.shutdown()
            self._server.close_connections()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join()

    def reconnect(self) -> None:
        """The network is back: no outage from now on (held answers stay held until ``release``)."""

        with self._lock:
            self._outage = None
            self.plan = Plan(limit_s=self.plan.limit_s)

    def release(self) -> None:
        """Every held answer ends now with its connection closed, as when the window that waited for it is gone."""

        self._released.set()

    def calls(self) -> list[Call]:
        with self._lock:
            return [seen.call for seen in self.seen]

    def _decide(self, method: str, url: str, body: str) -> tuple[Call, Fault | None]:
        call = self._counter.next(call_kind(method, url, body))
        with self._lock:
            plan = self.plan
            hit = plan.fault if plan.target == call else None
            if plan.fault is Fault.REFUSED_NO_PROPOSAL and plan.target is not None:
                # Dwie awarie przy jednym zleceniu (#908): jego propozycja Emmetta, a potem „Załaduj do zlecenia”.
                paired = call.method == "POST" and call.occurrence == plan.target.occurrence
                hit = {FILL_EMMETT: Fault.HTTP_5XX, plan.target.path: Fault.REFUSED}.get(call.path) if paired else None
            if hit in OUTAGES:
                self._outage = hit
            fault = self._outage if self._outage is not None else hit
            self.seen.append(Seen(call, time.monotonic() - self._started, "" if fault is None else fault.name))
        if fault in LOGOUTS:
            self.expire_session()
        return call, fault

    def _take_error_list(self) -> bool:
        """``LOGIN_ERROR``: whether this list, the first after Dad's login, is the server's error page (only once)."""

        with self._lock:
            taken, self._error_list = self._error_list, False
            return taken

    def _held(self, seconds: float | None = None) -> None:
        self._released.wait(seconds)


class _Server(ThreadingHTTPServer):
    """Proxy server on a free port of ``127.0.0.1`` that closes its open connections at the end."""

    daemon_threads = True
    request_queue_size = 128

    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        with self._connections_lock:
            self._connections.add(connection)
        return connection, address

    def shutdown_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
        if isinstance(request, socket.socket):
            with self._connections_lock:
                self._connections.discard(request)
        super().shutdown_request(request)

    def close_connections(self) -> None:
        with self._connections_lock:
            for connection in self._connections:
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)


@dataclass(frozen=True)
class _Answer:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


def _handler(proxy: Proxy) -> type[BaseHTTPRequestHandler]:
    upstream = urlparse(proxy.upstream)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except OSError as error:
                if not (isinstance(error, ConnectionError) or proxy._released.is_set()):
                    raise

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._serve("GET", b"")

        def do_POST(self) -> None:
            self._serve("POST", self.rfile.read(int(self.headers.get("Content-Length") or 0)))

        def _serve(self, method: str, body: bytes) -> None:
            own = urlparse(self.path).path.lstrip("/")
            if own in (FORBIDDEN_CLICK, DAD):
                with proxy._lock:
                    proxy.forbidden_clicks += own == FORBIDDEN_CLICK
                    proxy._error_list |= own == DAD and proxy.plan.fault is Fault.LOGIN_ERROR
                self._send(_Answer(HTTPStatus.NO_CONTENT, (), b""))
                return
            call, fault = proxy._decide(method, self.path, body.decode("utf-8", "replace"))
            if method == "GET" and call.path == LIST_PAGE and proxy._take_error_list():
                self._send(_error_page(HTTPStatus.INTERNAL_SERVER_ERROR))
                return
            if fault is Fault.CUT:
                self._cut()
                return
            if fault is Fault.HTTP_4XX:
                status = HTTPStatus.NOT_FOUND if call.is_file else HTTPStatus.FORBIDDEN
                self._send(_error_page(status))
                return
            if fault is Fault.REDIRECT:
                self._send(_Answer(HTTPStatus.FOUND, (("Location", _ELSEWHERE),), b""))
                return
            if fault is Fault.REFUSED:
                self._send(_Answer(HTTPStatus.OK, (("Content-Type", "application/json"),), b'{"result": "nok", "error": "Nie zapisano."}'))
                return
            if fault is Fault.LOGIN_PAGE:
                login = self._executed("GET", b"", Call("GET", LOGIN_PAGE, "", 0), f"/{LOGIN_PAGE}")
                self._send(_Answer(HTTPStatus.OK, login.headers, login.body))
                return
            proxy.before_executed(call)
            answer = self._executed(method, body, call)
            proxy.after_executed(call)
            match fault:
                case Fault.TORN | Fault.STALLED:
                    self._send_head(answer)
                    self.wfile.write(answer.body[: len(answer.body) // 2])
                    self.wfile.flush()
                    if fault is Fault.TORN:
                        self._cut()
                    else:
                        proxy._held()
                        self.close_connection = True
                case Fault.SLOW | Fault.HUNG:
                    proxy._held()
                    self.close_connection = True
                case Fault.HTTP_5XX:
                    self._send(_error_page(HTTPStatus.INTERNAL_SERVER_ERROR))
                case Fault.LATE_BEFORE | Fault.LATE_AFTER:
                    plan = proxy.plan
                    delay = plan.limit_s - plan.early_s if fault is Fault.LATE_BEFORE else plan.limit_s + plan.late_s
                    proxy._held(delay)
                    if proxy._released.is_set():
                        self.close_connection = True
                    else:
                        self._send(answer)
                case _:
                    self._send(answer)

        def _executed(self, method: str, body: bytes, call: Call, path: str | None = None) -> _Answer:
            """The answer of the Atrapa to this request (or to ``path``), or the proxy's own stylesheet; pages get the
            stylesheet and the watcher, and the login page, when Dad acts in it, the request ``DAD``."""

            if call.path == STYLESHEET:
                return _Answer(HTTPStatus.OK, (("Content-Type", "text/css; charset=utf-8"),), b"body { margin: 0; }\n")
            connection = http.client.HTTPConnection(upstream.hostname or "127.0.0.1", upstream.port, timeout=60)
            try:
                headers = {name: value for name in ("Content-Type", "Cookie") if (value := self.headers.get(name))}
                connection.request(method, path or self.path, body=body if method == "POST" else None, headers=headers)
                response = connection.getresponse()
                content = response.read()
                kept = tuple(
                    (name, value) for name, value in response.getheaders() if name.lower() in ("content-type", "location", "set-cookie")
                )
            finally:
                connection.close()
            if response.status == HTTPStatus.OK and method == "GET" and call.path in _PAGES:
                dad = proxy.plan.fault in DAD_LOGINS and call.path == LOGIN_PAGE
                acts = f"<script>setTimeout(() => fetch('{DAD}'), 300);</script>" if dad else ""
                content = content.replace(
                    b"</head>", f'<link rel="stylesheet" href="{STYLESHEET}?v=1">{_WATCHER}{acts}</head>'.encode(), 1
                )
            return _Answer(response.status, kept, content)

        def _send_head(self, answer: _Answer) -> None:
            self.send_response(answer.status)
            for name, value in answer.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(answer.body)))
            self.end_headers()

        def _send(self, answer: _Answer) -> None:
            self._send_head(answer)
            self.wfile.write(answer.body)

        def _cut(self) -> None:
            """Resets the connection without an answer (``SO_LINGER`` 0 sends RST)."""

            self.close_connection = True
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.connection.close()

    return Handler


def _error_page(status: HTTPStatus) -> _Answer:
    body = f"<!doctype html><html><head><title>{status.value}</title></head><body><p>{status.phrase}</p></body></html>"
    return _Answer(status, (("Content-Type", "text/html; charset=utf-8"),), body.encode())
