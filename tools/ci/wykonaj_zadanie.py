"""Wykonuje jedno zadanie planu runu CI (``tools/lib/plan_runu.py``): pytest z jego plikami, potem kroki CI i kroki skilli.

Zadanie wykonuje tylko plan, którego treść zgadza się z jego ``digest``. Pytest biegnie z plikami i udziałami zadania:
udział k dużego pliku z ``-p tools.lib.pytest_czesc`` (testy pliku posortowane po id, po kolei), a krok skilla z częścią
``#k/n`` z tą częścią w ``jednostka.ZMIENNA_CZESCI``. Kroki skilli biegną po kolei, także po porażce, każdy w checkoucie
swojego skilla, z limitem ``LIMIT_S`` i echem wyjścia. Krok skilla z modelem kodu (``model/definicje.json``), którego
kod zmienił się od skrótów modelu (``tools/lib/rozjazd_modelu.py``), nie biegnie: pada z linią ``ROZJAZD MODELU Z KODEM``
i krokami naprawy, tak jak krok ``rozjazd modelu`` w ``tools/szybko.py``. Podstawa ``ci:`` przechodzi z kodem 0, a skrypt
mutacji kończy się linią ``MUTACJE OK``; ostrzeżenia ``CZAS BLISKO LIMITU`` z wyjścia skryptu (``tools/mutacje.py``) idą do zapisu
wykonania. Krok biegnie przez ``tools/lib/potomne.py``: jego procesy potomne giną po jego końcu i po limicie, a cały krok
ginie razem z zadaniem, choćby zabitym przez SIGKILL.

Na pull request zadanie po porażce pytest uruchamia raz same testy, które padły (``niestabilne_testy``, najwyżej
``PONOWIENIE_NAJWIECEJ``; więcej porażek to nie flaky test), jeśli id każdego da się zgłosić w issue. Gdy wszystkie
przejdą, pytest przechodzi, a każdy z nich trafia do zapisu flaky testów; druga porażka to porażka. Każde zadanie z pytest
zapisuje też wynik swoich testów z kwarantanny.
Krok pytest ma limit ``plan_runu.limit_pytest_s`` ze ściany zadania z planu: po nim drzewo pytest ginie, a linia
``LIMIT`` mówi, że to limit, nie porażka testu.

Zapis ``plan_runu.WYKONANIE`` ma wynik każdej jednostki i ostrzeżenia ``CZAS BLISKO LIMITU`` kroków skilli
(``blisko_limitu``), które noc zgłasza w issue PR-u (``tools/mutacje_nocne.py``). Kod 1, gdy coś padło.

Z ``--kroki-pushu`` (zadanie mutations ``tools/ci_lokalnie.py``) wykonuje tak samo jedno zadanie z każdym krokiem skilli
zakresu pushu (``tools/lib/zakres_runu.py``), bez planu i bez części, a FAIL znalezienia kroku (zgubiony skrypt
mutacji, zły klucz ``ci:`` albo ``ci-czesci:``) drukuje i liczy jako porażkę.

    python tools/ci/wykonaj_zadanie.py --plan .ci-plan/plan.json --zadanie windows-3.14-2       # albo mutacje-1
    python tools/ci/wykonaj_zadanie.py --kroki-pushu
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from kroki_skilli import Katalog, Step
import mutacje
import niestabilne_testy
from niestabilne_testy import FlakyTest, ZapisKwarantanny
import plan_runu
from plan_runu import Plan, Zadanie
import potomne
from repo import ROOT
import rozjazd_modelu
from zakres_runu import KROKI, MUTACJE, Krok, Zdarzenie, zakres

JUNIT = Path(".ci-czasy", "junit.xml")
PONOWIENIE = Path(".ci-czasy", "junit-ponowienie.xml")
# Flaky test trafia w jeden albo dwa testy (Skrzynka w runach 26.10); więcej porażek naraz to defekt albo awaria runnera.
PONOWIENIE_NAJWIECEJ = 5
CZESCI = Path(".ci-plan", "czesci.json")
# Najdłuższy skrypt mutacji trwał w CI na Windows 770 s; limit łapie zawieszenie, a nie wolny runner.
LIMIT_S = 30 * 60
KROKI_PUSHU = "kroki-skilli-pushu"


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


def _uruchom(root: Path, nazwa: str, polecenia: Sequence[tuple[tuple[str, ...], float]], po_limicie: str = "") -> dict[str, object]:
    """Polecenia po kolei w ``root`` do pierwszej porażki; wyjście na bieżąco, a drzewo procesów ginie z limitem z linią ``LIMIT``
    i dopiskiem ``po_limicie``."""

    print(f"== {nazwa}", flush=True)
    start, status = time.monotonic(), "ok"
    for polecenie, limit in polecenia:
        try:
            kod = potomne.run(polecenie, cwd=root, timeout=limit, echo=True).returncode
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


@dataclass(frozen=True)
class Wynik:
    """Powód porażki kroku skilla (``None``: przeszedł) i ostrzeżenia ``CZAS BLISKO LIMITU`` z wyjścia jego ``check_all``."""

    powod: str | None
    blisko_limitu: tuple[mutacje.NearLimit, ...] = ()


def run(step: Step, limit_s: float = LIMIT_S, env: Mapping[str, str] | None = None) -> Wynik:
    """Krok skilla z echem wyjścia i zmiennymi ``env`` w checkoucie jego skilla (``Step.root``); krok skilla, którego
    model rozjechał się z kodem, nie biegnie. Krok po limicie nie oddaje ostrzeżeń, bo jego wyjścia już nie ma."""

    if (step.skill / rozjazd_modelu.DEFINICJE).is_file() and (drift := rozjazd_modelu.rozjazd(step.skill, step.root)) is not None:
        print(f"{rozjazd_modelu.ROZJAZD} | {step.skill.name}: {drift}", flush=True)
        return Wynik(rozjazd_modelu.ROZJAZD)
    command = step.command
    try:
        done = potomne.run(
            [sys.executable, str(step.root / command[0]), *command[1:]],
            cwd=step.root,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
            timeout=limit_s,
            echo=True,
        )
    except subprocess.TimeoutExpired:
        return Wynik(f"przekroczył limit {limit_s:.0f} s")
    near = tuple(mutacje.near_limits(done))
    if done.returncode != 0:
        return Wynik(f"kod wyjścia {done.returncode}", near)
    if step.verdict is not None and [line.strip() for line in done.stdout.splitlines() if line.strip()][-1:] != [step.verdict]:
        return Wynik(f"brak końcowej linii {step.verdict}", near)
    return Wynik(None, near)


def _krok_skilla(klucz: Klucz, katalog: Katalog) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Krok skilla albo jego część ``#k/n``; wynik zgłasza pod kluczem całego kroku, jak udział pliku testów,
    a obok jego ostrzeżenia ``CZAS BLISKO LIMITU`` (``mutacje.NearLimit``) pod tym samym kluczem."""

    nazwa = str(klucz.zgloszony)
    print(f"== {klucz}", flush=True)
    start = time.monotonic()
    try:
        krok = katalog.krok(klucz)
    except KeyError:
        wynik = Wynik("planu nie ma wśród kroków skilli")
    else:
        wynik = run(krok, env={jednostka.ZMIENNA_CZESCI: str(klucz.czesc)} if klucz.czesc else None)
    s = round(time.monotonic() - start, 1)
    print(f"OK   {klucz} ({s:.0f} s)" if wynik.powod is None else f"FAIL {klucz} ({s:.0f} s): {wynik.powod}", flush=True)
    blisko = [ostrzezenie.record(nazwa) for ostrzezenie in wynik.blisko_limitu]
    return {"klucz": nazwa, "s": s, "status": "ok" if wynik.powod is None else "fail"}, blisko


def _krok_pytest(root: Path, plan: Plan, zadanie: Zadanie, pliki: Mapping[str, list[Czesc]]) -> dict[str, object]:
    start, limit = time.monotonic(), plan_runu.limit_pytest_s(zadanie)
    po_limicie = (
        f" ({plan_runu.ZAPAS_PYTEST:.0f} × ściana zadania {zadanie.sciana_s:.0f} s z planu, najmniej {plan_runu.LIMIT_PYTEST_MIN_S} s): to nie porażka testu, tylko"
        " test albo proces, który się zawiesił; test, który wisiał ponad faulthandler_timeout z pyproject.toml, zostawił wyżej"
        " stosy swoich wątków, a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia"
    )
    status = _uruchom(root, jednostka.krok("pytest"), [(_pytest(pliki), limit)], po_limicie)["status"]
    if status != "ok" and plan.zdarzenie is Zdarzenie.PULL_REQUEST and (testy := niestabilne_testy.padniete(JUNIT)):
        if len(testy) > PONOWIENIE_NAJWIECEJ:
            print(f"PONOWIENIE | bez ponowienia: padło {len(testy)} testów, a flaky testy to najwyżej {PONOWIENIE_NAJWIECEJ}", flush=True)
        elif obce := [test for test in testy if not niestabilne_testy.zgloszalny(test)]:
            print(f"PONOWIENIE | bez ponowienia: id testu, którego nie da się zgłosić w issue: {', '.join(obce)}", flush=True)
        elif _ponow(root, zadanie, testy):
            status = "ok"
    sha, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_kwarantanne(ZapisKwarantanny(zadanie.id, proba, sha, niestabilne_testy.wyniki_kwarantanny(JUNIT)))
    return {"klucz": jednostka.krok("pytest"), "s": round(time.monotonic() - start, 1), "status": status}


def _ponow(root: Path, zadanie: Zadanie, testy: Sequence[str]) -> bool:
    """Testy, które padły, raz jeszcze w jednym procesie; przejście każdego to flaky test w ``niestabilne_testy.FLAKY_TESTY``."""

    polecenie = (sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *testy, "--junitxml", str(PONOWIENIE))
    if _uruchom(root, "ponowienie", [(polecenie, plan_runu.PONOWIENIE_LIMIT_S)])["status"] != "ok" or not niestabilne_testy.po_ponowieniu(JUNIT, PONOWIENIE, testy):
        return False
    print(f"FLAKY TESTY | przeszły po ponowieniu: {', '.join(testy)}", flush=True)
    sha, run, proba = os.environ.get("GITHUB_SHA", ""), int(os.environ.get("GITHUB_RUN_ID", "0")), int(os.environ.get("GITHUB_RUN_ATTEMPT", "0"))
    niestabilne_testy.zapisz_flaky_testy([FlakyTest(test, zadanie.nazwa, sha, run, proba) for test in testy])
    return True


def wykonaj(plan: Plan, zadanie_id: str, bledy: Sequence[str] = (), *, root: Path = ROOT) -> int:
    """Jednostki zadania w checkoucie ``root``; ``bledy`` to nazwy kroków, których nie dało się znaleźć, a padają razem
    z jednostkami."""

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
    wyniki = [_krok_pytest(root, plan, zadanie, pliki)] if pliki else []
    wyniki += [_uruchom(root, jednostka.krok(krok.nazwa), _polecenia(krok)) for krok in kroki]
    blisko: list[dict[str, object]] = []
    if skille:
        # Po kolei: mutacje kilku skilli naraz na czterech rdzeniach runnera przekraczają swoje limity czasu.
        katalog = Katalog.skanuj(root)
        for klucz in skille:
            wynik, ostrzezenia = _krok_skilla(klucz, katalog)
            wyniki.append(wynik)
            blisko += ostrzezenia
    plan_runu.WYKONANIE.parent.mkdir(parents=True, exist_ok=True)
    zapis = {"plan": plan.digest, "zadanie": zadanie.id, "jednostki": wyniki, "blisko_limitu": blisko}
    plan_runu.WYKONANIE.write_text(json.dumps(zapis, indent=1), encoding="utf-8")
    padly = [*bledy, *(str(wynik["klucz"]) for wynik in wyniki if wynik["status"] != "ok")]
    print(f"WYKONANIE FAIL | {', '.join(padly)}" if padly else f"WYKONANIE OK | {zadanie.nazwa}")
    return 1 if padly else 0


def _kroki_pushu(root: Path) -> int:
    praca = zakres(Zdarzenie.PUSH, frozenset(), root)
    for nazwa, powod in praca.bledy:
        print(f"FAIL {nazwa}: {powod}", flush=True)
    klucze = tuple(jednostka.skill(wybrany.krok.key) for wybrany in praca.wybrane)
    plan = Plan(Zdarzenie.PUSH, 0.0, (), (Zadanie(KROKI_PUSHU, MUTACJE.nazwa, "kroki skilli pushu", klucze, 0.0),))
    return wykonaj(plan, KROKI_PUSHU, [nazwa for nazwa, _ in praca.bledy], root=root)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    jak = parser.add_mutually_exclusive_group(required=True)
    jak.add_argument("--plan", type=Path)
    jak.add_argument("--kroki-pushu", action="store_true", help="Każdy krok skilli zakresu pushu po kolei (tools/ci_lokalnie.py).")
    parser.add_argument("--zadanie")
    args = parser.parse_args(argv)
    if args.kroki_pushu:
        return _kroki_pushu(root)
    if args.zadanie is None:
        parser.error("--plan wymaga --zadanie")
    try:
        wczytany = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"WYKONANIE FAIL | plan {args.plan.as_posix()}: {error}")
        return 1
    return wykonaj(wczytany, args.zadanie, root=root)


if __name__ == "__main__":
    raise SystemExit(main())
