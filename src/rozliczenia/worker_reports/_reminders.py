"""Przypomnienia o raporcie (ADR 0030): które przypomnienia należą się teraz, ich temat i treść.

Pory, dzień, od którego należy się przypomnienie, i treść ze wzorem Raportu wykonawcy są tu jako dane, a czytelność
tematu Raportu wykonawcy rozstrzyga ``_subject.read``, ten sam co we Wpisaniu raportów. Temat przypomnienia też ma
``_subject`` (``reminder_subject``, ``reminder_day``), bo odpowiedź na przypomnienie jest Raportem wykonawcy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Final

from . import _subject
from ._model import Login, OrderNumber, RegisterOrder, ReportMail, SenderAddress, Window, WorkerAddresses
from ._subject import reminder_subject


class Pora(Enum):
    """Pora przypomnień: w każdej idzie najwyżej jedno przypomnienie za dzień do Wykonawcy."""

    MORNING = "poranna"
    EVENING = "wieczorna"


_PORY: Final = ((Pora.MORNING, time(8), time(18)), (Pora.EVENING, time(18), time(22)))
"""Pora poranna od 8:00 do 18:00 i wieczorna od 18:00 do 22:00, bez końca pory; poza nimi przypomnienia nie idą."""

FIRST_REMINDER: Final = time(8)
"""Przypomnienie za dzień X należy się od tej godziny dnia X+1."""

EXAMPLE: Final = ("12345678 tak montaż ONT", "12345679 nie brak klienta")
"""Linie przykładu w treści przypomnienia."""

EXAMPLE_NUMBERS: Final = frozenset(OrderNumber(line.split()[0]) for line in EXAMPLE)
"""Numery zleceń z przykładu w treści przypomnienia: w żadnym mailu nie są Wpisami (``_entries.entries``)."""



@dataclass(frozen=True)
class SentReminder:
    """Przypomnienie z folderu „Wysłane” skrzynki raportów: adresaci, dzień z tematu i chwila wysłania ze strefą."""

    recipients: frozenset[SenderAddress]
    day: date
    sent_at: datetime


@dataclass(frozen=True)
class ReminderInputs:
    """Wejście ``reminders_due``: chwila ze strefą taty, okno dni (od dnia wdrożenia przypomnień, bez okresów z Plikiem
    zbiorczym), uporządkowane zlecenia INTERMAX, maile ze Skrzynki raportów, przypomnienia z „Wysłanych”, adresy
    Wykonawców i stopka taty (``None``: bez pliku stopki)."""

    now: datetime
    window: Window
    orders: Sequence[RegisterOrder]
    mails: Sequence[ReportMail]
    sent: Sequence[SentReminder]
    addresses: WorkerAddresses
    footer: str | None


@dataclass(frozen=True)
class Reminder:
    """Przypomnienie do wysłania: Wykonawca, wszystkie jego adresy z listy, dzień zleceń, temat i treść."""

    worker: Login
    recipients: tuple[SenderAddress, ...]
    day: date
    subject: str
    text: str


def reminder_pora(now: datetime) -> Pora | None:
    """Pora chwili ``now``; ``None`` w nocy, od 22:00 do 8:00."""

    return next((pora for pora, start, end in _PORY if start <= now.time() < end), None)


def reminder_text(day: date, footer: str | None) -> str:
    """Treść Przypomnienia o raporcie za dzień ``day`` ze wzorem Raportu wykonawcy, a na końcu stopka taty, gdy jest."""

    shown = f"{day:%d.%m.%Y}"
    lines = [
        f"Poproszę o wysłanie raportu za dzień {shown}.",
        "",
        "Raport proszę wysłać według tego wzoru:",
        f"Temat maila: Raport {shown}",
        "Treść maila: NR. ZLECENIA [spacja] tak/nie [spacja] opis zrealizowanej czynności",
        "PRZYKŁAD:",
        *EXAMPLE,
    ]
    if footer is not None and footer.strip():
        lines += ["", footer.strip("\r\n")]
    return "\n".join(lines) + "\n"


def reminders_due(inputs: ReminderInputs) -> tuple[Reminder, ...]:
    """Przypomnienia, które należą się w chwili ``inputs.now``, po dniu i Wykonawcy.

    Przypomnienie za dzień X należy się Wykonawcy z listy adresów, który ma zlecenie dnia X, od ``FIRST_REMINDER`` dnia
    X+1, w porze (``reminder_pora``), w której tego dnia nie poszło jeszcze przypomnienie za X do żadnego jego adresu,
    dopóki nie przyśle czytelnego Raportu wykonawcy za X (temat daje dzień X, treść bez znaczenia) z któregokolwiek
    adresu z listy. Liczą się tylko dni otwarte okna (``Window.opens``): od dnia wdrożenia przypomnień, bez okresów z
    Plikiem zbiorczym. Każdy dzień ma osobne przypomnienie.
    """

    now = inputs.now
    pora = reminder_pora(now)
    if pora is None:
        return ()
    logins = inputs.addresses.logins
    reported = {
        (worker, day)
        for mail in inputs.mails
        if isinstance(day := _subject.read(mail.subject), date) and (worker := logins.get(mail.sender)) is not None
    }
    reminded = {
        (worker, sent.day)
        for sent in inputs.sent
        if (moment := sent.sent_at.astimezone(now.tzinfo)).date() == now.date() and reminder_pora(moment) is pora
        for recipient in sent.recipients
        if (worker := logins.get(recipient)) is not None
    }
    answered = reported | reminded
    recipients: dict[Login, list[SenderAddress]] = {}
    for address, login in logins.items():
        recipients.setdefault(login, []).append(address)
    due = {
        (order.key.day, order.key.worker)
        for order in inputs.orders
        if inputs.window.opens(order.key.day)
        and now >= datetime.combine(order.key.day + timedelta(days=1), FIRST_REMINDER, now.tzinfo)
        and order.key.worker in recipients
        and (order.key.worker, order.key.day) not in answered
    }
    return tuple(
        Reminder(worker, tuple(sorted(recipients[worker])), day, reminder_subject(day), reminder_text(day, inputs.footer))
        for day, worker in sorted(due)
    )
