from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import threading
from typing import Annotated, Final, Generic, Literal, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.pricing_progress import OrderDone, PricingProgress
from rozliczenia.centrum.run_logs import RUN_LOGS_DIRECTORY, LoggedInterruption, LoggedOrder, RunLog, StartFacts
from rozliczenia.centrum.run_logs_guard import TOOL_TEXT_GRAMMAR, GuardedLogs, exact_logs
from rozliczenia.efenix_pricing import OrderResult
from rozliczenia.file_state import folder_entries, remove_file
from rozliczenia.wall_clock import utc_now

LAST_STARTED_FILE: Final = "ostatnie-uruchomienie.json"
_JOURNALS: Final = "dzienniki-wyceny"
_JOURNAL_SUFFIX: Final = ".jsonl"
_STARTER: Final = object()
_RUN_ID: Final = TOOL_TEXT_GRAMMAR["RunLog.run_id"]
_NAME: Final = re.compile(
    rf"(?P<second>\d{{8}}T\d{{6}}Z)-(?P<process>{'|'.join(get_args(common_contract.ProcessKey))})-(?P<run_id>{_RUN_ID.pattern})\.json"
)

T = TypeVar("T")


def name_of(start: StartFacts) -> str:
    return f"{start.started_at:%Y%m%dT%H%M%SZ}-{start.process}-{start.run_id}.json"


@dataclass(frozen=True)
class _Name:
    second: str
    process: common_contract.ProcessKey
    run_id: str


def _parsed(name: str) -> _Name | None:
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    process = next(key for key in get_args(common_contract.ProcessKey) if key == match["process"])
    return _Name(second=match["second"], process=process, run_id=match["run_id"])


@dataclass(frozen=True)
class Found:
    logs: RunLog


@dataclass(frozen=True)
class Missing:
    ...


@dataclass(frozen=True)
class Unreadable:
    ...


@dataclass(frozen=True)
class Refused:
    failure: OSError


LogsRead = Found | Missing | Unreadable | Refused


class _StartedFile(StartFacts):
    schema_version: Literal[1, 2]


class _JournalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _JournalStarted(StartFacts):
    entry: Literal["start Uruchomienia"]


class _OrderBegun(_JournalRecord):
    at: datetime
    entry: Literal["zaczynam zlecenie"]
    row: int
    place: int
    total: int


class _OrderEnded(_JournalRecord):
    at: datetime
    entry: Literal["zlecenie skończone"]
    order: LoggedOrder


class _RunEnded(_JournalRecord):
    at: datetime
    entry: Literal["koniec Uruchomienia"]
    result: RunResult | None = None


_JournalEntry = Annotated[_JournalStarted | _OrderBegun | _OrderEnded | _RunEnded, Field(discriminator="entry")]


class _JournalLine(RootModel[_JournalEntry]):
    ...


def _first_line(start: StartFacts) -> _JournalStarted:
    return _JournalStarted(**dict(start.start), entry="start Uruchomienia")


class Journal:
    def __init__(self, directory: Path, log: CentrumLog, *, process: common_contract.ProcessKey) -> None:
        self.process: Final = process
        self._directory = directory
        self._log = log
        self._lock = threading.Lock()
        self._start: StartFacts | None = None
        self._header = False
        self._failed = False
        self._done: list[OrderDone] = []
        self._total: int | None = None
        self._current: int | None = None

    def run_started(self, start: StartFacts, proof: object) -> None:
        if proof is not _STARTER:
            raise TypeError("Dziennik Wyceny w efenix startuje tylko LogsOnDisk.started.")
        with self._lock:
            self._done, self._total, self._current = [], None, None
            if start.process != self.process:
                self._start = None
                return
            self._start = start
            self._header, self._failed = True, False
            self._append_locked(start)

    def progress(self, run_id: str) -> PricingProgress | None:
        with self._lock:
            start = self._start
            if start is None or start.run_id != run_id or self._header:
                return None
            return PricingProgress(start, tuple(self._done), self._total, self._current)

    def begun(self, row: int, place: int, total: int) -> None:
        self._write(_OrderBegun(at=utc_now(), entry="zaczynam zlecenie", row=row, place=place, total=total))

    def ended(self, result: OrderResult) -> None:
        self._write(_OrderEnded(at=utc_now(), entry="zlecenie skończone", order=LoggedOrder.of(result)))

    def end(self, run_id: str, result: RunResult) -> None:
        with self._lock:
            start, header = self._start, self._header
        if start is None or start.run_id != run_id:
            return
        if header:
            _remove(self._path(start), self._log, where="wpis")
        else:
            self._write(_RunEnded(at=utc_now(), entry="koniec Uruchomienia", result=result))

    def remove(self, run_id: str) -> None:
        with self._lock:
            start, header = self._start, self._header
        if start is None or start.run_id != run_id or header:
            return
        _remove(self._path(start), self._log, where="wpis")

    def _path(self, start: StartFacts) -> Path:
        return self._directory / Path(name_of(start)).with_suffix(_JOURNAL_SUFFIX)

    def _write(self, entry: _OrderBegun | _OrderEnded | _RunEnded) -> None:
        with self._lock:
            start = self._start
            if start is None:
                return
            if not self._append_locked(start, entry):
                return
            match entry:
                case _OrderBegun():
                    self._total, self._current = entry.total, entry.row
                case _OrderEnded(order=order):
                    self._done.append(OrderDone.of(order))
                    self._current = None
                case _RunEnded():
                    pass

    def _append_locked(self, start: StartFacts, *entries: _OrderBegun | _OrderEnded | _RunEnded) -> bool:
        lines: list[_JournalEntry] = [_first_line(start), *entries] if self._header else list(entries)
        path = self._path(start)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as journal:
                journal.write("".join(_JournalLine(line).model_dump_json() + "\n" for line in lines))
                journal.flush()
                os.fsync(journal.fileno())
        except OSError as failure:
            if not self._failed:
                self._log.pricing_journal_unavailable(failure, where="wpis")
                self._failed = True
            return False
        self._header = False
        return True


@dataclass(frozen=True)
class EndEntry:
    result: RunResult | None


@dataclass(frozen=True)
class JournalRead:
    started: StartFacts
    orders: list[LoggedOrder]
    interruption: LoggedInterruption
    last_at: datetime
    total: int | None
    end: EndEntry | None

    @property
    def progress(self) -> PricingProgress:
        done = tuple(OrderDone.of(order) for order in self.orders)
        return PricingProgress(self.started, done, self.total, self.interruption.row)


class JournalKey:
    __slots__ = ()


@dataclass(frozen=True)
class LeftJournal:
    key: JournalKey
    journal: JournalRead | None
    logs: LogsRead


def _read_journal(path: Path) -> JournalRead | None:
    started: _JournalStarted | None = None
    orders: list[LoggedOrder] = []
    last: _OrderBegun | _OrderEnded | None = None
    total: int | None = None
    end: _RunEnded | None = None
    omitted = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = _JournalLine.model_validate_json(line).root
        except ValidationError:
            omitted += 1
            continue
        match entry:
            case _JournalStarted():
                if started is None:
                    started = entry
            case _OrderBegun():
                last, total = entry, entry.total
            case _OrderEnded():
                orders.append(entry.order)
                last = entry
            case _RunEnded():
                end = entry
    if started is None:
        return None
    begun = last if isinstance(last, _OrderBegun) else None
    interruption = LoggedInterruption(
        row=None if begun is None else begun.row,
        place=None if begun is None else begun.place,
        total=None if begun is None else begun.total,
        omitted=omitted,
    )
    return JournalRead(
        started.start,
        orders,
        interruption,
        started.started_at if last is None else last.at,
        total,
        None if end is None else EndEntry(end.result),
    )


def _remove(path: Path, log: CentrumLog, *, where: Literal["wpis", "start"]) -> None:
    try:
        remove_file(path)
    except OSError as failure:
        log.pricing_journal_unavailable(failure, where=where)


class LogsOnDisk:
    def __init__(self, log: CentrumLog, *, journaled: common_contract.ProcessKey) -> None:
        self._logs = log.directory / RUN_LOGS_DIRECTORY
        self._last_started = log.directory / LAST_STARTED_FILE
        self._journals = log.directory / _JOURNALS
        self._log = log
        self._journal = Journal(self._journals, log, process=journaled)
        self._left: dict[JournalKey, Path] = {}

    @property
    def journal(self) -> Journal:
        return self._journal

    def started(self, start: StartFacts) -> None:
        self.journal.run_started(start, _STARTER)
        started = _StartedFile(**dict(start.start), schema_version=2)
        replace_atomically(self._last_started, started.model_dump_json(indent=2) + "\n")

    def write(self, logs: GuardedLogs) -> None:
        checked = exact_logs(logs)
        replace_atomically(self._logs / name_of(checked.record.start), checked.text, newline="")

    def last_start(self) -> StartFacts | None:
        try:
            started = _StartedFile.model_validate_json(self._last_started.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return started.start

    def logs(self, run_id: str) -> LogsRead:
        if _RUN_ID.fullmatch(run_id) is None:
            return Missing()
        try:
            names = _names(self._logs)
        except OSError as failure:
            return Refused(failure)
        name = next((name for name, parsed in names if parsed.run_id == run_id), None)
        return Missing() if name is None else _read_logs(self._logs / name)

    def newest(self, process: common_contract.ProcessKey) -> RunLog | None:
        try:
            listed = _names(self._logs)
        except OSError:
            return None
        names = sorted((pair for pair in listed if pair[1].process == process), key=lambda pair: pair[0])
        if not names:
            return None
        second = names[-1][1].second
        read = [_read_logs(self._logs / name) for name, parsed in names if parsed.second == second]
        found = [logs.logs for logs in read if isinstance(logs, Found)]
        return max(found, key=lambda record: record.started_at) if found else None

    def viewed(self, view: Callable[[RunLog], T | None]) -> ViewedLogs[T]:
        return ViewedLogs(self._logs, view)

    def left_behind(self) -> Iterator[LeftJournal]:
        try:
            paths = sorted(self._journals.glob(f"*{_JOURNAL_SUFFIX}"))
        except OSError as failure:
            self._log.pricing_journal_unavailable(failure, where="start")
            return
        for path in paths:
            try:
                read = _read_journal(path)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            logs = Missing() if read is None else self.logs(read.started.run_id)
            key = JournalKey()
            self._left[key] = path
            yield LeftJournal(key, read, logs)

    def remove_journal(self, key: JournalKey) -> None:
        _remove(self._left.pop(key), self._log, where="start")


class ViewedLogs(Generic[T]):
    def __init__(self, logs: Path, view: Callable[[RunLog], T | None]) -> None:
        self._logs = logs
        self._view = view
        self._lock = threading.Lock()
        self._known: dict[str, tuple[tuple[int, int], T | None]] = {}

    def of(self, process: common_contract.ProcessKey) -> list[T]:
        try:
            listed = _names(self._logs)
        except OSError:
            return []
        names = sorted((name for name, parsed in listed if parsed.process == process), reverse=True)
        with self._lock:
            viewed = [self._of(self._logs / name) for name in names]
        return [view for view in viewed if view is not None]

    def _of(self, path: Path) -> T | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        version = (stat.st_mtime_ns, stat.st_size)
        known = self._known.get(path.name)
        if known is not None and known[0] == version:
            return known[1]
        read = _read_logs(path)
        view = self._view(read.logs) if isinstance(read, Found) else None
        self._known[path.name] = (version, view)
        return view


def _names(logs: Path) -> list[tuple[str, _Name]]:
    entries = folder_entries(logs) or []
    return [(entry.name, parsed) for entry in entries if (parsed := _parsed(entry.name)) is not None]


def _read_logs(path: Path) -> LogsRead:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as failure:
        return Refused(failure)
    except ValueError:
        return Unreadable()
    try:
        return Found(RunLog.model_validate_json(text))
    except ValueError:
        return Unreadable()
