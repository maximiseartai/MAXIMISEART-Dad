from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import threading
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.client_data import ForbiddenValues, guarded
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import ClickResult, DecisionsUnreadable, StateUnreadable
from rozliczenia.tool_files import REPORT_ENTERING_DECISIONS, REPORT_ENTERING_RESULT, REPORT_ENTERING_STATE
from rozliczenia.worker_reports import (
    ConflictingVerdicts,
    FaultyDescription,
    Kept,
    Login,
    MailId,
    ManualDifference,
    MissingVerdict,
    Offer,
    OlderOwnEntries,
    OrderDetail,
    OrderKey,
    OrderNumber,
    RefusedMove,
    OwnEntries,
    OwnEntry,
    OwnMove,
    RepeatedNumber,
    RepeatedOrder,
    ReportNote,
    ReportProblem,
    RequestedEntry,
    SavedState,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
)
from rozliczenia.worker_reports.reasons import note, overtaken, reason, subject_fault

_DECISIONS_VERSION: Final = 1
_STATE_VERSION: Final = 4
_RESULT_VERSION: Final = 3

Column = Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Own(_Record):
    number: str
    day: date
    worker: str
    column: Column
    value: str


class _Move(_Record):
    number: str
    day: date
    worker: str
    origin_day: date
    origin_worker: str
    origin_name: str
    since: datetime
    overridden: bool
    added: bool = False


class _Requested(_Record):
    mail: str
    worker: str
    day: date
    number: str
    verdict: Literal["tak", "nie"]
    activities: str
    at: datetime

    @classmethod
    def of(cls, decision: RequestedEntry) -> _Requested:
        return cls(
            mail=decision.mail.digest,
            worker=decision.worker,
            day=decision.day,
            number=decision.number,
            verdict=decision.verdict.value,
            activities=decision.activities,
            at=decision.at,
        )

    def decision(self) -> RequestedEntry:
        key = MailId(self.mail), Login(self.worker), self.day, OrderNumber(self.number)
        return RequestedEntry(*key, Verdict(self.verdict), self.activities, self.at)


class _StateV1(_Record):
    schema_version: Literal[1]
    rollout: date
    own: list[_Own]


class _StateV2(_Record):
    schema_version: Literal[2]
    rollout: date
    own: list[_Own]
    moves: list[dict[str, object]]


class _StateV3(_Record):
    schema_version: Literal[3]
    rollout: date
    own: list[_Own]
    moves: list[_Move]


class _State(_Record):
    schema_version: Literal[4]
    rollout: date
    own: list[_Own]
    moves: list[_Move]
    requested: list[_Requested] = []


class _AnyState(RootModel[Annotated[_StateV1 | _StateV2 | _StateV3 | _State, Field(discriminator="schema_version")]]):
    ...

class _Kept(_Record):
    number: str
    day: date
    worker: str
    column: Column
    reported: str

    @classmethod
    def of(cls, kept: Kept) -> _Kept:
        key = kept.key
        return cls(number=key.number, day=key.day, worker=key.worker, column=kept.column.value, reported=kept.reported)

    def kept(self) -> Kept:
        key = OrderKey(OrderNumber(self.number), self.day, Login(self.worker))
        return Kept(key, ReportColumn(self.column), self.reported)


class _Decisions(_Record):
    schema_version: Literal[1]
    kept: list[_Kept]


class _WorkerV1(_Record):
    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: list[str]


class _OrderOffer(_Record):
    mail: str
    activities: str
    successful: Literal["tak", "nie"]
    worker: str
    order_day: date

    @classmethod
    def of(cls, offer: Offer) -> _OrderOffer:
        return cls(
            mail=offer.mail.digest,
            activities=offer.activities,
            successful=offer.verdict.value,
            worker=offer.worker,
            order_day=offer.order_day,
        )

    def offer(self, number: OrderNumber) -> Offer:
        return Offer(
            MailId(self.mail), Login(self.worker), self.order_day, number, Verdict(self.successful), self.activities, self.order_day
        )


class _Order(_Record):
    number: str
    successful: str | None
    activities: str | None
    reported: bool
    codes: list[str] | None = None
    faulty: bool = False
    request: _OrderOffer | None = None


class _Worker(_WorkerV1):
    orders_detail: list[_Order]
    mistaken: list[date] = []
    overtaken: list[str] = []


class _FaultySubject(_Record):
    subject: str
    fault: str
    day: date | None
    arrived: datetime
    mail: str | None = None


class _Offer(_Record):
    mail: str
    worker: str
    day: date
    number: str
    activities: str
    successful: Literal["tak", "nie"]
    order_day: date

    @classmethod
    def of(cls, offer: Offer) -> _Offer:
        return cls(
            mail=offer.mail.digest,
            worker=offer.worker,
            day=offer.day,
            number=offer.number,
            activities=offer.activities,
            successful=offer.verdict.value,
            order_day=offer.order_day,
        )

    def offer(self) -> Offer:
        key = MailId(self.mail), Login(self.worker), self.day, OrderNumber(self.number)
        return Offer(*key, Verdict(self.successful), self.activities, self.order_day)


class _Problem(_Record):
    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: _Kept | None
    request: _Offer | None = None
    faulty_subject: _FaultySubject | None = None


class _Note(_Record):
    day: date
    worker: str
    number: str
    text: str


class _ResultV1(_Record):
    schema_version: Literal[1]
    clicked_at: datetime
    days: list[date]
    workers: list[_WorkerV1]
    problems: list[_Problem]


class _ResultV2(_Record):
    schema_version: Literal[2]
    clicked_at: datetime
    days: list[date]
    workers: list[_Worker]
    problems: list[_Problem]


class _Result(_Record):
    schema_version: Literal[3]
    clicked_at: datetime
    days: list[date]
    workers: list[_Worker]
    problems: list[_Problem]
    notes: list[_Note]


class _AnyResult(RootModel[Annotated[_ResultV1 | _ResultV2 | _Result, Field(discriminator="schema_version")]]):
    ...

@dataclass(frozen=True)
class ShownWorker:
    day: date
    worker: str
    orders: int
    entered: int
    mails: int
    without_report: tuple[str, ...]
    orders_detail: tuple[OrderDetail, ...] | None
    mistaken: tuple[date, ...]
    overtaken: tuple[str, ...]


@dataclass(frozen=True)
class ShownFaultySubject:
    subject: str
    fault: str
    day: date | None
    arrived: datetime
    mail: str | None = None


@dataclass(frozen=True)
class ShownProblem:
    day: date
    worker: str | None
    number: str | None
    reason: str
    sender: str | None
    difference: Kept | None
    faulty_subject: ShownFaultySubject | None
    request: Offer | None = None


@dataclass(frozen=True)
class ShownNote:
    day: date
    worker: str
    number: str
    text: str


@dataclass(frozen=True)
class ShownResult:
    clicked_at: datetime
    days: tuple[date, ...]
    workers: tuple[ShownWorker, ...]
    problems: tuple[ShownProblem, ...]
    detailed: bool
    notes: tuple[ShownNote, ...] = ()

    def offers(self) -> dict[str, Offer]:
        at_orders = (order.request for worker in self.workers for order in worker.orders_detail or ())
        found = (*(problem.request for problem in self.problems), *at_orders)
        return {offer.token: offer for offer in found if offer is not None}


@dataclass
class _TextFile:
    file: StateFile
    unreadable: type[Exception]
    _written: str | None = field(default=None, repr=False)

    def text(self) -> str | None:
        self.file.retry()
        if self.file.unavailable:
            return self._written
        try:
            return self.file.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as error:
            raise self.unreadable from error

    def write(self, record: BaseModel) -> bool:
        self._written = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self.file.write(self._written)
        return not self.file.unavailable


@dataclass
class FileReportState:
    memory: _TextFile
    result: _TextFile
    decisions: _TextFile
    forbidden: ForbiddenValues
    _deciding: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def of_work(cls, work: CentrumWork) -> FileReportState:
        def file(name: str, where: str, unreadable: type[Exception] = StateUnreadable) -> _TextFile:
            return _TextFile(StateFile(work.config / name, work.log, where=where, pause=work.pause), unreadable)

        return cls(
            file(REPORT_ENTERING_STATE, "pamięć Wpisania raportów"),
            file(REPORT_ENTERING_RESULT, "wynik Wpisania raportów"),
            file(REPORT_ENTERING_DECISIONS, "decyzje „Zostaw moją”", DecisionsUnreadable),
            work.forbidden,
        )

    def load(self) -> SavedState:
        text = self.memory.text()
        if text is None:
            return SavedState(None, OwnEntries.EMPTY, self.kept())
        try:
            state = _AnyState.model_validate_json(text).root
            entries = frozenset(
                OwnEntry(
                    OrderKey(OrderNumber(own.number), own.day, Login(own.worker)), ReportColumn(own.column), own.value
                )
                for own in state.own
            )
            moves = frozenset(
                OwnMove(
                    OrderNumber(move.number),
                    move.day,
                    Login(move.worker),
                    move.origin_day,
                    Login(move.origin_worker),
                    move.origin_name,
                    move.since,
                    move.overridden,
                    move.added,
                )
                for move in (state.moves if isinstance(state, _StateV3 | _State) else ())
            )
            memory = OwnEntries(entries, moves)
        except (ValidationError, ValueError) as error:
            raise StateUnreadable from error
        requested = frozenset(found.decision() for found in (state.requested if isinstance(state, _State) else ()))
        return SavedState(
            state.rollout, memory if isinstance(state, _State) else OlderOwnEntries(memory), self.kept(), requested
        )

    def save_memory(
        self, written: CellsWritten, rollout: date, memory: OwnEntries, requested: frozenset[RequestedEntry]
    ) -> bool:
        own = [
            _Own(
                number=entry.key.number,
                day=entry.key.day,
                worker=entry.key.worker,
                column=entry.column.value,
                value=entry.value,
            )
            for entry in sorted(memory.entries, key=lambda entry: (entry.key, entry.column.value, entry.value))
        ]
        moves = [
            _Move(
                number=move.number,
                day=move.day,
                worker=move.worker,
                origin_day=move.origin_day,
                origin_worker=move.origin_worker,
                origin_name=move.origin_name,
                since=move.since,
                overridden=move.overridden,
                added=move.added,
            )
            for move in sorted(memory.moves, key=lambda move: (move.day, move.number))
        ]
        decisions = [
            _Requested.of(decision)
            for decision in sorted(
                requested,
                key=lambda decision: (decision.day, decision.worker, decision.number, decision.mail.digest, decision.at),
            )
        ]
        return self.memory.write(
            _State(schema_version=_STATE_VERSION, rollout=rollout, own=own, moves=moves, requested=decisions)
        )

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        workers = [
            _Worker(
                day=worker.day,
                worker=worker.worker,
                orders=worker.orders,
                entered=worker.entered,
                mails=worker.mails,
                without_report=list(worker.without_report),
                orders_detail=[
                    _Order(
                        number=order.number,
                        successful=order.successful,
                        activities=order.activities,
                        reported=order.reported,
                        codes=None if order.codes is None else list(order.codes),
                        faulty=order.faulty,
                        request=None if order.request is None else _OrderOffer.of(order.request),
                    )
                    for order in worker.orders_detail
                ],
                mistaken=list(worker.mistaken),
                overtaken=[
                    overtaken(found, guarded(self.forbidden, found.subject.shown(), "temat Raportu wykonawcy").text)
                    for found in worker.overtaken
                ],
            )
            for worker in result.workers
        ]
        self.result.write(
            _Result(
                schema_version=_RESULT_VERSION,
                clicked_at=result.clicked_at,
                days=list(result.days),
                workers=workers,
                problems=[_problem(problem, self.forbidden) for problem in result.problems],
                notes=[_note(found) for found in result.notes],
            )
        )

    def shown(self) -> ShownResult | None:
        text = self.result.text()
        if text is None:
            return None
        try:
            result = _AnyResult.model_validate_json(text).root
        except ValidationError as error:
            raise StateUnreadable from error
        return ShownResult(
            result.clicked_at,
            tuple(result.days),
            tuple(
                ShownWorker(
                    worker.day,
                    worker.worker,
                    worker.orders,
                    worker.entered,
                    worker.mails,
                    tuple(worker.without_report),
                    _orders(worker),
                    tuple(worker.mistaken) if isinstance(worker, _Worker) else (),
                    tuple(worker.overtaken) if isinstance(worker, _Worker) else (),
                )
                for worker in result.workers
            ),
            tuple(
                ShownProblem(
                    problem.day,
                    problem.worker,
                    problem.number,
                    problem.reason,
                    problem.sender,
                    None if problem.difference is None else problem.difference.kept(),
                    None
                    if (faulty := problem.faulty_subject) is None
                    else ShownFaultySubject(faulty.subject, faulty.fault, faulty.day, faulty.arrived, faulty.mail),
                    None if problem.request is None else problem.request.offer(),
                )
                for problem in result.problems
            ),
            detailed=not isinstance(result, _ResultV1),
            notes=tuple(
                ShownNote(found.day, found.worker, found.number, found.text)
                for found in (result.notes if isinstance(result, _Result) else ())
            ),
        )

    def kept(self) -> frozenset[Kept]:
        text = self.decisions.text()
        if text is None:
            return frozenset()
        try:
            return frozenset(decision.kept() for decision in _Decisions.model_validate_json(text).kept)
        except ValidationError as error:
            raise DecisionsUnreadable from error

    def keep(self, kept: Kept) -> None:
        with self._deciding:
            decisions = sorted(self.kept() | {kept}, key=lambda decision: (decision.key, decision.column.value, decision.reported))
            self.decisions.write(
                _Decisions(schema_version=_DECISIONS_VERSION, kept=[_Kept.of(decision) for decision in decisions])
            )


def _orders(worker: _WorkerV1) -> tuple[OrderDetail, ...] | None:
    if not isinstance(worker, _Worker):
        return None
    return tuple(
        OrderDetail(
            OrderNumber(order.number),
            order.successful,
            order.activities,
            order.reported,
            None if order.codes is None else tuple(order.codes),
            order.faulty,
            None if order.request is None else order.request.offer(OrderNumber(order.number)),
        )
        for order in worker.orders_detail
    )


def _note(found: ReportNote) -> _Note:
    return _Note(day=found.day, worker=found.worker, number=found.number, text=note(found))


def _problem(problem: ReportProblem, forbidden: ForbiddenValues) -> _Problem:
    said = reason(problem)
    match problem:
        case UnreadableSubject(mail=mail, worker=worker, arrived=arrived, fault=fault, subject=subject, day=day):
            shown = guarded(forbidden, subject.shown(), "temat Raportu wykonawcy").text
            found = _FaultySubject(subject=shown, fault=subject_fault(fault), day=day, arrived=arrived, mail=mail.digest)
            return _Problem(
                day=day or arrived.date(),
                worker=worker,
                number=None,
                reason=said,
                sender=None,
                difference=None,
                faulty_subject=found,
            )
        case UnknownSender(sender=sender, day=day):
            return _Problem(day=day, worker=None, number=None, reason=said, sender=sender.shown(), difference=None)
        case MissingVerdict(offer=offer) if offer is not None:
            return _Problem(
                day=problem.day,
                worker=problem.worker,
                number=problem.number,
                reason=said,
                sender=None,
                difference=None,
                request=_Offer.of(offer),
            )
        case MissingVerdict() | ConflictingVerdicts() | UnknownNumber() | RepeatedOrder() | RepeatedNumber() | FaultyDescription():
            return _Problem(
                day=problem.day, worker=problem.worker, number=problem.number, reason=said, sender=None, difference=None
            )
        case RefusedMove(worker=worker, number=number):
            return _Problem(day=problem.shown, worker=worker, number=number, reason=said, sender=None, difference=None)
        case ManualDifference(key=key, column=column, reported=reported):
            difference = _Kept.of(Kept(key, column, reported))
            return _Problem(
                day=key.day, worker=key.worker, number=key.number, reason=said, sender=None, difference=difference
            )
        case _:
            assert_never(problem)
