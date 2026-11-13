"""Przypomnienia o raporcie (ADR 0030, ADR 0032): które przypomnienia należą się teraz, ich temat i treść.

Pory, godzina pierwszego przypomnienia, pierwsze zdanie treści i stopka to Ustawienia Centrum taty
(``ReminderSettings``), a dzisiejsze wartości z ADR 0030 są ich wartościami domyślnymi (``DEFAULT_REMINDERS``). Reguły
tych ustawień ma jedna budowa, ``ReminderSettings.of``. Stały blok wzoru Raportu wykonawcy z ``EXAMPLE`` i temat zostają w
kodzie, bo po nich Wpisanie raportów poznaje odpowiedź, a numery przykładu nie są Wpisami. Czytelność tematu Raportu
wykonawcy rozstrzyga ``_subject.read``, ten sam co we Wpisaniu raportów. Temat przypomnienia też ma ``_subject``
(``reminder_subject``, ``reminder_day``), bo odpowiedź na przypomnienie jest Raportem wykonawcy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Final, Literal

from . import _subject
from ._model import Login, OrderNumber, RegisterOrder, ReportMail, SenderAddress, Window, WorkerAddresses
from ._subject import reminder_subject


class Pora(Enum):
    """Pora przypomnień: w każdej idzie najwyżej jedno przypomnienie za dzień do Wykonawcy."""

    MORNING = "poranna"
    EVENING = "wieczorna"


@dataclass(frozen=True)
class TimeRange:
    """Pora od ``start`` do ``end``, bez końca pory: przy porze 8:00–17:00 16:59 jest w porze, a 17:00 już nie."""

    start: time
    end: time

    def holds(self, moment: time) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True)
class ReminderSchedule:
    """Pory przypomnień i godzina pierwszego: przypomnienie za dzień X należy się od ``first`` dnia X+1, w porze
    porannej albo wieczornej; poza nimi przypomnienia nie idą."""

    morning: TimeRange
    evening: TimeRange
    first: time


DAY_FIELD: Final = "{dzień}"
"""Jedyne pole w pierwszym zdaniu przypomnienia: dzień raportu w postaci ``dd.mm.rrrr``."""

DEFAULT_SCHEDULE: Final = ReminderSchedule(TimeRange(time(8), time(17)), TimeRange(time(18), time(22)), time(8))
"""Pora poranna od 8:00 do 17:00, wieczorna od 18:00 do 22:00 i pierwsze przypomnienie od 8:00 (ADR 0030). Poranne
przypomnienie nie nadrabia się od 17:00, żeby laptop włączony tuż przed 18:00 nie wysłał Wykonawcy dwóch przypomnień w
kilka minut (decyzja Maksa 12.11)."""

DEFAULT_TEXT: Final = f"Poproszę o wysłanie raportu za dzień {DAY_FIELD}."
"""Pierwsze zdanie przypomnienia ze speca #1344."""

EXAMPLE: Final = ("12345678 tak montaż ONT", "12345679 nie brak klienta")
"""Linie przykładu w treści przypomnienia."""

EXAMPLE_NUMBERS: Final = frozenset(OrderNumber(line.split()[0]) for line in EXAMPLE)
"""Numery zleceń z przykładu w treści przypomnienia: w żadnym mailu nie są Wpisami (``_entries.entries``)."""


ReminderProblemKind = Literal["empty_morning", "empty_evening", "overlap", "empty_text", "unknown_field", "enabled_without_since"]
"""Reguła ustawień przypomnień, której wartość nie spełnia: pusta albo odwrócona pora poranna lub wieczorna, pory
zachodzące na siebie (poranna kończy się po początku wieczornej), puste pierwsze zdanie, nawias klamrowy inny niż
``{dzień}`` i włączone przypomnienia bez dnia wdrożenia."""


@dataclass(frozen=True)
class ReminderProblem:
    kind: ReminderProblemKind


@dataclass(frozen=True)
class ReminderSettings:
    """Przypomnienia o raporcie z Ustawień Centrum: czy idą, dzień wdrożenia (``since``: od niego liczą się dni, ustawia
    go pierwsze włączenie), pory, pierwsze zdanie treści z polem ``{dzień}`` i stopka taty (``""``: bez stopki)."""

    enabled: bool
    since: date | None
    schedule: ReminderSchedule
    text: str
    footer: str

    @classmethod
    def of(
        cls, enabled: bool, since: date | None, schedule: ReminderSchedule, text: str, footer: str
    ) -> ReminderSettings | ReminderProblem:
        """Jedyna budowa z regułami, w stałej kolejności: pierwsza niespełniona reguła to problem."""

        rules: Mapping[ReminderProblemKind, bool] = {
            "empty_morning": schedule.morning.start < schedule.morning.end,
            "empty_evening": schedule.evening.start < schedule.evening.end,
            "overlap": schedule.morning.end <= schedule.evening.start,
            "empty_text": bool(text.strip()),
            "unknown_field": not {"{", "}"} & set(text.replace(DAY_FIELD, "")),
            "enabled_without_since": not enabled or since is not None,
        }
        broken = next((kind for kind, holds in rules.items() if not holds), None)
        if broken is not None:
            return ReminderProblem(broken)
        return cls(enabled, since, schedule, text, footer)

    @property
    def sends(self) -> date | None:
        """Dzień wdrożenia, gdy przypomnienia idą; ``None``: przypomnienia wyłączone."""

        return self.since if self.enabled else None


DEFAULT_REMINDERS: Final = ReminderSettings(False, None, DEFAULT_SCHEDULE, DEFAULT_TEXT, "")
"""Przypomnienia bez pliku Ustawień: wyłączone, bez dnia wdrożenia, z porami i treścią z ADR 0030 i bez stopki."""


@dataclass(frozen=True)
class SentReminder:
    """Przypomnienie z folderu „Wysłane” skrzynki raportów: adresaci, dzień z tematu i chwila wysłania ze strefą."""

    recipients: frozenset[SenderAddress]
    day: date
    sent_at: datetime


CLOCK_MARGIN: Final = timedelta(minutes=2)
"""Ile chwila z „Wysłanych” (zegar Gmaila) może odejść od zegara laptopa taty, przy którym praca przypomnień zapisała
pory. Sprawdzenie z nowymi porami rusza najwcześniej minutę po końcu sprawdzenia, które wysyłało przy starych."""


@dataclass(frozen=True)
class ScheduleSince:
    """Pory, które praca przypomnień wzięła pierwszy raz w sprawdzeniu z chwili ``since`` (ze strefą)."""

    since: datetime
    schedule: ReminderSchedule


@dataclass(frozen=True)
class SchedulesInEffect:
    """Pory przypomnień, przy których praca przypomnień sprawdzała, od najstarszych: każde obowiązują od chwili swojego
    pierwszego sprawdzenia do chwili następnych. Z nich nazwana pora przypomnienia z „Wysłanych”: ta, w której poszło
    przy porach z chwili wysyłki, a nie przy bieżących (decyzja Maksa W1 w #1568). Bez wpisów pory się nie zmieniały,
    więc obowiązują bieżące."""

    changes: tuple[ScheduleSince, ...] = ()

    def around(self, moment: datetime, current: ReminderSchedule) -> frozenset[ReminderSchedule]:
        """Pory obowiązujące w chwili ``moment`` z zapasem ``CLOCK_MARGIN`` w obie strony; przed pierwszym wpisem
        pierwsze, a bez wpisów ``current``. Przy zmianie pór blisko wysyłki mail zamyka nazwaną porę przy obu porach,
        bo dwa maile tej samej pory są gorsze niż przypomnienie, które poczeka do następnej pory."""

        if not self.changes:
            return frozenset({current})
        start, end = moment - CLOCK_MARGIN, moment + CLOCK_MARGIN
        earlier = [change.schedule for change in self.changes if change.since <= start]
        found = {earlier[-1] if earlier else self.changes[0].schedule}
        return frozenset(found | {change.schedule for change in self.changes if start < change.since <= end})

    def checked(self, moment: datetime, schedule: ReminderSchedule) -> SchedulesInEffect:
        """Pory po sprawdzeniu z chwili ``moment`` przy porach ``schedule``: nowy wpis, gdy różnią się od ostatnich.
        Zostają wpisy z ostatniej doby i ostatni sprzed niej, bo „Wysłane” liczą się tylko z bieżącego dnia."""

        if self.changes and self.changes[-1].schedule == schedule:
            return self
        cutoff = moment - timedelta(days=1)
        older = [change for change in self.changes if change.since < cutoff]
        recent = [change for change in self.changes if change.since >= cutoff]
        return SchedulesInEffect((*older[-1:], *recent, ScheduleSince(moment, schedule)))


@dataclass(frozen=True)
class ReminderInputs:
    """Wejście ``reminders_due``: chwila ze strefą taty, okno dni (od dnia wdrożenia przypomnień, bez okresów z Plikiem
    zbiorczym), uporządkowane zlecenia INTERMAX, maile ze Skrzynki raportów, przypomnienia z „Wysłanych”, adresy
    Wykonawców z Listy Wykonawców (także tych, którym przypomnienia nie idą: ich Raport wykonawcy dalej jest raportem),
    loginy Wykonawców, którym przypomnienia idą (``reminded``: aktywni z włączonymi przypomnieniami), Ustawienia
    przypomnień (pory, godzina pierwszego, treść i stopka) i pory, przy których praca przypomnień sprawdzała
    (``in_effect``; bez nich pory „Wysłanych” to bieżące)."""

    now: datetime
    window: Window
    orders: Sequence[RegisterOrder]
    mails: Sequence[ReportMail]
    sent: Sequence[SentReminder]
    addresses: WorkerAddresses
    reminded: frozenset[Login]
    settings: ReminderSettings
    in_effect: SchedulesInEffect = SchedulesInEffect()


@dataclass(frozen=True)
class Reminder:
    """Przypomnienie do wysłania: Wykonawca, wszystkie jego adresy z listy, dzień zleceń, temat i treść."""

    worker: Login
    recipients: tuple[SenderAddress, ...]
    day: date
    subject: str
    text: str


def reminder_pora(now: datetime, schedule: ReminderSchedule) -> Pora | None:
    """Pora chwili ``now``; ``None`` poza porami (przy porach domyślnych od 17:00 do 18:00 i w nocy, od 22:00 do 8:00)."""

    if schedule.morning.holds(now.time()):
        return Pora.MORNING
    return Pora.EVENING if schedule.evening.holds(now.time()) else None


def reminder_text(day: date, text: str, footer: str) -> str:
    """Treść Przypomnienia o raporcie za dzień ``day``: pierwsze zdanie taty z dniem w miejscu ``{dzień}``, stały wzór
    Raportu wykonawcy, a na końcu stopka taty, gdy nie jest pusta."""

    shown = f"{day:%d.%m.%Y}"
    lines = [
        text.replace(DAY_FIELD, shown),
        "",
        "Raport proszę wysłać według tego wzoru:",
        f"Temat maila: Raport {shown}",
        "Treść maila: NR. ZLECENIA [spacja] tak/nie [spacja] opis zrealizowanej czynności",
        "PRZYKŁAD:",
        *EXAMPLE,
    ]
    if footer.strip():
        lines += ["", footer.strip("\r\n")]
    return "\n".join(lines) + "\n"


def reminders_due(inputs: ReminderInputs) -> tuple[Reminder, ...]:
    """Przypomnienia, które należą się w chwili ``inputs.now``, po dniu i Wykonawcy.

    Przypomnienie za dzień X należy się Wykonawcy z listy adresów, któremu przypomnienia idą (``reminded``), który ma
    zlecenie dnia X, od godziny pierwszego przypomnienia dnia
    X+1, w porze (``reminder_pora``), w której tego dnia nie poszło jeszcze przypomnienie za X do żadnego jego adresu
    (porę wysłanego liczą pory z chwili wysyłki, ``SchedulesInEffect.around``),
    dopóki nie przyśle czytelnego Raportu wykonawcy za X (temat daje dzień X, także z literówką w roku, treść bez znaczenia) z któregokolwiek
    adresu z listy. Liczą się tylko dni otwarte okna (``Window.opens``): od dnia wdrożenia przypomnień, bez okresów z
    Plikiem zbiorczym. Każdy dzień ma osobne przypomnienie.
    """

    now = inputs.now
    schedule = inputs.settings.schedule
    pora = reminder_pora(now, schedule)
    if pora is None:
        return ()
    logins = inputs.addresses.logins
    reported = {
        (worker, day)
        for mail in inputs.mails
        if isinstance(day := _subject.read(mail.subject, mail.arrived.date()), date) and (worker := logins.get(mail.sender)) is not None
    }
    reminded = {
        (worker, sent.day)
        for sent in inputs.sent
        if (moment := sent.sent_at.astimezone(now.tzinfo)).date() == now.date()
        and pora in {reminder_pora(moment, found) for found in inputs.in_effect.around(moment, schedule)}
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
        and now >= datetime.combine(order.key.day + timedelta(days=1), schedule.first, now.tzinfo)
        and order.key.worker in recipients
        and order.key.worker in inputs.reminded
        and (order.key.worker, order.key.day) not in answered
    }
    return tuple(
        Reminder(worker, tuple(sorted(recipients[worker])), day, reminder_subject(day), reminder_text(day, inputs.settings.text, inputs.settings.footer))
        for day, worker in sorted(due)
    )
