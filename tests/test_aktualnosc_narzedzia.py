"""Źródła Aktualności narzędzia i Powiadomienia o nowej wersji, których HTTP API Centrum nie dosięga, bo w testach są
podstawione.

Lista tagów Wydań i lista GitHub Releases pochodzą z lokalnego serwera HTTP na 127.0.0.1, nigdy z GitHuba, a Token do
Zgłoszeń w tych pytaniach jest wymyślonym napisem.
Commit narzędzia pochodzi z syntetycznych katalogów ``.git``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse

import pytest

from rozliczenia.centrum import tool_freshness, tool_update
from rozliczenia.centrum.github import TOOL_API
from rozliczenia.centrum.tool_freshness import (
    GitHubReleases,
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

from tests.fixtures.proxy_systemu import system_proxy

# Prawdziwe ``github_releases`` z chwili importu: autouse ``bez_githuba`` (``tests/conftest.py``) podmienia je w module.
GITHUB_RELEASES = tool_freshness.github_releases
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
# Commit scalenia PR do `main` tak daleko na linii jak ``FAR_ON_LINE``.
MERGED_FAR = "efefefefefefefefefefefefefefefefefefefef"
NOT_A_COMMIT = "nie-commit"
# Odpowiedź porównania commitu tagu z czubkiem `main` ``MAIN`` albo jego pierwszym rodzicem (``compare``); brak wpisu
# to odmowa GitHuba. ``OLDER`` jest pierwszym rodzicem ``MAIN``.
_STATUS = {
    (OLDER, MAIN): "ahead",
    (OLDER, f"{MAIN}~1"): "identical",
    (NEWEST, MAIN): "identical",
    (OTHER, MAIN): "diverged",
    (OFF_MAIN, MAIN): "behind",
    # Commit gałęzi wciągniętej merge'em: przodek `main`, ale nie jego pierwszego rodzica. Przy ``REFUSED_MIDWAY``
    # GitHub odmawia dopiero porównania z pierwszym rodzicem, czyli w połowie wyszukiwania.
    (MERGED_BRANCH, MAIN): "ahead",
    (MERGED_BRANCH, f"{MAIN}~1"): "behind",
    (REFUSED_MIDWAY, MAIN): "ahead",
    # Porównanie bez liczby commitów i porównanie z czubkiem `main`, który nie jest commitem: GitHub, który by je
    # dał, nie daje pełnej odpowiedzi.
    (UNCOUNTED, MAIN): "identical",
    (NEWEST, NOT_A_COMMIT): "identical",
    # Pierwszy commit repozytorium jest pierwszym rodzicem `main`, a `main` ma jeszcze dwa commity z wciągniętej
    # gałęzi (``ahead_by`` 3): ``MAIN~2`` i dalej nie istnieją (404).
    (FAR_ON_LINE, MAIN): "ahead",
    (MERGED_FAR, MAIN): "ahead",
    # Gałąź wciągnięta merge'em, gdy `main` poszedł już dalej: jego pierwsi rodzice od niej odchodzą („diverged”).
    (MERGED_LATE, MAIN): "ahead",
    (MERGED_LATE, f"{MAIN}~1"): "diverged",
    (MERGED_LATE, f"{MAIN}~2"): "diverged",
    (FIRST_COMMIT, MAIN): "ahead",
    (FIRST_COMMIT, f"{MAIN}~1"): "identical",
}
# Odpowiedzi GitHuba w innym kształcie niż w API: czubek `main` i porównanie (``None``: zerwane połączenie).
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
# ``FAR_ON_LINE`` to ``MAIN~700``, a `main` ma 1000 commitów spoza niego: tydzień zmian z wciągniętymi gałęziami.
_FAR_DEPTH = 700


def _far_status(base: str, head: str) -> str | None:
    if base not in (FAR_ON_LINE, MERGED_FAR) or not head.startswith(f"{MAIN}~"):
        return None
    depth = int(head.removeprefix(f"{MAIN}~"))
    return "ahead" if depth < _FAR_DEPTH else "identical" if depth == _FAR_DEPTH else "behind"
_NOT_FOUND = {(FIRST_COMMIT, f"{MAIN}~2"), (FIRST_COMMIT, f"{MAIN}~3")}


def _tags(*named: tuple[str, str]) -> str:
    return json.dumps([{"name": name, "commit": {"sha": sha, "url": "https://api.github.com/x"}} for name, sha in named])


# Repozytorium (pierwszy człon ścieżki) wybiera listę tagów i jej strony; kolejność jak u GitHuba nie jest
# kolejnością Wydań.
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
}

NOTES = "Plik zbiorczy ma kolumnę z kilometrami.\n\n## Rozwiązane sprawy taty\n\n- Uwaga taty #12: Kilometry\n"


def _release(tag: object, *, body: object = "", published_at: object = "2026-10-20T10:00:00Z", **flags: object) -> object:
    return {"tag_name": tag, "body": body, "published_at": published_at, "draft": False, "prerelease": False} | flags


# Lista GitHub Releases: od najnowszego, z szkicem, wersją przedpremierową, tagiem, który nie jest Wydaniem, i
# wpisami w innym kształcie.
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


# PR-y commitu (``commits/<sha>/pulls``). ``MERGED_FAR`` scalił drugi PR na liście. Uśpiony tag z gałęzi wciągniętej
# merge'em stoi na czubku PR (``head.sha``), który scalił inny commit; commit ``MERGED_BRANCH`` ma też PR, który nie
# czyni go czubkiem `main`, albo odpowiedź w innym kształcie.
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
# Commit scalenia PR do `main`, który nie jest przodkiem czubka `main` (po force-pushu `main` od niego odszedł albo
# się przed niego cofnął).
_MERGED_NOT_IN_MAIN = {"scalony-poza-main": OTHER, "scalony-przed-czubkiem": OFF_MAIN}
for _repository, _commit in _MERGED_NOT_IN_MAIN.items():
    _PAGES[f"/{_repository}/tags?per_page=100"] = (_tags(("v0.1.0", _commit)), None)
    _PAGES[f"/{_repository}/commits/{_commit}/pulls"] = (json.dumps([_pull(_commit)]), None)


# Ścieżki i nagłówki pytań do atrapy GitHuba, w kolejności; ``github`` czyści listy przed testem.
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
            if answer is None:  # połączenie zerwane w trakcie odpowiedzi
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHub)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_najnowsze_wydanie_to_najwyzszy_numer_a_nie_ostatni_tag_alfabetycznie(github: str) -> None:
    assert releases_from(f"{github}/tagi", timeout_s=30) == GitHubReleases(NEWEST, "v0.10.0")


def test_najnowsze_wydanie_ze_wszystkich_stron_listy_tagow(github: str) -> None:
    assert releases_from(f"{github}/strony", timeout_s=30) == GitHubReleases(NEWEST, "v1.0.0")


@pytest.mark.parametrize("token", [None, TOKEN], ids=["bez-tokenu", "z-tokenem"])
def test_aktualnosc_pyta_github_naglowkami_api_rest_z_wersja_api(github: str, token: str | None) -> None:
    # Nagłówki z dokumentacji REST API GitHuba: typ odpowiedzi, wersja API i obowiązkowy User-Agent (bez niego 403).
    expected = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "centrum-rozliczen",
        "Authorization": None if token is None else f"Bearer {token}",
    }

    assert releases_from(f"{github}/tagi", timeout_s=30, token=token) == GitHubReleases(NEWEST, "v0.10.0")
    assert published_from(f"{github}/wydania", timeout_s=30, token=token) is not None

    assert len(_ASKED_HEADERS) >= 2
    assert all({name: headers[name] for name in expected} == expected for headers in _ASKED_HEADERS)


@pytest.mark.parametrize("token", [None, TOKEN], ids=["bez-tokenu", "z-tokenem"])
def test_aktualnosc_laczy_sie_z_githubem_wprost_mimo_proxy_w_ustawieniach_systemu(
    github: str, monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    with system_proxy(monkeypatch) as proxied:
        assert releases_from(f"{github}/tagi", timeout_s=30, token=token) == GitHubReleases(NEWEST, "v0.10.0")
        assert published_from(f"{github}/wydania", timeout_s=30, token=token) is not None

    assert proxied == []


def test_health_centrum_na_tym_komputerze_idzie_wprost_mimo_proxy_w_ustawieniach_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"service": SERVICE, "commit": "a" * 40}).encode()
            self.send_response(200 if self.path == "/api/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        with system_proxy(monkeypatch) as proxied:
            running = running_centrum(server.server_address[1], timeout_s=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert (running, proxied) == (RunningCentrum("a" * 40), [])


def test_sprawdzenia_wydan_i_health_wczytuja_certyfikaty_systemu_najwyzej_raz_na_proces(monkeypatch: pytest.MonkeyPatch) -> None:
    # Na Windows jedno wczytanie to 42–75 ms (sonda #1673): przy każdym pytaniu zjadało limit Diagnozy (#1580), a przy
    # każdym sprawdzeniu health limit czekania launchera na Centrum.
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
            # Atrapa GitHuba odpowiada na /api/health 404, więc Centrum tam nie ma.
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
    assert _comparisons() <= 12  # log2(1001) + 2


def test_aktualnosc_w_centrum_pamieta_linie_main_miedzy_sprawdzeniami(github: str) -> None:
    release = GITHUB_RELEASES(lambda: None, f"{github}/z-galezi")

    assert release() == GitHubReleases(None, None)
    _ASKED.clear()
    assert release() == GitHubReleases(None, None)
    assert _comparisons() == 0


def test_wydanie_ze_scalenia_pr_daleko_na_linii_main_to_cztery_pytania_bez_wzgledu_na_odleglosc(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/daleko-scalone", timeout_s=30, known=known) == GitHubReleases(MERGED_FAR, "v0.1.0")
    assert (len(_ASKED), known) == (4, {MERGED_FAR: True})  # tagi, czubek `main`, porównanie z czubkiem, PR-y commitu


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


# Wyjątek w wątku pytania też kończy się ``None`` (``deadline.within``), ale jako ślad wywołań na stderr Centrum:
# odpowiedź w innym kształcie ma być „nie wiadomo” bez wyjątku.
@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize("repository", [*_ODD_REFS, *_ODD_COMPARES])
def test_czubek_main_albo_porownanie_w_innym_ksztalcie_to_nie_wiadomo(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=30) is None


def test_wyzsze_wydanie_spoza_main_jest_pominiete_a_nizsze_na_main_wybrane_po_jednym_pytaniu_o_czubek_main(github: str) -> None:
    assert releases_from(f"{github}/spoza-main", timeout_s=30) == GitHubReleases(OLDER, "v0.2.0")
    assert _comparisons() >= 3
    assert sum(path.endswith("/git/ref/heads/main") for path in _ASKED) == 1


def test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu() -> None:
    with socket.socket() as silent:  # przyjmuje połączenie i nigdy nie odpowiada
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        started = time.monotonic()

        answer = releases_from(f"http://127.0.0.1:{silent.getsockname()[1]}/tagi", timeout_s=0.3)

        assert (answer, time.monotonic() - started < 1.5) == (None, True)


def test_brak_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # port zwolniony po wyjściu: połączenie zostaje odrzucone

    assert releases_from(f"http://127.0.0.1:{port}/tagi", timeout_s=30) is None


def test_aktualnosc_i_aktualizacja_pytaja_repozytorium_tego_checkoutu_bez_przekierowania() -> None:
    # Pod starym adresem GitHub przekierowuje każde pytanie: 8 zapytań zamiast 4 i „Nie sprawdzono” po 3 s (#536).
    # Aktualizacja przez przekierowanie działa, więc bez tej asercji powrót do starego adresu niczego nie psuje w testach (#540).
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


@pytest.mark.parametrize("repository", ["limit", "strona"], ids=["odmowa", "nie-lista"])
def test_lista_wydan_bez_odpowiedzi_api_to_nie_wiadomo(github: str, repository: str) -> None:
    assert published_from(f"{github}/{repository}", timeout_s=30) is None


def test_lista_wydan_bez_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]

    assert published_from(f"http://127.0.0.1:{port}/wydania", timeout_s=30) is None


REPOSITORY = "/repos/tata/narzedzie"


def test_z_tokenem_kazde_pytanie_o_wydania_do_hosta_api_idzie_z_tokenem_a_strona_z_innego_hosta_bez_niego() -> None:
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST)) as elsewhere:
        next_page = f'<{elsewhere.url}{REPOSITORY}/tags?per_page=100>; rel="next"'
        first_page = {f"{REPOSITORY}/tags?per_page=100": Answer(body=[], headers={"Link": next_page})}
        with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST) | first_page) as api:
            newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)
            published = published_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert (newest, published is not None) == (GitHubReleases(NEWEST, "v0.2.0"), True)
    assert [asked.authorization for asked in api.asked] == [WITH_TOKEN] * 4  # tagi, czubek `main`, porównanie, Releases
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
    """Publiczne repozytorium narzędzia odpowiada także bez tokenu, więc token nie idzie za żadnym przekierowaniem."""

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
        # 404 bywa prawdziwą odpowiedzią wyszukiwania, więc token zostaje dla następnych pytań.
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
    # Każde sprawdzenie pyta z tokenem, a po odmowie ponawia to pytanie bez tokenu.
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


def test_wyczerpany_limit_konta_z_tokenem_daje_odpowiedz_bez_tokenu_i_propozycje_aktualizacji() -> None:
    """Limit konta MAXIMISEART-AI dzielą z Centrum agenci Maksa; limit adresu IP taty to osobna pula."""

    limited = Answer(403, {"message": "API rate limit exceeded"}, LIMIT)
    with github_api(newest_on_main(REPOSITORY, "v0.2.0", NEWEST), refused_token=limited) as api:
        newest = releases_from(f"{api.url}{REPOSITORY}", timeout_s=30, token=TOKEN)

    assert newest == GitHubReleases(NEWEST, "v0.2.0")
    assert [asked.authorization for asked in api.asked][:2] == [WITH_TOKEN, None]
    assert WITH_TOKEN not in [asked.authorization for asked in api.asked][1:]


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


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_odpowiedz_urwana_w_trakcie_tresci_to_brak_odpowiedzi_a_nie_wyjatek() -> None:
    """Odmowa listy PR-ów commitu (``commits/<sha>/pulls``) to brak odpowiedzi, po którym decyduje wyszukiwanie
    binarne; urwana treść tej odmowy też."""

    answers = {
        f"{REPOSITORY}/tags?per_page=100": Answer(body=[{"name": "v0.2.0", "commit": {"sha": NEWEST}}]),
        f"{REPOSITORY}/git/ref/heads/main": Answer(body={"object": {"sha": MAIN}}),
        f"{REPOSITORY}/compare/{NEWEST}...{MAIN}?per_page=1&page=2": Answer(body={"status": "ahead", "ahead_by": 1}),
        f"{REPOSITORY}/commits/{NEWEST}/pulls": Answer(404, {"message": "Not Found"}, ending="cut"),
        f"{REPOSITORY}/compare/{NEWEST}...{MAIN}~1?per_page=1&page=2": Answer(body={"status": "identical", "ahead_by": 0}),
    }
    with github_api(answers) as api:
        assert releases_from(f"{api.url}{REPOSITORY}", timeout_s=30) == GitHubReleases(NEWEST, "v0.2.0")


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
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
