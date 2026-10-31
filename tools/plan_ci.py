"""Drukuje plan runu CI gałęzi (plan --baza origin/main): zadania pytest i Mutation checks, ich pliki i kroki skilli; użyj przed pushem albo gdy CI biegło inaczej.

Plan CI: ile zadań pytest i Mutation checks startuje w runie ``ci.yml`` i co biegnie w każdym.

Co biegnie, wyznacza zakres runu (``tools/lib/zakres_runu.py``, ADR 0020, ADR 0021) dla zdarzenia (``pull_request``,
``push`` albo ``noc``, workflow ``mutacje-nocne.yml``) i zmiany od bazy: tory pytest z krokami CI (E2E, straż czasu) i
pliki testów na każdym, oraz kroki skilli, które biegną, z powodem. Plan tylko wycenia i pakuje ten zakres: pytest na
torach zakresu, a kroki skilli na torze ``MUTACJE`` (Windows 3.14, zadania Mutation checks), każda podstawa ``ci:`` i
każdy skrypt mutacji osobno, a krok z częściami ustalonymi przez zakres (nocą każda część każdej liczby części podstawy
z ``ci-czesci``) każdą z nich. Koszt jednostki to ściana, którą dodaje do zadania: plik waży sumę czasów swoich testów przez
``WORKERY`` workerów xdist, krok swój czas. Czasy to mediany z ostatnich runów main (``tools/ci/czasy_ci.py``). Plik albo
krok skilla bez pomiaru waży medianę zmierzonych jednostek tego rodzaju na torze, a bez żadnych pomiarów wagę z
``DOMYSLNIE``: plan to wypisuje i biegnie dalej, bo brak czasów psuje tylko równowagę zadań, nie zbiór pracy.

Ściana zadania to narzut (od startu zadania do pracy), start pytest, suma kosztów jego jednostek i koniec zadania;
narzut i start też są z pomiarów. Plan dzieli każdy tor na najmniej zadań o ścianie najwyżej ``cel_s`` (LPT: najdłuższa jednostka do
zadania o najmniejszej sumie). Plik dłuższy niż zadanie dzieli się na k udziałów o tej samej wadze: udział k biegnie
z ``-p tools.ci.pytest_czesc`` (testy pliku posortowane po id, po kolei). Skrypt mutacji dłuższy niż zadanie dzieli się tak samo na
najwyżej tyle części, ile ma mutacji: część biegnie z ``MUTACJE_CZESC=k/n`` (``tools/mutacje.py``), z podstawą
poleceń swoich mutacji. Podstawa ``ci:`` z ``ci-czesci: <n>`` dzieli się tak samo na najwyżej n części (część k
skrypt bierze z ``MUTACJE_CZESC=k/n``, ``tools/lib/skrypt_skilla.py``), a bez niego nie. Plan drukuje najdłuższą jednostkę
każdego toru po podziale: poniżej niej ściana zadania nie zejdzie.
Zadanie Mutation checks instaluje Chromium tylko wtedy, gdy ma krok skilla, którego skrypty importują Playwright. Gdy
run (``STALE_ZADANIA``, zadania pytest i Mutation checks) przekroczyłby ``ZADANIA_RUNU`` na pull request albo
``ZADANIA_RUNU_MAIN`` na pushu i nocą, cel wszystkich torów rośnie co ``KROK_CELU_S``.

Na pull request zadanie po porażce pytest uruchamia raz same testy, które padły (``niestabilne_testy``, najwyżej
``PONOWIENIE_NAJWIECEJ``; więcej porażek to nie flaky test), jeśli id każdego da się zgłosić w issue. Gdy wszystkie
przejdą, pytest przechodzi, a każdy z nich trafia do zapisu flaky testów; druga porażka to porażka. Każde zadanie z pytest
zapisuje też wynik swoich testów z kwarantanny.
Krok pytest ma limit ``limit_pytest_s`` ze ściany zadania z planu: po nim drzewo pytest ginie, a linia ``LIMIT`` mówi, że
to limit, nie porażka testu. Zadanie pytest dostaje w macierzy ``limit_minut`` (``timeout-minutes`` w ``ci.yml``), sumę
limitów swoich kroków z zapasem, więc GitHub zabija je dopiero wtedy, gdy zawiesi się coś poza krokami z limitem.

Plan ma ``digest``: zadanie wykonuje tylko plan, którego treść się z nim zgadza, i zapisuje go w swoim zapisie czasów,
a ``Required CI status`` (``werdykt``) przyjmuje tylko zapisy tego planu. Werdykt przepuszcza run, gdy każde zadanie
przeszło, zadanie pominięte to tylko takie, któremu plan nie dał pracy, a każde zadanie planu zgłosiło w ostatniej
próbie każdą swoją jednostkę (plik testów, krok CI, krok skilla) bez porażki, a części każdej podzielonej jednostki
składają się na całość (każda z 1..n dokładnie raz). Plan, którego nie ma, i skrypt mutacji,
który wybór skilli zgubił albo zły klucz ``ci:`` (``bledy`` planu), są czerwonym werdyktem z przyczyną.

    python3 tools/plan_ci.py plan --zdarzenie pull_request --baza HEAD^1 --czasy .ci-plan/czasy --wyjscie .ci-plan/plan.json
    python3 tools/plan_ci.py plan --zdarzenie noc --baza <baza nocy> --czasy .ci-plan/czasy --wyjscie .ci-plan/plan.json
    python tools/plan_ci.py wykonaj --plan .ci-plan/plan.json --zadanie windows-3.14-2       # albo mutacje-1
    python3 tools/plan_ci.py werdykt --plan .ci-plan/plan.json --zapisy .ci-czasy/zapisy      # NEEDS: toJSON(needs)

Lokalnie plan na czasach z ``.git/czasy-ci`` (wspólnych z ``tools/szybko.py``) drukuje zadania i ich prognozę:

    .venv/bin/python tools/plan_ci.py plan --baza origin/main
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import czasy_ci
from kroki_skilli import Step, steps
import mutacje
import mutacje_skilli
import niestabilne_testy
from niestabilne_testy import FlakyTest, ZapisKwarantanny
import potomne
from wplyw_zmiany import changed_since
from zakres_runu import KROKI, MUTACJE, TORY, Krok, KrokSkilla, Tor, ZakresRunu, Zdarzenie, zakres

ROOT = Path(__file__).resolve().parents[1]
WERSJA = 1
WORKERY = 4  # pytest -n auto na runnerze 4 vCPU
JUNIT = Path(".ci-czasy", "junit.xml")
PONOWIENIE = Path(".ci-czasy", "junit-ponowienie.xml")
# Flaky test trafia w jeden albo dwa testy (Skrzynka w runach 26.10); więcej porażek naraz to defekt albo awaria runnera.
PONOWIENIE_NAJWIECEJ = 5
PONOWIENIE_LIMIT_S = 10 * 60
# Krok pytest zielonego zadania trwał najwyżej 1,68 × ścianę zadania z planu (418 zadań zielonych runów CI z 28–31.10,
# najdłuższy 668 s przy ścianie 411 s), więc limit 3 × ściana go nie przerywa. Najmniej 10 min, żeby test zawieszony
# pod koniec kroku zdążył zostawić stosy wątków (faulthandler_timeout w pyproject.toml) przed limitem.
ZAPAS_PYTEST = 3.0
LIMIT_PYTEST_MIN_S = 10 * 60
# Zadanie pytest poza krokami z limitem: checkout, Python, zależności, artefakty i zapis czasów (narzut do 43 s w tych runach).
NARZUT_ZADANIA_S = 10 * 60
WYKONANIE = Path(".ci-czasy", "wykonanie.json")
CZESCI = Path(".ci-plan", "czesci.json")
# W symulacji 60 PR (29.10) cel 60, 75 i 90 s daje bramce ten sam p50 i p90, bo ścianę trzyma jednostka, której plan
# nie dzieli (część podstawy skilla, krok E2E, długi test), a 90 s najmniej zadań: stały koszt zadania pytest to ok. 40 s.
CEL_S = 90.0
KROK_CELU_S = 5.0
# Organizacja ma 60 zadań naraz ze wszystkich workflowów (plan Team od 26.10): run pull request bierze najwyżej 40, a
# run na main (push i noc) 20, więc największy run PR i pełne CI main startują razem bez kolejki.
ZADANIA_RUNU = 40
ZADANIA_RUNU_MAIN = 20
# Zadania ci.yml o stałej liczbie (plan, Frontend, Ruff i mypy, Required).
STALE_ZADANIA = 4
# Zadania bramki w ci.yml, które startują tylko z pracą od planu.
Z_PLANU = ("pytest", "mutations")


@dataclass(frozen=True)
class Domyslnie:
    """Wagi bez pomiaru, z runów 40276834805 i 40288016668 w zaokrągleniu."""

    plik_s: float = 20.0
    narzut_s: float = 15.0
    start_s: float = 25.0
    # Zapis czasów, wysłanie artefaktów i koniec zadania po pracy: 4–8 s w runie 40288016668. Zapis czasów go nie mierzy.
    koniec_s: float = 6.0
    # Mediany kroków skilli i narzutu Mutation checks (z Chromium) z runów main 40297447225, 40304311652, 40308056465.
    krok_skilla_s: float = 90.0
    narzut_mutacji_s: float = 45.0


DOMYSLNIE = Domyslnie()


@dataclass(frozen=True)
class Jednostka:
    """Praca, którą plan daje zadaniu: ``pytest:<plik>``, udział ``pytest:<plik>#k/n``, ``krok:<nazwa>``,
    ``skill:<skill>/ci`` (podstawa), ``skill:<skill>/<skrypt>`` albo część skryptu mutacji ``skill:<skill>/<skrypt>#k/n``."""

    klucz: str
    s: float  # ściana, którą dodaje do zadania


@dataclass(frozen=True)
class Zadanie:
    id: str
    tor: str
    nazwa: str
    jednostki: tuple[str, ...]
    sciana_s: float
    przegladarka: bool = False  # ma krok skilla, którego skrypty importują Playwright


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
        return plan

    def macierz(self, szablon: str) -> list[dict[str, str | bool | int]]:
        """``include`` macierzy zadania ``szablon`` w ci.yml (``[]``, gdy plan nie ma jego zadań: zadanie jest pominięte)."""

        tory = {tor.nazwa: tor for tor in (*TORY, MUTACJE)}
        wpisy: list[dict[str, str | bool | int]] = []
        for z in self.zadania:
            tor = tory[z.tor]
            if tor.szablon == szablon:
                wpis: dict[str, str | bool | int] = {"id": z.id, "nazwa": z.nazwa, "os": tor.os, "python": tor.python}
                if szablon == MUTACJE.szablon:
                    wpis["przegladarka"] = z.przegladarka
                else:
                    wpis["limit_minut"] = self.limit_zadania_min(z)
                wpisy.append(wpis)
        return wpisy

    def limit_zadania_min(self, zadanie: Zadanie) -> int:
        """``timeout-minutes`` zadania pytest: suma limitów jego kroków (pytest, na pull request ponowienie, kroki CI)
        i ``NARZUT_ZADANIA_S``, więc zadanie kończy limit kroku z linią ``LIMIT``, zanim zabije je GitHub."""

        kroki = [KROKI[klucz.removeprefix("krok:")] for klucz in zadanie.jednostki if klucz.startswith("krok:")]
        ponowienie = PONOWIENIE_LIMIT_S if self.zdarzenie is Zdarzenie.PULL_REQUEST else 0
        return math.ceil((NARZUT_ZADANIA_S + limit_pytest_s(zadanie) + ponowienie + sum(sum(krok.limity_s) for krok in kroki)) / 60)


def limit_pytest_s(zadanie: Zadanie) -> float:
    """Limit kroku pytest zadania: ``ZAPAS_PYTEST`` × jego ściana z planu, najmniej ``LIMIT_PYTEST_MIN_S``."""

    return max(LIMIT_PYTEST_MIN_S, ZAPAS_PYTEST * zadanie.sciana_s)


# --- plan ---


@dataclass(frozen=True)
class Wycena:
    """Koszty jednego toru: jednostki przed podziałem, narzut i start pracy zadania."""

    tor: Tor
    podzielne: Mapping[str, float]  # plik testów albo skrypt mutacji -> ściana całości
    niepodzielne: Mapping[str, float]  # węzeł testu, krok CI albo podstawa skilla
    narzut_s: float
    start_s: float
    czesci: Mapping[str, int] = field(default_factory=dict)  # najwięcej części jednostki podzielnej (skrypt: mutacje)
    przegladarka: frozenset[str] = frozenset()  # jednostki, które potrzebują Chromium

    def jednostki(self, pojemnosc_s: float) -> list[Jednostka]:
        """Jednostki podzielne dłuższe niż ``pojemnosc_s`` w częściach, które się w niej mieszczą, i niepodzielne."""

        wynik = [Jednostka(klucz, s) for klucz, s in self.niepodzielne.items()]
        for klucz, s in self.podzielne.items():
            k = max(1, math.ceil(s / pojemnosc_s)) if pojemnosc_s > 0 else 1
            k = min(k, self.czesci.get(klucz, k))
            wynik += [Jednostka(klucz, s)] if k == 1 else [Jednostka(f"{klucz}#{i}/{k}", s / k) for i in range(1, k + 1)]
        return wynik


def wycen(tor: Tor, pliki: Sequence[str], czasy: czasy_ci.Czasy) -> Wycena:
    """Plik testów jest podzielny na udziały, a węzeł ``plik::test`` nie i waży najwyżej tyle, co typowy plik."""

    zmierzone = czasy.pliki(tor.pomiary)
    domyslny = statistics.median(zmierzone.values()) if zmierzone else DOMYSLNIE.plik_s
    kroki = {f"krok:{nazwa}": czasy.praca(tor.pomiary, f"krok:{nazwa}") or KROKI[nazwa].domyslnie_s for nazwa in tor.kroki}
    wezly = {f"pytest:{wezel}": min(zmierzone.get(wezel.partition("::")[0], domyslny), domyslny) / WORKERY for wezel in pliki if "::" in wezel}
    zadania = [z for z in czasy.zadania(tor.pomiary) if f"narzut:{tor.szablon}" in z]
    narzuty = [z[f"narzut:{tor.szablon}"] for z in zadania]
    # Start pytest: ściana pytest zadania ponad sumę jego testów na workerach (start, kolekcja, ogon workerów).
    starty = [z["krok:pytest"] - sum(s for k, s in z.items() if k.startswith("pytest:")) / WORKERY for z in zadania if "krok:pytest" in z]
    return Wycena(
        tor,
        {f"pytest:{plik}": zmierzone.get(plik, domyslny) / WORKERY for plik in pliki if "::" not in plik},
        {**wezly, **kroki},
        statistics.median(narzuty) if narzuty else DOMYSLNIE.narzut_s,
        max(0.0, statistics.median(starty)) if starty else DOMYSLNIE.start_s,
    )


def wycen_mutacje(kroki: Sequence[KrokSkilla], czasy: czasy_ci.Czasy) -> Wycena:
    """Kroki skilli na torze ``MUTACJE``: skrypt mutacji podzielny na najwyżej tyle części, ile ma mutacji, podstawa na
    tyle, ile mówi jej ``ci-czesci``, a bez niego wcale. Krok z częściami ustalonymi przez zakres (``KrokSkilla.czesci``)
    biegnie dokładnie nimi, każda osobną jednostką."""

    tor = MUTACJE
    pomiary = czasy.tory.get(tor.pomiary, {})
    zmierzone = {klucz: s for klucz in pomiary if klucz.startswith("skill:") and (s := czasy.praca(tor.pomiary, klucz)) is not None}
    domyslny = statistics.median(zmierzone.values()) if zmierzone else DOMYSLNIE.krok_skilla_s
    koszty = {f"skill:{w.krok.key}": zmierzone.get(f"skill:{w.krok.key}", domyslny) for w in kroki}
    narzuty = [z[f"narzut:{tor.szablon}"] for z in czasy.zadania(tor.pomiary) if f"narzut:{tor.szablon}" in z]
    podzielne = [w.krok for w in kroki if (w.krok.verdict or w.krok.parts > 1) and not w.czesci]
    ustalone = {f"skill:{w.krok.key}#{k}/{n}": koszty[f"skill:{w.krok.key}"] / n for w in kroki for k, n in w.czesci}
    return Wycena(
        tor,
        {f"skill:{krok.key}": koszty[f"skill:{krok.key}"] for krok in podzielne},
        {f"skill:{w.krok.key}": koszty[f"skill:{w.krok.key}"] for w in kroki if w.krok not in podzielne and not w.czesci} | ustalone,
        statistics.median(narzuty) if narzuty else DOMYSLNIE.narzut_mutacji_s,
        # Wybór kroków i start Pythona przed pierwszym krokiem: do 1 s w runach main 40297447225–40308056465.
        0.0,
        {f"skill:{krok.key}": krok.parts for krok in podzielne},
        frozenset(f"skill:{w.krok.key}" for w in kroki if w.krok.browser),
    )


def _lpt(jednostki: Iterable[Jednostka], n: int) -> list[list[Jednostka]]:
    """Najdłuższa jednostka do zadania o najmniejszej sumie, remis po kluczu i numerze zadania."""

    zadania: list[list[Jednostka]] = [[] for _ in range(n)]
    sumy = [0.0] * n
    for jednostka in sorted(jednostki, key=lambda j: (-j.s, j.klucz)):
        najlzejsze = sumy.index(min(sumy))
        zadania[najlzejsze].append(jednostka)
        sumy[najlzejsze] += jednostka.s
    return zadania


def _pojemnosc(wycena: Wycena, cel_s: float) -> float:
    return cel_s - wycena.narzut_s - wycena.start_s - DOMYSLNIE.koniec_s


def _upakuj(wycena: Wycena, cel_s: float) -> list[list[Jednostka]]:
    """Najmniej zadań toru, z których każde mieści się w ``cel_s``; jednostka dłuższa od celu stoi sama."""

    pojemnosc = _pojemnosc(wycena, cel_s)
    jednostki = wycena.jednostki(pojemnosc)
    n = max(1, math.ceil(sum(j.s for j in jednostki) / pojemnosc)) if pojemnosc > 0 else len(jednostki)
    while True:
        zadania = _lpt(jednostki, n)
        if n >= len(jednostki) or max(sum(j.s for j in zadanie) for zadanie in zadania) <= pojemnosc:
            return [zadanie for zadanie in zadania if zadanie]
        n += 1


def _kolejnosc(jednostka: Jednostka) -> tuple[bool, float, str, bool, str]:
    """Najdłuższe pliki pierwsze, bo xdist zaczyna od nich, kroki CI po pytest, a podstawa skilla przed jego skryptami."""

    if jednostka.klucz.startswith("skill:"):
        skill, _, krok = jednostka.klucz.removeprefix("skill:").partition("/")
        return (False, 0.0, skill, krok != "ci", jednostka.klucz)
    return (jednostka.klucz.startswith("krok:"), -jednostka.s, "", False, jednostka.klucz)


def _limit_runu(zdarzenie: Zdarzenie) -> int:
    return ZADANIA_RUNU if zdarzenie is Zdarzenie.PULL_REQUEST else ZADANIA_RUNU_MAIN


def rozplanuj(wyceny: Sequence[Wycena], zdarzenie: Zdarzenie, runy: tuple[int, ...] = (), bledy: tuple[str, ...] = ()) -> Plan:
    """Najmniej zadań na tor przy celu ``CEL_S``; gdy run przekroczyłby limit zadań zdarzenia (``ZADANIA_RUNU`` albo
    ``ZADANIA_RUNU_MAIN``), cel wszystkich torów rośnie o ``KROK_CELU_S``. Tor bez pracy nie ma zadań."""

    limit = _limit_runu(zdarzenie) - STALE_ZADANIA
    if limit < sum(bool(wycena.podzielne or wycena.niepodzielne) for wycena in wyceny):
        raise ValueError(f"limit {_limit_runu(zdarzenie)} zadań runu nie mieści po jednym zadaniu na tor z pracą")
    cel = CEL_S
    podzial = [_upakuj(wycena, cel) for wycena in wyceny]
    while sum(map(len, podzial)) > limit:
        cel += KROK_CELU_S
        podzial = [_upakuj(wycena, cel) for wycena in wyceny]
    zadania = []
    for wycena, tor in zip(wyceny, podzial, strict=True):
        for numer, jednostki in enumerate(tor, start=1):
            zadania.append(
                Zadanie(
                    id=f"{wycena.tor.nazwa}-{numer}",
                    tor=wycena.tor.nazwa,
                    nazwa=wycena.tor.zadanie.format(numer=numer, liczba=len(tor)),
                    jednostki=tuple(j.klucz for j in sorted(jednostki, key=_kolejnosc)),
                    sciana_s=round(wycena.narzut_s + wycena.start_s + sum(j.s for j in jednostki) + DOMYSLNIE.koniec_s, 1),
                    przegladarka=any(j.klucz.partition("#")[0] in wycena.przegladarka for j in jednostki),
                )
            )
    return Plan(zdarzenie, cel, runy, tuple(zadania), bledy)


def _git(*argumenty: str) -> str:
    return subprocess.run(["git", *argumenty], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _katalog_czasow() -> Path:
    return (ROOT / _git("rev-parse", "--git-common-dir").strip() / "czasy-ci").resolve()


def _wypisz(plan: Plan, praca: ZakresRunu, wyceny: Sequence[Wycena]) -> None:
    run = STALE_ZADANIA + len(plan.zadania)
    zrodlo = ", ".join(map(str, plan.runy)) or "brak (wagi domyślne)"
    print(f"PLAN CI | {plan.zdarzenie} | {praca.zrodlo} | cel {plan.cel_s:.0f} s | {run} zadań runu (limit {_limit_runu(plan.zdarzenie)}) | czasy z runów main: {zrodlo}")
    for wycena in wyceny:
        # Najdłuższa jednostka po podziale to dolna granica ściany zadania toru: celu poniżej niej plan nie osiągnie.
        najdluzsza = max(wycena.jednostki(_pojemnosc(wycena, plan.cel_s)), key=lambda j: (j.s, j.klucz), default=None)
        dopisek = f", najdłuższa jednostka {najdluzsza.klucz} {najdluzsza.s:.0f} s" if najdluzsza else ""
        print(f"{wycena.tor.nazwa}: narzut {wycena.narzut_s:.0f} s, start {wycena.start_s:.0f} s{dopisek}")
        for zadanie in (z for z in plan.zadania if z.tor == wycena.tor.nazwa):
            pliki = sum(klucz.startswith("pytest:") for klucz in zadanie.jednostki)
            reszta = [klucz for klucz in zadanie.jednostki if "#" in klucz or not klucz.startswith("pytest:")]
            opis = " ".join([f"{pliki} plików"] * bool(pliki) + reszta + ["+ Chromium"] * zadanie.przegladarka)
            print(f"  {zadanie.nazwa}: {zadanie.sciana_s:.0f} s | {opis}")
    for nazwa, powod in praca.bledy:
        print(f"FAIL {nazwa}: {powod}")
    for wybrany in praca.wybrane:
        print(f"WYBRANY {wybrany.krok.name} ({wybrany.powod})" if wybrany.powod else f"WYBRANY {wybrany.krok.name}")
    for krok, powod in praca.pominiete:
        print(f"POMINIĘTY {krok.name}: {powod}")
    print(f"PLAN CI DIGEST | {plan.digest}")


def _plan(args: argparse.Namespace) -> int:
    katalog = args.czasy or _katalog_czasow()
    czasy = czasy_ci.z_mainu(katalog, odswiez_po_s=0 if args.czasy else czasy_ci.ODSWIEZ_S)
    if czasy.blad:
        print(f"CZASY CI | {czasy.blad}; plan waży pracę bez pomiaru domyślnie")
    praca = zakres(args.zdarzenie, frozenset() if args.zdarzenie is Zdarzenie.PUSH else changed_since(ROOT, args.baza), ROOT)
    wyceny = [*(wycen(tor, praca.pliki, czasy) for tor in praca.tory), wycen_mutacje(praca.wybrane, czasy)]
    plan = rozplanuj(wyceny, args.zdarzenie, czasy.runy, tuple(f"{nazwa}: {powod}" for nazwa, powod in praca.bledy))
    _wypisz(plan, praca, wyceny)
    if args.wyjscie:
        args.wyjscie.parent.mkdir(parents=True, exist_ok=True)
        args.wyjscie.write_text(plan.do_json(), encoding="utf-8")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            for szablon in dict.fromkeys(tor.szablon for tor in (*TORY, MUTACJE)):
                plik.write(f"{szablon}={json.dumps(plan.macierz(szablon), ensure_ascii=False)}\n")
    return 0


# --- wykonanie ---


def _pytest(pliki: Mapping[str, list[tuple[int, int]]]) -> tuple[str, ...]:
    czesci = {plik: {"n": udzialy[0][1], "udzialy": sorted(k for k, _ in udzialy)} for plik, udzialy in pliki.items() if udzialy}
    CZESCI.parent.mkdir(parents=True, exist_ok=True)
    CZESCI.write_text(json.dumps(czesci, indent=1), encoding="utf-8")
    # Bez '=' w argumentach: shim py (cmd) dzieli argument na '='.
    return (sys.executable, "-m", "pytest", "-n", "auto", "-p", "tools.ci.pytest_czesc", "--czesci", str(CZESCI), *pliki, "--junitxml", str(JUNIT))


def _polecenia(krok: Krok) -> list[tuple[tuple[str, ...], float]]:
    wartosci = {
        "{python}": sys.executable,
        "{temp}": os.environ.get("RUNNER_TEMP", tempfile.gettempdir()),
        "{podsumowanie}": os.environ.get("GITHUB_STEP_SUMMARY", os.devnull),
    }

    def wstaw(argument: str) -> str:
        for znacznik, wartosc in wartosci.items():
            argument = argument.replace(znacznik, wartosc)
        return argument

    return [(tuple(map(wstaw, polecenie.split())), limit) for polecenie, limit in zip(krok.polecenia, krok.limity_s, strict=True)]


def _uruchom(nazwa: str, polecenia: Sequence[tuple[tuple[str, ...], float]], po_limicie: str = "") -> dict[str, object]:
    """Polecenia po kolei do pierwszej porażki; wyjście na bieżąco, a drzewo procesów ginie z limitem z linią ``LIMIT``
    i dopiskiem ``po_limicie``."""

    print(f"== {nazwa}", flush=True)
    start, status = time.monotonic(), "ok"
    for polecenie, limit in polecenia:
        try:
            kod = potomne.run(polecenie, cwd=ROOT, timeout=limit, echo=True).returncode
        except subprocess.TimeoutExpired:
            program = " ".join(polecenie[1:3]) if polecenie[1] == "-m" else polecenie[1]
            print(f"LIMIT | {nazwa}: {program} przerwany po limicie {limit:.0f} s{po_limicie}", flush=True)
            kod = None
        if kod != 0:
            status = "fail"
            break
    s = round(time.monotonic() - start, 1)
    print(f"{'OK  ' if status == 'ok' else 'FAIL'} {nazwa} ({s:.0f} s)", flush=True)
    return {"klucz": nazwa, "s": s, "status": status}


def _krok_skilla(klucz: str, znalezione: Mapping[str, Step]) -> dict[str, object]:
    """Krok skilla albo część ``#k/n`` skryptu mutacji; wynik zgłasza pod kluczem całego kroku, jak udział pliku testów."""

    nazwa, _, czesc = klucz.partition("#")
    print(f"== {klucz}", flush=True)
    start = time.monotonic()
    krok = znalezione.get(nazwa)
    powod = "planu nie ma wśród kroków skilli" if krok is None else mutacje_skilli.run(krok, env={mutacje.PART: czesc} if czesc else None)
    s = round(time.monotonic() - start, 1)
    print(f"OK   {klucz} ({s:.0f} s)" if powod is None else f"FAIL {klucz} ({s:.0f} s): {powod}", flush=True)
    return {"klucz": nazwa, "s": s, "status": "ok" if powod is None else "fail"}


def _krok_pytest(plan: Plan, zadanie: Zadanie, pliki: Mapping[str, list[tuple[int, int]]]) -> dict[str, object]:
    """Pytest zadania z limitem ``limit_pytest_s``; na pull request po porażce raz same testy, które padły. Potem wynik
    testów z kwarantanny."""

    start, limit = time.monotonic(), limit_pytest_s(zadanie)
    # Linia limitu mówi, że krok przerwał limit, a nie porażka testu, i gdzie szukać miejsca zawieszenia.
    po_limicie = (
        f" ({ZAPAS_PYTEST:.0f} × ściana zadania {zadanie.sciana_s:.0f} s z planu, najmniej {LIMIT_PYTEST_MIN_S} s): to nie porażka testu, tylko"
        " test albo proces, który się zawiesił; test, który wisiał ponad faulthandler_timeout z pyproject.toml, zostawił wyżej"
        " stosy swoich wątków, a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia"
    )
    status = _uruchom("krok:pytest", [(_pytest(pliki), limit)], po_limicie)["status"]
    if status != "ok" and plan.zdarzenie is Zdarzenie.PULL_REQUEST and (testy := niestabilne_testy.padniete(JUNIT)):
        if len(testy) > PONOWIENIE_NAJWIECEJ:
            print(f"PONOWIENIE | bez ponowienia: padło {len(testy)} testów, a flaky testy to najwyżej {PONOWIENIE_NAJWIECEJ}", flush=True)
        elif obce := [test for test in testy if not niestabilne_testy.zgloszalny(test)]:
            print(f"PONOWIENIE | bez ponowienia: id testu, którego nie da się zgłosić w issue: {', '.join(obce)}", flush=True)
        elif _ponow(zadanie, testy):
            status = "ok"
    sha, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_kwarantanne(ZapisKwarantanny(zadanie.id, proba, sha, niestabilne_testy.wyniki_kwarantanny(JUNIT)))
    return {"klucz": "krok:pytest", "s": round(time.monotonic() - start, 1), "status": status}


def _ponow(zadanie: Zadanie, testy: Sequence[str]) -> bool:
    """Testy, które padły, raz jeszcze w jednym procesie; przejście każdego to flaky test w ``niestabilne_testy.FLAKY_TESTY``."""

    polecenie = (sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *testy, "--junitxml", str(PONOWIENIE))
    if _uruchom("ponowienie", [(polecenie, PONOWIENIE_LIMIT_S)])["status"] != "ok" or not niestabilne_testy.po_ponowieniu(JUNIT, PONOWIENIE, testy):
        return False
    print(f"FLAKY TESTY | przeszły po ponowieniu: {', '.join(testy)}", flush=True)
    sha, run, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ID", "0")), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_flaky_testy([FlakyTest(test, zadanie.nazwa, sha, run, proba) for test in testy])
    return True


def wykonaj(plan: Plan, zadanie_id: str) -> int:
    """Pytest z plikami i udziałami zadania, potem jego kroki CI i kroki skilli po kolei, także po porażce. Kod 1, gdy
    coś padło."""

    zadanie = next((z for z in plan.zadania if z.id == zadanie_id), None)
    if zadanie is None:
        print(f"WYKONANIE FAIL | plan {plan.digest[:12]} nie ma zadania {zadanie_id}")
        return 1
    pliki: dict[str, list[tuple[int, int]]] = defaultdict(list)
    kroki = []
    skille = []
    for klucz in zadanie.jednostki:
        nazwa, _, udzial = klucz.partition("#")
        if nazwa.startswith("pytest:"):
            k, _, n = udzial.partition("/")
            pliki[nazwa.removeprefix("pytest:")] += [(int(k), int(n))] if udzial else []
        elif nazwa.startswith("skill:"):
            skille.append(klucz)
        else:
            kroki.append(KROKI[nazwa.removeprefix("krok:")])
    wyniki = [_krok_pytest(plan, zadanie, pliki)] if pliki else []
    wyniki += [_uruchom(f"krok:{krok.nazwa}", _polecenia(krok)) for krok in kroki]
    if skille:
        # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
        znalezione = {f"skill:{krok.key}": krok for krok in steps({})}
        wyniki += [_krok_skilla(klucz, znalezione) for klucz in skille]
    WYKONANIE.parent.mkdir(parents=True, exist_ok=True)
    WYKONANIE.write_text(json.dumps({"plan": plan.digest, "zadanie": zadanie.id, "jednostki": wyniki}, indent=1), encoding="utf-8")
    padly = [str(wynik["klucz"]) for wynik in wyniki if wynik["status"] != "ok"]
    print(f"WYKONANIE FAIL | {', '.join(padly)}" if padly else f"WYKONANIE OK | {zadanie.nazwa}")
    return 1 if padly else 0


# --- Required ---


def werdykt(plan: Plan | None, wyniki_zadan: Mapping[str, str], zapisy: Sequence[czasy_ci.Zapis], *, brak_planu: str = "") -> list[str]:
    """Przyczyny czerwonego Required; pusta lista to zielony."""

    przyczyny = []
    if plan is None:
        przyczyny.append(f"plan CI: {brak_planu or 'brak planu'}; zadania pytest i Mutation checks nie miały pracy")
    uruchomione = {} if plan is None else {szablon: False for szablon in Z_PLANU}
    if plan is not None:
        tory = {tor.nazwa: tor.szablon for tor in (*TORY, MUTACJE)}
        uruchomione |= {tory[zadanie.tor]: True for zadanie in plan.zadania}
    for nazwa, wynik in wyniki_zadan.items():
        if wynik != "success" and not (wynik == "skipped" and uruchomione.get(nazwa) is False):
            przyczyny.append(f"{nazwa}={wynik}")
    if plan is None:
        return przyczyny
    przyczyny += [f"mutacje skilli: {blad}" for blad in plan.bledy]
    przyczyny += _niepelne_czesci(plan)
    ostatnie: dict[str, czasy_ci.Zapis] = {}
    for zapis in zapisy:
        if zapis.plan == plan.digest and zapis.zadanie_planu is not None:
            if zapis.zadanie_planu not in ostatnie or zapis.proba > ostatnie[zapis.zadanie_planu].proba:
                ostatnie[zapis.zadanie_planu] = zapis
    for zadanie in plan.zadania:
        if (ostatni := ostatnie.get(zadanie.id)) is None:
            przyczyny.append(f"{zadanie.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły")
            continue
        # Udział pliku i węzeł testu zapis czasów zgłasza jako cały plik (junit zna tylko plik testu).
        zaplanowane = {klucz.partition("#")[0].partition("::")[0] for klucz in zadanie.jednostki}
        if brak := sorted(zaplanowane - {jednostka.klucz for jednostka in ostatni.jednostki}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki bez wyniku: {', '.join(brak)}")
        # Druga linia obrony, gdyby zadanie z porażką skończyło się sukcesem.
        if padly := sorted(zaplanowane & {jednostka.klucz for jednostka in ostatni.jednostki if jednostka.status != "ok"}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki z porażką: {', '.join(padly)}")
    return przyczyny


def _niepelne_czesci(plan: Plan) -> list[str]:
    """Jednostki podzielone w planie, których części ``#k/n`` z zadań jednego toru nie są dokładnie raz każdą z 1..n."""

    czesci: dict[tuple[str, str], list[str]] = defaultdict(list)
    for zadanie in plan.zadania:
        for klucz in zadanie.jednostki:
            nazwa, _, czesc = klucz.partition("#")
            if czesc:
                czesci[(zadanie.tor, nazwa)].append(czesc)
    przyczyny = []
    for (tor, nazwa), lista in sorted(czesci.items()):
        n = lista[0].partition("/")[2]
        calosc = [f"{k}/{n}" for k in range(1, int(n) + 1)] if n.isdigit() else []
        if sorted(lista) != sorted(calosc):
            przyczyny.append(f"plan CI: części {', '.join(sorted(lista))} jednostki {nazwa} na torze {tor} nie są całością 1..{n}")
    return przyczyny


def _werdykt(args: argparse.Namespace) -> int:
    plan, brak = None, ""
    try:
        plan = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        brak = f"{args.plan.as_posix()} nieczytelny ({error})"
    zapisy = []
    for sciezka in sorted(args.zapisy.rglob("*.json")) if args.zapisy.is_dir() else []:
        try:
            zapisy.append(czasy_ci.wczytaj(sciezka))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"CZASY CI FAIL | {sciezka.name}: {error!r}")
    wyniki = {zadanie: need["result"] for zadanie, need in json.loads(os.environ["NEEDS"]).items()}
    if przyczyny := werdykt(plan, wyniki, zapisy, brak_planu=brak):
        print("\n".join(f"REQUIRED FAIL | {przyczyna}" for przyczyna in przyczyny))
        return 1
    assert plan is not None
    jednostki = sum(len(zadanie.jednostki) for zadanie in plan.zadania)
    print(f"REQUIRED OK | {len(wyniki)} zadań, {len(plan.zadania)} zadań z planu {plan.digest[:12]}, {jednostki} jednostek")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Plan runu: zadania pytest i Mutation checks (zadanie plan albo lokalnie).")
    plan.add_argument("--zdarzenie", type=Zdarzenie, choices=list(Zdarzenie), default=Zdarzenie.PULL_REQUEST)
    plan.add_argument(
        "--baza",
        default="origin/main",
        help="Od czego na pull request i nocą liczy się zmiana: wybór plików pytest, E2E i straży czasu i wybór kroków skilli (w CI HEAD^1, nocą baza nocy).",
    )
    plan.add_argument("--czasy", type=Path, help="Katalog artefaktów czasy-ci, pobieranych od nowa (domyślnie .git/czasy-ci).")
    plan.add_argument("--wyjscie", type=Path)
    wykonanie = polecenia.add_parser("wykonaj", help="Jednostki jednego zadania planu (w zadaniu pytest albo Mutation checks).")
    wykonanie.add_argument("--plan", type=Path, required=True)
    wykonanie.add_argument("--zadanie", required=True)
    sad = polecenia.add_parser("werdykt", help="Required CI status: zadania i jednostki wobec planu (env NEEDS).")
    sad.add_argument("--plan", type=Path, required=True)
    sad.add_argument("--zapisy", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.polecenie == "plan":
        return _plan(args)
    if args.polecenie == "werdykt":
        return _werdykt(args)
    try:
        wczytany = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"WYKONANIE FAIL | plan {args.plan.as_posix()}: {error}")
        return 1
    return wykonaj(wczytany, args.zadanie)


if __name__ == "__main__":
    raise SystemExit(main())
