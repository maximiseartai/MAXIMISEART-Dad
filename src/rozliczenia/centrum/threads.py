from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol


class Signal(Protocol):
    def set(self) -> None: ...

    def clear(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class Startable(Protocol):
    def start(self) -> None: ...


class Threading(Protocol):
    def Lock(self) -> AbstractContextManager[Any]: ...  # noqa: N802 - nazwa z threading

    def Event(self) -> Signal: ...  # noqa: N802 - nazwa z threading

    def Thread(self, *, target: Callable[[], object], name: str, daemon: bool) -> Startable: ...  # noqa: N802 - nazwa z threading
