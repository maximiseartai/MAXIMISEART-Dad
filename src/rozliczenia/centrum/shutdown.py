"""Zamknięcie Centrum rozliczeń przyciskiem „Zamknij Centrum rozliczeń”.

Zamknięcie karty przeglądarki nie wyłącza serwera; robi to tylko ta prośba
(albo wylogowanie z Windows). ``serve`` czeka na prośbę i kończy pracę po
wysłaniu odpowiedzi. Trwające Uruchomienie procesu odmawia zamknięcia przez
``refuse_while``. Po udanej Aktualizacji narzędzia Centrum zamyka się samo
(``close_for_update``), a nową wersję startuje opiekun ponownego startu.
"""

from __future__ import annotations

from collections.abc import Callable
import threading

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.threads import Threading

ShutdownBlocker = Callable[[], str | None]
"""Bezpieczny komunikat, dlaczego teraz nie można zamknąć Centrum, albo ``None``, gdy można."""


class Shutdown:
    def __init__(self, log: CentrumLog, *, threads: Threading = threading) -> None:
        """``threads`` daje Event prośby o zamknięcie; inny niż moduł ``threading`` daje tylko wyrocznia
        ``verify-jedno-uruchomienie-naraz`` (``threads.Threading``)."""

        self._log = log
        self._requested = threads.Event()
        self._blocker: ShutdownBlocker = lambda: None

    def refuse_while(self, blocker: ShutdownBlocker) -> None:
        """Warunek odmowy, sprawdzany przy każdej prośbie o zamknięcie (``Shutdown`` powstaje przed serwerem)."""

        self._blocker = blocker

    def request(self) -> None:
        message = self._blocker()
        if message is not None:
            raise contract.Refusal(409, message)
        self._log.shutdown_requested()
        self._requested.set()

    def close_for_update(self) -> None:
        """Zamknięcie po udanej Aktualizacji narzędzia, bez warunku odmowy: miejsce „jedno naraz” trzyma ona sama."""

        self._log.shutdown_for_update()
        self._requested.set()

    def wait(self) -> None:
        self._requested.wait()


def shutdown_router(shutdown: Shutdown) -> APIRouter:
    router = APIRouter(prefix="/api/shutdown", tags=["centrum"])

    @router.post("", operation_id="closeCentrum", status_code=202, responses={409: {"model": contract.Problem}})
    def close() -> contract.Closing:
        shutdown.request()
        return contract.Closing(state="closing")

    return router
