from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final
import time

from fastapi import APIRouter, Request, Response

from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.log import CentrumLog

SERVER_TIMING_METRIC = "centrum"
_VIEW_NAMES: Final[dict[timing_contract.ViewKind, str]] = {"cold_start": "zimny-start", "navigation": "przejscie-w-menu"}


def timing_router(log: CentrumLog) -> APIRouter:
    router = APIRouter(prefix="/api/view-timings", tags=["centrum"])

    @router.post("", operation_id="recordViewTiming", status_code=204)
    def record(timing: timing_contract.ViewTiming) -> None:
        log.view_timed(
            view=_VIEW_NAMES[timing.kind],
            page=timing.page,
            ready_ms=timing.ready_ms,
            fcp_ms=timing.fcp_ms,
            skeleton_ms=timing.skeleton_ms,
            requests=[(request.operation, request.browser_ms, request.server_ms) for request in timing.requests],
        )

    return router


async def server_timing(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"{SERVER_TIMING_METRIC};dur={elapsed_ms:.1f}"
    return response
