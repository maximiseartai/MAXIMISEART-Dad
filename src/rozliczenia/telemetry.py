"""Lokalny, bezpieczny zapis i odczyt metryk uruchomień."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, TypedDict, get_args

from .domain import PHASES, ProgressPhase, StopKind
from .settlement_period import PERIOD_TOKEN_PATTERN
from .write_routes import Route, RouteCounts, TemplateKind


# Wersja 2 dodaje ``stop``: Rodzaj Zatrzymania i kod Komunikatu przerwanego Uruchomienia procesu.
# Wersja 3 dodaje ``routes``: ile zapisanych plików każdego rodzaju powstało każdą drogą zapisu z Wzorca (ADR 0008).
METRICS_SCHEMA_VERSION = 3
MINIMUM_STATISTIC_SAMPLES = 5
METRIC_MODES = frozenset({"RUN", "DRY-RUN"})
METRIC_RESULTS = frozenset({"OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"})
# Okres w rekordzie, gdy tokenu nie udało się ustalić.
UNKNOWN_PERIOD = "nieznany"
PERIOD_PATTERN = re.compile(rf"^(?:{PERIOD_TOKEN_PATTERN}|{UNKNOWN_PERIOD})$")
STOP_KINDS = frozenset(get_args(StopKind))
# Kod Komunikatu, nigdy jego treść (ADR 0004): wielkie litery, cyfry i podkreślenia, bez ścieżek i danych klientów.
STOP_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
ROUTE_NAMES = frozenset(route.value for route in Route)
TEMPLATE_KIND_NAMES = frozenset(kind.value for kind in TemplateKind)
_V1_FIELDS = frozenset(
    {
        "schema_version",
        "started_at",
        "mode",
        "period",
        "completed",
        "result",
        "total_duration_ms",
        "phase_durations_ms",
        "counters",
    }
)
# Pola rekordu każdej czytanej wersji schematu; stare rekordy zostają w historii taty.
_FIELDS_BY_VERSION = {1: _V1_FIELDS, 2: _V1_FIELDS | {"stop"}, METRICS_SCHEMA_VERSION: _V1_FIELDS | {"stop", "routes"}}


class RecordedStop(TypedDict):
    """Zatrzymanie w rekordzie metryk: Rodzaj Zatrzymania i kod Komunikatu, bez jego treści."""

    kind: StopKind
    code: str


CompletedResult = Literal["OK", "WYMAGA_SPRAWDZENIA"]
"""Wynik zakończonego Uruchomienia procesu; przerwane ma zamiast niego ``RecordedStop`` i wynik ``BLAD_KRYTYCZNY``."""


def metric_record(
    *,
    mode: str,
    period: str,
    started_at: str,
    total_duration_ms: int,
    phase_durations_ms: Mapping[ProgressPhase, int],
    ending: CompletedResult | RecordedStop,
    counters: Mapping[str, int],
    routes: RouteCounts = MappingProxyType({}),
) -> dict[str, Any]:
    """Rekord jednego Uruchomienia procesu w schemacie sprawdzanym przez ``MetricsStore``.

    ``ending``: wynik zakończonego Uruchomienia albo Zatrzymanie przerwanego, które w rekordzie ma wynik
    ``BLAD_KRYTYCZNY`` i ``stop``; zakończone ma ``stop`` równe ``None``. Okres spoza wzorca okresu trafia jako
    ``nieznany``, a etap bez zmierzonego czasu ma ``0`` ms. ``routes`` ma dla
    każdego rodzaju pliku z Wzorca liczbę zapisanych plików każdej drogi zapisu, a droga bez plików ``0``;
    domyślnie nie ma żadnego pliku. Rozliczenie wewnętrzne powstaje zawsze drogą openpyxl, więc dopiero
    rodzaj pliku mówi, czy kopia nie przyjęła Wzorca, który przyjmuje.
    """

    result, stop = (ending, None) if isinstance(ending, str) else ("BLAD_KRYTYCZNY", ending)
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "started_at": started_at,
        "mode": mode,
        "period": period if PERIOD_PATTERN.fullmatch(period) else UNKNOWN_PERIOD,
        "completed": result != "BLAD_KRYTYCZNY",
        "result": result,
        "total_duration_ms": total_duration_ms,
        "phase_durations_ms": {phase: phase_durations_ms.get(ProgressPhase(phase), 0) for phase in PHASES},
        "counters": dict(counters),
        "stop": stop,
        "routes": {kind.value: {route.value: routes.get((kind, route), 0) for route in Route} for kind in TemplateKind},
    }


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_valid_stop(stop: object, result: object) -> bool:
    if result != "BLAD_KRYTYCZNY":
        return stop is None
    if not isinstance(stop, dict) or set(stop) != {"kind", "code"}:
        return False
    kind, code = stop["kind"], stop["code"]
    return isinstance(kind, str) and kind in STOP_KINDS and isinstance(code, str) and bool(STOP_CODE_PATTERN.fullmatch(code))


def _are_valid_routes(routes: object) -> bool:
    return (
        isinstance(routes, dict)
        and set(routes) == TEMPLATE_KIND_NAMES
        and all(
            isinstance(counts, dict)
            and set(counts) == ROUTE_NAMES
            and all(_is_nonnegative_int(count) for count in counts.values())
            for counts in routes.values()
        )
    )


def _is_valid_record(record: object, counter_names: frozenset[str]) -> bool:
    if not isinstance(record, dict):
        return False
    version = record.get("schema_version")
    if type(version) is not int or _FIELDS_BY_VERSION.get(version) != frozenset(record):
        return False
    routes_valid = version != METRICS_SCHEMA_VERSION or _are_valid_routes(record["routes"])
    if not routes_valid or (version != 1 and not _is_valid_stop(record["stop"], record["result"])):
        return False
    started_at = record["started_at"]
    if not isinstance(started_at, str):
        return False
    try:
        timestamp = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    mode = record["mode"]
    result = record["result"]
    if not isinstance(mode, str) or mode not in METRIC_MODES:
        return False
    if not PERIOD_PATTERN.fullmatch(str(record["period"])):
        return False
    if not isinstance(result, str) or result not in METRIC_RESULTS:
        return False
    if type(record["completed"]) is not bool:
        return False
    if not _is_nonnegative_int(record["total_duration_ms"]):
        return False

    phase_durations = record["phase_durations_ms"]
    if not isinstance(phase_durations, dict) or set(phase_durations) != set(PHASES):
        return False
    if not all(_is_nonnegative_int(value) for value in phase_durations.values()):
        return False

    counters = record["counters"]
    if not isinstance(counters, dict) or set(counters) != counter_names:
        return False
    return all(_is_nonnegative_int(value) for value in counters.values())


class MetricsStore:
    """Dopisuje rekordy JSONL bez przechowywania danych skoroszytów.

    Każdy proces ma własną historię i własny zestaw liczników ``counter_names``.
    Rekordy z innym zestawem są odrzucane.
    ``read`` zwraca też rekordy wersji 1, które nie mają ``stop``: nie wiadomo,
    jakiego rodzaju było ich Zatrzymanie, oraz rekordy wersji 1 i 2 bez ``routes``:
    nie wiadomo, którą drogą powstały ich pliki.
    """

    def __init__(self, path: Path, counter_names: frozenset[str]):
        self.path = path.expanduser()
        self.counter_names = counter_names

    def append(self, record: dict[str, Any]) -> None:
        if not _is_valid_record(record, self.counter_names):
            raise ValueError("Niepoprawny rekord metryk.")
        serialized = (json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode(
            "utf-8"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as stream:
            separator = b""
            stream.seek(0)
            content = stream.read()
            if content:
                last_newline = content.rfind(b"\n")
                final_line_start = last_newline + 1
                final_line = content[final_line_start:]
                has_newline = False
                if last_newline == len(content) - 1:
                    final_line_start = content.rfind(b"\n", 0, last_newline) + 1
                    final_line = content[final_line_start:last_newline].rstrip(b"\r")
                    has_newline = True
                # Urwany zapis to linia, która nie jest JSON-em; pełny rekord innej wersji narzędzia zostaje.
                try:
                    json.loads(final_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    stream.truncate(final_line_start)
                else:
                    separator = b"" if has_newline else b"\n"
                stream.seek(0, os.SEEK_END)
            stream.write(separator + serialized)
            stream.flush()
            os.fsync(stream.fileno())

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _is_valid_record(record, self.counter_names):
                    records.append(record)
        return records


def percentile(values: list[float], proportion: float) -> float:
    """Zwraca interpolowany percentyl dla niepustej, posortowanej próby."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def comparable_records(
    records: list[dict[str, Any]],
    mode: str,
    counter_names: frozenset[str],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if _is_valid_record(record, counter_names) and record["mode"] == mode and record["completed"] is True
    ]


def statistics_for(
    records: list[dict[str, Any]],
    mode: str,
    counter_names: frozenset[str],
) -> dict[str, tuple[int, int]] | None:
    comparable = comparable_records(records, mode, counter_names)
    if len(comparable) < MINIMUM_STATISTIC_SAMPLES:
        return None

    durations: dict[str, list[float]] = {"total": []}
    for phase in PHASES:
        durations[phase] = []
    for record in comparable:
        durations["total"].append(float(record["total_duration_ms"]))
        phase_values = record.get("phase_durations_ms", {})
        for phase in durations:
            if phase != "total":
                durations[phase].append(float(phase_values[phase]))

    return {
        name: (round(percentile(values, 0.50)), round(percentile(values, 0.95)))
        for name, values in durations.items()
    }
