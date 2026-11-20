from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import cache, partial
import hashlib
from pathlib import Path
import platform
import threading
from typing import Final, Protocol, TypeVar, assert_never

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.comment_versions import (
    LABEL,
    CommentVersion,
    Drop,
    LogsPost,
    OwnLogs,
    ProgressVersion,
    StandInLogs,
    StandInVersion,
    WithoutLogsVersion,
    close,
    journal_after,
    post_of,
    progress_markdown,
)
from rozliczenia.centrum.dad_action_journal import DadActionJournal
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.logs_disk import JournalKey, JournalRead, LogsOnDisk
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.logs_of_run import logged_diagnosis, logs_of
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.run_logs import CentrumLogLines, Environment, LoggedFile, RunLog, StartFacts, Tool
from rozliczenia.centrum.run_logs_guard import guard_logs, guard_text
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.reads import SettingsSnapshot
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.template_archive import ArchivedTemplate, TemplateChecks, TemplateRefused
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.dad_files import DadFiles
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.wall_clock import utc_now
from rozliczenia.workbook_files import WorkbookError

PROGRESS_S: Final = 300.0

_AFTER_RUN: Final = "po wyniku Uruchomienia procesu"
_LEFT_BEHIND: Final = "wysyłka wersji zastępczych przy starcie"

_PROGRESS_PLACE: Final = "postęp Wyceny w efenix"

T = TypeVar("T")

ProcessFiles = Callable[[common_contract.ProcessKey, str, SettingsSnapshot | None], Sequence[Path] | Unreadable]

ProcessTemplates = Callable[[common_contract.ProcessKey], Sequence[Path]]


class CommentQueue(Protocol):
    def post(self, post: LogsPost) -> bool:
        ...

    def delivered(self, run_id: str, label: Label) -> str | None:
        ...


@dataclass(frozen=True)
class LeftBehindClosed:
    pass


@dataclass(frozen=True)
class MadeLogs:
    record: RunLog
    templates: tuple[ArchivedTemplate, ...]


class RecordMaker:
    def __init__(
        self,
        *,
        commit: CommitSource,
        wydanie: Callable[[str], Release | None],
        files: ProcessFiles,
        templates: ProcessTemplates,
        dad_files: DadFiles,
        checks: TemplateChecks,
        cloud_files: CloudFiles,
        dad_actions: DadActionJournal,
        centrum_log: CentrumLog,
    ) -> None:
        self._commit = commit
        self._wydanie = wydanie
        self._files = files
        self._templates = templates
        self._dad_files = dad_files
        self._checks = checks
        self._cloud = cloud_files
        self._dad_actions = dad_actions
        self._centrum_log = centrum_log

    def of(self, run: EndedRun) -> MadeLogs:
        read = self._read_templates(run.info.process)
        environment = self._environment(run.info.process, run.info.period, run.settings.snapshot, read)
        record = logs_of(
            run,
            tool=self._tool(),
            environment=environment,
            dad_actions=self._dad_actions.take(),
            centrum_log=self._centrum_log_lines(),
        )
        checked = [self._checks.checked(path.name, content) for path, content in read.items()]
        notes = [found.note for found in checked if isinstance(found, TemplateRefused)]
        if notes:
            record = record.model_copy(update={"input_copy_notes": [*record.input_copy_notes, *notes]})
        return MadeLogs(record, tuple(found for found in checked if isinstance(found, ArchivedTemplate)))

    def _read_templates(self, process: common_contract.ProcessKey) -> dict[Path, bytes]:
        read: dict[Path, bytes] = {}
        for path in self._templates(process):
            try:
                read[path] = self._dad_files.read(path, despite_excel_lock=True).content
            except WorkbookError:
                continue
        return read

    def interrupted(self, journal: JournalRead) -> RunLog:
        return RunLog.interrupted(
            journal.started,
            ended_at=journal.last_at,
            orders=journal.orders,
            interruption=journal.interruption,
            tool=self._tool(),
            environment=self._environment(journal.started.process, journal.started.period, None, {}),
            dad_actions=self._dad_actions.take(),
            centrum_log=self._centrum_log_lines(),
        )

    def _centrum_log_lines(self) -> CentrumLogLines:
        lines, omitted = self._centrum_log.take_for_logs()
        return CentrumLogLines(lines=lines, omitted=omitted)

    def _tool(self) -> Tool:
        commit = self._commit()
        release = None if commit is None else self._wydanie(commit)
        return Tool(wydanie=None if release is None else release.version, commit=commit)

    def _environment(
        self,
        process: common_contract.ProcessKey,
        period: str,
        settings: SettingsSnapshot | None,
        templates: Mapping[Path, bytes],
    ) -> Environment:
        unreadable: str | None = None
        files: list[LoggedFile] | None = None
        try:
            paths = self._files(process, period, settings)
        except (OSError, PeriodFolderInaccessible):
            pass
        else:
            if isinstance(paths, Unreadable):
                unreadable = paths.name
            else:
                files = [self._file(path, templates.get(path)) for path in paths]
        return Environment(system=_system(), python=platform.python_version(), files=files, unreadable_settings=unreadable)

    def _file(self, path: Path, content: bytes | None) -> LoggedFile:
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        online_only = self._cloud.online_only(path) if self._cloud.checked and size is not None else None
        sha256 = None if content is None else hashlib.sha256(content).hexdigest()
        return LoggedFile(name=path.name, size=size, online_only=online_only, sha256=sha256)


@cache
def _system() -> str:
    return platform.platform()


@dataclass(frozen=True)
class _Watched:
    run_id: str
    since: float
    ended: bool = False


class RunComments:
    def __init__(self, work: CentrumWork, disk: LogsOnDisk, queue: CommentQueue, records: RecordMaker) -> None:
        self._disk = disk
        self._queue = queue
        self._forbidden = work.forbidden
        self._prefix = work.box_prefix
        self._clock = work.clock
        self._log = work.log
        self._records = records
        self._lock = threading.Lock()
        self._watched: _Watched | None = None
        self._last: OwnLogs | None = None
        self._pending: list[tuple[JournalKey, StandInVersion]] = []

    def run_started(self, info: runs_contract.RunInfo, started_at: datetime) -> None:
        self._disk.started(StartFacts.of_run(info, started_at))
        if info.process != self._disk.journal.process:
            return
        watched = self._watched = _Watched(info.id, self._clock())
        self._step(partial(self._progress, watched), where=_PROGRESS_PLACE)
        self._clock.after(PROGRESS_S, partial(self._refresh, info.id))

    def _refresh(self, run_id: str) -> None:
        watched = self._watched
        if watched is None or watched.run_id != run_id:
            return
        if self._step(partial(self._progress, watched), where=_PROGRESS_PLACE) is False:
            return
        self._clock.after(PROGRESS_S, partial(self._refresh, run_id))

    def _progress(self, watched: _Watched) -> bool:
        progress = self._disk.journal.progress(watched.run_id)
        elapsed_s = self._clock() - watched.since
        with self._lock:
            current = self._watched
            if current is None or current.run_id != watched.run_id or current.ended:
                return False
            if progress is not None:
                text = guard_text(progress_markdown(progress, elapsed_s=elapsed_s), _PROGRESS_PLACE, self._forbidden)
                self._sent(ProgressVersion(progress, text))
            return True

    def run_ended(self, run: EndedRun) -> None:
        run_id = run.info.id
        self._step(lambda: self._disk.journal.end(run_id, run.result), where=_AFTER_RUN)
        with self._lock:
            if self._watched is not None and self._watched.run_id == run_id:
                self._watched = replace(self._watched, ended=True)
        version = self._step(lambda: self._own(run), where=_AFTER_RUN)
        if version is None:
            return
        accepted: list[bool] = []
        self._step(lambda: self._keep(version, accepted.append), where=_AFTER_RUN)
        if accepted and journal_after(version, accepted=accepted[0]) == "usuń":
            self._step(lambda: self._disk.journal.remove(run_id), where=_AFTER_RUN)

    def _own(self, run: EndedRun) -> OwnLogs:
        made = self._records.of(run)
        version = OwnLogs(guard_logs(made.record, self._forbidden), made.templates)
        with self._lock:
            self._last = version
        return version

    def _step(self, step: Callable[[], T], *, where: str) -> T | None:
        try:
            return step()
        except Exception as failure:
            self._log.unexpected_failure(failure, where=where)
            return None

    def _sent(self, version: CommentVersion) -> bool:
        return self._queue.post(post_of(version, prefix=self._prefix))

    def link(self, run_id: str) -> str | None:
        return self._queue.delivered(run_id, LABEL)

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None:
        with self._lock:
            last = self._last
            if last is None or last.logs.record.run_id != run_id:
                return
            logged = logged_diagnosis(diagnosis, diagnosed_at=utc_now())
            logs = last.logs.with_diagnosis(logged, self._forbidden)
            if logs is None:
                return
            version = OwnLogs(logs, last.templates)
            self._keep(version, lambda accepted: None)
            self._last = version

    def _keep(self, version: OwnLogs, accepted: Callable[[bool], None]) -> None:
        try:
            self._disk.write(version.logs)
        finally:
            accepted(self._sent(version))

    def close_left_behind(self) -> LeftBehindClosed:
        for left in self._disk.left_behind():
            try:
                closing = close(left, self._forbidden, self._records.interrupted)
            except OSError as failure:
                self._log.pricing_journal_unavailable(failure, where="start")
                continue
            match closing:
                case Drop():
                    self._disk.remove_journal(left.key)
                    continue
                case StandInLogs(logs=logs):
                    try:
                        self._disk.write(logs)
                    except OSError as failure:
                        self._log.pricing_journal_unavailable(failure, where="start")
                case WithoutLogsVersion():
                    pass
                case _:
                    assert_never(closing)
            with self._lock:
                self._pending.append((left.key, closing))
        return LeftBehindClosed()

    def send_left_behind(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
        for key, version in pending:
            try:
                if journal_after(version, accepted=self._sent(version)) == "usuń":
                    self._disk.remove_journal(key)
            except Exception as failure:
                self._log.unexpected_failure(failure, where=_LEFT_BEHIND)
