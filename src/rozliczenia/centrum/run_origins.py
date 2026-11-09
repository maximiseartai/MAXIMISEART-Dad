"""Które Uruchomienia procesu z plików metryk wystartowały z Centrum rozliczeń.

Schemat metryk się nie zmienia (Centrum i skrypt dla maszyn dopisują te same
rekordy), więc Centrum zapisuje we własnym lokalnym pliku obok ustawień, poza
gitem, proces i dokładny ``started_at`` rekordu metryk, który dopisało jego
Uruchomienie. Metryki porównują po tej parze; reszta historii ma pochodzenie
``.cmd``: stare Uruchomienia taty z dawnych launcherów i CLI oraz rekordy ze
skryptu dla maszyn. Obok pary leży identyfikator Uruchomienia w Centrum, ten
sam co w jego Logach Uruchomienia; linie sprzed #322 go nie mają.

Plik ma tylko bezpieczne fakty (proces, czas startu i identyfikator). Jego brak,
uszkodzenie albo nieudany zapis oznacza tylko, że Uruchomienie pokaże się jako
``.cmd``: nigdy nie zmienia wyniku Uruchomienia ani metryk.
"""

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
        """Zapamiętuje rekordy metryk ``process`` ze startem od ``since`` do ``until`` (UTC) jako Uruchomienie ``run_id``.

        Centrum prowadzi jedno Uruchomienie naraz, więc w tym oknie jest jego rekord.
        Uruchomienie spoza Centrum w tym samym czasie też zostałoby oznaczone; to rzadkie i tylko kosmetyczne.
        """

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
        """Identyfikator Uruchomienia z Centrum po parze (proces, ``started_at`` rekordu metryk).

        ``None``: linia sprzed #322, bez identyfikatora. Niepoprawne linie są pomijane.
        """

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
