"""Uruchamia claude -p z pracą w tle i bez niej, by sprawdzić hook Stop praca_w_tle.py; uruchom po każdej aktualizacji Claude Code.

Wyrocznia hooka ``tools/hooks/praca_w_tle.py``: hook działa, dopóki Claude Code uruchamia hooki ``Stop`` z listą
``background_tasks`` i słucha ich odmowy, więc po aktualizacji Claude Code ta wyrocznia uruchamia ``claude -p`` w trybie
bypass (jak T3) w katalogu tego checkoutu, czyli z jego ``.claude/settings.json``. Modelu nie ma: lokalne fałszywe API
(``ANTHROPIC_BASE_URL``) każe wywołać Basha z poleceniem przypadku, a po jego wyniku kończy turę słowami agentów z nocy
4/5.11.2026 („Czekam na powiadomienie o procesie w tle.”), także po każdej odmowie hooka.

Przypadki (``CASES``): ``praca-w-tle`` uruchamia ``sleep 60`` z ``run_in_background``, a ``ZGODNE`` znaczy, że hook
odmówił końca tury dwa razy, drugi raz przy ``stop_hook_active``; wtedy wyrocznia kończy Claude Code, a ``sleep 60``,
które Claude Code uruchamia poza swoją grupą procesów, kończy się samo. ``bez-pracy-w-tle`` uruchamia ``true`` na pierwszym planie, a ``ZGODNE`` znaczy, że Claude Code sam
skończył turę bez odmowy. Hook pisze dziennik do pliku w katalogu tymczasowym wyroczni
(``praca_w_tle.LOG_ENV``), nie do ``~/.cache/maximiseart/praca_w_tle.jsonl``. Inny wynik to ``ZMIANA`` z opisem. Ostatnia linia to ``WYROCZNIA OK | …`` (kod 0) tylko
wtedy, gdy każdy przypadek jest ``ZGODNE``; inaczej ``WYROCZNIA ZMIANA | …`` (kod 1). Bez ``claude`` na PATH albo na
Windows kończy się kodem 2, tak samo wyrocznia uruchomiona w Claude Code, które uruchomiła wyrocznia. Claude Code
uruchamia ``tools/lib/falszywe_api.py`` tak, by mogło pytać tylko fałszywe API, a gdy przez ``--kontakt-s`` sekund go
nie zapyta, kończy je, a wyrocznia zgłasza ``ZMIANA``.

    .venv/bin/python tools/wyrocznia_pracy_w_tle.py               # oba przypadki, ok. 5 s
    .venv/bin/python tools/wyrocznia_pracy_w_tle.py praca-w-tle   # wybrany przypadek
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hooks"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import falszywe_api
import potomne
import praca_w_tle

ROOT = Path(__file__).resolve().parents[1]
MARKER = "WYROCZNIA-PRACY-W-TLE"
WAITING = "Czekam na powiadomienie o procesie w tle."
LIMIT_S = 120.0


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


class _Api:
    """Stan fałszywego Messages API przypadku: Bash, po jego wyniku koniec tury, po drugiej odmowie hooka ``stop``."""

    case = CASES[0]
    lock = threading.Lock()
    refusals = 0
    tool_result = False
    asked = False
    stop = threading.Event()


def answer(body: dict[str, object]) -> bytes:
    """Odpowiedź API na zapytanie ``body``; liczy odmowy hooka i zapamiętuje wynik Basha w stanie ``_Api``."""

    api = _Api
    found = body.get("messages")
    messages = found if isinstance(found, list) else []
    texts = [_texts(message) for message in messages]
    if not texts or MARKER not in "".join(texts[0]):
        return falszywe_api.stream({"type": "text", "text": "ok"})  # zapytanie poboczne Claude Code (tytuł, podsumowanie)
    api.asked = True
    refusals = sum(any(praca_w_tle.REFUSAL in text for text in message) for message in texts)
    with api.lock:
        if api.stop.is_set():  # Claude Code przed końcem pyta jeszcze raz; wynik przypadku już jest
            return falszywe_api.stream({"type": "text", "text": WAITING})
        api.refusals = max(api.refusals, refusals)
        api.tool_result = api.tool_result or any(_has_tool_result(message) for message in messages)
        if refusals >= 2:
            api.stop.set()
        if api.tool_result:
            return falszywe_api.stream({"type": "text", "text": WAITING})
    return falszywe_api.stream({"type": "tool_use", "id": "toolu_wyrocznia", "name": "Bash", "input": api.case.bash})


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
        "--max-turns",
        "10",
    ]


def ask(case: Case, log: Path, limit_s: float, contact_s: float) -> Outcome:
    """Jedno ``claude -p`` przypadku aż do jego końca, drugiej odmowy hooka albo ``limit_s``.

    Dziennik hooka idzie do ``log`` (``praca_w_tle.LOG_ENV``), bo odmowy z prób wyroczni nie należą do dziennika
    prawdziwych sesji w katalogu domowym.
    """

    _Api.case, _Api.refusals, _Api.tool_result, _Api.asked = case, 0, False, False
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
    return Outcome(_Api.refusals, _Api.tool_result, ran.returncode, _Api.asked)


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
        default=falszywe_api.CONTACT_S,
        help="Po ilu sekundach bez zapytania do fałszywego API wyrocznia kończy Claude Code "
        f"(domyślnie {falszywe_api.CONTACT_S:g} s).",
    )
    args = parser.parse_args(argv)
    chosen = [case for case in CASES if not args.nazwy or case.name in args.nazwy]
    nested = falszywe_api.nested()
    if nested:
        print(f"WYROCZNIA BRAK | {nested}")
        return 2
    if sys.platform == "win32" or shutil.which("claude") is None:
        print("WYROCZNIA BRAK | potrzebny claude na PATH na macOS albo Linuksie")
        return 2
    version = potomne.run(["claude", "--version"], cwd=ROOT, timeout=60).stdout.strip()
    print(f"Claude Code {version}, przypadki {len(chosen)}", flush=True)
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
