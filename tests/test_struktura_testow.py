"""Struktura testów: moduły niczego nie eksportują, a test czeka na stan przez ``wait_for`` i mierzy czas bez stałej
liczby sekund.

Wspólne dane i pomocniki są w ``tests.fixtures``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
import re

import pytest

from tests.fixtures.skladnia import dotted, imports

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


def test_moduly_testow_importuja_pomocniki_tylko_z_fixtures() -> None:
    imports = {
        f"{path.name}: {node.module}"
        for path in sorted(TESTS.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("tests.")
        and not node.module.startswith("tests.fixtures")
    }

    assert imports == set(), "przenieś pomocnik do tests/fixtures i importuj go stamtąd; moduł testu niczego nie eksportuje"


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
    for use in ast.walk(tree):
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
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for call in ast.walk(tree):
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
        for call, function in _fixed_sleeps(ast.parse(path.read_text(encoding="utf-8"))):
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
    "test_potomne.py::test_potomek_spoza_drzewa_z_otwartym_wyjsciem_nie_wstrzymuje_wyniku::time.monotonic() - started < 30": (
        "granica 30 s oddziela koniec od zawieszenia: potomek z otwartym wyjściem śpi 600 s"
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
    for node in ast.walk(tree):
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
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for statement in ast.walk(tree):
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
        for compare, function in _constant_time_bounds(ast.parse(path.read_text(encoding="utf-8"))):
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
