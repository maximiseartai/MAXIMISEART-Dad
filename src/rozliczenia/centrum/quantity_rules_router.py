"""Interfejs HTTP sekcji Reguły ilości i Urządzenia okna Ustawień: odczyt reguł jako zdań i Listy Urządzeń (ADR 0033).

Reguły i Listę Urządzeń daje właściciel Ustawień (``CentrumSettings.quantity_rules``), te same, którymi liczy następne
Uruchomienie. Nazwy kolumn to pozycje cennika z wiersza 17 Wzorca pliku zbiorczego z Konfiguracji, czytane tą samą
drogą co jego Sprawdzanie; Wzorzec, którego nie da się przeczytać, daje same litery. Odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import threading

from fastapi import APIRouter

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.contract.settings import SettingProblem
from rozliczenia.centrum.rule_sentences import rule_sentence
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.quantity_engine import DeviceGroup, QuantityRules, Scope
from rozliczenia.template_file import TemplateFile
from rozliczenia.workbook_files import WorkbookError

_SCOPES: dict[Scope, contract.RuleScope] = {Scope.KNOWN: "known", Scope.UNKNOWN: "unknown", Scope.EVERY: "every"}
_GROUPS: dict[DeviceGroup, contract.DeviceGroup] = {DeviceGroup.ROUTER: "router", DeviceGroup.TV: "tv", DeviceGroup.EXTENDER: "extender"}


class _PriceList:
    """Nazwy pozycji cennika z Wzorca pliku zbiorczego: jeden Wzorzec na pracę Centrum, który czyta plik od nowa tylko
    po jego zmianie (``TemplateFile``); żądania z kilku wątków czytają go po kolei."""

    def __init__(self, template: Path) -> None:
        self._template = TemplateFile.collective_file(template)
        self._lock = threading.Lock()

    def names(self) -> Mapping[str, str]:
        with self._lock:
            try:
                return self._template.price_list()
            except WorkbookError:
                return {}


def quantity_rules_router(settings: CentrumSettings, collective_template: Path) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])
    price_list = _PriceList(collective_template)

    @router.get("/quantity-rules", operation_id="getQuantityRules")
    def read() -> contract.QuantityRulesSettings:
        view = settings.quantity_rules()
        return contract.QuantityRulesSettings(
            rules=_rules(view.rules, price_list.names()),
            devices=[
                contract.DeviceComponent(
                    id=component.id,
                    name=component.spellings[0],
                    other_spellings=list(component.spellings[1:]),
                    group=None if component.group is None else _GROUPS[component.group],
                )
                for component in view.rules.devices.components
            ],
            rules_problem=_problem(view.rules_problem),
            devices_problem=_problem(view.devices_problem),
        )

    return router


def _rules(rules: QuantityRules, names: Mapping[str, str]) -> list[contract.QuantityRuleSentence]:
    return [
        contract.QuantityRuleSentence(id=rule.id, scope=_SCOPES[rule.scope], sentence=rule_sentence(rule, rules.devices, names))
        for rule in rules.rules
    ]


def _problem(problem: FieldProblem | None) -> SettingProblem | None:
    return None if problem is None else SettingProblem(field=problem.field, message=problem.sentence)
