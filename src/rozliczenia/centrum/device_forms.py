"""Sekcja Urządzenia okna Ustawień (ADR 0033): formularz składnika z kontraktu ↔ składnik silnika ``Component`` i zmiana
Listy Urządzeń.

Zapisy z formularza Centrum zapisuje tak, jak Reguły ilości czytają słowa ``URZĄDZENIA`` (``device_spelling``), a
powtórzony zapis w jednym składniku liczy się raz. Formularz odmawia z polem (``nazwa``, ``zapisy[<n>]``) składnika bez
nazwy, zapisu z gwiazdką i zapisu, który ma już inny składnik, nazwany jego nazwą. Usunięcie składnika, którego
potrzebuje reguła, to odmowa ze zdaniem tej reguły (``needed_by``), a resztę niezmienników listy sprawdza silnik
(``DeviceList``). Przy zapisie właściciel Ustawień sprawdza jeszcze raz listę razem z regułami (``CentrumSettings``).

Nowy składnik dostaje id ze swojej nazwy (spacje na „-”, zajęte z kolejnym numerem) i staje na końcu listy. Zajęte jest
id składnika z listy i każde id z wierszy Historii Ustawień listy (``used``), więc „Cofnij” starszego wiersza nie rusza
składnika dodanego później pod tą samą nazwą. Zmieniony zostaje na swoim miejscu z tym samym id, więc reguły, które go
potrzebują, działają dalej z nowymi zapisami.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, assert_never

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.rule_forms import GROUPS
from rozliczenia.centrum.rule_sentences import plain_sentence, rule_sentence
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldPath, FieldProblem
from rozliczenia.quantity_engine import (
    Component,
    DeviceGroup,
    DeviceList,
    QuantityRules,
    QuantityRulesRefused,
    device_spelling,
)

_GROUP_OF: Final[Mapping[contract.DeviceGroup, DeviceGroup]] = {shown: group for group, shown in GROUPS.items()}


@dataclass(frozen=True)
class AddComponent:
    form: contract.ComponentForm


@dataclass(frozen=True)
class ChangeComponent:
    component: str
    form: contract.ComponentForm


@dataclass(frozen=True)
class RemoveComponent:
    component: str


DeviceEdit = AddComponent | ChangeComponent | RemoveComponent


@dataclass(frozen=True)
class UnknownComponent:
    """Składnika o tym id nie ma na Liście Urządzeń, którą liczy Centrum."""


def device_component(component: Component) -> contract.DeviceComponent:
    """Składnik Listy Urządzeń dla sekcji Urządzenia."""

    return contract.DeviceComponent(
        id=component.id,
        name=component.spellings[0],
        other_spellings=list(component.spellings[1:]),
        group=None if component.group is None else GROUPS[component.group],
    )


def edited(
    components: tuple[Component, ...], edit: DeviceEdit, used: frozenset[str]
) -> tuple[Component, ...] | FieldProblem | UnknownComponent:
    """Lista ``components`` po zmianie ``edit`` sprawdzona przez silnik; ``used``: id składników z wierszy Historii,
    których nowy składnik nie dostanie. ``FieldProblem``: zły formularz albo lista, ``UnknownComponent``: zmiana albo
    usunięcie składnika, którego nie ma."""

    match edit:
        case AddComponent(form=form):
            built = _component(form, _new_id(components, form, used), components)
            after = built if isinstance(built, FieldProblem) else (*components, built)
        case ChangeComponent(component=identifier, form=form):
            if identifier not in {component.id for component in components}:
                return UnknownComponent()
            others = tuple(component for component in components if component.id != identifier)
            built = _component(form, identifier, others)
            after = built if isinstance(built, FieldProblem) else tuple(built if old.id == identifier else old for old in components)
        case RemoveComponent(component=identifier):
            if identifier not in {component.id for component in components}:
                return UnknownComponent()
            after = tuple(component for component in components if component.id != identifier)
        case _:
            assert_never(edit)
    if isinstance(after, FieldProblem):
        return after
    try:
        DeviceList(after)
    except QuantityRulesRefused as refused:
        return FieldProblem(None, refused.problem.message)
    return after


def needed_by(
    rules: QuantityRules, components: tuple[Component, ...], names: Mapping[str, str]
) -> FieldProblem | None:
    """Odmowa listy ``components``, której brakuje składnika potrzebnego regule ``rules`` (pierwszej takiej), ze
    zdaniem tej reguły; składnik i reguła nazwane jak w oknie Ustawień (``names``: kolumna → nazwa z cennika)."""

    devices = DeviceList(components)
    for rule in rules.rules:
        try:
            QuantityRules((rule,), devices)
        except QuantityRulesRefused as refused:
            missing = refused.problem.component
            if missing is not None:
                name = next(component.spellings[0] for component in rules.devices.components if component.id == missing)
                sentence = plain_sentence(rule_sentence(rule, rules.devices, names))
                return FieldProblem(None, messages.component_used_by_rule(name, sentence))
    return None


def _component(form: contract.ComponentForm, identifier: str, others: tuple[Component, ...]) -> Component | FieldProblem:
    name = device_spelling(form.name)
    if not name:
        return FieldProblem(FieldPath("nazwa"), messages.component_name_empty())
    typed = [(FieldPath("nazwa"), name)] + [
        (FieldPath("zapisy", index), device_spelling(spelling)) for index, spelling in enumerate(form.other_spellings)
    ]
    owners = {spelling: other for other in others for spelling in other.spellings}
    spellings: dict[str, None] = {}
    for field, spelling in typed:
        if not spelling:
            continue
        if "*" in spelling:
            return FieldProblem(field, messages.spelling_with_star(spelling))
        owner = owners.get(spelling)
        if owner is not None:
            return FieldProblem(field, messages.spelling_taken(spelling, owner.spellings[0]))
        spellings[spelling] = None
    return Component(identifier, tuple(spellings), None if form.group is None else _GROUP_OF[form.group])


def _new_id(components: tuple[Component, ...], form: contract.ComponentForm, used: frozenset[str]) -> str:
    """Id nowego składnika z jego nazwy: ``ont x`` → ``ont-x``, zajęte na liście albo w Historii → ``ont-x-2``; składnik
    bez nazwy i tak odpada."""

    base = device_spelling(form.name).replace(" ", "-") or "skladnik"
    taken = {component.id for component in components} | used
    return next(
        candidate
        for candidate in (base, *(f"{base}-{number}" for number in range(2, len(taken) + 3)))
        if candidate not in taken
    )
