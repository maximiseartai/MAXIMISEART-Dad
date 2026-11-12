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

# Pliki, którym wolno parsować Pythona ręcznie: stan z 12.11.2026 (23 pliki); wpis maleje z każdym usuniętym plikiem.
# Jeden napis z odstępami, bo graf wyboru testów (``tools/lib/wplyw_zmiany.py``) bierze ścieżkę z napisu testu za jego
# zależność, a zapadki i tak biegną przy każdej zmianie (``ZAPADKI`` w ``tools/szybko.py``).
PARSERS = frozenset(
    """
    .agents/skills/verify-centrum-rozliczen/scripts/centrum_self_test.py
    tests/fixtures/skladnia.py
    tests/test_decyzje_na_faktach.py
    tests/test_eksplorator_w_procesie.py
    tests/test_granice_importow.py
    tests/test_granice_wyjatkow.py
    tests/test_jeden_odczyt_skoroszytu.py
    tests/test_jeden_zapis_skoroszytu.py
    tests/test_komunikaty_expect.py
    tests/test_limit_drive_centrum.py
    tests/test_mapy_funkcji.py
    tests/test_potomne.py
    tests/test_rodzaj_zatrzymania.py
    tests/test_skrypty_bez_instalacji.py
    tests/test_spis_narzedzi.py
    tests/test_struktura_testow.py
    tests/test_tabela_zatrzyman_efenix.py
    tests/test_wywolanie_skryptow_skilli.py
    tools/lib/kroki_skilli.py
    tools/lib/niestabilne_testy.py
    tools/lib/rozjazd_modelu.py
    tools/lib/wplyw_zmiany.py
    tools/mutacje_zmiany.py
    """.split()
)
PARSER_FOLDERS = ("tests", "tools", ".agents/skills")
_PARSER_CALL = re.compile(r"(?<![\w.])(?:ast\.(?:parse|walk)\(|tokenize\.)")
_NEW_PARSER = (
    "nowy plik z ręcznym parserem Pythona (ast.parse, ast.walk, tokenize): nazwij korzeń poprawki i napraw go na"
    " najwyższym szczeblu z sekcji „Reguły i co ich pilnuje” w AGENTS.md: (a) jedna droga i jeden właściciel, (b) typ"
    " albo reguła ruff (banned-api TID251 z msg „użyj X” w pyproject.toml), (c) test zachowania, (d) dopiero zapadka"
    " w tests/test_zapadki.py; plik, który mimo to parsuje, dopisz do PARSERS w tests/test_zapadki.py z powodem w"
    " opisie PR"
)
_GONE_PARSER = "plik zniknął: usuń go z PARSERS w tests/test_zapadki.py"


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


def parsers_off_entry(root: Path, base: str) -> list[str]:
    """Pliki zmiany od ``base``, na których wpis ``PARSERS`` rozjeżdża się ze stanem, każdy z poleceniem naprawy.

    Łapie tylko plik ``*.py`` w ``tests/``, ``tools/`` albo ``.agents/skills/`` (bez ``tests/test_zapadki.py``), który
    zmiana dodaje, zmienia albo usuwa (zmiana nazwy to usunięcie i dodanie), gdy po zmianie jego tekst, z komentarzami i
    napisami, ma ``ast.parse(``, ``ast.walk(`` albo ``tokenize.``, a ``PARSERS`` go nie ma: nowy plik z ręcznym
    parserem albo istniejący, do którego zmiana dopisała pierwsze takie wywołanie.
    Z wpisu każe usunąć tylko plik z ``PARSERS``, którego zmiana usuwa.
    Plik z ``PARSERS``, z którego zmiana usuwa ostatnie takie wywołanie, przechodzi i zostaje we wpisie, bo zapadka pada
    tylko na dodanym: inaczej nocna mutacja, która usuwa linię parsera, byłaby WYKRYTA przez wpis, a nie przez test
    zachowania, i linia bez testu nie trafiłaby do ``Przeżyte mutacje z #N`` (#670).
    Nie łapie matchera dopisanego do pliku z ``PARSERS`` ani do ``tests/test_zapadki.py``, regexu,
    ``from ast import parse``, ``import ast as a``, samego ``import tokenize``, ``from tokenize import …``,
    ``compile(…, ast.PyCF_ONLY_AST)``, ``ast.NodeVisitor``, wywołania pomocnika, który parsuje za wywołującego
    (``tests/fixtures/skladnia.py``), ani parsera w ``src/`` i poza tymi trzema folderami; te zostają przeglądowi.
    Pliku z ``PARSERS``, którego zmiana nie dotyka, nie sprawdza.
    """

    patterns = [f"{folder}/*.py" for folder in PARSER_FOLDERS]
    changed = {
        *_git(root, "diff", "--no-renames", "--name-only", base, "--", *patterns).splitlines(),
        *_git(root, "ls-files", "--others", "--exclude-standard", "--", *patterns).splitlines(),
    }
    found = []
    for path in sorted(changed - {"tests/test_zapadki.py"}):
        file = root / path
        parses = file.is_file() and _PARSER_CALL.search(file.read_text(encoding="utf-8")) is not None
        if parses and path not in PARSERS:
            found.append(f"{path}: {_NEW_PARSER}")
        elif not file.is_file() and path in PARSERS:
            found.append(f"{path}: {_GONE_PARSER}")
    return found


def test_reczny_parser_pythona_stoi_tylko_w_plikach_z_wpisu() -> None:
    base = _base()
    if base is None:
        pytest.skip(f"brak bazy zmiany: ustaw MAXIMISEART_ZAPADKA_BAZA albo pobierz {BASE}")

    assert parsers_off_entry(ROOT, base) == []


# Plik z ``PARSERS``, który testy zapadki kładą w swoim repozytorium (zmienna, nie napis, z powodu jak przy ``PARSERS``).
_IN_ENTRY = min(PARSERS)


def _repo_with_parser(root: Path) -> str:
    """Repozytorium z jednym plikiem z ``PARSERS`` i jednym bez parsera; zwraca commit bazy."""

    for path, text in {
        _IN_ENTRY: "import ast\n\ntree = ast.parse(source)\n",
        "tests/test_zwykly.py": "def test_zwykly() -> None:\n    assert True\n",
    }.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=zapadka", "-c", "user.email=zapadka@localhost", "commit", "-q", "-m", "baza")
    return _git(root, "rev-parse", "HEAD").strip()


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("tests/test_nowy.py", "import ast\n\nnodes = list(ast.walk(ast.parse(source)))\n"),
        ("tests/fixtures/nowy.py", "for node in ast.walk(tree):\n    pass\n"),
        ("tools/lib/nowy.py", "import tokenize\n\ntokens = tokenize.generate_tokens(readline)\n"),
        (".agents/skills/verify-x/scripts/nowy.py", "tree = ast.parse(path.read_text())\n"),
        ("tests/test_zwykly.py", "import ast\n\n\ndef test_zwykly() -> None:\n    assert ast.parse('x')\n"),
    ],
    ids=["nowy-test", "nowy-pomocnik", "tokenize-w-tools", "skrypt-skilla", "pierwsze-wywolanie-w-istniejacym"],
)
def test_zapadka_parsera_lapie_plik_spoza_wpisu_z_recznym_parserem(tmp_path: Path, path: str, text: str) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(text, encoding="utf-8")

    assert parsers_off_entry(tmp_path, base) == [f"{path}: {_NEW_PARSER}"]


def test_zapadka_parsera_widzi_nowy_plik_oznaczony_git_add_n(tmp_path: Path) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / "tests" / "test_nowy.py").write_text("tree = ast.parse(source)\n", encoding="utf-8")
    _git(tmp_path, "add", "-N", "tests/test_nowy.py")

    assert parsers_off_entry(tmp_path, base) == [f"tests/test_nowy.py: {_NEW_PARSER}"]


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (_IN_ENTRY, "import ast\n\ntree = ast.parse(source)\nnodes = list(ast.walk(tree))\n"),
        ("tests/test_nowy.py", "import re\n\nCALL = re.compile(r'open\\(')\n"),
        ("tests/test_nowy.py", "from ast import parse\n\ntree = parse(source)\n"),
        ("tests/test_nowy.py", "import ast as syntax\n\ntree = syntax.parse(source)\n"),
        ("tests/test_nowy.py", "import tokenize\n"),
        ("tests/test_nowy.py", "from tokenize import generate_tokens\n\ntokens = generate_tokens(readline)\n"),
        ("tests/test_nowy.py", "from tests.fixtures.skladnia import calls\n\nfound = calls(tree)\n"),
        ("tests/test_nowy.py", "tree = myast.parse(source)\nvalue = node.ast.walk(x)\n"),
        ("src/pakiet/nowy.py", "tree = ast.parse(source)\n"),
        ("tests/test_zapadki.py", "tree = ast.parse(source)\n"),
    ],
    ids=[
        "matcher-w-pliku-z-wpisu",
        "regex",
        "from-ast-import",
        "alias-modulu",
        "import-tokenize",
        "from-tokenize-import",
        "pomocnik",
        "inna-nazwa-przed-kropka",
        "src",
        "plik-zapadek",
    ],
)
def test_zapadka_parsera_przepuszcza_formy_spoza_granicy(tmp_path: Path, path: str, text: str) -> None:
    base = _repo_with_parser(tmp_path)
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(text, encoding="utf-8")

    assert parsers_off_entry(tmp_path, base) == []


@pytest.mark.parametrize(
    ("removed", "written", "expected"),
    [
        (True, {}, [f"{_IN_ENTRY}: {_GONE_PARSER}"]),
        (False, {_IN_ENTRY: "from tests.fixtures.skladnia import calls\n"}, []),
        (
            True,
            {"tests/test_granice.py": "import ast\n\ntree = ast.parse(source)\n"},
            [f"{_IN_ENTRY}: {_GONE_PARSER}", f"tests/test_granice.py: {_NEW_PARSER}"],
        ),
    ],
    ids=["usuniety", "bez-wywolania", "nowa-nazwa"],
)
def test_zapadka_parsera_kaze_usunac_z_wpisu_tylko_plik_ktory_zniknal(
    tmp_path: Path, removed: bool, written: dict[str, str], expected: list[str]
) -> None:
    base = _repo_with_parser(tmp_path)
    if removed:
        (tmp_path / _IN_ENTRY).unlink()
    for path, text in written.items():
        (tmp_path / path).write_text(text, encoding="utf-8")
    # W indeksie, jak w commicie gałęzi, git widzi przeniesienie pliku jako zmianę nazwy.
    _git(tmp_path, "add", "-A")

    assert parsers_off_entry(tmp_path, base) == expected
