from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
from typing import Any
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from api_actions import REZERWA_POMIARU, Api, PonizejRezerwy, ZRezerwa, runy
import czasy_ci
import github
from github import REPO, BladApi, GhApi, GitHub
from jednostka import Klucz
import plan_runu
from plan_runu import Plan
import pomiar_ci
from pomiar_ci import Odcinek, Pomiar
from repo import ROOT
from zakres_runu import MUTACJE, TORY

OPIS = """Strażnik budżetu bramki PR: p90 push → Required z 7 dni wobec 5 min i jedno issue z wąskim gardłem; użyj po zmianie CI (--bez-zapisu).

Budżet to decyzja Maksa D2 z 19.11 (ADR 0020): p90 ≤ 5 min od pushu do ``Required CI status``, a przekroczenie
automatycznie zakłada issue z wąskim gardłem. Sposób pomiaru wybrał autor strażnika (ADR 0020, poziom 2): cel „każdy
PR” z ``tools/pomiar_ci.py`` (``BUDZET``), czyli pierwsza próba każdego runu PR ``ci.yml``, bez anulowanych i bez okien
awarii runnerów, w oknie 7 pełnych dni UTC przed dniem uruchomienia (``--dzien``, domyślnie dziś); tydzień wcześniej
to 7 dni przed nim. Definicje runu, krytycznego zadania, jego odcinków i klasy zmiany należą do ``tools/pomiar_ci.py``;
strażnik ich nie powtarza, tylko je liczy w oknie i decyduje o issue. Workflow ``.github/workflows/budzet-ci.yml``
uruchamia strażnika codziennie o 5:23 UTC (minuta 23, bo GitHub opóźnia i porzuca biegi z cronu na początku godziny).

Pamięć (``--katalog``, w workflow przez actions/cache): ``pamiec.json`` z listą runów PR każdego zamkniętego dnia i
rekordem ``tools/pomiar_ci.py`` każdego zmierzonego runu PR z ostatnich ``DNI_PAMIECI`` dni (z jednostkami krytycznego
zadania z planu runu, gdy strażnik je pobrał), oraz ``czasy-ci/`` z artefaktami ``czasy-ci`` main. Strażnik pyta więc
API tylko o dni i runy, których pamięć nie ma. Runy okna mierzy w kolejności skrótu SHA-256 numeru runu, więc niepełny
pomiar (pierwszy bieg bez pamięci) to próbka z całego okna, a resztę dopełnia następny dzień.

Pobieranie (listy dni, zadania runów, plany) kończy się na pierwszym z dwóch limitów, a strażnik liczy wtedy okno
z tego, co ma, i nazywa limit w linii wyniku i w treści issue (okno niepełne):

    zapytania   ``--limit-zapytan`` (``LIMIT_ZAPYTAN``) z rezerwą ``REZERWA`` na czasy-ci, etykietę i issue, bo limit
                ``GITHUB_TOKEN`` to 1000 zapytań na godzinę na repozytorium, które dzieli z ``ci.yml``
    czas        ``--limit-czasu`` (``LIMIT_CZASU_S``) od startu, połowa ``timeout-minutes`` zadania workflow: zapytanie
                o zadania runu czeka 2–4 s na pierwszy bajt odpowiedzi GitHuba (19.11), więc zimny start bez pamięci
                (około 1000 runów okna) nie zdążyłby przed limitem zadania

Pamięć trafia na dysk na końcu biegu, także po błędzie, i co ``ZAPIS_CO_S`` w trakcie pobierania, więc bieg przerwany
z zewnątrz (anulowanie zadania) zostawia na dysku prawie wszystko, co zmierzył, a workflow zapisuje to do cache.

Koszt dnia w zapytaniach (``Licznik``, linia ``BUDŻET CI OK``):

    lista runów      strona na każde 100 runów ``ci.yml`` dnia, tylko dla dnia, którego pamięć nie ma (zwykle wczoraj)
    zadania runu     strona na run PR pierwszej próby, do 3 stron ponowionego (``tools/pomiar_ci.py``)
    plan             2 na run ogona bez jednostek (lista artefaktów runu i zip ``plan``), tylko gdy p90 > budżet
    czasy-ci         do 5 (``czasy_ci.z_mainu``), tylko gdy p90 > budżet
    issue            lista otwartych z etykietą, zapis issue, przy pierwszym założeniu lista etykiet i etykieta

Przy 147 runach PR na dobę (11–17.11) to około 160 zapytań dziennie, a 306 runów PR (14.11) około 330; pierwszy bieg
bez pamięci zatrzymuje się na limicie czasu i działa na próbce. Decyzja wymaga list wszystkich dni okna i rekordów
co najmniej ``POKRYCIE`` runów do zmierzenia; bez tego strażnik kończy się linią ``BUDŻET CI | pomiar niepełny`` i
issue nie rusza.

Issue to otwarte issue z etykietą ``ETYKIETA`` (tytuł ``TYTUL``), jedno na raz:

    p90 > budżet, issue brak        zakłada issue (i brakującą etykietę)
    p90 > budżet, issue otwarte     zmienia jego treść, bez komentarza
    p90 ≤ budżet, issue otwarte     komentuje liczby okna i je zamyka
    p90 ≤ budżet, issue brak        nic

Treść issue należy do strażnika, więc uwagi idą w komentarze: pomiar (p90, p50, n, runy ponad budżet, pokrycie)
wobec tygodnia wcześniej, wąskie gardło, ścieżka krytyczna z wkładem każdego odcinka, ponowienia runów, krytyczne
zadanie, najwolniejsze jednostki, klasy zmian i trend p90 okien kończących się w ostatnich ``TREND`` dniach.

Wąskie gardło to odcinek ścieżki krytycznej (``pomiar_ci.Odcinek``) o największym wkładzie do p90. Wkład odcinka to
jego średnia w runach ogona (czas do Required ≥ p90 okna) minus jego średnia w runach w budżecie (≤ 5 min), więc wkłady
sumują się do różnicy średnich czasów tych dwóch grup, a wkład pokazuje, czym wolne runy różnią się od tych, które
mieszczą się w budżecie. Gdy żaden run nie mieści się w budżecie, wkład to sama średnia w ogonie. Strażnik nazywa też
krytyczne zadanie (szablon ``ci.yml``), którego runy ogona dają największą część wkładu tego odcinka: wkład dzieli się
między szablony krytycznego zadania tak samo, sumą odcinka w runach z tym szablonem przez liczbę runów grupy.

Najwolniejsze jednostki to jednostki krytycznego zadania runów ogona z ich planu (artefakt ``plan`` runu), ważone
czasem z ``czasy-ci`` (mediana runów main, ``czasy_ci.Czasy.praca``; część ``k/n`` jednostki to 1/n czasu całości):
ranking według liczby runów ogona razy ten czas. Ponowienia runu leżą poza p90, który liczy pierwszą próbę, więc
strażnik podaje je obok ścieżki: dodatkowy czas od końca Required pierwszej próby do końca Required ostatniej.

Linie wyniku: ``BUDŻET CI | …`` na każdą akcję, błąd API i ostrzeżenie, z ``--bez-zapisu`` treść issue, a na końcu
``BUDŻET CI OK | okno … | zapytań <n> z limitu <n>, <s> s z limitu pobierania <s> s``; okno z pomiarem przerwanym
na limicie daje też linię ``BUDŻET CI | okno niepełne``. Błąd GitHuba albo Gita poza zapytaniem o run kończy się linią
``BUDŻET CI FAIL`` i kodem 1.

    .venv/bin/python tools/budzet_ci.py --katalog ~/.t3/notes/<bieg>/budzet --bez-zapisu
"""

PREFIKS = "BUDŻET CI"
BUDZET = next(cel for cel in pomiar_ci.CELE if cel.nazwa == "każdy PR")
BUDZET_S = BUDZET.p90_min * 60
ETYKIETA = "budzet-ci"
ETYKIETY = {ETYKIETA: ("d93f0b", f"p90 bramki PR ponad {BUDZET.p90_min:g} min (tools/budzet_ci.py, ADR 0020)")}
TYTUL = f"Budżet CI: p90 bramki PR ponad {BUDZET.p90_min:g} min"
DNI_OKNA = 7
DNI_PAMIECI = 2 * DNI_OKNA
TREND = DNI_OKNA + 1
LIMIT_ZAPYTAN = 600
REZERWA = 15
LIMIT_CZASU_S = 15 * 60
ZAPIS_CO_S = 60
LIMIT_API = "limit API GitHuba"
POKRYCIE = 0.5
JEDNOSTKI = 8
PLIK_PAMIECI = "pamiec.json"
WERSJA_PAMIECI = 1
# Pola runu z listy API, których potrzebują ``pomiar_ci.zadania`` i ``pomiar_ci.zmierz``.
POLA_RUNU = ("id", "event", "head_branch", "head_sha", "created_at", "run_attempt", "conclusion", "status")
POMIARY_TORU = {tor.nazwa: tor.pomiary for tor in (*TORY, MUTACJE)}
GITHUB = ZRezerwa(GhApi(limit_s=60), REZERWA_POMIARU)


class Licznik:
    """GitHub, który liczy każde zapytanie, także równoległe z ``czasy_ci.z_mainu``."""

    def __init__(self, github: GitHub) -> None:
        self.github = github
        self.zapytania = 0
        self._blokada = threading.Lock()

    def _licz(self) -> None:
        with self._blokada:
            self.zapytania += 1

    def json(self, sciezka: str) -> Any:
        self._licz()
        return self.github.json(sciezka)

    def bajty(self, sciezka: str) -> bytes:
        self._licz()
        return self.github.bajty(sciezka)

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self._licz()
        return self.github.wyslij(metoda, sciezka, tresc)


@dataclass(frozen=True)
class Rekord:
    """Zmierzony run PR i jednostki jego krytycznego zadania z planu runu (``None``: jeszcze nie pobrane)."""

    pomiar: Pomiar
    jednostki: tuple[str, ...] | None = None
    tor: str | None = None  # tor czasów krytycznego zadania w czasy-ci (``Tor.pomiary``)
    bez_planu: str | None = None  # czemu jednostek nie ma: artefakt wygasł albo plan nie ma krytycznego zadania

    @property
    def dzien(self) -> date:
        return _dzien(self.pomiar.utworzony)


@dataclass
class Pamiec:
    """Listy runów PR zamkniętych dni i rekordy zmierzonych runów; pamięć innej wersji to pusta pamięć."""

    listy: dict[str, list[dict[str, Any]]]
    rekordy: dict[int, Rekord]

    @classmethod
    def wczytaj(cls, katalog: Path) -> Pamiec:
        plik = katalog / PLIK_PAMIECI
        if not plik.is_file():
            return cls({}, {})
        try:
            dane = json.loads(plik.read_text(encoding="utf-8"))
            if dane["wersja"] != WERSJA_PAMIECI:
                return cls({}, {})
            rekordy = {}
            for wpis in dane["rekordy"]:
                jednostki = wpis["jednostki"]
                rekord = Rekord(Pomiar(**wpis["pomiar"]), tuple(jednostki) if jednostki is not None else None, wpis["tor"], wpis["bez_planu"])
                rekordy[rekord.pomiar.run] = rekord
        except (ValueError, KeyError, TypeError):
            return cls({}, {})
        return cls(dane["listy"], rekordy)

    def zapisz(self, katalog: Path, dzien: date) -> None:
        """Zapisuje dni nie starsze niż ``DNI_PAMIECI`` przed ``dzien``."""

        granica = dzien - timedelta(days=DNI_PAMIECI)
        dane = {
            "wersja": WERSJA_PAMIECI,
            "listy": {d: runy for d, runy in sorted(self.listy.items()) if date.fromisoformat(d) >= granica},
            "rekordy": [asdict(rekord) for _, rekord in sorted(self.rekordy.items()) if rekord.dzien >= granica],
        }
        katalog.mkdir(parents=True, exist_ok=True)
        tymczasowy = katalog / f"{PLIK_PAMIECI}.zapis"
        tymczasowy.write_text(json.dumps(dane, ensure_ascii=False), encoding="utf-8")
        tymczasowy.replace(katalog / PLIK_PAMIECI)


def _dzien(chwila: str) -> date:
    return datetime.fromisoformat(chwila.replace("Z", "+00:00")).astimezone(timezone.utc).date()


@dataclass(frozen=True)
class Okno:
    od: date
    do: date

    @classmethod
    def konczace(cls, ostatni: date) -> Okno:
        return cls(ostatni - timedelta(days=DNI_OKNA - 1), ostatni)

    def dni(self) -> list[date]:
        return [self.od + timedelta(days=n) for n in range((self.do - self.od).days + 1)]

    def zawiera(self, dzien: date) -> bool:
        return self.od <= dzien <= self.do

    def wczesniej(self) -> Okno:
        return Okno.konczace(self.od - timedelta(days=1))

    def __str__(self) -> str:
        return f"{self.od:%d.%m}–{self.do:%d.%m.%Y}"


def _do_zmierzenia(run: Mapping[str, Any]) -> bool:
    """Run PR, który cel „każdy PR” może policzyć: zakończony, nieanulowany, spoza okien awarii."""

    utworzony = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
    return run["event"] == "pull_request" and run["status"] == "completed" and run["conclusion"] != "cancelled" and pomiar_ci.awaria(utworzony) is None


def _limit_api(blad: BladApi) -> bool:
    return isinstance(blad, PonizejRezerwy) or "rate limit" in blad.stderr.lower()


@dataclass
class Pobieranie:
    """Pobiera do pamięci dni, runy i plany okna, dopóki starcza zapytań i czasu.

    ``bledy`` to linie błędów API, ``brak_dni`` dni bez listy, ``wyczerpany`` limit, na którym pobieranie stanęło,
    a ``bez_planu`` przyczyna, z której ten bieg nie ma planu runu ogona (pamięć jej nie trzyma, więc następny bieg
    pyta o ten plan znowu)."""

    pamiec: Pamiec
    licznik: Licznik
    api: Api
    limit: int
    limit_czasu_s: float
    zegar: Callable[[], float]
    katalog: Path
    dzis: date
    bledy: list[str] = field(default_factory=list)
    brak_dni: list[date] = field(default_factory=list)
    bez_planu: dict[int, str] = field(default_factory=dict)
    wyczerpany: str | None = None

    def __post_init__(self) -> None:
        self.start = self.zapisana = self.zegar()

    @property
    def czas_s(self) -> float:
        return self.zegar() - self.start

    def _wolne(self) -> bool:
        if self.wyczerpany is None and self.licznik.zapytania >= self.limit - REZERWA:
            self.wyczerpany = f"limit zapytań {self.limit}"
        if self.wyczerpany is None and self.czas_s >= self.limit_czasu_s:
            self.wyczerpany = f"limit czasu {self.limit_czasu_s:.0f} s"
        return self.wyczerpany is None

    def _zapisz_co_chwile(self) -> None:
        if self.zegar() - self.zapisana >= ZAPIS_CO_S:
            self.pamiec.zapisz(self.katalog, self.dzis)
            self.zapisana = self.zegar()

    def runy_okna(self, okno: Okno) -> list[dict[str, Any]]:
        """Runy PR do zmierzenia z każdego dnia okna; dzień bez listy trafia do ``brak_dni``."""

        wynik = []
        for dzien in okno.dni():
            zapamietane = self.pamiec.listy.get(dzien.isoformat())
            if zapamietane is None and self._wolne():
                try:
                    lista = runy(self.api, dzien, dzien, self.dzis)
                except (BladApi, subprocess.TimeoutExpired) as blad:
                    self.bledy.append(f"{PREFIKS} | błąd API lista runów {dzien}: {blad}")
                    if isinstance(blad, BladApi) and _limit_api(blad):
                        self.wyczerpany = self.wyczerpany or LIMIT_API
                    lista = None
                if lista is not None:
                    zapamietane = [{pole: run[pole] for pole in POLA_RUNU} for run in lista if run["event"] == "pull_request"]
                    if dzien < self.dzis and all(run["status"] == "completed" for run in zapamietane):
                        self.pamiec.listy[dzien.isoformat()] = zapamietane
            if zapamietane is None:
                self.brak_dni.append(dzien)
                continue
            wynik += [run for run in zapamietane if _do_zmierzenia(run)]
        return wynik

    def zmierz(self, runy: Sequence[dict[str, Any]], root: Path) -> None:
        """Rekord każdego runu bez rekordu, w kolejności skrótu numeru runu, dopóki starcza zapytań i czasu."""

        brakujace = sorted((run for run in runy if run["id"] not in self.pamiec.rekordy), key=lambda run: hashlib.sha256(str(run["id"]).encode()).hexdigest())
        if not brakujace or not self._wolne():
            return
        zmiany = pomiar_ci.Zmiany(root, (run["head_sha"] for run in brakujace))
        for run in brakujace:
            if not self._wolne():
                return
            try:
                wszystkie = pomiar_ci.zadania(self.api, run)
            except (BladApi, subprocess.TimeoutExpired) as blad:
                self.bledy.append(f"{PREFIKS} | błąd API run {run['id']}: {blad}")
                if isinstance(blad, BladApi) and _limit_api(blad):
                    self.wyczerpany = self.wyczerpany or LIMIT_API
                    return
                continue
            zmienione = zmiany.pliki(run["head_sha"], run["created_at"])
            self.pamiec.rekordy[run["id"]] = Rekord(pomiar_ci.zmierz(run, wszystkie, None, zmienione))
            self._zapisz_co_chwile()

    def plany(self, ogon: Iterable[Pomiar]) -> None:
        """Jednostki krytycznego zadania każdego runu ogona z artefaktu ``plan`` runu, dopóki starcza zapytań i czasu."""

        for pomiar in ogon:
            rekord = self.pamiec.rekordy[pomiar.run]
            if rekord.jednostki is not None or rekord.bez_planu is not None:
                continue
            if not self._wolne():
                self.bez_planu[pomiar.run] = f"planu nie pobrano ({self.wyczerpany})"
                continue
            try:
                self.pamiec.rekordy[pomiar.run] = _z_planem(rekord, self.licznik)
            except (BladApi, subprocess.TimeoutExpired, zipfile.BadZipFile, KeyError, ValueError) as blad:
                self.bledy.append(f"{PREFIKS} | błąd planu run {pomiar.run}: {blad}")
                self.bez_planu[pomiar.run] = f"błąd planu ({_przyczyna(blad)})"
                if isinstance(blad, BladApi) and _limit_api(blad):
                    self.wyczerpany = self.wyczerpany or LIMIT_API
            self._zapisz_co_chwile()


def _przyczyna(blad: Exception) -> str:
    """Przyczyna błędu planu bez numeru runu, więc runy z tym samym błędem liczą się w treści issue razem."""

    if isinstance(blad, BladApi):
        return (blad.stderr.strip().splitlines() or ["gh api bez komunikatu"])[0][:120]
    if isinstance(blad, subprocess.TimeoutExpired):
        return f"gh api ponad {blad.timeout:g} s"
    return f"{type(blad).__name__}: {blad}"[:120]


def _z_planem(rekord: Rekord, github: GitHub) -> Rekord:
    run = rekord.pomiar.run
    artefakty = github.json(f"{REPO}/actions/runs/{run}/artifacts?name={plan_runu.ARTEFAKT}")["artifacts"]
    artefakt = next((a for a in artefakty if not a["expired"]), None)
    if artefakt is None:
        return Rekord(rekord.pomiar, bez_planu="artefakt plan wygasł")
    with zipfile.ZipFile(io.BytesIO(github.bajty(f"{REPO}/actions/artifacts/{artefakt['id']}/zip"))) as archiwum:
        plan = Plan.z_json(archiwum.read(plan_runu.PLIK).decode("utf-8"))
    zadanie = next((z for z in plan.zadania if z.nazwa == rekord.pomiar.krytyczne_nazwa), None)
    if zadanie is None:
        return Rekord(rekord.pomiar, bez_planu=f"plan nie ma zadania {rekord.pomiar.krytyczne_nazwa}")
    return Rekord(rekord.pomiar, zadanie.jednostki, POMIARY_TORU.get(zadanie.tor, zadanie.tor))


def _sredni(odcinki: list[dict[Odcinek, float]], szablony: list[str | None]) -> dict[Odcinek, dict[str, float]]:
    """Średni odcinek grupy rozdzielony na szablony krytycznego zadania: suma w runach z szablonem przez liczbę runów."""

    srednie: dict[Odcinek, dict[str, float]] = {odcinek: defaultdict(float) for odcinek in Odcinek}
    for sciezka, szablon in zip(odcinki, szablony, strict=True):
        for odcinek, s in sciezka.items():
            srednie[odcinek][szablon or "?"] += s / len(odcinki)
    return srednie


@dataclass(frozen=True)
class Tydzien:
    """Liczby jednego okna: runy celu „każdy PR”, kwantyle, ogon, wkłady odcinków i wąskie gardło."""

    okno: Okno
    runy: list[Pomiar]
    p50: float | None
    p90: float | None
    ogon: list[Pomiar]
    w_budzecie: list[Pomiar]
    wklady: dict[Odcinek, dict[str, float]]  # odcinek → szablon krytycznego → sekundy

    @classmethod
    def z(cls, rekordy: Iterable[Rekord], okno: Okno) -> Tydzien:
        pary = [(p, czas) for p in BUDZET.runy(rekord.pomiar for rekord in rekordy if okno.zawiera(rekord.dzien)) if (czas := BUDZET.czas(p)) is not None]
        czasy = [czas for _, czas in pary]
        p90 = pomiar_ci.kwantyl(czasy, 0.9)
        ogon = [p for p, czas in pary if p90 is not None and czas >= p90]
        w_budzecie = [p for p, czas in pary if czas <= BUDZET_S]

        def srednie(grupa: list[Pomiar]) -> dict[Odcinek, dict[str, float]]:
            z_sciezka = [(sciezka, p.krytyczne) for p in grupa if (sciezka := pomiar_ci.sciezka(p)) is not None]
            return _sredni([s for s, _ in z_sciezka], [k for _, k in z_sciezka])

        w_ogonie, w_budzecie_s = srednie(ogon), srednie(w_budzecie)
        wklady = {
            odcinek: {szablon: w_ogonie[odcinek].get(szablon, 0.0) - w_budzecie_s[odcinek].get(szablon, 0.0) for szablon in sorted({*w_ogonie[odcinek], *w_budzecie_s[odcinek]})}
            for odcinek in Odcinek
        }
        return cls(okno, [p for p, _ in pary], pomiar_ci.kwantyl(czasy, 0.5), p90, ogon, w_budzecie, wklady)

    def wklad(self, odcinek: Odcinek) -> float:
        return sum(self.wklady[odcinek].values())

    @property
    def gardlo(self) -> tuple[Odcinek, str] | None:
        """Odcinek o największym wkładzie i szablon krytycznego zadania o największej części tego wkładu."""

        if not self.ogon:
            return None
        odcinek = max(Odcinek, key=self.wklad)
        return odcinek, max(self.wklady[odcinek], key=lambda szablon: self.wklady[odcinek][szablon], default="?")

    @property
    def ponad(self) -> int:
        return sum(_czas(p) > BUDZET_S for p in self.runy)

    @property
    def przekroczony(self) -> bool:
        """p90 okna ponad budżet; p90 równy 5 min mieści się w D2 „p90 ≤ 5 min”."""

        return self.p90 is not None and self.p90 > BUDZET_S


def _czas(pomiar: Pomiar) -> float:
    """Czas runu celu „każdy PR” (run z ``Tydzien.runy`` zawsze go ma)."""

    return BUDZET.czas(pomiar) or 0.0


def _m(s: float | None) -> str:
    return "–" if s is None else f"{s / 60:.1f}".replace(".", ",")


def _sr(wartosci: Sequence[float]) -> float | None:
    return statistics.fmean(wartosci) if wartosci else None


def _gardlo(tydzien: Tydzien) -> str:
    gardlo = tydzien.gardlo
    return "–" if gardlo is None else f"{gardlo[0].value} · `{gardlo[1]}`"


def _czas_jednostki(czasy: czasy_ci.Czasy, tor: str, klucz: Klucz) -> float | None:
    calosc = czasy.praca(tor, str(klucz.zgloszony))
    return None if calosc is None else calosc / (klucz.czesc.n if klucz.czesc else 1)


def _jednostki(ogon: Sequence[Pomiar], rekordy: Mapping[int, Rekord], czasy: czasy_ci.Czasy | None, bez_planu: Mapping[int, str]) -> list[str]:
    """Jednostki krytycznego zadania runów ogona, części jednej jednostki razem: w ilu runach ogona była, ile sekund
    pracy z czasy-ci dawała krytycznemu zadaniu jednego runu (mediana) i razem w ogonie. Run ogona bez planu liczy się
    z przyczyną z pamięci albo z tego biegu (``Pobieranie.bez_planu``); bez żadnej strażnik planów nie pobierał, bo p90
    mieści się w budżecie."""

    z_planem = [rekordy[p.run] for p in ogon if rekordy[p.run].jednostki is not None]
    bez = Counter(
        rekordy[p.run].bez_planu or bez_planu.get(p.run, "planu nie pobrano (p90 w budżecie)") for p in ogon if rekordy[p.run].jednostki is None
    )
    linie = [f"Plany: {len(z_planem)} z {len(ogon)} runów ogona" + "".join(f"; {powod}: {n}" for powod, n in bez.most_common()) + "."]
    if czasy is None or czasy.blad:
        linie.append(f"Czasy jednostek: brak ({czasy.blad if czasy else 'nie pobrano'}).")
    w_runach: dict[tuple[str, str], list[float]] = defaultdict(list)
    for rekord in z_planem:
        w_runie: dict[tuple[str, str], float] = defaultdict(float)
        for tekst in rekord.jednostki or ():
            klucz = Klucz.z_tekstu(tekst)
            w_runie[(rekord.tor or "?", str(klucz.zgloszony))] += (_czas_jednostki(czasy, rekord.tor or "?", klucz) if czasy else None) or 0.0
        for miejsce, s in w_runie.items():
            w_runach[miejsce].append(s)
    wiersze = sorted(w_runach.items(), key=lambda w: (-sum(w[1]), -len(w[1]), w[0]))
    if not wiersze:
        return linie
    return [
        *linie,
        "",
        "| jednostka (wszystkie części) | tor czasów | runy ogona | s w runie (mediana) | razem, min |",
        "|---|---|---|---|---|",
        *(f"| `{jednostka}` | {tor} | {len(s)} | {statistics.median(s):.0f} | {_m(sum(s))} |" for (tor, jednostka), s in wiersze[:JEDNOSTKI]),
    ]


def _klasy(runy: Sequence[Pomiar]) -> list[str]:
    grupy: dict[str, list[float]] = defaultdict(list)
    for p in runy:
        grupy[p.klasa or "bez klasy (brak commitu)"].append(_czas(p))
    wiersze = sorted(grupy.items(), key=lambda g: -(pomiar_ci.kwantyl(g[1], 0.9) or 0.0))
    return [
        "| klasa zmiany | n | p50 | p90 | ponad budżet |",
        "|---|---|---|---|---|",
        *(
            f"| {nazwa} | {len(czasy)} | {_m(pomiar_ci.kwantyl(czasy, 0.5))} | {_m(pomiar_ci.kwantyl(czasy, 0.9))} | {sum(c > BUDZET_S for c in czasy)} |"
            for nazwa, czasy in wiersze
        ),
    ]


def _sciezka(teraz: Tydzien, wczesniej: Tydzien) -> list[str]:
    def wartosci(grupa: Sequence[Pomiar], odcinek: Odcinek) -> list[float]:
        return [sciezka[odcinek] for p in grupa if (sciezka := pomiar_ci.sciezka(p)) is not None]

    def chromium(grupa: Sequence[Pomiar]) -> str:
        return _m(_sr([p.przegladarka_s or 0.0 for p in grupa if pomiar_ci.sciezka(p) is not None]))

    opisy = {
        Odcinek.PLAN: "plan (utworzenie runu → utworzenie krytycznego)",
        Odcinek.KOLEJKA: "kolejka krytycznego",
        Odcinek.START: "start (checkout, zależności, Chromium)",
        Odcinek.PRACA: "praca (do mediany pracy zadań planu runu)",
        Odcinek.MARUDER: "maruder (praca krytycznego ponad tę medianę)",
        Odcinek.KONIEC: "koniec krytycznego",
        Odcinek.OGON: "ogon (krytyczne → Required)",
    }
    linie = [
        "| odcinek | p50 | p90 | średnia w ogonie | średnia w budżecie | wkład | wkład tydzień wcześniej |",
        "|---|---|---|---|---|---|---|",
    ]
    for odcinek in Odcinek:
        wszystkie = wartosci(teraz.runy, odcinek)
        linie.append(
            f"| {opisy[odcinek]} | {_m(pomiar_ci.kwantyl(wszystkie, 0.5))} | {_m(pomiar_ci.kwantyl(wszystkie, 0.9))}"
            f" | {_m(_sr(wartosci(teraz.ogon, odcinek)))} | {_m(_sr(wartosci(teraz.w_budzecie, odcinek)))}"
            f" | **{_m(teraz.wklad(odcinek))}** | {_m(wczesniej.wklad(odcinek)) if wczesniej.ogon else '–'} |"
        )
    ponowione = [(p.do_ostatniego_required_s or 0.0) - (p.do_required_s or 0.0) for p in teraz.runy if p.proby > 1 and p.do_ostatniego_required_s is not None]
    return [
        *linie,
        "",
        f"Krok Chromium krytycznego (część startu), średnio: w ogonie {chromium(teraz.ogon)}, w budżecie {chromium(teraz.w_budzecie)} min.",
        f"Ponowienia runu (poza p90, który liczy pierwszą próbę): runy z ponowieniem {len(ponowione)}, od Required pierwszej próby do Required"
        f" ostatniej p50 {_m(pomiar_ci.kwantyl(ponowione, 0.5))} / p90 {_m(pomiar_ci.kwantyl(ponowione, 0.9))} min.",
    ]


def tresc(
    teraz: Tydzien, wczesniej: Tydzien, trend: Sequence[Tydzien], rekordy: Mapping[int, Rekord], czasy: czasy_ci.Czasy | None, pokrycie: str, bez_planu: Mapping[int, str]
) -> str:
    """Treść issue: szablon bez wolnej prozy, każda liczba z rekordów okna."""

    gardlo = teraz.gardlo
    krytyczne = Counter(p.krytyczne or "?" for p in teraz.runy)
    krytyczne_ogona = Counter(p.krytyczne or "?" for p in teraz.ogon)
    roznica = (_sr([_czas(p) for p in teraz.ogon]) or 0.0) - (_sr([_czas(p) for p in teraz.w_budzecie]) or 0.0)
    linie = [
        "Treść zmienia codziennie strażnik budżetu bramki PR (`tools/budzet_ci.py`, workflow `budzet-ci.yml`); uwagi idą w komentarze.",
        f"Budżet (ADR 0020, decyzja Maksa D2 z 19.11): p90 od pushu do `Required CI status` ≤ {BUDZET.p90_min:g} min."
        f" Pomiar (wybór autora strażnika, ADR 0020): pierwsza próba każdego runu PR, okno {DNI_OKNA} pełnych dni UTC.",
        "",
        f"## Pomiar {teraz.okno}",
        "",
        "| | to okno | tydzień wcześniej |",
        "|---|---|---|",
        f"| p90, min | **{_m(teraz.p90)}** | {_m(wczesniej.p90)} |",
        f"| p50, min | {_m(teraz.p50)} | {_m(wczesniej.p50)} |",
        f"| runy PR (n) | {len(teraz.runy)} | {len(wczesniej.runy)} |",
        f"| ponad budżet | {teraz.ponad} | {wczesniej.ponad} |",
        "",
        f"Pokrycie: {pokrycie}.",
        "",
        f"## Wąskie gardło: {_gardlo(teraz)}",
        "",
    ]
    if gardlo is not None:
        odcinek, szablon = gardlo
        linie += [
            f"Odcinek o największym wkładzie do p90: średnio {_m(teraz.wklad(odcinek))} z {_m(roznica)} min różnicy między runami ogona"
            f" (≥ p90, n {len(teraz.ogon)}) a runami w budżecie (≤ {BUDZET.p90_min:g} min, n {len(teraz.w_budzecie)});"
            f" z tego `{szablon}` jako krytyczne zadanie {_m(teraz.wklady[odcinek][szablon])} min.",
        ]
    linie += [
        "",
        "## Ścieżka krytyczna",
        "",
        "Odcinki sumują się do czasu do Required (`pomiar_ci.sciezka`), w minutach; wkład to średnia w ogonie minus średnia w budżecie.",
        "",
        *_sciezka(teraz, wczesniej),
        "",
        "## Krytyczne zadanie",
        "",
        "| szablon w ci.yml | runy | runy ogona |",
        "|---|---|---|",
        *(f"| `{szablon}` | {n} | {krytyczne_ogona.get(szablon, 0)} |" for szablon, n in krytyczne.most_common()),
        "",
        "## Najwolniejsze jednostki krytycznego zadania w ogonie",
        "",
        *_jednostki(teraz.ogon, rekordy, czasy, bez_planu),
        "",
        "## Klasy zmian",
        "",
        *_klasy(teraz.runy),
        "",
        "## Trend",
        "",
        "| okno | p90 | p50 | n | wąskie gardło |",
        "|---|---|---|---|---|",
        *(f"| {t.okno} | {_m(t.p90)} | {_m(t.p50)} | {len(t.runy)} | {_gardlo(t)} |" if t.runy else f"| {t.okno} | – | – | 0 | brak danych w pamięci |" for t in trend),
    ]
    return "\n".join(linie) + "\n"


def _akcje(teraz: Tydzien, otwarte: list[dict[str, Any]], tekst: str) -> tuple[list[github.Akcja], list[str]]:
    otwarte = sorted(otwarte, key=lambda issue: int(issue["number"]))
    if teraz.przekroczony:
        if not otwarte:
            return [github.Zaloz(TYTUL, tekst, (ETYKIETA,))], []
        ostrzezenia = [f"{PREFIKS} | otwartych issues z etykietą {ETYKIETA}: {len(otwarte)}, zmieniam najstarsze #{otwarte[0]['number']}"] if len(otwarte) > 1 else []
        return [github.Edytuj(int(otwarte[0]["number"]), tekst)], ostrzezenia
    zamkniecie = (
        f"Budżet wrócił: p90 {_m(teraz.p90)} min ≤ {BUDZET.p90_min:g} min, p50 {_m(teraz.p50)} min, n {len(teraz.runy)},"
        f" ponad budżet {teraz.ponad} (okno {teraz.okno}, `tools/budzet_ci.py`)."
    )
    return [github.Zamknij(int(issue["number"]), zamkniecie) for issue in otwarte], []


def main(
    argv: Sequence[str] | None = None, *, root: Path = ROOT, github_api: GitHub = GITHUB, zegar: Callable[[], float] = time.monotonic, kopia: Path | None = None
) -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--katalog", type=Path, required=True, help="Pamięć strażnika: pamiec.json i czasy-ci/.")
    parser.add_argument("--dzien", type=date.fromisoformat, help="Dzień uruchomienia, RRRR-MM-DD (UTC, domyślnie dziś); okno to 7 dni przed nim.")
    parser.add_argument("--limit-zapytan", type=int, default=LIMIT_ZAPYTAN, help=f"Najwięcej zapytań API biegu (domyślnie {LIMIT_ZAPYTAN}).")
    parser.add_argument(
        "--limit-czasu",
        type=float,
        default=LIMIT_CZASU_S,
        help=f"Sekundy od startu, po których strażnik przestaje pobierać i liczy niepełne okno (domyślnie {LIMIT_CZASU_S}).",
    )
    parser.add_argument("--bez-zapisu", action="store_true", help="Niczego nie zapisuj na GitHubie, tylko wydrukuj treść issue.")
    args = parser.parse_args(argv)
    dzis = args.dzien or datetime.now(timezone.utc).date()
    okno = Okno.konczace(dzis - timedelta(days=1))
    licznik = Licznik(github_api)
    pamiec = Pamiec.wczytaj(args.katalog)
    pobieranie = Pobieranie(pamiec, licznik, Api(licznik, kopia), args.limit_zapytan, args.limit_czasu, zegar, args.katalog, dzis)
    try:
        linie, teraz = _bieg(pobieranie, okno, root, args.katalog, bez_zapisu=args.bez_zapisu)
    except (BladApi, subprocess.SubprocessError, OSError, KeyError, ValueError) as blad:
        print(f"{PREFIKS} FAIL | {blad} | {_koszt(pobieranie)}")
        return 1
    finally:
        pamiec.zapisz(args.katalog, dzis)
    print("\n".join(linie))
    stan = "–" if teraz.p90 is None else ("ponad budżet" if teraz.przekroczony else "w budżecie")
    print(
        f"{PREFIKS} OK | okno {okno}: każdy PR p90 {_m(teraz.p90)} min (n {len(teraz.runy)}), {stan} {BUDZET.p90_min:g} min"
        f" | wąskie gardło {_gardlo(teraz)} | {_koszt(pobieranie)}"
    )
    return 0


def _koszt(pobieranie: Pobieranie) -> str:
    return (
        f"zapytań {pobieranie.licznik.zapytania} z limitu {pobieranie.limit},"
        f" {pobieranie.czas_s:.0f} s z limitu pobierania {pobieranie.limit_czasu_s:.0f} s"
    )


def _bieg(pobieranie: Pobieranie, okno: Okno, root: Path, katalog: Path, *, bez_zapisu: bool) -> tuple[list[str], Tydzien]:
    """Pobiera okno, liczy je i wykonuje akcję issue; linie wyniku i liczby okna."""

    pamiec, licznik = pobieranie.pamiec, pobieranie.licznik
    runy_okna = pobieranie.runy_okna(okno)
    pobieranie.zmierz(runy_okna, root)
    teraz = Tydzien.z(pamiec.rekordy.values(), okno)
    pokryte = sum(run["id"] in pamiec.rekordy for run in runy_okna)
    pokrycie = f"{pokryte} z {len(runy_okna)} runów PR do zmierzenia (bez anulowanych i okien awarii)" + (
        f"; dni bez listy runów: {', '.join(f'{d:%d.%m}' for d in pobieranie.brak_dni)}" if pobieranie.brak_dni else ""
    )
    niepelne = pobieranie.brak_dni or pokryte < len(runy_okna)
    if niepelne:
        pokrycie += f"; okno niepełne ({pobieranie.wyczerpany or 'błędy API, linie w logu workflow'}), resztę zmierzy następny bieg z pamięci"
    if pobieranie.brak_dni or not runy_okna or pokryte < POKRYCIE * len(runy_okna):
        return [*pobieranie.bledy, f"{PREFIKS} | pomiar niepełny: {pokrycie}; issue bez zmian"], teraz
    czasy = None
    if teraz.przekroczony:
        pobieranie.plany(sorted(teraz.ogon, key=lambda p: -_czas(p)))
        czasy = czasy_ci.z_mainu(katalog / czasy_ci.ARTEFAKT, github=licznik)
    trend = [Tydzien.z(pamiec.rekordy.values(), Okno.konczace(okno.do - timedelta(days=n))) for n in range(TREND)]
    tekst = tresc(teraz, Tydzien.z(pamiec.rekordy.values(), okno.wczesniej()), trend, pamiec.rekordy, czasy, pokrycie, pobieranie.bez_planu)
    akcje, ostrzezenia = _akcje(teraz, github.issues(licznik, ETYKIETA, "open"), tekst)
    linie = [*pobieranie.bledy, *ostrzezenia, *([f"{PREFIKS} | okno niepełne, issue z próbki: {pokrycie}"] if niepelne else [])]
    if any(isinstance(akcja, github.Zaloz) for akcja in akcje):
        linie += github.zaloz_etykiety(licznik, ETYKIETY, PREFIKS, zapis=not bez_zapisu)
    if bez_zapisu:
        return [*linie, *(f"{PREFIKS} | bez zapisu: {github.opis(akcja)}" for akcja in akcje), tekst], teraz
    return [*linie, *github.wykonaj(licznik, akcje, PREFIKS)], teraz


if __name__ == "__main__":
    raise SystemExit(main())
