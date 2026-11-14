"""``tools/mutacje.py`` dowodzi, że polecenie pada na zepsutym kodzie, bez dotykania checkoutu.

Mutacje dopisują kod na końcu modułów ``rozliczenia`` w kopii checkoutu; kotwicą jest cała treść
modułu, więc test nie zależy od niej.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import pytest

from tests.fixtures.brama_typow import FAKE_GATE
from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import commit, git, repository
from tests.fixtures.potomne import beating, wait_for
import potomne

import ciezkie_ci
import mutacje
import plan_runu
import silnik_mutacji
from zakres_runu import Zdarzenie

ROOT = Path(__file__).resolve().parents[1]

TOOL = ROOT / "tools" / "mutacje.py"
PACKAGE = "src/rozliczenia/__init__.py"
IMPORT = ("-c", "import rozliczenia")


def _appended(module: str, code: str) -> list[str]:
    """Zmiana mutacji: ``code`` dopisany na końcu modułu."""

    source = (ROOT / module).read_text(encoding="utf-8")
    return [module, source, f"{source}{code}\n"]


def _mutacje(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_mutacja_kodu_kopii_jest_wykryta_mimo_edytowalnej_instalacji_checkoutu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "raise SystemExit(3)"), "--", *IMPORT)

    assert answered.returncode == 0, answered.stdout
    assert answered.stdout.splitlines()[-2:] == ["WYKRYTA: mutacja → kod wyjścia 3", "MUTACJE OK"]


def test_mutacja_bez_wplywu_na_polecenie_jest_niewykryta() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "# bez skutku"), "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEWYKRYTA: mutacja")


def test_mutacja_w_kilku_plikach_zmienia_wszystkie_naraz(tmp_path: Path) -> None:
    both = "import rozliczenia as r, rozliczenia.message as m; raise SystemExit(getattr(r, 'A', 0) + getattr(m, 'B', 0))"
    mutations = tmp_path / "mutacje.json"
    mutations.write_text(
        json.dumps(
            [
                {
                    "nazwa": "dwa pliki",
                    "zmiany": [_appended(PACKAGE, "A = 1"), _appended("src/rozliczenia/message.py", "B = 1")],
                }
            ]
        ),
        encoding="utf-8",
    )

    answered = _mutacje("--plik", str(mutations), "--", "-c", both)

    assert "WYKRYTA: dwa pliki → kod wyjścia 2" in answered.stdout.splitlines()


def test_mutacja_z_pusta_kotwica_tworzy_plik_w_nowym_katalogu() -> None:
    absent = "import pathlib, sys; sys.exit(pathlib.Path('.nowy/katalog/SKILL.md').is_file())"

    answered = _mutacje("--zmiana", ".nowy/katalog/SKILL.md", "", "skill", "--", "-c", absent)

    assert answered.stdout.splitlines()[-2:] == ["WYKRYTA: mutacja → kod wyjścia 1", "MUTACJE OK"]


# Początek i koniec docstringu pakietu: ta sama kotwica stoi w pliku dwa razy.
@pytest.mark.parametrize("anchor", ["tego tekstu nie ma w pliku", '"""'], ids=["brak", "wiele-razy"])
def test_mutacja_z_kotwica_nie_dokladnie_raz_w_pliku_jest_nieaktualna(anchor: str) -> None:
    answered = _mutacje("--zmiana", PACKAGE, anchor, "", "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEAKTUALNA: mutacja → kotwicy nie ma dokładnie raz")


def test_polecenie_czerwone_bez_mutacji_nie_daje_werdyktu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, ""), "--", "-c", "raise SystemExit(1)")

    assert answered.returncode == 2
    assert answered.stdout.splitlines()[0].startswith("PODSTAWA CZERWONA:")
    assert "WYKRYTA" not in answered.stdout


@pytest.mark.parametrize(
    ("end", "limit_s", "last"),
    [("sys.exit(1)", "600", "CLEANUP OK"), ("threading.Event().wait()", "2", "brak wyniku po 2 s")],
    ids=["pada", "po-limicie"],
)
def test_czerwona_podstawa_pokazuje_pod_swoja_linia_koniec_stdout_i_stderr(end: str, limit_s: str, last: str) -> None:
    """Jak przejazd verify-centrum-rozliczen na Windows w #932: porażka na stderr, a stdout kończy linia sprzątania.

    Podstawa po ``--limit-s`` pokazuje to, co zdążyła wypisać (#947). Koniec strumieni idzie na stderr, a log CI łączy
    stderr ze stdout, więc stoi tam pod linią ``PODSTAWA CZERWONA``; z dłuższego stdout zostaje jego koniec, nie początek.
    """

    steps = silnik_mutacji.BASE_TAIL + 5
    base = (
        f"import sys, threading; print(*(f'STEP krok-{{n}}' for n in range({steps})), sep=chr(10)); "
        f"print('DRIVE FAIL | przyczyna', file=sys.stderr); print('CLEANUP OK', flush=True); {end}"
    )

    def answered(stderr: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), "--limit-s", limit_s, "--zmiana", *_appended(PACKAGE, ""), "--", "-c", base],
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            # Krócej niż pytest-timeout (120 s): narzędzie, które nie kończy podstawy po --limit-s, pada tu, a nie wisi.
            timeout=60,
            check=False,
        )

    merged, split = answered(subprocess.STDOUT), answered(subprocess.PIPE)

    lines = merged.stdout.splitlines()
    tail = [f"  stdout | STEP krok-{number}" for number in range(steps - silnik_mutacji.BASE_TAIL + 1, steps)]
    end_lines = [*tail, "  stdout | CLEANUP OK", "  stderr | DRIVE FAIL | przyczyna"]
    refused = "MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi"
    assert (merged.returncode, lines[0].startswith("PODSTAWA CZERWONA: "), lines[0].endswith(f"→ {last}")) == (2, True, True), merged.stdout
    assert lines[1:] == [*end_lines, refused], merged.stdout
    assert (split.stdout.splitlines()[1:], split.stderr.splitlines()) == ([refused], end_lines), (split.stdout, split.stderr)


@pytest.mark.parametrize(
    ("checker", "verdict", "code"),
    [
        ("import rozliczenia\nprint(getattr(rozliczenia, 'RAPORT', 'SPRAWDZENIE OK'))", "WYKRYTA: wynik → SPRAWDZENIE: NARUSZENIE", 0),
        ("print('SPRAWDZENIE: NARUSZENIE')", "PODSTAWA CZERWONA:", 2),
    ],
    ids=["sprawdzenie-dziala", "sprawdzenie-zawsze-zglasza-naruszenie"],
)
def test_mutacja_z_oczekiwana_linia_jest_wykryta_tylko_gdy_bez_mutacji_jej_nie_ma(
    tmp_path: Path, checker: str, verdict: str, code: int
) -> None:
    plan = tmp_path / "mutacje.json"
    change = _appended(PACKAGE, "RAPORT = 'SPRAWDZENIE: NARUSZENIE'")
    plan.write_text(json.dumps([{"nazwa": "wynik", "zmiany": [change], "oczekiwane": "SPRAWDZENIE: NARUSZENIE"}]), encoding="utf-8")

    answered = _mutacje("--plik", str(plan), "--", "-c", checker)

    assert answered.returncode == code, answered.stdout
    assert answered.stdout.splitlines()[0].startswith(verdict), answered.stdout


def test_bez_polecenia_po_myslnikach_narzedzie_odmawia_z_podpowiedzia() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "raise SystemExit(3)"))

    hint = "podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu, albo --jak-ci"
    assert (answered.returncode, answered.stderr.splitlines()[-1].partition(": error: ")[2]) == (2, hint), answered.stdout


def test_pomoc_podaje_domyslna_galaz_bazy_regresu() -> None:
    answered = _mutacje("--help")

    assert answered.returncode == 0
    assert "--baza BAZA Gałąź, z której merge-base z HEAD daje REGRES i plan --jak-ci (domyślnie origin/main)." in " ".join(answered.stdout.split())


# Tyle linii ``--help`` czytali agenci pierwszym poleceniem (``| head -40``) w 143 ze 185 sesji implementacji (retro 6.11).
FIRST_PAGE = 40


def test_pierwsza_strona_pomocy_ma_przepis_z_plikiem_json_ktory_narzedzie_przyjmuje(tmp_path: Path) -> None:
    """Przepis (wywołania, pełny plik JSON, ``-n 0``, ``--baza``, limit mutacji) stoi w pierwszych ``FIRST_PAGE``
    liniach ``--help``, a zasady werdyktów drukuje dopiero ``--zasady``."""

    whole = _mutacje("--help").stdout
    page = whole.splitlines()[:FIRST_PAGE]
    answered = _mutacje("--zasady")
    rules = answered.stdout

    start, end = page.index("    ["), page.index("    ]")
    example = tmp_path / "mutacje.json"
    example.write_text("\n".join(page[start : end + 1]), encoding="utf-8")
    parsed = mutacje._from_file(example, ("-c", ""))
    text = " ".join(" ".join(page).split())
    assert [(mutation.name, len(mutation.edits), mutation.expected is not None) for mutation in parsed] == [("bez limitu", 1, False), ("dwa miejsca", 2, True)]
    assert "--zmiana src/rozliczenia/x.py 'if n > LIMIT:' 'if False:' \\ -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu" in text
    assert [phrase in text for phrase in ("``-p no:xdist`` pada", "``--baza``", f"najwyżej {ciezkie_ci.TARGETED} mutacji", "drukuje ``--zasady``")] == [True] * 4
    assert ("pytest-timeout" in whole, "ZAWIESZENIE to test, który pytest-timeout skończył" in rules) == (False, True)
    assert answered.returncode == 0, answered.stderr


@pytest.mark.parametrize(
    ("entries", "problem"),
    [
        ({"nazwa": "m"}, "plik mutacji to lista, nie dict"),
        (["m"], "wpis 1 nie jest obiektem"),
        ([{"zmiany": [["a.py", "x", "y"]]}], "wpis 1 ma zły albo brakujący klucz 'nazwa'"),
        ([{"nazwa": "m", "zmiana": [["a.py", "x", "y"]]}], "wpis 1 ma nieznany klucz 'zmiana'"),
        ([{"nazwa": "m", "zmiany": [["a.py", "x"]]}], "wpis 1 ma zły albo brakujący klucz 'zmiany'"),
        ([{"nazwa": "m", "zmiany": []}], "wpis 1 ma zły albo brakujący klucz 'zmiany'"),
        ([{"nazwa": "m", "zmiany": [["a.py", "x", "y"]]}, {"nazwa": "n", "zmiany": [["a.py", "x", "y"]], "polecenie": "-c"}], "wpis 2 ma zły albo brakujący klucz 'polecenie'"),
    ],
    ids=["nie-lista", "wpis-nie-obiekt", "bez-nazwy", "nieznany-klucz", "zmiana-bez-zamiany", "zmiany-puste", "polecenie-tekstem"],
)
def test_plik_mutacji_innej_postaci_jest_odrzucony_z_postacia_pliku(tmp_path: Path, entries: object, problem: str) -> None:
    plan = tmp_path / "mutacje.json"
    plan.write_text(json.dumps(entries), encoding="utf-8")

    answered = _mutacje("--plik", str(plan), "--", *IMPORT)

    assert (answered.returncode, answered.stderr.splitlines()[-1].partition(": error: ")[2]) == (2, f"{plan}: {problem}; postać: {mutacje.FILE_SHAPE}")


KOD_4 = (
    "pytest nie uruchomił testu (kod 4): zła ścieżka, test albo opcja w poleceniu po -- "
    "albo conftest.py, którego nie da się zaimportować; który, mówi koniec stderr niżej"
)


@pytest.mark.parametrize(
    ("command", "cause"),
    [
        (("-m", "pytest", "-q", "-n", "0", "tests/test_ciezkie_ci.py", "-k", "nie_ma_takiego_testu"), "pytest nie wybrał żadnego testu (kod 5), więc popraw ścieżkę albo -k w poleceniu po --; to błąd polecenia, nie kodu"),
        (("-m", "pytest", "-q", "-p", "no:xdist", "tests/test_ciezkie_ci.py"), "pytest odrzucił -p no:xdist (kod 4), bo addopts w pyproject.toml ma --dist, więc zamiast niego daj -n 0 w poleceniu po --"),
        (("-m", "pytest", "-q", "-n", "0", "tests/test_nie_ma_takiego_pliku.py"), KOD_4),
        (("-m", "pytest", "-q", "-n", "0", "tests/test_ciezkie_ci.py::nie_ma_takiego_testu"), KOD_4),
        (("-c", "raise SystemExit(5)"), None),
    ],
    ids=["nic-nie-wybrane", "bez-xdist", "brak-pliku", "brak-testu-node-id", "nie-pytest-z-kodem-5"],
)
def test_podstawa_pytest_bez_testu_podaje_przyczyne(command: tuple[str, ...], cause: str | None) -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, ""), "--", *command)

    lines = answered.stdout.splitlines()
    expected = [f"PODSTAWA BEZ TESTU: {cause}"] if cause else []
    shown = (answered.returncode, answered.stdout.startswith("PODSTAWA CZERWONA: "), lines[1:-1])
    assert shown == (2, True, expected), f"stdout:\n{answered.stdout}\nstderr:\n{answered.stderr}"


def test_podstawa_z_conftest_ktorego_nie_da_sie_zaimportowac_nie_jest_nazwana_bledem_polecenia(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text('raise NameError("zepsuty")\n', encoding="utf-8")
    (tmp_path / "test_a.py").write_text("def test_a() -> None:\n    pass\n", encoding="utf-8")

    answered = _mutacje("--zmiana", *_appended(PACKAGE, ""), "--", "-m", "pytest", "-q", "-n", "0", str(tmp_path / "test_a.py"))

    lines = answered.stdout.splitlines()
    assert (answered.returncode, lines[0].startswith("PODSTAWA CZERWONA: "), [line for line in lines if "BEZ TESTU" in line]) == (2, True, [f"PODSTAWA BEZ TESTU: {KOD_4}"]), answered.stdout


def test_pusta_lista_mutacji_niczego_nie_dowodzi() -> None:
    answered = subprocess.run(
        [sys.executable, "-c", "import sys\nsys.path.insert(0, 'tools/lib')\nfrom silnik_mutacji import check_all\nraise SystemExit(check_all(()))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert (answered.returncode, answered.stdout.strip()) == (1, "MUTACJE: brak mutacji, więc nie ma czego dowieść")


def test_skrypt_mutacji_skilla_pokazuje_czas_kazdej_mutacji_i_ostrzega_o_tej_ktora_zuzyla_ponad_polowe_limitu(tmp_path: Path) -> None:
    """Mutacja z #911 rosła od ~74 s do ponad 600 s, a log CI pokazał ją dopiero jako PRZEKROCZONY CZAS (#927).

    Czas i ostrzeżenie idą na stderr, które log CI łączy ze stdout: ostrzeżenie nie jest werdyktem, więc werdykty, linia
    ``MUTACJE OK`` i kod 0 zostają takie jak bez niego.
    """

    repo = _small_repository(tmp_path)
    script = ".agents/skills/verify-x/scripts/check_x_mutations.py"
    (repo / script).parent.mkdir(parents=True)
    (repo / script).write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, 'tools/lib')\nfrom silnik_mutacji import Edit, Mutation, check_all\n\n"
        "slow = ('-c', 'import time, rozliczenia\\nif rozliczenia.WARTOSC == 1:\\n    time.sleep(2)\\nraise SystemExit(rozliczenia.WARTOSC)')\n"
        "MUTATIONS = (\n"
        f"    Mutation('wolna', (Edit(Path({PACKAGE!r}), 'WARTOSC = 0', 'WARTOSC = 1'),), slow),\n"
        f"    Mutation('szybka', (Edit(Path({PACKAGE!r}), 'WARTOSC = 0', 'WARTOSC = 2'),), slow),\n"
        ")\nraise SystemExit(check_all(MUTATIONS, limit_s=4))\n",
        encoding="utf-8",
    )

    started = time.perf_counter()
    answered = subprocess.run(
        [sys.executable, script], cwd=repo, env=WITHOUT_XDIST_WORKERS | {"MUTACJE_CZESC": "1/1"}, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )
    took = time.perf_counter() - started

    shown = answered.stdout + answered.stderr
    verdicts = ["MUTACJE CZĘŚĆ 1/1: 2 z 2 mutacji", "WYKRYTA: wolna → kod wyjścia 1", "WYKRYTA: szybka → kod wyjścia 2", "MUTACJE OK"]
    assert (answered.returncode, answered.stdout.splitlines()) == (0, verdicts), shown
    times = answered.stderr.splitlines()
    assert len(times) == 3, shown
    slow = re.fullmatch(r"CZAS: wolna → ([0-9]+) s", times[0])
    fast = re.fullmatch(r"CZAS: szybka → ([0-9]+) s", times[1])
    warned = re.fullmatch(rf"CZAS BLISKO LIMITU: {re.escape(script)} \(MUTACJE_CZESC=1/1\): wolna → ([0-9]+) s z limitu --limit-s 4 s .*", times[2])
    assert slow and fast and warned, shown
    assert "to jeszcze nie porażka, ale przenieś mutację do mniejszego zakresu sprawdzenia albo przyspiesz sprawdzenie" in times[2], shown
    # Wolna śpi połowę limitu, więc jej polecenie zawsze trwa ponad połowę, a szybka nie śpi; żadna nie biegnie dłużej
    # niż cały skrypt na zegarze testu.
    assert (2 <= int(slow[1]) <= round(took), int(fast[1]) < int(slow[1]), warned[1] == slow[1]) == (True, True, True), shown
    # Z linii ostrzeżenia noc odtwarza skrypt, część, mutację, czas i limit, które zgłasza w issue PR-u (#935).
    assert silnik_mutacji.near_limits(answered) == [silnik_mutacji.NearLimit(script, "1/1", "wolna", int(slow[1]), 4)], shown


def test_czesci_tabeli_sprawdzaja_kazda_mutacje_raz_kazda_z_podstawa_tylko_polecen_swoich_mutacji(tmp_path: Path) -> None:
    """Podstawa części biegnie po kolei dla każdego polecenia jej mutacji, więc część bierze mutacje jednego polecenia
    razem: tu sześć mutacji trzech poleceń w dwóch częściach uruchamia cztery podstawy, a nie sześć, jak przy podziale
    co drugą po nazwie (m1, m3, m5 i m2, m4, m6 to w obu częściach polecenia A, B i C)."""

    repo = _small_repository(tmp_path)
    log = tmp_path / "polecenia"

    def command(name: str) -> list[str]:
        seen = "os.environ.get('MUTACJE_CZESC', '-')"
        writes = f"open(os.environ['DZIENNIK'], 'a').write('{name} ' + str(rozliczenia.WARTOSC) + ' ' + {seen} + chr(10))"
        return ["-c", f"import os, rozliczenia\n{writes}\nraise SystemExit(rozliczenia.WARTOSC)"]

    table = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]], "polecenie": command("CAB"[number % 3])} for number in range(1, 7)]
    seen = {}
    # Każda część to osobne zadanie CI z tą samą tabelą, a kolejność tabeli nie zmienia podziału.
    for part, order in (("1/2", table), ("2/2", table[::-1]), ("2/3", table[2:] + table[:2]), ("1/7", table)):
        (tmp_path / "mutacje.json").write_text(json.dumps(order), encoding="utf-8")
        log.write_text("", encoding="utf-8")
        answered = _in_repository(repo, "--plik", str(tmp_path / "mutacje.json"), "--", "-c", "", env=WITHOUT_XDIST_WORKERS | {"MUTACJE_CZESC": part, "DZIENNIK": str(log)})
        checked = sorted(line.split()[1] for line in answered.stdout.splitlines() if line.startswith("WYKRYTA: "))
        ran = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
        baseline = sorted(command for command, value, _ in ran if value == "0")
        # Część dzieli tabelę skryptu, a sprawdzane polecenie zmiennej nie dostaje.
        seen[part] = (answered.returncode, answered.stdout.splitlines()[-1], checked, baseline, {inherited for _, _, inherited in ran})
    broken = _in_repository(repo, "--plik", str(tmp_path / "mutacje.json"), "--", "-c", "", env=WITHOUT_XDIST_WORKERS | {"MUTACJE_CZESC": "0/3", "DZIENNIK": str(log)})

    assert seen == {
        "1/2": (0, "MUTACJE OK", ["m1", "m2", "m4"], ["A", "B"], {"-"}),
        "2/2": (0, "MUTACJE OK", ["m3", "m5", "m6"], ["B", "C"], {"-"}),
        "2/3": (0, "MUTACJE OK", ["m2", "m5"], ["B"], {"-"}),
        "1/7": (0, "MUTACJE OK", [], [], set()),
    }
    assert broken.returncode == 1 and "MUTACJE_CZESC to K/N z 1 <= K <= N, nie '0/3'" in broken.stderr, broken.stderr


def test_kopia_ma_niezacommitowane_zmiany_checkoutu_a_checkout_zostaje_nietkniety(tmp_path: Path) -> None:
    package = "src/rozliczenia"
    repo = repository(
        tmp_path / "repo",
        {
            ".gitignore": "__pycache__/\n",
            **{f"{package}/{name}.py": "WARTOSC = 0\n" for name in ("__init__", "w_indeksie", "poza_indeksem", "usuniety")},
        },
    )
    commit(repo, "baza")
    (repo / package / "w_indeksie.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    git(repo, "add", f"{package}/w_indeksie.py")
    (repo / package / "poza_indeksem.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "nowy.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "usuniety.py").unlink()
    status = git(repo, "status", "--porcelain")
    sees_changes = (
        "import importlib.util as u, rozliczenia.w_indeksie as a, rozliczenia.poza_indeksem as b, rozliczenia.nowy as c; "
        "raise SystemExit(0 if a.WARTOSC + b.WARTOSC + c.WARTOSC == 3 and not u.find_spec('rozliczenia.usuniety') else 9)"
    )
    tool = [sys.executable, str(repo / "tools" / "mutacje.py")]

    answered = subprocess.run(
        [*tool, "--zmiana", f"{package}/nowy.py", "WARTOSC = 1", "WARTOSC = 2", "--", "-c", sees_changes],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: mutacja → kod wyjścia 9", "MUTACJE OK"]
    assert (git(repo, "status", "--porcelain"), git(repo, "worktree", "list", "--porcelain").count("worktree ")) == (status, 1)


def test_plik_mutacji_spoza_repozytorium_jest_odrzucony_przed_zmiana() -> None:
    answered = _mutacje("--zmiana", str(ROOT / PACKAGE), "x", "y", "--", *IMPORT)

    assert answered.returncode == 2
    assert "plik mutacji musi leżeć w repozytorium" in answered.stderr


@pytest.mark.parametrize(
    ("before", "after"),
    [({"zmiana": "plik"}, {"zmiana/a.txt": "nowy", "zmiana/b.txt": "nowy", "zmiana/c.txt": "nowy"}), ({"zmiana/a.txt": "stary"}, {"zmiana": "nowy"})],
    ids=["plik-w-katalog", "katalog-w-plik"],
)
def test_kopia_ma_sciezke_ktora_zmienila_typ(tmp_path: Path, before: dict[str, str], after: dict[str, str]) -> None:
    repo = repository(tmp_path / "repo", {"src/rozliczenia/__init__.py": "WARTOSC = 0\n", **before})
    commit(repo, "baza")
    if (repo / "zmiana").is_dir():
        shutil.rmtree(repo / "zmiana")
    else:
        (repo / "zmiana").unlink()
    for name, text in after.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    sees_after = (
        "import pathlib, rozliczenia; path = pathlib.Path('zmiana'); "
        "seen = {file.as_posix(): file.read_text() for file in [path, *path.rglob('*')] if file.is_file()}; "
        f"raise SystemExit(0 if seen == {after!r} and rozliczenia.WARTOSC == 0 else 9)"
    )

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), "--zmiana", "src/rozliczenia/__init__.py", "WARTOSC = 0", "WARTOSC = 1", "--", "-c", sees_after],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: mutacja → kod wyjścia 9", "MUTACJE OK"], answered.stderr


def _hanging_repository(path: Path) -> tuple[Path, list[str], Path, Path]:
    """Repozytorium, którego mutacja uruchamia wnuka i wisi; wnuk, póki żyje, dopisuje do pliku co 0,1 s."""

    repo = repository(path / "repo", {"src/rozliczenia/__init__.py": "WISI = False\n"})
    commit(repo, "baza")
    started, beats = path / "wystartowal", path / "wnuk-zyje"
    grandchild = f"import time\nwhile True:\n    open({str(beats)!r}, 'a').write('.')\n    time.sleep(0.1)\n"
    hangs = (
        "import pathlib, subprocess, sys, time, rozliczenia\n"
        "if rozliczenia.WISI:\n"
        f"    subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        f"    while not pathlib.Path({str(beats)!r}).exists():\n"
        "        time.sleep(0.1)\n"
        f"    pathlib.Path({str(started)!r}).touch()\n"
        "    time.sleep(60)\n"
    )
    mutation = ["--zmiana", "src/rozliczenia/__init__.py", "WISI = False", "WISI = True", "--", "-c", hangs]
    return repo, mutation, started, beats


def test_polecenie_bez_wyniku_w_limicie_czasu_narzedzia_daje_przekroczony_czas(tmp_path: Path) -> None:
    repo, mutation, _, _ = _hanging_repository(tmp_path)

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), "--limit-s", "2", *mutation],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    expected = "PRZEKROCZONY CZAS: mutacja → brak wyniku po 2 s (limit --limit-s narzędzia, nie pytest-timeout)"
    assert (answered.returncode, answered.stdout.splitlines()[0]) == (1, expected)
    # Polecenie kończy się z limitem, a nie później: tekst werdyktu podaje limit z argumentu, nie czas, który minął.
    spent = re.search(r"^CZAS: mutacja → ([0-9]+) s$", answered.stderr, re.MULTILINE)
    assert spent and 2 <= int(spent[1]) < 4, answered.stderr


@pytest.mark.parametrize(
    ("method", "line"),
    [
        pytest.param(
            "signal",
            re.escape("Failed: Timeout (>1.0s) from pytest-timeout."),
            marks=pytest.mark.skipif(sys.platform == "win32", reason="metoda signal pytest-timeout potrzebuje SIGALRM"),
        ),
        # Szerokość nagłówka zależy od terminala, w którym biegnie pytest.
        ("thread", r"\++ Timeout \++"),
    ],
)
def test_test_skonczony_przez_pytest_timeout_po_mutacji_daje_zawieszenie_a_nie_wykryta(tmp_path: Path, method: str, line: str) -> None:
    """#660: test, który po mutacji wisi do limitu pytest-timeout, pada, ale to zawieszenie, a nie wykrycie."""

    repo = repository(
        tmp_path / "repo",
        {PACKAGE: "WISI = False\n", "tests/test_wisi.py": "import time, rozliczenia\n\n\ndef test_wisi():\n    if rozliczenia.WISI:\n        time.sleep(60)\n"},
    )
    commit(repo, "baza")

    answered = _in_repository(
        repo,
        *("--zmiana", PACKAGE, "WISI = False", "WISI = True"),
        *("--", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "--timeout", "1", "--timeout-method", method, "tests/test_wisi.py"),
    )

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert re.fullmatch(f"ZAWIESZENIE: mutacja → {line}", answered.stdout.splitlines()[0]), answered.stdout + answered.stderr


def test_mutacja_niewykryta_bez_merge_base_z_baza_zostaje_niewykryta_z_powodem_na_stderr(tmp_path: Path) -> None:
    """Checkout CI nie ma gałęzi bazy, a pierwsza linia wyjścia zostaje werdyktem mutacji."""

    repo = _small_repository(tmp_path)

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", "-c", "")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["NIEWYKRYTA: mutacja → kod wyjścia 0", "MUTACJE: 1 bez oczekiwanego wyniku"])
    assert answered.stderr.startswith("MERGE-BASE: brak merge-base HEAD z glowna, więc REGRES niesprawdzony, a NIEWYKRYTA bez porównania"), answered.stderr


def test_wykryta_mutacja_bez_merge_base_z_baza_nie_zglasza_niesprawdzonego_regresu(tmp_path: Path) -> None:
    """REGRES sprawdza się tylko dla mutacji NIEWYKRYTA, więc bez niej brak merge-base niczego nie pomija."""

    repo = _small_repository(tmp_path)
    caught = "import rozliczenia; raise SystemExit(rozliczenia.WARTOSC)"

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", "-c", caught)

    assert (answered.returncode, answered.stdout.splitlines()) == (0, ["WYKRYTA: mutacja → kod wyjścia 1", "MUTACJE OK"]), answered.stderr
    assert [line for line in answered.stderr.splitlines() if not line.startswith("CZAS: mutacja → ")] == [], answered.stderr


def test_merge_base_rowny_czystemu_checkoutowi_nie_uruchamia_mutacji_drugi_raz(tmp_path: Path) -> None:
    # Bez .gitignore pliki __pycache__ narzędzi byłyby niezacommitowaną zmianą checkoutu.
    repo = repository(tmp_path / "repo", {PACKAGE: "WARTOSC = 0\n", ".gitignore": "__pycache__/\n"})
    commit(repo, "baza")
    git(repo, "branch", "glowna")
    runs = tmp_path / "przebiegi"
    counted = f"import pathlib; path = pathlib.Path({str(runs)!r}); path.write_text(path.read_text() + '.' if path.exists() else '.')"

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", "-c", counted)

    assert answered.stdout.splitlines() == ["NIEWYKRYTA: mutacja → kod wyjścia 0", "MUTACJE: 1 bez oczekiwanego wyniku"], answered.stderr
    # Podstawa i mutacja na HEAD; podstawa i mutacja na merge-base dałyby to samo.
    assert runs.read_text(encoding="utf-8") == ".."


def test_test_ktory_pada_na_tekscie_linii_pytest_timeout_daje_wykryta(tmp_path: Path) -> None:
    """Asercja drukuje tekst linii pytest-timeout w cudzysłowie, a to nie jest zawieszenie."""

    repo = repository(
        tmp_path / "repo",
        {PACKAGE: "TEKST = ''\n", "tests/test_tekst.py": "import rozliczenia\n\n\ndef test_tekst():\n    assert rozliczenia.TEKST == ''\n"},
    )
    commit(repo, "baza")
    printed = "TEKST = 'Failed: Timeout (>1.0s) from pytest-timeout.'"

    answered = _in_repository(repo, "--zmiana", PACKAGE, "TEKST = ''", printed, "--", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_tekst.py")

    assert answered.stdout.splitlines()[0].startswith("WYKRYTA: mutacja → 1 failed"), answered.stdout + answered.stderr


STRICT = "import pathlib, rozliczenia; raise SystemExit(rozliczenia.WARTOSC if pathlib.Path('scisle').exists() else 0)"


@pytest.mark.parametrize(
    ("base", "head", "uncommitted", "line"),
    [
        ({"scisle": ""}, {}, False, "REGRES: mutacja → kod wyjścia 0 (WYKRYTA na merge-base {base}: kod wyjścia 1)"),
        ({"scisle": ""}, {"scisle": ""}, True, "REGRES: mutacja → kod wyjścia 0 (WYKRYTA na merge-base {base}: kod wyjścia 1)"),
        ({}, {}, False, "NIEWYKRYTA: mutacja → kod wyjścia 0"),
        ({"scisle": "", PACKAGE: "WARTOSC = 2\n"}, {PACKAGE: "WARTOSC = 0\n"}, False, "NIEWYKRYTA: mutacja → kod wyjścia 0 (na merge-base {base} podstawa czerwona: kod wyjścia 2)"),
        ({"scisle": "", PACKAGE: "WARTOSC = 0 \n"}, {PACKAGE: "WARTOSC = 0\n"}, False, "NIEWYKRYTA: mutacja → kod wyjścia 0 (na merge-base {base} NIEAKTUALNA: kotwicy nie ma dokładnie raz w src/rozliczenia/__init__.py: 'WARTOSC = 0')"),
    ],
    ids=["test-oslabiony-w-commicie", "test-oslabiony-w-checkoucie", "test-bez-zmiany", "podstawa-merge-base-czerwona", "merge-base-bez-kotwicy"],
)
def test_mutacja_niewykryta_na_head_a_wykryta_na_merge_base_daje_regres(
    tmp_path: Path, base: dict[str, str], head: dict[str, str], uncommitted: bool, line: str
) -> None:
    """Zmiana, która osłabia test, daje REGRES; mutacja, której merge-base nie rozstrzyga, zostaje NIEWYKRYTA z jego wynikiem."""

    repo = repository(tmp_path / "repo", {PACKAGE: "WARTOSC = 0\n", **base})
    forked = commit(repo, "baza")
    git(repo, "branch", "glowna")
    for name in base.keys() - head.keys():
        (repo / name).unlink()
    for name, text in head.items():
        (repo / name).write_text(text, encoding="utf-8")
    if base != head:
        commit(repo, "zmiana")
    if uncommitted:
        (repo / "scisle").unlink()

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, "WARTOSC = 0\n", "WARTOSC = 1\n", "--", "-c", STRICT)

    expected = line.format(base=forked[:8])
    assert (answered.returncode, answered.stdout.splitlines()) == (1, [expected, "MUTACJE: 1 bez oczekiwanego wyniku"]), answered.stderr


OLD_TEST = "def test_stary():\n    pass\n"
NOWY_TEST_NA_BAZIE = "polecenie bez testu, więc test jest nowy i REGRES nie dotyczy"
KOD_4_NA_BAZIE = "pytest nie uruchomił testu (kod 4: test albo plik nowy, zła ścieżka albo opcja, albo zepsuty conftest.py), więc REGRES nie dotyczy"
NEW_TEST = "import rozliczenia\n\n\ndef test_nowy():\n    assert rozliczenia.WARTOSC < 5\n"


@pytest.mark.parametrize(
    ("base", "selected", "there", "why"),
    [
        ({}, (), r"no tests ran", KOD_4_NA_BAZIE),
        ({"tests/test_n.py": OLD_TEST}, ("-k", "test_nowy"), r"1 deselected", NOWY_TEST_NA_BAZIE),
        ({"tests/test_n.py": OLD_TEST}, ("::test_nowy",), r"no tests ran", KOD_4_NA_BAZIE),
    ],
    ids=["nowy-plik-testow", "nowy-test-w-pliku", "nowy-test-przez-node-id"],
)
def test_niewykryta_z_testem_ktorego_nie_ma_na_merge_base_mowi_ze_regres_nie_dotyczy(
    tmp_path: Path, base: dict[str, str], selected: tuple[str, ...], there: str, why: str
) -> None:
    """Nowy test, którego mutacja przeżyła: na merge-base pytest nie ma czego uruchomić, a to nie czerwona podstawa."""

    repo = repository(tmp_path / "repo", {PACKAGE: "WARTOSC = 0\n", ".gitignore": "__pycache__/\n", **base})
    forked = commit(repo, "baza")
    git(repo, "branch", "glowna")
    (repo / "tests" / "test_n.py").parent.mkdir(exist_ok=True)
    (repo / "tests" / "test_n.py").write_text(f"{base.get('tests/test_n.py', '')}\n\n{NEW_TEST}", encoding="utf-8")
    commit(repo, "nowy test")
    node = ("tests/test_n.py" + selected[0],) if selected[:1] == ("::test_nowy",) else ("tests/test_n.py", *selected)
    pytest_command = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", *node)

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", *pytest_command)

    note = rf"\(na merge-base {forked[:8]} {re.escape(why)}: {there} in [0-9.]+s\)"
    assert re.fullmatch(rf"NIEWYKRYTA: mutacja → 1 passed[^(]* in [0-9.]+s {note}", answered.stdout.splitlines()[0]), answered.stdout + answered.stderr


LOOSE_OLD_TEST = "import rozliczenia\n\n\ndef test_stary():\n    assert rozliczenia.WARTOSC < 5\n"
ASSERTING_NEW_TEST = "import rozliczenia\n\n\ndef test_nowy():\n    assert {condition}\n"
STRICT_NEW_TEST = ASSERTING_NEW_TEST.format(condition="rozliczenia.WARTOSC == {value}")
# Drugi test pada po mutacji tylko za pierwszym w tym samym procesie.
NEIGHBOURS_TEST = (
    "import rozliczenia\n\n\ndef test_sasiad():\n    rozliczenia.SLAD = rozliczenia.WARTOSC\n\n\n"
    "def test_po_sasiedzie():\n    assert getattr(rozliczenia, 'SLAD', 0) < 5\n"
)
OTHER_TEST = "\n\ndef test_inny():\n    assert True\n"
CAUGHT_BY_OLD = (
    "JUŻ ŁAPIE tests/test_stary.py::test_stary: ten test sprzed zmiany sam łapie mutację „{name}” (pada z nią, bez niej "
    "przechodzi), więc sprawdź, czy nowy test dodaje coś ponad niego; asercję możesz dopisać tam"
)
TWO_MUTATIONS = [{"nazwa": name, "zmiany": [[PACKAGE, "WARTOSC = 0", f"WARTOSC = {value}"]]} for name, value in (("m1-ujemna", -1), ("m2-duza", 7))]


def _branch_with_new_test(path: Path, old_at_base: str, old_in_branch: str, new: str, value: int = 0, files: dict[str, str] | None = None) -> tuple[Path, str]:
    """Repozytorium, którego gałąź dopisuje ``new`` jako ``tests/test_n.py`` nad ``glowna`` z ``tests/test_stary.py``,
    i skrót merge-base; świeże czasy CI bez pomiarów, chyba że test dopisze własne."""

    repo = repository(path / "repo", {PACKAGE: "WARTOSC = 0\n", ".gitignore": "__pycache__/\n", "tests/test_stary.py": old_at_base, **(files or {})})
    forked = commit(repo, "baza")
    git(repo, "branch", "glowna")
    (repo / PACKAGE).write_text(f"WARTOSC = {value}\n", encoding="utf-8")
    (repo / "tests" / "test_stary.py").write_text(old_in_branch, encoding="utf-8")
    (repo / "tests" / "test_n.py").write_text(new, encoding="utf-8")
    commit(repo, "nowy test")
    # Bez pomiaru każdy plik waży 0, więc szybko.plan bierze każdy, a narzędzie nie pobiera czasów z GitHuba.
    (repo / ".git" / "czasy-ci").mkdir(exist_ok=True)
    (repo / ".git" / "czasy-ci" / "pobrane").touch()
    return repo, forked[:8]


def _two_mutations(repo: Path, tmp_path: Path, selected: str, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Narzędzie w ``repo`` z „m1-ujemna” (0 → -1) i „m2-duza” (0 → 7) na poleceniu pytest z ``selected``."""

    plan = tmp_path / "mutacje.json"
    plan.write_text(json.dumps(TWO_MUTATIONS), encoding="utf-8")
    return _in_repository(repo, "--baza", "glowna", *arguments, "--plik", str(plan), "--", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", selected, env=env or ONE_WORKER)


def _already_lines(answered: subprocess.CompletedProcess[str], mutations: list[str]) -> list[str]:
    """Linie ``JUŻ ŁAPIE`` ze stderr przebiegu, w którym każda z ``mutations`` jest WYKRYTA, a stdout i kod są jak bez
    sprawdzenia; żadna linia nie radzi usunąć testu, bo tego, czy nowy test dodaje coś ponad stary, narzędzie nie wie."""

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert answered.stdout.splitlines()[-1] == "MUTACJE OK", answered.stdout
    assert [line.split(" → ")[0] for line in answered.stdout.splitlines()[:-1]] == [f"WYKRYTA: {name}" for name in mutations], answered.stdout
    assert "usuń" not in answered.stderr.lower(), answered.stderr
    return [found for found in answered.stderr.splitlines() if found.startswith("JUŻ ŁAPIE")]


@pytest.mark.parametrize(
    ("value", "old_at_base", "old_in_branch", "mutated", "selected", "lines"),  # lines: wzorce re z {base}, skrótem merge-base
    [
        (0, LOOSE_OLD_TEST, LOOSE_OLD_TEST, 7, "tests/test_n.py", [re.escape(CAUGHT_BY_OLD.format(name="mutacja"))]),
        (0, LOOSE_OLD_TEST, LOOSE_OLD_TEST, 1, "tests/test_n.py", []),
        (0, LOOSE_OLD_TEST, LOOSE_OLD_TEST.replace("< 5", "< 6"), 7, "tests/test_n.py", []),
        (0, LOOSE_OLD_TEST, LOOSE_OLD_TEST, 7, "tests/test_stary.py", ["JUŻ ŁAPIE NIESPRAWDZONE: mutacja: polecenie nie wybiera testu dodanego ani zmienionego od merge-base {base}"]),
        (0, LOOSE_OLD_TEST, LOOSE_OLD_TEST + OTHER_TEST, 7, "tests/test_stary.py::test_stary", ["JUŻ ŁAPIE NIESPRAWDZONE: mutacja: polecenie nie wybiera testu dodanego ani zmienionego od merge-base {base}"]),
        (0, NEIGHBOURS_TEST, NEIGHBOURS_TEST, 7, "tests/test_n.py", [r"JUŻ ŁAPIE NIESPRAWDZONE: mutacja: tests/test_stary.py::test_po_sasiedzie sam daje z mutacją NIEWYKRYTA \(1 passed in [0-9.]+s\), bez niej NIEWYKRYTA \(1 passed in [0-9.]+s\), więc niczego nie dowodzi"]),
    ],
    ids=["stary-test-lapie", "lapie-tylko-nowy", "stary-test-zmieniony-w-galezi", "polecenie-bez-nowego-testu", "polecenie-ze-starym-testem-zmienionego-pliku", "stary-test-pada-tylko-za-sasiadem"],
)
def test_wykryta_mutacja_ktora_lapie_test_sprzed_zmiany_dostaje_juz_lapie_a_werdykt_i_kod_zostaja(
    tmp_path: Path, value: int, old_at_base: str, old_in_branch: str, mutated: int, selected: str, lines: list[str]
) -> None:
    """Gałąź dopisuje ścisły test, a test sprzed niej łapie mutację albo nie (T2: repro recenzenta na drugiej warstwie).

    Linia na stderr nie zmienia stdout ani kodu wyjścia. Test zmieniony w gałęzi niczego nie dowodzi, tak samo test,
    który po mutacji pada tylko za sąsiadem. Test sprzed zmiany w pliku, do którego gałąź dopisała inny test, nie jest
    nowym testem polecenia.
    """

    repo, base = _branch_with_new_test(tmp_path, old_at_base, old_in_branch, STRICT_NEW_TEST.format(value=value), value)
    command = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", selected)

    answered = _in_repository(repo, "--baza", "glowna", "--zmiana", PACKAGE, f"WARTOSC = {value}", f"WARTOSC = {mutated}", "--", *command, env=ONE_WORKER)

    found = _already_lines(answered, ["mutacja"])
    expected = [line.format(base=base) for line in lines]
    assert len(found) == len(expected) and all(map(re.fullmatch, expected, found)), answered.stderr


# Pakiet merge-base ma ``NAZWA``, a gałąź ją usuwa, więc test sprzed zmiany, który jej używa, jest czerwony bez mutacji.
WITH_NAME = {PACKAGE: "WARTOSC = 0\nNAZWA = 'x'\n"}
RED_OLD_TESTS = {
    "porazka": "import rozliczenia\n\n\ndef test_stary():\n    assert rozliczenia.WARTOSC < 5 and rozliczenia.NAZWA\n",
    "blad-przygotowania": (
        "import pytest, rozliczenia\n\n\n@pytest.fixture\ndef nazwa():\n    return rozliczenia.NAZWA\n\n\n"
        "def test_stary(nazwa):\n    assert rozliczenia.WARTOSC < 5\n"
    ),
    "blad-kolekcji": "import rozliczenia\nfrom rozliczenia import NAZWA\n\n\ndef test_stary():\n    assert rozliczenia.WARTOSC < 5\n",
    **{
        name: (
            f"import time, pytest, rozliczenia\n\n\n@pytest.mark.timeout(2{method})\ndef test_stary():\n"
            "    if not hasattr(rozliczenia, 'NAZWA'):\n        time.sleep(30)\n    assert rozliczenia.WARTOSC < 5\n"
        )
        # Metoda domyślna systemu (signal na Macu i Linuksie, thread na Windows) i thread wprost, jak na Windows.
        for name, method in (("zawieszenie", ""), ("zawieszenie-thread", ", method='thread'"))
    },
}
# Test sprzed zmiany pada bez mutacji tylko za sąsiadem w swoim pliku, a ``conftest.py`` podkatalogu nie da się
# zaimportować (sondy przeglądu #1726 r1, W1).
NEIGHBOUR_RED = (
    "import rozliczenia\n\n\ndef test_sasiad():\n    rozliczenia.SLAD = getattr(rozliczenia, 'NAZWA', None)\n\n\n"
    "def test_po_sasiedzie():\n    assert rozliczenia.WARTOSC < 5 and getattr(rozliczenia, 'SLAD', 'x') is not None\n"
)
GREEN_OLD = "import rozliczenia\n\n\ndef test_stary():\n    assert rozliczenia.WARTOSC < 100\n"
SUB_CONFTEST = {
    "tests/sub/__init__.py": "",
    "tests/sub/conftest.py": "from rozliczenia import NAZWA\n",
    "tests/sub/test_c.py": "import rozliczenia\n\n\ndef test_c():\n    assert rozliczenia.WARTOSC < 100\n",
}
# Test sprzed zmiany, który naprawdę łapie mutację, a stoi przed czerwonym, więc ``-x`` JUŻ ŁAPIE kończy się na nim.
CATCHES_OLD = {"tests/test_a.py": "import rozliczenia\n\n\ndef test_lapie():\n    assert rozliczenia.WARTOSC < 5\n"}
BASE_RED = "MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi"


@pytest.mark.parametrize(
    ("old", "files", "shown"),
    [
        *((old, {}, "tests/test_stary.py") for old in RED_OLD_TESTS.values()),
        (NEIGHBOUR_RED, {}, "tests/test_stary.py::test_po_sasiedzie"),
        (GREEN_OLD, SUB_CONFTEST, "tests/sub/conftest.py"),
        (RED_OLD_TESTS["porazka"], CATCHES_OLD, "tests/test_stary.py::test_stary"),
    ],
    ids=[*RED_OLD_TESTS, "sasiad-w-pliku", "conftest-podkatalogu", "za-testem-ktory-lapie"],
)
def test_test_sprzed_zmiany_czerwony_bez_mutacji_daje_odmowe_zamiast_mutacje_ok(tmp_path: Path, old: str, files: dict[str, str], shown: str) -> None:
    """Jak #1719: zmiana psuje test sprzed niej z wyboru szybko, który CI uruchomi, a polecenie przechodzi. Wybór biegnie
    raz bez mutacji w podstawie silnika, jak polecenie, więc każda postać czerwieni (porażka, błąd przygotowania albo
    kolekcji, zawieszenie metodą domyślną i ``thread`` z Windows, porażka za sąsiadem, ``conftest.py`` podkatalogu, test
    za tym, który łapie mutację) daje ``PODSTAWA CZERWONA`` i odmowę przed mutacjami, a stderr pokazuje, co padło."""

    repo, _ = _branch_with_new_test(tmp_path, old, old, STRICT_NEW_TEST.format(value=0), files=WITH_NAME | files)

    answered = _two_mutations(repo, tmp_path, "tests/test_n.py")

    listed = repo / ".git" / "mutacje-testy-sprzed-zmiany.txt"
    red = rf"PODSTAWA CZERWONA: -m pytest -q -x -n 1 -p no:cacheprovider @{re.escape(str(listed.resolve()))} → .+"
    lines = answered.stdout.splitlines()
    # Między nimi tylko ``PODSTAWA BEZ TESTU`` przy kodzie 4 pytest (``conftest.py``, którego nie da się zaimportować).
    assert (answered.returncode, lines[-1], [line for line in lines[1:-1] if not line.startswith("PODSTAWA BEZ TESTU: ")]) == (2, BASE_RED, []), answered.stdout
    assert (bool(re.fullmatch(red, lines[0])), shown in answered.stderr) == (True, True), answered.stdout + answered.stderr


def test_podstawa_testow_sprzed_zmiany_bez_wyniku_w_limicie_daje_odmowe_zamiast_mutacje_ok(tmp_path: Path) -> None:
    """Test sprzed zmiany, zielony, ale dłuższy niż ``--podstawa-s``: bez wyniku podstawy ``MUTACJE OK`` nie mówiłoby,
    że wybór przechodzi, więc narzędzie mówi ``PODSTAWA NIESPRAWDZONA`` i kończy się kodem 2."""

    slow = "import time, rozliczenia\n\n\ndef test_stary():\n    time.sleep(30)\n    assert rozliczenia.WARTOSC < 100\n"
    repo, _ = _branch_with_new_test(tmp_path, slow, slow, STRICT_NEW_TEST.format(value=0))

    answered = _two_mutations(repo, tmp_path, "tests/test_n.py", "--podstawa-s", "3")

    lines = answered.stdout.splitlines()
    unchecked = "MUTACJE: podstawa bez wyniku w swoim limicie, więc MUTACJE OK byłoby niesprawdzone; podnieś jej limit albo uruchom ją sam"
    assert (answered.returncode, lines[-1], len(lines)) == (2, unchecked, 2), answered.stdout + answered.stderr
    assert re.fullmatch(r"PODSTAWA NIESPRAWDZONA: -m pytest -q -x -n 1 -p no:cacheprovider @.+ → brak wyniku po 3 s", lines[0]), answered.stdout


# Znane luki odmowy: test sprzed zmiany czerwony bez mutacji, a narzędzie i tak kończy się ``MUTACJE OK``, bo wybór szybko
# go nie ma albo podstawa wyboru nie biegnie. Klucz to „klasa: postać”, wartość to polecenie, argumenty narzędzia i
# pliki merge-base; gdy narzędzie zacznie tu odmawiać, przenieś próbkę do testu odmowy wyżej.
FAR_RED = {
    "src/posrednik.py": "from rozliczenia import WARTOSC, NAZWA\n",
    "tests/test_daleki.py": "import posrednik\n\n\ndef test_daleki():\n    assert posrednik.NAZWA\n",
}
ZNANE_LUKI = {
    "podstawa wyboru nie biegnie: polecenie nie wybiera testu dodanego ani zmienionego": ("tests/test_a.py", (), CATCHES_OLD),
    "podstawa wyboru nie biegnie: limit --juz-lapie-s minął przed planem": ("tests/test_n.py", ("--juz-lapie-s", "0"), {}),
    "wybór szybko bez pliku: czasy CI odkładają plik ponad budżet": ("tests/test_n.py", (), FAR_RED),
}


@pytest.mark.parametrize(("selected", "arguments", "files"), list(ZNANE_LUKI.values()), ids=list(ZNANE_LUKI))
def test_znane_luki_odmowy_na_czerwonym_tescie_sprzed_zmiany_koncza_sie_mutacje_ok(
    tmp_path: Path, selected: str, arguments: tuple[str, ...], files: dict[str, str]
) -> None:
    old = GREEN_OLD if "tests/test_daleki.py" in files else RED_OLD_TESTS["porazka"]
    repo, _ = _branch_with_new_test(tmp_path, old, old, STRICT_NEW_TEST.format(value=0), files=WITH_NAME | files)
    seconds = {"tests/test_stary.py": 0.1, "tests/test_n.py": 0.1, "tests/test_daleki.py": 10_000.0}
    lane = {f"pytest:{path}": [{"run": 1, "proba": 1, "zadanie": "z", "s": s, "status": "ok", "testy": 1}] for path, s in seconds.items()}
    (repo / ".git" / "czasy-ci" / "1.json").write_text(json.dumps({"runy": [{"run": 1}], "tory": {"linux-3.14": lane}}), encoding="utf-8")

    answered = _in_repository(
        repo, "--baza", "glowna", *arguments, "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 7", "--", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", selected, env=ONE_WORKER
    )

    assert (answered.returncode, answered.stdout.splitlines()[-1]) == (0, "MUTACJE OK"), answered.stdout + answered.stderr


# Kolekcja (``--collect-only``) dłuższa niż limit sprawdzenia w teście, a przebiegi testów bez czekania.
SLOW_COLLECTION = {"tests/conftest.py": "import sys, time\n\nif '--collect-only' in sys.argv:\n    time.sleep(20)\n"}
SETS_TRACE = {"tests/test_a.py": "import rozliczenia\n\n\ndef test_ustawia():\n    rozliczenia.SLAD = rozliczenia.WARTOSC\n"}


@pytest.mark.parametrize(
    ("new", "arguments", "files", "lines"),
    [
        (ASSERTING_NEW_TEST.format(condition="rozliczenia.WARTOSC >= 0"), (), {}, [CAUGHT_BY_OLD.format(name="m2-duza")]),
        (ASSERTING_NEW_TEST.format(condition="getattr(rozliczenia, 'SLAD', 0) >= 0 and rozliczenia.WARTOSC < 5"), (), SETS_TRACE, [CAUGHT_BY_OLD.format(name="m2-duza")]),
        (ASSERTING_NEW_TEST.format(condition="0 <= rozliczenia.WARTOSC < 5"), ("--juz-lapie-s", "0"), {}, [f"JUŻ ŁAPIE NIESPRAWDZONE: {name}: minął limit sprawdzenia 0 s" for name in ("m1-ujemna", "m2-duza")]),
        (
            ASSERTING_NEW_TEST.format(condition="0 <= rozliczenia.WARTOSC < 5"),
            ("--juz-lapie-s", "5"),
            SLOW_COLLECTION,
            ["JUŻ ŁAPIE NIESPRAWDZONE: m1-ujemna: kolekcja testów polecenia nie skończyła się w limicie", "JUŻ ŁAPIE NIESPRAWDZONE: m2-duza: minął limit sprawdzenia 5 s"],
        ),
    ],
    ids=["nowy-test-nie-lapie-mutacji-starego", "nowy-test-lapie-tylko-za-sasiadem", "limit-calego-sprawdzenia", "kolekcja-w-limicie-sprawdzenia"],
)
def test_juz_lapie_mowi_tylko_o_mutacji_ktora_sam_lapie_test_sprzed_zmiany(
    tmp_path: Path, new: str, arguments: tuple[str, ...], files: dict[str, str], lines: list[str]
) -> None:
    """Polecenie z całym katalogiem testów i dwie mutacje: „m1-ujemna” w poleceniu łapie tylko nowy test (sam albo za
    testem sprzed zmiany, który ustawia mu stan), a „m2-duza” także test sprzed zmiany `WARTOSC < 5` (przegląd #1493 r1
    i r2).

    Linię faktu dostaje tylko „m2-duza”, a żadna linia nie radzi usunąć nowego testu, który jako jedyny łapie
    „m1-ujemna”. Limit obejmuje całe sprawdzenie, z kolekcją.
    """

    repo, _ = _branch_with_new_test(tmp_path, LOOSE_OLD_TEST, LOOSE_OLD_TEST, new, files=files)

    answered = _two_mutations(repo, tmp_path, "tests", *arguments)

    assert _already_lines(answered, ["m1-ujemna", "m2-duza"]) == lines, answered.stderr


def test_juz_lapie_milczy_gdy_mutacja_nie_padla_w_poleceniu(tmp_path: Path) -> None:
    """„m2-duza” przeżywa nowy test, choć łapie ją test sprzed zmiany: linia o mutacji, która w poleceniu nie padła, nie
    ma czego dotyczyć, więc przy kodzie 1 sprawdzenie nie biegnie, a werdykty zostają."""

    repo, _ = _branch_with_new_test(tmp_path, LOOSE_OLD_TEST, LOOSE_OLD_TEST, ASSERTING_NEW_TEST.format(condition="rozliczenia.WARTOSC >= 0"))

    answered = _two_mutations(repo, tmp_path, "tests/test_n.py")

    assert answered.returncode == 1, answered.stdout + answered.stderr
    assert [line.split(" → ")[0] for line in answered.stdout.splitlines()] == ["WYKRYTA: m1-ujemna", "NIEWYKRYTA: m2-duza", "MUTACJE: 1 bez oczekiwanego wyniku"], answered.stdout
    assert "JUŻ ŁAPIE" not in answered.stderr, answered.stderr


def test_juz_lapie_w_czesci_mutacji_nie_mowi_o_mutacjach_spoza_niej(tmp_path: Path) -> None:
    """Z ``MUTACJE_CZESC`` polecenie biegło tylko z mutacjami części, więc fakt o mutacji spoza niej (tu „m2-duza”, którą
    łapie test sprzed zmiany) byłby o mutacji, która w poleceniu nie padła."""

    repo, _ = _branch_with_new_test(tmp_path, LOOSE_OLD_TEST, LOOSE_OLD_TEST, ASSERTING_NEW_TEST.format(condition="0 <= rozliczenia.WARTOSC < 5"))

    answered = _two_mutations(repo, tmp_path, "tests", env=ONE_WORKER | {"MUTACJE_CZESC": "1/2"})

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert [line.split(" → ")[0] for line in answered.stdout.splitlines()] == ["MUTACJE CZĘŚĆ 1/2: 1 z 2 mutacji", "WYKRYTA: m1-ujemna", "MUTACJE OK"], answered.stdout
    assert [line for line in answered.stderr.splitlines() if line.startswith("JUŻ ŁAPIE")] == [
        "JUŻ ŁAPIE NIESPRAWDZONE: MUTACJE_CZESC=1/2: część mówi, że padły tylko jej mutacje, a sprawdzenie nie wie które"
    ], answered.stderr


def test_juz_lapie_mowi_o_plikach_testow_sprzed_zmiany_odlozonych_przez_szybko(tmp_path: Path) -> None:
    """„m1-ujemna” łapie tylko test sprzed zmiany, który stoi dalej od mutacji, a czasy CI ważą go ponad budżet szybko,
    więc nie biegnie, a „m2-duza” łapie test obok: brak linii o „m1-ujemna” nie może wyglądać na zachowanie naprawdę
    nowe (przegląd #1493 r1). Plik samych nowych testów szybko też odkłada, ale to nie plik testów sprzed zmiany, więc
    liczba odłożonych go nie liczy (przegląd #1493 r2)."""

    far = {
        "src/posrednik.py": "from rozliczenia import WARTOSC\n",
        "tests/test_daleki.py": "import posrednik\n\n\ndef test_daleki():\n    assert posrednik.WARTOSC >= 0\n",
    }
    seconds = {"tests/test_stary.py": 0.1, "tests/test_n.py": 10_000.0, "tests/test_daleki.py": 10_000.0}
    lane = {f"pytest:{path}": [{"run": 1, "proba": 1, "zadanie": "z", "s": s, "status": "ok", "testy": 1}] for path, s in seconds.items()}
    repo, _ = _branch_with_new_test(tmp_path, LOOSE_OLD_TEST, LOOSE_OLD_TEST, STRICT_NEW_TEST.format(value=0), files=far)
    (repo / ".git" / "czasy-ci" / "1.json").write_text(json.dumps({"runy": [{"run": 1}], "tory": {"linux-3.14": lane}}), encoding="utf-8")

    answered = _two_mutations(repo, tmp_path, "tests/test_n.py")

    assert _already_lines(answered, ["m1-ujemna", "m2-duza"]) == [
        "JUŻ ŁAPIE NIESPRAWDZONE: m1-ujemna: pliki testów sprzed zmiany odłożone przez szybko ponad budżet nie biegły (odłożone: 1)",
        CAUGHT_BY_OLD.format(name="m2-duza"),
    ], answered.stderr


def test_mutacja_z_oczekiwana_linia_nie_dostaje_juz_lapie(tmp_path: Path) -> None:
    """Mutację z ``oczekiwane`` wykrywa linia wyjścia, nie porażka testu, więc sprawdzenie testami sprzed zmiany jej nie
    dotyczy, choć ten sam test sprzed zmiany ją łapie."""

    repo, _ = _branch_with_new_test(tmp_path, LOOSE_OLD_TEST, LOOSE_OLD_TEST, STRICT_NEW_TEST.format(value=0))
    plan = tmp_path / "mutacje.json"
    plan.write_text(json.dumps([{"nazwa": "z linia", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 7"]], "oczekiwane": "1 failed"}]), encoding="utf-8")

    answered = _in_repository(repo, "--baza", "glowna", "--plik", str(plan), "--", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_n.py", env=ONE_WORKER)

    assert _already_lines(answered, ["z linia"]) == [], answered.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT do jednego procesu jest sygnałem POSIX")
def test_przerwane_narzedzie_konczy_trwajace_mutacje_i_sprzata(tmp_path: Path) -> None:
    repo, mutation, started, beats = _hanging_repository(tmp_path)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    tool = subprocess.Popen(
        [sys.executable, str(repo / "tools" / "mutacje.py"), *mutation],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for(started.exists, 60, every=0.1)

    tool.send_signal(signal.SIGINT)
    tool.wait(timeout=20)
    wait_for(lambda: not any(scratch.iterdir()), 20, every=0.1)

    assert (started.exists(), beating(beats)) == (True, False)
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert list(scratch.iterdir()) == []


# Środowisko wywołującego bez wartości ``-n auto``, którą ustawia ``tools/szybko.py``.
WITHOUT_XDIST_WORKERS = {name: value for name, value in os.environ.items() if name != "PYTEST_XDIST_AUTO_NUM_WORKERS"}
ONE_WORKER = {**WITHOUT_XDIST_WORKERS, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1"}


def _small_repository(path: Path) -> Path:
    repo = repository(path / "repo", {"src/rozliczenia/__init__.py": "WARTOSC = 0\n"})
    commit(repo, "baza")
    return repo


def _plan(path: Path, count: int) -> Path:
    plan = path / "mutacje.json"
    entries = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]]} for number in range(1, count + 1)]
    plan.write_text(json.dumps(entries), encoding="utf-8")
    return plan


def _in_repository(
    repo: Path, *arguments: str, env: dict[str, str] = WITHOUT_XDIST_WORKERS, merged: bool = False
) -> subprocess.CompletedProcess[str]:
    """Narzędzie z ``tools/`` repozytorium testu; z ``merged`` stderr trafia do stdout, jak w logu CI."""

    return subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), *arguments],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merged else subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    ("arguments", "caller", "seen"),
    [(("--rownolegle",), {}, "1"), (("--rownolegle",), {"PYTEST_XDIST_AUTO_NUM_WORKERS": "3"}, "3"), ((), {}, "brak")],
    ids=["naraz", "naraz-z-wartoscia-wywolujacego", "po-kolei"],
)
def test_mutacje_naraz_daja_zagniezdzonemu_pytest_n_auto_jednego_workera(
    tmp_path: Path, arguments: tuple[str, ...], caller: dict[str, str], seen: str
) -> None:
    """26.10 test każdej z 20 mutacji naraz uruchomił ``pytest -n auto`` z 16 workerami: load 229 na 16 rdzeniach."""

    workers = (
        "import os, rozliczenia; print('workery', os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS', 'brak')); "
        "raise SystemExit(rozliczenia.WARTOSC)"
    )

    answered = _in_repository(
        _small_repository(tmp_path), *arguments, "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", "-c", workers, env=WITHOUT_XDIST_WORKERS | caller
    )

    assert answered.stdout.splitlines() == [f"WYKRYTA: mutacja → workery {seen}", "MUTACJE OK"], answered.stderr


def test_skrypt_mutacji_skilla_daje_zagniezdzonemu_pytest_n_auto_jednego_workera(tmp_path: Path) -> None:
    """``check_all`` skryptu mutacji skilla puszcza mutacje naraz, więc ich polecenia dostają jednego workera xdist."""

    workers = "import os, rozliczenia; print('workery', os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS', 'brak')); raise SystemExit(rozliczenia.WARTOSC)"
    script = (
        "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nfrom silnik_mutacji import Edit, Mutation, check_all\n"
        f"mutation = Mutation('m', (Edit(Path({PACKAGE!r}), 'WARTOSC = 0', 'WARTOSC = 1'),), ('-c', {workers!r}))\n"
        "raise SystemExit(check_all([mutation]))\n"
    )

    answered = subprocess.run(
        [sys.executable, "-c", script], cwd=_small_repository(tmp_path), env=WITHOUT_XDIST_WORKERS, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: m → workery 1", "MUTACJE OK"], answered.stderr


# Narzędzie na komputerze z ``cores`` rdzeniami: ``os.cpu_count`` podmieniony przed jego startem.
# Jak ``python tools/mutacje.py``: katalog skryptu na początku ``sys.path`` (runpy.run_path go nie dopisuje).
ON_CORES = (
    "import os, runpy, sys; _, cores, *sys.argv = sys.argv; os.cpu_count = lambda: int(cores); "
    "sys.path.insert(0, os.path.dirname(sys.argv[0])); runpy.run_path(sys.argv[0], run_name='__main__')"
)


@pytest.mark.parametrize(("cores", "at_once"), [(3, 3), (16, 8)], ids=["runner-ci-mniej-rdzeni-niz-8", "mac-wiecej-rdzeni-niz-8"])
def test_naraz_biegnie_najwyzej_tyle_mutacji_ile_rdzeni_i_najwyzej_osiem(tmp_path: Path, cores: int, at_once: int) -> None:
    """Każda mutacja czeka, aż wystartuje ``at_once``, i podaje, ile biegnie naraz; następna startuje dopiero po końcu
    innej. Osiem eksploratorów naraz na 4 vCPU runnera CI dzieliło procesor, a czas mutacji rósł do limitu (#968)."""

    started, running = tmp_path / "wystartowaly", tmp_path / "biegna"
    started.mkdir()
    running.mkdir()
    counts = (
        "import pathlib, time, uuid, rozliczenia\n"
        "if rozliczenia.WARTOSC:\n"
        f"    started, running, me = pathlib.Path({str(started)!r}), pathlib.Path({str(running)!r}), uuid.uuid4().hex\n"
        "    (started / me).touch()\n"
        "    (running / me).touch()\n"
        "    deadline = time.monotonic() + 20\n"
        f"    while len(list(started.iterdir())) < {at_once} and time.monotonic() < deadline:\n"
        "        time.sleep(0.05)\n"
        "    time.sleep(0.5)\n"
        "    print('naraz', len(list(running.iterdir())))\n"
        "    (running / me).unlink()\n"
        "    raise SystemExit(1)\n"
    )

    repo = _small_repository(tmp_path)
    answered = subprocess.run(
        [sys.executable, "-c", ON_CORES, str(cores), str(repo / "tools" / "mutacje.py"), "--rownolegle", "--plik", str(_plan(tmp_path, at_once + 1)), "--", "-c", counts],
        cwd=repo,
        env=WITHOUT_XDIST_WORKERS,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    seen = [int(line.rsplit(" ", 1)[1]) for line in answered.stdout.splitlines() if line.startswith("WYKRYTA: m")]
    assert (len(seen), max(seen, default=0)) == (at_once + 1, at_once), answered.stdout + answered.stderr



WISI_TEST = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_wisi.py")
# Z flagą ``WOLNO`` czeka na zdarzenie, które nie nadejdzie, a bez niej kończy się zaraz po starcie Pythona: przed
# limitem, który ma minąć, stoi tylko start interpretera, a nie start pytest.
WAITS = ("-c", "import threading, rozliczenia\nif rozliczenia.WOLNO:\n    threading.Event().wait()\n")


def _skill_check(
    tmp_path: Path, anchor: str, replacement: str, *, hang_s: int, limit_s: int, command: tuple[str, ...] = WISI_TEST
) -> subprocess.CompletedProcess[str]:
    """``check_all`` skryptu mutacji skilla z atrapą bramy (``FAKE_GATE``) i jedną mutacją pakietu z poleceniem
    ``command``: ``WISI_TEST`` to pytest z testem ``test_wisi`` (z flagą ``WISI`` śpi do pytest-timeout po ``hang_s``
    s), a ``WAITS`` z flagą ``WOLNO`` czeka bez końca."""

    tests = f"import time\n\nimport pytest\nimport rozliczenia\n\n\n@pytest.mark.timeout({hang_s})\ndef test_wisi():\n    if rozliczenia.WISI:\n        time.sleep(60)\n"
    repo = repository(tmp_path / "repo", {PACKAGE: "WISI = False\nWOLNO = False\nNIC = 0\n", "tests/test_wisi.py": tests})
    commit(repo, "baza")
    script = (
        "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nimport silnik_mutacji\nfrom silnik_mutacji import Edit, Mutation, check_all\n"
        f"{FAKE_GATE}\nmutation = Mutation('m', (Edit(Path({PACKAGE!r}), {anchor!r}, {replacement!r}),), {command!r})\n"
        f"raise SystemExit(check_all([mutation], limit_s={limit_s}, gate=brama))\n"
    )
    # Krócej niż pytest-timeout (120 s): silnik, który nie kończy ``WAITS`` po limicie, pada tu, a nie wisi.
    return subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


@pytest.mark.parametrize(
    ("anchor", "replacement", "code", "lines"),
    [
        pytest.param("WISI = False", "WISI = True", 0, [r"ZAWIESZENIE: m → .*Timeout.* \(liczona jako wykryta: pytest-timeout czerwieni test w CI\)", "MUTACJE OK"]),
        pytest.param(
            "WOLNO = False",
            "WOLNO = True",
            1,
            [re.escape("PRZEKROCZONY CZAS: m → brak wyniku po 2 s (limit --limit-s narzędzia, nie pytest-timeout)"), "MUTACJE: 1 bez oczekiwanego wyniku"],
        ),
        pytest.param("NIC = 0", "NIC = 1", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param(
            "NIC = 0", "NIC = 1  # brama: mypy assignment", 0, [re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → mypy: src/rozliczenia/__init__.py:3: assignment"), "MUTACJE OK"]
        ),
        pytest.param(
            "WOLNO = False",
            "WOLNO = True  # brama: mypy exhaustive-match",
            0,
            [re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → mypy: src/rozliczenia/__init__.py:2: exhaustive-match"), "MUTACJE OK"],
        ),
        pytest.param(
            "NIC = 0", "NIC = 1  # brama: ruff F821", 0, [re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → ruff: src/rozliczenia/__init__.py:3: F821"), "MUTACJE OK"]
        ),
        pytest.param(
            "NIC = 0", "NIC = 1  # brama: ruff F822", 0, [re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → ruff: src/rozliczenia/__init__.py:3: F822"), "MUTACJE OK"]
        ),
        pytest.param(
            "NIC = 0",
            "NIC = 1  # brama: ruff invalid-syntax",
            0,
            [re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → ruff: src/rozliczenia/__init__.py:3: invalid-syntax"), "MUTACJE OK"],
        ),
        pytest.param("NIC = 0", "NIC = 1  # brama: ruff F401", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy unused-ignore", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy redundant-cast", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy no-any-return", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy -", 1, [r"NIEWYKRYTA: m → 1 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param(
            "NIC = 0",
            "NIC = 1  # brama: mypy późno",
            1,
            [re.escape("BEZ WERDYKTU: m → brama typów, mypy: brak wyniku po 1 s"), "MUTACJE: 1 bez oczekiwanego wyniku"],
        ),
        pytest.param(
            "tego nie ma",
            "",
            1,
            [re.escape("NIEAKTUALNA: m → kotwicy nie ma dokładnie raz w src/rozliczenia/__init__.py: 'tego nie ma'"), "MUTACJE: 1 bez oczekiwanego wyniku"],
        ),
    ],
    ids=[
        "zawieszenie",
        "przekroczony-czas",
        "niewykryta",
        "brama-mypy",
        "przekroczony-czas-brama-mypy",
        "brama-ruff",
        "brama-ruff-nazwa-w-all",
        "brama-ruff-blad-skladni",
        "brama-ruff-nieuzyty-import",
        "brama-mypy-nieuzyty-ignore",
        "brama-mypy-zbedny-cast",
        "brama-mypy-wynik-any",
        "brama-mypy-bez-kodu",
        "brama-bez-wyniku",
        "nieaktualna",
    ],
)
def test_skrypt_mutacji_skilla_liczy_zawieszenie_i_brame_typow_jak_wykryta_a_inne_werdykty_jako_porazke(
    tmp_path: Path, anchor: str, replacement: str, code: int, lines: list[str]
) -> None:
    """pytest-timeout czerwieni CI, więc noc nie zgłasza skryptu skilla, którego mutacja wiesza test do tego limitu; test
    tylko wolniejszy niż limit narzędzia w CI przechodzi, więc jego mutacja jest porażką, jak przed werdyktem ZAWIESZENIE.
    Mutację, którą testy przepuściły, a o której ruff albo mypy bramy pre-push mówią, że kod jest błędny, CI też by nie
    wpuściło (#703); nieużyty import, ``# type: ignore`` albo ``cast`` i wynik ``Any`` to tylko artefakt mutacji jednej
    linii."""

    # Mutacja flagi WOLNO ma przekroczyć limit, więc biegnie poleceniem WAITS z krótkim limitem.
    waits = anchor == "WOLNO = False"
    answered = _skill_check(tmp_path, anchor, replacement, hang_s=1, limit_s=2 if waits else 8, command=WAITS if waits else WISI_TEST)

    shown = answered.stdout.splitlines()
    assert answered.returncode == code and len(shown) == len(lines), answered.stdout + answered.stderr
    assert all(re.fullmatch(line, out) for line, out in zip(lines, shown, strict=True)), answered.stdout + answered.stderr



@pytest.mark.parametrize(
    ("anchor", "replacement", "verdict", "command", "limit_s", "least"),
    [
        pytest.param("WISI = False", "WISI = True", r"ZAWIESZENIE: m → .*Timeout.*", WISI_TEST, 10, 5, id="zawieszenie"),
        pytest.param(
            "WOLNO = False",
            "WOLNO = True  # brama: mypy exhaustive-match",
            re.escape("WYKRYTA PRZEZ BRAMĘ TYPÓW: m → mypy: src/rozliczenia/__init__.py:2: exhaustive-match"),
            WAITS,
            2,
            2,
            id="przekroczony-czas-brama-mypy",
        ),
    ],
)
def test_mutacja_liczona_jako_wykryta_po_dlugim_poleceniu_pokazuje_jego_czas_i_ostrzega_o_limicie(
    tmp_path: Path, anchor: str, replacement: str, verdict: str, command: tuple[str, ...], limit_s: int, least: int
) -> None:
    """ZAWIESZENIE i PRZEKROCZONY CZAS, który brama typów zmienia w WYKRYTA PRZEZ BRAMĘ TYPÓW, kończą się ``MUTACJE OK``,
    więc tylko linie ``CZAS`` i ``CZAS BLISKO LIMITU`` mówią w logu, że polecenie zużyło ponad połowę limitu albo cały
    (#927): pytest-timeout po połowie limitu albo cały limit, a nie dłużej niż cały skrypt na zegarze testu ani niż dwa
    limity."""

    started = time.perf_counter()
    answered = _skill_check(tmp_path, anchor, replacement, hang_s=limit_s // 2, limit_s=limit_s, command=command)
    took = time.perf_counter() - started

    shown = answered.stdout + answered.stderr
    lines = answered.stdout.splitlines()
    assert (answered.returncode, len(lines), lines[1:]) == (0, 2, ["MUTACJE OK"]) and re.fullmatch(verdict, lines[0]), shown
    times = answered.stderr.splitlines()
    assert len(times) == 2, shown
    spent = re.fullmatch(r"CZAS: m → ([0-9]+) s", times[0])
    warned = re.fullmatch(rf"CZAS BLISKO LIMITU: .*: m → ([0-9]+) s z limitu --limit-s {limit_s} s .*", times[1])
    assert spent and warned and warned[1] == spent[1] and least <= int(spent[1]) <= round(took), shown
    assert int(spent[1]) < 2 * limit_s, shown


LINUX_1 = "pytest (Python 3.14, Linux, 1/2)"


def _ci_repository(tmp_path: Path, plans: dict[str, list[plan_runu.Zadanie]], runs: list[int]) -> tuple[Path, dict[str, str], Path]:
    """Repozytorium z gałęzią ``praca``, która zmienia ``tests/test_zmieniony.py`` od ``glowna``, środowisko z atrapą
    ``gh`` na ``PATH`` i plik jej wywołań; atrapa podaje artefakt ``plan`` runów z ``plans`` i listę runów ``runs``, a
    pobranie runu 998 kończy błędem tylko na stdout."""

    neighbour = "import rozliczenia\n\n\ndef test_sasiad():\n    assert rozliczenia.WARTOSC == 0\n"
    files = {
        PACKAGE: "WARTOSC = 0\n",
        "tests/test_sasiad.py": neighbour,
        "tests/test_inny.py": neighbour.replace("sasiad", "inny"),
        "tests/test_windows.py": "def test_windows():\n    pass\n",
        "tests/test_zmieniony.py": "def test_zmieniony():\n    pass\n",
    }
    repo = repository(tmp_path / "repo", files)
    shutil.copytree(ROOT / "tools", repo / "tools", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    git(repo, "checkout", "--quiet", "-b", "praca")
    commit(repo, "baza")
    git(repo, "branch", "glowna")
    (repo / "tests/test_zmieniony.py").write_text("def test_zmieniony():\n    assert True\n", encoding="utf-8")
    commit(repo, "zmiana testu")
    gh = tmp_path / "gh"
    gh.mkdir()
    for run, jobs in plans.items():
        (gh / f"plan-{run}.json").write_text(plan_runu.Plan(Zdarzenie.PULL_REQUEST, 300.0, (), tuple(jobs)).do_json(), encoding="utf-8")
    (gh / "runy.json").write_text(json.dumps([{"databaseId": run} for run in runs]), encoding="utf-8")
    calls = gh / "wywolania"
    fake_cli(
        gh,
        "gh",
        "import pathlib, shutil, sys\n"
        "here = pathlib.Path(__file__).parent\n"
        "arguments = sys.argv[1:]\n"
        "with (here / 'wywolania').open('a', encoding='utf-8') as log:\n    log.write(' '.join(arguments) + chr(10))\n"
        "if arguments[:2] == ['run', 'list']:\n    print((here / 'runy.json').read_text(encoding='utf-8'))\n"
        "elif arguments[:3] == ['run', 'download', '998']:\n    print('gh: błąd tylko na stdout')\n    sys.exit(1)\n"
        "elif arguments[:2] == ['run', 'download'] and (here / f'plan-{arguments[2]}.json').exists():\n"
        "    shutil.copy(here / f'plan-{arguments[2]}.json', pathlib.Path(arguments[arguments.index('--dir') + 1]) / 'plan.json')\n"
        "else:\n    sys.exit(f'gh: atrapa nie zna {arguments}')\n",
    )
    return repo, {**WITHOUT_XDIST_WORKERS, "PATH": f"{gh}{os.pathsep}{os.environ['PATH']}"}, calls


def _job(track: str, name: str, *units: str) -> plan_runu.Zadanie:
    return plan_runu.Zadanie(f"{track}-{name[-4]}", track, name, units, 60.0)


PLAN = [
    _job("linux-3.14", LINUX_1, "pytest:tests/test_sasiad.py", "pytest:tests/test_zmieniony.py#1/2"),
    _job("linux-3.14", "pytest (Python 3.14, Linux, 2/2)", "pytest:tests/test_inny.py", "krok:timing"),
    _job("windows-3.13", "pytest (Python 3.13, 1/1)", "pytest:tests/test_zmieniony.py", "pytest:tests/test_windows.py"),
    _job("mutacje", "Mutation checks (1/1)", "skill:verify-x/ci"),
]
CHANGE = ("--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1")
# Run próbny 42584543040 (9.11.2026) na windows-latest: atrapę ``gh.cmd`` narzędzie znajduje (``tools/lib/github.py``),
# ale na Windows ``--jak-ci`` wybiera zadania toru Windows, a nie toru linux-3.14 tych planów.
ODTWARZA_TOR_LINUX = pytest.mark.skipif(
    sys.platform == "win32", reason="--jak-ci odtwarza zadanie toru systemu, na którym biegnie, a te plany sprawdzają tor Linux"
)


@ODTWARZA_TOR_LINUX
def test_jak_ci_uruchamia_mutacje_z_plikami_zadania_runu_w_ktorym_stoi_zmieniony_test(tmp_path: Path) -> None:
    """Sąsiad z zadania runu wykrywa mutację, której sam zmieniony test nie widzi; inne zadania i tor Windows nie biegną."""

    repo, env, _ = _ci_repository(tmp_path, {"123": PLAN}, [])

    answered = _in_repository(repo, "--jak-ci", "123", "--baza", "glowna", *CHANGE, env=env, merged=True)

    # Linia JAK CI wychodzi przed linią CZAS ze stderr, choć narzędzie pisze ją przed długim przebiegiem mutacji.
    lines = answered.stdout.splitlines()
    command = "-m pytest -q -n 1 -p no:cacheprovider tests/test_sasiad.py tests/test_zmieniony.py"
    assert (answered.returncode, lines[0], lines[3:]) == (0, f"JAK CI: run 123, {LINUX_1}: {command}", ["MUTACJE OK"]), answered.stdout
    assert lines[1].startswith(f"CZAS: mutacja [{LINUX_1}] → "), answered.stdout
    assert lines[2].startswith(f"WYKRYTA: mutacja [{LINUX_1}] → 1 failed, 1 passed"), answered.stdout


@ODTWARZA_TOR_LINUX
def test_jak_ci_uruchamia_kazda_mutacje_w_kazdym_zadaniu_runu_ze_zmienionym_testem(tmp_path: Path) -> None:
    """Zmieniony test stoi w dwóch zadaniach, a mutację wykrywa tylko sąsiad z drugiego, więc biegną oba; krok CI
    zadania nie jest plikiem testów."""

    second = "pytest (Python 3.14, Linux, 2/2)"
    plan = [
        _job("linux-3.14", LINUX_1, "pytest:tests/test_zmieniony.py#1/2"),
        _job("linux-3.14", second, "pytest:tests/test_sasiad.py", "pytest:tests/test_zmieniony.py#2/2", "krok:timing"),
    ]
    repo, env, _ = _ci_repository(tmp_path, {"123": plan}, [])

    answered = _in_repository(repo, "--jak-ci", "123", "--baza", "glowna", *CHANGE, env=env)

    lines = answered.stdout.splitlines()
    alone, together = "tests/test_zmieniony.py", "tests/test_sasiad.py tests/test_zmieniony.py"
    assert lines[:2] == [
        f"JAK CI: run 123, {LINUX_1}: -m pytest -q -n 1 -p no:cacheprovider {alone}",
        f"JAK CI: run 123, {second}: -m pytest -q -n 1 -p no:cacheprovider {together}",
    ], answered.stdout + answered.stderr
    assert [line.partition(" → ")[0] for line in lines[2:]] == [f"NIEWYKRYTA: mutacja [{LINUX_1}]", f"WYKRYTA: mutacja [{second}]", "MUTACJE: 1 bez oczekiwanego wyniku"], answered.stdout


@ODTWARZA_TOR_LINUX
@pytest.mark.parametrize("tracked", [True, False], ids=["galaz-sledzona", "galaz-bez-sledzonej"])
def test_jak_ci_bez_numeru_bierze_ostatni_run_ci_galezi(tmp_path: Path, tracked: bool) -> None:
    repo, env, calls = _ci_repository(tmp_path, {"456": PLAN}, [456])
    if tracked:
        git(repo, "remote", "add", "origin", str(tmp_path / "zdalne"))
        git(repo, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
        git(repo, "branch", "--quiet", "--set-upstream-to", "origin/feat/x")

    answered = _in_repository(repo, "--jak-ci", "--baza", "glowna", *CHANGE, env=env)

    assert answered.stdout.splitlines()[0].startswith(f"JAK CI: run 456, {LINUX_1}: "), answered.stdout + answered.stderr
    branch = "feat/x" if tracked else "praca"
    asked = [line.rsplit(" --dir ", 1)[0] for line in calls.read_text(encoding="utf-8").splitlines()]
    assert asked == [f"run list --workflow ci.yml --branch {branch} --limit 1 --json databaseId", "run download 456 --name plan"]


@ODTWARZA_TOR_LINUX
@pytest.mark.parametrize(
    ("arguments", "runs", "detached", "error"),
    [
        ((), [], False, "gałąź praca nie ma runu CI, więc podaj numer runu: --jak-ci <id runu>"),
        ((), [456], True, "HEAD nie jest na gałęzi, więc podaj numer runu CI: --jak-ci <id runu>"),
        (("789",), [], False, "run 789 nie stawia w zadaniu pytest toru linux-3.14 pliku testów zmienionego od glowna"),
        (("999",), [], False, "gh run download padł: gh: atrapa nie zna"),
        (("998",), [], False, "gh run download padł: gh: błąd tylko na stdout"),
    ],
    ids=["galaz-bez-runu", "odlaczony-head", "run-bez-zmienionego-testu-na-torze", "run-bez-artefaktu", "blad-gh-na-stdout"],
)
def test_jak_ci_bez_zadania_do_odtworzenia_odmawia_z_powodem(
    tmp_path: Path, arguments: tuple[str, ...], runs: list[int], detached: bool, error: str
) -> None:
    other = [_job("windows-3.13", "pytest (Python 3.13, 1/1)", "pytest:tests/test_zmieniony.py"), PLAN[1]]
    repo, env, _ = _ci_repository(tmp_path, {"456": PLAN, "789": other}, runs)
    if detached:
        git(repo, "checkout", "--quiet", "--detach")

    answered = _in_repository(repo, "--jak-ci", *arguments, "--baza", "glowna", *CHANGE, env=env)

    assert answered.returncode == 2, answered.stdout + answered.stderr
    assert answered.stderr.splitlines()[-1].partition(": error: ")[2].startswith(error), answered.stderr


@pytest.mark.parametrize(
    ("entry", "command", "error"),
    [
        ({}, ["--", "-c", ""], "--jak-ci składa polecenie samo, więc nie podawaj go po --"),
        ({"polecenie": ["-c", ""]}, [], "--jak-ci składa polecenie samo, a wpisy m mają własne"),
    ],
    ids=["polecenie-po-myslnikach", "polecenie-we-wpisie"],
)
def test_jak_ci_nie_przyjmuje_wlasnego_polecenia(tmp_path: Path, entry: dict[str, list[str]], command: list[str], error: str) -> None:
    plan = tmp_path / "mutacje.json"
    plan.write_text(json.dumps([{"nazwa": "m", "zmiany": [_appended(PACKAGE, "")], **entry}]), encoding="utf-8")

    # Baza, której nie ma: narzędzie, które mimo polecenia zacznie budować plan CI, pada na niej od razu.
    answered = _mutacje("--jak-ci", "--baza", "nie-ma-takiej-galezi", "--plik", str(plan), *command)

    assert (answered.returncode, answered.stderr.splitlines()[-1].partition(": error: ")[2]) == (2, error)


def _check_all(repo: Path, anchor: str, replacement: str) -> subprocess.CompletedProcess[str]:
    """``check_all`` skryptu mutacji skilla z atrapą bramy (``FAKE_GATE``), jedną mutacją pakietu i poleceniem, które
    tylko go importuje."""

    script = (
        "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nimport silnik_mutacji\nfrom silnik_mutacji import Edit, Mutation, check_all\n"
        f"{FAKE_GATE}\nmutation = Mutation('m', (Edit(Path({PACKAGE!r}), {anchor!r}, {replacement!r}),), {IMPORT!r})\n"
        "raise SystemExit(check_all([mutation], gate=brama))\n"
    )
    return subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)


def test_brama_typow_czerwona_bez_mutacji_zostawia_przezyta_mutacje_przezyta(tmp_path: Path) -> None:
    """Brama, która coś zgłasza bez mutacji, niczego nie dowodzi, więc nie zabiera mutacji z issue; jej linia idzie na
    stderr, więc nie zmienia wyjścia, które czytają wywołujący."""

    repo = repository(tmp_path / "repo", {PACKAGE: "ZLE = 1  # brama: ruff F401\nNIC = 0\n"})
    commit(repo, "baza")

    answered = _check_all(repo, "NIC = 0", "NIC = 1  # brama: mypy assignment")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["NIEWYKRYTA: m → kod wyjścia 0", "MUTACJE: 1 bez oczekiwanego wyniku"]), answered.stderr
    assert [line for line in answered.stderr.splitlines() if not line.startswith("CZAS: m → ")] == [
        "BRAMA TYPÓW CZERWONA: ruff: src/rozliczenia/__init__.py:1: F401 (bez mutacji, więc przeżyte mutacje zostają przeżyte)"
    ]


def test_skrypt_mutacji_skilla_w_pythonie_bez_ruff_i_mypy_konczy_sie_bledem_instalacji_a_nie_przezyta_mutacja(tmp_path: Path) -> None:
    """Mutation checks z samym ``requirements.txt`` drukowały ``BRAMA TYPÓW CZERWONA: ruff: … No module named ruff`` i
    zostawiały przeżyte mutacje przeżytymi, choć brama typów mogła je wykryć (main 5.11–12.11). Brak narzędzia bramy to
    zła instalacja, więc skrypt kończy się kodem 2 z poleceniem, które ją naprawia."""

    script = (
        "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nfrom silnik_mutacji import Edit, Mutation, check_all\n"
        f"raise SystemExit(check_all([Mutation('m', (Edit(Path({PACKAGE!r}), 'WARTOSC = 0', 'WARTOSC = 1'),), {IMPORT!r})]))\n"
    )

    answered = subprocess.run(
        [_python_without_dev(tmp_path), "-c", script], cwd=_small_repository(tmp_path), capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )

    shown = answered.stdout.splitlines()
    assert (answered.returncode, len(shown)) == (2, 1), answered.stdout + answered.stderr
    assert re.fullmatch(r'MUTACJE: brama typów bez narzędzia: .+ nie ma modułu ruff kroku ruff; zainstaluj dodatek dev \(uv pip install -e "\.\[dev\]"\)', shown[0]), shown


def test_brama_typow_nocy_w_pythonie_bez_ruff_i_mypy_jest_czerwona_i_zostawia_werdykty(tmp_path: Path) -> None:
    """Noc (``tools/mutacje_zmiany.py``) woła ``type_gate`` z ``static_gate``, a jej testy biegną w zadaniu pytest na
    Windows z samym ``requirements.txt``. Brak narzędzia nie przerywa tam przebiegu: brama jest czerwona bez mutacji,
    a przeżyta mutacja zostaje przeżyta."""

    script = (
        "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nfrom silnik_mutacji import Edit, Mutation, Verdict, static_gate, type_gate\n"
        f"mutation = Mutation('m', (Edit(Path({PACKAGE!r}), 'WARTOSC = 0', 'WARTOSC = 1'),), {IMPORT!r})\n"
        "print([(str(verdict), shown) for verdict, shown in type_gate([mutation], [(Verdict.SURVIVED, 'kod wyjścia 0')], workers=1, gate=static_gate)])\n"
    )

    answered = subprocess.run(
        [_python_without_dev(tmp_path), "-c", script], cwd=_small_repository(tmp_path), capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )

    assert (answered.returncode, answered.stdout) == (0, "[('NIEWYKRYTA', 'kod wyjścia 0')]\n"), answered.stdout + answered.stderr
    assert re.fullmatch(r"BRAMA TYPÓW CZERWONA: ruff: .*No module named ruff \(bez mutacji, więc przeżyte mutacje zostają przeżyte\)\n", answered.stderr), answered.stderr


def _python_without_dev(tmp_path: Path) -> Path:
    """Python świeżego venv bez pakietów, więc bez ruff i mypy dodatku dev, jak zadanie pytest na Windows."""

    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "venv")], check=True, timeout=120)
    return next(path for path in (tmp_path / "venv" / "bin" / "python", tmp_path / "venv" / "Scripts" / "python.exe") if path.exists())


# Atrapy ``python -m ruff`` i ``python -m mypy`` w korzeniu kopii, które biegną przed zainstalowanymi: ruff zgłasza
# niezdefiniowaną nazwę (F821, wykrycie bramy typów) w każdej linii ``src`` z komentarzem ``# brama: F821``, a mypy przechodzi.
FAKE_RUFF = """\
import json, pathlib, sys
found = [
    {"code": "F821", "filename": str(path), "location": {"row": number}, "message": "Undefined name"}
    for path in sorted(pathlib.Path("src").rglob("*.py"))
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
    if "# brama: F821" in line
]
print(json.dumps(found))
sys.exit(1 if found else 0)
"""


@pytest.mark.parametrize(
    ("skill", "verdict"), [(True, "WYKRYTA PRZEZ BRAMĘ TYPÓW: m → ruff: "), (False, "NIEWYKRYTA: mutacja → kod wyjścia 0")], ids=["skrypt-skilla", "przeglad"]
)
def test_przeglad_z_wiersza_polecen_nie_liczy_bramy_typow_jako_wykrycia(tmp_path: Path, skill: bool, verdict: str) -> None:
    """Przegląd dowodzi, że jego polecenie łapie mutację (mypy sprawdza się ``-- -m mypy``), więc mutacja, którą łapie
    tylko brama typów, jest w nim NIEWYKRYTA, a w skrypcie mutacji skilla WYKRYTA PRZEZ BRAMĘ TYPÓW."""

    tools = {f"{name}/{module}": "" for name in ("ruff", "mypy") for module in ("__init__.py", "__main__.py")}
    repo = repository(tmp_path / "repo", {PACKAGE: "NIC = 0\n", **tools, "ruff/__main__.py": FAKE_RUFF})
    commit(repo, "baza")
    mutated = ("NIC = 0", "NIC = 1  # brama: F821")

    if skill:
        script = (
            "import sys\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nfrom silnik_mutacji import Edit, Mutation, check_all\n"
            f"raise SystemExit(check_all([Mutation('m', (Edit(Path({PACKAGE!r}), *{mutated!r}),), {IMPORT!r})]))\n"
        )
        answered = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    else:
        answered = _in_repository(repo, "--zmiana", PACKAGE, *mutated, "--baza", "HEAD", "--", *IMPORT)

    assert answered.stdout.splitlines()[0].startswith(verdict), answered.stdout + answered.stderr
    assert answered.returncode == (0 if skill else 1), answered.stdout + answered.stderr


def test_brama_typow_bez_wyniku_przed_koncem_czasu_wywolujacego_daje_bez_werdyktu(tmp_path: Path) -> None:
    """Przeżyta, której brama nie sprawdziła przed końcem czasu, to BEZ WERDYKTU: noc zgłasza ją jako mutację bez werdyktu, a nie przeżytą."""

    repo = repository(tmp_path / "repo", {PACKAGE: "NIC = 0\n"})
    commit(repo, "baza")
    script = (
        "import sys, time\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nimport silnik_mutacji\n"
        f"mutation = silnik_mutacji.Mutation('m', (silnik_mutacji.Edit(Path({PACKAGE!r}), 'NIC = 0', 'NIC = 1'),), {IMPORT!r})\n"
        "found = [(silnik_mutacji.Verdict.SURVIVED, 'kod wyjścia 0'), (silnik_mutacji.Verdict.CAUGHT, 'kod wyjścia 1')]\n"
        "for verdict, last in silnik_mutacji.type_gate([mutation, mutation], found, workers=1, deadline=time.monotonic()):\n"
        "    print(f'{verdict}: {last}')\n"
    )

    answered = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)

    assert answered.stdout.splitlines() == [
        "BEZ WERDYKTU: kod wyjścia 0 (brama typów, ruff: czas minął, zanim się zaczął, bez mutacji)",
        "WYKRYTA: kod wyjścia 1",
    ], answered.stdout + answered.stderr


def _type_gate(repo: Path, gate: str, found: str, *, deadline: str = "None") -> subprocess.CompletedProcess[str]:
    """``type_gate`` z bramą ``gate`` (źródło funkcji ``brama``) dla werdyktów ``found`` jednej mutacji ``NIC = 0`` →
    ``NIC = 1``; drukuje werdykt po bramie."""

    script = (
        "import sys, time\nsys.path.insert(0, 'tools/lib')\nfrom pathlib import Path\nimport silnik_mutacji\n"
        f"{gate}\nmutation = silnik_mutacji.Mutation('m', (silnik_mutacji.Edit(Path({PACKAGE!r}), 'NIC = 0', 'NIC = 1'),), {IMPORT!r})\n"
        f"for verdict, last in silnik_mutacji.type_gate([mutation], {found}, workers=1, deadline={deadline}, gate=brama):\n"
        "    print(f'{verdict}: {last}')\n"
    )
    repo = repository(repo, {PACKAGE: "NIC = 0\n"})
    commit(repo, "baza")
    return subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)


def test_brama_typow_nie_biegnie_gdy_polecenie_zlapalo_kazda_mutacje(tmp_path: Path) -> None:
    """Brama to ruff i mypy obu systemów na kopii checkoutu, więc biegnie tylko dla mutacji, którą polecenie przepuściło."""

    gate = "def brama(copy, **_):\n    print('brama biegła')\n    return silnik_mutacji.Checked((silnik_mutacji.Finding('ruff', 'ruff', 'F821', 'x'),))\n"

    answered = _type_gate(tmp_path / "repo", gate, "[(silnik_mutacji.Verdict.CAUGHT, 'kod wyjścia 1')]")

    assert (answered.stdout.splitlines(), answered.stderr) == (["WYKRYTA: kod wyjścia 1"], "")


def test_kopia_mutacji_dostaje_cache_mypy_bramy_z_kopii_bez_mutacji(tmp_path: Path) -> None:
    """Mypy na kopii mutacji sprawdza od nowa tylko to, co mutacja zmienia, bo dostaje cache z przebiegu bez mutacji."""

    gate = (
        "def brama(copy, **_):\n"
        "    cache = copy / silnik_mutacji.MYPY_CACHE / 'z-kopii-bez-mutacji'\n"
        f"    if 'NIC = 0' in (copy / {PACKAGE!r}).read_text(encoding='utf-8'):\n"
        "        cache.mkdir(parents=True)\n"
        "        return silnik_mutacji.Checked()\n"
        "    return silnik_mutacji.Checked((silnik_mutacji.Finding('mypy', 'mypy', 'misc', f'cache bez mutacji: {cache.is_dir()}'),))\n"
    )

    answered = _type_gate(tmp_path / "repo", gate, "[(silnik_mutacji.Verdict.SURVIVED, 'kod wyjścia 0')]")

    assert answered.stdout.splitlines() == ["WYKRYTA PRZEZ BRAMĘ TYPÓW: mypy: cache bez mutacji: True"], answered.stderr


def test_brama_typow_kopii_z_mutacja_konczy_sie_z_czasem_wywolujacego(tmp_path: Path) -> None:
    """Krok bramy na kopii z mutacją, który nie zdąży przed końcem czasu wywołującego, daje BEZ WERDYKTU, nie przeżytą."""

    gate = (
        "def brama(copy, *, deadline, **_):\n"
        f"    needed = 30 if 'NIC = 1' in (copy / {PACKAGE!r}).read_text(encoding='utf-8') else 0\n"
        "    late = deadline is not None and deadline - time.monotonic() < needed\n"
        "    return silnik_mutacji.Checked((), 'mypy: brak wyniku przed końcem czasu' if late else None)\n"
    )

    answered = _type_gate(tmp_path / "repo", gate, "[(silnik_mutacji.Verdict.SURVIVED, 'kod wyjścia 0')]", deadline="time.monotonic() + 10")

    assert answered.stdout.splitlines() == ["BEZ WERDYKTU: brama typów, mypy: brak wyniku przed końcem czasu"], answered.stderr


# Atrapa ``python -m ruff`` i ``python -m mypy`` w katalogu kroku (``-m`` szuka najpierw w nim): odpowiedź z
# ``<narzędzie>.json`` w JSON tylko z opcją, z którą brama prosi o JSON, a bez niej linia tekstu.
FAKE_TOOL = """\
import json, pathlib, sys
answer = json.loads(pathlib.Path({name!r} + ".json").read_text(encoding="utf-8"))
if {option!r} not in " ".join(sys.argv[1:]):
    print("bez JSON")
    raise SystemExit(1)
sys.stdout.write(answer["stdout"])
sys.stderr.write(answer["stderr"])
raise SystemExit(answer["code"])
"""


def _ruff_item(folder: Path, code: str, row: int, message: str) -> dict[str, object]:
    return {"code": code, "filename": str(folder / "src" / "a.py"), "location": {"row": row, "column": 1}, "message": message, "fix": None}


def _mypy_line(severity: str, code: str, message: str) -> str:
    return json.dumps({"file": "src/a.py", "line": 3, "column": 1, "message": message, "hint": None, "code": code, "severity": severity})


@pytest.mark.parametrize(
    ("ruff", "mypy", "findings"),
    [
        pytest.param(
            lambda folder: (1, json.dumps([_ruff_item(folder, "F401", 1, "`os` imported but unused"), _ruff_item(folder, "F821", 2, "Undefined name `x`")]), ""),
            lambda folder: (1, _mypy_line("error", "name-defined", 'Name "x" is not defined') + "\n", ""),
            [("ruff", "ruff", "F401", "src/a.py:1: F401 `os` imported but unused"), ("ruff", "ruff", "F821", "src/a.py:2: F821 Undefined name `x`")],
            id="błąd-ruff-kończy-bramę",
        ),
        pytest.param(
            lambda folder: (1, "", "python: No module named ruff\n"),
            lambda folder: (
                1,
                "\n".join([_mypy_line("note", "misc", "Ta notatka nie jest błędem"), _mypy_line("error", "unused-ignore", 'Unused "type: ignore" comment'), "Found 1 error"]),
                "",
            ),
            [
                ("ruff", "ruff", None, "python: No module named ruff"),
                ("mypy", "mypy", "unused-ignore", 'src/a.py:3: error: Unused "type: ignore" comment  [unused-ignore]'),
                ("mypy (Windows)", "mypy", "unused-ignore", 'src/a.py:3: error: Unused "type: ignore" comment  [unused-ignore]'),
            ],
            id="wyjscie-bez-json-i-pozostalosci",
        ),
        pytest.param(
            lambda folder: (1, "[1]", ""),
            lambda folder: (1, '"tekst"\n' + _mypy_line("error", "name-defined", 'Name "x" is not defined') + "\n", ""),
            [("ruff", "ruff", None, "[1]"), ("mypy", "mypy", "name-defined", 'src/a.py:3: error: Name "x" is not defined  [name-defined]')],
            id="json-innego-ksztaltu",
        ),
        pytest.param(lambda folder: (0, "[]", ""), lambda folder: (0, "nic", ""), [], id="kroki-przechodza"),
    ],
)
def test_brama_typow_czyta_diagnostyki_ruff_i_mypy_z_json(
    tmp_path: Path,
    ruff: Callable[[Path], tuple[int, str, str]],
    mypy: Callable[[Path], tuple[int, str, str]],
    findings: list[tuple[str, str, str | None, str]],
) -> None:
    """Kroki bramy biegną z ``--output-format json`` (ruff) i ``--output json`` (mypy); wyjście, którego nie da się
    przeczytać, to diagnostyka bez kodu, a krok, który przechodzi, nie ma diagnostyk."""

    for name, option, answer in (("ruff", "--output-format json", ruff), ("mypy", "--output json", mypy)):
        (tmp_path / name).mkdir()
        # Zwykły pakiet: katalog bez ``__init__.py`` przegrywa z zainstalowanym ruff albo mypy.
        (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / name / "__main__.py").write_text(FAKE_TOOL.format(name=name, option=option), encoding="utf-8")
        code, stdout, stderr = answer(tmp_path)
        (tmp_path / f"{name}.json").write_text(json.dumps({"code": code, "stdout": stdout, "stderr": stderr}), encoding="utf-8")

    checked = silnik_mutacji.static_gate(tmp_path, limit_s=60, stop=threading.Event(), deadline=None)

    assert checked == silnik_mutacji.Checked(tuple(silnik_mutacji.Finding(*finding) for finding in findings))


def test_krok_bramy_typow_bez_wyniku_w_limicie_daje_kopie_bez_werdyktu(tmp_path: Path) -> None:
    """Krok, który wisi dłużej niż ``limit_s``, nie daje diagnostyk, więc brama nie wie, czy mutacja przeżyła: noc liczy
    BEZ WERDYKTU i zgłasza ją w issue jako mutację bez werdyktu, a nie przeżytą."""

    (tmp_path / "ruff").mkdir()
    (tmp_path / "ruff" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "ruff" / "__main__.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")

    checked = silnik_mutacji.static_gate(tmp_path, limit_s=1, stop=threading.Event(), deadline=None)

    assert checked == silnik_mutacji.Checked((), "ruff: brak wyniku po 1 s")


def test_przerwanie_narzedzia_konczy_krok_bramy_typow_bez_czekania_na_limit(tmp_path: Path) -> None:
    (tmp_path / "ruff").mkdir()
    (tmp_path / "ruff" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "ruff" / "__main__.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    stop = threading.Event()
    stop.set()

    with pytest.raises(potomne.Stopped):
        silnik_mutacji.static_gate(tmp_path, limit_s=20, stop=stop, deadline=None)
