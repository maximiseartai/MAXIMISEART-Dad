"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Jedyna operacja to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``worker_addresses.load``), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, problemy, liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla taty o problemie daje
``reasons.reason``. Typy są w ``_model.py``, a rozpoznanie tematu i Wpisów, dopasowanie do zleceń i reguły komórek w
pozostałych modułach ``_*.py``; moduły prywatne importuje tylko ten pakiet. Pakiet bierze tylko bibliotekę standardową
oraz ``report_cells``, ``settlement_period`` i ``text``, bo przejdzie bez zmian do Centrum w chmurze (#1161).
"""

from __future__ import annotations

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

    Liczy się tylko mail z tematem ``Raport dd.mm.rrrr`` z dniem otwartym w ``inputs.window``; inne maile rdzeń pomija
    po cichu. Wpis trafia tylko do zlecenia nadawcy z dnia z tematu i tylko do pustej komórki, a przy kilku Wpisach
    jednego zlecenia wygrywa najpóźniejszy mail.
    """

    orders = tuple(order for order in inputs.orders if inputs.window.opens(order.key.day))
    read: list[MailRead] = []
    problems: list[ReportProblem] = []
    for mail in inputs.mails:
        day = _subject.day_of(mail.subject)
        if day is None or not inputs.window.opens(day):
            continue
        worker = inputs.addresses.logins.get(mail.sender)
        if worker is None:
            read.append(ReadStranger(mail.id, mail.arrived, day))
            problems.append(UnknownSender(mail.id, mail.sender, day))
        else:
            read.append(ReadReport(mail.id, mail.arrived, worker, day, _entries.entries(mail.text)))
    mails = tuple(sorted(read, key=lambda found: (found.arrived, found.mail)))
    reports = [found for found in mails if isinstance(found, ReadReport)]
    targets, unmatched = _matching.match(reports, orders)
    changes, memory = _cells.reconcile(targets, orders, inputs.memory)
    found = tuple(sorted({*problems, *unmatched}, key=problem_order))
    return ReportsOutcome(changes, found, _figures.worker_days(orders, reports, found, changes), mails, memory)
