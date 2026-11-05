"""Aplikacja HTTP Centrum rozliczeń: API pod ``/api`` i zbudowany frontend pod ``/``.

Każda grupa zasobów ma własny router (``settings_router``, ``periods_router``, ``filling_router``,
``runs_router``, ``intermax_router``, ``intermax_copies_router``, ``notifications_router``, ``dad_notes_router``,
``metrics_router``, ``configuration_router``, ``tool_update_router``, ``shutdown_router``, ``timing_router``);
``create_app`` składa je, pilnuje nagłówków ``Host`` i ``Origin`` (ADR 0004),
zamienia odmowy (``contract.Refusal``) i folder okresów, którego nie da się odczytać, na bezpieczne
odpowiedzi ``Problem``,
nieoczekiwany wyjątek na wpis w dzienniku Centrum i odpowiedź bez treści wyjątku,
a każdej odpowiedzi API dodaje czas obsługi w ``Server-Timing`` (``timing``).
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

from rozliczenia.centrum.catalog import EFENIX
from rozliczenia.centrum.clock import SYSTEM_CLOCK, Clock
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import CONFIGURATION_WAIT_S, ConfigurationFiles, configuration_router
from rozliczenia.centrum.case_delivery import case_outbox
from rozliczenia.centrum.contract import Health, Problem, Refusal, RunInfo
from rozliczenia.centrum.dad_actions import DAD_ACTIONS_FILE, DadActionJournal
from rozliczenia.centrum.dad_cases import DadCases
from rozliczenia.centrum.dad_notes import dad_notes_router
from rozliczenia.centrum.diagnosis import Surroundings, diagnose, files_of_process
from rozliczenia.centrum.efenix_run import EfenixEntry, EfenixWindow
from rozliczenia.centrum.filling import FillingReads, filling_router
from rozliczenia.centrum.intermax_run import IntermaxEntry, intermax_copies_router, intermax_router
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import metrics_router, read_runs
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE, Notifications, ReadNotifications, notifications_router
from rozliczenia.centrum.period_board import periods_router
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.keyed_box import OPENING_FILE, KeyedBox, NotesFile, read_report_key
from rozliczenia.centrum.report_box import GitHubReportBox, ReportBox
from rozliczenia.centrum.outbox import ADDRESSES_FILE, QUEUE_DIRECTORY
from rozliczenia.centrum.quantity_check_run import QuantityCheckAfterRun
from rozliczenia.centrum.reports import SEARCH_DEADLINE_S, UNSENT_DIRECTORY, Reports
from rozliczenia.centrum.preparation_run import PreparationEntry
from rozliczenia.centrum.pricing_journal import (
    JOURNALS_DIRECTORY,
    InterruptedPricings,
    JournalAfterLogs,
    PricingJournal,
)
from rozliczenia.centrum.pricing_progress import ProgressComment
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.run_cards import LAST_STARTED_FILE, RunCards, run_cards_router
from rozliczenia.centrum.run_logs import RUN_LOGS_DIRECTORY, RunLogs
from rozliczenia.centrum.run_origins import CENTRUM_RUNS_FILE, CentrumRuns
from rozliczenia.centrum.runs import ProcessEntry, RunHost, runs_router
from rozliczenia.centrum.settings import settings_router
from rozliczenia.settings import SettingsStore
from rozliczenia.centrum.settlement_run import SettlementEntry
from rozliczenia.centrum.shutdown import Shutdown, shutdown_router
from rozliczenia.centrum.stops import Stops
from rozliczenia.centrum.timing import server_timing, timing_router
from rozliczenia.centrum.tool_freshness import RememberedRelease, ToolFreshness
from rozliczenia.centrum import restart_guardian
from rozliczenia.centrum.tool_update import RESULT_FILE, ToolClone
from rozliczenia.centrum.tool_updates import GuardianLauncher, ToolUpdates, tool_update_router
from rozliczenia.centrum.version import SERVICE, short_commit
from rozliczenia.client_data import ForbiddenValues
from rozliczenia.input_checks import FILE_READERS, Readers
from rozliczenia.intermax_copies import default_directory as default_intermax_copies
from rozliczenia.intermax_replace import LOCAL_DISK, Disk, Waiting
from rozliczenia.period_folder import PeriodFolderInaccessible

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(
    *,
    settings_path: Path,
    platform: Platform,
    log: CentrumLog,
    shutdown: Shutdown,
    today: Callable[[], date] = date.today,
    processes: Processes | None = None,
    configuration_files: ConfigurationFiles | None = None,
    tool_freshness: ToolFreshness | None = None,
    cloud_files: CloudFiles | None = None,
    report_box: ReportBox | None = None,
    clock: Clock = SYSTEM_CLOCK,
    pause: Callable[[float], None] = time.sleep,
    report_search_deadline_s: float = SEARCH_DEADLINE_S,
    tool_update: ToolClone | None = None,
    guardian: GuardianLauncher | None = None,
    readers: Readers = FILE_READERS,
    intermax_copies: Path | None = None,
    intermax_disk: Disk = LOCAL_DISK,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    efenix_window: EfenixWindow | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Powiadomienia: pierwsze pytanie skrzynki o stan spraw taty przy starcie, nie dopiero przy odczycie.
        notifications.check_in_background()
        # Klucz do Zgłoszeń: pierwsze sprawdzenie w tle, żeby Konfiguracja nie czekała na Skrzynkę.
        box.check_in_background()
        # Kontrole ilości, Logi i Uwagi taty, których poprzednia praca Centrum nie wysłała (brak sieci albo klucza),
        # wychodzą w tle.
        outbox.resume()
        yield

    # Działania taty w Centrum dla Logów następnego Uruchomienia: każda trasa API wpisuje widok albo przycisk.
    dad_actions = DadActionJournal(log.directory / DAD_ACTIONS_FILE, log)

    async def send_interrupted() -> None:
        # Logi Urwanych Uruchomień z dzienników Wyceny w efenix idą przy pierwszym zapytaniu, już po ``lifespan``.
        await interrupted.send()

    # Bez /docs i /openapi.json: kontrakt eksportuje tools/ci/export_openapi.py, a Swagger ładowałby skrypty z sieci.
    app = FastAPI(
        title="Centrum rozliczeń",
        version="kontrakt",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(dad_actions.observe), Depends(send_interrupted)],
    )

    @app.middleware("http")
    async def only_local_browser(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if urlsplit(f"//{host}").hostname not in _LOCAL_HOSTNAMES:
            return _problem(403, "Centrum rozliczeń odpowiada tylko na adres tego komputera.")
        if request.method not in _SAFE_METHODS and request.headers.get("origin") != f"http://{host}":
            return _problem(403, "Tę akcję można wykonać tylko z karty Centrum rozliczeń.")
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
            return _problem(500, "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie.")

    # Ostatni dodany middleware jest zewnętrzny: czas obejmuje też odmowy Host/Origin i nieoczekiwane wyjątki.
    app.middleware("http")(server_timing)

    @app.exception_handler(Refusal)
    async def refused(request: Request, refusal: Refusal) -> Response:
        return _problem(refusal.status_code, refusal.message)

    @app.exception_handler(PeriodFolderInaccessible)
    async def inaccessible_folder(request: Request, inaccessible: PeriodFolderInaccessible) -> Response:
        return _problem(
            500,
            f"Nie udało się odczytać folderu {inaccessible.folder.name}. "
            "Sprawdź, czy otwiera się w Eksploratorze plików i czy OneDrive działa, potem odśwież kartę.",
        )

    # Każdy start Centrum ma własny identyfikator: karta po aktualizacji rozpozna po nim nowe Centrum.
    instance = uuid.uuid4().hex

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(service=SERVICE, commit=_short(surroundings.tool_freshness.local()), instance=instance)

    store = SettingsStore(settings_path)
    app.include_router(settings_router(store, platform))
    configuration = configuration_files or ConfigurationFiles.default()
    processes = processes or Processes.default()
    app.include_router(periods_router(store, platform, today, processes))
    # Uruchomienia z Centrum we własnym dzienniku obok ustawień; schemat metryk się nie zmienia.
    centrum_runs = CentrumRuns(settings_path.parent / CENTRUM_RUNS_FILE)
    # Najnowsze Wydanie na GitHubie: jedna pamiętana odpowiedź dla Konfiguracji, Powiadomień i wyniku Aktualizacji
    # narzędzia (limit API bez klucza); Diagnoza pyta za każdym razem, a jej odpowiedź też trafia do pamięci.
    freshness = tool_freshness or ToolFreshness.of_system()
    release = RememberedRelease(freshness.release, clock=clock)
    # Sprawy taty: wysłane Zgłoszenia i Uwagi taty w jednym pliku stanu obok Ustawień taty (ADR 0015).
    config = settings_path.parent
    cases = DadCases(config, log, pause=pause)
    # Zgłoszenia do Maksa: skrzynka obok platformy, klucz obok Ustawień taty (ADR 0007).
    box = KeyedBox(
        report_box or GitHubReportBox(),
        lambda: read_report_key(config),
        clock=clock,
        opening=NotesFile(config / OPENING_FILE, replace_atomically, log.box_notes_unavailable),
    )
    # Diagnoza: commit `main` z GitHuba, atrybuty OneDrive i werdykt Skrzynki o kluczu to granice komputera taty.
    surroundings = Surroundings(
        replace(freshness, release=release.fresh),
        cloud_files or CloudFiles.of_system(),
        lambda: box.judge(wait_s=report_search_deadline_s),
    )
    # Reguła danych (ADR 0025): zakazane wartości z każdego pliku taty, który ta praca Centrum przeczytała, dla
    # strażnika każdej wysyłki do Skrzynki; jedna pamięć na pracę Centrum, tylko w pamięci.
    forbidden = ForbiddenValues()
    filling = FillingReads(clock=clock, forbidden=forbidden)
    app.include_router(filling_router(store, log, surroundings.cloud_files, filling))
    # Kontrola ilości, Logi Uruchomienia, Uwagi taty i Zgłoszenia: w kolejce Skrzynki, wysyłane w tle (ADR 0007, 0013,
    # 0015); co doręczenie znaczy dla Spraw taty, wiedzą Sprawy taty w Skrzynce.
    outbox = case_outbox(
        config / UNSENT_DIRECTORY / QUEUE_DIRECTORY, box, log, cases, clock=clock, addresses=config / ADDRESSES_FILE
    )
    reports = Reports(
        box,
        outbox,
        surroundings.tool_freshness.local,
        cases,
        search_deadline_s=report_search_deadline_s,
        forbidden=forbidden,
    )
    # Dziennik Wyceny w efenix w trakcie Uruchomienia, obok Logów: przeżywa nagłe zgaśnięcie Centrum (#845).
    journal = PricingJournal(log.directory / JOURNALS_DIRECTORY, log, process=EFENIX.key)
    # Logi Uruchomienia: jeden plik JSON na Uruchomienie obok dziennika Centrum, poza Gitem i OneDrive (ADR 0015).
    run_logs = RunLogs(
        log.directory / RUN_LOGS_DIRECTORY,
        outbox,
        commit=surroundings.tool_freshness.local,
        wydanie=surroundings.tool_freshness.wydanie,
        files=lambda process, period: files_of_process(
            process, period, settings=store.load(), configuration=configuration
        ),
        cloud_files=surroundings.cloud_files,
        dad_actions=dad_actions,
        forbidden=forbidden,
    )
    # Jedno Uruchomienie procesu albo Aktualizacja narzędzia naraz; w ich trakcie zamknięcie Centrum jest odrzucone.
    stops = Stops(
        reports,
        lambda process, period: diagnose(
            process,
            period,
            settings=store.load(),
            configuration=configuration,
            log=log,
            surroundings=surroundings,
            readers=readers,
            forbidden=forbidden,
        ),
        log,
        run_logs,
    )
    # Adaptery startu procesów z katalogu procesów; reszta Centrum pyta wpis procesu w katalogu, nie adapter.
    entries: list[ProcessEntry] = [
        PreparationEntry(store, configuration, processes, today, readers, forbidden),
        # Okno efenix taty: Google Chrome w profilu narzędzia z prawdziwym efenix; testy podają okno Atrapy efenix.
        # Kafelek Wyceny w efenix stoi przed Przebiegiem rozliczeń, bo w tej kolejności tata pracuje.
        EfenixEntry(store, processes, today, efenix_window or EfenixWindow.of_tata(), journal, forbidden),
        SettlementEntry(store, configuration, processes, today, readers, forbidden),
    ]
    # Uporządkowanie INTERMAX ma własną kartę poza okresami (ADR 0019), więc ma własny router startu.
    intermax = IntermaxEntry(
        store,
        processes,
        intermax_copies or default_intermax_copies(),
        now,
        Waiting(clock, pause),
        intermax_disk,
        surroundings.cloud_files,
        forbidden,
    )
    # Karty Uruchomień z pliku startu, Logów Uruchomienia i Historii: ostatnie po starcie Centrum i wiersz Historii (ADR 0017).
    cards = RunCards(
        log.directory / RUN_LOGS_DIRECTORY,
        log.directory / LAST_STARTED_FILE,
        lambda: read_runs(processes, centrum_runs.started()),
    )
    # Dzienniki Urwanych Wycen w efenix stają się ich Logami, zanim karta ostatniego Uruchomienia przeczyta Logi.
    interrupted = InterruptedPricings(log.directory / JOURNALS_DIRECTORY, run_logs, log)
    interrupted.close()
    # Komentarz postępu Wyceny w efenix w issue Logów okresu, odświeżany z jej dziennika (#846).
    progress = ProgressComment(journal, run_logs, clock=clock)

    def run_started(info: RunInfo, started_at: datetime) -> None:
        journal.run_started(info, started_at)
        cards.run_started(info, started_at)
        progress.run_started(info, started_at)  # ostatni: postęp jest dla Maksa, a nie warunkiem pracy taty

    # Powiadomienia o Uwagach taty, wysłanych Zgłoszeniach, Wydaniach i zakończonych Wycenach w efenix z Logów
    # Uruchomienia; przeczytane obok Ustawień taty (ADR 0015).
    notifications = Notifications(
        cases,
        ReadNotifications(config / NOTIFICATIONS_FILE, log, pause=pause),
        box,
        surroundings.tool_freshness,
        release,
        log,
        lambda: cards.ended(EFENIX.key),
        clock=clock,
    )
    runs = RunHost(
        log,
        centrum_runs,
        stops,
        previous=cards.last(),
        run_started=run_started,
        # Wpis końca dziennika Wyceny w efenix przed Logami z wynikiem: start Centrum nie weźmie Uruchomienia, którego Logi
        # z wynikiem mogą być w Skrzynce, za Urwane (#871).
        after_run=[
            journal,
            run_logs,
            JournalAfterLogs(journal, run_logs),
            QuantityCheckAfterRun(outbox, surroundings.tool_freshness.local, forbidden),
            filling,
        ],
    )
    shutdown.refuse_while(runs.shutdown_refusal)
    # Klon narzędzia, które Centrum aktualizuje (ADR 0009); w testach klon z lokalnym „origin”. Po sukcesie
    # opiekun ponownego startu zostawia wynik obok Ustawień taty, a to Centrum odczytuje go teraz, raz.
    updates = ToolUpdates(
        lambda: tool_update or ToolClone.of_system(),
        runs,
        log,
        surroundings.tool_freshness.local,
        reports,
        shutdown=shutdown,
        guardian=guardian or (lambda copy, restart: restart_guardian.launch(copy, restart)),
        result_file=settings_path.parent / RESULT_FILE,
        release=release,
    )
    app.include_router(runs_router(runs, entries))
    app.include_router(intermax_router(runs, intermax, lambda: cards.latest(intermax.key)))
    app.include_router(intermax_copies_router(runs, intermax))
    app.include_router(run_cards_router(cards))
    app.include_router(notifications_router(notifications))
    app.include_router(
        dad_notes_router(
            cases,
            outbox,
            box,
            surroundings.tool_freshness.local,
            lambda: read_runs(processes, centrum_runs.started()),
            run_logs.link,
            forbidden,
        )
    )
    app.include_router(metrics_router(processes, today, centrum_runs))
    app.include_router(
        configuration_router(
            configuration, surroundings.tool_freshness, release, lambda: box.judge(wait_s=CONFIGURATION_WAIT_S), readers
        )
    )
    app.include_router(tool_update_router(updates))
    app.include_router(shutdown_router(shutdown))
    app.include_router(timing_router(log))
    if STATIC_DIRECTORY.is_dir():  # bez buildu (np. świeży katalog roboczy frontendu) działa samo API
        app.mount("/", _Frontend(directory=STATIC_DIRECTORY, html=True), name="frontend")
    return app


def _problem(status_code: int, message: str) -> Response:
    return JSONResponse(Problem(message=message).model_dump(), status_code=status_code)


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
