from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import notifications as notifications_contract
from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.keyed_box import KeyedBox, NoKey
from rozliczenia.centrum.report_issue import LABEL as REPORT_LABEL
from rozliczenia.centrum.report_box import (
    Closure,
    CloseReason,
    Label,
    Refused,
    Unreachable,
    close_reason,
    read_moment,
)
from rozliczenia.centrum.work import CentrumWork

DAD_CASES_FILE: Final = "sprawy-taty.json"
SCHEMA_VERSION: Final = 1
OLD_REPORTS_FILE: Final = "zgloszenia-wyslane.json"
OLD_NOTES_FILE: Final = "uwagi-taty.json"
_OLD_NOTES_SCHEMA: Final = 1


@dataclass(frozen=True)
class CaseKind:
    key: notifications_contract.CaseKey
    label: Label
    name: str
    recurs: bool


REPORT: Final = CaseKind("zgloszenie", REPORT_LABEL, "Zgłoszenie", recurs=True)
NOTE: Final = CaseKind("uwaga", "uwaga-taty", "Uwaga taty", recurs=False)
KINDS: Final = (REPORT, NOTE)
_BY_KEY: Final[Mapping[str, CaseKind]] = {kind.key: kind for kind in KINDS}

_ANSWERS: Final[Mapping[CloseReason | None, notifications_contract.Resolved | notifications_contract.ReadByMaks]] = {
    "completed": notifications_contract.Resolved(state="resolved"),
    # ZEWNĘTRZNE: GitHub zamyka issue bez podanego powodu jako „completed” (GitHub REST API, Issues, pole state_reason)
    None: notifications_contract.Resolved(state="resolved"),
    "not_planned": notifications_contract.ReadByMaks(state="read"),
    "duplicate": notifications_contract.ReadByMaks(state="read"),
}


@dataclass(frozen=True)
class Case:
    kind: CaseKind
    id: str
    title: str | None
    commit: str | None
    sent_at: datetime | None
    number: int | None
    closure: Closure | None = None
    run_id: str | None = None

    @property
    def open(self) -> bool:
        return self.number is not None and self.closure is None


@dataclass(frozen=True)
class CaseNumbered:
    case_id: str
    number: int


@dataclass(frozen=True)
class CaseRejected:
    case_id: str


CaseNews = CaseNumbered | CaseRejected
Watcher = Callable[[CaseNews], None]


class DadCases:
    def __init__(self, work: CentrumWork) -> None:
        self.file = StateFile(work.config / DAD_CASES_FILE, work.log, where="stan Spraw taty", pause=work.pause)
        self._lock = threading.Lock()
        self._cases = _load(work.config)
        self._rejected: set[str] = set()
        self._watchers: dict[CaseKind, list[Watcher]] = {}

    def all(self) -> list[Case]:
        with self._lock:
            return list(self._cases)

    def find(self, kind: CaseKind, case_id: str) -> Case | None:
        return next((case for case in reversed(self.all()) if case.kind == kind and case.id == case_id), None)

    def add(self, case: Case) -> None:
        self._change(lambda cases: [*cases, case])

    def forget(self, kind: CaseKind, case_id: str) -> None:
        self._change(lambda cases: [case for case in cases if not (case.kind == kind and case.id == case_id)])

    def withdraw(self, case: Case) -> None:
        self._change(lambda cases: [known for known in cases if known != case])

    def numbered(self, kind: CaseKind, case_id: str, number: int) -> bool:
        found: list[Case] = []

        def ours(case: Case) -> bool:
            return case.kind == kind and case.id == case_id

        def change(cases: list[Case]) -> list[Case]:
            if not kind.recurs:
                found.extend(case for case in cases if ours(case))
                return [replace(case, number=number) if ours(case) else case for case in cases]
            pending = next((case for case in reversed(cases) if ours(case) and case.number is None), None)
            if pending is None:
                return cases
            found.append(pending)
            if any(case.number == number for case in cases):
                return [case for case in cases if case is not pending]
            return [replace(case, number=number) if case is pending else case for case in cases]

        self._change(change)
        if found:
            self._tell(kind, CaseNumbered(case_id, number))
        return bool(found)

    def rejected(self, kind: CaseKind, case_id: str) -> None:
        with self._lock:
            self._rejected.add(case_id)
        self._tell(kind, CaseRejected(case_id))

    def watch(self, kind: CaseKind, watcher: Watcher) -> None:
        with self._lock:
            self._watchers.setdefault(kind, []).append(watcher)

    def _tell(self, kind: CaseKind, news: CaseNews) -> None:
        with self._lock:
            watchers = list(self._watchers.get(kind, ()))
        for watcher in watchers:
            watcher(news)

    def queued(self, case_id: str, box: KeyedBox) -> common_contract.Queued | common_contract.Rejected:
        with self._lock:
            if case_id in self._rejected:
                return common_contract.Rejected(state="rejected")
        refused = box.judge(wait_s=0) in ("missing", "refused")
        return common_contract.Queued(state="queued", waits_for="key" if refused else "internet")

    def state(self, case: Case, box: KeyedBox) -> notifications_contract.CaseState:
        if case.number is None:
            return self.queued(case.id, box)
        closure = case.closure
        return common_contract.Sent(state="sent") if closure is None else _ANSWERS[closure.reason]

    def ask_box(self, box: KeyedBox) -> None:
        asked = {case.kind for case in self.all() if case.open}
        for kind in (kind for kind in KINDS if kind in asked):
            issues = box.labelled_issues(kind.label, include_closed=True)
            if not isinstance(issues, NoKey | Refused | Unreachable):
                self._close({issue.number: issue.closure for issue in issues})

    def _close(self, closures: Mapping[int | None, Closure | None]) -> None:
        self._change(lambda cases: [replace(case, closure=closures.get(case.number, case.closure)) for case in cases])

    def _change(self, change: Callable[[list[Case]], list[Case]]) -> None:
        with self._lock:
            changed = change(self._cases)
            if changed == self._cases:
                self.file.retry()
                return
            self._cases = changed
            document = {"schema_version": SCHEMA_VERSION, "sprawy": [_case_json(case) for case in self._cases]}
            self.file.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def _load(config_directory: Path) -> list[Case]:
    try:
        document = json.loads((config_directory / DAD_CASES_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        reports = _document(config_directory / OLD_REPORTS_FILE)
        notes = _document(config_directory / OLD_NOTES_FILE)
        return _cases(_old_reports(reports)) + _cases(_old_notes(notes))
    except (OSError, ValueError):
        return []
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        return []
    return _cases(document.get("sprawy"))


def _document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _old_reports(document: object) -> object:
    if not isinstance(document, list):
        return None
    return [
        {"kind": REPORT.key, "id": entry.get("fingerprint"), "title": entry.get("what"), **_shared(entry, "sent_at")}
        for entry in document
        if isinstance(entry, dict) and type(entry.get("number")) is int
    ]


def _old_notes(document: object) -> object:
    if not isinstance(document, dict) or document.get("schema_version") != _OLD_NOTES_SCHEMA:
        return None
    entries = document.get("uwagi")
    if not isinstance(entries, list):
        return None
    return [
        {
            "kind": NOTE.key,
            "id": entry.get("id"),
            "title": entry.get("title"),
            **_shared(entry, "written_at"),
            "run_id": entry.get("run_id"),
        }
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("title"), str) and read_moment(entry.get("written_at"))
    ]


def _shared(entry: dict[str, object], sent_at: str) -> dict[str, object]:
    return {
        "commit": entry.get("commit"),
        "sent_at": entry.get(sent_at),
        "number": entry.get("number"),
        "closure": entry.get("closure"),
    }


def _cases(entries: object) -> list[Case]:
    return [case for case in map(_case, entries) if case is not None] if isinstance(entries, list) else []


def _case(entry: object) -> Case | None:
    if not isinstance(entry, dict):
        return None
    kind, case_id, title, commit, number, run_id = (
        entry.get(name) for name in ("kind", "id", "title", "commit", "number", "run_id")
    )
    if not (isinstance(kind, str) and kind in _BY_KEY and isinstance(case_id, str)):
        return None
    if not (
        isinstance(commit, str | None) and isinstance(run_id, str | None) and (number is None or type(number) is int)
    ):
        return None
    return Case(
        _BY_KEY[kind],
        case_id,
        title if isinstance(title, str) else None,
        commit,
        read_moment(entry.get("sent_at")),
        number,
        _closure(entry.get("closure")),
        run_id,
    )


def _case_json(case: Case) -> dict[str, object]:
    closure = case.closure
    return {
        "kind": case.kind.key,
        "id": case.id,
        "title": case.title,
        "commit": case.commit,
        "sent_at": None if case.sent_at is None else case.sent_at.isoformat(),
        "number": case.number,
        "closure": None
        if closure is None
        else {"reason": closure.reason, "at": None if closure.at is None else closure.at.isoformat()},
        "run_id": case.run_id,
    }


def _closure(value: object) -> Closure | None:
    if not isinstance(value, dict):
        return None
    return Closure(close_reason(value.get("reason")), read_moment(value.get("at")))
