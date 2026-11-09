"""Kroki sprawdzeń, które biegną lokalnie tak jak w CI (ruff, mypy obu systemów, pytest), i środowisko kodu drzewa.

Kroki ruff i mypy (``static_steps``) to brama pre-push i zadanie CI „Ruff, mypy”: biegną nimi ``tools/ci_lokalnie.py``,
``tools/szybko.py`` i brama typów mutacji (``tools/lib/silnik_mutacji.py``). Krok pytest (``pytest_step``) to ten sam pytest, który
``tools/ci_lokalnie.py`` uruchamia w całości, a ``tools/szybko.py`` z wybranymi testami.

``environment`` to środowisko procesu, który uruchamia kod drzewa ``root`` (checkoutu albo jego kopii): edytowalna
instalacja ``.venv`` wskazuje ``src`` checkoutu, więc ``src`` drzewa stoi na ``PYTHONPATH`` przed nią.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

from jednostka import ZMIENNA_CZESCI

# Tyle ostatnich linii wyjścia kroku, który padł, drukują ``tools/ci_lokalnie.py`` i ``tools/szybko.py``.
OUTPUT_ON_FAILURE = 40


@dataclass(frozen=True)
class Step:
    name: str
    job: str  # zadanie ``tools/ci_lokalnie.py``, w którym krok biegnie
    command: tuple[str, ...]
    cwd: Path


def static_steps(root: Path) -> list[Step]:
    """Kroki ruff i mypy obu systemów w ``root``, w kolejności bramy pre-push."""

    python = sys.executable
    return [
        Step("ruff", "ruff", (python, "-m", "ruff", "check"), root),
        # Gałęzie innych systemów niż Windows sprawdza mypy systemu, na którym biegnie; CI biegnie na Linuksie.
        Step("mypy", "mypy", (python, "-m", "mypy"), root),
        # Gałęzie tylko dla Windows używają API, którego inne systemy nie mają.
        # Własny cache, bo zmiana --platform unieważnia wspólny i oba kroki sprawdzałyby za każdym razem całość.
        Step("mypy (Windows)", "mypy", (python, "-m", "mypy", "--platform", "win32", "--cache-dir", ".mypy_cache/win32"), root),
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
