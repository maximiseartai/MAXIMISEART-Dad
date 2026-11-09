"""Zmiana komórki Wpisania raportów: którą komórkę uporządkowanego zlecenia w INTERMAX i na jaki tekst zmienić.

Rdzeń Wpisania raportów zwraca listę takich zmian bez Excela, a zapis do INTERMAX (``intermax_cells.write_cells``)
przyjmuje tylko ją (ADR 0028). Moduł nie zna skoroszytu, więc rdzeń może go brać i w chmurze (#1161).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["CellChange", "OrderRow", "ReportColumn"]


class ReportColumn(Enum):
    """Kolumna, którą Wpisanie raportów zmienia, nazwana nagłówkiem INTERMAX; innej nie zmienia."""

    SUCCESSFUL = "SKUTECZNE"
    COMPLETED = "CZYNNOŚCI ZREALIZOWANE"


@dataclass(frozen=True)
class OrderRow:
    """Wiersz zlecenia w arkuszu zleceń INTERMAX: nazwa arkusza i numer wiersza (od 1)."""

    sheet: str
    row: int


@dataclass(frozen=True)
class CellChange:
    """Komórka ``column`` zlecenia ``order`` dostaje tekst ``value``."""

    order: OrderRow
    column: ReportColumn
    value: str
