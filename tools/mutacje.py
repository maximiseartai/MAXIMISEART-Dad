"""Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.

Przepis z korzenia checkoutu; po ``--`` stoją argumenty Pythona, który uruchomił narzędzie:

    # jedna mutacja: plik, kotwica (jej tekst stoi w pliku dokładnie raz) i zamiana
    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'if n > LIMIT:' 'if False:' \\
        -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu
    # mutacje z pliku JSON, naraz
    .venv/bin/python tools/mutacje.py --rownolegle --plik mutacje.json -- -m pytest -q -n 0 tests/test_x.py

    mutacje.json: "polecenie" (zamiast polecenia po --) i "oczekiwane" (początek ostatniej linii wyjścia, który
    wykrywa mutację zamiast kodu wyjścia) są opcjonalne
    [
      {"nazwa": "bez limitu", "zmiany": [["src/rozliczenia/x.py", "if n > LIMIT:", "if False:"]]},
      {"nazwa": "dwa miejsca", "zmiany": [["src/rozliczenia/x.py", "n = 1", "n = 2"], ["tools/y.py", "z", "w"]],
       "polecenie": ["-m", "pytest", "-q", "-n", "0", "tests/test_y.py"], "oczekiwane": "SPRAWDZENIE: NARUSZENIE"}
    ]

Pytest w jednym procesie to ``-n 0``: ``-p no:xdist`` pada na ``--dist`` z ``addopts`` w ``pyproject.toml``. Ścieżka
i ``-k`` muszą wybrać test, bo polecenie bez mutacji (podstawa) musi przejść, zanim mutacja czegoś dowiedzie. Mutację
NIEWYKRYTA narzędzie powtarza na merge-base HEAD z ``--baza`` (domyślnie origin/main; gałąź zbudowana na innej podaje
ją), a WYKRYTA tam to REGRES. Poza CI jedno uruchomienie ma najwyżej 100 mutacji (``ciezkie_ci.TARGETED``). Dowodem
jest tylko WYKRYTA, a narzędzie kończy się wtedy kodem 0 i linią ``MUTACJE OK``.

Zasady werdyktów, kopii, bramy typów, nocy, ``--jak-ci`` i ``MUTACJE_CZESC`` drukuje ``--zasady``.

Zasady werdyktów i przebiegu

Każda mutacja dostaje własną kopię checkoutu: odłączony ``git worktree`` z HEAD w katalogu
tymczasowym z naniesionymi niezacommitowanymi zmianami (także dodanymi do indeksu), więc ``git``
działa w niej jak w checkoucie. Checkout zostaje nietknięty, więc nie ma czego przywracać ani
nieaktualnych ``.pyc``. Polecenie biegnie Pythonem, który uruchomił narzędzie, w korzeniu kopii,
z ``PYTHONPATH`` na ``src`` kopii: edytowalna instalacja ``.venv`` wskazuje ``src`` checkoutu.

Mutacja zmienia jedną albo kilka kotwic, każdą obecną w swoim pliku dokładnie raz; inaczej jest
NIEAKTUALNA. Pusta kotwica w pliku, którego nie ma, tworzy go razem z katalogami. Zanim narzędzie
zepsuje kod, polecenie musi przejść na kopii bez mutacji, a jeśli mutacja oczekuje ostatniej
linii wyjścia, polecenie bez mutacji nie może się nią kończyć. Werdykty to ``Verdict``, a dowodem jest tylko
WYKRYTA: polecenie pada albo kończy się oczekiwaną linią. ZAWIESZENIE to test, który pytest-timeout skończył po
swoim limicie (linia ``Failed: Timeout (>…s) from pytest-timeout.`` metody ``signal`` albo linia ``+++ Timeout +++``
metody ``thread`` bez xdist); worker xdist, którego zabiła metoda ``thread`` (Windows), nie zostawia takiej linii, więc
tam ZAWIESZENIA nie ma, a werdykt daje kod wyjścia albo ``--limit-s``. PRZEKROCZONY CZAS to polecenie bez wyniku w
``--limit-s`` samego narzędzia. Mutacja, która nie zdąży zacząć się albo skończyć przed końcem czasu wywołującego
(``deadline`` w ``verdicts``), dostaje BEZ WERDYKTU.

ZAWIESZENIE czerwieni CI, bo pytest-timeout kończy test porażką. Dlatego ``in_ci`` liczy je jak WYKRYTA z dopiskiem, a
liczą tak noc (``tools/mutacje_zmiany.py``) i ``check_all`` skryptów mutacji skilli, więc nie trafia do issue
``Przeżyte mutacje z #N``. PRZEKROCZONY CZAS CI nie czerwieni, gdy każdy test mieści się w swoim limicie pytest-timeout
(test tylko wolniejszy), więc noc i skrypty skilli liczą go jak przeżytą. W narzędziu z wiersza poleceń, którego używa
przegląd PR, oba są porażką.

Mutację, którą polecenie przepuściło (NIEWYKRYTA, PRZEKROCZONY CZAS), noc (poza cofnięciem fragmentu do bazy, które
przywraca kod, który bramę przeszedł) i ``check_all`` skryptów skilli sprawdzają jeszcze bramą typów (``type_gate``):
krokami ruff i mypy obu systemów bramy pre-push (``tools/ci_lokalnie.py --tylko ruff,mypy``) na kopii z mutacją, z
diagnostykami w JSON. Gdy któryś zgłasza diagnostykę, która mówi, że kod jest błędny
(``wrong``: z ruff tylko niezdefiniowana nazwa i błąd składni, z mypy każdy błąd typów poza pozostałościami jak
``unused-ignore``), mutacja jest WYKRYTA PRZEZ BRAMĘ TYPÓW z nazwą kroku i tą diagnostyką, a ``in_ci`` liczy ją jak
WYKRYTA, bo takiej zmiany nie wpuszczą brama pre-push i zadanie CI „Ruff, mypy”. Diagnostyka, że coś zostało nieużyte
(F401, F841), nie liczy się: zostawia ją sama mutacja jednej linii, np. ``return wynik`` → ``return None``, więc nie
dowodzi, że test jest zbędny.
Brama biegnie tylko dla takich mutacji, raz najpierw bez mutacji, a gdy wtedy zgłasza cokolwiek, linia ``BRAMA TYPÓW
CZERWONA`` na stderr zostawia werdykty bez zmian; tak jest w zadaniach skryptów skilli w CI, które instalują tylko
``requirements.txt``, bez ruff i mypy (``ci.yml`` i ``mutacje-nocne.yml``), więc tam brama nic nie zmienia. Narzędzie
z wiersza poleceń bramy nie uruchamia: przegląd dowodzi swojego polecenia, a mypy sprawdza poleceniem ``-- -m mypy``.

Narzędzie z wiersza poleceń uruchamia każdą mutację NIEWYKRYTA na HEAD także na merge-base HEAD z ``--baza`` (bez
niezacommitowanych zmian), z podstawą jej polecenia na merge-base. Gdy tam jest WYKRYTA, dostaje REGRES: zmiana
osłabiła test, który ją łapał. Gdy merge-base to HEAD bez niezacommitowanych zmian, drugiego przebiegu nie ma, a gdy
merge-base nie ma (checkout bez ``--baza``), REGRES jest pominięty z linią ``MERGE-BASE`` na stderr.

Z ``--jak-ci [RUN]`` narzędzie pobiera artefakt ``plan`` runu CI ``RUN`` (bez numeru: ostatniego runu ``ci.yml``
gałęzi, którą śledzi bieżąca) i dla każdego zadania pytest toru systemu, na którym biegnie, w którym ten run postawił
plik testów zmieniony od merge-base, robi z każdej mutacji osobną mutację z poleceniem ``pytest -n 1`` z plikami tego
zadania. Odtwarza więc skład zadania tego runu, a nie planu z dzisiejszych czasów. Nie odtwarza podziału na workery:
CI biegnie z ``-n auto``, a tu cały skład dzieli jeden proces, więc sąsiad z innego workera CI też jest w nim. Plik,
który plan dzieli na udziały, biegnie cały.

    .venv/bin/python tools/mutacje.py --jak-ci 41204010349 --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod'

Mutacje biegną po kolei, bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` puszcza
naraz najwyżej ``PARALLEL`` (tyle, ile rdzeni ma komputer, i najwyżej 8), a ich polecenia dostają
``PYTEST_XDIST_AUTO_NUM_WORKERS=1`` (chyba że wywołujący je ustawił), bo gołe ``pytest -n auto`` w teście każdej z nich
bierze wszystkie rdzenie komputera.
Polecenia i kopie biegną przez ``tools/lib/potomne.py``: procesy potomne polecenia giną z jego końcem, a
przekroczony czas, przerwanie (Ctrl-C) i zabicie narzędzia kończą polecenie i usuwają kopie.

Lista dłuższa niż ``ciezkie_ci.TARGETED`` mutacji to ręczne ``change-mutations``: poza CI narzędzie odmawia
jej startu (kod 2 i linia ``CIĘŻKIE CI ODMOWA``) na zasadach ``tools/lib/ciezkie_ci.py``. Skrypty
``check_<co>_mutations.py`` skilli ``verify-*`` używają tego samego silnika przez ``check_all``, który
takiego limitu nie ma.

Z ``MUTACJE_CZESC=K/N`` w środowisku ``check_all`` sprawdza tylko K-tą z N części tabeli: mutacje w kolejności nazw,
co N-tą od K-tej, więc część nie zależy od kolejności tabeli, a N części sprawdza każdą mutację dokładnie raz. Podstawa
części to tylko polecenia jej mutacji, a część bez mutacji kończy się ``MUTACJE OK``. Tak plan CI
(``tools/plan_ci.py``) dzieli długi skrypt mutacji skilla na zadania bez zmiany skryptu.

``check_all`` drukuje na stderr czas polecenia każdej mutacji (linia ``CZAS``) i ostrzeżenie ``CZAS BLISKO LIMITU`` dla
mutacji, której polecenie trwało ponad połowę ``--limit-s`` (``NEAR_LIMIT``), więc rosnący czas widać w logu, zanim
stanie się PRZEKROCZONY CZAS; werdyktów, linii końcowej ani kodu wyjścia to nie zmienia. Ostrzeżenie (``NearLimit``)
czyta z wyjścia skryptu ``near_limits``, a nocne skrypty mutacji skilli zgłaszają je raz na mutację w issue PR-u
(``tools/mutacje_nocne.py``).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
import importlib
from itertools import pairwise
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import NamedTuple, Protocol, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
# ci_lokalnie (brama typów) importuje dopiero w funkcji, bo sam importuje ten moduł.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ciezkie_ci
import github
from jednostka import ZMIENNA_CZESCI, Czesc, Klucz, Rodzaj
from ostatnie_linie import MUTACJE_OK
import potomne
from repo import BASE, ROOT
import repo

TIMEOUT = 600
# Mutacji naraz najwyżej tyle, ile rdzeni ma komputer (4 vCPU runnera Windows CI), i najwyżej 8 (16 rdzeni Maca dzielą
# agenci). Osiem eksploratorów naraz na 4 vCPU dzieliło procesor, więc czas mutacji zależał od tego, ile ciężkich mutacji
# plan CI wrzucił do jednej części (do 600 s limitu, #963, #968).
PARALLEL = min(8, os.cpu_count() or 1)
# Cache mypy kroków bramy typów (``--cache-dir`` kroku Windows leży w nim), który kopia bez mutacji daje kopiom mutacji.
MYPY_CACHE = ".mypy_cache"
# Część ``--limit-s``, ponad którą czas polecenia mutacji daje ostrzeżenie ``CZAS BLISKO LIMITU`` w ``check_all``.
NEAR_LIMIT = 0.5
# Linie, którymi pytest-timeout kończy test po limicie, w pytest_timeout.py 2.4: ``PYTEST_FAILURE_MESSAGE`` metody
# ``signal`` jako błąd testu (``E   Failed: …``) albo w krótkim podsumowaniu (``FAILED <test> - Failed: …``) i nagłówek
# zrzutu stosów metody ``thread`` (``terminal.sep("+", title="Timeout")``). Cała linia, bo ten sam tekst w cudzysłowie
# drukuje też asercja testu, który go sprawdza.
PYTEST_TIMEOUT = re.compile(r"(?:E\s+|FAILED \S+ - )?(?P<hang>Failed: Timeout \(>[0-9.]+s\) from pytest-timeout\.)|(?P<thread>\++ Timeout \++)")
# Tyle ostatnich linii stdout i tyle stderr czerwonej podstawy ``check_all`` drukuje pod jej linią: przejazd
# verify-centrum-rozliczen kończy stdout linią sprzątania, a porażkę (DRIVE FAIL, VERIFY FAIL) pisze na stderr (#932).
BASE_TAIL = 40
RULES_HEADING = "Zasady werdyktów i przebiegu"
RECIPE, _, RULES = (__doc__ or "").partition(f"\n{RULES_HEADING}\n")
PYTEST_EXIT_USAGE_ERROR = 4
PYTEST_EXIT_NO_TESTS_COLLECTED = 5


class Verdict(StrEnum):
    """Werdykt mutacji; tylko WYKRYTA dowodzi, że polecenie łapie zepsuty kod."""

    CAUGHT = "WYKRYTA"  # polecenie pada albo kończy się oczekiwaną linią
    TYPE_GATE = "WYKRYTA PRZEZ BRAMĘ TYPÓW"  # polecenie przechodzi, ale ruff albo mypy, które czerwienią CI, padają
    SURVIVED = "NIEWYKRYTA"  # polecenie przechodzi po mutacji
    REGRESSION = "REGRES"  # NIEWYKRYTA na HEAD, a WYKRYTA na merge-base: zmiana osłabiła test
    HANG = "ZAWIESZENIE"  # test skończony przez pytest-timeout, co czerwieni CI
    OVER_LIMIT = "PRZEKROCZONY CZAS"  # polecenie bez wyniku w --limit-s narzędzia, czego CI nie widzi
    STALE = "NIEAKTUALNA"  # kotwica nie występuje dokładnie raz
    NO_VERDICT = "BEZ WERDYKTU"  # koniec czasu wywołującego przed wynikiem


NO_VERDICT = Verdict.NO_VERDICT
HANG_CAUGHT = "liczona jako wykryta: pytest-timeout czerwieni test w CI"
OVER_LIMIT_NOTE = "limit --limit-s narzędzia, nie pytest-timeout"


def in_ci(verdict: Verdict, last: str) -> tuple[bool, str]:
    """Czy CI złapałoby mutację z tym werdyktem, i ostatnia linia do logu.

    ZAWIESZENIE (pytest-timeout) dostaje dopisek ``HANG_CAUGHT``; PRZEKROCZONY CZAS nie jest wykryciem, bo test, który
    tylko przekroczył ``--limit-s`` narzędzia, w CI przechodzi. WYKRYTA PRZEZ BRAMĘ TYPÓW (``type_gate``) jest wykryciem:
    zmianę, na której pada ruff albo mypy, odrzucają brama pre-push i zadanie CI „Ruff, mypy”.
    """

    if verdict is Verdict.HANG:
        return True, f"{last} ({HANG_CAUGHT})"
    return verdict in {Verdict.CAUGHT, Verdict.TYPE_GATE}, last


@dataclass(frozen=True)
class Edit:
    file: Path  # względem korzenia repozytorium
    anchor: str
    replacement: str

    def __post_init__(self) -> None:
        if self.file.anchor or ".." in self.file.parts:
            raise ValueError(f"plik mutacji musi leżeć w repozytorium, względem jego korzenia: {self.file}")


@dataclass(frozen=True)
class Mutation:
    name: str
    edits: tuple[Edit, ...]
    command: tuple[str, ...]  # argumenty Pythona, uruchamiane w korzeniu kopii
    harm: str = ""
    expected: str | None = None  # początek ostatniej linii wyjścia; None: polecenie kończy się błędem


def environment(copy: Path, *, concurrent: bool = False) -> dict[str, str]:
    nested = {"PYTEST_XDIST_AUTO_NUM_WORKERS": "1"} if concurrent else {}
    # Część dzieli tabelę tego skryptu, nie tabele, które sprawdzane polecenie samo uruchamia.
    inherited = {name: value for name, value in os.environ.items() if name != ZMIENNA_CZESCI}
    return {
        **nested,
        **inherited,
        "PYTHONPATH": os.pathsep.join([str(copy / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }


@contextmanager
def checkout_copy(commit: str | None = None) -> Iterator[Path]:
    """Kopia HEAD z niezacommitowanymi zmianami checkoutu albo, z ``commit``, kopia samego commitu."""

    names = [] if commit is not None else sorted(repo.uncommitted(ROOT))
    with potomne.commit_copy(ROOT, commit or "HEAD") as copy:
        present = [name for name in names if (ROOT / name).is_symlink() or (ROOT / name).is_file()]
        # Najpierw usunięcia: ścieżka, która zmieniła typ, zwalnia miejsce na plik albo katalog o tej nazwie.
        for name in sorted(set(names) - set(present)):
            _remove(copy, copy / name)
        for name in present:
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, copy / name, follow_symlinks=False)
        found = potomne.run(
            [sys.executable, "-c", "import rozliczenia; print(rozliczenia.__file__)"], cwd=copy, env=environment(copy)
        )
        found.check_returncode()
        imported = found.stdout.strip()
        if not Path(imported).resolve().is_relative_to(copy.resolve()):
            raise RuntimeError(f"kopia importuje rozliczenia z {imported}, nie ze swojego src")
        yield copy


def _remove(copy: Path, path: Path) -> None:
    """Usuwa plik kopii i katalogi, które przez to zostały puste, jak ``git rm``."""

    path.unlink(missing_ok=True)
    for parent in path.parents:
        if parent == copy or any(parent.iterdir()):
            break
        parent.rmdir()


def _apply(copy: Path, edits: Sequence[Edit]) -> str | None:
    """Zmienia kod kopii; zwraca opis kotwicy, której nie ma dokładnie raz."""

    for edit in edits:
        path = copy / edit.file
        code = path.read_text(encoding="utf-8") if path.is_file() else ""
        if code.count(edit.anchor) != 1:
            return f"kotwicy nie ma dokładnie raz w {edit.file.as_posix()}: {edit.anchor.strip()[:60]!r}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code.replace(edit.anchor, edit.replacement), encoding="utf-8")
    return None


@dataclass(frozen=True)
class _Ran:
    code: int | None  # None: polecenie przekroczyło limit
    last: str  # ostatnia linia wyjścia
    hang: str | None  # linia pytest-timeout
    seconds: float  # czas polecenia, także tego, które przekroczyło limit
    tail: tuple[str, ...] = ()  # ostatnie linie stdout, potem stderr (``BASE_TAIL`` każdego), z nazwą strumienia


def _run(
    copy: Path, command: Sequence[str], limit_s: float, stop: threading.Event | None = None, *, concurrent: bool = False
) -> _Ran:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia, ostatnią linię, linię pytest-timeout, jeśli była, czas i koniec
    obu strumieni, także polecenia, które przekroczyło limit (to, co zdążyło wypisać)."""

    started = time.monotonic()
    try:
        env = environment(copy, concurrent=concurrent)
        done = potomne.run([sys.executable, *command], cwd=copy, env=env, timeout=limit_s, stop=stop)
    except potomne.TimeoutExpired as expired:
        return _Ran(None, f"brak wyniku po {limit_s:g} s", None, time.monotonic() - started, _tail(*expired.printed))
    seconds = time.monotonic() - started
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    hangs = (PYTEST_TIMEOUT.fullmatch(line.strip()) for line in f"{done.stdout}\n{done.stderr}".splitlines())
    hang = next((found["hang"] or found["thread"] for found in hangs if found), None)
    return _Ran(done.returncode, lines[-1] if lines else f"kod wyjścia {done.returncode}", hang, seconds, _tail(done.stdout, done.stderr))


def _tail(stdout: str, stderr: str) -> tuple[str, ...]:
    """Ostatnie ``BASE_TAIL`` linii stdout, potem tyle samo stderr, każda z nazwą swojego strumienia."""

    return tuple(f"{name} | {line}" for name, text in (("stdout", stdout), ("stderr", stderr)) for line in text.splitlines()[-BASE_TAIL:])


def _without_test(command: Sequence[str], ran: _Ran) -> bool:
    """Czy polecenie to pytest, który nie uruchomił żadnego testu (kod 4 albo 5)."""

    return ("-m", "pytest") in pairwise(command) and ran.code in {PYTEST_EXIT_USAGE_ERROR, PYTEST_EXIT_NO_TESTS_COLLECTED}


def _no_test_cause(command: Sequence[str], ran: _Ran) -> str:
    """Przyczyna, z którą pytest nie uruchomił testu (``_without_test``).

    Kod 4 daje i polecenie (zła ścieżka, test wybrany przez ``plik::test``, którego nie ma, opcja), i ``conftest.py``,
    którego nie da się zaimportować, a komunikatów pytest jest więcej, niż da się wyliczyć, więc kod 4 dostaje obie
    możliwości z odesłaniem do stderr, a błędem polecenia jest tylko kod 5 i ``-p no:xdist``.
    """

    if ran.code == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return "pytest nie wybrał żadnego testu (kod 5), więc popraw ścieżkę albo -k w poleceniu po --; to błąd polecenia, nie kodu"
    if any(argument.endswith("no:xdist") for argument in command):
        return "pytest odrzucił -p no:xdist (kod 4), bo addopts w pyproject.toml ma --dist, więc zamiast niego daj -n 0 w poleceniu po --"
    return (
        "pytest nie uruchomił testu (kod 4): zła ścieżka, test albo opcja w poleceniu po -- "
        "albo conftest.py, którego nie da się zaimportować; który, mówi koniec stderr niżej"
    )


def _merge_base_note(command: Sequence[str], ran: _Ran) -> str:
    """Dlaczego merge-base nie rozstrzyga mutacji, której podstawa tam jest czerwona."""

    if ran.code == PYTEST_EXIT_NO_TESTS_COLLECTED and _without_test(command, ran):
        return "polecenie bez testu, więc test jest nowy i REGRES nie dotyczy"
    if _without_test(command, ran):
        return "pytest nie uruchomił testu (kod 4: test albo plik nowy, zła ścieżka albo opcja, albo zepsuty conftest.py), więc REGRES nie dotyczy"
    return "podstawa czerwona"


def _verdict(
    mutation: Mutation, *, limit_s: float, stop: threading.Event, concurrent: bool, deadline: float | None, commit: str | None
) -> tuple[Verdict, str, float | None]:
    """Werdykt, ostatnia linia wyjścia i czas polecenia mutacji, z każdym werdyktem polecenia, które biegło (także po
    limicie); bez czasu tylko mutacja, której polecenie nie biegło (NIEAKTUALNA, BEZ WERDYKTU przed startem)."""

    left = limit_s if deadline is None else deadline - time.monotonic()
    if left <= 0:
        return Verdict.NO_VERDICT, "czas minął, zanim się zaczęła", None
    with checkout_copy(commit) as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return Verdict.STALE, stale, None
        ran = _run(copy, mutation.command, min(limit_s, left), stop, concurrent=concurrent)
    if ran.code is None:
        # Koniec czasu wywołującego, a nie limit polecenia, nie mówi, czy mutacja zawiesza polecenie.
        judged = (Verdict.OVER_LIMIT, f"{ran.last} ({OVER_LIMIT_NOTE})") if left >= limit_s else (Verdict.NO_VERDICT, ran.last)
    elif ran.hang is not None:
        judged = Verdict.HANG, ran.hang
    else:
        caught = ran.last.startswith(mutation.expected) if mutation.expected is not None else ran.code != 0
        judged = (Verdict.CAUGHT if caught else Verdict.SURVIVED), ran.last
    return *judged, ran.seconds


def _baseline(mutations: Sequence[Mutation], limit_s: float, commit: str | None = None) -> dict[tuple[str, ...], _Ran]:
    """Polecenia, które bez mutacji padają albo kończą się linią oczekiwaną po mutacji, z ich przebiegiem."""

    expected: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for mutation in mutations:
        expected[mutation.command] |= set() if mutation.expected is None else {mutation.expected}
    red = {}
    with checkout_copy(commit) as copy:
        for command in sorted(expected):
            ran = _run(copy, command, limit_s)
            if ran.code != 0 or any(ran.last.startswith(line) for line in expected[command]):
                red[command] = ran
    return red


def verdicts(
    mutations: Sequence[Mutation],
    *,
    workers: int,
    limit_s: float = TIMEOUT,
    deadline: float | None = None,
    commit: str | None = None,
) -> Iterator[tuple[Verdict, str]]:
    """Werdykt i ostatnia linia wyjścia każdej mutacji po kolei, bez sprawdzenia podstawy; ``workers`` mutacji naraz.

    Z ``deadline`` (chwila ``time.monotonic()``) żadne polecenie nie biegnie dłużej niż do niej. Z ``commit`` mutacje
    biegną na kopii tego commitu bez niezacommitowanych zmian checkoutu.
    """

    for verdict, last, _ in _timed(mutations, workers=workers, limit_s=limit_s, deadline=deadline, commit=commit):
        yield verdict, last


def _timed(
    mutations: Sequence[Mutation], *, workers: int, limit_s: float, deadline: float | None = None, commit: str | None = None
) -> Iterator[tuple[Verdict, str, float | None]]:
    """``verdicts`` z czasem polecenia każdej mutacji (``_verdict``)."""

    run = partial(_verdict, limit_s=limit_s, concurrent=workers > 1, deadline=deadline, commit=commit)
    yield from _each(run, mutations, workers)


_Item = TypeVar("_Item")
_Result = TypeVar("_Result")


def _each(run: Callable[..., _Result], items: Sequence[_Item], workers: int) -> Iterator[_Result]:
    """``run(item, stop=...)`` każdego elementu po kolei, ``workers`` naraz; przerwanie ustawia ``stop`` każdego."""

    stop = threading.Event()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        yield from pool.map(partial(run, stop=stop), items)
    except BaseException:
        # Przerwanie w głównym wątku nie dociera do wątków, które czekają na swoje polecenia.
        stop.set()
        raise
    finally:
        pool.shutdown(cancel_futures=True)


def _left(limit_s: float, deadline: float | None) -> float:
    return limit_s if deadline is None else min(limit_s, deadline - time.monotonic())


@dataclass(frozen=True)
class Finding:
    """Diagnostyka kroku bramy typów."""

    step: str  # nazwa kroku: ruff, mypy, mypy (Windows)
    job: str  # narzędzie kroku (``Step.job`` w ``tools/ci_lokalnie.py``): ruff albo mypy
    code: str | None  # kod reguły; None: wyjście, którego nie dało się przeczytać jako diagnostyk
    text: str  # plik, linia i komunikat, które pokazuje werdykt


@dataclass(frozen=True)
class Checked:
    """Wynik bramy typów na jednej kopii: diagnostyki kroków, które padły, i krok, który nie skończył się w czasie."""

    findings: tuple[Finding, ...] = ()
    late: str | None = None  # nazwa kroku i powód, gdy nie dał wyniku przed ``limit_s`` albo ``deadline``


class Gate(Protocol):
    def __call__(self, copy: Path, *, limit_s: float, stop: threading.Event, deadline: float | None) -> Checked: ...


# Kody ruff, które mówią, że kod jest błędny: nazwa, której nie ma (także w ``__all__`` i przed przypisaniem), i błąd
# składni. Inne reguły ruff mówią o stylu albo o czymś nieużytym (F401, F841), czyli o artefakcie mutacji jednej linii.
RUFF_WRONG = frozenset({"F821", "F822", "F823", "invalid-syntax"})
# Kody mypy, które mówią o pozostałości po zmienionym kodzie albo o typie, którego mypy nie zna, a nie o błędzie typów:
# ``unused-ignore``, ``redundant-cast`` i ``no-any-return`` ze ``strict``, ``unreachable`` z ``warn_unreachable``,
# ``redundant-expr`` i ``redundant-self``.
MYPY_LEFTOVER = frozenset({"unused-ignore", "redundant-cast", "no-any-return", "redundant-expr", "redundant-self", "unreachable"})


def _relative(name: str, copy: Path) -> str:
    try:
        return Path(name).resolve().relative_to(copy.resolve()).as_posix()
    except ValueError:
        return name


def _ruff_findings(output: str, copy: Path) -> list[tuple[str | None, str]]:
    """Diagnostyki z ``ruff check --output-format json``: lista obiektów z ``code``, ``filename``, ``location``."""

    try:
        return [
            (item["code"], f"{_relative(item['filename'], copy)}:{item['location']['row']}: {item['code']} {item['message']}")
            for item in json.loads(output)
        ]
    except (ValueError, KeyError, TypeError):
        return []


def _mypy_findings(output: str, copy: Path) -> list[tuple[str | None, str]]:
    """Błędy z ``mypy --output json``: obiekt w każdej linii; inne linie (błąd, który zatrzymał mypy) pomija."""

    found: list[tuple[str | None, str]] = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
            if item["severity"] == "error":
                found.append((item["code"], f"{item['file']}:{item['line']}: error: {item['message']}  [{item['code']}]"))
        except (ValueError, KeyError, TypeError):
            continue
    return found


@dataclass(frozen=True)
class _Tool:
    output: tuple[str, ...]  # opcje, z którymi narzędzie drukuje diagnostyki w JSON
    findings: Callable[[str, Path], list[tuple[str | None, str]]]  # kod i tekst każdej diagnostyki ze stdout
    wrong: Callable[[str], bool]  # czy diagnostyka z tym kodem mówi, że kod jest błędny


_TOOLS = {
    "ruff": _Tool(("--output-format", "json"), _ruff_findings, RUFF_WRONG.__contains__),
    "mypy": _Tool(("--output", "json"), _mypy_findings, lambda code: code not in MYPY_LEFTOVER),
}


def wrong(finding: Finding) -> bool:
    """Czy diagnostyka bramy typów mówi, że kod jest błędny, a więc liczy się jako wykrycie mutacji.

    Ruff liczy się tylko kodami z listy ``RUFF_WRONG``, bo prawie każda jego reguła to styl albo coś nieużytego, a mutacja
    jednej linii zostawia nieużyte: ``return wynik`` → ``return None`` zostawia F841, choć kod przed mutacją przeszedł
    bramę. Mypy liczy się każdym kodem poza ``MYPY_LEFTOVER``, bo każdy jego kod poza tymi mówi, że program jest źle
    otypowany (także opcjonalne kody ``enable_error_code``: ``exhaustive-match``, ``truthy-bool``); ``no-any-return``
    mówi tylko, że mypy nie zna typu wyniku, więc jest pozostałością jak ``unused-ignore``. Lista dozwolonych
    wymieniałaby kilkadziesiąt kodów błędów typów, z których każdy przeoczony zakładałby fałszywe issue.
    Żadna lista nie odróżnia artefaktu cofnięcia fragmentu do bazy: cofnięty fragment przeszedł bramę, więc każdy jej
    błąd na nim to niezgodność z resztą zmiany, i dlatego noc cofnięć bramą nie sprawdza (``tools/mutacje_zmiany.py``).
    Diagnostyka bez kodu (wyjście, którego nie dało się przeczytać) nie liczy się nigdy: brama, która nie wie, co
    znalazła, nie zabiera mutacji z issue.
    """

    return finding.code is not None and _TOOLS[finding.job].wrong(finding.code)


def static_gate(copy: Path, *, limit_s: float, stop: threading.Event, deadline: float | None) -> Checked:
    """Kroki ruff i mypy obu systemów bramy pre-push (``ci_lokalnie.static_steps``) w kopii, z diagnostykami w JSON.

    Diagnostyki każdego kroku, który padł; kroki biegną do pierwszego, którego diagnostyka liczy się jako wykrycie
    (``wrong``), albo do pierwszego, który nie skończył się w czasie.
    """

    found: list[Finding] = []
    # Przez import_module: ci_lokalnie importuje ten moduł.
    for step in importlib.import_module("ci_lokalnie").static_steps(copy):
        tool = _TOOLS[step.job]
        left = _left(limit_s, deadline)
        if left <= 0:
            return Checked(tuple(found), f"{step.name}: czas minął, zanim się zaczął")
        try:
            done = potomne.run([*step.command, *tool.output], cwd=copy, env=environment(copy), timeout=left, stop=stop)
        except subprocess.TimeoutExpired:
            return Checked(tuple(found), f"{step.name}: brak wyniku po {left:g} s")
        if done.returncode:
            read = tool.findings(done.stdout, copy)
            lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
            unread = [(None, lines[0] if lines else f"kod wyjścia {done.returncode}")]
            found.extend(Finding(step.name, step.job, code, text) for code, text in read or unread)
            if any(map(wrong, found)):
                break
    return Checked(tuple(found))


def _gated(
    mutation: Mutation, *, cache: Path, limit_s: float, stop: threading.Event, deadline: float | None, gate: Gate
) -> tuple[Verdict, str] | None:
    if _left(limit_s, deadline) <= 0:
        return Verdict.NO_VERDICT, "czas minął przed bramą typów"
    with checkout_copy() as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return Verdict.STALE, stale
        if cache.is_dir():
            shutil.copytree(cache, copy / MYPY_CACHE)
        checked = gate(copy, limit_s=limit_s, stop=stop, deadline=deadline)
    caught = next((finding for finding in checked.findings if wrong(finding)), None)
    if caught is not None:
        return Verdict.TYPE_GATE, f"{caught.step}: {caught.text}"
    if checked.late is not None:
        return Verdict.NO_VERDICT, f"brama typów, {checked.late}"
    return None


def type_gate(
    mutations: Sequence[Mutation],
    found: Sequence[tuple[Verdict, str]],
    *,
    workers: int,
    limit_s: float = TIMEOUT,
    deadline: float | None = None,
    gate: Gate = static_gate,
) -> list[tuple[Verdict, str]]:
    """Werdykty ``found`` po bramie typów: mutację, którą polecenie przepuściło (NIEWYKRYTA, PRZEKROCZONY CZAS),
    sprawdza jeszcze ``gate``, domyślnie kroki ruff i mypy obu systemów bramy pre-push (``static_gate``).

    Najpierw ``gate`` biegnie raz na kopii bez mutacji: gdy tam zgłasza cokolwiek, brama niczego nie dowodzi, więc linia
    ``BRAMA TYPÓW CZERWONA`` na stderr i werdykty bez zmian; jej cache mypy dostaje każda kopia mutacji, więc mypy
    sprawdza od nowa tylko moduły, które mutacja zmienia, i te, które od nich zależą. Każda diagnostyka na kopii z
    mutacją powstała więc przez mutację. Mutacja, której diagnostyka mówi, że kod jest błędny (``wrong``), jest WYKRYTA
    PRZEZ BRAMĘ TYPÓW z nazwą kroku i tą diagnostyką; inne diagnostyki (nieużyty import, nieużyte ``# type: ignore``)
    zostawiają werdykt. Krok bez wyniku przed ``limit_s`` albo ``deadline`` daje BEZ WERDYKTU.
    """

    gated = [index for index, (verdict, _) in enumerate(found) if verdict in {Verdict.SURVIVED, Verdict.OVER_LIMIT}]
    if not gated:
        return list(found)
    result = list(found)
    with tempfile.TemporaryDirectory(prefix="brama-typow-") as folder:
        cache = Path(folder) / MYPY_CACHE
        with checkout_copy() as copy:
            clean = gate(copy, limit_s=limit_s, stop=threading.Event(), deadline=deadline)
            if (copy / MYPY_CACHE).is_dir():
                shutil.copytree(copy / MYPY_CACHE, cache)
        if clean.findings:
            first = clean.findings[0]
            print(f"BRAMA TYPÓW CZERWONA: {first.step}: {first.text} (bez mutacji, więc przeżyte mutacje zostają przeżyte)", file=sys.stderr, flush=True)
            return result
        if clean.late is not None:
            for index in gated:
                result[index] = (Verdict.NO_VERDICT, f"{found[index][1]} (brama typów, {clean.late}, bez mutacji)")
            return result
        run = partial(_gated, cache=cache, limit_s=limit_s, deadline=deadline, gate=gate)
        for index, verdict in zip(gated, _each(run, [mutations[index] for index in gated], workers), strict=True):
            if verdict is not None:
                result[index] = verdict
    return result


def _part(mutations: Sequence[Mutation], part: str) -> list[Mutation]:
    """Mutacje części ``K/N`` (``Czesc.co_nta`` po nazwie) w kolejności tabeli; zła postać to ``ValueError`` z nazwą zmiennej."""

    try:
        czesc = Czesc.z_tekstu(part)
    except ValueError as error:
        raise ValueError(f"{ZMIENNA_CZESCI} to {error}") from None
    by_name = sorted(range(len(mutations)), key=lambda index: (mutations[index].name, repr(mutations[index])))
    chosen = set(czesc.co_nta(by_name))
    return [mutation for index, mutation in enumerate(mutations) if index in chosen]


def _against_base(
    mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], base: str, *, workers: int, limit_s: float
) -> list[tuple[Verdict, str]]:
    """Mutacje NIEWYKRYTA na HEAD, które na merge-base HEAD z ``base`` są WYKRYTA, jako REGRES.

    Mutacja, której merge-base nie rozstrzyga (podstawa czerwona, pytest bez testu, bo test jest nowy, inny werdykt niż
    NIEWYKRYTA), zostaje NIEWYKRYTA z dopiskiem, co dał merge-base; ta, która tam też jest NIEWYKRYTA, zostaje bez zmian.
    """

    survived = [index for index, (verdict, _) in enumerate(found) if verdict is Verdict.SURVIVED]
    if not survived:
        return list(found)
    try:
        commit = repo.merge_base(ROOT, "HEAD", base)
    except subprocess.CalledProcessError as error:
        # Na stderr: pierwsza linia wyjścia to werdykt mutacji, także w checkoucie CI bez gałęzi bazy.
        print(f"MERGE-BASE: brak merge-base HEAD z {base}, więc REGRES niesprawdzony, a NIEWYKRYTA bez porównania ({error.stderr.strip()})", file=sys.stderr, flush=True)
        return list(found)
    if commit == repo.commit(ROOT, "HEAD") and not repo.uncommitted(ROOT):
        # Merge-base to sam checkout, więc drugi przebieg dałby te same werdykty.
        return list(found)
    red = _baseline([mutations[index] for index in survived], limit_s, commit)
    compared = [index for index in survived if mutations[index].command not in red]
    there = verdicts([mutations[index] for index in compared], workers=workers, limit_s=limit_s, commit=commit)
    on_base = dict(zip(compared, there, strict=True))
    result = list(found)
    for index in survived:
        last, command = found[index][1], mutations[index].command
        if command in red:
            ran = red[command]
            why = _merge_base_note(command, ran)
            result[index] = (Verdict.SURVIVED, f"{last} (na merge-base {commit[:8]} {why}: {ran.last})")
            continue
        verdict, base_last = on_base[index]
        if verdict is Verdict.CAUGHT:
            result[index] = (Verdict.REGRESSION, f"{last} ({verdict} na merge-base {commit[:8]}: {base_last})")
        elif verdict is not Verdict.SURVIVED:
            result[index] = (Verdict.SURVIVED, f"{last} (na merge-base {commit[:8]} {verdict}: {base_last})")
    return result


def check_all(
    mutations: Sequence[Mutation], *, parallel: bool = True, limit_s: float = TIMEOUT, base: str | None = None, gate: Gate = static_gate
) -> int:
    """Podstawa, werdykt i czas polecenia każdej mutacji; kod 0, gdy CI złapałoby każdą (``in_ci``).

    Pod linią ``PODSTAWA CZERWONA`` stderr dostaje koniec stdout i stderr polecenia podstawy (``BASE_TAIL`` linii
    każdego), także podstawy, która przekroczyła ``limit_s``, bo ostatnia linia nie zawsze mówi, co padło, a kopii
    commitu z wyjściem już nie ma (#932, #947). Podstawa pytest, z którą nie biegł żaden test (``_without_test``), ma
    między nimi linię ``PODSTAWA BEZ TESTU`` z przyczyną (``_no_test_cause``).

    Przed linią werdyktu każdej mutacji linia ``CZAS`` na stderr podaje czas jej polecenia, a mutację, której polecenie
    trwało ponad ``NEAR_LIMIT`` limitu ``limit_s``, linia ``CZAS BLISKO LIMITU`` na stderr przed linią końcową wymienia ze
    skryptem, częścią i limitem (``NearLimit.line``), zanim limit da PRZEKROCZONY CZAS (#911, #927). Log CI skryptu skilla
    ma obie, bo ``tools/ci/mutacje_skilli.py`` łączy stderr ze stdout i z niego czyta ostrzeżenia (#935). To nie werdykt,
    więc stdout (werdykty i linia końcowa) i kod wyjścia się nie zmieniają. Czas ma każda mutacja, której polecenie biegło, także po limicie, więc linię ``CZAS`` i
    ostrzeżenie dostaje też PRZEKROCZONY CZAS, który brama typów zmienia w WYKRYTA PRZEZ BRAMĘ TYPÓW, i ZAWIESZENIE,
    które ``in_ci`` liczy jako wykrycie; bez linii ``CZAS`` jest tylko mutacja, której polecenie nie biegło (NIEAKTUALNA, BEZ
    WERDYKTU przed startem).

    Bez ``base`` (skrypty mutacji skilli) mutację, którą polecenie przepuściło, sprawdza jeszcze ``type_gate`` z ``gate``. Z
    ``base``, czyli w przeglądzie z wiersza poleceń, porażką jest wszystko poza WYKRYTA, także ZAWIESZENIE, a mutacja
    NIEWYKRYTA biegnie też na merge-base HEAD z ``base`` (REGRES), bez bramy typów.
    """

    if not mutations:
        print("MUTACJE: brak mutacji, więc nie ma czego dowieść")
        return 1
    if part := os.environ.get(ZMIENNA_CZESCI):
        total = len(mutations)
        mutations = _part(mutations, part)
        print(f"MUTACJE CZĘŚĆ {part}: {len(mutations)} z {total} mutacji", flush=True)
        if not mutations:
            print(MUTACJE_OK)
            return 0
    red = _baseline(mutations, limit_s)
    for command, ran in red.items():
        print(f"PODSTAWA CZERWONA: {' '.join(command)} → {ran.last}", flush=True)
        if _without_test(command, ran):
            print(f"PODSTAWA BEZ TESTU: {_no_test_cause(command, ran)}", flush=True)
        # Na stderr, jak linia CZAS: przyczyna porażki podstawy, której kopia commitu z dowodami już nie ma (#932).
        for line in ran.tail:
            print(f"  {line}", file=sys.stderr, flush=True)
    if red:
        print("MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi")
        return 2
    failures = 0
    workers = PARALLEL if parallel else 1
    timed = list(_timed(mutations, workers=workers, limit_s=limit_s))
    found = [(verdict, last) for verdict, last, _ in timed]
    times = [seconds for _, _, seconds in timed]
    if base is not None:
        found = _against_base(mutations, found, base, workers=workers, limit_s=limit_s)
    else:
        found = type_gate(mutations, found, workers=workers, limit_s=limit_s, gate=gate)
    for mutation, (verdict, shown), seconds in zip(mutations, found, times, strict=True):
        caught, last = (verdict is Verdict.CAUGHT, shown) if base is not None else in_ci(verdict, shown)
        failures += not caught
        harm = f" ({mutation.harm})" if mutation.harm else ""
        if seconds is not None:
            print(f"CZAS: {mutation.name} → {seconds:.0f} s", file=sys.stderr, flush=True)
        print(f"{verdict}: {mutation.name}{harm} → {last}", flush=True)
    for mutation, seconds in zip(mutations, times, strict=True):
        if seconds is not None and seconds > NEAR_LIMIT * limit_s:
            print(NearLimit(_script(), os.environ.get(ZMIENNA_CZESCI, ""), mutation.name, round(seconds), limit_s).line, file=sys.stderr, flush=True)
    print(MUTACJE_OK if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


def _script() -> str:
    """Skrypt, który uruchomił ``check_all``, względem korzenia repozytorium, jak w poleceniu CI."""

    path = Path(sys.argv[0]).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else sys.argv[0]


@dataclass(frozen=True)
class NearLimit:
    """Ostrzeżenie ``CZAS BLISKO LIMITU``: mutacja ``name`` skryptu ``script`` (część ``part`` z ``MUTACJE_CZESC``, pusta
    bez niej), której polecenie trwało ``seconds`` z limitu ``limit_s``. ``check_all`` drukuje je linią ``line``, a
    ``near_limits`` czyta je z wyjścia skryptu, więc noc dostaje je przez zapis wykonania planu CI (#935)."""

    script: str
    part: str
    name: str
    seconds: int
    limit_s: float

    @property
    def line(self) -> str:
        part = f" ({ZMIENNA_CZESCI}={self.part})" if self.part else ""
        near = f"CZAS BLISKO LIMITU: {self.script}{part}: {self.name} → {self.seconds} s z limitu --limit-s {self.limit_s:g} s"
        return f"{near} (po nim PRZEKROCZONY CZAS: podziel zakres mutacji albo przyspiesz sprawdzenie)"


# ``NearLimit.line`` na początku linii; nazwa mutacji kończy się przed ostatnią strzałką przed czasem.
_NEAR = re.compile(
    rf"^CZAS BLISKO LIMITU: (?P<script>\S+)(?: \({ZMIENNA_CZESCI}=(?P<part>[0-9]+/[0-9]+)\))?: (?P<name>.+) → (?P<seconds>[0-9]+) s z limitu --limit-s (?P<limit>\S+) s \(po nim ",
    re.MULTILINE,
)


def near_limits(output: str) -> list[NearLimit]:
    """Ostrzeżenia ``CZAS BLISKO LIMITU``, które ``check_all`` wydrukował w ``output``, w ich kolejności."""

    return [NearLimit(found["script"], found["part"] or "", found["name"], int(found["seconds"]), float(found["limit"])) for found in _NEAR.finditer(output)]


def _texts(value: object, count: int | None = None) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value) and count in {None, len(value)}


class _Key(NamedTuple):
    required: bool
    valid: Callable[[object], bool]


_ENTRY = {
    "nazwa": _Key(required=True, valid=lambda value: isinstance(value, str)),
    "zmiany": _Key(required=True, valid=lambda value: isinstance(value, list) and bool(value) and all(_texts(edit, 3) for edit in value)),
    "polecenie": _Key(required=False, valid=_texts),
    "oczekiwane": _Key(required=False, valid=lambda value: isinstance(value, str)),
}
FILE_SHAPE = '[{"nazwa": "...", "zmiany": [["plik", "kotwica", "zamiana"], ...]}, ...] z opcjonalnymi "polecenie": [...] i "oczekiwane": "..."'


def _entry_problem(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return "nie jest obiektem"
    if unknown := sorted(entry.keys() - _ENTRY.keys()):
        return f"ma nieznany klucz {unknown[0]!r}"
    wrong = [key for key, (required, valid) in _ENTRY.items() if (key in entry or required) and not (key in entry and valid(entry[key]))]
    return f"ma zły albo brakujący klucz {wrong[0]!r}" if wrong else None


def _from_file(path: Path, command: tuple[str, ...], *, own_command: bool = True) -> list[Mutation]:
    """Mutacje z pliku JSON; plik innej postaci niż ``FILE_SHAPE`` to ``ValueError``, która ją podaje."""

    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"{path}: plik mutacji to lista, nie {type(entries).__name__}; postać: {FILE_SHAPE}")
    for number, entry in enumerate(entries, 1):
        if problem := _entry_problem(entry):
            raise ValueError(f"{path}: wpis {number} {problem}; postać: {FILE_SHAPE}")
    if not own_command and (named := [entry["nazwa"] for entry in entries if "polecenie" in entry]):
        raise ValueError(f"--jak-ci składa polecenie samo, a wpisy {', '.join(named)} mają własne")
    return [
        Mutation(
            name=entry["nazwa"],
            edits=tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in entry["zmiany"]),
            command=tuple(entry.get("polecenie", command)),
            expected=entry.get("oczekiwane"),
        )
        for entry in entries
    ]


def ci_jobs(jobs: Iterable[tuple[str, str, Sequence[str]]], tracks: Collection[str], tested: Collection[str]) -> list[tuple[str, list[str]]]:
    """Nazwa i pliki testów (i węzły ``plik::test``) każdego zadania pytest (tor, nazwa, jednostki) z ``tracks``, w
    którym stoi plik z ``tested``.

    Kolejność zadań i plików jak w planie, bez powtórzeń; udział pliku ``#k/n`` to cały plik.
    """

    found = []
    for track, name, units in jobs:
        files = list(dict.fromkeys(klucz.nazwa for klucz in map(Klucz.z_tekstu, units) if klucz.rodzaj is Rodzaj.PYTEST))
        if track in tracks and any(file.partition("::")[0] in tested for file in files):
            found.append((name, files))
    return found


def _output(*arguments: str) -> str:
    """Wyjście polecenia ``gh``; porażka to ``ValueError`` z końcem jego błędu."""

    try:
        return github.gh(*arguments, limit_s=None).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{' '.join(error.cmd[:3])} padł: {(error.stderr.strip() or error.stdout.strip())[-300:]}") from None


def _last_run() -> str:
    """Numer ostatniego runu ``ci.yml`` gałęzi, którą śledzi bieżąca (bez śledzonej: bieżącej)."""

    try:
        head = repo.git(ROOT, "rev-parse", "--symbolic-full-name", "HEAD").strip()
        if not head.startswith("refs/heads/"):
            raise ValueError("HEAD nie jest na gałęzi, więc podaj numer runu CI: --jak-ci <id runu>")
        branch = repo.git(ROOT, "for-each-ref", "--format=%(upstream:lstrip=3)", head).strip() or head.removeprefix("refs/heads/")
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{' '.join(error.cmd[:3])} padł: {(error.stderr.strip() or error.stdout.strip())[-300:]}") from error
    runs = json.loads(_output("run", "list", "--workflow", "ci.yml", "--branch", branch, "--limit", "1", "--json", "databaseId"))
    if not runs:
        raise ValueError(f"gałąź {branch} nie ma runu CI, więc podaj numer runu: --jak-ci <id runu>")
    return str(runs[0]["databaseId"])


def _ci_mutations(mutations: Sequence[Mutation], run: str, base: str) -> list[Mutation]:
    """Każda mutacja raz na każde zadanie pytest runu ``run`` (pusty: ``_last_run``), w którym stoi test zmieniony od
    ``base``, z poleceniem ``pytest -n 1`` z plikami tego zadania."""

    # Przez import_module: kopie narzędzi w repozytoriach testów nie mają ani plan_runu, ani wplyw_zmiany.
    plan_runu = importlib.import_module("plan_runu")
    wplyw_zmiany = importlib.import_module("wplyw_zmiany")
    try:
        tested = wplyw_zmiany.changed_since(ROOT, base)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"brak merge-base HEAD z {base}, więc nie wiadomo, które testy zmieniono: {error.stderr.strip()}") from error
    run = run or _last_run()
    with tempfile.TemporaryDirectory(prefix="plan-ci-") as folder:
        _output("run", "download", run, "--name", "plan", "--dir", folder)
        plan = plan_runu.Plan.z_json((Path(folder) / "plan.json").read_text(encoding="utf-8"))
    tracks = {track.nazwa for track in importlib.import_module("zakres_runu").TORY if track.os.startswith("windows") == (sys.platform == "win32")}
    jobs = ci_jobs([(job.tor, job.nazwa, job.jednostki) for job in plan.zadania], tracks, tested)
    if not jobs:
        raise ValueError(f"run {run} nie stawia w zadaniu pytest toru {', '.join(sorted(tracks))} pliku testów zmienionego od {base}")
    commands = {name: ("-m", "pytest", "-q", "-n", "1", "-p", "no:cacheprovider", *files) for name, files in jobs}
    for name, command in commands.items():
        print(f"JAK CI: run {run}, {name}: {' '.join(command)}", flush=True)
    return [replace(mutation, name=f"{mutation.name} [{name}]", command=command) for mutation in mutations for name, command in commands.items()]


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    split = arguments.index("--") if "--" in arguments else len(arguments)
    command = tuple(arguments[split + 1 :])
    parser = argparse.ArgumentParser(description=RECIPE, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--zmiana",
        nargs=3,
        action="append",
        default=[],
        metavar=("PLIK", "KOTWICA", "ZAMIANA"),
        help="Jedna zmiana mutacji; powtórz dla mutacji w kilku miejscach.",
    )
    parser.add_argument("--nazwa", default="mutacja", help="Nazwa mutacji z --zmiana w raporcie.")
    parser.add_argument("--plik", type=Path, help="Plik JSON z listą mutacji.")
    parser.add_argument("--rownolegle", action="store_true", help="Mutacje naraz, każda w swojej kopii.")
    parser.add_argument("--limit-s", type=float, default=TIMEOUT, help="Limit czasu jednego polecenia w sekundach.")
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, z której merge-base z HEAD daje REGRES i plan --jak-ci (domyślnie {BASE}).")
    parser.add_argument(
        "--jak-ci",
        nargs="?",
        const="",
        metavar="RUN",
        help="Polecenie z plików każdego zadania pytest runu CI RUN (bez numeru: ostatniego runu gałęzi), w którym stoją zmienione testy, bez polecenia po --.",
    )
    ciezkie_ci.argument(parser)
    parser.add_argument("--zasady", action="store_true", help=f"Drukuje zasady werdyktów, kopii, bramy typów, nocy, --jak-ci i {ZMIENNA_CZESCI}.")
    args = parser.parse_args(arguments[:split])
    if args.zasady:
        print(RULES.strip())
        return 0
    jak_ci = args.jak_ci is not None
    if jak_ci and command:
        parser.error("--jak-ci składa polecenie samo, więc nie podawaj go po --")
    try:
        mutations = _from_file(args.plik, command, own_command=not jak_ci) if args.plik else []
        if args.zmiana:
            edits = tuple(Edit(Path(file), anchor, replacement) for file, anchor, replacement in args.zmiana)
            mutations.append(Mutation(args.nazwa, edits, command))
    except ValueError as error:
        parser.error(str(error))
    if not mutations or not (jak_ci or all(mutation.command for mutation in mutations)):
        parser.error("podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q -n 0 tests/test_x.py -k nazwa_testu, albo --jak-ci")
    if jak_ci:
        try:
            mutations = _ci_mutations(mutations, args.jak_ci, args.baza)
        except ValueError as error:
            parser.error(str(error))
    if refused := ciezkie_ci.mutations_refusal(len(mutations), args.odtwarzam, root=ROOT):
        print(refused)
        return 2
    return check_all(mutations, parallel=args.rownolegle, limit_s=args.limit_s, base=args.baza)


if __name__ == "__main__":
    raise SystemExit(main())
