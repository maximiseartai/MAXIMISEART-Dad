"""Treści dla testów rejestru korzeni i issues „Chwast: R-KOD” (ADR 0031, decyzje Q11, Q12, Q15, Q22) z HTML
z renderera GitHuba: werdykty z kodami, komentarze ze zgodą Maksa, opis PR, który wyrywa chwast, i treść issue chwastu.

Wymagania bierzemy z ADR 0031 i decyzji Maksa: chwast to kod z Ważnym w co najmniej 2 różnych PR-ach, issue ma
sekcje „Korzeń”, „Wystąpienia” z tabelą PR | Ważne | Szczebel wyrwania | Mechanizm i „Gotowe, gdy”, zgoda Maksa
na powrót po szczeblu (a) to linia ``ZGODA KORZEŃ: R-KOD``, a issue zamyka PR z linią ``Korzeń z #<issue>: R-KOD``.
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
DESCRIPTION = "Nowa reguła albo gałąź kodu bez testu zachowania, który ją rozstrzyga (przeżyta mutacja albo przypadek bez próbki)."
TABLE = "| PR | Ważne | Szczebel wyrwania | Mechanizm |"


def _lines(*lines: str) -> str:
    return "\n".join(lines)


def _major(number: int, code: str) -> tuple[str, ...]:
    return (f"### W{number}. Brak testu.", "Gdzie: kod/inne.py:1", "Dowód: tools/mutacje.py: NIEWYKRYTA", f"Korzeń: {code} - gałąź bez testu.", "Szczebel: (c) - test zachowania.")


# Treści werdyktów pod dwiema pierwszymi liniami.
WERDYKTY = {
    "dwa-wazne-z-tym-samym-kodem": _lines(*_major(1, CODE), *_major(2, CODE), "## Sprawdzone", "- diff"),
    "inny-kod": _lines(*_major(1, "R-DRUGA-DROGA"), "## Sprawdzone", "- diff"),
    "potwierdza-kod": _lines("## Sprawdzone", f"- Korzeń W1 r1: {CODE} - brak testu zachowania.", "- diff"),
}
ZGODY = {
    "zgoda": f"ZGODA KORZEŃ: {CODE}",
    "zgoda-w-bloku-kodu": _lines("```", f"ZGODA KORZEŃ: {CODE}", "```"),
    "zgoda-na-inny-kod": "ZGODA KORZEŃ: R-DRUGA-DROGA",
}
OPISY = {
    "wyrywa-chwast": opisy_pr.wzor(f"Korzeń z #{WEED_ISSUE}: {CODE}"),
}


def _issue(*rows: str) -> str:
    """Treść issue chwastu w szablonie Q15 z wierszami tabeli „Wystąpienia” ``rows``."""

    return _lines(
        "## Korzeń",
        "",
        f"{CODE}: {DESCRIPTION}",
        "",
        "## Wystąpienia",
        "",
        TABLE,
        "| --- | --- | --- | --- |",
        *rows,
        "",
        "## Gotowe, gdy",
        "",
        f"- PR z linią „Korzeń z #N: {CODE}” w opisie, gdzie N to numer tego issue, wyrywa korzeń szczebel wyżej niż najwyższy w tabeli (ADR 0031, Q11), a tools/scal_pr.py zamyka to issue przy merge'u tego PR.",
        "",
    )


OTHER_ROW = f"| #{OTHER} | W1 r1 | (b) | reguła ruff. |"
# Treść otwartego issue chwastu z jednym wystąpieniem w #1436, w szablonie Q15.
ISSUE = _issue(OTHER_ROW)
ISSUES = {
    "w-szablonie": ISSUE,
    "z-proza": f"{ISSUE}\nUwaga dopisana ręcznie.\n",
    # issue, które zakłada publikacja werdyktu na PR 1, gdy #1436 ma to samo Ważne ze szczeblem (b)
    "zalozone-z-pr-1": _issue("| #1 | W1 r1 | - | - |", OTHER_ROW),
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

    return [*WERDYKTY.values(), *ZGODY.values(), *OPISY.values(), *ISSUES.values()]


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
