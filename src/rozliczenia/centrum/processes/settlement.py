"""Przebieg rozliczeń w katalogu procesów: wpis i widok Uruchomienia."""

from __future__ import annotations

from typing import Final

from rozliczenia import settlement_messages, settlement_process
from rozliczenia.centrum import contract
from rozliczenia.centrum.process_kind import PERIODS_DIRECTORY, TAIL, PeriodFolderCheck, PeriodProcessKind
from rozliczenia.centrum.run_view import PeriodProcessView, count_figure
from rozliczenia.engine import SettlementInputs, SettlementSummary
from rozliczenia.period_folder import period_status_label
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.tool_files import SETTLEMENT_METRICS

# Etykiety Przebiegu rozliczeń wspólne dla liczb na żywo i wyniku.
_ROWS: Final = "Wiersze danych"
_PLANNED: Final = "Planowane szablony"
_WRITTEN: Final = "Zapisane szablony"
_EMPTY: Final = "Puste szablony"


def _figures(snapshot: ProgressSnapshot, dry_run: bool) -> list[contract.Figure]:
    counters = snapshot.metric_counters()
    return [
        count_figure(_ROWS, snapshot.rows),
        count_figure(_PLANNED, counters["planned"]) if dry_run else count_figure(_WRITTEN, counters["written"]),
        count_figure(_EMPTY, counters["empty"]),
        count_figure("Problemy", snapshot.issue_count),
    ]


def _summary(summary: SettlementSummary, dry_run: bool) -> contract.RunSummary:
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
    return contract.RunSummary(
        figures=figures,
        counts=None,
        files=[],
        worker_settlements=[
            contract.WorkerSettlement(
                worker=result.worker_name,
                file=result.output_file.name,
                orders=result.rows,
                empty=result.status == "PUSTY_SZABLON",
            )
            for result in summary.results
        ],
    )


KIND: Final[PeriodProcessKind[SettlementInputs, SettlementSummary]] = PeriodProcessKind(
    key="settlement",
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
    settings=(PERIODS_DIRECTORY,),
    templates=("worker",),
    checks=(
        "tata_settings",
        "files_in_onedrive",
        "templates",
        "worker_config",
        PeriodFolderCheck(collective_file_missing=settlement_messages.collective_file_missing),
        "period_files_in_excel",
        *TAIL,
    ),
)
