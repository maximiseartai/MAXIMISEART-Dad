"""Sekwencer etapów: tylko zachowanie, którego poprawne procesy nie mogą wywołać.

Pełne przebiegi z prawdziwą projekcją postępu jako obserwatorem są w testach
Przebiegu rozliczeń i Przygotowania pliku zbiorczego.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from rozliczenia.domain import PhaseFailed, ProgressEvent, ProgressProtocolError, StepReached
from rozliczenia.phase_runner import PhaseRunner


def fail() -> None:
    raise RuntimeError("syntetyczny błąd")


def run_whole(runner: PhaseRunner) -> None:
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None, issue_count=lambda _planned: 0)
    runner.save(lambda: None)


def run_check(runner: PhaseRunner) -> None:
    runner.check(lambda: None)


def fail_check(runner: PhaseRunner) -> None:
    with pytest.raises(RuntimeError):
        runner.check(fail)


@pytest.mark.parametrize(
    ("before", "stage"),
    [
        (lambda runner: None, "read"),
        (run_check, "check"),
        (run_whole, "save"),
        (run_whole, "check"),
        (fail_check, "read"),
        (fail_check, "check"),
    ],
    ids=[
        "przed-sprawdzaniem",
        "ponowiony",
        "po-zapisywaniu",
        "od-nowa-po-zapisywaniu",
        "po-failed",
        "ponowiony-po-failed",
    ],
)
def test_etap_poza_kolejnoscia_jest_bledem_kodu_przed_uruchomieniem_operacji(
    before: Callable[[PhaseRunner], None], stage: str
) -> None:
    runner = PhaseRunner(None)
    before(runner)
    calls: list[str] = []

    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: calls.append(stage))

    assert calls == []


def test_etap_uruchomiony_w_trakcie_poprzedniego_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    calls: list[str] = []

    with pytest.raises(ProgressProtocolError):
        runner.check(lambda: runner.read(lambda: calls.append("odczyt")))

    assert calls == []


def run_until_plan(runner: PhaseRunner) -> None:
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(
        lambda: None, templates=lambda result: ["Adrian Testowy", "Darek Fikcyjny"], issue_count=lambda _planned: 0
    )


def settled_outside_saving(runner: PhaseRunner) -> None:
    runner.each_template(lambda worker_name: pytest.fail("Szablon pracownika poza Zapisywaniem."))


@pytest.mark.parametrize("stage", ["check", "read", "plan"])
def test_przetworzenie_szablonow_pracownika_w_innym_etapie_niz_zapisywanie_jest_bledem_kodu(stage: str) -> None:
    runner = PhaseRunner(None)
    if stage != "check":
        runner.check(lambda: None)
    if stage == "plan":
        runner.read(lambda: None)

    counts = {"issue_count": lambda _planned: 0} if stage == "plan" else {}
    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: settled_outside_saving(runner), **counts)


@pytest.mark.parametrize("stage", ["check", "read", "plan"])
def test_krok_zapisywania_zgloszony_w_innym_etapie_jest_bledem_kodu(stage: str) -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    if stage != "check":
        runner.check(lambda: None)
    if stage == "plan":
        runner.read(lambda: None)

    counts = {"issue_count": lambda _planned: 0} if stage == "plan" else {}
    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: runner.step("Zlecenia", worker="adrian.testowy", done=0, total=1), **counts)

    assert not any(isinstance(event, StepReached) for event in events)


def test_krok_zapisywania_poza_trwajacym_zapisywaniem_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    run_whole(runner)

    with pytest.raises(ProgressProtocolError):
        runner.step("Znaczniki efenix w Pliku zbiorczym")


def test_przetworzenie_szablonow_pracownika_poza_trwajacym_zapisywaniem_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    run_until_plan(runner)

    with pytest.raises(ProgressProtocolError):
        settled_outside_saving(runner)


@pytest.mark.parametrize(
    ("counted", "failing", "next_stage"),
    [([("read", 2)], ("plan", 1), "save"), ([], ("read", -1), "plan")],
    ids=["malejaca-liczba-problemow", "ujemna-liczba-problemow"],
)
def test_niepoprawna_liczba_konczy_etap_przerwaniem_i_bledem_kodu(
    counted: list[tuple[str, int]], failing: tuple[str, int], next_stage: str
) -> None:
    runner = PhaseRunner(None)
    runner.check(lambda: None)
    for stage, count in counted:
        getattr(runner, stage)(lambda: None, issue_count=lambda result: count)

    stage, count = failing
    with pytest.raises(ProgressProtocolError):
        getattr(runner, stage)(lambda: None, issue_count=lambda result: count)

    calls: list[str] = []
    counts = {"issue_count": lambda _planned: 0} if next_stage == "plan" else {}
    with pytest.raises(ProgressProtocolError):
        getattr(runner, next_stage)(lambda: calls.append(next_stage), **counts)
    assert calls == []


def test_zapisywanie_bez_szablonow_pracownika_z_planu_jest_bledem_kodu() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    run_until_plan(runner)

    with pytest.raises(ProgressProtocolError):
        runner.save(lambda: None)

    assert isinstance(events[-1], PhaseFailed)
