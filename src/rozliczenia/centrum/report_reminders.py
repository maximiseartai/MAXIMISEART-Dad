from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from rozliczenia import register_file
from rozliczenia.centrum import reminder_messages
from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.log import ReminderFailure
from rozliczenia.centrum.reports import ProblemFingerprint, ReminderReport, Reports
from rozliczenia.centrum.settings.files import FieldProblem, Unreadable
from rozliczenia.centrum.settings.owner import CentrumSettings, SettingsSnapshot
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.dad_files import DadFiles
from rozliczenia.message import StopError
from rozliczenia.report_entering import (
    DecisionsUnreadable,
    ReportState,
    StateUnreadable,
    closed_periods,
    register_window,
)
from rozliczenia.tool_files import REMINDERS_RESULT, REMINDERS_SCHEDULES
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.worker_report_inbox import (
    InboxUnreachable,
    MailRefused,
    Mails,
    MailSent,
    PasswordRejected,
    ReminderMailbox,
    SentReminders,
)
from rozliczenia.worker_reports import (
    DEFAULT_REMINDERS,
    OLD_VERSION_SCHEDULES,
    EnteringMemory,
    Pora,
    Reminder,
    ReminderSchedule,
    SchedulesInEffect,
    ScheduleSince,
    SentReminder,
    TimeRange,
    WorkerAddresses,
    reminder_pora,
)

REMINDERS_THREAD: Final = "przypomnienia-o-raporcie"
CHECK_EVERY_S: Final = 60.0
_RESULT_VERSION: Final = 1


class ReminderRhythm(Protocol):
    def start(self, check: Callable[[], None]) -> None:
        ...

    def stop(self) -> None:
        ...


class MinuteRhythm:
    def __init__(self) -> None:
        self._stopped = threading.Event()

    def start(self, check: Callable[[], None]) -> None:
        def loop() -> None:
            while not self._stopped.is_set():
                check()
                self._stopped.wait(CHECK_EVERY_S)

        threading.Thread(target=loop, name=REMINDERS_THREAD, daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()


@dataclass(frozen=True)
class _Failed:
    cause: ReminderFailure
    failure: str | None = None
    retry: bool = True
    file: str | None = None


@dataclass(frozen=True)
class _Unread:
    day: date
    pora: Pora
    file: str


@dataclass
class _Check:
    failed: _Failed | None = None
    footer: Literal["present", "missing"] | None = None
    sent: list[tuple[str, date, datetime]] = field(default_factory=list)


class _Sent(BaseModel):
    worker: str
    day: date
    sent_at: datetime


class _Result(BaseModel):
    schema_version: Literal[1]
    footer: Literal["present", "missing"] | None
    sent: list[_Sent]


@dataclass(frozen=True)
class ShownReminders:
    sent: Mapping[tuple[str, date], tuple[datetime, ...]] = field(default_factory=dict)
    without_footer: bool = False


class ReportReminders:
    def __init__(
        self,
        work: CentrumWork,
        settings: CentrumSettings,
        mailbox: ReminderMailbox,
        files: DadFiles,
        reports: Reports,
        now: Callable[[], datetime],
        entering: ReportState,
    ) -> None:
        self._log = work.log
        self._settings = settings
        self._mailbox = mailbox
        self._files = files
        self._reports = reports
        self._now = now
        self._entering = entering
        self._result = StateFile(
            work.config / REMINDERS_RESULT, work.log, where="wynik Przypomnień o raporcie", pause=work.pause
        )
        self._lock = threading.Lock()
        self._schedules = StateFile(
            work.config / REMINDERS_SCHEDULES, work.log, where="pory Przypomnień o raporcie", pause=work.pause
        )
        self._in_effect: SchedulesInEffect | None = None
        self._settled: tuple[date, Pora, ReminderSchedule] | None = None
        self._last_failure: _Failed | None = None
        self._schedule: ReminderSchedule | None = None
        self._unread: _Unread | None = None
        self._sent_in_work: list[SentReminder] = []

    def check(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._check()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="Przypomnienia o raporcie")
        finally:
            self._lock.release()

    def shown(self) -> ShownReminders:
        try:
            result = _Result.model_validate_json(self._result.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError):
            return ShownReminders()
        sent: dict[tuple[str, date], tuple[datetime, ...]] = {}
        for found in result.sent:
            sent[found.worker, found.day] = (*sent.get((found.worker, found.day), ()), found.sent_at)
        return ShownReminders(sent, without_footer=result.footer == "missing")

    def _check(self) -> None:
        now = self._now()
        snapshot = self._settings.snapshot()
        reminders = snapshot.reminders_or_unreadable
        in_effect: SchedulesInEffect | None = None
        if isinstance(reminders, Unreadable):
            schedule = self._unread_schedule()
        else:
            schedule = self._schedule = reminders.schedule
            if reminders.sends is not None:
                in_effect = self._checked(now, schedule)
        pora = reminder_pora(now, schedule)
        self._close_unread(now.date(), pora)
        if pora is None or self._settled == (now.date(), pora, schedule):
            return
        if isinstance(reminders, Unreadable):
            self._unread = _Unread(now.date(), pora, reminders.name)
            return
        self._unread = None
        if in_effect is None:
            return
        found = _Check()
        if self._schedules.unavailable:
            found.failed = _Failed("zapis-por")
        else:
            self._send(now, snapshot, schedule, in_effect, found)
        failed = found.failed
        if failed is None or not failed.retry:
            self._settled = (now.date(), pora, schedule)
        self._unread = None if failed is None or failed.file is None else _Unread(now.date(), pora, failed.file)
        if failed is not None and failed.file is None and failed != self._last_failure:
            self._log.reminders_failed(cause=failed.cause, failure=failed.failure)
        self._last_failure = failed
        self._write(now, pora, found)

    def _unread_schedule(self) -> ReminderSchedule:
        if self._schedule is not None:
            return self._schedule
        in_effect = schedules_in_effect(self._schedules.path, DEFAULT_REMINDERS.schedule)
        return in_effect.changes[-1].schedule if in_effect.changes else DEFAULT_REMINDERS.schedule

    def _close_unread(self, day: date, pora: Pora | None) -> None:
        unread = self._unread
        if unread is not None and (unread.day, unread.pora) != (day, pora):
            self._log.reminders_failed(cause="plik-bez-odczytu", file=unread.file)
            self._unread = None

    def _checked(self, now: datetime, schedule: ReminderSchedule) -> SchedulesInEffect:
        before = self._in_effect if self._in_effect is not None else schedules_in_effect(self._schedules.path, schedule)
        self._in_effect = before.checked(now, schedule)
        if self._in_effect is not before:
            self._schedules.write(_schedules_document(self._in_effect))
        else:
            self._schedules.retry()
        return self._in_effect

    def _send(
        self, now: datetime, snapshot: SettingsSnapshot, schedule: ReminderSchedule, in_effect: SchedulesInEffect, found: _Check
    ) -> None:
        read = due_reminders(
            now, snapshot, self._mailbox, self._files, in_effect, tuple(self._sent_in_work), self._entering
        )
        match read:
            case NotRead():
                found.failed = _Failed(read.cause, read.failure, file=read.file)
                return
            case PasswordRejected() | InboxUnreachable():
                self._failed(read, found)
                return
            case DueReminders():
                pass
        found.footer = "missing" if read.footer is None else "present"
        found.sent = [*_by_worker(read.sent, read.addresses)]
        for reminder in read.due:
            moment = self._now()
            if (moment.date(), reminder_pora(moment, schedule)) != (now.date(), reminder_pora(now, schedule)):
                return
            outcome = self._mailbox.send(reminder, moment)
            match outcome:
                case MailSent():
                    self._sent_in_work.append(SentReminder(frozenset(reminder.recipients), reminder.day, moment))
                    self._log.reminder_sent(day=reminder.day.isoformat(), pora=_pora(now, schedule))
                    found.sent.append((reminder.worker, reminder.day, moment))
                case MailRefused(cause=cause):
                    found.failed = _Failed("odmowa-wysylki", cause, retry=False)
                case PasswordRejected() | InboxUnreachable():
                    self._failed(outcome, found)
                    return

    def _failed(self, outcome: PasswordRejected | InboxUnreachable, found: _Check) -> None:
        match outcome:
            case PasswordRejected():
                found.failed = _Failed("haslo-odrzucone", retry=False)
                message = reminder_messages.password_rejected()
                handle = self._reports.handle(ProblemFingerprint.of_reminders(message))
                handle.prepare(ReminderReport.of(message, self._log))
                handle.send()
            case InboxUnreachable(cause=cause):
                found.failed = _Failed("brak-sieci", cause)

    def _write(self, now: datetime, pora: Pora, found: _Check) -> None:
        document = {
            "schema_version": _RESULT_VERSION,
            "checked_at": now.astimezone(timezone.utc).isoformat(),
            "pora": pora.value,
            "failure": None if found.failed is None else found.failed.cause,
            "footer": found.footer,
            "sent": [
                {"worker": worker, "day": day.isoformat(), "sent_at": sent_at.astimezone(timezone.utc).isoformat()}
                for worker, day, sent_at in sorted(found.sent)
            ],
        }
        self._result.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


NotReadCause = Literal[
    "bez-wdrozenia", "plik-bez-odczytu", "bez-ustawien", "bez-dostepu", "bez-adresow", "pamiec-wpisania", "okresy", "intermax"
]


@dataclass(frozen=True)
class DueReminders:
    due: tuple[Reminder, ...]
    sent: tuple[SentReminder, ...]
    addresses: WorkerAddresses
    footer: str | None


@dataclass(frozen=True)
class NotRead:
    cause: NotReadCause
    failure: str | None = None
    file: str | None = None


def due_reminders(
    now: datetime,
    snapshot: SettingsSnapshot,
    mailbox: ReminderMailbox,
    files: DadFiles,
    in_effect: SchedulesInEffect,
    sent_in_work: tuple[SentReminder, ...],
    entering: ReportState,
) -> DueReminders | NotRead | PasswordRejected | InboxUnreachable:
    reminders = snapshot.reminders_or_unreadable
    if isinstance(reminders, Unreadable):
        return NotRead("plik-bez-odczytu", file=reminders.name)
    rollout = reminders.sends
    if rollout is None:
        return NotRead("bez-wdrozenia")
    settings = snapshot.folders_or_unreadable
    if isinstance(settings, Unreadable):
        return NotRead("plik-bez-odczytu", file=settings.name)
    legend = snapshot.activity_legend_or_unreadable
    if isinstance(legend, Unreadable):
        return NotRead("plik-bez-odczytu", file=legend.name)
    if settings.register is None or settings.periods_directory is None:
        return NotRead("bez-ustawien")
    if mailbox.access() != "ready":
        return NotRead("bez-dostepu")
    workers = snapshot.workers.counted_or_unreadable()
    if isinstance(workers, Unreadable):
        return NotRead("plik-bez-odczytu", file=workers.name)
    if isinstance(workers, FieldProblem):
        return NotRead("bez-adresow")
    addresses = workers.addresses()
    try:
        memory = EnteringMemory(entering)
    except (StateUnreadable, DecisionsUnreadable) as error:
        return NotRead("pamiec-wpisania", type(error).__name__)
    periods_directory = settings.periods_directory
    try:
        window = memory.window(
            now.date(), lambda periods: closed_periods(periods_directory, periods), reminders_since=rollout
        )
    except StopError:
        return NotRead("okresy")
    try:
        register = register_file.read(settings.register, files, despite_excel_lock=True)
        intermax = register_window(register, window, addresses, copy=False)
    except (WorkbookError, StopError) as error:
        return NotRead("intermax", type(error).__name__)
    mails = mailbox.mails_since(window.first)
    if not isinstance(mails, Mails):
        return mails
    filed = mailbox.sent_reminders(window.first)
    if not isinstance(filed, SentReminders):
        return filed
    sent = _known_sent(filed.reminders, sent_in_work)
    due = memory.reminders(
        now,
        window,
        intermax,
        mails.mails,
        addresses,
        legend,
        sent=sent,
        reminded=workers.reminded(),
        settings=reminders,
        in_effect=in_effect,
    )
    return DueReminders(due, sent, addresses, reminders.footer if reminders.footer.strip() else None)



class _Range(BaseModel):
    od: time
    do: time


class _Schedule(BaseModel):
    poranna: _Range
    wieczorna: _Range
    pierwsze: time

    def schedule(self) -> ReminderSchedule:
        return ReminderSchedule(
            TimeRange(self.poranna.od, self.poranna.do), TimeRange(self.wieczorna.od, self.wieczorna.do), self.pierwsze
        )


class _Since(_Schedule):
    od: datetime


class _Schedules(BaseModel):
    schema_version: Literal[1]
    przed: list[_Schedule] = Field(min_length=1)
    pory: list[_Since]


def schedules_in_effect(path: Path, current: ReminderSchedule) -> SchedulesInEffect:
    try:
        found = _Schedules.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SchedulesInEffect()
    except (OSError, UnicodeDecodeError, ValidationError):
        return SchedulesInEffect(OLD_VERSION_SCHEDULES | {current})
    if any(entry.od.tzinfo is None for entry in found.pory):
        return SchedulesInEffect(OLD_VERSION_SCHEDULES | {current})
    return SchedulesInEffect(
        frozenset(entry.schedule() for entry in found.przed),
        tuple(ScheduleSince(entry.od, entry.schedule()) for entry in sorted(found.pory, key=lambda entry: entry.od)),
    )


def _schedules_document(in_effect: SchedulesInEffect) -> str:
    def shown(schedule: ReminderSchedule) -> dict[str, object]:
        return {
            "poranna": {"od": f"{schedule.morning.start:%H:%M}", "do": f"{schedule.morning.end:%H:%M}"},
            "wieczorna": {"od": f"{schedule.evening.start:%H:%M}", "do": f"{schedule.evening.end:%H:%M}"},
            "pierwsze": f"{schedule.first:%H:%M}",
        }

    document = {
        "schema_version": _RESULT_VERSION,
        "przed": sorted((shown(schedule) for schedule in in_effect.before), key=lambda found: json.dumps(found)),
        "pory": [{"od": change.since.isoformat(), **shown(change.schedule)} for change in in_effect.changes],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _pora(now: datetime, schedule: ReminderSchedule) -> str:
    pora = reminder_pora(now, schedule)
    return "" if pora is None else pora.value


def _known_sent(filed: tuple[SentReminder, ...], in_work: tuple[SentReminder, ...]) -> tuple[SentReminder, ...]:
    return (*filed, *(mine for mine in in_work if not any(mine.same_mail(found) for found in filed)))


def _by_worker(sent: tuple[SentReminder, ...], addresses: WorkerAddresses) -> list[tuple[str, date, datetime]]:
    found: list[tuple[str, date, datetime]] = []
    for reminder in sent:
        reached = {addresses.logins[address] for address in reminder.recipients if address in addresses.logins}
        found += [(worker, reminder.day, reminder.sent_at) for worker in sorted(reached)]
    return found
