#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from nakladka import NAKLADKI, ZMIENNA_SESJI
import potomne
import repo

try:
    from czekanie import CI_ADDRESS, INSTEAD
except (ImportError, SyntaxError) as error:
    BROKEN: Optional[str] = f"{type(error).__name__}: {error}"
else:
    BROKEN = None

CHECKOUT = NAKLADKI.parent.parent
QUERIES = Path(".cache") / "maximiseart" / "odpytywanie_gh"
SAME_QUERIES_ALLOWED = 6
WINDOW_S = 600
VALUE_OPTIONS = frozenset({"-R", "--repo"})
STATUS_PAIRS = frozenset({("pr", "checks"), ("run", "list")})
LOG_OPTIONS = frozenset({"--log", "--log-failed", "--web", "-w"})
PYTHON = re.compile(r"python[0-9.]*")
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
ANCESTORS = 16


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


def python_script(words: list[str]) -> Optional[str]:
    value = False
    for word in words:
        if value:
            value = False
        elif word == "-":
            return None
        elif word == "--check-hash-based-pycs":
            value = True
        elif word.startswith("--"):
            continue
        elif word.startswith("-"):
            for position, letter in enumerate(word[1:], start=2):
                if letter in "cm":
                    return None
                if letter in "WX":
                    value = position == len(word)
                    break
        else:
            return word
    return None


def shell_script(words: list[str]) -> tuple[bool, Optional[str]]:
    value = False
    for word in words:
        if value:
            value = False
        elif word in SHELL_VALUE_OPTIONS:
            value = True
        elif word.startswith("--command"):
            return True, None
        elif word.startswith("--"):
            continue
        elif word[:1] in "-+" and len(word) > 1:
            if "c" in word[1:]:
                return True, None
        else:
            return False, word
    return False, None


def process(pid: int) -> Optional[tuple[int, list[str]]]:
    try:
        shown = subprocess.run(
            ["ps", "-ww", "-o", "ppid=", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return None
    if len(shown) < 2 or not shown[0].isdigit():
        return None
    return int(shown[0]), shown[1:]


def working_folder(pid: int) -> Optional[Path]:
    proc = Path("/proc") / str(pid) / "cwd"
    if proc.is_dir():
        return proc.resolve()
    try:
        shown = potomne.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], cwd=CHECKOUT, timeout=10).stdout.splitlines()
    except (OSError, potomne.TimeoutExpired):
        return None
    return next((Path(line[1:]) for line in shown if line.startswith("n/")), None)


def tracked(pid: int, script: str) -> bool:
    path = Path(script)
    if not path.is_absolute():
        folder = working_folder(pid)
        if folder is None:
            return False
        path = folder / path
    try:
        inside = path.resolve().relative_to(CHECKOUT.resolve())
    except ValueError:
        return False
    return repo.succeeds(CHECKOUT, "ls-files", "--error-unmatch", "--", inside.as_posix())


def from_repo_script(pid: int) -> bool:
    for _ in range(ANCESTORS):
        found = process(pid) if pid > 1 else None
        if found is None:
            return False
        parent, words = found
        name = Path(words[0]).name.lstrip("-").lower()
        if PYTHON.fullmatch(name):
            script = python_script(words[1:])
            return script is not None and tracked(pid, script)
        if name in SHELLS:
            command, script = shell_script(words[1:])
            if not command:
                return script is not None and tracked(pid, script)
        pid = parent
    return False


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
    if BROKEN is not None:
        print(f"nakładka gh: nie liczę zapytań o stan CI, bo tools/hooks/czekanie.py się nie importuje ({BROKEN})", file=sys.stderr)
    elif session and asks_status(arguments) and not from_repo_script(os.getppid()):
        refused = refusal(arguments, session)
        if refused is not None:
            print(refused, file=sys.stderr)
            return 2
    os.execv(gh, [gh, *arguments])
    return 0


if __name__ == "__main__":
    sys.exit(main())
