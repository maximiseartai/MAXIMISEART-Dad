"""Uruchomienie procesu: rdzeń wspólny dla każdego rozmówcy.

Rdzeń (``run_process``) prowadzi Uruchomienie procesu od gotowego wejścia
procesu do wyniku: pomiar ``Czas uruchomienia`` bez czasu decyzji taty, jedną
projekcję postępu (ADR 0002) z odłączanym obserwatorem, przechwycenie każdego
wyjątku, widok podsumowania rozmówcy w tej samej osłonie, rekord metryk i
wynik jako strukturę (``Outcome``). Każde zakończenie to ``Finished`` albo
``Stop`` z Komunikatem z katalogu procesu. Rozmówca (``Interlocutor``)
pokazuje tacie Decyzję w trakcie silnika (``decision``), pokazuje postęp i sam
renderuje wynik. Decyzję składa proces, nie rozmówca. Proces
opisuje tylko to, co jest jego i wspólne dla każdego rozmówcy (``Process``).
Tekst wyjątku nigdy nie przechodzi przez ten seam: tata widzi wyłącznie
Komunikaty podane przez proces.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generic, Literal, Protocol, Self, TypeVar

from .call_trace import CallTrace
from .decision import Conversation, Decision, Declined
from .domain import ProgressEvent, ProgressObserver, ProgressPhase, StopKind
from .message import Message, StopError
from .progress import PhaseState, ProgressProjection, ProgressSnapshot
from .telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from .write_routes import RouteCounts
from .run_clock import RunClock

__all__ = [
    "Counter",
    "Finished",
    "Interlocutor",
    "Outcome",
    "Preview",
    "Process",
    "ProcessInputs",
    "ProcessSummary",
    "Stop",
    "run_process",
]

_DETACHED_OBSERVER_NOTE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."


class ProcessInputs(Protocol):
    """Wejście procesu znane rdzeniowi: okres do metryk i podglądu oraz tryb."""

    @property
    def period(self) -> str: ...

    @property
    def dry_run(self) -> bool: ...


class EngineContext(Protocol):
    """Kontekst Uruchomienia, jak go widzi rdzeń (``run_context.RunContext``): zegar Uruchomienia i ten sam kontekst z
    obserwatorem postępu i rozmową rdzenia. Rdzeń nie zna reszty kontekstu (plików taty i czytników), więc nie zależy od
    warstwy skoroszytu."""

    @property
    def clock(self) -> RunClock: ...

    def engaged(self, observer: ProgressObserver, conversation: Conversation) -> Self: ...


class ProcessSummary(Protocol):
    """Podsumowanie silnika, jak je widzi rdzeń: czasy etapów do rekordu metryk."""

    @property
    def phase_durations_ms(self) -> Mapping[ProgressPhase, int]: ...


InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT", bound=ProcessSummary)
ViewT = TypeVar("ViewT")
ContextT = TypeVar("ContextT", bound=EngineContext)


class Interlocutor(Conversation, Protocol):
    """Rozmówca Uruchomienia procesu: Decyzja taty w trakcie silnika i podgląd postępu.

    Podgląd dostaje wyłącznie niemutowalne snapshoty jedynej projekcji postępu
    (ADR 0002): pusty na starcie, potem po każdym Zdarzeniu przebiegu. Wyjątek z
    ``show_progress`` odłącza go na resztę Uruchomienia bez wpływu na wynik.
    """

    def show_progress(self, snapshot: ProgressSnapshot) -> None: ...


StopEnding = Literal["stop", "declined", "unexpected", "after_engine"]
"""Sposób zakończenia Uruchomienia procesu Zatrzymaniem (``Stop.kind``)."""


@dataclass(frozen=True)
class Stop:
    """Zatrzymanie Uruchomienia procesu; zawsze z Komunikatem z katalogu procesu (``message``).

    ``stop``: własne zatrzymanie procesu (``StopError``) z jego Komunikatem.
    ``declined``: Zatrzymanie po odmowie w Decyzji taty (``Declined``), z Komunikatem procesu.
    ``unexpected``: inny wyjątek przed końcem silnika, z Komunikatem
    ``Process.unexpected_failure``. ``after_engine``: silnik skończył, ale nie
    dało się zbudować podsumowania, z Komunikatem Podglądu bez zapisu procesu
    (``Process.preview``, DRY-RUN) albo ``Process.summary_not_shown`` (RUN).

    ``trace``: ślad wywołań dla Zgłoszenia do Maksa i Logów Uruchomienia:
    nieoczekiwanego wyjątku (``unexpected``, ``after_engine``) i każdego
    własnego zatrzymania, które ma przyczynę w wyjątku (``StopError`` z
    ``__cause__``), także dla taty, z łańcuchem przyczyn (#976). ``facts``: fakty Zatrzymania procesu
    dla Logów Uruchomienia (``StopError.facts``). Oba nie należą do tożsamości
    Zatrzymania i nie trafiają do dziennika ani metryk.
    """

    kind: StopEnding
    message: Message
    trace: CallTrace | None = field(default=None, compare=False, repr=False)
    facts: object = field(default=None, compare=False, repr=False)

    @property
    def stop_kind(self) -> StopKind:
        """Rodzaj Zatrzymania, ten sam w metrykach i w Centrum.

        „Do Maksa”: Komunikat ma Rodzaj „do Maksa” (``Message.reports_to_maintainer``)
        albo zakończenie nie jest własnym zatrzymaniem procesu (nieoczekiwany
        wyjątek, błąd po silniku).
        Każde inne, także po odmowie w Decyzji taty, jest „dla taty”.
        """

        own = self.kind in ("stop", "declined")
        return "for_maks" if not own or self.message.reports_to_maintainer else "for_tata"


@dataclass(frozen=True)
class Finished:
    """Fakty zakończonego procesu, te same w metrykach: wynik, liczniki, czasy etapów i drogi zapisu.

    Klucze ``counters`` to dokładnie ``Process.counter_names``. ``routes``: ile zapisanych plików każdego rodzaju
    powstało każdą drogą zapisu z Wzorca (ADR 0008); proces, który nie pisze z Wzorca, nie ma żadnej.
    """

    result: CompletedResult
    counters: Mapping[str, int]
    phase_durations_ms: Mapping[ProgressPhase, int]
    routes: RouteCounts = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Counter(Generic[SummaryT]):
    """Licznik rekordu metryk procesu: nazwa i jego wartość z podsumowania silnika."""

    name: str
    count: Callable[[SummaryT], int]


@dataclass(frozen=True)
class Preview:
    """Podgląd bez zapisu procesu: Komunikat, gdy planu nie da się pokazać."""

    plan_not_shown: Message


def _no_routes(_summary: object) -> RouteCounts:
    return MappingProxyType({})


@dataclass(frozen=True, kw_only=True)
class Process(Generic[InputsT, SummaryT, ContextT]):
    """Opis procesu dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.

    ``name`` to nazwa procesu z GLOSSARY. ``execute`` to sam silnik: dostaje
    gotowe wejście procesu i Kontekst Uruchomienia.
    Zatrzymanie zgłasza ``StopError`` z Komunikatem z katalogu procesu.
    Komunikaty zakończeń z tego samego katalogu (``unexpected_failure``,
    ``summary_not_shown``, ``preview``) rdzeń dołącza do każdego innego
    zatrzymania, więc żaden rozmówca nie dobiera treści sam. ``preview`` ``None``: proces bez Podglądu bez zapisu.
    Fakty zakończonego procesu (``finished``) to wynik z wejścia i podsumowania (``result``), liczniki
    (``counters``: jedyna definicja nazw i kolejności liczników rekordu metryk) i drogi zapisu z Wzorca (``routes``;
    proces, który nie pisze z Wzorca, zostawia domyślne: żadnej).
    ``metrics_path`` to domyślny plik metryk procesu.
    """

    name: str
    counters: tuple[Counter[SummaryT], ...]
    result: Callable[[InputsT, SummaryT], CompletedResult]
    routes: Callable[[SummaryT], RouteCounts] = _no_routes
    preview: Preview | None
    metrics_path: Callable[[], Path]
    metrics_failure_tail: str
    execute: Callable[[InputsT, ContextT], SummaryT]
    unexpected_failure: Message
    summary_not_shown: Message

    @property
    def counter_names(self) -> frozenset[str]:
        return frozenset(counter.name for counter in self.counters)

    def finished(self, inputs: InputsT, summary: SummaryT) -> Finished:
        return Finished(
            result=self.result(inputs, summary),
            counters={counter.name: counter.count(summary) for counter in self.counters},
            phase_durations_ms=summary.phase_durations_ms,
            routes=self.routes(summary),
        )


@dataclass(frozen=True)
class Outcome(Generic[ViewT]):
    """Wynik Uruchomienia procesu dla rozmówcy.

    ``view`` to widok podsumowania rozmówcy, gdy proces się zakończył
    (``Finished``); zrobiła go funkcja rozmówcy w osłonie rdzenia.
    ``technical_notes`` to uwagi techniczne: niezapisane metryki i odłączony
    podgląd postępu. ``metrics_saved``: rekord metryk trafił do pliku metryk.
    ``progress``: ostatni snapshot jedynej projekcji postępu (etapy, Przetworzenia
    Szablonów pracownika, liczba problemów); po odłączeniu podglądu ten z chwili odłączenia.
    ``files_unchanged``: Uruchomienie nie zmieniło plików taty, bo było podglądem bez zapisu albo skończyło
    się, zanim zaczęło się Zapisywanie. Po odłączeniu podglądu nie wiadomo, czy Zapisywanie się zaczęło,
    więc wtedy tylko podgląd.
    """

    ending: Finished | Stop
    view: ViewT | None
    total_duration_ms: int
    technical_notes: tuple[str, ...]
    metrics_saved: bool
    progress: ProgressSnapshot
    files_unchanged: bool

    @property
    def result(self) -> Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]:
        return self.ending.result if isinstance(self.ending, Finished) else "BLAD_KRYTYCZNY"


class _ClockedConversation:
    """Rozmowa rozmówcy dla silnika; czas czekania na Decyzję taty wstrzymuje zegar Uruchomienia."""

    def __init__(self, interlocutor: Interlocutor, clock: RunClock) -> None:
        self._interlocutor = interlocutor
        self._clock = clock

    @property
    def continue_hint(self) -> str:
        return self._interlocutor.continue_hint

    def confirm(self, decision: Decision) -> bool:
        with self._clock.hold():
            return self._interlocutor.confirm(decision)


class _Observation:
    """Obserwator silnika: jedna projekcja postępu i podgląd rozmówcy (ADR 0002).

    Wyjątek projekcji albo podglądu oznacza odłączenie: sekwencer etapów
    przestaje wysyłać zdarzenia, a rdzeń kończy jedną neutralną linią.
    """

    def __init__(self, interlocutor: Interlocutor) -> None:
        self._interlocutor = interlocutor
        self.projection = ProgressProjection()
        self.failed = False

    def start(self) -> None:
        try:
            self._interlocutor.show_progress(self.projection.snapshot)
        except Exception:  # noqa: BLE001 - ADR 0002: awaria podglądu odłącza go, rdzeń zgłasza to neutralną linią
            self.failed = True

    def __call__(self, event: ProgressEvent) -> None:
        try:
            snapshot = self.projection.update(event)
            if self.failed:
                raise RuntimeError("Progress view is detached.")
            self._interlocutor.show_progress(snapshot)
        except Exception:
            self.failed = True
            raise


def _stop_from(error: Exception, process: Process[Any, Any, Any]) -> Stop:
    """Własne zatrzymanie procesu z jego Komunikatem i faktami; każdy inny wyjątek to Komunikat nieoczekiwanego błędu.

    Własne zatrzymanie z przyczyną w wyjątku ma ślad wywołań z łańcuchem przyczyn, bo Maks ustala z niego, gdzie proces
    stanął, także przy Zatrzymaniu dla taty: Wycena w efenix, której okno nie wystartowało, mówi w nim, która droga
    startu zawiodła (``EfenixUnreachable``, ``BrowserNotStarted``) i z jakim wyjątkiem (#976).
    """

    if isinstance(error, Declined):
        return Stop("declined", error.message)
    if isinstance(error, StopError):
        stop = Stop("stop", error.message, facts=error.facts)
        if error.__cause__ is not None:
            return replace(stop, trace=CallTrace.of(error))
        return stop
    return Stop("unexpected", process.unexpected_failure, CallTrace.of(error))


# Budowa podsumowania i widoku rozmówcy odroczona do chwili po pomiarze Czasu
# uruchomienia, żeby jej czas się nie liczył.
_DeferredSummary = Callable[[], tuple[Finished, ViewT]]


def _run_engine(
    process: Process[InputsT, SummaryT, ContextT],
    inputs: InputsT,
    context: ContextT,
    view: Callable[[InputsT, SummaryT], ViewT],
) -> _DeferredSummary[ViewT] | Stop:
    """Silnik z kontekstem rdzenia; po sukcesie zwraca odroczoną budowę podsumowania i widoku."""

    try:
        summary = process.execute(inputs, context)
    except Exception as error:  # noqa: BLE001 - granica procesu: _stop_from rozróżnia błąd typowany od nieoczekiwanego
        return _stop_from(error, process)
    return lambda: (process.finished(inputs, summary), view(inputs, summary))


def _build_summary(
    engine_outcome: _DeferredSummary[ViewT] | Stop, *, not_shown: Message
) -> tuple[Finished | Stop, ViewT | None]:
    """Buduje odroczone podsumowanie i widok; błąd to zatrzymanie ``after_engine`` z Komunikatem ``not_shown``."""

    if isinstance(engine_outcome, Stop):
        return engine_outcome, None
    try:
        return engine_outcome()
    except Exception as error:  # noqa: BLE001 - granica procesu: kończy jako zatrzymanie "after_engine" w wyniku i metrykach
        return Stop("after_engine", not_shown, CallTrace.of(error)), None


def run_process(
    process: Process[InputsT, SummaryT, ContextT],
    inputs: InputsT,
    interlocutor: Interlocutor,
    *,
    view: Callable[[InputsT, SummaryT], ViewT],
    metrics_path: Path,
    context: ContextT,
) -> Outcome[ViewT]:
    """Prowadzi jedno Uruchomienie procesu z gotowym wejściem procesu i dowolnym rozmówcą.

    ``view`` robi z podsumowania silnika widok rozmówcy; jej wyjątek to błąd po
    silniku z Komunikatem zakończenia procesu. Rekord metryk trafia do
    ``metrics_path``; rozmówca renderuje ``Outcome`` sam. Silnik dostaje ``context`` z obserwatorem postępu i rozmową
    rozmówcy, a rdzeń liczy ``Czas uruchomienia`` zegarem kontekstu (``context.clock``).
    """

    dry_run = inputs.dry_run
    if dry_run and process.preview is None:
        raise ValueError(f"{process.name} has no Podgląd bez zapisu.")
    mode = "DRY-RUN" if dry_run else "RUN"
    started_at = datetime.now(timezone.utc).isoformat()
    clock = context.clock
    started = clock.now()
    observation = _Observation(interlocutor)
    observation.start()

    engine_outcome = _run_engine(
        process, inputs, context.engaged(observation, _ClockedConversation(interlocutor, clock)), view
    )
    total_duration_ms = max(0, round((clock.now() - started) * 1000))
    ending, shown = _build_summary(
        engine_outcome,
        not_shown=process.preview.plan_not_shown if process.preview is not None and dry_run else process.summary_not_shown,
    )

    finished = ending if isinstance(ending, Finished) else None
    record = metric_record(
        mode=mode,
        period=inputs.period,
        started_at=started_at,
        total_duration_ms=total_duration_ms,
        phase_durations_ms=(
            finished.phase_durations_ms if finished else observation.projection.snapshot.phase_durations_ms
        ),
        ending=(
            ending.result
            if isinstance(ending, Finished)
            else RecordedStop(kind=ending.stop_kind, code=ending.message.code)
        ),
        counters=finished.counters if finished else {counter.name: 0 for counter in process.counters},
        # Bez wyniku drogi zapisu są nieznane i rekord ma ich zero, tak jak liczników: także gdy zatrzymanie przyszło
        # dopiero przy pokazaniu wyniku, a pliki z Wzorca już powstały.
        routes=finished.routes if finished else {},
    )
    technical_notes: list[str] = []
    try:
        MetricsStore(metrics_path, process.counter_names).append(record)
        metrics_saved = True
    except (OSError, UnicodeError, ValueError):
        metrics_saved = False
        technical_notes.append(f"Ostrzeżenie: Nie zapisano metryk; {process.metrics_failure_tail}")
    if observation.failed:
        technical_notes.append(_DETACHED_OBSERVER_NOTE)
    progress = observation.projection.snapshot
    before_saving = not observation.failed and progress.phase_states[ProgressPhase.SAVING] is PhaseState.PENDING

    return Outcome(
        ending=ending,
        view=shown,
        total_duration_ms=total_duration_ms,
        technical_notes=tuple(technical_notes),
        metrics_saved=metrics_saved,
        progress=progress,
        files_unchanged=dry_run or before_saving,
    )
