"""Centrum rozliczeń w testach: aplikacja na syntetycznym folderze okresów i skryptowany komputer taty."""

from __future__ import annotations

import itertools
import json
import threading
import time
import weakref
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rozliczenia import efenix_process, intermax_process, preparation_process, settlement_process
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.efenix_run import EfenixWindow
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, REPORT
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.report_box import (
    REPOSITORY,
    CloseReason,
    Closure,
    CommentOutcome,
    Commented,
    Issue,
    IssuesOutcome,
    Label,
    Refused,
    SendOutcome,
    Sent,
    Unreachable,
)
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import GitHubReleases, PublishedRelease, ToolFreshness
from rozliczenia.centrum.tool_update import Release

from tests.fixtures.clock import ManualClock

ROOT = Path(__file__).resolve().parents[2]


CENTRUM = "http://127.0.0.1:47811"
# Syntetyczny commit narzędzia; testy nigdy nie czytają prawdziwego `main` z GitHuba.
TOOL_COMMIT = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
# GitHub odpowiedział, ale nie ma żadnego Wydania na `main`.
NO_RELEASE = "brak-wydania"
# Atrybuty plików Windows: zwykły plik i plik OneDrive „tylko online” (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS).
NORMAL_FILE = 0x80
ONLINE_ONLY_FILE = 0x400000
# Pierwszy numer issue ruchu w tle fałszywej skrzynki; numery Zgłoszeń i Kontroli ilości w testach są mniejsze.
BACKGROUND_NUMBERS = 1001
# Logi Uruchomienia idą do skrzynki po każdym Uruchomieniu; testy innych wysyłek ich nie oglądają.
RUN_LOGS_IN_BACKGROUND: frozenset[Label] = frozenset({"logi-uruchomienia"})
# Najdłuższe czekanie zatrzymania Centrum na koniec jego wątków w tle; tyle, co skrzynka czeka na wysyłkę w tle.
STOP_S = 30.0
# Wątek przejścia kolejki Skrzynki (``Outbox.send_in_background``).
QUEUE_THREAD = "skrzynka-kolejka"
# Wątek Aktualizacji narzędzia (``ToolUpdates.start``); po udanej kończy się, gdy opiekun wystartował i Centrum się zamknęło.
UPDATE_THREAD = "aktualizacja-narzedzia"


@dataclass
class FakePlatform:
    """Akcje systemowe komputera taty zastąpione zapisem wywołań i przygotowanymi odpowiedziami."""

    chosen_files: list[Path | None] = field(default_factory=list)
    chosen_folders: list[Path | None] = field(default_factory=list)
    opened: list[Path] = field(default_factory=list)
    dialog_titles: list[str] = field(default_factory=list)
    failure: Exception | None = None  # awaria systemu przy otwieraniu, np. zablokowany Excel

    def open_path(self, path: Path) -> None:
        if self.failure is not None:
            raise self.failure
        self.opened.append(path)

    def choose_file(self, title: str, filetypes: Sequence[tuple[str, str]]) -> Path | None:
        self.dialog_titles.append(title)
        return self.chosen_files.pop(0)

    def choose_folder(self, title: str) -> Path | None:
        self.dialog_titles.append(title)
        return self.chosen_folders.pop(0)


@dataclass
class FakeIssue:
    """Issue fałszywej skrzynki: etykieta, tytuł i treść, jak je założyło Centrum."""

    number: int
    label: Label
    title: str
    body: str
    comments: list[str] = field(default_factory=list)


@dataclass
class FakeReportBox:
    """Skrzynka Zgłoszeń zastąpiona zapisem założonych issue i przygotowanymi wynikami.

    Bez przygotowanego wyniku (``outcomes``, po jednym na każde zakładane issue) każde
    issue dostaje kolejny numer i jest otwarte, dopóki Maks nie zamknie jego numeru
    (``close``, z powodem); komentarz do issue, którego nie ma, to odmowa jak 404 GitHuba. ``sent`` to Zgłoszenia
    (etykieta ``zgloszenie``), a ``issues_with`` issue innej etykiety. ``search_failure`` to odmowa albo brak
    połączenia przy każdym pytaniu o issue z etykietą, a ``listed`` to etykieta i ``include_closed`` każdego pytania.
    ``search_hold`` to skrzynka, która na pytanie o issue z etykietą odpowiada
    dopiero, gdy test ją puści (``set``), jak GitHub bez sieci; ``searching``
    mówi, że takie pytanie już trwa. ``open_hold`` i ``opening`` robią to samo
    z zakładaniem issue, a ``comment_outcomes`` to przygotowane wyniki komentarzy. ``lost_answers`` to tyle
    następnych zakładanych issue, które skrzynka zakłada, ale odpowiedź się urywa (``Unreachable``), a
    ``lost_comment_answers`` tak samo z następnymi komentarzami.
    ``wait_until`` czeka na wysyłkę w tle.

    Issue etykiet z ``background`` to ruch w tle, którego test nie ogląda (np. Logi Uruchomienia w testach
    Zgłoszeń): skrzynka przyjmuje je jak działający GitHub w ``background_issues``, z numerami od
    ``BACKGROUND_NUMBERS`` (GitHub też nie numeruje issue bez przerw), bez ``keys``, przygotowanych wyników,
    wstrzymań i porażek; jedyny wyjątek to ``background_comment_outcomes``, przygotowane wyniki ich komentarzy.
    """

    outcomes: list[SendOutcome] = field(default_factory=list)
    issues: list[FakeIssue] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    closed: dict[int, Closure] = field(default_factory=dict)
    search_failure: Refused | Unreachable | None = None
    listed: list[tuple[Label, bool]] = field(default_factory=list)
    search_hold: threading.Event | None = None
    searching: threading.Event = field(default_factory=threading.Event)
    open_hold: threading.Event | None = None
    opening: threading.Event = field(default_factory=threading.Event)
    comment_outcomes: list[CommentOutcome] = field(default_factory=list)
    lost_answers: int = 0
    lost_comment_answers: int = 0
    background: frozenset[Label] = frozenset()
    background_issues: list[FakeIssue] = field(default_factory=list)
    background_comment_outcomes: list[CommentOutcome] = field(default_factory=list)
    _changed: threading.Condition = field(default_factory=threading.Condition)

    def wait_until(self, condition: Callable[[FakeReportBox], bool], seconds: float = 30) -> bool:
        """Czeka, aż skrzynka dostanie to, czego test oczekuje (wysyłka w tle); ``False`` po ``seconds``."""

        with self._changed:
            return self._changed.wait_for(lambda: condition(self), seconds)

    @property
    def sent(self) -> list[FakeIssue]:
        return self.issues_with(REPORT.label)

    def issues_with(self, label: Label) -> list[FakeIssue]:
        with self._changed:
            return [issue for issue in self.issues if issue.label == label]

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if label in self.background:
            with self._changed:
                number = BACKGROUND_NUMBERS + len(self.background_issues)
                self.background_issues.append(FakeIssue(number, label, title, body))
                self._changed.notify_all()
            return Sent(number)
        self.opening.set()
        if self.open_hold is not None:
            self.open_hold.wait()
        with self._changed:
            self.keys.append(key)
            outcome = self.outcomes.pop(0) if self.outcomes else Sent(number=len(self.issues) + 1)
            if isinstance(outcome, Sent):
                self.issues.append(FakeIssue(outcome.number, label, title, body))
                if self.lost_answers:
                    self.lost_answers -= 1
                    outcome = Unreachable()
            self._changed.notify_all()
        return outcome

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        with self._changed:
            behind = next((issue for issue in self.background_issues if issue.number == number), None)
            if behind is not None:
                if self.background_comment_outcomes:
                    return self.background_comment_outcomes.pop(0)
                behind.comments.append(body)
                self._changed.notify_all()
                position = len(behind.comments)
                return Commented(position, f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-{position}")
            self.keys.append(key)
            self._changed.notify_all()
            if self.comment_outcomes:
                return self.comment_outcomes.pop(0)
            issue = next((issue for issue in self.issues if issue.number == number), None)
            if issue is None:
                return Refused()
            issue.comments.append(body)
            comment_id = sum(len(issue.comments) for issue in self.issues)
            if self.lost_comment_answers:
                self.lost_comment_answers -= 1
                return Unreachable()
        return Commented(comment_id, f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-{comment_id}")

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if label in self.background:
            with self._changed:
                return tuple(
                    Issue(issue.number, issue.body, self.closed.get(issue.number))
                    for issue in self.background_issues
                    if include_closed or issue.number not in self.closed
                )
        self.listed.append((label, include_closed))
        assert key, "skrzynka pytana bez klucza"
        self.searching.set()
        if self.search_hold is not None:
            self.search_hold.wait()
        if self.search_failure is not None:
            return self.search_failure
        return tuple(
            Issue(issue.number, issue.body, self.closed.get(issue.number))
            for issue in self.issues_with(label)
            if include_closed or issue.number not in self.closed
        )

    def close(self, number: int, reason: CloseReason | None = "completed", at: datetime | None = None) -> None:
        """Maks zamyka issue ``number`` z powodem ``reason`` (``state_reason`` GitHuba) w chwili ``at``."""

        self.closed[number] = Closure(reason, at or datetime.now(timezone.utc))


@dataclass
class FakeGitHub:
    """Commit narzędzia u taty, dzień, od którego narzędzie jest na nim, i najnowsze Wydanie na GitHubie.

    ``release`` to commit najnowszego Wydania na `main`, a ``tag`` jego tag; ``release=None`` to brak sieci,
    ``NO_RELEASE`` to GitHub bez żadnego Wydania. ``published`` to lista GitHub Releases (``None``: brak sieci).
    ``asked`` liczy pytania o najnowsze Wydanie, a ``asked_published`` o listę. Commit narzędzia zawiera tylko taki
    sam commit Wydania. ``wydanie`` to Wydanie, którego tag w klonie wskazuje commit narzędzia.
    """

    tool_commit: str | None = TOOL_COMMIT
    since: date | None = None
    release: str | None = TOOL_COMMIT
    tag: str | None = None
    published: list[PublishedRelease] | None = field(default_factory=list)
    asked: int = 0
    asked_published: int = 0
    wydanie: Release | None = None

    def freshness(self) -> ToolFreshness:
        return ToolFreshness(
            local=lambda: self.tool_commit,
            since=lambda: self.since,
            release=self._release,
            published=self._published,
            wydanie=lambda local: self.wydanie,
        )

    def _release(self) -> GitHubReleases | None:
        self.asked += 1
        if self.release is None:
            return None
        return GitHubReleases(None, None) if self.release == NO_RELEASE else GitHubReleases(self.release, self.tag)

    def _published(self) -> tuple[PublishedRelease, ...] | None:
        self.asked_published += 1
        return None if self.published is None else tuple(self.published)


@dataclass
class FakeOneDrive:
    """Atrybuty plików jak w Windows: pliki z ``online_only`` są tylko w OneDrive w chmurze."""

    online_only: set[Path] = field(default_factory=set)

    def attributes(self, path: Path) -> int:
        return ONLINE_ONLY_FILE if path in self.online_only else NORMAL_FILE

    def cloud_files(self) -> CloudFiles:
        return CloudFiles(read_attributes=self.attributes)


@dataclass(frozen=True)
class MetricsPaths:
    """Pliki metryk procesów w Centrum testu zamiast historii z katalogu narzędzia; Wycena w efenix obok Przebiegu."""

    preparation: Path
    settlement: Path
    intermax: Path

    @property
    def efenix(self) -> Path:
        return self.settlement.with_name("efenix-metrics.jsonl")

    def processes(self) -> Processes:
        return Processes(
            preparation=replace(preparation_process.PROCESS, metrics_path=lambda: self.preparation),
            settlement=replace(settlement_process.PROCESS, metrics_path=lambda: self.settlement),
            efenix=replace(efenix_process.PROCESS, metrics_path=lambda: self.efenix),
            intermax=replace(intermax_process.PROCESS, metrics_path=lambda: self.intermax),
        )


# Numer startu przodka każdego wątku, którego uruchomił wątek testu (pierwszego wątku tej linii).
_LINE_STARTS: weakref.WeakKeyDictionary[threading.Thread, int] = weakref.WeakKeyDictionary()
_STARTS = itertools.count()
_thread_start = threading.Thread.start


def _start_in_line(self: threading.Thread) -> None:
    """Wątek dziedziczy numer startu linii po wątku, który go uruchamia; wątek testu zaczyna nową linię."""

    line = _LINE_STARTS.get(threading.current_thread())
    _LINE_STARTS[self] = next(_STARTS) if line is None else line
    _thread_start(self)


threading.Thread.start = _start_in_line  # type: ignore[method-assign]


def new_line() -> int:
    """Numer, od którego ``threads_since`` liczy wątki, które wątek testu uruchomi od teraz."""

    return next(_STARTS)


def threads_since(since: int, *, named: str | None = None) -> list[threading.Thread]:
    """Żywe wątki z linii, które wątek testu zaczął od ``since``, także uruchomione później przez wątki tych linii.

    ``named``: tylko wątki o tej nazwie.
    """

    return [
        thread
        for thread in threading.enumerate()
        if _LINE_STARTS.get(thread, -1) >= since and named in (None, thread.name)
    ]


def join_threads_since(since: int, timeout_s: float = STOP_S, *, named: str | None = None) -> None:
    """Czeka, aż skończy się każdy wątek z ``threads_since``; wątek żywy po ``timeout_s`` wywraca test z nazwą."""

    deadline = time.monotonic() + timeout_s
    while alive := threads_since(since, named=named):
        left = deadline - time.monotonic()
        assert left > 0, f"Centrum nie zatrzymało się: żyją wątki {', '.join(thread.name for thread in alive)}"
        alive[0].join(left)


class CentrumClient(TestClient):
    """Klient HTTP Centrum w teście, który zatrzymuje Centrum, zanim test przeczyta albo usunie jego pliki.

    Na Windows pliku, który wątek Centrum w tle w tej chwili pisze albo czyta, nie da się otworzyć ani usunąć
    (``PermissionError``), więc test dotyka plików Centrum dopiero po ``stop``. Wątki Centrum to wątki z linii, które
    wątek testu zaczął od ``since``, także uruchomione później przez wątki tej linii. Wątek z linii sprzed ``since``
    należy do Centrum innego testu, nawet gdy powstał po ``since`` (budzik kolejki z ``SYSTEM_CLOCK`` co
    ``RETRY_S`` uruchamia następny). Centrum po ponownym starcie dostaje ``since`` poprzedniego, żeby ``stop``
    czekał też na wątki jego poprzedniej pracy.
    """

    def __init__(self, app: FastAPI, *, since: int | None = None) -> None:
        super().__init__(app, base_url=CENTRUM, headers={"Origin": CENTRUM})
        self.since = new_line() if since is None else since

    def threads(self) -> list[threading.Thread]:
        """Żywe wątki Centrum: serwera i jego pracy w tle."""

        return threads_since(self.since)

    def stop(self, timeout_s: float = STOP_S) -> None:
        """Zamyka serwer (``lifespan``) i czeka, aż skończy się każdy wątek Centrum; drugie ``stop`` nic nie robi.

        Wątek, który nie skończy się w ``timeout_s``, wywraca test z nazwą wątku.
        """

        if self.portal is not None:
            self.__exit__(None, None, None)
        join_threads_since(self.since, timeout_s)


@dataclass
class Centrum:
    client: CentrumClient
    platform: FakePlatform
    settings_path: Path
    metrics: MetricsPaths
    log_path: Path
    report_box: FakeReportBox
    clock: ManualClock


def case_states(client: TestClient, kind: str) -> list[str]:
    """Stany Spraw taty rodzaju ``kind`` (``uwaga``, ``zgloszenie``) w Powiadomieniach.

    Na nie czeka test, a nie na plik stanu: Centrum podaje sprawy pod blokadą, która trzyma też zapis pliku, a na
    Windows plik otwarty przez test w pętli blokuje jego zamianę (``os.replace``) i zapis przepada.
    """

    items = client.get("/api/notifications").json()["items"]
    return [item["state"] for item in items if item["kind"] == kind]


def dad_cases(config: Path, kind: str) -> list[dict[str, Any]]:
    """Sprawy taty rodzaju ``kind`` (``uwaga``, ``zgloszenie``) z pliku stanu u taty; bez pliku żadnych."""

    path = config / DAD_CASES_FILE
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    return [entry for entry in document["sprawy"] if entry["kind"] == kind]


def centrum(tmp_path: Path, *, today: date = date(2026, 10, 19)) -> Centrum:
    """Centrum na syntetycznym folderze; zegar stoi, dopóki test go nie przesunie, więc nie zostawia budzików."""

    platform = FakePlatform()
    clock = ManualClock()
    report_box = FakeReportBox(background=RUN_LOGS_IN_BACKGROUND)
    settings_path = tmp_path / "config" / "centrum-ustawienia.yaml"
    metrics = MetricsPaths(
        preparation=tmp_path / "przygotowanie-metrics.jsonl",
        settlement=tmp_path / "metrics.jsonl",
        intermax=tmp_path / "intermax-metrics.jsonl",
    )
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    log = CentrumLog(log_path)
    app = create_app(
        settings_path=settings_path,
        platform=platform,
        log=log,
        shutdown=Shutdown(log),
        today=lambda: today,
        processes=metrics.processes(),
        tool_freshness=FakeGitHub().freshness(),
        cloud_files=FakeOneDrive().cloud_files(),
        report_box=report_box,
        clock=clock,
        pause=clock.pause,
        # Wycena w efenix w tym Centrum nie dociera do żadnego efenix: pod tym adresem nic nie odpowiada.
        efenix_window=EfenixWindow(
            "http://127.0.0.1:9/index.php",
            tmp_path / "przegladarka-efenix",
            tmp_path / "slad-wyceny-emmetta",
            channel=None,
            headless=True,
            pace=None,
        ),
    )
    client = CentrumClient(app)
    return Centrum(client, platform, settings_path, metrics, log_path, report_box, clock)


def view_timing(**changes: object) -> dict[str, object]:
    """Pomiar zimnego startu Metryk, jaki przeglądarka wysyła po gotowym widoku; ``changes`` podmienia pola."""

    timing: dict[str, object] = {
        "kind": "cold_start",
        "page": "metryki",
        "ready_ms": 415,
        "fcp_ms": 210,
        "skeleton_ms": 120,
        "requests": [
            {"operation": "getSettings", "browser_ms": 12, "server_ms": 3},
            {"operation": "getMetrics", "browser_ms": 48, "server_ms": None},
        ],
    }
    return timing | changes


def without_times(value: object) -> object:
    """Wynik Uruchomienia albo rekord metryk bez czasów i identyfikatorów, które różnią się z każdym Uruchomieniem."""

    if isinstance(value, dict):
        return {
            key: without_times(item)
            for key, item in value.items()
            if not (key == "id" or key.endswith("_ms") or key.endswith("_at") or key in ("timestamp", "value"))
        }
    if isinstance(value, list):
        return [without_times(item) for item in value]
    return value


def run_events(client: TestClient) -> Iterator[dict[str, Any]]:
    """Zdarzenia strumienia SSE Uruchomień procesu, każde jako sparsowany JSON z linii ``data:``."""

    with client.stream("GET", "/api/runs/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line.removeprefix("data: "))


def views_until(client: TestClient, *states: str) -> list[dict[str, Any]]:
    """Widoki bieżącego Uruchomienia ze strumienia, aż do pierwszego w jednym ze stanów ``states``."""

    views = []
    for event in run_events(client):
        views.append(event["view"])
        if event["view"]["state"] in states:
            return views
    raise AssertionError("Strumień skończył się przed oczekiwanym stanem.")


def finished_view(client: TestClient) -> dict[str, Any]:
    return views_until(client, "finished")[-1]


def phase_states(view: dict[str, Any]) -> dict[str, str]:
    return {phase["phase"]: phase["state"] for phase in view["progress"]["phases"]}
