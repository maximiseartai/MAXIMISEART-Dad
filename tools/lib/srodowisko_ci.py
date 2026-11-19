"""Środowisko Required CI dowodu strażnika ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md),
„Środowisko dowodu”): drzewo HEAD PR scalone z bazą i Python z jego zależnościami, zbudowane tak, jak zadanie
„Ruff, mypy” (``JOB``) z ``.github/workflows/ci.yml`` buduje swoje.

Dowód strażnika ``mypy``, ``ruff``, ``ast-grep <id>`` i ``pytest <węzeł>`` (``tools/na_scalonych_pr.py --straznik``,
``tools/lib/straznik.py``) bierze środowisko tylko stąd, nie od wołającego, więc job ``dowod``, merge na Macu i autor
liczą to, co Required CI (#2116 r4–r6: system maszyny, lista platform, zależności ``main`` zamiast HEAD PR):

- ``built`` scala HEAD PR z bazą (``repo.merge_commit``, jak ``refs/pull/N/merge``, które sprawdza Required CI), zakłada
  kopię tego drzewa i przez uv (bez konfiguracji uv, ze zmiennymi ``variables``) środowisko: Python ``CI_PYTHON``,
  pakiety, które uv rozwiązuje z ``pyproject.toml`` drzewa z dodatkami ``CI_EXTRAS`` dla systemu runnera
  (``CI_PLATFORM``), zainstalowane bez ponownego rozwiązania, więc Mac dostaje zbiór pakietów linuksa, i projekt
  edytowalnie z kopii, jak ``CI_INSTALL``;
- ``mismatch`` mówi, czym zadanie ``JOB`` drzewa różni się od jedynej postaci, którą dowód liczy: kroki różne od
  ``job_steps`` (wszystkie kroki zadania na równość, poza ``name`` i wersją akcji: checkout, setup-python ``CI_PYTHON``,
  setup-uv, ``CI_INSTALL``, kroki ``kroki_lokalne.static_steps`` w ich kolejności i za nimi kroki reguł chwastów, każdy
  z warunkiem ``_CI_IF``), klucz zadania spoza ``_JOB_KEYS`` (np. ``container``, ``env``, ``strategy``,
  ``continue-on-error``), inny runner, ``env`` i ``defaults`` workflow albo konfiguracja uv w drzewie. Przed
  sprawdzeniami nie biegnie więc żaden kod PR poza instalacją, kroki ruff i mypy dowodu to kroki zadania słowo w słowo,
  a każdy krok, na którym dowód stoi, Required CI liczy bez wyjątku (#2161 r3 W1: krok dopisany za ostatnim
  sprawdzeniem). Kroki, na których dowód nie stoi (``.github/``, przypadki reguł), są w zadaniu Frontend.
  ``built`` odmawia drzewa z różnicą,
  a ``tests/test_srodowisko_ci.py`` wymaga ``mismatch(ROOT) == []``, więc stałe opisują Required CI ``main``, a zmiana
  środowiska Required CI wchodzi osobnym PR przed dowodem, który jej potrzebuje;
- ``pytest_mismatch`` mówi to samo o torze Linux zadania ``PYTEST_JOB``, który powtarza dowód testu (``built``
  z ``tests``): ten sam Python i ta sama instalacja ``CI_INSTALL`` co ``JOB``, zmienne zadania ``PYTEST_VARIABLES``,
  a na Linuksie do kroku pytest włącznie tylko kroki ``_PYTEST_STEPS``; tor Windows (Python 3.13, ``requirements.txt``)
  dowód pomija, więc test, który przechodzi tylko tam, dowód odmawia na drzewie bez zmian.

Odmowa to ``Refused`` (``ValueError``) z tym, co zrobić. Granica: wydanie poprawkowe Pythona (``CI_PYTHON`` bez
poprawki), wersja uv i obraz runnera mogą różnić się od runu Required CI, a pakiety rozwiązują się w chwili dowodu
(repo nie ma pliku blokady, więc dwa runy CI też mogą je rozwiązać inaczej); zmienne runnera (``CI``, ``GITHUB_*``),
które czyta kod PR (wtyczka mypy, backend budowy, testy), dowód ma w jobie ``dowod``, a przy merge'u na Macu nie; Pythona toru
Linux zadania pytest (``zakres_runu.TORY``) z ``CI_PYTHON`` wiąże test, nie ``pytest_mismatch``. Dowód biegnie na Linuksie i macOS (job
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
CI_EXTRAS = ("dev",)
CI_INSTALL = 'uv pip install --system --python "${{ steps.python.outputs.python-path }}" -e ".[' + ",".join(CI_EXTRAS) + ']"'
BUILD_TIMEOUT_S = 300
# ZEWNĘTRZNE: multiprocessing kładzie gniazdo serwera forkserver w TMPDIR/pymp-XXXXXXXX/sock-XXXXXXXXXXXX, a przy długim TMPDIR próbuje /tmp, którego piaskownica nie przyjmuje, więc wraca do TMPDIR, a bind pada, gdy ścieżka ma 104 bajty sun_path macOS albo więcej (Lib/multiprocessing/util.py, _get_base_temp_dir; connection.py, arbitrary_address)
_SOCKET_MAX = 104
_RUN_SOCKET = "/srodowisko-ci-XXXXXXXX/tmp/pymp-XXXXXXXX/sock-XXXXXXXXXXXX"
_SYSTEM_TEMP = Path("/tmp")
_JOB_KEYS = {"name", "runs-on", "steps"}
_INSTALL_ID = "deps"  # ``id`` kroku ``CI_INSTALL``, którego wynik czyta ``_CI_IF``
_CI_IF = "${{ !cancelled() && steps." + _INSTALL_ID + ".outcome == 'success' }}"
_PYTEST = "python -m pytest -q -rs -n 0 -p no:cacheprovider"
# Kroki reguł chwastów za mypy, na których stoi dowód: reguły całego drzewa i zakaz tłumienia reguły ast-grep i zakazu
# ruff komentarzem (ADR 0036), a potem reguły ast-grep na liniach dodanych od bazy runu, które dowód ``ast-grep <id>``
# liczy tą samą funkcją ``odpalenia_ast_grep.on_added_lines``.
_WEED_TESTS = (
    "test_reguly_calego_drzewa_nie_zglaszaja_zadnej_linii",
    "test_kazda_regula_calego_drzewa_jest_w_katalogu_regul",
    "test_zadna_linia_repo_nie_tlumi_reguly_ast_grep",
    "test_zadna_linia_repo_nie_tlumi_zakazu_ruff",
)
_WEED_RULES: dict[str, object] = {"if": _CI_IF, "run": " ".join((_PYTEST, *(f"tests/test_zapadki.py::{test}" for test in _WEED_TESTS)))}
_ADDED_LINES: dict[str, object] = {
    "if": _CI_IF,
    "env": {"MAXIMISEART_ZAPADKA_BAZA": "HEAD^1"},
    "run": f"{_PYTEST} tests/test_zapadki.py::test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo",
}
# Zadanie Required CI z torami pytest (``zakres_runu.TORY``): dowód ``pytest <węzeł>`` powtarza jego tor Linux, czyli
# Pythona ``CI_PYTHON`` z instalacją ``CI_INSTALL`` (to samo środowisko co ``JOB``) i zmienne zadania ``PYTEST_VARIABLES``.
PYTEST_JOB = "pytest"
PYTEST_VARIABLES = {"EXPECTED_PYTHON_VERSION": CI_PYTHON, "PYTHONUTF8": "1"}
_MATRIX_PYTHON = "${{ matrix.python }}"
_PYTEST_ENV = {**PYTEST_VARIABLES, "EXPECTED_PYTHON_VERSION": _MATRIX_PYTHON}
_WINDOWS = "${{ runner.os == 'Windows' }}"
_PYTEST_RUN = "python tools/ci/wykonaj_zadanie.py"  # początek polecenia kroku, który uruchamia pytest zadania
# Kroki zadania ``PYTEST_JOB``, które biegną na Linuksie do kroku ``_PYTEST_RUN`` włącznie (krok z ``if: _WINDOWS`` się
# nie liczy), każdy w całości: ``env``, ``shell`` albo inne polecenie kroku pytest zmienia przebieg testów w Required CI.
_PYTEST_STEPS: list[dict[str, object]] = [
    {"uses": "actions/checkout", "with": {"persist-credentials": False}},
    {"id": "python", "uses": "actions/setup-python", "with": {"python-version": _MATRIX_PYTHON}},
    {"uses": "astral-sh/setup-uv", "with": {"enable-cache": False}},
    {"if": "${{ runner.os == 'Linux' }}", "run": CI_INSTALL},
    {"if": "${{ matrix.przegladarka }}", "uses": "./.github/actions/chromium"},
    {"uses": "actions/download-artifact", "with": {"name": "plan", "path": ".ci-plan"}},
    {"id": "units", "run": f"{_PYTEST_RUN} --plan .ci-plan/plan.json --zadanie ${{{{ matrix.id }}}}"},
]
_PYTEST_HIDDEN_KEYS = ("container", "services", "defaults")
# Zmienne wołającego, których uv i narzędzia dowodu nie dostają: sterują Pythonem, mypy, ruff, pytest, pip i uv,
# środowiskiem wirtualnym albo testami repo (``MAXIMISEART_``) albo dają token GitHuba; ``ci.yml`` żadnej z nich nie
# ustawia (``mismatch``, ``pytest_mismatch``). Miejsce pamięci uv i jego Pythonów wyniku nie zmienia, więc zostaje.
_HIDDEN_PREFIXES = ("PYTHON", "MYPY", "RUFF", "PYTEST_", "MAXIMISEART_", "PIP_", "UV_")
_HIDDEN = {"VIRTUAL_ENV", "CONDA_PREFIX", "GH_TOKEN", "GITHUB_TOKEN"}
_KEPT = {"UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"}


class Refused(ValueError):
    """Odmowa dowodu: środowiska Required CI nie da się zbudować tak, jak buduje je CI; tekst mówi, co zrobić."""


def variables() -> dict[str, str]:
    """Zmienne wołającego dla uv i narzędzi dowodu, bez tych, którymi ``ci.yml`` nie steruje Required CI."""

    return {name: value for name, value in os.environ.items() if name in _KEPT or not (name.startswith(_HIDDEN_PREFIXES) or name in _HIDDEN)}


@contextmanager
def built(root: Path, head: str, target: str, *, tests: bool = False) -> Iterator[Environment]:
    """Środowisko Required CI dla HEAD PR ``head`` scalonego z ``target`` (baza PR; dla PR już scalonego ``main`` sprzed
    jego merge'a), w repozytorium ``root``; znika z końcem bloku. Narzędzia dostają ``HOME`` i ``TMPDIR`` tego
    środowiska, jedyne miejsca obok kopii, w których piaskownica dowodu (``straznik``) pozwala biegowi pisać. Z ``tests``
    to środowisko toru Linux zadania ``PYTEST_JOB``: odmawia też drzewa z różnicą ``pytest_mismatch``, a narzędzia
    dostają zmienne ``PYTEST_VARIABLES``."""

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
    with tempfile.TemporaryDirectory(prefix="srodowisko-ci-", dir=run_root(Path(tempfile.gettempdir()))) as folder:
        home, copy = Path(folder) / "dom", Path(folder) / "drzewo"
        home.mkdir()
        _checkout(root, tree, copy)
        if problems := [*mismatch(copy), *(pytest_mismatch(copy) if tests else [])]:
            raise Refused(
                f"środowisko Required CI: zadanie {JOB} z {WORKFLOW} drzewa PR scalonego z bazą różni się od zadania, które liczy dowód ({'; '.join(problems)}): "
                "zmień środowisko Required CI osobnym PR przed tym, razem z tools/lib/srodowisko_ci.py, bo dowód buduje je kodem bazy"
            )
        python = _install(uv, copy, Path(folder))
        # Narzędzia z pustym HOME, jak na runnerze: bez konfiguracji użytkownika mypy i ruff i bez globalnych wykluczeń gita.
        tools = {name: value for name, value in variables().items() if not name.startswith("XDG_")}
        tools.setdefault("UV_PYTHON_INSTALL_DIR", _built(copy, "uv python dir", (uv, "--no-config", "python", "dir")).strip())
        if tests:
            tools |= PYTEST_VARIABLES
        (temporary := Path(folder) / "tmp").mkdir()
        yield Environment(tree, copy, python, {**tools, "HOME": str(home), "TMPDIR": str(temporary)})


def run_root(temporary: Path) -> Path:
    return temporary if len(str(temporary)) + len(_RUN_SOCKET) < _SOCKET_MAX else _SYSTEM_TEMP


def _checkout(root: Path, commit: str, copy: Path) -> None:
    """Kopia commitu ``commit`` w ``copy`` jak checkout Required CI: osobne repozytorium z obiektami ``root``
    (alternates), bez szablonów, ``info/exclude`` repozytorium ``root`` i konfiguracji gita wołającego, które czytałyby
    checkout (filtry, końce linii) i ruff (wykluczenia)."""

    commands = (
        (root, ("clone", "--quiet", "--shared", "--no-checkout", "--template=", str(root.resolve()), str(copy))),
        (copy, ("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit)),
    )
    for cwd, arguments in commands:
        done = repo.run_git(cwd, *arguments, timeout=BUILD_TIMEOUT_S, isolated=True)
        if done.returncode:
            raise Refused(f"środowisko Required CI: git {arguments[0]} kopii skończył się kodem {done.returncode} ({done.stderr.strip()[-300:]}): uruchom ponownie")


def _twins(root: Path, tree: str) -> list[str]:
    """Ścieżki commitu ``tree``, które różnią się od innej tylko wielkością liter albo normalizacją Unicode (NFC i NFD):
    APFS macOS scala obie, a system plików runnera nie."""

    seen: dict[str, list[str]] = {}
    for path in repo.git(root, "ls-tree", "-r", "-z", "--name-only", tree).split("\0"):
        if path:
            seen.setdefault(repo.folded(path), []).append(path)
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
    """Wszystkie kroki zadania ``JOB`` w jedynej postaci, którą zadanie może mieć, żeby ``built`` i ``straznik`` liczyły
    to, co ono: checkout, setup-python ``CI_PYTHON``, setup-uv, ``CI_INSTALL``, kroki ``kroki_lokalne.static_steps``
    w ich kolejności i kroki reguł chwastów, każdy z warunkiem ``_CI_IF``. Klucz ``name`` i wersja akcji po ``@``
    (podbija ją dependabot) się nie liczą."""

    checks: list[dict[str, object]] = [{"if": _CI_IF, "run": " ".join(("python", *step.ci[1:]))} for step in static_steps(tree)]
    return [
        {"uses": "actions/checkout", "with": {"fetch-depth": 2, "persist-credentials": False}},
        {"id": "python", "uses": "actions/setup-python", "with": {"python-version": CI_PYTHON}},
        {"uses": "astral-sh/setup-uv", "with": {"enable-cache": False}},
        {"id": _INSTALL_ID, "run": CI_INSTALL},
        *checks,
        _WEED_RULES,
        _ADDED_LINES,
    ]


def mismatch(tree: Path) -> list[str]:
    """Czym zadanie ``JOB`` z ``WORKFLOW`` w drzewie ``tree`` różni się od postaci, którą liczy dowód: pierwszy krok różny
    od ``job_steps`` (cała lista na równość, więc też krok dopisany albo brakujący), klucz zadania spoza ``_JOB_KEYS``,
    inny runner, ``env`` i ``defaults`` workflow albo konfiguracja uv."""

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
    for number, (want, have) in enumerate(itertools.zip_longest(job_steps(tree), map(_normal, given)), start=1):
        if want != have:
            problems.append(f"krok {number} zadania to {have!r} zamiast {want!r}")
            break
    return problems


def pytest_mismatch(tree: Path) -> list[str]:
    """Czym tor Linux zadania ``PYTEST_JOB`` z ``WORKFLOW`` w drzewie ``tree`` różni się od toru, który powtarza dowód
    testu: zmienne zadania inne niż ``_PYTEST_ENV``, klucz zadania z ``_PYTEST_HIDDEN_KEYS`` albo kroki do kroku
    ``_PYTEST_RUN`` włącznie, które biegną na Linuksie, inne niż ``_PYTEST_STEPS`` (cała lista na równość, bez ``name``
    i wersji akcji). ``env`` i ``defaults`` workflow zgłasza ``mismatch``."""

    try:
        job = yaml.safe_load((tree / WORKFLOW).read_text(encoding="utf-8"))["jobs"][PYTEST_JOB]
        given = [_normal(step) for step in job["steps"]]
        end = next(number for number, step in enumerate(given) if str(step.get("run", "")).startswith(_PYTEST_RUN))
    except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return [f"brak kroku {_PYTEST_RUN} zadania {PYTEST_JOB} w {WORKFLOW} ({type(error).__name__}: {error})"]
    problems = [f"{key} w zadaniu {PYTEST_JOB}" for key in _PYTEST_HIDDEN_KEYS if key in job]
    if job.get("env") != _PYTEST_ENV:
        problems.append(f"env zadania {PYTEST_JOB} to {job.get('env')!r} zamiast {_PYTEST_ENV!r}")
    linux = [step for step in given[: end + 1] if step.get("if") != _WINDOWS]
    for number, (want, have) in enumerate(itertools.zip_longest(_PYTEST_STEPS, linux), start=1):
        if want != have:
            problems.append(f"krok {number} toru Linux zadania {PYTEST_JOB} do pytest to {have!r} zamiast {want!r}")
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
