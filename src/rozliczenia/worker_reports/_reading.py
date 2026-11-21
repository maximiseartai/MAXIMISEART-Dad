"""Odczyt okna Raportów wykonawców (ADR 0041): które maile Skrzynki raportów są Raportami wykonawców okna, od którego
Wykonawcy, z jakimi Wpisami i za które dni, w jednej kolejności; jedyny dla Wpisania raportów (``enter_reports``) i
Przypomnień o raporcie (``reminders_due``)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..report_cells import OrderRow
from . import _corrections, _descriptions, _entries, _mails, _matching, _subject
from ._model import (
    Login,
    MailEntryKey,
    MailId,
    MailRead,
    Offer,
    OrderKey,
    OvertakenSubject,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RegisterOrder,
    ReportProblem,
    ReportEntry,
    ReportInputs,
    ReportSubject,
    UnknownSender,
    Window,
)


@dataclass(frozen=True)
class WindowRead:
    """Odczyty maili po ``_mail_order``, dla każdego Raportu wykonawcy, także z błędem tematu, każdy dzień, za który
    jest przysłany (``reported``: Wykonawca i dzień, ``_matching.Board.days``), i każdy dzień otwarty, za który liczy
    się raport z pomylonym tematem, z jego dniem z tematu (``mistaken``: Wykonawca, dzień, dzień z tematu). Raport z
    błędem tematu z dniem z tematu, który liczy się tylko za dni spoza dni otwartych, tata nie widzi, jak Raport
    wykonawcy z takim dniem, a raportu, którego każdy Wpis tata wpisał Wpisem na życzenie, tata już nie widzi jako błędu
    (``_settled``), także gdy pozostałe zlecenia wziął późniejszy mail. Raport z błędem tematu, którego każde zlecenie
    wziął późniejszy mail, też nie jest błędem, tylko informacją przy każdym dniu otwartym, za który się liczy
    (``overtaken``, ``_overtaken``), bo nie ma z niego czego wpisać. ``faulty_entries``: zlecenia (numer, dzień,
    Wykonawca) z Wpisem w raporcie z błędem tematu za każdy dzień, za który ten raport się liczy; raport jest przysłany,
    więc takie zlecenie nie jest bez raportu, choć Centrum jego Wpisu nie wpisało.

    Wpis na życzenie przy raporcie z błędem tematu (ADR 0041) ma kształt Wpisu Raportu wykonawcy z dniem zlecenia w
    temacie: ``offers`` to Wpis na życzenie przy wierszu każdego zlecenia, o którym decyduje Wpis takiego raportu,
    gdy Centrum wie, co wpisać (``_offers``), a Wpisy, przy których tata kliknął (``inputs.requested``), są Raportami
    wykonawcy tego maila z dniem decyzji (``_mails.requested_reports``) wśród Raportów wykonawców Wpisania raportów.

    Odczyty maili (``mails``) są tylko w kapsule ``WindowMails``, z której wychodzą fakty, a Raporty wykonawców
    Wpisania raportów (z dniem z tematu i Wpisy na życzenie, po kolei maili, więc późniejszy mail wygrywa z Wpisem na
    życzenie jak z każdym Wpisem wcześniejszego) nie są polem odczytu: ``read_window`` daje z nich tylko wyniki, bo
    własne przejście po nich nie zna raportu z błędem tematu. ``said``: zlecenia (numer, dzień, Wykonawca) z ich
    Wpisem, z dniem z tematu, a Wpis na życzenie z dniem decyzji taty (``WindowMails.said`` z decyzjami
    ``inputs.requested``); ``matched``: zwycięski Wpis
    każdego zlecenia (``Board.match``); ``additions``: Zlecenia dopisane z raportu, którego nie poprawił późniejszy
    Raport wykonawcy (``_corrections.uncorrected``); ``standing``: problemy nieznanych nadawców z dniem otwartym,
    Wpisów i Błędów opisu (``_descriptions.entered``) z raportami z błędem tematu, które tata widzi, bez tych, które
    zdjął poprawiony mail Wykonawcy (``_corrections.standing``)."""

    mails: _mails.WindowMails
    reported: tuple[tuple[Login, date], ...]
    mistaken: tuple[tuple[Login, date, date], ...]
    faulty_entries: frozenset[OrderKey]
    offers: Mapping[OrderRow, Offer]
    overtaken: tuple[OvertakenSubject, ...]
    said: frozenset[OrderKey]
    matched: _matching.Matched
    additions: tuple[_matching.Addition, ...]
    standing: frozenset[ReportProblem]


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
                said = _entries.entries(mail.text, digits)
                if worker is not None and window.opens(mail.arrived.date()) and said:
                    read.append(ReadUnreadable(mail.id, mail.arrived, worker, fault, said, day, ReportSubject(mail.subject)))
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
    days = _faulty(unreadable, reported, orders, window, inputs.entering_rollout or window.rollout, board)
    counted = {found: board.days(sorted(found.numbers), day) if day else frozenset() for found, day in days.items()}
    reported += [(found.worker, day) for found in unreadable for day in sorted(counted[found])]
    decided = _mails.decided(unreadable, inputs.requested)
    shown = {found: frozenset(filter(window.opens, counted[found])) for found in unreadable}
    entries = frozenset(
        OrderKey(number, day, found.worker) for found in unreadable for day in counted[found] for number in found.numbers
    )
    requested = _mails.requested_reports(unreadable, decided)
    asked = tuple(
        ReadReport(found.mail, found.arrived, found.worker, day, tuple(map(_leaned, found.entries)))
        for found in unreadable
        if shown[found] and (day := days[found]) is not None
    )
    matched = board.match(sorted((*reports, *requested, *asked), key=_mail_order), inputs.requested)
    offers = _offers(matched, asked, decided)
    overtaken = {found: takers for found in unreadable if (takers := _overtaken(found, matched.taken))}
    faulty = tuple(
        (found, shown[found])
        for found in unreadable
        if (shown[found] or found.day is None) and not _settled(found, decided, matched.taken)
    )
    taken = tuple(
        OvertakenSubject(found.worker, day, found.arrived, found.fault, found.subject, takers)
        for found, takers in overtaken.items()
        for day in sorted(shown[found])
    )
    entering = tuple(sorted((*reports, *requested), key=_mail_order))
    entered = board.match(entering, inputs.requested)
    additions = _corrections.uncorrected(entered.added, entering, board)
    described = _descriptions.entered(inputs.legend, inputs.rules, entered.entered, additions)
    newest = {found.number: (found.arrived, found.mail) for found in additions}
    standing = _corrections.standing([*strangers, *entered.problems, *described], entering, faulty, board, newest)
    found_mails = _mails.WindowMails(mails)
    keys = found_mails.said(inputs.requested)
    return WindowRead(
        found_mails, tuple(reported), tuple(mistaken), entries, offers, taken, keys, entered, additions, frozenset(standing)
    )


def _days(board: _matching.Board, report: ReadReport) -> frozenset[date]:
    return board.days((entry.number for entry in report.entries), report.day)


def _faulty(
    unreadable: Sequence[ReadUnreadable],
    reported: Sequence[tuple[Login, date]],
    orders: Sequence[RegisterOrder],
    window: Window,
    since: date,
    board: _matching.Board,
) -> dict[ReadUnreadable, date | None]:
    """Dzień każdego raportu z błędem tematu (ADR 0041), z którego numery zleceń wyznaczają dni, za które się liczy, jak
    przy pomylonym temacie (``Board.days``): dzień z tematu, gdy da się go przeczytać, a bez niego dzień wskazany, czyli
    ostatni dzień otwarty Wykonawcy ze zleceniami, nie wcześniejszy niż dzień wdrożenia Wpisania raportów ``since`` i nie
    późniejszy niż dzień przyjścia maila, za który nie ma innego raportu (``reported`` i raporty z błędem tematu z dniem
    z tematu, potem bez niego po ``_mail_order``). Bez dnia z
    tematu i bez wskazanego dnia raport nie liczy się za żaden dzień (``None``: problem bez dnia)."""

    found_days: dict[ReadUnreadable, date | None] = {}
    taken = set(reported)
    for found in sorted(dict.fromkeys(unreadable), key=lambda found: found.day is None):
        day = found_days[found] = found.day or _indicated(found, orders, window, since, taken)
        if day is not None:
            taken.update((found.worker, counted_day) for counted_day in board.days(sorted(found.numbers), day))
    return found_days


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


def _offers(
    matched: _matching.Matched, asked: Sequence[ReadReport], decided: Mapping[MailEntryKey, object]
) -> dict[OrderRow, Offer]:
    """Wpis na życzenie przy każdym zleceniu, którego zwycięskim Wpisem byłby Wpis raportu z błędem tematu, gdyby każdy
    taki raport miał w temacie swój dzień, a każdy znak z zamiarem był swoim ``tak``/``nie`` (``asked``), wśród
    Raportów wykonawców Wpisania raportów (``matched``: ``Board.match`` Raportów wykonawców Wpisania raportów i ``asked``
    po kolei maili z decyzjami taty): decyduje najpóźniejszy mail z numerem.
    Wpis, który tata już wpisał (``decided``), i Wpis, z którym wygrywa późniejszy mail, przycisku nie mają, a Wpis
    późniejszego raportu z błędem tematu ma własny, także przy zleceniu z Wpisem na życzenie wcześniejszego maila. Wpis,
    który stawia zlecenie u nadawcy albo w dniu z tematu, ma przycisk jak Raport wykonawcy, który by je przeniósł (ADR
    0029); bez przycisku zostaje to, czego taki raport by nie wpisał: przeciwne Wpisy, Wpis bez znaku, numer bez
    zlecenia, numer w kilku miejscach i Przeniesienie, do którego nie wolno. Dzień decyzji (``Offer.day``) to dzień
    zlecenia po Wpisie, który decyzja daje Raportowi wykonawcy tego maila jako dzień z tematu
    (``_mails.requested_reports``)."""

    faulty = {(report.mail, report.worker) for report in asked}
    return {
        order.row: Offer(mail, key.worker, key.day, key.number, entry.verdict, entry.activities, key.day)
        for key, (order, entry) in matched.targets.items()
        if ((mail := matched.mails[order.row]), key.worker) in faulty
        and (mail, key.worker, key.number) not in decided
        and entry.verdict is not None
    }


def _overtaken(found: ReadUnreadable, taken: Mapping[MailEntryKey, Login]) -> tuple[Login, ...]:
    """Wykonawcy późniejszych maili, których Wpisy wzięły zlecenia raportu z błędem tematu ``found``
    (``Matched.taken``), alfabetycznie, gdy wzięły zlecenie każdego jego Wpisu; inaczej pusto."""

    said = [(found.mail, found.worker, number) for number in found.numbers]
    if not all(place in taken for place in said):
        return ()
    return tuple(sorted({taken[place] for place in said}))


def _leaned(entry: ReportEntry) -> ReportEntry:
    if entry.verdict is None and entry.leaning is not None:
        return ReportEntry(entry.number, entry.leaning, None, entry.activities)
    return entry


def _settled(
    found: ReadUnreadable,
    decided: Mapping[MailEntryKey, object],
    taken: Mapping[MailEntryKey, Login],
) -> bool:
    places = [(found.mail, found.worker, number) for number in found.numbers]
    return all(place in decided or place in taken for place in places)


def _mail_order(found: MailRead) -> tuple[datetime, MailId, str, tuple[str, ...]]:
    """Chwila przyjścia, mail, a przy remisie (Message-ID ustawia nadawca) rodzaj i każde pole odczytu, więc dwa różne
    odczyty nigdy nie mają równego miejsca."""

    match found:
        case ReadReport(worker=worker, day=day, entries=entries):
            return found.arrived, found.mail, "report", (worker, day.isoformat(), *_content(entries))
        case ReadUnreadable(worker=worker, fault=fault, entries=entries, day=day):
            said = (fault.name, "" if day is None else day.isoformat())
            return found.arrived, found.mail, "unreadable", (worker, *said, *_content(entries))
        case ReadStranger(day=day):
            return found.arrived, found.mail, "stranger", (day.isoformat(),)


def _content(entries: Iterable[ReportEntry]) -> tuple[str, ...]:
    return tuple(
        part
        for entry in entries
        for part in (
            entry.number,
            "" if entry.verdict is None else entry.verdict.value,
            "" if entry.fault is None else entry.fault.name,
            entry.activities,
        )
    )
