"""Zegar testu dla maszyny pomiarów ``tools/quiet_machine.py``.

Zegar testu przesuwa się tylko wtedy, gdy maszyna śpi między sprawdzeniami, więc minuty
czekania mijają od razu, a o zadanej minucie dzieje się to, co test zaplanował.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["ZegarTestu"]


class ZegarTestu:
    def __init__(self) -> None:
        self.now = 0.0
        self._planned: list[tuple[float, Callable[[], None]]] = []

    def at(self, seconds: float, action: Callable[[], None]) -> None:
        self._planned.append((seconds, action))

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        due = [action for at, action in self._planned if at <= self.now]
        self._planned = [(at, action) for at, action in self._planned if at > self.now]
        for action in due:
            action()
