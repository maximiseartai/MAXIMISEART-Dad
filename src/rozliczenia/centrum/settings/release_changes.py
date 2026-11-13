"""Zmiany Ustawień Centrum w Wydaniu (ADR 0032, furtka Maksa): jawne, nazwane, jednorazowe zmiany, które Wydanie niesie
w kodzie, bo Aktualizacja narzędzia nie nadpisuje plików w ``config``.

Właściciel (``CentrumSettings.apply_release_changes``) stosuje przy każdym starcie Centrum, przed pierwszym zapytaniem,
każdą zmianę, której jeszcze nie zapamiętał, z tymi samymi sprawdzeniami co zmiana taty. Zmiana, która weszła, ma w
Historii Ustawień źródło z numerem Wydania i „Cofnij”, a odrzucona ma powód i nie wraca. Wydanie bez wpisu niczego nie pisze.

Wpis dopisuje się do ``RELEASE_CHANGES`` obok wpisów tej samej funkcji, nigdy nie zmienia się ani nie usuwa wpisu z
Wydania, które już wyszło: jego id jest w pamięci właściciela u taty. Edycja jest deklaratywna („ustaw”, „dodaj, jeśli
nie ma”), bo po utracie pamięci właściciela zmiana biegnie jeszcze raz i wtedy nie może dać różnicy ani wiersza.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Generic, TypeVar

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
    """Zmiana jednego pliku Ustawień Centrum; ``id`` w postaci ``rrrr-mm-nazwa`` jest jej pamięcią u taty."""

    id: str
    file: SettingsFile[T]
    propose: Callable[[ReleaseInputs[T]], Proposal[T]]


RELEASE_CHANGES: Final[tuple[ReleaseChange[Any], ...]] = ()
"""Zmiany Ustawień Centrum, które niesie to Wydanie i każde poprzednie."""
