"""Atrapa API GitHuba na 127.0.0.1 dla pytań o Wydania: odpowiedzi po ścieżce i nagłówek ``Authorization`` każdego
pytania, nigdy połączenie z GitHubem."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Final, Literal

from rozliczenia.centrum.tool_freshness import PUBLISHED_PAGE

# Tyle pytań bez tokenu zostało w tej godzinie: odmowa tokenu nie jest odmową z powodu limitu.
_LEFT: Final = {"X-RateLimit-Remaining": "59"}


@dataclass(frozen=True)
class Answer:
    """Odpowiedź atrapy: status, treść JSON i nagłówki (``Link``, ``Location``, ``X-RateLimit-*``).

    ``ending`` zmienia koniec treści: ``"endless"`` to treść bez końca, aż klient przestanie czytać, a ``"cut"`` to
    połączenie zerwane w środku treści."""

    status: int = 200
    body: object = None
    headers: Mapping[str, str] = field(default_factory=dict)
    ending: Literal["endless", "cut"] | None = None


@dataclass(frozen=True)
class Asked:
    """Jedno pytanie do atrapy: ścieżka z zapytaniem i nagłówek ``Authorization`` (``None``: bez tokenu)."""

    path: str
    authorization: str | None


class GitHubApi:
    """Atrapa pod ``url``: ``answers`` po ścieżce, a na każde pytanie z tokenem odmowa ``refused_token``, gdy jest
    (status albo cała odpowiedź, np. odmowa z powodu limitu konta)."""

    def __init__(self, answers: Mapping[str, Answer], refused_token: int | Answer | None) -> None:
        self.answers = answers
        self.refused_token = refused_token
        self.asked: list[Asked] = []
        self.url = ""
        self.closing = threading.Event()


@contextmanager
def github_api(answers: Mapping[str, Answer], *, refused_token: int | Answer | None = None) -> Iterator[GitHubApi]:
    """Atrapa API GitHuba czynna w bloku ``with``; ścieżka spoza ``answers`` to 404."""

    api = GitHubApi(answers, refused_token)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            authorization = self.headers.get("Authorization")
            api.asked.append(Asked(self.path, authorization))
            refused = api.refused_token
            refusal = Answer(refused, {"message": "Bad credentials"}, _LEFT) if isinstance(refused, int) else refused
            if authorization is not None and refusal is not None:
                answer = refusal
            else:
                answer = api.answers.get(self.path, Answer(404, {"message": "Not Found"}, _LEFT))
            body = json.dumps(answer.body).encode("utf-8")
            self.send_response(answer.status)
            for name, value in answer.headers.items():
                self.send_header(name, value)
            if answer.ending is None:
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._chunked(body, endless=answer.ending == "endless")

        def _chunked(self, body: bytes, *, endless: bool) -> None:
            self.close_connection = True
            chunk = b"%x\r\n%s\r\n" % (len(body), body)
            try:
                self.wfile.write(chunk)
                while endless and not api.closing.is_set():
                    self.wfile.write(chunk)
            except OSError:  # klient przestał czytać
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    api.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield api
    finally:
        api.closing.set()
        server.shutdown()
        server.server_close()
        thread.join()


def newest_on_main(repository: str, tag: str, commit: str) -> dict[str, Answer]:
    """Odpowiedzi API repozytorium pod ścieżką ``repository`` z jednym Wydaniem ``tag`` na czubku `main` (``commit``):
    lista tagów, czubek `main`, porównanie z nim i lista GitHub Releases."""

    released = {"tag_name": tag, "body": "", "published_at": "2026-11-08T06:00:00Z", "draft": False, "prerelease": False}
    return {
        f"{repository}/tags?per_page=100": Answer(body=[{"name": tag, "commit": {"sha": commit}}]),
        f"{repository}/git/ref/heads/main": Answer(body={"ref": "refs/heads/main", "object": {"sha": commit}}),
        f"{repository}/compare/{commit}...{commit}?per_page=1&page=2": Answer(body={"status": "identical", "ahead_by": 0}),
        f"{repository}/releases?per_page={PUBLISHED_PAGE}": Answer(body=[released]),
    }
