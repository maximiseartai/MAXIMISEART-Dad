"""Karta przed startem i start procesu z okresem w Centrum rozliczeń: jedna mechanika, polityka z wpisu procesu.

Każdy proces z okresem (``process_kind.PeriodProcessKind``) ma na karcie Uruchomień kafelek z okresami do wyboru, a
start z okresem przechodzi przez te same odmowy dla taty w tej samej kolejności. Co różni procesy (co powstaje, jak
wybrać okresy, odmowa podglądu), mówi ``PeriodStart`` wpisu. Pliki wejścia biorą się z Ustawień Centrum, Folderu okresu i
Konfiguracji, a Lista Wykonawców z migawki Ustawień Centrum; tata nie wskazuje ich przy starcie.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final, assert_never

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import periods as periods_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.catalog import Catalog
from rozliczenia.centrum.configuration import ConfigurationFiles, InputWorkbook, open_in_excel
from rozliczenia.centrum.metrics import previewed_periods
from rozliczenia.centrum.period_board import located_period_folder, observed_period_folder, read_board, requested_period
from rozliczenia.centrum.process_kind import (
    ByStatus,
    HostParts,
    PathNeed,
    PeriodProcessKind,
    PreparedRun,
    RecentWeeks,
    SettingField,
    start_from_settings,
)
from rozliczenia.centrum.settings.folders import FolderSettings
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.period_folder import PeriodFolders, collective_file_name, period_status_label, scan_period_folders
from rozliczenia.run_context import RunContexts
from rozliczenia.settlement_period import SettlementPeriod, last_complete_period

_TILES: Final[tuple[common_contract.PeriodProcessKey, ...]] = ("preparation", "efenix", "settlement")
"""Kafelek Wyceny w efenix stoi przed Przebiegiem rozliczeń, bo w tej kolejności tata pracuje."""


@dataclass(frozen=True)
class PeriodStarts:
    settings: CentrumSettings
    configuration: ConfigurationFiles
    catalog: Catalog
    today: Callable[[], date]
    contexts: RunContexts
    parts: HostParts

    def setup(self) -> runs_contract.RunSetup:
        settings = self.settings.snapshot().folders
        return runs_contract.RunSetup(processes=[self._setup(self.catalog.period_kind(key), settings) for key in _TILES])

    def prepare(self, request: runs_contract.RunRequest) -> PreparedRun[Any, Any]:
        """Uruchomienie z karty: ``Refusal``, gdy tata czegoś jeszcze nie wskazał albo wybrał coś, czego nie ma."""

        kind = self.catalog.period_kind(request.process)
        if request.pricing not in (kind.view.pricing_modes or (runs_contract.DEFAULT_PRICING,)):
            raise refusal.no_forwarding(kind.title)
        snapshot = self.settings.snapshot()
        folders = snapshot.folders
        chosen = kind.required_paths(folders)
        if request.mode.dry_run and kind.start.no_preview is not None:
            raise kind.start.no_preview
        period = requested_period(request.period)
        start = start_from_settings(
            kind, snapshot, {need: self._path(need, chosen, period) for need in kind.path_needs},
            period=period.token, dry_run=request.mode.dry_run,
            pricing=request.pricing if kind.view.pricing_modes else None,
        )
        return self.catalog.prepared(kind.key, start, self.parts, self.contexts.new())

    def _path(self, need: PathNeed, chosen: Mapping[SettingField, Path], period: SettlementPeriod) -> Path:
        match need:
            case "register" | "periods_directory":
                return chosen[need]
            case "collective_file":
                return located_period_folder(chosen["periods_directory"], period).collective_file
            case "internal_template" | "collective_template" | "worker_template":
                return self.configuration.path(need)
            case "copies_directory":
                raise ValueError("Kopie INTERMAX ma tylko Uporządkowanie INTERMAX, które nie ma okresu (ADR 0019)")
            case _:
                assert_never(need)

    def _setup(self, kind: PeriodProcessKind[Any, Any], settings: FolderSettings) -> runs_contract.ProcessSetup:
        view = kind.view
        open_templates = open_in_excel(self.configuration.template_inputs(kind.templates))
        previewed = previewed_periods(self.catalog.metrics(kind.key)) if kind.preview_hint is not None else frozenset()
        chooser = kind.start.chooser
        match chooser:
            case ByStatus():
                board = read_board(settings.periods_directory, self.today(), self.catalog)
                rows = [row for row in board.periods if row.status in chooser.statuses] if board.state == "ready" else []
                files = _collective_files(settings.periods_directory, rows)
                periods = [_board_choice(kind, row, files[row.token], row.token in previewed, open_templates) for row in rows]
                preselected = next(
                    (row.token for row in rows if row.last_complete),
                    rows[0].token if rows else last_complete_period(self.today()).token,
                )
                blocker = _board_blocker(board, rows, chooser)
            case RecentWeeks():
                last_complete = last_complete_period(self.today())
                recent = [SettlementPeriod(last_complete.tuesday - timedelta(weeks=week)) for week in range(chooser.weeks)]
                folders = None if settings.periods_directory is None else scan_period_folders(settings.periods_directory)
                register = settings.register
                open_register = [] if register is None else open_in_excel([InputWorkbook(view.register_name, register, "data_file")])
                reminder = view.start_reminder(data_file_open=bool(open_register), template_open=bool(open_templates))
                periods = [
                    _recent_choice(
                        folders,
                        period,
                        last_complete=period == last_complete,
                        previewed=period.token in previewed,
                        open_files=open_register + open_templates,
                        reminder=reminder,
                    )
                    for period in recent
                ]
                preselected = last_complete.token
                blocker = None
            case _:
                assert_never(chooser)
        return runs_contract.ProcessSetup(
            process=kind.key,
            title=kind.title,
            creates=kind.start.creates,
            reads="register" if kind.reads_register else "collective_file",
            reminder=view.reminder,
            confirms_readiness=view.confirms_readiness,
            preview_hint=kind.preview_hint,
            pricing_modes=list(view.pricing_modes),
            periods=periods,
            preselected_period=preselected,
            blocker=kind.settings_blocker(settings) or blocker,
        )


def _collective_files(periods_directory: Path | None, rows: list[periods_contract.PeriodRow]) -> dict[str, Path]:
    """Plik zbiorczy każdego okresu do wyboru, w tym Folderze okresu, który pokazuje Tablica okresów."""

    if periods_directory is None:
        return {}
    folders = scan_period_folders(periods_directory)
    return {row.token: observed_period_folder(folders, SettlementPeriod(row.tuesday)).collective_file for row in rows}


def _board_choice(
    kind: PeriodProcessKind[Any, Any],
    row: periods_contract.PeriodRow,
    collective_file: Path,
    previewed: bool,
    open_templates: list[str],
) -> runs_contract.PeriodChoice:
    open_collective = open_in_excel([InputWorkbook("Plik zbiorczy", collective_file, "data_file")])
    return runs_contract.PeriodChoice(
        token=row.token,
        tuesday=row.tuesday,
        monday=row.monday,
        status_label=row.status_label,
        last_complete=row.last_complete,
        previewed=previewed,
        collective_file=collective_file_name(SettlementPeriod(row.tuesday)),
        open_in_excel=open_collective + open_templates,
        reminder=kind.view.start_reminder(data_file_open=bool(open_collective), template_open=bool(open_templates)),
    )


def _board_blocker(board: periods_contract.PeriodBoard, rows: list[periods_contract.PeriodRow], chooser: ByStatus) -> str | None:
    """Czego brakuje w folderze okresów, który Ustawienia Centrum już wskazują."""

    if board.state == "missing":
        return f"Nie ma już folderu okresów {board.name}. Wskaż go ponownie."
    if not rows:
        return chooser.none_ready
    return None


def _recent_choice(
    folders: PeriodFolders | None,
    period: SettlementPeriod,
    *,
    last_complete: bool,
    previewed: bool,
    open_files: list[str],
    reminder: str | None,
) -> runs_contract.PeriodChoice:
    status = observed_period_folder(folders, period).observe().status if folders is not None else "no_period_files"
    return runs_contract.PeriodChoice(
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
