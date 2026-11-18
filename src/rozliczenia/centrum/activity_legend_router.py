"""Interfejs HTTP sekcji Legenda czynności okna Ustawień (ADR 0038): Kody czynności jako zdania i formularze, kolumny do
wyboru, formularz kodu (dodaj, zmień, usuń) i podgląd zmiany przed zapisem.

Legendę daje właściciel Ustawień (``CentrumSettings.activity_legend``), tę samą, którą liczy następne Uruchomienie;
trasy tylko parsują żądanie, wołają właściciela i tłumaczą jego wynik na HTTP. Każdy zapis formularza idzie poleceniem do
właściciela (``CentrumSettings.change_legend``), który sam robi zmianę (``legend_forms``) i sprawdza legendę po zmianie,
a jego odmowa stoi przy polu formularza. Podgląd pyta właściciela o to samo polecenie bez zapisu
(``CentrumSettings.legend_after``) i liczy jego skutek na ostatnich Plikach zbiorczych (``activity_legend_preview``), więc
zapis jest możliwy także przy różnicach od taty. Zmiana albo usunięcie kodu, którego już nie ma, to 404, a zapis i
podgląd przy pliku legendy, którego system nie daje teraz czytać, to 409 o tym pliku
(``refusal.settings_file_unreadable``), a podgląd także przy pliku pary Reguł ilości albo Folderów bez odczytu
(``CentrumSettings``), nie podgląd liczony Regułami ilości z Wydania. Id kodu w adresie może mieć „/” (``dzielnik1/2``).

Nazwy kolumn to pozycje cennika z wiersza 17 Wzorca pliku zbiorczego (``PriceList``), a Wzorzec, którego nie da się
przeczytać, daje same litery. Odczyt i podgląd niczego nie zapisują poza wierszem Historii zmiany spoza Centrum, który
dopisuje każdy odczyt właściciela.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json

from fastapi import APIRouter

from rozliczenia.activity_legend import AMOUNT_COLUMN, COLUMNS, FILL_COLUMNS, LegendProblem
from rozliczenia.activity_legend_file import parse_code
from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import activity_legend as contract
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem
from rozliczenia.centrum.legend_forms import form_of
from rozliczenia.centrum.legend_sentences import AMOUNT_NAME, code_effects, code_sentence, code_spellings
from rozliczenia.centrum.activity_legend_preview import legend_preview
from rozliczenia.centrum.quantity_rules_preview import RecentCollectiveFiles
from rozliczenia.centrum.quantity_rules_router import PriceList, RuleSentences
from rozliczenia.centrum.settings.activity_legend import LEGEND, LEGEND_SECTION
from rozliczenia.centrum.settings.files import FieldProblem, Unreadable
from rozliczenia.centrum.settings.owner import ActivityLegendView, CentrumSettings, NotSaved, Refused, Saved
from rozliczenia.client_data import ForbiddenValues

_REFUSED: dict[int | str, dict[str, object]] = {
    422: {"model": common_contract.Problem, "description": "Zły Kod czynności z polem formularza i zdaniem"},
    409: {"model": common_contract.Problem, "description": "Pliku Legendy czynności nie da się teraz przeczytać"},
}
_UNKNOWN_OR_REFUSED: dict[int | str, dict[str, object]] = {404: {"model": common_contract.Problem}, **_REFUSED}


def activity_legend_router(
    settings: CentrumSettings, price_list: PriceList, recent: RecentCollectiveFiles, forbidden: ForbiddenValues
) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    def described() -> contract.ActivityLegendSettings:
        view = settings.activity_legend()
        names = price_list.names()
        return contract.ActivityLegendSettings(
            codes=[
                contract.ActivityCodeSentence(
                    id=code.id, spellings=code_spellings(code), sentence=code_effects(code, names), code=form_of(code)
                )
                for code in view.shown.codes
            ],
            problem=None if view.problem is None else SettingProblem(field=view.problem.place, message=view.problem.sentence),
            columns=[_column(letter, names) for letter in COLUMNS],
            amount_column=_column(AMOUNT_COLUMN, names),
            fill_columns=[_column(letter, names) for letter in FILL_COLUMNS],
        )

    def saved(edit: contract.ActivityCodeEdit) -> contract.ActivityLegendSaved:
        """Zapis zmiany przez właściciela Ustawień na bieżącej wartości pliku legendy, z jego sprawdzeniem legendy."""

        _known_code(edit, settings.activity_legend())
        match settings.change_legend(edit):
            case Saved(change=change):
                return contract.ActivityLegendSaved(activity_legend=described(), change=change)
            case Refused(problem=problem):
                raise refusal.setting_refused(problem)
            case NotSaved(unreadable=str(file)):
                raise refusal.settings_file_unreadable(file)
            case NotSaved():
                raise refusal.settings_not_saved()

    @router.get("/activity-legend", operation_id="getActivityLegend")
    def read() -> contract.ActivityLegendSettings:
        return described()

    @router.post("/activity-legend", operation_id="addActivityCode", responses=_REFUSED)
    def add(code: contract.ActivityCodeForm) -> contract.ActivityLegendSaved:
        return saved(contract.AddActivityCode(kind="add", code=code))

    @router.put("/activity-legend/{code_id:path}", operation_id="changeActivityCode", responses=_UNKNOWN_OR_REFUSED)
    def change(code_id: str, code: contract.ActivityCodeForm) -> contract.ActivityLegendSaved:
        return saved(contract.ChangeActivityCode(kind="change", code_id=code_id, code=code))

    @router.delete("/activity-legend/{code_id:path}", operation_id="removeActivityCode", responses=_UNKNOWN_OR_REFUSED)
    def remove(code_id: str) -> contract.ActivityLegendSaved:
        return saved(contract.RemoveActivityCode(kind="remove", code_id=code_id))

    @router.post("/activity-legend/preview", operation_id="previewActivityLegend", responses=_UNKNOWN_OR_REFUSED)
    def preview_change(edit: contract.ActivityCodeEdit) -> contract.LegendPreview:
        """Skutek zmiany na ostatnich Plikach zbiorczych po Przebiegu rozliczeń, bez zapisu (``activity_legend_preview``);
        legendę po zmianie i odmowę daje właściciel tą samą drogą co zapis (``CentrumSettings.legend_after``)."""

        view = settings.activity_legend()
        _known_code(edit, view)
        after = settings.legend_after(edit)
        if isinstance(after, NotSaved):
            match after:
                case NotSaved(unreadable=str(file)):
                    raise refusal.settings_file_unreadable(file)
                case NotSaved():
                    raise refusal.settings_not_saved()
        if isinstance(after, FieldProblem):
            raise refusal.setting_refused(after)
        directory = settings.folders().periods_directory_to_read
        if directory is None:
            return contract.LegendPreviewWithoutFiles(state="no_periods_directory")
        found = recent.read(directory)
        if not found.files and not found.unread:
            return contract.LegendPreviewWithoutFiles(state="no_settled_periods")
        rules = settings.quantity_rules().rules
        return legend_preview(settings.counted_activity_legend(), after, rules, found, price_list.names(), forbidden)

    return router


def _known_code(edit: contract.ActivityCodeEdit, view: ActivityLegendView) -> None:
    """409, gdy system nie daje teraz czytać pliku legendy, więc nie wiadomo, co w nim jest, a 404, gdy zmiana albo
    usunięcie dotyczy kodu, którego w legendzie już nie ma."""

    codes = view.codes
    if isinstance(codes, Unreadable):
        raise refusal.settings_file_unreadable(LEGEND.name)
    if isinstance(edit, contract.ChangeActivityCode | contract.RemoveActivityCode) and edit.code_id not in {code.id for code in codes}:
        raise refusal.activity_code_unknown()


def _column(letter: str, names: Mapping[str, str]) -> contract.LegendColumn:
    return contract.LegendColumn(letter=letter, name=AMOUNT_NAME if letter == AMOUNT_COLUMN else names.get(letter) or None)


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
