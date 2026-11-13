"""Logi Wpisania raportów (ADR 0028): pole ``report_entering`` pliku Logów Uruchomienia (``run_logs.RunLog``), czyli
Wpisy, problemy i zmiany komórek bez adresów nadawców, tematów i treści maili poza Wpisami.

``LoggedReports.of_run`` składa je z faktów Uruchomienia, które wpis procesu w katalogu dostaje przy Logach
(``ProcessKind.logs``), a ``logged_read`` czyta mail z nich z powrotem dla odtworzenia Uruchomienia z Logów. Kolejność
deklaracji pól to kolejność kluczy w pliku, a pole, którego nie mają Logi z wcześniejszych Wydań, czyta się z domyślną
(opis przy rekordzie), bo te pliki czytają karta z Logów, Historia i odtworzenie.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field

from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import EnteringFacts, EnteringSummary
from rozliczenia.worker_reports import (
    AddBar,
    ConflictingVerdicts,
    Login,
    MailId,
    MailRead,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    MoveBar,
    RefusedMove,
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


LoggedColumn = Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]
"""Kolumna INTERMAX, którą zmienia Wpisanie raportów (``report_cells.ReportColumn``)."""
LoggedVerdictFault = Literal["missing", "letter_yes", "letter_no", "word_yes", "word_no"]
LoggedSubjectFault = Literal["no_date", "other_text", "no_year", "date_form", "separator", "year_digits", "not_a_day"]


def _move_bar(bar: MoveBar) -> LoggedMoveBar:
    match bar:
        case MoveBar.NOT_ORDERED:
            return "not_ordered"
        case MoveBar.OTHER_SHEET:
            return "other_sheet"
        case MoveBar.CLOSED_TARGET:
            return "closed_target"
        case MoveBar.CLOSED_SOURCE:
            return "closed_source"
        case MoveBar.AFTER_TODAY:
            return "after_today"


def _column(column: ReportColumn) -> LoggedColumn:
    match column:
        case ReportColumn.SUCCESSFUL:
            return "SKUTECZNE"
        case ReportColumn.COMPLETED:
            return "CZYNNOŚCI ZREALIZOWANE"


def _verdict_fault(fault: VerdictFault) -> LoggedVerdictFault:
    match fault:
        case VerdictFault.MISSING:
            return "missing"
        case VerdictFault.LETTER_YES:
            return "letter_yes"
        case VerdictFault.LETTER_NO:
            return "letter_no"
        case VerdictFault.WORD_YES:
            return "word_yes"
        case VerdictFault.WORD_NO:
            return "word_no"


def _subject_fault(fault: SubjectFault) -> LoggedSubjectFault:
    match fault:
        case SubjectFault.NO_DATE:
            return "no_date"
        case SubjectFault.OTHER_TEXT:
            return "other_text"
        case SubjectFault.NO_YEAR:
            return "no_year"
        case SubjectFault.DATE_FORM:
            return "date_form"
        case SubjectFault.SEPARATOR:
            return "separator"
        case SubjectFault.YEAR_DIGITS:
            return "year_digits"
        case SubjectFault.NOT_A_DAY:
            return "not_a_day"


class LoggedReportEntry(_Record):
    """Wpis raportu: numer zlecenia z treści maila (pod strażnikiem: 9 cyfr z rzędu maskuje jak telefon), ``tak``/``nie``
    albo powód jego braku i czynności (pod strażnikiem: telefon i ulica zamaskowane)."""

    number: str
    verdict: Literal["tak", "nie"] | None
    fault: LoggedVerdictFault | None
    activities: str

    @classmethod
    def of(cls, entry: ReportEntry) -> LoggedReportEntry:
        return cls(
            number=entry.number,
            verdict=None if entry.verdict is None else entry.verdict.value,
            fault=None if entry.fault is None else _verdict_fault(entry.fault),
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
    fault: LoggedSubjectFault
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
                fault=_subject_fault(read.fault),
                numbers=sorted(read.numbers),
            )
        case ReadStranger():
            return LoggedStrangerMail(kind="stranger", mail=read.mail.digest, arrived=read.arrived, day=read.day)
        case _:
            assert_never(read)


def logged_read(mail: LoggedMail) -> MailRead:
    """Odczyt maila z jego zapisu w Logach, czyli zapis w drugą stronę: odtworzenie Uruchomienia z Logów (#1233) podaje
    go procesowi jako mail w postaci kanonicznej (``worker_reports.as_mail``)."""

    match mail:
        case LoggedReportMail():
            entries = tuple(
                ReportEntry(
                    OrderNumber(entry.number),
                    None if entry.verdict is None else Verdict(entry.verdict),
                    None if entry.fault is None else _verdict_fault_of(entry.fault),
                    entry.activities,
                )
                for entry in mail.entries
            )
            return ReadReport(MailId(mail.mail), mail.arrived, Login(mail.worker), mail.day, entries)
        case LoggedUnreadableMail():
            numbers = frozenset(OrderNumber(number) for number in mail.numbers or ())
            return ReadUnreadable(MailId(mail.mail), mail.arrived, Login(mail.worker), _subject_fault_of(mail.fault), numbers)
        case LoggedStrangerMail():
            return ReadStranger(MailId(mail.mail), mail.arrived, mail.day)
        case _:
            assert_never(mail)


def _verdict_fault_of(fault: LoggedVerdictFault) -> VerdictFault:
    return {_verdict_fault(member): member for member in VerdictFault}[fault]


def _subject_fault_of(fault: LoggedSubjectFault) -> SubjectFault:
    return {_subject_fault(member): member for member in SubjectFault}[fault]


LoggedMoveBar = Literal["not_ordered", "other_sheet", "closed_target", "closed_source", "after_today"]
LoggedAddBar = Literal["in_intermax", "before_window", "form", "mistaken_subject", "not_ordered"]


def _add_bar(bar: AddBar) -> LoggedAddBar:
    match bar:
        case AddBar.IN_INTERMAX:
            return "in_intermax"
        case AddBar.BEFORE_WINDOW:
            return "before_window"
        case AddBar.FORM:
            return "form"
        case AddBar.MISTAKEN_SUBJECT:
            return "mistaken_subject"
        case AddBar.NOT_ORDERED:
            return "not_ordered"


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
    fault: LoggedVerdictFault | None = None
    owner: str | None = None
    order_days: list[date] = []
    places: list[LoggedOrderPlace] = []
    bar: LoggedMoveBar | LoggedAddBar | None = None


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
    fault: LoggedSubjectFault


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
    column: LoggedColumn
    value: str

    @classmethod
    def of(cls, key: OrderKey, column: ReportColumn, value: str) -> LoggedOwnEntry:
        return cls(number=int(key.number), day=key.day, worker=key.worker, column=_column(column), value=value)


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
                fault=_subject_fault(problem.fault),
            )
        case UnknownSender():
            return LoggedSenderProblem(kind="unknown_sender", mail=problem.mail.digest, day=problem.day)
        case MissingVerdict():
            return LoggedOrderProblem(
                kind="missing_verdict",
                worker=problem.worker,
                day=problem.day,
                number=problem.number,
                fault=_verdict_fault(problem.fault),
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
                bar=_add_bar(problem.bar),
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
                bar=_move_bar(problem.bar),
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
    column: LoggedColumn
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
                LoggedChange(
                    sheet=change.order.sheet, row=change.order.row, column=_column(change.column), value=change.value
                )
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
