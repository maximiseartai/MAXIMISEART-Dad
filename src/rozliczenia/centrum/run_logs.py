"""Logi Uruchomienia na komputerze taty (ADR 0015): jeden plik JSON na Uruchomienie procesu z Centrum.

Działanie po wyniku Uruchomienia (``runs.AfterRun``), w każdej drodze zakończenia i w obu trybach. Logi powstają
z tych samych faktów co karta Uruchomienia (``EndedRun``): wynik, Komunikaty z kodami, podsumowanie, etapy, ślad
wywołań Zatrzymania, a z ostatniego snapshotu projekcji postępu (``EndedRun.snapshot``) Przetworzenia Szablonów
pracownika i liczba problemów. Środowisko to system, Python i pliki procesu z Diagnozy z rozmiarem i atrybutem OneDrive.
Z podsumowania silnika Przebiegu rozliczeń jest też liczba wyczyszczonych Ilości tylko dla INEA, której karta nie
pokazuje (ADR 0018), a z podsumowania Uporządkowania INTERMAX jego Wpisy urządzenia i czynności INTERMAX (ADR 0019):
wiersze i operatorzy, bez innej treści wierszy. Z podsumowania Wyceny w efenix jest ślad każdego zlecenia (``LoggedOrder``):
wiersz Pliku zbiorczego, wynik z kodem Komunikatu, ilości z pliku po kodach pozycji, ``Kwota`` (AU) i działania okna efenix
z czasami, ilościami Emmetta, wpisanymi i kwotami, bez numeru zlecenia, adresu, loginu Wykonawcy i treści stron efenix.
Zatrzymanie okna efenix (``efenix_pricing.PricingStopped``) daje ślad zleceń sprzed niego i ``LoggedWindowStop``:
przyczynę techniczną z zamkniętej listy, wiersz i miejsce zlecenia w przebiegu oraz jego działania aż do tego, które się
nie udało; a Zatrzymanie „do Maksa” z przyczyną w wyjątku ma ślad wywołań z łańcuchem przyczyn.
Logi nie mają treści komórek: żadne pole nie niesie Wiersza danych, a pliki mają tylko nazwę, nigdy pełną ścieżkę.
Skrypt dla maszyn nie ma działań po wyniku, więc Logów nie tworzy.

Plik leży w katalogu Logów obok dziennika Centrum, poza Gitem i OneDrive, bez rotacji. Nazwa to czas startu (UTC),
klucz procesu i identyfikator Uruchomienia, więc jest jedna na Uruchomienie i układa się chronologicznie. Zapis jest
atomowy; nieudany wychodzi z ``run_ended``, a ``RunHost.after`` zapisuje w dzienniku tylko jego typ, bez zmiany
wyniku i bez Komunikatu.

Te same Logi idą przez kolejkę Skrzynki Zgłoszeń (``Outbox``) do issue okresu z etykietą ``logi-uruchomienia``,
także zamkniętego: każde Uruchomienie to komentarz z podsumowaniem w Markdown (``summary_markdown``) i pełnym JSON
w zwijanym bloku, a JSON ponad limit komentarza idzie w kolejnych częściach, które sklejone dają tekst pliku.

Diagnoza Zatrzymania dopisuje się do Logów swojego Uruchomienia (``RunLogs.diagnosed``): ten sam plik dostaje pole
``diagnosis``, a issue okresu kolejny komentarz z całymi Logami, więc najnowszy komentarz Uruchomienia to zawsze jego
plik. Diagnoza z tym samym wynikiem co ostatnio dopisana (``LoggedDiagnosis.same_result``) nie zmienia niczego: po
nieoczekiwanym wyjątku karta zaczyna Diagnozę sama przy każdym pokazaniu, a Maks potrzebuje tylko zmiany wyniku.
Diagnozę ma tylko ostatnie Uruchomienie tej pracy Centrum, więc w pamięci zostają tylko jego Logi; Diagnoza,
w której trakcie skończyło się następne Uruchomienie, nie dopisuje się nigdzie.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import cache
from pathlib import Path
import platform
import threading
from typing import Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict

from rozliczenia.call_trace import CallTrace
from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.diagnosis import CheckState, Diagnosis
from rozliczenia.centrum.outbox import Outbox, PeriodThread, Post
from rozliczenia.centrum.report_box import Label
from rozliczenia.centrum.runs import EndedRun, Ending
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.version import short_commit
from rozliczenia.domain import SettlementSummary, WorkerStatus
from rozliczenia.efenix_pricing import (
    BrowserFailure,
    Closed,
    ElementCount,
    EmmettWarning,
    LoginSign,
    MissingPositions,
    OrderError,
    OrderResult,
    OtherShape,
    PagePart,
    PricingStopped,
    PricingSummary,
    Ready,
    StoppedOrder,
    WindowCause,
)
from rozliczenia.efenix_positions import file_quantities
from rozliczenia.efenix_trace import Action, TraceStep
from rozliczenia.intermax_ordering import OrderingSummary
from rozliczenia.message import Message
from rozliczenia.period_folder import PeriodFolderInaccessible

RUN_LOGS_DIRECTORY: Final = "uruchomienia"
LABEL: Final[Label] = "logi-uruchomienia"

ProcessFiles = Callable[[contract.ProcessKey, str], Sequence[Path]]
"""Pliki taty Uruchomienia procesu dla tokenu okresu, z Ustawieniami taty z chwili końca Uruchomienia."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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


class LoggedTemplate(_Record):
    """Przetworzenie Szablonu pracownika: Wykonawca, wynik, Wiersze danych i czas."""

    wykonawca: str
    outcome: WorkerStatus | Literal["failed"]
    rows: int
    duration_ms: int


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


class LoggedStep(_Record):
    """Działanie okna efenix przy zleceniu (``efenix_trace.TraceStep``): czas i to, co odpowiedział efenix."""

    action: Action
    duration_ms: int
    found: int | None
    execution_date: date | None
    amount: Decimal | None
    quantities: dict[str, int] | None
    position: str | None
    quantity: int | None
    accepted: bool | None

    @classmethod
    def of(cls, step: TraceStep) -> LoggedStep:
        return cls(
            action=step.action,
            duration_ms=step.duration_ms,
            found=step.found,
            execution_date=step.execution_date,
            amount=step.amount,
            quantities=None if step.quantities is None else dict(step.quantities),
            position=step.position,
            quantity=step.quantity,
            accepted=step.accepted,
        )


OrderOutcome = Literal["gotowe", "błąd", "ostrzeżenie Emmetta"]
"""Wynik zlecenia Wyceny w efenix w Logach Uruchomienia."""


class LoggedOrder(_Record):
    """Ślad zlecenia Wyceny w efenix: wiersz Pliku zbiorczego, wynik z kodem Komunikatu (``None`` przy gotowym),
    ilości z pliku po kodach pozycji (``None``, gdy nie dało się ich przepisać), ``Kwota`` (AU) i działania okna."""

    row: int
    outcome: OrderOutcome
    code: str | None
    file: dict[str, int] | None
    file_amount: Decimal
    steps: list[LoggedStep]

    @classmethod
    def all_of(cls, summary: PricingSummary) -> list[LoggedOrder]:
        """Ślad każdego zlecenia po kolei; kody Komunikatów idą w kolejności zleceń, które zostały tacie."""

        codes = iter([message.code for _result, message in summary.left_for_tata])
        return [
            cls._of(result, None if isinstance(result.outcome, Ready) else next(codes)) for result in summary.results
        ]

    @classmethod
    def _of(cls, result: OrderResult, code: str | None) -> LoggedOrder:
        file = file_quantities(result.order)
        outcome: OrderOutcome
        match result.outcome:
            case Ready():
                outcome = "gotowe"
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
    """Przyczyna techniczna Zatrzymania okna efenix z zamkniętej listy (``efenix_pricing.WindowCause``), bez treści strony
    i wyjątku: ``part`` to część strony (nazwa ``PagePart``, ``None`` poza stronami efenix), a ``what`` przyczyna z listy.

    ``positions``: kody pozycji (brakujące z przypisania kolumn albo pozycja, której dotyczy budowa). ``element`` i
    ``count``: selektor z kodu okna i ile razy jest na stronie. ``error_type`` i ``operation``: typ wyjątku Playwrighta i
    działanie przeglądarki (``None``: działanie bez nazwy).
    """

    part: str | None
    what: str
    positions: list[str] | None = None
    element: str | None = None
    count: int | None = None
    error_type: str | None = None
    operation: str | None = None

    @classmethod
    def of(cls, part: PagePart | None, cause: WindowCause) -> LoggedCause:
        name = None if part is None else part.name
        match cause:
            case MissingPositions(positions):
                return cls(part=name, what=_MISSING_POSITIONS, positions=list(positions))
            case ElementCount(selector, count):
                return cls(part=name, what=_ELEMENT_COUNT, element=selector, count=count)
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
            case _:
                assert_never(cause)


_MISSING_POSITIONS: Final = "strona zlecenia bez pozycji z przypisania kolumn"
_ELEMENT_COUNT: Final = "element strony nie występuje dokładnie raz"
_BROWSER_FAILURE: Final = "błąd przeglądarki w działaniu okna"


class LoggedWindowStop(_Record):
    """Zatrzymanie okna efenix w Wycenie w efenix: przyczyna techniczna i zlecenie, przy którym okno stanęło.

    ``row``: wiersz Pliku zbiorczego, ``order`` z ``orders``: miejsce zlecenia w przebiegu (od 1), ``steps``: udane
    działania okna przy nim, ``failed``: działanie, które się nie udało, z rodzajem i czasem. Przy Zatrzymaniu przed
    pierwszym zleceniem (otwarcie okna, logowanie) ``row``, ``order``, ``orders`` i ``failed`` są ``None``, a ``steps``
    puste; ``failed`` ``None`` przy zleceniu to strona bez pozycji z przypisania kolumn po ostatnim działaniu w ``steps``.
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


class Tool(_Record):
    wydanie: str | None
    """Numer Wydania (ADR 0014), którego tag w klonie wskazuje ``commit`` (``0.10.0``); ``None``, gdy nie da się go
    ustalić lokalnie: commit po Wydaniu, bez Gita albo bez commitu."""
    commit: str | None


class RunLog(_Record):
    """Logi jednego Uruchomienia procesu z Centrum; kształt tego modelu to schemat pliku JSON.

    ``duration_ms`` to Czas uruchomienia bez czekania na Decyzję taty; ``started_at`` i ``ended_at`` to zegar ścienny.
    ``issue_count``, ``templates`` i ``duration_ms`` są puste tylko wtedy, gdy sam rdzeń (``run_process``) rzucił wyjątek.
    """

    schema_version: Literal[1]
    run_id: str
    process: contract.ProcessKey
    mode: Literal["podgląd", "zapis"]
    period: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int | None
    tool: Tool
    result: contract.RunResult
    ending: Ending
    stop_kind: contract.StopKind | None
    issue_count: int | None
    messages: list[LoggedMessage]
    technical_notes: list[str]
    summary: contract.RunSummary | None
    phases: list[contract.PhaseProgress]
    templates: list[LoggedTemplate]
    inea_only_cleared: dict[str, int] | None = None
    """Ilości tylko dla INEA (ADR 0018): litera kolumny → liczba komórek z wartością, które Przebieg rozliczeń zostawił
    (w podglądzie: zostawiłby) puste w Rozliczeniach pracownika. ``None``: Przygotowanie, Przebieg bez podsumowania
    i pliki sprzed tego pola."""
    intermax_entries: LoggedEntries | None = None
    """Wpisy urządzenia i czynności INTERMAX (ADR 0019). ``None``: inne procesy, Uporządkowanie bez podsumowania
    i pliki sprzed tego pola."""
    efenix_orders: list[LoggedOrder] | None = None
    """Ślad każdego zlecenia Wyceny w efenix po kolei, a po Zatrzymaniu okna efenix każdego zlecenia sprzed niego.
    ``None``: inne procesy, Wycena w efenix bez podsumowania i bez Zatrzymania okna oraz pliki sprzed tego pola."""
    efenix_stop: LoggedWindowStop | None = None
    """Zatrzymanie okna efenix z przyczyną techniczną. ``None``: inne procesy, Wycena w efenix bez takiego Zatrzymania
    i pliki sprzed tego pola."""
    environment: Environment
    trace: CallTrace | None
    diagnosis: LoggedDiagnosis | None
    """Ostatnia Diagnoza tego Uruchomienia z nowym wynikiem; ``None``, dopóki tata jej nie uruchomił (pliki schematu 1 sprzed niej też)."""

    @classmethod
    def of(cls, run: EndedRun, *, tool: Tool, environment: Environment) -> RunLog:
        info, stopped, snapshot = run.info, run.stopped, run.snapshot
        engine_summary = None if run.shown is None else run.shown.engine_summary
        facts = None if stopped is None else stopped.stop.facts
        priced = engine_summary if isinstance(engine_summary, PricingSummary) else None
        if isinstance(facts, PricingStopped):
            priced = facts.summary
        return cls(
            schema_version=1,
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
            phases=run.progress.phases,
            templates=[]
            if snapshot is None
            else [
                LoggedTemplate(
                    wykonawca=template.worker_name,
                    outcome=template.outcome,
                    rows=template.rows,
                    duration_ms=template.duration_ms,
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
        )

    @property
    def file_name(self) -> str:
        """``20261023T140507Z-settlement-<run_id>.json``: start w UTC, klucz procesu, identyfikator Uruchomienia."""

        return f"{self.started_at:%Y%m%dT%H%M%SZ}-{self.process}-{self.run_id}.json"

    @property
    def text(self) -> str:
        """Treść pliku Logów; te same znaki idą do Skrzynki Zgłoszeń."""

        return self.model_dump_json(indent=2) + "\n"


def logi_post(record: RunLog) -> Post:
    """Logi do issue okresu w Skrzynce Zgłoszeń: podsumowanie, pod nim JSON w ``<details>``, w razie potrzeby w częściach."""

    period, run_id = record.period, record.run_id

    def frame(number: int, count: int, chunk: str) -> str:
        part = "" if count == 1 else f", część {number}/{count}"
        top = summary_markdown(record) if number == 1 else f"**Logi Uruchomienia** {run_id}{part}"
        return f"{top}\n\n<details><summary>Logi JSON{part}</summary>\n\n````json\n{chunk}\n````\n\n</details>\n"

    return Post.of(
        PeriodThread(
            label=LABEL,
            line=f"- Logi Uruchomienia okresu: {period}",
            closed="reuse",
            title=f"Logi Uruchomienia {period}",
        ),
        period=period,
        run_id=run_id,
        header=(
            f"Logi Uruchomień okresu {period} z Centrum rozliczeń taty. Każde Uruchomienie to komentarz: "
            "podsumowanie, a pod nim pełny JSON Logów. Długie Logi idą w kolejnych komentarzach „część k/n”."
        ),
        blocks=[record.text],
        frame=frame,
    )


def summary_markdown(record: RunLog) -> str:
    """Podsumowanie na górze komentarza Logów: proces, tryb, okres, wynik, czas, kody Komunikatów, Diagnoza i Wydanie."""

    commit = "nieznany" if record.tool.commit is None else short_commit(record.tool.commit)
    diagnosis = "" if record.diagnosis is None else f"- Diagnoza: {_diagnosis(record.diagnosis)}\n"
    return (
        f"**Logi Uruchomienia**: {declaration_of(record.process).title}, {record.mode}, okres {record.period}\n"
        "\n"
        f"- Wynik: {_result(record)}\n"
        f"- Czas: {_duration(record.duration_ms)}\n"
        f"- Komunikaty: {_codes(record.messages)}\n"
        f"{diagnosis}"
        f"- Wydanie: {record.tool.wydanie or 'brak'}, commit {commit}\n"
        f"- Uruchomienie: {record.run_id}, start {record.started_at:%Y-%m-%d %H:%M:%S} UTC"
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
            return record.result
        case "stop" | "declined":
            return f"{record.result}, {_stop(record.stop_kind)}"
        case "unexpected":
            return f"{record.result}, nieoczekiwany wyjątek"
        case "after_engine":
            return f"{record.result}, błąd po zakończeniu silnika"
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
    ) -> None:
        self._directory = directory
        self._outbox = outbox
        self._commit = commit
        self._wydanie = wydanie
        self._files = files
        self._cloud = cloud_files
        self._lock = threading.Lock()
        self._last: RunLog | None = None  # Logi ostatniego Uruchomienia tak, jak ostatnio poszły do pliku i Skrzynki

    def run_ended(self, run: EndedRun) -> None:
        commit = self._commit()
        release = None if commit is None else self._wydanie(commit)
        tool = Tool(wydanie=None if release is None else release.version, commit=commit)
        record = RunLog.of(run, tool=tool, environment=self._environment(run))
        with self._lock:
            self._last = record
        self._keep(record)

    def link(self, run_id: str) -> str | None:
        """Adres komentarza Logów Uruchomienia ``run_id``, który Skrzynka przyjęła w tej pracy Centrum; ``None``: jeszcze żaden.

        Każdy komentarz Logów Uruchomienia ma całe Logi, więc adres po Diagnozie też prowadzi do pełnych Logów.
        """

        return self._outbox.delivered(run_id, LABEL)

    def diagnosed(self, run_id: str, diagnosis: Diagnosis) -> None:
        """Dopisuje Diagnozę do Logów Uruchomienia ``run_id``: do pliku i jako kolejny komentarz w issue okresu.

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
        """Plik Logów (nowy albo nadpisany) i komentarz w issue okresu z tymi samymi znakami."""

        try:
            replace_atomically(self._directory / record.file_name, record.text)
        finally:
            # Katalog Logów, który nie przyjął pliku, nie zatrzymuje Logów w drodze do Maksa.
            self._outbox.post(logi_post(record))

    def _environment(self, run: EndedRun) -> Environment:
        try:
            paths = self._files(run.info.process, run.info.period)
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
