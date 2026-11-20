from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
import importlib.util
from itertools import pairwise
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import NamedTuple

import pytest

from repo import IMPORT_ROOTS
from rozliczenia import period_folder, tool_files
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
POLLING_LOOP = "fixtures/potomne.py::wait_for"
SIMULATED_TIME = {
    "test_centrum_przygotowanie.py::test_czas_czekania_na_decyzje_nie_wlicza_sie_do_czasu_ani_metryk": (
        "tata myśli 1,5 s nad Decyzją, a test mierzy zegarem testu, że ten czas nie wlicza się do metryk (f17b7fe)"
    ),
    "test_opiekun_ponownego_startu.py::test_skrot_klikniety_w_trakcie_ponownego_startu_nie_cofa_nowej_wersji_ktora_dziala": (
        "test gra skrót, który trzyma port przez 3 s w trakcie startu nowej wersji"
    ),
    "test_sen_w_tescie.py::test_sen_watku_sasiada_nie_trafia_do_podmiany_a_sen_watku_testu_trafia": (
        "sen wątku testu idzie do podmiany sleep_in_test_thread i nie czeka; test sprawdza, że do niej trafia"
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


class PathCall(NamedTuple):
    last_name: str
    path_position: int
    path_keyword: str


PREPEND = PathCall("syspath_prepend", 0, "path")
LOAD = PathCall("spec_from_file_location", 1, "location")
ON_PATH = frozenset(PurePosixPath(root).parts[1:] for root in IMPORT_ROOTS if PurePosixPath(root).parts[:1] == ("tools",))


def _tools_on_path(tree: ast.Module) -> list[int]:
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

    def path_of(node: ast.Call, call: PathCall) -> ast.expr | None:
        if called(node) != call.last_name:
            return None
        if len(node.args) > call.path_position:
            return node.args[call.path_position]
        return next((argument.value for argument in node.keywords if argument.arg == call.path_keyword), None)

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


TOOLS_NOT_ON_PATH = {
    "katalog-scripts-skilla-poza-conftest": 'SKILL = ROOT / ".agents" / "skills" / "verify-x"\nmonkeypatch.syspath_prepend(str(SKILL / "scripts"))',
    "katalog-z-tools-w-nazwie": 'monkeypatch.syspath_prepend("my_tools")',
    "wstawka-w-napisie-kodu-podprocesu-bez-conftest": 'KOD = "import sys\\nsys.path.insert(0, \'tools\')\\nimport mutacje\\n"',
    "sciezka-tools-bez-wstawki": 'LISTA = [str(ROOT / "tools")]',
    "plik-z-tools-hooks-poza-conftest": 'HOOK = ROOT / "tools" / "hooks" / "czekanie.py"\nimportlib.util.spec_from_file_location("czekanie", HOOK)',
    "plik-skryptu-skilla": 'importlib.util.spec_from_file_location("x", ROOT / ".agents" / "skills" / "verify-x" / "scripts" / "x.py")',
    "plik-atrapy-poza-conftest": 'importlib.util.spec_from_file_location("x", ROOT / "tools" / "lib" / "atrapy" / "x.py")',
    "katalog-zamiast-pliku-py": 'importlib.util.spec_from_file_location("lib", ROOT / "tools" / "lib")',
}


@pytest.mark.parametrize("code", TOOLS_NOT_ON_PATH.values(), ids=TOOLS_NOT_ON_PATH.keys())
def test_sprawdzenie_sys_path_przepuszcza_skrypty_skilli_i_kod_podprocesu(code: str) -> None:
    assert _tools_on_path(ast.parse(code)) == []


def test_narzedzie_wczytane_z_pliku_bez_wpisu_w_sys_modules_to_druga_kopia_w_ktorej_dataclass_pada(tmp_path: Path) -> None:
    narzedzie = tmp_path / "narzedzie_z_pliku.py"
    narzedzie.write_text(
        "from __future__ import annotations\nfrom dataclasses import dataclass\n\n\n@dataclass\nclass Wynik:\n    kod: int\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location(narzedzie.stem, narzedzie)
    assert spec is not None and spec.loader is not None
    kopia = importlib.util.module_from_spec(spec)

    with pytest.raises(AttributeError):
        spec.loader.exec_module(kopia)
    assert narzedzie.stem not in sys.modules


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
    platformy = platformy_mypy_ci()
    assert {"linux", "win32"} <= set(platformy), platformy
    kontrole = {platforma: f'import sys\n\nif sys.platform == "{platforma}":\n    x: int = "a"\n' for platforma in platformy}

    zgloszenia = ruff_i_mypy(zapisz(kontrole, tmp_path), sonda=TESTS / "test_sonda_luki.py")

    assert {platforma: [z.partition(" ")[0] for z in lista] for platforma, lista in zgloszenia.items()} == {
        platforma: [f"mypy[{platforma}]"] for platforma in platformy
    }, zgloszenia
    assert all(lista[0].endswith("[assignment]") for lista in zgloszenia.values()), zgloszenia


OWNED_NAMES_AS_LITERALS = {
    "test_opiekun_ponownego_startu.py": "test kontraktu nazw tool_files i scenariusze repozytorium Git opiekuna",
    "test_uszkodzone_wejscia.py": "test kontraktu miejsc plików stanu Centrum",
    "test_aktualizacja_narzedzia.py": "scenariusze repozytorium Git: historia, .gitignore i git status klonu taty",
    "test_przerwana_aktualizacja_narzedzia.py": "scenariusz repozytorium Git: plik taty, który nowa wersja przestaje śledzić",
    "fixtures/tool_clone.py": "pierwsza wersja repozytorium narzędzia w historii Git",
    "tools/lib/atrapy/pliki_taty.py": "kopia celowa świata taty: atrapy budują pliki taty niezależnie od src",
}
CONTRACTS = ("test_opiekun_ponownego_startu.py", "test_uszkodzone_wejscia.py")
SRC = TESTS.parent / "src" / "rozliczenia"


def test_nazwy_plikow_narzedzia_i_stanu_centrum_biora_testy_od_wlasciciela() -> None:
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


NAZWY_WLASCICIELA = {
    "napis-rowny-nazwie": (f"PLIK = {REPORT_KEY_FILE!r}\n", [REPORT_KEY_FILE]),
    "sciezka-konczaca-sie-nazwa-po-ukosniku": (f'PLIK = "config/{REPORT_KEY_FILE}"\n', [f"config/{REPORT_KEY_FILE}"]),
    "sciezka-windows-konczaca-sie-nazwa": (f'PLIK = r"config\\{REPORT_KEY_FILE}"\n', [f"config\\{REPORT_KEY_FILE}"]),
    "czesc-f-stringu": (f'PLIK = f"{{KATALOG}}/{REPORT_KEY_FILE}"\n', [f"/{REPORT_KEY_FILE}"]),
    "nazwa-sciezki-z-tool-files": (f"WZORZEC = {tool_files.WORKER_TEMPLATE.name!r}\n", [tool_files.WORKER_TEMPLATE.name]),
    "nazwa-stalej-file-z-src": (f"PLIK = {WORKERS_FILE!r}\n", [WORKERS_FILE]),
    "granica-nazwa-w-zdaniu-komunikatu-taty-jak-w-tests-expected": (
        f'TEKST = "Zapisz {REPORT_KEY_FILE} w folderze config."\n',
        [],
    ),
    "granica-folder-to-slowo-ogolne-takze-nazwa-strony": ('KATALOG = "config"\nSTRONA = "uruchomienia"\n', []),
    "granica-dziennik-centrum-centrumlog-w-tescie-dostaje-dowolna-sciezke": (
        f'DZIENNIK = "logs/{tool_files.LOG_PATH.name}"\n',
        [],
    ),
}


@pytest.mark.parametrize(("code", "found"), NAZWY_WLASCICIELA.values(), ids=NAZWY_WLASCICIELA.keys())
def test_straznik_nazw_wlasciciela_lapie_napis_i_koniec_sciezki_a_przepuszcza_granice(
    tmp_path: Path, code: str, found: list[str]
) -> None:
    module = tmp_path / "test_nazwa.py"
    module.write_text(code, encoding="utf-8")

    assert [node.value for node in _owned_literals(module, _owned_names())] == found


ZNANE_LUKI_NAZW_WLASCICIELA = {
    "nazwa sklejona z części w trakcie działania": f"PLIK = {REPORT_KEY_FILE[:5]!r} + {REPORT_KEY_FILE[5:]!r}\n",
    "stała tekstowa src bez przyrostka _FILE": f"STAN = {tool_files.REPORT_ENTERING_STATE!r}\n",
    "plik okresu z tokenem okresu": f"PLIK = {period_folder.collective_file_name_with('01_07_09_2026')!r}\n",
}


def test_znane_luki_straznika_nazw_wlasciciela_przechodza_przez_niego(tmp_path: Path) -> None:
    names = _owned_names()
    pliki = zapisz(ZNANE_LUKI_NAZW_WLASCICIELA, tmp_path)

    zgloszenia = {opis: [f"_owned_literals: {node.value!r}" for node in _owned_literals(plik, names)] for opis, plik in pliki.items()}

    assert_znane_luki(zgloszenia, "tests/test_struktura_testow.py (ZNANE_LUKI_NAZW_WLASCICIELA)")


def _scanned() -> list[tuple[Path, str]]:
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
    function = call.func
    return dotted(function, names, "") in SLEEPS or (
        isinstance(function, ast.Attribute)
        and function.attr == "wait"
        and isinstance(function.value, ast.Call)
        and dotted(function.value.func, names, "") == "threading.Event"
    )


def _handed_over(definition: Definition, tree: ast.Module, parents: dict[ast.AST, ast.AST]) -> bool:
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


SNY = {
    "time-sleep": ("import time\ndef test_a() -> None:\n    time.sleep(1)\n", ["test_a"]),
    "modul-time-pod-inna-nazwa": ("import time as zegar\ndef test_a() -> None:\n    zegar.sleep(1)\n", ["test_a"]),
    "sleep-z-importu-pod-inna-nazwa": ("from time import sleep as pauza\ndef test_a() -> None:\n    pauza(1)\n", ["test_a"]),
    "asyncio-sleep": ("import asyncio\nasync def test_a() -> None:\n    await asyncio.sleep(1)\n", ["test_a"]),
    "czekanie-na-nowe-zdarzenie-ktorego-nikt-nie-ustawi": (
        "import threading\ndef test_a() -> None:\n    threading.Event().wait(1)\n",
        ["test_a"],
    ),
    "sen-poza-funkcja": ("import time\ntime.sleep(1)\n", ["<moduł>"]),
    "petla-z-wlasnym-terminem": (
        "import time\ndef test_a(stan) -> None:\n    koniec = time.monotonic() + 5\n"
        "    while not stan() and time.monotonic() < koniec:\n        time.sleep(0.1)\n",
        ["test_a"],
    ),
    "funkcja-ktora-test-wola-sam": (
        "import time\ndef pomocnik() -> None:\n    time.sleep(1)\ndef test_a() -> None:\n    pomocnik()\n",
        ["pomocnik"],
    ),
    "klasa-ktorej-metode-test-wola-sam": (
        "import time\nclass Wolny:\n    def czekaj(self) -> None:\n        time.sleep(1)\n"
        "def test_a() -> None:\n    Wolny().czekaj()\n",
        ["czekaj"],
    ),
    "lambda-wolana-od-razu": ("import time\ndef test_a() -> None:\n    (lambda: time.sleep(1))()\n", ["test_a"]),
    "lambda-wolana-przez-nazwe": (
        "import time\ndef test_a() -> None:\n    czekaj = lambda: time.sleep(1)\n    czekaj()\n",
        ["test_a"],
    ),
    "granica-podrobka-funkcja-przekazana-kodowi-pod-testem": (
        "import time\ndef wolno() -> None:\n    time.sleep(1)\ndef test_a(kod) -> None:\n    kod(wolno)\n",
        [],
    ),
    "granica-podrobka-klasa-przekazana-kodowi-pod-testem": (
        "import time\nclass Wolny:\n    def czekaj(self) -> None:\n        time.sleep(1)\n"
        "def test_a(kod) -> None:\n    kod(Wolny)\n",
        [],
    ),
    "granica-podrobka-lambda-przekazana-kodowi-pod-testem": (
        "import time\ndef test_a(kod) -> None:\n    kod(lambda: time.sleep(1))\n",
        [],
    ),
    "granica-podrobka-lambda-z-nazwy-przekazana-kodowi-pod-testem": (
        "import time\ndef test_a(kod) -> None:\n    czekaj = lambda: time.sleep(1)\n    kod(czekaj)\n",
        [],
    ),
}


@pytest.mark.parametrize(("code", "functions"), SNY.values(), ids=SNY.keys())
def test_sprawdzenie_snu_zglasza_sen_testu_z_jego_funkcja_a_przepuszcza_sen_podrobki(code: str, functions: list[str]) -> None:
    assert [function for _, function in _fixed_sleeps(ast.parse(code))] == functions


ZNANE_LUKI_SNU = {
    "zdarzenie w zmiennej, którego nikt nie ustawia": (
        "import threading\ndef test_a() -> None:\n    hold = threading.Event()\n    hold.wait(2)\n"
    ),
    "podróbka, którą test woła sam przez inną nazwę": (
        "import time\ndef wolno() -> None:\n    time.sleep(1)\ndef test_a() -> None:\n    inna = wolno\n    inna()\n"
    ),
    "pętla z terminem bez snu": (
        "import time\ndef test_a(stan) -> None:\n    koniec = time.monotonic() + 5\n"
        "    while not stan() and time.monotonic() < koniec:\n        pass\n"
    ),
}


def test_znane_luki_sprawdzenia_snu_przechodza_przez_nie() -> None:
    zgloszenia = {
        opis: [f"_fixed_sleeps: {ast.unparse(call)} w {function}" for call, function in _fixed_sleeps(ast.parse(kod))]
        for opis, kod in ZNANE_LUKI_SNU.items()
    }

    assert_znane_luki(zgloszenia, "tests/test_struktura_testow.py (ZNANE_LUKI_SNU)")


def test_testy_czekaja_na_stan_a_nie_stala_liczbe_sekund() -> None:
    found, simulated = [], set()
    for path, name in _scanned():
        for call, function in _fixed_sleeps(drzewo(path)):
            if f"{name}::{function}" == POLLING_LOOP:
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
    "test_aktualizacja_narzedzia.py::test_pobranie_ktore_stoi_konczy_sam_git_zanim_minie_limit_czasu_pobrania"
    "::elapsed < 30": (
        "granica 30 s oddziela koniec od zawieszenia: Git kończy stojące pobranie po 1 s (_STALLED_FOR_S w teście), "
        "a bez http.lowSpeedLimit czekałby na limit czasu pobrania, w teście 60 s"
    ),
    "test_aktualnosc_narzedzia.py::test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu"
    "::time.monotonic() - started < 1.5": (
        "serwer nie odpowiada nigdy, więc bez limitu 0,3 s diagnoza czekałaby bez końca; granica to 5× ten limit"
    ),
    "test_centrum_launcher.py::test_obcy_program_ktory_milczy_nie_wstrzymuje_startu_dluzej_niz_limit_czekania_na_health"
    "::waited < wait_s * 1.8": (
        "obcy program mierzy samo czekanie launchera, od pytania o health do zamknięcia połączenia, bez reszty startu; "
        "granica poniżej dwóch skróconych limitów (2,5 s) łapie launcher, który czeka dwa razy dłużej albo na "
        "prawdziwym limicie 5 s"
    ),
    "test_centrum_launcher.py::test_obcy_program_ktory_milczy_nie_wstrzymuje_startu_dluzej_niz_limit_czekania_na_health"
    "::took < wait_s * 2": (
        "cały start to skrócony limit (2,5 s) i praca startu, której zapas to drugi limit, prawie dwa razy więcej niż "
        "cały narzut runnera Windows w #1782 (1,34 s); łapie start, który czeka jeszcze limit przed pytaniem o health "
        "albo po nim, także ponawianie portu przez 10 s"
    ),
    "test_centrum_powiadomienia.py::test_spozniona_odpowiedz_skrzynki_nie_wstrzymuje_powiadomien_a_jej_stan_i_tak_zostaje"
    "::took < wait_s * 1.8": (
        "skrzynka trzyma odpowiedź do końca testu, a granica poniżej dwóch skróconych limitów CHECK_WAIT_S (1 s) łapie "
        "Powiadomienia, które czekają dwa razy dłużej"
    ),
    "test_model_tlc.py::test_przebieg_tlc_bez_wyniku_w_limicie_konczy_sprawdzenie_zawieszeniem_ze_zrzutem_watkow_i_zabija_drzewo_tlc"
    "::took < 30": (
        "granica 30 s oddziela koniec od zawieszenia: atrapa Javy śpi 60 s, a limit przebiegu z czasem na zrzut to najwyżej 9 s"
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
    nots = 0
    node: ast.AST = compare
    while node is not statement:
        node = parents[node]
        nots += isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    return nots % 2 == 1


def _constant_time_bounds(tree: ast.Module) -> Iterator[tuple[ast.Compare, str]]:
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


GRANICE_CZASU = {
    "nazwa-elapsed": ("def test_a(elapsed) -> None:\n    assert elapsed < 2\n", ["elapsed < 2"]),
    "nazwa-duration": ("def test_a(duration) -> None:\n    assert duration <= 2\n", ["duration <= 2"]),
    "nazwa-z-przyrostkiem-ms": ("def test_a(took_ms) -> None:\n    assert took_ms < 200\n", ["took_ms < 200"]),
    "atrybut-z-przyrostkiem-s": ("def test_a(wynik) -> None:\n    assert wynik.load_s < 2\n", ["wynik.load_s < 2"]),
    "odczyt-zegara": (
        "import time\ndef test_a() -> None:\n    started = time.monotonic()\n    assert time.monotonic() - started < 2\n",
        ["time.monotonic() - started < 2"],
    ),
    "odczyt-datetime-now-pod-nazwa-z-importu": (
        "from datetime import datetime\ndef test_a(start) -> None:\n    assert (datetime.now() - start).seconds < 2\n",
        ["(datetime.now() - start).seconds < 2"],
    ),
    "stala-z-lewej": ("def test_a(elapsed) -> None:\n    assert 2 > elapsed\n", ["2 > elapsed"]),
    "pod-nieparzysta-liczba-not": ("def test_a(elapsed) -> None:\n    assert not elapsed >= 2\n", ["elapsed >= 2"]),
    "pod-parzysta-liczba-not": ("def test_a(elapsed) -> None:\n    assert not not elapsed < 2\n", ["elapsed < 2"]),
    "stala-z-dzialania-na-liczbach": ("def test_a(elapsed) -> None:\n    assert elapsed < -2 * 3\n", ["elapsed < -2 * 3"]),
    "stala-z-nazwy-przypisanej-tylko-liczbie": (
        "LIMIT = 2\ndef test_a(elapsed) -> None:\n    assert elapsed < LIMIT\n",
        ["elapsed < LIMIT"],
    ),
    "porownanie-lancuchowe": ("def test_a(elapsed) -> None:\n    assert 0 <= elapsed < 2\n", ["0 <= elapsed < 2"]),
    "nazwa-z-rozpakowania-krotki": (
        "import time\ndef test_a(started) -> None:\n    took, _ = time.monotonic() - started, 0\n    assert took < 2\n",
        ["took < 2"],
    ),
    "nazwa-z-przyrostu": (
        "import time\ndef test_a(started) -> None:\n    took = 0\n    took += time.monotonic() - started\n    assert took < 2\n",
        ["took < 2"],
    ),
    "granica-dolna-granica-pod-not": ("def test_a(elapsed) -> None:\n    assert not elapsed < 2\n", []),
    "granica-dolna-granica": ("def test_a(elapsed) -> None:\n    assert elapsed >= 2\n", []),
    "granica-wartosc-bez-czasu": ("def test_a(count) -> None:\n    assert count < 2\n", []),
    "granica-nazwa-czasu-przypisana-liczbie": ("wait_s = 2\ndef test_a(count) -> None:\n    assert count * wait_s < 3\n", []),
    "granica-limit-z-parametru": ("def test_a(elapsed, wait_s) -> None:\n    assert elapsed < wait_s * 2\n", []),
    "granica-limit-przypisany-liczbie-i-petli": (
        "LIMIT = 2\ndef test_a(elapsed) -> None:\n    for LIMIT in (1, 3):\n        assert elapsed < LIMIT\n",
        [],
    ),
    "granica-limit-zalezny-od-siebie": (
        "LIMIT = 2\nLIMIT += 1\ndef test_a(elapsed) -> None:\n    assert elapsed < LIMIT\n",
        [],
    ),
    "granica-wartosc-logiczna": ("def test_a(elapsed) -> None:\n    assert elapsed < True\n", []),
}


@pytest.mark.parametrize(("module", "bounds"), GRANICE_CZASU.values(), ids=GRANICE_CZASU.keys())
def test_sprawdzenie_granicy_czasu_lapie_kazda_wyliczona_postac_a_przepuszcza_granice(module: str, bounds: list[str]) -> None:
    assert [ast.unparse(compare) for compare, _ in _constant_time_bounds(ast.parse(module))] == bounds


def test_nazwy_wiazane_wiele_razy_bez_zegara_nie_daja_granicy_czasu_bez_przejscia_kazdej_sciezki_wiazan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebound = 60
    chain = "".join(f"n{number + 1} = n{number}\nn{number + 1} = n{number} + 1\n" for number in range(rebound))
    values = 2 * rebound + 1
    evaluated: list[ast.expr] = []
    measured = _measured

    def counted(
        expression: ast.expr, bound: dict[str, list[ast.expr | None]], names: dict[str, str], measured_names: set[str]
    ) -> bool:
        evaluated.append(expression)
        assert len(evaluated) <= values**2, "licz nazwy ze zmierzonym czasem punktem stałym raz na moduł, a nie każdą ścieżką wiązań osobno"
        return measured(expression, bound, names, measured_names)

    monkeypatch.setattr(sys.modules[__name__], "_measured", counted)

    assert list(_constant_time_bounds(ast.parse(f"n0 = wczytaj()\n{chain}assert n{rebound} < 2\n"))) == []


ZNANE_LUKI_GRANICY_CZASU = {
    "stała z parametru pytest.mark.parametrize": (
        'import pytest\n@pytest.mark.parametrize("limit", [2])\ndef test_a(elapsed, limit) -> None:\n    assert elapsed < limit\n'
    ),
    "stała z innego modułu": "from stale import LIMIT\ndef test_a(elapsed) -> None:\n    assert elapsed < LIMIT\n",
    "stała z atrybutu klasy": "class Stale:\n    LIMIT = 2\ndef test_a(elapsed) -> None:\n    assert elapsed < Stale.LIMIT\n",
    "stała z timedelta": (
        "from datetime import timedelta\ndef test_a(elapsed) -> None:\n    assert elapsed < timedelta(seconds=2)\n"
    ),
    "nazwa wiązana gdzie indziej czymś innym niż liczba": (
        "LIMIT = 2\ndef inny() -> None:\n    LIMIT = wczytaj()\ndef test_a(elapsed) -> None:\n    assert elapsed < LIMIT\n"
    ),
    "zmierzony czas w pomocniku z innego modułu": (
        "from pomocnicy import zmierz\ndef test_a() -> None:\n    took = zmierz()\n    assert took < 2\n"
    ),
    "pytest.approx z abs": "import pytest\ndef test_a(elapsed) -> None:\n    assert elapsed == pytest.approx(1, abs=1)\n",
    "math.isclose z abs_tol": "import math\ndef test_a(elapsed) -> None:\n    assert math.isclose(elapsed, 1, abs_tol=1)\n",
    "if z pytest.fail": 'import pytest\ndef test_a(elapsed) -> None:\n    if elapsed > 2:\n        pytest.fail("za wolno")\n',
}


def test_znane_luki_sprawdzenia_granicy_czasu_przechodza_przez_nie() -> None:
    zgloszenia = {
        opis: [f"_constant_time_bounds: {ast.unparse(compare)}" for compare, _ in _constant_time_bounds(ast.parse(kod))]
        for opis, kod in ZNANE_LUKI_GRANICY_CZASU.items()
    }

    assert_znane_luki(zgloszenia, "tests/test_struktura_testow.py (ZNANE_LUKI_GRANICY_CZASU)")


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
NOT_THREADS = {
    "test_instrukcja_taty.py::<moduł>::aktualizacja-narzedzia": "funkcja Instrukcji taty o tej samej nazwie co wątek",
    "test_centrum_przygotowanie.py::test_dziennik_centrum_ma_poczatek_i_koniec_uruchomienia_z_wynikiem_bez_danych_klientow"
    "::uruchomienie-": "początek nazw wpisów dziennika Centrum o Uruchomieniu, nie wątku",
}


def _thread_names(tree: ast.Module) -> set[str]:
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


@pytest.mark.parametrize(
    ("not_threads", "found"),
    [
        ({}, []),
        (
            {"test_kopia.py::<moduł>::watek-proby": "napis bez kopii"},
            ["NOT_THREADS: test_kopia.py::<moduł>::watek-proby nie ma już tego napisu, usuń wpis"],
        ),
    ],
    ids=["docstring-rowny-nazwie-watku-to-nie-kopia", "wpis-not-threads-bez-napisu"],
)
def test_straznik_nazw_watkow_przepuszcza_docstring_i_zglasza_wpis_not_threads_bez_napisu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, not_threads: dict[str, str], found: list[str]
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_kopia.py").write_text('"""watek-proby"""\n\n\ndef test_a() -> None:\n    """watek-proby"""\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "TESTS", tmp_path / "tests")
    monkeypatch.setattr(sys.modules[__name__], "ATRAPY", tmp_path / "atrapy")
    monkeypatch.setattr(sys.modules[__name__], "NOT_THREADS", not_threads)

    assert _thread_name_copies({"watek-proby"}) == found


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


_ZAPADKA_AST_GREP = "tests/test_zapadki.py::test_reguly_ast_grep_nie_zglaszaja_linii_dodanych_w_repo"
WORKERY_DOWODU = 4


def _empty_tree_problems(root: Path) -> list[str]:
    empty_tree = subprocess.run(
        ["git", "hash-object", "-t", "tree", "--stdin"], cwd=root, input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    environment = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    selection = ("-p", "no:cacheprovider", "tests/test_zapadki.py", "--deselect", _ZAPADKA_AST_GREP)

    def pytest(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *arguments, *selection],
            cwd=root,
            env={**environment, "MAXIMISEART_ZAPADKA_BAZA": empty_tree},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    collected = pytest("--collect-only", "-n", "0")
    summary = collected.stdout.splitlines()[-1] if collected.stdout else ""
    if collected.returncode:
        return [f"kolekcja tests/test_zapadki.py: kod {collected.returncode}:\n{collected.stdout[-3000:]}"]
    if not re.search(r"\(1 deselected\)", summary):
        return [
            f"--deselect {_ZAPADKA_AST_GREP} pominął inną liczbę testów niż jeden, więc inny test zapadek zniknąłby z dowodu:"
            f" nadaj mu nazwę, która nie zaczyna się od nazwy tej zapadki | {summary}"
        ]
    answered = pytest("-n", str(WORKERY_DOWODU))
    return [] if answered.returncode == 0 else [f"kod {answered.returncode}:\n{answered.stdout[-3000:]}"]


def test_zapadki_nie_zglaszaja_zadnej_linii_testow() -> None:
    assert _empty_tree_problems(TESTS.parent) == []


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
_BEZ_DODATKU_DEV_ANCHOR = 'BEZ_DODATKU_DEV = sys.platform == "win32"'
_AST_GREP = shutil.which("ast-grep", path=sysconfig.get_path("scripts"))


def _repo_copy(root: Path) -> Path:
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
    root = _repo_copy(tmp_path)
    (root / "reguly-ast-grep").mkdir(exist_ok=True)
    (root / "reguly-ast-grep" / "zakazane-wywolanie.yml").write_text(_REGULA_FIKSTURA, encoding="utf-8")
    (root / "src" / "rozliczenia" / "stare_wywolanie.py").write_text("zakazane()\n", encoding="utf-8")
    zapadki = root / "tests" / "test_zapadki.py"
    text = zapadki.read_text(encoding="utf-8")
    assert text.count(_AST_GREP_ANCHOR) == 1, f"tests/test_zapadki.py nie ma już linii {_AST_GREP_ANCHOR}"
    assert text.count(_BEZ_DODATKU_DEV_ANCHOR) == 1, f"tests/test_zapadki.py nie ma już linii {_BEZ_DODATKU_DEV_ANCHOR}"
    if not ast_grep:
        text = text.replace(_AST_GREP_ANCHOR, "AST_GREP = None").replace(_BEZ_DODATKU_DEV_ANCHOR, "BEZ_DODATKU_DEV = True")
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

    assert problem.startswith(f"--deselect {_ZAPADKA_AST_GREP} pominął inną liczbę testów niż jeden"), problem
    assert "1/3 tests collected (2 deselected)" in problem, problem


def test_bieg_pustego_drzewa_mowi_o_bledzie_kolekcji_pliku_zapadek(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_zapadki.py").write_text("import nie_ma_takiego_modulu\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    [problem] = _empty_tree_problems(tmp_path)

    assert problem.startswith("kolekcja tests/test_zapadki.py: kod 2:"), problem
    assert "nie_ma_takiego_modulu" in problem, problem
