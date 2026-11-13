"""Zakres runu CI (``tools/lib/zakres_runu.py``): co CI uruchamia dla zdarzenia i zmiany, każda reguła raz, na ``zakres``.

Testy budują repozytorium z własnymi skillami, dają jego korzeń ``zakres`` i ``kroki_skilli.Katalog.skanuj``, bez łatek
modułów, i pytają o zakres jawnej zmiany, bez gita i bez uruchamiania kroków. Plan CI (``tests/test_plan_ci.py``) i
``tools/skille_dla_zmiany.py`` (``tests/test_skille_dla_zmiany.py``) mają tylko testy tłumaczenia zakresu na swoje wyjście.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
import tomllib

import pytest
import yaml

from tests.fixtures.git_repo import repository

from jednostka import Klucz
import kroki_skilli
import setup_worktree
from wplyw_zmiany import STRUCTURE, Repository
from zakres_runu import PRZEGLADARKA, TORY, Zdarzenie, ZakresRunu, pliki_testow, potrzebuja_chromium, zakres

ROOT = Path(__file__).resolve().parents[1]

PASSING = 'print("WYKRYTA: proba")\nprint("MUTACJE OK")\n'
CHECKED = "src/pakiet/sprawdzany.py"
ANCHORS = "src/pakiet/kotwice.txt"
GUARDED = "---\nname: verify-x\npilnuje:\n  - src/pakiet/rout*.py\n---\n"
WITH_TABLE = f"""from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
from silnik_mutacji import Edit, Mutation  # noqa: E402

MUTATIONS = (
    Mutation("m", (Edit(Path("{CHECKED}"), "X", "Y"), Edit(Path("{ANCHORS}"), "X", "Y")), (".agents/skills/verify-a/scripts/sprawdz_a.py",)),
)
"""
# Skill a z ``pilnuje`` i tabelą, b z tabelą bez ``pilnuje``, c z ``pilnuje`` bez tabeli.
SKILLS = {
    "src/pakiet/__init__.py": "",
    CHECKED: "def run() -> int:\n    from pakiet import pomocnik\n\n    return pomocnik.X\n",
    "src/pakiet/pomocnik.py": "X = 1\n",
    "src/pakiet/routing.py": "Z = 3\n",
    ANCHORS: "X\n",
    "docs/opis.md": "opis\n",
    "requirements.txt": "pytest\n",
    ".agents/skills/verify-a/SKILL.md": GUARDED,
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "from pakiet import sprawdzany\n",
    ".agents/skills/verify-a/scripts/check_a_mutations.py": WITH_TABLE,
    ".agents/skills/verify-b/SKILL.md": "",
    ".agents/skills/verify-b/scripts/check_b_mutations.py": WITH_TABLE,
    ".agents/skills/verify-c/SKILL.md": GUARDED,
    ".agents/skills/verify-c/scripts/check_c_mutations.py": PASSING,
}
SCRIPT_A = "verify-a/check_a_mutations.py"


def _with_ci(name: str, command: str, globs: str = "src/pakiet/rout*.py") -> str:
    return f"---\nname: {name}\npilnuje:\n  - {globs}\nci: {command}\n---\n"


def _decisions(praca: ZakresRunu) -> dict[str, tuple[bool, str]]:
    """Klucz kroku skilla → (biegnie, powód)."""

    return {**{w.krok.key: (True, w.powod) for w in praca.wybrane}, **{step.key: (False, why) for step, why in praca.pominiete}}


def _runs(praca: ZakresRunu) -> set[str]:
    return {w.krok.key for w in praca.wybrane}


# --- pytest i kroki CI ---


GATE = {
    "src/pakiet/__init__.py": "",
    "src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n",
    "src/pakiet/b.py": "def b(x: int) -> bool:\n    return x < 3\n",
    "tests/test_a.py": "from pakiet.a import a\n\n\ndef test_a() -> None:\n    assert a(2)\n",
    "tests/test_b.py": "from pakiet.b import b\n\n\ndef test_b() -> None:\n    assert b(2)\n",
    "tools/benchmark_przebiegu.py": "from pakiet.a import a\n",
    "tools/syntetyczne_wzorce.py": "",
    "tools/raport.py": "",
    "README.md": "Repozytorium\n",
    ".github/workflows/ci.yml": "name: CI\n",
}
WINDOWS, LINUX = "windows-3.13", "linux-3.14"


@pytest.mark.parametrize(
    ("changed", "source", "files", "steps"),
    [
        ("tests/test_b.py", "wybór 1 plików", ["tests/test_b.py"], ()),
        ("src/pakiet/b.py", "wybór 1 plików", ["tests/test_b.py"], ("e2e",)),
        ("src/pakiet/a.py", "wybór 1 plików", ["tests/test_a.py"], ("e2e", "timing")),
        ("tools/syntetyczne_wzorce.py", "wybór 0 plików", [], ("timing",)),
        ("tools/raport.py", "wybór 0 plików", [], ()),
        ("README.md", "wybór 0 plików", [], ()),
        (".github/workflows/ci.yml", "FULL (.github/workflows/ci.yml)", None, ("e2e", "timing")),
        ("requirements.txt", "FULL (requirements.txt)", None, ("e2e", "timing")),
    ],
    ids=["test", "src poza straza czasu", "src w domknieciu strazy czasu", "skrypt strazy czasu", "tools", "dokument", "workflow", "plik FULL"],
)
def test_bramka_pr_biegnie_na_windows_313_i_linuksie_z_wyborem_szybko_a_e2e_i_straz_czasu_tylko_przy_ich_zmianie(
    tmp_path: Path, changed: str, source: str, files: list[str] | None, steps: tuple[str, ...]
) -> None:
    repo = repository(tmp_path / "repo", GATE)

    gate = zakres(Zdarzenie.PULL_REQUEST, frozenset({changed}), repo)

    rule = (
        "bramka PR uruchamia pytest na Windows 3.13 i Linux 3.14 na wyborze tools/szybko.py dla zmiany, a zmiana ścieżki "
        "z Context.PR_GATE (tools/lib/wplyw_zmiany.py) wybiera wszystkie pliki, E2E i straż czasu"
    )
    assert [(lane.nazwa, lane.kroki) for lane in gate.tory] == [(WINDOWS, steps), (LINUX, ())], rule
    assert gate.zrodlo == source, rule
    # GATE nie ma plików testów ze STRUCTURE, więc wybór biegnie z całą strukturą.
    assert list(gate.pliki) == (pliki_testow(repo) if files is None else [*files, *STRUCTURE])


def test_bramka_pr_biegnie_wybrany_plik_testow_raz_bez_jego_wezlow_ze_struktury(tmp_path: Path) -> None:
    file = next(node.partition("::")[0] for node in STRUCTURE if "::" in node)
    repo = repository(tmp_path / "repo", {**GATE, file: "def test_wezel() -> None:\n    pass\n"})

    gate = zakres(Zdarzenie.PULL_REQUEST, frozenset({file}), repo)

    assert [unit for unit in gate.pliki if unit.startswith(file)] == [file]


def test_bramka_pr_na_windows_testuje_najstarszego_pythona_z_requires_python_jak_mypy_ruff_i_setup_worktree(tmp_path: Path) -> None:
    """Najstarszy Python z ``requires-python`` to Python taty (3.13.15 od 13.11, ADR 0020): bramka PR testuje go na
    Windows, mypy i ruff sprawdzają kod dla niego, a ``tools/setup_worktree.py`` (systemowy Python, bez ``tomllib``)
    trzyma jego kopię."""

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    oldest = re.fullmatch(r">=(\d+)\.(\d+)", pyproject["project"]["requires-python"])
    assert oldest is not None
    gate = zakres(Zdarzenie.PULL_REQUEST, frozenset({"README.md"}), repository(tmp_path / "repo", GATE))

    assert {
        "bramka PR na Windows": next(lane.python for lane in gate.tory if lane.os.startswith("windows")),
        "mypy": pyproject["tool"]["mypy"]["python_version"],
        "ruff": pyproject["tool"]["ruff"]["target-version"].replace("py3", "3."),
        "setup_worktree": ".".join(map(str, setup_worktree.MINIMUM_PYTHON)),
    } == dict.fromkeys(("bramka PR na Windows", "mypy", "ruff", "setup_worktree"), f"{oldest[1]}.{oldest[2]}")


def test_push_biegnie_pelne_ci_main_na_trzech_torach_z_kazdym_plikiem_testow_a_noc_bez_pytest(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {**GATE, "tests/c_test.py": "def test_c() -> None:\n    pass\n"})

    main = zakres(Zdarzenie.PUSH, frozenset({"tests/test_a.py"}), repo)
    night = zakres(Zdarzenie.NOC, frozenset({"src/pakiet/a.py"}), repo)

    assert (main.tory, main.pliki, main.zrodlo) == (TORY, ("tests/c_test.py", "tests/test_a.py", "tests/test_b.py"), "wszystkie pliki")
    assert [(lane.nazwa, lane.kroki) for lane in main.tory] == [("windows-3.13", ("e2e",)), ("windows-3.14", ("e2e", "timing")), ("linux-3.14", ())]
    assert (night.tory, night.pliki, night.zrodlo) == ((), (), "bez pytest")


def test_plik_testow_ktory_siega_atrapy_efenix_potrzebuje_chromium_na_pull_request_i_na_pushu(tmp_path: Path) -> None:
    atrapa = "from atrapy.atrapa_efenix import ATRAPA\n\n\ndef test_c() -> None:\n    assert ATRAPA\n"
    files = {
        **GATE,
        "tests/__init__.py": "",
        "tests/fixtures/__init__.py": "",
        PRZEGLADARKA: "ATRAPA = 1\n",
        "tests/fixtures/okno.py": "from atrapy.atrapa_efenix import ATRAPA as OKNO\n",
        "tests/test_c.py": atrapa,
        "tests/test_d.py": "from tests.fixtures.okno import OKNO\n\n\ndef test_d() -> None:\n    assert OKNO\n",
    }
    repo = repository(tmp_path / "repo", files)

    gate = zakres(Zdarzenie.PULL_REQUEST, frozenset({"tests/test_c.py", "tests/test_a.py"}), repo)
    main = zakres(Zdarzenie.PUSH, frozenset(), repo)
    without = zakres(Zdarzenie.PULL_REQUEST, frozenset({"tests/test_a.py"}), repo)

    assert (gate.przegladarka, main.przegladarka, without.przegladarka) == (
        frozenset({"tests/test_c.py"}),
        frozenset({"tests/test_c.py", "tests/test_d.py"}),
        frozenset(),
    )
    # Węzeł ``plik::test`` (test ``STRUCTURE`` bez swojego pliku w wyborze) biegnie w tym samym Chromium co jego plik.
    assert potrzebuja_chromium(["tests/test_d.py::test_d", "tests/test_a.py::test_a"], Repository.scan(repo)) == {"tests/test_d.py"}


# --- kroki skilli ---


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        ("docs/opis.md", False),
        ("src/pakiet/obcy.py", False),
        # Trafienie w pilnuje uruchamia podstawę skilla na PR, a skrypt mutacji nie (ADR 0020).
        ("src/pakiet/routing.py", False),
        (".agents/skills/verify-b/SKILL.md", False),
        # Plik, który mutacje zmieniają, i importy sprawdzenia: pytest bramki i pełne CI main, nie skrypt mutacji nocą.
        (CHECKED, False),
        (ANCHORS, False),
        ("src/pakiet/pomocnik.py", False),
        # Polityka zakresu i samo narzędzie z wiersza poleceń (z jego odmową ciężkiego CI) nie biegną w procesie skryptu.
        ("tools/lib/zakres_runu.py", False),
        ("tools/mutacje.py", False),
        ("tools/lib/ciezkie_ci.py", False),
        (".agents/skills/verify-a/scripts/sprawdz_a.py", True),
        (".agents/skills/verify-a/SKILL.md", True),
        ("requirements.txt", True),
        # Uruchamiacz kroku i silnik mutacji, który skrypt importuje, z każdym modułem, do którego silnik dochodzi.
        ("tools/ci/wykonaj_zadanie.py", True),
        ("tools/lib/kroki_skilli.py", True),
        ("tools/lib/silnik_mutacji.py", True),
        ("tools/lib/potomne.py", True),
        ("tools/lib/repo.py", True),
    ],
)
def test_noca_skrypt_mutacji_biegnie_przy_zmianie_folderu_skilla_jego_importow_albo_uruchamiacza(tmp_path: Path, changed: str, runs: bool) -> None:
    repo = repository(tmp_path / "repo", SKILLS)

    praca = zakres(Zdarzenie.NOC, frozenset({changed}), repo)

    # Skill bez pilnuje biegnie zawsze, a skrypt, którego tabeli nie da się wczytać, biegnie i pokazuje swój błąd.
    assert _decisions(praca)["verify-b/check_b_mutations.py"] == (True, ".agents/skills/verify-b/SKILL.md nie ma klucza pilnuje")
    assert (SCRIPT_A in _runs(praca), _runs(praca) >= {"verify-b/check_b_mutations.py", "verify-c/check_c_mutations.py"}) == (runs, True)


def test_noca_skrypt_mutacji_ktorego_tabeli_nie_da_sie_wczytac_biegnie_i_pokazuje_blad(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", SKILLS)

    decision = _decisions(zakres(Zdarzenie.NOC, frozenset({"docs/opis.md"}), repo))["verify-c/check_c_mutations.py"]

    assert decision[0] and decision[1].startswith("nie da się wczytać tabeli mutacji: "), decision


def test_noca_sprawdzenie_spoza_folderu_skilla_uruchamia_skrypt_ktorego_mutacje_je_uruchamiaja(tmp_path: Path) -> None:
    checker = "tests/test_sprawdzenie.py"
    repo = repository(
        tmp_path / "repo",
        {
            **SKILLS,
            checker: "X = 1\n",
            ".agents/skills/verify-b/SKILL.md": GUARDED,
            ".agents/skills/verify-b/scripts/check_b_mutations.py": WITH_TABLE.replace(".agents/skills/verify-a/scripts/sprawdz_a.py", checker),
        },
    )

    praca = zakres(Zdarzenie.NOC, frozenset({checker}), repo)

    assert (SCRIPT_A in _runs(praca), "verify-b/check_b_mutations.py" in _runs(praca)) == (False, True)


@pytest.mark.parametrize(
    ("event", "runs"),
    [(Zdarzenie.NOC, ["verify-b/check_b_mutations.py", "verify-c/check_c_mutations.py"]), (Zdarzenie.PUSH, [SCRIPT_A, "verify-b/check_b_mutations.py", "verify-c/check_c_mutations.py"])],
    ids=["noc", "push"],
)
def test_bez_zmian_od_bazy_noc_pomija_tylko_skill_z_pilnuje_i_tabela_a_push_biegnie_wszystko(
    tmp_path: Path, event: Zdarzenie, runs: list[str]
) -> None:
    repo = repository(tmp_path / "repo", SKILLS)

    praca = zakres(event, frozenset(), repo)

    assert sorted(_runs(praca)) == runs
    assert ({w.powod for w in praca.wybrane} == {""}) == (event is Zdarzenie.PUSH)


@pytest.mark.parametrize(
    ("skill_md", "reason"),
    [
        ("---\npilnuje: src/pakiet/routing.py\n---\n", "pilnuje w .agents/skills/verify-a/SKILL.md nie jest listą globów pod kluczem"),
        ("---\npilnuje:\nname: verify-a\n---\n", "pilnuje w .agents/skills/verify-a/SKILL.md nie ma żadnego globu"),
        # Frontmatter bez linii zamykającej nie ma kluczy, a nie psuje znalezienia kroków wszystkich skilli.
        ("---\nname: verify-a\npilnuje:\n  - src/pakiet/rout*.py\n", ".agents/skills/verify-a/SKILL.md nie ma klucza pilnuje"),
    ],
    ids=["pilnuje-nie-lista", "pilnuje-bez-globu", "frontmatter-niezamkniety"],
)
def test_pilnuje_ktorego_nie_da_sie_odczytac_uruchamia_skrypt(tmp_path: Path, skill_md: str, reason: str) -> None:
    repo = repository(tmp_path / "repo", {**SKILLS, ".agents/skills/verify-a/SKILL.md": skill_md})

    praca = zakres(Zdarzenie.NOC, frozenset(), repo)

    assert _decisions(praca)[SCRIPT_A] == (True, reason)


@pytest.mark.parametrize(
    ("script", "browser"),
    [
        ("from playwright.sync_api import sync_playwright\n", True),
        ("import playwright.sync_api\n", True),
        ("from .playwright import okno\n", False),
        ("def niedokonczona(\n", True),
    ],
    ids=["from-import", "import", "import-wzgledny", "skrypt-bez-skladni"],
)
def test_krok_skilla_potrzebuje_chromium_gdy_skrypt_skilla_importuje_playwright_albo_sie_nie_parsuje(
    tmp_path: Path, script: str, browser: bool
) -> None:
    changed = ".agents/skills/verify-a/scripts/sprawdz_a.py"
    repo = repository(tmp_path / "repo", {**SKILLS, changed: script})

    praca = zakres(Zdarzenie.NOC, frozenset({changed}), repo)

    assert [w.krok.browser for w in praca.wybrane if w.krok.key == SCRIPT_A] == [browser]


# --- katalog kroków skilli z korzenia checkoutu ---


BASELINE_K = ".agents/skills/verify-a/scripts/sprawdz_a.py"
SCRIPT_K = ".agents/skills/verify-a/scripts/check_a_mutations.py"
LOST_K = ".agents/skills/verify-b/scripts/check_mutation_proba.py"
# Skill a z podstawą w dwóch częściach i tabelą jednej mutacji, b bez pilnuje ze zgubionym skryptem, z ze złym
# ci-czesci, inny bez kroków, ze wskazaniem skryptu mutacji, którego nie ma. Podstawa a, tabela a, zgubiony skrypt i
# wskazanie są tylko w tym checkoucie.
KATALOG = {
    "src/pakiet/routing.py": "Z = 3\n",
    ".agents/skills/verify-a/SKILL.md": _with_ci("verify-a", BASELINE_K).replace("ci: ", "ci-czesci: 2\nci: "),
    BASELINE_K: "print('a')\n",
    SCRIPT_K: WITH_TABLE,
    ".agents/skills/verify-b/SKILL.md": "",
    ".agents/skills/verify-b/scripts/check_b_mutations.py": PASSING,
    LOST_K: "MUTATIONS = ()\n",
    ".agents/skills/verify-z/SKILL.md": f"---\nname: verify-z\nci-czesci: 0\nci: {BASELINE_K}\n---\n",
    ".agents/skills/inny/SKILL.md": "---\nname: inny\n---\npy -3 scripts\\check_inny_mutations.py\n",
}


def test_katalog_skilli_checkoutu_ma_kroki_i_bledy_jego_skilli(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", KATALOG)

    katalog = kroki_skilli.Katalog.skanuj(repo)

    assert [(step.key, step.name, step.command, step.parts, step.root, step.folder) for step in katalog.kroki] == [
        ("verify-a/ci", "PODSTAWA verify-a", (BASELINE_K,), 2, repo, ".agents/skills/verify-a/"),
        ("verify-a/check_a_mutations.py", SCRIPT_K, (SCRIPT_K,), 1, repo, ".agents/skills/verify-a/"),
        ("verify-b/check_b_mutations.py", ".agents/skills/verify-b/scripts/check_b_mutations.py", (".agents/skills/verify-b/scripts/check_b_mutations.py",), 1, repo, ".agents/skills/verify-b/"),
    ]
    assert dict(katalog.bledy) == {
        LOST_K: "nazwa spoza wzorca scripts/check_*_mutations.py",
        "PODSTAWA verify-z": "ci-czesci w .agents/skills/verify-z/SKILL.md nie jest liczbą części od 1",
        ".agents/skills/inny/scripts/check_inny_mutations.py": "wskazany w .agents/skills/inny/SKILL.md, a nie ma go pod tą nazwą",
    }
    assert [skill.name for skill in katalog.skille("verify-*")] == ["verify-a", "verify-b", "verify-z"]
    assert [skill.name for skill in katalog.skille()] == ["inny", "verify-a", "verify-b", "verify-z"]


@pytest.mark.parametrize(
    ("files", "bledy"),
    [
        ({".agents/skills/verify-a/SKILL.md": ""}, {"scripts/check_*_mutations.py": "brak skryptów .agents/skills/*/scripts/check_*_mutations.py"}),
        ({".agents/skills/verify-b/SKILL.md": "", LOST_K: "MUTATIONS = ()\n"}, {LOST_K: "nazwa spoza wzorca scripts/check_*_mutations.py"}),
    ],
    ids=["bez skryptow", "tylko zgubiony skrypt"],
)
def test_katalog_bez_skryptow_mutacji_to_fail_a_zgubiony_skrypt_juz_go_zglasza(tmp_path: Path, files: dict[str, str], bledy: dict[str, str]) -> None:
    assert dict(kroki_skilli.Katalog.skanuj(repository(tmp_path / "repo", files)).bledy) == bledy


def test_krok_katalogu_po_kluczu_planu(tmp_path: Path) -> None:
    katalog = kroki_skilli.Katalog.skanuj(repository(tmp_path / "repo", KATALOG))

    assert (katalog.krok(Klucz.z_tekstu("skill:verify-a/ci")).name, katalog.krok(Klucz.z_tekstu(f"skill:{SCRIPT_A}#2/3")).name) == ("PODSTAWA verify-a", SCRIPT_K)
    with pytest.raises(KeyError, match="verify-a/ci"):
        katalog.krok(Klucz.z_tekstu("krok:verify-a/ci"))


def test_reguly_kroku_skilla_licza_od_korzenia_checkoutu_skilla(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", KATALOG)
    katalog = kroki_skilli.Katalog.skanuj(repo)
    skill = repo / ".agents" / "skills" / "verify-a"

    found = kroki_skilli.hits(skill, {".agents/skills/verify-a/opis.md", "src/pakiet/routing.py", "docs/opis.md"})

    assert found == kroki_skilli.Hits({".agents/skills/verify-a/opis.md": kroki_skilli.FOLDER, "src/pakiet/routing.py": "src/pakiet/rout*.py"}, None)
    imported = {SCRIPT_K: ("tools/lib/z.py", "tools/lib/a.py")}.get

    assert kroki_skilli.watched(katalog.krok(Klucz.z_tekstu(f"skill:{SCRIPT_A}")), lambda path: imported(path, ())) == (
        ".agents/skills/verify-a/",
        "tools/lib/a.py",
        "tools/lib/z.py",
        *kroki_skilli.LAUNCHER,
        BASELINE_K,
    )
    assert kroki_skilli.ci_command(skill / "SKILL.md") == (BASELINE_K,)


MODEL = ".agents/skills/verify-m/model/M.tla"
MODEL_CHECK = ".agents/skills/verify-m/scripts/sprawdz_m.py"
MODEL_ENGINE = "tools/lib/silnik_modelu.py"
MODEL_UNTOUCHED = (
    "skrypt mutacji modelu biegnie na pull request tylko przy zmianie modelu, skryptu, sprawdzeń jego mutacji albo modułów, które te sprawdzenia importują"
)


def _model_skill(name: str, edited: tuple[str, ...]) -> dict[str, str]:
    """Skill ``name`` z folderem ``model/`` i skryptem mutacji, którego jedyna mutacja psuje pliki ``edited``."""

    edits = "".join(f'Edit(Path("{path}"), "X", "Y"), ' for path in edited)
    table = WITH_TABLE.replace(f'Edit(Path("{CHECKED}"), "X", "Y"), Edit(Path("{ANCHORS}"), "X", "Y")', edits)
    folder = f".agents/skills/{name}"
    return {
        f"{folder}/SKILL.md": GUARDED,
        f"{folder}/scripts/check_{name[-1]}_mutations.py": table.replace(".agents/skills/verify-a/scripts/sprawdz_a.py", MODEL_CHECK),
        f"{folder}/model/M.tla": "X\n",
        f"{folder}/model/m.cfg": "X\n",
        f"{folder}/model/oczekiwane.json": "{}\n",
        MODEL_CHECK: "from silnik_modelu import X\n",
        MODEL_ENGINE: "from tlc_modelu import Y\n\nX = Y\n",
        "tools/lib/tlc_modelu.py": "Y = 1\n",
        "tools/lib/obok.py": "Z = 1\n",
    }


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        (MODEL, True),
        (".agents/skills/verify-m/model/oczekiwane.json", True),
        (".agents/skills/verify-m/model/m.cfg", True),
        (".agents/skills/verify-m/scripts/check_m_mutations.py", True),
        (MODEL_CHECK, True),
        # Silnik modelu, który sprawdzenie importuje wprost albo przez inny moduł, decyduje o werdykcie jak samo sprawdzenie.
        (MODEL_ENGINE, True),
        ("tools/lib/tlc_modelu.py", True),
        ("tools/lib/obok.py", False),
        # Folder skilla poza modelem i silnik mutacji uruchamiają skrypt tylko nocą.
        (".agents/skills/verify-m/SKILL.md", False),
        # Sąsiad folderu modelu, którego nazwa zaczyna się od „model”, nie jest modelem.
        (".agents/skills/verify-m/model-notatki.md", False),
        (".agents/skills/verify-m/modele/M.tla", False),
        ("tools/lib/silnik_mutacji.py", False),
        ("requirements.txt", False),
        ("src/pakiet/routing.py", False),
    ],
)
def test_na_pull_request_skrypt_mutacji_modelu_biegnie_przy_zmianie_modelu_skryptu_albo_sprawdzenia(
    tmp_path: Path, changed: str, runs: bool
) -> None:
    # Skrypt, którego mutacja psuje także plik spoza modelu, nie jest skryptem mutacji modelu.
    files = {**SKILLS, **_model_skill("verify-m", (MODEL,)), **_model_skill("verify-n", (".agents/skills/verify-n/model/M.tla", CHECKED))}
    repo = repository(tmp_path / "repo", files)

    praca = zakres(Zdarzenie.PULL_REQUEST, frozenset({changed, ".agents/skills/verify-n/model/M.tla"}), repo)
    decisions = _decisions(praca)

    assert {key for key in _runs(praca) if not key.endswith("/ci")} == ({"verify-m/check_m_mutations.py"} if runs else set())
    assert decisions["verify-m/check_m_mutations.py"] == ((True, f"zmienione: {changed}") if runs else (False, f"{MODEL_UNTOUCHED}, a poza tym nocą"))
    assert decisions["verify-n/check_n_mutations.py"] == (False, "skrypt mutacji biegnie nocą na main (mutacje-nocne.yml, ADR 0021)")


@pytest.mark.parametrize(("changed", "runs"), [(True, True), (False, False)], ids=["zmieniony skrypt", "skrypt bez zmiany"])
def test_na_pull_request_skrypt_mutacji_ktorego_tabeli_nie_da_sie_wczytac_biegnie_gdy_go_zmieniono(
    tmp_path: Path, changed: bool, runs: bool
) -> None:
    script = ".agents/skills/verify-a/scripts/check_a_mutations.py"
    repo = repository(tmp_path / "repo", {**SKILLS, script: "MUTATIONS = (\n"})

    decision = _decisions(zakres(Zdarzenie.PULL_REQUEST, frozenset({script} if changed else ()), repo))[SCRIPT_A]

    assert decision[0] == runs
    assert decision[1].startswith("nie da się wczytać tabeli mutacji: ") if runs else decision[1] == "skrypt mutacji biegnie nocą na main (mutacje-nocne.yml, ADR 0021)"


BASELINE_D = ".agents/skills/verify-d/scripts/sprawdz_d.py"


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        ("docs/opis.md", False),
        ("src/pakiet/obcy.py", False),
        ("src/pakiet/routing.py", True),
        # Import sprawdzenia spoza pilnuje nie uruchamia podstawy na PR (ADR 0020): pełne CI main ją uruchamia.
        ("src/pakiet/pomocnik.py", False),
        (".agents/skills/verify-d/SKILL.md", True),
        ("requirements.txt", True),
        ("tools/ci/wykonaj_zadanie.py", False),
    ],
)
def test_ze_zmianami_od_bazy_podstawa_ci_biegnie_przy_trafieniu_w_pilnuje_albo_folder_skilla(
    tmp_path: Path, changed: str, runs: bool
) -> None:
    files = {**SKILLS, ".agents/skills/verify-d/SKILL.md": _with_ci("verify-d", BASELINE_D), BASELINE_D: "print('sprawdzone')\n"}
    repo = repository(tmp_path / "repo", files)

    decision = _decisions(zakres(Zdarzenie.PULL_REQUEST, frozenset({changed}), repo))["verify-d/ci"]

    assert decision == ((True, f"zmienione: {changed}") if runs else (False, "zmiany nie trafiają w pilnuje ani w folder skilla"))


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        (("src/pakiet/routa.py", "src/pakiet/routb.py", "src/pakiet/routing.py"), "zmienione: src/pakiet/routa.py, src/pakiet/routb.py, src/pakiet/routing.py"),
        (
            ("src/pakiet/routa.py", "src/pakiet/routb.py", "src/pakiet/routc.py", "src/pakiet/routing.py"),
            "zmienione: src/pakiet/routa.py, src/pakiet/routb.py, src/pakiet/routc.py i 1 innych",
        ),
    ],
    ids=["trzy", "cztery"],
)
def test_powod_podstawy_wymienia_najwyzej_trzy_zmienione_pliki_i_liczbe_pozostalych(
    tmp_path: Path, changed: tuple[str, ...], reason: str
) -> None:
    files = {**SKILLS, ".agents/skills/verify-d/SKILL.md": _with_ci("verify-d", BASELINE_D), BASELINE_D: "print('sprawdzone')\n"}
    repo = repository(tmp_path / "repo", files)

    decision = _decisions(zakres(Zdarzenie.PULL_REQUEST, frozenset(changed), repo))["verify-d/ci"]

    assert decision == (True, reason)


@pytest.mark.parametrize(
    ("event", "baseline", "script"),
    [
        (Zdarzenie.PULL_REQUEST, (True, "zmienione: "), (False, "skrypt mutacji biegnie nocą")),
        (Zdarzenie.NOC, (False, "podstawa biegnie na pull request, nie nocą"), (True, "zmienione: ")),
    ],
    ids=["pull-request", "noc"],
)
def test_na_pull_request_biegna_same_podstawy_a_noca_same_skrypty_mutacji(
    tmp_path: Path, event: Zdarzenie, baseline: tuple[bool, str], script: tuple[bool, str]
) -> None:
    command = ".agents/skills/verify-a/scripts/sprawdz_a.py"
    repo = repository(tmp_path / "repo", {**SKILLS, ".agents/skills/verify-a/SKILL.md": _with_ci("verify-a", command)})

    decisions = _decisions(zakres(event, frozenset({command}), repo))

    assert (decisions["verify-a/ci"][0], decisions[SCRIPT_A][0]) == (baseline[0], script[0])
    assert decisions["verify-a/ci"][1].startswith(baseline[1]) and decisions[SCRIPT_A][1].startswith(script[1]), decisions


@pytest.mark.parametrize(
    ("arguments", "event", "changed", "separately", "script"),
    [
        ("", Zdarzenie.PUSH, "", False, True),
        (" --pelny", Zdarzenie.PUSH, "", True, True),
        # Na PR biegnie sama podstawa, także przy zmianie folderu skilla, bo skrypt mutacji biegnie nocą.
        ("", Zdarzenie.PULL_REQUEST, "src/pakiet/routing.py", True, False),
        ("", Zdarzenie.PULL_REQUEST, ".agents/skills/verify-a/scripts/sprawdz_a.py", True, False),
    ],
)
def test_podstawa_ci_ktora_uruchamia_wybrany_skrypt_mutacji_nie_biegnie_drugi_raz(
    tmp_path: Path, arguments: str, event: Zdarzenie, changed: str, separately: bool, script: bool
) -> None:
    command = ".agents/skills/verify-a/scripts/sprawdz_a.py" + arguments
    repo = repository(tmp_path / "repo", {**SKILLS, ".agents/skills/verify-a/SKILL.md": _with_ci("verify-a", command)})

    runs = _runs(zakres(event, frozenset({changed} - {""}), repo))

    assert ("verify-a/ci" in runs, SCRIPT_A in runs) == (separately, script)


@pytest.mark.parametrize(
    ("event", "n", "parts"),
    [
        (Zdarzenie.NOC, 3, ((1, 1), (1, 2), (2, 2), (1, 3), (2, 3), (3, 3))),
        (Zdarzenie.NOC, 2, ((1, 1), (1, 2), (2, 2))),
        (Zdarzenie.PULL_REQUEST, 3, ()),
        (Zdarzenie.PUSH, 3, ()),
    ],
    ids=["noc, ci-czesci 3", "noc, ci-czesci 2", "pull-request", "push"],
)
def test_noca_podstawa_z_ci_czesci_biegnie_kazda_czescia_kazdego_n_a_pull_request_i_push_czesci_wybiera_plan(
    tmp_path: Path, event: Zdarzenie, n: int, parts: tuple[tuple[int, int], ...]
) -> None:
    # Argument odróżnia podstawę od polecenia mutacji skryptu, więc podstawa biegnie także obok skryptu.
    command = ".agents/skills/verify-a/scripts/sprawdz_a.py --czesciami"
    repo = repository(tmp_path / "repo", {**SKILLS, ".agents/skills/verify-a/SKILL.md": _with_ci("verify-a", command).replace("ci: ", f"ci-czesci: {n}\nci: ")})

    praca = zakres(event, frozenset({".agents/skills/verify-a/scripts/sprawdz_a.py"}), repo)

    assert {w.krok.key: tuple(str(czesc) for czesc in w.czesci) for w in praca.wybrane if w.krok.verdict is None} == {"verify-a/ci": tuple(f"{k}/{n}" for k, n in parts)}
    assert all(w.czesci == () for w in praca.wybrane if w.krok.verdict is not None)


ROUTING, ENGINE, LIBRARIES = "src/pakiet/routing.py", "tools/lib/silnik_mutacji.py", "requirements.txt"
FOLDER_C = ".agents/skills/verify-c/scripts/check_c_mutations.py"
# Podstawa w częściach skilla bez pilnuje.
BASELINE_E = ".agents/skills/verify-e/scripts/sprawdz_e.py"


@pytest.mark.parametrize(
    ("changed", "files"),
    [
        (
            {ROUTING, ENGINE, "docs/opis.md"},
            {
                "verify-d/ci": {ROUTING},
                "verify-e/ci": set(),
                SCRIPT_A: {ENGINE},
                "verify-b/check_b_mutations.py": {ENGINE},
                "verify-c/check_c_mutations.py": set(),
            },
        ),
        # Zmiana z SKILL_STEPS i folder skilla bez pilnuje albo bez czytelnej tabeli uruchamiają krok obok innego powodu.
        (
            {LIBRARIES, FOLDER_C, BASELINE_E},
            {
                "verify-d/ci": {LIBRARIES},
                "verify-e/ci": {LIBRARIES, BASELINE_E},
                SCRIPT_A: {LIBRARIES},
                "verify-b/check_b_mutations.py": {LIBRARIES},
                "verify-c/check_c_mutations.py": {LIBRARIES, FOLDER_C},
            },
        ),
        # Skill bez pilnuje i skrypt bez czytelnej tabeli biegną bez pliku, który by je uruchomił.
        ({"docs/opis.md"}, {"verify-e/ci": set(), "verify-b/check_b_mutations.py": set(), "verify-c/check_c_mutations.py": set()}),
    ],
    ids=["pilnuje i runner", "biblioteki i folder", "bez trafien"],
)
def test_noca_wybrany_krok_skilla_niesie_zmienione_pliki_ktore_go_uruchamiaja(
    tmp_path: Path, changed: set[str], files: dict[str, set[str]]
) -> None:
    skill_d = _with_ci("verify-d", BASELINE_D).replace("ci: ", "ci-czesci: 2\nci: ")
    skill_e = f"---\nname: verify-e\nci-czesci: 2\nci: {BASELINE_E}\n---\n"
    baselines = {".agents/skills/verify-d/SKILL.md": skill_d, BASELINE_D: "print('d')\n", ".agents/skills/verify-e/SKILL.md": skill_e, BASELINE_E: "print('e')\n"}
    repo = repository(tmp_path / "repo", {**SKILLS, **baselines})

    praca = zakres(Zdarzenie.NOC, frozenset(changed), repo)

    assert {w.krok.key: set(w.pliki) for w in praca.wybrane} == files


def test_zgubiony_skrypt_mutacji_i_zly_klucz_ci_trafiaja_do_bledow_zakresu_kazdego_zdarzenia(tmp_path: Path) -> None:
    lost = ".agents/skills/verify-a/scripts/check_mutation_proba.py"
    repo = repository(tmp_path / "repo", {**SKILLS, lost: "MUTATIONS = ()\n", ".agents/skills/verify-z/SKILL.md": "---\nname: verify-z\nci: brak.py\n---\n"})

    found = {event: zakres(event, frozenset(), repo).bledy for event in Zdarzenie}

    assert set(found.values()) == {
        (
            (lost, "nazwa spoza wzorca scripts/check_*_mutations.py"),
            ("PODSTAWA verify-z", "ci w .agents/skills/verify-z/SKILL.md nie zaczyna się skryptem .py z repozytorium"),
        )
    }


# --- polecenia skilla, które CI liczy ---


@pytest.mark.parametrize(
    ("changed", "commands"),
    [
        ("src/a/b.py", [("sprawdz_r.py", "--wszystko"), ("run_verification.py", "--variant", "all")]),
        (".agents/skills/verify-rozliczenia/SKILL.md", [("sprawdz_r.py", "--wszystko")]),
        ("docs/inne.md", []),
    ],
    ids=["src: podstawa i E2E", "tylko folder skilla: podstawa bez E2E", "nic"],
)
def test_polecenia_skilla_to_jego_wybrane_kroki_i_wywolania_w_krokach_ci_ktore_biegna_w_tym_runie(
    tmp_path: Path, changed: str, commands: list[tuple[str, ...]]
) -> None:
    skill = ".agents/skills/verify-rozliczenia"
    files = {
        f"{skill}/SKILL.md": _with_ci("verify-rozliczenia", f"{skill}/scripts/sprawdz_r.py --wszystko", "src/a/*"),
        f"{skill}/scripts/sprawdz_r.py": "print('r')\n",
        f"{skill}/scripts/run_verification.py": "print('e2e')\n",
        f"{skill}/scripts/check_r_mutations.py": "MUTATIONS = ()\n",
        # Zły klucz ci: nie daje polecenia, choć skill obowiązuje.
        ".agents/skills/verify-zly/SKILL.md": "---\nname: verify-zly\npilnuje:\n  - src/a/*\nci: docs/inne.md\n---\n",
        "src/a/b.py": "X = 1\n",
        "docs/inne.md": "inne\n",
    }
    repo = repository(tmp_path / "repo", files)

    praca = zakres(Zdarzenie.PULL_REQUEST, frozenset({changed}), repo)

    assert praca.polecenia(repo / skill) == commands
    assert praca.polecenia(repo / ".agents/skills/verify-zly") == []


# Katalog skilli w napisie workflow: ``.agents`` albo segment ścieżki ``skills`` z ``/`` lub ``\``, bez względu na
# wielkość liter, bo na Windows i macOS ``.AGENTS\SKILLS`` to ten sam katalog.
KATALOG_SKILLI = re.compile(r"\.agents\b|(?<![\w-])skills[/\\]|[/\\]skills(?![\w-])", re.IGNORECASE)


def _napisy(wezel: object) -> Iterator[str]:
    """Każda wartość drzewa YAML jako napis."""

    if isinstance(wezel, dict):
        for wartosc in wezel.values():
            yield from _napisy(wartosc)
    elif isinstance(wezel, list):
        for element in wezel:
            yield from _napisy(element)
    else:
        yield str(wezel)


def _odwolania_do_skilli(workflow: str) -> list[str]:
    """Napisy workflow, które wskazują katalog skilli (``KATALOG_SKILLI``)."""

    return [napis for napis in _napisy(yaml.safe_load(workflow)) if KATALOG_SKILLI.search(napis)]


def _workflow(krok: str) -> str:
    return f"name: CI\non: pull_request\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n{krok}"


@pytest.mark.parametrize(
    "krok",
    [
        "      - run: python .agents/skills/verify-a/scripts/sprawdz_a.py\n",
        "      - run: python -m runpy .agents/skills/verify-a/scripts/sprawdz_a.py\n",
        "      - working-directory: .agents/skills/verify-a/scripts\n        run: python sprawdz_a.py\n",
        "      - run: cd .agents/skills/verify-a && python scripts/sprawdz_a.py\n",
        "      - run: python .agents/skills/${{ matrix.skill }}/scripts/sprawdz.py\n",
        "      - env:\n          SKILL: .agents/skills/verify-a\n        run: python $SKILL/scripts/sprawdz_a.py\n",
        "      - shell: pwsh\n        run: python .agents\\skills\\verify-a\\scripts\\sprawdz_a.py\n",
        "      - if: runner.os == 'Windows'\n        run: py -3 .AGENTS\\SKILLS\\verify-a\\scripts\\sprawdz_a.py\n",
        "      - run: echo start\n      - run: python .agents/skills/verify-a/scripts/sprawdz_a.py\n",
        "      - run: for s in .agents/skills/*/scripts/check_*_mutations.py; do python $s; done\n",
        "      - run: cd .agents\n      - run: python skills/verify-a/scripts/sprawdz_a.py\n",
        '      - run: cd "${{ vars.KATALOG }}" && python skills/verify-a/scripts/sprawdz_a.py\n',
        "      - working-directory: ${{ vars.KATALOG }}/skills\n        run: python verify-a/scripts/sprawdz_a.py\n",
        "      - shell: pwsh\n        run: python ${{ vars.KATALOG }}\\skills\\verify-a\\scripts\\sprawdz_a.py\n",
        '      - uses: ./.github/actions/skill\n        with:\n          katalog: "${{ github.workspace }}/.agents"\n',
    ],
    ids=["ścieżka", "runpy", "working-directory", "cd", "matrix", "env", "backslash", "wielkie litery", "drugi krok", "glob", "cd w osobnym kroku", "skills/ ze zmiennej", "/skills ze zmiennej", "\\skills ze zmiennej", "with"],
)
def test_odwolanie_workflow_do_katalogu_skilli_w_kazdej_postaci_jest_zgloszone(krok: str) -> None:
    assert _odwolania_do_skilli(_workflow(krok)) != []


def test_komentarz_nazwa_kroku_i_runner_mutacji_skilli_nie_sa_odwolaniem_do_katalogu_skilli() -> None:
    krok = (
        "      # Runs .agents/skills/verify-a/scripts/sprawdz_a.py through the plan.\n"
        "      - name: Plan the mutation scripts of the skills changed since the base\n"
        "        run: python tools/ci/wykonaj_zadanie.py --plan .ci-plan/plan.json --zadanie mutacje-1\n"
        "      - uses: org/skills-cache@v1\n"
        "        with:\n          path: docs/myskills/\n"
    )

    assert _odwolania_do_skilli(_workflow(krok)) == []


def test_workflowy_runow_nie_wywoluja_skryptow_skilli_poza_planem() -> None:
    """Polecenia skilli w CI pochodzą z zakresu (kroki skilli i ``KROKI``), więc ``ci.yml`` i ``mutacje-nocne.yml`` nie
    wywołują skryptu skilla wprost: takie wywołanie nie trafiłoby do ``LICZY CI``.

    Strażnik zabrania więcej niż wywołania: żadna wartość YAML tych dwóch workflowów (``run``,
    ``working-directory``, ``env``, ``with``, macierz, nazwa kroku) nie wskazuje katalogu skilli, czyli nie zawiera
    ``.agents`` ani segmentu ścieżki ``skills`` z ``/`` lub ``\\`` (``KATALOG_SKILLI``). Łapie więc dosłowną ścieżkę
    skryptu, ``runpy``, ``working-directory`` i ``cd`` do folderu skilla, ``${{ matrix.* }}`` i glob w ścieżce, ścieżkę
    w ``env`` i ścieżkę Windows, także pisaną innymi wielkimi literami (``.AGENTS\\SKILLS``), w każdym kroku i jobie.
    Skrypty skilli workflow uruchamia tylko przez plan i runner
    (``tools/ci/wykonaj_zadanie.py``, ``tools/plan_ci.py``), które nie nazywają katalogu skilli.

    Granica: komentarze YAML nie są sprawdzane. Nie łapie ścieżki złożonej w czasie runu z części bez tych segmentów
    (``".ag""ents"``, wynik innego kroku spoza planu), globu bez obu segmentów (``.*/*/verify-*/...``), ``find
    -name 'check_*_mutations.py'`` ani ``\\`` w środku słowa, ani skryptu spoza ``.agents``, który sam uruchamia skrypt
    skilla; to łapie przegląd. Workflow skilla Windows (``verify-centrum-na-windowsie.yml``) to osobny run poza
    planem."""

    workflows = {
        "ci.yml": (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        "mutacje-nocne.yml": (ROOT / ".github" / "workflows" / "mutacje-nocne.yml").read_text(encoding="utf-8"),
    }

    assert {name: _odwolania_do_skilli(text) for name, text in workflows.items()} == {"ci.yml": [], "mutacje-nocne.yml": []}, (
        "ci.yml i mutacje-nocne.yml nie wywołują skryptu skilla wprost, bo takiego wywołania nie wymieniłaby linia LICZY CI: "
        "uruchom go jako krok zakresu runu (podstawa ci: we frontmatterze skilla, skrypt mutacji albo wywołanie w kroku CI "
        "z KROKI w tools/lib/zakres_runu.py)"
    )
