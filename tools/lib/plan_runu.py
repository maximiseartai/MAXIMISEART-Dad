"""Plan runu CI: zadania pytest i Mutation checks runu ``ci.yml`` z jednostkami każdego zadania, jako plik JSON.

Plan układa ``tools/plan_ci.py plan`` (zadanie ``plan`` w ``ci.yml`` i w ``mutacje-nocne.yml``, a lokalnie agent), każde
zadanie wykonuje swoje jednostki przez ``tools/ci/wykonaj_zadanie.py``, a ``Required CI status`` sprawdza wyniki wobec
planu przez ``tools/ci/werdykt_required.py``. Jednostka to plik testów, jego udział, krok CI, podstawa skilla, skrypt
mutacji albo jego część, pod napisem swojego klucza (``tools/lib/jednostka.py``).

Plan ma ``digest``: zadanie wykonuje tylko plan, którego treść się z nim zgadza, i zapisuje go w swoim zapisie czasów,
a werdykt przyjmuje tylko zapisy tego planu. Limit kroku pytest (``limit_pytest_s``) i limit zadania pytest w macierzy
(``limit_minut``, ``timeout-minutes`` w ``ci.yml``) liczy plan z tych samych stałych, z którymi zadanie je egzekwuje.
Moduł używa tylko biblioteki standardowej, bo plan i werdykt biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from jednostka import Klucz, Rodzaj
from zakres_runu import KROKI, MUTACJE, TORY, Zdarzenie

WERSJA = 1
# Artefakt runu ``ci.yml`` z planem i plik planu w nim (``--wyjscie`` zadania ``plan``).
ARTEFAKT = "plan"
PLIK = "plan.json"
# Zapis wykonania zadania: wynik każdej jednostki i ostrzeżenia ``CZAS BLISKO LIMITU`` (``tools/ci/wykonaj_zadanie.py``).
WYKONANIE = Path(".ci-czasy", "wykonanie.json")
PONOWIENIE_LIMIT_S = 10 * 60
# Krok pytest zielonego zadania trwał najwyżej 1,68 × ścianę zadania z planu (418 zadań zielonych runów CI z 28–31.10,
# najdłuższy 668 s przy ścianie 411 s), więc limit 3 × ściana go nie przerywa. Najmniej 10 min, żeby test zawieszony
# pod koniec kroku zdążył zostawić stosy wątków (faulthandler_timeout w pyproject.toml) przed limitem.
ZAPAS_PYTEST = 3.0
LIMIT_PYTEST_MIN_S = 10 * 60
# Zadanie pytest poza krokami z limitem: checkout, Python, zależności, artefakty i zapis czasów (narzut do 43 s w tych runach).
NARZUT_ZADANIA_S = 10 * 60
# Zadania bramki w ci.yml, które startują tylko z pracą od planu.
Z_PLANU = ("pytest", "mutations")


@dataclass(frozen=True)
class Zadanie:
    id: str
    tor: str
    nazwa: str
    jednostki: tuple[str, ...]
    sciana_s: float
    przegladarka: bool = False  # ma krok skilla, którego skrypty importują Playwright

    @property
    def klucze(self) -> tuple[Klucz, ...]:
        return tuple(map(Klucz.z_tekstu, self.jednostki))


@dataclass(frozen=True)
class Plan:
    zdarzenie: Zdarzenie
    cel_s: float
    runy: tuple[int, ...]  # runy main, z których są czasy
    zadania: tuple[Zadanie, ...]
    bledy: tuple[str, ...] = ()  # FAIL-e znalezienia kroków skilli: zgubiony skrypt mutacji, zły klucz ``ci:``

    @property
    def digest(self) -> str:
        tresc = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(tresc.encode("utf-8")).hexdigest()

    def do_json(self) -> str:
        return json.dumps({"wersja": WERSJA, "digest": self.digest, **asdict(self)}, indent=1, ensure_ascii=False)

    @classmethod
    def z_json(cls, tekst: str) -> Plan:
        """Plan z pliku; treść niezgodna z ``digest`` to ``ValueError``, bo zadania biegłyby z innego planu."""

        dane = json.loads(tekst)
        if dane.pop("wersja", None) != WERSJA:
            raise ValueError(f"plan w wersji innej niż {WERSJA}")
        digest = dane.pop("digest")
        zadania = tuple(Zadanie(**{**zadanie, "jednostki": tuple(zadanie["jednostki"])}) for zadanie in dane.pop("zadania"))
        plan = cls(**{**dane, "zdarzenie": Zdarzenie(dane["zdarzenie"]), "runy": tuple(dane["runy"]), "zadania": zadania, "bledy": tuple(dane["bledy"])})
        if plan.digest != digest:
            raise ValueError(f"treść planu nie zgadza się z jego digest {digest[:12]}")
        # Klucz jednostki w innej postaci to ValueError, jak plan w innej wersji.
        for klucz in (klucz for zadanie in plan.zadania for klucz in zadanie.jednostki):
            Klucz.z_tekstu(klucz)
        return plan

    def pliki_pytest(self, tory: Collection[str], zmienione: Collection[str]) -> list[tuple[str, list[str]]]:
        """Nazwa i pliki testów (i węzły ``plik::test``) każdego zadania pytest z ``tory``, w którym stoi plik z
        ``zmienione``; kolejność zadań i plików jak w planie, bez powtórzeń, a udział pliku ``#k/n`` to cały plik."""

        znalezione = []
        for zadanie in self.zadania:
            pliki = list(dict.fromkeys(klucz.nazwa for klucz in zadanie.klucze if klucz.rodzaj is Rodzaj.PYTEST))
            if zadanie.tor in tory and any(plik.partition("::")[0] in zmienione for plik in pliki):
                znalezione.append((zadanie.nazwa, pliki))
        return znalezione

    def macierz(self, szablon: str) -> list[dict[str, str | bool | int]]:
        """``include`` macierzy zadania ``szablon`` w ci.yml (``[]``, gdy plan nie ma jego zadań: zadanie jest pominięte)."""

        tory = {tor.nazwa: tor for tor in (*TORY, MUTACJE)}
        wpisy: list[dict[str, str | bool | int]] = []
        for z in self.zadania:
            tor = tory[z.tor]
            if tor.szablon == szablon:
                wpis: dict[str, str | bool | int] = {"id": z.id, "nazwa": z.nazwa, "os": tor.os, "python": tor.python}
                wpis["przegladarka"] = z.przegladarka
                if szablon != MUTACJE.szablon:
                    wpis["limit_minut"] = self.limit_zadania_min(z)
                wpisy.append(wpis)
        return wpisy

    def limit_zadania_min(self, zadanie: Zadanie) -> int:
        """``timeout-minutes`` zadania pytest: suma limitów jego kroków (pytest, na pull request ponowienie, kroki CI)
        i ``NARZUT_ZADANIA_S``, więc zadanie kończy limit kroku z linią ``LIMIT``, zanim zabije je GitHub."""

        kroki = [KROKI[klucz.nazwa] for klucz in zadanie.klucze if klucz.rodzaj is Rodzaj.KROK]
        ponowienie = PONOWIENIE_LIMIT_S if self.zdarzenie is Zdarzenie.PULL_REQUEST else 0
        return math.ceil((NARZUT_ZADANIA_S + limit_pytest_s(zadanie) + ponowienie + sum(sum(krok.limity_s) for krok in kroki)) / 60)


def tory_systemu(windows: bool) -> list[str]:
    return [tor.nazwa for tor in TORY if tor.os.startswith("windows") == windows]


def limit_pytest_s(zadanie: Zadanie) -> float:
    return max(LIMIT_PYTEST_MIN_S, ZAPAS_PYTEST * zadanie.sciana_s)
