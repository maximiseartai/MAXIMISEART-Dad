from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Generic, Literal, Protocol, TypeVar, final

import yaml

T = TypeVar("T")


class _SettingsDumper(yaml.SafeDumper):
    ...


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"' if "\x85" in value else None)


_SettingsDumper.add_representer(str, _text)


def settings_yaml(document: Mapping[str, object]) -> bytes:
    text = yaml.dump(dict(document), Dumper=_SettingsDumper, allow_unicode=True, sort_keys=False, width=1_000_000)
    return text.encode("utf-8")


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
    "przedzialy",
    "kwota",
    "wypelnienia",
    "temat",
]


@dataclass(frozen=True, init=False)
class FieldPath:
    text: str

    def __init__(self, first: FieldName, *rest: FieldName | int) -> None:
        parts = (f"[{part}]" if isinstance(part, int) else f".{part}" for part in rest)
        object.__setattr__(self, "text", first + "".join(parts))


@dataclass(frozen=True)
class FieldProblem:
    field: FieldPath | None
    sentence: str

    @property
    def place(self) -> str | None:
        return None if self.field is None else self.field.text


@dataclass(frozen=True)
class Good(Generic[T]):
    value: T


@dataclass(frozen=True)
class Bad(Generic[T]):
    problem: FieldProblem
    usable: T | None


@final
@dataclass(frozen=True)
class Unreadable:
    name: str


Read = Good[T] | Bad[T]


def usable(read: Read[T]) -> T | None:
    match read:
        case Good(value=value):
            return value
        case Bad(usable=value):
            return value


@dataclass(frozen=True)
class KeyChange:
    key: str
    before: str | None
    after: str | None


RemovedWhat = Literal["worker", "login"]


@dataclass(frozen=True)
class RemovedLogins:
    logins: frozenset[str]
    what: RemovedWhat


@dataclass(frozen=True)
class SettingsFile(Generic[T]):
    name: str
    parse: Callable[[bytes | None], T | FieldProblem]
    dump: Callable[[T], bytes]
    diff: Callable[[T, T], tuple[KeyChange, ...]]
    restore: Callable[[T, tuple[KeyChange, ...]], T | FieldProblem]
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
        return frozenset(key.removeprefix(f"{self.section}.") for key in keys if key.startswith(f"{self.section}."))

    def restore(self, current: tuple[_Entry, ...], changes: tuple[KeyChange, ...]) -> tuple[_Entry, ...]:
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
