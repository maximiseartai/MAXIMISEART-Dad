from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar

from .file_state import path_state
from .message import Message, StopError

ResultT = TypeVar("ResultT")

__all__ = ["LOCAL_DISK", "Disk", "publish_staged", "staging_prefix"]


def staging_prefix(name: str) -> str:
    return f".{name}.staging-"


def _make_staging(prefix: str, directory: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=directory))


def _remove_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


@dataclass(frozen=True)
class Disk:
    make_staging: Callable[[str, Path], Path] = _make_staging
    remove_staging: Callable[[Path], None] = _remove_staging


LOCAL_DISK: Final = Disk()


def publish_staged(
    directory: Path,
    name: str,
    publish: Callable[[Path], ResultT],
    *,
    failed: Message,
    left: Callable[[Message, str], Message],
    disk: Disk = LOCAL_DISK,
) -> ResultT:
    prefix = staging_prefix(name)
    try:
        staging = disk.make_staging(prefix, directory)
    except OSError as exc:
        raise StopError(failed) from exc
    try:
        try:
            result = publish(staging)
        except OSError as exc:
            raise StopError(failed) from exc
    except BaseException as error:
        disk.remove_staging(staging)
        if isinstance(error, StopError) and path_state(staging) != "missing":
            raise StopError(left(error.message, prefix)) from error
        raise
    disk.remove_staging(staging)
    return result
