"""Przypomnienia o raporcie (ADR 0030, ADR 0032, ADR 0041): które przypomnienia należą się teraz, ich temat i treść.

Pory, godzina pierwszego przypomnienia, pierwsze zdanie treści i stopka to Ustawienia Centrum taty
(``ReminderSettings``), a dzisiejsze wartości z ADR 0030 są ich wartościami domyślnymi (``DEFAULT_REMINDERS``). Reguły
tych ustawień ma jedna budowa, ``ReminderSettings.of``. Stały blok wzoru Raportu wykonawcy z przykładem
(``_entries.EXAMPLE``) i temat zostają w kodzie, bo po nich Wpisanie raportów poznaje odpowiedź, a numery przykładu nie
są Wpisami. Który mail jest Raportem wykonawcy za który dzień, mówi odczyt okna ``_reading.read_window``, ten sam co
we Wpisaniu raportów. Temat przypomnienia ma ``_subject`` (``reminder_subject``, ``reminder_day``), bo odpowiedź na
przypomnienie jest Raportem wykonawcy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Final, Literal

from . import _reading
from ._entries import EXAMPLE
from ._model import Login, ReportInputs, SenderAddress
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

    def same_mail(self, other: SentReminder) -> bool:
        """Ten sam mail widziany dwoma zegarami: ci sami adresaci i dzień przypomnienia, a chwile wysłania (zegar
        laptopa taty i zegar Gmaila w „Wysłanych”) najwyżej ``CLOCK_MARGIN`` od siebie. Nie porównuje pór: dwa maile tej
        samej pory, gdy Gmail nie położył pierwszego przed ponownym startem Centrum, to dwa maile."""

        return (
            (self.recipients, self.day) == (other.recipients, other.day)
            and abs(self.sent_at - other.sent_at) <= CLOCK_MARGIN
        )


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
    """Wejście ``reminders_due``: chwila ze strefą taty, wejście odczytu okna (``reports``, w kształcie wejścia Wpisania
    raportów: okno dni od wcześniejszego z dni wdrożenia przypomnień i Wpisania raportów, bez okresów z Plikiem
    zbiorczym, bo Przeniesienie Centrum na dzień sprzed wdrożenia przypomnień dalej zmienia dzień raportu; zlecenia, Dni
    uporządkowane i numery wierszy z tego samego odczytu INTERMAX co we Wpisaniu, maile ze Skrzynki raportów i adresy
    Wykonawców z Listy Wykonawców, także tych, którym przypomnienia nie idą, bo ich Raport wykonawcy dalej jest
    raportem), przypomnienia z „Wysłanych”, loginy Wykonawców, którym przypomnienia idą (``reminded``: aktywni z
    włączonymi przypomnieniami), Ustawienia przypomnień (dzień wdrożenia, od którego idą, pory, godzina pierwszego,
    treść i stopka) i pory, przy których praca przypomnień sprawdzała
    (``in_effect``; bez nich pory „Wysłanych” to pory z ADR 0030, jedyne pory wersji sprzed Ustawień Centrum).

    ``reports`` ma pamięć własnych wpisów i decyzje „Zostaw moją” z pamięci Wpisania raportów, bo dzień raportu zależy
    od pamięci (Zlecenia dopisane z raportu, dzień sprzed Przeniesienia): przy tej samej pamięci przypomnienie nie
    idzie za żaden dzień, za który kafelek Wpisania liczy raport, a idzie za każdy inny (``_memory.EnteringMemory``
    buduje to wejście dla obu operacji)."""

    now: datetime
    reports: ReportInputs
    sent: Sequence[SentReminder]
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
        "Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód",
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
    dopóki nie przyśle z któregokolwiek adresu z listy żadnego Raportu wykonawcy za X (ADR 0041): Raport z Błędem opisu
    jest przysłany, a Raport z pomylonym tematem jest przysłany za dzień swoich zleceń, nie za dzień z tematu. Dzień
    każdego Raportu daje ten sam odczyt okna co we Wpisaniu raportów (``_reading.read_window``). Liczą
    się tylko dni otwarte okna (``Window.opens``) od dnia wdrożenia przypomnień (``ReminderSettings.since``, bez niego
    od dnia wdrożenia okna), bez okresów z Plikiem zbiorczym. Każdy dzień ma osobne przypomnienie.
    """

    now = inputs.now
    schedule = inputs.settings.schedule
    pora = reminder_pora(now, schedule)
    if pora is None:
        return ()
    since = inputs.settings.since or inputs.reports.window.rollout
    logins = inputs.reports.addresses.logins
    reported = set(_reading.read_window(inputs.reports).reported)
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
        for order in inputs.reports.orders
        if inputs.reports.window.opens(order.key.day)
        and order.key.day >= since
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
            reminder_text(day, settings.text, settings.footer),
        )
        for day, worker in sorted(due)
    )
