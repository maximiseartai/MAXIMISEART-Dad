from __future__ import annotations

from bisect import bisect_left
import threading
import uuid
import weakref
from collections.abc import Callable, Sequence
from dataclasses import astuple, dataclass
import hashlib
from typing import Final, Literal

from rozliczenia.client_data import ForbiddenValues, Outgoing, guarded, tool
from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import report_messages
from rozliczenia.centrum.box_prefix import titled
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_cases import REPORT, Case, CaseNews, CaseNumbered, CaseRejected, DadCases
from rozliczenia.centrum.deadline import within
from rozliczenia.centrum.diagnosis import LOG_ENTRIES, Diagnosis
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, PART_LIMIT, OpenIssue, Outbox, Post
from rozliczenia.centrum.report_issue import RETURNED_HEADING, fingerprint_line
from rozliczenia.centrum.report_box import FindOutcome
from rozliczenia.centrum.tool_freshness import RELEASES_TIMEOUT_S, CommitSource
from rozliczenia.centrum.tool_update import UpdateResult
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.message import Message
from rozliczenia.process_run import Stop
from rozliczenia.wall_clock import utc_now

SEARCH_DEADLINE_S: Final = RELEASES_TIMEOUT_S
REPORT_THREAD: Final = "zgloszenie-skrzynka"

_CHECK_STATES: Final = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}


@dataclass(frozen=True)
class Report:
    title: str
    body: str
    fingerprint: str
    what: str


@dataclass(frozen=True)
class ProblemFingerprint:
    process: common_contract.ProcessKey | Literal["tool_update", "report_reminders"]
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, process: common_contract.ProcessKey, message: Message) -> ProblemFingerprint:
        return cls(process, message.code, message.what, message.where, message.action)

    @classmethod
    def of_tool_update(cls, message: Message) -> ProblemFingerprint:
        return cls("tool_update", message.code, message.what, message.where, message.action)

    @classmethod
    def of_reminders(cls, message: Message) -> ProblemFingerprint:
        return cls("report_reminders", message.code, message.what, message.where, message.action)

    @property
    def digest(self) -> str:
        return hashlib.sha256("\x1f".join(astuple(self)).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StopReport:
    run: runs_contract.RunInfo
    stop: Stop
    fingerprint: ProblemFingerprint
    diagnosis: Diagnosis
    logs: str | None

    @property
    def period(self) -> str:
        return self.run.period

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        run, message, diagnosis, trace = self.run, self.stop.message, self.diagnosis, self.stop.trace
        fingerprint = self.fingerprint.digest
        explanation = diagnosis.explanation

        def lines(dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(message),
                "## Uruchomienie procesu",
                "",
                f"- Proces: {run.title}",
                f"- Okres: {run.period}",
                f"- Tryb: {run.mode}",
                f"- Logi: {self.logs or f'jeszcze niewysłane, Uruchomienie {run.id}'}",
                "",
                *_trace_lines(trace, dropped_frames),
                *_tool_lines(fingerprint, previous, commit=f"- Commit: {commit or 'nieznany'}"),
                "## Diagnoza",
                "",
                f"Wyjaśnienie: {explanation.code} · {explanation.what}",
                "",
                "| Sprawdzenie | Wynik | Szczegóły |",
                "| --- | --- | --- |",
                *(
                    f"| {_cell(check.label)} | {_CHECK_STATES[check.state]} | {_cell(check.detail)} |"
                    for check in diagnosis.checks
                ),
                "",
                *_settings_lines(settings),
                *_log_lines(diagnosis.log_entries, dropped_entries),
            ]

        frames = 0 if trace is None else len(trace.frames)
        return _report(message, _fitted(lines, frames=frames, entries=len(diagnosis.log_entries)), fingerprint)


@dataclass(frozen=True)
class UpdateReport:
    result: UpdateResult
    message: Message
    log_entries: tuple[str, ...]
    fingerprint: ProblemFingerprint

    @classmethod
    def of(cls, result: UpdateResult, message: Message, log: CentrumLog) -> UpdateReport:
        return cls(result, message, tuple(log.recent(LOG_ENTRIES)), ProblemFingerprint.of_tool_update(message))

    @property
    def period(self) -> None:
        return None

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        result, fingerprint = self.result, self.fingerprint.digest

        def lines(_dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(self.message),
                "## Aktualizacja narzędzia",
                "",
                f"- Wynik: {result.code}",
                f"- Commit przed: {result.before or 'nieznany'}",
                f"- Commit po: {result.after or 'brak'}",
                f"- Biblioteki instalowane: {'tak' if result.installed else 'nie'}",
                "",
                *_tool_lines(fingerprint, previous),
                *_settings_lines(settings),
                *_log_lines(self.log_entries, dropped_entries),
            ]

        return _report(self.message, _fitted(lines, frames=0, entries=len(self.log_entries)), fingerprint)


@dataclass(frozen=True)
class ReminderReport:
    message: Message
    log_entries: tuple[str, ...]
    fingerprint: ProblemFingerprint

    @classmethod
    def of(cls, message: Message, log: CentrumLog) -> ReminderReport:
        return cls(message, tuple(log.recent(LOG_ENTRIES)), ProblemFingerprint.of_reminders(message))

    @property
    def period(self) -> None:
        return None

    def report(self, *, commit: str | None, previous: int | None, settings: Sequence[str]) -> Report:
        fingerprint = self.fingerprint.digest

        def lines(_dropped_frames: int, dropped_entries: int) -> list[str]:
            return [
                *_message_lines(self.message),
                *_tool_lines(fingerprint, previous, commit=f"- Commit: {commit or 'nieznany'}"),
                *_settings_lines(settings),
                *_log_lines(self.log_entries, dropped_entries),
            ]

        return _report(self.message, _fitted(lines, frames=0, entries=len(self.log_entries)), fingerprint)


ReportSource = StopReport | UpdateReport | ReminderReport


def _message_lines(message: Message) -> list[str]:
    return [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        f"- Kod: {message.code}",
        f"- Co się stało: {message.what}",
        f"- Gdzie: {message.where}",
        f"- Co zrobić: {message.action}",
        "",
    ]


def _tool_lines(fingerprint: str, previous: int | None, *, commit: str | None = None) -> list[str]:
    return [
        "## Narzędzie",
        "",
        *([] if commit is None else [commit]),
        fingerprint_line(fingerprint),
        *([] if previous is None else [f"- Poprzednie Zgłoszenie: #{previous}"]),
        "",
    ]


def _settings_lines(changes: Sequence[str]) -> list[str]:
    return ["## Zmiany Ustawień (30 dni)", "", *(changes or ["- bez zmian"]), ""]


def _report(message: Message, lines: list[str], fingerprint: str) -> Report:
    return Report(title=f"{message.code}: {message.what}", body=_body(lines), fingerprint=fingerprint, what=message.what)


def _guarded(report: Report, period: str | None, forbidden: ForbiddenValues) -> _Preview:
    title = guarded(forbidden, report.title, "tytuł Zgłoszenia")
    body = guarded(forbidden, report.body, "treść Zgłoszenia")
    notes = [*title.notes, *body.notes]
    tail = "" if not notes else "\n## Uwagi techniczne\n\n" + "".join(f"- {note}\n" for note in notes)
    return _Preview(title.text, body.text + tool(tail), report.fingerprint, report.what, period)


def _body(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _fitted(lines: Callable[[int, int], list[str]], *, frames: int, entries: int) -> list[str]:
    steps = [
        *((dropped, 0) for dropped in range(frames + 1)),
        *((frames, dropped) for dropped in range(1, entries + 1)),
    ]

    def fits(step: tuple[int, int]) -> bool:
        return len(_body(lines(*step))) <= PART_LIMIT

    first = 0 if fits(steps[0]) else bisect_left(steps, True, lo=1, key=fits)
    return lines(*steps[min(first, len(steps) - 1)])


def _trace_lines(trace: CallTrace | None, dropped: int) -> list[str]:
    if trace is None:
        return []
    return [
        "## Ślad wywołań",
        "",
        f"- Wyjątek: {trace.exception_type}",
        *(f"- Przyczyna: {cause.exception_type}" for cause in trace.causes),
        *([] if dropped == 0 else [f"- Pominięte pierwsze ramki: {dropped}, pełny ślad wywołań jest w Logach Uruchomienia"]),
        "",
        "```text",
        *(f"{frame.file}:{frame.line} w {frame.function}" for frame in trace.frames[dropped:]),
        "```",
        "",
    ]


def _log_lines(entries: Sequence[str], dropped: int) -> list[str]:
    return [
        "## Dziennik Centrum rozliczeń",
        "",
        *([] if dropped == 0 else [f"Pominięte najstarsze wpisy: {dropped}, żeby Zgłoszenie zmieściło się w jednym issue.", ""]),
        "```text",
        *entries[dropped:],
        "```",
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")




def report_target(fingerprint: str, title: Outgoing) -> OpenIssue:
    return OpenIssue(REPORT.label, tool(fingerprint_line(fingerprint)), title, tool(RETURNED_HEADING))


def _unframed(_number: int, _count: int, text: Outgoing) -> Outgoing:
    return text


@dataclass(frozen=True)
class _Preview:
    title: Outgoing
    body: Outgoing
    fingerprint: str
    what: str
    period: str | None

    @property
    def view(self) -> diagnosis_contract.ReportDraft:
        return diagnosis_contract.ReportDraft(title=self.title, body=self.body)


ReportShown = Callable[[diagnosis_contract.ReportState], None]


class NoPreview(Exception):
    ...

class _Ear:
    def __init__(self, delivered: Callable[[], None], rejected: Callable[[], None]) -> None:
        self._delivered = weakref.WeakMethod(delivered)
        self._rejected = weakref.WeakMethod(rejected)

    def delivered(self) -> None:
        if (heard := self._delivered()) is not None:
            heard()

    def rejected(self) -> None:
        if (heard := self._rejected()) is not None:
            heard()


@dataclass(frozen=True)
class _Desk:
    state_of: Callable[[str], diagnosis_contract.ReportState]
    preview: Callable[[ReportSource], _Preview]
    ask_box: Callable[[str], None]
    queue: Callable[[_Preview], diagnosis_contract.ReportState]
    pending: Callable[[str], bool]
    listen: Callable[[str, _Ear], None]


class ReportHandle:
    def __init__(self, desk: _Desk, fingerprint: str, shown: ReportShown | None) -> None:
        self._desk = desk
        self._fingerprint = fingerprint
        self._shown = shown
        self._changed = threading.Condition()
        self._state = desk.state_of(fingerprint)
        self._preview: _Preview | None = None
        self._asking: threading.Thread | None = None
        self._sends = 0
        self._sending = False
        self._returned = False
        self._ear = _Ear(self._delivered, self._rejected)
        desk.listen(fingerprint, self._ear)

    @property
    def state(self) -> diagnosis_contract.ReportState:
        with self._changed:
            return self._state

    def prepare(self, source: ReportSource) -> diagnosis_contract.ReportDraft:
        preview = self._desk.preview(source)
        comeback = preview if isinstance(source, StopReport) else None
        with self._changed:
            self._preview = preview
            asking = self._asking = threading.Thread(
                target=self._ask, args=(self._sends, comeback), name=REPORT_THREAD, daemon=True
            )
        asking.start()
        return preview.view

    def wait_for_box(self) -> None:
        with self._changed:
            asking = self._asking
        if asking is not None:
            asking.join()

    def _ask(self, sends: int, comeback: _Preview | None) -> None:
        self._desk.ask_box(self._fingerprint)
        with self._changed:
            if sends != self._sends:
                return
            self._show(self._state if self._done else self._desk.state_of(self._fingerprint))
            if comeback is None or self._returned or not isinstance(self._state, diagnosis_contract.ReportWaiting):
                return
            self._returned = self._sending = True
        try:
            self._desk.queue(comeback)
        finally:
            with self._changed:
                self._sending = False
                self._changed.notify_all()

    def send(self) -> diagnosis_contract.ReportState:
        with self._changed:
            while self._sending:
                self._changed.wait()
            preview = self._preview
            if preview is None:
                raise NoPreview
            if self._done:
                return self._state
            self._sending = True
            self._sends += 1
        try:
            state = self._desk.queue(preview)
        except BaseException:
            with self._changed:
                self._sending = False
                self._changed.notify_all()
            raise
        with self._changed:
            self._sending = False
            if isinstance(state, common_contract.Queued) and not self._desk.pending(self._fingerprint):
                state = common_contract.Sent(state="sent")
            self._show(state)
            self._changed.notify_all()
            return state

    def _rejected(self) -> None:
        with self._changed:
            self._show(common_contract.Rejected(state="rejected"))

    def _delivered(self) -> None:
        with self._changed:
            if isinstance(self._state, common_contract.Queued):
                self._show(common_contract.Sent(state="sent"))

    @property
    def _done(self) -> bool:
        return isinstance(self._state, common_contract.Sent | common_contract.Queued)

    def _show(self, state: diagnosis_contract.ReportState) -> None:
        self._state = state
        if self._shown is not None:
            self._shown(state)


class Reports:
    def __init__(
        self,
        work: CentrumWork,
        box: KeyedBox,
        outbox: Outbox,
        commit: CommitSource,
        cases: DadCases,
        *,
        search_deadline_s: float,
        settings_changes: Callable[[], tuple[str, ...]],
    ) -> None:
        self._commit = commit
        self._settings_changes = settings_changes
        self._forbidden = work.forbidden
        self._prefix = work.box_prefix
        self._search_deadline_s = search_deadline_s
        self._cases = cases
        self._queue_directory = outbox.directory
        self._box = box
        self._outbox = outbox
        self._lock = threading.Lock()
        self._open: dict[str, int | None] = {}
        self._numbered: dict[str, int] = {}
        self._ears: dict[str, weakref.WeakSet[_Ear]] = {}
        self._desk = _Desk(
            state_of=self._state_of,
            preview=self._preview,
            ask_box=self._ask_box,
            queue=self._queue,
            pending=self._pending,
            listen=self._listen,
        )
        cases.watch(REPORT, self._heard)

    def handle(self, fingerprint: ProblemFingerprint, *, shown: ReportShown | None = None) -> ReportHandle:
        return ReportHandle(self._desk, fingerprint.digest, shown)

    def _listen(self, fingerprint: str, ear: _Ear) -> None:
        with self._lock:
            self._ears.setdefault(fingerprint, weakref.WeakSet()).add(ear)

    def _heard(self, news: CaseNews) -> None:
        with self._lock:
            if isinstance(news, CaseNumbered):
                self._open[news.case_id] = news.number
                self._numbered[news.case_id] = self._numbered.get(news.case_id, 0) + 1
            ears = list(self._ears.get(news.case_id, ()))
        for ear in ears:
            match news:
                case CaseNumbered():
                    ear.delivered()
                case CaseRejected():
                    ear.rejected()

    def _preview(self, source: ReportSource) -> _Preview:
        fingerprint = source.fingerprint.digest
        sent = [case.number for case in self._cases.all() if case.kind == REPORT and case.id == fingerprint]
        previous = next((number for number in reversed(sent) if number is not None), None)
        report = source.report(commit=self._commit(), previous=previous, settings=self._settings_changes())
        return _guarded(report, source.period, self._forbidden)

    def _queue(self, preview: _Preview) -> diagnosis_contract.ReportState:
        fingerprint = preview.fingerprint
        if self._pending(fingerprint):
            return self._cases.queued(fingerprint, self._box)
        case = Case(REPORT, fingerprint, preview.what, self._commit(), utc_now(), number=None)
        post = Post.of(
            report_target(fingerprint, titled(self._prefix, preview.title)),
            period=preview.period,
            run_id=tool(uuid.uuid4().hex),
            blocks=[preview.body],
            frame=_unframed,
        )
        self._cases.add(case)
        queued = False
        try:
            queued = self._outbox.post(post)
        finally:
            if not queued:
                self._cases.withdraw(case)
        if not queued:
            message = report_messages.not_queued(self._queue_directory)
            return diagnosis_contract.ReportNotQueued(state="not_queued", message=common_contract.Message.of(message))
        if self._outbox.wait_delivered(post.run_id, REPORT.label, timeout_s=DELIVERY_WAIT_S):
            return common_contract.Sent(state="sent")
        return self._cases.queued(fingerprint, self._box)


    def _pending(self, fingerprint: str) -> bool:
        latest = self._cases.find(REPORT, fingerprint)
        return latest is not None and latest.number is None

    def _ask_box(self, fingerprint: str) -> None:
        with self._lock:
            numbered = self._numbered.get(fingerprint, 0)
        answer = within(self._search_deadline_s, lambda: (self._find_open(fingerprint),), name="skrzynka-szukaj")
        if answer is None:
            return
        [found] = answer
        if found is None or isinstance(found, int):
            with self._lock:
                if self._numbered.get(fingerprint, 0) == numbered:
                    self._open[fingerprint] = found

    def _find_open(self, fingerprint: str) -> FindOutcome | NoKey:
        return self._box.find_issue(REPORT.label, fingerprint_line(fingerprint), include_closed=False)

    def _state_of(self, fingerprint: str) -> diagnosis_contract.ReportState:
        latest = self._cases.find(REPORT, fingerprint)
        if latest is not None and latest.number is None:
            return self._cases.queued(fingerprint, self._box)
        with self._lock:
            known = fingerprint in self._open
            waiting = self._open.get(fingerprint) is not None
        if not known:
            waiting = latest is not None and latest.closure is None
        return diagnosis_contract.ReportWaiting(state="waiting") if waiting else diagnosis_contract.ReportReady(state="ready")
