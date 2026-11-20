from __future__ import annotations

from datetime import datetime
import threading
from typing import Final, TypeGuard, get_args

from fastapi import Request
from pydantic import RootModel, ValidationError

from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.dad_actions import ButtonPressed, CentrumStarted, DadAction, DadActions, ViewOpened
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.wall_clock import utc_now

DAD_ACTIONS_FILE: Final = "dzialania-taty.jsonl"
MAX_ENTRIES: Final = 1000
_API_OPERATIONS: Final[frozenset[str]] = frozenset(get_args(timing_contract.ApiOperation))
_SENT_WHILE_TYPING: Final[frozenset[timing_contract.ApiOperation]] = frozenset({"draftDadNote"})


class _Line(RootModel[DadAction]):
    ...


class DadActionJournal:
    def __init__(self, work: CentrumWork) -> None:
        self._path = work.log.directory / DAD_ACTIONS_FILE
        self._log = work.log
        self._lock = threading.Lock()
        self._unwritten_start: CentrumStarted | None = CentrumStarted(at=utc_now(), action="start Centrum")

    async def observe(self, request: Request) -> None:
        operation = getattr(request.scope.get("route"), "operation_id", None)
        if request.method == "GET" or operation is None:
            return
        at = utc_now()
        if operation == "recordViewTiming":
            try:
                timing = timing_contract.ViewTiming.model_validate_json(await request.body())
            except ValidationError:
                return
            self._add(ViewOpened(at=at, action="widok", page=timing.page, kind=timing.kind))
        elif _is_api_operation(operation) and operation not in _SENT_WHILE_TYPING:
            self._add(_pressed(at, operation, await request.body()))

    def take(self) -> DadActions:
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                lines = []
            except OSError as failure:
                self._log.dad_actions_unavailable(failure)
                return DadActions(entries=[], omitted=0)
            try:
                replace_atomically(self._path, "")
            except OSError as failure:
                self._log.dad_actions_unavailable(failure)
        entries: list[DadAction] = []
        for line in lines:
            try:
                entries.append(_Line.model_validate_json(line).root)
            except ValidationError:
                continue
        kept = entries[-MAX_ENTRIES:]
        return DadActions(entries=kept, omitted=len(lines) - len(kept))

    def _add(self, action: DadAction) -> None:
        try:
            with self._lock:
                pending = [action] if self._unwritten_start is None else [self._unwritten_start, action]
                text = "".join(_Line(entry).model_dump_json() + "\n" for entry in pending)
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as journal:
                    journal.write(text)
                self._unwritten_start = None
        except OSError as failure:
            self._log.dad_actions_unavailable(failure)


def _is_api_operation(operation: str) -> TypeGuard[timing_contract.ApiOperation]:
    return operation in _API_OPERATIONS


def _pressed(at: datetime, operation: timing_contract.ApiOperation, body: bytes) -> ButtonPressed:
    if operation == "startRun":
        try:
            request = runs_contract.RunRequest.model_validate_json(body)
        except ValidationError:
            pass
        else:
            return ButtonPressed(
                at=at, action="przycisk", operation=operation, process=request.process, mode=request.mode
            )
    return ButtonPressed(at=at, action="przycisk", operation=operation)
