"""Zmiana Ustawień Centrum w Wydaniu (``release_changes``): co widzi przy starcie i co proponuje właścicielowi."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from rozliczenia.centrum.settings.files import Read, SettingsFile, Unreadable

T = TypeVar("T")


@dataclass(frozen=True)
class ReleaseInputs(Generic[T]):
    """Co zmiana widzi przy starcie: wartość swojego pliku po wykryciu zmiany spoza Centrum i folder ``config`` ze
    starymi plikami, które migracja przenosi."""

    current: Read[T] | Unreadable
    config: Path


@dataclass(frozen=True)
class Edit(Generic[T]):
    """Edycja bieżącej wartości pliku; ``undoable=False`` dla migracji, której cofnięcie zostawiłoby Centrum bez danych."""

    edit: Callable[[T], T]
    undoable: bool = True


@dataclass(frozen=True)
class Nothing:
    """Nic do zmiany (np. plik już przeniesiony): zmiana jest zapamiętana bez wiersza Historii."""


@dataclass(frozen=True)
class Later:
    """Teraz się nie da (np. OneDrive nie oddał folderu): bez wiersza i bez pamięci, zmiana wraca przy następnym starcie."""

    reason: str


@dataclass(frozen=True)
class Refuse:
    """Zmiana nie wejdzie: wiersz Historii ``odrzucono`` ze zdaniem dla taty, a zmiana już nie wraca."""

    sentence: str


Proposal = Edit[T] | Nothing | Later | Refuse


@dataclass(frozen=True)
class ReleaseChange(Generic[T]):
    """Zmiana jednego pliku Ustawień Centrum; ``id`` w postaci ``rrrr-mm-nazwa`` jest jej pamięcią u taty.

    ``refused_absent``: zdanie złego ustawienia, gdy zmiana została odrzucona, a jej pliku dalej nie ma (migracja, bez
    której plik nie ma danych taty); ``None``: brak pliku po odmowie to wartości domyślne pliku."""

    id: str
    file: SettingsFile[T]
    propose: Callable[[ReleaseInputs[T]], Proposal[T]]
    refused_absent: str | None = None
