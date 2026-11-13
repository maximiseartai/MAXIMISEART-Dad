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
Wydania (``completed_devices``), bez zmiany pliku taty. Zapis taty wygrywa: składnik z Wydania dochodzi tylko z zapisami,
których lista taty nie ma, a składnik, którego każdy zapis ma lista taty, nie dochodzi wcale. Lista bez takiego składnika
nie jest zła, a reguły liczą tak, jakby żadne zlecenie go nie miało (``without_components``); sekcja Urządzenia mówi o nim
zdaniem (``taken_problem``).

Wartością pliku są same krotki reguł i składników, bo cofnięcie (``restore``) może złożyć wartość, której ``parse`` nie
przyjmie, a właściciel sprawdza ją dopiero przez ``dump`` i ``parse``. Klucz Historii to ``reguly.<id>`` albo
``urzadzenia.<id>``, a wartość to wpis pliku jako JSON, z którego cofnięcie odtwarza regułę albo składnik.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    without_components,
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
    Wydania (``release``: tata nie ma pliku reguł) tylko składnik, który procesy biorą z Listy Urządzeń z Wydania
    (``completed_devices``), nazwany jak w sekcji: jego pierwszym zapisem spoza listy. Składnik z Wydania, którego każdy
    zapis ma lista, problemem listy nie jest (``taken_problem``)."""

    problem = _refusal(rules, devices)
    if problem is None:
        return None
    completion = _completion(devices, rules) if release else None
    if completion is not None:
        joined = completion.joined
        return FieldProblem(None, messages.needed_by_release_rules(joined[0].spellings[0])) if joined else None
    if problem.component is not None:
        return FieldProblem(None, messages.needed_by_rules(DEVICES_FILE, _name(problem.component, devices_good)))
    return _problem(DEVICES_FILE, problem)


def taken_problem(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> FieldProblem | None:
    """Zdanie sekcji Urządzenia o składniku z Listy Urządzeń z Wydania, którego potrzebują reguły ``rules``, a którego
    każdy zapis ma lista ``devices``, więc procesy liczą bez niego (``None``: takiego składnika nie ma). Zdanie mówi, jak
    zwolnić jego pierwszy zapis: usunąć go ze składnika z innymi zapisami, usunąć składnik, którego nie potrzebuje żadna
    reguła, którą liczą procesy, albo zmienić nazwę składnika, którego taka reguła potrzebuje."""

    completion = _completion(devices, rules)
    if completion is None or not completion.absent:
        return None
    spelling = completion.absent[0].spellings[0]
    owner = next(component for component in devices if spelling in component.spellings)
    how: messages.TakenAction
    if len(owner.spellings) > 1:
        how = "zapis"
    elif _refusal(completion.rules, tuple(component for component in completion.devices if component.id != owner.id)) is None:
        how = "skladnik"
    else:
        how = "nazwa"
    return FieldProblem(None, messages.release_component_taken(spelling, owner.spellings[0], how))


def completed_devices(devices: tuple[Component, ...], rules: tuple[QuantityRule, ...]) -> tuple[Component, ...]:
    """Lista ``devices`` ze składnikami z Listy Urządzeń z Wydania, których potrzebują reguły ``rules``, a lista ich nie
    ma, na końcu, każdy tylko z zapisami, których lista nie ma (zapis taty wygrywa); składnik bez takiego zapisu nie
    dochodzi. Lista, której nie da się tak uzupełnić, zostaje bez zmian. Tak procesy liczą Regułami ilości z Wydania, gdy
    Wydanie zmieniło je pod Listą Urządzeń taty, a tata nie ma pliku reguł."""

    completion = _completion(devices, rules)
    return devices if completion is None else completion.devices


def quantity_rules(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> QuantityRules:
    """Reguły ilości, którymi liczą procesy: reguły i lista przyjęte razem. Przyjęcie pilnuje, że do siebie pasują, poza
    Regułami ilości z Wydania (tata bez pliku reguł), którym brakujące składniki daje Lista Urządzeń z Wydania
    (``completed_devices``), a bez składnika, którego każdy zapis ma lista taty, liczą tak, jakby żadne zlecenie go nie
    miało. Reguły ilości z Wydania z ich Listą Urządzeń zostają tylko bez dobrej pary: listy nie da się teraz przeczytać,
    a ostatnie dobre reguły taty potrzebują składnika, którego lista z Wydania nie ma."""

    completion = _completion(devices, rules)
    if completion is None:
        return DEFAULT_QUANTITY_RULES
    try:
        return QuantityRules(completion.rules, DeviceList(completion.devices))
    except QuantityRulesRefused:
        return DEFAULT_QUANTITY_RULES


@dataclass(frozen=True)
class _Completion:
    """Lista ``devices`` uzupełniona o składniki z Listy Urządzeń z Wydania z zapisami spoza listy (``joined``) i reguły
    ``rules`` bez składników z Wydania, których każdy zapis ma lista (``absent``)."""

    devices: tuple[Component, ...]
    rules: tuple[QuantityRule, ...]
    joined: tuple[Component, ...]
    absent: tuple[Component, ...]


def _completion(devices: tuple[Component, ...], rules: tuple[QuantityRule, ...]) -> _Completion | None:
    """Uzupełnienie listy ``devices`` do reguł ``rules`` (``completed_devices``); ``None``: reguła potrzebuje składnika,
    którego nie ma ani na liście, ani na Liście Urządzeń z Wydania, albo reguły bez składnika dalej go potrzebują."""

    release = {component.id: component for component in DEFAULT_QUANTITY_RULES.devices.components}
    taken = {spelling for component in devices for spelling in component.spellings}
    joined: dict[str, Component] = {}
    absent: dict[str, Component] = {}
    while (problem := _refusal(without_components(rules, frozenset(absent)), (*devices, *joined.values()))) is not None:
        missing = release.get(problem.component or "")
        if missing is None or missing.id in absent:
            return None
        free = tuple(spelling for spelling in missing.spellings if spelling not in taken)
        if free:
            joined[missing.id] = replace(missing, spellings=free)
        else:
            absent[missing.id] = missing
    return _Completion(
        (*devices, *joined.values()), without_components(rules, frozenset(absent)), tuple(joined.values()), tuple(absent.values())
    )


def _name(component: str, devices: tuple[Component, ...]) -> str:
    return next((found.spellings[0] for found in devices if found.id == component), component)


def _refusal(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> RulesProblem | None:
    try:
        QuantityRules(rules, DeviceList(devices))
    except QuantityRulesRefused as refused:
        return refused.problem
    return None
