"""Wypisuje wiadomości operatora z transkryptów Claude Code tego repo w jednym tygodniu; użyj w polowaniu na powtarzane błędy.

Polowanie (skill ``.agents/skills/polowanie/SKILL.md``) szuka poprawek Maksa w wątkach agentów. Transkrypt Claude Code
zapisuje tak samo, jako rekord ``user``, wiadomość, którą Maks napisał, i tekst, który do wątku włożył T3 Code albo
inny agent, więc narzędzie zostawia wiadomość tylko wtedy, gdy nikt inny jej nie dał:

- rekord głównego wątku (bez ``isSidechain``) z sesji, którą prowadzi człowiek, czyli z ``entrypoint`` z ``HUMAN``
  (T3 Code i terminal Claude Code); sesja ``claude -p`` (``sdk-cli``) i każde inne wejście to „sesje bez operatora”;
- tekst wiadomości, a nie wynik narzędzia; komenda (``/skill argumenty``) liczy się raz, z całym tekstem, który Maks
  wpisał razem z nią (rekord ``isMeta`` z ``commandTextBlocks``), a inny rekord ``isMeta`` to treść skilla albo
  harnessu;
- bez streszczenia kontekstu (``isCompactSummary``), tekstu harnessu (``HARNESS``) i szablonów T3 Code (``T3``):
  powiadomienia o PR, wyniku delegata i briefu delegata;
- bez tekstu, który agent wysłał przed chwilą wiadomości narzędziem T3 Code (``t3_thread_send``, ``delegate_task``,
  ``schedule_task`` i każde inne ``mcp__t3-code__*``), ``SendMessage`` albo poleceniem Bash ``t3 thread send <wątek>
  <tekst>`` w którymkolwiek transkrypcie katalogów, także innego projektu i sprzed tygodnia: wiadomości koordynatora
  i pulsu zadania T3. Wiadomość jest tekstem agenta, gdy jej pierwsze ``KEY`` znaków bez różnicy białych znaków, cała
  albo za pierwszą pustą linią (opakowanie briefu T3), to początek tekstu wysłanego wcześniej; gdy wysłany tekst stoi
  cały na początku wiadomości, a za nim operator dopisał swój, zostaje dopisana część. Tekst operatora, który agent
  przekazał dalej dopiero po nim, zostaje wiadomością operatora.

Katalogi (``--katalog``, domyślnie ``~/.claude/projects``) to katalogi projektów Claude Code; wiadomości narzędzie
bierze z plików ``*.jsonl`` wprost w każdym podkatalogu, którego nazwa ma ``REPO``, więc kopia z innej maszyny
(``rsync`` tego samego układu) czyta się tak samo. Tydzień trwa od poniedziałku 0:00 do następnego poniedziałku 0:00 czasu polskiego
(``tydzien_polski``); bez ``--tydzien`` to ostatni pełny tydzień.

Linia na wiadomość, w kolejności czasu: ``<czas polski> | <wątek> | <treść>``, gdzie wątek to nazwa katalogu projektu
za ``REPO`` i początek identyfikatora sesji, a treść ma najwyżej ``--znaki`` znaków, z ``" / "`` w miejscu końca linii.
Ostatnia linia: ``POPRAWKI OPERATORA OK | tydzień RRRR-MM-DD: n wiadomości operatora w w wątkach z m rekordów
w p transkryptach | <rodzaj> k, …`` z liczbą rekordów każdego pominiętego rodzaju; brak katalogu kończy się linią
``POPRAWKI OPERATORA FAIL`` i kodem 1. Narzędzie tylko czyta: treść wiadomości idzie na standardowe wyjście,
a zapis jej w repozytorium, PR albo issue łamie prywatność wątków Maksa, więc test narzędzia ma tylko tekst,
sesje i katalogi wymyślone.

Granica: tekst, który agent włożył do wątku spoza transkryptów katalogów (skrypt launchd przez ``t3 thread send``,
agent na maszynie bez kopii jej transkryptów, wysłany tekst krótszy niż ``MIN_SENT``) albo poleceniem Bash, którego
tekstu ``shlex`` nie odczyta dosłownie (``t3`` pod zmienną, tekst ze zmienną albo z ``$(…)``, tekst z wejścia ``-``),
wygląda jak wiadomość operatora.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from itertools import takewhile
import json
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from tydzien_polski import WARSAW, last_full_week, midnight, week_of

PREFIX = "POPRAWKI OPERATORA"
REPO = "MAXIMISEART-Dad"
HUMAN = frozenset({"t3-code", "sdk-ts", "cli"})
KEY = 60
MIN_SENT = 20
CHARS = 400
SENDER_TOOLS = ("mcp__t3-code__", "SendMessage")
BASH_SEND = ("thread", "send")
SENDER_MARKERS = (*(name.encode() for name in SENDER_TOOLS), " ".join(BASH_SEND).encode())
SHELL_OPERATORS = frozenset("();<>|&")
USER_MARKERS = (b'"user"',)
COMMAND = ("<command-message>", "<command-name>")

EXAMPLES = """\
    .venv/bin/python tools/poprawki_operatora.py                                   # ostatni pełny tydzień, transkrypty tego Maca
    .venv/bin/python tools/poprawki_operatora.py --tydzien 2026-11-09 --katalog ~/.claude/projects --katalog <kopia og-box>
"""


class Kind(Enum):
    """Rodzaj rekordu ``user`` z tekstem; wartość to nazwa w linii wyniku."""

    OPERATOR = "operatora"
    NO_OPERATOR = "sesje bez operatora"
    SUMMARY = "streszczenia kontekstu"
    HARNESS = "harness"
    PR_UPDATE = "powiadomienia PR"
    DELEGATE_RESULT = "wyniki delegatów"
    AGENT = "wiadomości agentów"
    COMMAND_COPY = "kopie komend"


T3 = (
    ("Update on pull request #", Kind.PR_UPDATE),
    ("Delegated task node:", Kind.DELEGATE_RESULT),
    ("Act as the ", Kind.AGENT),
)
HARNESS = (
    "<local-command-",
    "<task-notification>",
    "[Request interrupted by user",
    "<bash-input>",
    "<bash-stdout>",
    "Continue where you left off.",
    "Note: the T3 server restarted",
)


@dataclass(frozen=True)
class Message:
    moment: datetime
    thread: str
    text: str


Sent = dict[str, list[tuple[datetime, str]]]
"""Wysłane teksty po ich początku: chwila wysłania i cały tekst bez różnicy białych znaków."""


def _normal(text: str) -> str:
    return " ".join(text.split())


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _records(path: Path, markers: tuple[bytes, ...]) -> Iterator[dict[str, object]]:
    with path.open("rb") as lines:
        for line in lines:
            if any(marker in line for marker in markers):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record


def _blocks(record: dict[str, object]) -> list[object]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [{"type": "text", "text": content}] if isinstance(content, str) else content if isinstance(content, list) else []


def _texts(blocks: Iterable[object]) -> list[str]:
    return [str(block.get("text", "")) for block in blocks if isinstance(block, dict) and block.get("type") == "text"]


def _bash_sent(command: str) -> list[str]:
    """Teksty poleceń ``t3 thread send [flagi] <wątek> <tekst>`` w poleceniu Bash, odczytane przez ``shlex``."""

    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:
        return []
    texts = []
    for at in range(1, len(words) - 2):
        if Path(words[at - 1]).name == "t3" and tuple(words[at : at + 2]) == BASH_SEND:
            arguments = takewhile(lambda word: not set(word) <= SHELL_OPERATORS, words[at + 2 :])
            texts += [word for word in arguments if not word.startswith("-")][1:2]
    return texts


def _sent_by(block: object) -> list[str]:
    if not isinstance(block, dict) or block.get("type") != "tool_use":
        return []
    name, arguments = str(block.get("name", "")), block.get("input")
    if name.startswith(SENDER_TOOLS):
        return list(_strings(arguments))
    if name == "Bash" and isinstance(arguments, dict):
        return _bash_sent(str(arguments.get("command", "")))
    return []


def sent_texts(paths: Iterable[Path]) -> Sent:
    """Teksty co najmniej ``MIN_SENT`` znaków, które agent wysłał narzędziem z ``SENDER_TOOLS`` albo poleceniem Bash
    ``t3 thread send`` w transkryptach ``paths``."""

    found: Sent = {}
    for path in paths:
        for record in _records(path, SENDER_MARKERS):
            moment = datetime.fromisoformat(str(record.get("timestamp", "1970-01-01T00:00:00Z")))
            for block in _blocks(record):
                for text in map(_normal, _sent_by(block)):
                    if len(text) >= MIN_SENT:
                        found.setdefault(text[:KEY], []).append((moment, text))
    return found


def _after(text: str, prefix: str) -> str:
    """Reszta ``text`` za ``prefix`` (bez różnicy białych znaków), gdy ``prefix`` kończy się na granicy słowa."""

    wanted = len(prefix.replace(" ", ""))
    at = 0
    while wanted:
        wanted -= not text[at].isspace()
        at += 1
    return text[at:].strip() if at == len(text) or text[at].isspace() else ""


def _own(text: str, moment: datetime, sent: Sent) -> str:
    """Część wiadomości, którą napisał operator: bez tekstów wysłanych przed ``moment`` na jej początku, a pusta, gdy
    wysłany tekst nie stoi na początku cały albo stoi za pierwszą pustą linią (opakowanie briefu T3)."""

    def earlier(part: str) -> list[str]:
        return [whole for when, whole in sent.get(_normal(part)[:KEY], ()) if when <= moment]

    if any(map(earlier, text.split("\n\n", 1)[1:])):
        return ""
    texts = earlier(text)
    if not texts:
        return text
    normal = _normal(text)
    prefix = max((whole for whole in texts if normal.startswith(whole)), key=len, default="")
    return _own(_after(text, prefix), moment, sent) if prefix else ""


def _command(text: str) -> str:
    def tag(name: str) -> str:
        return text.split(f"<{name}>", 1)[1].split(f"</{name}>", 1)[0] if f"<{name}>" in text else ""

    return f"{tag('command-name')} {tag('command-args')}".strip()


def classify(path: Path, label: str, sent: Sent, since: datetime, until: datetime) -> Iterator[tuple[Kind, Message]]:
    """Rodzaj i wiadomość każdego rekordu ``user`` z tekstem transkryptu ``path`` z chwilą w ``[since, until)``."""

    records = [record for record in _records(path, USER_MARKERS) if record.get("type") == "user" and not record.get("isSidechain")]
    companions = {record.get("parentUuid") for record in records if record.get("isMeta") and record.get("commandTextBlocks")}
    for record in records:
        moment = datetime.fromisoformat(str(record.get("timestamp", "1970-01-01T00:00:00Z")))
        blocks = _blocks(record)
        if not since <= moment < until or any(isinstance(block, dict) and block.get("type") == "tool_result" for block in blocks):
            continue
        text = "\n".join(_texts(blocks)).strip()
        if record.get("isMeta") and record.get("commandTextBlocks"):
            own = record["commandTextBlocks"]
            text = "\n".join(_texts(blocks)[: own.get("own", 1) if isinstance(own, dict) else 1]).strip()
        if not text:
            continue
        message = Message(moment, label, text)
        if record.get("entrypoint") not in HUMAN:
            yield Kind.NO_OPERATOR, message
        elif record.get("isCompactSummary"):
            yield Kind.SUMMARY, message
        elif record.get("isMeta") and not record.get("commandTextBlocks"):
            yield Kind.HARNESS, message
        elif text.startswith(COMMAND) and record.get("uuid") in companions:
            yield Kind.COMMAND_COPY, message
        elif text.startswith(COMMAND):
            yield Kind.OPERATOR, Message(moment, label, _command(text))
        elif text.startswith(HARNESS):
            yield Kind.HARNESS, message
        elif kind := next((kind for start, kind in T3 if text.startswith(start)), None):
            yield kind, message
        elif own := _own(text, moment, sent):
            yield Kind.OPERATOR, Message(moment, label, own)
        else:
            yield Kind.AGENT, message


def transcripts(folders: Iterable[Path], projects: str = "*") -> list[Path]:
    """Pliki ``*.jsonl`` wprost w podkatalogach ``projects`` każdego katalogu ``folders``."""

    return sorted(path for folder in folders for project in folder.glob(projects) for path in project.glob("*.jsonl"))


def _label(path: Path) -> str:
    tail = path.parent.name.rsplit(REPO, 1)[-1].strip("-") or REPO
    return f"{tail}/{path.stem[:8]}"


def _line(message: Message, chars: int) -> str:
    text = " / ".join(line.strip() for line in message.text.splitlines() if line.strip())
    shown = text if len(text) <= chars else f"{text[:chars]}… ({len(text)} zn.)"
    return f"{message.moment.astimezone(WARSAW):%Y-%m-%d %H:%M} | {message.thread} | {shown}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tydzien", type=date.fromisoformat, help="Dzień tygodnia, RRRR-MM-DD (domyślnie ostatni pełny tydzień).")
    parser.add_argument("--katalog", type=Path, action="append", help="Katalog projektów Claude Code (domyślnie ~/.claude/projects); można powtórzyć.")
    parser.add_argument("--znaki", type=int, default=CHARS, help=f"Najwięcej znaków treści w linii (domyślnie {CHARS}).")
    args = parser.parse_args(argv)
    folders = args.katalog or [Path.home() / ".claude" / "projects"]
    missing = [str(folder) for folder in folders if not folder.is_dir()]
    if missing:
        print(f"{PREFIX} FAIL | brak katalogu: {', '.join(missing)}")
        return 1
    week = last_full_week(datetime.now(UTC)) if args.tydzien is None else week_of(midnight(args.tydzien))
    since, until = midnight(week), midnight(week + timedelta(days=7))
    sent = sent_texts(transcripts(folders))
    active = [path for path in transcripts(folders, f"*{REPO}*") if datetime.fromtimestamp(path.stat().st_mtime, UTC) >= since]
    kinds: Counter[Kind] = Counter()
    kept = []
    for path in active:
        for kind, message in classify(path, _label(path), sent, since, until):
            kinds[kind] += 1
            if kind is Kind.OPERATOR:
                kept.append(message)
    for message in sorted(kept, key=lambda message: message.moment):
        print(_line(message, args.znaki))
    skipped = ", ".join(f"{kind.value} {kinds[kind]}" for kind in Kind if kind is not Kind.OPERATOR)
    threads = len({message.thread for message in kept})
    print(f"{PREFIX} OK | tydzień {week.isoformat()}: {len(kept)} wiadomości operatora w {threads} wątkach z {kinds.total()} rekordów w {len(active)} transkryptach | {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
