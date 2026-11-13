"""Drukuje plan runu CI gałęzi (plan --baza origin/main): zadania pytest i Mutation checks, ich pliki i kroki skilli; użyj przed pushem albo gdy CI biegło inaczej.

Plan CI: ile zadań pytest i Mutation checks startuje w runie ``ci.yml`` i co biegnie w każdym.

Co biegnie, wyznacza zakres runu (``tools/lib/zakres_runu.py``, ADR 0020, ADR 0021) dla zdarzenia (``pull_request``,
``push`` albo ``noc``, workflow ``mutacje-nocne.yml``) i zmiany od bazy: tory pytest z krokami CI (E2E, straż czasu) i
pliki testów na każdym, oraz kroki skilli, które biegną, z powodem. Plan tylko wycenia i pakuje ten zakres: pytest na
torach zakresu, a kroki skilli na torze ``MUTACJE`` (Windows 3.14, zadania Mutation checks), każda podstawa ``ci:`` i
każdy skrypt mutacji osobno, a krok z częściami ustalonymi przez zakres (nocą każda część każdej liczby części podstawy
z ``ci-czesci``) każdą z nich. Koszt jednostki to ściana, którą dodaje do zadania: plik waży sumę czasów swoich testów przez
``WORKERY`` workerów xdist, krok swój czas. Czasy to mediany z ostatnich runów main (``tools/lib/czasy_ci.py``), a toru bez pomiarów, który zastąpił
inny (``POMIARY_ZASTEPCZE``), czasy tamtego. Plik albo
krok skilla bez pomiaru waży medianę zmierzonych jednostek tego rodzaju na torze, a bez żadnych pomiarów wagę z
``DOMYSLNIE``: plan to wypisuje i biegnie dalej, bo brak czasów psuje tylko równowagę zadań, nie zbiór pracy.

Ściana zadania to narzut (od startu zadania do pracy), start pytest, suma kosztów jego jednostek i koniec zadania;
narzut i start też są z pomiarów. Plan dzieli każdy tor na najmniej zadań o ścianie najwyżej ``cel_s`` (LPT: najdłuższa jednostka do
zadania o najmniejszej sumie). Plik dłuższy niż zadanie dzieli się na k udziałów o tej samej wadze, najwyżej tyle, ile
testów policzyły mu runy main (``Czasy.testy``), bo udział bez testu nie zgłasza wyniku i czerwieni ``Required CI
status``. Bez tej liczby (czasy-ci sprzed jej zapisu) plik dzieli się tylko po czasie: cały, niepodzielny plik
podniósłby cel wszystkich torów do swojej ściany (okno 22e6fe616, cel 615 s). Udział k biegnie z ``-p tools.lib.pytest_czesc`` (testy pliku posortowane po id, po kolei). Skrypt mutacji dłuższy niż zadanie dzieli się tak samo na
najwyżej tyle części, ile ma mutacji: część biegnie z ``MUTACJE_CZESC=k/n`` (``tools/lib/silnik_mutacji.py``), z podstawą
poleceń swoich mutacji. Podstawa ``ci:`` z ``ci-czesci: <n>`` dzieli się tak samo na najwyżej n części (część k
skrypt bierze z ``MUTACJE_CZESC=k/n``, ``tools/lib/skrypt_skilla.py``), a bez niego nie. Plan drukuje najdłuższą jednostkę
każdego toru po podziale: poniżej niej ściana zadania nie zejdzie.
Zadanie Mutation checks instaluje Chromium tylko wtedy, gdy ma krok skilla, którego skrypty importują Playwright, a
zadanie pytest tylko wtedy, gdy ma plik testów, który sięga Chromium dla testów (``PRZEGLADARKA``). Gdy
run (``STALE_ZADANIA``, zadania pytest i Mutation checks) przekroczyłby limit zadań swojego zdarzenia
(``ZADANIA_RUNU`` na pull request, ``ZADANIA_RUNU_MAIN`` na pushu, ``ZADANIA_RUNU_NOCY`` nocą), cel wszystkich torów
rośnie co ``KROK_CELU_S``.

Plan (``tools/lib/plan_runu.py``) zapisuje się w pliku ``--wyjscie``, a macierze zadań w ``GITHUB_OUTPUT``: każde zadanie
wykonuje swoje jednostki (``tools/ci/wykonaj_zadanie.py``), a ``Required CI status`` sprawdza je wobec planu
(``tools/ci/werdykt_required.py``). Zadanie pytest dostaje w macierzy ``limit_minut`` (``timeout-minutes`` w ``ci.yml``),
sumę limitów swoich kroków z zapasem, więc GitHub zabija je dopiero wtedy, gdy zawiesi się coś poza krokami z limitem.

    python3 tools/plan_ci.py plan --zdarzenie pull_request --baza HEAD^1 --czasy .ci-plan/czasy --wyjscie .ci-plan/plan.json
    python3 tools/plan_ci.py plan --zdarzenie noc --baza <baza nocy> --czasy .ci-plan/czasy --wyjscie .ci-plan/plan.json

Lokalnie plan na czasach z ``.git/czasy-ci`` (wspólnych z ``tools/szybko.py``) drukuje zadania i ich prognozę:

    .venv/bin/python tools/plan_ci.py plan --baza origin/main
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import czasy_ci
from github import GitHub
import jednostka
from jednostka import Klucz, Rodzaj
from plan_runu import Plan, Zadanie
from repo import BASE, ROOT
from wplyw_zmiany import changed_since
from zakres_runu import KROKI, MUTACJE, RDZENIE_RUNNERA, TORY, KrokSkilla, Tor, ZakresRunu, Zdarzenie, zakres

WORKERY = RDZENIE_RUNNERA  # pytest -n auto
# W symulacji 60 PR (29.10) cel 60, 75 i 90 s daje bramce ten sam p50 i p90, bo ścianę trzyma jednostka, której plan
# nie dzieli (część podstawy skilla, krok E2E, długi test), a 90 s najmniej zadań: stały koszt zadania pytest to ok. 40 s.
CEL_S = 90.0
KROK_CELU_S = 5.0
# Organizacja ma 60 zadań naraz ze wszystkich workflowów (plan Team od 26.10): run pull request bierze najwyżej 40, a
# noc 20 (ADR 0021). Push do main bierze 25 (ADR 0020, Z6): krótszy run main skraca czas od merge'a do werdyktu, a
# największy run PR i pełne CI main razem przekraczają 60 tylko o 5 zadań, rzadko i krótko.
ZADANIA_RUNU = 40
ZADANIA_RUNU_MAIN = 25
ZADANIA_RUNU_NOCY = 20
# Zadania ci.yml o stałej liczbie (plan, Frontend, Ruff i mypy, Required).
STALE_ZADANIA = 4


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
# Tor windows-3.13 zastąpił 13.11 tor windows-3.11 (ADR 0020). Póki czasy-ci nie mają pomiarów toru, plan waży jego
# pracę czasami toru, który zastąpił, bo z wag domyślnych dzieli bramkę na więcej zadań (wzorcowy PR L z
# tests/test_ksztalt_bramki.py: 9 zadań zamiast 6). Usuń 27.11.2026, gdy czasy-ci mają już tylko windows-3.13, razem z
# przemianowaniem toru w zamrożonych czasach tests/fixtures/ksztalt_bramki/czasy-ci.
POMIARY_ZASTEPCZE = {"windows-3.13": "windows-3.11"}


@dataclass(frozen=True)
class Jednostka:
    """Praca, którą plan daje zadaniu, pod napisem swojego ``jednostka.Klucz``."""

    klucz: str
    s: float  # ściana, którą dodaje do zadania


@dataclass(frozen=True)
class Wycena:
    """Koszty jednego toru: jednostki przed podziałem, narzut i start pracy zadania."""

    tor: Tor
    podzielne: Mapping[str, float]  # plik testów albo skrypt mutacji -> ściana całości
    niepodzielne: Mapping[str, float]  # węzeł testu, krok CI albo podstawa skilla
    narzut_s: float
    start_s: float
    czesci: Mapping[str, int] = field(default_factory=dict)  # najwięcej części jednostki podzielnej (plik: testy, skrypt: mutacje)
    przegladarka: frozenset[str] = frozenset()  # jednostki, które potrzebują Chromium

    def jednostki(self, pojemnosc_s: float) -> list[Jednostka]:
        """Jednostki podzielne dłuższe niż ``pojemnosc_s`` w częściach, które się w niej mieszczą, i niepodzielne."""

        wynik = [Jednostka(klucz, s) for klucz, s in self.niepodzielne.items()]
        for klucz, s in self.podzielne.items():
            k = max(1, math.ceil(s / pojemnosc_s)) if pojemnosc_s > 0 else 1
            k = min(k, self.czesci.get(klucz, k))
            wynik += [Jednostka(klucz, s)] if k == 1 else [Jednostka(str(czesc), s / k) for czesc in Klucz.z_tekstu(klucz).czesci(k)]
        return wynik


def wycen(tor: Tor, pliki: Sequence[str], czasy: czasy_ci.Czasy, przegladarka: frozenset[str] = frozenset()) -> Wycena:
    """Plik testów jest podzielny na najwyżej tyle udziałów, ile testów policzyły mu runy main (bez tej liczby tylko po
    czasie), a węzeł ``plik::test`` nie i waży najwyżej tyle, co typowy plik.

    ``przegladarka``: pliki testów, które potrzebują Chromium; ich jednostki (udziały, węzły) dostają je w zadaniu.
    """

    pomiary = tor.pomiary if czasy.tory.get(tor.pomiary) else POMIARY_ZASTEPCZE.get(tor.pomiary, tor.pomiary)
    koszty = czasy.koszty(pomiary)
    testy = {klucz: czasy.testy(pomiary, klucz) for klucz in (jednostka.pytest(plik) for plik in pliki if "::" not in plik)}
    domyslny = koszty.typowy(DOMYSLNIE.plik_s)
    kroki = {jednostka.krok(nazwa): czasy.praca(pomiary, jednostka.krok(nazwa)) or KROKI[nazwa].domyslnie_s for nazwa in tor.kroki}
    wezly = {jednostka.pytest(wezel): min(koszty.s(wezel.partition("::")[0], DOMYSLNIE.plik_s), domyslny) / WORKERY for wezel in pliki if "::" in wezel}
    narzut, pytest = jednostka.narzut(tor.szablon), jednostka.krok("pytest")
    zadania = [z for z in czasy.zadania(pomiary) if narzut in z]
    narzuty = [z[narzut] for z in zadania]
    # Start pytest: ściana pytest zadania ponad sumę jego testów na workerach (start, kolekcja, ogon workerów).
    starty = [z[pytest] - sum(s for k, s in z.items() if jednostka.rodzaj(k) is Rodzaj.PYTEST) / WORKERY for z in zadania if pytest in z]
    return Wycena(
        tor,
        {jednostka.pytest(plik): koszty.s(plik, DOMYSLNIE.plik_s) / WORKERY for plik in pliki if "::" not in plik},
        {**wezly, **kroki},
        statistics.median(narzuty) if narzuty else DOMYSLNIE.narzut_s,
        max(0.0, statistics.median(starty)) if starty else DOMYSLNIE.start_s,
        {klucz: liczba for klucz, liczba in testy.items() if liczba},
        przegladarka=frozenset(jednostka.pytest(plik) for plik in pliki if plik.partition("::")[0] in przegladarka),
    )


def wycen_mutacje(kroki: Sequence[KrokSkilla], czasy: czasy_ci.Czasy) -> Wycena:
    """Kroki skilli na torze ``MUTACJE``: skrypt mutacji podzielny na najwyżej tyle części, ile ma mutacji, podstawa na
    tyle, ile mówi jej ``ci-czesci``, a bez niego wcale. Krok z częściami ustalonymi przez zakres (``KrokSkilla.czesci``)
    biegnie dokładnie nimi, każda osobną jednostką."""

    tor = MUTACJE
    pomiary = czasy.tory.get(tor.pomiary, {})
    zmierzone = {klucz: s for klucz in pomiary if jednostka.rodzaj(klucz) is Rodzaj.SKILL and (s := czasy.praca(tor.pomiary, klucz)) is not None}
    domyslny = statistics.median(zmierzone.values()) if zmierzone else DOMYSLNIE.krok_skilla_s
    koszty = {jednostka.skill(w.krok.key): zmierzone.get(jednostka.skill(w.krok.key), domyslny) for w in kroki}
    narzut = jednostka.narzut(tor.szablon)
    narzuty = [z[narzut] for z in czasy.zadania(tor.pomiary) if narzut in z]
    podzielne = [w.krok for w in kroki if (w.krok.verdict or w.krok.parts > 1) and not w.czesci]
    ustalone = {
        str(Klucz(Rodzaj.SKILL, w.krok.key, czesc)): koszty[jednostka.skill(w.krok.key)] / czesc.n for w in kroki for czesc in w.czesci
    }
    return Wycena(
        tor,
        {jednostka.skill(krok.key): koszty[jednostka.skill(krok.key)] for krok in podzielne},
        {jednostka.skill(w.krok.key): koszty[jednostka.skill(w.krok.key)] for w in kroki if w.krok not in podzielne and not w.czesci} | ustalone,
        statistics.median(narzuty) if narzuty else DOMYSLNIE.narzut_mutacji_s,
        # Wybór kroków i start Pythona przed pierwszym krokiem: do 1 s w runach main 40297447225–40308056465.
        0.0,
        {jednostka.skill(krok.key): krok.parts for krok in podzielne},
        frozenset(jednostka.skill(w.krok.key) for w in kroki if w.krok.browser),
    )


def _lpt(jednostki: Iterable[Jednostka], n: int) -> list[list[Jednostka]]:
    zadania: list[list[Jednostka]] = [[] for _ in range(n)]
    sumy = [0.0] * n
    for praca in sorted(jednostki, key=lambda j: (-j.s, j.klucz)):
        najlzejsze = sumy.index(min(sumy))
        zadania[najlzejsze].append(praca)
        sumy[najlzejsze] += praca.s
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


def _kolejnosc(praca: Jednostka) -> tuple[bool, float, str, bool, str]:
    """Najdłuższe pliki pierwsze, bo xdist zaczyna od nich, kroki CI po pytest, a cała podstawa skilla przed jego
    skryptami; część podstawy stoi między nimi po kluczu."""

    klucz = Klucz.z_tekstu(praca.klucz)
    if klucz.rodzaj is Rodzaj.SKILL:
        skill, _, krok = klucz.nazwa.partition("/")
        return (False, 0.0, skill, krok != "ci" or klucz.czesc is not None, praca.klucz)
    return (klucz.rodzaj is Rodzaj.KROK, -praca.s, "", False, praca.klucz)


def _limit_runu(zdarzenie: Zdarzenie) -> int:
    return {Zdarzenie.PULL_REQUEST: ZADANIA_RUNU, Zdarzenie.PUSH: ZADANIA_RUNU_MAIN, Zdarzenie.NOC: ZADANIA_RUNU_NOCY}[zdarzenie]


def rozplanuj(
    wyceny: Sequence[Wycena], zdarzenie: Zdarzenie, runy: tuple[int, ...] = (), bledy: tuple[str, ...] = (), zmienione_wejscia: tuple[str, ...] = ()
) -> Plan:
    """Najmniej zadań na tor przy celu ``CEL_S``; gdy run przekroczyłby limit zadań zdarzenia (``ZADANIA_RUNU``,
    ``ZADANIA_RUNU_MAIN`` albo ``ZADANIA_RUNU_NOCY``), cel wszystkich torów rośnie o ``KROK_CELU_S``. Tor bez pracy nie
    ma zadań."""

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
                    przegladarka=any(str(Klucz.z_tekstu(j.klucz).calosc) in wycena.przegladarka for j in jednostki),
                )
            )
    return Plan(zdarzenie, cel, runy, tuple(zadania), bledy, zmienione_wejscia)


def _wypisz(plan: Plan, praca: ZakresRunu, wyceny: Sequence[Wycena]) -> None:
    run = STALE_ZADANIA + len(plan.zadania)
    zrodlo = ", ".join(map(str, plan.runy)) or "brak (wagi domyślne)"
    print(f"PLAN CI | {plan.zdarzenie} | {praca.zrodlo} | cel {plan.cel_s:.0f} s | {run} zadań runu (limit {_limit_runu(plan.zdarzenie)}) | czasy z runów main: {zrodlo}")
    for wycena in wyceny:
        najdluzsza = max(wycena.jednostki(_pojemnosc(wycena, plan.cel_s)), key=lambda j: (j.s, j.klucz), default=None)
        dopisek = f", najdłuższa jednostka {najdluzsza.klucz} {najdluzsza.s:.0f} s" if najdluzsza else ""
        print(f"{wycena.tor.nazwa}: narzut {wycena.narzut_s:.0f} s, start {wycena.start_s:.0f} s{dopisek}")
        for zadanie in (z for z in plan.zadania if z.tor == wycena.tor.nazwa):
            pliki = sum(klucz.rodzaj is Rodzaj.PYTEST for klucz in zadanie.klucze)
            reszta = [str(klucz) for klucz in zadanie.klucze if klucz.czesc or klucz.rodzaj is not Rodzaj.PYTEST]
            opis = " ".join([f"{pliki} plików"] * bool(pliki) + reszta + ["+ Chromium"] * zadanie.przegladarka)
            print(f"  {zadanie.nazwa}: {zadanie.sciana_s:.0f} s | {opis}")
    for nazwa, powod in praca.bledy:
        print(f"FAIL {nazwa}: {powod}")
    for wybrany in praca.wybrane:
        print(f"WYBRANY {wybrany.krok.name} ({wybrany.powod})" if wybrany.powod else f"WYBRANY {wybrany.krok.name}")
    for krok, powod in praca.pominiete:
        print(f"POMINIĘTY {krok.name}: {powod}")
    if plan.zmienione_wejscia:
        print(f"BEZ PONOWIENIA | {len(plan.zmienione_wejscia)} plików testów z wejściami zmienionymi przez ten PR")
    print(f"PLAN CI DIGEST | {plan.digest}")


def _plan(args: argparse.Namespace, root: Path, github: GitHub) -> int:
    katalog = args.czasy or czasy_ci.katalog_checkoutu(root)
    czasy = czasy_ci.z_mainu(katalog, odswiez_po_s=0 if args.czasy else czasy_ci.ODSWIEZ_S, github=github)
    if czasy.blad:
        print(f"CZASY CI | {czasy.blad}; plan waży pracę bez pomiaru domyślnie")
    praca = zakres(args.zdarzenie, frozenset() if args.zdarzenie is Zdarzenie.PUSH else changed_since(root, args.baza), root)
    wyceny = [*(wycen(tor, praca.pliki, czasy, praca.przegladarka) for tor in praca.tory), wycen_mutacje(praca.wybrane, czasy)]
    bledy = tuple(f"{nazwa}: {powod}" for nazwa, powod in praca.bledy)
    plan = rozplanuj(wyceny, args.zdarzenie, czasy.runy, bledy, tuple(sorted(praca.zmienione_wejscia)))
    _wypisz(plan, praca, wyceny)
    if args.wyjscie:
        args.wyjscie.parent.mkdir(parents=True, exist_ok=True)
        args.wyjscie.write_text(plan.do_json(), encoding="utf-8")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            for szablon in dict.fromkeys(tor.szablon for tor in (*TORY, MUTACJE)):
                plik.write(f"{szablon}={json.dumps(plan.macierz(szablon), ensure_ascii=False)}\n")
    return 0


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, github: GitHub = czasy_ci.GITHUB) -> int:
    """``root`` to checkout, którego zmianę i skille plan wycenia, a ``github`` daje czasy z runów main."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Plan runu: zadania pytest i Mutation checks (zadanie plan albo lokalnie).")
    plan.add_argument("--zdarzenie", type=Zdarzenie, choices=list(Zdarzenie), default=Zdarzenie.PULL_REQUEST)
    plan.add_argument(
        "--baza",
        default=BASE,
        help="Od czego na pull request i nocą liczy się zmiana: wybór plików pytest, E2E i straży czasu i wybór kroków skilli (w CI HEAD^1, nocą baza nocy).",
    )
    plan.add_argument("--czasy", type=Path, help="Katalog artefaktów czasy-ci, pobieranych od nowa (domyślnie .git/czasy-ci).")
    plan.add_argument("--wyjscie", type=Path)
    return _plan(parser.parse_args(argv), root, github)


if __name__ == "__main__":
    raise SystemExit(main())
