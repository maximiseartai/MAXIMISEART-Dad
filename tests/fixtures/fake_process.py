"""Sztuczny proces w pamięci: trzeci adapter seamu ``Process`` obok obu procesów taty."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, NoReturn

from rozliczenia.decision import Decision
from rozliczenia.domain import ProgressPhase
from rozliczenia.message import Message, StopError
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.process_run import Counter, Preview, Process
from rozliczenia.run_context import RunContext

PERIOD = "08_14_09_2026"
METRICS_WARNING = "Ostrzeżenie: Nie zapisano metryk; Proces testowy zakończył się niezależnie."
SECRET = "sekret klienta SYN-001"
# Komunikaty zakończeń sztucznego procesu z Podglądem bez zapisu: każde zatrzymanie bez własnego Komunikatu procesu
# dostaje jeden z nich.
ENDINGS = {
    "unexpected_failure": Message("BLAD_NIEOCZEKIWANY", "Wystąpił nieoczekiwany błąd.", "Proces testowy", "Uruchom ponownie."),
    "plan_not_shown": Message("BLAD_PLANU", "Nie udało się pokazać planu.", "Proces testowy", "Zgłoś to."),
    "summary_not_shown": Message("BLAD_PODSUMOWANIA", "Nie udało się pokazać podsumowania.", "Proces testowy", "Zgłoś to."),
}

Durations = Mapping[ProgressPhase, int]


@dataclass(frozen=True)
class Summary:
    phase_durations_ms: Durations


@dataclass(frozen=True)
class Inputs:
    period: str = PERIOD
    dry_run: bool = False


def stop_error(what: str) -> StopError:
    return StopError(Message(code="ZATRZYMANIE", what=what, where="Proces testowy", action="Uruchom ponownie."))


def all_phases(context: RunContext, before_save: Callable[[], None] = lambda: None) -> Summary:
    phases = PhaseRunner(context.observer, clock=context.clock.now)
    phases.check(lambda: None)
    phases.read(lambda: None)
    phases.plan(lambda: None, issue_count=lambda _planned: 0)
    before_save()
    phases.save(lambda: None)
    return Summary(phases.durations_ms())


def execute(_inputs: Inputs, context: RunContext) -> Summary:
    return all_phases(context)


def fail(*_args: object) -> NoReturn:
    raise RuntimeError(SECRET)


def fake_process(**overrides: Any) -> Process[Inputs, Summary, RunContext]:
    fields: dict[str, Any] = {
        "name": "Proces testowy",
        "counters": (Counter("items", lambda _summary: 1),),
        "result": lambda _inputs, _summary: "OK",
        "preview": Preview(ENDINGS["plan_not_shown"]),
        "metrics_failure_tail": "Proces testowy zakończył się niezależnie.",
        "execute": execute,
        "unexpected_failure": ENDINGS["unexpected_failure"],
        "summary_not_shown": ENDINGS["summary_not_shown"],
    }
    fields.update(overrides)
    return Process(**fields)


def records(metrics_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]


QUESTION = Decision(
    message=Message("PYTANIE", "Dane mogą być niepełne.", "Proces testowy", "Sprawdź liczby."),
    counts_title="Elementy",
    counts=[("pierwszy", 1)],
    question="Kontynuować?",
)


def asking_between_planning_and_saving(_inputs: Inputs, context: RunContext) -> Summary:
    def ask() -> None:
        if not context.conversation.confirm(QUESTION):
            raise stop_error("Przerwano zgodnie z odpowiedzią.")

    return all_phases(context, before_save=ask)
