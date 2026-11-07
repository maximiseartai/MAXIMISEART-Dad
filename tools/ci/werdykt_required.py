"""Required CI status: przepuszcza run, gdy każde zadanie i każda jednostka planu runu CI (``tools/lib/plan_runu.py``) przeszła.

Werdykt przyjmuje tylko zapisy czasów (``tools/lib/czasy_ci.py``) z planu o tym samym ``digest``. Przepuszcza run, gdy
każde zadanie przeszło, zadanie pominięte to tylko takie, któremu plan nie dał pracy, a każde zadanie planu zgłosiło w
ostatniej próbie każdą swoją jednostkę (plik testów, krok CI, krok skilla) bez porażki, a części każdej podzielonej
jednostki składają się na całość (każda z 1..n dokładnie raz). Plan, którego nie ma, i skrypt mutacji, który wybór
skilli zgubił albo zły klucz ``ci:`` (``bledy`` planu), są czerwonym werdyktem z przyczyną. Wyniki zadań podaje
zmienna ``NEEDS`` (``toJSON(needs)``).

    python3 tools/ci/werdykt_required.py --plan .ci-plan/plan.json --zapisy .ci-czasy/zapisy
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import czasy_ci
from plan_runu import Z_PLANU, Plan
from zakres_runu import MUTACJE, TORY


def werdykt(plan: Plan | None, wyniki_zadan: Mapping[str, str], zapisy: Sequence[czasy_ci.Zapis], *, brak_planu: str = "") -> list[str]:
    """Przyczyny czerwonego Required; pusta lista to zielony."""

    przyczyny = []
    if plan is None:
        przyczyny.append(f"plan CI: {brak_planu or 'brak planu'}; zadania pytest i Mutation checks nie miały pracy")
    uruchomione = {} if plan is None else {szablon: False for szablon in Z_PLANU}
    if plan is not None:
        tory = {tor.nazwa: tor.szablon for tor in (*TORY, MUTACJE)}
        uruchomione |= {tory[zadanie.tor]: True for zadanie in plan.zadania}
    for nazwa, wynik in wyniki_zadan.items():
        if wynik != "success" and not (wynik == "skipped" and uruchomione.get(nazwa) is False):
            przyczyny.append(f"{nazwa}={wynik}")
    if plan is None:
        return przyczyny
    przyczyny += [f"mutacje skilli: {blad}" for blad in plan.bledy]
    przyczyny += _niepelne_czesci(plan)
    ostatnie: dict[str, czasy_ci.Zapis] = {}
    for zapis in zapisy:
        if zapis.plan == plan.digest and zapis.zadanie_planu is not None:
            if zapis.zadanie_planu not in ostatnie or zapis.proba > ostatnie[zapis.zadanie_planu].proba:
                ostatnie[zapis.zadanie_planu] = zapis
    for zadanie in plan.zadania:
        if (ostatni := ostatnie.get(zadanie.id)) is None:
            przyczyny.append(f"{zadanie.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły")
            continue
        # Udział pliku i węzeł testu zapis czasów zgłasza jako cały plik (junit zna tylko plik testu).
        zaplanowane = {klucz.partition("#")[0].partition("::")[0] for klucz in zadanie.jednostki}
        if brak := sorted(zaplanowane - {jednostka.klucz for jednostka in ostatni.jednostki}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki bez wyniku: {', '.join(brak)}")
        # Druga linia obrony, gdyby zadanie z porażką skończyło się sukcesem.
        if padly := sorted(zaplanowane & {jednostka.klucz for jednostka in ostatni.jednostki if jednostka.status != "ok"}):
            przyczyny.append(f"{zadanie.nazwa}: jednostki z porażką: {', '.join(padly)}")
    return przyczyny


def _niepelne_czesci(plan: Plan) -> list[str]:
    """Jednostki podzielone w planie, których części ``#k/n`` z zadań jednego toru nie są dokładnie raz każdą z 1..n."""

    czesci: dict[tuple[str, str], list[str]] = defaultdict(list)
    for zadanie in plan.zadania:
        for klucz in zadanie.jednostki:
            nazwa, _, czesc = klucz.partition("#")
            if czesc:
                czesci[(zadanie.tor, nazwa)].append(czesc)
    przyczyny = []
    for (tor, nazwa), lista in sorted(czesci.items()):
        n = lista[0].partition("/")[2]
        calosc = [f"{k}/{n}" for k in range(1, int(n) + 1)] if n.isdigit() else []
        if sorted(lista) != sorted(calosc):
            przyczyny.append(f"plan CI: części {', '.join(sorted(lista))} jednostki {nazwa} na torze {tor} nie są całością 1..{n}")
    return przyczyny


def _werdykt(args: argparse.Namespace) -> int:
    plan, brak = None, ""
    try:
        plan = Plan.z_json(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        brak = f"{args.plan.as_posix()} nieczytelny ({error})"
    zapisy = []
    for sciezka in sorted(args.zapisy.rglob("*.json")) if args.zapisy.is_dir() else []:
        try:
            zapisy.append(czasy_ci.wczytaj(sciezka))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"CZASY CI FAIL | {sciezka.name}: {error!r}")
    wyniki = {zadanie: need["result"] for zadanie, need in json.loads(os.environ["NEEDS"]).items()}
    if przyczyny := werdykt(plan, wyniki, zapisy, brak_planu=brak):
        print("\n".join(f"REQUIRED FAIL | {przyczyna}" for przyczyna in przyczyny))
        return 1
    assert plan is not None
    jednostki = sum(len(zadanie.jednostki) for zadanie in plan.zadania)
    print(f"REQUIRED OK | {len(wyniki)} zadań, {len(plan.zadania)} zadań z planu {plan.digest[:12]}, {jednostki} jednostek")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--zapisy", type=Path, required=True)
    return _werdykt(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
