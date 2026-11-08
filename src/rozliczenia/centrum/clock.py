"""Zegar Centrum rozliczeń: czas monotoniczny w sekundach i budzik na tym samym zegarze.

Jedyne źródło czasu dla pamięci odpowiedzi (``RememberedRelease``, ``KeyedBox``), rytmu Powiadomień i ponawiania
kolejki Skrzynki. U taty ``SYSTEM_CLOCK``; testy podstawiają zegar, który przesuwają same i który budzi w ich wątku.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Final, Protocol


class Clock(Protocol):
    def __call__(self) -> float:
        """Teraz, w sekundach zegara monotonicznego."""
        ...

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        """Woła ``wake`` raz w innym wątku, gdy na tym zegarze minie ``seconds``; bez odwołania."""
        ...


# Nazwa wątku budzika ``SystemClock.after``.
ALARM_THREAD: Final = "budzik"


class SystemClock:
    """``time.monotonic`` i budzik z ``threading.Timer`` jako wątek demona: zamknięcie Centrum na niego nie czeka."""

    def __call__(self) -> float:
        return time.monotonic()

    def after(self, seconds: float, wake: Callable[[], None]) -> None:
        timer = threading.Timer(seconds, wake)
        timer.daemon = True
        timer.name = ALARM_THREAD
        timer.start()


SYSTEM_CLOCK: Final = SystemClock()
