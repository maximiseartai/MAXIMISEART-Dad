"""Rejestr ADR w ``docs/adr/``: numer pliku jednoznacznie wskazuje decyzję."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

ADR_DIRECTORY = Path(__file__).resolve().parents[1] / "docs" / "adr"


def _number(path: Path) -> str:
    return path.name.split("-", 1)[0]


def test_numery_plikow_adr_sa_unikalne() -> None:
    numbers = Counter(_number(path) for path in ADR_DIRECTORY.glob("*.md"))

    assert numbers
    assert {number: count for number, count in numbers.items() if count > 1} == {}, (
        "numer ADR jest unikalny: nadaj nowemu plikowi następny wolny numer i popraw odsyłacze do niego"
    )


def test_naglowek_adr_ma_numer_pliku() -> None:
    headings = {path: path.read_text(encoding="utf-8").splitlines()[0] for path in ADR_DIRECTORY.glob("*.md")}

    assert {
        path.name: heading for path, heading in headings.items() if not heading.startswith(f"# ADR {_number(path)}:")
    } == {}, "pierwsza linia ADR to „# ADR <numer z nazwy pliku>: <tytuł>”: popraw nagłówek albo numer w nazwie pliku"
