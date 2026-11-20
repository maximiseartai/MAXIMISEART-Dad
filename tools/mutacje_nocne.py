from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from enum import Enum
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import urllib.parse
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from api_actions import REZERWA_POMIARU, STRONA, Api, ZRezerwa
import czasy_ci
from github import MERGE, REPO, SQUASH, Akcja, Edytuj, GhApi, GitHub, Skomentuj, Zaloz, Zamknij, blok_kodu, issues, strony, zaloz_etykiety
from github import wykonaj as wykonaj_akcje
from kroki_skilli import Katalog, Step
from jednostka import ZMIENNA_CZESCI, Czesc, Klucz
import jednostka
import mutacje_zmiany
import plan_runu
from repo import ROOT
import repo
from silnik_mutacji import NearLimit, Verdict
from wplyw_zmiany import Repository, changed_since
from zakres_runu import KrokSkilla, Zdarzenie, potrzebuja_chromium, zakres

OPIS = """Liczy nocne mutacje na main i zgłasza przeżyte w issue PR-ów; użyj (plan), by bez testów zobaczyć bazę i części najbliższej nocy.

Mutacje nocne (ADR 0021): mutacje linii zmienionych na ``main`` od ostatniej nocy i issue dla przeżytych.

Workflow ``mutacje-nocne.yml`` biegnie raz na dobę na ``main`` i ręcznie (``workflow_dispatch`` z opcjonalnym ``od``).

- ``start`` (workflow ``mutacje-nocne-start.yml``, każdy push na ``main``) uruchamia noc z pierwszego pushu po
  ``POCZATEK_NOCY`` UTC, bo cron ``30 1 * * *`` tworzy run z kilkugodzinnym opóźnieniem: przed tą godziną nic nie robi, a po
  niej uruchamia ``mutacje-nocne.yml`` na ``main`` z wejściem ``start: auto``, chyba że run nocy (każde zdarzenie)
  powstał już od tej godziny. Run crona albo startu z pushu, przed którym powstał już nieanulowany run nocy doby, nie
  robi drugiej nocy: ``plan`` daje ``do`` równe ``baza`` i pustą macierz części, a artefakt ``zakres-nocy`` z tym samym
  ``do``, więc zielony run bez pracy nie przesuwa bazy następnej nocy. Ręczny run bez ``start: auto`` biegnie zawsze.

- ``plan`` ustala bazę: ``--od`` (albo ``--baza``), gdy jest (``od`` spoza linii ``main`` zastępuje wspólny przodek HEAD i ``od``, od
  którego liczy też część), inaczej koniec zakresu ostatniego udanego runu tego workflow na ``main``
  (``do`` z jego artefaktu ``zakres-nocy``, a run bez tego artefaktu policzył wszystko do swojego ``headSha``), a bez
  takiego runu (albo gdy jego commit nie jest przodkiem HEAD) ostatni commit linii pierwszych rodziców HEAD sprzed 24 h.
  Mutacje od bazy liczy bez testów ``mutacje_zmiany.ZakresMutacji``, ten sam, który daje części jej mutacje, a zły
  wyjątek ``# mutacje-zmiany:`` liczy jako jedną mutację, żeby część go zgłosiła.
- Czerwony run nie przesuwa bazy, więc noc po nim dostaje jego zakres jeszcze raz. Plan zbiera więc z zapisów części
  każdego czerwonego runu tego workflow na ``main`` z tą samą bazą (``baza`` jego ``zakres-nocy``, runy utworzone od
  czasu commitu bazy) tożsamości mutacji, których werdykt nie potrzebuje issue (``mutacje_zmiany.OSADZONE``: wykryte,
  zdominowane, pod wyjątkiem i innego systemu), i liczy listę bez nich (``ZakresMutacji.bez_osadzonych``) przed ``do`` i
  podziałem na części, więc noc mutuje tylko to, czego żadna część nie osądziła, a w zwolnionym limicie sięga dalej.
  Przeżyte i mutacje z przekroczonym czasem biegną znowu, bo to, czy mają issue, rozstrzygają tylko klucze w issue
  (``akcje``): zgłoszenie czerwonego runu mogło paść przed ich issue, a gdy je założyło, noc nie zgłosi ich drugi raz.
  Część, która padła bez zapisu, nie daje tożsamości, więc jej mutacje biegną znowu. Tożsamości plan zapisuje z
  ``--osadzone`` (artefakt ``osadzone-nocy``), a zadania pokrycia i części podają ten plik w ``--osadzone``, więc liczą
  tę samą listę. Bez czerwonego runu tej bazy plik jest pusty, a noc taka jak bez niego.
- Część ma najwyżej ``NA_CZESC`` mutacji: tyle, że kończy się w limicie czasu części także z najdroższymi mutacjami
  zmierzonych nocy, w testach linii i w testach pliku. Noc mutuje najwyżej ``CZESCI_NA_NOC`` części, żeby nie dostała więcej,
  niż przerobi. Gdy od bazy jest więcej mutacji, ``do`` to najdalszy commit linii
  pierwszych rodziców od bazy, do którego mutacje zmian mieszczą się w tym limicie (co najmniej pierwszy commit z
  mutacjami, także większy), a noc mutuje tylko zmiany do niego (``ZakresMutacji.do``). Bazą następnej nocy jest
  ``do``, więc zaległość przechodzi na kolejne noce, a nie przepada. Plan pisze do ``GITHUB_OUTPUT`` ``baza``, ``do``,
  ``czesci``, ``liczba`` i ``pokrycie`` (macierz zadań pokrycia, ``macierz_pokrycia``), a z ``--zakres`` plik JSON z ``baza`` i ``do`` (artefakt ``zakres-nocy``). ``czesci`` to
  macierz zadań części: numer i ``przegladarka``, gdy testy, które mogą sprawdzać mutacje części (dotknięte jej
  plikami), sięgają Atrapy efenix, więc zadanie części instaluje Chromium tak jak zadanie pytest planu CI.
  Wpisy idą od części, której najdroższy plik ma najwięcej pracy testów na ``main`` (``czasy_ci``, tor ``TOR_LOKALNY``),
  bo GitHub wpuszcza wpisy macierzy do okna ``max-parallel`` w kolejności listy (start na runnerze zależy jeszcze od
  wolnych slotów organizacji), a długa część
  na końcu kolejki wydłuża noc. Kolejność nie zmienia mutacji części, bo te daje numer części; równa praca, także bez
  czasów, zostawia kolejność numerów.
- Część k z n to ``tools/mutacje_zmiany.py --baza <baza> --do <do> --czesc k/n --pokrycie <zapisy> --zapis …``: kolejne
  mutacje z listy posortowanej po plikach, więc mutacja biegnie z testami kilku plików, nie całej zmiany dnia. Pokrycie
  tych testów bez mutacji liczą przed częściami zadania ``pokrycie`` workflow, każde dla swojej części plików testów
  nocy (``tools/mutacje_zmiany.py --pokrycie-czesc``), a część czyta ich zapisy.
- ``wystapienia <plik>`` czyta wynik ``gh issue list --label przezyte-mutacje --json number,title,body,state,comments`` i drukuje
  każdą linię nocy, na którą ostatnia odpowiedź agenta nie zaczyna się od ``wykryta`` ani ``nie warto`` (linia
  ``WYSTĄPIENIE``), a na końcu liczbę issues z wystąpieniem i bez; linię nocy i odpowiedź rozpoznaje ``rdzen``, ten sam,
  po którym noc nie zgłasza linii drugi raz. Woła go krok 1 skilla polowania.
- ``zglos`` czyta zapisy części. Każdą przeżytą mutację, mutację bez werdyktu po limicie czasu części i mutację, której
  testy w ostatnim przebiegu przekroczyły limit czasu mutacji, przypisuje PR-owi, który ostatni zmienił jej linie: zmienione
  linie, które mutacja psuje, a nie linię jej nazwy, bo nazwę daje początek węzła, a w wielowierszowym ``if (`` zmienia
  się często tylko linia w środku. ``git blame`` tych linii daje commity nocy, bo to linie zmienione od bazy, a z nich
  liczy się ten, który linia pierwszych rodziców HEAD wniosła ostatni. Numer PR podaje temat commitu tej linii, który go wniósł
  (``Merge pull request #N`` albo squash ``… (#N)``); gałąź zbudowana na innej wnosi swoje commity do kilku PR-ów, a
  temat scalenia mówi, który z nich je scalił. Bez numeru w temacie PR podaje ``gh api …/commits/<sha>/pulls``. Na PR
  przypada jedno issue ``Przeżyte mutacje z #N`` z etykietami ``ETYKIETY``, a w nim linie
  ``MUTACJA <plik>:<linia> <opis> | klucz <klucz>`` (z pól zapisu części: id jak w ``NIEWYKRYTA``, klucz z ``mutacje_zmiany.fingerprint``),
  a mutacja bez werdyktu ma na końcu dopisek swojego ``Rodzaj`` i radę w issue: część po limicie czasu jej nie
  sprawdziła albo jej testy przekroczyły limit czasu mutacji (``--limit-s`` całego zbioru testów, #1339), więc noc nie
  wraca do jej zakresu, a sprawdza ją agent PR-u ``tools/mutacje.py --plik`` z jednym wąskim węzłem pytest na mutację
  (``polecenie`` wpisu), bo cały zbiór testów pliku trwa blisko limitu.
  Mutacji, której klucz issue już ma w treści albo komentarzu, nie dostaje drugi raz; nowe idą do istniejącego issue
  komentarzem, a zamknięte issue z nowymi wraca otwarte z ``ready-for-agent``. Noc zakłada albo komentuje issue
  najwyżej ``ISSUES_NA_NOC`` PR-ów, od PR-u z najwięcej nowymi przeżytymi mutacjami, a przy równej liczbie z najwięcej
  nowymi mutacjami. Nowe mutacje PR-ów ponad limit nie dostają issue, a linia
  ``MUTACJE NOCNE BEZ ISSUE`` podaje ich liczbę i pliki z liczbą mutacji każdego; noc ich nie powtarza, bo baza
  przechodzi za nie.
  Część bez zapisu albo z kodem wyjścia spoza ``mutacje_zmiany.KODY_Z_WYNIKIEM`` (testy padają albo nie kończą się
  w limicie czasu części bez mutacji, zły wyjątek) czerwieni run po zgłoszeniu reszty, także przeżytych mutacji z jej
  zapisu, więc następna noc liczy od tej samej bazy, z tym samym limitem mutacji, ale bez mutacji, którym części tego
  runu dały werdykt bez issue (``plan`` wyżej). Zgłoszone mutacje się nie powtórzą, także gdy PR z
  następnego dnia przesunie ich linie, bo klucz nie ma numerów linii.
- Skrypty mutacji skilli nocy planuje ``tools/plan_ci.py plan --zdarzenie noc --baza <baza>`` (skrypty skilli, których
  folder, import (silnik mutacji i jego zależności), uruchamiacz kroku albo sprawdzenie zmieniło się od bazy, i części każdego n podstaw z ``ci-czesci``), a zadanie
  planu wgrywa swój zapis wykonania jako artefakt ``mutacje-skilli-<id zadania>``. ``zglos --plan-skilli`` daje każdy
  skrypt, który padł, linią ``SKRYPT <skrypt>`` do issue ``Przeżyte mutacje skilli z #N`` PR-u, który ostatni zmienił
  plik zmieniony od bazy, który uruchomił krok w zakresie nocy (``KrokSkilla.pliki``): najpierw plik w folderze skilla,
  potem inny, a bez takiego pliku ostatni PR nocy; linii, którą issue już ma, nie dostaje drugi raz. Do tego samego issue idzie każde
  ostrzeżenie ``CZAS BLISKO LIMITU`` z zapisu zadania (``blisko_limitu``, ``NearLimit`` z ``tools/lib/silnik_mutacji.py``): mutacja skryptu, której
  polecenie trwało ponad połowę limitu, linią ``CZAS BLISKO LIMITU <skrypt> | <mutacja> | <czas> z limitu …``. Czas
  zmienia się co noc, więc issue, które ma już linię z tym skryptem i mutacją, nie dostaje jej drugi raz (#935).
  Zadanie bez zapisu tego planu albo bez wyniku jednostki czerwieni run, tak jak skrypt, który padł, albo ostrzeżenie w
  nocy bez commitu od bazy, bo nie ma PR-u, który by je dostał.
- ``odczyt RUN`` (zadanie ``odczyt`` workflow po zgłoszeniu) liczy odczyt nocy z zadań runu (ostatnia próba), logu
  zadania ``ZADANIE_PLANU`` i logów zadań części, przez kopię odpowiedzi ``api_actions.Api``: ścianę od utworzenia runu do
  końca ostatniego zadania, godziny runnerów (suma czasów zadań bez pominiętych), mutacje i zaległość z linii planu,
  najdłuższy krok ``KROK_CZESCI`` wobec ``mutacje_zmiany.PART_LIMIT_S`` i linie ``BEZ WERDYKTU`` każdej części. Próg to
  ściana ponad ``LIMIT_SCIANY_S``, krok części do ``PART_LIMIT_S`` albo choć jedna mutacja ``BEZ WERDYKTU``. Drukuje
  treść odczytu (także do ``GITHUB_STEP_SUMMARY``) i linię ``MUTACJE NOCNE ODCZYT``, a z ``--issue`` zapisuje treść w
  jednym issue z etykietą ``ETYKIETA_ODCZYTU`` (najstarszym): bez niego je zakłada, noc ponad progiem otwiera zamknięte
  komentarzem z wąskim gardłem, a noc w progach zamyka otwarte komentarzem z liczbami. Część albo plan, który jeszcze
  biegnie, nie daje odczytu.

Bazę, koniec zakresu i liczbę części nocy drukuje lokalnie bez testów, a odczyt nocy bez zapisu w issue:

    .venv/bin/python tools/mutacje_nocne.py plan
    .venv/bin/python tools/mutacje_nocne.py odczyt 44441152441
"""

WORKFLOW = "mutacje-nocne.yml"
# Doba nocy zaczyna się o godzinie crona ``30 1 * * *`` w mutacje-nocne.yml; od niej noc startuje z pierwszego pushu na main.
POCZATEK_NOCY = time(1, 30)
# Wejście ``start`` runu, który uruchomił start z pushu; ``plan`` traktuje taki run jak run crona.
START_AUTO = "auto"
PREFIKS = "MUTACJE NOCNE"
# Część to 6 pełnych kolejek po WORKERS mutacji naraz. W nocach 31.10–3.11 (runy 41179652907, 41285996039, 41408995300,
# 41601085650) mediana mutacji pliku wynosiła 1–210 s, ale 16 mutacji tools/mutacje.py trwało w testach linii pełny limit
# mutacji (MUTATION_LIMIT_S). Testy kodu pliku jednej mutacji trwały najwyżej 836 s (doszło do nich najwyżej 11 z 32
# mutacji części), a testy pliku, które biegną po jednej, w nocach 17–19.11 do pełnego limitu mutacji (najwyżej 37 z 93).
# Pokrycie biegnie w osobnych zadaniach, a brama typów części trwała najwyżej 156 s. Część mieści się w limicie czasu
# części (PART_LIMIT_S), gdy ma najgorszy czas każdego przebiegu naraz, a do dalszych przebiegów dochodzi tyle jej
# mutacji, co w którejś zmierzonej części 31.10–3.11: ok. 13 400 s, a o kolejkę większa ok. 15 400 s (ADR 0021).
# Mutacja, która trwa pełny limit także w testach pliku, może go przekroczyć i zostaje bez werdyktu.
NA_CZESC = 6 * mutacje_zmiany.WORKERS
# Zadania części biegną najwyżej po 17 naraz, a zadania skryptów skilli po 3 (max-parallel w mutacje-nocne.yml), bo 60
# zadań organizacji dzielą też runy CI PR-ów, a noc dostaje z nich najwyżej 20. W 6 nocach 12–17.11 zmiany main dawały
# ok. 980 mutacji na dobę, a noc 40 części najwyżej 960, więc zaległość rosła (11.11: 7450, 17.11: 7812). 60 części to
# 1440 mutacji: zaległość maleje o ok. 460 na noc, a noc trwa ok. 4 h zamiast 3,5 h, bo części biegną w czterech falach
# po 17 zamiast w trzech (ADR 0021).
CZESCI_NA_NOC = 60
# Zadania pokrycia nocy (``mutacje_zmiany.py --pokrycie-czesc``): każde liczy pokrycie ok. czwartej części plików testów
# nocy, a części nocy czekają na najwolniejsze. Każde płaci też checkout, instalację i listę mutacji nocy (ADR 0021).
CZESCI_POKRYCIA = 4
# Plan bez czasów CI waży każdą część zerem, więc części zostają w kolejności numerów.
BEZ_CZASOW = czasy_ci.KosztyPlikow({})
GITHUB = GhApi()
OKNO = timedelta(hours=24)
ETYKIETY = ("ready-for-agent", "przezyte-mutacje")
ISSUES_NA_NOC = 5
# Artefakt części k w mutacje-nocne.yml: ``mutacje-nocne-<k>`` z plikiem ``--zapis`` narzędzia mutacji.
ARTEFAKT = "mutacje-nocne-"
ZAPIS = "czesc.json"
# Artefakt zadania skryptów mutacji skilli: ``mutacje-skilli-<id zadania planu>`` z zapisem ``plan_runu.WYKONANIE``.
ARTEFAKT_SKILLI = "mutacje-skilli-"
# Artefakt planu z plikiem ``--zakres``: baza i koniec zakresu nocy, od którego zaczyna następna noc.
ARTEFAKT_ZAKRESU = "zakres-nocy"
ZAKRES = "zakres.json"
# Artefakt planu z plikiem ``--osadzone`` (``mutacje_zmiany.zapisz_osadzone``): tożsamości mutacji, którym części
# czerwonych runów tej samej bazy dały werdykt bez issue. Zadania pokrycia i części pobierają go i pomijają je jak plan.
ARTEFAKT_OSADZONYCH = "osadzone-nocy"
# Klucz z linii ``MUTACJA`` w treści issue; długość klucza daje ``mutacje_zmiany.fingerprint``.
_KLUCZ = re.compile(r"\| klucz (?P<klucz>[0-9a-f]+)\b")
# Początki linii ``SKRYPT`` i ``CZAS BLISKO LIMITU`` issue skryptów skilli oraz środek czasu ostrzeżenia, który ``rdzen``
# odcina, bo czas zmienia się co noc.
_SKRYPT = "SKRYPT "
_BLISKO = "CZAS BLISKO LIMITU "
_Z_LIMITU = " s z limitu --limit-s "
_CZAS_BLISKO = re.compile(rf" \| \d+{re.escape(_Z_LIMITU)}\S+ s( \({ZMIENNA_CZESCI}=\S+\))?\s*$")
_ZALEGLOSC = "zaległość:"
_MUTACJE_PLANU = "mutacje"
ZADANIE_PLANU = "Plan mutacji nocnych"
ZADANIE_CZESCI = "Change mutations ("
KROK_CZESCI = "Mutate the part's changed lines of src/ and tools/"
LIMIT_SCIANY_S = 7 * 3600
ODCZYT = f"{PREFIKS} ODCZYT"
ETYKIETA_ODCZYTU = "noc-mutacji"
ETYKIETY_ODCZYTU = {ETYKIETA_ODCZYTU: ("5319e7", "Odczyt nocy mutacji: noc ponad próg (tools/mutacje_nocne.py odczyt, ADR 0021)")}
TYTUL_ODCZYTU = "Noc mutacji ponad próg"
_STEMPEL = r"(?m)^(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?"
_PLAN_W_LOGU = re.compile(rf"{_STEMPEL}{PREFIKS} PLAN \| .*? \| {_MUTACJE_PLANU} (?P<mutacje>\d+) \|")
_ZALEGLOSC_W_LOGU = re.compile(rf"{_STEMPEL}{PREFIKS} \| {_ZALEGLOSC} (?P<zalegle>\d+) ")
_BEZ_WERDYKTU_W_LOGU = re.compile(rf"{_STEMPEL}{Verdict.NO_VERDICT}: ")
_RADA_MUTACJE = (
    "sprawdź ją `tools/mutacje.py --plik` z jednym wąskim węzłem pytest w `polecenie` jej wpisu (`tests/test_x.py::test_y`), "
    "bo cały zbiór testów pliku trwa blisko limitu, a gdy test ją wykrywa, napisz w komentarzu "
    "`MUTACJA <plik>:<linia> <opis> | wykryta, <polecenie>`"
)


class Rodzaj(Enum):
    """Mutacja, którą noc zgłasza: lista zapisu części (``tools/mutacje_zmiany.py --zapis``), z której przychodzi, koniec
    jej linii ``MUTACJA``, jej nazwa w ostatniej linii ``zglos`` i rada w issue, gdy noc nie dała jej werdyktu."""

    PRZEZYTA = (mutacje_zmiany.PRZEZYTE, "", "przeżyło", "")
    BEZ_WERDYKTU = (
        mutacje_zmiany.BEZ_WERDYKTU,
        " | bez werdyktu w limicie czasu części",
        "bez werdyktu",
        f"to mutacja, której noc nie sprawdziła przed limitem czasu części: {_RADA_MUTACJE}.",
    )
    # Limit ``--limit-s`` dotyczy całego zbioru testów przebiegu, który bez mutacji trwa blisko niego, więc mutacja, po
    # której test pada, potrafi go przekroczyć (#1339); mutacja, która tylko spowalnia test, przeżywa.
    PRZEKROCZONY_CZAS = (
        mutacje_zmiany.PRZEKROCZONY_CZAS,
        " | przekroczony czas testów, bez werdyktu",
        "przekroczony czas",
        "to mutacja, której testy nie skończyły się w limicie czasu mutacji (`--limit-s` całego zbioru testów), więc noc nie wie, "
        f"czy test ją łapie: {_RADA_MUTACJE}, a gdy przechodzi, tylko wolniej, dodaj test albo powód `nie warto`.",
    )

    def __init__(self, lista: str, dopisek: str, nazwa: str, rada: str) -> None:
        self.lista = lista
        self.dopisek = dopisek
        self.nazwa = nazwa
        self.rada = rada


# --- start z pushu ---


@dataclass(frozen=True)
class Wyzwolenie:
    """Co uruchomiło run planu: zdarzenie GitHub Actions (``github.event_name``), wejście ``start`` i id runu
    (``GITHUB_RUN_ID``)."""

    zdarzenie: str = ""
    start: str = ""
    run: int = 0

    @property
    def noc_doby(self) -> bool:
        """Run, który ma być nocą doby: cron albo start z pushu; ręczny run człowieka (z ``od``) biegnie zawsze."""

        return self.zdarzenie == "schedule" or self.start == START_AUTO


# Plan poza runem crona i startu z pushu (lokalnie, ręczny run z ``od``) biegnie zawsze.
RECZNE = Wyzwolenie()


def _runy_doby(github: GitHub, teraz: datetime) -> list[dict[str, Any]]:
    """Runy tego workflow na ``main`` utworzone od ``POCZATEK_NOCY`` UTC doby ``teraz``, każdym zdarzeniem."""

    od = urllib.parse.quote(f">={datetime.combine(teraz.date(), POCZATEK_NOCY, UTC):%Y-%m-%dT%H:%M:%SZ}")
    runy: list[dict[str, Any]] = github.json(f"{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&created={od}&per_page=100")["workflow_runs"]
    return runy


def start(github: GitHub, teraz: datetime) -> int:
    """Uruchamia noc doby ``teraz`` z pushu na ``main``: przed ``POCZATEK_NOCY`` UTC i po runie nocy utworzonym od tej
    godziny nic, a inaczej ``workflow_dispatch`` tego workflow na ``main`` z wejściem ``start: auto``."""

    if teraz.time() < POCZATEK_NOCY:
        print(f"MUTACJE NOCNE START | {teraz:%H:%M} UTC, przed {POCZATEK_NOCY:%H:%M} UTC: noc startuje z pierwszego pushu po tej godzinie")
        return 0
    if runy := _runy_doby(github, teraz):
        print(f"MUTACJE NOCNE START | noc doby ma już run {min(run['id'] for run in runy)} od {POCZATEK_NOCY:%H:%M} UTC: bez drugiego")
        return 0
    github.wyslij("POST", f"{REPO}/actions/workflows/{WORKFLOW}/dispatches", {"ref": "main", "inputs": {"start": START_AUTO}})
    print(f"MUTACJE NOCNE START | uruchomiona noc doby (start {START_AUTO})")
    return 0


def _wczesniejsza_noc(github: GitHub, wyzwolenie: Wyzwolenie, teraz: datetime) -> int | None:
    """Pierwszy run nocy doby ``teraz`` utworzony przed runem ``wyzwolenie``, gdy ``wyzwolenie`` to noc doby. Run anulowany
    (także czekający, którego zastąpił nowszy w grupie ``concurrency``) nic nie zmutował, więc go nie liczy."""

    if not wyzwolenie.noc_doby:
        return None
    wczesniejsze = [run["id"] for run in _runy_doby(github, teraz) if run["id"] < wyzwolenie.run and run.get("conclusion") != "cancelled"]
    return min(wczesniejsze, default=None)


# --- plan ---


def baza(github: GitHub, root: Path, od: str, teraz: datetime) -> tuple[str, str]:
    """SHA, od którego noc mutuje zmiany, i skąd go wzięła. Z ``od`` to wspólny przodek HEAD i ``od``, od którego liczy
    też część (``tools/mutacje_zmiany.py``), więc ``od`` spoza linii ``main`` nie dokłada planowi cofnięcia zmian swojej
    gałęzi, których część nie mutuje."""

    if od:
        commit = repo.git(root, "rev-parse", "--verify", f"{od}^{{commit}}").strip()
        try:
            wspolny = repo.merge_base(root, "HEAD", commit)
        except subprocess.CalledProcessError:
            raise ValueError(f"--od {od} nie ma wspólnego przodka z HEAD") from None
        return wspolny, f"--od {od}" if wspolny == commit else f"merge-base HEAD z --od {od}"
    runy = github.json(f"{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&status=success&per_page=1")["workflow_runs"]
    if runy and repo.is_ancestor(root, runy[0]["head_sha"], "HEAD"):
        return _koniec_runu(github, runy[0]), f"ostatni udany run {runy[0]['id']}"
    przed = repo.git(root, "rev-list", "-1", "--first-parent", f"--before={(teraz - OKNO).isoformat()}", "HEAD").strip()
    if not przed:
        raise ValueError("HEAD nie ma commitu sprzed 24 h; podaj --od")
    return przed, "24 h wstecz, bez udanego runu przodka HEAD"


def _koniec_runu(github: GitHub, run: dict[str, Any]) -> str:
    """Commit, do którego udany ``run`` zmutował zmiany: ``do`` z jego artefaktu ``zakres-nocy``, a bez artefaktu (run
    sprzed limitu nocy) jego ``head_sha``. Wygasły artefakt to błąd, bo ``head_sha`` pominąłby zaległość tego runu."""

    artefakty = github.json(f"{REPO}/actions/runs/{run['id']}/artifacts?name={ARTEFAKT_ZAKRESU}")["artifacts"]
    if not artefakty:
        return str(run["head_sha"])
    if artefakty[0]["expired"]:
        raise ValueError(f"artefakt {ARTEFAKT_ZAKRESU} runu {run['id']} wygasł, więc nie wiadomo, dokąd run zmutował zmiany; podaj --od")
    return str(json.loads(_plik_artefaktu(github, artefakty[0], ZAKRES))["do"])


def _plik_artefaktu(github: GitHub, artefakt: dict[str, Any], plik: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(github.bajty(f"{REPO}/actions/artifacts/{artefakt['id']}/zip"))) as archiwum:
        return archiwum.read(plik)


def osadzone(github: GitHub, root: Path, od_sha: str) -> tuple[frozenset[mutacje_zmiany.Tozsamosc], list[int]]:
    """Tożsamości mutacji, którym części czerwonych runów tego workflow na ``main`` z bazą ``od_sha`` (``baza`` z ich
    artefaktu ``zakres-nocy``) dały werdykt bez issue (``mutacje_zmiany.OSADZONE``), i id tych runów.

    Czerwony run nie przesuwa bazy, więc noc po nim dostaje jego zakres jeszcze raz; bez tych mutacji mutuje tylko to,
    czego żadna jego część nie osądziła, i sięga dalej. Przeżytych zapis nie ma, więc biegną znowu, a issue nie przyjmuje
    ich klucza drugi raz. Część bez zapisu (padła, kod 2) nie daje tożsamości, więc jej mutacje biegną znowu. Runy szuka
    od czasu commitu bazy, bo run z tą bazą powstał po nim, a nie od ostatniego udanego runu: spóźniony run crona po
    czerwonej nocy doby jest zielony bez pracy i bazy nie przesuwa. Run, którego artefaktów nie da się przeczytać, nie
    daje tożsamości, bo bez nich noc tylko powtarza pracę."""

    od = datetime.fromtimestamp(int(repo.git(root, "log", "-1", "--format=%ct", od_sha)), UTC)
    zapytanie = urllib.parse.quote(f">={od:%Y-%m-%dT%H:%M:%SZ}")
    runy = github.json(f"{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&status=failure&created={zapytanie}&per_page=100")["workflow_runs"]
    wszystkie: set[mutacje_zmiany.Tozsamosc] = set()
    czerwone: list[int] = []
    for run in runy:
        try:
            z_runu = _osadzone_runu(github, run["id"], od_sha)
        except (RuntimeError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as blad:
            print(f"MUTACJE NOCNE | czerwony run {run['id']} bez tożsamości osądzonych mutacji ({blad!r}): noc sprawdzi je znowu")
            continue
        if z_runu is not None:
            czerwone.append(run["id"])
            wszystkie |= z_runu
    return frozenset(wszystkie), czerwone


def _osadzone_runu(github: GitHub, run: int, od_sha: str) -> frozenset[mutacje_zmiany.Tozsamosc] | None:
    """Tożsamości ``mutacje_zmiany.OSADZONE`` zapisów części runu, a ``None``, gdy run miał inną bazę. Run bez zakresu
    albo z wygasłym artefaktem rzuca błąd, z którym ``osadzone`` go pomija."""

    # Lista artefaktów runu ma strony po 100: zapis każdej części, pokrycie i jego testy niestabilne, zapisy skryptów
    # skilli, więc noc z ok. 75 częściami już się na jednej nie mieści.
    artefakty = {artefakt["name"]: artefakt for artefakt in strony(github, f"{REPO}/actions/runs/{run}/artifacts", "artifacts")}
    if json.loads(_plik_artefaktu(github, artefakty[ARTEFAKT_ZAKRESU], ZAKRES))["baza"] != od_sha:
        return None
    zapisy = [json.loads(_plik_artefaktu(github, artefakt, ZAPIS)) for nazwa, artefakt in artefakty.items() if nazwa.startswith(ARTEFAKT)]
    return frozenset().union(*(mutacje_zmiany.wczytaj_osadzone(zapis.get(mutacje_zmiany.OSADZONE, [])) for zapis in zapisy))


def macierz(noc: mutacje_zmiany.ZakresMutacji, n: int, repository: Repository, koszty: czasy_ci.KosztyPlikow) -> list[dict[str, int | bool]]:
    """Wpis macierzy każdej z ``n`` części nocy: jej numer i ``przegladarka``, gdy testy jej mutacji sięgają Atrapy efenix,
    więc zadanie części instaluje Chromium jak zadanie pytest planu CI (``zakres_runu.potrzebuja_chromium``).

    Wpisy idą od części, której plik ma najwięcej pracy dotkniętych nim plików testów (``koszty``): mutacja pliku
    uruchamia jego testy, a część czeka na swój najdroższy plik. Równa praca zostawia kolejność numerów."""

    wpisy: list[tuple[float, dict[str, int | bool]]] = []
    for czesc in Czesc.calosc(n):
        dotkniete = mutacje_zmiany.tests_of(repository, {mutant.path for mutant in noc.czesc(czesc)})
        testy = [test for testy_pliku in dotkniete.values() for test in testy_pliku]
        praca = max((sum(koszty.s(plik) for plik in {test.partition("::")[0] for test in testy_pliku}) for testy_pliku in dotkniete.values()), default=0.0)
        wpisy.append((praca, {"czesc": czesc.k, "przegladarka": bool(potrzebuja_chromium(testy, repository))}))
    return [wpis for _, wpis in sorted(wpisy, key=lambda para: -para[0])]


def macierz_pokrycia(noc: mutacje_zmiany.ZakresMutacji, repository: Repository) -> list[dict[str, int | bool]]:
    """Wpis macierzy każdego zadania pokrycia nocy: numer jego części plików testów nocy (``Czesc.co_nta`` listy
    ``ZakresMutacji.pliki_testow``, jak w ``mutacje_zmiany.py --pokrycie-czesc``) i ``przegladarka``, gdy któryś z nich
    sięga Atrapy efenix. Zadań jest ``CZESCI_POKRYCIA``, a mniej, gdy noc ma mniej plików testów."""

    testy = noc.pliki_testow(repository)
    return [
        {"czesc": czesc.k, "przegladarka": bool(potrzebuja_chromium(czesc.co_nta(testy), repository))}
        for czesc in Czesc.calosc(min(CZESCI_POKRYCIA, len(testy)))
    ]


def zaplanuj(
    github: GitHub,
    root: Path,
    od: str,
    zakres: Path | None,
    *,
    osadzone_plik: Path | None = None,
    wyzwolenie: Wyzwolenie = RECZNE,
    teraz: datetime | None = None,
    na_czesc: int = NA_CZESC,
    czesci_na_noc: int = CZESCI_NA_NOC,
    koszty: czasy_ci.KosztyPlikow = BEZ_CZASOW,
) -> int:
    """Plan nocy w ``root``: baza, koniec jej zakresu i macierz części po najwyżej ``na_czesc`` mutacji, najwyżej
    ``czesci_na_noc`` części, od najdroższej według ``koszty`` plików testów, w ``GITHUB_OUTPUT``, a z ``zakres`` plik
    artefaktu ``zakres-nocy``. Mutacji, którym czerwone runy tej bazy dały werdykt bez issue (``osadzone``), plan nie
    liczy, a ich tożsamości zapisuje w ``osadzone_plik`` (artefakt ``osadzone-nocy``) dla zadań pokrycia i części. Noc doby (``wyzwolenie``),
    przed którą doba ``teraz`` miała już run nocy, nic nie mutuje: ``do`` to baza, a ``GITHUB_OUTPUT`` ma
    ``pominieta=true``."""

    teraz = teraz or datetime.now(UTC)
    od_sha, skad = baza(github, root, od, teraz)
    if (wczesniejsza := _wczesniejsza_noc(github, wyzwolenie, teraz)) is not None:
        print(f"MUTACJE NOCNE | noc doby biegła już w runie {wczesniejsza}: ten run nic nie mutuje, a następna noc zacznie od tej samej bazy")
        return _zapisz_plan(od_sha, skad, od_sha, [], [], 0, zakres, osadzone_plik, frozenset(), pominieta=True)
    osadzone_czerwonych, czerwone = osadzone(github, root, od_sha)
    if czerwone:
        print(f"MUTACJE NOCNE | czerwone runy tej bazy {', '.join(map(str, czerwone))}: noc pomija {len(osadzone_czerwonych)} mutacji, którym dały werdykt bez issue")
    caly = mutacje_zmiany.ZakresMutacji.od(od_sha, root).bez_osadzonych(osadzone_czerwonych)
    if caly.zly_wyjatek is not None:
        print(f"MUTACJE NOCNE | {caly.zly_wyjatek}; część mutacji to zgłosi")
    do_sha = caly.najdalszy_koniec(na_czesc * czesci_na_noc)
    noc = caly.do(do_sha)
    repository = Repository.scan(root)
    wpisy = macierz(noc, noc.liczba_czesci(na_czesc), repository, koszty)
    pokrycie = macierz_pokrycia(noc, repository) if wpisy else []
    zalegle = len(caly.mutanty) - len(noc.mutanty)
    return _zapisz_plan(od_sha, skad, do_sha, wpisy, pokrycie, noc.liczba_mutacji, zakres, osadzone_plik, osadzone_czerwonych, zalegle=zalegle)


def _zapisz_plan(
    od_sha: str,
    skad: str,
    do_sha: str,
    wpisy: list[dict[str, int | bool]],
    pokrycie: list[dict[str, int | bool]],
    mutacje: int,
    zakres: Path | None,
    osadzone_plik: Path | None,
    osadzone_czerwonych: frozenset[mutacje_zmiany.Tozsamosc],
    *,
    pominieta: bool = False,
    zalegle: int = 0,
) -> int:
    if zalegle:
        print(f"{PREFIKS} | {_ZALEGLOSC} {zalegle} mutacji zmian po {do_sha} czeka na następne noce")
    z_chromium = sum(bool(wpis["przegladarka"]) for wpis in wpisy)
    print(f"{PREFIKS} PLAN | baza {od_sha} ({skad}) | do {do_sha} | {_MUTACJE_PLANU} {mutacje} | części {len(wpisy)} | z Chromium {z_chromium}")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(
                f"baza={od_sha}\ndo={do_sha}\nczesci={json.dumps(wpisy)}\nliczba={len(wpisy)}\npokrycie={json.dumps(pokrycie)}\n"
                + ("pominieta=true\n" if pominieta else "")
            )
    if zakres is not None:
        zakres.parent.mkdir(parents=True, exist_ok=True)
        zakres.write_text(json.dumps({"baza": od_sha, "do": do_sha}), encoding="utf-8")
    if osadzone_plik is not None:
        mutacje_zmiany.zapisz_osadzone(osadzone_plik, osadzone_czerwonych)
    return 0


# --- zgłoszenie ---


@dataclass(frozen=True)
class Przezyta:
    """Mutacja z zapisu części, którą noc zgłasza, z ``rodzaj`` swojej listy: plik, linia i opis jej nazwy, zmienione
    linie, które psuje, i jej klucz."""

    plik: str
    linia: int
    opis: str
    linie: tuple[int, ...]
    klucz: str
    rodzaj: Rodzaj = Rodzaj.PRZEZYTA

    @classmethod
    def z_zapisu(cls, wpis: dict[str, Any], rodzaj: Rodzaj = Rodzaj.PRZEZYTA) -> Przezyta:
        """Wpis ``mutacje_zmiany.entry``; wpis bez któregoś pola, z polem ``null`` albo z polem innego typu to ``ValueError``."""

        if not isinstance(wpis, dict):
            raise ValueError(f"wpis mutacji to nie obiekt JSON: {wpis}")
        if brak := next((pole for pole in ("plik", "linia", "opis", "linie", "klucz") if wpis.get(pole) is None), None):
            raise ValueError(f"wpis mutacji bez pola {brak!r}: {wpis}")
        try:
            return cls(str(wpis["plik"]), int(wpis["linia"]), str(wpis["opis"]), tuple(wpis["linie"]), str(wpis["klucz"]), rodzaj)
        except TypeError as blad:
            raise ValueError(f"wpis mutacji z polem innego typu ({blad}): {wpis}") from None

    @property
    def w_issue(self) -> str:
        """Linia ``MUTACJA`` issue: nazwa jak w ``NIEWYKRYTA`` i klucz, po którym noc nie zgłasza jej drugi raz."""

        return f"MUTACJA {self.plik}:{self.linia} {self.opis} | klucz {self.klucz}{self.rodzaj.dopisek}"


def zapisy(katalog: Path, liczba: int) -> tuple[list[Przezyta], list[str]]:
    """Mutacje każdego ``Rodzaj`` wszystkich części oraz przyczyny porażki części, które nie dały wyniku.

    Część, której limit czasu minął po pokryciu (kod 3 ``tools/mutacje_zmiany.py``), dała wynik: jej mutacje bez werdyktu
    idą do issue jak przeżyte, więc nie zatrzymują bazy nocy."""

    przezyte: list[Przezyta] = []
    problemy: list[str] = []
    for numer in range(1, liczba + 1):
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT}{numer}" / ZAPIS).read_text(encoding="utf-8"))
            # Część, której limit czasu minął przed werdyktem części mutacji, też zapisuje przeżyte z reszty.
            czesci = [Przezyta.z_zapisu(wpis, rodzaj) for rodzaj in Rodzaj for wpis in zapis[rodzaj.lista]]
        except (OSError, ValueError) as blad:
            problemy.append(f"część {numer}/{liczba} bez zapisu: {blad}")
            continue
        przezyte += czesci
        if zapis.get("kod") is None:
            problemy.append(f"część {numer}/{liczba} bez kodu wyjścia: {zapis.get('wynik')}")
        elif zapis["kod"] not in mutacje_zmiany.KODY_Z_WYNIKIEM:
            problemy.append(f"część {numer}/{liczba}: {zapis.get('wynik')}")
    return przezyte, problemy


@dataclass(frozen=True)
class Autor:
    """PR (``numer``) albo, bez PR, commit, który ostatni zmienił linię mutacji: commity jednego PR to jeden autor."""

    numer: int | None
    commit: str | None = None

    @property
    def tytul(self) -> str:
        return f"Przeżyte mutacje z {self.w_tytule}"

    @property
    def w_tytule(self) -> str:
        return f"#{self.numer}" if self.numer else f"commitu {str(self.commit)[:9]}"

    @property
    def nazwa(self) -> str:
        return f"#{self.numer}" if self.numer else f"commit {self.commit}"


def _pr_z_tematu(temat: str) -> int | None:
    znalezione = MERGE.fullmatch(temat) or SQUASH.fullmatch(temat)
    return int(znalezione["numer"]) if znalezione else None


def _wniesienie(root: Path, linia_main: Sequence[str], commit: str) -> int:
    """Pozycja na ``linia_main`` commitu, który wniósł ``commit`` na linię pierwszych rodziców HEAD."""

    potomkowie = {commit, *repo.git(root, "rev-list", "--ancestry-path", f"{commit}..HEAD").split()}
    return next(numer for numer, kandydat in enumerate(linia_main) if kandydat in potomkowie)


def _commity_linii(root: Path, plik: str, linie: Sequence[int]) -> set[str]:
    """Commity, które ostatnie zmieniły ``linie`` pliku na HEAD; wiersz ``blame -l -s`` zaczyna pełny SHA commitu."""

    zakresy = [argument for linia in linie for argument in ("-L", f"{linia},{linia}")]
    return {wiersz.split(maxsplit=1)[0] for wiersz in repo.git(root, "blame", "-l", "-s", *zakresy, "HEAD", "--", plik, timeout=None).splitlines()}


def przypisz(github: GitHub, root: Path, od: str, przezyte: Sequence[Przezyta]) -> dict[Autor, list[Przezyta]]:
    """Przeżyte mutacje według PR-u, który ostatni zmienił ich zmienione linie."""

    linia_main = repo.git(root, "rev-list", "--first-parent", "--reverse", f"{od}..HEAD").split()
    wniesione: dict[str, int] = {}
    autorzy: dict[str, Autor] = {}
    wynik: dict[Autor, list[Przezyta]] = {}
    for mutacja in przezyte:
        # Linie mutacji to linie zmienione od ``od``, więc blame daje tylko commity nocy.
        commity = _commity_linii(root, mutacja.plik, mutacja.linie)
        for commit in commity - wniesione.keys():
            wniesione[commit] = _wniesienie(root, linia_main, commit)
        commit = max(sorted(commity), key=wniesione.__getitem__)
        if commit not in autorzy:
            autorzy[commit] = autor(github, root, linia_main[wniesione[commit]], commit)
        wynik.setdefault(autorzy[commit], []).append(mutacja)
    return wynik


def autor(github: GitHub, root: Path, scalenie: str, commit: str) -> Autor:
    """PR, który wniósł ``commit`` commitem ``scalenie`` linii pierwszych rodziców HEAD."""

    if numer := _pr_z_tematu(repo.git(root, "log", "-1", "--format=%s", scalenie).strip()):
        return Autor(numer)
    scalone = [pr for pr in github.json(f"{REPO}/commits/{commit}/pulls") if pr.get("merged_at")]
    return Autor(int(scalone[0]["number"])) if scalone else Autor(None, commit)


def wyniki_skilli(plan: plan_runu.Plan, katalog: Path) -> tuple[list[str], list[tuple[str, NearLimit]], list[str]]:
    """Kroki skilli (``skill:<skill>/<skrypt>``), które padły w zadaniach ``plan``, ostrzeżenia ``CZAS BLISKO LIMITU``
    z kluczem kroku i przyczyny zadań bez wyniku."""

    padly, blisko, problemy = set(), [], []
    for zadanie in plan.zadania:
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT_SKILLI}{zadanie.id}" / plan_runu.WYKONANIE.name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as blad:
            problemy.append(f"{zadanie.nazwa} bez zapisu: {blad}")
            continue
        if zapis.get("plan") != plan.digest:
            problemy.append(f"{zadanie.nazwa}: zapis innego planu niż {plan.digest[:12]}")
            continue
        # Części jednego kroku w zadaniu zgłaszają się pod jego kluczem: krok padł, gdy padła którakolwiek.
        zaplanowane = {str(klucz.zgloszony) for klucz in zadanie.klucze}
        if brak := sorted(zaplanowane - {jednostka["klucz"] for jednostka in zapis["jednostki"]}):
            problemy.append(f"{zadanie.nazwa}: jednostki bez wyniku: {', '.join(brak)}")
        padly |= zaplanowane & {jednostka["klucz"] for jednostka in zapis["jednostki"] if jednostka["status"] != "ok"}
        blisko += [NearLimit.from_record(wpis) for wpis in zapis["blisko_limitu"]]
    return sorted(padly), blisko, problemy


@dataclass
class Skrypty:
    """Co z nocnych kroków skilli trafia do issue jednego PR-u: skrypty, które padły, i ostrzeżenia ``CZAS BLISKO LIMITU``."""

    padly: list[str] = field(default_factory=list)
    blisko: list[NearLimit] = field(default_factory=list)


def przypisz_skrypty(
    github: GitHub, root: Path, od: str, padly: Sequence[str], blisko: Sequence[tuple[str, NearLimit]] = ()
) -> tuple[dict[Autor, Skrypty], list[str]]:
    """Skrypty mutacji skilli, które padły, i ostrzeżenia ``CZAS BLISKO LIMITU`` ich mutacji według PR-u, którego zmiana
    od ``od`` uruchomiła krok (``_autor_kroku``), i przyczyny porażki tych, których nie ma komu przypisać, bo ``main``
    nie ma commitu od ``od``."""

    katalog = Katalog.skanuj(root)
    # Ten sam wybór co plan nocy (``tools/plan_ci.py``). Nieśledzone zapisy artefaktów w checkoucie zgłoszenia nie mają
    # historii, więc ``_autor_kroku`` ich nie znajduje w ``git log``.
    wybrane = {jednostka.skill(w.krok.key): w for w in zakres(Zdarzenie.NOC, changed_since(root, od), root).wybrane}
    linia_main = repo.git(root, "rev-list", "--first-parent", "--reverse", f"{od}..HEAD").split()
    autorzy = {
        klucz: _autor_kroku(github, root, od, linia_main, katalog.krok(Klucz.z_tekstu(klucz)), wybrane.get(klucz)) for klucz in {*padly, *(klucz for klucz, _ in blisko)}
    }
    wynik: dict[Autor, Skrypty] = {}
    problemy: list[str] = []
    for klucz in padly:
        if (kto := autorzy[klucz]) is None:
            # Skill bez pilnuje biegnie także w nocy bez commitu od bazy, a wtedy jego porażka nie ma PR ani issue.
            problemy.append(f"skrypt {katalog.krok(Klucz.z_tekstu(klucz)).command[0]} padł, a od bazy {od} main nie ma commitu, którego PR by go dostał")
            continue
        wynik.setdefault(kto, Skrypty()).padly.append(katalog.krok(Klucz.z_tekstu(klucz)).command[0])
    for klucz, ostrzezenie in blisko:
        if (kto := autorzy[klucz]) is None:
            problemy.append(f"{_klucz_blisko(ostrzezenie)}: od bazy {od} main nie ma commitu, którego PR by je dostał")
            continue
        wynik.setdefault(kto, Skrypty()).blisko.append(ostrzezenie)
    return wynik, problemy


def _autor_kroku(
    github: GitHub, root: Path, od: str, linia_main: Sequence[str], krok: Step, wybrany: KrokSkilla | None
) -> Autor | None:
    """PR, który ostatni zmienił plik uruchamiający krok (``KrokSkilla.pliki`` wyboru nocy), najpierw w folderze skilla,
    a bez takiego pliku ostatni PR nocy; ``None``, gdy ``main`` nie ma commitu od ``od``.

    Pliki to różnica netto od ``od``: plik, którego zmiany nocy się znoszą, nie wskazuje PR-u, ale plik, który zmienił się
    netto, wskazuje PR, który ostatni go zmienił, także gdy ten PR cofnął tylko część zmiany. Krok, którego wybór
    nocy nie wybrał (``wybrany`` ``None``: plan z innego commitu albo innej bazy), też dostaje ostatni PR nocy."""

    folder = krok.folder
    pliki = wybrany.pliki if wybrany else frozenset()
    w_folderze = sorted(plik for plik in pliki if plik.startswith(folder))
    grupy = [grupa for grupa in (w_folderze, sorted(pliki.difference(w_folderze))) if grupa]
    # Grupa bez ścieżek daje ostatni commit nocy.
    for grupa in (*grupy, []):
        if commit := repo.git(root, "log", "-1", "--format=%H", f"{od}..HEAD", "--", *grupa).strip():
            return autor(github, root, linia_main[_wniesienie(root, linia_main, commit)], commit)
    return None


def akcje(github: GitHub, przypisane: dict[Autor, list[Przezyta]], run: str) -> tuple[list[Akcja], list[Przezyta]]:
    """Nowe issue dla PR bez issue, a komentarz z nowymi mutacjami dla PR, którego issue nie ma jeszcze ich kluczy, dla
    najwyżej ``ISSUES_NA_NOC`` PR-ów z najwięcej nowymi przeżytymi, a potem wszystkimi nowymi mutacjami, oraz nowe mutacje
    PR-ów ponad limit, które zostają bez issue."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in issues(github, ETYKIETY[1], "all"):
        istniejace.setdefault(znalezione["title"], znalezione)
    kandydaci: list[tuple[Autor, dict[str, Any] | None, list[Przezyta]]] = []
    for kto, mutacje in przypisane.items():
        issue = istniejace.get(kto.tytul)
        if issue is None:
            kandydaci.append((kto, None, mutacje))
            continue
        znane = "\n".join([issue.get("body") or "", *(komentarz["body"] or "" for komentarz in strony(github, f"{REPO}/issues/{issue['number']}/comments"))])
        klucze = {znalezione["klucz"] for znalezione in _KLUCZ.finditer(znane)}
        if nowe := [mutacja for mutacja in mutacje if mutacja.klucz not in klucze]:
            kandydaci.append((kto, issue, nowe))
    kandydaci.sort(key=lambda kandydat: (-sum(mutacja.rodzaj is Rodzaj.PRZEZYTA for mutacja in kandydat[2]), -len(kandydat[2])))
    wynik: list[Akcja] = []
    for kto, issue, mutacje in kandydaci[:ISSUES_NA_NOC]:
        linie = [mutacja.w_issue for mutacja in mutacje]
        if issue is None:
            tresc = [
                f"Nocne mutacje `main` ([run]({run})) przeżyły testy na liniach, które ostatnio zmienił {kto.nazwa}:",
                "",
                *blok_kodu(linie),
                "",
                "Dla każdej linii `MUTACJA` dodaj test, który zabija tę mutację (dowód: `tools/mutacje.py`), albo napisz w komentarzu "
                "`MUTACJA <plik>:<linia> <opis> | nie warto, bo <powód>`.",
                *_rady(mutacje),
                "Gdy każda linia ma test albo powód, zamknij issue (ADR 0021).",
            ]
            wynik.append(Zaloz(kto.tytul, "\n".join(tresc), ETYKIETY))
            continue
        tresc = [f"Nowe przeżyte mutacje z [runu]({run}):", "", *blok_kodu(linie), *_rady(mutacje)]
        wynik.append(_uzupelnij(issue, "\n".join(tresc)))
    return wynik, [mutacja for *_, mutacje in kandydaci[ISSUES_NA_NOC:] for mutacja in mutacje]


def _bez_issue(mutacje: Sequence[Przezyta]) -> str:
    pliki = Counter(mutacja.plik for mutacja in mutacje)
    return f"mutacje {len(mutacje)}, pliki {len(pliki)}" + (f": {', '.join(f'{plik} ({liczba})' for plik, liczba in sorted(pliki.items()))}" if pliki else "")


def _rady(mutacje: Sequence[Przezyta]) -> list[str]:
    """Rada każdego rodzaju mutacji bez werdyktu, który jest wśród ``mutacje``."""

    obecne = {mutacja.rodzaj for mutacja in mutacje}
    return [f"Linia z `{rodzaj.dopisek.removeprefix(' | ')}` {rodzaj.rada}" for rodzaj in Rodzaj if rodzaj.rada and rodzaj in obecne]


def _po_rdzeniu(tekst: str, rdzen: str) -> list[str]:
    """Reszta każdej linii ``tekst``, która zaczyna się rdzeniem linii nocy ``rdzen``: pusta dla samego rdzenia, a po
    ``rdzen |`` tekst za kreską bez spacji wokół."""

    reszty = []
    for obecna in (linia.strip() for linia in tekst.splitlines()):
        if obecna == rdzen:
            reszty.append("")
        elif obecna.startswith(f"{rdzen} |"):
            reszty.append(obecna.removeprefix(f"{rdzen} |").strip())
    return reszty


def _ma(tekst: str, linia: str) -> bool:
    return bool(_po_rdzeniu(tekst, linia))


def akcje_skryptow(github: GitHub, przypisane: dict[Autor, Skrypty], run: str) -> list[Akcja]:
    """Issue ``Przeżyte mutacje skilli z #N`` dla PR bez niego, a komentarz z liniami ``SKRYPT`` i ``CZAS BLISKO LIMITU``,
    których jego issue nie ma. Ostrzeżenie porównuje bez czasu, który zmienia się co noc, więc mutacja trafia do issue raz."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in issues(github, ETYKIETY[1], "all"):
        istniejace.setdefault(znalezione["title"], znalezione)
    wynik: list[Akcja] = []
    for kto, skrypty in przypisane.items():
        tytul = f"Przeżyte mutacje skilli z {kto.w_tytule}"
        issue = istniejace.get(tytul)
        znane = "" if issue is None else "\n".join(
            [issue.get("body") or "", *(komentarz["body"] or "" for komentarz in strony(github, f"{REPO}/issues/{issue['number']}/comments"))]
        )
        padly = [linia for linia in (f"{_SKRYPT}{skrypt}" for skrypt in skrypty.padly) if not _ma(znane, linia)]
        blisko = [_linia_blisko(ostrzezenie) for ostrzezenie in skrypty.blisko if not _ma(znane, _klucz_blisko(ostrzezenie))]
        if issue is None:
            tresc = []
            if padly:
                tresc += [
                    f"Nocne skrypty mutacji skilli `main` ([run]({run})) padły po zmianie folderu skilla, którą ostatnio wniósł {kto.nazwa}:",
                    "",
                    *blok_kodu(padly),
                    "",
                    "Log runu pokazuje, która mutacja przeżyła sprawdzenie skilla (`NIEWYKRYTA`), straciła kotwicę (`NIEAKTUALNA`) "
                    f"albo czy padła podstawa; część z planu odtwarzasz z `{ZMIENNA_CZESCI}=<k>/<n>`.",
                    "Dla każdej linii `SKRYPT` popraw sprawdzenie skilla albo tabelę mutacji, albo napisz w komentarzu "
                    "`SKRYPT <skrypt> | nie warto, bo <powód>`.",
                    "",
                ]
            if blisko:
                tresc += [
                    f"Mutacje nocnych skryptów mutacji skilli `main` ([run]({run})) po zmianie, którą ostatnio wniósł {kto.nazwa}, "
                    "trwały ponad połowę limitu czasu mutacji:",
                    "",
                    *blok_kodu(blisko),
                    "",
                    RADA_BLISKO,
                    "",
                ]
            wynik.append(Zaloz(tytul, "\n".join([*tresc, "Gdy każda linia ma poprawkę albo odpowiedź, zamknij issue (ADR 0021)."]), ETYKIETY))
            continue
        tresc = [f"Nowe skrypty, które padły w [runie]({run}):", "", *blok_kodu(padly)] if padly else []
        if blisko:
            tresc += [*([""] if tresc else []), f"Mutacje blisko limitu czasu w [runie]({run}):", "", *blok_kodu(blisko), "", RADA_BLISKO]
        if tresc:
            wynik.append(_uzupelnij(issue, "\n".join(tresc)))
    return wynik


RADA_BLISKO = (
    "To jeszcze nie porażka, ale po limicie mutacja da `PRZEKROCZONY CZAS`, a skrypt padnie: dla każdej linii `CZAS BLISKO LIMITU` "
    "przenieś mutację do mniejszego zakresu sprawdzenia albo przyspiesz sprawdzenie, albo napisz w komentarzu "
    "`CZAS BLISKO LIMITU <skrypt> | <mutacja> | nie warto, bo <powód>`. Noc zgłasza mutację raz, choć jej czas zmienia się co noc."
)


def _klucz_blisko(ostrzezenie: NearLimit) -> str:
    """Początek linii ostrzeżenia w issue: bez czasu, który zmienia się co noc, więc po nim noc nie zgłasza go drugi raz."""

    return f"{_BLISKO}{ostrzezenie.script} | {ostrzezenie.name}"


def _linia_blisko(ostrzezenie: NearLimit) -> str:
    czesc = f" ({ZMIENNA_CZESCI}={ostrzezenie.part})" if ostrzezenie.part else ""
    return f"{_klucz_blisko(ostrzezenie)} | {ostrzezenie.seconds}{_Z_LIMITU}{ostrzezenie.limit_s:g} s{czesc}"


def rdzen(linia: str) -> str | None:
    """Rdzeń linii, którą noc pisze w issue: linia ``MUTACJA`` do klucza (``Przezyta.w_issue``), linia ``SKRYPT`` cała,
    a linia ``CZAS BLISKO LIMITU`` bez czasu (``_klucz_blisko``). Po rdzeniu noc nie zgłasza linii drugi raz (``_ma``),
    a agent na nią odpowiada (``rdzeń | <odpowiedź>``). Każda inna linia, także odpowiedź agenta, daje ``None``."""

    linia = linia.strip()
    if linia.startswith("MUTACJA ") and (klucz := _KLUCZ.search(linia)):
        return linia[: klucz.start()].rstrip()
    if linia.startswith(_SKRYPT):
        return linia
    if linia.startswith(_BLISKO) and (czas := _CZAS_BLISKO.search(linia)):
        return linia[: czas.start()]
    return None


# Odpowiedzi z rad nocy, po których linia nie jest luką w testach ani sprawdzeniu: test albo brama typów już ją widzi,
# albo agent uzasadnił, że nie ma czego widzieć.
BEZ_LUKI = ("wykryta", "nie warto")
# Autor treści issue i komentarzy nocy w ``gh issue list --json`` (``github-actions``) i w REST API (``[bot]``).
_NOC = ("github-actions", "github-actions[bot]")


@dataclass(frozen=True)
class Wystapienie:
    """Issue przeżytych mutacji z liniami nocy (``rdzen``), na które ostatnia odpowiedź agenta nie jest ``BEZ_LUKI``."""

    numer: int
    tytul: str
    linie: tuple[str, ...]


def wystapienia(issues_json: Sequence[Any]) -> tuple[list[Wystapienie], int]:
    """Wystąpienia z wyniku ``gh issue list --json number,title,body,comments`` i liczba issues bez wystąpienia.

    Linie nocy to linie treści issue i komentarzy ``_NOC``, którym ``rdzen`` daje rdzeń. Odpowiedź na linię to reszta
    linii komentarza agenta po ``rdzeń |`` (postać z rady nocy) albo po całej linii nocy i ``|``; liczy się ostatnia,
    więc późniejsza odpowiedź odwołuje wcześniejszą, a sam cytat linii nocy niczego nie odpowiada. Issue bez żadnej linii
    nocy to ``ValueError``: noc pisze je w postaci, której ``rdzen`` nie zna.
    """

    wynik: list[Wystapienie] = []
    bez = 0
    for issue in issues_json:
        if not isinstance(issue, dict) or any(pole not in issue for pole in ("number", "title", "body", "comments")):
            raise ValueError(f"issue bez pól number, title, body i comments (gh issue list --json number,title,body,comments): {str(issue)[:200]}")
        komentarze = issue["comments"]
        nocne = [issue["body"] or "", *(k["body"] or "" for k in komentarze if k["author"]["login"] in _NOC)]
        pelne: dict[str, set[str]] = {}
        for linia in (linia.strip() for tekst in nocne for linia in tekst.splitlines()):
            if r := rdzen(linia):
                pelne.setdefault(r, set()).add(linia)
        if not pelne:
            raise ValueError(f"issue #{issue['number']} nie ma linii nocy w postaci, którą zna rdzen()")
        agenta = [linia for k in komentarze if k["author"]["login"] not in _NOC for linia in (k["body"] or "").splitlines()]
        otwarte = tuple(r for r, linie in pelne.items() if not _ostatnia_odpowiedz(agenta, (*sorted(linie, key=len, reverse=True), r)).startswith(BEZ_LUKI))
        if otwarte:
            wynik.append(Wystapienie(int(issue["number"]), str(issue["title"]), otwarte))
        else:
            bez += 1
    return wynik, bez


def _ostatnia_odpowiedz(linie: Sequence[str], przedrostki: Sequence[str]) -> str:
    """Ostatnia niepusta reszta linii po pierwszym z ``przedrostki``, od którego zaczyna się linia; ``""`` bez odpowiedzi."""

    ostatnia = ""
    for linia in linie:
        reszta = next((reszty[0] for przedrostek in przedrostki if (reszty := _po_rdzeniu(linia, przedrostek))), "")
        ostatnia = reszta or ostatnia
    return ostatnia


def _uzupelnij(issue: dict[str, Any], tresc: str) -> Skomentuj:
    """Komentarz z nowymi liniami; zamknięte issue wraca otwarte z etykietą pracy dla agenta."""

    return Skomentuj(issue["number"], tresc, ETYKIETY[:1] if issue["state"] == "closed" else ())


def zglos(github: GitHub, root: Path, od: str, katalog: Path, liczba: int, run: str, plan_skilli: plan_runu.Plan | None = None) -> int:
    przezyte, problemy = zapisy(katalog, liczba)
    zgloszone, ponad_limit = akcje(github, przypisz(github, root, od, przezyte), run)
    linie = wykonaj_akcje(github, zgloszone, PREFIKS)
    padly: list[str] = []
    blisko: list[tuple[str, NearLimit]] = []
    if plan_skilli is not None:
        padly, blisko, problemy_skilli = wyniki_skilli(plan_skilli, katalog)
        przypisane, bez_pr = przypisz_skrypty(github, root, od, padly, blisko)
        problemy += problemy_skilli + bez_pr
        linie += wykonaj_akcje(github, akcje_skryptow(github, przypisane, run), PREFIKS)
    print("\n".join(linie) or "MUTACJE NOCNE | nic nowego do zgłoszenia")
    print(f"MUTACJE NOCNE BEZ ISSUE | ponad limit {ISSUES_NA_NOC} issues na noc {_bez_issue(ponad_limit)}")
    if problemy:
        print(f"MUTACJE NOCNE FAIL | {'; '.join(problemy)}")
        return 1
    skille = "" if plan_skilli is None else f" | zadania skilli {len(plan_skilli.zadania)} | padło skryptów {len(padly)}"
    skille += f" | blisko limitu czasu {len(blisko)}" if blisko else ""
    liczby = Counter(mutacja.rodzaj for mutacja in przezyte)
    werdykty = " | ".join(f"{rodzaj.nazwa} {liczby[rodzaj]}" for rodzaj in Rodzaj if rodzaj is Rodzaj.PRZEZYTA or liczby[rodzaj])
    print(f"MUTACJE NOCNE OK | części {liczba} | {werdykty}{skille}")
    return 0


@dataclass(frozen=True)
class Zadanie:
    nazwa: str
    start: datetime
    koniec: datetime


@dataclass(frozen=True)
class Odczyt:
    run: int
    adres: str
    utworzony: datetime
    zadania: tuple[Zadanie, ...]
    mutacje: int
    zaleglosc: int
    czasy_czesci: dict[str, float]
    bez_werdyktu: dict[str, int]

    @property
    def sciana_s(self) -> float:
        return (max(z.koniec for z in self.zadania) - self.utworzony).total_seconds() if self.zadania else 0.0

    @property
    def praca_s(self) -> float:
        return sum((z.koniec - z.start).total_seconds() for z in self.zadania)

    @property
    def najdluzsza(self) -> tuple[str, float] | None:
        return max(self.czasy_czesci.items(), key=lambda para: para[1], default=None)

    @property
    def dzien(self) -> str:
        return f"{self.utworzony:%d.%m.%Y}"

    @property
    def gardla(self) -> list[str]:
        wynik = []
        if self.sciana_s > LIMIT_SCIANY_S:
            ostatnie = max(self.zadania, key=lambda z: z.koniec)
            wynik.append(
                f"ściana nocy {_h(self.sciana_s)} h ponad {_h(LIMIT_SCIANY_S)} h: ostatnie skończyło się zadanie `{ostatnie.nazwa}`,"
                f" które ruszyło {_h((ostatnie.start - self.utworzony).total_seconds())} h po utworzeniu runu i biegło {_h((ostatnie.koniec - ostatnie.start).total_seconds())} h"
            )
        if (najdluzsza := self.najdluzsza) is not None and najdluzsza[1] >= mutacje_zmiany.PART_LIMIT_S:
            wynik.append(f"część `{najdluzsza[0]}` doszła do limitu części: {najdluzsza[1]:.0f} s z `PART_LIMIT_S` {mutacje_zmiany.PART_LIMIT_S} s")
        if bez := sum(self.bez_werdyktu.values()):
            czesci = ", ".join(f"`{nazwa}` {n}" for nazwa, n in sorted(self.bez_werdyktu.items(), key=lambda para: -para[1]))
            wynik.append(f"{Verdict.NO_VERDICT} {bez}: {czesci}")
        return wynik

    def tresc(self) -> str:
        najdluzsza = "–" if self.najdluzsza is None else f"`{self.najdluzsza[0]}` {self.najdluzsza[1]:.0f} s"
        linie = [
            f"Treść zmienia co noc odczyt nocy mutacji (`tools/mutacje_nocne.py odczyt`, zadanie `odczyt` workflow `{WORKFLOW}`); uwagi idą w komentarze.",
            f"Issue jest otwarte, gdy ostatnia noc przekroczyła próg: ściana ponad {_h(LIMIT_SCIANY_S)} h, część do `PART_LIMIT_S`"
            f" ({mutacje_zmiany.PART_LIMIT_S} s) albo {Verdict.NO_VERDICT} > 0.",
            "",
            f"## Noc {self.dzien} ([run {self.run}]({self.adres}))",
            "",
            "Ściana nocy to czas od utworzenia runu do końca ostatniego zadania, a godziny runnerów to suma czasów jego zadań.",
            "",
            "| | |",
            "|---|---|",
            f"| ściana nocy | {_h(self.sciana_s)} h |",
            f"| godziny runnerów | {self.praca_s / 3600:.1f} h w {len(self.zadania)} zadaniach |",
            f"| mutacje nocy | {self.mutacje} w {len(self.czasy_czesci)} częściach |",
            f"| zaległość | {self.zaleglosc} mutacji |",
            f"| najdłuższa część | {najdluzsza} z `PART_LIMIT_S` {mutacje_zmiany.PART_LIMIT_S} s |",
            f"| {Verdict.NO_VERDICT} | {sum(self.bez_werdyktu.values())} w {len(self.bez_werdyktu)} częściach |",
            "",
            "## Wąskie gardło",
            "",
            *([f"- {gardlo}" for gardlo in self.gardla] or ["Noc w progach."]),
        ]
        return "\n".join(linie) + "\n"

    @property
    def linia(self) -> str:
        najdluzsza = "–" if self.najdluzsza is None else f"{self.najdluzsza[1]:.0f} s"
        return (
            f"{ODCZYT} | run {self.run} | ściana {_h(self.sciana_s)} h | runnery {self.praca_s / 3600:.1f} h | mutacje {self.mutacje}"
            f" | zaległość {self.zaleglosc} | najdłuższa część {najdluzsza} z {mutacje_zmiany.PART_LIMIT_S} s"
            f" | bez werdyktu {sum(self.bez_werdyktu.values())} | {'ponad próg' if self.gardla else 'w progach'}"
        )


def _h(sekundy: float) -> str:
    return f"{sekundy / 3600:.2f}"


def _chwila(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def _zadania_runu(api: Api, run: dict[str, Any]) -> list[dict[str, Any]]:
    def trwala(dane: dict[str, Any]) -> bool:
        return all(zadanie["status"] == "completed" for zadanie in dane["jobs"])

    zadania: list[dict[str, Any]] = []
    for strona in range(1, 100):
        partia: list[dict[str, Any]] = api.json(f"{REPO}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page={STRONA}&page={strona}", trwala)["jobs"]
        zadania += partia
        if len(partia) < STRONA:
            break
    return zadania


def _log(api: Api, zadanie: dict[str, Any]) -> str:
    if zadanie["status"] != "completed":
        raise ValueError(f"zadanie {zadanie['name']} jeszcze biegnie, więc noc nie ma jeszcze odczytu")
    return api.bajty(f"{REPO}/actions/jobs/{zadanie['id']}/logs").decode("utf-8", errors="replace")


def odczytaj(api: Api, run_id: int) -> Odczyt:
    run = api.json(f"{REPO}/actions/runs/{run_id}", lambda _: False)
    zadania = _zadania_runu(api, run)
    plan = next((zadanie for zadanie in zadania if zadanie["name"] == ZADANIE_PLANU), None)
    if plan is None:
        raise ValueError(f"run {run_id} nie ma zadania {ZADANIE_PLANU}")
    log_planu = _log(api, plan)
    if (linia_planu := _PLAN_W_LOGU.search(log_planu)) is None:
        raise ValueError(f"log zadania {ZADANIE_PLANU} runu {run_id} nie ma linii {PREFIKS} PLAN")
    zalegle = _ZALEGLOSC_W_LOGU.search(log_planu)
    czasy: dict[str, float] = {}
    bez_werdyktu: dict[str, int] = {}
    for czesc in (zadanie for zadanie in zadania if zadanie["name"].startswith(ZADANIE_CZESCI)):
        if n := len(_BEZ_WERDYKTU_W_LOGU.findall(_log(api, czesc))):
            bez_werdyktu[czesc["name"]] = n
        krok = next((krok for krok in czesc.get("steps") or [] if krok["name"] == KROK_CZESCI and krok.get("started_at") and krok.get("completed_at")), None)
        if krok is not None:
            czasy[czesc["name"]] = (_chwila(krok["completed_at"]) - _chwila(krok["started_at"])).total_seconds()
    zakonczone = tuple(
        Zadanie(zadanie["name"], _chwila(zadanie["started_at"]), _chwila(zadanie["completed_at"]))
        for zadanie in zadania
        if zadanie["status"] == "completed" and zadanie["conclusion"] != "skipped" and zadanie.get("started_at") and zadanie.get("completed_at")
    )
    return Odczyt(
        run_id,
        str(run["html_url"]),
        _chwila(run["created_at"]),
        zakonczone,
        int(linia_planu["mutacje"]),
        int(zalegle["zalegle"]) if zalegle else 0,
        czasy,
        bez_werdyktu,
    )


def _issues_odczytu(github: GitHub) -> list[dict[str, Any]]:
    return sorted(issues(github, ETYKIETA_ODCZYTU, "all"), key=lambda issue: int(issue["number"]))


def zapisz_odczyt(github: GitHub, odczyt: Odczyt) -> list[str]:
    linie: list[str] = []
    akcje: list[Akcja] = []
    if not (istniejace := _issues_odczytu(github)):
        linie += zaloz_etykiety(github, ETYKIETY_ODCZYTU, ODCZYT, zapis=True)
        linie += wykonaj_akcje(github, [Zaloz(TYTUL_ODCZYTU, odczyt.tresc(), (ETYKIETA_ODCZYTU,))], ODCZYT)
        istniejace = _issues_odczytu(github)
    else:
        akcje.append(Edytuj(int(istniejace[0]["number"]), odczyt.tresc()))
    numer, otwarte = int(istniejace[0]["number"]), istniejace[0]["state"] == "open"
    noc = f"Noc {odczyt.dzien} ([run {odczyt.run}]({odczyt.adres}))"
    if odczyt.gardla and not otwarte:
        akcje.append(Skomentuj(numer, f"{noc} ponad próg:\n\n" + "\n".join(f"- {gardlo}" for gardlo in odczyt.gardla), (ETYKIETA_ODCZYTU,)))
    if not odczyt.gardla and otwarte:
        akcje.append(Zamknij(numer, f"{noc} w progach: {odczyt.linia.removeprefix(f'{ODCZYT} | ')}."))
    return linie + wykonaj_akcje(github, akcje, ODCZYT)


def _odczyt(api: Api, github: GitHub, run_id: int, *, zapis: bool) -> int:
    odczyt = odczytaj(api, run_id)
    tekst = odczyt.tresc()
    if podsumowanie := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(podsumowanie, "a", encoding="utf-8") as plik:
            plik.write(tekst)
    print("\n".join(zapisz_odczyt(github, odczyt)) if zapis else tekst)
    print(odczyt.linia)
    return 0


def _drukuj_wystapienia(issues_json: Any) -> int:
    if not isinstance(issues_json, list):
        raise ValueError("plik issues to nie lista JSON z gh issue list")
    znalezione, bez = wystapienia(issues_json)
    for wystapienie in znalezione:
        for linia in wystapienie.linie:
            print(f"WYSTĄPIENIE #{wystapienie.numer} {wystapienie.tytul} | {linia}")
    print(f"{PREFIKS} WYSTĄPIENIA | issues z wystąpieniem {len(znalezione)} | bez wystąpienia {bez} | z {len(issues_json)}")
    return 0


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, github: GitHub | None = None, kopia: Path | None = None) -> int:
    """``root`` to checkout ``main``, którego zmiany noc mutuje, a ``github`` daje runy nocy, issue przeżytych mutacji
    i artefakty czasów CI; bez niego noc pyta ``GITHUB``, a czasy ``czasy_ci.GITHUB``."""

    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Baza i koniec zakresu nocy, liczba mutacji i części (GITHUB_OUTPUT).")
    plan.add_argument("--od", default="", help="Commit, od którego liczyć zmiany, a spoza linii HEAD jego wspólny przodek z HEAD (domyślnie koniec zakresu ostatniego udanego runu albo 24 h wstecz).")
    plan.add_argument("--baza", help="To samo co --od, jak w innych narzędziach zmiany; obie z różnymi wartościami to błąd użycia.")
    plan.add_argument("--zakres", type=Path, help=f"Plik JSON z bazą i końcem zakresu nocy (artefakt {ARTEFAKT_ZAKRESU}, z którego następna noc bierze bazę).")
    plan.add_argument(
        "--osadzone", type=Path, help=f"Plik tożsamości mutacji osądzonych bez issue przez czerwone runy tej bazy (artefakt {ARTEFAKT_OSADZONYCH} dla pokrycia i części)."
    )
    plan.add_argument("--czasy", type=Path, help="Katalog artefaktów czasy-ci, pobieranych od nowa (domyślnie .git/czasy-ci); kolejność części.")
    plan.add_argument("--zdarzenie", default="", help="Zdarzenie runu (github.event_name): run schedule nie robi drugiej nocy doby; id runu daje GITHUB_RUN_ID.")
    plan.add_argument("--start", default="", help=f"Wejście start runu: {START_AUTO} (start z pushu) nie robi drugiej nocy doby, jak run schedule.")
    polecenia.add_parser("start", help=f"Z pushu na main po {POCZATEK_NOCY:%H:%M} UTC uruchamia noc doby, gdy nie ma jeszcze jej runu.")
    wystapien = polecenia.add_parser("wystapienia", help="Linie nocy bez odpowiedzi wykryta albo nie warto w issues przeżytych mutacji (krok 1 polowania).")
    wystapien.add_argument("issues", type=Path, help="Wynik gh issue list --label przezyte-mutacje --json number,title,body,state,comments.")
    zgloszenie = polecenia.add_parser("zglos", help="Issue dla przeżytych mutacji ze wszystkich części.")
    zgloszenie.add_argument("--baza", required=True, help="Baza nocy z planu.")
    zgloszenie.add_argument("--zapisy", type=Path, required=True, help=f"Katalog z podkatalogami artefaktów {ARTEFAKT}<k>.")
    zgloszenie.add_argument("--czesci", type=int, required=True, help="Liczba części z planu.")
    zgloszenie.add_argument("--run", required=True, help="URL runu workflow.")
    zgloszenie.add_argument("--plan-skilli", type=Path, help=f"Plan skryptów mutacji skilli nocy; ich zapisy w podkatalogach {ARTEFAKT_SKILLI}<id zadania>.")
    odczyt = polecenia.add_parser("odczyt", help="Odczyt nocy z zadań runu, logu planu i logów części: ściana, godziny runnerów, zaległość, najdłuższa część, BEZ WERDYKTU.")
    odczyt.add_argument("run", type=int, help="Id runu nocy.")
    odczyt.add_argument("--issue", action="store_true", help=f"Zapisz odczyt w issue z etykietą {ETYKIETA_ODCZYTU} (bez tej flagi tylko drukuje).")
    args = parser.parse_args(argv)
    noc = GITHUB if github is None else github
    try:
        if args.polecenie == "wystapienia":
            return _drukuj_wystapienia(json.loads(args.issues.read_text(encoding="utf-8")))
        if args.polecenie == "start":
            return start(noc, datetime.now(UTC))
        if args.polecenie == "odczyt":
            return _odczyt(Api(ZRezerwa(noc, REZERWA_POMIARU) if github is None else noc, kopia), noc, args.run, zapis=args.issue)
        if args.polecenie == "plan":
            if args.od and args.baza and args.od != args.baza:
                plan.error(f"dwie różne bazy: --od {args.od} i --baza {args.baza}")
            # Czasy pobiera klient czasy_ci z krótkim limitem zapytania, żeby zawieszony gh nie trzymał planu nocy (limit
            # zadania 10 min).
            czasy_github = czasy_ci.GITHUB if github is None else github
            czasy = czasy_ci.z_mainu(args.czasy or czasy_ci.katalog_checkoutu(root), odswiez_po_s=0 if args.czasy else czasy_ci.ODSWIEZ_S, github=czasy_github)
            if czasy.blad:
                print(f"CZASY CI | {czasy.blad}; część bez zmierzonej pracy testów zostaje na miejscu swojego numeru")
            # Części biegną na ubuntu-latest z Pythonem 3.14, jak zadania pytest toru ``TOR_LOKALNY``.
            wyzwolenie = Wyzwolenie(args.zdarzenie, args.start, int(os.environ.get("GITHUB_RUN_ID") or 0))
            return zaplanuj(
                noc, root, args.od or args.baza or "", args.zakres, osadzone_plik=args.osadzone, wyzwolenie=wyzwolenie, koszty=czasy.koszty(czasy_ci.TOR_LOKALNY)
            )
        plan_skilli = None if args.plan_skilli is None else plan_runu.Plan.z_json(args.plan_skilli.read_text(encoding="utf-8"))
        return zglos(noc, root, args.baza, args.zapisy, args.czesci, args.run, plan_skilli)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as blad:
        szczegol = blad.stderr.strip() if isinstance(blad, subprocess.CalledProcessError) else blad
        print(f"MUTACJE NOCNE FAIL | {szczegol}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
