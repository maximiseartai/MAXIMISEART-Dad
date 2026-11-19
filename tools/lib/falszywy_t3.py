"""Fałszywy serwer MCP ``t3-code`` wyroczni ``tools/wyrocznia_pracy_w_tle.py`` z jednym narzędziem ``t3_background_wait``.

Claude Code uruchamia go z ``--mcp-config`` (``config``) jako proces, który czyta JSON-RPC liniami ze stdin i odpowiada
liniami na stdout. Narzędzie przyjmuje ``taskIds`` i ``waiting`` jak ``t3_background_wait`` T3 i odpowiada tak jak T3
dla zadań, które zna (``{"matched": taskIds, "unmatched": []}``). Niczego nie trzyma i nikogo nie budzi: wyrocznia
sprawdza hooki ``tools/hooks/praca_w_tle.py`` i to, że Claude Code sam budzi sesję po końcu zadania, a nie T3.
Używa tylko biblioteki standardowej.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

NAME = "t3-code"
TOOL = "t3_background_wait"
# Nazwa narzędzia w Claude Code: ``mcp__<serwer>__<narzędzie>``.
CALLED = f"mcp__{NAME}__{TOOL}"
SCHEMA = {
    "type": "object",
    "properties": {"taskIds": {"type": "array", "items": {"type": "string"}}, "waiting": {"type": "boolean"}},
    "required": ["taskIds"],
}


def config() -> str:
    """Wartość ``--mcp-config`` Claude Code z tym serwerem uruchomionym przez Pythona, który uruchomił wyrocznię."""

    return json.dumps({"mcpServers": {NAME: {"command": sys.executable, "args": [str(Path(__file__).resolve())]}}})


def reply(message: object) -> dict[str, object] | None:
    """Odpowiedź JSON-RPC na ``message`` albo ``None`` dla powiadomienia (wiadomości bez ``id``)."""

    if not isinstance(message, dict) or "id" not in message:
        return None
    method, params = message.get("method"), message.get("params")
    given = params if isinstance(params, dict) else {}
    result: dict[str, object]
    if method == "initialize":
        version = given.get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": NAME, "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": TOOL, "description": "Keep this thread in Working while background work runs.", "inputSchema": SCHEMA}]}
    elif method == "tools/call":
        arguments = given.get("arguments")
        ids = arguments.get("taskIds") if isinstance(arguments, dict) else None
        matched = [name for name in ids if isinstance(name, str)] if isinstance(ids, list) else []
        result = {"content": [{"type": "text", "text": json.dumps({"matched": matched, "unmatched": []})}]}
    else:
        result = {}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def main() -> int:
    for line in sys.stdin:
        try:
            answer = reply(json.loads(line))
        except ValueError:
            continue
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
