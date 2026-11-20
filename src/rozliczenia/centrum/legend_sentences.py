from __future__ import annotations

from collections.abc import Mapping
from typing import Final, assert_never

from rozliczenia.activity_legend import AMOUNT_COLUMN, SHOWN_NUMBER, ActivityCode, ColumnByNumber, FillColour, FixedColumn, shown_spelling
from rozliczenia.centrum.contract.quantity_rules import SentenceColumn, SentencePart, SentenceText

AMOUNT_NAME: Final = "Uwagi - kwota"


def code_sentence(code: ActivityCode, names: Mapping[str, str]) -> list[SentencePart]:
    return _merged([_text(f"{code_spellings(code)}: "), *code_effects(code, names)])


def code_spellings(code: ActivityCode) -> str:
    first, *others = (shown_spelling(spelling) for spelling in code.spellings)
    return f"{first} (też {', '.join(others)})" if others else first


def code_effects(code: ActivityCode, names: Mapping[str, str]) -> list[SentencePart]:
    effects: list[list[SentencePart]] = []
    match code.column:
        case FixedColumn(column=column):
            effects.append([_text(f"{code.value} w "), _column(column, names)])
        case ColumnByNumber(ranges=ranges):
            effects.extend(
                [_text(f"{SHOWN_NUMBER} od {found.low} do {found.high} → {code.value} w "), _column(found.column, names)]
                for found in ranges
            )
        case None:
            pass
        case unknown:
            assert_never(unknown)
    if code.amount is not None:
        effects.append([_text(f"{code.amount} w "), SentenceColumn(kind="column", letter=AMOUNT_COLUMN, name=AMOUNT_NAME)])
    effects.extend(
        [SentenceColumn(kind="column", letter=fill.column, name=None), _text(f" na {_COLOURS[fill.colour]}")]
        for fill in code.fills
    )
    parts: list[SentencePart] = []
    for index, effect in enumerate(effects):
        if index:
            parts.append(_text(", "))
        parts.extend(effect)
    if not code.counts_in_fault:
        parts.append(_text("; w usterce się nie liczy"))
    parts.append(_text("."))
    return _merged(parts)


_COLOURS: Final[Mapping[FillColour, str]] = {FillColour.GREEN: "zielono", FillColour.RED: "czerwono"}


def _text(text: str) -> SentenceText:
    return SentenceText(kind="text", text=text)


def _column(letter: str, names: Mapping[str, str]) -> SentenceColumn:
    return SentenceColumn(kind="column", letter=letter, name=names.get(letter) or None)


def _merged(parts: list[SentencePart]) -> list[SentencePart]:
    merged: list[SentencePart] = []
    for part in parts:
        last = merged[-1] if merged else None
        if isinstance(part, SentenceText) and isinstance(last, SentenceText):
            merged[-1] = _text(last.text + part.text)
        else:
            merged.append(part)
    return merged
