"""Przeniesienia zleceń kliknięcia: zlecenia po Przeniesieniach, operacje zapisu, pamięć miejsc zleceń i informacje dla
taty.

Przeniesienie zlecenia (ADR 0029) zmienia Wykonawcę zlecenia w dniu zlecenia. Pamięć (``OwnMove``) mówi, u kogo Centrum
postawiło zlecenie albo przyjęło Wpis jego Wykonawcy, kiedy przyszedł ostatni przyjęty mail i gdzie zlecenie stało
przed pierwszym Przeniesieniem Centrum, więc ręczna zmiana taty wygrywa (``_matching._movable``), a informacje o
Przeniesieniu stoją przy każdym kliknięciu, dopóki INTERMAX ma zlecenie tam, gdzie je postawiło Centrum.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

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
    accepted: Sequence[tuple[RegisterOrder, Login, datetime]],
    orders: Sequence[RegisterOrder],
    memory: OwnEntries,
    window: Window,
) -> Moved:
    """Zlecenia zwycięskich Wpisów ``accepted`` (zlecenie, nadawca, chwila przyjścia maila) u ich nadawców.

    Zlecenie innego Wykonawcy przechodzi do nadawcy i dostaje pisownię ``WYKONAWCA`` z ostatniego zlecenia nadawcy w tym
    dniu, bez niego z jego najpóźniejszego zlecenia z dni otwartych, bez niego z pamięci (``origin_name`` Przeniesienia,
    które zaczęło się u nadawcy), a bez żadnej jego login. Pamięć dostaje miejsce każdego zlecenia zwycięskiego Wpisu
    z chwilą maila (``OwnMove``): po Przeniesieniu u nadawcy, z ``origin`` z pamięci, gdy INTERMAX ma zlecenie tam,
    gdzie je postawiło Centrum, a inaczej z miejsca sprzed Przeniesienia; Wpis nadawcy w jego własnym zleceniu
    zapisuje to zlecenie u niego, chyba że tata zmienił ``WYKONAWCA`` po wcześniejszym miejscu z pamięci: wtedy pamięć
    zostaje jak była, bo to ona mówi, że zmiana taty wygrywa. Własne wpisy przeniesionego zlecenia przechodzą na jego
    nowy klucz, bo komórki idą z wierszem, tak samo jak własne wpisy zlecenia, któremu tata zmienił ``WYKONAWCA`` po
    miejscu z pamięci: komórki, których nikt nie ruszył, dalej są wpisem Centrum. Miejsce z pamięci zostaje, dopóki
    jego dzień jest otwarty.
    """

    remembered = {(move.number, move.day): move for move in memory.moves}
    keys: dict[OrderRow, OrderKey] = {}
    moves: list[OrderMove] = []
    for order, worker, arrived in accepted:
        number, day = order.key.number, order.key.day
        earlier = remembered.get((number, day))
        standing = earlier is not None and earlier.worker == order.key.worker
        if worker == order.key.worker:
            if earlier is None:
                remembered[number, day] = OwnMove(number, day, worker, day, worker, order.worker_name, arrived)
            elif standing:
                remembered[number, day] = replace(earlier, since=arrived)
            continue
        key = OrderKey(number, day, worker)
        keys[order.row] = key
        moves.append(OrderMove(order.row, day, _name(worker, day, orders, memory.moves)))
        if earlier is not None and standing:
            origin = (earlier.origin_day, earlier.origin_worker, earlier.origin_name)
        else:
            origin = (day, order.key.worker, order.worker_name)
        remembered[number, day] = OwnMove(number, day, worker, *origin, arrived)
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


def _name(worker: Login, day: date, orders: Iterable[RegisterOrder], remembered: Iterable[OwnMove]) -> str:
    own = [order for order in orders if order.key.worker == worker]
    same_day = [order for order in own if order.key.day == day]
    if same_day:
        return max(same_day, key=lambda order: (order.row.sheet, order.row.row)).worker_name
    if own:
        return max(own, key=lambda order: (order.key.day, order.row.sheet, order.row.row)).worker_name
    names = sorted((move.origin_day, move.number, move.origin_name) for move in remembered if move.origin_worker == worker)
    return names[-1][2] if names else worker


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

