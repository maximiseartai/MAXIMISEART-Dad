"""Centrum rozliczeń w testach z procesem do uruchomienia: syntetyczne pliki Przygotowania i Przebiegu.

``restart()`` to nowa aplikacja Centrum na tych samych plikach i Ustawieniach
taty, jak po zamknięciu i ponownym otwarciu Centrum na komputerze taty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
import json
from pathlib import Path
import shutil
import threading
from typing import Any, Protocol, TypeVar

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.catalog import Catalog
from rozliczenia.centrum.reports import SEARCH_DEADLINE_S
from rozliczenia.centrum.restart_guardian import Restart
from rozliczenia.centrum.tool_freshness import GitHubReleases, ToolFreshness
from rozliczenia.centrum.tool_update import ToolClone, find_git
from rozliczenia.efenix_pace import Pace
from rozliczenia.dad_files import ReadFile
from rozliczenia.input_checks import FILE_READERS, Readers
from rozliczenia.preparation_register import RegisterSheet
from rozliczenia.settlement_period import SettlementPeriod
from rozliczenia.process_run import Process, ProcessInputs, ProcessSummary
from rozliczenia.telemetry import CompletedResult
from rozliczenia.run_context import RunContext

from tests.fixtures.centrum import (
    NO_EFENIX,
    QUEUE_THREAD,
    RUN_LOGS_IN_BACKGROUND,
    CentrumClient,
    FakeGitHub,
    FakeOneDrive,
    FakePlatform,
    FakeReportBox,
    MetricsPaths,
    ToolDirectory,
    centrum_app,
    efenix_window,
    finished_view,
    join_threads_since,
)
from tests.fixtures.clock import ManualClock
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import (
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    write_collective_template,
    write_internal_template,
)
from tests.fixtures.settlement import SOURCE_NAME, write_mapping, write_source, write_template
from tests.fixtures.tool_clone import FakeInstaller, ToolRepository

# Środa po okresie 08_14_09_2026, więc to on jest ostatnim pełnym okresem.
TODAY = date(2026, 9, 16)
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {PERIOD}"

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=ProcessSummary)


@dataclass
class Engines:
    """Prawdziwe rdzenie obu procesów, sterowane przez seam ``Process``.

    ``fail_engine``: silnik rzuca nieoczekiwany wyjątek, zanim przeczyta pliki taty. ``fail_summary``:
    silnik kończy pracę, a wynik procesu (``Process.result``) rzuca wyjątek, czyli podsumowania nie da się pokazać.
    """

    metrics: MetricsPaths
    fail_engine: bool = False
    fail_summary: bool = False

    def catalog(self) -> Catalog:
        return self.metrics.catalog().steered(self._steered)

    def _steered(self, real: Process[InputsT, SummaryT, RunContext]) -> Process[InputsT, SummaryT, RunContext]:
        def execute(inputs: InputsT, context: RunContext) -> SummaryT:
            if self.fail_engine:
                raise RuntimeError("nieprzewidziany błąd przy SYN-001")
            return real.execute(inputs, context)

        def result(inputs: InputsT, summary: SummaryT) -> CompletedResult:
            if self.fail_summary:
                raise ValueError("synthetic summary failure SYN-001")
            return real.result(inputs, summary)

        return replace(real, execute=execute, result=result)


@dataclass
class _StartClock:
    """Zegar jednego startu Centrum na czasie ``ManualClock`` komputera, jak zegar procesu na zegarze komputera.

    Po ``stopped`` budziki tego startu już nie dzwonią, jak budziki zamkniętego procesu, a czas biegnie dalej dla
    następnego startu. ``ManualClock.wakes`` liczy je, dopóki ich chwila nie nadejdzie.
    """

    clock: ManualClock
    stopped: bool = False

    def __call__(self) -> float:
        return self.clock()

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        def woken() -> None:
            if not self.stopped:
                wake()

        self.clock.after(seconds, woken)


@dataclass
class Surroundings:
    """GitHub, OneDrive, skrzynka Zgłoszeń, zegar i czytniki plików taty widziane z komputera taty.

    ``clock`` to zegar komputera taty: każdy start Centrum dostaje na nim własny zegar (``started_clock``).

    ``onedrive=None`` to prawdziwy odczyt atrybutów tego systemu. ``tool`` to
    narzędzie jako prawdziwy klon z lokalnym „origin” zamiast GitHuba: wtedy
    commit narzędzia i najnowsze Wydanie pochodzą z tych repozytoriów, a Aktualizacja
    narzędzia przesuwa ten klon. ``update_hold`` zatrzymuje każdą Aktualizację
    narzędzia na jej początku, dopóki test jej nie puści (``set``), a
    ``installer`` instaluje biblioteki zamiast pip. Opiekun ponownego startu po udanej
    aktualizacji tylko zapisuje prośbę w ``restarts`` (i usuwa katalog
    tymczasowy aktualizacji, jak prawdziwy po starcie nowej wersji). Z
    ``guardian_failure`` opiekun nie wystartuje: wywołuje ją i rzuca ``OSError``.
    ``report_search_deadline_s`` to limit, po którym Diagnoza przestaje czekać na skrzynkę Zgłoszeń.
    ``release_unanswered`` to GitHub, który przy ``tool`` nie odpowiada o najnowsze Wydanie, chociaż klon dalej
    pobiera z „origin”. ``readers`` czytają Rejestr zleceń i Wzorce w Uruchomieniu procesu, Diagnozie i Konfiguracji.
    ``find_git`` znajduje Gita, którego przy ``tool`` używa Centrum (``None``: Gita nie ma). ``efenix_url`` to lista zleceń
    okna efenix Wyceny w efenix w Chromium Playwrighta bez okna: domyślnie adres, pod którym nic nie odpowiada, a w testach
    Wyceny adres Atrapy efenix, nigdy efenix.pl; ``efenix_arguments`` to dodatkowe argumenty tej przeglądarki (np. port
    debugowania, przez który test zamyka okno), a ``efenix_pace`` tempo ludzkie tego okna, domyślnie wyłączone.
    """

    github: FakeGitHub = field(default_factory=FakeGitHub)
    onedrive: FakeOneDrive | None = field(default_factory=FakeOneDrive)
    report_box: FakeReportBox = field(default_factory=lambda: FakeReportBox(background=RUN_LOGS_IN_BACKGROUND))
    clock: ManualClock = field(default_factory=ManualClock)
    tool: ToolRepository | None = None
    update_hold: threading.Event | None = None
    installer: FakeInstaller = field(default_factory=FakeInstaller)
    restarts: list[Restart] = field(default_factory=list)
    guardian_failure: Callable[[], None] | None = None
    report_search_deadline_s: float = SEARCH_DEADLINE_S
    release_unanswered: bool = False
    readers: Readers = FILE_READERS
    find_git: Callable[[], Path | None] = find_git
    efenix_url: str = NO_EFENIX
    efenix_arguments: tuple[str, ...] = ()
    efenix_pace: Pace | None = None
    _start: _StartClock | None = field(default=None, init=False, repr=False)

    def started_clock(self) -> _StartClock:
        """Zegar nowego startu Centrum; budziki poprzedniego startu na tych otoczeniach już nie dzwonią."""

        if self._start is not None:
            self._start.stopped = True
        self._start = _StartClock(self.clock)
        return self._start

    def tool_freshness(self) -> ToolFreshness:
        tool = self.tool
        if tool is None:
            return self.github.freshness()

        def release() -> GitHubReleases | None:
            return None if self.release_unanswered else tool.github_releases()

        return ToolFreshness.of_clone(tool.clone, release, tool.published, find_git=self.find_git)

    def tool_update(self) -> ToolClone | None:
        tool, hold = self.tool, self.update_hold
        if tool is None:
            return None

        def held_git() -> Path | None:
            if hold is not None:
                hold.wait()
            return self.find_git()

        return ToolClone(
            tool.clone, origin=str(tool.origin), find_git=held_git, install=self.installer
        )

    def guardian(self, copy: Path, restart: Restart) -> None:
        assert (copy / "rozliczenia" / "centrum" / "restart_guardian.py").is_file()
        if self.guardian_failure is not None:
            self.guardian_failure()
            raise OSError("opiekun nie wystartował")
        self.restarts.append(restart)
        shutil.rmtree(restart.work)


@dataclass
class HeldRegister:
    """Rejestr zleceń, którego odczyt w Uruchomieniu procesu czeka, aż test go puści (``released``).

    ``reading`` mówi, że Uruchomienie już czyta Rejestr. Ponowny start Centrum w tym czasie to Centrum zamknięte
    w trakcie Uruchomienia: stare Uruchomienie nie kończy się, dopóki test go nie puści.
    """

    reading: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)

    def readers(self) -> Readers:
        def register(file: ReadFile, period: SettlementPeriod | None) -> list[RegisterSheet]:
            self.reading.set()
            self.released.wait()
            return FILE_READERS.register(file, period)

        return replace(FILE_READERS, register=register)


def _client(
    tmp_path: Path,
    platform: FakePlatform,
    configuration: ConfigurationFiles,
    engines: Engines,
    surroundings: Surroundings,
    since: int | None = None,
) -> CentrumClient:
    return CentrumClient(_app(tmp_path, platform, configuration, engines, surroundings), since=since)


def _app(
    tmp_path: Path,
    platform: FakePlatform,
    configuration: ConfigurationFiles,
    engines: Engines,
    surroundings: Surroundings,
) -> FastAPI:
    tool = ToolDirectory(tmp_path)
    onedrive = surroundings.onedrive
    return centrum_app(
        tool,
        platform=platform,
        today=TODAY,
        configuration_files=configuration,
        catalog=engines.catalog(),
        tool_freshness=surroundings.tool_freshness(),
        cloud_files=None if onedrive is None else onedrive.cloud_files(),
        report_box=surroundings.report_box,
        clock=surroundings.started_clock(),
        pause=surroundings.clock.pause,
        report_search_deadline_s=surroundings.report_search_deadline_s,
        tool_update=surroundings.tool_update(),
        guardian=surroundings.guardian,
        readers=surroundings.readers,
        window=efenix_window(
            tool, surroundings.efenix_url, arguments=surroundings.efenix_arguments, pace=surroundings.efenix_pace
        ),
    )


@dataclass
class PreparingCentrum:
    client: CentrumClient
    fixture: PreparationFixture
    metrics_path: Path
    log_path: Path
    tmp_path: Path
    surroundings: Surroundings
    engines: Engines

    @property
    def tool(self) -> ToolDirectory:
        return ToolDirectory(self.tmp_path)

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "preparation", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def restart(self) -> None:
        """Nowe Centrum na tych samych plikach i Ustawieniach taty, gdy skończy się przejście kolejki poprzedniego.

        Jak w nowym procesie kolejka poprzedniego Centrum już nic nie robi: kolejka, która zastałaby jej przejście na
        tym samym folderze, oddałaby jej swoje (``outbox._claimed``), więc ponowny start czeka na koniec tego
        przejścia, a budziki poprzedniego Centrum (ponowienie kolejki za ``RETRY_S``) już nie dzwonią, choć czas
        ``surroundings.clock`` biegnie dalej. Inne wątki poprzedniego Centrum mogą dalej żyć, np. Uruchomienie, które
        test trzyma (``HeldRegister``): puszczone kończy się w poprzednim Centrum i jego Logi idą jego kolejką.
        """

        join_threads_since(self.client.since, named=QUEUE_THREAD)
        self.client = _preparation_client(
            self.tmp_path,
            self.fixture,
            FakePlatform(),
            self.surroundings,
            self.engines,
            since=self.client.since,
        )


def _preparation_client(
    tmp_path: Path,
    fixture: PreparationFixture,
    platform: FakePlatform,
    surroundings: Surroundings,
    engines: Engines,
    *,
    since: int | None = None,
) -> CentrumClient:
    configuration = replace(
        ToolDirectory(tmp_path).configuration,
        worker_config=fixture.config_path,
        internal_template=fixture.internal_template_path,
        collective_template=fixture.collective_template_path,
    )
    return _client(tmp_path, platform, configuration, engines, surroundings, since)


def preparing_centrum(
    tmp_path: Path, rows: list[RegisterRow] | None = None, *, surroundings: Surroundings | None = None
) -> PreparingCentrum:
    """Centrum z zapamiętanym syntetycznym Rejestrem zleceń i folderem okresów oraz własnymi wzorcami i metrykami.

    Bez ``surroundings`` narzędzie jest aktualne, a każdy plik ma kopię na tym komputerze.
    """

    fixture = make_preparation_fixture(tmp_path, rows)
    platform = FakePlatform(chosen_files=[fixture.register_path], chosen_folders=[fixture.periods_directory])
    surroundings = surroundings or Surroundings()
    engines = Engines(ToolDirectory(tmp_path).metrics)
    client = _preparation_client(tmp_path, fixture, platform, surroundings, engines)
    client.post("/api/settings/register/choose")
    client.post("/api/settings/periods-directory/choose")
    return PreparingCentrum(
        client,
        fixture,
        engines.metrics.preparation,
        ToolDirectory(tmp_path).log_path,
        tmp_path,
        surroundings,
        engines,
    )


@dataclass
class SettlingCentrum:
    client: CentrumClient
    periods_directory: Path
    metrics_path: Path
    log_path: Path
    period_parent: Path
    configuration: ConfigurationFiles
    tmp_path: Path
    surroundings: Surroundings
    engines: Engines

    @property
    def tool(self) -> ToolDirectory:
        return ToolDirectory(self.tmp_path)

    @property
    def period_directory(self) -> Path:
        return self.period_parent / PERIOD

    @property
    def collective_file(self) -> Path:
        return self.period_directory / SOURCE_NAME

    @property
    def worker_settlements(self) -> Path:
        return self.period_directory / WORKER_SETTLEMENTS

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "settlement", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def restart(self) -> None:
        """Nowe Centrum na tych samych plikach i Ustawieniach taty, gdy skończy się przejście kolejki poprzedniego.

        Jak w nowym procesie kolejka poprzedniego Centrum już nic nie robi: kolejka, która zastałaby jej przejście na
        tym samym folderze, oddałaby jej swoje (``outbox._claimed``), więc ponowny start czeka na koniec tego
        przejścia, a budziki poprzedniego Centrum (ponowienie kolejki za ``RETRY_S``) już nie dzwonią, choć czas
        ``surroundings.clock`` biegnie dalej. Inne wątki poprzedniego Centrum mogą dalej żyć, np. Uruchomienie, które
        test trzyma (``HeldRegister``): puszczone kończy się w poprzednim Centrum i jego Logi idą jego kolejką.
        """

        join_threads_since(self.client.since, named=QUEUE_THREAD)
        self.client = _client(
            self.tmp_path,
            FakePlatform(),
            self.configuration,
            self.engines,
            self.surroundings,
            self.client.since,
        )


def settling_centrum(
    tmp_path: Path,
    *,
    include_unmapped: bool = False,
    dad_layout: bool = False,
    surroundings: Surroundings | None = None,
    register: Path | None = None,
) -> SettlingCentrum:
    """Centrum z zapamiętanym folderem okresów, w którym okres ma tylko syntetyczny Plik zbiorczy.

    ``dad_layout`` kładzie Folder okresu w ``Załączniki\\Rozliczenia 2026\\09_Wrzesień_2026\\INEA``.
    ``register``: tata wskazał też ten Rejestr zleceń, którego Przebieg rozliczeń nie czyta.
    """

    periods_directory = tmp_path / ("Załączniki" if dad_layout else "INEA")
    parent = periods_directory / "Rozliczenia 2026" / "09_Wrzesień_2026" / "INEA" if dad_layout else periods_directory
    (parent / PERIOD).mkdir(parents=True)
    write_source(parent / PERIOD / SOURCE_NAME, include_unmapped=include_unmapped)
    tool = ToolDirectory(tmp_path)
    tool.config.mkdir()
    configuration = tool.configuration
    write_template(configuration.worker_template)
    write_mapping(configuration.worker_config)
    engines = Engines(tool.metrics)
    surroundings = surroundings or Surroundings()
    platform = FakePlatform(chosen_files=[register], chosen_folders=[periods_directory])
    client = _client(tmp_path, platform, configuration, engines, surroundings)
    client.post("/api/settings/periods-directory/choose")
    if register is not None:
        client.post("/api/settings/register/choose")
    return SettlingCentrum(
        client,
        periods_directory,
        engines.metrics.settlement,
        tool.log_path,
        parent,
        configuration,
        tmp_path,
        surroundings,
        engines,
    )


def write_configuration(tool: ToolDirectory) -> ConfigurationFiles:
    """Trzy syntetyczne Wzorce i Konfiguracja wykonawców w folderze ``config`` katalogu narzędzia ``tool``."""

    files = tool.configuration
    tool.config.mkdir(parents=True, exist_ok=True)
    write_mapping(files.worker_config)
    write_internal_template(files.internal_template)
    write_collective_template(files.collective_template)
    write_template(files.worker_template)
    return files


def settling_app(tmp_path: Path, surroundings: Surroundings) -> FastAPI:
    """Aplikacja Centrum na plikach, które ``settling_centrum`` założył w ``tmp_path`` (Ustawienia taty, wzorce, metryki
    i katalog Logów), bez klienta testu: tak startuje Centrum w osobnym procesie (``centrum_w_procesie``)."""

    tool = ToolDirectory(tmp_path)
    return _app(tmp_path, FakePlatform(), tool.configuration, Engines(tool.metrics), surroundings)


class _Starting(Protocol):
    @property
    def client(self) -> TestClient: ...

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any: ...


def run_to_end(centrum: _Starting, *, dry_run: bool) -> dict[str, Any]:
    started = centrum.start(dry_run=dry_run)
    assert started.status_code == 200, started.json()
    return finished_view(centrum.client)


def stopped_for_maks(centrum: PreparingCentrum | SettlingCentrum) -> str:
    """Zatrzymanie „do Maksa” bez zmiany plików: podgląd, którego planu nie da się pokazać; zwraca id Uruchomienia."""

    centrum.engines.fail_summary = True
    try:
        view = run_to_end(centrum, dry_run=True)
    finally:
        centrum.engines.fail_summary = False
    assert view["result"]["stop_kind"] == "for_maks"
    run_logs_handled(centrum)
    return str(view["run"]["id"])


def run_logs_handled(centrum: PreparingCentrum | SettlingCentrum) -> None:
    """Czeka na wpis wątku kolejki, że Logi Uruchomienia poszły albo czekają; przychodzi w tle, po wyniku.

    Rozpoznaje tylko pierwsze Uruchomienie tej pracy Centrum: po kolejnych wystarczyłby mu wpis poprzedniego.
    """

    def handled() -> bool:
        log = centrum.log_path.read_text(encoding="utf-8")
        return any(f"{entry} etykieta=logi-uruchomienia" in log for entry in ("skrzynka-wyslano", "skrzynka-czeka"))

    assert wait_for(handled), "wątek kolejki nie obsłużył Logów Uruchomienia"
