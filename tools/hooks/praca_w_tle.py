#!/usr/bin/env python3
"""Hooki ``Stop`` i ``PostToolUse`` Claude Code: agent nie kończy tury, dopóki w tle biegnie jego polecenie Basha albo
jego Monitor, którego nie zarejestrował w ``t3_background_wait``.

Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: wywołujący (rodzic, T3, ``claude -p``)
dostaje odpowiedź bez wyniku, a agent stoi. W nocy 4/5.11.2026 tak stanęło pięciu delegatów T3 („czekam na
powiadomienie o procesie w tle”) i za każdym razem było to polecenie Basha z ``run_in_background``; zakaz w briefie nie
pomógł.

Claude Code (2.1.318 i 2.1.328, ``claude -p`` w ``tools/wyrocznia_pracy_w_tle.py``) podaje hookowi ``Stop`` listę
``background_tasks`` z zadaniami sesji w statusie ``running`` albo ``pending`` (skończone z niej znikają), każde z
``id``, ``type`` i ``status``. Typ ``shell`` mają zadania ``local_bash``: polecenie Basha z ``run_in_background`` i
Monitor agenta (narzędzie Monitor tworzy ``local_bash`` z ``kind`` ``monitor``). Hook odmawia (JSON
``{"decision": "block", "reason": …}`` na stdout, kod 0; ``reason`` trafia do agenta jako polecenie dalszej pracy),
gdy na liście jest zadanie typu ``BLOCKING`` o statusie z ``ALIVE``, którego nie przepuszcza plik sesji (niżej).
Odmawia także przy ``stop_hook_active``: Claude Code ustawia je po pierwszej odmowie do końca tury, także po wywołaniach
narzędzi, więc przepuszczenie przy nim oddałoby turę z pracą w tle już przy drugiej próbie. Pętlę bez końca ucina sam
Claude Code: po ośmiu odmowach z rzędu bez wywołania narzędzia kończy turę z ostrzeżeniem
(``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``), a wywołanie narzędzia zeruje ten licznik.

Lista należy do całej sesji, także do podagentów narzędzia Agent, a wpis ``shell`` podagenta ma te same pola co wpis
głównej pętli (Claude Code 2.1.328, przypadek ``shell-podagenta`` wyroczni). Właściciela zadania widzi tylko hook
``PostToolUse``: wejście narzędzia wywołanego w podagencie ma ``agent_id``, a ID zadania stoi w odpowiedzi narzędzia
(pole z ``SPAWNED``). Hook ``PostToolUse`` (``.claude/settings.json``: ``Bash``, ``Monitor`` i ``WAIT``) dopisuje do
pliku sesji (``STATE``, plik ``<session_id>.jsonl``) zadania, które hook ``Stop`` przepuszcza:

- zadanie uruchomione w podagencie, bo jego koniec dostaje podagent, a nie wątek, który kończy turę;
- zadanie z ``taskIds`` wywołania ``t3_background_wait`` (``waiting: false`` je wypisuje), bo T3 trzyma wtedy wątek
  w pracy, a Claude Code po końcu zadania budzi sesję powiadomieniem i zaczyna nową turę (przypadek
  ``zadanie-zarejestrowane`` wyroczni), więc wywołujący nie dostaje odpowiedzi bez wyniku.

Plik sesji nie zawiera ani nie zastępuje listy ``background_tasks``: wpis zadania, które już się skończyło, niczego nie
przepuszcza. Pliki sesji starsze niż ``KEEP_S`` hook usuwa przy dopisaniu.

Typ ``monitor`` hook przepuszcza i zapisuje w dzienniku (``UNSURE``): mają go ``monitor_mcp`` (monitor serwera MCP) i
``monitor_ws``, a ``monitor_ws`` to także obserwacja artefaktu, którą Claude Code włącza sam po jego publikacji i która
trwa do końca sesji. Claude Code pomija ją w swoich listach po polu ``ambient``, ale hookowi go nie podaje: rekord
obserwacji ma tylko ``id``, ``type``, ``status`` i ``description``, jak każdy ``monitor_ws``, więc żadne pole nie
odróżnia go od monitora, który agent uruchomił sam (binarka 2.1.318, budowa ``background_tasks``).

Wszystko inne przechodzi (kod 0, nic na stdout), bo fałszywa odmowa zatrzymałaby każdego agenta projektu: pusta lista,
znane typy, które same raportują wywołującemu (``REPORTING``: podagent, workflow, sesja w chmurze i inne), zaplanowane
wybudzenia (``session_crons``), a także wątpliwość: wejście nieczytelne albo bez listy ``background_tasks``, wpis
listy, który nie jest obiektem, ``type`` albo ``status``, które nie są tekstem, typ spoza ``BLOCKING`` i ``REPORTING``,
typ ``monitor`` i zadanie ``shell`` o statusie spoza ``ALIVE``. Wątpliwość, zadanie przepuszczone przez plik sesji i
każdą odmowę hook dopisuje do dziennika ``~/.cache/maximiseart/praca_w_tle.jsonl`` (``LOG``, inny plik daje zmienna
``LOG_ENV``, której używa wyrocznia; pliki sesji leżą obok niego); błąd zapisu dziennika albo pliku sesji trafia na
stderr i nie zmienia decyzji, a plik sesji, którego nie da się przeczytać, niczego nie przepuszcza. Hook po
``timeout`` z ustawień Claude Code zabija bez decyzji i tura się kończy (próba 5.11.2026 na 2.1.318), więc hook czyta
listę w czasie liniowym.

Granica: inne harnessy niż Claude Code (Codex, opencode) łapie tylko przegląd, a sesja, której ustawienia ze startu
nie mają hooka ``PostToolUse``, dostaje odmowę także za zadanie podagenta i zadanie zarejestrowane. Hook nie jest
wpięty w ``SubagentStop``, bo tam lista należy do całej sesji, a nie do podagenta. Monitor wtyczki (``monitors``
w manifeście wtyczki, uruchamiany bez prośby agenta) to też ``local_bash`` z ``kind`` ``monitor``, więc hook
odmówiłby przy nim jak przy Bashu; żadna wtyczka na Macu Maksa go nie deklaruje (5.11.2026).
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``ruff.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Optional

BLOCKING = "shell"
UNSURE = "monitor"
REPORTING = frozenset(
    {
        "subagent",
        "workflow",
        "MCP task",
        "teammate",
        "dream",
        "auto-mode scan",
        "memory import",
        "memory save",
        "cloud session",
    }
)
ALIVE = frozenset({"running", "pending"})
LOG = Path(".cache") / "maximiseart" / "praca_w_tle.jsonl"
LOG_ENV = "MAXIMISEART_PRACA_W_TLE_DZIENNIK"
# Katalog plików sesji obok dziennika: ``~/.cache/maximiseart/praca_w_tle/<session_id>.jsonl``.
STATE = "praca_w_tle"
KEEP_S = 7 * 24 * 3600
WAIT = "mcp__t3-code__t3_background_wait"
# Narzędzie, które uruchamia zadanie ``shell``, i pole jego odpowiedzi z ID zadania (Claude Code 2.1.328).
SPAWNED = {"Bash": "backgroundTaskId", "Monitor": "taskId"}
SESSION = re.compile(r"[A-Za-z0-9_-]{1,128}")
REFUSAL = "Odmowa końca tury: w tle sesji biegnie jeszcze"
# Jedyna droga czekania na własne zadanie w tle; ``tools/hooks/czekanie.py`` mówi to samo (test pilnuje równości).
WAIT_FOR_TASK = (
    "Na swoje zadanie w tle czekaj tylko tak: wywołaj t3_background_wait z taskIds (lista ID, nie taskId) i zakończ "
    "turę bez sleep i bez pętli; T3 trzyma wątek w pracy, a Claude Code budzi go powiadomieniem po końcu zadania. "
    "Zadanie, na które nie czekasz, zatrzymaj TaskStop z jego ID."
)


def judge(event: object, passed: dict[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    """ID i opisy żywych zadań ``BLOCKING`` spoza ``passed`` oraz wpisy dziennika z wejścia hooka ``Stop``.

    ``passed`` to zadania przepuszczone przez plik sesji z powodem; odmowa tylko przy żywych zadaniach spoza niego.
    """

    tasks = event.get("background_tasks") if isinstance(event, dict) else None
    if not isinstance(tasks, list):
        return [], ["wejście bez listy background_tasks"]
    alive: list[tuple[str, str]] = []
    notes: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            notes.append(f"wpis listy zadań nie jest obiektem: {type(task).__name__}")
            continue
        kind, status, name = task.get("type"), task.get("status"), task.get("id")
        described = f"{kind} {name} „{task.get('command') or task.get('description')}”"
        if not isinstance(kind, str) or not isinstance(status, str):
            notes.append(f"zadanie {name} z type {kind!r} i status {status!r}, z których nie każde jest tekstem")
        elif kind == BLOCKING and status in ALIVE and isinstance(name, str) and name in passed:
            notes.append(f"{described} przepuszczony: {passed[name]}")
        elif kind == BLOCKING and status in ALIVE:
            alive.append((str(name), described))
        elif kind == BLOCKING:
            notes.append(f"{kind} {name} o nieznanym statusie {status!r}")
        elif kind == UNSURE:
            notes.append(
                f"{kind} {name} „{task.get('description')}” ({status}) przepuszczony: typ monitor ma też obserwacja "
                "artefaktu, której Claude Code nie odróżnia w wejściu hooka"
            )
        elif kind not in REPORTING:
            notes.append(f"{kind} {name} ({status}) przepuszczony: nieznany typ zadania")
    return alive, notes


def refusal(tasks: list[tuple[str, str]]) -> str:
    ids = json.dumps([name for name, _ in tasks])
    return (
        f"{REFUSAL} {'; '.join(described for _, described in tasks)}. Tura oddana z pracą w tle wygląda na "
        "skończoną, choć wyniku jeszcze nie ma: wywołujący (rodzic, T3, claude -p) dostaje odpowiedź bez niego. "
        f"{WAIT_FOR_TASK} Tu: t3_background_wait z taskIds: {ids}. Poza T3 (bez t3_background_wait) zatrzymaj "
        "zadanie i uruchom tę pracę Bashem na pierwszym planie (timeout do 600000 ms, dłuższą dziel na części). "
        "Proces, który ma żyć po turze, bo prosi o to człowiek (serwer), zatrzymaj jako zadanie i uruchom odłączony "
        "(nohup … & w Bashu na pierwszym planie)."
    )


def remembered(event: dict[str, object]) -> list[dict[str, object]]:
    """Wpisy pliku sesji z wejścia hooka ``PostToolUse``: zadanie podagenta i zadania z wywołania ``WAIT``."""

    tool, given, answer, agent = (event.get(key) for key in ("tool_name", "tool_input", "tool_response", "agent_id"))
    if tool == WAIT and isinstance(given, dict) and isinstance(given.get("taskIds"), list):
        passes = given.get("waiting") is not False
        return [
            {"id": name, "przepuszczam": passes, "powod": "zarejestrowany w t3_background_wait"}
            for name in given["taskIds"]
            if isinstance(name, str)
        ]
    field = SPAWNED.get(tool) if isinstance(tool, str) else None
    started = answer.get(field) if field is not None and isinstance(answer, dict) else None
    if isinstance(agent, str) and agent and isinstance(started, str):
        return [{"id": started, "przepuszczam": True, "powod": f"zadanie podagenta {agent}"}]
    return []


def passed_in(lines: list[str]) -> dict[str, str]:
    """Zadania, które przepuszcza plik sesji o liniach ``lines``, z powodem; późniejszy wpis zadania wygrywa."""

    passed: dict[str, str] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        name = row.get("id") if isinstance(row, dict) else None
        if not isinstance(name, str):
            continue
        if row.get("przepuszczam") is True:
            passed[name] = str(row.get("powod"))
        else:
            passed.pop(name, None)
    return passed


def _log_path() -> Path:
    return Path(os.environ.get(LOG_ENV) or Path.home() / LOG)


def _session_file(event: object) -> Optional[Path]:
    session = event.get("session_id") if isinstance(event, dict) else None
    if not isinstance(session, str) or SESSION.fullmatch(session) is None:
        return None
    return _log_path().parent / STATE / f"{session}.jsonl"


def _remember(event: dict[str, object]) -> None:
    rows = remembered(event)
    if not rows:
        return
    try:
        path = _session_file(event)
        if path is None:
            _log(event, "pomijam", [f"zadania {[row['id'] for row in rows]} bez session_id, którym hook nazywa plik sesji"])
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as state:
            state.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        for old in path.parent.glob("*.jsonl"):
            if old.stat().st_mtime < time.time() - KEEP_S:
                old.unlink()
    except (OSError, RuntimeError, KeyError) as error:  # RuntimeError i KeyError: Path.home() bez katalogu domowego
        print(f"praca_w_tle: plik sesji niedostępny: {error!r}", file=sys.stderr)


def _passed(event: object) -> dict[str, str]:
    try:
        path = _session_file(event)
        return {} if path is None else passed_in(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RuntimeError, KeyError) as error:  # ValueError: plik sesji nie w UTF-8
        print(f"praca_w_tle: plik sesji nieczytelny: {error!r}", file=sys.stderr)
        return {}


def _log(event: object, decision: str, details: list[str]) -> None:
    fields = event if isinstance(event, dict) else {}
    row = {
        "czas": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decyzja": decision,
        "szczegoly": details,
        "session_id": fields.get("session_id"),
        "prompt_id": fields.get("prompt_id"),
        "cwd": fields.get("cwd"),
        "stop_hook_active": fields.get("stop_hook_active"),
    }
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (OSError, RuntimeError, KeyError) as error:  # RuntimeError i KeyError: Path.home() bez katalogu domowego
        print(f"praca_w_tle: dziennik ~/{LOG.as_posix()} niedostępny: {error!r}", file=sys.stderr)


def main() -> int:
    try:
        event: object = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, RecursionError) as error:  # także UnicodeDecodeError i JSON głębszy niż stos Pythona
        _log(None, "przepuszczam", [f"nieczytelne wejście: {type(error).__name__}"])
        return 0
    if isinstance(event, dict) and event.get("hook_event_name") == "PostToolUse":
        _remember(event)
        return 0
    alive, notes = judge(event, _passed(event))
    if alive:
        _log(event, "odmowa", [described for _, described in alive] + notes)
        # json.dumps zapisuje polskie litery jako ``ł``, bo konsola Windows nie zapisze ich w swoim kodowaniu.
        print(json.dumps({"decision": "block", "reason": refusal(alive)}))
    elif notes:
        _log(event, "przepuszczam", notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
