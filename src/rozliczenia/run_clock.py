from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class RunClock:
    def __init__(self, raw: Callable[[], float] = time.perf_counter) -> None:
        self._raw = raw
        self._held_s = 0.0
        self._held_at = 0.0
        self._holds = 0

    def now(self) -> float:
        return (self._held_at if self._holds else self._raw()) - self._held_s

    @contextmanager
    def hold(self) -> Iterator[None]:
        if not self._holds:
            self._held_at = self._raw()
        self._holds += 1
        try:
            yield
        finally:
            self._holds -= 1
            if not self._holds:
                self._held_s += self._raw() - self._held_at
