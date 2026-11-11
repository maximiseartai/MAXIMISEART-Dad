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
) -> tuple[WorkerDay, ...]:
    """Liczby dla każdego Wykonawcy z dnia, który ma zlecenia albo Raport wykonawcy; ``entered`` liczy zlecenia, których
    ``SKUTECZNE`` po zapisie zmian ma ``tak`` albo ``nie``, kto by ich nie wpisał."""

    successful: dict[OrderRow, str] = {
        change.order: change.value for change in changes if change.column is ReportColumn.SUCCESSFUL
    }
    days: defaultdict[tuple[date, Login], list[RegisterOrder]] = defaultdict(list)
    for order in orders:
        days[order.key.day, order.key.worker].append(order)
    mails = Counter((report.day, report.worker) for report in reports)
    reported = {OrderKey(entry.number, report.day, report.worker) for report in reports for entry in report.entries}
    places = Counter(place for problem in problems if (place := _place(problem)) is not None)
    figures = []
    for day, worker in sorted(days.keys() | mails.keys()):
        found = days.get((day, worker), [])
        entered = sum(normalize_text(successful.get(order.row, order.successful)) in _VERDICTS for order in found)
        missing = {order.key.number for order in found if order.key not in reported}
        figures.append(
            WorkerDay(
                day,
                worker,
                orders=len(found),
                entered=entered,
                mails=mails[day, worker],
                problems=places[day, worker],
                without_report=tuple(sorted(missing, key=lambda number: (len(number), number))),
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
