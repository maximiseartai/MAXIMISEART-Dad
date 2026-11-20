#!/usr/bin/env python3
"""Hook ``PermissionRequest`` Claude Code dla Basha: w trybie bypass odmawia od razu, zamiast czekać na zgodę człowieka.

Claude Code 2.1.309–2.1.310 w trybie ``bypassPermissions`` (tak T3 uruchamia agentów) pyta człowieka o zgodę na
polecenie Basha w dwóch przypadkach: przy kontroli bezpieczeństwa, której nie zdejmuje reguła ``permissions.allow``
(we wszystkich znanych przypadkach to ``rm``, którego celu Claude Code nie umie ustalić z tekstu polecenia), i przy
poleceniu, które pasuje do reguły ``permissions.ask`` z ustawień. Agent w tle stał wtedy bez słowa: 24.10 do 66 min,
26.10 do 104 min. Claude Code uruchamia ten hook razem z pytaniem do hosta, a po odmowie z hooka w ciągu ok. 0,1 s
wysyła hostowi ``control_cancel_request`` i oddaje agentowi poprawkę, więc agent działa dalej. Odmowę dostaje każde
takie pytanie, także z reguły ``ask``: wejście hooka nie mówi, która kontrola pyta (pytanie z reguły ``ask`` różni
się od pytania o ``rm`` tylko brakiem pola ``permission_suggestions``), więc poprawka jest ogólna, a ``rm`` to w niej
przykład. Kiedy pytać, rozstrzyga sama kontrola Claude Code i reguły ustawień, a hook ich nie odtwarza. W innym
trybie (sesja człowieka w ``default``) hook nic nie wypisuje i pytanie idzie do człowieka jak zwykle. Wejście, którego
nie da się odczytać, też, bo hook nie zna wtedy trybu.

Granica: hook działa, dopóki Claude Code uruchamia hooki ``PermissionRequest`` przy pytaniu o zgodę. Po aktualizacji
Claude Code sprawdza to ``tools/wyrocznia_zgody.py``. Kartę zgody, którą T3 pokazuje w wątku, hook nie zamyka:
T3 nie zamyka jej na ``control_cancel_request``, więc zostaje w stanie „waiting” także po końcu tury (26.10 u dziecka
``delegate_task``: jeszcze 3 min po końcu runu, „cancelled” dopiero 30 min po nim). Inne harnessy niż Claude Code
(Codex, opencode) łapie tylko przegląd. Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod
3.9 (``per-file-target-version`` w ``ruff.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

import json
import sys

MESSAGE = (
    "Claude Code zatrzymałby to polecenie Basha na zgodzie człowieka, a agent w trybie bypass nie czeka na zgodę, "
    "więc polecenie nie ruszyło. Gdy to rm, którego celu Claude Code nie ustali z tekstu polecenia, uruchom rm "
    "osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną (rm -rf /abs/katalog/logi) albo ze zmienną w postaci "
    "${VAR:?}, a resztę polecenia w następnym wywołaniu. Kod i dane z rm zapisz do pliku narzędziem Write albo Edit, "
    "a nie w heredocu ani w napisie w poleceniu. Gdy polecenie pasuje do reguły permissions.ask z ustawień, potrzebuje "
    "zgody człowieka: nie obchodź jej innym zapisem, tylko napisz w odpowiedzi, o co prosisz."
)


def decision(event: object) -> dict[str, object] | None:
    if not isinstance(event, dict) or event.get("permission_mode") != "bypassPermissions":
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": MESSAGE},
        }
    }


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read())
    except (ValueError, RecursionError):
        return 0
    answer = decision(event)
    if answer is not None:
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
