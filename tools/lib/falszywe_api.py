"""Claude Code wyroczni hooka, który może pytać tylko lokalne fałszywe Messages API, nigdy prawdziwego modelu.

Wyrocznie hooków (``tools/wyrocznia_zgody.py``, ``tools/wyrocznia_pracy_w_tle.py``) uruchamiają prawdziwe ``claude``,
a model udaje fałszywe API na ``127.0.0.1``. ``claude`` to jedyna droga takiego uruchomienia, a jego zabezpieczenia
są tu, bo 5.11.2026 ``claude -p`` z adresem fałszywego API tylko w środowisku procesu zapytał prawdziwy model przez hub
(``env.ANTHROPIC_BASE_URL`` w ``~/.claude/settings.json`` wygrywa ze środowiskiem), a ten model uruchamiał wyrocznię
dalej, aż do ok. 100 sesji:

- ``--setting-sources project,local``: Claude Code nie czyta ustawień użytkownika (adres huba, ``apiKeyHelper``);
- adres fałszywego API, puste gniazdo API (``SOCKET``) i wyłączone przełączniki innych dostawców (``PROVIDERS``:
  Bedrock, Vertex, Foundry i inne z Claude Code 2.1.318) w ``--settings``, które wygrywają z ``env`` ustawień projektu
  i lokalnych checkoutu;
- środowisko ``claude`` z listy dozwolonej (``_INHERITED``), zmiennych, które wyrocznia podaje jawnie w ``env``, i
  zmiennych tego modułu: ze środowiska procesu wyroczni nie dochodzi nic innego (adres API, gniazdo
  ``ANTHROPIC_UNIX_SOCKET``, pośrednik ``HTTPS_PROXY``, przełącznik dostawcy, token huba, zmienne sesji Claude Code),
  także ustawione przez ``os.environb`` albo zmienne, których dzisiejszy Claude Code jeszcze nie zna;
- ``NESTED`` w środowisku ``claude``: ``claude`` w Claude Code uruchomionym przez wyrocznię odmawia (``Nested``),
  a wyrocznia pyta ``nested`` na starcie, żeby odmówić słowami;
- ``claude``, które przez ``contact_s`` nie zapyta fałszywego API, pyta inny model, więc ginie od razu.

Granica: managed settings (``/Library/Application Support/ClaudeCode/managed-settings.json`` na macOS,
``/etc/claude-code/managed-settings.json`` na Linuksie, polityka MDM) wygrywają z ``--settings``, więc ich ``env`` albo
``apiKeyHelper`` przekierowałyby ``claude`` mimo tych zabezpieczeń; na Macu Maksa ich nie ma (5.11.2026).
Nowy przełącznik dostawcy albo gniazdo z późniejszego Claude Code, których ``--settings`` nie zeruje, ustawione w
``env`` projektu albo ``.claude/settings.local.json``, też by go przekierowały, bo lista dozwolona chroni tylko przed
środowiskiem procesu wyroczni. Przed jednym i drugim
chroni wtedy już tylko ``contact_s``: takie ``claude`` ginie po ``contact_s`` sekundach, ale jedno zapytanie do innego
modelu mogło już pójść.

Model to ``MODEL`` (reguła zespołu: tylko Opus); fałszywe API go nie uruchamia, a odpowiedź podaje jego nazwę.

    import falszywe_api

    if falszywe_api.claude_code(ROOT, len(cases)) is None:
        return 2
    ran = falszywe_api.claude(["-p", "…"], answer=lambda body: falszywe_api.stream(block), cwd=ROOT, env={}, timeout=60, stop=stop)
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import potomne

MODEL = "claude-opus-5-5"
CONTACT_S = 30.0
NESTED = "MAXIMISEART_WYROCZNIA_W_SRODKU"
_API_KEY = "sk-ant-wyrocznia"
# Jedyne zmienne środowiska procesu wyroczni, które dostaje ``claude``; wyrocznie biegną tylko na macOS i Linuksie.
_INHERITED = (
    "PATH",  # ``claude``, ``python3`` hooka i polecenia narzędzia Bash
    "HOME",  # ``~/.claude.json`` i ``~/.claude`` Claude Code, piaskownica wyroczni zgody w ``~/.cache``
    "TMPDIR",  # katalog tymczasowy użytkownika na macOS, w którym Claude Code i polecenia zapisują pliki
    "USER",  # nazwa użytkownika, którą czytają Claude Code i polecenia
    "LOGNAME",  # to samo pod nazwą POSIX
    "SHELL",  # powłoka narzędzia Bash Claude Code
    "LANG",  # kodowanie tekstu poleceń i ich wyniku (polskie litery)
    "LC_ALL",  # jw., gdy ustawione zamiast LANG
    "LC_CTYPE",  # jw.
)
# Przełączniki dostawców innych niż Messages API spod ``ANTHROPIC_BASE_URL`` w Claude Code 2.1.318; włącza je tylko
# wartość 1, true, yes albo on, więc ``"0"`` w ``--settings`` wyłącza każdy, także ustawiony w ``env`` projektu.
PROVIDERS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_GATEWAY",
)
# Niepuste gniazdo API wygrywa z ``ANTHROPIC_BASE_URL`` w Claude Code 2.1.318, a pusty tekst je wyłącza.
SOCKET = "ANTHROPIC_UNIX_SOCKET"


class Nested(RuntimeError):
    """``claude`` wołane w Claude Code, które uruchomiła wyrocznia: kolejne uruchomienie dałoby łańcuch sesji."""


@dataclass(frozen=True)
class Ran:
    # Kod wyjścia ``claude``, które skończyło się samo, albo ``None``, gdy zginęło po ``stop``, limicie albo bez kontaktu.
    returncode: int | None
    # Czy fałszywe API dostało choć jedno zapytanie.
    contacted: bool


def nested() -> str | None:
    """Powód odmowy, gdy wyrocznia biegnie w Claude Code, które uruchomiła wyrocznia; inaczej ``None``."""

    return f"uruchomiona w Claude Code wyroczni ({NESTED})" if os.environ.get(NESTED) else None


def claude_code(root: Path, cases: int) -> str | None:
    """Wersja Claude Code wyroczni po linii z nią i liczbą przypadków; ``None`` po linii ``WYROCZNIA BRAK``, gdy
    wyrocznia biegnie w Claude Code wyroczni albo nie ma ``claude`` na PATH na macOS albo Linuksie."""

    reason = nested()
    if reason is None and (sys.platform == "win32" or shutil.which("claude") is None):
        reason = "potrzebny claude na PATH na macOS albo Linuksie"
    if reason is not None:
        print(f"WYROCZNIA BRAK | {reason}")
        return None
    version = potomne.run(["claude", "--version"], cwd=root, timeout=60).stdout.strip()
    print(f"Claude Code {version}, przypadki {cases}", flush=True)
    return version


def contact_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kontakt-s",
        type=float,
        default=CONTACT_S,
        help=f"Po ilu sekundach bez zapytania do fałszywego API wyrocznia kończy Claude Code (domyślnie {CONTACT_S:g} s).",
    )


def tool_result(message: object) -> str | None:
    """Tekst pierwszego wyniku narzędzia w wiadomości zapytania API albo ``None``, gdy wiadomość go nie ma."""

    content = message.get("content") if isinstance(message, dict) else None
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "tool_result":
            inner = part.get("content")
            return inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
    return None


def claude(
    arguments: Sequence[str],
    *,
    answer: Callable[[dict[str, object]], bytes],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    stop: threading.Event,
    contact_s: float = CONTACT_S,
    stdin: Path | None = None,
) -> Ran:
    """Jedno ``claude`` z ``arguments`` wobec fałszywego API aż do jego końca, ``stop``, ``timeout`` albo braku kontaktu.

    ``answer`` dostaje JSON każdego zapytania i zwraca strumień odpowiedzi (``stream``). Środowisko ``claude`` to
    zmienne ``_INHERITED`` procesu wyroczni, zmienne wyroczni z ``env`` i zmienne tego modułu, które wygrywają z ``env``. ``stdin`` to plik (potok nazwany), z którego ``claude`` czyta wejście; bez niego
    wejście jest puste. Gdy fałszywe API nie dostanie zapytania przez ``contact_s``, ``claude`` ginie, a ``stop`` jest
    ustawione. W Claude Code, które uruchomiła wyrocznia, ``claude`` niczego nie uruchamia i rzuca ``Nested``.
    """

    reason = nested()
    if reason:
        raise Nested(reason)
    contacted = threading.Event()

    class Api(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            contacted.set()
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
            data = answer(body if isinstance(body, dict) else {})
            try:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass  # wyrocznia zabiła ``claude`` po odpowiedzi, której już nie odczytało

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def watchdog() -> None:
        if not contacted.wait(contact_s):
            stop.set()

    threading.Thread(target=watchdog, daemon=True).start()
    command = _command(arguments, server.server_address[1])
    if stdin is not None:
        command = ["/bin/sh", "-c", 'exec "$@" <"$0"', str(stdin), *command]
    returncode: int | None = None
    try:
        returncode = potomne.run(command, cwd=cwd, env=_environment(server.server_address[1], env), timeout=timeout, stop=stop).returncode
    except (potomne.Stopped, subprocess.TimeoutExpired):
        pass
    finally:
        reached = contacted.is_set()
        contacted.set()
        server.shutdown()
        server.server_close()
    return Ran(returncode, reached)


def _base(port: int) -> dict[str, str]:
    return {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}"}


def _command(arguments: Sequence[str], port: int) -> list[str]:
    return [
        "claude",
        *arguments,
        "--setting-sources",
        "project,local",
        "--settings",
        json.dumps({"env": {**_base(port), SOCKET: "", **dict.fromkeys(PROVIDERS, "0")}}),
        "--model",
        MODEL,
    ]


def _environment(port: int, extra: Mapping[str, str]) -> dict[str, str]:
    kept = {name: os.environ[name] for name in _INHERITED if name in os.environ}
    return {**kept, **extra, **_base(port), "ANTHROPIC_API_KEY": _API_KEY, NESTED: "1"}


def stream(block: dict[str, object]) -> bytes:
    """Strumień odpowiedzi API z jednym blokiem: ``tool_use`` kończy się ``stop_reason`` ``tool_use``, tekst ``end_turn``."""

    tool = block["type"] == "tool_use"
    message: dict[str, object] = {
        "id": "msg_wyrocznia",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
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
