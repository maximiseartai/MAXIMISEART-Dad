"""Odczyt okna Raportów wykonawców (ADR 0041): które maile Skrzynki raportów są Raportami wykonawców okna, od którego
Wykonawcy, z jakimi Wpisami i za które dni, w jednej kolejności; jedyny dla Wpisania raportów (``enter_reports``) i
Przypomnień o raporcie (``reminders_due``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from . import _entries, _matching, _subject
from ._model import (
    Login,
    MailId,
    MailRead,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    ReportInputs,
    SubjectFault,
    UnknownSender,
)


@dataclass(frozen=True)
class WindowRead:
    """Odczyty maili po ``_mail_order``, problemy nieznanych nadawców z dniem otwartym, Raporty wykonawców w tej samej
    kolejności, zlecenia kliknięcia (``board``) i dla każdego Raportu wykonawcy każdy dzień, za który jest przysłany
    (``reported``: Wykonawca i dzień, ``_matching.Board.days``)."""

    mails: tuple[MailRead, ...]
    strangers: tuple[UnknownSender, ...]
    reports: tuple[ReadReport, ...]
    board: _matching.Board
    reported: tuple[tuple[Login, date], ...]


def read_window(inputs: ReportInputs) -> WindowRead:
    """Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``, z rokiem literówki czytanym od dnia przyjścia
    maila): od nieznanego nadawcy z dniem otwartym w ``inputs.window``, a od Wykonawcy z co najmniej jednym Wpisem (mail
    bez Wpisów nie jest raportem, ADR 0041) i z dniem otwartym, z dniem w okresie
    z Plikiem zbiorczym od dnia wdrożenia (``Window.closes``) albo z każdym innym dniem, gdy temat jest pomylony (ADR
    0029: numery zleceń z innego dnia wygrywają z datą, także z datą po dziś); inne maile pomija po cichu. Temat ze
    słowem ``raport`` bez dnia zleceń daje ``ReadUnreadable``, gdy mail z Wpisami przyszedł od Wykonawcy w dniu otwartym. Wpis
    zaczyna numer z co najmniej tyloma cyframi, ile ma najkrótszy numer odczytanego zlecenia (``_entries.entries``)."""

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
            case SubjectFault():
                numbers = frozenset(entry.number for entry in _entries.entries(mail.text, digits))
                if worker is not None and window.opens(mail.arrived.date()) and numbers:
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, found, numbers))
            case date() if worker is None and window.opens(found):
                read.append(ReadStranger(mail.id, mail.arrived, found))
                strangers.append(UnknownSender(mail.id, mail.sender, found))
            case date() if worker is not None:
                report = ReadReport(mail.id, mail.arrived, worker, found, _entries.entries(mail.text, digits))
                if report.entries and (window.opens(found) or window.closes(found) or board.days(report) != {found}):
                    read.append(report)
            case date():
                continue
    mails = tuple(sorted(read, key=_mail_order))
    reports = tuple(found for found in mails if isinstance(found, ReadReport))
    reported = tuple((report.worker, day) for report in reports for day in sorted(board.days(report)))
    return WindowRead(mails, tuple(strangers), reports, board, reported)


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
        case ReadUnreadable(worker=worker, fault=fault, numbers=numbers):
            return found.arrived, found.mail, "unreadable", (worker, fault.name, *sorted(numbers))
        case ReadStranger(day=day):
            return found.arrived, found.mail, "stranger", (day.isoformat(),)
