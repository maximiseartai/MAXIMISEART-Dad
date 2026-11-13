"""Reguły ilości i Lista Urządzeń (ADR 0033): pliki ``reguly-ilosci.yaml`` i ``lista-urzadzen.yaml`` w ``config``.

Format plików i niezmienniki należą do silnika i jego parsera (``quantity_engine``, ``quantity_rules_file``); tu jest ich
opis dla właściciela Ustawień. Brak pliku to Reguły ilości z Wydania (``DEFAULT_QUANTITY_RULES``). Każdy plik
sprawdza się sam (``parse``): Lista Urządzeń swoje składniki, a Reguły ilości wszystko poza tym, czy składnik reguły jest
na liście. Ten jeden niezmiennik obu plików właściciel sprawdza przy każdym przyjęciu pliku (odczyt zmiany spoza
Centrum, zapis, cofnięcie) tymi samymi dwiema funkcjami: ``rules_problem`` przyjmuje reguły pasujące do bieżącej Listy
Urządzeń (dobrej samej w sobie) albo do ostatniej dobrej, a ``devices_problem`` listę pasującą do reguł, którymi liczą
procesy. Plik, który do drugiego nie pasuje, to złe ustawienie z ostatnią dobrą wartością, więc procesy liczą ostatnią
dobrą parą (``quantity_rules``). Reguły ilości z Wydania (tata nie ma pliku reguł) pasować nie muszą: Wydanie mogło je
zmienić pod Listą Urządzeń taty, więc zła jest wtedy lista, a procesy biorą brakujący składnik z Listy Urządzeń z
Wydania (``completed_devices``), bez zmiany pliku taty.

Wartością pliku są same krotki reguł i składników, bo cofnięcie (``restore``) może złożyć wartość, której ``parse`` nie
przyjmie, a właściciel sprawdza ją dopiero przez ``dump`` i ``parse``. Klucz Historii to ``reguly.<id>`` albo
``urzadzenia.<id>``, a wartość to wpis pliku jako JSON, z którego cofnięcie odtwarza regułę albo składnik.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
import json
from typing import Final, Generic, Protocol, TypeVar

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldProblem, KeyChange, SettingsFile, settings_yaml
from rozliczenia.quantity_engine import (
    Component,
    DeviceList,
    QuantityRule,
    QuantityRules,
    QuantityRulesRefused,
    RulesProblem,
)
from rozliczenia.quantity_rules_file import (
    DEFAULT_QUANTITY_RULES,
    dump_component,
    dump_components,
    dump_rule,
    dump_rule_list,
    parse_component,
    parse_device_list,
    parse_rule,
    parse_rule_list,
)

RULES_FILE: Final = "reguly-ilosci.yaml"
DEVICES_FILE: Final = "lista-urzadzen.yaml"
RULES_SECTION: Final = "reguly"
DEVICES_SECTION: Final = "urzadzenia"

class _Identified(Protocol):
    @property
    def id(self) -> str: ...


_Entry = TypeVar("_Entry", bound=_Identified)


def _document(file: str, data: bytes) -> object | FieldProblem:
    try:
        document: object = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(file))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(file))
    return document


def _problem(file: str, problem: RulesProblem) -> FieldProblem:
    """Problem całego pliku: miejsce w silniku (``reguly[nokia].to``) ma id reguł i klucze z pliku taty, a pole
    ``FieldPath`` przyjmuje tylko znane nazwy pól, więc miejsce zostaje w zdaniu silnika, nie w polu."""

    return FieldProblem(None, messages.quantity_rules_problem(file, problem.message))


@lru_cache(maxsize=4)
def _parse_rules(data: bytes | None) -> tuple[QuantityRule, ...] | FieldProblem:
    """Reguły z bajtów pliku; ``None`` (brak pliku) to reguły z Wydania. Te same bajty dają ten sam wynik, więc odczyt
    przy każdej migawce nie parsuje pliku od nowa."""

    if data is None:
        return DEFAULT_QUANTITY_RULES.rules
    document = _document(RULES_FILE, data)
    if isinstance(document, FieldProblem):
        return document
    rules = parse_rule_list(document)
    return _problem(RULES_FILE, rules) if isinstance(rules, RulesProblem) else rules


@lru_cache(maxsize=4)
def _parse_devices(data: bytes | None) -> tuple[Component, ...] | FieldProblem:
    if data is None:
        return DEFAULT_QUANTITY_RULES.devices.components
    document = _document(DEVICES_FILE, data)
    if isinstance(document, FieldProblem):
        return document
    devices = parse_device_list(document)
    return _problem(DEVICES_FILE, devices) if isinstance(devices, RulesProblem) else devices.components


def _dump(document: dict[str, object]) -> str:
    return settings_yaml(document)


def _entry_json(entry: dict[str, object]) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(", ", ": "))


@dataclass(frozen=True)
class _Entries(Generic[_Entry]):
    """Jak porównać i odtworzyć wpisy jednego pliku: sekcja klucza Historii, wpis jako JSON i z powrotem."""

    section: str
    dumped: Callable[[_Entry], dict[str, object]]
    parsed: Callable[[object], _Entry | RulesProblem]

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
            if isinstance(restored, RulesProblem):
                continue
            position: int = next((index for index, entry in enumerate(entries) if entry.id == identifier), len(kept))
            entries = [*kept[:position], restored, *kept[position:]]
        return tuple(entries)


_RULE_ENTRIES: Final = _Entries[QuantityRule](RULES_SECTION, dump_rule, parse_rule)
_DEVICE_ENTRIES: Final = _Entries[Component](DEVICES_SECTION, dump_component, parse_component)


def _reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu: reguła albo składnik nie mają danych osobowych, więc wprost."""

    return f"{change.key}: {_shown(change.before)} → {_shown(change.after)}"


def _shown(value: str | None) -> str:
    return "nie ustawiono" if value is None else value


RULES: Final = SettingsFile[tuple[QuantityRule, ...]](
    name=RULES_FILE,
    parse=_parse_rules,
    dump=lambda rules: _dump(dump_rule_list(rules)),
    diff=_RULE_ENTRIES.diff,
    restore=_RULE_ENTRIES.restore,
    reported=_reported,
    default=DEFAULT_QUANTITY_RULES.rules,
)
DEVICES: Final = SettingsFile[tuple[Component, ...]](
    name=DEVICES_FILE,
    parse=_parse_devices,
    dump=lambda components: _dump(dump_components(components)),
    diff=_DEVICE_ENTRIES.diff,
    restore=_DEVICE_ENTRIES.restore,
    reported=_reported,
    default=DEFAULT_QUANTITY_RULES.devices.components,
)


def rule_ids(keys: frozenset[str]) -> frozenset[str]:
    """Id reguł z kluczy Historii Ustawień pliku reguł (``reguly.<id>``)."""

    return _RULE_ENTRIES.ids(keys)


def device_ids(keys: frozenset[str]) -> frozenset[str]:
    """Id składników z kluczy Historii Ustawień Listy Urządzeń (``urzadzenia.<id>``)."""

    return _DEVICE_ENTRIES.ids(keys)


def rules_problem(
    rules: tuple[QuantityRule, ...], devices_now: tuple[Component, ...] | None, devices_good: tuple[Component, ...]
) -> FieldProblem | None:
    """Problem Reguł ilości dobrych samych w sobie razem z Listą Urządzeń: ``None``, gdy pasują do bieżącej listy
    (``devices_now``, ``None``: lista zła sama w sobie albo nieczytelna) albo do ostatniej dobrej (``devices_good``)."""

    if devices_now is not None and _refusal(rules, devices_now) is None:
        return None
    problem = _refusal(rules, devices_good)
    return None if problem is None else _problem(RULES_FILE, problem)


def devices_problem(
    devices: tuple[Component, ...], rules: tuple[QuantityRule, ...], devices_good: tuple[Component, ...], *, release: bool
) -> FieldProblem | None:
    """Problem Listy Urządzeń dobrej samej w sobie razem z regułami, którymi liczą procesy (``rules``): składnik, którego
    reguła potrzebuje, a lista go nie ma. Przy regułach z pliku taty nazwany jak w sekcji Urządzenia, która pokazuje
    wtedy ostatnią dobrą listę (``devices_good``; składnik spoza niej ma tylko swój identyfikator). Przy Regułach ilości z
    Wydania (``release``: tata nie ma pliku reguł) nazwany jak na Liście Urządzeń z Wydania, z której procesy go biorą
    (``completed_devices``)."""

    match _refusal(rules, devices):
        case None:
            return None
        case RulesProblem(component=str() as missing) if release:
            return FieldProblem(None, messages.needed_by_release_rules(_name(missing, DEFAULT_QUANTITY_RULES.devices.components)))
        case RulesProblem(component=str() as missing):
            return FieldProblem(None, messages.needed_by_rules(DEVICES_FILE, _name(missing, devices_good)))
        case problem:
            return _problem(DEVICES_FILE, problem)


def completed_devices(devices: tuple[Component, ...], rules: tuple[QuantityRule, ...]) -> tuple[Component, ...]:
    """Lista ``devices`` ze składnikami z Listy Urządzeń z Wydania, których potrzebują reguły ``rules``, a lista ich nie
    ma, na końcu; lista, która do reguł pasuje albo której tak uzupełnić się nie da, zostaje bez zmian. Tak procesy liczą
    Regułami ilości z Wydania, gdy Wydanie zmieniło je pod Listą Urządzeń taty, a tata nie ma pliku reguł."""

    release = {component.id: component for component in DEFAULT_QUANTITY_RULES.devices.components}
    completed = devices
    while (problem := _refusal(rules, completed)) is not None:
        missing = release.get(problem.component or "")
        if missing is None or missing in completed:
            return devices
        completed = (*completed, missing)
    try:
        DeviceList(completed)
    except QuantityRulesRefused:
        return devices
    return completed


def quantity_rules(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> QuantityRules:
    """Reguły ilości, którymi liczą procesy: reguły i lista przyjęte razem. Przyjęcie pilnuje, że do siebie pasują, poza
    Regułami ilości z Wydania (tata bez pliku reguł), którym brakujące składniki daje Lista Urządzeń z Wydania
    (``completed_devices``). Reguły ilości z Wydania z ich Listą Urządzeń zostają tylko bez dobrej pary: listy nie da się
    teraz przeczytać, a ostatnie dobre reguły taty potrzebują składnika, którego lista z Wydania nie ma."""

    try:
        return QuantityRules(rules, DeviceList(completed_devices(devices, rules)))
    except QuantityRulesRefused:
        return DEFAULT_QUANTITY_RULES


def _name(component: str, devices: tuple[Component, ...]) -> str:
    return next((found.spellings[0] for found in devices if found.id == component), component)


def _refusal(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> RulesProblem | None:
    try:
        QuantityRules(rules, DeviceList(devices))
    except QuantityRulesRefused as refused:
        return refused.problem
    return None
