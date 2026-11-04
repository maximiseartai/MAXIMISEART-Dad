"""Wycena w efenix z Centrum rozliczeń: wybór okresu z Plikiem zbiorczym, okno efenix taty i wejście procesu.

Do wyboru są okresy, które mają Plik zbiorczy (Status okresu „Plik zbiorczy przygotowany” albo „Rozliczenia
pracowników gotowe”); Plik zbiorczy wynika z folderu okresów i okresu, a Status okresu się nie zmienia. Wycena w efenix
nie ma Podglądu bez zapisu, więc start bez zapisu jest odrzucony. Okno efenix (``EfenixWindow``) to w Centrum taty
widoczne okno zainstalowanego Google Chrome w trwałym profilu narzędzia (``efenix_browser.default_profile``), w którym
proces czeka, aż tata się zaloguje i pracuje w tempie ludzkim, a Ślad Wyceny Emmetta leży w ``config/`` narzędzia; testy
i weryfikacja podają Chromium Playwrighta, adres Atrapy efenix, własny folder śladu i okno bez tempa. Wejście procesu ma
dziennik Wyceny w efenix Centrum (``pricing_journal``), który przeżywa nagłe zgaśnięcie Centrum.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from rozliczenia import efenix_browser, efenix_emmett_trace
from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import EFENIX
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.period_board import located_period_folder, observed_period_folder, read_board, requested_period
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.runs import PreparedRun
from rozliczenia.client_data import ForbiddenValues
from rozliczenia.efenix_pace import Pace
from rozliczenia.efenix_pricing import OpenEfenix, OrderJournal
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.period_folder import PeriodStatus, collective_file_name, scan_period_folders
from rozliczenia.settings import SettingsStore
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period

_VIEW: Final = EFENIX.view
_ELIGIBLE: Final[frozenset[PeriodStatus]] = frozenset({"collective_file_prepared", "worker_settlements_ready"})
_NO_PREVIEW: Final = "Wycena w efenix nie ma podglądu bez zapisu. Uruchom ją przyciskiem „Uruchom”."
EFENIX_URL: Final = "https://efenix.pl/index.php"
"""Lista zleceń prawdziwego efenix, którą otwiera tylko Centrum taty; testy i weryfikacja podają adres Atrapy efenix."""


@dataclass(frozen=True)
class EfenixWindow:
    """Okno efenix, które Centrum otwiera dla Wyceny w efenix: adres listy zleceń, profil, przeglądarka, folder Śladów
    Wyceny Emmetta (``efenix_emmett_trace``) i tempo ludzkie (``efenix_pace``).

    ``channel`` ``"chrome"`` to zainstalowany Google Chrome, ``None`` Chromium Playwrighta; ``headless`` i ``arguments``
    są tylko dla testów i weryfikacji, które nie mają ekranu, a ``pace`` ``None`` (bez przerw) tylko dla Atrapy efenix.
    """

    url: str
    profile: Path
    trace_directory: Path
    channel: str | None = "chrome"
    headless: bool = False
    arguments: tuple[str, ...] = ()
    pace: Pace | None = Pace()

    @classmethod
    def of_tata(cls) -> EfenixWindow:
        """Widoczne okno Google Chrome taty w profilu narzędzia z prawdziwym efenix, w tempie ludzkim, ze Śladem Wyceny
        Emmetta w ``config/`` narzędzia."""

        return cls(EFENIX_URL, efenix_browser.default_profile(), efenix_emmett_trace.default_directory())

    def opener(self) -> OpenEfenix:
        return lambda login: efenix_browser.chrome(
            self.url, self.profile, login, channel=self.channel, headless=self.headless, arguments=self.arguments
        )


@dataclass(frozen=True)
class EfenixEntry:
    """Wycena w efenix jako proces uruchamiany z Centrum (``runs.ProcessEntry``) z dziennikiem ``journal``."""

    store: SettingsStore
    processes: Processes
    today: Callable[[], date]
    window: EfenixWindow
    journal: OrderJournal
    forbidden: ForbiddenValues

    @property
    def key(self) -> contract.PeriodProcessKey:
        return EFENIX.key

    def setup(self) -> contract.ProcessSetup:
        settings = self.store.load()
        periods_directory = settings.periods_directory
        board = read_board(periods_directory, self.today(), self.processes)
        rows = [row for row in board.periods if row.status in _ELIGIBLE] if board.state == "ready" else []
        preselected = next(
            (row.token for row in rows if row.last_complete),
            rows[0].token if rows else last_complete_period(self.today()).token,
        )
        collective_files = _collective_files(periods_directory, rows) if periods_directory is not None else {}
        return contract.ProcessSetup(
            process=self.key,
            title=EFENIX.title,
            creates="Wyceny zleceń i Znaczniki efenix",
            reminder=_VIEW.reminder,
            confirms_readiness=_VIEW.confirms_readiness,
            preview_hint=None,
            periods=[_choice(row, collective_files[row.token]) for row in rows],
            preselected_period=preselected,
            blocker=EFENIX.settings_blocker(settings) or _blocker(board, rows),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        periods_directory = EFENIX.required_paths(self.store.load())["periods_directory"]
        if request.dry_run:
            raise contract.Refusal(409, _NO_PREVIEW)
        period = requested_period(request.period)
        source = located_period_folder(periods_directory, period).collective_file
        inputs = EfenixInputs(
            source,
            self.window.opener(),
            self.window.pace,
            self.window.trace_directory,
            journal=self.journal,
            forbidden=self.forbidden,
        )
        return PreparedRun(declaration=EFENIX, period=period.token, process=EFENIX.core(self.processes), inputs=inputs)


def _collective_files(periods_directory: Path, rows: list[contract.PeriodRow]) -> dict[str, Path]:
    folders = scan_period_folders(periods_directory)
    return {row.token: observed_period_folder(folders, SettlementPeriod(row.tuesday)).collective_file for row in rows}


def _choice(row: contract.PeriodRow, collective_file: Path) -> contract.PeriodChoice:
    open_collective = open_in_excel([InputWorkbook("Plik zbiorczy", collective_file, "data_file")])
    return contract.PeriodChoice(
        token=row.token,
        tuesday=row.tuesday,
        monday=row.monday,
        status_label=row.status_label,
        last_complete=row.last_complete,
        previewed=False,
        collective_file=collective_file_name(SettlementPeriod(row.tuesday)),
        open_in_excel=open_collective,
        reminder=_VIEW.start_reminder(data_file_open=bool(open_collective), template_open=False),
    )


def _blocker(board: contract.PeriodBoard, rows: list[contract.PeriodRow]) -> str | None:
    if board.state == "missing":
        return f"Nie ma już folderu okresów {board.name}. Wskaż go ponownie."
    if not rows:
        return "Żaden okres nie ma Pliku zbiorczego. Najpierw przygotuj plik zbiorczy."
    return None
