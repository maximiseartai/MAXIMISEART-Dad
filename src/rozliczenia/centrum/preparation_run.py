"""Przygotowanie pliku zbiorczego z Centrum rozliczeń: wybór okresu, wejście procesu z ustawień i wynik.

Rejestr zleceń i folder okresów pochodzą z ustawień, okres z listy ostatnich
pełnych okresów.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.catalog import PREPARATION
from rozliczenia.centrum.configuration import ConfigurationFiles, InputWorkbook, open_in_excel
from rozliczenia.centrum.metrics import previewed_periods
from rozliczenia.centrum.period_board import observed_period_folder, requested_period
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.runs import PreparedRun
from rozliczenia.client_data import ForbiddenValues
from rozliczenia.input_copy import InputCopy
from rozliczenia.centrum.settings import SettingsStore
from rozliczenia.period_folder import PeriodFolders, period_status_label, scan_period_folders
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.input_checks import Readers
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period
from rozliczenia.telemetry import MetricsStore

_VIEW: Final = run_view.PREPARATION
_CHOSEN_WEEKS: Final = 8


@dataclass(frozen=True)
class PreparationEntry:
    """Przygotowanie pliku zbiorczego jako proces uruchamiany z Centrum (``runs.ProcessEntry``)."""

    store: SettingsStore
    configuration: ConfigurationFiles
    processes: Processes
    today: Callable[[], date]
    readers: Readers
    forbidden: ForbiddenValues

    @property
    def key(self) -> contract.PeriodProcessKey:
        return PREPARATION.key

    def setup(self) -> contract.ProcessSetup:
        settings = self.store.load()
        last_complete = last_complete_period(self.today())
        periods = [SettlementPeriod(last_complete.tuesday - timedelta(weeks=week)) for week in range(_CHOSEN_WEEKS)]
        process = PREPARATION.core(self.processes)
        previewed = previewed_periods(MetricsStore(process.metrics_path(), process.counter_names))
        folders = scan_period_folders(settings.periods_directory) if settings.periods_directory is not None else None
        register = [] if settings.register is None else [InputWorkbook("Rejestr zleceń", settings.register, "data_file")]
        open_register = open_in_excel(register)
        open_templates = open_in_excel(self.configuration.template_inputs(PREPARATION.templates))
        return contract.ProcessSetup(
            process=self.key,
            title=PREPARATION.title,
            creates="Rozliczenie wewnętrzne i Plik zbiorczy",
            reminder=_VIEW.reminder,
            confirms_readiness=_VIEW.confirms_readiness,
            preview_hint=_VIEW.preview_hint,
            periods=[
                _choice(
                    folders,
                    period,
                    last_complete=period == last_complete,
                    previewed=period.token in previewed,
                    open_files=open_register + open_templates,
                    reminder=_VIEW.start_reminder(data_file_open=bool(open_register), template_open=bool(open_templates)),
                )
                for period in periods
            ],
            preselected_period=last_complete.token,
            blocker=PREPARATION.settings_blocker(settings),
        )

    def prepare(self, request: contract.RunRequest) -> PreparedRun[Any, Any]:
        paths = PREPARATION.required_paths(self.store.load())
        period = requested_period(request.period).token
        copy = InputCopy()
        inputs = PreparationInputs(
            paths["register"],
            paths["periods_directory"],
            period,
            dry_run=request.dry_run,
            config_path=self.configuration.worker_config,
            internal_template_path=self.configuration.internal_template,
            collective_template_path=self.configuration.collective_template,
            readers=self.readers,
            forbidden=self.forbidden,
            copy=copy,
        )
        return PreparedRun(
            declaration=PREPARATION,
            period=period,
            process=PREPARATION.core(self.processes),
            inputs=inputs,
            input_copy=copy,
        )


def _choice(
    folders: PeriodFolders | None,
    period: SettlementPeriod,
    *,
    last_complete: bool,
    previewed: bool,
    open_files: list[str],
    reminder: str | None,
) -> contract.PeriodChoice:
    status = observed_period_folder(folders, period).observe().status if folders is not None else "no_period_files"
    return contract.PeriodChoice(
        token=period.token,
        tuesday=period.tuesday,
        monday=period.monday,
        status_label=period_status_label(status),
        last_complete=last_complete,
        previewed=previewed,
        collective_file=None,
        open_in_excel=open_files,
        reminder=reminder,
    )

