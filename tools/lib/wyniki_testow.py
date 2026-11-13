"""Wyniki testów pytest z pliku junit (``--junitxml``, ``junit_family = "xunit1"``): jedyny czytnik tego formatu.

Każdy ``<testcase>`` to ``Test``: plik z atrybutu ``file`` (z ``/``), id pytest (``tests/test_x.py::Klasa::test_y[parametry]``)
z pliku, klas z ``classname`` za modułem tego pliku i nazwy z parametrami z ``name``, czas z ``time``, wynik i nazwy
własności junit. Błąd kolekcji pliku pytest zapisuje z pustym ``classname`` i nazwą modułu w ``name``, więc taki test
ma plik, ale nie ma id. Postać ``xunit1`` daje ``pyproject.toml`` zadaniom CI, a narzędzia, które same uruchamiają
pytest w innym drzewie, wymuszają ją argumentami ``zapis``.

Czytają go zapis czasów CI (``tools/ci/zapis_czasow.py``), flaky testy i kwarantanna (``tools/lib/niestabilne_testy.py``),
pamięć zielonych testów ``tools/szybko.py``, test scalenia ``tools/scal_pr.py`` i sprawdzenie ``JUŻ ŁAPIE``
``tools/mutacje.py``. Moduł używa tylko biblioteki standardowej, bo zapis czasów biegnie systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

Wynik = Literal["przeszedł", "padł", "pominięty", "xfail"]


@dataclass(frozen=True)
class Test:
    plik: str | None
    id: str | None  # ``None``: bez pliku albo błąd kolekcji
    nazwa: str | None
    sekundy: float | None
    wynik: Wynik
    wlasnosci: frozenset[str] = frozenset()


def zapis(plik: Path) -> tuple[str, ...]:
    """Argumenty pytest, z którymi zapisuje junit ``plik`` w postaci, którą czyta ``testy``."""

    return (f"--junitxml={plik}", "-o", "junit_family=xunit1")


def testy(junit: Path) -> list[Test]:
    """Testy z pliku ``junit`` w jego kolejności; brak pliku to ``OSError``, plik, który nie jest XML, ``ValueError``."""

    return [_test(element) for element in _drzewo(junit).iter("testcase")]


def bez_porazek(junit: Path, ids: Collection[str]) -> None:
    drzewo = _drzewo(junit)
    for element in drzewo.iter("testcase"):
        if _id(element) in ids:
            for porazka in [*element.findall("failure"), *element.findall("error")]:
                element.remove(porazka)
    drzewo.write(junit, encoding="utf-8", xml_declaration=True)


def _drzewo(junit: Path) -> ElementTree.ElementTree[ElementTree.Element]:
    try:
        return ElementTree.parse(junit)
    except ElementTree.ParseError as error:
        raise ValueError(f"to nie jest XML ({error})") from None


def _test(element: ElementTree.Element) -> Test:
    plik = element.get("file")
    czas = element.get("time")
    return Test(
        plik.replace("\\", "/") if plik is not None else None,
        _id(element),
        element.get("name"),
        float(czas) if czas is not None else None,
        _wynik(element),
        frozenset(str(wlasnosc.get("name")) for wlasnosc in element.iter("property")),
    )


def _id(element: ElementTree.Element) -> str | None:
    plik = (element.get("file") or "").replace("\\", "/")
    modul = plik.removesuffix(".py").replace("/", ".")
    klasy, nazwa = element.get("classname", ""), element.get("name")
    if not plik.endswith(".py") or nazwa is None or not (klasy == modul or klasy.startswith(f"{modul}.")):
        return None
    return "::".join([plik, *klasy[len(modul) :].split(".")[1:], nazwa])


def _wynik(element: ElementTree.Element) -> Wynik:
    if element.find("failure") is not None or element.find("error") is not None:
        return "padł"
    pominiety = element.find("skipped")
    if pominiety is None:
        return "przeszedł"
    return "xfail" if pominiety.get("type") == "pytest.xfail" else "pominięty"
