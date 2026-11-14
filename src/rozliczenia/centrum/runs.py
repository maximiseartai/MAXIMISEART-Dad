"""Uruchomienia procesu z Centrum rozliczeń: jedno naraz, w wątku roboczym, z podglądem przez SSE.

Centrum jest rozmówcą rdzenia Uruchomienia procesu (``process_run``) i
podglądem projekcji postępu (ADR 0002, ADR 0004). Ten moduł nie zna żadnego
procesu: proces podaje gotowe ``PreparedRun``, a moduł
prowadzi z nim rdzeń i publikuje widoki dla przeglądarki. Widok podsumowania robi rdzeń
w swojej osłonie, więc jego awaria to błąd po silniku z Komunikatem z katalogu
procesu, ten sam wynik co w metrykach. Zatrzymania, ostrzeżenia i decyzja taty
przechodzą jako Komunikaty w trzech częściach.

Każda zmiana stanu to nowy niemutowalny widok (``runs_contract.RunView``) z kolejnym
numerem. Strumień SSE wysyła najpierw bieżący widok, potem każdy kolejny, więc
ponowne podłączenie (odświeżenie, nowa karta) zaczyna od bieżącego stanu.
Decyzja taty czeka w stanie ``awaiting_decision``, aż przyjdzie przez API.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, Protocol

import anyio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT, Refusal, Retry
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_start import PeriodStarts
from rozliczenia.centrum.process_kind import PreparedRun, startable
from rozliczenia.centrum.settings.owner import SettingsSnapshot
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.centrum.run_view import ProcessView, Shown
from rozliczenia.centrum.stops import StoppedRun, Stops
from rozliczenia.centrum.threads import Signal, Threading
from rozliczenia.call_trace import CallTrace
from rozliczenia.decision import Decision
from rozliczenia.input_copy import InputCopy
from rozliczenia.message import Message
from rozliczenia.process_run import Finished, Outcome, RunResult, Stop
from rozliczenia.progress import ProgressProjection, ProgressSnapshot
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.wall_clock import utc_now

_STREAM_POLL_SECONDS: Final = 0.05
_KEEPALIVE_SECONDS: Final = 15.0
_RECONNECT_MS: Final = 1000
RUN_THREAD_PREFIX: Final = "uruchomienie-"
_RESULT_NOT_SHOWN: Final = Message.to_maintainer(
    code="BLAD_WYNIKU",
    what="Nie udało się pokazać wyniku Uruchomienia procesu.",
    where="Centrum rozliczeń",
    check="Folder okresu",
)
"""Ostatnia siatka adaptera: wyniku nie dało się pokazać, choć rdzeń zapisał już metryki."""

_STOP_HEADLINES: Final[Mapping[runs_contract.StopKind, str]] = {
    "for_tata": "Do poprawy",
    "repeated": "Do poprawy",
    "for_maks": "Błąd",
    "declined": "Przerwano",
}
"""Tytuł wyniku przy Zatrzymaniu: tata poprawia sam, błąd do Maksa albo jego własna odmowa w Decyzji taty."""

_NOT_YOUR_FILES: Final = "To nie wynika z Twoich plików."


def stop_note(kind: runs_contract.StopKind | None) -> str | None:
    """Zdanie pod tytułem Zatrzymania na karcie."""

    return _NOT_YOUR_FILES if kind == "for_maks" else None

Ending = runs_contract.Ending


def verdict(
    *,
    ending: Ending,
    stop_kind: runs_contract.StopKind | None,
    result: RunResult,
    dry_run: bool,
    view: ProcessView[Any],
) -> tuple[str, runs_contract.NextAction]:
    """Tytuł wyniku i jedyna akcja po nim: jedna reguła dla karty na żywo i karty z Logów Uruchomienia.

    Po błędzie podsumowania przy zapisie (``after_engine``) pliki już są, więc karta nie proponuje ponownego
    Uruchomienia, tylko akcję po wyniku z zapisem.
    """

    if stop_kind is not None:
        return _STOP_HEADLINES[stop_kind], view.result_action if ending == "after_engine" and not dry_run else "rerun"
    if result == "WYMAGA_SPRAWDZENIA":
        if dry_run:
            return "Podgląd wymaga sprawdzenia · nic nie zapisano", "rerun"
        return f"{view.done} · wymaga sprawdzenia", view.result_action
    return ("Podgląd gotowy · nic nie zapisano", "run") if dry_run else (view.done, view.result_action)


@dataclass(frozen=True)
class EndedRun:
    """Zakończone Uruchomienie procesu z Centrum, każdą drogą: fakty wyliczone raz, z których czyta karta i działania po wyniku."""

    info: runs_contract.RunInfo
    core: Outcome[Shown[Any]] | None
    """Wynik rdzenia tak, jak go pokazuje Centrum; ``None``, gdy rdzeń nie oddał wyniku.

    Po błędzie samego adaptera (ostatnia siatka) ma jej Zatrzymanie, bez widoku i bez uwag technicznych,
    a czas i snapshot projekcji postępu zostają z rdzenia.
    """
    stopped: StoppedRun | None
    """Zatrzymanie, także ostatniej siatki adaptera; ``None``, gdy proces się zakończył."""
    progress: runs_contract.Progress
    """Postęp z karty: ostatni widok projekcji, który dostała przeglądarka."""
    started_at: datetime
    ended_at: datetime
    input_copy: InputCopy | None = None
    """Kopia wejścia Uruchomienia (``PreparedRun.input_copy``) z tym, co czytniki przeczytały do jego końca."""
    settings: SettingsSnapshot | None = None
    """Migawka Ustawień Centrum ze startu Uruchomienia (``PreparedRun.settings``), z której Logi biorą pliki procesu."""
    quantity_rules: QuantityRules | None = None
    """Reguły ilości ze startu Uruchomienia (``PreparedRun.quantity_rules``), które Logi zapisują dla odtworzenia."""
    start_warnings: tuple[Message, ...] = ()
    """Ostrzeżenia ze startu (``Start.warnings``): proces biegł na ostatniej dobrej Liście Wykonawców."""

    @classmethod
    def of(
        cls,
        prepared: PreparedRun[Any, Any],
        core: Outcome[Shown[Any]] | None,
        *,
        info: runs_contract.RunInfo,
        stopped: StoppedRun | None,
        progress: runs_contract.Progress,
        started_at: datetime,
    ) -> EndedRun:
        return cls(
            info, core, stopped, progress, started_at, utc_now(), prepared.input_copy, prepared.settings,
            prepared.quantity_rules, prepared.warnings
        )

    @property
    def result(self) -> RunResult:
        return "BLAD_KRYTYCZNY" if self.core is None else self.core.result

    @property
    def shown(self) -> Shown[Any] | None:
        """Wynik zakończonego procesu; ``None`` przy każdym Zatrzymaniu."""

        return None if self.core is None else self.core.view

    @property
    def technical_notes(self) -> tuple[str, ...]:
        return () if self.core is None else self.core.technical_notes

    @property
    def snapshot(self) -> ProgressSnapshot | None:
        return None if self.core is None else self.core.progress

    @property
    def duration_ms(self) -> int | None:
        return None if self.core is None else self.core.total_duration_ms

    @property
    def files_unchanged(self) -> bool:
        """Pliki taty bez zmian; gdy rdzeń nie oddał wyniku, wiadomo to tylko o podglądzie bez zapisu."""

        return self.info.mode.dry_run if self.core is None else self.core.files_unchanged

    @property
    def ending(self) -> Ending:
        return "finished" if self.stopped is None else self.stopped.stop.kind

    @property
    def stops(self) -> tuple[Message, ...]:
        return () if self.stopped is None else (self.stopped.stop.message,)

    @property
    def result_warnings(self) -> tuple[Message, ...]:
        """Ostrzeżenia wyniku; przy Zatrzymaniu żadnych."""

        return () if self.shown is None else tuple(self.shown.warnings)

    @property
    def warnings(self) -> tuple[Message, ...]:
        """Ostrzeżenia ze startu, potem ostrzeżenia wyniku."""

        return self.start_warnings + self.result_warnings

    def card(self, view: ProcessView[Any]) -> runs_contract.RunOutcome:
        stopped = self.stopped
        kind = None if stopped is None else stopped.kind
        headline, next_action = verdict(
            ending=self.ending,
            stop_kind=kind,
            result=self.result,
            dry_run=self.info.mode.dry_run,
            view=view,
        )
        return runs_contract.RunOutcome(
            result=self.result,
            headline=headline,
            ending=self.ending,
            next_action=next_action,
            stop_kind=kind,
            stop_note=stop_note(kind),
            diagnosis=None if stopped is None else stopped.offer,
            report=None if stopped is None or stopped.report is None else stopped.report.state,
            stops=[common_contract.Message.of(message) for message in self.stops],
            warnings=[common_contract.Message.of(message) for message in self.warnings],
            technical_notes=list(self.technical_notes),
            summary=None if self.shown is None else self.shown.summary,
            files_unchanged=self.files_unchanged,
            opens=None if stopped is None else stopped.stop.message.dad_file,
            order_notes=None if self.shown is None else self.shown.notes,
            collective_file_prepared=view.collective_file_prepared(ending=self.ending, dry_run=self.info.mode.dry_run),
        )


class AfterRun(Protocol):
    def run_ended(self, run: EndedRun) -> None:
        """Na wątku Uruchomienia, przed końcem Uruchomienia: tylko lokalny zapis w milisekundach, bez sieci.

        Wyjątek nie zmienia wyniku: ``RunHost.after`` zapisuje jego typ w dzienniku i woła następne działanie.
        """
        ...


class RunLogsKeeper(AfterRun, Protocol):
    """Logi Uruchomienia (``run_comments.RunComments``): start każdego Uruchomienia i pierwsze działanie po wyniku."""

    def run_started(self, info: runs_contract.RunInfo, started_at: datetime) -> None:
        """Start Uruchomienia, zanim ruszy jego wątek; wyjątek ``RunHost.start`` zapisuje tylko w dzienniku."""
        ...


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    To samo miejsce „jedno naraz” zajmuje Aktualizacja narzędzia (``begin_update``
    do ``end_update``): w jej trakcie start Uruchomienia jest odrzucony, a w trakcie
    Uruchomienia ona. Tak samo przywrócenie Kopii INTERMAX (``begin_restore`` do
    ``end_restore``): podmienia INTERMAX, więc nie biegnie obok Uporządkowania INTERMAX.
    ``shutdown_refusal()`` odmawia zamknięcia serwera także wtedy, gdy Uruchomienie czeka na decyzję taty.
    Zatrzymanie zakończonego Uruchomienia przejmuje jego właściciel (``stops``); Diagnoza i „Wyślij do Maksa” idą tylko
    do Zatrzymania bieżącego Uruchomienia, a nowy stan Zgłoszenia trafia na jego kartę.
    Działania po wyniku biegną przed końcem Uruchomienia, więc przyjęte zamknięcie
    Centrum albo Aktualizacja narzędzia ich nie przerwie: najpierw Logi Uruchomienia
    (``logs``, #871), potem ``after_run``. Pierwszy widok niesie
    ``previous``, ostatnie Uruchomienie sprzed startu Centrum. Start następnego Uruchomienia zostawia wynik
    poprzedniego w widokach, więc karta, która czyta strumień co chwilę, dostaje wynik każdego Uruchomienia.

    ``threads`` daje blokadę, Event decyzji taty i wątek Uruchomienia (``threads.Threading``), a ``created`` dostaje
    każdy nowy ``Run`` pod blokadą, zanim zajmie miejsce „jedno naraz”, z ostatnim widokiem sprzed jego startu (tym, co
    karta mogła już przeczytać). Inne niż domyślne (moduł ``threading`` i nic) daje tylko wyrocznia
    ``verify-jedno-uruchomienie-naraz``, która decyduje o każdym kroku.
    """

    def __init__(
        self,
        log: CentrumLog,
        centrum_runs: CentrumRuns,
        stops: Stops,
        *,
        previous: runs_contract.PastRun | None,
        logs: RunLogsKeeper,
        after_run: Sequence[AfterRun],
        threads: Threading = threading,
        created: Callable[[Run, runs_contract.RunEvent], None] = lambda _run, _last: None,
    ) -> None:
        self._log = log
        self._centrum_runs = centrum_runs
        self._stops = stops
        self._run_started = logs.run_started
        self._after_run = (logs, *after_run)
        self._threads = threads
        self._created = created
        self._lock = threads.Lock()
        self._sequence = 0
        first = runs_contract.RunIdle(state="idle", previous=previous)
        self._events: list[runs_contract.RunEvent] = [runs_contract.RunEvent(sequence=0, view=first)]
        self._run: Run | None = None
        self._updating = False
        self._restoring = False
        self._closing = False

    def shutdown_refusal(self) -> Refusal | None:
        """Dlaczego teraz nie można zamknąć Centrum (``Shutdown.refuse_while``); ``None``, gdy nic nie trwa.

        ``None`` przyjmuje zamknięcie w tej samej blokadzie: kolejne Uruchomienie ani aktualizacja już nie wystartują.
        """

        with self._lock:
            busy = self._busy_locked("shutdown")
            if busy is None:
                self._closing = True
            return busy

    def begin_update(self) -> None:
        """Zajmuje miejsce „jedno naraz” na Aktualizację narzędzia; ``Refusal``, gdy jest zajęte."""

        with self._lock:
            if self._closing:
                raise refusal.closing("update")
            if self._updating:
                raise refusal.update_in_progress()
            busy = self._busy_locked("update")
            if busy is not None:
                raise busy
            self._updating = True

    def end_update(self) -> None:
        with self._lock:
            self._updating = False

    def begin_restore(self) -> None:
        """Zajmuje miejsce „jedno naraz” na przywrócenie Kopii INTERMAX; ``Refusal``, gdy jest zajęte."""

        with self._lock:
            if self._closing:
                raise refusal.closing("restore")
            busy = self._busy_locked("restore")
            if busy is not None:
                raise busy
            self._restoring = True

    def end_restore(self) -> None:
        with self._lock:
            self._restoring = False

    def _busy_locked(self, then: Retry) -> Refusal | None:
        """Odmowa z tym, co teraz trwa, i prośbą, żeby poczekać i ``then``; ``None``, gdy nic."""

        if self._updating:
            return refusal.updating(then)
        if self._restoring:
            return refusal.restoring(then)
        run = self._run
        if run is None or run.ended:
            return None
        return refusal.running(run.info.title, run.info.period, then)

    def current(self) -> runs_contract.RunEvent:
        with self._lock:
            return self._events[-1]

    def events_after(self, sequence: int) -> list[runs_contract.RunEvent]:
        with self._lock:
            return [event for event in self._events if event.sequence > sequence]

    def start(self, prepared: PreparedRun[Any, Any]) -> runs_contract.RunView:
        with self._lock:
            if self._closing:
                raise refusal.closing("start")
            if self._updating:
                raise refusal.updating("start")
            if self._restoring:
                raise refusal.restoring("start")
            if self._run is not None and not self._run.ended:
                running = self._run.info
                raise refusal.run_in_progress(running.title, running.period)
            run = Run(self, prepared, self._stops, self._threads)
            self._created(run, self._events[-1])
            self._run = run
            # Wynik poprzedniego Uruchomienia zostaje dla karty, która go jeszcze nie odczytała (#723).
            self._events = self._events[-1:]
            self._publish_locked(run.running_view())
            view = self._events[-1].view
        self._log.run_started(process=prepared.kind.key, mode=run.info.mode, period=prepared.period)
        try:
            self._run_started(run.info, run.started_at)
        except Exception as failure:  # zapis startu na dysku nie może zmienić Uruchomienia
            self._log.unexpected_failure(failure, where="start Uruchomienia procesu")
        self._threads.Thread(target=run.work, name=f"{RUN_THREAD_PREFIX}{run.info.id}", daemon=True).start()
        return view

    def decide(self, run_id: str, answer: runs_contract.DecisionAnswer) -> runs_contract.RunView:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise refusal.unknown_run()
            if not run.awaiting_decision:
                raise refusal.not_awaiting_decision()
            run.answer(answer.answer == "continue")
            self._publish_locked(run.running_view())
            return self._events[-1].view

    def diagnose(self, run_id: str) -> diagnosis_contract.Diagnosis:
        return self._stops.diagnose(self._stopped(run_id))

    def send_report(self, run_id: str) -> diagnosis_contract.ReportState:
        return self._stops.send(self._stopped(run_id))

    def _stopped(self, run_id: str) -> StoppedRun:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise refusal.unknown_run()
            stopped = run.stopped
        if not run.ended or stopped is None:
            raise refusal.no_diagnosis()
        return stopped

    def remember(self, prepared: PreparedRun[Any, Any], run_id: str, since: datetime) -> None:
        self._centrum_runs.remember(prepared.kind.key, run_id, prepared.metrics, since, utc_now())

    def failed(self, failure: Exception) -> None:
        """Wyniku Uruchomienia nie dało się pokazać."""

        self._log.unexpected_failure(failure, where="wynik Uruchomienia procesu")

    def show_report(self, run_id: str, state: diagnosis_contract.ReportState) -> None:
        with self._lock:
            view = self._events[-1].view
            if isinstance(view, runs_contract.RunFinished) and view.run.id == run_id:
                result = view.result.model_copy(update={"report": state})
                self._publish_locked(view.model_copy(update={"result": result}))

    def after(self, run: EndedRun) -> None:
        for action in self._after_run:
            try:
                action.run_ended(run)
            except Exception as failure:  # działanie po wyniku nie może zmienić wyniku Uruchomienia
                self._log.unexpected_failure(failure, where="po wyniku Uruchomienia procesu")

    def finished(self, run: EndedRun) -> None:
        info = run.info
        self._log.run_finished(
            process=info.process,
            mode=info.mode,
            period=info.period,
            result=run.result,
            ending=run.ending,
        )

    def end(self, run: Run, result: runs_contract.RunFinished) -> None:
        """Wynik Uruchomienia ``run`` na kartę i koniec Uruchomienia pod jedną blokadą.

        Start z drugiej karty, który czeka na koniec Uruchomienia, nie wejdzie między wynik a koniec (#723).
        """

        with self._lock:
            self._publish_locked(result)
            run.ended = True

    def publish(self, run: Run, view: runs_contract.RunView) -> None:
        with self._lock:
            if self._run is run:
                self._publish_locked(view)

    def _publish_locked(self, view: runs_contract.RunView) -> None:
        self._sequence += 1
        self._events.append(runs_contract.RunEvent(sequence=self._sequence, view=view))


class Run:
    """Jedno Uruchomienie procesu i jednocześnie jego rozmówca w rdzeniu (``Interlocutor``)."""

    def __init__(self, host: RunHost, prepared: PreparedRun[Any, Any], stops: Stops, threads: Threading) -> None:
        self._host = host
        self._prepared = startable(prepared)
        self._stops = stops
        self.info = prepared.info(uuid.uuid4().hex)
        self.started_at = utc_now()
        self._progress = prepared.progress_view(ProgressProjection().snapshot)
        self._stale = False
        self._decided: Signal = threads.Event()
        self._consent = False
        self.awaiting_decision = False
        self.ended = False
        self.stopped: StoppedRun | None = None

    def running_view(self) -> runs_contract.RunRunning:
        return runs_contract.RunRunning(
            state="running",
            run=self.info,
            progress=self._progress,
            progress_stale=self._stale,
        )

    def work(self) -> None:
        prepared = self._prepared
        core: Outcome[Shown[Any]] | None = None
        since = self.started_at
        try:
            core = startable(prepared).conduct(self)
            self._host.remember(prepared, self.info.id, since)
            ended = self._ended(core, None if isinstance(core.ending, Finished) else core.ending, since)
            result = ended.card(prepared.kind.view)
        except Exception as failure:
            self._host.failed(failure)
            stop = Stop("after_engine", _RESULT_NOT_SHOWN, CallTrace.of(failure))
            core = None if core is None else replace(core, ending=stop, view=None, technical_notes=())
            ended = self._ended(core, stop, since)
            result = ended.card(prepared.kind.view)
        self.stopped = ended.stopped
        self._host.after(ended)
        self._host.finished(ended)
        self._host.end(
            self,
            runs_contract.RunFinished(
                state="finished", run=self.info, progress=self._progress, progress_stale=self._stale, result=result
            ),
        )

    def _ended(self, core: Outcome[Shown[Any]] | None, stop: Stop | None, since: datetime) -> EndedRun:
        return EndedRun.of(
            self._prepared,
            core,
            info=self.info,
            stopped=self._stops.ended(self.info, stop, shown=self._show_report, settings=self._prepared.settings),
            progress=self._progress,
            started_at=since,
        )

    def _show_report(self, state: diagnosis_contract.ReportState) -> None:
        self._host.show_report(self.info.id, state)

    def answer(self, consent: bool) -> None:
        """Wywoływane przez ``RunHost.decide`` pod blokadą hosta."""

        self._consent = consent
        self.awaiting_decision = False
        self._decided.set()

    @property
    def continue_hint(self) -> str:
        return runs_contract.CONTINUE_HINT

    def confirm(self, decision: Decision) -> bool:
        self._decided.clear()
        self.awaiting_decision = True
        self._host.publish(
            self,
            runs_contract.RunAwaitingDecision(
                state="awaiting_decision", run=self.info, progress=self._progress, decision=_decision_view(decision)
            ),
        )
        self._decided.wait()
        return self._consent

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        try:
            progress = self._prepared.progress_view(snapshot)
        except Exception:
            self._stale = True
            self._host.publish(self, self.running_view())
            raise
        if progress != self._progress:
            self._progress = progress
            self._host.publish(self, self.running_view())


def _decision_view(decision: Decision) -> runs_contract.Decision:
    return runs_contract.Decision(
        question=decision.question,
        message=common_contract.Message.of(decision.message),
        counts=runs_contract.CountGroup(
            title=decision.counts_title,
            counts=[runs_contract.Count(label=label, count=count) for label, count in decision.counts],
        ),
    )


def _sse(event: runs_contract.RunEvent) -> str:
    return f"id: {event.sequence}\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(host: RunHost) -> AsyncIterator[str]:
    current = host.current()
    yield f"retry: {_RECONNECT_MS}\n" + _sse(current)
    seen = current.sequence
    idle = 0.0
    while True:
        await anyio.sleep(_STREAM_POLL_SECONDS)
        events = host.events_after(seen)
        for event in events:
            yield _sse(event)
            seen = event.sequence
        idle = 0.0 if events else idle + _STREAM_POLL_SECONDS
        if idle >= _KEEPALIVE_SECONDS:
            idle = 0.0
            yield ": trwa\n\n"


_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "Strumień SSE; każde pole `data` to `RunEvent` (JSON).", "model": runs_contract.RunEvent},
}


def runs_router(host: RunHost, starts: PeriodStarts) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.get("/setup", operation_id="getRunSetup")
    def setup() -> runs_contract.RunSetup:
        return starts.setup()

    @router.post("", operation_id="startRun", responses=NOT_FOUND_OR_CONFLICT)
    def start(request: runs_contract.RunRequest) -> runs_contract.RunView:
        return host.start(starts.prepare(request))

    @router.get("/current", operation_id="getCurrentRun")
    def current() -> runs_contract.RunView:
        return host.current().view

    @router.post("/{run_id}/decision", operation_id="decideRun", responses=NOT_FOUND_OR_CONFLICT)
    def decide(run_id: str, answer: runs_contract.DecisionAnswer) -> runs_contract.RunView:
        return host.decide(run_id, answer)

    @router.get("/events", operation_id="streamRunEvents", response_class=StreamingResponse, responses=_STREAM_RESPONSES)
    def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(host),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/{run_id}/diagnosis", operation_id="diagnoseRun", responses=NOT_FOUND_OR_CONFLICT)
    def run_diagnosis(run_id: str) -> diagnosis_contract.Diagnosis:
        return host.diagnose(run_id)

    @router.post("/{run_id}/report", operation_id="reportRun", responses=NOT_FOUND_OR_CONFLICT)
    def send_report(run_id: str) -> diagnosis_contract.ReportState:
        return host.send_report(run_id)

    return router

