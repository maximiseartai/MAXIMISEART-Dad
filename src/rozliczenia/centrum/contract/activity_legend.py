"""Kontrakt sekcji Legenda czynności okna Ustawień: Kody czynności jako zdania (ADR 0038)."""

from __future__ import annotations

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem


class ActivityCodeSentence(Model):
    """Kod czynności jako jedno zdanie: zapisy i to, co wyznacza, z kolumnami nazwanymi z cennika."""

    id: str
    sentence: list[SentencePart]


class ActivityLegendSettings(Model):
    """Legenda czynności, którą liczy następne Przygotowanie pliku zbiorczego, w kolejności z pliku. ``problem``: złe
    ustawienie w pliku, a wtedy pokazana jest legenda, którą Centrum liczy mimo to (ostatnia dobra albo z Wydania)."""

    codes: list[ActivityCodeSentence]
    problem: SettingProblem | None
