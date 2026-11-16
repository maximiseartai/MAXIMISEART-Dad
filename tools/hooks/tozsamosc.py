#!/usr/bin/env python3
"""Hook Claude Code dla Basha: przywraca tożsamość autora gita, którą polecenie zmieniło we wspólnym configu.

``git config user.email r@x`` bez ``--file`` pisze do ``.git/config`` głównego checkoutu, który dzielą wszystkie
jego worktree, więc od tej chwili każdy agent na tym komputerze podpisuje nim commity (13.11.2026 recenzent PR #1646
ustawił tak próbną tożsamość i podpisała ona setki commitów na ``main``).

Hook ocenia skutek polecenia, a nie jego tekst, bo zapis może przyjść w nieskończenie wielu postaciach (``xargs``,
skrypt, Python, łamanie linii, alias). ``PreToolUse`` zapamiętuje bajty configów, z których git czyta tożsamość:
wspólnego configu repo katalogu polecenia (``cwd``) i projektu (``CLAUDE_PROJECT_DIR``) razem z ``config.worktree``
głównego checkoutu i bieżącego worktree, globalnego (``GIT_CONFIG_GLOBAL`` albo ``~/.gitconfig`` i
``$XDG_CONFIG_HOME/git/config``) i systemowego (``GIT_CONFIG_SYSTEM`` albo ``/etc/gitconfig`` i ``etc/gitconfig`` obok
katalogu ``git`` z PATH). ``PostToolUse`` i ``PostToolUseFailure`` (polecenie z kodem różnym od zera i przerwane)
porównują je z tym samym plikiem stanu (``session_id`` i ``tool_use_id``). Gdy plik się zmienił, ``git config --file``
czyta z obu wersji klucze ``user``, ``author`` i ``committer`` z ``name`` i ``email``; każdy zmieniony klucz wraca do
poprzednich wartości, a kod 2 z przyczyną i drogą jednorazowego podpisu na stderr trafia do agenta. Git biegnie więc
tylko wtedy, gdy któryś config zmienił bajty, a repo tymczasowe spoza tych configów (świeży ``git init``) zostaje bez
zmian.

Hook nie wie, kto zmienił config: zmianę Maksa z jego terminalu w trakcie polecenia agenta też cofa, a komunikat każe
agentowi powiedzieć o tym w raporcie. Commit zrobiony w tym samym poleceniu ma już zmienioną tożsamość.
Wszystko inne przechodzi bez słowa (kod 0), także wejście, którego nie da się odczytać, i brak gita, bo hook nie może
zatrzymać pracy.

Granica: hook porównuje configi tylko do zwrotu polecenia (zapis w poleceniu w tle po nim zostaje), tylko w repo
katalogu polecenia i projektu, bez plików z ``include.path`` i tylko na tym komputerze (``ssh``); inne harnessy niż
Claude Code (Codex, opencode) łapie tylko przegląd. Postacie z próbkami są w ``ZNANE_LUKI`` w
``tests/test_tozsamosc.py``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a poza biblioteką standardową importuje tylko ``tools/lib/repo.py``
(też pod 3.9), i to dopiero przy zmianie configu.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

IDENTITY_KEYS = tuple(f"{section}.{name}" for section in ("user", "author", "committer") for name in ("name", "email"))
# Katalog plików stanu między ``PreToolUse`` a ``PostToolUse``; testy podają własny.
STATE_ENV = "TOZSAMOSC_STAN"
# Plik stanu bez ``PostToolUse`` (inny hook odmówił polecenia, człowiek go nie zatwierdził) znika po dobie.
STALE_S = 24 * 3600
GIT_TIMEOUT_S = 3.0

Identity = dict[str, list[str]]

MESSAGE = (
    "Tożsamość autora gita zmieniła się w trakcie tego polecenia, więc hook przywrócił poprzednie wartości:\n{changes}\n"
    "Te configi dzielą checkout główny i wszystkie jego worktree (globalny i systemowy: każde repo na komputerze), więc "
    "każdy agent podpisywałby nimi commity. Podpisz jedno polecenie: git -c user.name=… -c user.email=… commit …, albo "
    "zmiennymi GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME i GIT_COMMITTER_EMAIL przed tym poleceniem (próba "
    "z wieloma commitami: export tych zmiennych na początku jej polecenia Basha); świeże repo w katalogu tymczasowym "
    "(git init) ma własny config. Commit zrobiony w tym poleceniu ma zmienioną tożsamość: przed pushem popraw go "
    "jednorazowym podpisem (git -c user.name=… -c user.email=… commit --amend --reset-author --no-edit). Jeśli to "
    "polecenie nie zmieniało tożsamości, zmienił ją w tym czasie ktoś inny (inny agent albo Maks w swoim terminalu): "
    "powiedz o tym w raporcie, bo hook cofnął także tę zmianę. Tożsamość we wspólnym configu zmienia tylko Maks."
)


def _git_dir(start: Path) -> Optional[Path]:
    """Katalog gita repo, w którym leży ``start`` (``.git`` albo ``gitdir:`` z pliku ``.git`` worktree)."""

    for directory in (start, *start.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            first = dot_git.read_text(encoding="utf-8", errors="replace").partition("\n")[0]
            if first.startswith("gitdir:"):
                return directory / first[len("gitdir:") :].strip()
            return None
    return None


def _common_dir(git_dir: Path) -> Path:
    commondir = git_dir / "commondir"
    if commondir.is_file():
        return git_dir / commondir.read_text(encoding="utf-8", errors="replace").strip()
    return git_dir


def watched(directories: list[str], environment: dict[str, str]) -> list[Path]:
    """Configi, z których git w ``directories`` czyta tożsamość, w kolejności, bez powtórzeń."""

    files: list[Path] = []
    for directory in directories:
        git_dir = _git_dir(Path(directory))
        if git_dir is not None:
            common = _common_dir(git_dir)
            files += [common / "config", common / "config.worktree", git_dir / "config.worktree"]
    if environment.get("GIT_CONFIG_GLOBAL"):
        files.append(Path(environment["GIT_CONFIG_GLOBAL"]))
    else:
        home = Path(environment.get("HOME") or Path.home())
        xdg = environment.get("XDG_CONFIG_HOME") or str(home / ".config")
        files += [home / ".gitconfig", Path(xdg) / "git" / "config"]
    if environment.get("GIT_CONFIG_SYSTEM"):
        files.append(Path(environment["GIT_CONFIG_SYSTEM"]))
    else:
        files.append(Path("/etc/gitconfig"))
        git = shutil.which("git", path=environment.get("PATH"))
        if git:
            files.append(Path(git).parent.parent / "etc" / "gitconfig")
    unique: dict[str, Path] = {}
    for path in files:
        unique.setdefault(os.path.realpath(path), Path(os.path.normpath(path)))
    return list(unique.values())


def _read(path: Path) -> Optional[str]:
    """Bajty pliku jako tekst latin-1 (odwracalny dla każdego bajtu) albo ``None``, gdy pliku nie ma."""

    try:
        return path.read_bytes().decode("latin-1")
    except OSError:
        return None


def _state_dir(environment: dict[str, str]) -> Path:
    given = environment.get(STATE_ENV)
    if given:
        return Path(given)
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "")
    return Path(tempfile.gettempdir()) / f"claude-tozsamosc-{user}"


def _state_file(data: dict[str, object], environment: dict[str, str]) -> Optional[Path]:
    session, call = data.get("session_id"), data.get("tool_use_id")
    if not isinstance(call, str) or not call:
        return None
    name = re.sub(r"[^\w.-]", "_", f"{session}-{call}")[:200]
    return _state_dir(environment) / f"{name}.json"


def before(data: dict[str, object], environment: dict[str, str]) -> None:
    state = _state_file(data, environment)
    if state is None:
        return
    directories = [value for value in (data.get("cwd"), environment.get("CLAUDE_PROJECT_DIR")) if isinstance(value, str) and value]
    snapshot = {str(path): _read(path) for path in watched(directories, environment)}
    state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = time.time()
    for old in state.parent.glob("*.json"):
        try:
            if now - old.stat().st_mtime > STALE_S:
                old.unlink()
        except OSError:
            pass
    descriptor = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle)


def _git(directory: Path, *arguments: str) -> str:
    import repo  # dopiero przy zmianie configu: polecenie, które configu nie zmienia, nie płaci za import

    return repo.git(directory, *arguments, timeout=GIT_TIMEOUT_S)


def identity(content: Optional[str], directory: Path) -> Optional[Identity]:
    """Wartości kluczy tożsamości w treści configu (pusty słownik bez pliku) albo ``None``, gdy git jej nie czyta."""

    if content is None:
        return {}
    copy = directory / f"config-{os.getpid()}"
    copy.write_bytes(content.encode("latin-1"))
    try:
        listed = _git(directory, "config", "--file", str(copy), "--no-includes", "--list", "-z")
    except subprocess.CalledProcessError:
        return None
    finally:
        copy.unlink()
    found: Identity = {}
    for entry in listed.split("\0"):
        key, _, value = entry.partition("\n")  # git podaje sekcję i nazwę klucza małymi literami
        if key in IDENTITY_KEYS:
            found.setdefault(key, []).append(value)
    return found


def _restore(path: Path, key: str, values: list[str]) -> Optional[str]:
    """Przywraca ``values`` klucza ``key`` w ``path`` (jedną wartość w miejscu wpisu); zwraca błąd gita albo ``None``."""

    steps: list[tuple[str, ...]] = [("--replace-all", key, values[0])] if len(values) == 1 else [("--unset-all", key)]
    if len(values) != 1:
        steps += [("--add", key, value) for value in values]
    for step in steps:
        try:
            _git(path.parent, "config", "--file", str(path), *step)
        except subprocess.CalledProcessError as failed:
            if failed.returncode != 5:  # 5: klucza nie ma, więc nie ma czego usuwać
                return str(failed.stderr).strip() or f"kod {failed.returncode}"
    return None


def _shown(values: list[str]) -> str:
    return ", ".join(repr(value) for value in values) or "(brak)"


def after(data: dict[str, object], environment: dict[str, str]) -> list[str]:
    """Zmiany tożsamości od ``PreToolUse`` tego polecenia, każda przywrócona (albo z błędem przywrócenia)."""

    state = _state_file(data, environment)
    if state is None:
        return []
    try:
        snapshot = json.loads(state.read_text(encoding="utf-8"))
        state.unlink()
    except (OSError, ValueError):
        return []
    changes: list[str] = []
    for name, old in snapshot.items() if isinstance(snapshot, dict) else ():
        path = Path(name)
        new = _read(path)
        if new == old:
            continue
        before_values, after_values = identity(old, state.parent), identity(new, state.parent)
        if before_values is None or after_values is None:
            continue
        for key in IDENTITY_KEYS:
            was, now = before_values.get(key, []), after_values.get(key, [])
            if was != now:
                failed = _restore(path, key, was)
                outcome = f"nie udało się przywrócić ({failed}), powiedz Maksowi" if failed else "przywrócone"
                changes.append(f"- {path}: {key} {_shown(was)} → {_shown(now)}: {outcome}")
    return changes


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, RecursionError):
        return 0
    if not isinstance(data, dict):
        return 0
    environment = dict(os.environ)
    event = data.get("hook_event_name")
    try:
        if event == "PreToolUse":
            before(data, environment)
            return 0
        if event not in ("PostToolUse", "PostToolUseFailure"):
            return 0
        changes = after(data, environment)
    except (OSError, ImportError, subprocess.SubprocessError):
        return 0
    if not changes:
        return 0
    print(MESSAGE.format(changes="\n".join(changes)), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
