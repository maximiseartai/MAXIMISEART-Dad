"""Podgląd zmiany Legendy czynności przed zapisem (ADR 0038, US 45–46): skutek na Wierszach danych ostatnich Plików
zbiorczych po Przebiegu rozliczeń, tym samym rachunkiem wiersza co Kontrola ilości.

Pliki to te same ostatnie Pliki zbiorcze co w podglądzie zmiany Reguł ilości (``quantity_rules_preview.Recent``),
przeczytane jego odczytem; plik, którego nie da się przeczytać, podgląd pomija i nazywa jego okres. Jedyny rachunek
wiersza to ``quantity_check.legend_row_check`` na treści wiersza po filtrze prywatności (``OrderFacts``), dla legendy
teraz i po zmianie, z Regułami ilości, którymi liczy następne Uruchomienie. ``differences_after`` to suma jego różnic na
każdym pliku, więc liczba różnic legendy, którą Kontrola ilości dałaby tym plikom po zmianie; ``errors_before`` i
``errors_after`` liczą osobno wiersze z Błędem opisu. Wiersz zmienia się, gdy legenda wpisze w nim co innego: inne
Ilości usług, kwotę w ``AS`` albo kolory (``CodesOnly`` rachunku; wiersz bez kodów i z Błędem opisu nie dostaje nic).
Będzie tak, jak wpisał tata, gdy rachunek po zmianie nie oddaje opisu technika: wiersz nie ma różnicy legendy ani
Błędu opisu, a bez kodów wpisu taty w kolumnie z opisu technika albo w ``AS``. Wiersz bez kodów albo z Błędem opisu
pokazuje wpis taty jako komórki, w które legenda nic nie wpisze, a wiersz z Błędem opisu także jego powody.

Odpowiedź idzie do przeglądarki taty, więc ma tylko numer wiersza, Kody czynności, komórki, powody Błędu opisu bez
tekstu technika (``problem_text``) i opis technika, który rachunek oddaje tylko w wierszu z różnicą albo z Błędem opisu;
opis przechodzi przez strażnika reguły danych (ADR 0025) z pamięcią pracy Centrum, która zna każdą wartość ``ADRES`` i
numer Orange przeczytanych plików. Nigdy adresu, numeru zlecenia ani daty dziennej.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from rozliczenia.activity_legend import AMOUNT_COLUMN, ActivityLegend, CodesOnly, DescriptionError, DescriptionRead, FillColour, problem_text
from rozliczenia.centrum.contract import activity_legend as contract
from rozliczenia.centrum.contract.quantity_rules import PreviewFile
from rozliczenia.centrum.legend_forms import colour_name
from rozliczenia.centrum.legend_sentences import AMOUNT_NAME
from rozliczenia.centrum.quantity_rules_preview import SHOWN_ROWS, Recent
from rozliczenia.client_data import ForbiddenValues, guarded
from rozliczenia.quantity_check import FillDifference, LegendDifference, LegendRowCheck, ValueDifference, legend_row_check
from rozliczenia.quantity_engine import QuantityRules

_PLACE: Final = "podgląd Legendy czynności"


def legend_preview(
    before: ActivityLegend,
    after: ActivityLegend,
    rules: QuantityRules,
    recent: Recent,
    names: Mapping[str, str],
    forbidden: ForbiddenValues,
) -> contract.LegendPreviewReady:
    """Skutek zmiany legendy ``before`` → ``after`` na plikach ``recent`` z Regułami ilości ``rules``; ``names``: litera
    kolumny → nazwa pozycji cennika."""

    changed = changed_as_tata = differences_before = differences_after = errors_before = errors_after = more = 0
    rows: list[contract.LegendPreviewRow] = []
    for file in recent.files:
        for numbered in file.orders.rows:
            old, new = legend_row_check(numbered.order, before, rules), legend_row_check(numbered.order, after, rules)
            differences_before += len(old.differences)
            differences_after += len(new.differences)
            errors_before += isinstance(old.read, DescriptionError)
            errors_after += isinstance(new.read, DescriptionError)
            if _written(old.read) == _written(new.read):
                continue
            changed += 1
            if new.description is None:
                changed_as_tata += 1
            elif len(rows) < SHOWN_ROWS:
                rows.append(_row(file.period, numbered.number, new, names, forbidden))
            else:
                more += 1
    return contract.LegendPreviewReady(
        state="ready",
        files=[PreviewFile(period=file.period, rows=len(file.orders.rows)) for file in recent.files],
        unread=list(recent.unread),
        changed=changed,
        changed_as_tata=changed_as_tata,
        differences_before=differences_before,
        differences_after=differences_after,
        errors_before=errors_before,
        errors_after=errors_after,
        rows=rows,
        more=more,
    )


def _written(read: DescriptionRead) -> object:
    """To, co legenda wpisze w wierszu Pliku zbiorczego: Ilości usług, kwota w ``AS`` i kolory."""

    if not isinstance(read, CodesOnly):
        return ({}, 0, {})
    return (dict(read.quantities), read.amount, dict(read.fills))


def _row(
    period: str, number: int, checked: LegendRowCheck, names: Mapping[str, str], forbidden: ForbiddenValues
) -> contract.LegendPreviewRow:
    assert checked.description is not None, "wiersz z różnicą legendy ma opis technika"
    read = checked.read
    return contract.LegendPreviewRow(
        period=period,
        row=number,
        description=guarded(forbidden, checked.description, _PLACE).text,
        codes=list(dict.fromkeys(found.code for found in read.found)) if isinstance(read, CodesOnly) else [],
        problems=list(dict.fromkeys(problem_text(problem) for problem in read.problems)) if isinstance(read, DescriptionError) else [],
        cells=[
            *(_cell(difference, names) for difference in checked.differences),
            *(_cell(ValueDifference(column, 0, tata), names) for column, tata in checked.entry),
        ],
    )


def _cell(difference: LegendDifference, names: Mapping[str, str]) -> contract.LegendPreviewCell:
    name = AMOUNT_NAME if difference.column == AMOUNT_COLUMN else names.get(difference.column) or None
    if isinstance(difference, FillDifference):
        return contract.LegendPreviewFill(
            kind="fill", column=difference.column, name=name, legend=_colour(difference.legend), tata=_colour(difference.tata)
        )
    return contract.LegendPreviewValue(
        kind="value", column=difference.column, name=name, legend=difference.legend, tata=difference.tata
    )


def _colour(colour: FillColour | None) -> contract.FillColourName | None:
    return None if colour is None else colour_name(colour)
