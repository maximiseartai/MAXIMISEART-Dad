"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Operacja Wpisania raportów to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``worker_addresses.load``), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, problemy, liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla taty o problemie daje
``reasons.reason``, a mail, z którego rdzeń czyta z powrotem ten sam odczyt (odtworzenie z Logów, #1233), ``as_mail``.
Druga operacja, ``reminders_due``, mówi, które Przypomnienia o raporcie należą się teraz (ADR 0030, ``_reminders.py``).
Typy są w ``_model.py``, a rozpoznanie tematu i Wpisów, dopasowanie do zleceń, reguły komórek i postać kanoniczna maila
w pozostałych modułach ``_*.py``; moduły prywatne importuje tylko ten pakiet. Pakiet bierze tylko bibliotekę standardową
oraz ``report_cells``, ``settlement_period`` i ``text``, bo przejdzie bez zmian do Centrum w chmurze (#1161).
"""

from __future__ import annotations

from datetime import date, datetime

from . import _cells, _corrections, _entries, _figures, _matching, _subject
from ._model import (
    SUBJECT_WORD,
    ConflictingVerdicts,
    ForeignOrder,
    Kept,
    Login,
    MailId,
    MailRead,
    ManualDifference,
    MissingVerdict,
    OrderDetail,
    OrderKey,
    OrderNumber,
    OrderState,
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
from ._canonical import as_mail
from ._reminders import (
    EXAMPLE_NUMBERS,
    FIRST_REMINDER,
    Pora,
    Reminder,
    ReminderInputs,
    SentReminder,
    reminder_pora,
    reminder_text,
    reminders_due,
)
from ._subject import reminder_day, reminder_subject

__all__ = [
    "EXAMPLE_NUMBERS",
    "FIRST_REMINDER",
    "SUBJECT_WORD",
    "ConflictingVerdicts",
    "ForeignOrder",
    "Kept",
    "Login",
    "MailId",
    "MailRead",
    "ManualDifference",
    "MissingVerdict",
    "OrderDetail",
    "OrderKey",
    "OrderNumber",
    "OrderState",
    "OtherDay",
    "OwnEntries",
    "OwnEntry",
    "Pora",
    "ReadReport",
    "ReadStranger",
    "ReadUnreadable",
    "RegisterOrder",
    "Reminder",
    "ReminderInputs",
    "RepeatedOrder",
    "ReportEntry",
    "ReportInputs",
    "ReportMail",
    "ReportProblem",
    "ReportsOutcome",
    "SenderAddress",
    "SentReminder",
    "SubjectFault",
    "UnknownNumber",
    "UnknownSender",
    "UnreadableSubject",
    "Verdict",
    "VerdictFault",
    "Window",
    "WorkerAddresses",
    "WorkerDay",
    "as_mail",
    "enter_reports",
    "reminder_day",
    "reminder_pora",
    "reminder_subject",
    "reminder_text",
    "reminders_due",
]


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Operacja Wpisania raportów: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``) z dniem otwartym w ``inputs.window``; inne maile
    rdzeń pomija po cichu. Temat ze słowem ``raport`` bez dnia zleceń daje ``UnreadableSubject``, gdy mail przyszedł od
    Wykonawcy w dniu otwartym. Wpis zaczyna numer z co najmniej tyloma cyframi, ile ma najkrótszy numer zlecenia z dni
    otwartych (``_entries.entries``). Wpis trafia tylko do zlecenia nadawcy z dnia z tematu, a przy kilku Wpisach jednego
    zlecenia decyduje najpóźniejszy mail; mail z tą samą chwilą przyjścia i tym samym Message-ID rozstrzyga treść
    odczytu. Wpis zmienia pustą komórkę albo własny wpis z ``inputs.memory``, którego nikt od tamtej pory nie zmienił, a
    inna wartość komórki jest ręczna i zostaje z ``ManualDifference`` (``_cells.reconcile``). Problem z błędu Wykonawcy
    znika, gdy Wykonawca przyśle poprawiony mail (``_corrections.standing``).
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
                    numbers = frozenset(entry.number for entry in _entries.entries(mail.text, digits))
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, found, numbers))
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
    changes, differences, memory = _cells.reconcile(targets, orders, inputs.memory, inputs.kept)
    unreadable = [found for found in mails if isinstance(found, ReadUnreadable)]
    standing = _corrections.standing([*problems, *unmatched], reports, unreadable, orders)
    problems_found = tuple(sorted({*standing, *differences}, key=problem_order))
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
        case ReadUnreadable(worker=worker, fault=fault, numbers=numbers):
            return found.arrived, found.mail, "unreadable", (worker, fault.name, *sorted(numbers))
        case ReadStranger(day=day):
            return found.arrived, found.mail, "stranger", (day.isoformat(),)
