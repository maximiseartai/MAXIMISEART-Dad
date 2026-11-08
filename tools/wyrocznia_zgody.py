"""Sprawdza, czy zainstalowany Claude Code oddaje hookowi zgoda.py pytanie o zgodę na rm; uruchom po każdej aktualizacji Claude Code.

Wyrocznia hooka ``tools/hooks/zgoda.py``: czy zainstalowany Claude Code oddaje temu hookowi pytanie o zgodę na ``rm``.

Hook działa, dopóki Claude Code uruchamia hooki ``PermissionRequest`` przy pytaniu o zgodę, więc po aktualizacji
Claude Code ta wyrocznia uruchamia go tak jak T3 (``stream-json`` na wejściu i wyjściu, ``--permission-prompt-tool
stdio``, ``--permission-mode bypassPermissions``), w katalogu tego checkoutu, czyli z jego ``.claude/settings.json``.
Modelu nie ma: lokalne fałszywe API każe wysłać polecenie przypadku z ``tools/wyrocznia_zgody.jsonl`` bajt w
bajt narzędziem Bash i odbiera wynik narzędzia, a wtedy wyrocznia kończy Claude Code. Claude Code uruchamia
``tools/lib/falszywe_api.py`` tak, by mogło pytać tylko fałszywe API, także gdy ``~/.claude/settings.json`` ma
``env.ANTHROPIC_BASE_URL`` huba, a gdy przez ``--kontakt-s`` sekund go nie zapyta, kończy je (``ZMIANA``). Polecenia nie biegną: prefiks powłoki ``tools/wyrocznia_zgody_prefiks.sh`` wykonuje tylko polecenie
równe co do znaku poleceniu hooka zgody z ``.claude/settings.json``.
Host, czyli T3 z człowiekiem, nigdy nie odpowiada na pytanie o zgodę i zamyka wejście po ``--host-s`` sekundach bez
wyniku narzędzia. Ścieżki ``@WS@``, ``@FAR@`` i ``@TFAR@`` (ta sama co ``@FAR@``, ale przez ``~``) prowadzą do
katalogu tymczasowego w ``~/.cache``, który narzędzie usuwa na końcu.

Wiersz na przypadek: ``ZGODNE`` (polecenie z ``pyta_o_zgode`` dostało odmowę hooka, a pozostałe doszły do powłoki),
``PRZESTÓJ`` (wynik narzędzia przyszedł dopiero po zamknięciu wejścia przez hosta, czyli w T3 agent stałby do powrotu
człowieka) albo ``ZMIANA`` (inny wynik, np. Claude Code już nie pyta o polecenie z pliku albo pyta o polecenie
kontrolne). Ostatnia linia to ``WYROCZNIA OK | …`` (kod 0) tylko wtedy, gdy każdy przypadek jest ``ZGODNE``, a hook
choć raz odmówił; inaczej ``WYROCZNIA PRZESTÓJ | …`` albo ``WYROCZNIA ZMIANA | …`` (kod 1). Bez ``claude`` na PATH
albo na Windows kończy się kodem 2, tak samo wyrocznia uruchomiona w Claude Code, które uruchomiła wyrocznia.

    .venv/bin/python tools/wyrocznia_zgody.py                  # wszystkie przypadki, ok. 5 min
    .venv/bin/python tools/wyrocznia_zgody.py k-sam-doslowny  # wybrane przypadki
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hooks"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import falszywe_api
from repo import ROOT
import zgoda

CASES = ROOT / "tools" / "wyrocznia_zgody.jsonl"
PREFIX = ROOT / "tools" / "wyrocznia_zgody_prefiks.sh"
SETTINGS = ROOT / ".claude" / "settings.json"
NOT_RUN = "WYROCZNIA-ZGODY-NIE-WYKONANO"
HOST_S = 30.0
# Flagi wyjścia, wejścia i uprawnień, z którymi T3 uruchamia Claude Code (ps na komputerze Maksa, 26.10.2026).
T3_FLAGS = (
    "--output-format",
    "stream-json",
    "--verbose",
    "--input-format",
    "stream-json",
    "--permission-prompt-tool",
    "stdio",
    "--tools",
    "default",
    "--permission-mode",
    "bypassPermissions",
    "--allow-dangerously-skip-permissions",
)
DENIED = "odmowa hooka"
SHELL = "powłoka"
WAITED = "czekał na hosta"


@dataclass(frozen=True)
class Case:
    name: str
    command: str
    asks: bool


@dataclass(frozen=True)
class Outcome:
    # Wynik narzędzia Bash, który Claude Code oddał modelowi, i czy host zamknął wejście, zanim go oddał.
    result: str | None
    host_gave_up: bool
    # Czy fałszywe API dostało choć jedno zapytanie.
    contacted: bool


class _Api:
    """Stan fałszywego Messages API: polecenie przypadku i wynik narzędzia, który Claude Code oddał modelowi."""

    command = ""
    result: str | None = None
    answered = threading.Event()


def answer(body: dict[str, object]) -> bytes:
    """Każda odpowiedź to ``tool_use`` Bash z poleceniem przypadku; wynik narzędzia z ``body`` kończy przypadek."""

    # Claude Code 2.1.310 woła tu tylko POST /v1/messages (1737 zapytań w pomiarach rundy 3 #496).
    messages = body.get("messages")
    result = falszywe_api.tool_result(messages[-1] if isinstance(messages, list) and messages else None)
    if result is not None:
        _Api.result = result
        _Api.answered.set()
    return falszywe_api.stream(
        {"type": "tool_use", "id": "toolu_wyrocznia", "name": "Bash", "input": {"command": _Api.command}}
    )


def cases(path: Path) -> list[Case]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Case(row["nazwa"], row["polecenie"], row["pyta_o_zgode"]) for row in rows]


def placed(command: str, sandbox: Path) -> str:
    far = sandbox / "far"
    tilde = "~/" + far.relative_to(Path.home()).as_posix()
    return command.replace("@WS@", str(sandbox / "ws")).replace("@FAR@", str(far)).replace("@TFAR@", tilde)


def what(got: Outcome) -> str:
    if not got.contacted:
        return "Claude Code nie zapytał fałszywego API"
    if got.result is not None and zgoda.MESSAGE in got.result:
        return DENIED
    if got.result is not None and NOT_RUN in got.result:
        return SHELL
    if got.host_gave_up:
        return WAITED
    return f"inny wynik: {(got.result or 'brak wyniku narzędzia')[:120]!r}"


def verdict(case: Case, seen: str) -> str:
    if seen == (DENIED if case.asks else SHELL):
        return "ZGODNE"
    return "PRZESTÓJ" if seen == WAITED else "ZMIANA"


def hook_command() -> str:
    """Jedyne polecenie hooka ``PermissionRequest`` z ustawień checkoutu, dosłownie tak, jak Claude Code podaje je prefiksowi."""

    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]
    (command,) = [str(hook["command"]) for entry in entries for hook in entry["hooks"]]
    return command


def ask(command: str, sandbox: Path, host_s: float, contact_s: float) -> Outcome:
    """Jedno uruchomienie Claude Code z poleceniem ``command`` aż do wyniku narzędzia; host nie odpowiada na zgodę."""

    if sys.platform == "win32":
        raise NotImplementedError("host wyroczni to potok nazwany, którego Windows nie ma")
    _Api.command = command
    _Api.result = None
    _Api.answered.clear()
    gave_up = threading.Event()
    pipe = sandbox / "wejscie"
    os.mkfifo(pipe)
    lines = [
        {"type": "control_request", "request_id": "init", "request": {"subtype": "initialize", "hooks": None}},
        {"type": "user", "message": {"role": "user", "content": "Run the command."}, "parent_tool_use_id": None, "session_id": ""},
    ]

    def host() -> None:
        with pipe.open("w", encoding="utf-8") as stdin:
            stdin.write("".join(json.dumps(line) + "\n" for line in lines))
            stdin.flush()
            if not _Api.answered.wait(host_s):
                gave_up.set()

    threading.Thread(target=host, daemon=True).start()
    try:
        # Claude Code w trybie stream-json nie kończy się sam po turze, więc wyrocznia kończy go po wyniku narzędzia.
        ran = falszywe_api.claude(
            [*T3_FLAGS, "--max-turns", "3"],
            answer=answer,
            cwd=ROOT,
            env={"CLAUDE_CODE_SHELL_PREFIX": str(PREFIX), "WYROCZNIA_ZGODY_HOOK": hook_command()},
            timeout=host_s + 60,
            stop=_Api.answered,
            contact_s=contact_s,
            stdin=pipe,
        )
    finally:
        _Api.answered.set()
        pipe.unlink()
    return Outcome(_Api.result, gave_up.is_set(), ran.contacted)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("nazwy", nargs="*", help="Nazwy przypadków (pole nazwa); bez nich wszystkie.")
    parser.add_argument("--przypadki", type=Path, default=CASES, help="Plik przypadków JSONL.")
    parser.add_argument(
        "--host-s", type=float, default=HOST_S, help=f"Jak długo host czeka bez odpowiedzi (domyślnie {HOST_S:g} s)."
    )
    falszywe_api.contact_option(parser)
    args = parser.parse_args(argv)
    chosen = [case for case in cases(args.przypadki) if not args.nazwy or case.name in args.nazwy]
    version = falszywe_api.claude_code(ROOT, len(chosen))
    if version is None:
        return 2
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="wyrocznia-zgody-", dir=cache))
    counts: dict[str, int] = {}
    denied = 0
    try:
        for folder in ("ws", "far/logi"):
            (sandbox / folder).mkdir(parents=True)
        for case in chosen:
            seen = what(ask(placed(case.command, sandbox), sandbox, args.host_s, args.kontakt_s))
            result = verdict(case, seen)
            counts[result] = counts.get(result, 0) + 1
            denied += seen == DENIED
            print(f"{result} {case.name} | {seen}", flush=True)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    failed = next((name for name in ("PRZESTÓJ", "ZMIANA") if counts.get(name)), None)
    if failed is None and denied == 0:
        failed = "ZMIANA"
        summary += ", hook nie odmówił ani razu"
    print(f"WYROCZNIA {failed or 'OK'} | Claude Code {version} | {summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
