"""Plik Ustawień Centrum w ``config``: jak go przeczytać, zapisać, porównać i cofnąć, ten sam opis dla każdego pliku.

Każdy plik ma jedną regułę ``parse``: sprawdza zapis taty, cofnięcie i plik zmieniony ręcznie, więc zła wartość nie
wchodzi żadną drogą. Brak pliku to wartość domyślna. Pliki, które ma właściciel (``CentrumSettings``), wymienia jego
``_FILES``, a każdy z nich to opis z własnym ``parse``, ``dump``, ``diff`` i ``restore``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Generic, Literal, Protocol, TypeVar

import yaml

T = TypeVar("T")


class _SettingsDumper(yaml.SafeDumper):
    """Zapis YAML plików Ustawień: napis ze znakiem NEL (U+0085) w cudzysłowie podwójnym, w którym stoi on jako ``\\N``,
    bo przy ``allow_unicode`` pakiet yaml pisze go wprost, a przy odczycie czyta jako podział linii ze spacją."""


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"' if "\x85" in value else None)


_SettingsDumper.add_representer(str, _text)


def settings_yaml(document: Mapping[str, object]) -> str:
    """Treść pliku Ustawień w YAML: klucze w kolejności ``document``, polskie litery wprost, bez łamania długich
    linii; każdy napis wraca z pliku bez zmian."""

    return yaml.dump(dict(document), Dumper=_SettingsDumper, allow_unicode=True, sort_keys=False, width=1_000_000)


FieldName = Literal[
    "rejestr_zlecen",
    "folder_okresow",
    "motyw",
    "adres",
    "haslo",
    "wykonawcy",
    "do_rozstrzygniecia",
    "nazwa",
    "loginy",
    "adresy",
    "aktywny",
    "przypomnienia",
    "wlaczone",
    "wlaczone_od",
    "pora_poranna",
    "pora_wieczorna",
    "od",
    "do",
    "pierwsze_przypomnienie",
    "tresc",
    "stopka",
    "autostart",
    "wyjatki",
    "okres",
    "wiersz",
    "tata",
    "odcisk",
    "jesli",
    "skladnik",
    "tekst",
    "slowo",
    "dni",
    "od",
    "to",
    "wpisy",
    "kolumna",
    "wartosc",
    "kolumny",
    "zapisy",
]
"""Znane nazwy pól plików Ustawień: jedyne słowa, z których powstaje ``FieldPath``.

Nazwy stoją w grupach według pliku: ``centrum-ustawienia.yaml`` od ``rejestr_zlecen``, ``skrzynka-raportow.txt`` od
``adres``, ``wykonawcy.yaml`` od ``wykonawcy``, ``przypomnienia.yaml`` od ``wlaczone``, przełącznik startu razem z Windows
(skrót w folderze Autostart) ``autostart``, ``wyjatki-ilosci.yaml`` (różnice Kontroli ilości oznaczone „To był wyjątek”)
od ``wyjatki``, reguła pliku ``reguly-ilosci.yaml`` w edytorze Reguł ilości od ``jesli`` i składnik pliku
``lista-urzadzen.yaml`` w sekcji Urządzenia ``zapisy`` (nazwa składnika to ``nazwa``).
"""


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
    obowiązują wartości domyślne pliku). Sekret, którego treści pamięć nie trzyma, ma tu wartość samej złej treści
    (``SettingsFile.unchecked``; ``None``: treść nie daje wartości)."""

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


RemovedWhat = Literal["worker", "login"]
"""Co zmiana usuwa z Listy Wykonawców: całego Wykonawcę albo tylko jego login."""


@dataclass(frozen=True)
class RemovedLogins:
    """Loginy, które zmiana usuwa z Listy Wykonawców, i czy znika z nimi cały Wykonawca (``what``)."""

    logins: frozenset[str]
    what: RemovedWhat


@dataclass(frozen=True)
class SettingsFile(Generic[T]):
    """Plik Ustawień Centrum w ``config``.

    ``parse`` dostaje bajty pliku (``None``: pliku nie ma) i daje wartość albo pierwszy problem, ``dump`` daje treść
    pliku, ``diff`` klucze, które różnią dwie wartości, a ``restore`` wartość z kluczami ustawionymi na ich wartość
    ``before``. ``restore`` może dać wartość, której ``parse`` nie przyjmie; właściciel sprawdza ją jak każdą zmianę.
    ``reported`` daje zmianę klucza dla Zgłoszenia, a ``logged`` klucz dla Logów Centrum, oba bez danych osobowych. Plik
    ``secret`` ma w Historii tylko klucze, bez wartości, i nie da się go cofnąć. Ostatniej dobrej treści sekretu nikt nie
    pamięta, więc ``unchecked`` daje wartość jego treści bez reguł ``parse`` (``None``: treść nie daje wartości): zapis
    taty na złej treści zaczyna od niej, a ``parse`` zapisu odrzuca to, czego zapis nie naprawił. ``removed_logins``
    daje loginy, które zmiana wartości usuwa z Listy Wykonawców (``None``: żadnego): właściciel zapisuje zmianę taty
    dopiero, gdy żaden z nich nie występuje w okresie (ADR 0032).
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
    unchecked: Callable[[bytes | None], T | None] | None = None
    removed_logins: Callable[[T, T], RemovedLogins | None] | None = None


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


_Entry = TypeVar("_Entry", bound=_Identified)


@dataclass(frozen=True)
class EntriesById(Generic[_Entry]):
    """Jak porównać i odtworzyć wpisy pliku, który jest listą wpisów z ``id``: klucz Historii ``<sekcja>.<id>``, a wartość
    to wpis jako JSON (``dumped``) i z powrotem (``parsed``; ``None``: wpisu nie da się odczytać)."""

    section: str
    dumped: Callable[[_Entry], dict[str, object]]
    parsed: Callable[[object], _Entry | None]

    def diff(self, before: tuple[_Entry, ...], after: tuple[_Entry, ...]) -> tuple[KeyChange, ...]:
        old: dict[str, str] = {entry.id: _entry_json(self.dumped(entry)) for entry in before}
        new: dict[str, str] = {entry.id: _entry_json(self.dumped(entry)) for entry in after}
        return tuple(
            KeyChange(f"{self.section}.{identifier}", old.get(identifier), new.get(identifier))
            for identifier in dict.fromkeys((*old, *new))
            if old.get(identifier) != new.get(identifier)
        )

    def ids(self, keys: frozenset[str]) -> frozenset[str]:
        """Id wpisów z kluczy Historii Ustawień tej sekcji (``<sekcja>.<id>``)."""

        return frozenset(key.removeprefix(f"{self.section}.") for key in keys if key.startswith(f"{self.section}."))

    def restore(self, current: tuple[_Entry, ...], changes: tuple[KeyChange, ...]) -> tuple[_Entry, ...]:
        """``current`` z każdym wpisem ``changes`` jak przed zmianą: usunięty wraca na koniec, dodany znika; klucz innej
        sekcji albo wpis, którego nie da się odczytać, zostaje bez zmian."""

        entries = list(current)
        for change in changes:
            section, _, identifier = change.key.partition(".")
            if section != self.section:
                continue
            kept: list[_Entry] = [entry for entry in entries if entry.id != identifier]
            if change.before is None:
                entries = kept
                continue
            try:
                restored = self.parsed(json.loads(change.before))
            except ValueError:
                continue
            if restored is None:
                continue
            position: int = next((index for index, entry in enumerate(entries) if entry.id == identifier), len(kept))
            entries = [*kept[:position], restored, *kept[position:]]
        return tuple(entries)


def _entry_json(entry: dict[str, object]) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(", ", ": "))
