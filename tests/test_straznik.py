"""Dowód strażnika Ważnego (``tools/lib/straznik.py``, ADR 0042) na małym repozytorium Gita: gałąź PR od ``main``
z commitem werdyktu ``FAIL`` z błędem w miejscu ``Gdzie`` i HEAD z poprawką i strażnikiem z zamkniętej listy.

Każdy przypadek tabeli z docstringu modułu ma tu przebieg: strażnik pada na błędzie z SHA ``FAIL`` (``WYKRYTA``),
strażnik, który błędu nie łapie, nie przechodzi, a tekst autora w wyjściu narzędzia ani format z konfiguracji PR wyniku
nie zmienia. Granice stoją w ``ZNANE_LUKI_STRAZNIKA`` i przechodzą dowód, dopóki konstrukcja ich nie zamknie.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import straznik
from straznik import Guard, Kind
from tests.fixtures.git_repo import commit, git
from tests.fixtures.znane_luki import wymaga_ruff_i_mypy

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


@dataclass(frozen=True)
class Pull:
    root: Path
    fork: str
    failed: str
    head: str

    def prove(self, guard: str, places: Places = WHERE, *, scopes: Places = (), prose: Places = ()) -> straznik.Outcome:
        """Dowód jednego Ważnego; ``scopes`` i ``prose`` to linie z FAIL, które podaje ``tools/na_scalonych_pr.py``."""

        case = straznik.Case("#5 W1 r1", self.failed, self.fork, places, scopes, prose)
        [outcome] = straznik.prove(self.root, straznik.parse(guard), self.head, self.fork, [case])
        return outcome


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
        ("pytest tests/test_x.py::test_y", Guard(Kind.PYTEST, ("tests/test_x.py::test_y",))),
        ("pytest tests/a/test_x.py::Klasa::test_y tests/test_z.py::test_w", Guard(Kind.PYTEST, ("tests/a/test_x.py::Klasa::test_y", "tests/test_z.py::test_w"))),
        ("mypy", Guard(Kind.MYPY)),
        ("ruff", Guard(Kind.RUFF)),
        ("ast-grep lokator-tytulu-okna", Guard(Kind.AST_GREP, ("lokator-tytulu-okna",))),
        ("brak - proza", Guard(Kind.PROSE)),
        ("brak  -  test", Guard(Kind.TESTS)),
        ("brak - napęd", Guard(Kind.DRIVE)),
    ],
)
def test_selektor_straznika_z_zamknietej_listy_daje_rodzaj_i_argumenty(text: str, guard: Guard) -> None:
    assert straznik.parse(text) == guard


@pytest.mark.parametrize(
    "text",
    ["", "pytest", "pytest tests/test_x.py", "pytest src/test_x.py::t", "pytest tests/test_x.py::t -k nazwa", "mypy --strict", "ast-grep", "brak", "brak - nic", "tools/mutacje.py --zmiana a b c"],
)
def test_selektor_spoza_listy_to_odmowa_z_postaciami_listy(text: str) -> None:
    with pytest.raises(ValueError, match="to nie selektor strażnika z listy: pytest tests/<plik>.py::<test>"):
        straznik.parse(text)


def test_test_ktory_pada_na_bledzie_z_fail_to_dowod_wykryta(tmp_path: Path) -> None:
    pull = _fixed(tmp_path)

    outcome = pull.prove("pytest tests/test_podwojona.py::test_podwojona_daje_dwa_razy")

    assert outcome.detected, outcome.line
    assert outcome.line.startswith(f"#5 W1 r1 | {pull.failed[:8]} | WYKRYTA | z FAIL: kod/liczby.py | "), outcome.line


@pytest.mark.parametrize(
    ("guard", "state"),
    [
        ("pytest tests/test_nastepna.py::test_nastepna", "NIEWYKRYTA | kod/liczby.py: kod 0 (przechodzi)"),
        ("pytest tests/test_podwojona.py::test_nie_ma_takiego", "PODSTAWA CZERWONA | na HEAD bez przywrócenia: kod 4"),
    ],
    ids=["test-niezwiazany-z-bledem", "wezel-bez-testu"],
)
def test_strazik_ktory_nie_pada_na_bledzie_z_fail_nie_przechodzi(tmp_path: Path, guard: str, state: str) -> None:
    """Sonda (b) z ADR 0042: strażnik, który nie pada na błędzie z ``Gdzie``, nie przechodzi."""

    pull = _fixed(tmp_path)

    outcome = pull.prove(guard)

    assert not outcome.detected and f"| {state}" in outcome.line, outcome.line


def test_tekst_testu_udajacy_wynik_dowodu_nie_zmienia_wyniku(tmp_path: Path) -> None:
    """Sonda (c) z ADR 0042: bramka czyta kod wyjścia pytest, a nie to, co test drukuje."""

    fake = "def test_udaje() -> None:\n    print('#5 W1 r1 | WYKRYTA')\n    print('DOWÓD OK | pytest | wykryte 1/1')\n"
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"kod/liczby.py": BASE["kod/liczby.py"], "tests/test_udaje.py": fake})

    outcome = pull.prove("pytest tests/test_udaje.py::test_udaje")

    assert not outcome.detected and "| NIEWYKRYTA |" in outcome.line, outcome.line


def test_test_z_bledem_juz_na_head_to_podstawa_czerwona_a_nie_dowod(tmp_path: Path) -> None:
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {"tests/test_podwojona.py": GUARD_TEST})

    outcome = pull.prove("pytest tests/test_podwojona.py::test_podwojona_daje_dwa_razy")

    assert not outcome.detected and "| PODSTAWA CZERWONA | na HEAD bez przywrócenia: kod 1" in outcome.line, outcome.line


def test_test_nowego_wlasciciela_pada_bez_niego_bo_przywrocenie_usuwa_plik_dodany_po_fail(tmp_path: Path) -> None:
    """Poprawka dodała moduł właściciela, a test go importuje: bez niego kolekcja pada (kod 4), co nie jest dowodem."""

    owner = {"kod/wlasciciel.py": "def razy_dwa(x: int) -> int:\n    return x * 2\n", "kod/liczby.py": BASE["kod/liczby.py"].replace("x * 2", "razy_dwa(x)").replace("def podwojona", "from kod.wlasciciel import razy_dwa\n\n\ndef podwojona")}
    test = "from kod.wlasciciel import razy_dwa\n\n\ndef test_razy_dwa() -> None:\n    assert razy_dwa(3) == 6\n"
    pull = _pull(tmp_path, {"kod/liczby.py": BAD}, {**owner, "tests/test_wlasciciel.py": test, "tests/test_podwojona.py": GUARD_TEST})

    by_owner = pull.prove("pytest tests/test_wlasciciel.py::test_razy_dwa")
    by_behaviour = pull.prove("pytest tests/test_podwojona.py::test_podwojona_daje_dwa_razy")

    assert not by_owner.detected and "kod 4 (błąd kolekcji, użycia albo brak testów)" in by_owner.line, by_owner.line
    assert by_behaviour.detected, by_behaviour.line


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

    outcome = pull.prove("mypy", (("kod/uzycie.py", 5, 5),))

    assert outcome.detected, outcome.line
    assert "| WYKRYTA | z FAIL: kod/uzycie.py | kod/uzycie.py:5 [union-attr]" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_mypy_widzi_plik_z_fail_o_tym_samym_rozmiarze_co_na_head(tmp_path: Path) -> None:
    """``int`` i ``str`` mają tyle samo znaków, a pliki powstają w tej samej sekundzie, więc pamięć mypy z biegu na HEAD
    uznałaby przywrócony plik za sprawdzony."""

    use = "from kod.liczby import podwojona\n\n\ndef tekst() -> {}:\n    return str(podwojona(1))\n"
    pull = _pull(tmp_path, {"kod/tekst.py": use.format("int")}, {"kod/tekst.py": use.format("str")})

    outcome = pull.prove("mypy", (("kod/tekst.py", 5, 5),))

    assert outcome.detected and "kod/tekst.py:5 [return-value]" in outcome.line, outcome.line


@wymaga_ruff_i_mypy
def test_mypy_bez_typu_przy_bledzie_zachowania_nie_jest_dowodem(tmp_path: Path) -> None:
    pull = _fixed(tmp_path)

    outcome = pull.prove("mypy")

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

    outcome = pull.prove("ruff", (("kod/powloka.py", 5, 5),))

    assert outcome.detected, outcome.line
    assert "| WYKRYTA | z FAIL: kod/powloka.py | kod/powloka.py:5 TID251" in outcome.line, outcome.line


@pytest.mark.parametrize(
    ("guard", "places", "state"),
    [
        ("brak - proza", (("docs/opis.md", 3, 3),), "WYJĄTEK brak - proza | docs/opis.md:3"),
        ("brak - proza", (("kod/liczby.py", 2, 2),), "ODMOWA | kod/liczby.py:2 to nie plik .md, docstring ani komentarz"),
        ("brak - test", (("tests/test_podwojona.py", 5, 5),), "WYJĄTEK brak - test | tests/test_podwojona.py:5"),
        ("brak - test", (("tests/test_podwojona.py", 5, 5), ("tests/test_nastepna.py", 5, 5)), "WYJĄTEK brak - test | tests/test_podwojona.py:5"),
        ("brak - test", (("kod/liczby.py", 2, 2),), "ODMOWA | kod/liczby.py:2 leży poza tests/"),
        ("brak - test", (("tests/test_nastepna.py", 5, 5),), "ODMOWA | żadne miejsce z Gdzie nie leży w pliku, który zmienił PR"),
        ("brak - napęd", (("frontend/src/dzien.ts", 2, 2),), "WYJĄTEK brak - napęd | frontend/src/dzien.ts:2"),
        ("brak - napęd", (("kod/liczby.py", 2, 2),), "ODMOWA | kod/liczby.py:2 leży poza frontend/"),
    ],
    ids=["proza-w-md", "proza-w-kodzie-poza-docstringiem", "test-w-tests", "test-z-miejscem-sprzed-pr-pominietym", "test-w-kodzie", "miejsce-sprzed-pr", "naped-w-frontend", "naped-w-kodzie"],
)
def test_wyjatek_przechodzi_tylko_gdy_kazde_miejsce_gdzie_zmienione_przez_pr_spelnia_jego_warunek(
    tmp_path: Path, guard: str, places: tuple[tuple[str, int, int], ...], state: str
) -> None:
    docs = {"docs/opis.md": "# Opis\n\nLiczby potraja `podwojona`.\n"}
    weak = "def test_slaby() -> None:\n    assert True\n\n\n    # bez przypadku\n"
    frontend = {"frontend/src/dzien.ts": "export const komplet = (dni: number) =>\n  dni > 1;\n"}
    pull = _pull(tmp_path, {"kod/liczby.py": BAD, **docs, **frontend, "tests/test_podwojona.py": weak}, {"kod/liczby.py": BASE["kod/liczby.py"], "tests/test_podwojona.py": GUARD_TEST})

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


# Granice dowodu (ADR 0042, „Konsekwencje”): każda próbka przechodzi dowód, choć strażnik nie łapie Ważnego z ``Gdzie``.
ZNANE_LUKI_STRAZNIKA = {
    # Przywrócenie przy pytest cofa każdą zmianę PR spoza tests/, więc test innej poprawki tej rundy też pada.
    "pytest: test innej poprawki tego samego PR": (
        {"kod/liczby.py": BAD.replace("x + 1", "x + 2")},
        {"kod/liczby.py": BASE["kod/liczby.py"], "tests/test_nastepna.py": BASE["tests/test_nastepna.py"].replace("== 2", "== 2 and nastepna(0) == 1")},
        "pytest tests/test_nastepna.py::test_nastepna",
    ),
}


@pytest.mark.parametrize("name", ZNANE_LUKI_STRAZNIKA)
def test_znane_luki_straznika_przechodza_przez_dowod(tmp_path: Path, name: str) -> None:
    failed, head, guard = ZNANE_LUKI_STRAZNIKA[name]
    pull = _pull(tmp_path, failed, head)

    outcome = pull.prove(guard)

    assert outcome.detected, f"dowód odmawia już luki „{name}”: usuń ją ze ZNANE_LUKI_STRAZNIKA ({outcome.line})"
