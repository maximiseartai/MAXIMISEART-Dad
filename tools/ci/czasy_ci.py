"""Czasy CI: ile trwała każda jednostka pracy zadań ``ci.yml``, zmierzone w runie, a nie wpisane ręcznie.

Zapis zadania. Zadania ``pytest`` i ``mutations`` kończą się poleceniem ``zadanie``, które zapisuje jeden plik JSON
(artefakt ``czasy-zadanie-<zadanie>-<indeks macierzy>-<próba>``, 7 dni), także gdy zadanie padło:

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
    krok:praca               ściana kroku, w którym ``tools/plan_ci.py wykonaj`` biegnie przez jednostki zadania
    skill:<skill>/ci         podstawa skilla w zadaniu Mutation checks
    skill:<skill>/<skrypt>   skrypt mutacji skilla; jego części z różnych zadań runu dają kilka obserwacji klucza

Status jednostki to ``ok`` albo ``fail``; pominięty krok i pominięty skrypt nie są jednostką. Czasy kroków i start zadania
podaje API zadań runu (``$GITHUB_API_URL/repos/<repo>/actions/runs/<run>/attempts/<próba>/jobs``, token z ``GH_TOKEN``,
z dokładnością do sekundy), w którym zadanie znajduje się po nazwie swojego runnera. Narzut to sekundy od startu zadania do startu pierwszego kroku jednostki.
Krok jednostki, który właśnie się skończył, API pokazuje przez chwilę bez wyniku (``conclusion: null``), więc zadanie
czyta API ponownie, do 5 odczytów co sekundę; krok wciąż bez wyniku to błąd, a nie krok pominięty. Jednostki, które
mierzy sam ``tools/plan_ci.py wykonaj`` (pytest, E2E, straż czasu, kroki skilli), i plan, z którego biegły (``plan`` to
jego ``digest``), zapis bierze z jego pliku ``--wykonanie``.

Scalenie. Na pushu do main ``Required CI status`` pobiera zapisy runu i poleceniem ``scal`` tworzy ``czasy-ci.json``
(artefakt ``czasy-ci``, 30 dni), jedyne źródło czasów CI:

    {"wersja": 1, "runy": [{"run": 40259456807, "proba": 1, "sha": "31bb7651...", "zdarzenie": "push"}],
     "tory": {"windows-3.14": {"narzut:pytest": [{"run": 40259456807, "proba": 1, "zadanie": "...", "s": 17.0, "status": "ok"}],
                               "pytest:tests/test_adr.py": [...]}}}

Obserwacje klucza idą po runie, próbie i zadaniu, więc te same zapisy dają ten sam plik bajt w bajt.

Wejście, którego brakuje albo którego nie da się odczytać, daje linię ``CZASY CI FAIL | ...`` i kod 1, a zapis powstaje
z reszty. Pomiar nie zmienia werdyktu CI: jego kroki w ``ci.yml`` mają ``continue-on-error``.

Odczyt. ``z_mainu`` daje ``Czasy`` z artefaktów ``czasy-ci`` ostatnich ``ILE_RUNOW`` zielonych runów ``ci.yml`` na main
(``gh``, w CI z ``GH_TOKEN``), które trzyma w katalogu: plan CI w świeżym katalogu runu, a ``tools/szybko.py``,
``tools/plan_ci.py`` i ``tools/scal_pr.py`` w ``katalog_checkoutu``, czyli ``.git/czasy-ci`` wspólnym dla worktree,
odświeżanym co ``ODSWIEZ_S``. Bez sieci, bez ``gh`` i bez artefaktu
``Czasy`` są puste, a ``blad`` mówi dlaczego: czytający waży wtedy pracę domyślnie, zamiast padać. Obserwacje
zadania z kilku prób runu liczą się z ostatniej.

    python tools/ci/czasy_ci.py zadanie --tor Windows-3.14.0 --junit junit.xml --wykonanie wykonanie.json --wyjscie zapis.json
    python3 tools/ci/czasy_ci.py scal --katalog zapisy --wyjscie czasy-ci.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Literal
import urllib.request
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import repo

WERSJA = 1
# Krok zadania, który właśnie się skończył, API pokazuje przez około sekundę bez wyniku (conclusion: null).
ODCZYTY_API = 5
CZEKANIE_API_S = 1.0
LIMIT_API_S = 20.0
Status = Literal["ok", "fail"]
# Kroki ci.yml, których czas jest jednostką; czasy kroków jednego klucza się sumują.
KROKI = {"Run the planned units": "krok:praca"}
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
    plan: str | None = None  # digest planu, z którego zadanie biegło (tools/plan_ci.py)
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
        """Koszt każdego zmierzonego pliku testów toru: ``praca`` jego klucza ``pytest:``."""

        return {klucz.removeprefix("pytest:"): s for klucz in self.tory.get(tor, {}) if klucz.startswith("pytest:") and (s := self.praca(tor, klucz)) is not None}

    def zadania(self, tor: str) -> list[dict[str, float]]:
        """Pomiary każdego zadania toru w każdym runie: klucz -> sekundy."""

        zadania: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
        for klucz, obserwacje in self.tory.get(tor, {}).items():
            for obserwacja in obserwacje:
                zadania[(obserwacja.run, obserwacja.zadanie)][klucz] = obserwacja.s
        return [zadania[zadanie] for zadanie in sorted(zadania)]


def _tor(runner: str) -> str:
    """``Windows-3.14.0`` → ``windows-3.14``."""

    system, _, wersja = runner.lower().partition("-")
    return f"{system}-{'.'.join(wersja.split('.')[:2])}"


def _junit(plik: Path) -> list[Jednostka]:
    try:
        korzen = ElementTree.parse(plik).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"to nie jest XML ({error})") from None
    sekundy: dict[str, float] = defaultdict(float)
    porazki = set()
    for test in korzen.iter("testcase"):
        nazwa, czas = test.get("file"), test.get("time")
        if nazwa is None or czas is None:
            raise ValueError(f"test {test.get('name')} bez atrybutu file albo time (pytest bez junit_family = xunit1)")
        nazwa = nazwa.replace("\\", "/")
        sekundy[nazwa] += float(czas)
        if test.find("failure") is not None or test.find("error") is not None:
            porazki.add(nazwa)
    if not sekundy:
        raise ValueError("brak testów")
    return [Jednostka(f"pytest:{nazwa}", round(s, 3), "fail" if nazwa in porazki else "ok") for nazwa, s in sorted(sekundy.items())]


def _wykonanie(plik: Path) -> tuple[str, str, list[Jednostka]]:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    return dane["plan"], dane["zadanie"], [Jednostka(**jednostka) for jednostka in dane["jednostki"]]


def _chwila(tekst: str) -> float:
    return datetime.fromisoformat(tekst).timestamp()


def _zadanie_z_api(runner: str) -> dict[str, Any]:
    adres = (
        f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        f"/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100"
    )
    prosba = urllib.request.Request(adres, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"})
    with urllib.request.urlopen(prosba, timeout=LIMIT_API_S) as odpowiedz:
        dane = json.load(odpowiedz)
    zadania: list[dict[str, Any]] = [zadanie for zadanie in dane["jobs"] if zadanie["runner_name"] == runner]
    if len(zadania) != 1:
        raise ValueError(f"{len(zadania)} zadań na runnerze {runner!r} zamiast jednego")
    return zadania[0]


def _kroki(runner: str) -> tuple[str, float | None, list[Jednostka]]:
    """Nazwa zadania, narzut i jednostki-kroki zadania na runnerze ``runner`` z API zadań tej próby runu."""

    for odczyt in range(ODCZYTY_API):
        zadanie = _zadanie_z_api(runner)
        bez_wyniku = [krok["name"] for krok in zadanie["steps"] if krok["name"] in KROKI and krok["conclusion"] is None]
        if not bez_wyniku:
            break
        if odczyt == ODCZYTY_API - 1:
            raise ValueError(f"kroki {bez_wyniku} bez wyniku w API po {ODCZYTY_API} odczytach")
        time.sleep(CZEKANIE_API_S)
    sekundy: dict[str, float] = defaultdict(float)
    porazki = set()
    pierwszy = None
    for krok in zadanie["steps"]:
        klucz = KROKI.get(krok["name"])
        if klucz is None or krok["conclusion"] not in ("success", "failure"):
            continue
        if pierwszy is None:
            pierwszy = _chwila(krok["started_at"])
        sekundy[klucz] += _chwila(krok["completed_at"]) - _chwila(krok["started_at"])
        if krok["conclusion"] == "failure":
            porazki.add(klucz)
    narzut = None if pierwszy is None else pierwszy - _chwila(zadanie["started_at"])
    jednostki = [Jednostka(klucz, s, "fail" if klucz in porazki else "ok") for klucz, s in sorted(sekundy.items())]
    return zadanie["name"], narzut, jednostki


def _zadanie(args: argparse.Namespace) -> int:
    bledy = []
    jednostki: list[Jednostka] = []
    nazwa, narzut = os.environ["GITHUB_JOB"], None
    try:
        nazwa, narzut, kroki = _kroki(os.environ["RUNNER_NAME"])
        jednostki += kroki
    except (OSError, ValueError, KeyError, TypeError) as error:
        bledy.append(f"API zadań runu: {error!r}")
    if args.junit:
        try:
            jednostki += _junit(args.junit)
        except (OSError, ValueError) as error:
            bledy.append(f"{args.junit.name}: {error!r}")
    plan = zadanie_planu = None
    if args.wykonanie:
        try:
            plan, zadanie_planu, wykonane = _wykonanie(args.wykonanie)
            jednostki += wykonane
        except (OSError, ValueError, KeyError, TypeError) as error:
            bledy.append(f"{args.wykonanie.name}: {error!r}")
    zapis = Zapis(
        run=int(os.environ["GITHUB_RUN_ID"]),
        proba=int(os.environ["GITHUB_RUN_ATTEMPT"]),
        szablon=os.environ["GITHUB_JOB"],
        zadanie=nazwa,
        tor=_tor(args.tor),
        zdarzenie=os.environ["GITHUB_EVENT_NAME"],
        sha=os.environ["GITHUB_SHA"],
        narzut_s=narzut,
        jednostki=tuple(jednostki),
        bledy=tuple(bledy),
        plan=plan,
        zadanie_planu=zadanie_planu,
    )
    args.wyjscie.parent.mkdir(parents=True, exist_ok=True)
    args.wyjscie.write_text(json.dumps({"wersja": WERSJA, **asdict(zapis)}, indent=1), encoding="utf-8")
    for blad in bledy:
        print(f"CZASY CI FAIL | {blad}")
    print(f"CZASY CI | {zapis.zadanie} | {zapis.tor} | {len(jednostki)} jednostek | narzut {'?' if narzut is None else f'{narzut:.0f}'} s | {args.wyjscie.name}")
    return 1 if bledy else 0


def wczytaj(plik: Path) -> Zapis:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    if dane.pop("wersja") != WERSJA:
        raise ValueError(f"wersja zapisu inna niż {WERSJA}")
    return Zapis(**{**dane, "jednostki": tuple(Jednostka(**jednostka) for jednostka in dane["jednostki"])})


def _scal(args: argparse.Namespace) -> int:
    bledy = []
    tory: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    runy = set()
    pliki = list(args.katalog.rglob("*.json"))
    for plik in pliki:
        try:
            zapis = wczytaj(plik)
        except (OSError, ValueError, KeyError, TypeError) as error:
            bledy.append(f"{plik.name}: {error!r}")
            continue
        runy.add((zapis.run, zapis.proba, zapis.sha, zapis.zdarzenie))
        narzut = () if zapis.narzut_s is None else (Jednostka(f"narzut:{zapis.szablon}", zapis.narzut_s, "ok"),)
        for jednostka in (*zapis.jednostki, *narzut):
            obserwacja = {"run": zapis.run, "proba": zapis.proba, "zadanie": zapis.zadanie, "s": jednostka.s, "status": jednostka.status}
            tory[zapis.tor][jednostka.klucz].append(obserwacja)
    if not pliki:
        bledy.append(f"brak zapisów zadań w {args.katalog}")
    for blad in bledy:
        print(f"CZASY CI FAIL | {blad}")
    if not runy:
        return 1
    czasy = {
        "wersja": WERSJA,
        "runy": [{"run": run, "proba": proba, "sha": sha, "zdarzenie": zdarzenie} for run, proba, sha, zdarzenie in sorted(runy)],
        "tory": {
            tor: {klucz: sorted(obserwacje, key=lambda o: (o["run"], o["proba"], o["zadanie"])) for klucz, obserwacje in sorted(klucze.items())}
            for tor, klucze in sorted(tory.items())
        },
    }
    args.wyjscie.write_text(json.dumps(czasy, indent=1), encoding="utf-8")
    for tor, klucze in sorted(tory.items()):
        pliki_testow = sum(klucz.startswith("pytest:") for klucz in klucze)
        print(f"CZASY CI | {tor} | {len(klucze)} kluczy, w tym {pliki_testow} plików testów")
    print(f"CZASY CI SCALONE | {len(pliki) - len(bledy)} zapisów zadań | {args.wyjscie.name}")
    return 1 if bledy else 0


def _gh(*argumenty: str) -> str:
    return subprocess.run(["gh", *argumenty], capture_output=True, text=True, encoding="utf-8", check=True, timeout=LIMIT_GH_S).stdout


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    zadanie = polecenia.add_parser("zadanie", help="Zapis czasów jednego zadania runu (w zadaniu CI).")
    zadanie.add_argument("--tor", required=True, help="System runnera i wersja Pythona, np. Windows-3.14.0.")
    zadanie.add_argument("--junit", type=Path, help="Junit pytest (junit_family = xunit1 w pyproject.toml).")
    zadanie.add_argument("--wykonanie", type=Path, help="Wynik tools/plan_ci.py wykonaj: jego jednostki i plan.")
    zadanie.add_argument("--wyjscie", type=Path, required=True)
    scal = polecenia.add_parser("scal", help="Scalenie zapisów zadań runu w czasy-ci.json (w Required na main).")
    scal.add_argument("--katalog", type=Path, required=True)
    scal.add_argument("--wyjscie", type=Path, required=True)
    args = parser.parse_args(argv)
    return _zadanie(args) if args.polecenie == "zadanie" else _scal(args)


if __name__ == "__main__":
    raise SystemExit(main())
