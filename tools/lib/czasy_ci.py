"""Czasy CI: ile trwała każda jednostka pracy zadań ``ci.yml``, zmierzone w runie, a nie wpisane ręcznie.

Zapis zadania (``Zapis``, ``wczytaj``). Każde zadanie ``pytest`` i ``mutations`` zapisuje jeden plik JSON
(``tools/ci/zapis_czasow.py zadanie``, artefakt ``czasy-zadanie-<zadanie>-<indeks macierzy>-<próba>``, 7 dni):

    {"wersja": 1, "run": 43473166640, "proba": 1, "szablon": "pytest", "zadanie": "pytest (Python 3.13, 1/4)",
     "tor": "windows-3.13", "zdarzenie": "push", "sha": "c11a455d...", "narzut_s": 17.0,
     "jednostki": [{"klucz": "pytest:tests/test_adr.py", "s": 0.412, "status": "ok", "testy": 3}, ...], "bledy": [],
     "plan": "9f2c...", "zadanie_planu": "windows-3.13-1"}

Tor to system runnera i jego Python (``windows-3.13``, ``windows-3.14``, ``linux-3.14``). Klucz jednostki nie zależy od
podziału na zadania, więc para tor i klucz wskazuje tę samą pracę w każdym runie:

    pytest:<plik testów>     suma czasów testów pliku, każdy setup + call + teardown (junit pytest, ``junit_family = "xunit1"``
                             w pyproject.toml); to nie ściana pliku, bo workery xdist biegną równolegle
    krok:pytest              ściana pytest zadania
    krok:e2e                 krok E2E (verify-rozliczenia --variant all)
    krok:timing              trzy polecenia straży czasu razem
    krok:praca               ściana kroku, w którym ``tools/ci/wykonaj_zadanie.py`` biegnie przez jednostki zadania
    skill:<skill>/ci         podstawa skilla w zadaniu Mutation checks
    skill:<skill>/<skrypt>   skrypt mutacji skilla; jego części z różnych zadań runu dają kilka obserwacji klucza

Status jednostki to ``ok`` albo ``fail``; pominięty krok i pominięty skrypt nie są jednostką. ``testy`` ma tylko plik
testów: ile jego testów (``<testcase>``) jest w junit zadania. ``plan`` to ``digest`` planu, z którego zadanie biegło.

Scalenie. Na pushu do main ``Required CI status`` scala zapisy runu w ``czasy-ci.json`` (``tools/ci/zapis_czasow.py
scal``, artefakt ``czasy-ci``, 30 dni), jedyne źródło czasów CI:

    {"wersja": 1, "runy": [{"run": 43473166640, "proba": 1, "sha": "c11a455d...", "zdarzenie": "push"}],
     "tory": {"windows-3.13": {"narzut:pytest": [{"run": 43473166640, "proba": 1, "zadanie": "...", "s": 17.0, "status": "ok", "testy": null}],
                               "pytest:tests/test_adr.py": [...]}}}

Obserwacje klucza idą po runie, próbie i zadaniu, więc te same zapisy dają ten sam plik bajt w bajt.

Odczyt. ``z_mainu`` daje ``Czasy`` z artefaktów ``czasy-ci`` ostatnich ``ILE_RUNOW`` zielonych runów ``ci.yml`` na main
(``gh``, w CI z ``GH_TOKEN``), które trzyma w katalogu: plan CI w świeżym katalogu runu, a ``tools/plan_ci.py`` i
``lokalne`` w ``katalog_checkoutu``, czyli ``.git/czasy-ci`` wspólnym dla worktree, odświeżanym co ``ODSWIEZ_S``. Bez
sieci, bez ``gh`` i bez artefaktu ``Czasy`` są puste, a ``blad`` mówi dlaczego: czytający waży wtedy pracę domyślnie,
zamiast padać. Obserwacje zadania z kilku prób runu liczą się z ostatniej.

Liczba testów pliku (``Czasy.testy``) to najmniejsza z runów suma jego testów w zadaniach runu: plan CI nie dzieli pliku
na więcej udziałów, niż ma testów, bo udział bez testu nie zgłasza wyniku i czerwieni ``Required CI status``.
Plik, któremu PR usunął testy poniżej liczby jego udziałów, wciąż może dostać udział bez testu.

Koszt pliku testów (``KosztyPlikow``) to jego zmierzona praca, a pliku bez pomiaru mediana zmierzonych plików toru:
tak ważą pliki plan CI, ``tools/szybko.py`` i test scalenia ``tools/scal_pr.py``. Dwa ostatnie liczą pracę pytestu
na Macu agenta (``lokalne``): tor ``TOR_LOKALNY`` i ``workery_lokalne()`` workerów xdist. Moduł używa tylko biblioteki standardowej, bo plan CI i zapis czasów
biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any, Literal
import zipfile

from github import REPO, GhApi, GitHub
import jednostka
from jednostka import Klucz, Rodzaj
import repo

WERSJA = 1
Status = Literal["ok", "fail"]
ARTEFAKT = "czasy-ci"
ILE_RUNOW = 3
ODSWIEZ_S = 24 * 3600
# Tor, którego czasy ważą pracę na Macu agenta (Linux jak komputer agenta, nie Windows): budżet ``tools/szybko.py`` i
# limit testu scalenia ``tools/scal_pr.py``.
TOR_LOKALNY = "linux-3.14"
# Workery xdist pytestu na Macu agenta, chyba że ustawiono ``PYTEST_XDIST_AUTO_NUM_WORKERS``: gołe ``-n auto`` bierze
# wszystkie rdzenie Maca, na którym pracuje naraz kilku agentów.
WORKERY_LOKALNE = 4
# Tyle najnowszych artefaktów ``czasy-ci`` przegląda odczyt, szukając ``ILE_RUNOW`` z zielonych runów.
SZUKANE_ARTEFAKTY = 30
LIMIT_GH_S = 30.0
# GitHub odczytu czasów: repozytorium checkoutu, a każde zapytanie najwyżej ``LIMIT_GH_S``.
GITHUB = GhApi(limit_s=LIMIT_GH_S)
# Błędy pobrania, po których odczyt bierze kopię z katalogu: sieć i ``gh`` (``BladApi`` z ``GhApi``, limit czasu),
# odpowiedź API w innym kształcie i artefakt bez pliku.
_BLEDY_POBRANIA = (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError, TypeError, zipfile.BadZipFile)


def workery_lokalne() -> int:
    """Workery xdist kroku pytest na Macu agenta: ``PYTEST_XDIST_AUTO_NUM_WORKERS``, a bez niej ``WORKERY_LOKALNE``.
    Wartość, która nie jest liczbą (np. ``auto``), daje jak w pytest-xdist liczbę rdzeni, a liczba mniejsza od 1 to 1."""

    tekst = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS") or str(WORKERY_LOKALNE)
    try:
        return max(1, int(tekst))
    except ValueError:
        return os.cpu_count() or WORKERY_LOKALNE


@dataclass(frozen=True)
class Jednostka:
    klucz: str
    s: float
    status: Status
    testy: int | None = None  # testy pliku w junit zadania; inna jednostka ich nie ma


@dataclass(frozen=True)
class Zapis:
    run: int
    proba: int
    szablon: str  # id zadania w ci.yml
    zadanie: str  # nazwa zadania w runie
    tor: str
    zdarzenie: str
    sha: str
    narzut_s: float | None
    jednostki: tuple[Jednostka, ...]
    bledy: tuple[str, ...]
    plan: str | None = None  # digest planu, z którego zadanie biegło (tools/lib/plan_runu.py)
    zadanie_planu: str | None = None


@dataclass(frozen=True)
class Obserwacja:
    run: int
    zadanie: str
    s: float
    testy: int | None = None


@dataclass(frozen=True)
class KosztyPlikow:
    """Sekundy pracy plików testów toru."""

    zmierzone: Mapping[str, float]

    def typowy(self, bez_pomiarow: float = 0.0) -> float:
        return statistics.median(self.zmierzone.values()) if self.zmierzone else bez_pomiarow

    def s(self, plik: str, bez_pomiarow: float = 0.0) -> float:
        return self.zmierzone.get(plik, self.typowy(bez_pomiarow))


@dataclass(frozen=True)
class Czasy:
    """Pomiary ostatnich runów main: tor -> klucz -> obserwacje z ostatniej próby każdego zadania."""

    runy: tuple[int, ...]
    tory: Mapping[str, Mapping[str, tuple[Obserwacja, ...]]]
    blad: str | None = None

    def praca(self, tor: str, klucz: str) -> float | None:
        """Mediana po runach sumy klucza w runie: plik testów podzielony między zadania liczy się raz, cały."""

        w_runie: dict[int, float] = defaultdict(float)
        for obserwacja in self.tory.get(tor, {}).get(klucz, ()):
            w_runie[obserwacja.run] += obserwacja.s
        return statistics.median(w_runie.values()) if w_runie else None

    def testy(self, tor: str, klucz: str) -> int | None:
        """Najmniej testów pliku w runach, które je policzyły (suma zadań runu, bo udziały pliku biegną w kilku), albo
        ``None`` bez takiego runu: test dodany po starszym runie tylko zaniża liczbę, a usunięty liczy się od runu,
        który go już nie miał."""

        w_runie: dict[int, int] = defaultdict(int)
        for obserwacja in self.tory.get(tor, {}).get(klucz, ()):
            if obserwacja.testy is not None:
                w_runie[obserwacja.run] += obserwacja.testy
        return min(w_runie.values()) if w_runie else None

    def pliki(self, tor: str) -> dict[str, float]:
        return {
            Klucz.z_tekstu(klucz).nazwa: s
            for klucz in self.tory.get(tor, {})
            if jednostka.rodzaj(klucz) is Rodzaj.PYTEST and (s := self.praca(tor, klucz)) is not None
        }

    def koszty(self, tor: str) -> KosztyPlikow:
        return KosztyPlikow(self.pliki(tor))

    def zadania(self, tor: str) -> list[dict[str, float]]:
        """Pomiary każdego zadania toru w każdym runie: klucz -> sekundy."""

        zadania: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
        for klucz, obserwacje in self.tory.get(tor, {}).items():
            for obserwacja in obserwacje:
                zadania[(obserwacja.run, obserwacja.zadanie)][klucz] = obserwacja.s
        return [zadania[zadanie] for zadanie in sorted(zadania)]


def wczytaj(plik: Path) -> Zapis:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    if dane.pop("wersja") != WERSJA:
        raise ValueError(f"wersja zapisu inna niż {WERSJA}")
    return Zapis(**{**dane, "jednostki": tuple(Jednostka(**jednostka) for jednostka in dane["jednostki"])})


def _pobierz(katalog: Path, github: GitHub) -> None:
    """Artefakty ``czasy-ci`` ``ILE_RUNOW`` najnowszych zielonych runów main do ``<run>.json``; starsze usuwa.

    Zapytania idą równolegle, bo Plan CI czeka na nie na ścieżce krytycznej runu. Zielony run main ma swój artefakt, więc
    zielone runy wśród ``SZUKANE_ARTEFAKTY`` najnowszych artefaktów są wśród tylu najnowszych zielonych runów.
    """

    def pobierz(run: int) -> None:
        with zipfile.ZipFile(io.BytesIO(github.bajty(f"{REPO}/actions/artifacts/{artefakt_runu[run]}/zip"))) as archiwum:
            tresc = archiwum.read(f"{ARTEFAKT}.json")
        pobrany = katalog / f"{run}.json.pobieranie"
        pobrany.write_bytes(tresc)
        pobrany.replace(katalog / f"{run}.json")

    with ThreadPoolExecutor() as pula:
        zielone = pula.submit(github.json, f"{REPO}/actions/workflows/ci.yml/runs?branch=main&event=push&status=success&per_page={SZUKANE_ARTEFAKTY}")
        artefakty = pula.submit(github.json, f"{REPO}/actions/artifacts?name={ARTEFAKT}&per_page={SZUKANE_ARTEFAKTY}")
        id_zielonych = {int(run["id"]) for run in zielone.result()["workflow_runs"]}
        artefakt_runu = {
            run: int(artefakt["id"])
            for artefakt in artefakty.result()["artifacts"]
            if not artefakt["expired"] and (run := int(artefakt["workflow_run"]["id"])) in id_zielonych
        }
        runy = sorted(artefakt_runu, reverse=True)[:ILE_RUNOW]
        list(pula.map(pobierz, [run for run in runy if not (katalog / f"{run}.json").is_file()]))
    for plik in katalog.glob("*.json"):
        if plik.stem.isdigit() and int(plik.stem) not in runy:
            plik.unlink()


def _obserwacje(dokumenty: list[dict[str, Any]]) -> dict[str, dict[str, tuple[Obserwacja, ...]]]:
    ostatnia: dict[tuple[str, int, str], int] = {}
    for dokument in dokumenty:
        for tor, klucze in dokument["tory"].items():
            for obserwacje in klucze.values():
                for o in obserwacje:
                    miejsce = (tor, o["run"], o["zadanie"])
                    ostatnia[miejsce] = max(ostatnia.get(miejsce, 0), o["proba"])
    tory: dict[str, dict[str, tuple[Obserwacja, ...]]] = defaultdict(dict)
    for dokument in dokumenty:
        for tor, klucze in dokument["tory"].items():
            for klucz, obserwacje in klucze.items():
                wybrane = [Obserwacja(o["run"], o["zadanie"], float(o["s"]), o.get("testy")) for o in obserwacje if o["proba"] == ostatnia[(tor, o["run"], o["zadanie"])]]
                tory[tor][klucz] = (*tory[tor].get(klucz, ()), *wybrane)
    return tory


def katalog_checkoutu(root: Path) -> Path:
    """Katalog ``czasy-ci`` w katalogu gita checkoutu ``root``, wspólny dla jego worktree: tu ``z_mainu`` trzyma artefakty
    poza CI."""

    return repo.common_dir(root) / ARTEFAKT


def z_mainu(katalog: Path, *, odswiez_po_s: float = 0, github: GitHub = GITHUB) -> Czasy:
    """``Czasy`` z artefaktów w ``katalog``, który najpierw odświeża z ``github``, gdy ostatnie udane pobranie jest
    starsze niż ``odswiez_po_s``. Błąd sieci, ``gh`` albo pliku nie przerywa: ``Czasy`` mają wtedy to, co się dało, i
    ``blad``, a następny odczyt próbuje pobrać znowu."""

    blad = None
    pobrane = katalog / "pobrane"
    if not pobrane.is_file() or time.time() - pobrane.stat().st_mtime >= odswiez_po_s:
        katalog.mkdir(parents=True, exist_ok=True)
        try:
            _pobierz(katalog, github)
            pobrane.touch()
        except _BLEDY_POBRANIA as error:
            blad = f"pobranie {ARTEFAKT} z GitHuba: {getattr(error, 'stderr', None) or error}".strip()
    dokumenty = []
    for plik in sorted((plik for plik in katalog.glob("*.json") if plik.stem.isdigit()), key=lambda plik: int(plik.stem))[-ILE_RUNOW:]:
        try:
            dokumenty.append(json.loads(plik.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            blad = f"{plik.name}: {error}"
    try:
        tory = _obserwacje(dokumenty)
        runy = tuple(sorted({run["run"] for dokument in dokumenty for run in dokument["runy"]}))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return Czasy((), {}, f"{ARTEFAKT} w innym kształcie: {error!r}")
    if not dokumenty and blad is None:
        blad = f"brak artefaktu {ARTEFAKT} z zielonego runu main"
    return Czasy(runy, tory, blad)


def lokalne(root: Path) -> tuple[KosztyPlikow, str | None]:
    """Koszty plików testów toru ``TOR_LOKALNY`` z czasów main w ``katalog_checkoutu`` checkoutu ``root`` i przyczyna,
    gdy nie ma żadnego pomiaru (wtedy każdy plik waży 0)."""

    czasy = z_mainu(katalog_checkoutu(root), odswiez_po_s=ODSWIEZ_S)
    koszty = czasy.koszty(TOR_LOKALNY)
    if koszty.zmierzone:
        return koszty, None
    return koszty, czasy.blad or f"brak plików testów toru {TOR_LOKALNY} w {ARTEFAKT}"
