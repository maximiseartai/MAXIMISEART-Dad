from __future__ import annotations

import ast
import builtins
from collections.abc import Iterable, Iterator, Mapping, Sequence
import copy
import dataclasses
import enum
import functools
import hashlib
import inspect
import itertools
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
    "drugi raz: przywróć ją taką, jaka jest w tagu Wydania, a to, co ma się jeszcze zmienić u taty, dopisz do "
    "RELEASE_CHANGES (rozliczenia.centrum.settings.release_changes) jako nowy ReleaseChange z nowym id obok wpisów "
    "tego samego pliku"
)
INNY_KOD: Final = (
    f"gdy to poprawka wpisu w miejscu albo wpis sięga teraz po inną definicję, {NOWY_WPIS}; gdy to nowa nazwa albo "
    "nowe miejsce definicji lub modułu spoza modułu propose, plik modułu propose przywróć taki, jaki jest w tagu, i "
    "wpisu nie przepinaj: odcisk zna je tylko po nazwie, pod którą moduł propose je wiąże, więc w kodzie, który "
    "zmieniłeś, zostaw starą nazwę do importu (alias stara = nowa w jej module, moduł pod starą ścieżką)"
)
GRANICA_ODCISKU: Final = (
    "odcisk Zmiany z Wydania bierze propose, które jest funkcją albo functools.partial, i to, po co sięga w biegu: "
    "funkcje i klasy modułu propose ze źródłem w pliku, dane (stała, krotka, lista, słownik, zbiór, Enum, dataclass) i "
    "nazwy, pod którymi moduł propose wiąże definicje i moduły spoza siebie; definicję albo moduł spoza modułu propose "
    "zwiąż w nim nazwą (import), a obiekt innej klasy, metodę obiektu, funkcję bez źródła w pliku albo pod "
    "functools.lru_cache i dwie lambdy w jednej linii zamień na funkcję modułu albo dataclass"
)
_STALE: Final = (bool, int, float, str, bytes)
_LIMIT_ODCZYTU_S: Final = 120


@dataclasses.dataclass(frozen=True)
class Wpis:
    plik: str
    odcisk: str
    drzewo: object = dataclasses.field(default=None, compare=False, repr=False)


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


def _importowana_nazwa(wezel: ast.Import | ast.ImportFrom, alias: ast.alias) -> str:
    if isinstance(wezel, ast.ImportFrom):
        return alias.name
    return alias.name.rpartition(".")[2] if alias.asname else alias.name.partition(".")[0]


def _importy_pod_inna_nazwa(drzewo: ast.Module) -> dict[str, str]:
    importy: list[ast.Import | ast.ImportFrom] = []
    czekajace: list[ast.AST] = list(drzewo.body)
    while czekajace:
        wezel = czekajace.pop()
        if isinstance(wezel, (ast.Import, ast.ImportFrom)):
            importy.append(wezel)
        elif not isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            czekajace += ast.iter_child_nodes(wezel)
    etykiety: dict[str, list[str]] = {}
    for wezel in sorted(importy, key=lambda wezel: (wezel.lineno, wezel.col_offset)):
        for alias in wezel.names:
            importowana = _importowana_nazwa(wezel, alias)
            wiazana = alias.asname or importowana
            etykieta = wiazana if importowana == wiazana else f"{importowana} as {wiazana}"
            if etykieta not in etykiety.setdefault(wiazana, []):
                etykiety[wiazana].append(etykieta)
    return {wiazana: ", ".join(nazwy) for wiazana, nazwy in etykiety.items() if nazwy != [wiazana]}


def _nazwy_wartosci(przestrzen: Mapping[str, object], importy: Mapping[str, str]) -> dict[int, list[str]]:
    nazwy: dict[int, list[str]] = {}
    for nazwa, wartosc in sorted(przestrzen.items()):
        nazwy.setdefault(id(wartosc), []).append(importy.get(nazwa, nazwa))
    return nazwy


class _Odcisk:
    def __init__(self, modul: str) -> None:
        self._modul = modul
        self._w_toku: set[int] = set()
        self._drzewa: dict[str, ast.Module] = {}
        przestrzen = vars(sys.modules[modul]) if modul in sys.modules else {}
        plik = przestrzen.get("__file__")
        importy = _importy_pod_inna_nazwa(self._drzewo_pliku(plik, modul)) if isinstance(plik, str) else {}
        wbudowane = {id(wartosc): [nazwa] for nazwa, wartosc in vars(builtins).items() if getattr(wartosc, "__name__", None) == nazwa}
        self._nazwy = wbudowane | _nazwy_wartosci(przestrzen, importy)

    def wartosc(self, wartosc: object) -> object:
        if wartosc is None or type(wartosc) in _STALE:
            return {"stała": repr(wartosc)}
        if type(wartosc) is tuple or type(wartosc) is list:
            return {type(wartosc).__name__: [self.wartosc(element) for element in wartosc]}
        if type(wartosc) is set or type(wartosc) is frozenset:
            return {type(wartosc).__name__: sorted(json.dumps(self.wartosc(element), ensure_ascii=False) for element in wartosc)}
        if type(wartosc) is dict:
            return {"dict": [[self.wartosc(klucz), self.wartosc(element)] for klucz, element in wartosc.items()]}
        if isinstance(wartosc, enum.Enum):
            return {"enum": self.definicja(type(wartosc)), "członek": wartosc.name}
        if dataclasses.is_dataclass(wartosc) and not isinstance(wartosc, type):
            pola = {pole.name: self.wartosc(getattr(wartosc, pole.name)) for pole in dataclasses.fields(wartosc)}
            return {"dataclass": self.definicja(type(wartosc)), "pola": pola}
        if type(wartosc) is functools.partial:
            return {"partial": self.wartosc(wartosc.func), "argumenty": self.wartosc(wartosc.args), "nazwane": self.wartosc(wartosc.keywords)}
        if isinstance(wartosc, ModuleType):
            return {"moduł": self.definicja(wartosc)}
        if isinstance(wartosc, UnionType):
            return {"unia": [self.wartosc(typ) for typ in wartosc.__args__]}
        if isinstance(getattr(wartosc, "__qualname__", None), str) and isinstance(getattr(wartosc, "__module__", None), str):
            return self.definicja(wartosc)
        raise ValueError(f"obiekt {type(wartosc).__module__}.{type(wartosc).__qualname__}: {GRANICA_ODCISKU}")

    def definicja(self, definicja: Any) -> object:
        if isinstance(definicja, ModuleType) or definicja.__module__ != self._modul:
            if id(definicja) in self._nazwy:
                return {"nazwa w module propose": " = ".join(self._nazwy[id(definicja)])}
            opis = definicja.__name__ if isinstance(definicja, ModuleType) else f"{definicja.__module__}.{definicja.__qualname__}"
            raise ValueError(f"{opis} spoza modułu {self._modul}, który nie wiąże go nazwą: {GRANICA_ODCISKU}")
        if id(definicja) in self._w_toku:
            return {"w toku": definicja.__qualname__}
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
        return {
            "funkcja": ast.unparse(self._zrodlo(kod.co_filename, kod.co_name, kod.co_firstlineno, kod.co_qualname)),
            "domyślne": self.wartosc(funkcja.__defaults__),
            "domyślne nazwane": self.wartosc(funkcja.__kwdefaults__),
            "domknięcie": {nazwa: self.wartosc(komorka.cell_contents) for nazwa, komorka in zip(kod.co_freevars, funkcja.__closure__ or (), strict=True)},
            "nazwy": {nazwa: self.wartosc(funkcja.__globals__[nazwa]) for nazwa in sorted(_nazwy_kodu(kod)) if nazwa in funkcja.__globals__},
            "atrybuty": {nazwa: self.wartosc(atrybut) for nazwa, atrybut in sorted(vars(funkcja).items())},
        }

    def _klasa(self, klasa: type) -> object:
        try:
            plik = inspect.getfile(klasa)
        except TypeError as blad:
            raise ValueError(f"{klasa.__module__}.{klasa.__qualname__} bez pliku źródła: {GRANICA_ODCISKU}") from blad
        zrodlo = self._zrodlo(plik, klasa.__name__, getattr(klasa, "__firstlineno__", -1), klasa.__qualname__)
        assert isinstance(zrodlo, ast.ClassDef)
        modul = vars(sys.modules[klasa.__module__])
        metody_systemowe = {
            nazwa: [
                self.definicja(funkcja)
                for funkcja in _funkcje_czlonka(czlonek)
                if funkcja.__code__.co_filename == plik
                and any(_poczatek(wezel, funkcja.__code__.co_name, funkcja.__code__.co_firstlineno) for wezel in ast.walk(zrodlo))
            ]
            for nazwa, czlonek in sorted(vars(klasa).items())
            if _systemowa(nazwa)
        }
        return {
            "klasa": ast.unparse(zrodlo),
            "nazwy": {nazwa: self.wartosc(modul[nazwa]) for nazwa in sorted(_nazwy_ciala_klasy(zrodlo)) if nazwa in modul},
            "członki": {nazwa: self.wartosc(_bez_opakowania(czlonek)) for nazwa, czlonek in sorted(vars(klasa).items()) if not _systemowa(nazwa)},
            "metody systemowe": {nazwa: metody for nazwa, metody in metody_systemowe.items() if metody},
        }

    def _drzewo_pliku(self, plik: str, opis: str) -> ast.Module:
        if plik not in self._drzewa:
            try:
                self._drzewa[plik] = ast.parse(Path(plik).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError) as blad:
                raise ValueError(f"{opis}: nie ma źródła w pliku {plik} ({blad}): {GRANICA_ODCISKU}") from blad
        return self._drzewa[plik]

    def _zrodlo(self, plik: str, nazwa: str, linia: int, opis: str) -> ast.AST:
        trafione = [wezel for wezel in ast.walk(self._drzewo_pliku(plik, opis)) if _poczatek(wezel, nazwa, linia)]
        if len(trafione) != 1:
            raise ValueError(f"{opis}: {len(trafione)} definicji {nazwa} od linii {linia} w {plik}: {GRANICA_ODCISKU}")
        return _bez_docstringow(trafione[0])


def _drzewo(propose: object) -> object:
    korzen = propose
    while type(korzen) is functools.partial:
        korzen = korzen.func
    if not isinstance(korzen, FunctionType):
        raise ValueError(f"propose to {type(propose).__module__}.{type(propose).__qualname__}: {GRANICA_ODCISKU}")
    return _Odcisk(korzen.__module__).wartosc(propose)


def _wpis(plik: str, drzewo_odcisku: object) -> Wpis:
    zrzut = json.dumps(drzewo_odcisku, ensure_ascii=False)
    return Wpis(plik, hashlib.sha256(zrzut.encode()).hexdigest()[:16], drzewo_odcisku)


def wpisy(zmiany: Iterable[ReleaseChange[Any]]) -> dict[str, Wpis]:
    return {zmiana.id: _wpis(zmiana.file.name, _drzewo(zmiana.propose)) for zmiana in zmiany}


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
    return {id_zmiany: _wpis(plik, drzewo_odcisku) for id_zmiany, (plik, drzewo_odcisku) in json.loads(odczyt.stdout).items()}


def zmienione(root: Path, wydania: Sequence[tuple[str, str]], commit: str) -> list[str]:
    teraz = wpisy_commitu(root, commit)
    zmienione: dict[str, str] = {}
    for tag, wydany in wydania:
        for id_zmiany, roznica in roznice(wpisy_commitu(root, wydany), teraz, tag).items():
            zmienione.setdefault(id_zmiany, roznica)
    return list(zmienione.values())


def roznice(wtedy: Mapping[str, Wpis], teraz: Mapping[str, Wpis], skad: str) -> dict[str, str]:
    return {id_zmiany: f"{id_zmiany} z {skad} {_roznica(wpis, teraz.get(id_zmiany))}" for id_zmiany, wpis in wtedy.items() if teraz.get(id_zmiany) != wpis}


def _roznica(wtedy: Wpis, teraz: Wpis | None) -> str:
    if teraz is None:
        return f"zniknęła: {NOWY_WPIS}"
    if teraz.plik != wtedy.plik:
        return f"zmienia {teraz.plik} zamiast {wtedy.plik}: {NOWY_WPIS}"
    for (miejsce_wtedy, lisc_wtedy), (miejsce, lisc) in itertools.zip_longest(_liscie(wtedy.drzewo, ("propose",)), _liscie(teraz.drzewo, ("propose",)), fillvalue=((), None)):
        if miejsce != miejsce_wtedy:
            return f"ma inny kod: {' › '.join(miejsce) or 'nic'} zamiast {' › '.join(miejsce_wtedy) or 'nic'}; {INNY_KOD}"
        if lisc != lisc_wtedy:
            linia_wtedy, linia = _pierwsza_rozna_linia(lisc_wtedy, lisc)
            return f"ma inny kod w {' › '.join(miejsce)} („{linia}” zamiast „{linia_wtedy}”); {INNY_KOD}"
    return f"ma inny odcisk ({teraz.odcisk} zamiast {wtedy.odcisk}); {INNY_KOD}"


def _liscie(wezel: object, miejsce: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], object]]:
    if isinstance(wezel, dict):
        for klucz, wartosc in wezel.items():
            yield from _liscie(wartosc, (*miejsce, klucz))
    elif isinstance(wezel, list):
        for numer, wartosc in enumerate(wezel):
            yield from _liscie(wartosc, (*miejsce, str(numer)))
    else:
        yield miejsce, wezel


def _pierwsza_rozna_linia(wtedy: object, teraz: object) -> tuple[str, str]:
    linie = itertools.zip_longest(str(wtedy).splitlines(), str(teraz).splitlines(), fillvalue="")
    return next(((linia_wtedy.strip(), linia.strip()) for linia_wtedy, linia in linie if linia_wtedy != linia), (str(wtedy), str(teraz)))


def _wypisz_wpisy() -> None:
    from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES

    print(json.dumps({id_zmiany: [wpis.plik, wpis.drzewo] for id_zmiany, wpis in wpisy(RELEASE_CHANGES).items()}))


if __name__ == "__main__":
    _wypisz_wpisy()
