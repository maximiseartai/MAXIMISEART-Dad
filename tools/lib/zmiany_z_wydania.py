from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence
import copy
import dataclasses
import enum
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import CodeType, FunctionType, ModuleType, UnionType
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
GRANICA_ODCISKU: Final = (
    "odcisk Zmiany z Wydania bierze propose, które jest funkcją albo functools.partial, i to, po co sięga w biegu: "
    "funkcje i klasy modułu propose ze źródłem w pliku, dane (stała, krotka, lista, słownik, zbiór, Enum, dataclass) i "
    "nazwy definicji innych modułów; obiekt innej klasy, metodę obiektu, funkcję bez źródła w pliku albo pod "
    "functools.lru_cache i dwie lambdy w jednej linii zamień na funkcję modułu albo dataclass"
)
_STALE: Final = (bool, int, float, str, bytes)
_LIMIT_ODCZYTU_S: Final = 120


@dataclasses.dataclass(frozen=True)
class Wpis:
    plik: str
    odcisk: str


def _nazwy_kodu(kod: CodeType) -> set[str]:
    return set(kod.co_names).union(*(_nazwy_kodu(stala) for stala in kod.co_consts if isinstance(stala, CodeType)))


def _nazwy_ciala_klasy(klasa: ast.ClassDef) -> set[str]:
    nazwy: set[str] = set()
    czekajace: list[ast.AST] = [*klasa.bases, *klasa.keywords, *klasa.decorator_list, *klasa.body]
    while czekajace:
        wezel = czekajace.pop()
        if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef)):
            czekajace += wezel.decorator_list
        elif isinstance(wezel, ast.AnnAssign):
            czekajace += [wezel.target, *([wezel.value] if wezel.value else [])]
        elif isinstance(wezel, ast.Name):
            nazwy.add(wezel.id)
        else:
            czekajace += ast.iter_child_nodes(wezel)
    return nazwy


def _bez_docstringow(wezel: ast.AST) -> ast.AST:
    wezel = copy.deepcopy(wezel)
    for wlasciciel in ast.walk(wezel):
        for pole in ("body", "orelse", "finalbody"):
            instrukcje = getattr(wlasciciel, pole, None)
            if isinstance(instrukcje, list) and instrukcje and isinstance(instrukcje[0], ast.stmt):
                zostaja = [
                    instrukcja
                    for instrukcja in instrukcje
                    if not (isinstance(instrukcja, ast.Expr) and isinstance(instrukcja.value, ast.Constant) and isinstance(instrukcja.value.value, str))
                ]
                setattr(wlasciciel, pole, zostaja or [ast.Pass()])
    return wezel


def _poczatek(wezel: ast.AST, nazwa: str, linia: int) -> bool:
    if isinstance(wezel, ast.Lambda):
        return nazwa == "<lambda>" and wezel.lineno == linia
    if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return wezel.name == nazwa and min([wezel.lineno, *(dekorator.lineno for dekorator in wezel.decorator_list)]) == linia
    return False


def _bez_opakowania(czlonek: object) -> object:
    if isinstance(czlonek, (staticmethod, classmethod)):
        return czlonek.__func__
    if isinstance(czlonek, property):
        return (czlonek.fget, czlonek.fset, czlonek.fdel)
    return czlonek


def _funkcje_czlonka(czlonek: object) -> Iterator[FunctionType]:
    rozpakowany = _bez_opakowania(czlonek)
    yield from (funkcja for funkcja in (rozpakowany if isinstance(rozpakowany, tuple) else (rozpakowany,)) if isinstance(funkcja, FunctionType))


def _systemowa(nazwa: str) -> bool:
    return len(nazwa) > 2 and nazwa.startswith("_") and nazwa.endswith("_")


class _Odcisk:
    def __init__(self, modul: str) -> None:
        self._modul = modul
        self._w_toku: set[int] = set()
        self._drzewa: dict[str, ast.Module] = {}

    def wartosc(self, wartosc: object) -> object:
        if wartosc is None or type(wartosc) in _STALE:
            return ["stała", repr(wartosc)]
        if type(wartosc) is tuple or type(wartosc) is list:
            return [type(wartosc).__name__, [self.wartosc(element) for element in wartosc]]
        if type(wartosc) is set or type(wartosc) is frozenset:
            return [type(wartosc).__name__, sorted(json.dumps(self.wartosc(element), ensure_ascii=False) for element in wartosc)]
        if type(wartosc) is dict:
            return ["dict", [[self.wartosc(klucz), self.wartosc(element)] for klucz, element in wartosc.items()]]
        if isinstance(wartosc, enum.Enum):
            return ["enum", self.definicja(type(wartosc)), wartosc.name]
        if dataclasses.is_dataclass(wartosc) and not isinstance(wartosc, type):
            pola = [[pole.name, self.wartosc(getattr(wartosc, pole.name))] for pole in dataclasses.fields(wartosc)]
            return ["dataclass", self.definicja(type(wartosc)), pola]
        if type(wartosc) is functools.partial:
            return ["partial", self.wartosc(wartosc.func), self.wartosc(wartosc.args), self.wartosc(wartosc.keywords)]
        if isinstance(wartosc, ModuleType):
            return ["moduł", wartosc.__name__]
        if isinstance(wartosc, UnionType):
            return ["unia", [self.wartosc(typ) for typ in wartosc.__args__]]
        if isinstance(getattr(wartosc, "__qualname__", None), str) and isinstance(getattr(wartosc, "__module__", None), str):
            return self.definicja(wartosc)
        raise ValueError(f"obiekt {type(wartosc).__module__}.{type(wartosc).__qualname__}: {GRANICA_ODCISKU}")

    def definicja(self, definicja: Any) -> object:
        if definicja.__module__ != self._modul:
            return ["odwołanie", definicja.__module__, definicja.__qualname__]
        if id(definicja) in self._w_toku:
            return ["w toku", definicja.__qualname__]
        self._w_toku.add(id(definicja))
        try:
            if isinstance(definicja, FunctionType):
                return self._funkcja(definicja)
            if isinstance(definicja, type):
                return self._klasa(definicja)
        finally:
            self._w_toku.discard(id(definicja))
        raise ValueError(f"{definicja.__module__}.{definicja.__qualname__} to {type(definicja).__qualname__}: {GRANICA_ODCISKU}")

    def _funkcja(self, funkcja: FunctionType) -> object:
        kod = funkcja.__code__
        domkniecie = [[nazwa, self.wartosc(komorka.cell_contents)] for nazwa, komorka in zip(kod.co_freevars, funkcja.__closure__ or (), strict=True)]
        globalne = [[nazwa, self.wartosc(funkcja.__globals__[nazwa])] for nazwa in sorted(_nazwy_kodu(kod)) if nazwa in funkcja.__globals__]
        zrodlo = self._zrodlo(kod.co_filename, kod.co_name, kod.co_firstlineno, kod.co_qualname)
        atrybuty = [[nazwa, self.wartosc(atrybut)] for nazwa, atrybut in sorted(vars(funkcja).items())]
        domyslne = [self.wartosc(funkcja.__defaults__), self.wartosc(funkcja.__kwdefaults__)]
        return ["funkcja", ast.unparse(zrodlo), domyslne, domkniecie, globalne, atrybuty]

    def _klasa(self, klasa: type) -> object:
        try:
            plik = inspect.getfile(klasa)
        except TypeError as blad:
            raise ValueError(f"{klasa.__module__}.{klasa.__qualname__} bez pliku źródła: {GRANICA_ODCISKU}") from blad
        zrodlo = self._zrodlo(plik, klasa.__name__, getattr(klasa, "__firstlineno__", -1), klasa.__qualname__)
        assert isinstance(zrodlo, ast.ClassDef)
        modul = vars(sys.modules[klasa.__module__])
        globalne = [[nazwa, self.wartosc(modul[nazwa])] for nazwa in sorted(_nazwy_ciala_klasy(zrodlo)) if nazwa in modul]
        czlonki = [[nazwa, self.wartosc(_bez_opakowania(czlonek))] for nazwa, czlonek in sorted(vars(klasa).items()) if not _systemowa(nazwa)]
        metody_systemowe = [
            [nazwa, self.definicja(funkcja)]
            for nazwa, czlonek in sorted(vars(klasa).items())
            if _systemowa(nazwa)
            for funkcja in _funkcje_czlonka(czlonek)
            if funkcja.__code__.co_filename == plik
            and any(_poczatek(wezel, funkcja.__code__.co_name, funkcja.__code__.co_firstlineno) for wezel in ast.walk(zrodlo))
        ]
        return ["klasa", ast.unparse(zrodlo), globalne, czlonki, metody_systemowe]

    def _zrodlo(self, plik: str, nazwa: str, linia: int, opis: str) -> ast.AST:
        if plik not in self._drzewa:
            try:
                self._drzewa[plik] = ast.parse(Path(plik).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError) as blad:
                raise ValueError(f"{opis}: nie ma źródła w pliku {plik} ({blad}): {GRANICA_ODCISKU}") from blad
        trafione = [wezel for wezel in ast.walk(self._drzewa[plik]) if _poczatek(wezel, nazwa, linia)]
        if len(trafione) != 1:
            raise ValueError(f"{opis}: {len(trafione)} definicji {nazwa} od linii {linia} w {plik}: {GRANICA_ODCISKU}")
        return _bez_docstringow(trafione[0])


def odcisk(propose: object) -> str:
    korzen = propose
    while type(korzen) is functools.partial:
        korzen = korzen.func
    if not isinstance(korzen, FunctionType):
        raise ValueError(f"propose to {type(propose).__module__}.{type(propose).__qualname__}: {GRANICA_ODCISKU}")
    zrzut = json.dumps(_Odcisk(korzen.__module__).wartosc(propose), ensure_ascii=False)
    return hashlib.sha256(zrzut.encode()).hexdigest()[:16]


def wpisy(zmiany: Iterable[ReleaseChange[Any]]) -> dict[str, Wpis]:
    return {zmiana.id: Wpis(zmiana.file.name, odcisk(zmiana.propose)) for zmiana in zmiany}


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
