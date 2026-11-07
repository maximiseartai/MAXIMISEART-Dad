"""``tools/ci/mutacje_skilli.py`` nie przepuszcza skryptu mutacji, który zgubił się albo nie dał werdyktu, a kroki skilli
(``tools/lib/kroki_skilli.py``) mają polecenie, części i przeglądarkę z frontmattera i skryptów skilla.

Każdy test buduje własne ``.agents/skills`` i uruchamia obok nich kopię narzędzia albo czyta katalog
``Katalog.skanuj`` ich korzenia, więc widzi tylko te skille. Które kroki
biegną w runie CI, sprawdza ``tests/test_zakres_runu.py``.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import importlib.util
from pathlib import Path
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from types import ModuleType

import pytest

from tests.fixtures.git_repo import copy_files, git
from tests.fixtures.granice_ksztaltow import GAPS
from tests.fixtures.potomne import beating, wait_for

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS / "lib"))

from jednostka import Klucz  # noqa: E402
import rozjazd_modelu  # noqa: E402

TOOL = TOOLS / "ci" / "mutacje_skilli.py"
STEPS = TOOLS / "lib" / "kroki_skilli.py"
PASSING = 'print("WYKRYTA: proba")\nprint("MUTACJE OK")\n'
CHECKED = "src/pakiet/sprawdzany.py"
GUARDED = "---\nname: verify-x\npilnuje:\n  - src/pakiet/rout*.py\n---\n"
ANCHORS = "src/pakiet/kotwice.txt"
# Dawny znak potwierdzenia modelu w ``SKILL.md``: SHA, który przepisuje każdy rebase gałęzi (#1060).
SYNC_COMMIT = re.compile(r"Sync commit: `[0-9a-f]{7,40}`")
WITH_TABLE = f"""from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from mutacje import Edit, Mutation  # noqa: E402

MUTATIONS = (
    Mutation("m", (Edit(Path("{CHECKED}"), "X", "Y"), Edit(Path("{ANCHORS}"), "X", "Y")), (".agents/skills/verify-a/scripts/sprawdz_a.py",)),
)

if __name__ == "__main__":
    {PASSING.replace(chr(10), chr(10) + "    ").rstrip()}
"""
REPO = {
    "src/pakiet/__init__.py": "",
    CHECKED: "def run() -> int:\n    from pakiet import pomocnik\n\n    return pomocnik.X\n",
    "src/pakiet/pomocnik.py": "X = 1\n",
    "src/pakiet/obcy.py": "Y = 2\n",
    "src/pakiet/routing.py": "Z = 3\n",
    ANCHORS: "X\n",
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "from pakiet import sprawdzany\n",
    "requirements.txt": "pytest\n",
    "docs/opis.md": "opis\n",
}


def _skill(root: Path, name: str, scripts: dict[str, str], skill_md: str = "") -> None:
    skill = root / ".agents" / "skills" / name
    for script, body in scripts.items():
        (skill / "scripts" / script).parent.mkdir(parents=True, exist_ok=True)
        (skill / "scripts" / script).write_text(body, encoding="utf-8")
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _tool(root: Path) -> list[str]:
    """Kopia narzędzia w ``root``; kopii, która już jest, nie nadpisuje, bo test może ją zmieniać."""

    names = (
        "tools/ci/mutacje_skilli.py", "tools/lib/kroki_skilli.py", "tools/lib/zakres_runu.py", "tools/lib/potomne.py", "tools/lib/repo.py", "tools/lib/ciezkie_ci.py",
        "tools/mutacje.py", "tools/lib/sciezki_w_kodzie.py", "tools/lib/wplyw_zmiany.py", "tools/ci_lokalnie.py", "tools/lib/czasy_ci.py", "tools/lib/github.py",
        "tools/lib/jednostka.py", "tools/lib/ostatnie_linie.py",
    )
    copy_files(root, [name for name in names if not (root / name).exists()])
    return [sys.executable, str(root / "tools" / "ci" / "mutacje_skilli.py")]


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_tool(root), *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def _start(root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _tool(root),
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def test_skrypty_z_werdyktem_przechodza(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, "py -3 scripts\\check_a_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_mutacji_o_zlej_nazwie_albo_w_podfolderze_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {"check_mutation_proba.py": PASSING, "sub/check_sub_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 1
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-b/scripts/check_mutation_proba.py" in final
    assert ".agents/skills/verify-b/scripts/sub/check_sub_mutations.py" in final


def test_skrypt_wskazany_w_skill_md_a_usuniety_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-b", {}, "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout.splitlines()[-1]


@pytest.mark.parametrize(
    "mention",
    [
        "Nazwij skrypt `scripts/check_<co>_mutations.py`.",
        "Zobacz też `check_b_mutations.py` w verify-b.",
        "py -3 .agents\\skills\\verify-b\\scripts\\check_b_mutations.py",
        "Testy runnera są w `tests/test_mutations.py`.",
    ],
)
def test_wzmianka_w_prozie_nie_daje_fail(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts\\check_a_mutations.py\n{mention}\n")
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_skrypt_bez_werdyktu_daje_fail(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "def main() -> int:\n    return 0\n"})

    result = _run(tmp_path)

    assert result.returncode == 1
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in result.stdout.splitlines()[-1]


def test_skrypt_po_limicie_czasu_daje_fail_a_kolejne_dalej_ruszaja(tmp_path: Path) -> None:
    # Wybór kroków importuje skrypt, żeby przeczytać jego tabelę, więc ``sleep`` na poziomie modułu biegłby w procesie
    # narzędzia, a nie w skrypcie, którego pilnuje limit. Werdykt po ``sleep`` sprawia, że FAIL daje tylko limit.
    late = "import time\n\nif __name__ == '__main__':\n    time.sleep(60)\n" + "".join(f"    {line}\n" for line in PASSING.splitlines())
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": late})
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": PASSING})

    result = _run(tmp_path, "--limit-s", "1")

    assert result.returncode == 1
    assert "OK   .agents/skills/verify-b/scripts/check_b_mutations.py" in result.stdout
    final = result.stdout.splitlines()[-1]
    assert ".agents/skills/verify-a/scripts/check_a_mutations.py" in final
    assert "verify-b" not in final


def test_wyjscie_skryptu_mutacji_widac_w_trakcie_jego_pracy(tmp_path: Path) -> None:
    seen = tmp_path / "linia-widziana"
    script = (
        "import pathlib, sys, time\n"
        "print('WYKRYTA: pierwsza', flush=True)\n"
        "deadline = time.monotonic() + 20\n"
        f"while not pathlib.Path({str(seen)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(3)\n"
        "    time.sleep(0.05)\n" + PASSING
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    runner = _start(tmp_path)
    assert runner.stdout is not None
    lines = []
    for line in runner.stdout:
        lines.append(line.rstrip("\n"))
        if line.startswith("WYKRYTA: pierwsza"):
            seen.touch()
    runner.wait(timeout=30)

    assert (runner.returncode, lines[-1]) == (0, "MUTACJE SKILLI OK"), lines


def test_nazwe_kroku_widac_zanim_krok_cokolwiek_wydrukuje(tmp_path: Path) -> None:
    # Krok, który wisi bez słowa, ma w logu swoją nazwę, więc wiadomo, który wisi. Wybór kroków importuje skrypt, więc
    # czeka on dopiero pod ``__main__``.
    seen = tmp_path / "naglowek-widziany"
    waiting = (
        "deadline = time.monotonic() + 20\n"
        f"while not pathlib.Path({str(seen)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(3)\n"
        "    time.sleep(0.05)\n" + PASSING
    )
    script = "import pathlib, sys, time\n\nif __name__ == '__main__':\n" + "".join(f"    {line}\n" for line in waiting.splitlines())
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    runner = _start(tmp_path)
    assert runner.stdout is not None
    lines = []
    for line in runner.stdout:
        lines.append(line.rstrip("\n"))
        if line.rstrip("\n") == "== .agents/skills/verify-a/scripts/check_a_mutations.py":
            seen.touch()
    runner.wait(timeout=30)

    assert (runner.returncode, lines[-1]) == (0, "MUTACJE SKILLI OK"), lines


@pytest.mark.parametrize(
    ("script", "code", "last", "step"),
    [
        (PASSING, 0, "CI LOKALNIE OK | tylko mutations", "OK   mutacje skilli"),
        ('print("NIEWYKRYTA: proba")\nraise SystemExit(1)\n', 1, "CI LOKALNIE FAIL | mutacje skilli", "FAIL mutacje skilli"),
    ],
    ids=["skrypt przechodzi", "skrypt pada"],
)
def test_zadanie_mutations_ci_lokalnie_uruchamia_skrypty_mutacji_skilli(tmp_path: Path, script: str, code: int, last: str, step: str) -> None:
    _tool(tmp_path)
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})

    # Poza CI zadanie mutations odmawia startu (``tools/lib/ciezkie_ci.py``).
    result = subprocess.run(
        [sys.executable, str(tmp_path / "tools" / "ci_lokalnie.py"), "--tylko", "mutations"],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    lines = result.stdout.splitlines()
    assert (result.returncode, lines[-1]) == (code, last), result.stdout + result.stderr
    assert [line.partition(" (")[0] for line in lines if line.startswith(("OK ", "FAIL "))] == [step], result.stdout


def test_skrypt_bez_limitu_z_wiersza_polecen_przerywa_domyslny_limit_czasu(tmp_path: Path) -> None:
    _tool(tmp_path)
    copy = tmp_path / "tools" / "ci" / "mutacje_skilli.py"
    copy.write_text(copy.read_text(encoding="utf-8").replace("LIMIT_S = 30 * 60", "LIMIT_S = 1"), encoding="utf-8")
    late = "import time\n\nif __name__ == '__main__':\n    time.sleep(15)\n" + "".join(f"    {line}\n" for line in PASSING.splitlines())
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": late})

    result = _run(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "FAIL .agents/skills/verify-a/scripts/check_a_mutations.py" in result.stdout
    assert "przekroczył limit 1 s" in result.stdout


@pytest.mark.parametrize(
    "mention",
    [
        "py -3 ./.agents/skills/verify-a/scripts/check_a_mutations.py",
        "py -3 .\\.agents\\skills\\verify-a\\scripts\\check_a_mutations.py",
        "py -3 {root}/.agents/skills/verify-a/scripts/check_a_mutations.py",
    ],
)
def test_sciezka_z_kropka_albo_bezwzgledna_do_skryptu_w_repo_przechodzi(tmp_path: Path, mention: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING}, mention.format(root=tmp_path))

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI OK"


def test_sciezka_bezwzgledna_spoza_repo_daje_nazwany_fail(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "gdzie-indziej" / "scripts" / "check_x_mutations.py"
    _skill(root, "verify-a", {"check_a_mutations.py": PASSING}, f"py -3 scripts/check_a_mutations.py\npy -3 {outside}\n")

    result = _run(root)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert outside.as_posix() in result.stdout.splitlines()[-1]


def test_zabity_runner_nie_zostawia_skryptu_mutacji(tmp_path: Path) -> None:
    ready, beats = tmp_path / "skrypt-gotowy", tmp_path / "skrypt-zyje"
    beat = f"open({str(beats)!r}, 'a').write('.')"
    script = (
        f"import os, pathlib, time\n{beat}\npathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        f"while True:\n    {beat}\n    time.sleep(0.1)\n"
    )
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": script})
    runner = subprocess.Popen(_tool(tmp_path), cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "skrypt mutacji nie ruszył"
        runner.kill()
        runner.wait(timeout=30)

        assert wait_for(lambda: not beating(beats), 5), "skrypt mutacji przeżył runner"
    finally:
        runner.kill()
        runner.wait()
        if ready.exists():
            with contextlib.suppress(OSError):
                os.kill(int(ready.read_text()), signal.SIGTERM)


def _load_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("kroki_skilli", STEPS)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def test_kazdy_glob_pilnuje_trafia_w_plik_repozytorium(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)
    tracked = git(ROOT, "ls-files").splitlines()

    guarded = {md.parent.name: tool.guarded(md) for md in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))}
    dead = [f"{skill}: {glob}" for skill, globs in guarded.items() for glob in globs or () if not any(fnmatch.fnmatchcase(name, glob) for name in tracked)]

    assert any(guarded.values())
    assert dead == []


POZA_VERIFY_ROZLICZENIA: dict[str, str] = {}


def test_kazdy_modul_silnika_jest_w_pilnuje_verify_rozliczenia_albo_na_liscie_wylaczen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Glob ``pilnuje:`` ``verify-rozliczenia`` wymienia moduły silnika z nazwy, więc nowy moduł musi trafić do globu albo
    do ``POZA_VERIFY_ROZLICZENIA``; inaczej jego zmiana na PR nie uruchamia podstawy skilla. Plik spoza gita też się
    liczy, bo nowy moduł istnieje przed commitem."""

    globs = _load_tool(monkeypatch).guarded(ROOT / ".agents" / "skills" / "verify-rozliczenia" / "SKILL.md")
    engine = (ROOT / "src" / "rozliczenia").rglob("*.py")
    modules = {name for path in engine if "centrum" not in (name := path.relative_to(ROOT).as_posix()).split("/")}
    covered = {name for name in modules if any(fnmatch.fnmatchcase(name, glob) for glob in globs)}

    assert sorted(modules - covered - POZA_VERIFY_ROZLICZENIA.keys()) == [], "dopisz moduł do pilnuje: verify-rozliczenia albo do POZA_VERIFY_ROZLICZENIA"
    assert sorted(POZA_VERIFY_ROZLICZENIA.keys() - (modules - covered)) == [], "usuń z POZA_VERIFY_ROZLICZENIA moduł, którego nie ma albo który glob obejmuje"


def test_kazdy_skill_z_modelem_wskazuje_kod_modelu_w_pilnuje_i_kroki_naprawy_rozjazdu_bez_sync_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rozjazd modelu z kodem (``tools/lib/rozjazd_modelu.py``) sprawdza skrypt skilla w CI i ``tools/szybko.py`` tylko dla
    skilla z ``model/definicje.json``, więc ma go każdy skill z modelem TLA+ (``model/*.tla``) i eksplorator z częściami
    modelowanymi ręcznie. Każdy plik z ``definicje.json`` leży w ``pilnuje:`` skilla, żeby jego zmiana uruchamiała
    podstawę i krok szybko, a ``SKILL.md`` ma sekcję z krokami, którymi rozjazd każe go naprawić, i nie ma Sync commit:
    model potwierdzają skróty w ``definicje.json``, a SHA w ``SKILL.md`` przepisuje każdy rebase (#1060)."""

    tool = _load_tool(monkeypatch)
    models = {path.parents[1] for path in (ROOT / ".agents" / "skills").glob("*/model/*.tla")}
    problems = []
    for skill in rozjazd_modelu.skille(ROOT):
        definitions = rozjazd_modelu.definicje(skill)
        unguarded = sorted(name for name in definitions if tool.hits(skill, {name}).files.keys() != {name})
        problems += [f"{skill.name}: {name} poza pilnuje:" for name in unguarded]
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        if SYNC_COMMIT.search(text) is not None:
            problems.append(f"{skill.name}: SKILL.md z Sync commit")
        if not re.search(rf"^#+ {rozjazd_modelu.KROKI}", text, re.MULTILINE):
            problems.append(f"{skill.name}: SKILL.md bez sekcji „{rozjazd_modelu.KROKI}”")

    assert len(models) >= 4
    assert sorted(models - set(rozjazd_modelu.skille(ROOT))) == []
    assert problems == []


def test_polecenie_ci_kazdego_skilla_to_skrypt_z_repozytorium(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool(monkeypatch)

    commands = {md.parent.name: tool.ci_command(md) for md in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))}

    assert {"verify-centrum-rozliczen", "verify-aktualizacja-narzedzia"} <= {skill for skill, command in commands.items() if command}


def test_nazwy_mutacji_w_tabeli_kazdego_skryptu_skilla_sa_rozne(monkeypatch: pytest.MonkeyPatch) -> None:
    """Część ``MUTACJE_CZESC`` układa mutacje po nazwie; przy dwóch równych nazwach decydowałoby ``repr`` ścieżek."""

    tool = _load_tool(monkeypatch)
    scripts = sorted((ROOT / ".agents" / "skills").glob(f"*/scripts/{tool.PATTERN}"))
    names = {script.name: [mutation.name for mutation in tool._mutations(script)] for script in scripts}

    assert scripts
    assert {script: sorted(set(found)) for script, found in names.items()} == {script: sorted(found) for script, found in names.items()}


def test_kotwica_kazdej_mutacji_skilla_trafia_w_swoj_plik_dokladnie_raz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skrypty mutacji skilli poza modelem nie biegną na pull request, więc zmiana kodu, po której mutacja jest NIEAKTUALNA, czerwieni
    dopiero ``main`` (#667 i #669 zmieniły warunek budzenia w ``outbox.py``). Test nanosi zmiany każdej mutacji tym samym
    ``_apply`` co ``tools/mutacje.py``, na kopii plików, które ona zmienia, bez uruchamiania jej polecenia."""

    tool = _load_tool(monkeypatch)
    engine = importlib.import_module("mutacje")
    scripts = sorted((ROOT / ".agents" / "skills").glob(f"*/scripts/{tool.PATTERN}"))
    stale = []
    for script in scripts:
        for number, mutation in enumerate(tool._mutations(script)):
            copy = tmp_path / script.parents[1].name / script.stem / str(number)
            for edit in mutation.edits:
                if (ROOT / edit.file).is_file() and not (copy / edit.file).exists():
                    (copy / edit.file).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / edit.file, copy / edit.file)
            if found := engine._apply(copy, mutation.edits):
                stale.append(f"{script.relative_to(ROOT).as_posix()}: {mutation.name} → {found}")

    assert scripts
    assert stale == []


def test_krok_skilla_ktorego_skrypty_importuja_playwright_potrzebuje_przegladarki_a_skrypt_ma_tyle_czesci_ile_mutacji(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = (
        "from pathlib import Path\nimport sys\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools'))\n"
        "from mutacje import Edit, Mutation  # noqa: E402\n\n"
        "MUTATIONS = tuple(Mutation(f'm{numer}', (Edit(Path('a.txt'), 'X', 'Y'),), ('a.py',)) for numer in range({count}))\n"
    )
    drive = ".agents/skills/verify-a/scripts/drive/przegladarka.py"
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": table.replace("{count}", "3"), "drive/przegladarka.py": "from playwright.sync_api import sync_playwright\n"}, _with_ci("verify-a", drive))
    _skill(tmp_path, "verify-b", {"check_b_mutations.py": table.replace("{count}", "0"), "opis.py": "TEKST = 'import playwright'\n"})
    tool = _load_tool(monkeypatch)

    katalog = tool.Katalog.skanuj(tmp_path)

    assert [(step.key, step.parts, step.browser) for step in katalog.kroki] == [
        ("verify-a/ci", 1, True),
        ("verify-a/check_a_mutations.py", 3, True),
        ("verify-b/check_b_mutations.py", 1, False),
    ]
    assert katalog.bledy == {}


CHECKED_IN_CI = (
    "import sys\n"
    "def _uzywa():\n"
    "    from pakiet import pomocnik\n"
    "print('sprawdzone', *sys.argv[1:])\n"
    "sys.exit({code})\n"
)


def _with_ci(name: str, command: str, globs: str = "src/pakiet/rout*.py") -> str:
    return f"---\nname: {name}\npilnuje:\n  - {globs}\nci: {command}\n---\n"


def test_podstawa_ci_biegnie_z_argumentami_przed_mutacjami_skilla(tmp_path: Path) -> None:
    command = ".agents/skills/verify-d/scripts/sprawdz_d.py --feature all"
    _skill(tmp_path, "verify-d", {"check_d_mutations.py": PASSING, "sprawdz_d.py": CHECKED_IN_CI.format(code=0)}, _with_ci("verify-d", command))

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines.index(f"== PODSTAWA verify-d: {command}") < lines.index("sprawdzone --feature all") < lines.index("== .agents/skills/verify-d/scripts/check_d_mutations.py")
    assert lines[-1] == "MUTACJE SKILLI OK"


def test_czerwona_podstawa_ci_daje_fail_takze_w_skillu_bez_skryptu_mutacji(tmp_path: Path) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-d", {"sprawdz_d.py": CHECKED_IN_CI.format(code=1)}, _with_ci("verify-d", ".agents/skills/verify-d/scripts/sprawdz_d.py"))

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "FAIL PODSTAWA verify-d" in result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI FAIL | PODSTAWA verify-d"


@pytest.mark.parametrize(("parts", "chosen"), [("", 1), ("ci-czesci: 1\n", 1), ("ci-czesci: 4\n", 4)], ids=["bez klucza", "jedna", "cztery"])
def test_podstawa_dzieli_sie_najwyzej_na_tyle_czesci_ile_mowi_ci_czesci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parts: str, chosen: int) -> None:
    command = ".agents/skills/verify-d/scripts/sprawdz_d.py --feature all"
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": "MUTATIONS = ()\n"})
    _skill(tmp_path, "verify-d", {"sprawdz_d.py": CHECKED_IN_CI.format(code=0)}, _with_ci("verify-d", command).replace(f"ci: {command}\n", f"ci: {command}\n{parts}"))
    tool = _load_tool(monkeypatch)

    katalog = tool.Katalog.skanuj(tmp_path)

    assert [(step.key, step.parts) for step in katalog.kroki] == [("verify-a/check_a_mutations.py", 1), ("verify-d/ci", chosen)]
    assert katalog.bledy == {}


@pytest.mark.parametrize("value", ["0", "osiem", "-2", ""])
def test_zly_klucz_ci_czesci_daje_fail_podstawy(tmp_path: Path, value: str) -> None:
    command = ".agents/skills/verify-d/scripts/sprawdz_d.py"
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-d", {"sprawdz_d.py": CHECKED_IN_CI.format(code=0)}, _with_ci("verify-d", command).replace(f"ci: {command}\n", f"ci: {command}\nci-czesci: {value}\n"))

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "FAIL PODSTAWA verify-d: ci-czesci w .agents/skills/verify-d/SKILL.md nie jest liczbą części od 1" in result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI FAIL | PODSTAWA verify-d"


@pytest.mark.parametrize("command", ["docs/opis.md", "", ".agents/skills/verify-d/scripts/nie_ma.py"])
def test_klucz_ci_bez_skryptu_z_repozytorium_daje_fail(tmp_path: Path, command: str) -> None:
    _skill(tmp_path, "verify-a", {"check_a_mutations.py": PASSING})
    _skill(tmp_path, "verify-d", {}, _with_ci("verify-d", command))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/opis.md").write_text("opis\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "FAIL PODSTAWA verify-d: ci w .agents/skills/verify-d/SKILL.md nie zaczyna się skryptem .py z repozytorium" in result.stdout
    assert result.stdout.splitlines()[-1] == "MUTACJE SKILLI FAIL | PODSTAWA verify-d"


def test_krok_skilla_biegnie_w_checkoucie_swojego_skilla_a_nie_w_katalogu_biezacym_ani_checkoucie_narzedzia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run`` uruchamia krok w korzeniu checkoutu, w którym leży jego skill (``Step.root``), więc polecenie ``ci:``
    i ścieżki od korzenia w skrypcie trafiają w pliki tego checkoutu, gdziekolwiek stoi narzędzie i proces."""

    checkout = tmp_path / "checkout"
    script = (
        "import os\nfrom pathlib import Path\n\nMUTATIONS = ()\n\nif __name__ == '__main__':\n"
        "    Path(__file__).with_name('katalog.txt').write_text(os.getcwd(), encoding='utf-8')\n    print('MUTACJE OK')\n"
    )
    _skill(checkout, "verify-a", {"check_a_mutations.py": script})
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(TOOLS / "ci"))
    import mutacje_skilli

    krok = _load_tool(monkeypatch).Katalog.skanuj(checkout).krok(Klucz.z_tekstu("skill:verify-a/check_a_mutations.py"))

    assert mutacje_skilli.run(krok, limit_s=60).powod is None
    assert Path((checkout / ".agents/skills/verify-a/scripts/katalog.txt").read_text(encoding="utf-8")).resolve() == checkout.resolve()


SHAPE_GAPS = ROOT / "tests" / "fixtures" / "granice_ksztaltow.py"


def _shape_gaps(root: Path) -> dict[str, list[str]]:
    """Luki granic kształtów każdego eksploratora skilla ``verify-*`` w ``root``, po ścieżce eksploratora. Kod
    eksploratora wykonuje własny proces z limitem czasu, nie proces pytest (#651)."""

    gaps = {}
    for explorer in sorted((root / ".agents" / "skills").glob("verify-*/scripts/explore_*.py")):
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(SHAPE_GAPS), str(TOOLS), str(explorer)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert done.returncode in (0, GAPS), done.stdout + done.stderr
        gaps[explorer.relative_to(root).as_posix()] = json.loads(done.stdout.splitlines()[-1])
    return gaps


def test_kazde_przyjete_ryzyko_i_znane_ustalenie_eksploratora_ma_mutacje_tuz_za_granica_kazdej_czesci_ksztaltu() -> None:
    """Przyjęte ryzyko albo znane ustalenie, które wybacza szerzej niż jego historia, przepuszcza zepsuty kod jako znany
    (#867 runda 3, #916 rundy 1 i 2). Każdy wpis ``ACCEPTED_RISKS`` i ``KNOWN_FINDINGS`` eksploratora skilla
    ``verify-*`` ma jawny kształt i w ``BOUNDARIES`` skryptu mutacji skilla mutację tuż za granicą każdej jego części
    (``tests/fixtures/granice_ksztaltow.py``); nazwy wpisów i części pochodzą z kodu eksploratora."""

    gaps = _shape_gaps(ROOT)

    assert len(gaps) >= 5, gaps
    assert {explorer: found for explorer, found in gaps.items() if found} == {}


_SHAPED = '''from dataclasses import dataclass
import enum


class Rodzaj(enum.Enum):
    A = "a"
    B = "b"


@dataclass(frozen=True)
class Ksztalt:
    krok: frozenset[str]
    rodzaj: frozenset[Rodzaj]
    stan: int


@dataclass(frozen=True)
class Wpis:
    name: str
    shape: Ksztalt


ACCEPTED_RISKS = (Wpis("ryzyko", Ksztalt(frozenset({"zapis"}), frozenset(Rodzaj), 1)),)
KNOWN_FINDINGS = {("ZNANE", 1): Wpis("ustalenie", Ksztalt(frozenset({"zapis"}), frozenset({Rodzaj.A}), 2))}
'''
_TABLE = '''from pathlib import Path

from mutacje import Edit, Mutation


def m(name, expected="X: NOWE NARUSZENIE", explorer="explore_x.py"):
    return Mutation(name, (Edit(Path("a.py"), "a", "b"),), (f".agents/skills/verify-x/scripts/{explorer}",), "", expected)


BOUNDARIES = {
    "ryzyko": {"krok": (m("krok ryzyka"),), "stan": (m("stan ryzyka"),)},
    "ustalenie": {"krok": (m("krok ustalenia"),), "rodzaj": (m("rodzaj ustalenia"),), "stan": (m("stan ustalenia"),)},
}
MUTATIONS = tuple(
    mutation
    for parts in BOUNDARIES.values()
    for mutations in (parts.values() if isinstance(parts, dict) else [parts])
    for mutation in mutations
)
'''


@pytest.mark.parametrize(
    ("explorer", "table", "expected"),
    [
        pytest.param(_SHAPED, _TABLE, [], id="kazda-czesc-poza-calym-wyliczeniem-ma-mutacje"),
        pytest.param(
            _SHAPED,
            _TABLE.replace('"stan": (m("stan ryzyka"),)', '"rodzaj": (m("rodzaj ryzyka"),)'),
            [
                "ryzyko: część stan bez mutacji tuż za granicą w check_x_mutations.py",
                "ryzyko: check_x_mutations.py wymienia część rodzaj, której kształt nie zawęża",
            ],
            id="czesc-bez-mutacji-a-cale-wyliczenie-z-mutacja",
        ),
        pytest.param(
            _SHAPED,
            _TABLE.replace('m("stan ustalenia")', 'm("stan ustalenia", "X OK")'),
            ["ustalenie, część stan: mutacja stan ustalenia nie jest w MUTATIONS albo nie kończy się „NOWE NARUSZENIE”"],
            id="mutacja-bez-nowego-naruszenia",
        ),
        pytest.param(
            _SHAPED,
            _TABLE + "MUTATIONS = MUTATIONS[:-1]\n",
            ["ustalenie, część stan: mutacja stan ustalenia nie jest w MUTATIONS albo nie kończy się „NOWE NARUSZENIE”"],
            id="mutacja-spoza-tabeli",
        ),
        pytest.param(
            _SHAPED,
            _TABLE.replace('m("stan ustalenia")', 'm("stan ustalenia", explorer="explore_y.py")'),
            ["ustalenie, część stan: mutacja stan ustalenia nie uruchamia explore_x.py"],
            id="mutacja-innego-eksploratora",
        ),
        pytest.param(
            _SHAPED.replace('Wpis("ryzyko"', 'Wpis("inne"'),
            _TABLE,
            [
                "check_x_mutations.py: BOUNDARIES ma wpis ryzyko, którego eksplorator nie ma",
                "inne: część krok bez mutacji tuż za granicą w check_x_mutations.py",
                "inne: część stan bez mutacji tuż za granicą w check_x_mutations.py",
            ],
            id="wpis-bez-swojej-nazwy-w-tabeli",
        ),
        pytest.param(
            _SHAPED,
            _TABLE.replace('"ryzyko": {"krok": (m("krok ryzyka"),), "stan": (m("stan ryzyka"),)}', '"ryzyko": (m("krok ryzyka"),)'),
            ["ryzyko: check_x_mutations.py daje mutacje wpisu bez części, której każda dotyczy (mapa część → mutacje)"],
            id="mutacje-wpisu-bez-czesci",
        ),
        pytest.param(
            "ACCEPTED_RISKS = {('R', 1): 'opis'}\nKNOWN_FINDINGS = ()\n",
            "",
            ["ACCEPTED_RISKS opis: wpis bez nazwy albo bez jawnego kształtu (dataklasa w ``shape``)"],
            id="sygnatura-albo-predykat-zamiast-ksztaltu",
        ),
    ],
)
def test_straznik_granic_czerwieni_wpis_bez_jawnego_ksztaltu_albo_czesc_bez_mutacji_tuz_za_granica(
    tmp_path: Path, explorer: str, table: str, expected: list[str]
) -> None:
    _skill(tmp_path, "verify-x", {"explore_x.py": explorer, **({"check_x_mutations.py": table} if table else {})})

    gaps = _shape_gaps(tmp_path)

    assert gaps == {".agents/skills/verify-x/scripts/explore_x.py": expected}
