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

# Lookbehind wokół cyfr numeru, jak ``(?<![0-9a-f])`` w 5b2edaf2f9 i ``(?<![0-9])`` w cc7e5ced21.
_ORDER_NUMBER_ORACLE = re.compile(r"\(\?<!\[?(?:\\d|0-9)")
_ORDER_NUMBER_HELPER = (
    "własna wyrocznia wycieku numeru zlecenia: sprawdź tekst przez zawiera_wartosc z tests/fixtures/wyciek.py, która"
    " pyta strażnika reguły danych (ForbiddenValues.guard)"
)

# Stan ścieżki bez file_state, jak ``copy.path.exists()`` w ea69c32bea i ``old.is_file()`` w 5f4e134ba5.
_BARE_FILE_STATE = re.compile(r"\.(?:exists|is_file|is_dir)\(\s*\)|\bos\.path\.(?:exists|lexists|isfile|isdir)\(")
_FILE_STATE = "src/rozliczenia/file_state.py"
_FILE_STATE_HELPER = (
    "stan pliku poza file_state: zapytaj src/rozliczenia/file_state.py (file_state, path_state, path_taken, a o wpis"
    " folder_entries entry_kind), które rozróżnia brak od pliku niedostępnego (OneDrive, folder bez dostępu)"
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

    Łapie tylko napis ``(?<!``, po nim opcjonalnie ``[``, a po nim ``\\d`` z jednym ukośnikiem albo ``0-9``: tak zaczyna
    się ``(?<![0-9a-f])``, ``(?<![0-9])``, ``(?<!0-9`` i ``r"(?<!\\d)"``. Nie łapie ``"(?<!\\\\d)"`` (dwa ukośniki w napisie
    bez ``r``), klasy, w której ``0-9`` nie stoi zaraz po ``[`` (``(?<![a-f0-9])``), ``\\b`` wokół liczby, literału liczby
    przed ``not in``, numeru ze zmiennej, ``str.find``, ``count``, ``re.search`` na samym numerze, lookaheadu bez
    lookbehindu ani wyrażenia złożonego w kilku liniach; te zostają przeglądowi. Każda forma ma 0 trafień, gdy każda
    linia ``tests/`` jest dodana (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``),
    dlatego literał liczby przed ``not in`` nie jest formą: w ``tests/`` stoją poprawne ``"2026" not in`` i ``"999999" not
    in``.
    """

    return _ORDER_NUMBER_ORACLE.search(line) is not None


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


def bare_file_state(line: str) -> bool:
    """Czy linia ``src/`` pyta o stan ścieżki z pominięciem ``file_state``.

    Łapie tylko ``.exists()``, ``.is_file()`` i ``.is_dir()`` bez argumentów, także ze spacją w nawiasie (na ``Path`` i
    na wpisie ``os.DirEntry``), oraz ``os.path.exists(``, ``os.path.lexists(``, ``os.path.isfile(`` i
    ``os.path.isdir(``, także w komentarzu i napisie. Nie łapie ``.iterdir()`` (#1249 dodał świadome
    ``register.parent.iterdir()`` w ``try``/``except OSError``, którego po linii nie odróżnić od błędu #1021),
    ``os.listdir``, ``os.scandir``, ``glob``, ``stat`` i ``try``/``except OSError`` napisanych od nowa, wywołań z
    argumentem (``is_file(follow_symlinks=False)``) ani rozbitych na kilka linii, metody pod inną nazwą
    (``check = path.exists``), ``Path.exists(path)``, ``os.path`` pod aliasem (``import os.path as osp``) ani ``exists``
    z ``from os.path import``; te zostają przeglądowi.
    Żadna forma nie trafia w dzisiejsze ``src/``, gdy każda jego linia jest dodana
    (``test_zapadki_nie_zglaszaja_zadnej_linii_testow`` w ``tests/test_struktura_testow.py``).
    """

    return _BARE_FILE_STATE.search(line) is not None


def file_state_bypasses(root: Path, base: str) -> list[str]:
    """Linie ``src/`` poza ``file_state.py``, które zmiana od ``base`` dodaje z ``bare_file_state``, z komunikatem."""

    return [
        f"{path}:{number}: {_FILE_STATE_HELPER}"
        for path, number, line in _added_lines(root, base, "src")
        if path != _FILE_STATE and bare_file_state(line)
    ]


def test_stan_pliku_w_src_tylko_przez_file_state() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")
    assert file_state_bypasses(ROOT, base) == []


def test_zapadka_stanu_pliku_widzi_tylko_src_poza_file_state(tmp_path: Path) -> None:
    author = ("-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, *author, "commit", "-q", "--allow-empty", "-m", "baza")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path in (_FILE_STATE, "src/rozliczenia/kopia.py", "tests/test_kopii.py", "tools/narzedzie.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("def taken(path):\n    return path.exists()\n", encoding="utf-8")

    found = file_state_bypasses(tmp_path, base)

    assert found == [f"src/rozliczenia/kopia.py:2: {_FILE_STATE_HELPER}"]


@pytest.mark.parametrize(
    "line",
    [
        "    taken = copy.path.exists()",
        "    return old.name if old.is_file() else None",
        "    if STATIC_DIRECTORY.is_dir():",
        "    for entry in entries if entry.is_dir() and _YEAR_FOLDER.fullmatch(entry.name)",
        "    return os.path.exists(excel_lock_file(path))",
        "            collective_file_exists=os.path.isfile(path),",
        "    if not path.exists( ):",
    ],
)
def test_zapadka_lapie_stan_pliku_poza_file_state(line: str) -> None:
    assert bare_file_state(line)


@pytest.mark.parametrize(
    "line",
    [
        '    return old.name if file_state(old) == "file" else None',
        "    if path_taken(self._state):",
        '    present = [period_place_label(place) for place in places if observed.exists(place)]',
        "                taken = disk.exists(copy.path)",
        # Formy, których zapadka według docstringu nie łapie.
        "        names = sorted(path.name for path in register.parent.iterdir())",
        "    return path.is_file(follow_symlinks=False)",
        "    names = os.listdir(folder)",
    ],
)
def test_zapadka_przepuszcza_file_state_i_metody_domeny(line: str) -> None:
    assert not bare_file_state(line)


@pytest.mark.parametrize(
    "line",
    [
        'return re.search(rf"(?<![0-9a-f]){re.escape(number.removeprefix(\'#\'))}(?![0-9a-f])", text) is not None',
        'number = re.compile(r"(?<![0-9a-f])9401(?![0-9a-f])")',
        'number = re.compile(r"(?<![0-9])9401(?![0-9])")',
        r'assert re.search(r"(?<!\d)9401", text) is None',
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
        # Formy, których zapadka według docstringu nie łapie.
        'number = re.compile("(?<!\\\\d)94001(?!\\\\d)")',
        'number = re.compile(r"(?<![a-f0-9])94001(?![a-f0-9])")',
        r'assert not re.search(r"\b94001\b", text)',
        'assert "94001" not in (tmp_path / "slad.json").read_text(encoding="utf-8")',
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


def test_zapadka_bierze_baze_zmiany_ze_zmiennej(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAXIMISEART_ZAPADKA_BAZA", "galaz-rodzica")

    assert _base() == "galaz-rodzica"
