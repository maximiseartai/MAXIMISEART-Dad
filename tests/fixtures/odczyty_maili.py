"""Odczyty maili okna dla testów: rdzeń raportów wystawia odczyty maili tylko w kapsule ``WindowMails``, więc test
składa oczekiwane odczyty z rekordów Logów Wpisania raportów (``LoggedMail``, jedyny schemat zapisu odczytu maila) i
czyta odczyty z wyniku tym samym schematem (``logged_mails``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from rozliczenia.centrum.report_entering_logs import (
    LoggedMail,
    LoggedReportEntry,
    LoggedReportMail,
    LoggedStrangerMail,
    LoggedUnreadableMail,
    window_mails,
)
from rozliczenia.worker_reports import MailId, ReportEntry, SubjectFault, WindowMails


def report(mail: MailId, arrived: datetime, worker: str, day: date, entries: Iterable[ReportEntry]) -> LoggedReportMail:
    """Raport wykonawcy od ``worker`` z dniem z tematu ``day`` i Wpisami ``entries``."""

    logged = [LoggedReportEntry.of(entry) for entry in entries]
    return LoggedReportMail(kind="report", mail=mail.digest, arrived=arrived, worker=worker, day=day, entries=logged)


def unreadable(
    mail: MailId, arrived: datetime, worker: str, fault: SubjectFault, entries: Iterable[ReportEntry], day: date | None
) -> LoggedUnreadableMail:
    """Raport wykonawcy z błędem tematu z powodem ``fault``, Wpisami ``entries`` i dniem z tematu ``day``; numery jego
    Wpisów rosnąco, jak w Logach."""

    found = tuple(entries)
    return LoggedUnreadableMail(
        kind="unreadable",
        mail=mail.digest,
        arrived=arrived,
        worker=worker,
        fault=fault,
        numbers=sorted({entry.number for entry in found}),
        day=day,
        entries=[LoggedReportEntry.of(entry) for entry in found],
    )


def stranger(mail: MailId, arrived: datetime, day: date) -> LoggedStrangerMail:
    """Raport wykonawcy od nieznanego nadawcy z dniem z tematu ``day``."""

    return LoggedStrangerMail(kind="stranger", mail=mail.digest, arrived=arrived, day=day)


def mails(*logged: LoggedMail) -> WindowMails:
    """Odczyty maili okna z rekordów ``logged``, po kolei."""

    return window_mails(logged)
