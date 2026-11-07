"""Czasy CI: ile trwała każda jednostka pracy zadań ``ci.yml``, zmierzone w runie, a nie wpisane ręcznie.

Zapis zadania (``Zapis``, ``wczytaj``). Każde zadanie ``pytest`` i ``mutations`` zapisuje jeden plik JSON
(``tools/ci/zapis_czasow.py zadanie``, artefakt ``czasy-zadanie-<zadanie>-<indeks macierzy>-<próba>``, 7 dni):

    {"wersja": 1, "run": 40259456807, "proba": 1, "szablon": "pytest", "zadanie": "pytest (Python 3.14, 1/4)",
     "tor": "windows-3.14", "zdarzenie": "push", "sha": "31bb7651...", "narzut_s": 17.0,
     "jednostki": [{"klucz": "pytest:tests/test_adr.py", "s": 0.412, "status": "ok"}, ...], "bledy": [],
     "plan": "9f2c...", "zadanie_planu": "windows-3.14-1"}

Tor to system runnera i jego Python (``windows-3.11``, ``windows-3.14``, ``linux-3.14``). Klucz jednostki nie zależy od
podziału na zadania, więc para tor i klucz wskazuje tę samą pracę w każdym runie:

    pytest:<plik testów>     suma czasów testów pliku, każdy setup + call + teardown (junit pytest, ``junit_family = "xunit1"``
                             w pyproject.toml); to nie ściana pliku, bo workery xdist biegną równolegle
    krok:pytest              ściana pytest zadania
    krok:e2e                 krok E2E (verify-rozliczenia --variant all)
    krok:timing              trzy polecenia straży czasu razem
    krok:praca               ściana kroku, w którym ``tools/ci/wykonaj_zadanie.py`` biegnie przez jednostki zadania
    skill:<skill>/ci         podstawa skilla w zadaniu Mutation checks
    skill:<skill>/<skrypt>   skrypt mutacji skilla; jego części z różnych zadań runu dają kilka obserwacji klucza

Status jednostki to ``ok`` albo ``fail``; pominięty krok i pominięty skrypt nie są jednostką. ``plan`` to ``digest``
planu, z którego zadanie biegło.

Scalenie. Na pushu do main ``Required CI status`` scala zapisy runu w ``czasy-ci.json`` (``tools/ci/zapis_czasow.py
scal``, artefakt ``czasy-ci``, 30 dni), jedyne źródło czasów CI:

    {"wersja": 1, "runy": [{"run": 40259456807, "proba": 1, "sha": "31bb7651...", "zdarzenie": "push"}],
     "tory": {"windows-3.14": {"narzut:pytest": [{"run": 40259456807, "proba": 1, "zadanie": "...", "s": 17.0, "status": "ok"}],
                               "pytest:tests/test_adr.py": [...]}}}

Obserwacje klucza idą po runie, próbie i zadaniu, więc te same zapisy dają ten sam plik bajt w bajt.

Odczyt. ``z_mainu`` daje ``Czasy`` z artefaktów ``czasy-ci`` ostatnich ``ILE_RUNOW`` zielonych runów ``ci.yml`` na main
(``gh``, w CI z ``GH_TOKEN``), które trzyma w katalogu: plan CI w świeżym katalogu runu, a ``tools/szybko.py``,
``tools/plan_ci.py`` i ``tools/scal_pr.py`` w ``katalog_checkoutu``, czyli ``.git/czasy-ci`` wspólnym dla worktree,
odświeżanym co ``ODSWIEZ_S``. Bez sieci, bez ``gh`` i bez artefaktu
``Czasy`` są puste, a ``blad`` mówi dlaczego: czytający waży wtedy pracę domyślnie, zamiast padać. Obserwacje
zadania z kilku prób runu liczą się z ostatniej. Moduł używa tylko biblioteki standardowej, bo plan CI i zapis czasów
biegną systemowym ``python3`` runnera.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from typing import Any, Literal

import github
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
# Tyle najnowszych artefaktów ``czasy-ci`` przegląda odczyt, szukając ``ILE_RUNOW`` z zielonych runów.
SZUKANE_ARTEFAKTY = 30
LIMIT_GH_S = 30.0


@dataclass(frozen=True)
class Jednostka:
    klucz: str
    s: float
    status: Status


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

    def pliki(self, tor: str) -> dict[str, float]:
        """Koszt każdego zmierzonego pliku testów toru: ``praca`` jego klucza rodzaju ``Rodzaj.PYTEST``."""

        return {
            Klucz.z_tekstu(klucz).nazwa: s
            for klucz in self.tory.get(tor, {})
            if jednostka.rodzaj(klucz) is Rodzaj.PYTEST and (s := self.praca(tor, klucz)) is not None
        }

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


def _gh(*argumenty: str) -> str:
    return github.gh(*argumenty, limit_s=LIMIT_GH_S)


def _pobierz(katalog: Path) -> None:
    """Artefakty ``czasy-ci`` ``ILE_RUNOW`` najnowszych zielonych runów main do ``<run>.json``; starsze usuwa.

    Zapytania idą równolegle, bo Plan CI czeka na nie na ścieżce krytycznej runu. Zielony run main ma swój artefakt, więc
    zielone runy wśród ``SZUKANE_ARTEFAKTY`` najnowszych artefaktów są wśród tylu najnowszych zielonych runów.
    """

    def pobierz(run: int) -> None:
        pobrany = katalog / f"{run}.pobieranie"
        shutil.rmtree(pobrany, ignore_errors=True)
        _gh("run", "download", str(run), "--name", ARTEFAKT, "--dir", str(pobrany))
        (pobrany / f"{ARTEFAKT}.json").replace(katalog / f"{run}.json")
        shutil.rmtree(pobrany)

    with ThreadPoolExecutor() as pula:
        zielone = pula.submit(_gh, "api", f"repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?branch=main&event=push&status=success&per_page={SZUKANE_ARTEFAKTY}", "--jq", ".workflow_runs[].id")
        artefakty = pula.submit(_gh, "api", f"repos/{{owner}}/{{repo}}/actions/artifacts?name={ARTEFAKT}&per_page={SZUKANE_ARTEFAKTY}", "--jq", ".artifacts[] | select(.expired | not) | .workflow_run.id")
        runy = sorted({int(run) for run in artefakty.result().split() if run in set(zielone.result().split())}, reverse=True)[:ILE_RUNOW]
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
                wybrane = [Obserwacja(o["run"], o["zadanie"], float(o["s"])) for o in obserwacje if o["proba"] == ostatnia[(tor, o["run"], o["zadanie"])]]
                tory[tor][klucz] = (*tory[tor].get(klucz, ()), *wybrane)
    return tory


def katalog_checkoutu(root: Path) -> Path:
    """Katalog ``czasy-ci`` w katalogu gita checkoutu ``root``, wspólny dla jego worktree: tu ``z_mainu`` trzyma artefakty
    poza CI."""

    return repo.common_dir(root) / ARTEFAKT


def z_mainu(katalog: Path, *, odswiez_po_s: float = 0) -> Czasy:
    """``Czasy`` z artefaktów w ``katalog``, który najpierw odświeża z GitHuba, gdy ostatnie udane pobranie jest starsze
    niż ``odswiez_po_s``. Błąd sieci, ``gh`` albo pliku nie przerywa: ``Czasy`` mają wtedy to, co się dało, i ``blad``,
    a następny odczyt próbuje pobrać znowu."""

    blad = None
    pobrane = katalog / "pobrane"
    if not pobrane.is_file() or time.time() - pobrane.stat().st_mtime >= odswiez_po_s:
        katalog.mkdir(parents=True, exist_ok=True)
        try:
            _pobierz(katalog)
            pobrane.touch()
        except (OSError, subprocess.SubprocessError) as error:
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
