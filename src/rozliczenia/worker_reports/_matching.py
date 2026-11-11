"""Dopasowanie Wpisów raportu do zleceń: zlecenie nadawcy z dnia z tematu, a przy kilku Wpisach najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from ._model import (
    ConflictingVerdicts,
    ForeignOrder,
    Login,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    OtherDay,
    ReadReport,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    UnknownNumber,
    VerdictFault,
)


def match(
    reports: Iterable[ReadReport], orders: Iterable[RegisterOrder]
) -> tuple[dict[OrderKey, tuple[RegisterOrder, ReportEntry]], list[ReportProblem]]:
    """Zlecenie i zwycięski Wpis dla każdego zlecenia z Wpisami oraz problemy Wpisów bez jednego zlecenia.

    ``reports`` idą w kolejności przyjścia, więc późniejszy mail zastępuje Wpisy wcześniejszego. Numer w dwóch zleceniach
    Wykonawcy z dnia z tematu to ``RepeatedOrder``, a numer bez jego zlecenia z tego dnia rozstrzyga ``_unmatched``.
    Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo, co Wykonawca miał na
    myśli, a zwycięski mail z Wpisami numeru o przeciwnym zamiarze (``_entries.entries``) to ``ConflictingVerdicts``.
    """

    rows: defaultdict[OrderKey, list[RegisterOrder]] = defaultdict(list)
    numbered: defaultdict[OrderNumber, list[OrderKey]] = defaultdict(list)
    for order in orders:
        rows[order.key].append(order)
        numbered[order.key.number].append(order.key)
    latest: dict[OrderKey, tuple[RegisterOrder, ReadReport, tuple[ReportEntry, ...]]] = {}
    problems: list[ReportProblem] = []
    for report in reports:
        said: defaultdict[OrderNumber, list[ReportEntry]] = defaultdict(list)
        for entry in report.entries:
            said[entry.number].append(entry)
        for number, written in said.items():
            key = OrderKey(number, report.day, report.worker)
            match rows.get(key, []):
                case []:
                    problems += _unmatched(key, numbered[number])
                case [order]:
                    latest[key] = (order, report, tuple(written))
                case _:
                    problems.append(RepeatedOrder(report.worker, report.day, number))
    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
    for key, (order, report, entries) in latest.items():
        match entries:
            case (ReportEntry(fault=None) as entry,):
                targets[key] = (order, entry)
            case (ReportEntry(fault=VerdictFault() as fault),):
                problems.append(MissingVerdict(key.worker, key.day, key.number, fault))
            case _:
                problems.append(ConflictingVerdicts(key.worker, key.day, key.number, report.mail, report.arrived, entries))
    return targets, problems


def _unmatched(wanted: OrderKey, found: Sequence[OrderKey]) -> list[ReportProblem]:
    """Problem Wpisu Wykonawcy ``wanted.worker`` z dnia ``wanted.day``, którego zlecenia o tym numerze nie ma w tym dniu;
    ``found`` to zlecenia z tym numerem z dni otwartych.

    Zlecenie nadawcy z innego dnia daje ``OtherDay`` ze wszystkimi jego dniami, bo Wpis trafia tylko do zlecenia
    nadawcy, więc jego własne zlecenie jest bliżej zamiaru Wykonawcy niż cudze. Inaczej zlecenie innego Wykonawcy z
    tego dnia daje ``ForeignOrder`` z każdym z nich, a numer bez obu to ``UnknownNumber``.
    """

    days: set[date] = {key.day for key in found if key.worker == wanted.worker}
    if days:
        return [OtherDay(wanted.worker, wanted.day, wanted.number, tuple(sorted(days)))]
    owners: set[Login] = {key.worker for key in found if key.day == wanted.day}
    if owners:
        return [ForeignOrder(wanted.worker, wanted.day, wanted.number, owner) for owner in sorted(owners)]
    return [UnknownNumber(wanted.worker, wanted.day, wanted.number)]
