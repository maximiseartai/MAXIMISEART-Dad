from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final

from rozliczenia.centrum.log import CentrumLog

RETRY_PAUSES_S: Final = (0.05, 0.1, 0.2, 0.4)


def replace_atomically(
    path: Path,
    text: str | bytes,
    *,
    pause: Callable[[float], None] = time.sleep,
    pauses: Sequence[float] = RETRY_PAUSES_S,
    newline: str | None = None,
) -> None:
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if isinstance(text, bytes):
            temporary.write_bytes(text)
        else:
            temporary.write_text(text, encoding="utf-8", newline=newline)
        for seconds in pauses:
            try:
                temporary.replace(path)
                return
            # ZEWNĘTRZNE: Windows odmawia zamiany pliku, który inny program (antywirus, indeksowanie) trzyma na chwilę otwarty, a Python zgłasza ERROR_ACCESS_DENIED i ERROR_SHARING_VIOLATION jako PermissionError (Microsoft Learn MoveFileEx, CPython PC/errmap.h)
            except PermissionError:
                pause(seconds)
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


class StateFile:
    def __init__(self, path: Path, log: CentrumLog, *, where: str, pause: Callable[[float], None]) -> None:
        self.path = path
        self._log = log
        self._where = where
        self._pause = pause
        self._lock = threading.Lock()
        self._waiting: str | None = None

    @property
    def unavailable(self) -> bool:
        with self._lock:
            return self._waiting is not None

    def write(self, text: str) -> None:
        with self._lock:
            self._save(text)

    def retry(self) -> None:
        with self._lock:
            if self._waiting is not None:
                self._save(self._waiting)

    def _save(self, text: str) -> None:
        try:
            pauses = RETRY_PAUSES_S if self._waiting is None else ()
            replace_atomically(self.path, text, pause=self._pause, pauses=pauses)
        except OSError as failure:
            if self._waiting is None:
                self._log.unexpected_failure(failure, where=self._where)
            self._waiting = text
        else:
            self._waiting = None
