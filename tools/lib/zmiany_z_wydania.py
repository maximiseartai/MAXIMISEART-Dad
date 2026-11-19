from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
import copy
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any, Final

import potomne
import repo

if TYPE_CHECKING:
    from rozliczenia.centrum.settings.proposal import ReleaseChange

MODUL_ZMIAN: Final = "src/rozliczenia/centrum/settings/release_changes.py"
NOWY_WPIS: Final = (
    "u taty ta Zmiana z Wydania już weszła i właściciel Ustawień ma jej id w pamięci, więc zmieniona nie pobiegnie "
    "drugi raz: przywróć ją taką, jaka jest w tagu Wydania, i dopisz do RELEASE_CHANGES "
    "(rozliczenia.centrum.settings.release_changes) nowy ReleaseChange z nowym id obok wpisów tego samego pliku"
)
_LIMIT_ODCZYTU_S: Final = 120


@dataclass(frozen=True)
class Wpis:
    plik: str
    odcisk: str


def _bez_docstringu(node: ast.AST) -> ast.AST:
    node = copy.deepcopy(node)
    for owner in ast.walk(node):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        first = owner.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            owner.body = owner.body[1:] or [ast.Pass()]
    return node


def odcisk(path: Path, name: str) -> str:
    definitions: dict[str, ast.stmt] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
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
        waiting += [node.id for node in ast.walk(definitions[current]) if isinstance(node, ast.Name)]
    unparsed = "\n".join(ast.unparse(_bez_docstringu(definitions[current])) for current in sorted(seen))
    return hashlib.sha256(unparsed.encode()).hexdigest()[:16]


def wpisy(zmiany: Iterable[ReleaseChange[Any]]) -> dict[str, Wpis]:
    return {
        zmiana.id: Wpis(zmiana.file.name, odcisk(Path(inspect.getfile(sys.modules[zmiana.propose.__module__])), zmiana.propose.__name__))
        for zmiana in zmiany
    }


def wpisy_commitu(root: Path, commit: str) -> dict[str, Wpis]:
    if repo.blob(root, commit, MODUL_ZMIAN) is None:
        return {}
    with tempfile.TemporaryDirectory() as katalog:
        archiwum = Path(katalog, "src.tar")
        spakowanie = repo.run_git(root, "archive", f"--output={archiwum}", commit, "src", timeout=_LIMIT_ODCZYTU_S)
        if spakowanie.returncode:
            raise ValueError(f"git archive {commit}: {spakowanie.stderr.strip()}")
        with tarfile.open(archiwum) as spakowane:
            spakowane.extractall(katalog, filter="data")
        srodowisko = {**os.environ, "PYTHONPATH": str(Path(katalog, "src"))}
        odczyt = potomne.run([sys.executable, __file__], cwd=Path(katalog), env=srodowisko, timeout=_LIMIT_ODCZYTU_S)
    if odczyt.returncode:
        raise ValueError(f"Zmian z Wydania z commitu {commit} nie da się odczytać: {odczyt.stderr.strip()}")
    return {id_zmiany: Wpis(*pola) for id_zmiany, pola in json.loads(odczyt.stdout).items()}


def zmienione(root: Path, wydania: Sequence[tuple[str, str]], commit: str) -> list[str]:
    teraz = wpisy_commitu(root, commit)
    zmienione: dict[str, str] = {}
    for tag, wydany in wydania:
        for id_zmiany, wpis in wpisy_commitu(root, wydany).items():
            nowy = teraz.get(id_zmiany)
            if id_zmiany in zmienione or nowy == wpis:
                continue
            if nowy is None:
                zmienione[id_zmiany] = f"{id_zmiany} z {tag} zniknęła"
            elif nowy.plik != wpis.plik:
                zmienione[id_zmiany] = f"{id_zmiany} z {tag} zmienia {nowy.plik} zamiast {wpis.plik}"
            else:
                zmienione[id_zmiany] = f"{id_zmiany} z {tag} ma inny kod (odcisk {nowy.odcisk} zamiast {wpis.odcisk})"
    return list(zmienione.values())


def _wypisz_wpisy() -> None:
    from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES

    print(json.dumps({id_zmiany: [wpis.plik, wpis.odcisk] for id_zmiany, wpis in wpisy(RELEASE_CHANGES).items()}))


if __name__ == "__main__":
    _wypisz_wpisy()
