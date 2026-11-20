from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
import threading
from typing import Any, Final, Literal, Protocol, TypeVar, final
import uuid

from rozliczenia.centrum import device_forms, legend_forms, refusal, rule_forms
from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.contract.activity_legend import ActivityCodeEdit
from rozliczenia.centrum.contract.quantity_rules import RuleEdit
from rozliczenia.centrum.device_forms import DeviceEdit
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings.activity_legend import LEGEND, Codes, activity_legend, code_ids, legend_refusal
from rozliczenia.centrum.settings.autostart import AUTOSTART, AutostartPlace, Unsupported
from rozliczenia.centrum.settings.files import (
    Bad,
    FieldProblem,
    Good,
    KeyChange,
    Read,
    RemovedLogins,
    RemovedWhat,
    SettingsFile,
    Unreadable,
)
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings, FoldersEdit, dad_folders
from rozliczenia.centrum.settings import inbox
from rozliczenia.centrum.settings.inbox import INBOX, InboxFile
from rozliczenia.centrum.settings.history import (
    ByDad,
    FromRelease,
    History,
    HistoryRead,
    HistoryRow,
    Outside,
    ReleaseOrigin,
    RowChange,
    RowSource,
)
from rozliczenia.centrum.settings.memory import Applied, AppliedResult, AppliedUnknown, Memory, Remembered, settings_bytes
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Refuse, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS, QuantityException, with_exception
from rozliczenia.centrum.settings.quantity_rules import (
    DEVICES,
    RULES,
    ColumnNames,
    DevicesEdit,
    dad_devices_edit,
    device_ids,
    dad_rules_problem,
    devices_for_dad_rules,
    devices_problem,
    listed_name,
    quantity_rules,
    rule_ids,
    rules_problem,
    taken_problem,
)
from rozliczenia.centrum.settings.reminders import REMINDERS, RemindersEdit, dad_reminders
from rozliczenia.centrum.settings.settlement_mail import SETTLEMENT_MAIL, WrittenMail, written
from rozliczenia.centrum.settings.workers import WORKERS, AddWorker, WorkersEdit, dad_workers
from rozliczenia.activity_legend import ActivityCode, ActivityLegend
from rozliczenia.quantity_engine import Component, DeviceList, QuantityRule, QuantityRules
from rozliczenia.settlement_mailing import SettlementMailSettings
from rozliczenia.worker_list import Unresolved, Worker, WorkerList
from rozliczenia.worker_periods import InPeriod, InRegister, NotInPeriods, Unchecked, WorkerPeriods
from rozliczenia.worker_report_inbox import InboxState
from rozliczenia.worker_reports import ReminderSettings

T = TypeVar("T")

REPORTED_CHANGES: Final = 20
HISTORY_UNREADABLE: Final = "- Historii Ustawień nie dało się przeczytać"
_RulesEdit = Callable[[tuple[QuantityRule, ...]], tuple[QuantityRule, ...] | FieldProblem]


_PairCheck = Callable[[Any], FieldProblem | Unreadable | None]


@final
@dataclass(frozen=True)
class ShownWorkers:
    state: Literal["good", "bad", "unreadable"]
    workers: tuple[Worker, ...]
    unresolved: tuple[Unresolved, ...]
    problem: FieldProblem | None


@final
@dataclass(frozen=True)
class WorkerListRead:
    _read: Read[WorkerList] | Unreadable

    def counted(self) -> WorkerList:
        match self.counted_or_unreadable():
            case Unreadable():
                raise refusal.workers_unusable(None)
            case FieldProblem() as problem:
                raise refusal.workers_unusable(problem)
            case WorkerList() as workers:
                return workers

    def counted_or_unreadable(self) -> WorkerList | Unreadable | FieldProblem:
        return _counted(self._read, WORKERS)

    def problem(self) -> FieldProblem | Unreadable | None:
        match self._read:
            case Good():
                return None
            case Bad(problem=problem):
                return problem
            case Unreadable() as unreadable:
                return unreadable

    def last_good(self) -> FieldProblem | None:
        read = self._read
        return read.problem if isinstance(read, Bad) and read.usable is not None else None

    def shown(self) -> ShownWorkers:
        match self._read:
            case Good(value=workers):
                return ShownWorkers("good", workers.workers, workers.unresolved, None)
            case Bad(problem=problem, usable=usable):
                listed = WorkerList(()) if usable is None else usable
                return ShownWorkers("bad", listed.workers, listed.unresolved, problem)
            case Unreadable():
                return ShownWorkers("unreadable", (), (), FieldProblem(None, messages.worker_list_unreadable()))


@dataclass(frozen=True)
class SettingsSnapshot:
    folders_or_unreadable: FolderSettings | Unreadable
    workers: WorkerListRead
    inbox: InboxState
    reminders_or_unreadable: ReminderSettings | Unreadable
    quantity_rules_or_unreadable: QuantityRules | Unreadable
    activity_legend_or_unreadable: ActivityLegend | Unreadable
    settlement_mail_or_unreadable: SettlementMailSettings | Unreadable | FieldProblem

    @property
    def folders(self) -> FolderSettings:
        return _readable(self.folders_or_unreadable)

    @property
    def reminders(self) -> ReminderSettings:
        return _readable(self.reminders_or_unreadable)

    @property
    def quantity_rules(self) -> QuantityRules:
        return _readable(self.quantity_rules_or_unreadable)

    @property
    def activity_legend(self) -> ActivityLegend:
        return _readable(self.activity_legend_or_unreadable)

    @property
    def settlement_mail(self) -> SettlementMailSettings:
        mail = self.settlement_mail_or_unreadable
        if isinstance(mail, FieldProblem):
            raise refusal.settlement_mail_unusable(mail)
        return _readable(mail)


def _readable(value: T | Unreadable) -> T:
    if isinstance(value, Unreadable):
        raise refusal.settings_file_unreadable(value.name)
    return value


@final
@dataclass(frozen=True)
class ShownQuantityRules:
    rules: tuple[QuantityRule, ...]
    devices: DeviceList


@final
@dataclass(frozen=True)
class ShownActivityLegend:
    codes: tuple[ActivityCode, ...]


@dataclass(frozen=True)
class QuantityRulesView:
    rules_or_unreadable: QuantityRules | Unreadable
    shown: ShownQuantityRules
    rules_problem: FieldProblem | None
    devices_problem: FieldProblem | None
    source_rules: tuple[QuantityRule, ...] | Unreadable
    exceptions: tuple[QuantityException, ...]
    exceptions_problem: FieldProblem | None

    @property
    def rules(self) -> QuantityRules:
        return _readable(self.rules_or_unreadable)


@dataclass(frozen=True)
class ActivityLegendView:
    shown: ShownActivityLegend
    problem: FieldProblem | None
    codes: tuple[ActivityCode, ...] | Unreadable


@dataclass(frozen=True)
class SettlementMailView:
    read: Read[SettlementMailSettings] | Unreadable
    shown: WrittenMail


@dataclass(frozen=True)
class SettingsView:
    folders: Read[FolderSettings] | Unreadable
    workers: WorkerListRead
    inbox: Read[InboxFile] | Unreadable
    autostart: Read[bool] | Unreadable | Unsupported
    reminders: Read[ReminderSettings] | Unreadable
    settlement_mail: SettlementMailView


@dataclass(frozen=True)
class Saved:
    change: str | None


@dataclass(frozen=True)
class Refused:
    problem: FieldProblem


@dataclass(frozen=True)
class NotSaved:
    unreadable: str | None = None


@dataclass(frozen=True)
class KeptInPeriods:
    presence: InRegister | InPeriod | Unchecked
    what: RemovedWhat


@dataclass(frozen=True)
class NotUndoable:
    known: bool


class SettingsReads(Protocol):
    def snapshot(self) -> SettingsSnapshot: ...

    def folders(self) -> FolderSettings: ...

    def quantity_rules(self) -> QuantityRulesView: ...

    def counted_activity_legend(self) -> ActivityLegend: ...


class _Place(Protocol):
    def unsupported(self) -> FieldProblem | None:
        ...

    def read(self) -> bytes | None | OSError:
        ...

    def write(self, data: bytes | None) -> None:
        ...


@dataclass(frozen=True)
class _ConfigFile:
    path: Path
    pause: Callable[[float], None]

    def unsupported(self) -> FieldProblem | None:
        return None

    def read(self) -> bytes | None | OSError:
        return settings_bytes(self.path)

    def write(self, data: bytes | None) -> None:
        if data is None:
            self.path.unlink(missing_ok=True)
        else:
            replace_atomically(self.path, data, pause=self.pause)


class CentrumSettings:
    def __init__(
        self,
        config: Path,
        *,
        log: CentrumLog,
        now: Callable[[], datetime],
        pause: Callable[[float], None],
        autostart: Autostart,
        periods: WorkerPeriods,
        column_names: ColumnNames,
        release_changes: tuple[ReleaseChange[Any], ...],
        release_origin: Callable[[], ReleaseOrigin],
    ) -> None:
        self._config = config
        self._log = log
        self._now = now
        self._pause = pause
        self._periods = periods
        self._column_names = column_names
        self._release_changes = release_changes
        self._release_origin = release_origin
        self._memory = Memory(config, pause)
        self._history = History(config, pause)
        self._lock = threading.Lock()
        self._absent: dict[str, str] = {}
        self._places: Mapping[str, _Place] = {
            FOLDERS.name: _ConfigFile(config / FOLDERS.name, pause),
            WORKERS.name: _ConfigFile(config / WORKERS.name, pause),
            REMINDERS.name: _ConfigFile(config / REMINDERS.name, pause),
            SETTLEMENT_MAIL.name: _ConfigFile(config / SETTLEMENT_MAIL.name, pause),
            INBOX.name: _ConfigFile(config / INBOX.name, pause),
            AUTOSTART.name: AutostartPlace(autostart),
            DEVICES.name: _ConfigFile(config / DEVICES.name, pause),
            RULES.name: _ConfigFile(config / RULES.name, pause),
            EXCEPTIONS.name: _ConfigFile(config / EXCEPTIONS.name, pause),
            LEGEND.name: _ConfigFile(config / LEGEND.name, pause),
        }

    def snapshot(self) -> SettingsSnapshot:
        with self._lock:
            folders = _or_unreadable(self._observe(FOLDERS), FOLDERS)
            workers = self._observe(WORKERS)
            inbox_state = inbox.state(self._observe(INBOX))
            reminders = _or_unreadable(self._observe(REMINDERS), REMINDERS)
            mail = _counted(self._observe(SETTLEMENT_MAIL), SETTLEMENT_MAIL)
            rules = self._quantity_rules()
            return SettingsSnapshot(
                folders_or_unreadable=folders,
                workers=WorkerListRead(workers),
                inbox=inbox_state,
                reminders_or_unreadable=reminders,
                quantity_rules_or_unreadable=rules.rules_or_unreadable,
                activity_legend_or_unreadable=self._activity_legend(),
                settlement_mail_or_unreadable=mail,
            )

    def folders(self) -> FolderSettings:
        return _readable(self.folders_or_unreadable())

    def folders_or_unreadable(self) -> FolderSettings | Unreadable:
        with self._lock:
            return _or_unreadable(self._observe(FOLDERS), FOLDERS)

    def quantity_rules(self) -> QuantityRulesView:
        with self._lock:
            return self._quantity_rules()

    def activity_legend(self) -> ActivityLegendView:
        with self._lock:
            observed = self._observe(LEGEND)
            codes = _usable(observed, LEGEND)
            shown = ShownActivityLegend(activity_legend(_or_release(observed, LEGEND)).codes)
            return ActivityLegendView(shown, _problem(observed, LEGEND, messages.unreadable), codes)

    def counted_activity_legend(self) -> ActivityLegend:
        with self._lock:
            return _readable(self._activity_legend())

    def _activity_legend(self) -> ActivityLegend | Unreadable:
        legend = self._observe(LEGEND)
        return legend if isinstance(legend, Unreadable) else activity_legend(_value(legend, LEGEND))

    def view(self) -> SettingsView:
        with self._lock:
            autostart = self._places[AUTOSTART.name].unsupported()
            return SettingsView(
                folders=self._observe(FOLDERS),
                workers=WorkerListRead(self._observe(WORKERS)),
                inbox=self._observe(INBOX),
                autostart=Unsupported() if autostart is not None else self._observe(AUTOSTART),
                reminders=self._observe(REMINDERS),
                settlement_mail=self._settlement_mail(),
            )

    def _settlement_mail(self) -> SettlementMailView:
        data = self._places[SETTLEMENT_MAIL.name].read()
        if isinstance(data, OSError):
            return SettlementMailView(Unreadable(SETTLEMENT_MAIL.name), _shown_mail(SETTLEMENT_MAIL.default))
        read = self._observed(SETTLEMENT_MAIL, data)
        match read:
            case Good(value=value) | Bad(usable=value) if value is not None:
                shown = _shown_mail(value)
            case _:
                shown = written(data) or _shown_mail(SETTLEMENT_MAIL.default)
        return SettlementMailView(read, shown)

    def change_folders(self, edit: FoldersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        current = self.folders_or_unreadable()
        before = None if isinstance(current, Unreadable) else current.periods_directory
        return self._by_dad(FOLDERS, dad_folders(edit, before), undoes=None)

    def change_autostart(self, enabled: bool) -> Saved | Refused | NotSaved | KeptInPeriods:
        return self._by_dad(AUTOSTART, lambda _: enabled, undoes=None)

    def change_inbox_password(self, typed: str) -> Saved | Refused | NotSaved | KeptInPeriods:
        with self._lock:
            password = inbox.new_password(self._observe(INBOX), typed)
        if isinstance(password, FieldProblem):
            return Refused(password)
        return self._by_dad(INBOX, lambda current: inbox.with_password(current, password), undoes=None)

    def change_reminders(self, edit: RemindersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        return self._by_dad(REMINDERS, lambda current: dad_reminders(current, edit), undoes=None)

    def change_settlement_mail(self, form: SettlementMailSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
        return self._by_dad(SETTLEMENT_MAIL, lambda _: form, undoes=None)

    def change_workers(self, edit: WorkersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        unusable = None if isinstance(edit, AddWorker) else refusal.workers_unusable
        return self._by_dad(WORKERS, lambda current: dad_workers(current, edit), undoes=None, unusable=unusable)

    def change_exceptions(self, exception: QuantityException) -> Saved | Refused | NotSaved | KeptInPeriods:
        return self._by_dad(EXCEPTIONS, lambda current: with_exception(current, exception), undoes=None)

    def change_devices(self, edit: DeviceEdit) -> Saved | Refused | NotSaved:
        return self._with_used_keys(DEVICES, lambda current, keys: device_forms.dad_devices(current, edit, device_ids(keys)))

    def change_rules(self, edit: RuleEdit) -> Saved | Refused | NotSaved:
        return self._with_used_keys(RULES, lambda current, keys: rule_forms.dad_rules(current, edit, rule_ids(keys)))

    def change_legend(self, edit: ActivityCodeEdit) -> Saved | Refused | NotSaved:
        return self._with_used_keys(LEGEND, lambda current, keys: legend_forms.dad_legend(current, edit, code_ids(keys)))

    def _with_used_keys(
        self, file: SettingsFile[T], edit: Callable[[T, frozenset[str]], T | FieldProblem]
    ) -> Saved | Refused | NotSaved:
        with self._lock:
            keys = self._used_keys(file)
            if isinstance(keys, Unreadable):
                self._log.settings_unreadable(cause="historia")
                return NotSaved()
            return self._dad_change(file, lambda current: edit(current, keys), undoes=None, checked=frozenset())

    def rules_after(self, edit: RuleEdit) -> QuantityRules | FieldProblem | NotSaved:
        with self._lock:
            paired = self._rules_after(lambda current: rule_forms.dad_rules(current, edit, frozenset()))
            if isinstance(paired, FieldProblem | NotSaved):
                return paired
            return QuantityRules(paired[0], DeviceList(paired[1]))

    def legend_after(self, edit: ActivityCodeEdit) -> ActivityLegend | FieldProblem | NotSaved:
        with self._lock:
            current = _usable(self._observe_for_change(LEGEND), LEGEND)
            if isinstance(current, Unreadable):
                return NotSaved(LEGEND.name)
            codes = legend_refusal(legend_forms.dad_legend(current, edit, frozenset()))
            if isinstance(codes, FieldProblem):
                return codes
            parsed = LEGEND.parse(LEGEND.dump(codes))
            return parsed if isinstance(parsed, FieldProblem) else activity_legend(parsed)

    def _counts_release_rules(self) -> bool:
        return self._places[RULES.name].read() is None

    def _used_keys(self, file: SettingsFile[Any]) -> frozenset[str] | Unreadable:
        history = self._history.read()
        if isinstance(history, Unreadable):
            return history
        return frozenset(change.key for row in history.rows if row.file == file.name for change in row.changes)

    def undo(self, row_id: str) -> Saved | Refused | NotSaved | NotUndoable | KeptInPeriods:
        with self._lock:
            history = self._history.read()
            if isinstance(history, Unreadable):
                self._log.settings_unreadable(cause="historia")
                return NotSaved()
            row = next((row for row in history.rows if row.id == row_id), None)
            if row is None:
                return NotUndoable(known=False)
            file = _UNDOABLE.get(row.file)
            if file is None or not row.undoable or row.result != "zapisano":
                return NotUndoable(known=True)
            changes = row.key_changes()
        return self._by_dad(file, lambda current: file.restore(current, changes), undoes=row)

    def history(self) -> HistoryRead | Unreadable:
        with self._lock:
            for file in _FILES.values():
                if self._places[file.name].unsupported() is None:
                    self._observe(file)
            read = self._history.read()
            if isinstance(read, Unreadable):
                return read
            rows = tuple(row if row.file in _UNDOABLE else row.model_copy(update={"undoable": False}) for row in read.rows)
            return read.model_copy(update={"rows": rows})

    def apply_release_changes(self) -> None:
        changes = self._release_changes
        with self._lock:
            remembered = self._memory.applied()
            if isinstance(remembered, AppliedUnknown):
                for change in changes:
                    self._log.settings_release(change=change.id, result="bez-pamieci")
                applied: dict[str, Applied] = {}
            else:
                applied = remembered
                self._apply_pending(changes, applied, self._release_origin)
            self._absent = {
                change.file.name: sentence
                for change in changes
                if (sentence := _absent_sentence(change, applied, self._config)) is not None
            }

    def _apply_pending(
        self, changes: tuple[ReleaseChange[Any], ...], applied: dict[str, Applied], origin: Callable[[], ReleaseOrigin]
    ) -> None:
        pending = [change for change in changes if change.id not in applied]
        if not pending:
            return
        in_history = self._release_rows()
        if isinstance(in_history, Unreadable):
            for change in pending:
                self._log.settings_release(change=change.id, result="bez-historii")
            return
        version: ReleaseOrigin | None = None
        for change in pending:
            done = in_history.get(change.id)
            if done is None:
                version = version or origin()
                try:
                    result = self._apply(change, version)
                except Exception as failure:
                    self._log.unexpected_failure(failure, where=f"zmiana Ustawień z Wydania {change.id}")
                    continue
                if result is None:
                    continue
                done = Applied(at=self._now(), release=version.release, commit=version.commit, result=result)
            applied[change.id] = done
            try:
                self._memory.remember_applied(applied)
            except OSError:
                self._log.settings_release(change=change.id, result="bez-pamieci")

    def _release_rows(self) -> dict[str, Applied] | Unreadable:
        history = self._history.read()
        if isinstance(history, Unreadable):
            return history
        found: dict[str, Applied] = {}
        for row in history.rows:
            if isinstance(row.source, FromRelease) and row.source.change not in found:
                found[row.source.change] = Applied(
                    at=row.at,
                    release=row.source.release,
                    commit=row.source.commit,
                    result="zastosowano" if row.result == "zapisano" else "odrzucono",
                )
        return found

    def _apply(self, change: ReleaseChange[T], version: ReleaseOrigin) -> AppliedResult | None:
        source = FromRelease(release=version.release, commit=version.commit, change=change.id)
        match change.propose(ReleaseInputs(self._observe(change.file), self._config)):
            case Nothing():
                result: AppliedResult | None = "bez-zmian"
            case Later():
                self._log.settings_release(change=change.id, result="pozniej")
                return None
            case Refuse(sentence=sentence):
                result = self._refuse(change.file, source, sentence)
            case Edit(edit=edit, undoable=undoable):
                match self._change(change.file, edit, undoes=None, source=source, undoable=undoable, checked=None):
                    case Saved(change=row):
                        result = "bez-zmian" if row is None else "zastosowano"
                    case Refused(problem=problem):
                        result = self._refuse(change.file, source, problem.sentence)
                    case NotSaved():
                        result = None
        self._log.settings_release(change=change.id, result="bez-zapisu" if result is None else result)
        return result

    def _refuse(self, file: SettingsFile[T], source: FromRelease, sentence: str) -> AppliedResult | None:
        row = self._row(file, (), source, undoes=None, undoable=False, created=False, removed=False).model_copy(
            update={"result": "odrzucono", "reason": sentence}
        )
        try:
            self._history.append(row)
        except OSError:
            return None
        return "odrzucono"

    def reported_changes(self, days: int = 30) -> tuple[str, ...]:
        history = self.history()
        if isinstance(history, Unreadable):
            return (HISTORY_UNREADABLE,)
        since = self._now() - timedelta(days=days)
        rows = [row for row in history.rows if row.at >= since][:REPORTED_CHANGES]
        return tuple(_reported(row) for row in rows)

    def _quantity_rules(self) -> QuantityRulesView:
        rules = self._observe(RULES)
        devices = self._observe(DEVICES)
        exceptions = self._observe(EXCEPTIONS)
        source_rules = _usable(rules, RULES)
        usable_rules, usable_devices = _or_release(rules, RULES), _or_release(devices, DEVICES)
        waiting = devices_for_dad_rules(usable_devices, usable_rules, usable_rules) if self._counts_release_rules() else None
        unreadable = next((read for read in (rules, devices) if isinstance(read, Unreadable)), None)
        shown = quantity_rules(usable_rules, usable_devices)
        return QuantityRulesView(
            shown if unreadable is None else unreadable,
            ShownQuantityRules(shown.rules, shown.devices),
            _problem(rules, RULES, messages.unreadable) or (waiting if isinstance(waiting, FieldProblem) else None),
            _problem(devices, DEVICES, messages.unreadable) or taken_problem(usable_rules, usable_devices),
            source_rules,
            _or_release(exceptions, EXCEPTIONS),
            _problem(exceptions, EXCEPTIONS, messages.unavailable),
        )

    def _checked(
        self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem
    ) -> T | FieldProblem | Unreadable:
        together: Mapping[str, _PairCheck] = {
            RULES.name: self._rules_problem,
            DEVICES.name: self._devices_problem,
        }
        return _paired(file, data, parsed, together)

    def _rules_problem(self, rules: tuple[QuantityRule, ...]) -> FieldProblem | Unreadable | None:
        data = self._places[DEVICES.name].read()
        return _rules_problem(rules, data, self._memory.read(DEVICES.name))

    def _devices_problem(self, devices: tuple[Component, ...]) -> FieldProblem | Unreadable | None:
        rules = self._observe(RULES)
        if isinstance(rules, Unreadable):
            return rules
        return devices_problem(
            devices,
            _value(rules, RULES),
            _last_good_devices(self._memory.read(DEVICES.name)),
            release=self._counts_release_rules(),
        )

    def _by_dad(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: HistoryRow | None,
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved | KeptInPeriods:
        with self._lock:
            removed = self._removed_logins(file, edit)
            if removed is None:
                return self._dad_change(file, edit, undoes=undoes, checked=frozenset(), unusable=unusable)
            folders = _usable(self._observe(FOLDERS), FOLDERS)
            if isinstance(folders, Unreadable):
                self._log.settings_unreadable(cause="dostep")
                return NotSaved(FOLDERS.name)
        presence = self._periods.find(removed.logins, folders.register, folders.periods_directory)
        if not isinstance(presence, NotInPeriods):
            return KeptInPeriods(presence, removed.what)
        with self._lock:
            return self._dad_change(file, edit, undoes=undoes, checked=removed.logins, unusable=unusable)

    def _dad_change(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: HistoryRow | None,
        checked: frozenset[str],
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved:
        paired: Mapping[str, Callable[..., Saved | Refused | NotSaved]] = {
            DEVICES.name: self._dad_devices,
            RULES.name: self._dad_rules,
            LEGEND.name: self._dad_legend,
        }
        write = paired.get(file.name)
        if write is None:
            return self._change(file, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked, unusable=unusable)
        return write(edit, undoes=undoes, checked=checked)

    def _dad_legend(self, edit: Callable[[Codes], Codes | FieldProblem], *, undoes: HistoryRow | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        return self._change(LEGEND, lambda current: legend_refusal(edit(current)), undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _dad_devices(self, edit: DevicesEdit, *, undoes: HistoryRow | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        rules = _usable(self._observe_for_change(RULES), RULES)
        if isinstance(rules, Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved(RULES.name)
        changed = dad_devices_edit(edit, rules, self._column_names, release=self._counts_release_rules())
        return self._change(DEVICES, changed, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _dad_rules(self, edit: _RulesEdit, *, undoes: HistoryRow | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        paired = self._rules_after(edit)
        if isinstance(paired, FieldProblem):
            return Refused(paired)
        if isinstance(paired, NotSaved):
            self._log.settings_unreadable(cause="dostep")
            return paired
        _, devices = paired
        if devices != _or_release(self._observe(DEVICES), DEVICES):
            listed = self._change(DEVICES, lambda _: devices, undoes=None, source=ByDad(), undoable=True, checked=checked)
            if not isinstance(listed, Saved):
                return listed
        return self._change(RULES, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _rules_after(
        self, edit: _RulesEdit
    ) -> tuple[tuple[QuantityRule, ...], tuple[Component, ...]] | FieldProblem | NotSaved:
        current = _usable(self._observe_for_change(RULES), RULES)
        if isinstance(current, Unreadable):
            return NotSaved(RULES.name)
        rules = edit(current)
        if isinstance(rules, FieldProblem):
            return rules
        devices = _usable(self._observe_for_change(DEVICES), DEVICES)
        if isinstance(devices, Unreadable):
            return NotSaved(DEVICES.name)
        if self._counts_release_rules():
            needed = devices_for_dad_rules(devices, rules, current)
            if isinstance(needed, FieldProblem):
                return needed
            devices = needed
        problem = dad_rules_problem(rules, devices, self._column_names, self._listed_name)
        return (rules, devices) if problem is None else problem

    def _listed_name(self, component: str) -> str:
        history = self._history.read()
        rows = () if isinstance(history, Unreadable) else history.rows
        return listed_name(component, (change.change() for row in rows if row.file == DEVICES.name for change in row.changes))

    def _removed_logins(self, file: SettingsFile[T], edit: Callable[[T], T | FieldProblem]) -> RemovedLogins | None:
        if file.removed_logins is None:
            return None
        current = _usable(self._observe_for_change(file), file)
        if isinstance(current, Unreadable):
            return None
        value = edit(current)
        return None if isinstance(value, FieldProblem) else file.removed_logins(current, value)

    def _change(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: HistoryRow | None,
        source: RowSource,
        undoable: bool,
        checked: frozenset[str] | None,
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved:
        place = self._places[file.name]
        unsupported = place.unsupported()
        if unsupported is not None:
            return Refused(unsupported)
        data = self._bytes_for_change(place, file.name)
        if isinstance(data, Unreadable) or isinstance(self._memory.read(file.name), Unreadable):
            self._log.settings_unreadable(cause="dostep")
            if isinstance(data, Unreadable) and unusable is not None:
                raise unusable(None)
            return NotSaved()
        observed = self._observed(file, data)
        if isinstance(observed, Bad) and observed.usable is None and unusable is not None:
            raise unusable(observed.problem)
        if isinstance(observed, Bad) and file.secret and observed.usable is None:
            return Refused(observed.problem)
        current = _value(observed, file)
        value = edit(current)
        if isinstance(value, FieldProblem):
            return Refused(value)
        new = None if self._restores_absence(file, undoes, value) else file.dump(value)
        edited = self._checked(file, new, file.parse(new))
        if isinstance(edited, Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved(edited.name)
        if isinstance(edited, FieldProblem):
            return Refused(edited)
        if checked is not None and file.removed_logins is not None:
            removed = file.removed_logins(current, edited)
            if removed is not None and not removed.logins <= checked:
                return Refused(FieldProblem(None, messages.worker_list_changed()))
        changes = file.diff(current, edited)
        if not changes and isinstance(observed, Good):
            return Saved(change=None)
        if isinstance(observed, Bad) and data is not None and not file.secret:
            self._memory.keep_rejected(file.name, data, self._now())
        row = (
            self._row(file, changes, source, undoes=undoes, undoable=undoable, created=data is None, removed=new is None)
            if changes
            else None
        )
        try:
            place.write(new)
        except OSError:
            return NotSaved()
        if row is not None:
            try:
                self._history.append(row)
            except OSError:
                self._put_back(place, data)
                return NotSaved()
        self._remember(file, Remembered(seen=new, good=new))
        if row is None:
            return Saved(change=None)
        keys = tuple(dict.fromkeys(file.logged(change.key) for change in changes))
        self._log.settings_changed(file=file.name, keys=keys, source=source.kind)
        return Saved(change=row.id)

    def _put_back(self, place: _Place, data: bytes | None) -> None:
        try:
            place.write(data)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="przywrócenie Ustawień po nieudanym wierszu Historii")

    def _remember(self, file: SettingsFile[T], remembered: Remembered) -> None:
        if file.secret:
            remembered = Remembered(seen=_seen(file, remembered.seen), good=None)
        try:
            self._memory.write(file.name, remembered)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="pamięć Ustawień")

    def _bytes_for_change(self, place: _Place, name: str) -> bytes | None | Unreadable:
        data = place.read()
        for seconds in RETRY_PAUSES_S:
            if not isinstance(data, OSError):
                break
            self._pause(seconds)
            data = place.read()
        return Unreadable(name) if isinstance(data, OSError) else data

    def _observe(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        data = self._places[file.name].read()
        if isinstance(data, OSError):
            return Unreadable(file.name)
        return self._observed(file, data)

    def _observe_for_change(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        data = self._bytes_for_change(self._places[file.name], file.name)
        return data if isinstance(data, Unreadable) else self._observed(file, data)

    def _observed(self, file: SettingsFile[T], data: bytes | None) -> Read[T]:
        compared = self._compared(file, data)
        absent = self._absent.get(file.name)
        if data is None and absent is not None:
            return Bad(FieldProblem(None, absent), None)
        return _with_secret_value(file, compared, data)

    def _compared(self, file: SettingsFile[T], data: bytes | None) -> Read[T]:
        parsed = self._checked(file, data, file.parse(data))
        remembered = self._memory.read(file.name)
        if isinstance(parsed, Unreadable):
            return _pair_waits(file, parsed, remembered.good if isinstance(remembered, Remembered) else None)
        if isinstance(remembered, Unreadable):
            return _read(parsed, None)
        if remembered is None:
            if isinstance(parsed, FieldProblem):
                self._log.settings_bad(file=file.name, field=parsed.place or "plik")
            self._remember(file, Remembered(seen=data, good=None if isinstance(parsed, FieldProblem) else data))
            return _read(parsed, None)
        good = None if remembered.good is None else _good_value(remembered.good, file)
        before = file.default if good is None else good
        if _seen(file, data) == remembered.seen and (isinstance(parsed, FieldProblem) or file.secret or remembered.good == data):
            return _read(parsed, good)
        try:
            self._history.append(self._outside_row(file, data, parsed, before, created=remembered.seen is None))
        except OSError:
            self._log.settings_external(file=file.name, result="bez-zapisu")
            return _read(parsed, good)
        self._remember(file, Remembered(seen=data, good=remembered.good if isinstance(parsed, FieldProblem) else data))
        if isinstance(parsed, FieldProblem):
            self._log.settings_bad(file=file.name, field=parsed.place or "plik")
            self._log.settings_external(file=file.name, result="odrzucono")
            return Bad(parsed, good)
        self._log.settings_external(file=file.name, result="zapisano")
        return Good(parsed)

    def _outside_row(
        self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, before: T, *, created: bool
    ) -> HistoryRow:
        if isinstance(parsed, FieldProblem):
            return self._row(
                file, (), Outside(), undoes=None, undoable=False, created=created, removed=data is None
            ).model_copy(update={"result": "odrzucono", "reason": parsed.sentence})
        changes = file.diff(before, parsed)
        return self._row(
            file, changes, Outside(), undoes=None, undoable=bool(changes), created=created, removed=data is None
        )

    def _restores_absence(self, file: SettingsFile[T], undoes: HistoryRow | None, value: T) -> bool:
        if undoes is None or not undoes.created:
            return False
        if any(change.refused_absent is not None or change.waiting is not None for change in self._release_changes if change.file is file):
            return False
        history = self._history.read()
        if isinstance(history, Unreadable):
            return False
        rows = [row for row in history.rows if row.file == file.name]
        position = next((index for index, row in enumerate(rows) if row.id == undoes.id), None)
        if position is None:
            return False
        first: dict[str, KeyChange] = {}
        for row in reversed(rows[: position + 1]):
            for change in row.key_changes():
                first.setdefault(change.key, change)
        restored = file.restore(value, tuple(first.values()))
        return not isinstance(restored, FieldProblem) and not file.diff(restored, value)

    def _row(
        self,
        file: SettingsFile[T],
        changes: tuple[KeyChange, ...],
        source: RowSource,
        *,
        undoes: HistoryRow | None,
        undoable: bool,
        created: bool,
        removed: bool,
    ) -> HistoryRow:
        sections = {_SECTION.split(change.key, maxsplit=1)[0] for change in changes}
        return HistoryRow(
            id=uuid.uuid4().hex,
            at=self._now(),
            source=source,
            undoes=None if undoes is None else undoes.id,
            file=file.name,
            section=next(iter(sections)) if len(sections) == 1 else None,
            changes=tuple(RowChange(key=change.key, before=None, after=None) if file.secret else RowChange.of(change) for change in changes),
            secret=file.secret,
            undoable=undoable and not file.secret,
            result="zapisano",
            reason=None,
            created=created,
            removed=removed,
        )


_FILES: Final[Mapping[str, SettingsFile[Any]]] = {
    FOLDERS.name: FOLDERS,
    WORKERS.name: WORKERS,
    REMINDERS.name: REMINDERS,
    SETTLEMENT_MAIL.name: SETTLEMENT_MAIL,
    AUTOSTART.name: AUTOSTART,
    DEVICES.name: DEVICES,
    RULES.name: RULES,
    EXCEPTIONS.name: EXCEPTIONS,
    LEGEND.name: LEGEND,
    INBOX.name: INBOX,
}
_UNDOABLE: Final[Mapping[str, SettingsFile[Any]]] = {name: file for name, file in _FILES.items() if not file.secret}
_SECTION: Final = re.compile(r"[.\[]")


def read_snapshot(config: Path) -> SettingsSnapshot:
    remembered_devices = Memory(config, lambda _: None).read(DEVICES.name)
    devices_data = settings_bytes(config / DEVICES.name)
    rules = _read_only(config, RULES, {RULES.name: lambda value: _rules_problem(value, devices_data, remembered_devices)})
    release = settings_bytes(config / RULES.name) is None
    devices = _read_only(
        config,
        DEVICES,
        {DEVICES.name: lambda value: devices_problem(value, rules, _last_good_devices(remembered_devices), release=release)},
    )
    folders = _or_unreadable(_read_only_view(config, FOLDERS), FOLDERS)
    reminders = _or_unreadable(_read_only_view(config, REMINDERS), REMINDERS)
    codes = _or_unreadable(_read_only_view(config, LEGEND), LEGEND)
    mail = _counted(_read_only_view(config, SETTLEMENT_MAIL), SETTLEMENT_MAIL)
    return SettingsSnapshot(
        folders_or_unreadable=folders,
        workers=WorkerListRead(_read_only_view(config, WORKERS)),
        inbox=inbox.state(_read_only_view(config, INBOX)),
        reminders_or_unreadable=reminders,
        quantity_rules_or_unreadable=quantity_rules(rules, devices),
        activity_legend_or_unreadable=codes if isinstance(codes, Unreadable) else activity_legend(codes),
        settlement_mail_or_unreadable=mail,
    )


def _read_only(config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None) -> T:
    return _or_release(_read_only_view(config, file, together), file)


def _read_only_view(
    config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None
) -> Read[T] | Unreadable:
    data = settings_bytes(config / file.name)
    if isinstance(data, OSError):
        return Unreadable(file.name)
    parsed = _paired(file, data, file.parse(data), together or {})
    if not isinstance(parsed, FieldProblem | Unreadable):
        return Good(parsed)
    remembered = Memory(config, lambda _: None).read(file.name)
    good = remembered.good if isinstance(remembered, Remembered) else None
    if isinstance(parsed, Unreadable):
        return _pair_waits(file, parsed, good)
    return _with_secret_value(file, Bad(parsed, None if good is None else _good_value(good, file)), data)


def _paired(
    file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, together: Mapping[str, _PairCheck]
) -> T | FieldProblem | Unreadable:
    if data is None and file.name == RULES.name:
        return parsed
    check = together.get(file.name)
    problem = None if check is None or isinstance(parsed, FieldProblem) else check(parsed)
    return parsed if problem is None else problem


def _pair_waits(file: SettingsFile[T], partner: Unreadable, good: bytes | None) -> Bad[T]:
    return Bad(FieldProblem(None, messages.unreadable(partner.name)), None if good is None else _good_value(good, file))


def _with_secret_value(file: SettingsFile[T], read: Read[T], data: bytes | None) -> Read[T]:
    if not (file.secret and isinstance(read, Bad)):
        return read
    return Bad(read.problem, None if file.unchecked is None else file.unchecked(data))


def _seen(file: SettingsFile[T], data: bytes | None) -> bytes | None:
    if data is None or not file.secret:
        return data
    return hashlib.sha256(data).digest()


def _rules_problem(
    rules: tuple[QuantityRule, ...], devices: bytes | None | OSError, remembered: Remembered | None | Unreadable
) -> FieldProblem | Unreadable | None:
    if isinstance(devices, OSError):
        return Unreadable(DEVICES.name)
    now = DEVICES.parse(devices)
    return rules_problem(rules, None if isinstance(now, FieldProblem) else now, _last_good_devices(remembered))


def _last_good_devices(remembered: Remembered | None | Unreadable) -> tuple[Component, ...]:
    good = _good_value(remembered.good if isinstance(remembered, Remembered) else None, DEVICES)
    return DEVICES.default if good is None else good


def _good_value(good: bytes | None, file: SettingsFile[T]) -> T | None:
    parsed = file.parse(good)
    return None if isinstance(parsed, FieldProblem) else parsed


def _problem(observed: Read[T] | Unreadable, file: SettingsFile[T], unreadable: Callable[[str], str]) -> FieldProblem | None:
    match observed:
        case Good():
            return None
        case Bad(problem=problem):
            return problem
        case Unreadable():
            return FieldProblem(None, unreadable(file.name))


def _absent_sentence(change: ReleaseChange[Any], applied: Mapping[str, Applied], config: Path) -> str | None:
    done = applied.get(change.id)
    if done is not None:
        return change.refused_absent if done.result == "odrzucono" else None
    if change.waiting is not None and change.waiting.old_files(config):
        return change.waiting.sentence
    return None


def _read(parsed: T | FieldProblem, usable: T | None) -> Read[T]:
    return Bad(parsed, usable) if isinstance(parsed, FieldProblem) else Good(parsed)


def _usable(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable:
    match observed:
        case Good() | Bad():
            return _value(observed, file)
        case Unreadable():
            return observed


def _value(read: Read[T], file: SettingsFile[T]) -> T:
    match read:
        case Good(value=value):
            return value
        case Bad(usable=usable):
            return file.default if usable is None else usable


def _or_unreadable(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable:
    return observed if isinstance(observed, Unreadable) else _value(observed, file)


def _counted(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable | FieldProblem:
    match observed:
        case Unreadable():
            return observed
        case Good(value=value):
            return value
        case Bad(problem=problem, usable=value):
            return problem if value is None else value


def _shown_mail(mail: SettlementMailSettings) -> WrittenMail:
    return WrittenMail(mail.subject, mail.text)


def _or_release(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T:
    return file.default if isinstance(observed, Unreadable) else _value(observed, file)


def _reported(row: HistoryRow) -> str:
    head = f"- {row.at:%Y-%m-%d %H:%M} · {_reported_source(row.source)} · {row.file}"
    if row.result == "odrzucono":
        return f"{head} · odrzucono: {row.reason}"
    file = _FILES.get(row.file)
    if row.secret or file is None:
        return f"{head} · zmieniono: " + ", ".join(change.key for change in row.changes)
    undo = " · cofnięcie" if row.undoes is not None else ""
    removed = " · usunięto plik" if row.removed else ""
    return f"{head}{undo}{removed} · " + "; ".join(file.reported(change.change()) for change in row.changes)


def _reported_source(source: RowSource) -> str:
    match source:
        case ByDad():
            return "tata"
        case Outside():
            return "spoza Centrum"
        case FromRelease(release=release, commit=commit, change=change):
            if release is not None:
                return f"Wydanie {release} ({change})"
            return f"{'wersja nieznana' if commit is None else f'commit {commit}'} ({change})"
