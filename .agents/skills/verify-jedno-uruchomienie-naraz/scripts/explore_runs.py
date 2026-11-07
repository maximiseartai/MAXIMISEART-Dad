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
  ``RunHost.start`` creates its ``_Run`` until ``RunHost.finished`` has written its end to the Centrum
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

Replaced: ``threading`` inside ``runs.py`` and ``shutdown.py`` by model primitives that hand control to
the checker; ``run_process`` by an engine with two steps and an optional Decyzja through the real
``_Run.confirm``; ``CentrumLog``, ``CentrumRuns`` and the start file (``run_started``) by steps that write
nothing, with no Uruchomienie before Centrum's start; the actions after the result
(``AfterRun``) by one step that writes nothing. ``ToolUpdates``
(``tool_updates.py``) is modelled by hand around the real ``begin_update``, ``end_update`` and
``Shutdown.close_for_update``: Git, pip and the restart guardian are one step that ends either without a
new version (or with a failure) or with the guardian started. Modelled by hand:
``stop_when_asked`` in ``server.py`` and uvicorn's graceful shutdown. After ``Shutdown.wait`` returns,
the server may end at any moment when no HTTP request is in flight; a request that arrived before
that is served to the end. Any other ``threading`` use in the two files stops the check as LUKA MODELU, and so does
a modelled thread that waits on something outside the model (a real lock or Event, ``time.sleep``) for
``STALL_SECONDS`` without a step.

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
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, ModuleType, SimpleNamespace
from typing import Any, Literal

from greenlet import getcurrent, greenlet  # type: ignore[import-untyped]  # greenlet ships no type hints

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from rozliczenia import process_run
from rozliczenia.centrum import contract, runs, shutdown
from rozliczenia.centrum.catalog import PREPARATION
from rozliczenia.decision import Decision
from rozliczenia.message import Message
from rozliczenia.preparation_process import PROCESS
from rozliczenia.progress import ProgressProjection
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


# --- Scheduler: one modelled thread runs at a time, from one step to the next ------------------------
#
# Each modelled thread is a greenlet on the checker's own OS thread. With an OS thread each, every step was a
# hand-over through the kernel, several hundred thousand per check, and on a CI runner busy with other xdist workers
# each one waited for a free CPU until the check hit pytest's 120 s limit (#565). A greenlet switch does not wait.
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
class Actor:
    name: str
    status: Literal["running", "parked", "done"] = "running"
    pending: Pending | None = None
    go: str | None = None
    in_flight: bool = False
    run: Any = None  # the _Run whose work() this thread runs
    history: list[str] = field(default_factory=list)
    greenlet: greenlet | None = None


_ABORT = "\0abort"


def _current_actor() -> Actor:
    actor: Actor | None = getattr(getcurrent(), "actor", None)
    if actor is None:
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


class Scheduler:
    def __init__(self, trace: list[str], progress: Progress) -> None:
        self.home = getcurrent()  # the checker, which picks every step
        self.actors: list[Actor] = []
        self.trace = trace
        self.gaps: list[str] = []
        self.running: Actor | None = None  # the thread between two of its steps
        self.progress = progress
        progress.scheduler = self

    def spawn(self, name: str, body: Callable[[], None], run: Any = None) -> Actor:
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
                actor.status = "done"
                actor.pending = None

        # A thread spawned by another thread still ends into the checker, not into the thread that spawned it.
        actor.greenlet = greenlet(main, parent=self.home)
        actor.greenlet.actor = actor
        self.actors.append(actor)
        return actor

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
        actor.status = "parked"
        self.home.switch()
        outcome, actor.go = actor.go, None
        actor.pending = None
        assert outcome is not None  # release() set it before switching here
        if outcome == _ABORT:
            raise Abort()
        actor.history.append(f"{call} → {outcome}" if outcome else call)
        return outcome

    def note(self, text: str) -> None:
        self.trace.append(f"{_current_actor().name}: {text}")

    def settle(self) -> None:
        """Runs every released or new thread up to its next step or its end."""

        while (actor := next((actor for actor in self.actors if actor.status == "running"), None)) is not None:
            assert actor.greenlet is not None
            self.running = actor
            actor.greenlet.switch()
            self.running = None
            if self.progress.abandoned:
                raise Abort()
            self.progress.steps += 1

    def release(self, actor: Actor, outcome: str) -> None:
        actor.status = "running"
        actor.go = outcome

    def abort_all(self) -> None:
        for actor in self.actors:
            if actor.status == "parked":
                self.release(actor, _ABORT)
        self.settle()


# --- Model primitives in place of ``threading`` inside runs.py and shutdown.py --------------------------


class ModelLock:
    """``RunHost._lock``: entering is one step, which can be taken only while the lock is free."""

    def __init__(self, scheduler: Scheduler, label: str) -> None:
        self._scheduler = scheduler
        self.label = label
        self.owner: str | None = None

    def __enter__(self) -> bool:
        self._scheduler.step(f"wejście w blokadę {self.label}", enabled=lambda: self.owner is None)
        self.owner = _current_actor().name
        return True

    def __exit__(self, *_: object) -> None:
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
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
    ) -> None:
        if not daemon:
            raise ModelGap("wątek Uruchomienia nie jest daemon: koniec procesu Pythona by na niego czekał")
        self._scheduler = scheduler
        self._target = target

    def start(self) -> None:
        self._scheduler.step("start wątku Uruchomienia")
        run = getattr(self._target, "__self__", None)
        name = getattr(run, "model_name", "Uruchomienie")
        self._scheduler.spawn(f"wątek {name}", self._target, run)


class ModelThreading:
    """Stands in for the ``threading`` module inside one verified file."""

    def __init__(
        self,
        scheduler: Scheduler,
        module: str,
        lock_label: str,
        event_label: str,
        events: list[ModelEvent],
    ):
        self._scheduler = scheduler
        self._module = module
        self._lock_label = lock_label
        self._event_label = event_label
        self._events = events

    def Lock(self) -> ModelLock:  # noqa: N802 - same name as threading.Lock
        return ModelLock(self._scheduler, self._lock_label)

    def Event(self) -> ModelEvent:  # noqa: N802 - same name as threading.Event
        event = ModelEvent(self._scheduler, self._event_label)
        self._events.append(event)
        return event

    def Thread(self, *, target: Callable[[], None], name: str, daemon: bool = False) -> ModelThread:  # noqa: N802
        return ModelThread(self._scheduler, target=target, name=name, daemon=daemon)

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
                run.model_done = True

        return entry


class AfterRunSteps:
    """``AfterRun``: the actions after the result (Kontrola ilości into its queue file) are one step; nothing is written."""

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def run_ended(self, _run: object) -> None:
        self._scheduler.step("po wyniku: działania po wyniku Uruchomienia (plik kolejki)")
        run = _current_actor().run
        if run is not None:
            run.model_after_done = True


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

PREPARED: runs.PreparedRun[Any, Any] = runs.PreparedRun(
    declaration=PREPARATION,
    period="08_14_09_2026",
    process=PROCESS,
    inputs=SimpleNamespace(dry_run=False),
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
    created: list[Any]
    host: runs.RunHost
    shutdown: shutdown.Shutdown
    lock: ModelLock | None
    log: Any = None
    exited: bool = False
    closes_refused: int = 0
    starts_refused: int = 0
    updates_refused: int = 0
    restores_refused: int = 0
    updates: list[Update] = field(default_factory=list)
    restores: list[Restore] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)

    def in_progress(self) -> list[Any]:
        return [run for run in self.created if not run.model_done]

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
        for actor in self.scheduler.actors:
            if actor.name == CLOSE_TAB and actor.pending is not None and actor.pending.call in (
                CLOSE_LOG,
                REQUESTED_SET,
            ):
                return "między sprawdzeniem odmowy a przyjęciem prośby"
        return "przed sprawdzeniem odmowy"


@contextmanager
def harness(scheduler: Scheduler) -> Iterator[World]:
    events: list[ModelEvent] = []
    created: list[Any] = []
    world_box: list[World] = []

    class TrackedRun(runs._Run):
        def __init__(self, host: runs.RunHost, prepared: runs.PreparedRun[Any, Any], stops: Any) -> None:
            super().__init__(host, prepared, stops)
            self.model_name = f"Uruchomienie {len(created) + 1}"
            self.model_creator = _current_actor().name
            self.model_window = world_box[0].close_window()
            self.model_done = False
            self.model_after_done = False
            # A card that has read the stream up to this start: every view it reads later has a higher sequence.
            self.model_card_seen = host._sequence
            self.model_returned = False
            created.append(self)

        def work(self) -> None:
            super().work()
            self.model_returned = True

    def engine(process: Any, inputs: Any, interlocutor: Any, *, view: Any, metrics_path: Path) -> Any:
        variant = scheduler.step("silnik: Sprawdzanie … Zapisywanie", variants=("bez Decyzji", WITH_DECISION))
        if variant == WITH_DECISION:
            interlocutor.confirm(DECISION)
        scheduler.step("silnik kończy i dopisuje rekord metryk")
        ending = process_run.Finished("OK", {name: 0 for name in process.counter_names}, {})
        return process_run.Outcome(
            ending=ending,
            view=None,
            total_duration_ms=0,
            technical_notes=(),
            metrics_saved=True,
            progress=ProgressProjection().snapshot,
            files_unchanged=False,
        )

    class NoStops:
        def ended(self, info: object, stop: object, *, shown: object) -> None:
            if stop is not None:
                raise ModelGap("Zatrzymanie w Stops.ended; model kończy każde Uruchomienie sukcesem")

    # Each verified file sees its own stand-ins; the originals come back after the schedule.
    stand_ins = (
        ModelThreading(scheduler, "runs.py", "RunHost._lock", "_Run._decided", events),
        ModelThreading(scheduler, "shutdown.py", "Shutdown", "Shutdown._requested", events),
        engine,
        TrackedRun,
    )
    originals = _originals()
    for (module, name), value in zip(PATCHED, stand_ins, strict=True):
        setattr(module, name, value)
    try:
        log = LogSteps(scheduler)
        # Wired as in create_app (app.py): RunHost, then Shutdown.refuse_while(runs.shutdown_refusal).
        stopper = shutdown.Shutdown(log)  # type: ignore[arg-type]
        host = runs.RunHost(
            log,  # type: ignore[arg-type]
            CentrumRunsSteps(scheduler),  # type: ignore[arg-type]
            NoStops(),  # type: ignore[arg-type]
            previous=None,
            run_started=StartFileSteps(scheduler).run_started,
            after_run=[AfterRunSteps(scheduler)],
        )
        stopper.refuse_while(host.shutdown_refusal)
        lock = getattr(host, "_lock", None)
        world = World(
            scheduler,
            events,
            created,
            host,
            stopper,
            lock if isinstance(lock, ModelLock) else None,
            log=log,
        )
        world_box.append(world)
        yield world
    finally:
        _put_back(originals)


# What ``harness`` replaces in the verified files; ``explore`` puts it back itself after a schedule that never ends.
PATCHED: tuple[tuple[ModuleType, str], ...] = (
    (runs, "threading"),
    (shutdown, "threading"),
    (runs, "run_process"),
    (runs, "_Run"),
)


def _originals() -> list[tuple[ModuleType, str, object]]:
    return [(module, name, getattr(module, name)) for module, name in PATCHED]


def _put_back(originals: list[tuple[ModuleType, str, object]]) -> None:
    for module, name, value in originals:
        setattr(module, name, value)


def _start_tab(world: World, number: int) -> Callable[[], None]:
    def body() -> None:
        scheduler = world.scheduler
        scheduler.step("żądanie POST /api/runs dociera do serwera")
        _current_actor().in_flight = True
        try:
            view = world.host.start(PREPARED)
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
        scheduler.spawn(f"wątek {update.name}", _update_thread(world, update))
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
    def awaiting() -> Any | None:
        return next(
            (run for run in world.created if run.awaiting_decision and not run.ended),
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
            enabled=lambda: not any(actor.in_flight for actor in world.scheduler.actors),
        )
        world.exited = True
        for run in world.in_progress():
            doing = "czeka na Decyzję taty" if run.awaiting_decision else "trwa"
            world.violations.append(
                Violation(
                    "BEZ_ZAMKNIECIA_W_TRAKCIE",
                    ("BEZ_ZAMKNIECIA_W_TRAKCIE", run.model_window),
                    f"Centrum kończy pracę, a {run.model_name} (z: {run.model_creator}) {doing}; "
                    f"wystartowało {run.model_window}",
                )
            )
        for run in world.created:
            if run.model_done and not run.model_after_done:
                world.violations.append(
                    Violation(
                        "PO_WYNIKU_PRZED_KONCEM",
                        ("PO_WYNIKU_PRZED_KONCEM",),
                        f"Centrum kończy pracę po wyniku {run.model_name} (z: {run.model_creator}), "
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
    picks: list[int]
    widths: list[int]
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
    names = {run.info.id: run.model_name for run in world.created}
    return (
        tuple(
            (event.sequence, event.view.state, names.get(getattr(getattr(event.view, "run", None), "id", None)))
            for event in world.host._events
        ),
        tuple((run.model_card_seen, run.model_returned) for run in world.created),
        tuple(
            (
                actor.name,
                actor.status,
                tuple(actor.history),
                actor.pending.call if actor.pending else None,
                actor.in_flight,
            )
            for actor in world.scheduler.actors
        ),
        tuple(
            (
                run.model_name,
                run.model_creator,
                run.model_window,
                run.model_done,
                run.model_after_done,
                run.ended,
                run.awaiting_decision,
            )
            for run in world.created
        ),
        tuple((update.name, update.creator, update.window, update.done) for update in world.updates),
        tuple((restore.name, restore.creator, restore.window, restore.done) for restore in world.restores),
        world.lock.owner if world.lock is not None else None,
        tuple((event.label, event.flag) for event in world.events),
        world.exited,
    )


def execute(scope: Scope, prefix: Sequence[int], visited: set[object], progress: Progress) -> Execution:
    picks: list[int] = []
    widths: list[int] = []
    trace: list[str] = []

    def choose(count: int) -> int:
        index = prefix[len(picks)] if len(picks) < len(prefix) else 0
        picks.append(index)
        widths.append(count)
        return index

    scheduler = Scheduler(trace, progress)
    try:
        with harness(scheduler) as world:
            cut = _drive(world, scope, choose, picks, len(prefix), visited)
    except ModelGap as gap:
        return Execution(
            picks,
            widths,
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
        picks,
        widths,
        trace,
        world.violations,
        list(scheduler.gaps),
        cut,
        clean_close=world.exited and not world.violations,
        close_refused=world.closes_refused > 0,
        start_refused=world.starts_refused > 0,
        run_ended=any(run.model_done for run in world.created),
        update_refused=world.updates_refused > 0,
        update_restarted=any(update.restarted for update in world.updates) and not world.violations,
        restore_refused=world.restores_refused > 0,
        restore_done=any(restore.done for restore in world.restores) and not world.violations,
        results_shown_twice=sum(run.model_returned for run in world.created) > 1,
    )


def _drive(
    world: World,
    scope: Scope,
    choose: Callable[[int], int],
    picks: list[int],
    replay: int,
    visited: set[object],
) -> bool:
    """Runs one schedule to its end; ``True`` when it was cut short at an already explored state."""

    scheduler = world.scheduler
    if world.lock is None:
        scheduler.gaps.append("RunHost nie ma blokady _lock z threading.Lock()")
    for number in range(1, scope.start_tabs + 1):
        scheduler.spawn(f"karta Uruchom {number}", _start_tab(world, number))
    for number in range(1, scope.update_tabs + 1):
        scheduler.spawn(f"karta Zaktualizuj {number}", _update_tab(world, number))
    for number in range(1, scope.restore_tabs + 1):
        scheduler.spawn(f"karta Przywróć {number}", _restore_tab(world, number))
    scheduler.spawn(CLOSE_TAB, _close_tab(world, scope.close_clicks))
    scheduler.spawn("tata", _decision_tab(world, scope.decisions))
    scheduler.spawn("serwer", _server(world))
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
                    [f"{run.model_name} (z: {run.model_creator})" for run in running]
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
                for actor in scheduler.actors
                if actor.status == "parked" and actor.pending is not None and actor.pending.enabled()
                for variant in actor.pending.variants
            ]
            if not options:
                _check_results_on_card(world)
                return False
            state = _state(world)
            if len(picks) >= replay and state in visited:
                return True
            visited.add(state)
            actor, variant = options[choose(len(options))]
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
        if not run.model_returned:
            continue
        readable = [event.view for event in world.host._events if event.sequence > run.model_card_seen]
        if not any(isinstance(view, contract.RunFinished) and view.run.id == run.info.id for view in readable):
            world.violations.append(
                Violation(
                    "WYNIK_NA_KARCIE",
                    ("WYNIK_NA_KARCIE",),
                    f"{run.model_name} (z: {run.model_creator}) skończyło pracę, a karta, która śledzi strumień "
                    "od jego startu, nie dostaje jego wyniku: zostaje tylko w Historii",
                )
            )


def next_prefix(execution: Execution) -> list[int] | None:
    for depth in range(len(execution.picks) - 1, -1, -1):
        if execution.picks[depth] + 1 < execution.widths[depth]:
            return execution.picks[:depth] + [execution.picks[depth] + 1]
    return None


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
    originals = _originals()

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
            # The checker's thread stays blocked for good, so the verified files get their real threading back here.
            progress.abandoned = True
            _put_back(originals)
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
    prefix: list[int] | None = []
    while prefix is not None:
        execution = execute(report.scope, prefix, visited, progress)
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
        prefix = next_prefix(execution)


# --- Report -------------------------------------------------------------------------------------------

# Real defects in the current code, reported on every run until a code change fixes them: signature → why.
# Empty since „Zamknij” that is not refused closes RunHost to new Uruchomienia and Aktualizacje under its lock.
KNOWN_FINDINGS: dict[tuple[object, ...], str] = {}


@dataclass
class Outcome:
    new_violations: int
    known_findings: int
    gaps: int
    vacuous: int
    lines: list[str]

    @property
    def exit_code(self) -> int:
        if self.gaps:
            return 2
        return 1 if self.new_violations or self.vacuous else 0


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines = [
        "Jedno Uruchomienie naraz i brak zamknięcia Centrum w trakcie pracy: sprawdzenie wyczerpujące",
        "",
    ]
    new = known = gaps = vacuous = 0
    shown: dict[tuple[object, ...], str] = {}
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
            finding = KNOWN_FINDINGS.get(signature)
            if finding is not None and not strict:
                known += signature not in shown
                lines.append(f"  ZNANE USTALENIE ({violation.rule}): {finding}")
            else:
                new += signature not in shown
                lines.append(f"  NARUSZENIE {violation.rule}: {violation.text}")
            if signature in shown:
                lines.append(f"    kontrprzykład jak w zakresie {shown[signature]}")
                continue
            shown[signature] = report.scope.name
            lines.extend(f"    {number}. {step}" for number, step in enumerate(trace, start=1))
        lines.append("")
    if gaps:
        lines.append(f"URUCHOMIENIA: LUKA MODELU ({gaps}): kod używa threading w sposób, którego model nie obejmuje.")
    elif new or vacuous:
        lines.append(f"URUCHOMIENIA: NOWE NARUSZENIE ({new + vacuous})")
    elif known:
        lines.append(f"URUCHOMIENIA OK, ZNANE USTALENIA: {known}")
    else:
        lines.append("URUCHOMIENIA OK")
    return Outcome(new, known, gaps, vacuous, lines)


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
