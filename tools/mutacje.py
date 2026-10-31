"""Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.

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
Mutacje biegną po kolei, bo równoległe testy przekraczają swoje limity czasu; ``--rownolegle`` puszcza
naraz najwyżej ``PARALLEL``, a ich polecenia dostają ``PYTEST_XDIST_AUTO_NUM_WORKERS=1`` (chyba że wywołujący je
ustawił), bo gołe ``pytest -n auto`` w teście każdej z nich bierze wszystkie rdzenie komputera.
Polecenia i kopie biegną przez ``tools/lib/potomne.py``: procesy potomne polecenia giną z jego końcem, a
przekroczony czas, przerwanie (Ctrl-C) i zabicie narzędzia kończą polecenie i usuwają kopie.

    .venv/bin/python tools/mutacje.py --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod' \\
        -- -m pytest -q tests/test_x.py -k nazwa_testu
    .venv/bin/python tools/mutacje.py --plik mutacje.json -- -m pytest -q tests/test_x.py
    .venv/bin/python tools/mutacje.py --jak-ci 41204010349 --zmiana src/rozliczenia/x.py 'stary kod' 'nowy kod'

Plik JSON to lista ``{"nazwa", "zmiany": [[plik, kotwica, zamiana], ...]}`` z opcjonalnym
``"polecenie"`` (argumenty Pythona), które zastępuje polecenie po ``--``, i opcjonalnym
``"oczekiwane"``, początkiem ostatniej linii wyjścia, który wykrywa mutację zamiast kodu wyjścia.
Lista dłuższa niż ``ciezkie_ci.TARGETED`` mutacji to ręczne ``change-mutations``: poza CI narzędzie odmawia
jej startu (kod 2 i linia ``CIĘŻKIE CI ODMOWA``) na zasadach ``tools/lib/ciezkie_ci.py``. Skrypty
``check_<co>_mutations.py`` skilli ``verify-*`` używają tego samego silnika przez ``check_all``, który
takiego limitu nie ma.

Z ``MUTACJE_CZESC=K/N`` w środowisku ``check_all`` sprawdza tylko K-tą z N części tabeli: mutacje w kolejności nazw,
co N-tą od K-tej, więc część nie zależy od kolejności tabeli, a N części sprawdza każdą mutację dokładnie raz. Podstawa
części to tylko polecenia jej mutacji, a część bez mutacji kończy się ``MUTACJE OK``. Tak plan CI
(``tools/plan_ci.py``) dzieli długi skrypt mutacji skilla na zadania bez zmiany skryptu.
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
from typing import Protocol, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
# plan_ci i wplyw_zmiany importuje dopiero --jak-ci: plan_ci sam importuje ten moduł.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ciezkie_ci
import potomne

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600
# Tyle mutacji naraz dawał ThreadPoolExecutor (rdzenie + 4) na 4 vCPU runnera CI; na 16 rdzeniach Maca dawał 20.
PARALLEL = 8
# Cache mypy kroków bramy typów (``--cache-dir`` kroku Windows leży w nim), który kopia bez mutacji daje kopiom mutacji.
MYPY_CACHE = ".mypy_cache"
PART = "MUTACJE_CZESC"
BASE = "origin/main"
# Linie, którymi pytest-timeout kończy test po limicie, w pytest_timeout.py 2.4: ``PYTEST_FAILURE_MESSAGE`` metody
# ``signal`` jako błąd testu (``E   Failed: …``) albo w krótkim podsumowaniu (``FAILED <test> - Failed: …``) i nagłówek
# zrzutu stosów metody ``thread`` (``terminal.sep("+", title="Timeout")``). Cała linia, bo ten sam tekst w cudzysłowie
# drukuje też asercja testu, który go sprawdza.
PYTEST_TIMEOUT = re.compile(r"(?:E\s+|FAILED \S+ - )?(?P<hang>Failed: Timeout \(>[0-9.]+s\) from pytest-timeout\.)|(?P<thread>\++ Timeout \++)")


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
    inherited = {name: value for name, value in os.environ.items() if name != PART}
    return {
        **nested,
        **inherited,
        "PYTHONPATH": os.pathsep.join([str(copy / "src"), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }


def _git(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout


def _uncommitted() -> list[str]:
    """Ścieżki, w których checkout różni się od HEAD: zmienione, także w indeksie, usunięte i nieśledzone."""

    changed = _git("diff", "--name-only", "-z", "--no-renames", "HEAD") + _git("ls-files", "-z", "--others", "--exclude-standard")
    return sorted(set(filter(None, changed.decode("utf-8").split("\0"))))


@contextmanager
def checkout_copy(commit: str | None = None) -> Iterator[Path]:
    """Kopia HEAD z niezacommitowanymi zmianami checkoutu albo, z ``commit``, kopia samego commitu."""

    names = [] if commit is not None else _uncommitted()
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


def _run(
    copy: Path, command: Sequence[str], limit_s: float, stop: threading.Event | None = None, *, concurrent: bool = False
) -> _Ran:
    """Uruchamia polecenie w kopii; zwraca kod wyjścia, ostatnią linię i linię pytest-timeout, jeśli była."""

    try:
        env = environment(copy, concurrent=concurrent)
        done = potomne.run([sys.executable, *command], cwd=copy, env=env, timeout=limit_s, stop=stop)
    except subprocess.TimeoutExpired:
        return _Ran(None, f"brak wyniku po {limit_s:g} s", None)
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    hangs = (PYTEST_TIMEOUT.fullmatch(line.strip()) for line in f"{done.stdout}\n{done.stderr}".splitlines())
    hang = next((found["hang"] or found["thread"] for found in hangs if found), None)
    return _Ran(done.returncode, lines[-1] if lines else f"kod wyjścia {done.returncode}", hang)


def _verdict(
    mutation: Mutation, *, limit_s: float, stop: threading.Event, concurrent: bool, deadline: float | None, commit: str | None
) -> tuple[Verdict, str]:
    left = limit_s if deadline is None else deadline - time.monotonic()
    if left <= 0:
        return Verdict.NO_VERDICT, "czas minął, zanim się zaczęła"
    with checkout_copy(commit) as copy:
        stale = _apply(copy, mutation.edits)
        if stale:
            return Verdict.STALE, stale
        ran = _run(copy, mutation.command, min(limit_s, left), stop, concurrent=concurrent)
    if ran.code is None:
        # Koniec czasu wywołującego, a nie limit polecenia, nie mówi, czy mutacja zawiesza polecenie.
        return (Verdict.OVER_LIMIT, f"{ran.last} ({OVER_LIMIT_NOTE})") if left >= limit_s else (Verdict.NO_VERDICT, ran.last)
    if ran.hang is not None:
        return Verdict.HANG, ran.hang
    caught = ran.last.startswith(mutation.expected) if mutation.expected is not None else ran.code != 0
    return (Verdict.CAUGHT if caught else Verdict.SURVIVED), ran.last


def _baseline(mutations: Sequence[Mutation], limit_s: float, commit: str | None = None) -> dict[tuple[str, ...], str]:
    """Polecenia, które bez mutacji padają albo kończą się linią oczekiwaną po mutacji, z ostatnią linią wyjścia."""

    expected: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for mutation in mutations:
        expected[mutation.command] |= set() if mutation.expected is None else {mutation.expected}
    red = {}
    with checkout_copy(commit) as copy:
        for command in sorted(expected):
            ran = _run(copy, command, limit_s)
            if ran.code != 0 or any(ran.last.startswith(line) for line in expected[command]):
                red[command] = ran.last
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
    """Mutacje części ``K/N`` w kolejności tabeli; zła postać to ``ValueError`` z nazwą zmiennej."""

    number, _, count = part.partition("/")
    if not (number.isdigit() and count.isdigit() and 1 <= int(number) <= int(count)):
        raise ValueError(f"{PART} to K/N z 1 <= K <= N, nie {part!r}")
    by_name = sorted(range(len(mutations)), key=lambda index: (mutations[index].name, repr(mutations[index])))
    chosen = set(by_name[int(number) - 1 :: int(count)])
    return [mutation for index, mutation in enumerate(mutations) if index in chosen]


def _against_base(
    mutations: Sequence[Mutation], found: Sequence[tuple[Verdict, str]], base: str, *, workers: int, limit_s: float
) -> list[tuple[Verdict, str]]:
    """Mutacje NIEWYKRYTA na HEAD, które na merge-base HEAD z ``base`` są WYKRYTA, jako REGRES.

    Mutacja, której merge-base nie rozstrzyga (podstawa czerwona, inny werdykt niż NIEWYKRYTA), zostaje NIEWYKRYTA z
    dopiskiem, co dał merge-base; ta, która tam też jest NIEWYKRYTA, zostaje bez zmian.
    """

    survived = [index for index, (verdict, _) in enumerate(found) if verdict is Verdict.SURVIVED]
    if not survived:
        return list(found)
    fork = subprocess.run(["git", "merge-base", "HEAD", base], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    if fork.returncode:
        # Na stderr: pierwsza linia wyjścia to werdykt mutacji, także w checkoucie CI bez gałęzi bazy.
        print(f"MERGE-BASE: brak merge-base HEAD z {base}, więc REGRES niesprawdzony, a NIEWYKRYTA bez porównania ({fork.stderr.strip()})", file=sys.stderr, flush=True)
        return list(found)
    commit = fork.stdout.strip()
    if commit == _git("rev-parse", "HEAD").decode("utf-8").strip() and not _uncommitted():
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
            result[index] = (Verdict.SURVIVED, f"{last} (na merge-base {commit[:8]} podstawa czerwona: {red[command]})")
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
    """Podstawa i werdykt każdej mutacji; kod 0, gdy CI złapałoby każdą (``in_ci``).

    Bez ``base`` (skrypty mutacji skilli) mutację, którą polecenie przepuściło, sprawdza jeszcze ``type_gate`` z ``gate``. Z
    ``base``, czyli w przeglądzie z wiersza poleceń, porażką jest wszystko poza WYKRYTA, także ZAWIESZENIE, a mutacja
    NIEWYKRYTA biegnie też na merge-base HEAD z ``base`` (REGRES), bez bramy typów.
    """

    if not mutations:
        print("MUTACJE: brak mutacji, więc nie ma czego dowieść")
        return 1
    if part := os.environ.get(PART):
        total = len(mutations)
        mutations = _part(mutations, part)
        print(f"MUTACJE CZĘŚĆ {part}: {len(mutations)} z {total} mutacji", flush=True)
        if not mutations:
            print("MUTACJE OK")
            return 0
    red = _baseline(mutations, limit_s)
    for command, last in red.items():
        print(f"PODSTAWA CZERWONA: {' '.join(command)} → {last}", flush=True)
    if red:
        print("MUTACJE: polecenie bez mutacji pada albo daje wynik mutacji, więc wynik po mutacji niczego nie dowodzi")
        return 2
    failures = 0
    workers = PARALLEL if parallel else 1
    found = list(verdicts(mutations, workers=workers, limit_s=limit_s))
    if base is not None:
        found = _against_base(mutations, found, base, workers=workers, limit_s=limit_s)
    else:
        found = type_gate(mutations, found, workers=workers, limit_s=limit_s, gate=gate)
    for mutation, (verdict, shown) in zip(mutations, found, strict=True):
        caught, last = (verdict is Verdict.CAUGHT, shown) if base is not None else in_ci(verdict, shown)
        failures += not caught
        harm = f" ({mutation.harm})" if mutation.harm else ""
        print(f"{verdict}: {mutation.name}{harm} → {last}", flush=True)
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


def _from_file(path: Path, command: tuple[str, ...], *, own_command: bool = True) -> list[Mutation]:
    entries = json.loads(path.read_text(encoding="utf-8"))
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
        files = list(dict.fromkeys(unit.removeprefix("pytest:").partition("#")[0] for unit in units if unit.startswith("pytest:")))
        if track in tracks and any(file.partition("::")[0] in tested for file in files):
            found.append((name, files))
    return found


def _output(command: Sequence[str]) -> str:
    """Wyjście polecenia ``gh`` albo ``git``; porażka to ``ValueError`` z końcem jego błędu."""

    done = potomne.run(command, cwd=ROOT)
    if done.returncode:
        raise ValueError(f"{' '.join(command[:3])} padł: {(done.stderr.strip() or done.stdout.strip())[-300:]}")
    return done.stdout.strip()


def _last_run() -> str:
    """Numer ostatniego runu ``ci.yml`` gałęzi, którą śledzi bieżąca (bez śledzonej: bieżącej)."""

    head = _output(["git", "rev-parse", "--symbolic-full-name", "HEAD"])
    if not head.startswith("refs/heads/"):
        raise ValueError("HEAD nie jest na gałęzi, więc podaj numer runu CI: --jak-ci <id runu>")
    branch = _output(["git", "for-each-ref", "--format=%(upstream:lstrip=3)", head]) or head.removeprefix("refs/heads/")
    runs = json.loads(_output(["gh", "run", "list", "--workflow", "ci.yml", "--branch", branch, "--limit", "1", "--json", "databaseId"]))
    if not runs:
        raise ValueError(f"gałąź {branch} nie ma runu CI, więc podaj numer runu: --jak-ci <id runu>")
    return str(runs[0]["databaseId"])


def _ci_mutations(mutations: Sequence[Mutation], run: str, base: str) -> list[Mutation]:
    """Każda mutacja raz na każde zadanie pytest runu ``run`` (pusty: ``_last_run``), w którym stoi test zmieniony od
    ``base``, z poleceniem ``pytest -n 1`` z plikami tego zadania."""

    # Przez import_module: plan_ci importuje ten moduł, a kopie narzędzi w repozytoriach testów nie mają ani jego, ani wplyw_zmiany.
    plan_ci = importlib.import_module("plan_ci")
    wplyw_zmiany = importlib.import_module("wplyw_zmiany")
    try:
        tested = wplyw_zmiany.changed_since(ROOT, base)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"brak merge-base HEAD z {base}, więc nie wiadomo, które testy zmieniono: {error.stderr.strip()}") from error
    run = run or _last_run()
    with tempfile.TemporaryDirectory(prefix="plan-ci-") as folder:
        _output(["gh", "run", "download", run, "--name", "plan", "--dir", folder])
        plan = plan_ci.Plan.z_json((Path(folder) / "plan.json").read_text(encoding="utf-8"))
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    args = parser.parse_args(arguments[:split])
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
        parser.error("podaj mutację (--zmiana albo --plik) i polecenie po --, np. -- -m pytest -q tests/test_x.py, albo --jak-ci")
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
