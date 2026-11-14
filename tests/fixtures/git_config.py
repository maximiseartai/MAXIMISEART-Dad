"""Git w testach z jedną konfiguracją, tą samą na Macu Maksa i na runnerach CI.

Bez niej Git czyta konfigurację systemową i globalną komputera testów. Na Macu Command Line Tools ustawiają
``init.defaultBranch=main``, a Ubuntu w CI tworzy ``master``, więc test z ``git init --bare`` przechodził lokalnie i padał
w CI. ``hermetic_git`` (sesja z ``tests/conftest.py``) wyłącza konfigurację systemową, podstawia globalną z ``CONFIG``
i odrzuca każde uruchomienie gita z procesu testów ze środowiskiem, które ją gubi: przez ``subprocess`` (także przez
``env``, powłokę i ``executable=``), ``os.posix_spawn`` i ``os.system``. Przechodzi też git bez żadnej konfiguracji
komputera, jak ``repo.git(isolated=True)``: ``GIT_CONFIG_GLOBAL`` to ``os.devnull``, ``HOME`` pusty katalog, a
``XDG_CONFIG_HOME`` nie ma. Granica: taki git nie ma tożsamości, więc jego ``git commit`` na Macu zgadnie ją z nazwy
komputera, a w CI padnie.

Proces, który uruchamia kod narzędzia (pakiet ``rozliczenia``), dostaje gita bez tożsamości, jak u taty: ``CONFIG``
daje ją tylko gitowi testów i narzędzi Maksa.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import inspect
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from types import FrameType
from typing import Any

import pytest

CONFIG: Mapping[str, str] = {
    "init.defaultBranch": "main",
    "user.name": "test",
    "user.email": "test@example.com",
    "core.autocrlf": "false",
    "commit.gpgSign": "false",
    "tag.gpgSign": "false",
    # Od Gita 2.54 konserwacja po ``commit`` robi też ``git worktree prune`` w tle i usuwa worktree zakładany
    # w następnym kroku testu (#312).
    "maintenance.auto": "false",
    "gc.auto": "0",
}
# Puste, a nie usunięte: Git bez ``user.*`` zgaduje tożsamość z nazwy komputera, a na Macu nazwa z „.local” mu wystarcza.
_WITHOUT_IDENTITY: Mapping[str, str] = {"user.name": "", "user.email": ""}
_IDENTITY_VARIABLES = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL")
_MACHINE_VARIABLES = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_SYSTEM")
_GIT = frozenset({"git", "git.exe"})
_ENV = frozenset({"env", "env.exe"})
_SHELLS = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "sh.exe", "bash.exe", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
)
_SHELL_OPTION = re.compile(r"-\w+|/[a-zA-Z]")
_FIX = (
    "zbuduj env z os.environ (np. os.environ | {...}) albo nie podawaj env; konfigurację komputera z czymś więcej "
    "podstaw przez computer_git_config z tests/fixtures/git_config.py"
)
_POPEN = inspect.signature(subprocess.Popen.__init__)
_configs: set[str] = set()

__all__ = ["CONFIG", "computer_git_config", "hermetic_git"]


def _text(extra: str) -> str:
    sections: dict[str, list[str]] = {}
    for key, value in CONFIG.items():
        section, _, name = key.rpartition(".")
        sections.setdefault(section, []).append(f"\t{name} = {value}\n")
    return "".join(f"[{section}]\n{''.join(lines)}" for section, lines in sections.items()) + extra


def computer_git_config(path: Path, extra: str) -> Path:
    """Globalna konfiguracja Gita komputera: ``CONFIG`` i ``extra``; podstaw ją jako ``GIT_CONFIG_GLOBAL``."""

    path.write_text(_text(extra), encoding="utf-8")
    _configs.add(str(path))
    return path


def _word(value: object) -> str:
    if isinstance(value, (str, bytes, os.PathLike)):
        return os.fsdecode(value)
    return ""


def _name(value: object) -> str:
    return re.split(r"[\\/]", _word(value))[-1].lower()


def _command_git(words: Sequence[object], environment: Mapping[str, str]) -> Mapping[str, str] | None:
    """Środowisko gita, którego uruchamia polecenie ``words``; ``None``, gdy polecenie nie uruchamia gita."""

    if not words:
        return None
    name = _name(words[0])
    if name in _GIT:
        return environment
    if name in _ENV:
        return _after_env([_word(word) for word in words[1:]], environment)
    if name in _SHELLS:
        script = [_word(word) for word in words[1:]]
        return _shell_git(" ".join(word for word in script if not _SHELL_OPTION.fullmatch(word)), environment)
    return None


def _after_env(words: list[str], environment: Mapping[str, str]) -> Mapping[str, str] | None:
    changed = dict(environment)
    while words:
        word = words.pop(0)
        if word in {"-i", "-", "--ignore-environment"}:
            changed = {}
        elif word in {"-u", "--unset"} and words:
            changed.pop(words.pop(0), None)
        elif word.startswith("--unset="):
            changed.pop(word.removeprefix("--unset="), None)
        elif word in {"-S", "--split-string"} and words:
            words[:0] = shlex.split(words.pop(0))
        elif word in {"-C", "--chdir"} and words:
            words.pop(0)
        elif word.startswith("-"):
            continue
        elif "=" in word:
            name, _, value = word.partition("=")
            changed[name] = value
        else:
            return _command_git([word, *words], changed)
    return None


def _shell_git(script: str, environment: Mapping[str, str]) -> Mapping[str, str] | None:
    """Środowisko pierwszego gita w poleceniu powłoki: prostych poleceń, ``export``, ``unset`` i przypisań przed nimi."""

    current = dict(environment)
    for part in re.split(r"[;&|()\n`]+", script):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        if words[:1] in (["export"], ["unset"]):
            for word in words[1:]:
                name, assigned, value = word.partition("=")
                if words[0] == "unset":
                    current.pop(name, None)
                elif assigned:
                    current[name] = value
            continue
        found = _after_env(words, current)
        if found is not None:
            return found
    return None


def _popen_git(arguments: Mapping[str, Any]) -> Mapping[str, str] | None:
    args = arguments["args"]
    given = arguments.get("env")
    environment: Mapping[str, str] = os.environ if given is None else given
    if arguments.get("shell"):
        script = args if isinstance(args, (str, bytes)) else " ".join(map(_word, args))
        return _shell_git(_word(script), environment)
    if isinstance(args, (str, bytes)):
        words: list[object] = list(_word(args).split())
    elif isinstance(args, Sequence):
        words = list(args)
    else:
        words = [args]
    if arguments.get("executable") is not None:
        words = [arguments["executable"], *words[1:]]
    return _command_git(words, environment)


def _without_config(environment: Mapping[str, str]) -> bool:
    """Czy git ze środowiskiem ``environment`` nie czyta żadnej konfiguracji użytkownika: pusty plik globalny i pusty
    ``HOME`` bez ``XDG_CONFIG_HOME``, więc też bez plików ``~/.config/git``."""

    home = environment.get("HOME")
    empty_home = home is not None and Path(home).is_dir() and not any(Path(home).iterdir())
    return environment.get("GIT_CONFIG_GLOBAL") == os.devnull and "XDG_CONFIG_HOME" not in environment and empty_home


def _problem(environment: Mapping[str, str]) -> str | None:
    if environment.get("GIT_CONFIG_NOSYSTEM") != "1":
        return "GIT_CONFIG_NOSYSTEM nie jest 1, więc git czyta konfigurację systemową komputera"
    if environment.get("GIT_CONFIG_GLOBAL") not in _configs and not _without_config(environment):
        return f"GIT_CONFIG_GLOBAL={environment.get('GIT_CONFIG_GLOBAL')!r} to nie konfiguracja testów"
    return None


def _refuse(git_environment: Mapping[str, str] | None) -> None:
    problem = None if git_environment is None else _problem(git_environment)
    if problem is not None:
        raise AssertionError(
            f"Test uruchamia gita ze środowiskiem bez konfiguracji testów: {problem}. Git w testach ma jedną konfigurację, "
            f"tę samą na każdym komputerze, więc test nie zależy od konfiguracji Maksa ani runnera. Napraw: {_FIX}."
        )


def _launched_by_tool() -> bool:
    """Czy proces uruchamia kod narzędzia taty: najbliższa ramka z ``rozliczenia``, ``tests`` albo ``tools``."""

    frame: FrameType | None = sys._getframe(2)
    while frame is not None:
        package = str(frame.f_globals.get("__name__", "")).partition(".")[0]
        if package == "rozliczenia":
            return True
        if package in {"tests", "tools", "conftest"}:
            return False
        frame = frame.f_back
    return False


def _without_identity(environment: Mapping[str, str]) -> dict[str, str]:
    kept = {name: value for name, value in environment.items() if name not in _IDENTITY_VARIABLES}
    first = int(kept.get("GIT_CONFIG_COUNT", "0"))
    for index, (key, value) in enumerate(_WITHOUT_IDENTITY.items(), start=first):
        kept[f"GIT_CONFIG_KEY_{index}"] = key
        kept[f"GIT_CONFIG_VALUE_{index}"] = value
    kept["GIT_CONFIG_COUNT"] = str(first + len(_WITHOUT_IDENTITY))
    return kept


def _checked_spawn(original: Callable[..., int]) -> Callable[..., int]:
    # Od Pythona 3.13 ``env=None`` znaczy środowisko procesu, a ``subprocess`` na Linuksie przekazuje je tak przez
    # ``os.posix_spawn``, gdy ``Popen`` dostał ``env=None``.
    def spawn(path: Any, argv: Sequence[Any], env: Mapping[str, str] | None, *rest: Any, **options: Any) -> int:
        _refuse(_command_git([path, *argv[1:]], os.environ if env is None else env))
        return original(path, argv, env, *rest, **options)

    return spawn


@contextmanager
def hermetic_git(directory: Path) -> Iterator[None]:
    """Git w tym procesie i w jego potomkach tylko z ``CONFIG``, bez konfiguracji systemowej komputera."""

    config = computer_git_config(directory / "gitconfig", "")
    original_init = subprocess.Popen.__init__
    original_system = os.system

    def checked_init(self: subprocess.Popen[Any], *args: Any, **options: Any) -> None:
        bound = _POPEN.bind(self, *args, **options)
        if _launched_by_tool():
            given = bound.arguments.get("env")
            bound.arguments["env"] = _without_identity(os.environ if given is None else given)
        _refuse(_popen_git(bound.arguments))
        original_init(*bound.args, **bound.kwargs)

    def checked_system(command: Any) -> int:
        _refuse(_shell_git(_word(command), os.environ))
        return original_system(command)

    with pytest.MonkeyPatch.context() as patch:
        for name in _MACHINE_VARIABLES:
            patch.delenv(name, raising=False)
        patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        patch.setenv("GIT_CONFIG_GLOBAL", str(config))
        patch.setattr(subprocess.Popen, "__init__", checked_init)
        patch.setattr(os, "system", checked_system)
        if sys.platform != "win32":
            patch.setattr(os, "posix_spawn", _checked_spawn(os.posix_spawn))
            patch.setattr(os, "posix_spawnp", _checked_spawn(os.posix_spawnp))
        yield
