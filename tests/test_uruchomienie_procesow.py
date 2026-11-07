"""Przebieg rozliczeń i Przygotowanie pliku zbiorczego przez rdzeń Uruchomienia procesu (``run_process``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from rozliczenia import preparation_process, settlement_process
from rozliczenia.collective_preparation import PreparationSummary
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.process_run import Outcome, Process, ProcessInputs, Stop, run_process
from rozliczenia.settlement_process import SettlementInputs
from rozliczenia.telemetry import MetricsStore

from tests.fixtures.fake_process import fail
from tests.fixtures.interlocutor import Tata
from tests.fixtures.preparation import PreparationFixture, incomplete_period_fixture, make_preparation_fixture, register_order
from tests.fixtures.settlement import NOT_A_PERIOD, PERIOD, make_fixture, make_preview_fixture
from tests.fixtures.workbooks import refused_by_copy

PHASES = {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}


@dataclass(frozen=True)
class ProcessCase:
    process: Process[Any, Any]
    inputs: Callable[[bool], ProcessInputs]
    period_files: tuple[Path, ...]
    client_data_markers: tuple[str, ...]
    templates: tuple[Path, ...]


def settlement(tmp_path: Path, *, period: str = PERIOD) -> ProcessCase:
    source, target_directory, config = make_fixture(tmp_path, period=period)
    worker_template = config.parent / "Wzorzec rozliczenia pracownika.xlsx"
    return ProcessCase(
        process=settlement_process.PROCESS,
        inputs=lambda dry_run: SettlementInputs(source, config, worker_template, dry_run),
        period_files=(target_directory,),
        client_data_markers=("syntetyczny adres", "#1"),
        templates=(worker_template,),
    )


def preparation(tmp_path: Path, *, period: str = PERIOD, fixture: PreparationFixture | None = None) -> ProcessCase:
    fixture = fixture or make_preparation_fixture(tmp_path)
    return ProcessCase(
        process=preparation_process.PROCESS,
        inputs=lambda dry_run: PreparationInputs(
            fixture.register_path,
            fixture.periods_directory,
            period,
            fixture.config_path,
            fixture.internal_template_path,
            fixture.collective_template_path,
            dry_run,
        ),
        period_files=(fixture.internal_settlement_path, fixture.collective_file_path),
        client_data_markers=("SYN-",),
        templates=(fixture.internal_template_path, fixture.collective_template_path),
    )


CASES = {"przebieg-rozliczen": settlement, "przygotowanie-pliku-zbiorczego": preparation}


def summary_view(_inputs: ProcessInputs, summary: object) -> object:
    return summary


def run(
    case: ProcessCase,
    metrics_path: Path,
    *,
    dry_run: bool = False,
    view: Callable[[Any, Any], object] = summary_view,
) -> Outcome[object]:
    return run_process(case.process, case.inputs(dry_run), Tata(), view=view, metrics_path=metrics_path)


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
@pytest.mark.parametrize("name", CASES)
def test_podsumowanie_ktorego_nie_da_sie_pokazac_konczy_zatrzymaniem_a_pliki_okresu_sa_tylko_po_uruchom(
    tmp_path: Path, name: str, dry_run: bool
) -> None:
    case = CASES[name](tmp_path)

    outcome = run(case, tmp_path / "metrics.jsonl", dry_run=dry_run, view=fail)

    not_shown = case.process.plan_not_shown if dry_run else case.process.summary_not_shown
    assert outcome.ending == Stop("after_engine", not_shown)
    assert [path.exists() for path in case.period_files] == [not dry_run] * len(case.period_files)


SETTLEMENT_COUNTERS = {
    "templates_total": 3,
    "templates_completed": 3,
    "rows": 3,
    "written": 2,
    "empty": 1,
    "planned": 0,
    "skipped": 0,
    "issues": 0,
}
# Domyślny syntetyczny Rejestr ma tylko urządzenia nieznane Regułom ilości: dwa ostrzeżenia ilości.
PREPARATION_COUNTERS = {"period_orders": 4, "successful_orders": 3, "skipped_empty_rows": 5, "warnings": 2}


def written(**copy_and_openpyxl: tuple[int, int]) -> dict[str, dict[str, int]]:
    """Drogi zapisu w rekordzie metryk: pliki kopią i drogą openpyxl dla podanych rodzajów pliku, dla reszty zera."""

    return {
        kind: dict(zip(("kopia", "openpyxl"), copy_and_openpyxl.get(kind, (0, 0)), strict=True))
        for kind in ("worker_settlement", "collective_file", "internal_settlement")
    }


NO_ROUTES = written()


# Syntetyczny Wzorzec rozliczenia pracownika i Wzorzec pliku zbiorczego przyjmuje kopia, a Rozliczenie wewnętrzne
# powstaje zawsze drogą openpyxl; Podgląd bez zapisu nie zapisuje żadnego pliku.
@pytest.mark.parametrize(
    ("name", "dry_run", "counters", "result", "routes"),
    [
        ("przebieg-rozliczen", False, SETTLEMENT_COUNTERS, "OK", written(worker_settlement=(3, 0))),
        ("przebieg-rozliczen", True, SETTLEMENT_COUNTERS | {"written": 0, "planned": 2}, "OK", NO_ROUTES),
        (
            "przygotowanie-pliku-zbiorczego",
            False,
            PREPARATION_COUNTERS,
            "WYMAGA_SPRAWDZENIA",
            written(collective_file=(1, 0), internal_settlement=(0, 1)),
        ),
        ("przygotowanie-pliku-zbiorczego", True, PREPARATION_COUNTERS, "OK", NO_ROUTES),
    ],
    ids=["przebieg-RUN", "przebieg-DRY-RUN", "przygotowanie-RUN", "przygotowanie-DRY-RUN"],
)
def test_rekord_metryk_ma_liczniki_procesu_i_drogi_zapisu_bez_sciezek_i_danych_klientow(
    tmp_path: Path,
    name: str,
    dry_run: bool,
    counters: dict[str, int],
    result: str,
    routes: dict[str, dict[str, int]],
) -> None:
    case = CASES[name](tmp_path)
    metrics_path = tmp_path / "metrics.jsonl"

    outcome = run(case, metrics_path, dry_run=dry_run)

    assert (outcome.result, outcome.metrics_saved) == (result, True)
    metrics_text = metrics_path.read_text(encoding="utf-8")
    [line] = metrics_text.splitlines()
    record = json.loads(line)
    assert (record["mode"], record["period"], record["completed"], record["result"]) == (
        "DRY-RUN" if dry_run else "RUN",
        PERIOD,
        True,
        result,
    )
    assert record["counters"] == counters
    assert record["routes"] == routes
    assert set(record["phase_durations_ms"]) == PHASES
    assert str(tmp_path) not in metrics_text
    assert [marker for marker in case.client_data_markers if marker in metrics_text] == []
    assert MetricsStore(metrics_path, case.process.counter_names).read() == [record]


@pytest.mark.parametrize(
    ("name", "routes"),
    [
        ("przebieg-rozliczen", written(worker_settlement=(0, 3))),
        ("przygotowanie-pliku-zbiorczego", written(collective_file=(0, 1), internal_settlement=(0, 1))),
    ],
)
def test_rekord_metryk_liczy_pliki_z_wzorca_ktorego_kopia_nie_przyjmuje_jako_droge_openpyxl(
    tmp_path: Path, name: str, routes: dict[str, dict[str, int]]
) -> None:
    case = CASES[name](tmp_path)
    for template in case.templates:
        refused_by_copy(template)

    run(case, tmp_path / "metrics.jsonl")

    [record] = MetricsStore(tmp_path / "metrics.jsonl", case.process.counter_names).read()
    assert record["routes"] == routes


@pytest.mark.parametrize(
    ("name", "period", "code"),
    [
        ("przebieg-rozliczen", NOT_A_PERIOD, "ZLY_PLIK_ZBIORCZY"),
        ("przygotowanie-pliku-zbiorczego", "zly okres", "ZLY_TOKEN_OKRESU"),
    ],
)
def test_okres_ktorego_nie_da_sie_ustalic_trafia_do_metryk_jako_nieznany(
    tmp_path: Path, name: str, period: str, code: str
) -> None:
    case = CASES[name](tmp_path, period=period)

    outcome = run(case, tmp_path / "metrics.jsonl")

    assert isinstance(outcome.ending, Stop)
    assert (outcome.ending.kind, outcome.ending.message.code) == ("stop", code)
    [record] = MetricsStore(tmp_path / "metrics.jsonl", case.process.counter_names).read()
    assert (record["period"], record["completed"], record["result"]) == ("nieznany", False, "BLAD_KRYTYCZNY")
    assert record["counters"] == dict.fromkeys(case.process.counter_names, 0)
    assert record["routes"] == NO_ROUTES


def test_problem_przebiegu_rozliczen_i_ostrzezenie_przygotowania_sa_licznikami_rekordu_metryk(tmp_path: Path) -> None:
    (tmp_path / "przebieg").mkdir()
    (tmp_path / "przygotowanie").mkdir()
    source, _target_directory, config = make_preview_fixture(tmp_path / "przebieg")
    worker_template = config.parent / "Wzorzec rozliczenia pracownika.xlsx"
    settled = run_process(
        settlement_process.PROCESS,
        SettlementInputs(source, config, worker_template, dry_run=True),
        Tata(),
        view=summary_view,
        metrics_path=tmp_path / "przebieg.jsonl",
    )
    prepared = run(
        preparation(tmp_path, fixture=incomplete_period_fixture(tmp_path / "przygotowanie")),
        tmp_path / "przygotowanie.jsonl",
        dry_run=True,
    )

    assert (settled.result, prepared.result) == ("WYMAGA_SPRAWDZENIA", "OK")
    [settlement_record] = MetricsStore(tmp_path / "przebieg.jsonl", settlement_process.PROCESS.counter_names).read()
    [preparation_record] = MetricsStore(
        tmp_path / "przygotowanie.jsonl", preparation_process.PROCESS.counter_names
    ).read()
    assert (settlement_record["result"], settlement_record["counters"]["issues"]) == ("WYMAGA_SPRAWDZENIA", 1)
    assert (preparation_record["result"], preparation_record["counters"]["warnings"]) == ("OK", 3)


METRICS_NOT_SAVED = {
    "przebieg-rozliczen": "Ostrzeżenie: Nie zapisano metryk; proces rozliczeń zakończył się niezależnie.",
    "przygotowanie-pliku-zbiorczego": (
        "Ostrzeżenie: Nie zapisano metryk; Przygotowanie pliku zbiorczego zakończyło się niezależnie."
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_nieudany_zapis_metryk_jest_ostrzezeniem_procesu_bez_zmiany_wyniku(tmp_path: Path, name: str) -> None:
    not_a_directory = tmp_path / "nie-katalog"
    not_a_directory.write_text("nie katalog", encoding="utf-8")

    outcome = run(CASES[name](tmp_path), not_a_directory / "metrics.jsonl", dry_run=True)

    assert (outcome.result, outcome.metrics_saved, outcome.technical_notes) == ("OK", False, (METRICS_NOT_SAVED[name],))


def test_zapisane_przygotowanie_okresu_z_samymi_zleceniami_nieskutecznymi_wymaga_sprawdzenia(tmp_path: Path) -> None:
    rows: list[dict[str, object] | None] = [
        register_order(number, datetime(2026, 9, 14, 8, number), successful="nie") for number in (1, 2)
    ]
    case = preparation(tmp_path, fixture=make_preparation_fixture(tmp_path, rows))

    outcome = run(case, tmp_path / "metrics.jsonl")

    assert outcome.result == "WYMAGA_SPRAWDZENIA"
    assert isinstance(outcome.view, PreparationSummary)
    assert "KOLUMNY_Z_OPISU" in [warning.code for warning in outcome.view.warnings]
