"""Dopasowanie Wpisów raportu do zleceń: zlecenie nadawcy z dnia z tematu, a przy kilku Wpisach najpóźniejszy mail."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ._model import (
    MissingVerdict,
    OrderKey,
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

    ``reports`` idą w kolejności przyjścia, więc późniejszy Wpis zastępuje wcześniejszy. Numer, którego Wykonawca nie
    ma w dniu z tematu, to ``UnknownNumber``, a numer w dwóch jego zleceniach z tego dnia to ``RepeatedOrder``.
    Zwycięski Wpis bez ``tak`` ani ``nie`` to ``MissingVerdict`` zamiast celu, bo nie wiadomo, co Wykonawca miał na
    myśli.
    """

    rows: defaultdict[OrderKey, list[RegisterOrder]] = defaultdict(list)
    for order in orders:
        rows[order.key].append(order)
    targets: dict[OrderKey, tuple[RegisterOrder, ReportEntry]] = {}
    problems: list[ReportProblem] = []
    for report in reports:
        for entry in report.entries:
            key = OrderKey(entry.number, report.day, report.worker)
            match rows.get(key, []):
                case []:
                    problems.append(UnknownNumber(report.worker, report.day, entry.number))
                case [order]:
                    targets[key] = (order, entry)
                case _:
                    problems.append(RepeatedOrder(report.worker, report.day, entry.number))
    for key, (_, entry) in list(targets.items()):
        if entry.fault is not None:
            del targets[key]
            problems.append(MissingVerdict(key.worker, key.day, key.number, entry.fault))
    return targets, problems
