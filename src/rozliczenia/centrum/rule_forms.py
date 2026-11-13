"""Edytor Reguł ilości (ADR 0033): formularz reguły z kontraktu ↔ reguła silnika ``QuantityRule`` i zmiana listy reguł.

Formularz niczego nie sprawdza sam. Regułę z niego sprawdza silnik razem z resztą reguł i Listą Urządzeń
(``QuantityRules``), a ``checked`` zamienia jego problem na odmowę z polem formularza (``FieldPath`` względem reguły:
``to``, ``jesli[0].tekst``, ``to.wpisy[1].kolumna``). Miejsce problemu silnik daje swoim tekstem
(``reguly[<id>].jesli[0].tekst``): ``checked`` zdejmuje przedrostek reguły o znanym id i przyjmuje tylko formy z listy
(``_RULE_FIELD``), a każda inna forma to odmowa bez pola, ze zdaniem nad formularzem. Sam formularz odmawia tylko tego,
czego typ silnika nie wyrazi: reguły bez działania i godziny, która nie jest godziną z minutą.

Nowa reguła dostaje id ``regula-<n>`` z najmniejszym ``n`` od 1, którego nie ma żadna reguła teraz ani żaden klucz
Historii Ustawień pliku reguł (``used``), i staje na końcu listy. Id usuniętej reguły nie wraca więc do nowej, a klucz
Historii ``reguly.<id>`` zawsze wskazuje jedną regułę: „Cofnij” starego wiersza nie rusza reguły dodanej po nim. Historii
się nie przycina, więc ``used`` ma każde id, jakie plik reguł kiedykolwiek miał w Historii, także z Wydania i spoza
Centrum. Zmieniona reguła zostaje na swoim miejscu, więc kolejność reguł w pliku (od niej zależy kolejność kolumn
podpowiedzi Uzupełnienia) się nie zmienia.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
import re
from typing import Final, TypeVar, assert_never

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldName, FieldPath, FieldProblem
from rozliczenia.quantity_engine import (
    ActivitiesContain,
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
    Scope,
    StartedAt,
    TextMode,
    Write,
    WriteNothing,
)

SCOPES: Final[Mapping[Scope, contract.RuleScope]] = {Scope.KNOWN: "known", Scope.UNKNOWN: "unknown", Scope.EVERY: "every"}
GROUPS: Final[Mapping[DeviceGroup, contract.DeviceGroup]] = {
    DeviceGroup.ROUTER: "router",
    DeviceGroup.TV: "tv",
    DeviceGroup.EXTENDER: "extender",
}
_MODES: Final[Mapping[TextMode, contract.DevicesMode]] = {
    TextMode.EMPTY: "empty",
    TextMode.EXACTLY: "exactly",
    TextMode.CONTAINS: "contains",
}
_MULTIPLIERS: Final[Mapping[Multiplier, contract.RuleMultiplier]] = {
    Multiplier.ONCE: "once",
    Multiplier.COMPONENT: "component",
    Multiplier.PIECES: "pieces",
}
_HOUR: Final = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
_NEW_ID: Final = "regula-{}"
_K = TypeVar("_K")
_V = TypeVar("_V")


@dataclass(frozen=True)
class UnknownRule:
    """Reguły o tym id nie ma w regułach, którymi liczy Centrum."""


def form_of(rule: QuantityRule) -> contract.RuleForm:
    """Reguła silnika jako formularz edytora."""

    return contract.RuleForm(
        scope=SCOPES[rule.scope],
        conditions=[_condition_form(condition) for condition in rule.conditions],
        action=_action_form(rule.action),
    )


def edited(
    rules: tuple[QuantityRule, ...], edit: contract.RuleEdit, used: frozenset[str]
) -> tuple[QuantityRule, ...] | FieldProblem | UnknownRule:
    """Reguły ``rules`` po zmianie ``edit``, jeszcze niesprawdzone przez silnik; ``used``: id reguł z kluczy Historii
    Ustawień, których nowa reguła nie dostanie. ``FieldProblem``: formularz, którego typ silnika nie wyrazi,
    ``UnknownRule``: zmiana albo usunięcie reguły, której nie ma."""

    match edit:
        case contract.AddRule(rule=form):
            rule = _rule(form, _new_id(rules, used))
            return rule if isinstance(rule, FieldProblem) else (*rules, rule)
        case contract.ChangeRule(rule_id=rule_id, rule=form):
            if rule_id not in {rule.id for rule in rules}:
                return UnknownRule()
            rule = _rule(form, rule_id)
            return rule if isinstance(rule, FieldProblem) else tuple(rule if old.id == rule_id else old for old in rules)
        case contract.RemoveRule(rule_id=rule_id):
            if rule_id not in {rule.id for rule in rules}:
                return UnknownRule()
            return tuple(rule for rule in rules if rule.id != rule_id)
        case _:
            assert_never(edit)


def edited_id(before: tuple[QuantityRule, ...], after: tuple[QuantityRule, ...]) -> str | None:
    """Id reguły, którą zmiana dodała albo zmieniła (``None``: zmiana tylko usunęła albo niczego nie zmieniła)."""

    old = {rule.id: rule for rule in before}
    return next((rule.id for rule in after if old.get(rule.id) != rule), None)


def checked(rules: tuple[QuantityRule, ...], devices: DeviceList, rule_id: str | None) -> QuantityRules | FieldProblem:
    """Reguły po zmianie sprawdzone przez silnik z Listą Urządzeń ``devices``; problem reguły ``rule_id`` ma pole
    formularza, każdy inny tylko zdanie."""

    try:
        return QuantityRules(rules, devices)
    except QuantityRulesRefused as refused:
        problem = refused.problem
        prefix = f"reguly[{rule_id}]."
        place = problem.field.removeprefix(prefix) if rule_id is not None and problem.field.startswith(prefix) else None
        return FieldProblem(None if place is None else _field(place), problem.message)


_RULE_FIELD: Final = re.compile(
    r"jesli\[(?P<condition>\d+)\]\.(?P<condition_field>skladnik|tekst|slowo|dni|od)"
    r"|to\.wpisy\[(?P<write>\d+)\]\.(?P<write_field>kolumna|wartosc|skladnik)"
    r"|to\.(?P<action_field>wpisy|kolumny)"
)
"""Miejsca problemu jednej reguły w silniku, które formularz ma jako pole; inne nie mają pola."""
_NAMES: Final[Mapping[str, FieldName]] = {
    "skladnik": "skladnik",
    "tekst": "tekst",
    "slowo": "slowo",
    "dni": "dni",
    "od": "od",
    "kolumna": "kolumna",
    "wartosc": "wartosc",
    "wpisy": "wpisy",
    "kolumny": "kolumny",
}


def _field(place: str) -> FieldPath | None:
    found = _RULE_FIELD.fullmatch(place)
    if found is None:
        return None
    if found["condition"] is not None:
        return FieldPath("jesli", int(found["condition"]), _NAMES[found["condition_field"]])
    if found["write"] is not None:
        return FieldPath("to", "wpisy", int(found["write"]), _NAMES[found["write_field"]])
    return FieldPath("to", _NAMES[found["action_field"]])


def _new_id(rules: tuple[QuantityRule, ...], used: frozenset[str]) -> str:
    taken = {rule.id for rule in rules} | used
    return next(_NEW_ID.format(number) for number in range(1, len(taken) + 2) if _NEW_ID.format(number) not in taken)


def _rule(form: contract.RuleForm, rule_id: str) -> QuantityRule | FieldProblem:
    conditions: list[Condition] = []
    for index, condition in enumerate(form.conditions):
        built = _condition(condition, index)
        if isinstance(built, FieldProblem):
            return built
        conditions.append(built)
    if form.action is None:
        return FieldProblem(FieldPath("to"), messages.rule_without_action())
    return QuantityRule(rule_id, tuple(conditions), _key(SCOPES, form.scope), _action(form.action))


def _key(shown: Mapping[_K, _V], value: _V) -> _K:
    return next(key for key, each in shown.items() if each == value)


def _condition(condition: contract.RuleCondition, index: int) -> Condition | FieldProblem:
    match condition:
        case contract.ComponentCondition(component=component, negated=negated):
            return ContainsComponent(component, negated)
        case contract.DevicesCondition(mode=mode, text=text, negated=negated):
            return DevicesText(_key(_MODES, mode), text, negated)
        case contract.ActivitiesCondition(text=text, negated=negated):
            return ActivitiesContain(text, negated)
        case contract.ContractCondition(word=word, negated=negated):
            return ContractFirstWord(word, negated)
        case contract.DateCondition(days=days, since=since, negated=negated):
            hour = _HOUR.fullmatch(since)
            if hour is None:
                return FieldProblem(FieldPath("jesli", index, "od"), messages.rule_hour())
            return StartedAt(frozenset(days), time(int(hour[1]), int(hour[2])), negated)
        case contract.GroupCondition(group=group, negated=negated):
            return HasGroup(_key(GROUPS, group), negated)
        case _:
            assert_never(condition)


def _action(action: contract.RuleAction) -> Fill | WriteNothing | LeaveEmpty:
    match action:
        case contract.FillAction(writes=writes):
            return Fill(
                tuple(
                    Write(write.column, write.value, _key(_MULTIPLIERS, write.multiplier), write.component) for write in writes
                )
            )
        case contract.NothingAction():
            return WriteNothing()
        case contract.LeaveEmptyAction(columns=columns):
            return LeaveEmpty(tuple(columns))
        case _:
            assert_never(action)


def _condition_form(condition: Condition) -> contract.RuleCondition:
    match condition:
        case ContainsComponent(component=component, negated=negated):
            return contract.ComponentCondition(kind="component", component=component, negated=negated)
        case DevicesText(mode=mode, text=text, negated=negated):
            return contract.DevicesCondition(kind="devices", mode=_MODES[mode], text=text, negated=negated)
        case ActivitiesContain(text=text, negated=negated):
            return contract.ActivitiesCondition(kind="activities", text=text, negated=negated)
        case ContractFirstWord(word=word, negated=negated):
            return contract.ContractCondition(kind="contract", word=word, negated=negated)
        case StartedAt(days=days, since=since, negated=negated):
            return contract.DateCondition(kind="date", days=sorted(days), since=f"{since:%H:%M}", negated=negated)
        case HasGroup(group=group, negated=negated):
            return contract.GroupCondition(kind="group", group=GROUPS[group], negated=negated)
        case _:
            assert_never(condition)


def _action_form(action: Fill | WriteNothing | LeaveEmpty) -> contract.RuleAction:
    match action:
        case Fill(writes=writes):
            return contract.FillAction(
                kind="fill",
                writes=[
                    contract.RuleWrite(
                        column=write.column, value=write.value, multiplier=_MULTIPLIERS[write.multiplier], component=write.component
                    )
                    for write in writes
                ],
            )
        case WriteNothing():
            return contract.NothingAction(kind="nothing")
        case LeaveEmpty(columns=columns):
            return contract.LeaveEmptyAction(kind="leave_empty", columns=list(columns))
        case _:
            assert_never(action)
