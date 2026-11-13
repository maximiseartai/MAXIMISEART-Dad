"""Opisy PR z sekcją ``## Korzeń``, opisy PR korzenia, sekcje skilla ``przeglad`` i treści werdyktów z punktem
rozstrzygnięcia kodu, z HTML z renderera GitHuba, dla testów bramki korzenia ``tools/scal_pr.py`` (ADR 0031).

Wymagania bierzemy z ADR 0031, wzoru sekcji „Root section” skilla ``pr`` i decyzji Q8, Q10, Q14, Q17, Q18, Q20, Q25
i Q26: blok ``### W<n> r<k>: R-KOD`` na każde Ważne werdyktów ``FAIL``, ``Szczebel``, ``Wyżej nie, bo`` z linią na
każdy wyższy szczebel, ``Dowód``, ``Wyrwany w #M`` z PR-em korzenia, który ma linię ``Korzeń z #N: R-KOD``, blok
``### Czerwony main #N: R-KOD`` i punkt w „Co jest porażką” przy szczeblu (e). Numery to prawdziwe PR-y i issues
tego repo, bo renderer linkuje tylko istniejące i odróżnia issue od PR po stanie na GitHubie: #1 i #1436 to PR-y,
#1456 issue czerwonego `main`, #1485 issue flaky testu, #1457 PR przykładu innego PR w skillu. Testy biegną na PR 1 jako PR
z funkcją, a #1436 udaje PR korzenia.

``korzenie_pr.json`` trzyma HTML każdej treści z ``gh api markdown`` (``mode=gfm``, ``context`` to ``REPO``), a testy
podają go zamiast GitHuba, więc biegną bez sieci. Po zmianie treści w tym pliku odśwież plik (jedno wywołanie ``gh``
na treść, po kolei):

    .venv/bin/python -m tests.fixtures.korzenie_pr
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import subprocess

from tests.fixtures import opisy_pr

REPO = opisy_pr.REPO
RENDERED = Path(__file__).with_name("korzenie_pr.json")
FEATURE = 1
ROOT_PR = 1436
RED_MAIN = 1456
FLAKY = 1485
EVIDENCE = "Dowód: tools/mutacje.py --test tests/test_x.py: MUTACJE OK"


def _lines(*lines: str) -> str:
    return "\n".join(lines)


def body(*blocks: str, why: str = "Cel.") -> str:
    """Opis PR z nagłówkami wzoru skilla ``pr`` i sekcją ``## Korzeń`` z ``blocks`` przed ``## Merge Danger``; bez
    ``blocks`` bez sekcji."""

    sections = opisy_pr.wzor(why).split("## Merge Danger")
    root = _lines("## Korzeń", "", "\n\n".join(blocks), "", "") if blocks else ""
    return f"{sections[0]}{root}## Merge Danger{sections[1]}"


C_BLOCK = _lines(
    "### W1 r1: R-BEZ-TESTU",
    "Szczebel: (c) - test zachowania łapie klasę.",
    "Wyżej nie, bo:",
    "(a) - nie ma drugiej drogi do usunięcia.",
    "(b) - typ nie wyrazi tej reguły.",
    EVIDENCE,
)
OPISY = {
    "bez-sekcji": body(),
    "szczebel-c": body(C_BLOCK),
    "szczebel-a": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", EVIDENCE)),
    "szczebel-b-wyzej-w-linii-pola": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (b) - reguła ruff.", "Wyżej nie, bo: (a) - nie ma drugiej drogi.", EVIDENCE)),
    "inny-kod": body(C_BLOCK.replace("R-BEZ-TESTU", "R-DRUGA-DROGA")),
    "nowy-kod": body(C_BLOCK.replace("R-BEZ-TESTU", "R-NOWY-KOD")),
    "blok-innego-waznego": body(C_BLOCK.replace("W1 r1", "W2 r1")),
    "blok-dwa-razy": body(C_BLOCK, C_BLOCK),
    "szczebel-c-bez-wyzej-nie": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (c) - test zachowania.", EVIDENCE)),
    "szczebel-c-bez-zdania-dla-b": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (c) - test zachowania.", "Wyżej nie, bo:", "(a) - nie ma drugiej drogi.", EVIDENCE)),
    "szczebel-a-z-wyzej-nie": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", "Wyżej nie, bo: (a) - nic.", EVIDENCE)),
    "bez-dowodu": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.")),
    "bez-szczebla": body(_lines("### W1 r1: R-BEZ-TESTU", EVIDENCE)),
    "szczebel-e": body(
        _lines(
            "### W1 r1: R-BEZ-TESTU",
            "Szczebel: (e) - punkt w „Co jest porażką”.",
            "Wyżej nie, bo:",
            "(a) - nie ma drugiej drogi.",
            "(b) - typ nie wyrazi reguły.",
            "(c) - test nie złapie klasy.",
            "(d) - wzorzec nie jest powszechny.",
            "Dowód: diff skilla przeglad.",
        )
    ),
    "cytat-pola-w-bloku-kodu": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", "Dowód: odmowa:", "```", "### W1 r1: R-DRUGA-DROGA", "Szczebel: (e) - cytat", "```")),
    "cytat-pola-bez-bloku-kodu": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", "Dowód: odmowa:", "", "### W1 r1: R-DRUGA-DROGA", "Szczebel: (e) - cytat")),
    "wyrwany": body(_lines("### W1 r1: R-BEZ-TESTU", f"Wyrwany w #{ROOT_PR}")),
    "wyrwany-z-dowodem": body(_lines("### W1 r1: R-BEZ-TESTU", f"Wyrwany w #{ROOT_PR}", EVIDENCE)),
    "wyrwany-bez-linku": body(_lines("### W1 r1: R-BEZ-TESTU", "Wyrwany w #9999999")),
    "wyrwany-w-issue": body(_lines("### W1 r1: R-BEZ-TESTU", f"Wyrwany w #{RED_MAIN}")),
    "czerwony-main-bez-sekcji": body(why=f"Część #{RED_MAIN}"),
    "czerwony-main": body(_lines(f"### Czerwony main #{RED_MAIN}: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", EVIDENCE), why=f"Część #{RED_MAIN}"),
    "czerwony-main-kod-spoza-listy": body(_lines(f"### Czerwony main #{RED_MAIN}: R-WYMYSLONY-KOD", "Szczebel: (a) - jeden właściciel.", EVIDENCE), why=f"Część #{RED_MAIN}"),
    "flaky-test": body(why=f"Część #{FLAKY}"),
    "kod-rozstrzygniety": body(C_BLOCK.replace("R-BEZ-TESTU", "R-DRUGA-DROGA")),
    "proza-w-sekcji": body("Korzeń wyrwany w tym PR.", C_BLOCK),
    "naglowek-poza-wzorem": body(C_BLOCK.replace("### W1 r1: R-BEZ-TESTU", "### W1: R-BEZ-TESTU")),
    "dowod-6-linii": body(_lines("### W1 r1: R-BEZ-TESTU", "Szczebel: (a) - jeden właściciel.", EVIDENCE, *(f"linia {number}" for number in range(2, 7)))),
}
PR_KORZENIA = {
    "ten-kod": opisy_pr.wzor(f"Korzeń z #{FEATURE}: R-BEZ-TESTU"),
    "inny-kod": opisy_pr.wzor(f"Korzeń z #{FEATURE}: R-DRUGA-DROGA"),
    "inny-pr": opisy_pr.wzor(f"Korzeń z #{ROOT_PR}: R-BEZ-TESTU"),
}
_FAILURES = ("# Przegląd", "", "## Co jest porażką", "", "- Punkt bez przykładu.")
SKILL = {
    "baza": _lines(*_FAILURES, "", "## Dowody", "", "Tekst.", ""),
    "punkt-z-przykladem": _lines(*_FAILURES, "- Nowy punkt z przykładem #1457.", "", "## Dowody", "", "Tekst.", ""),
    "punkt-bez-przykladu": _lines(*_FAILURES, "- Nowy punkt bez przykładu.", "", "## Dowody", "", "Tekst.", ""),
    "punkt-z-przykladem-poza-sekcja": _lines(*_FAILURES, "", "## Dowody", "", "- Punkt z przykładem #1457.", ""),
    "punkt-z-linkiem-do-pr": _lines(*_FAILURES, f"- Nowy punkt z przykładem #{FEATURE}.", "", "## Dowody", "", "Tekst.", ""),
    "punkt-z-przykladem-zmieniony-z-linkiem-do-pr": _lines(*_FAILURES, f"- Nowy punkt z przykładem #1457 i #{FEATURE}.", "", "## Dowody", "", "Tekst.", ""),
    "punkt-z-linkiem-do-pr-i-zmieniony-punkt-bazy": _lines(
        "# Przegląd", "", "## Co jest porażką", "", "- Punkt bez przykładu, przeredagowany.", f"- Nowy punkt z przykładem #{FEATURE}.", "", "## Dowody", "", "Tekst.", ""
    ),
    "punkty-bazy-zamienione-z-linkiem-do-pr": _lines(
        "# Przegląd", "", "## Co jest porażką", "", "- Nowy punkt z przykładem #1457.", "- Punkt bez przykładu.", f"- Nowy punkt z przykładem #{FEATURE}.", "", "## Dowody", "", "Tekst.", ""
    ),
}
# Treści werdyktów pod dwiema pierwszymi liniami: punkt rozstrzygnięcia kodu w „## Sprawdzone” (decyzja Q25).
WERDYKTY = {
    "rozstrzyga-w1-r1": _lines("## Sprawdzone", "- Korzeń W1 r1: R-DRUGA-DROGA - druga droga, nie brak testu.", "- diff"),
    "rozstrzyga-nowym-kodem": _lines("## Sprawdzone", "- Korzeń W1 r1: NOWY R-NOWY-KOD - opis kodu spoza listy.", "- diff"),
    "rozstrzyga-kodem-spoza-listy": _lines("## Sprawdzone", "- Korzeń W1 r1: R-NIE-MA - kod spoza listy.", "- diff"),
    "rozstrzygniecie-bez-rundy": _lines("## Sprawdzone", "- Korzeń W1: R-DRUGA-DROGA - bez rundy.", "- diff"),
    "wazne-bez-korzenia": "- Ważne: brak testu, opisane prozą.",
}


@functools.cache
def _saved() -> dict[str, str]:
    saved: dict[str, str] = json.loads(RENDERED.read_text(encoding="utf-8"))
    return saved


def rendered() -> dict[str, str]:
    """HTML z renderera GitHuba dla każdej treści z ``korzenie_pr.json``."""

    return dict(_saved())


def html(text: str) -> str:
    return _saved()[text]


def bodies() -> list[str]:
    """Treści, których HTML muszą mieć testy."""

    return [*OPISY.values(), *PR_KORZENIA.values(), *SKILL.values(), *WERDYKTY.values()]


def _refresh() -> None:
    saved = {}
    for text in dict.fromkeys(bodies()):
        request = json.dumps({"text": text, "mode": "gfm", "context": REPO})
        saved[text] = subprocess.run(
            ["gh", "api", "markdown", "--input", "-"], input=request, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60
        ).stdout
    RENDERED.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"KORZENIE PR OK | {len(saved)} treści w {RENDERED.name}")


if __name__ == "__main__":
    _refresh()
