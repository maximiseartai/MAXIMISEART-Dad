"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Operacja Wpisania raportów to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``worker_addresses.load``), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, Przeniesienia zleceń, problemy, informacje i liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla
taty o problemie daje ``reasons.reason``, o informacji ``reasons.note``, a mail, z którego rdzeń czyta z powrotem ten
sam odczyt (odtworzenie z Logów, #1233), ``as_mail``.
Druga operacja, ``reminders_due``, mówi, które Przypomnienia o raporcie należą się teraz (ADR 0030, ``_reminders.py``).
Typy są w ``_model.py``, a rozpoznanie tematu i Wpisów, dopasowanie do zleceń, reguły komórek i postać kanoniczna maila
w pozostałych modułach ``_*.py``; moduły prywatne importuje tylko ten pakiet. Pakiet bierze tylko bibliotekę standardową
oraz ``report_cells``, ``settlement_period`` i ``text``, bo przejdzie bez zmian do Centrum w chmurze (#1161).
"""

from __future__ import annotations

from datetime import date, datetime

from . import _cells, _corrections, _entries, _figures, _matching, _moves, _subject
from ._model import (
    SUBJECT_WORD,
    ConflictingVerdicts,
    HandedOver,
    Kept,
    Login,
    MailId,
    MailRead,
    ManualDifference,
    MissingVerdict,
    MoveBar,
    MovedFrom,
    MovedTo,
    OrderDetail,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OrderState,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RefusedMove,
    RegisterOrder,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportNote,
    ReportProblem,
    ReportsOutcome,
    SenderAddress,
    SubjectFault,
    SubjectLost,
    TakenOver,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    VerdictFault,
    Window,
    WorkerAddresses,
    WorkerDay,
    note_order,
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
    "HandedOver",
    "Kept",
    "Login",
    "MailId",
    "MailRead",
    "ManualDifference",
    "MissingVerdict",
    "MoveBar",
    "MovedFrom",
    "MovedTo",
    "OrderDetail",
    "OrderedDay",
    "OrderKey",
    "OrderNumber",
    "OrderState",
    "OwnEntries",
    "OwnEntry",
    "OwnMove",
    "Pora",
    "ReadReport",
    "ReadStranger",
    "ReadUnreadable",
    "RefusedMove",
    "RegisterOrder",
    "Reminder",
    "ReminderInputs",
    "RepeatedNumber",
    "RepeatedOrder",
    "ReportEntry",
    "ReportInputs",
    "ReportMail",
    "ReportNote",
    "ReportProblem",
    "ReportsOutcome",
    "SenderAddress",
    "SentReminder",
    "SubjectFault",
    "SubjectLost",
    "TakenOver",
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
    "note_order",
    "reminder_day",
    "reminder_pora",
    "reminder_subject",
    "reminder_text",
    "reminders_due",
]


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Operacja Wpisania raportów: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``) z dniem otwartym w ``inputs.window``, a od
    Wykonawcy także z dniem w okresie z Plikiem zbiorczym od dnia wdrożenia (``Window.closes``), który daje tylko
    niezgodne Wpisy; inne maile rdzeń pomija po cichu. Temat ze słowem ``raport`` bez dnia zleceń daje
    ``UnreadableSubject``, gdy mail przyszedł od Wykonawcy w dniu otwartym. Które numery są w INTERMAX i ile mają
    zleceń, mówi każde odczytane zlecenie (``inputs.orders``, także z dni zamkniętych i po dziś), a okno mówi tylko, do
    których wolno pisać; Wpis zaczyna więc numer z co najmniej tyloma cyframi, ile ma najkrótszy numer odczytanego
    zlecenia (``_entries.entries``). Wpis trafia do zlecenia nadawcy z dnia z tematu, a bez niego do jedynego zlecenia tego
    numeru u innego Wykonawcy w tym dniu albo do jedynego zlecenia tego numeru z innego dnia: Przeniesienie zlecenia do
    nadawcy i na dzień z tematu albo, przy pomylonym temacie, do nadawcy w dniu zlecenia (ADR 0029,
    ``_matching.Board``, ``_moves.moved``), z informacją dla taty. Przy kilku Wpisach jednego zlecenia decyduje
    najpóźniejszy mail, także od innego Wykonawcy; mail z tą samą chwilą przyjścia i tym samym Message-ID rozstrzyga
    treść odczytu. Wpis zmienia pustą komórkę albo własny wpis z ``inputs.memory``, którego nikt od tamtej pory nie
    zmienił, a inna wartość komórki jest ręczna i zostaje z ``ManualDifference`` (``_cells.reconcile``); własny wpis
    pamięć ma tylko przy jedynym zleceniu numeru (``_moves._carried``). Problem z błędu Wykonawcy znika, gdy Wykonawca
    przyśle poprawiony mail (``_corrections.standing``).
    """

    window = inputs.window
    orders = tuple(inputs.orders)
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
                if worker is not None and window.opens(mail.arrived.date()):
                    numbers = frozenset(entry.number for entry in _entries.entries(mail.text, digits))
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, found, numbers))
            case date() if worker is None and window.opens(found):
                read.append(ReadStranger(mail.id, mail.arrived, found))
                problems.append(UnknownSender(mail.id, mail.sender, found))
            case date() if worker is not None and (window.opens(found) or window.closes(found)):
                entries = _entries.entries(mail.text, digits)
                read.append(ReadReport(mail.id, mail.arrived, worker, found, entries))
            case date():
                continue
    mails = tuple(sorted(read, key=_mail_order))
    reports = [found for found in mails if isinstance(found, ReadReport)]
    board = _matching.Board(orders, inputs.memory, window, inputs.ordered_days)
    matched = board.match(reports)
    moved = _moves.moved(matched.accepted, orders, inputs.memory, window)
    after = {order.row: order for order in moved.orders}
    targets = {key: (after[order.row], entry) for key, (order, entry) in matched.targets.items()}
    changes, differences, memory = _cells.reconcile(targets, moved.orders, moved.memory, inputs.kept)
    unreadable = [found for found in mails if isinstance(found, ReadUnreadable)]
    standing = _corrections.standing([*problems, *matched.problems], reports, unreadable, orders, board)
    problems_found = tuple(sorted({*standing, *differences}, key=problem_order))
    shown = [report for report in reports if window.opens(report.day)]
    opened = [order for order in moved.orders if window.opens(order.key.day)]
    figures = _figures.worker_days(opened, shown, problems_found, changes, moved.rows, frozenset(targets))
    notes = tuple(sorted((*moved.notes, *matched.lost), key=note_order))
    return ReportsOutcome(changes, problems_found, figures, mails, memory, moved.moves, notes)


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
