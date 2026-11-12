"""Przeniesienia zleceń kliknięcia: zlecenia po Przeniesieniach, operacje zapisu, pamięć zleceń i informacje dla taty.

Przeniesienie zlecenia (ADR 0029) zmienia Wykonawcę zlecenia w dniu zlecenia. Pamięć zlecenia (``OwnMove``) mówi, u
kogo Centrum je zostawiło, gdzie stało przed pierwszym Przeniesieniem Centrum, na jaki najświeższy mail Centrum
zadziałało i czy tata zmienił Wykonawcę po Przeniesieniu Centrum, więc ręczna zmiana taty wygrywa (``_model.may_move``),
a informacje o Przeniesieniu stoją przy każdym kliknięciu, dopóki INTERMAX ma zlecenie tam, gdzie je postawiło Centrum.
"""

from __future__ import annotations

from collections import defaultdict
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
    OwnEntry,
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
    (``memory``, z pamięcią zleceń po kliknięciu) i informacje dla taty (``notes``)."""

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
    """Zlecenia zwycięskich Wpisów ``accepted`` (zlecenie, nadawca, chwila przyjścia maila) u ich nadawców i pamięć
    zleceń po kliknięciu według tabeli przejść (opis #1358).

    Zlecenie innego Wykonawcy przechodzi do nadawcy i dostaje pisownię ``WYKONAWCA`` z ostatniego zlecenia nadawcy w tym
    dniu, bez niego z jego najpóźniejszego zlecenia z dni otwartych, bez niego z pamięci (``origin_name`` zlecenia,
    które zaczęło się u nadawcy), a bez żadnej jego login.

    Pamięć zlecenia: najpierw obserwacja, czy tata zmienił Wykonawcę po Przeniesieniu Centrum (``overridden``, zostaje).
    Wpis przyjęty u Wykonawcy zlecenia z INTERMAX zakłada pamięć, gdy jej nie było (Centrum zostawiło zlecenie u niego),
    a inaczej tylko podnosi ``since``: miejsce Centrum nie idzie za ręczną zmianą taty. Przeniesienie zostawia zlecenie
    u nadawcy z chwilą jego maila, z miejscem sprzed pierwszego Przeniesienia z pamięci, gdy zlecenie stało tam, gdzie je
    zostawiło Centrum, a inaczej z miejsca sprzed tego Przeniesienia. Pamięć zlecenia zostaje, dopóki jego dzień jest
    otwarty. Własne wpisy idą za wierszem (``_following``).
    """

    rows = _rows(orders)
    remembered = {(move.number, move.day): _observed(move, rows) for move in memory.moves}
    keys: dict[OrderRow, OrderKey] = {}
    moves: list[OrderMove] = []
    for order, worker, arrived in accepted:
        number, day = order.key.number, order.key.day
        earlier = remembered.get((number, day))
        if worker == order.key.worker:
            remembered[number, day] = (
                OwnMove(number, day, worker, day, worker, order.worker_name, arrived)
                if earlier is None
                else replace(earlier, since=max(earlier.since, arrived))
            )
            continue
        keys[order.row] = OrderKey(number, day, worker)
        moves.append(OrderMove(order.row, day, _name(worker, day, orders, memory.moves)))
        if earlier is not None and (earlier.worker, earlier.day) == (order.key.worker, day):
            origin = (earlier.origin_day, earlier.origin_worker, earlier.origin_name)
        else:
            origin = (day, order.key.worker, order.worker_name)
        remembered[number, day] = OwnMove(number, day, worker, *origin, arrived)
    after = tuple(replace(order, key=keys[order.row]) if order.row in keys else order for order in orders)
    kept_moves = frozenset(move for move in remembered.values() if window.opens(move.day))
    return Moved(
        after,
        frozenset(keys),
        tuple(sorted(moves, key=lambda move: (move.order.sheet, move.order.row))),
        OwnEntries(_following(memory.entries, _rows(after)), kept_moves),
        _notes(kept_moves, after),
    )


def _rows(orders: Iterable[RegisterOrder]) -> dict[tuple[OrderNumber, date], list[OrderKey]]:
    """Klucze zleceń każdego numeru i dnia."""

    found: defaultdict[tuple[OrderNumber, date], list[OrderKey]] = defaultdict(list)
    for order in orders:
        found[order.key.number, order.key.day].append(order.key)
    return dict(found)


def _observed(move: OwnMove, rows: dict[tuple[OrderNumber, date], list[OrderKey]]) -> OwnMove:
    """Pamięć zlecenia po obserwacji kliknięcia: gdy INTERMAX ma jeden wiersz tego numeru i dnia, a tata zmienił jego
    Wykonawcę po Przeniesieniu Centrum, pamięć to zapamiętuje (``overridden``); przy kilku wierszach albo żadnym czeka."""

    match rows.get((move.number, move.day), []):
        case [current] if move.overridden_at(current.worker, current.day):
            return replace(move, overridden=True)
        case _:
            return move


def _following(entries: Iterable[OwnEntry], rows: dict[tuple[OrderNumber, date], list[OrderKey]]) -> frozenset[OwnEntry]:
    """Własne wpisy idą za wierszem: przechodzą na klucz, który zlecenie ma po kliknięciu (po Przeniesieniu albo po
    ręcznej zmianie ``WYKONAWCA``, która nie rusza komórek), gdy numer w tym dniu ma jeden wiersz, a pamięć ma wpisy
    tego numeru i dnia jednego Wykonawcy. Inaczej zostają pod swoim kluczem, a ``_cells.reconcile`` zatrzyma tylko te,
    których komórka dalej ma zapamiętaną wartość."""

    entries = tuple(entries)
    workers: defaultdict[tuple[OrderNumber, date], set[Login]] = defaultdict(set)
    for entry in entries:
        workers[entry.key.number, entry.key.day].add(entry.key.worker)

    def key(entry: OwnEntry) -> OrderKey:
        place = (entry.key.number, entry.key.day)
        match rows.get(place, []):
            case [current] if len(workers[place]) == 1:
                return current
            case _:
                return entry.key

    return frozenset(replace(entry, key=key(entry)) for entry in entries)


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
