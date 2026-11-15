"""Aplikacja HTTP Centrum rozliczeń: API pod ``/api`` i zbudowany frontend pod ``/``.

Każda grupa zasobów ma własny router; ``create_app`` składa je i zakłada straż HTTP (``http_guard``): nagłówki ``Host``
i ``Origin`` (ADR 0004), odmowy (``Refusal``), folder okresów, którego nie da się odczytać, i nieoczekiwany wyjątek jako
bezpieczne odpowiedzi ``Problem`` oraz czas obsługi każdej odpowiedzi API w ``Server-Timing`` (``timing``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
import threading
import time
import uuid

from fastapi import Depends, FastAPI, Response
from fastapi.staticfiles import StaticFiles

from rozliczenia.centrum.catalog import CATALOG, Catalog
from rozliczenia.centrum.clock import SYSTEM_CLOCK, Clock
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.configuration_router import CONFIGURATION_WAIT_S, configuration_router
from rozliczenia.centrum.case_delivery import case_outbox
from rozliczenia.centrum.contract.centrum import Health
from rozliczenia.centrum.dad_action_journal import DadActionJournal
from rozliczenia.centrum.dad_cases import DadCases
from rozliczenia.centrum.dad_notes import dad_notes_router
from rozliczenia.centrum.diagnosis import Surroundings, diagnose, files_of_process
from rozliczenia.centrum.efenix_chrome import EfenixWindow
from rozliczenia.centrum.filling import FillingReads, filling_router
from rozliczenia.centrum.http_guard import guard
from rozliczenia.centrum.intermax_run import IntermaxEntry, intermax_copies_router, intermax_router
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import LogsOnDisk
from rozliczenia.centrum.metrics import History, metrics_router
from rozliczenia.centrum.notifications import Notifications, notifications_router
from rozliczenia.centrum.order_register_router import order_register_router
from rozliczenia.centrum.period_board import periods_router
from rozliczenia.centrum.period_start import PeriodStarts
from rozliczenia.centrum.platform import Autostart, Platform
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.report_box import GitHubReportBox, ReportBox
from rozliczenia.centrum.quantity_check_run import QuantityCheckAfterRun
from rozliczenia.centrum.reports import SEARCH_DEADLINE_S, Reports
from rozliczenia.centrum.run_cards import RunCards, run_cards_router
from rozliczenia.centrum.run_comments import RecordMaker, RunComments
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.centrum.process_kind import HostParts
from rozliczenia.centrum.report_entering_run import ReportEnteringEntry, report_entering_router
from rozliczenia.centrum.report_entering_state import FileReportState
from rozliczenia.centrum.report_reminders import MinuteRhythm, ReminderRhythm, ReportReminders
from rozliczenia.centrum.runs import RunHost, runs_router
from rozliczenia.centrum.server import AFTER_START
from rozliczenia.centrum.settings.history import ReleaseOrigin
from rozliczenia.centrum.settings.owner import CentrumSettings, SettingsSnapshot
from rozliczenia.centrum.settings.proposal import ReleaseChange
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings_router import settings_router
from rozliczenia.centrum.workers_router import workers_router
from rozliczenia.centrum.quantity_differences import quantity_differences_router, with_exception_sentences
from rozliczenia.centrum.quantity_rules_preview import RecentCollectiveFiles
from rozliczenia.centrum.quantity_rules_router import PriceList, history_sentences, quantity_rules_router
from rozliczenia.centrum.shutdown import Shutdown, shutdown_router
from rozliczenia.centrum.threads import Threading
from rozliczenia.centrum.stops import Stops
from rozliczenia.centrum.timing import timing_router
from rozliczenia.centrum.tool_freshness import RememberedRelease, ToolFreshness
from rozliczenia.centrum import restart_guardian
from rozliczenia.centrum.tool_update import ToolClone
from rozliczenia.centrum.tool_updates import GuardianLauncher, ToolUpdates, tool_update_router
from rozliczenia.centrum.version import SERVICE, short_commit
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.client_data import empty_memory
from rozliczenia.dad_files import DadFiles
from rozliczenia.file_state import path_state
from rozliczenia.run_context import RunContexts, TemplateCheck, check_on_disk
from rozliczenia.intermax_copies import default_directory as default_intermax_copies
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting
from rozliczenia.report_entering import ReportEnteringParts
from rozliczenia.workbook_files import ByteSource
from rozliczenia.worker_periods import WorkerPeriods
from rozliczenia.worker_report_inbox import ImapConnect, ImapInbox, ReminderMailbox, WorkerReportInbox
from rozliczenia.wall_clock import dad_today, local_now

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


def create_app(
    *,
    config: Path,
    platform: Platform,
    autostart: Autostart,
    log: CentrumLog,
    shutdown: Shutdown,
    today: Callable[[], date] = dad_today,
    catalog: Catalog = CATALOG,
    configuration_files: ConfigurationFiles | None = None,
    tool_freshness: ToolFreshness | None = None,
    cloud_files: CloudFiles | None = None,
    report_box: ReportBox | None = None,
    clock: Clock = SYSTEM_CLOCK,
    pause: Callable[[float], None] = time.sleep,
    report_search_deadline_s: float = SEARCH_DEADLINE_S,
    tool_update: ToolClone | None = None,
    guardian: GuardianLauncher | None = None,
    source: ByteSource = DadFiles.source,
    template_check: TemplateCheck = check_on_disk,
    intermax_copies: Path | None = None,
    intermax_disk: Disk = LOCAL_DISK,
    now: Callable[[], datetime] = local_now,
    efenix_window: EfenixWindow | None = None,
    inbox_connect: ImapConnect | None = None,
    worker_report_inbox: WorkerReportInbox | None = None,
    reminder_mailbox: ReminderMailbox | None = None,
    reminder_rhythm: ReminderRhythm | None = None,
    release_changes: tuple[ReleaseChange[Any], ...] = RELEASE_CHANGES,
    update_threads: Threading = threading,
) -> FastAPI:
    """Aplikacja jednej pracy Centrum (``CentrumWork``): części składa raz, a ich kolejność przy starcie daje ``lifespan``.

    Start: najpierw zmiany Ustawień Centrum z Wydania, bo Przypomnienia o raporcie czytają Ustawienia; potem w tle
    pierwsze pytania skrzynki o sprawy taty (Powiadomienia) i o klucz do Zgłoszeń, żeby Konfiguracja nie czekała na
    Skrzynkę; potem kolejka wysyłek poprzedniej pracy, a dopiero po wpisie ``start`` wersje zastępcze z jej dzienników
    Wyceny w efenix (``AFTER_START``), bo kolejka nie dostaje wysyłki przed swoim startem; na końcu Przypomnienia co
    minutę do zamknięcia, poza Uruchomieniami (ADR 0030).

    Części: Ustawienia Centrum są jedynym czytelnikiem i pisarzem swoich plików, Historii i pamięci (ADR 0032), a chwila
    wiersza Historii to zegar ścienny, nie ``now``, które testy podają jako chwile Uruchomień. Skrzynka raportów bierze
    dostęp od Ustawień przy każdej sesji, więc nowe hasło taty działa od następnej. Najnowsze Wydanie z GitHuba ma jedną
    pamiętaną odpowiedź dla Konfiguracji, Powiadomień i Aktualizacji narzędzia (limit API); Diagnoza pyta za każdym
    razem i też zapisuje odpowiedź w pamięci. Każdy start ma własny identyfikator w ``/api/health``, po którym karta
    rozpozna nowe Centrum po Aktualizacji narzędzia.

    Trasy: bez ``/docs``, ``/redoc`` i ``/openapi.json``, bo kontrakt eksportuje ``tools/ci/export_openapi.py``, a
    Swagger ładowałby skrypty z sieci. Odmowy ``Host``/``Origin``, kolejność middleware i ``Server-Timing`` należą do
    straży HTTP (``http_guard``). Uporządkowanie INTERMAX (ADR 0019) i Wpisanie raportów (ADR 0028) mają własne karty
    i routery startu poza okresami; widok Raportów pokazuje też wynik ostatniego sprawdzenia Przypomnień. Bez
    zbudowanego frontendu działa samo API.
    """

    work = CentrumWork(config=config, log=log, clock=clock, pause=pause, forbidden=empty_memory())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[dict[str, Callable[[], None]]]:
        settings.apply_release_changes()
        notifications.check_in_background()
        box.check_in_background()
        outbox.resume()
        rhythm.start(reminders.check)
        try:
            yield {AFTER_START: comments.send_left_behind}
        finally:
            rhythm.stop()

    dad_actions = DadActionJournal(work)
    app = FastAPI(
        title="Centrum rozliczeń",
        version="kontrakt",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(dad_actions.observe)],
    )

    guard(app, log)

    instance = uuid.uuid4().hex

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(service=SERVICE, commit=_short(surroundings.tool_freshness.local()), instance=instance)

    box = KeyedBox.of_work(report_box or GitHubReportBox(), work)
    freshness = tool_freshness or ToolFreshness.of_system(box.github_key)

    def release_origin() -> ReleaseOrigin:
        """Wersja narzędzia tego Centrum dla wiersza Historii zmiany z Wydania: numer Wydania i skrót commitu."""

        commit = freshness.local()
        at_commit = None if commit is None else freshness.wydanie(commit)
        return ReleaseOrigin(
            release=None if at_commit is None else at_commit.version, commit=None if commit is None else short_commit(commit)
        )

    files = DadFiles(source=source, forbidden=work.forbidden)
    configuration = configuration_files or ConfigurationFiles.default()
    price_list = PriceList(configuration.collective_template)
    settings = CentrumSettings(
        config,
        log=log,
        now=local_now,
        pause=pause,
        autostart=autostart,
        periods=WorkerPeriods(files),
        column_names=price_list.names,
        release_changes=release_changes,
        release_origin=release_origin,
    )
    inbox = ImapInbox(lambda: settings.snapshot().inbox, connect=inbox_connect)
    sentences = with_exception_sentences(history_sentences(settings, price_list), price_list)
    app.include_router(settings_router(settings, platform, inbox.try_login, today, sentences))
    app.include_router(order_register_router(settings, platform))
    app.include_router(periods_router(settings, platform, today, catalog))
    centrum_runs = CentrumRuns(work.config)
    history = History(catalog, centrum_runs)
    cases = DadCases(work)
    release = RememberedRelease(freshness.release, clock=clock)

    surroundings = Surroundings(
        replace(freshness, release=release.fresh),
        cloud_files or CloudFiles.of_system(),
        lambda: box.judge(wait_s=report_search_deadline_s),
    )
    app.include_router(workers_router(settings, files, today))
    recent = RecentCollectiveFiles(files)
    app.include_router(quantity_rules_router(settings, price_list, recent))
    app.include_router(quantity_differences_router(settings, price_list, recent))
    filling = FillingReads(work, files)
    app.include_router(filling_router(settings, log, surroundings.cloud_files, filling))
    outbox = case_outbox(work, box, cases)
    reports = Reports(
        work,
        box,
        outbox,
        surroundings.tool_freshness.local,
        cases,
        search_deadline_s=report_search_deadline_s,
        settings_changes=settings.reported_changes,
    )

    def at(start: SettingsSnapshot | None) -> SettingsSnapshot:
        """Migawka Ustawień Centrum ze startu Uruchomienia, a bez niej (Urwane Uruchomienie) bieżąca: Logi i Diagnoza
        wyjaśniają to Uruchomienie, nie późniejszą zmianę Ustawień (D9)."""

        return settings.snapshot() if start is None else start

    disk = LogsOnDisk(log, journaled=catalog.journaled)
    records = RecordMaker(
        commit=surroundings.tool_freshness.local,
        wydanie=surroundings.tool_freshness.wydanie,
        files=lambda process, period, at_start: files_of_process(
            process, period, settings=at(at_start).folders, configuration=configuration
        ),
        cloud_files=surroundings.cloud_files,
        dad_actions=dad_actions,
    )
    comments = RunComments(work, disk, outbox, records)
    stops = Stops(
        reports,
        lambda process, period, at_start: diagnose(
            process,
            period,
            settings=at(at_start).folders,
            configuration=configuration,
            log=log,
            surroundings=surroundings,
            template_check=template_check,
            files=files,
            workers=at(at_start).workers,
        ),
        log,
        comments,
    )
    contexts = RunContexts(files=files, template_check=template_check)
    report_files = FileReportState.of_work(work)
    parts = HostParts(
        efenix=(efenix_window or EfenixWindow.of_tata()).opening(),
        journal=disk.journal,
        now=now,
        waiting=Waiting(clock, pause),
        disk=intermax_disk,
        reports=ReportEnteringParts(worker_report_inbox or inbox, report_files),
    )
    starts = PeriodStarts(settings, configuration, catalog, today, contexts, parts)
    intermax = IntermaxEntry(
        settings, catalog, intermax_copies or default_intermax_copies(), parts, surroundings.cloud_files, contexts
    )
    reminders = ReportReminders(
        work, settings, reminder_mailbox or inbox, files, reports, now
    )
    report_entering = ReportEnteringEntry(settings, catalog, configuration, parts, contexts, report_files, reminders.shown)
    rhythm = reminder_rhythm or MinuteRhythm()
    cards = RunCards(disk, history.runs)
    closed = comments.close_left_behind()
    notifications = Notifications(work, cases, box, surroundings.tool_freshness, release, lambda: cards.ended("efenix"))
    runs = RunHost(
        log,
        centrum_runs,
        stops,
        previous=cards.last(closed),
        logs=comments,
        after_run=[QuantityCheckAfterRun(work, outbox, surroundings.tool_freshness.local), filling],
    )
    shutdown.refuse_while(runs.shutdown_refusal)
    updates = ToolUpdates(
        work,
        lambda: tool_update or ToolClone.of_system(),
        runs,
        surroundings.tool_freshness.local,
        reports,
        shutdown=shutdown,
        guardian=guardian or (lambda copy, restart: restart_guardian.launch(copy, restart)),
        release=release,
        threads=update_threads,
    )
    app.include_router(runs_router(runs, starts))
    app.include_router(intermax_router(runs, intermax, lambda: cards.latest(intermax.key)))
    app.include_router(intermax_copies_router(runs, intermax))
    app.include_router(report_entering_router(runs, report_entering, lambda: cards.latest(report_entering.key)))
    app.include_router(run_cards_router(cards))
    app.include_router(notifications_router(notifications))
    app.include_router(
        dad_notes_router(work, cases, outbox, box, surroundings.tool_freshness.local, history.runs, comments.link)
    )
    app.include_router(metrics_router(history, today))
    app.include_router(
        configuration_router(
            configuration,
            surroundings.tool_freshness,
            release,
            lambda: box.judge(wait_s=CONFIGURATION_WAIT_S),
            template_check,
        )
    )
    app.include_router(tool_update_router(updates))
    app.include_router(shutdown_router(shutdown))
    app.include_router(timing_router(log))
    if path_state(STATIC_DIRECTORY) == "folder":
        app.mount("/", _Frontend(directory=STATIC_DIRECTORY, html=True), name="frontend")
    return app


class _Frontend(StaticFiles):
    """Zbudowany frontend: przeglądarka sprawdza każdy plik przy każdym użyciu (ETag), bo nazwy plików są stałe.

    Bez ``Cache-Control`` przeglądarka mogłaby po Aktualizacji narzędzia brać stary ``assets/index.js`` z pamięci
    bez pytania serwera (heurystyczna świeżość z ``Last-Modified``, RFC 9111 §4.2.2).
    """

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _short(commit: str | None) -> str | None:
    return None if commit is None else short_commit(commit)
