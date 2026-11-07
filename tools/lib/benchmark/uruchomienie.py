"""Jedno uruchomienie Przebiegu rozliczeń na lustrze tym samym rdzeniem Uruchomienia procesu co Centrum rozliczeń.

Czas ściany uruchomienia dzieli się na start procesu (do ``started_at`` rekordu
metryk), ``Czas uruchomienia`` (z rekordu metryk) i zakończenie procesu.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark import SCRIPT, BenchmarkError
from benchmark.lustro import PERIOD, period_directory, run_quietly
from rozliczenia.period_folder import PeriodFolder, collective_file_name


def remove_worker_settlements(folder: Path) -> None:
    """Każde uruchomienie startuje bez Folderu rozliczeń pracowników i bez folderów roboczych publikacji."""

    for path in (folder, *folder.parent.glob(f".{folder.name}.staging-*")):
        if path.is_dir():
            shutil.rmtree(path)


def _process_metrics(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if len(lines) != 1:
        raise BenchmarkError("Przebieg rozliczeń nie zapisał jednego rekordu metryk procesu.")
    record: dict[str, Any] = json.loads(lines[0])
    if not record.get("completed") or record.get("mode") != "RUN":
        raise BenchmarkError(f"Przebieg rozliczeń nie zakończył się w trybie RUN: {record.get('result')}.")
    return record


@dataclass(frozen=True)
class Przebieg:
    """Jedno uruchomienie Przebiegu rozliczeń na lustrze.

    ``start_ms``: od uruchomienia procesu do startu silnika (``started_at`` rekordu metryk).
    """

    wall_ms: int
    start_ms: int
    metrics: dict[str, Any]
    result: dict[str, Any]

    @property
    def finish_ms(self) -> int:
        """Zakończenie procesu: czas ściany po starcie procesu i po ``Czas uruchomienia``."""

        return self.wall_ms - self.start_ms - int(self.metrics["total_duration_ms"])


def run_przebieg(checkout: Path, mirror: Path, config: Path, worker_template: Path, scratch: Path) -> Przebieg:
    """Przebieg rozliczeń checkoutu ``checkout`` na lustrze, tym samym rdzeniem co Centrum rozliczeń."""

    source = period_directory(mirror) / collective_file_name(PERIOD)
    remove_worker_settlements(PeriodFolder.from_collective_file(source).worker_settlements)
    metrics_path = Path(tempfile.mkdtemp(prefix="uruchomienie-", dir=scratch)) / "metrics.jsonl"
    failure_log = mirror.parent / "ostatni-blad-przebiegu.txt"
    run = run_quietly(
        [
            checkout / SCRIPT,
            "settlement",
            "--source",
            source,
            "--config",
            config,
            "--worker-template",
            worker_template,
            "--metrics",
            metrics_path,
        ],
        failure_log,
    )
    if run.exit_code != 0:
        raise BenchmarkError(f"Przebieg rozliczeń zakończył się kodem {run.exit_code}; wyjście w {failure_log}.")
    metrics = _process_metrics(metrics_path)
    engine_started = datetime.fromisoformat(metrics["started_at"])
    start_ms = max(0, round((engine_started - run.spawned_at).total_seconds() * 1000))
    return Przebieg(run.wall_ms, start_ms, metrics, json.loads(run.stdout))
