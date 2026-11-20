from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache
import os
import sys
from typing import Any, NamedTuple

import pytest


class Reach(NamedTuple):
    event: str
    path: str


Trace = list[Reach]
_ACTIVE: list[Trace] = []
LISTING = ("os.listdir", "os.scandir")
_PATH_EVENTS = frozenset({"open", "os.listdir", "os.scandir", "os.rename", "os.remove", "os.rmdir", "os.mkdir",
                          "shutil.copyfile", "stat", "lstat"})


def record(event: str, args: tuple[object, ...]) -> None:
    if event not in _PATH_EVENTS:
        return
    for trace in _ACTIVE:
        trace.extend(Reach(event, os.fsdecode(arg)) for arg in args if isinstance(arg, str | bytes | os.PathLike))


@cache
def _audit_hook() -> None:
    # ZEWNĘTRZNE: hooka audytu nie da się zdjąć, więc zostaje w workerze do końca sesji (PEP 578)
    sys.addaudithook(record)


def _recorded(stat: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
    def recorded(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        record(stat.__name__, (path,))
        return stat(path, *args, **kwargs)

    return recorded


@contextmanager
def tracing() -> Iterator[Trace]:
    _audit_hook()
    trace: Trace = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "stat", _recorded(os.stat))
        patch.setattr(os, "lstat", _recorded(os.lstat))
        _ACTIVE.append(trace)
        try:
            yield trace
        finally:
            _ACTIVE.remove(trace)
