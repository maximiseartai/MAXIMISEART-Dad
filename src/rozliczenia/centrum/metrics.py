"""Metryki: historia Uruchomień każdego procesu z katalogu procesów z plików metryk, z P50/P95 i rozkładem wyników.

Pliki są czytane przy każdym odczycie, więc rekord dopisany spoza Centrum, np.
przez skrypt dla maszyn, widać bez restartu serwera. Walidację rekordów, pomijanie
niepoprawnych i reguły P50/P95 daje ``telemetry``; Centrum ich nie powtarza.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import metrics as metrics_contract
from rozliczenia.centrum import refusal
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.catalog import Catalog
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.domain import PHASES, RunMode
from rozliczenia.telemetry import MINIMUM_STATISTIC_SAMPLES, MetricsStore, comparable_records, statistics_for

_RECENT_WEEKS = 8


CentrumStarted = Mapping[tuple[str, str], str | None]


class History:
    """Jedyne źródło Historii dla kart Uruchomień, Uwag taty i Metryk."""

    def __init__(self, catalog: Catalog, centrum_runs: CentrumRuns) -> None:
        self._catalog = catalog
        self._centrum_runs = centrum_runs

    def runs(self) -> list[metrics_contract.ProcessRun]:
        """Uruchomienia procesu od najnowszego; ``OSError``: plików metryk nie da się odczytać."""

        return _runs(self._catalog, _records(self._catalog), self._centrum_runs.started())

    def metrics(self, today: date) -> metrics_contract.Metrics:
        return _metrics(self._catalog, today, self._centrum_runs.started())


def _metrics(catalog: Catalog, today: date, centrum_started: CentrumStarted) -> metrics_contract.Metrics:
    records = _records(catalog)
    runs = _runs(catalog, records, centrum_started)
    since = today - timedelta(weeks=_RECENT_WEEKS)
    return metrics_contract.Metrics(
        processes=[metrics_contract.ProcessFacts(process=kind.key, label=kind.short_title) for kind in catalog.kinds],
        phases=list(PHASES),
        minimum_completed_runs=MINIMUM_STATISTIC_SAMPLES,
        runs=runs,
        statistics=[
            _statistics(kind.key, mode, catalog.metrics(kind.key).counter_names, records[kind.key], runs)
            for kind in catalog.kinds
            for mode in kind.view.modes
        ],
        recent=metrics_contract.RecentResults(
            weeks=_RECENT_WEEKS,
            results=_results(run for run in runs if run.started_at.astimezone().date() >= since),
        ),
    )


def _records(catalog: Catalog) -> dict[common_contract.ProcessKey, list[dict[str, Any]]]:
    return {kind.key: catalog.metrics(kind.key).read() for kind in catalog.kinds}


def _runs(
    catalog: Catalog,
    records: Mapping[common_contract.ProcessKey, list[dict[str, Any]]],
    centrum_started: CentrumStarted,
) -> list[metrics_contract.ProcessRun]:
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
    process: common_contract.ProcessKey, label: str, record: dict[str, Any], centrum_started: CentrumStarted
) -> metrics_contract.ProcessRun:
    """Uruchomienie z rekordu metryk ``record``. Rekord nie mówi, skąd wystartował (schemat bez zmian), więc Centrum
    pamięta swoje Uruchomienia samo (``centrum_started``), a rekord wersji 1 nie ma ``stop`` i rodzaju jego Zatrzymania
    nie zgadujemy."""

    started = (process, record["started_at"])
    return metrics_contract.ProcessRun(
        process=process,
        process_label=label,
        started_at=datetime.fromisoformat(record["started_at"]).astimezone(timezone.utc),
        mode=record["mode"],
        period=record["period"],
        result=record["result"],
        total_duration_ms=record["total_duration_ms"],
        phase_durations=[
            metrics_contract.PhaseDuration(phase=phase, duration_ms=record["phase_durations_ms"][phase]) for phase in PHASES
        ],
        origin="centrum" if started in centrum_started else "cmd",
        run_id=centrum_started.get(started),
        stop_kind=stop["kind"] if (stop := record.get("stop")) else None,
    )


def _statistics(
    process: common_contract.ProcessKey,
    mode: RunMode,
    counter_names: frozenset[str],
    records: list[dict[str, Any]],
    runs: list[metrics_contract.ProcessRun],
) -> metrics_contract.ModeStatistics:
    statistics = statistics_for(records, mode, counter_names)
    return metrics_contract.ModeStatistics(
        process=process,
        mode=mode,
        completed_runs=len(comparable_records(records, mode, counter_names)),
        percentiles=None
        if statistics is None
        else metrics_contract.Percentiles(
            p50_ms=statistics["total"][0],
            p95_ms=statistics["total"][1],
            phases=[
                metrics_contract.PhasePercentiles(phase=phase, p50_ms=statistics[phase][0], p95_ms=statistics[phase][1])
                for phase in PHASES
            ],
        ),
        results=_results(run for run in runs if run.process == process and run.mode == mode),
    )


def _results(runs: Iterable[metrics_contract.ProcessRun]) -> metrics_contract.ResultCounts:
    tones = Counter(run.tone for run in runs)
    return metrics_contract.ResultCounts(
        ok=tones["ok"], needs_review=tones["needs_review"], stopped=tones["stopped"], failed=tones["failed"]
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


def last_results(store: MetricsStore) -> dict[str, RunResult]:
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


def metrics_router(history: History, today: Callable[[], date]) -> APIRouter:
    router = APIRouter(prefix="/api/metrics", tags=["metryki"])

    @router.get("", operation_id="getMetrics", responses={500: {"model": common_contract.Problem}})
    def metrics() -> metrics_contract.Metrics:
        try:
            return history.metrics(today())
        except OSError:
            raise refusal.metrics_unreadable() from None

    return router
