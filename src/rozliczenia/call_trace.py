from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rozliczenia.tool_files import TOOL_ROOT

_OUTSIDE_TOOL: Final = frozenset({".venv", "site-packages"})


@dataclass(frozen=True)
class CallFrame:
    file: str
    line: int
    function: str


@dataclass(frozen=True)
class CallCause:
    exception_type: str
    frames: tuple[CallFrame, ...]


@dataclass(frozen=True)
class CallTrace:
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
    path = Path(filename)
    if not path.is_absolute():
        return None
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if _OUTSIDE_TOOL & set(relative.parts):
        return None
    return relative.as_posix()
