"""Praca Centrum (``CentrumWork``) dla testów modułów Centrum, które budują je bez aplikacji."""

from __future__ import annotations

from pathlib import Path

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.client_data import ForbiddenValues
from tests.fixtures.clock import ManualClock


def centrum_work(config: Path, log: CentrumLog, clock: ManualClock | None = None) -> CentrumWork:
    """Praca Centrum testu modułu bez aplikacji: pliki stanu w ``config``, dziennik ``log`` i zegar, który stoi."""

    clock = clock or ManualClock()
    return CentrumWork(config=config, log=log, clock=clock, pause=clock.pause, forbidden=ForbiddenValues())
