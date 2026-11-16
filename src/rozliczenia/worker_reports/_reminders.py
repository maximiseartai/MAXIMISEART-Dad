"""Przypomnienia o raporcie (ADR 0030, ADR 0032, ADR 0039): które przypomnienia należą się teraz, ich temat i treść.

Pory, godzina pierwszego przypomnienia, pierwsze zdanie treści i stopka to Ustawienia Centrum taty
(``ReminderSettings``), a dzisiejsze wartości z ADR 0030 są ich wartościami domyślnymi (``DEFAULT_REMINDERS``). Reguły
tych ustawień ma jedna budowa, ``ReminderSettings.of``. Stały blok wzoru Raportu wykonawcy z przykładem
(``_entries.EXAMPLE``) i temat zostają w kodzie, bo po nich Wpisanie raportów poznaje odpowiedź, a numery przykładu nie
są Wpisami. Czytelność tematu Raportu wykonawcy rozstrzyga ``_subject.read``, a Wpisy treści ``_entries.entries``, te
same co we Wpisaniu raportów. Temat przypomnienia też ma ``_subject`` (``reminder_subject``, ``reminder_day``), bo
odpowiedź na przypomnienie jest Raportem wykonawcy. Który Wpis ``tak`` ma Błąd opisu, mówi ``_descriptions``, ta sama
reguła co w problemie Wpisania raportów.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Final, Literal, assert_never

from ..activity_legend import ActivityLegend, ColumnTwice, DescriptionProblem, NotACode, NumberOutOfRange, TwoColours
from . import _descriptions, _entries, _subject
from ._entries import EXAMPLE
from ._model import FaultyDescription, Login, ReadReport, RegisterOrder, ReportMail, SenderAddress, Window, WorkerAddresses
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
"""Pierwsze zdanie domyślnego tekstu przypomnienia."""


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


OLD_VERSION_SCHEDULES: Final = frozenset({DEFAULT_SCHEDULE})
"""Pory przypomnień sprzed pierwszego sprawdzenia, które zapisało pory: wysyłała wtedy tylko wersja sprzed Ustawień
Centrum, a ona znała jedne pory, stałe z ADR 0030."""


@dataclass(frozen=True)
class SchedulesInEffect:
    """Pory przypomnień, przy których praca przypomnień sprawdzała, od najstarszych: każde obowiązują od chwili swojego
    pierwszego sprawdzenia do chwili następnych, a przed pierwszym obowiązują pory ``before``. Z nich nazwana pora
    przypomnienia z „Wysłanych”: ta, w której poszło przy porach z chwili wysyłki, a nie przy bieżących
    (decyzja Maksa)."""

    before: frozenset[ReminderSchedule] = OLD_VERSION_SCHEDULES
    changes: tuple[ScheduleSince, ...] = ()

    def around(self, moment: datetime) -> frozenset[ReminderSchedule]:
        """Pory obowiązujące w chwili ``moment`` z zapasem ``CLOCK_MARGIN`` w obie strony; przed pierwszym wpisem
        ``before``. Przy zmianie pór blisko wysyłki mail zamyka nazwaną porę przy obu porach, bo dwa maile tej samej
        pory są gorsze niż przypomnienie, które poczeka do następnej pory."""

        start, end = moment - CLOCK_MARGIN, moment + CLOCK_MARGIN
        earlier = [change.schedule for change in self.changes if change.since <= start]
        found = {earlier[-1]} if earlier else set(self.before)
        return frozenset(found | {change.schedule for change in self.changes if start < change.since <= end})

    def checked(self, moment: datetime, schedule: ReminderSchedule) -> SchedulesInEffect:
        """Pory po sprawdzeniu z chwili ``moment`` przy porach ``schedule``: nowy wpis, gdy różnią się od ostatnich.
        Zostają wpisy z ostatniej doby i ostatni sprzed niej, bo „Wysłane” liczą się tylko z bieżącego dnia."""

        if self.changes and self.changes[-1].schedule == schedule:
            return self
        cutoff = moment - timedelta(days=1)
        older = [change for change in self.changes if change.since < cutoff]
        recent = [change for change in self.changes if change.since >= cutoff]
        return SchedulesInEffect(self.before, (*older[-1:], *recent, ScheduleSince(moment, schedule)))


@dataclass(frozen=True)
class ReminderInputs:
    """Wejście ``reminders_due``: chwila ze strefą taty, okno dni (od dnia wdrożenia przypomnień, bez okresów z Plikiem
    zbiorczym), uporządkowane zlecenia INTERMAX, maile ze Skrzynki raportów, przypomnienia z „Wysłanych”, adresy
    Wykonawców z Listy Wykonawców (także tych, którym przypomnienia nie idą: ich Raport wykonawcy dalej jest raportem),
    loginy Wykonawców, którym przypomnienia idą (``reminded``: aktywni z włączonymi przypomnieniami), Ustawienia
    przypomnień (pory, godzina pierwszego, treść i stopka), Legenda czynności Ustawień Centrum (``legend``, ta sama co
    we Wpisaniu raportów) i pory, przy których praca przypomnień sprawdzała (``in_effect``; bez nich pory „Wysłanych”
    to pory z ADR 0030, jedyne pory wersji sprzed Ustawień Centrum)."""

    now: datetime
    window: Window
    orders: Sequence[RegisterOrder]
    mails: Sequence[ReportMail]
    sent: Sequence[SentReminder]
    addresses: WorkerAddresses
    reminded: frozenset[Login]
    settings: ReminderSettings
    legend: ActivityLegend
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


def reminder_text(day: date, text: str, footer: str, faults: Sequence[FaultyDescription] = ()) -> str:
    """Treść Przypomnienia o raporcie za dzień ``day``: pierwsze zdanie taty z dniem w miejscu ``{dzień}``, zlecenia
    raportu z tego dnia z Błędem opisu z powodem (``faults``), stały wzór Raportu wykonawcy, a na końcu stopka taty,
    gdy nie jest pusta.

    Linia zlecenia z Błędem opisu zaczyna się słowem „Zlecenie”, a po numerze stoi „ma”, więc odpowiedź, która cytuje ją
    bez znaku cytatu, nie daje z niej Wpisu (``_entries.entries``). Powód nie ma słów opisu Wykonawcy (``_said``)."""

    shown = f"{day:%d.%m.%Y}"
    lines = [text.replace(DAY_FIELD, shown), ""]
    if faults:
        lines += [
            "W raporcie za ten dzień opis zlecenia ma być z samych kodów czynności. Proszę wysłać jeszcze raz te zlecenia:",
            *(f"Zlecenie {fault.number} ma w opisie {_said(fault.problems)}." for fault in faults),
            "",
        ]
    lines += [
        "Raport proszę wysłać według tego wzoru:",
        f"Temat maila: Raport {shown}",
        "Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód",
        "PRZYKŁAD:",
        *EXAMPLE,
    ]
    if footer.strip():
        lines += ["", footer.strip("\r\n")]
    return "\n".join(lines) + "\n"


def _said(problems: Sequence[DescriptionProblem]) -> str:
    """Powody Błędu opisu dla Wykonawcy, każdy rodzaj raz, w kolejności z opisu: bez słów z jego opisu, bo przypomnienie
    idzie na każdy jego adres z listy, i bez kolumn Pliku zbiorczego, których Wykonawca nie zna."""

    said = list(dict.fromkeys(map(_reason, problems)))
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} i {said[-1]}"


def _reason(problem: DescriptionProblem) -> str:
    match problem:
        case NotACode():
            return "słowo inne niż kod czynności"
        case NumberOutOfRange():
            return f"kod z liczbą spoza zakresu ({problem.detail})"
        case ColumnTwice():
            return "dwa kody tej samej usługi"
        case TwoColours():
            return "kody, których nie można łączyć"
        case _:
            assert_never(problem)


def reminders_due(inputs: ReminderInputs) -> tuple[Reminder, ...]:
    """Przypomnienia, które należą się w chwili ``inputs.now``, po dniu i Wykonawcy.

    Przypomnienie za dzień X należy się Wykonawcy z listy adresów, któremu przypomnienia idą (``reminded``), który ma
    zlecenie dnia X, od godziny pierwszego przypomnienia dnia
    X+1, w porze (``reminder_pora``), w której tego dnia nie poszło jeszcze przypomnienie za X do żadnego jego adresu
    (porę wysłanego liczą pory z chwili wysyłki, ``SchedulesInEffect.around``),
    dopóki nie przyśle czytelnego Raportu wykonawcy za X (temat daje dzień X, także z literówką w roku) z któregokolwiek
    adresu z listy i dopóki któryś wygrywający Wpis ``tak`` jego raportów za X ma Błąd opisu (``_descriptions.standing``,
    ADR 0039); przypomnienie po Błędzie opisu mówi, w którym zleceniu jest i jaki. Liczą
    się tylko dni otwarte okna (``Window.opens``): od dnia wdrożenia przypomnień, bez okresów z Plikiem zbiorczym.
    Każdy dzień ma osobne przypomnienie.
    """

    now = inputs.now
    schedule = inputs.settings.schedule
    pora = reminder_pora(now, schedule)
    if pora is None:
        return ()
    logins = inputs.addresses.logins
    digits = min((len(order.key.number) for order in inputs.orders), default=1)
    reports = sorted(
        (
            ReadReport(mail.id, mail.arrived, worker, day, _entries.entries(mail.text, digits))
            for mail in inputs.mails
            if isinstance(day := _subject.read(mail.subject, mail.arrived.date()), date)
            and (worker := logins.get(mail.sender)) is not None
        ),
        key=lambda report: (report.arrived, report.mail),
    )
    faults = _descriptions.standing(inputs.legend, reports, frozenset(order.key.number for order in inputs.orders))
    reported = {(report.worker, report.day) for report in reports} - faults.keys()
    reminded = {
        (worker, sent.day)
        for sent in inputs.sent
        if (moment := sent.sent_at.astimezone(now.tzinfo)).date() == now.date()
        and pora in {reminder_pora(moment, found) for found in inputs.in_effect.around(moment)}
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
    settings = inputs.settings
    return tuple(
        Reminder(
            worker,
            tuple(sorted(recipients[worker])),
            day,
            reminder_subject(day),
            reminder_text(day, settings.text, settings.footer, faults.get((worker, day), ())),
        )
        for day, worker in sorted(due)
    )
