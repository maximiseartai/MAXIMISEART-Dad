"""Test expect: wynik porównany z tekstem zapisanym w repo, żeby diff PR pokazywał zmianę zachowania.

Plik expect jest w UTF-8 z końcami linii ``\\n``; odczyt ``read_text`` zamienia ``\\r\\n`` z checkoutu na Windows na ``\\n``.
Przy różnicy test pada z unified diffem i poleceniem, które zapisuje nowy plik (``save_command``):
``ZAPISZ_EXPECT=1`` przed pytestem. W CI (``CI`` ustawione) plik nigdy się nie zapisuje.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
import shlex
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAVE = "ZAPISZ_EXPECT"


def save_command(test: str, *, windows: bool) -> str:
    """Polecenie z katalogu repo, które zapisuje plik expect testu ``test``: w PowerShellu na Windows, w sh gdzie indziej.

    PowerShell trzyma ``$env:`` do końca sesji, więc polecenie zdejmuje zmienną po pyteście, żeby następne testy
    porównywały plik, a nie go zapisywały.
    """

    if windows:
        quoted = "'" + test.replace("'", "''") + "'"
        return f"$env:{SAVE}=1; .venv\\Scripts\\python.exe -m pytest {quoted}; Remove-Item Env:{SAVE}"
    return f"{SAVE}=1 .venv/bin/python -m pytest {shlex.quote(test)}"


def assert_expected(actual: str, path: Path) -> None:
    name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    if os.environ.get(SAVE) == "1":
        if os.environ.get("CI"):
            pytest.fail(f"{SAVE}=1 w CI: plik expect {name} zapisuje się tylko lokalnie", pytrace=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    expected = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        return
    diff = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True), actual.splitlines(keepends=True), f"{name} (zapisany)", f"{name} (wynik testu)"
        )
    )
    test = os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0] or name
    pytest.fail(
        f"wynik różni się od pliku expect {name}:\n{diff}\n"
        f"Jeśli zmiana jest zamierzona, zapisz nowy plik i dodaj go do tego samego commita:\n"
        f"  {save_command(test, windows=sys.platform == 'win32')}",
        pytrace=False,
    )
