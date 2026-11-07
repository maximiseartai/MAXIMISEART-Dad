"""Niestabilne testy (ADR 0020): ponowienie testu, który padł w bramce PR, zapis flaky testu i zapis testów z kwarantanny.

Zadanie pytest (``tools/ci/wykonaj_zadanie.py``) zapisuje dwa pliki, a dwa narzędzia je czytają z artefaktów runu:

- ``FlakyTest``: test, który w zadaniu pytest bramki padł, a po jednym ponowieniu przeszedł. Lista trafia do
  ``FLAKY_TESTY`` (artefakt ``flaky-testy-<zadanie>-<próba>``), a ``tools/ci/zgloszenia_ci.py`` zakłada z niej issue
  ``Flaky test: <test>``.
- ``ZapisKwarantanny``: wynik każdego testu z kwarantanny, który biegł w zadaniu (artefakt ``kwarantanna-<zadanie>-<próba>``
  na pushu do `main`). Test z kwarantanny ma w junit własność ``WLASNOSC`` (``tests/conftest.py``). ``stan_kwarantanny``
  mówi ``tools/wydanie.py``, czy na commicie testy z kwarantanny przeszły.

Id testu to id pytest (``tests/test_x.py::Klasa::test_y[parametry]``), odtworzone z junit (``junit_family = "xunit1"``):
plik z atrybutu ``file``, klasy z ``classname`` za modułem tego pliku i nazwa z parametrami z ``name``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Literal
from xml.etree import ElementTree

FLAKY_TESTY = Path(".ci-niestabilne", "flaky-testy.json")
# Początek nazwy artefaktu z ``FLAKY_TESTY`` i z ``KWARANTANNA`` każdego zadania pytest w ``ci.yml``.
ARTEFAKT_FLAKY_TESTOW = "flaky-testy-"
# Plik ze słownikiem ``KWARANTANNA`` (ścieżka w repozytorium, jak ją podaje ``git show <commit>:<ścieżka>``).
PLIK_KWARANTANNY = "tests/fixtures/kwarantanna.py"
KWARANTANNA = Path(".ci-niestabilne", "kwarantanna.json")
ARTEFAKT_KWARANTANNY = "kwarantanna-"
# Id testu, które bramka ponawia, a zgłoszenia przepisują do issue: plik pod ``tests/`` bez ``..``, nazwy i parametry
# w jednej linii. Parametry pytest escapuje (``\u017c``), ale mogą mieć nawiasy, cudzysłowy, ``;``, ``@`` i backticki,
# więc treść issue podaje id tylko w bloku kodu.
ID_TESTU = re.compile(r"tests/[\w/]+\.py(?:::\w+)+(?:\[.*\])?")
# Własność junit testu z kwarantanny (``tests/conftest.py``), z powodem kwarantanny jako wartością.
WLASNOSC = "kwarantanna"

Wynik = Literal["przeszedł", "padł", "pominięty"]
StanKwarantanny = Literal["przeszła", "padła", "bez zapisu"]


@dataclass(frozen=True)
class FlakyTest:
    test: str
    zadanie: str  # nazwa zadania w runie
    sha: str
    run: int
    proba: int


@dataclass(frozen=True)
class ZapisKwarantanny:
    zadanie: str  # id zadania planu
    proba: int
    sha: str
    wyniki: Mapping[str, Wynik]  # testy z kwarantanny, które biegły w zadaniu


def zapisz_flaky_testy(flaky_testy: Sequence[FlakyTest], plik: Path = FLAKY_TESTY) -> None:
    plik.parent.mkdir(parents=True, exist_ok=True)
    plik.write_text(json.dumps([asdict(flaky) for flaky in flaky_testy], indent=1, ensure_ascii=False), encoding="utf-8")


def zgloszalny(test: str) -> bool:
    """Czy id testu da się zgłosić w issue; bramka ponawia tylko takie, więc każde przejście po ponowieniu ma issue."""

    return test.isprintable() and ID_TESTU.fullmatch(test) is not None


def flaky_testy_z_json(tekst: str) -> tuple[list[FlakyTest], list[str]]:
    """Flaky testy z artefaktu i powód odrzucenia każdego wpisu, którego kształt albo id testu się nie zgadza; ``ValueError``,
    gdy plik nie jest listą JSON. Zły wpis nie zabiera reszty artefaktu."""

    dane = json.loads(tekst)
    if not isinstance(dane, list):
        raise ValueError("flaky testy to nie lista")
    flaky_testy, odrzucone = [], []
    for wpis in dane:
        try:
            flaky = FlakyTest(**wpis)
        except TypeError as blad:
            odrzucone.append(f"wpis o złym kształcie: {blad}")
            continue
        if not isinstance(flaky.test, str) or not zgloszalny(flaky.test):
            odrzucone.append(f"id testu poza wzorcem {ID_TESTU.pattern}: {str(flaky.test)[:80]!r}")
            continue
        flaky_testy.append(flaky)
    return flaky_testy, odrzucone


def zapisz_kwarantanne(zapis: ZapisKwarantanny, plik: Path = KWARANTANNA) -> None:
    plik.parent.mkdir(parents=True, exist_ok=True)
    plik.write_text(json.dumps(asdict(zapis), indent=1, ensure_ascii=False), encoding="utf-8")


def kwarantanna_z_json(tekst: str) -> ZapisKwarantanny:
    return ZapisKwarantanny(**json.loads(tekst))


def ma_wpisy(zrodlo: str) -> bool:
    """Czy ``KWARANTANNA`` w źródle ``PLIK_KWARANTANNY`` ma wpis, odczytane bez wykonania kodu. Pusta jest tylko wtedy,
    gdy jedynym użyciem nazwy w module jest jedno przypisanie dosłownego ``{}`` na poziomie modułu; każde inne (dopisany
    klucz, ``.update``, ``|=``, drugie przypisanie, słownik spoza literału) liczy się jak wpisy."""

    try:
        modul = ast.parse(zrodlo)
    except SyntaxError:
        return True
    # Nazwa w polu węzła: ``Name``, ``Attribute``, import albo napis (``globals()["KWARANTANNA"]``).
    uzycia = [wezel for wezel in ast.walk(modul) if any(pole == "KWARANTANNA" for _, pole in ast.iter_fields(wezel))]
    for instrukcja in modul.body:
        cele: list[ast.expr]
        if isinstance(instrukcja, ast.AnnAssign):
            cele, wartosc = [instrukcja.target], instrukcja.value
        elif isinstance(instrukcja, ast.Assign):
            cele, wartosc = instrukcja.targets, instrukcja.value
        else:
            continue
        if cele == uzycia:
            return not (isinstance(wartosc, ast.Dict) and not wartosc.keys)
    return True


def stan_kwarantanny(zapisy: Iterable[ZapisKwarantanny]) -> StanKwarantanny:
    """Ostatnia próba każdego zadania runu: ``padła``, gdy test z kwarantanny gdzieś padł, ``bez zapisu``, gdy run nie
    ma zapisów albo test z kwarantanny nigdzie nie przeszedł (np. wszędzie pominięty), inaczej ``przeszła``."""

    ostatnie: dict[str, ZapisKwarantanny] = {}
    for zapis in zapisy:
        if zapis.zadanie not in ostatnie or zapis.proba > ostatnie[zapis.zadanie].proba:
            ostatnie[zapis.zadanie] = zapis
    if not ostatnie:
        return "bez zapisu"
    wyniki = [zapis.wyniki for zapis in ostatnie.values()]
    wpisy = {wpis for wynik in wyniki for wpis in wynik}
    if any(wynik.get(wpis) == "padł" for wynik in wyniki for wpis in wpisy):
        return "padła"
    if any(all(wynik.get(wpis) != "przeszedł" for wynik in wyniki) for wpis in wpisy):
        return "bez zapisu"
    return "przeszła"


def _id(test: ElementTree.Element) -> str | None:
    plik = (test.get("file") or "").replace("\\", "/")
    modul = plik.removesuffix(".py").replace("/", ".")
    klasy, nazwa = test.get("classname", ""), test.get("name")
    if not plik.endswith(".py") or nazwa is None or not (klasy == modul or klasy.startswith(f"{modul}.")):
        return None
    return "::".join([plik, *klasy[len(modul) :].split(".")[1:], nazwa])


def _testy(junit: Path) -> list[tuple[str | None, ElementTree.Element]]:
    return [(_id(test), test) for test in ElementTree.parse(junit).getroot().iter("testcase")]


def _wynik(test: ElementTree.Element) -> Wynik:
    if test.find("failure") is not None or test.find("error") is not None:
        return "padł"
    pominiety = test.find("skipped")
    if pominiety is None:
        return "przeszedł"
    return "padł" if pominiety.get("type") == "pytest.xfail" else "pominięty"


def padniete(junit: Path) -> tuple[str, ...] | None:
    """Id testów z porażką albo błędem; ``None``, gdy junit nie da się odczytać albo porażka nie ma id testu (błąd
    kolekcji): wtedy nie ma czego ponowić."""

    try:
        testy = _testy(junit)
    except (OSError, ElementTree.ParseError):
        return None
    padly = [(id_testu, test) for id_testu, test in testy if test.find("failure") is not None or test.find("error") is not None]
    if any(id_testu is None for id_testu, _ in padly):
        return None
    return tuple(dict.fromkeys(id_testu for id_testu, _ in padly if id_testu is not None))


def po_ponowieniu(junit: Path, ponowienie: Path, testy: Sequence[str]) -> bool:
    """Czy każdy z ``testy`` przeszedł w junit ``ponowienie``. Gdy tak, ``junit`` traci ich porażki, bo z niego zapis
    czasów zgłasza wynik pliku testów, który sprawdza ``Required CI status``."""

    try:
        wyniki = {id_testu: _wynik(test) for id_testu, test in _testy(ponowienie)}
    except (OSError, ElementTree.ParseError):
        return False
    if any(wyniki.get(test) != "przeszedł" for test in testy):
        return False
    drzewo = ElementTree.parse(junit)
    for test in drzewo.getroot().iter("testcase"):
        if _id(test) in testy:
            for porazka in [*test.findall("failure"), *test.findall("error")]:
                test.remove(porazka)
    drzewo.write(junit, encoding="utf-8", xml_declaration=True)
    return True


def wyniki_kwarantanny(junit: Path) -> dict[str, Wynik]:
    """Wynik każdego testu z kwarantanny w junit; jego xfail to porażka, a xpass przejście."""

    try:
        testy = _testy(junit)
    except (OSError, ElementTree.ParseError):
        return {}
    return {id_testu: _wynik(test) for id_testu, test in testy if id_testu and any(w.get("name") == WLASNOSC for w in test.iter("property"))}
