"""Interfejs HTTP sekcji Reguły ilości i Urządzenia okna Ustawień (ADR 0033): odczyt reguł jako zdań i formularzy,
Listy Urządzeń i kolumn, edytor reguły (dodaj, zmień, usuń), podgląd zmiany przed zapisem, edycja Listy Urządzeń (dodaj,
zmień, usuń składnik; ``device_forms``) i jej podpowiedzi z ostatnich okresów (``device_suggestions``).

Reguły i Listę Urządzeń daje właściciel Ustawień (``CentrumSettings.quantity_rules``), te same, którymi liczy następne
Uruchomienie. Trasy tylko parsują żądanie, wołają właściciela i tłumaczą jego wynik na HTTP. Formularz odmawia z polem
tylko tego, czego sam nie wyrazi (``rule_forms``, ``device_forms``), a każdy zapis edytora i sekcji Urządzenia idzie
zapisem taty właściciela (``CentrumSettings.change_with_used_keys``), który sprawdza parę Reguł ilości i Listy Urządzeń
jako zmianę, tym samym zdaniem co „Cofnij” w Historii; odmowę zapisu u dwóch składników trasa stawia przy polu
formularza z tym zapisem. Podgląd pyta właściciela o tę samą zmianę bez zapisu (``CentrumSettings.rules_after``).
Zmiana albo usunięcie reguły albo składnika, którego już nie ma, to 404.

Nazwy kolumn to pozycje cennika z wiersza 17 Wzorca pliku zbiorczego z Konfiguracji, czytane tą samą drogą co jego
Sprawdzanie; Wzorzec, którego nie da się przeczytać, daje same litery. Odczyt, podgląd i podpowiedzi niczego nie
zapisują.
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
from rozliczenia.centrum import device_forms
from rozliczenia.centrum.device_forms import AddComponent, ChangeComponent, DeviceEdit, RemoveComponent, UnknownComponent
from rozliczenia.centrum.device_suggestions import device_suggestions
from rozliczenia.centrum.quantity_rules_preview import RecentCollectiveFiles, preview
from rozliczenia.centrum.rule_forms import SCOPES, UnknownRule, component_field, edited, edited_id, form_of, form_problem
from rozliczenia.centrum.rule_sentences import component_sentence, rule_sentence
from rozliczenia.centrum.settings.files import FieldProblem, Unreadable
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, QuantityRulesView, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import (
    DEVICES,
    DEVICES_SECTION,
    RULES,
    RULES_SECTION,
    TakenSpelling,
    UnlistedComponent,
    device_ids,
    rule_ids,
)
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.quantity_engine import BUILT_IN_COLUMNS, Component, QuantityRule, QuantityRules, RulesProblem
from rozliczenia.quantity_rules_file import parse_component, parse_rule
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
"""Zdanie reguły albo składnika z wartości klucza Historii Ustawień (``reguly.<id>``, ``urzadzenia.<id>``); ``None``: klucz
innej sekcji albo wartość, z której nie da się odtworzyć reguły ani składnika."""


def history_sentences(settings: CentrumSettings, price_list: PriceList) -> Callable[[], RuleSentences]:
    """Zdania reguł i składników dla jednego odczytu Historii: składniki w regułach nazwane bieżącą Listą Urządzeń, kolumny
    nazwami z cennika."""

    def reader() -> RuleSentences:
        devices = settings.quantity_rules().rules.devices
        names = price_list.names()

        def sentence(key: str, value: str | None) -> list[SentencePart] | None:
            section = key.partition(".")[0]
            if value is None or section not in (RULES_SECTION, DEVICES_SECTION):
                return None
            try:
                entry: object = json.loads(value)
            except ValueError:
                return None
            if section == DEVICES_SECTION:
                component = parse_component(entry)
                return None if isinstance(component, RulesProblem) else component_sentence(component)
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
            devices=[device_forms.device_component(component) for component in view.rules.devices.components],
            columns=[
                contract.RuleColumn(letter=letter, name=names.get(letter) or None, writable=letter not in BUILT_IN_COLUMNS)
                for letter in QUANTITY_LETTERS
            ],
            rules_problem=_problem(view.rules_problem),
            devices_problem=_problem(view.devices_problem),
        )

    def proposed(edit: contract.RuleEdit) -> tuple[QuantityRules, QuantityRules, str | None]:
        """Reguły teraz i po zmianie ``edit`` oraz id reguły, którą zmiana dodaje albo zmienia; reguły po zmianie i
        odmowę daje właściciel tą samą drogą co zapis (``CentrumSettings.rules_after``), bez zapisu.

        Historia, której nie da się przeczytać, nie daje id do pominięcia: id nowej reguły w podglądzie może wtedy być
        inne niż przy zapisie, ale zapis i tak się wtedy nie uda (``change_with_used_keys``).
        """

        view = settings.quantity_rules()
        _known_rule(edit, view)
        used = settings.used_keys(RULES)
        keys = frozenset() if isinstance(used, Unreadable) else used
        after = settings.rules_after(lambda current: _ruled(edit)(current, keys))
        if isinstance(after, FieldProblem):
            raise _rule_refused(edit, after)
        rule_id = edit.rule_id if isinstance(edit, contract.ChangeRule) else edited_id(view.source_rules, after.rules)
        return view.rules, after, rule_id

    def saved(edit: contract.RuleEdit) -> contract.QuantityRulesSaved:
        """Zapis zmiany przez właściciela Ustawień: na bieżącej wartości pliku reguł, z jego sprawdzeniem pary."""

        _known_rule(edit, settings.quantity_rules())
        match settings.change_with_used_keys(RULES, _ruled(edit)):
            case Saved(change=change):
                return contract.QuantityRulesSaved(quantity_rules=described(), change=change)
            case Refused(problem=problem):
                raise _rule_refused(edit, problem)
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

    def device_saved(edit: DeviceEdit) -> contract.QuantityRulesSaved:
        """Zmiana Listy Urządzeń zapisem taty właściciela Ustawień na bieżącej wartości pliku, z id nowego składnika spoza
        kluczy Historii (jak reguła); formularz, parę z regułami i uzupełnienie listy sprawdza właściciel
        (``CentrumSettings._dad_change``), a odmowę zapisu u dwóch składników trasa stawia przy polu z tym zapisem."""

        if isinstance(edit, ChangeComponent | RemoveComponent) and edit.component not in settings.quantity_rules().rules.devices.ids():
            raise refusal.device_component_unknown()

        def applied(current: tuple[Component, ...], keys: frozenset[str]) -> tuple[Component, ...] | FieldProblem:
            changed = device_forms.edited(current, edit, device_ids(keys))
            return current if isinstance(changed, UnknownComponent) else changed

        match settings.change_with_used_keys(DEVICES, applied):
            case Saved(change=change):
                return contract.QuantityRulesSaved(quantity_rules=described(), change=change)
            case Refused(problem=TakenSpelling(spelling=spelling) as taken):
                raise refusal.setting_refused(FieldProblem(device_forms.field_of(edit, spelling), taken.sentence))
            case Refused(problem=problem):
                raise refusal.setting_refused(problem)
            case NotSaved():
                raise refusal.settings_not_saved()

    @router.post("/devices", operation_id="addDevice", responses=_REFUSED)
    def add_device(component: contract.ComponentForm) -> contract.QuantityRulesSaved:
        return device_saved(AddComponent(component))

    @router.put("/devices/{device_id}", operation_id="changeDevice", responses=_UNKNOWN_OR_REFUSED)
    def change_device(device_id: str, component: contract.ComponentForm) -> contract.QuantityRulesSaved:
        return device_saved(ChangeComponent(device_id, component))

    @router.delete("/devices/{device_id}", operation_id="removeDevice", responses=_UNKNOWN_OR_REFUSED)
    def remove_device(device_id: str) -> contract.QuantityRulesSaved:
        return device_saved(RemoveComponent(device_id))

    @router.get("/devices/suggestions", operation_id="getDeviceSuggestions")
    def suggestions() -> contract.DeviceSuggestions:
        """Zapisy z ``URZĄDZENIA`` ostatnich Plików zbiorczych spoza Listy Urządzeń (``device_suggestions``)."""

        rules = settings.quantity_rules().rules
        directory = settings.snapshot().folders.periods_directory_to_read
        if directory is None:
            return contract.DeviceSuggestions(suggestions=[], unread=[])
        return device_suggestions(rules, recent.read(directory))

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


def _known_rule(edit: contract.RuleEdit, view: QuantityRulesView) -> None:
    """404, gdy zmiana albo usunięcie dotyczy reguły, której już nie ma w regułach, z których liczy Centrum."""

    if isinstance(edit, contract.ChangeRule | contract.RemoveRule) and edit.rule_id not in {rule.id for rule in view.source_rules}:
        raise refusal.quantity_rule_unknown()


def _rule_refused(edit: contract.RuleEdit, problem: FieldProblem) -> refusal.Refusal:
    """Odmowa właściciela zmiany reguły jako odmowa HTTP; składnik spoza listy stoi przy polu formularza z tym składnikiem."""

    if isinstance(problem, UnlistedComponent) and not isinstance(edit, contract.RemoveRule):
        return refusal.setting_refused(FieldProblem(component_field(edit.rule, problem.component), problem.sentence))
    return refusal.setting_refused(problem)


def _ruled(
    edit: contract.RuleEdit,
) -> Callable[[tuple[QuantityRule, ...], frozenset[str]], tuple[QuantityRule, ...] | FieldProblem]:
    """Zmiana ``edit`` z edytora jako zmiana taty dla właściciela: bieżące reguły i klucze Historii → reguły po zmianie
    albo odmowa formularza z polem (``rule_forms``); reguły, której już nie ma, nie rusza (404 daje ``_known_rule``)."""

    def applied(current: tuple[QuantityRule, ...], keys: frozenset[str]) -> tuple[QuantityRule, ...] | FieldProblem:
        changed = edited(current, edit, rule_ids(keys))
        if isinstance(changed, UnknownRule):
            return current
        if isinstance(changed, FieldProblem):
            return changed
        rule_id = edit.rule_id if isinstance(edit, contract.ChangeRule) else edited_id(current, changed)
        return form_problem(changed, rule_id) or changed

    return applied


def _rule(rule: QuantityRule, rules: QuantityRules, names: Mapping[str, str]) -> contract.QuantityRuleSentence:
    return contract.QuantityRuleSentence(
        id=rule.id, scope=SCOPES[rule.scope], sentence=rule_sentence(rule, rules.devices, names), rule=form_of(rule)
    )


def _problem(problem: FieldProblem | None) -> SettingProblem | None:
    return None if problem is None else SettingProblem(field=problem.place, message=problem.sentence)
