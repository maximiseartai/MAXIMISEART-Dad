"""Pomiar u taty: czas obsługi zapytań API i pomiary widoków z przeglądarki w dzienniku Centrum.

Każda odpowiedź API ma nagłówek ``Server-Timing`` z samym czasem obsługi
zapytania. Przeglądarka czyta go przy każdym zapytaniu i po gotowym widoku
(zimny start strony, przejście w menu) wysyła pomiar, który serwer dopisuje do
dziennika Centrum. Pomiar to same liczby i nazwy z kontraktu (strona z menu,
operacja API), więc do dziennika nie trafia adres zapytania, token okresu ani
ścieżka (ADR 0004). Dzięki temu Maks widzi u taty, czy wolny jest odczyt plików
z OneDrive (czas serwera), czy przeglądarka.
"""

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
