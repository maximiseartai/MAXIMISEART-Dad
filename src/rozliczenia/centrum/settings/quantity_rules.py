"""Reguły ilości i Lista Urządzeń (ADR 0033): pliki ``reguly-ilosci.yaml`` i ``lista-urzadzen.yaml`` w ``config``.

Format plików i niezmienniki należą do silnika i jego parsera (``quantity_engine``, ``quantity_rules_file``); tu jest ich
opis dla właściciela Ustawień. Brak pliku to Reguły ilości z Wydania (``DEFAULT_QUANTITY_RULES``). Każdy plik
sprawdza się sam (``parse``): Lista Urządzeń swoje składniki, a Reguły ilości wszystko poza tym, czy składnik reguły jest
na liście. Ten jeden niezmiennik obu plików właściciel sprawdza przy każdym przyjęciu pliku (odczyt zmiany spoza
Centrum, zapis, cofnięcie) tymi samymi dwiema funkcjami: ``rules_problem`` przyjmuje reguły pasujące do bieżącej Listy
Urządzeń (dobrej samej w sobie) albo do ostatniej dobrej, a ``devices_problem`` listę pasującą do reguł, którymi liczą
procesy. Plik, który do drugiego nie pasuje, to złe ustawienie z ostatnią dobrą wartością, więc procesy liczą ostatnią
dobrą parą (``quantity_rules``).

Wartością pliku są same krotki reguł i składników, bo cofnięcie (``restore``) może złożyć wartość, której ``parse`` nie
przyjmie, a właściciel sprawdza ją dopiero przez ``dump`` i ``parse``. Klucz Historii to ``reguly.<id>`` albo
``urzadzenia.<id>``, a wartość to wpis pliku jako JSON, z którego cofnięcie odtwarza regułę albo składnik.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import EntriesById, FieldProblem, KeyChange, SettingsFile, settings_yaml
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


def _rule(entry: object) -> QuantityRule | None:
    rule = parse_rule(entry)
    return None if isinstance(rule, RulesProblem) else rule


def _component(entry: object) -> Component | None:
    component = parse_component(entry)
    return None if isinstance(component, RulesProblem) else component


_RULE_ENTRIES: Final = EntriesById[QuantityRule](RULES_SECTION, dump_rule, _rule)
_DEVICE_ENTRIES: Final = EntriesById[Component](DEVICES_SECTION, dump_component, _component)


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

    return frozenset(key.removeprefix(f"{RULES_SECTION}.") for key in keys if key.startswith(f"{RULES_SECTION}."))


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
    devices: tuple[Component, ...], rules: tuple[QuantityRule, ...], devices_good: tuple[Component, ...]
) -> FieldProblem | None:
    """Problem Listy Urządzeń dobrej samej w sobie razem z regułami, którymi liczą procesy (``rules``): składnik, którego
    reguła potrzebuje, a lista go nie ma, nazwany jak w sekcji Urządzenia, która pokazuje wtedy ostatnią dobrą listę
    (``devices_good``); składnik spoza niej ma tylko swój identyfikator."""

    match _refusal(rules, devices):
        case None:
            return None
        case RulesProblem(component=str() as missing):
            names = {component.id: component.spellings[0] for component in devices_good}
            return FieldProblem(None, messages.needed_by_rules(DEVICES_FILE, names.get(missing, missing)))
        case problem:
            return _problem(DEVICES_FILE, problem)


def quantity_rules(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> QuantityRules:
    """Reguły ilości, którymi liczą procesy: reguły i lista przyjęte razem. Przyjęcie pilnuje, że do siebie pasują, więc
    Reguły ilości z Wydania z ich Listą Urządzeń zostają tylko bez dobrej pary: Wydanie zmieniło Reguły ilości z Wydania
    pod Listą Urządzeń taty, a pliku reguł tata nie ma, albo listy nie da się teraz przeczytać, a ostatnie dobre reguły
    nie pasują do listy z Wydania."""

    try:
        return QuantityRules(rules, DeviceList(devices))
    except QuantityRulesRefused:
        return DEFAULT_QUANTITY_RULES


def _refusal(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> RulesProblem | None:
    try:
        QuantityRules(rules, DeviceList(devices))
    except QuantityRulesRefused as refused:
        return refused.problem
    return None
