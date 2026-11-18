"""Kroki sprawdzeń, które biegną lokalnie tak jak w CI (ruff, mypy obu systemów, pytest), i środowisko kodu drzewa.

Kroki ruff i mypy (``static_steps``) to brama pre-push i polecenia zadania CI „Ruff, mypy” na każdej maszynie: mypy
biegnie raz dla każdej platformy z ``MYPY_PLATFORMS``, jedynej listy platform mypy, a ``srodowisko_ci.mismatch``
(na ``main`` w ``tests/test_srodowisko_ci.py``, w dowodzie strażnika na drzewie PR) pilnuje, że każdy krok zaczyna się
poleceniem ruff albo mypy zadania „Ruff, mypy” z ``ci.yml``, a każde takie polecenie ma krok. Biegną nimi
``tools/ci_lokalnie.py``, ``tools/szybko.py``, brama typów mutacji (``tools/lib/silnik_mutacji.py``) i dowód strażnika ``mypy`` i ``ruff`` (``tools/lib/straznik.py``), więc zmiana listy
zmienia je wszystkie naraz. Diagnostyki kroku w JSON (opcje ``JSON_OUTPUT``) czyta ``diagnostics``. Kroki zizmor, actionlint i shellcheck akcji złożonych (``workflow_steps``) sprawdzają
``.github/`` w tym samym zadaniu CI, a lokalnie biegną nimi ``tools/ci_lokalnie.py`` i ``tools/szybko.py``. Krok pytest
(``pytest_step``) to ten sam pytest, który ``tools/ci_lokalnie.py`` uruchamia w całości, a ``tools/szybko.py``
z wybranymi testami.

``environment`` to środowisko procesu, który uruchamia kod drzewa ``root`` (checkoutu albo jego kopii): edytowalna
instalacja ``.venv`` wskazuje ``src`` checkoutu, więc ``src`` drzewa stoi na ``PYTHONPATH`` przed nią.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig

from jednostka import ZMIENNA_CZESCI

# Tyle ostatnich linii wyjścia kroku, który padł, drukują ``tools/ci_lokalnie.py`` i ``tools/szybko.py``.
OUTPUT_ON_FAILURE = 40
# Platformy, dla których Required CI sprawdza mypy (``.github/workflows/ci.yml``, zadanie „Ruff, mypy”), i nazwa kroku
# każdej. Mypy systemu maszyny pominąłby na Macu gałąź tylko dla Linuksa, a przyjął gałąź tylko dla macOS (#2116 r5 W1).
MYPY_PLATFORMS = {"linux": "mypy", "win32": "mypy (Windows)"}
# Opcje, z którymi krok ruff albo mypy (``Step.job``) drukuje diagnostyki w JSON, które czyta ``diagnostics``.
JSON_OUTPUT = {"ruff": ("--output-format", "json"), "mypy": ("--output", "json")}


@dataclass(frozen=True)
class Step:
    name: str
    job: str  # zadanie ``tools/ci_lokalnie.py``, w którym krok biegnie
    command: tuple[str, ...]
    cwd: Path


def static_steps(root: Path, python: str = sys.executable) -> list[Step]:
    """Kroki ruff i mypy każdej platformy ``MYPY_PLATFORMS`` w ``root``, w kolejności bramy pre-push, Pythonem ``python``
    (dowód strażnika: Pythonem środowiska Required CI z ``srodowisko_ci.built``)."""

    # Własny cache każdej platformy, bo zmiana --platform unieważnia wspólny i kroki sprawdzałyby za każdym razem całość.
    mypy = (
        Step(name, "mypy", (python, "-m", "mypy", "--platform", platform, "--cache-dir", f".mypy_cache/{platform}"), root)
        for platform, name in MYPY_PLATFORMS.items()
    )
    return [Step("ruff", "ruff", (python, "-m", "ruff", "check"), root), *mypy]


@dataclass(frozen=True)
class Diagnostic:
    """Diagnostyka kroku ruff albo mypy z wyjścia w JSON."""

    path: str  # plik względem korzenia drzewa, gdy w nim leży, z ``/``
    line: int
    code: str | None  # kod reguły; None, gdy narzędzie go nie podało
    message: str


def diagnostics(job: str, output: str, root: Path) -> list[Diagnostic]:
    """Diagnostyki kroku narzędzia ``job`` (``ruff``: lista obiektów, ``mypy``: obiekt w każdej linii, tylko błędy) z wyjścia
    z opcjami ``JSON_OUTPUT``, uruchomionego w drzewie ``root``; wyjście, którego nie da się przeczytać, nie daje żadnej."""

    if job == "ruff":
        try:
            return [Diagnostic(_relative(item["filename"], root), int(item["location"]["row"]), item["code"], item["message"]) for item in json.loads(output)]
        except (ValueError, KeyError, TypeError):
            return []
    found = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
            if item["severity"] == "error":
                found.append(Diagnostic(_relative(item["file"], root), int(item["line"]), item["code"], item["message"]))
        except (ValueError, KeyError, TypeError):
            continue
    return found


def _relative(name: str, root: Path) -> str:
    """Ścieżka pliku diagnostyki z ``/``: względem ``root``, gdy w nim leży (ruff podaje bezwzględną, mypy względną)."""

    path = Path(name) if Path(name).is_absolute() else root / name
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(name).as_posix()


def workflow_steps(root: Path) -> list[Step]:
    """Kroki zizmor, actionlint z shellcheckiem (``.github/workflows``) i shellcheck skryptów akcji złożonych
    (``.github/actions``, których actionlint nie czyta) w ``root``, jak w zadaniu CI „Ruff, mypy”, narzędziami z dodatku
    ``workflowy`` w katalogu skryptów Pythona, który je uruchamia; bez narzędzia krok pada z poleceniem, które je instaluje."""

    scripts = sysconfig.get_path("scripts")
    zizmor, actionlint, shellcheck = (shutil.which(name, path=scripts) for name in ("zizmor", "actionlint", "shellcheck"))
    missing = f"brak narzędzi w {scripts}: uruchom python3 tools/setup_worktree.py (dodatek workflowy)"
    fails = (sys.executable, "-c", f"raise SystemExit({missing!r})")
    return [
        Step("zizmor", "workflowy", (zizmor, "--offline", "--min-severity", "low", ".github") if zizmor else fails, root),
        Step("actionlint", "workflowy", (actionlint, "-shellcheck", shellcheck) if actionlint and shellcheck else fails, root),
        Step(
            "shellcheck akcji",
            "workflowy",
            (sys.executable, "tools/ci/shellcheck_akcji.py", "--shellcheck", shellcheck) if shellcheck else fails,
            root,
        ),
    ]


def pytest_step(root: Path, name: str = "pytest", arguments: tuple[str, ...] = ()) -> Step:
    return Step(name, "pytest", (sys.executable, "-m", "pytest", "-q", "-n", "auto", *arguments), root)


def environment(root: Path, *, concurrent: bool = False) -> dict[str, str]:
    """Środowisko procesu z kodem drzewa ``root``; z ``concurrent`` jego ``pytest -n auto`` ma jednego workera xdist, chyba
    że wywołujący ustawił ``PYTEST_XDIST_AUTO_NUM_WORKERS``."""

    nested = {"PYTEST_XDIST_AUTO_NUM_WORKERS": "1"} if concurrent else {}
    # Część dzieli tabelę skryptu mutacji skilla, nie tabele, które sprawdzane polecenie samo uruchamia.
    inherited = {name: value for name, value in os.environ.items() if name != ZMIENNA_CZESCI}
    return {
        **nested,
        **inherited,
        "PYTHONPATH": os.pathsep.join([str(root / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }
