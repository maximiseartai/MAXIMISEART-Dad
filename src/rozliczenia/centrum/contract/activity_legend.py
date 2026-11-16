"""Kontrakt sekcji Legenda czynności okna Ustawień: Kody czynności jako zdania i formularze, kolumny do wyboru i zapis
formularza kodu (ADR 0038)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem

FillColourName = Literal["zielony", "czerwony"]
"""Kolor wypełnienia z plików taty."""


class FixedColumnForm(Model):
    """Kod wpisuje w jedną kolumnę, a liczba w zapisie nie ma znaczenia."""

    kind: Literal["fixed"]
    column: str


class RangeForm(Model):
    """Liczba z zapisu od ``low`` do ``high`` włącznie wybiera kolumnę ``column``."""

    low: int
    high: int
    column: str


class RangesForm(Model):
    """Kod wybiera kolumnę liczbą z zapisu, przedziałami („1–15 → AL, 16–30 → AJ”)."""

    kind: Literal["ranges"]
    ranges: list[RangeForm]


ColumnForm = Annotated[FixedColumnForm | RangesForm, Field(discriminator="kind")]


class FillForm(Model):
    column: str
    colour: FillColourName


class ActivityCodeForm(Model):
    """Kod czynności w formularzu: zapisy (``#`` w miejscu liczby), kolumna Ilości usług (``None``: bez kolumny) z wartością
    za jedno wystąpienie, kwota w ``AS`` (``None``: bez kwoty) i kolory wybranych kolumn. Bez kolumny wartość się nie
    liczy."""

    spellings: list[str]
    column: ColumnForm | None
    value: int
    amount: int | None
    fills: list[FillForm]


class ActivityCodeSentence(Model):
    """Kod czynności jako jedno zdanie „zapisy: co wyznacza.”: ``spellings`` to zapisy (``#`` w miejscu liczby, inne
    po „też”), a ``sentence`` to, co wyznacza, z kolumnami nazwanymi z cennika; ``code`` to ten sam kod jako formularz."""

    id: str
    spellings: str
    sentence: list[SentencePart]
    code: ActivityCodeForm


class LegendColumn(Model):
    """Kolumna do wyboru w formularzu kodu z nazwą pozycji cennika z wiersza 17 Wzorca pliku zbiorczego (``None``: Wzorca
    nie da się przeczytać albo komórka jest pusta)."""

    letter: str
    name: str | None


class ActivityLegendSettings(Model):
    """Legenda czynności, którą liczy następne Przygotowanie pliku zbiorczego, w kolejności z pliku. ``problem``: złe
    ustawienie w pliku, a wtedy pokazana jest legenda, którą Centrum liczy mimo to (ostatnia dobra albo z Wydania).
    ``columns``: kolumny, w które kod wpisuje Ilość usług, ``amount_column``: kolumna kwoty (``AS``), a ``fill_columns``:
    kolumny, które kod wypełnia kolorem."""

    codes: list[ActivityCodeSentence]
    problem: SettingProblem | None
    columns: list[LegendColumn]
    amount_column: LegendColumn
    fill_columns: list[LegendColumn]


class ActivityLegendSaved(Model):
    """Legenda czynności po zapisie formularza kodu; ``change``: id wiersza Historii Ustawień („Zapisano · Cofnij”),
    ``None``: zapis niczego nie zmienił."""

    activity_legend: ActivityLegendSettings
    change: str | None


class AddActivityCode(Model):
    kind: Literal["add"]
    code: ActivityCodeForm


class ChangeActivityCode(Model):
    kind: Literal["change"]
    code_id: str
    code: ActivityCodeForm


class RemoveActivityCode(Model):
    kind: Literal["remove"]
    code_id: str


ActivityCodeEdit = Annotated[AddActivityCode | ChangeActivityCode | RemoveActivityCode, Field(discriminator="kind")]
"""Zmiana Legendy czynności z formularza kodu."""
