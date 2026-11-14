"""Sen kodu pod testem bez prawdziwego czekania i bez snów innych wątków procesu workera pytest."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest


def sleep_in_test_thread(monkeypatch: pytest.MonkeyPatch, pause: Callable[[float], None]) -> None:
    """``time.sleep`` w wątku testu woła ``pause`` zamiast spać, a w każdym innym wątku śpi naprawdę.

    ``time.sleep`` jest jeden na cały proces workera pytest, a w nim żyją też wątki sąsiadów, np. budzik
    ``ScriptedClock`` skilla verify-centrum-rozliczen, który śpi po 0,2 s (#1783). Podmiana dla całego procesu
    zapisałaby ich sny jako sny kodu pod testem, a ich pętla bez snu kręciłaby się do końca testu.
    """

    sleep = time.sleep
    test_thread = threading.current_thread()

    def sleep_or_pause(seconds: float) -> None:
        (pause if threading.current_thread() is test_thread else sleep)(seconds)

    monkeypatch.setattr(time, "sleep", sleep_or_pause)
