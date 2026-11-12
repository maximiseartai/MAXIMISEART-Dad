"""Poprawiony mail: problemy z błędów Wykonawcy i Zlecenia dopisane z raportu z jego literówki, które znikają, gdy
Wykonawca przyśle swój Raport wykonawcy jeszcze raz."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime

from . import _matching
from ._model import (
    Login,
    MailId,
    OrderNumber,
    ReadReport,
    ReadUnreadable,
    RefusedMove,
    RepeatedNumber,
    ReportProblem,
    UnknownNumber,
    UnreadableSubject,
)


def standing(
    problems: Iterable[ReportProblem],
    reports: Sequence[ReadReport],
    unreadable: Sequence[ReadUnreadable],
    board: _matching.Board,
    added: Mapping[OrderNumber, tuple[datetime, MailId]],
) -> set[ReportProblem]:
    """Problemy, które dalej stoją po poprawionych mailach (US 40); ``board``: zlecenia kliknięcia, jak w
    ``enter_reports``, ``added``: numery Zleceń dopisanych z raportu w tym kliknięciu z chwilą i mailem, który je
    dopisał.

    Stary mail zostaje w skrzynce, więc rdzeń liczy jego problemy przy każdym kliknięciu. Poprawionym mailem jest
    późniejszy Raport wykonawcy tego samego Wykonawcy z dnia poprawki, który ma numer każdego Wpisu wcześniejszego
    maila do zleceń tego Wykonawcy z tego dnia, a takich Wpisów jest co najmniej jeden; zlecenia Wykonawcy z dnia są
    sprzed Przeniesień Centrum, bez zleceń, które Centrum dopisało (``Board.own_numbers``). Reguła porównuje tylko
    numery: nie sprawdza ``tak``/``nie`` ani opisu i nie wymaga, żeby poprawiony mail powtórzył resztę wcześniejszego. Kolejny
    raport bez tych numerów problemu nie usuwa, bo nieznany numer może być zleceniem, którego brak w INTERMAX.
    Poprawiony mail usuwa nieznany numer z dnia z tematu, numer z kilkoma zleceniami z dniem któregoś z nich (dzień
    poprawki to dzień zlecenia), Przeniesienie na dzień, do którego nie wolno, tak samo z dniem zlecenia i nieczytelny
    temat (``unreadable``: odczyty maili z nieczytelnym tematem z numerami ich Wpisów). Nieznany numer znika też, gdy
    ten numer dopisał w tym kliknięciu późniejszy mail (od każdego Wykonawcy), bo zlecenie już jest. Ostrzeżenie
    o nieczytelnym temacie stoi, gdy któregoś odczytu z nim nie poprawiono, więc nie zależy od kolejności maili z tym
    samym Message-ID. Brak
    ``tak``/``nie`` i przeciwny zamiar Wpisów jednego numeru daje już najpóźniejszy mail z numerem, a numer dwa razy
    w dniu to stan INTERMAX, więc stoją, jak nieznany nadawca i różnica z ręczną wartością.
    """

    def corrected(worker: Login, numbers: frozenset[OrderNumber], sent: tuple[datetime, MailId], on: set[date] | None) -> bool:
        return _corrected(reports, board.own_numbers, worker, numbers, sent, on)

    found: set[ReportProblem] = set()
    for problem in problems:
        match problem:
            case UnknownNumber() | RepeatedNumber() | RefusedMove():
                continue
            case _:
                found.add(problem)
    for read in unreadable:
        if not corrected(read.worker, read.numbers, (read.arrived, read.mail), None):
            found.add(UnreadableSubject(read.mail, read.worker, read.arrived, read.fault))
    for report in reports:
        numbers = frozenset(entry.number for entry in report.entries)
        for problem in board.match([report]).problems:
            match problem:
                case UnknownNumber(number=number) if added.get(number, (report.arrived, report.mail)) > (
                    report.arrived,
                    report.mail,
                ):
                    continue
                case UnknownNumber(day=day):
                    on = {day}
                case RepeatedNumber(places=places):
                    on = {day for day, _ in places}
                case RefusedMove(order_day=order_day):
                    on = {order_day}
                case _:
                    continue
            if not corrected(report.worker, numbers, (report.arrived, report.mail), on):
                found.add(problem)
    return found


def uncorrected(
    additions: Iterable[_matching.Addition], reports: Sequence[ReadReport], board: _matching.Board
) -> tuple[_matching.Addition, ...]:
    """Zlecenia dopisane z raportu bez tych, których Raport wykonawcy poprawił późniejszy mail tego Wykonawcy z tym
    samym dniem z tematu (ta sama reguła poprawionego maila co w ``standing``, US 40): poprawiony mail nie ma ich numeru,
    bo z nim to on byłby najpóźniejszym mailem numeru, więc numer był literówką i nie staje się zleceniem. Kolejny
    raport bez numeru zlecenia Wykonawcy z pierwszego nie jest poprawką, a raport bez Wpisu do zlecenia Wykonawcy z tego
    dnia nie ma poprawki, więc ich numery się dopisują. Zlecenia Wykonawcy z dnia są sprzed Przeniesień Centrum, bez
    dopisanych (``Board.own_numbers``): Przeniesienie albo dopisanie tego kliknięcia nie zmienia więc w następnym
    kliknięciu, który mail jest poprawką, i numer odrzucony jako literówka nie dopisuje się drugim kliknięciem (własność
    N4, przegląd #1374 r5)."""

    return tuple(
        addition
        for addition in additions
        if not _corrected(
            reports,
            board.own_numbers,
            addition.worker,
            frozenset(entry.number for entry in addition.report.entries),
            (addition.arrived, addition.mail),
            {addition.day},
        )
    )


def _corrected(
    reports: Iterable[ReadReport],
    days: Mapping[tuple[Login, date], frozenset[OrderNumber]],
    worker: Login,
    numbers: frozenset[OrderNumber],
    sent: tuple[datetime, MailId],
    on: set[date] | None,
) -> bool:
    """Czy mail Wykonawcy ``worker`` z numerami ``numbers``, który przyszedł ``sent``, poprawił późniejszy Raport
    wykonawcy tego Wykonawcy z dniem z ``on`` (``None``: z każdym dniem): powtarza każdy z tych numerów, który jest
    zleceniem Wykonawcy z dnia tego Raportu, a takich jest co najmniej jeden."""

    return any(
        report.worker == worker
        and (report.arrived, report.mail) > sent
        and (on is None or report.day in on)
        and _repeats(numbers & days.get((worker, report.day), frozenset()), report)
        for report in reports
    )


def _repeats(numbers: frozenset[OrderNumber], report: ReadReport) -> bool:
    return bool(numbers) and numbers <= {entry.number for entry in report.entries}
