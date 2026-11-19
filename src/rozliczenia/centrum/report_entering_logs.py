from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from rozliczenia.activity_legend import problem_text
from rozliczenia.client_data import MASKS
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import EnteringFacts, EnteringSummary
from rozliczenia.worker_reports import (
    AddBar,
    ConflictingVerdicts,
    FaultyDescription,
    Kept,
    Login,
    MailId,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    MoveBar,
    RefusedMove,
    OwnEntries,
    OwnEntry,
    OwnMove,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    RequestedEntry,
    SavedState,
    SubjectFault,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    VerdictFault,
    WindowMails,
)


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LoggedReportEntry(_Record):
    number: str
    verdict: Literal["tak", "nie"] | None
    fault: VerdictFault | None
    activities: str

    @classmethod
    def of(cls, entry: ReportEntry) -> LoggedReportEntry:
        return cls(
            number=entry.number,
            verdict=None if entry.verdict is None else entry.verdict.value,
            fault=entry.fault,
            activities=entry.activities,
        )

    def entry(self) -> ReportEntry:
        verdict = None if self.verdict is None else Verdict(self.verdict)
        return ReportEntry(OrderNumber(self.number), verdict, self.fault, self.activities)


class LoggedReportMail(_Record):
    kind: Literal["report"]
    mail: str
    arrived: datetime
    worker: str
    day: date
    entries: list[LoggedReportEntry]


class LoggedUnreadableMail(_Record):
    kind: Literal["unreadable"]
    mail: str
    arrived: datetime
    worker: str
    fault: SubjectFault
    numbers: list[str] | None = None
    day: date | None = None
    entries: list[LoggedReportEntry] | None = None


class LoggedStrangerMail(_Record):
    kind: Literal["stranger"]
    mail: str
    arrived: datetime
    day: date


LoggedMail = Annotated[LoggedReportMail | LoggedUnreadableMail | LoggedStrangerMail, Field(discriminator="kind")]


class _MailRecord(_Record):
    mail: LoggedMail


def logged_mails(mails: WindowMails) -> list[LoggedMail]:
    return [_MailRecord.model_validate({"mail": record}).mail for record in mails.log()]


def window_mails(logged: Iterable[LoggedMail]) -> WindowMails:
    return WindowMails.from_log(mail.model_dump(mode="json") for mail in logged)


class LoggedOrderPlace(_Record):
    day: date
    worker: str


class LoggedOrderProblem(_Record):
    kind: Literal[
        "missing_verdict",
        "unknown_number",
        "foreign_order",
        "other_day",
        "repeated_order",
        "repeated_number",
        "refused_move",
    ]
    worker: str
    day: date
    number: str
    fault: VerdictFault | None = None
    owner: str | None = None
    order_days: list[date] = []
    places: list[LoggedOrderPlace] = []
    bar: MoveBar | AddBar | None = None

    @field_validator("bar", mode="before")
    @classmethod
    def _bar_of_kind(cls, bar: object, info: ValidationInfo) -> object:
        kind = _BARS.get(info.data.get("kind", ""))
        return kind(bar) if isinstance(bar, str) and kind is not None else bar


_BARS: Final[Mapping[str, type[MoveBar] | type[AddBar]]] = {"refused_move": MoveBar, "unknown_number": AddBar}


class LoggedConflictProblem(_Record):
    kind: Literal["conflicting_verdicts"]
    mail: str
    arrived: datetime
    worker: str
    day: date
    number: str
    entries: list[LoggedReportEntry]


class LoggedDescriptionProblem(_Record):
    kind: Literal["faulty_description"]
    worker: str
    day: date
    number: str
    reasons: list[str]


class LoggedSubjectProblem(_Record):
    kind: Literal["unreadable_subject"]
    mail: str
    worker: str
    arrived: datetime
    fault: SubjectFault
    day: date | None = None


class LoggedSenderProblem(_Record):
    kind: Literal["unknown_sender"]
    mail: str
    day: date


class LoggedOwnEntry(_Record):
    number: int
    day: date
    worker: str
    column: ReportColumn
    value: str

    @classmethod
    def of(cls, key: OrderKey, column: ReportColumn, value: str) -> LoggedOwnEntry:
        return cls(number=int(key.number), day=key.day, worker=key.worker, column=column, value=value)


class LoggedManualProblem(_Record):
    kind: Literal["manual_difference"]
    cell: LoggedOwnEntry
    manual: str


LoggedProblem = Annotated[
    LoggedOrderProblem
    | LoggedConflictProblem
    | LoggedDescriptionProblem
    | LoggedSubjectProblem
    | LoggedSenderProblem
    | LoggedManualProblem,
    Field(discriminator="kind"),
]


def _problem(problem: ReportProblem) -> LoggedProblem:
    match problem:
        case UnreadableSubject():
            return LoggedSubjectProblem(
                kind="unreadable_subject",
                mail=problem.mail.digest,
                worker=problem.worker,
                arrived=problem.arrived,
                fault=problem.fault,
                day=problem.day,
            )
        case UnknownSender():
            return LoggedSenderProblem(kind="unknown_sender", mail=problem.mail.digest, day=problem.day)
        case MissingVerdict():
            return LoggedOrderProblem(
                kind="missing_verdict",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                fault=problem.fault,
            )
        case ConflictingVerdicts():
            return LoggedConflictProblem(
                kind="conflicting_verdicts",
                mail=problem.mail.digest,
                arrived=problem.arrived,
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                entries=[LoggedReportEntry.of(entry) for entry in problem.entries],
            )
        case UnknownNumber():
            return LoggedOrderProblem(
                kind="unknown_number",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                bar=problem.bar,
            )
        case RepeatedOrder():
            return LoggedOrderProblem(kind="repeated_order", worker=problem.worker, day=problem.day, number=problem.number)
        case RepeatedNumber():
            return LoggedOrderProblem(
                kind="repeated_number",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                places=[LoggedOrderPlace(day=day, worker=worker) for day, worker in problem.places],
            )
        case RefusedMove():
            return LoggedOrderProblem(
                kind="refused_move",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                order_days=[problem.order_day],
                bar=problem.bar,
            )
        case ManualDifference():
            cell = LoggedOwnEntry.of(problem.key, problem.column, problem.reported)
            return LoggedManualProblem(kind="manual_difference", cell=cell, manual=problem.manual)
        case FaultyDescription():
            return LoggedDescriptionProblem(
                kind="faulty_description",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                reasons=list(dict.fromkeys(map(problem_text, problem.problems))),
            )
        case _:
            assert_never(problem)


class LoggedChange(_Record):
    sheet: str
    row: int
    column: ReportColumn
    value: str


class LoggedMove(_Record):
    sheet: str
    row: int
    day: date
    worker: str


class LoggedAdded(_Record):
    sheet: str
    day: date
    worker: str
    number: int
    successful: Literal["tak", "nie"]
    completed: str | None


class LoggedRequestedEntry(_Record):
    mail: str
    worker: str
    day: date
    number: str
    verdict: Literal["tak", "nie"]
    activities: str
    at: datetime

    @classmethod
    def of(cls, decision: RequestedEntry) -> LoggedRequestedEntry:
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


class LoggedOrderless(_Record):
    sheet: str
    number: int
    day: date | None = None


class LoggedOwnMove(_Record):
    number: int
    day: date
    worker: str
    origin_day: date
    origin_worker: str
    origin_name: str
    since: datetime
    overridden: bool = False
    added: bool = False

    @classmethod
    def of(cls, move: OwnMove) -> LoggedOwnMove:
        return cls(
            number=int(move.number),
            day=move.day,
            worker=move.worker,
            origin_day=move.origin_day,
            origin_worker=move.origin_worker,
            origin_name=move.origin_name,
            since=move.since,
            overridden=move.overridden,
            added=move.added,
        )


class LoggedReports(_Record):
    today: date
    rollout_before: date | None
    rollout: date
    closed: list[str] = []
    skipped: int
    mails: list[LoggedMail]
    problems: list[LoggedProblem]
    changes: list[LoggedChange]
    memory_before: list[LoggedOwnEntry]
    kept: list[LoggedOwnEntry] = []
    moves: list[LoggedMove] = []
    moves_before: list[LoggedOwnMove] = []
    added: list[LoggedAdded] = []
    orderless: list[LoggedOrderless] = []
    requested: list[LoggedRequestedEntry] = []
    written: int | None

    @classmethod
    def of(cls, facts: EnteringFacts, written: int | None) -> LoggedReports:
        return cls(
            today=facts.today,
            rollout_before=facts.rollout_before,
            rollout=facts.rollout,
            closed=list(facts.closed),
            skipped=facts.skipped,
            mails=logged_mails(facts.mails),
            problems=[_problem(problem) for problem in facts.problems],
            changes=[
                LoggedChange(sheet=change.order.sheet, row=change.order.row, column=change.column, value=change.value)
                for change in facts.changes
            ],
            memory_before=[LoggedOwnEntry.of(entry.key, entry.column, entry.value) for entry in facts.memory_before],
            kept=[LoggedOwnEntry.of(kept.key, kept.column, kept.reported) for kept in facts.kept],
            moves=[
                LoggedMove(sheet=move.order.sheet, row=move.order.row, day=move.day, worker=move.worker)
                for move in facts.moves
            ],
            moves_before=[LoggedOwnMove.of(move) for move in facts.moves_before],
            added=[
                LoggedAdded(
                    sheet=added.sheet,
                    day=added.day,
                    worker=added.worker,
                    number=int(added.number),
                    successful=Verdict(added.successful).value,
                    completed=added.completed,
                )
                for added in facts.added
            ],
            orderless=[
                LoggedOrderless(sheet=found.sheet, number=int(found.number), day=found.day) for found in facts.orderless
            ],
            requested=[LoggedRequestedEntry.of(decision) for decision in facts.requested],
            written=written,
        )

    @classmethod
    def of_run(cls, summary: EnteringSummary | None, facts: object) -> LoggedReports | None:
        match summary, facts:
            case EnteringSummary() as done, _:
                return cls.of(done.facts, done.written)
            case _, EnteringSummary() as done:
                return cls.of(done.facts, done.written)
            case _, EnteringFacts() as stopped:
                return cls.of(stopped, None)
            case _:
                return None

    def replay(self) -> EnteringReplay | Unreplayable:
        masked = [entry.number for entry in _logged_entries(self) if not _digits(entry.number)]
        if masked:
            return Unreplayable(
                f"Wpis raportu w Logach ma numer zlecenia zamaskowany przez strażnika reguły danych ({masked[0]}: 9 cyfr "
                "w kształcie telefonu, w Logach starszych Wydań także z zerem z przodu), więc odtworzenie nie wie, do "
                "którego zlecenia szedł ten Wpis"
            )
        numbers = _numbers(self)
        for name, logged in (("pamięć wpisów", self.memory_before), ("decyzje „Zostaw moją”", self.kept)):
            unknown = [entry for entry in logged if len(_texts(numbers, entry.number, entry.day, entry.worker)) != 1]
            if unknown:
                entry = unknown[0]
                return Unreplayable(
                    f"{name} w Logach ma zlecenie {entry.number} Wykonawcy {entry.worker} z {entry.day:%d.%m.%Y} "
                    "tylko jako liczbę, a jego numeru nie ma w dokładnie jednym Wpisie raportu w Logach, więc "
                    "odtworzenie nie wie, czy numer ma zera na początku"
                )
        try:
            saved = _saved(self)
        except ValueError as error:
            return Unreplayable(
                f"pamięć wpisów i zleceń w Logach z numerami w postaci z Wpisów raportu łamie regułę pamięci "
                f"({str(error).rstrip('.')}), a Logi mają jej numery tylko jako liczbę, więc odtworzenie nie wie, które z "
                "nich mają zera na początku"
            )
        reservations: list[str] = []
        counted = Counter(
            {mask: sum(entry.activities.count(mask) for entry in _logged_entries(self)) for mask in MASKS}
        )
        if +counted:
            masks = ", ".join(f"{mask} ×{count}" for mask, count in (+counted).most_common())
            reservations.append(
                f"Wpisy raportu w Logach mają maski strażnika reguły danych ({masks}): odtworzenie wpisuje do INTERMAX "
                "maskę w miejscu czynności Wykonawcy, więc reguła, która porównuje je z komórką, może zdecydować inaczej"
            )
        if any(isinstance(mail, LoggedUnreadableMail) and mail.numbers is None for mail in self.mails):
            reservations.append(
                "Logi sprzed numerów Wpisów maila z nieczytelnym tematem (v0.7.0): odtworzenie czyta ten mail bez Wpisów, "
                "więc ostrzeżenie o nieczytelnym temacie, które u taty zdjął poprawiony mail, wraca w odtworzeniu jako "
                "różnica"
            )
        return EnteringReplay(
            today=self.today,
            closed=tuple(self.closed),
            skipped=self.skipped,
            mails=window_mails(self.mails),
            strangers=tuple(_strangers(self)),
            saved=saved,
            orderless=tuple(_orderless(self)),
            reservations=tuple(reservations),
        )


@dataclass(frozen=True)
class EnteringReplay:
    today: date
    closed: tuple[str, ...]
    skipped: int
    mails: WindowMails
    strangers: tuple[int, ...]
    saved: SavedState
    orderless: tuple[ReplayedOrderless, ...]
    reservations: tuple[str, ...]

    @classmethod
    def without_logs(cls, today: date) -> EnteringReplay:
        return cls(today, (), 0, window_mails(()), (), SavedState(None, OwnEntries.EMPTY), (), ())


@dataclass(frozen=True)
class ReplayedOrderless:
    sheet: str
    number: str | int
    day: date | None


@dataclass(frozen=True)
class Unreplayable:
    reason: str


def _strangers(entering: LoggedReports) -> list[int]:
    senders = Counter((problem.mail, problem.day) for problem in entering.problems if isinstance(problem, LoggedSenderProblem))
    seen: Counter[tuple[str, date]] = Counter()
    found: list[int] = []
    for mail in entering.mails:
        if isinstance(mail, LoggedStrangerMail):
            key = (mail.mail, mail.day)
            found.append(seen[key] % max(senders[key], 1))
            seen[key] += 1
    return found


def _digits(number: str) -> bool:
    return number.isascii() and number.isdigit()


def _logged_entries(entering: LoggedReports) -> list[LoggedReportEntry]:
    return [
        entry
        for mail in entering.mails
        if not isinstance(mail, LoggedStrangerMail)
        for entry in (mail.entries or () if isinstance(mail, LoggedUnreadableMail) else mail.entries)
    ]


def _texts(numbers: dict[tuple[int, date, str], set[str]], number: int, day: date, worker: str) -> set[str]:
    return (
        numbers.get((number, day, worker))
        or {text for (value, found, _), texts in numbers.items() if (value, found) == (number, day) for text in texts}
        or {text for (value, _, _), texts in numbers.items() if value == number for text in texts}
    )


def _numbers(entering: LoggedReports) -> dict[tuple[int, date, str], set[str]]:
    decisions = [logged.decision() for logged in entering.requested]
    said = window_mails(entering.mails).said(()) | {OrderKey(found.number, found.day, found.worker) for found in decisions}
    numbers: dict[tuple[int, date, str], set[str]] = {}
    for key in said:
        if _digits(key.number):
            numbers.setdefault((int(key.number), key.day, key.worker), set()).add(key.number)
    return numbers


def _saved(entering: LoggedReports) -> SavedState:
    numbers = _numbers(entering)

    def key(logged: LoggedOwnEntry) -> OrderKey:
        [number] = _texts(numbers, logged.number, logged.day, logged.worker)
        return OrderKey(OrderNumber(number), logged.day, Login(logged.worker))

    def number(logged: LoggedOwnMove) -> OrderNumber:
        found = _texts(numbers, logged.number, logged.day, logged.worker)
        return OrderNumber(found.pop() if len(found) == 1 else str(logged.number))

    entries = frozenset(OwnEntry(key(logged), logged.column, logged.value) for logged in entering.memory_before)
    kept = frozenset(Kept(key(logged), logged.column, logged.value) for logged in entering.kept)
    moves = frozenset(
        OwnMove(
            number(logged),
            logged.day,
            Login(logged.worker),
            logged.origin_day,
            Login(logged.origin_worker),
            logged.origin_name,
            logged.since,
            logged.overridden,
            logged.added,
        )
        for logged in entering.moves_before
    )
    requested = frozenset(logged.decision() for logged in entering.requested)
    return SavedState(entering.rollout_before, OwnEntries(entries, moves), kept, requested)


def _orderless(entering: LoggedReports) -> list[ReplayedOrderless]:
    numbers = _numbers(entering)
    replayed: list[ReplayedOrderless] = []
    for logged in entering.orderless:
        number = logged.number
        texts = {text for (value, _, _), found in numbers.items() if value == number for text in found}
        zero = sorted(text for text in texts if text.startswith("0"))
        replayed.append(ReplayedOrderless(logged.sheet, zero[0] if zero else number, logged.day))
    return replayed
