"""Przeniesienia zleceń kliknięcia: zlecenia po Przeniesieniach, operacje zapisu, pamięć zleceń i informacje dla taty.

Przeniesienie zlecenia (ADR 0029) zmienia Wykonawcę albo dzień zlecenia. Pamięć zlecenia (``OwnMove``) mówi, gdzie
Centrum je zostawiło, gdzie stało przed pierwszym Przeniesieniem Centrum, na jaki najświeższy mail Centrum zadziałało i
czy tata zmienił Wykonawcę albo dzień po Przeniesieniu Centrum, więc ręczna zmiana taty wygrywa (``_model.may_move``),
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
    MovedFrom,
    MovedTo,
    OrderKey,
    OrderNumber,
    OwnEntries,
    OwnEntry,
    OwnMove,
    RegisterOrder,
    ReportNote,
    TakenOver,
    Window,
    memories_of,
    note_order,
    single_orders,
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
    accepted: Sequence[tuple[RegisterOrder, Login, date, datetime]],
    orders: Sequence[RegisterOrder],
    memory: OwnEntries,
    window: Window,
) -> Moved:
    """Zlecenia zwycięskich Wpisów ``accepted`` (zlecenie, nadawca, dzień po kliknięciu, chwila przyjścia maila) u ich
    nadawców i w ich dniach oraz pamięć zleceń po kliknięciu według tabeli przejść (opis #1358, miejsce = Wykonawca i
    dzień); ``orders``: każde zlecenie, które proces odczytał z INTERMAX.

    Zlecenie w innym miejscu przechodzi do nadawcy i na dzień po kliknięciu i dostaje pisownię ``WYKONAWCA`` z
    ostatniego zlecenia nadawcy w dniu docelowym, bez niego z jego najpóźniejszego odczytanego zlecenia, bez niego z
    pamięci (``origin_name`` zlecenia, które zaczęło się u nadawcy), a bez żadnego jego login.

    Pamięć zleceń numeru (``memories_of``): najpierw obserwacja, czy tata zmienił Wykonawcę albo dzień po Przeniesieniu
    Centrum (``overridden``, zostaje, ``_observed``). Wpis przyjęty w miejscu zlecenia z INTERMAX zakłada pamięć, gdy
    numer jej nie ma (Centrum zostawiło zlecenie tam), a inaczej tylko podnosi ``since`` każdej pamięci numeru, także
    założonej w tym kliknięciu Wpisem do drugiego zlecenia numeru: miejsce Centrum nie idzie za ręczną zmianą taty, a
    ``since`` nie maleje. Przeniesienie, które dotyczy tylko jedynego zlecenia numeru (``_matching.Board``), zastępuje
    całą pamięć numeru pamięcią pod dniem docelowym, z miejscem u nadawcy i chwilą jego maila, z miejscem sprzed
    pierwszego Przeniesienia z pamięci, gdy zlecenie stało tam, gdzie je zostawiło Centrum, a inaczej z miejsca sprzed
    tego Przeniesienia. Pamięć zlecenia zostaje, dopóki jej dzień jest otwarty. Własne wpisy idą za wierszem tylko przy
    jedynym zleceniu numeru (``_carried``).
    """

    standing = tuple(move for move in memory.moves if window.opens(move.day))
    observed = tuple(_observed(move, orders) for move in standing)
    remembered = {(move.number, move.day): move for move in observed}
    keys: dict[OrderRow, OrderKey] = {}
    moves: list[OrderMove] = []
    for order, worker, day, arrived in accepted:
        number = order.key.number
        earlier = memories_of(remembered.values(), number)
        if (worker, day) == (order.key.worker, order.key.day):
            if not earlier:
                remembered[number, day] = OwnMove(number, day, worker, day, worker, order.worker_name, arrived)
            for found in earlier:
                remembered[found.number, found.day] = replace(found, since=max(found.since, arrived))
            continue
        keys[order.row] = OrderKey(number, day, worker)
        moves.append(OrderMove(order.row, day, _name(worker, day, orders, memory.moves)))
        here = [found for found in earlier if (found.worker, found.day) == (order.key.worker, order.key.day)]
        if here:
            origin = (here[0].origin_day, here[0].origin_worker, here[0].origin_name)
        else:
            origin = (order.key.day, order.key.worker, order.worker_name)
        for found in earlier:
            remembered.pop((found.number, found.day), None)
        remembered[number, day] = OwnMove(number, day, worker, *origin, arrived)
    after = tuple(replace(order, key=keys[order.row]) if order.row in keys else order for order in orders)
    kept_moves = frozenset(remembered.values())
    return Moved(
        after,
        frozenset(keys),
        tuple(sorted(moves, key=lambda move: (move.order.sheet, move.order.row))),
        OwnEntries(_carried(memory.entries, after), kept_moves),
        _notes(kept_moves, after),
    )


def _observed(move: OwnMove, orders: Iterable[RegisterOrder]) -> OwnMove:
    """Pamięć zlecenia po obserwacji kliknięcia: gdy Przeniesienie Centrum stoi w pamięci, a żadne zlecenie jej numeru
    nie stoi tam, gdzie je zostawiło Centrum (``OwnMove.left``), tata zmienił Wykonawcę albo dzień tego zlecenia, i
    pamięć to zapamiętuje (``overridden``), także gdy numer ma kilka zleceń albo żadnego."""

    places = [(order.key.worker, order.key.day) for order in orders if order.key.number == move.number]
    return replace(move, overridden=True) if move.left(places) else move


def _carried(entries: Iterable[OwnEntry], orders: Iterable[RegisterOrder]) -> frozenset[OwnEntry]:
    """Własne wpisy idą za wierszem tylko wtedy, gdy to na pewno ten sam wiersz: numer ma w odczytanych dniach jedno
    zlecenie teraz (``single_orders``), a pamięć ma jego wpisy pod jednym kluczem, czyli numer miał jedno zlecenie także
    w chwili zapisu pamięci (``OwnEntries``). Wpisy przechodzą wtedy na klucz, który zlecenie ma po kliknięciu: po
    ręcznej zmianie ``WYKONAWCA`` albo dnia, która nie rusza komórek, i po Przeniesieniu Centrum. Wpisy numeru, który
    ma teraz kilka zleceń albo żadnego, przepadają: Excel nie mówi, który wiersz jest którym (tata mógł usunąć jeden,
    scalić je albo zamienić ich Wykonawców), a komórka bez pamięci liczy się jak wartość taty, więc Centrum jej nie
    nadpisze."""

    entries = tuple(entries)
    single = single_orders(orders)
    remembered: defaultdict[OrderNumber, set[OrderKey]] = defaultdict(set)
    for entry in entries:
        remembered[entry.key.number].add(entry.key)
    return frozenset(
        replace(entry, key=single[entry.key.number])
        for entry in entries
        if entry.key.number in single and len(remembered[entry.key.number]) == 1
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
