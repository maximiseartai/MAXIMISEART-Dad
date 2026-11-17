"""Interfejs HTTP sekcji Reguły ilości i Urządzenia okna Ustawień (ADR 0033): odczyt reguł jako zdań i formularzy,
Listy Urządzeń i kolumn, edytor reguły (dodaj, zmień, usuń), podgląd zmiany przed zapisem, edycja Listy Urządzeń (dodaj,
zmień, usuń składnik; ``device_forms``) i jej podpowiedzi z ostatnich okresów (``device_suggestions``).

Reguły i Listę Urządzeń daje właściciel Ustawień (``CentrumSettings.quantity_rules``), te same, którymi liczy następne
Uruchomienie. Trasy tylko parsują żądanie, wołają właściciela i tłumaczą jego wynik na HTTP. Formularz odmawia z polem
tylko tego, czego sam nie wyrazi (``rule_forms``, ``device_forms``), a każdy zapis edytora i sekcji Urządzenia idzie
poleceniem formularza do właściciela (``CentrumSettings.change_rules``, ``change_devices``), który sam robi zmianę i
sprawdza parę Reguł ilości i Listy Urządzeń jako zmianę, tym samym zdaniem co „Cofnij” w Historii; odmowę zapisu u dwóch
składników trasa stawia przy polu formularza z tym zapisem. Podgląd pyta właściciela o to samo polecenie bez zapisu
(``CentrumSettings.rules_after``).
Zmiana albo usunięcie reguły albo składnika, którego już nie ma, to 404. Podgląd, zmiana i usunięcie reguły przy pliku
reguł albo Folderów, którego system nie daje teraz czytać, to 409 o tym pliku (``refusal.settings_file_unreadable``,
Foldery przez ``settings_reads.readable_folders``), nie „tej reguły już nie ma” ani „brak folderu okresów”; zmiana i
usunięcie składnika przy pliku pary bez odczytu to 409 o nim (``settings_reads.readable_quantity_rules``), nie „tego
składnika już nie ma”.

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
from rozliczenia.centrum.device_forms import AddComponent, ChangeComponent, DeviceEdit, RemoveComponent
from rozliczenia.centrum.device_suggestions import device_suggestions
from rozliczenia.centrum.quantity_rules_preview import RecentCollectiveFiles, preview
from rozliczenia.centrum.rule_forms import SCOPES, component_field, edited_id, form_of
from rozliczenia.centrum.rule_sentences import component_sentence, rule_sentence
from rozliczenia.centrum.settings.files import FieldProblem, Unreadable
from rozliczenia.centrum.settings.owner import (
    CentrumSettings,
    NotSaved,
    QuantityRulesView,
    Refused,
    Saved,
)
from rozliczenia.centrum.settings.quantity_rules import (
    DEVICES_SECTION,
    RULES,
    RULES_SECTION,
    TakenSpelling,
    UnlistedComponent,
)
from rozliczenia.centrum.settings_reads import readable_folders, readable_quantity_rules
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.quantity_engine import BUILT_IN_COLUMNS, QuantityRule, QuantityRules, RulesProblem
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
        odmowę daje właściciel tą samą drogą co zapis (``CentrumSettings.rules_after``), bez zapisu."""

        view = settings.quantity_rules()
        source_rules = _known_rule(edit, view)
        after = settings.rules_after(edit)
        if isinstance(after, NotSaved):
            match after:
                case NotSaved(unreadable=str(file)):
                    raise refusal.settings_file_unreadable(file)
                case NotSaved():
                    raise refusal.settings_not_saved()
        if isinstance(after, FieldProblem):
            raise refusal.setting_refused(_at_form_field(edit, after))
        rule_id = edit.rule_id if isinstance(edit, contract.ChangeRule) else edited_id(source_rules, after.rules)
        return view.rules, after, rule_id

    def saved(edit: contract.RuleEdit) -> contract.QuantityRulesSaved:
        """Zapis zmiany przez właściciela Ustawień: na bieżącej wartości pliku reguł, z jego sprawdzeniem pary."""

        _known_rule(edit, settings.quantity_rules())
        match settings.change_rules(edit):
            case Saved(change=change):
                return contract.QuantityRulesSaved(quantity_rules=described(), change=change)
            case Refused(problem=problem):
                raise refusal.setting_refused(_at_form_field(edit, problem))
            case NotSaved(unreadable=str(file)):
                raise refusal.settings_file_unreadable(file)
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

        if isinstance(edit, ChangeComponent | RemoveComponent) and edit.component not in readable_quantity_rules(settings).rules.devices.ids():
            raise refusal.device_component_unknown()

        match settings.change_devices(edit):
            case Saved(change=change):
                return contract.QuantityRulesSaved(quantity_rules=described(), change=change)
            case Refused(problem=TakenSpelling(spelling=spelling) as taken):
                raise refusal.setting_refused(FieldProblem(device_forms.field_of(edit, spelling), taken.sentence))
            case Refused(problem=problem):
                raise refusal.setting_refused(problem)
            case NotSaved(unreadable=str(file)):
                raise refusal.settings_file_unreadable(file)
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
        """Zapisy z ``URZĄDZENIA`` ostatnich Plików zbiorczych spoza Listy Urządzeń (``device_suggestions``). Plik
        Folderów bez odczytu daje pustą listę jak niewskazany folder okresów: to podpowiedź, nie straż."""

        rules = settings.quantity_rules().rules
        folders = settings.folders()
        directory = None if isinstance(folders, Unreadable) else folders.periods_directory_to_read
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
        directory = readable_folders(settings).periods_directory_to_read
        if directory is None:
            return contract.PreviewWithoutFiles(state="no_periods_directory", sentence=shown)
        found = recent.read(directory)
        if not found.files and not found.unread:
            return contract.PreviewWithoutFiles(state="no_settled_periods", sentence=shown)
        return preview(now, after, found, names, sentence, shown)

    return router


def _known_rule(edit: contract.RuleEdit, view: QuantityRulesView) -> tuple[QuantityRule, ...]:
    """Reguły, z których liczy Centrum; 404, gdy zmiana albo usunięcie dotyczy reguły, której już w nich nie ma, a 409,
    gdy system nie daje teraz czytać pliku reguł, więc nie wiadomo, czy ją ma."""

    source_rules = view.source_rules
    if isinstance(source_rules, Unreadable):
        raise refusal.settings_file_unreadable(RULES.name)
    if isinstance(edit, contract.ChangeRule | contract.RemoveRule) and edit.rule_id not in {rule.id for rule in source_rules}:
        raise refusal.quantity_rule_unknown()
    return source_rules


def _at_form_field(edit: contract.RuleEdit, problem: FieldProblem) -> FieldProblem:
    """Odmowa właściciela zmiany reguły przy polu formularza: składnik spoza listy stoi przy polu z tym składnikiem,
    a każda inna odmowa zostaje przy swoim miejscu."""

    if isinstance(problem, UnlistedComponent) and not isinstance(edit, contract.RemoveRule):
        return FieldProblem(component_field(edit.rule, problem.component), problem.sentence)
    return problem


def _rule(rule: QuantityRule, rules: QuantityRules, names: Mapping[str, str]) -> contract.QuantityRuleSentence:
    return contract.QuantityRuleSentence(
        id=rule.id, scope=SCOPES[rule.scope], sentence=rule_sentence(rule, rules.devices, names), rule=form_of(rule)
    )


def _problem(problem: FieldProblem | None) -> SettingProblem | None:
    return None if problem is None else SettingProblem(field=problem.place, message=problem.sentence)
