#!/usr/bin/env python3
"""Hooki ``PostToolUse`` i ``SessionStart`` Claude Code w T3: wątek, który zlecił pracę delegatowi, dostaje strażnika sam.

Koordynator (wątek T3, który zleca pracę innym wątkom i czeka na nich, często na noc) staje po cichu, gdy dziecko
utknie albo T3 go nie obudzi po końcu dziecka, a nikt tego nie widzi do rana. Strażnika spoza procesu Claude Code
stawiał dotąd sam koordynator, ze skryptu kopiowanego z biegu do biegu, więc stawiał go dopiero na prośbę Maksa,
choć instrukcja kazała bez niej. Tu strażnika stawia hook, bez osądu agenta, czy jest koordynatorem i czy praca potrwa.

Hook ``PostToolUse`` narzędzia ``DELEGATE`` (``.claude/settings.json``) dopisuje identyfikator wątku dziecka z
odpowiedzi (pole ``CHILD_KEY``) z chwilą zlecenia do pliku ``.dzieci`` wątku i za każdym razem uruchamia proces
strażnika (``pilnuj <wątek>``, ``potomne.detach``, więc koniec Claude Code go nie kończy); ``SessionStart`` (wznowienie
sesji, także po restarcie T3 albo Maca) uruchamia go, gdy plik jest. Tylko ``delegate_task`` jest delegacją, po której
końcu T3 budzi rodzica; ``t3_thread_launch`` i ``create_threads`` zakładają wątki najwyższego poziomu, na które nikt nie
czeka, więc hook pomija każde inne narzędzie. Wątek to ``T3CODE_THREAD_ID``, a program T3 to ``T3CODE_CLI_PATH``, oba ze
środowiska, które T3 daje sesji: bez nich (Claude Code poza T3, komputer taty) i na Windows hook nic nie robi. Pliki
wątku leżą w ``~/.cache/maximiseart/straznik/`` (``STATE``), nazwane skrótem jego identyfikatora.

Cykl życia nie ma stanu, który ktoś usuwa albo przepisuje: plik ``.dzieci`` jest tylko dopisywany (jedna linia na
zlecenie, atomowo przez ``O_APPEND``), a wpis traci znaczenie ``MAX_LIFE_S`` po swoim zleceniu. O tym, który proces
pilnuje, rozstrzygają dwie blokady ``flock``, które system zwalnia ze śmiercią procesu: blokada życia (``.zycie``)
należy do jedynego pilnującego, a blokada kolejki (``.kolejka``) do najwyżej jednego czekającego. Proces bierze kolejkę
bez czekania (zajęta: kończy się, bo czekający jeszcze nie czytał pliku i przeczyta dopisane dziecko), potem czeka na
życie, oddaje kolejkę i dopiero wtedy czyta plik. Każde dopisanie poprzedza więc uruchomienie procesu, który plik
przeczyta po dopisaniu, w każdej kolejności kroków hooka i kończącego się strażnika (``serve``).

Pilnujący co ``STEP_S`` sekund czyta plik od zera, pyta ``t3 thread show`` o wątek i każde dziecko z wpisów młodszych
niż ``MAX_LIFE_S``, a kończy się, gdy od najmłodszego wpisu minęło ``MAX_LIFE_S`` (``alive``), cokolwiek i jakkolwiek
wolno odpowiada T3. ``Seen`` niesie ``updatedAt`` z T3, a każdy wiek liczy się z jednego ``now`` pytania:

- ``decide`` budzi wątek (``t3 thread send``), gdy wątek skończył turę (status z ``FINISHED``, także ``failed`` i
  ``interrupted``), a dziecko trwa bez ruchu dłużej niż ``CHILD_STALE_S`` albo skończyło się ponad ``WAKE_S`` temu, a
  wątek od tego czasu nie ruszył, czyli T3 go nie obudził (``stalled``; koniec dziecka zapisuje ``observe``);
- tego samego powodu (dziecko i rodzaj powodu) nie powtarza, a dwa budzenia dzieli ``PAUSE_S``;
- wątek ``running`` bez ruchu dłużej niż ``STUCK_S`` tylko zapisuje w dzienniku, bo wiadomość do zajętego wątku
  czeka na jego następną turę;
- kończy się wcześniej, gdy nie ma już czego pilnować (``pending``: żadne dziecko nie trwa, a po każdym końcu dziecka
  wątek ruszył albo dostał budzenie; dziecko, którego ``t3 thread show`` nie pokazuje dłużej niż ``LOST_S``, przestaje
  się liczyć).

Granica: dzieci to tylko wątki z ``childThreadId`` w odpowiedzi ``delegate_task``; dziecko w innym środowisku (og-box)
ma ``childThreadId`` null, a jego identyfikator należy do tamtego środowiska, więc strażnik go nie pilnuje; podagent
narzędzia Agent biegnie w procesie koordynatora i nie ma wątku, więc strażnik go nie widzi. Koordynator stojący przy
gotowym PR bez żywego dziecka nie dostaje budzenia. Plik ``.dzieci`` rośnie o linię na zlecenie i nikt go nie
skraca; przez całe życie pilnującego obok śpi najwyżej jeden czekający proces. T3, które przy końcu dziecka dopisze coś do wątku rodzica bez jego tury, przesunie ruch rodzica i
ukryje brak budzenia. Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``ruff.toml``), a plik importuje tylko bibliotekę standardową i ``potomne``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import IO

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import potomne

DELEGATE = "mcp__t3-code__delegate_task"
CHILD_KEY = "childThreadId"
THREAD_ENV = "T3CODE_THREAD_ID"
CLI_ENV = "T3CODE_CLI_PATH"
STATE = Path(".cache") / "maximiseart" / "straznik"
# Odstęp pytań strażnika; test podaje krótszy, żeby strażnik skończył się w kilka sekund.
STEP_ENV = "MAXIMISEART_STRAZNIK_ODSTEP_S"
STEP_S = 300.0
# Limit życia wpisu; test procesu podaje krótszy, żeby strażnik, którego test nie zakończył, skończył się sam.
LIFE_ENV = "MAXIMISEART_STRAZNIK_ZYCIE_S"
CHILD_STALE_S = 45 * 60
WAKE_S = 15 * 60
PAUSE_S = 30 * 60
STUCK_S = 60 * 60
LOST_S = 30 * 60
MAX_LIFE_S = 12 * 60 * 60
# Status wątku T3 po końcu tury; każdy inny (running, waiting na odpowiedź, preparing, nieznany) znaczy, że wątek trwa.
FINISHED = frozenset({"completed", "failed", "interrupted", "cancelled"})
NUDGE = "Strażnik koordynatora (tools/hooks/straznik_koordynatora.py):"


@dataclass(frozen=True)
class Seen:
    """Stan wątku z ``t3 thread show``: status i ``updatedAt`` w sekundach epoki Uniksa."""

    status: str
    updated: float

    def age(self, now: float) -> float:
        return now - self.updated


@dataclass
class Memory:
    """Co strażnik pamięta między pytaniami: koniec każdego dziecka (``updatedAt``), od kiedy dziecka nie widać, klucze
    powodów, z którymi już budził, i chwilę ostatniego budzenia."""

    ended: dict[str, float] = field(default_factory=dict)
    unseen: dict[str, float] = field(default_factory=dict)
    told: set[str] = field(default_factory=set)
    last_nudge: float = float("-inf")


def observe(children: dict[str, Seen | None], now: float, memory: Memory) -> None:
    """Dziecko ``None`` to dziecko, którego ``t3 thread show`` nie pokazuje (usunięte, środowisko odłączone, T3 nie
    odpowiada). Zapisuje koniec dziecka z jego ``updatedAt`` przy pierwszym pytaniu, na które dziecko jest skończone, i
    potem go nie zmienia, bo ``updatedAt`` skończonego wątku T3 przesuwa się później także bez jego pracy (restart T3);
    dziecko, które znów trwa (wznowione przez koordynatora), traci zapisany koniec."""

    for name, state in children.items():
        if state is None:
            memory.unseen.setdefault(name, now)
            continue
        memory.unseen.pop(name, None)
        if state.status not in FINISHED:
            memory.ended.pop(name, None)
        elif name not in memory.ended:
            memory.ended[name] = state.updated


def stalled(parent: Seen, children: dict[str, Seen | None], now: float, memory: Memory) -> dict[str, str]:
    """Powody budzenia wątku ``parent`` po kluczu (dziecko i rodzaj powodu), bez względu na to, czy wątek biegnie."""

    reasons = {}
    for child, state in children.items():
        ended = memory.ended.get(child)
        if state is None:
            continue
        if state.status not in FINISHED and state.age(now) > CHILD_STALE_S:
            reasons[f"{child} stoi"] = f"dziecko {child} ({state.status}) bez ruchu od {int(state.age(now) // 60)} min"
        elif ended is not None and WAKE_S < now - ended and parent.updated < ended:
            reasons[f"{child} bez budzenia"] = (
                f"dziecko {child} skończyło się statusem {state.status} {int((now - ended) // 60)} min temu, a ten "
                "wątek od tego czasu nie ruszył"
            )
    return reasons


def decide(parent: Seen, children: dict[str, Seen | None], now: float, memory: Memory) -> list[str]:
    observe(children, now, memory)
    fresh = {key: text for key, text in stalled(parent, children, now, memory).items() if key not in memory.told}
    if parent.status not in FINISHED or not fresh or now - memory.last_nudge < PAUSE_S:
        return []
    memory.told.update(fresh)
    memory.last_nudge = now
    return list(fresh.values())


def pending(parent: Seen, children: dict[str, Seen | None], now: float, memory: Memory) -> bool:
    for child, state in children.items():
        if state is None:
            if now - memory.unseen.get(child, now) <= LOST_S:
                return True
        elif state.status not in FINISHED:
            return True
        elif child in memory.ended and parent.updated <= memory.ended[child] and f"{child} bez budzenia" not in memory.told:
            return True
    return False


def alive(newest: float | None, now: float, life: float) -> bool:
    return newest is not None and now - newest <= life


def entries(text: str, now: float, life: float) -> tuple[list[str], float | None]:
    """Dzieci z wpisów pliku ``.dzieci`` młodszych niż ``life`` (bez powtórzeń, w kolejności zleceń) i chwila
    najmłodszego wpisu; linia, która nie ma postaci ``<chwila> <dziecko>``, nic nie znaczy."""

    children: list[str] = []
    newest = None
    for line in text.splitlines():
        moment, _, child = line.partition(" ")
        try:
            when = float(moment)
        except ValueError:
            continue
        if child and now - when <= life:
            newest = when if newest is None else max(newest, when)
            if child not in children:
                children.append(child)
    return children, newest


def message(reasons: list[str]) -> str:
    return (
        f"{NUDGE} {'; '.join(reasons)}. Sprawdź task_status każdego dziecka tego wątku, wznów albo zleć od nowa to, co "
        "stoi, i zapisz stan; tę wiadomość wysłał proces strażnika, nie Maks."
    )


def children_in(response: object) -> list[str]:
    found: list[str] = []
    stack = [response]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            with contextlib.suppress(ValueError):
                stack.append(json.loads(item))
        elif isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            for key, value in item.items():
                if key == CHILD_KEY and isinstance(value, str) and value not in found:
                    found.append(value)
                else:
                    stack.append(value)
    return found


@dataclass(frozen=True)
class Files:
    kids: Path
    life: Path
    queue: Path
    log: Path


def _files(thread: str) -> Files:
    base = Path.home() / STATE
    name = hashlib.sha256(thread.encode("utf-8")).hexdigest()[:16]
    return Files(base / f"{name}.dzieci", base / f"{name}.zycie", base / f"{name}.kolejka", base / f"{name}.jsonl")


def _log(path: Path, **row: object) -> None:
    row = {"czas": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"straznik_koordynatora: dziennik {path} niedostępny: {error!r}", file=sys.stderr)


def _taken(handle: IO[str], *, wait: bool) -> bool:
    """Bierze blokadę pliku ``handle`` (z ``wait`` czekając na nią); ``fcntl`` jest tylko na POSIX, a hook na Windows
    nic nie robi."""

    if sys.platform == "win32":
        return False
    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def record(files: Files, children: list[str], now: float) -> None:
    """Dopisuje dzieci z chwilą zlecenia; jeden zapis w trybie dopisywania, więc linie dwóch hooków się nie mieszają."""

    files.kids.parent.mkdir(parents=True, exist_ok=True)
    with files.kids.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{now!r} {child}\n" for child in children))


def _start(thread: str, files: Files) -> int:
    return potomne.detach(
        [sys.executable, str(Path(__file__).resolve()), "pilnuj", thread], cwd=Path.home(), stderr=files.log
    )


def _show(cli: str, thread: str) -> Seen | None:
    try:
        shown = potomne.run([cli, "thread", "show", thread, "--json", "--messages", "0"], cwd=Path.home(), timeout=60)
        if shown.returncode:
            raise ValueError(f"kod {shown.returncode}: {shown.stderr.strip()}")
        state = json.loads(shown.stdout)["thread"]
        moved = datetime.fromisoformat(str(state["updatedAt"]).replace("Z", "+00:00"))
        return Seen(str(state["status"]), moved.timestamp())
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        print(f"straznik_koordynatora: t3 thread show {thread}: {error!r}", file=sys.stderr)
        return None


def _send(cli: str, thread: str, text: str) -> int:
    return potomne.run([cli, "thread", "send", thread, text], cwd=Path.home(), timeout=60).returncode


def serve(thread: str, cli: str) -> int:
    files = _files(thread)
    files.kids.parent.mkdir(parents=True, exist_ok=True)
    with files.life.open("a") as life:
        with files.queue.open("a") as queue:
            if not _taken(queue, wait=False):
                return 0
            if not _taken(life, wait=True):
                return 0
        return watch(thread, cli, files)


def watch(thread: str, cli: str, files: Files) -> int:
    """Pętla pilnującego, który trzyma blokadę życia; każdy przebieg czyta plik ``.dzieci`` od zera."""

    _log(files.log, zdarzenie="start", pid=os.getpid())
    step = float(os.environ.get(STEP_ENV) or STEP_S)
    life = float(os.environ.get(LIFE_ENV) or MAX_LIFE_S)
    memory = Memory()
    while True:
        try:
            text = files.kids.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        names, newest = entries(text, time.time(), life)
        if not alive(newest, time.time(), life):
            _log(files.log, zdarzenie="koniec", powod="limit życia: brak zlecenia młodszego niż limit")
            return 0
        parent = _show(cli, thread)
        children = {name: _show(cli, name) for name in names} if parent is not None else {}
        now = time.time()
        if parent is not None:
            if parent.status == "running" and parent.age(now) > STUCK_S and "zastój" not in memory.told:
                memory.told.add("zastój")
                _log(files.log, zdarzenie="zastój", szczegoly=f"wątek running bez ruchu od {int(parent.age(now) // 60)} min")
            reasons = decide(parent, children, now, memory)
            if reasons:
                _log(files.log, zdarzenie="budzenie", powody=reasons, kod=_send(cli, thread, message(reasons)))
            elif not pending(parent, children, now, memory):
                _log(files.log, zdarzenie="koniec", powod="nie ma czego pilnować: nic nie trwa ani nie czeka na budzenie")
                return 0
        assert newest is not None
        time.sleep(max(0.0, min(step, newest + life - time.time())))


def main(argv: list[str]) -> int:
    thread, cli = os.environ.get(THREAD_ENV), os.environ.get(CLI_ENV)
    if sys.platform == "win32" or not thread or not cli:
        return 0
    if argv[:1] == ["pilnuj"] and len(argv) == 2:
        return serve(argv[1], cli)
    try:
        event: object = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, RecursionError):
        event = None
    fields = event if isinstance(event, dict) else {}
    if fields.get("hook_event_name") == "PostToolUse" and fields.get("tool_name") != DELEGATE:
        return 0
    new = [child for child in children_in(fields.get("tool_response")) if child != thread]
    files = _files(thread)
    if not new and not files.kids.exists():
        return 0
    try:
        if new:
            record(files, new, time.time())
        done = f"strażnik uruchomiony (PID {_start(thread, files)})"
    except OSError as error:
        done = f"błąd: {error!r}"
    _log(files.log, zdarzenie=fields.get("hook_event_name"), dzieci=new, wynik=done)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
