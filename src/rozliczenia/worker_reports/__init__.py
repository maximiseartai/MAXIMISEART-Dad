"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Jedyna operacja to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``worker_addresses.load``), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, problemy, liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla taty o problemie daje
``reasons.reason``. Typy są w ``_model.py``, a rozpoznanie tematu i Wpisów, dopasowanie do zleceń i reguły komórek w
pozostałych modułach ``_*.py``; moduły prywatne importuje tylko ten pakiet. Pakiet bierze tylko bibliotekę standardową
oraz ``report_cells``, ``settlement_period`` i ``text``, bo przejdzie bez zmian do Centrum w chmurze (#1161).
"""

from __future__ import annotations

from datetime import date, datetime

from . import _cells, _entries, _figures, _matching, _subject
from ._model import (
    SUBJECT_WORD,
    ForeignOrder,
    Kept,
    Login,
    MailId,
    MailRead,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnEntries,
    OwnEntry,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportProblem,
    ReportsOutcome,
    SenderAddress,
    SubjectFault,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    VerdictFault,
    Window,
    WorkerAddresses,
    WorkerDay,
    problem_order,
)

__all__ = [
    "SUBJECT_WORD",
    "ForeignOrder",
    "Kept",
    "Login",
    "MailId",
    "MailRead",
    "ManualDifference",
    "MissingVerdict",
    "OrderKey",
    "OrderNumber",
    "OtherDay",
    "OwnEntries",
    "OwnEntry",
    "ReadReport",
    "ReadStranger",
    "ReadUnreadable",
    "RegisterOrder",
    "RepeatedOrder",
    "ReportEntry",
    "ReportInputs",
    "ReportMail",
    "ReportProblem",
    "ReportsOutcome",
    "SenderAddress",
    "SubjectFault",
    "UnknownNumber",
    "UnknownSender",
    "UnreadableSubject",
    "Verdict",
    "VerdictFault",
    "Window",
    "WorkerAddresses",
    "WorkerDay",
    "enter_reports",
]


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Jedyna operacja rdzenia: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``) z dniem otwartym w ``inputs.window``; inne maile
    rdzeń pomija po cichu. Temat ze słowem ``raport`` bez dnia zleceń daje ``UnreadableSubject``, gdy mail przyszedł od
    Wykonawcy w dniu otwartym. Wpis zaczyna numer z co najmniej tyloma cyframi, ile ma najkrótszy numer zlecenia z dni
    otwartych (``_entries.entries``). Wpis trafia tylko do zlecenia nadawcy z dnia z tematu i tylko do pustej komórki, a przy
    kilku Wpisach jednego zlecenia decyduje najpóźniejszy mail; mail z tą samą chwilą przyjścia i tym samym Message-ID
    rozstrzyga treść odczytu.
    """

    orders = tuple(order for order in inputs.orders if inputs.window.opens(order.key.day))
    digits = min((len(order.key.number) for order in orders), default=1)
    read: list[MailRead] = []
    problems: list[ReportProblem] = []
    for mail in inputs.mails:
        found = _subject.read(mail.subject)
        worker = inputs.addresses.logins.get(mail.sender)
        match found:
            case None:
                continue
            case SubjectFault():
                if worker is not None and inputs.window.opens(mail.arrived.date()):
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, found))
                    problems.append(UnreadableSubject(mail.id, worker, mail.arrived, found))
            case date() if not inputs.window.opens(found):
                continue
            case date() if worker is None:
                read.append(ReadStranger(mail.id, mail.arrived, found))
                problems.append(UnknownSender(mail.id, mail.sender, found))
            case date():
                entries = _entries.entries(mail.text, digits)
                read.append(ReadReport(mail.id, mail.arrived, worker, found, entries))
    mails = tuple(sorted(read, key=_mail_order))
    reports = [found for found in mails if isinstance(found, ReadReport)]
    targets, unmatched = _matching.match(reports, orders)
    changes, memory = _cells.reconcile(targets, orders, inputs.memory)
    problems_found = tuple(sorted({*problems, *unmatched}, key=problem_order))
    return ReportsOutcome(
        changes, problems_found, _figures.worker_days(orders, reports, problems_found, changes), mails, memory
    )


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
        case ReadUnreadable(worker=worker, fault=fault):
            return found.arrived, found.mail, "unreadable", (worker, fault.name)
        case ReadStranger(day=day):
            return found.arrived, found.mail, "stranger", (day.isoformat(),)
