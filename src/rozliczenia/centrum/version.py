from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from pathlib import Path
from typing import Final
import urllib.request

from rozliczenia.centrum.opener import opener
from rozliczenia.file_state import file_state, path_state
from rozliczenia.tool_files import HOST, TOOL_ROOT

SERVICE: Final = "centrum-rozliczen"
_COMMIT = re.compile(r"[0-9a-f]{40}")


def short_commit(commit: str) -> str:
    return commit[:7]


def version_label(commit: str | None) -> str:
    return "nieznana" if commit is None else short_commit(commit)


@dataclass(frozen=True)
class RunningCentrum:
    commit: str | None

    def runs(self, commit: str | None) -> bool:
        return self.commit == (None if commit is None else short_commit(commit))


def running_centrum(port: int, *, timeout_s: float) -> RunningCentrum | None:
    direct = opener(urllib.request.ProxyHandler({}))
    try:
        with direct.open(f"http://{HOST}:{port}/api/health", timeout=timeout_s) as response:
            health = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(health, dict) or health.get("service") != SERVICE:
        return None
    commit = health.get("commit")
    return RunningCentrum(commit if isinstance(commit, str) else None)


def is_commit(text: str) -> bool:
    return _COMMIT.fullmatch(text) is not None


def tool_commit(root: Path = TOOL_ROOT) -> str | None:
    try:
        git_directory = _git_directory(root)
        if git_directory is None:
            return None
        head = (git_directory / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if is_commit(head) else None
        return _resolved(head.removeprefix("ref: "), git_directory)
    except (OSError, UnicodeDecodeError):
        return None


def commit_since(commit: str, root: Path = TOOL_ROOT) -> date | None:
    try:
        git_directory = _git_directory(root)
        if git_directory is None:
            return None
        entries = (git_directory / "logs" / "HEAD").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not entries:
        return None
    fields = entries[-1].partition("\t")[0].split(" ")
    if len(fields) < 5 or fields[1] != commit:
        return None
    try:
        return datetime.fromtimestamp(int(fields[-2]), datetime.strptime(fields[-1], "%z").tzinfo).date()
    except (ValueError, OverflowError):
        return None


def _git_directory(root: Path) -> Path | None:
    dot_git = root / ".git"
    state = path_state(dot_git)
    if state == "folder":
        return dot_git
    if state == "file":
        pointer = dot_git.read_text(encoding="utf-8").strip()
        if pointer.startswith("gitdir: "):
            return (root / pointer.removeprefix("gitdir: ")).resolve()
    return None


def _resolved(ref: str, git_directory: Path) -> str | None:
    common = git_directory
    commondir = git_directory / "commondir"
    if file_state(commondir) == "file":
        common = (git_directory / commondir.read_text(encoding="utf-8").strip()).resolve()
    for directory in dict.fromkeys((git_directory, common)):
        loose = directory / ref
        if file_state(loose) == "file":
            commit = loose.read_text(encoding="utf-8").strip()
            return commit if is_commit(commit) else None
    packed = common / "packed-refs"
    if file_state(packed) == "file":
        for line in packed.read_text(encoding="utf-8").splitlines():
            commit, _, name = line.partition(" ")
            if name == ref and is_commit(commit):
                return commit
    return None
