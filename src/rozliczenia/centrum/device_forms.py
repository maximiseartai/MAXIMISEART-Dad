"""Sekcja Urządzenia okna Ustawień (ADR 0033): formularz składnika z kontraktu ↔ składnik silnika ``Component`` i zmiana
Listy Urządzeń.

Zapisy z formularza Centrum zapisuje tak, jak Reguły ilości czytają słowa ``URZĄDZENIA`` (``device_spelling``), a
powtórzony zapis w jednym składniku liczy się raz. Formularz odmawia z polem (``nazwa``, ``zapisy[<n>]``) tylko tego,
czego sam nie wyrazi: składnika bez nazwy i zapisu z gwiazdką. Listę po zmianie sprawdza właściciel Ustawień jako zmianę
pary, tak samo dla formularza i „Cofnij” (``CentrumSettings._dad_change``): zapis, który ma już inny składnik, i
składnik, którego potrzebuje reguła; pole formularza z zapisem, którego dotyczy jego odmowa, daje ``field_of``.

Nowy składnik dostaje id ze swojej nazwy (każdy ciąg znaków innych niż litery i cyfry na „-”, bo id stoi w adresie jego
zmiany i usunięcia; zajęte z kolejnym numerem) i staje na końcu listy. Zajęte jest
id składnika z listy i każde id z wierszy Historii Ustawień listy (``used``), więc „Cofnij” starszego wiersza nie rusza
składnika dodanego później pod tą samą nazwą. Zmieniony zostaje na swoim miejscu z tym samym id, więc reguły, które go
potrzebują, działają dalej z nowymi zapisami.
"""

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
"""Znaki, których id składnika nie ma: wszystko poza literami i cyframi („/”, „?”, „#”, „.” psują adres w przeglądarce)."""


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
    """Lista ``components`` po zmianie ``edit``, jeszcze niesprawdzona jako lista; ``used``: id składników z wierszy
    Historii, których nowy składnik nie dostanie. ``FieldProblem``: zły formularz, ``UnknownComponent``: zmiana albo
    usunięcie składnika, którego nie ma."""

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


def field_of(edit: DeviceEdit, spelling: str) -> FieldPath | None:
    """Pole formularza zmiany ``edit``, w którym tata wpisał zapis ``spelling`` (``None``: usunięcie składnika albo zapis
    spoza formularza): przy nim stoi odmowa właściciela o tym zapisie."""

    match edit:
        case AddComponent(form=form) | ChangeComponent(form=form):
            return next((field for field, typed in _typed(form) if typed == spelling), None)
        case RemoveComponent():
            return None
        case _:
            assert_never(edit)


def _typed(form: contract.ComponentForm) -> list[tuple[FieldPath, str]]:
    """Zapisy formularza w postaci zapisu Listy Urządzeń, każdy z polem, z którego pochodzi."""

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
    """Id nowego składnika z jego nazwy: ``ont x`` → ``ont-x``, ``ont/stb`` → ``ont-stb``, zajęte na liście albo w Historii
    → ``ont-x-2``; składnik bez nazwy i tak odpada."""

    base = _NOT_IN_ID.sub("-", device_spelling(form.name)).strip("-") or "skladnik"
    taken = {component.id for component in components} | used
    return next(
        candidate
        for candidate in (base, *(f"{base}-{number}" for number in range(2, len(taken) + 3)))
        if candidate not in taken
    )
