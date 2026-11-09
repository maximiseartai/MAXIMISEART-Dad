"""Uporządkowanie INTERMAX w katalogu procesów: wpis i widok Uruchomienia.

Uporządkowanie porządkuje dzień, nie okres (ADR 0019): czyta tylko INTERMAX z Ustawień taty.
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rozliczenia import intermax_messages, intermax_process
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import TAIL, HostParts, NeededSetting, ProcessKind, Start
from rozliczenia.centrum.run_logs import LoggedEntries, ProcessLogs
from rozliczenia.centrum.run_view import ProcessView, count_figure, elapsed_only
from rozliczenia.intermax_ordering import OrderingInputs, OrderingSummary
from rozliczenia.text import day_label
from rozliczenia.tool_files import INTERMAX_METRICS


def _summary(summary: OrderingSummary, _dry_run: bool) -> runs_contract.RunSummary:
    return runs_contract.RunSummary(
        figures=[count_figure("Zlecenia", summary.order_count), count_figure("Wykonawcy", summary.worker_count)],
        counts=runs_contract.CountGroup(
            title="Uporządkowany dzień",
            counts=[runs_contract.Count(label=day_label(summary.day), count=summary.order_count)],
        ),
        files=[],
        worker_settlements=None,
        intermax_copy=summary.copy_name,
    )


def _logs(summary: OrderingSummary | None, _facts: object) -> ProcessLogs:
    return ProcessLogs(intermax_entries=None if summary is None else LoggedEntries.of(summary))


def _inputs(start: Start, parts: HostParts) -> OrderingInputs:
    return OrderingInputs(
        start.path("register"), start.path("copies_directory"), now=parts.now, waiting=parts.waiting, disk=parts.disk
    )


_VIEW: Final[ProcessView[OrderingInputs, OrderingSummary]] = ProcessView(
    reminder="Zapisz i zamknij INTERMAX w Excelu",
    confirms_readiness=False,
    done="INTERMAX uporządkowany",
    result_action="open_order_register",
    register_name="INTERMAX",
    _figures=elapsed_only,
    _summary=_summary,
)
KIND: Final[ProcessKind[OrderingInputs, OrderingSummary]] = ProcessKind(
    key="intermax",
    short_title="INTERMAX",
    view=_VIEW,
    core=intermax_process.PROCESS,
    default_metrics=INTERMAX_METRICS,
    needs=("register", "copies_directory"),
    inputs=_inputs,
    settings=(
        NeededSetting(
            _VIEW.register_name,
            "register",
            partial(intermax_messages.register_missing, replacement=intermax_messages.ORDERING),
        ),
    ),
    checks=("tata_settings", "files_in_onedrive", "intermax", *TAIL),
    logs=_logs,
)
