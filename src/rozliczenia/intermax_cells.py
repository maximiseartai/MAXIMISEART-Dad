"""Zapis komórek Wpisania raportów do INTERMAX bez Kopii INTERMAX (ADR 0028).

Operacją jest ``write_cells``: dostaje Rejestr zleceń przeczytany przez proces (``register_file.read``) i zmiany komórek
z rdzenia Wpisania raportów (``report_cells.CellChange``). Najpierw odrzuca całość, gdy którakolwiek zmiana nie trafia
w ``SKUTECZNE`` albo ``CZYNNOŚCI ZREALIZOWANE`` uporządkowanego wiersza zlecenia (``CellProblem``), a INTERMAX zostaje
wtedy nietknięty. Inaczej bajty z tylko tymi komórkami (``intermax_file.with_cells``) zastępują INTERMAX tą samą
podmianą co Uporządkowanie INTERMAX, bez Kopii (``intermax_replace.replace_without_copy``), z odczytem kontrolnym
``intermax_file.check_cells``. Podmiana porównuje INTERMAX z bajtami, które proces przeczytał, więc zmiana pracownika
wgrana przez OneDrive w przerwie przed ponowną próbą daje odmowę, a nie zostaje nadpisana.

Uporządkowany wiersz to wiersz z wyglądem uporządkowanego dnia (``raw_orders.look``) w arkuszu zleceń z obszarem
wklejania: Surowego zlecenia, pustego wiersza, wiersza nagłówków i arkusza starszego układu Wpisanie raportów nie
zmienia.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from . import intermax_file, raw_orders
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting, replace_without_copy
from .raw_orders import RowLook
from .register_columns import COMPLETED, SUCCESSFUL, Column
from .register_file import OrderSheets, PasteArea, RegisterFile
from .report_cells import CellChange, ReportColumn

__all__ = ["CellProblem", "CellsWritten", "Rejected", "write_cells"]

_COLUMNS: Final[Mapping[ReportColumn, Column]] = {
    ReportColumn.SUCCESSFUL: SUCCESSFUL,
    ReportColumn.COMPLETED: COMPLETED,
}
_LONGEST: Final = 32767
"""Najwięcej znaków, które Excel przyjmuje w komórce."""
_NOT_IN_XML: Final = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
"""Znak, którego XML 1.0 nie przyjmuje w treści, więc Excel nie otworzyłby INTERMAX z nim w komórce."""


class CellProblem(Enum):
    """Powód, przez który zmiana komórki nie trafia do INTERMAX."""

    NOT_ORDERED = "wiersz nie jest uporządkowanym wierszem zlecenia"
    """Arkusz nie jest arkuszem zleceń z obszarem wklejania albo wiersza w nim nie ma, jest pusty, jest wierszem
    nagłówków albo Surowym zleceniem."""
    NOT_REPORT_COLUMN = "kolumna spoza SKUTECZNE i CZYNNOŚCI ZREALIZOWANE"
    REPEATED = "ta sama komórka więcej niż raz"
    UNWRITABLE_TEXT = "tekst, którego komórka nie przyjmie"
    """Znak spoza XML albo więcej niż 32767 znaków."""


@dataclass(frozen=True)
class Rejected:
    """Zmiany, których INTERMAX nie dostał, każda z powodem; żadna inna zmiana też nie trafiła do INTERMAX."""

    problems: tuple[tuple[CellChange, CellProblem], ...]


@dataclass(frozen=True)
class CellsWritten:
    """INTERMAX ma wszystkie zmiany; ``count``: ile komórek (0: INTERMAX nietknięty)."""

    count: int


def write_cells(
    register: RegisterFile,
    changes: Sequence[CellChange],
    *,
    waiting: Waiting,
    disk: Disk = LOCAL_DISK,
) -> CellsWritten | Rejected | Refusal:
    """Wpisuje ``changes`` do INTERMAX ``register`` bez Kopii INTERMAX albo nie zmienia go wcale.

    ``Rejected`` przed zapisem, gdy którakolwiek zmiana nie trafia w komórkę raportu uporządkowanego wiersza, a
    ``Refusal`` podmiany (Excel, OneDrive, nieudany albo niezgodny zapis) tak samo jak w Uporządkowaniu INTERMAX.
    ``UnsupportedShape``, gdy komórka ma formułę, leży w scaleniu albo wierszy arkusza nie da się rozdzielić, a
    ``WorkbookError``, gdy stylów INTERMAX nie da się odczytać; INTERMAX zostaje wtedy nietknięty.
    """

    cells, problems = _cells(register, changes)
    if problems:
        return Rejected(problems)
    if not changes:
        return CellsWritten(0)

    def written_as_planned(written: bytes) -> None:
        intermax_file.check_cells(register, written, cells)

    content = intermax_file.with_cells(register, cells)
    refusal = replace_without_copy(
        register.path, register.content, content, written_as_planned, waiting=waiting, disk=disk
    )
    return CellsWritten(len(changes)) if refusal is None else refusal


def _cells(
    register: RegisterFile, changes: Sequence[CellChange]
) -> tuple[intermax_file.Cells, tuple[tuple[CellChange, CellProblem], ...]]:
    """Komórki do zapisu po obszarach wklejania i zmiany odrzucone z powodem."""

    sheets = register.order_sheets.sheets if isinstance(register.order_sheets, OrderSheets) else ()
    areas = {sheet.name: (sheet.paste, sheet.positions) for sheet in sheets if sheet.paste is not None}
    ordered = {name: _ordered_rows(area, changes) for name, (area, _) in areas.items()}
    cells: dict[PasteArea, dict[tuple[int, int], str]] = {}
    problems: list[tuple[CellChange, CellProblem]] = []
    for change in changes:
        found = areas.get(change.order.sheet)
        column = _COLUMNS.get(change.column)
        if found is None or change.order.row not in ordered[change.order.sheet]:
            problems.append((change, CellProblem.NOT_ORDERED))
        elif column is None:
            problems.append((change, CellProblem.NOT_REPORT_COLUMN))
        elif len(change.value) > _LONGEST or _NOT_IN_XML.search(change.value):
            problems.append((change, CellProblem.UNWRITABLE_TEXT))
        else:
            area, positions = found
            target = cells.setdefault(area, {})
            cell = (change.order.row, positions[column])
            if cell in target:
                problems.append((change, CellProblem.REPEATED))
            target[cell] = change.value
    return cells, tuple(problems)


def _ordered_rows(area: PasteArea, changes: Sequence[CellChange]) -> frozenset[int]:
    """Uporządkowane wiersze obszaru ``area`` od dołu do najwyższego wiersza, który ``changes`` w nim zmieniają."""

    wanted = [change.order.row for change in changes if change.order.sheet == area.sheet]
    if not wanted:
        return frozenset()
    highest = min(wanted)
    ordered: set[int] = set()
    for facts in area.rows_from_bottom():
        if facts.number < highest:
            break
        if raw_orders.look(facts, area.columns) is RowLook.ORDERED:
            ordered.add(facts.number)
    return frozenset(ordered)
