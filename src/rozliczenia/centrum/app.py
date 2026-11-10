"""Aplikacja HTTP Centrum rozliczeń: API pod ``/api`` i zbudowany frontend pod ``/``.

Każda grupa zasobów ma własny router; ``create_app`` składa je, pilnuje nagłówków ``Host`` i ``Origin`` (ADR 0004),
zamienia odmowy (``Refusal``) i folder okresów, którego nie da się odczytać, na bezpieczne odpowiedzi ``Problem``,
nieoczekiwany wyjątek na wpis w dzienniku Centrum i odpowiedź bez treści wyjątku, a każdej odpowiedzi API dodaje czas
obsługi w ``Server-Timing`` (``timing``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
import time
import uuid
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from rozliczenia.centrum.catalog import CATALOG, Catalog
from rozliczenia.centrum.clock import SYSTEM_CLOCK, Clock
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import CONFIGURATION_WAIT_S, ConfigurationFiles, configuration_router
from rozliczenia.centrum.case_delivery import case_outbox
from rozliczenia.centrum.contract.centrum import Health
from rozliczenia.centrum.contract.common import Problem
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.dad_action_journal import DadActionJournal
from rozliczenia.centrum.dad_cases import DadCases
from rozliczenia.centrum.dad_notes import dad_notes_router
from rozliczenia.centrum.diagnosis import Surroundings, diagnose, files_of_process
from rozliczenia.centrum.efenix_chrome import EfenixWindow
from rozliczenia.centrum.filling import FillingReads, filling_router
from rozliczenia.centrum.intermax_run import IntermaxEntry, intermax_copies_router, intermax_router
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import LogsOnDisk
from rozliczenia.centrum.metrics import History, metrics_router
from rozliczenia.centrum.notifications import Notifications, notifications_router
from rozliczenia.centrum.period_board import periods_router
from rozliczenia.centrum.period_start import PeriodStarts
from rozliczenia.centrum.platform import Platform
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
from rozliczenia.centrum.runs import RunHost, runs_router
from rozliczenia.centrum.server import AFTER_START
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.centrum.settings_router import settings_router
from rozliczenia.centrum.shutdown import Shutdown, shutdown_router
from rozliczenia.centrum.stops import Stops
from rozliczenia.centrum.timing import server_timing, timing_router
from rozliczenia.centrum.tool_freshness import RememberedRelease, ToolFreshness
from rozliczenia.centrum import restart_guardian
from rozliczenia.centrum.tool_update import ToolClone
from rozliczenia.centrum.tool_updates import GuardianLauncher, ToolUpdates, tool_update_router
from rozliczenia.centrum.version import SERVICE, short_commit
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.dad_files import DadFiles
from rozliczenia.run_context import RunContexts, TemplateCheck, check_on_disk
from rozliczenia.intermax_copies import default_directory as default_intermax_copies
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.tool_files import HOST
from rozliczenia.report_entering import ReportEnteringParts
from rozliczenia.workbook_files import ByteSource, file_bytes
from rozliczenia.worker_report_inbox import ImapInbox, WorkerReportInbox

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_LOCAL_HOSTNAMES = frozenset({HOST, "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(
    *,
    settings_path: Path,
    platform: Platform,
    log: CentrumLog,
    shutdown: Shutdown,
    today: Callable[[], date] = date.today,
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
    source: ByteSource = file_bytes,
    template_check: TemplateCheck = check_on_disk,
    intermax_copies: Path | None = None,
    intermax_disk: Disk = LOCAL_DISK,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    efenix_window: EfenixWindow | None = None,
    worker_report_inbox: WorkerReportInbox | None = None,
) -> FastAPI:
    work = CentrumWork(config=settings_path.parent, log=log, clock=clock, pause=pause)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[dict[str, Callable[[], None]]]:
        # Powiadomienia: pierwsze pytanie skrzynki o stan spraw taty przy starcie, nie dopiero przy odczycie.
        notifications.check_in_background()
        # Klucz do Zgłoszeń: pierwsze sprawdzenie w tle, żeby Konfiguracja nie czekała na Skrzynkę.
        box.check_in_background()
        # Wysyłki, których poprzednia praca Centrum nie wysłała, a po nich, już po wpisie ``start``, wersje zastępcze z
        # jej dzienników Wyceny w efenix: kolejka nie dostaje wysyłki przed swoim startem.
        outbox.resume()
        yield {AFTER_START: comments.send_left_behind}

    dad_actions = DadActionJournal(work)
    # Bez /docs i /openapi.json: kontrakt eksportuje tools/ci/export_openapi.py, a Swagger ładowałby skrypty z sieci.
    app = FastAPI(
        title="Centrum rozliczeń",
        version="kontrakt",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(dad_actions.observe)],
    )

    @app.middleware("http")
    async def only_local_browser(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if urlsplit(f"//{host}").hostname not in _LOCAL_HOSTNAMES:
            return _problem(refusal.not_local_address())
        if request.method not in _SAFE_METHODS and request.headers.get("origin") != f"http://{host}":
            return _problem(refusal.not_from_centrum_card())
        return await call_next(request)

    @app.middleware("http")
    async def unexpected_failure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as failure:
            route = request.scope.get("route")
            log.unexpected_failure(failure, where=f"{request.method} {getattr(route, 'path', 'poza API')}")
            return _problem(refusal.unexpected_failure())

    # Ostatni dodany middleware jest zewnętrzny: czas obejmuje też odmowy Host/Origin i nieoczekiwane wyjątki.
    app.middleware("http")(server_timing)

    @app.exception_handler(Refusal)
    async def refused(request: Request, refused: Refusal) -> Response:
        return _problem(refused)

    @app.exception_handler(PeriodFolderInaccessible)
    async def inaccessible_folder(request: Request, inaccessible: PeriodFolderInaccessible) -> Response:
        return _problem(refusal.period_folder_unreadable(inaccessible.folder.name))

    # Każdy start Centrum ma własny identyfikator: karta po aktualizacji rozpozna po nim nowe Centrum.
    instance = uuid.uuid4().hex

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(service=SERVICE, commit=_short(surroundings.tool_freshness.local()), instance=instance)

    store = SettingsStore(settings_path, log=log, pause=pause)
    app.include_router(settings_router(store, platform))
    configuration = configuration_files or ConfigurationFiles.default()
    app.include_router(periods_router(store, platform, today, catalog))
    centrum_runs = CentrumRuns(work.config)
    history = History(catalog, centrum_runs)
    cases = DadCases(work)
    box = KeyedBox.of_work(report_box or GitHubReportBox(), work)
    # Najnowsze Wydanie na GitHubie, pytane z kluczem do Zgłoszeń, gdy jest: jedna pamiętana odpowiedź dla Konfiguracji,
    # Powiadomień i wyniku Aktualizacji narzędzia (limit API); Diagnoza pyta za każdym razem, a jej odpowiedź też trafia
    # do pamięci.
    freshness = tool_freshness or ToolFreshness.of_system(box.github_key)
    release = RememberedRelease(freshness.release, clock=clock)
    # Diagnoza: commit `main` z GitHuba, atrybuty OneDrive i werdykt Skrzynki o kluczu to granice komputera taty.
    surroundings = Surroundings(
        replace(freshness, release=release.fresh),
        cloud_files or CloudFiles.of_system(),
        lambda: box.judge(wait_s=report_search_deadline_s),
    )
    # Uchwyt plików taty tej pracy: Uruchomienia, Diagnoza, Uzupełnienie i dni INTERMAX czytają nim pliki taty ze źródła
    # bajtów ``source``, a jego pamięć to pamięć reguły danych pracy.
    files = DadFiles(source=source, forbidden=work.forbidden)
    filling = FillingReads(work, files)
    app.include_router(filling_router(store, log, surroundings.cloud_files, filling))
    outbox = case_outbox(work, box, cases)
    reports = Reports(
        work, box, outbox, surroundings.tool_freshness.local, cases, search_deadline_s=report_search_deadline_s
    )
    disk = LogsOnDisk(log, journaled=catalog.journaled)
    records = RecordMaker(
        commit=surroundings.tool_freshness.local,
        wydanie=surroundings.tool_freshness.wydanie,
        files=lambda process, period: files_of_process(
            process, period, settings=store.load(), configuration=configuration
        ),
        cloud_files=surroundings.cloud_files,
        dad_actions=dad_actions,
    )
    comments = RunComments(work, disk, outbox, records)
    stops = Stops(
        reports,
        lambda process, period: diagnose(
            process,
            period,
            settings=store.load(),
            configuration=configuration,
            log=log,
            surroundings=surroundings,
            template_check=template_check,
            files=files,
        ),
        log,
        comments,
    )
    contexts = RunContexts(files=files, template_check=template_check)
    # Okno efenix taty: Google Chrome w profilu narzędzia z prawdziwym efenix; testy podają okno Atrapy efenix.
    # Skrzynka raportów taty w Gmailu z plikiem dostępu w ``config``; testy i skille podają atrapę.
    report_files = FileReportState.of_work(work)
    parts = HostParts(
        efenix=(efenix_window or EfenixWindow.of_tata()).opening(),
        journal=disk.journal,
        now=now,
        waiting=Waiting(clock, pause),
        disk=intermax_disk,
        reports=ReportEnteringParts(worker_report_inbox or ImapInbox(work.config), report_files),
    )
    starts = PeriodStarts(store, configuration, catalog, today, contexts, parts)
    # Uporządkowanie INTERMAX ma własną kartę poza okresami (ADR 0019), więc ma własny router startu.
    intermax = IntermaxEntry(
        store, catalog, intermax_copies or default_intermax_copies(), parts, surroundings.cloud_files, contexts
    )
    # Wpisanie raportów ma własną kartę poza okresami (ADR 0028), jak Uporządkowanie INTERMAX.
    report_entering = ReportEnteringEntry(store, catalog, configuration, parts, contexts, report_files)
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
    # Klon narzędzia, które Centrum aktualizuje (ADR 0009); w testach klon z lokalnym „origin”.
    updates = ToolUpdates(
        work,
        lambda: tool_update or ToolClone.of_system(),
        runs,
        surroundings.tool_freshness.local,
        reports,
        shutdown=shutdown,
        guardian=guardian or (lambda copy, restart: restart_guardian.launch(copy, restart)),
        release=release,
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
            configuration, surroundings.tool_freshness, release, lambda: box.judge(wait_s=CONFIGURATION_WAIT_S), template_check
        )
    )
    app.include_router(tool_update_router(updates))
    app.include_router(shutdown_router(shutdown))
    app.include_router(timing_router(log))
    if STATIC_DIRECTORY.is_dir():  # bez buildu (np. świeży katalog roboczy frontendu) działa samo API
        app.mount("/", _Frontend(directory=STATIC_DIRECTORY, html=True), name="frontend")
    return app


def _problem(refused: Refusal) -> Response:
    return JSONResponse(Problem(message=refused.message).model_dump(), status_code=refused.status_code)


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
