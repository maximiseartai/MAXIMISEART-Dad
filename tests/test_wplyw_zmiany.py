"""``tools/lib/wplyw_zmiany.py``: zmienione ścieżki, reguły „uruchom wszystko” i testy dotknięte zmianą, przez interfejs
modułu na repozytorium Gita w katalogu testu."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.fixtures.git_repo import commit, git

from wplyw_zmiany import Context, Repository, changed_since, run_all

ROOT = Path(__file__).resolve().parents[1]

# Moduł ``pakiet`` w ``src``: ``posredni`` importuje ``a``, a test importuje ``posredni``.
GRAPH = {
    "src/pakiet/__init__.py": "",
    "src/pakiet/a.py": "def wartosc() -> int:\n    return 1\n",
    "src/pakiet/posredni.py": "from pakiet.a import wartosc\n",
    "src/pakiet/b.py": "def inna() -> int:\n    return 1\n",
    "tests/test_posredni.py": "from pakiet.posredni import wartosc\n",
    "tests/test_zawsze_pada.py": "from pakiet.b import inna\n",
    "tools/narzedzie.py": "print('wynik')\n",
    "src/pakiet/narzedzia.py": "from pathlib import Path\n\nSKRYPT = Path('tools', 'narzedzie.py')\n",
    "tests/test_narzedzie.py": "from pakiet.narzedzia import SKRYPT\n",
    "src/witryna/__init__.py": "",
    "src/witryna/strona.py": "from pathlib import Path\n\nSTRONA = Path(__file__).parent / 'strona.html'\n",
    "src/witryna/strona.html": "Centrum\n",
    "tests/test_strona.py": "from witryna.strona import STRONA\n",
    "skille/a/OPIS.md": "pilnuje: src\n",
    "tests/test_opisy.py": "from pathlib import Path\n\nOPISY = (Path(__file__).parents[1] / 'skille').glob('*/OPIS.md')\n",
    "docs/dane/wpis.md": "zgodny\n",
    "tests/test_dane.py": "from pathlib import Path\n\nDANE = Path(__file__).parents[1] / 'docs' / 'dane'\n",
    "docs/wzorce/zestaw/wpis.md": "zgodny\n",
    # Test kopiuje katalog, a napis niesie tylko koniec jego ścieżki: początek przychodzi w argumencie.
    "tests/test_zestaw.py": "from pathlib import Path\n\n\ndef _kopia(docs: Path) -> Path:\n    return docs / 'wzorce' / 'zestaw'\n",
    "tests/test_koniec.py": "PLIK = 'dane/wpis.md'\n",
    "tests/test_glob_konca.py": "from pathlib import Path\n\n\ndef _wpisy(docs: Path) -> list[Path]:\n    return sorted((docs / 'dane').glob('*.md'))\n",
    "src/pakiet/pod/__init__.py": "",
    "src/pakiet/pod/wzgledny.py": "from ..a import wartosc\n",
    "tests/test_wzgledny.py": "from pakiet.pod.wzgledny import wartosc\n",
    "tests/skrypty/hak": "#!/usr/bin/env python3\nimport pakiet.a\n",
    "tests/test_hak.py": "HAK = 'tests/skrypty/hak'\n",
}
# Pliki, których test nie używa, choć coś w nich przypomina zależność.
UNUSED = {
    "tests/fixtures/opis.json": '{"plik": "src/pakiet/b.py"}\n',
    "tests/test_opis.py": "OPIS = 'tests/fixtures/opis.json'\n",
    "src/pakiet/proces.py": "PLIK = 'wpis.md'\n",
    "tests/test_proces.py": "from pakiet.proces import PLIK\n",
    "tools/raport.py": "",
    "tools/raport.md": "opis\n",
    "tests/test_raport.py": "import raport\n",
    ".agents/skills/a/scripts/narzedzie.py": "import drive\n",
    ".agents/skills/a/scripts/drive/__init__.py": "",
    ".agents/skills/b/scripts/drive/__init__.py": "",
    "tests/test_skill_a.py": "SKRYPT = '.agents/skills/a/scripts/narzedzie.py'\n",
    ".claude/settings.json": "{}\n",
    "tests/test_dom.py": "from pathlib import Path\n\nUSTAWIENIA = Path.home() / '.claude'\n",
    "tests/test_buduje.py": "KATALOG = 'src/pakiet'\n",
    "tests/skrypty/uruchom.sh": "#!/usr/bin/env python3\nimport pakiet.b\n",
    "tests/test_skrypt_sh.py": "SKRYPT = 'tests/skrypty/uruchom.sh'\n",
    "tests/skrypty/uruchom": "#!/usr/bin/env node\nrequire('src/pakiet/b.py')\n",
    "tests/test_skrypt_node.py": "SKRYPT = 'tests/skrypty/uruchom'\n",
    "tests/expected/test_raport.txt": "raport\n",
}
CONFIGURATION_READER = "from pathlib import Path\n\nKONFIGURACJA = Path('pyproject.toml')\n"


def _repo(path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    git(path, "init", "--quiet")
    commit(path, "baza")
    return path


@pytest.mark.parametrize(
    ("changed", "touched"),
    [
        ("src/pakiet/a.py", "tests/test_posredni.py"),
        ("tools/narzedzie.py", "tests/test_narzedzie.py"),
        ("docs/dane/wpis.md", "tests/test_dane.py"),
        ("docs/wzorce/zestaw/wpis.md", "tests/test_zestaw.py"),
        ("skille/a/OPIS.md", "tests/test_opisy.py"),
        ("src/witryna/strona.html", "tests/test_strona.py"),
        ("docs/dane/wpis.md", "tests/test_koniec.py"),
        ("docs/dane/wpis.md", "tests/test_glob_konca.py"),
        ("src/pakiet/a.py", "tests/test_wzgledny.py"),
        ("src/pakiet/a.py", "tests/test_hak.py"),
    ],
    ids=[
        "moduł, który test importuje przez inny moduł",
        "skrypt, który test uruchamia",
        "plik katalogu, który test czyta",
        "plik katalogu, który test wskazuje końcem jego ścieżki",
        "plik z globu na katalogu",
        "plik danych pakietu, który czyta jego moduł",
        "plik, który test wskazuje końcem jego ścieżki",
        "plik z globu na katalogu wskazanym końcem ścieżki",
        "moduł z importu względnego modułu, który test importuje",
        "moduł, który importuje skrypt Pythona bez rozszerzenia",
    ],
)
def test_test_jest_dotkniety_zmiana_pliku_od_ktorego_zalezy(tmp_path: Path, changed: str, touched: str) -> None:
    repo = _repo(tmp_path, GRAPH)

    tests = Repository.scan(repo).impact(frozenset({changed})).tests

    assert touched in tests
    assert "tests/test_zawsze_pada.py" not in tests


@pytest.mark.parametrize(
    ("changed", "untouched"),
    [
        ("src/pakiet/b.py", "tests/test_opis.py"),
        ("docs/dane/wpis.md", "tests/test_proces.py"),
        ("tools/raport.md", "tests/test_raport.py"),
        (".agents/skills/b/scripts/drive/__init__.py", "tests/test_skill_a.py"),
        (".claude/settings.json", "tests/test_dom.py"),
        ("src/pakiet/b.py", "tests/test_buduje.py"),
        ("src/pakiet/b.py", "tests/test_skrypt_sh.py"),
        ("src/pakiet/b.py", "tests/test_skrypt_node.py"),
        ("tests/expected/test_raport.txt", "tests/expected/test_raport.txt"),
    ],
    ids=[
        "plik nazwany w danych JSON, które test czyta",
        "plik nazwany bez katalogu w module poza testami",
        "plik obok modułu z tą samą nazwą bez rozszerzenia",
        "pakiet innego skilla z tą samą nazwą co pakiet obok skryptu",
        "katalog nazwany w teście bez ukośnika",
        "katalog pakietu nazwany w teście",
        "skrypt z rozszerzeniem innym niż .py i shebangiem Pythona",
        "skrypt bez rozszerzenia z shebangiem innego języka",
        "plik test_ w tests, który nie jest Pythonem",
    ],
)
def test_test_nie_jest_dotkniety_zmiana_pliku_ktorego_nie_uzywa(tmp_path: Path, changed: str, untouched: str) -> None:
    repo = _repo(tmp_path, {**GRAPH, **UNUSED})

    assert untouched not in Repository.scan(repo).impact(frozenset({changed})).tests


def test_plik_testow_z_koncowka_test_jest_wybierany_jak_plik_z_przedrostkiem_a_modul_pomocniczy_nie(tmp_path: Path) -> None:
    """Plik testów to plik, który pytest zbiera (domyślne ``python_files``: ``test_*.py`` i ``*_test.py``), więc wybór
    na pull request bierze ``tests/a_test.py`` tak samo jak pełne CI ``main``, a moduł obok bez takiej nazwy i plik z taką
    nazwą poza ``tests/`` nie są testem."""

    repo = _repo(
        tmp_path,
        {
            "src/pakiet/__init__.py": "",
            "src/pakiet/a.py": "A = 1\n",
            "tests/test_a.py": "from pakiet import a\n",
            "tests/a_test.py": "from pakiet import a\n",
            "tests/pomoc_a.py": "from pakiet import a\n",
            "tests/test_a.txt": "pakiet/a.py\n",
            # Skrypt skilla z końcówką ``_test`` leży poza ``tests/``, więc nie jest plikiem testów.
            ".agents/skills/verify-a/scripts/self_test.py": "from pakiet import a\n",
        },
    )

    assert sorted(Repository.scan(repo).impact(frozenset({"src/pakiet/a.py"})).tests) == ["tests/a_test.py", "tests/test_a.py"]


def test_skan_katalogu_poza_repozytorium_gita_pada_zamiast_dac_puste_repozytorium(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Puste repozytorium nie wybrałoby żadnego testu, jak zmiana, której nic nie dotyczy.
    folder = tmp_path / "bez_gita"
    folder.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))

    with pytest.raises(subprocess.CalledProcessError):
        Repository.scan(folder)


def test_odleglosc_od_zmiany_to_najkrotsza_droga_w_grafie_zaleznosci(tmp_path: Path) -> None:
    # ``tests/test_dane.py`` czyta ``docs/dane.md``, a ``src/czyta.py`` czyta go dla ``tests/test_czyta.py``.
    repo = _repo(
        tmp_path,
        {
            "src/a.py": "",
            "tests/test_a_drogi.py": "import a\n",
            "tests/test_a_tani.py": "import a\n",
            "src/b.py": "import a\n",
            "tests/test_b.py": "import b\n",
            "src/c.py": "import b\n",
            "tests/test_c_drogi.py": "import c\n",
            "tests/test_c_tani.py": "import c\n",
            "tests/test_c_bez_czasu.py": "import c\n",
            "docs/dane.md": "",
            "src/czyta.py": "from pathlib import Path\n\nDANE = Path('docs/dane.md')\n",
            "tests/test_dane.py": "from pathlib import Path\n\nDANE = Path('docs/dane.md')\n",
            "tests/test_czyta.py": "import czyta\n",
            "src/obok.py": "",
            "tests/test_obok.py": "import obok\n",
            "src/d.py": "import a\nimport czyta\n",
        },
    )

    impact = Repository.scan(repo).impact(frozenset({"src/a.py", "docs/dane.md"}))

    assert impact.distances == {
        "src/a.py": 0,
        "docs/dane.md": 0,
        "tests/test_a_drogi.py": 1,
        "tests/test_a_tani.py": 1,
        "src/b.py": 1,
        "tests/test_dane.py": 1,
        "src/czyta.py": 1,
        "src/d.py": 1,
        "tests/test_b.py": 2,
        "tests/test_czyta.py": 2,
        "src/c.py": 2,
        "tests/test_c_drogi.py": 3,
        "tests/test_c_tani.py": 3,
        "tests/test_c_bez_czasu.py": 3,
    }
    assert impact.tests == tuple(sorted(path for path in impact.distances if path.startswith("tests/")))


@pytest.mark.parametrize(
    ("path", "contexts"),
    [
        # Pliki, od których zależy każdy test (#305, #360): lokalnie i w bramce PR; biblioteki też każdy krok skilla.
        ("pyproject.toml", {Context.TESTS, Context.PR_GATE, Context.SKILL_STEPS}),
        ("tests/conftest.py", {Context.TESTS, Context.PR_GATE}),
        ("tests/fixtures/git_config.py", {Context.TESTS, Context.PR_GATE}),
        # Biblioteki: też każdy krok skilla (#293, powód przy regule).
        ("requirements.txt", {Context.TESTS, Context.PR_GATE, Context.SKILL_STEPS}),
        # Workflow w bramce PR (ADR 0020), a kroki skilli tylko przy zadaniu CI, w którym biegną (#293).
        (".github/workflows/ci.yml", {Context.PR_GATE, Context.SKILL_STEPS}),
        (".github/workflows/mutacje-nocne.yml", {Context.PR_GATE}),
        # Akcja złożona to kroki zadań pytest i Mutation checks, które workflowy wołają.
        (".github/actions/chromium/action.yml", {Context.PR_GATE, Context.SKILL_STEPS}),
        (".gitattributes", {Context.SKILL_STEPS}),
        (".github/scripts/py.cmd", set()),
        ("tests/fixtures/git_repo.py", set()),
        ("src/rozliczenia/engine.py", set()),
    ],
)
def test_zmiana_sciezki_uruchamia_wszystko_dokladnie_w_jej_kontekstach(path: str, contexts: set[Context]) -> None:
    assert {context for context in Context if run_all({path, "docs/inny.md"}, context) == (path,)} == contexts
    assert {context for context in Context if path in context.paths()} <= contexts


@pytest.mark.parametrize("changed", ["pyproject.toml", "requirements.txt", "tests/conftest.py", "tests/fixtures/git_config.py"])
def test_zmiana_pliku_kazdego_testu_wybiera_wszystkie_testy(tmp_path: Path, changed: str) -> None:
    repo = _repo(tmp_path, {**GRAPH, "tests/test_usuniety.py": ""})
    git(repo, "rm", "--quiet", "tests/test_usuniety.py")

    tests = Repository.scan(repo).impact(frozenset({changed, "tests/test_usuniety.py"})).tests

    assert tests == tuple(sorted(name for name in GRAPH if name.startswith("tests/test_")))


@pytest.mark.parametrize(
    ("also_changed", "distance"),
    [((), 2), (("tests/test_konfiguracja.py",), 0)],
    ids=["sama konfiguracja", "konfiguracja i jej czytelnik"],
)
def test_czytelnik_zmienionego_pliku_kazdego_testu_ma_odleglosc_najwyzej_2(
    tmp_path: Path, also_changed: tuple[str, ...], distance: int
) -> None:
    repo = _repo(tmp_path, {**GRAPH, "pyproject.toml": "", "tests/test_konfiguracja.py": CONFIGURATION_READER})
    repository = Repository.scan(repo)

    impact = repository.impact(frozenset({"pyproject.toml", *also_changed}))
    unchanged = repository.impact(frozenset({"src/pakiet/b.py"}))

    assert impact.distances["tests/test_konfiguracja.py"] == distance
    assert "pyproject.toml" not in impact.distances
    assert "tests/test_konfiguracja.py" not in unchanged.distances


def test_plik_kazdego_testu_nie_ma_odleglosci_takze_gdy_nazywa_sam_siebie(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {**GRAPH, "tests/conftest.py": "RADA = 'tests/conftest.py'\n"})

    impact = Repository.scan(repo).impact(frozenset({"tests/conftest.py"}))

    assert "tests/conftest.py" not in impact.distances


def test_test_ktory_importuje_usuniety_modul_jest_dotkniety_a_usuniety_test_nie(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {**GRAPH, "src/pakiet/usuniety.py": "", "tests/test_uzywa.py": "from pakiet.usuniety import X\n", "tests/test_stary.py": ""},
    )
    git(repo, "rm", "--quiet", "src/pakiet/usuniety.py", "tests/test_stary.py")

    impact = Repository.scan(repo).impact(changed_since(repo, "HEAD"))

    assert impact.tests == ("tests/test_uzywa.py",)
    assert impact.distances["tests/test_uzywa.py"] == 1


def test_odcisk_testu_zmienia_sie_z_jego_wejsciem_i_plikiem_kazdego_testu(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {**GRAPH, "pyproject.toml": ""})

    def fingerprint() -> str:
        return Repository.scan(repo).impact(frozenset({"src/pakiet/a.py"})).fingerprint("tests/test_posredni.py")

    first = fingerprint()
    (repo / "src" / "pakiet" / "b.py").write_text("ZMIANA = 1\n", encoding="utf-8")
    unrelated = fingerprint()
    (repo / "src" / "pakiet" / "a.py").write_text("ZMIANA = 1\n", encoding="utf-8")
    own_input = fingerprint()
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    configuration = fingerprint()

    assert first == unrelated
    assert len({unrelated, own_input, configuration}) == 3


GLOBS = (
    "from pathlib import Path\n\nROOT = Path(__file__).parents[1]\n"
    "SKRYPTY = [*(ROOT / 'narzedzia').glob('**/*.py'), *(ROOT / 'skille').glob('*/scripts/**/*.py'), *(ROOT / 'dane').rglob('*.json')]\n"
)


@pytest.mark.parametrize(
    ("changed", "touched"),
    [
        ("narzedzia/a.py", True),
        ("narzedzia/lib/b.py", True),
        ("narzedzia/lib/x/c.py", True),
        ("narzedzia/opis.md", False),
        ("skille/s/scripts/d.py", True),
        ("skille/s/scripts/drive/e.py", True),
        ("skille/s/f.py", False),
        ("dane/g.json", True),
        ("dane/x/h.json", True),
    ],
)
def test_glob_z_dwiema_gwiazdkami_obejmuje_plik_w_kazdej_glebokosci_takze_w_samym_katalogu(tmp_path: Path, changed: str, touched: bool) -> None:
    """``**`` w globie to zero albo więcej katalogów, jak w ``Path.glob``: test, który zbiera skrypty ``tools/**/*.py``,
    jest dotknięty zmianą ``tools/mutacje_nocne.py``, więc noc go uruchamia (#735, #761, #809)."""

    files = {name: "" for name in ("narzedzia/a.py", "narzedzia/lib/b.py", "narzedzia/lib/x/c.py", "narzedzia/opis.md")}
    files |= {name: "" for name in ("skille/s/scripts/d.py", "skille/s/scripts/drive/e.py", "skille/s/f.py", "dane/g.json", "dane/x/h.json")}
    repository = Repository.scan(_repo(tmp_path, {**files, "tests/test_globy.py": GLOBS}))

    assert ("tests/test_globy.py" in repository.impact(frozenset({changed})).tests) is touched
    assert ("tests/test_globy.py" in repository.reaching(changed)) is touched


def test_modul_skryptu_skilla_tylko_w_podkatalogu_scripts_jest_dotkniety_przez_test_ktory_go_importuje(tmp_path: Path) -> None:
    # Skill bez pliku prosto w ``scripts/``: jego ``scripts`` to i tak korzeń modułów, jak ``drive`` w verify-centrum-rozliczen.
    files = {".agents/skills/s/scripts/drive/__init__.py": "", ".agents/skills/s/scripts/drive/wspolne.py": "", "tests/test_drive.py": "import drive.wspolne\n"}
    repository = Repository.scan(_repo(tmp_path, files))

    assert "tests/test_drive.py" in repository.impact(frozenset({".agents/skills/s/scripts/drive/wspolne.py"})).tests


def test_test_siega_pliku_przez_katalog_nazwany_w_tescie_a_nie_przez_sciezke_nazwana_tylko_w_narzedziu(tmp_path: Path) -> None:
    # Test uruchamia skrypty z katalogu, który nazywa; narzędzie, które test uruchamia, nazywa inne narzędzie.
    repo = _repo(
        tmp_path,
        {
            **GRAPH,
            "narzedzia/skrypty/uruchom.py": "from pakiet.a import wartosc\n",
            "tests/test_skrypty.py": "from pathlib import Path\n\nSKRYPTY = Path(__file__).parents[1] / 'narzedzia' / 'skrypty'\n",
            "tools/kopiujace.py": "from pathlib import Path\n\nINNE = Path('tools/inne.py')\n",
            "tools/inne.py": "",
            "tests/test_kopiujace.py": "from pathlib import Path\n\nNARZEDZIE = Path('tools/kopiujace.py')\n",
        },
    )
    repository = Repository.scan(repo)

    assert "tests/test_skrypty.py" in repository.reaching("src/pakiet/a.py")
    assert "tests/test_skrypty.py" not in repository.impact(frozenset({"src/pakiet/a.py"})).tests
    assert "tests/test_kopiujace.py" not in repository.reaching("tools/inne.py")
    assert "tests/test_kopiujace.py" in repository.impact(frozenset({"tools/inne.py"})).tests
    assert repository.reaching("tools/inne.py") == frozenset()


def test_zmiana_od_bazy_to_pliki_od_rozgalezienia_z_niezacommitowanymi_nowymi_i_obiema_sciezkami_przeniesienia(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, GRAPH)
    trunk = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "--quiet", "-b", "praca")
    git(repo, "mv", "docs/dane/wpis.md", "docs/dane/przeniesiony.md")
    commit(repo, "przeniesienie")
    git(repo, "checkout", "--quiet", trunk)
    (repo / "skille" / "a" / "OPIS.md").write_text("pilnuje: tools\n", encoding="utf-8")
    moved = commit(repo, "baza poszła dalej")
    git(repo, "checkout", "--quiet", "praca")
    (repo / "src" / "pakiet" / "b.py").write_text("ZMIANA = 1\n", encoding="utf-8")
    (repo / "src" / "pakiet" / "nowy.py").write_text("", encoding="utf-8")
    (repo / "tools" / "narzedzie.py").unlink()

    changed = changed_since(repo, moved)

    assert changed == {"docs/dane/wpis.md", "docs/dane/przeniesiony.md", "src/pakiet/b.py", "src/pakiet/nowy.py", "tools/narzedzie.py"}
