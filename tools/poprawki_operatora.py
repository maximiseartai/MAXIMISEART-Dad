from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
import json
from pathlib import Path, PurePath
import re
import sqlite3
import stat
import subprocess
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import repo
from tydzien_polski import WARSAW, last_full_week, midnight, week_of

OPIS = """Wypisuje wiadomości operatora z wątków T3 Code tego repo w tygodniu albo oknie czasu; użyj w polowaniu na powtarzane błędy.

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
zostaje w każdym, ile razy by ją agent przekazał dalej.

Wątek należy do repo, gdy jego projekt T3 jest pewnie repo według ``doubt``: katalog projektu (``workspace_root``)
nazywa się ``REPO`` albo jest dziś checkoutem gita z origin dokładnie ``ORIGIN`` (host, właściciel i repo), albo
``--projekt`` podaje jego identyfikator. O każdym innym projekcie narzędzie nie rozstrzyga po cichu: jego wiadomości
operatora z okna idą do części ``inne projekty:`` linii wyniku z powodem (``Doubt``), bo katalog wątku z minionego
tygodnia narzędzie widzi tylko w dniu biegu, a repo przeniesione w tygodniu zostawia projekt, którego katalogu już nie
ma. Kto czyta linię, rozstrzyga, czy taki projekt to repo, i wtedy uruchamia narzędzie z ``--projekt <id>``.

Okno to chwile od ``--od`` włącznie do ``--do`` bez niego, w czasie polskim ``RRRR-MM-DD`` (początek dnia) albo
``RRRR-MM-DD GG:MM``, a ``--do`` domyślnie to chwila biegu, więc okno może leżeć w tygodniu, który jeszcze trwa (analiza
wsteczna po resecie limitów). ``--tydzien`` to skrót okna od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu
polskiego (``tydzien_polski``), a bez ``--od`` i ``--tydzien`` okno to ostatni pełny tydzień.

Linia na wiadomość, w kolejności czasu: ``<czas polski> | <wątek> | <treść>``, gdzie wątek to identyfikator wątku T3,
a treść ma najwyżej ``--znaki`` znaków, z ``" / "`` w miejscu końca linii. Ostatnia linia: ``POPRAWKI OPERATORA OK |
<okno>: n wiadomości operatora w w wątkach z m wiadomości user | <nadawca> k, … | inne projekty: <projekt>
k (<powód>), …`` z liczbą pozostałych wiadomości każdego nadawcy (``<createdBy>/<creationSource>`` albo ``COMPACT``)
i liczbą wiadomości operatora każdego projektu, który nie jest pewnie repo (``inne projekty: brak``, gdy takich nie ma);
``<okno>`` to ``tydzień RRRR-MM-DD`` (poniedziałek) albo ``okno RRRR-MM-DD GG:MM – RRRR-MM-DD GG:MM``;
projekt to ostatni człon jego katalogu i identyfikator projektu T3 w nawiasie kwadratowym, bez reszty ścieżki. Narzędzie tylko czyta bazę: treść
wiadomości idzie na standardowe wyjście, a zapis jej w repozytorium, PR albo issue łamie prywatność wątków Maksa, więc
test narzędzia ma tylko tekst i identyfikatory wymyślone.

Linia ``OK`` z zerem nie istnieje: okno bez wiadomości operatora w wątkach repo kończy się linią ``POPRAWKI OPERATORA
FAIL | <okno>: 0 wiadomości operatora w wątkach REPO z m wiadomości user | inne projekty: <projekt> k
(<powód>), …`` i kodem 1, bo przy kilkuset wiadomościach operatora na tydzień zero częściej znaczy nieczytane wejście (repo
przeniesione do katalogu, który nie jest już checkoutem repo, a stary dostaje tylko wiadomości agentów) niż
tydzień bez poprawek, a liczba wiadomości operatora w innych projektach mówi, gdzie patrzeć. Przed liczeniem narzędzie
sprawdza wejście (``alive``), a każdy z tych stanów też kończy się linią ``FAIL`` z powodem i kodem 1: brak bazy albo
tabel T3, ``created_at`` wiadomości w innym typie albo zapisie niż tekst ``toISOString``, żaden projekt T3 pewnie
repo (z listą projektów i powodów), ``--projekt`` spoza bazy i najnowsza wiadomość bazy sprzed ``min(--do, chwila biegu - QUIET_H godzin)`` (baza, której T3
już nie pisze, jak ``state.sqlite`` po przejściu na ``statev2.sqlite``): okno, które skończyło się dawniej niż
``QUIET_H`` godzin temu, baza ma do końca, a w oknie do ostatnich godzin wiadomość może jeszcze nie przyjść, więc wtedy
wystarczy wiadomość z ostatnich ``QUIET_H`` godzin. Tak samo kończy się wiadomość wątku
repo z nadawcą albo źródłem spoza kontraktu.

Granica: wiadomość wpisana poza oknem T3 (terminal Claude Code, ``claude -p``) nie ma wiersza w bazie, a wątki innej
maszyny (og-box) są w bazie tamtej maszyny, więc narzędzie biegnie tam osobno. Odpowiedź operatora na pytanie dostawcy
(identyfikator ``async-answer:``) ma nadawcę ``user/server`` taki sam jak odpowiedź agenta przez ``t3_pending_request``,
więc narzędzie liczy ją jako ``user/server`` (próbka ``ZNANE_LUKI`` w teście).
"""

PREFIX = "POPRAWKI OPERATORA"
REPO = "MAXIMISEART-Dad"
ORIGIN = "github.com/maximiseartai/maximiseart-dad"
GIT_S = 10.0
BAZA = Path.home() / ".t3" / "userdata" / "statev2.sqlite"
CHARS = 400
QUIET_H = 6
ACTORS = frozenset({"user", "agent", "system"})
SOURCES = frozenset({"web", "mobile", "mcp", "provider", "server"})
WINDOW = frozenset({"web", "mobile"})
OPERATOR = "operatora"
COMPACT = "/compact po powrocie"
FEEDBACK = "approval-feedback:"
QUERY = """
SELECT m.message_id, m.thread_id, m.created_at, m.payload_json, t.project_id
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
PROJECTS = "SELECT project_id, workspace_root FROM projection_projects"
# Zapis scp origin gita: ``[użytkownik@]host:ścieżka``.
SCP = re.compile(r"(?:[^@/:]+@)?(?P<host>[^@/:]+):(?P<path>[^/].*)")

EXAMPLES = """\
    .venv/bin/python tools/poprawki_operatora.py                          # ostatni pełny tydzień, baza T3 tej maszyny
    .venv/bin/python tools/poprawki_operatora.py --tydzien 2026-11-09 --baza <kopia bazy T3>
    .venv/bin/python tools/poprawki_operatora.py --tydzien 2026-11-09 --projekt <id z części „inne projekty”>
    .venv/bin/python tools/poprawki_operatora.py --od "2026-11-18 23:00"                  # od tej chwili do teraz
    .venv/bin/python tools/poprawki_operatora.py --od 2026-11-18 --do "2026-11-19 17:00"
"""


class ShapeError(ValueError):
    """Wiadomość, której nadawcy narzędzie nie zna: baza T3 ma inny kształt niż kontrakt ``orchestrationV2``."""


class DeadInput(ValueError):
    """Wejście, z którego narzędzie nie przeczytałoby wiadomości okna, więc zero nic by nie znaczyło."""


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


class Doubt(StrEnum):
    """Czemu narzędzie nie liczy projektu T3 do repo; linia wyniku pokazuje powód przy liczbie jego wiadomości."""

    FOREIGN = "inny origin"
    NO_ORIGIN = "bez origin"
    MISSING = "brak katalogu"
    NO_GIT = "bez git"
    UNREADABLE = "bez odczytu"
    GIT_TIMEOUT = "limit czasu gita"


def _origin(url: str) -> str | None:
    """``host/właściciel/repo`` małymi literami z ``remote.origin.url`` w zapisie URL albo scp, bez użytkownika,
    tokenu, portu, ``.git`` i ``/`` na końcu; ``None`` dla innego zapisu (ścieżka lokalna)."""

    text = url.strip()
    if "://" in text:
        parts = urlsplit(text)
        host, path = parts.hostname, parts.path
    elif match := SCP.fullmatch(text):
        host, path = match["host"], match["path"]
    else:
        return None
    return f"{host}/{path.strip('/').removesuffix('.git').strip('/')}".lower()


def doubt(root: str) -> Doubt | None:
    """``None``, gdy katalog projektu T3 jest pewnie repo: nazywa się ``REPO`` albo jest checkoutem gita, którego
    origin to dokładnie ``ORIGIN`` (``_origin``); inaczej powód. Origin czyta lokalny git bez sieci i bez środowiska
    wołającego (``repo.git(isolated=True)``), więc ``GIT_DIR`` odziedziczony z hooka gita nie podmienia katalogu
    projektu."""

    if PurePath(root).name == REPO:
        return None
    try:
        if not stat.S_ISDIR(Path(root).stat().st_mode):
            return Doubt.MISSING
        url = repo.git(
            Path(root),
            "config",
            "--local",
            "--get",
            "remote.origin.url",
            timeout=GIT_S,
            isolated=True,
        )
    except (FileNotFoundError, NotADirectoryError):
        return Doubt.MISSING
    except OSError:
        return Doubt.UNREADABLE
    except subprocess.TimeoutExpired:
        return Doubt.GIT_TIMEOUT
    except subprocess.CalledProcessError as error:
        # git config --get: 1 to brak klucza w checkoucie, 128 to katalog poza checkoutem gita (--local).
        return Doubt.NO_ORIGIN if error.returncode == 1 else Doubt.NO_GIT
    return None if _origin(url) == ORIGIN else Doubt.FOREIGN


@dataclass(frozen=True)
class Project:
    """Projekt T3 z bazy: ``doubt`` ``None`` liczy go do repo."""

    label: str
    doubt: Doubt | None


def _projects(db: sqlite3.Connection, forced: frozenset[str]) -> dict[str, Project]:
    """Każdy projekt T3 bazy po identyfikatorze; projekt z ``forced`` (``--projekt``) jest repo bez pytania dysku."""

    found = {
        project_id: Project(
            f"{PurePath(root).name} [{project_id}]",
            None if project_id in forced else doubt(root),
        )
        for project_id, root in db.execute(PROJECTS)
    }
    if unknown := forced - found.keys():
        raise ValueError(f"--projekt spoza bazy: {', '.join(sorted(unknown))}")
    return found


def _others(counts: Counter[Project]) -> str:
    """Część ``inne projekty:`` linii wyniku: liczba wiadomości operatora i powód każdego projektu spoza repo."""

    listed = ", ".join(
        f"{project.label} {counts[project]} ({project.doubt})"
        for project in sorted(counts, key=lambda project: project.label)
    )
    return f"inne projekty: {listed or 'brak'}"


def _iso(moment: datetime) -> str:
    """Chwila w zapisie ``created_at`` bazy T3 (``toISOString``), więc porównanie napisów to porównanie chwil."""

    return (
        moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def alive(
    db: sqlite3.Connection, fresh: datetime, projects: dict[str, Project]
) -> None:
    """Rzuca ``DeadInput``, gdy baza nie da wiadomości okna: ``created_at`` w innym zapisie niż ``toISOString``
    (``_iso``), brak projektu pewnie repo wśród ``projects`` albo baza, której T3 nie pisał do chwili ``fresh``."""

    shapes = {shape: (count, newest) for shape, count, newest in db.execute(SHAPES)}
    if foreign := {
        shape: count for shape, (count, _) in shapes.items() if shape != ISO
    }:
        raise DeadInput(
            f"created_at wiadomości poza zapisem {ISO}: {', '.join(f'{shape} {count}' for shape, count in sorted(foreign.items()))}"
        )
    if all(project.doubt for project in projects.values()):
        listed = ", ".join(
            sorted(
                f"{project.label} ({project.doubt})" for project in projects.values()
            )
        )
        raise DeadInput(
            f"żaden projekt T3 nie jest repo: katalog {REPO} albo checkout z origin {ORIGIN}; projekty: {listed or 'brak'}"
        )
    newest = shapes.get(ISO, (0, None))[1]
    if newest is None or newest < _iso(fresh):
        raise DeadInput(
            f"najnowsza wiadomość bazy ({newest}) jest sprzed {_iso(fresh)}, końca okna albo {QUIET_H} h przed biegiem: T3 pisze inną bazę albo od tej chwili nic nie zapisał"
        )


def _operator_elsewhere(message_id: str, payload: dict[str, object]) -> bool:
    """Czy wiadomość projektu spoza repo napisał operator; nadawca spoza kontraktu tam tylko jej nie liczy."""

    try:
        return sender(message_id, payload) == OPERATOR
    except ShapeError:
        return False


def messages(
    base: Path,
    since: datetime,
    until: datetime,
    now: datetime,
    forced: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, Message]], Counter[Project]]:
    """Nadawca i wiadomość każdej wiadomości ``user`` wątku repo z chwilą w ``[since, until)`` z bazy, którą T3 pisał do
    ``min(until, now - QUIET_H godzin)`` (``alive``), oraz liczba wiadomości operatora w tym czasie w każdym projekcie
    T3, który nie jest pewnie repo (``_projects``)."""

    with closing(sqlite3.connect(f"{base.resolve().as_uri()}?mode=ro", uri=True)) as db:
        projects = _projects(db, forced)
        alive(db, min(until, now - timedelta(hours=QUIET_H)), projects)
        rows = db.execute(QUERY, (_iso(since), _iso(until))).fetchall()
    found = []
    elsewhere: Counter[Project] = Counter()
    for message_id, thread, created, payload_json, project_id in rows:
        payload = json.loads(payload_json)
        project = projects[project_id]
        if project.doubt is None:
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
            elsewhere[project] += 1
    return found, elsewhere


def _line(message: Message, chars: int) -> str:
    text = " / ".join(
        line.strip() for line in message.text.splitlines() if line.strip()
    )
    shown = text if len(text) <= chars else f"{text[:chars]}… ({len(text)} zn.)"
    return f"{message.moment.astimezone(WARSAW):%Y-%m-%d %H:%M} | {message.thread} | {shown}"


def _moment(text: str) -> datetime:
    """Chwila czasu polskiego z ``RRRR-MM-DD`` (początek dnia) albo ``RRRR-MM-DD GG:MM``."""

    shape = "%Y-%m-%d %H:%M" if " " in text else "%Y-%m-%d"
    try:
        return datetime.strptime(text, shape).replace(tzinfo=WARSAW)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"{text!r} to nie RRRR-MM-DD ani RRRR-MM-DD GG:MM"
        ) from error


@dataclass(frozen=True)
class Window:
    """Okno ``[since, until)`` i jego nazwa w linii wyniku."""

    since: datetime
    until: datetime
    label: str


def _window(args: argparse.Namespace, now: datetime) -> Window:
    if args.od is not None:
        until = now if args.do is None else args.do
        return Window(
            args.od,
            until,
            f"okno {args.od:%Y-%m-%d %H:%M} – {until.astimezone(WARSAW):%Y-%m-%d %H:%M}",
        )
    week = (
        last_full_week(now) if args.tydzien is None else week_of(midnight(args.tydzien))
    )
    return Window(
        midnight(week),
        midnight(week + timedelta(days=7)),
        f"tydzień {week.isoformat()}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=OPIS,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tydzien",
        type=date.fromisoformat,
        help="Dzień tygodnia, RRRR-MM-DD: skrót okna od jego poniedziałku do następnego (domyślnie ostatni pełny tydzień).",
    )
    parser.add_argument(
        "--od",
        type=_moment,
        help="Początek okna włącznie, czas polski RRRR-MM-DD albo RRRR-MM-DD GG:MM.",
    )
    parser.add_argument(
        "--do",
        type=_moment,
        help="Koniec okna bez niego, jak --od (domyślnie chwila biegu); tylko z --od.",
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
    parser.add_argument(
        "--projekt",
        action="append",
        default=[],
        metavar="ID",
        help="Identyfikator projektu T3 z części „inne projekty”, który jest repo (np. stary katalog po przeniesieniu); można powtórzyć.",
    )
    args = parser.parse_args(argv)
    if args.tydzien is not None and args.od is not None:
        parser.error("--tydzien to skrót okna: podaj go albo --od, nie oba")
    if args.do is not None and args.od is None:
        parser.error("--do kończy okno od --od: podaj też --od")
    now = datetime.now(UTC)
    window = _window(args, now)
    if window.since >= window.until:
        parser.error(
            f"puste {window.label}: --od musi być przed --do i przed chwilą biegu"
        )
    if not args.baza.is_file():
        print(f"{PREFIX} FAIL | brak bazy T3: {args.baza}")
        return 1
    try:
        found, elsewhere = messages(
            args.baza, window.since, window.until, now, frozenset(args.projekt)
        )
    except (sqlite3.DatabaseError, ValueError) as error:
        print(f"{PREFIX} FAIL | baza T3 {args.baza}: {error}")
        return 1
    kept = sorted(
        (message for name, message in found if name == OPERATOR),
        key=lambda message: (message.moment, message.thread),
    )
    if not kept:
        print(
            f"{PREFIX} FAIL | {window.label}: 0 wiadomości operatora w wątkach {REPO} z {len(found)} wiadomości user | {_others(elsewhere)}"
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
        f"{PREFIX} OK | {window.label}: {len(kept)} wiadomości operatora w {threads} wątkach z {len(found)} wiadomości user | {skipped} | {_others(elsewhere)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
