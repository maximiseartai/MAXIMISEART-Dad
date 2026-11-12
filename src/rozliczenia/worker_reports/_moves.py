"""Przeniesienia zleceń kliknięcia: zlecenia po Przeniesieniach, operacje zapisu, pamięć Przeniesień i informacje dla taty.

Przeniesienie zlecenia (ADR 0029) zmienia Wykonawcę albo dzień zlecenia. Pamięć (``OwnMove``) mówi, gdzie Centrum
postawiło zlecenie i gdzie stało przed pierwszym Przeniesieniem Centrum, więc ręczna zmiana taty wygrywa
(``_matching.Board``), a informacje o Przeniesieniu stoją przy każdym kliknięciu, dopóki INTERMAX ma zlecenie tam,
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
    MovedFrom,
    MovedTo,
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
    placements: Sequence[tuple[RegisterOrder, Login, date]],
    orders: Sequence[RegisterOrder],
    memory: OwnEntries,
    window: Window,
) -> Moved:
    """Zlecenia ``placements`` u nowych Wykonawców i w nowych dniach.

    Przeniesione zlecenie dostaje pisownię ``WYKONAWCA`` z ostatniego zlecenia nowego Wykonawcy w dniu docelowym, bez
    niego z jego najpóźniejszego zlecenia z dni otwartych, a bez żadnego jego login. Własne wpisy przeniesionego
    zlecenia przechodzą na jego nowy klucz, bo komórki idą z wierszem, tak samo jak własne wpisy jedynego zlecenia
    numeru, które tata przeniósł po Przeniesieniu Centrum: komórki, których nikt nie ruszył, dalej są wpisem Centrum.
    Przeniesienie z pamięci przechodzi pod nowy dzień zlecenia, zostaje, dopóki jego dzień jest otwarty, a ``origin``
    zostaje z pierwszego Przeniesienia Centrum.
    """

    remembered = {(move.number, move.day): move for move in memory.moves}
    keys: dict[OrderRow, OrderKey] = {}
    moves: list[OrderMove] = []
    for order, worker, day in placements:
        key = OrderKey(order.key.number, day, worker)
        keys[order.row] = key
        moves.append(OrderMove(order.row, day, _name(worker, day, orders)))
        earlier = remembered.get((order.key.number, order.key.day))
        if earlier is not None and earlier.worker == order.key.worker:
            del remembered[order.key.number, order.key.day]
            origin_day, origin_worker = earlier.origin_day, earlier.origin_worker
        else:
            origin_day, origin_worker = order.key.day, order.key.worker
        remembered[key.number, key.day] = OwnMove(key.number, key.day, worker, origin_day, origin_worker)
    renamed = {order.key: keys[order.row] for order in orders if order.row in keys}
    current = {order.key for order in orders}
    for move in memory.moves:
        left = OrderKey(move.number, move.day, move.worker)
        same = [order.key for order in orders if order.key.number == move.number]
        if left not in current and len(same) == 1:
            renamed.setdefault(left, renamed.get(same[0], same[0]))
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
    """Informacje o Przeniesieniach, które stoją: INTERMAX ma zlecenie tam, gdzie postawiło je Centrum, u innego
    Wykonawcy (przejęte i przekazane) albo w innym dniu (przeniesione z i na) niż przed pierwszym Przeniesieniem."""

    standing = {order.key for order in orders}
    notes: list[ReportNote] = []
    for move in moves:
        if OrderKey(move.number, move.day, move.worker) not in standing:
            continue
        number = OrderNumber(move.number)
        if move.worker != move.origin_worker:
            notes += [
                TakenOver(move.day, move.worker, number, move.origin_worker),
                HandedOver(move.origin_day, move.origin_worker, number, move.worker),
            ]
        if move.day != move.origin_day:
            notes += [
                MovedFrom(move.day, move.worker, number, move.origin_day),
                MovedTo(move.origin_day, move.origin_worker, number, move.day),
            ]
    return tuple(sorted(notes, key=note_order))
