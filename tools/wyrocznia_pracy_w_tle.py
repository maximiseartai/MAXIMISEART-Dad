from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hooks"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import falszywe_api
import falszywy_t3
import praca_w_tle
from repo import ROOT

OPIS = """Uruchamia claude -p z pracą w tle, podagentem i t3_background_wait, by sprawdzić hooki praca_w_tle.py; uruchom po każdej aktualizacji Claude Code.

Wyrocznia hooka ``tools/hooks/praca_w_tle.py``: hook działa, dopóki Claude Code uruchamia hooki ``Stop`` z listą
``background_tasks`` i ``PostToolUse`` z ``agent_id`` podagenta i ID zadania w odpowiedzi narzędzia, słucha odmowy
hooka ``Stop`` i budzi sesję po końcu zadania w tle. Po aktualizacji Claude Code ta wyrocznia uruchamia więc
``claude -p`` w trybie bypass (jak T3) w katalogu tego checkoutu, czyli z jego ``.claude/settings.json``, a z serwerów
MCP tylko z fałszywym ``t3-code`` (``tools/lib/falszywy_t3.py``). Modelu nie ma: lokalne fałszywe API (adres z
``falszywe_api.claude``) każe wywołać narzędzia przypadku, a po ich wyniku kończy turę słowami agentów z nocy
4/5.11.2026 („Czekam na powiadomienie o procesie w tle.”), także po każdej odmowie hooka.

Przypadki (``CASES``):

- ``praca-w-tle`` uruchamia ``sleep 60`` z ``run_in_background``, a ``ZGODNE`` znaczy, że hook odmówił końca tury dwa
  razy, drugi raz przy ``stop_hook_active``; wtedy wyrocznia kończy Claude Code, a ``sleep 60``, które Claude Code
  uruchamia poza swoją grupą procesów, kończy się samo;
- ``bez-pracy-w-tle`` uruchamia ``true`` na pierwszym planie, a ``ZGODNE`` znaczy, że Claude Code sam skończył turę
  bez odmowy;
- ``shell-podagenta`` woła narzędzie Agent, którego podagent uruchamia ``sleep 5`` z ``run_in_background`` i kończy,
  a ``ZGODNE`` znaczy, że Bash podagenta oddał wynik, a Claude Code skończył się sam bez odmowy;
- ``zadanie-zarejestrowane`` uruchamia ``sleep 3`` z ``run_in_background`` i wywołuje ``t3_background_wait`` z jego
  ID, a ``ZGODNE`` znaczy, że Claude Code skończył się sam bez odmowy, a przedtem po końcu zadania zapytał API z
  powiadomieniem o nim (``NOTIFICATION``), czyli obudził sesję.

Hook pisze dziennik i pliki sesji do katalogu tymczasowego wyroczni (``praca_w_tle.LOG_ENV``), nie do
``~/.cache/maximiseart/``. Inny wynik to ``ZMIANA`` z opisem. Ostatnia linia to ``WYROCZNIA OK | …`` (kod 0) tylko
wtedy, gdy każdy przypadek jest ``ZGODNE``; inaczej ``WYROCZNIA ZMIANA | …`` (kod 1). Bez ``claude`` na PATH albo na
Windows kończy się kodem 2, tak samo wyrocznia uruchomiona w Claude Code, które uruchomiła wyrocznia. Claude Code
uruchamia ``tools/lib/falszywe_api.py`` tak, by mogło pytać tylko fałszywe API, a gdy przez ``--kontakt-s`` sekund go
nie zapyta, kończy je, a wyrocznia zgłasza ``ZMIANA``.

    .venv/bin/python tools/wyrocznia_pracy_w_tle.py               # wszystkie przypadki, ok. 20 s
    .venv/bin/python tools/wyrocznia_pracy_w_tle.py praca-w-tle   # wybrany przypadek
"""

MARKER = "WYROCZNIA-PRACY-W-TLE"
# Polecenie podagenta; nie zawiera ``MARKER``, więc jego zapytania API są odróżnialne od zapytań głównej pętli.
SUBAGENT = "WYROCZNIA-PODAGENT"
WAITING = "Czekam na powiadomienie o procesie w tle."
NOTIFICATION = "<task-notification>"
TASK_ID = re.compile(r"with ID: (\w+)")
AGENT = "Agent"
LIMIT_S = 120.0


@dataclass(frozen=True)
class Case:
    name: str
    # Bash przypadku: w głównej pętli, a przy ``subagent`` w podagencie narzędzia Agent.
    bash: dict[str, object]
    # Ile odmów hooka znaczy ZGODNE: 2 (druga przy stop_hook_active) przy pracy w tle, 0 bez niej.
    refusals: int
    subagent: bool = False
    # Po wyniku Basha główna pętla wywołuje ``t3_background_wait`` z ID jego zadania.
    register: bool = False


def _background(command: str, description: str) -> dict[str, object]:
    return {"command": command, "run_in_background": True, "description": description}


CASES = (
    Case("praca-w-tle", _background("sleep 60", "Sen 60 s w tle"), 2),
    Case("bez-pracy-w-tle", {"command": "true", "description": "Polecenie na pierwszym planie"}, 0),
    Case("shell-podagenta", _background("sleep 5", "Sen podagenta w tle"), 0, subagent=True),
    Case("zadanie-zarejestrowane", _background("sleep 3", "Sen zarejestrowany w tle"), 0, register=True),
)


@dataclass(frozen=True)
class Outcome:
    refusals: int
    tool_result: bool
    # Kod wyjścia Claude Code, który skończył się sam, albo ``None``, gdy zakończyła go wyrocznia albo limit czasu.
    returncode: int | None
    # Czy fałszywe API dostało zapytanie przypadku (z ``MARKER``).
    asked: bool
    # Czy Bash podagenta oddał wynik.
    subagent_result: bool
    # Czy po wyniku ``t3_background_wait`` główna pętla dostała powiadomienie o końcu zadania.
    woken: bool


class _Api:
    """Stan fałszywego Messages API przypadku: narzędzia przypadku, po nich koniec tury, po drugiej odmowie ``stop``."""

    case = CASES[0]
    lock = threading.Lock()
    refusals = 0
    tool_result = False
    subagent_result = False
    woken = False
    asked = False
    stop = threading.Event()


def _tool(name: str, given: dict[str, object], call: str) -> bytes:
    """Wywołanie narzędzia ``name``; ``call`` odróżnia wywołania jednej rozmowy, bo Claude Code skleja te o jednym ID."""

    return falszywe_api.stream({"type": "tool_use", "id": f"toolu_wyrocznia_{call}", "name": name, "input": given})


def _text(text: str) -> bytes:
    return falszywe_api.stream({"type": "text", "text": text})


def answer(body: dict[str, object]) -> bytes:
    api = _Api
    found = body.get("messages")
    messages = found if isinstance(found, list) else []
    texts = [_texts(message) for message in messages]
    first = "".join(texts[0]) if texts else ""
    results = [result for message in messages for result in falszywe_api.tool_results(message)]
    if SUBAGENT in first:
        with api.lock:
            api.subagent_result = api.subagent_result or bool(results)
        return _text("Podagent skończył.") if results else _tool("Bash", api.case.bash, "podagent")
    if MARKER not in first:
        return _text("ok")  # zapytanie poboczne Claude Code (tytuł, podsumowanie)
    api.asked = True
    refusals = sum(any(praca_w_tle.REFUSAL in text for text in message) for message in texts)
    with api.lock:
        if api.stop.is_set():  # Claude Code przed końcem pyta jeszcze raz; wynik przypadku już jest
            return _text(WAITING)
        api.refusals = max(api.refusals, refusals)
        api.tool_result = api.tool_result or bool(results)
        notified = any(NOTIFICATION in text for message in texts for text in message)
        api.woken = api.woken or (api.case.register and len(results) >= 2 and notified)
        if refusals >= 2:
            api.stop.set()
        if not results and api.case.subagent:
            subagent: dict[str, object] = {"description": "Podagent z pracą w tle", "prompt": f"{SUBAGENT}: uruchom polecenie.", "subagent_type": "general-purpose"}
            return _tool(AGENT, subagent, "agent")
        if not results:
            return _tool("Bash", api.case.bash, "bash")
        if api.case.register and len(results) == 1:
            return _tool(falszywy_t3.CALLED, {"taskIds": TASK_ID.findall(results[0])[-1:]}, "rejestracja")
    return _text(WAITING)


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


def command_line(case: Case) -> list[str]:
    """Argumenty ``claude -p`` przypadku; ustawienia, adres fałszywego API i model dodaje ``falszywe_api.claude``."""

    return [
        "-p",
        f"{MARKER} {case.name}: uruchom polecenie.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--allow-dangerously-skip-permissions",
        "--mcp-config",
        falszywy_t3.config(),
        "--strict-mcp-config",
        "--max-turns",
        "10",
    ]


def ask(case: Case, log: Path, limit_s: float, contact_s: float) -> Outcome:
    """Jedno ``claude -p`` przypadku aż do jego końca, drugiej odmowy hooka albo ``limit_s``.

    Dziennik hooka i pliki sesji idą obok ``log`` (``praca_w_tle.LOG_ENV``), bo zapisy z prób wyroczni nie należą do
    prawdziwych sesji w katalogu domowym.
    """

    _Api.case, _Api.refusals, _Api.tool_result, _Api.asked = case, 0, False, False
    _Api.subagent_result, _Api.woken = False, False
    _Api.stop.clear()
    ran = falszywe_api.claude(
        command_line(case),
        answer=answer,
        cwd=ROOT,
        env={praca_w_tle.LOG_ENV: str(log)},
        timeout=limit_s,
        stop=_Api.stop,
        contact_s=contact_s,
    )
    return Outcome(_Api.refusals, _Api.tool_result, ran.returncode, _Api.asked, _Api.subagent_result, _Api.woken)


def verdict(case: Case, got: Outcome) -> tuple[str, str]:
    """``ZGODNE`` albo ``ZMIANA`` przypadku i opis tego, co zrobił Claude Code."""

    tool = AGENT if case.subagent else "Bash"
    if not got.asked:
        seen = "Claude Code nie zapytał fałszywego API"
    elif not got.tool_result:
        seen = f"{tool} nie oddał wyniku"
    elif case.subagent and not got.subagent_result:
        seen = "Bash podagenta nie oddał wyniku"
    elif got.refusals:
        seen = f"odmowy hooka: {got.refusals}"
    elif case.register and not got.woken:
        seen = f"koniec tury bez odmowy (kod {got.returncode}), ale bez powiadomienia o końcu zadania"
    else:
        woke = ", sesja obudzona po końcu zadania" if case.register else ""
        seen = f"koniec tury bez odmowy (kod {got.returncode}){woke}"
    quiet = got.refusals == 0 and got.returncode == 0
    expected = got.tool_result and (
        got.refusals >= 2
        if case.refusals
        else quiet and (got.subagent_result or not case.subagent) and (got.woken or not case.register)
    )
    return ("ZGODNE" if expected else "ZMIANA"), seen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "nazwy", nargs="*", help=f"Nazwy przypadków ({', '.join(case.name for case in CASES)}); bez nich wszystkie."
    )
    parser.add_argument(
        "--limit-s", type=float, default=LIMIT_S, help=f"Limit jednego przypadku (domyślnie {LIMIT_S:g} s)."
    )
    falszywe_api.contact_option(parser)
    args = parser.parse_args(argv)
    chosen = [case for case in CASES if not args.nazwy or case.name in args.nazwy]
    version = falszywe_api.claude_code(ROOT, len(chosen))
    if version is None:
        return 2
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="wyrocznia-pracy-w-tle-") as folder:
        log = Path(folder) / "praca_w_tle.jsonl"
        for case in chosen:
            result, seen = verdict(case, ask(case, log, args.limit_s, args.kontakt_s))
            counts[result] = counts.get(result, 0) + 1
            print(f"{result} {case.name} | {seen}", flush=True)
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    failed = bool(counts.get("ZMIANA")) or not chosen
    print(f"WYROCZNIA {'ZMIANA' if failed else 'OK'} | Claude Code {version} | {summary or 'brak przypadków'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
