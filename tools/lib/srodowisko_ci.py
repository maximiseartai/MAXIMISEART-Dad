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
- ``mismatch`` mówi, czym zadanie ``JOB`` drzewa buduje środowisko inaczej niż ``built``: kroki od pierwszego do
  ostatniego kroku ruff albo mypy różne od ``job_steps`` (checkout, setup-python ``CI_PYTHON``, setup-uv, ``CI_INSTALL``
  i kroki ``kroki_lokalne.static_steps`` w ich kolejności z warunkiem ``_CI_IF``; równość, poza ``name`` i wersją akcji),
  klucz zadania spoza ``_JOB_KEYS`` (np. ``container``, ``env``, ``strategy``, ``continue-on-error``), inny runner,
  ``env`` i ``defaults`` workflow albo konfiguracja uv w drzewie. Przed sprawdzeniami nie biegnie więc żaden kod PR poza
  instalacją, a kroki dowodu to kroki zadania słowo w słowo. ``built`` odmawia drzewa z różnicą,
  a ``tests/test_srodowisko_ci.py`` wymaga ``mismatch(ROOT) == []``, więc stałe opisują Required CI ``main``, a zmiana
  środowiska Required CI wchodzi osobnym PR przed dowodem, który jej potrzebuje.

Odmowa to ``Refused`` (``ValueError``) z tym, co zrobić. Granica: wydanie poprawkowe Pythona (``CI_PYTHON`` bez
poprawki), wersja uv i obraz runnera mogą różnić się od runu Required CI, a pakiety rozwiązują się w chwili dowodu
(repo nie ma pliku blokady, więc dwa runy CI też mogą je rozwiązać inaczej). Dowód biegnie na Linuksie i macOS (job
``dowod`` i Mac koordynatora), a na macOS odmawia drzewa ze ścieżkami różnymi tylko wielkością liter, których jego
system plików nie rozróżnia.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import itertools
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from typing import Any

import yaml

from kroki_lokalne import static_steps
import potomne
import repo
from straznik import Environment

WORKFLOW = ".github/workflows/ci.yml"
JOB = "ruff-mypy"  # zadanie Required CI „Ruff, mypy”, w którym biegną ruff i mypy
CI_RUNNER = "ubuntu-latest"
CI_PLATFORM = "x86_64-unknown-linux-gnu"  # system ``CI_RUNNER`` dla ``uv pip compile --python-platform``
CI_PYTHON = "3.14"
CI_EXTRAS = ("dev", "workflowy")
CI_INSTALL = 'uv pip install --system --python "${{ steps.python.outputs.python-path }}" -e ".[' + ",".join(CI_EXTRAS) + ']"'
BUILD_TIMEOUT_S = 300
_JOB_KEYS = {"name", "runs-on", "permissions", "timeout-minutes", "steps"}
_INSTALL_ID = "deps"  # ``id`` kroku ``CI_INSTALL``, którego wynik czyta ``_CI_IF``
_CI_IF = "${{ !cancelled() && steps." + _INSTALL_ID + ".outcome == 'success' }}"
# Zmienne wołającego, których uv i narzędzia dowodu nie dostają: sterują Pythonem, mypy, ruff, pip i uv, środowiskiem
# wirtualnym albo dają token GitHuba; ``ci.yml`` żadnej z nich nie ustawia (``mismatch``). Miejsce pamięci uv i jego
# Pythonów wyniku nie zmienia, więc zostaje.
_HIDDEN_PREFIXES = ("PYTHON", "MYPY", "RUFF", "PIP_", "UV_")
_HIDDEN = {"VIRTUAL_ENV", "CONDA_PREFIX", "GH_TOKEN", "GITHUB_TOKEN"}
_KEPT = {"UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"}


class Refused(ValueError):
    """Odmowa dowodu: środowiska Required CI nie da się zbudować tak, jak buduje je CI; tekst mówi, co zrobić."""


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
    if sys.platform == "darwin" and (twins := _twins(root, tree)):
        raise Refused(
            f"środowisko Required CI: drzewo ma ścieżki różne tylko wielkością liter albo normalizacją Unicode ({', '.join(twins[:3])}), a system plików macOS "
            "trzyma jedną z nich, Linux runnera obie: dowód policzy job dowod statusu „Werdykt i bramka”, a przy merge'u uruchom go na Linuksie"
        )
    with tempfile.TemporaryDirectory(prefix="srodowisko-ci-") as folder:
        home, copy = Path(folder) / "dom", Path(folder) / "drzewo"
        home.mkdir()
        _checkout(root, tree, copy, home)
        if problems := mismatch(copy):
            raise Refused(
                f"środowisko Required CI: zadanie {JOB} z {WORKFLOW} drzewa PR scalonego z bazą buduje je inaczej niż dowód ({'; '.join(problems)}): "
                "zmień środowisko Required CI osobnym PR przed tym, razem z tools/lib/srodowisko_ci.py, bo dowód buduje je kodem bazy"
            )
        python = _install(uv, copy, Path(folder))
        # Narzędzia z pustym HOME, jak na runnerze: bez konfiguracji użytkownika mypy i ruff i bez globalnych wykluczeń gita.
        tools = {name: value for name, value in variables().items() if not name.startswith("XDG_")}
        yield Environment(tree, copy, python, {**tools, "HOME": str(home)})


def _checkout(root: Path, commit: str, copy: Path, home: Path) -> None:
    """Kopia commitu ``commit`` w ``copy`` jak checkout Required CI: osobne repozytorium z obiektami ``root``
    (alternates), bez szablonów, ``info/exclude`` repozytorium ``root`` i konfiguracji gita wołającego, które czytałyby
    checkout (filtry, końce linii) i ruff (wykluczenia)."""

    isolated = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1"}
    commands = (
        (("git", "clone", "--quiet", "--shared", "--no-checkout", "--template=", str(root.resolve()), str(copy)), root),
        (("git", "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit), copy),
    )
    for command, cwd in commands:
        done = potomne.run(command, cwd=cwd, env=isolated, timeout=BUILD_TIMEOUT_S)
        if done.returncode:
            raise Refused(f"środowisko Required CI: {' '.join(command[:2])} kopii skończył się kodem {done.returncode} ({done.stderr.strip()[-300:]}): uruchom ponownie")


def _twins(root: Path, tree: str) -> list[str]:
    """Ścieżki commitu ``tree``, które różnią się od innej tylko wielkością liter albo normalizacją Unicode (NFC i NFD):
    APFS macOS scala obie, a system plików runnera nie."""

    seen: dict[str, list[str]] = {}
    for path in repo.git(root, "ls-tree", "-r", "-z", "--name-only", tree).split("\0"):
        if path:
            seen.setdefault(unicodedata.normalize("NFC", path).casefold(), []).append(path)
    return sorted(path for paths in seen.values() if len(paths) > 1 for path in paths)


def _install(uv: str, copy: Path, folder: Path) -> Path:
    environment, pins = folder / "env", folder / "piny.txt"
    python = environment / "bin" / "python"
    extras = [part for extra in CI_EXTRAS for part in ("--extra", extra)]
    plain = (uv, "--no-config", "--quiet")
    _built(copy, "uv venv", (*plain, "venv", "--python", CI_PYTHON, str(environment)))
    # Znaczniki zależności (``python_full_version``) z wersją Pythona środowiska z poprawką, a nie z 3.14.0.
    version = _built(copy, "python --version", (str(python), "-c", "import platform; print(platform.python_version())")).strip()
    compiled = (*plain, "pip", "compile", "--python-version", version, "--python-platform", CI_PLATFORM, *extras, "--output-file", str(pins), str(copy / "pyproject.toml"))
    _built(copy, "uv pip compile", compiled)
    _built(copy, "uv pip install", (*plain, "pip", "install", "--python", str(python), "--no-deps", "-r", str(pins)))
    _built(copy, "uv pip install", (*plain, "pip", "install", "--python", str(python), "--no-deps", "-e", str(copy)))
    return python


def _built(copy: Path, step: str, command: tuple[str, ...]) -> str:
    """Wyjście kroku ``step`` budowy środowiska; porażka i przekroczony czas to ``Refused`` z tym, co zrobić."""

    try:
        done = potomne.run(command, cwd=copy, env=variables(), timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise Refused(f"środowisko Required CI: {step} trwało ponad {BUILD_TIMEOUT_S} s, uruchom ponownie") from None
    if done.returncode:
        lines = (done.stdout + done.stderr).strip().splitlines()
        raise Refused(f"środowisko Required CI: {step} skończył się kodem {done.returncode} ({lines[-1][:300] if lines else 'bez wyjścia'}): popraw pyproject.toml albo uruchom ponownie")
    return done.stdout


def job_steps(tree: Path) -> list[dict[str, object]]:
    """Kroki zadania ``JOB`` od pierwszego do ostatniego kroku ruff albo mypy, w postaci, którą zadanie musi mieć, żeby
    ``built`` i ``straznik`` liczyły to, co ono: checkout, setup-python ``CI_PYTHON``, setup-uv, ``CI_INSTALL`` i kroki
    ``kroki_lokalne.static_steps`` w ich kolejności, każdy z warunkiem ``_CI_IF``. Klucz ``name`` i wersja akcji po ``@``
    (podbija ją dependabot) się nie liczą."""

    checks = [{"if": _CI_IF, "run": " ".join(("python", *step.ci[1:]))} for step in static_steps(tree)]
    return [
        {"uses": "actions/checkout", "with": {"fetch-depth": 0, "persist-credentials": False}},
        {"id": "python", "uses": "actions/setup-python", "with": {"python-version": CI_PYTHON}},
        {"uses": "astral-sh/setup-uv", "with": {"enable-cache": False}},
        {"id": _INSTALL_ID, "run": CI_INSTALL},
        *checks,
    ]


def mismatch(tree: Path) -> list[str]:
    """Czym zadanie ``JOB`` z ``WORKFLOW`` w drzewie ``tree`` buduje środowisko ruff i mypy inaczej niż ``built``: każda
    różnica kroków od ``job_steps`` (równość, nie podobieństwo), klucz zadania spoza ``_JOB_KEYS``, inny runner, ``env``
    i ``defaults`` workflow albo konfiguracja uv."""

    problems = [f"{name} w drzewie: uv Required CI ją czyta, a dowód nie" for name in _uv_configs(tree)]
    try:
        workflow = yaml.safe_load((tree / WORKFLOW).read_text(encoding="utf-8"))
        job = workflow["jobs"][JOB]
        given = list(job["steps"])
    except (OSError, yaml.YAMLError, KeyError, TypeError) as error:
        return [*problems, f"brak kroków zadania {JOB} w {WORKFLOW} ({type(error).__name__}: {error})"]
    problems += [f"{key} w workflow" for key in ("env", "defaults") if key in workflow]
    problems += [f"{key} w zadaniu" for key in sorted(set(job) - _JOB_KEYS)]
    if job.get("runs-on") != CI_RUNNER:
        problems.append(f"runs-on {job.get('runs-on')!r} zamiast {CI_RUNNER!r}")
    expected = job_steps(tree)
    found = [_normal(step) for step in given[: len(expected)]]
    for number, (want, have) in enumerate(itertools.zip_longest(expected, found), start=1):
        if want != have:
            problems.append(f"krok {number} zadania to {have!r} zamiast {want!r}")
            break
    return problems


def _uv_configs(tree: Path) -> list[str]:
    """Konfiguracja uv, którą czyta ``CI_INSTALL`` w korzeniu drzewa: ``uv.toml`` i tabela ``tool.uv`` w ``pyproject.toml``
    w każdej postaci TOML (``[tool.uv]``, ``[ tool.uv ]``, ``uv.…`` pod ``[tool]``), więc czyta ją parser, nie tekst."""

    found = ["uv.toml"] if (tree / "uv.toml").exists() else []
    try:
        tool = tomllib.loads((tree / "pyproject.toml").read_text(encoding="utf-8")).get("tool", {})
    except FileNotFoundError:
        return found
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return [*found, f"pyproject.toml bez odczytu TOML ({type(error).__name__}: {error})"]
    return [*found, *(["tabela tool.uv w pyproject.toml"] if isinstance(tool, dict) and "uv" in tool else [])]


def _normal(step: Any) -> Any:
    """Krok bez ``name`` i z akcją bez wersji po ``@``; co innego niż słownik zostaje, jak jest."""

    if not isinstance(step, Mapping):
        return step
    normal = {key: value for key, value in step.items() if key != "name"}
    if "uses" in normal:
        normal["uses"] = str(normal["uses"]).partition("@")[0]
    return normal
