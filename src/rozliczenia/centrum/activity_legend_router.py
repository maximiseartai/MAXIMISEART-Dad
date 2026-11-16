"""Interfejs HTTP sekcji Legenda czynności okna Ustawień (ADR 0038): odczyt Kodów czynności jako zdań.

Legendę daje właściciel Ustawień (``CentrumSettings.activity_legend``), tę samą, którą liczy następne Uruchomienie; trasa
tylko woła właściciela i tłumaczy jego wynik na kontrakt. Nazwy kolumn to pozycje cennika z wiersza 17 Wzorca pliku
zbiorczego (``PriceList``), a Wzorzec, którego nie da się przeczytać, daje same litery. Odczyt niczego nie zapisuje poza
wierszem Historii zmiany spoza Centrum, który dopisuje każdy odczyt właściciela.
"""

from __future__ import annotations

from collections.abc import Callable
import json

from fastapi import APIRouter

from rozliczenia.activity_legend import LegendProblem
from rozliczenia.activity_legend_file import parse_code
from rozliczenia.centrum.contract import activity_legend as contract
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem
from rozliczenia.centrum.legend_sentences import code_sentence
from rozliczenia.centrum.quantity_rules_router import PriceList, RuleSentences
from rozliczenia.centrum.settings.activity_legend import LEGEND_SECTION
from rozliczenia.centrum.settings.owner import CentrumSettings


def activity_legend_router(settings: CentrumSettings, price_list: PriceList) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    @router.get("/activity-legend", operation_id="getActivityLegend")
    def read() -> contract.ActivityLegendSettings:
        view = settings.activity_legend()
        names = price_list.names()
        return contract.ActivityLegendSettings(
            codes=[contract.ActivityCodeSentence(id=code.id, sentence=code_sentence(code, names)) for code in view.legend.codes],
            problem=None if view.problem is None else SettingProblem(field=view.problem.place, message=view.problem.sentence),
        )

    return router


def with_legend_sentences(others: Callable[[], RuleSentences], price_list: PriceList) -> Callable[[], RuleSentences]:
    """Zdania Historii Ustawień innych sekcji (``others``) i do tego Kodów czynności (klucz ``kody.<id>``)."""

    def reader() -> RuleSentences:
        other = others()
        names = price_list.names()

        def sentence(key: str, value: str | None) -> list[SentencePart] | None:
            if key.partition(".")[0] != LEGEND_SECTION:
                return other(key, value)
            if value is None:
                return None
            try:
                code = parse_code(json.loads(value))
            except ValueError:
                return None
            return None if isinstance(code, LegendProblem) else code_sentence(code, names)

        return sentence

    return reader
