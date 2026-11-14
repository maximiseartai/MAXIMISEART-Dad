"""Silnik mutacji: kopia checkoutu z zepsutym kodem, werdykt polecenia, brama typów i części tabeli; jedyny w repozytorium.

Wołają go narzędzie ``tools/mutacje.py`` (``review``), skrypty mutacji skilli ``check_<co>_mutations.py``
(``check_all``), mutacje nocy ``tools/mutacje_zmiany.py`` (``verdicts``, ``in_ci``, ``type_gate``) i zadanie planu CI
``tools/ci/wykonaj_zadanie.py`` (``near_limits``). Zasady niżej drukuje ``tools/mutacje.py --zasady``.

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
(test tylko wolniejszy), więc ``in_ci`` nie liczy go jak WYKRYTA, a skrypty skilli liczą go jak przeżytą. Noc też go
nie liczy jak wykrytą, ale ``--limit-s`` dotyczy u niej całego zbioru testów przebiegu, który bez mutacji trwa blisko
limitu, więc mutacja, po której test pada, też potrafi go przekroczyć (#1339): mutację z PRZEKROCZONYM CZASEM w
ostatnim przebiegu testów noc zgłasza w issue z dopiskiem, że nie dała jej werdyktu, a nie jako przeżytą. W narzędziu z
wiersza poleceń, którego używa przegląd PR, oba są porażką.

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
CZERWONA`` na stderr zostawia werdykty bez zmian. Ruff i mypy daje dodatek ``dev``, który instaluje każde zadanie CI z
mutacjami. W skrypcie skilla Python bez nich to błąd ``MissingGateTool`` i kod 2, a w nocy brama czerwona, bo noc
biegnie też w testach pytest na Windows, które instalują samo ``requirements.txt``. Narzędzie
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

Z ``MUTACJE_CZESC=K/N`` w środowisku ``check_all`` sprawdza tylko K-tą z N części tabeli: K-ty z N kolejnych kawałków
mutacji ułożonych po poleceniu, potem po nazwie, więc część nie zależy od kolejności tabeli, a N części sprawdza każdą
mutację dokładnie raz. Podstawa części to tylko polecenia jej mutacji, po kolei, a część bez mutacji kończy się
``MUTACJE OK``. Kawałki po poleceniu dają poleceniu podstawę tylko w częściach, do których trafiają jego mutacje:
polecenie z mutacjami w jednym kawałku w jednej części albo, na granicy kawałków, w dwóch, a polecenie z większą
liczbą mutacji niż kawałek także w trzech i więcej (``_part`` na tabelach skryptów: ``check_model_kolejki_mutations.py``
przy N=4 w 3, ``check_runs_mutations.py`` przy N=7 w 4, ``check_model_wznowienia_mutations.py`` z 2 poleceniami i 9
mutacjami przy N=8 w 7). Przy podziale co N-tą po nazwie każda z czterech części skryptu mutacji modelu Kolejki
Skrzynki uruchamiała podstawę 5–9 z jego 13 poleceń i trwała 316–550 s (zadania Mutation checks runów PR 43363580640,
43365452211, 43368688448). Tak plan CI (``tools/plan_ci.py``) dzieli długi skrypt mutacji skilla na zadania bez zmiany skryptu.

``check_all`` drukuje na stderr czas polecenia każdej mutacji (linia ``CZAS``) i ostrzeżenie ``CZAS BLISKO LIMITU`` dla
mutacji, której polecenie trwało ponad połowę ``--limit-s`` (``NEAR_LIMIT``), więc rosnący czas widać w logu, zanim
stanie się PRZEKROCZONY CZAS; werdyktów, linii końcowej ani kodu wyjścia to nie zmienia. Ostrzeżenie (``NearLimit``)
czyta z wyjścia skryptu ``near_limits``, a nocne skrypty mutacji skilli zgłaszają je raz na mutację w issue PR-u
(``tools/mutacje_nocne.py``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import partial
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
from typing import Any, Protocol, TypeVar

from import_dynamiczny import jest_modul
from jednostka import ZMIENNA_CZESCI, Czesc
from kroki_lokalne import environment, static_steps
from ostatnie_linie import MUTACJE_OK
import potomne
from repo import ROOT
import repo

TIMEOUT = 600
# Mutacji naraz najwyżej tyle, ile rdzeni ma komputer (4 vCPU runnera Windows CI), i najwyżej 8 (16 rdzeni Maca dzielą
# agenci). Osiem eksploratorów naraz na 4 vCPU dzieliło procesor, więc czas mutacji zależał od tego, ile ciężkich mutacji
# plan CI wrzucił do jednej części (do 600 s limitu, #963, #968). Noc ma własne ``mutacje_zmiany.WORKERS``: z niego plan
# nocy liczy rozmiar części, który nie może zależeć od komputera, na którym plan biegnie.
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


HANG_CAUGHT = "liczona jako wykryta: pytest-timeout czerwieni test w CI"
OVER_LIMIT_NOTE = "limit --limit-s narzędzia, nie pytest-timeout"


def in_ci(verdict: Verdict, last: str) -> tuple[bool, str]:
    """Czy CI złapałoby mutację z tym werdyktem, i ostatnia linia do logu.

    ZAWIESZENIE (pytest-timeout) dostaje dopisek ``HANG_CAUGHT``; PRZEKROCZONY CZAS nie jest wykryciem, bo test, który
    tylko przekroczył ``--limit-s`` narzędzia, w CI przechodzi; noc nie liczy go też jak przeżytej
    (``tools/mutacje_zmiany.py``). WYKRYTA PRZEZ BRAMĘ TYPÓW (``type_gate``) jest wykryciem: zmianę, na której pada ruff
    albo mypy, odrzucają brama pre-push i zadanie CI „Ruff, mypy”.
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
    """Przebieg polecenia w kopii, także polecenia, które przekroczyło limit (to, co zdążyło wypisać)."""

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
    return tuple(f"{name} | {line}" for name, text in (("stdout", stdout), ("stderr", stderr)) for line in text.splitlines()[-BASE_TAIL:])


def _without_test(command: Sequence[str], ran: _Ran) -> bool:
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
    job: str  # narzędzie kroku (``Step.job`` w ``tools/lib/kroki_lokalne.py``): ruff albo mypy
    code: str | None  # kod reguły; None: wyjście, którego nie dało się przeczytać jako diagnostyk
    text: str  # plik, linia i komunikat, które pokazuje werdykt


@dataclass(frozen=True)
class Checked:
    """Wynik bramy typów na jednej kopii: diagnostyki kroków, które padły, i krok, który nie skończył się w czasie."""

    findings: tuple[Finding, ...] = ()
    late: str | None = None  # nazwa kroku i powód, gdy nie dał wyniku przed ``limit_s`` albo ``deadline``


class Gate(Protocol):
    def __call__(self, copy: Path, *, limit_s: float, stop: threading.Event, deadline: float | None) -> Checked: ...


class MissingGateTool(Exception):
    """Python bramy typów nie ma jej narzędzia (ruff albo mypy z dodatku ``dev``), więc brama niczego nie sprawdzi."""


# Kody ruff, które mówią, że kod jest błędny: nazwa, której nie ma (także w ``__all__`` i przed przypisaniem), i błąd
# składni; dlaczego tylko one, mówi ``wrong``.
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
    """Kroki ruff i mypy obu systemów bramy pre-push (``kroki_lokalne.static_steps``) w kopii, z diagnostykami w JSON.

    Diagnostyki każdego kroku, który padł; kroki biegną do pierwszego, którego diagnostyka liczy się jako wykrycie
    (``wrong``), albo do pierwszego, który nie skończył się w czasie. Krok bez narzędzia pada jak każdy inny
    (``No module named ruff``), więc ``type_gate`` widzi bramę czerwoną bez mutacji; błędem instalacji robi to tylko
    brama ``check_all`` (``_installed_gate``).
    """

    found: list[Finding] = []
    for step in static_steps(copy):
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


def _installed_gate(copy: Path, *, limit_s: float, stop: threading.Event, deadline: float | None) -> Checked:
    """``static_gate`` skryptu mutacji skilla: krok, którego narzędzia Python nie znajdzie, to ``MissingGateTool``.

    Zadania CI ze skryptami skilli instalują dodatek ``dev``, więc brak ruff albo mypy to zła instalacja, a nie kod, który
    bramy nie przechodzi. Noc (``tools/mutacje_zmiany.py``) bierze samo ``static_gate``: pytest na Windows uruchamia ją
    z ``requirements.txt``, bez narzędzi bramy, i wtedy brama jest czerwona bez mutacji.
    """

    for step in static_steps(copy):
        # ``python -m`` w korzeniu kopii szuka modułu najpierw w nim, potem tam, gdzie Python tego procesu.
        if not jest_modul(step.job, [str(copy), *sys.path]):
            raise MissingGateTool(f"{sys.executable} nie ma modułu {step.job} kroku {step.name}")
    return static_gate(copy, limit_s=limit_s, stop=stop, deadline=deadline)


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
    """Mutacje części ``K/N`` (``Czesc.kawalek`` po poleceniu i nazwie) w kolejności tabeli; zła postać to ``ValueError``
    z nazwą zmiennej."""

    try:
        czesc = Czesc.z_tekstu(part)
    except ValueError as error:
        raise ValueError(f"{ZMIENNA_CZESCI} to {error}") from None
    by_command = sorted(range(len(mutations)), key=lambda index: (mutations[index].command, mutations[index].name, repr(mutations[index])))
    chosen = set(czesc.kawalek(by_command))
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


class _Judge(Protocol):
    def __call__(
        self, mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], *, workers: int, limit_s: float
    ) -> list[tuple[Verdict, str, bool]]: ...


def _skill_judgement(
    mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], *, workers: int, limit_s: float, gate: Gate
) -> list[tuple[Verdict, str, bool]]:
    """Werdykt skryptu mutacji skilla: mutację, którą polecenie przepuściło, sprawdza jeszcze ``type_gate`` z ``gate``, a
    wykryciem jest to, co złapałoby CI (``in_ci``)."""

    judged = []
    for verdict, shown in type_gate(mutations, found, workers=workers, limit_s=limit_s, gate=gate):
        caught, last = in_ci(verdict, shown)
        judged.append((verdict, last, caught))
    return judged


def _review_judgement(
    mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], *, workers: int, limit_s: float, base: str
) -> list[tuple[Verdict, str, bool]]:
    """Werdykt przeglądu z wiersza poleceń: porażką jest wszystko poza WYKRYTA, także ZAWIESZENIE, a mutacja NIEWYKRYTA
    biegnie też na merge-base HEAD z ``base`` (REGRES), bez bramy typów."""

    compared = _against_base(mutations, found, base, workers=workers, limit_s=limit_s)
    return [(verdict, shown, verdict is Verdict.CAUGHT) for verdict, shown in compared]


def check_all(mutations: Sequence[Mutation], *, limit_s: float = TIMEOUT, gate: Gate = _installed_gate) -> int:
    """Główna funkcja skryptu mutacji skilla (``check_<co>_mutations.py``): mutacje naraz (``PARALLEL``) z werdyktem,
    który złapałoby CI, po bramie typów ``gate``; kod 0, gdy CI złapałoby każdą, a kod 2, gdy brama nie ma narzędzia
    (``MissingGateTool``). Brama biegnie tylko po mutacji, którą polecenie przepuściło, więc przebieg, w którym CI
    złapałoby każdą, kończy się kodem 0 także w Pythonie bez dodatku ``dev``.

    Część tabeli bierze z ``MUTACJE_CZESC`` w środowisku procesu, które ustawia plan CI, a nazwę skryptu do ostrzeżenia
    ``CZAS BLISKO LIMITU`` z ``sys.argv[0]``, więc działa tylko jako główna funkcja procesu skryptu.
    """

    judge = partial(_skill_judgement, gate=gate)
    try:
        return _check(mutations, judge=judge, part=_environment_part(), script=_script(), workers=PARALLEL, limit_s=limit_s)
    except MissingGateTool as missing:
        print(f'MUTACJE: brama typów bez narzędzia: {missing}; zainstaluj dodatek dev (uv pip install -e ".[dev]")', flush=True)
        return 2


def review(mutations: Sequence[Mutation], *, base: str, workers: int, limit_s: float = TIMEOUT) -> int:
    """Główna funkcja narzędzia ``tools/mutacje.py``: werdykt przeglądu (``_review_judgement``) z REGRES na merge-base
    HEAD z ``base``, ``workers`` mutacji naraz; kod 0, gdy każda mutacja jest WYKRYTA."""

    judge = partial(_review_judgement, base=base)
    return _check(mutations, judge=judge, part=_environment_part(), script=_script(), workers=workers, limit_s=limit_s)


def _check(mutations: Sequence[Mutation], *, judge: _Judge, part: str, script: str, workers: int, limit_s: float) -> int:
    """Podstawa, werdykt ``judge`` i czas polecenia każdej mutacji części ``part`` (pusta: całej listy); kod 0, gdy
    ``judge`` uznał każdą za wykrytą.

    Pod linią ``PODSTAWA CZERWONA`` stderr dostaje koniec stdout i stderr polecenia podstawy (``BASE_TAIL`` linii
    każdego), także podstawy, która przekroczyła ``limit_s``, bo ostatnia linia nie zawsze mówi, co padło, a kopii
    commitu z wyjściem już nie ma (#932, #947). Podstawa pytest, z którą nie biegł żaden test (``_without_test``), ma
    między nimi linię ``PODSTAWA BEZ TESTU`` z przyczyną (``_no_test_cause``).

    Przed linią werdyktu każdej mutacji linia ``CZAS`` na stderr podaje czas jej polecenia, a mutację, której polecenie
    trwało ponad ``NEAR_LIMIT`` limitu ``limit_s``, linia ``CZAS BLISKO LIMITU`` na stderr przed linią końcową wymienia ze
    skryptem ``script``, częścią i limitem (``NearLimit.line``), zanim limit da PRZEKROCZONY CZAS (#911, #927). Log CI
    skryptu skilla ma obie, a ``near_limits`` czyta ostrzeżenia z obu strumieni wyniku skryptu (#935). To nie werdykt,
    więc stdout (werdykty i linia końcowa) i kod wyjścia się nie zmieniają. Czas ma każda mutacja, której polecenie
    biegło, także po limicie, więc linię ``CZAS`` i ostrzeżenie dostaje też PRZEKROCZONY CZAS, który brama typów zmienia w
    WYKRYTA PRZEZ BRAMĘ TYPÓW, i ZAWIESZENIE, które ``in_ci`` liczy jako wykrycie; bez linii ``CZAS`` jest tylko mutacja,
    której polecenie nie biegło (NIEAKTUALNA, BEZ WERDYKTU przed startem).
    """

    if not mutations:
        print("MUTACJE: brak mutacji, więc nie ma czego dowieść")
        return 1
    if part:
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
    timed = list(_timed(mutations, workers=workers, limit_s=limit_s))
    times = [seconds for _, _, seconds in timed]
    judged = judge(mutations, [(verdict, last) for verdict, last, _ in timed], workers=workers, limit_s=limit_s)
    for mutation, (verdict, last, caught), seconds in zip(mutations, judged, times, strict=True):
        failures += not caught
        harm = f" ({mutation.harm})" if mutation.harm else ""
        if seconds is not None:
            print(f"CZAS: {mutation.name} → {seconds:.0f} s", file=sys.stderr, flush=True)
        print(f"{verdict}: {mutation.name}{harm} → {last}", flush=True)
    for mutation, seconds in zip(mutations, times, strict=True):
        if seconds is not None and seconds > NEAR_LIMIT * limit_s:
            print(NearLimit(script, part, mutation.name, round(seconds), limit_s).line, file=sys.stderr, flush=True)
    print(MUTACJE_OK if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


def _environment_part() -> str:
    return os.environ.get(ZMIENNA_CZESCI, "")


def _script() -> str:
    """Skrypt, który uruchomił ``check_all``, względem korzenia repozytorium, jak w poleceniu CI."""

    path = Path(sys.argv[0]).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else sys.argv[0]


@dataclass(frozen=True)
class NearLimit:
    """Ostrzeżenie ``CZAS BLISKO LIMITU``: mutacja ``name`` skryptu ``script`` (część ``part`` z ``MUTACJE_CZESC``, pusta
    bez niej), której polecenie trwało ``seconds`` z limitu ``limit_s``. ``check_all`` drukuje je linią ``line``, a
    ``near_limits`` czyta je z wyjścia skryptu, więc noc dostaje je przez zapis wykonania planu CI (#935): wpis
    ``record`` pod kluczem kroku, który ``from_record`` czyta z powrotem."""

    script: str
    part: str
    name: str
    seconds: int
    limit_s: float

    @property
    def line(self) -> str:
        part = f" ({ZMIENNA_CZESCI}={self.part})" if self.part else ""
        near = f"CZAS BLISKO LIMITU: {self.script}{part}: {self.name} → {self.seconds} s z limitu --limit-s {self.limit_s:g} s"
        return (
            f"{near} (po nim PRZEKROCZONY CZAS i czerwony main: to jeszcze nie porażka, ale przenieś mutację do mniejszego "
            "zakresu sprawdzenia albo przyspiesz sprawdzenie; ostrzeżenie z nocy trafia raz do issue „Przeżyte mutacje skilli z #N”)"
        )

    def record(self, key: str) -> dict[str, Any]:
        """Wpis ``blisko_limitu`` zapisu wykonania zadania planu CI: klucz kroku skilla ``key`` i pola ostrzeżenia."""

        return {"klucz": key, **asdict(self)}

    @classmethod
    def from_record(cls, entry: dict[str, Any]) -> tuple[str, NearLimit]:
        fields = dict(entry)
        key = str(fields.pop("klucz"))
        return key, cls(**fields)


# ``NearLimit.line`` na początku linii; nazwa mutacji kończy się przed ostatnią strzałką przed czasem.
_NEAR = re.compile(
    rf"^CZAS BLISKO LIMITU: (?P<script>\S+)(?: \({ZMIENNA_CZESCI}=(?P<part>[0-9]+/[0-9]+)\))?: (?P<name>.+) → (?P<seconds>[0-9]+) s z limitu --limit-s (?P<limit>\S+) s \(po nim ",
    re.MULTILINE,
)


def near_limits(done: subprocess.CompletedProcess[str]) -> list[NearLimit]:
    """Ostrzeżenia ``CZAS BLISKO LIMITU``, które ``check_all`` skryptu ``done`` wydrukował, w ich kolejności: ze stderr,
    gdzie je drukuje, a też ze stdout, gdy wołający połączył z nim stderr."""

    output = f"{done.stdout or ''}\n{done.stderr or ''}"
    return [NearLimit(found["script"], found["part"] or "", found["name"], int(found["seconds"]), float(found["limit"])) for found in _NEAR.finditer(output)]
