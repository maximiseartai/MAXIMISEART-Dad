"""Liczby Wykonawcy z dnia dla widoku Raporty."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date

from ..activity_legend import ActivityLegend
from ..report_cells import CellChange, OrderRow, ReportColumn
from ..text import normalize_text
from ._descriptions import codes
from ._model import (
    ConflictingVerdicts,
    FaultyDescription,
    Login,
    ManualDifference,
    MissingVerdict,
    OrderDetail,
    OrderKey,
    OvertakenSubject,
    RefusedMove,
    RegisterOrder,
    RepeatedNumber,
    RepeatedOrder,
    ReportProblem,
    Requestable,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    WorkerDay,
)

_VERDICTS = frozenset(verdict.value for verdict in Verdict)


def worker_days(
    orders: Iterable[RegisterOrder],
    said: frozenset[OrderKey],
    sent: Iterable[tuple[date, Login]],
    problems: Iterable[ReportProblem],
    changes: Iterable[CellChange],
    moved: frozenset[OrderRow],
    reached: frozenset[OrderKey],
    added: Iterable[tuple[OrderKey, OrderDetail]],
    legend: ActivityLegend,
    mistaken: Iterable[tuple[Login, date, date]],
    faulty: frozenset[OrderKey],
    offers: Mapping[OrderRow, Requestable],
    overtaken: Iterable[OvertakenSubject],
) -> tuple[WorkerDay, ...]:
    """Liczby i zlecenia dla każdego Wykonawcy z dnia, który ma zlecenia albo Raport wykonawcy; ``entered`` liczy
    zlecenia, których ``SKUTECZNE`` po zapisie zmian ma ``tak`` albo ``nie``, kto by ich nie wpisał, a ``mails``
    Raporty wykonawców za ten dzień (``sent``: dzień i Wykonawca raz na Raport i dzień, za który jest przysłany,
    przy pomylonym temacie dzień zleceń, ADR 0041). Dzień z tematu Raportu wykonawcy ma swoje liczby, także gdy Raport
    liczy się za inny dzień, bo przy nim stoją problemy jego Wpisów.

    ``orders`` mają klucz po Przeniesieniach kliknięcia. Zlecenia dnia idą w kolejności z INTERMAX po zapisie: arkusze
    zleceń tak, jak przyszły w ``orders``, a w arkuszu od góry, a zlecenia przeniesione (``moved``) za pozostałymi,
    bo zapis stawia je pod ostatnim zleceniem nowego Wykonawcy. Zlecenie ma Wpis, gdy Raport wykonawcy z jego dnia ma
    jego numer (``said``: ``WindowRead.said`` z dniem otwartym, z dniem z tematu) albo gdy zwycięski Wpis innego dnia
    trafił do niego (``reached``: klucze celów po kliknięciu, np. pomylony temat). Zlecenia dopisane z raportu (``added``: klucz i zlecenie po zapisie) stoją na końcu zleceń swojego
    Wykonawcy z dnia, za przeniesionymi, bo zapis dopisuje je po Przeniesieniach. Każde zlecenie ``tak`` ma Kody
    czynności swojego opisu z Legendy czynności ``legend`` (``_descriptions.codes``). Dzień, za który liczy się
    raport z pomylonym tematem (``mistaken``: Wykonawca, ten dzień i dzień z tematu), ma jego dzień z tematu.
    Zlecenie bez Wpisu, które ma Wpis w raporcie z błędem tematu za swój dzień (``faulty``,
    ``WindowRead.faulty_entries``), nie jest bez raportu, bo raport przyszedł. Zlecenie, o którym decyduje Wpis raportu z
    błędem tematu, ma Wpis na życzenie z ``offers`` (``WindowRead.offers``, po wierszu), także gdy ma już Wpis, a bez
    Wpisu nie jest bez raportu, także przy Przeniesieniu do nadawcy. Raport z błędem tematu, z którego nie ma już czego
    wpisać (``overtaken``, ``WindowRead.overtaken``), stoi przy swoim dniu jako informacja.
    """

    found_orders = tuple(orders)
    written: dict[tuple[OrderRow, ReportColumn], str] = {(change.order, change.column): change.value for change in changes}
    sheets = {sheet: rank for rank, sheet in enumerate(dict.fromkeys(order.row.sheet for order in found_orders))}
    days: defaultdict[tuple[date, Login], list[RegisterOrder]] = defaultdict(list)
    for order in sorted(found_orders, key=lambda order: (order.row in moved, sheets[order.row.sheet], order.row.row)):
        days[order.key.day, order.key.worker].append(order)
    mails = Counter(sent)
    reported = reached | said
    places = Counter(place for problem in problems if (place := _place(problem)) is not None)
    extra: defaultdict[tuple[date, Login], list[OrderDetail]] = defaultdict(list)
    for key, found in added:
        extra[key.day, key.worker].append(found)
    subject_days: defaultdict[tuple[date, Login], set[date]] = defaultdict(set)
    for worker, day, subject_day in mistaken:
        subject_days[day, worker].add(subject_day)
    taken: defaultdict[tuple[date, Login], list[OvertakenSubject]] = defaultdict(list)
    for report in overtaken:
        taken[report.day, report.worker].append(report)
    figures = []
    subjects = {(key.day, key.worker) for key in said}
    for day, worker in sorted(days.keys() | mails.keys() | subjects | extra.keys() | taken.keys()):
        detail = tuple(
            replace(found, codes=codes(legend, found.successful, found.activities))
            for found in (
                *(
                    OrderDetail(
                        order.key.number,
                        written.get((order.row, ReportColumn.SUCCESSFUL), order.successful),
                        written.get((order.row, ReportColumn.COMPLETED), order.completed),
                        order.key in reported,
                        faulty=order.key in faulty or order.row in offers,
                        request=offers.get(order.row),
                    )
                    for order in days.get((day, worker), [])
                ),
                *extra.get((day, worker), []),
            )
        )
        missing = {order.number for order in detail if not (order.reported or order.faulty)}
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
                mistaken=tuple(sorted(subject_days.get((day, worker), ()))),
                overtaken=tuple(sorted(taken.get((day, worker), ()), key=lambda report: report.arrived)),
            )
        )
    return tuple(figures)


def _place(problem: ReportProblem) -> tuple[date, Login] | None:
    match problem:
        case UnreadableSubject(day=date() as day):
            return day, problem.worker
        case UnreadableSubject() | UnknownSender():
            return None
        case MissingVerdict() | ConflictingVerdicts() | UnknownNumber() | RepeatedOrder() | RepeatedNumber() | FaultyDescription():
            return problem.day, problem.worker
        case RefusedMove():
            return problem.shown, problem.worker
        case ManualDifference(key=key):
            return key.day, key.worker
