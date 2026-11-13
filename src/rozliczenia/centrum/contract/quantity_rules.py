"""Kontrakt sekcji Reguły ilości i Urządzenia okna Ustawień: reguły jako zdania „jeśli … to …”, Lista Urządzeń, edytor
reguły (formularz, zapis) i podgląd zmiany na ostatnich Plikach zbiorczych (ADR 0033)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.settings_workers import SettingProblem


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

DeviceGroup = Literal["router", "tv", "extender"]


class ComponentCondition(Model):
    """``URZĄDZENIA`` zawierają składnik Listy Urządzeń (``component``: jego id)."""

    kind: Literal["component"]
    component: str
    negated: bool


DevicesMode = Literal["empty", "exactly", "contains"]


class DevicesCondition(Model):
    """``URZĄDZENIA`` są puste, są dokładnie tekstem albo zawierają tekst (przy ``empty`` tekst jest pusty)."""

    kind: Literal["devices"]
    mode: DevicesMode
    text: str
    negated: bool


class ActivitiesCondition(Model):
    kind: Literal["activities"]
    text: str
    negated: bool


class ContractCondition(Model):
    """Pierwsze słowo ``UMOWA`` jest tym słowem."""

    kind: Literal["contract"]
    word: str
    negated: bool


class DateCondition(Model):
    """``DATA`` przypada w dni tygodnia (0 to poniedziałek) od godziny ``since`` (``GG:MM``)."""

    kind: Literal["date"]
    days: list[int]
    since: str
    negated: bool


class GroupCondition(Model):
    kind: Literal["group"]
    group: DeviceGroup
    negated: bool


RuleCondition = Annotated[
    ComponentCondition | DevicesCondition | ActivitiesCondition | ContractCondition | DateCondition | GroupCondition,
    Field(discriminator="kind"),
]

RuleMultiplier = Literal["once", "component", "pieces"]
"""Wartość raz na zlecenie, razy liczba składnika albo razy „N szt” z ``CZYNNOŚCI`` za każde wystąpienie składnika."""


class RuleWrite(Model):
    column: str
    value: int
    multiplier: RuleMultiplier
    component: str | None
    """Składnik mnożnika ``component`` i ``pieces``; przy ``once`` brak."""


class FillAction(Model):
    kind: Literal["fill"]
    writes: list[RuleWrite]


class NothingAction(Model):
    """Nic nie wpisuj w tym zleceniu: zlecenie rozliczane z opisu."""

    kind: Literal["nothing"]


class LeaveEmptyAction(Model):
    """Zostaw kolumny puste w Rozliczeniu pracownika (Ilości tylko dla INEA)."""

    kind: Literal["leave_empty"]
    columns: list[str]


RuleAction = Annotated[FillAction | NothingAction | LeaveEmptyAction, Field(discriminator="kind")]


class RuleForm(Model):
    """Reguła ilości w edytorze: zakres, warunki („ale nie gdy”: ``negated``) i działanie. ``action`` ``None``: tata nie
    wybrał działania, więc zapis to odmowa z polem ``to``."""

    scope: RuleScope
    conditions: list[RuleCondition]
    action: RuleAction | None


class QuantityRuleSentence(Model):
    """Reguła ilości jako zdanie „jeśli … to …”, poskładane z tekstu i kolumn, w kolejności z pliku reguł, i jako
    formularz edytora (``rule``)."""

    id: str
    scope: RuleScope
    sentence: list[SentencePart]
    rule: RuleForm


class DeviceComponent(Model):
    """Składnik Listy Urządzeń: nazwa (pierwszy zapis), inne zapisy tej samej rzeczy i grupa (``None``: żadna)."""

    id: str
    name: str
    other_spellings: list[str]
    group: DeviceGroup | None


class ComponentForm(Model):
    """Składnik w formularzu sekcji Urządzenia: nazwa (pierwszy zapis), inne zapisy i grupa (``None``: żadna). Zapisy
    Centrum zapisuje tak, jak Reguły ilości czytają słowa ``URZĄDZENIA``: małymi literami, przecinki jak spacje, bez
    ``xg``."""

    name: str
    other_spellings: list[str]
    group: DeviceGroup | None


class DeviceSuggestion(Model):
    """Zapis z ``URZĄDZENIA`` zleceń bez reguły w ostatnich Plikach zbiorczych, którego Lista Urządzeń nie zna;
    ``orders``: w ilu takich zleceniach jest."""

    spelling: str
    orders: int


class DeviceSuggestions(Model):
    """Podpowiedzi sekcji Urządzenia, od najczęstszej, najwyżej ``SHOWN_SUGGESTIONS``; ``unread``: okresy, których Pliku
    zbiorczego nie dało się przeczytać. Bez folderu okresów albo okresu po Przebiegu rozliczeń lista jest pusta."""

    suggestions: list[DeviceSuggestion]
    unread: list[str]


class RuleColumn(Model):
    """Kolumna Ilości usług ``N:AP`` z nazwą pozycji cennika (``None``: Wzorca nie da się przeczytać albo komórka jest
    pusta); ``writable`` fałszywe dla kolumn, które liczy narzędzie samo (P, Q, S): reguła może je tylko zostawić puste."""

    letter: str
    name: str | None
    writable: bool


class QuantityRulesSettings(Model):
    """Reguły ilości i Lista Urządzeń, którymi liczy następne Przygotowanie pliku zbiorczego. ``rules_problem`` i
    ``devices_problem``: złe ustawienie w pliku, a wtedy pokazane są reguły, którymi Centrum liczy mimo to;
    ``devices_problem`` przy dobrej liście mówi też o składniku z Wydania, którego zapisy ma lista, więc reguły z Wydania
    liczą bez niego."""

    rules: list[QuantityRuleSentence]
    devices: list[DeviceComponent]
    columns: list[RuleColumn]
    rules_problem: SettingProblem | None
    devices_problem: SettingProblem | None


class QuantityRulesSaved(Model):
    """Reguły ilości po zapisie z edytora reguły albo sekcji Urządzenia; ``change``: id wiersza Historii Ustawień („Zapisano · Cofnij”), ``None``:
    zapis niczego nie zmienił."""

    quantity_rules: QuantityRulesSettings
    change: str | None


class AddRule(Model):
    kind: Literal["add"]
    rule: RuleForm


class ChangeRule(Model):
    kind: Literal["change"]
    rule_id: str
    rule: RuleForm


class RemoveRule(Model):
    kind: Literal["remove"]
    rule_id: str


RuleEdit = Annotated[AddRule | ChangeRule | RemoveRule, Field(discriminator="kind")]
"""Zmiana Reguł ilości, której skutek pokazuje podgląd przed zapisem."""


class PreviewFile(Model):
    """Plik zbiorczy okresu ``period`` po Przebiegu rozliczeń w podglądzie; ``rows``: jego Wiersze danych."""

    period: str
    rows: int


class PreviewCell(Model):
    """Kolumna wiersza w podglądzie: ilość z Reguł ilości teraz (``before``) i po zmianie (``after``) oraz wpis taty
    (liczba albo „nieliczbowa”)."""

    column: str
    name: str | None
    before: int
    after: int
    tata: int | Literal["nieliczbowa"]


class SummedRule(Model):
    id: str
    sentence: list[SentencePart]


class PreviewSum(Model):
    """Kolumna, w którą po zmianie wpisało w tym wierszu kilka reguł, z sumą i tymi regułami („Z = 2, bo reguły A i B”)."""

    column: str
    name: str | None
    total: int
    rules: list[SummedRule]


class PreviewRow(Model):
    """Wiersz danych, w którym po zmianie reguła da inaczej niż wpisał tata: okres, numer wiersza Pliku zbiorczego,
    ``URZĄDZENIA``, ``CZYNNOŚCI``, dzień tygodnia z pełną godziną (``when``, np. „pt 16”) i kolumny. Bez adresu, numeru
    zlecenia, ``UMOWA`` i daty dziennej."""

    period: str
    row: int
    devices: str
    activities: str
    when: str
    cells: list[PreviewCell]
    sums: list[PreviewSum]


class PreviewReady(Model):
    """Skutek zmiany Reguł ilości na Wierszach danych ostatnich Plików zbiorczych po Przebiegu rozliczeń, tym samym
    rachunkiem co Kontrola ilości.

    ``sentence``: zdanie reguły po zmianie (``None`` przy usunięciu). ``unread``: okresy, których Pliku zbiorczego nie
    dało się przeczytać. ``changed``: wiersze, w których zmienią się ilości z Reguł ilości (albo kolumny zostawione
    puste), z czego ``changed_as_tata`` będzie tak, jak wpisał tata. ``differences_before`` i ``differences_after``:
    różnice Kontroli ilości tych plików teraz i po zmianie. ``rows``: zmienione wiersze z różnicą od taty, najwyżej
    ``SHOWN_ROWS``, a ``more`` reszta."""

    state: Literal["ready"]
    sentence: list[SentencePart] | None
    files: list[PreviewFile]
    unread: list[str]
    changed: int
    changed_as_tata: int
    differences_before: int
    differences_after: int
    rows: list[PreviewRow]
    more: int


class PreviewWithoutFiles(Model):
    """Podglądu nie ma na czym policzyć: folder okresów nie jest wskazany (``no_periods_directory``) albo żaden okres nie
    ma jeszcze Rozliczeń pracowników (``no_settled_periods``)."""

    state: Literal["no_periods_directory", "no_settled_periods"]
    sentence: list[SentencePart] | None


RulesPreview = Annotated[PreviewReady | PreviewWithoutFiles, Field(discriminator="state")]
