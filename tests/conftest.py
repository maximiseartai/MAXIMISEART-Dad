from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, NoReturn

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rozliczenia.centrum import report_box, restart_guardian, tool_freshness
from rozliczenia.centrum.tool_update import ToolClone
from rozliczenia.centrum.log import CentrumLog

from tests.fixtures.git_config import hermetic_git
from tests.fixtures.kwarantanna import KWARANTANNA

# Testy importują narzędzia tak, jak skrypt z ``tools/`` widzi je na ``sys.path``: narzędzia agenta, biblioteki i CI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

import niestabilne_testy

_CHECKED_CONTENT_TYPES = ("application/json", "text/event-stream")
# Kod eksploratora przeplotów skilla w procesie pytest wywraca test (docstring pluginu).
pytest_plugins = ["tests.fixtures.eksplorator_w_procesie"]


def pytest_itemcollected(item: pytest.Item) -> None:
    """Test z ``KWARANTANNA`` biegnie jako ``xfail(strict=False)``: jego porażka nie czerwieni CI, a junit ma jego wynik
    z własnością ``kwarantanna``, z której ``tools/plan_ci.py`` zapisuje wyniki testów z kwarantanny zadania."""

    entry = KWARANTANNA.get(item.nodeid)
    if entry is not None:
        reason = f"kwarantanna #{entry.issue} do {entry.do.isoformat()}"
        item.add_marker(pytest.mark.xfail(strict=False, reason=reason))
        item.user_properties.append((niestabilne_testy.WLASNOSC, reason))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Testy ``@pytest.mark.dlugi`` zaczynają kawałki listy, które ``--dist worksteal`` rozdaje workerom na start.

    Worker dostaje ciągły kawałek listy, a inne workery kradną z jego końca, więc długi test w głębi kawałka zaczyna
    się pod koniec przebiegu i jeden worker kończy kilkanaście sekund po pozostałych. Kolejność poza xdist zostaje.
    """

    workers = getattr(config, "workerinput", {}).get("workercount")
    long = [item for item in items if item.get_closest_marker("dlugi")]
    if not workers or not long:
        return
    collected = list(items)
    rest = [item for item in items if not item.get_closest_marker("dlugi")]
    ordered: list[pytest.Item] = []
    remaining = len(items)
    for index in range(workers):
        first = long[index::workers]
        # Rozmiar kawałka jak w WorkStealingScheduling.check_schedule: pozostałe testy po równo na pozostałe workery.
        size = remaining // (workers - index)
        take = max(size - len(first), 0)
        ordered += first + rest[:take]
        rest = rest[take:]
        remaining -= len(first) + take
    items[:] = ordered + rest
    assert sorted(map(id, items)) == sorted(map(id, collected)), (
        f"Hak kolejności xdist zmienił zbiór testów: {len(collected)} zebranych, {len(items)} po zmianie kolejności. "
        "Popraw podział na kawałki w pytest_collection_modifyitems, żeby każdy zebrany test został na liście raz."
    )


@pytest.fixture(autouse=True, scope="session")
def git_bez_konfiguracji_komputera(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Każdy git testów ma tę samą konfigurację na Macu Maksa i w CI, a git ze środowiskiem bez niej wywraca test."""

    with hermetic_git(tmp_path_factory.mktemp("git")):
        yield


@pytest.fixture(autouse=True)
def bez_githuba(monkeypatch: pytest.MonkeyPatch) -> None:
    """Żaden test nie łączy się z GitHubem: Centrum bez podstawionego ``tool_freshness`` kończy Diagnozę odpowiedzią 500."""

    def github_in_test() -> str | None:
        raise AssertionError("Test Centrum sięga do GitHuba; podstaw tool_freshness w create_app.")

    monkeypatch.setattr(tool_freshness, "github_releases", github_in_test)


@pytest.fixture(autouse=True)
def bez_aktualizacji_katalogu_narzedzia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Żaden test nie aktualizuje katalogu narzędzia: Centrum bez podstawionego ``tool_update`` odpowiada 500."""

    def tool_in_test() -> NoReturn:
        raise AssertionError("Test Centrum aktualizuje katalog narzędzia; podstaw tool_update w create_app.")

    monkeypatch.setattr(ToolClone, "of_system", tool_in_test)


@pytest.fixture(autouse=True)
def bez_opiekuna_ponownego_startu_w_tescie_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Centrum testu API bez podstawionego ``guardian`` nie uruchamia prawdziwego opiekuna ponownego startu."""

    def guardian_in_test(*args: object) -> NoReturn:
        raise AssertionError("Test Centrum uruchamia opiekuna ponownego startu; podstaw guardian w create_app.")

    monkeypatch.setattr(restart_guardian, "launch", guardian_in_test)


@pytest.fixture(autouse=True)
def bez_skrzynki_zgloszen_na_githubie(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Żaden test nie łączy się ze Skrzynką Zgłoszeń na GitHubie: podstaw report_box w create_app.

    Wysyłka w tle (Kontrola ilości) łapie każdy wyjątek swojego wątku, więc sam ``AssertionError`` by przepadł:
    każda próba jest zapisana i wywraca test po jego końcu.
    """

    attempts: list[str] = []

    def github_in_test(request: report_box.HttpRequest) -> NoReturn:
        attempts.append(f"{request.method} {request.url}")
        raise AssertionError("Test Centrum łączy się ze Skrzynką Zgłoszeń na GitHubie; podstaw report_box w create_app.")

    monkeypatch.setattr(report_box, "urllib_transport", github_in_test)
    yield
    assert attempts == [], "Test łączył się ze Skrzynką Zgłoszeń na GitHubie: " + ", ".join(attempts)


@pytest.fixture(autouse=True)
def regula_prywatnosci_centrum_rozliczen(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Reguła prywatności z ADR 0004 dla każdego testu Centrum rozliczeń przez HTTP API.

    Każda odpowiedź JSON, każde zdarzenie strumienia i dziennik Centrum aplikacji
    testowej nie mogą zawierać ścieżki z katalogu tymczasowego testów ani tekstu
    ``Traceback``. Wyjątki to ścieżki, które tata sam wskazał w ustawieniach
    (Rejestr zleceń, folder okresów), bo Centrum pokazuje je celowo, oraz pole
    ``input`` odpowiedzi 422, w którym FastAPI odsyła treść samego żądania.
    """

    responses: list[_Response] = []
    log_paths: list[Path] = []
    _record_responses(monkeypatch, responses)
    _record_log_paths(monkeypatch, log_paths)

    yield

    roots = _forms_of(tmp_path_factory.getbasetemp())
    leaks = [
        f"{response.where}: {leak}"
        for response in responses
        for leak in _leaks_in_response(response, roots)
    ]
    leaks += [
        f"dziennik Centrum: {line}"
        for log_path in log_paths
        if log_path.is_file()
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if _leaks_in_text(line, roots)
    ]
    assert leaks == [], "Reguła prywatności Centrum (ADR 0004) złamana:\n" + "\n".join(leaks)


@dataclass(frozen=True)
class _Response:
    """Treść odpowiedzi JSON albo jednego zdarzenia strumienia, tak jak dostaje ją przeglądarka."""

    where: str
    status: int
    body: str


def _record_responses(monkeypatch: pytest.MonkeyPatch, responses: list[_Response]) -> None:
    """Każdy TestClient dostaje aplikację, która zapisuje treść odpowiedzi JSON i zdarzeń SSE."""

    original_init = TestClient.__init__

    def recording_init(self: TestClient, app: ASGIApp, *args: Any, **kwargs: Any) -> None:
        original_init(self, _ResponseRecorder(app, responses), *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", recording_init)


def _record_log_paths(monkeypatch: pytest.MonkeyPatch, log_paths: list[Path]) -> None:
    original_init: Callable[[CentrumLog, Path], None] = CentrumLog.__init__

    def recording_init(self: CentrumLog, path: Path) -> None:
        log_paths.append(path)
        original_init(self, path)

    monkeypatch.setattr(CentrumLog, "__init__", recording_init)


class _ResponseRecorder:
    """Warstwa ASGI między TestClient a Centrum: widzi to samo, co dostaje przeglądarka."""

    def __init__(self, app: ASGIApp, responses: list[_Response]) -> None:
        self.app = app
        self._responses = responses

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        where = f"{scope['method']} {scope['path']}"
        status = 0
        content_type = ""
        body = bytearray()

        async def recording_send(message: Message) -> None:
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"").decode("latin-1")
            elif message["type"] == "http.response.body" and content_type.startswith(_CHECKED_CONTENT_TYPES):
                body.extend(message.get("body", b""))
                # Strumień zdarzeń może nie mieć końca, więc każde zdarzenie trafia do sprawdzenia od razu.
                if not message.get("more_body", False) or body.endswith(b"\n\n"):
                    self._responses.append(_Response(where, status, body.decode("utf-8")))
                    body.clear()
            await send(message)

        await self.app(scope, receive, recording_send)


def _forms_of(root: Path) -> tuple[str, ...]:
    """Ścieżka katalogu tymczasowego w każdej postaci, w jakiej może ją podać system."""

    forms = {str(root), str(root.resolve()), root.as_posix()}
    forms |= {form.removeprefix("/private") for form in forms if form.startswith("/private/")}
    return tuple(forms)


def _leaks_in_response(response: _Response, roots: tuple[str, ...]) -> list[str]:
    lines = response.body.splitlines()
    payloads = [line.removeprefix("data:").strip() for line in lines if line.startswith("data:")]
    echoed_request = response.status == 422
    leaks = []
    for payload in payloads or [response.body]:
        try:
            value = json.loads(payload)
        except ValueError:
            strings = [payload]
        else:
            strings = list(_strings_shown_to_browser(value, echoed_request=echoed_request))
        leaks += [text for text in strings if _leaks_in_text(text, roots)]
    return leaks


def _strings_shown_to_browser(value: object, *, echoed_request: bool) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings_shown_to_browser(item, echoed_request=echoed_request)
    elif isinstance(value, dict):
        chosen_by_tata = set(value) == {"state", "path", "name"} and value["state"] in {"ready", "missing"}
        for key, item in value.items():
            if (chosen_by_tata and key == "path") or (echoed_request and key == "input"):
                continue
            yield from _strings_shown_to_browser(item, echoed_request=echoed_request)


def _leaks_in_text(text: str, roots: tuple[str, ...]) -> bool:
    return "Traceback" in text or any(root in text for root in roots)
