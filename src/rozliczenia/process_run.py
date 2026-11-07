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

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
import time
from types import MappingProxyType
from typing import Any, Generic, Literal, Protocol, TypeVar

from .call_trace import CallTrace
from .decision import Conversation, Decision, Declined, EngineConversation
from .domain import ProgressEvent, ProgressObserver, ProgressPhase, StopKind
from .message import Message, StopError
from .progress import PhaseState, ProgressProjection, ProgressSnapshot
from .telemetry import CompletedResult, MetricsStore, RecordedStop, metric_record
from .write_routes import RouteCounts

__all__ = [
    "Finished",
    "Interlocutor",
    "Outcome",
    "Process",
    "ProcessInputs",
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


InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")
ViewT = TypeVar("ViewT")


class Interlocutor(Conversation, Protocol):
    """Rozmówca Uruchomienia procesu: Decyzja taty w trakcie silnika i podgląd postępu.

    Podgląd dostaje wyłącznie niemutowalne snapshoty jedynej projekcji postępu
    (ADR 0002): pusty na starcie, potem po każdym Zdarzeniu przebiegu. Wyjątek z
    ``show_progress`` odłącza go na resztę Uruchomienia bez wpływu na wynik.
    """

    def show_progress(self, snapshot: ProgressSnapshot) -> None: ...


@dataclass(frozen=True)
class Stop:
    """Zatrzymanie Uruchomienia procesu; zawsze z Komunikatem z katalogu procesu (``message``).

    ``stop``: własne zatrzymanie procesu (``StopError``) z jego Komunikatem.
    ``declined``: Zatrzymanie po odmowie w Decyzji taty (``Declined``), z Komunikatem procesu.
    ``unexpected``: inny wyjątek przed końcem silnika, z Komunikatem
    ``Process.unexpected_failure``. ``after_engine``: silnik skończył, ale nie
    dało się zbudować podsumowania, z Komunikatem ``Process.plan_not_shown``
    (DRY-RUN) albo ``Process.summary_not_shown`` (RUN).

    ``trace``: ślad wywołań dla Zgłoszenia do Maksa i Logów Uruchomienia:
    nieoczekiwanego wyjątku (``unexpected``, ``after_engine``) i każdego
    własnego zatrzymania, które ma przyczynę w wyjątku (``StopError`` z
    ``__cause__``), także dla taty, z łańcuchem przyczyn (#976). ``facts``: fakty Zatrzymania procesu
    dla Logów Uruchomienia (``StopError.facts``). Oba nie należą do tożsamości
    Zatrzymania i nie trafiają do dziennika ani metryk.
    """

    kind: Literal["stop", "declined", "unexpected", "after_engine"]
    message: Message
    trace: CallTrace | None = field(default=None, compare=False, repr=False)
    facts: object = field(default=None, compare=False, repr=False)

    @property
    def stop_kind(self) -> StopKind:
        """Rodzaj Zatrzymania, ten sam w metrykach i w Centrum.

        „Do Maksa”: Komunikat bezwarunkowo każe przekazać go osobie utrzymującej
        narzędzie (``Message.reports_to_maintainer``) albo zakończenie nie jest
        własnym zatrzymaniem procesu (nieoczekiwany wyjątek, błąd po silniku).
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
class Process(Generic[InputsT, SummaryT]):
    """Opis procesu dla rdzenia Uruchomienia procesu, wspólny dla każdego rozmówcy.

    ``name`` to nazwa procesu z GLOSSARY. ``execute`` wywołuje silnik z
    gotowym wejściem procesu.
    Zatrzymanie zgłasza ``StopError`` z Komunikatem z katalogu procesu.
    Komunikaty zakończeń z tego samego katalogu (``unexpected_failure``,
    ``plan_not_shown``, ``summary_not_shown``) rdzeń dołącza do każdego innego
    zatrzymania, więc żaden rozmówca nie dobiera treści sam. ``finished`` to
    czysta funkcja faktów zakończonego procesu z jego wejścia i podsumowania.
    ``metrics_path`` to domyślny plik metryk procesu.
    """

    name: str
    counter_names: frozenset[str]
    metrics_path: Callable[[], Path]
    metrics_failure_tail: str
    execute: Callable[[InputsT, ProgressObserver, EngineConversation], SummaryT]
    finished: Callable[[InputsT, SummaryT], Finished]
    unexpected_failure: Message
    plan_not_shown: Message
    summary_not_shown: Message


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


class _Clock:
    """``Czas uruchomienia`` od startu silnika, bez czasu decyzji taty."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self.started = clock()
        self.paused_s = 0.0

    def elapsed_ms(self) -> int:
        return max(0, round((self._clock() - self.started - self.paused_s) * 1000))

    @contextmanager
    def paused(self) -> Iterator[None]:
        paused_at = self._clock()
        try:
            yield
        finally:
            self.paused_s += self._clock() - paused_at


class _ClockedConversation:
    """Rozmowa rozmówcy dla silnika; czas czekania na Decyzję taty i na tatę poza nią wstrzymuje zegar rdzenia."""

    def __init__(self, interlocutor: Interlocutor, clock: _Clock) -> None:
        self._interlocutor = interlocutor
        self._clock = clock

    @property
    def continue_hint(self) -> str:
        return self._interlocutor.continue_hint

    def confirm(self, decision: Decision) -> bool:
        with self._clock.paused():
            return self._interlocutor.confirm(decision)

    def waiting(self) -> AbstractContextManager[None]:
        return self._clock.paused()


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


def _stop_from(error: Exception, process: Process[Any, Any]) -> Stop:
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
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    observation: _Observation,
    conversation: EngineConversation,
    view: Callable[[InputsT, SummaryT], ViewT],
) -> _DeferredSummary[ViewT] | Stop:
    """Silnik z podglądem jako obserwatorem; po sukcesie zwraca odroczoną budowę podsumowania i widoku."""

    try:
        summary = process.execute(inputs, observation, conversation)
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
    process: Process[InputsT, SummaryT],
    inputs: InputsT,
    interlocutor: Interlocutor,
    *,
    view: Callable[[InputsT, SummaryT], ViewT],
    metrics_path: Path,
    clock: Callable[[], float] = time.perf_counter,
) -> Outcome[ViewT]:
    """Prowadzi jedno Uruchomienie procesu z gotowym wejściem procesu i dowolnym rozmówcą.

    ``view`` robi z podsumowania silnika widok rozmówcy; jej wyjątek to błąd po
    silniku z Komunikatem zakończenia procesu. Rekord metryk trafia do
    ``metrics_path``; rozmówca renderuje ``Outcome`` sam. ``clock`` to zegar
    w sekundach, z którego rdzeń liczy ``Czas uruchomienia``.
    """

    dry_run = inputs.dry_run
    mode = "DRY-RUN" if dry_run else "RUN"
    started_at = datetime.now(timezone.utc).isoformat()
    run_clock = _Clock(clock)
    observation = _Observation(interlocutor)
    observation.start()

    engine_outcome = _run_engine(process, inputs, observation, _ClockedConversation(interlocutor, run_clock), view)
    total_duration_ms = run_clock.elapsed_ms()
    ending, shown = _build_summary(
        engine_outcome, not_shown=process.plan_not_shown if dry_run else process.summary_not_shown
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
        counters=finished.counters if finished else dict.fromkeys(process.counter_names, 0),
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
