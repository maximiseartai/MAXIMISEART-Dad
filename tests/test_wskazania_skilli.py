from __future__ import annotations

from pathlib import Path
import re
from typing import Final

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS: Final = ROOT / ".agents" / "skills"
DOCSTRING: Final = re.compile(r"doc[\s_-]*string|__doc__", re.IGNORECASE)
FIX: Final = (
    "docstringi znikają z kodu (ADR 0043), więc skill nie wskazuje docstringu: obietnicę napisz w skillu, a źródłem "
    "zrób test, ADR, GLOSSARY.md, --help albo nazwę w kodzie"
)


def _docstring_pointers(text: str) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), start=1) if DOCSTRING.search(line)]


def test_skill_nie_wskazuje_docstringu_bo_docstringi_znikaja_z_kodu() -> None:
    files = sorted([*SKILLS.rglob("SKILL.md"), *SKILLS.rglob("konfiguracje.json")])

    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in files
        for line in _docstring_pointers(path.read_text(encoding="utf-8"))
    ]

    assert {path.name for path in files} == {"SKILL.md", "konfiguracje.json"}
    assert found == [], f"{FIX}: {found}"


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        pytest.param("Source: the docstring of the class `Reports`.", [1], id="docstring-of"),
        pytest.param("`StateShape`, whose docstring names its parts", [1], id="whose-docstring"),
        pytest.param("The docstrings promise, and the model checks:", [1], id="liczba-mnoga"),
        pytest.param("nazwanej przez test (w nazwie albo docstringu)", [1], id="polska-odmiana"),
        pytest.param("Its Docstring says what `plan` does.", [1], id="wielka-litera"),
        pytest.param("its doc string lists the world", [1], id="ze-spacja"),
        pytest.param("`main.__doc__` is the reference", [1], id="atrybut-doc"),
        pytest.param('{\n  "zrodlo": "docstring of keyed_box"\n}', [2], id="linia-json"),
        pytest.param("The script's `--help` is the reference for its parameters.", [], id="help-przechodzi"),
        pytest.param("ADR 0019 and `tests/test_podmiana_intermax.py` say it.", [], id="test-i-adr-przechodza"),
        pytest.param("the documentation of the Skrzynka", [], id="documentation-przechodzi"),
    ],
)
def test_wskazanie_docstringu_lapie_kazda_postac_slowa_a_inne_zrodla_przechodza(text: str, lines: list[int]) -> None:
    assert _docstring_pointers(text) == lines
