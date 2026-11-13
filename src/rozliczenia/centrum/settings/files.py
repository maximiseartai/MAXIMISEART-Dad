"""Plik Ustawień Centrum w ``config``: jak go przeczytać, zapisać, porównać i cofnąć, ten sam opis dla każdego pliku.

Każdy plik ma jedną regułę ``parse``: sprawdza zapis taty, cofnięcie i plik zmieniony ręcznie, więc zła wartość nie
wchodzi żadną drogą. Brak pliku to wartość domyślna. Rejestr ``SETTINGS_FILES`` wymienia pliki, które ma właściciel
(``CentrumSettings``); kolejny plik to kolejny wpis z własnym ``parse``, ``dump``, ``diff`` i ``restore``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")


FieldName = Literal[
    # centrum-ustawienia.yaml
    "rejestr_zlecen",
    "folder_okresow",
    "motyw",
    # wykonawcy.yaml
    "wykonawcy",
    "do_rozstrzygniecia",
    "nazwa",
    "loginy",
    "adresy",
    "aktywny",
    "przypomnienia",
]
"""Znane nazwy pól plików Ustawień: jedyne słowa, z których powstaje ``FieldPath``."""


@dataclass(frozen=True, init=False)
class FieldPath:
    """Miejsce pola w pliku Ustawień (``wykonawcy[2].adresy[0]``), złożone tylko ze znanych nazw pól i numerów pozycji.

    Miejsce trafia do Logów Centrum, Historii Ustawień i Zgłoszenia, więc tekst z pliku (nieznany klucz, który bywa
    loginem albo nazwą) nie ma tu drogi: konstruktor przyjmuje tylko ``FieldName`` i ``int``, inny tekst odrzuca mypy.
    """

    text: str

    def __init__(self, first: FieldName, *rest: FieldName | int) -> None:
        parts = (f"[{part}]" if isinstance(part, int) else f".{part}" for part in rest)
        object.__setattr__(self, "text", first + "".join(parts))


@dataclass(frozen=True)
class FieldProblem:
    """Pierwszy problem treści pliku: pole w pliku (``rejestr_zlecen``) albo ``None`` dla całego pliku i zdanie dla taty."""

    field: FieldPath | None
    sentence: str

    @property
    def place(self) -> str | None:
        """Pole jako tekst odmowy, kontraktu i Logów Centrum; ``None`` dla całego pliku."""

        return None if self.field is None else self.field.text


@dataclass(frozen=True)
class Good(Generic[T]):
    value: T


@dataclass(frozen=True)
class Bad(Generic[T]):
    """Złe ustawienie: problem treści pliku i ostatnia dobra wartość z pamięci właściciela (``None``: nieznana, więc
    obowiązują wartości domyślne pliku)."""

    problem: FieldProblem
    usable: T | None


@dataclass(frozen=True)
class Unreadable:
    """Plik jest, ale system nie daje go teraz czytać (np. trzyma go antywirus): treść nieznana, a nie zła."""


Read = Good[T] | Bad[T]


def usable(read: Read[T] | Unreadable) -> T | None:
    """Wartość, na której proces może biec: dobra albo ostatnia dobra przy złym pliku; ``None``: żadnej nie ma."""

    match read:
        case Good(value=value):
            return value
        case Bad(usable=value):
            return value
        case Unreadable():
            return None


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
    ``reported`` daje zmianę klucza dla Zgłoszenia, a ``logged`` klucz dla Logów Centrum, oba bez danych osobowych. Plik
    ``secret`` ma w Historii tylko klucze, bez wartości, i nie da się go cofnąć.
    """

    name: str
    parse: Callable[[bytes | None], T | FieldProblem]
    dump: Callable[[T], str]
    diff: Callable[[T, T], tuple[KeyChange, ...]]
    restore: Callable[[T, tuple[KeyChange, ...]], T]
    reported: Callable[[KeyChange], str]
    default: T
    logged: Callable[[str], str] = str
    secret: bool = False
