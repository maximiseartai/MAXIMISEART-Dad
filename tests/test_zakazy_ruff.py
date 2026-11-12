"""Zakaz ruff z ``pyproject.toml`` obowiązuje też w katalogu, który ma własny ``ruff.toml`` z zakazami.

Ruff bierze tabelę ``banned-api`` (``TID251``) z najbliższego pliku konfiguracji w całości, zamiast dokładać ją do tabeli
pliku, który ten rozszerza (``extend``), więc katalog z własnymi zakazami powtarza każdy zakaz z ``pyproject.toml``.
Bez tego zakaz z ``pyproject.toml``, np. ``os.name``, w takim katalogu po cichu przestaje obowiązywać.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Każdy ruff.toml repozytorium, literałem, żeby tools/szybko.py wybierał ten test przy zmianie któregoś z nich.
DIRECTORY_CONFIGS = (
    ROOT / "src" / "ruff.toml",
    ROOT / "tests" / "ruff.toml",
    ROOT / ".agents" / "skills" / "verify-centrum-rozliczen" / "scripts" / "drive" / "ruff.toml",
)
# Katalogi, które ruff sprawdza (``include`` w ``pyproject.toml``), i nazwy plików konfiguracji ruff.
CHECKED = ("src", "tests", "tools", ".agents/skills")
NAMES = ("ruff.toml", ".ruff.toml")


def _banned(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("flake8-tidy-imports", {}).get("banned-api", {}))


def test_katalog_z_wlasnymi_zakazami_ruff_powtarza_kazdy_zakaz_z_pyproject() -> None:
    found = {path for top in CHECKED for name in NAMES for path in (ROOT / top).rglob(name)}
    found |= {ROOT / name for name in NAMES if (ROOT / name).exists()}
    assert found == set(DIRECTORY_CONFIGS), "dopisz nowy ruff.toml do DIRECTORY_CONFIGS w tests/test_zakazy_ruff.py"

    root = _banned(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"])
    problems = []
    for path in DIRECTORY_CONFIGS:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        where = path.relative_to(ROOT).as_posix()
        if (path.parent / config.get("extend", "")).resolve() != ROOT / "pyproject.toml":
            problems.append(f"{where}: extend nie wskazuje pyproject.toml repozytorium")
        local = _banned(config.get("lint", {}))
        problems += [f"{where}: brak zakazu {name} z pyproject.toml" for name, entry in root.items() if local.get(name) != entry]

    assert problems == [], "\n".join(
        [*problems, "ruff bierze banned-api z najbliższego pliku konfiguracji w całości: skopiuj tam wpis z pyproject.toml"]
    )
