"""Przypomnienia o raporcie z Centrum rozliczeń (ADR 0030): wewnętrzna praca co minutę, poza Uruchomieniami procesu.

Rytm (``ReminderRhythm``, u taty ``MinuteRhythm``) woła ``ReportReminders.check`` co minutę od startu Centrum do jego
zamknięcia. Sprawdzenie bierze chwilę z zegara Centrum (``now``) i na początku migawkę Ustawień Centrum, więc zmiana
pór, treści albo stopki działa od następnego sprawdzenia, bez ponownego startu Centrum (ADR 0032). Przy wyłączonych
przypomnieniach i poza porą przypomnień z Ustawień (``reminder_pora``) nic więcej nie robi. W porze bierze z migawki
INTERMAX i folder okresów, dzień wdrożenia przypomnień, Legendę czynności, Listę Wykonawców, treść i stopkę taty,
potem czyta Pliki zbiorcze okresów okna, INTERMAX tylko do odczytu, także otwarty w Excelu, bez Kopii wejścia, tym
samym odczytem co Wpisanie raportów (``register_window``), potem Skrzynkę raportów i jej „Wysłane”, pyta rdzeń raportów (``reminders_due``) i wysyła przypomnienia po
kolei przez port (``ReminderMailbox``). Przed każdym mailem bierze chwilę z zegara znowu: gdy jest już poza porą, w
której sprawdzenie ruszyło (minęła 17:00 albo 22:00 albo laptop zasnął w trakcie i obudził się innego dnia), reszta przypomnień
czeka na następną porę, która zna wysłane z „Wysłanych” i z pamięci tej pracy Centrum. Cały odczyt aż po rdzeń, bez wysyłki, to ``due_reminders``: z
niego bierze przypomnienia praca Centrum i próba Przypomnień przed Wydaniem (``tools/proba_przypomnien.py``).

Pora tego dnia jest załatwiona, gdy sprawdzenie skończy się bez porażki, którą naprawia czas: wtedy do końca pory nie
czyta już niczego poza Ustawieniami. Załatwiona jest pora przy tych porach z Ustawień: zmiana pór otwiera porę na jedno
nowe sprawdzenie, a przed drugim mailem tej samej nazwanej pory chronią „Wysłane” i pamięć tej pracy Centrum. Nazwaną porę przypomnienia z
„Wysłanych” liczą pory z chwili jego wysyłki, nie bieżące (decyzja Maksa): poranne wysłane o 8:05 zamyka
poranną porę tego dnia także po jej przesunięciu na 9:00–17:00. Dlatego każdy czytelny odczyt z włączonymi
przypomnieniami, w porze przed wysyłką i poza porą, zapisuje pory, gdy różnią się od ostatnio zapisanych
(``REMINDERS_SCHEDULES``, ``SchedulesInEffect``).
Bez tego pliku wysyłała tylko wersja sprzed Ustawień Centrum, więc liczą pory z ADR 0030 (dzień Aktualizacji), a z
plikiem nieczytelnym pory z ADR 0030 razem z bieżącymi, zapisane w pliku na następne starty. Dopóki zapis pór się nie
uda (``zapis-por``), sprawdzenie nie wysyła, a pora zostaje otwarta. Brak sieci
(``InboxUnreachable``) zostawia porę otwartą, więc następna minuta tej samej pory próbuje znowu, a przypomnienia, które
już poszły, zna z „Wysłanych” i z pamięci tej pracy Centrum: Gmail kładzie mail w „Wysłanych” z opóźnieniem, więc
przypomnienia wysłane w tej pracy praca pamięta też w pamięci procesu (``sent_in_work`` w ``due_reminders``), jak
Wysyłka rozliczeń (``settlement_mailing``). Jeden zbiór wysłanych, które zna praca (``_known_sent``: „Wysłane” i
pamięć bez maili, które Gmail już tam położył), dostaje i rdzeń, i widok Raporty. Granicą jest ponowny start Centrum tuż po wysyłce: nowa praca zna wysłane
tylko z „Wysłanych”, więc przypomnienie, którego Gmail jeszcze tam nie położył, może pójść drugi raz. Pamięć jest
własna, a nie wspólna z Wysyłką rozliczeń za jednym modułem „wysłane przez Centrum”, bo obie liczą z wysłanych co
innego: przypomnienie porę z chwili wysyłki i Wykonawcę z adresów Listy, Mail z rozliczeniem stan pliku po jego
nazwie i chwili zmiany, z ostatnim mailem pliku w miejscu poprzedniego, a dostęp do skrzynki sprawdzają w innym
miejscu odczytu i z innym skutkiem. Odrzucone hasło aplikacji zakłada Zgłoszenie do Maksa
(``ReminderReport``) i zamyka porę, żeby Gmail nie dostawał złego hasła co minutę. Brak pliku, Ustawienia albo
nieczytelny INTERMAX zostawia porę otwartą: naprawa Maksa albo taty działa od następnej minuty.

Plik Przypomnień, Folderów albo Legendy czynności, którego system nie daje teraz czytać (np. trzyma go OneDrive), to nie
wyłączone przypomnienia ani niewskazany INTERMAX: pora zostaje otwarta, więc następna minuta tej samej pory próbuje znowu, a gdy
plik nie wróci do końca pory, dziennik Centrum dostaje jeden wpis z nazwą pliku (``plik-bez-odczytu``), przy pierwszym
sprawdzeniu po tej porze. Bez pliku Przypomnień porę liczą pory z ostatniego przeczytanego pliku w tej pracy Centrum, a
przed nim ostatnie pory z ``REMINDERS_SCHEDULES`` (``_unread_schedule``); wyniku dla widoku Raporty
takie sprawdzenie nie pisze, bo nie wie, czy przypomnienia mają dzień wdrożenia.

Praca nie jest Uruchomieniem procesu: nie przechodzi przez ``RunHost``, więc nie blokuje innych Uruchomień i ich nie
czeka, nie bierze INTERMAX na wyłączność i nie pisze Kopii wejścia ani Logów Uruchomienia. Każda wysyłka i każda
porażka trafia do dziennika Centrum, bez adresów, Wykonawców i treści maili (ADR 0028); tę samą porażkę dziennik
dostaje raz, aż przyczyna się zmieni. Wyjątkiem są przypomnienia wyłączone w Ustawieniach (``bez-wdrozenia``): są
wtedy wyłączone, a nie zepsute, więc sprawdzenie nie zostawia śladu ani w dzienniku, ani w ``config``, a pora zostaje
otwarta. Wynik ostatniego sprawdzenia w porze z dniem wdrożenia leży w ``REMINDERS_RESULT`` dla widoku Raporty:
``{schema_version: 1, checked_at, pora, failure, footer, sent: [{worker, day, sent_at}]}``, gdzie ``sent`` to wysłane przypomnienia, które zna praca, i te z tego sprawdzenia, przypisane Wykonawcom z listy adresów (pusta lista, gdy sprawdzenie
nie doszło do „Wysłanych”), a ``footer`` to ``present``, ``missing`` (stopka w Ustawieniach pusta) albo ``null``, gdy
sprawdzenie nie doszło do przypomnień. Widok Raporty
czyta go przez ``ReportReminders.shown`` tym samym kształtem (``_Result``): chwile wysłania po Wykonawcy i dniu i to, czy
ostatnie sprawdzenie nie znalazło stopki.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from rozliczenia import register_file
from rozliczenia.centrum import reminder_messages
from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.log import ReminderFailure
from rozliczenia.centrum.reports import ProblemFingerprint, ReminderReport, Reports
from rozliczenia.centrum.settings.files import usable
from rozliczenia.centrum.settings.owner import CentrumSettings, SettingsSnapshot, UnreadableFile
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.dad_files import DadFiles
from rozliczenia.message import StopError
from rozliczenia.report_entering import closed_periods, register_window
from rozliczenia.tool_files import REMINDERS_RESULT, REMINDERS_SCHEDULES
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.worker_report_inbox import (
    InboxUnreachable,
    MailRefused,
    Mails,
    MailSent,
    PasswordRejected,
    ReminderMailbox,
    SentReminders,
)
from rozliczenia.worker_reports import (
    DEFAULT_REMINDERS,
    OLD_VERSION_SCHEDULES,
    OwnEntries,
    Pora,
    Reminder,
    ReminderInputs,
    ReminderSchedule,
    ReportInputs,
    SchedulesInEffect,
    ScheduleSince,
    SentReminder,
    TimeRange,
    Window,
    WorkerAddresses,
    reminder_pora,
    reminders_due,
)

REMINDERS_THREAD: Final = "przypomnienia-o-raporcie"
CHECK_EVERY_S: Final = 60.0
_RESULT_VERSION: Final = 1


class ReminderRhythm(Protocol):
    def start(self, check: Callable[[], None]) -> None:
        """Woła ``check`` od teraz co ``CHECK_EVERY_S``, w innym wątku albo na żądanie testu."""
        ...

    def stop(self) -> None:
        """Kończy wołanie ``check``; trwające sprawdzenie kończy się samo."""
        ...


class MinuteRhythm:
    """Wątek demona ``REMINDERS_THREAD``, który woła ``check`` zaraz po starcie i potem co ``CHECK_EVERY_S``."""

    def __init__(self) -> None:
        self._stopped = threading.Event()

    def start(self, check: Callable[[], None]) -> None:
        def loop() -> None:
            while not self._stopped.is_set():
                check()
                self._stopped.wait(CHECK_EVERY_S)

        threading.Thread(target=loop, name=REMINDERS_THREAD, daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()


@dataclass(frozen=True)
class _Failed:
    cause: ReminderFailure
    failure: str | None = None
    retry: bool = True
    file: str | None = None


@dataclass(frozen=True)
class _Unread:
    """Plik Ustawień ``file`` bez odczytu w porze ``pora`` dnia ``day``: wpis w dzienniku Centrum czeka do końca pory."""

    day: date
    pora: Pora
    file: str


@dataclass
class _Check:
    """Wynik jednego sprawdzenia: porażka, stopka i przypomnienia (Wykonawca, dzień, chwila) dla widoku Raporty."""

    failed: _Failed | None = None
    footer: Literal["present", "missing"] | None = None
    sent: list[tuple[str, date, datetime]] = field(default_factory=list)


class _Sent(BaseModel):
    worker: str
    day: date
    sent_at: datetime


class _Result(BaseModel):
    """Kształt pliku ``REMINDERS_RESULT``, który pisze ``ReportReminders._write``, w polach, które czyta widok Raporty."""

    schema_version: Literal[1]
    footer: Literal["present", "missing"] | None
    sent: list[_Sent]


@dataclass(frozen=True)
class ShownReminders:
    """Wynik ostatniego sprawdzenia przypomnień dla widoku Raporty: chwile wysłania (UTC, rosnąco, jak w pliku po
    ``_write``) po Wykonawcy i dniu przypomnienia i to, czy sprawdzenie nie znalazło pliku stopki. Bez adresów, tematów
    i treści maili (ADR 0030)."""

    sent: Mapping[tuple[str, date], tuple[datetime, ...]] = field(default_factory=dict)
    without_footer: bool = False


class ReportReminders:
    """Praca Przypomnień o raporcie jednej pracy Centrum; ``check`` woła rytm, ``now`` to chwila ze strefą taty."""

    def __init__(
        self,
        work: CentrumWork,
        settings: CentrumSettings,
        mailbox: ReminderMailbox,
        files: DadFiles,
        reports: Reports,
        now: Callable[[], datetime],
    ) -> None:
        self._log = work.log
        self._settings = settings
        self._mailbox = mailbox
        self._files = files
        self._reports = reports
        self._now = now
        self._result = StateFile(
            work.config / REMINDERS_RESULT, work.log, where="wynik Przypomnień o raporcie", pause=work.pause
        )
        self._lock = threading.Lock()
        self._schedules = StateFile(
            work.config / REMINDERS_SCHEDULES, work.log, where="pory Przypomnień o raporcie", pause=work.pause
        )
        self._in_effect: SchedulesInEffect | None = None
        self._settled: tuple[date, Pora, ReminderSchedule] | None = None
        self._last_failure: _Failed | None = None
        self._schedule: ReminderSchedule | None = None
        self._unread: _Unread | None = None
        self._sent_in_work: list[SentReminder] = []

    def check(self) -> None:
        """Jedno sprawdzenie; nieoczekiwany wyjątek trafia do dziennika Centrum, a następna minuta próbuje znowu."""

        if not self._lock.acquire(blocking=False):
            return
        try:
            self._check()
        except Exception as failure:
            self._log.unexpected_failure(failure, where="Przypomnienia o raporcie")
        finally:
            self._lock.release()

    def shown(self) -> ShownReminders:
        """Wynik ostatniego sprawdzenia z ``REMINDERS_RESULT``; bez pliku albo z plikiem nieczytelnym pusty, bo widok
        Raporty pokazuje Wpisanie raportów także wtedy, gdy przypomnień nie ma albo ich wynik się zepsuł."""

        try:
            result = _Result.model_validate_json(self._result.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError):
            return ShownReminders()
        sent: dict[tuple[str, date], tuple[datetime, ...]] = {}
        for found in result.sent:
            sent[found.worker, found.day] = (*sent.get((found.worker, found.day), ()), found.sent_at)
        return ShownReminders(sent, without_footer=result.footer == "missing")

    def _check(self) -> None:
        """Sprawdzenie pory teraz. Wyłączone przypomnienia są wyłączone, a nie zepsute: tak stoi każde Centrum bez pliku
        przypomnień i każdy klon bez ``config`` taty, więc praca nie zostawia wtedy śladu ani w dzienniku, ani
        w ``config``."""

        now = self._now()
        snapshot = self._settings.snapshot()
        reminders = snapshot.reminders
        in_effect: SchedulesInEffect | None = None
        if isinstance(reminders, UnreadableFile):
            schedule = self._unread_schedule()
        else:
            schedule = self._schedule = reminders.schedule
            if reminders.sends is not None:
                in_effect = self._checked(now, schedule)
        pora = reminder_pora(now, schedule)
        self._close_unread(now.date(), pora)
        if pora is None or self._settled == (now.date(), pora, schedule):
            return
        if isinstance(reminders, UnreadableFile):
            self._unread = _Unread(now.date(), pora, reminders.name)
            return
        self._unread = None
        if in_effect is None:
            return
        found = _Check()
        if self._schedules.unavailable:
            found.failed = _Failed("zapis-por")
        else:
            self._send(now, snapshot, schedule, in_effect, found)
        failed = found.failed
        if failed is None or not failed.retry:
            self._settled = (now.date(), pora, schedule)
        self._unread = None if failed is None or failed.file is None else _Unread(now.date(), pora, failed.file)
        if failed is not None and failed.file is None and failed != self._last_failure:
            self._log.reminders_failed(cause=failed.cause, failure=failed.failure)
        self._last_failure = failed
        self._write(now, pora, found)

    def _unread_schedule(self) -> ReminderSchedule:
        """Pory przy pliku Przypomnień bez odczytu: z ostatniego pliku przeczytanego w tej pracy Centrum, a przed nim
        z ostatnich pór w ``REMINDERS_SCHEDULES``, bo plik zablokowany od startu Centrum nie mówi o porach taty nic
        innego. ``_checked`` zapisuje tam pory z każdego czytelnego odczytu przy włączonych przypomnieniach, także poza
        porą, więc zmiana pór, po której tata zamknął Centrum przed następną porą, też tam jest. Bez wpisu w tym pliku
        praca nie przeczytała pliku Przypomnień z włączonymi przypomnieniami ani razu (włączenie bez minuty pracy
        Centrum przed blokadą), więc żadne pory taty nie są znane i zostają pory z ADR 0030: to granica, nie stan."""

        if self._schedule is not None:
            return self._schedule
        in_effect = schedules_in_effect(self._schedules.path, DEFAULT_REMINDERS.schedule)
        return in_effect.changes[-1].schedule if in_effect.changes else DEFAULT_REMINDERS.schedule

    def _close_unread(self, day: date, pora: Pora | None) -> None:
        """Wpis w dzienniku Centrum o pliku Ustawień, który do końca swojej pory nie dał się przeczytać: pierwsze
        sprawdzenie poza tą porą go zapisuje."""

        unread = self._unread
        if unread is not None and (unread.day, unread.pora) != (day, pora):
            self._log.reminders_failed(cause="plik-bez-odczytu", file=unread.file)
            self._unread = None

    def _checked(self, now: datetime, schedule: ReminderSchedule) -> SchedulesInEffect:
        """Pory, przy których sprawdzała praca, z porami tego odczytu; nowe zapisuje przy każdym czytelnym odczycie
        z włączonymi przypomnieniami, w porze przed wysyłką i poza porą, a zapis, który czeka w ``StateFile``, ponawia.
        Odczyt poza porą nie zmienia przypisania „Wysłanych”: między ostatnim sprawdzeniem przy starych porach a pierwszym
        przy nowych nie idzie żaden mail. Dopóki zapis czeka, sprawdzenie nie wysyła: po ponownym starcie Centrum bez
        pliku pór wysłane liczyłyby pory z ADR 0030, a nie pory z chwili wysyłki."""

        before = self._in_effect if self._in_effect is not None else schedules_in_effect(self._schedules.path, schedule)
        self._in_effect = before.checked(now, schedule)
        if self._in_effect is not before:
            self._schedules.write(_schedules_document(self._in_effect))
        else:
            self._schedules.retry()
        return self._in_effect

    def _send(
        self, now: datetime, snapshot: SettingsSnapshot, schedule: ReminderSchedule, in_effect: SchedulesInEffect, found: _Check
    ) -> None:
        read = due_reminders(now, snapshot, self._mailbox, self._files, in_effect, tuple(self._sent_in_work))
        match read:
            case NotRead():
                found.failed = _Failed(read.cause, read.failure, file=read.file)
                return
            case PasswordRejected() | InboxUnreachable():
                self._failed(read, found)
                return
            case DueReminders():
                pass
        found.footer = "missing" if read.footer is None else "present"
        found.sent = [*_by_worker(read.sent, read.addresses)]
        for reminder in read.due:
            moment = self._now()
            if (moment.date(), reminder_pora(moment, schedule)) != (now.date(), reminder_pora(now, schedule)):
                return
            outcome = self._mailbox.send(reminder, moment)
            match outcome:
                case MailSent():
                    self._sent_in_work.append(SentReminder(frozenset(reminder.recipients), reminder.day, moment))
                    self._log.reminder_sent(day=reminder.day.isoformat(), pora=_pora(now, schedule))
                    found.sent.append((reminder.worker, reminder.day, moment))
                case MailRefused(cause=cause):
                    found.failed = _Failed("odmowa-wysylki", cause, retry=False)
                case PasswordRejected() | InboxUnreachable():
                    self._failed(outcome, found)
                    return

    def _failed(self, outcome: PasswordRejected | InboxUnreachable, found: _Check) -> None:
        match outcome:
            case PasswordRejected():
                found.failed = _Failed("haslo-odrzucone", retry=False)
                message = reminder_messages.password_rejected()
                handle = self._reports.handle(ProblemFingerprint.of_reminders(message))
                handle.prepare(ReminderReport.of(message, self._log))
                handle.send()
            case InboxUnreachable(cause=cause):
                found.failed = _Failed("brak-sieci", cause)

    def _write(self, now: datetime, pora: Pora, found: _Check) -> None:
        document = {
            "schema_version": _RESULT_VERSION,
            "checked_at": now.astimezone(timezone.utc).isoformat(),
            "pora": pora.value,
            "failure": None if found.failed is None else found.failed.cause,
            "footer": found.footer,
            "sent": [
                {"worker": worker, "day": day.isoformat(), "sent_at": sent_at.astimezone(timezone.utc).isoformat()}
                for worker, day, sent_at in sorted(found.sent)
            ],
        }
        self._result.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


NotReadCause = Literal["bez-wdrozenia", "plik-bez-odczytu", "bez-ustawien", "bez-dostepu", "bez-adresow", "okresy", "intermax"]
"""Przyczyny ``ReminderFailure``, przy których sprawdzenie nie doszło do skrzynki albo do rdzenia."""


@dataclass(frozen=True)
class DueReminders:
    """Odczyt sprawdzenia, które doszło do przypomnień: przypomnienia, które należą się teraz, wysłane przypomnienia,
    które zna praca (``_known_sent``), adresy Wykonawców i stopka taty z Ustawień (``None``: stopka pusta)."""

    due: tuple[Reminder, ...]
    sent: tuple[SentReminder, ...]
    addresses: WorkerAddresses
    footer: str | None


@dataclass(frozen=True)
class NotRead:
    """Sprawdzenie nie doszło do przypomnień przez plik, Ustawienia albo INTERMAX: przyczyna, nazwa typu wyjątku i nazwa
    pliku Ustawień bez odczytu (``plik-bez-odczytu``)."""

    cause: NotReadCause
    failure: str | None = None
    file: str | None = None


def due_reminders(
    now: datetime,
    snapshot: SettingsSnapshot,
    mailbox: ReminderMailbox,
    files: DadFiles,
    in_effect: SchedulesInEffect,
    sent_in_work: tuple[SentReminder, ...],
) -> DueReminders | NotRead | PasswordRejected | InboxUnreachable:
    """Przypomnienia, które należą się w chwili ``now``, po odczycie w kolejności z docstringu modułu: Przypomnienia o
    raporcie, Ustawienia Centrum z Legendą czynności i Listą Wykonawców z migawki ``snapshot``, Pliki zbiorcze okresów okna,
    INTERMAX tylko do odczytu, skrzynka i jej „Wysłane” przez ``mailbox``, z porami „Wysłanych” z ``in_effect``
    (``schedules_in_effect``). Przypomnienia wysłane w tej pracy Centrum (``sent_in_work``) liczą się jak te z
    „Wysłanych”: zamykają porę i są w ``DueReminders.sent`` dla widoku Raporty. Niczego nie wysyła i nie zapisuje: wysyła
    praca przypomnień, a próba Przypomnień (``tools/proba_przypomnien.py``) liczy ten sam wynik bez wysyłki do
    Wykonawców."""

    reminders = snapshot.reminders
    if isinstance(reminders, UnreadableFile):
        return NotRead("plik-bez-odczytu", file=reminders.name)
    rollout = reminders.sends
    if rollout is None:
        return NotRead("bez-wdrozenia")
    settings = snapshot.folders
    if isinstance(settings, UnreadableFile):
        return NotRead("plik-bez-odczytu", file=settings.name)
    legend = snapshot.activity_legend
    if isinstance(legend, UnreadableFile):
        return NotRead("plik-bez-odczytu", file=legend.name)
    if settings.register is None or settings.periods_directory is None:
        return NotRead("bez-ustawien")
    if mailbox.access() != "ready":
        return NotRead("bez-dostepu")
    workers = usable(snapshot.workers)
    if workers is None:
        return NotRead("bez-adresow")
    addresses = workers.addresses()
    today = now.date()
    try:
        closed = closed_periods(settings.periods_directory, Window.periods(today, rollout))
    except StopError:
        return NotRead("okresy")
    window = Window.of(today, rollout, closed)
    try:
        register = register_file.read(settings.register, files, despite_excel_lock=True)
        intermax = register_window(register, window, addresses, copy=False)
    except (WorkbookError, StopError) as error:
        return NotRead("intermax", type(error).__name__)
    mails = mailbox.mails_since(window.first)
    if not isinstance(mails, Mails):
        return mails
    filed = mailbox.sent_reminders(window.first)
    if not isinstance(filed, SentReminders):
        return filed
    sent = _known_sent(filed.reminders, sent_in_work)
    reports = ReportInputs(
        mails=mails.mails,
        addresses=addresses,
        orders=intermax.orders,
        window=window,
        memory=OwnEntries.EMPTY,
        kept=frozenset(),
        present=tuple(read for _, read in intermax.present),
        legend=legend,
        ordered_days=intermax.ordered_days,
    )
    due = reminders_due(ReminderInputs(now, reports, sent, workers.reminded(), reminders, in_effect))
    return DueReminders(due, sent, addresses, reminders.footer if reminders.footer.strip() else None)



class _Range(BaseModel):
    od: time
    do: time


class _Schedule(BaseModel):
    poranna: _Range
    wieczorna: _Range
    pierwsze: time

    def schedule(self) -> ReminderSchedule:
        return ReminderSchedule(
            TimeRange(self.poranna.od, self.poranna.do), TimeRange(self.wieczorna.od, self.wieczorna.do), self.pierwsze
        )


class _Since(_Schedule):
    od: datetime


class _Schedules(BaseModel):
    """Kształt pliku ``REMINDERS_SCHEDULES``, który pisze ``_schedules_document``: pory sprzed pierwszego wpisu
    (``przed``) i wpisy pór od chwili ich pierwszego sprawdzenia (``pory``)."""

    schema_version: Literal[1]
    przed: list[_Schedule] = Field(min_length=1)
    pory: list[_Since]


def schedules_in_effect(path: Path, current: ReminderSchedule) -> SchedulesInEffect:
    """Pory, przy których sprawdzała praca przypomnień, z pliku ``REMINDERS_SCHEDULES``. Bez pliku praca tej wersji
    jeszcze nie sprawdzała w porze, więc przypomnienia z „Wysłanych” wysłała wersja sprzed Ustawień Centrum przy porach
    z ADR 0030. Z plikiem nieczytelnym albo z chwilą bez strefy nie wiadomo, przy jakich porach sprawdzała, więc
    wysłane liczą pory z ADR 0030 i bieżące ``current``: więcej zamkniętych pór, a nie drugi mail tej samej pory."""

    try:
        found = _Schedules.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SchedulesInEffect()
    except (OSError, UnicodeDecodeError, ValidationError):
        return SchedulesInEffect(OLD_VERSION_SCHEDULES | {current})
    if any(entry.od.tzinfo is None for entry in found.pory):
        return SchedulesInEffect(OLD_VERSION_SCHEDULES | {current})
    return SchedulesInEffect(
        frozenset(entry.schedule() for entry in found.przed),
        tuple(ScheduleSince(entry.od, entry.schedule()) for entry in sorted(found.pory, key=lambda entry: entry.od)),
    )


def _schedules_document(in_effect: SchedulesInEffect) -> str:
    def shown(schedule: ReminderSchedule) -> dict[str, object]:
        return {
            "poranna": {"od": f"{schedule.morning.start:%H:%M}", "do": f"{schedule.morning.end:%H:%M}"},
            "wieczorna": {"od": f"{schedule.evening.start:%H:%M}", "do": f"{schedule.evening.end:%H:%M}"},
            "pierwsze": f"{schedule.first:%H:%M}",
        }

    document = {
        "schema_version": _RESULT_VERSION,
        "przed": sorted((shown(schedule) for schedule in in_effect.before), key=lambda found: json.dumps(found)),
        "pory": [{"od": change.since.isoformat(), **shown(change.schedule)} for change in in_effect.changes],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _pora(now: datetime, schedule: ReminderSchedule) -> str:
    pora = reminder_pora(now, schedule)
    return "" if pora is None else pora.value


def _known_sent(filed: tuple[SentReminder, ...], in_work: tuple[SentReminder, ...]) -> tuple[SentReminder, ...]:
    """Wysłane przypomnienia, które zna praca: te z „Wysłanych” i te z pamięci tej pracy, których Gmail jeszcze tam nie
    położył (``SentReminder.same_mail``), więc mail położony już przez Gmaila liczy się raz."""

    return (*filed, *(mine for mine in in_work if not any(mine.same_mail(found) for found in filed)))


def _by_worker(sent: tuple[SentReminder, ...], addresses: WorkerAddresses) -> list[tuple[str, date, datetime]]:
    """Wysłane przypomnienia przypisane Wykonawcom z listy adresów, raz na Wykonawcę w przypomnieniu."""

    found: list[tuple[str, date, datetime]] = []
    for reminder in sent:
        reached = {addresses.logins[address] for address in reminder.recipients if address in addresses.logins}
        found += [(worker, reminder.day, reminder.sent_at) for worker in sorted(reached)]
    return found
