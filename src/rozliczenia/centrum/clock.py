from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Final, Protocol


class Clock(Protocol):
    def __call__(self) -> float: ...

    def after(self, seconds: float, wake: Callable[[], None]) -> None: ...


ALARM_THREAD: Final = "budzik"


class SystemClock:
    def __call__(self) -> float:
        return time.monotonic()

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        timer = threading.Timer(seconds, wake)
        timer.daemon = True
        timer.name = ALARM_THREAD
        timer.start()


SYSTEM_CLOCK: Final = SystemClock()
