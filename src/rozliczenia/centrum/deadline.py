from __future__ import annotations

from collections.abc import Callable
import threading
from typing import TypeVar

T = TypeVar("T")


def within(seconds: float, call: Callable[[], T], *, name: str) -> T | None:
    answer: list[T] = []
    # ZEWNĘTRZNE: limit czasu gniazda nie obejmuje rozwiązywania nazwy, bo socket.create_connection woła getaddrinfo, zanim ustawi limit gniazda (CPython Lib/socket.py)
    worker = threading.Thread(target=lambda: answer.append(call()), name=name, daemon=True)
    worker.start()
    worker.join(seconds)
    return answer[0] if answer else None
