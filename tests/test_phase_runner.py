from __future__ import annotations

from collections.abc import Callable

import pytest

from rozliczenia.domain import (
    PhaseFailed,
    PhaseStarted,
    ProgressEvent,
    ProgressPhase,
    ProgressProtocolError,
    StepReached,
)
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


def test_przetworzenie_szablonow_pracownika_w_innym_etapie_niz_zapisywanie_jest_bledem_kodu() -> None:
    runner = PhaseRunner(None)
    runner.check(lambda: None)
    runner.read(lambda: None)

    with pytest.raises(ProgressProtocolError):
        runner.plan(lambda: settled_outside_saving(runner), issue_count=lambda _planned: 0)


def test_krok_zapisywania_zgloszony_w_innym_etapie_jest_bledem_kodu() -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    runner.check(lambda: None)
    runner.read(lambda: None)

    with pytest.raises(ProgressProtocolError):
        runner.plan(lambda: runner.step("Zlecenia", worker="adrian.testowy", done=0, total=1), issue_count=lambda _planned: 0)

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


def test_obserwator_ktory_pada_jest_odlaczony_do_konca_uruchomienia_a_etapy_ida_dalej() -> None:
    seen: list[ProgressEvent] = []

    def failing(event: ProgressEvent) -> None:
        seen.append(event)
        raise RuntimeError("obserwator nie działa")

    runner = PhaseRunner(failing)
    run_whole(runner)

    assert [type(event) for event in seen] == [PhaseStarted]
    assert set(runner.durations_ms()) == set(ProgressPhase)


@pytest.mark.parametrize(
    "orders",
    [{"done": -1, "total": 1}, {"done": 0, "total": -1}, {"done": True, "total": 1}],
    ids=["ujemne-zrobione", "ujemna-suma", "prawda-zamiast-liczby"],
)
def test_krok_zapisywania_z_liczba_zlecen_inna_niz_nieujemna_calkowita_jest_bledem_kodu(orders: dict[str, int]) -> None:
    events: list[ProgressEvent] = []
    runner = PhaseRunner(events.append)
    runner.check(lambda: None)
    runner.read(lambda: None)
    runner.plan(lambda: None, issue_count=lambda _planned: 0)

    with pytest.raises(ProgressProtocolError):
        runner.save(lambda: runner.step("Zlecenia", worker="adrian.testowy", **orders))

    assert not any(isinstance(event, StepReached) for event in events)
