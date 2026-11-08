"""Exhaustively check that Centrum rozliczeń runs one Uruchomienie procesu at a time and never closes during one.

The checker runs the real ``RunHost`` (``runs.py``) and ``Shutdown`` (``shutdown.py``), wired as in
``create_app``, in modelled threads: browser tabs clicking „Uruchom”, „Zaktualizuj narzędzie” and „Zamknij Centrum
rozliczeń”, Dad answering a Decyzja, the Uruchomienie thread that ``RunHost.start`` spawns, the
Aktualizacja narzędzia thread, and the server thread ``stop_when_asked``. Every lock entry, Event ``set``/``wait``/``clear``, thread start and Centrum log
entry of the real code is one indivisible step. Before every step the checker may let any other
thread go first. It tries every such schedule within the bounds of a scope, re-running the code once
per schedule, and checks four rules:

- JEDNO_NARAZ: at no moment are two Uruchomienia procesu in progress, or an Uruchomienie and an
  Aktualizacja narzędzia, or two Aktualizacje. An Uruchomienie is in progress from the moment
  ``RunHost.start`` creates its ``Run`` until ``RunHost.finished`` has written its end to the Centrum
  log, after the engine and the metrics record. The checker tracks this itself, not through the code's
  ``ended`` flag, so a flag set too early is caught. An Aktualizacja is in progress from a successful
  ``RunHost.begin_update`` until ``RunHost.end_update`` returns or the restart guardian has started.
- BEZ_ZAMKNIECIA_W_TRAKCIE: when the server ends, no Uruchomienie procesu is in progress, including
  one waiting for Dad's Decyzja, and no Aktualizacja narzędzia before its restart guardian started.
  Both threads are daemons, so the end of the Python process kills them mid-work.
- PO_WYNIKU_PRZED_KONCEM: when the server ends, every Uruchomienie that reached its end in the Centrum
  log has also run its actions after the result (``RunHost.after``: the Kontrola ilości lands in the
  queue file there). Otherwise a shutdown accepted right after the result kills the thread before the file
  exists.
- WYNIK_NA_KARCIE: every Uruchomienie whose thread finished its work has its result (the ``finished`` view) among
  the views a card's event stream reads after the view it read when that Uruchomienie started (``RunHost.events_after``),
  at the end of every schedule. A card reads the stream every 50 ms, so a start from a second tab that drops the
  result before such a read leaves the card without it; the result is then only in Historia.

Given through public seams, not by replacing anything in the verified modules: model primitives that hand control to
the checker as the ``threads`` of ``RunHost`` and ``Shutdown`` (``threads.Threading``); an engine with two steps and an
optional Decyzja through the real ``Run.confirm`` as the ``PreparedRun.conduct`` of the run every tab starts (in the code
it runs ``run_process``); ``CentrumLog``, ``CentrumRuns`` and the start file (``run_started``) as steps that write
nothing, with no Uruchomienie before Centrum's start; the actions after the result
(``AfterRun``) as one step that writes nothing. ``RunHost``'s ``created`` hands the checker each new ``Run`` under the
lock, and the checker reads the views through ``RunHost.events_after``. ``ToolUpdates``
(``tool_updates.py``) is modelled by hand around the real ``begin_update``, ``end_update`` and
``Shutdown.close_for_update``: Git, pip and the restart guardian are one step that ends either without a
new version (or with a failure) or with the guardian started. Modelled by hand:
``stop_when_asked`` in ``server.py`` and uvicorn's graceful shutdown. After ``Shutdown.wait`` returns,
the server may end at any moment when no HTTP request is in flight; a request that arrived before
that is served to the end. Any other use of the ``threads`` seam (``RLock``, ``wait(timeout=...)``) stops the check as
LUKA MODELU, and so do a ``RunHost`` that takes no lock from it and a modelled thread that waits on something outside
the model (a real lock or Event, ``time.sleep``) for ``STALL_SECONDS`` without a step.

Schedules that reach a state already explored are cut short: the code is deterministic, so a state
(each thread's steps so far, every Uruchomienie's flags, the lock and the Events) has the same
futures every time.
"""

from __future__ import annotations

import argparse
import linecache
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import FrameType, SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from rozliczenia import process_run
from rozliczenia.centrum import contract, process_kind, runs, shutdown
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.decision import Decision
from rozliczenia.message import Message
from rozliczenia.process_run import Interlocutor
from rozliczenia.progress import ProgressProjection
from rozliczenia.run_context import RunContext
from eksplorator import Choices, Excuse, Interleaving, Shape, Thread, excuse_line, excused, gone_lines, schedules, verdict
import rozjazd_modelu

REPO_ROOT = Path(__file__).resolve().parents[4]

VERIFIED_FILES = ("runs.py", "shutdown.py")
CLOSE_LOG = "dziennik Centrum: shutdown_requested"
REQUESTED_SET = "Shutdown._requested.set()"
CLOSE_TAB = "karta Zamknij"
WITH_DECISION = "z Decyzją taty"
NEW_VERSION = "nowa wersja, opiekun ponownego startu wystartował"
DECISION = Decision(
    title="Decyzja",
    message=Message(code="MODEL", what="Pytanie modelu.", where="silnik", action="Odpowiedz."),
    counts_title="Liczby",
    counts=(("Wiersze danych", 1),),
    question="Kontynuować?",
)


class Abort(BaseException):
    """The server ended (the Python process ends) or the checker stops this schedule."""


class ModelGap(BaseException):
    """The real code used ``threading`` in a way the model primitives do not cover."""


# --- Scheduler: one modelled thread runs at a time, from one step to the next (``eksplorator.Interleaving``) --------
#
# A modelled thread that waits on a real lock, Event or sleep outside the model stops that one OS thread with it, and
# no code of the thread runs again: no hub and no trace hook can see it. So ``explore`` runs the check on a thread of
# its own and watches its steps from outside. A step costs microseconds of CPU and no hand-over, so a busy runner
# stretches the gap between two steps, not their number (the longest gap of a whole check on a 16-core Mac with 32
# processes burning CPU: 0.17 s). STALL_SECONDS without a step therefore means a thread that waits for real.
STALL_SECONDS = 10.0


@dataclass
class Pending:
    call: str
    where: str
    enabled: Callable[[], bool]
    variants: tuple[str, ...]


@dataclass
class Actor(Thread):
    pending: Pending | None = None
    in_flight: bool = False
    run: Tracked | None = None  # the Uruchomienie whose work() this thread runs


_ABORT = "\0abort"


def _current_actor() -> Actor:
    actor = Interleaving.current()
    if not isinstance(actor, Actor):
        raise ModelGap("krok poza wątkiem modelu")
    return actor


def _code_location(frame: FrameType | None = None) -> str:
    frame = sys._getframe(2) if frame is None else frame
    while frame is not None:
        name = Path(frame.f_code.co_filename).name
        if name in VERIFIED_FILES and Path(frame.f_code.co_filename).parent.name == "centrum":
            return f"{name}:{frame.f_lineno} {frame.f_code.co_name}"
        frame = frame.f_back
    return "model"


@dataclass
class Progress:
    """The checker's thread as ``explore`` watches it from outside: the schedule it runs and its steps so far."""

    scheduler: Scheduler | None = None
    steps: int = 0
    abandoned: bool = False  # explore gave up on it: a thread that wakes up later stops at its next step


class Scheduler(Interleaving[Actor]):
    def __init__(self, trace: list[str], progress: Progress) -> None:
        super().__init__()
        self.trace = trace
        self.gaps: list[str] = []
        self.running: Actor | None = None  # the thread between two of its steps
        self.progress = progress
        progress.scheduler = self

    def add(self, name: str, body: Callable[[], None], run: Tracked | None = None) -> Actor:
        """Adds a thread that runs up to its first step at the next ``settle``."""

        actor = Actor(name, run=run)

        def main() -> None:
            try:
                body()
            except Abort:
                pass
            except ModelGap as gap:
                self.gaps.append(f"{actor.name}: {gap}")
            finally:
                actor.pending = None

        return self.spawn(actor, main)

    def step(
        self,
        call: str,
        *,
        enabled: Callable[[], bool] = lambda: True,
        variants: tuple[str, ...] = ("",),
    ) -> str:
        """Parks the calling thread until the checker picks this step; returns the picked variant."""

        actor = _current_actor()
        actor.pending = Pending(call, _code_location(), enabled, variants)
        outcome = self.park(actor)
        actor.pending = None
        if outcome == _ABORT:
            raise Abort()
        actor.history.append(f"{call} → {outcome}" if outcome else call)
        return outcome

    def note(self, text: str) -> None:
        self.trace.append(f"{_current_actor().name}: {text}")

    def _switch(self, thread: Actor) -> None:
        self.running = thread
        super()._switch(thread)
        self.running = None
        if self.progress.abandoned:
            raise Abort()
        self.progress.steps += 1

    def abort_all(self) -> None:
        for actor in self.threads:
            if actor.status == "parked":
                self.release(actor, _ABORT)
        self.settle()


# --- Model primitives given to RunHost, Run and Shutdown as their ``threads`` (``threads.Threading``) ----------------


@dataclass
class Tracked:
    """One Uruchomienie as the checker tracks it from the moment ``RunHost.start`` creates its ``Run`` (``created``)."""

    run: runs.Run
    name: str
    creator: str
    window: str
    card_seen: int
    """A card that has read the stream up to this start: every view it reads later has a higher sequence."""
    done: bool = False
    after_done: bool = False
    returned: bool = False


class ModelLock:
    """The lock of ``RunHost``: entering is one step, which can be taken only while the lock is free.

    The checker itself reads ``RunHost`` between steps, outside any modelled thread, when every modelled thread waits
    before a step of its own: that read is no step and does not take the lock.
    """

    def __init__(self, scheduler: Scheduler, label: str) -> None:
        self._scheduler = scheduler
        self.label = label
        self.owner: str | None = None

    def __enter__(self) -> bool:
        if Interleaving.current() is None:
            return True
        self._scheduler.step(f"wejście w blokadę {self.label}", enabled=lambda: self.owner is None)
        self.owner = _current_actor().name
        return True

    def __exit__(self, *_: object) -> None:
        if Interleaving.current() is not None:
            self.owner = None


class ModelEvent:
    """``threading.Event``: ``set``, ``clear`` and ``wait`` are steps; ``wait`` can be taken only once set."""

    def __init__(self, scheduler: Scheduler, label: str) -> None:
        self._scheduler = scheduler
        self.label = label
        self.flag = False

    def set(self) -> None:
        self._scheduler.step(f"{self.label}.set()")
        self.flag = True

    def clear(self) -> None:
        self._scheduler.step(f"{self.label}.clear()")
        self.flag = False

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None:
            raise ModelGap(f"{self.label}.wait(timeout=...)")
        self._scheduler.step(f"{self.label}.wait()", enabled=lambda: self.flag)
        return True

    def is_set(self) -> bool:
        return self.flag


class ModelThread:
    """The Uruchomienie thread started by ``RunHost.start``: starting it is one step, then it runs as an actor."""

    def __init__(
        self,
        scheduler: Scheduler,
        tracked: Callable[[object], Tracked | None],
        *,
        target: Callable[[], object],
        name: str,
        daemon: bool,
    ) -> None:
        if not daemon:
            raise ModelGap("wątek Uruchomienia nie jest daemon: koniec procesu Pythona by na niego czekał")
        self._scheduler = scheduler
        self._tracked = tracked
        self._target = target

    def start(self) -> None:
        self._scheduler.step("start wątku Uruchomienia")
        run = self._tracked(getattr(self._target, "__self__", None))

        def body() -> None:
            self._target()
            if run is not None:
                run.returned = True

        self._scheduler.add(f"wątek {run.name if run is not None else 'Uruchomienie'}", body, run)


class ModelThreading:
    """The ``threads`` of one verified class (``threads.Threading``); remembers the locks it gave out.

    ``tracked`` finds the tracked Uruchomienie of the ``Run`` whose ``work`` a new thread runs.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        module: str,
        lock_label: str,
        event_label: str,
        events: list[ModelEvent],
        tracked: Callable[[object], Tracked | None] = lambda _run: None,
    ):
        self._scheduler = scheduler
        self._module = module
        self._lock_label = lock_label
        self._event_label = event_label
        self._events = events
        self._tracked = tracked
        self.locks: list[ModelLock] = []

    def Lock(self) -> ModelLock:  # noqa: N802 - same name as threading.Lock
        lock = ModelLock(self._scheduler, self._lock_label)
        self.locks.append(lock)
        return lock

    def Event(self) -> ModelEvent:  # noqa: N802 - same name as threading.Event
        event = ModelEvent(self._scheduler, self._event_label)
        self._events.append(event)
        return event

    def Thread(self, *, target: Callable[[], object], name: str, daemon: bool = False) -> ModelThread:  # noqa: N802
        return ModelThread(self._scheduler, self._tracked, target=target, name=name, daemon=daemon)

    def __getattr__(self, name: str) -> Any:
        raise ModelGap(f"threading.{name} w {self._module}")


class LogSteps:
    """``CentrumLog``: each entry is one step, like the file write in the real log; nothing is written."""

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def __getattr__(self, name: str) -> Callable[..., None]:
        def entry(*_: object, **__: object) -> None:
            self._scheduler.step(f"dziennik Centrum: {name}")
            run = _current_actor().run
            if name == "run_finished" and run is not None:
                run.done = True

        return entry


class AfterRunSteps:
    """``AfterRun``: the actions after the result (Kontrola ilości into its queue file) are one step; nothing is written."""

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def run_ended(self, _run: object) -> None:
        self._scheduler.step("po wyniku: działania po wyniku Uruchomienia (plik kolejki)")
        run = _current_actor().run
        if run is not None:
            run.after_done = True


class CentrumRunsSteps:
    """``CentrumRuns``: remembering the metrics record of an Uruchomienie is one step; nothing is written."""

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def remember(self, *_: object) -> None:
        self._scheduler.step("CentrumRuns.remember: rekord metryk Uruchomienia z Centrum")


class StartFileSteps:
    """``run_started`` of ``RunHost``: the start file of each Uruchomienie is one step; nothing is written."""

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def run_started(self, *_: object) -> None:
        self._scheduler.step("run_started: plik startu Uruchomienia")


# --- Harness ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    name: str
    start_tabs: int
    close_clicks: int
    decisions: int
    update_tabs: int = 0
    restore_tabs: int = 0

    def describe(self) -> str:
        updates = (
            f"karty „Zaktualizuj narzędzie”: {self.update_tabs}, aktualizacja bez nowej wersji albo z ponownym startem, "
            if self.update_tabs
            else ""
        )
        restores = f"karty „Przywróć tę kopię”: {self.restore_tabs}, " if self.restore_tabs else ""
        return (
            f"karty „Uruchom”: {self.start_tabs}, {updates}{restores}kliknięcia „Zamknij Centrum rozliczeń”: "
            f"≤ {self.close_clicks}, Decyzje taty: ≤ {self.decisions}, silnik z Decyzją albo bez"
        )


SCOPES = {
    "zamknij-w-trakcie": Scope("zamknij-w-trakcie", start_tabs=1, close_clicks=2, decisions=1),
    "dwie-karty": Scope("dwie-karty", start_tabs=2, close_clicks=1, decisions=2),
    "aktualizacja": Scope("aktualizacja", start_tabs=1, close_clicks=1, decisions=1, update_tabs=2),
    "przywracanie": Scope("przywracanie", start_tabs=1, close_clicks=1, decisions=1, restore_tabs=2),
}

PREPARED: process_kind.PreparedRun[Any, Any] = CATALOG.prepared(
    "preparation", period="08_14_09_2026", inputs=SimpleNamespace(dry_run=False), context=RunContext()
)


@dataclass(frozen=True)
class ModelledRun(process_kind.PreparedRun[Any, Any]):
    """``PREPARED`` with the checker's engine as ``conduct``: a work step that ends with or without a Decyzja taken
    through the real ``Run.confirm``, then the end with the metrics record. Every Uruchomienie ends in success."""

    scheduler: Scheduler | None = None

    @classmethod
    def of(cls, prepared: process_kind.PreparedRun[Any, Any], scheduler: Scheduler) -> ModelledRun:
        return cls(**{part.name: getattr(prepared, part.name) for part in fields(prepared)}, scheduler=scheduler)

    def conduct(self, interlocutor: Interlocutor) -> process_run.Outcome[Any]:
        assert self.scheduler is not None
        variant = self.scheduler.step("silnik: Sprawdzanie … Zapisywanie", variants=("bez Decyzji", WITH_DECISION))
        if variant == WITH_DECISION:
            interlocutor.confirm(DECISION)
        self.scheduler.step("silnik kończy i dopisuje rekord metryk")
        ending = process_run.Finished("OK", {name: 0 for name in self.kind.core.counter_names}, {})
        return process_run.Outcome(
            ending=ending,
            view=None,
            total_duration_ms=0,
            technical_notes=(),
            metrics_saved=True,
            progress=ProgressProjection().snapshot,
            files_unchanged=False,
        )


@dataclass(frozen=True)
class Violation:
    rule: str
    signature: tuple[object, ...]
    text: str


@dataclass
class Update:
    """One Aktualizacja narzędzia that ``RunHost.begin_update`` let in."""

    name: str
    creator: str
    window: str
    done: bool = False
    restarted: bool = False


@dataclass
class Restore:
    """One przywrócenie Kopii INTERMAX that ``RunHost.begin_restore`` let in; it runs inside its HTTP request."""

    name: str
    creator: str
    window: str
    done: bool = False


@dataclass
class World:
    """One schedule: the real ``RunHost`` and ``Shutdown`` and everything the checker observes of them."""

    scheduler: Scheduler
    events: list[ModelEvent]
    created: list[Tracked]
    host: runs.RunHost
    shutdown: shutdown.Shutdown
    lock: ModelLock | None
    prepared: ModelledRun
    log: Any = None
    exited: bool = False
    closes_refused: int = 0
    starts_refused: int = 0
    updates_refused: int = 0
    restores_refused: int = 0
    updates: list[Update] = field(default_factory=list)
    restores: list[Restore] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)

    def in_progress(self) -> list[Tracked]:
        return [run for run in self.created if not run.done]

    def updating(self) -> list[Update]:
        return [update for update in self.updates if not update.done]

    def restoring(self) -> list[Restore]:
        return [restore for restore in self.restores if not restore.done]

    def requested(self) -> bool:
        return any(event.label == "Shutdown._requested" and event.flag for event in self.events)

    def close_window(self) -> str:
        """Where the Zamknij click stood when an Uruchomienie was created."""

        if self.requested():
            return "po przyjęciu prośby o zamknięcie"
        for actor in self.scheduler.threads:
            if actor.name == CLOSE_TAB and actor.pending is not None and actor.pending.call in (
                CLOSE_LOG,
                REQUESTED_SET,
            ):
                return "między sprawdzeniem odmowy a przyjęciem prośby"
        return "przed sprawdzeniem odmowy"


def wire(scheduler: Scheduler) -> World:
    """The real ``RunHost`` and ``Shutdown`` of one schedule, wired as in ``create_app``, with the checker's seams."""

    events: list[ModelEvent] = []
    created: list[Tracked] = []
    world_box: list[World] = []

    def tracked(run: object) -> Tracked | None:
        return next((known for known in created if known.run is run), None)

    def track(run: runs.Run, last: contract.RunEvent) -> None:
        created.append(
            Tracked(
                run,
                f"Uruchomienie {len(created) + 1}",
                _current_actor().name,
                world_box[0].close_window(),
                last.sequence,
            )
        )

    class NoStops:
        def ended(self, info: object, stop: object, *, shown: object) -> None:
            if stop is not None:
                raise ModelGap("Zatrzymanie w Stops.ended; model kończy każde Uruchomienie sukcesem")

    log = LogSteps(scheduler)
    host_threads = ModelThreading(scheduler, "runs.py", "RunHost._lock", "Run._decided", events, tracked)
    # Wired as in create_app (app.py): RunHost, then Shutdown.refuse_while(runs.shutdown_refusal).
    stopper = shutdown.Shutdown(
        log,  # type: ignore[arg-type]
        threads=ModelThreading(scheduler, "shutdown.py", "Shutdown", "Shutdown._requested", events),
    )
    host = runs.RunHost(
        log,  # type: ignore[arg-type]
        CentrumRunsSteps(scheduler),  # type: ignore[arg-type]
        NoStops(),  # type: ignore[arg-type]
        previous=None,
        run_started=StartFileSteps(scheduler).run_started,
        after_run=[AfterRunSteps(scheduler)],
        threads=host_threads,
        created=track,
    )
    stopper.refuse_while(host.shutdown_refusal)
    world = World(
        scheduler,
        events,
        created,
        host,
        stopper,
        host_threads.locks[0] if len(host_threads.locks) == 1 else None,
        ModelledRun.of(PREPARED, scheduler),
        log=log,
    )
    world_box.append(world)
    return world


def _start_tab(world: World, number: int) -> Callable[[], None]:
    def body() -> None:
        scheduler = world.scheduler
        scheduler.step("żądanie POST /api/runs dociera do serwera")
        _current_actor().in_flight = True
        try:
            view = world.host.start(world.prepared)
            scheduler.note(f"odpowiedź 200: {view.state}")
        except contract.Refusal as refusal:
            world.starts_refused += 1
            scheduler.note(f"odpowiedź {refusal.status_code}: {refusal.message}")
        _current_actor().in_flight = False

    return body


def _close_tab(world: World, clicks: int) -> Callable[[], None]:
    def body() -> None:
        scheduler = world.scheduler
        for _ in range(clicks):
            scheduler.step("żądanie POST /api/shutdown dociera do serwera")
            _current_actor().in_flight = True
            try:
                world.shutdown.request()
            except contract.Refusal as refusal:
                world.closes_refused += 1
                scheduler.note(f"odpowiedź {refusal.status_code}: {refusal.message}")
                _current_actor().in_flight = False
                continue
            scheduler.note("odpowiedź 202: Centrum się zamyka")
            _current_actor().in_flight = False
            return

    return body


def _update_tab(world: World, number: int) -> Callable[[], None]:
    """``ToolUpdates.start`` behind POST /api/tool-update: the slot, the log entry, then its own thread."""

    def body() -> None:
        scheduler = world.scheduler
        scheduler.step("żądanie POST /api/tool-update dociera do serwera")
        _current_actor().in_flight = True
        try:
            world.host.begin_update()
        except contract.Refusal as refusal:
            world.updates_refused += 1
            scheduler.note(f"odpowiedź {refusal.status_code}: {refusal.message}")
            _current_actor().in_flight = False
            return
        update = Update(f"Aktualizacja {number}", _current_actor().name, world.close_window())
        world.updates.append(update)
        world.log.update_started()
        scheduler.step("start wątku aktualizacji")
        scheduler.add(f"wątek {update.name}", _update_thread(world, update))
        scheduler.note("odpowiedź 202: aktualizacja trwa")
        _current_actor().in_flight = False

    return body


def _update_thread(world: World, update: Update) -> Callable[[], None]:
    """``ToolUpdates._update``: without a new version it frees the slot, with one it hands over and closes Centrum."""

    def body() -> None:
        variant = world.scheduler.step(
            "aktualizacja: Git, pliki taty, biblioteki",
            variants=("bez nowej wersji albo porażka", NEW_VERSION),
        )
        if variant == NEW_VERSION:
            # From here the restart guardian owns the update; the end of this process is what it waits for.
            update.done = update.restarted = True
            world.shutdown.close_for_update()
            return
        world.log.update_finished()
        world.host.end_update()
        update.done = True

    return body


def _restore_tab(world: World, number: int) -> Callable[[], None]:
    """``intermax_copies_router`` behind POST /api/intermax/copies/restore: the slot, the restore, then its end."""

    def body() -> None:
        scheduler = world.scheduler
        scheduler.step("żądanie POST /api/intermax/copies/restore dociera do serwera")
        _current_actor().in_flight = True
        try:
            world.host.begin_restore()
        except contract.Refusal as refusal:
            world.restores_refused += 1
            scheduler.note(f"odpowiedź {refusal.status_code}: {refusal.message}")
            _current_actor().in_flight = False
            return
        restore = Restore(f"Przywrócenie {number}", _current_actor().name, world.close_window())
        world.restores.append(restore)
        scheduler.step("przywrócenie: Kopia stanu bieżącego i podmiana INTERMAX")
        world.host.end_restore()
        restore.done = True
        scheduler.note("odpowiedź 200: kopia przywrócona")
        _current_actor().in_flight = False

    return body


def _decision_tab(world: World, decisions: int) -> Callable[[], None]:
    def awaiting() -> runs.Run | None:
        return next(
            (tracked.run for tracked in world.created if tracked.run.awaiting_decision and not tracked.run.ended),
            None,
        )

    def body() -> None:
        scheduler = world.scheduler
        for _ in range(decisions):
            scheduler.step(
                "tata odpowiada na Decyzję: POST /api/runs/{id}/decision",
                enabled=lambda: awaiting() is not None,
            )
            _current_actor().in_flight = True
            run = awaiting()
            try:
                world.host.decide(
                    run.info.id if run is not None else "",
                    contract.DecisionAnswer(answer="continue"),
                )
                scheduler.note("odpowiedź 200: Decyzja przyjęta")
            except contract.Refusal as refusal:
                scheduler.note(f"odpowiedź {refusal.status_code}: {refusal.message}")
            _current_actor().in_flight = False

    return body


def _server(world: World) -> Callable[[], None]:
    """``stop_when_asked`` in server.py, then uvicorn's graceful shutdown and the end of the process."""

    def body() -> None:
        world.shutdown.wait()
        world.scheduler.step(
            "serwer kończy pracę: uvicorn zamknięty, proces Pythona się kończy, wątki daemon giną",
            enabled=lambda: not any(actor.in_flight for actor in world.scheduler.threads),
        )
        world.exited = True
        for run in world.in_progress():
            doing = "czeka na Decyzję taty" if run.run.awaiting_decision else "trwa"
            world.violations.append(
                Violation(
                    "BEZ_ZAMKNIECIA_W_TRAKCIE",
                    ("BEZ_ZAMKNIECIA_W_TRAKCIE", run.window),
                    f"Centrum kończy pracę, a {run.name} (z: {run.creator}) {doing}; "
                    f"wystartowało {run.window}",
                )
            )
        for run in world.created:
            if run.done and not run.after_done:
                world.violations.append(
                    Violation(
                        "PO_WYNIKU_PRZED_KONCEM",
                        ("PO_WYNIKU_PRZED_KONCEM",),
                        f"Centrum kończy pracę po wyniku {run.name} (z: {run.creator}), "
                        "zanim przeszły jego działania po wyniku",
                    )
                )
        for update in world.updating():
            world.violations.append(
                Violation(
                    "BEZ_ZAMKNIECIA_W_TRAKCIE",
                    ("BEZ_ZAMKNIECIA_W_TRAKCIE", "aktualizacja", update.window),
                    f"Centrum kończy pracę, a {update.name} (z: {update.creator}) trwa przed startem opiekuna; "
                    f"zaczęła się {update.window}",
                )
            )
        for restore in world.restoring():
            world.violations.append(
                Violation(
                    "BEZ_ZAMKNIECIA_W_TRAKCIE",
                    ("BEZ_ZAMKNIECIA_W_TRAKCIE", "przywrócenie", restore.window),
                    f"Centrum kończy pracę, a {restore.name} (z: {restore.creator}) podmienia INTERMAX; "
                    f"zaczęło się {restore.window}",
                )
            )

    return body


# --- Exploration ------------------------------------------------------------------------------------


@dataclass
class Execution:
    trace: list[str]
    violations: list[Violation]
    gaps: list[str]
    cut: bool
    clean_close: bool
    close_refused: bool
    start_refused: bool
    run_ended: bool
    update_refused: bool = False
    update_restarted: bool = False
    restore_refused: bool = False
    restore_done: bool = False
    results_shown_twice: bool = False


def _state(world: World) -> object:
    # The views a card can still read and each card's cursor decide WYNIK_NA_KARCIE; run ids differ in every schedule.
    names: dict[object, str] = {run.run.info.id: run.name for run in world.created}
    return (
        tuple(
            (event.sequence, event.view.state, names.get(getattr(getattr(event.view, "run", None), "id", None)))
            for event in world.host.events_after(-1)
        ),
        tuple((run.card_seen, run.returned) for run in world.created),
        tuple(
            (
                actor.name,
                actor.status,
                tuple(actor.history),
                actor.pending.call if actor.pending else None,
                actor.in_flight,
            )
            for actor in world.scheduler.threads
        ),
        tuple(
            (
                run.name,
                run.creator,
                run.window,
                run.done,
                run.after_done,
                run.run.ended,
                run.run.awaiting_decision,
            )
            for run in world.created
        ),
        tuple((update.name, update.creator, update.window, update.done) for update in world.updates),
        tuple((restore.name, restore.creator, restore.window, restore.done) for restore in world.restores),
        world.lock.owner if world.lock is not None else None,
        tuple((event.label, event.flag) for event in world.events),
        world.exited,
    )


def execute(scope: Scope, choices: Choices, visited: set[object], progress: Progress) -> Execution:
    trace: list[str] = []
    scheduler = Scheduler(trace, progress)
    try:
        world = wire(scheduler)
        cut = _drive(world, scope, choices, visited)
    except ModelGap as gap:
        return Execution(
            trace,
            [],
            [f"wiązanie RunHost i Shutdown: {gap}"],
            False,
            False,
            False,
            False,
            False,
        )
    if cut and not world.violations:
        trace.append("dalej ten sam stan co w harmonogramie sprawdzonym wcześniej")
    return Execution(
        trace,
        world.violations,
        list(scheduler.gaps),
        cut,
        clean_close=world.exited and not world.violations,
        close_refused=world.closes_refused > 0,
        start_refused=world.starts_refused > 0,
        run_ended=any(run.done for run in world.created),
        update_refused=world.updates_refused > 0,
        update_restarted=any(update.restarted for update in world.updates) and not world.violations,
        restore_refused=world.restores_refused > 0,
        restore_done=any(restore.done for restore in world.restores) and not world.violations,
        results_shown_twice=sum(run.returned for run in world.created) > 1,
    )


def _drive(world: World, scope: Scope, choices: Choices, visited: set[object]) -> bool:
    """Runs one schedule to its end; ``True`` when it was cut short at an already explored state."""

    scheduler = world.scheduler
    if world.lock is None:
        scheduler.gaps.append("RunHost nie wziął jednej blokady z threads.Lock()")
    for number in range(1, scope.start_tabs + 1):
        scheduler.add(f"karta Uruchom {number}", _start_tab(world, number))
    for number in range(1, scope.update_tabs + 1):
        scheduler.add(f"karta Zaktualizuj {number}", _update_tab(world, number))
    for number in range(1, scope.restore_tabs + 1):
        scheduler.add(f"karta Przywróć {number}", _restore_tab(world, number))
    scheduler.add(CLOSE_TAB, _close_tab(world, scope.close_clicks))
    scheduler.add("tata", _decision_tab(world, scope.decisions))
    scheduler.add("serwer", _server(world))
    try:
        while not scheduler.gaps:
            scheduler.settle()
            running = world.in_progress()
            updating = world.updating()
            restoring = world.restoring()
            if len(running) + len(updating) + len(restoring) > 1 and not any(
                violation.rule == "JEDNO_NARAZ" for violation in world.violations
            ):
                names = ", ".join(
                    [f"{run.name} (z: {run.creator})" for run in running]
                    + [f"{update.name} (z: {update.creator})" for update in updating]
                    + [f"{restore.name} (z: {restore.creator})" for restore in restoring]
                )
                kinds = [kind for kind, busy in (("Uruchomienie", running), ("Aktualizacja", updating), ("Przywrócenie", restoring)) if busy]
                kind = "Uruchomienia" if kinds == ["Uruchomienie"] else " i ".join(kinds)
                world.violations.append(Violation("JEDNO_NARAZ", ("JEDNO_NARAZ", kind), f"naraz trwają: {names}"))
            if world.exited:
                _check_results_on_card(world)
                return False
            options = [
                (actor, variant)
                for actor in scheduler.threads
                if actor.status == "parked" and actor.pending is not None and actor.pending.enabled()
                for variant in actor.pending.variants
            ]
            if not options:
                _check_results_on_card(world)
                return False
            state = _state(world)
            if not choices.replaying and state in visited:
                return True
            visited.add(state)
            actor, variant = options[choices.choose(len(options))]
            assert actor.pending is not None
            detail = f" → {variant}" if variant else ""
            scheduler.trace.append(f"{actor.name}: {actor.pending.call}{detail} [{actor.pending.where}]")
            scheduler.release(actor, variant)
        return False
    finally:
        scheduler.abort_all()


def _check_results_on_card(world: World) -> None:
    """WYNIK_NA_KARCIE at the end of a schedule: what a card reads next, read without a step of the lock."""

    for run in world.created:
        if not run.returned:
            continue
        readable = [event.view for event in world.host.events_after(run.card_seen)]
        if not any(isinstance(view, contract.RunFinished) and view.run.id == run.run.info.id for view in readable):
            world.violations.append(
                Violation(
                    "WYNIK_NA_KARCIE",
                    ("WYNIK_NA_KARCIE",),
                    f"{run.name} (z: {run.creator}) skończyło pracę, a karta, która śledzi strumień "
                    "od jego startu, nie dostaje jego wyniku: zostaje tylko w Historii",
                )
            )


@dataclass
class ScopeReport:
    scope: Scope
    schedules: int = 0
    states: int = 0
    seconds: float = 0.0
    clean_closes: int = 0
    closes_refused: int = 0
    starts_refused: int = 0
    runs_ended: int = 0
    updates_refused: int = 0
    updates_restarted: int = 0
    restores_refused: int = 0
    restores_done: int = 0
    results_shown_twice: int = 0
    counterexamples: dict[tuple[object, ...], tuple[Violation, list[str]]] = field(default_factory=dict)
    gaps: dict[str, list[str]] = field(default_factory=dict)

    def vacuous(self) -> list[str]:
        """Behaviour every scope must reach, or the check could pass without testing anything."""

        missing = []
        if not self.clean_closes:
            missing.append("BRAK_ZAMKNIECIA: Centrum ani razu nie zamknęło się bez trwającego Uruchomienia.")
        if not self.closes_refused:
            missing.append("BRAK_ODMOWY_ZAMKNIECIA: „Zamknij” ani razu nie dostało 409 w trakcie Uruchomienia.")
        if not self.runs_ended:
            missing.append("BRAK_WYNIKU: żadne Uruchomienie procesu nie doszło do wyniku.")
        if self.scope.start_tabs > 1 and not self.starts_refused:
            missing.append("BRAK_ODMOWY_STARTU: druga karta „Uruchom” ani razu nie dostała 409.")
        if self.scope.start_tabs > 1 and not self.results_shown_twice:
            missing.append(
                "BRAK_DRUGIEGO_WYNIKU: druga karta „Uruchom” ani razu nie uruchomiła procesu po wyniku pierwszego, "
                "więc WYNIK_NA_KARCIE nie sprawdza startu, który mógłby zgubić wynik."
            )
        if self.scope.update_tabs and not self.starts_refused:
            missing.append("BRAK_ODMOWY_STARTU: „Uruchom” ani razu nie dostało 409 w trakcie aktualizacji.")
        if self.scope.update_tabs and not self.updates_refused:
            missing.append("BRAK_ODMOWY_AKTUALIZACJI: „Zaktualizuj narzędzie” ani razu nie dostało 409.")
        if self.scope.update_tabs and not self.updates_restarted:
            missing.append("BRAK_PONOWNEGO_STARTU: żadna aktualizacja nie zamknęła Centrum dla nowej wersji.")
        if self.scope.restore_tabs and not self.starts_refused:
            missing.append("BRAK_ODMOWY_STARTU: „Uruchom” ani razu nie dostało 409 w trakcie przywracania.")
        if self.scope.restore_tabs and not self.restores_refused:
            missing.append("BRAK_ODMOWY_PRZYWROCENIA: „Przywróć tę kopię” ani razu nie dostało 409.")
        if self.scope.restore_tabs and not self.restores_done:
            missing.append("BRAK_PRZYWROCENIA: żadne przywrócenie Kopii INTERMAX nie doszło do końca.")
        return missing


def explore(scope: Scope) -> ScopeReport:
    """Tries every schedule of ``scope`` on a thread of its own; a modelled thread that waits for real is a LUKA MODELU.

    That thread stays blocked, with every lock it holds, until the process ends, so check the real code in a process
    of its own (#651); the script's process ends after the report, because the thread is a daemon.
    """

    report = ScopeReport(scope)
    progress = Progress()
    failures: list[BaseException] = []

    def check() -> None:
        try:
            _explore(report, progress)
        except BaseException as failure:  # noqa: BLE001 - raised again below, in the thread that called explore
            failures.append(failure)

    started = time.perf_counter()
    checker = threading.Thread(target=check, name="sprawdzenie przeplotów", daemon=True)
    checker.start()
    seen, since = -1, time.monotonic()
    while checker.is_alive():
        checker.join(STALL_SECONDS / 10)
        if progress.steps != seen:
            seen, since = progress.steps, time.monotonic()
        elif time.monotonic() - since >= STALL_SECONDS:
            progress.abandoned = True
            gap, trace = _stalled(progress, checker)
            report.gaps[gap] = trace
            break
    report.seconds = time.perf_counter() - started
    if failures:
        raise failures[0]
    return report


def _stalled(progress: Progress, checker: threading.Thread) -> tuple[str, list[str]]:
    """The modelled thread that waits outside the model, its last step and the line it waits on."""

    scheduler = progress.scheduler
    actor = scheduler.running if scheduler is not None else None
    frame = sys._current_frames().get(checker.ident or 0)
    where = "?"
    if frame is not None:
        code = frame.f_code
        line = linecache.getline(code.co_filename, frame.f_lineno).strip()
        where = f"{Path(code.co_filename).name}:{frame.f_lineno} {code.co_name} ({line})"
        if (verified := _code_location(frame)) != "model" and not where.startswith(verified):
            where += f", dokąd doszedł z {verified}"
    name = actor.name if actor is not None else "sprawdzenie"
    if actor is not None and actor.history:
        stalled = f"po kroku „{actor.history[-1]}” wątek modelu przez {STALL_SECONDS:.0f} s nie doszedł do kolejnego"
    else:
        stalled = f"wątek modelu przez {STALL_SECONDS:.0f} s nie doszedł do pierwszego kroku"
    gap = (
        f"{name}: {stalled} i stoi w {where}, "
        "czyli czeka na coś spoza modelu (prawdziwą blokadę, Event albo time.sleep)"
    )
    return gap, list(scheduler.trace) if scheduler is not None else []


def _explore(report: ScopeReport, progress: Progress) -> None:
    visited: set[object] = set()
    for execution in schedules(lambda choices: execute(report.scope, choices, visited, progress)):
        report.schedules += 1
        report.states = len(visited)  # so far, also for a check that stalls
        report.clean_closes += execution.clean_close
        report.closes_refused += execution.close_refused
        report.starts_refused += execution.start_refused
        report.runs_ended += execution.run_ended
        report.updates_refused += execution.update_refused
        report.updates_restarted += execution.update_restarted
        report.restores_refused += execution.restore_refused
        report.restores_done += execution.restore_done
        report.results_shown_twice += execution.results_shown_twice
        for violation in execution.violations:
            # Keep the shortest counterexample.
            known = report.counterexamples.get(violation.signature)
            if known is None or len(execution.trace) < len(known[1]):
                report.counterexamples[violation.signature] = (
                    violation,
                    execution.trace,
                )
        for gap in execution.gaps:
            report.gaps.setdefault(gap, execution.trace)


# --- Report -------------------------------------------------------------------------------------------

# Real defects in the current code, reported on every run until a code change fixes them. An entry's shape judges a
# violation's ``signature``. Empty since „Zamknij” that is not refused closes RunHost to new Uruchomienia and
# Aktualizacje under its lock.
KNOWN_FINDINGS: tuple[Excuse[Shape], ...] = ()


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines = [
        "Jedno Uruchomienie naraz i brak zamknięcia Centrum w trakcie pracy: sprawdzenie wyczerpujące",
        "",
    ]
    new = known = gaps = vacuous = 0
    shown: dict[tuple[object, ...], str] = {}
    excuses_shown: set[tuple[str, str]] = set()
    for report in reports:
        lines.append(f"zakres {report.scope.name}: {report.scope.describe()}")
        lines.append(
            f"  harmonogramy: {report.schedules}, różne stany: {report.states}, "
            f"zamknięcia bez trwającego Uruchomienia: {report.clean_closes}, czas: {report.seconds:.1f} s"
        )
        for missing in report.vacuous():
            vacuous += 1
            lines.append(f"  {missing}")
        for gap, trace in report.gaps.items():
            gaps += 1
            lines.append(f"  LUKA MODELU: {gap}")
            lines.extend(f"    {number}. {step}" for number, step in enumerate(trace, start=1))
        for signature, (violation, trace) in sorted(report.counterexamples.items(), key=lambda item: str(item[0])):
            found = excused(violation.rule, signature, known=KNOWN_FINDINGS)
            if found is not None:
                excuses_shown.add((found[1].name, report.scope.name))
            if found is not None and not strict:
                known += signature not in shown
                lines.append(f"  {excuse_line(*found)}")
            else:
                new += signature not in shown
                lines.append(f"  NARUSZENIE {violation.rule}: {violation.text}")
            if signature in shown:
                lines.append(f"    kontrprzykład jak w zakresie {shown[signature]}")
                continue
            shown[signature] = report.scope.name
            lines.extend(f"    {number}. {step}" for number, step in enumerate(trace, start=1))
        lines.append("")
    finished = [report.scope.name for report in reports if not report.gaps]
    disappeared = gone_lines(finished, excuses_shown, known=KNOWN_FINDINGS)
    lines.extend(disappeared)
    verdict_line, code = verdict(
        "URUCHOMIENIA",
        new=new + vacuous,
        gone=len(disappeared),
        known=known,
        gaps=gaps,
        gap_reason=": kod używa threading w sposób, którego model nie obejmuje.",
    )
    lines.append(verdict_line)
    return Outcome(lines, code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustive check of one Uruchomienie at a time and no shutdown during one."
    )
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        action="append",
        help="one scope; default: all",
    )
    parser.add_argument("--strict", action="store_true", help="report known findings as violations too")
    arguments = parser.parse_args(argv)
    drift = rozjazd_modelu.rozjazd(Path(__file__).resolve().parents[1], REPO_ROOT)
    if (failure := rozjazd_modelu.porazka_w_ci(drift, "URUCHOMIENIA")) is not None:
        print(failure)
        return 1
    reports = [explore(SCOPES[name]) for name in (arguments.scope or SCOPES)]
    outcome = summarize(reports, strict=arguments.strict)
    if drift is not None:
        print(f"UWAGA: {drift}\n")
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
