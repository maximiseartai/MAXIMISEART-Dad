"""Katalog repo, który box boat przeniósł w trakcie biegu (``.agents/skills/boat/SKILL.md``): jedyny właściciel decyzji,
co ten box wyjaśnia, a co zostaje porażką testu.

Box ze snapshotu albo po wznowieniu podaje katalog domowy z montowania FUSE ładowanego leniwie (lazyfs). Po
załadowaniu lazyfs podstawia prawdziwy dysk, a stare drzewo przenosi pod ``KATALOG_ZWOLNIONY``: proces, który już
biegł w katalogu repo, ma wtedy katalog roboczy pod tą ścieżką.

Plugin stanu procesu (``tests/fixtures/stan_procesu.py``) pyta ten moduł o trzy rzeczy. ``wyjasnione``: którą różnicę
stanu procesu wyjaśnia box (tylko katalog roboczy; zostawiony zasób i każda inna wartość dalej są stanem testu).
``jedyna_przyczyna``: czy porażka fazy testu to tylko ``KatalogPrzeniesiony``; raport takiej fazy dostaje własność
``WLASNOSC``. ``kod_sesji``: sesja, której każda porażka ma tę własność, kończy się ``KOD_WYJSCIA`` zamiast porażki
testów. ``tools/szybko.py`` kończy wynikiem ``SZYBKO INFRA`` bieg, w którym każdy krok, który padł, to pytest z tym
kodem."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TypeVar

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


def przeniesiony(katalog: str) -> bool:
    """Czy katalog roboczy ``katalog`` to katalog repo, który box przeniósł po załadowaniu dysku."""

    return katalog.startswith(KATALOG_ZWOLNIONY)


def wyjasnione(zmienione: Collection[_Klucz], katalog: _Klucz, katalog_teraz: str) -> set[_Klucz]:
    """Te z kluczy ``zmienione`` (wartości stanu procesu z inną wartością niż oczekiwana), które wyjaśnia box: tylko klucz
    katalogu roboczego ``katalog``, gdy ``katalog_teraz`` jest przeniesiony. Każdy inny klucz zostaje stanem testu."""

    return {katalog} if katalog in zmienione and przeniesiony(katalog_teraz) else set()


def jedyna_przyczyna(error: BaseException | None) -> bool:
    """Czy wyjątek fazy testu to dokładnie ``KatalogPrzeniesiony`` bez wyjątku pod nim (``__cause__``, ``__context__``):
    błąd teardownu dołączony jako przyczyna i wyjątek innego haka to porażka testu."""

    return type(error) is KatalogPrzeniesiony and error.__cause__ is None and error.__context__ is None


def kod_sesji(kod: int, porazki: Sequence[bool]) -> int:
    """Kod wyjścia sesji pytest z kodem ``kod``, której raporty, które padły, mają albo nie mają własności ``WLASNOSC``
    (``porazki``): ``KOD_WYJSCIA``, gdy padły testy, a każda porażka ma własność; inaczej ``kod``."""

    return KOD_WYJSCIA if kod == PORAZKA_TESTOW and porazki and all(porazki) else kod
