"""Kontrakt sekcji Reguły ilości i Urządzenia okna Ustawień: reguły jako zdania „jeśli … to …” i Lista Urządzeń, tylko
do odczytu."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.settings import SettingProblem


class SentenceText(Model):
    kind: Literal["text"]
    text: str


class SentenceColumn(Model):
    """Kolumna Ilości usług w zdaniu: litera i nazwa pozycji cennika z wiersza 17 Wzorca pliku zbiorczego; ``None``:
    Wzorca nie da się przeczytać albo komórka jest pusta."""

    kind: Literal["column"]
    letter: str
    name: str | None


SentencePart = Annotated[SentenceText | SentenceColumn, Field(discriminator="kind")]

RuleScope = Literal["known", "unknown", "every"]
"""Dla których zleceń reguła działa: Lista Urządzeń zna każdy składnik ``URZĄDZENIA``, jest składnik spoza listy,
każde zlecenie."""


class QuantityRuleSentence(Model):
    """Reguła ilości jako zdanie „jeśli … to …”, poskładane z tekstu i kolumn, w kolejności z pliku reguł."""

    id: str
    scope: RuleScope
    sentence: list[SentencePart]


DeviceGroup = Literal["router", "tv", "extender"]


class DeviceComponent(Model):
    """Składnik Listy Urządzeń: nazwa (pierwszy zapis), inne zapisy tej samej rzeczy i grupa (``None``: żadna)."""

    id: str
    name: str
    other_spellings: list[str]
    group: DeviceGroup | None


class QuantityRulesSettings(Model):
    """Reguły ilości i Lista Urządzeń, którymi liczy następne Przygotowanie pliku zbiorczego. ``rules_problem`` i
    ``devices_problem``: złe ustawienie w pliku, a wtedy pokazane są reguły, którymi Centrum liczy mimo to."""

    rules: list[QuantityRuleSentence]
    devices: list[DeviceComponent]
    rules_problem: SettingProblem | None
    devices_problem: SettingProblem | None
