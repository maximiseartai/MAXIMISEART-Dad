"""Wypisuje wiadomości operatora z wątków T3 Code tego repo w jednym tygodniu; użyj w polowaniu na powtarzane błędy.

Polowanie (skill ``.agents/skills/polowanie/SKILL.md``) szuka poprawek Maksa w wątkach agentów. Kto napisał wiadomość,
zapisuje T3 Code w chwili jej przyjęcia w bazie stanu serwera (``--baza``, domyślnie ``BAZA``): wiadomość ``user`` ma
pola ``createdBy`` (``ACTORS``) i ``creationSource`` (``SOURCES``) z kontraktu ``orchestrationV2`` T3. Wiadomość
operatora to ``createdBy`` ``user`` ze źródła okna T3 (``WINDOW``: aplikacja, przeglądarka, telefon) bez pola
``idleCompaction``, czyli bez ``/compact``, które okno wysyła samo po powrocie operatora. Tekst, który do wątku włożył
agent (``t3_thread_send``, także z polecenia ``t3 thread send``, ``delegate_task``, ``schedule_task``) albo serwer
(powiadomienie o PR, wynik delegata, wznowienie po restarcie), ma innego nadawcę albo inne źródło, więc tekstu
wiadomości narzędzie z niczym nie porównuje: poprawka, którą operator wkleił do kilku wątków, zostaje w każdym, ile
razy by ją agent przekazał dalej. Wątek należy do repo, gdy katalog jego projektu T3 (``workspace_root``) nazywa się
``REPO``.

Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego (``tydzien_polski``); bez
``--tydzien`` to ostatni pełny tydzień.

Linia na wiadomość, w kolejności czasu: ``<czas polski> | <wątek> | <treść>``, gdzie wątek to identyfikator wątku T3,
a treść ma najwyżej ``--znaki`` znaków, z ``" / "`` w miejscu końca linii. Ostatnia linia: ``POPRAWKI OPERATORA OK |
tydzień RRRR-MM-DD: n wiadomości operatora w w wątkach z m wiadomości user | <nadawca> k, …`` z liczbą pozostałych
wiadomości każdego nadawcy (``<createdBy>/<creationSource>`` albo ``COMPACT``). Brak bazy, baza bez tabel T3 i
wiadomość z nadawcą albo źródłem spoza kontraktu kończą się linią ``POPRAWKI OPERATORA FAIL`` i kodem 1. Narzędzie
tylko czyta bazę: treść wiadomości idzie na standardowe wyjście, a zapis jej w repozytorium, PR albo issue łamie
prywatność wątków Maksa, więc test narzędzia ma tylko tekst i identyfikatory wymyślone.

Granica: wiadomość wpisana poza oknem T3 (terminal Claude Code, ``claude -p``) nie ma wiersza w bazie, a wątki innej
maszyny (og-box) są w bazie tamtej maszyny, więc narzędzie biegnie tam osobno.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path, PurePath
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from tydzien_polski import WARSAW, last_full_week, midnight, week_of

PREFIX = "POPRAWKI OPERATORA"
REPO = "MAXIMISEART-Dad"
BAZA = Path.home() / ".t3" / "userdata" / "statev2.sqlite"
CHARS = 400
ACTORS = frozenset({"user", "agent", "system"})
SOURCES = frozenset({"web", "mobile", "mcp", "provider", "server"})
WINDOW = frozenset({"web", "mobile"})
OPERATOR = "operatora"
COMPACT = "/compact po powrocie"
QUERY = """
SELECT m.thread_id, m.created_at, m.payload_json, p.workspace_root
FROM orchestration_v2_projection_messages AS m
JOIN orchestration_v2_projection_threads AS t ON t.thread_id = m.thread_id
JOIN projection_projects AS p ON p.project_id = t.project_id
WHERE m.role = 'user' AND m.created_at >= ? AND m.created_at < ?
"""

EXAMPLES = """\
    .venv/bin/python tools/poprawki_operatora.py                          # ostatni pełny tydzień, baza T3 tej maszyny
    .venv/bin/python tools/poprawki_operatora.py --tydzien 2026-11-09 --baza <kopia bazy T3>
"""


class ShapeError(ValueError):
    """Wiadomość, której nadawcy narzędzie nie zna: baza T3 ma inny kształt niż kontrakt ``orchestrationV2``."""


@dataclass(frozen=True)
class Message:
    moment: datetime
    thread: str
    text: str


def sender(payload: dict[str, object]) -> str:
    """Nadawca wiadomości ``user`` z bazy T3: ``OPERATOR``, ``COMPACT`` albo ``<createdBy>/<creationSource>``."""

    actor, source = payload.get("createdBy"), payload.get("creationSource")
    if actor not in ACTORS or source not in SOURCES:
        raise ShapeError(f"nadawca {actor!r} ze źródła {source!r} spoza kontraktu orchestrationV2")
    if actor == "user" and source in WINDOW:
        return COMPACT if "idleCompaction" in payload else OPERATOR
    return f"{actor}/{source}"


def _iso(moment: datetime) -> str:
    """Chwila w zapisie ``created_at`` bazy T3 (``toISOString``), więc porównanie napisów to porównanie chwil."""

    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def messages(base: Path, since: datetime, until: datetime) -> Iterator[tuple[str, Message]]:
    """Nadawca i wiadomość każdej wiadomości ``user`` wątku repo z chwilą w ``[since, until)``."""

    with closing(sqlite3.connect(f"{base.resolve().as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute(QUERY, (_iso(since), _iso(until))).fetchall()
    for thread, created, payload_json, root in rows:
        if PurePath(root).name == REPO:
            payload = json.loads(payload_json)
            yield sender(payload), Message(datetime.fromisoformat(created), thread, str(payload.get("text") or ""))


def _line(message: Message, chars: int) -> str:
    text = " / ".join(line.strip() for line in message.text.splitlines() if line.strip())
    shown = text if len(text) <= chars else f"{text[:chars]}… ({len(text)} zn.)"
    return f"{message.moment.astimezone(WARSAW):%Y-%m-%d %H:%M} | {message.thread} | {shown}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tydzien", type=date.fromisoformat, help="Dzień tygodnia, RRRR-MM-DD (domyślnie ostatni pełny tydzień).")
    parser.add_argument("--baza", type=Path, default=BAZA, help="Baza stanu serwera T3 Code (domyślnie ~/.t3/userdata/statev2.sqlite).")
    parser.add_argument("--znaki", type=int, default=CHARS, help=f"Najwięcej znaków treści w linii (domyślnie {CHARS}).")
    args = parser.parse_args(argv)
    if not args.baza.is_file():
        print(f"{PREFIX} FAIL | brak bazy T3: {args.baza}")
        return 1
    week = last_full_week(datetime.now(UTC)) if args.tydzien is None else week_of(midnight(args.tydzien))
    try:
        found = list(messages(args.baza, midnight(week), midnight(week + timedelta(days=7))))
    except (sqlite3.DatabaseError, ValueError) as error:
        print(f"{PREFIX} FAIL | baza T3 {args.baza}: {error}")
        return 1
    kept = sorted((message for name, message in found if name == OPERATOR), key=lambda message: (message.moment, message.thread))
    for message in kept:
        print(_line(message, args.znaki))
    others = Counter(name for name, _ in found if name != OPERATOR)
    skipped = ", ".join(f"{name} {others[name]}" for name in sorted(others)) or "innych 0"
    threads = len({message.thread for message in kept})
    print(f"{PREFIX} OK | tydzień {week.isoformat()}: {len(kept)} wiadomości operatora w {threads} wątkach z {len(found)} wiadomości user | {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
