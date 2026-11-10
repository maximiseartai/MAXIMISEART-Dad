"""Wpisanie raportów w katalogu procesów: wpis i widok Uruchomienia (ADR 0028).

Wpisanie raportów wpisuje Raporty wykonawców do INTERMAX z Ustawień taty i nie należy do okresu (jak Uporządkowanie
INTERMAX, ADR 0019); folder okresów z Ustawień czyta tylko po to, by pominąć dni okresów z Plikiem zbiorczym. Skrzynkę raportów i pamięć własnych wpisów daje gospodarz (``HostParts.reports``).
"""

from __future__ import annotations

from functools import partial
from typing import Final

from rozliczenia import intermax_messages, report_entering_process
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.process_kind import TAIL, HostParts, NeededSetting, ProcessKind, Start
from rozliczenia.centrum.run_logs import LoggedReports, ProcessLogs
from rozliczenia.centrum.run_view import ProcessView, count_figure, elapsed_only
from rozliczenia.report_entering import EnteringFacts, EnteringInputs, EnteringSummary
from rozliczenia.tool_files import REPORT_ENTERING_METRICS


def _summary(summary: EnteringSummary, _dry_run: bool) -> runs_contract.RunSummary:
    return runs_contract.RunSummary(
        figures=[
            count_figure("Wpisane", summary.entered),
            count_figure("Problemy", len(summary.facts.problems)),
            count_figure("Raporty", summary.reports),
        ],
        counts=None,
        files=[],
        worker_settlements=None,
    )


def _logs(summary: EnteringSummary | None, facts: object) -> ProcessLogs:
    if summary is not None:
        return ProcessLogs(report_entering=LoggedReports.of(summary.facts, summary.written))
    if isinstance(facts, EnteringSummary):
        return ProcessLogs(report_entering=LoggedReports.of(facts.facts, facts.written))
    if isinstance(facts, EnteringFacts):
        return ProcessLogs(report_entering=LoggedReports.of(facts, None))
    return ProcessLogs()


def _inputs(start: Start, parts: HostParts) -> EnteringInputs:
    return EnteringInputs(
        start.path("register"),
        start.path("periods_directory"),
        start.path("worker_config"),
        start.path("worker_addresses"),
        parts.report_entering(),
        now=parts.now,
        waiting=parts.waiting,
        disk=parts.disk,
    )


_VIEW: Final[ProcessView[EnteringSummary]] = ProcessView(
    reminder="Zapisz i zamknij INTERMAX w Excelu",
    confirms_readiness=False,
    done="Raporty wpisane",
    result_action="open_order_register",
    register_name="INTERMAX",
    _figures=elapsed_only,
    _summary=_summary,
)
KIND: Final[ProcessKind[EnteringInputs, EnteringSummary]] = ProcessKind(
    key="report_entering",
    short_title="Raporty",
    view=_VIEW,
    core=report_entering_process.PROCESS,
    default_metrics=REPORT_ENTERING_METRICS,
    needs=("register", "periods_directory", "worker_config", "worker_addresses", "worker_report_inbox"),
    inputs=_inputs,
    settings=(
        NeededSetting(
            _VIEW.register_name,
            "register",
            partial(intermax_messages.register_missing, replacement=intermax_messages.ENTERING),
        ),
    ),
    checks=("tata_settings", "files_in_onedrive", "intermax", "worker_config", *TAIL),
    logs=_logs,
)
