"""Logi Wpisania raportów (ADR 0028): pole ``report_entering`` pliku Logów Uruchomienia (``run_logs.RunLog``), czyli
Wpisy, problemy i zmiany komórek bez adresów nadawców, tematów i treści maili poza Wpisami.

``LoggedReports.of_run`` składa je z faktów Uruchomienia, które wpis procesu w katalogu dostaje przy Logach
(``ProcessKind.logs``), a ``LoggedReports.replay`` czyta z nich z powrotem wejście kliknięcia dla odtworzenia
Uruchomienia z Logów albo powód, dla którego Logi go nie wyznaczają. Kolejność deklaracji pól to kolejność kluczy w
pliku, a pole, którego nie mają Logi z wcześniejszych Wydań, czyta się z domyślną (opis przy rekordzie), bo te pliki
czytają karta z Logów, Historia i odtworzenie.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from rozliczenia.client_data import MASKS
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import EnteringFacts, EnteringSummary, SavedState
from rozliczenia.worker_reports import (
    AddBar,
    ConflictingVerdicts,
    Kept,
    Login,
    MailId,
    MailRead,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    MoveBar,
    RefusedMove,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportProblem,
    SubjectFault,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    VerdictFault,
)


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LoggedReportEntry(_Record):
    """Wpis raportu: numer zlecenia z treści maila (pod strażnikiem: 9 cyfr z rzędu maskuje jak telefon), ``tak``/``nie``
    albo powód jego braku i czynności (pod strażnikiem: telefon i ulica zamaskowane)."""

    number: str
    verdict: Literal["tak", "nie"] | None
    fault: VerdictFault | None
    activities: str

    @classmethod
    def of(cls, entry: ReportEntry) -> LoggedReportEntry:
        return cls(
            number=entry.number,
            verdict=None if entry.verdict is None else entry.verdict.value,
            fault=entry.fault,
            activities=entry.activities,
        )


class LoggedReportMail(_Record):
    """Raport wykonawcy od Wykonawcy z listy adresów: skrót maila, chwila przyjścia, login, dzień z tematu i Wpisy; bez
    adresu, tematu i reszty treści."""

    kind: Literal["report"]
    mail: str
    arrived: datetime
    worker: str
    day: date
    entries: list[LoggedReportEntry]


class LoggedUnreadableMail(_Record):
    """Mail od Wykonawcy z tematem, z którego nie da się odczytać dnia; bez tematu."""

    kind: Literal["unreadable"]
    mail: str
    arrived: datetime
    worker: str
    fault: SubjectFault
    numbers: list[str] | None = None
    """Numery Wpisów treści maila rosnąco, po których poprawiony mail zdejmuje ostrzeżenie. ``None``: Logi sprzed tego
    pola (v0.7.0), które odtworzenie czyta jak mail bez Wpisów, więc ostrzeżenie zdjęte przez poprawkę wraca w nim jako
    różnica."""


class LoggedStrangerMail(_Record):
    """Raport wykonawcy z adresu spoza listy adresów; bez adresu."""

    kind: Literal["stranger"]
    mail: str
    arrived: datetime
    day: date


LoggedMail = Annotated[LoggedReportMail | LoggedUnreadableMail | LoggedStrangerMail, Field(discriminator="kind")]


def _mail(read: MailRead) -> LoggedMail:
    match read:
        case ReadReport():
            entries = [LoggedReportEntry.of(entry) for entry in read.entries]
            return LoggedReportMail(
                kind="report", mail=read.mail.digest, arrived=read.arrived, worker=read.worker, day=read.day, entries=entries
            )
        case ReadUnreadable():
            return LoggedUnreadableMail(
                kind="unreadable",
                mail=read.mail.digest,
                arrived=read.arrived,
                worker=read.worker,
                fault=read.fault,
                numbers=sorted(read.numbers),
            )
        case ReadStranger():
            return LoggedStrangerMail(kind="stranger", mail=read.mail.digest, arrived=read.arrived, day=read.day)
        case _:
            assert_never(read)


def _read(mail: LoggedMail) -> MailRead:
    """Odczyt maila z jego zapisu w Logach, czyli zapis w drugą stronę: odtworzenie Uruchomienia z Logów (#1233) podaje
    go procesowi jako mail w postaci kanonicznej (``worker_reports.as_mail``)."""

    match mail:
        case LoggedReportMail():
            entries = tuple(
                ReportEntry(
                    OrderNumber(entry.number),
                    None if entry.verdict is None else Verdict(entry.verdict),
                    entry.fault,
                    entry.activities,
                )
                for entry in mail.entries
            )
            return ReadReport(MailId(mail.mail), mail.arrived, Login(mail.worker), mail.day, entries)
        case LoggedUnreadableMail():
            numbers = frozenset(OrderNumber(number) for number in mail.numbers or ())
            return ReadUnreadable(MailId(mail.mail), mail.arrived, Login(mail.worker), mail.fault, numbers)
        case LoggedStrangerMail():
            return ReadStranger(MailId(mail.mail), mail.arrived, mail.day)
        case _:
            assert_never(mail)


class LoggedOrderPlace(_Record):
    """Miejsce zlecenia w INTERMAX: dzień i Wykonawca."""

    day: date
    worker: str


class LoggedOrderProblem(_Record):
    """Problem Wpisu raportu Wykonawcy z dnia: rodzaj, numer z treści maila (pod strażnikiem jak w
    ``LoggedReportEntry``), a przy ``missing_verdict`` powód, przy ``repeated_number`` miejsce każdego zlecenia z tym
    numerem (``places``), przy ``refused_move`` dzień zlecenia (``order_days``) i powód odmowy Przeniesienia (``bar``),
    a przy ``unknown_number`` powód, dla którego Centrum nie dopisało zlecenia (``bar``; Logi sprzed Zleceń dopisanych z
    raportu go nie mają). Logi sprzed #1350 mają też ``foreign_order`` z Wykonawcą zlecenia (``owner``) i ``other_day``
    z dniami zleceń z tym numerem (``order_days``): dziś to ``repeated_number``."""

    kind: Literal[
        "missing_verdict",
        "unknown_number",
        "foreign_order",
        "other_day",
        "repeated_order",
        "repeated_number",
        "refused_move",
    ]
    worker: str
    day: date
    number: str
    fault: VerdictFault | None = None
    owner: str | None = None
    order_days: list[date] = []
    places: list[LoggedOrderPlace] = []
    bar: MoveBar | AddBar | None = None

    @field_validator("bar", mode="before")
    @classmethod
    def _bar_of_kind(cls, bar: object, info: ValidationInfo) -> object:
        """Słowo powodu z pliku to członek enuma rodzaju problemu, bo ``not_ordered`` mają oba."""

        kind = _BARS.get(info.data.get("kind", ""))
        return kind(bar) if isinstance(bar, str) and kind is not None else bar


_BARS: Final[Mapping[str, type[MoveBar] | type[AddBar]]] = {"refused_move": MoveBar, "unknown_number": AddBar}


class LoggedConflictProblem(_Record):
    """Raport wykonawcy z Wpisami jednego numeru o przeciwnym zamiarze: skrót maila, chwila przyjścia, Wykonawca, dzień
    z tematu, numer i te Wpisy (pod strażnikiem jak w ``LoggedReportEntry``)."""

    kind: Literal["conflicting_verdicts"]
    mail: str
    arrived: datetime
    worker: str
    day: date
    number: str
    entries: list[LoggedReportEntry]


class LoggedSubjectProblem(_Record):
    kind: Literal["unreadable_subject"]
    mail: str
    worker: str
    arrived: datetime
    fault: SubjectFault


class LoggedSenderProblem(_Record):
    """Raport wykonawcy z adresu spoza listy adresów: skrót maila i dzień, bez adresu."""

    kind: Literal["unknown_sender"]
    mail: str
    day: date


class LoggedOwnEntry(_Record):
    """Komórka zlecenia INTERMAX z wartością Wpisania raportów. ``number`` to ``NUMER ZL.`` z wiersza INTERMAX jako
    liczba: liczby spoza ``READ_VALUES`` strażnik nie sprawdza, a numer zlecenia może wyjść (ADR 0025), więc 9 cyfr nie
    staje się maską telefonu. ``value`` to tekst komórki pod strażnikiem."""

    number: int
    day: date
    worker: str
    column: ReportColumn
    value: str

    @classmethod
    def of(cls, key: OrderKey, column: ReportColumn, value: str) -> LoggedOwnEntry:
        return cls(number=int(key.number), day=key.day, worker=key.worker, column=column, value=value)


class LoggedManualProblem(_Record):
    """Różnica Wpisu z ręczną wartością komórki: komórka zlecenia jak w ``LoggedOwnEntry`` z wartością z Wpisu
    (``value``) i ręczną (``manual``)."""

    kind: Literal["manual_difference"]
    cell: LoggedOwnEntry
    manual: str


LoggedProblem = Annotated[
    LoggedOrderProblem | LoggedConflictProblem | LoggedSubjectProblem | LoggedSenderProblem | LoggedManualProblem,
    Field(discriminator="kind"),
]


def _problem(problem: ReportProblem) -> LoggedProblem:
    match problem:
        case UnreadableSubject():
            return LoggedSubjectProblem(
                kind="unreadable_subject",
                mail=problem.mail.digest,
                worker=problem.worker,
                arrived=problem.arrived,
                fault=problem.fault,
            )
        case UnknownSender():
            return LoggedSenderProblem(kind="unknown_sender", mail=problem.mail.digest, day=problem.day)
        case MissingVerdict():
            return LoggedOrderProblem(
                kind="missing_verdict",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                fault=problem.fault,
            )
        case ConflictingVerdicts():
            return LoggedConflictProblem(
                kind="conflicting_verdicts",
                mail=problem.mail.digest,
                arrived=problem.arrived,
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                entries=[LoggedReportEntry.of(entry) for entry in problem.entries],
            )
        case UnknownNumber():
            return LoggedOrderProblem(
                kind="unknown_number",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                bar=problem.bar,
            )
        case RepeatedOrder():
            return LoggedOrderProblem(kind="repeated_order", worker=problem.worker, day=problem.day, number=problem.number)
        case RepeatedNumber():
            return LoggedOrderProblem(
                kind="repeated_number",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                places=[LoggedOrderPlace(day=day, worker=worker) for day, worker in problem.places],
            )
        case RefusedMove():
            return LoggedOrderProblem(
                kind="refused_move",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                order_days=[problem.order_day],
                bar=problem.bar,
            )
        case ManualDifference():
            cell = LoggedOwnEntry.of(problem.key, problem.column, problem.reported)
            return LoggedManualProblem(kind="manual_difference", cell=cell, manual=problem.manual)
        case _:
            assert_never(problem)


class LoggedChange(_Record):
    """Komórka, którą Wpisanie raportów wpisuje: arkusz, wiersz, kolumna i tekst (pod strażnikiem)."""

    sheet: str
    row: int
    column: ReportColumn
    value: str


class LoggedMove(_Record):
    """Przeniesienie zlecenia, które Wpisanie raportów zapisuje: arkusz i wiersz zlecenia sprzed zapisu, dzień i
    ``WYKONAWCA`` po zapisie."""

    sheet: str
    row: int
    day: date
    worker: str


class LoggedAdded(_Record):
    """Zlecenie dopisane z raportu, które Wpisanie raportów zapisuje: arkusz, dzień, ``WYKONAWCA``, numer jak w
    ``LoggedOwnEntry`` (liczba z numeru z aplikacji firmowej, 8 cyfr), ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` (pod
    strażnikiem; ``None``: pusta)."""

    sheet: str
    day: date
    worker: str
    number: int
    successful: Literal["tak", "nie"]
    completed: str | None


class LoggedOrderless(_Record):
    """Numer z Wpisem w kliknięciu, który INTERMAX ma w przeczytanym wierszu bez zlecenia, także obok zlecenia tego
    numeru (``report_entering.Orderless``): arkusz i numer jak w ``LoggedOwnEntry``, a ``day`` dzień zlecenia, gdy każdy
    przeczytany wiersz numeru to zlecenie z dniem sprzed ``Window.start`` (Logi sprzed #1374 r4 go nie mają).
    Odtworzenie stawia go na dole arkusza jak Surowe zlecenie, z tym dniem i Wykonawcą, gdy ``day`` go ma, bo Kopia
    wejścia Wpisania raportów ma tylko uporządkowane wiersze zleceń z dni od ``Window.start``."""

    sheet: str
    number: int
    day: date | None = None


class LoggedOwnMove(_Record):
    """Pamięć zlecenia Wpisania raportów (``OwnMove``): numer jak w ``LoggedOwnEntry``, dzień i Wykonawca, u którego
    Centrum je zostawiło, dzień, Wykonawca i pisownia ``WYKONAWCA`` sprzed pierwszego Przeniesienia Centrum, chwila
    przyjścia najświeższego maila, na który Centrum zadziałało, czy tata zmienił Wykonawcę po Przeniesieniu Centrum
    (Logi z gałęzi #1347 sprzed jej trzeciej rundy go nie mają) i czy Centrum dopisało to zlecenie (Logi sprzed Zleceń
    dopisanych z raportu go nie mają)."""

    number: int
    day: date
    worker: str
    origin_day: date
    origin_worker: str
    origin_name: str
    since: datetime
    overridden: bool = False
    added: bool = False

    @classmethod
    def of(cls, move: OwnMove) -> LoggedOwnMove:
        return cls(
            number=int(move.number),
            day=move.day,
            worker=move.worker,
            origin_day=move.origin_day,
            origin_worker=move.origin_worker,
            origin_name=move.origin_name,
            since=move.since,
            overridden=move.overridden,
            added=move.added,
        )


class LoggedReports(_Record):
    """Wpisanie raportów (ADR 0028) bez adresów nadawców, tematów i treści maili poza Wpisami.

    ``today`` i okno dni od ``rollout`` (dzień wdrożenia tego kliknięcia; ``rollout_before`` z pamięci przed nim,
    ``None``: pierwsze kliknięcie) bez dni okresów ``closed`` (tokeny okresów okna z Plikiem zbiorczym; Logi sprzed
    #1229 ich nie mają, bo wtedy kliknięcie ich nie sprawdzało), ``skipped``: maile, których Skrzynka raportów nie umiała przeczytać, ``mails``
    przeczytane maile po chwili przyjścia, ``problems`` problemy rdzenia raportów, ``changes`` komórki do wpisania,
    ``memory_before`` zapamiętane wpisy zleceń z Wpisami tego kliknięcia, ``kept`` decyzje „Zostaw moją” tych zleceń z
    migawki kliknięcia (komórka z treścią Wpisu jako ``value``; Logi sprzed #1231 ich nie mają), ``moves`` Przeniesienia
    zleceń do zapisu, ``moves_before`` zapamiętane miejsca zleceń numerów z Wpisami tego kliknięcia (Logi sprzed #1347 nie
    mają obu), ``added`` Zlecenia dopisane z raportu do zapisu, ``orderless`` numery z Wpisem tego kliknięcia z
    przeczytanych wierszy INTERMAX bez zlecenia (Logi sprzed Zleceń dopisanych z raportu nie mają obu), a ``written``
    liczba wpisanych komórek (``None``: zapisu nie było, np. Zatrzymanie przy zapisie).
    """

    today: date
    rollout_before: date | None
    rollout: date
    closed: list[str] = []
    skipped: int
    mails: list[LoggedMail]
    problems: list[LoggedProblem]
    changes: list[LoggedChange]
    memory_before: list[LoggedOwnEntry]
    kept: list[LoggedOwnEntry] = []
    moves: list[LoggedMove] = []
    moves_before: list[LoggedOwnMove] = []
    added: list[LoggedAdded] = []
    orderless: list[LoggedOrderless] = []
    written: int | None

    @classmethod
    def of(cls, facts: EnteringFacts, written: int | None) -> LoggedReports:
        return cls(
            today=facts.today,
            rollout_before=facts.rollout_before,
            rollout=facts.rollout,
            closed=list(facts.closed),
            skipped=facts.skipped,
            mails=[_mail(read) for read in facts.mails],
            problems=[_problem(problem) for problem in facts.problems],
            changes=[
                LoggedChange(sheet=change.order.sheet, row=change.order.row, column=change.column, value=change.value)
                for change in facts.changes
            ],
            memory_before=[LoggedOwnEntry.of(entry.key, entry.column, entry.value) for entry in facts.memory_before],
            kept=[LoggedOwnEntry.of(kept.key, kept.column, kept.reported) for kept in facts.kept],
            moves=[
                LoggedMove(sheet=move.order.sheet, row=move.order.row, day=move.day, worker=move.worker)
                for move in facts.moves
            ],
            moves_before=[LoggedOwnMove.of(move) for move in facts.moves_before],
            added=[
                LoggedAdded(
                    sheet=added.sheet,
                    day=added.day,
                    worker=added.worker,
                    number=int(added.number),
                    successful=Verdict(added.successful).value,
                    completed=added.completed,
                )
                for added in facts.added
            ],
            orderless=[
                LoggedOrderless(sheet=found.sheet, number=int(found.number), day=found.day) for found in facts.orderless
            ],
            written=written,
        )

    @classmethod
    def of_run(cls, summary: EnteringSummary | None, facts: object) -> LoggedReports | None:
        """Logi Wpisania raportów z podsumowania albo z faktów Zatrzymania: po zapisie ``EnteringSummary`` (także
        Zatrzymanie przy konflikcie po zapisie), przed zapisem ``EnteringFacts`` bez liczby wpisanych komórek, a
        ``None``, gdy Zatrzymanie przyszło przed rdzeniem raportów."""

        match summary, facts:
            case EnteringSummary() as done, _:
                return cls.of(done.facts, done.written)
            case _, EnteringSummary() as done:
                return cls.of(done.facts, done.written)
            case _, EnteringFacts() as stopped:
                return cls.of(stopped, None)
            case _:
                return None

    def replay(self) -> EnteringReplay | Unreplayable:
        """Wejście kliknięcia z Logów dla odtworzenia Uruchomienia: maile, pamięć wpisów i decyzje „Zostaw moją” sprzed
        kliknięcia i numery bez zlecenia, z zastrzeżeniami, a ``Unreplayable``, gdy Logi nie wyznaczają numeru zlecenia
        Wpisu albo pamięci."""

        masked = [entry.number for entry in _logged_entries(self) if not _digits(entry.number)]
        if masked:
            return Unreplayable(
                f"Wpis raportu w Logach ma numer zlecenia zamaskowany przez strażnika reguły danych ({masked[0]}: 9 cyfr "
                "z rzędu strażnik bierze za telefon), więc odtworzenie nie wie, do którego zlecenia szedł ten Wpis"
            )
        numbers = _numbers(self)
        for name, logged in (("pamięć wpisów", self.memory_before), ("decyzje „Zostaw moją”", self.kept)):
            unknown = [entry for entry in logged if len(_texts(numbers, entry.number, entry.day, entry.worker)) != 1]
            if unknown:
                entry = unknown[0]
                return Unreplayable(
                    f"{name} w Logach ma zlecenie {entry.number} Wykonawcy {entry.worker} z {entry.day:%d.%m.%Y} "
                    "tylko jako liczbę, a jego numeru nie ma w dokładnie jednym Wpisie raportu w Logach, więc "
                    "odtworzenie nie wie, czy numer ma zera na początku"
                )
        try:
            saved = _saved(self)
        except ValueError as error:
            return Unreplayable(
                f"pamięć wpisów i zleceń w Logach z numerami w postaci z Wpisów raportu łamie regułę pamięci "
                f"({str(error).rstrip('.')}), a Logi mają jej numery tylko jako liczbę, więc odtworzenie nie wie, które z "
                "nich mają zera na początku"
            )
        reservations: list[str] = []
        counted = Counter(
            {mask: sum(entry.activities.count(mask) for entry in _logged_entries(self)) for mask in MASKS}
        )
        if +counted:
            masks = ", ".join(f"{mask} ×{count}" for mask, count in (+counted).most_common())
            reservations.append(
                f"Wpisy raportu w Logach mają maski strażnika reguły danych ({masks}): odtworzenie wpisuje do INTERMAX "
                "maskę w miejscu czynności Wykonawcy, więc reguła, która porównuje je z komórką, może zdecydować inaczej"
            )
        if any(isinstance(mail, LoggedUnreadableMail) and mail.numbers is None for mail in self.mails):
            reservations.append(
                "Logi sprzed numerów Wpisów maila z nieczytelnym tematem (v0.7.0): odtworzenie czyta ten mail bez Wpisów, "
                "więc ostrzeżenie o nieczytelnym temacie, które u taty zdjął poprawiony mail, wraca w odtworzeniu jako "
                "różnica"
            )
        return EnteringReplay(
            today=self.today,
            closed=tuple(self.closed),
            skipped=self.skipped,
            mails=tuple(_read(mail) for mail in self.mails),
            strangers=tuple(_strangers(self)),
            saved=saved,
            orderless=tuple(_orderless(self)),
            reservations=tuple(reservations),
        )


@dataclass(frozen=True)
class EnteringReplay:
    """Wejście kliknięcia Wpisania raportów z Logów: dzień kliknięcia, tokeny okresów zamkniętych, maile, których
    Skrzynka raportów nie umiała przeczytać, przeczytane maile po kolei, numer adresu każdego maila spoza listy adresów
    po kolei, pamięć wpisów i decyzje „Zostaw moją” sprzed kliknięcia, numery z Wpisem z wierszy INTERMAX bez
    zlecenia i zastrzeżenia odtworzenia, które z nich wynikają."""

    today: date
    closed: tuple[str, ...]
    skipped: int
    mails: tuple[MailRead, ...]
    strangers: tuple[int, ...]
    saved: SavedState
    orderless: tuple[ReplayedOrderless, ...]
    reservations: tuple[str, ...]

    @classmethod
    def without_logs(cls, today: date) -> EnteringReplay:
        """Kliknięcie z dnia ``today`` bez Logów Wpisania raportów: pusta skrzynka i pamięć bez dnia wdrożenia."""

        return cls(today, (), 0, (), (), SavedState(None, OwnEntries.EMPTY), (), ())


@dataclass(frozen=True)
class ReplayedOrderless:
    """Numer bez zlecenia z Logów (``LoggedOrderless``) z wartością ``NUMER ZL.`` wiersza, który odtworzenie stawia na
    dole arkusza ``sheet``: postać z zerem na początku z Wpisu, gdy Wpis ją ma, a inaczej liczba."""

    sheet: str
    number: str | int
    day: date | None


@dataclass(frozen=True)
class Unreplayable:
    """Logi Wpisania raportów, z których odtworzenie nie wyznaczy wejścia kliknięcia, i powód."""

    reason: str


def _strangers(entering: LoggedReports) -> list[int]:
    """Numer adresu każdego maila spoza listy adresów w Logach, po kolei: jeden z tylu adresów, ile problemów nieznanego
    nadawcy mają w Logach jego skrót i dzień, bo rdzeń daje jeden problem na różny adres maili z tym Message-ID."""

    senders = Counter((problem.mail, problem.day) for problem in entering.problems if isinstance(problem, LoggedSenderProblem))
    seen: Counter[tuple[str, date]] = Counter()
    found: list[int] = []
    for mail in entering.mails:
        if isinstance(mail, LoggedStrangerMail):
            key = (mail.mail, mail.day)
            found.append(seen[key] % max(senders[key], 1))
            seen[key] += 1
    return found


def _digits(number: str) -> bool:
    return number.isascii() and number.isdigit()


def _logged_entries(entering: LoggedReports) -> list[LoggedReportEntry]:
    return [entry for mail in entering.mails if isinstance(mail, LoggedReportMail) for entry in mail.entries]


def _texts(numbers: dict[tuple[int, date, str], set[str]], number: int, day: date, worker: str) -> set[str]:
    """Postacie numeru ``number`` z dnia ``day`` we Wpisach raportu Wykonawcy ``worker`` w Logach, bez jego Wpisu od
    każdego Wykonawcy z tego dnia, a bez Wpisu z tego dnia z każdego dnia: wpis pamięci idzie za wierszem, więc może
    stać pod Wykonawcą, który nie przysłał Raportu, i pod dniem innym niż temat Raportu (Przeniesienie na inny dzień)."""

    return (
        numbers.get((number, day, worker))
        or {text for (value, found, _), texts in numbers.items() if (value, found) == (number, day) for text in texts}
        or {text for (value, _, _), texts in numbers.items() if value == number for text in texts}
    )


def _numbers(entering: LoggedReports) -> dict[tuple[int, date, str], set[str]]:
    """Numery Wpisów raportu w Logach po liczbie, dniu i Wykonawcy: pamięć wpisów ma w Logach numer tylko jako liczbę,
    a ma tylko zlecenia z Wpisem w tym kliknięciu, więc numer z zerami na początku jest w jego Wpisie."""

    numbers: dict[tuple[int, date, str], set[str]] = {}
    for mail in entering.mails:
        if isinstance(mail, LoggedReportMail):
            for entry in mail.entries:
                if _digits(entry.number):
                    numbers.setdefault((int(entry.number), mail.day, mail.worker), set()).add(entry.number)
    return numbers


def _saved(entering: LoggedReports) -> SavedState:
    numbers = _numbers(entering)

    def key(logged: LoggedOwnEntry) -> OrderKey:
        [number] = _texts(numbers, logged.number, logged.day, logged.worker)
        return OrderKey(OrderNumber(number), logged.day, Login(logged.worker))

    def number(logged: LoggedOwnMove) -> OrderNumber:
        """Numer zlecenia Przeniesienia ``logged``. 0123 i 123 to dwa zlecenia, a Logi niosą numer pamięci tylko jako
        liczbę, więc jedyna postać spod Wpisu Wykonawcy i dnia Przeniesienia odchodzi z nim i następne Przeniesienie tej
        liczby nie weźmie jej spod tego Wpisu. Postać spod Wpisu innego Wykonawcy albo dnia nie odchodzi: następne
        Przeniesienie może dostać tę samą."""

        found = _texts(numbers, logged.number, logged.day, logged.worker)
        return OrderNumber(found.pop() if len(found) == 1 else str(logged.number))

    entries = frozenset(OwnEntry(key(logged), logged.column, logged.value) for logged in entering.memory_before)
    kept = frozenset(Kept(key(logged), logged.column, logged.value) for logged in entering.kept)
    moves = frozenset(
        OwnMove(
            number(logged),
            logged.day,
            Login(logged.worker),
            logged.origin_day,
            Login(logged.origin_worker),
            logged.origin_name,
            logged.since,
            logged.overridden,
            logged.added,
        )
        for logged in entering.moves_before
    )
    return SavedState(entering.rollout_before, OwnEntries(entries, moves), kept)


def _orderless(entering: LoggedReports) -> list[ReplayedOrderless]:
    numbers = _numbers(entering)
    replayed: list[ReplayedOrderless] = []
    for logged in entering.orderless:
        number = logged.number
        texts = {text for (value, _, _), found in numbers.items() if value == number for text in found}
        zero = sorted(text for text in texts if text.startswith("0"))
        replayed.append(ReplayedOrderless(logged.sheet, zero[0] if zero else number, logged.day))
    return replayed
