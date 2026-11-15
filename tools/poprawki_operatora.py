"""Wypisuje wiadomości operatora z wątków T3 Code tego repo w jednym tygodniu; użyj w polowaniu na powtarzane błędy.

Polowanie (skill ``.agents/skills/polowanie/SKILL.md``) szuka poprawek Maksa w wątkach agentów. Kto napisał wiadomość,
zapisuje T3 Code w chwili jej przyjęcia w bazie stanu serwera (``--baza``, domyślnie ``BAZA``): wiadomość ``user`` ma
pola ``createdBy`` (``ACTORS``) i ``creationSource`` (``SOURCES``) z kontraktu ``orchestrationV2`` T3. Wiadomość
operatora to ``createdBy`` ``user`` ze źródła okna T3 (``WINDOW``: aplikacja, przeglądarka, telefon) bez pola
``idleCompaction``, czyli bez ``/compact``, które okno wysyła samo po powrocie operatora, oraz powód, który operator
wpisał w oknie przy odmowie zgody na narzędzie: T3 zapisuje go jako ``user/server`` z identyfikatorem
``approval-feedback:<prośba>`` (``FEEDBACK``), a narzędzie agenta ``t3_pending_request`` zgody nie rozstrzyga. Tekst,
który do wątku włożył agent (``t3_thread_send``, także z polecenia ``t3 thread send``, ``delegate_task``,
``schedule_task``) albo serwer (powiadomienie o PR, wynik delegata, wznowienie po restarcie), ma innego nadawcę albo
inne źródło, więc tekstu wiadomości narzędzie z niczym nie porównuje: poprawka, którą operator wkleił do kilku wątków,
zostaje w każdym, ile razy by ją agent przekazał dalej. Wątek należy do repo, gdy katalog jego projektu T3
(``workspace_root``) jest repo według ``is_repo``: nazywa się ``REPO`` albo jest checkoutem gita z origin ``ORIGIN``, więc
repo przeniesione do katalogu o innej nazwie i klon pod inną nazwą (og-box) liczą się w całości.

Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego (``tydzien_polski``); bez
``--tydzien`` to ostatni pełny tydzień.

Linia na wiadomość, w kolejności czasu: ``<czas polski> | <wątek> | <treść>``, gdzie wątek to identyfikator wątku T3,
a treść ma najwyżej ``--znaki`` znaków, z ``" / "`` w miejscu końca linii. Ostatnia linia: ``POPRAWKI OPERATORA OK |
tydzień RRRR-MM-DD: n wiadomości operatora w w wątkach z m wiadomości user | <nadawca> k, …`` z liczbą pozostałych
wiadomości każdego nadawcy (``<createdBy>/<creationSource>`` albo ``COMPACT``). Narzędzie tylko czyta bazę: treść
wiadomości idzie na standardowe wyjście, a zapis jej w repozytorium, PR albo issue łamie prywatność wątków Maksa, więc
test narzędzia ma tylko tekst i identyfikatory wymyślone.

Linia ``OK`` z zerem nie istnieje: tydzień bez wiadomości operatora w wątkach repo kończy się linią ``POPRAWKI OPERATORA
FAIL | tydzień RRRR-MM-DD: 0 wiadomości operatora w wątkach REPO z m wiadomości user | inne projekty T3 tej bazy: <katalog>
k, …`` i kodem 1, bo przy kilkuset wiadomościach operatora na tydzień zero częściej znaczy nieczytane wejście (repo
przeniesione do katalogu, który nie jest już checkoutem repo, a stary dostaje tylko wiadomości agentów) niż
tydzień bez poprawek, a liczba wiadomości operatora w innych projektach mówi, gdzie patrzeć. Przed liczeniem narzędzie
sprawdza wejście (``alive``), a każdy z tych stanów też kończy się linią ``FAIL`` z powodem i kodem 1: brak bazy albo
tabel T3, ``created_at`` wiadomości w innym typie albo zapisie niż tekst ``toISOString``, żaden projekt T3 repo
(``is_repo``), najnowsza wiadomość bazy sprzed końca tygodnia (baza, której T3 już nie pisze, jak
``state.sqlite`` po przejściu na ``statev2.sqlite``) i tydzień, który jeszcze trwa. Tak samo kończy się wiadomość wątku
repo z nadawcą albo źródłem spoza kontraktu.

Granica: wiadomość wpisana poza oknem T3 (terminal Claude Code, ``claude -p``) nie ma wiersza w bazie, a wątki innej
maszyny (og-box) są w bazie tamtej maszyny, więc narzędzie biegnie tam osobno. Projekt T3 w katalogu o innej nazwie,
który nie jest checkoutem gita (kopia bez ``.git``), nie jest repo: wiadomości z takiego katalogu idą do liczby innych
projektów, a nie do repo. Odpowiedź operatora na pytanie dostawcy
(identyfikator ``async-answer:``) ma nadawcę ``user/server`` taki sam jak odpowiedź agenta przez ``t3_pending_request``,
więc narzędzie liczy ją jako ``user/server`` (próbka ``ZNANE_LUKI`` w teście).
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path, PurePath
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import repo
from tydzien_polski import WARSAW, last_full_week, midnight, week_of

PREFIX = "POPRAWKI OPERATORA"
REPO = "MAXIMISEART-Dad"
ORIGIN = "maximiseartai/maximiseart-dad"
BAZA = Path.home() / ".t3" / "userdata" / "statev2.sqlite"
CHARS = 400
ACTORS = frozenset({"user", "agent", "system"})
SOURCES = frozenset({"web", "mobile", "mcp", "provider", "server"})
WINDOW = frozenset({"web", "mobile"})
OPERATOR = "operatora"
COMPACT = "/compact po powrocie"
FEEDBACK = "approval-feedback:"
QUERY = """
SELECT m.message_id, m.thread_id, m.created_at, m.payload_json, p.workspace_root
FROM orchestration_v2_projection_messages AS m
JOIN orchestration_v2_projection_threads AS t ON t.thread_id = m.thread_id
JOIN projection_projects AS p ON p.project_id = t.project_id
WHERE m.role = 'user' AND m.created_at >= ? AND m.created_at < ?
"""
ISO = "toISOString"
SHAPES = f"""
SELECT CASE
  WHEN typeof(created_at) <> 'text' THEN typeof(created_at)
  WHEN created_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-6][0-9].[0-9][0-9][0-9]Z' THEN '{ISO}'
  ELSE 'tekst w innym zapisie'
END, count(*), max(created_at)
FROM orchestration_v2_projection_messages GROUP BY 1
"""
ROOTS = "SELECT workspace_root FROM projection_projects"

EXAMPLES = """\
    .venv/bin/python tools/poprawki_operatora.py                          # ostatni pełny tydzień, baza T3 tej maszyny
    .venv/bin/python tools/poprawki_operatora.py --tydzien 2026-11-09 --baza <kopia bazy T3>
"""


class ShapeError(ValueError):
    """Wiadomość, której nadawcy narzędzie nie zna: baza T3 ma inny kształt niż kontrakt ``orchestrationV2``."""


class DeadInput(ValueError):
    """Wejście, z którego narzędzie nie przeczytałoby wiadomości tygodnia, więc zero nic by nie znaczyło."""


@dataclass(frozen=True)
class Message:
    moment: datetime
    thread: str
    text: str


def sender(message_id: str, payload: dict[str, object]) -> str:
    """Nadawca wiadomości ``user`` z bazy T3: ``OPERATOR``, ``COMPACT`` albo ``<createdBy>/<creationSource>``."""

    actor, source = payload.get("createdBy"), payload.get("creationSource")
    if actor not in ACTORS or source not in SOURCES:
        raise ShapeError(
            f"nadawca {actor!r} ze źródła {source!r} spoza kontraktu orchestrationV2"
        )
    if actor == "user" and source in WINDOW:
        return COMPACT if "idleCompaction" in payload else OPERATOR
    if actor == "user" and source == "server" and message_id.startswith(FEEDBACK):
        return OPERATOR
    return f"{actor}/{source}"


def is_repo(root: str) -> bool:
    """Czy katalog projektu T3 to repo: nazywa się ``REPO`` albo jest checkoutem gita, którego ``remote.origin.url``
    kończy się na ``ORIGIN`` (bez wielkości liter, ``.git`` i końcowego ``/``). Origin czyta lokalny git bez sieci
    i bez środowiska wołającego (``repo.git(isolated=True)``), więc ``GIT_DIR`` odziedziczony z hooka gita nie podmienia
    katalogu projektu; katalog, którego nie ma albo który nie jest checkoutem, nie ma origin."""

    if PurePath(root).name == REPO:
        return True
    if not Path(root).is_dir():
        return False
    try:
        url = repo.git(
            Path(root), "config", "--get", "remote.origin.url", isolated=True
        )
    except subprocess.CalledProcessError:
        return False
    return url.strip().rstrip("/").removesuffix(".git").lower().endswith(ORIGIN)


def _iso(moment: datetime) -> str:
    """Chwila w zapisie ``created_at`` bazy T3 (``toISOString``), więc porównanie napisów to porównanie chwil."""

    return (
        moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def alive(db: sqlite3.Connection, until: datetime) -> None:
    """Rzuca ``DeadInput``, gdy baza nie da wiadomości tygodnia kończącego się w ``until``: ``created_at`` w innym
    zapisie niż ``toISOString`` (``_iso``), brak projektu repo albo baza, której T3 nie pisał do końca tygodnia."""

    shapes = {shape: (count, newest) for shape, count, newest in db.execute(SHAPES)}
    if foreign := {
        shape: count for shape, (count, _) in shapes.items() if shape != ISO
    }:
        raise DeadInput(
            f"created_at wiadomości poza zapisem {ISO}: {', '.join(f'{shape} {count}' for shape, count in sorted(foreign.items()))}"
        )
    if not any(is_repo(root) for (root,) in db.execute(ROOTS)):
        raise DeadInput(
            f"żaden projekt T3 nie jest repo: katalog {REPO} albo checkout z origin {ORIGIN}"
        )
    newest = shapes.get(ISO, (0, None))[1]
    if newest is None or newest < _iso(until):
        raise DeadInput(
            f"najnowsza wiadomość bazy ({newest}) jest sprzed końca tygodnia {_iso(until)}: T3 pisze inną bazę albo od końca tygodnia nic nie zapisał"
        )


def _operator_elsewhere(message_id: str, payload: dict[str, object]) -> bool:
    """Czy wiadomość projektu spoza repo napisał operator; nadawca spoza kontraktu tam tylko jej nie liczy."""

    try:
        return sender(message_id, payload) == OPERATOR
    except ShapeError:
        return False


def messages(
    base: Path, since: datetime, until: datetime
) -> tuple[list[tuple[str, Message]], Counter[str]]:
    """Nadawca i wiadomość każdej wiadomości ``user`` wątku repo z chwilą w ``[since, until)`` z żywej bazy (``alive``)
    oraz liczba wiadomości operatora w tym czasie w każdym innym katalogu projektu T3."""

    with closing(sqlite3.connect(f"{base.resolve().as_uri()}?mode=ro", uri=True)) as db:
        alive(db, until)
        rows = db.execute(QUERY, (_iso(since), _iso(until))).fetchall()
    found = []
    elsewhere: Counter[str] = Counter()
    repo = {root: is_repo(root) for root in {row[4] for row in rows}}
    for message_id, thread, created, payload_json, root in rows:
        payload = json.loads(payload_json)
        if repo[root]:
            found.append(
                (
                    sender(message_id, payload),
                    Message(
                        datetime.fromisoformat(created),
                        thread,
                        str(payload.get("text") or ""),
                    ),
                )
            )
        elif _operator_elsewhere(message_id, payload):
            elsewhere[PurePath(root).name] += 1
    return found, elsewhere


def _line(message: Message, chars: int) -> str:
    text = " / ".join(
        line.strip() for line in message.text.splitlines() if line.strip()
    )
    shown = text if len(text) <= chars else f"{text[:chars]}… ({len(text)} zn.)"
    return f"{message.moment.astimezone(WARSAW):%Y-%m-%d %H:%M} | {message.thread} | {shown}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tydzien",
        type=date.fromisoformat,
        help="Dzień tygodnia, RRRR-MM-DD (domyślnie ostatni pełny tydzień).",
    )
    parser.add_argument(
        "--baza",
        type=Path,
        default=BAZA,
        help="Baza stanu serwera T3 Code (domyślnie ~/.t3/userdata/statev2.sqlite).",
    )
    parser.add_argument(
        "--znaki",
        type=int,
        default=CHARS,
        help=f"Najwięcej znaków treści w linii (domyślnie {CHARS}).",
    )
    args = parser.parse_args(argv)
    if not args.baza.is_file():
        print(f"{PREFIX} FAIL | brak bazy T3: {args.baza}")
        return 1
    now = datetime.now(UTC)
    week = (
        last_full_week(now) if args.tydzien is None else week_of(midnight(args.tydzien))
    )
    until = midnight(week + timedelta(days=7))
    if until > now:
        print(
            f"{PREFIX} FAIL | tydzień {week.isoformat()} jeszcze trwa: kończy się {until.astimezone(WARSAW):%Y-%m-%d %H:%M}"
        )
        return 1
    try:
        found, elsewhere = messages(args.baza, midnight(week), until)
    except (sqlite3.DatabaseError, ValueError) as error:
        print(f"{PREFIX} FAIL | baza T3 {args.baza}: {error}")
        return 1
    kept = sorted(
        (message for name, message in found if name == OPERATOR),
        key=lambda message: (message.moment, message.thread),
    )
    if not kept:
        projects = (
            ", ".join(f"{name} {elsewhere[name]}" for name in sorted(elsewhere))
            or "brak"
        )
        print(
            f"{PREFIX} FAIL | tydzień {week.isoformat()}: 0 wiadomości operatora w wątkach {REPO} z {len(found)} wiadomości user | inne projekty T3 tej bazy: {projects}"
        )
        return 1
    for message in kept:
        print(_line(message, args.znaki))
    others = Counter(name for name, _ in found if name != OPERATOR)
    skipped = (
        ", ".join(f"{name} {others[name]}" for name in sorted(others)) or "innych 0"
    )
    threads = len({message.thread for message in kept})
    print(
        f"{PREFIX} OK | tydzień {week.isoformat()}: {len(kept)} wiadomości operatora w {threads} wątkach z {len(found)} wiadomości user | {skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
