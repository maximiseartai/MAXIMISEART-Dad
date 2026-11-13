"""Schemat Logów Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Logi powstają z tych samych faktów co karta Uruchomienia (``logs_of_run.logs_of``): wynik, Komunikaty z kodami,
podsumowanie, etapy, ślad wywołań Zatrzymania, a z ostatniego snapshotu projekcji postępu Przetworzenia Szablonów
pracownika i liczba problemów. Środowisko to system, Python i pliki procesu z Diagnozy z rozmiarem i atrybutem OneDrive.
Dodatki Logów procesu (``ProcessLogs``) daje jego wpis w katalogu procesów: z podsumowania silnika Przebiegu rozliczeń
liczba wyczyszczonych Ilości tylko dla INEA, której karta nie pokazuje (ADR 0018), a z podsumowania Uporządkowania
INTERMAX jego Wpisy urządzenia i czynności INTERMAX (ADR 0019): wiersze i operatorzy, bez innej treści wierszy, a z
Wpisania raportów Wpisy, problemy i zmiany komórek (``LoggedReports``, ADR 0028) bez adresów, tematów i treści maili. Z
podsumowania Wyceny w efenix jest ślad każdego zlecenia (``LoggedOrder``) z działaniami okna efenix i odczytem strony po
każdym (``LoggedStep``, #843), bez numeru zlecenia i bez danych adresowych z pliku i z efenix.
Zatrzymanie okna efenix (``efenix_pricing.PricingStopped``) daje ślad zleceń sprzed niego i ``LoggedWindowStop``:
przyczynę techniczną z zamkniętej listy, wiersz i miejsce zlecenia w przebiegu oraz jego działania aż do tego, które się
nie udało; a każde Zatrzymanie z przyczyną w wyjątku, także dla taty, ma ślad wywołań z łańcuchem przyczyn, więc
Zatrzymanie przy starcie okna efenix nazywa drogę startu, która zawiodła, i typ jej wyjątku (#976).
Wiersze danych niesie tylko Kopia wejścia (``input_copy``, #841): każdy plik taty, który Uruchomienie przeczytało, z
odciskiem i przeczytanymi wierszami bez kolumn ``ADRES`` i numeru Orange (w Uporządkowaniu INTERMAX wklejone wiersze,
#842). Poza nią komórkę cytuje tylko Komunikat (``ZLE_SKUTECZNE``), a pliki mają tylko nazwę, nigdy pełną ścieżkę. Plik i
wysyłka biorą tylko Logi po strażniku reguły danych (``run_logs_guard``, ADR 0025). Skrypt dla maszyn nie ma działań po
wyniku, więc Logów nie tworzy.

Schemat 2 (#839) daje każdemu krokowi śladu godzinę (UTC) obok czasu trwania: etap ma chwilę rozpoczęcia i końca,
Przetworzenie Szablonu pracownika też, a działanie okna efenix chwilę rozpoczęcia, więc widać przerwy i czekanie, których
czasy trwania nie liczą. Dochodzi dziennik działań taty w Centrum (``dad_actions``) od Logów poprzedniego Uruchomienia do
końca tego, bez treści zapytań, więc bez treści Uwagi taty. Plik schematu 1 nie ma godzin ani dziennika, a te pola są
w nim ``None``.

Schemat 3 zapisuje tryb Uruchomienia, także przy starcie Uruchomienia w dzienniku działań taty, wartością ``RunMode``
(``RUN``, ``DRY-RUN``) jak rekord metryk, zamiast słowa „zapis”/„podgląd”, a fakty startu (``StartFacts``) stoją w
pliku przed resztą pól. Karta z Logów, Historia, odtworzenie i Uwaga taty czytają każdy schemat: słowo trybu z pliku
schematu 1–2 to ten sam tryb (``StoredRunMode``).

Plik leży w katalogu Logów obok dziennika Centrum (``logs_disk``), poza Gitem i OneDrive, bez rotacji. Urwana Wycena w
efenix (#845) ma Logi z dziennika Wyceny (``RunLog.interrupted``): sposób zakończenia ``interrupted``, bez wyniku, czasu,
etapów i Komunikatów, ze śladem zleceń skończonych przed zgaśnięciem Centrum i ze zleceniem zaczętym bez wyniku
(``LoggedInterruption``); ich koniec to ostatni wpis dziennika, bo chwili zgaśnięcia nikt nie zapisał.

Moduł zależy tylko od kontraktu i typów silnika, które Logi niosą, a nie od gospodarza Uruchomień ani Diagnozy: Logi z
nich składa ``logs_of_run`` (``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_actions import ButtonPressed, DadActions, StoredRunMode
from rozliczenia.domain import ProgressPhase, WorkerStatus
from rozliczenia.efenix_checks import ListedRead
from rozliczenia.efenix_pricing import OrderKind, OrderResult, PricingStopped, PricingSummary, StoppedOrder
from rozliczenia.efenix_window import (
    BrowserFailure,
    Closed,
    ElementCount,
    HttpStatus,
    LoginSign,
    OtherShape,
    PagePart,
    StatusChangeBlocked,
    WindowAction,
    WindowCause,
)
from rozliczenia.efenix_trace import TraceStep
from rozliczenia.input_copy import CellValue, CopiedFile, CopiedSheet, Typed, TypedKind
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.message import Message, SettingsSection
from rozliczenia.process_run import RunResult, StopEnding
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import EnteringFacts
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

RUN_LOGS_DIRECTORY: Final = "uruchomienia"
SCHEMA_VERSION: Final = 3

LoggedEnding = Literal["finished", StopEnding, "interrupted"]
"""Sposób zakończenia w Logach: jak na karcie (``runs.Ending``) albo ``interrupted``, Urwane Uruchomienie, którego Logi
zamknął start Centrum z dziennika Wyceny w efenix."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StartFacts(_Record):
    """Bezpieczne fakty startu jednego Uruchomienia, jedyny ich kształt: nagłówek Logów (``RunLog``), plik ostatniego
    startu i pierwsza linia dziennika Wyceny w efenix (``logs_disk``) to te pola z polami swojego pliku."""

    run_id: str
    process: common_contract.ProcessKey
    mode: StoredRunMode
    period: str
    started_at: datetime
    pricing: runs_contract.Pricing | None = None
    """Tryb Wyceny w efenix (ADR 0027). ``None``: inne procesy i Logi sprzed trybów, w których Wycena biegła bez
    Przekazania."""

    @classmethod
    def of_run(cls, info: runs_contract.RunInfo, started_at: datetime) -> StartFacts:
        return cls(
            run_id=info.id,
            process=info.process,
            mode=info.mode,
            period=info.period,
            started_at=started_at,
            pricing=info.pricing,
        )

    @property
    def start(self) -> StartFacts:
        """Same fakty startu, bez pól pliku, który je niesie; z nich ``logs_disk.name_of`` daje nazwę pliku Logów."""

        return StartFacts.model_validate({name: getattr(self, name) for name in StartFacts.model_fields})


class _ReadValues:
    """Znacznik pola Logów (``Annotated``), które niesie wartości przeczytane z komórek pliku taty albo ze strony efenix,
    także liczby: strażnik (``guard_logs``) maskuje w nim liczbę z zakazaną wartością albo telefonem jak tekst. Każda inna
    liczba Logów (numer wiersza, rozmiar, czas, liczba zleceń) to liczba, którą policzyło narzędzie."""


READ_VALUES: Final = _ReadValues()

LoggedQuantity = int | str
"""Ilość pozycji przy zleceniu Wyceny w efenix; tekst to maska strażnika (``[numer Orange]``) zamiast liczby."""


class LoggedMessage(_Record):
    """Komunikat karty w trzech częściach z kodem; ``stop`` to Zatrzymanie, ``warning`` ostrzeżenie wyniku.
    ``setting``: sekcja Ustawień Centrum z linkiem na karcie; bez niej pola nie ma w pliku, jak w Logach sprzed niej."""

    kind: Literal["stop", "warning"]
    code: str
    what: str
    where: str
    action: str
    setting: SettingsSection | None = Field(default=None, exclude_if=lambda setting: setting is None)

    @classmethod
    def of(cls, kind: Literal["stop", "warning"], message: Message) -> LoggedMessage:
        return cls(
            kind=kind,
            code=message.code,
            what=message.what,
            where=message.where,
            action=message.action,
            setting=message.setting,
        )

    def shown(self) -> common_contract.Message:
        """Komunikat karty odtworzonej z Logów, z tym samym linkiem do Ustawień co na karcie na żywo."""

        return common_contract.Message(what=self.what, where=self.where, action=self.action, setting=self.setting)


class LoggedPhase(_Record):
    """Etap Uruchomienia jak na karcie (stan i czas bez czekania na tatę) z chwilami rozpoczęcia i końca (UTC).

    ``started_at`` ``None``: etap się nie zaczął; ``ended_at`` ``None``: nie skończył się (Zatrzymanie w innym etapie,
    odłączony podgląd postępu). Oba ``None`` także w plikach schematu 1.
    """

    phase: runs_contract.PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @classmethod
    def all_of(cls, phases: Sequence[runs_contract.PhaseProgress], snapshot: ProgressSnapshot | None) -> list[LoggedPhase]:
        def moment(moments: Mapping[ProgressPhase, datetime] | None, phase: runs_contract.PhaseName) -> datetime | None:
            return None if moments is None else moments.get(ProgressPhase(phase))

        started = None if snapshot is None else snapshot.phase_started_at
        ended = None if snapshot is None else snapshot.phase_ended_at
        return [
            cls(
                phase=phase.phase,
                state=phase.state,
                duration_ms=phase.duration_ms,
                started_at=moment(started, phase.phase),
                ended_at=moment(ended, phase.phase),
            )
            for phase in phases
        ]

    @property
    def progress(self) -> runs_contract.PhaseProgress:
        """Etap tak, jak go pokazuje karta Uruchomienia."""

        return runs_contract.PhaseProgress(phase=self.phase, state=self.state, duration_ms=self.duration_ms)


class LoggedTemplate(_Record):
    """Przetworzenie Szablonu pracownika; chwile rozpoczęcia i końca w UTC, ``None`` w plikach schematu 1."""

    wykonawca: str
    outcome: WorkerStatus | Literal["failed"]
    rows: int
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None


class LoggedFile(_Record):
    """Plik taty procesu: sama nazwa, rozmiar i atrybut OneDrive „tylko online”.

    ``size`` ``None``: pliku nie ma albo nie da się go odczytać. ``online_only`` ``None``: poza Windows albo bez pliku.
    """

    name: str
    size: int | None
    online_only: bool | None


class Environment(_Record):
    system: str
    python: str
    files: list[LoggedFile] | None
    """``None``: plików procesu nie dało się wyliczyć (np. Folder okresu niedostępny)."""


class Explanation(_Record):
    """Wyjaśnienie Diagnozy: Komunikat w trzech częściach z kodem, jak w Zgłoszeniu."""

    code: str
    what: str
    where: str
    action: str


class LoggedCheck(_Record):
    """Sprawdzenie Diagnozy jak na liście „Sprawdzono” taty; ``code`` to kod Komunikatu sprawdzenia, które nie przeszło."""

    label: str
    state: diagnosis_contract.CheckState
    detail: str
    code: str | None

    @property
    def result(self) -> tuple[str, diagnosis_contract.CheckState, str | None, str | None]:
        """Sprawdzenie bez okoliczności: ``detail`` sprawdzenia, które przeszło, to fakt chwili (liczba wpisów dziennika
        rośnie z każdą Diagnozą), a przy ``failed`` i ``not_checked`` sam wynik: treść Komunikatu albo powód."""

        return self.label, self.state, self.code, None if self.state == "passed" else self.detail


class LoggedDiagnosis(_Record):
    """Ostatnia Diagnoza Uruchomienia; sprawdzenia po kolei."""

    diagnosed_at: datetime
    explanation: Explanation
    next_action: diagnosis_contract.DiagnosisNextAction
    checks: list[LoggedCheck]

    def same_result(self, other: LoggedDiagnosis) -> bool:
        """Te same Logi Diagnozy bez okoliczności: bez chwili i z każdym sprawdzeniem jako ``LoggedCheck.result``."""

        def result(diagnosis: LoggedDiagnosis) -> object:
            return diagnosis.explanation, diagnosis.next_action, [check.result for check in diagnosis.checks]

        return result(self) == result(other)


class LoggedWholesale(_Record):
    """Instalacja hurt bez Wpisu: wiersz INTERMAX i nazwa operatora z aplikacji (``None``: puste ``CZYNNOŚCI``)."""

    row: int
    operator: str | None


class LoggedEntries(_Record):
    """Wpisy urządzenia i czynności INTERMAX Uporządkowania: operator z reguły taty → wiersze INTERMAX z Wpisem
    oraz instalacje hurt bez Wpisu (operator spoza reguły)."""

    rows: dict[str, list[int]]
    without_entry: list[LoggedWholesale]

    @classmethod
    def of(cls, summary: OrderingSummary) -> LoggedEntries:
        return cls(
            rows={operator: list(rows) for operator, rows in summary.entries.items()},
            without_entry=[LoggedWholesale(row=row, operator=operator) for row, operator in summary.without_entry],
        )


class LoggedResult(_Record):
    """Wiersz listy zleceń efenix po szukaniu (``efenix_checks.ListedRead``): czy ``Numer dokumentu`` to ``NUMER ZL.`` z
    pliku, status i login realizatora jak na liście oraz nazwy części adresu (``efenix_address.AddressPart``), którymi
    ``Dane adresowe`` różnią się od ``ADRES``, bez wartości; pusta lista to ten sam adres."""

    same_number: bool
    status: str
    realizator: str | None
    address: list[str]

    @classmethod
    def of(cls, read: ListedRead) -> LoggedResult:
        return cls(
            same_number=read.same_number,
            status=read.status,
            realizator=read.realizator,
            address=[part.value for part in read.address],
        )


class LoggedStep(_Record):
    """Działanie okna efenix przy zleceniu (``efenix_trace.TraceStep``): chwila rozpoczęcia (UTC; ``None`` w plikach
    schematu 1), czas i odczyt strony efenix po nim.

    ``results``: każdy wiersz listy po szukaniu, ``status`` i ``realizator``: wiersz listy, którego stronę zlecenia okno
    otworzyło, ``refusal``: nazwa odmowy efenix przy Przekazaniu do akceptacji (``efenix_window.ForwardRefusal``, bez
    tekstu okna informacji); ``None`` przy innych działaniach i w plikach sprzed tych pól.
    """

    action: WindowAction
    started_at: datetime | None = None
    duration_ms: int
    found: int | None
    execution_date: date | None
    amount: Decimal | None
    quantities: Annotated[dict[str, LoggedQuantity] | None, READ_VALUES]
    position: str | None
    quantity: Annotated[LoggedQuantity | None, READ_VALUES]
    accepted: bool | None
    results: list[LoggedResult] | None = None
    status: str | None = None
    realizator: str | None = None
    refusal: str | None = None

    @classmethod
    def of(cls, step: TraceStep) -> LoggedStep:
        return cls(
            action=step.action,
            started_at=step.started_at,
            duration_ms=step.duration_ms,
            found=step.found,
            execution_date=step.execution_date,
            amount=step.amount,
            quantities=None if step.quantities is None else dict(step.quantities),
            position=step.position,
            quantity=step.quantity,
            accepted=step.accepted,
            results=None if step.results is None else [LoggedResult.of(read) for read in step.results],
            status=step.status,
            realizator=step.realizator,
            refusal=None if step.refusal is None else step.refusal.name,
        )


class LoggedOrder(_Record):
    """Ślad zlecenia Wyceny w efenix: wiersz Pliku zbiorczego, wynik (``OrderKind``, w pliku jego klucz) z kodem
    Komunikatu (``None`` przy wyniku, który nie zostaje tacie), ilości z pliku po kodach pozycji (``None``, gdy nie dało
    się ich przepisać), ``Kwota`` (AU) i działania okna."""

    row: int
    outcome: OrderKind
    code: str | None
    file: Annotated[dict[str, LoggedQuantity] | None, READ_VALUES]
    file_amount: Decimal
    steps: list[LoggedStep]

    @classmethod
    def all_of(cls, summary: PricingSummary) -> list[LoggedOrder]:
        return [cls.of(result) for result in summary.results]

    @classmethod
    def of(cls, result: OrderResult) -> LoggedOrder:
        return cls(
            row=result.order.row,
            outcome=result.kind,
            code=None if result.message is None else result.message.code,
            file=None if result.file is None else dict(result.file),
            file_amount=result.order.amount,
            steps=[LoggedStep.of(step) for step in result.steps],
        )


class LoggedCause(_Record):
    """Przyczyna techniczna Zatrzymania Wyceny w efenix z zamkniętej listy (``efenix_window.WindowCause``), bez treści
    strony i wyjątku: ``part`` to część strony (nazwa ``PagePart``, ``None`` poza stronami efenix), a ``what`` przyczyna z
    listy.

    ``positions``: kod pozycji, której dotyczy budowa. ``element`` i ``count``: selektor z kodu okna i ile razy jest na
    stronie. ``status``: status HTTP strony błędu efenix. ``error_type`` i ``operation``: typ wyjątku Playwrighta i
    działanie przeglądarki (``None``: działanie bez nazwy).
    """

    part: str | None
    what: str
    positions: list[str] | None = None
    element: str | None = None
    count: int | None = None
    status: int | None = None
    error_type: str | None = None
    operation: str | None = None

    @classmethod
    def of(cls, part: PagePart | None, cause: WindowCause) -> LoggedCause:
        name = None if part is None else part.name
        match cause:
            case ElementCount(selector, count):
                return cls(part=name, what=_ELEMENT_COUNT, element=selector, count=count)
            case HttpStatus(status):
                return cls(part=name, what=_HTTP_STATUS, status=status)
            case OtherShape(shape, position):
                return cls(part=name, what=shape.value, positions=None if position is None else [position])
            case BrowserFailure(error_type, operation):
                return cls(
                    part=name,
                    what=_BROWSER_FAILURE,
                    error_type=error_type,
                    operation=None if operation is None else operation.value,
                )
            case LoginSign() | Closed() | StatusChangeBlocked():
                return cls(part=name, what=cause.value)
            case _:
                assert_never(cause)


_ELEMENT_COUNT: Final = "element strony nie występuje dokładnie raz"
_BROWSER_FAILURE: Final = "błąd przeglądarki w działaniu okna"
_HTTP_STATUS: Final = "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno"


class LoggedWindowStop(_Record):
    """Zatrzymanie okna efenix w Wycenie w efenix: przyczyna techniczna i zlecenie, przy którym Wycena stanęła.

    ``row``: wiersz Pliku zbiorczego, ``order`` z ``orders``: miejsce zlecenia w przebiegu (od 1), ``steps``: udane
    działania okna przy nim, ``failed``: działanie, które się nie udało, z rodzajem i czasem. Przy Zatrzymaniu przed
    pierwszym zleceniem (otwarcie okna, logowanie) ``row``, ``order``, ``orders`` i ``failed`` są ``None``, a ``steps``
    puste.
    """

    cause: LoggedCause
    row: int | None
    order: int | None
    orders: int | None
    steps: list[LoggedStep]
    failed: LoggedStep | None

    @classmethod
    def of(cls, stopped: PricingStopped) -> LoggedWindowStop:
        at: StoppedOrder | None = stopped.stopped_at
        cause = LoggedCause.of(stopped.part, stopped.cause)
        if at is None:
            return cls(cause=cause, row=None, order=None, orders=None, steps=[], failed=None)
        return cls(
            cause=cause,
            row=at.row,
            order=at.place,
            orders=at.total,
            steps=[LoggedStep.of(step) for step in at.steps],
            failed=None if at.failed is None else LoggedStep.of(at.failed),
        )


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


class ProcessLogs(_Record):
    """Dodatki Logów jednego procesu: wpis procesu w katalogu daje je z podsumowania silnika i faktów Zatrzymania
    (``ProcessKind.logs``), a plik ma je jako pola ``RunLog`` o tych samych nazwach. Proces bez dodatków ma wszystkie
    ``None``."""

    inea_only_cleared: dict[str, int] | None = None
    intermax_entries: LoggedEntries | None = None
    efenix_orders: list[LoggedOrder] | None = None
    efenix_stop: LoggedWindowStop | None = None
    report_entering: LoggedReports | None = None


class LoggedInterruption(_Record):
    """Urwana Wycena w efenix z dziennika: zlecenie zaczęte bez wyniku i wpisy dziennika, których nie dało się odczytać.

    ``row`` (wiersz Pliku zbiorczego), ``place`` i ``total`` (miejsce w przebiegu, od 1): zlecenie, w którego trakcie Centrum
    zgasło, więc jego zmiany w efenix mogą być niepełne; ``None``, gdy zgasło między zleceniami. ``omitted``: wpisy
    dziennika, których nie dało się odczytać (np. wpis urwany zgaśnięciem w trakcie zapisu).
    """

    row: int | None
    place: int | None
    total: int | None
    omitted: int


class LoggedTyped(_Record):
    """Wartość komórki, której JSON nie odróżnia od tekstu (``input_copy.Typed``): rodzaj i zapis."""

    type: TypedKind
    text: str


LoggedCell = bool | int | float | str | LoggedTyped
"""Wartość niepustej komórki w Kopii wejścia."""


def _cell(value: CellValue) -> LoggedCell:
    return LoggedTyped(type=value.kind, text=value.text) if isinstance(value, Typed) else value


class LoggedRow(_Record):
    """Przeczytany wiersz: numer w arkuszu i niepuste komórki po literze kolumny."""

    row: int
    cells: Annotated[dict[str, LoggedCell], READ_VALUES]


class LoggedSheet(_Record):
    """Przeczytany arkusz: wiersz nagłówka, nagłówki po literze kolumny (bez zakazanych kolumn), wiersze i puste wiersze
    z odczytanego zakresu, które proces liczy (Rejestr zleceń).

    Fakty wklejenia INTERMAX (``input_copy.PasteFacts``) poza wierszami ze śladem przesunięcia, które idą do uwag
    (``RunLog.input_copy_notes``), stoją płasko w arkuszu. ``shifted_row``: przesunięty pierwszy wiersz wklejenia
    INTERMAX, którego komórki Uporządkowanie czyta w pliku dwie kolumny na lewo od nagłówka, a tu stoją pod nim; ``None``:
    bez niego i pliki sprzed #842. ``uncertain_rows``: wiersze wklejenia bez pewnego położenia, które mają tylko komórki
    dozwolone w każdym ich możliwym położeniu. ``last_ordered_row`` i ``yellow_row``: ostatni uporządkowany i żółty
    wiersz nad wklejeniem INTERMAX, od których Planowanie liczy wiersz dnia, bez treści; ``None``: bez takiego wiersza,
    inne pliki i pliki sprzed #847.
    """

    sheet: str
    header_row: int
    columns: dict[str, str]
    rows: list[LoggedRow]
    empty_rows: list[int]
    shifted_row: int | None = None
    uncertain_rows: list[int] = []
    last_ordered_row: int | None = None
    yellow_row: int | None = None

    @classmethod
    def of(cls, sheet: CopiedSheet) -> LoggedSheet:
        paste = sheet.paste
        return cls(
            sheet=sheet.name,
            header_row=sheet.header_row,
            columns=dict(sheet.columns),
            rows=[
                LoggedRow(row=row.number, cells={letter: _cell(value) for letter, value in row.cells.items()})
                for row in sheet.rows
            ],
            empty_rows=list(sheet.empty_rows),
            shifted_row=paste.shifted_row,
            uncertain_rows=list(paste.uncertain_rows),
            last_ordered_row=paste.last_ordered_row,
            yellow_row=paste.yellow_row,
        )


class LoggedFingerprint(_Record):
    """Odcisk pliku: rozmiar i skrót SHA-256 przeczytanych bajtów, chwila zmiany pliku tuż przed odczytem (UTC; ``None``,
    gdy system jej nie oddał)."""

    size: int
    modified_at: datetime | None
    sha256: str


class LoggedInputFile(_Record):
    """Plik taty w Kopii wejścia (``input_copy``): sama nazwa, odcisk i przeczytane arkusze.

    ``folders``: nazwy folderu nad folderem pliku i folderu pliku (``input_copy.CopiedFile.folders``; Komunikaty
    INTERMAX pokazują tylko folder pliku); pusta lista w plikach sprzed #847.
    """

    name: str
    fingerprint: LoggedFingerprint
    sheets: list[LoggedSheet]
    folders: list[str] = []

    @classmethod
    def of(cls, copied: CopiedFile) -> LoggedInputFile:
        fingerprint = copied.fingerprint
        return cls(
            name=copied.name,
            fingerprint=LoggedFingerprint(
                size=fingerprint.size, modified_at=fingerprint.modified_at, sha256=fingerprint.sha256
            ),
            sheets=[LoggedSheet.of(sheet) for sheet in copied.sheets],
            folders=list(copied.folders),
        )


class Tool(_Record):
    wydanie: str | None
    """Numer Wydania (ADR 0014), którego tag w klonie wskazuje ``commit`` (``0.10.0``); ``None``, gdy nie da się go
    ustalić lokalnie: commit po Wydaniu, bez Gita albo bez commitu."""
    commit: str | None


class RunLog(StartFacts):
    """Logi jednego Uruchomienia procesu z Centrum; kształt tego modelu to schemat pliku JSON, a fakty startu
    (``StartFacts``) to jego nagłówek.

    ``duration_ms`` to Czas uruchomienia bez czekania na Decyzję taty; ``started_at`` i ``ended_at`` to zegar ścienny.
    ``issue_count``, ``templates`` i ``duration_ms`` są puste tylko wtedy, gdy sam rdzeń (``run_process``) rzucił wyjątek,
    albo w Logach Urwanego Uruchomienia (``ending`` ``interrupted``), które nie mają też wyniku (``result`` ``None``).
    Centrum zapisuje schemat 3, a czyta też pliki schematu 1 (bez godzin kroków i dziennika działań taty) i 2 (tryb
    i tryb przycisków startu w dzienniku działań taty jako słowo „podgląd”/„zapis”, ``StoredRunMode``), a taki plik
    zapisuje z powrotem w jego schemacie (``_in_own_schema``).
    """

    schema_version: Literal[1, 2, 3]
    ended_at: datetime
    duration_ms: int | None
    tool: Tool
    result: RunResult | None
    ending: LoggedEnding
    stop_kind: runs_contract.StopKind | None
    issue_count: int | None
    messages: list[LoggedMessage]
    technical_notes: list[str]
    summary: runs_contract.RunSummary | None
    phases: list[LoggedPhase]
    templates: list[LoggedTemplate]
    inea_only_cleared: dict[str, int] | None = None
    """Ilości tylko dla INEA (ADR 0018): litera kolumny → liczba komórek z wartością, które Przebieg rozliczeń zostawił
    (w podglądzie: zostawiłby) puste w Rozliczeniach pracownika. ``None``: Przygotowanie, Przebieg bez podsumowania
    i pliki sprzed tego pola."""
    intermax_entries: LoggedEntries | None = None
    """Wpisy urządzenia i czynności INTERMAX (ADR 0019). ``None``: inne procesy, Uporządkowanie bez podsumowania
    i pliki sprzed tego pola."""
    efenix_orders: list[LoggedOrder] | None = None
    """Ślad każdego zlecenia Wyceny w efenix po kolei, a po Zatrzymaniu z ``efenix_stop`` każdego zlecenia sprzed niego.
    ``None``: inne procesy, Wycena w efenix bez podsumowania i bez Zatrzymania okna oraz pliki sprzed tego pola."""
    efenix_stop: LoggedWindowStop | None = None
    """Zatrzymanie okna efenix z przyczyną techniczną. ``None``: inne procesy, Wycena w efenix bez takiego Zatrzymania i
    pliki sprzed tego pola."""
    report_entering: LoggedReports | None = None
    """Wpisanie raportów (``LoggedReports``). ``None``: inne procesy, Wpisanie raportów zatrzymane przed rdzeniem raportów
    i pliki sprzed tego pola."""
    environment: Environment
    trace: CallTrace | None
    diagnosis: LoggedDiagnosis | None
    """Ostatnia Diagnoza tego Uruchomienia z nowym wynikiem; ``None``, dopóki tata jej nie uruchomił (pliki schematu 1 sprzed niej też)."""
    dad_actions: DadActions | None = None
    """Działania taty w Centrum od Logów poprzedniego Uruchomienia do końca tego (``dad_actions``). ``None``: pliki
    schematu 1."""
    interruption: LoggedInterruption | None = None
    """Urwana Wycena w efenix (``ending`` ``interrupted``); ``None`` w każdych innych Logach."""
    input_copy: list[LoggedInputFile] | None = None
    """Kopia wejścia (``input_copy``, #841): pliki taty, które Uruchomienie przeczytało, w kolejności odczytu, każdy z
    odciskiem i przeczytanymi Wierszami danych po regule danych. Pusta lista: Uruchomienie skończyło się przed odczytem.
    ``None``: Logi Urwanego Uruchomienia, pliki sprzed tego pola i Uporządkowania INTERMAX sprzed #842."""
    input_copy_notes: list[str] = []
    """Uwagi techniczne o Kopii wejścia, osobno od ``technical_notes``, które pokazuje karta Uruchomienia z Logów: wiersz
    ze śladem przesunięcia, który łamie fakt domeny (``logs_of_run.logs_of``), i uwagi strażnika reguły danych o
    wartościach zamaskowanych w Kopii (``guard_logs``)."""

    @model_serializer(mode="wrap")
    def _in_own_schema(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Logi w ich schemacie: plik sprzed schematu 3, który start Centrum zapisuje z powrotem przy dzienniku Wyceny
        (``comment_versions.close``), ma dalej tryb i tryb przycisków startu słowem, bo odtworzenie czyta go kodem jego
        commitu (``tool.commit``). Zrzut w trybie Pythona też ma słowo: ``StoredRunMode`` czyta je z powrotem."""

        dumped: dict[str, Any] = handler(self)
        if self.schema_version == SCHEMA_VERSION:
            return dumped
        dumped["mode"] = self.mode.word
        if self.dad_actions is not None:
            for action, entry in zip(self.dad_actions.entries, dumped["dad_actions"]["entries"], strict=True):
                if isinstance(action, ButtonPressed) and action.mode is not None:
                    entry["mode"] = action.mode.word
        return dumped

    @classmethod
    def interrupted(
        cls,
        started: StartFacts,
        *,
        ended_at: datetime,
        orders: Sequence[LoggedOrder],
        interruption: LoggedInterruption,
        tool: Tool,
        environment: Environment,
        dad_actions: DadActions,
    ) -> RunLog:
        """Logi Urwanego Uruchomienia ``started`` z dziennika Wyceny w efenix: zlecenia skończone przed zgaśnięciem Centrum
        (``orders``) i ``interruption``; ``ended_at`` to ostatni wpis dziennika."""

        return cls(
            **dict(started.start),
            schema_version=SCHEMA_VERSION,
            ended_at=ended_at,
            duration_ms=None,
            tool=tool,
            result=None,
            ending="interrupted",
            stop_kind=None,
            issue_count=None,
            messages=[],
            technical_notes=[],
            summary=None,
            phases=[],
            templates=[],
            efenix_orders=list(orders),
            environment=environment,
            trace=None,
            diagnosis=None,
            dad_actions=dad_actions,
            interruption=interruption,
        )

    @property
    def text(self) -> str:
        """Treść pliku Logów; te same znaki idą do Skrzynki Zgłoszeń."""

        return self.model_dump_json(indent=2) + "\n"


assert all(RunLog.model_fields[name].annotation == field.annotation for name, field in ProcessLogs.model_fields.items()), (
    "dodatki Logów procesu to pola RunLog tych samych typów"
)

