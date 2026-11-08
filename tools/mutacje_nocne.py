"""Liczy nocne mutacje na main i zgłasza przeżyte w issue PR-ów; użyj (plan), by bez testów zobaczyć bazę i części najbliższej nocy.

Mutacje nocne (ADR 0021): mutacje linii zmienionych na ``main`` od ostatniej nocy i issue dla przeżytych.

Workflow ``mutacje-nocne.yml`` biegnie raz na dobę na ``main`` i ręcznie (``workflow_dispatch`` z opcjonalnym ``od``).

- ``plan`` ustala bazę: ``--od`` (albo ``--baza``), gdy jest (``od`` spoza linii ``main`` zastępuje wspólny przodek HEAD i ``od``, od
  którego liczy też część), inaczej koniec zakresu ostatniego udanego runu tego workflow na ``main``
  (``do`` z jego artefaktu ``zakres-nocy``, a run bez tego artefaktu policzył wszystko do swojego ``headSha``), a bez
  takiego runu (albo gdy jego commit nie jest przodkiem HEAD) ostatni commit linii pierwszych rodziców HEAD sprzed 24 h.
  Mutacje od bazy liczy bez testów ``mutacje_zmiany.ZakresMutacji``, ten sam, który daje części jej mutacje, a zły
  wyjątek ``# mutacje-zmiany:`` liczy jako jedną mutację, żeby część go zgłosiła.
- Część ma najwyżej ``NA_CZESC`` mutacji: tyle, że kończy się w limicie czasu części także z najdroższymi mutacjami
  zmierzonych nocy, w testach linii i w testach pliku. Noc mutuje najwyżej ``CZESCI_NA_NOC`` części, żeby nie dostała więcej,
  niż przerobi. Gdy od bazy jest więcej mutacji, ``do`` to najdalszy commit linii
  pierwszych rodziców od bazy, do którego mutacje zmian mieszczą się w tym limicie (co najmniej pierwszy commit z
  mutacjami, także większy), a noc mutuje tylko zmiany do niego (``ZakresMutacji.do``). Bazą następnej nocy jest
  ``do``, więc zaległość przechodzi na kolejne noce, a nie przepada. Plan pisze do ``GITHUB_OUTPUT`` ``baza``, ``do``,
  ``czesci`` i ``liczba``, a z ``--zakres`` plik JSON z ``baza`` i ``do`` (artefakt ``zakres-nocy``). ``czesci`` to
  macierz zadań części: numer i ``przegladarka``, gdy testy, które mogą sprawdzać mutacje części (dotknięte jej
  plikami), sięgają Atrapy efenix, więc zadanie części instaluje Chromium tak jak zadanie pytest planu CI.
- Część k z n to ``tools/mutacje_zmiany.py --baza <baza> --do <do> --czesc k/n --zapis …``: kolejne mutacje z listy
  posortowanej po plikach, więc pokrycie biegnie na testach kilku plików, nie całej zmiany dnia.
- ``zglos`` czyta zapisy części. Każdą przeżytą mutację i mutację bez werdyktu po limicie czasu części przypisuje PR-owi, który ostatni zmienił jej linie: zmienione
  linie, które mutacja psuje, a nie linię jej nazwy, bo nazwę daje początek węzła, a w wielowierszowym ``if (`` zmienia
  się często tylko linia w środku. ``git blame`` tych linii daje commity nocy, bo to linie zmienione od bazy, a z nich
  liczy się ten, który linia pierwszych rodziców HEAD wniosła ostatni. Numer PR podaje temat commitu tej linii, który go wniósł
  (``Merge pull request #N`` albo squash ``… (#N)``); gałąź zbudowana na innej wnosi swoje commity do kilku PR-ów, a
  temat scalenia mówi, który z nich je scalił. Bez numeru w temacie PR podaje ``gh api …/commits/<sha>/pulls``. Na PR
  przypada jedno issue ``Przeżyte mutacje z #N`` z etykietami ``ETYKIETY``, a w nim linie
  ``MUTACJA <plik>:<linia> <opis> | klucz <klucz>`` (z pól zapisu części: id jak w ``NIEWYKRYTA``, klucz z ``mutacje_zmiany.fingerprint``),
  a mutacja bez werdyktu ma na końcu ``BEZ_WERDYKTU``: część po limicie czasu jej nie sprawdziła, więc noc nie wraca do
  jej zakresu, a sprawdza ją agent PR-u.
  Mutacji, której klucz issue już ma w treści albo komentarzu, nie dostaje drugi raz; nowe idą do istniejącego issue
  komentarzem, a zamknięte issue z nowymi wraca otwarte z ``ready-for-agent``.
  Część bez zapisu albo z kodem wyjścia spoza ``mutacje_zmiany.KODY_Z_WYNIKIEM`` (testy padają albo nie kończą się
  w limicie czasu części bez mutacji, zły wyjątek) czerwieni run po zgłoszeniu reszty, także przeżytych mutacji z jej
  zapisu, więc następna noc liczy od tej samej bazy, z tym samym limitem mutacji. Zgłoszone mutacje się nie powtórzą, także gdy PR z
  następnego dnia przesunie ich linie, bo klucz nie ma numerów linii.
- Skrypty mutacji skilli nocy planuje ``tools/plan_ci.py plan --zdarzenie noc --baza <baza>`` (skrypty skilli, których
  folder, runner mutacji albo sprawdzenie zmieniło się od bazy, i części każdego n podstaw z ``ci-czesci``), a zadanie
  planu wgrywa swój zapis wykonania jako artefakt ``mutacje-skilli-<id zadania>``. ``zglos --plan-skilli`` daje każdy
  skrypt, który padł, linią ``SKRYPT <skrypt>`` do issue ``Przeżyte mutacje skilli z #N`` PR-u, który ostatni zmienił
  plik zmieniony od bazy, który uruchomił krok w zakresie nocy (``KrokSkilla.pliki``): najpierw plik w folderze skilla,
  potem inny, a bez takiego pliku ostatni PR nocy; linii, którą issue już ma, nie dostaje drugi raz. Do tego samego issue idzie każde
  ostrzeżenie ``CZAS BLISKO LIMITU`` z zapisu zadania (``blisko_limitu``, ``NearLimit`` z ``tools/mutacje.py``): mutacja skryptu, której
  polecenie trwało ponad połowę limitu, linią ``CZAS BLISKO LIMITU <skrypt> | <mutacja> | <czas> z limitu …``. Czas
  zmienia się co noc, więc issue, które ma już linię z tym skryptem i mutacją, nie dostaje jej drugi raz (#935).
  Zadanie bez zapisu tego planu albo bez wyniku jednostki czerwieni run, tak jak skrypt, który padł, albo ostrzeżenie w
  nocy bez commitu od bazy, bo nie ma PR-u, który by je dostał.

Bazę, koniec zakresu i liczbę części nocy drukuje lokalnie bez testów:

    .venv/bin/python tools/mutacje_nocne.py plan
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from github import MERGE, REPO, SQUASH, Akcja, GhApi, GitHub, Skomentuj, Zaloz, blok_kodu, issues, strony
from github import wykonaj as wykonaj_akcje
from kroki_skilli import Katalog, Step
from jednostka import ZMIENNA_CZESCI, Czesc, Klucz
import jednostka
from mutacje import NearLimit
import mutacje_zmiany
import plan_runu
from repo import ROOT
import repo
from wplyw_zmiany import Repository, changed_since
from zakres_runu import KrokSkilla, Zdarzenie, potrzebuja_chromium, zakres

WORKFLOW = "mutacje-nocne.yml"
PREFIKS = "MUTACJE NOCNE"
# Część to 6 pełnych kolejek po WORKERS mutacji naraz. W nocach 31.10–3.11 (runy 41179652907, 41285996039, 41408995300,
# 41601085650) mediana mutacji pliku wynosiła 1–210 s, ale 16 mutacji tools/mutacje.py trwało w testach linii pełny limit
# mutacji (MUTATION_LIMIT_S). Testy kodu pliku jednej mutacji trwały najwyżej 836 s (doszło do nich najwyżej 11 z 32
# mutacji części), testy pliku, które biegną po jednej, najwyżej 441 s (najwyżej 37 z 93), pokrycie części 1006 s, a brama
# typów 58 s. Część mieści się w limicie czasu części (PART_LIMIT_S), gdy ma najgorszy czas każdego przebiegu naraz, a do
# dalszych przebiegów dochodzi tyle jej mutacji, co w którejś zmierzonej części: ok. 9700 s, a o kolejkę większa ok.
# 10 800 s (ADR 0021). Mutacja, która trwa pełny limit także w testach pliku, może go przekroczyć i zostaje bez werdyktu.
NA_CZESC = 6 * mutacje_zmiany.WORKERS
# Zadania części biegną najwyżej po 20 naraz (max-parallel w mutacje-nocne.yml), bo 60 zadań organizacji dzielą też
# runy CI PR-ów, więc noc to najwyżej dwie fale części.
CZESCI_NA_NOC = 40
OKNO = timedelta(hours=24)
ETYKIETY = ("ready-for-agent", "przezyte-mutacje")
# Artefakt części k w mutacje-nocne.yml: ``mutacje-nocne-<k>`` z plikiem ``--zapis`` narzędzia mutacji.
ARTEFAKT = "mutacje-nocne-"
ZAPIS = "czesc.json"
# Artefakt zadania skryptów mutacji skilli: ``mutacje-skilli-<id zadania planu>`` z zapisem ``plan_runu.WYKONANIE``.
ARTEFAKT_SKILLI = "mutacje-skilli-"
# Artefakt planu z plikiem ``--zakres``: baza i koniec zakresu nocy, od którego zaczyna następna noc.
ARTEFAKT_ZAKRESU = "zakres-nocy"
ZAKRES = "zakres.json"
# Klucz z linii ``MUTACJA`` w treści issue; długość klucza daje ``mutacje_zmiany.fingerprint``.
_KLUCZ = re.compile(r"\| klucz (?P<klucz>[0-9a-f]+)\b")
# Koniec linii ``MUTACJA`` mutacji, której część nie dała werdyktu przed limitem czasu.
BEZ_WERDYKTU = " | bez werdyktu w limicie czasu części"


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
    with zipfile.ZipFile(io.BytesIO(github.bajty(f"{REPO}/actions/artifacts/{artefakty[0]['id']}/zip"))) as archiwum:
        return str(json.loads(archiwum.read(ZAKRES))["do"])


def macierz(noc: mutacje_zmiany.ZakresMutacji, n: int, repository: Repository) -> list[dict[str, int | bool]]:
    """Wpis macierzy każdej z ``n`` części nocy: jej numer i ``przegladarka``, gdy testy jej mutacji sięgają Atrapy efenix,
    więc zadanie części instaluje Chromium jak zadanie pytest planu CI (``zakres_runu.potrzebuja_chromium``)."""

    wpisy: list[dict[str, int | bool]] = []
    for czesc in Czesc.calosc(n):
        sciezki = {mutant.path for mutant in noc.czesc(czesc)}
        testy = [test for dotkniete in mutacje_zmiany.tests_of(repository, sciezki).values() for test in dotkniete]
        wpisy.append({"czesc": czesc.k, "przegladarka": bool(potrzebuja_chromium(testy, repository))})
    return wpisy


def zaplanuj(github: GitHub, od: str, zakres: Path | None) -> int:
    """Plan nocy: baza, koniec jej zakresu i macierz części w ``GITHUB_OUTPUT``, a z ``zakres`` plik artefaktu ``zakres-nocy``."""

    od_sha, skad = baza(github, ROOT, od, datetime.now(UTC))
    caly = mutacje_zmiany.ZakresMutacji.od(od_sha, ROOT)
    if caly.zly_wyjatek is not None:
        print(f"MUTACJE NOCNE | {caly.zly_wyjatek}; część mutacji to zgłosi")
    do_sha = caly.najdalszy_koniec(NA_CZESC * CZESCI_NA_NOC)
    noc = caly.do(do_sha)
    wpisy = macierz(noc, noc.liczba_czesci(NA_CZESC), Repository.scan(ROOT))
    z_chromium = sum(bool(wpis["przegladarka"]) for wpis in wpisy)
    if zalegle := len(caly.mutanty) - len(noc.mutanty):
        print(f"MUTACJE NOCNE | zaległość: {zalegle} mutacji zmian po {do_sha} czeka na następne noce")
    print(f"MUTACJE NOCNE PLAN | baza {od_sha} ({skad}) | do {do_sha} | mutacje {noc.liczba_mutacji} | części {len(wpisy)} | z Chromium {z_chromium}")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(f"baza={od_sha}\ndo={do_sha}\nczesci={json.dumps(wpisy)}\nliczba={len(wpisy)}\n")
    if zakres is not None:
        zakres.parent.mkdir(parents=True, exist_ok=True)
        zakres.write_text(json.dumps({"baza": od_sha, "do": do_sha}), encoding="utf-8")
    return 0


# --- zgłoszenie ---


@dataclass(frozen=True)
class Przezyta:
    """Przeżyta mutacja z zapisu części, a z ``bez_werdyktu`` mutacja, której część nie dała werdyktu przed limitem
    czasu: plik, linia i opis jej nazwy, zmienione linie, które psuje, i jej klucz."""

    plik: str
    linia: int
    opis: str
    linie: tuple[int, ...]
    klucz: str
    bez_werdyktu: bool = False

    @classmethod
    def z_zapisu(cls, wpis: dict[str, Any], *, bez_werdyktu: bool = False) -> Przezyta:
        """Wpis ``mutacje_zmiany.entry``; wpis bez któregoś pola to ``ValueError``."""

        try:
            return cls(str(wpis["plik"]), int(wpis["linia"]), str(wpis["opis"]), tuple(wpis["linie"]), str(wpis["klucz"]), bez_werdyktu)
        except KeyError as blad:
            raise ValueError(f"wpis mutacji bez pola {blad}: {wpis}") from None

    @property
    def w_issue(self) -> str:
        """Linia ``MUTACJA`` issue: nazwa jak w ``NIEWYKRYTA`` i klucz, po którym noc nie zgłasza jej drugi raz."""

        return f"MUTACJA {self.plik}:{self.linia} {self.opis} | klucz {self.klucz}{BEZ_WERDYKTU if self.bez_werdyktu else ''}"


def zapisy(katalog: Path, liczba: int) -> tuple[list[Przezyta], list[str]]:
    """Przeżyte mutacje i mutacje bez werdyktu wszystkich części oraz przyczyny porażki części, które nie dały wyniku.

    Część, której limit czasu minął po pokryciu (kod 3 ``tools/mutacje_zmiany.py``), dała wynik: jej mutacje bez werdyktu
    idą do issue jak przeżyte, więc nie zatrzymują bazy nocy."""

    przezyte: list[Przezyta] = []
    problemy: list[str] = []
    for numer in range(1, liczba + 1):
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT}{numer}" / ZAPIS).read_text(encoding="utf-8"))
            # Część, której limit czasu minął przed werdyktem części mutacji, też zapisuje przeżyte z reszty.
            czesci = [Przezyta.z_zapisu(wpis) for wpis in zapis.get("przezyte") or []]
            czesci += [Przezyta.z_zapisu(wpis, bez_werdyktu=True) for wpis in zapis.get("bez_werdyktu") or []]
        except (OSError, ValueError) as blad:
            problemy.append(f"część {numer}/{liczba} bez zapisu: {blad}")
            continue
        przezyte += czesci
        if zapis.get("kod") not in mutacje_zmiany.KODY_Z_WYNIKIEM:
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


def akcje(github: GitHub, przypisane: dict[Autor, list[Przezyta]], run: str) -> list[Akcja]:
    """Nowe issue dla PR bez issue, a komentarz z nowymi mutacjami dla PR, którego issue nie ma jeszcze ich kluczy."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in issues(github, ETYKIETY[1], "all"):
        istniejace.setdefault(znalezione["title"], znalezione)
    wynik: list[Akcja] = []
    for kto, mutacje in przypisane.items():
        linie = [mutacja.w_issue for mutacja in mutacje]
        issue = istniejace.get(kto.tytul)
        if issue is None:
            tresc = [
                f"Nocne mutacje `main` ([run]({run})) przeżyły testy na liniach, które ostatnio zmienił {kto.nazwa}:",
                "",
                *blok_kodu(linie),
                "",
                "Dla każdej linii `MUTACJA` dodaj test, który zabija tę mutację (dowód: `tools/mutacje.py`), albo napisz w komentarzu "
                "`MUTACJA <plik>:<linia> <opis> | nie warto, bo <powód>`.",
                *_rada_bez_werdyktu(mutacje),
                "Gdy każda linia ma test albo powód, zamknij issue (ADR 0021).",
            ]
            wynik.append(Zaloz(kto.tytul, "\n".join(tresc), ETYKIETY))
            continue
        znane = "\n".join([issue.get("body") or "", *(komentarz["body"] or "" for komentarz in strony(github, f"{REPO}/issues/{issue['number']}/comments"))])
        klucze = {znalezione["klucz"] for znalezione in _KLUCZ.finditer(znane)}
        if nowe := [mutacja for mutacja in mutacje if mutacja.klucz not in klucze]:
            tresc = [f"Nowe przeżyte mutacje z [runu]({run}):", "", *blok_kodu([mutacja.w_issue for mutacja in nowe]), *_rada_bez_werdyktu(nowe)]
            wynik.append(_uzupelnij(issue, "\n".join(tresc)))
    return wynik


def _rada_bez_werdyktu(mutacje: Sequence[Przezyta]) -> list[str]:
    if not any(mutacja.bez_werdyktu for mutacja in mutacje):
        return []
    return [
        f"Linia z `{BEZ_WERDYKTU.removeprefix(' | ')}` to mutacja, której noc nie sprawdziła przed limitem czasu części: "
        "uruchom ją `tools/mutacje.py`, a gdy test już ją wykrywa, napisz w komentarzu `MUTACJA <plik>:<linia> <opis> | wykryta, <polecenie>`."
    ]


def _ma(tekst: str, linia: str) -> bool:
    return any(obecna.strip() == linia or obecna.strip().startswith(f"{linia} |") for obecna in tekst.splitlines())


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
        padly = [linia for linia in (f"SKRYPT {skrypt}" for skrypt in skrypty.padly) if not _ma(znane, linia)]
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

    return f"CZAS BLISKO LIMITU {ostrzezenie.script} | {ostrzezenie.name}"


def _linia_blisko(ostrzezenie: NearLimit) -> str:
    czesc = f" ({ZMIENNA_CZESCI}={ostrzezenie.part})" if ostrzezenie.part else ""
    return f"{_klucz_blisko(ostrzezenie)} | {ostrzezenie.seconds} s z limitu --limit-s {ostrzezenie.limit_s:g} s{czesc}"


def _uzupelnij(issue: dict[str, Any], tresc: str) -> Skomentuj:
    """Komentarz z nowymi liniami; zamknięte issue wraca otwarte z etykietą pracy dla agenta."""

    return Skomentuj(issue["number"], tresc, ETYKIETY[:1] if issue["state"] == "closed" else ())


def zglos(github: GitHub, root: Path, od: str, katalog: Path, liczba: int, run: str, plan_skilli: plan_runu.Plan | None = None) -> int:
    przezyte, problemy = zapisy(katalog, liczba)
    linie = wykonaj_akcje(github, akcje(github, przypisz(github, root, od, przezyte), run), PREFIKS)
    padly: list[str] = []
    blisko: list[tuple[str, NearLimit]] = []
    if plan_skilli is not None:
        padly, blisko, problemy_skilli = wyniki_skilli(plan_skilli, katalog)
        przypisane, bez_pr = przypisz_skrypty(github, root, od, padly, blisko)
        problemy += problemy_skilli + bez_pr
        linie += wykonaj_akcje(github, akcje_skryptow(github, przypisane, run), PREFIKS)
    print("\n".join(linie) or "MUTACJE NOCNE | nic nowego do zgłoszenia")
    if problemy:
        print(f"MUTACJE NOCNE FAIL | {'; '.join(problemy)}")
        return 1
    skille = "" if plan_skilli is None else f" | zadania skilli {len(plan_skilli.zadania)} | padło skryptów {len(padly)}"
    skille += f" | blisko limitu czasu {len(blisko)}" if blisko else ""
    bez_werdyktu = sum(mutacja.bez_werdyktu for mutacja in przezyte)
    werdykty = f"przeżyło {len(przezyte) - bez_werdyktu}" + (f" | bez werdyktu {bez_werdyktu}" if bez_werdyktu else "")
    print(f"MUTACJE NOCNE OK | części {liczba} | {werdykty}{skille}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Baza i koniec zakresu nocy, liczba mutacji i części (GITHUB_OUTPUT).")
    plan.add_argument("--od", default="", help="Commit, od którego liczyć zmiany, a spoza linii HEAD jego wspólny przodek z HEAD (domyślnie koniec zakresu ostatniego udanego runu albo 24 h wstecz).")
    plan.add_argument("--baza", help="To samo co --od, jak w innych narzędziach zmiany; obie z różnymi wartościami to błąd użycia.")
    plan.add_argument("--zakres", type=Path, help=f"Plik JSON z bazą i końcem zakresu nocy (artefakt {ARTEFAKT_ZAKRESU}, z którego następna noc bierze bazę).")
    zgloszenie = polecenia.add_parser("zglos", help="Issue dla przeżytych mutacji ze wszystkich części.")
    zgloszenie.add_argument("--baza", required=True, help="Baza nocy z planu.")
    zgloszenie.add_argument("--zapisy", type=Path, required=True, help=f"Katalog z podkatalogami artefaktów {ARTEFAKT}<k>.")
    zgloszenie.add_argument("--czesci", type=int, required=True, help="Liczba części z planu.")
    zgloszenie.add_argument("--run", required=True, help="URL runu workflow.")
    zgloszenie.add_argument("--plan-skilli", type=Path, help=f"Plan skryptów mutacji skilli nocy; ich zapisy w podkatalogach {ARTEFAKT_SKILLI}<id zadania>.")
    args = parser.parse_args(argv)
    try:
        if args.polecenie == "plan":
            if args.od and args.baza and args.od != args.baza:
                plan.error(f"dwie różne bazy: --od {args.od} i --baza {args.baza}")
            return zaplanuj(GhApi(), args.od or args.baza or "", args.zakres)
        plan_skilli = None if args.plan_skilli is None else plan_runu.Plan.z_json(args.plan_skilli.read_text(encoding="utf-8"))
        return zglos(GhApi(), ROOT, args.baza, args.zapisy, args.czesci, args.run, plan_skilli)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as blad:
        szczegol = blad.stderr.strip() if isinstance(blad, subprocess.CalledProcessError) else blad
        print(f"MUTACJE NOCNE FAIL | {szczegol}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
