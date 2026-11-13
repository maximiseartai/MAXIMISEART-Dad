"""Pliki Reguł ilości i Listy Urządzeń (ADR 0033) ↔ typy silnika ``quantity_engine``.

Dwa dokumenty YAML ze ``schema_version: 1``: ``reguly-ilosci.yaml`` (klucz ``reguly``) i ``lista-urzadzen.yaml``
(klucz ``urzadzenia``). ``parse_device_list`` i ``parse_quantity_rules`` biorą dokument po ``yaml.safe_load`` i dają typ
albo pierwszy problem z polem (``RulesProblem``): nieznany klucz, brak klucza, zły rodzaj wartości i każdy niezmiennik
typów silnika. Reguły sprawdzają się z Listą Urządzeń, do której się odwołują. ``dump_*`` daje dokument, który
``parse_*`` czyta z powrotem w ten sam typ.

``DEFAULT_QUANTITY_RULES`` to Reguły ilości z Wydania: pliki ``reguly_ilosci_domyslne.yaml`` i
``lista_urzadzen_domyslna.yaml`` obok tego modułu, czytane tym samym parserem.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import time
from enum import StrEnum
from importlib import resources
import re
from typing import Final, TypeVar

import yaml

from .quantity_engine import (
    ActivitiesContain,
    Component,
    Condition,
    ContainsComponent,
    ContractFirstWord,
    DeviceGroup,
    DeviceList,
    DevicesText,
    Fill,
    HasGroup,
    LeaveEmpty,
    Multiplier,
    QuantityRule,
    QuantityRules,
    QuantityRulesRefused,
    RulesProblem,
    Scope,
    StartedAt,
    TextMode,
    Write,
    WriteNothing,
)

SCHEMA_VERSION: Final = 1
_HOUR = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
_E = TypeVar("_E", bound=StrEnum)


class _Malformed(Exception):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(path, message)
        self.problem = RulesProblem(path, message)


def parse_device_list(document: object) -> DeviceList | RulesProblem:
    """Lista Urządzeń z dokumentu pliku ``lista-urzadzen.yaml`` albo pierwszy problem."""

    try:
        body = _document(document, "urzadzenia")
        return DeviceList(tuple(_component(entry, f"urzadzenia[{index}]") for index, entry in enumerate(_list(body, "urzadzenia"))))
    except _Malformed as malformed:
        return malformed.problem
    except QuantityRulesRefused as refused:
        return refused.problem


def parse_quantity_rules(document: object, devices: DeviceList) -> QuantityRules | RulesProblem:
    """Reguły ilości z dokumentu pliku ``reguly-ilosci.yaml`` z Listą Urządzeń ``devices`` albo pierwszy problem."""

    try:
        body = _document(document, "reguly")
        rules = tuple(_rule(entry, f"reguly[{index}]") for index, entry in enumerate(_list(body, "reguly")))
        return QuantityRules(rules, devices)
    except _Malformed as malformed:
        return malformed.problem
    except QuantityRulesRefused as refused:
        return refused.problem


def dump_device_list(devices: DeviceList) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "urzadzenia": [_dump_component(component) for component in devices.components]}


def dump_quantity_rules(rules: QuantityRules) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "reguly": [_dump_rule(rule) for rule in rules.rules]}


def _document(document: object, key: str) -> object:
    entries = _mapping(document, "", required={"schema_version", key})
    if entries["schema_version"] != SCHEMA_VERSION or isinstance(entries["schema_version"], bool):
        raise _Malformed("schema_version", f"Plik ma inną wersję zapisu niż {SCHEMA_VERSION}.")
    return entries[key]


def _component(entry: object, path: str) -> Component:
    fields = _mapping(entry, path, required={"id", "zapisy"}, optional={"grupa"})
    identifier = _text(fields["id"], f"{path}.id")
    path = f"urzadzenia[{identifier}]"
    spellings = tuple(_text(spelling, f"{path}.zapisy") for spelling in _list(fields["zapisy"], f"{path}.zapisy"))
    group = _choice(fields["grupa"], DeviceGroup, f"{path}.grupa") if "grupa" in fields else None
    return Component(identifier, spellings, group)


def _rule(entry: object, path: str) -> QuantityRule:
    fields = _mapping(entry, path, required={"id", "zakres", "jesli", "to"})
    identifier = _text(fields["id"], f"{path}.id")
    path = f"reguly[{identifier}]"
    conditions = tuple(
        _condition(condition, f"{path}.jesli[{index}]") for index, condition in enumerate(_list(fields["jesli"], f"{path}.jesli"))
    )
    return QuantityRule(identifier, conditions, _choice(fields["zakres"], Scope, f"{path}.zakres"), _action(fields["to"], f"{path}.to"))


def _condition(entry: object, path: str) -> Condition:
    kind = _kind(entry, path, tuple(_CONDITIONS))
    fields_of, build = _CONDITIONS[kind]
    required, optional = fields_of
    fields = _mapping(entry, path, required={"rodzaj", *required}, optional={"zaprzeczony", *optional})
    negated = _flag(fields["zaprzeczony"], f"{path}.zaprzeczony") if "zaprzeczony" in fields else False
    return build(fields, path, negated)


def _devices_text(fields: Mapping[str, object], path: str, negated: bool) -> Condition:
    mode = _choice(fields["tryb"], TextMode, f"{path}.tryb")
    if mode is TextMode.EMPTY:
        if "tekst" in fields:
            raise _Malformed(f"{path}.tekst", "Warunek „URZĄDZENIA są puste” nie ma tekstu.")
        return DevicesText(mode, "", negated)
    if "tekst" not in fields:
        raise _Malformed(f"{path}.tekst", "Brakuje tekstu warunku.")
    return DevicesText(mode, _text(fields["tekst"], f"{path}.tekst"), negated)


def _started_at(fields: Mapping[str, object], path: str, negated: bool) -> Condition:
    days = frozenset(_day(day, f"{path}.dni") for day in _list(fields["dni"], f"{path}.dni"))
    hour = _HOUR.fullmatch(fields["od"]) if isinstance(fields["od"], str) else None
    if hour is None:
        raise _Malformed(f"{path}.od", "Godzinę wpisz w cudzysłowie jako „GG:MM”, np. „17:00”.")
    return StartedAt(days, time(int(hour[1]), int(hour[2])), negated)


_ConditionBuilder = Callable[[Mapping[str, object], str, bool], Condition]
_CONDITIONS: Final[Mapping[str, tuple[tuple[frozenset[str], frozenset[str]], _ConditionBuilder]]] = {
    "skladnik": (
        (frozenset({"skladnik"}), frozenset()),
        lambda fields, path, negated: ContainsComponent(_text(fields["skladnik"], f"{path}.skladnik"), negated),
    ),
    "urzadzenia": ((frozenset({"tryb"}), frozenset({"tekst"})), _devices_text),
    "czynnosci": (
        (frozenset({"tekst"}), frozenset()),
        lambda fields, path, negated: ActivitiesContain(_text(fields["tekst"], f"{path}.tekst"), negated),
    ),
    "umowa": (
        (frozenset({"slowo"}), frozenset()),
        lambda fields, path, negated: ContractFirstWord(_text(fields["slowo"], f"{path}.slowo"), negated),
    ),
    "data": ((frozenset({"dni", "od"}), frozenset()), _started_at),
    "grupa": (
        (frozenset({"grupa"}), frozenset()),
        lambda fields, path, negated: HasGroup(_choice(fields["grupa"], DeviceGroup, f"{path}.grupa"), negated),
    ),
}


def _action(entry: object, path: str) -> Fill | WriteNothing | LeaveEmpty:
    kind = _kind(entry, path, ("wpisz", "nic", "pusta"))
    if kind == "nic":
        _mapping(entry, path, required={"rodzaj"})
        return WriteNothing()
    if kind == "pusta":
        fields = _mapping(entry, path, required={"rodzaj", "kolumny"})
        return LeaveEmpty(tuple(_text(column, f"{path}.kolumny") for column in _list(fields["kolumny"], f"{path}.kolumny")))
    fields = _mapping(entry, path, required={"rodzaj", "wpisy"})
    return Fill(tuple(_write(write, f"{path}.wpisy[{index}]") for index, write in enumerate(_list(fields["wpisy"], f"{path}.wpisy"))))


def _write(entry: object, path: str) -> Write:
    fields = _mapping(entry, path, required={"kolumna", "wartosc", "razy"}, optional={"skladnik"})
    value = fields["wartosc"]
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Malformed(f"{path}.wartosc", "Wartość musi być liczbą całkowitą.")
    component = _text(fields["skladnik"], f"{path}.skladnik") if "skladnik" in fields else None
    return Write(_text(fields["kolumna"], f"{path}.kolumna"), value, _choice(fields["razy"], Multiplier, f"{path}.razy"), component)


def _dump_component(component: Component) -> dict[str, object]:
    dumped: dict[str, object] = {"id": component.id, "zapisy": list(component.spellings)}
    if component.group is not None:
        dumped["grupa"] = str(component.group)
    return dumped


def _dump_rule(rule: QuantityRule) -> dict[str, object]:
    return {
        "id": rule.id,
        "zakres": str(rule.scope),
        "jesli": [_dump_condition(condition) for condition in rule.conditions],
        "to": _dump_action(rule.action),
    }


def _dump_condition(condition: Condition) -> dict[str, object]:
    dumped: dict[str, object]
    match condition:
        case ContainsComponent(component=component):
            dumped = {"rodzaj": "skladnik", "skladnik": component}
        case DevicesText(mode=mode, text=text):
            dumped = {"rodzaj": "urzadzenia", "tryb": str(mode)}
            if mode is not TextMode.EMPTY:
                dumped["tekst"] = text
        case ActivitiesContain(text=text):
            dumped = {"rodzaj": "czynnosci", "tekst": text}
        case ContractFirstWord(word=word):
            dumped = {"rodzaj": "umowa", "slowo": word}
        case StartedAt(days=days, since=since):
            dumped = {"rodzaj": "data", "dni": sorted(days), "od": f"{since:%H:%M}"}
        case HasGroup(group=group):
            dumped = {"rodzaj": "grupa", "grupa": str(group)}
    if condition.negated:
        dumped["zaprzeczony"] = True
    return dumped


def _dump_action(action: Fill | WriteNothing | LeaveEmpty) -> dict[str, object]:
    match action:
        case Fill(writes=writes):
            return {"rodzaj": "wpisz", "wpisy": [_dump_write(write) for write in writes]}
        case WriteNothing():
            return {"rodzaj": "nic"}
        case LeaveEmpty(columns=columns):
            return {"rodzaj": "pusta", "kolumny": list(columns)}


def _dump_write(write: Write) -> dict[str, object]:
    dumped: dict[str, object] = {"kolumna": write.column, "wartosc": write.value, "razy": str(write.multiplier)}
    if write.component is not None:
        dumped["skladnik"] = write.component
    return dumped


def _mapping(entry: object, path: str, *, required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> dict[str, object]:
    where = path or "plik"
    if not isinstance(entry, dict):
        raise _Malformed(where, "Tu powinny być pola „klucz: wartość”.")
    for key in entry:
        if key not in required and key not in optional:
            raise _Malformed(f"{path}.{key}" if path else str(key), f"Nieznane pole „{key}”.")
    for key in sorted(required):
        if key not in entry:
            raise _Malformed(f"{path}.{key}" if path else key, f"Brakuje pola „{key}”.")
    return {str(key): value for key, value in entry.items()}


def _kind(entry: object, path: str, kinds: tuple[str, ...]) -> str:
    kind = entry.get("rodzaj") if isinstance(entry, dict) else None
    if kind not in kinds:
        raise _Malformed(f"{path}.rodzaj", f"Rodzaj musi być jednym z: {', '.join(kinds)}.")
    assert isinstance(kind, str)
    return kind


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise _Malformed(path, "Tu powinna być lista.")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise _Malformed(path, "Tu powinien być tekst.")
    return value


def _flag(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise _Malformed(path, "Tu powinno być true albo false.")
    return value


def _day(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 6:
        raise _Malformed(path, "Dzień tygodnia to liczba od 0 (poniedziałek) do 6 (niedziela).")
    return value


def _choice(value: object, kind: type[_E], path: str) -> _E:
    for member in kind:
        if value == member.value:
            return member
    raise _Malformed(path, f"Wartość musi być jedną z: {', '.join(member.value for member in kind)}.")


def _default() -> QuantityRules:
    package = resources.files(__package__)
    devices = parse_device_list(yaml.safe_load(package.joinpath("lista_urzadzen_domyslna.yaml").read_text(encoding="utf-8")))
    assert isinstance(devices, DeviceList), devices
    rules = parse_quantity_rules(yaml.safe_load(package.joinpath("reguly_ilosci_domyslne.yaml").read_text(encoding="utf-8")), devices)
    assert isinstance(rules, QuantityRules), rules
    return rules


DEFAULT_QUANTITY_RULES: Final = _default()
"""Reguły ilości z Wydania: dzisiejsze reguły z kodu jako dane (ADR 0033, „Start bez zmiany wyniku”)."""
