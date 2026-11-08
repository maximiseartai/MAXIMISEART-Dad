"""Przebieg rozliczeń z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Plik zbiorczy wynika z folderu okresów i okresu; tata go nie wskazuje. Do
wyboru są okresy ze Statusem okresu „Plik zbiorczy przygotowany”. Kliknięcie
„Uruchom” jest potwierdzeniem Gotowości: Centrum nie zgaduje jej z pliku ani
nie blokuje startu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.catalog import SETTLEMENT
from rozliczenia.centrum.configuration import ConfigurationFiles, InputWorkbook, open_in_excel
from rozliczenia.centrum.metrics import previewed_periods
from rozliczenia.centrum.period_board import located_period_folder, observed_period_folder, read_board, requested_period
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.process_kind import PreparedRun
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.period_folder import PeriodStatus, collective_file_name, period_status_label, scan_period_folders
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period
from rozliczenia.run_context import RunContexts
from rozliczenia.telemetry import MetricsStore
from rozliczenia.engine import SettlementInputs

_VIEW: Final = run_view.SETTLEMENT
_ELIGIBLE: Final[PeriodStatus] = "collective_file_prepared"


@dataclass(frozen=True)
class SettlementEntry:
    """Przebieg rozliczeń jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    processes: Processes
    today: Callable[[], date]
    contexts: RunContexts

    @property
    def key(self) -> contract.PeriodProcessKey:
        return SETTLEMENT.key

    def setup(self) -> contract.ProcessSetup:
        settings = self.store.load()
        periods_directory = settings.periods_directory
        board = read_board(periods_directory, self.today(), self.processes)
        rows = [row for row in board.periods if row.status == _ELIGIBLE] if board.state == "ready" else []
        preselected = next(
            (row.token for row in rows if row.last_complete),
            rows[0].token if rows else last_complete_period(self.today()).token,
        )
        process = SETTLEMENT.core(self.processes)
        previewed = previewed_periods(MetricsStore(process.metrics_path(), process.counter_names))
        collective_files = _collective_files(periods_directory, rows) if periods_directory is not None else {}
        open_templates = open_in_excel(self.configuration.template_inputs(SETTLEMENT.templates))
        return contract.ProcessSetup(
            process=self.key,
            title=SETTLEMENT.title,
            creates="Rozliczenia pracowników",
            reminder=_VIEW.reminder,
            confirms_readiness=_VIEW.confirms_readiness,
            preview_hint=_VIEW.preview_hint,
            pricing_modes=list(_VIEW.pricing_modes),
            periods=[
                _choice(
                    row,
                    previewed=row.token in previewed,
                    open_collective=open_in_excel(
                        [InputWorkbook("Plik zbiorczy", collective_files[row.token], "data_file")]
                    ),
                    open_templates=open_templates,
                )
                for row in rows
            ],
            preselected_period=preselected,
            blocker=SETTLEMENT.settings_blocker(settings) or _blocker(board, rows),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        periods_directory = SETTLEMENT.required_paths(self.store.load())["periods_directory"]
        period = requested_period(request.period)
        source = located_period_folder(periods_directory, period).collective_file
        inputs = SettlementInputs(
            source,
            dry_run=request.dry_run,
            config_path=self.configuration.worker_config,
            worker_template_path=self.configuration.worker_template,
        )
        return PreparedRun(
            declaration=SETTLEMENT,
            period=period.token,
            process=SETTLEMENT.core(self.processes),
            inputs=inputs,
            context=self.contexts.new(),
        )


def _collective_files(periods_directory: Path, rows: list[contract.PeriodRow]) -> dict[str, Path]:
    """Plik zbiorczy każdego okresu do wyboru, w tym Folderze okresu, który pokazuje Tablica okresów."""

    folders = scan_period_folders(periods_directory)
    return {row.token: observed_period_folder(folders, SettlementPeriod(row.tuesday)).collective_file for row in rows}


def _choice(
    row: contract.PeriodRow, *, previewed: bool, open_collective: list[str], open_templates: list[str]
) -> contract.PeriodChoice:
    return contract.PeriodChoice(
        token=row.token,
        tuesday=row.tuesday,
        monday=row.monday,
        status_label=row.status_label,
        last_complete=row.last_complete,
        previewed=previewed,
        collective_file=collective_file_name(SettlementPeriod(row.tuesday)),
        open_in_excel=open_collective + open_templates,
        reminder=_VIEW.start_reminder(data_file_open=bool(open_collective), template_open=bool(open_templates)),
    )


def _blocker(board: contract.PeriodBoard, rows: list[contract.PeriodRow]) -> str | None:
    """Czego brakuje w folderze okresów, który Ustawienia taty już wskazują."""

    if board.state == "missing":
        return f"Nie ma już folderu okresów {board.name}. Wskaż go ponownie."
    if not rows:
        return f"Żaden okres nie ma Statusu „{period_status_label(_ELIGIBLE)}”. Najpierw przygotuj plik zbiorczy."
    return None

