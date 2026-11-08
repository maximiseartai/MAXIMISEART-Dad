"""Schemat Logów Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Logi powstają z tych samych faktów co karta Uruchomienia (``logs_of_run.logs_of``): wynik, Komunikaty z kodami,
podsumowanie, etapy, ślad wywołań Zatrzymania, a z ostatniego snapshotu projekcji postępu Przetworzenia Szablonów
pracownika i liczba problemów. Środowisko to system, Python i pliki procesu z Diagnozy z rozmiarem i atrybutem OneDrive.
Z podsumowania silnika Przebiegu rozliczeń jest też liczba wyczyszczonych Ilości tylko dla INEA, której karta nie
pokazuje (ADR 0018), a z podsumowania Uporządkowania INTERMAX jego Wpisy urządzenia i czynności INTERMAX (ADR 0019):
wiersze i operatorzy, bez innej treści wierszy. Z podsumowania Wyceny w efenix jest ślad każdego zlecenia (``LoggedOrder``):
wiersz Pliku zbiorczego, wynik z kodem Komunikatu, ilości z pliku po kodach pozycji, ``Kwota`` (AU) i działania okna efenix
z czasami i odczytem strony po każdym (``LoggedStep``, #843): przy szukaniu każdy wiersz listy ze statusem, loginem
realizatora, zgodnością numeru i nazwami części adresu, którymi różni się od ``ADRES`` (``LoggedResult``), przy otwarciu
zlecenia jego status i realizator, a ze strony zlecenia data wykonania, kwota i ilości wszystkich pozycji. Bez numeru
zlecenia i bez danych adresowych z pliku i z efenix.
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
końca tego, bez treści zapytań, więc bez treści Uwagi taty. Karta z Logów i Historia czytają oba schematy: plik schematu 1
nie ma godzin ani dziennika, a te pola są w nim ``None``.

Plik leży w katalogu Logów obok dziennika Centrum (``logs_disk``), poza Gitem i OneDrive, bez rotacji. Urwana Wycena w
efenix (#845) ma Logi z dziennika Wyceny (``RunLog.interrupted``): sposób zakończenia ``interrupted``, bez wyniku, czasu,
etapów i Komunikatów, ze śladem zleceń skończonych przed zgaśnięciem Centrum i ze zleceniem zaczętym bez wyniku
(``LoggedInterruption``); ich koniec to ostatni wpis dziennika, bo chwili zgaśnięcia nikt nie zapisał.

Moduł zależy tylko od kontraktu i typów silnika, które Logi niosą, a nie od gospodarza Uruchomień ani Diagnozy: Logi z
nich składa ``logs_of_run`` (``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract
from rozliczenia.centrum.dad_actions import DadActions
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
from rozliczenia.message import Message
from rozliczenia.process_run import StopEnding
from rozliczenia.progress import ProgressSnapshot

RUN_LOGS_DIRECTORY: Final = "uruchomienia"

LoggedEnding = Literal["finished", StopEnding, "interrupted"]
"""Sposób zakończenia w Logach: jak na karcie (``runs.Ending``) albo ``interrupted``, Urwane Uruchomienie, którego Logi
zamknął start Centrum z dziennika Wyceny w efenix."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _ReadValues:
    """Znacznik pola Logów (``Annotated``), które niesie wartości przeczytane z komórek pliku taty albo ze strony efenix,
    także liczby: strażnik (``guard_logs``) maskuje w nim liczbę z zakazaną wartością albo telefonem jak tekst. Każda inna
    liczba Logów (numer wiersza, rozmiar, czas, liczba zleceń) to liczba, którą policzyło narzędzie."""


READ_VALUES: Final = _ReadValues()

LoggedQuantity = int | str
"""Ilość pozycji przy zleceniu Wyceny w efenix; tekst to maska strażnika (``[numer Orange]``) zamiast liczby."""


class LoggedMessage(_Record):
    """Komunikat karty w trzech częściach z kodem; ``stop`` to Zatrzymanie, ``warning`` ostrzeżenie wyniku."""

    kind: Literal["stop", "warning"]
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, kind: Literal["stop", "warning"], message: Message) -> LoggedMessage:
        return cls(kind=kind, code=message.code, what=message.what, where=message.where, action=message.action)


class LoggedPhase(_Record):
    """Etap Uruchomienia jak na karcie (stan i czas bez czekania na tatę) z chwilami rozpoczęcia i końca (UTC).

    ``started_at`` ``None``: etap się nie zaczął; ``ended_at`` ``None``: nie skończył się (Zatrzymanie w innym etapie,
    odłączony podgląd postępu). Oba ``None`` także w plikach schematu 1.
    """

    phase: contract.PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @classmethod
    def all_of(cls, phases: Sequence[contract.PhaseProgress], snapshot: ProgressSnapshot | None) -> list[LoggedPhase]:
        def moment(moments: Mapping[ProgressPhase, datetime] | None, phase: contract.PhaseName) -> datetime | None:
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
    def progress(self) -> contract.PhaseProgress:
        """Etap tak, jak go pokazuje karta Uruchomienia."""

        return contract.PhaseProgress(phase=self.phase, state=self.state, duration_ms=self.duration_ms)


class LoggedTemplate(_Record):
    """Przetworzenie Szablonu pracownika: Wykonawca, wynik, Wiersze danych, czas oraz chwile rozpoczęcia i końca (UTC;
    ``None`` w plikach schematu 1)."""

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
    state: contract.CheckState
    detail: str
    code: str | None

    @property
    def result(self) -> tuple[str, contract.CheckState, str | None, str | None]:
        """Sprawdzenie bez okoliczności: ``detail`` sprawdzenia, które przeszło, to fakt chwili (liczba wpisów dziennika
        rośnie z każdą Diagnozą), a przy ``failed`` i ``not_checked`` sam wynik: treść Komunikatu albo powód."""

        return self.label, self.state, self.code, None if self.state == "passed" else self.detail


class LoggedDiagnosis(_Record):
    """Ostatnia Diagnoza Uruchomienia: wyjaśnienie z kodem, co tata robi dalej i każde sprawdzenie po kolei."""

    diagnosed_at: datetime
    explanation: Explanation
    next_action: contract.DiagnosisNextAction
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
        """Ślad każdego zlecenia po kolei."""

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

    ``shifted_row``: przesunięty pierwszy wiersz wklejenia INTERMAX, którego komórki Uporządkowanie czyta w pliku dwie
    kolumny na lewo od nagłówka, a tu stoją pod nim (``input_copy.CopiedSheet.shifted_row``); ``None``: bez niego i
    pliki sprzed #842. ``uncertain_rows``: wiersze wklejenia bez pewnego położenia, które mają tylko komórki dozwolone
    w każdym ich możliwym położeniu (``input_copy.CopiedSheet.uncertain_rows``). ``last_ordered_row`` i ``yellow_row``:
    ostatni uporządkowany i żółty wiersz nad wklejeniem INTERMAX, od których Planowanie liczy wiersz dnia, bez treści
    (``input_copy.CopiedSheet.last_ordered_row``); ``None``: bez takiego wiersza, inne pliki i pliki sprzed #847.
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
        return cls(
            sheet=sheet.name,
            header_row=sheet.header_row,
            columns=dict(sheet.columns),
            rows=[
                LoggedRow(row=row.number, cells={letter: _cell(value) for letter, value in row.cells.items()})
                for row in sheet.rows
            ],
            empty_rows=list(sheet.empty_rows),
            shifted_row=sheet.shifted_row,
            uncertain_rows=list(sheet.uncertain_rows),
            last_ordered_row=sheet.last_ordered_row,
            yellow_row=sheet.yellow_row,
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


class RunLog(_Record):
    """Logi jednego Uruchomienia procesu z Centrum; kształt tego modelu to schemat pliku JSON.

    ``duration_ms`` to Czas uruchomienia bez czekania na Decyzję taty; ``started_at`` i ``ended_at`` to zegar ścienny.
    ``issue_count``, ``templates`` i ``duration_ms`` są puste tylko wtedy, gdy sam rdzeń (``run_process``) rzucił wyjątek,
    albo w Logach Urwanego Uruchomienia (``ending`` ``interrupted``), które nie mają też wyniku (``result`` ``None``).
    Centrum zapisuje schemat 2, a czyta też pliki schematu 1 (bez godzin kroków i dziennika działań taty).
    """

    schema_version: Literal[1, 2]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    pricing: contract.Pricing | None = None
    """Tryb Wyceny w efenix (ADR 0027). ``None``: inne procesy i Logi sprzed trybów, w których Wycena biegła bez
    Przekazania."""
    period: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int | None
    tool: Tool
    result: contract.RunResult | None
    ending: LoggedEnding
    stop_kind: contract.StopKind | None
    issue_count: int | None
    messages: list[LoggedMessage]
    technical_notes: list[str]
    summary: contract.RunSummary | None
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
            schema_version=2,
            run_id=started.run_id,
            process=started.process,
            mode=started.mode,
            pricing=started.pricing,
            period=started.period,
            started_at=started.started_at,
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
    def start(self) -> StartFacts:
        """Bezpieczne fakty startu tych Logów, z których ``logs_disk.name_of`` daje nazwę ich pliku."""

        return StartFacts(
            run_id=self.run_id,
            process=self.process,
            mode=self.mode,
            period=self.period,
            started_at=self.started_at,
            pricing=self.pricing,
        )

    @property
    def text(self) -> str:
        """Treść pliku Logów; te same znaki idą do Skrzynki Zgłoszeń."""

        return self.model_dump_json(indent=2) + "\n"


@dataclass(frozen=True)
class StartFacts:
    """Bezpieczne fakty startu jednego Uruchomienia: te same co nagłówek jego Logów (``RunLog.start``), plik ostatniego
    startu (``logs_disk``) i pierwsza linia dziennika Wyceny w efenix. ``pricing``: tryb Wyceny w efenix (``None``:
    inne procesy i zapisy sprzed trybów)."""

    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime
    pricing: contract.Pricing | None = None

    @classmethod
    def of_run(cls, info: contract.RunInfo, started_at: datetime) -> StartFacts:
        """Fakty startu Uruchomienia ``info``, które Centrum startuje teraz (``RunHost.start`` → ``run_started``)."""

        mode: Literal["podgląd", "zapis"] = "podgląd" if info.dry_run else "zapis"
        return cls(
            run_id=info.id,
            process=info.process,
            mode=mode,
            period=info.period,
            started_at=started_at,
            pricing=info.pricing,
        )
