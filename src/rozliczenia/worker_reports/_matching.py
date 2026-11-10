"""Dopasowanie Wpisów raportu do zleceń: zlecenie nadawcy z dnia z tematu, a przy kilku Wpisach najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from ._model import (
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
)


def match(
    reports: Iterable[ReadReport], orders: Iterable[RegisterOrder]
) -> tuple[dict[OrderKey, tuple[RegisterOrder, ReportEntry]], list[ReportProblem]]:
    """Zlecenie i zwycięski Wpis dla każdego zlecenia z Wpisami oraz problemy Wpisów bez jednego zlecenia.

    ``reports`` idą w kolejności przyjścia, więc późniejszy Wpis zastępuje wcześniejszy. Numer w dwóch zleceniach
    Wykonawcy z dnia z tematu to ``RepeatedOrder``, a numer bez jego zlecenia z tego dnia rozstrzyga ``_unmatched``.
    Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo, co Wykonawca miał na
    myśli.
    """

    rows: defaultdict[OrderKey, list[RegisterOrder]] = defaultdict(list)
    numbered: defaultdict[OrderNumber, list[OrderKey]] = defaultdict(list)
    for order in orders:
        rows[order.key].append(order)
        numbered[order.key.number].append(order.key)
    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
    problems: list[ReportProblem] = []
    for report in reports:
        for entry in report.entries:
            key = OrderKey(entry.number, report.day, report.worker)
            match rows.get(key, []):
                case []:
                    problems += _unmatched(key, numbered[entry.number])
                case [order]:
                    targets[key] = (order, entry)
                case _:
                    problems.append(RepeatedOrder(report.worker, report.day, entry.number))
    for key, (_, entry) in list(targets.items()):
        if entry.fault is not None:
            del targets[key]
            problems.append(MissingVerdict(key.worker, key.day, key.number, entry.fault))
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
