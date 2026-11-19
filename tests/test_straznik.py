"""Dowód strażnika Ważnego (``tools/lib/straznik.py``, ADR 0042) na małym repozytorium Gita: gałąź PR od ``main``
z commitem werdyktu ``FAIL`` z błędem w miejscu ``Gdzie`` i HEAD z poprawką i strażnikiem z zamkniętej listy.

Każdy przypadek tabeli ``straznik.ZASADY`` ma tu przebieg: strażnik pada na błędzie z SHA ``FAIL`` albo z mutacji
recenzenta (``WYKRYTA``), strażnik, który błędu nie łapie, nie przechodzi, a format z konfiguracji PR wyniku nie
zmienia. Granice stoją w ``ZNANE_LUKI_STRAZNIKA`` i przechodzą dowód, dopóki konstrukcja ich nie zamknie.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
import json
from pathlib import Path
import sys
import uuid
import zlib

import pytest

from mutacja_recenzenta import Block
import piaskownica
import srodowisko_ci
import straznik
from straznik import Guard, Kind
from kroki_lokalne import MYPY_PLATFORMS
from tests.fixtures.git_repo import commit, git
from tests.fixtures.znane_luki import wymaga_ruff_i_mypy

wymaga_piaskownicy = pytest.mark.skipif(
    sys.platform == "win32", reason="dowód mypy, ruff i pytest biegnie w piaskownicy systemu (Landlock na Linuksie, sandbox-exec na macOS), której Windows nie ma"
)
PYPROJECT = """\
[tool.mypy]
files = ["kod"]
strict = true
{mypy}
[tool.ruff]
{ruff}
[tool.ruff.lint]
select = ["F", "TID251"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
{banned}

[tool.pytest.ini_options]
"""
BASE = {
    "kod/__init__.py": "",
    "kod/liczby.py": "def podwojona(x: int) -> int:\n    return x * 2\n\n\ndef nastepna(x: int) -> int:\n    return x + 1\n",
    "tests/__init__.py": "",
    "tests/test_nastepna.py": "from kod.liczby import nastepna\n\n\ndef test_nastepna() -> None:\n    assert nastepna(1) == 2\n",
    "docs/opis.md": "# Opis\n\nLiczby podwaja `podwojona`.\n",
}
GUARD_TEST = "from kod.liczby import podwojona\n\n\ndef test_podwojona_daje_dwa_razy() -> None:\n    assert podwojona(3) == 6\n"
BAD = BASE["kod/liczby.py"].replace("x * 2", "x * 3")
Places = tuple[tuple[str, int, int], ...]
WHERE: Places = (("kod/liczby.py", 2, 2),)
# Zakres ``WHERE`` jak z ``na_scalonych_pr.places``: najmniejsza funkcja wokół miejsca, ``podwojona``.
SCOPE: Places = (("kod/liczby.py", 1, 2),)


@dataclass(frozen=True)
class Pull:
    root: Path
    fork: str
    failed: str
    head: str

    def prove(
        self, guard: str, places: Places = WHERE, *, scopes: Places = (), prose: Places = (), before_test_proof: bool = False, mutation: str | None = None
    ) -> straznik.Outcome:
        """Dowód jednego Ważnego; ``scopes`` i ``prose`` to linie z FAIL, które podaje ``tools/na_scalonych_pr.py``,
        a ``mutation`` tekst najnowszego bloku ``### Mutacja W1 r1`` z werdyktów PR. Mypy, ruff i pytest biegną tu
        Pythonem testów na kopii HEAD, bo te testy sprawdzają przywrócenie błędu; środowisko Required CI
        z ``srodowisko_ci.built``, którym biegnie dowód, i osobne środowisko na każdy bieg testu sprawdza
        ``tests/test_srodowisko_ci.py``."""

        block = None if mutation is None else Block("W1", 1, mutation)
        case = straznik.Case("#5 W1 r1", self.failed, self.fork, places, scopes, prose, block)
        chosen = straznik.parse(guard)
        if chosen.kind in straznik.EXEMPT:
            [outcome] = straznik.exempt(self.root, chosen, self.head, self.fork, [case], before_test_proof=before_test_proof)
            return outcome
        if chosen.kind is Kind.PYTEST:
            [outcome] = straznik.prove_test(chosen.arguments[0], self._copy, [case])
            return outcome
        with self._copy() as environment:
            [outcome] = straznik.prove(self.root, chosen, environment, [case])
        return outcome

    @contextmanager
    def _copy(self) -> Iterator[straznik.Environment]:
        """Kopia HEAD z własnym gitem, ``HOME`` i ``TMPDIR`` obok siebie, jak każde środowisko z ``srodowisko_ci.built``."""

        with srodowisko_ci.run_folder("straznik-") as folder:
            copy, home, temporary = (folder / name for name in ("drzewo", "dom", "tmp"))
            srodowisko_ci._checkout(self.root, self.head, copy)
            home.mkdir()
            temporary.mkdir()
            yield straznik.Environment(self.head, copy, Path(sys.executable), {**srodowisko_ci.variables(), "HOME": str(home), "TMPDIR": str(temporary)})


def _pull(tmp_path: Path, failed: dict[str, str], head: dict[str, str]) -> Pull:
    """``main`` z ``BASE``, commit werdyktu ``FAIL`` z plikami ``failed`` i HEAD z ``head`` na nim."""

    root = tmp_path / "repo"
    files = {"pyproject.toml": PYPROJECT.format(mypy="", ruff="", banned=""), **BASE}
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    git(root, "init", "--quiet", "--initial-branch", "main")
    fork = commit(root, "main")
    shas: list[str] = []
    for version in (failed, head):
        for name, text in version.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        shas.append(commit(root, f"wersja {len(shas) + 1}"))
    return Pull(root, fork, shas[0], shas[1])


def _fixed(tmp_path: Path) -> Pull:
    return _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": BASE["kod/liczby.py"], "tests/test_podwojona.py": GUARD_TEST})


@pytest.mark.parametrize(
    ("text", "guard"),
    [
        ("mypy", Guard(Kind.MYPY)),
        ("ruff", Guard(Kind.RUFF)),
        ("ast-grep lokator-tytulu-okna", Guard(Kind.AST_GREP, ("lokator-tytulu-okna",))),
        ("pytest tests/test_g.py::test_g", Guard(Kind.PYTEST, ("tests/test_g.py::test_g",))),
        ("pytest tests/centrum/test_ż.py::Klasa::test_ą[1-a]", Guard(Kind.PYTEST, ("tests/centrum/test_ż.py::Klasa::test_ą[1-a]",))),
        ("brak - proza", Guard(Kind.PROSE)),
        ("brak  -  test", Guard(Kind.TESTS)),
        ("brak - napęd", Guard(Kind.DRIVE)),
        ("brak - usunięte", Guard(Kind.REMOVED)),
    ],
)
def test_selektor_straznika_z_zamknietej_listy_daje_rodzaj_i_argumenty(text: str, guard: Guard) -> None:
    assert straznik.parse(text) == guard


@pytest.mark.parametrize(
    "text",
    [
        "",
        "pytest tests/test_x.py",
        "pytest tests/test_x.py::test_y -k z",
        "pytest src/rozliczenia/x.py::test_y",
        "pytest tests/../src/x.py::test_y",
        "pytest tests/test_x.py::A::B::test_y",
        "pytest tests/test_x.py::TestKlasa",
        "mypy --strict",
        "ast-grep",
        "brak",
        "brak - nic",
        "tools/mutacje.py --zmiana a b c",
    ],
    ids=[
        "pusty",
        "caly-plik-testow",
        "wezel-z-opcja-pytest",
        "wezel-poza-tests",
        "sciezka-wychodzi-z-tests",
        "klasa-w-klasie",
        "klasa-testow",
        "mypy-z-flaga",
        "ast-grep-bez-id",
        "brak-bez-powodu",
        "brak-z-powodem-spoza-listy",
        "mutacja-autora",
    ],
)
def test_selektor_spoza_listy_to_odmowa_z_postaciami_listy(text: str) -> None:
    """Test wskazuje jeden węzeł pytest w ``tests/`` (test albo jego parametr), bez opcji, bo dowód liczy padnięcie tego
    węzła z mutacją recenzenta; mutację pisze recenzent w werdykcie, nie autor w selektorze; inna postać to odmowa
    z listą."""

    with pytest.raises(ValueError, match=r"to nie selektor strażnika z listy: mypy, ruff, .* pytest tests/<plik>\.py::<test>, .* brak - usunięte"):
        straznik.parse(text)


TYPED = {
    "kod/odczyt.py": "def odczyt() -> str:\n    return 'tekst'\n",
    "kod/uzycie.py": "from kod.odczyt import odczyt\n\n\ndef glosno() -> str:\n    return odczyt().upper()\n",
}
TYPED_FIX = {
    "kod/odczyt.py": "def odczyt() -> str | None:\n    return None\n",
    "kod/uzycie.py": "from kod.odczyt import odczyt\n\n\ndef glosno() -> str:\n    tekst = odczyt()\n    return '' if tekst is None else tekst.upper()\n",
}


@wymaga_ruff_i_mypy
@pytest.mark.parametrize(
    "mypy",
    ["", "hide_error_codes = true\nshow_column_numbers = true\npretty = true\nshow_error_context = true\n"],
    ids=["format-domyslny", "format-z-konfiguracji-pr"],
)
def test_typ_ktory_odrzuca_zla_postac_z_gdzie_to_dowod_mypy_takze_przy_formacie_z_konfiguracji_pr(tmp_path: Path, mypy: str) -> None:
    """Typ z HEAD (``str | None``) odrzuca kod z FAIL, który bierze wynik jak ``str``; format wyjścia z ``pyproject.toml``
    PR (sonda (c) i #1912 r4) dowodu nie zmienia, bo dowód czyta ``mypy -O json``."""

    pull = _pull(tmp_path, TYPED, {**TYPED_FIX, "pyproject.toml": PYPROJECT.format(mypy=mypy, ruff="", banned="")})

    outcome = pull.prove("mypy", (("kod/uzycie.py", 5, 5),), scopes=(("kod/uzycie.py", 4, 5),))

    assert outcome.detected, outcome.line
    assert "| WYKRYTA | z FAIL: kod/uzycie.py | kod/uzycie.py:5 [union-attr]" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_mypy_widzi_plik_z_fail_o_tym_samym_rozmiarze_co_na_head(tmp_path: Path) -> None:
    """``int`` i ``str`` mają tyle samo znaków, a pliki powstają w tej samej sekundzie, więc pamięć mypy z biegu na HEAD
    uznałaby przywrócony plik za sprawdzony."""

    use = "from kod.liczby import podwojona\n\n\ndef tekst() -> {}:\n    return str(podwojona(1))\n"
    pull = _pull(tmp_path, {"kod/tekst.py": use.format("int")}, {"kod/tekst.py": use.format("str")})

    outcome = pull.prove("mypy", (("kod/tekst.py", 5, 5),), scopes=(("kod/tekst.py", 4, 5),))

    assert outcome.detected and "kod/tekst.py:5 [return-value]" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_dowod_mypy_lapie_blad_w_galezi_systemu_wtedy_i_tylko_wtedy_gdy_required_ci_sprawdza_ten_system(tmp_path: Path, platform: str) -> None:
    """Dowód biegnie mypy dla każdej platformy z ``kroki_lokalne.MYPY_PLATFORMS``, jedynej listy platform Required CI
    (#2116 r4 W1, r5 W1), na każdej maszynie: błąd typu w gałęzi ``sys.platform == <platforma>`` łapie wtedy i tylko
    wtedy, gdy ta platforma stoi na liście, więc zmiana listy zmienia dowód razem z CI."""

    use = f"import sys\n\nfrom kod.odczyt import odczyt\n\n\ndef glosno() -> str:\n    if sys.platform == '{platform}':\n{{}}    return ''\n"
    failed = {**TYPED, "kod/uzycie.py": use.format("        return odczyt().upper()\n")}
    fixed = {**TYPED_FIX, "kod/uzycie.py": use.format("        tekst = odczyt()\n        return '' if tekst is None else tekst.upper()\n")}
    pull = _pull(tmp_path, failed, fixed)

    outcome = pull.prove("mypy", (("kod/uzycie.py", 8, 8),), scopes=(("kod/uzycie.py", 6, 9),))

    if platform in MYPY_PLATFORMS:
        assert outcome.detected and "kod/uzycie.py:8 [union-attr]" in outcome.line, outcome.line
    else:
        assert not outcome.detected and "| NIEWYKRYTA | kod/uzycie.py: bez znaleziska (kod 0)" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_mypy_bez_typu_przy_bledzie_zachowania_nie_jest_dowodem(tmp_path: Path) -> None:
    pull = _fixed(tmp_path)

    outcome = pull.prove("mypy", scopes=SCOPE)

    assert not outcome.detected and "| NIEWYKRYTA | kod/liczby.py: bez znaleziska (kod 0)" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_znalezisko_mypy_poza_funkcja_z_gdzie_nie_jest_dowodem(tmp_path: Path) -> None:
    """Przywrócony plik pada na typie innej funkcji niż ta z ``Gdzie`` (dryf API), więc dowód nie liczy tego znaleziska."""

    failed = {**TYPED, "kod/uzycie.py": TYPED["kod/uzycie.py"] + "\n\ndef zla(x: int) -> int:\n    return x * 3\n"}
    fixed = {**TYPED_FIX, "kod/uzycie.py": TYPED_FIX["kod/uzycie.py"] + "\n\ndef zla(x: int) -> int:\n    return x * 2\n"}
    pull = _pull(tmp_path, failed, fixed)

    outcome = pull.prove("mypy", (("kod/uzycie.py", 9, 9),), scopes=(("kod/uzycie.py", 8, 9),))

    assert not outcome.detected and "znaleziska poza funkcją z Gdzie: kod/uzycie.py:5" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_znalezisko_w_calym_przywroconym_pliku_liczy_sie_gdy_kod_funkcji_z_gdzie_stoi_bez_zmian_na_head(tmp_path: Path) -> None:
    """``Gdzie`` wskazuje miejsce objawu (#1956 W2 r1: linia 207, a błąd typu na 184): funkcja z FAIL stoi na HEAD bez
    zmian, więc poprawka leży obok i dowód liczy znalezisko w całym przywróconym pliku."""

    symptom = "\n\ndef objaw(x: int) -> int:\n    return x\n"
    pull = _pull(tmp_path, {**TYPED, "kod/uzycie.py": TYPED["kod/uzycie.py"] + symptom}, {**TYPED_FIX, "kod/uzycie.py": TYPED_FIX["kod/uzycie.py"] + symptom})

    outcome = pull.prove("mypy", (("kod/uzycie.py", 9, 9),), scopes=(("kod/uzycie.py", 8, 9),))

    assert outcome.detected and "kod/uzycie.py:5 [union-attr]" in outcome.line, outcome.line


BANNED = '"os.system".msg = "użyj subprocess.run"'
SHELL = "import os\n\n\ndef uruchom() -> int:\n    return os.system('true')\n"
SHELL_FIX = "import subprocess\n\n\ndef uruchom() -> int:\n    return subprocess.run(['true'], check=False).returncode\n"


@wymaga_ruff_i_mypy
@pytest.mark.parametrize("ruff", ["", 'output-format = "concise"\n'], ids=["format-domyslny", "format-z-konfiguracji-pr"])
def test_zakaz_ruff_dodany_w_pr_to_dowod_ruff_takze_przy_formacie_z_konfiguracji_pr(tmp_path: Path, ruff: str) -> None:
    """Zakaz ``banned-api`` z HEAD łapie przywrócone ``os.system`` w funkcji z ``Gdzie``; ``output-format`` z konfiguracji
    PR (#1912 r3) dowodu nie zmienia, bo dowód podaje ``--output-format json`` w wierszu poleceń."""

    pull = _pull(
        tmp_path,
        {"kod/powloka.py": SHELL},
        {"kod/powloka.py": SHELL_FIX, "pyproject.toml": PYPROJECT.format(mypy="", ruff=ruff, banned=BANNED)},
    )

    outcome = pull.prove("ruff", (("kod/powloka.py", 5, 5),), scopes=(("kod/powloka.py", 4, 5),))

    assert outcome.detected, outcome.line
    assert "| WYKRYTA | z FAIL: kod/powloka.py | kod/powloka.py:5 TID251" in outcome.line, outcome.line


@pytest.mark.parametrize(
    ("guard", "places", "state"),
    [
        ("brak - proza", (("docs/opis.md", 3, 3),), "WYJĄTEK brak - proza | docs/opis.md:3"),
        ("brak - proza", (("kod/liczby.py", 2, 2),), "ODMOWA | kod/liczby.py:2 to nie plik .md, docstring ani komentarz"),
        ("brak - proza", (("docs/opis.md", 3, 3), ("tests/test_nastepna.py", 5, 5)), "WYJĄTEK brak - proza | docs/opis.md:3"),
        ("brak - proza", (("tests/test_nastepna.py", 5, 5),), "ODMOWA | żadne miejsce z Gdzie nie leży w pliku, który zmienił PR"),
        ("brak - napęd", (("frontend/src/dzien.ts", 2, 2),), "WYJĄTEK brak - napęd | frontend/src/dzien.ts:2"),
        ("brak - napęd", (("kod/liczby.py", 2, 2),), "ODMOWA | kod/liczby.py:2 leży poza frontend/"),
    ],
    ids=["proza-w-md", "proza-w-kodzie-poza-docstringiem", "proza-z-miejscem-sprzed-pr-pominietym", "miejsce-sprzed-pr", "naped-w-frontend", "naped-w-kodzie"],
)
def test_wyjatek_przechodzi_tylko_gdy_kazde_miejsce_gdzie_zmienione_przez_pr_spelnia_jego_warunek(
    tmp_path: Path, guard: str, places: tuple[tuple[str, int, int], ...], state: str
) -> None:
    docs = {"docs/opis.md": "# Opis\n\nLiczby potraja `podwojona`.\n"}
    frontend = {"frontend/src/dzien.ts": "export const komplet = (dni: number) =>\n  dni > 1;\n"}
    pull = _pull(tmp_path, {"kod/liczby.py": BAD, **docs, **frontend}, {"kod/liczby.py": BASE["kod/liczby.py"], "tests/test_podwojona.py": GUARD_TEST})

    outcome = pull.prove(guard, places)

    assert outcome.detected == state.startswith("WYJĄTEK"), outcome.line
    assert outcome.line == f"#5 W1 r1 | {pull.failed[:8]} | {state}", outcome.line


def test_proza_w_docstringu_i_komentarzu_pythona_to_wyjatek(tmp_path: Path) -> None:
    documented = '"""Moduł liczb.\n\nPodwaja `podwojona`.\n"""\n\n# komentarz o liczbach\n' + BASE["kod/liczby.py"]
    pull = _pull(tmp_path, {"kod/liczby.py": documented.replace("Podwaja", "Potraja")}, {"kod/liczby.py": documented})

    outcome = pull.prove("brak - proza", (("kod/liczby.py", 3, 3), ("kod/liczby.py", 6, 6)), prose=(("kod/liczby.py", 1, 4), ("kod/liczby.py", 6, 6)))

    assert outcome.detected, outcome.line


def test_komentarz_za_kodem_na_linii_z_gdzie_nie_jest_proza(tmp_path: Path) -> None:
    trailing = BASE["kod/liczby.py"].replace("return x * 2", "return x * 2  # podwaja")
    pull = _pull(tmp_path, {"kod/liczby.py": trailing.replace("x * 2", "x * 3")}, {"kod/liczby.py": trailing})

    outcome = pull.prove("brak - proza", WHERE, prose=(("kod/liczby.py", 2, 2),))

    assert not outcome.detected and "kod/liczby.py:2 to nie plik .md, docstring ani komentarz" in outcome.line, outcome.line


# Dowód ``pytest <węzeł>`` z mutacją recenzenta (ADR 0042, aneks): HEAD z poprawką ``x * 2`` i blok, który przywraca
# ``x * 3`` z FAIL. Węzeł pada tylko przez mutację z bloku, więc sondy rund r1–r3 #2197 (nazwa dodana po FAIL, wyjątek
# złapany w kodzie HEAD, stan biegu) nie mają czego sklasyfikować.
GOOD = BASE["kod/liczby.py"]
NODE = "tests/test_g.py::test_g"
TEST_G = "from kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    assert podwojona(3) == 6\n"


def _block(*edits: tuple[str, str, str], name: str = "x * 3 z FAIL") -> str:
    return json.dumps([{"nazwa": name, "zmiany": [list(edit) for edit in edits]}])


def _with_trace(text: str, trace: str) -> str:
    """Źródło próbki z ``{slad}`` zastąpionym literałem Pythona ścieżki ``trace`` (``repr``), a nie samym tekstem
    ścieżki w cudzysłowie: ścieżka Windows ``C:\\Users\\…`` w cudzysłowie to ``SyntaxError`` (``\\U``), więc podstawa
    dowodu na Windows jest czerwona (#2197 r6 W1)."""

    return text.replace("{slad}", repr(trace))


TRIPLED = _block(("kod/liczby.py", "return x * 2", "return x * 3"))
# Parametr testu z id z danych produkcji (sonda #2197 r4 W1): z mutacją, która przywraca listę z FAIL, węzła nie ma.
FORMATS = 'OBSLUGIWANE = ("a", "b")\n\n\ndef obsluz(nazwa: str) -> bool:\n    return nazwa in OBSLUGIWANE\n'
TEST_FORMATS = 'import pytest\n\nfrom kod.pliki import OBSLUGIWANE, obsluz\n\n\n@pytest.mark.parametrize("nazwa", OBSLUGIWANE)\ndef test_g(nazwa: str) -> None:\n    assert obsluz(nazwa)\n'
IMPORT_FAIL = _block(("kod/liczby.py", "def podwojona(x: int) -> int:\n", "from kod.nie_ma import LIMIT\n\n\ndef podwojona(x: int) -> int:\n"), name="import z FAIL")
MEMO = (
    "_PAMIEC: dict[int, int] = {}\n\n\ndef _norma(x: int) -> int:\n    try:\n        return _PAMIEC[x]\n    except KeyError:\n"
    "        _PAMIEC[x] = x\n        return x\n\n\ndef podwojona(x: int) -> int:\n    return _norma(x) * 2\n"
)


@dataclass(frozen=True)
class Sample:
    """HEAD z plikami ``head`` po FAIL z ``x * 3`` w ``podwojona``, blok mutacji ``mutation`` (``None``: żaden werdykt
    go nie ma), początek stanu w linii dowodu i jej fragment ``tail`` dalej."""

    head: dict[str, str]
    mutation: str | None
    state: str
    node: str = NODE
    tail: str = ""


PROBKI_TESTU = {
    "prawdziwy-straznik": Sample({"tests/test_g.py": TEST_G}, TRIPLED, "WYKRYTA | z bloku ### Mutacja W1 r1: x * 3 z FAIL → 1 failed"),
    "test-innej-funkcji": Sample({"tests/test_g.py": TEST_G.replace("podwojona(3) == 6", "podwojona(0) == 0")}, TRIPLED, "NIEWYKRYTA | x * 3 z FAIL: NIEWYKRYTA: 1 passed"),
    # Sonda r1 W1, r2 W1 i r3 W1 #2197: test padał na drzewie FAIL tylko przez nazwę dodaną po FAIL; z mutacją z bloku ta
    # nazwa stoi, więc test pada tylko wtedy, gdy łapie błąd.
    "test-nazwy-dodanej-po-fail": Sample(
        {"kod/liczby.py": GOOD + "\n\nWERSJA = 2\n", "tests/test_g.py": "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.podwojona(0) == 0\n    assert kod.liczby.WERSJA == 2\n"},
        TRIPLED,
        "NIEWYKRYTA | x * 3 z FAIL: NIEWYKRYTA: 1 passed",
    ),
    # Sonda r3 W2 #2197: pomocnik HEAD w tym samym pliku zgłasza i łapie ``KeyError``; dowód nie porównuje wyjątków, więc
    # prawdziwy strażnik przechodzi.
    "prawdziwy-straznik-z-wyjatkiem-zlapanym-w-kodzie-head": Sample(
        {"kod/liczby.py": MEMO, "tests/test_g.py": TEST_G},
        _block(("kod/liczby.py", "return _norma(x) * 2", "return _norma(x) * 3")),
        "WYKRYTA | z bloku ### Mutacja W1 r1",
    ),
    "dwie-mutacje-jedna-niewykryta": Sample(
        {"tests/test_g.py": TEST_G},
        json.dumps([{"nazwa": "x * 3", "zmiany": [["kod/liczby.py", "return x * 2", "return x * 3"]]}, {"nazwa": "x + 2", "zmiany": [["kod/liczby.py", "return x + 1", "return x + 2"]]}]),
        "NIEWYKRYTA | x + 2: NIEWYKRYTA: 1 passed",
    ),
    # Sonda #2197 r4 W1: z mutacją pytest nie uruchamia węzła (kod 4), a Required CI uruchamia cały plik i jest zielone.
    "wezel-znika-z-mutacja": Sample(
        {"kod/pliki.py": FORMATS, "tests/test_g.py": TEST_FORMATS},
        _block(("kod/pliki.py", '("a", "b")', '("a",)'), name="lista bez b z FAIL"),
        "NIEWYKRYTA | lista bez b z FAIL: NIEWYKRYTA: ",
        "tests/test_g.py::test_g[b]",
        "(pytest nie uruchomił testu z polecenia, kod 4, a pliki testów polecenia z mutacją się zbierają: ",
    ),
    # Sonda #2224 r1 W1: z mutacją nie importuje się moduł węzła albo ``tests/conftest.py`` (pytest kod 4 jak przy
    # zniknięciu węzła), a Required CI, które uruchamia plik, pada; to wykrycie.
    "modul-wezla-nie-importuje-sie-z-mutacja": Sample(
        {"tests/test_g.py": TEST_G},
        IMPORT_FAIL,
        "WYKRYTA | z bloku ### Mutacja W1 r1: import z FAIL → ",
        tail="(pliki testów polecenia z mutacją się nie zbierają, kod 2: ",
    ),
    "plik-wezla-bez-testow-z-mutacja": Sample(
        {
            "kod/flagi.py": "WLACZONE = True\n",
            "tests/test_g.py": "from kod.flagi import WLACZONE\n\nif WLACZONE:\n\n    def test_g() -> None:\n        assert WLACZONE\n",
        },
        _block(("kod/flagi.py", "WLACZONE = True", "WLACZONE = False"), name="flaga wyłączona z FAIL"),
        "NIEWYKRYTA | flaga wyłączona z FAIL: NIEWYKRYTA: ",
        tail="a pliki testów polecenia z mutacją się zbierają: ",
    ),
    "conftest-nie-importuje-sie-z-mutacja": Sample(
        {"tests/test_g.py": TEST_G, "tests/conftest.py": "import kod.liczby\n"},
        IMPORT_FAIL,
        "WYKRYTA | z bloku ### Mutacja W1 r1: import z FAIL → ",
        tail="(pliki testów polecenia z mutacją się nie zbierają, kod 4: ",
    ),
    "blok-zmienia-test": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("tests/test_g.py", "== 6", "== 7")),
        "ODMOWA | blok ### Mutacja W1 r1: zmiana w tests/test_g.py: zła postać to kod, konfiguracja albo reguła, które test ma złapać, a nie test",
    ),
    # Sonda #2197 r6 D1: APFS macOS nanosi ``Tests/test_g.py`` na test, a Linux nie ma takiego pliku; odmowa ta sama
    # na każdym systemie.
    "blok-zmienia-test-pod-inna-wielkoscia-liter": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("Tests/test_g.py", "== 6", "== 7")),
        "ODMOWA | blok ### Mutacja W1 r1: zmiana w Tests/test_g.py: zła postać to kod, konfiguracja albo reguła, które test ma złapać, a nie test",
    ),
    "blok-z-pusta-sciezka": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("", "return x * 2", "return x * 3")),
        "ODMOWA | x * 3 z FAIL: . to katalog, a nie plik na HEAD scalonym z bazą: recenzent następnej rundy odnawia blok",
    ),
    "blok-ze-sciezka-katalogu-i-pusta-kotwica": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("kod", "", "X = 1\n")),
        "ODMOWA | x * 3 z FAIL: kod to katalog, a nie plik na HEAD scalonym z bazą: recenzent następnej rundy odnawia blok",
    ),
    "pominiety-na-head": Sample({"tests/test_g.py": TEST_G.replace("def test_g", "import pytest\n\n\n@pytest.mark.skip\ndef test_g")}, TRIPLED, "NIEWYKRYTA | x * 3 z FAIL: NIEWYKRYTA: 1 skipped"),
    "brak-bloku": Sample({"tests/test_g.py": TEST_G}, None, "ODMOWA | żaden werdykt PR nie ma bloku ### Mutacja W1 r1 ze złą postacią do naniesienia na HEAD: recenzent następnej rundy dopisuje blok"),
    "kotwica-nieobecna-na-head": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("kod/liczby.py", "return x * 4", "return x * 3")),
        "ODMOWA | x * 3 z FAIL: kotwicy nie ma dokładnie raz w kod/liczby.py: 'return x * 4' na HEAD scalonym z bazą: recenzent następnej rundy odnawia blok ### Mutacja W1 r1",
    ),
    "kotwica-dwa-razy-na-head": Sample(
        {"tests/test_g.py": TEST_G},
        _block(("kod/liczby.py", "return x", "return 3 * x")),
        "ODMOWA | x * 3 z FAIL: kotwicy nie ma dokładnie raz w kod/liczby.py: 'return x' na HEAD scalonym z bazą: recenzent następnej rundy odnawia blok",
    ),
    "blok-z-poleceniem": Sample(
        {"tests/test_g.py": TEST_G},
        json.dumps([{"nazwa": "m", "zmiany": [["kod/liczby.py", "return x * 2", "return x * 3"]], "polecenie": ["-c", "raise SystemExit(1)"]}]),
        "ODMOWA | blok ### Mutacja W1 r1: wpis ma tylko klucze nazwa i zmiany, bo polecenie daje selektor strażnika pytest: recenzent następnej rundy odnawia blok",
    ),
    "blok-nie-json": Sample({"tests/test_g.py": TEST_G}, "[{nazwa: m}]", "ODMOWA | blok ### Mutacja W1 r1: to nie JSON"),
}


@wymaga_piaskownicy
@pytest.mark.parametrize("name", PROBKI_TESTU)
def test_dowod_testu_przyjmuje_test_ktory_pada_tylko_przez_mutacje_recenzenta(tmp_path: Path, name: str) -> None:
    """Węzeł bez mutacji przechodzi, a z każdą mutacją najnowszego bloku pada: tylko wtedy ``WYKRYTA``; bez bloku albo
    z kotwicą, której na HEAD nie ma dokładnie raz, odmowa mówi recenzentowi następnej rundy, co zrobić."""

    sample = PROBKI_TESTU[name]
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, **sample.head})

    outcome = pull.prove(f"pytest {sample.node}", mutation=sample.mutation)

    assert outcome.detected is sample.state.startswith("WYKRYTA"), outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | {sample.state}" in outcome.line, outcome.line
    assert sample.tail in outcome.line, outcome.line


def _once(place: str) -> str:
    return f"import pathlib\nimport tempfile\n\n\ndef test_g() -> None:\n    slad = {place}\n    assert not slad.exists()\n    slad.write_text('1')\n"


ONCE = _once("pathlib.Path({slad})")
GIT = (
    "import subprocess\n\n\ndef _git(*arguments: str) -> str:\n"
    "    return subprocess.run(['git', *arguments], capture_output=True, text=True, input='slad', check=False).stdout.strip()\n\n\n"
)
SYSV = (
    "import ctypes\nimport zlib\n\nfrom kod.liczby import podwojona\n\n_LIBC = ctypes.CDLL(None, use_errno=True)\n"
    "_LIBC.shmget.argtypes = (ctypes.c_int, ctypes.c_size_t, ctypes.c_int)\nKLUCZ = zlib.crc32({slad}.encode()) & 0x3FFFFFFF | 1\n\n\n"
)
ONCE_SYSV = SYSV + "def test_g() -> None:\n    assert _LIBC.shmget(KLUCZ, 1, 0o3600) >= 0, 'ślad poprzedniego biegu'\n"
LOCK = "import multiprocessing\n\n\ndef test_g() -> None:\n    with multiprocessing.Lock():\n        pass\n"
UNTOUCHED = "NIEWYKRYTA | x * 3 z FAIL: NIEWYKRYTA: 1 passed"
REFUSED = f"ODMOWA | {NODE} na HEAD scalonym z bazą bez mutacji nie przechodzi: 1 failed"


@dataclass(frozen=True)
class Trace:
    test: str
    state: str
    where: str = "tmp_path"
    found: bool = False
    platform: str | None = None


SONDY_SLADU = {
    "tmpdir-biegu": Trace(_once("pathlib.Path(tempfile.gettempdir()) / 'slad.txt'"), UNTOUCHED),
    "home-biegu": Trace(_once("pathlib.Path.home() / 'slad.txt'"), UNTOUCHED),
    "plik-w-kopii": Trace(_once("pathlib.Path('slad.txt')"), UNTOUCHED),
    "zapis-do-dev-null": Trace("import os\n\n\ndef test_g() -> None:\n    with open(os.devnull, 'w') as sink:\n        sink.write('1')\n", UNTOUCHED),
    "konfiguracja-gita-kopii": Trace(
        GIT + "def test_g() -> None:\n    assert _git('config', '--local', '--get', 'straznik.slad') == ''\n    _git('config', '--local', 'straznik.slad', '1')\n", UNTOUCHED
    ),
    "obiekt-gita-kopii": Trace(
        GIT + "def test_g() -> None:\n    assert subprocess.run(['git', 'cat-file', '-e', _git('hash-object', '--stdin')], check=False).returncode != 0\n"
        "    _git('hash-object', '-w', '--stdin')\n",
        UNTOUCHED,
    ),
    "sciezka-bezwzgledna": Trace(ONCE, REFUSED),
    "katalog-tmp": Trace(ONCE, REFUSED, where="/tmp"),
    "slad-na-przemian": Trace(
        "import pathlib\n\n\ndef test_g() -> None:\n    slad = pathlib.Path({slad})\n    if slad.exists():\n        slad.unlink()\n"
        "        raise AssertionError('ślad poprzedniego biegu')\n    slad.write_text('1')\n",
        REFUSED,
    ),
    "blad-dopiero-przy-sladzie": Trace(
        "import pathlib\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    slad = pathlib.Path({slad})\n"
        "    if slad.exists():\n        assert podwojona(3) == 6\n    slad.write_text('1')\n",
        REFUSED,
    ),
    "katalog-obok-kopii-z-tym-samym-przedrostkiem": Trace(_once("pathlib.Path.cwd().with_name(pathlib.Path.cwd().name + '-obok')"), REFUSED),
    "wyjscie-z-kopii-przez-kropki": Trace(_once("pathlib.Path('..') / 'slad.txt'"), REFUSED),
    "dowiazanie-z-kopii-na-zewnatrz": Trace(
        "import os\nimport pathlib\n\n\ndef test_g() -> None:\n    slad = pathlib.Path('slad.txt')\n    assert not slad.is_symlink()\n"
        "    os.symlink({slad}, slad)\n    slad.write_text('1')\n",
        REFUSED,
    ),
    "pamiec-dzielona-obok-dev-null": Trace(ONCE, REFUSED, where="/dev/shm", platform="linux"),
    "semafor-multiprocessing-w-dev-shm-linuksa": Trace(LOCK, REFUSED, platform="linux"),
    "semafor-multiprocessing-poza-plikami-macos": Trace(LOCK, UNTOUCHED, platform="darwin"),
    "metadane-pliku-poza-kopia": Trace(
        "import os\nimport pathlib\n\n\ndef test_g() -> None:\n    slad = pathlib.Path({slad})\n    assert slad.stat().st_mtime != 1\n    os.utime(slad, (1, 1))\n",
        REFUSED,
        found=True,
        platform="darwin",
    ),
}


def _platform(platform: str | None) -> list[pytest.MarkDecorator]:
    return [] if platform is None else [pytest.mark.skipif(sys.platform != platform, reason=f"przypadek piaskownicy systemu {platform}")]


def _trace(tmp_path: Path, where: str) -> Path:
    return tmp_path / "slad.txt" if where == "tmp_path" else Path(where) / f"straznik-sonda-{uuid.uuid4().hex}.txt"


@wymaga_piaskownicy
@pytest.mark.parametrize("name", [pytest.param(name, marks=_platform(trace.platform)) for name, trace in SONDY_SLADU.items()])
def test_slad_biegu_w_srodowisku_biegu_znika_z_nim_a_zapis_poza_nim_to_odmowa_systemu(tmp_path: Path, name: str) -> None:
    trace = SONDY_SLADU[name]
    where = _trace(tmp_path, trace.where)
    if trace.found:
        where.write_text("0")
    before = where.stat().st_mtime if trace.found else None
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, "tests/test_g.py": _with_trace(trace.test, str(where))})

    try:
        outcome = pull.prove(f"pytest {NODE}", mutation=TRIPLED)
        after = where.stat().st_mtime if where.exists() else None
    finally:
        if trace.where != "tmp_path":
            where.unlink(missing_ok=True)

    assert not outcome.detected, outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | {trace.state}" in outcome.line, outcome.line
    assert after == before, f"bieg dowodu zmienił {where} poza swoim środowiskiem"


def _remove_segment(trace: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.shmget.argtypes = (ctypes.c_int, ctypes.c_size_t, ctypes.c_int)
    segment = libc.shmget(zlib.crc32(trace.encode()) & 0x3FFFFFFF | 1, 0, 0)
    if segment >= 0:
        libc.shmctl(segment, 0, None)


@wymaga_piaskownicy
def test_stan_uslugi_systemu_poza_plikami_ktory_wywraca_bieg_bez_mutacji_to_odmowa(tmp_path: Path) -> None:
    trace = str(tmp_path / "slad.txt")
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, "tests/test_g.py": _with_trace(ONCE_SYSV, trace)})

    try:
        outcome = pull.prove(f"pytest {NODE}", mutation=TRIPLED)
    finally:
        _remove_segment(trace)

    assert not outcome.detected, outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | ODMOWA | {NODE} bez mutacji pada po biegach z mutacją (1 failed" in outcome.line, outcome.line


COLLECTED = (
    "import pathlib\nimport sys\n\nfrom kod.flagi import WLACZONE\n\nif sys.argv[0] == '-c':\n    pathlib.Path({slad}).write_text('1')\n\n"
    "if WLACZONE:\n\n    def test_g() -> None:\n        assert WLACZONE\n"
)


@wymaga_piaskownicy
def test_zbieranie_plikow_testow_po_mutacji_bez_wezla_biegnie_w_piaskownicy(tmp_path: Path) -> None:
    trace = tmp_path / "slad.txt"
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, "kod/flagi.py": "WLACZONE = True\n", "tests/test_g.py": _with_trace(COLLECTED, str(trace))})

    outcome = pull.prove(f"pytest {NODE}", mutation=_block(("kod/flagi.py", "WLACZONE = True", "WLACZONE = False"), name="flaga wyłączona z FAIL"))

    assert "pliki testów polecenia z mutacją się nie zbierają" in outcome.line, outcome.line
    assert not trace.exists()


PLUGIN = "import pathlib\n\nfrom mypy.plugin import Plugin\n\npathlib.Path({slad}).write_text('1')\n\n\ndef plugin(version: str) -> type[Plugin]:\n    return Plugin\n"


@wymaga_ruff_i_mypy
@wymaga_piaskownicy
def test_krok_mypy_ktory_pisze_poza_kopia_biegu_to_odmowa_systemu_a_nie_wynik_dowodu(tmp_path: Path) -> None:
    trace = tmp_path / "slad.txt"
    configured = PYPROJECT.format(mypy='plugins = ["wtyczka.py"]', ruff="", banned="")
    pull = _pull(tmp_path, TYPED, {**TYPED_FIX, "wtyczka.py": _with_trace(PLUGIN, str(trace)), "pyproject.toml": configured})

    outcome = pull.prove("mypy", (("kod/uzycie.py", 5, 5),), scopes=(("kod/uzycie.py", 4, 5),))

    assert not outcome.detected, outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | ODMOWA | na HEAD scalonym z bazą bez przywrócenia krok skończył się kodem 2 bez znalezisk (mypy: " in outcome.line, outcome.line
    assert not trace.exists()


@wymaga_piaskownicy
@pytest.mark.parametrize("guard", ["mypy", f"pytest {NODE}"])
def test_dowod_bez_piaskownicy_systemu_to_odmowa_przed_pierwszym_biegiem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard: str) -> None:
    pull = _fixed(tmp_path)
    monkeypatch.setattr(piaskownica, "unavailable", lambda: "jądro bez Landlock")

    outcome = pull.prove(guard, scopes=SCOPE, mutation=TRIPLED)

    assert not outcome.detected, outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | ODMOWA | jądro bez Landlock: każdy bieg dowodu biegnie w piaskownicy systemu" in outcome.line, outcome.line


@wymaga_piaskownicy
@pytest.mark.parametrize(
    ("head", "fragment"),
    [
        ({"tests/test_g.py": TEST_G.replace("== 6", "== 7")}, f"ODMOWA | {NODE} na HEAD scalonym z bazą bez mutacji nie przechodzi: 1 failed"),
        ({"tests/test_g.py": TEST_G.replace("def test_g", "def test_inny")}, f"ODMOWA | {NODE} na HEAD scalonym z bazą bez mutacji nie przechodzi: "),
    ],
    ids=["pada", "bez-wezla"],
)
def test_dowod_testu_odmawia_wezla_ktory_na_head_bez_mutacji_nie_przechodzi(tmp_path: Path, head: dict[str, str], fragment: str) -> None:
    """Węzeł, który pada bez mutacji (np. tylko na Windows przechodzi) albo którego nie ma, niczego nie dowodzi."""

    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, **head})

    outcome = pull.prove(f"pytest {NODE}", mutation=TRIPLED)

    assert not outcome.detected and fragment in outcome.line, outcome.line


@pytest.mark.parametrize(("before_test_proof", "state"), [(False, "ODMOWA | brak - test przechodzi tylko w wątku sprzed wdrożenia dowodu testu"), (True, "WYJĄTEK brak - test")])
def test_brak_testu_przechodzi_tylko_w_watku_sprzed_wdrozenia_dowodu_testu(tmp_path: Path, before_test_proof: bool, state: str) -> None:
    """Sonda luki G3: ``brak - test`` przechodziło bez testu, który łapie błąd. Po wdrożeniu dowodu testu
    (``bramka_straznika.TEST_MARKER``) strażnik-test to ``pytest <węzeł>`` z blokiem mutacji recenzenta."""

    pull = _fixed(tmp_path)

    outcome = pull.prove("brak - test", before_test_proof=before_test_proof)

    assert outcome.detected is before_test_proof, outcome.line
    assert f"#5 W1 r1 | {pull.failed[:8]} | {state}" in outcome.line, outcome.line


@dataclass(frozen=True)
class Gap:
    """Granica: HEAD z plikami ``head`` po FAIL z ``x * 3``, selektor ``guard``, blok ``mutation`` i wątek sprzed dowodu
    testu (``before_test_proof``)."""

    head: dict[str, str]
    guard: str
    mutation: str | None = None
    before_test_proof: bool = False
    found: bool = False
    segment: bool = False
    platform: str | None = None


# Granice dowodu (ADR 0042, „Konsekwencje” i aneks): każda próbka przechodzi dowód, choć strażnik nie łapie Ważnego
# z ``Gdzie``.
ZNANE_LUKI_STRAZNIKA = {
    # W wątku sprzed wdrożenia dowodu testu ``brak - test`` przechodzi przy Ważnym w kodzie także bez testu, który łapie
    # błąd z ``Gdzie``, i przy Ważnym, które zamknąłby typ; to ocenia recenzent następnej rundy (skill ``przeglad``).
    "brak - test: wątek sprzed dowodu testu bez testu, który łapie błąd": Gap({}, "brak - test", before_test_proof=True),
    # Usunięcia kodu z ``Gdzie`` też nie dowodzi narzędzie, więc ``brak - usunięte`` przechodzi, choć funkcja z ``Gdzie``
    # stoi na HEAD poprawiona w miejscu.
    "brak - usunięte: kod z Gdzie poprawiony w miejscu, a nie usunięty": Gap({}, "brak - usunięte"),
    # Mutacja szersza niż błąd z Ważnego (cała funkcja zamiast ``x * 3``) łapie test innej zmiany tej funkcji; wierność
    # bloku ocenia recenzent następnej rundy, który go czyta.
    "pytest: mutacja szersza niż błąd łapie test innej zmiany": Gap(
        {
            "kod/liczby.py": GOOD.replace("    return x * 2\n", "    if x < 0:\n        raise ValueError(x)\n    return x * 2\n"),
            "tests/test_g.py": "import pytest\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    with pytest.raises(ValueError):\n        podwojona(-1)\n",
        },
        f"pytest {NODE}",
        _block(("kod/liczby.py", "    if x < 0:\n        raise ValueError(x)\n    return x * 2\n", "    return x * 3\n")),
    ),
    # Wierna mutacja (kod z FAIL: ujemne razy 3) łapana inną drogą niż błąd z Ważnego (sonda #2197 r4 D2): test podaje
    # napis, na którym porównanie z FAIL zgłasza ``TypeError``, a ujemnych liczb nie sprawdza.
    "pytest: wierna mutacja łapana inną drogą niż błąd": Gap(
        {"tests/test_g.py": "from kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    assert podwojona('ab') == 'abab'  # type: ignore[arg-type]\n"},
        f"pytest {NODE}",
        _block(("kod/liczby.py", "    return x * 2\n", "    return x * 2 if x >= 0 else x * 3\n"), name="ujemne razy 3 z FAIL"),
    ),
    # Sąsiad w sesji Required CI (sonda #2197 r6 W2): rejestr formatów wypełnia import ``kod.csv_format``, a poprawka
    # dodaje ten import do ``kod/eksport.py``. Dowód uruchamia węzeł sam, więc z mutacją, która import usuwa, test pada,
    # a zadanie pytest zbiera też ``tests/test_csv_format.py`` (każdy worker xdist zbiera wszystkie pliki zadania przed
    # pierwszym testem), który moduł formatu importuje, więc z błędem przechodzi; tak samo maskuje stan zostawiony przez
    # wcześniejszy test workera. To ocenia recenzent.
    "pytest: sąsiad w sesji Required CI ustawia stan modułu, który maskuje błąd": Gap(
        {
            "kod/formaty.py": "FORMATY: dict[str, str] = {}\n",
            "kod/csv_format.py": "from kod.formaty import FORMATY\n\nFORMATY['csv'] = 'przecinki'\n",
            "kod/eksport.py": "import kod.csv_format\nfrom kod.formaty import FORMATY\n\n\ndef opis(nazwa: str) -> str:\n    return FORMATY[nazwa]\n",
            "tests/test_g.py": "from kod.eksport import opis\n\n\ndef test_g() -> None:\n    assert opis('csv') == 'przecinki'\n",
            "tests/test_csv_format.py": "import kod.csv_format\nfrom kod.formaty import FORMATY\n\n\ndef test_csv() -> None:\n    assert FORMATY['csv'] == 'przecinki'\n",
        },
        f"pytest {NODE}",
        _block(("kod/eksport.py", "import kod.csv_format\n", ""), name="eksport bez importu, który rejestruje csv, z FAIL"),
    ),
    # Test tekstu definicji zamiast jej zachowania pada z mutacją tego tekstu; dowód nie ocenia, co test sprawdza.
    "pytest: test tekstu definicji zamiast jej zachowania": Gap(
        {"tests/test_g.py": "import inspect\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    assert 'x * 2' in inspect.getsource(podwojona)\n"},
        f"pytest {NODE}",
        TRIPLED,
    ),
    "pytest: mutacja pisze poza piaskownicą, więc odmowa systemu wywraca test, a Required CI ten zapis przyjmuje": Gap(
        {
            "kod/zapis.py": "import pathlib\n\n\ndef zapisz(folder: pathlib.Path) -> None:\n    (folder / 'wynik.txt').write_text('1')\n",
            "tests/test_g.py": "import pathlib\n\nfrom kod.zapis import zapisz\n\n\ndef test_g(tmp_path: pathlib.Path) -> None:\n    zapisz(tmp_path)\n",
        },
        f"pytest {NODE}",
        _block(("kod/zapis.py", "(folder / 'wynik.txt')", "pathlib.Path({slad})"), name="zapis poza folderem z FAIL"),
    ),
    "pytest: stan usługi systemu poza plikami sprawdza błąd dopiero przy śladzie poprzedniego biegu": Gap(
        {"tests/test_g.py": SYSV + "def test_g() -> None:\n    if _LIBC.shmget(KLUCZ, 1, 0o600) >= 0:\n        assert podwojona(3) == 6\n    _LIBC.shmget(KLUCZ, 1, 0o1600)\n"},
        f"pytest {NODE}",
        TRIPLED,
        segment=True,
    ),
    "pytest: Landlock nie broni metadanych pliku poza kopią, więc ślad w czasie zmiany pliku sprawdza błąd dopiero w następnym biegu": Gap(
        {
            "tests/test_g.py": (
                "import os\nimport pathlib\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    slad = pathlib.Path({slad})\n"
                "    if slad.stat().st_mtime == 1:\n        assert podwojona(3) == 6\n    os.utime(slad, (1, 1))\n"
            )
        },
        f"pytest {NODE}",
        TRIPLED,
        found=True,
        platform="linux",
    ),
}


@pytest.mark.parametrize(
    "name",
    [pytest.param(name, marks=[*_platform(gap.platform), *([wymaga_piaskownicy] if gap.guard.startswith(Kind.PYTEST.value) else [])]) for name, gap in ZNANE_LUKI_STRAZNIKA.items()],
)
def test_znane_luki_straznika_przechodza_przez_dowod(tmp_path: Path, name: str) -> None:
    gap = ZNANE_LUKI_STRAZNIKA[name]
    trace = tmp_path / "slad.txt"
    if gap.found:
        trace.write_text("0")
    head = {path: _with_trace(text, str(trace)) for path, text in gap.head.items()}
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, **head})

    try:
        outcome = pull.prove(gap.guard, scopes=SCOPE, before_test_proof=gap.before_test_proof, mutation=gap.mutation and _with_trace(gap.mutation, str(trace)))
    finally:
        if gap.segment:
            _remove_segment(str(trace))

    assert outcome.detected, f"dowód odmawia już luki „{name}”: usuń ją ze ZNANE_LUKI_STRAZNIKA ({outcome.line})"


# Ścieżka ``tmp_path`` runnera Windows w Required CI (#2197 r6 W1, job ``pytest (Python 3.13, …)``).
WINDOWS_TRACE = r"C:\Users\runneradmin\AppData\Local\Temp\pytest-of-runneradmin\pytest-0\test_g0\slad.txt"


SOURCES = {
    f"{name}: {path}": text
    for name, head in [
        *((name, sample.head) for name, sample in PROBKI_TESTU.items()),
        *((name, {"tests/test_g.py": trace.test}) for name, trace in SONDY_SLADU.items()),
        ("pamiec-uslugi-systemu", {"tests/test_g.py": ONCE_SYSV}),
        ("wtyczka-mypy", {"wtyczka.py": PLUGIN}),
        ("zbieranie-po-mutacji", {"tests/test_g.py": COLLECTED}),
        *((name, gap.head) for name, gap in ZNANE_LUKI_STRAZNIKA.items()),
    ]
    for path, text in head.items()
    if path.endswith(".py")
}


@pytest.mark.parametrize("source", SOURCES)
def test_zrodlo_kazdej_probki_dowodu_testu_kompiluje_sie_ze_sladem_pod_sciezka_windows(source: str) -> None:
    """Próbka wstawia ścieżkę ``tmp_path`` do źródła testu (``{slad}``) tylko przez ``_with_trace``, więc z ukośnikami
    wstecznymi Windows źródło jest tym samym Pythonem; ścieżka w cudzysłowie bez ucieczki to ``SyntaxError``
    i czerwona podstawa dowodu tylko na Windows (#2197 r6 W1), a ten test łapie to na każdym systemie."""

    compile(_with_trace(SOURCES[source], WINDOWS_TRACE), source, "exec")
