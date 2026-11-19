"""Katalog repo, który box boat przeniósł w trakcie biegu (``.agents/skills/boat/SKILL.md``): jedyny właściciel decyzji,
co ten box wyjaśnia, a co zostaje porażką testu.

Box ze snapshotu albo po wznowieniu podaje ``KATALOG_DOMOWY`` z montowania FUSE ładowanego leniwie (lazyfs). Po
załadowaniu lazyfs podstawia prawdziwy dysk, a stare drzewo przenosi pod ``KATALOG_ZWOLNIONY``: proces, który już
biegł w katalogu repo, ma wtedy katalog roboczy pod ``przeniesienie`` tego katalogu.

Plugin stanu procesu (``tests/fixtures/stan_procesu.py``) pyta ten moduł o trzy rzeczy. ``wyjasnione``: którą różnicę
stanu procesu wyjaśnia box (tylko katalog roboczy, który jest dokładnie oczekiwanym katalogiem po przeniesieniu;
zostawiony zasób, każda inna wartość i inny katalog dalej są stanem testu). ``jedyna_przyczyna``: czy porażka fazy
testu to tylko wyjątek, który plugin zgłosił przez ``zglos``; raport takiej fazy dostaje własność ``WLASNOSC``.
``kod_sesji``: sesja, której każda porażka ma tę własność, kończy się ``KOD_WYJSCIA`` zamiast porażki testów.
``tools/szybko.py`` kończy wynikiem ``SZYBKO INFRA`` bieg, w którym każdy krok, który padł, to pytest z tym kodem.
Granica: wyjątek z ``zglos`` wywołanego wprost przez test, a nie przez plugin, też liczy się jako porażka boxa."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import PurePosixPath
from typing import TypeVar
import weakref

KATALOG_DOMOWY = "/home/user"
"""Katalog domowy boxa: lazyfs podaje go z montowania FUSE, a po załadowaniu przenosi pod ``KATALOG_ZWOLNIONY/home``."""
KATALOG_ZWOLNIONY = "/var/lib/ascii-lazy/retired/"
KOMUNIKAT = "BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg"
WLASNOSC = "box_boat_przeniosl_katalog_repo"
PORAZKA_TESTOW = 1
"""Kod wyjścia pytest, gdy padły testy (``pytest.ExitCode.TESTS_FAILED``)."""
KOD_WYJSCIA = 75
"""EX_TEMPFAIL z sysexits.h, czyli „powtórz”: inny niż kody pytest (0–5), więc nie myli się z porażką testów."""

_Klucz = TypeVar("_Klucz")


class KatalogPrzeniesiony(AssertionError):
    """Porażka sprawdzenia stanu procesu, której przyczyną jest katalog repo przeniesiony przez box, a nie test."""


_ZGLOSZONE: weakref.WeakSet[KatalogPrzeniesiony] = weakref.WeakSet()
"""Wyjątki z ``zglos``: ``KatalogPrzeniesiony`` rzucony przez kod testu nie jest porażką boxa."""


def przeniesienie(katalog: str) -> str | None:
    """Ścieżka, pod którą katalog ``katalog`` jest po przeniesieniu przez lazyfs; ``None`` dla katalogu spoza
    ``KATALOG_DOMOWY``, którego lazyfs nie przenosi."""

    sciezka, dom = PurePosixPath(katalog), PurePosixPath(KATALOG_DOMOWY)
    if sciezka != dom and dom not in sciezka.parents:
        return None
    return str(PurePosixPath(KATALOG_ZWOLNIONY, "home", sciezka.relative_to(dom)))


def wyjasnione(zmienione: Collection[_Klucz], katalog: _Klucz, oczekiwany: str | None, teraz: str) -> set[_Klucz]:
    """Te z kluczy ``zmienione`` (wartości stanu procesu z inną wartością niż oczekiwana), które wyjaśnia box: tylko klucz
    katalogu roboczego ``katalog``, gdy katalog roboczy ``teraz`` to dokładnie ``przeniesienie`` oczekiwanego. Każdy inny
    klucz i katalog, do którego test wszedł sam, zostają stanem testu."""

    katalog_teraz = teraz if oczekiwany is not None and teraz == przeniesienie(oczekiwany) else ""
    return {katalog} if katalog in zmienione and przeniesiony(katalog_teraz) else set()


def przeniesiony(katalog: str) -> bool:
    """Czy katalog ``katalog`` leży pod ``KATALOG_ZWOLNIONY``, czyli w drzewie, które lazyfs przeniósł."""

    return katalog.startswith(KATALOG_ZWOLNIONY)


def zglos(opis: str) -> KatalogPrzeniesiony:
    """Wyjątek, którym plugin stanu procesu zgłasza katalog przeniesiony przez box; tylko taki uznaje ``jedyna_przyczyna``."""

    blad = KatalogPrzeniesiony(opis)
    _ZGLOSZONE.add(blad)
    return blad


def jedyna_przyczyna(error: BaseException | None) -> bool:
    """Czy wyjątek fazy testu to wyjątek z ``zglos`` bez wyjątku pod nim (``__cause__``, ``__context__``): błąd teardownu
    dołączony jako przyczyna, wyjątek innego haka i ``KatalogPrzeniesiony`` rzucony przez test to porażka testu."""

    return error in _ZGLOSZONE and _bez_przyczyny(error)


def _bez_przyczyny(error: BaseException | None) -> bool:
    return type(error) is KatalogPrzeniesiony and error.__cause__ is None and error.__context__ is None


def kod_sesji(kod: int, porazki: Sequence[bool]) -> int:
    """Kod wyjścia sesji pytest z kodem ``kod``, której raporty, które padły, mają albo nie mają własności ``WLASNOSC``
    (``porazki``): ``KOD_WYJSCIA``, gdy padły testy, a każda porażka ma własność; inaczej ``kod``."""

    return KOD_WYJSCIA if kod == PORAZKA_TESTOW and porazki and all(porazki) else kod
