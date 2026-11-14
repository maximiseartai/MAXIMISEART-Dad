"""Treści dla testów rejestru korzeni (ADR 0031, decyzje Q13, Q22, Q25) z HTML z renderera GitHuba: werdykty z kodami
i opis PR z linią „Korzeń z #<issue>: R-KOD”, którą merge zamyka otwarte issue „Chwast: R-KOD”.

Numery to prawdziwe PR-y i issues tego repo, bo renderer linkuje tylko istniejące: #1436 udaje PR z wcześniejszym
wystąpieniem kodu, a #1485 (issue) udaje issue chwastu.

``chwasty.json`` trzyma HTML każdej treści z ``gh api markdown`` (``mode=gfm``, ``context`` to ``REPO``), a testy
podają go zamiast GitHuba, więc biegną bez sieci. Po zmianie treści w tym pliku odśwież plik (jedno wywołanie ``gh``
na treść, po kolei):

    .venv/bin/python -m tests.fixtures.chwasty
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import subprocess

from tests.fixtures import opisy_pr

REPO = opisy_pr.REPO
RENDERED = Path(__file__).with_name("chwasty.json")
OTHER = 1436
WEED_ISSUE = 1485
CODE = "R-BEZ-TESTU"


def _lines(*lines: str) -> str:
    return "\n".join(lines)


def _major(number: int, code: str) -> tuple[str, ...]:
    return (f"### W{number}. Brak testu.", "Gdzie: kod/inne.py:1", "Dowód: tools/mutacje.py: NIEWYKRYTA", f"Korzeń: {code} - gałąź bez testu.", "Szczebel: (c) - test zachowania.")


# Treści werdyktów pod dwiema pierwszymi liniami.
WERDYKTY = {
    "dwa-wazne-z-tym-samym-kodem": _lines(*_major(1, CODE), *_major(2, CODE), "## Sprawdzone", "- diff"),
    "inny-kod": _lines(*_major(1, "R-DRUGA-DROGA"), "## Sprawdzone", "- diff"),
}
OPISY = {
    "wyrywa-chwast": opisy_pr.wzor(f"Korzeń z #{WEED_ISSUE}: {CODE}"),
}


@functools.cache
def _saved() -> dict[str, str]:
    saved: dict[str, str] = json.loads(RENDERED.read_text(encoding="utf-8"))
    return saved


def rendered() -> dict[str, str]:
    """HTML z renderera GitHuba dla każdej treści z ``chwasty.json``."""

    return dict(_saved())


def bodies() -> list[str]:
    """Treści, których HTML muszą mieć testy."""

    return [*WERDYKTY.values(), *OPISY.values()]


def _refresh() -> None:
    saved = {}
    for text in dict.fromkeys(bodies()):
        request = json.dumps({"text": text, "mode": "gfm", "context": REPO})
        saved[text] = subprocess.run(
            ["gh", "api", "markdown", "--input", "-"], input=request, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60
        ).stdout
    RENDERED.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"CHWASTY OK | {len(saved)} treści w {RENDERED.name}")


if __name__ == "__main__":
    _refresh()
