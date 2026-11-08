"""Wykonuje jedno zadanie planu runu CI (``tools/lib/plan_runu.py``): pytest z jego plikami, potem kroki CI i kroki skilli.

Zadanie wykonuje tylko plan, którego treść zgadza się z jego ``digest``. Pytest biegnie z plikami i udziałami zadania:
udział k dużego pliku z ``-p tools.lib.pytest_czesc`` (testy pliku posortowane po id, po kolei), a krok skilla z częścią
``#k/n`` z tą częścią w ``jednostka.ZMIENNA_CZESCI``. Kroki skilli biegną po kolei przez ``tools/ci/mutacje_skilli.py``
(``run``), także po porażce.

Na pull request zadanie po porażce pytest uruchamia raz same testy, które padły (``niestabilne_testy``, najwyżej
``PONOWIENIE_NAJWIECEJ``; więcej porażek to nie flaky test), jeśli id każdego da się zgłosić w issue. Gdy wszystkie
przejdą, pytest przechodzi, a każdy z nich trafia do zapisu flaky testów; druga porażka to porażka. Każde zadanie z pytest
zapisuje też wynik swoich testów z kwarantanny.
Krok pytest ma limit ``plan_runu.limit_pytest_s`` ze ściany zadania z planu: po nim drzewo pytest ginie, a linia
``LIMIT`` mówi, że to limit, nie porażka testu.

Zapis ``plan_runu.WYKONANIE`` ma wynik każdej jednostki i ostrzeżenia ``CZAS BLISKO LIMITU`` kroków skilli
(``blisko_limitu``), które noc zgłasza w issue PR-u (``tools/mutacje_nocne.py``). Kod 1, gdy coś padło.

    python tools/ci/wykonaj_zadanie.py --plan .ci-plan/plan.json --zadanie windows-3.14-2       # albo mutacje-1
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import jednostka
from jednostka import Czesc, Klucz, Rodzaj
from kroki_skilli import Katalog
import mutacje_skilli
import niestabilne_testy
from niestabilne_testy import FlakyTest, ZapisKwarantanny
import plan_runu
from plan_runu import Plan, Zadanie
import potomne
from repo import ROOT
from zakres_runu import KROKI, Krok, Zdarzenie

JUNIT = Path(".ci-czasy", "junit.xml")
PONOWIENIE = Path(".ci-czasy", "junit-ponowienie.xml")
# Flaky test trafia w jeden albo dwa testy (Skrzynka w runach 26.10); więcej porażek naraz to defekt albo awaria runnera.
PONOWIENIE_NAJWIECEJ = 5
CZESCI = Path(".ci-plan", "czesci.json")


def _pytest(pliki: Mapping[str, list[Czesc]]) -> tuple[str, ...]:
    czesci = {plik: {"n": udzialy[0].n, "udzialy": sorted(udzial.k for udzial in udzialy)} for plik, udzialy in pliki.items() if udzialy}
    CZESCI.parent.mkdir(parents=True, exist_ok=True)
    CZESCI.write_text(json.dumps(czesci, indent=1), encoding="utf-8")
    # Bez '=' w argumentach: shim py (cmd) dzieli argument na '='.
    return (sys.executable, "-m", "pytest", "-n", "auto", "-p", "tools.lib.pytest_czesc", "--czesci", str(CZESCI), *pliki, "--junitxml", str(JUNIT))


def _polecenia(krok: Krok) -> list[tuple[tuple[str, ...], float]]:
    wartosci = {
        "{python}": sys.executable,
        "{temp}": os.environ.get("RUNNER_TEMP", tempfile.gettempdir()),
        "{podsumowanie}": os.environ.get("GITHUB_STEP_SUMMARY", os.devnull),
    }

    def wstaw(argument: str) -> str:
        for znacznik, wartosc in wartosci.items():
            argument = argument.replace(znacznik, wartosc)
        return argument

    return [(tuple(map(wstaw, polecenie.split())), limit) for polecenie, limit in zip(krok.polecenia, krok.limity_s, strict=True)]


def _uruchom(nazwa: str, polecenia: Sequence[tuple[tuple[str, ...], float]], po_limicie: str = "") -> dict[str, object]:
    """Polecenia po kolei do pierwszej porażki; wyjście na bieżąco, a drzewo procesów ginie z limitem z linią ``LIMIT``
    i dopiskiem ``po_limicie``."""

    print(f"== {nazwa}", flush=True)
    start, status = time.monotonic(), "ok"
    for polecenie, limit in polecenia:
        try:
            kod = potomne.run(polecenie, cwd=ROOT, timeout=limit, echo=True).returncode
        except subprocess.TimeoutExpired:
            program = " ".join(polecenie[1:3]) if polecenie[1] == "-m" else polecenie[1]
            print(f"LIMIT | {nazwa}: {program} przerwany po limicie {limit:.0f} s{po_limicie}", flush=True)
            kod = None
        if kod != 0:
            status = "fail"
            break
    s = round(time.monotonic() - start, 1)
    print(f"{'OK  ' if status == 'ok' else 'FAIL'} {nazwa} ({s:.0f} s)", flush=True)
    return {"klucz": nazwa, "s": s, "status": status}


def _krok_skilla(klucz: Klucz, katalog: Katalog) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Krok skilla albo jego część ``#k/n``; wynik zgłasza pod kluczem całego kroku, jak udział pliku testów,
    a obok jego ostrzeżenia ``CZAS BLISKO LIMITU`` (``mutacje.NearLimit``) pod tym samym kluczem."""

    nazwa = str(klucz.zgloszony)
    print(f"== {klucz}", flush=True)
    start = time.monotonic()
    try:
        krok = katalog.krok(klucz)
    except KeyError:
        wynik = mutacje_skilli.Wynik("planu nie ma wśród kroków skilli")
    else:
        wynik = mutacje_skilli.run(krok, env={jednostka.ZMIENNA_CZESCI: str(klucz.czesc)} if klucz.czesc else None)
    s = round(time.monotonic() - start, 1)
    print(f"OK   {klucz} ({s:.0f} s)" if wynik.powod is None else f"FAIL {klucz} ({s:.0f} s): {wynik.powod}", flush=True)
    blisko = [ostrzezenie.record(nazwa) for ostrzezenie in wynik.blisko_limitu]
    return {"klucz": nazwa, "s": s, "status": "ok" if wynik.powod is None else "fail"}, blisko


def _krok_pytest(plan: Plan, zadanie: Zadanie, pliki: Mapping[str, list[Czesc]]) -> dict[str, object]:
    """Pytest zadania z limitem ``plan_runu.limit_pytest_s``; na pull request po porażce raz same testy, które padły. Potem wynik
    testów z kwarantanny."""

    start, limit = time.monotonic(), plan_runu.limit_pytest_s(zadanie)
    # Linia limitu mówi, że krok przerwał limit, a nie porażka testu, i gdzie szukać miejsca zawieszenia.
    po_limicie = (
        f" ({plan_runu.ZAPAS_PYTEST:.0f} × ściana zadania {zadanie.sciana_s:.0f} s z planu, najmniej {plan_runu.LIMIT_PYTEST_MIN_S} s): to nie porażka testu, tylko"
        " test albo proces, który się zawiesił; test, który wisiał ponad faulthandler_timeout z pyproject.toml, zostawił wyżej"
        " stosy swoich wątków, a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia"
    )
    status = _uruchom(jednostka.krok("pytest"), [(_pytest(pliki), limit)], po_limicie)["status"]
    if status != "ok" and plan.zdarzenie is Zdarzenie.PULL_REQUEST and (testy := niestabilne_testy.padniete(JUNIT)):
        if len(testy) > PONOWIENIE_NAJWIECEJ:
            print(f"PONOWIENIE | bez ponowienia: padło {len(testy)} testów, a flaky testy to najwyżej {PONOWIENIE_NAJWIECEJ}", flush=True)
        elif obce := [test for test in testy if not niestabilne_testy.zgloszalny(test)]:
            print(f"PONOWIENIE | bez ponowienia: id testu, którego nie da się zgłosić w issue: {', '.join(obce)}", flush=True)
        elif _ponow(zadanie, testy):
            status = "ok"
    sha, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_kwarantanne(ZapisKwarantanny(zadanie.id, proba, sha, niestabilne_testy.wyniki_kwarantanny(JUNIT)))
    return {"klucz": jednostka.krok("pytest"), "s": round(time.monotonic() - start, 1), "status": status}


def _ponow(zadanie: Zadanie, testy: Sequence[str]) -> bool:
    """Testy, które padły, raz jeszcze w jednym procesie; przejście każdego to flaky test w ``niestabilne_testy.FLAKY_TESTY``."""

    polecenie = (sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *testy, "--junitxml", str(PONOWIENIE))
    if _uruchom("ponowienie", [(polecenie, plan_runu.PONOWIENIE_LIMIT_S)])["status"] != "ok" or not niestabilne_testy.po_ponowieniu(JUNIT, PONOWIENIE, testy):
        return False
    print(f"FLAKY TESTY | przeszły po ponowieniu: {', '.join(testy)}", flush=True)
    sha, run, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ID", "0")), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_flaky_testy([FlakyTest(test, zadanie.nazwa, sha, run, proba) for test in testy])
    return True


def wykonaj(plan: Plan, zadanie_id: str) -> int:
    """Pytest z plikami i udziałami zadania, potem jego kroki CI i kroki skilli po kolei, także po porażce."""

    zadanie = next((z for z in plan.zadania if z.id == zadanie_id), None)
    if zadanie is None:
        print(f"WYKONANIE FAIL | plan {plan.digest[:12]} nie ma zadania {zadanie_id}")
        return 1
    pliki: dict[str, list[Czesc]] = defaultdict(list)
    kroki = []
    skille = []
    for klucz in zadanie.klucze:
        match klucz.rodzaj:
            case Rodzaj.PYTEST:
                pliki[klucz.nazwa] += [klucz.czesc] if klucz.czesc else []
            case Rodzaj.SKILL:
                skille.append(klucz)
            case Rodzaj.KROK | Rodzaj.NARZUT:
                kroki.append(KROKI[klucz.nazwa])
    wyniki = [_krok_pytest(plan, zadanie, pliki)] if pliki else []
    wyniki += [_uruchom(jednostka.krok(krok.nazwa), _polecenia(krok)) for krok in kroki]
    blisko: list[dict[str, object]] = []
    if skille:
        # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
        katalog = Katalog.skanuj(ROOT)
        for klucz in skille:
            wynik, ostrzezenia = _krok_skilla(klucz, katalog)
            wyniki.append(wynik)
            blisko += ostrzezenia
    plan_runu.WYKONANIE.parent.mkdir(parents=True, exist_ok=True)
    zapis = {"plan": plan.digest, "zadanie": zadanie.id, "jednostki": wyniki, "blisko_limitu": blisko}
    plan_runu.WYKONANIE.write_text(json.dumps(zapis, indent=1), encoding="utf-8")
    padly = [str(wynik["klucz"]) for wynik in wyniki if wynik["status"] != "ok"]
    print(f"WYKONANIE FAIL | {', '.join(padly)}" if padly else f"WYKONANIE OK | {zadanie.nazwa}")
    return 1 if padly else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--zadanie", required=True)
    args = parser.parse_args(argv)
    try:
        wczytany = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"WYKONANIE FAIL | plan {args.plan.as_posix()}: {error}")
        return 1
    return wykonaj(wczytany, args.zadanie)


if __name__ == "__main__":
    raise SystemExit(main())
