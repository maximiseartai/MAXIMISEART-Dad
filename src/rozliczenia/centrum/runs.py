"""Uruchomienia procesu z Centrum rozliczeń: jedno naraz, w wątku roboczym, z podglądem przez SSE.

Centrum jest rozmówcą rdzenia Uruchomienia procesu (``process_run``) i
podglądem projekcji postępu (ADR 0002, ADR 0004). Ten moduł nie zna żadnego
procesu: proces podaje gotowe ``PreparedRun`` (wpis procesu z katalogu procesów, rdzeń
procesu z jego plikiem metryk i wejście procesu), a moduł
prowadzi z nim rdzeń i publikuje widoki dla przeglądarki. Widok podsumowania robi rdzeń
w swojej osłonie, więc jego awaria to błąd po silniku z Komunikatem z katalogu
procesu, ten sam wynik co w metrykach. Zatrzymania, ostrzeżenia i decyzja taty
przechodzą jako Komunikaty w trzech częściach.

Każda zmiana stanu to nowy niemutowalny widok (``contract.RunView``) z kolejnym
numerem. Strumień SSE wysyła najpierw bieżący widok, potem każdy kolejny, więc
ponowne podłączenie (odświeżenie, nowa karta) zaczyna od bieżącego stanu.
Decyzja taty czeka w stanie ``awaiting_decision``, aż przyjdzie przez API.

Zakończone Uruchomienie każdą drogą to jedna wartość (``EndedRun``): fakty
wyliczone raz, z których powstaje wynik na karcie, a czytają je działania po
wyniku (``AfterRun``: Logi Uruchomienia, Kontrola ilości, odczyty Uzupełnienia). Każde z nich dostaje
ją po wyniku, a przed końcem Uruchomienia w dzienniku, w osobnej osłonie: tylko
krótka praca lokalna, nigdy sieć, a jego wyjątek nie zmienia wyniku.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Final, Literal, Protocol

import anyio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from rozliczenia.centrum import contract
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.period_start import PeriodStarts
from rozliczenia.centrum.process_kind import PreparedRun
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.centrum.run_view import ProcessView, Shown
from rozliczenia.centrum.stops import NO_DIAGNOSIS, StoppedRun, Stops
from rozliczenia.centrum.threads import Signal, Threading
from rozliczenia.call_trace import CallTrace
from rozliczenia.decision import Decision
from rozliczenia.input_copy import InputCopy
from rozliczenia.message import Message
from rozliczenia.process_run import Finished, Outcome, Stop, StopEnding
from rozliczenia.progress import ProgressProjection, ProgressSnapshot

_STREAM_POLL_SECONDS: Final = 0.05
_KEEPALIVE_SECONDS: Final = 15.0
_RECONNECT_MS: Final = 1000
CONTINUE_HINT: Final = "przy decyzji wybierz „Kontynuuj”"
"""Jak w Centrum wyraża się zgodę w Decyzji taty (``Conversation.continue_hint``); ten sam tekst ma Komunikat po
odmowie w Uruchomieniu odtworzonym z Logów (``tools/odtworz_uruchomienie.py``)."""
# Ostatnia siatka adaptera: wyniku nie dało się pokazać, choć rdzeń zapisał już metryki.
_RESULT_NOT_SHOWN: Final = Message.to_maintainer(
    code="BLAD_WYNIKU",
    what="Nie udało się pokazać wyniku Uruchomienia procesu.",
    where="Centrum rozliczeń",
    check="Folder okresu",
)

# Tytuł wyniku przy Zatrzymaniu: tata poprawia sam, błąd do Maksa albo jego własna odmowa w Decyzji taty.
_STOP_HEADLINES: Final[Mapping[contract.StopKind, str]] = {
    "for_tata": "Do poprawy",
    "repeated": "Do poprawy",
    "for_maks": "Błąd",
    "declined": "Przerwano",
}

Ending = Literal["finished", StopEnding]


def verdict(
    *,
    ending: Ending,
    stop_kind: contract.StopKind | None,
    result: contract.RunResult,
    dry_run: bool,
    view: ProcessView[Any, Any],
) -> tuple[str, contract.NextAction]:
    """Tytuł wyniku i jedyna akcja po nim: jedna reguła dla karty na żywo i karty z Logów Uruchomienia.

    Tytuł Zatrzymania zależy od Rodzaju Zatrzymania (``stop_kind``, ``None`` bez Zatrzymania). Deklaracja
    procesu ``view`` daje tytuł wyniku po zapisie (``done``) i akcję, która otwiera to, co proces zapisał
    (``result_action``). Wynik „Wymaga sprawdzenia” ma własny tytuł, a po podglądzie proponuje ponowny
    podgląd po poprawce zamiast zapisu.
    """

    if stop_kind is not None:
        # Po błędzie podsumowania przy zapisie pliki już są: nie proponujemy ponownego uruchomienia.
        return _STOP_HEADLINES[stop_kind], view.result_action if ending == "after_engine" and not dry_run else "rerun"
    if result == "WYMAGA_SPRAWDZENIA":
        if dry_run:
            return "Podgląd wymaga sprawdzenia · nic nie zapisano", "rerun"
        return f"{view.done} · wymaga sprawdzenia", view.result_action
    return ("Podgląd gotowy · nic nie zapisano", "run") if dry_run else (view.done, view.result_action)


@dataclass(frozen=True)
class EndedRun:
    """Zakończone Uruchomienie procesu z Centrum, każdą drogą: fakty wyliczone raz, z których czyta karta i działania po wyniku."""

    info: contract.RunInfo
    core: Outcome[Shown[Any]] | None
    """Wynik rdzenia tak, jak go pokazuje Centrum; ``None``, gdy rdzeń nie oddał wyniku.

    Po błędzie samego adaptera (ostatnia siatka) ma jej Zatrzymanie, bez widoku i bez uwag technicznych,
    a czas i snapshot projekcji postępu zostają z rdzenia.
    """
    stopped: StoppedRun | None
    """Zatrzymanie, także ostatniej siatki adaptera; ``None``, gdy proces się zakończył."""
    progress: contract.Progress
    """Postęp z karty: ostatni widok projekcji, który dostała przeglądarka."""
    started_at: datetime
    ended_at: datetime
    input_copy: InputCopy | None = None
    """Kopia wejścia Uruchomienia (``PreparedRun.input_copy``) z tym, co czytniki przeczytały do jego końca."""

    @classmethod
    def of(
        cls,
        prepared: PreparedRun[Any, Any],
        core: Outcome[Shown[Any]] | None,
        *,
        info: contract.RunInfo,
        stopped: StoppedRun | None,
        progress: contract.Progress,
        started_at: datetime,
    ) -> EndedRun:
        """Koniec Uruchomienia ``prepared`` w tej chwili, z jego Kopią wejścia: w Centrum (``Run``) i w odtworzeniu."""

        return cls(info, core, stopped, progress, started_at, datetime.now(timezone.utc), prepared.input_copy)

    @property
    def result(self) -> contract.RunResult:
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
        """Ostatni snapshot projekcji postępu z rdzenia; ``None``, gdy rdzeń nie oddał wyniku."""

        return None if self.core is None else self.core.progress

    @property
    def duration_ms(self) -> int | None:
        """Czas uruchomienia; ``None``, gdy rdzeń nie oddał wyniku."""

        return None if self.core is None else self.core.total_duration_ms

    @property
    def files_unchanged(self) -> bool:
        """Pliki taty bez zmian; gdy rdzeń nie oddał wyniku, wiadomo to tylko o podglądzie bez zapisu."""

        return self.info.dry_run if self.core is None else self.core.files_unchanged

    @property
    def ending(self) -> Ending:
        return "finished" if self.stopped is None else self.stopped.stop.kind

    @property
    def stops(self) -> tuple[Message, ...]:
        return () if self.stopped is None else (self.stopped.stop.message,)

    @property
    def warnings(self) -> tuple[Message, ...]:
        return () if self.shown is None else self.shown.warnings

    def card(self, view: ProcessView[Any, Any]) -> contract.RunOutcome:
        """Wynik na karcie Uruchomienia z deklaracji procesu ``view`` (``verdict``)."""

        stopped = self.stopped
        headline, next_action = verdict(
            ending=self.ending,
            stop_kind=None if stopped is None else stopped.kind,
            result=self.result,
            dry_run=self.info.dry_run,
            view=view,
        )
        return contract.RunOutcome(
            result=self.result,
            headline=headline,
            ending=self.ending,
            next_action=next_action,
            stop_kind=None if stopped is None else stopped.kind,
            diagnosis=None if stopped is None else stopped.offer,
            report=None if stopped is None or stopped.report is None else stopped.report.state,
            stops=[contract.Message.of(message) for message in self.stops],
            warnings=[contract.Message.of(message) for message in self.warnings],
            technical_notes=list(self.technical_notes),
            summary=None if self.shown is None else self.shown.summary,
            files_unchanged=self.files_unchanged,
            opens=None if stopped is None else stopped.stop.message.dad_file,
            order_notes=None if self.shown is None else self.shown.notes,
        )


class AfterRun(Protocol):
    def run_ended(self, run: EndedRun) -> None:
        """Na wątku Uruchomienia, przed końcem Uruchomienia: tylko lokalny zapis w milisekundach, bez sieci.

        Wyjątek nie zmienia wyniku: ``RunHost.after`` zapisuje jego typ w dzienniku i woła następne działanie.
        """
        ...


# Odmowa w trakcie Aktualizacji narzędzia: uruchomienia procesu, zamknięcia Centrum albo innej aktualizacji.
_UPDATING = "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem {then}."
# Odmowa po przyjętym zamknięciu: wątek, który teraz by wystartował, zginąłby z końcem serwera.
_CLOSING = "Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem {then}."
# Odmowa w trakcie przywracania Kopii INTERMAX: uruchomienia procesu, aktualizacji, zamknięcia albo drugiego przywrócenia.
_RESTORING = "Trwa przywracanie Kopii INTERMAX. Poczekaj na jego wynik, potem {then}."
_RESTORE = "przywróć kopię jeszcze raz"


class RunHost:
    """Jedno Uruchomienie procesu naraz w obrębie serwera i jego widoki dla przeglądarki.

    To samo miejsce „jedno naraz” zajmuje Aktualizacja narzędzia (``begin_update``
    do ``end_update``): w jej trakcie start Uruchomienia jest odrzucony, a w trakcie
    Uruchomienia ona. Tak samo przywrócenie Kopii INTERMAX (``begin_restore`` do
    ``end_restore``): podmienia INTERMAX, więc nie biegnie obok Uporządkowania INTERMAX.
    ``shutdown_refusal()`` odmawia zamknięcia serwera, gdy Uruchomienie trwa (także gdy
    czeka na decyzję taty), trwa aktualizacja albo przywrócenie, a gdy nie odmawia, od
    tej chwili odrzuca każdy z tych startów. Początek i koniec każdego Uruchomienia
    trafiają do dziennika Centrum jako bezpieczne fakty, a rekord metryk każdego
    Uruchomienia z Centrum do ``CentrumRuns``. Zatrzymanie zakończonego Uruchomienia
    przejmuje jego właściciel (``stops``); Diagnoza i „Wyślij do Maksa” idą tylko do
    Zatrzymania bieżącego Uruchomienia, a nowy stan Zgłoszenia trafia na jego kartę.
    Działania po wyniku (``after_run``) biegną przed końcem Uruchomienia, więc
    przyjęte zamknięcie Centrum albo Aktualizacja narzędzia ich nie przerwie.
    Pierwszy widok niesie ``previous``, ostatnie Uruchomienie sprzed startu Centrum,
    a każdy start idzie do ``run_started`` (plik startu na dysku), zanim ruszy jego wątek;
    nieudany zapis startu trafia tylko do dziennika. Uruchomienie kończy się (``end``) pod tą
    samą blokadą co publikacja jego wyniku, a start następnego zostawia ten wynik w widokach,
    więc karta, która czyta strumień co chwilę, dostaje wynik każdego Uruchomienia.

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
        previous: contract.PastRun | None,
        run_started: Callable[[contract.RunInfo, datetime], None],
        after_run: Sequence[AfterRun],
        threads: Threading = threading,
        created: Callable[[Run, contract.RunEvent], None] = lambda _run, _last: None,
    ) -> None:
        self._log = log
        self._centrum_runs = centrum_runs
        self._stops = stops
        self._run_started = run_started
        self._after_run = tuple(after_run)
        self._threads = threads
        self._created = created
        self._lock = threads.Lock()
        self._sequence = 0
        first = contract.RunIdle(state="idle", previous=previous)
        self._events: list[contract.RunEvent] = [contract.RunEvent(sequence=0, view=first)]
        self._run: Run | None = None
        self._updating = False
        self._restoring = False
        self._closing = False

    def shutdown_refusal(self) -> str | None:
        """Dlaczego teraz nie można zamknąć Centrum (``Shutdown.refuse_while``); ``None``, gdy nic nie trwa.

        ``None`` przyjmuje zamknięcie w tej samej blokadzie: kolejne Uruchomienie ani aktualizacja już nie wystartują.
        """

        with self._lock:
            busy = self._busy_locked("zamknij Centrum rozliczeń")
            if busy is None:
                self._closing = True
            return busy

    def begin_update(self) -> None:
        """Zajmuje miejsce „jedno naraz” na Aktualizację narzędzia; ``contract.Refusal``, gdy jest zajęte."""

        with self._lock:
            if self._closing:
                raise contract.Refusal(409, _CLOSING.format(then="zaktualizuj narzędzie"))
            if self._updating:
                raise contract.Refusal(409, "Trwa już aktualizacja narzędzia. Poczekaj na jej wynik.")
            busy = self._busy_locked("zaktualizuj narzędzie")
            if busy is not None:
                raise contract.Refusal(409, busy)
            self._updating = True

    def end_update(self) -> None:
        with self._lock:
            self._updating = False

    def begin_restore(self) -> None:
        """Zajmuje miejsce „jedno naraz” na przywrócenie Kopii INTERMAX; ``contract.Refusal``, gdy jest zajęte."""

        with self._lock:
            if self._closing:
                raise contract.Refusal(409, _CLOSING.format(then=_RESTORE))
            busy = self._busy_locked(_RESTORE)
            if busy is not None:
                raise contract.Refusal(409, busy)
            self._restoring = True

    def end_restore(self) -> None:
        with self._lock:
            self._restoring = False

    def _busy_locked(self, then: str) -> str | None:
        """Co teraz trwa, z prośbą, żeby poczekać i ``then``; ``None``, gdy nic."""

        if self._updating:
            return _UPDATING.format(then=then)
        if self._restoring:
            return _RESTORING.format(then=then)
        run = self._run
        if run is None or run.ended:
            return None
        return (
            f"Trwa Uruchomienie procesu: {run.info.title}, okres {run.info.period}. "
            f"Poczekaj na jego wynik w Uruchomieniach, potem {then}."
        )

    def current(self) -> contract.RunEvent:
        with self._lock:
            return self._events[-1]

    def events_after(self, sequence: int) -> list[contract.RunEvent]:
        with self._lock:
            return [event for event in self._events if event.sequence > sequence]

    def start(self, prepared: PreparedRun[Any, Any]) -> contract.RunView:
        with self._lock:
            if self._closing:
                raise contract.Refusal(409, _CLOSING.format(then="uruchom proces"))
            if self._updating:
                raise contract.Refusal(409, _UPDATING.format(then="uruchom proces"))
            if self._restoring:
                raise contract.Refusal(409, _RESTORING.format(then="uruchom proces"))
            if self._run is not None and not self._run.ended:
                running = self._run.info
                raise contract.Refusal(
                    409,
                    f"Trwa już Uruchomienie procesu: {running.title}, okres {running.period}. "
                    "Poczekaj na jego wynik w Uruchomieniach.",
                )
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
        self._threads.Thread(target=run.work, name=f"uruchomienie-{run.info.id}", daemon=True).start()
        return view

    def decide(self, run_id: str, answer: contract.DecisionAnswer) -> contract.RunView:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise contract.Refusal(404, "Nie ma takiego Uruchomienia procesu.")
            if not run.awaiting_decision:
                raise contract.Refusal(409, "To Uruchomienie procesu nie czeka na decyzję.")
            run.answer(answer.answer == "continue")
            self._publish_locked(run.running_view())
            return self._events[-1].view

    def diagnose(self, run_id: str) -> contract.Diagnosis:
        return self._stops.diagnose(self._stopped(run_id))

    def send_report(self, run_id: str) -> contract.ReportState:
        return self._stops.send(self._stopped(run_id))

    def _stopped(self, run_id: str) -> StoppedRun:
        with self._lock:
            run = self._run
            if run is None or run.info.id != run_id:
                raise contract.Refusal(404, "Nie ma takiego Uruchomienia procesu.")
            stopped = run.stopped
        if not run.ended or stopped is None:
            raise contract.Refusal(409, NO_DIAGNOSIS)
        return stopped

    def remember(self, prepared: PreparedRun[Any, Any], run_id: str, since: datetime) -> None:
        """Zapamiętuje rekord metryk, który dopisało Uruchomienie ``run_id``, jako Uruchomienie z Centrum."""

        self._centrum_runs.remember(prepared.kind.key, run_id, prepared.metrics, since, datetime.now(timezone.utc))

    def failed(self, failure: Exception) -> None:
        """Wyniku Uruchomienia nie dało się pokazać: do dziennika tylko typ wyjątku, bez jego tekstu."""

        self._log.unexpected_failure(failure, where="wynik Uruchomienia procesu")

    def show_report(self, run_id: str, state: contract.ReportState) -> None:
        """Nowy stan Zgłoszenia w wyniku zakończonego Uruchomienia ``run_id`` dla każdej karty Centrum."""

        with self._lock:
            view = self._events[-1].view
            if isinstance(view, contract.RunFinished) and view.run.id == run_id:
                result = view.result.model_copy(update={"report": state})
                self._publish_locked(view.model_copy(update={"result": result}))

    def after(self, run: EndedRun) -> None:
        """Każde działanie po wyniku we własnej osłonie: błąd jednego nie pomija następnych ani nie zmienia wyniku."""

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

    def end(self, run: Run, result: contract.RunFinished) -> None:
        """Wynik Uruchomienia ``run`` na kartę i koniec Uruchomienia pod jedną blokadą.

        Start z drugiej karty, który czeka na koniec Uruchomienia, nie wejdzie między wynik a koniec (#723).
        """

        with self._lock:
            self._publish_locked(result)
            run.ended = True

    def publish(self, run: Run, view: contract.RunView) -> None:
        with self._lock:
            if self._run is run:
                self._publish_locked(view)

    def _publish_locked(self, view: contract.RunView) -> None:
        self._sequence += 1
        self._events.append(contract.RunEvent(sequence=self._sequence, view=view))


class Run:
    """Jedno Uruchomienie procesu i jednocześnie jego rozmówca w rdzeniu (``Interlocutor``).

    ``show_progress`` zamienia snapshot projekcji na widok i publikuje go.
    Wyjątek przy tym oznacza, że podgląd przestał się aktualizować: widok
    dostaje ``progress_stale``, a rdzeń odłącza podgląd bez wpływu na wynik.
    """

    def __init__(self, host: RunHost, prepared: PreparedRun[Any, Any], stops: Stops, threads: Threading) -> None:
        self._host = host
        self._prepared = prepared
        self._stops = stops
        self.info = prepared.info(uuid.uuid4().hex)
        self.started_at = datetime.now(timezone.utc)
        self._progress = prepared.progress_view(ProgressProjection().snapshot)
        self._stale = False
        self._decided: Signal = threads.Event()
        self._consent = False
        self.awaiting_decision = False
        self.ended = False
        self.stopped: StoppedRun | None = None

    def running_view(self) -> contract.RunRunning:
        return contract.RunRunning(
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
            core = prepared.conduct(self)
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
            contract.RunFinished(
                state="finished", run=self.info, progress=self._progress, progress_stale=self._stale, result=result
            ),
        )

    def _ended(self, core: Outcome[Shown[Any]] | None, stop: Stop | None, since: datetime) -> EndedRun:
        return EndedRun.of(
            self._prepared,
            core,
            info=self.info,
            stopped=self._stops.ended(self.info, stop, shown=self._show_report),
            progress=self._progress,
            started_at=since,
        )

    def _show_report(self, state: contract.ReportState) -> None:
        self._host.show_report(self.info.id, state)

    def answer(self, consent: bool) -> None:
        """Wywoływane przez ``RunHost.decide`` pod blokadą hosta."""

        self._consent = consent
        self.awaiting_decision = False
        self._decided.set()

    # Decyzja taty w trakcie silnika (Conversation); wejście procesu przychodzi z ustawień.

    @property
    def continue_hint(self) -> str:
        return CONTINUE_HINT

    def confirm(self, decision: Decision) -> bool:
        self._decided.clear()
        self.awaiting_decision = True
        self._host.publish(
            self,
            contract.RunAwaitingDecision(
                state="awaiting_decision", run=self.info, progress=self._progress, decision=_decision_view(decision)
            ),
        )
        self._decided.wait()
        return self._consent

    # Podgląd postępu. Każde powiadomienie odświeża widok
    # na żywo; przeglądarka dostaje nowy widok tylko wtedy, gdy zmieniło się to, co pokazuje.

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


def _decision_view(decision: Decision) -> contract.Decision:
    return contract.Decision(
        question=decision.question,
        title=decision.title,
        message=contract.Message.of(decision.message),
        counts=contract.CountGroup(
            title=decision.counts_title,
            counts=[contract.Count(label=label, count=count) for label, count in decision.counts],
        ),
    )


def _sse(event: contract.RunEvent) -> str:
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
    200: {"description": "Strumień SSE; każde pole `data` to `RunEvent` (JSON).", "model": contract.RunEvent},
}


def runs_router(host: RunHost, starts: PeriodStarts) -> APIRouter:
    router = APIRouter(prefix="/api/runs", tags=["uruchomienia"])

    @router.get("/setup", operation_id="getRunSetup")
    def setup() -> contract.RunSetup:
        return starts.setup()

    @router.post("", operation_id="startRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def start(request: contract.RunRequest) -> contract.RunView:
        return host.start(starts.prepare(request))

    @router.get("/current", operation_id="getCurrentRun")
    def current() -> contract.RunView:
        return host.current().view

    @router.post("/{run_id}/decision", operation_id="decideRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def decide(run_id: str, answer: contract.DecisionAnswer) -> contract.RunView:
        return host.decide(run_id, answer)

    @router.get("/events", operation_id="streamRunEvents", response_class=StreamingResponse, responses=_STREAM_RESPONSES)
    def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(host),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/{run_id}/diagnosis", operation_id="diagnoseRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def run_diagnosis(run_id: str) -> contract.Diagnosis:
        return host.diagnose(run_id)

    @router.post("/{run_id}/report", operation_id="reportRun", responses=contract.NOT_FOUND_OR_CONFLICT)
    def send_report(run_id: str) -> contract.ReportState:
        return host.send_report(run_id)

    return router

