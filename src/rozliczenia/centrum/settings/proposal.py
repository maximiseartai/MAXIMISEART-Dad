from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from rozliczenia.centrum.settings.files import Read, SettingsFile, Unreadable

T = TypeVar("T")


@dataclass(frozen=True)
class ReleaseInputs(Generic[T]):
    current: Read[T] | Unreadable
    config: Path


@dataclass(frozen=True)
class Edit(Generic[T]):
    edit: Callable[[T], T]
    undoable: bool = True


@dataclass(frozen=True)
class Nothing:
    ...


@dataclass(frozen=True)
class Later:
    reason: str


@dataclass(frozen=True)
class Refuse:
    sentence: str


Proposal = Edit[T] | Nothing | Later | Refuse


@dataclass(frozen=True)
class Waiting:
    sentence: str
    old_files: Callable[[Path], bool]


@dataclass(frozen=True)
class ReleaseChange(Generic[T]):
    id: str
    file: SettingsFile[T]
    propose: Callable[[ReleaseInputs[T]], Proposal[T]]
    refused_absent: str | None = None
    waiting: Waiting | None = None
