"""Interfejs HTTP sekcji Reguły ilości i Urządzenia okna Ustawień (ADR 0033): odczyt reguł jako zdań i formularzy,
Listy Urządzeń i kolumn, edytor reguły (dodaj, zmień, usuń) i podgląd zmiany przed zapisem.

Reguły i Listę Urządzeń daje właściciel Ustawień (``CentrumSettings.quantity_rules``), te same, którymi liczy następne
Uruchomienie. Każdy zapis edytora idzie zapisem właściciela (``CentrumSettings.change`` pliku reguł), więc sprawdza go
ta sama reguła pary Reguł ilości i Listy Urządzeń co odczyt, cofnięcie i zmianę spoza Centrum, a zmiana ma wiersz
Historii z „Cofnij”. Przed nim silnik sprawdza reguły po zmianie z bieżącą Listą Urządzeń, a jego problem z reguły
edytora wraca jako odmowa 422 z polem formularza (``rule_forms.checked``); zmiana albo usunięcie reguły, której już
nie ma, to 404.

Nazwy kolumn to pozycje cennika z wiersza 17 Wzorca pliku zbiorczego z Konfiguracji, czytane tą samą drogą co jego
Sprawdzanie; Wzorzec, którego nie da się przeczytać, daje same litery. Odczyt i podgląd niczego nie zapisują.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import threading

from fastapi import APIRouter

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem
from rozliczenia.centrum.quantity_rules_preview import RecentCollectiveFiles, preview
from rozliczenia.centrum.rule_forms import GROUPS, SCOPES, UnknownRule, checked, edited, edited_id, form_of
from rozliczenia.centrum.rule_sentences import rule_sentence
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import RULES, RULES_SECTION
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.quantity_engine import BUILT_IN_COLUMNS, QuantityRule, QuantityRules, RulesProblem
from rozliczenia.quantity_rules_file import parse_rule
from rozliczenia.template_file import TemplateFile
from rozliczenia.workbook_files import WorkbookError

_REFUSED: dict[int | str, dict[str, object]] = {
    422: {"model": common_contract.Problem, "description": "Zła reguła ilości z polem formularza i zdaniem"}
}
_UNKNOWN_OR_REFUSED: dict[int | str, dict[str, object]] = {404: {"model": common_contract.Problem}, **_REFUSED}


class PriceList:
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


RuleSentences = Callable[[str, str | None], list[SentencePart] | None]
"""Zdanie reguły z wartości klucza Historii Ustawień (``reguly.<id>``); ``None``: klucz innej sekcji albo wartość, z której
nie da się odtworzyć reguły."""


def history_sentences(settings: CentrumSettings, price_list: PriceList) -> Callable[[], RuleSentences]:
    """Zdania reguł dla jednego odczytu Historii: składniki nazwane bieżącą Listą Urządzeń, kolumny nazwami z cennika."""

    def reader() -> RuleSentences:
        devices = settings.quantity_rules().rules.devices
        names = price_list.names()

        def sentence(key: str, value: str | None) -> list[SentencePart] | None:
            if value is None or not key.startswith(f"{RULES_SECTION}."):
                return None
            try:
                entry: object = json.loads(value)
            except ValueError:
                return None
            rule = parse_rule(entry)
            return None if isinstance(rule, RulesProblem) else rule_sentence(rule, devices, names)

        return sentence

    return reader


def quantity_rules_router(settings: CentrumSettings, price_list: PriceList, recent: RecentCollectiveFiles) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    def described() -> contract.QuantityRulesSettings:
        view = settings.quantity_rules()
        names = price_list.names()
        return contract.QuantityRulesSettings(
            rules=[_rule(rule, view.rules, names) for rule in view.rules.rules],
            devices=[
                contract.DeviceComponent(
                    id=component.id,
                    name=component.spellings[0],
                    other_spellings=list(component.spellings[1:]),
                    group=None if component.group is None else GROUPS[component.group],
                )
                for component in view.rules.devices.components
            ],
            columns=[
                contract.RuleColumn(letter=letter, name=names.get(letter) or None, writable=letter not in BUILT_IN_COLUMNS)
                for letter in QUANTITY_LETTERS
            ],
            rules_problem=_problem(view.rules_problem),
            devices_problem=_problem(view.devices_problem),
        )

    def proposed(edit: contract.RuleEdit) -> tuple[QuantityRules, QuantityRules, str | None]:
        """Reguły teraz i po zmianie ``edit`` sprawdzone przez silnik oraz id reguły, którą zmiana dodaje albo zmienia."""

        now = settings.quantity_rules().rules
        rules = edited(now.rules, edit)
        if isinstance(rules, UnknownRule):
            raise refusal.quantity_rule_unknown()
        if isinstance(rules, FieldProblem):
            raise refusal.setting_refused(rules)
        rule_id = edit.rule_id if isinstance(edit, contract.ChangeRule) else edited_id(now.rules, rules)
        after = checked(rules, now.devices, rule_id)
        if isinstance(after, FieldProblem):
            raise refusal.setting_refused(after)
        return now, after, rule_id

    def saved(edit: contract.RuleEdit) -> contract.QuantityRulesSaved:
        """Zapis zmiany przez właściciela Ustawień: na bieżącej wartości pliku reguł, z jego sprawdzeniem pary."""

        proposed(edit)

        def applied(current: tuple[QuantityRule, ...]) -> tuple[QuantityRule, ...]:
            changed = edited(current, edit)
            return changed if isinstance(changed, tuple) else current

        match settings.change(RULES, applied):
            case Saved(change=change):
                return contract.QuantityRulesSaved(quantity_rules=described(), change=change)
            case Refused(problem=problem):
                raise refusal.setting_refused(problem)
            case NotSaved():
                raise refusal.settings_not_saved()

    @router.get("/quantity-rules", operation_id="getQuantityRules")
    def read() -> contract.QuantityRulesSettings:
        return described()

    @router.post("/quantity-rules", operation_id="addQuantityRule", responses=_REFUSED)
    def add(rule: contract.RuleForm) -> contract.QuantityRulesSaved:
        return saved(contract.AddRule(kind="add", rule=rule))

    @router.put("/quantity-rules/{rule_id}", operation_id="changeQuantityRule", responses=_UNKNOWN_OR_REFUSED)
    def change(rule_id: str, rule: contract.RuleForm) -> contract.QuantityRulesSaved:
        return saved(contract.ChangeRule(kind="change", rule_id=rule_id, rule=rule))

    @router.delete("/quantity-rules/{rule_id}", operation_id="removeQuantityRule", responses=_UNKNOWN_OR_REFUSED)
    def remove(rule_id: str) -> contract.QuantityRulesSaved:
        return saved(contract.RemoveRule(kind="remove", rule_id=rule_id))

    @router.post("/quantity-rules/preview", operation_id="previewQuantityRules", responses=_UNKNOWN_OR_REFUSED)
    def preview_change(edit: contract.RuleEdit) -> contract.RulesPreview:
        """Skutek zmiany na ostatnich Plikach zbiorczych po Przebiegu rozliczeń, bez zapisu (``quantity_rules_preview``)."""

        now, after, rule_id = proposed(edit)
        names = price_list.names()

        def sentence(rule: QuantityRule) -> list[SentencePart]:
            return rule_sentence(rule, after.devices, names)

        rule = next((rule for rule in after.rules if rule.id == rule_id), None)
        shown = None if rule is None else sentence(rule)
        directory = settings.snapshot().folders.periods_directory_to_read
        if directory is None:
            return contract.PreviewWithoutFiles(state="no_periods_directory", sentence=shown)
        found = recent.read(directory)
        if not found.files and not found.unread:
            return contract.PreviewWithoutFiles(state="no_settled_periods", sentence=shown)
        return preview(now, after, found, names, sentence, shown)

    return router


def _rule(rule: QuantityRule, rules: QuantityRules, names: Mapping[str, str]) -> contract.QuantityRuleSentence:
    return contract.QuantityRuleSentence(
        id=rule.id, scope=SCOPES[rule.scope], sentence=rule_sentence(rule, rules.devices, names), rule=form_of(rule)
    )


def _problem(problem: FieldProblem | None) -> SettingProblem | None:
    return None if problem is None else SettingProblem(field=problem.place, message=problem.sentence)
