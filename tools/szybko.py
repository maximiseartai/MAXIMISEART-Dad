"""Szybko sprawdza zmianę: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą; uruchom po każdej zmianie przed pushem.

Agent uruchamia je po każdej zmianie; pełną bramką jest CI na GitHubie. Zmiana to pliki, którymi checkout,
razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie
``origin/main``). Kroki ruff i mypy, a przy zmianie w ``.github/`` zizmor i actionlint, to kroki ``tools/ci_lokalnie.py``, a pytest to jego krok z wybranymi
testami. Gdy ``.venv`` ma Pythona nowszego niż najstarszy z ``requires-python``, który CI też testuje, krok
``import src pod Pythonem <wersja>`` importuje każdy moduł ``src/`` tym Pythonem przez ``uv`` (bez ``uv`` pada), a gdy
starszego, krok ``Python <wersja> albo nowszy`` pada z drogą naprawy (``tools/setup_worktree.py``).
Kroki biegną naraz, a gdy padnie inny krok, szybko przerywa krok pytest i wypisuje, że go przerwał.

Zmianę, testy dotknięte zmianą i ich odległość od niej liczy ``tools/lib/wplyw_zmiany.py`` z grafu zależności,
który wynika z samego kodu, więc świeży worktree wybiera tak samo. Zmiana pliku, od którego zależy każdy test
(``Context.TESTS`` tego modułu: konfiguracja i zależności, ``conftest.py`` każdego testu i fixture gita, którą
wczytuje dla całej sesji), wybiera wszystkie testy. Test, który już przeszedł na tych samych plikach, nie biegnie
drugi raz: pamięć zielonych testów leży w katalogu gita worktree. Krok pytest bierze ``czasy_ci.WORKERY_LOKALNE``
workerów, chyba że ustawiono ``PYTEST_XDIST_AUTO_NUM_WORKERS``, a ściana i budżet są na tylu samych workerów.

Z wybranych testów biegną zawsze zmienione pliki testów (``plan``), a dalsze po odległości od zmiany w grafie
zależności i czasie w CI rosnąco: zależne wprost od zmienionego pliku (odległość 1), dopóki mieszczą się w ścianie
``WALL_S``, czyli krok pytest kończy się przed limitem 600 s polecenia Basha agenta, a dalsze w budżecie ``BUDGET_S``. Czas pliku to jego koszt na Linuksie z ostatnich runów main (``czasy_ci.lokalne``,
kopia w ``.git/czasy-ci`` odświeżana raz na dobę, a po nieudanym pobraniu w następnym przebiegu); bez niej, na przykład
bez sieci, każdy plik waży 0 i biegnie, a szybko mówi to linią ``SZYBKO | bez czasów CI (<przyczyna>)``. Test, który importuje albo
czyta zmieniony plik konfiguracji, ma najwyżej 2, więc biegnie w budżecie przed testami bez drogi w grafie. Resztę liczy pełny pytest w CI, a szybko wypisuje ją przed wynikiem
jako „zostawione CI”, więc ``SZYBKO OK`` znaczy, że przeszły uruchomione testy.

Testy ``STRUCTURE`` modułu wpływu zmiany (strażnicy reguł z ``RULE_GUARDS`` w ``tests/test_szybko.py`` oraz testy całego
repozytorium) biegną przy każdej zmianie, a gdy ``--baza`` poszła dalej niż HEAD, także na mergu z nią (to drzewo
sprawdza CI PR-u; numer ADR zajęty równolegle pada dopiero tam). Na mergu biegną tylko one, bez mypy, testów
dotkniętych zmianą i workerów xdist, razem z pozostałymi krokami. Zapadki (``ZAPADKI``) biegną przy każdej zmianie
tylko w szybko, bo zadania pytest w CI nie mają bazy zmiany (reguły ast-grep na dodanych liniach całego repozytorium
ma też zadanie CI „Ruff, mypy”), i liczą dodane linie od ``merge-base`` HEAD z ``--baza`` (zmienna ``ZAPADKA_BAZA``).
Merge z konfliktem szybko pomija z linią ``UWAGA``, a merge, którego git nie policzy (``git merge-tree`` z kodem
innym niż konflikt), wywraca ten krok z powodem.
Szybko nie pobiera ``origin``, więc merge jest z bazą z ostatniego ``git fetch``. Nie uruchamia zadań CI
``mutations`` (skrypty mutacji skilli), ``Frontend``, E2E ani Timing guard.

Krok ``rozjazd modelu`` pyta ``tools/lib/rozjazd_modelu.py`` o każdy skill z ``model/definicje.json``, którego podstawę
``ci:`` zmiana uruchomiłaby na pull request (``tools/lib/zakres_runu.py``): czy kod opisany jego modelem zmienił się od
skrótów z tego pliku. To samo pytanie w CI zadaje wykonanie zadania (``tools/ci/wykonaj_zadanie.py``) przed krokiem
skilla i kończy go porażką, więc szybko pada też, bez TLC, z nazwą skilla, pliku i definicji i krokami „Bring the model
in line” ze ``SKILL.md`` skilla.

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
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import czasy_ci
from kroki_lokalne import OUTPUT_ON_FAILURE, Step, environment, pytest_step, static_steps, workflow_steps
import potomne
from repo import BASE, ROOT
import repo
import rozjazd_modelu
from wplyw_zmiany import STRUCTURE, Context, Repository, changed_since, run_all, with_structure
import wyniki_testow
from zakres_runu import podstawa_na_pull_request

GREEN = "szybko-zielone.json"
# Zapadki padają tylko na liniach, które zmiana dodaje, więc biegną przy każdej zmianie jak ``STRUCTURE``. Plan CI ich
# nie ma, bo płytki checkout zadań pytest nie ma bazy zmiany i zapadka się tam pomija; reguły ast-grep na dodanych
# liniach całego repozytorium dostają ją w zadaniu CI „Ruff, mypy”.
ZAPADKI = ("tests/test_zapadki.py",)
# Zmienna, z której zapadki biorą bazę zmiany.
ZAPADKA_BAZA = "MAXIMISEART_ZAPADKA_BAZA"
# Sekundy czasów CI na workera. Porażki pytest w szybko z 23–24.10 łapie ten sam plan od 20 s wzwyż, bo prawie
# wszystkie padły w odległości 0–1 albo w testach struktury, więc budżet stoi blisko tej granicy.
BUDGET_S = 45.0
# Sekundy czasów CI na workera dla plików zależnych wprost od zmiany. Mac agenta biegnie wybór w 0,3–1,7 jego czasu
# w CI (20 przekroczeń limitu 5–12.11, mediana 0,6, p90 0,88), więc z testami struktury (~40 s na workera) przy p90
# krok pytest kończy się przed ~480 s, pod limitem 600 s polecenia Basha agenta. Pod obciążeniem innymi agentami limitu
# ściana nie zapewnia: przegląd #1486 zmierzył 603 s przy load5 16–53.
WALL_S = 500.0
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


def plan(
    tests: Iterable[str],
    distances: dict[str, int],
    costs: czasy_ci.KosztyPlikow,
    *,
    workers: int,
    budget_s: float = BUDGET_S,
    wall_s: float = WALL_S,
) -> Plan:
    """Pliki zmienione (odległość 0) biegną zawsze. Dalsze, po odległości i koszcie rosnąco, biegną, gdy suma kosztów
    na ``workers`` workerów kroku pytest mieści się jeszcze w ``wall_s`` (odległość 1) albo w ``budget_s`` (dalsze)."""

    cost = {test: costs.s(test) for test in tests}
    used = 0.0
    run, deferred = [], []
    for test in sorted(cost, key=lambda test: (distances.get(test, math.inf), cost[test], test)):
        distance = distances.get(test, math.inf)
        limit = math.inf if distance == 0 else (wall_s if distance == 1 else budget_s) * workers
        if used + cost[test] <= limit:
            run.append(test)
            used += cost[test]
        else:
            deferred.append(test)
    return Plan(tuple(sorted(run)), tuple(sorted(deferred)), sum(cost[test] for test in deferred))


def _select(changed: frozenset[str]) -> Selection:
    impact = Repository.scan(ROOT).impact(changed)
    full = run_all(changed, Context.TESTS)
    return Selection({test: impact.fingerprint(test) for test in impact.tests}, impact.distances, f"zmiana w {', '.join(full)}" if full else None)


def _times(root: Path) -> czasy_ci.KosztyPlikow:
    costs, why = czasy_ci.lokalne(root)
    if why is not None:
        print(f"SZYBKO | bez czasów CI ({why}): każdy plik waży 0, więc biegnie cały wybór", flush=True)
    return costs


@dataclass(frozen=True)
class GreenMemory:
    path: Path

    @classmethod
    def of_checkout(cls) -> GreenMemory:
        return cls(ROOT / repo.git(ROOT, "rev-parse", "--git-path", GREEN).strip())

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
        tests = wyniki_testow.testy(junit)
    except (OSError, ValueError):
        return set()
    ran = set(ran)
    passed = {test.plik for test in tests if test.plik in ran} - {test.plik for test in tests if test.wynik == "padł"}
    return {str(plik) for plik in passed}


def _merge_steps(base: str, copies: ExitStack) -> list[Step]:
    """Krok testów struktury na mergu HEAD z ``base``; bez kroku, gdy ``base`` jest w HEAD albo merge ma konflikt, a krok,
    który pada z powodem, gdy git nie umie policzyć mergu."""

    if repo.is_ancestor(ROOT, base, "HEAD"):
        return []
    name = f"testy struktury po mergu z {base}"
    try:
        merged = repo.merge_tree(ROOT, "HEAD", base)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr.strip().splitlines() or [f"kod {error.returncode}"])[0]
        return [_failing(ROOT, name, f"git merge-tree z {base}: {reason}")]
    if merged.conflicts:
        print(f"UWAGA: merge z {base} ma konflikt w {', '.join(merged.conflicts)}; testy struktury po mergu pominięte", flush=True)
        return []
    author = ("-c", "user.name=szybko", "-c", "user.email=szybko@localhost")
    merge = repo.git(ROOT, *author, "commit-tree", merged.tree, "-p", "HEAD", "-p", base, "-m", f"szybko: HEAD z {base}").strip()
    copy = copies.enter_context(potomne.commit_copy(ROOT, merge))
    # Biegnie razem z krokiem pytest, więc bez workerów xdist nie podwaja liczby rdzeni szybko.
    return [pytest_step(copy, name, (*STRUCTURE, "-n", "0"))]


def _pytest_arguments(tests: Iterable[str], junit: Path) -> tuple[str, ...]:
    chosen = with_structure(tests)
    return (*chosen, *(path for path in ZAPADKI if path not in chosen), *wyniki_testow.zapis(junit))


def _failing(root: Path, name: str, why: str) -> Step:
    return Step(name, "pytest", (sys.executable, "-c", f"raise SystemExit({why!r})"), root)


def _imports_on_oldest(root: Path) -> list[Step]:
    """CI testuje też najstarszy Python z ``requires-python``, a ``.venv`` bywa nowszy: kod tylko dla nowszego Pythona
    pada dopiero w CI. Krok jest pusty, gdy szybko biegnie tym najstarszym albo projekt go nie podaje, a pada, gdy
    ``.venv`` jest starszy, bo został po podniesieniu ``requires-python`` (13.11: 3.11 → 3.13)."""

    try:
        required = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    oldest = re.fullmatch(r">=\s*(\d+)\.(\d+)", str(required).strip())
    if oldest is None:
        why = f"requires-python {required!r} nie ma postaci >=X.Y, więc szybko nie zna najstarszego Pythona"
        return [_failing(root, "import src pod najstarszym Pythonem", why)]
    version = f"{oldest[1]}.{oldest[2]}"
    if sys.version_info[:2] < (int(oldest[1]), int(oldest[2])):
        why = f"szybko biegnie Pythonem {sys.version_info[0]}.{sys.version_info[1]}, starszym niż requires-python {required!r}: odtwórz .venv przez python3 tools/setup_worktree.py"
        return [_failing(root, f"Python {version} albo nowszy", why)]
    if sys.version_info[:2] == (int(oldest[1]), int(oldest[2])):
        return []
    name = f"import src pod Pythonem {version}"
    uv = shutil.which("uv")
    if uv is None:
        return [_failing(root, name, f"brak uv, więc szybko nie sprawdzi Pythona {version}: zainstaluj uv albo .venv z {version}")]
    requirements = ("--with-requirements", "requirements.txt") if (root / "requirements.txt").is_file() else ()
    return [Step(name, "pytest", (sys.executable, "-c", WITH_UV, uv, version, IMPORT_ALL, *requirements), root)]


def _steps(root: Path, tests: Iterable[str], junit: Path, changed: frozenset[str]) -> list[Step]:
    workflows = workflow_steps(root) if any(path.startswith(".github/") for path in changed) else []
    return [*static_steps(root), *workflows, pytest_step(root, "pytest", _pytest_arguments(tests, junit)), *_imports_on_oldest(root)]


def _environment(root: Path, base: str) -> dict[str, str]:
    return {
        **environment(root),
        "PYTEST_XDIST_AUTO_NUM_WORKERS": str(czasy_ci.workery_lokalne()),
        "PYTHON": sys.executable,
        ZAPADKA_BAZA: base,
    }


def _run_all(steps: list[Step], base: str, interruptible: Step | None = None) -> tuple[list[str], list[str]]:
    """Kroki naraz, z bazą zapadek ``base``; zwraca nazwy kroków, które padły, i przerwanych. Gdy padnie krok inny niż
    ``interruptible``, ``interruptible`` jest przerywany: wynik i tak jest FAIL, a na koniec długiego kroku pytest nie
    trzeba czekać."""

    stop, failure = threading.Event(), threading.Event()

    def run(step: Step) -> tuple[bool | None, str, float]:
        started = time.monotonic()
        try:
            done = potomne.run(
                step.command, cwd=step.cwd, env=_environment(step.cwd, base), stop=failure if step is interruptible else stop
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
                print("\n".join(output.rstrip().splitlines()[-OUTPUT_ON_FAILURE :]), flush=True)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        failure.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)
    return failed, interrupted


def _model_drift(root: Path, changed: frozenset[str]) -> list[str]:
    """Rozjazdy modelu skilli, których podstawę ``ci:`` zmiana ``changed`` uruchomiłaby na pull request: w CI ta podstawa
    pada na nich, zanim ruszy."""

    return [
        f"{skill.name}: {found}"
        for skill in rozjazd_modelu.skille(root)
        if podstawa_na_pull_request(skill, changed)[0] and (found := rozjazd_modelu.rozjazd(skill, root)) is not None
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
    chosen = plan(memory.to_run(selection), selection.distances, _times(ROOT), workers=czasy_ci.workery_lokalne())
    print(_describe(selection, chosen, changed, args.baza), flush=True)
    if drift := _model_drift(ROOT, changed):
        print("FAIL rozjazd modelu (bez TLC)\n" + "\n".join(drift), flush=True)
    junit = memory.path.with_name(f"szybko-junit-{os.getpid()}.xml")
    steps = _steps(ROOT, chosen.run, junit, changed)
    with ExitStack() as copies:
        steps += _merge_steps(args.baza, copies)
        base = repo.merge_base(ROOT, "HEAD", args.baza)
        failed, interrupted = _run_all(steps, base, next(step for step in steps if step.name == "pytest"))
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
