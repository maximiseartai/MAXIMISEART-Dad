"""Rozstrzyga D1, NF czy N0, z cienia podstaw w plan.json runów PR i audytu kandydatów (--od, --do, --audyt); użyj po 14 dniach cienia.

Reguła rozstrzygnięcia, zapisana 19.11.2026 przed włączeniem NF (ADR 0020, D1): N0 wygrywa, gdy w ``DNI`` dniach po
merge'u NF kroki skilli NF na pull request złapały mniej niż ``X`` prawdziwych defektów, których pytest nie złapał, a cień
daje N0 oszczędność czekania na PR co najmniej ``OSZCZEDNOSC_MIN`` agent-minut; inaczej zostaje NF. Prawdziwy defekt to
osobna przyczyna porażki, którą potwierdził audyt (decyzja koordynatora programu CI z 19.11 w #2169), bo ``X`` wycenia
jedną ucieczkę na ``main``: jedno czerwone ``main`` i jeden PR naprawy, a dwa PR-y z tą samą przyczyną dałyby ich tyle
samo. Wyrocznia ``main`` (ucieczki z NF i ich czerwień) nie rozstrzyga, bo takie ucieczki przechodzą przy NF i przy N0,
ale pokazuje, czy czerwień ucieczki zgadza się z przyjętą w koszcie. Progi wynikają z danych 11–18.11 (ADR 0020, D1):
koszt ucieczki ``KOSZT_UCIECZKI_MIN`` to mediana czerwieni ``main`` czterech defektów, które przeszły bramkę (58,5 min),
i mediana PR-u naprawy (16,2 min), a ``X`` to oszczędność N0 wobec NF w backteście (830 agent-minut na 14 dni) przez ten
koszt (11,1), w dół; ``OSZCZEDNOSC_MIN`` to ``X`` razy koszt ucieczki. Progi liczą okno ``DNI`` dni, więc okno innej
długości nie ma wyniku.

Kandydat na defekt złapany przez NF to porażka jednego kroku w jednym czerwonym runie PR ``ci.yml``: run bez porażki
zadania pytest, w którym padła jednostka ``skill:`` (linia ``WYKONANIE FAIL`` w logu zadania Mutation checks) z kroków
cienia ``NA_ZYWO`` spoza cienia N0 (``plan.json``, pole ``cien``), a naprawa do następnego runu gałęzi zmienia folder
tego skilla albo ``src/``. Czerwony run to run PR z padłym zadaniem, także anulowany (``cancel-in-progress`` po nowym
pushu), a następny run gałęzi to najbliższy późniejszy run z wynikiem success albo failure, bo głowa runu anulowanego
nie ma naprawy z pushu, który go anulował. Każdy czerwony run ma własnego kandydata, także kolejny run gałęzi z tym samym
krokiem, bo jego porażka może mieć inną przyczynę; w przyczyny grupuje kandydatów audyt. Przypadki porażki kroku skilla
w runie PR okna:

    postać                                                                   | w wyniku
    krok NF spoza N0, pytest przeszedł, naprawa w folderze skilla albo src/  | KANDYDAT NF
    jak wyżej, a każdy plik naprawy kroku zmienił też main między bazami głów | KANDYDAT NF, wymaga audytu
    run anulowany, zanim pytest skończył                                      | kandydat albo niepoliczony, wymaga audytu
    kolejny czerwony run gałęzi z tym samym krokiem                           | osobny kandydat albo niepoliczony
    następny run gałęzi anulowany                                             | naprawa do następnego runu z wynikiem
    bez naprawy, czerwona głowa nie jest przodkiem następnej (rebase, reset)  | NIEPOLICZONY, wymaga audytu
    bez następnego runu z wynikiem w oknie albo z głową, której git nie zna   | NIEPOLICZONY, wymaga audytu
    run bez artefaktu planu, z naprawą                                        | BEZ CIENIA
    run bez artefaktu planu, bez naprawy kroku                                | NIE LICZY SIĘ: nie wiadomo, czy N0 by ją puścił
    naprawa tylko poza folderem skilla i src/, historia nieprzepisana         | NIE LICZY SIĘ (flaky, test, infrastruktura)
    bez zmiany własnej zmiany PR (np. tylko scalenie main), jak wyżej         | NIE LICZY SIĘ (flaky albo naprawa w main)
    padł też pytest; krok spoza NF albo w N0                                  | NIE LICZY SIĘ: pytest złapał; warianty się nie różnią

Każda porażka kroku skilla czerwonego runu stoi w wyniku dokładnie raz, w jednej z tych linii, więc reguła, która
się pomyli, przesuwa porażkę na oczach audytora, a nie gubi jej.

Naprawa to pliki, które zmienia commit bez merge'a osiągalny z następnej głowy, a nie z czerwonej ani z bazy następnej,
i w których zmieniła się własna zmiana PR: treść pliku przy obu głowach różni się poza liniami, które ``main`` zmienił
w tym pliku między bazami głów (baza głowy to jej baza scalenia z ``main`` sprzed scalenia tej głowy). Plik, który
``main`` przemianował między bazami głów (``git diff -M`` baz), przy czerwonej głowie i jej bazie ma ścieżkę sprzed
przemianowania, a przy następnej głowie ścieżkę po nim, także gdy commit naprawy zmienił go pod starą ścieżką przed
scaleniem ``main`` do gałęzi. Rebase, scalenie ``main`` do gałęzi, rozstrzygnięcie konfliktu i amend, które zostawiają
własną zmianę PR, naprawą nie są, którąkolwiek drogą zaktualizowano gałąź. Zmiana tylko w commicie scalenia
(rozstrzygnięcie, które łączy linię ``main`` i PR w nową, plik wygenerowany na nowo) też nie, a ta sama nowa linia
w commicie rebase'u jest naprawą, bo nie różni się od poprawki tej linii. Granica: poprawka, która dodaje, usuwa albo przestawia tylko linie o treści jednej
z linii zmienionych przez ``main`` w tym pliku między bazami (np. pustą linię), naprawą nie jest. Znane luki reguły
naprawy to próbki ``ZNANE_LUKI`` w ``tests/test_cien_podstaw.py`` (linie pliku naprawy przestawione przez ``main``,
naprawa samym usunięciem commitu), a wynik pisze przy nich „wymaga audytu”.

Przy każdym kandydacie i niepoliczonym wynik drukuje klucz porażki (``<run> <krok>``) i dowód do audytu: PR, czerwony
run z padłym krokiem, następny run, adresy obu, inne czerwone runy gałęzi z tym krokiem, a przy każdym pliku naprawy
kroku polecenia własnego diffu PR przy obu głowach (``git diff <baza>...<głowa> -- <plik>``, przy czerwonej głowie po
ścieżce sprzed przemianowania; pełne diffy w ``rekordy.json``) i linie +/-, którymi te diffy się różnią. Audyt
(``--audyt PLIK``) to obiekt JSON: klucz porażki każdego kandydata i niepoliczonego z wyniku → lista nazw przyczyn,
które audyt w niej potwierdził (pusta: nie prawdziwy defekt albo niepewny), a ta sama nazwa przy kilku porażkach to
jedna przyczyna. Audyt bez którejś porażki z wyniku albo z porażką spoza niego to odmowa. Prawdziwe defekty to różne
nazwy przyczyn; bez audytu wynik czeka na audyt, chyba że oszczędność N0 jest pod progiem.
Oszczędność N0: średnia różnica ściany planu NF i N0 z cienia runów PR próbki (co któryś run okna, najwyżej
``--probka``; czerwone runy spoza próbki jej nie przesuwają) razy liczba runów PR okna z wynikiem success albo failure.
Ucieczka z NF (wyrocznia ``main``): run pushu ``main`` z padłą podstawą, którą ostatni run PR-u scalonego od
poprzedniego runu ``main`` miał w cieniu V0, a nie w cieniu NF; czerwień to minuty od końca tego runu do końca
następnego zielonego runu ``main``.

Dane: runy ``ci.yml`` okna (dzień utworzenia, UTC), artefakty ``plan`` (``retention-days: 30`` w ``ci.yml``) czerwonych
runów PR, próbki i scalonych PR-ów, zadania runów PR bez wyniku success i logi ich padłych zadań Mutation checks, a z gita
checkoutu pliki głów PR i ich baz i merge'e ``main`` z numerami PR-ów (brakujące głowy runów pobiera jeden ``git
fetch``). Odpowiedzi API zapisują się w ``<katalog>/api`` (``tools/lib/api_actions.py``), a rekordy z dowodami
w ``<katalog>/rekordy.json``; 14 dni to kilkaset zapytań, a ich liczbę drukuje pierwsza linia wyniku. ``--rekordy
PLIK`` liczy rozstrzygnięcie z zapisanych rekordów bez GitHuba. Wynik kończy linia:

    D1 | złapane przez NF: kandydaci <n> (wymaga audytu <m>), niepoliczone <k>, przyczyny po audycie <p> | oszczędność N0 …
    | wynik: N0 wygrywa|NF zostaje|czeka na audyt|brak: …

    .venv/bin/python tools/cien_podstaw.py --katalog ~/.t3/notes/d1-cien --od 2026-11-20 --do 2026-12-03
    .venv/bin/python tools/cien_podstaw.py --rekordy ~/.t3/notes/d1-cien/rekordy.json --audyt ~/.t3/notes/d1-cien/audyt.json
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from enum import StrEnum
import io
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from typing import Any
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from api_actions import Api, runy
from github import REPO, BladApi, GhApi, GitHub
from jednostka import Klucz, Rodzaj
from plan_runu import ARTEFAKT, PLIK, Plan
import repo
from repo import ROOT
from zakres_runu import NA_ZYWO, Podstawy

GITHUB = GhApi(limit_s=60)
# Progi D1 (ADR 0020, D1), zapisane przed włączeniem NF; zmiana któregoś unieważnia rozstrzygnięcie.
KOSZT_UCIECZKI_MIN = 75.0
X = 11
OSZCZEDNOSC_MIN = X * KOSZT_UCIECZKI_MIN
DNI = 14
# Czerwień main w koszcie ucieczki: wyrocznia main drukuje ją obok swojej mediany.
CZERWIEN_MIN = 59.0
PROBKA = 100
# Linie różnicy własnego diffu PR między głowami na plik naprawy w wyniku; resztę dają polecenia i ``rekordy.json``.
POKAZ_LINII = 20
WYKONANIE_FAIL = re.compile(r"WYKONANIE FAIL \| (.+)")
MERGE_PR = re.compile(r"Merge pull request #(\d+) from [^/\s]+/(\S+)")
# Zadania runu, których porażka to porażka pytest i kroków skilli (nazwy z ``zakres_runu.TORY`` i ``MUTACJE``).
PYTEST, MUTACJE = "pytest (", "Mutation checks ("
# Wyniki runu, który biegł do końca: tylko taki run ma następną głowę z naprawą i liczy się w oszczędności.
SKONCZONE = ("success", "failure")


class Pytest(StrEnum):
    """Zadania pytest czerwonego runu: run anulowany po nowym pushu mógł je przerwać, zanim skończyły."""

    PRZESZEDL = "przeszedł"
    PADL = "padł"
    NIE_SKONCZYL = "nie skończył"


class Wynik(StrEnum):
    N0_WYGRYWA = "N0 wygrywa"
    NF_ZOSTAJE = "NF zostaje"
    CZEKA_NA_AUDYT = "czeka na audyt"
    OKNO = f"brak: progi D1 liczą okno {DNI} dni"


class BladAudytu(ValueError):
    """Plik audytu nie pasuje do wyniku: brak porażki z wyniku, porażka spoza niego albo wartość, która nie jest listą
    nazw przyczyn."""


@dataclass(frozen=True)
class Wariant:
    kroki: tuple[str, ...]  # klucze kroków skilli (``Step.key``), które wariant uruchomiłby na tym runie
    sciana_s: float


@dataclass(frozen=True)
class Glowa:
    run: int
    url: str
    sha: str
    baza: str  # baza scalenia głowy z ``main`` sprzed jej scalenia (``_baza_pr``)


@dataclass(frozen=True)
class PlikNaprawy:
    sciezka: str  # przy następnej głowie
    sciezka_czerwonej: str  # przy czerwonej głowie i jej bazie: inna, gdy ``main`` przemianował plik między bazami głów
    diff_czerwonej: str  # własny diff PR pliku przy czerwonej głowie: ``git diff <baza>...<głowa> -- <plik>``
    diff_nastepnej: str
    main_zmienil: bool  # ``main`` zmienił treść pliku między bazami głów, więc regułę treści myli przestawienie jego linii


@dataclass(frozen=True)
class Naprawa:
    czerwona: Glowa
    nastepna: Glowa
    pliki: tuple[PlikNaprawy, ...]  # pliki, w których własna zmiana PR zmieniła się według reguły treści
    przepisana: bool  # czerwona głowa nie jest przodkiem następnej, więc naprawa mogła usunąć commit bez pliku w ``pliki``

    @property
    def sciezki(self) -> tuple[str, ...]:
        return tuple(plik.sciezka for plik in self.pliki)


@dataclass(frozen=True)
class RunPr:
    run: int
    galaz: str
    pytest: Pytest
    padle: tuple[str, ...]  # kroki skilli z porażką
    # None: run bez kroku z porażką albo bez następnego runu gałęzi z wynikiem w oknie, albo git nie zna którejś głowy
    naprawa: Naprawa | None
    cien: Mapping[str, Wariant] | None  # wariant ``Podstawy`` → jego cień; None: run bez artefaktu planu z cieniem
    probka: bool = False  # run próbki oszczędności
    pr: int | None = None  # numer PR-u gałęzi z merge'a do ``main`` w oknie; None: gałąź bez merge'a w oknie


@dataclass(frozen=True)
class RunMain:
    run: int
    padle: tuple[str, ...]
    pominiete_przez_nf: tuple[str, ...]  # podstawy w cieniu V0, a nie NF, ostatnich runów PR-ów scalonych w ten run
    czerwien_min: float | None


@dataclass(frozen=True)
class Rekordy:
    od: str
    do: str
    pr_runow: int
    pr: tuple[RunPr, ...]
    main: tuple[RunMain, ...]

    @classmethod
    def z_json(cls, tekst: str) -> Rekordy:
        dane = json.loads(tekst)

        def cien(run: dict[str, Any]) -> dict[str, Wariant] | None:
            return None if run["cien"] is None else {w: Wariant(tuple(c["kroki"]), c["sciana_s"]) for w, c in run["cien"].items()}

        def naprawa(n: dict[str, Any] | None) -> Naprawa | None:
            if n is None:
                return None
            return Naprawa(Glowa(**n["czerwona"]), Glowa(**n["nastepna"]), tuple(PlikNaprawy(**p) for p in n["pliki"]), n["przepisana"])

        pr = tuple(
            RunPr(r["run"], r["galaz"], Pytest(r["pytest"]), tuple(r["padle"]), naprawa(r["naprawa"]), cien(r), r["probka"], r["pr"])
            for r in dane["pr"]
        )
        main = tuple(RunMain(r["run"], tuple(r["padle"]), tuple(r["pominiete_przez_nf"]), r["czerwien_min"]) for r in dane["main"])
        return cls(dane["od"], dane["do"], dane["pr_runow"], pr, main)


@dataclass(frozen=True)
class Porazka:
    """Porażka kroku skilla ``krok`` w czerwonym runie PR ``run``: jednostka kandydata, niepoliczonego i audytu."""

    run: RunPr
    krok: str

    @property
    def klucz(self) -> str:
        """Klucz porażki w wyniku i w pliku audytu."""

        return f"{self.run.run} {self.krok}"

    @property
    def naprawiona(self) -> bool:
        return self.run.naprawa is not None and any(_w_naprawie(self.krok, sciezka) for sciezka in self.run.naprawa.sciezki)

    @property
    def powody_audytu(self) -> tuple[str, ...]:
        """Czemu audyt musi rozstrzygnąć porażkę, której reguła naprawy nie umie ocenić; pusta: kandydat tylko do audytu."""

        naprawa = self.run.naprawa
        powody = ["run anulowany, zanim pytest skończył: nie wiadomo, czy pytest by ją złapał"] if self.run.pytest is Pytest.NIE_SKONCZYL else []
        if naprawa is None:
            powody.append("brak następnego runu gałęzi z wynikiem w oknie albo git nie zna jego głowy: naprawa mogła pójść inną gałęzią albo po oknie")
        elif not self.naprawiona:
            powody.append("czerwona głowa nie jest przodkiem następnej (rebase, usunięty commit, reset): naprawa usunięciem commitu nie ma pliku")
        elif all(plik.main_zmienil for plik in naprawa.pliki if _w_naprawie(self.krok, plik.sciezka)):
            powody.append("każdy plik naprawy zmienił też main między bazami głów")
        return tuple(powody)


@dataclass(frozen=True)
class Rozstrzygniecie:
    kandydaci: tuple[Porazka, ...]  # porażki kroków NF z naprawą w folderze skilla albo ``src/``
    niepoliczone: tuple[Porazka, ...]  # porażki kroków NF bez takiej naprawy z przepisaną historią albo bez następnego runu
    bez_cienia: tuple[Porazka, ...]  # porażki z naprawą runów bez artefaktu planu: nie wiadomo, czy N0 by je puścił
    nie_licza_sie: tuple[tuple[Porazka, str], ...]  # pozostałe porażki czerwonych runów, każda z powodem
    przyczyny: Mapping[str, tuple[Porazka, ...]] | None  # przyczyna z audytu → jej porażki; None: bez audytu
    dni: int  # długość okna
    oszczednosc_min: float | None  # None: żaden run próbki nie ma cienia
    probka: int
    ucieczki: tuple[tuple[int, str], ...]  # (run main, podstawa)
    czerwien_min: float | None  # mediana czerwieni runów main z ucieczką

    @property
    def wymaga_audytu(self) -> tuple[Porazka, ...]:
        return tuple(porazka for porazka in self.kandydaci if porazka.powody_audytu)

    @property
    def wynik(self) -> Wynik:
        if self.dni != DNI:
            return Wynik.OKNO
        if self.oszczednosc_min is None or self.oszczednosc_min < OSZCZEDNOSC_MIN:
            return Wynik.NF_ZOSTAJE
        if self.przyczyny is None:
            return Wynik.CZEKA_NA_AUDYT
        return Wynik.N0_WYGRYWA if len(self.przyczyny) < X else Wynik.NF_ZOSTAJE


def rozstrzygnij(rekordy: Rekordy, audyt: Mapping[str, Sequence[str]] | None = None) -> Rozstrzygniecie:
    kandydaci: list[Porazka] = []
    niepoliczone: list[Porazka] = []
    bez_cienia: list[Porazka] = []
    nie_licza_sie: list[tuple[Porazka, str]] = []
    for run in rekordy.pr:
        for porazka in (Porazka(run, krok) for krok in run.padle):
            if run.pytest is Pytest.PADL:
                nie_licza_sie.append((porazka, "padł też pytest: pytest złapał"))
            elif run.cien is None:
                if porazka.naprawiona:
                    bez_cienia.append(porazka)
                else:
                    nie_licza_sie.append((porazka, "run bez artefaktu planu, bez naprawy w folderze skilla ani src/"))
            elif porazka.krok not in run.cien[NA_ZYWO].kroki or porazka.krok in run.cien[Podstawy.N0].kroki:
                nie_licza_sie.append((porazka, "krok spoza NF albo w N0: warianty się nie różnią"))
            elif porazka.naprawiona:
                kandydaci.append(porazka)
            elif run.naprawa is None or run.naprawa.przepisana:
                niepoliczone.append(porazka)
            elif run.naprawa.sciezki:
                nie_licza_sie.append((porazka, f"naprawa tylko poza folderem skilla i src/: {', '.join(run.naprawa.sciezki)}"))
            else:
                nie_licza_sie.append((porazka, "własna zmiana PR przy następnej głowie ta sama co przy czerwonej (np. tylko scalenie main)"))
    roznice = [run.cien[NA_ZYWO].sciana_s - run.cien[Podstawy.N0].sciana_s for run in rekordy.pr if run.probka and run.cien is not None]
    oszczednosc = statistics.mean(roznice) * rekordy.pr_runow / 60 if roznice else None
    ucieczki = tuple((run.run, krok) for run in rekordy.main for krok in run.padle if krok in run.pominiete_przez_nf)
    czerwien = [run.czerwien_min for run in rekordy.main if run.czerwien_min is not None and any(run.run == u for u, _ in ucieczki)]

    def po_galezi(porazki: list[Porazka]) -> tuple[Porazka, ...]:
        return tuple(sorted(porazki, key=lambda porazka: (porazka.run.galaz, porazka.krok, porazka.run.run)))

    return Rozstrzygniecie(
        po_galezi(kandydaci),
        po_galezi(niepoliczone),
        po_galezi(bez_cienia),
        tuple(sorted(nie_licza_sie, key=lambda para: (para[0].run.galaz, para[0].krok, para[0].run.run))),
        None if audyt is None else _przyczyny(kandydaci + niepoliczone, audyt),
        (date.fromisoformat(rekordy.do) - date.fromisoformat(rekordy.od)).days + 1,
        oszczednosc,
        len(roznice),
        ucieczki,
        statistics.median(czerwien) if czerwien else None,
    )


def wczytaj_audyt(tekst: str) -> dict[str, tuple[str, ...]]:
    """Audyt z pliku JSON (docstring modułu); inna postać niż obiekt list nazw przyczyn to ``BladAudytu``."""

    dane = json.loads(tekst)
    if not isinstance(dane, dict) or not all(
        isinstance(przyczyny, list) and all(isinstance(nazwa, str) and nazwa.strip() for nazwa in przyczyny) for przyczyny in dane.values()
    ):
        raise BladAudytu('audyt to obiekt JSON {"<run> <krok>": ["<przyczyna>", …]} z kluczem każdej porażki z wyniku; pusta lista: nie prawdziwy defekt')
    return {klucz: tuple(przyczyny) for klucz, przyczyny in dane.items()}


def _przyczyny(porazki: list[Porazka], audyt: Mapping[str, Sequence[str]]) -> dict[str, tuple[Porazka, ...]]:
    klucze = {porazka.klucz for porazka in porazki}
    if klucze != audyt.keys():
        raise BladAudytu(
            f"audyt nie pasuje do wyniku: bez porażek z wyniku {sorted(klucze - audyt.keys())}, z porażkami spoza wyniku {sorted(audyt.keys() - klucze)}"
        )
    przyczyny: dict[str, list[Porazka]] = {}
    for porazka in porazki:
        for nazwa in dict.fromkeys(audyt[porazka.klucz]):
            przyczyny.setdefault(nazwa, []).append(porazka)
    return {nazwa: tuple(przyczyny[nazwa]) for nazwa in sorted(przyczyny)}


def _w_naprawie(krok: str, sciezka: str) -> bool:
    return sciezka.startswith(("src/", f".agents/skills/{krok.partition('/')[0]}/"))


def wypisz(rekordy: Rekordy, wynik: Rozstrzygniecie) -> list[str]:
    linie = [f"D1 CIEŃ | okno {rekordy.od}–{rekordy.do} ({wynik.dni} dni) | runów PR {rekordy.pr_runow}, z cieniem w próbce {wynik.probka}"]
    numery = {porazka.klucz: f"kandydat {numer}" for numer, porazka in enumerate(wynik.kandydaci, 1)}
    numery |= {porazka.klucz: "niepoliczony" for porazka in wynik.niepoliczone}
    for numer, porazka in enumerate(wynik.kandydaci, 1):
        audyt = f"wymaga audytu: {'; '.join(porazka.powody_audytu)}" if porazka.powody_audytu else "do audytu"
        linie.append(f"KANDYDAT NF {numer}/{len(wynik.kandydaci)} | {porazka.klucz} | {porazka.run.galaz}, {_pr(porazka.run)} | {audyt}")
        linie += _dowod(porazka, wynik, numery)
    for porazka in wynik.niepoliczone:
        linie.append(f"NIEPOLICZONY, wymaga audytu | {porazka.klucz} | {porazka.run.galaz}, {_pr(porazka.run)} | {'; '.join(porazka.powody_audytu)}")
        linie += _dowod(porazka, wynik, numery)
    linie += [f"BEZ CIENIA | {porazka.klucz} | {porazka.run.galaz} (run bez artefaktu planu)" for porazka in wynik.bez_cienia]
    linie += [f"NIE LICZY SIĘ | {porazka.klucz} | {porazka.run.galaz}, {_pr(porazka.run)} | {powod}" for porazka, powod in wynik.nie_licza_sie]
    if wynik.przyczyny is not None:
        policzone = {porazka.klucz for porazki in wynik.przyczyny.values() for porazka in porazki}
        linie += [
            f"PRZYCZYNA {numer}/{len(wynik.przyczyny)} | {nazwa} | {', '.join(porazka.klucz for porazka in porazki)}"
            for numer, (nazwa, porazki) in enumerate(wynik.przyczyny.items(), 1)
        ]
        linie += [f"BEZ PRZYCZYNY | {klucz} (audyt: nie prawdziwy defekt albo niepewny)" for klucz in numery if klucz not in policzone]
    czerwien = {run.run: run.czerwien_min for run in rekordy.main}
    linie += [f"UCIECZKA Z NF | run main {run}: {krok}, czerwień {_min(czerwien[run])}" for run, krok in wynik.ucieczki]
    linie.append(
        f"WYROCZNIA MAIN | ucieczki z NF {len(wynik.ucieczki)}, mediana czerwieni {_min(wynik.czerwien_min)}"
        f" (koszt ucieczki w progu przyjmuje {CZERWIEN_MIN:.0f} min)"
    )
    oszczednosc = "brak cienia" if wynik.oszczednosc_min is None else f"{wynik.oszczednosc_min:.0f} agent-min"
    przyczyny = "brak audytu (--audyt)" if wynik.przyczyny is None else str(len(wynik.przyczyny))
    linie.append(
        f"D1 | złapane przez NF: kandydaci {len(wynik.kandydaci)} (wymaga audytu {len(wynik.wymaga_audytu)}), niepoliczone"
        f" {len(wynik.niepoliczone)}, przyczyny po audycie {przyczyny}; N0 wygrywa poniżej {X} przyczyn"
        f" | oszczędność N0 {oszczednosc} (próg {OSZCZEDNOSC_MIN:.0f}) | wynik: {wynik.wynik}"
    )
    return linie


def _pr(run: RunPr) -> str:
    return "PR bez merge'a w oknie" if run.pr is None else f"PR #{run.pr}"


def _dowod(porazka: Porazka, wynik: Rozstrzygniecie, numery: Mapping[str, str]) -> list[str]:
    """Dowód audytu porażki: oba runy z głowami i bazami, inne czerwone runy gałęzi z tym krokiem, a przy każdym pliku
    naprawy kroku polecenia własnego diffu PR przy obu głowach (pełne diffy są w ``rekordy.json``) i linie +/-, którymi
    te diffy się różnią."""

    krok, naprawa = porazka.krok, porazka.run.naprawa
    inne = [
        f"{inna.run.run} ({numery[inna.klucz]})"
        for inna in (*wynik.kandydaci, *wynik.niepoliczone)
        if (inna.run.galaz, inna.krok) == (porazka.run.galaz, krok) and inna.run.run != porazka.run.run
    ]
    linie = [f"  ten krok padł też w runach tej gałęzi: {', '.join(inne)}"] if inne else []
    if naprawa is None:
        return [f"  czerwony run {porazka.run.run} | padł krok {krok} | następny run: brak", *linie]
    czerwona, nastepna = naprawa.czerwona, naprawa.nastepna
    linie[:0] = [
        f"  czerwony run {czerwona.run} {czerwona.url} | padł krok {krok} | głowa {czerwona.sha[:12]}, baza {czerwona.baza[:12]}",
        f"  następny run {nastepna.run} {nastepna.url} | głowa {nastepna.sha[:12]}, baza {nastepna.baza[:12]}",
    ]
    if poza := [plik.sciezka for plik in naprawa.pliki if not _w_naprawie(krok, plik.sciezka)]:
        linie.append(f"  poza naprawą kroku: {', '.join(poza)}")
    for plik in (plik for plik in naprawa.pliki if _w_naprawie(krok, plik.sciezka)):
        przemianowany = f" | przy czerwonej głowie {plik.sciezka_czerwonej}: main przemianował go między bazami głów" if plik.sciezka_czerwonej != plik.sciezka else ""
        linie.append(f"  plik {plik.sciezka}{przemianowany}{' | main zmienił go między bazami głów' if plik.main_zmienil else ''}")
        przed, po = _zmiany(plik.diff_czerwonej), _zmiany(plik.diff_nastepnej)
        linie += [
            f"    git diff {glowa.baza[:12]}...{glowa.sha[:12]} -- {sciezka} | linii +/-: {len(zmiany)}"
            for glowa, sciezka, zmiany in ((czerwona, plik.sciezka_czerwonej, przed), (nastepna, plik.sciezka, po))
        ]
        roznica = [
            f"{znak} {linia}"
            for kod, i, j, k, m in SequenceMatcher(None, przed, po, autojunk=False).get_opcodes()
            if kod != "equal"
            for znak, linia in [*(("-", linia) for linia in przed[i:j]), *(("+", linia) for linia in po[k:m])]
        ]
        linie.append(f"    linie +/- tylko przy czerwonej (-) albo tylko przy następnej (+): {len(roznica)}")
        linie += [f"      {linia}" for linia in roznica[:POKAZ_LINII]]
        linie += [f"      … i {len(roznica) - POKAZ_LINII} więcej (polecenia wyżej)"] if len(roznica) > POKAZ_LINII else []
    return linie


def _zmiany(diff: str) -> list[str]:
    """Linie +/- diffu jednego pliku, od pierwszego nagłówka ``@@``, bo ``---`` i ``+++`` przed nim to nazwy plików."""

    linie = diff.splitlines()
    poczatek = next((numer for numer, linia in enumerate(linie) if linia.startswith("@@")), len(linie))
    return [linia for linia in linie[poczatek:] if linia.startswith(("+", "-"))]


def _min(wartosc: float | None) -> str:
    return "brak" if wartosc is None else f"{wartosc:.0f} min"


# --- zbieranie z GitHuba i gita ---


def zbierz(api: Api, root: Path, od: date, do: date, dzis: date, probka: int) -> Rekordy:
    wszystkie = sorted((r for r in runy(api, od, do, dzis) if r["status"] == "completed"), key=lambda r: r["created_at"])
    pr_wszystkie = [r for r in wszystkie if r["event"] == "pull_request"]
    pr = [r for r in pr_wszystkie if r["conclusion"] in SKONCZONE]
    main_wszystkie = [r for r in wszystkie if r["event"] == "push" and r["head_branch"] == "main"]
    main = [r for r in main_wszystkie if r["conclusion"] in SKONCZONE]
    # Głowa ostatniego runu main okna zawiera bazę scalenia każdej głowy PR okna, bo main tylko rośnie.
    main_po_oknie = main_wszystkie[-1]["head_sha"] if main_wszystkie else repo.BASE
    _pobierz(root, {r["head_sha"] for r in wszystkie})
    numery = _pr_scalonych(root, main_po_oknie, od)
    w_probce = {r["id"] for r in pr[:: max(1, len(pr) // probka)][:probka]} if probka else set()
    rekordy_pr = []
    for run in pr_wszystkie:
        # Padłe zadanie ma też run anulowany: jego wynik to cancelled, a nie failure.
        pytest, padle = _porazki(api, run) if run["conclusion"] != "success" else (Pytest.PRZESZEDL, ())
        if not (padle or run["id"] in w_probce):
            continue
        nastepny = next((r for r in pr if r["head_branch"] == run["head_branch"] and r["created_at"] > run["created_at"]), None)
        naprawa = _naprawa(root, main_po_oknie, run, nastepny) if padle and nastepny else None
        rekordy_pr.append(RunPr(run["id"], run["head_branch"], pytest, padle, naprawa, _cien(api, run["id"]), run["id"] in w_probce, numery.get(run["head_branch"])))
    ostatni_pr = {r["head_sha"]: r["id"] for r in pr_wszystkie}
    rekordy_main = []
    for numer, run in enumerate(main):
        if run["conclusion"] != "failure" or numer == 0:
            continue
        _, padle = _porazki(api, run)
        pominiete: set[str] = set()
        for glowa in _glowy_scalonych(root, main[numer - 1]["head_sha"], run["head_sha"]):
            cien = _cien(api, ostatni_pr[glowa]) if glowa in ostatni_pr else None
            pominiete |= set(cien[Podstawy.V0].kroki) - set(cien[Podstawy.NF].kroki) if cien else set()
        # Pierwszy zielony run, który skończył po czerwonym (ponowiona próba przesuwa koniec czerwonego).
        zielony = next((r for r in main[numer + 1 :] if r["conclusion"] == "success" and r["updated_at"] > run["updated_at"]), None)
        czerwien = None if zielony is None else (_chwila(zielony["updated_at"]) - _chwila(run["updated_at"])).total_seconds() / 60
        rekordy_main.append(RunMain(run["id"], padle, tuple(sorted(pominiete)), czerwien))
    return Rekordy(od.isoformat(), do.isoformat(), len(pr), tuple(rekordy_pr), tuple(rekordy_main))


def _porazki(api: Api, run: dict[str, Any]) -> tuple[Pytest, tuple[str, ...]]:
    """Zadania pytest i kroki skilli z porażką z logów padłych zadań Mutation checks ostatniej próby runu; zadanie pytest
    z innym wynikiem niż success, skipped albo failure (anulowane, przekroczony czas) nie skończyło."""

    zadania = api.json(f"{REPO}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100", lambda _: True)["jobs"]
    kroki = set()
    for zadanie in (z for z in zadania if z["conclusion"] == "failure" and z["name"].startswith(MUTACJE)):
        log = api.bajty(f"{REPO}/actions/jobs/{zadanie['id']}/logs").decode("utf-8", errors="replace")
        for linia in WYKONANIE_FAIL.findall(log):
            kroki |= {klucz.nazwa for klucz in map(Klucz.z_tekstu, linia.strip().split(", ")) if klucz.rodzaj is Rodzaj.SKILL}
    wyniki = {z["conclusion"] for z in zadania if z["name"].startswith(PYTEST)}
    pytest = Pytest.PADL if "failure" in wyniki else Pytest.PRZESZEDL if wyniki <= {"success", "skipped"} else Pytest.NIE_SKONCZYL
    return pytest, tuple(sorted(kroki))


def _cien(api: Api, run: int) -> dict[str, Wariant] | None:
    artefakty = api.json(f"{REPO}/actions/runs/{run}/artifacts?name={ARTEFAKT}", lambda _: True)["artifacts"]
    zywy = next((a for a in artefakty if not a["expired"]), None)
    if zywy is None:
        return None
    with zipfile.ZipFile(io.BytesIO(api.bajty(f"{REPO}/actions/artifacts/{zywy['id']}/zip"))) as archiwum:
        plan = Plan.z_json(archiwum.read(PLIK).decode("utf-8"))
    return {str(w.wariant): Wariant(w.kroki, w.sciana_s) for w in plan.cien} or None


def _pobierz(root: Path, glowy: Iterable[str]) -> None:
    brak = sorted(sha for sha in glowy if repo.commit(root, sha) is None)
    if brak and (pobranie := repo.run_git(root, "fetch", "--no-tags", "--quiet", "origin", *brak, timeout=600)).returncode:
        print(f"D1 CIEŃ | git fetch {len(brak)} głów runów: {pobranie.stderr.strip()[:300]}", file=sys.stderr)


def _naprawa(root: Path, main: str, czerwony: Mapping[str, Any], nastepny: Mapping[str, Any]) -> Naprawa | None:
    """Naprawa między głowami runów ``czerwony`` i ``nastepny`` (docstring modułu) z dowodem do audytu; ``None``, gdy
    git nie zna którejś głowy."""

    try:
        czerwona, nastepna = (Glowa(r["id"], r["html_url"], r["head_sha"], _baza_pr(root, main, r["head_sha"])) for r in (czerwony, nastepny))
        commity = repo.git(root, "log", "--no-merges", "--no-renames", "--name-only", "-z", "--format=", nastepna.sha, f"^{czerwona.sha}", f"^{nastepna.baza}")
        przemianowane = _przemianowane_przez_main(root, czerwona.baza, nastepna.baza)
        # Commit naprawy sprzed scalenia ``main`` do gałęzi zmienia plik pod ścieżką sprzed przemianowania, a po nim pod nową.
        po_przemianowaniu = {stara: nowa for nowa, stara in przemianowane.items()}
        pary = sorted({(przemianowane.get(plik, plik), po_przemianowaniu.get(plik, plik)) for plik in {plik.strip("\n") for plik in commity.split("\0")} - {""}})
        return Naprawa(
            czerwona,
            nastepna,
            tuple(_plik_naprawy(root, *para, czerwona, nastepna) for para in pary if _wlasna_zmiana_inna(root, *para, czerwona, nastepna)),
            not repo.is_ancestor(root, czerwona.sha, nastepna.sha),
        )
    except subprocess.CalledProcessError:
        return None


def _przemianowane_przez_main(root: Path, baza_czerwonej: str, baza_nastepnej: str) -> dict[str, str]:
    """Ścieżka pliku przy bazie następnej głowy → jego ścieżka przy bazie czerwonej, gdy ``main`` przemianował go między
    bazami głów (wpis ``R`` w ``git diff -M`` baz, także ze zmianą treści)."""

    if baza_czerwonej == baza_nastepnej:
        return {}
    pola = iter(repo.git(root, "diff", "--no-ext-diff", "--name-status", "-M", "-z", baza_czerwonej, baza_nastepnej).split("\0"))
    przemianowane: dict[str, str] = {}
    for status in pola:
        if not status:
            continue
        # Wpis -z to status i ścieżka, a przemianowanie (R) i kopia (C) mają dwie ścieżki: sprzed i po.
        sciezki = [next(pola) for _ in range(2 if status[0] in "RC" else 1)]
        if status[0] == "R":
            przemianowane[sciezki[1]] = sciezki[0]
    return przemianowane


def _wlasna_zmiana_inna(root: Path, przy_czerwonej: str, przy_nastepnej: str, czerwona: Glowa, nastepna: Glowa) -> bool:
    """Czy treść pliku przy głowach PR różni się poza liniami, które ``main`` zmienił w tym pliku między bazami głów
    (diff ``difflib`` obu baz): rebase i rozstrzygnięcie konfliktu, które zostawiają własną zmianę PR, zmieniają w pliku
    tylko takie linie, a przesunięte linie diffu (``git diff`` z powtórzoną linią obok zmiany) nie mają tu znaczenia,
    bo porównanie nie czyta diffu głów. Plik przy czerwonej głowie i jej bazie ma ścieżkę ``przy_czerwonej``."""

    przed, po = _linie(root, czerwona.baza, przy_czerwonej), _linie(root, nastepna.baza, przy_nastepnej)
    z_main = {linia for kod, i, j, k, m in SequenceMatcher(None, przed, po, autojunk=False).get_opcodes() if kod != "equal" for linia in przed[i:j] + po[k:m]}
    wlasne = [[linia for linia in _linie(root, glowa.sha, sciezka) if linia not in z_main] for glowa, sciezka in ((czerwona, przy_czerwonej), (nastepna, przy_nastepnej))]
    return wlasne[0] != wlasne[1]


def _plik_naprawy(root: Path, przy_czerwonej: str, przy_nastepnej: str, czerwona: Glowa, nastepna: Glowa) -> PlikNaprawy:
    def diff(glowa: Glowa, sciezka: str) -> str:
        return repo.git(root, "diff", "--no-ext-diff", "--no-color", f"{glowa.baza}...{glowa.sha}", "--", sciezka)

    return PlikNaprawy(
        przy_nastepnej,
        przy_czerwonej,
        diff(czerwona, przy_czerwonej),
        diff(nastepna, przy_nastepnej),
        repo.blob(root, czerwona.baza, przy_czerwonej) != repo.blob(root, nastepna.baza, przy_nastepnej),
    )


def _linie(root: Path, rewizja: str, plik: str) -> list[bytes]:
    tresc = repo.blob(root, rewizja, plik)
    return [] if tresc is None else tresc.split(b"\n")


def _baza_pr(root: Path, main: str, glowa: str) -> str:
    """Baza scalenia głowy PR z ``main`` sprzed jej scalenia: z rodzicem pierwszego commitu pierwszego rodzica ``main``,
    który ją zawiera, a gdy żaden jej nie zawiera, z samym ``main``."""

    potomne = set(repo.git(root, "rev-list", "--ancestry-path", f"{glowa}..{main}").split())
    zawierajace = [sha for sha in repo.git(root, "rev-list", "--first-parent", f"{glowa}..{main}").split() if sha in potomne]
    return repo.merge_base(root, glowa, f"{zawierajace[-1]}^1" if zawierajace else main)


def _pr_scalonych(root: Path, main: str, od: date) -> dict[str, int]:
    """Gałąź → numer PR-u z merge'y pierwszego rodzica ``main`` od dnia ``od`` (tytuł ``Merge pull request #N from
    <właściciel>/<gałąź>``, który pisze GitHub); gałąź scalona dwa razy bierze pierwszy merge."""

    numery: dict[str, int] = {}
    for tytul in repo.git(root, "log", "--first-parent", "--merges", "--reverse", f"--since={od.isoformat()}", "--format=%s", main).splitlines():
        if scalenie := MERGE_PR.fullmatch(tytul):
            numery.setdefault(scalenie[2], int(scalenie[1]))
    return numery


def _glowy_scalonych(root: Path, od: str, do: str) -> list[str]:
    """Głowy PR-ów scalonych w ``main`` między dwoma runami: drugi rodzic każdego merge'a pierwszego rodzica."""

    rodzice = repo.git(root, "log", "--first-parent", "--merges", "--format=%P", f"{od}..{do}").split("\n")
    return [linia.split()[1] for linia in rodzice if len(linia.split()) > 1]


def _chwila(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, github: GitHub = GITHUB) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--katalog", type=Path, help="Folder biegu: odpowiedzi API i rekordy.json.")
    parser.add_argument("--od", type=date.fromisoformat, help="Pierwszy dzień okna cienia (UTC).")
    parser.add_argument("--do", type=date.fromisoformat, help="Ostatni dzień okna cienia (UTC), zakończony.")
    parser.add_argument("--probka", type=int, default=PROBKA, help=f"Najwięcej runów PR, z których cienia liczy się oszczędność (domyślnie {PROBKA}).")
    parser.add_argument("--rekordy", type=Path, help="Rekordy zapisane wcześniej (rekordy.json): rozstrzygnięcie bez GitHuba.")
    parser.add_argument("--audyt", type=Path, help="Audyt kandydatów i niepoliczonych (JSON, docstring): wynik liczy przyczyny z audytu.")
    args = parser.parse_args(argv)
    try:
        audyt = None if args.audyt is None else wczytaj_audyt(args.audyt.read_text(encoding="utf-8"))
    except (BladAudytu, json.JSONDecodeError) as blad:
        parser.error(f"--audyt {args.audyt}: {blad}")
    if args.rekordy:
        rekordy = Rekordy.z_json(args.rekordy.read_text(encoding="utf-8"))
    elif args.katalog and args.od and args.do:
        dzis = datetime.now(timezone.utc).date()
        if args.do >= dzis:
            parser.error(f"okno kończy się {args.do}, a dzień trwa: pomiar biegnie po zakończonym oknie")
        api = Api(args.katalog, github)
        try:
            rekordy = zbierz(api, root, args.od, args.do, dzis, args.probka)
        except (BladApi, subprocess.TimeoutExpired) as blad:
            print(f"D1 CIEŃ | błąd API po {api.zapytania} zapytaniach: {blad}")
            return 1
        (args.katalog / "rekordy.json").write_text(json.dumps(asdict(rekordy), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"D1 CIEŃ | zapytań API {api.zapytania}, rekordy {args.katalog / 'rekordy.json'}")
    else:
        parser.error("podaj --rekordy albo --katalog z --od i --do")
    try:
        wynik = rozstrzygnij(rekordy, audyt)
    except BladAudytu as blad:
        parser.error(f"--audyt {args.audyt}: {blad}")
    print("\n".join(wypisz(rekordy, wynik)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
