"""Uruchamia claude -p z pracą w tle i bez niej, by sprawdzić hook Stop praca_w_tle.py; uruchom po każdej aktualizacji Claude Code.

Wyrocznia hooka ``tools/hooks/praca_w_tle.py``: hook działa, dopóki Claude Code uruchamia hooki ``Stop`` z listą
``background_tasks`` i słucha ich odmowy, więc po aktualizacji Claude Code ta wyrocznia uruchamia ``claude -p`` w trybie
bypass (jak T3) w katalogu tego checkoutu, czyli z jego ``.claude/settings.json``. Modelu nie ma: lokalne fałszywe API
(``ANTHROPIC_BASE_URL``) każe wywołać Basha z poleceniem przypadku, a po jego wyniku kończy turę słowami agentów z nocy
4/5.11.2026 („Czekam na powiadomienie o procesie w tle.”), także po każdej odmowie hooka.

Przypadki (``CASES``): ``praca-w-tle`` uruchamia ``sleep 60`` z ``run_in_background``, a ``ZGODNE`` znaczy, że hook
odmówił końca tury dwa razy, drugi raz przy ``stop_hook_active``; wtedy wyrocznia kończy Claude Code, a ``sleep 60``,
które Claude Code uruchamia poza swoją grupą procesów, kończy się samo. ``bez-pracy-w-tle`` uruchamia ``true`` na pierwszym planie, a ``ZGODNE`` znaczy, że Claude Code sam
skończył turę bez odmowy. Inny wynik to ``ZMIANA`` z opisem. Ostatnia linia to ``WYROCZNIA OK | …`` (kod 0) tylko
wtedy, gdy każdy przypadek jest ``ZGODNE``; inaczej ``WYROCZNIA ZMIANA | …`` (kod 1). Bez ``claude`` na PATH albo na
Windows kończy się kodem 2, tak samo wyrocznia uruchomiona w Claude Code, którego sama uruchomiła (``NESTED``). Claude
Code, który przez ``--kontakt-s`` sekund nie zapyta fałszywego API, wyrocznia kończy (``ZMIANA``), bo pyta wtedy prawdziwy model.

    .venv/bin/python tools/wyrocznia_pracy_w_tle.py               # oba przypadki, ok. 5 s
    .venv/bin/python tools/wyrocznia_pracy_w_tle.py praca-w-tle   # wybrany przypadek
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hooks"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import potomne
import praca_w_tle

ROOT = Path(__file__).resolve().parents[1]
MARKER = "WYROCZNIA-PRACY-W-TLE"
WAITING = "Czekam na powiadomienie o procesie w tle."
LIMIT_S = 120.0
CONTACT_S = 30.0
# Zmienna, którą wyrocznia daje Claude Code: wyrocznia uruchomiona w nim odmawia, zamiast uruchamiać kolejne claude.
NESTED = "WYROCZNIA_PRACY_W_TLE_W_SRODKU"


@dataclass(frozen=True)
class Case:
    name: str
    bash: dict[str, object]
    # Ile odmów hooka znaczy ZGODNE: 2 (druga przy stop_hook_active) przy pracy w tle, 0 bez niej.
    refusals: int


CASES = (
    Case("praca-w-tle", {"command": "sleep 60", "run_in_background": True, "description": "Sen 60 s w tle"}, 2),
    Case("bez-pracy-w-tle", {"command": "true", "description": "Polecenie na pierwszym planie"}, 0),
)


@dataclass(frozen=True)
class Outcome:
    refusals: int
    tool_result: bool
    # Kod wyjścia Claude Code, który skończył się sam, albo ``None``, gdy zakończyła go wyrocznia albo limit czasu.
    returncode: int | None
    # Czy fałszywe API dostało zapytanie przypadku (z ``MARKER``).
    asked: bool


class _Api(http.server.BaseHTTPRequestHandler):
    """Fałszywe Messages API przypadku: Bash, po jego wyniku koniec tury, po drugiej odmowie hooka ``stop``."""

    case = CASES[0]
    lock = threading.Lock()
    refusals = 0
    tool_result = False
    asked = False
    stop = threading.Event()
    contacted = threading.Event()

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        messages = body.get("messages") if isinstance(body, dict) else None
        stream = answer(type(self), messages if isinstance(messages, list) else [])
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(stream)))
        self.end_headers()
        self.wfile.write(stream)


def answer(api: type[_Api], messages: list[object]) -> bytes:
    """Odpowiedź API na zapytanie z ``messages``; liczy odmowy hooka i zapamiętuje wynik Basha w stanie ``api``."""

    api.contacted.set()
    texts = [_texts(message) for message in messages]
    if not texts or MARKER not in "".join(texts[0]):
        return reply({"type": "text", "text": "ok"})  # zapytanie poboczne Claude Code (tytuł, podsumowanie)
    api.asked = True
    refusals = sum(any(praca_w_tle.REFUSAL in text for text in message) for message in texts)
    with api.lock:
        if api.stop.is_set():  # Claude Code przed końcem pyta jeszcze raz; wynik przypadku już jest
            return reply({"type": "text", "text": WAITING})
        api.refusals = max(api.refusals, refusals)
        api.tool_result = api.tool_result or any(_has_tool_result(message) for message in messages)
        if refusals >= 2:
            api.stop.set()
        if api.tool_result:
            return reply({"type": "text", "text": WAITING})
    return reply({"type": "tool_use", "id": "toolu_wyrocznia", "name": "Bash", "input": api.case.bash})


def _texts(message: object) -> list[str]:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content]
    found = []
    for part in content if isinstance(content, list) else []:
        inner = part.get("text", part.get("content")) if isinstance(part, dict) else None
        found.extend(
            _texts({"content": inner}) if isinstance(inner, list) else [inner] if isinstance(inner, str) else []
        )
    return found


def _has_tool_result(message: object) -> bool:
    content = message.get("content") if isinstance(message, dict) else None
    return any(isinstance(part, dict) and part.get("type") == "tool_result" for part in content or [])


def reply(block: dict[str, object]) -> bytes:
    """Strumień odpowiedzi API z jednym blokiem: ``tool_use`` kończy się ``stop_reason`` ``tool_use``, tekst ``end_turn``."""

    tool = block["type"] == "tool_use"
    message: dict[str, object] = {
        "id": "msg_wyrocznia",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    start: dict[str, object]
    delta: dict[str, object]
    if tool:
        start = {**block, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
    else:
        start = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": block["text"]}
    events = [
        ("message_start", {"type": "message_start", "message": message}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": start}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def environment(port: int) -> dict[str, str]:
    """Środowisko ``claude``: bez zmiennych sesji Claude Code, w której biegnie wyrocznia, z fałszywym API i ``NESTED``."""

    kept = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CLAUDE_CODE_") and name not in ("CLAUDECODE", "ANTHROPIC_AUTH_TOKEN")
    }
    return {**kept, **_fake_api(port), "ANTHROPIC_API_KEY": "sk-ant-wyrocznia-pracy-w-tle", NESTED: "1"}


def _fake_api(port: int) -> dict[str, str]:
    return {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}"}


def command_line(case: Case, port: int) -> list[str]:
    """``claude -p`` przypadku: ustawienia tylko projektu i adres fałszywego API także w ``--settings``.

    ``env`` z ustawień użytkownika (na Macu Maksa ``ANTHROPIC_BASE_URL`` huba) wygrywa ze środowiskiem procesu, więc bez
    ``--setting-sources project,local`` i ``--settings`` Claude Code pytał prawdziwy model (5.11.2026).
    """

    return [
        "claude",
        "-p",
        f"{MARKER} {case.name}: uruchom polecenie.",
        "--setting-sources",
        "project,local",
        "--settings",
        json.dumps({"env": _fake_api(port)}),
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--allow-dangerously-skip-permissions",
        "--model",
        "claude-haiku-5-5",
        "--max-turns",
        "10",
    ]


def ask(case: Case, port: int, limit_s: float, contact_s: float = CONTACT_S) -> Outcome:
    """Jedno ``claude -p`` przypadku aż do jego końca, drugiej odmowy hooka albo ``limit_s``."""

    _Api.case, _Api.refusals, _Api.tool_result, _Api.asked = case, 0, False, False
    _Api.stop.clear()
    _Api.contacted.clear()

    def watchdog() -> None:
        # Claude Code, który nie pyta fałszywego API, pyta inny model: wyrocznia kończy go od razu.
        if not _Api.contacted.wait(contact_s):
            _Api.stop.set()

    threading.Thread(target=watchdog, daemon=True).start()
    returncode: int | None = None
    try:
        returncode = potomne.run(
            command_line(case, port), cwd=ROOT, env=environment(port), timeout=limit_s, stop=_Api.stop
        ).returncode
    except (potomne.Stopped, subprocess.TimeoutExpired):
        pass
    finally:
        _Api.contacted.set()
    return Outcome(_Api.refusals, _Api.tool_result, returncode, _Api.asked)


def verdict(case: Case, got: Outcome) -> tuple[str, str]:
    """``ZGODNE`` albo ``ZMIANA`` przypadku i opis tego, co zrobił Claude Code."""

    if not got.asked:
        seen = "Claude Code nie zapytał fałszywego API"
    elif not got.tool_result:
        seen = "Bash nie oddał wyniku"
    elif got.refusals:
        seen = f"odmowy hooka: {got.refusals}"
    else:
        seen = f"koniec tury bez odmowy (kod {got.returncode})"
    expected = got.tool_result and (got.refusals >= 2 if case.refusals else got.refusals == 0 and got.returncode == 0)
    return ("ZGODNE" if expected else "ZMIANA"), seen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "nazwy", nargs="*", help=f"Nazwy przypadków ({', '.join(case.name for case in CASES)}); bez nich wszystkie."
    )
    parser.add_argument(
        "--limit-s", type=float, default=LIMIT_S, help=f"Limit jednego przypadku (domyślnie {LIMIT_S:g} s)."
    )
    parser.add_argument(
        "--kontakt-s",
        type=float,
        default=CONTACT_S,
        help=f"Po ilu sekundach bez zapytania do fałszywego API wyrocznia kończy Claude Code (domyślnie {CONTACT_S:g} s).",
    )
    args = parser.parse_args(argv)
    chosen = [case for case in CASES if not args.nazwy or case.name in args.nazwy]
    if os.environ.get(NESTED):
        print(f"WYROCZNIA BRAK | uruchomiona w Claude Code samej wyroczni ({NESTED})")
        return 2
    if sys.platform == "win32" or shutil.which("claude") is None:
        print("WYROCZNIA BRAK | potrzebny claude na PATH na macOS albo Linuksie")
        return 2
    version = potomne.run(["claude", "--version"], cwd=ROOT, timeout=60).stdout.strip()
    print(f"Claude Code {version}, przypadki {len(chosen)}", flush=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    counts: dict[str, int] = {}
    try:
        for case in chosen:
            result, seen = verdict(case, ask(case, server.server_address[1], args.limit_s, args.kontakt_s))
            counts[result] = counts.get(result, 0) + 1
            print(f"{result} {case.name} | {seen}", flush=True)
    finally:
        server.shutdown()
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    failed = bool(counts.get("ZMIANA")) or not chosen
    print(f"WYROCZNIA {'ZMIANA' if failed else 'OK'} | Claude Code {version} | {summary or 'brak przypadków'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
