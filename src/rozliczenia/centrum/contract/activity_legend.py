"""Kontrakt sekcji Legenda czynności okna Ustawień: Kody czynności jako zdania i formularze, kolumny do wyboru i zapis
formularza kodu (ADR 0038)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.quantity_rules import PreviewFile, SentencePart
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
    za jedno wystąpienie, kwota w ``AS`` (``None``: bez kwoty), kolory wybranych kolumn i to, czy kod liczy się w usterce
    (``counts_in_fault``). Bez kolumny wartość się nie liczy."""

    spellings: list[str]
    column: ColumnForm | None
    value: int
    amount: int | None
    fills: list[FillForm]
    counts_in_fault: bool


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


class LegendPreviewValue(Model):
    """Wartość komórki (Ilość usług w kolumnie albo kwota w ``AS``) po zmianie inna niż u taty: ``legend`` to Reguły ilości
    i legenda razem, tak jak wpisze je Przygotowanie, a ``tata`` wpis taty (liczba albo „nieliczbowa”)."""

    kind: Literal["value"]
    column: str
    name: str | None
    legend: int
    tata: int | Literal["nieliczbowa"]


class LegendPreviewFill(Model):
    """Kolor wypełnienia kolumny po zmianie inny niż u taty; ``None``: bez koloru legendy."""

    kind: Literal["fill"]
    column: str
    name: str | None
    legend: FillColourName | None
    tata: FillColourName | None


LegendPreviewCell = Annotated[LegendPreviewValue | LegendPreviewFill, Field(discriminator="kind")]


class LegendPreviewRow(Model):
    """Wiersz danych, w którym po zmianie legenda da inaczej niż wpisał tata: okres, numer wiersza Pliku zbiorczego, opis
    technika (``CZYNNOŚCI ZREALIZOWANE``) po strażniku reguły danych, Kody czynności z opisu z kodami bez Błędu opisu,
    powody Błędu opisu bez tekstu technika (puste bez błędu) i komórki różne od taty. Bez adresu, numeru zlecenia i daty dziennej."""

    period: str
    row: int
    description: str
    codes: list[str]
    problems: list[str]
    cells: list[LegendPreviewCell]


class LegendPreviewReady(Model):
    """Skutek zmiany Legendy czynności na Wierszach danych ostatnich Plików zbiorczych po Przebiegu rozliczeń, tym samym
    rachunkiem wiersza co Kontrola ilości.

    ``unread``: okresy, których Pliku zbiorczego nie dało się przeczytać. ``changed``: wiersze, w których legenda wpisze
    co innego (Ilości usług, kwotę w ``AS`` albo kolory), z czego ``changed_as_tata`` będzie tak, jak wpisał tata.
    ``differences_before`` i ``differences_after``: różnice legendy Kontroli ilości tych plików teraz i po zmianie, a
    ``errors_before`` i ``errors_after``: wiersze z Błędem opisu teraz i po zmianie. ``rows``: zmienione wiersze z różnicą
    od taty albo z Błędem opisu, najwyżej ``SHOWN_ROWS``, a ``more`` reszta."""

    state: Literal["ready"]
    files: list[PreviewFile]
    unread: list[str]
    changed: int
    changed_as_tata: int
    differences_before: int
    differences_after: int
    errors_before: int
    errors_after: int
    rows: list[LegendPreviewRow]
    more: int


class LegendPreviewWithoutFiles(Model):
    """Podglądu nie ma na czym policzyć: folder okresów nie jest wskazany (``no_periods_directory``) albo żaden okres nie
    ma jeszcze Rozliczeń pracowników (``no_settled_periods``)."""

    state: Literal["no_periods_directory", "no_settled_periods"]


LegendPreview = Annotated[LegendPreviewReady | LegendPreviewWithoutFiles, Field(discriminator="state")]
