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
  powiadomienie o jego końcu do wątku nie dotarło (``stalled``; koniec dziecka zapisuje ``observe``);
- powiadomienie dotarło, gdy ostatni kontakt koordynatora z bieżącym biegiem dziecka mówi, że wie o jego końcu
  (``hear``, kolejność wpisów w transkrypcie, bez zegara). Bieg to ``TASK_KEY`` z odpowiedzi narzędzia z ``STARTS``
  (``delegate_task`` i ``t3_thread_send``, rozpoznanej po ``tool_use_id`` wywołania), który T3 nadaje w każdej postaci
  węzła (``delegate-task``, ``thread-send``, ``provider-continuation``). Kontaktem jest powiadomienie T3 (wiadomość
  ``user`` z tekstem, nie wynik narzędzia, z linią od ``notice``; ``queue-operation`` to jeszcze kolejka) i odpowiedź
  na dowolne własne wywołanie koordynatora, której przedmiotem jest ten bieg (``_subject``). „Wie o końcu” daje tylko
  zamknięty zbiór znaczników końca: powiadomienie i odpowiedź ze statusem biegu z ``FINISHED`` (``_ended``; ten sam
  zbiór co dla ``t3 thread show``, z ``cancel_requested`` odpowiedzi ``task_cancel``). Odpowiedź startu i każda inna
  odpowiedź o biegu, także ze stanem, którego zbiór nie zna (``waiting_for_children``), albo bez statusu, znaczą
  „trwa”, więc nieznany kształt kosztuje najwyżej jedno zbędne budzenie, a nigdy zgubione powiadomienie. Kolejność,
  nie chwila, bo T3 przesuwa ``updatedAt`` skończonego dziecka po powiadomieniu (rozliczenie dzieci przy końcu
  rodzeństwa, restart), więc nowy pilnujący widziałby powiadomienie „przed końcem”. Ścieżki dają linie pliku ``.transkrypt``, które hook dopisuje z ``transcript_path``
  wejścia; strażnik czyta każdy transkrypt w kolejności dopisania, od miejsca, w którym skończył, bo dziecko zlecone w
  starej sesji ma tam swój start i powiadomienie. Sam ruch wątku nie wystarcza, bo koordynator zajęty innymi dziećmi
  rusza się także wtedy, gdy T3 powiadomienie zgubiło (9.11.2026 gotowy wynik przeglądu PR czekał przez to godzinę);
  bez transkryptu i dla dziecka bez startu w transkryptach dotarciem jest, jak dotąd, ruch wątku po końcu dziecka;
- tego samego powodu (dziecko i rodzaj powodu) nie powtarza, a dwa budzenia dzieli ``PAUSE_S``;
- wątek ``running`` bez ruchu dłużej niż ``STUCK_S`` tylko zapisuje w dzienniku, bo wiadomość do zajętego wątku
  czeka na jego następną turę;
- kończy się wcześniej, gdy nie ma już czego pilnować (``pending``: żadne dziecko nie trwa, a po każdym końcu dziecka
  powiadomienie dotarło albo wątek dostał budzenie; dziecko, którego ``t3 thread show`` nie pokazuje dłużej niż
  ``LOST_S``, przestaje się liczyć).

Granica: dzieci to tylko wątki z ``childThreadId`` w odpowiedzi ``delegate_task``; dziecko w innym środowisku (og-box)
ma ``childThreadId`` null, a jego identyfikator należy do tamtego środowiska, więc strażnik go nie pilnuje; podagent
narzędzia Agent biegnie w procesie koordynatora i nie ma wątku, więc strażnik go nie widzi. Koordynator stojący przy
gotowym PR bez żywego dziecka nie dostaje budzenia. Plik ``.dzieci`` rośnie o linię na zlecenie, a ``.transkrypt`` o
linię na nową sesję wątku, i nikt ich nie skraca; przez całe życie pilnującego obok śpi najwyżej jeden czekający
proces. Bieg rozpoznaje ``taskId``, nie tytuł, więc powiadomienie o rodzeństwie o tym samym początku tytułu nie kończy
czekania. Bieg, który T3 wznowi samo (bez ``t3_thread_send``), nie ma startu w transkrypcie, więc ostatni kontakt z
poprzednim biegiem ukrywa brak jego powiadomienia; koordynator, który dowiedział się o końcu poza T3 (werdykt na
GitHubie), a powiadomienie nie przyszło, dostaje jedno budzenie; inny początek powiadomienia w przyszłym T3 dałby jedno
budzenie na każde dziecko; odczyt wątku ze statusem ``completed`` przed powiadomieniem jego biegu (T3 pokazuje koniec
tury dziecka, a bieg czeka) liczy się jako koniec.
Bez transkryptu brak powiadomienia ukrywa też T3, które przy końcu dziecka dopisze coś do wątku rodzica bez jego tury.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9 (``per-file-target-version`` w
``pyproject.toml``), a plik importuje tylko bibliotekę standardową i ``potomne``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
# Status wątku albo biegu T3 po końcu (``cancel_requested`` daje odpowiedź task_cancel koordynatora); każdy inny
# (running, waiting na odpowiedź, preparing, nieznany, brak) znaczy, że wątek albo bieg trwa.
FINISHED = frozenset({"completed", "failed", "interrupted", "cancelled", "cancel_requested"})
# Narzędzia, których odpowiedź to start biegu dziecka (zlecenie i wiadomość do dziecka), i pola tej odpowiedzi:
# wątek dziecka (``CHILD_KEY`` po zleceniu, ``SEND_KEY`` po wiadomości) i węzeł biegu, który niesie jego powiadomienie.
STARTS = frozenset({DELEGATE, "mcp__t3-code__t3_thread_send"})
SEND_KEY = "threadId"
TASK_KEY = "taskId"
NOTICE = "Delegated task "
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
    powodów, z którymi już budził, chwilę ostatniego budzenia, czy po ostatnim starcie dziecka dotarło do transkryptu
    wątku powiadomienie o tym biegu (``heard``; ``None``: transkryptu nie ma, więc dotarciem jest ruch wątku),
    ``taskId`` ostatniego biegu każdego dziecka (``runs``) i identyfikatory wywołań narzędzi ``STARTS`` (``starts``)."""

    ended: dict[str, float] = field(default_factory=dict)
    unseen: dict[str, float] = field(default_factory=dict)
    told: set[str] = field(default_factory=set)
    last_nudge: float = float("-inf")
    heard: dict[str, bool] | None = None
    runs: dict[str, str] = field(default_factory=dict)
    starts: set[str] = field(default_factory=set)


def unheard(child: str, parent: Seen, memory: Memory) -> bool:
    """Czy po zapisanym końcu dziecka powiadomienie o nim nie dotarło do wątku ``parent``."""

    if memory.heard is None or child not in memory.heard:
        return parent.updated < memory.ended[child]
    return not memory.heard[child]


def _blocks(entry: dict[str, object], kind: str) -> list[dict[str, object]]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    blocks = content if isinstance(content, list) else []
    return [block for block in blocks if isinstance(block, dict) and block.get("type") == kind]


def _replies(block: dict[str, object]) -> list[dict[str, object]]:
    """Obiekty JSON z tekstu odpowiedzi narzędzia (napis albo lista bloków ``text``)."""

    content = block.get("content")
    texts = [content] if isinstance(content, str) else []
    if isinstance(content, list):
        texts += [str(part.get("text")) for part in content if isinstance(part, dict) and part.get("type") == "text"]
    found = []
    for text in texts:
        with contextlib.suppress(ValueError, RecursionError):
            reply = json.loads(text)
            if isinstance(reply, dict):
                found.append(reply)
    return found


def _subject(reply: dict[str, object], runs: Mapping[str, str]) -> str | None:
    """Dziecko, którego bieżący bieg jest przedmiotem odpowiedzi: ``thread.threadId``, ``CHILD_KEY`` albo ``SEND_KEY``
    równe dziecku albo ``TASK_KEY`` równy jego biegowi (``None``: odpowiedź nie mówi o żadnym pilnowanym biegu)."""

    thread = reply.get("thread")
    named = thread.get(SEND_KEY) if isinstance(thread, dict) else reply.get(CHILD_KEY) or reply.get(SEND_KEY)
    if isinstance(named, str) and named in runs:
        return named
    task = reply.get(TASK_KEY)
    return next((child for child, run in runs.items() if task == run), None)


def _ended(reply: dict[str, object]) -> bool:
    """Czy odpowiedź mówi, że bieg się skończył: jego status (``thread.status`` w odczycie wątku, ``status`` w
    odpowiedzi o zadaniu) należy do ``FINISHED``; każdy inny status, brak statusu i inny kształt znaczą, że trwa."""

    thread = reply.get("thread")
    shown = thread if isinstance(thread, dict) else reply
    return shown.get("status") in FINISHED


def _text(entry: dict[str, object]) -> str:
    """Tekst wiadomości wpisu (napis albo bloki ``text``), bez wyników narzędzi."""

    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    return "\n".join(str(block.get("text")) for block in _blocks(entry, "text"))


def notice(task: str) -> str:
    """Początek linii powiadomienia T3 o końcu biegu ``task``."""

    return f"{NOTICE}{task} "


def hear(path: Path, offset: int, children: Iterable[str], memory: Memory) -> int:
    """Czyta transkrypt od bajtu ``offset`` do ostatniej pełnej linii i zapisuje w ``memory.heard``, co po ostatnim
    kontakcie z bieżącym biegiem dziecka koordynator sądzi: ``False`` (trwa: odpowiedź startu albo odpowiedź, która
    mówi, że bieg trwa) albo ``True`` (wie o końcu: powiadomienie T3 i każda inna odpowiedź o tym biegu); zwraca
    miejsce, od którego czytać następnym razem."""

    heard = memory.heard if memory.heard is not None else {}
    memory.heard = heard
    watched = set(children)
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    complete = data[: data.rfind(b"\n") + 1]
    for raw in complete.splitlines():
        line = raw.decode("utf-8", errors="replace")
        signs = [*STARTS, *watched, *memory.runs.values()]
        if NOTICE not in line and not any(sign in line for sign in signs):
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "assistant":
            memory.starts.update(str(block.get("id")) for block in _blocks(entry, "tool_use") if block.get("name") in STARTS)
            continue
        if entry.get("type") != "user":
            continue
        runs = {child: run for child, run in memory.runs.items() if child in watched}
        for block in _blocks(entry, "tool_result"):
            start = block.get("tool_use_id") in memory.starts
            for reply in _replies(block):
                if start:
                    child, task = reply.get(CHILD_KEY) or reply.get(SEND_KEY), reply.get(TASK_KEY)
                    if child in watched and isinstance(task, str) and task:
                        memory.runs[str(child)] = runs[str(child)] = task
                        heard[str(child)] = False
                    continue
                about = _subject(reply, runs)
                if about is not None:
                    heard[about] = _ended(reply)
        said = _text(entry).splitlines()
        for child, task in runs.items():
            if any(text.startswith(notice(task)) for text in said):
                heard[child] = True
    return offset + len(complete)


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
        elif ended is not None and WAKE_S < now - ended and unheard(child, parent, memory):
            reasons[f"{child} bez budzenia"] = (
                f"dziecko {child} skończyło się statusem {state.status} {int((now - ended) // 60)} min temu, a "
                "powiadomienie o jego końcu do tego wątku nie dotarło"
            )
    return reasons


def decide(parent: Seen, children: dict[str, Seen | None], now: float, memory: Memory) -> list[str]:
    """Powody, z którymi budzić wątek teraz (pusta lista: nie budzić); zapamiętuje to pytanie i budzenie w ``memory``."""

    observe(children, now, memory)
    fresh = {key: text for key, text in stalled(parent, children, now, memory).items() if key not in memory.told}
    if parent.status not in FINISHED or not fresh or now - memory.last_nudge < PAUSE_S:
        return []
    memory.told.update(fresh)
    memory.last_nudge = now
    return list(fresh.values())


def pending(parent: Seen, children: dict[str, Seen | None], now: float, memory: Memory) -> bool:
    """Czy po ``decide`` zostało coś do pilnowania: dziecko trwa, dziecka nie widać krócej niż ``LOST_S`` albo po końcu
    dziecka wątek nie ruszył i nie dostał budzenia."""

    for child, state in children.items():
        if state is None:
            if now - memory.unseen.get(child, now) <= LOST_S:
                return True
        elif state.status not in FINISHED:
            return True
        elif child in memory.ended and unheard(child, parent, memory) and f"{child} bez budzenia" not in memory.told:
            return True
    return False


def alive(newest: float | None, now: float, life: float) -> bool:
    """Czy strażnik może jeszcze żyć: od najmłodszego wpisu ``.dzieci`` (``None``: brak wpisu) minęło najwyżej ``life``."""

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
    """Identyfikatory wątków z pól ``CHILD_KEY`` w odpowiedzi narzędzia, także w tekście JSON wewnątrz niej."""

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
    transcript: Path


def _files(thread: str) -> Files:
    base = Path.home() / STATE
    name = hashlib.sha256(thread.encode("utf-8")).hexdigest()[:16]
    kids, life, queue, log, transcript = (base / f"{name}.{kind}" for kind in ("dzieci", "zycie", "kolejka", "jsonl", "transkrypt"))
    return Files(kids, life, queue, log, transcript)


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


def _transcripts(files: Files) -> list[Path]:
    """Transkrypty sesji wątku z pliku ``.transkrypt`` w kolejności dopisania, bez powtórzeń (pusta lista: hook żadnego
    nie podał)."""

    try:
        lines = files.transcript.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [Path(line) for line in dict.fromkeys(lines) if line]


def _send(cli: str, thread: str, text: str) -> int:
    return potomne.run([cli, "thread", "send", thread, text], cwd=Path.home(), timeout=60).returncode


def serve(thread: str, cli: str) -> int:
    """Proces strażnika: kolejka bez czekania, potem życie z czekaniem, oddanie kolejki i dopiero wtedy pętla ``watch``
    (kolejność kroków i czemu, mówi docstring modułu)."""

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
    offsets: dict[Path, int] = {}
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
        # Każda sesja wątku pisze swój transkrypt; dziecko zlecone w starej sesji ma tam swój start i powiadomienie.
        for transcript in _transcripts(files):
            try:
                offsets[transcript] = hear(transcript, offsets.get(transcript, 0), names, memory)
            except OSError as error:
                print(f"straznik_koordynatora: transkrypt {transcript}: {error!r}", file=sys.stderr)
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
        transcript = fields.get("transcript_path")
        if isinstance(transcript, str) and transcript and Path(transcript) not in _transcripts(files):
            with files.transcript.open("a", encoding="utf-8") as handle:
                handle.write(transcript + "\n")
        done = f"strażnik uruchomiony (PID {_start(thread, files)})"
    except OSError as error:
        done = f"błąd: {error!r}"
    _log(files.log, zdarzenie=fields.get("hook_event_name"), dzieci=new, wynik=done)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
