"""Kody czynności jako zdania dla taty (ADR 0038), z typów silnika ``activity_legend``.

Zdanie ma postać „zapis (też inne zapisy): co wyznacza.”, np. „spawpg: 1 w Spawanie w mufie (AB), 70 w Uwagi - kwota
(AS), AS na czerwono.”. Miejsce na liczbę w zapisie (``{n}``) to ``#``. Kolumna Ilości usług to osobna część zdania z
literą i nazwą pozycji cennika z wiersza 17 Wzorca pliku zbiorczego, którą pokazuje okno; kwota stoi zawsze w ``AS``
nazwanej „Uwagi - kwota” (nie jest pozycją cennika), a kolumna wypełnienia to sama litera. Kod z przedziałami mówi każdy
przedział: „# od 1 do 15 → 1 w … (AL)”.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, assert_never

from rozliczenia.activity_legend import AMOUNT_COLUMN, NUMBER, ActivityCode, ColumnByNumber, FillColour, FixedColumn
from rozliczenia.centrum.contract.quantity_rules import SentenceColumn, SentencePart, SentenceText

AMOUNT_NAME: Final = "Uwagi - kwota"
"""Nazwa kolumny ``AS`` w zdaniu kodu."""
SHOWN_NUMBER: Final = "#"
"""Miejsce na liczbę w zapisie pokazanym tacie."""


def code_sentence(code: ActivityCode, names: Mapping[str, str]) -> list[SentencePart]:
    """Zdanie kodu ``code``; ``names``: litera kolumny → nazwa pozycji cennika (brak albo ``""``: sama litera)."""

    first, *others = (shown_spelling(spelling) for spelling in code.spellings)
    head = f"{first} (też {', '.join(others)}): " if others else f"{first}: "
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
    parts: list[SentencePart] = [_text(head)]
    for index, effect in enumerate(effects):
        if index:
            parts.append(_text(", "))
        parts.extend(effect)
    parts.append(_text("."))
    return _merged(parts)


def shown_spelling(spelling: str) -> str:
    return spelling.replace(NUMBER, SHOWN_NUMBER)


_COLOURS: Final[Mapping[FillColour, str]] = {FillColour.GREEN: "zielono", FillColour.RED: "czerwono"}


def _text(text: str) -> SentenceText:
    return SentenceText(kind="text", text=text)


def _column(letter: str, names: Mapping[str, str]) -> SentenceColumn:
    return SentenceColumn(kind="column", letter=letter, name=names.get(letter) or None)


def _merged(parts: list[SentencePart]) -> list[SentencePart]:
    """Sąsiednie teksty sklejone w jeden."""

    merged: list[SentencePart] = []
    for part in parts:
        last = merged[-1] if merged else None
        if isinstance(part, SentenceText) and isinstance(last, SentenceText):
            merged[-1] = _text(last.text + part.text)
        else:
            merged.append(part)
    return merged
