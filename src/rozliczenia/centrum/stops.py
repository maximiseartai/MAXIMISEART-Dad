from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import threading
from typing import Protocol, overload

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.settings.reads import SettingsSnapshot
from rozliczenia.centrum.reports import NoPreview, ProblemFingerprint, ReportHandle, ReportShown, Reports, StopReport
from rozliczenia.process_run import Stop

Diagnose = Callable[[common_contract.ProcessKey, str, SettingsSnapshot | None], Diagnosis]


class DiagnosedLogs(Protocol):
    def link(self, run_id: str) -> str | None: ...

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None: ...


class Stops:
    def __init__(self, reports: Reports, diagnosis_of: Diagnose, log: CentrumLog, logs: DiagnosedLogs) -> None:
        self._reports = reports
        self._diagnosis_of = diagnosis_of
        self._log = log
        self._logs = logs
        self._lock = threading.Lock()
        self._last: dict[common_contract.ProcessKey, ProblemFingerprint] = {}

    @overload
    def ended(
        self, info: runs_contract.RunInfo, stop: Stop, *, shown: ReportShown, settings: SettingsSnapshot | None
    ) -> StoppedRun: ...

    @overload
    def ended(
        self, info: runs_contract.RunInfo, stop: None, *, shown: ReportShown, settings: SettingsSnapshot | None
    ) -> None: ...

    def ended(
        self, info: runs_contract.RunInfo, stop: Stop | None, *, shown: ReportShown, settings: SettingsSnapshot | None
    ) -> StoppedRun | None:
        if stop is None:
            with self._lock:
                self._last.pop(info.process, None)
            return None
        named = plain(info, stop)
        if stop.kind == "declined":
            with self._lock:
                self._last.pop(info.process, None)
            return named
        fingerprint = named.fingerprint
        with self._lock:
            repeated = self._last.get(info.process) == fingerprint
            self._last[info.process] = fingerprint
        kind: runs_contract.StopKind = "repeated" if repeated and named.kind == "for_tata" else named.kind
        offer: runs_contract.DiagnosisOffer | None = (
            None if kind == "for_tata" else "on_request" if stop.kind == "stop" else "automatic"
        )
        report = None if offer is None else self._reports.handle(fingerprint, shown=shown)
        return replace(named, kind=kind, offer=offer, report=report, settings=settings)

    def diagnose(self, stopped: StoppedRun) -> diagnosis_contract.Diagnosis:
        report = stopped.report
        if report is None:
            raise refusal.no_diagnosis()
        info = stopped.info
        diagnosis = self._diagnosis_of(info.process, info.period, stopped.settings)
        self._log.diagnosed(process=info.process, period=info.period, cause=diagnosis.explanation.code)
        logs = self._logs.link(info.id)
        self._log_diagnosis(info.id, diagnosis)
        draft = report.prepare(StopReport(info, stopped.stop, stopped.fingerprint, diagnosis, logs))
        return diagnosis.view(stopped.stop.message, draft)

    def _log_diagnosis(self, run_id: str, diagnosis: Diagnosis) -> None:
        try:
            self._logs.diagnosed(run_id, diagnosis)
        except Exception as failure:
            self._log.unexpected_failure(failure, where="Diagnoza w Logach Uruchomienia")

    def send(self, stopped: StoppedRun) -> diagnosis_contract.ReportState:
        report = stopped.report
        if report is None:
            raise refusal.no_diagnosis()
        try:
            return report.send()
        except NoPreview:
            raise refusal.no_report_draft() from None


@dataclass(frozen=True, eq=False)
class StoppedRun:
    info: runs_contract.RunInfo
    stop: Stop
    fingerprint: ProblemFingerprint
    kind: runs_contract.StopKind
    offer: runs_contract.DiagnosisOffer | None
    report: ReportHandle | None
    settings: SettingsSnapshot | None = None


def plain(info: runs_contract.RunInfo, stop: Stop) -> StoppedRun:
    kind: runs_contract.StopKind = "declined" if stop.kind == "declined" else stop.stop_kind
    return StoppedRun(info, stop, ProblemFingerprint.of(info.process, stop.message), kind, None, None)
