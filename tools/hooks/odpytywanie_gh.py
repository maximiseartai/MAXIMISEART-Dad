#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from czekanie import CI_ADDRESS, INSTEAD
from nakladka import NAKLADKI, POMIJA, ZMIENNA_SESJI

QUERIES = Path(".cache") / "maximiseart" / "odpytywanie_gh"
SAME_QUERIES_ALLOWED = 6
WINDOW_S = 600
VALUE_OPTIONS = frozenset({"-R", "--repo"})
STATUS_PAIRS = frozenset({("pr", "checks"), ("run", "list")})
LOG_OPTIONS = frozenset({"--log", "--log-failed", "--web", "-w"})


def asks_status(arguments: list[str]) -> bool:
    positional: list[str] = []
    value = False
    for word in arguments:
        if value:
            value = False
        elif word in VALUE_OPTIONS:
            value = True
        elif not word.startswith("-"):
            positional.append(word)
    pair = tuple(positional[:2])
    if pair in STATUS_PAIRS:
        return True
    if pair == ("run", "view"):
        return not LOG_OPTIONS.intersection(arguments)
    if pair == ("pr", "view"):
        return any("statusCheckRollup" in word for word in arguments)
    return positional[:1] == ["api"] and any(CI_ADDRESS.search(word) for word in arguments)


def real_gh() -> Optional[str]:
    folders = [
        folder
        for folder in os.environ.get("PATH", "").split(os.pathsep)
        if folder and Path(folder).resolve() != NAKLADKI.resolve()
    ]
    return shutil.which("gh", path=os.pathsep.join(folders))


def refusal(arguments: list[str], session: str) -> Optional[str]:
    key = json.dumps([os.getcwd(), os.environ.get("GH_REPO", ""), arguments])
    queries = Path.home() / QUERIES / f"{session}.jsonl"
    now = time.time()
    try:
        lines = queries.read_text(encoding="utf-8").splitlines() if queries.exists() else []
    except OSError:
        return None
    recent = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("k") == key and now - float(entry.get("t", 0)) < WINDOW_S:
            recent += 1
    if recent >= SAME_QUERIES_ALLOWED:
        return (
            f"Odmowa nakładki gh: gh {' '.join(arguments)} pyta o stan CI po raz {recent + 1} w {WINDOW_S // 60} minut, czyli odpytuje w "
            f"pętli. {INSTEAD}"
        )
    try:
        queries.parent.mkdir(parents=True, exist_ok=True)
        with queries.open("a", encoding="utf-8") as stored:
            stored.write(json.dumps({"t": now, "k": key}) + "\n")
    except OSError:
        return None
    return None


def main() -> int:
    arguments = sys.argv[1:]
    gh = real_gh()
    if gh is None:
        print("nakładka gh: w PATH nie ma prawdziwego gh", file=sys.stderr)
        return 127
    session = os.environ.get(ZMIENNA_SESJI, "")
    if session and not os.environ.get(POMIJA) and asks_status(arguments):
        refused = refusal(arguments, session)
        if refused is not None:
            print(refused, file=sys.stderr)
            return 2
    os.execv(gh, [gh, *arguments])
    return 0


if __name__ == "__main__":
    sys.exit(main())
