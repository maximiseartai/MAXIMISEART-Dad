"""Schemat Logów Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Logi powstają z tych samych faktów co karta Uruchomienia (``logs_of_run.logs_of``): wynik, Komunikaty z kodami,
podsumowanie, etapy, ślad wywołań Zatrzymania, a z ostatniego snapshotu projekcji postępu Przetworzenia Szablonów
pracownika i liczba problemów. Środowisko to system, Python i pliki procesu z Diagnozy z rozmiarem i atrybutem OneDrive.
Dodatki Logów procesu (``ProcessLogs``) daje jego wpis w katalogu procesów: z podsumowania silnika Przebiegu rozliczeń
liczba wyczyszczonych Ilości tylko dla INEA, której karta nie pokazuje (ADR 0018), a z podsumowania Uporządkowania
INTERMAX jego Wpisy urządzenia i czynności INTERMAX (ADR 0019): wiersze i operatorzy, bez innej treści wierszy, a z
Wpisania raportów Wpisy, problemy i zmiany komórek bez adresów, tematów i treści maili (``report_entering_logs``, ADR
0028). Z podsumowania Wyceny w efenix jest ślad każdego zlecenia (``LoggedOrder``) z działaniami okna efenix i odczytem
strony po każdym (``LoggedStep``, #843), bez numeru zlecenia i bez danych adresowych z pliku i z efenix.
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
import json
from typing import Annotated, Any, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.dad_actions import ButtonPressed, DadActions, StoredRunMode
from rozliczenia.centrum.report_entering_logs import LoggedReports
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
from rozliczenia.quantity_engine import QuantityRules, RulesProblem
from rozliczenia.quantity_rules_file import (
    dump_device_list,
    dump_quantity_rules,
    parse_device_list,
    parse_quantity_rules,
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
    ``setting``: sekcja Ustawień Centrum z linkiem na karcie; bez niej pola nie ma w pliku, jak w Logach sprzed niej.
    ``at_start``: ostrzeżenie startu (``Start.warnings``), fakt startu, który odtworzenie bierze z Logów zamiast liczyć
    go z Ustawień, których Logi nie mają; bez niego pola nie ma w pliku."""

    kind: Literal["stop", "warning"]
    code: str
    what: str
    where: str
    action: str
    setting: SettingsSection | None = Field(default=None, exclude_if=lambda setting: setting is None)
    at_start: bool = Field(default=False, exclude_if=lambda at_start: not at_start)

    @classmethod
    def of(cls, kind: Literal["stop", "warning"], message: Message, *, at_start: bool = False) -> LoggedMessage:
        return cls(
            kind=kind,
            code=message.code,
            what=message.what,
            where=message.where,
            action=message.action,
            setting=message.setting,
            at_start=at_start,
        )

    def message(self) -> Message:
        """Komunikat z Logów z tym samym kodem, treścią i sekcją Ustawień; pliku taty Logi nie mają."""

        return Message(code=self.code, what=self.what, where=self.where, action=self.action, setting=self.setting)

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


class ProcessLogs(_Record):
    """Dodatki Logów jednego procesu: wpis procesu w katalogu daje je z podsumowania silnika i faktów Zatrzymania
    (``ProcessKind.logs``), a plik ma je jako pola ``RunLog`` o tych samych nazwach. Proces bez dodatków ma wszystkie
    ``None``. Rekordy dodatku, który odtworzenie czyta z powrotem kodem ``src``, stoją we własnym module Logów procesu
    (Wpisanie raportów: ``report_entering_logs``), a pozostałe tutaj."""

    inea_only_cleared: dict[str, int] | None = None
    intermax_entries: LoggedEntries | None = None
    efenix_orders: list[LoggedOrder] | None = None
    efenix_stop: LoggedWindowStop | None = None
    report_entering: LoggedReports | None = None


class LoggedQuantityRules(_Record):
    """Reguły ilości z Listą Urządzeń ze startu Uruchomienia (migawka Ustawień Centrum): dokumenty plików
    ``reguly-ilosci.yaml`` i ``lista-urzadzen.yaml`` (``quantity_rules_file``) jako tekst JSON. Tekst, a nie słownik,
    bo strażnik reguły danych maskuje klucze słownika jak dane, a nazwy pól pliku reguł to słowa narzędzia. Liczą nimi
    Przygotowanie pliku zbiorczego, Przebieg rozliczeń i jego Kontrola ilości, a odtworzenie z Logów liczy nimi zamiast
    regułami z Wydania."""

    rules: str
    devices: str

    @classmethod
    def of(cls, rules: QuantityRules) -> LoggedQuantityRules:
        return cls(rules=_json_text(dump_quantity_rules(rules)), devices=_json_text(dump_device_list(rules.devices)))

    def value(self) -> QuantityRules | RulesProblem:
        """Reguły ilości z Logów tym samym parserem co pliki Ustawień; problem, gdy ich nie da się odczytać (np. maska
        strażnika reguły danych w tekście reguły albo zapis innego Wydania)."""

        try:
            rules, devices = json.loads(self.rules), json.loads(self.devices)
        except ValueError:
            return RulesProblem("plik", "Reguły ilości w Logach nie są tekstem JSON.")
        found = parse_device_list(devices)
        return found if isinstance(found, RulesProblem) else parse_quantity_rules(rules, found)


def _json_text(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


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
    quantity_rules: LoggedQuantityRules | None = None
    """Reguły ilości ze startu Uruchomienia (``LoggedQuantityRules``). ``None``: Logi Urwanego Uruchomienia i pliki sprzed
    tego pola."""

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

    def start_warnings(self) -> tuple[Message, ...]:
        """Ostrzeżenia startu Uruchomienia (``LoggedMessage.at_start``) dla startu odtworzenia."""

        return tuple(message.message() for message in self.messages if message.at_start)

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

