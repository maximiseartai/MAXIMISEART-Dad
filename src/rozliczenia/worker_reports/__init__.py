"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Jedyna operacja to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``worker_addresses.load``), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, Przeniesienia zleceń, problemy, informacje i liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla
taty o problemie daje ``reasons.reason``, o informacji ``reasons.note``, a mail, z którego rdzeń czyta z powrotem ten sam odczyt (odtworzenie z Logów, #1233), ``as_mail``.
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
    ForeignOrder,
    HandedOver,
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
    OwnMove,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportNote,
    ReportProblem,
    ReportsOutcome,
    SenderAddress,
    SubjectFault,
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

__all__ = [
    "SUBJECT_WORD",
    "ConflictingVerdicts",
    "ForeignOrder",
    "HandedOver",
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
    "OwnMove",
    "ReadReport",
    "ReadStranger",
    "ReadUnreadable",
    "RegisterOrder",
    "RepeatedOrder",
    "ReportEntry",
    "ReportInputs",
    "ReportMail",
    "ReportNote",
    "ReportProblem",
    "ReportsOutcome",
    "SenderAddress",
    "SubjectFault",
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
]


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Jedyna operacja rdzenia: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Liczy się tylko mail z tematem Raportu wykonawcy (``_subject.read``) z dniem otwartym w ``inputs.window``; inne maile
    rdzeń pomija po cichu. Temat ze słowem ``raport`` bez dnia zleceń daje ``UnreadableSubject``, gdy mail przyszedł od
    Wykonawcy w dniu otwartym. Wpis zaczyna numer z co najmniej tyloma cyframi, ile ma najkrótszy numer zlecenia z dni
    otwartych (``_entries.entries``). Wpis trafia do zlecenia nadawcy z dnia z tematu, a bez niego do jedynego zlecenia
    tego numeru u innego Wykonawcy w tym dniu, które wtedy przechodzi do nadawcy (Przeniesienie zlecenia, ADR 0029,
    ``_matching.match``, ``_moves.moved``) z informacją dla taty po obu stronach. Przy kilku Wpisach jednego zlecenia
    decyduje najpóźniejszy mail, także od innego Wykonawcy; mail z tą samą chwilą przyjścia i tym samym Message-ID
    rozstrzyga treść odczytu. Wpis zmienia pustą komórkę albo własny wpis z ``inputs.memory``, którego nikt od tamtej pory nie zmienił, a
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
    remembered = {(move.number, move.day): move for move in inputs.memory.moves}
    matched = _matching.match(reports, orders, remembered)
    moved = _moves.moved(matched.transfers, orders, inputs.memory, inputs.window)
    after = {order.row: order for order in moved.orders}
    targets = {key: (after[order.row], entry) for key, (order, entry) in matched.targets.items()}
    changes, differences, memory = _cells.reconcile(targets, moved.orders, moved.memory, inputs.kept)
    unreadable = [found for found in mails if isinstance(found, ReadUnreadable)]
    standing = _corrections.standing([*problems, *matched.problems], reports, unreadable, orders, remembered)
    problems_found = tuple(sorted({*standing, *differences}, key=problem_order))
    figures = _figures.worker_days(moved.orders, reports, problems_found, changes, moved.rows)
    return ReportsOutcome(changes, problems_found, figures, mails, memory, moved.moves, moved.notes)


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
