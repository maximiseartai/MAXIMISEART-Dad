"""Przebieg rozliczeń w katalogu procesów: wpis i widok Uruchomienia."""

from __future__ import annotations

from typing import Final

from rozliczenia import quantity_check, settlement_messages, settlement_process
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import (
    PERIODS_DIRECTORY,
    TAIL,
    ByStatus,
    HostParts,
    PeriodFolderCheck,
    PeriodProcessKind,
    PeriodStart,
    Start,
)
from rozliczenia.centrum.run_logs import ProcessLogs
from rozliczenia.centrum.run_view import PeriodProcessView, count_figure
from rozliczenia.engine import SettlementInputs, SettlementSummary
from rozliczenia.period_folder import period_status_label
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.tool_files import SETTLEMENT_METRICS

_ROWS: Final = "Wiersze danych"
_PLANNED: Final = "Planowane szablony"
_WRITTEN: Final = "Zapisane szablony"
_EMPTY: Final = "Puste szablony"


def _figures(snapshot: ProgressSnapshot, dry_run: bool) -> list[runs_contract.Figure]:
    counts = snapshot.operation_counts
    return [
        count_figure(_ROWS, snapshot.rows),
        count_figure(_PLANNED, counts.get("PLAN", 0)) if dry_run else count_figure(_WRITTEN, counts.get("ZAPISANO", 0)),
        count_figure(_EMPTY, counts.get("PUSTY_SZABLON", 0)),
        count_figure("Problemy", snapshot.issue_count),
    ]


def _summary(summary: SettlementSummary, dry_run: bool) -> runs_contract.RunSummary:
    figures = (
        [
            count_figure(_ROWS, summary.total_rows),
            count_figure(_PLANNED, summary.planned_count),
            count_figure(_EMPTY, summary.empty_count),
        ]
        if dry_run
        else [
            count_figure(_WRITTEN, summary.written_count),
            count_figure(_EMPTY, summary.empty_count),
        ]
    )
    return runs_contract.RunSummary(
        figures=figures,
        counts=None,
        files=[],
        worker_settlements=[
            runs_contract.WorkerSettlement(
                worker=result.worker_name,
                file=result.output_file.name,
                orders=result.rows,
                empty=result.status == "PUSTY_SZABLON",
            )
            for result in summary.results
        ],
    )


def _logs(summary: SettlementSummary | None, _facts: object) -> ProcessLogs:
    return ProcessLogs(
        inea_only_cleared=None
        if summary is None
        else dict(summary.inea_only_cleared)
    )


def _quantity_check(summary: SettlementSummary) -> quantity_check.CheckResult:
    return quantity_check.check(summary.orders, summary.quantity_rules)


def _inputs(start: Start, _parts: HostParts) -> SettlementInputs:
    return SettlementInputs(
        start.path("collective_file"),
        dry_run=start.dry_run,
        workers=start.worker_list(),
        worker_template_path=start.path("worker_template"),
        quantity_rules=start.quantity_rules,
    )


KIND: Final[PeriodProcessKind[SettlementInputs, SettlementSummary]] = PeriodProcessKind(
    key="settlement",
    short_title="Przebieg",
    view=PeriodProcessView(
        reminder="Zapisz i zamknij Plik zbiorczy w Excelu",
        confirms_readiness=True,
        preview_hint="Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
        done=period_status_label("worker_settlements_ready"),
        result_action="open_worker_settlements_folder",
        _figures=_figures,
        _summary=_summary,
    ),
    core=settlement_process.PROCESS,
    default_metrics=SETTLEMENT_METRICS,
    needs=("collective_file", "workers", "worker_template"),
    inputs=_inputs,
    start=PeriodStart(
        creates="Rozliczenia pracowników",
        chooser=ByStatus(
            frozenset({"collective_file_prepared"}),
            f"Żaden okres nie ma Statusu „{period_status_label('collective_file_prepared')}”. "
            "Najpierw przygotuj plik zbiorczy.",
        ),
    ),
    settings=(PERIODS_DIRECTORY,),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        "templates",
        "worker_list",
        PeriodFolderCheck(collective_file_missing=settlement_messages.collective_file_missing),
        "period_files_in_excel",
        *TAIL,
    ),
    logs=_logs,
    quantity_check=_quantity_check,
    quantity_rules=True,
)
"""Przebieg rozliczeń w Centrum. Kliknięcie „Uruchom” jest potwierdzeniem Gotowości Pliku zbiorczego
(``confirms_readiness``): Centrum nie zgaduje jej z pliku ani nie blokuje startu."""
