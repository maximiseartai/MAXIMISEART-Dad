"""Kształt bramki PR (ADR 0020): plan dwóch wzorcowych PR-ów mieści się w limicie testów, liczby zadań i prognozy ściany.

L to PR z samym plikiem testu (#416), C to zmiana Centrum (#461): ``src/``, frontend i drive skilla. Ich zmienione
ścieżki i czasy CI jednego runu ``main`` leżą zamrożone w ``tests/fixtures/ksztalt_bramki``, więc plan zmienia się
tylko z kodem planu i wyboru testów albo z grafem zależności testów repozytorium. Liczą się zadania runu bez Mutation
checks, a prognoza to najdłuższa ściana zadania z planu. Testy to pliki i węzły ``plik::test``,
które biegną na każdym torze: limit zadań C przepuszcza wszystkie pliki na dwóch torach, a limit testów nie.

Limit to wartość z HEAD PR, który wprowadził bramkę, plus 20%. Gdy test padnie, bramka urosła: najpierw znajdź
przyczynę (test, który zaczął zależeć od wszystkiego, wybór szerszy niż zmiana) i napraw ją w kodzie. Podniesienie
limitu to decyzja Maksa.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import czasy_ci  # noqa: E402
import plan_ci  # noqa: E402
from zakres_runu import Zdarzenie, zakres  # noqa: E402

PRZYPADKI = ROOT / "tests" / "fixtures" / "ksztalt_bramki"


@dataclass(frozen=True)
class Limit:
    testy: int
    zadania: int
    sciana_s: float


# Na HEAD bramki: L 27 testów, 5 zadań i 56,9 s, C 80 testów, 10 zadań i 219,2 s; wszystkie pliki to 118 testów.
# Cel ściany 90 s i limit 40 zadań runu PR (hillclimb CI 29.10, H5) dzielą C na więcej krótszych zadań: 21 zadań runu
# i 104,1 s (cel rośnie do 105 s, bo krok E2E na Windows się nie dzieli), więc limit zadań C to 25, a prognozy ściany
# 124,9 s (+20%). L się nie zmienia: 6 zadań i 58,5 s.
LIMITY = {"L": Limit(32, 6, 68.3), "C": Limit(96, 25, 124.9)}


@pytest.fixture(scope="module")
def czasy(tmp_path_factory: pytest.TempPathFactory) -> czasy_ci.Czasy:
    katalog = tmp_path_factory.mktemp("czasy-ci")
    for plik in (PRZYPADKI / "czasy-ci").glob("*.json"):
        shutil.copy2(plik, katalog / plik.name)
    (katalog / "pobrane").touch()
    zamrozone = czasy_ci.z_mainu(katalog, odswiez_po_s=math.inf)
    assert zamrozone.blad is None and zamrozone.runy
    return zamrozone


@pytest.mark.parametrize("przypadek", sorted(LIMITY))
def test_plan_bramki_wzorcowego_pr_miesci_sie_w_limicie_testow_zadan_i_prognozy_sciany(przypadek: str, czasy: czasy_ci.Czasy) -> None:
    zmiana = frozenset((PRZYPADKI / f"{przypadek}.txt").read_text(encoding="utf-8").split())
    praca = zakres(Zdarzenie.PULL_REQUEST, zmiana)
    plan = plan_ci.rozplanuj([plan_ci.wycen(tor, praca.pliki, czasy) for tor in praca.tory], Zdarzenie.PULL_REQUEST, czasy.runy)
    zadania = plan_ci.STALE_ZADANIA + len(plan.zadania)
    sciana = max(zadanie.sciana_s for zadanie in plan.zadania)
    limit = LIMITY[przypadek]

    assert (len(praca.pliki) <= limit.testy, zadania <= limit.zadania, sciana <= limit.sciana_s) == (True, True, True), (
        f"przypadek {przypadek}: {len(praca.pliki)} testów na torze (limit {limit.testy}), {zadania} zadań runu (limit {limit.zadania}),"
        f" prognoza ściany {sciana:.1f} s (limit {limit.sciana_s} s),"
        f" {praca.zrodlo}; podniesienie limitu to decyzja Maksa"
    )
