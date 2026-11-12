"""Zapis czasów CI (``tools/lib/czasy_ci.py``): zapis jednego zadania runu i scalenie zapisów runu w ``czasy-ci.json``.

Zadania ``pytest`` i ``mutations`` kończą się poleceniem ``zadanie``, które zapisuje ``czasy_ci.Zapis``, także gdy
zadanie padło. Czasy kroków i start zadania podaje API zadań runu
(``$GITHUB_API_URL/repos/<repo>/actions/runs/<run>/attempts/<próba>/jobs``, token z ``GH_TOKEN``, z dokładnością do
sekundy), w którym zadanie znajduje się po nazwie swojego runnera. Narzut to sekundy od startu zadania do startu
pierwszego kroku jednostki. Krok jednostki, który właśnie się skończył, API pokazuje przez chwilę bez wyniku
(``conclusion: null``), więc zadanie czyta API ponownie, do 5 odczytów co sekundę; krok wciąż bez wyniku to błąd, a nie
krok pominięty. Jednostki, które mierzy sam ``tools/ci/wykonaj_zadanie.py`` (pytest, E2E, straż czasu, kroki skilli), i
plan, z którego biegły, zapis bierze z jego pliku ``--wykonanie``.

Na pushu do main ``Required CI status`` pobiera zapisy runu i poleceniem ``scal`` tworzy ``czasy-ci.json``.

Wejście, którego brakuje albo którego nie da się odczytać, daje linię ``CZASY CI FAIL | ...`` i kod 1, a zapis powstaje
z reszty. Pomiar nie zmienia werdyktu CI: jego kroki w ``ci.yml`` mają ``continue-on-error``.

    python tools/ci/zapis_czasow.py zadanie --tor Windows-3.14.0 --junit junit.xml --wykonanie wykonanie.json --wyjscie zapis.json
    python3 tools/ci/zapis_czasow.py scal --katalog zapisy --wyjscie czasy-ci.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from czasy_ci import WERSJA, Jednostka, Zapis, wczytaj
import jednostka
from jednostka import Rodzaj
import wyniki_testow

ODCZYTY_API = 5
CZEKANIE_API_S = 1.0
LIMIT_API_S = 20.0
# Kroki ci.yml, których czas jest jednostką; czasy kroków jednego klucza się sumują.
KROKI = {"Run the planned units": jednostka.krok("praca")}


def _tor(runner: str) -> str:
    """``Windows-3.14.0`` → ``windows-3.14``."""

    system, _, wersja = runner.lower().partition("-")
    return f"{system}-{'.'.join(wersja.split('.')[:2])}"


def _junit(plik: Path) -> list[Jednostka]:
    sekundy: dict[str, float] = defaultdict(float)
    liczba: dict[str, int] = defaultdict(int)
    porazki = set()
    for test in wyniki_testow.testy(plik):
        if test.plik is None or test.sekundy is None:
            raise ValueError(f"test {test.nazwa} bez atrybutu file albo time (pytest bez junit_family = xunit1)")
        sekundy[test.plik] += test.sekundy
        liczba[test.plik] += 1
        if test.wynik == "padł":
            porazki.add(test.plik)
    if not sekundy:
        raise ValueError("brak testów")
    return [Jednostka(jednostka.pytest(nazwa), round(s, 3), "fail" if nazwa in porazki else "ok", liczba[nazwa]) for nazwa, s in sorted(sekundy.items())]


def _wykonanie(plik: Path) -> tuple[str, str, list[Jednostka]]:
    dane = json.loads(plik.read_text(encoding="utf-8"))
    return dane["plan"], dane["zadanie"], [Jednostka(**wpis) for wpis in dane["jednostki"]]


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
        narzut = () if zapis.narzut_s is None else (Jednostka(jednostka.narzut(zapis.szablon), zapis.narzut_s, "ok"),)
        for praca in (*zapis.jednostki, *narzut):
            obserwacja = {"run": zapis.run, "proba": zapis.proba, "zadanie": zapis.zadanie, "s": praca.s, "status": praca.status, "testy": praca.testy}
            tory[zapis.tor][praca.klucz].append(obserwacja)
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
        pliki_testow = sum(jednostka.rodzaj(klucz) is Rodzaj.PYTEST for klucz in klucze)
        print(f"CZASY CI | {tor} | {len(klucze)} kluczy, w tym {pliki_testow} plików testów")
    print(f"CZASY CI SCALONE | {len(pliki) - len(bledy)} zapisów zadań | {args.wyjscie.name}")
    return 1 if bledy else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    zadanie = polecenia.add_parser("zadanie", help="Zapis czasów jednego zadania runu (w zadaniu CI).")
    zadanie.add_argument("--tor", required=True, help="System runnera i wersja Pythona, np. Windows-3.14.0.")
    zadanie.add_argument("--junit", type=Path, help="Junit pytest (junit_family = xunit1 w pyproject.toml).")
    zadanie.add_argument("--wykonanie", type=Path, help="Wynik tools/ci/wykonaj_zadanie.py: jego jednostki i plan.")
    zadanie.add_argument("--wyjscie", type=Path, required=True)
    scal = polecenia.add_parser("scal", help="Scalenie zapisów zadań runu w czasy-ci.json (w Required na main).")
    scal.add_argument("--katalog", type=Path, required=True)
    scal.add_argument("--wyjscie", type=Path, required=True)
    args = parser.parse_args(argv)
    return _zadanie(args) if args.polecenie == "zadanie" else _scal(args)


if __name__ == "__main__":
    raise SystemExit(main())
