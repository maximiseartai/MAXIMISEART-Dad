from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from email.message import Message
from http.server import BaseHTTPRequestHandler
import itertools
import json
import math
from pathlib import Path
import re
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse

import pytest

from atrapy.serwer_http import serwer_http
from rozliczenia.centrum import tool_freshness, tool_update
from rozliczenia.centrum.github import TOOL_API
from rozliczenia.centrum.opener import opener
from rozliczenia.centrum.tool_freshness import (
    RELEASE_NOTES_THREAD,
    RELEASES_THREAD,
    AnswerSource,
    GitHubReleases,
    KeySource,
    PublishedRelease,
    RateLimited,
    RememberedRelease,
    ToolFreshness,
    offers_update,
    published_from,
    releases_from,
)
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.version import SERVICE, RunningCentrum, running_centrum, tool_commit
from tests.fixtures.github_api import Answer, github_api, newest_on_main
from tests.fixtures.linie_watkow import new_line, threads_since
from tests.fixtures.proxy_systemu import system_proxy

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

MAIN = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
TOKEN = "token-wymyslony-w-tescie"
WITH_TOKEN = f"Bearer {TOKEN}"
BRANCH = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
OLDER = "1111111111111111111111111111111111111111"
NEWEST = "2222222222222222222222222222222222222222"
OTHER = "3333333333333333333333333333333333333333"
OFF_MAIN = "4444444444444444444444444444444444444444"
NOT_COMPARED = "5555555555555555555555555555555555555555"
UNCOUNTED = "6666666666666666666666666666666666666666"
MERGED_BRANCH = "7777777777777777777777777777777777777777"
REFUSED_MIDWAY = "8888888888888888888888888888888888888888"
FIRST_COMMIT = "9999999999999999999999999999999999999999"
FAR_ON_LINE = "abababababababababababababababababababab"
MERGED_LATE = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
MERGED_FAR = "efefefefefefefefefefefefefefefefefefefef"
NOT_A_COMMIT = "nie-commit"
_STATUS = {
    (OLDER, MAIN): "ahead",
    (OLDER, f"{MAIN}~1"): "identical",
    (NEWEST, MAIN): "identical",
    (OTHER, MAIN): "diverged",
    (OFF_MAIN, MAIN): "behind",
    (MERGED_BRANCH, MAIN): "ahead",
    (MERGED_BRANCH, f"{MAIN}~1"): "behind",
    (REFUSED_MIDWAY, MAIN): "ahead",
    (UNCOUNTED, MAIN): "identical",
    (NEWEST, NOT_A_COMMIT): "identical",
    (FAR_ON_LINE, MAIN): "ahead",
    (MERGED_FAR, MAIN): "ahead",
    (MERGED_LATE, MAIN): "ahead",
    (MERGED_LATE, f"{MAIN}~1"): "diverged",
    (MERGED_LATE, f"{MAIN}~2"): "diverged",
    (FIRST_COMMIT, MAIN): "ahead",
    (FIRST_COMMIT, f"{MAIN}~1"): "identical",
}
_ODD_REFS = {
    "czubek-lista": json.dumps([]),
    "czubek-nie-obiektem": json.dumps({"object": "main"}),
    "czubek-bez-napisu": json.dumps({"object": {"sha": 5}}),
}
_ODD_COMPARES: dict[str, str | None] = {
    "porownanie-nie-obiektem": json.dumps([]),
    "porownanie-bez-napisu": json.dumps({"status": 5, "ahead_by": 1}),
    "porownanie-nie-json": "<html>GitHub ma awarię</html>",
    "porownanie-zerwane": None,
}
_AHEAD_BY = {FIRST_COMMIT: 3, FAR_ON_LINE: 1000, MERGED_LATE: 3, MERGED_FAR: 1000}
_FAR_DEPTH = 700


def _far_status(base: str, head: str) -> str | None:
    if base not in (FAR_ON_LINE, MERGED_FAR) or not head.startswith(f"{MAIN}~"):
        return None
    depth = int(head.removeprefix(f"{MAIN}~"))
    return "ahead" if depth < _FAR_DEPTH else "identical" if depth == _FAR_DEPTH else "behind"
_NOT_FOUND = {(FIRST_COMMIT, f"{MAIN}~2"), (FIRST_COMMIT, f"{MAIN}~3")}


def _tags(*named: tuple[str, str]) -> str:
    return json.dumps([{"name": name, "commit": {"sha": sha, "url": "https://api.github.com/x"}} for name, sha in named])


_PAGES = {
    "/tagi/tags?per_page=100": (
        _tags(("v0.9.0", OLDER), ("v0.10.0", NEWEST), ("proba", OTHER), ("v0.10", OTHER), ("v1.0.0-rc1", OTHER)),
        None,
    ),
    "/strony/tags?per_page=100": (_tags(("v0.9.0", OLDER)), "/strony/tags?page=2"),
    "/strony/tags?page=2": (_tags(("v1.0.0", NEWEST), ("v0.11.0", OLDER)), None),
    "/spoza-main/tags?per_page=100": (_tags(("v0.2.0", OLDER), ("v0.3.0", OFF_MAIN), ("v0.4.0", OTHER)), None),
    "/tylko-spoza-main/tags?per_page=100": (_tags(("v0.3.0", OFF_MAIN)), None),
    "/bez-wydan/tags?per_page=100": (_tags(("proba", OTHER)), None),
    "/bez-konca/tags?per_page=100": (_tags(("v0.1.0", OLDER)), "/bez-konca/tags?per_page=100"),
    "/bez-porownania/tags?per_page=100": (_tags(("v0.1.0", NOT_COMPARED)), None),
    "/bez-czubka/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/bez-czubka/git/ref/heads/main": (json.dumps({"object": {"sha": NOT_A_COMMIT}}), None),
    "/bez-liczby/tags?per_page=100": (_tags(("v0.1.0", UNCOUNTED)), None),
    "/z-galezi/tags?per_page=100": (_tags(("v0.1.0", MERGED_BRANCH)), None),
    "/odmowa-w-wyszukiwaniu/tags?per_page=100": (_tags(("v0.1.0", REFUSED_MIDWAY)), None),
    "/od-pierwszego-commitu/tags?per_page=100": (_tags(("v0.1.0", FIRST_COMMIT)), None),
    "/daleko/tags?per_page=100": (_tags(("v0.1.0", FAR_ON_LINE)), None),
    "/z-galezi-pozniej/tags?per_page=100": (_tags(("v0.1.0", MERGED_LATE)), None),
    "/czubek-lista/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/czubek-nie-obiektem/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/czubek-bez-napisu/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/porownanie-nie-obiektem/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/porownanie-bez-napisu/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/porownanie-nie-json/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/porownanie-zerwane/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/piec-wyzszych-spoza-main/tags?per_page=100": (
        _tags(*((f"v0.{minor}.0", OFF_MAIN) for minor in range(2, 7)), ("v0.1.0", OLDER)),
        None,
    ),
    "/cztery-wyzsze-spoza-main/tags?per_page=100": (
        _tags(*((f"v0.{minor}.0", OFF_MAIN) for minor in range(2, 6)), ("v0.1.0", OLDER)),
        None,
    ),
}

NOTES = "Plik zbiorczy ma kolumnę z kilometrami.\n\n## Rozwiązane sprawy taty\n\n- Uwaga taty #12: Kilometry\n"


def _release(tag: object, *, body: object = "", published_at: object = "2026-10-20T10:00:00Z", **flags: object) -> object:
    return {"tag_name": tag, "body": body, "published_at": published_at, "draft": False, "prerelease": False} | flags


_PAGES["/obiekt/releases?per_page=30"] = (json.dumps({"message": "Moved Permanently"}), None)
_PAGES["/bez-opublikowanych/releases?per_page=30"] = (json.dumps([]), None)
_PAGES["/wydania/releases?per_page=30"] = (
    json.dumps(
        [
            _release("v0.3.0", draft=True),
            _release("v0.2.1", prerelease=True),
            _release("v0.2.0", body=NOTES, published_at="2026-10-20T10:00:00Z"),
            _release("proba"),
            _release("v0.1.5", published_at="20.10.2026"),
            _release("v0.1.4", published_at="2026-10-15T10:00:00"),
            _release("v0.1.3", body=7),
            "v0.1.2",
            _release("v0.1.0", body=None, published_at="2026-10-01T08:00:00+02:00"),
        ]
    ),
    None,
)


def _pull(merge_commit_sha: str, **fields: object) -> object:
    merged = {"number": 461, "merge_commit_sha": merge_commit_sha, "merged_at": "2026-10-25T19:26:59Z"}
    return merged | {"base": {"ref": "main"}, "head": {"sha": BRANCH}} | fields


_PAGES["/daleko-scalone/tags?per_page=100"] = (_tags(("v0.1.0", MERGED_FAR)), None)
_PAGES[f"/daleko-scalone/commits/{MERGED_FAR}/pulls"] = (json.dumps([_pull(BRANCH), _pull(MERGED_FAR)]), None)
_PAGES[f"/z-galezi/commits/{MERGED_BRANCH}/pulls"] = (json.dumps([_pull(MAIN, head={"sha": MERGED_BRANCH})]), None)
_PULLS_NOT_MERGING = {
    "pr-do-galezi": [_pull(MERGED_BRANCH, base={"ref": "agent"})],
    "pr-otwarty": [_pull(MERGED_BRANCH, merged_at=None)],
    "pr-bez-bazy": [_pull(MERGED_BRANCH, base=None)],
    "pr-napisem": ["#461"],
    "pr-liczba": 5,
}
for _repository, _pulls in _PULLS_NOT_MERGING.items():
    _PAGES[f"/{_repository}/tags?per_page=100"] = (_tags(("v0.1.0", MERGED_BRANCH)), None)
    _PAGES[f"/{_repository}/commits/{MERGED_BRANCH}/pulls"] = (json.dumps(_pulls), None)
_MERGED_NOT_IN_MAIN = {"scalony-poza-main": OTHER, "scalony-przed-czubkiem": OFF_MAIN}
for _repository, _commit in _MERGED_NOT_IN_MAIN.items():
    _PAGES[f"/{_repository}/tags?per_page=100"] = (_tags(("v0.1.0", _commit)), None)
    _PAGES[f"/{_repository}/commits/{_commit}/pulls"] = (json.dumps([_pull(_commit)]), None)


_ASKED: list[str] = []
_ASKED_HEADERS: list[Message] = []


def _comparisons() -> int:
    return sum("/compare/" in path for path in _ASKED)


class _GitHub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        _ASKED.append(self.path)
        _ASKED_HEADERS.append(self.headers)
        repository, _, rest = self.path[1:].partition("/")
        if self.path in _PAGES:
            body, following = _PAGES[self.path]
            self.send_response(200)
            if following is not None:
                host = self.headers["Host"]
                self.send_header("Link", f'<http://{host}{following}>; rel="next", <http://{host}/tagi>; rel="last"')
            self.end_headers()
            self.wfile.write(body.encode("ascii"))
        elif rest == "git/ref/heads/main" and repository in _ODD_REFS:
            self._answer(200, _ODD_REFS[repository])
        elif rest.startswith("compare/") and repository in _ODD_COMPARES:
            answer = _ODD_COMPARES[repository]
            if answer is None:
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
            else:
                self._answer(200, answer)
        elif rest == "git/ref/heads/main" and repository != "limit":
            self._answer(200, json.dumps({"ref": "refs/heads/main", "object": {"sha": MAIN, "type": "commit"}}))
        elif rest.startswith("compare/") and rest.endswith("?per_page=1&page=2"):
            base, _, head = rest.removeprefix("compare/").removesuffix("?per_page=1&page=2").partition("...")
            status = _STATUS.get((base, head)) or _far_status(base, head)
            if (base, head) in _NOT_FOUND:
                self._answer(404, '{"message": "Not Found"}')
            elif status is None:
                self._answer(403, '{"message": "API rate limit exceeded"}')
            else:
                counted = {} if base == UNCOUNTED else {"ahead_by": _AHEAD_BY.get(base, 1)}
                self._answer(200, json.dumps({"status": status, **counted, "commits": [], "files": []}))
        elif repository == "limit":
            self._answer(403, '{"message": "API rate limit exceeded"}')
        else:
            self._answer(200, "<html>to nie jest lista tagów</html>")

    def _answer(self, status: int, body: str) -> None:
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode("ascii"))

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def github() -> Iterator[str]:
    _ASKED.clear()
    _ASKED_HEADERS.clear()
    with serwer_http(_GitHub, name="atrapa-api-github") as server:
        yield server.url


def test_najnowsze_wydanie_to_najwyzszy_numer_a_nie_ostatni_tag_alfabetycznie(github: str) -> None:
    assert releases_from(f"{github}/tagi", timeout_s=30) == GitHubReleases(NEWEST, "v0.10.0")


def test_najnowsze_wydanie_ze_wszystkich_stron_listy_tagow(github: str) -> None:
    assert releases_from(f"{github}/strony", timeout_s=30) == GitHubReleases(NEWEST, "v1.0.0")


def test_aktualnosc_pyta_github_naglowkami_api_rest_z_wersja_api(github: str) -> None:
    # ZEWNĘTRZNE: REST API GitHuba odmawia pytania bez nagłówka User-Agent kodem 403 (docs.github.com, Getting started with the REST API, User agent)
    expected = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
        "Authorization": None,
    }

    assert releases_from(f"{github}/tagi", timeout_s=30) == GitHubReleases(NEWEST, "v0.10.0")
    assert published_from(f"{github}/wydania", timeout_s=30) is not None

    assert len(_ASKED_HEADERS) >= 2
    assert all({name: headers[name] for name in expected} == expected for headers in _ASKED_HEADERS)


def test_aktualnosc_laczy_sie_z_githubem_wprost_mimo_proxy_w_ustawieniach_systemu(
    github: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with system_proxy(monkeypatch) as proxied:
        assert releases_from(f"{github}/tagi", timeout_s=30) == GitHubReleases(NEWEST, "v0.10.0")
        assert published_from(f"{github}/wydania", timeout_s=30) is not None

    assert proxied == []


def _health(answer: dict[str, str]) -> type[BaseHTTPRequestHandler]:
    class _Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(answer).encode()
            self.send_response(200 if self.path == "/api/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return _Health


def test_health_centrum_na_tym_komputerze_idzie_wprost_mimo_proxy_w_ustawieniach_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    health = _health({"service": SERVICE, "commit": "a" * 40})

    with serwer_http(health, name="atrapa-health-centrum") as server, system_proxy(monkeypatch) as proxied:
        running = running_centrum(server.server_address[1], timeout_s=30)

    assert (running, proxied) == (RunningCentrum("a" * 40), [])


def test_health_innej_uslugi_na_porcie_centrum_to_nie_centrum_rozliczen() -> None:
    with serwer_http(_health({"service": "inna-usluga", "commit": "a" * 40}), name="atrapa-health-innej-uslugi") as server:
        running = running_centrum(server.server_address[1], timeout_s=30)

    assert running is None


def _client_hello(server: socket.socket) -> bytes:
    connection, _ = server.accept()
    with connection:
        data = b""
        while len(data) < 5 or len(data) < 5 + int.from_bytes(data[3:5], "big"):
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
    return data


# ZEWNĘTRZNE: ClientHello to nagłówek rekordu, nagłówek wiadomości, wersja, losowe bajty, potem identyfikator sesji, szyfry i kompresje z długością, a po nich rozszerzenia z długością (RFC 8446, 4.1.2 i 5.1; ALPN: RFC 7301, 3.1)
_RECORD_HEADER, _HANDSHAKE_HEADER, _LEGACY_VERSION, _RANDOM = 5, 4, 2, 32
_SESSION_ID_LENGTH, _CIPHER_SUITES_LENGTH, _COMPRESSION_METHODS_LENGTH, _EXTENSIONS_LENGTH = 1, 2, 1, 2
_ALPN_EXTENSION = 16


def _length_prefixed_end(hello: bytes, position: int, length_bytes: int) -> int:
    return position + length_bytes + int.from_bytes(hello[position : position + length_bytes], "big")


def _alpn_protocols(hello: bytes) -> list[bytes] | None:
    position = _RECORD_HEADER + _HANDSHAKE_HEADER + _LEGACY_VERSION + _RANDOM
    for length_bytes in (_SESSION_ID_LENGTH, _CIPHER_SUITES_LENGTH, _COMPRESSION_METHODS_LENGTH):
        position = _length_prefixed_end(hello, position, length_bytes)
    end = _length_prefixed_end(hello, position, _EXTENSIONS_LENGTH)
    position += _EXTENSIONS_LENGTH
    while position < end:
        kind = int.from_bytes(hello[position : position + 2], "big")
        length = int.from_bytes(hello[position + 2 : position + 4], "big")
        data = hello[position + 4 : position + 4 + length]
        if kind == _ALPN_EXTENSION:
            protocols, index = [], 2
            while index < len(data):
                protocols.append(data[index + 1 : index + 1 + data[index]])
                index += 1 + data[index]
            return protocols
        position += 4 + length
    return None


def test_kontekst_tls_centrum_proponuje_serwerowi_tylko_http_1_1_jak_kontekst_ktory_urllib_tworzy_sam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    with socket.create_server(("127.0.0.1", 0)) as server:
        hello: list[bytes] = []
        thread = threading.Thread(target=lambda: hello.append(_client_hello(server)), daemon=True)
        thread.start()
        with pytest.raises(urllib.error.URLError):
            opener().open(f"https://127.0.0.1:{server.getsockname()[1]}/", timeout=30)
        thread.join(30)

    assert _alpn_protocols(hello[0]) == [b"http/1.1"]


def test_sprawdzenia_wydan_i_health_wczytuja_certyfikaty_systemu_najwyzej_raz_na_proces(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[ssl.SSLContext] = []
    load_default_certs = ssl.SSLContext.load_default_certs

    def counted(context: ssl.SSLContext, purpose: ssl.Purpose = ssl.Purpose.SERVER_AUTH) -> None:
        loads.append(context)
        load_default_certs(context, purpose)

    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", counted)
    with github_api(newest_on_main("/repos/tata/narzedzie", "v9.0.0", NEWEST)) as api:
        port = urllib.parse.urlsplit(api.url).port
        assert port is not None
        for _ in range(2):
            assert releases_from(f"{api.url}/repos/tata/narzedzie", timeout_s=30) == GitHubReleases(NEWEST, "v9.0.0")
            assert running_centrum(port, timeout_s=30) is None

    assert (len(api.asked), len(loads) <= 1) == (8, True)


@pytest.mark.parametrize("repository", ["bez-wydan", "tylko-spoza-main"])
def test_bez_wydania_na_main_github_odpowiada_ze_nie_ma_wydania(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) == GitHubReleases(None, None)


@pytest.mark.parametrize(
    "repository",
    ["limit", "strona", "bez-konca", "bez-porownania", "bez-czubka", "bez-liczby"],
    ids=["odmowa", "nie-lista", "bez-konca", "odmowa-porownania", "czubek-main-nie-commitem", "porownanie-bez-liczby"],
)
def test_odmowa_odpowiedz_nie_z_api_albo_niepelna_lista_to_nie_wiadomo(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) is None


def test_wydanie_z_galezi_wciagnietej_mergem_nie_jest_na_main_i_ta_odpowiedz_zostaje_w_pamieci(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/z-galezi", timeout_s=30, known=known) == GitHubReleases(None, None)
    assert known == {MERGED_BRANCH: False}
    _ASKED.clear()
    assert releases_from(f"{github}/z-galezi", timeout_s=30, known=known) == GitHubReleases(None, None)
    assert _comparisons() == 0


def test_wydanie_z_galezi_wciagnietej_po_dalszych_zmianach_main_nie_jest_na_main(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/z-galezi-pozniej", timeout_s=30, known=known) == GitHubReleases(None, None)
    assert known == {MERGED_LATE: False}


def test_wydanie_daleko_na_linii_main_kosztuje_tylko_logarytm_porownan(github: str) -> None:
    assert releases_from(f"{github}/daleko", timeout_s=30) == GitHubReleases(FAR_ON_LINE, "v0.1.0")
    assert _comparisons() <= math.log2(_AHEAD_BY[FAR_ON_LINE]) + 2


def test_aktualnosc_w_centrum_pamieta_linie_main_miedzy_sprawdzeniami(
    github: str, prawdziwe_wydania_githuba: Callable[[KeySource, str], AnswerSource]
) -> None:
    release = prawdziwe_wydania_githuba(lambda: None, f"{github}/z-galezi")

    assert release() == GitHubReleases(None, None)
    _ASKED.clear()
    assert release() == GitHubReleases(None, None)
    assert _comparisons() == 0


def test_wydanie_ze_scalenia_pr_daleko_na_linii_main_to_cztery_pytania_bez_wzgledu_na_odleglosc(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/daleko-scalone", timeout_s=30, known=known) == GitHubReleases(MERGED_FAR, "v0.1.0")
    assert (_ASKED, known) == (
        [
            "/daleko-scalone/tags?per_page=100",
            "/daleko-scalone/git/ref/heads/main",
            f"/daleko-scalone/compare/{MERGED_FAR}...{MAIN}?per_page=1&page=2",
            f"/daleko-scalone/commits/{MERGED_FAR}/pulls",
        ],
        {MERGED_FAR: True},
    )


@pytest.mark.parametrize("repository", _PULLS_NOT_MERGING)
def test_wydanie_z_galezi_z_pr_ktory_go_nie_scalil_do_main_nie_jest_na_main(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) == GitHubReleases(None, None)


@pytest.mark.parametrize("repository", _MERGED_NOT_IN_MAIN)
def test_scalenie_pr_do_main_spoza_czubka_main_nie_jest_wydaniem(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) == GitHubReleases(None, None)


def test_wydanie_na_pierwszym_commicie_repozytorium_jest_na_main(github: str) -> None:
    assert releases_from(f"{github}/od-pierwszego-commitu", timeout_s=30) == GitHubReleases(FIRST_COMMIT, "v0.1.0")


def test_odmowa_githuba_w_polowie_wyszukiwania_to_nie_wiadomo_i_nic_nie_zostaje_w_pamieci(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/odmowa-w-wyszukiwaniu", timeout_s=30, known=known) is None
    assert known == {}


@pytest.mark.parametrize("repository", [*_ODD_REFS, *_ODD_COMPARES])
def test_czubek_main_albo_porownanie_w_innym_ksztalcie_to_nie_wiadomo(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) is None


def test_wyzsze_wydanie_spoza_main_jest_pominiete_a_nizsze_na_main_wybrane_po_jednym_pytaniu_o_czubek_main(github: str) -> None:
    assert releases_from(f"{github}/spoza-main", timeout_s=30) == GitHubReleases(OLDER, "v0.2.0")
    assert _comparisons() >= 3
    assert sum(path.endswith("/git/ref/heads/main") for path in _ASKED) == 1


@pytest.mark.parametrize(
    ("repository", "newest"),
    [("cztery-wyzsze-spoza-main", GitHubReleases(OLDER, "v0.1.0")), ("piec-wyzszych-spoza-main", None)],
    ids=["piate-wydanie-na-main", "szoste-wydanie-na-main"],
)
def test_aktualnosc_sprawdza_po_kolei_najwyzej_piec_najwyzszych_wydan_a_dalej_nie_wiadomo(
    github: str, repository: str, newest: GitHubReleases | None
) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) == newest


def test_wydanie_przed_czubkiem_main_nie_zostaje_w_pamieci_a_gdy_main_do_niego_dojdzie_jest_najnowsze() -> None:
    ahead_of_main = {
        f"{REPOSITORY}/tags?per_page=100": Answer(body=[{"name": "v0.2.0", "commit": {"sha": NEWEST}}]),
        f"{REPOSITORY}/git/ref/heads/main": Answer(body={"object": {"sha": MAIN}}),
        f"{REPOSITORY}/compare/{NEWEST}...{MAIN}?per_page=1&page=2": Answer(body={"status": "behind", "ahead_by": 0}),
    }
    known: dict[str, bool] = {}
    with github_api(ahead_of_main) as api:
        before = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, known=known)
        api.answers = newest_on_main(REPOSITORY, "v0.2.0", NEWEST)
        after = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, known=known)

    assert (before, after, known) == (GitHubReleases(None, None), GitHubReleases(NEWEST, "v0.2.0"), {NEWEST: True})


_TOTAL_LIMIT_S = 0.4
_PIECES = 10
_PIECE_PAUSE_S = _TOTAL_LIMIT_S / 5


def _answering_in_pieces(answers: Mapping[str, Answer]) -> type[BaseHTTPRequestHandler]:
    class _InPieces(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(answers[self.path].body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            bounds = [len(body) * piece // _PIECES for piece in range(_PIECES + 1)]
            for start, end in itertools.pairwise(bounds):
                time.sleep(_PIECE_PAUSE_S)
                self.wfile.write(body[start:end])

        def log_message(self, format: str, *args: object) -> None:
            pass

    return _InPieces


def test_wydania_z_odpowiedziami_wolniejszymi_niz_limit_to_nie_wiadomo_a_linia_main_i_tak_trafia_do_pamieci() -> None:
    known: dict[str, bool] = {}
    line = new_line()
    with serwer_http(_answering_in_pieces(newest_on_main(REPOSITORY, "v0.2.0", NEWEST)), name="atrapa-api-github") as server:
        newest = releases_from(f"{server.url}{REPOSITORY}", timeout_s=_TOTAL_LIMIT_S, known=known)
        for late in threads_since(line, named=RELEASES_THREAD):
            late.join(30)

    assert (newest, known) == (None, {NEWEST: True})


def test_lista_wydan_wolniejsza_niz_limit_to_nie_wiadomo() -> None:
    line = new_line()
    with serwer_http(_answering_in_pieces(newest_on_main(REPOSITORY, "v0.2.0", NEWEST)), name="atrapa-api-github") as server:
        published = published_from(f"{server.url}{REPOSITORY}", timeout_s=_TOTAL_LIMIT_S)
        for late in threads_since(line, named=RELEASE_NOTES_THREAD):
            late.join(30)

    assert published is None


def test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu() -> None:
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        started = time.monotonic()

        answer = releases_from(f"http://127.0.0.1:{silent.getsockname()[1]}/tagi", timeout_s=0.3)

        assert (answer, time.monotonic() - started < 1.5) == (None, True)


def _released_port() -> int:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        return int(closed.getsockname()[1])


def test_brak_sieci_to_nie_wiadomo() -> None:
    assert releases_from(f"http://127.0.0.1:{_released_port()}/tagi", timeout_s=30) is None


def test_aktualnosc_i_aktualizacja_pytaja_repozytorium_tego_checkoutu_bez_przekierowania() -> None:
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=Path(__file__).parent, capture_output=True, text=True, check=True
    ).stdout.strip()
    repository = re.sub(r"^(https://github\.com/|git@github\.com:)|\.git$", "", origin)

    assert TOOL_API == f"https://api.github.com/repos/{repository}"
    assert tool_update.ToolClone(Path()).origin == f"https://github.com/{repository}.git"


def test_lista_wydan_ma_tylko_opublikowane_wydania_z_notka_i_czasem_publikacji(github: str) -> None:
    assert published_from(f"{github}/wydania", timeout_s=30) == (
        PublishedRelease(Release((0, 2, 0), "v0.2.0"), NOTES, datetime(2026, 10, 20, 10, tzinfo=timezone.utc)),
        PublishedRelease(Release((0, 1, 0), "v0.1.0"), "", datetime(2026, 10, 1, 6, tzinfo=timezone.utc)),
    )


@pytest.mark.parametrize("repository", ["limit", "strona", "obiekt"], ids=["odmowa", "nie-json", "obiekt-zamiast-listy"])
def test_lista_wydan_bez_odpowiedzi_api_to_nie_wiadomo(github: str, repository: str) -> None:
    assert published_from(f"{github}/{repository}", timeout_s=30) is None


def test_bez_opublikowanych_wydan_lista_wydan_jest_pusta_a_nie_brak_odpowiedzi(github: str) -> None:
    assert published_from(f"{github}/bez-opublikowanych", timeout_s=30) == ()


def test_lista_wydan_bez_sieci_to_nie_wiadomo() -> None:
    assert published_from(f"http://127.0.0.1:{_released_port()}/wydania", timeout_s=30) is None


REPOSITORY = "/repos/tata/narzedzie"


def test_z_tokenem_kazde_pytanie_o_wydania_do_hosta_api_idzie_z_tokenem_a_strona_z_innego_hosta_bez_niego() -> None:
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST)) as elsewhere:
        next_page = f'<{elsewhere.url}{REPOSITORY}/tags?per_page=100>; rel="next"'
        first_page = {f"{REPOSITORY}/tags?per_page=100": Answer(body=[], headers={"Link": next_page})}
        with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST) | first_page) as api:
            newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)
            published = published_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert (newest, published is not None) == (GitHubReleases(NEWEST, "v0.2.0"), True)
    assert [(asked.path, asked.authorization) for asked in api.asked] == [
        (path, WITH_TOKEN) for path in newest_on_main(REPOSITORY, "v0.2.0", NEWEST)
    ]
    assert [asked.authorization for asked in elsewhere.asked] == [None]


def test_przekierowanie_pytania_z_tokenem_na_inny_host_idzie_tam_bez_tokenu() -> None:
    answers = newest_on_main(REPOSITORY, "v0.2.0", NEWEST)
    with github_api(answers) as elsewhere:
        moved = {path: Answer(301, headers={"Location": f"{elsewhere.url}{path}"}) for path in answers}
        with github_api(moved) as api:
            newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert newest == GitHubReleases(NEWEST, "v0.2.0")
    assert {asked.authorization for asked in api.asked} == {WITH_TOKEN}
    assert [asked.authorization for asked in elsewhere.asked] == [None, None, None]


def test_przekierowanie_pytania_z_tokenem_na_ten_sam_host_idzie_tam_bez_tokenu() -> None:
    answers = newest_on_main(REPOSITORY, "v0.2.0", NEWEST)
    moved = {path: path.replace(REPOSITORY, "/repositories/1") for path in answers}
    with github_api({}) as api:
        redirects = {path: Answer(301, headers={"Location": f"{api.url}{target}"}) for path, target in moved.items()}
        api.answers = redirects | {moved[path]: answer for path, answer in answers.items()}
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert newest == GitHubReleases(NEWEST, "v0.2.0")
    assert [(asked.path in moved, asked.authorization) for asked in api.asked] == [(True, WITH_TOKEN), (False, None)] * 3


@pytest.mark.parametrize(
    ("refusal", "authorizations"),
    [
        (401, [WITH_TOKEN, None, None, None, WITH_TOKEN, None]),
        (403, [WITH_TOKEN, None, None, None, WITH_TOKEN, None]),
        (404, [WITH_TOKEN, None, WITH_TOKEN, None, WITH_TOKEN, None, WITH_TOKEN, None]),
    ],
    ids=["401", "403", "404"],
)
def test_odmowa_pytania_z_tokenem_daje_odpowiedz_bez_tokenu_i_propozycje_aktualizacji(
    refusal: int, authorizations: list[str | None]
) -> None:
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST), refused_token=refusal) as api:
        freshness = ToolFreshness(
            local=lambda: OLDER,
            since=lambda: None,
            release=lambda: releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN),
            published=lambda: published_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN),
        )
        judgement = freshness.judge()
        published = freshness.published()

    assert offers_update(judgement)
    assert published == (
        PublishedRelease(Release((0, 2, 0), "v0.2.0"), "", datetime(2026, 11, 8, 6, tzinfo=timezone.utc)),
    )
    assert [asked.authorization for asked in api.asked] == authorizations


LIMIT_RESET = datetime(2026, 11, 8, 3, 49, tzinfo=timezone.utc)


LIMIT = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(LIMIT_RESET.timestamp()))}


@pytest.mark.parametrize(("token", "authorizations"), [(None, [None]), (TOKEN, [WITH_TOKEN, None])], ids=["bez-tokenu", "z-tokenem"])
@pytest.mark.parametrize("status", [403, 429])
def test_odmowa_z_powodu_limitu_githuba_mowi_kiedy_limit_sie_odnowi_a_bez_tokenu_nie_jest_ponawiana(
    status: int, token: str | None, authorizations: list[str | None]
) -> None:
    refused = Answer(status, {"message": "API rate limit exceeded"}, LIMIT)
    with github_api({f"{REPOSITORY}/tags?per_page=100": refused}) as api:
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=token)

    assert newest == RateLimited(LIMIT_RESET)
    assert [asked.authorization for asked in api.asked] == authorizations


def test_odmowa_z_tokenem_z_nieczytelna_chwila_odnowienia_limitu_to_odmowa_tokenu_ponowiona_bez_niego() -> None:
    unreadable = Answer(403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "jutro"})
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST), refused_token=unreadable) as api:
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert newest == GitHubReleases(NEWEST, "v0.2.0")
    assert [asked.authorization for asked in api.asked][:2] == [WITH_TOKEN, None]


def test_awaria_githuba_na_pytanie_z_tokenem_to_brak_odpowiedzi_bez_ponowienia_bez_tokenu() -> None:
    failure = Answer(500, {"message": "Server Error"})
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST), refused_token=failure) as api:
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert newest is None
    assert [asked.authorization for asked in api.asked] == [WITH_TOKEN]


@pytest.mark.parametrize(
    "headers",
    [{"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "1793000000"}, {"X-RateLimit-Remaining": "0"}],
    ids=["zostaly-pytania", "bez-chwili-odnowienia"],
)
def test_odmowa_bez_wyczerpanego_limitu_albo_bez_chwili_odnowienia_to_brak_odpowiedzi(headers: dict[str, str]) -> None:
    with github_api({f"{REPOSITORY}/tags?per_page=100": Answer(403, {"message": "Forbidden"}, headers)}) as api:
        assert releases_from(f"{api.url}{REPOSITORY}", timeout_s=30) is None


def test_odmowa_z_trescia_bez_konca_czytana_do_1_mb_a_pytanie_ponowione_bez_tokenu() -> None:
    endless = Answer(404, {"message": "Not Found", "padding": "x" * 65_536}, ending="endless")
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST), refused_token=endless) as api:
        published = published_from(f"{api.url}{REPOSITORY}", timeout_s=5, token=TOKEN)

    assert published is not None
    assert [asked.authorization for asked in api.asked] == [WITH_TOKEN, None]


def test_urwana_odmowa_listy_pr_commitu_to_brak_odpowiedzi_po_ktorym_decyduje_wyszukiwanie_binarne() -> None:
    answers = {
        f"{REPOSITORY}/tags?per_page=100": Answer(body=[{"name": "v0.2.0", "commit": {"sha": NEWEST}}]),
        f"{REPOSITORY}/git/ref/heads/main": Answer(body={"object": {"sha": MAIN}}),
        f"{REPOSITORY}/compare/{NEWEST}...{MAIN}?per_page=1&page=2": Answer(body={"status": "ahead", "ahead_by": 1}),
        f"{REPOSITORY}/commits/{NEWEST}/pulls": Answer(404, {"message": "Not Found"}, ending="cut"),
        f"{REPOSITORY}/compare/{NEWEST}...{MAIN}~1?per_page=1&page=2": Answer(body={"status": "identical", "ahead_by": 0}),
    }
    with github_api(answers) as api:
        assert releases_from(f"{api.url}{REPOSITORY}", timeout_s=30) == GitHubReleases(NEWEST, "v0.2.0")


def test_lista_tagow_urwana_w_trakcie_tresci_to_brak_odpowiedzi_a_nie_wyjatek() -> None:
    cut = Answer(body=[{"name": "v0.2.0", "commit": {"sha": NEWEST}}], ending="cut")
    with github_api({f"{REPOSITORY}/tags?per_page=100": cut}) as api:
        assert releases_from(f"{api.url}{REPOSITORY}", timeout_s=30) is None


@pytest.mark.parametrize(("pages", "complete"), [(10, True), (11, False)], ids=["10-stron", "11-stron"])
def test_lista_tagow_dluzsza_niz_dziesiec_stron_to_brak_odpowiedzi(pages: int, complete: bool) -> None:
    answers = newest_on_main(REPOSITORY, "v0.2.0", NEWEST)
    tags = answers.pop(f"{REPOSITORY}/tags?per_page=100")
    with github_api({}) as api:
        paths = [f"{REPOSITORY}/tags?per_page=100"] + [f"{REPOSITORY}/tags?per_page=100&page={n}" for n in range(2, pages + 1)]
        following = [Answer(body=[], headers={"Link": f'<{api.url}{path}>; rel="next"'}) for path in paths[1:]]
        api.answers = answers | dict(zip(paths, [*following, tags], strict=True))
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30)

    assert newest == (GitHubReleases(NEWEST, "v0.2.0") if complete else None)


def test_token_do_zgloszen_dopisany_po_starcie_idzie_z_nastepnym_pytaniem_o_wydania_i_ich_notki(
    monkeypatch: pytest.MonkeyPatch, prawdziwe_wydania_githuba: Callable[[KeySource, str], AnswerSource]
) -> None:
    monkeypatch.setattr(tool_freshness, "github_releases", prawdziwe_wydania_githuba)
    keys: list[str | None] = [None]
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST)) as api:
        monkeypatch.setattr(tool_freshness, "TOOL_API", f"{api.url}{REPOSITORY}")
        freshness = ToolFreshness.of_system(lambda: keys[-1])
        checks = [(freshness.release(), freshness.published() is not None)]
        keys.append(TOKEN)
        checks.append((freshness.release(), freshness.published() is not None))

    assert checks == [(GitHubReleases(NEWEST, "v0.2.0"), True)] * 2
    assert [asked.authorization for asked in api.asked] == [None] * 4 + [WITH_TOKEN] * 2


def test_narzedzie_bez_commitu_nie_pyta_githuba() -> None:
    asked: list[str] = []

    def release() -> RateLimited:
        asked.append("wydania")
        return RateLimited(LIMIT_RESET)

    freshness = ToolFreshness(local=lambda: None, since=lambda: None, release=release, published=lambda: ())

    assert (freshness.assess(), asked) == (("no_commit", None), [])


def test_odpowiedz_githuba_pamietana_dziesiec_minut_a_brak_odpowiedzi_minute() -> None:
    now = [0.0]
    answers: list[GitHubReleases | None] = [GitHubReleases(NEWEST, "v0.2.0"), None, GitHubReleases(OLDER, "v0.1.0")]
    remembered = RememberedRelease(lambda: answers.pop(0), clock=lambda: now[0])

    readings = []
    for at in (0.0, 599.9, 600.0, 659.9, 660.0):
        now[0] = at
        readings.append(remembered())

    newest, older = GitHubReleases(NEWEST, "v0.2.0"), GitHubReleases(OLDER, "v0.1.0")
    assert readings == [newest, newest, None, None, older]


def _git(root: Path, head: str) -> Path:
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n", encoding="utf-8")
    return git


def test_commit_galezi_klonu(tmp_path: Path) -> None:
    git = _git(tmp_path, "ref: refs/heads/main")
    (git / "refs" / "heads" / "main").write_text(BRANCH + "\n", encoding="utf-8")

    assert tool_commit(tmp_path) == BRANCH


def test_commit_galezi_spakowanej(tmp_path: Path) -> None:
    git = _git(tmp_path, "ref: refs/heads/main")
    (git / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{MAIN} refs/heads/inna\n{BRANCH} refs/heads/main\n",
        encoding="utf-8",
    )

    assert tool_commit(tmp_path) == BRANCH


def test_commit_odlaczonego_head(tmp_path: Path) -> None:
    _git(tmp_path, BRANCH)

    assert tool_commit(tmp_path) == BRANCH


def test_commit_katalogu_roboczego_worktree(tmp_path: Path) -> None:
    clone = tmp_path / "klon"
    git = _git(clone, "ref: refs/heads/main")
    (git / "refs" / "heads" / "zgloszenia").write_text(BRANCH + "\n", encoding="utf-8")
    worktree_git = git / "worktrees" / "drugi"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/zgloszenia\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "drugi"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")

    assert tool_commit(worktree) == BRANCH


@pytest.mark.parametrize(
    "head",
    [None, "ref: refs/heads/brak", "nie-commit"],
    ids=["bez-gita", "galaz-bez-commitu", "uszkodzony-head"],
)
def test_narzedzie_bez_commitu(tmp_path: Path, head: str | None) -> None:
    if head is not None:
        _git(tmp_path, head)

    assert tool_commit(tmp_path) is None
