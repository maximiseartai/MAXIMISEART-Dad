"""Metryki: historia Uruchomień każdego procesu z katalogu procesów z plików metryk, z P50/P95 i rozkładem wyników.

Pliki są czytane przy każdym odczycie, więc rekord dopisany spoza Centrum, np.
przez skrypt dla maszyn, widać bez restartu serwera. Walidację rekordów, pomijanie
niepoprawnych i reguły P50/P95 daje ``telemetry``; Centrum ich nie powtarza.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import Catalog
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.domain import PHASES
from rozliczenia.telemetry import MINIMUM_STATISTIC_SAMPLES, MetricsStore, comparable_records, statistics_for

_RECENT_WEEKS = 8


CentrumStarted = Mapping[tuple[str, str], str | None]
"""Identyfikator Uruchomienia z Centrum po parze (proces, ``started_at``) z ``CentrumRuns.started``."""


def read_runs(catalog: Catalog, centrum_started: CentrumStarted) -> list[contract.ProcessRun]:
    """Uruchomienia procesu każdego procesu z katalogu ``catalog`` z jego plików metryk, od najnowszego."""

    return _runs(catalog, _records(catalog), centrum_started)


def read_metrics(catalog: Catalog, today: date, centrum_started: CentrumStarted) -> contract.Metrics:
    """Metryki procesów katalogu ``catalog``; statystyki każdego procesu tylko w trybach jego widoku."""

    records = _records(catalog)
    runs = _runs(catalog, records, centrum_started)
    since = today - timedelta(weeks=_RECENT_WEEKS)
    return contract.Metrics(
        phases=list(PHASES),
        minimum_completed_runs=MINIMUM_STATISTIC_SAMPLES,
        runs=runs,
        statistics=[
            _statistics(kind.key, mode, catalog.metrics(kind.key).counter_names, records[kind.key], runs)
            for kind in catalog.kinds
            for mode in kind.view.modes
        ],
        recent=contract.RecentResults(
            weeks=_RECENT_WEEKS,
            results=_results(run for run in runs if run.started_at.astimezone().date() >= since),
        ),
    )


def _records(catalog: Catalog) -> dict[contract.ProcessKey, list[dict[str, Any]]]:
    return {kind.key: catalog.metrics(kind.key).read() for kind in catalog.kinds}


def _runs(
    catalog: Catalog,
    records: Mapping[contract.ProcessKey, list[dict[str, Any]]],
    centrum_started: CentrumStarted,
) -> list[contract.ProcessRun]:
    return sorted(
        (
            _run(process, catalog.kind(process).title, record, centrum_started)
            for process, process_records in records.items()
            for record in process_records
        ),
        key=lambda run: run.started_at,
        reverse=True,
    )


def _run(
    process: contract.ProcessKey, label: str, record: dict[str, Any], centrum_started: CentrumStarted
) -> contract.ProcessRun:
    started = (process, record["started_at"])
    return contract.ProcessRun(
        process=process,
        process_label=label,
        started_at=datetime.fromisoformat(record["started_at"]).astimezone(timezone.utc),
        mode=record["mode"],
        period=record["period"],
        result=record["result"],
        total_duration_ms=record["total_duration_ms"],
        phase_durations=[
            contract.PhaseDuration(phase=phase, duration_ms=record["phase_durations_ms"][phase]) for phase in PHASES
        ],
        # Rekord metryk nie mówi, skąd wystartował (schemat bez zmian); Centrum pamięta swoje Uruchomienia samo.
        origin="centrum" if started in centrum_started else "cmd",
        run_id=centrum_started.get(started),
        # Rekord wersji 1 nie ma ``stop``: rodzaju jego Zatrzymania nie zgadujemy.
        stop_kind=stop["kind"] if (stop := record.get("stop")) else None,
    )


def _statistics(
    process: contract.ProcessKey,
    mode: contract.RunMode,
    counter_names: frozenset[str],
    records: list[dict[str, Any]],
    runs: list[contract.ProcessRun],
) -> contract.ModeStatistics:
    statistics = statistics_for(records, mode, counter_names)
    return contract.ModeStatistics(
        process=process,
        mode=mode,
        completed_runs=len(comparable_records(records, mode, counter_names)),
        percentiles=None
        if statistics is None
        else contract.Percentiles(
            p50_ms=statistics["total"][0],
            p95_ms=statistics["total"][1],
            phases=[
                contract.PhasePercentiles(phase=phase, p50_ms=statistics[phase][0], p95_ms=statistics[phase][1])
                for phase in PHASES
            ],
        ),
        results=_results(run for run in runs if run.process == process and run.mode == mode),
    )


def _results(runs: Iterable[contract.ProcessRun]) -> contract.ResultCounts:
    """Przerwane bez rodzaju (stary rekord) liczą się jako zatrzymane, nie jako błąd."""

    counted = list(runs)
    results = [run.result for run in counted]
    failed = sum(run.stop_kind == "for_maks" for run in counted)
    return contract.ResultCounts(
        ok=results.count("OK"),
        needs_review=results.count("WYMAGA_SPRAWDZENIA"),
        stopped=results.count("BLAD_KRYTYCZNY") - failed,
        failed=failed,
    )


def previewed_periods(store: MetricsStore) -> frozenset[str]:
    """Okresy, dla których historia metryk ma udany podgląd bez zapisu (DRY-RUN z wynikiem OK).

    Nieczytelny plik metryk oznacza „nie było podglądu”.
    """

    try:
        records = store.read()
    except OSError:
        return frozenset()
    return frozenset(record["period"] for record in records if (record["mode"], record["result"]) == ("DRY-RUN", "OK"))


def last_results(store: MetricsStore) -> dict[str, contract.RunResult]:
    """Wynik ostatniego Uruchomienia procesu (najpóźniejszy start) każdego okresu z historii metryk.

    Nieczytelny plik metryk oznacza „nie było Uruchomień”.
    """

    try:
        records = store.read()
    except OSError:
        return {}
    last: dict[str, dict[str, Any]] = {}
    for record in records:
        known = last.get(record["period"])
        if known is None or _started(record) > _started(known):
            last[record["period"]] = record
    return {period: record["result"] for period, record in last.items()}


def _started(record: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(record["started_at"])


def metrics_router(catalog: Catalog, today: Callable[[], date], centrum_runs: CentrumRuns) -> APIRouter:
    router = APIRouter(prefix="/api/metrics", tags=["metryki"])

    @router.get("", operation_id="getMetrics", responses={500: {"model": contract.Problem}})
    def metrics() -> contract.Metrics:
        try:
            return read_metrics(catalog, today(), centrum_runs.started())
        except OSError:
            raise contract.Refusal(500, "Nie udało się odczytać plików metryk. Odśwież kartę.") from None

    return router
