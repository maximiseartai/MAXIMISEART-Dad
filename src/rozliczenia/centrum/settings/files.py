"""Plik Ustawień Centrum w ``config``: jak go przeczytać, zapisać, porównać i cofnąć, ten sam opis dla każdego pliku.

Każdy plik ma jedną regułę ``parse``: sprawdza zapis taty, cofnięcie i plik zmieniony ręcznie, więc zła wartość nie
wchodzi żadną drogą. Brak pliku to wartość domyślna. Rejestr ``SETTINGS_FILES`` wymienia pliki, które ma właściciel
(``CentrumSettings``); kolejny plik to kolejny wpis z własnym ``parse``, ``dump``, ``diff`` i ``restore``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class FieldProblem:
    """Pierwszy problem treści pliku: pole w pliku (``rejestr_zlecen``) albo ``None`` dla całego pliku i zdanie dla taty."""

    field: str | None
    sentence: str


@dataclass(frozen=True)
class Good(Generic[T]):
    value: T


@dataclass(frozen=True)
class Bad(Generic[T]):
    """Złe ustawienie: problem treści pliku i ostatnia dobra wartość z pamięci właściciela (``None``: nieznana, więc
    obowiązują wartości domyślne pliku). Sekret, którego treści pamięć nie trzyma, ma tu wartość samej złej treści
    (``SettingsFile.unchecked``; ``None``: treść nie daje wartości)."""

    problem: FieldProblem
    usable: T | None


@dataclass(frozen=True)
class Unreadable:
    """Plik jest, ale system nie daje go teraz czytać (np. trzyma go antywirus): treść nieznana, a nie zła."""


Read = Good[T] | Bad[T]


@dataclass(frozen=True)
class KeyChange:
    """Zmiana jednego klucza (``sekcja.pole``) w wierszu Historii Ustawień: wartość przed i po, ``None``: nie ustawiono."""

    key: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class SettingsFile(Generic[T]):
    """Plik Ustawień Centrum w ``config``.

    ``parse`` dostaje bajty pliku (``None``: pliku nie ma) i daje wartość albo pierwszy problem, ``dump`` daje treść
    pliku, ``diff`` klucze, które różnią dwie wartości, a ``restore`` wartość z kluczami ustawionymi na ich wartość
    ``before``. ``restore`` może dać wartość, której ``parse`` nie przyjmie; właściciel sprawdza ją jak każdą zmianę.
    ``shown`` daje wartość klucza dla Zgłoszenia, bez danych osobowych. Plik ``secret`` ma w Historii tylko klucze, bez
    wartości, i nie da się go cofnąć. Ostatniej dobrej treści sekretu nikt nie pamięta, więc ``unchecked`` daje wartość
    jego treści bez reguł ``parse`` (``None``: treść nie daje wartości): zapis taty na złej treści zaczyna od niej, a
    ``parse`` zapisu odrzuca to, czego zapis nie naprawił.
    """

    name: str
    parse: Callable[[bytes | None], T | FieldProblem]
    dump: Callable[[T], str]
    diff: Callable[[T, T], tuple[KeyChange, ...]]
    restore: Callable[[T, tuple[KeyChange, ...]], T]
    shown: Callable[[str, str | None], str]
    default: T
    secret: bool = False
    unchecked: Callable[[bytes | None], T | None] | None = None
