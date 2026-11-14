"""Przygotowanie pliku zbiorczego w katalogu procesów: wpis i widok Uruchomienia."""

from __future__ import annotations

from typing import Final

from rozliczenia import preparation_messages, preparation_process
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import (
    PERIODS_DIRECTORY,
    TAIL,
    HostParts,
    NeededSetting,
    PeriodFolderCheck,
    PeriodProcessKind,
    PeriodStart,
    RecentWeeks,
    Start,
)
from rozliczenia.centrum.run_view import PeriodProcessView, count_figure, elapsed_figure
from rozliczenia.collective_preparation import PreparationInputs, PreparationSummary
from rozliczenia.period_folder import period_status_label
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.tool_files import PREPARATION_METRICS


def _figures(snapshot: ProgressSnapshot, _dry_run: bool) -> list[runs_contract.Figure]:
    return [count_figure("Ostrzeżenia", snapshot.issue_count), elapsed_figure(snapshot)]


def _summary(summary: PreparationSummary, _dry_run: bool) -> runs_contract.RunSummary:
    return runs_contract.RunSummary(
        figures=[
            count_figure("Zlecenia okresu", summary.period_order_count),
            count_figure("Zlecenia skuteczne", summary.successful_order_count),
            count_figure("Pominięte puste wiersze", summary.skipped_empty_rows),
        ],
        counts=runs_contract.CountGroup(
            title="Zlecenia na dzień",
            counts=[
                runs_contract.Count(label=label, count=count) for label, count in summary.labeled_orders_per_day()
            ],
        ),
        files=[
            runs_contract.PeriodFile(name=summary.internal_settlement_file.name, kind="internal_settlement"),
            runs_contract.PeriodFile(name=summary.collective_file.name, kind="collective_file"),
        ],
        worker_settlements=None,
    )


def _inputs(start: Start, _parts: HostParts) -> PreparationInputs:
    return PreparationInputs(
        start.path("register"),
        start.path("periods_directory"),
        start.token(),
        dry_run=start.dry_run,
        workers=start.worker_list(),
        internal_template_path=start.path("internal_template"),
        collective_template_path=start.path("collective_template"),
        quantity_rules=start.quantity_rules,
    )


_VIEW: Final[PeriodProcessView[PreparationSummary]] = PeriodProcessView(
    reminder="Zapisz i zamknij Rejestr zleceń w Excelu",
    confirms_readiness=False,
    preview_hint="Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
    done=period_status_label("collective_file_prepared"),
    result_action="open_collective_file",
    prepares_collective_file=True,
    _figures=_figures,
    _summary=_summary,
)
KIND: Final[PeriodProcessKind[PreparationInputs, PreparationSummary]] = PeriodProcessKind(
    key="preparation",
    short_title="Przygotowanie",
    view=_VIEW,
    core=preparation_process.PROCESS,
    default_metrics=PREPARATION_METRICS,
    needs=("register", "periods_directory", "period", "workers", "internal_template", "collective_template"),
    inputs=_inputs,
    start=PeriodStart(creates="Rozliczenie wewnętrzne i Plik zbiorczy", chooser=RecentWeeks(8)),
    settings=(
        NeededSetting(_VIEW.register_name, "register", preparation_messages.register_missing),
        PERIODS_DIRECTORY,
    ),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        "register",
        "templates",
        "worker_list",
        PeriodFolderCheck(collective_file_missing=None),
        "period_files_in_excel",
        *TAIL,
    ),
    quantity_rules=True,
)
"""Przygotowanie pliku zbiorczego w Centrum. Sprawdzenie OneDrive (``files_in_onedrive``) idzie przed sprawdzeniami,
które otwierają Rejestr zleceń, Wzorce i pliki okresu: plik tylko w chmurze może się nie otworzyć, a wtedy przyczyną
jest OneDrive, nie uszkodzony plik."""
