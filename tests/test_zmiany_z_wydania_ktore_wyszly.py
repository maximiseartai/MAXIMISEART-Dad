from __future__ import annotations

import ast
import copy
import hashlib
import inspect
from pathlib import Path
import sys
from typing import Any, Final

import pytest

from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.proposal import ReleaseChange
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE

from tests.fixtures.skladnia import drzewo, wezly

WYDANE: Final[dict[str, tuple[str, str, str]]] = {
    "2026-11-lista-wykonawcow": ("0.10.0", WORKERS_FILE, "c469fcf617a2ba00"),
    "2026-11-folder-okresow-od-zalacznikow": ("0.10.0", SETTINGS_FILE, "54784b00870283c2"),
    "2026-11-przypomnienia": ("0.10.0", REMINDERS_FILE, "0a59d2c0f4842677"),
}

NOWY_WPIS: Final = (
    "u taty ta Zmiana z Wydania już weszła i właściciel Ustawień ma jej id w pamięci, więc zmieniona nie pobiegnie "
    "drugi raz: zostaw ją bez zmian i dopisz do RELEASE_CHANGES (rozliczenia.centrum.settings.release_changes) nowy "
    "ReleaseChange z nowym id obok wpisów tego samego pliku"
)


def _bez_docstringu(node: ast.AST) -> ast.AST:
    node = copy.deepcopy(node)
    for owner in wezly(node):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        first = owner.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            owner.body = owner.body[1:] or [ast.Pass()]
    return node


def odcisk(path: Path, name: str) -> str:
    definitions: dict[str, ast.stmt] = {}
    for node in drzewo(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            definitions.update({target.id: node for target in targets if isinstance(target, ast.Name)})
    seen: set[str] = set()
    waiting = [name]
    while waiting:
        current = waiting.pop()
        if current in seen or current not in definitions:
            continue
        seen.add(current)
        waiting += [node.id for node in wezly(definitions[current]) if isinstance(node, ast.Name)]
    unparsed = "\n".join(ast.unparse(_bez_docstringu(definitions[current])) for current in sorted(seen))
    return hashlib.sha256(unparsed.encode()).hexdigest()[:16]


def _odcisk_zmiany(change: ReleaseChange[Any]) -> str:
    propose = change.propose
    return odcisk(Path(inspect.getfile(sys.modules[propose.__module__])), propose.__name__)


@pytest.mark.parametrize("id_zmiany", list(WYDANE))
def test_zmiana_z_wydania_ktore_wyszlo_zostaje_bez_zmian_bo_tata_ma_jej_id_w_pamieci(id_zmiany: str) -> None:
    wersja, plik, skrot = WYDANE[id_zmiany]
    zmiany = {change.id: change for change in RELEASE_CHANGES}

    assert id_zmiany in zmiany, f"zniknęła Zmiana z Wydania {id_zmiany} z {wersja}: {NOWY_WPIS}"
    assert zmiany[id_zmiany].file.name == plik, f"Zmiana z Wydania {id_zmiany} z {wersja} zmienia inny plik: {NOWY_WPIS}"
    assert _odcisk_zmiany(zmiany[id_zmiany]) == skrot, f"zmieniona Zmiana z Wydania {id_zmiany} z {wersja}: {NOWY_WPIS}"


ZNANE_LUKI_ODCISKU: Final = {
    "funkcja modułu, po którą wpis sięga napisem z nazwą": (
        {"zmiana.py": "import sys\n\ndef _d(x):\n    return 1\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n"},
        {"zmiana.py": "import sys\n\ndef _d(x):\n    return 2\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n"},
    ),
    "metoda, po którą wpis sięga atrybutem obiektu": (
        {"zmiana.py": "class K:\n    def f(self):\n        return 1\n\ndef propose(inputs):\n    return inputs.f()\n"},
        {"zmiana.py": "class K:\n    def f(self):\n        return 2\n\ndef propose(inputs):\n    return inputs.f()\n"},
    ),
    "funkcja z innego modułu, którą wpis importuje": (
        {"zmiana.py": "from pomocnik import d\n\ndef propose(inputs):\n    return d(inputs)\n", "pomocnik.py": "def d(x):\n    return 1\n"},
        {"zmiana.py": "from pomocnik import d\n\ndef propose(inputs):\n    return d(inputs)\n", "pomocnik.py": "def d(x):\n    return 2\n"},
    ),
}


def _odcisk_plikow(katalog: Path, pliki: dict[str, str]) -> str:
    katalog.mkdir()
    for nazwa, tekst in pliki.items():
        (katalog / nazwa).write_text(tekst, encoding="utf-8")
    return odcisk(katalog / "zmiana.py", "propose")


@pytest.mark.parametrize("przed, po", list(ZNANE_LUKI_ODCISKU.values()), ids=list(ZNANE_LUKI_ODCISKU))
def test_znane_luki_odcisku_zmiany_z_wydania_daja_ten_sam_odcisk(tmp_path: Path, przed: dict[str, str], po: dict[str, str]) -> None:
    rowne = _odcisk_plikow(tmp_path / "przed", przed) == _odcisk_plikow(tmp_path / "po", po)

    assert rowne, "odcisk łapie już tę lukę: usuń próbkę z ZNANE_LUKI_ODCISKU"


def test_odcisk_zmiany_z_wydania_widzi_funkcje_i_stale_modulu_po_ktore_wpis_siega_nazwa_a_nie_docstring(tmp_path: Path) -> None:
    przed = 'LIMIT = 1\n\ndef _dzien(text):\n    """Dzień."""\n    return text[:LIMIT]\n\ndef propose(inputs):\n    return _dzien(inputs)\n'
    bazowy = _odcisk_plikow(tmp_path / "baza", {"zmiana.py": przed})

    assert _odcisk_plikow(tmp_path / "bez_docstringu", {"zmiana.py": przed.replace('"""Dzień."""\n    ', "")}) == bazowy
    assert _odcisk_plikow(tmp_path / "inna_funkcja", {"zmiana.py": przed.replace("text[:LIMIT]", "text[1:]")}) != bazowy
    assert _odcisk_plikow(tmp_path / "inna_stala", {"zmiana.py": przed.replace("LIMIT = 1", "LIMIT = 2")}) != bazowy
