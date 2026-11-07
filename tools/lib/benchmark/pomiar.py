"""Pomiar scenariusza: kilka uruchomień Przebiegu rozliczeń na lustrze, jeden naraz, i rekord dziennika."""

from __future__ import annotations

import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from benchmark import BenchmarkError
from benchmark.referencja import Reference, check_oracle
from benchmark.uruchomienie import Przebieg, run_przebieg
from repo import ROOT
import repo


RUNS = 3


LOCK_POLL_SECONDS = 0.5


def _spread(values: Sequence[int]) -> dict[str, int]:
    return {"mediana": round(statistics.median(values)), "min": min(values), "max": max(values)}


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def measurement_lock(references: Path) -> Path:
    """Plik blokady pomiarów obok folderu wyników referencyjnych (``reference`` → ``reference.lock``)."""

    return references.with_name(f"{references.name}.lock")


@contextmanager
def exclusive_measurement(lock: Path) -> Iterator[None]:
    """Jeden pomiar naraz: dwa pomiary dzielą procesor i zawyżają sobie czasy.

    Pomiary ze wspólnym folderem wyników referencyjnych (oficjalne pomiary ze wszystkich worktree) czekają na
    siebie. Blokadę zwalnia system także wtedy, gdy proces pomiaru zginie.
    """

    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        if not _try_lock(handle):
            print(f"Inny pomiar benchmarku trwa (blokada {lock}); ten czeka na jego koniec.", file=sys.stderr, flush=True)
            while not _try_lock(handle):
                time.sleep(LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _unlock(handle)


def measure(
    mirror: Path,
    scenario_name: str,
    config: Path,
    worker_template: Path,
    machine: str,
    reference: Reference | None = None,
) -> dict[str, Any]:
    """Rekord dziennika z ``RUNS`` uruchomień Przebiegu rozliczeń na lustrze i bramki poprawności ostatniego z nich."""

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    sha = repo.commit(ROOT, "HEAD")
    try:
        dirty: bool | None = bool(repo.git(ROOT, "status", "--porcelain").strip())
    except (OSError, subprocess.SubprocessError):
        dirty = None
    runs: list[Przebieg] = []
    with tempfile.TemporaryDirectory(prefix="benchmark-przebiegu-") as scratch:
        for run in range(1, RUNS + 1):
            runs.append(run_przebieg(ROOT, mirror, config, worker_template, Path(scratch)))
            print(f"Uruchomienie {run}/{RUNS}: {runs[-1].wall_ms} ms", flush=True)
    metrics = [przebieg.metrics for przebieg in runs]
    counters = metrics[0]["counters"]
    if any(record["counters"] != counters for record in metrics):
        raise BenchmarkError("Liczniki Przebiegu rozliczeń różnią się między uruchomieniami tego samego lustra.")
    phases = list(metrics[0]["phase_durations_ms"])
    return {
        "started_at": started_at,
        "git_sha": sha,
        "dirty": dirty,
        "machine": machine,
        "scenario": scenario_name,
        "runs": RUNS,
        "wall_ms": _spread([przebieg.wall_ms for przebieg in runs]),
        "start_procesu_ms": _spread([przebieg.start_ms for przebieg in runs]),
        "czas_uruchomienia_ms": _spread([record["total_duration_ms"] for record in metrics]),
        "zakonczenie_procesu_ms": _spread([przebieg.finish_ms for przebieg in runs]),
        "phase_durations_ms": {
            phase: _spread([record["phase_durations_ms"][phase] for record in metrics]) for phase in phases
        },
        "counters": counters,
        "oracle": None if reference is None else check_oracle(reference, mirror, runs[-1]),
    }
