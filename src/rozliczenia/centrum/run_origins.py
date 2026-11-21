from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.telemetry import MetricsStore

CENTRUM_RUNS_FILE: Final = "centrum-uruchomienia.jsonl"


class CentrumRuns:
    def __init__(self, config: Path) -> None:
        self._path = config / CENTRUM_RUNS_FILE
        self._lock = threading.Lock()

    def remember(
        self, process: common_contract.ProcessKey, run_id: str, metrics: MetricsStore, since: datetime, until: datetime
    ) -> None:
        try:
            started = [
                record["started_at"]
                for record in metrics.read()
                if since <= datetime.fromisoformat(record["started_at"]) <= until
            ]
            if not started:
                return
            lines = "".join(
                json.dumps({"process": process, "started_at": value, "run_id": run_id}) + "\n" for value in started
            )
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as log:
                    log.write(lines)
        except (OSError, UnicodeError, ValueError):
            return

    def started(self) -> Mapping[tuple[str, str], str | None]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {}
        runs: dict[tuple[str, str], str | None] = {}
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get("process"), str) and isinstance(
                entry.get("started_at"), str
            ):
                run_id = entry.get("run_id")
                runs[entry["process"], entry["started_at"]] = run_id if isinstance(run_id, str) else None
        return runs
