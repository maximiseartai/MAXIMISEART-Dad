from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from typing import Final

import yaml

from rozliczenia.centrum.rule_sentences import plain_sentence, rule_sentence
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
    return FieldProblem(None, messages.quantity_rules_problem(file, problem.message))


@lru_cache(maxsize=4)
def _parse_rules(data: bytes | None) -> tuple[QuantityRule, ...] | FieldProblem:
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


def _dump(document: dict[str, object]) -> bytes:
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
    return _RULE_ENTRIES.ids(keys)


def device_ids(keys: frozenset[str]) -> frozenset[str]:
    return _DEVICE_ENTRIES.ids(keys)


def rules_problem(
    rules: tuple[QuantityRule, ...], devices_now: tuple[Component, ...] | None, devices_good: tuple[Component, ...]
) -> FieldProblem | None:
    if devices_now is not None and _refusal(rules, devices_now) is None:
        return None
    problem = _refusal(rules, devices_good)
    return None if problem is None else _problem(RULES_FILE, problem)


def devices_problem(
    devices: tuple[Component, ...], rules: tuple[QuantityRule, ...], devices_good: tuple[Component, ...], *, release: bool
) -> FieldProblem | None:
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
    completion = _completion(devices, rules)
    if completion is None or not completion.absent:
        return None
    spelling, owner = _taken(completion, devices)
    return FieldProblem(None, messages.release_component_taken(spelling, owner.spellings[0], _how(spelling, owner, completion)))


DevicesEdit = Callable[[tuple[Component, ...]], tuple[Component, ...] | FieldProblem]

ColumnNames = Callable[[], Mapping[str, str]]


@dataclass(frozen=True)
class TakenSpelling(FieldProblem):
    spelling: str


@dataclass(frozen=True)
class UnlistedComponent(FieldProblem):
    component: str


def dad_devices_edit(edit: DevicesEdit, rules: tuple[QuantityRule, ...], names: ColumnNames, *, release: bool) -> DevicesEdit:
    def checked_edit(current: tuple[Component, ...]) -> tuple[Component, ...] | FieldProblem:
        completion = _completion(current, rules) if release else None
        start = current if completion is None else completion.devices
        changed = edit(start)
        if isinstance(changed, FieldProblem):
            return changed
        problem = _list_problem(start, changed)
        if problem is not None:
            return problem
        if completion is None:
            final, counted = changed, rules
        else:
            untouched = frozenset(component.id for component in completion.joined if component in changed)
            final = _completed_devices(tuple(component for component in changed if component.id not in untouched), rules)
            counted = completion.rules
        lost = _lost_component(start, changed, final, counted, names, release=completion is not None)
        return final if lost is None else lost

    return checked_edit


def dad_rules_problem(
    rules: tuple[QuantityRule, ...], devices: tuple[Component, ...], names: ColumnNames, unlisted: Callable[[str], str]
) -> FieldProblem | None:
    listed = DeviceList(devices)
    for rule in rules:
        problem = _refusal((rule,), devices)
        if problem is not None and problem.component is not None:
            name = unlisted(problem.component)
            sentence = plain_sentence(rule_sentence(rule, listed, names(), unlisted={problem.component: name}))
            return UnlistedComponent(None, messages.rule_needs_component(name, sentence), problem.component)
    problem = _refusal(rules, devices)
    return None if problem is None else FieldProblem(None, problem.message)


def listed_name(component: str, changes: Iterable[KeyChange]) -> str:
    key = f"{DEVICES_SECTION}.{component}"
    for change in changes:
        for value in (change.after, change.before) if change.key == key else ():
            try:
                found = None if value is None else _component(json.loads(value))
            except ValueError:
                continue
            if found is not None:
                return found.spellings[0]
    return _name(component, DEFAULT_QUANTITY_RULES.devices.components)


def _list_problem(before: tuple[Component, ...], after: tuple[Component, ...]) -> FieldProblem | None:
    taken = _taken_spelling(before, after)
    if taken is not None:
        return taken
    try:
        DeviceList(after)
    except QuantityRulesRefused as refused:
        return FieldProblem(None, refused.problem.message)
    return None


def _lost_component(
    before: tuple[Component, ...],
    after: tuple[Component, ...],
    final: tuple[Component, ...],
    rules: tuple[QuantityRule, ...],
    names: ColumnNames,
    *,
    release: bool,
) -> FieldProblem | None:
    kept = {component.id: component for component in before}
    supplied = {component.id: component for component in final}
    listed = DeviceList(before)
    for rule in rules:
        problem = _refusal((rule,), after)
        if problem is None or problem.component is None:
            continue
        if release and supplied.get(problem.component) != kept.get(problem.component):
            continue
        sentence = plain_sentence(rule_sentence(rule, listed, names()))
        return FieldProblem(None, messages.component_used_by_rule(_name(problem.component, before), sentence))
    return None


def _taken_spelling(before: tuple[Component, ...], after: tuple[Component, ...]) -> TakenSpelling | None:
    kept = frozenset(before)
    for component in sorted(after, key=lambda component: component in kept):
        for spelling in component.spellings:
            owner = next((other for other in after if other.id != component.id and spelling in other.spellings), None)
            if owner is not None:
                return TakenSpelling(None, messages.spelling_taken(spelling, owner.spellings[0]), spelling)
    return None


def devices_for_dad_rules(
    devices: tuple[Component, ...], rules: tuple[QuantityRule, ...], counted: tuple[QuantityRule, ...]
) -> tuple[Component, ...] | FieldProblem:
    completion = _completion(devices, rules)
    if completion is None:
        return devices
    if not completion.absent:
        return completion.devices
    spelling, owner = _taken(completion, devices)
    now = _completion(devices, counted)
    how = _how(spelling, owner, completion if now is None else now)
    return FieldProblem(None, messages.rules_wait_for_release_component(spelling, owner.spellings[0], how))


def _completed_devices(devices: tuple[Component, ...], rules: tuple[QuantityRule, ...]) -> tuple[Component, ...]:
    completion = _completion(devices, rules)
    return devices if completion is None else completion.devices


def quantity_rules(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> QuantityRules:
    completion = _completion(devices, rules)
    if completion is None:
        return DEFAULT_QUANTITY_RULES
    return QuantityRules(completion.rules, DeviceList(completion.devices))


@dataclass(frozen=True)
class _Completion:
    devices: tuple[Component, ...]
    rules: tuple[QuantityRule, ...]
    joined: tuple[Component, ...]
    absent: tuple[Component, ...]


def _completion(devices: tuple[Component, ...], rules: tuple[QuantityRule, ...]) -> _Completion | None:
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


def _taken(completion: _Completion, devices: tuple[Component, ...]) -> tuple[str, Component]:
    spelling = completion.absent[0].spellings[0]
    return spelling, next(component for component in devices if spelling in component.spellings)


def _how(spelling: str, owner: Component, completion: _Completion) -> messages.TakenAction:
    if spelling in owner.spellings[1:]:
        return "zapis"
    others = tuple(component for component in completion.devices if component.id != owner.id)
    if len(owner.spellings) == 1 and _refusal(completion.rules, others) is None:
        return "skladnik"
    return "nazwa"


def _name(component: str, devices: tuple[Component, ...]) -> str:
    return next((found.spellings[0] for found in devices if found.id == component), component)


def _refusal(rules: tuple[QuantityRule, ...], devices: tuple[Component, ...]) -> RulesProblem | None:
    try:
        QuantityRules(rules, DeviceList(devices))
    except QuantityRulesRefused as refused:
        return refused.problem
    return None
