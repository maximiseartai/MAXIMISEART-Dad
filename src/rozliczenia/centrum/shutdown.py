from __future__ import annotations

from collections.abc import Callable
import threading

from fastapi import APIRouter

from rozliczenia.centrum.contract import centrum as centrum_contract
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.threads import Threading

ShutdownBlocker = Callable[[], Refusal | None]


class Shutdown:
    def __init__(self, log: CentrumLog, *, threads: Threading = threading) -> None:
        self._log = log
        self._requested = threads.Event()
        self._blocker: ShutdownBlocker = lambda: None

    def refuse_while(self, blocker: ShutdownBlocker) -> None:
        self._blocker = blocker

    def request(self) -> None:
        refused = self._blocker()
        if refused is not None:
            raise refused
        self._log.shutdown_requested()
        self._requested.set()

    def close_for_update(self) -> None:
        self._log.shutdown_for_update()
        self._requested.set()

    def wait(self) -> None:
        self._requested.wait()


def shutdown_router(shutdown: Shutdown) -> APIRouter:
    router = APIRouter(prefix="/api/shutdown", tags=["centrum"])

    @router.post("", operation_id="closeCentrum", status_code=202, responses={409: {"model": common_contract.Problem}})
    def close() -> centrum_contract.Closing:
        shutdown.request()
        return centrum_contract.Closing(state="closing")

    return router
