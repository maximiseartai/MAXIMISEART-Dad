"""Dziennik Wyceny w efenix w formacie pliku na dysku taty: linie, które zostawiła poprzednia praca Centrum, i ich odczyt.

Test pisze dziennik sam, bez kodu Centrum, bo start Centrum ma czytać plik zapisany przez każdą wcześniejszą pracę
Centrum, także sprzed zmiany kodu, który go pisze. Z tego samego powodu sprawdzenie ``verify-wycena-efenix`` czyta tu
dziennik, który zapisał kod Centrum (docs/agents/skille.md, „Co wyrocznia bierze z ``src``”): zmiana formatu w
``logs_disk`` ma wywrócić sprawdzenie, a nie przejść razem z nim.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from rozliczenia.centrum.logs_disk import name_of
from rozliczenia.centrum.run_logs import LoggedOrder, StartFacts

Line = dict[str, object]

JOURNALS_DIRECTORY = "dzienniki-wyceny"
BEGUN = "zaczynam zlecenie"
ENDED = "zlecenie skończone"


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

    return {"at": at.isoformat(), "entry": BEGUN, "row": row, "place": place, "total": total}


def ended_line(at: datetime, order: LoggedOrder) -> Line:
    """„Zlecenie skończone” ze śladem zlecenia ``order``."""

    return {"at": at.isoformat(), "entry": ENDED, "order": order.model_dump(mode="json")}


def end_line(at: datetime) -> Line:
    """„Koniec Uruchomienia” sprzed #910, bez wyniku."""

    return {"at": at.isoformat(), "entry": "koniec Uruchomienia"}


def _text(*lines: Line) -> str:
    """Treść dziennika: jedna linia JSON na wpis."""

    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def journal_path(logs: Path, start: StartFacts) -> Path:
    """Plik dziennika Uruchomienia ``start`` w katalogu Logów ``logs``, w którym szuka go start Centrum."""

    return logs / JOURNALS_DIRECTORY / Path(name_of(start)).with_suffix(".jsonl")


def left_journal(logs: Path, start: StartFacts, *entries: Line) -> Path:
    """Dziennik Uruchomienia ``start`` w katalogu Logów ``logs`` z pierwszą linią i ``entries``."""

    path = journal_path(logs, start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_text(start_line(start), *entries), encoding="utf-8")
    return path


def _entries(text: str) -> list[dict[str, object]]:
    """Wpisy dziennika ``text``; linii, której nie da się odczytać (urwany zapis), nie ma, jak przy starcie Centrum."""

    entries = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def begun_rows(text: str) -> set[int]:
    """Wiersze Pliku zbiorczego zleceń, które dziennik ``text`` zaczął („zaczynam zlecenie”)."""

    rows = set()
    for entry in _entries(text):
        row = entry.get("row")
        if entry.get("entry") == BEGUN and isinstance(row, int):
            rows.add(row)
    return rows


def ended_outcomes(text: str) -> dict[int, str]:
    """Wynik każdego zlecenia, które dziennik ``text`` skończył („zlecenie skończone”), po wierszu Pliku zbiorczego."""

    outcomes = {}
    for entry in _entries(text):
        order = entry.get("order")
        if entry.get("entry") != ENDED or not isinstance(order, dict):
            continue
        row, outcome = order.get("row"), order.get("outcome")
        if isinstance(row, int) and isinstance(outcome, str):
            outcomes[row] = outcome
    return outcomes
