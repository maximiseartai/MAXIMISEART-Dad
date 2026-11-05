"""Logi Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Działanie po wyniku Uruchomienia (``runs.AfterRun``), w każdej drodze zakończenia i w obu trybach. Logi powstają
z tych samych faktów co karta Uruchomienia (``EndedRun``): wynik, Komunikaty z kodami, podsumowanie, etapy, ślad
wywołań Zatrzymania, a z ostatniego snapshotu projekcji postępu (``EndedRun.snapshot``) Przetworzenia Szablonów
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
nie udało; a Zatrzymanie „do Maksa” z przyczyną w wyjątku ma ślad wywołań z łańcuchem przyczyn.
Wiersze danych niesie tylko Kopia wejścia (``input_copy``, #841): każdy plik taty, który Uruchomienie przeczytało, z
odciskiem i przeczytanymi wierszami bez kolumn ``ADRES`` i numeru Orange (w Uporządkowaniu INTERMAX wklejone wiersze,
#842), zebrana po końcu procesu z tego, co czytniki oddały Kopii wejścia Uruchomienia (``EndedRun.input_copy``). Poza nią komórkę cytuje tylko Komunikat
(``ZLE_SKUTECZNE``), a pliki mają tylko nazwę, nigdy pełną ścieżkę. Przed zapisem pliku i przed wysyłką Logi przechodzą
przez strażnika reguły danych pracy Centrum (``guarded``, ADR 0025): wartość ``ADRES`` albo numeru Orange z przeczytanych
plików, także wpisana w inną komórkę Kopii wejścia albo zapisana przez Excel jako liczba, staje się maską z uwagą
techniczną, a telefony i ulice w tekście są zamaskowane. Pola, które niosą tylko słowa i chwile narzędzia (okres,
Uruchomienie, proces, chwile startu i końca, commit), i nazwy pól schematu zostają bez maski (#936).
Skrypt dla maszyn nie ma działań po wyniku, więc Logów nie tworzy.

Schemat 2 (#839) daje każdemu krokowi śladu godzinę (UTC) obok czasu trwania: etap ma chwilę rozpoczęcia i końca,
Przetworzenie Szablonu pracownika też, a działanie okna efenix chwilę rozpoczęcia, więc widać przerwy i czekanie, których
czasy trwania nie liczą. Etapy i Szablony mają chwile z projekcji postępu (``ProgressSnapshot``), działania okna efenix
z jego śladu (``efenix_trace``). Dochodzi dziennik działań taty w Centrum (``dad_actions``) od Logów poprzedniego
Uruchomienia do końca tego, bez treści zapytań, więc bez treści Uwagi taty. Karta z Logów i Historia czytają oba
schematy: plik schematu 1 nie ma godzin ani dziennika, a te pola są w nim ``None``.

Plik leży w katalogu Logów obok dziennika Centrum, poza Gitem i OneDrive, bez rotacji. Nazwa to czas startu (UTC),
klucz procesu i identyfikator Uruchomienia, więc jest jedna na Uruchomienie i układa się chronologicznie. Zapis jest
atomowy; nieudany wychodzi z ``run_ended``, a ``RunHost.after`` zapisuje w dzienniku tylko jego typ, bez zmiany
wyniku i bez Komunikatu.

Te same Logi idą przez kolejkę Skrzynki Zgłoszeń (``Outbox``) jedną wysyłką (``logi_post``, #844): do issue okresu z
etykietą ``logi-uruchomienia``, także zamkniętego, jeden komentarz na Uruchomienie z podsumowaniem w Markdown
(``summary_markdown``) i odnośnikiem do pełnych Logów, a do Archiwum Logów okresu (GitHub Release ``logi-<okres>`` w
repozytorium Skrzynki, nie Wydanie narzędzia) plik o nazwie pliku Logów spakowany gzipem, który rozpakowany ma znak w
znak tekst pliku Logów.

Diagnoza Zatrzymania dopisuje się do Logów swojego Uruchomienia (``RunLogs.diagnosed``): ten sam plik dostaje pole
``diagnosis``, a Logi idą do kolejki drugi raz z tym samym identyfikatorem wysyłki (Uruchomienie i etykieta), więc
kolejka podmienia plik w Archiwum i zmienia komentarz tego Uruchomienia zamiast dokładać nowy (#840, #844).
Diagnoza z tym samym wynikiem co ostatnio dopisana (``LoggedDiagnosis.same_result``) nie zmienia niczego: po
nieoczekiwanym wyjątku karta zaczyna Diagnozę sama przy każdym pokazaniu, a Maks potrzebuje tylko zmiany wyniku.
Diagnozę ma tylko ostatnie Uruchomienie tej pracy Centrum, więc w pamięci zostają tylko jego Logi; Diagnoza,
w której trakcie skończyło się następne Uruchomienie, nie dopisuje się nigdzie.

Urwana Wycena w efenix (#845) ma Logi z dziennika Wyceny w efenix (``pricing_journal``), które start Centrum zamyka
(``RunLogs.interrupted``, ``RunLogs.close``) i wysyła (``RunLogs.send``) jak zwykłe Logi: sposób zakończenia
``interrupted``, bez wyniku (``result`` ``None``), czasu, etapów i Komunikatów, ze śladem zleceń skończonych przed
zgaśnięciem Centrum i ze zleceniem zaczętym bez wyniku (``LoggedInterruption``). Koniec takich Logów to ostatni wpis
dziennika, bo chwili zgaśnięcia nikt nie zapisał.

W trakcie Wyceny w efenix jej komentarz Uruchomienia pokazuje postęp z dziennika (``RunLogs.progress``, #846). Każda
wysyłka Logów jednego Uruchomienia niesie stopień wersji (``outbox.Rank``, #910), który wybiera ten moduł, a nie zegar:
postęp ma najniższy (``DRAFT``), wersja zastępcza, którą następny start Centrum wysyła z dziennika (``send``: Logi z
pliku, Logi Urwanego Uruchomienia albo wynik bez Logów, ``ResultWithoutLogs``), środkowy (``STAND_IN``), a Logi z pracy
Centrum Uruchomienia (``_keep``: z wynikiem, z Diagnozą) najwyższy (``OWN``). Wersja końcowa zamienia więc komentarz
postępu w podsumowanie także po cofnięciu zegara, a wersja zastępcza nie zastępuje Logów z wynikiem, które kolejka już
przyjęła, w kolejce ani w Skrzynce. Start wysyła ją tylko za Wycenę, której Logów kolejka nie przyjęła w pracy jej
Uruchomienia (``queued``), bo inaczej dziennik już zniknął (``pricing_journal.JournalAfterLogs``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import cache
from pathlib import Path
import platform
import re
import threading
from typing import Annotated, Final, Literal, Protocol, assert_never, cast, get_args

from openpyxl.utils import column_index_from_string
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.fields import FieldInfo

from rozliczenia.client_data import CellPlace, CopiedCell, ForbiddenValues, Guarded
from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.dad_actions import DadActionJournal, DadActions
from rozliczenia.centrum.diagnosis import CheckState, Diagnosis
from rozliczenia.centrum.outbox import ArchiveFile, Outbox, PeriodThread, Post, Rank
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.runs import EndedRun, Ending
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.version import short_commit
from rozliczenia.domain import ProgressPhase, SettlementSummary, WorkerStatus
from rozliczenia.efenix_pricing import (
    AheadNotSaved,
    BrowserFailure,
    Closed,
    ElementCount,
    HttpStatus,
    EmmettWarning,
    LoginSign,
    OrderError,
    OrderResult,
    OtherShape,
    PagePart,
    PricingStopped,
    PricingSummary,
    Ready,
    Settled,
    StopCause,
    StoppedOrder,
)
from rozliczenia.efenix_checks import ListedRead
from rozliczenia.efenix_positions import file_quantities
from rozliczenia.efenix_trace import Action, TraceStep
from rozliczenia.input_copy import CellValue, CopiedFile, CopiedSheet, Typed, TypedKind
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.message import Message
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.raw_orders import SHIFT

RUN_LOGS_DIRECTORY: Final = "uruchomienia"
LABEL: Final[Label] = "logi-uruchomienia"

LoggedEnding = Literal[Ending, "interrupted"]
"""Sposób zakończenia w Logach: jak na karcie (``runs.Ending``) albo ``interrupted``, Urwane Uruchomienie, którego Logi
zamknął start Centrum z dziennika Wyceny w efenix."""

ProcessFiles = Callable[[contract.ProcessKey, str], Sequence[Path]]
"""Pliki taty Uruchomienia procesu dla tokenu okresu, z Ustawieniami taty z chwili końca Uruchomienia."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _ReadValues:
    """Znacznik pola Logów (``Annotated``), które niesie wartości przeczytane z komórek pliku taty albo ze strony efenix,
    także liczby: strażnik (``guarded``) maskuje w nim liczbę z zakazaną wartością albo telefonem jak tekst. Każda inna
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
    state: CheckState
    detail: str
    code: str | None

    @property
    def result(self) -> tuple[str, CheckState, str | None, str | None]:
        """Sprawdzenie bez okoliczności: ``detail`` sprawdzenia, które przeszło, to fakt chwili (liczba wpisów dziennika
        rośnie z każdą Diagnozą), a przy ``failed`` i ``not_checked`` sam wynik: treść Komunikatu albo powód."""

        return self.label, self.state, self.code, None if self.state == "passed" else self.detail


class LoggedDiagnosis(_Record):
    """Ostatnia Diagnoza Uruchomienia: wyjaśnienie z kodem, co tata robi dalej i każde sprawdzenie po kolei."""

    diagnosed_at: datetime
    explanation: Explanation
    next_action: contract.DiagnosisNextAction
    checks: list[LoggedCheck]

    @classmethod
    def of(cls, diagnosis: Diagnosis, *, diagnosed_at: datetime) -> LoggedDiagnosis:
        explanation = diagnosis.explanation
        return cls(
            diagnosed_at=diagnosed_at,
            explanation=Explanation(
                code=explanation.code, what=explanation.what, where=explanation.where, action=explanation.action
            ),
            next_action=diagnosis.next_action,
            checks=[
                LoggedCheck(
                    label=check.label,
                    state=check.state,
                    detail=check.detail,
                    code=None if check.message is None else check.message.code,
                )
                for check in diagnosis.checks
            ],
        )

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
    otworzyło; ``None`` przy innych działaniach i w plikach sprzed tych pól.
    """

    action: Action
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
        )


OrderOutcome = Literal["gotowe", "rozliczone", "błąd", "ostrzeżenie Emmetta"]
"""Wynik zlecenia Wyceny w efenix w Logach Uruchomienia; ``rozliczone`` to Zlecenie rozliczone, które nie jest błędem."""


class LoggedOrder(_Record):
    """Ślad zlecenia Wyceny w efenix: wiersz Pliku zbiorczego, wynik z kodem Komunikatu (``None`` przy gotowym i
    rozliczonym), ilości z pliku po kodach pozycji (``None``, gdy nie dało się ich przepisać), ``Kwota`` (AU) i działania
    okna."""

    row: int
    outcome: OrderOutcome
    code: str | None
    file: Annotated[dict[str, LoggedQuantity] | None, READ_VALUES]
    file_amount: Decimal
    steps: list[LoggedStep]

    @classmethod
    def all_of(cls, summary: PricingSummary) -> list[LoggedOrder]:
        """Ślad każdego zlecenia po kolei, z kodem Komunikatu zlecenia, które zostało tacie."""

        codes = {id(result): message.code for result, message in summary.left_for_tata}
        return [cls.of(result, codes.get(id(result))) for result in summary.results]

    @classmethod
    def of(cls, result: OrderResult, code: str | None) -> LoggedOrder:
        """Ślad zlecenia ``result`` z kodem Komunikatu ``code`` zlecenia, które zostało tacie."""

        file = file_quantities(result.order)
        outcome: OrderOutcome
        match result.outcome:
            case Ready():
                outcome = "gotowe"
            case Settled():
                outcome = "rozliczone"
            case EmmettWarning():
                outcome = "ostrzeżenie Emmetta"
            case OrderError():
                outcome = "błąd"
        return cls(
            row=result.order.row,
            outcome=outcome,
            code=code,
            file=dict(file) if isinstance(file, Mapping) else None,
            file_amount=result.order.amount,
            steps=[LoggedStep.of(step) for step in result.steps],
        )


class LoggedCause(_Record):
    """Przyczyna techniczna Zatrzymania Wyceny w efenix z zamkniętej listy (``efenix_pricing.StopCause``), bez treści
    strony i wyjątku: ``part`` to część strony (nazwa ``PagePart``, ``None`` poza stronami efenix), a ``what`` przyczyna z
    listy.

    ``positions``: kod pozycji, której dotyczy budowa albo zapis z wyprzedzeniem w Śladzie Wyceny Emmetta. ``element`` i ``count``: selektor z kodu okna i ile razy jest na
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
    def of(cls, part: PagePart | None, cause: StopCause) -> LoggedCause:
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
            case LoginSign() | Closed():
                return cls(part=name, what=cause.value)
            case AheadNotSaved(position):
                return cls(part=name, what=_AHEAD_NOT_SAVED, positions=[position])
            case _:
                assert_never(cause)


_ELEMENT_COUNT: Final = "element strony nie występuje dokładnie raz"
_BROWSER_FAILURE: Final = "błąd przeglądarki w działaniu okna"
_HTTP_STATUS: Final = "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno"
_AHEAD_NOT_SAVED: Final = "Ślad Wyceny Emmetta nie zapisał ilości z wyprzedzeniem, więc okno jej nie wpisało"


class LoggedWindowStop(_Record):
    """Zatrzymanie okna efenix albo zapisu z wyprzedzeniem w Śladzie Wyceny Emmetta w Wycenie w efenix: przyczyna
    techniczna i zlecenie, przy którym Wycena stanęła.

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


LoggedOrderKind = Literal["FAULT", "WHOLESALE_INSTALLATION", "OTHER"]
"""Nazwa rodzaju zlecenia ``raw_orders.OrderKind`` w Kopii wejścia (``LoggedSheet.order_kinds``)."""


class LoggedSheet(_Record):
    """Przeczytany arkusz: wiersz nagłówka, nagłówki po literze kolumny (bez zakazanych kolumn), wiersze i puste wiersze
    z odczytanego zakresu, które proces liczy (Rejestr zleceń).

    ``shifted_row``: przesunięty pierwszy wiersz wklejenia INTERMAX, którego komórki Uporządkowanie czyta w pliku dwie
    kolumny na lewo od nagłówka, a tu stoją pod nim (``input_copy.CopiedSheet.shifted_row``); ``None``: bez niego i
    pliki sprzed #842. ``uncertain_rows``: wiersze wklejenia z dwoma położeniami, które mają tylko komórki dozwolone
    w każdym ich możliwym położeniu (``input_copy.CopiedSheet.uncertain_rows``). ``last_ordered_row`` i ``yellow_row``:
    ostatni uporządkowany i żółty wiersz nad wklejeniem INTERMAX, od których Planowanie liczy wiersz dnia, bez treści
    (``input_copy.CopiedSheet.last_ordered_row``); ``None``: bez takiego wiersza, inne pliki i pliki sprzed #847.
    ``order_kinds``: rodzaj zlecenia (nazwa ``raw_orders.OrderKind``) wiersza z dwoma położeniami bez ``URZĄDZENIA`` w
    Kopii (``input_copy.CopiedSheet.order_kinds``); nazwa, a nie tekst rodzaju, bo tekst rodzaju to też wartość
    ``URZĄDZENIA``, którą strażnik maskuje jako wartość z drugiego położenia.
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
    order_kinds: dict[int, LoggedOrderKind] = {}

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
            order_kinds={row: cast(LoggedOrderKind, kind.name) for row, kind in sheet.order_kinds.items()},
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
    """Zatrzymanie okna efenix albo zapisu z wyprzedzeniem w Śladzie Wyceny Emmetta z przyczyną techniczną. ``None``: inne
    procesy, Wycena w efenix bez takiego Zatrzymania i pliki sprzed tego pola."""
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
    ze śladem przesunięcia, który łamie fakt domeny (``_domain_fact_notes``), i uwagi strażnika reguły danych o
    wartościach zamaskowanych w Kopii (``guarded``)."""

    @classmethod
    def of(cls, run: EndedRun, *, tool: Tool, environment: Environment, dad_actions: DadActions) -> RunLog:
        info, stopped, snapshot = run.info, run.stopped, run.snapshot
        engine_summary = None if run.shown is None else run.shown.engine_summary
        facts = None if stopped is None else stopped.stop.facts
        priced = engine_summary if isinstance(engine_summary, PricingSummary) else None
        if isinstance(facts, PricingStopped):
            priced = facts.summary
        copied = None if run.input_copy is None else run.input_copy.files()
        return cls(
            schema_version=2,
            run_id=info.id,
            process=info.process,
            mode="podgląd" if info.dry_run else "zapis",
            period=info.period,
            started_at=run.started_at,
            ended_at=run.ended_at,
            duration_ms=run.duration_ms,
            tool=tool,
            result=run.result,
            ending=run.ending,
            stop_kind=None if stopped is None else stopped.kind,
            issue_count=None if snapshot is None else snapshot.issue_count,
            messages=[LoggedMessage.of("stop", stop) for stop in run.stops]
            + [LoggedMessage.of("warning", warning) for warning in run.warnings],
            technical_notes=list(run.technical_notes),
            summary=None if run.shown is None else run.shown.summary,
            phases=LoggedPhase.all_of(run.progress.phases, snapshot),
            templates=[]
            if snapshot is None
            else [
                LoggedTemplate(
                    wykonawca=template.worker_name,
                    outcome=template.outcome,
                    rows=template.rows,
                    duration_ms=template.duration_ms,
                    started_at=template.started_at,
                    ended_at=template.ended_at,
                )
                for template in snapshot.templates
            ],
            inea_only_cleared={column.value: count for column, count in engine_summary.inea_only_cleared.items()}
            if isinstance(engine_summary, SettlementSummary)
            else None,
            intermax_entries=LoggedEntries.of(engine_summary) if isinstance(engine_summary, OrderingSummary) else None,
            efenix_orders=None if priced is None else LoggedOrder.all_of(priced),
            efenix_stop=LoggedWindowStop.of(facts) if isinstance(facts, PricingStopped) else None,
            environment=environment,
            trace=None if stopped is None else stopped.stop.trace,
            diagnosis=None,
            dad_actions=dad_actions,
            input_copy=None if copied is None else [LoggedInputFile.of(file) for file in copied],
            input_copy_notes=[] if copied is None else _domain_fact_notes(copied),
        )

    @classmethod
    def interrupted(
        cls,
        started: StartedFacts,
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
    def file_name(self) -> str:
        """``20261023T140507Z-settlement-<run_id>.json``: start w UTC, klucz procesu, identyfikator Uruchomienia."""

        return logs_file_name(self.started_at, self.process, self.run_id)

    @property
    def text(self) -> str:
        """Treść pliku Logów; te same znaki idą do Skrzynki Zgłoszeń."""

        return self.model_dump_json(indent=2) + "\n"


class StartedFacts(Protocol):
    """Bezpieczne fakty startu Uruchomienia, te same co nagłówek Logów (plik ostatniego startu, dziennik Wyceny w efenix)."""

    @property
    def run_id(self) -> str: ...
    @property
    def process(self) -> contract.ProcessKey: ...
    @property
    def mode(self) -> Literal["podgląd", "zapis"]: ...
    @property
    def period(self) -> str: ...
    @property
    def started_at(self) -> datetime: ...


def _domain_fact_notes(files: Sequence[CopiedFile]) -> list[str]:
    """Uwaga o każdym wierszu Kopii ze śladem przesunięcia poza pierwszym wierszem bloku wklejenia
    (``CopiedSheet.traced_rows``): fakt domeny, na którym Maks opiera koszt reguły danych, nie zachodzi (ADR 0025)."""

    return [
        f"Fakt domeny złamany: wiersz {row} arkusza {sheet.name} w {file.name} ma ślad przesunięcia "
        f"({', '.join(trace.value for trace in traces)}), a nie jest pierwszym wierszem wklejenia; pamięć reguły danych "
        "zna go w obu położeniach (ADR 0025)."
        for file in files
        for sheet in file.sheets
        for row, traces in sorted(sheet.traced_rows.items())
    ]


def logs_file_name(started_at: datetime, process: contract.ProcessKey, run_id: str) -> str:
    """Nazwa pliku Logów Uruchomienia: sekunda startu w UTC, klucz procesu i identyfikator, więc jedna na Uruchomienie,
    a pliki układają się chronologicznie."""

    return f"{started_at:%Y%m%dT%H%M%SZ}-{process}-{run_id}.json"


def guarded(record: RunLog, forbidden: ForbiddenValues) -> RunLog:
    """Logi po strażniku reguły danych (``ForbiddenValues.guard``): każdy tekst i klucz bez zakazanych wartości, z
    zamaskowanymi telefonami i ulicami, a każda zamaskowana wartość to uwaga techniczna z kolumną i polem pliku.

    Strażnik widzi każdy tekst pliku: także datę, kwotę i wartość ``Decimal``, które JSON zapisuje jako tekst. Liczbę
    sprawdza w polu z wartościami z komórek pliku taty albo ze strony efenix (``READ_VALUES``: komórki Kopii wejścia i
    ilości przy zleceniu Wyceny w efenix) w tekście, który pokazuje Excel (``ForbiddenValues.guard_number``), i liczba z
    zakazaną wartością albo telefonem staje się w całości maską. Liczb, które policzyło narzędzie, nie sprawdza.

    Strażnik porównuje słowa, a nie pochodzenie wartości, więc wartość z pliku taty równa słowu albo chwili narzędzia
    trafiłaby też w pole, które niesie tylko to, co dało narzędzie. Takich pól (``TOOL_FIELDS``) nie maskuje i zostawia
    w nich wartość z rekordu, a klucza pola modelu Logów (nazwy pola schematu) też nie: maska w nich gubiła całe Logi
    albo ich okres, Uruchomienie i commit (#936). Klucz słownika (operator, kod pozycji, litera kolumny) to dane, więc go
    maskuje.

    Komórkę Kopii wejścia strażnik sprawdza z jej miejscem w pliku taty i nagłówkiem (``client_data.CopiedCell``):
    wartość z wiersza z dwoma położeniami maskuje w niej tylko tam, gdzie mówi ``client_data``, a nie w zwykłej kolumnie
    innego wiersza tego samego pliku. Każde inne pole to wolny tekst z maską każdej wartości.

    Pole to ścieżka JSON z nazw pól, a klucz z danych (operator, kod pozycji) jest w niej ``[…]``, żeby uwaga nie
    niosła treści. Uwaga o polu Kopii wejścia idzie do ``input_copy_notes``, a każda inna do ``technical_notes``, które
    pokazuje karta Uruchomienia z Logów: Kopii karta nie pokazuje, więc karta po starcie Centrum zostaje taka jak przed
    nim (ADR 0017). Pole typowane, które maski nie przyjmuje, zostaje puste albo odpada z uwagą techniczną
    (``_representable``). Logi bez niczego do zamaskowania wracają te same.
    """

    notes: list[str] = []
    copy_notes: list[str] = []

    def noted(found: Guarded, place: str) -> str:
        (copy_notes if re.split(r"[.\[]", place)[0] == _INPUT_COPY else notes).extend(found.notes)
        return found.text

    def text(value: str, place: str, cell: CopiedCell | None = None) -> str:
        return noted(forbidden.guard(value, place or "Logi", cell), place)

    def number(value: int | float, place: str, cell: CopiedCell | None) -> object:
        found = forbidden.guard_number(value, place, cell)
        return value if found is None else noted(found, place)

    def walk(source: object, value: object, place: str, read: bool, at: _InCopy) -> object:
        """``value`` z JSON-a Logów i ``source``, z którego powstał (``None``: poza modelem Logów); ``read``: w polu
        ``READ_VALUES``; ``at``: miejsce w Kopii wejścia."""

        at = at.into(source)
        if place in TOOL_FIELDS:
            return value
        if isinstance(value, str):
            return text(value, place, at.cell)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return number(value, place, at.cell) if read else value
        if isinstance(value, list):
            sources = source if isinstance(source, list) else [None] * len(value)
            return [
                walk(item, entry, f"{place}[{index}]", read, at)
                for index, (item, entry) in enumerate(zip(sources, value, strict=True))
            ]
        if isinstance(value, dict):
            items: dict[str, object] = {}
            for key, entry in value.items():
                child, field = _child(source, key)
                marked = field is not None and READ_VALUES in field.metadata
                items[key if field is not None else text(key, place)] = walk(
                    child, entry, _field(place, key), read or marked, at.under(source, key)
                )
            return items
        return value

    dumped = record.model_dump(mode="json")
    walked = walk(record, dumped, "", False, _InCopy())
    if walked == dumped:
        return record
    assert isinstance(walked, dict)
    walked["technical_notes"] = [*walked["technical_notes"], *dict.fromkeys(notes)]
    walked["input_copy_notes"] = [*walked["input_copy_notes"], *dict.fromkeys(copy_notes)]
    return _representable(walked)


_INPUT_COPY: Final = "input_copy"
"""Pole Kopii wejścia w Logach; uwagi strażnika o nim idą do ``input_copy_notes``."""


@dataclass(frozen=True)
class _InCopy:
    """Miejsce strażnika w Kopii wejścia: plik, arkusz i wiersz, nad którymi jest, a ``cell`` to komórka, której
    wartość sprawdza (``None``: poza komórką Kopii); ``cells``: w słowniku komórek wiersza."""

    file: LoggedInputFile | None = None
    sheet: LoggedSheet | None = None
    row: int | None = None
    cells: bool = False
    cell: CopiedCell | None = None

    def into(self, source: object) -> _InCopy:
        if isinstance(source, LoggedInputFile):
            return _InCopy(file=source)
        if isinstance(source, LoggedSheet):
            return replace(self, sheet=source)
        if isinstance(source, LoggedRow):
            return replace(self, row=source.row)
        return self

    def under(self, source: object, key: str) -> _InCopy:
        """Miejsce pod kluczem ``key`` słownika ``source``: komórka, gdy to litera w słowniku komórek wiersza."""

        if self.cells:
            return replace(self, cells=False, cell=self._cell(key))
        return replace(self, cells=isinstance(source, LoggedRow) and key == "cells")

    def _cell(self, letter: str) -> CopiedCell | None:
        """Komórka ``letter`` wiersza Kopii w pliku taty: przesunięty pierwszy wiersz wklejenia INTERMAX stoi w Kopii pod
        nagłówkiem, a w pliku ``SHIFT`` kolumn na lewo; ``None`` (wolny tekst), gdy to nie litera kolumny."""

        if self.file is None or self.sheet is None or self.row is None:
            return None
        try:
            column = column_index_from_string(letter)
        except ValueError:
            return None
        shift = SHIFT if self.row == self.sheet.shifted_row else 0
        place = CellPlace(self.file.name, self.file.fingerprint.sha256, self.sheet.sheet, self.row, column - shift)
        return CopiedCell(place, self.sheet.columns.get(letter))

TOOL_FIELDS: Final = frozenset(
    {
        "run_id",
        "process",
        "mode",
        "period",
        "started_at",
        "ended_at",
        "tool",
        "result",
        "ending",
        "stop_kind",
        "phases",
        "trace",
        "dad_actions",
        "environment.system",
        "environment.python",
    }
)
"""Pola Logów (ścieżka JSON jak w uwadze strażnika), które niosą tylko słowa i chwile narzędzia, więc strażnik
(``guarded``) zostawia w nich wartość z rekordu (#936). Każde ma wartość z kodu narzędzia, a nie z pliku taty:
``run_id`` to ``uuid4``, ``period`` token okresu z ``parse_period_token`` albo z zegara (INTERMAX), ``process``,
``mode``, ``result``, ``ending`` i ``stop_kind`` to wartości zamkniętych list schematu, ``started_at`` i ``ended_at``
chwile zegara Centrum (w Logach Urwanego Uruchomienia z dziennika Wyceny, który pisze Centrum), ``tool`` Wydanie i
commit z Gita narzędzia, ``phases`` etapy z zamkniętej listy ze stanem, czasem i chwilami projekcji postępu, ``trace``
typy wyjątków i ramki kodu narzędzia bez treści wyjątku (``call_trace``), ``dad_actions`` chwile, wartości zamkniętych
list i operacje API z kontraktu bez treści zapytań, a ``system`` i ``python`` Środowiska moduł ``platform``.

Pole spoza listy może nieść treść pliku taty (tekst Komunikatu, Wykonawca, nazwa pliku, odczyt strony efenix, Kopia
wejścia), więc strażnik maskuje je dalej, także w polu z wartością narzędzia w modelu, który niesie i jedno, i drugie
(kod Komunikatu, wynik zlecenia efenix). Liczby, które policzyło narzędzie (``schema_version``, ``duration_ms``,
``issue_count``, ``interruption``), zostają i bez listy, bo strażnik sprawdza tylko liczby z ``READ_VALUES``. Każde
pole najwyższego poziomu bez ``None`` poza Środowiskiem jest więc na liście, jest liczbą narzędzia albo listą, z której
maska zabiera najwyżej element, a Środowisko (``environment``) ma poza listą tylko pliki procesu (lista albo ``None``),
więc maska nie gubi całych Logów (``UnrepresentableLogs``).

Pole z listy strażnik zostawia z całym poddrzewem, więc test struktury w ``tests/test_komentarz_logow_uruchomienia.py``
przechodzi typ każdego z nich (modele, dataclassy, unie) i czerwienieje, gdy w poddrzewie jest typ, który przyjmuje
dowolny tekst (``str`` spoza jawnych wyjątków z powodem w teście, słownik, ``Any``), liczba ``READ_VALUES`` albo typ,
którego test nie zna."""

_Path = tuple[str | int, ...]


class UnrepresentableLogs(ValueError):
    """Logi, w których maska strażnika trafiła w pole, które nie może stracić wartości: pole najwyższego poziomu bez
    ``None`` spoza listy pól narzędzia (``TOOL_FIELDS``), albo ``stuck``: cięcia (``_representable``) przestały zmieniać
    Logi, czyli błąd w cięciach. ``place``: to pole albo miejsce ostatniego cięcia.

    Schemat Logów nie ma dziś pola najwyższego poziomu bez ``None``, które gubiłoby Logi (#936). Nowe takie pole wywraca
    przemiatanie pełnych Logów w ``tests/test_komentarz_logow_uruchomienia.py``, które każe pełnym Logom mieć wartość w
    każdym polu ``RunLog``: każdy tekst i każda liczba tych Logów (od ``MIN_VALUE`` znaków) po kolei jako wartość z pliku
    taty, także liczba w polu ``READ_VALUES``. Pole, którego wartość w pełnych Logach jest krótsza, przemiatanie
    przepuszcza."""

    def __init__(self, place: str, *, stuck: bool = False) -> None:
        reason = (
            f"cięcia strażnika przestały zmieniać Logi (ostatnie w polu {place})"
            if stuck
            else f"Logi bez miejsca na maskę strażnika w polu {place} (#936)"
        )
        super().__init__(reason)
        self.place = place
        self.stuck = stuck


@dataclass(frozen=True)
class GuardCut:
    """Miejsce Logów, które straciło wartość, bo strażnik zamaskował w nim pole, które maski nie przyjmuje
    (``_representable``): ``removed`` element listy odpadł, inaczej pole jest puste. ``place``: ścieżka JSON jak w
    uwadze strażnika."""

    place: str
    removed: bool


def guard_cuts(record: RunLog) -> tuple[GuardCut, ...]:
    """Miejsca, które strażnik pominął albo zostawił puste, z uwag technicznych i uwag o Kopii wejścia Logów."""

    found = (_CUT_NOTE.fullmatch(note) for note in (*record.technical_notes, *record.input_copy_notes))
    return tuple(
        GuardCut(match["removed"] or match["emptied"], match["removed"] is not None) for match in found if match
    )


def _cut_note(place: str, removed: bool) -> str:
    what = f"pominięto {place}" if removed else f"pole {place} jest puste"
    return f"Reguła danych: {what}: strażnik zamaskował w nim wartość, której pole nie przyjmuje."


_CUT_NOTE: Final = re.compile(
    r"Reguła danych: (?:pominięto (?P<removed>\S+)|pole (?P<emptied>\S+) jest puste): strażnik zamaskował w nim "
    r"wartość, której pole nie przyjmuje\."
)
"""Uwaga ``_cut_note``; miejsce (``_place``) nie ma spacji."""


def _representable(walked: dict[str, object]) -> RunLog:
    """Logi z JSON-a po strażniku (``guarded``), w którym każde pole przyjmuje swoją wartość.

    Pole typowane (kwota ``Decimal``, data, wartość z zamkniętej listy), w którym strażnik zamaskował tekst, maski nie
    przyjmuje, więc takie Logi nie przeszłyby walidacji i przepadły. Pole dostaje ``None``, a gdy i ``None`` nie
    przyjmuje, odpada najbliższy element listy nad nim (zlecenie, krok, plik) albo ``None`` dostaje pole nad nim
    (``_cut``), z uwagą techniczną o tym miejscu (``guard_cuts``). Pole Logów najwyższego poziomu bez ``None`` i poza
    listą nie ma czego stracić, więc dałoby ``UnrepresentableLogs``, ale każde takie pole niesie słowa narzędzia, których
    strażnik nie maskuje (``TOOL_FIELDS``, #936).

    Każde cięcie zabiera Logom co najmniej jedną wartość, więc cięć jest najwyżej tyle, ile Logi mają wartości:
    po tylu obrotach bez poprawnych Logów pętla kończy się ``UnrepresentableLogs``, a nie wisi z końcem Uruchomienia.
    """

    # Miejsce w Logach przed cięciami → odpadło z listy (``False``: dostało ``None``). Błędy idą od ostatniego, więc
    # element, który odpada, przesuwa w liście tylko elementy już bez błędów, a miejsca w uwagach są te sprzed cięć.
    cuts: dict[_Path, bool] = {}
    place: _Path = ()
    for _ in range(_values(walked) + 1):
        try:
            record = RunLog.model_validate(walked)
        except ValidationError as failure:
            place, removed = _cut(walked, _existing(walked, failure.errors()[-1]["loc"]))
            if removed:
                cuts = {cut: kind for cut, kind in cuts.items() if cut[: len(place)] != place}
            cuts[place] = removed
            continue
        notes: dict[bool, list[str]] = {True: [], False: []}  # Kopia wejścia → uwagi
        for path, removed in sorted(cuts.items()):
            notes[path[0] == _INPUT_COPY].append(_cut_note(_place(path), removed))
        return record.model_copy(
            update={
                "technical_notes": [*record.technical_notes, *notes[False]],
                "input_copy_notes": [*record.input_copy_notes, *notes[True]],
            }
        )
    raise UnrepresentableLogs(_place(place), stuck=True)


def _cut(walked: dict[str, object], path: _Path) -> tuple[_Path, bool]:
    """Najgłębsze miejsce ścieżki błędu walidacji ``path``, które może stracić wartość, i czy odpadło z listy.

    Element listy odpada, a pole z wartością dostaje ``None``. Pole, które już ma ``None``, a wciąż ma błąd, ``None``
    nie przyjmuje, więc wartość traci miejsce wyżej; ścieżka bez takiego miejsca to ``UnrepresentableLogs``.
    """

    for depth in range(len(path), 0, -1):
        place = path[:depth]
        container, key = _at(walked, place[:-1]), place[-1]
        if isinstance(container, list) and isinstance(key, int):
            del container[key]
            return place, True
        if isinstance(container, dict) and container[key] is not None:
            container[key] = None
            return place, False
    raise UnrepresentableLogs(_place(path))


def _values(value: object) -> int:
    """Liczba wartości JSON-a (słowników, list i liści) bez ``None``: ile razy najwyżej da się coś z niego zabrać."""

    if isinstance(value, dict):
        return 1 + sum(_values(entry) for entry in value.values())
    if isinstance(value, list):
        return 1 + sum(_values(entry) for entry in value)
    return 0 if value is None else 1


def _existing(walked: object, location: Sequence[str | int]) -> _Path:
    """Najdłuższy początek miejsca błędu walidacji ``location``, który jest w JSON-ie ``walked`` (dalej pydantic dopisuje
    nazwy wariantów typu)."""

    path: list[str | int] = []
    for key in location:
        if isinstance(walked, dict) and key in walked:
            walked = walked[key]
        elif isinstance(walked, list) and isinstance(key, int):
            walked = walked[key]
        else:
            break
        path.append(key)
    return tuple(path)


def _at(walked: object, path: _Path) -> object:
    for key in path:
        if isinstance(walked, dict):
            walked = walked[key]
        elif isinstance(walked, list) and isinstance(key, int):
            walked = walked[key]
    return walked


def _place(path: _Path) -> str:
    place = ""
    for key in path:
        place = f"{place}[{key}]" if isinstance(key, int) else _field(place, key)
    return place


def _child(source: object, key: str) -> tuple[object, FieldInfo | None]:
    """Wartość pod kluczem ``key`` modelu albo słownika ``source``, z którego powstał JSON Logów, i pole modelu z tym
    kluczem (``None``: klucz słownika, czyli dane, albo JSON poza modelem Logów)."""

    if isinstance(source, BaseModel):
        return getattr(source, key, None), type(source).model_fields.get(key)
    if isinstance(source, Mapping):
        return source.get(key), None
    return None, None


def _field(place: str, key: str) -> str:
    name = key if _FIELD_NAME.fullmatch(key) else "[…]"
    return f"{place}.{name}" if place else name


_FIELD_NAME: Final = re.compile(r"[a-z_]+")
"""Nazwa pola schematu Logów; inny klucz (operator, kod pozycji, litera kolumny) to dane."""


def logi_post(record: RunLog, rank: Rank = Rank.OWN) -> Post:
    """Logi do Skrzynki Zgłoszeń jedną wysyłką: komentarz z podsumowaniem i odnośnikiem w issue okresu i pełne Logi w
    Archiwum Logów okresu (``archive_file``).

    Identyfikator wysyłki to Uruchomienie (``run_id``) i etykieta ``logi-uruchomienia``, te same po Diagnozie i w
    postępie Wyceny w efenix (``progress_post``), więc Logi z Diagnozą podmieniają plik w Archiwum i zmieniają komentarz
    swojego Uruchomienia, a Logi na końcu Wyceny zamieniają jej komentarz postępu w podsumowanie (``outbox``). Stopień
    wersji ``rank``: ``OWN`` dla Logów z pracy Centrum Uruchomienia, ``STAND_IN`` dla Logów, które start wysyła z
    dziennika (``RunLogs.send``).
    """

    return _logs_post(record.period, record.run_id, summary_markdown(record), archive_file(record), rank)


def _logs_post(period: str, run_id: str, comment: str, archive: ArchiveFile | None, rank: Rank) -> Post:
    """Wysyłka Logów Uruchomienia ``run_id`` w stopniu wersji ``rank``: jeden komentarz ``comment`` w issue Logów
    okresu ``period``."""

    return Post(
        PeriodThread(
            label=LABEL,
            line=f"- Logi Uruchomienia okresu: {period}",
            closed="reuse",
            title=f"Logi Uruchomienia {period}",
        ),
        period=period,
        run_id=run_id,
        header=(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to jeden komentarz: "
            f"podsumowanie i odnośnik do pełnych Logów w Archiwum Logów okresu (Release `logi-{period}`)."
        ),
        parts=(comment + "\n",),
        archive=archive,
        rank=rank,
    )


@dataclass(frozen=True)
class OrderDone:
    """Zlecenie skończone w trakcie Wyceny w efenix, jak we wpisie dziennika „zlecenie skończone”: wiersz Pliku
    zbiorczego, wynik i kod Komunikatu zlecenia (``None`` przy gotowym i rozliczonym)."""

    row: int
    outcome: OrderOutcome
    code: str | None


@dataclass(frozen=True)
class PricingProgress:
    """Postęp Wyceny w efenix w trakcie Uruchomienia (#846): to, co ma jej dziennik na dysku.

    ``done``: zlecenia skończone po kolei; ``total``: ile zleceń ma przebieg, z ostatniego wpisu „zaczynam zlecenie”
    (``None`` przed pierwszym, np. gdy okno efenix czeka na logowanie taty, albo gdy dziennika nie da się zapisać);
    ``current``: wiersz zlecenia zaczętego bez wyniku (``None`` między zleceniami).
    """

    started: StartedFacts
    done: tuple[OrderDone, ...]
    total: int | None
    current: int | None


def progress_post(progress: PricingProgress, comment: str) -> Post:
    """Postęp Wyceny w efenix jako wersja wysyłki Logów tego Uruchomienia (``logi_post``) najniższego stopnia
    (``Rank.DRAFT``): ten sam identyfikator i ten sam komentarz w issue Logów okresu, a ``comment`` to jego tekst
    (``progress_markdown``). Każda wersja końcowa jest od niego nowsza, także po cofnięciu zegara komputera.

    Postęp nie ma pliku w Archiwum Logów okresu: pełne Logi powstają dopiero na końcu Uruchomienia.
    """

    return _logs_post(progress.started.period, progress.started.run_id, comment, None, Rank.DRAFT)


def progress_markdown(progress: PricingProgress, *, elapsed_s: float) -> str:
    """Komentarz postępu: proces, tryb, okres, zlecenia skończone z wszystkich i ich wyniki, ostatnie skończone,
    zlecenie w trakcie, czas od startu (``elapsed_s``) i Uruchomienie; odnośnik do pełnych Logów przychodzi z końcem."""

    started = progress.started
    done = progress.done
    orders = _orders_done(progress) or "dziennik Wyceny nie ma jeszcze żadnego zlecenia"
    lines = ["- Wynik: jeszcze nie ma, Uruchomienie trwa", f"- Zlecenia: {orders}"]
    if done:
        last = done[-1]
        code = "" if last.code is None else f", `{last.code}`"
        lines.append(f"- Ostatnie zlecenie: wiersz {last.row}, {last.outcome}{code}")
    if progress.current is not None:
        lines.append(f"- W trakcie: wiersz {progress.current}")
    lines += [
        f"- Czas: {int(elapsed_s // 60)} min do tej pory",
        f"- Uruchomienie: {started.run_id}, start {started.started_at:%Y-%m-%d %H:%M:%S} UTC",
        "- Pełne Logi: w tym komentarzu, gdy Uruchomienie się skończy",
    ]
    return _comment_title(started) + "\n".join(lines)


LogsMissing = Literal["niezapisane", "nieczytelne"]
"""Dlaczego start Centrum nie ma Logów Wyceny, która doszła do wyniku: pliku nie ma albo nie da się go odczytać."""

_LOGS_MISSING: Final[dict[LogsMissing, str]] = {
    "niezapisane": "nie ma, Centrum nie zapisało ich po wyniku (np. zamknęło się tuż po nim)",
    "nieczytelne": "plik Logów na komputerze taty jest, ale nie da się go odczytać",
}


@dataclass(frozen=True)
class ResultWithoutLogs:
    """Wersja końcowa komentarza Uruchomienia Wyceny w efenix, której Logów start Centrum nie ma (``logs``): wynik z
    wpisu końca dziennika Wyceny (``result``; ``None``: dziennik go nie ma) i zlecenia z dziennika (``journal``), bez
    pliku w Archiwum Logów okresu."""

    journal: PricingProgress
    result: contract.RunResult | None
    logs: LogsMissing


def without_logs_markdown(final: ResultWithoutLogs) -> str:
    """Wynik bez Logów: proces, tryb, okres, wynik z wpisu końca dziennika, zlecenia skończone z dziennika i ich wyniki,
    zlecenie zaczęte bez wyniku, Uruchomienie i dlaczego pełnych Logów nie ma."""

    journal = final.journal
    started = journal.started
    result = "nieznany, dziennik Wyceny go nie ma" if final.result is None else final.result
    lines = [f"- Wynik: {result}", f"- Zlecenia: {_orders_done(journal) or 'dziennik Wyceny nie ma żadnego zlecenia'}"]
    if journal.current is not None:
        lines.append(f"- Zlecenie bez wyniku: wiersz {journal.current}")
    lines += [
        f"- Uruchomienie: {started.run_id}, start {started.started_at:%Y-%m-%d %H:%M:%S} UTC",
        f"- Pełne Logi: {_LOGS_MISSING[final.logs]}",
    ]
    return _comment_title(started) + "\n".join(lines)


def _comment_title(started: StartedFacts) -> str:
    return f"**Logi Uruchomienia**: {declaration_of(started.process).title}, {started.mode}, okres {started.period}\n\n"


def _orders_done(progress: PricingProgress) -> str | None:
    """Ile zleceń skończonych z wszystkich i ile każdego wyniku, w kolejności ``OrderOutcome``; ``None`` przed
    pierwszym wpisem „zaczynam zlecenie”."""

    if progress.total is None:
        return None
    counted = Counter(order.outcome for order in progress.done)
    outcomes = ", ".join(f"{outcome} {counted[outcome]}" for outcome in get_args(OrderOutcome) if counted[outcome])
    return f"{len(progress.done)} z {progress.total} skończone" + (f" ({outcomes})" if outcomes else "")


def archive_file(record: RunLog) -> ArchiveFile:
    """Pełne Logi w Archiwum Logów okresu: Release z tagiem ``logi-<okres>``, plik o nazwie i treści pliku Logów."""

    period = record.period
    return ArchiveFile(
        tag=f"logi-{period}",
        title=f"Logi Uruchomień {period}",
        description=(
            f"Pełne Logi Uruchomień okresu {period} z Centrum rozliczeń taty: jeden plik na Uruchomienie, nazwany jak "
            "plik Logów na komputerze taty i spakowany gzipem. To nie jest Wydanie narzędzia."
        ),
        name=record.file_name,
        text=record.text,
    )


def summary_markdown(record: RunLog) -> str:
    """Komentarz Logów: proces, tryb, okres, wynik, czas, kody Komunikatów, Diagnoza, Wydanie i odnośnik do pełnych Logów
    w Archiwum Logów okresu."""

    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    diagnosis = "" if record.diagnosis is None else f"- Diagnoza: {_diagnosis(record.diagnosis)}\n"
    archive = archive_file(record)
    return (
        f"**Logi Uruchomienia**: {declaration_of(record.process).title}, {record.mode}, okres {record.period}\n"
        "\n"
        f"- Wynik: {_result(record)}\n"
        f"- Czas: {_duration(record.duration_ms)}\n"
        f"- Komunikaty: {_codes(record.messages)}\n"
        f"{diagnosis}"
        f"- Wydanie: {record.tool.wydanie or 'brak'}, commit {commit}\n"
        f"- Uruchomienie: {record.run_id}, start {record.started_at:%Y-%m-%d %H:%M:%S} UTC\n"
        f"- Pełne Logi: [{archive.packed_name}]({archive.link})"
    )


def _diagnosis(diagnosis: LoggedDiagnosis) -> str:
    """Kod wyjaśnienia, a po nim sprawdzenia, które nie przeszły albo których nie sprawdzono."""

    groups = [f"`{diagnosis.explanation.code}`"]
    for state, name in (("failed", "nie przeszło"), ("not_checked", "nie sprawdzono")):
        labels = [check.label for check in diagnosis.checks if check.state == state]
        if labels:
            groups.append(f"{name}: {', '.join(labels)}")
    return "; ".join(groups)


def _result(record: RunLog) -> str:
    match record.ending:
        case "finished":
            return f"{record.result}"
        case "stop" | "declined":
            return f"{record.result}, {_stop(record.stop_kind)}"
        case "unexpected":
            return f"{record.result}, nieoczekiwany wyjątek"
        case "after_engine":
            return f"{record.result}, błąd po zakończeniu silnika"
        case "interrupted":
            return "brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)"
        case _:
            assert_never(record.ending)


def _stop(kind: contract.StopKind | None) -> str:
    match kind:
        case "for_tata":
            return "Zatrzymanie dla taty"
        case "for_maks":
            return "Zatrzymanie do Maksa"
        case "repeated":
            return "powtórzone Zatrzymanie dla taty"
        case "declined":
            return "Zatrzymanie po odmowie w Decyzji taty"
        case None:
            return "Zatrzymanie"
        case _:
            assert_never(kind)


def _duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "nieznany"
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    return f"{milliseconds / 1000:.1f} s".replace(".", ",")


def _codes(messages: Sequence[LoggedMessage]) -> str:
    """Kody w kolejności karty, każdy raz, z liczbą powtórzeń i rodzajem."""

    counted = Counter((message.kind, message.code) for message in messages)
    if not counted:
        return "brak"
    kinds = {"stop": "Zatrzymanie", "warning": "ostrzeżenie"}
    return ", ".join(
        f"`{code}`{f' ×{count}' if count > 1 else ''} ({kinds[kind]})" for (kind, code), count in counted.items()
    )


class RunLogs:
    """Logi Uruchomienia każdego Uruchomienia procesu z Centrum (``runs.AfterRun``) w katalogu ``directory``."""

    def __init__(
        self,
        directory: Path,
        outbox: Outbox,
        *,
        commit: CommitSource,
        wydanie: Callable[[str], Release | None],
        files: ProcessFiles,
        cloud_files: CloudFiles,
        dad_actions: DadActionJournal,
        forbidden: ForbiddenValues,
    ) -> None:
        self._directory = directory
        self._dad_actions = dad_actions
        self._forbidden = forbidden
        self._outbox = outbox
        self._commit = commit
        self._wydanie = wydanie
        self._files = files
        self._cloud = cloud_files
        self._lock = threading.Lock()
        self._last: RunLog | None = None  # Logi ostatniego Uruchomienia tak, jak ostatnio poszły do pliku i Skrzynki
        self._ended: set[str] = set()  # Uruchomienia tej pracy Centrum po wyniku: ich postęp się skończył (``progress``)
        # Uruchomienia tej pracy Centrum, których Logi przyjęła Kolejka wysyłki (``queued``); ``_keep`` tylko dodaje,
        # jedną operacją ``set.add``, także bez blokady.
        self._queued: set[str] = set()

    def run_ended(self, run: EndedRun) -> None:
        with self._lock:  # postęp, który już idzie do kolejki, jest w niej przed Logami, a następny nie pójdzie
            self._ended.add(run.info.id)
        environment = self._environment(run.info.process, run.info.period)
        record = RunLog.of(run, tool=self._tool(), environment=environment, dad_actions=self._dad_actions.take())
        with self._lock:
            self._last = record
        self._keep(record)

    def link(self, run_id: str) -> str | None:
        """Adres komentarza Logów Uruchomienia ``run_id``, który Skrzynka przyjęła w tej pracy Centrum; ``None``: jeszcze żaden.

        Komentarz Uruchomienia prowadzi do jego pełnych Logów w Archiwum Logów okresu, także po Diagnozie.
        """

        return self._outbox.delivered(run_id, LABEL)

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None:
        """Dopisuje Diagnozę do Logów Uruchomienia ``run_id``: do pliku, do pliku w Archiwum Logów okresu i do komentarza
        Uruchomienia w issue okresu.

        Logi z Diagnozą to nowsza wersja tej samej wysyłki (``logi_post``), więc kolejka podmienia plik w Archiwum i
        zmienia komentarz, które już są w Skrzynce. Logi, które jeszcze czekają w kolejce, nowsza wersja zastępuje
        (``outbox._superseded``): przejście kolejki, które zastaje obie, oznacza starsze bez wysyłania i wysyła tylko Logi z
        Diagnozą, jednym komentarzem bez edycji. Gdy przejście przeczytało Logi, zanim przyszła Diagnoza, wysyła je, a
        plik w Archiwum i komentarz zmienia następne przejście.

        Uruchomienie, którego Logi nie powstały w tej pracy Centrum, nie dostaje niczego, a Diagnoza z tym samym
        wynikiem co ostatnio dopisana też nie.
        """

        with self._lock:  # dwie Diagnozy naraz (np. dwie karty): plik i komentarz każdej, jedna po drugiej
            last = self._last
            if last is None or last.run_id != run_id:
                return
            logged = LoggedDiagnosis.of(diagnosis, diagnosed_at=datetime.now(timezone.utc))
            if last.diagnosis is not None and logged.same_result(last.diagnosis):
                return
            record = last.model_copy(update={"diagnosis": logged})
            self._keep(record)
            self._last = record  # po pliku, który nie powstał, następna Diagnoza próbuje znowu: plik i komentarz

    def _keep(self, record: RunLog) -> None:
        """Plik Logów (nowy albo nadpisany) po strażniku reguły danych, a do Skrzynki komentarz w issue okresu i plik w
        Archiwum Logów okresu z tymi samymi bajtami co plik (``_write``); Logi, które kolejka przyjęła, zna ``queued``."""

        kept = guarded(record, self._forbidden)
        try:
            self._write(kept)
        finally:
            # Katalog Logów, który nie przyjął pliku, nie zatrzymuje Logów w drodze do Maksa.
            if self._outbox.post(logi_post(kept)):
                self._queued.add(kept.run_id)

    def queued(self, run_id: str) -> bool:
        """Czy Kolejka wysyłki przyjęła w tej pracy Centrum Logi Uruchomienia ``run_id`` (``run_ended``), także gdy ich
        pliku nie dało się zapisać: wersja końcowa jego komentarza Uruchomienia jest już w drodze do Skrzynki."""

        return run_id in self._queued

    def interrupted(
        self,
        started: StartedFacts,
        *,
        ended_at: datetime,
        orders: Sequence[LoggedOrder],
        interruption: LoggedInterruption,
    ) -> RunLog:
        """Logi Urwanego Uruchomienia ``started`` (``RunLog.interrupted``) z dzisiejszym narzędziem i środowiskiem i z
        działaniami taty, które czekają na Logi: Aktualizacja narzędzia nie startuje w trakcie Uruchomienia, więc po
        zgaśnięciu Centrum ma ten sam commit."""

        return RunLog.interrupted(
            started,
            ended_at=ended_at,
            orders=orders,
            interruption=interruption,
            tool=self._tool(),
            environment=self._environment(started.process, started.period),
            dad_actions=self._dad_actions.take(),
        )

    def file_of(self, started: StartedFacts) -> Path:
        """Plik Logów Uruchomienia ``started``, także taki, którego jeszcze nie ma."""

        return self._directory / logs_file_name(started.started_at, started.process, started.run_id)

    def guard(self, record: RunLog) -> RunLog:
        """Logi ``record`` po strażniku reguły danych tej pracy Centrum (``guarded``), jak w ``_keep``: Logi Urwanego
        Uruchomienia przechodzą przez niego przed plikiem (``close``) i wysyłką (``send``)."""

        return guarded(record, self._forbidden)

    def close(self, record: RunLog) -> None:
        """Plik Logów Urwanego Uruchomienia, jeszcze bez wysyłki (``send``); ``OSError``: pliku nie udało się zapisać."""

        self._write(record)

    def _write(self, record: RunLog) -> None:
        """Plik Logów ``record`` z bajtami pliku w Archiwum Logów okresu (``ArchiveFile.packed``): ``text`` w UTF-8 bez
        zamiany ``\n`` na ``\r\n``, którą robi zapis tekstowy na Windows, więc ``gunzip`` pliku z Archiwum daje plik
        z komputera taty bajt w bajt."""

        replace_atomically(self._directory / record.file_name, record.text, newline="")

    def send(self, final: RunLog | ResultWithoutLogs) -> bool:
        """Wersja zastępcza komentarza Uruchomienia, którą start Centrum zamyka dziennik Wyceny, do Kolejki wysyłki w
        stopniu ``Rank.STAND_IN``: Logi (``logi_post``) albo wynik bez Logów po strażniku reguły danych tej pracy Centrum.
        Zastępuje postęp, a Logi z wynikiem, które kolejka przyjęła w pracy Uruchomienia, zostają. ``False``: kolejka jej
        nie przyjęła (typ błędu jest w dzienniku Centrum)."""

        match final:
            case RunLog():
                return self._outbox.post(logi_post(final, Rank.STAND_IN))
            case ResultWithoutLogs(journal=journal):
                comment = self._guarded(without_logs_markdown(final), "wynik Wyceny w efenix bez Logów")
                started = journal.started
                return self._outbox.post(_logs_post(started.period, started.run_id, comment, None, Rank.STAND_IN))

    def progress(self, run_id: str, progress: PricingProgress | None, *, elapsed_s: float) -> bool:
        """Postęp Wyceny w efenix ``run_id`` do Kolejki wysyłki jako starsza wersja wysyłki Logów tego Uruchomienia
        (``progress_post``), po strażniku reguły danych tej pracy Centrum jak Logi: zamaskowana wartość to uwaga techniczna
        na końcu komentarza. ``progress`` ``None``: dziennik nie ma jeszcze na dysku swojej pierwszej linii, więc nic nie
        idzie. ``False``: Uruchomienie doszło do działań po wyniku (``run_ended``), więc jego postęp się skończył i nic nie
        idzie, bo postęp po Logach byłby ich nowszą wersją i cofnąłby podsumowanie. Postęp, którego kolejka nie przyjęła,
        daje ``True``: typ błędu jest w dzienniku Centrum, a następne odświeżenie spróbuje znowu."""

        with self._lock:
            if run_id in self._ended:
                return False
            if progress is not None:
                comment = self._guarded(progress_markdown(progress, elapsed_s=elapsed_s), "postęp Wyceny w efenix")
                self._outbox.post(progress_post(progress, comment))
            return True

    def _guarded(self, text: str, place: str) -> str:
        """Komentarz bez pliku Logów po strażniku reguły danych: zamaskowana wartość to uwaga techniczna na jego końcu."""

        guarded = self._forbidden.guard(text, place)
        return guarded.text + "".join(f"\n- Uwaga techniczna: {note}" for note in guarded.notes)

    def _tool(self) -> Tool:
        commit = self._commit()
        release = None if commit is None else self._wydanie(commit)
        return Tool(wydanie=None if release is None else release.version, commit=commit)

    def _environment(self, process: contract.ProcessKey, period: str) -> Environment:
        try:
            paths = self._files(process, period)
        except (OSError, PeriodFolderInaccessible):
            # Niedostępny folder to stan komputera taty, nie nieoczekiwany wyjątek: bez wpisu, który Diagnoza by zgłosiła.
            files = None
        else:
            files = [self._file(path) for path in paths]
        return Environment(system=_system(), python=platform.python_version(), files=files)

    def _file(self, path: Path) -> LoggedFile:
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        online_only = self._cloud.online_only(path) if self._cloud.checked and size is not None else None
        return LoggedFile(name=path.name, size=size, online_only=online_only)


@cache
def _system() -> str:
    """System raz na pracę Centrum, przy pierwszych Logach, nie przy starcie; nigdy ``platform.node()`` (nazwa komputera)."""

    return platform.platform()
