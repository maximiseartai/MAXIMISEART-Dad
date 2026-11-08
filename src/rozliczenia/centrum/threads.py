"""Blokady, Eventy i wątki Uruchomień i zamknięcia Centrum rozliczeń jako szew konstruktora.

``RunHost``, jego ``Run`` i ``Shutdown`` biorą je z ``Threading`` podanego w konstruktorze, domyślnie z modułu
``threading``. Inne niż domyślne daje tylko wyrocznia ``verify-jedno-uruchomienie-naraz``: każde wejście w blokadę,
sygnał i start wątku jest u niej krokiem, o którego kolejności decyduje.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol


class Signal(Protocol):
    """``threading.Event`` w tym, czego używa Centrum."""

    def set(self) -> None: ...

    def clear(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class Startable(Protocol):
    def start(self) -> None: ...


class Threading(Protocol):
    """Moduł ``threading`` w tym, czego używają ``RunHost``, ``Run`` i ``Shutdown``; sam moduł go spełnia."""

    def Lock(self) -> AbstractContextManager[Any]: ...  # noqa: N802 - nazwa z threading

    def Event(self) -> Signal: ...  # noqa: N802 - nazwa z threading

    def Thread(self, *, target: Callable[[], object], name: str, daemon: bool) -> Startable: ...  # noqa: N802 - nazwa z threading
