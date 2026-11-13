"""Reguły ilości jako zdania „jeśli … to …” dla taty (ADR 0033), z typów silnika ``quantity_engine``.

Zdanie ma postać „Jeśli A i B, ale nie gdy C albo D, to działanie.”: warunki bez zaprzeczenia, potem zaprzeczone („ale
nie gdy”), potem działanie. Reguła bez warunków to samo działanie, a reguła z samymi zaprzeczonymi to działanie z „ale
nie gdy”. Zakresu zdanie nie mówi: okno Ustawień grupuje według niego reguły. Składnik nazywa jego pierwszy zapis z
Listy Urządzeń, a kolumna to osobna część zdania z literą i nazwą pozycji cennika, którą pokazuje okno.

Każdy rodzaj warunku i działania ma tu swoje zdanie (``match`` z ``assert_never``), więc nowy rodzaj w słowniku nie
przejdzie mypy bez zdania.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import time
from typing import Final, assert_never

from rozliczenia.centrum.contract.quantity_rules import SentenceColumn, SentencePart, SentenceText
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
    StartedAt,
    TextMode,
    Write,
    WriteNothing,
)

_DAYS: Final = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
_GROUPS: Final[Mapping[DeviceGroup, str]] = {DeviceGroup.ROUTER: "router", DeviceGroup.TV: "TV", DeviceGroup.EXTENDER: "extender"}


def rule_sentence(rule: QuantityRule, devices: DeviceList, names: Mapping[str, str]) -> list[SentencePart]:
    """Zdanie reguły ``rule``; ``names``: litera kolumny → nazwa pozycji cennika (brak albo ``""``: sama litera)."""

    held = [_condition(condition, devices) for condition in rule.conditions if not condition.negated]
    excepted = [_condition(condition, devices) for condition in rule.conditions if condition.negated]
    action = _action(rule.action, devices, names)
    exception = f"ale nie gdy {_joined(excepted, ' albo ')}" if excepted else ""
    if held:
        return _parts(f"Jeśli {_joined(held, ' i ')}{', ' + exception if exception else ''}, to ", *action, ".")
    first, *rest = action
    assert isinstance(first, str), "działanie zaczyna się od słowa"
    return _parts(first[:1].upper() + first[1:], *rest, f", {exception}." if exception else ".")


def component_name(component: str, devices: DeviceList) -> str:
    """Nazwa składnika dla taty: jego pierwszy zapis z Listy Urządzeń (identyfikator, gdy go tam nie ma)."""

    return next((found.spellings[0] for found in devices.components if found.id == component), component)


def _condition(condition: Condition, devices: DeviceList) -> str:
    match condition:
        case ContainsComponent(component=component):
            return f"URZĄDZENIA zawierają „{component_name(component, devices)}”"
        case DevicesText(mode=mode, text=text):
            match mode:
                case TextMode.EMPTY:
                    return "URZĄDZENIA są puste"
                case TextMode.EXACTLY:
                    return f"URZĄDZENIA to dokładnie „{text}”"
                case TextMode.CONTAINS:
                    return f"URZĄDZENIA zawierają tekst „{text}”"
                case _:
                    assert_never(mode)
        case ActivitiesContain(text=text):
            return f"CZYNNOŚCI zawierają „{text}”"
        case ContractFirstWord(word=word):
            return f"UMOWA zaczyna się od słowa „{word}”"
        case StartedAt(days=days, since=since):
            return f"DATA to {_days(days)} od {_hour(since)}"
        case HasGroup(group=group):
            return f"zlecenie ma urządzenie z grupy {_GROUPS[group]}"
        case _:
            assert_never(condition)


def _action(action: Fill | WriteNothing | LeaveEmpty, devices: DeviceList, names: Mapping[str, str]) -> list[str | SentenceColumn]:
    match action:
        case Fill(writes=writes):
            amounts: dict[str, list[str]] = {}
            for write in writes:
                amounts.setdefault(_amount(write, devices), []).append(write.column)
            parts: list[str | SentenceColumn] = ["wpisz "]
            for index, (amount, columns) in enumerate(amounts.items()):
                parts += [" oraz " if index else "", f"{amount} w ", *_columns(columns, names)]
            return parts
        case WriteNothing():
            return ["nic nie wpisuj w tym zleceniu"]
        case LeaveEmpty(columns=columns):
            empty = "pustą" if len(columns) == 1 else "puste"
            return ["zostaw ", *_columns(columns, names), f" {empty} w Rozliczeniu pracownika"]
        case _:
            assert_never(action)


def _amount(write: Write, devices: DeviceList) -> str:
    times = "" if write.value == 1 else f"{write.value} × "
    match write.multiplier:
        case Multiplier.ONCE:
            return str(write.value)
        case Multiplier.COMPONENT:
            return f"{times}liczbę „{component_name(write.component or '', devices)}”"
        case Multiplier.PIECES:
            return f"{times}„N szt” z CZYNNOŚCI za każde „{component_name(write.component or '', devices)}”"
        case _:
            assert_never(write.multiplier)


def _columns(letters: Sequence[str], names: Mapping[str, str]) -> list[str | SentenceColumn]:
    parts: list[str | SentenceColumn] = []
    for index, letter in enumerate(letters):
        if index:
            parts.append(" i " if index == len(letters) - 1 else ", ")
        parts.append(SentenceColumn(kind="column", letter=letter, name=names.get(letter) or None))
    return parts


def _days(days: frozenset[int]) -> str:
    """Dni tygodnia po kolei; trzy i więcej dni z rzędu jako przedział „poniedziałek–piątek”."""

    runs: list[list[int]] = []
    for day in sorted(days):
        if runs and runs[-1][-1] == day - 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    shown = [
        f"{_DAYS[run[0]]}–{_DAYS[run[-1]]}" if len(run) >= 3 else ", ".join(_DAYS[day] for day in run) for run in runs
    ]
    return ", ".join(shown)


def _hour(since: time) -> str:
    return f"{since.hour}:{since.minute:02d}"


def _joined(items: Sequence[str], last: str) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + last + items[-1]


def _parts(*items: str | SentenceColumn) -> list[SentencePart]:
    """Części zdania: sąsiednie teksty sklejone w jeden, puste pominięte."""

    parts: list[SentencePart] = []
    for item in items:
        if isinstance(item, SentenceColumn):
            parts.append(item)
        elif item and parts and isinstance(parts[-1], SentenceText):
            parts[-1] = SentenceText(kind="text", text=parts[-1].text + item)
        elif item:
            parts.append(SentenceText(kind="text", text=item))
    return parts
