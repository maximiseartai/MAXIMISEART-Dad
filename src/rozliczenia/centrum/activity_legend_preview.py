from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from rozliczenia.activity_legend import AMOUNT_COLUMN, ActivityLegend, DescriptionError, DescriptionRead, FillColour, WithCodes, problem_text
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
    if not isinstance(read, WithCodes):
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
        codes=list(dict.fromkeys(found.code for found in read.found)) if isinstance(read, WithCodes) else [],
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
