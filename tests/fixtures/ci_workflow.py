"""Zadania ``.github/workflows/ci.yml`` tak, jak GitHub Actions rozwija ich macierz, i akcje złożone z ``.github/actions/``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

GITHUB = Path(__file__).resolve().parents[2] / ".github"
WORKFLOW = GITHUB / "workflows" / "ci.yml"
# Akcja złożona, która instaluje Chromium dla Playwright w każdym zadaniu, które prowadzi przeglądarkę.
CHROMIUM = "./.github/actions/chromium"


def jobs() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return loaded


def action(uses: str) -> dict[str, Any]:
    """Plik ``action.yml`` akcji złożonej, którą krok woła jako ``uses: ./.github/actions/<nazwa>``."""

    loaded: dict[str, Any] = yaml.safe_load((GITHUB.parent / uses / "action.yml").read_text(encoding="utf-8"))
    return loaded


def chromium(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job.get("steps", []) if step.get("uses") == CHROMIUM]


def combinations(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    """Kombinacje macierzy GitHub Actions: iloczyn list, bez ``exclude``, z ``include``."""

    axes = {key: values for key, values in matrix.items() if key not in ("include", "exclude")}
    chosen: list[dict[str, Any]] = [{}]
    for key, values in axes.items():
        chosen = [{**combination, key: value} for combination in chosen for value in values]
    for excluded in matrix.get("exclude", []):
        chosen = [c for c in chosen if any(c.get(key) != value for key, value in excluded.items())]
    for extra in matrix.get("include", []):
        matching = [c for c in chosen if all(c[key] == value for key, value in extra.items() if key in axes)]
        for combination in matching:
            combination.update({key: value for key, value in extra.items() if key not in axes})
        if not matching:
            chosen.append(dict(extra))
    return chosen
