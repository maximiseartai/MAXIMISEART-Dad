"""Centrum rozliczeń w testach: aplikacja na syntetycznym folderze okresów i skryptowany komputer taty."""

from __future__ import annotations

import enum
import imaplib
import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time as day_time, timezone
from pathlib import Path
from typing import Any, Final, Self, TypeVar

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rozliczenia import tool_files
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.case_delivery import UNSENT_DIRECTORY
from rozliczenia.centrum.catalog import CATALOG, Catalog
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.efenix_chrome import EfenixWindow
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, REPORT
from rozliczenia.centrum.keyed_box import REPORT_KEY_FILE
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import LAST_STARTED_FILE
from rozliczenia.centrum.outbox import QUEUE_DIRECTORY
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.report_reminders import ReminderRhythm
from rozliczenia.centrum.report_box import (
    REPOSITORY,
    ArchiveOutcome,
    CloseReason,
    Closure,
    Comment,
    CommentOutcome,
    CommentsOutcome,
    Commented,
    IssuesOutcome,
    Label,
    OpenArchiveOutcome,
    Refused,
    RemoveOutcome,
    ReportBox,
    SendOutcome,
    Sent,
    Unreachable,
    UploadOutcome,
)
from rozliczenia.centrum.reports import SEARCH_DEADLINE_S
from rozliczenia.centrum.run_logs import RUN_LOGS_DIRECTORY
from rozliczenia.centrum.server import after_start
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.proposal import ReleaseChange
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.tool_freshness import GitHubReleases, PublishedRelease, RateLimited, ReleaseAnswer, ToolFreshness
from rozliczenia.centrum.tool_update import Release, ToolClone
from rozliczenia.centrum.tool_updates import GuardianLauncher
from rozliczenia.efenix_pace import Pace
from rozliczenia.intermax_copies import default_directory as default_intermax_copies
from rozliczenia.intermax_replace import LOCAL_DISK, Disk
from rozliczenia.run_context import TemplateCheck, check_on_disk
from rozliczenia.workbook_files import ByteSource, file_bytes
from rozliczenia.worker_report_inbox import ImapConnect, ReminderMailbox, WorkerReportInbox
from rozliczenia.centrum.settings.workers import WORKERS_FILE

from tests.fixtures.clock import ManualClock
from tests.fixtures.linie_watkow import new_line, stop_after_test, threads_since
from atrapy.skrzynka import Archives, BoxArchive, BoxIssue, Issues
from atrapy.skrzynka_raportow import FakeInbox, FakeMailbox

ROOT = Path(__file__).resolve().parents[2]


CENTRUM = "http://127.0.0.1:47811"
# Dzień i chwila u taty w Centrum testu, które nie podaje własnych.
TODAY = date(2026, 10, 19)
NOW = datetime.combine(TODAY, day_time(12)).astimezone()
# Lista zleceń okna efenix Centrum testu: pod tym adresem nic nie odpowiada, więc Wycena nie dociera do żadnego efenix.
NO_EFENIX = "http://127.0.0.1:9/index.php"
# Syntetyczny Token do Zgłoszeń, który Maks wpisuje w pliku ``REPORT_KEY_FILE`` obok Ustawień taty.
REPORT_KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
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
class FakeReportBox:
    """Skrzynka Zgłoszeń zastąpiona stanem atrap (``atrapy.skrzynka``: reguły GitHuba) i przygotowanymi wynikami.

    Bez przygotowanego wyniku (``outcomes``, po jednym na każde zakładane issue) każde
    issue dostaje kolejny numer i jest otwarte, dopóki Maks nie zamknie jego numeru
    (``close``, z powodem); komentarz do issue, którego nie ma, to odmowa jak 404 GitHuba. ``issues`` to issue po
    kolei, ``sent`` to Zgłoszenia (etykieta ``zgloszenie``), a ``issues_with`` issue innej etykiety.
    ``search_failure`` to odmowa albo brak
    połączenia przy każdym pytaniu o issue z etykietą, a ``listed`` to etykieta i ``include_closed`` każdego pytania.
    ``search_hold`` to skrzynka, która na pytanie o issue z etykietą odpowiada
    dopiero, gdy test ją puści (``set``), jak GitHub bez sieci; ``searching``
    mówi, że takie pytanie już trwa. ``open_hold`` i ``opening`` robią to samo
    z zakładaniem issue, a ``comment_outcomes`` to przygotowane wyniki komentarzy. ``lost_answers`` to tyle
    następnych zakładanych issue, które skrzynka zakłada, ale odpowiedź się urywa (``Unreachable``), a
    ``lost_comment_answers`` tak samo z następnymi komentarzami. ``after_comment`` biegnie, gdy skrzynka przyjęła
    komentarz, przed odpowiedzią. ``edited`` to identyfikator każdego poprawionego komentarza po kolei, a
    ``lost_edit_answers`` to numery tych poprawek (od 1), które skrzynka przyjmuje, ale odpowiedź się urywa.
    ``written`` to identyfikator i tekst każdego przyjętego komentarza i każdej poprawki po kolei.
    ``wait_until`` czeka na wysyłkę w tle. ``list_lag`` to lista issue, która nie widzi nowego issue, dopóki test jej
    nie puści (``list_caught_up``), jak lista GitHuba, która nadąża za nowym issue po kilku sekundach (#879); tak samo
    lista Archiwów (GitHub Releases) i ich plików, która nadąża za nowym Archiwum (``verify-github-skrzynki``, #887).

    ``archives`` to Archiwa okresów (GitHub Release) z plikami. ``archive_failure`` to odmowa albo brak sieci
    przy każdym kroku Archiwum (np. Token do Zgłoszeń bez uprawnienia do zapisu treści repozytorium), a
    ``archive_requests`` liczy kroki Archiwum, które doszły do skrzynki, także te z odmową.

    Issue etykiet z ``background`` to ruch w tle, którego test nie ogląda (np. Logi Uruchomienia w testach
    Zgłoszeń): skrzynka przyjmuje je jak działający GitHub w ``background_issues``, z numerami od
    ``BACKGROUND_NUMBERS`` (GitHub też nie numeruje issue bez przerw), bez ``keys``, przygotowanych wyników,
    wstrzymań i porażek; jedyny wyjątek to ``background_comment_outcomes``, przygotowane wyniki ich komentarzy.
    """

    outcomes: list[SendOutcome] = field(default_factory=list)
    issues: list[BoxIssue] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    search_failure: Refused | Unreachable | None = None
    listed: list[tuple[Label, bool]] = field(default_factory=list)
    search_hold: threading.Event | None = None
    searching: threading.Event = field(default_factory=threading.Event)
    open_hold: threading.Event | None = None
    opening: threading.Event = field(default_factory=threading.Event)
    comment_outcomes: list[CommentOutcome] = field(default_factory=list)
    lost_answers: int = 0
    lost_comment_answers: int = 0
    after_comment: Callable[[], None] = lambda: None
    edited: list[int] = field(default_factory=list)
    lost_edit_answers: frozenset[int] = frozenset()
    written: list[tuple[int, str]] = field(default_factory=list)
    background: frozenset[Label] = frozenset()
    background_issues: list[BoxIssue] = field(default_factory=list)
    background_comment_outcomes: list[CommentOutcome] = field(default_factory=list)
    archives: list[BoxArchive] = field(default_factory=list)
    archive_failure: Refused | Unreachable | None = None
    archive_requests: int = 0
    list_lag: bool = False
    _box: Issues = field(init=False)
    _background_box: Issues = field(init=False)
    _archive_box: Archives = field(init=False)
    _changed: threading.Condition = field(default_factory=threading.Condition)

    def __post_init__(self) -> None:
        self._box = Issues(self.issues, lag=self.list_lag)
        self._background_box = Issues(
            self.background_issues, first_number=BACKGROUND_NUMBERS, comment_base=BACKGROUND_NUMBERS
        )
        self._archive_box = Archives(self.archives, lag=self.list_lag)

    def wait_until(self, condition: Callable[[FakeReportBox], bool], seconds: float = 30) -> bool:
        """Czeka, aż skrzynka dostanie to, czego test oczekuje (wysyłka w tle); ``False`` po ``seconds``."""

        with self._changed:
            return self._changed.wait_for(lambda: condition(self), seconds)

    @property
    def sent(self) -> list[BoxIssue]:
        return self.issues_with(REPORT.label)

    def issues_with(self, label: Label) -> list[BoxIssue]:
        with self._changed:
            return [issue for issue in self.issues if issue.label == label]

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        if label in self.background:
            with self._changed:
                opened = self._background_box.open(label, title, body)
                self._changed.notify_all()
            return Sent(opened.number)
        self.opening.set()
        if self.open_hold is not None:
            self.open_hold.wait()
        with self._changed:
            self.keys.append(key)
            outcome = self.outcomes.pop(0) if self.outcomes else None
            if outcome is None or isinstance(outcome, Sent):
                outcome = Sent(self._box.open(label, title, body, None if outcome is None else outcome.number).number)
                if self.lost_answers:
                    self.lost_answers -= 1
                    outcome = Unreachable()
            self._changed.notify_all()
        return outcome

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        with self._changed:
            if self._background_box.find(number) is not None:
                if self.background_comment_outcomes:
                    return self.background_comment_outcomes.pop(0)
                behind = self._background_box.comment(number, body)
                assert not isinstance(behind, Refused)
                self._changed.notify_all()
                issue, comment_id = behind
                return Commented(comment_id, self._url_of(issue, comment_id))
            self.keys.append(key)
            self._changed.notify_all()
            if self.comment_outcomes:
                return self.comment_outcomes.pop(0)
            found = self._box.comment(number, body)
            if isinstance(found, Refused):
                return found
            issue, comment_id = found
            self.written.append((comment_id, body))
            lost = self.lost_comment_answers > 0
            self.lost_comment_answers -= lost
        self.after_comment()
        return Unreachable() if lost else Commented(comment_id, self._url_of(issue, comment_id))

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        with self._changed:
            found = self._box.comments(number)
            if isinstance(found, Refused):
                found = self._background_box.comments(number)
            if isinstance(found, Refused):
                return found
            return tuple(
                Comment(comment_id, self._url_of(found, comment_id), text)
                for comment_id, text in zip(found.comment_ids, found.comment_texts, strict=True)
            )

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        with self._changed:
            found = self._box.edit_comment(comment_id, body)
            if isinstance(found, Refused):
                found = self._background_box.edit_comment(comment_id, body)
            if isinstance(found, Refused):
                return found
            self.edited.append(comment_id)
            self.written.append((comment_id, body))
            self._changed.notify_all()
            if len(self.edited) in self.lost_edit_answers:
                return Unreachable()
            return Commented(comment_id, self._url_of(found, comment_id))

    def _url_of(self, issue: BoxIssue, comment_id: int) -> str:
        """Adres komentarza: w ruchu w tle z jego miejscem w issue, inaczej z identyfikatorem."""

        behind = issue in self.background_issues
        return _comment_url(issue.number, issue.position(comment_id) if behind else comment_id)

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if label in self.background:
            with self._changed:
                return self._background_box.listed(label, include_closed=include_closed)
        self.listed.append((label, include_closed))
        assert key, "skrzynka pytana bez klucza"
        self.searching.set()
        if self.search_hold is not None:
            self.search_hold.wait()
        if self.search_failure is not None:
            return self.search_failure
        with self._changed:
            return self._box.listed(label, include_closed=include_closed)

    def list_caught_up(self) -> None:
        """Lista issue i lista Archiwów nadążają: widzą każde issue i Archiwum, które skrzynka założyła."""

        with self._changed:
            self._box.caught_up()
            self._archive_box.caught_up()

    def close(self, number: int, reason: CloseReason | None = "completed", at: datetime | None = None) -> None:
        """Maks zamyka issue ``number`` z powodem ``reason`` (``state_reason`` GitHuba) w chwili ``at``."""

        with self._changed:
            issue = self._box.find(number) or self._background_box.find(number)
            assert issue is not None, f"Maks zamyka issue {number}, którego skrzynka nie ma"
            issue.closure = Closure(reason, at or datetime.now(timezone.utc))

    def archived(self, tag: str) -> dict[str, bytes]:
        """Pliki Archiwum z tagiem ``tag`` po nazwie, rozpakowane bajt w bajt; bez takiego Archiwum pusto."""

        with self._changed:
            return {asset.name: asset.unpacked for archive in self.archives if archive.tag == tag for asset in archive.assets}

    def archive(self, tag: str, *, key: str) -> ArchiveOutcome:
        with self._changed:
            self.archive_requests += 1
            if self.archive_failure is not None:
                return self.archive_failure
            return self._archive_box.archive(tag)

    def open_archive(self, tag: str, title: str, description: str, *, key: str) -> OpenArchiveOutcome:
        with self._changed:
            self.archive_requests += 1
            if self.archive_failure is not None:
                return self.archive_failure
            outcome = self._archive_box.open_archive(tag, title, description)
            self._changed.notify_all()
            return outcome

    def upload(self, archive_id: int, name: str, label: str, data: bytes, *, key: str) -> UploadOutcome:
        with self._changed:
            self.archive_requests += 1
            if self.archive_failure is not None:
                return self.archive_failure
            outcome = self._archive_box.upload(archive_id, name, label, data)
            self._changed.notify_all()
            return outcome

    def remove(self, asset_id: int, *, key: str) -> RemoveOutcome:
        with self._changed:
            self.archive_requests += 1
            if self.archive_failure is not None:
                return self.archive_failure
            outcome = self._archive_box.remove(asset_id)
            self._changed.notify_all()
            return outcome


def _comment_url(number: int, comment: int) -> str:
    return f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-{comment}"


@dataclass
class FakeGitHub:
    """Commit narzędzia u taty, dzień, od którego narzędzie jest na nim, i najnowsze Wydanie na GitHubie.

    ``release`` to commit najnowszego Wydania na `main`, a ``tag`` jego tag; ``release=None`` to brak sieci,
    ``NO_RELEASE`` to GitHub bez żadnego Wydania, a ``limited`` odmowa z powodu limitu GitHuba do tej chwili. ``published`` to lista GitHub Releases (``None``: brak sieci).
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
    limited: datetime | None = None

    def freshness(self) -> ToolFreshness:
        return ToolFreshness(
            local=lambda: self.tool_commit,
            since=lambda: self.since,
            release=self._release,
            published=self._published,
            wydanie=lambda local: self.wydanie,
        )

    def _release(self) -> ReleaseAnswer:
        self.asked += 1
        if self.limited is not None:
            return RateLimited(self.limited)
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
    """Pliki metryk procesów w Centrum testu zamiast historii z katalogu narzędzia."""

    preparation: Path
    settlement: Path
    efenix: Path
    intermax: Path
    report_entering: Path

    def catalog(self) -> Catalog:
        return CATALOG.with_metrics(
            {
                "preparation": self.preparation,
                "settlement": self.settlement,
                "efenix": self.efenix,
                "intermax": self.intermax,
                "report_entering": self.report_entering,
            }
        )


@dataclass(frozen=True)
class ToolDirectory:
    """Katalog narzędzia Centrum testu w ``root``: każdy plik tam, gdzie ``tool_files`` kładzie go w katalogu narzędzia."""

    root: Path

    def _moved(self, path: Path) -> Path:
        return self.root / path.relative_to(tool_files.TOOL_ROOT)

    @property
    def config(self) -> Path:
        """Folder ``config``: Ustawienia Centrum, Wzorce, Token do Zgłoszeń i pliki stanu."""

        return tool_files.config_dir(self.root)

    @property
    def settings(self) -> Path:
        return self.config / SETTINGS_FILE

    @property
    def report_key(self) -> Path:
        return self.config / REPORT_KEY_FILE

    @property
    def queue(self) -> Path:
        """Kolejka Skrzynki Zgłoszeń: pliki, które czekają na wysłanie."""

        return self.config / UNSENT_DIRECTORY / QUEUE_DIRECTORY

    @property
    def log_path(self) -> Path:
        """Dziennik Centrum w katalogu Logów."""

        return self._moved(tool_files.LOG_PATH)

    @property
    def run_logs(self) -> Path:
        return self.log_path.parent / RUN_LOGS_DIRECTORY

    @property
    def last_started(self) -> Path:
        return self.log_path.parent / LAST_STARTED_FILE

    @property
    def configuration(self) -> ConfigurationFiles:
        return ConfigurationFiles(
            internal_template=self._moved(tool_files.INTERNAL_TEMPLATE),
            collective_template=self._moved(tool_files.COLLECTIVE_TEMPLATE),
            worker_template=self._moved(tool_files.WORKER_TEMPLATE),
        )

    @property
    def worker_list(self) -> Path:
        """Lista Wykonawców w Ustawieniach Centrum."""

        return self.config / WORKERS_FILE

    @property
    def metrics(self) -> MetricsPaths:
        return MetricsPaths(
            preparation=self._moved(tool_files.PREPARATION_METRICS),
            settlement=self._moved(tool_files.SETTLEMENT_METRICS),
            efenix=self._moved(tool_files.EFENIX_METRICS),
            intermax=self._moved(tool_files.INTERMAX_METRICS),
            report_entering=self._moved(tool_files.REPORT_ENTERING_METRICS),
        )

    @property
    def intermax_copies(self) -> Path:
        return self._moved(default_intermax_copies())


def write_report_key(tool: ToolDirectory, key: str = REPORT_KEY) -> Path:
    """Token do Zgłoszeń w lokalnym pliku obok Ustawień taty, jak go wpisuje Maks; zwraca ten plik."""

    tool.config.mkdir(parents=True, exist_ok=True)
    tool.report_key.write_text(key + "\n", encoding="utf-8")
    return tool.report_key


def remove_report_key(client: CentrumClient, tool: ToolDirectory) -> None:
    """Maks zabiera Token do Zgłoszeń działającemu Centrum: usuwa jego plik, gdy wątki Centrum w tle skończyły pracę.

    Pytania skrzynki, które Diagnoza i Kolejka wysyłki zostawiają w tle po odpowiedzi API, czytają ten plik, a na Windows
    pliku, który wątek w tej chwili czyta, nie da się usunąć (``PermissionError``, #1064).
    """

    join_threads_since(client.since)
    tool.report_key.unlink()


def efenix_window(
    tool: ToolDirectory, url: str = NO_EFENIX, *, arguments: tuple[str, ...] = (), pace: Pace | None = None
) -> EfenixWindow:
    """Okno efenix Wyceny w efenix w Chromium Playwrighta bez okna, z profilem w katalogu narzędzia testu.

    ``url`` to lista zleceń: domyślnie adres, pod którym nic nie odpowiada, a w testach Wyceny adres Atrapy efenix,
    nigdy efenix.pl; ``arguments`` to dodatkowe argumenty przeglądarki, a ``pace`` tempo ludzkie, domyślnie wyłączone.
    """

    return EfenixWindow(url, tool.root / "przegladarka-efenix", channel=None, headless=True, arguments=arguments, pace=pace)


class Fake(enum.Enum):
    """Parametr ``centrum_app`` pominięty przez test: Centrum dostaje podróbkę testu."""

    FAKE = "podróbka testu"


FAKE = Fake.FAKE
T = TypeVar("T")


def _or_fake(value: T | None | Fake, fake: Callable[[], T]) -> T | None:
    return fake() if isinstance(value, Fake) else value


def centrum_app(
    tool: ToolDirectory,
    *,
    platform: Platform | None = None,
    log: CentrumLog | None = None,
    shutdown: Shutdown | None = None,
    today: date = TODAY,
    now: Callable[[], datetime] = lambda: NOW,
    catalog: Catalog | Fake = FAKE,
    configuration_files: ConfigurationFiles | None | Fake = FAKE,
    tool_freshness: ToolFreshness | None | Fake = FAKE,
    cloud_files: CloudFiles | None | Fake = FAKE,
    report_box: ReportBox | None | Fake = FAKE,
    clock: Clock | None = None,
    pause: Callable[[float], None] | None = None,
    report_search_deadline_s: float = SEARCH_DEADLINE_S,
    tool_update: ToolClone | None = None,
    guardian: GuardianLauncher | None = None,
    source: ByteSource = file_bytes,
    template_check: TemplateCheck = check_on_disk,
    intermax_copies: Path | None | Fake = FAKE,
    intermax_disk: Disk = LOCAL_DISK,
    window: EfenixWindow | None | Fake = FAKE,
    inbox_connect: ImapConnect | Fake = FAKE,
    worker_report_inbox: WorkerReportInbox | Fake = FAKE,
    reminder_mailbox: ReminderMailbox | Fake = FAKE,
    reminder_rhythm: ReminderRhythm | Fake = FAKE,
    release_changes: tuple[ReleaseChange[Any], ...] = (),
) -> FastAPI:
    """Jedyna aplikacja Centrum w testach: na plikach katalogu narzędzia ``tool`` i z podróbkami świata taty.

    Parametr pominięty daje podróbkę testu, nigdy domyślną wartość produkcyjną ``create_app``: komputer taty
    (``FakePlatform``), metryki i Konfiguracja w ``tool``, GitHub (``FakeGitHub``), OneDrive (``FakeOneDrive``),
    skrzynka Zgłoszeń z Logami Uruchomienia w tle, zegar, który stoi (``ManualClock``, a jego ``pause`` tylko
    przesuwa czas), dzień ``TODAY`` i chwila ``NOW``, Kopie INTERMAX w ``tool``, okno efenix pod martwym adresem i
    Skrzynka raportów bez maili (``FakeInbox``), skrzynka raportów bez sieci przy próbie logowania po zmianie hasła
    (``inbox_connect``), skrzynka Przypomnień o raporcie bez maili (``FakeMailbox``) i rytm przypomnień, który
    sprawdza tylko na ``HandRhythm.tick`` testu, a Wydanie bez zmian Ustawień Centrum (produkcyjna lista
    ``RELEASE_CHANGES`` tylko w teście, który ją podaje); prawdziwego Gmaila test nie dostaje nigdy.
    ``None`` daje domyślną wartość produkcyjną tylko testowi, który ją sprawdza (np. Kopie INTERMAX w folderze
    narzędzia albo prawdziwy odczyt atrybutów OneDrive). Bez ``tool_update`` i ``guardian`` Aktualizacja narzędzia i
    opiekun ponownego startu wywracają test (``tests/conftest.py``).
    """

    log = log or CentrumLog(tool.log_path)
    if clock is None:
        clock = ManualClock()
    if pause is None:
        assert isinstance(clock, ManualClock), "Zegar inny niż ManualClock potrzebuje własnego pause."
        pause = clock.pause
    return create_app(
        config=tool.config,
        platform=platform or FakePlatform(),
        log=log,
        shutdown=shutdown or Shutdown(log),
        today=lambda: today,
        catalog=tool.metrics.catalog() if isinstance(catalog, Fake) else catalog,
        configuration_files=_or_fake(configuration_files, lambda: tool.configuration),
        tool_freshness=_or_fake(tool_freshness, lambda: FakeGitHub().freshness()),
        cloud_files=_or_fake(cloud_files, lambda: FakeOneDrive().cloud_files()),
        report_box=_or_fake(report_box, lambda: FakeReportBox(background=RUN_LOGS_IN_BACKGROUND)),
        clock=clock,
        pause=pause,
        report_search_deadline_s=report_search_deadline_s,
        tool_update=tool_update,
        guardian=guardian,
        source=source,
        template_check=template_check,
        intermax_copies=_or_fake(intermax_copies, lambda: tool.intermax_copies),
        intermax_disk=intermax_disk,
        now=now,
        efenix_window=_or_fake(window, lambda: efenix_window(tool)),
        inbox_connect=_no_network if isinstance(inbox_connect, Fake) else inbox_connect,
        worker_report_inbox=FakeInbox() if isinstance(worker_report_inbox, Fake) else worker_report_inbox,
        reminder_mailbox=FakeMailbox() if isinstance(reminder_mailbox, Fake) else reminder_mailbox,
        reminder_rhythm=HandRhythm() if isinstance(reminder_rhythm, Fake) else reminder_rhythm,
        release_changes=release_changes,
    )


def _no_network() -> imaplib.IMAP4:
    raise ConnectionRefusedError("test bez skrzynki raportów: podstaw inbox_connect z AtrapaImap")


@dataclass
class HandRhythm:
    """Rytm Przypomnień o raporcie w teście: sprawdzenie biegnie tylko w ``tick``, w wątku testu, po starcie Centrum."""

    check: Callable[[], None] | None = None

    def start(self, check: Callable[[], None]) -> None:
        self.check = check

    def stop(self) -> None:
        self.check = None

    def tick(self) -> None:
        assert self.check is not None, "Rytm przypomnień tyka dopiero po starcie Centrum (CentrumClient.start)."
        self.check()


def join_threads_since(since: int, timeout_s: float = STOP_S, *, named: str | None = None) -> None:
    """Czeka, aż skończy się każdy wątek z ``threads_since``; wątek żywy po ``timeout_s`` wywraca test z nazwą."""

    deadline = time.monotonic() + timeout_s
    while alive := threads_since(since, named=named):
        left = deadline - time.monotonic()
        assert left > 0, f"Centrum nie zatrzymało się: żyją wątki {', '.join(thread.name for thread in alive)}"
        alive[0].join(left)


class CentrumClient(TestClient):
    """Klient HTTP Centrum w teście, który zatrzymuje Centrum, zanim test przeczyta albo usunie jego pliki.

    Po teście ``tests/conftest.py`` zatrzymuje każdego klienta, którego test nie zatrzymał (``stop_after_test``).

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
        stop_after_test(self.stop)

    def threads(self) -> list[threading.Thread]:
        """Żywe wątki Centrum: serwera i jego pracy w tle."""

        return threads_since(self.since)

    def __enter__(self) -> Self:
        """Start serwera jak u taty: ``lifespan``, a po nim krok po starcie (``server.after_start``), jak w ``serve`` po
        wpisie ``start``."""

        entered = super().__enter__()
        after_start(self.app_state)
        return entered

    def start(self) -> None:
        """Start serwera jak u taty (``__enter__``): Kolejka wysyłki wznawia wysyłki, a po niej idą wersje zastępcze z
        dzienników Wyceny w efenix. Bez niego klient tylko obsługuje zapytania aplikacji."""

        self.__enter__()

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
    tool: ToolDirectory
    report_box: FakeReportBox
    clock: ManualClock

    @property
    def settings_path(self) -> Path:
        return self.tool.settings

    @property
    def metrics(self) -> MetricsPaths:
        return self.tool.metrics

    @property
    def log_path(self) -> Path:
        return self.tool.log_path


# Stany Spraw taty w Powiadomieniach i stany wysyłki w odpowiedzi na „Wyślij” (``SendState`` kontraktu).
SENT: Final = {"state": "sent"}
QUEUED_FOR_INTERNET: Final = {"state": "queued", "waits_for": "internet"}
QUEUED_FOR_KEY: Final = {"state": "queued", "waits_for": "key"}
REJECTED: Final = {"state": "rejected"}
RESOLVED: Final = {"state": "resolved"}
READ_BY_MAKS: Final = {"state": "read"}


def case_states(client: TestClient, kind: str) -> list[dict[str, str]]:
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


def centrum(tmp_path: Path, *, today: date = TODAY) -> Centrum:
    """Centrum na syntetycznym folderze; zegar stoi, dopóki test go nie przesunie, więc nie zostawia budzików."""

    tool = ToolDirectory(tmp_path)
    platform = FakePlatform()
    clock = ManualClock()
    report_box = FakeReportBox(background=RUN_LOGS_IN_BACKGROUND)
    app = centrum_app(tool, platform=platform, today=today, report_box=report_box, clock=clock)
    return Centrum(CentrumClient(app), platform, tool, report_box, clock)


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


