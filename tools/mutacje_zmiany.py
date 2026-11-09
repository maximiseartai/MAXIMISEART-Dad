"""Psuje linie zmienione od bazy jak nocne mutacje main; użyj, gdy część nocnych mutacji padła i odtwarzasz ją na commicie runu (--odtwarzam).

Psuje zmienione linie ``src/`` i ``tools/`` i sprawdza, że test to zauważa, jak nocne mutacje ``main`` (ADR 0021).

Zmiana to linie plików ``src/**/*.py`` i ``tools/**/*.py``, którymi checkout (z niezacommitowanymi i nieśledzonymi
plikami) różni się od ``merge-base`` HEAD z ``--baza`` (domyślnie ``origin/main``). Na każdej zmienionej linii narzędzie
robi mutacje, które przeglądy PR-ów robiły ręcznie i które przeżywały testy:

- bez jednego członu ``and``/``or``;
- wyrażenie ``a if w else b`` zastąpione jedną gałęzią;
- ``True`` zamienione na ``False`` i odwrotnie;
- warunek ``if`` zawsze prawdziwy i zawsze fałszywy;
- granica porównania (``<`` i ``<=``, ``>`` i ``>=``);
- ``return wartość`` zamienione na ``return None``, a w funkcji modułu, której wynik moduł podaje ``sys.exit(...)``
  albo ``raise SystemExit(...)`` (``sys.exit(main())``), ``return <liczba>`` zamienione na inny kod wyjścia
  (``return 0`` na ``return 1``, inna liczba na ``return 0``), bo ``sys.exit(None)`` kończy się kodem 0 jak ``return 0``;
- ``a in b``, ``b.startswith(a)`` i ``b.endswith(a)`` zamienione na siebie nawzajem (także ``not in``), gdy ``b`` nie
  jest literałem kolekcji, a ``startswith``/``endswith`` mają jeden argument, który nie jest krotką; biegnie
  ``in`` → ``startswith``, ``startswith`` → ``endswith`` i ``endswith`` → ``startswith``;
- argument nazwany (``wersja=wersja``) ustawiony na ``None``, gdy jego wartość nie jest stałą (stałą psuje już
  ``True``/``False``, a ``encoding="utf-8"`` bez niej działa na Linuksie tak samo); pozycyjnych narzędzie nie rusza,
  bo ich ``None`` zwykle tylko wywraca wywołanie;
- wywołanie w osobnej linii usunięte;
- bez jednego elementu krotki, która nie jest samymi stałymi;
- fragment zmiany (hunk) cofnięty do bazy: test poprawki, który przechodzi bez niej, tu przeżywa.

Biegnie każde cofnięcie fragmentu i najwyżej jedna inna mutacja na linię (``selected``): ta z najgłębszego węzła
drzewa składni linii, czyli ostatnia, którą daje przejście drzewa wszerz (``ast.walk``), a z kilku na tym samym węźle
ostatnia z nich. Psuje ona najmniejszy kawałek linii, więc przeżywa test, który sprawdza tylko ogólny skutek linii;
ogólny skutek fragmentu sprawdza już jego cofnięcie. Predykat napisu biegnie tylko na linii bez innej mutacji: przy
zbiorze albo słowniku po prawej ``startswith`` tylko rzuca ``AttributeError``. Cofnięcie, które daje ten sam kod co
inna mutacja (bez elementu krotki, ``False`` → ``True``), biegnie jako cofnięcie pod jej opisem. Linia mutacji to linia
jej wyjątku (``Mutant.line``).

Mutacja, która zmienia tylko docstringi, komentarze, adnotacje argumentów i wyników funkcji, importy albo aliasy
typów (``Nazwa = Callable[...]``, ``A | B`` czytane tylko w adnotacjach), nie zmienia zachowania, więc jej nie ma.
Dekoratorów narzędzie nie psuje, a samo usunięcie linii (bez linii dodanej w tym miejscu) nie daje mutacji.
Kod, którego na tym systemie strzeże ``sys.platform ==``/``!=`` literał, dostaje linię ``POMINIĘTA``: gałąź ``if``
albo ``… if … else …`` innego systemu, kod po ``if`` z takim warunkiem, którego ciało kończy się ``return``/``raise``
na tym systemie, i sam warunek. Kod tylko dla innego systemu w innej postaci (stała czytana tylko w jego gałęzi,
warunek przez ``startswith`` albo zmienną) przeżywa i potrzebuje wyjątku.

Najpierw biegną raz testy dotknięte zmianą, wybrane jak w ``tools/szybko.py`` (``tools/lib/wplyw_zmiany.py``), z pluginem
``tools/lib/pytest_pokrycie.py``. Zapisuje on, które testy wykonują które zmienione linie i jakikolwiek kod zmienionych
plików, także w procesach Pythona uruchomionych przez test, oraz linie wykonane dla wielu testów naraz: przy imporcie
modułu i w fixture o zasięgu szerszym niż test. Testy muszą przejść, inaczej wynik mutacji niczego nie dowodzi.

Potem każda mutacja biegnie przez silnik ``tools/mutacje.py`` (własna kopia checkoutu), najpierw z testami, które
wykonały jej linie. Pokrycie tylko przyspiesza wykrycie: mutacja, która je przeżyła, biegnie drugi raz, po jednej
naraz z ``--rownolegle`` workerami xdist, i dopiero ta porażka daje ``NIEWYKRYTA``. Drugi raz biegną testy, które
wykonały jakikolwiek kod jej pliku albo uruchomiły proces i dochodzą do pliku importem albo nazwą pliku, katalogu
lub globu w teście albo jego fixture (``Repository.reaching``), a wszystkie testy dotknięte plikiem, gdy linię wykonano
dla wielu testów naraz albo leży w funkcji z ``@cache``, ``@lru_cache`` albo ``@cached_property`` (wynik pierwszego wywołania dostają też
inne testy). Taką mutację przed testami pliku sprawdzają jeszcze, po kilka mutacji naraz jak w pierwszym przebiegu,
testy, które wykonały jakikolwiek kod jej pliku (linia ``(testy kodu pliku)``): tabelę modułu wykonuje import, a
czytają ją funkcje pliku. Kodu procesu zapis nie widzi, gdy proces ma ``-I`` albo własne środowisko bez zmiennych zapisu, i gdy
wykonuje kopię pliku spoza checkoutu: tak test uruchamia narzędzie z ``tools/`` skopiowane do repozytorium w katalogu
tymczasowym. Wtedy mutację tej linii od razu sprawdzają te same testy. Test, który dochodzi do pliku tylko przez
ścieżkę nazwaną w innym narzędziu i nie wykonał jego kodu, nie biegnie: to każdy test z repozytorium Gita, bo
``tests/fixtures/git_repo.py`` kopiuje ``tools/ci_lokalnie.py``, a ten nazywa ``tools/mutacje_zmiany.py``.
Kod, który biegnie tylko w takim procesie z ``-I`` uruchomionym przez inne narzędzie, dostaje więc ``NIEWYKRYTA``,
nawet gdy test tamtego narzędzia by go wykrył: potrzebuje testu, który sam nazywa jego plik.
Mutacja, po której pytest-timeout kończy test (``ZAWIESZENIE``), liczy się jak wykryta z dopiskiem ``liczona jako
wykryta: pytest-timeout czerwieni test w CI`` (``mutacje.in_ci``) i nie biegnie z szerszymi testami. Mutacja, po której
testy nie kończą się w ``--limit-s`` (``PRZEKROCZONY CZAS``), biegnie dalej jak przeżyta, bo test tylko wolniejszy CI
przechodzi.
Mutację, która przeżyła ostatni przebieg testów albo nie ma żadnego testu, sprawdza jeszcze brama typów
(``mutacje.type_gate``): ruff i mypy obu systemów, kroki bramy pre-push. Mutacja, po której któryś zgłasza, że kod jest
błędny (niezdefiniowana nazwa, błąd składni, błąd typów), to ``WYKRYTA PRZEZ BRAMĘ TYPÓW`` z nazwą kroku i tym błędem, i
nie trafia do zapisu ani do issue (``mutacje.wrong``). Cofnięcia fragmentu do bazy (``Mutant.revert``) brama nie
sprawdza: przywraca ono kod, który przeszedł bramę, więc jej błąd na nim powstaje tylko z niezgodności z niecofniętymi
fragmentami tej samej zmiany (import, adnotacja, typ w innym miejscu). Pełne cofnięcie zmiany przeszłoby bramę, a testy
by go nie złapały, więc takie cofnięcie przeżywa i trafia do issue; gdy zmiana była tylko typów, agent odpowiada
``nie warto`` (#671, #674).
Linia ``CZAS`` mówi, ile trwała każda faza, także brama typów.

Mutacja, która przeżywa, to obietnica bez testu: dopisz test, który ją wykrywa. Mutacja równoważna (kod robi to samo)
dostaje wyjątek w linii mutacji albo w samodzielnym komentarzu tuż nad nią:
``# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>``. Wyjątek obejmuje każdą mutację tej linii; cofnięcie
fragmentu ma linię początku fragmentu, więc obejmuje je komentarz nad nim albo w jego pierwszej linii. Wyjątek po
terminie nie obowiązuje, ale narzędzie widzi go dopiero przy
następnej zmianie jego pliku, a komentarz ``mutacje-zmiany:`` w innej postaci kończy narzędzie błędem.

Kończy się ``MUTACJE ZMIANY OK | …`` (kod 0) albo ``MUTACJE ZMIANY FAIL | …``: kodem 1, gdy przeżyły mutacje, kodem
2, gdy wynik mutacji nic nie mówi (nieznana baza, zły wyjątek, testy padają albo nie kończą się w limicie czasu części
bez mutacji, odmowa ``tools/lib/ciezkie_ci.py``), a kodem 3, gdy limit czasu części (``--limit-czesci-s``) minął po
pokryciu, przed werdyktem którejś mutacji. Po limicie żadne polecenie już nie biegnie, a mutacje bez wyniku dostają
linię ``BEZ WERDYKTU``, więc część kończy się zapisem przed limitem czasu zadania CI.
W CI biegnie nocą na Linuksie, na ``main``, od bazy z ``tools/mutacje_nocne.py``, w częściach
workflow ``mutacje-nocne.yml``. Z ``--zapis`` każda część zapisuje swoją ostatnią linię, przeżyte mutacje i mutacje bez
werdyktu po limicie czasu części: plik, linię i opis z nazwy (``<plik>:<linia> <opis>``, jak w linii ``NIEWYKRYTA``),
zmienione linie, które mutacja psuje (``Mutant.lines``), i klucz (``fingerprint``), a do tego kod wyjścia; z nich
``tools/mutacje_nocne.py`` zakłada issue PR-u, który ostatni zmienił te linie.

Granica: nie zastępuje mutacji z opisu PR. Obietnicę, której żadna z tych mutacji nie psuje (inny klucz
wyszukiwania, kolejność kroków), samo usunięcie linii, dekoratory, argument pozycyjny, kod poza ``src/`` i ``tools/``
(skrypty skilli w ``.agents/skills/*/scripts``, bo zwykle nie biegnie ich żaden test pytest, ``ci.yml``) i kod innego
systemu łapie tylko przegląd z mutacjami z ``tools/mutacje.py``.

Pod ``tools/na_scalonych_pr.py`` pliki ``tools/``, które ten podmienił narzędziami z checkoutu, nie są zmianą, a zmianę
commitu w takim pliku narzędzie zgłasza linią ``NIESPRAWDZONA``: zmianę ``tools/`` z historii sprawdza tylko próba
z ``--narzedzia`` wskazującym commit, który do narzędzi tego commitu dokłada samo nowe ``tools/mutacje_zmiany.py``.

Poza CI biegnie tylko do odtworzenia części, która padła (kod 2) w runie Actions (``tools/lib/ciezkie_ci.py``). Run
nocny odtwarza się na jego commicie, z bazą i częścią z jego planu:

    git checkout --detach <headSha runu>
    .venv/bin/python tools/mutacje_zmiany.py --baza <baza z planu> --do <do z planu> --czesc K/N --odtwarzam <id albo URL runu>

Z ``--czesc K/N`` biegnie K-ty z N kolejnych kawałków listy mutacji, posortowanej po plikach i liniach, więc N zadań
CI dzieli mutacje bez listy w workflow, a każde liczy pokrycie tylko na testach swoich kilku plików.
Z ``--do <commit>`` lista ma tylko mutacje, z których linii co najmniej jedną ostatni zmienił (``git blame
--first-parent``) commit, który ``<commit>`` zawiera: noc z zaległością mutuje zmiany ``main`` tylko do tego commitu
(``tools/mutacje_nocne.py``).
Listę mutacji od bazy, jej przycięcie do ``--do`` i kawałek części liczy ``ZakresMutacji``, o który pyta też plan nocy
w ``tools/mutacje_nocne.py``, więc plan i części dzielą tę samą listę.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
import datetime
import difflib
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tokenize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import ciezkie_ci
from jednostka import Czesc
import mutacje
import pokrycie_procesu
import potomne
from repo import BASE, ROOT
import repo
import wplyw_zmiany

# Mutacji naraz i workerów xdist pokrycia: 4 vCPU runnera Linux nocy. Stała, a nie ``mutacje.PARALLEL`` (rdzenie
# komputera), bo z niej plan nocy liczy rozmiar części (``mutacje_nocne.NA_CZESC``, ADR 0021), który nie może zależeć od
# komputera, na którym plan biegnie.
WORKERS = 4
# Limit czasu testów jednej mutacji (``--limit-s``): polecenie bez wyniku po nim to PRZEKROCZONY CZAS.
MUTATION_LIMIT_S = 900
# Zadanie części w mutacje-nocne.yml ma 180 min; 5 min zostaje na instalację i wgranie zapisu.
PART_LIMIT_S = 10500
# Początek ostatniej linii części bez porażki i części, w której przeżyły mutacje (kod 1): wyniki, które
# ``tools/mutacje_nocne.py`` tylko zgłasza.
OK = "MUTACJE ZMIANY OK"
SURVIVED = "MUTACJE ZMIANY FAIL | przeżyło"
# Kody wyjścia części, której zapis ``--zapis`` niesie wynik mutacji: 0 bez przeżytych, 1 z przeżytymi, 3 z mutacjami bez
# werdyktu po limicie czasu części; kod 2 nic o mutacjach nie mówi.
KODY_Z_WYNIKIEM = frozenset({0, 1, 3})
# Linia poleceń Windows ma najwyżej 32 767 znaków; dłuższa lista testów idzie jako pliki testów.
COMMAND_LIMIT = 20_000
EXCEPTION = re.compile(r"#\s*mutacje-zmiany:(?P<rest>.*)$")
EXCEPTION_FORM = re.compile(r"\s*(?P<reason>[^|]*\S)\s*\|\s*do\s+(?P<until>\d{4}-\d{2}-\d{2})\s*\|\s*zgoda\s+(?P<who>\S.*?)\s*$")
Node = ast.expr | ast.stmt
_HUNK = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@")


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int  # linia, w której wyjątek wyłącza mutację
    lines: frozenset[int]  # zmienione linie, które mutacja psuje
    description: str
    source: str  # cały plik po mutacji
    other_system: bool = False  # kod gałęzi innego systemu niż ten, na którym biegną testy
    shared_state: bool = False  # kod funkcji z ``@cache``: wynik pierwszego wywołania dostają następne testy
    revert: bool = False  # cofnięcie fragmentu zmiany do bazy
    last_resort: bool = False  # predykat napisu: biegnie tylko na linii bez innej mutacji


@dataclass(frozen=True)
class Allowance:
    reason: str
    until: datetime.date
    who: str


@dataclass(frozen=True)
class Hunk:
    start: int  # pierwsza linia po zmianie; przy samym usunięciu linia, po której stały usunięte
    count: int
    old: tuple[str, ...]


def _short(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[: limit - 1]}…"


CODE = ("src/", "tools/")  # foldery, których pliki ``.py`` psuje zakres


def _code(path: str) -> bool:
    return path.startswith(CODE) and path.endswith(".py")


def _changes(fork: str, root: Path) -> dict[str, list[Hunk]]:
    """Fragmenty zmiany każdego pliku ``src/**/*.py`` i ``tools/**/*.py`` z checkoutu ``root``; nowy plik to jeden fragment."""

    found: dict[str, list[Hunk]] = defaultdict(list)
    current: str | None = None
    old_left = new_left = 0  # linie fragmentu, których parser jeszcze nie przeczytał: nie są nagłówkiem
    # Przeniesiony plik (``-M``) psuje tylko linie, które przy przeniesieniu się zmieniły, także gdy przyszedł spoza
    # ``src/`` i ``tools/``: dlatego diff obejmuje całe repozytorium, a ścieżki odsiewa ``_code`` po nagłówku ``+++``.
    # Linie spoza UTF-8 mogą mieć tylko pliki, które ``_code`` odsiewa (plik ``.py`` czyta ``read_text`` w UTF-8),
    # więc zastąpienie ich znaków nie zmienia fragmentów.
    # Usunięty plik nie ma linii do zepsucia, więc każdy nagłówek ``+++`` to ``b/<ścieżka>``.
    for line in repo.git(root, "diff", "-U0", "-M", "--diff-filter=d", "--no-color", fork).split("\n"):
        if old_left and line.startswith("-"):
            old_left -= 1
            if current is not None:
                hunk = found[current][-1]
                found[current][-1] = Hunk(hunk.start, hunk.count, (*hunk.old, line[1:]))
        elif new_left and line.startswith("+"):
            new_left -= 1
        elif line.startswith("+++ "):
            path = line.removeprefix("+++ b/")
            current = path if _code(path) else None
        elif match := _HUNK.match(line):
            old_left, new_left = int(match["old_count"] or 1), int(match["new_count"] or 1)
            if current is not None:
                found[current].append(Hunk(int(match["new"]), new_left, ()))
    for name in filter(_code, repo.git(root, "ls-files", "--others", "--exclude-standard").splitlines()):
        found[name] = [Hunk(1, len(_rows((root / name).read_text(encoding="utf-8"))), ())]
    return {path: hunks for path, hunks in found.items() if (root / path).is_file()}


def _overlay(fork: str, root: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    """Pliki ``tools/``, które ``tools/na_scalonych_pr.py`` podmienił narzędziami z checkoutu, i te z nich, które zmienia commit.

    Podmieniony plik to sprawdzane narzędzie, nie zmiana. Zmiany commitu w takim pliku nie widać, bo kopia ma w jego
    miejscu narzędzie z checkoutu.
    """

    if os.environ.get(ciezkie_ci.FROM_MERGED_PRS) != "1":
        return frozenset(), ()
    replaced = repo.uncommitted(root, paths=("tools",))
    return replaced, tuple(sorted(replaced & repo.changed(root, fork, "HEAD", paths=("tools",))))


def _rows(text: str) -> list[str]:
    """Linie z końcami, jak liczy je git: tylko ``\n`` kończy linię (``str.splitlines`` dzieli też na U+2028)."""

    rows = [f"{row}\n" for row in text.split("\n")]
    rows[-1] = rows[-1][:-1]
    return rows if rows[-1] else rows[:-1]


def changed_lines(hunks: Sequence[Hunk]) -> frozenset[int]:
    return frozenset(line for hunk in hunks for line in range(hunk.start, hunk.start + hunk.count))


class _Source:
    """Tekst pliku z wymianą fragmentu wskazanego pozycjami węzła AST (kolumny w bajtach UTF-8)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.encode("utf-8").splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.data = text.encode("utf-8")

    def segment(self, node: Node) -> str:
        start, end = self._span(node)
        return self.data[start:end].decode("utf-8")

    def replaced(self, node: Node, replacement: str) -> str:
        start, end = self._span(node)
        return (self.data[:start] + replacement.encode("utf-8") + self.data[end:]).decode("utf-8")

    def _span(self, node: Node) -> tuple[int, int]:
        end_lineno = node.lineno if node.end_lineno is None else node.end_lineno
        end_col = node.col_offset if node.end_col_offset is None else node.end_col_offset
        return self.starts[node.lineno - 1] + node.col_offset, self.starts[end_lineno - 1] + end_col


def _span_lines(node: Node) -> frozenset[int]:
    return frozenset(range(node.lineno, (node.end_lineno or node.lineno) + 1))


def _skipped(tree: ast.AST) -> set[int]:
    """Węzły, których nie warto psuć: adnotacje typów, dekoratory, docstringi i bloki ``TYPE_CHECKING`` i ``__main__``."""

    skipped: set[int] = set()

    def skip(node: ast.AST | None) -> None:
        if node is not None:
            skipped.update(id(inner) for inner in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            skip(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            skip(node.returns)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # ``@dataclass(frozen=True)`` bez zamrożenia działa tak samo, dopóki nikt nie zmienia pola.
            for decorator in node.decorator_list:
                skip(decorator)
        elif isinstance(node, ast.If) and ast.unparse(node.test) in {
            "TYPE_CHECKING",
            "typing.TYPE_CHECKING",
            "__name__ == '__main__'",
        }:
            skip(node)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip(first)
    return skipped


def _platform_test(test: ast.expr) -> tuple[str, bool] | None:
    """``sys.platform == "x"`` daje ``("x", True)``, ``!=`` daje ``("x", False)``, inny warunek ``None``."""

    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.NotEq))):
        return None
    right = test.comparators[0]
    if ast.unparse(test.left) != "sys.platform" or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
        return None
    return right.value, isinstance(test.ops[0], ast.Eq)


def _ends(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _other_system(tree: ast.AST, platform: str) -> set[int]:
    """Węzły kodu, który na systemie ``platform`` nie biegnie, bo strzeże go ``sys.platform ==``/``!=`` literał."""

    other: set[int] = set()

    def mark(nodes: list[ast.stmt] | list[ast.expr]) -> None:
        other.update(id(inner) for node in nodes for inner in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)) and (found := _platform_test(node.test)) is not None:
            literal, equal = found
            here = (platform == literal) == equal
            mark([node.test])
            if isinstance(node, ast.If):
                mark(node.orelse if here else node.body)
            else:
                mark([node.orelse if here else node.body])
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block):
                guard = _platform_test(statement.test) if isinstance(statement, ast.If) else None
                if guard is not None and isinstance(statement, ast.If) and not statement.orelse and _ends(statement.body):
                    literal, equal = guard
                    if (platform == literal) == equal:
                        mark(block[index + 1 :])
    return other


_CACHES = frozenset({"cache", "lru_cache", "cached_property"})


def _cached_lines(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""
            if name in _CACHES:
                found |= _span_lines(node)
    return found


def _own(function: ast.FunctionDef) -> Iterator[ast.AST]:
    """Węzły ciała funkcji bez ciał funkcji zagnieżdżonych w niej (także metod klasy): ich ``return`` nie jest jej wynikiem."""

    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pending.extend(ast.iter_child_nodes(node))


def _exit_codes(tree: ast.Module) -> dict[int, tuple[ast.expr, int]]:
    """Wartość i inny kod wyjścia każdego ``return <liczba>`` funkcji modułu, której wynik moduł podaje ``sys.exit(...)``
    albo ``raise SystemExit(...)``: ``0`` dla liczby różnej od zera, ``1`` dla zera."""

    exiting = {
        argument.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {"sys.exit", "SystemExit"}
        for argument in node.args
        if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name)
    }
    return {
        id(node): (node.value, 0 if node.value.value else 1)
        for function in tree.body
        if isinstance(function, ast.FunctionDef) and function.name in exiting
        for node in _own(function)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and type(node.value.value) is int
    }


_BOUNDARY: dict[type[ast.cmpop], str] = {ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">"}
_PREDICATES = ("startswith", "endswith")
# Literał kolekcji nigdy nie jest napisem, więc ``x in [...]`` zamienione na ``startswith`` tylko wywraca kod.
_COLLECTIONS = (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _predicates(node: ast.AST, source: _Source) -> Iterator[tuple[Node, Node, str, str]]:
    """Zamiana predykatu napisu ``in``, ``startswith`` albo ``endswith`` na każdy z pozostałych dwóch."""

    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.In, ast.NotIn))
        and not isinstance(node.comparators[0], _COLLECTIONS)
        and not (isinstance(node.left, ast.Constant) and not isinstance(node.left.value, str))
    ):
        item, text, now = node.left, node.comparators[0], "in"
        negation = "not " if isinstance(node.ops[0], ast.NotIn) else ""
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _PREDICATES
        and len(node.args) == 1
        and not node.keywords
        and not isinstance(node.args[0], (ast.Tuple, ast.Starred))
    ):
        item, text, now, negation = node.args[0], node.func.value, node.func.attr, ""
    else:
        return
    item_code, text_code = source.segment(item), source.segment(text)
    # ``selected`` bierze ostatnią zamianę węzła, więc ``in`` dostaje ``startswith``: na #460 r1 test wykrył ``endswith``,
    # a przeżyło ``startswith``, które znalazł przegląd. Biegnie ona tylko na linii bez innej mutacji (``selected``).
    for method in ("in", "endswith", "startswith"):
        if method == now:
            continue
        shown = f"{item_code} in {text_code}" if method == "in" else f"{text_code}.{method}({item_code})"
        code = f"({item_code}) in ({text_code})" if method == "in" else f"({text_code}).{method}({item_code})"
        yield node, node, f"({negation}{code})", f"`{_short(source.segment(node))}` → `{_short(negation + shown)}`"


def _candidates(node: ast.AST, source: _Source, exit_codes: dict[int, tuple[ast.expr, int]]) -> Iterator[tuple[Node, Node, str, str]]:
    """(węzeł do zastąpienia, węzeł, którego linie psuje mutacja, zamiana, opis) dla jednego węzła.

    ``exit_codes`` to inny kod wyjścia dla ``return <liczba>`` funkcji, której wynik trafia do ``sys.exit``.
    """

    if isinstance(node, ast.BoolOp):
        word = "and" if isinstance(node.op, ast.And) else "or"
        for dropped in node.values:
            rest = [source.segment(value) for value in node.values if value is not dropped]
            yield node, dropped, f"({f' {word} '.join(rest)})", f"bez `{_short(source.segment(dropped))}` w `{word}`"
    elif isinstance(node, ast.IfExp):
        for branch in (node.body, node.orelse):
            yield node, node, f"({source.segment(branch)})", f"`{_short(source.segment(node))}` zawsze `{_short(source.segment(branch), 30)}`"
    elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
        yield node, node, str(not node.value), f"`{node.value}` → `{not node.value}`"
    elif isinstance(node, ast.If):
        for value in (True, False):
            yield node.test, node.test, str(value), f"warunek `{_short(source.segment(node.test))}` zawsze `{value}`"
    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _BOUNDARY:
        left, right = source.segment(node.left), source.segment(node.comparators[0])
        swapped = _BOUNDARY[type(node.ops[0])]
        yield node, node, f"({left} {swapped} {right})", f"granica `{_short(source.segment(node))}` → `{swapped}`"
    elif id(node) in exit_codes:
        returned, code = exit_codes[id(node)]
        yield returned, returned, str(code), f"`return {source.segment(returned)}` → `return {code}`"
    elif isinstance(node, ast.Return) and node.value is not None and not (
        isinstance(node.value, ast.Constant) and node.value.value is None
    ):
        yield node.value, node, "None", f"`return {_short(source.segment(node.value))}` → `return None`"
    elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Call, ast.Await)):
        yield node, node, "pass", f"bez wywołania `{_short(source.segment(node.value))}`"
    elif isinstance(node, ast.Call):
        for keyword in node.keywords:
            if keyword.arg is not None and not isinstance(keyword.value, ast.Constant):
                shown = f"{keyword.arg}={_short(source.segment(keyword.value), 30)}"
                yield keyword.value, keyword.value, "None", f"`{shown}` → `{keyword.arg}=None`"
    elif (
        isinstance(node, ast.Tuple)
        and isinstance(node.ctx, ast.Load)
        and 2 <= len(node.elts) <= 6
        and not any(isinstance(element, ast.Starred) for element in node.elts)
        and not all(isinstance(element, ast.Constant) for element in node.elts)
    ):
        for dropped in node.elts:
            rest = [source.segment(element) for element in node.elts if element is not dropped]
            tail = "," if len(rest) == 1 else ""
            yield node, dropped, f"({', '.join(rest)}{tail})", f"krotka bez `{_short(source.segment(dropped))}`"


def _meaning(text: str) -> str:
    """Kod bez tego, czego test nie widzi: docstringów, adnotacji funkcji, importów i aliasów typów.

    Adnotacje argumentów i wyników (``from __future__ import annotations``) nie działają w czasie wykonania, a import
    nazwy, którą kod naprawdę wywołuje, psuje już mutacja linii z tym wywołaniem. W pliku z pydantic albo FastAPI
    adnotacje i aliasy decydują o walidacji i trasach, więc zostają; tam pomija się tylko docstringi i importy.
    Adnotacje pól zostają zawsze.
    """

    tree = ast.parse(text)
    if _runtime_annotations(tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                node.body = [statement for statement in node.body if not _invisible(statement, set(), module=False)]
        return ast.dump(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            node.annotation = None
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
    loaded = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            module = isinstance(node, ast.Module)
            node.body = [statement for statement in node.body if not _invisible(statement, loaded, module=module)]
    return ast.dump(tree)


def _runtime_annotations(tree: ast.AST) -> bool:
    """Plik importuje pydantic albo FastAPI, które czytają adnotacje i aliasy typów w czasie wykonania."""

    for node in ast.walk(tree):
        names = (
            [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        )
        if any(name.split(".")[0] in {"pydantic", "fastapi"} for name in names):
            return True
    return False


_TYPE_FORMS = frozenset(
    {"Callable", "Literal", "Annotated", "Union", "Optional", "Mapping", "Sequence", "Iterable", "Iterator", "type"}
    | {"dict", "list", "tuple", "set", "frozenset"}
)


def _type_form(value: ast.expr) -> bool:
    if isinstance(value, ast.BinOp):
        return isinstance(value.op, ast.BitOr) and _type_form(value.left) and _type_form(value.right)
    if isinstance(value, ast.Constant):
        return value.value is None
    if isinstance(value, ast.Subscript):
        value = value.value
    name = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else None
    # Klasa ma nazwę w CamelCase, a stała modułu (``OPCJE["nowa"]``) wielkimi literami.
    return name is not None and (name in _TYPE_FORMS or (name[:1].isupper() and not name.isupper()))


def _invisible(statement: ast.stmt, loaded: set[str], *, module: bool) -> bool:
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
        return True
    # Alias typu modułu (``Nazwa = Callable[...]`` albo ``A | B``) czytany tylko w adnotacjach.
    return (
        module
        and isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id not in loaded
        and isinstance(statement.value, (ast.Subscript, ast.BinOp))
        and _type_form(statement.value)
    )


def mutants(path: str, text: str, hunks: Sequence[Hunk], platform: str = sys.platform) -> list[Mutant]:
    """Mutacje zmienionych linii pliku ``path`` o treści ``text``; każda daje kod, który się kompiluje.

    Testy biegną na systemie ``platform``: mutacja kodu gałęzi innego systemu ma ``other_system``.
    """

    tree = ast.parse(text)
    source = _Source(text)
    changed = changed_lines(hunks)
    skipped = _skipped(tree)
    other = _other_system(tree, platform)
    other_lines = {
        line for node in ast.walk(tree) if id(node) in other and isinstance(node, (ast.expr, ast.stmt)) for line in _span_lines(node)
    }
    cached = _cached_lines(tree)
    exit_codes = _exit_codes(tree)
    found: dict[str, Mutant] = {}
    meaning = _meaning(text)

    def add(
        lines: frozenset[int], line: int, description: str, mutated: str, *, other_system: bool, revert: bool = False, last_resort: bool = False
    ) -> None:
        if revert and mutated in found:
            # Cofnięcie, które daje kod innej mutacji, to ta mutacja: biegnie jako cofnięcie.
            found[mutated] = replace(found[mutated], revert=True)
            return
        if mutated == text or mutated in found:
            return
        try:
            compile(mutated, path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError):
            return
        if _meaning(mutated) != meaning:
            found[mutated] = Mutant(path, line, lines, description, mutated, other_system, bool(lines & cached), revert, last_resort)

    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        for last_resort, candidates in ((False, _candidates(node, source, exit_codes)), (True, _predicates(node, source))):
            for replaced, broken, replacement, description in candidates:
                lines = _span_lines(broken) & changed
                if lines:
                    mutated = source.replaced(replaced, replacement)
                    other_system = id(broken) in other or id(node) in other
                    add(lines, broken.lineno, description, mutated, other_system=other_system, last_resort=last_resort)
    rows = _rows(text)
    for hunk in hunks:
        if not hunk.count or (not hunk.old and hunk.count == len(rows)):
            continue  # samo usunięcie nie ma linii do testu, a nowy plik nie ma bazy
        old = [f"{line}\n" for line in hunk.old]
        mutated = "".join([*rows[: hunk.start - 1], *old, *rows[hunk.start - 1 + hunk.count :]])
        last = hunk.start + hunk.count - 1
        span = f"{hunk.start}" if hunk.count == 1 else f"{hunk.start}–{last}"
        lines = changed_lines([hunk])
        # Komentarz i pusta linia nie biegną na żadnym systemie, więc nie decydują, czyj jest fragment.
        code = {line for line in lines if line <= len(rows) and rows[line - 1].strip() and not rows[line - 1].lstrip().startswith("#")}
        add(lines, hunk.start, f"zmiana linii {span} cofnięta do bazy", mutated, other_system=bool(code) and code <= other_lines, revert=True)
    # Sortowanie stabilne: w linii zostaje kolejność przejścia drzewa wszerz, z której wybiera ``selected``.
    return sorted(found.values(), key=lambda mutant: mutant.line)


def selected(path: str, text: str, hunks: Sequence[Hunk], platform: str = sys.platform) -> list[Mutant]:
    """Mutacje, które biegną w CI i liczy plan: każde cofnięcie fragmentu i ostatnia inna mutacja każdej linii.

    Predykat napisu biegnie tylko na linii bez innej mutacji: ``x in y`` → ``y.startswith(x)`` przy ``y`` będącym
    zbiorem albo słownikiem tylko rzuca ``AttributeError``, a wypierał ``bez członu`` i stały warunek (#486
    ``tools/lib/sciezki_w_kodzie.py:67``: przeżywa ``bez `node.func.attr in GLOBS` w `and` ``).
    """

    found = mutants(path, text, hunks, platform)
    last: dict[int, Mutant] = {}
    for mutant in found:
        if not mutant.revert and (mutant.line not in last or not mutant.last_resort or last[mutant.line].last_resort):
            last[mutant.line] = mutant
    return [mutant for mutant in found if mutant.revert or last[mutant.line] is mutant]


def fingerprint(mutant: Mutant, text: str) -> str:
    """Klucz mutacji pliku o treści ``text``, ten sam po przesunięciu jej linii: plik i linie, które mutacja usuwa i
    dodaje, bez numerów i wcięć. Ta sama zmiana tego samego kodu w dwóch miejscach pliku ma jeden klucz."""

    diff = difflib.unified_diff(text.splitlines(), mutant.source.splitlines(), n=0, lineterm="")
    edited = [line[0] + line[1:].strip() for line in itertools.islice(diff, 2, None) if not line.startswith("@@")]
    return hashlib.sha256("\n".join([mutant.path, *edited]).encode("utf-8")).hexdigest()[:12]


def exceptions(text: str, path: str) -> dict[int, Allowance]:
    """Wyjątki ``# mutacje-zmiany:`` pliku według linii kodu, której dotyczą; zła postać rzuca ``ValueError``.

    Wyjątkiem jest tylko komentarz: napis z tym tekstem (opis postaci wyjątku w docstringu) nim nie jest.
    """

    found: dict[int, Allowance] = {}
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        match = EXCEPTION.search(token.string) if token.type == tokenize.COMMENT else None
        if match is None:
            continue
        number = token.start[0]
        form = EXCEPTION_FORM.fullmatch(match["rest"])
        if form is None:
            raise ValueError(f"{path}:{number}: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`")
        try:
            until = datetime.date.fromisoformat(form["until"])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: zła data wyjątku {form['until']}") from error
        allowance = Allowance(form["reason"], until, form["who"])
        found[number] = allowance
        if not token.line[: token.start[1]].strip():
            found[number + 1] = allowance
    return found


@dataclass
class Coverage:
    lines: dict[str, dict[str, set[int]]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(set)))  # test → plik → linie
    files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # test → pliki, których kod wykonał
    shared: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))  # plik → linie wykonane dla wielu testów
    spawners: set[str] = field(default_factory=set)  # testy, które uruchomiły proces

    def covering(self, mutant: Mutant) -> list[str]:
        return sorted(test for test, files in self.lines.items() if files.get(mutant.path, set()) & mutant.lines)

    def touching(self, path: str, runners: frozenset[str]) -> list[str]:
        """Testy, które wykonały kod pliku ``path`` albo z plików testów ``runners`` uruchomiły proces, którego kodu
        zapis może nie widzieć."""

        executed = {test for test, files in self.files.items() if path in files}
        return sorted(executed | {test for test in self.spawners if test.split("::")[0] in runners})


def _coverage(
    tests: Sequence[str], lines: dict[str, frozenset[int]], timeout: float
) -> tuple[subprocess.CompletedProcess[str], Coverage]:
    """Uruchamia testy raz z pluginem ``pytest_pokrycie``; zwraca wynik i pokrycie zmienionych plików.

    Po ``timeout`` sekundach rzuca ``subprocess.TimeoutExpired``.
    """

    with tempfile.TemporaryDirectory(prefix="mutacje-zmiany-") as folder:
        settings = {"linie": {str(ROOT / path): sorted(numbers) for path, numbers in lines.items()}, "wynik": folder}
        # ``sitecustomize`` włącza zapis w każdym procesie Pythona, który test uruchamia z tym ``PYTHONPATH``.
        site = Path(folder) / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(pokrycie_procesu.SITECUSTOMIZE, encoding="utf-8")
        tools = [str(ROOT / "tools" / folder) for folder in ("lib", ".")]
        python_path = os.pathsep.join([str(site), *tools, str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])
        inherited = {name: value for name, value in os.environ.items() if name != pokrycie_procesu.TEST}
        env = {
            **inherited,
            "PYTEST_XDIST_AUTO_NUM_WORKERS": os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", str(WORKERS)),
            "PYTHONPATH": python_path.rstrip(os.pathsep),
            "POKRYCIE_LINII": json.dumps(settings),
        }
        command = [sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "pytest_pokrycie", "-p", "no:cacheprovider", *tests]
        done = potomne.run(command, cwd=ROOT, env=env, timeout=timeout)
        coverage = Coverage()

        def relative(absolute: str) -> str:
            return Path(absolute).relative_to(ROOT).as_posix()

        for part in sorted(Path(folder).glob("*.json")):
            recorded = json.loads(part.read_text(encoding="utf-8"))
            for test, files in recorded["linie"].items():
                for absolute, numbers in files.items():
                    coverage.lines[test][relative(absolute)].update(numbers)
            for test, paths in recorded["pliki"].items():
                coverage.files[test].update(relative(path) for path in paths)
            for absolute, numbers in recorded["wspolne"].items():
                coverage.shared[relative(absolute)].update(numbers)
            coverage.spawners.update(recorded["procesy"])
    return done, coverage


def _command(tests: Sequence[str], workers: int = 0) -> tuple[str, ...]:
    if sum(len(test) + 1 for test in tests) > COMMAND_LIMIT:
        tests = sorted({test.split("::")[0] for test in tests})
    return ("-m", "pytest", "-q", "-x", "-n", str(workers), "-p", "no:cacheprovider", *tests)


def _allowance(allowed: Mapping[int, Allowance], mutant: Mutant, today: datetime.date) -> Allowance | None:
    """Ważny wyjątek z linii mutacji; cofnięcie fragmentu ma linię jego początku."""

    allowance = allowed.get(mutant.line)
    return allowance if allowance is not None and allowance.until >= today else None


def _part(text: str) -> Czesc:
    try:
        return Czesc.z_tekstu(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"część {error}") from None


def main(argv: list[str] | None = None, *, gate: mutacje.Gate = mutacje.static_gate) -> int:
    """Kod wyjścia narzędzia; ``gate`` to brama typów przeżytych mutacji (``mutacje.type_gate``)."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", default=BASE, help=f"Gałąź, od której liczy się zmiana (domyślnie {BASE}).")
    parser.add_argument("--rownolegle", type=int, default=WORKERS, help="Ile mutacji biegnie naraz, każda w swojej kopii.")
    parser.add_argument("--limit-s", type=float, default=MUTATION_LIMIT_S, help="Limit czasu testów jednej mutacji w sekundach.")
    parser.add_argument(
        "--limit-czesci-s", type=float, default=PART_LIMIT_S, help=f"Limit czasu całej części w sekundach (domyślnie {PART_LIMIT_S})."
    )
    parser.add_argument(
        "--do", default="", help="Tylko mutacje linii, które ostatni zmienił commit linii pierwszych rodziców zawarty w tym (zakres nocy z planu)."
    )
    parser.add_argument("--czesc", metavar="K/N", type=_part, default=Czesc(1, 1), help="Tylko K-ty z N kolejnych kawałków listy mutacji.")
    parser.add_argument("--zapis", type=Path, help="Plik JSON z ostatnią linią i nazwami przeżytych mutacji (artefakt CI).")
    ciezkie_ci.argument(parser)
    args = parser.parse_args(argv)
    if refusal := ciezkie_ci.refusal({"change-mutations"}, args.odtwarzam, root=ROOT):
        print(refusal)
        return 2
    survived: list[tuple[Mutant, str]] = []
    unchecked: list[tuple[Mutant, str]] = []
    code, result = _mutate(args, survived, unchecked, gate)
    print(result)
    if args.zapis is not None:
        args.zapis.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "czesc": str(args.czesc),
            "kod": code,
            "wynik": result,
            "przezyte": [entry(mutant, text) for mutant, text in survived],
            "bez_werdyktu": [entry(mutant, text) for mutant, text in unchecked],
        }
        args.zapis.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return code


def _name(mutant: Mutant) -> str:
    return f"{mutant.path}:{mutant.line} {mutant.description}"


def entry(mutant: Mutant, text: str) -> dict[str, object]:
    """Przeżyta albo bez werdyktu mutacja pliku o treści ``text`` w zapisie ``--zapis``, który czyta ``tools/mutacje_nocne.py``."""

    return {"plik": mutant.path, "linia": mutant.line, "opis": mutant.description, "linie": sorted(mutant.lines), "klucz": fingerprint(mutant, text)}


def _last_changes(every: Sequence[Mutant], root: Path) -> list[frozenset[str]]:
    """Commity linii pierwszych rodziców, które ostatnie zmieniły linie każdej mutacji z ``every`` w checkoucie
    (``git blame --first-parent``: zmianę z gałęzi PR-u dostaje jego commit scalenia, a linię niezacommitowaną zera).
    Wiersze blame dzieli tylko koniec linii gita (``_rows``): linia z U+2028 albo form feed to dalej jeden wiersz."""

    blamed = {
        path: [row.split(maxsplit=1)[0].lstrip("^") for row in _rows(repo.git(root, "blame", "--first-parent", "-l", "-s", "--", path, timeout=None))]
        for path in dict.fromkeys(mutant.path for mutant in every)
    }
    return [frozenset(blamed[mutant.path][line - 1] for line in mutant.lines) for mutant in every]


def tests_of(repository: wplyw_zmiany.Repository, paths: Iterable[str]) -> dict[str, list[str]]:
    """Testy dotknięte każdym plikiem z ``paths``: tylko spośród nich biegną testy mutacji tego pliku."""

    return {path: list(repository.impact(frozenset({path})).tests) for path in paths}


@dataclass(frozen=True)
class ZakresMutacji:
    """Mutacje zmienionych linii ``src/`` i ``tools/`` od bazy do checkoutu ``root``, w kolejności części: po plikach,
    w pliku po liniach.

    Jedyne źródło listy mutacji planu nocy i części (ADR 0021): plan pyta o koniec zakresu nocy, liczbę części i
    mutacje każdej z nich, a część o swoje mutacje, więc obie dostają tę samą listę, bo składa ją tylko ta klasa.
    """

    root: Path
    baza: str  # wspólny przodek HEAD i podanej bazy: od niego liczą plan i część
    teksty: Mapping[str, str]  # plik zmiany → jego treść w checkoucie
    fragmenty: Mapping[str, Sequence[Hunk]]
    mutanty: tuple[Mutant, ...]  # ``selected`` każdego pliku zmiany, po ``do`` tylko z zakresu do commitu
    wyjatki: Mapping[str, Mapping[int, Allowance]]  # ``exceptions`` każdego pliku; puste przy złym wyjątku
    zly_wyjatek: str | None  # pierwszy wyjątek w złej postaci: część kończy się wtedy kodem 2
    niesprawdzone: tuple[str, ...]  # pliki, które commit zmienia, a ``tools/na_scalonych_pr.py`` podmienił (``overlay``)

    @classmethod
    def od(cls, baza: str, root: Path) -> ZakresMutacji:
        """Zakres od wspólnego przodka HEAD i ``baza``: zmiana bez plików podmienionych przez ``overlay``, mutacje
        ``selected`` i wyjątki. Nieznana baza rzuca ``subprocess.CalledProcessError``."""

        fork = repo.merge_base(root, "HEAD", baza)
        replaced, unseen = _overlay(fork, root)
        hunks = {path: found for path, found in _changes(fork, root).items() if path not in replaced}
        texts = {path: (root / path).read_text(encoding="utf-8") for path in hunks}
        every = tuple(mutant for path, text in texts.items() for mutant in selected(path, text, hunks[path]))
        try:
            allowed = {path: exceptions(text, path) for path, text in texts.items()}
        except ValueError as error:
            return cls(root, fork, texts, hunks, every, {}, str(error), unseen)
        return cls(root, fork, texts, hunks, every, allowed, None, unseen)

    def do(self, commit: str) -> ZakresMutacji:
        """Tylko mutacje, z których linii co najmniej jedną ostatni zmienił (``git blame --first-parent``) commit, który
        ``commit`` zawiera na linii pierwszych rodziców: zakres nocy do ``commit``. Mutacje linii zmienionych później
        dostaje następna noc, której bazą jest ``commit``."""

        contained = set(repo.git(self.root, "rev-list", "--first-parent", commit).split())
        commits = _last_changes(self.mutanty, self.root)
        return replace(self, mutanty=tuple(mutant for mutant, last in zip(self.mutanty, commits, strict=True) if last & contained))

    def najdalszy_koniec(self, limit: int) -> str:
        """Commit, do którego noc mutuje zmiany: HEAD, gdy mutacji jest najwyżej ``limit``, a inaczej najdalszy commit
        linii pierwszych rodziców od bazy, do którego ``do`` zostawia ich najwyżej ``limit``, ale co najmniej pierwszy
        commit z mutacjami, także gdy sam ma ich więcej."""

        if len(self.mutanty) <= limit:
            return repo.git(self.root, "rev-parse", "HEAD").strip()
        line = repo.git(self.root, "rev-list", "--first-parent", "--reverse", f"{self.baza}..HEAD").split()
        position = {commit: number for number, commit in enumerate(line)}
        # Mutacja wchodzi do zakresu z najwcześniejszym commitem, który zmienił którąś jej linię (jak w ``do``), a commit
        # spoza linii od bazy (sprzed niej) każdy zakres już zawiera, więc liczy się od pierwszego commitu.
        from_commit = Counter(min(position.get(commit, 0) for commit in commits) for commits in _last_changes(self.mutanty, self.root))
        total = 0
        for number in range(len(line)):
            if total and total + from_commit[number] > limit:
                return line[number - 1]
            total += from_commit[number]
        return line[-1]

    @property
    def liczba_mutacji(self) -> int:
        """Mutacje, które zgłoszą części: przy złym wyjątku co najmniej jedna, bo część zgłasza go porażką, a bez części
        noc byłaby zielona i przesunęła bazę za niego."""

        return max(len(self.mutanty), 1) if self.zly_wyjatek is not None else len(self.mutanty)

    def liczba_czesci(self, na_czesc: int) -> int:
        return math.ceil(self.liczba_mutacji / na_czesc)

    def czesc(self, czesc: Czesc) -> Sequence[Mutant]:
        """Mutacje części: jej kolejny kawałek listy, każda mutacja w jednej części."""

        return czesc.kawalek(self.mutanty)


def _mutate(
    args: argparse.Namespace, survived: list[tuple[Mutant, str]], unchecked: list[tuple[Mutant, str]], gate: mutacje.Gate
) -> tuple[int, str]:
    """Kod wyjścia i ostatnia linia; przeżyte mutacje z treścią ich pliku przed mutacją dopisuje do ``survived``, a mutacje
    bez werdyktu po limicie czasu części do ``unchecked``."""

    deadline = time.monotonic() + args.limit_czesci_s
    out_of_time = f"MUTACJE ZMIANY FAIL | limit czasu części {args.limit_czesci_s:g} s minął"
    czesc: Czesc = args.czesc
    try:
        zakres = ZakresMutacji.od(args.baza, ROOT)
    except subprocess.CalledProcessError:
        return 2, f"MUTACJE ZMIANY FAIL | nieznana baza {args.baza}"
    for path in zakres.niesprawdzone:
        print(f"NIESPRAWDZONA: {path} → commit go zmienia, a tools/na_scalonych_pr.py podstawił w jego miejscu narzędzie z checkoutu")
    if zakres.zly_wyjatek is not None:
        return 2, f"MUTACJE ZMIANY FAIL | {zakres.zly_wyjatek}"
    if args.do:
        zakres = zakres.do(args.do)
    texts, hunks, allowed = zakres.teksty, zakres.fragmenty, zakres.wyjatki
    found = zakres.czesc(czesc)
    if not found:
        where = f" w części {czesc}" if zakres.mutanty else ""
        return 0, f"{OK} | brak mutacji zmienionych linii src/ i tools/ od {args.baza}{where}"
    paths = {mutant.path for mutant in found}
    repository = wplyw_zmiany.Repository.scan(ROOT)
    by_file = tests_of(repository, paths)
    tests = sorted({test for chosen in by_file.values() for test in chosen})
    part = f" (część {czesc} z {len(zakres.mutanty)})" if czesc.n > 1 else ""
    print(f"Mutacje: {len(found)}{part} w {len(paths)} plikach src/ i tools/ od {args.baza}. Testy dotknięte zmianą: {len(tests)}.", flush=True)
    near = {path: repository.reaching(path) for path in paths}
    clock = [time.monotonic()]
    coverage = Coverage()
    if tests:
        try:
            done, coverage = _coverage(tests, {path: changed_lines(hunks[path]) for path in paths}, deadline - time.monotonic())
        except subprocess.TimeoutExpired:
            return 2, f"{out_of_time} w pokryciu, przed werdyktem {len(found)} mutacji"
        if done.returncode != 0:
            print("\n".join((done.stdout + done.stderr).rstrip().splitlines()[-30:]))
            return 2, "MUTACJE ZMIANY FAIL | testy dotknięte zmianą padają bez mutacji, więc mutacje niczego nie dowiodą"
        print(f"Pokrycie: {len(coverage.lines)} testów wykonało zmienione linie, {len(coverage.spawners)} uruchomiło proces.", flush=True)
    today = datetime.datetime.now(datetime.UTC).date()
    narrow: list[tuple[Mutant, mutacje.Mutation, list[list[str]]]] = []  # i testy dalszych przebiegów, gdy pierwszy przeżyje
    # Mutacje, które przeżyły testy, z werdyktem, jego linią i dopiskiem przebiegu; sprawdza je jeszcze brama typów.
    passed: list[tuple[Mutant, mutacje.Mutation, mutacje.Verdict, str, str]] = []
    excused = other_system = 0
    for mutant in found:
        name = _name(mutant)
        allowance = _allowance(allowed[mutant.path], mutant, today)
        if allowance is not None:
            excused += 1
            print(f"WYJĄTEK: {name} ({allowance.reason}, do {allowance.until}, zgoda {allowance.who})")
            continue
        if mutant.other_system:
            other_system += 1
            print(f"POMINIĘTA: {name} → kod innego systemu niż {sys.platform}")
            continue
        edit = mutacje.Edit(Path(mutant.path), texts[mutant.path], mutant.source)
        if not by_file[mutant.path]:
            passed.append((mutant, mutacje.Mutation(name, (edit,), ()), mutacje.Verdict.SURVIVED, f"żaden test nie zależy od {mutant.path}", ""))
            continue
        # Kod, którego wynik dostają też testy, które go nie wykonały (import, fixture szersza niż test, ``@cache``),
        # sprawdzają wszystkie testy pliku; inny kod testy, które wykonały jakikolwiek kod jego pliku. Taki kod czytają
        # zwykle funkcje jego pliku, więc ich testy biegną przed tysiącami testów pliku.
        shared = mutant.shared_state or bool(mutant.lines & coverage.shared.get(mutant.path, set()))
        candidates = set(by_file[mutant.path])
        touching = [test for test in coverage.touching(mutant.path, near[mutant.path]) if test.split("::")[0] in candidates]
        covering = coverage.covering(mutant)
        steps = [covering, touching, by_file[mutant.path]] if shared else [covering, touching or by_file[mutant.path]]
        first, *later = [list(tests) for tests in dict.fromkeys(map(tuple, steps)) if tests]
        narrow.append((mutant, mutacje.Mutation(name, (edit,), _command(first)), later))
    clock.append(time.monotonic())
    # Pokrycie tylko przyspiesza: mutacja, która przeżyła testy swoich linii, biegnie z coraz większym zbiorem testów.
    # Przebieg przed ostatnim biegnie po kilka mutacji naraz jak pierwszy. Ostatni ma testy pliku, często tysiące, a
    # takich mutacji jest kilka, więc biegną po jednej, każda z workerami xdist.
    wide: list[tuple[Mutant, mutacje.Mutation]] = []
    middle = 0
    queued, label = narrow, ""
    while queued:
        verdicts = mutacje.verdicts([m for _, m, _ in queued], workers=args.rownolegle, limit_s=args.limit_s, deadline=deadline)
        further: list[tuple[Mutant, mutacje.Mutation, list[list[str]]]] = []
        for (mutant, mutation, remaining), (verdict, shown) in zip(queued, verdicts, strict=True):
            # ZAWIESZENIE (pytest-timeout) czerwieni CI, więc kończy mutację jak WYKRYTA, bez szerszych testów.
            caught, last = mutacje.in_ci(verdict, shown)
            if verdict == mutacje.Verdict.NO_VERDICT:
                unchecked.append((mutant, texts[mutant.path]))
            elif not caught and not remaining:
                passed.append((mutant, mutation, verdict, shown, label))
                continue
            if caught or verdict == mutacje.Verdict.NO_VERDICT or not remaining:
                print(f"{verdict}: {mutation.name} → {last}{label}", flush=True)
            elif remaining[1:]:
                further.append((mutant, replace(mutation, command=_command(remaining[0])), remaining[1:]))
            else:
                wide.append((mutant, replace(mutation, command=_command(remaining[0], args.rownolegle))))
        middle += len(further)
        queued, label = further, " (testy kodu pliku)"
    clock.append(time.monotonic())
    for (mutant, mutation), (verdict, shown) in zip(wide, mutacje.verdicts([m for _, m in wide], workers=1, limit_s=args.limit_s, deadline=deadline), strict=True):
        caught, last = mutacje.in_ci(verdict, shown)
        if not caught and verdict != mutacje.Verdict.NO_VERDICT:
            passed.append((mutant, mutation, verdict, shown, " (testy pliku)"))
            continue
        if verdict == mutacje.Verdict.NO_VERDICT:
            unchecked.append((mutant, texts[mutant.path]))
        print(f"{verdict}: {mutation.name} → {last} (testy pliku)", flush=True)
    clock.append(time.monotonic())
    # Cofnięcie do bazy przywraca kod, który przeszedł bramę, więc jej błąd mówi tylko o niezgodności z resztą zmiany.
    checked = [(mutation, (verdict, shown)) for mutant, mutation, verdict, shown, _ in passed if not mutant.revert]
    gated = iter(
        mutacje.type_gate(
            [mutation for mutation, _ in checked], [found for _, found in checked], workers=args.rownolegle, limit_s=args.limit_s, deadline=deadline, gate=gate
        )
    )
    for mutant, mutation, tests_verdict, tests_shown, label in passed:
        verdict, shown = (tests_verdict, tests_shown) if mutant.revert else next(gated)
        caught, last = mutacje.in_ci(verdict, shown)
        if verdict == mutacje.Verdict.NO_VERDICT:
            unchecked.append((mutant, texts[mutant.path]))
        elif not caught:
            survived.append((mutant, texts[mutant.path]))
        print(f"{verdict}: {mutation.name} → {last}{label}", flush=True)
    clock.append(time.monotonic())
    uncovered = sum(not later for _, _, later in narrow)
    coverage_s, narrow_s, wide_s, gate_s = (later - earlier for earlier, later in itertools.pairwise(clock))
    print(
        f"CZAS | pokrycie {coverage_s:.0f} s | testy linii {narrow_s:.0f} s ({len(narrow)} mutacji, w tym {uncovered} bez drugiego"
        f" i {middle} z testami kodu pliku) | testy pliku {wide_s:.0f} s ({len(wide)} mutacji)"
        f" | brama typów {gate_s:.0f} s ({len(checked)} mutacji)",
        flush=True,
    )
    summary = f"mutacje={len(found)} | wyjątki={excused} | innego systemu={other_system}"
    if unchecked:
        return 3, f"{out_of_time} przed werdyktem {len(unchecked)} mutacji | przeżyło {len(survived)} | {summary}"
    if survived:
        return 1, f"{SURVIVED} {len(survived)} | {summary}"
    return 0, f"{OK} | {summary}"


if __name__ == "__main__":
    raise SystemExit(main())
