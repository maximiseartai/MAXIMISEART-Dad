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
from tests.fixtures.git_repo import commit, git, repository
from tests.fixtures.potomne import beating

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import mutacje  # noqa: E402
import plan_ci  # noqa: E402
from zakres_runu import Zdarzenie  # noqa: E402

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


@pytest.mark.parametrize("anchor", ["tego tekstu nie ma w pliku", "\n"], ids=["brak", "wiele-razy"])
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


def test_pusta_lista_mutacji_niczego_nie_dowodzi() -> None:
    answered = subprocess.run(
        [sys.executable, "-c", "import sys\nsys.path.insert(0, 'tools')\nfrom mutacje import check_all\nraise SystemExit(check_all(()))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert (answered.returncode, answered.stdout.strip()) == (1, "MUTACJE: brak mutacji, więc nie ma czego dowieść")


def test_czesci_tabeli_sprawdzaja_kazda_mutacje_raz_kazda_z_podstawa_tylko_polecen_swoich_mutacji(tmp_path: Path) -> None:
    repo = _small_repository(tmp_path)
    log = tmp_path / "polecenia"

    def command(name: str) -> list[str]:
        seen = "os.environ.get('MUTACJE_CZESC', '-')"
        writes = f"open(os.environ['DZIENNIK'], 'a').write('{name} ' + str(rozliczenia.WARTOSC) + ' ' + {seen} + chr(10))"
        return ["-c", f"import os, rozliczenia\n{writes}\nraise SystemExit(rozliczenia.WARTOSC)"]

    table = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]], "polecenie": command("AB"[number % 2])} for number in range(1, 6)]
    seen = {}
    # Każda część to osobne zadanie CI z tą samą tabelą, a kolejność tabeli nie zmienia podziału.
    for part, order in (("1/3", table), ("2/3", table[::-1]), ("3/3", table[2:] + table[:2]), ("6/6", table)):
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
        "1/3": (0, "MUTACJE OK", ["m1", "m4"], ["A", "B"], {"-"}),
        "2/3": (0, "MUTACJE OK", ["m2", "m5"], ["A", "B"], {"-"}),
        "3/3": (0, "MUTACJE OK", ["m3"], ["B"], {"-"}),
        "6/6": (0, "MUTACJE OK", [], [], set()),
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
        [sys.executable, str(repo / "tools" / "mutacje.py"), "--limit-s", "5", *mutation],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    expected = "PRZEKROCZONY CZAS: mutacja → brak wyniku po 5 s (limit --limit-s narzędzia, nie pytest-timeout)"
    assert (answered.returncode, answered.stdout.splitlines()[0]) == (1, expected)


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
    deadline = time.monotonic() + 60
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.1)

    tool.send_signal(signal.SIGINT)
    tool.wait(timeout=20)
    deadline = time.monotonic() + 20
    while any(scratch.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.1)

    assert (started.exists(), beating(beats)) == (True, False)
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert list(scratch.iterdir()) == []


# Środowisko wywołującego bez wartości ``-n auto``, którą ustawia ``tools/szybko.py``.
WITHOUT_XDIST_WORKERS = {name: value for name, value in os.environ.items() if name != "PYTEST_XDIST_AUTO_NUM_WORKERS"}


def _small_repository(path: Path) -> Path:
    repo = repository(path / "repo", {"src/rozliczenia/__init__.py": "WARTOSC = 0\n"})
    commit(repo, "baza")
    return repo


def _plan(path: Path, count: int) -> Path:
    plan = path / "mutacje.json"
    entries = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]]} for number in range(1, count + 1)]
    plan.write_text(json.dumps(entries), encoding="utf-8")
    return plan


def _in_repository(repo: Path, *arguments: str, env: dict[str, str] = WITHOUT_XDIST_WORKERS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), *arguments],
        cwd=repo,
        env=env,
        capture_output=True,
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


def test_naraz_biegnie_najwyzej_osiem_mutacji(tmp_path: Path) -> None:
    """Każda mutacja czeka, aż wystartuje osiem, i podaje, ile biegnie naraz; dziewiąta startuje dopiero po końcu innej."""

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
        "    while len(list(started.iterdir())) < 8 and time.monotonic() < deadline:\n"
        "        time.sleep(0.05)\n"
        "    time.sleep(0.5)\n"
        "    print('naraz', len(list(running.iterdir())))\n"
        "    (running / me).unlink()\n"
        "    raise SystemExit(1)\n"
    )

    answered = _in_repository(_small_repository(tmp_path), "--rownolegle", "--plik", str(_plan(tmp_path, 9)), "--", "-c", counts)

    seen = [int(line.rsplit(" ", 1)[1]) for line in answered.stdout.splitlines() if line.startswith("WYKRYTA: m")]
    assert (len(seen), max(seen, default=0)) == (9, 8), answered.stdout + answered.stderr



@pytest.mark.parametrize(
    ("anchor", "replacement", "code", "lines"),
    [
        pytest.param("WISI = False", "WISI = True", 0, [r"ZAWIESZENIE: m → .*Timeout.* \(liczona jako wykryta: pytest-timeout czerwieni test w CI\)", "MUTACJE OK"]),
        pytest.param(
            "WOLNO = False",
            "WOLNO = True",
            1,
            [re.escape("PRZEKROCZONY CZAS: m → brak wyniku po 8 s (limit --limit-s narzędzia, nie pytest-timeout)"), "MUTACJE: 1 bez oczekiwanego wyniku"],
        ),
        pytest.param("NIC = 0", "NIC = 1", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
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
        pytest.param("NIC = 0", "NIC = 1  # brama: ruff F401", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy unused-ignore", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy redundant-cast", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy no-any-return", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
        pytest.param("NIC = 0", "NIC = 1  # brama: mypy -", 1, [r"NIEWYKRYTA: m → 2 passed in .*", "MUTACJE: 1 bez oczekiwanego wyniku"]),
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

    tests = (
        "import time\n\nimport pytest\nimport rozliczenia\n\n\n"
        "@pytest.mark.timeout(1)\ndef test_wisi():\n    if rozliczenia.WISI:\n        time.sleep(60)\n\n\n"
        "def test_wolno():\n    if rozliczenia.WOLNO:\n        time.sleep(60)\n"
    )
    repo = repository(tmp_path / "repo", {PACKAGE: "WISI = False\nWOLNO = False\nNIC = 0\n", "tests/test_wisi.py": tests})
    commit(repo, "baza")
    command = ("-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_wisi.py")
    script = (
        "import sys\nsys.path.insert(0, 'tools')\nfrom pathlib import Path\nimport mutacje\nfrom mutacje import Edit, Mutation, check_all\n"
        f"{FAKE_GATE}\nmutation = Mutation('m', (Edit(Path({PACKAGE!r}), {anchor!r}, {replacement!r}),), {command!r})\n"
        "raise SystemExit(check_all([mutation], limit_s=8, gate=brama))\n"
    )

    answered = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)

    shown = answered.stdout.splitlines()
    assert answered.returncode == code and len(shown) == len(lines), answered.stdout + answered.stderr
    assert all(re.fullmatch(line, out) for line, out in zip(lines, shown, strict=True)), answered.stdout + answered.stderr


LINUX_1 = "pytest (Python 3.14, Linux, 1/2)"


def _ci_repository(tmp_path: Path, plans: dict[str, list[plan_ci.Zadanie]], runs: list[int]) -> tuple[Path, dict[str, str], Path]:
    """Repozytorium z gałęzią ``praca``, która zmienia ``tests/test_zmieniony.py`` od ``glowna``, środowisko z atrapą
    ``gh`` na ``PATH`` i plik jej wywołań; atrapa podaje artefakt ``plan`` runów z ``plans`` i listę runów ``runs``."""

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
        (gh / f"plan-{run}.json").write_text(plan_ci.Plan(Zdarzenie.PULL_REQUEST, 300.0, (), tuple(jobs)).do_json(), encoding="utf-8")
    (gh / "runy.json").write_text(json.dumps([{"databaseId": run} for run in runs]), encoding="utf-8")
    calls = gh / "wywolania"
    (gh / "gh.py").write_text(
        "import pathlib, shutil, sys\n"
        "here = pathlib.Path(__file__).parent\n"
        "arguments = sys.argv[1:]\n"
        "with (here / 'wywolania').open('a', encoding='utf-8') as log:\n    log.write(' '.join(arguments) + chr(10))\n"
        "if arguments[:2] == ['run', 'list']:\n    print((here / 'runy.json').read_text(encoding='utf-8'))\n"
        "elif arguments[:2] == ['run', 'download'] and (here / f'plan-{arguments[2]}.json').exists():\n"
        "    shutil.copy(here / f'plan-{arguments[2]}.json', pathlib.Path(arguments[arguments.index('--dir') + 1]) / 'plan.json')\n"
        "else:\n    sys.exit(f'gh: atrapa nie zna {arguments}')\n",
        encoding="utf-8",
    )
    (gh / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{gh / "gh.py"}" "$@"\n', encoding="utf-8")
    (gh / "gh").chmod(0o755)
    return repo, {**WITHOUT_XDIST_WORKERS, "PATH": f"{gh}{os.pathsep}{os.environ['PATH']}"}, calls


def _job(track: str, name: str, *units: str) -> plan_ci.Zadanie:
    return plan_ci.Zadanie(f"{track}-{name[-4]}", track, name, units, 60.0)


PLAN = [
    _job("linux-3.14", LINUX_1, "pytest:tests/test_sasiad.py", "pytest:tests/test_zmieniony.py#1/2"),
    _job("linux-3.14", "pytest (Python 3.14, Linux, 2/2)", "pytest:tests/test_inny.py", "krok:timing"),
    _job("windows-3.11", "pytest (Python 3.11, 1/1)", "pytest:tests/test_zmieniony.py", "pytest:tests/test_windows.py"),
    _job("mutacje", "Mutation checks (1/1)", "skill:verify-x/ci"),
]
CHANGE = ("--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1")


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")
def test_jak_ci_uruchamia_mutacje_z_plikami_zadania_runu_w_ktorym_stoi_zmieniony_test(tmp_path: Path) -> None:
    """Sąsiad z zadania runu wykrywa mutację, której sam zmieniony test nie widzi; inne zadania i tor Windows nie biegną."""

    repo, env, _ = _ci_repository(tmp_path, {"123": PLAN}, [])

    answered = _in_repository(repo, "--jak-ci", "123", "--baza", "glowna", *CHANGE, env=env)

    lines = answered.stdout.splitlines()
    command = "-m pytest -q -n 1 -p no:cacheprovider tests/test_sasiad.py tests/test_zmieniony.py"
    assert (answered.returncode, lines[0], lines[2:]) == (0, f"JAK CI: run 123, {LINUX_1}: {command}", ["MUTACJE OK"]), answered.stdout + answered.stderr
    assert lines[1].startswith(f"WYKRYTA: mutacja [{LINUX_1}] → 1 failed, 1 passed"), answered.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")
def test_jak_ci_uruchamia_kazda_mutacje_w_kazdym_zadaniu_runu_ze_zmienionym_testem(tmp_path: Path) -> None:
    """Zmieniony test stoi w dwóch zadaniach, a mutację wykrywa tylko sąsiad z drugiego, więc biegną oba."""

    second = "pytest (Python 3.14, Linux, 2/2)"
    plan = [
        _job("linux-3.14", LINUX_1, "pytest:tests/test_zmieniony.py#1/2"),
        _job("linux-3.14", second, "pytest:tests/test_sasiad.py", "pytest:tests/test_zmieniony.py#2/2"),
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


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")
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


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa gh to skrypt sh")
@pytest.mark.parametrize(
    ("arguments", "runs", "detached", "error"),
    [
        ((), [], False, "gałąź praca nie ma runu CI, więc podaj numer runu: --jak-ci <id runu>"),
        ((), [456], True, "HEAD nie jest na gałęzi, więc podaj numer runu CI: --jak-ci <id runu>"),
        (("789",), [], False, "run 789 nie stawia w zadaniu pytest toru linux-3.14 pliku testów zmienionego od glowna"),
        (("999",), [], False, "gh run download padł: gh: atrapa nie zna"),
    ],
    ids=["galaz-bez-runu", "odlaczony-head", "run-bez-zmienionego-testu-na-torze", "run-bez-artefaktu"],
)
def test_jak_ci_bez_zadania_do_odtworzenia_odmawia_z_powodem(
    tmp_path: Path, arguments: tuple[str, ...], runs: list[int], detached: bool, error: str
) -> None:
    other = [_job("windows-3.11", "pytest (Python 3.11, 1/1)", "pytest:tests/test_zmieniony.py"), PLAN[1]]
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


def _check_all(repo: Path, anchor: str, replacement: str, *, base: str | None = None) -> subprocess.CompletedProcess[str]:
    """``check_all`` skryptu mutacji skilla z atrapą bramy (``FAKE_GATE``), jedną mutacją pakietu i poleceniem, które
    tylko go importuje."""

    script = (
        "import sys\nsys.path.insert(0, 'tools')\nfrom pathlib import Path\nimport mutacje\nfrom mutacje import Edit, Mutation, check_all\n"
        f"{FAKE_GATE}\nmutation = Mutation('m', (Edit(Path({PACKAGE!r}), {anchor!r}, {replacement!r}),), {IMPORT!r})\n"
        f"raise SystemExit(check_all([mutation], base={base!r}, gate=brama))\n"
    )
    return subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)


def test_brama_typow_czerwona_bez_mutacji_zostawia_przezyta_mutacje_przezyta(tmp_path: Path) -> None:
    """Brama, która coś zgłasza bez mutacji, niczego nie dowodzi, więc nie zabiera mutacji z issue; jej linia idzie na
    stderr, więc nie zmienia wyjścia, które czytają wywołujący."""

    repo = repository(tmp_path / "repo", {PACKAGE: "ZLE = 1  # brama: ruff F401\nNIC = 0\n"})
    commit(repo, "baza")

    answered = _check_all(repo, "NIC = 0", "NIC = 1  # brama: mypy assignment")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["NIEWYKRYTA: m → kod wyjścia 0", "MUTACJE: 1 bez oczekiwanego wyniku"]), answered.stderr
    assert answered.stderr.splitlines() == [
        "BRAMA TYPÓW CZERWONA: ruff: src/rozliczenia/__init__.py:1: F401 (bez mutacji, więc przeżyte mutacje zostają przeżyte)"
    ]


def test_przeglad_z_wiersza_polecen_nie_liczy_bramy_typow_jako_wykrycia(tmp_path: Path) -> None:
    """Przegląd (``check_all`` z ``base``) dowodzi, że jego polecenie łapie mutację; mypy sprawdza się ``-- -m mypy``."""

    repo = repository(tmp_path / "repo", {PACKAGE: "NIC = 0\n"})
    commit(repo, "baza")

    answered = _check_all(repo, "NIC = 0", "NIC = 1  # brama: mypy assignment", base="HEAD")

    assert (answered.returncode, answered.stdout.splitlines()) == (1, ["NIEWYKRYTA: m → kod wyjścia 0", "MUTACJE: 1 bez oczekiwanego wyniku"]), answered.stderr


def test_brama_typow_bez_wyniku_przed_koncem_czasu_wywolujacego_daje_bez_werdyktu(tmp_path: Path) -> None:
    """Noc liczy BEZ WERDYKTU jak część bez wyniku, więc przeżyta, której brama nie sprawdziła, nie trafia do issue."""

    repo = repository(tmp_path / "repo", {PACKAGE: "NIC = 0\n"})
    commit(repo, "baza")
    script = (
        "import sys, time\nsys.path.insert(0, 'tools')\nfrom pathlib import Path\nimport mutacje\n"
        f"mutation = mutacje.Mutation('m', (mutacje.Edit(Path({PACKAGE!r}), 'NIC = 0', 'NIC = 1'),), {IMPORT!r})\n"
        "found = [(mutacje.Verdict.SURVIVED, 'kod wyjścia 0'), (mutacje.Verdict.CAUGHT, 'kod wyjścia 1')]\n"
        "for verdict, last in mutacje.type_gate([mutation, mutation], found, workers=1, deadline=time.monotonic()):\n"
        "    print(f'{verdict}: {last}')\n"
    )

    answered = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)

    assert answered.stdout.splitlines() == [
        "BEZ WERDYKTU: kod wyjścia 0 (brama typów, ruff: czas minął, zanim się zaczął, bez mutacji)",
        "WYKRYTA: kod wyjścia 1",
    ], answered.stdout + answered.stderr


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

    checked = mutacje.static_gate(tmp_path, limit_s=60, stop=threading.Event(), deadline=None)

    assert checked == mutacje.Checked(tuple(mutacje.Finding(*finding) for finding in findings))


def test_krok_bramy_typow_bez_wyniku_w_limicie_daje_kopie_bez_werdyktu(tmp_path: Path) -> None:
    """Krok, który wisi dłużej niż ``limit_s``, nie daje diagnostyk, więc brama nie wie, czy mutacja przeżyła: noc liczy
    BEZ WERDYKTU i sprawdza ją następnej nocy, zamiast zgłosić ją w issue."""

    (tmp_path / "ruff").mkdir()
    (tmp_path / "ruff" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "ruff" / "__main__.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")

    checked = mutacje.static_gate(tmp_path, limit_s=1, stop=threading.Event(), deadline=None)

    assert checked == mutacje.Checked((), "ruff: brak wyniku po 1 s")
