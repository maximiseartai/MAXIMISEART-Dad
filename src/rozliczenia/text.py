"""Reguły tekstu wspólne dla wszystkich procesów: normalizacja tekstu z komórek taty i polskie formy w Komunikatach."""

from __future__ import annotations

import unicodedata

__all__ = ["normalize_text", "plural", "row_range"]


def normalize_text(value: object) -> str:
    """Normalizuje identyfikator bez usuwania polskich znaków."""

    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.replace(" ", " ").split()).casefold()


def plural(count: int, one: str, few: str, many: str) -> str:
    """Forma słowa dla liczby ``count``: ``one`` dla 1, ``few`` dla 2–4 (bez 12–14) na końcu liczby, ``many`` dla
    pozostałych, np. „różnica”, „różnice”, „różnic”."""

    if count == 1:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def row_range(first: int, last: int) -> str:
    """Kolejne wiersze arkusza: „wiersz 18” albo „wiersze 18–20”."""

    return f"wiersz {first}" if first == last else f"wiersze {first}–{last}"
