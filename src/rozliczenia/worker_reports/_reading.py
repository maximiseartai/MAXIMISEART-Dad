"""Odczyt okna Raportów wykonawców (ADR 0041): które maile Skrzynki raportów są Raportami wykonawców okna, od którego
Wykonawcy, z jakimi Wpisami i za które dni, w jednej kolejności; jedyny dla Wpisania raportów (``enter_reports``) i
Przypomnień o raporcie (``reminders_due``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from . import _entries, _matching, _subject
from ._model import (
    Login,
    MailId,
    MailRead,
    OrderKey,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RegisterOrder,
    ReportInputs,
    ReportSubject,
    UnknownSender,
    Window,
)


@dataclass(frozen=True)
class WindowRead:
    """Odczyty maili po ``_mail_order``, problemy nieznanych nadawców z dniem otwartym, Raporty wykonawców w tej samej
    kolejności, zlecenia kliknięcia (``board``), dla każdego Raportu wykonawcy, także z błędem tematu, każdy dzień, za
    który jest przysłany (``reported``: Wykonawca i dzień, ``_matching.Board.days``), raporty z błędem tematu, które tata
    widzi, w tej samej kolejności, z dniami otwartymi, za które się liczą (``faulty``; pusto: problem bez dnia), i każdy
    dzień otwarty, za który liczy się raport z pomylonym tematem, z jego dniem z tematu (``mistaken``: Wykonawca, dzień,
    dzień z tematu). Raport z błędem tematu z dniem z tematu, który liczy się tylko za dni spoza dni otwartych, tata nie
    widzi, jak Raport wykonawcy z takim dniem. ``faulty_entries``: zlecenia (numer, dzień, Wykonawca) z Wpisem w raporcie
    z błędem tematu za każdy dzień, za który ten raport się liczy; raport jest przysłany, więc takie zlecenie nie jest
    bez raportu, choć Centrum jego Wpisu nie wpisało."""

    mails: tuple[MailRead, ...]
    strangers: tuple[UnknownSender, ...]
    reports: tuple[ReadReport, ...]
    board: _matching.Board
    reported: tuple[tuple[Login, date], ...]
    faulty: tuple[tuple[ReadUnreadable, frozenset[date]], ...]
    mistaken: tuple[tuple[Login, date, date], ...]
    faulty_entries: frozenset[OrderKey]


def read_window(inputs: ReportInputs) -> WindowRead:
    """Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``, z rokiem literówki czytanym od dnia przyjścia
    maila): od nieznanego nadawcy z dniem otwartym w ``inputs.window``, a od Wykonawcy z co najmniej jednym Wpisem (mail
    bez Wpisów nie jest raportem, ADR 0041) i z dniem otwartym, z dniem w okresie
    z Plikiem zbiorczym od dnia wdrożenia (``Window.closes``) albo z każdym innym dniem, gdy temat jest pomylony (ADR
    0029: numery zleceń z innego dnia wygrywają z datą, także z datą po dziś); inne maile pomija po cichu. Temat ze
    słowem ``raport`` bez dnia zleceń daje raport z błędem tematu (``ReadUnreadable``), gdy mail z Wpisami przyszedł od
    Wykonawcy w dniu otwartym. Wpis zaczyna numer z co najmniej tyloma cyframi, ile ma najkrótszy numer odczytanego
    zlecenia (``_entries.entries``). Za które dni liczy się raport z błędem tematu, mówi ``_faulty``."""

    window = inputs.window
    orders = tuple(inputs.orders)
    digits = min((len(order.key.number) for order in orders), default=1)
    board = _matching.Board(orders, inputs.memory, window, inputs.ordered_days, inputs.present)
    read: list[MailRead] = []
    strangers: list[UnknownSender] = []
    for mail in inputs.mails:
        found = _subject.read(mail.subject, mail.arrived.date())
        worker = inputs.addresses.logins.get(mail.sender)
        match found:
            case None:
                continue
            case _subject.FaultySubject(fault=fault, day=day):
                numbers = frozenset(entry.number for entry in _entries.entries(mail.text, digits))
                if worker is not None and window.opens(mail.arrived.date()) and numbers:
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, fault, numbers, day, ReportSubject(mail.subject)))
            case date() if worker is None and window.opens(found):
                read.append(ReadStranger(mail.id, mail.arrived, found))
                strangers.append(UnknownSender(mail.id, mail.sender, found))
            case date() if worker is not None:
                report = ReadReport(mail.id, mail.arrived, worker, found, _entries.entries(mail.text, digits))
                if report.entries and (window.opens(found) or window.closes(found) or _days(board, report) != {found}):
                    read.append(report)
            case date():
                continue
    mails = tuple(sorted(read, key=_mail_order))
    reports = tuple(found for found in mails if isinstance(found, ReadReport))
    reported = [(report.worker, day) for report in reports for day in sorted(_days(board, report))]
    mistaken = [
        (report.worker, day, report.day)
        for report in reports
        for day in sorted(_days(board, report) - {report.day})
        if window.opens(day)
    ]
    unreadable = [found for found in mails if isinstance(found, ReadUnreadable)]
    counted = _faulty(unreadable, reported, orders, window, inputs.entering_rollout or window.rollout, board)
    reported += [(found.worker, day) for found in unreadable for day in sorted(counted[found])]
    faulty = tuple(
        (found, shown)
        for found in unreadable
        if (shown := frozenset(filter(window.opens, counted[found]))) or found.day is None
    )
    entries = frozenset(
        OrderKey(number, day, found.worker) for found in unreadable for day in counted[found] for number in found.numbers
    )
    return WindowRead(mails, tuple(strangers), reports, board, tuple(reported), faulty, tuple(mistaken), entries)


def _days(board: _matching.Board, report: ReadReport) -> frozenset[date]:
    return board.days((entry.number for entry in report.entries), report.day)


def _faulty(
    unreadable: Sequence[ReadUnreadable],
    reported: Sequence[tuple[Login, date]],
    orders: Sequence[RegisterOrder],
    window: Window,
    since: date,
    board: _matching.Board,
) -> dict[ReadUnreadable, frozenset[date]]:
    """Dni, za które liczy się każdy raport z błędem tematu (ADR 0041), z numerami zleceń, które wygrywają z datą jak przy
    pomylonym temacie (``Board.days``): dzień z tematu, gdy da się go przeczytać, a bez niego dzień wskazany, czyli
    ostatni dzień otwarty Wykonawcy ze zleceniami, nie wcześniejszy niż dzień wdrożenia Wpisania raportów ``since`` i nie
    późniejszy niż dzień przyjścia maila, za który nie ma innego raportu (``reported`` i raporty z błędem tematu z dniem
    z tematu, potem bez niego po ``_mail_order``). Bez dnia z
    tematu i bez wskazanego dnia raport nie liczy się za żaden dzień (pusto: problem bez dnia)."""

    counted: dict[ReadUnreadable, frozenset[date]] = {}
    taken = set(reported)
    for found in sorted(dict.fromkeys(unreadable), key=lambda found: found.day is None):
        day = found.day or _indicated(found, orders, window, since, taken)
        counted[found] = frozenset() if day is None else board.days(sorted(found.numbers), day)
        taken.update((found.worker, counted_day) for counted_day in counted[found])
    return counted


def _indicated(
    found: ReadUnreadable, orders: Sequence[RegisterOrder], window: Window, since: date, taken: set[tuple[Login, date]]
) -> date | None:
    days = {
        order.key.day
        for order in orders
        if order.key.worker == found.worker
        and window.opens(order.key.day)
        and since <= order.key.day <= found.arrived.date()
        and (found.worker, order.key.day) not in taken
    }
    return max(days, default=None)


def _mail_order(found: MailRead) -> tuple[datetime, MailId, str, tuple[str, ...]]:
    """Chwila przyjścia, mail, a przy remisie (Message-ID ustawia nadawca) rodzaj i każde pole odczytu, więc dwa różne
    odczyty nigdy nie mają równego miejsca."""

    match found:
        case ReadReport(worker=worker, day=day, entries=entries):
            content = (
                part
                for entry in entries
                for part in (
                    entry.number,
                    "" if entry.verdict is None else entry.verdict.value,
                    "" if entry.fault is None else entry.fault.name,
                    entry.activities,
                )
            )
            return found.arrived, found.mail, "report", (worker, day.isoformat(), *content)
        case ReadUnreadable(worker=worker, fault=fault, numbers=numbers, day=day, subject=subject):
            said = (fault.name, "" if day is None else day.isoformat(), subject.shown())
            return found.arrived, found.mail, "unreadable", (worker, *said, *sorted(numbers))
        case ReadStranger(day=day):
            return found.arrived, found.mail, "stranger", (day.isoformat(),)
