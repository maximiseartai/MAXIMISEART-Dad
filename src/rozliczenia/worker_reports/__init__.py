"""Rdzeń raportów Wpisania raportów (ADR 0028): Raporty wykonawców bez Excela i bez IMAP.

Operacja Wpisania raportów to ``enter_reports``: maile ze Skrzynki raportów (``worker_report_inbox``), adresy Wykonawców
(``WorkerList.addresses`` z Listy Wykonawców), uporządkowane zlecenia INTERMAX, dni otwarte i pamięć własnych wpisów na wejściu, a zmiany
komórek, Przeniesienia zleceń, problemy, informacje i liczby dla widoku Raporty i nowa pamięć na wyjściu. Zdanie dla
taty o problemie daje ``reasons.reason``, o informacji ``reasons.note``, a mail, z którego rdzeń czyta z powrotem ten
sam odczyt (odtworzenie z Logów), ``as_mail``.
Druga operacja, ``reminders_due``, mówi, które Przypomnienia o raporcie należą się teraz (ADR 0030, ADR 0041,
``_reminders.py``). Obie biorą Raporty wykonawców i ich dni z jednego odczytu okna (``_reading.py``), a Wpisanie czyta
opis Wpisu ``tak`` Legendą czynności z wejścia (``_descriptions.py``, ADR 0039).
Typy są w ``_model.py``, a rozpoznanie tematu i Wpisów, dopasowanie do zleceń, reguły komórek i postać kanoniczna maila
w pozostałych modułach ``_*.py``; moduły prywatne importuje tylko ten pakiet. Pakiet bierze tylko bibliotekę standardową
oraz ``report_cells``, ``settlement_period``, ``text`` i ``activity_legend``, bo przejdzie bez zmian do Centrum w
chmurze.
"""

from __future__ import annotations

from . import _cells, _corrections, _descriptions, _figures, _moves, _reading
from ._model import (
    ADDED_DIGITS,
    SUBJECT_WORD,
    AddBar,
    Added,
    ConflictingVerdicts,
    FaultyDescription,
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
    OlderOwnEntries,
    OrderDetail,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OrderState,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadNumber,
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
    Requestable,
    RequestedEntry,
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
    order_number,
    problem_order,
)
from ._canonical import as_mail
from ._entries import EXAMPLE_NUMBERS
from ._reminders import (
    DAY_FIELD,
    DEFAULT_REMINDERS,
    DEFAULT_SCHEDULE,
    DEFAULT_TEXT,
    OLD_VERSION_SCHEDULES,
    Pora,
    Reminder,
    ReminderInputs,
    ReminderProblem,
    ReminderProblemKind,
    ReminderSchedule,
    ReminderSettings,
    ScheduleSince,
    SchedulesInEffect,
    SentReminder,
    TimeRange,
    reminder_pora,
    reminder_text,
    reminders_due,
)
from ._subject import reads_as_report, reminder_day, reminder_subject

__all__ = [
    "ADDED_DIGITS",
    "DAY_FIELD",
    "DEFAULT_REMINDERS",
    "DEFAULT_SCHEDULE",
    "DEFAULT_TEXT",
    "EXAMPLE_NUMBERS",
    "OLD_VERSION_SCHEDULES",
    "SUBJECT_WORD",
    "AddBar",
    "Added",
    "ConflictingVerdicts",
    "FaultyDescription",
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
    "OlderOwnEntries",
    "OrderDetail",
    "OrderedDay",
    "OrderKey",
    "OrderNumber",
    "OrderState",
    "OwnEntries",
    "OwnEntry",
    "OwnMove",
    "Pora",
    "ReadNumber",
    "ReadReport",
    "ReadStranger",
    "ReadUnreadable",
    "RefusedMove",
    "RegisterOrder",
    "Reminder",
    "ReminderInputs",
    "ReminderProblem",
    "ReminderProblemKind",
    "ReminderSchedule",
    "ReminderSettings",
    "RepeatedNumber",
    "RepeatedOrder",
    "ReportEntry",
    "ReportInputs",
    "ReportMail",
    "ReportNote",
    "ReportProblem",
    "ReportsOutcome",
    "Requestable",
    "RequestedEntry",
    "ScheduleSince",
    "SchedulesInEffect",
    "SenderAddress",
    "SentReminder",
    "SubjectFault",
    "SubjectLost",
    "TakenOver",
    "TimeRange",
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
    "order_number",
    "reads_as_report",
    "reminder_day",
    "reminder_pora",
    "reminder_subject",
    "reminder_text",
    "reminders_due",
]


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Operacja Wpisania raportów: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Które maile są Raportami wykonawców i za które dni, mówi odczyt okna (``_reading.read_window``), ten sam co w
    Przypomnieniach o raporcie: mail od Wykonawcy bez żadnego Wpisu nie jest raportem (ADR 0041), Raport z dniem w
    okresie z Plikiem zbiorczym albo spoza okna daje tylko niezgodne Wpisy, a temat Raportu wykonawcy bez dnia zleceń
    daje ``UnreadableSubject``, gdy mail z Wpisami przyszedł od Wykonawcy w dniu otwartym. Liczba Raportów wykonawców dnia w widoku
    Raporty liczy Raport za każdy dzień, za który jest przysłany (``WindowRead.reported``). Które numery są w INTERMAX i ile mają
    zleceń, mówi każde odczytane zlecenie (``inputs.orders``, także z dni zamkniętych i po dziś), a okno mówi tylko, do
    których wolno pisać; Wpis zaczyna więc numer z co najmniej tyloma cyframi, ile ma najkrótszy numer odczytanego
    zlecenia (``_entries.entries``). Wpis trafia do zlecenia nadawcy z dnia z tematu, a bez niego do jedynego zlecenia tego
    numeru u innego Wykonawcy w tym dniu albo do jedynego zlecenia tego numeru z innego dnia: Przeniesienie zlecenia do
    nadawcy i na dzień z tematu albo, przy pomylonym temacie, do nadawcy w dniu zlecenia (ADR 0029,
    ``_matching.Board``, ``_moves.moved``), z informacją dla taty. Zlecenia numeru, który stoi w kilku przeczytanych
    wierszach (``inputs.present``, także w wierszu bez zlecenia), Wpis nie przenosi. Numer, którego INTERMAX nie ma w żadnym przeczytanym
    wierszu (``inputs.present``, jedyna odpowiedź na pytanie, czy INTERMAX ma numer), w postaci numeru z aplikacji
    firmowej (``ADDED_DIGITS`` cyfr), to Zlecenie dopisane z raportu pod zleceniami nadawcy w dniu z tematu, gdy ten
    jest Dniem uporządkowanym, a temat nie jest pomylony (inaczej, także dla numeru z wiersza bez zlecenia,
    ``UnknownNumber`` z powodem ``AddBar``), a jego Raportu wykonawcy nie poprawił późniejszy mail
    (``_corrections.uncorrected``); jego ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` trafiają do pamięci jak własne
    wpisy. Przy kilku Wpisach jednego zlecenia decyduje najpóźniejszy mail, także od innego Wykonawcy; mail z tą samą
    chwilą przyjścia i tym samym Message-ID rozstrzyga treść odczytu. Wpis zmienia pustą komórkę albo własny wpis z
    ``inputs.memory``, którego nikt od tamtej pory nie zmienił, a inna wartość komórki jest ręczna i zostaje z
    ``ManualDifference`` (``_cells.reconcile``); własny wpis pamięć ma tylko przy jedynym zleceniu numeru
    (``_moves._carried``). Wpis ``tak`` z Błędem opisu (Legenda czynności ``inputs.legend``) wpisuje się jak każdy, bo
    bez ``SKUTECZNE`` Przygotowanie pliku zbiorczego się zatrzymuje, a tata widzi przy nim problem
    ``FaultyDescription``, dopóki zlecenie nie dostanie poprawnego Wpisu (ADR 0039, ``_descriptions.entered``). Problem
    z błędu Wykonawcy znika, gdy Wykonawca przyśle poprawiony mail (``_corrections.standing``). Decyzja taty Wpisu na
    życzenie (``inputs.requested``) wpisuje Wpis ze znakiem zamiast ``tak``/``nie`` jak Wpis z chwilą kliknięcia
    (``_matching.Board.match``).
    """

    window = inputs.window
    orders = tuple(inputs.orders)
    read = _reading.read_window(inputs)
    mails, reports, board = read.mails, list(read.reports), read.board
    problems: list[ReportProblem] = list(read.strangers)
    matched = board.match(reports, inputs.requested)
    additions = _corrections.uncorrected(matched.added, reports, board)
    described = _descriptions.entered(inputs.legend, matched.entered, additions)
    moved = _moves.moved(matched.accepted, additions, orders, inputs.memory, window)
    after = {order.row: order for order in moved.orders}
    targets = {key: (after[order.row], entry) for key, (order, entry) in matched.targets.items()}
    changes, differences, memory = _cells.reconcile(targets, moved.orders, moved.memory, inputs.kept)
    added = {OrderKey(found.number, found.day, found.worker): found for found in additions}
    memory = _cells.with_added(memory, ((key, found.verdict, found.activities) for key, found in added.items()))
    unreadable = [found for found in mails if isinstance(found, ReadUnreadable)]
    newest = {found.number: (found.arrived, found.mail) for found in additions}
    standing = _corrections.standing([*problems, *matched.problems, *described], reports, unreadable, board, newest)
    problems_found = tuple(sorted({*standing, *differences}, key=problem_order))
    shown = [report for report in reports if window.opens(report.day)]
    reported = [(day, worker) for worker, day in read.reported if window.opens(day)]
    details = [
        (key, OrderDetail(found.number, found.verdict.value, found.activities or None, True))
        for key, found in added.items()
    ]
    opened = [order for order in moved.orders if window.opens(order.key.day)]
    figures = _figures.worker_days(
        opened, shown, reported, problems_found, changes, moved.rows, frozenset(targets), details, inputs.legend
    )
    notes = tuple(sorted((*moved.notes, *matched.lost), key=note_order))
    return ReportsOutcome(changes, problems_found, figures, mails, memory, moved.moves, notes, moved.added)

