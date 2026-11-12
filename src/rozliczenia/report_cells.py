"""Zmiany Wpisania raportów w INTERMAX: którą komórkę uporządkowanego zlecenia zmienić na jaki tekst, które zlecenie
przenieść do którego Wykonawcy (Przeniesienie zlecenia) i które dopisać (Zlecenie dopisane z raportu, ADR 0029).

Rdzeń Wpisania raportów zwraca listy takich zmian bez Excela, a zapis do INTERMAX (``intermax_cells.write_cells``)
przyjmuje tylko je (ADR 0028). Moduł nie zna skoroszytu, więc rdzeń może go brać i w chmurze (#1161).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

__all__ = ["CellChange", "OrderAdded", "OrderMove", "OrderRow", "ReportColumn"]


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


@dataclass(frozen=True)
class OrderMove:
    """Przeniesienie zlecenia: wiersz ``order``, tak jak go przeczytał proces, przed zmianami kliknięcia, dostaje w
    ``WYKONAWCA`` tekst ``worker`` i staje pod ostatnim zleceniem tego Wykonawcy w dniu ``day``, a gdy Wykonawca nie ma
    w tym dniu segmentu, w nowym segmencie na jego miejscu w kolejności alfabetycznej. Na inny dzień niż dzień
    zlecenia zapis zmienia też dzień w ``DATA GODZ. POCZ.``, a godzina zostaje."""

    order: OrderRow
    day: date
    worker: str


@dataclass(frozen=True)
class OrderAdded:
    """Zlecenie dopisane z raportu: nowy wiersz w arkuszu zleceń ``sheet`` pod ostatnim zleceniem Wykonawcy ``worker``
    (tekst ``WYKONAWCA``) w dniu ``day``, a gdy Wykonawca nie ma w tym dniu segmentu, w nowym segmencie na jego miejscu
    w kolejności alfabetycznej. Wiersz ma tylko ``NUMER ZL.`` ``number`` (same cyfry), dzień w ``DATA GODZ. POCZ.``,
    ``WYKONAWCA``, ``SKUTECZNE`` ``successful`` (``tak`` albo ``nie``) i ``CZYNNOŚCI ZREALIZOWANE`` ``completed``
    (``None``: pusta); resztę uzupełnia tata."""

    sheet: str
    day: date
    worker: str
    number: str
    successful: str
    completed: str | None
