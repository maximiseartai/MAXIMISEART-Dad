"""Nienadpisywanie komórek: Wpis zmienia pustą komórkę albo nietknięty własny wpis, a ręczna wartość zostaje z różnicą."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace

from ..report_cells import CellChange, ReportColumn
from ..text import normalize_text
from ._model import Kept, ManualDifference, OrderKey, OwnEntries, OwnEntry, RegisterOrder, ReportEntry, Verdict

_COLUMNS = tuple(ReportColumn)


def reconcile(
    targets: Mapping[OrderKey, tuple[RegisterOrder, ReportEntry]],
    orders: Iterable[RegisterOrder],
    memory: OwnEntries,
    kept: frozenset[Kept],
) -> tuple[tuple[CellChange, ...], tuple[ManualDifference, ...], OwnEntries]:
    """Zmiany komórek, różnice z ręczną wartością i następna pamięć.

    Każda kolumna osobno: ``tak``/``nie`` do ``SKUTECZNE``, niepusty opis do ``CZYNNOŚCI ZREALIZOWANE``. Pusta komórka
    i komórka z zapamiętaną własną wartością dostają Wpis, komórka równa Wpisowi (``normalize_text``) zostaje, a inna
    wartość jest ręczna: zostaje z ``ManualDifference``, chyba że tata kliknął „Zostaw moją” przy tej treści Wpisu
    (``kept``). Pamięć to nowe zmiany oraz dawne wpisy, których komórka dalej ma zapamiętaną wartość, z Przeniesieniami
    z ``memory``; wartość ręczna równa Wpisowi do pamięci nie trafia, żeby późniejsza poprawka nie nadpisała taty.
    """

    remembered = {(entry.key, entry.column): entry.value for entry in memory.entries}
    current: defaultdict[tuple[OrderKey, ReportColumn], set[str | None]] = defaultdict(set)
    for order in orders:
        for column in _COLUMNS:
            current[order.key, column].add(order.cell(column))
    own = {cell: value for cell, value in remembered.items() if value in current[cell]}
    changes: list[CellChange] = []
    differences: list[ManualDifference] = []
    for order, entry in targets.values():
        reported = {
            ReportColumn.SUCCESSFUL: None if entry.verdict is None else entry.verdict.value,
            ReportColumn.COMPLETED: entry.activities or None,
        }
        for column, value in reported.items():
            cell = order.cell(column)
            if value is None or (cell is not None and normalize_text(cell) == normalize_text(value)):
                continue
            if cell is None or cell == remembered.get((order.key, column)):
                changes.append(CellChange(order.row, column, value))
                own[order.key, column] = value
            elif Kept(order.key, column, value) not in kept:
                differences.append(ManualDifference(order.key, column, cell, value))
    ordered = sorted(changes, key=lambda change: (change.order.sheet, change.order.row, _COLUMNS.index(change.column)))
    entries = frozenset(OwnEntry(key, column, value) for (key, column), value in own.items())
    return tuple(ordered), tuple(differences), OwnEntries(entries, memory.moves)


def with_added(memory: OwnEntries, added: Iterable[tuple[OrderKey, Verdict, str]]) -> OwnEntries:
    """Pamięć z wartościami, które Zlecenie dopisane z raportu pod kluczem dostaje w ``SKUTECZNE`` (``tak``/``nie``) i w
    ``CZYNNOŚCI ZREALIZOWANE`` (niepusty opis): Centrum je wpisało, więc w następnych kliknięciach poprawka Wykonawcy je
    zmienia, a ręczna wartość taty wygrywa jak przy każdej komórce."""

    entries = {(entry.key, entry.column): entry for entry in memory.entries}
    for key, verdict, activities in added:
        entries[key, ReportColumn.SUCCESSFUL] = OwnEntry(key, ReportColumn.SUCCESSFUL, verdict.value)
        if activities:
            entries[key, ReportColumn.COMPLETED] = OwnEntry(key, ReportColumn.COMPLETED, activities)
    return replace(memory, entries=frozenset(entries.values()))
