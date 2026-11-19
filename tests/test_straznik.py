"""Dowód strażnika Ważnego (``tools/lib/straznik.py``, ADR 0042) na małym repozytorium Gita: gałąź PR od ``main``
z commitem werdyktu ``FAIL`` z błędem w miejscu ``Gdzie`` i HEAD z poprawką i strażnikiem z zamkniętej listy.

Każdy przypadek tabeli z docstringu modułu ma tu przebieg: strażnik pada na błędzie z SHA ``FAIL`` (``WYKRYTA``),
strażnik, który błędu nie łapie, nie przechodzi, a format z konfiguracji PR wyniku nie zmienia. Granice stoją
w ``ZNANE_LUKI_STRAZNIKA`` i przechodzą dowód, dopóki konstrukcja ich nie zamknie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys

import pytest

import potomne
import srodowisko_ci
import straznik
from straznik import Guard, Kind
from kroki_lokalne import MYPY_PLATFORMS
from tests.fixtures.git_repo import commit, git
from tests.fixtures.znane_luki import wymaga_ruff_i_mypy

# Dowód testu biegnie na Linuksie i macOS, jak każdy dowód w środowisku Required CI (``srodowisko_ci.built`` odmawia
# Windows), a plugin rozjazdu potrzebuje ``sys.monitoring``.
dowod_testu = pytest.mark.skipif(sys.platform == "win32", reason="dowód strażnika biegnie na Linuksie i macOS (srodowisko_ci.built)")

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

    def prove(self, guard: str, places: Places = WHERE, *, scopes: Places = (), prose: Places = (), before_test_proof: bool = False) -> straznik.Outcome:
        """Dowód jednego Ważnego; ``scopes`` i ``prose`` to linie z FAIL, które podaje ``tools/na_scalonych_pr.py``.
        Mypy, ruff i pytest biegną tu Pythonem testów na kopii HEAD, bo te testy sprawdzają przywrócenie błędu;
        środowisko Required CI z ``srodowisko_ci.built``, którym biegnie dowód, sprawdza ``tests/test_srodowisko_ci.py``."""

        case = straznik.Case("#5 W1 r1", self.failed, self.fork, places, scopes, prose)
        chosen = straznik.parse(guard)
        if chosen.kind in straznik.EXEMPT:
            [outcome] = straznik.exempt(self.root, chosen, self.head, self.fork, [case], before_test_proof=before_test_proof)
            return outcome
        with potomne.commit_copy(self.root, self.head) as copy:
            environment = straznik.Environment(self.head, copy, Path(sys.executable), srodowisko_ci.variables())
            [outcome] = straznik.prove(self.root, chosen, environment, [case])
        return outcome


def _pull(tmp_path: Path, failed: dict[str, str], head: dict[str, str], base: dict[str, str] | None = None) -> Pull:
    """``main`` z ``BASE`` (z ``base`` zamiast tych plików), commit werdyktu ``FAIL`` z plikami ``failed`` i HEAD z ``head``
    na nim."""

    root = tmp_path / "repo"
    files = {"pyproject.toml": PYPROJECT.format(mypy="", ruff="", banned=""), **BASE, **(base or {})}
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
        "mypy-z-flaga",
        "ast-grep-bez-id",
        "brak-bez-powodu",
        "brak-z-powodem-spoza-listy",
        "mutacja-autora",
    ],
)
def test_selektor_spoza_listy_to_odmowa_z_postaciami_listy(text: str) -> None:
    """Test wskazuje jeden węzeł pytest w ``tests/`` (test albo jego parametr), bez opcji, bo dowód liczy padnięcie tego
    węzła; inna postać to odmowa z listą."""

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


# Dowód ``pytest <węzeł>`` na próbkach G3 (G3/DESIGN.md programu chwastów, ``przypadki.py``): strażnik pada, gdy
# definicje z ``Gdzie`` wracają z FAIL, a sondy rund r1–r3 #2116 i sondy przeciw kształtom dowodu (A1–A7b) padają tylko
# przez coś, co poprawka dodała albo zmieniła obok, więc dowód ich nie przyjmuje.
GOOD = BASE["kod/liczby.py"]
TEST_G = "from kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    assert podwojona(3) == 6\n"
NODE = "tests/test_g.py::test_g"
CLASS = "\n\nclass Mnoznik:\n    def nastepna(self, x: int) -> int:\n        return x + 1\n"
OWNER = {"kod/wlasciciel.py": "def razy_dwa(x: int) -> int:\n    return x * 2\n"}
OWNED = {**OWNER, "kod/liczby.py": "from kod.wlasciciel import razy_dwa\n\n\n" + GOOD.replace("x * 2", "razy_dwa(x)")}
FAILING_OWNER = "from kod.wlasciciel import razy_dwa\n\n\ndef test_razy_dwa() -> None:\n    assert razy_dwa(3) == 6\n"
HELPER = "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.razy(5, 7) == 35\n"
NEW_NAME = "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.podwojona(0) == 0\n    assert getattr(kod.liczby, 'NOWA', None) == 1\n"
METHODS = "class Mnoznik:\n    def podwojona(self, x: int) -> int:\n        return x * 2\n\n    def nastepna(self, x: int) -> int:\n        return x + 1\n"
SECOND = {"kod/wlasciciel.py": OWNER["kod/wlasciciel.py"], "kod/uzycie.py": "from kod.wlasciciel import razy_dwa\n\n\ndef opis(x: int) -> str:\n    return f'{razy_dwa(x)}'\n"}
RENAMED = "class Mnoznik:\n    def stara(self, x: int) -> int:\n        return x * 2\n\n\ndef podwojona(x: int) -> int:\n    return Mnoznik().stara(x) + x * 0\n"
ERRORS = "BLEDY = (ValueError,)\n\n\ndef czytaj(x: str) -> float | None:\n    try:\n        return float(int(x)) if len(x) < 400 else float(10 ** len(x))\n    except BLEDY:\n        return None\n"
CALLS = "def podwojona(x: int) -> int:\n    return x * 2\n\n\ndef nastepna(x: int) -> int:\n    return podwojona(0) + x + 1\n"
PERIOD = "from dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Okres:\n    dni: int\n\n\ndef okres(x: int) -> Okres:\n    return Okres(x * 2)\n"
PERIOD_HEAD = PERIOD.replace("    dni: int\n", "    dni: int\n    nazwa: str\n").replace("return Okres(x * 2)", "return Okres(x * 2, 'm')")
TEST_PERIOD = "from kod.okres import okres\n\n\ndef test_g() -> None:\n    assert okres(0).dni == 0\n"
DAYS = "def okres(x: int) -> dict[str, int]:\n    return {'dni': x * 2}\n"
READER = "from kod.okres import okres\n\n\ndef opis(x: int) -> str:\n    return str(okres(x)['dni'])\n"
BRANCHES = "import sys\n\nif sys.platform == 'win32':\n    def podwojona(x: int) -> int:\n        return x * 2\nelse:\n    def podwojona(x: int) -> int:\n        return x * 2\n"
VERSION = "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.podwojona(0) == 0\n    assert getattr(kod.liczby, 'WERSJA', None) == 2\n"
DATA = "def dane(x: int) -> dict[str, int]:\n    return {'dni': x}\n"
USES_DATA = "import kod.dane\n\n\ndef podwojona(x: int) -> int:\n    return kod.dane.dane(x)['dni'] * 2\n"
FIELDS = "POLA = ('dni',)\n\n\ndef podwojona(x: int) -> int:\n    (pole,) = POLA\n    return x * 2 if pole else 0\n"
SAFE_READER = "from kod.okres import okres\n\n\ndef opis(x: int) -> str:\n    try:\n        return str(okres(x)['dni'])\n    except KeyError:\n        return '?'\n"
HOMELY = "import pathlib\n\n\ndef podwojona(x: int) -> int:\n    try:\n        (pathlib.Path.home() / 'brak.txt').read_text()\n    except FileNotFoundError:\n        pass\n    return x * 2\n"
GUARDED = "from kod.liczby import podwojona\n\n\ndef opis(x: int) -> str:\n    try:\n        return str(podwojona(x))\n    except KeyError:\n        return '?'\n"
FIRST = "def pierwsza(x: list[int] | None) -> int:\n    return x[0] if x else 0\n"
CALLER = "from kod.liczby import podwojona\n\n\ndef opis(x: int) -> str:\n    return f'{podwojona(x)}'\n"


# Warunek, którym dowód odrzuca próbkę: drzewo FAIL przechodzi, padnięcie inne niż na drzewie FAIL, nowy wyjątek kodu
# przeszczepu, a przy odrzuconym prawdziwym strażniku zdanie, co zrobić.
NOT_ON_FAIL = "na drzewie FAIL (pliki PR spoza tests/ z treścią z FAIL) węzeł nie pada"
OTHERWISE = "inaczej niż na drzewie FAIL"
NEW_EXCEPTION = "zgłasza wyjątek, którego na drzewie FAIL nie zgłosił"
REACH_GDZIE = "strażnik musi na drzewie FAIL dojść do kodu z Gdzie i paść tak samo"


@dataclass(frozen=True)
class Sample:
    """Ważne z ``Gdzie`` ``where`` i strażnik ``node``: ``main`` z ``BASE`` i plikami ``base``, FAIL z ``failed``, HEAD
    z ``head``; ``proved`` mówi, czy dowód ma go przyjąć, a ``reason``, którym warunkiem go odrzuca."""

    failed: dict[str, str]
    head: dict[str, str]
    proved: bool
    where: Places = WHERE
    node: str = NODE
    base: dict[str, str] = field(default_factory=dict)
    reason: str = ""


PROBKI_TESTU = {
    # Prawdziwi strażnicy.
    "K0-test-funkcji-z-gdzie": Sample({"kod/liczby.py": BAD + CLASS}, {"kod/liczby.py": GOOD + CLASS, "tests/test_g.py": TEST_G}, True, base={"kod/liczby.py": GOOD + CLASS}),
    "R1-druga-droga-usunieta-test-wolajacego": Sample(
        {"kod/uzycie.py": "from kod.liczby import podwojona\n\n\ndef opis(x: int) -> str:\n    return f'{podwojona(x)}'\n", "kod/liczby.py": BAD},
        {**SECOND, "kod/liczby.py": "def nastepna(x: int) -> int:\n    return x + 1\n", "tests/test_g.py": "from kod.uzycie import opis\n\n\ndef test_g() -> None:\n    assert opis(3) == '6'\n"},
        True,
        (("kod/liczby.py", 1, 2),),
        base=SECOND,
    ),
    "R2-gdzie-w-kodzie-i-w-slabej-probce": Sample(
        {"kod/liczby.py": BAD, "tests/test_g.py": TEST_G.replace("podwojona(3) == 6", "podwojona(0) == 0")},
        {"kod/liczby.py": GOOD, "tests/test_g.py": TEST_G},
        True,
        (("kod/liczby.py", 2, 2), ("tests/test_g.py", 5, 5)),
    ),
    "A4-krotka-wyjatkow-modulu": Sample(
        {"kod/czytaj.py": ERRORS},
        {"kod/czytaj.py": ERRORS.replace("(ValueError,)", "(ValueError, OverflowError)"), "tests/test_czytaj.py": "from kod.czytaj import czytaj\n\n\ndef test_czytaj() -> None:\n    assert czytaj('9' * 400) is None\n"},
        True,
        (("kod/czytaj.py", 1, 1),),
        "tests/test_czytaj.py::test_czytaj",
        {"kod/czytaj.py": ERRORS.replace("(ValueError,)", "(TypeError,)")},
    ),
    "A5-poprawka-wola-nowego-pomocnika": Sample(
        {"kod/liczby.py": BAD},
        {"kod/pomoc.py": "def razy(x: int, k: int) -> int:\n    return x * k\n", "kod/liczby.py": "from kod.pomoc import razy\n\n\n" + GOOD.replace("x * 2", "razy(x, 2)"), "tests/test_g.py": TEST_G},
        True,
    ),
    # Sondy r1 #2116: test pada na drzewie FAIL tylko z braku nazwy dodanej przez poprawkę.
    "r1-P1a-test-wlasciciela-import-na-gorze": Sample({"kod/liczby.py": BAD}, {**OWNED, "tests/test_wlasciciel.py": FAILING_OWNER}, False, node="tests/test_wlasciciel.py::test_razy_dwa"),
    "r1-P1b-test-wlasciciela-import-w-tescie": Sample(
        {"kod/liczby.py": BAD},
        {**OWNED, "tests/test_wlasciciel.py": "def test_razy_dwa() -> None:\n    from kod.wlasciciel import razy_dwa\n\n    assert razy_dwa(3) == 6\n"},
        False,
        node="tests/test_wlasciciel.py::test_razy_dwa",
    ),
    "r1-P2-znacznik-dodany-po-fail": Sample(
        {"kod/liczby.py": BAD},
        {"kod/liczby.py": GOOD + "\n\nWERSJA = 2\n", "tests/test_wersja.py": "import kod.liczby\n\n\ndef test_wersja() -> None:\n    assert getattr(kod.liczby, 'WERSJA', None) == 2\n"},
        False,
        node="tests/test_wersja.py::test_wersja",
    ),
    # Sondy r2 #2116: kod testu sam wybiera wyjątek, którym pada na drzewie FAIL.
    "r2-K1-modul-wlasciciela-import-w-tescie": Sample(
        {"kod/liczby.py": BAD + CLASS},
        {
            **OWNER,
            "kod/liczby.py": (GOOD + CLASS).replace("x * 2", "razy_dwa(x)").replace("def podwojona", "from kod.wlasciciel import razy_dwa\n\n\ndef podwojona", 1),
            "tests/test_g.py": "def test_g() -> None:\n    from kod.wlasciciel import razy_dwa\n\n    assert razy_dwa(3) == 6\n",
        },
        False,
        base={"kod/liczby.py": GOOD + CLASS},
    ),
    "r2-S1-metoda-dodana-po-fail": Sample(
        {"kod/liczby.py": BAD + CLASS},
        {
            "kod/liczby.py": (GOOD + CLASS).replace("x * 2", "Mnoznik().razy_dwa(x)").replace("        return x + 1\n", "        return x + 1\n\n    def razy_dwa(self, x: int) -> int:\n        return x * 2\n"),
            "tests/test_g.py": "from kod.liczby import Mnoznik\n\n\ndef test_g() -> None:\n    assert Mnoznik().razy_dwa(3) == 6\n",
        },
        False,
        base={"kod/liczby.py": GOOD + CLASS},
    ),
    "r2-S2-monkeypatch-nazwy-dodanej-po-fail": Sample(
        {"kod/liczby.py": BAD + CLASS},
        {
            "kod/liczby.py": (GOOD + CLASS).replace("x * 2", "x * MNOZNIK") + "\n\nMNOZNIK = 2\n",
            "tests/test_g.py": "import pytest\n\nimport kod.liczby\n\n\ndef test_g(monkeypatch: pytest.MonkeyPatch) -> None:\n    monkeypatch.setattr(kod.liczby, 'MNOZNIK', 5)\n    assert kod.liczby.MNOZNIK == 5\n",
        },
        False,
        base={"kod/liczby.py": GOOD + CLASS},
    ),
    "r2-S3-opcja-narzedzia-dodana-po-fail": Sample(
        {"kod/liczby.py": BAD + CLASS + "\n\ndef main(argv: list[str]) -> int:\n    import argparse\n\n    parser = argparse.ArgumentParser()\n    return 0 if parser.parse_args(argv) else 1\n"},
        {
            "kod/liczby.py": GOOD + CLASS + "\n\ndef main(argv: list[str]) -> int:\n    import argparse\n\n    parser = argparse.ArgumentParser()\n    parser.add_argument('--podwojona', type=int)\n    return podwojona(parser.parse_args(argv).podwojona)\n",
            "tests/test_g.py": "from kod.liczby import main\n\n\ndef test_g() -> None:\n    assert main(['--podwojona', '0']) == 0\n",
        },
        False,
        base={"kod/liczby.py": GOOD + CLASS},
    ),
    # Sondy r3 #2116: ``Gdzie`` z zakresem funkcji, a poprawka dodaje nazwę tuż obok.
    "r3-P1-atrybut-modulu-nad-funkcja": Sample(
        {"kod/liczby.py": BAD},
        {**OWNED, "tests/test_g.py": "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.razy_dwa(2) == 4\n"},
        False,
        (("kod/liczby.py", 1, 2),),
    ),
    "r3-P2-pomocnik-pod-funkcja": Sample(
        {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD.replace("    return x * 2\n", "    return razy(x, 2)\n\n\ndef razy(x: int, k: int) -> int:\n    return x * k\n"), "tests/test_g.py": HELPER}, False, (("kod/liczby.py", 1, 2),)
    ),
    "r3-P3-pomocnik-nad-funkcja": Sample(
        {"kod/liczby.py": BAD}, {"kod/liczby.py": "def razy(x: int, k: int) -> int:\n    return x * k\n\n\n" + GOOD.replace("    return x * 2\n", "    return razy(x, 2)\n"), "tests/test_g.py": HELPER}, False, (("kod/liczby.py", 1, 2),)
    ),
    "r3-P4-metoda-pod-metoda": Sample(
        {"kod/klasa.py": METHODS.replace("x * 2", "x * 3")},
        {
            "kod/klasa.py": METHODS.replace("        return x * 2\n", "        return self.razy(x, 2)\n\n    def razy(self, x: int, k: int) -> int:\n        return x * k\n"),
            "tests/test_g.py": "from kod.klasa import Mnoznik\n\n\ndef test_g() -> None:\n    assert Mnoznik().razy(5, 7) == 35\n",
        },
        False,
        (("kod/klasa.py", 2, 3),),
        base={"kod/klasa.py": METHODS},
    ),
    # Sondy przeciw kształtom dowodu.
    "A1-linia-gdzie-wykonana-padniecie-na-nowej-nazwie": Sample({"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD + "\n\nNOWA = 1\n", "tests/test_g.py": NEW_NAME}, False),
    "A3-metoda-przemianowana-na-head": Sample(
        {"kod/liczby.py": RENAMED.replace("x * 0", "x * 1")},
        {"kod/liczby.py": RENAMED.replace("def stara", "def nowa").replace("Mnoznik().stara(x) + x * 0", "Mnoznik().nowa(x)") + "\n\nNOWA = 1\n", "tests/test_g.py": NEW_NAME},
        False,
        (("kod/liczby.py", 7, 7),),
        base={"kod/liczby.py": RENAMED},
    ),
    "A6-test-innej-poprawki-przez-funkcje-z-gdzie": Sample(
        {"kod/liczby.py": CALLS.replace("x * 2", "x * 3").replace("x + 1", "x + 2")},
        {"kod/liczby.py": CALLS, "tests/test_g.py": "from kod.liczby import nastepna\n\n\ndef test_g() -> None:\n    assert nastepna(1) == 2\n"},
        False,
        base={"kod/liczby.py": CALLS},
    ),
    "A7-pole-dataclass-dodane-przez-pr": Sample(
        {"kod/okres.py": PERIOD.replace("x * 2", "x * 3")},
        {"kod/okres.py": PERIOD_HEAD, "tests/test_g.py": TEST_PERIOD},
        False,
        (("kod/okres.py", 10, 10),),
        base={"kod/okres.py": PERIOD},
        reason=NOT_ON_FAIL,
    ),
    # Poprawka zmieniła klucz danych, które funkcja z ``Gdzie`` zwraca, a czyta je moduł spoza przeszczepu: przeszczep
    # pada na ``KeyError`` w tamtym module, a test błędu nie łapie (0 × 3 = 0 × 2), więc na drzewie FAIL przechodzi.
    "A8-klucz-danych-zmieniony-czyta-modul-spoza-przeszczepu": Sample(
        {"kod/okres.py": DAYS.replace("x * 2", "x * 3")},
        {
            "kod/okres.py": DAYS.replace("'dni'", "'liczba_dni'"),
            "kod/opis.py": READER.replace("'dni'", "'liczba_dni'"),
            "tests/test_g.py": "from kod.opis import opis\n\n\ndef test_g() -> None:\n    assert opis(0) == '0'\n",
        },
        False,
        (("kod/okres.py", 2, 2),),
        base={"kod/okres.py": DAYS, "kod/opis.py": READER},
        reason=NOT_ON_FAIL,
    ),
    "A8c-klucz-zlapany-w-module-spoza-przeszczepu-i-nazwa-po-fail": Sample(
        {"kod/okres.py": DAYS.replace("x * 2", "x * 3")},
        {
            "kod/okres.py": DAYS.replace("'dni'", "'liczba_dni'"),
            "kod/opis.py": SAFE_READER.replace("'dni'", "'liczba_dni'") + "\n\nNOWA = 1\n",
            "tests/test_g.py": "import kod.opis\nfrom kod.opis import opis\n\n\ndef test_g() -> None:\n    assert opis(0) == '0'\n    assert getattr(kod.opis, 'NOWA', None) == 1\n",
        },
        False,
        (("kod/okres.py", 2, 2),),
        base={"kod/okres.py": DAYS, "kod/opis.py": SAFE_READER},
        reason=OTHERWISE,
    ),
    # Prawdziwy strażnik, którego funkcja z ``Gdzie`` zgłasza i łapie wyjątek z katalogiem domowym biegu w komunikacie:
    # katalog każdego biegu jest inny, a porównanie liczy go jako ``<bieg>``.
    "K-wyjatek-z-katalogiem-biegu-w-komunikacie": Sample(
        {"kod/liczby.py": HOMELY.replace("x * 2", "x * 3")},
        {"kod/liczby.py": HOMELY, "tests/test_g.py": TEST_G},
        True,
        (("kod/liczby.py", 9, 9),),
        base={"kod/liczby.py": HOMELY},
    ),
    # Poprawka dodała parametr funkcji z ``Gdzie``: wołający z HEAD podaje drugi argument funkcji z FAIL, więc test, który
    # błędu nie łapie (0 × 3 = 0 × 2), pada na wywołaniu w pliku spoza przeszczepu i na drzewie FAIL na nazwie dodanej po
    # FAIL; wołający wraca z FAIL razem z funkcją, więc przeszczep przechodzi.
    "sygnatura-zmieniona-test-pada-tylko-na-wywolaniu": Sample(
        {"kod/liczby.py": BAD, "kod/uzycie.py": CALLER},
        {
            "kod/liczby.py": GOOD.replace("def podwojona(x: int) -> int:\n    return x * 2", "def podwojona(x: int, k: int) -> int:\n    return x * k"),
            "kod/uzycie.py": CALLER.replace("podwojona(x)}", "podwojona(x, 2)}") + "\n\nNOWA = 1\n",
            "tests/test_g.py": "import kod.uzycie\nfrom kod.uzycie import opis\n\n\ndef test_g() -> None:\n    assert opis(0) == '0'\n    assert getattr(kod.uzycie, 'NOWA', None) == 1\n",
        },
        False,
        base={"kod/uzycie.py": CALLER},
        reason="na przeszczepie z FAIL (kod/liczby.py:podwojona+kod/uzycie.py:opis) węzeł nie pada",
    ),
    # Funkcja z ``Gdzie`` w gałęzi bloku ``if`` modułu (jak ``tools/lib/potomne.py``): definicją jest cały blok, a nie
    # cały plik, więc nazwa dodana po FAIL obok bloku zostaje z HEAD (sonda #2197 r1 W1).
    "W1-funkcja-w-bloku-if-modulu-test-nazwy-po-fail": Sample(
        {"kod/liczby.py": BRANCHES.replace("        return x * 2\n", "        return x * 3\n").replace("return x * 3\nelse", "return x * 2\nelse")},
        {"kod/liczby.py": BRANCHES + "\n\nWERSJA = 2\n", "tests/test_g.py": VERSION},
        False,
        (("kod/liczby.py", 8, 8),),
        base={"kod/liczby.py": BRANCHES},
        reason="na przeszczepie z FAIL (kod/liczby.py:=podwojona) węzeł nie pada",
    ),
    # Rozjazd interfejsu HEAD w pliku przeszczepu wyjątkiem dowolnego rodzaju (``KeyError``, ``ValueError``), a test, który
    # błędu nie łapie, pada na drzewie FAIL na nazwie dodanej po FAIL: przeszczep pada inaczej niż drzewo FAIL (#2197 r1 W2).
    "W2-rozjazd-keyerror-w-pliku-przeszczepu-i-nazwa-po-fail": Sample(
        {"kod/liczby.py": USES_DATA.replace("* 2", "* 3")},
        {"kod/dane.py": DATA.replace("'dni'", "'liczba_dni'"), "kod/liczby.py": USES_DATA.replace("'dni'", "'liczba_dni'") + "\n\nNOWA = 1\n", "tests/test_g.py": NEW_NAME},
        False,
        (("kod/liczby.py", 5, 5),),
        base={"kod/dane.py": DATA, "kod/liczby.py": USES_DATA},
        reason=OTHERWISE,
    ),
    "W2-rozjazd-valueerror-w-pliku-przeszczepu-i-nazwa-po-fail": Sample(
        {"kod/liczby.py": FIELDS.replace("x * 2", "x * 3")},
        {"kod/liczby.py": "POLA = ('dni', 'nazwa')\n\n\ndef podwojona(x: int) -> int:\n    return x * 2\n\n\nNOWA = 1\n", "tests/test_g.py": NEW_NAME},
        False,
        (("kod/liczby.py", 6, 6),),
        base={"kod/liczby.py": FIELDS},
        reason=OTHERWISE,
    ),
    # Rozjazd w pliku spoza przeszczepu (A8) i podwójny zbieg: na drzewie FAIL test pada na nazwie dodanej po FAIL, na
    # przeszczepie na ``KeyError`` w module, który czyta nowy klucz, czyli inaczej. A8c: moduł łapie ``KeyError``, a test
    # pada tym samym ``AssertionError`` w innej linii niż na drzewie FAIL.
    "A8b-klucz-danych-w-module-spoza-przeszczepu-i-nazwa-po-fail": Sample(
        {"kod/okres.py": DAYS.replace("x * 2", "x * 3")},
        {
            "kod/okres.py": DAYS.replace("'dni'", "'liczba_dni'"),
            "kod/opis.py": READER.replace("'dni'", "'liczba_dni'") + "\n\nNOWA = 1\n",
            "tests/test_g.py": "import kod.opis\nfrom kod.opis import opis\n\n\ndef test_g() -> None:\n    assert opis(0) == '0'\n    assert getattr(kod.opis, 'NOWA', None) == 1\n",
        },
        False,
        (("kod/okres.py", 2, 2),),
        base={"kod/okres.py": DAYS, "kod/opis.py": READER},
        reason=OTHERWISE,
    ),
    # Rozjazd złapany w kodzie: ``KeyError`` funkcji z FAIL łapie wołający, a test sprawdza w jednej linii wynik, którego
    # błąd nie zmienia, i nazwę dodaną po FAIL, więc na przeszczepie i na drzewie FAIL pada tym samym ``AssertionError``
    # w tej samej linii; odrzuca go dopiero wyjątek kodu przeszczepu, którego na drzewie FAIL nie było.
    "W2-rozjazd-zlapany-w-kodzie-i-ta-sama-linia-testu": Sample(
        {"kod/liczby.py": USES_DATA.replace("* 2", "* 3")},
        {
            "kod/dane.py": DATA.replace("'dni'", "'liczba_dni'"),
            "kod/liczby.py": USES_DATA.replace("'dni'", "'liczba_dni'"),
            "kod/opis.py": GUARDED + "\n\nNOWA = 1\n",
            "tests/test_g.py": "import kod.opis\n\n\ndef test_g() -> None:\n    assert kod.opis.opis(0) == '0' and getattr(kod.opis, 'NOWA', None) == 1\n",
        },
        False,
        (("kod/liczby.py", 5, 5),),
        base={"kod/dane.py": DATA, "kod/liczby.py": USES_DATA, "kod/opis.py": GUARDED},
        reason=NEW_EXCEPTION,
    ),
    # Poprawka naprawiła indeks i dopuściła ``None`` w funkcji z ``Gdzie`` (kontrakt HEAD), a test, który błędu indeksu nie
    # łapie, podaje ``None`` z nazwy dodanej po FAIL: funkcja z FAIL pada na ``None``, którego na FAIL nikt nie podawał. Ten kształt ma też prawdziwy
    # strażnik z błędem na ``None`` (sonda #2197 r1 W2, ``W2-prawdziwy-…`` niżej), więc dowód odrzuca oba: na drzewie FAIL
    # test nie dochodzi do funkcji z ``Gdzie``, a komunikat mówi, żeby tam doszedł.
    "W2-kontrakt-head-none-z-nazwy-po-fail": Sample(
        {"kod/liczby.py": FIRST.replace("x[0] if x else 0", "x[1]")},
        {"kod/liczby.py": FIRST + "\n\nPUSTE: list[int] | None = None\n", "tests/test_g.py": "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.pierwsza(kod.liczby.PUSTE) == 0\n"},
        False,
        (("kod/liczby.py", 2, 2),),
        base={"kod/liczby.py": FIRST.replace("x[0] if x else 0", "x[0]")},
        reason=REACH_GDZIE,
    ),
    "W2-prawdziwy-blad-none-z-nazwy-po-fail": Sample(
        {"kod/liczby.py": FIRST.replace("x[0] if x else 0", "x[0]")},
        {"kod/liczby.py": FIRST + "\n\nPUSTE: list[int] | None = None\n", "tests/test_g.py": "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.pierwsza(kod.liczby.PUSTE) == 0\n"},
        False,
        (("kod/liczby.py", 2, 2),),
        base={"kod/liczby.py": FIRST},
        reason=REACH_GDZIE,
    ),
    "W2-prawdziwy-blad-none-wprost": Sample(
        {"kod/liczby.py": FIRST.replace("x[0] if x else 0", "x[0]")},
        {"kod/liczby.py": FIRST, "tests/test_g.py": "import kod.liczby\n\n\ndef test_g() -> None:\n    assert kod.liczby.pierwsza(None) == 0\n"},
        True,
        (("kod/liczby.py", 2, 2),),
        base={"kod/liczby.py": FIRST},
    ),
    "A7b-pole-dataclass-i-nazwa-dodana-po-fail": Sample(
        {"kod/okres.py": PERIOD.replace("x * 2", "x * 3")},
        {"kod/okres.py": PERIOD_HEAD + "\n\nNOWA = 1\n", "tests/test_g.py": TEST_PERIOD.replace("from kod.okres", "import kod.okres\nfrom kod.okres") + "    assert getattr(kod.okres, 'NOWA', None) == 1\n"},
        False,
        (("kod/okres.py", 10, 10),),
        base={"kod/okres.py": PERIOD},
        reason=OTHERWISE,
    ),
}


@dowod_testu
@pytest.mark.parametrize("name", PROBKI_TESTU)
def test_dowod_testu_przyjmuje_strażnika_ktory_pada_na_przeszczepie_z_fail_a_nie_test_tego_co_poprawka_dodala_obok(tmp_path: Path, name: str) -> None:
    """Prawdziwy strażnik pada, gdy definicje z ``Gdzie`` wracają z FAIL; sonda, która na drzewie FAIL pada tylko przez
    nazwę, metodę, pole albo pomocnika dodanego przez poprawkę obok, przechodzi na przeszczepie albo pada na nim na
    interfejsie HEAD, więc dowód jej nie przyjmuje."""

    sample = PROBKI_TESTU[name]
    pull = _pull(tmp_path, sample.failed, sample.head, sample.base)

    outcome = pull.prove(f"pytest {sample.node}", sample.where)

    assert outcome.detected is sample.proved, outcome.line
    assert ("| WYKRYTA | przeszczep z FAIL: " if sample.proved else "| NIEWYKRYTA | ") in outcome.line, outcome.line
    assert sample.reason in outcome.line, outcome.line


@pytest.mark.parametrize(
    ("places", "before_test_proof", "state"),
    [
        (WHERE, False, "ODMOWA | przeszczep z FAIL ma kod/liczby.py:podwojona: strażnik-test to pytest tests/<plik>.py::<test> z dowodem narzędzia, a brak - test przechodzi tylko przy pustym przeszczepie"),
        ((("tests/test_podwojona.py", 5, 5),), False, f"WYJĄTEK brak - test | przeszczep pusty: {straznik._EMPTY} | {straznik.REVIEWED[Kind.TESTS]}"),
        ((("kod/liczby.py", 5, 6),), False, f"WYJĄTEK brak - test | przeszczep pusty: {straznik._EMPTY} | {straznik.REVIEWED[Kind.TESTS]}"),
        (WHERE, True, f"WYJĄTEK brak - test | {straznik.REVIEWED[Kind.TESTS]}"),
    ],
    ids=["kod-z-gdzie-zmieniony", "gdzie-tylko-w-tests", "gdzie-w-funkcji-bez-zmian", "watek-sprzed-dowodu-testu"],
)
def test_brak_testu_przechodzi_tylko_gdy_przeszczep_jest_pusty_albo_watek_jest_sprzed_dowodu_testu(
    tmp_path: Path, places: Places, before_test_proof: bool, state: str
) -> None:
    """Sonda luki G3: Ważne w kodzie z ``brak - test`` przechodziło bez testu, który łapie błąd. Gdy przeszczep ma
    definicje z ``Gdzie``, strażnik-test to ``pytest <węzeł>`` z dowodem; ``brak - test`` zostaje dla pustego
    przeszczepu i dla wątku sprzed wdrożenia dowodu testu (``bramka_straznika.TEST_MARKER``)."""

    pull = _fixed(tmp_path)

    outcome = pull.prove("brak - test", places, before_test_proof=before_test_proof)

    assert outcome.detected == state.startswith("WYJĄTEK"), outcome.line
    assert outcome.line == f"#5 W1 r1 | {pull.failed[:8]} | {state}", outcome.line


@dowod_testu
@pytest.mark.parametrize(
    ("head", "fragment"),
    [
        ({"tests/test_g.py": TEST_G.replace("def test_g", "import pytest\n\n\n@pytest.mark.skip\ndef test_g")}, "PODSTAWA CZERWONA | tests/test_g.py::test_g na HEAD scalonym z bazą: pominięty"),
        ({"tests/test_g.py": TEST_G.replace("== 6", "== 7")}, "PODSTAWA CZERWONA | tests/test_g.py::test_g na HEAD scalonym z bazą: kod 1: AssertionError: assert 6 == 7 (tests/test_g.py:5)"),
        ({"tests/test_g.py": TEST_G.replace("def test_g", "def test_inny")}, "PODSTAWA CZERWONA | tests/test_g.py::test_g na HEAD scalonym z bazą: kod 4"),
    ],
    ids=["pominiety", "pada", "bez-wezla"],
)
def test_dowod_testu_odmawia_wezla_ktory_na_drzewie_bez_zmian_nie_przechodzi_w_calosci(tmp_path: Path, head: dict[str, str], fragment: str) -> None:
    """Węzeł pominięty (np. tylko na Windows), padający albo bez testu niczego nie dowodzi, więc dowód odmawia z tym,
    co zrobić, zamiast liczyć padnięcie na przeszczepie."""

    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, **head})

    outcome = pull.prove(f"pytest {NODE}")

    assert not outcome.detected and fragment in outcome.line, outcome.line


@dowod_testu
def test_dowod_testu_bez_kodu_z_gdzie_do_przeszczepu_odsyla_do_brak_test(tmp_path: Path) -> None:
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, "tests/test_g.py": TEST_G})

    outcome = pull.prove(f"pytest {NODE}", (("kod/liczby.py", 5, 6),))

    assert not outcome.detected, outcome.line
    assert outcome.line.endswith(f"| NIC DO PRZESZCZEPIENIA | {straznik._EMPTY}: dowodu testu nie ma z czego liczyć, strażnik to brak - test"), outcome.line


@dowod_testu
def test_dowod_testu_odmawia_gdzie_w_instrukcji_modulu_bez_nazwy_zamiast_przeszczepiac_caly_plik(tmp_path: Path) -> None:
    """Miejsce ``Gdzie`` w instrukcji modułu, która nie wiąże nazwy (``if __name__``), nie ma definicji do przeszczepienia;
    cały plik z FAIL przyjąłby test nazwy dodanej obok (kształt r1 #2116), więc dowód odmawia."""

    main = "\n\nif __name__ == '__main__':\n    print(podwojona(2))\n"
    pull = _pull(tmp_path, {"kod/liczby.py": BAD + main.replace("2))", "3))")}, {"kod/liczby.py": GOOD + main + "\n\nWERSJA = 2\n", "tests/test_g.py": VERSION})

    outcome = pull.prove(f"pytest {NODE}", (("kod/liczby.py", 10, 10),))

    assert not outcome.detected and "| ODMOWA | Gdzie kod/liczby.py:10-10 nie leży w definicji" in outcome.line, outcome.line


# Test, który zostawia ślad i pada przy drugim biegu (miejsce śladu → ścieżka w teście): na HEAD przechodzi, a bez
# powrotu kopii przed następnym biegiem padałby na przeszczepie i na drzewie FAIL także bez błędu z ``Gdzie``.
SLADY = {
    "plik-sledzony-przez-git": "pathlib.Path('slad.txt')",
    "plik-ignorowany": "pathlib.Path('ignorowane/slad.txt')",
    "katalog-domowy": "pathlib.Path.home() / 'slad.txt'",
    "katalog-tymczasowy": "pathlib.Path(__import__('tempfile').gettempdir()) / 'slad-straznika.txt'",
}


@dowod_testu
@pytest.mark.parametrize("trace", SLADY.values(), ids=SLADY)
def test_slad_biegu_wezla_nie_przechodzi_do_nastepnego_biegu_dowodu(tmp_path: Path, trace: str) -> None:
    once = (
        "import pathlib\n\n\ndef test_g() -> None:\n"
        f"    slad = {trace}\n    assert not slad.exists()\n    slad.parent.mkdir(parents=True, exist_ok=True)\n    slad.write_text('1')\n"
    )
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD, "tests/test_g.py": once, ".gitignore": "ignorowane/\n"})

    outcome = pull.prove(f"pytest {NODE}")

    assert not outcome.detected and "| NIEWYKRYTA | na przeszczepie z FAIL (kod/liczby.py:podwojona) węzeł nie pada" in outcome.line, outcome.line


TABLE = "class Tablica:\n    def match(self, x: int) -> bool:\n        return x > 0\n"
TEXT = "import re\n\n\ndef czy_kod(s: str) -> bool:\n    return bool(re.match(r'\\d', s))\n"
# Granice dowodu (ADR 0042, „Konsekwencje”): każda próbka przechodzi dowód, choć strażnik nie łapie Ważnego z ``Gdzie``.
# Postać: (pliki FAIL, pliki HEAD, selektor, miejsca ``Gdzie``).
ZNANE_LUKI_STRAZNIKA: dict[str, tuple[dict[str, str], dict[str, str], str, Places]] = {
    # ``brak - test`` przy pustym przeszczepie nie ma warunku testu: ``Gdzie`` wskazuje funkcję, której poprawka nie
    # zmieniła (poprawka leży obok), a HEAD nie ma testu, który łapie błąd; to ocenia recenzent następnej rundy.
    "brak - test: pusty przeszczep, bo Gdzie wskazuje funkcję bez zmian": ({"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD}, "brak - test", (("kod/liczby.py", 5, 6),)),
    # Usunięcia kodu z ``Gdzie`` też nie dowodzi narzędzie, więc ``brak - usunięte`` przechodzi, choć funkcja z ``Gdzie``
    # stoi na HEAD poprawiona w miejscu.
    "brak - usunięte: kod z Gdzie poprawiony w miejscu, a nie usunięty": ({"kod/liczby.py": BAD}, {"kod/liczby.py": GOOD}, "brak - usunięte", WHERE),
    # Ta sama definicja, inna zmiana PR (A2 G3): test drugiej zmiany funkcji z ``Gdzie`` pada, gdy wraca cała definicja
    # z FAIL, choć powrotu samego błędu nie łapie; jak przy mypy i ruff ocenia go recenzent z linii dowodu.
    "pytest: test innej zmiany tej samej definicji z Gdzie": (
        {"kod/liczby.py": BAD},
        {
            "kod/liczby.py": GOOD.replace("    return x * 2\n", "    if x < 0:\n        raise ValueError(x)\n    return x * 2\n"),
            "tests/test_g.py": "import pytest\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    with pytest.raises(ValueError):\n        podwojona(-1)\n",
        },
        f"pytest {NODE}",
        WHERE,
    ),
    # Plik spoza Pythona, TOML i YAML jest jedną definicją, więc test innej zmiany tego pliku przechodzi jak A2.
    "pytest: plik danych w całości jest definicją z Gdzie": (
        {"kod/dane.json": '{"mnoznik": 3}\n'},
        {
            "kod/dane.json": '{"mnoznik": 2, "nazwa": "x"}\n',
            "tests/test_g.py": "import json\nimport pathlib\n\n\ndef test_g() -> None:\n    assert json.loads(pathlib.Path('kod/dane.json').read_text())['nazwa'] == 'x'\n",
        },
        f"pytest {NODE}",
        (("kod/dane.json", 1, 1),),
    ),
    # Wołający, który wraca przy zmienionej sygnaturze, to każda definicja plików PR z tą nazwą, także atrybutu cudzego
    # obiektu (``re.match`` przy ``Tablica.match``, sonda #2197 r1 D1), więc test innej zmiany takiej funkcji przechodzi.
    "pytest: wołający po nazwie atrybutu wraca z FAIL": (
        {"kod/tablica.py": TABLE.replace("x > 0", "x >= 0"), "kod/tekst.py": TEXT},
        {
            "kod/tablica.py": TABLE.replace("x: int)", "x: int, strict: bool = False)"),
            "kod/tekst.py": TEXT.replace("r'\\d'", "r'\\d+$'"),
            "tests/test_g.py": "from kod.tekst import czy_kod\n\n\ndef test_g() -> None:\n    assert not czy_kod('1a')\n",
        },
        f"pytest {NODE}",
        (("kod/tablica.py", 3, 3),),
    ),
    # ``brak - test`` nie liczy miejsca ``Gdzie`` poza definicją (``if __name__``), którego przeszczep nie przenosi.
    "brak - test: Gdzie w instrukcji modułu bez nazwy": (
        {"kod/liczby.py": GOOD + "\n\nif __name__ == '__main__':\n    print(podwojona(3))\n"},
        {"kod/liczby.py": GOOD + "\n\nif __name__ == '__main__':\n    print(podwojona(2))\n"},
        "brak - test",
        (("kod/liczby.py", 10, 10),),
    ),
    # Test tekstu definicji zamiast jej zachowania pada, gdy wraca definicja z FAIL; dowód nie ocenia, co test sprawdza.
    "pytest: test tekstu definicji z Gdzie zamiast jej zachowania": (
        {"kod/liczby.py": BAD},
        {"kod/liczby.py": GOOD, "tests/test_g.py": "import inspect\n\nfrom kod.liczby import podwojona\n\n\ndef test_g() -> None:\n    assert 'x * 2' in inspect.getsource(podwojona)\n"},
        f"pytest {NODE}",
        WHERE,
    ),
}


@pytest.mark.parametrize("name", ZNANE_LUKI_STRAZNIKA)
def test_znane_luki_straznika_przechodza_przez_dowod(tmp_path: Path, name: str) -> None:
    failed, head, guard, places = ZNANE_LUKI_STRAZNIKA[name]
    if guard.startswith("pytest") and sys.platform == "win32":
        pytest.skip("dowód strażnika biegnie na Linuksie i macOS (srodowisko_ci.built)")
    pull = _pull(tmp_path, failed, head)

    outcome = pull.prove(guard, places, scopes=SCOPE)

    assert outcome.detected, f"dowód odmawia już luki „{name}”: usuń ją ze ZNANE_LUKI_STRAZNIKA ({outcome.line})"
