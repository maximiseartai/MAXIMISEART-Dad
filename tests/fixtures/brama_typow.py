"""Brama typów mutacji (``silnik_mutacji.type_gate``) w testach: atrapa dla logiki i konfiguracja prawdziwego ruff i mypy."""

from __future__ import annotations

import importlib.util

import pytest

__all__ = ["FAKE_GATE", "TYPE_GATE_ON_SRC", "real_static_tools"]

# Źródło atrapy bramy ``brama(copy, **_)`` dla skryptu, który już zaimportował ``silnik_mutacji``: każda linia ``src`` kopii z
# komentarzem ``# brama: <narzędzie> <kod>`` daje diagnostykę tego narzędzia z tym kodem (``-``: bez kodu, jak wyjście,
# którego brama nie umie przeczytać; ``późno``: krok bez wyniku w czasie). Komentarz ``# brama gdy <tekst>: …`` daje ją
# tylko, gdy kod linii przed nim ma ``<tekst>``, czyli po mutacji operatora (``return 1`` → ``return None``), a nie bez
# niej. Test logiki bramy nie zależy więc od tego, czy na runnerze są ruff i mypy (zadania pytest na Windows instalują
# tylko ``requirements.txt``).
FAKE_GATE = '''
import re as _re


def brama(copy, **_):
    found, late = [], None
    for path in sorted((copy / "src").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            marker = _re.search(r"# brama(?: gdy (\\S+))?: (\\S+) (\\S+)", line)
            if marker and (marker[1] is None or marker[1] in line[: marker.start()]):
                where = f"{path.relative_to(copy).as_posix()}:{number}"
                if marker[3] == "późno":
                    late = f"{marker[2]}: brak wyniku po 1 s"
                    continue
                code = None if marker[3] == "-" else marker[3]
                found.append(silnik_mutacji.Finding(marker[2], marker[2], code, f"{where}: {marker[3]}"))
    return silnik_mutacji.Checked(tuple(found), late)
'''

# ``pyproject.toml`` repozytorium testu, w którym prawdziwe kroki ruff i mypy bramy (``kroki_lokalne.static_steps``)
# sprawdzają tylko jego ``src``: ``pyproject.toml`` checkoutu nazywa pliki, których repozytorium testu nie ma, więc tam
# mypy pada już bez mutacji.
TYPE_GATE_ON_SRC = """\
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
include = ["src/**/*.py"]

[tool.mypy]
strict = true
files = ["src"]
enable_error_code = ["exhaustive-match"]
"""

real_static_tools = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None or importlib.util.find_spec("mypy") is None,
    reason="test prawdziwej bramy typów potrzebuje ruff i mypy z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt",
)
