"""Pliki drzewa, z którego ``srodowisko_ci.built`` buduje w teście środowisko Required CI dowodu strażnika: ``ci.yml``
repozytorium i ``pyproject.toml`` projektu bez pakietów z pinami mypy, ruff i ast-grep z dodatku dev repozytorium."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tomllib

import pytest

import srodowisko_ci

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / srodowisko_ci.WORKFLOW).read_text(encoding="utf-8")
PINS = tuple(
    pin
    for pin in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]["dev"]
    if pin.startswith(("mypy==", "ruff==", "ast-grep-cli=="))
)

wymaga_uv = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("uv") is None,
    reason="środowisko Required CI dowodu buduje uv na Linuksie i macOS (srodowisko_ci.built)",
)


def project(*dependencies: str, dev: tuple[str, ...] = (), tools: str = "") -> dict[str, str]:
    """``pyproject.toml`` z zależnościami ``dependencies``, dodatkiem dev z ``PINS`` i ``dev`` oraz ustawieniami narzędzi
    ``tools`` i ``ci.yml`` repozytorium."""

    listed = ", ".join(f'"{one}"' for one in dependencies)
    extras = ", ".join(f'"{one}"' for one in (*PINS, *dev))
    text = (
        '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n'
        f'[project]\nname = "proba"\nversion = "0"\ndependencies = [{listed}]\n\n'
        f"[project.optional-dependencies]\ndev = [{extras}]\nworkflowy = []\n\n"
        f"[tool.setuptools]\npackages = []\n\n{tools}"
    )
    return {"pyproject.toml": text, srodowisko_ci.WORKFLOW: CI}
