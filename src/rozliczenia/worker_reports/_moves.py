"""Przeniesienia zleceń kliknięcia: zlecenia po Przeniesieniach, operacje zapisu, pamięć Przeniesień i informacje dla taty.

Przeniesienie zlecenia (ADR 0029) zmienia Wykonawcę zlecenia w dniu zlecenia. Pamięć (``OwnMove``) mówi, gdzie Centrum
postawiło zlecenie i gdzie stało przed pierwszym Przeniesieniem Centrum, więc ręczna zmiana taty wygrywa
(``_matching._movable``), a informacje o Przeniesieniu stoją przy każdym kliknięciu, dopóki INTERMAX ma zlecenie tam,
gdzie je postawiło Centrum.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from ..report_cells import OrderMove, OrderRow
from ._model import (
    HandedOver,
    Login,
    OrderKey,
    OrderNumber,
    OwnEntries,
    OwnMove,
    RegisterOrder,
    ReportNote,
    TakenOver,
    Window,
    note_order,
)


@dataclass(frozen=True)
class Moved:
    """Kliknięcie po Przeniesieniach: zlecenia z kluczem po kliknięciu (``orders``, w kolejności wejścia), wiersze
    przeniesionych zleceń (``rows``), operacje zapisu (``moves``), pamięć własnych wpisów z kluczem po kliknięciu
    (``memory``, z nowymi Przeniesieniami) i informacje dla taty (``notes``)."""

    orders: tuple[RegisterOrder, ...]
    rows: frozenset[OrderRow]
    moves: tuple[OrderMove, ...]
    memory: OwnEntries
    notes: tuple[ReportNote, ...]


def moved(
    transfers: Sequence[tuple[RegisterOrder, Login]], orders: Sequence[RegisterOrder], memory: OwnEntries, window: Window
) -> Moved:
    """Zlecenia ``transfers`` u nowych Wykonawców.

    Przeniesione zlecenie dostaje pisownię ``WYKONAWCA`` z ostatniego zlecenia nowego Wykonawcy w tym dniu, bez niego z
    jego najpóźniejszego zlecenia z dni otwartych, a bez żadnego jego login. Własne wpisy przeniesionego zlecenia
    przechodzą na jego nowy klucz, bo komórki idą z wierszem, tak samo jak własne wpisy zlecenia, któremu tata zmienił
    ``WYKONAWCA`` po Przeniesieniu Centrum: komórki, których nikt nie ruszył, dalej są wpisem Centrum. Przeniesienie z pamięci zostaje, dopóki jego dzień jest
    otwarty, a ``origin`` zostaje z pierwszego Przeniesienia Centrum.
    """

    remembered = {(move.number, move.day): move for move in memory.moves}
    keys: dict[OrderRow, OrderKey] = {}
    moves: list[OrderMove] = []
    for order, worker in transfers:
        key = OrderKey(order.key.number, order.key.day, worker)
        keys[order.row] = key
        moves.append(OrderMove(order.row, key.day, _name(worker, key.day, orders)))
        earlier = remembered.get((key.number, key.day))
        origin_day, origin_worker = (order.key.day, order.key.worker) if earlier is None else (earlier.origin_day, earlier.origin_worker)
        remembered[key.number, key.day] = OwnMove(key.number, key.day, worker, origin_day, origin_worker)
    renamed = {order.key: keys[order.row] for order in orders if order.row in keys}
    for move in memory.moves:
        current = [order.key for order in orders if (order.key.number, order.key.day) == (move.number, move.day)]
        if len(current) == 1 and current[0].worker != move.worker:
            renamed.setdefault(OrderKey(move.number, move.day, move.worker), renamed.get(current[0], current[0]))
    after = tuple(replace(order, key=keys[order.row]) if order.row in keys else order for order in orders)
    entries = frozenset(replace(entry, key=renamed.get(entry.key, entry.key)) for entry in memory.entries)
    kept_moves = frozenset(move for move in remembered.values() if window.opens(move.day))
    return Moved(
        after,
        frozenset(keys),
        tuple(sorted(moves, key=lambda move: (move.order.sheet, move.order.row))),
        OwnEntries(entries, kept_moves),
        _notes(kept_moves, after),
    )


def _name(worker: Login, day: date, orders: Iterable[RegisterOrder]) -> str:
    own = [order for order in orders if order.key.worker == worker]
    same_day = [order for order in own if order.key.day == day]
    if same_day:
        return max(same_day, key=lambda order: (order.row.sheet, order.row.row)).worker_name
    if own:
        return max(own, key=lambda order: (order.key.day, order.row.sheet, order.row.row)).worker_name
    return worker


def _notes(moves: Iterable[OwnMove], orders: Sequence[RegisterOrder]) -> tuple[ReportNote, ...]:
    """Informacje o Przeniesieniach, które stoją: INTERMAX ma zlecenie u Wykonawcy z pamięci, innego niż przed pierwszym
    Przeniesieniem Centrum."""

    standing = {order.key for order in orders}
    notes: list[ReportNote] = []
    for move in moves:
        if move.worker == move.origin_worker or OrderKey(move.number, move.day, move.worker) not in standing:
            continue
        number = OrderNumber(move.number)
        notes += [
            TakenOver(move.day, move.worker, number, move.origin_worker),
            HandedOver(move.origin_day, move.origin_worker, number, move.worker),
        ]
    return tuple(sorted(notes, key=note_order))

