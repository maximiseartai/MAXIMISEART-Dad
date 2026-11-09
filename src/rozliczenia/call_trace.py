"""Ślad wywołań wyjątku w kodzie narzędzia, bez treści wyjątku.

Treść wyjątku może mieć dane z Rejestru zleceń, a pełna ścieżka nazwę konta, więc ślad nie ma ani jednego, ani
drugiego. Ramki bibliotek i biblioteki standardowej są pomijane. Ślad niesie tylko Zatrzymanie; pokazują go Zgłoszenie
do Maksa (ADR 0007) i Logi Uruchomienia.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rozliczenia.tool_files import TOOL_ROOT

_OUTSIDE_TOOL: Final = frozenset({".venv", "site-packages"})


@dataclass(frozen=True)
class CallFrame:
    """Ramka kodu narzędzia: plik względem katalogu narzędzia (z ``/``), linia i funkcja."""

    file: str
    line: int
    function: str


@dataclass(frozen=True)
class CallCause:
    """Przyczyna z łańcucha ``__cause__``: typ wyjątku i ramki kodu narzędzia od miejsca, w którym przeszła w następny
    wyjątek, do miejsca rzucenia."""

    exception_type: str
    frames: tuple[CallFrame, ...]


@dataclass(frozen=True)
class CallTrace:
    """Typ wyjątku i ramki kodu narzędzia od miejsca przechwycenia do miejsca rzucenia, a w ``causes`` łańcuch
    ``__cause__`` po kolei, od bezpośredniej przyczyny do źródłowej."""

    exception_type: str
    frames: tuple[CallFrame, ...]
    causes: tuple[CallCause, ...] = ()

    @classmethod
    def of(cls, error: BaseException) -> CallTrace:
        causes: list[CallCause] = []
        cause = error.__cause__
        while cause is not None and len(causes) < _MAX_CAUSES:
            causes.append(CallCause(exception_type(cause), _frames(cause)))
            cause = cause.__cause__
        return cls(exception_type(error), _frames(error), tuple(causes))


_MAX_CAUSES: Final = 10
"""Łańcuch przyczyn dłuższy niż ten jest ucięty, także łańcuch, który wraca do siebie."""


def exception_type(error: BaseException) -> str:
    kind = type(error)
    return kind.__qualname__ if kind.__module__ == "builtins" else f"{kind.__module__}.{kind.__qualname__}"


def _frames(error: BaseException) -> tuple[CallFrame, ...]:
    return tuple(
        CallFrame(file, frame.lineno or 0, frame.name)
        for frame in traceback.extract_tb(error.__traceback__)
        if (file := _tool_file(frame.filename, TOOL_ROOT)) is not None
    )


def _tool_file(filename: str, root: Path) -> str | None:
    """Plik ramki względem ``root``; ``None`` poza kodem narzędzia (biblioteki, środowisko Pythona)."""

    path = Path(filename)
    if not path.is_absolute():  # np. „<frozen runpy>” albo „<string>”
        return None
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if _OUTSIDE_TOOL & set(relative.parts):
        return None
    return relative.as_posix()
