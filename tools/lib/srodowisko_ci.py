"""Środowisko Required CI dowodu strażnika ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md),
„Środowisko dowodu”): drzewo HEAD PR scalone z bazą i Python z jego zależnościami, zbudowane tak, jak zadanie
„Ruff, mypy” (``JOB``) z ``.github/workflows/ci.yml`` buduje swoje.

Dowód strażnika ``mypy``, ``ruff`` i ``ast-grep <id>`` (``tools/na_scalonych_pr.py --straznik``, ``tools/lib/straznik.py``)
bierze środowisko tylko stąd, nie od wołającego, więc job ``dowod``, merge na Macu i autor liczą to, co Required CI
(#2116 r4–r6: system maszyny, lista platform, zależności ``main`` zamiast HEAD PR):

- ``built`` scala HEAD PR z bazą (``repo.merge_commit``, jak ``refs/pull/N/merge``, które sprawdza Required CI), zakłada
  kopię tego drzewa i przez uv (bez konfiguracji uv, ze zmiennymi ``variables``) środowisko: Python ``CI_PYTHON``,
  pakiety, które uv rozwiązuje z ``pyproject.toml`` drzewa z dodatkami ``CI_EXTRAS`` dla systemu runnera
  (``CI_PLATFORM``), zainstalowane bez ponownego rozwiązania, więc Mac dostaje zbiór pakietów linuksa, i projekt
  edytowalnie z kopii, jak ``CI_INSTALL``;
- ``mismatch`` mówi, czym zadanie ``JOB`` drzewa buduje środowisko inaczej niż ``built``: runner, ``container``,
  ``env`` i ``defaults`` workflow i zadania, krok przed ostatnim krokiem ruff albo mypy spoza listy (checkout bez
  ``ref`` i ``path``, setup-python z ``CI_PYTHON``, setup-uv, ``CI_INSTALL``, ``python -m ruff|mypy|pytest`` bez
  ``env``, ``working-directory`` i ``shell``), polecenia ruff i mypy inne niż ``kroki_lokalne.static_steps`` i konfiguracja
  uv w drzewie. ``built`` odmawia drzewa z różnicą, a ``tests/test_srodowisko_ci.py`` wymaga ``mismatch(ROOT) == []``,
  więc stałe opisują Required CI ``main``, a zmiana środowiska Required CI wchodzi osobnym PR przed dowodem, który jej
  potrzebuje.

Odmowa to ``Refused`` (``ValueError``) z tym, co zrobić. Granica: wydanie poprawkowe Pythona (``CI_PYTHON`` bez
poprawki), wersja uv i obraz runnera mogą różnić się od runu Required CI, pakiety rozwiązują się w chwili dowodu (repo
nie ma pliku blokady, więc dwa runy CI też mogą je rozwiązać inaczej), a krok ``python -m pytest`` przed mypy uznaje się
za taki, który środowiska nie zmienia. Dowód biegnie na Linuksie i macOS (job ``dowod`` i Mac koordynatora).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import yaml

from kroki_lokalne import static_steps
import potomne
import repo

WORKFLOW = ".github/workflows/ci.yml"
JOB = "ruff-mypy"  # zadanie Required CI „Ruff, mypy”, w którym biegną ruff i mypy
CI_RUNNER = "ubuntu-latest"
CI_PLATFORM = "x86_64-unknown-linux-gnu"  # system ``CI_RUNNER`` dla ``uv pip compile --python-platform``
CI_PYTHON = "3.14"
CI_EXTRAS = ("dev", "workflowy")
CI_INSTALL = 'uv pip install --system --python "${{ steps.python.outputs.python-path }}" -e ".[' + ",".join(CI_EXTRAS) + ']"'
BUILD_TIMEOUT_S = 300
# Akcje dozwolone przed ostatnim krokiem ruff albo mypy i klucze ``with``, które środowiska nie zmieniają.
_ACTIONS = {"actions/checkout": {"fetch-depth", "persist-credentials"}, "actions/setup-python": {"python-version"}, "astral-sh/setup-uv": {"enable-cache"}}
_RUN_KEYS = {"name", "id", "if", "run"}
_USES_KEYS = {"name", "id", "if", "uses", "with"}
_CHECKS = ("ruff", "mypy", "pytest")  # ``python -m <narzędzie>`` dozwolone przed ostatnim krokiem ruff albo mypy
# Zmienne wołającego, których uv i narzędzia dowodu nie dostają: sterują Pythonem, mypy, ruff, pip i uv, środowiskiem
# wirtualnym albo dają token GitHuba; ``ci.yml`` żadnej z nich nie ustawia (``mismatch``). Miejsce pamięci uv i jego
# Pythonów wyniku nie zmienia, więc zostaje.
_HIDDEN_PREFIXES = ("PYTHON", "MYPY", "RUFF", "PIP_", "UV_")
_HIDDEN = {"VIRTUAL_ENV", "CONDA_PREFIX", "GH_TOKEN", "GITHUB_TOKEN"}
_KEPT = {"UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"}


class Refused(ValueError):
    """Odmowa dowodu: środowiska Required CI nie da się zbudować tak, jak buduje je CI; tekst mówi, co zrobić."""


@dataclass(frozen=True)
class Environment:
    """Środowisko Required CI z ``built``: commit ``tree`` (HEAD PR scalony z bazą), jego kopia ``copy`` z projektem
    zainstalowanym edytowalnie, ``python`` z zależnościami drzewa i zmienne ``variables``, z którymi biegną narzędzia."""

    tree: str
    copy: Path
    python: Path
    variables: Mapping[str, str]

    @property
    def ast_grep(self) -> Path:
        return self.python.parent / "ast-grep"


def variables() -> dict[str, str]:
    """Zmienne wołającego dla uv i narzędzi dowodu, bez tych, którymi ``ci.yml`` nie steruje Required CI."""

    return {name: value for name, value in os.environ.items() if name in _KEPT or not (name.startswith(_HIDDEN_PREFIXES) or name in _HIDDEN)}


@contextmanager
def built(root: Path, head: str, target: str) -> Iterator[Environment]:
    """Środowisko Required CI dla HEAD PR ``head`` scalonego z ``target`` (baza PR; dla PR już scalonego ``main`` sprzed
    jego merge'a), w repozytorium ``root``; znika z końcem bloku."""

    if sys.platform == "win32":
        raise Refused("środowisko Required CI: dowód strażnika biegnie na Linuksie i macOS, uruchom go tam")
    uv = shutil.which("uv")
    if uv is None:
        raise Refused("środowisko Required CI: brak uv na PATH, a Required CI instaluje zależności uv (setup-uv): zainstaluj uv")
    merged = repo.merge_tree(root, target, head)
    if merged.conflicts:
        raise Refused(f"środowisko Required CI: HEAD {head[:7]} scala się z bazą {target[:7]} z konfliktem ({', '.join(merged.conflicts)}): zaktualizuj PR z bazy")
    tree = repo.merge_commit(root, target, head, merged)
    with potomne.commit_copy(root, tree) as copy, tempfile.TemporaryDirectory(prefix="srodowisko-ci-") as folder:
        if problems := mismatch(copy):
            raise Refused(
                f"środowisko Required CI: zadanie {JOB} z {WORKFLOW} drzewa PR scalonego z bazą buduje je inaczej niż dowód ({'; '.join(problems)}): "
                "zmień środowisko Required CI osobnym PR przed tym, razem z tools/lib/srodowisko_ci.py, bo dowód buduje je kodem bazy"
            )
        yield Environment(tree, copy, _install(uv, copy, Path(folder)), variables())


def _install(uv: str, copy: Path, folder: Path) -> Path:
    environment, pins = folder / "env", folder / "piny.txt"
    python = environment / "bin" / "python"
    extras = [part for extra in CI_EXTRAS for part in ("--extra", extra)]
    plain = (uv, "--no-config", "--quiet")
    commands = (
        (*plain, "venv", "--python", CI_PYTHON, str(environment)),
        (*plain, "pip", "compile", "--python-version", CI_PYTHON, "--python-platform", CI_PLATFORM, *extras, "--output-file", str(pins), str(copy / "pyproject.toml")),
        (*plain, "pip", "install", "--python", str(python), "--no-deps", "-r", str(pins)),
        (*plain, "pip", "install", "--python", str(python), "--no-deps", "-e", str(copy)),
    )
    for command in commands:
        step = " ".join(part for part in command[3:6] if not part.startswith("-"))
        try:
            done = potomne.run(command, cwd=copy, env=variables(), timeout=BUILD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise Refused(f"środowisko Required CI: uv {step} trwało ponad {BUILD_TIMEOUT_S} s, uruchom ponownie") from None
        if done.returncode:
            lines = (done.stdout + done.stderr).strip().splitlines()
            raise Refused(f"środowisko Required CI: uv {step} skończył się kodem {done.returncode} ({lines[-1][:300] if lines else 'bez wyjścia'}): popraw pyproject.toml albo uruchom ponownie")
    return python


def mismatch(tree: Path) -> list[str]:
    """Czym zadanie ``JOB`` z ``WORKFLOW`` w drzewie ``tree`` buduje środowisko ruff i mypy inaczej niż ``built``."""

    problems = [f"{name} w drzewie: uv Required CI ją czyta, a dowód nie" for name in _uv_configs(tree)]
    try:
        workflow = yaml.safe_load((tree / WORKFLOW).read_text(encoding="utf-8"))
        job, steps = workflow["jobs"][JOB], workflow["jobs"][JOB]["steps"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as error:
        return [*problems, f"brak kroków zadania {JOB} w {WORKFLOW} ({type(error).__name__}: {error})"]
    problems += [f"{key} w workflow" for key in ("env", "defaults") if key in workflow]
    problems += [f"{key} w zadaniu" for key in ("container", "env", "defaults") if key in job]
    if job.get("runs-on") != CI_RUNNER:
        problems.append(f"runs-on {job.get('runs-on')!r} zamiast {CI_RUNNER!r}")
    checks = [index for index, step in enumerate(steps) if _command(step)[2:3] in (["ruff"], ["mypy"])]
    for step in steps[: checks[-1] + 1 if checks else len(steps)]:
        if problem := _step_problem(step):
            problems.append(f"krok „{step.get('name') or step.get('uses') or step.get('run')}” przed ostatnim krokiem ruff albo mypy: {problem}")
    ci = [" ".join(_command(steps[index])) for index in checks]
    local = [" ".join(("python", *step.command[1:])) for step in static_steps(tree)]
    problems += [f"krok ruff albo mypy „{one}” bez kroku dowodu (kroki_lokalne.static_steps)" for one in ci if not any(_starts(command, one) for command in local)]
    problems += [f"krok dowodu „{command}” bez kroku ruff albo mypy w zadaniu" for command in local if not any(_starts(command, one) for one in ci)]
    return problems


def _uv_configs(tree: Path) -> list[str]:
    found = ["uv.toml"] if (tree / "uv.toml").exists() else []
    pyproject = tree / "pyproject.toml"
    return [*found, *(["[tool.uv] w pyproject.toml"] if pyproject.exists() and "[tool.uv" in pyproject.read_text(encoding="utf-8") else [])]


def _command(step: Any) -> list[str]:
    """Słowa polecenia ``run`` kroku (``>-`` w YAML składa je w jedną linię); krok bez ``run`` nie ma żadnego."""

    return str(step.get("run", "")).split() if isinstance(step, Mapping) else []


def _starts(command: str, ci: str) -> bool:
    return command == ci or command.startswith(f"{ci} ")


def _step_problem(step: Any) -> str | None:
    if not isinstance(step, Mapping):
        return "to nie krok"
    if extra := set(step) - (_USES_KEYS if "uses" in step else _RUN_KEYS):
        return f"klucze {sorted(extra)} zmieniają środowisko"
    if "uses" in step:
        action = str(step["uses"]).partition("@")[0]
        given = step.get("with") or {}
        if action not in _ACTIONS:
            return "akcja spoza listy srodowisko_ci._ACTIONS"
        if extra := set(given) - _ACTIONS[action]:
            return f"with {sorted(extra)} spoza listy"
        if action == "actions/setup-python" and str(given.get("python-version")) != CI_PYTHON:
            return f"python-version {given.get('python-version')!r} zamiast {CI_PYTHON!r}"
        return None
    words = _command(step)
    if " ".join(words) == CI_INSTALL or (words[:2] == ["python", "-m"] and words[2:3] and words[2] in _CHECKS):
        return None
    return f"polecenie spoza listy (instalacja {CI_INSTALL} albo python -m {'|'.join(_CHECKS)})"
