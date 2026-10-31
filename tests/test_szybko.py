"""``tools/szybko.py``: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą, raz na tych samych plikach."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import szybko  # noqa: E402
from wplyw_zmiany import STRUCTURE  # noqa: E402

BY_CHANGE_ONLY = {
    "tests/test_brama_pre_push.py": "sprawdza zachowanie bramy pushem w repozytorium testu, a nie całe repozytorium",
    "tests/test_ciezkie_ci.py": "sprawdza strażnika narzędzi na repozytoriach testu i atrapie gh; ci.yml czyta ścieżką, którą graf widzi",
    "tests/test_czekanie.py": "sprawdza hook na pojedynczych poleceniach; graf wybiera go przy zmianie hooka i .claude/settings.json",
    "tests/test_eksplorator_w_procesie.py": (
        "sprawdza strażnika na katalogach przypadków w osobnym pytest; graf wybiera go przy zmianie pluginu (import), "
        "a zmiana tests/conftest.py uruchamia pełny zestaw"
    ),
    "tests/test_git_w_testach.py": (
        "sprawdza gita sesji testów, a nie całe repozytorium"
    ),
    "tests/test_komunikaty_expect.py": (
        "skanuje cały src/, ale globem (rglob) na src, który graf widzi, więc wybiera go przy zmianie każdego modułu "
        "src/, katalogu (import message_samples) i pliku tests/expected/komunikaty.txt (literał)"
    ),
    "tests/test_mutacje.py": "sprawdza silnik mutacji na repozytoriach testu, a nie całe repozytorium",
    "tests/test_mutacje_nocne.py": (
        "sprawdza narzędzie na repozytoriach testu i atrapie GitHuba; mutacje-nocne.yml czyta ścieżką, którą graf widzi"
    ),
    "tests/test_na_scalonych_pr.py": "sprawdza narzędzie na repozytoriach testu, a nie całe repozytorium",
    "tests/test_plan_ci.py": "sprawdza plan na repozytoriach testu i atrapach czasów; graf wybiera go przy zmianie planu i ci.yml",
    "tests/test_podstawa_w_czesciach.py": "sprawdza podział podstawy Centrum; graf wybiera go przy zmianie skilla, skrypt_skilla.py i mutacje_skilli.py",
    "tests/test_praca_w_toku.py": "sprawdza werdykt narzędzia na repozytoriach testu, a nie całe repozytorium; trwa ok. 19 s",
    "tests/test_scal_pr.py": "sprawdza narzędzie na atrapie gh i repozytoriach testu, a nie całe repozytorium",
    "tests/test_skille_dla_zmiany.py::test_liczy_ci_i_liczy_noc_wymieniaja_dokladnie_kroki_skilla_ktore_uruchamia_plan_pull_requestu_i_nocy": (
        "sprawdza linie LICZY CI i LICZY NOC na repozytorium testu, a nie całe repozytorium"
    ),
    "tests/test_skille_dla_zmiany.py::test_skrypt_mutacji_modelu_przy_zmianie_modelu_stoi_w_liczy_ci_a_nie_w_liczy_noc": (
        "sprawdza linie LICZY CI i LICZY NOC skryptu mutacji modelu na repozytorium testu, a nie całe repozytorium"
    ),
    "tests/test_skille_dla_zmiany.py::test_skill_z_poleceniami_w_ci_zostaje_w_skillach_verify_a_liczy_ci_wymienia_jego_polecenia": (
        "sprawdza wybór skilli na repozytorium testu, a nie całe repozytorium"
    ),
    "tests/test_szybko.py": "sprawdza samo szybko w repozytoriach testu; graf wybiera go przy zmianie tools/szybko.py i tabel reguł",
    "tests/test_zakres_runu.py": "sprawdza zakres runu na repozytoriach testu, a ci.yml i mutacje-nocne.yml czyta ścieżką, którą graf widzi",
    "tests/test_zadania_ci.py": "sprawdza ci.yml, który czyta ścieżką widoczną dla grafu, i plan na atrapach zapisów",
    "tests/test_zgoda.py": (
        "sprawdza hook zgody i jego wyrocznię na pojedynczych zdarzeniach; graf wybiera go przy zmianie hooka, wyroczni "
        "i .claude/settings.json"
    ),
}

# Pliki z tabelami reguł: nagłówek po polsku w dokumentach procesu, po angielsku w ``CODING_STANDARDS.md``.
RULE_TABLES = (
    ROOT / "AGENTS.md",
    ROOT / "CODING_STANDARDS.md",
    ROOT / "docs" / "agents" / "pr-i-ci.md",
    ROOT / "docs" / "agents" / "skille.md",
)
RULE_TABLE_HEADERS = ("| Reguła | Co jej pilnuje |", "| Rule | Guard |")

BASE_FILES = {
    ".agents/skills/verify-x/scripts/skrypt.py": "WARTOSC = 1\n",
    "uruchom.py": "WARTOSC = 1\n",
    "tools/hooks/pre-push": "#!/usr/bin/env python3\n",
    "src/pakiet/__init__.py": "",
    "src/pakiet/a.py": "def wartosc() -> int:\n    return 1\n",
    "src/pakiet/posredni.py": "from pakiet.a import wartosc\n\n\ndef podwojona() -> int:\n    return 2 * wartosc()\n",
    "src/pakiet/b.py": "def inna() -> int:\n    return 1\n",
    "tests/__init__.py": "",
    "tests/test_posredni.py": (
        "from pakiet.posredni import podwojona\n\n\ndef test_podwojona() -> None:\n    assert podwojona() == 2\n"
    ),
    "tests/test_zawsze_pada.py": "from pakiet.b import inna\n\n\ndef test_niedotkniety() -> None:\n    assert inna() == 2\n",
    "tools/narzedzie.py": "print('wynik')\n",
    "src/pakiet/narzedzia.py": "from pathlib import Path\n\nSKRYPT = Path('tools', 'narzedzie.py')\n",
    "tests/test_narzedzie.py": (
        "from pathlib import Path\nimport subprocess\nimport sys\n\nfrom pakiet.narzedzia import SKRYPT\n\n\n"
        "def test_narzedzie() -> None:\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    done = subprocess.run([sys.executable, str(root / SKRYPT)], capture_output=True, text=True, check=True)\n"
        "    assert done.stdout == 'wynik\\n'\n"
    ),
    "src/witryna/__init__.py": "",
    "src/witryna/strona.py": (
        "from pathlib import Path\n\n\ndef tytul() -> str:\n"
        "    return (Path(__file__).parent / 'strona.html').read_text(encoding='utf-8').strip()\n"
    ),
    "src/witryna/strona.html": "Centrum\n",
    "tests/test_strona.py": "from witryna.strona import tytul\n\n\ndef test_tytul() -> None:\n    assert tytul() == 'Centrum'\n",
    "skille/a/OPIS.md": "pilnuje: src\n",
    "tests/test_opisy.py": (
        "from pathlib import Path\n\nSKILLE = Path(__file__).resolve().parents[1] / 'skille'\n\n\n"
        "def test_opisy() -> None:\n"
        "    assert [p.read_text(encoding='utf-8') for p in SKILLE.glob('*/OPIS.md')] == ['pilnuje: src\\n']\n"
    ),
    "docs/dane/wpis.md": "zgodny\n",
    "tests/test_dane.py": (
        "from pathlib import Path\n\nDANE = Path(__file__).resolve().parents[1] / 'docs' / 'dane'\n\n\n"
        "def test_dane() -> None:\n"
        "    assert [path.read_text(encoding='utf-8') for path in sorted(DANE.iterdir())] == ['zgodny\\n']\n"
    ),
    "docs/wzorce/zestaw/wpis.md": "zgodny\n",
    # Test kopiuje katalog, a napis niesie tylko koniec jego ścieżki: początek przychodzi w argumencie.
    "tests/test_zestaw.py": (
        "from pathlib import Path\nimport shutil\n\n\n"
        "def _kopia(docs: Path, cel: Path) -> Path:\n"
        "    return Path(shutil.copytree(docs / 'wzorce' / 'zestaw', cel / 'kopia'))\n\n\n"
        "def test_zestaw(tmp_path: Path) -> None:\n"
        "    kopia = _kopia(Path(__file__).resolve().parents[1] / 'docs', tmp_path)\n"
        "    assert [path.read_text(encoding='utf-8') for path in kopia.iterdir()] == ['zgodny\\n']\n"
    ),
}
CONFIGURATION_READER = (
    "from pathlib import Path\n\n\ndef test_konfiguracja() -> None:\n    assert Path('pyproject.toml').name == 'inna.toml'\n"
)
UNIQUE_ADR = (
    "numbers = [p.name[:4] for p in (Path(__file__).parents[1] / 'docs' / 'adr').glob('*.md')]\n"
    "    assert len(numbers) == len(set(numbers))"
)
COUNTED = (
    "import os\nfrom pathlib import Path\n\nfrom pakiet.posredni import podwojona\n\n\n"
    "def test_podwojona() -> None:\n"
    "    with Path(os.environ['PRZEBIEGI']).open('a', encoding='utf-8') as runs:\n"
    "        runs.write('.')\n"
    "    assert podwojona() == 2\n"
)


@pytest.fixture(autouse=True)
def wspolny_cache_mypy(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mypy repozytoriów testu dzieli cache workera: typeshed i biblioteki nie są sprawdzane na nowo w każdym teście.

    Pliki repozytorium mają w każdym teście inną ścieżkę, więc mypy sprawdza je od nowa. Krok dla Windows ma własne
    ``--cache-dir`` w repozytorium testu i zmienna go nie dotyczy.
    """

    monkeypatch.setenv("MYPY_CACHE_DIR", str(tmp_path_factory.getbasetemp() / "mypy-szybko"))


def _structure_stubs(body: str) -> dict[str, str]:
    stubs: dict[str, str] = {}
    for node in STRUCTURE:
        path, _, name = node.partition("::")
        header = "from pathlib import Path\n" if "Path(" in body else ""
        stubs[path] = stubs.get(path, header) + f"\n\ndef {name or 'test_struktura'}() -> None:\n    {body}\n"
    return stubs


def _repo(tmp_path: Path, structure: str = "pass") -> Path:
    # Zadanie pytest na Windows w CI instaluje tylko requirements.txt; szybko biegnie tam w zadaniu na Linuksie.
    for static_check in ("ruff", "mypy"):
        pytest.importorskip(static_check, reason="szybko uruchamia ruff i mypy z dodatku dev")
    repo = repository(tmp_path / "repo", {**BASE_FILES, **_structure_stubs(structure)})
    # Krok najstarszego Pythona sprawdzają osobne testy; tu requires-python to Python, którym biegnie szybko.
    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    current = f'requires-python = ">={sys.version_info[0]}.{sys.version_info[1]}"'
    (repo / "pyproject.toml").write_text(re.sub(r"requires-python = .*", current, pyproject), encoding="utf-8")
    for name in (".gitignore", "tools/szybko.py", "tools/lib/wplyw_zmiany.py"):
        shutil.copy2(ROOT / name, repo / name)
    commit(repo, "baza")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _szybko(
    repo: Path, *arguments: str, runs: Path | None = None, workers: str | None = "2", path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    # ``PYTEST_XDIST_WORKER`` workera, który uruchamia ten test, nie może udawać workera szybko.
    environment = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    environment |= {"PATH": f"{path}{os.pathsep}{environment['PATH']}"} if path else {}
    environment |= {"PRZEBIEGI": str(runs)} if runs else {}
    environment |= {"PYTEST_XDIST_AUTO_NUM_WORKERS": workers} if workers else {}
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py"), *arguments],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _verdict(answered: subprocess.CompletedProcess[str]) -> str:
    """Ostatnia linia bez dopisku o przerwanym kroku pytest: czy skończył się przed porażką innego kroku, zależy od
    czasu, a przerwanie sprawdza ``test_blad_ruff_przerywa_krok_pytest_zamiast_czekac_na_jego_koniec``."""

    return answered.stdout.splitlines()[-1].removesuffix(" | pytest przerwany")


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


def _base_moved_on(repo: Path, on_main: tuple[str, str], on_branch: tuple[str, str]) -> None:
    """``origin/main`` z commitem ``on_main``, a HEAD na gałęzi od jego rodzica z commitem ``on_branch``."""

    git(repo, "checkout", "--quiet", "-b", "inna-galaz")
    _write(repo, *on_main)
    git(repo, "update-ref", "refs/remotes/origin/main", commit(repo, f"{on_main[0]} na main"))
    git(repo, "checkout", "--quiet", "-b", "galaz", "HEAD~1")
    _write(repo, *on_branch)
    commit(repo, f"{on_branch[0]} na gałęzi")


def _commit_times(repo: Path, expensive: dict[str, float]) -> None:
    """Czasy CI z main, jakie szybko pobrał dziś do ``.git/czasy-ci`` (artefakt ``czasy-ci``, ``tools/ci/czasy_ci.py``), i
    commit dotychczasowych zmian jako ``origin/main``."""

    times = {test: 0.1 for test in BASE_FILES if test.startswith("tests/test_")} | expensive
    keys = {f"pytest:{test}": [{"run": 7, "proba": 1, "zadanie": "pytest (Python 3.14, Linux, 1/2)", "s": s, "status": "ok"}] for test, s in times.items()}
    artifact = {"wersja": 1, "runy": [{"run": 7, "proba": 1, "sha": "0" * 40, "zdarzenie": "push"}], "tory": {szybko.TIMES_TOR: keys}}
    _write(repo, ".git/czasy-ci/7.json", json.dumps(artifact))
    _write(repo, ".git/czasy-ci/pobrane", "")
    commit(repo, "pliki testów z czasami")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


@pytest.mark.parametrize("committed", [True, False], ids=["zacommitowana", "niezacommitowana"])
def test_zmiana_modulu_uruchamia_testy_ktore_go_importuja_a_pozostalych_nie(tmp_path: Path, committed: bool) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 5\n")
    if committed:
        commit(repo, "zmiana a")

    answered = _szybko(repo)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (1, "SZYBKO FAIL | pytest")
    assert "FAILED tests/test_posredni.py::test_podwojona" in answered.stdout
    assert "test_zawsze_pada" not in answered.stdout


def test_blad_ruff_przerywa_krok_pytest_zamiast_czekac_na_jego_koniec(tmp_path: Path) -> None:
    repo = _repo(tmp_path, structure=UNIQUE_ADR)
    # Bez przerwania krok pytest skończyłby się po 30 s i przeszedł.
    _write(repo, "tests/test_wolny.py", "import time\n\nfrom pakiet.a import wartosc\n\n\ndef test_wolny() -> None:\n    time.sleep(30)\n    assert wartosc() == 1\n")
    commit(repo, "wolny test")
    _base_moved_on(repo, ("docs/adr/0002-z-main.md", "# ADR 0002\n"), ("docs/adr/0002-z-galezi.md", "# ADR 0002\n"))
    # Mypy i krok struktury po mergu nie są przerywane, więc ich błędy widać w tym samym przebiegu co błąd ruff.
    _write(repo, "src/pakiet/a.py", "import os\n\n\ndef wartosc() -> int:\n    return '1'\n")

    answered = _szybko(repo)

    assert re.search(r"^PRZERWANY pytest \(\d+ s\): padł inny krok, więc jego testy nie są sprawdzone$", answered.stdout, re.MULTILINE)
    last = answered.stdout.splitlines()[-1]
    expected = "SZYBKO FAIL | ruff, mypy, mypy (Windows), testy struktury po mergu z origin/main | pytest przerwany"
    assert (answered.returncode, last) == (1, expected), answered.stdout


def test_zmiana_bez_bledu_konczy_sie_ok_choc_niedotkniety_test_pada(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 0 + 1\n")

    answered = _szybko(repo)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_zielony_test_biegnie_znowu_dopiero_po_zmianie_pliku_od_ktorego_zalezy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runs = tmp_path / "przebiegi"
    _write(repo, "tests/test_posredni.py", COUNTED)
    first, again = _szybko(repo, runs=runs), _szybko(repo, runs=runs)
    _write(repo, "src/pakiet/a.py", "def wartosc() -> int:\n    return 2 - 1\n")
    after_change = _szybko(repo, runs=runs)

    assert [answered.stdout.splitlines()[-1] for answered in (first, again, after_change)] == ["SZYBKO OK"] * 3
    assert runs.read_text(encoding="utf-8") == ".."


def test_pamiec_zielonych_nie_przepuszcza_zmiany_pliku_danych_pakietu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with (repo / "src" / "witryna" / "strona.py").open("a", encoding="utf-8") as module:
        module.write("\n\nWERSJA = 2\n")
    green = _szybko(repo)
    _write(repo, "src/witryna/strona.html", "Inny tytuł\n")
    after_change = _szybko(repo)

    assert [green.stdout.splitlines()[-1], after_change.stdout.splitlines()[-1]] == ["SZYBKO OK", "SZYBKO FAIL | pytest"]
    assert "FAILED tests/test_strona.py::test_tytul" in after_change.stdout


@pytest.mark.parametrize(("workers", "expected"), [(None, "4"), ("3", "3")], ids=["bez zmiennej", "ze zmienną"])
def test_pytest_bierze_cztery_workery_chyba_ze_zmienna_mowi_inaczej(tmp_path: Path, workers: str | None, expected: str) -> None:
    repo = _repo(tmp_path)
    _write(
        repo,
        "tests/test_workery.py",
        f"import os\n\n\ndef test_workery() -> None:\n    assert os.environ['PYTEST_XDIST_AUTO_NUM_WORKERS'] == '{expected}'\n",
    )

    answered = _szybko(repo, workers=workers)

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_test_ktory_padl_biegnie_znowu_bez_zmian(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runs = tmp_path / "przebiegi"
    _write(repo, "tests/test_posredni.py", COUNTED.replace("== 2", "== 3"))

    answered = [_szybko(repo, runs=runs).stdout.splitlines()[-1] for _ in range(2)]

    assert answered == ["SZYBKO FAIL | pytest"] * 2
    assert runs.read_text(encoding="utf-8") == ".."


def test_nowy_niesledzony_test_biegnie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "tests/test_nowy.py", "def test_nowy() -> None:\n    assert False\n")

    answered = _szybko(repo)

    assert "FAILED tests/test_nowy.py::test_nowy" in answered.stdout
    assert answered.returncode == 1


def test_zmiana_konfiguracji_uruchamia_pelny_zestaw_i_mowi_dlaczego(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as file:
        file.write("\n")
    (repo / "tests" / "conftest.py").write_text("", encoding="utf-8")

    answered = _szybko(repo)

    assert "Testy pełny zestaw (zmiana w pyproject.toml, tests/conftest.py):" in answered.stdout
    assert "FAILED tests/test_zawsze_pada.py::test_niedotkniety" in answered.stdout
    assert answered.returncode == 1


def test_zmiana_konfiguracji_zostawia_ci_testy_ponad_budzet_i_mowi_ktore_w_kazdym_przebiegu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # Każdy z trzech drogich plików pada, gdy biegnie. ``test_konfiguracja`` wymienia ``pyproject.toml``, więc ma do
    # zmiany drogę w grafie, a z ``test_uszkodzone_wejscia`` biegnie jego test struktury i trafia do tego samego junit.
    _write(repo, "tests/test_konfiguracja.py", CONFIGURATION_READER)
    with (repo / "tests" / "test_uszkodzone_wejscia.py").open("a", encoding="utf-8") as stub:
        stub.write("\n\ndef test_reszta_pliku() -> None:\n    raise AssertionError('biegnie tylko w CI')\n")
    expensive = ("tests/test_konfiguracja.py", "tests/test_uszkodzone_wejscia.py", "tests/test_zawsze_pada.py")
    _commit_times(repo, dict.fromkeys(expensive, 9000.0))
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as file:
        file.write("\n")

    first, again = _szybko(repo), _szybko(repo)

    deferred = r"zostawione CI: 3 z \d+ plików testów \(~27000 s w CI\): test_konfiguracja\.py, test_uszkodzone_wejscia\.py, test_zawsze_pada\.py"
    for answered in (first, again):
        lines = answered.stdout.splitlines()
        assert re.fullmatch(deferred, lines[-2]), answered.stdout
        assert (answered.returncode, lines[-1]) == (0, "SZYBKO OK"), answered.stdout
    assert "zielone na tych samych plikach 0;" in first.stdout, first.stdout


@pytest.mark.parametrize(
    ("changed", "text", "failing"),
    [
        ("src/pakiet/b.py", "def inna() -> int:\n    return 0 + 1\n", "tests/test_zawsze_pada.py::test_niedotkniety"),
        ("tests/test_konfiguracja.py", CONFIGURATION_READER.replace("inna.toml", "inny.toml"), "tests/test_konfiguracja.py::test_konfiguracja"),
    ],
    ids=["moduł, który test importuje", "zmieniony test, który czyta konfigurację"],
)
def test_zmiana_konfiguracji_razem_z_innym_plikiem_uruchamia_zawsze_testy_w_odleglosci_1_od_niego(
    tmp_path: Path, changed: str, text: str, failing: str
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "tests/test_konfiguracja.py", CONFIGURATION_READER)
    _commit_times(repo, dict.fromkeys(("tests/test_konfiguracja.py", "tests/test_zawsze_pada.py"), 9000.0))
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as file:
        file.write("\n")
    _write(repo, changed, text)

    answered = _szybko(repo)

    assert f"FAILED {failing}" in answered.stdout, answered.stdout
    assert answered.returncode == 1


@pytest.mark.parametrize(
    ("also_changed", "reader_s", "deferred", "deferred_s"),
    [
        # Tańszy test_zawsze_pada nie ma drogi w grafie.
        ((), 100.0, "tests/test_zawsze_pada.py", 90.0),
        # test_posredni ma odległość 2 od a.py, tyle co test, który czyta konfigurację, więc rozstrzyga koszt.
        (("src/pakiet/a.py", "def wartosc() -> int:\n    return 0 + 1\n"), 90.0, "tests/test_posredni.py", 100.0),
    ],
    ids=["sama konfiguracja", "konfiguracja i moduł"],
)
def test_zmiana_konfiguracji_uruchamia_w_budzecie_testy_ktore_ja_czytaja_jak_w_odleglosci_2(
    tmp_path: Path, also_changed: tuple[str, str], reader_s: float, deferred: str, deferred_s: float
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "tests/test_konfiguracja.py", CONFIGURATION_READER)
    # Pojemność to 45 s na 4 workery, więc z dwóch drogich testów (razem 190 s) mieści się jeden.
    _commit_times(repo, {"tests/test_konfiguracja.py": reader_s, deferred: deferred_s})
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as file:
        file.write("\n")
    if also_changed:
        _write(repo, *also_changed)

    answered = _szybko(repo)

    assert "FAILED tests/test_konfiguracja.py::test_konfiguracja" in answered.stdout, answered.stdout
    name = re.escape(PurePosixPath(deferred).name)
    line = rf"^zostawione CI: 1 z \d+ plików testów \(~{deferred_s:.0f} s w CI\): {name}$"
    assert re.search(line, answered.stdout, re.MULTILINE), answered.stdout


def test_bez_czasow_ci_szybko_mowi_w_jednej_linii_dlaczego(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    offline = tmp_path / "bin"
    _write(offline, "gh", "#!/bin/sh\necho 'error connecting to api.github.com' >&2\nexit 1\n")
    (offline / "gh").chmod(0o755)

    answered = _szybko(repo, path=offline)

    line = "SZYBKO | bez czasów CI (pobranie czasy-ci z GitHuba: error connecting to api.github.com): każdy plik waży 0, więc biegnie cały wybór"
    assert line in answered.stdout.splitlines(), answered.stdout


# Odległości od zmiany ``src/a.py`` i ``docs/dane.md`` w grafie z
# ``tests/test_wplyw_zmiany.py::test_odleglosc_od_zmiany_to_najkrotsza_droga_w_grafie_zaleznosci``.
FROZEN_DISTANCES = {
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
FROZEN_TIMES = {
    "tests/test_a_drogi.py": 33.0,
    "tests/test_a_tani.py": 1.0,
    "tests/test_dane.py": 1.0,
    "tests/test_b.py": 4.0,
    "tests/test_czyta.py": 3.0,
    "tests/test_c_drogi.py": 200.0,
    "tests/test_c_tani.py": 2.0,
    "tests/test_obok.py": 2.0,
}


@pytest.mark.parametrize(
    ("budget_s", "deferred"),
    [
        # 4 workery po 10 s: odległość 1 zajmuje 35 s, test_czyta (3 s) i test_c_tani (2 s) dopełniają dokładnie 40 s,
        # a bliższy test_b (4 s) już się nie mieści.
        (10.0, ("tests/test_b.py", "tests/test_c_bez_czasu.py", "tests/test_c_drogi.py")),
        (0.0, ("tests/test_b.py", "tests/test_c_bez_czasu.py", "tests/test_c_drogi.py", "tests/test_c_tani.py", "tests/test_czyta.py")),
    ],
    ids=["budżet na część dalszych", "budżet zerowy"],
)
def test_plan_bierze_zawsze_odleglosc_1_a_dalsze_w_budzecie_i_nazywa_zostawione(budget_s: float, deferred: tuple[str, ...]) -> None:
    tests = sorted(path for path in FROZEN_DISTANCES if path.startswith("tests/"))

    chosen = szybko.plan(tests, FROZEN_DISTANCES, FROZEN_TIMES, budget_s)

    # Plik spoza tabeli kosztuje tyle, co mediana tabeli: 2,5 s.
    costs = {**dict.fromkeys(tests, 2.5), **FROZEN_TIMES}
    assert chosen.deferred == deferred
    assert sorted(chosen.run + chosen.deferred) == tests
    assert chosen.deferred_s == sum(costs[test] for test in deferred)
    assert {"tests/test_a_drogi.py", "tests/test_a_tani.py", "tests/test_dane.py"} <= set(chosen.run)


def test_testy_struktury_biegna_przy_zmianie_ktora_ich_nie_dotyka(tmp_path: Path) -> None:
    repo = _repo(tmp_path, structure="assert False")
    _write(repo, "docs/notatka.md", "nowa\n")

    answered = _szybko(repo)

    failed = set(re.findall(r"^FAILED (\S+)", answered.stdout, re.MULTILINE))
    assert {node if "::" in node else f"{node}::test_struktura" for node in STRUCTURE} <= failed
    assert answered.returncode == 1


def test_testy_struktury_biegna_tez_na_mergu_z_baza_ktora_poszla_dalej(tmp_path: Path) -> None:
    repo = _repo(tmp_path, structure=UNIQUE_ADR)
    _base_moved_on(repo, ("docs/adr/0002-z-main.md", "# ADR 0002\n"), ("docs/adr/0002-z-galezi.md", "# ADR 0002\n"))

    answered = _szybko(repo)

    last = _verdict(answered)
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | testy struktury po mergu z origin/main"), answered.stdout


def test_proces_testu_struktury_na_mergu_importuje_kod_z_mergu(tmp_path: Path) -> None:
    imports = "import subprocess\n    import sys\n\n    code = 'from pakiet.b import inna; assert inna() == 1'\n"
    repo = _repo(tmp_path, structure=f"{imports}    assert subprocess.run([sys.executable, '-c', code], check=False).returncode == 0")
    _base_moved_on(repo, ("src/pakiet/b.py", "def inna() -> int:\n    return 2\n"), ("docs/notatka.md", "z gałęzi\n"))

    answered = _szybko(repo)

    last = _verdict(answered)
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | testy struktury po mergu z origin/main"), answered.stdout


def test_testy_struktury_na_mergu_biegna_bez_workerow_xdist(tmp_path: Path) -> None:
    # Na HEAD biegną w kroku pytest z workerami, a na mergu, który ma plik z main, krok biegnie razem z nim.
    single_process = (
        "import os\n\n    on_merge = (Path(__file__).parents[1] / 'docs' / 'z-main.md').exists()\n"
        "    assert not (on_merge and 'PYTEST_XDIST_WORKER' in os.environ)"
    )
    repo = _repo(tmp_path, structure=single_process)
    _base_moved_on(repo, ("docs/z-main.md", "z main\n"), ("docs/notatka.md", "z gałęzi\n"))

    answered = _szybko(repo)

    assert re.search(r"^OK   testy struktury po mergu z origin/main \(\d+ s\)$", answered.stdout, re.MULTILINE), answered.stdout
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_konflikt_z_baza_jest_uwaga_a_nie_porazka(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _base_moved_on(repo, ("docs/notatka.md", "z main\n"), ("docs/notatka.md", "z gałęzi\n"))

    answered = _szybko(repo)

    assert "UWAGA: merge z origin/main ma konflikt w docs/notatka.md" in answered.stdout
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_blad_typu_tylko_na_windows_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/pakiet/system.py", "import os\n\n\ndef zakoncz(grupa: int) -> None:\n    os.killpg(grupa, 9)\n")

    answered = _szybko(repo)

    # Na Windows zwykły krok mypy też sprawdza Windows, więc pada razem z krokiem dla Windows.
    expected = "SZYBKO FAIL | mypy, mypy (Windows)" if sys.platform == "win32" else "SZYBKO FAIL | mypy (Windows)"
    assert (answered.returncode, _verdict(answered)) == (1, expected), answered.stdout


ONLY_NEWER_PYTHON = (
    "from dataclasses import dataclass, field\nfrom types import MappingProxyType\n\n\n"
    "@dataclass(frozen=True)\nclass Ilosci:\n    wartosci: object = field(default=MappingProxyType({}))\n"
)


def _requiring(repo: Path, version: tuple[int, int]) -> None:
    _write(repo, "pyproject.toml", f'[project]\nname = "pakiet"\nrequires-python = ">={version[0]}.{version[1]}"\n\n[tool.mypy]\nfiles = ["src"]\n')
    commit(repo, "requires-python")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_modul_ktory_nie_importuje_sie_najstarszym_pythonem_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    if sys.version_info[:2] == (3, 11) or shutil.which("uv") is None:
        pytest.skip("krok biegnie, gdy szybko ma Pythona nowszego niż 3.11 i uv, które da Pythona 3.11")
    repo = _repo(tmp_path)
    _requiring(repo, (3, 11))
    _write(repo, "src/pakiet/ilosci.py", ONLY_NEWER_PYTHON)

    answered = _szybko(repo)

    assert "pakiet.ilosci: ValueError: mutable default" in answered.stdout
    last = _verdict(answered)
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | import src pod Pythonem 3.11"), answered.stdout


def test_bez_uv_krok_najstarszego_pythona_pada_z_droga_naprawy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, (3, sys.version_info[1] - 1))
    git_folder = str(Path(shutil.which("git") or "git").parent)
    if shutil.which("uv", path=git_folder):
        pytest.skip("uv leży w tym samym folderze co git")

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py")],
        cwd=repo,
        env={**os.environ, "PATH": git_folder, "PYTEST_XDIST_AUTO_NUM_WORKERS": "2"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    oldest = f"3.{sys.version_info[1] - 1}"
    assert f"brak uv, więc szybko nie sprawdzi Pythona {oldest}: zainstaluj uv albo .venv z {oldest}" in answered.stdout
    last = _verdict(answered)
    assert (answered.returncode, last) == (1, f"SZYBKO FAIL | import src pod Pythonem {oldest}"), answered.stdout


FAKE_UV = f"""#!{sys.executable}
import os, subprocess, sys
with open(os.environ["WYWOLANIA_UV"], "a", encoding="utf-8") as calls:
    calls.write(("offline" if "--offline" in sys.argv else "online") + "\\n")
if "--offline" in sys.argv and os.environ["CACHE_UV"] == "zimny":
    sys.exit(1)
arguments = sys.argv[1:]
sys.exit(subprocess.run([sys.executable, *arguments[arguments.index("python") + 1 :]]).returncode)
"""


@pytest.mark.parametrize(("cache", "calls"), [("ciepły", ["offline"]), ("zimny", ["offline", "online"])])
def test_uv_pyta_siec_tylko_bez_cache_a_modul_ktory_sie_nie_importuje_wywraca_krok(
    tmp_path: Path, cache: str, calls: list[str]
) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, (3, sys.version_info[1] - 1))
    _write(repo, "src/pakiet/stary.py", "raise ImportError('tylko na nowszym Pythonie')\n")
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(FAKE_UV, encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "wywolania.txt"

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "szybko.py")],
        cwd=repo,
        env={**os.environ, "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}", "WYWOLANIA_UV": str(log), "CACHE_UV": cache},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert log.read_text(encoding="utf-8").split() == calls
    assert "pakiet.stary: ImportError: tylko na nowszym Pythonie" in answered.stdout
    last = _verdict(answered)
    assert (answered.returncode, last) == (1, f"SZYBKO FAIL | import src pod Pythonem 3.{sys.version_info[1] - 1}"), answered.stdout


def test_requires_python_bez_najstarszej_wersji_wywraca_szybkie_sprawdzenie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "pyproject.toml", '[project]\nname = "pakiet"\nrequires-python = "~=3.11"\n\n[tool.mypy]\nfiles = ["src"]\n')
    commit(repo, "requires-python")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    answered = _szybko(repo)

    assert "requires-python '~=3.11' nie ma postaci >=X.Y" in answered.stdout
    last = _verdict(answered)
    assert (answered.returncode, last) == (1, "SZYBKO FAIL | import src pod najstarszym Pythonem"), answered.stdout


def test_szybko_na_najstarszym_pythonie_nie_ma_osobnego_kroku_importu(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _requiring(repo, sys.version_info[:2])

    answered = _szybko(repo)

    assert "import src pod Pythonem" not in answered.stdout
    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "SZYBKO OK"), answered.stdout


def test_nieznana_baza_konczy_sie_jedna_linia_wyniku(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    answered = _szybko(repo, "--baza", "nie-ma-takiej")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["SZYBKO FAIL | nieznana baza nie-ma-takiej"])


def _rule_rows(text: str) -> list[str]:
    """Wiersze każdej tabeli reguł w tekście: linie ``|`` pod nagłówkiem z ``RULE_TABLE_HEADERS``, bez separatora."""

    rows: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.strip() in RULE_TABLE_HEADERS:
            in_table = True
        elif not (in_table and line.lstrip().startswith("|")):
            in_table = False
        elif not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", line.strip()):
            rows.append(line)
    return rows


def _lines_outside_rule_tables(text: str) -> list[str]:
    """Linie ``|`` spoza tabel reguł: każda tabela w pliku reguł, z dowolnym separatorem, zaczyna się nagłówkiem tabeli reguł."""

    outside: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.strip() in RULE_TABLE_HEADERS:
            in_table = True
        elif not line.lstrip().startswith("|"):
            in_table = False
        elif not in_table:
            outside.append(line)
    return outside


def _named_tests(guard: str) -> list[str]:
    """Testy z komórki strażnika: plik, węzeł ``plik::test`` i skrót ``::test`` pliku nazwanego wcześniej w komórce."""

    tests: list[str] = []
    file = ""
    for found in re.finditer(r"(tests/test_\w+\.py)?::(\w+)|tests/test_\w+\.py", guard):
        if found[2] is None:
            file = found[0]
            tests.append(file)
        else:
            file = found[1] or file
            tests.append(f"{file}::{found[2]}")
    return tests


def test_kazdy_test_z_tabel_regul_jest_testem_struktury_albo_ma_powod() -> None:
    """Tabele reguł żyją w ``RULE_TABLES``: plik bez tabeli i tabela w innym pliku Markdown wywracają test.

    Węzeł ``plik::test`` z tabeli biegnie sam albo z całym plikiem, bo inny węzeł tego pliku w ``STRUCTURE`` go nie
    uruchamia; sam plik z tabeli wystarcza z dowolnym swoim węzłem.
    """

    rows = {path: _rule_rows(path.read_text(encoding="utf-8")) for path in RULE_TABLES}
    listed = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"]
    markdown = subprocess.run(listed, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    elsewhere = [
        name
        for name in markdown.stdout.splitlines()
        if ROOT / name not in rows and (ROOT / name).is_file() and _rule_rows((ROOT / name).read_text(encoding="utf-8"))
    ]
    guards = [row.rsplit("|", 2)[-2] for found in rows.values() for row in found]
    named = {test for guard in guards for test in _named_tests(guard)}
    whole_files = {node for node in STRUCTURE if "::" not in node}
    files_with_node = {node.partition("::")[0] for node in STRUCTURE}

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *STRUCTURE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert [path.relative_to(ROOT).as_posix() for path, found in rows.items() if not found] == []
    outside = {
        path.relative_to(ROOT).as_posix(): lines
        for path in RULE_TABLES
        if (lines := _lines_outside_rule_tables(path.read_text(encoding="utf-8")))
    }
    assert outside == {}, "tabela w pliku reguł to tabela reguł: nagłówek z RULE_TABLE_HEADERS"
    assert elsewhere == [], "dopisz plik z tabelą reguł do RULE_TABLES"
    runs_every_time = {test for test in named if test in STRUCTURE or test in files_with_node or test.partition("::")[0] in whole_files}
    with_reason = {test for test in named if {test, test.partition("::")[0]} & BY_CHANGE_ONLY.keys()}
    undecided = named - runs_every_time - with_reason
    assert undecided == set(), "dopisz test do STRUCTURE w tools/lib/wplyw_zmiany.py albo powód do BY_CHANGE_ONLY"
    named_files = {test.partition("::")[0] for test in named}
    assert BY_CHANGE_ONLY.keys() - named - named_files == set(), "BY_CHANGE_ONLY ma test spoza tabeli"
    assert collected.returncode == 0, collected.stdout
