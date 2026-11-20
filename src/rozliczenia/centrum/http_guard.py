from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract.common import Problem
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.timing import server_timing
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.tool_files import HOST

_LOCAL_HOSTNAMES = frozenset({HOST, "localhost"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def guard(app: FastAPI, log: CentrumLog) -> None:
    @app.middleware("http")
    async def only_local_browser(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if urlsplit(f"//{host}").hostname not in _LOCAL_HOSTNAMES:
            return _problem(refusal.not_local_address())
        if request.method not in _SAFE_METHODS and request.headers.get("origin") != f"http://{host}":
            return _problem(refusal.not_from_centrum_card())
        return await call_next(request)

    @app.middleware("http")
    async def unexpected_failure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as failure:
            route = request.scope.get("route")
            log.unexpected_failure(failure, where=f"{request.method} {getattr(route, 'path', 'poza API')}")
            return _problem(refusal.unexpected_failure())

    app.middleware("http")(server_timing)

    @app.exception_handler(Refusal)
    async def refused(request: Request, refused: Refusal) -> Response:
        return _problem(refused)

    @app.exception_handler(PeriodFolderInaccessible)
    async def inaccessible_folder(request: Request, inaccessible: PeriodFolderInaccessible) -> Response:
        return _problem(refusal.period_folder_unreadable(inaccessible.folder.name))


def _problem(refused: Refusal) -> Response:
    problem = Problem(message=refused.message, field=refused.field)
    return JSONResponse(problem.model_dump(exclude_none=True), status_code=refused.status_code)
