"""Jednostka planu runu CI: jej klucz (``pytest:<plik>``, ``krok:<nazwa>``, ``skill:<krok skilla>``, ``narzut:<szablon>``,
z częścią ``#k/n`` albo bez) i część ``k/n``, także ta, którą krok skilla dostaje w zmiennej ``MUTACJE_CZESC``.

Klucz składa i rozbiera tylko ``Klucz``: plan (``tools/plan_ci.py``, ``tools/lib/plan_runu.py``), zadanie
(``tools/ci/wykonaj_zadanie.py``), werdykt Required, zapis czasów i noc trzymają w JSON jego napis. Część ma dwa
znaczenia, każde swoją metodą: ``co_nta`` (k-ta, potem co n-ta pozycja listy w ustalonej kolejności: mutacje skryptu
mutacji w ``tools/mutacje.py`` i testy udziału pliku w ``tools/lib/pytest_czesc.py``) i ``kawalek`` (k-ty z n kolejnych
kawałków: jednostki podstawy skilla w ``tools/lib/skrypt_skilla.py`` i mutacje części nocy w ``tools/mutacje_zmiany.py``).
Moduł używa tylko biblioteki standardowej, bo plan i werdykt biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeVar

T = TypeVar("T")

ZMIENNA_CZESCI = "MUTACJE_CZESC"


@dataclass(frozen=True)
class Czesc:
    """Część ``k`` z ``n``, ``1 <= k <= n``."""

    k: int
    n: int

    @classmethod
    def z_tekstu(cls, tekst: str) -> Czesc:
        """Część z napisu ``k/n``; inna postać to ``ValueError`` z napisem."""

        k, _, n = tekst.partition("/")
        if not (k.isdigit() and n.isdigit() and 1 <= int(k) <= int(n)):
            raise ValueError(f"K/N z 1 <= K <= N, nie {tekst!r}")
        return cls(int(k), int(n))

    @staticmethod
    def calosc(n: int) -> tuple[Czesc, ...]:
        return tuple(Czesc(k, n) for k in range(1, n + 1))

    def __str__(self) -> str:
        return f"{self.k}/{self.n}"

    def co_nta(self, elementy: Sequence[T]) -> list[T]:
        """Pozycje ``k``, ``k + n``, ``k + 2n``… z ``elementy`` (numerowanych od 1)."""

        return list(elementy[self.k - 1 :: self.n])

    def kawalek(self, elementy: Sequence[T]) -> Sequence[T]:
        """K-ty z ``n`` kolejnych kawałków ``elementy``; ``n`` części daje każdy element dokładnie raz."""

        return elementy[len(elementy) * (self.k - 1) // self.n : len(elementy) * self.k // self.n]


class Rodzaj(Enum):
    PYTEST = "pytest"  # plik testów albo węzeł ``plik::test``
    KROK = "krok"  # krok CI z ``zakres_runu.KROKI`` (także ``krok:pytest`` i ``krok:praca`` w zapisie czasów)
    SKILL = "skill"  # krok skilla, ``kroki_skilli.Step.key``
    NARZUT = "narzut"  # narzut zadania szablonu w zapisie czasów


@dataclass(frozen=True)
class Klucz:
    rodzaj: Rodzaj
    nazwa: str
    czesc: Czesc | None = None

    @classmethod
    def z_tekstu(cls, tekst: str) -> Klucz:
        """Klucz z napisu; nieznany rodzaj, brak nazwy albo zła część to ``ValueError``."""

        przed, _, czesc = tekst.partition("#")
        rodzaj, dwukropek, nazwa = przed.partition(":")
        if not dwukropek or not nazwa or rodzaj not in {r.value for r in Rodzaj}:
            raise ValueError(f"klucz jednostki {tekst!r} nie ma postaci <{'|'.join(r.value for r in Rodzaj)}>:<nazwa>[#k/n]")
        return cls(Rodzaj(rodzaj), nazwa, Czesc.z_tekstu(czesc) if czesc else None)

    def __str__(self) -> str:
        return f"{self.rodzaj.value}:{self.nazwa}" + (f"#{self.czesc}" if self.czesc else "")

    @property
    def calosc(self) -> Klucz:
        """Klucz bez części: pod nim zadanie zgłasza wynik każdej swojej części."""

        return replace(self, czesc=None)

    @property
    def zgloszony(self) -> Klucz:
        """Klucz, pod którym zapis zadania zgłasza wynik jednostki: krok bez części, a plik testów także bez węzła
        ``::test``, bo junit zna tylko plik testu."""

        return Klucz(self.rodzaj, self.nazwa.partition("::")[0]) if self.rodzaj is Rodzaj.PYTEST else self.calosc

    def czesci(self, n: int) -> tuple[Klucz, ...]:
        return tuple(replace(self, czesc=czesc) for czesc in Czesc.calosc(n))


def rodzaj(tekst: str) -> Rodzaj | None:
    """Rodzaj klucza z zapisu czasów bez sprawdzania reszty; klucz innego rodzaju (``None``) zapis czasów tylko pomija."""

    przed, dwukropek, _ = tekst.partition(":")
    return next((r for r in Rodzaj if dwukropek and r.value == przed), None)


def pytest(plik: str) -> str:
    return str(Klucz(Rodzaj.PYTEST, plik))


def krok(nazwa: str) -> str:
    return str(Klucz(Rodzaj.KROK, nazwa))


def skill(klucz_kroku: str) -> str:
    return str(Klucz(Rodzaj.SKILL, klucz_kroku))


def narzut(szablon: str) -> str:
    return str(Klucz(Rodzaj.NARZUT, szablon))
