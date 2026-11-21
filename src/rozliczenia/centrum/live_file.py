from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import threading
from typing import Final, Generic, TypeVar

from rozliczenia.wall_clock import utc_now

SHOWN_FAILING_AFTER_S: Final = 60.0
RETRY_GAP_S: Final = 15.0

T = TypeVar("T")


def saved_version(path: Path) -> str | None:
    try:
        status = path.stat()
    except OSError:
        return None
    return f"{status.st_mtime_ns}-{status.st_size}"


@dataclass(frozen=True)
class GoodRead(Generic[T]):
    value: T
    version: str | None
    read_at: datetime
    retrying: bool = False


@dataclass(frozen=True)
class Attempt:
    version: str | None
    started: float


@dataclass(frozen=True)
class Failing(Generic[T]):
    kept: GoodRead[T] | None
    new_cause: bool


@dataclass(frozen=True)
class _Series:
    first_started: float
    last_ended: float
    last_version: str | None
    gave_message: bool
    logged_causes: frozenset[str]

    def continues(self, attempt: Attempt) -> bool:
        return (
            self.gave_message
            or attempt.started - self.last_ended <= RETRY_GAP_S
            or attempt.version == self.last_version
        )


@dataclass
class _File(Generic[T]):
    last: GoodRead[T] | None = None
    failing: _Series | None = None


class LastGoodReads(Generic[T]):
    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._files: dict[Path, _File[T]] = {}

    def attempt(self, path: Path) -> Attempt:
        return Attempt(saved_version(path), self._clock())

    def succeeded(self, path: Path, value: T, attempt: Attempt) -> GoodRead[T]:
        with self._lock:
            file = self._files.setdefault(path, _File())
            file.last = GoodRead(value, attempt.version, utc_now())
            file.failing = None
            return file.last

    def forget_all(self) -> None:
        with self._lock:
            self._files.clear()

    def failed(self, path: Path, attempt: Attempt, cause: str) -> Failing[T]:
        with self._lock:
            file = self._files.setdefault(path, _File())
            now = self._clock()
            before = file.failing
            if before is not None and before.continues(attempt):
                since, causes = before.first_started, before.logged_causes
            else:
                since, causes = attempt.started, before.logged_causes if before is not None else frozenset()
            kept = None
            if file.last is not None and now - since < SHOWN_FAILING_AFTER_S:
                kept = replace(file.last, retrying=True)
            file.failing = _Series(
                since, now, attempt.version, gave_message=kept is None, logged_causes=causes | {cause}
            )
            return Failing(kept, cause not in causes)
