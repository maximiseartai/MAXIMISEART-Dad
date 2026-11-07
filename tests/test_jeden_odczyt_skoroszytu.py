"""Plik taty czyta jedna droga: bajty skoroszytu z dysku tylko ``file_bytes``, a wartości pliku taty tylko uchwyt plików
taty (``dad_files.DadFiles``) ze świadkiem arkusza.

``file_bytes`` (``workbook_files``) zamienia błąd systemu plików na ``Problem.INACCESSIBLE``, a ``_open`` otwiera
skoroszyt w openpyxl tylko z bajtów. Odczyt z dysku poza nimi trafia w klasyfikację uszkodzeń openpyxl, dla której
``OSError`` to plik nieczytelny, i tata dostaje Komunikat o uszkodzonym pliku, który jest cały.

``DadFiles.read`` bierze chwilę zmiany pliku przed jego bajtami, więc odcisk w Kopii wejścia ma chwilę przeczytanej
wersji. Pamięć reguły danych i Kopię wejścia pisze tylko świadek arkusza (``dad_files.WitnessedSheet``), więc Kopia nie
ma wiersza, którego nie zna pamięć (ADR 0025). Test podstawia bajty przez ``input_checks.Readers.source``, a nie łata
modułu skoroszytu.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

ONLY: dict[str, frozenset[str]] = {
    "read_bytes": frozenset({"rozliczenia/workbook_files.py::file_bytes"}),
    "load_workbook": frozenset({"rozliczenia/workbook_files.py::_open"}),
    "_modified_at": frozenset({"rozliczenia/dad_files.py::read"}),
    "ReadFile": frozenset({"rozliczenia/dad_files.py::read"}),
    "InputCopy": frozenset({"rozliczenia/dad_files.py::for_run"}),
    "remember_value": frozenset({"rozliczenia/dad_files.py::remember"}),
    "workbook": frozenset({"rozliczenia/dad_files.py::enter_copy"}),
    "adapted": frozenset(),
}
"""Wywołanie (nazwa funkcji, klasy albo metody) → jedyne miejsca w ``src`` (plik::funkcja), które je wołają."""

EXCEPTIONS: dict[tuple[str, str], str] = {
    ("read_bytes", "rozliczenia/centrum/keyed_box.py::read_report_key"): "klucz Zgłoszeń to plik tekstowy; bez dostępu jest brakiem klucza",
    ("remember_value", "rozliczenia/efenix_pricing.py::_searched"): "adres z listy efenix, a nie z pliku taty",
    ("remember_value", "rozliczenia/input_checks.py::read_register"): "pamięć Rejestru w Przygotowaniu do N5b-1",
    ("workbook", "rozliczenia/input_checks.py::_copied"): "Kopia Rejestru w Przygotowaniu do N5b-1",
    **{
        ("InputCopy", f"rozliczenia/centrum/{run}_run.py::prepare"): "Kopia Uruchomienia z adaptera Centrum do N1a-1"
        for run in ("preparation", "settlement", "intermax", "efenix")
    },
    **{
        ("adapted", where): "uchwyt silnika z jego argumentów do N1a-1"
        for where in (
            "rozliczenia/engine.py::run_settlements",
            "rozliczenia/collective_preparation.py::prepare_collective_file",
            "rozliczenia/intermax_ordering.py::order_register",
            "rozliczenia/efenix_orders.py::read_scope",
        )
    },
}
"""Miejsca poza ``ONLY`` z powodem: stałe albo z terminem PR-u rozplątania 7.11, który je zdejmuje."""

PATCHED_IN_TESTS: dict[str, str] = {
    "test_centrum_uporzadkowanie_intermax.py": "Uporządkowanie dostaje Readers.source w N1a-1",
    "test_centrum_logi_uruchomienia.py": "Wycena w efenix dostaje Readers.source w N1a-1",
}
"""Pliki testów, które do N1a-1 łatają ``workbook_files``, bo ich silnik nie bierze jeszcze ``Readers.source``."""


def _calls(path: Path) -> list[tuple[str, str, int, str]]:
    """Wywołania w pliku: nazwa, funkcja, która woła, linia i tekst wywołania."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = {
        alias.asname: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname
    }
    owner = {
        node: function.name
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if called is not None:
            found.append((aliases.get(called, called), owner.get(node, "<moduł>"), node.lineno, ast.unparse(node.func)))
    return found


def test_plik_taty_czyta_jedna_droga_a_pamiec_i_kopie_pisze_tylko_swiadek_arkusza() -> None:
    found, excepted = [], set()
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        for called, function, line, text in _calls(path):
            if called not in ONLY:
                continue
            where = f"{name}::{function}"
            if where in ONLY[called]:
                continue
            if (called, where) in EXCEPTIONS:
                excepted.add((called, where))
            else:
                found.append(f"src/{name}:{line}: {text}(...) w {where}")
    found += [f"EXCEPTIONS: {called} w {where} już nie występuje, usuń wpis" for called, where in sorted(EXCEPTIONS.keys() - excepted)]

    assert not found, "\n".join(
        [
            *found,
            "Bajty skoroszytu czytaj przez file_bytes, a skoroszyt otwieraj przez _open z tych bajtów (workbook_files.py). "
            "Wartości pliku taty czytaj obiektywem na DadFiles.read; pamięć reguły danych i Kopia wejścia tylko przez "
            "WitnessedSheet albo SheetMemory (dad_files.py). Plik, który nie jest skoroszytem, wpisz do EXCEPTIONS z powodem.",
        ]
    )


def test_test_podstawia_bajty_plikow_taty_przez_readers_source_a_nie_latajac_modul_skoroszytu() -> None:
    found, patched = [], set()
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr"):
                continue
            target = node.args[0] if node.args else None
            named = isinstance(target, ast.Name) and target.id == "workbook_files"
            dotted = isinstance(target, ast.Constant) and str(target.value).startswith("rozliczenia.workbook_files")
            if not (named or dotted):
                continue
            if path.name in PATCHED_IN_TESTS:
                patched.add(path.name)
            else:
                found.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: {ast.unparse(node)}")
    found += [f"PATCHED_IN_TESTS: {name} już nie łata workbook_files, usuń wpis" for name in sorted(PATCHED_IN_TESTS.keys() - patched)]

    assert not found, "\n".join(
        [*found, "Bajty plików taty podstawiaj przez replace(FILE_READERS, source=...) w Surroundings(readers=...)."]
    )
