"""Logi Uruchomienia (``run_logs.RunLog``) z wyniku pracy Centrum: z Uruchomienia, które doszło do działań po wyniku
(``runs.EndedRun``), i z Diagnozy jego Zatrzymania (``diagnosis.Diagnosis``).

Tylko ten moduł Logów zna gospodarza Uruchomień i Diagnozę, więc schemat Logów, który czytają karta z Logów, plik i
odtworzenie, od nich nie zależy.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rozliczenia.centrum.dad_actions import DadActions
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.run_logs import (
    SCHEMA_VERSION,
    Environment,
    Explanation,
    LoggedCheck,
    LoggedDiagnosis,
    LoggedEntries,
    LoggedInputFile,
    LoggedMessage,
    LoggedOrder,
    LoggedPhase,
    LoggedTemplate,
    LoggedWindowStop,
    RunLog,
    StartFacts,
    Tool,
)
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.efenix_pricing import PricingStopped, PricingSummary
from rozliczenia.engine import SettlementSummary
from rozliczenia.input_copy import CopiedFile
from rozliczenia.intermax_ordering import OrderingSummary


def logs_of(run: EndedRun, *, tool: Tool, environment: Environment, dad_actions: DadActions) -> RunLog:
    """Logi Uruchomienia ``run`` z narzędziem ``tool``, środowiskiem ``environment`` i działaniami taty ``dad_actions``,
    bez Diagnozy."""

    info, stopped, snapshot = run.info, run.stopped, run.snapshot
    engine_summary = None if run.shown is None else run.shown.engine_summary
    facts = None if stopped is None else stopped.stop.facts
    priced = engine_summary if isinstance(engine_summary, PricingSummary) else None
    if isinstance(facts, PricingStopped):
        priced = facts.summary
    copied = None if run.input_copy is None else run.input_copy.files()
    return RunLog(
        **dict(StartFacts.of_run(info, run.started_at)),
        schema_version=SCHEMA_VERSION,
        ended_at=run.ended_at,
        duration_ms=run.duration_ms,
        tool=tool,
        result=run.result,
        ending=run.ending,
        stop_kind=None if stopped is None else stopped.kind,
        issue_count=None if snapshot is None else snapshot.issue_count,
        messages=[LoggedMessage.of("stop", stop) for stop in run.stops]
        + [LoggedMessage.of("warning", warning) for warning in run.warnings],
        technical_notes=list(run.technical_notes),
        summary=None if run.shown is None else run.shown.summary,
        phases=LoggedPhase.all_of(run.progress.phases, snapshot),
        templates=[]
        if snapshot is None
        else [
            LoggedTemplate(
                wykonawca=template.worker_name,
                outcome=template.outcome,
                rows=template.rows,
                duration_ms=template.duration_ms,
                started_at=template.started_at,
                ended_at=template.ended_at,
            )
            for template in snapshot.templates
        ],
        inea_only_cleared={column.value: count for column, count in engine_summary.inea_only_cleared.items()}
        if isinstance(engine_summary, SettlementSummary)
        else None,
        intermax_entries=LoggedEntries.of(engine_summary) if isinstance(engine_summary, OrderingSummary) else None,
        efenix_orders=None if priced is None else LoggedOrder.all_of(priced),
        efenix_stop=LoggedWindowStop.of(facts) if isinstance(facts, PricingStopped) else None,
        environment=environment,
        trace=None if stopped is None else stopped.stop.trace,
        diagnosis=None,
        dad_actions=dad_actions,
        input_copy=None if copied is None else [LoggedInputFile.of(file) for file in copied],
        input_copy_notes=[] if copied is None else _domain_fact_notes(copied),
    )


def logged_diagnosis(diagnosis: Diagnosis, *, diagnosed_at: datetime) -> LoggedDiagnosis:
    """Diagnoza ``diagnosis`` z chwili ``diagnosed_at`` w postaci pola ``RunLog.diagnosis``."""

    explanation = diagnosis.explanation
    return LoggedDiagnosis(
        diagnosed_at=diagnosed_at,
        explanation=Explanation(
            code=explanation.code, what=explanation.what, where=explanation.where, action=explanation.action
        ),
        next_action=diagnosis.next_action,
        checks=[
            LoggedCheck(
                label=check.label,
                state=check.state,
                detail=check.detail,
                code=None if check.message is None else check.message.code,
            )
            for check in diagnosis.checks
        ],
    )


def _domain_fact_notes(files: Sequence[CopiedFile]) -> list[str]:
    """Uwaga o każdym wierszu Kopii ze śladem przesunięcia poza pierwszym wierszem bloku wklejenia
    (``CopiedSheet.traced_rows``): fakt domeny, na którym stoi reguła położenia wiersza, nie zachodzi (ADR 0025)."""

    return [
        f"Fakt domeny złamany: wiersz {row} arkusza {sheet.name} w {file.name} ma datę z godziną dwie kolumny na lewo od "
        "DATA GODZ. POCZ., a nie jest pierwszym wierszem bloku wklejenia; pamięć reguły danych zna go w obu położeniach "
        "(ADR 0025)."
        for file in files
        for sheet in file.sheets
        for row in sheet.traced_rows
    ]
