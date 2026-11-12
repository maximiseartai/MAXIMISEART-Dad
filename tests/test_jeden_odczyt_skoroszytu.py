"""Plik taty czyta jedna droga: bajty skoroszytu z dysku tylko ``file_bytes``, a wartości pliku taty tylko uchwyt plików
taty (``dad_files.DadFiles``) ze świadkiem arkusza.

``file_bytes`` (``workbook_files``) zamienia błąd systemu plików na ``Problem.INACCESSIBLE``, a ``_open`` otwiera
skoroszyt w openpyxl tylko z bajtów. Odczyt z dysku poza nimi trafia w klasyfikację uszkodzeń openpyxl, dla której
``OSError`` to plik nieczytelny, i tata dostaje Komunikat o uszkodzonym pliku, który jest cały.

``DadFiles.read`` bierze chwilę zmiany pliku przed jego bajtami, więc odcisk w Kopii wejścia ma chwilę przeczytanej
wersji. Bajty z ``file_bytes``, ``workbook_content`` albo ``template_content`` i skoroszyt z ``open_workbook`` mają
tylko miejsca z ``ONLY`` i ``EXCEPTIONS``, więc nowy czytnik nie czyta wartości pliku taty obok uchwytu, bez sprawdzenia
dostępności, źródła bajtów uchwytu (``DadFiles.source``), pamięci i Kopii. Pamięć reguły danych i Kopię wejścia pisze
tylko świadek arkusza (``dad_files.WitnessedSheet``), więc Kopia nie ma wiersza, którego nie zna pamięć (ADR 0025). Test
i atrapa wspólna z testami (``tools/lib/atrapy``) podstawiają bajty przez źródło bajtów uchwytu (``DadFiles.source``, w
Centrum ``create_app(source=...)``), a nie łatają modułu skoroszytu.

Granica: strażnik widzi wywołanie po nazwie funkcji (także z aliasem importu ``from … import … as …``) i łatanie modułu
``workbook_files`` przez ``setattr``/``delattr`` oraz ``patch``/``patch.object``/``patch.multiple``, gdy moduł stoi w
wywołaniu po nazwie, aliasie importu, jako atrybut (``rozliczenia.workbook_files``) albo jako napis
``"rozliczenia.workbook_files…"``. Funkcję albo moduł wzięte do zmiennej (``read = workbook_files.file_bytes``,
``importlib``, napis złożony w czasie biegu), przypisanie wprost (``workbook_files.file_bytes = …``), łatkę przez alias
łatającego (``patch as p``), ``patch.dict``, ``getattr`` z napisem i surowe ``open(path, "rb")`` w ``src`` widzi tylko
przegląd.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
# Atrapy wspólne z testami (tools/lib/atrapy) podstawiają bajty plików taty tak samo jak testy.
ATRAPY = ROOT / "tools" / "lib" / "atrapy"

ONLY: dict[str, frozenset[str]] = {
    "read_bytes": frozenset({"rozliczenia/workbook_files.py::file_bytes"}),
    "load_workbook": frozenset({"rozliczenia/workbook_files.py::_open"}),
    "file_bytes": frozenset(
        {
            "rozliczenia/workbook_files.py::workbook_content",
            "rozliczenia/workbook_files.py::template_content",
        }
    ),
    "workbook_content": frozenset(),
    "template_content": frozenset({"rozliczenia/template_file.py::_read"}),
    "open_workbook": frozenset(
        {"rozliczenia/template_file.py::_openpyxl_workbook", "rozliczenia/register_file.py::_windows"}
    ),
    "_modified_at": frozenset({"rozliczenia/dad_files.py::read"}),
    "ReadFile": frozenset({"rozliczenia/dad_files.py::read"}),
    "InputCopy": frozenset({"rozliczenia/dad_files.py::for_run"}),
    "remember_value": frozenset({"rozliczenia/dad_files.py::remember"}),
    "workbook": frozenset({"rozliczenia/dad_files.py::enter_copy"}),
}
"""Wywołanie (nazwa funkcji, klasy albo metody) → jedyne miejsca w ``src`` (plik::funkcja), które je wołają."""

EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        "read_bytes",
        "rozliczenia/centrum/keyed_box.py::read_report_key",
    ): "klucz Zgłoszeń to plik tekstowy; bez dostępu jest brakiem klucza",
    (
        "read_bytes",
        "rozliczenia/worker_report_inbox.py::_read_access",
    ): "plik dostępu do Skrzynki raportów to plik tekstowy Maksa w config, nie plik taty",
    (
        "read_bytes",
        "rozliczenia/centrum/report_reminders.py::_text",
    ): "dzień wdrożenia i stopka Przypomnień o raporcie to pliki tekstowe Maksa w config, nie pliki taty",
    (
        "workbook_content",
        "rozliczenia/intermax_replace.py::_read",
    ): "bajty Rejestru do podmiany pliku, nie jego wartości",
    (
        "workbook_content",
        "rozliczenia/intermax_restore.py::restore",
    ): "bajty Rejestru i Kopii INTERMAX do przywrócenia, nie ich wartości",
    (
        "workbook_content",
        "rozliczenia/efenix_marking.py::mark_orders",
    ): "porównanie bajtów pliku przed zapisem Znaczników, nie jego wartości",
    (
        "remember_value",
        "rozliczenia/efenix_pricing.py::_searched",
    ): "adres z listy efenix, a nie z pliku taty",
}
"""Miejsca poza ``ONLY`` z powodem."""

MODULE = "workbook_files"
PATCHERS = frozenset({"setattr", "delattr", "patch", "object", "multiple"})
"""Wywołania, które łatają atrybut modułu: ``monkeypatch``, wbudowane ``setattr``/``delattr`` i ``unittest.mock``."""


def _called(node: ast.Call) -> str | None:
    return (
        node.func.attr
        if isinstance(node.func, ast.Attribute)
        else getattr(node.func, "id", None)
    )


def _calls(source: str) -> list[tuple[str, str, int, str]]:
    """Wywołania w tekście modułu: nazwa, funkcja, która woła, linia i tekst wywołania."""

    tree = ast.parse(source)
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
        if isinstance(node, ast.Call) and (called := _called(node)) is not None:
            found.append(
                (
                    aliases.get(called, called),
                    owner.get(node, "<moduł>"),
                    node.lineno,
                    ast.unparse(node.func),
                )
            )
    return found


def _src_findings(modules: Mapping[str, str]) -> tuple[list[str], set[tuple[str, str]]]:
    """Wywołania z ``ONLY`` poza ich miejscami i wyjątkami w modułach ``nazwa względem src → tekst`` oraz wyjątki, które
    wystąpiły."""

    found, excepted = [], set()
    for name, source in modules.items():
        for called, function, line, text in _calls(source):
            if called not in ONLY:
                continue
            where = f"{name}::{function}"
            if where in ONLY[called]:
                continue
            if (called, where) in EXCEPTIONS:
                excepted.add((called, where))
            else:
                found.append(f"src/{name}:{line}: {text}(...) w {where}")
    return found, excepted


def _module_names(tree: ast.Module) -> set[str]:
    """Nazwy, pod którymi test ma moduł ``rozliczenia.workbook_files``: sama nazwa i aliasy importu."""

    names = {MODULE}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "rozliczenia":
            names |= {
                alias.asname
                for alias in node.names
                if alias.name == MODULE and alias.asname
            }
        elif isinstance(node, ast.Import):
            names |= {
                alias.asname
                for alias in node.names
                if alias.name == f"rozliczenia.{MODULE}" and alias.asname
            }
    return names


def _patches(source: str) -> list[tuple[int, str]]:
    """Łatania modułu ``workbook_files`` w tekście testu: linia i tekst wywołania."""

    tree = ast.parse(source)
    names = _module_names(tree)

    def is_module(target: ast.expr | None) -> bool:
        if isinstance(target, ast.Name):
            return target.id in names
        if isinstance(target, ast.Attribute):
            return target.attr == MODULE
        return isinstance(target, ast.Constant) and str(target.value).startswith(
            f"rozliczenia.{MODULE}"
        )

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _called(node) in PATCHERS):
            continue
        target = (
            node.args[0]
            if node.args
            else next((kw.value for kw in node.keywords if kw.arg == "target"), None)
        )
        if is_module(target):
            found.append((node.lineno, ast.unparse(node)))
    return found


def test_plik_taty_czyta_jedna_droga_a_pamiec_i_kopie_pisze_tylko_swiadek_arkusza() -> (
    None
):
    found, excepted = _src_findings(
        {
            path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(SRC.rglob("*.py"))
        }
    )
    found += [
        f"EXCEPTIONS: {called} w {where} już nie występuje, usuń wpis"
        for called, where in sorted(EXCEPTIONS.keys() - excepted)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Bajty skoroszytu czytaj przez file_bytes, a skoroszyt otwieraj przez _open z tych bajtów (workbook_files.py). "
            "Wartości pliku taty czytaj obiektywem na DadFiles.read, a nie z bajtów file_bytes, workbook_content albo "
            "template_content; pamięć reguły danych i Kopia wejścia tylko przez WitnessedSheet albo SheetMemory "
            "(dad_files.py). Plik, który nie jest skoroszytem z wartościami taty (Wzorzec, bajty do podmiany), wpisz do "
            "EXCEPTIONS z powodem.",
        ]
    )


def test_czytnik_wartosci_pliku_taty_z_bajtow_obok_uchwytu_wywraca_straznika() -> None:
    reader = (
        "from . import workbook_files\n"
        "from .workbook_files import open_workbook as opened, workbook_content\n"
        "def first_address(path):\n"
        "    with workbook_files.open_workbook(path, workbook_files.file_bytes(path), read_only=True) as read:\n"
        "        return read.workbook.active['B18'].value\n"
        "def first_address_after_check(path):\n"
        "    with opened(path, workbook_content(path)) as read:\n"
        "        return read.workbook.active['B18'].value\n"
        "def template_address(path):\n"
        "    return workbook_files.template_content(path)\n"
        "def opened_values(path, content):\n"
        "    return workbook_files.open_workbook(path, content, read_only=True)\n"
    )

    found, _ = _src_findings({"rozliczenia/sonda.py": reader})

    assert sorted(found) == sorted(
        [
            "src/rozliczenia/sonda.py:4: workbook_files.open_workbook(...) w rozliczenia/sonda.py::first_address",
            "src/rozliczenia/sonda.py:4: workbook_files.file_bytes(...) w rozliczenia/sonda.py::first_address",
            "src/rozliczenia/sonda.py:7: opened(...) w rozliczenia/sonda.py::first_address_after_check",
            "src/rozliczenia/sonda.py:7: workbook_content(...) w rozliczenia/sonda.py::first_address_after_check",
            "src/rozliczenia/sonda.py:10: workbook_files.template_content(...) w rozliczenia/sonda.py::template_address",
            "src/rozliczenia/sonda.py:12: workbook_files.open_workbook(...) w rozliczenia/sonda.py::opened_values",
        ]
    )


def _patching_candidates() -> list[Path]:
    return sorted([*TESTS.rglob("*.py"), *ATRAPY.rglob("*.py")])


def test_sprawdzenie_latania_czyta_testy_i_atrapy() -> None:
    read = {path.relative_to(ROOT).as_posix() for path in _patching_candidates()}

    assert {"tests/test_jeden_odczyt_skoroszytu.py", "tools/lib/atrapy/workbooks.py"} <= read


def test_test_podstawia_bajty_plikow_taty_przez_zrodlo_uchwytu_a_nie_latajac_modul_skoroszytu() -> (
    None
):
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {text}"
        for path in _patching_candidates()
        for line, text in _patches(path.read_text(encoding="utf-8"))
    ]

    assert not found, "\n".join(
        [
            *found,
            "Bajty plików taty podstawiaj przez Surroundings(source=...) albo centrum_app(source=...) w teście Centrum, "
            "a w teście silnika przez RunContext(files=DadFiles(source=...)).",
        ]
    )


def test_sprawdzenie_latania_zglasza_latanie_w_atrapie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Łatanie modułu skoroszytu w atrapie obok pustego katalogu testów: strażnik je zgłasza, więc czyta atrapy, a nie
    tylko ``tests/`` (przegląd #1170 r2, Drobne 1)."""

    atrapy = tmp_path / "tools" / "lib" / "atrapy"
    atrapy.mkdir(parents=True)
    (atrapy / "naruszenie.py").write_text(
        'from unittest import mock\nmock.patch("rozliczenia.workbook_files.file_bytes", lambda path: b"")\n', encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    module = sys.modules[__name__]
    for name, path in (("ROOT", tmp_path), ("TESTS", tmp_path / "tests"), ("ATRAPY", atrapy)):
        monkeypatch.setattr(module, name, path)

    with pytest.raises(AssertionError) as raised:
        test_test_podstawia_bajty_plikow_taty_przez_zrodlo_uchwytu_a_nie_latajac_modul_skoroszytu()

    assert "tools/lib/atrapy/naruszenie.py:2: mock.patch(" in str(raised.value)


def test_latanie_modulu_skoroszytu_przez_alias_napis_i_mock_wywraca_straznika_a_inny_modul_nie() -> (
    None
):
    test = (
        "import sys\n"
        "from unittest import mock\n"
        "import rozliczenia.workbook_files as skoroszyty\n"
        "import rozliczenia.workbook_files\n"
        "from rozliczenia import input_checks, workbook_files as wf\n"
        "from rozliczenia.workbook_files import file_bytes as wf_bytes\n"
        "def test_lata(monkeypatch):\n"
        "    monkeypatch.setattr(wf, 'file_bytes', lambda path: b'')\n"
        "    monkeypatch.setattr(skoroszyty, 'file_bytes', lambda path: b'')\n"
        "    monkeypatch.delattr(rozliczenia.workbook_files, 'file_bytes')\n"
        "    monkeypatch.setattr('rozliczenia.workbook_files.file_bytes', lambda path: b'')\n"
        "    setattr(wf, 'file_bytes', None)\n"
        "    with mock.patch.object(wf, 'ensure_available'), mock.patch('rozliczenia.workbook_files.file_bytes'):\n"
        "        pass\n"
        "    with mock.patch.multiple(target=wf, file_bytes=None):\n"
        "        pass\n"
        "    monkeypatch.setattr(input_checks, 'ProcessTemplate', None)\n"
        "    monkeypatch.setattr(wf_bytes, '__doc__', '')\n"
        "    mock.patch.object(sys, 'stdin')\n"
        "    mock.patch('rozliczenia.input_checks.check_preparation')\n"
    )

    assert sorted(line for line, _ in _patches(test)) == [8, 9, 10, 11, 12, 13, 13, 15]
