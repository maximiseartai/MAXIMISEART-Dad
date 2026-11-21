from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Annotated, Any, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_actions import ButtonPressed, DadActions, StoredRunMode
from rozliczenia.centrum.logged_input_copy import LoggedInputFile
from rozliczenia.centrum.report_entering_logs import LoggedReports
from rozliczenia.client_data import READ_VALUES
from rozliczenia.domain import ProgressPhase, WorkerStatus
from rozliczenia.efenix_checks import ListedRead
from rozliczenia.efenix_pricing import OrderKind, OrderResult, PricingStopped, PricingSummary, StoppedOrder
from rozliczenia.efenix_window import (
    BrowserFailure,
    Closed,
    ElementCount,
    HttpStatus,
    LoginSign,
    OtherShape,
    PagePart,
    StatusChangeBlocked,
    WindowAction,
    WindowCause,
)
from rozliczenia.activity_legend import ActivityLegend, LegendProblem
from rozliczenia.activity_legend_file import dump_activity_legend, parse_activity_legend
from rozliczenia.efenix_trace import TraceStep
from rozliczenia.intermax_ordering import HistoryCounts, OrderingSummary
from rozliczenia.message import Message, SettingsSection
from rozliczenia.process_run import RunResult, StopEnding
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.quantity_engine import QuantityRules, RulesProblem
from rozliczenia.quantity_rules_file import (
    dump_device_list,
    dump_quantity_rules,
    parse_device_list,
    parse_quantity_rules,
)
from rozliczenia.worker_list import WorkerEntry, WorkerList, WorkerListProblem

RUN_LOGS_DIRECTORY: Final = "uruchomienia"
SCHEMA_VERSION: Final = 3

LoggedEnding = Literal["finished", StopEnding, "interrupted"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StartFacts(_Record):
    run_id: str
    process: common_contract.ProcessKey
    mode: StoredRunMode
    period: str
    started_at: datetime
    pricing: runs_contract.Pricing | None = None

    @classmethod
    def of_run(cls, info: runs_contract.RunInfo, started_at: datetime) -> StartFacts:
        return cls(
            run_id=info.id,
            process=info.process,
            mode=info.mode,
            period=info.period,
            started_at=started_at,
            pricing=info.pricing,
        )

    @property
    def start(self) -> StartFacts:
        return StartFacts.model_validate({name: getattr(self, name) for name in StartFacts.model_fields})


LoggedQuantity = int | str


class LoggedMessage(_Record):
    kind: Literal["stop", "warning"]
    code: str
    what: str
    where: str
    action: str
    setting: SettingsSection | None = Field(default=None, exclude_if=lambda setting: setting is None)
    at_start: bool = Field(default=False, exclude_if=lambda at_start: not at_start)

    @classmethod
    def of(cls, kind: Literal["stop", "warning"], message: Message, *, at_start: bool = False) -> LoggedMessage:
        return cls(
            kind=kind,
            code=message.code,
            what=message.what,
            where=message.where,
            action=message.action,
            setting=message.setting,
            at_start=at_start,
        )

    def message(self) -> Message:
        return Message(code=self.code, what=self.what, where=self.where, action=self.action, setting=self.setting)

    def shown(self) -> common_contract.Message:
        return common_contract.Message(what=self.what, where=self.where, action=self.action, setting=self.setting)


class LoggedPhase(_Record):
    phase: runs_contract.PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @classmethod
    def all_of(cls, phases: Sequence[runs_contract.PhaseProgress], snapshot: ProgressSnapshot | None) -> list[LoggedPhase]:
        def moment(moments: Mapping[ProgressPhase, datetime] | None, phase: runs_contract.PhaseName) -> datetime | None:
            return None if moments is None else moments.get(ProgressPhase(phase))

        started = None if snapshot is None else snapshot.phase_started_at
        ended = None if snapshot is None else snapshot.phase_ended_at
        return [
            cls(
                phase=phase.phase,
                state=phase.state,
                duration_ms=phase.duration_ms,
                started_at=moment(started, phase.phase),
                ended_at=moment(ended, phase.phase),
            )
            for phase in phases
        ]

    @property
    def progress(self) -> runs_contract.PhaseProgress:
        return runs_contract.PhaseProgress(phase=self.phase, state=self.state, duration_ms=self.duration_ms)


class LoggedTemplate(_Record):
    wykonawca: str
    outcome: WorkerStatus | Literal["failed"]
    rows: int
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None


class LoggedFile(_Record):
    name: str
    size: int | None
    online_only: bool | None
    sha256: str | None = None


class LoggedWorker(_Record):
    logins: list[str]
    name: str
    active: bool

    @classmethod
    def all_of(cls, workers: WorkerList) -> list[LoggedWorker]:
        return [cls(logins=list(worker.logins), name=worker.name, active=worker.active) for worker in workers.workers]

    @staticmethod
    def worker_list(logged: Sequence[LoggedWorker]) -> WorkerList | WorkerListProblem:
        return WorkerList.of([WorkerEntry(worker.logins, worker.name, active=worker.active) for worker in logged])


class CentrumLogLines(_Record):
    lines: list[str]
    omitted: int


class Environment(_Record):
    system: str
    python: str
    files: list[LoggedFile] | None
    unreadable_settings: str | None = None


class Explanation(_Record):
    code: str
    what: str
    where: str
    action: str


class LoggedCheck(_Record):
    label: str
    state: diagnosis_contract.CheckState
    detail: str
    code: str | None

    @property
    def result(self) -> tuple[str, diagnosis_contract.CheckState, str | None, str | None]:
        return self.label, self.state, self.code, None if self.state == "passed" else self.detail


class LoggedDiagnosis(_Record):
    diagnosed_at: datetime
    explanation: Explanation
    next_action: diagnosis_contract.DiagnosisNextAction
    checks: list[LoggedCheck]

    def same_result(self, other: LoggedDiagnosis) -> bool:
        def result(diagnosis: LoggedDiagnosis) -> object:
            return diagnosis.explanation, diagnosis.next_action, [check.result for check in diagnosis.checks]

        return result(self) == result(other)


class LoggedWholesale(_Record):
    row: int
    operator: str | None


class LoggedEntries(_Record):
    rows: dict[str, list[int]]
    without_entry: list[LoggedWholesale]

    @classmethod
    def of(cls, summary: OrderingSummary) -> LoggedEntries:
        return cls(
            rows={operator: list(rows) for operator, rows in summary.entries.items()},
            without_entry=[LoggedWholesale(row=row, operator=operator) for row, operator in summary.without_entry],
        )


class LoggedHistory(_Record):
    orders: int
    rows: int
    sheets: int

    @classmethod
    def of(cls, history: HistoryCounts) -> LoggedHistory:
        return cls(orders=history.orders, rows=history.rows, sheets=history.sheets)


class LoggedResult(_Record):
    same_number: bool
    status: str
    realizator: str | None
    address: list[str]

    @classmethod
    def of(cls, read: ListedRead) -> LoggedResult:
        return cls(
            same_number=read.same_number,
            status=read.status,
            realizator=read.realizator,
            address=[part.value for part in read.address],
        )


class LoggedStep(_Record):
    action: WindowAction
    started_at: datetime | None = None
    duration_ms: int
    found: int | None
    execution_date: date | None
    amount: Decimal | None
    quantities: Annotated[dict[str, LoggedQuantity] | None, READ_VALUES]
    position: str | None
    quantity: Annotated[LoggedQuantity | None, READ_VALUES]
    accepted: bool | None
    results: list[LoggedResult] | None = None
    status: str | None = None
    realizator: str | None = None
    refusal: str | None = None

    @classmethod
    def of(cls, step: TraceStep) -> LoggedStep:
        return cls(
            action=step.action,
            started_at=step.started_at,
            duration_ms=step.duration_ms,
            found=step.found,
            execution_date=step.execution_date,
            amount=step.amount,
            quantities=None if step.quantities is None else dict(step.quantities),
            position=step.position,
            quantity=step.quantity,
            accepted=step.accepted,
            results=None if step.results is None else [LoggedResult.of(read) for read in step.results],
            status=step.status,
            realizator=step.realizator,
            refusal=None if step.refusal is None else step.refusal.name,
        )


class LoggedOrder(_Record):
    row: int
    outcome: OrderKind
    code: str | None
    file: Annotated[dict[str, LoggedQuantity] | None, READ_VALUES]
    file_amount: Decimal
    steps: list[LoggedStep]

    @classmethod
    def all_of(cls, summary: PricingSummary) -> list[LoggedOrder]:
        return [cls.of(result) for result in summary.results]

    @classmethod
    def of(cls, result: OrderResult) -> LoggedOrder:
        return cls(
            row=result.order.row,
            outcome=result.kind,
            code=None if result.message is None else result.message.code,
            file=None if result.file is None else dict(result.file),
            file_amount=result.order.amount,
            steps=[LoggedStep.of(step) for step in result.steps],
        )


class LoggedCause(_Record):
    part: str | None
    what: str
    positions: list[str] | None = None
    element: str | None = None
    count: int | None = None
    status: int | None = None
    error_type: str | None = None
    operation: str | None = None

    @classmethod
    def of(cls, part: PagePart | None, cause: WindowCause) -> LoggedCause:
        name = None if part is None else part.name
        match cause:
            case ElementCount(selector, count):
                return cls(part=name, what=_ELEMENT_COUNT, element=selector, count=count)
            case HttpStatus(status):
                return cls(part=name, what=_HTTP_STATUS, status=status)
            case OtherShape(shape, position):
                return cls(part=name, what=shape.value, positions=None if position is None else [position])
            case BrowserFailure(error_type, operation):
                return cls(
                    part=name,
                    what=_BROWSER_FAILURE,
                    error_type=error_type,
                    operation=None if operation is None else operation.value,
                )
            case LoginSign() | Closed() | StatusChangeBlocked():
                return cls(part=name, what=cause.value)
            case _:
                assert_never(cause)


_ELEMENT_COUNT: Final = "element strony nie występuje dokładnie raz"
_BROWSER_FAILURE: Final = "błąd przeglądarki w działaniu okna"
_HTTP_STATUS: Final = "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno"


class LoggedWindowStop(_Record):
    cause: LoggedCause
    row: int | None
    order: int | None
    orders: int | None
    steps: list[LoggedStep]
    failed: LoggedStep | None

    @classmethod
    def of(cls, stopped: PricingStopped) -> LoggedWindowStop:
        at: StoppedOrder | None = stopped.stopped_at
        cause = LoggedCause.of(stopped.part, stopped.cause)
        if at is None:
            return cls(cause=cause, row=None, order=None, orders=None, steps=[], failed=None)
        return cls(
            cause=cause,
            row=at.row,
            order=at.place,
            orders=at.total,
            steps=[LoggedStep.of(step) for step in at.steps],
            failed=None if at.failed is None else LoggedStep.of(at.failed),
        )


class ProcessLogs(_Record):
    inea_only_cleared: dict[str, int] | None = None
    intermax_entries: LoggedEntries | None = None
    address_history: LoggedHistory | None = None
    efenix_orders: list[LoggedOrder] | None = None
    efenix_stop: LoggedWindowStop | None = None
    report_entering: LoggedReports | None = None


class LoggedQuantityRules(_Record):
    rules: str
    devices: str

    @classmethod
    def of(cls, rules: QuantityRules) -> LoggedQuantityRules:
        return cls(rules=_json_text(dump_quantity_rules(rules)), devices=_json_text(dump_device_list(rules.devices)))

    def value(self) -> QuantityRules | RulesProblem:
        try:
            rules, devices = json.loads(self.rules), json.loads(self.devices)
        except ValueError:
            return RulesProblem("plik", "Reguły ilości w Logach nie są tekstem JSON.")
        found = parse_device_list(devices)
        return found if isinstance(found, RulesProblem) else parse_quantity_rules(rules, found)


class LoggedActivityLegend(_Record):
    legend: str

    @classmethod
    def of(cls, legend: ActivityLegend) -> LoggedActivityLegend:
        return cls(legend=_json_text(dump_activity_legend(legend)))

    def value(self) -> ActivityLegend | LegendProblem:
        try:
            document = json.loads(self.legend)
        except ValueError:
            return LegendProblem("plik", "Legenda czynności w Logach nie jest tekstem JSON.")
        return parse_activity_legend(document)


def _json_text(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


class LoggedInterruption(_Record):
    row: int | None
    place: int | None
    total: int | None
    omitted: int


class Tool(_Record):
    wydanie: str | None
    commit: str | None


class RunLog(StartFacts):
    schema_version: Literal[1, 2, 3]
    ended_at: datetime
    duration_ms: int | None
    tool: Tool
    result: RunResult | None
    ending: LoggedEnding
    stop_kind: runs_contract.StopKind | None
    issue_count: int | None
    messages: list[LoggedMessage]
    technical_notes: list[str]
    summary: runs_contract.RunSummary | None
    phases: list[LoggedPhase]
    templates: list[LoggedTemplate]
    inea_only_cleared: dict[str, int] | None = None
    intermax_entries: LoggedEntries | None = None
    address_history: LoggedHistory | None = None
    efenix_orders: list[LoggedOrder] | None = None
    efenix_stop: LoggedWindowStop | None = None
    report_entering: LoggedReports | None = None
    environment: Environment
    trace: CallTrace | None
    diagnosis: LoggedDiagnosis | None
    dad_actions: DadActions | None = None
    centrum_log: CentrumLogLines | None = None
    interruption: LoggedInterruption | None = None
    input_copy: list[LoggedInputFile] | None = None
    input_copy_notes: list[str] = []
    quantity_rules: LoggedQuantityRules | None = None
    activity_legend: LoggedActivityLegend | None = None
    workers: list[LoggedWorker] | None = None

    @model_serializer(mode="wrap")
    def _in_own_schema(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        dumped: dict[str, Any] = handler(self)
        if self.schema_version == SCHEMA_VERSION:
            return dumped
        dumped["mode"] = self.mode.word
        if self.dad_actions is not None:
            for action, entry in zip(self.dad_actions.entries, dumped["dad_actions"]["entries"], strict=True):
                if isinstance(action, ButtonPressed) and action.mode is not None:
                    entry["mode"] = action.mode.word
        return dumped

    def start_warnings(self) -> tuple[Message, ...]:
        return tuple(message.message() for message in self.messages if message.at_start)

    @classmethod
    def interrupted(
        cls,
        started: StartFacts,
        *,
        ended_at: datetime,
        orders: Sequence[LoggedOrder],
        interruption: LoggedInterruption,
        tool: Tool,
        environment: Environment,
        dad_actions: DadActions,
        centrum_log: CentrumLogLines | None = None,
    ) -> RunLog:
        return cls(
            **dict(started.start),
            schema_version=SCHEMA_VERSION,
            ended_at=ended_at,
            duration_ms=None,
            tool=tool,
            result=None,
            ending="interrupted",
            stop_kind=None,
            issue_count=None,
            messages=[],
            technical_notes=[],
            summary=None,
            phases=[],
            templates=[],
            efenix_orders=list(orders),
            environment=environment,
            trace=None,
            diagnosis=None,
            dad_actions=dad_actions,
            centrum_log=centrum_log,
            interruption=interruption,
        )

    @property
    def text(self) -> str:
        return self.model_dump_json(indent=2) + "\n"


assert all(RunLog.model_fields[name].annotation == field.annotation for name, field in ProcessLogs.model_fields.items()), (
    "dodatki Logów procesu to pola RunLog tych samych typów"
)

