"""Zapadki: reguły, które padają tylko na liniach dodanych przez zmianę, bo stare wystąpienia już zniknęły albo jest ich
za dużo, by je zakazać od razu.

Bazę zmiany daje zmienna ``MAXIMISEART_ZAPADKA_BAZA`` (commit albo gałąź), a bez niej zapadka liczy od ``merge-base``
HEAD z ``origin/main``. Dodane linie to ``git diff`` od bazy (z niezacommitowanymi zmianami) i całe pliki nieśledzone.
Płytki checkout bez bazy (zadania pytest w CI) nie ma czego porównać, więc zapadka się pomija; pilnuje jej
``tools/szybko.py`` przed pushem. Moduł importuje tylko bibliotekę standardową i pytest, bo pomiar zapadek uruchamia go
też w kopii starego commitu.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")

_ORDER_NUMBER_ORACLES = (
    # Granica liczby w wyrażeniu: lookbehind na cyfrach, jak ``(?<![0-9a-f])`` w 5b2edaf2f9 i cc7e5ced21.
    re.compile(r"\(\?<!\[?(?:\\d|0-9)"),
    # Granica słowa wokół literału liczby, np. ``\b9401\b``.
    re.compile(r"\\b#?\d{4,}\\b"),
    # Goły podciąg literału liczby: ``"9401" not in ślad`` (czerwony main po #757).
    re.compile(r"""["']#?\d{4,}["']\s+not\s+in\b"""),
)
_ORDER_NUMBER_HELPER = (
    "własna wyrocznia wycieku numeru zlecenia: sprawdź tekst przez zawiera_wartosc z tests/fixtures/wyciek.py, która"
    " pyta strażnika reguły danych (ForbiddenValues.guard)"
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _base() -> str | None:
    base = os.environ.get("MAXIMISEART_ZAPADKA_BAZA")
    if base:
        return base
    try:
        return _git(ROOT, "merge-base", "HEAD", BASE).strip()
    except subprocess.CalledProcessError:
        return None


def _added_lines(root: Path, base: str, folder: str) -> Iterator[tuple[str, int, str]]:
    """Linie ``*.py`` w ``folder`` repozytorium ``root``, które zmiana od ``base`` dodaje: ścieżka, numer linii i treść."""

    path = None
    number = 0
    for line in _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", f"{folder}/*.py").splitlines():
        if line.startswith("+++ "):
            path = line.removeprefix("+++ b/") if line != "+++ /dev/null" else None
        elif hunk := _HUNK.match(line):
            number = int(hunk["start"])
        elif line.startswith("+") and path is not None:
            yield path, number, line[1:]
            number += 1
    for path in _git(root, "ls-files", "--others", "--exclude-standard", "--", f"{folder}/*.py").splitlines():
        for number, line in enumerate((root / path).read_text(encoding="utf-8").splitlines(), start=1):
            yield path, number, line


def order_number_oracle(line: str) -> bool:
    """Czy linia testu sprawdza wyciek numeru zlecenia własną definicją zamiast ``zawiera_wartosc``.

    Łapie tylko trzy formy, w których agenci ją pisali: lookbehind na cyfrach (``\\d``, ``[0-9…]``), literał co
    najmniej czterech cyfr między ``\\b`` i literał co najmniej czterech cyfr (z ``#`` albo bez) przed ``not in``. Nie
    łapie numeru ze zmiennej w ``in`` albo ``not in``, ``str.find``, ``count``, ``re.search`` na samym numerze, lookahead
    bez lookbehindu ani wyrażenia złożonego w kilku liniach; te zostają przeglądowi.
    """

    return any(pattern.search(line) for pattern in _ORDER_NUMBER_ORACLES)


def test_wyciek_numeru_zlecenia_test_sprawdza_tylko_przez_zawiera_wartosc() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    found = [
        f"{path}:{number}: {_ORDER_NUMBER_HELPER}"
        for path, number, line in _added_lines(ROOT, base, "tests")
        if path != "tests/test_zapadki.py" and order_number_oracle(line)
    ]
    assert found == []


@pytest.mark.parametrize(
    "line",
    [
        'return re.search(rf"(?<![0-9a-f]){re.escape(number.removeprefix(\'#\'))}(?![0-9a-f])", text) is not None',
        'number = re.compile(r"(?<![0-9a-f])9401(?![0-9a-f])")',
        'number = re.compile(r"(?<![0-9])9401(?![0-9])")',
        r'assert re.search(r"(?<!\d)9401", text) is None',
        r'assert not re.search(r"\b9401\b", text)',
        'assert "9401" not in (tmp_path / "slad.json").read_text(encoding="utf-8")',
        "assert '#94001' not in text",
    ],
)
def test_zapadka_lapie_wlasna_wyrocznie_numeru_zlecenia(line: str) -> None:
    assert order_number_oracle(line)


@pytest.mark.parametrize(
    "line",
    [
        "assert [zawiera_wartosc(text, order.number) for text in texts] == [False, False]",
        'FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\\\/]")',
        'assert "TESTOWA" not in text',
        'assert "2026" in text',
        'assert re.fullmatch(r"CZAS: ([0-9]+) s", line)',
    ],
)
def test_zapadka_przepuszcza_zawiera_wartosc_i_inne_wyrazenia(line: str) -> None:
    assert not order_number_oracle(line)


def test_zapadka_widzi_linie_dodane_od_bazy_i_nowe_pliki_a_nie_usuniete_ani_spoza_folderu(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("pierwsza\nusunieta\ntrzecia\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, *author, "commit", "-q", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "tests" / "test_a.py").write_text("pierwsza\ndodana\ntrzecia\nna końcu\n", encoding="utf-8")
    (tmp_path / "tests" / "fixtures").mkdir()
    (tmp_path / "tests" / "fixtures" / "nowy.py").write_text("nowa\n", encoding="utf-8")
    (tmp_path / "poza.py").write_text("poza testami\n", encoding="utf-8")

    added = sorted(_added_lines(tmp_path, base, "tests"))

    assert added == [("tests/fixtures/nowy.py", 1, "nowa"), ("tests/test_a.py", 2, "dodana"), ("tests/test_a.py", 4, "na końcu")]
