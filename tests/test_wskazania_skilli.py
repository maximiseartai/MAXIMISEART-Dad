from __future__ import annotations

from pathlib import Path
import re
from typing import Final

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS: Final = ROOT / ".agents" / "skills"
WORD: Final = r"doc[\s_-]*string\w*"
DOCSTRING_AS_SOURCE: Final = re.compile(
    rf"\b(?:the|its|whose|this|their|jego|jej|ich)\s+(?:(?:module|class|function)\s+)?{WORD}"
    rf"|[\w`.]+'s\s+{WORD}"
    rf"|{WORD}\s+(?:of\s+)?(?:\w+\s+){{0,2}}`"
    r"|__doc__",
    re.IGNORECASE,
)
FIX: Final = (
    "docstringi znikają z kodu (ADR 0043), więc skill nie wskazuje docstringu jako źródła: obietnicę napisz w skillu, "
    "a źródłem zrób test, ADR, GLOSSARY.md, --help albo nazwę w kodzie"
)


def _docstring_sources(text: str) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), start=1) if DOCSTRING_AS_SOURCE.search(line)]


def test_skill_nie_wskazuje_docstringu_jako_zrodla_bo_docstringi_znikaja_z_kodu() -> None:
    files = sorted([*SKILLS.rglob("SKILL.md"), *SKILLS.rglob("konfiguracje.json")])

    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in files
        for line in _docstring_sources(path.read_text(encoding="utf-8"))
    ]

    assert {path.name for path in files} == {"SKILL.md", "konfiguracje.json"}
    assert found == [], f"{FIX}: {found}"


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        pytest.param("Source: the docstring of the class `Reports`.", [1], id="docstring-klasy"),
        pytest.param("(docstring `Reports`: „Sprawa znika od razu”)", [1], id="docstring-nazwy"),
        pytest.param("(docstring of `reconcile`: „wartość ręczna”)", [1], id="docstring-of-nazwy"),
        pytest.param("the docstrings of `explore_outbox.py`, `MemoryBox` and `Scope` say it", [1], id="docstringi-kilku"),
        pytest.param("`StateShape`, whose docstring names its parts", [1], id="whose-docstring"),
        pytest.param("`tools/wydanie.py` (its docstring says what `plan` does)", [1], id="its-docstring"),
        pytest.param("`reference` in `explore.py`; its module docstring states it", [1], id="its-module-docstring"),
        pytest.param("The script's docstring is the reference.", [1], id="script-s-docstring"),
        pytest.param("The docstrings promise, and the model checks:", [1], id="the-docstrings"),
        pytest.param("Źródło: w docstringu `DadCases`.", [1], id="w-docstringu-nazwy"),
        pytest.param("Źródło: docstringu modułu `dad_cases.py`.", [1], id="docstringu-modulu-nazwy"),
        pytest.param("its doc string lists the world", [1], id="doc-string-ze-spacja"),
        pytest.param("`main.__doc__` is the reference", [1], id="atrybut-doc"),
        pytest.param('{\n  "zrodlo": "the docstring of keyed_box"\n}', [2], id="linia-json"),
        pytest.param(
            "- próbka testu, która nie może paść na złej implementacji nazwanej przez test (w nazwie, id przypadku albo "
            "docstringu), bo w świecie próbki nie ma przypadku z obietnicy",
            [],
            id="regula-przegladu-z-bazy-przechodzi",
        ),
        pytest.param(
            "Ważne jest odtworzony przypadek, który według wiersza reguły, docstringu albo opisu PR to sprawdzenie "
            "powinno wywrócić",
            [],
            id="regula-sprawdzenia-z-bazy-przechodzi",
        ),
        pytest.param("(w nazwie, id przypadku albo docstringu, który jeszcze stoi)", [], id="docstring-ktory-stoi-przechodzi"),
        pytest.param("The script's `--help` is the reference for its parameters.", [], id="help-przechodzi"),
        pytest.param("ADR 0019 and `tests/test_podmiana_intermax.py` say it.", [], id="test-i-adr-przechodza"),
    ],
)
def test_wskazanie_docstringu_jako_zrodla_pada_a_regula_o_docstringach_przechodzi(text: str, lines: list[int]) -> None:
    assert _docstring_sources(text) == lines
