#!/usr/bin/env python3
"""Hook ``Stop`` Claude Code: agent nie kończy tury, dopóki w tle jego sesji biegnie polecenie Basha albo jego Monitor.

Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: wywołujący (rodzic, T3, ``claude -p``)
dostaje odpowiedź bez wyniku, a agent stoi. W nocy 4/5.11.2026 tak stanęło pięciu delegatów T3 („czekam na
powiadomienie o procesie w tle”) i za każdym razem było to polecenie Basha z ``run_in_background``; zakaz w briefie nie
pomógł.

Claude Code (2.1.318, ``claude -p`` w ``tools/wyrocznia_pracy_w_tle.py``) podaje hookowi ``Stop`` listę
``background_tasks`` z zadaniami sesji w statusie ``running`` albo ``pending`` (skończone z niej znikają), każde z
``id``, ``type`` i ``status``. Typ ``shell`` mają zadania ``local_bash``: polecenie Basha z ``run_in_background`` i
Monitor agenta (narzędzie Monitor tworzy ``local_bash`` z ``kind`` ``monitor``). Hook odmawia (JSON
``{"decision": "block", "reason": …}`` na stdout, kod 0; ``reason`` trafia do agenta jako polecenie dalszej pracy),
gdy na liście jest zadanie typu ``BLOCKING`` o statusie z ``ALIVE``. Odmawia także przy ``stop_hook_active``: Claude
Code ustawia je po pierwszej odmowie do końca tury, także po wywołaniach narzędzi, więc przepuszczenie przy nim oddałoby
turę z pracą w tle już przy drugiej próbie. Pętlę bez końca ucina sam Claude Code: po ośmiu odmowach z rzędu bez
wywołania narzędzia kończy turę z ostrzeżeniem (``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``), a wywołanie narzędzia zeruje ten
licznik.

Typ ``monitor`` hook przepuszcza i zapisuje w dzienniku (``UNSURE``): mają go ``monitor_mcp`` (monitor serwera MCP) i
``monitor_ws``, a ``monitor_ws`` to także obserwacja artefaktu, którą Claude Code włącza sam po jego publikacji i która
trwa do końca sesji. Claude Code pomija ją w swoich listach po polu ``ambient``, ale hookowi go nie podaje: rekord
obserwacji ma tylko ``id``, ``type``, ``status`` i ``description``, jak każdy ``monitor_ws``, więc żadne pole nie
odróżnia go od monitora, który agent uruchomił sam (binarka 2.1.318, budowa ``background_tasks``).

Wszystko inne przechodzi (kod 0, nic na stdout), bo fałszywa odmowa zatrzymałaby każdego agenta projektu: pusta lista,
znane typy, które same raportują wywołującemu (``REPORTING``: podagent, workflow, sesja w chmurze i inne), zaplanowane
wybudzenia (``session_crons``), a także wątpliwość: wejście nieczytelne albo bez listy ``background_tasks``, wpis
listy, który nie jest obiektem, ``type`` albo ``status``, które nie są tekstem, typ spoza ``BLOCKING`` i ``REPORTING``,
typ ``monitor`` i zadanie ``shell`` o statusie spoza ``ALIVE``. Wątpliwość i każdą odmowę hook dopisuje do dziennika
``~/.cache/maximiseart/praca_w_tle.jsonl`` (``LOG``, inny plik daje zmienna ``LOG_ENV``, której używa wyrocznia);
błąd zapisu dziennika trafia na stderr i nie zmienia decyzji. Hook po ``timeout`` z ustawień Claude Code zabija bez
decyzji i tura się kończy (próba 5.11.2026 na 2.1.318), więc hook czyta listę w czasie liniowym.

Granica: inne harnessy niż Claude Code (Codex, opencode) i podagent narzędzia Agent łapie tylko przegląd. Hook nie
jest wpięty w ``SubagentStop``, bo tam lista należy do całej sesji, a nie do podagenta. Monitor wtyczki (``monitors``
w manifeście wtyczki, uruchamiany bez prośby agenta) to też ``local_bash`` z ``kind`` ``monitor``, więc hook
odmówiłby przy nim jak przy Bashu; żadna wtyczka na Macu Maksa go nie deklaruje (5.11.2026).
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

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
REFUSAL = "Odmowa końca tury: w tle sesji biegnie jeszcze"


def judge(event: object) -> tuple[list[str], list[str]]:
    """Opisy żywych zadań ``BLOCKING`` i wątpliwości z wejścia hooka ``Stop``; odmowa tylko przy żywych zadaniach."""

    tasks = event.get("background_tasks") if isinstance(event, dict) else None
    if not isinstance(tasks, list):
        return [], ["wejście bez listy background_tasks"]
    alive, doubts = [], []
    for task in tasks:
        if not isinstance(task, dict):
            doubts.append(f"wpis listy zadań nie jest obiektem: {type(task).__name__}")
            continue
        kind, status, name = task.get("type"), task.get("status"), task.get("id")
        if not isinstance(kind, str) or not isinstance(status, str):
            doubts.append(f"zadanie {name} z type {kind!r} i status {status!r}, z których nie każde jest tekstem")
        elif kind == BLOCKING and status in ALIVE:
            alive.append(f"{kind} {name} „{task.get('command') or task.get('description')}”")
        elif kind == BLOCKING:
            doubts.append(f"{kind} {name} o nieznanym statusie {status!r}")
        elif kind == UNSURE:
            doubts.append(
                f"{kind} {name} „{task.get('description')}” ({status}) przepuszczony: typ monitor ma też obserwacja "
                "artefaktu, której Claude Code nie odróżnia w wejściu hooka"
            )
        elif kind not in REPORTING:
            doubts.append(f"{kind} {name} ({status}) przepuszczony: nieznany typ zadania")
    return alive, doubts


def refusal(tasks: list[str]) -> str:
    return (
        f"{REFUSAL} {'; '.join(tasks)}. Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: "
        "wywołujący (rodzic, T3, claude -p) dostaje odpowiedź bez niego, a powiadomienie o końcu zadania może nie "
        "obudzić agenta. Nie kończ tury słowami „czekam na powiadomienie”. Poczekaj na koniec zadania na pierwszym "
        "planie (w T3 t3_background_wait z jego ID) i zapisz wynik, albo zatrzymaj je (TaskStop z jego ID), uruchom tę "
        "pracę Bashem bez run_in_background (timeout do 600000 ms, dłuższą dziel na części) i zapisz wynik. Monitor "
        "to też zadanie w tle, a samo sleep nie jest pracą: na pierwszym planie sprawdzaj stan, na który czekasz. Proces, "
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
        path = Path(os.environ.get(LOG_ENV) or Path.home() / LOG)
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
