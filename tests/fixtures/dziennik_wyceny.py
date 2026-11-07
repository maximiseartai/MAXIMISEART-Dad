"""Dziennik Wyceny w efenix, który zostawiła poprzednia praca Centrum: linie w formacie pliku na dysku taty.

Test pisze dziennik sam, bez kodu Centrum, bo start Centrum ma czytać plik zapisany przez każdą wcześniejszą pracę
Centrum, także sprzed zmiany kodu, który go pisze.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from rozliczenia.centrum.logs_disk import name_of
from rozliczenia.centrum.run_logs import LoggedOrder, StartFacts

Line = dict[str, object]


def start_line(start: StartFacts) -> Line:
    """Pierwsza linia dziennika: start Uruchomienia."""

    return {
        "entry": "start Uruchomienia",
        "run_id": start.run_id,
        "process": start.process,
        "mode": start.mode,
        "period": start.period,
        "started_at": start.started_at.isoformat(),
    }


def begun_line(at: datetime, *, row: int, place: int, total: int) -> Line:
    """„Zaczynam zlecenie” z wiersza ``row``, ``place`` z ``total`` w przebiegu."""

    return {"at": at.isoformat(), "entry": "zaczynam zlecenie", "row": row, "place": place, "total": total}


def ended_line(at: datetime, order: LoggedOrder) -> Line:
    """„Zlecenie skończone” ze śladem zlecenia ``order``."""

    return {"at": at.isoformat(), "entry": "zlecenie skończone", "order": order.model_dump(mode="json")}


def end_line(at: datetime) -> Line:
    """„Koniec Uruchomienia” sprzed #910, bez wyniku."""

    return {"at": at.isoformat(), "entry": "koniec Uruchomienia"}


def _text(*lines: Line) -> str:
    """Treść dziennika: jedna linia JSON na wpis."""

    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def left_journal(logs: Path, start: StartFacts, *entries: Line) -> Path:
    """Dziennik Uruchomienia ``start`` w katalogu Logów ``logs`` z pierwszą linią i ``entries``."""

    path = logs / "dzienniki-wyceny" / Path(name_of(start)).with_suffix(".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_text(start_line(start), *entries), encoding="utf-8")
    return path
