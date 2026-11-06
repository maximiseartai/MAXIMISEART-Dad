"""Szybko sprawdza zmianę: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą; uruchom po każdej zmianie przed pushem.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi
testami. Gdy ``.venv`` ma Pythona nowszego niż najstarszy z ``requires-python``, który CI też testuje, krok
``import src pod Pythonem <wersja>`` importuje każdy moduł ``src/`` tym Pythonem przez ``uv`` (bez ``uv`` pada).
Kroki biegną naraz, a gdy padnie inny krok, szybko przerywa krok pytest i wypisuje, że go przerwał.

Zmianę, testy dotknięte zmianą i ich odległość od niej liczy ``tools/lib/wplyw_zmiany.py`` z grafu zależności,
który wynika z samego kodu, więc świeży worktree wybiera tak samo. Zmiana pliku, od którego zależy każdy test
(``Context.TESTS`` tego modułu: konfiguracja i zależności, ``conftest.py`` każdego testu i fixture gita, którą
wczytuje dla całej sesji), wybiera wszystkie testy. Test, który już przeszedł na tych samych plikach, nie biegnie
drugi raz: pamięć zielonych testów leży w katalogu gita worktree. Krok pytest bierze ``WORKERS`` workerów, chyba że
ustawiono ``PYTEST_XDIST_AUTO_NUM_WORKERS``.

Z wybranych testów biegną zawsze pliki w odległości najwyżej 1 od zmiany w grafie zależności (``plan``), czyli
zmienione albo zależne wprost od zmienionego pliku, a dalsze po odległości i czasie w CI rosnąco, dopóki mieszczą
się w budżecie ``BUDGET_S``. Czas pliku to jego koszt na Linuksie z ostatnich runów main (``tools/ci/czasy_ci.py``,
kopia w ``.git/czasy-ci`` odświeżana raz na dobę, a po nieudanym pobraniu w następnym przebiegu); bez niej, na przykład
bez sieci, każdy plik waży 0 i biegnie, a szybko mówi to linią ``SZYBKO | bez czasów CI (<przyczyna>)``. Test, który importuje albo
czyta zmieniony plik konfiguracji, ma najwyżej 2, więc biegnie w budżecie przed testami bez drogi w grafie. Resztę liczy pełny pytest w CI, a szybko wypisuje ją przed wynikiem
jako „zostawione CI”, więc ``SZYBKO OK`` znaczy, że przeszły uruchomione testy.

Testy ``STRUCTURE`` modułu wpływu zmiany (reguły z tabel w ``AGENTS.md``, ``CODING_STANDARDS.md`` i ``docs/agents/`` oraz testy całego
repozytorium) biegną przy każdej zmianie, a gdy ``--baza`` poszła dalej niż HEAD, także na mergu z nią (to drzewo
sprawdza CI PR-u; numer ADR zajęty równolegle pada dopiero tam). Na mergu biegną tylko one, bez mypy, testów
dotkniętych zmianą i workerów xdist, razem z pozostałymi krokami.
Szybko nie pobiera ``origin``, więc merge jest z bazą z ostatniego ``git fetch``. Nie uruchamia zadań CI
``mutations`` (skrypty mutacji skilli), ``Frontend``, E2E ani Timing guard.

Krok ``rozjazd modelu`` pyta ``tools/lib/rozjazd_modelu.py`` o każdy skill z ``model/definicje.json``, którego podstawę
``ci:`` zmiana uruchomiłaby na pull request (``tools/lib/zakres_runu.py``): czy kod opisany jego modelem TLA+ zmienił się
od Sync commit z jego ``SKILL.md``. To samo pytanie skrypt modelu zadaje w CI przed TLC i tam pada, więc szybko pada też,
bez TLC, z nazwą skilla, pliku i definicji i krokami „Bring the model in line” ze ``SKILL.md`` skilla.

Kończy się ``SZYBKO OK`` albo ``SZYBKO FAIL | <kroki>``, z dopiskiem `` | pytest przerwany``, gdy szybko przerwał
krok pytest.

    .venv/bin/python tools/szybko.py
    .venv/bin/python tools/szybko.py --baza feat/galaz-rodzica
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tomllib
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

import ci_lokalnie
import czasy_ci
from mutacje import environment
import potomne
import rozjazd_modelu
from wplyw_zmiany import STRUCTURE, Context, Repository, changed_since, run_all, with_structure
from zakres_runu import podstawa_na_pull_request

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
GREEN = "szybko-zielone.json"
WORKERS = "4"
# Tor CI, którego czasy plików waży szybko: Linux, jak komputer agenta, nie Windows.
# Sekundy czasów CI na workera. Porażki pytest w szybko z 23–24.10 łapie ten sam plan od 20 s wzwyż, bo prawie
# wszystkie padły w odległości 0–1 albo w testach struktury, więc budżet stoi blisko tej granicy.
BUDGET_S = 45.0
# Importuje każdy moduł ``src/`` i wypisuje te, które padają; moduł, który się nie importuje, wywraca każdy test.
IMPORT_ALL = """\
import importlib, pathlib, sys
src = pathlib.Path(sys.argv[1])
names = sorted({".".join(p.relative_to(src).with_suffix("").parts).removesuffix(".__init__") for p in src.rglob("*.py")})
failed = []
for name in names:
    try:
        importlib.import_module(name)
    except Exception as error:
        failed.append(f"{name}: {type(error).__name__}: {error}")
print("\\n".join(failed) or f"{len(names)} modułów")
sys.exit(3 if failed or not names else 0)
"""
# ``uv run --offline`` z ciepłym cache działa bez sieci; dopiero porażka samego uv (inny kod niż 0 i 3) pyta sieć.
WITH_UV = """\
import subprocess, sys
uv, version, imports, *requirements = sys.argv[1:]
command = [uv, "run", "--no-project", "--quiet", "--python", version, *requirements, "python", "-c", imports, "src"]
code = subprocess.run([*command[:2], "--offline", *command[2:]]).returncode
if code not in (0, 3):
    code = subprocess.run(command).returncode
sys.exit(code)
"""


@dataclass(frozen=True)
class Selection:
    fingerprints: dict[str, str]
    distances: dict[str, int]
    full_reason: str | None = None


@dataclass(frozen=True)
class Plan:
    """Pliki testów, które biegną, i te zostawione CI (``deferred_s`` to ich czas w CI)."""

    run: tuple[str, ...]
    deferred: tuple[str, ...]
    deferred_s: float


def plan(tests: Iterable[str], distances: dict[str, int], times: dict[str, float], budget_s: float = BUDGET_S) -> Plan:
    """Pliki w odległości najwyżej 1 od zmiany biegną zawsze, także ponad budżet. Dalsze, po odległości i koszcie
    rosnąco, biegną, gdy suma kosztów na ``WORKERS`` workerów mieści się jeszcze w ``budget_s``. Koszt pliku bez
    pomiaru to mediana pomiarów."""

    default = statistics.median(times.values()) if times else 0.0
    cost = {test: times.get(test, default) for test in tests}
    capacity, used = budget_s * int(WORKERS), 0.0
    run, deferred = [], []
    for test in sorted(cost, key=lambda test: (distances.get(test, math.inf), cost[test], test)):
        if distances.get(test, math.inf) <= 1 or used + cost[test] <= capacity:
            run.append(test)
            used += cost[test]
        else:
            deferred.append(test)
    return Plan(tuple(sorted(run)), tuple(sorted(deferred)), sum(cost[test] for test in deferred))


def _select(changed: frozenset[str]) -> Selection:
    impact = Repository.scan(ROOT).impact(changed)
    full = run_all(changed, Context.TESTS)
    return Selection({test: impact.fingerprint(test) for test in impact.tests}, impact.distances, f"zmiana w {', '.join(full)}" if full else None)


def _times(root: Path) -> dict[str, float]:
    times = czasy_ci.z_mainu(czasy_ci.katalog_checkoutu(root), odswiez_po_s=czasy_ci.ODSWIEZ_S)
    costs = times.pliki(czasy_ci.TOR_LOKALNY)
    if not costs:
        why = times.blad or f"brak plików testów toru {czasy_ci.TOR_LOKALNY} w {czasy_ci.ARTEFAKT}"
        print(f"SZYBKO | bez czasów CI ({why}): każdy plik waży 0, więc biegnie cały wybór", flush=True)
    return costs


@dataclass(frozen=True)
class GreenMemory:
    path: Path

    @classmethod
    def of_checkout(cls) -> GreenMemory:
        return cls(ROOT / _git("rev-parse", "--git-path", GREEN).strip())

    def to_run(self, selection: Selection) -> list[str]:
        green = self._recalled()
        return [test for test, fingerprint in selection.fingerprints.items() if green.get(test) != fingerprint]

    def remember(self, selection: Selection, junit: Path, ran: Iterable[str]) -> None:
        green = {test: selection.fingerprints[test] for test in _passed(junit, ran)}
        written = self.path.with_suffix(".tmp")
        written.write_text(json.dumps({**self._recalled(), **green}, indent=1, sort_keys=True), encoding="utf-8")
        written.replace(self.path)

    def _recalled(self) -> dict[str, str]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(test): str(fingerprint) for test, fingerprint in loaded.items()} if isinstance(loaded, dict) else {}


def _passed(junit: Path, ran: Iterable[str]) -> set[str]:
    try:
        cases = list(ET.parse(junit).iter("testcase"))
    except (OSError, ET.ParseError):
        return set()
    ran = set(ran)
    seen: set[str] = set()
    failed: set[str] = set()
    for case in cases:
        # ``tests.test_x`` albo ``tests.test_x.TestKlasa``
        parts = case.get("classname", "").split(".")
        test = next((path for end in range(len(parts), 0, -1) if (path := "/".join(parts[:end]) + ".py") in ran), None)
        if test is None:
            continue
        seen.add(test)
        if case.find("failure") is not None or case.find("error") is not None:
            failed.add(test)
    return seen - failed


def _git(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return completed.stdout


def _merge_with(base: str) -> str | None:
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT, capture_output=True, check=False)
    if ancestor.returncode == 0:
        return None
    merged = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "HEAD", base],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    tree, *conflicts = merged.stdout.split("\n\n", 1)[0].splitlines()
    if merged.returncode != 0:
        print(f"UWAGA: merge z {base} ma konflikt w {', '.join(conflicts)}; testy struktury po mergu pominięte", flush=True)
        return None
    author = ("-c", "user.name=szybko", "-c", "user.email=szybko@localhost")
    return _git(*author, "commit-tree", tree, "-p", "HEAD", "-p", base, "-m", f"szybko: HEAD z {base}").strip()


def _pytest_arguments(tests: Iterable[str], junit: Path) -> tuple[str, ...]:
    return (*with_structure(tests), f"--junitxml={junit}")


def _pytest(root: Path, name: str, arguments: Iterable[str]) -> ci_lokalnie.Step:
    pytest = next(step for step in ci_lokalnie._steps(root) if step.job == "pytest")
    return replace(pytest, name=name, command=(*pytest.command, *arguments))


def _failing(root: Path, name: str, why: str) -> ci_lokalnie.Step:
    return ci_lokalnie.Step(name, "pytest", "", (sys.executable, "-c", f"raise SystemExit({why!r})"), root)


def _imports_on_oldest(root: Path) -> list[ci_lokalnie.Step]:
    """CI testuje też najstarszy Python z ``requires-python``, a ``.venv`` bywa nowszy: kod tylko dla nowszego Pythona
    pada dopiero w CI. Krok jest pusty, gdy szybko biegnie tym najstarszym albo projekt go nie podaje."""

    try:
        required = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    oldest = re.fullmatch(r">=\s*(\d+)\.(\d+)", str(required).strip())
    if oldest is None:
        why = f"requires-python {required!r} nie ma postaci >=X.Y, więc szybko nie zna najstarszego Pythona"
        return [_failing(root, "import src pod najstarszym Pythonem", why)]
    if sys.version_info[:2] <= (int(oldest[1]), int(oldest[2])):
        return []
    version = f"{oldest[1]}.{oldest[2]}"
    name = f"import src pod Pythonem {version}"
    uv = shutil.which("uv")
    if uv is None:
        return [_failing(root, name, f"brak uv, więc szybko nie sprawdzi Pythona {version}: zainstaluj uv albo .venv z {version}")]
    requirements = ("--with-requirements", "requirements.txt") if (root / "requirements.txt").is_file() else ()
    return [ci_lokalnie.Step(name, "pytest", "", (sys.executable, "-c", WITH_UV, uv, version, IMPORT_ALL, *requirements), root)]


def _steps(root: Path, tests: Iterable[str], junit: Path) -> list[ci_lokalnie.Step]:
    return [*ci_lokalnie.static_steps(root), _pytest(root, "pytest", _pytest_arguments(tests, junit)), *_imports_on_oldest(root)]


def _environment(root: Path) -> dict[str, str]:
    # Gołe ``-n auto`` bierze wszystkie rdzenie Maca, na którym pracuje naraz kilku agentów.
    return {"PYTEST_XDIST_AUTO_NUM_WORKERS": WORKERS, **environment(root), "PYTHON": sys.executable}


def _run_all(steps: list[ci_lokalnie.Step], interruptible: ci_lokalnie.Step | None = None) -> tuple[list[str], list[str]]:
    """Kroki naraz; zwraca nazwy kroków, które padły, i przerwanych. Gdy padnie krok inny niż ``interruptible``,
    ``interruptible`` jest przerywany: wynik i tak jest FAIL, a na koniec długiego kroku pytest nie trzeba czekać."""

    stop, failure = threading.Event(), threading.Event()

    def run(step: ci_lokalnie.Step) -> tuple[bool | None, str, float]:
        started = time.monotonic()
        try:
            done = potomne.run(
                step.command, cwd=step.cwd, env=_environment(step.cwd), stop=failure if step is interruptible else stop
            )
        except potomne.Stopped:
            return None, "", time.monotonic() - started
        if done.returncode:
            failure.set()
        return done.returncode == 0, done.stdout + done.stderr, time.monotonic() - started

    failed, interrupted = [], []
    pool = ThreadPoolExecutor(max_workers=len(steps))
    try:
        for step, (passed, output, elapsed) in zip(steps, pool.map(run, steps), strict=True):
            if passed is None:
                print(f"PRZERWANY {step.name} ({elapsed:.0f} s): padł inny krok, więc jego testy nie są sprawdzone", flush=True)
                interrupted.append(step.name)
                continue
            print(f"{'OK  ' if passed else 'FAIL'} {step.name} ({elapsed:.0f} s)", flush=True)
            if not passed:
                failed.append(step.name)
                print("\n".join(output.rstrip().splitlines()[-ci_lokalnie.OUTPUT_ON_FAILURE :]), flush=True)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        failure.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)
    return failed, interrupted


def _model_drift(root: Path, changed: frozenset[str]) -> list[str]:
    """Rozjazdy modelu skilli, których podstawę ``ci:`` zmiana ``changed`` uruchomiłaby na pull request: skrypt modelu w
    niej pada na nich przed TLC. Szybko nie pobiera ``origin``, więc nie dopobiera historii do Sync commit."""

    return [
        f"{skill.name}: {found}"
        for skill in rozjazd_modelu.skille(root)
        if podstawa_na_pull_request(skill, changed)[0] and (found := rozjazd_modelu.rozjazd(skill, root, dopobierz=False)) is not None
    ]


def _describe(selection: Selection, chosen: Plan, changed: frozenset[str], base: str) -> str:
    kind = f"pełny zestaw ({selection.full_reason})" if selection.full_reason else "dotknięte zmianą"
    names = ", ".join(PurePosixPath(path).name for path in chosen.run) or "brak"
    green = len(selection.fingerprints) - len(chosen.run) - len(chosen.deferred)
    return (
        f"Zmiana: {len(changed)} plików od {base}. Testy {kind}: {len(selection.fingerprints)},"
        f" do uruchomienia {len(chosen.run)} ({names}), zielone na tych samych plikach {green}; i testy struktury."
    )


def _deferred(chosen: Plan, selected: int) -> str:
    names = ", ".join(PurePosixPath(path).name for path in chosen.deferred)
    return f"zostawione CI: {len(chosen.deferred)} z {selected} plików testów (~{chosen.deferred_s:.0f} s w CI): {names}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, od której liczy się zmiana (domyślnie {BASE}).")
    args = parser.parse_args(argv)
    try:
        changed = changed_since(ROOT, args.baza)
    except subprocess.CalledProcessError:
        print(f"SZYBKO FAIL | nieznana baza {args.baza}")
        return 1
    selection = _select(changed)
    memory = GreenMemory.of_checkout()
    chosen = plan(memory.to_run(selection), selection.distances, _times(ROOT))
    print(_describe(selection, chosen, changed, args.baza), flush=True)
    if drift := _model_drift(ROOT, changed):
        print("FAIL rozjazd modelu (bez TLC)\n" + "\n".join(drift), flush=True)
    junit = memory.path.with_name(f"szybko-junit-{os.getpid()}.xml")
    steps = _steps(ROOT, chosen.run, junit)
    with ExitStack() as copies:
        if merge := _merge_with(args.baza):
            copy = copies.enter_context(potomne.commit_copy(ROOT, merge))
            # Biegnie razem z krokiem pytest, więc bez workerów xdist nie podwaja liczby rdzeni szybko.
            steps.append(_pytest(copy, f"testy struktury po mergu z {args.baza}", (*STRUCTURE, "-n", "0")))
        failed, interrupted = _run_all(steps, next(step for step in steps if step.name == "pytest"))
    failed = (["rozjazd modelu"] if drift else []) + failed
    memory.remember(selection, junit, chosen.run)
    junit.unlink(missing_ok=True)
    if chosen.deferred:
        print(_deferred(chosen, len(selection.fingerprints)))
    stopped = "".join(f" | {name} przerwany" for name in interrupted)
    print(f"SZYBKO FAIL | {', '.join(failed)}{stopped}" if failed else "SZYBKO OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
