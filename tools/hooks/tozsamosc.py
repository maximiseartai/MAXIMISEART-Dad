#!/usr/bin/env python3
"""Hook Claude Code dla Basha: przywraca tożsamość autora gita, którą polecenie zmieniło we wspólnym configu.

``git config user.email r@x`` bez ``--file`` pisze do ``.git/config`` głównego checkoutu, który dzielą wszystkie
jego worktree, więc od tej chwili każdy agent na tym komputerze podpisuje nim commity (13.11.2026 recenzent PR #1646
ustawił tak próbną tożsamość i podpisała ona setki commitów na ``main``).

Hook ocenia skutek polecenia, a nie jego tekst, bo zapis może przyjść w nieskończenie wielu postaciach (``xargs``,
skrypt, Python, łamanie linii, alias). Pilnuje configów, z których git czyta tożsamość: wspólnego configu repo
katalogu polecenia (``cwd``) i projektu (``CLAUDE_PROJECT_DIR``) razem z ``config.worktree`` głównego checkoutu
i bieżącego worktree, globalnego (``GIT_CONFIG_GLOBAL`` albo ``~/.gitconfig`` i ``$XDG_CONFIG_HOME/git/config``)
i systemowego (``GIT_CONFIG_SYSTEM`` albo ``/etc/gitconfig`` i ``etc/gitconfig`` obok katalogu ``git`` z PATH).

Cel przywrócenia ma jednego właściciela: rejestr wspólny dla wszystkich sesji Claude Code użytkownika
(``~/.cache/claude-tozsamosc``), czytany i pisany tylko pod wyłączną blokadą pliku. Trzyma polecenia w toku z ich
configami i bajty odniesienia każdego configu, którego pilnuje któreś z nich. ``PreToolUse`` zapisuje polecenie
w toku i migawkę jego configów (plik stanu: ``session_id`` i ``tool_use_id``), a bieżące bajty configu bierze za
odniesienie tylko wtedy, gdy żadne inne polecenie w toku go nie pilnuje, bo tylko wtedy nie może w nim stać zapis
polecenia agenta w trakcie. ``PostToolUse`` i ``PostToolUseFailure`` (kod różny od zera i przerwane) zdejmują
polecenie z toku i porównują bajty z jego migawką. Gdy config się zmienił, ``git config --file`` czyta klucze
``user``, ``author`` i ``committer`` z ``name`` i ``email``; klucz zmieniony w trakcie polecenia, który różni się od
odniesienia, wraca do wartości odniesienia (zapis zajęty przez ``config.lock`` innego gita ponawia przez
``RESTORE_RETRY_S``), a kod 2 z przyczyną i drogą jednorazowego podpisu na stderr trafia do agenta. Hook nigdy nie
zapisuje więc wartości z własnej migawki: zły podpis innego agenta, który stał w configu w chwili ``PreToolUse``, nie
jest odniesieniem, bo tamto polecenie było wtedy w toku. Git biegnie tylko wtedy, gdy któryś config zmienił bajty,
a repo tymczasowe spoza tych configów (świeży ``git init``) zostaje bez zmian.

Hook nie wie, kto zmienił config: zmiana Maksa z jego terminalu staje się odniesieniem przy następnym poleceniu, gdy
żaden agent nie ma wtedy polecenia w toku, a zmianę w trakcie polecenia agenta cofa, i komunikat każe agentowi
powiedzieć o tym w raporcie. Commit zrobiony w tym samym poleceniu ma już zmienioną tożsamość. Wszystko inne
przechodzi bez słowa (kod 0), także wejście, którego nie da się odczytać, brak gita i blokada rejestru zajęta dłużej
niż ``LOCK_WAIT_S``, bo hook nie może zatrzymać pracy.

Granica: hook porównuje configi tylko do zwrotu polecenia (zapis w poleceniu w tle po nim zostaje, a następne
polecenie bez innych w toku bierze go za odniesienie), tylko w repo katalogu polecenia i projektu, bez plików
z ``include.path`` i tylko na tym komputerze (``ssh``); polecenie bez ``PostToolUse`` (inny hook odmówił) zostaje
w toku przez ``IN_FLIGHT_S``, więc do tej pory zmiana Maksa nie staje się odniesieniem; inne harnessy niż Claude Code
(Codex, opencode) łapie tylko przegląd. Postacie z próbkami są w ``ZNANE_LUKI`` w ``tests/test_tozsamosc.py``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a poza biblioteką standardową importuje tylko ``tools/lib/repo.py``
(też pod 3.9), i to dopiero przy zmianie configu.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Optional
from collections.abc import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

IDENTITY_KEYS = tuple(f"{section}.{name}" for section in ("user", "author", "committer") for name in ("name", "email"))
# Katalog rejestru i plików stanu; testy podają własny.
STATE_ENV = "TOZSAMOSC_STAN"
SHARED = "wspolne.stan"
CALL_PREFIX = "polecenie-"
# Plik stanu bez ``PostToolUse`` (inny hook odmówił polecenia, człowiek go nie zatwierdził) znika po dobie.
STALE_S = 24 * 3600
# Polecenie w toku bez ``PostToolUse`` przestaje wstrzymywać przyjęcie odniesienia po trzykroć najdłuższym poleceniu
# Basha w Claude Code (600 s). Blokada i ponowienie zostawiają zapas do limitu hooka w ustawieniach (10 s).
IN_FLIGHT_S = 1800
LOCK_WAIT_S = 4.0
RESTORE_RETRY_S = 2.0
GIT_TIMEOUT_S = 3.0

Identity = dict[str, list[str]]

MESSAGE = (
    "Tożsamość autora gita zmieniła się w trakcie tego polecenia, więc hook przywrócił wartości sprzed poleceń agentów:\n"
    "{changes}\n"
    "Te configi dzielą checkout główny i wszystkie jego worktree (globalny i systemowy: każde repo na komputerze), więc "
    "każdy agent podpisywałby nimi commity. Podpisz jedno polecenie: git -c user.name=… -c user.email=… commit …, albo "
    "zmiennymi GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME i GIT_COMMITTER_EMAIL przed tym poleceniem (próba "
    "z wieloma commitami: export tych zmiennych na początku jej polecenia Basha); świeże repo w katalogu tymczasowym "
    "(git init) ma własny config. Commit zrobiony w tym poleceniu ma zmienioną tożsamość: przed pushem popraw go "
    "jednorazowym podpisem (git -c user.name=… -c user.email=… commit --amend --reset-author --no-edit). Jeśli to "
    "polecenie nie zmieniało tożsamości, zmienił ją w tym czasie ktoś inny (inny agent albo Maks w swoim terminalu): "
    "powiedz o tym w raporcie, bo hook cofnął także tę zmianę. Tożsamość we wspólnym configu zmienia tylko Maks, gdy "
    "żaden agent nie ma polecenia w toku."
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
    """Katalog stanu: jeden dla wszystkich sesji użytkownika, więc nie z ``TMPDIR``, który procesy mogą mieć różny."""

    given = environment.get(STATE_ENV)
    if given:
        return Path(given)
    return Path(environment.get("HOME") or Path.home()) / ".cache" / "claude-tozsamosc"


def _call_name(data: dict[str, object]) -> Optional[str]:
    session, call = data.get("session_id"), data.get("tool_use_id")
    if not isinstance(call, str) or not call:
        return None
    return re.sub(r"[^\w.-]", "_", f"{session}-{call}")[:200]


class Registry:
    """Wspólny rejestr: bajty odniesienia każdego configu i polecenia w toku (chwila ``PreToolUse``, configi)."""

    def __init__(self) -> None:
        self.reference: dict[str, Optional[str]] = {}
        self.running: dict[str, tuple[float, list[str]]] = {}


def _loaded(text: str) -> Registry:
    loaded = json.loads(text)
    registry = Registry()
    if not isinstance(loaded, dict):
        return registry
    reference, running = loaded.get("reference"), loaded.get("running")
    for path, content in reference.items() if isinstance(reference, dict) else ():
        if content is None or isinstance(content, str):
            registry.reference[path] = content
    for name, entry in running.items() if isinstance(running, dict) else ():
        since, paths = (entry.get("since"), entry.get("paths")) if isinstance(entry, dict) else (None, None)
        if isinstance(since, (int, float)) and isinstance(paths, list):
            registry.running[name] = (float(since), [str(path) for path in paths])
    return registry


@contextmanager
def _locked(directory: Path) -> Iterator[Registry]:
    """Rejestr pod wyłączną blokadą pliku, zapisany po wyjściu z bloku; ``TimeoutError`` po ``LOCK_WAIT_S`` czekania."""

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory / "zamek", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        while not _try_lock(descriptor):
            if time.monotonic() > deadline:
                raise TimeoutError("blokada rejestru tożsamości zajęta")
            time.sleep(0.01)
        shared = directory / SHARED
        try:
            registry = _loaded(shared.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            registry = Registry()
        yield registry
        running = {name: {"since": since, "paths": paths} for name, (since, paths) in registry.running.items()}
        temporary = directory / f"{SHARED}.{os.getpid()}"
        temporary.write_text(json.dumps({"reference": registry.reference, "running": running}), encoding="utf-8")
        os.replace(temporary, shared)
    finally:
        os.close(descriptor)  # zamknięcie zwalnia blokadę


def _try_lock(descriptor: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def before(data: dict[str, object], environment: dict[str, str]) -> None:
    name = _call_name(data)
    if name is None:
        return
    directories = [value for value in (data.get("cwd"), environment.get("CLAUDE_PROJECT_DIR")) if isinstance(value, str) and value]
    paths = watched(directories, environment)
    directory = _state_dir(environment)
    now = time.time()
    with _locked(directory) as registry:
        registry.running = {other: entry for other, entry in registry.running.items() if now - entry[0] <= IN_FLIGHT_S}
        busy = {path for _, watched_paths in registry.running.values() for path in watched_paths}
        # Odniesienie configu, którego nie pilnuje żadne polecenie w toku, następne PreToolUse i tak bierze z dysku.
        registry.reference = {path: content for path, content in registry.reference.items() if path in busy}
        snapshot = {str(path): _read(path) for path in paths}
        for path, content in snapshot.items():
            registry.reference.setdefault(path, content)
        registry.running[name] = (now, list(snapshot))
        descriptor = os.open(directory / f"{CALL_PREFIX}{name}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle)
    for old in directory.glob(f"{CALL_PREFIX}*.json"):
        try:
            if now - old.stat().st_mtime > STALE_S:
                old.unlink()
        except OSError:
            pass


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


def _config(path: Path, deadline: float, *step: str) -> None:
    """``git config --file path`` z ``step``; zapis, któremu ``config.lock`` trzyma inny git, ponawia do ``deadline``."""

    while True:
        try:
            _git(path.parent, "config", "--file", str(path), *step)
            return
        except subprocess.CalledProcessError as failed:
            locked = (failed.returncode == 255 and Path(f"{path}.lock").exists()) or "could not lock" in str(failed.stderr)
            if not locked or time.monotonic() > deadline:
                raise
        time.sleep(0.05)


def _restore(path: Path, key: str, values: list[str], deadline: float) -> Optional[str]:
    """Przywraca ``values`` klucza ``key`` w ``path`` (jedną wartość w miejscu wpisu); zwraca błąd gita albo ``None``."""

    steps: list[tuple[str, ...]] = [("--replace-all", key, values[0])] if len(values) == 1 else [("--unset-all", key)]
    if len(values) != 1:
        steps += [("--add", key, value) for value in values]
    for step in steps:
        try:
            _config(path, deadline, *step)
        except subprocess.CalledProcessError as failed:
            if failed.returncode != 5:  # 5: klucza nie ma, więc nie ma czego usuwać
                return str(failed.stderr).strip() or f"kod {failed.returncode}"
    return None


def _shown(values: list[str]) -> str:
    return ", ".join(repr(value) for value in values) or "(brak)"


def after(data: dict[str, object], environment: dict[str, str]) -> list[str]:
    """Zmiany tożsamości od ``PreToolUse`` tego polecenia, każda przywrócona do odniesienia (albo z błędem)."""

    name = _call_name(data)
    if name is None:
        return []
    directory = _state_dir(environment)
    state = directory / f"{CALL_PREFIX}{name}.json"
    if not state.is_file():
        return []
    deadline = time.monotonic() + RESTORE_RETRY_S
    changes: list[str] = []
    with _locked(directory) as registry:
        registry.running.pop(name, None)
        try:
            snapshot = json.loads(state.read_text(encoding="utf-8"))
            state.unlink()
        except (OSError, ValueError):
            return []
        parsed: dict[Optional[str], Optional[Identity]] = {}

        def read(content: Optional[str]) -> Optional[Identity]:
            if content not in parsed:
                parsed[content] = identity(content, directory)
            return parsed[content]

        for name_of_path, old in snapshot.items() if isinstance(snapshot, dict) else ():
            path = Path(name_of_path)
            new = _read(path)
            if new == old:
                continue
            was, now, target = read(old), read(new), read(registry.reference.get(name_of_path, old))
            if was is None or now is None or target is None:
                continue
            for key in IDENTITY_KEYS:
                current, wanted = now.get(key, []), target.get(key, [])
                if was.get(key, []) != current and current != wanted:
                    failed = _restore(path, key, wanted, deadline)
                    outcome = f"nie udało się przywrócić ({failed}), powiedz Maksowi" if failed else "przywrócone"
                    changes.append(f"- {path}: {key} {_shown(wanted)} → {_shown(current)}: {outcome}")
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
