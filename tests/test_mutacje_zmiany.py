"""``tools/mutacje_zmiany.py`` psuje zmienione linie ``src/`` i ``tools/`` i pada, gdy żaden test tego nie widzi.

Przebiegi idą w małym repozytorium z narzędziami checkoutu: baza ma ``return a``, zmiana ``return a and b``.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tests.fixtures.brama_typow import FAKE_GATE, TYPE_GATE_ON_SRC, real_static_tools
from tests.fixtures.git_repo import commit, copy_files, git, repository, with_imports

from jednostka import Czesc
from mutacje_zmiany import Hunk, ZakresMutacji, exceptions, fingerprint, mutants, selected
import pokrycie_procesu

ROOT = Path(__file__).resolve().parents[1]
# Mutacje zmian z modułami, które importują, i pluginem pokrycia, który ładują w pytest po nazwie.
MUTACJE_ZMIANY = ("tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py")

MODULE = "src/rozliczenia/warunek.py"
BASE = 'def oba(a: bool, b: bool) -> bool:\n    return a\n'
CHANGED = 'def oba(a: bool, b: bool) -> bool:\n    return a and b\n'
ONE_CASE = "from rozliczenia.warunek import oba\n\n\ndef test_oba() -> None:\n    assert oba(True, True) is True\n"
ALL_CASES = (
    "from rozliczenia.warunek import oba\n\n\n"
    "def test_oba() -> None:\n"
    "    assert oba(True, True) is True\n"
    "    assert oba(True, False) is False\n"
    "    assert oba(False, True) is False\n"
)


def _repo(
    tmp_path: Path, test: str, changed: str = CHANGED, base: str = BASE, conftest: str = "", other: str = "", pyproject: str = ""
) -> Path:
    files = {".gitignore": "__pycache__/\n", "src/rozliczenia/__init__.py": "", MODULE: base, "tests/test_warunek.py": test}
    if pyproject:
        files["pyproject.toml"] = pyproject
    if conftest:
        files["tests/conftest.py"] = conftest
    if other:
        files["src/rozliczenia/inny.py"] = other
    repo = repository(tmp_path, files)
    copy_files(repo, with_imports(MUTACJE_ZMIANY))
    commit(repo, "baza")
    git(repo, "branch", "--quiet", "baza")
    (repo / MODULE).write_text(changed, encoding="utf-8")
    return repo


# Narzędzie z atrapą bramy typów (``FAKE_GATE``) zamiast kroków ruff i mypy; argumenty z wiersza poleceń.
FAKE_GATE_TOOL = f"import sys\nsys.path[:0] = ['tools', 'tools/lib']\nimport mutacje_zmiany\nimport silnik_mutacji\n{FAKE_GATE}\nraise SystemExit(mutacje_zmiany.main(gate=brama))\n"


def _run(
    repo: Path, *arguments: str, trial: bool = False, log: Path | None = None, fake_gate: bool = False
) -> subprocess.CompletedProcess[str]:
    """Wyjście narzędzia w ``stdout``, a z ``log`` w pliku ``log`` jak w CI, którego ścieżkę testy widzą w ``LOG_NARZEDZIA``;
    z ``fake_gate`` brama typów to atrapa ``FAKE_GATE``."""

    tool = ["-c", FAKE_GATE_TOOL] if fake_gate else [str(repo / "tools" / "mutacje_zmiany.py")]
    with log.open("w", encoding="utf-8") if log else contextlib.nullcontext() as output:
        return subprocess.run(
            [sys.executable, *tool, "--baza", "baza", "--rownolegle", "2", *arguments],
            cwd=repo,
            # Jeden worker xdist: testy biegną w kolejności z pliku, więc fixture sesji ustawia zawsze pierwszy z nich.
            # Narzędzie biegnie jak w zadaniu CI, bo poza nim odmawia startu (tools/lib/ciezkie_ci.py).
            env={
                **os.environ,
                "PYTEST_XDIST_AUTO_NUM_WORKERS": "1",
                "GITHUB_ACTIONS": "true",
                "MAXIMISEART_NA_SCALONYCH_PR": str(int(trial)),
                "LOG_NARZEDZIA": str(log),
            },
            stdout=output or subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )


def test_zmiana_bez_testu_ktory_ja_widzi_konczy_sie_fail_z_nazwa_mutacji_takze_w_zapisie_dla_scal_pr(tmp_path: Path) -> None:
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", ONE_CASE), "--zapis", str(record))

    assert done.returncode == 1, done.stdout + done.stderr
    survived = [line.removeprefix("NIEWYKRYTA: ").partition(" → ")[0] for line in done.stdout.splitlines() if line.startswith("NIEWYKRYTA")]
    assert sorted(survived) == ["src/rozliczenia/warunek.py:2 bez `b` w `and`", "src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy"]
    assert done.stdout.splitlines()[-1].startswith("MUTACJE ZMIANY FAIL | przeżyło 2")
    written = json.loads(record.read_text(encoding="utf-8"))
    assert (written["czesc"], written["kod"], written["wynik"]) == ("1/1", 1, done.stdout.splitlines()[-1])
    assert sorted((_named(entry), entry["linie"]) for entry in written["przezyte"]) == [(name, [2]) for name in sorted(survived)]
    assert len({entry["klucz"] for entry in written["przezyte"]}) == 2



@pytest.mark.parametrize(("koniec", "kod", "pliki"), [("warunek", 0, ["src/rozliczenia/warunek.py"]), ("inny", 1, ["src/rozliczenia/inny.py", "src/rozliczenia/warunek.py"])])
def test_czesc_nocy_z_zalegloscia_mutuje_tylko_zmiany_main_do_konca_zakresu_z_planu(tmp_path: Path, koniec: str, kod: int, pliki: list[str]) -> None:
    """Na ``main`` PR zmienia warunek (testy go widzą), a następny ``inny.py``, którego nie sprawdza żaden test."""

    repo = _repo(tmp_path / "repo", ALL_CASES, other="def inny() -> int:\n    return 1\n")
    commity = {"warunek": commit(repo, "Warunek (#1)")}
    (repo / "src" / "rozliczenia" / "inny.py").write_text("def inny() -> int:\n    return 2\n", encoding="utf-8")
    commity["inny"] = commit(repo, "Inny (#2)")

    done = _run(repo, "--do", commity[koniec])

    assert done.returncode == kod, done.stdout + done.stderr
    mutated = {line.split(": ", 1)[1].split(":", 1)[0] for line in done.stdout.splitlines() if line.startswith(("WYKRYTA: ", "NIEWYKRYTA: "))}
    assert sorted(mutated) == pliki


def _named(entry: dict[str, object]) -> str:
    """Nazwa mutacji wpisu zapisu części (``--zapis``), jak w linii ``NIEWYKRYTA``."""

    return f"{entry['plik']}:{entry['linia']} {entry['opis']}"


def _caught(done: subprocess.CompletedProcess[str]) -> list[str]:
    return [line.removeprefix("WYKRYTA: ").partition(" → ")[0] for line in done.stdout.splitlines() if line.startswith("WYKRYTA: ")]


@pytest.mark.parametrize("separator", [" ", "\x0c"], ids=["u2028", "form-feed"])
def test_czesc_nocy_mutuje_zmieniona_linie_za_linia_z_separatorem_ktory_nie_konczy_linii_gita(tmp_path: Path, separator: str) -> None:
    """``str.splitlines`` dzieli też na U+2028 i form feed, a git kończy linię tylko ``\\n``: zmieniona linia tuż za takim
    znakiem nie może dostać w ``git blame`` końcówki napisu zamiast commitu, bo wypadłaby z każdej nocy."""

    function = 'def oba(a: bool, b: bool) -> bool:\n    napis = "x{separator}y"\n    return {result}\n'
    repo = _repo(tmp_path / "repo", ALL_CASES, function.format(separator=separator, result="a and b"), function.format(separator=separator, result="a"))
    head = commit(repo, "Warunek (#1)")

    done = _run(repo, "--do", head)

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(_caught(done)) == ["src/rozliczenia/warunek.py:3 bez `b` w `and`", "src/rozliczenia/warunek.py:3 zmiana linii 3 cofnięta do bazy"]


def test_czesc_nocy_do_commitu_scalenia_mutuje_zmiane_z_galezi_pr(tmp_path: Path) -> None:
    """``main`` scala PR commitem scalenia, a linię zmienił commit gałęzi PR-u, którego nie ma na linii pierwszych rodziców."""

    repo = _repo(tmp_path / "repo", ALL_CASES)
    main = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "--quiet", "-b", "pr")
    commit(repo, "Warunek")
    git(repo, "checkout", "--quiet", main)
    git(repo, "merge", "--quiet", "--no-ff", "--message", "Merge pull request #1 from maximiseartai/pr", "pr")

    done = _run(repo, "--do", git(repo, "rev-parse", "HEAD"))

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(_caught(done)) == ["src/rozliczenia/warunek.py:2 bez `b` w `and`", "src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy"]


def test_mutacja_ktora_przezyla_testy_pliku_albo_nie_ma_testow_tez_trafia_do_zapisu(tmp_path: Path) -> None:
    other = "def inna() -> int:\n    return 1\n"
    third = "\n\ndef trzecia() -> int:\n    return 3\n"
    # ``test_trzecia`` wykonuje kod pliku, ale nie zmienionej linii, więc przeżyte mutacje biegną jeszcze z testami pliku.
    tests = ONE_CASE.replace("import oba", "import oba, trzecia") + "\n\ndef test_trzecia() -> None:\n    assert trzecia() == 3\n"
    repo = _repo(tmp_path / "repo", tests, CHANGED + third, BASE + third, other=other)
    (repo / "src" / "rozliczenia" / "inny.py").write_text(other.replace("1", "2"), encoding="utf-8")
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(repo, "--zapis", str(record))

    assert done.returncode == 1, done.stdout + done.stderr
    # Opis mutacji ``return`` też ma strzałkę, więc wynik testów oddziela ostatnia.
    survived = {line.removeprefix("NIEWYKRYTA: ").rpartition(" → ")[0]: line for line in done.stdout.splitlines() if line.startswith("NIEWYKRYTA")}
    assert sorted(survived) == [
        "src/rozliczenia/inny.py:2 `return 2` → `return None`",
        "src/rozliczenia/inny.py:2 zmiana linii 2 cofnięta do bazy",
        "src/rozliczenia/warunek.py:2 bez `b` w `and`",
        "src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy",
    ], done.stdout
    assert [line.endswith("żaden test nie zależy od src/rozliczenia/inny.py") for _, line in sorted(survived.items())] == [True, True, False, False]
    assert [line.endswith("(testy pliku)") for _, line in sorted(survived.items())] == [False, False, True, True]
    written = json.loads(record.read_text(encoding="utf-8"))["przezyte"]
    assert sorted(_named(entry) for entry in written) == sorted(survived)
    assert all(entry["linie"] == [2] and len(entry["klucz"]) == 12 for entry in written)

# Jak #674: zmiana dopisuje ``case`` brakującego wariantu, a gołe ``return`` po ``match`` w bazie robi to samo, więc testy
# przepuszczają cofnięcie, które odrzuca mypy (``exhaustive-match``). Jak #675: ``__all__`` nie czyta ani test, ani mypy.
MATCH_BASE = (
    "from enum import Enum\n\n__all__ = [\"Kolor\"]\n\n\n"
    "class Kolor(Enum):\n    CZERWONY = 1\n    ZIELONY = 2\n\n\n"
    "def nazwa(kolor: Kolor) -> str:\n    match kolor:\n        case Kolor.CZERWONY:\n            return \"czerwony\"\n    return \"zielony\"\n"
)
MATCH_CHANGED = MATCH_BASE.replace('["Kolor"]', '["Kolor", "nazwa"]').replace(
    '    return "zielony"\n', '        case Kolor.ZIELONY:\n            return "zielony"\n'
)
MATCH_TEST = (
    "from rozliczenia.warunek import Kolor, nazwa\n\n\n"
    "def test_nazwa() -> None:\n    assert [nazwa(kolor) for kolor in Kolor] == [\"czerwony\", \"zielony\"]\n"
)


def test_brama_typow_sprawdza_przezyte_mutacje_operatorow_a_cofniecie_do_bazy_trafia_do_zapisu(tmp_path: Path) -> None:
    """Bramę sprawdzają przeżyte mutacje operatorów, także z pliku bez testów; atrapa łapie linie z ``# brama:``.

    Cofnięcie przywraca kod bazy, który przeszedł bramę, więc jej błąd na nim (tu ``# brama:`` z bazy, jak #674 i #671)
    mówi tylko o niezgodności z resztą zmiany: cofnięcie trafia do zapisu, a brama go nie sprawdza.
    """

    record = tmp_path / "zapis" / "czesc.json"
    base = MATCH_BASE.replace('    return "zielony"\n', '    return "zielony"  # brama: mypy exhaustive-match\n')
    # Mutacje operatorów, które przeżywają testy linii (``zapas``) i testy pliku (``WOLNO`` czyta import modułu).
    changed = MATCH_CHANGED + "\n\ndef zapas() -> int:\n    return 1  # brama gdy None: mypy return-value\n\n\nWOLNO = False  # brama gdy True: mypy assignment\n"
    repo = _repo(tmp_path / "repo", MATCH_TEST, changed, base, other="def inna() -> int:\n    return 2  # brama: ruff F821\n")
    (repo / "src" / "rozliczenia" / "inny.py").write_text("def inna() -> int:\n    return 1  # brama gdy None: ruff F821\n", encoding="utf-8")

    done = _run(repo, "--zapis", str(record), fake_gate=True)

    assert done.returncode == 1, done.stdout + done.stderr
    caught = sorted(line for line in done.stdout.splitlines() if line.startswith("WYKRYTA PRZEZ BRAMĘ TYPÓW"))
    assert caught == [
        "WYKRYTA PRZEZ BRAMĘ TYPÓW: src/rozliczenia/inny.py:2 `return 1` → `return None` → ruff: src/rozliczenia/inny.py:2: F821",
        "WYKRYTA PRZEZ BRAMĘ TYPÓW: src/rozliczenia/warunek.py:20 `return 1` → `return None` → mypy: src/rozliczenia/warunek.py:20: return-value",
        "WYKRYTA PRZEZ BRAMĘ TYPÓW: src/rozliczenia/warunek.py:23 `False` → `True` → mypy: src/rozliczenia/warunek.py:23: assignment (testy pliku)",
    ], done.stdout
    assert re.search(r"\| brama typów \d+ s \(3 mutacji\)$", next(line for line in done.stdout.splitlines() if line.startswith("CZAS |"))), done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert sorted(_named(entry) for entry in written["przezyte"]) == [
        "src/rozliczenia/inny.py:2 zmiana linii 2 cofnięta do bazy",
        "src/rozliczenia/warunek.py:15 zmiana linii 15–23 cofnięta do bazy",
        "src/rozliczenia/warunek.py:3 zmiana linii 3 cofnięta do bazy",
    ]


def test_mutacja_ktorej_brama_typow_nie_sprawdzila_w_czasie_trafia_do_zapisu_jako_bez_werdyktu(tmp_path: Path) -> None:
    """Mutacja, która przeżyła testy, a której brama nie dała wyniku w czasie, nie jest ani przeżyta, ani wykryta: część
    kończy się kodem 3, a zapis wymienia ją w ``bez_werdyktu``, więc noc zgłasza ją do issue (ADR 0021).

    W nocach to najczęstsza droga do mutacji bez werdyktu (run 41285996039, części 11, 12 i 15: „brama typów, ruff: czas
    minął, zanim się zaczął”); tu krok atrapy bramy bez wyniku daje ``# brama gdy None: ruff późno``.
    """

    record = tmp_path / "zapis" / "czesc.json"
    changed = CHANGED + "\n\ndef zapas() -> int:\n    return 1  # brama gdy None: ruff późno\n"
    late = "src/rozliczenia/warunek.py:6 `return 1` → `return None`"

    done = _run(_repo(tmp_path / "repo", ALL_CASES, changed), "--zapis", str(record), fake_gate=True)

    assert done.returncode == 3, done.stdout + done.stderr
    assert f"BEZ WERDYKTU: {late} → brama typów, ruff: brak wyniku po 1 s" in done.stdout.splitlines(), done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["kod"] == 3
    assert written["wynik"].startswith("MUTACJE ZMIANY FAIL | limit czasu części 10500 s minął przed werdyktem 1 mutacji | "), written["wynik"]
    assert [_named(entry) for entry in written["bez_werdyktu"]] == [late]
    assert late not in [_named(entry) for entry in written["przezyte"]]


# Poprawka dodaje import w jednym fragmencie, a używa go w innym, i zmienną, którą zwraca; test przechodzi z nią i bez
# niej. Cofnięcie fragmentu z użyciem zostawia nieużyty import (ruff F401), a ``return wynik`` → ``return None``
# nieużytą zmienną (F841): oba przeżywają jak przed bramą (#703, runda 1 przeglądu #721).
GATE_BASE = MATCH_BASE + "\n\ndef wciety(tekst: str) -> str:\n    return tekst\n\n\ndef pierwszy(teksty: list[str]) -> str | None:\n    return None\n"
GATE_CHANGED = (
    MATCH_CHANGED.replace("from enum import Enum\n", "from enum import Enum\nimport textwrap\n")
    + "\n\ndef wciety(tekst: str) -> str:\n    return textwrap.dedent(tekst)\n\n\n"
    + "def pierwszy(teksty: list[str]) -> str | None:\n    wynik = teksty[0] if teksty else None\n    return wynik\n"
)
GATE_TEST = MATCH_TEST.replace("import Kolor, nazwa", "import Kolor, nazwa, pierwszy, wciety") + (
    "\n\ndef test_wciety() -> None:\n    assert wciety(\"a\") == \"a\"\n\n\ndef test_pierwszy() -> None:\n    assert pierwszy([]) is None\n"
)


@real_static_tools
def test_brama_typow_z_ruff_i_mypy_liczy_blad_mutacji_operatora_a_cofniecie_do_bazy_przezywa(tmp_path: Path) -> None:
    """Jedyny test z prawdziwymi ruff i mypy: ich JSON i kody, które brama liczy (``silnik_mutacji.wrong``).

    Cofnięcia, na których brama by padła (F821 jak #671, ``exhaustive-match`` jak #674, F401), przeżywają, bo brama ich
    nie sprawdza; ``return JEDEN`` → ``return None`` w funkcji ``-> int``, której nie sprawdza test, łapie tylko mypy.
    """

    record = tmp_path / "zapis" / "czesc.json"
    # Jak #671: cofnięcie definicji zostawia nazwę, której nie ma, w pliku bez testów.
    other = "def inna() -> int:\n    return 1\n"
    repo = _repo(tmp_path / "repo", GATE_TEST, GATE_CHANGED, GATE_BASE, other=other, pyproject=TYPE_GATE_ON_SRC)
    (repo / "src" / "rozliczenia" / "inny.py").write_text("JEDEN = 1\n\n\ndef inna() -> int:\n    return JEDEN\n", encoding="utf-8")

    done = _run(repo, "--zapis", str(record))

    caught = sorted(line for line in done.stdout.splitlines() if line.startswith("WYKRYTA PRZEZ BRAMĘ TYPÓW"))
    assert [re.sub(r"error: .*  \[", "error: …  [", line) for line in caught] == [
        "WYKRYTA PRZEZ BRAMĘ TYPÓW: src/rozliczenia/inny.py:5 `return JEDEN` → `return None` → mypy: src/rozliczenia/inny.py:5: error: …  [return-value]",
    ], done.stdout + done.stderr
    survived = [_named(entry) for entry in json.loads(record.read_text(encoding="utf-8"))["przezyte"]]
    assert {
        "src/rozliczenia/inny.py:1 zmiana linii 1–3 cofnięta do bazy",
        "src/rozliczenia/warunek.py:16 zmiana linii 16–17 cofnięta do bazy",
        "src/rozliczenia/warunek.py:21 zmiana linii 21 cofnięta do bazy",
        "src/rozliczenia/warunek.py:26 `return wynik` → `return None`",
    } <= set(survived), done.stdout


def test_czesc_konczy_sie_zapisem_w_limicie_czasu_czesci_takze_gdy_mutacja_zawiesza_testy(tmp_path: Path) -> None:
    # Noc 41019818658: część 5/20 nie zmieściła się w 60 min zadania CI, więc GitHub ją anulował bez zapisu.
    hangs = (
        "import time\n\nfrom rozliczenia.warunek import jeden, oba\n\n\n"
        "def test_oba() -> None:\n    while oba(True, False):\n        time.sleep(0.1)\n\n\n"
        "def test_jeden() -> None:\n    assert jeden() == 1\n"
    )
    # test_jeden wykonuje inny kod pliku, więc mutacja ma po testach linii jeszcze krok z testami pliku (#695).
    one = "\n\ndef jeden() -> int:\n    return 1\n"
    record = tmp_path / "zapis" / "czesc.json"

    # Bez limitu po pokryciu zawieszona mutacja kończy się po ``--limit-s`` przekroczonym czasem (kod 1), a nie wiesza
    # testu; z nim ``--limit-s`` nie mija pierwszy, bo mutacja startuje po końcu pokrycia, od którego liczy się limit.
    arguments = ("--rownolegle", "1", "--limit-po-pokryciu-s", "15", "--limit-s", "20", "--zapis", str(record))
    done = _run(_repo(tmp_path / "repo", hangs, CHANGED + one, BASE + one), *arguments)

    assert done.returncode == 3, done.stdout + done.stderr
    verdicts = [line for line in done.stdout.splitlines() if " → " in line]
    # Pierwsza mutacja zawiesza testy do końca czasu części, więc druga już się nie zaczyna, a mutacja bez werdyktu
    # nie biegnie w dalszym kroku, więc każda ma jedną linię i liczy się raz.
    assert len(verdicts) == 2 and verdicts[0].startswith("BEZ WERDYKTU: src/rozliczenia/warunek.py:2 bez `b` w `and` → brak wyniku po "), done.stdout
    assert verdicts[1] == "BEZ WERDYKTU: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy → czas minął, zanim się zaczęła", done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["wynik"] == "MUTACJE ZMIANY FAIL | limit czasu części 15 s po pokryciu minął przed werdyktem 2 mutacji | przeżyło 0 | mutacje=2 | wyjątki=0 | innego systemu=0"
    # Testy zawieszone do końca czasu części to nie przeżyta mutacja, ale noc zgłasza ją jako mutację bez werdyktu.
    assert written["przezyte"] == []
    assert [(_named(entry), entry["linie"]) for entry in written["bez_werdyktu"]] == [
        ("src/rozliczenia/warunek.py:2 bez `b` w `and`", [2]),
        ("src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy", [2]),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="linię Failed: Timeout drukuje metoda signal pytest-timeout, a noc biegnie na Linuksie")
@pytest.mark.parametrize("further", [False, True], ids=["ostatni-krok", "z-dalszymi-krokami"])
def test_mutacja_ktora_wiesza_test_do_limitu_pytest_timeout_jest_wykryta_a_nie_przezyta(tmp_path: Path, further: bool) -> None:
    # Przegląd #711: test skończony przez pytest-timeout czerwieni zadanie CI, więc noc nie zakłada o nim issue.
    hangs = (
        "import time\n\nimport pytest\n\nfrom rozliczenia.warunek import oba\n\n\n"
        "@pytest.mark.timeout(3)\ndef test_oba() -> None:\n    assert oba(True, True) is True\n    while oba(True, False):\n        time.sleep(0.1)\n"
    )
    # Bez test_jeden testy linii to jedyny krok kolejki. Z nim, a test_jeden wykonuje inny kod pliku, mutacja, której
    # testy linii nie złapały, biegnie dalej z linią „(testy pliku)”.
    one = "\n\ndef jeden() -> int:\n    return 1\n" if further else ""
    if further:
        hangs = hangs.replace("import oba", "import jeden, oba") + "\n\ndef test_jeden() -> None:\n    assert jeden() == 1\n"
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", hangs, CHANGED + one, BASE + one), "--rownolegle", "1", "--zapis", str(record))

    assert done.returncode == 0, done.stdout + done.stderr
    hang = "→ Failed: Timeout (>3.0s) from pytest-timeout. (liczona jako wykryta: pytest-timeout czerwieni test w CI)"
    assert [line for line in done.stdout.splitlines() if " → " in line] == [
        f"ZAWIESZENIE: src/rozliczenia/warunek.py:2 bez `b` w `and` {hang}",
        f"ZAWIESZENIE: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy {hang}",
    ], done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert (written["kod"], written["wynik"], written["przezyte"]) == (0, "MUTACJE ZMIANY OK | mutacje=2 | wyjątki=0 | innego systemu=0", [])


@pytest.mark.parametrize("further", [False, True], ids=["ostatni-krok", "z-dalszymi-krokami"])
def test_mutacja_ktora_tylko_spowalnia_test_ponad_limit_narzedzia_nie_jest_wykryta_a_trafia_do_zapisu_z_przekroczonym_czasem(
    tmp_path: Path, further: bool
) -> None:
    """Przegląd #711, runda 2: test kończy się w CI, bo pytest-timeout go nie przerywa, więc mutacja nie jest wykryta
    (ADR 0021). Noc nie wie jednak, czy test by ją złapał, więc zapis ma ją w ``przekroczony_czas``, a nie w przeżytych
    (#1339)."""

    slow = "import time\n\n" + ONE_CASE + "    if oba(True, False):\n        time.sleep(30)\n"
    # Z test_jeden, który wykonuje inny kod pliku, mutacja po przekroczonym czasie testów linii biegnie dalej z testami
    # pliku, z linią o tym w logu, i dopiero tam kończy się przekroczonym czasem (#695).
    one = "\n\ndef jeden() -> int:\n    return 1\n" if further else ""
    if further:
        slow = slow.replace("import oba", "import jeden, oba") + "\n\ndef test_jeden() -> None:\n    assert jeden() == 1\n"
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", slow, CHANGED + one, BASE + one), "--limit-s", "8", "--zapis", str(record))

    assert done.returncode == 1, done.stdout + done.stderr
    late = "→ brak wyniku po 8 s (limit --limit-s narzędzia, nie pytest-timeout)"
    names = ["src/rozliczenia/warunek.py:2 bez `b` w `and`", "src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy"]
    lines = [line for line in done.stdout.splitlines() if " → " in line]
    if further:
        lines_pass = [f"PRZEKROCZONY CZAS: {name} {late} (testy linii), biegnie dalej z szerszymi testami" for name in names]
        assert sorted(lines[:2]) == lines_pass, done.stdout
        lines = lines[2:]
    assert lines == [f"PRZEKROCZONY CZAS: {name} {late}" + (" (testy pliku)" if further else "") for name in names], done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["wynik"].startswith("MUTACJE ZMIANY FAIL | przeżyło 0 | przekroczony czas 2 | "), written["wynik"]
    assert (written["przezyte"], sorted(_named(entry) for entry in written["przekroczony_czas"])) == ([], names)


def test_mutacja_ktora_test_pliku_lapie_po_limicie_czasu_calego_zbioru_trafia_do_zapisu_z_przekroczonym_czasem_a_nie_jako_przezyta(
    tmp_path: Path,
) -> None:
    """Jak #1265 i #1279: zbiór testów pliku bez mutacji mieści się w ``--limit-s``, a po mutacji test, który ją łapie,
    pada dopiero po limicie całego polecenia. ``PRZEKROCZONY CZAS`` nie mówi więc, że test jej nie łapie (#1339)."""

    # Stałą czyta test, który nie wykonał kodu pliku, więc jej mutację sprawdza dopiero drugi przebieg z testami pliku.
    tests = (
        "import subprocess\nimport sys\nimport time\n\nimport rozliczenia.warunek as warunek\n\n\n"
        "def test_import_w_procesie() -> None:\n    subprocess.run([sys.executable, '-c', 'import rozliczenia.warunek'], check=True)\n\n\n"
        "def test_stala() -> None:\n    if warunek.LIMIT != 5:\n        time.sleep(60)\n    assert warunek.LIMIT == 5\n"
    )
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", tests, "LIMIT = 5\n", "LIMIT = 3\n"), "--limit-s", "10", "--zapis", str(record))

    assert done.returncode == 1, done.stdout + done.stderr
    name = "src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy"
    late = f"PRZEKROCZONY CZAS: {name} → brak wyniku po 10 s (limit --limit-s narzędzia, nie pytest-timeout) (testy pliku)"
    assert [line for line in done.stdout.splitlines() if " → " in line] == [late], done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["wynik"] == "MUTACJE ZMIANY FAIL | przeżyło 0 | przekroczony czas 1 | mutacje=1 | wyjątki=0 | innego systemu=0"
    assert (written["przezyte"], [_named(entry) for entry in written["przekroczony_czas"]]) == ([], [name])


def test_mutacja_ktora_zawiesza_dopiero_testy_pliku_konczy_sie_bez_werdyktu_w_limicie_czasu_czesci(tmp_path: Path) -> None:
    # Stałą czyta test, który nie wykonał kodu pliku, więc jej mutację sprawdza dopiero drugi przebieg z testami pliku.
    tests = (
        "import subprocess\nimport sys\nimport time\n\nimport rozliczenia.warunek as warunek\n\n\n"
        "def test_import_w_procesie() -> None:\n    subprocess.run([sys.executable, '-c', 'import rozliczenia.warunek'], check=True)\n\n\n"
        "def test_stala() -> None:\n    while warunek.LIMIT != 5:\n        time.sleep(0.1)\n"
    )
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", tests, "LIMIT = 5\n", "LIMIT = 3\n"), "--limit-po-pokryciu-s", "15", "--limit-s", "20", "--zapis", str(record))

    assert done.returncode == 3, done.stdout + done.stderr
    verdict = next(line for line in done.stdout.splitlines() if " → " in line)
    assert verdict.startswith("BEZ WERDYKTU: src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy → ") and verdict.endswith(" (testy pliku)"), done.stdout
    written = json.loads(record.read_text(encoding="utf-8"))
    assert (written["przezyte"], [_named(entry) for entry in written["bez_werdyktu"]]) == ([], ["src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy"])


@pytest.mark.skipif(sys.platform == "win32", reason="linię Failed: Timeout drukuje metoda signal pytest-timeout, a noc biegnie na Linuksie")
def test_mutacja_ktora_wiesza_dopiero_test_pliku_do_limitu_pytest_timeout_jest_wykryta(tmp_path: Path) -> None:
    # Stałą czyta test, który nie wykonał kodu pliku, więc zawieszenie wychodzi dopiero w przebiegu z testami pliku.
    tests = (
        "import subprocess\nimport sys\nimport time\n\nimport pytest\n\nimport rozliczenia.warunek as warunek\n\n\n"
        "def test_import_w_procesie() -> None:\n    subprocess.run([sys.executable, '-c', 'import rozliczenia.warunek'], check=True)\n\n\n"
        "@pytest.mark.timeout(3)\ndef test_stala() -> None:\n    while warunek.LIMIT != 5:\n        time.sleep(0.1)\n"
    )
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", tests, "LIMIT = 5\n", "LIMIT = 3\n"), "--zapis", str(record))

    assert done.returncode == 0, done.stdout + done.stderr
    hang = "→ Failed: Timeout (>3.0s) from pytest-timeout. (liczona jako wykryta: pytest-timeout czerwieni test w CI) (testy pliku)"
    assert f"ZAWIESZENIE: src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy {hang}" in done.stdout.splitlines(), done.stdout
    assert json.loads(record.read_text(encoding="utf-8"))["przezyte"] == []


# Limit mutacji części liczony od końca pokrycia; mutacje z testami, które padają od razu, trwały na Macu 0,56–1,10 s przy
# load 16–77, ponad 13 razy krócej (#1461).
LIMIT_PO_POKRYCIU_S = 15


def test_limit_po_pokryciu_liczy_czas_mutacji_od_konca_pokrycia_wiec_wolne_pokrycie_nie_zabiera_go_mutacjom(tmp_path: Path) -> None:
    """#1461: pokrycie pod obciążeniem trwa kilka razy dłużej, a limit liczony od startu kończył część przed mutacjami,
    choć kod był poprawny. Tu testy bez mutacji śpią cały limit, a po każdej mutacji padają na asercji przed snem."""

    slow = "import time\n\n" + ALL_CASES + f"    time.sleep({LIMIT_PO_POKRYCIU_S})\n"
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", slow), "--limit-po-pokryciu-s", str(LIMIT_PO_POKRYCIU_S), "--zapis", str(record))

    assert (done.returncode, done.stdout.splitlines()[-1]) == (0, "MUTACJE ZMIANY OK | mutacje=2 | wyjątki=0 | innego systemu=0"), done.stdout + done.stderr


def test_czesc_z_testem_zawieszonym_bez_mutacji_konczy_sie_zapisem_w_limicie_czasu_czesci(tmp_path: Path) -> None:
    hangs = "import time\n\n" + ONE_CASE + "\n\ndef test_zawieszony() -> None:\n    while True:\n        time.sleep(0.1)\n"
    record = tmp_path / "zapis" / "czesc.json"

    done = _run(_repo(tmp_path / "repo", hangs), "--limit-czesci-s", "5", "--zapis", str(record))

    # Testy, które bez mutacji nie kończą się w limicie części, to porażka części, a nie mutacje bez werdyktu.
    assert done.returncode == 2, done.stdout + done.stderr
    written = json.loads(record.read_text(encoding="utf-8"))
    assert (written["wynik"], written["przezyte"], written["bez_werdyktu"]) == (
        "MUTACJE ZMIANY FAIL | limit czasu części 5 s minął w pokryciu, przed werdyktem 2 mutacji",
        [],
        [],
    )


@pytest.mark.parametrize(
    ("changed", "arguments", "verdict"),
    [
        (CHANGED.replace("and b", "and b  # mutacje-zmiany: bez terminu"), (), "MUTACJE ZMIANY FAIL | src/rozliczenia/warunek.py:2: wyjątek musi mieć postać"),
        (CHANGED, ("--baza", "nie-ma-takiej"), "MUTACJE ZMIANY FAIL | nieznana baza nie-ma-takiej"),
    ],
    ids=["zly-wyjatek", "nieznana-baza"],
)
def test_porazka_bez_wyniku_mutacji_ma_inny_kod_niz_przezyte_mutacje(tmp_path: Path, changed: str, arguments: tuple[str, ...], verdict: str) -> None:
    # Nocna część zostawia kod 1 przeżytych mutacji zgłoszeniu, a każdą inną porażką czerwieni się (mutacje-nocne.yml).
    done = _run(_repo(tmp_path, ONE_CASE, changed), *arguments)

    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1].startswith(verdict)


def test_klucz_mutacji_nie_zalezy_od_jej_linii_a_rozroznia_mutacje() -> None:
    hunk = Hunk(2, 1, ("    return a",))
    found = selected(MODULE, CHANGED, [hunk])
    shifted = "# opis\n\n" + CHANGED
    moved = selected(MODULE, shifted, [Hunk(4, 1, ("    return a",))])

    assert [mutant.line for mutant in moved] == [mutant.line + 2 for mutant in found]
    keys = [fingerprint(mutant, CHANGED) for mutant in found]
    assert [fingerprint(mutant, shifted) for mutant in moved] == keys
    assert len(set(keys)) == len(keys) == 2


def test_zmiana_z_testami_ktore_widza_kazda_mutacje_konczy_sie_ok(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ALL_CASES))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "NIEWYKRYTA" not in done.stdout
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | mutacje=2 | wyjątki=0 | innego systemu=0"


def test_liczbe_mutacji_widac_w_logu_ci_zanim_pobiegna_testy(tmp_path: Path) -> None:
    # Log CI to plik, więc linia bez ``flush`` czekałaby w buforze przez cały pierwszy przebieg testów.
    line = "Mutacje: 2 w 1 plikach src/ i tools/ od baza. Testy dotknięte zmianą: 1."
    reads_log = f"\n\ndef test_log() -> None:\n    assert {line!r} in Path(os.environ['LOG_NARZEDZIA']).read_text(encoding='utf-8')\n"
    log = tmp_path / "log.txt"

    done = _run(_repo(tmp_path / "repo", "import os\nfrom pathlib import Path\n" + ALL_CASES + reads_log), log=log)

    assert done.returncode == 0, log.read_text(encoding="utf-8") + done.stderr


def test_werdykt_mutacji_z_testami_pliku_widac_w_logu_ci_zanim_pobiegnie_nastepna(tmp_path: Path) -> None:
    # Testy pliku to często tysiące testów na mutację, a po nich biegnie jeszcze brama typów, więc werdykt bez ``flush``
    # czekałby w buforze, a anulowane zadanie CI (noc 41019818658) nie zostawiłoby go w logu.
    tests = (
        "import os\nfrom pathlib import Path\nimport subprocess\nimport sys\n\nimport rozliczenia.warunek as warunek\n\n\n"
        "def test_import_w_procesie() -> None:\n    subprocess.run([sys.executable, '-c', 'import rozliczenia.warunek'], check=True)\n\n\n"
        "def test_a() -> None:\n    assert warunek.A == 2\n\n\n"
        "def test_b() -> None:\n"
        "    if warunek.B != 2:\n"
        "        log = Path(os.environ['LOG_NARZEDZIA'])\n"
        "        log.with_name('log-przy-drugiej-mutacji.txt').write_text(log.read_text(encoding='utf-8'), encoding='utf-8')\n"
        "    assert warunek.B == 2\n"
    )
    # Stałe czytają testy, które nie wykonały kodu pliku, więc obie mutacje sprawdza dopiero przebieg z testami pliku, po kolei.
    log = tmp_path / "log.txt"

    done = _run(_repo(tmp_path / "repo", tests, "A = 2\n\n\nB = 2\n", "A = 1\n\n\nB = 1\n"), log=log)

    assert done.returncode == 0, log.read_text(encoding="utf-8") + done.stderr
    seen = (tmp_path / "log-przy-drugiej-mutacji.txt").read_text(encoding="utf-8").splitlines()
    first = [line for line in seen if line.startswith("WYKRYTA: src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy → ")]
    assert len(first) == 1 and first[0].endswith(" (testy pliku)"), seen


def test_czesci_dziela_mutacje_miedzy_siebie(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE)

    parts = [_run(repo, "--czesc", f"{number}/2") for number in (1, 2)]

    names = [{line.split(" → ")[0].split(": ", 1)[1] for line in done.stdout.splitlines() if "WYKRYTA: " in line} for done in parts]
    assert len(names[0]) == len(names[1]) == 1, [done.stdout for done in parts]
    assert not names[0] & names[1]


def test_czesc_bierze_kolejne_mutacje_wiec_pokrycie_biegnie_na_testach_mniejszej_liczby_plikow(tmp_path: Path) -> None:
    # Noc mutuje zmiany wielu PR-ów; co N-ta mutacja dałaby każdej części testy wszystkich zmienionych plików.
    repo = _repo(tmp_path, ONE_CASE, other="def inny(a: bool, b: bool) -> bool:\n    return a\n")
    (repo / "src" / "rozliczenia" / "inny.py").write_text("def inny(a: bool, b: bool) -> bool:\n    return a or b\n", encoding="utf-8")

    parts = [_run(repo, "--czesc", f"{number}/2") for number in (1, 2)]

    counted = [next(line for line in done.stdout.splitlines() if line.startswith("Mutacje: ")) for done in parts]
    assert [line.partition(" od ")[0] for line in counted] == [f"Mutacje: 2 (część {number}/2 z 4) w 1 plikach src/ i tools/" for number in (1, 2)]


FUNKCJA = "def a(x: int) -> bool:\n    return x > 1\n"


def _dopisz(repo: Path, subject: str, *names: str) -> str:
    """Commit, który dopisuje funkcję do każdego ``src/pakiet/<nazwa>.py``: dwie mutacje, granica porównania i cofnięcie."""

    for name in names:
        with (repo / "src" / "pakiet" / f"{name}.py").open("a", encoding="utf-8") as code:
            code.write(f"\n\ndef {subject}_{name}(x: int) -> bool:\n    return x < 3\n")
    return commit(repo, subject)


def _historia_zakresu(tmp_path: Path) -> tuple[Path, str, list[str]]:
    """``main`` z bazą i czterema commitami: bez mutacji (README), 2 mutacje w ``m1``, 4 w ``m2`` i ``m3`` i druga funkcja
    w ``m1`` tuż za pierwszą. Cofnięcie fragmentu ``m1`` psuje wtedy linie obu commitów, więc wchodzi do zakresu z
    pierwszym, a ostatni commit ma już tylko granicę porównania: razem 7 mutacji."""

    repo = repository(tmp_path / "repo", {"README.md": "repozytorium\n", **{f"src/pakiet/m{number}.py": FUNKCJA for number in (1, 2, 3)}})
    base = commit(repo, "baza")
    (repo / "README.md").write_text("repozytorium z historią\n", encoding="utf-8")
    commits = [commit(repo, "readme")]
    commits += [_dopisz(repo, "pierwszy", "m1"), _dopisz(repo, "drugi", "m2", "m3"), _dopisz(repo, "trzeci", "m1")]
    return repo, base, commits


def test_czesci_zakresu_skladaja_sie_w_kolejnosci_plikow_i_linii_na_cala_liste_mutacji_kazda_raz(tmp_path: Path) -> None:
    repo, base, _ = _historia_zakresu(tmp_path)

    zakres = ZakresMutacji.od(base, repo)

    assert len(zakres.mutanty) == 7
    assert [(mutant.path, mutant.line) for mutant in zakres.mutanty] == sorted((mutant.path, mutant.line) for mutant in zakres.mutanty)
    for count in range(1, len(zakres.mutanty) + 2):
        parts = [list(zakres.czesc(czesc)) for czesc in Czesc.calosc(count)]
        assert [mutant for part in parts for mutant in part] == list(zakres.mutanty), count
        # Plan daje tyle części, ile trzeba na jego mutacje, więc żadna z nich nie może zostać pusta.
        assert all(parts) or count > len(zakres.mutanty)


@pytest.mark.parametrize(
    ("limit", "end", "inside"),
    [(0, 1, 2), (1, 1, 2), (2, 1, 2), (5, 1, 2), (6, 2, 6), (7, 3, 7), (100, 3, 7)],
)
def test_koniec_nocy_to_najdalszy_commit_do_ktorego_zakres_miesci_limit_a_co_najmniej_pierwszy_z_mutacjami(
    tmp_path: Path, limit: int, end: int, inside: int
) -> None:
    """Zakres do kolejnych commitów ma 0, 2, 6 i 7 mutacji, więc limit mniejszy niż 2 i tak daje noc do pierwszego commitu
    z mutacjami."""

    repo, base, commits = _historia_zakresu(tmp_path)
    caly = ZakresMutacji.od(base, repo)

    koniec = caly.najdalszy_koniec(limit)

    assert (commits.index(koniec), len(caly.do(koniec).mutanty)) == (end, inside)


def test_mutacje_linii_ktora_blame_przypisuje_commitowi_sprzed_bazy_licza_sie_do_konca_nocy_od_pierwszego_commitu(tmp_path: Path) -> None:
    """Diff od bazy widzi przeniesioną linię ``a`` jako dodaną, a ``git blame`` przypisuje ją bazie: każdy zakres ``do``
    zawiera jej mutacje, więc koniec nocy liczy je od pierwszego commitu, a nie pomija."""

    repo = repository(tmp_path / "repo", {"README.md": "repozytorium\n"})
    # Baza nie jest pierwszym commitem: ``git blame -l`` drukuje go jako granicę ``^`` bez ostatniego znaku skrótu.
    commit(repo, "pierwszy")
    (repo / "src" / "pakiet").mkdir(parents=True)
    (repo / "src" / "pakiet" / "m.py").write_text("a = 1 > 0\nb = 2 > 0\n", encoding="utf-8")
    (repo / "src" / "pakiet" / "n.py").write_text(FUNKCJA, encoding="utf-8")
    base = commit(repo, "baza")
    (repo / "src" / "pakiet" / "m.py").write_text("b = 2 > 0\na = 1 > 0\nb = 2 > 0\n", encoding="utf-8")
    commit(repo, "b także przed a")
    (repo / "src" / "pakiet" / "m.py").write_text("b = 2 > 0\na = 1 > 0\n", encoding="utf-8")
    przed_trzecim = commit(repo, "bez drugiego b")
    _dopisz(repo, "trzeci", "n")
    caly = ZakresMutacji.od(base, repo)
    sprzed_bazy = [mutant for mutant in caly.mutanty if mutant.path == "src/pakiet/m.py"]
    assert sprzed_bazy
    assert [mutant.lines for mutant in sprzed_bazy] == [frozenset({2})] * len(sprzed_bazy)

    koniec = caly.najdalszy_koniec(len(sprzed_bazy))

    assert (koniec, caly.do(koniec).mutanty) == (przed_trzecim, tuple(sprzed_bazy))


@pytest.mark.parametrize(("comment", "parts"), [("# mutacje-zmiany: bez terminu", 1),("# mutacje-zmiany: na próbę | do 2999-01-01 | zgoda Maks", 0)])
def test_zly_wyjatek_daje_czesc_ktora_go_zglosi_takze_bez_mutacji(tmp_path: Path, comment: str, parts: int) -> None:
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": FUNKCJA})
    base = commit(repo, "baza")
    (repo / "src" / "pakiet" / "a.py").write_text(f"{FUNKCJA}{comment}\n", encoding="utf-8")
    head = commit(repo, "komentarz")

    zakres = ZakresMutacji.od(base, repo)

    shape = "src/pakiet/a.py:3: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`"
    assert (zakres.mutanty, zakres.zly_wyjatek) == ((), shape if parts else None)
    assert (zakres.liczba_czesci(24), zakres.do(head).liczba_czesci(24)) == (parts, parts)


@pytest.mark.parametrize("trial", [True, False], ids=["proba-na-scalonych-pr", "noc"])
def test_narzedzie_podmienione_przez_probe_na_scalonych_pr_jest_niesprawdzone_a_nie_zmiana_zakresu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trial: bool
) -> None:
    """Commit zmienia ``tools/narzedzie.py``, a próba podstawiła w jego miejscu narzędzie z checkoutu (zmiana w drzewie)."""

    repo = repository(tmp_path / "repo", {"tools/narzedzie.py": FUNKCJA})
    base = commit(repo, "baza")
    (repo / "tools" / "narzedzie.py").write_text(FUNKCJA.replace("x > 1", "x > 2"), encoding="utf-8")
    commit(repo, "zmiana narzędzia")
    (repo / "tools" / "narzedzie.py").write_text(FUNKCJA.replace("x > 1", "x > 5"), encoding="utf-8")
    monkeypatch.setenv("MAXIMISEART_NA_SCALONYCH_PR", str(int(trial)))

    zakres = ZakresMutacji.od(base, repo)

    paths = {mutant.path for mutant in zakres.mutanty}
    assert (zakres.niesprawdzone, paths) == ((("tools/narzedzie.py",), set()) if trial else ((), {"tools/narzedzie.py"}))


def test_wyjatek_w_linii_mutacji_ja_pomija_a_wygasly_juz_nie(tmp_path: Path) -> None:
    allowed = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n")
    expired = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2000-01-01 | zgoda Maks\n")

    excused = _run(_repo(tmp_path / "wazny", ONE_CASE, allowed))
    stale = _run(_repo(tmp_path / "wygasly", ONE_CASE, expired))

    assert excused.returncode == 0, excused.stdout + excused.stderr
    assert "WYJĄTEK: src/rozliczenia/warunek.py:2 bez `b` w `and` (tylko na próbę, do 2999-01-01, zgoda Maks)" in excused.stdout
    assert stale.returncode == 1, stale.stdout + stale.stderr


def test_mutacje_kodu_sprawdzanego_tylko_w_podprocesie_wykrywa_juz_pierwszy_przebieg(tmp_path: Path) -> None:
    base = BASE + "\n\ndef dwa() -> int:\n    return 1\n"
    changed = CHANGED + "\n\ndef dwa() -> int:\n    return 2\n"
    in_subprocess = (
        "import subprocess\nimport sys\n\n\n"
        "def test_z_podprocesu() -> None:\n"
        "    code = 'from rozliczenia.warunek import dwa; assert dwa() == 2'\n"
        "    subprocess.run([sys.executable, '-c', code], check=True)\n"
    )

    tests = "import subprocess\nimport sys\n" + ALL_CASES + "\n\n" + in_subprocess.replace("import subprocess\nimport sys\n\n\n", "")

    done = _run(_repo(tmp_path, tests, changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    found = next(line for line in done.stdout.splitlines() if "warunek.py:6 `return 2` → `return None`" in line)
    # Tylko test podprocesu: pozostałe testy pliku (``test_oba``) w pierwszym przebiegu nie biegną.
    assert found.startswith("WYKRYTA: ") and "→ 1 failed in" in found, done.stdout


def test_mutacje_kodu_w_procesie_z_flaga_izolacji_wykrywa_test_ktory_go_uruchomil(tmp_path: Path) -> None:
    base = BASE + "\n\ndef dwa() -> int:\n    return 1\n"
    changed = CHANGED + "\n\ndef dwa() -> int:\n    return 2\n"
    isolated = (
        "\n\ndef test_dwa_w_izolowanym_procesie() -> None:\n"
        "    code = 'import sys; sys.path.insert(0, \"src\"); from rozliczenia.warunek import dwa; assert dwa() == 2'\n"
        "    subprocess.run([sys.executable, '-I', '-c', code], check=True)\n"
    )

    done = _run(_repo(tmp_path, "import subprocess\nimport sys\n" + ALL_CASES + isolated, changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:6 `return 2` → `return None`" in done.stdout


INNE = "def oba(a: bool, b: bool) -> bool:\n    return a and b\n"
# Tak jak tools/ci_lokalnie.py nazywa tools/mutacje_zmiany.py, a git_repo.py kopiuje tools/ci_lokalnie.py.
KROKI = 'KROK = "tools/pomoc/inne.py"\n'
KROKI_TEST = "import subprocess\n\nNARZEDZIE = '{tool}'\n\n\ndef test_krok() -> None:\n    subprocess.run(['git', '--version'], check=True, capture_output=True)\n"


def _isolated(reference: str, call: str = "oba(True, True)") -> str:
    """Test, który dochodzi do ``tools/pomoc/inne.py`` przez ``reference`` i wywołuje ``call`` w procesie z ``-I``."""

    return (
        f"import subprocess\nimport sys\n\n{reference}\n\n\n"
        "def test_oba_w_izolowanym_procesie() -> None:\n"
        f"    code = f'import runpy; assert runpy.run_path({{SKRYPT!r}})[\"oba\"]{call.removeprefix('oba')}'\n"
        "    subprocess.run([sys.executable, '-I', '-c', code], check=True)\n"
    )


@pytest.mark.parametrize(
    ("reference", "helper", "tool"),
    [
        ("SKRYPT = 'tools/pomoc/inne.py'", "", "tools/kroki.py"),
        ("from pathlib import Path\nSKRYPT = str(sorted(Path('tools').glob('pomoc/*.py'))[0])", "", "tools/kroki.py"),
        ("from pomocnik import SKRYPT", "SKRYPT = 'tools/pomoc/inne.py'\n", "tools/kroki.py"),
        # Narzędzie w folderze ``tests/`` pod ``tools/`` nie jest plikiem testów: jego nazwy plików też się nie liczą.
        ("SKRYPT = 'tools/pomoc/inne.py'", "", "tools/tests/kroki.py"),
    ],
)
def test_kodu_procesu_nie_sprawdza_test_z_procesem_ktory_dochodzi_do_pliku_tylko_przez_inne_narzedzie(
    tmp_path: Path, reference: str, helper: str, tool: str
) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "tools" / "pomoc").mkdir()
    (repo / "tools" / "pomoc" / "inne.py").write_text(INNE, encoding="utf-8")
    (repo / tool).parent.mkdir(exist_ok=True)
    (repo / tool).write_text(KROKI, encoding="utf-8")
    (repo / "tests" / "test_a_kroki.py").write_text(KROKI_TEST.format(tool=tool), encoding="utf-8")
    (repo / "tests" / "test_inne.py").write_text(_isolated(reference), encoding="utf-8")
    if helper:
        (repo / "tests" / "pomocnik.py").write_text(helper, encoding="utf-8")

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    survived = next(line for line in done.stdout.splitlines() if line.startswith("NIEWYKRYTA: tools/pomoc/inne.py:2 bez `b` w `and`"))
    # Tylko test, który dochodzi do pliku importem, nazwą albo globem; test kroków (git) w tym przebiegu nie biegnie.
    assert "→ 1 passed in" in survived, done.stdout


def test_kod_procesu_sprawdza_test_narzedzia_ktore_wykonalo_kod_pliku(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "tools" / "pomoc").mkdir()
    (repo / "tools" / "pomoc" / "inne.py").write_text(INNE, encoding="utf-8")
    # Narzędzie wykonuje kod pliku u siebie (zapis to widzi), a jego funkcję w procesie z -I (tego zapis nie widzi).
    (repo / "tools" / "kroki.py").write_text(
        "from pathlib import Path\nimport runpy\nimport subprocess\nimport sys\n\n"
        + KROKI
        + "runpy.run_path(str(Path(KROK).resolve()))\n"
        "code = f'import runpy; assert runpy.run_path({KROK!r})[\"oba\"](True, False) is False'\n"
        "subprocess.run([sys.executable, '-I', '-c', code], check=True)\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_a_kroki.py").write_text(
        "import subprocess\nimport sys\n\nNARZEDZIE = 'tools/kroki.py'\n\n\n"
        "def test_krok() -> None:\n    subprocess.run([sys.executable, NARZEDZIE], check=True)\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_inne.py").write_text(_isolated("SKRYPT = 'tools/pomoc/inne.py'"), encoding="utf-8")

    done = _run(repo)

    assert any(line.startswith("WYKRYTA: tools/pomoc/inne.py:2 bez `b` w `and`") for line in done.stdout.splitlines()), done.stdout + done.stderr


def test_mutacje_stalej_modulu_wykrywa_test_innego_modulu_ktory_ja_czyta_przy_imporcie(tmp_path: Path) -> None:
    base = "LIMIT = 3\n\n\ndef nazwa() -> str:\n    return 'a'\n"
    other = "from rozliczenia.warunek import LIMIT\n\n\ndef duze(n: int) -> bool:\n    return n > LIMIT\n"
    changed = base.replace("LIMIT = 3", "LIMIT = 5").replace("return 'a'", "return 'b'")
    tests = (
        "from rozliczenia.inny import duze\nfrom rozliczenia.warunek import nazwa\n\n\n"
        "def test_nazwa() -> None:\n    assert nazwa() == 'b'\n\n\n"
        "def test_duze() -> None:\n    assert duze(4) is False\n    assert duze(6) is True\n"
    )

    done = _run(_repo(tmp_path, tests, changed, base, other=other))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:1 zmiana linii 1 cofnięta do bazy" in done.stdout


def test_mutacje_kodu_fixture_sesji_wykrywa_test_ktory_tylko_dostal_jej_wynik(tmp_path: Path) -> None:
    base = "def wartosc() -> int:\n    return 1\n\n\ndef inna() -> int:\n    return 7\n"
    conftest = "import pytest\n\nfrom rozliczenia.warunek import wartosc\n\n\n@pytest.fixture(scope='session')\ndef liczba() -> int:\n    return wartosc()\n"
    tests = (
        "from rozliczenia.warunek import inna\n\n\n"
        "def test_inna() -> None:\n    assert inna() == 7\n\n\n"
        "def test_typ(liczba: int) -> None:\n    assert isinstance(liczba, int)\n\n\n"
        "def test_wartosc(liczba: int) -> None:\n    assert liczba == 2\n"
    )

    done = _run(_repo(tmp_path, tests, base.replace("return 1", "return 2"), base, conftest))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy" in done.stdout


def test_mutacje_tabeli_modulu_wykrywa_test_funkcji_pliku_ktora_ja_czyta_przed_testami_calego_pliku(tmp_path: Path) -> None:
    # Noc 41019818658, część 5/20: tabelę modułu wykonał w teście tylko import w procesie innego testu, więc każda jej
    # mutacja czekała ok. 5 min na testy pliku, a część nie skończyła się w limicie 60 min zadania.
    base = "def fabryka() -> str:\n    return 'x'\n\n\nTABELA = {'a': (fabryka, 'report')}\n\n\ndef krok(kod: str) -> str:\n    _, dalej = TABELA[kod]\n    return dalej\n"
    tests = (
        "import subprocess\nimport sys\n\nfrom rozliczenia.warunek import krok\n\n\n"
        "def test_import_w_procesie() -> None:\n    subprocess.run([sys.executable, '-c', 'import rozliczenia.warunek'], check=True)\n\n\n"
        "def test_krok() -> None:\n    assert krok('a') == 'retry'\n"
    )

    done = _run(_repo(tmp_path, tests, base.replace("'report'", "'retry'"), base))

    assert done.returncode == 0, done.stdout + done.stderr
    found = [line for line in done.stdout.splitlines() if line.startswith("WYKRYTA: src/rozliczenia/warunek.py:5 ")]
    assert len(found) == 2 and all(line.endswith(" (testy kodu pliku)") for line in found), done.stdout


def test_cofniecie_przywraca_usunieta_linie_zaczynajaca_sie_od_dwoch_minusow(tmp_path: Path) -> None:
    base = 'TEKST = """\n-- stare\n"""\n'
    tests = "from rozliczenia.warunek import TEKST\n\n\ndef test_tekst() -> None:\n    assert '-- stare' not in TEKST\n"

    done = _run(_repo(tmp_path, tests, base.replace("-- stare", "nowe"), base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYKRYTA: src/rozliczenia/warunek.py:2 zmiana linii 2 cofnięta do bazy" in done.stdout


def test_przeniesiony_plik_bez_zmian_nie_daje_mutacji(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    git(repo, "mv", MODULE, "src/rozliczenia/przeniesiony.py")

    done = _run(repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ i tools/ od baza"


def test_plik_przeniesiony_do_narzedzi_spoza_src_i_tools_psuje_tylko_linie_zmienione_przy_przeniesieniu(tmp_path: Path) -> None:
    """Atrapa przeniesiona z ``tests/fixtures/`` do ``tools/lib/`` z jedną zmienioną linią to nie nowy plik, a zmiana
    testu w tym samym commicie, choć to plik ``.py``, nie wchodzi do zakresu."""

    functions = "".join(f"def f{number}(x: int) -> bool:\n    return x > {number}\n\n\n" for number in range(1, 6))
    repo = repository(tmp_path / "repo", {"tests/fixtures/atrapa.py": functions, "tests/test_atrapa.py": "def test_a() -> None:\n    pass\n"})
    base = commit(repo, "baza")
    git(repo, "mv", "tests/fixtures/atrapa.py", "tools/lib/atrapa.py")
    (repo / "tools" / "lib" / "atrapa.py").write_text(functions.replace("x > 3", "x >= 3"), encoding="utf-8")
    (repo / "tests" / "test_atrapa.py").write_text("def test_a() -> None:\n    assert True\n", encoding="utf-8")
    commit(repo, "atrapa w narzędziach")

    zakres = ZakresMutacji.od(base, repo)

    assert {path: [hunk.start for hunk in hunks] for path, hunks in zakres.fragmenty.items()} == {"tools/lib/atrapa.py": [10]}
    assert zakres.mutanty
    assert {(mutant.path, line) for mutant in zakres.mutanty for line in mutant.lines} == {("tools/lib/atrapa.py", 10)}


def test_zmiana_pliku_spoza_src_i_tools_w_kodowaniu_innym_niz_utf8_nie_przerywa_zakresu(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": FUNKCJA, "tests/fixtures/plik_taty.csv": "ilość\n"})
    base = commit(repo, "baza")
    (repo / "tests" / "fixtures" / "plik_taty.csv").write_bytes("ilość;zlecenie\n".encode("cp1250"))
    (repo / "src" / "pakiet" / "a.py").write_text(FUNKCJA.replace("x > 1", "x > 2"), encoding="utf-8")
    commit(repo, "plik taty w cp1250")

    zakres = ZakresMutacji.od(base, repo)

    assert {path: [hunk.start for hunk in hunks] for path, hunks in zakres.fragmenty.items()} == {"src/pakiet/a.py": [2]}


def test_samotne_cr_w_pliku_spoza_kodu_przed_tekstem_w_ksztalcie_naglowka_nie_chowa_zmiany_pliku_kodu(tmp_path: Path) -> None:
    """Git kończy linię tylko na ``\\n``: samotne ``\\r`` to znak w linii pliku tekstowego, a nie początek nowej linii diffu."""

    repo = repository(tmp_path / "repo", {"tools/a.txt": "x\n", "tools/b.py": FUNKCJA})
    base = commit(repo, "baza")
    (repo / "tools" / "a.txt").write_bytes(b"x\r@@ -1 +1,40 @@\n")
    (repo / "tools" / "b.py").write_text(FUNKCJA.replace("x > 1", "x > 2"), encoding="utf-8")
    commit(repo, "cr w pliku tekstowym")

    zakres = ZakresMutacji.od(base, repo)

    assert {path: [(hunk.start, hunk.count) for hunk in hunks] for path, hunks in zakres.fragmenty.items()} == {"tools/b.py": [(2, 1)]}


def test_plik_kodu_z_polska_litera_w_nazwie_dostaje_fragmenty_zacommitowany_i_niesledzony(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo", {"tools/żółw.py": FUNKCJA})
    base = commit(repo, "baza")
    (repo / "tools" / "żółw.py").write_text(FUNKCJA.replace("x > 1", "x > 2"), encoding="utf-8")
    commit(repo, "zmiana żółwia")
    (repo / "src").mkdir()
    (repo / "src" / "źdźbło.py").write_text(FUNKCJA, encoding="utf-8")

    zakres = ZakresMutacji.od(base, repo)

    assert {path: [(hunk.start, hunk.count) for hunk in hunks] for path, hunks in zakres.fragmenty.items()} == {
        "tools/żółw.py": [(2, 1)],
        "src/źdźbło.py": [(1, 2)],
    }


def test_plik_bez_zaleznych_testow_konczy_sie_fail(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def test_nic() -> None:\n    pass\n")

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "żaden test nie zależy od src/rozliczenia/warunek.py" in done.stdout


def test_wyjatek_nad_fragmentem_obejmuje_jego_cofniecie(tmp_path: Path) -> None:
    comment = "    # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n"
    changed = CHANGED.replace("    return a and b\n", comment + "    return a and b\n")

    done = _run(_repo(tmp_path, ONE_CASE, changed))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WYJĄTEK: src/rozliczenia/warunek.py:2 zmiana linii 2–3 cofnięta do bazy" in done.stdout


def test_wyjatek_w_srodku_fragmentu_nie_obejmuje_cofniecia_calego_fragmentu(tmp_path: Path) -> None:
    base = "def oba(a, b):\n    return a\n"
    changed = CHANGED.replace("a and b\n", "a and b  # mutacje-zmiany: tylko na próbę | do 2999-01-01 | zgoda Maks\n")

    done = _run(_repo(tmp_path, ONE_CASE, changed, base))

    assert done.returncode == 1, done.stdout + done.stderr
    assert "NIEWYKRYTA: src/rozliczenia/warunek.py:1 zmiana linii 1–2 cofnięta do bazy" in done.stdout


def test_nowy_niesledzony_plik_dostaje_mutacje(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "src" / "rozliczenia" / "nowy.py").write_text("def jeden(a: bool) -> bool:\n    return a or False\n", encoding="utf-8")

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "NIEWYKRYTA: src/rozliczenia/nowy.py:2 `False` → `True` → żaden test nie zależy od src/rozliczenia/nowy.py" in done.stdout


def test_wyjatek_obowiazuje_jeszcze_w_dniu_terminu(tmp_path: Path) -> None:
    today = datetime.datetime.now(datetime.UTC).date()
    changed = CHANGED.replace("a and b\n", f"a and b  # mutacje-zmiany: tylko na próbę | do {today} | zgoda Maks\n")

    done = _run(_repo(tmp_path, ALL_CASES.replace("    assert oba(True, False) is False\n", ""), changed))

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"WYJĄTEK: src/rozliczenia/warunek.py:2 bez `b` w `and` (tylko na próbę, do {today}, zgoda Maks)" in done.stdout


def test_galaz_innego_systemu_jest_pominieta_a_nie_niewykryta(tmp_path: Path) -> None:
    other = "nt" if sys.platform != "win32" else "posix"
    branch = "if sys.platform == 'win32':" if sys.platform != "win32" else "if sys.platform != 'win32':"
    base = f"import sys\n\n{branch}\n    SYSTEM = 'stary'\n"
    changed = base.replace("'stary'", f"'{other}'")

    done = _run(_repo(tmp_path, "import rozliczenia.warunek\n\n\ndef test_import() -> None:\n    pass\n", changed, base))

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"POMINIĘTA: src/rozliczenia/warunek.py:4 zmiana linii 4 cofnięta do bazy → kod innego systemu niż {sys.platform}" in done.stdout
    assert done.stdout.splitlines()[-1].endswith("innego systemu=1")


def test_testy_ktore_padaja_bez_mutacji_koncza_sie_bez_werdyktu_mutacji(tmp_path: Path) -> None:
    done = _run(_repo(tmp_path, ONE_CASE.replace("is True", "is False")))

    assert done.returncode == 2, done.stdout + done.stderr
    assert "NIEWYKRYTA" not in done.stdout and "WYKRYTA" not in done.stdout


def test_zmieniona_linia_narzedzia_dostaje_mutacje_jak_linia_src(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "tools" / "inne.py").write_text(
        "def oba(a: bool, b: bool) -> bool:\n    return a and b\n\n\ndef jedno(a: bool, b: bool) -> bool:\n    return a or b\n", encoding="utf-8"
    )
    (repo / "tests" / "test_inne.py").write_text(
        "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))\n\n"
        "from inne import jedno, oba  # noqa: E402\n\n\n"
        "def test_inne() -> None:\n    assert oba(True, False) is False\n    assert jedno(True, False) is True\n",
        encoding="utf-8",
    )

    done = _run(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "WYKRYTA: tools/inne.py:2 bez `b` w `and`" in done.stdout
    assert "NIEWYKRYTA: tools/inne.py:6 bez `b` w `or`" in done.stdout


def test_narzedzia_podstawione_przez_probe_na_scalonych_pr_nie_sa_zmiana(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    (repo / "tools" / "inne.py").write_text("def f(a: bool, b: bool) -> bool:\n    return a\n", encoding="utf-8")
    commit(repo, "commit zmienia narzędzie")
    (repo / "tools" / "inne.py").write_text("def f(a: bool, b: bool) -> bool:\n    return a and b\n", encoding="utf-8")
    (repo / "tools" / "nowe.py").write_text("def g(a: bool, b: bool) -> bool:\n    return a or b\n", encoding="utf-8")

    trial = _run(repo, trial=True)
    checkout = _run(repo)

    assert trial.returncode == 0, trial.stdout + trial.stderr
    # Nowy plik tools/nowe.py też jest podstawiony, ale commit go nie zmienia.
    assert [line for line in trial.stdout.splitlines() if line.startswith("NIESPRAWDZONA")] == [
        "NIESPRAWDZONA: tools/inne.py → commit go zmienia, a tools/na_scalonych_pr.py podstawił w jego miejscu narzędzie z checkoutu"
    ]
    assert trial.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ i tools/ od baza"
    assert checkout.returncode == 1, checkout.stdout + checkout.stderr
    assert "NIEWYKRYTA: tools/inne.py:2 bez `b` w `and`" in checkout.stdout
    assert "NIEWYKRYTA: tools/nowe.py:2 bez `b` w `or`" in checkout.stdout
    assert "NIESPRAWDZONA" not in checkout.stdout


def test_zmiana_skryptu_skilla_i_pliku_narzedzi_spoza_pythona_nie_daje_mutacji(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ONE_CASE, BASE)
    script = repo / ".agents" / "skills" / "verify-proba" / "scripts" / "sprawdz.py"
    script.parent.mkdir(parents=True)
    script.write_text("def f(a: bool, b: bool) -> bool:\n    return a and b\n", encoding="utf-8")
    hook = repo / "tools" / "hooks" / "pre-push"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\nexec python3 tools/brama.py\n", encoding="utf-8")

    done = _run(repo)

    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == "MUTACJE ZMIANY OK | brak mutacji zmienionych linii src/ i tools/ od baza"


def _described(text: str, changed: list[int], old: tuple[str, ...] = ()) -> dict[str, str]:
    hunks = [Hunk(line, 1, old if index == 0 else ()) for index, line in enumerate(changed)]
    return {mutant.description: mutant.source for mutant in mutants("m.py", text, hunks)}


@pytest.mark.parametrize(
    ("code", "description", "mutated"),
    [
        ("x = a or b\n", "bez `a` w `or`", "x = (b)\n"),
        ("x = a if w else b\n", "`a if w else b` zawsze `a`", "x = (a)\n"),
        ("f(zamkniete=True)\n", "`True` → `False`", "f(zamkniete=False)\n"),
        ("if w:\n    f()\n", "warunek `w` zawsze `False`", "if False:\n    f()\n"),
        ("x = a > b\n", "granica `a > b` → `>=`", "x = (a >= b)\n"),
        ("def f():\n    return wynik\n", "`return wynik` → `return None`", "def f():\n    return None\n"),
        ("zapisz(plik)\n", "bez wywołania `zapisz(plik)`", "pass\n"),
        ("klucz = (a.etykieta, a.kod)\n", "krotka bez `a.kod`", "klucz = (a.etykieta,)\n"),
        ("ok = slowo in tekst\n", "`slowo in tekst` → `tekst.startswith(slowo)`", "ok = ((tekst).startswith(slowo))\n"),
        ("ok = slowo in tekst\n", "`slowo in tekst` → `tekst.endswith(slowo)`", "ok = ((tekst).endswith(slowo))\n"),
        ("ok = slowo not in tekst\n", "`slowo not in tekst` → `not tekst.endswith(slowo)`", "ok = (not (tekst).endswith(slowo))\n"),
        ("ok = tekst.startswith(slowo)\n", "`tekst.startswith(slowo)` → `slowo in tekst`", "ok = ((slowo) in (tekst))\n"),
        ("ok = tekst.startswith(slowo)\n", "`tekst.startswith(slowo)` → `tekst.endswith(slowo)`", "ok = ((tekst).endswith(slowo))\n"),
        ("ok = tekst.endswith(slowo)\n", "`tekst.endswith(slowo)` → `tekst.startswith(slowo)`", "ok = ((tekst).startswith(slowo))\n"),
        ("ok = '/' in sciezka\n", "`'/' in sciezka` → `sciezka.startswith('/')`", "ok = ((sciezka).startswith('/'))\n"),
        ("odpowiedz(stan, wersja=wersja)\n", "`wersja=wersja` → `wersja=None`", "odpowiedz(stan, wersja=None)\n"),
        ("odpowiedz(wersja=wersja, czas=teraz)\n", "`czas=teraz` → `czas=None`", "odpowiedz(wersja=wersja, czas=None)\n"),
    ],
)
def test_kazdy_rodzaj_mutacji_psuje_zmieniona_linie(code: str, description: str, mutated: str) -> None:
    lines = list(range(1, code.count("\n") + 1))

    assert _described(code, lines)[description] == mutated


@pytest.mark.parametrize(
    "code",
    [
        "x = f(plik, wersja)\n",
        "x = f(encoding='utf-8', limit=3, wersja=None, **opcje)\n",
        "x = a in [1, 2] or b in {c: d}\n",
        "x = a in ('p', 'q')\n",
        "x = a in {'p', 'q'}\n",
        "x = a in [y for y in z]\n",
        "x = a in {y for y in z}\n",
        "x = a in {y: 1 for y in z}\n",
        "x = a in (y for y in z)\n",
        "x = 1 in liczby\n",
        "x = t.startswith(('a', 'b')) or t.endswith(a, 2)\n",
        "x = t.startswith(a, start=1) or t.endswith(*koncowki)\n",
        "x = a in b in c\n",
        "x = t.split(a)\n",
    ],
)
def test_argument_pozycyjny_stala_i_kolekcja_nie_dostaja_mutacji_none_ani_predykatu(code: str) -> None:
    assert [description for description in _described(code, [1]) if "w `or`" not in description] == []


def test_z_predykatu_napisu_biegnie_in_na_startswith() -> None:
    # #460 r1: ``word in text`` → ``text.endswith(word)`` wykrył test, a przeżyło ``text.startswith(word)``.
    code = "def f(a, t):\n    x = a in t\n    y = t.startswith(a)\n    z = t.endswith(a)\n"

    chosen = [(mutant.line, mutant.description) for mutant in selected("m.py", code, [Hunk(2, 3, ())]) if not mutant.revert]

    assert chosen == [
        (2, "`a in t` → `t.startswith(a)`"),
        (3, "`t.startswith(a)` → `t.endswith(a)`"),
        (4, "`t.endswith(a)` → `t.startswith(a)`"),
    ]


def test_predykat_napisu_biegnie_tylko_na_linii_bez_innej_mutacji() -> None:
    # #486 ``tools/lib/sciezki_w_kodzie.py:67``: przy zbiorze ``GLOBS.startswith(name)`` tylko rzuca ``AttributeError``, a
    # przeżywało ``bez `name in GLOBS` w `and` ``.
    code = 'GLOBS = frozenset({"glob", "rglob"})\n\n\ndef f(node, name, t):\n    if isinstance(node, str) and name in GLOBS:\n        return t\n'
    hunks = [Hunk(5, 1, ())]

    chosen = [mutant.description for mutant in selected("m.py", code, hunks) if not mutant.revert]

    assert "`name in GLOBS` → `GLOBS.startswith(name)`" in {mutant.description for mutant in mutants("m.py", code, hunks)}
    assert chosen == ["bez `name in GLOBS` w `and`"]


def test_mutacja_glebiej_niz_predykat_napisu_wygrywa_z_nim() -> None:
    chosen = [mutant.description for mutant in selected("m.py", "x = a in (b if c else d)\n", [Hunk(1, 1, ())]) if not mutant.revert]

    assert chosen == ["`b if c else d` zawsze `d`"]


def test_predykat_nie_dostaje_zamiany_na_samego_siebie() -> None:
    assert _described("ok = slowo not in tekst\n", [1]).keys() == {
        "`slowo not in tekst` → `not tekst.startswith(slowo)`",
        "`slowo not in tekst` → `not tekst.endswith(slowo)`",
    }


# Wzorzec narzędzi z ``tools/`` (``tools/hooks/czekanie.py``): wynik ``main()`` to kod wyjścia procesu.
EXITING = (
    "import sys\n\n\n"
    "def main() -> int:\n"
    "    def pomoc() -> int:\n"
    "        return 3\n\n"
    "    async def czekaj() -> int:\n"
    "        return 4\n\n"
    "    class Krok:\n"
    "        def wynik(self) -> int:\n"
    "            return 5\n\n"
    "    if sys.argv:\n"
    "        return 0\n"
    "    if pomoc():\n"
    "        return 'błąd'\n"
    "    return 2\n\n\n"
    "class Narzedzie:\n"
    "    def main(self) -> int:\n"
    "        return 7\n\n\n"
    "if __name__ == '__main__':\n"
    "    {ending}\n"
)


def _returns(code: str) -> set[str]:
    return {description for description in _described(code, list(range(1, code.count("\n") + 1))) if "`return" in description}


@pytest.mark.parametrize("ending", ["sys.exit(main())", "raise SystemExit(main())"])
def test_liczba_zwracana_do_sys_exit_dostaje_inny_kod_wyjscia_zamiast_none(ending: str) -> None:
    # ``sys.exit(None)`` kończy się kodem 0, więc ``return 0`` → ``return None`` niczego by nie zmieniło.
    assert _returns(EXITING.format(ending=ending)) == {
        "`return 0` → `return 1`",
        "`return 2` → `return 0`",
        "`return 'błąd'` → `return None`",
        "`return 3` → `return None`",
        "`return 4` → `return None`",
        "`return 5` → `return None`",
        "`return 7` → `return None`",
    }


def test_liczba_zwracana_poza_sys_exit_dostaje_none() -> None:
    code = "import sys\n\nimport cli\n\n\ndef policz() -> int:\n    return 0\n\n\nprint(policz())\nsys.exit(cli.main())\nraise SystemExit(1)\n"

    assert _returns(code) == {"`return 0` → `return None`"}


def test_biegnie_kazde_cofniecie_fragmentu_i_jedna_mutacja_linii_z_jej_najglebszego_wezla() -> None:
    code = "def f(a, b, c):\n    if a and b:\n        return c > 1\n    zapisz(a)\n    return (a, b)\n"
    hunks = [Hunk(2, 2, ("    if a:", "        return c")), Hunk(5, 1, ("    return a",))]

    every = mutants("m.py", code, hunks)
    chosen = [(mutant.line, mutant.description) for mutant in selected("m.py", code, hunks)]

    assert chosen == [
        (2, "bez `b` w `and`"),
        (2, "zmiana linii 2–3 cofnięta do bazy"),
        (3, "granica `c > 1` → `>=`"),
        (5, "krotka bez `b`"),
        (5, "zmiana linii 5 cofnięta do bazy"),
    ]
    assert len(every) > len(chosen)
    assert {mutant.line for mutant in every if not mutant.revert} == {line for line, description in chosen if "cofnięta" not in description}


def test_biegnie_cofniecie_rowne_innej_mutacji_linii() -> None:
    # #523, src/rozliczenia/intermax_file.py:476: dodany element krotki, a jej cofnięcie to „krotka bez” tego elementu.
    code = "def xf(number_format, font, fill_id, border):\n    return FORMAT % (number_format, font, fill_id, border)\n"
    base = "def xf(number_format, font, fill_id, border):\n    return FORMAT % (number_format, font, border)\n"

    chosen = selected("m.py", code, [Hunk(2, 1, ("    return FORMAT % (number_format, font, border)",))])

    assert [(mutant.description, mutant.revert, mutant.source == base) for mutant in chosen] == [
        ("krotka bez `fill_id`", True, True),
        ("krotka bez `border`", False, False),
    ]


def test_niezmieniona_linia_nie_dostaje_mutacji() -> None:
    assert _described("x = a or b\ny = c or d\n", [2]).keys() == {"bez `c` w `or`", "bez `d` w `or`", "zmiana linii 2 cofnięta do bazy"}


def test_mutacja_trafia_w_wezel_za_polskimi_znakami_w_tej_samej_linii() -> None:
    code = 'x = f("żółć") or zażółć\n'

    assert _described(code, [1])["bez `zażółć` w `or`"] == 'x = (f("żółć"))\n'


def test_cofniecie_fragmentu_przywraca_linie_bazy() -> None:
    code = 'def f(s: str) -> bool:\n    return NAGLOWEK_LINII.search(s) is not None\n'

    reverted = _described(code, [2], ("    return NAGLOWEK in s",))["zmiana linii 2 cofnięta do bazy"]

    assert reverted == "def f(s: str) -> bool:\n    return NAGLOWEK in s\n"


def test_cofniecie_samego_docstringu_komentarza_albo_importu_nie_jest_mutacja() -> None:
    code = '"""Nowy opis."""\n\nfrom a import b, c  # nowy komentarz\n\nx = 1\n'

    old = ('"""Stary opis."""', "", "from a import b")

    assert _described(code, [1, 2, 3], old) == {}


def test_cofniecie_samej_adnotacji_albo_aliasu_typu_nie_jest_mutacja() -> None:
    code = "Odbiorca = Callable[[str], bool] | None\n\n\ndef f(x: int) -> dict[str, str | int]:\n    return {}\n"

    old = ("def f(x: int) -> dict[str, str]:",)

    assert [d for d in _described(code, [1, 4], ()) if "cofnięta" in d] == []
    assert [d for d in _described(code, [4], old) if "cofnięta" in d] == []


def test_dekorator_nie_dostaje_mutacji() -> None:
    assert [d for d in _described("@dataclass(frozen=True)\nclass A:\n    x: int\n", [1]) if "cofnięta" not in d] == []


def test_gałąź_innego_systemu_i_jej_warunek_sa_oznaczone() -> None:
    code = "import sys\n\nif sys.platform == 'win32':\n    x = a or b\nelse:\n    y = c or d\n"
    hunks = [Hunk(line, 1, ()) for line in (3, 4, 6)]

    def other(platform: str) -> dict[str, bool]:
        return {m.description: m.other_system for m in mutants("m.py", code, hunks, platform) if "cofnięta" not in m.description}

    assert other("linux") == {
        "warunek `sys.platform == 'win32'` zawsze `True`": True,
        "warunek `sys.platform == 'win32'` zawsze `False`": True,
        "bez `a` w `or`": True,
        "bez `b` w `or`": True,
        "bez `c` w `or`": False,
        "bez `d` w `or`": False,
    }
    assert {d for d, flag in other("win32").items() if flag} == {
        "warunek `sys.platform == 'win32'` zawsze `True`",
        "warunek `sys.platform == 'win32'` zawsze `False`",
        "bez `c` w `or`",
        "bez `d` w `or`",
    }


@pytest.mark.parametrize(
    "code",
    [
        "x = (a or b) if sys.platform == 'win32' else c\n",
        "def f():\n    if sys.platform != 'win32':\n        return None\n    return a or b\n",
        "if sys.platform == 'darwin':\n    x = a or b\n",
    ],
)
def test_kod_innego_systemu_w_kazdej_postaci_jest_oznaczony(code: str) -> None:
    hunks = [Hunk(line, 1, ()) for line in range(1, code.count("\n") + 1)]
    runs_on = "win32" if "win32" in code else "darwin"

    def flagged(platform: str) -> set[str]:
        return {m.description for m in mutants("m.py", code, hunks, platform) if m.other_system and "w `or`" in m.description}

    assert flagged("linux") == {"bez `a` w `or`", "bez `b` w `or`"}
    assert flagged(runs_on) == set()


def test_cofniecie_fragmentu_gałęzi_windows_z_komentarzem_jest_oznaczone() -> None:
    code = "if sys.platform == 'win32':\n    # tylko Windows\n    x = 2\n"

    found = mutants("m.py", code, [Hunk(2, 2, ("    x = 1",))], "linux")

    assert [m.other_system for m in found if "cofnięta" in m.description] == [True]


def test_mutacja_funkcji_z_cache_ma_stan_wspolny() -> None:
    code = "@functools.cache\ndef zb() -> int:\n    return a or b\n\n\ndef inna() -> int:\n    return c or d\n"
    hunks = [Hunk(line, 1, ()) for line in (3, 7)]

    shared = {m.description: m.shared_state for m in mutants("m.py", code, hunks) if "w `or`" in m.description}

    assert shared == {"bez `a` w `or`": True, "bez `b` w `or`": True, "bez `c` w `or`": False, "bez `d` w `or`": False}


def test_cofniecie_liczy_linie_jak_git_mimo_separatora_unicode() -> None:
    code = 'a = "x\u2028y"\nb = 2\nc = 3\n'

    assert _described(code, [3], ("c = 4",))["zmiana linii 3 cofnięta do bazy"] == 'a = "x\u2028y"\nb = 2\nc = 4\n'


def test_adnotacja_pola_modelu_zostaje_mutacja_a_stala_nie_jest_aliasem() -> None:
    model = "class Model(BaseModel):\n    pole: int | None\n"
    constant = "TIMEOUT_S = 5 * 60\n"

    assert "zmiana linii 2 cofnięta do bazy" in _described(model, [2], ("    pole: int",))
    assert "zmiana linii 1 cofnięta do bazy" in _described(constant, [1], ("TIMEOUT_S = 3 * 60",))
    assert "zmiana linii 1 cofnięta do bazy" in _described('NAZWA = OPCJE["nowa"]\n', [1], ('NAZWA = OPCJE["stara"]',))


def test_w_pliku_z_pydantic_adnotacja_i_alias_typu_zostaja_mutacja() -> None:
    code = "from pydantic import BaseModel\nWynik = Annotated[A | B, Field(discriminator='rodzaj')]\n\n\ndef trasa() -> Wynik:\n    pass\n"

    assert "zmiana linii 2 cofnięta do bazy" in _described(code, [2], ("Wynik = A | B",))
    assert "zmiana linii 5 cofnięta do bazy" in _described(code, [5], ("def trasa() -> A:",))


def test_adnotacje_i_docstringi_nie_dostaja_mutacji() -> None:
    code = 'def f(x: tuple[int, str] | None = None) -> bool:\n    """Opis."""\n\n\nif TYPE_CHECKING:\n    g(a or b)\n'

    assert [description for description in _described(code, [1, 2, 5, 6]) if "cofnięta" not in description] == []


def test_wyjatek_w_samodzielnym_komentarzu_dotyczy_linii_pod_nim() -> None:
    code = "# mutacje-zmiany: to samo | do 2026-12-31 | zgoda Maks\nx = a or b\ny = 1  # mutacje-zmiany: inne | do 2027-01-31 | zgoda Maks\n"

    found = exceptions(code, "m.py")

    assert sorted(found) == [1, 2, 3]
    assert (found[2].reason, str(found[2].until), found[2].who) == ("to samo", "2026-12-31", "Maks")


def test_opis_postaci_wyjatku_w_napisie_nie_jest_wyjatkiem() -> None:
    form = "# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>"
    # Od Pythona 3.12 tekst f-stringu to osobny token (``FSTRING_MIDDLE``), a nie ``STRING``.
    code = f'OPIS = """\n``{form}``\n"""\nPOSTAC = "{form}"\nW_F = f"{{OPIS}} {form}"\nx = 1  # mutacje-zmiany: inne | do 2027-01-31 | zgoda Maks\n'

    assert sorted(exceptions(code, "m.py")) == [6]


@pytest.mark.parametrize("comment", ["# mutacje-zmiany: bez terminu", "# mutacje-zmiany: powód | do 2026-13-01 | zgoda Maks"])
def test_wyjatek_w_zlej_postaci_nazywa_plik_i_linie(comment: str) -> None:
    with pytest.raises(ValueError, match=r"^m\.py:2: "):
        exceptions(f"x = 1\ny = 2  {comment}\n", "m.py")


def test_pokrycie_workera_xdist_przetrwa_zamkniecie_workera_zaraz_po_koncu_sesji(tmp_path: Path) -> None:
    """Kontroler xdist zamyka workera zaraz po końcu jego sesji, a execnet przerywa mu główny wątek po 5 s (#788).

    Atrapa: worker ginie (``os._exit``) w pierwszym kroku po końcu sesji, a zapis ma już zmienioną linię testu.
    """

    module = tmp_path / "modul.py"
    module.write_text("def w_tescie() -> int:\n    return 1\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import os\n\nimport pytest\n\n\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_unconfigure(config):\n"
        "    if hasattr(config, 'workerinput'):\n"
        "        os._exit(0)\n",
        encoding="utf-8",
    )
    (tmp_path / "test_modul.py").write_text("import modul\n\n\ndef test_w_tescie() -> None:\n    modul.w_tescie()\n", encoding="utf-8")
    found = tmp_path / "wynik"
    found.mkdir()
    settings = {"linie": {str(module): [2]}, "wynik": str(found)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "1", "-p", "pytest_pokrycie", "-p", "no:cacheprovider", "test_modul.py"],
        cwd=tmp_path,
        env={
            **{name: value for name, value in os.environ.items() if name != pokrycie_procesu.TEST},
            "PYTHONPATH": os.pathsep.join([str(ROOT / "tools" / "lib"), str(tmp_path)]),
            "POKRYCIE_LINII": json.dumps(settings),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert "1 passed" in done.stdout, done.stdout + done.stderr
    recorded = [json.loads(written.read_text(encoding="utf-8")) for written in found.iterdir()]
    assert [part["linie"] for part in recorded if part["linie"]] == [{"test_modul.py::test_w_tescie": {str(module): [2]}}]


def test_pokrycie_przypisuje_zmieniona_linie_testom_ktore_ja_wykonuja_w_watku_i_w_podprocesie(tmp_path: Path) -> None:
    module = tmp_path / "modul.py"
    module.write_text(
        "import threading\n\n\n"
        "def w_watku() -> None:\n"
        "    x = 1\n\n\n"
        "def wprost() -> int:\n"
        "    return 2\n\n\n"
        "def watek() -> None:\n"
        "    t = threading.Thread(target=w_watku)\n"
        "    t.start()\n"
        "    t.join()\n\n\n"
        "def w_podprocesie() -> int:\n"
        "    return 3\n",
        encoding="utf-8",
    )
    (tmp_path / "test_modul.py").write_text(
        "import os\nimport subprocess\nimport sys\n\nimport modul\n\n\n"
        "def test_wprost() -> None:\n    modul.wprost()\n\n\n"
        "def test_watek() -> None:\n    modul.watek()\n\n\n"
        "def test_podproces() -> None:\n"
        "    code = 'import modul; modul.w_podprocesie()'\n"
        "    subprocess.run([sys.executable, '-c', code], env=dict(os.environ), check=True)\n",
        encoding="utf-8",
    )
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(pokrycie_procesu.SITECUSTOMIZE, encoding="utf-8")
    found = tmp_path / "wynik"
    found.mkdir()
    settings = {"linie": {str(module): [5, 9, 18]}, "wynik": str(found)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pytest_pokrycie", "-p", "no:cacheprovider", "test_modul.py"],
        cwd=tmp_path,
        env={
            **{name: value for name, value in os.environ.items() if name != pokrycie_procesu.TEST},
            "PYTHONPATH": os.pathsep.join([str(site), str(ROOT / "tools" / "lib"), str(tmp_path)]),
            "POKRYCIE_LINII": json.dumps(settings),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    merged: dict[str, dict[str, list[int]]] = {}
    for written in found.iterdir():
        merged |= json.loads(written.read_text(encoding="utf-8"))["linie"]
    assert merged == {
        "test_modul.py::test_wprost": {str(module): [9]},
        "test_modul.py::test_watek": {str(module): [5]},
        "test_modul.py::test_podproces": {str(module): [18]},
    }
