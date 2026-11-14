"""Struktura testów: moduły niczego nie eksportują, narzędzia na ``sys.path`` kładzie tylko ``conftest.py``, a test
czeka na stan przez ``wait_for`` i mierzy czas bez stałej liczby sekund.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from itertools import pairwise
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import sysconfig

import pytest

from rozliczenia import tool_files
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.centrum.keyed_box import REPORT_KEY_FILE
from rozliczenia.centrum.outbox import QUEUE_THREAD
from rozliczenia.centrum.runs import RUN_THREAD_PREFIX

from tests.fixtures.skladnia import dotted, drzewo, imports, pamiec_drzew, wezly
from tests.fixtures.znane_luki import (
    assert_znane_luki,
    platformy_mypy_ci,
    ruff,
    ruff_i_mypy,
    wymaga_ruff,
    wymaga_ruff_i_mypy,
    zapisz,
)

TESTS = Path(__file__).resolve().parent
# Atrapy wspólne z testami żyją poza tests/ (granica N13d), ale reguły czekania i limitów czasu obejmują je jak testy.
ATRAPY = TESTS.parent / "tools" / "lib" / "atrapy"
CLOCKS = frozenset({"time.monotonic", "time.perf_counter"})
TIME_READINGS = CLOCKS | {
    "time.time",
    "time.monotonic_ns",
    "time.perf_counter_ns",
    "time.time_ns",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
}
SLEEPS = frozenset({"time.sleep", "asyncio.sleep"})
# Jedyne czekanie na stan w testach: pętla z terminem, która śpi między pytaniami.
WAITING = "fixtures/potomne.py::wait_for"
SIMULATED_TIME = {
    "test_centrum_przygotowanie.py::test_czas_czekania_na_decyzje_nie_wlicza_sie_do_czasu_ani_metryk": (
        "tata myśli 1,5 s nad Decyzją, a test mierzy zegarem testu, że ten czas nie wlicza się do metryk (f17b7fe)"
    ),
    "test_opiekun_ponownego_startu.py::test_skrot_klikniety_w_trakcie_ponownego_startu_nie_cofa_nowej_wersji_ktora_dziala": (
        "test gra skrót, który trzyma port przez 3 s w trakcie startu nowej wersji"
    ),
}


@pytest.fixture(autouse=True, scope="module")
def drzewa_raz_na_modul() -> Iterator[None]:
    with pamiec_drzew():
        yield


def test_moduly_testow_importuja_pomocniki_tylko_z_fixtures() -> None:
    imports = {
        f"{path.name}: {node.module}"
        for path in sorted(TESTS.rglob("*.py"))
        for node in wezly(drzewo(path))
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("tests.")
        and not node.module.startswith("tests.fixtures")
    }

    assert imports == set(), "przenieś pomocnik do tests/fixtures i importuj go stamtąd; moduł testu niczego nie eksportuje"


CONFTEST = TESTS / "conftest.py"
# Ostatnia część nazwy wywołania (z każdym odbiorcą: ``monkeypatch.``, ``importlib.util.``, ``util.``, i bez niego), miejsce
# argumentu ścieżki i jego nazwa.
PREPEND = ("syspath_prepend", 0, "path")
LOAD = ("spec_from_file_location", 1, "location")
# Katalogi, które conftest kładzie na ``sys.path``, względem ``tools``.
ON_PATH = frozenset({(), ("lib",), ("ci",)})


def _tools_on_path(tree: ast.Module) -> list[int]:
    """Linie wstawek ścieżki z częścią ``tools`` przez ``syspath_prepend`` i wczytań pliku z ``tools``, ``tools/lib``
    albo ``tools/ci``: ``tests/conftest.py`` już kładzie te katalogi na ``sys.path`` każdego testu, więc druga wstawka w
    module testu albo fixture tylko to powtarza, fixture, który przez nią importuje narzędzie, kusi, żeby je
    re-eksportować, a moduł wczytany z pliku bez wpisu w ``sys.modules`` jest drugą kopią narzędzia, w której dataclass
    nie działa (K2 F15, 7 testów do 9.11.2026).

    Każde użycie ``sys.path`` w ``tests/`` (``sys.path.insert``, ``sys.path[:0] = …``, ``from sys import path``)
    odrzuca ruff ``TID251`` z ``tests/ruff.toml``, a to sprawdzenie łapie, na poziomie modułu i w funkcji:

    - wywołanie, którego nazwa kończy się na ``syspath_prepend`` (``monkeypatch.``, inna nazwa fixture), ze ścieżką
      pierwszym argumentem albo ``path=``;
    - wywołanie, którego nazwa kończy się na ``spec_from_file_location`` (``importlib.util.``, ``util.`` po ``from
      importlib import util``, sama nazwa), z plikiem ``.py`` drugim argumentem albo ``location=``.

    Ścieżkę czyta ze stałych napisów (``ROOT / "tools" / "lib"``, ``".../tools/ci"``, ``"C:\\repo\\tools"``), z nazw, które
    moduł przypisuje na swoim poziomie (``TOOLS = ROOT / "tools"`` albo ``TOOLS: Final = …``, potem ``TOOLS / "lib"``), i
    z argumentów pozycyjnych wywołań (``str(…)``).
    Katalog ``scripts`` skilla, plik z ``tools/hooks`` i wstawka w napisie kodu podprocesu przechodzą, bo conftest ich
    nie kładzie, a podproces nie ma conftest. Postacie, których nie łapie ani ruff, ani to sprawdzenie, są próbkami w
    ``ZNANE_LUKI_SYS_PATH``."""

    assigned = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    } | {
        node.target.id: node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None
    }

    def texts(node: ast.AST, seen: frozenset[str]) -> Iterator[str]:
        for part in ast.walk(node):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part.value
            elif isinstance(part, ast.Name) and part.id in assigned and part.id not in seen:
                yield from texts(assigned[part.id], seen | {part.id})

    def parts(node: ast.AST, seen: frozenset[str]) -> list[str]:
        """Części ścieżki w kolejności zapisu: ze stałych napisów, ``/`` między nimi, nazw modułu i argumentów wywołań."""

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return list(PureWindowsPath(node.value).parts)
        if isinstance(node, ast.Name) and node.id in assigned and node.id not in seen:
            return parts(assigned[node.id], seen | {node.id})
        if isinstance(node, ast.BinOp):
            return parts(node.left, seen) + parts(node.right, seen)
        if isinstance(node, ast.Call):
            return [part for argument in node.args for part in parts(argument, seen)]
        return []

    def a_tool(path: list[str]) -> bool:
        return any(part == "tools" and tuple(path[index + 1 : -1]) in ON_PATH for index, part in enumerate(path[:-1])) and path[-1].endswith(".py")

    def called(node: ast.Call) -> str:
        return node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""

    def path_of(node: ast.Call, call: tuple[str, int, str]) -> ast.expr | None:
        name, position, keyword = call
        if called(node) != name:
            return None
        if len(node.args) > position:
            return node.args[position]
        return next((argument.value for argument in node.keywords if argument.arg == keyword), None)

    def has_tools(node: ast.AST) -> bool:
        return any("tools" in PureWindowsPath(text).parts for text in texts(node, frozenset()))

    calls = [node for node in wezly(tree) if isinstance(node, ast.Call)]
    prepends = [node.lineno for node in calls if (path := path_of(node, PREPEND)) is not None and has_tools(path)]
    loads = [node.lineno for node in calls if (path := path_of(node, LOAD)) is not None and a_tool(parts(path, frozenset()))]
    return sorted([*prepends, *loads])


def test_tylko_conftest_kladzie_narzedzia_na_sys_path_testow() -> None:
    found = [
        f"{path.relative_to(TESTS.parent).as_posix()}:{line}"
        for path in sorted(TESTS.rglob("*.py"))
        if path != CONFTEST
        for line in _tools_on_path(drzewo(path))
    ]

    assert found == [], "\n".join(
        [
            *found,
            "tests/conftest.py kładzie tools, tools/lib i tools/ci na sys.path każdego testu: usuń wstawkę i importuj "
            "narzędzie wprost z jego modułu (import potomne), nie przez fixture, który je re-eksportuje.",
        ]
    )


# Każda postać wstawki katalogu narzędzi, którą zna sprawdzenie (``sys.path`` odrzuca ruff ``TID251``, z próbkami w
# ``tests/test_zakazy_ruff.py``).
TOOLS_ON_PATH = {
    "monkeypatch-z-katalogu-windows": 'def f(monkeypatch) -> None:\n    monkeypatch.syspath_prepend("C:\\\\repo\\\\tools")',
    "monkeypatch-z-nazwy-przez-nazwe": 'REPO = ROOT\nTOOLS = REPO / "tools"\nLIB = TOOLS / "lib"\ndef f(monkeypatch) -> None:\n    monkeypatch.syspath_prepend(str(LIB))',
    "monkeypatch-z-adnotacja": 'TOOLS: Final = ROOT / "tools"\ndef f(monkeypatch) -> None:\n    monkeypatch.syspath_prepend(str(TOOLS / "lib"))',
    "monkeypatch": 'TOOLS = ROOT / "tools"\ndef f(monkeypatch) -> None:\n    monkeypatch.syspath_prepend(str(TOOLS))',
    "plik-narzedzia": 'import importlib.util\nSCRIPT = ROOT / "tools" / "uruchom_proces.py"\nimportlib.util.spec_from_file_location("x", SCRIPT)',
    "plik-biblioteki": 'from importlib.util import spec_from_file_location\nTOOLS = ROOT / "tools"\nspec_from_file_location("x", TOOLS / "lib" / "kroki_skilli.py")',
    "plik-ci-napisem": 'import importlib.util\nimportlib.util.spec_from_file_location("x", Path(__file__).parents[1] / "tools/ci/export_openapi.py")',
    "plik-w-wywolaniu": 'import importlib.util\nimportlib.util.spec_from_file_location("x", str(ROOT / "tools" / "mutacje.py"))',
    "plik-nazwanymi-argumentami": 'import importlib.util\nimportlib.util.spec_from_file_location(name="x", location=ROOT / "tools" / "mutacje.py")',
    "plik-przez-alias-modulu": 'from importlib import util\nutil.spec_from_file_location("x", ROOT / "tools" / "mutacje.py")',
    "monkeypatch-nazwanym-argumentem": 'def f(monkeypatch) -> None:\n    monkeypatch.syspath_prepend(path=str(ROOT / "tools"))',
    "monkeypatch-inna-nazwa": 'def f(mp) -> None:\n    mp.syspath_prepend(str(ROOT / "tools" / "lib"))',
}


@pytest.mark.parametrize("code", TOOLS_ON_PATH.values(), ids=TOOLS_ON_PATH.keys())
def test_sprawdzenie_sys_path_lapie_kazda_wyliczona_postac_wstawki_narzedzi(code: str) -> None:
    assert len(_tools_on_path(ast.parse(code))) == 1


def test_sprawdzenie_sys_path_przepuszcza_skrypty_skilli_i_kod_podprocesu() -> None:
    code = (
        'SKILL = ROOT / ".agents" / "skills" / "verify-x"\n'
        'monkeypatch.syspath_prepend(str(SKILL / "scripts"))\n'
        'monkeypatch.syspath_prepend("my_tools")\n'
        'KOD = "import sys\\nsys.path.insert(0, \'tools\')\\nimport mutacje\\n"\n'
        'LISTA = [str(ROOT / "tools")]\n'
        'HOOK = ROOT / "tools" / "hooks" / "czekanie.py"\n'
        'importlib.util.spec_from_file_location("czekanie", HOOK)\n'
        'importlib.util.spec_from_file_location("x", ROOT / ".agents" / "skills" / "verify-x" / "scripts" / "x.py")\n'
        'importlib.util.spec_from_file_location("x", ROOT / "tools" / "lib" / "atrapy" / "x.py")\n'
        'importlib.util.spec_from_file_location("lib", ROOT / "tools" / "lib")\n'
    )

    assert _tools_on_path(ast.parse(code)) == []


# Znane luki sprawdzenia sys.path (tests/fixtures/znane_luki.py): opis postaci → moduł testu, który kładzie katalog
# narzędzi na sys.path albo wczytuje narzędzie z pliku, a mimo to przechodzi przez ruff z konfiguracją tests/ i
# _tools_on_path.
ZNANE_LUKI_SYS_PATH = {
    "ścieżka z argumentu funkcji": """\
from pathlib import Path

import pytest


def wstaw(monkeypatch: pytest.MonkeyPatch, katalog: Path) -> None:
    monkeypatch.syspath_prepend(katalog)


def test_narzedzie(monkeypatch: pytest.MonkeyPatch) -> None:
    wstaw(monkeypatch, Path(__file__).resolve().parents[1] / "tools")
""",
    "ścieżka z sys.argv": """\
import sys

import pytest


def test_narzedzie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(sys.argv[1])
""",
    "ścieżka z atrybutu klasy": """\
from pathlib import Path

import pytest


class Repo:
    narzedzia = Path(__file__).resolve().parents[1] / "tools"


def test_narzedzie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(Repo.narzedzia)
""",
    "syspath_prepend wzięte do zmiennej": """\
from pathlib import Path

import pytest


def test_narzedzie(monkeypatch: pytest.MonkeyPatch) -> None:
    wstaw = monkeypatch.syspath_prepend
    wstaw(Path(__file__).resolve().parents[1] / "tools")
""",
    "spec_from_file_location pod aliasem funkcji": """\
from importlib.util import spec_from_file_location as wczytaj
from pathlib import Path

SPEC = wczytaj("mutacje", Path(__file__).resolve().parents[1] / "tools" / "mutacje.py")
""",
    "runpy.run_path": """\
from pathlib import Path
import runpy

MUTACJE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "mutacje.py"))
""",
    "SourceFileLoader": """\
from importlib.machinery import SourceFileLoader
from pathlib import Path

MUTACJE = SourceFileLoader("mutacje", str(Path(__file__).resolve().parents[1] / "tools" / "mutacje.py")).load_module()
""",
    "sys.path.insert z noqa": """\
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))  # noqa: TID251 - sonda
""",
    "site.addsitedir": """\
from pathlib import Path
import site

site.addsitedir(str(Path(__file__).resolve().parents[1] / "tools"))
""",
}


@wymaga_ruff
def test_znane_luki_sprawdzenia_sys_path_przechodza_przez_ruff_i_sprawdzenie(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_SYS_PATH, tmp_path)
    zgloszenia = ruff(pliki, sonda=TESTS / "test_sonda_luki.py")
    for opis, plik in pliki.items():
        zgloszenia[opis] += [f"_tools_on_path: linia {line}" for line in _tools_on_path(drzewo(plik))]

    assert_znane_luki(zgloszenia, "tests/test_struktura_testow.py (ZNANE_LUKI_SYS_PATH)")


@wymaga_ruff_i_mypy
def test_znane_luki_licza_mypy_na_kazdej_platformie_krokow_ci(tmp_path: Path) -> None:
    """Required CI liczy mypy z ``--platform`` każdego kroku zadania „Ruff, mypy”, więc próbka-kontrola z błędem typu
    w gałęzi ``sys.platform == platforma`` ma zgłoszenie tylko tej platformy, na każdym systemie, na którym biegnie test."""

    platformy = platformy_mypy_ci()
    assert {"linux", "win32"} <= set(platformy), platformy
    kontrole = {platforma: f'import sys\n\nif sys.platform == "{platforma}":\n    x: int = "a"\n' for platforma in platformy}

    zgloszenia = ruff_i_mypy(zapisz(kontrole, tmp_path), sonda=TESTS / "test_sonda_luki.py")

    assert {platforma: [z.partition(" ")[0] for z in lista] for platforma, lista in zgloszenia.items()} == {
        platforma: [f"mypy[{platforma}]"] for platforma in platformy
    }, zgloszenia
    assert all(lista[0].endswith("[assignment]") for lista in zgloszenia.values()), zgloszenia


# Pliki, w których nazwa pliku narzędzia albo stanu Centrum zostaje literałem, z powodem.
OWNED_NAMES_AS_LITERALS = {
    "test_opiekun_ponownego_startu.py": "test kontraktu nazw tool_files i scenariusze repozytorium Git opiekuna",
    "test_uszkodzone_wejscia.py": "test kontraktu miejsc plików stanu Centrum",
    "test_aktualizacja_narzedzia.py": "scenariusze repozytorium Git: historia, .gitignore i git status klonu taty",
    "test_przerwana_aktualizacja_narzedzia.py": "scenariusz repozytorium Git: plik taty, który nowa wersja przestaje śledzić",
    "fixtures/tool_clone.py": "pierwsza wersja repozytorium narzędzia w historii Git",
    "tools/lib/atrapy/pliki_taty.py": "kopia celowa świata taty: atrapy budują pliki taty niezależnie od src",
}
# Testy kontraktu: każda nazwa właściciela stoi w jednym z nich literałem.
CONTRACTS = ("test_opiekun_ponownego_startu.py", "test_uszkodzone_wejscia.py")
SRC = TESTS.parent / "src" / "rozliczenia"


def test_nazwy_plikow_narzedzia_i_stanu_centrum_biora_testy_od_wlasciciela() -> None:
    """Nazwę pliku narzędzia albo stanu Centrum test i atrapa biorą od właściciela, a literałem stoi ona tylko w plikach
    ``OWNED_NAMES_AS_LITERALS``: test kontraktu przypina ją raz, a zmiana nazwy w ``src`` nie zostawia testów na starym
    pliku.

    Nazwy wylicza ``_owned_names`` z ``src``, więc nowy plik stanu nie potrzebuje wpisu tutaj: nazwa każdej ścieżki z
    suffiksem w ``tool_files`` (Konfiguracja wykonawców, Wzorce, Ustawienia, pliki metryk) poza ``LOG_PATH`` i każda
    stała tekstowa bez ``{`` przypisana na poziomie modułu ``src/rozliczenia`` do nazwy kończącej się na ``_FILE``
    (``REPORT_KEY_FILE``, ``DAD_CASES_FILE``, ``NOTIFICATIONS_FILE``, ``CENTRUM_RUNS_FILE``…). Każda z nich musi też
    stać literałem w jednym z ``CONTRACTS``.

    Łapie stałą tekstową (także część f-stringu) równą nazwie albo ścieżkę, która się nią kończy po ``/`` albo ``\\``, w
    ``tests/**/*.py`` i ``tools/lib/atrapy/**/*.py``. Każdą inną postać i nazwę sprawdza tylko przegląd: nazwę w dłuższym
    zdaniu (tekst Komunikatu, który czyta tata, zostaje literałem jak w ``tests/expected``), nazwę sklejoną z części,
    foldery (``config``, ``logs``, ``kolejka``, ``uruchomienia``: słowa ogólne, także nazwy stron), nazwę dziennika
    Centrum (``LOG_PATH``: ``CentrumLog`` w teście jednostki dostaje dowolną ścieżkę), stałe spoza tej reguły nazw
    (``RUN_LOGS_DIRECTORY``, ``PROFILE_DIRECTORY``) i pliki okresu, które niosą token okresu.
    """

    names = _owned_names()
    found = sorted(
        f"{name}:{node.lineno}: {node.value!r}"
        for path, name in _scanned()
        if name not in OWNED_NAMES_AS_LITERALS
        for node in _owned_literals(path, names)
    )
    pinned = {owned for name in CONTRACTS for node in _owned_literals(TESTS / name, names) for owned in names if _ends_with(str(node.value), owned)}

    assert {tool_files.WORKER_TEMPLATE.name, WORKERS_FILE, REPORT_KEY_FILE} <= names, "_owned_names nie widzi już tool_files albo stałych *_FILE"
    assert found == [], "weź nazwę od właściciela (tool_files, ToolDirectory w tests/fixtures/centrum.py, stała modułu Centrum)"
    assert sorted(names - pinned) == [], "przypnij nazwę literałem w teście kontraktu z CONTRACTS"


def _owned_names() -> set[str]:
    """Nazwy plików, które znają właściciele w ``src``; regułę opisuje docstring strażnika."""

    names = {
        path.name
        for path in vars(tool_files).values()
        if isinstance(path, Path) and path.suffix and path != tool_files.LOG_PATH
    }
    for module in sorted(SRC.rglob("*.py")):
        for node in drzewo(module).body:
            target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
            value = getattr(node, "value", None)
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(target, ast.Name)
                and target.id.endswith("_FILE")
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and "{" not in value.value
            ):
                names.add(value.value)
    return names


def _owned_literals(path: Path, names: set[str]) -> Iterator[ast.Constant]:
    for node in wezly(drzewo(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(_ends_with(node.value, owned) for owned in names):
            yield node


def _ends_with(value: str, owned: str) -> bool:
    return value == owned or value.endswith((f"/{owned}", f"\\{owned}"))


def _scanned() -> list[tuple[Path, str]]:
    """Pliki testów i atrap z nazwą do list wyjątków: względem ``tests/`` dla testów, względem korzenia dla atrap."""
    return [(path, path.relative_to(TESTS).as_posix()) for path in sorted(TESTS.rglob("*.py"))] + [
        (path, _shown(path)) for path in sorted(ATRAPY.rglob("*.py"))
    ]


def _shown(path: Path) -> str:
    return path.relative_to(TESTS.parent).as_posix()


def test_reguly_czekania_i_limitow_czasu_czytaja_testy_i_atrapy() -> None:
    read = {name for _, name in _scanned()}

    assert {"test_struktura_testow.py", "fixtures/potomne.py", "tools/lib/atrapy/sluchacz_kolejki.py"} <= read


Definition = ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _is_sleep(call: ast.Call, names: dict[str, str]) -> bool:
    """``time.sleep`` i ``asyncio.sleep`` pod każdą nazwą z importu i czekanie na nowe ``threading.Event``, którego nikt nie ustawi."""

    function = call.func
    return dotted(function, names, "") in SLEEPS or (
        isinstance(function, ast.Attribute)
        and function.attr == "wait"
        and isinstance(function.value, ast.Call)
        and dotted(function.value.func, names, "") == "threading.Event"
    )


def _handed_over(definition: Definition, tree: ast.Module, parents: dict[ast.AST, ast.AST]) -> bool:
    """Test przekazuje podróbkę jako wartość, więc jej sen woła kod pod testem, a nie sam test.

    Funkcję test woła sam, gdy jej nazwa stoi tylko w ``f(...)``, klasę, gdy tylko w ``C(...).metoda``, a lambdę,
    gdy woła ją od razu albo przez nazwę, do której ją przypisał.
    """

    if isinstance(definition, ast.Lambda):
        parent = parents[definition]
        if isinstance(parent, ast.Call) and parent.func is definition:
            return False
        if not (isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name)):
            return True
        name = parent.targets[0].id
    else:
        name = definition.name
    for use in wezly(tree):
        if not (isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load)):
            continue
        call = parents[use]
        called = isinstance(call, ast.Call) and call.func is use
        if isinstance(definition, ast.ClassDef):
            called = called and isinstance(parents.get(call), ast.Attribute)
        if not called:
            return True
    return False


def _fixed_sleeps(tree: ast.Module) -> Iterator[tuple[ast.Call, str]]:
    """Sen poza podróbką, z nazwą funkcji, w której jest; pętla z własnym terminem też się liczy.

    Podróbka to lambda, funkcja albo klasa, którą test przekazuje dalej jako wartość: jej sen udaje czas pracy kodu pod
    testem. Znana granica: zdarzenie w zmiennej, którego nikt nie ustawia (``hold.wait(2)``), podróbka, którą test woła
    sam przez inną nazwę, i pętla z terminem bez snu przechodzą, bo odróżnienie ich wymaga analizy przepływu danych.
    """

    names = imports(tree)
    parents = {child: node for node in wezly(tree) for child in ast.iter_child_nodes(node)}
    for call in wezly(tree):
        if not (isinstance(call, ast.Call) and _is_sleep(call, names)):
            continue
        enclosing: list[ast.AST] = []
        node: ast.AST = call
        while node in parents:
            node = parents[node]
            enclosing.append(node)
        faked = any(isinstance(node, Definition) and _handed_over(node, tree, parents) for node in enclosing)
        if not faked:
            functions = [node for node in enclosing if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            yield call, functions[0].name if functions else "<moduł>"


def test_testy_czekaja_na_stan_a_nie_stala_liczbe_sekund() -> None:
    found, simulated = [], set()
    for path, name in _scanned():
        for call, function in _fixed_sleeps(drzewo(path)):
            if f"{name}::{function}" == WAITING:
                continue
            if f"{name}::{function}" in SIMULATED_TIME:
                simulated.add(f"{name}::{function}")
            else:
                found.append(f"{_shown(path)}:{call.lineno}: {ast.unparse(call)} czeka stałą liczbą sekund")
    found += [f"SIMULATED_TIME: {key} nie ma już snu, usuń wpis" for key in sorted(SIMULATED_TIME.keys() - simulated)]

    assert not found, "\n".join(
        [
            *found,
            "Czekaj na stan przez wait_for z tests/fixtures/potomne.py, także zamiast pętli z własnym terminem "
            "(brak zdarzenia: assert not wait_for(zdarzenie, s)); "
            "czas pracy podróbki śpi w funkcji, lambdzie albo klasie, którą test przekazuje kodowi pod testem, a czas "
            "symulowany w samym teście wpisz do SIMULATED_TIME z powodem.",
        ]
    )


TIME_NAME = re.compile(r"elapsed|duration|_m?s$")
CONSTANT_TIME_BOUNDS = {
    "test_aktualizacja_narzedzia.py::test_github_proszacy_o_logowanie_konczy_sie_od_razu_bez_pytania_a_klon_zostaje_bez_zmian"
    "::elapsed < 20": (
        "granica 20 s oddziela koniec od zawieszenia: pomocnik logowania, na którego narzędzie nie może czekać, śpi 60 s"
    ),
    "test_aktualizacja_narzedzia.py::test_pomocnik_gita_trzymajacy_jego_wyjscie_nie_wstrzymuje_aktualizacji::elapsed < 20": (
        "granica 20 s oddziela koniec od zawieszenia: pomocnik gita trzyma jego wyjście otwarte przez 60 s"
    ),
    "test_aktualnosc_narzedzia.py::test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu"
    "::time.monotonic() - started < 1.5": (
        "serwer nie odpowiada nigdy, więc bez limitu 0,3 s diagnoza czekałaby bez końca; granica to 5× ten limit"
    ),
    "test_centrum_launcher.py::test_obcy_program_ktory_milczy_nie_wstrzymuje_startu_dluzej_niz_limit_czekania_na_health"
    "::took < wait_s * 1.8": (
        "obcy program nie odpowiada nigdy, a granica poniżej dwóch skróconych limitów czekania na health (0,5 s) łapie "
        "Centrum, które czeka dwa razy dłużej albo bez końca"
    ),
    "test_centrum_powiadomienia.py::test_spozniona_odpowiedz_skrzynki_nie_wstrzymuje_powiadomien_a_jej_stan_i_tak_zostaje"
    "::took < wait_s * 1.8": (
        "skrzynka trzyma odpowiedź do końca testu, a granica poniżej dwóch skróconych limitów CHECK_WAIT_S (1 s) łapie "
        "Powiadomienia, które czekają dwa razy dłużej"
    ),
    "test_mutacje.py::test_polecenie_bez_wyniku_w_limicie_czasu_narzedzia_daje_przekroczony_czas::2 <= int(spent[1]) < 4": (
        "polecenie mutacji śpi 60 s, linia CZAS mierzy samo polecenie (bez startu narzędzia i kopii), a granica poniżej "
        "dwóch limitów --limit-s (2 s) łapie silnik, który kończy je dwa razy później"
    ),
    "test_weryfikacja_w_excelu.py::test_start_excela_bez_zgody_na_automatyzacje_konczy_sie_od_razu_nazwana_przyczyna"
    "::time.monotonic() - started < 10": (
        "granica 10 s to połowa limitu startu Excela (20 s), do którego launch czekałby, gdyby nie rozpoznał odmowy"
    ),
}


def _unpacked(target: ast.expr, value: ast.expr | None) -> Iterator[tuple[str, ast.expr | None]]:
    """Nazwa w celu przypisania i jej wartość: ``took, _ = a, b`` wiąże ``took`` z ``a``."""

    if isinstance(target, ast.Name):
        yield target.id, value
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        values = value.elts if isinstance(value, (ast.Tuple, ast.List)) else []
        paired = len(values) == len(target.elts) and not any(
            isinstance(item, ast.Starred) for item in [*values, *target.elts]
        )
        for index, item in enumerate(target.elts):
            yield from _unpacked(item.value if isinstance(item, ast.Starred) else item, values[index] if paired else None)
        return
    for name in ast.walk(target):
        if isinstance(name, ast.Name):
            yield name.id, None


def _bindings(tree: ast.Module) -> dict[str, list[ast.expr | None]]:
    """Każda wartość przypisana nazwie w module; ``None``, gdy nazwę wiąże coś innego niż przypisanie.

    ``took += x`` to ``took = took + x``: dla ``_constant`` nazwa zależy od siebie, więc nie jest stałą, a dla
    ``_measured`` niesie odczyt zegara z ``x``.
    """

    bound: dict[str, list[ast.expr | None]] = {}
    for node in wezly(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for bound_name, value in _unpacked(target, node.value):
                    bound.setdefault(bound_name, []).append(value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            itself = ast.Name(id=node.target.id, ctx=ast.Load())
            bound.setdefault(node.target.id, []).append(ast.BinOp(left=itself, op=node.op, right=node.value))
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and isinstance(node.target, ast.Name):
            bound.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension, ast.withitem)):
            loop_target = node.optional_vars if isinstance(node, ast.withitem) else node.target
            for name in ast.walk(loop_target) if loop_target is not None else ():
                if isinstance(name, ast.Name):
                    bound.setdefault(name.id, []).append(None)
        elif isinstance(node, ast.arg):
            bound.setdefault(node.arg, []).append(None)
    return bound


def _constant(expression: ast.expr, bound: dict[str, list[ast.expr | None]], seen: frozenset[str] = frozenset()) -> bool:
    """Liczba znana przed uruchomieniem: literał, działanie na literałach albo nazwa przypisana tylko takiej liczbie."""

    if isinstance(expression, ast.Constant):
        return isinstance(expression.value, (int, float)) and not isinstance(expression.value, bool)
    if isinstance(expression, ast.UnaryOp):
        return _constant(expression.operand, bound, seen)
    if isinstance(expression, ast.BinOp):
        return _constant(expression.left, bound, seen) and _constant(expression.right, bound, seen)
    if isinstance(expression, ast.Name) and expression.id not in seen and expression.id in bound:
        return all(
            value is not None and _constant(value, bound, seen | {expression.id}) for value in bound[expression.id]
        )
    return False


def _measured(
    expression: ast.expr, bound: dict[str, list[ast.expr | None]], names: dict[str, str], measured_names: set[str]
) -> bool:
    """Zmierzony czas: wyrażenie z nazwą czasu (``elapsed``, ``duration``, ``_ms``, ``_s``), z odczytem zegara
    albo z nazwą z ``measured_names`` (``_measured_names``)."""

    if _constant(expression, bound):
        return False
    for node in ast.walk(expression):
        if isinstance(node, ast.Call) and dotted(node.func, names, "") in TIME_READINGS:
            return True
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
        if name is not None and TIME_NAME.search(name) and not (isinstance(node, ast.Name) and _constant(node, bound)):
            return True
        if isinstance(node, ast.Name) and node.id in measured_names:
            return True
    return False


def _measured_names(bound: dict[str, list[ast.expr | None]], names: dict[str, str]) -> set[str]:
    """Nazwy, którym moduł przypisuje zmierzony czas (``took = time.monotonic() - started``), także przez inne nazwy.

    Najmniejszy punkt stały raz na moduł: przejście każdej ścieżki wiązań osobno rośnie wykładniczo z liczbą nazw
    wiązanych w module wiele razy (#1010: ``tests/test_wycena_efenix.py`` po #995 trwał 25 s).
    """

    measured: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, values in bound.items():
            if name not in measured and any(
                value is not None and _measured(value, bound, names, measured) for value in values
            ):
                measured.add(name)
                changed = True
    return measured


def _negated(compare: ast.Compare, statement: ast.Assert, parents: dict[ast.AST, ast.AST]) -> bool:
    """Porównanie pod nieparzystą liczbą ``not``: ``assert not elapsed >= 2`` to ``assert elapsed < 2``."""

    nots = 0
    node: ast.AST = compare
    while node is not statement:
        node = parents[node]
        nots += isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    return nots % 2 == 1


def _constant_time_bounds(tree: ast.Module) -> Iterator[tuple[ast.Compare, str]]:
    """Asercja, że zmierzony czas jest mniejszy od stałej liczby, z nazwą funkcji, w której jest.

    Znana granica, bo wymaga analizy przepływu danych albo znajomości bibliotek: stała, która przychodzi parametrem
    (``pytest.mark.parametrize``), z innego modułu, z atrybutu klasy albo z ``timedelta(...)``; nazwa, którą moduł
    gdzie indziej wiąże z czymś innym niż liczba; zmierzony czas w pomocniku z innego modułu; granica bez porównania
    w ``assert``: ``pytest.approx(..., abs=...)``, ``math.isclose(..., abs_tol=...)`` i ``if elapsed > 2:
    pytest.fail(...)``.
    """

    names = imports(tree)
    bound = _bindings(tree)
    measured_names = _measured_names(bound, names)
    parents = {child: node for node in wezly(tree) for child in ast.iter_child_nodes(node)}
    for statement in wezly(tree):
        if not isinstance(statement, ast.Assert):
            continue
        for compare in ast.walk(statement.test):
            if not isinstance(compare, ast.Compare):
                continue
            negated = _negated(compare, statement, parents)
            for operator, (left, right) in zip(compare.ops, pairwise([compare.left, *compare.comparators]), strict=True):
                if isinstance(operator, (ast.Lt, ast.LtE)):
                    measured, limit = left, right
                elif isinstance(operator, (ast.Gt, ast.GtE)):
                    measured, limit = right, left
                else:
                    continue
                if negated:
                    measured, limit = limit, measured
                if _measured(measured, bound, names, measured_names) and _constant(limit, bound):
                    node: ast.AST = statement
                    while node in parents and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        node = parents[node]
                    yield compare, node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<moduł>"
                    break


def test_zmierzony_czas_nie_jest_ograniczony_stala_liczba() -> None:
    found, excepted = [], set()
    for path, name in _scanned():
        for compare, function in _constant_time_bounds(drzewo(path)):
            key = f"{name}::{function}::{ast.unparse(compare)}"
            if key in CONSTANT_TIME_BOUNDS:
                excepted.add(key)
            else:
                found.append(f"{_shown(path)}:{compare.lineno}: {ast.unparse(compare)} ogranicza zmierzony czas stałą liczbą ({key})")
    found += [
        f"CONSTANT_TIME_BOUNDS: {key} nie ma już takiej asercji, usuń wpis"
        for key in sorted(CONSTANT_TIME_BOUNDS.keys() - excepted)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Na wolnym runnerze sama praca trwa dłużej niż stała. Daj kodowi pod testem podróbkę zegara "
            "(ManualClock z tests/fixtures/clock.py, parametr clock) i sprawdź czas równością; gdy kod mierzy "
            "prawdziwy czas, ogranicz go zegarem testu (time.perf_counter() przed i po); gdy podróbka trzyma "
            "odpowiedź, sprawdź stan (jeszcze nie odpowiedziała), a granicę końca kontra zawieszenia wpisz do "
            "CONSTANT_TIME_BOUNDS pod kluczem z nawiasu, z powodem.",
        ]
    )


@pytest.mark.parametrize(
    "module",
    [
        "import time\nstarted = time.monotonic()\ntook = time.monotonic() - started\nassert took < 2\n",
        "import time\nstarted = time.monotonic()\ntook = raw * 1\nraw = time.monotonic() - started\nassert took < 2\n",
    ],
    ids=["nazwa-z-odczytu-zegara", "nazwa-przez-inna-nazwe"],
)
def test_czas_przypisany_nazwie_bez_slowa_czasu_jest_zmierzonym_czasem(module: str) -> None:
    assert [ast.unparse(compare) for compare, _ in _constant_time_bounds(ast.parse(module))] == ["took < 2"]


@pytest.mark.parametrize(
    ("guard", "atrapa", "reported"),
    [
        (
            test_testy_czekaja_na_stan_a_nie_stala_liczbe_sekund,
            "import time\ntime.sleep(0.5)\n",
            "tools/lib/atrapy/naruszenie.py:2: time.sleep(0.5) czeka stałą liczbą sekund",
        ),
        (
            test_zmierzony_czas_nie_jest_ograniczony_stala_liczba,
            "import time\nstarted = time.monotonic()\nassert time.monotonic() - started < 2\n",
            "tools/lib/atrapy/naruszenie.py:3: time.monotonic() - started < 2 ogranicza zmierzony czas stałą liczbą",
        ),
    ],
    ids=["sen", "limit-czasu"],
)
def test_straznik_czekania_i_limitow_czasu_zglasza_naruszenie_w_atrapie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard: Callable[[], None], atrapa: str, reported: str
) -> None:
    """Naruszenie w atrapie obok pustego katalogu testów: strażnik je zgłasza, więc czyta atrapy, a nie tylko ``tests/``
    (przegląd #1170 r2, Drobne 1)."""

    atrapy = tmp_path / "tools" / "lib" / "atrapy"
    atrapy.mkdir(parents=True)
    (atrapy / "naruszenie.py").write_text(atrapa, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(sys.modules[__name__], "TESTS", tmp_path / "tests")
    monkeypatch.setattr(sys.modules[__name__], "ATRAPY", atrapy)

    with pytest.raises(AssertionError) as raised:
        guard()

    assert reported in str(raised.value)


SRC = TESTS.parent / "src"
THREAD_CONSTANT = re.compile(r"[A-Z_]+_THREAD(?:_PREFIX)?")
# Napisy równe nazwie wątku, które nie nazywają wątku, z funkcją (``<moduł>`` poza funkcją) i powodem.
NOT_THREADS = {
    "test_instrukcja_taty.py::<moduł>::aktualizacja-narzedzia": "funkcja Instrukcji taty o tej samej nazwie co wątek",
    "test_centrum_przygotowanie.py::test_dziennik_centrum_ma_poczatek_i_koniec_uruchomienia_z_wynikiem_bez_danych_klientow"
    "::uruchomienie-": "początek nazw wpisów dziennika Centrum o Uruchomieniu, nie wątku",
}


def _thread_names(tree: ast.Module) -> set[str]:
    """Nazwy wątków modułu ``src/``: wartości stałych modułu ``*_THREAD`` i ``*_THREAD_PREFIX`` oraz napisy ``name=`` w
    wywołaniu ``…Thread(...)`` i ``within(...)`` (``centrum/deadline.py``, który nazwą wątku nazywa swoją pracę)."""

    names = set()
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and THREAD_CONSTANT.fullmatch(target.id) and isinstance(value, ast.Constant):
            names.add(value.value)
    for call in wezly(tree):
        if isinstance(call, ast.Call) and (ast.unparse(call.func).endswith("Thread") or ast.unparse(call.func).split(".")[-1] == "within"):
            names |= {
                keyword.value.value
                for keyword in call.keywords
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
            }
    return {name for name in names if isinstance(name, str)}


def _texts(tree: ast.Module) -> Iterator[tuple[str, int, str]]:
    """Napisy modułu z nazwą funkcji, w której stoją, poza docstringami (napis jako całe wyrażenie-instrukcja) i
    kawałkami f-stringów."""

    parents = {child: node for node in wezly(tree) for child in ast.iter_child_nodes(node)}
    for node in wezly(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if isinstance(parents.get(node), (ast.Expr, ast.JoinedStr)):
            continue
        enclosing: ast.AST = node
        while enclosing in parents and not isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing = parents[enclosing]
        function = enclosing.name if isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<moduł>"
        yield node.value, node.lineno, function


def _thread_names_in(src: Path) -> set[str]:
    return set().union(*(_thread_names(drzewo(path)) for path in sorted(src.rglob("*.py"))))


def _thread_name_copies(names: set[str]) -> list[str]:
    """Napisy testów i atrap równe nazwie wątku z ``names`` spoza ``NOT_THREADS`` i wpisy ``NOT_THREADS`` bez napisu."""

    found, excepted = [], set()
    for path, name in _scanned():
        for text, line, function in _texts(drzewo(path)):
            if text not in names:
                continue
            key = f"{name}::{function}::{text}"
            if key in NOT_THREADS:
                excepted.add(key)
            else:
                found.append(f"{_shown(path)}:{line}: {text!r} to kopia nazwy wątku z src/ ({key})")
    return found + [f"NOT_THREADS: {key} nie ma już tego napisu, usuń wpis" for key in sorted(NOT_THREADS.keys() - excepted)]


def test_testy_i_atrapy_nazywaja_watek_narzedzia_stala_a_nie_kopia_jego_nazwy() -> None:
    """Łapie napis równy całej nazwie wątku albo jej początkowi (``*_THREAD_PREFIX``) poza docstringami, a postacie,
    których nie łapie, są próbkami w ``ZNANE_LUKI_NAZW_WATKOW``. Napis, który nie nazywa wątku, trafia do
    ``NOT_THREADS`` pod kluczem z nawiasu."""

    names = _thread_names_in(SRC)
    found = _thread_name_copies(names)

    assert {QUEUE_THREAD, RUN_THREAD_PREFIX} <= names
    assert not found, "\n".join(
        [
            *found,
            "Importuj stałą nazwy wątku z src/ (np. QUEUE_THREAD), żeby zmiana jej tekstu nie zostawiła testu bez czekania; "
            "napis, który nie nazywa wątku, wpisz do NOT_THREADS pod kluczem z nawiasu, z powodem.",
        ]
    )


@pytest.mark.parametrize(
    ("src", "copy"),
    [
        ("import threading\nthreading.Thread(target=print, name='watek-proby').start()\n", "tools/lib/atrapy/kopia.py"),
        ("from typing import Final\nPROBA_THREAD: Final = 'watek-proby'\n", "test_kopia.py"),
        ("from rozliczenia.centrum.deadline import within\nwithin(1.0, print, name='watek-proby')\n", "tools/lib/atrapy/kopia.py"),
    ],
    ids=["name-w-thread", "stala-thread", "name-w-within"],
)
def test_straznik_nazw_watkow_zglasza_kopie_nazwy_z_kazdej_czytanej_postaci_w_testach_i_atrapach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, src: str, copy: str
) -> None:
    """Nazwa wątku w każdej postaci, którą strażnik czyta w ``src/``, skopiowana w atrapie albo teście obok pustej
    reszty: strażnik ją zgłasza (przegląd #1175 r1, Drobne 1 i 2)."""

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "watek.py").write_text(src, encoding="utf-8")
    atrapy = tmp_path / "tools" / "lib" / "atrapy"
    atrapy.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / ("tests" if copy.startswith("test_") else "") / copy).write_text("CZEKA_NA = 'watek-proby'\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "TESTS", tmp_path / "tests")
    monkeypatch.setattr(sys.modules[__name__], "ATRAPY", atrapy)
    monkeypatch.setattr(sys.modules[__name__], "NOT_THREADS", {})

    found = _thread_name_copies(_thread_names_in(tmp_path / "src"))

    assert [line.split(" (")[0] for line in found] == [f"{'tests/' if copy.startswith('test_') else ''}{copy}:1: 'watek-proby' to kopia nazwy wątku z src/"]


# Znane luki strażnika nazw wątków (tests/fixtures/znane_luki.py): opis postaci → moduł testu, który kopiuje nazwę
# wątku z src/ (QUEUE_THREAD, RUN_THREAD_PREFIX), a mimo to przechodzi przez _thread_name_copies.
ZNANE_LUKI_NAZW_WATKOW = {
    "nazwa złożona z kawałków w trakcie działania": 'CZEKA_NA = "skrzynka-" + "kolejka"\n',
    "początek nazwy w f-stringu": 'def watek_uruchomienia(numer: int) -> str:\n    return f"uruchomienie-{numer}"\n',
    "kawałek nazwy": 'def czeka_na_kolejke(nazwa: str) -> bool:\n    return nazwa.endswith("-kolejka")\n',
    "nazwa z bajtów": 'CZEKA_NA = b"skrzynka-kolejka".decode()\n',
}


def test_znane_luki_strazy_nazw_watkow_przechodza_przez_niego(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    pliki = zapisz(ZNANE_LUKI_NAZW_WATKOW, tmp_path / "tests")
    monkeypatch.setattr(sys.modules[__name__], "TESTS", tmp_path / "tests")
    monkeypatch.setattr(sys.modules[__name__], "ATRAPY", tmp_path / "atrapy")
    monkeypatch.setattr(sys.modules[__name__], "NOT_THREADS", {})
    names = _thread_names_in(SRC)
    opisy = {f"tests/{plik.name}": opis for opis, plik in pliki.items()}

    zgloszenia: dict[str, list[str]] = {opis: [] for opis in pliki}
    for linia in _thread_name_copies(names):
        zgloszenia[opisy[linia.split(":", 1)[0]]].append(linia)

    assert {QUEUE_THREAD, RUN_THREAD_PREFIX} <= names
    assert_znane_luki(zgloszenia, "tests/test_struktura_testow.py (ZNANE_LUKI_NAZW_WATKOW)")


# Zapadka, której bieg pustego drzewa nie uruchamia: dzisiejsze repozytorium ma wystąpienia form, których reguły ast-grep
# zakazują tylko w nowych liniach (ADR 0034), a zadania pytest na Windows instalują tylko ``requirements.txt``, bez ast-grep.
_ZAPADKA_AST_GREP = "tests/test_zapadki.py::test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo"


def _empty_tree_problems(root: Path) -> list[str]:
    """Problemy biegu ``tests/test_zapadki.py`` repozytorium ``root`` z bazą w pustym drzewie gita, w którym każda linia
    ``tests/`` i ``src/`` jest dodana: porażka biegu albo ``--deselect`` zapadki reguł ast-grep, który nie pominął
    dokładnie jednego testu. ``--deselect`` wybiera po prefiksie node id, więc test zapadek o nazwie z tym prefiksem
    zniknąłby z dowodu po cichu."""

    empty_tree = subprocess.run(
        ["git", "hash-object", "-t", "tree", "--stdin"], cwd=root, input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    environment = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    answered = subprocess.run(
        [
            *(sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "tests/test_zapadki.py"),
            *("--deselect", _ZAPADKA_AST_GREP),
        ],
        cwd=root,
        env={**environment, "MAXIMISEART_ZAPADKA_BAZA": empty_tree},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    summary = answered.stdout.splitlines()[-1] if answered.stdout else ""
    problems = [] if answered.returncode == 0 else [f"kod {answered.returncode}:\n{answered.stdout[-3000:]}"]
    if not re.search(r"(^|, )1 deselected\b", summary):
        problems.append(
            f"--deselect {_ZAPADKA_AST_GREP} pominął inną liczbę testów niż jeden, więc inny test zapadek zniknął z dowodu:"
            f" nadaj mu nazwę, która nie zaczyna się od nazwy tej zapadki | {summary}"
        )
    return problems


def test_zapadki_nie_zglaszaja_zadnej_linii_testow() -> None:
    """Dowód braku fałszywych alarmów każdej formy każdej zapadki: z bazą w pustym drzewie gita każda linia ``tests/``
    i ``src/`` jest dodana, a zapadki przechodzą, więc żadna forma nie trafia w dzisiejszy, poprawny test ani kod.

    Biegnie tu, a nie w ``tests/test_zapadki.py``, bo pomiar zapadek kładzie tamten plik na starych commitach, których
    ``tests/`` miało jeszcze własne wyrocznie, a moduł testu niczego nie eksportuje, więc zapadki biegną osobnym pytest.
    Reguły ast-grep biegną bez tego dowodu (``_ZAPADKA_AST_GREP``).
    """

    assert _empty_tree_problems(TESTS.parent) == []


# Reguła-fikstura z wystąpieniem w ``src/`` kopii repozytorium i fragment jej komunikatu dla ``AST_GREP_INSTRUCTIONS``.
_REGULA_FIKSTURA = """\
id: zakazane-wywolanie
language: python
severity: error
message: "Zamień zakazane() na dozwolone()."
files:
  - src/**
rule:
  pattern: zakazane()
"""
_AST_GREP_ANCHOR = 'AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))'
_AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))


def _repo_copy(root: Path) -> Path:
    """Kopia plików śledzonych i nieśledzonych, a nieignorowanych, checkoutu w ``root`` (to, co widzi bieg pustego
    drzewa), w nowym repozytorium gita bez commitu."""

    listed = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=TESTS.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    for name in filter(None, listed.split("\0")):
        if (TESTS.parent / name).is_file():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TESTS.parent / name, root / name)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.mark.parametrize(
    "ast_grep",
    [pytest.param(True, marks=pytest.mark.skipif(_AST_GREP is None, reason="brak ast-grep z dodatku dev")), False],
    ids=["z ast-grep", "bez ast-grep"],
)
def test_bieg_pustego_drzewa_przechodzi_z_regula_ast_grep_i_jej_starym_wystapieniem_w_src(tmp_path: Path, ast_grep: bool) -> None:
    """Pierwsza reguła w ``reguly-ast-grep/`` nie czerwieni dowodu braku fałszywych alarmów, choć dzisiejsze ``src/`` ma
    wystąpienia jej formy, z ast-grep (Mac, Linux z dodatkiem dev) i bez niego (zadania pytest na Windows z
    ``requirements.txt``): kopia repozytorium z regułą-fiksturą, jej wpisem w ``AST_GREP_INSTRUCTIONS`` i plikiem
    ``src/`` z jej formą przechodzi przez ``_empty_tree_problems``."""

    root = _repo_copy(tmp_path)
    (root / "reguly-ast-grep").mkdir(exist_ok=True)
    (root / "reguly-ast-grep" / "zakazane-wywolanie.yml").write_text(_REGULA_FIKSTURA, encoding="utf-8")
    (root / "src" / "rozliczenia" / "stare_wywolanie.py").write_text("zakazane()\n", encoding="utf-8")
    zapadki = root / "tests" / "test_zapadki.py"
    text = zapadki.read_text(encoding="utf-8")
    assert text.count(_AST_GREP_ANCHOR) == 1, f"tests/test_zapadki.py nie ma już linii {_AST_GREP_ANCHOR}"
    if not ast_grep:
        text = text.replace(_AST_GREP_ANCHOR, "AST_GREP = None")
    zapadki.write_text(text + '\nAST_GREP_INSTRUCTIONS["zakazane-wywolanie"] = "na dozwolone()"\n', encoding="utf-8")

    assert _empty_tree_problems(root) == []


def test_bieg_pustego_drzewa_zglasza_test_zapadek_pominiety_razem_z_zapadka_ast_grep(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    name = _ZAPADKA_AST_GREP.split("::")[1]
    (tmp_path / "tests" / "test_zapadki.py").write_text(
        "".join(f"def {test}() -> None:\n    pass\n\n\n" for test in (name, f"{name}_w_tests", "test_innej_zapadki")),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    [problem] = _empty_tree_problems(tmp_path)

    assert problem.startswith(f"--deselect {_ZAPADKA_AST_GREP} pominął inną liczbę testów niż jeden")
    assert "| 1 passed, 2 deselected in " in problem, problem
