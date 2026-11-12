"""Dopasowanie Wpisów raportu do zleceń: zlecenie nadawcy z dnia z tematu albo jedyne zlecenie tego numeru u innego
Wykonawcy w tym dniu (Przeniesienie zlecenia, ADR 0029), a przy kilku Wpisach najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..report_cells import OrderRow
from ._model import (
    ConflictingVerdicts,
    ForeignOrder,
    Login,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnMove,
    ReadReport,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    UnknownNumber,
    VerdictFault,
)


@dataclass(frozen=True)
class Matched:
    """Wynik dopasowania: zwycięski Wpis każdego zlecenia po kluczu, który zlecenie ma po kliknięciu (``targets``),
    zlecenia, które przechodzą do nadawcy zwycięskiego Wpisu (``transfers``: zlecenie i nadawca), i problemy Wpisów bez
    jednego zlecenia."""

    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]]
    transfers: tuple[tuple[RegisterOrder, Login], ...]
    problems: list[ReportProblem]


def match(
    reports: Iterable[ReadReport], orders: Iterable[RegisterOrder], moves: Mapping[tuple[OrderNumber, date], OwnMove]
) -> Matched:
    """Zlecenie i zwycięski Wpis dla każdego zlecenia z Wpisami oraz problemy Wpisów bez jednego zlecenia.

    ``reports`` idą w kolejności przyjścia, więc późniejszy mail zastępuje Wpisy wcześniejszego, także mail innego
    Wykonawcy. Wpis trafia do zlecenia nadawcy z dnia z tematu; numer w dwóch takich zleceniach to ``RepeatedOrder``.
    Bez zlecenia nadawcy w tym dniu Wpis trafia do jedynego zlecenia tego numeru u innego Wykonawcy w tym dniu, a gdy
    zwycięży, zlecenie przechodzi do nadawcy (Przeniesienie zlecenia), chyba że nadawca ma ten numer w innym dniu
    otwartym (``OtherDay``) albo tata zmienił ``WYKONAWCA`` po Przeniesieniu Centrum (``moves``): wtedy liczą się tylko
    Wpisy Wykonawcy z INTERMAX, bez problemu. Numer w kilku zleceniach innych Wykonawców z tego dnia rozstrzyga
    ``_unmatched``, tak jak numer bez zlecenia w tym dniu. Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict``
    zamiast celu, bo nie wiadomo, co Wykonawca miał na myśli, a zwycięski mail z Wpisami numeru o przeciwnym zamiarze
    (``_entries.entries``) to ``ConflictingVerdicts``; w obu zlecenie zostaje u swojego Wykonawcy.
    """

    rows: defaultdict[OrderKey, list[RegisterOrder]] = defaultdict(list)
    numbered: defaultdict[OrderNumber, list[OrderKey]] = defaultdict(list)
    days: defaultdict[tuple[OrderNumber, date], list[RegisterOrder]] = defaultdict(list)
    for order in orders:
        rows[order.key].append(order)
        numbered[order.key.number].append(order.key)
        days[order.key.number, order.key.day].append(order)
    latest: dict[OrderRow, tuple[RegisterOrder, ReadReport, tuple[ReportEntry, ...]]] = {}
    problems: list[ReportProblem] = []
    for report in reports:
        said: defaultdict[OrderNumber, list[ReportEntry]] = defaultdict(list)
        for entry in report.entries:
            said[entry.number].append(entry)
        for number, written in said.items():
            key = OrderKey(number, report.day, report.worker)
            match rows.get(key, []):
                case []:
                    found = _foreign(key, numbered[number], days[number, report.day])
                    if isinstance(found, RegisterOrder):
                        if _movable(found, moves):
                            latest[found.row] = (found, report, tuple(written))
                    else:
                        problems += found
                case [order]:
                    latest[order.row] = (order, report, tuple(written))
                case _:
                    problems.append(RepeatedOrder(report.worker, report.day, number))
    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
    transfers: list[tuple[RegisterOrder, Login]] = []
    for order, report, entries in latest.values():
        key = OrderKey(order.key.number, order.key.day, report.worker)
        match entries:
            case (ReportEntry(fault=None) as entry,):
                targets[key] = (order, entry)
                if report.worker != order.key.worker:
                    transfers.append((order, report.worker))
            case (ReportEntry(fault=VerdictFault() as fault),):
                problems.append(MissingVerdict(key.worker, key.day, key.number, fault))
            case _:
                problems.append(ConflictingVerdicts(key.worker, key.day, key.number, report.mail, report.arrived, entries))
    return Matched(targets, tuple(transfers), problems)


def _movable(order: RegisterOrder, moves: Mapping[tuple[OrderNumber, date], OwnMove]) -> bool:
    """Zlecenie bez Przeniesienia Centrum albo dalej u Wykonawcy, do którego przeniosło je Centrum: ręczna zmiana
    ``WYKONAWCA`` po Przeniesieniu wygrywa (ADR 0029)."""

    move = moves.get((order.key.number, order.key.day))
    return move is None or move.worker == order.key.worker


def _foreign(
    wanted: OrderKey, found: Sequence[OrderKey], same_day: Sequence[RegisterOrder]
) -> RegisterOrder | list[ReportProblem]:
    """Jedyne zlecenie numeru ``wanted.number`` u innego Wykonawcy z dnia ``wanted.day`` (``same_day``: zlecenia tego
    numeru z tego dnia) albo problem z ``_unmatched``, gdy nadawca ma ten numer w innym dniu albo zleceń innych
    Wykonawców z tym numerem jest w tym dniu kilka albo żadnego."""

    if any(key.worker == wanted.worker for key in found) or len(same_day) != 1:
        return _unmatched(wanted, found)
    return same_day[0]


def _unmatched(wanted: OrderKey, found: Sequence[OrderKey]) -> list[ReportProblem]:
    """Problem Wpisu Wykonawcy ``wanted.worker`` z dnia ``wanted.day``, którego zlecenia o tym numerze nie ma w tym dniu;
    ``found`` to zlecenia z tym numerem z dni otwartych.

    Zlecenie nadawcy z innego dnia daje ``OtherDay`` ze wszystkimi jego dniami, bo jego własne zlecenie jest bliżej
    zamiaru Wykonawcy niż cudze. Inaczej zlecenia innych Wykonawców z tego dnia (kilka, bo jedno to Przeniesienie
    zlecenia) dają ``ForeignOrder`` z każdym z nich, a numer bez obu to ``UnknownNumber``.
    """

    days: set[date] = {key.day for key in found if key.worker == wanted.worker}
    if days:
        return [OtherDay(wanted.worker, wanted.day, wanted.number, tuple(sorted(days)))]
    owners: set[Login] = {key.worker for key in found if key.day == wanted.day}
    if owners:
        return [ForeignOrder(wanted.worker, wanted.day, wanted.number, owner) for owner in sorted(owners)]
    return [UnknownNumber(wanted.worker, wanted.day, wanted.number)]
