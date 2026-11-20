from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Final

from fastapi import APIRouter, Request

from rozliczenia.centrum import restart_guardian, update_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import tool_update as tool_update_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.reports import ReportHandle, Reports, UpdateReport
from rozliczenia.centrum.restart_guardian import Restart
from rozliczenia.centrum.runs import RunHost
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.centrum.threads import Threading
from rozliczenia.centrum.tool_freshness import CommitSource, GitHubReleases, ReleaseSource
from rozliczenia.centrum.tool_update import (
    RESULT_FILE,
    UNEXPECTED,
    UP_TO_DATE,
    ROLLBACK_FAILED,
    UPDATED,
    Step,
    ToolClone,
    UpdateResult,
    read_result,
)
from rozliczenia.centrum.work import CentrumWork

UPDATE_THREAD: Final = "aktualizacja-narzedzia"

GuardianLauncher = Callable[[Path, Restart], object]


class ToolUpdates:
    def __init__(
        self,
        work: CentrumWork,
        clone: Callable[[], ToolClone],
        runs: RunHost,
        commit: CommitSource,
        reports: Reports,
        *,
        shutdown: Shutdown,
        guardian: GuardianLauncher,
        release: ReleaseSource,
        threads: Threading = threading,
    ) -> None:
        self._clone = clone
        self._runs = runs
        self._log = work.log
        self._reports = reports
        self._commit = commit
        self._shutdown = shutdown
        self._guardian = guardian
        self._result_file = work.config / RESULT_FILE
        self._release = release
        self._lock = threads.Lock()
        self._view: tool_update_contract.ToolUpdate | _Failed = tool_update_contract.ToolUpdateIdle(state="idle")
        self._up_to_date_with: GitHubReleases | None = None
        self._after_restart()

    def current(self) -> tool_update_contract.ToolUpdate:
        with self._lock:
            view, judged = self._view, self._up_to_date_with
        if isinstance(view, tool_update_contract.ToolUpdateUpToDate):
            newest = self._release()
            with self._lock:
                if newest is not None and newest != judged and self._view is view:
                    self._view = tool_update_contract.ToolUpdateIdle(state="idle")
                view = self._view
        return view.view if isinstance(view, _Failed) else view

    def start(self, port: int) -> tool_update_contract.ToolUpdate:
        clone = self._clone()
        self._runs.begin_update()
        before = self._commit()
        self._log.update_started(before=before)
        first = tool_update_contract.ToolUpdateRunning(state="running", step="fetching")
        with self._lock:
            self._view = first
        threading.Thread(target=self._update, args=(clone, before, port), name=UPDATE_THREAD, daemon=True).start()
        return first

    def _after_restart(self) -> None:
        result = read_result(self._result_file)
        if result is None:
            return
        running = self._commit()
        if result.code != UPDATED and running is not None and result.before is not None and result.before != running:
            self._log.update_result_stale(result=result.code, before=result.before, after=result.after)
            with suppress(OSError):
                self._result_file.unlink()
            return
        if result.code == UPDATED and running is not None and running != result.after:
            result = replace(result, code=UNEXPECTED)
        if not self._log.update_awaits(result=result.code, before=result.before, after=result.after):
            with suppress(OSError):
                self._result_file.unlink()
            return
        self._finished(result)
        try:
            self._result_file.unlink(missing_ok=True)
        except OSError as failure:
            self._log.update_result_kept(failure)
        self._view = _view_of(result) or self._failed(result, after_restart=True)

    def _update(self, clone: ToolClone, before: str | None, port: int) -> None:
        work = Path(tempfile.mkdtemp(prefix="centrum-aktualizacja-"))
        restarting = False
        view: tool_update_contract.ToolUpdate | _Failed | None = None
        newest: GitHubReleases | None = None
        try:
            result, guardian = self._result(clone, before, work)
            if result.before is None:
                result = replace(result, before=before)
            if result.skipped:
                self._log.update_skipped_releases(tags=result.skipped)
            if result.code == UPDATED and result.after is not None and guardian is not None:
                restart = Restart(
                    port, result.before, result.after, clone.root, self._result_file, result.installed, work
                )
                restarting = self._restart(clone, restart, guardian)
                if not restarting:
                    result = self._moved_back(clone, result)
            if not restarting:
                self._finished(result)
                view = _view_of(result)
                if isinstance(view, tool_update_contract.ToolUpdateUpToDate):
                    newest = self._release()
                if view is None:
                    failed = self._failed(result, after_restart=False)
                    failed.report.wait_for_box()
                    view = failed
        finally:
            if not restarting:
                shutil.rmtree(work, ignore_errors=True)
                with self._lock:
                    self._runs.end_update()
                    if view is not None:
                        self._view, self._up_to_date_with = view, newest

    def _result(self, clone: ToolClone, before: str | None, work: Path) -> tuple[UpdateResult, Path | None]:
        try:
            guardian = restart_guardian.prepare(work)
            return clone.update(self._show_step), guardian
        except Exception as failure:
            self._log.unexpected_failure(failure, where="aktualizacja narzędzia")
            return UpdateResult(UNEXPECTED, before, None), None

    def _restart(self, clone: ToolClone, restart: Restart, guardian: Path) -> bool:
        try:
            with clone.leased_to_guardian():
                with self._lock:
                    self._view = tool_update_contract.ToolUpdateRunning(state="running", step="restarting")
                self._guardian(guardian, restart)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="ponowny start po aktualizacji")
            return False
        self._shutdown.close_for_update()
        return True

    def _moved_back(self, clone: ToolClone, result: UpdateResult) -> UpdateResult:
        try:
            clone.roll_back()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="cofnięcie aktualizacji")
            return replace(result, code=ROLLBACK_FAILED)
        return replace(result, code=UNEXPECTED)

    def _finished(self, result: UpdateResult) -> None:
        self._log.update_finished(
            result=result.code, before=result.before, after=result.after, installed=result.installed
        )

    def _failed(self, result: UpdateResult, *, after_restart: bool) -> _Failed:
        failure = update_messages.UpdateFailure.of(result.code)
        source = UpdateReport.of(result, failure.message, self._log)
        report = self._reports.handle(source.fingerprint)
        return _Failed(
            common_contract.Message.of(failure.message),
            failure.next_action,
            report,
            report.prepare(source),
            after_restart,
        )

    def send_report(self) -> diagnosis_contract.ReportState:
        with self._lock:
            failed = self._view
        if not isinstance(failed, _Failed):
            raise refusal.no_failed_update()
        return failed.report.send()

    def _show_step(self, step: Step) -> None:
        with self._lock:
            self._view = tool_update_contract.ToolUpdateRunning(state="running", step=step)


@dataclass(frozen=True)
class _Failed:
    message: common_contract.Message
    next_action: update_messages.NextAction
    report: ReportHandle
    draft: diagnosis_contract.ReportDraft
    after_restart: bool

    @property
    def view(self) -> tool_update_contract.ToolUpdateFailed:
        return tool_update_contract.ToolUpdateFailed(
            state="failed",
            message=self.message,
            next_action=self.next_action,
            report=self.report.state,
            draft=self.draft,
            after_restart=self.after_restart,
        )


def _view_of(result: UpdateResult) -> tool_update_contract.ToolUpdate | None:
    if result.code == UPDATED:
        return tool_update_contract.ToolUpdateUpdated(state="updated")
    if result.code == UP_TO_DATE:
        return tool_update_contract.ToolUpdateUpToDate(state="up_to_date")
    return None


def tool_update_router(updates: ToolUpdates) -> APIRouter:
    router = APIRouter(prefix="/api/tool-update", tags=["aktualizacja"])

    @router.post(
        "",
        operation_id="startToolUpdate",
        status_code=202,
        responses={409: {"model": common_contract.Problem}, 500: {"model": common_contract.Problem}},
    )
    def start(request: Request) -> tool_update_contract.ToolUpdate:
        # ZEWNĘTRZNE: ASGI podaje `server` zakresu HTTP opcjonalnie, a dla gniazda bez portu TCP jako `[ścieżka, None]` (specyfikacja ASGI, HTTP Connection Scope, klucz server)
        match request.scope.get("server"):
            case (str(), int(port)):
                return updates.start(port)
            case _:
                raise refusal.update_without_port()

    @router.get("", operation_id="getToolUpdate")
    def current() -> tool_update_contract.ToolUpdate:
        return updates.current()

    @router.post("/report", operation_id="reportToolUpdate", responses={409: {"model": common_contract.Problem}})
    def send_report() -> diagnosis_contract.ReportState:
        return updates.send_report()

    return router
