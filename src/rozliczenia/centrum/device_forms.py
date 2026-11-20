from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final, assert_never

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.rule_forms import GROUPS
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldPath, FieldProblem
from rozliczenia.quantity_engine import Component, DeviceGroup, device_spelling

_GROUP_OF: Final[Mapping[contract.DeviceGroup, DeviceGroup]] = {shown: group for group, shown in GROUPS.items()}
_NOT_IN_ID: Final = re.compile(r"[\W_]+")


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
    ...


def device_component(component: Component) -> contract.DeviceComponent:
    return contract.DeviceComponent(
        id=component.id,
        name=component.spellings[0],
        other_spellings=list(component.spellings[1:]),
        group=None if component.group is None else GROUPS[component.group],
    )


def edited(
    components: tuple[Component, ...], edit: DeviceEdit, used: frozenset[str]
) -> tuple[Component, ...] | FieldProblem | UnknownComponent:
    match edit:
        case AddComponent(form=form):
            built = _component(form, _new_id(components, form, used))
            return built if isinstance(built, FieldProblem) else (*components, built)
        case ChangeComponent(component=identifier, form=form):
            if identifier not in {component.id for component in components}:
                return UnknownComponent()
            built = _component(form, identifier)
            return built if isinstance(built, FieldProblem) else tuple(built if old.id == identifier else old for old in components)
        case RemoveComponent(component=identifier):
            if identifier not in {component.id for component in components}:
                return UnknownComponent()
            return tuple(component for component in components if component.id != identifier)
        case _:
            assert_never(edit)


def dad_devices(
    components: tuple[Component, ...], edit: DeviceEdit, used: frozenset[str]
) -> tuple[Component, ...] | FieldProblem:
    changed = edited(components, edit, used)
    return components if isinstance(changed, UnknownComponent) else changed


def field_of(edit: DeviceEdit, spelling: str) -> FieldPath | None:
    match edit:
        case AddComponent(form=form) | ChangeComponent(form=form):
            return next((field for field, typed in _typed(form) if typed == spelling), None)
        case RemoveComponent():
            return None
        case _:
            assert_never(edit)


def _typed(form: contract.ComponentForm) -> list[tuple[FieldPath, str]]:
    return [(FieldPath("nazwa"), device_spelling(form.name))] + [
        (FieldPath("zapisy", index), device_spelling(spelling)) for index, spelling in enumerate(form.other_spellings)
    ]


def _component(form: contract.ComponentForm, identifier: str) -> Component | FieldProblem:
    typed = _typed(form)
    if not typed[0][1]:
        return FieldProblem(FieldPath("nazwa"), messages.component_name_empty())
    spellings: dict[str, None] = {}
    for field, spelling in typed:
        if not spelling:
            continue
        if "*" in spelling:
            return FieldProblem(field, messages.spelling_with_star(spelling))
        spellings[spelling] = None
    return Component(identifier, tuple(spellings), None if form.group is None else _GROUP_OF[form.group])


def _new_id(components: tuple[Component, ...], form: contract.ComponentForm, used: frozenset[str]) -> str:
    base = _NOT_IN_ID.sub("-", device_spelling(form.name)).strip("-") or "skladnik"
    taken = {component.id for component in components} | used
    return next(
        candidate
        for candidate in (base, *(f"{base}-{number}" for number in range(2, len(taken) + 3)))
        if candidate not in taken
    )
