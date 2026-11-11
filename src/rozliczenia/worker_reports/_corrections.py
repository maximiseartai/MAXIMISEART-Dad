"""Poprawiony mail: problemy z błędów Wykonawcy, które znikają, gdy Wykonawca przyśle swój Raport wykonawcy jeszcze raz."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from . import _matching
from ._model import (
    ForeignOrder,
    Login,
    MailId,
    OrderNumber,
    OtherDay,
    ReadReport,
    ReadUnreadable,
    RegisterOrder,
    ReportProblem,
    UnknownNumber,
    UnreadableSubject,
)


def standing(
    problems: Iterable[ReportProblem],
    reports: Sequence[ReadReport],
    unreadable: Sequence[ReadUnreadable],
    orders: Sequence[RegisterOrder],
) -> set[ReportProblem]:
    """Problemy, które dalej stoją po poprawionych mailach (US 40).

    Stary mail zostaje w skrzynce, więc rdzeń liczy jego problemy przy każdym kliknięciu. Poprawionym mailem jest
    późniejszy Raport wykonawcy tego samego Wykonawcy z dnia poprawki, który ma numer każdego Wpisu wcześniejszego
    maila do zleceń tego Wykonawcy z tego dnia, a takich Wpisów jest co najmniej jeden. Reguła porównuje tylko numery:
    nie sprawdza ``tak``/``nie`` ani opisu i nie wymaga, żeby poprawiony mail powtórzył resztę wcześniejszego. Kolejny
    raport bez tych numerów problemu nie usuwa, bo nieznany numer może być zleceniem, którego brak w INTERMAX.
    Poprawiony mail usuwa nieznany numer i cudze zlecenie z dnia z tematu, inną datę z dniem zlecenia (dzień
    poprawki to dzień zlecenia) i nieczytelny temat (``unreadable``: odczyty maili z nieczytelnym tematem z numerami ich Wpisów). Ostrzeżenie
    o nieczytelnym temacie stoi, gdy któregoś odczytu z nim nie poprawiono, więc nie zależy od kolejności maili z tym
    samym Message-ID. Brak
    ``tak``/``nie`` i przeciwny zamiar Wpisów jednego numeru daje już najpóźniejszy mail z numerem, a numer dwa razy
    w dniu to stan INTERMAX, więc stoją, jak nieznany nadawca i różnica z ręczną wartością.
    """

    days: defaultdict[tuple[Login, date], set[OrderNumber]] = defaultdict(set)
    for order in orders:
        days[order.key.worker, order.key.day].add(order.key.number)

    def corrected(worker: Login, numbers: frozenset[OrderNumber], sent: tuple[datetime, MailId], on: set[date] | None) -> bool:
        return any(
            report.worker == worker
            and (report.arrived, report.mail) > sent
            and (on is None or report.day in on)
            and _repeats(numbers & days[worker, report.day], report)
            for report in reports
        )

    found: set[ReportProblem] = set()
    for problem in problems:
        match problem:
            case UnknownNumber() | ForeignOrder() | OtherDay():
                continue
            case _:
                found.add(problem)
    for read in unreadable:
        if not corrected(read.worker, read.numbers, (read.arrived, read.mail), None):
            found.add(UnreadableSubject(read.mail, read.worker, read.arrived, read.fault))
    for report in reports:
        numbers = frozenset(entry.number for entry in report.entries)
        for problem in _matching.match([report], orders)[1]:
            match problem:
                case UnknownNumber(day=day) | ForeignOrder(day=day):
                    on = {day}
                case OtherDay(order_days=order_days):
                    on = set(order_days)
                case _:
                    continue
            if not corrected(report.worker, numbers, (report.arrived, report.mail), on):
                found.add(problem)
    return found


def _repeats(numbers: frozenset[OrderNumber], report: ReadReport) -> bool:
    return bool(numbers) and numbers <= {entry.number for entry in report.entries}
