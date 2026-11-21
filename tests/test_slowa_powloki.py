from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CIEZKIE = ROOT / "tools" / "hooks" / "ciezkie.py"
CZEKANIE = ROOT / "tools" / "hooks" / "czekanie.py"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"slowa_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HOOKS = {"ciezkie": _load(CIEZKIE), "czekanie": _load(CZEKANIE)}

SLOWA = [
    pytest.param("szybko", "szybko", id="bez-cudzyslowu"),
    pytest.param("'a b'", "a b", id="apostrofy"),
    pytest.param("'a\\b'", "a\\b", id="ukosnik-w-apostrofach-zostaje"),
    pytest.param('"a b"', "a b", id="cudzyslow"),
    pytest.param('"a\\"b"', 'a"b', id="cudzyslow-w-cudzyslowie"),
    pytest.param('"a\\\\b"', "a\\b", id="ukosnik-w-cudzyslowie"),
    pytest.param('"a\\nb"', "a\\nb", id="ukosnik-przed-litera-w-cudzyslowie-zostaje"),
    pytest.param('"a\\$b"', "a$b", id="ucieczka-dolara-w-cudzyslowie"),
    pytest.param('"a\\`b"', "a`b", id="ucieczka-grawisu-w-cudzyslowie"),
    pytest.param("'a\\$b'", "a\\$b", id="ukosnik-przed-dolarem-w-apostrofach-zostaje"),
    pytest.param("szybk\\o", "szybko", id="ucieczka-poza-cudzyslowem"),
    pytest.param("a\\ b", "a b", id="ucieczka-spacji"),
    pytest.param("szyb\\\nko", "szybko", id="kontynuacja-linii-poza-cudzyslowem"),
    pytest.param('"szyb\\\nko"', "szybko", id="kontynuacja-linii-w-cudzyslowie"),
    pytest.param('"a\\\\\nb"', "a\\\nb", id="ukosnik-przed-nowa-linia-w-cudzyslowie"),
    pytest.param("'szyb\\\nko'", "szyb\\\nko", id="kontynuacja-linii-w-apostrofach-zostaje"),
    pytest.param("'x'\"y\"\\z", "xyz", id="sklejone-czesci"),
]


@pytest.mark.parametrize(("slowo", "jak_bash"), SLOWA)
def test_oba_hooki_czytaja_slowo_polecenia_tak_jak_bash_po_rozwinieciu(slowo: str, jak_bash: str) -> None:
    read = {name: hook._words(f"echo {slowo}") for name, hook in HOOKS.items()}

    assert read == {name: ["echo", jak_bash] for name in HOOKS}
