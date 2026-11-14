"""Import modułu w trakcie działania poza ``tests/``: po nazwie (``modul``), z pliku (``modul_z_pliku``) i pytanie,
czy moduł jest (``jest_modul``).

Kod spoza ``tests/`` nie importuje kodu testów (``tests/test_granice_importow.py``), więc ``modul`` i ``modul_z_pliku``
odmawiają w biegu (``OdmowaImportuTestow``), zanim wykonają kod, modułu, którego plik albo katalog pakietu leży w
katalogu ``tests/`` repozytorium, pod każdą nazwą i także przez dowiązanie symboliczne. Reszta kodu poza ``tests/`` bierze import
w trakcie działania tylko stąd: ruff ``TID251`` odrzuca tam pakiet ``importlib`` (poza ``IMPORTLIB_DOZWOLONE``) i moduły,
których zadaniem jest import albo wykonanie modułu (``builtins.__import__``, ``_frozen_importlib``,
``_frozen_importlib_external``, ``_imp``, ``runpy``, ``pkgutil``, ``zipimport``), z komunikatem, który kieruje do tego
modułu, a ten moduł ma prawo właściciela (``per-file-ignores`` w ``pyproject.toml``). Inne moduły biblioteki standardowej,
które przy okazji wykonują plik albo importują po nazwie, kod w napisie, funkcje wbudowane bez importu i osobny proces
są znaną luką z próbkami ``ZNANE_LUKI_IMPORTU`` w ``tests/test_zakazy_ruff.py``, nie pełną listą.
"""

from __future__ import annotations

from collections.abc import Sequence
import importlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from types import ModuleType

_TESTY = Path(__file__).resolve().parents[2] / "tests"


class OdmowaImportuTestow(ValueError):
    """Kod spoza ``tests/`` chciał wykonać moduł z ``tests/``; nie ``ImportError``, żeby zapasowa ścieżka
    ``except ImportError`` jej nie połknęła."""


def _w_testach(miejsce: Path) -> bool:
    """Czy ``miejsce`` leży w ``tests/`` repozytorium: porównanie katalogów jak system plików (``samefile``), więc także
    przez dowiązanie i w innej wielkości liter na Macu i Windows."""
    for katalog in (miejsce, *miejsce.parents):
        try:
            if os.path.samefile(katalog, _TESTY):
                return True
        except OSError:
            continue
    return False


def _odmow_testow(nazwa: str, miejsca: Sequence[str]) -> None:
    if any(_w_testach(Path(miejsce).resolve()) for miejsce in miejsca):
        raise OdmowaImportuTestow(f"kod spoza tests/ nie importuje kodu testów: {nazwa} leży w {_TESTY}")


def modul(nazwa: str) -> ModuleType:
    """Moduł o nazwie ``nazwa`` (bezwzględnej), zaimportowany jak ``importlib.import_module``. Każdy człon nazwy
    (``a``, ``a.b``…) ma przed wykonaniem swojego kodu sprawdzone miejsce, bo import ``a.b`` wykonuje najpierw ``a``."""
    czlony = nazwa.split(".")
    for koniec in range(1, len(czlony) + 1):
        czesc = ".".join(czlony[:koniec])
        spec = importlib.util.find_spec(czesc)
        if spec is not None:
            _odmow_testow(czesc, [*([spec.origin] if spec.has_location and spec.origin else []), *(spec.submodule_search_locations or [])])
    return importlib.import_module(nazwa)


def modul_z_pliku(nazwa: str, plik: Path) -> ModuleType:
    """Moduł wykonany z pliku ``plik`` pod nazwą ``nazwa``, bez wpisu w ``sys.modules``."""
    _odmow_testow(nazwa, [str(plik)])
    spec = importlib.util.spec_from_file_location(nazwa, plik)
    if spec is None or spec.loader is None:
        raise ImportError(f"nie da się wczytać {plik}")
    wczytany = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wczytany)
    return wczytany


def jest_modul(nazwa: str, sciezki: Sequence[str] | None = None) -> bool:
    """Czy moduł najwyższego poziomu ``nazwa`` jest w ``sciezki`` (bez nich w ``sys.path``); nie wykonuje kodu modułu."""
    return importlib.machinery.PathFinder.find_spec(nazwa, None if sciezki is None else list(sciezki)) is not None
