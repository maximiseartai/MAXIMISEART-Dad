#!/usr/bin/env python3
"""Hook ``Stop`` Claude Code: agent nie kończy tury, dopóki w tle jego sesji biegnie polecenie Basha albo Monitor.

Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: wywołujący (rodzic, T3, ``claude -p``)
dostaje odpowiedź bez wyniku, a agent stoi. W nocy 4/5.11.2026 tak stanęło pięciu delegatów T3 („czekam na
powiadomienie o procesie w tle”), a zakaz w briefie nie pomógł.

Claude Code (2.1.318, ``claude -p`` w ``tools/wyrocznia_pracy_w_tle.py``) podaje hookowi ``Stop`` listę
``background_tasks`` z zadaniami sesji w statusie ``running`` albo ``pending`` (skończone z niej znikają), każde z
``id``, ``type`` i ``status``. Polecenie Basha z ``run_in_background`` i Monitor mają ``type`` ``shell``, a Monitor MCP
``monitor``. Hook odmawia (JSON ``{"decision": "block", "reason": …}`` na stdout, kod 0; ``reason`` trafia do agenta
jako polecenie dalszej pracy), gdy na liście jest zadanie typu z ``TYPES`` o statusie z ``ALIVE``. Odmawia także przy
``stop_hook_active``: Claude Code ustawia je po pierwszej odmowie do końca tury, także po wywołaniach narzędzi, więc
przepuszczenie przy nim oddałoby turę z pracą w tle już przy drugiej próbie. Pętlę bez końca ucina sam Claude Code:
po ośmiu odmowach z rzędu bez wywołania narzędzia kończy turę z ostrzeżeniem (``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``),
a wywołanie narzędzia zeruje ten licznik.

Wszystko inne przechodzi (kod 0, nic na stdout), bo fałszywa odmowa zatrzymałaby każdego agenta projektu: pusta lista,
inne typy zadań (podagent, workflow, sesja w chmurze, które same raportują wywołującemu), zaplanowane wybudzenia
(``session_crons``), a także wątpliwość: wejście nieczytelne albo bez listy ``background_tasks``, wpis listy, który
nie jest obiektem, i zadanie ``shell`` albo ``monitor`` o statusie spoza ``ALIVE``. Wątpliwość i każdą odmowę hook
dopisuje do dziennika ``~/.cache/maximiseart/praca_w_tle.jsonl`` (``LOG``); błąd zapisu dziennika trafia na stderr
i nie zmienia decyzji. Hook po ``timeout`` z ustawień Claude Code zabija bez decyzji i tura się kończy (próba
5.11.2026 na 2.1.318), więc hook czyta listę w czasie liniowym.

Granica: inne harnessy niż Claude Code (Codex, opencode) i podagent narzędzia Agent łapie tylko przegląd. Hook nie
jest wpięty w ``SubagentStop``, bo tam lista należy do całej sesji, a nie do podagenta.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

TYPES = frozenset({"shell", "monitor"})
ALIVE = frozenset({"running", "pending"})
LOG = Path(".cache") / "maximiseart" / "praca_w_tle.jsonl"
REFUSAL = "Odmowa końca tury: w tle sesji biegnie jeszcze"


def judge(event: object) -> tuple[list[str], list[str]]:
    """Opisy żywych zadań z ``TYPES`` i wątpliwości z wejścia hooka ``Stop``; odmowa tylko przy żywych zadaniach."""

    tasks = event.get("background_tasks") if isinstance(event, dict) else None
    if not isinstance(tasks, list):
        return [], ["wejście bez listy background_tasks"]
    alive, doubts = [], []
    for task in tasks:
        if not isinstance(task, dict):
            doubts.append(f"wpis listy zadań nie jest obiektem: {type(task).__name__}")
        elif task.get("type") in TYPES and task.get("status") in ALIVE:
            alive.append(f"{task['type']} {task.get('id')} „{task.get('command') or task.get('description')}”")
        elif task.get("type") in TYPES:
            doubts.append(f"{task['type']} {task.get('id')} o nieznanym statusie {task.get('status')!r}")
    return alive, doubts


def refusal(tasks: list[str]) -> str:
    return (
        f"{REFUSAL} {'; '.join(tasks)}. Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: "
        "wywołujący (rodzic, T3, claude -p) dostaje odpowiedź bez niego, a powiadomienie o końcu zadania może nie "
        "obudzić agenta. Nie kończ tury słowami „czekam na powiadomienie”. Poczekaj na koniec zadania na pierwszym "
        "planie (w T3 t3_background_wait z jego ID) i zapisz wynik, albo zatrzymaj je (TaskStop z jego ID), uruchom tę "
        "pracę Bashem bez run_in_background (timeout do 600000 ms, dłuższą dziel na części) i zapisz wynik. Proces, "
        "który ma żyć po turze, bo prosi o to człowiek (serwer), zatrzymaj jako zadanie i uruchom odłączony "
        "(nohup … & w Bashu na pierwszym planie)."
    )


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
        path = Path.home() / LOG
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
    alive, doubts = judge(event)
    if alive:
        _log(event, "odmowa", alive + doubts)
        # json.dumps zapisuje polskie litery jako ``\u0142``, bo konsola Windows nie zapisze ich w swoim kodowaniu.
        print(json.dumps({"decision": "block", "reason": refusal(alive)}))
    elif doubts:
        _log(event, "przepuszczam", doubts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
