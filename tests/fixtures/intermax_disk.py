"""Kroki podmiany INTERMAX na dysku z usterką, którą test wkłada w jeden krok bez łatania ``os`` i ``Path``.

``FaultyDisk`` daje ``intermax_replace.Disk``, którego krok bez usterki jest prawdziwy. Usterkę można włożyć także
po starcie Centrum (przed przywróceniem Kopii po Uporządkowaniu), bo ``Disk`` pyta ``FaultyDisk`` przy każdym kroku.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import errno
import os
from pathlib import Path

from rozliczenia.intermax_replace import LOCAL_DISK, Disk

Write = Callable[[Path, bytes], None]
Read = Callable[[Path], bytes]
Exists = Callable[[Path], bool]
Replace = Callable[[Path, Path], None]
Remove = Callable[[Path], None]


@dataclass
class FaultyDisk:
    write: Write | None = None
    read: Read | None = None
    exists: Exists | None = None
    create: Write | None = None
    replace: Replace | None = None
    remove: Remove | None = None

    def disk(self) -> Disk:
        return Disk(
            write=lambda path, content: (self.write or LOCAL_DISK.write)(path, content),
            read=lambda path: (self.read or LOCAL_DISK.read)(path),
            exists=lambda path: (self.exists or LOCAL_DISK.exists)(path),
            create=lambda path, content: (self.create or LOCAL_DISK.create)(path, content),
            replace=lambda source, target: (self.replace or LOCAL_DISK.replace)(source, target),
            remove=lambda path: (self.remove or LOCAL_DISK.remove)(path),
        )


def failing_replace(
    error: Callable[[], OSError], *, times: int | None = None, before: Callable[[], object] = lambda: None
) -> tuple[Replace, list[int]]:
    attempts: list[int] = []

    def replace(source: Path, target: Path) -> None:
        attempts.append(1)
        assert len(attempts) < 100, "ponowna próba bez przerwy na zegarze procesu"
        before()
        if times is None or len(attempts) <= times:
            raise error()
        LOCAL_DISK.replace(source, target)

    return replace, attempts


def denied() -> OSError:
    """Odmowa dostępu przy podmianie: Windows, gdy plik trzyma Excel albo OneDrive."""

    return PermissionError(errno.EACCES, os.strerror(errno.EACCES))


def no_space() -> OSError:
    return OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


def writing(change: Callable[[bytes], bytes]) -> Write:
    def write(path: Path, content: bytes) -> None:
        LOCAL_DISK.write(path, change(content))

    return write


def partial_copy(path: Path, content: bytes) -> None:
    """Kopia INTERMAX, której zapis kończy się brakiem miejsca na dysku po pierwszych bajtach."""

    LOCAL_DISK.create(path, content[:100])
    raise no_space()
