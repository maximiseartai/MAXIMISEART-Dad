#!/usr/bin/env python3
"""Hooki ``PostToolUse`` i ``SessionStart`` Claude Code w T3: wątek, który zlecił pracę innym wątkom, dostaje strażnika sam.

Koordynator (wątek T3, który zleca pracę innym wątkom i czeka na nich, często na noc) staje po cichu, gdy dziecko
utknie albo T3 go nie obudzi po końcu dziecka, a nikt tego nie widzi do rana. Strażnika spoza procesu Claude Code
stawiał dotąd sam koordynator, ze skryptu kopiowanego z biegu do biegu, więc stawiał go dopiero na prośbę Maksa,
choć instrukcja kazała bez niej. Tu strażnika stawia hook, bez osądu agenta, czy jest koordynatorem i czy praca potrwa.

Hook ``PostToolUse`` z dopasowaniem ``DELEGATING`` (``.claude/settings.json``) bierze z odpowiedzi narzędzia
identyfikatory wątków dzieci (pola ``CHILD_KEYS``), dopisuje je do stanu wątku i uruchamia strażnika, gdy żaden nie
trzyma blokady wątku. Hook ``SessionStart`` (wznowienie sesji, także po restarcie T3 albo Maca, po którym strażnika
może już nie być) uruchamia go ponownie, gdy wątek ma stan. Wątek to ``T3CODE_THREAD_ID``, a
program T3 to ``T3CODE_CLI_PATH``, oba ze środowiska, które T3 daje sesji: bez nich (Claude Code poza T3, komputer
taty) i na Windows hook nic nie robi. Stan, blokada i dziennik leżą w ``~/.cache/maximiseart/straznik/`` (``STATE``),
plik na wątek nazwany skrótem jego identyfikatora.

Strażnik (``pilnuj <wątek>``) to proces z ``potomne.detach``, więc koniec Claude Code go nie kończy. Co ``STEP_S``
sekund pyta ``t3 thread show`` o wątek i każde dziecko (status i ``updatedAt``, czyli chwilę ostatniego ruchu):

- ``decide`` budzi wątek (``t3 thread send``), gdy wątek skończył turę (status z ``FINISHED``, także ``failed`` i
  ``interrupted``), a dziecko trwa bez ruchu dłużej niż ``CHILD_STALE_S`` albo skończyło się ponad ``WAKE_S`` temu, a
  wątek od tego czasu nie ruszył, czyli T3 go nie obudził (``stalled``; koniec dziecka daje ``observe``);
- tego samego powodu (dziecko i rodzaj powodu) nie powtarza, a dwa budzenia dzieli ``PAUSE_S``;
- wątek ``running`` bez ruchu dłużej niż ``STUCK_S`` tylko zapisuje w dzienniku, bo wiadomość do zajętego wątku
  czeka na jego następną turę;
- kończy się, gdy żadne dziecko nie trwa, a wątek ruszył po każdym końcu dziecka (``settled``), gdy ktoś usunie
  stan wątku (plik ``.dzieci``), a także po ``GIVE_UP_S`` bez odpowiedzi T3.

Granica: dzieci to tylko wątki T3 z odpowiedzi narzędzi ``DELEGATING``; podagent narzędzia Agent biegnie w procesie
koordynatora i nie ma wątku, więc strażnik go nie widzi. Koordynator stojący przy gotowym PR bez żywego dziecka nie
dostaje budzenia. T3, które przy końcu dziecka dopisze coś do wątku rodzica bez jego tury, przesunie ruch rodzica i
ukryje brak budzenia. Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową i ``potomne``.
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

DELEGATING = ("mcp__t3-code__delegate_task", "mcp__t3-code__create_threads", "mcp__t3-code__t3_thread_launch")
CHILD_KEYS = ("childThreadId", "threadId")
THREAD_ENV = "T3CODE_THREAD_ID"
CLI_ENV = "T3CODE_CLI_PATH"
STATE = Path(".cache") / "maximiseart" / "straznik"
# Odstęp pytań strażnika; test podaje krótszy, żeby strażnik skończył się w kilka sekund.
STEP_ENV = "MAXIMISEART_STRAZNIK_ODSTEP_S"
STEP_S = 300.0
CHILD_STALE_S = 45 * 60
WAKE_S = 15 * 60
PAUSE_S = 30 * 60
STUCK_S = 60 * 60
GIVE_UP_S = 6 * 60 * 60
# Status wątku T3 po końcu tury; każdy inny (running, waiting na odpowiedź, preparing, nieznany) znaczy, że wątek trwa.
FINISHED = frozenset({"completed", "failed", "interrupted", "cancelled"})
NO_STATE = "bez stanu"
NUDGE = "Strażnik koordynatora (tools/hooks/straznik_koordynatora.py):"


@dataclass(frozen=True)
class Seen:
    """Stan wątku z ``t3 thread show``: status i sekundy od jego ostatniego ruchu (``updatedAt``)."""

    status: str
    age_s: float


@dataclass
class Memory:
    """Co strażnik pamięta między pytaniami: chwilę (na zegarze strażnika) końca każdego dziecka, klucze powodów, z
    którymi już budził, i chwilę ostatniego budzenia."""

    ended: dict[str, float] = field(default_factory=dict)
    told: set[str] = field(default_factory=set)
    last_nudge: float = float("-inf")


def observe(children: dict[str, Seen], now: float, memory: Memory) -> None:
    """Zapisuje koniec dziecka z jego ``updatedAt`` przy pierwszym pytaniu, na które dziecko jest skończone, i potem go
    nie zmienia, bo ``updatedAt`` skończonego wątku T3 przesuwa się później także bez jego pracy (restart T3). Dziecko,
    które znów trwa (wznowione przez koordynatora), traci zapisany koniec."""

    for child, state in children.items():
        if state.status not in FINISHED:
            memory.ended.pop(child, None)
        elif child not in memory.ended:
            memory.ended[child] = now - state.age_s


def stalled(parent: Seen, children: dict[str, Seen], now: float, memory: Memory) -> dict[str, str]:
    """Powody budzenia wątku ``parent`` po kluczu (dziecko i rodzaj powodu), bez względu na to, czy wątek biegnie."""

    reasons = {}
    for child, state in children.items():
        ended = memory.ended.get(child)
        if state.status not in FINISHED and state.age_s > CHILD_STALE_S:
            reasons[f"{child} stoi"] = f"dziecko {child} ({state.status}) bez ruchu od {int(state.age_s // 60)} min"
        elif ended is not None and WAKE_S < now - ended < parent.age_s:
            reasons[f"{child} bez budzenia"] = (
                f"dziecko {child} skończyło się statusem {state.status} {int((now - ended) // 60)} min temu, a ten "
                "wątek od tego czasu nie ruszył"
            )
    return reasons


def decide(parent: Seen, children: dict[str, Seen], now: float, memory: Memory) -> list[str]:
    """Powody, z którymi budzić wątek teraz (pusta lista: nie budzić); zapamiętuje to pytanie i budzenie w ``memory``."""

    observe(children, now, memory)
    fresh = {key: text for key, text in stalled(parent, children, now, memory).items() if key not in memory.told}
    if parent.status not in FINISHED or not fresh or now - memory.last_nudge < PAUSE_S:
        return []
    memory.told.update(fresh)
    memory.last_nudge = now
    return list(fresh.values())


def settled(parent: Seen, children: dict[str, Seen], now: float, memory: Memory) -> bool:
    """Żadne dziecko nie biegnie, a wątek ruszył po każdym końcu dziecka, który strażnik zobaczył (po ``decide``)."""

    return all(
        state.status in FINISHED and (child not in memory.ended or parent.age_s < now - memory.ended[child])
        for child, state in children.items()
    )


def message(reasons: list[str]) -> str:
    return (
        f"{NUDGE} {'; '.join(reasons)}. Sprawdź task_status każdego dziecka tego wątku, wznów albo zleć od nowa to, co "
        "stoi, i zapisz stan; tę wiadomość wysłał proces strażnika, nie Maks."
    )


def children_in(response: object) -> list[str]:
    """Identyfikatory wątków z pól ``CHILD_KEYS`` w odpowiedzi narzędzia, także w tekście JSON wewnątrz niej."""

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
                if key in CHILD_KEYS and isinstance(value, str) and value not in found:
                    found.append(value)
                else:
                    stack.append(value)
    return found


def _files(thread: str) -> tuple[Path, Path, Path]:
    base = Path.home() / STATE
    name = hashlib.sha256(thread.encode("utf-8")).hexdigest()[:16]
    return base / f"{name}.dzieci", base / f"{name}.blokada", base / f"{name}.jsonl"


def _log(path: Path, **row: object) -> None:
    row = {"czas": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"straznik_koordynatora: dziennik {path} niedostępny: {error!r}", file=sys.stderr)


def _taken(handle: IO[str]) -> bool:
    """Bierze blokadę pliku ``handle`` bez czekania; ``fcntl`` jest tylko na POSIX, a hook na Windows nic nie robi."""

    if sys.platform == "win32":
        return False
    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _guarded(lock: Path) -> bool:
    """Czy żywy strażnik trzyma blokadę wątku (blokadę zwalnia zamknięcie pliku)."""

    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        return not _taken(handle)


def arm(thread: str, new_children: list[str]) -> str:
    """Dopisuje dzieci do stanu wątku i uruchamia strażnika, gdy żaden nie żyje; zwraca, co zrobił, do dziennika."""

    kids, lock, log = _files(thread)
    kids.parent.mkdir(parents=True, exist_ok=True)
    if new_children:
        with kids.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"{child}\n" for child in new_children))
    elif not kids.exists():
        return NO_STATE
    if _guarded(lock):
        return "strażnik żyje"
    pid = potomne.detach([sys.executable, str(Path(__file__).resolve()), "pilnuj", thread], cwd=Path.home(), stderr=log)
    return f"strażnik uruchomiony (PID {pid})"


def _show(cli: str, thread: str) -> Seen | None:
    try:
        shown = potomne.run([cli, "thread", "show", thread, "--json", "--messages", "0"], cwd=Path.home(), timeout=60)
        if shown.returncode:
            raise ValueError(f"kod {shown.returncode}: {shown.stderr.strip()}")
        state = json.loads(shown.stdout)["thread"]
        moved = datetime.fromisoformat(str(state["updatedAt"]).replace("Z", "+00:00"))
        return Seen(str(state["status"]), (datetime.now(timezone.utc) - moved).total_seconds())
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        print(f"straznik_koordynatora: t3 thread show {thread}: {error!r}", file=sys.stderr)
        return None


def watch(thread: str, cli: str) -> int:
    """Pętla strażnika wątku ``thread``; trzyma blokadę wątku do końca, więc drugi strażnik kończy się od razu."""

    kids, lock, log = _files(thread)
    with lock.open("a") as handle:
        if not _taken(handle):
            return 0
        _log(log, zdarzenie="start", pid=os.getpid())
        step = float(os.environ.get(STEP_ENV) or STEP_S)
        memory, answered = Memory(), time.monotonic()
        while True:
            if not kids.exists():
                _log(log, zdarzenie="koniec", powod="stan wątku usunięty")
                return 0
            parent = _show(cli, thread)
            now = time.monotonic()
            if parent is None:
                if now - answered > GIVE_UP_S:
                    _log(log, zdarzenie="koniec", powod="T3 nie odpowiada")
                    return 1
                time.sleep(step)
                continue
            answered = now
            names = list(dict.fromkeys(kids.read_text(encoding="utf-8").split())) if kids.exists() else []
            shown = {name: _show(cli, name) for name in names}
            children = {name: seen for name, seen in shown.items() if seen is not None}
            if parent.status == "running" and parent.age_s > STUCK_S and "zastój" not in memory.told:
                memory.told.add("zastój")
                _log(log, zdarzenie="zastój", szczegoly=f"wątek running bez ruchu od {int(parent.age_s // 60)} min")
            reasons = decide(parent, children, now, memory)
            if reasons:
                sent = potomne.run([cli, "thread", "send", thread, message(reasons)], cwd=Path.home(), timeout=60)
                _log(log, zdarzenie="budzenie", powody=reasons, kod=sent.returncode)
            elif len(children) == len(shown) and settled(parent, children, now, memory):
                _log(log, zdarzenie="koniec", powod="nic nie biegnie, a wątek ruszył po końcu każdego dziecka")
                return 0
            time.sleep(step)


def main(argv: list[str]) -> int:
    thread, cli = os.environ.get(THREAD_ENV), os.environ.get(CLI_ENV)
    if sys.platform == "win32" or not thread or not cli:
        return 0
    if argv[:1] == ["pilnuj"] and len(argv) == 2:
        return watch(argv[1], cli)
    try:
        event: object = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, RecursionError):
        event = None
    fields = event if isinstance(event, dict) else {}
    new = [child for child in children_in(fields.get("tool_response")) if child != thread]
    try:
        done = arm(thread, new)
    except OSError as error:
        done = f"błąd: {error!r}"
    if done != NO_STATE:
        _log(_files(thread)[2], zdarzenie=fields.get("hook_event_name"), dzieci=new, wynik=done)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
