"""Liczby Wykonawcy z dnia dla widoku Raporty."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from ..report_cells import CellChange, OrderRow, ReportColumn
from ..text import normalize_text
from ._model import (
    ConflictingVerdicts,
    ForeignOrder,
    Login,
    ManualDifference,
    MissingVerdict,
    OrderDetail,
    OrderKey,
    OtherDay,
    ReadReport,
    RegisterOrder,
    RepeatedOrder,
    ReportProblem,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    WorkerDay,
)

_VERDICTS = frozenset(verdict.value for verdict in Verdict)


def worker_days(
    orders: Iterable[RegisterOrder],
    reports: Sequence[ReadReport],
    problems: Iterable[ReportProblem],
    changes: Iterable[CellChange],
    moved: frozenset[OrderRow],
) -> tuple[WorkerDay, ...]:
    """Liczby i zlecenia dla każdego Wykonawcy z dnia, który ma zlecenia albo Raport wykonawcy; ``entered`` liczy
    zlecenia, których ``SKUTECZNE`` po zapisie zmian ma ``tak`` albo ``nie``, kto by ich nie wpisał.

    ``orders`` mają klucz po Przeniesieniach kliknięcia. Zlecenia dnia idą w kolejności z INTERMAX po zapisie: arkusze
    zleceń tak, jak przyszły w ``orders``, a w arkuszu od góry, a zlecenia przeniesione (``moved``) za pozostałymi,
    bo zapis stawia je pod ostatnim zleceniem nowego Wykonawcy.
    """

    found_orders = tuple(orders)
    written: dict[tuple[OrderRow, ReportColumn], str] = {(change.order, change.column): change.value for change in changes}
    sheets = {sheet: rank for rank, sheet in enumerate(dict.fromkeys(order.row.sheet for order in found_orders))}
    days: defaultdict[tuple[date, Login], list[RegisterOrder]] = defaultdict(list)
    for order in sorted(found_orders, key=lambda order: (order.row in moved, sheets[order.row.sheet], order.row.row)):
        days[order.key.day, order.key.worker].append(order)
    mails = Counter((report.day, report.worker) for report in reports)
    reported = {OrderKey(entry.number, report.day, report.worker) for report in reports for entry in report.entries}
    places = Counter(place for problem in problems if (place := _place(problem)) is not None)
    figures = []
    for day, worker in sorted(days.keys() | mails.keys()):
        detail = tuple(
            OrderDetail(
                order.key.number,
                written.get((order.row, ReportColumn.SUCCESSFUL), order.successful),
                written.get((order.row, ReportColumn.COMPLETED), order.completed),
                order.key in reported,
            )
            for order in days.get((day, worker), [])
        )
        missing = {order.number for order in detail if not order.reported}
        figures.append(
            WorkerDay(
                day,
                worker,
                orders=len(detail),
                entered=sum(normalize_text(order.successful) in _VERDICTS for order in detail),
                mails=mails[day, worker],
                problems=places[day, worker],
                without_report=tuple(sorted(missing, key=lambda number: (len(number), number))),
                orders_detail=detail,
            )
        )
    return tuple(figures)


def _place(problem: ReportProblem) -> tuple[date, Login] | None:
    match problem:
        case UnreadableSubject() | UnknownSender():
            return None
        case MissingVerdict() | ConflictingVerdicts() | UnknownNumber() | ForeignOrder() | OtherDay() | RepeatedOrder():
            return problem.day, problem.worker
        case ManualDifference(key=key):
            return key.day, key.worker
