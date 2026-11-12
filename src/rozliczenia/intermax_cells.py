"""Zapis komórek, Przeniesień zleceń i Zleceń dopisanych z raportu Wpisania raportów do INTERMAX bez Kopii INTERMAX
(ADR 0028, ADR 0029).

Operacją jest ``write_cells``: dostaje Rejestr zleceń przeczytany przez proces (``register_file.read``), zmiany komórek
(``report_cells.CellChange``), Przeniesienia zleceń (``report_cells.OrderMove``) i Zlecenia dopisane z raportu
(``report_cells.OrderAdded``) z rdzenia Wpisania raportów. Najpierw odrzuca całość, gdy którakolwiek zmiana nie trafia
w ``SKUTECZNE`` albo ``CZYNNOŚCI ZREALIZOWANE`` uporządkowanego wiersza zlecenia, Przeniesienie nie zaczyna się w
uporządkowanym wierszu, dopisanie idzie do arkusza bez obszaru wklejania albo z tekstem, którego komórka nie przyjmie,
albo Przeniesienie lub dopisanie idzie na dzień bez uporządkowanych zleceń w arkuszu (``CellProblem``),
a INTERMAX zostaje wtedy nietknięty. Inaczej bajty z tylko tymi komórkami, a potem z wierszami w układzie dnia z planu
Przeniesień i dopisań (``raw_orders.plan_moves``, ``intermax_file.with_cells``) zastępują INTERMAX tą samą podmianą co
Uporządkowanie INTERMAX, bez Kopii (``intermax_replace.replace_without_copy``), z odczytem kontrolnym
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
from datetime import date, datetime
from enum import Enum
from typing import Final

from . import intermax_file, raw_orders
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting, replace_without_copy
from .raw_orders import AddedRow, MissingDays, MovePlan, RowLook
from .register_columns import COMPLETED, ORDER_NUMBER, SUCCESSFUL, Column
from .register_file import OrderSheet, OrderSheets, PasteArea, RegisterFile
from .report_cells import CellChange, OrderAdded, OrderMove, ReportColumn

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
    MOVE_NOT_ORDERED = "Przeniesienie spoza uporządkowanego wiersza zlecenia"
    """Przeniesienie z wiersza, który nie jest uporządkowanym wierszem zlecenia z datą, albo drugi raz z tego samego
    wiersza."""
    NO_DAY = "Przeniesienie albo dopisanie na dzień bez uporządkowanych zleceń w arkuszu"
    """Arkusz zlecenia nie ma uporządkowanego wiersza dnia docelowego, pod który wiersz mógłby stanąć
    (``raw_orders.MissingDays``); rdzeń przenosi i dopisuje tylko do Dnia uporządkowanego arkusza."""
    ADDED_OUTSIDE = "dopisanie do arkusza bez obszaru wklejania"


@dataclass(frozen=True)
class Rejected:
    """Zmiany, Przeniesienia i dopisania, których INTERMAX nie dostał, każde z powodem; żadna inna zmiana też nie trafiła
    do INTERMAX."""

    problems: tuple[tuple[CellChange | OrderMove | OrderAdded, CellProblem], ...]


@dataclass(frozen=True)
class CellsWritten:
    """INTERMAX ma wszystkie zmiany; ``count``: ile komórek, ``moved``: ile Przeniesień zleceń, ``added``: ile Zleceń
    dopisanych z raportu (wszystkie 0: INTERMAX nietknięty)."""

    count: int
    moved: int = 0
    added: int = 0


def write_cells(
    register: RegisterFile,
    changes: Sequence[CellChange],
    moves: Sequence[OrderMove] = (),
    added: Sequence[OrderAdded] = (),
    *,
    waiting: Waiting,
    disk: Disk = LOCAL_DISK,
) -> CellsWritten | Rejected | Refusal:
    """Wpisuje ``changes``, Przeniesienia ``moves`` i Zlecenia dopisane z raportu ``added`` do INTERMAX ``register`` bez
    Kopii INTERMAX albo nie zmienia go wcale. Wiersze zmian i Przeniesień są wierszami INTERMAX ``register``: komórki
    wpisują się przed przeniesieniem wiersza, więc idą z nim, a dopisania stają po Przeniesieniach.

    ``Rejected`` przed zapisem, gdy którakolwiek zmiana nie trafia w komórkę raportu uporządkowanego wiersza,
    Przeniesienie nie zaczyna się w uporządkowanym wierszu zlecenia, dopisanie idzie do arkusza bez obszaru wklejania
    albo ma tekst, którego komórka nie przyjmie, albo Przeniesienie lub dopisanie idzie na dzień bez uporządkowanych
    zleceń w arkuszu, a ``Refusal`` podmiany
    (Excel, OneDrive, nieudany albo niezgodny zapis) tak samo jak w Uporządkowaniu INTERMAX. ``UnsupportedShape``, gdy
    komórka albo przesuwany wiersz ma formułę, komórka leży w scaleniu, zakres sięga przesuwanych wierszy albo wierszy
    arkusza nie da się rozdzielić, a ``WorkbookError``, gdy stylów INTERMAX nie da się odczytać; INTERMAX zostaje wtedy
    nietknięty.
    """

    cells, problems = _cells(register, changes)
    plans, refused = _plans(register, moves, added)
    if problems or refused:
        return Rejected((*problems, *refused))
    if not changes and not moves and not added:
        return CellsWritten(0)

    def written_as_planned(written: bytes) -> None:
        intermax_file.check_cells(register, written, cells, plans)

    content = intermax_file.with_cells(register, cells, plans)
    refusal = replace_without_copy(
        register.path, register.content, content, written_as_planned, waiting=waiting, disk=disk
    )
    return CellsWritten(len(changes), len(moves), len(added)) if refusal is None else refusal


def _plans(
    register: RegisterFile, moves: Sequence[OrderMove], added: Sequence[OrderAdded]
) -> tuple[dict[PasteArea, MovePlan], tuple[tuple[OrderMove | OrderAdded, CellProblem], ...]]:
    """Plan Przeniesień i dopisań każdego obszaru wklejania z nimi oraz Przeniesienia i dopisania odrzucone z
    powodem."""

    sheets = register.order_sheets.sheets if isinstance(register.order_sheets, OrderSheets) else ()
    areas = {sheet.name: sheet.paste for sheet in sheets if sheet.paste is not None}
    wanted: dict[PasteArea, dict[int, tuple[str, date]]] = {}
    sources: dict[PasteArea, list[OrderMove | OrderAdded]] = {}
    rows: dict[PasteArea, list[AddedRow]] = {}
    problems: list[tuple[OrderMove | OrderAdded, CellProblem]] = []
    for move in moves:
        area = areas.get(move.order.sheet)
        facts = None if area is None else _ordered_row(area, move.order.row)
        when = None if facts is None or area is None else facts.value(area.columns.date)
        if area is None or not isinstance(when, datetime) or move.order.row in wanted.get(area, {}):
            problems.append((move, CellProblem.MOVE_NOT_ORDERED))
        else:
            wanted.setdefault(area, {})[move.order.row] = (move.worker, move.day)
            sources.setdefault(area, []).append(move)
    by_sheet = {sheet.name: sheet for sheet in sheets if sheet.paste is not None}
    for order in added:
        sheet = by_sheet.get(order.sheet)
        texts = (order.worker, order.successful, order.completed or "")
        if sheet is None or sheet.paste is None:
            problems.append((order, CellProblem.ADDED_OUTSIDE))
        elif any(not _writable(text) for text in texts):
            problems.append((order, CellProblem.UNWRITABLE_TEXT))
        else:
            rows.setdefault(sheet.paste, []).append(_added_row(sheet, order))
            sources.setdefault(sheet.paste, []).append(order)
    plans: dict[PasteArea, MovePlan] = {}
    for area in {**wanted, **rows}:
        plan = raw_orders.plan_moves(area.rows_from_bottom(), area.columns, wanted.get(area, {}), rows.get(area, ()))
        if isinstance(plan, MissingDays):
            problems += [(found, CellProblem.NO_DAY) for found in sources[area] if found.day in plan.days]
        else:
            plans[area] = plan
    if problems:
        return {}, tuple(problems)
    return plans, ()


def _added_row(sheet: OrderSheet, order: OrderAdded) -> AddedRow:
    """Wiersz dopisanego zlecenia w kolumnach arkusza ``sheet``: ``NUMER ZL.`` liczbą jak numery z aplikacji firmowej
    (tekstem, gdy zaczyna się od zera, którego liczba by nie miała), ``SKUTECZNE`` i niepuste ``CZYNNOŚCI
    ZREALIZOWANE``."""

    at = sheet.positions
    number: str | int = order.number if order.number.startswith("0") else int(order.number)
    cells: dict[int, str | int] = {at[ORDER_NUMBER]: number, at[SUCCESSFUL]: order.successful}
    if order.completed is not None:
        cells[at[COMPLETED]] = order.completed
    return AddedRow(order.worker, order.day, cells)


def _writable(text: str) -> bool:
    return len(text) <= _LONGEST and not _NOT_IN_XML.search(text)


def _ordered_row(area: PasteArea, number: int) -> raw_orders.RowFacts | None:
    """Fakty uporządkowanego wiersza ``number`` obszaru ``area``; ``None``, gdy wiersza nie ma albo nie jest
    uporządkowany."""

    for facts in area.rows_from_bottom():
        if facts.number < number:
            return None
        if facts.number == number:
            return facts if raw_orders.look(facts, area.columns) is RowLook.ORDERED else None
    return None


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
        elif not _writable(change.value):
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
