"""Nienadpisywanie komórek: Wpis zmienia tylko pustą komórkę, a pamięć własnych wpisów idzie za tym, co zostało."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from ..report_cells import CellChange, ReportColumn
from ._model import OrderKey, OwnEntries, OwnEntry, RegisterOrder, ReportEntry

_COLUMNS = tuple(ReportColumn)


def reconcile(
    targets: Mapping[OrderKey, tuple[RegisterOrder, ReportEntry]], orders: Iterable[RegisterOrder], memory: OwnEntries
) -> tuple[tuple[CellChange, ...], OwnEntries]:
    """Zmiany komórek i następna pamięć.

    Każda kolumna osobno: ``tak``/``nie`` do ``SKUTECZNE``, niepusty opis do ``CZYNNOŚCI ZREALIZOWANE``, i tylko do
    pustej komórki. Pamięć to nowe zmiany oraz dawne wpisy, których komórka dalej ma zapamiętaną wartość; wartość
    ręczna równa Wpisowi do pamięci nie trafia, żeby późniejsza poprawka nie nadpisała taty.
    """

    changes: list[CellChange] = []
    own: set[OwnEntry] = set()
    for order, entry in targets.values():
        reported = {
            ReportColumn.SUCCESSFUL: None if entry.verdict is None else entry.verdict.value,
            ReportColumn.COMPLETED: entry.activities or None,
        }
        for column, value in reported.items():
            if value is not None and order.cell(column) is None:
                changes.append(CellChange(order.row, column, value))
                own.add(OwnEntry(order.key, column, value))
    current: defaultdict[tuple[OrderKey, ReportColumn], set[str | None]] = defaultdict(set)
    for order in orders:
        for column in _COLUMNS:
            current[order.key, column].add(order.cell(column))
    own.update(entry for entry in memory.entries if entry.value in current[entry.key, entry.column])
    ordered = sorted(changes, key=lambda change: (change.order.sheet, change.order.row, _COLUMNS.index(change.column)))
    return tuple(ordered), OwnEntries(frozenset(own))
